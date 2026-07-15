"""Postmarket scheduler job implementation."""
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)


def _use_multi_agent_decision() -> bool:
    """Return True if the current signal profile uses multi-agent aggregation."""
    from backend.config import active_signal_weights

    return active_signal_weights().use_multi_agent


def _recent_signal_returns(db, limit: int = 20) -> list[float]:
    """最近正向信号的次日收益，用于 kill switch 连亏检测。"""
    from backend.data.database import Price, Signal
    from backend.decision.signal_policy import entry_recommendations

    recent_signals = (
        db.query(Signal)
        .filter(Signal.recommendation.in_(entry_recommendations(include_legacy=True)))
        .order_by(Signal.date.desc())
        .limit(limit)
        .all()
    )
    returns = []
    for sig in reversed(recent_signals):
        sig_price = (
            db.query(Price.close)
            .filter(Price.asset_key == sig.asset_key, Price.date == sig.date)
            .first()
        )
        next_price = (
            db.query(Price.close)
            .filter(Price.asset_key == sig.asset_key, Price.date > sig.date)
            .order_by(Price.date.asc())
            .first()
        )
        if sig_price and next_price and sig_price[0]:
            returns.append((next_price[0] - sig_price[0]) / sig_price[0])
    return returns


def _run_kill_switch_checks(
    db,
    *,
    recent_signal_returns: Callable[..., list[float]] = _recent_signal_returns,
) -> None:
    """盘后自动安全检查：连亏 + 数据新鲜度。"""
    try:
        from backend.data.database import Price
        from backend.ops import kill_switch

        latest = db.query(Price.date).order_by(Price.date.desc()).first()
        state = kill_switch.run_all_checks(
            trade_returns=recent_signal_returns(db),
            latest_price_date=latest[0] if latest else None,
        )
        if state:
            logger.warning("🛑 kill switch 自动检查触发：%s", state.reason)
    except Exception as e:
        logger.error("kill_switch auto checks failed: %s", e)


def _build_regime(db, stocks):
    """阶段A: 一次性构建大盘+板块 regime（盘后所有股票共用）"""
    import pandas as pd

    from backend.analysis.timing.regime import market_regime
    from backend.data.database import Price

    # HS300 OHLC — 没有真实 high/low 时不合成，RSRS 保持中性。
    index_df = None

    # 板块扩散：用自选股池近30日价格
    sector_dfs = {}
    for s in stocks:
        prc = (db.query(Price.date, Price.close)
               .filter(Price.asset_key == s.asset_key)
               .order_by(Price.date.desc()).limit(40).all())
        if len(prc) >= 25:
            sector_dfs[s.asset_key or s.symbol] = pd.DataFrame(
                [(r.date, r.close) for r in reversed(prc)],
                columns=["date", "close"],
            ).set_index("date")

    return market_regime(index_df, sector_dfs)


def _load_postmarket_context(
    db,
    stocks,
    *,
    build_regime: Callable[..., Any] = _build_regime,
) -> dict:
    """Load cross-stock context once for the whole post-market batch."""
    from backend.config import settings

    regime = None
    if settings.regime_filter_enabled and any(stock.market == "CN" for stock in stocks):
        try:
            regime = build_regime(db, stocks)
            logger.info("regime: %s", regime.reason)
        except Exception as e:
            logger.warning("regime 构建失败: %s", e)

    long_term_labels = {}
    if settings.long_term_team_enabled:
        try:
            from backend.agents.long_term.storage import bulk_get_labels, get_active_label
            cn_symbols = [s.symbol for s in stocks if s.market == "CN"]
            long_term_labels = bulk_get_labels(cn_symbols, db) if cn_symbols else {}
            for stock in stocks:
                if stock.market == "CN":
                    continue
                label = get_active_label(stock.symbol, db, market=stock.market)
                if label is not None:
                    long_term_labels[stock.asset_key] = label
            logger.info("long_term labels loaded: %d/%d stocks", len(long_term_labels), len(stocks))
        except Exception as e:
            logger.warning("long_term labels 读取失败: %s", e)

    return {"regime": regime, "long_term_labels": long_term_labels}


def _postmarket_news_sentiment(stock, db) -> dict:
    from backend.analysis.sentiment import analyze_news
    from backend.config import settings
    from backend.data.news import (
        fetch_titles_ifind,
        fetch_titles_tavily,
        get_recent_news_items,
    )
    from backend.data.news_audit import audited_titles

    market = getattr(stock, "market", "CN")
    news_items = get_recent_news_items(stock.symbol, db, hours=24, market=market)
    titles, news_audits = audited_titles(news_items)
    db_title_count = len(titles)
    if settings.ifind_mcp_enabled and len(titles) < settings.tavily_supplement_threshold:
        ifind_titles = fetch_titles_ifind(stock.symbol, stock.name)
        if ifind_titles:
            titles = titles + ifind_titles
            logger.info("iFinD补充 %s: +%d条 (DB=%d条)",
                        stock.symbol, len(ifind_titles), db_title_count)
    if settings.tavily_api_key and len(titles) < settings.tavily_supplement_threshold:
        tavily_titles = fetch_titles_tavily(stock.symbol, stock.name)
        if tavily_titles:
            titles = titles + tavily_titles
            logger.info("Tavily补充 %s: +%d条 (DB=%d条)",
                        stock.symbol, len(tavily_titles), len(titles) - len(tavily_titles))

    sentiment_result = analyze_news(titles, symbol=stock.symbol, market=market)
    sentiment_result["news_audit"] = [
        {
            "title": audit.title,
            "score": audit.score,
            "usable": audit.usable,
            "risk_flags": audit.risk_flags,
            "source": audit.news.source,
            "url": audit.news.url,
        }
        for audit in news_audits[:10]
    ]
    return sentiment_result


def _should_record_memory_usage(context: dict) -> bool:
    if context.get("read_only") or context.get("memory_read_only"):
        return False
    if context.get("record_memory_usage") is False:
        return False
    return True


def _analyze_postmarket_stock(
    stock,
    db,
    context: dict,
    as_of_date: str | None = None,
    *,
    postmarket_news_sentiment: Callable[..., dict] = _postmarket_news_sentiment,
    use_multi_agent_decision: Callable[[], bool] = _use_multi_agent_decision,
) -> dict | None:
    from backend.analysis.qlib_engine import qlib_score
    from backend.analysis.technical import technical_score
    from backend.data.market import load_price_df
    from backend.decision.aggregator import aggregate, aggregate_v2
    from backend.memory.stock_memory import build_memory_context, list_stock_memories

    df = load_price_df(stock.symbol, db, days=200, market=stock.market)
    if as_of_date:
        df = df[df.index <= as_of_date]
    expected_session = context.get("expected_session")
    if context.get("require_fresh_close") and expected_session:
        # Providers may already expose an in-progress current-session daily bar.
        # Clip it before the exact-session gate so gray signals only see a
        # clock-confirmed close and never reject a valid prior close merely
        # because a later partial bar is present.
        df = df[df.index <= expected_session["date"]]
    if len(df) < 60:
        logger.warning("not enough data for %s (%d rows), skipping", stock.symbol, len(df))
        return None

    if context.get("require_fresh_close") and expected_session:
        latest_date = str(df.index[-1])
        if latest_date != expected_session["date"]:
            logger.warning(
                "fresh close gate rejected %s expected=%s actual=%s calendar=%s",
                stock.asset_key,
                expected_session["date"],
                latest_date,
                expected_session.get("calendar_source"),
            )
            return None

    tech = technical_score(df, market=stock.market, symbol=stock.symbol)
    close = tech["latest"]["close"]
    atr = tech["latest"]["atr14"] or 0.0
    date_str = df.index[-1]
    if stock.market == "CN":
        quant_result = qlib_score(df, symbol=stock.symbol, db=db)
    else:
        # The production ranker is A-share trained.  Cross-market reuse would
        # create false precision, so HK/US stay neutral until their own models
        # pass market-scoped replay and promotion gates.
        quant_result = {
            "score": 0.0,
            "model": f"{stock.market.lower()}_gray_neutral_quant_m67",
            "reason": "market_model_not_promoted",
        }
    sentiment_result = postmarket_news_sentiment(stock, db)
    if stock.market == "CN":
        memory_context = build_memory_context(
            db,
            symbol=stock.symbol,
            query=f"{stock.symbol} {stock.name}",
            task_type="postmarket_signal",
            record_usage=_should_record_memory_usage(context),
        )
        try:
            research_pointers = list_stock_memories(
                db,
                symbol=stock.symbol,
                memory_type="research_pointer",
                limit=5,
            )
        except Exception as exc:
            logger.warning("research pointer context unavailable %s: %s", stock.symbol, exc)
            research_pointers = []
    else:
        memory_context = {"text": "", "used_stock_memory_ids": [], "ai_memory_keys": []}
        research_pointers = []
    if research_pointers:
        sentiment_result["research_context"] = research_pointers
    reflection = memory_context.get("text", "")
    lt_label = (
        context["long_term_labels"].get(getattr(stock, "asset_key", None))
        or context["long_term_labels"].get(stock.symbol)
    )

    if stock.market == "CN" and use_multi_agent_decision():
        result = aggregate_v2(
            quant_result=quant_result,
            technical_result=tech,
            sentiment_result=sentiment_result,
            close=close,
            atr=atr,
            regime=context.get("regime"),
            reflection_context=reflection,
            long_term_label=lt_label,
        )
    else:
        result = aggregate(
            quant_score=quant_result["score"],
            technical_result=tech,
            sentiment_score=sentiment_result["sentiment"],
            close=close,
            atr=atr,
            sentiment_result=sentiment_result,
            reflection_context=reflection,
            long_term_label=lt_label,
            memory_context=memory_context,
        )
    from backend.decision.market_signal_policy import apply_market_signal_policy

    result = apply_market_signal_policy(
        result,
        market=stock.market,
        close=close,
        atr=atr,
    )
    result["data_timestamp"] = str(date_str)
    result["news_audit"] = sentiment_result.get("news_audit", [])
    return {
        "date": date_str,
        "result": result,
        "quant_result": quant_result,
        "technical_result": tech,
        "sentiment_result": sentiment_result,
    }


def _persist_postmarket_stock(stock, analysis: dict, db) -> None:
    from backend.config import settings
    from backend.decision.aggregator import save_signal
    from backend.decision.decision_memory import save_decision
    from backend.decision.memory_layered import save_decision_layered

    date_str = analysis["date"]
    result = analysis["result"]
    save_signal(stock.symbol, date_str, result, db, market=stock.market)
    if stock.market != "CN":
        return
    try:
        save_decision(stock.symbol, date_str, result)
    except Exception as exc:
        logger.warning("save_decision failed for %s %s (best-effort): %s", stock.symbol, date_str, exc)
    if settings.layered_memory_enabled:
        save_decision_layered(stock.symbol, date_str, result, db=db)

    try:
        from backend.decision.harness import review_latest_signal
        review_latest_signal(db, stock.symbol)
    except Exception as e:
        logger.warning("auto review failed %s: %s", stock.symbol, e)


def _maybe_send_postmarket_alert(stock, result: dict) -> bool:
    from backend.decision.market_policy import signal_scope_for

    if signal_scope_for(stock.market, stock.symbol) != "production":
        return False
    from backend.decision.signal_policy import should_send_signal_alert

    if not should_send_signal_alert(result["recommendation"]):
        return False
    from backend.notification.bark import send_signal_alert
    return send_signal_alert(
        symbol=stock.symbol,
        name=stock.name,
        recommendation=result["recommendation"],
        score=result["composite_score"],
        stop_loss=result["stop_loss"],
        take_profit=result["take_profit"],
        position_pct=result.get("position_pct"),
    )


def _open_position_weights(db) -> dict[str, float]:
    """Best-effort CN holding weights for PortfolioManager input."""
    from backend.data.database import Position, Price, Stock
    from backend.decision.market_policy import is_production_signal_market

    try:
        positions = (
            db.query(Position)
            .outerjoin(Stock, Stock.asset_key == Position.asset_key)
            .filter(Position.status == "open")
            .all()
        )
    except Exception as e:
        logger.warning("portfolio position load failed: %s", e)
        return {}

    values: dict[str, float] = {}
    for pos in positions:
        market = getattr(pos, "market", None)
        if not market:
            stock = db.query(Stock).filter(Stock.asset_key == pos.asset_key).first()
            market = getattr(stock, "market", None)
        if not is_production_signal_market(market):
            continue
        quantity = float(getattr(pos, "quantity", 0) or 0)
        if quantity <= 0:
            continue
        latest = None
        try:
            latest = (
                db.query(Price.close)
                .filter(Price.asset_key == pos.asset_key)
                .order_by(Price.date.desc())
                .first()
            )
        except Exception:
            latest = None
        close = float(latest[0]) if latest else float(getattr(pos, "avg_cost", 0) or 0)
        if close > 0:
            values[pos.symbol] = values.get(pos.symbol, 0.0) + quantity * close

    total_value = sum(values.values())
    if total_value <= 0:
        return {}
    scale = min(1.0, float(settings.max_total_equity_pct or 1.0))
    return {symbol: round(value / total_value * scale, 4) for symbol, value in values.items()}


def _apply_portfolio_decision(
    batch_items: list[tuple[Any, dict]],
    db,
    *,
    open_position_weights: Callable[..., dict[str, float]] = _open_position_weights,
) -> int:
    """Apply batch-level PortfolioManager targets to per-stock signal results."""
    if not batch_items:
        return 0

    from backend.agents.portfolio_manager import (
        PortfolioCandidate,
        decision_to_dict,
        manage,
    )

    production_items = [item for item in batch_items if getattr(item[0], "market", None) == "CN"]
    if not production_items:
        return 0
    current_weights = open_position_weights(db)
    candidates = []
    for stock, analysis in production_items:
        result = analysis["result"]
        current = current_weights.get(stock.symbol, 0.0)
        risk_position_pct = float(result.get("risk_position_pct", result.get("position_pct")) or 0.0)
        candidates.append(PortfolioCandidate(
            symbol=stock.symbol,
            sector=getattr(stock, "industry", None) or "未分类",
            composite_score=float(result.get("composite_score") or 0.0),
            recommendation=result.get("recommendation") or "观望",
            confidence=result.get("confidence") or "低",
            suggested_position_pct=risk_position_pct,
            is_existing=current > 0,
            current_position_pct=current,
        ))

    decision = manage(candidates)
    batch_decision = decision_to_dict(decision)
    by_symbol = {a["symbol"]: a for a in batch_decision["allocations"]}
    for stock, analysis in production_items:
        result = analysis["result"]
        allocation = by_symbol.get(stock.symbol)
        if allocation is None:
            continue
        risk_position_pct = float(result.get("risk_position_pct", result.get("position_pct")) or 0.0)
        result.setdefault("trader_position_pct", risk_position_pct)
        result["risk_position_pct"] = risk_position_pct
        result["position_pct"] = allocation["target_position_pct"]
        result["allocation_rationale"] = allocation["rationale"]
        result["portfolio_decision"] = {
            **allocation,
            "available_capital_pct": batch_decision["available_capital_pct"],
            "sector_usage": batch_decision["sector_usage"],
            "rejected": batch_decision["rejected"],
            "notes": batch_decision["notes"],
        }
    return len(by_symbol)


def load_universe_symbols(path: str | Path) -> list[str]:
    """Load symbols from a paper-trading universe JSON file."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("stocks", payload) if isinstance(payload, dict) else payload
    symbols: list[str] = []
    for row in rows:
        symbol = row.get("symbol") if isinstance(row, dict) else row
        if symbol:
            symbols.append(str(symbol).zfill(6))
    return symbols


def run_postmarket_batch(
    db,
    universe_symbols: list[str] | None = None,
    market: str | None = None,
    *,
    load_context: Callable[..., dict] = _load_postmarket_context,
    analyze_stock: Callable[..., dict | None] = _analyze_postmarket_stock,
    apply_portfolio_decision: Callable[..., int] = _apply_portfolio_decision,
    persist_stock: Callable[..., None] = _persist_postmarket_stock,
    send_alert: Callable[..., bool] = _maybe_send_postmarket_alert,
    run_kill_switch_checks: Callable[..., None] = _run_kill_switch_checks,
) -> dict:
    """Run post-market analysis for active stocks or an explicit universe."""
    from backend.data.database import Stock
    from backend.data.market_profiles import expected_completed_session, normalize_market
    from backend.decision.market_policy import is_signal_eligible_stock, signal_scope_for

    if universe_symbols is None:
        query = db.query(Stock).filter(Stock.active)
        if market is not None:
            market = normalize_market(market)
            if hasattr(Stock, "market"):
                query = query.filter(Stock.market == market)
        candidates = query.all()
    else:
        query = db.query(Stock).filter(Stock.symbol.in_(universe_symbols))
        if market is not None:
            market = normalize_market(market)
            query = query.filter(Stock.market == market)
        candidates = query.all()
    stocks = [stock for stock in candidates if is_signal_eligible_stock(stock)]
    context = load_context(db, stocks)
    if market in {"HK", "US"}:
        context["require_fresh_close"] = True
        context["expected_session"] = expected_completed_session(market)
    scopes = {
        getattr(stock, "asset_key", f"{stock.market}:{stock.symbol}"):
        signal_scope_for(stock.market, stock.symbol)
        for stock in stocks
    }
    stats: dict[str, Any] = {
        "market": market or "ALL",
        "stocks": len(stocks),
        "input_stocks": len(candidates),
        "market_skipped": len(candidates) - len(stocks),
        "universe_filter": len(universe_symbols) if universe_symbols is not None else 0,
        "processed": 0,
        "saved": 0,
        "skipped": 0,
        "errors": 0,
        "alerts": 0,
        "portfolio_allocated": 0,
        "production_stocks": sum(scope == "production" for scope in scopes.values()),
        "gray_stocks": sum(scope == "gray" for scope in scopes.values()),
        "fresh_close_required": market in {"HK", "US"},
    }
    batch_items: list[tuple[Any, dict]] = []
    for stock in stocks:
        try:
            analysis = analyze_stock(stock, db, context)
            if analysis is None:
                stats["skipped"] += 1
                continue
            batch_items.append((stock, analysis))
            stats["processed"] += 1
        except Exception as e:
            stats["errors"] += 1
            logger.error("postmarket failed %s: %s", stock.symbol, e)

    try:
        stats["portfolio_allocated"] = apply_portfolio_decision(batch_items, db)
    except Exception as e:
        logger.warning("portfolio manager batch decision failed: %s", e)

    for stock, analysis in batch_items:
        try:
            persist_stock(stock, analysis, db)
            result = analysis["result"]
            stats["saved"] += 1
            if send_alert(stock, result):
                stats["alerts"] += 1
            logger.info(
                "signal saved: %s %s %s(%.0f) quant=%.1f tech=%.1f sentiment=%.2f model=%s",
                stock.symbol,
                analysis["date"],
                result["recommendation"],
                result["composite_score"],
                analysis["quant_result"]["score"],
                analysis["technical_result"].get("score", 0),
                analysis["sentiment_result"]["sentiment"],
                analysis["quant_result"].get("model", "?"),
            )
        except Exception as e:
            stats["errors"] += 1
            logger.error("postmarket failed %s: %s", stock.symbol, e)
    logger.info("post-market done: %d stocks processed", stats["processed"])
    if market in {None, "CN"} or any(stock.market == "CN" for stock in stocks):
        run_kill_switch_checks(db)
    return stats
