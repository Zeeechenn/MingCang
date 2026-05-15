"""FastAPI 路由"""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.data.database import get_db, SessionLocal, Stock, Signal, Price, NewsItem, FinancialMetric, LongTermLabel
from backend.api.schemas import (
    WatchlistItem, SignalOut, PriceBar, NewsOut,
    SignalEvalOut, SignalEvalRecord, LongTermLabelOut,
)
from backend.decision.signal_policy import is_entry_signal

router = APIRouter()


# ── 内部工具 ─────────────────────────────────────────────────────────

def _backfill_task(symbol: str, market: str) -> None:
    """Background task: backfill price data for the given symbol."""
    from backend.data.market import backfill_if_needed
    db = SessionLocal()
    try:
        backfill_if_needed(symbol, market, db)
    finally:
        db.close()


def _latest_signal(symbol: str, db: Session) -> Signal | None:
    """Return the most recent Signal row for symbol, or None."""
    return (
        db.query(Signal)
        .filter(Signal.symbol == symbol)
        .order_by(Signal.date.desc())
        .first()
    )


def _signal_to_schema(sig: Signal) -> SignalOut:
    """将 Signal ORM 对象转换为 SignalOut，自动解析 llm_rationale JSON"""
    rec = {
        "强买": "可小仓试错",
        "买入": "可关注",
        "卖出": "规避",
        "强卖": "规避",
    }.get(sig.recommendation, sig.recommendation)
    arb = None
    if sig.llm_rationale:
        try:
            arb = json.loads(sig.llm_rationale)
        except Exception:
            arb = {"rationale": sig.llm_rationale, "bull_points": [], "bear_points": [], "action_bias": "中性"}

    return SignalOut(
        id=sig.id,
        symbol=sig.symbol,
        date=sig.date,
        composite_score=sig.composite_score,
        recommendation=rec,
        confidence=sig.confidence,
        stop_loss=sig.stop_loss,
        take_profit=sig.take_profit,
        limit_status=sig.limit_status,
        quant_score=sig.quant_score,
        technical_score=sig.technical_score,
        sentiment_score=sig.sentiment_score,
        llm_arbitration=arb,
    )


# ── 自选股 ────────────────────────────────────────────────────────────

def _label_to_schema(lt) -> LongTermLabelOut | None:
    """Convert a LongTermLabel ORM row to the API schema, or None."""
    if lt is None:
        return None
    return LongTermLabelOut(
        symbol=lt.symbol,
        date=lt.date,
        label=lt.label,
        score=lt.score,
        votes=lt.votes,
        key_findings=lt.key_findings,
        expires_at=lt.expires_at,
    )


@router.get("/watchlist", response_model=list[WatchlistItem])
def get_watchlist(db: Session = Depends(get_db)):
    """Return all active watchlist stocks with their latest signal and long-term label."""
    from backend.agents.long_term.storage import bulk_get_labels

    stocks = db.query(Stock).filter(Stock.active == True).all()
    labels = bulk_get_labels([s.symbol for s in stocks], db) if stocks else {}
    result = []
    for s in stocks:
        sig = _latest_signal(s.symbol, db)
        lt = labels.get(s.symbol)
        result.append(WatchlistItem(
            symbol=s.symbol,
            name=s.name,
            market=s.market,
            industry=s.industry,
            latest_signal=_signal_to_schema(sig) if sig else None,
            long_term_label=_label_to_schema(lt),
        ))
    return result


@router.get("/long-term/{symbol}", response_model=LongTermLabelOut)
def get_long_term_label(symbol: str, db: Session = Depends(get_db)):
    """返回该股 TTL 未过期的最新一条长期标签"""
    from backend.agents.long_term.storage import get_active_label

    lt = get_active_label(symbol, db)
    if lt is None:
        raise HTTPException(404, "No active long-term label")
    return _label_to_schema(lt)


@router.post("/long-term/run")
def trigger_long_term_team(background_tasks: BackgroundTasks):
    """手动触发长期分析师团（背景任务），用于按需重算"""
    from backend.scheduler import job_weekly_longterm
    background_tasks.add_task(job_weekly_longterm)
    return {"status": "long-term team triggered"}


@router.post("/watchlist")
def add_stock(
    symbol: str,
    name: str,
    market: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Add or reactivate a stock in the watchlist and trigger backfill."""
    if market not in ("CN", "US"):
        raise HTTPException(400, "market must be CN or US")
    existing = db.query(Stock).filter(Stock.symbol == symbol).first()
    if existing:
        existing.active = True
    else:
        db.add(Stock(symbol=symbol, name=name, market=market))
    db.commit()
    background_tasks.add_task(_backfill_task, symbol, market)
    return {"status": "ok", "backfill": "started"}


@router.delete("/watchlist/{symbol}")
def remove_stock(symbol: str, db: Session = Depends(get_db)):
    """Soft-delete a stock from the watchlist (sets active=False)."""
    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    if stock:
        stock.active = False
        db.commit()
    return {"status": "ok"}


# ── 信号 ──────────────────────────────────────────────────────────────

@router.get("/signals/{symbol}/latest", response_model=SignalOut)
def get_latest_signal(symbol: str, db: Session = Depends(get_db)):
    """Return the most recent signal for a symbol."""
    sig = _latest_signal(symbol, db)
    if not sig:
        raise HTTPException(404, "No signal found")
    return _signal_to_schema(sig)


@router.get("/signals/{symbol}", response_model=list[SignalOut])
def get_signals(symbol: str, limit: int = 30, db: Session = Depends(get_db)):
    """Return the most recent signals for a symbol up to limit."""
    sigs = (
        db.query(Signal)
        .filter(Signal.symbol == symbol)
        .order_by(Signal.date.desc())
        .limit(limit)
        .all()
    )
    return [_signal_to_schema(s) for s in sigs]


# ── 行情 ──────────────────────────────────────────────────────────────

@router.get("/prices/{symbol}", response_model=list[PriceBar])
def get_prices(symbol: str, days: int = 120, db: Session = Depends(get_db)):
    """Return OHLCV price bars for a symbol over the past days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = (
        db.query(Price)
        .filter(Price.symbol == symbol, Price.date >= cutoff)
        .order_by(Price.date.asc())
        .all()
    )
    return [
        PriceBar(
            time=r.date,
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            volume=r.volume or 0.0,
        )
        for r in rows
    ]


# ── 模型 ──────────────────────────────────────────────────────────────

def _train_task() -> None:
    """Background task: train the LightGBM Alpha model."""
    from backend.data.database import SessionLocal
    from backend.analysis.qlib_engine import train
    db = SessionLocal()
    try:
        train(db)
    finally:
        db.close()


@router.post("/model/train")
def trigger_train(background_tasks: BackgroundTasks):
    """手动触发 LightGBM Alpha 模型重训（后台异步执行）"""
    background_tasks.add_task(_train_task)
    return {"status": "training started"}


@router.get("/model/status")
def model_status():
    """查询模型文件是否存在及最后修改时间"""
    from backend.analysis.qlib_engine import MODEL_PATH
    import os
    if MODEL_PATH.exists():
        mtime = os.path.getmtime(MODEL_PATH)
        from datetime import datetime
        return {
            "exists": True,
            "path": str(MODEL_PATH),
            "updated_at": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "size_kb": round(MODEL_PATH.stat().st_size / 1024, 1),
        }
    return {"exists": False}


# ── 信号 Alpha 评估 ──────────────────────────────────────────────────

@router.get("/signals/eval/{symbol}", response_model=SignalEvalOut)
def eval_signals(symbol: str, days: int = 60, db: Session = Depends(get_db)):
    """
    评估过去 days 天内该股信号的准确率。
    对每条信号，取其次一个交易日的收盘价与信号当日收盘价对比，
    判断建议方向是否与实际走势一致。
    """
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    signals = (
        db.query(Signal)
        .filter(Signal.symbol == symbol, Signal.date >= cutoff)
        .order_by(Signal.date.asc())
        .all()
    )

    records: list[SignalEvalRecord] = []
    returns: list[float] = []
    buy_returns: list[float] = []
    neutral_returns: list[float] = []
    sell_returns: list[float] = []
    correct_count = 0
    evaluated = 0

    for sig in signals:
        sig_price = (
            db.query(Price.close)
            .filter(Price.symbol == symbol, Price.date == sig.date)
            .first()
        )
        next_price = (
            db.query(Price.close)
            .filter(Price.symbol == symbol, Price.date > sig.date)
            .order_by(Price.date.asc())
            .first()
        )

        if sig_price and next_price and sig_price[0]:
            ret = (next_price[0] - sig_price[0]) / sig_price[0] * 100
            if is_entry_signal(sig.recommendation, include_legacy=True):
                direction = "long"
            elif sig.recommendation in ("卖出", "强卖", "规避"):
                direction = "short"
            else:
                direction = "neutral"

            correct = (
                (direction == "long" and ret > 0)
                or (direction == "short" and ret < 0)
                or (direction == "neutral" and abs(ret) <= 0.5)
            )
            if correct:
                correct_count += 1
            evaluated += 1
            returns.append(ret)
            if direction == "long":
                buy_returns.append(ret)
            elif direction == "short":
                sell_returns.append(ret)
            else:
                neutral_returns.append(ret)
            records.append(SignalEvalRecord(
                date=sig.date,
                recommendation=sig.recommendation,
                composite_score=sig.composite_score,
                next_day_return=round(ret, 2),
                correct=correct,
            ))
        else:
            records.append(SignalEvalRecord(
                date=sig.date,
                recommendation=sig.recommendation,
                composite_score=sig.composite_score,
            ))

    def _avg(lst) -> float | None:
        """Return the rounded average of a list, or None if empty."""
        return round(sum(lst) / len(lst), 2) if lst else None

    return SignalEvalOut(
        symbol=symbol,
        days=days,
        total_signals=len(signals),
        evaluated=evaluated,
        win_rate=round(correct_count / evaluated * 100, 1) if evaluated else None,
        avg_return=_avg(returns),
        avg_return_on_buy=_avg(buy_returns),
        avg_return_on_neutral=_avg(neutral_returns),
        avg_return_on_sell=_avg(sell_returns),
        records=records,
    )


# ── 系统状态 ─────────────────────────────────────────────────────────

@router.get("/system/status")
def system_status(db: Session = Depends(get_db)):
    """Return database and long-term label status summary."""
    from backend.config import settings
    from pathlib import Path

    latest_price_date = db.query(Price.date).order_by(Price.date.desc()).first()
    latest_label_date = db.query(LongTermLabel.date).order_by(LongTermLabel.date.desc()).first()
    return {
        "database_url": settings.database_url,
        "database_path": settings.database_url.removeprefix("sqlite:///"),
        "database_exists": Path(settings.database_url.removeprefix("sqlite:///")).exists(),
        "latest_price_date": latest_price_date[0] if latest_price_date else None,
        "financial_metrics_count": db.query(FinancialMetric).count(),
        "long_term_labels_count": db.query(LongTermLabel).count(),
        "latest_long_term_label_date": latest_label_date[0] if latest_label_date else None,
    }


@router.get("/system/health")
def system_health(db: Session = Depends(get_db)):
    """
    综合健康检查（Tier 4）：DB / 数据新鲜度 / kill switch / 连续亏损。

    供外部监控（如 Bark / Uptime / Grafana）轮询。
    """
    from backend.ops import kill_switch
    from backend.config import settings
    from pathlib import Path

    db_path = settings.database_url.removeprefix("sqlite:///")
    db_ok = Path(db_path).exists()

    latest_price_date = None
    data_age_days = None
    try:
        row = db.query(Price.date).order_by(Price.date.desc()).first()
        latest_price_date = row[0] if row else None
        if latest_price_date:
            last = datetime.strptime(latest_price_date, "%Y-%m-%d")
            data_age_days = (datetime.utcnow() - last).days
    except Exception:
        db_ok = False

    # 最近 N 笔信号收益（粗略：用 next_day_return 类似口径，从历史 signals 与 prices 对比）
    recent_losses = 0
    try:
        recent_signals = (
            db.query(Signal)
            .filter(Signal.recommendation.in_(["可小仓试错", "买入", "强买"]))
            .order_by(Signal.date.desc())
            .limit(10)
            .all()
        )
        returns = []
        for sig in recent_signals:
            sig_p = db.query(Price.close).filter(
                Price.symbol == sig.symbol, Price.date == sig.date
            ).first()
            next_p = db.query(Price.close).filter(
                Price.symbol == sig.symbol, Price.date > sig.date
            ).order_by(Price.date.asc()).first()
            if sig_p and next_p and sig_p[0]:
                returns.append((next_p[0] - sig_p[0]) / sig_p[0])
        recent_losses = kill_switch.detect_consecutive_losses(returns)
    except Exception:
        pass

    ks_state = kill_switch.current_state()
    healthy = (
        db_ok
        and (data_age_days is None or data_age_days <= kill_switch.DEFAULT_DATA_STALE_DAYS)
        and not (ks_state and ks_state.get("active"))
    )

    return {
        "healthy": healthy,
        "db_ok": db_ok,
        "db_path": db_path,
        "latest_price_date": latest_price_date,
        "data_age_days": data_age_days,
        "data_stale_threshold_days": kill_switch.DEFAULT_DATA_STALE_DAYS,
        "kill_switch": ks_state,
        "consecutive_losses": recent_losses,
        "consecutive_losses_threshold": kill_switch.DEFAULT_CONSECUTIVE_LOSSES,
    }


@router.post("/system/kill-switch/trigger")
def trigger_kill_switch(reason: str = "manual"):
    """Manually trigger the kill switch with a reason string."""
    from backend.ops import kill_switch
    state = kill_switch.trigger(reason=reason, metadata={"source": "api"})
    return state.to_dict()


@router.post("/system/kill-switch/reset")
def reset_kill_switch():
    """Reset an active kill switch state."""
    from backend.ops import kill_switch
    kill_switch.reset()
    return {"reset": True}


# ── 新闻 ──────────────────────────────────────────────────────────────

@router.get("/news/{symbol}", response_model=list[NewsOut])
def get_news(symbol: str, hours: int = 48, db: Session = Depends(get_db)):
    """Return recent news items for a symbol within the past hours."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    rows = (
        db.query(NewsItem)
        .filter(NewsItem.symbol == symbol, NewsItem.published_at >= cutoff)
        .order_by(NewsItem.published_at.desc())
        .limit(30)
        .all()
    )
    return [
        NewsOut(
            id=r.id,
            title=r.title,
            url=r.url,
            published_at=r.published_at.strftime("%Y-%m-%d %H:%M"),
            source=r.source,
            sentiment_score=r.sentiment_score,
        )
        for r in rows
    ]
