"""定时任务：盘前更新数据，盘后生成信号"""
import logging
from copy import deepcopy
from datetime import UTC, datetime
from functools import wraps
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.config import settings

logger = logging.getLogger(__name__)

# BackgroundScheduler 在独立线程运行，不阻塞 FastAPI event loop
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

JOB_STATE: dict[str, dict] = {}



def reset_job_state() -> None:
    """Reset in-memory scheduler state. Primarily used by tests."""
    JOB_STATE.clear()


def _state_for(job_name: str) -> dict:
    return JOB_STATE.setdefault(job_name, {
        "job": job_name,
        "running": False,
        "last_status": "never_run",
        "last_started_at": None,
        "last_finished_at": None,
        "last_duration_seconds": None,
        "last_result": None,
        "last_error": None,
        "success_count": 0,
        "error_count": 0,
    })


def get_scheduler_state() -> dict:
    """Return a JSON-serializable snapshot of scheduler runtime state."""
    return {
        "running": bool(getattr(scheduler, "running", False)),
        "jobs": deepcopy(JOB_STATE),
    }


def run_tracked_job(job_name: str, fn):
    """Run a job and record start/end/error metadata."""
    state = _state_for(job_name)
    started = datetime.now(UTC)
    state.update({
        "running": True,
        "last_status": "running",
        "last_started_at": started.isoformat(),
        "last_finished_at": None,
        "last_duration_seconds": None,
        "last_error": None,
    })
    try:
        result = fn()
        finished = datetime.now(UTC)
        state.update({
            "running": False,
            "last_status": "success",
            "last_finished_at": finished.isoformat(),
            "last_duration_seconds": round((finished - started).total_seconds(), 3),
            "last_result": result,
            "success_count": state.get("success_count", 0) + 1,
        })
        return result
    except Exception as exc:
        finished = datetime.now(UTC)
        state.update({
            "running": False,
            "last_status": "error",
            "last_finished_at": finished.isoformat(),
            "last_duration_seconds": round((finished - started).total_seconds(), 3),
            "last_error": str(exc),
            "error_count": state.get("error_count", 0) + 1,
        })
        raise


def tracked_job(job_name: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            return run_tracked_job(job_name, lambda: fn(*args, **kwargs))
        return wrapper
    return decorator


def _use_multi_agent_decision() -> bool:
    """Return True if the current signal profile uses multi-agent aggregation."""
    from backend.config import active_signal_weights

    return active_signal_weights().use_multi_agent


def _kill_switch_guard(job_name: str) -> bool:
    """job 入口防线：熔断态返回 True 表示应跳过。"""
    try:
        from backend.ops import kill_switch
        if kill_switch.is_active():
            state = kill_switch.current_state() or {}
            logger.warning("🛑 [%s] 熔断激活，跳过：%s", job_name, state.get("reason"))
            return True
    except Exception as e:
        logger.error("kill_switch check failed in %s: %s", job_name, e)
    return False


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
            .filter(Price.symbol == sig.symbol, Price.date == sig.date)
            .first()
        )
        next_price = (
            db.query(Price.close)
            .filter(Price.symbol == sig.symbol, Price.date > sig.date)
            .order_by(Price.date.asc())
            .first()
        )
        if sig_price and next_price and sig_price[0]:
            returns.append((next_price[0] - sig_price[0]) / sig_price[0])
    return returns


def _run_kill_switch_checks(db) -> None:
    """盘后自动安全检查：连亏 + 数据新鲜度。"""
    try:
        from backend.data.database import Price
        from backend.ops import kill_switch

        latest = db.query(Price.date).order_by(Price.date.desc()).first()
        state = kill_switch.run_all_checks(
            trade_returns=_recent_signal_returns(db),
            latest_price_date=latest[0] if latest else None,
        )
        if state:
            logger.warning("🛑 kill switch 自动检查触发：%s", state.reason)
    except Exception as e:
        logger.error("kill_switch auto checks failed: %s", e)


@tracked_job("premarket")
def job_premarket() -> None:
    """盘前任务：同步行情 + 个股新闻 + 沪深300指数"""
    if _kill_switch_guard("premarket"):
        return
    from backend.data.database import SessionLocal, Stock
    from backend.data.market import backfill_if_needed, sync_index_to_db
    from backend.data.news import fetch_stock_news_cn, save_news_to_db

    db = SessionLocal()
    try:
        stocks = db.query(Stock).filter(Stock.active).all()
        price_rows, news_rows = 0, 0

        for stock in stocks:
            # 行情回填
            try:
                price_rows += backfill_if_needed(stock.symbol, stock.market, db, refresh_today=True)
            except Exception as e:
                logger.error("backfill failed %s: %s", stock.symbol, e)

            # 个股新闻（仅A股，美股 Phase 7）
            if stock.market == "CN":
                try:
                    news = fetch_stock_news_cn(stock.symbol)
                    news_rows += save_news_to_db(news, db)
                except Exception as e:
                    logger.error("news fetch failed %s: %s", stock.symbol, e)

        try:
            sync_index_to_db(db)
        except Exception as e:
            logger.error("index sync failed: %s", e)

        logger.info("pre-market done: %d stocks, %d price rows, %d news items",
                    len(stocks), price_rows, news_rows)
    finally:
        db.close()


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
               .filter(Price.symbol == s.symbol)
               .order_by(Price.date.desc()).limit(40).all())
        if len(prc) >= 25:
            sector_dfs[s.symbol] = pd.DataFrame(
                [(r.date, r.close) for r in reversed(prc)],
                columns=["date", "close"],
            ).set_index("date")

    return market_regime(index_df, sector_dfs)


def _load_postmarket_context(db, stocks) -> dict:
    """Load cross-stock context once for the whole post-market batch."""
    from backend.config import settings

    regime = None
    if settings.regime_filter_enabled:
        try:
            regime = _build_regime(db, stocks)
            logger.info("regime: %s", regime.reason)
        except Exception as e:
            logger.warning("regime 构建失败: %s", e)

    long_term_labels = {}
    if settings.long_term_team_enabled:
        try:
            from backend.agents.long_term.storage import bulk_get_labels
            long_term_labels = bulk_get_labels([s.symbol for s in stocks], db)
            logger.info("long_term labels loaded: %d/%d", len(long_term_labels), len(stocks))
        except Exception as e:
            logger.warning("long_term labels 读取失败: %s", e)

    return {"regime": regime, "long_term_labels": long_term_labels}


def _postmarket_news_sentiment(stock, db) -> dict:
    from backend.analysis.sentiment import analyze_news
    from backend.config import settings
    from backend.data.news import (
        fetch_stock_news_anspire,
        fetch_titles_tavily,
        get_recent_news_items,
    )
    from backend.data.news_audit import audited_titles

    news_items = get_recent_news_items(stock.symbol, db, hours=24)
    titles, news_audits = audited_titles(news_items)
    db_title_count = len(titles)
    if len(titles) < settings.tavily_supplement_threshold:
        slots = settings.tavily_supplement_threshold - len(titles)
        limit = min(settings.anspire_news_max_add, max(0, slots))
        anspire_items = fetch_stock_news_anspire(stock.symbol, stock.name, limit=limit)
        if anspire_items:
            anspire_titles, anspire_audits = audited_titles(
                anspire_items,
                min_score=settings.anspire_news_min_score,
                limit=limit,
            )
            titles = titles + anspire_titles[:slots]
            news_audits = news_audits + anspire_audits
            logger.info("Anspire补充 %s: +%d条 (DB=%d条)",
                        stock.symbol, len(anspire_titles[:slots]), db_title_count)
    if settings.tavily_api_key:
        tavily_titles = fetch_titles_tavily(stock.symbol, stock.name)
        if tavily_titles:
            titles = titles + tavily_titles
            logger.info("Tavily补充 %s: +%d条 (DB=%d条)",
                        stock.symbol, len(tavily_titles), len(titles) - len(tavily_titles))

    sentiment_result = analyze_news(titles, symbol=stock.symbol)
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


def _analyze_postmarket_stock(stock, db, context: dict) -> dict | None:
    from backend.analysis.qlib_engine import qlib_score
    from backend.analysis.technical import technical_score
    from backend.data.market import load_price_df
    from backend.decision.aggregator import aggregate, aggregate_v2
    from backend.memory.stock_memory import build_memory_context

    df = load_price_df(stock.symbol, db, days=200)
    if len(df) < 60:
        logger.warning("not enough data for %s (%d rows), skipping", stock.symbol, len(df))
        return None

    tech = technical_score(df, market=stock.market, symbol=stock.symbol)
    close = tech["latest"]["close"]
    atr = tech["latest"]["atr14"] or 0.0
    date_str = df.index[-1]
    quant_result = qlib_score(df, symbol=stock.symbol, db=db)
    sentiment_result = _postmarket_news_sentiment(stock, db)
    memory_context = build_memory_context(
        db,
        symbol=stock.symbol,
        query=f"{stock.symbol} {stock.name}",
        task_type="postmarket_signal",
    )
    reflection = memory_context.get("text", "")
    lt_label = context["long_term_labels"].get(stock.symbol)

    if _use_multi_agent_decision():
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
        )
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
    save_signal(stock.symbol, date_str, result, db)
    save_decision(stock.symbol, date_str, result)
    if settings.layered_memory_enabled:
        save_decision_layered(stock.symbol, date_str, result, db=db)

    try:
        from backend.decision.harness import review_latest_signal
        review_latest_signal(db, stock.symbol)
    except Exception as e:
        logger.warning("auto review failed %s: %s", stock.symbol, e)


def _maybe_send_postmarket_alert(stock, result: dict) -> bool:
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
    """Best-effort current holding weights for PortfolioManager input."""
    from backend.data.database import Position, Price

    try:
        positions = db.query(Position).filter(Position.status == "open").all()
    except Exception as e:
        logger.warning("portfolio position load failed: %s", e)
        return {}

    values: dict[str, float] = {}
    for pos in positions:
        quantity = float(getattr(pos, "quantity", 0) or 0)
        if quantity <= 0:
            continue
        latest = None
        try:
            latest = (
                db.query(Price.close)
                .filter(Price.symbol == pos.symbol)
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


def _apply_portfolio_decision(batch_items: list[tuple[Any, dict]], db) -> int:
    """Apply batch-level PortfolioManager targets to per-stock signal results."""
    if not batch_items:
        return 0

    from backend.agents.portfolio_manager import (
        PortfolioCandidate,
        decision_to_dict,
        manage,
    )

    current_weights = _open_position_weights(db)
    candidates = []
    for stock, analysis in batch_items:
        result = analysis["result"]
        current = current_weights.get(stock.symbol, 0.0)
        candidates.append(PortfolioCandidate(
            symbol=stock.symbol,
            sector=getattr(stock, "industry", None) or "未分类",
            composite_score=float(result.get("composite_score") or 0.0),
            recommendation=result.get("recommendation") or "观望",
            confidence=result.get("confidence") or "低",
            suggested_position_pct=float(result.get("position_pct") or 0.0),
            is_existing=current > 0,
            current_position_pct=current,
        ))

    decision = manage(candidates)
    batch_decision = decision_to_dict(decision)
    by_symbol = {a["symbol"]: a for a in batch_decision["allocations"]}
    for stock, analysis in batch_items:
        result = analysis["result"]
        allocation = by_symbol.get(stock.symbol)
        if allocation is None:
            continue
        trader_position_pct = float(result.get("position_pct") or 0.0)
        result["trader_position_pct"] = trader_position_pct
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


def run_postmarket_batch(db) -> dict:
    """Run post-market analysis for active stocks and return batch stats."""
    from backend.data.database import Stock

    stocks = db.query(Stock).filter(Stock.active).all()
    context = _load_postmarket_context(db, stocks)
    stats = {
        "stocks": len(stocks),
        "processed": 0,
        "saved": 0,
        "skipped": 0,
        "errors": 0,
        "alerts": 0,
        "portfolio_allocated": 0,
    }
    batch_items: list[tuple[Any, dict]] = []
    for stock in stocks:
        try:
            analysis = _analyze_postmarket_stock(stock, db, context)
            if analysis is None:
                stats["skipped"] += 1
                continue
            batch_items.append((stock, analysis))
            stats["processed"] += 1
        except Exception as e:
            stats["errors"] += 1
            logger.error("postmarket failed %s: %s", stock.symbol, e)

    try:
        stats["portfolio_allocated"] = _apply_portfolio_decision(batch_items, db)
    except Exception as e:
        logger.warning("portfolio manager batch decision failed: %s", e)

    for stock, analysis in batch_items:
        try:
            _persist_postmarket_stock(stock, analysis, db)
            result = analysis["result"]
            stats["saved"] += 1
            if _maybe_send_postmarket_alert(stock, result):
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
    _run_kill_switch_checks(db)
    return stats


@tracked_job("postmarket")
def job_postmarket() -> dict:
    """盘后任务入口：量化 + 技术 + 情感 → 聚合 → 写 Signal 表。"""
    if _kill_switch_guard("postmarket"):
        return {"skipped": "kill_switch"}
    from backend.data.database import SessionLocal

    db = SessionLocal()
    try:
        return run_postmarket_batch(db)
    finally:
        db.close()

@tracked_job("stoploss_check")
def job_stoploss_check() -> None:
    """
    盘中止损预警（每天 14:30 运行）：
    取最近一次正向信号，比对当日最新价是否触及止损线，
    触及则发送 Bark 推送。
    """
    if _kill_switch_guard("stoploss_check"):
        return
    from backend.data.database import Price, SessionLocal, Signal, Stock
    from backend.decision.signal_policy import entry_recommendations
    from backend.notification.bark import send_stoploss_alert

    db = SessionLocal()
    try:
        stocks = db.query(Stock).filter(Stock.active).all()
        for stock in stocks:
            try:
                sig = (
                    db.query(Signal)
                    .filter(
                        Signal.symbol == stock.symbol,
                        Signal.recommendation.in_(entry_recommendations(include_legacy=True)),
                        Signal.stop_loss.isnot(None),
                    )
                    .order_by(Signal.date.desc())
                    .first()
                )
                if not sig:
                    continue

                latest_price = (
                    db.query(Price.close)
                    .filter(Price.symbol == stock.symbol)
                    .order_by(Price.date.desc())
                    .first()
                )
                if not latest_price:
                    continue

                current = float(latest_price[0])
                if sig.stop_loss is not None and current <= sig.stop_loss:
                    logger.warning("止损触发: %s 当前%.2f ≤ 止损%.2f (信号%s)",
                                   stock.symbol, current, sig.stop_loss, sig.date)
                    send_stoploss_alert(
                        symbol=stock.symbol,
                        name=stock.name,
                        current_price=current,
                        stop_loss=sig.stop_loss,
                        signal_date=sig.date,
                    )
            except Exception as e:
                logger.error("stoploss check failed %s: %s", stock.symbol, e)
    finally:
        db.close()


@tracked_job("train_model")
def job_train_model() -> None:
    """每周六重训 LightGBM Alpha 模型（数据不足时自动跳过）"""
    from backend.analysis.qlib_engine import train
    from backend.data.database import SessionLocal

    db = SessionLocal()
    try:
        ok = train(db)
        if ok:
            logger.info("weekly model training succeeded")
        else:
            logger.warning("weekly model training skipped (insufficient data)")
    except Exception as e:
        logger.error("weekly model training failed: %s", e)
    finally:
        db.close()


@tracked_job("weekly_longterm")
def job_weekly_longterm() -> None:
    """
    长期分析师团 first batch：每周日 11:00
    同步 industry + 5 年财报 → 跑 LongTermTeam → save_label
    """
    from backend.agents.long_term.storage import save_label
    from backend.agents.long_term.team import LongTermTeam
    from backend.data.database import SessionLocal, Stock
    from backend.data.fundamentals import (
        sync_disclosure_dates,
        sync_financial_metrics,
        sync_industry,
    )

    if not settings.long_term_team_enabled:
        logger.info("long_term team disabled, skipping weekly job")
        return

    db = SessionLocal()
    try:
        # 1. 同步基本面（industry 已有则跳过，财报幂等）
        try:
            n = sync_industry(db)
            logger.info("industry synced: %d updated", n)
        except Exception as e:
            logger.warning("sync_industry failed: %s", e)

        stocks = db.query(Stock).filter(Stock.active, Stock.market == "CN").all()
        for s in stocks:
            try:
                inserted = sync_financial_metrics(s.symbol, db, years=settings.financial_backfill_years)
                if inserted:
                    logger.info("financials %s: +%d rows", s.symbol, inserted)
            except Exception as e:
                logger.error("sync_financial_metrics %s failed: %s", s.symbol, e)

        try:
            n = sync_disclosure_dates(db, years=settings.financial_backfill_years)
            logger.info("disclosure dates synced: %d updated", n)
        except Exception as e:
            logger.warning("sync_disclosure_dates failed: %s", e)

        # 2. 跑团
        team = LongTermTeam()
        for s in stocks:
            try:
                label = team.run(s.symbol, s.name, db)
                save_label(label, db)
                logger.info("long-term %s = %s (score=%.0f)",
                            s.symbol, label.label, label.score)
            except Exception as e:
                logger.error("long-term team %s failed: %s", s.symbol, e)
    finally:
        db.close()


@tracked_job("weekly_long_term_reflect")
def job_weekly_long_term_reflect() -> dict:
    """Weekly long-term decision reflection into layered memory."""
    from backend.data.database import SessionLocal
    from backend.decision.memory_layered import weekly_long_term_reflect

    db = SessionLocal()
    try:
        reflection = weekly_long_term_reflect(db)
        return {"status": "ok", "reflection": reflection}
    finally:
        db.close()


@tracked_job("daily_memory_backup")
def job_daily_memory_backup() -> None:
    """Daily dump of ai_memory to ~/.stock-sage/memory/backups/ (M9.横向)."""
    from backend.data.database import SessionLocal
    from backend.memory.backup import run_daily_backup
    db = SessionLocal()
    try:
        path = run_daily_backup(db)
        logger.info("memory backup written: %s", path)
    except Exception as e:
        logger.error("memory backup failed: %s", e)
    finally:
        db.close()


@tracked_job("daily_memory_expire")
def job_daily_memory_expire() -> None:
    """Daily cleanup of expired memory rows and stock-memory outcomes."""
    from backend.data.database import SessionLocal
    from backend.memory.ai_memory import expire_stale_memories
    from backend.memory.audit_log import cleanup_audit_log
    from backend.memory.stock_memory import update_judgment_outcomes
    db = SessionLocal()
    try:
        removed = expire_stale_memories(db)
        if removed:
            logger.info("memory expire: removed %d stale rows", removed)
        outcomes = update_judgment_outcomes(db)
        if outcomes:
            logger.info("stock memory outcomes: wrote %d rows", outcomes)
        audit_removed = cleanup_audit_log(db)
        if audit_removed:
            logger.info("audit log cleanup: removed %d old rows", audit_removed)
    except Exception as e:
        logger.error("memory expire failed: %s", e)
    finally:
        db.close()


def start() -> None:
    """Register all cron jobs and start the background scheduler."""
    pre_h, pre_m = settings.schedule_premarket.split(":")
    post_h, post_m = settings.schedule_postmarket.split(":")
    long_mon_h, long_mon_m = settings.schedule_longterm_monday_time.split(":")
    long_fri_h, long_fri_m = settings.schedule_longterm_friday_time.split(":")
    reflect_h, reflect_m = settings.schedule_longterm_time.split(":")

    scheduler.add_job(job_premarket, CronTrigger(
        hour=int(pre_h), minute=int(pre_m), day_of_week="mon-fri",
    ), id="premarket", replace_existing=True)

    scheduler.add_job(job_postmarket, CronTrigger(
        hour=int(post_h), minute=int(post_m), day_of_week="mon-fri",
    ), id="postmarket", replace_existing=True)

    # 每周六 09:00 重训 LightGBM Alpha 模型
    scheduler.add_job(job_train_model, CronTrigger(
        hour=9, minute=0, day_of_week="sat",
    ), id="train_model", replace_existing=True)

    # 盘中止损预警 14:30（工作日）
    scheduler.add_job(job_stoploss_check, CronTrigger(
        hour=14, minute=30, day_of_week="mon-fri",
    ), id="stoploss_check", replace_existing=True)

    # 每日 00:30 备份 ai_memory（M9.横向）
    scheduler.add_job(job_daily_memory_backup, CronTrigger(
        hour=0, minute=30,
    ), id="daily_memory_backup", replace_existing=True)

    # 每日 01:00 清理过期 ai_memory（M9.3）
    scheduler.add_job(job_daily_memory_expire, CronTrigger(
        hour=1, minute=0,
    ), id="daily_memory_expire", replace_existing=True)

    # 长期分析师团：周一早盘前 + 周五收盘后复盘
    if settings.long_term_team_enabled:
        scheduler.add_job(job_weekly_longterm, CronTrigger(
            hour=int(long_mon_h), minute=int(long_mon_m), day_of_week=settings.schedule_longterm_monday_dow,
        ), id="weekly_longterm_monday", replace_existing=True)
        scheduler.add_job(job_weekly_longterm, CronTrigger(
            hour=int(long_fri_h), minute=int(long_fri_m), day_of_week=settings.schedule_longterm_friday_dow,
        ), id="weekly_longterm_friday", replace_existing=True)
        logger.info("long_term team scheduled: %s %s, %s %s",
                    settings.schedule_longterm_monday_dow,
                    settings.schedule_longterm_monday_time,
                    settings.schedule_longterm_friday_dow,
                    settings.schedule_longterm_friday_time)

    scheduler.add_job(job_weekly_long_term_reflect, CronTrigger(
        hour=int(reflect_h), minute=int(reflect_m), day_of_week=settings.schedule_longterm_dow,
    ), id="weekly_long_term_reflect", replace_existing=True)

    scheduler.start()
    logger.info("scheduler started (premarket=%s, postmarket=%s)",
                settings.schedule_premarket, settings.schedule_postmarket)


def stop() -> None:
    """Shut down the background scheduler without waiting for jobs to finish."""
    scheduler.shutdown(wait=False)
