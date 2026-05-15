"""定时任务：盘前更新数据，盘后生成信号"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from backend.config import settings

logger = logging.getLogger(__name__)

# BackgroundScheduler 在独立线程运行，不阻塞 FastAPI event loop
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


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
    from backend.data.database import Signal, Price
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


def job_premarket() -> None:
    """盘前任务：同步行情 + 个股新闻 + 沪深300指数"""
    if _kill_switch_guard("premarket"):
        return
    from backend.data.database import SessionLocal, Stock
    from backend.data.market import backfill_if_needed, sync_index_to_db
    from backend.data.news import fetch_stock_news_cn, save_news_to_db

    db = SessionLocal()
    try:
        stocks = db.query(Stock).filter(Stock.active == True).all()
        price_rows, news_rows = 0, 0

        for stock in stocks:
            # 行情回填
            try:
                price_rows += backfill_if_needed(stock.symbol, stock.market, db)
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


def _build_regime(db, stocks) -> dict:
    """阶段A: 一次性构建大盘+板块 regime（盘后所有股票共用）"""
    from backend.data.database import IndexPrice, Price
    from backend.analysis.timing.regime import market_regime
    import pandas as pd

    # HS300 OHLC — index_prices 只存 close，high/low 用 ±0.5% 估算
    rows = (db.query(IndexPrice.date, IndexPrice.close)
            .filter(IndexPrice.symbol == "sh000300")
            .order_by(IndexPrice.date.asc()).all())
    index_df = None
    if rows:
        df = pd.DataFrame(rows, columns=["date", "close"]).set_index("date")
        # 用 close ±0.5% 模拟 high/low（无 OHLC 时 RSRS 的退化估计）
        df["high"] = df["close"] * 1.005
        df["low"] = df["close"] * 0.995
        index_df = df

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


def job_postmarket() -> None:
    """盘后任务：量化 + 技术 + 情感 → 聚合 → 写 Signal 表 → 存决策记忆"""
    if _kill_switch_guard("postmarket"):
        return
    from backend.data.database import SessionLocal, Stock
    from backend.data.market import load_price_df
    from backend.data.news import get_recent_titles, fetch_titles_tavily
    from backend.analysis.technical import technical_score
    from backend.analysis.qlib_engine import qlib_score
    from backend.analysis.sentiment import analyze_news
    from backend.decision.aggregator import aggregate, aggregate_v2, save_signal
    from backend.decision.decision_memory import save_decision
    from backend.decision.memory_layered import save_decision_layered, get_layered_context
    from backend.decision.signal_policy import should_send_signal_alert
    from backend.config import settings

    db = SessionLocal()
    try:
        stocks = db.query(Stock).filter(Stock.active == True).all()

        # 阶段A: 大盘+板块 regime（所有股票共享）
        regime = None
        if settings.regime_filter_enabled:
            try:
                regime = _build_regime(db, stocks)
                logger.info("regime: %s", regime.reason)
            except Exception as e:
                logger.warning("regime 构建失败: %s", e)

        # 长期分析师团 label（一次性查所有自选股，可能为空）
        long_term_labels = {}
        if settings.long_term_team_enabled:
            try:
                from backend.agents.long_term.storage import bulk_get_labels
                long_term_labels = bulk_get_labels([s.symbol for s in stocks], db)
                logger.info("long_term labels loaded: %d/%d",
                            len(long_term_labels), len(stocks))
            except Exception as e:
                logger.warning("long_term labels 读取失败: %s", e)

        for stock in stocks:
            try:
                df = load_price_df(stock.symbol, db, days=200)
                if len(df) < 60:
                    logger.warning("not enough data for %s (%d rows), skipping", stock.symbol, len(df))
                    continue

                tech = technical_score(df, market=stock.market)
                close = tech["latest"]["close"]
                atr = tech["latest"]["atr14"] or 0.0
                date_str = df.index[-1]

                # 量化信号：LightGBM Alpha（未训练时退化为动量占位）
                quant_result = qlib_score(df)
                quant = quant_result["score"]

                # 情感信号：DB 24h内新闻 + Tavily实时补充（不足阈值时触发）
                titles = get_recent_titles(stock.symbol, db, hours=24)
                if len(titles) < settings.tavily_supplement_threshold:
                    tavily_titles = fetch_titles_tavily(stock.symbol, stock.name)
                    if tavily_titles:
                        titles = titles + tavily_titles
                        logger.info("Tavily补充 %s: +%d条 (DB=%d条)",
                                    stock.symbol, len(tavily_titles), len(titles) - len(tavily_titles))
                sentiment_result = analyze_news(titles, symbol=stock.symbol)

                reflection = get_layered_context(stock.symbol, db)
                lt_label = long_term_labels.get(stock.symbol)
                if _use_multi_agent_decision():
                    result = aggregate_v2(
                        quant_result=quant_result,
                        technical_result=tech,
                        sentiment_result=sentiment_result,
                        close=close,
                        atr=atr,
                        regime=regime,
                        reflection_context=reflection,
                        long_term_label=lt_label,
                    )
                else:
                    result = aggregate(
                        quant_score=quant,
                        technical_result=tech,
                        sentiment_score=sentiment_result["sentiment"],
                        close=close,
                        atr=atr,
                        sentiment_result=sentiment_result,
                        reflection_context=reflection,
                    )

                save_signal(stock.symbol, date_str, result, db)
                save_decision(stock.symbol, date_str, result)
                if settings.layered_memory_enabled:
                    save_decision_layered(stock.symbol, date_str, result)
                logger.info(
                    "signal saved: %s %s %s(%.0f) quant=%.1f tech=%.1f sentiment=%.2f model=%s",
                    stock.symbol, date_str, result["recommendation"],
                    result["composite_score"], quant, tech.get("score", 0),
                    sentiment_result["sentiment"], quant_result.get("model", "?"),
                )

                # Bark 推送：明确交易动作（观察/小仓试错/旧框架买入）
                if should_send_signal_alert(result["recommendation"]):
                    from backend.notification.bark import send_signal_alert
                    send_signal_alert(
                        symbol=stock.symbol,
                        name=stock.name,
                        recommendation=result["recommendation"],
                        score=result["composite_score"],
                        stop_loss=result["stop_loss"],
                        take_profit=result["take_profit"],
                        position_pct=result.get("position_pct"),
                    )
            except Exception as e:
                logger.error("postmarket failed %s: %s", stock.symbol, e)

        logger.info("post-market done: %d stocks processed", len(stocks))
        _run_kill_switch_checks(db)
    finally:
        db.close()


def job_stoploss_check() -> None:
    """
    盘中止损预警（每天 14:30 运行）：
    取最近一次正向信号，比对当日最新价是否触及止损线，
    触及则发送 Bark 推送。
    """
    if _kill_switch_guard("stoploss_check"):
        return
    from backend.data.database import SessionLocal, Stock, Signal, Price
    from backend.notification.bark import send_stoploss_alert
    from backend.decision.signal_policy import entry_recommendations

    db = SessionLocal()
    try:
        stocks = db.query(Stock).filter(Stock.active == True).all()
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
                if current <= sig.stop_loss:
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


def job_train_model() -> None:
    """每周六重训 LightGBM Alpha 模型（数据不足时自动跳过）"""
    from backend.data.database import SessionLocal
    from backend.analysis.qlib_engine import train

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


def job_weekly_longterm() -> None:
    """
    长期分析师团 first batch：每周日 11:00
    同步 industry + 5 年财报 → 跑 LongTermTeam → save_label
    """
    from backend.data.database import SessionLocal, Stock
    from backend.data.fundamentals import sync_industry, sync_financial_metrics
    from backend.agents.long_term.team import LongTermTeam
    from backend.agents.long_term.storage import save_label

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

        stocks = db.query(Stock).filter(Stock.active == True, Stock.market == "CN").all()
        for s in stocks:
            try:
                inserted = sync_financial_metrics(s.symbol, db, years=settings.financial_backfill_years)
                if inserted:
                    logger.info("financials %s: +%d rows", s.symbol, inserted)
            except Exception as e:
                logger.error("sync_financial_metrics %s failed: %s", s.symbol, e)

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


def start() -> None:
    """Register all cron jobs and start the background scheduler."""
    pre_h, pre_m = settings.schedule_premarket.split(":")
    post_h, post_m = settings.schedule_postmarket.split(":")

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

    # 长期分析师团（周末）
    if settings.long_term_team_enabled:
        lt_h, lt_m = settings.schedule_longterm_time.split(":")
        scheduler.add_job(job_weekly_longterm, CronTrigger(
            hour=int(lt_h), minute=int(lt_m),
            day_of_week=settings.schedule_longterm_dow,
        ), id="weekly_longterm", replace_existing=True)
        logger.info("long_term team scheduled: %s %s",
                    settings.schedule_longterm_dow, settings.schedule_longterm_time)

    scheduler.start()
    logger.info("scheduler started (premarket=%s, postmarket=%s)",
                settings.schedule_premarket, settings.schedule_postmarket)


def stop() -> None:
    """Shut down the background scheduler without waiting for jobs to finish."""
    scheduler.shutdown(wait=False)
