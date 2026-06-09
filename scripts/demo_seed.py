"""
Demo database seeder for MingCang.

Seeds a standalone demo SQLite file at examples/sample_db/mingcang_demo.db
with coherent sample data — 3 A-share stocks, 1 ForwardThesis (with a
falsification condition), 1 ReviewCase (复盘), and 1 pending
MemoryPromotionCandidate.

Usage (standalone, no API keys required):
    python scripts/demo_seed.py

Or via Makefile:
    make demo
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Point DATABASE_URL at the demo file BEFORE any backend import.
# The engine + SessionLocal are module-level singletons; setting the env var
# here ensures they bind to the demo path instead of the real mingcang.db.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent.resolve()
_DEMO_DB_DIR = _REPO_ROOT / "examples" / "sample_db"
_DEMO_DB_PATH = _DEMO_DB_DIR / "mingcang_demo.db"

_DEMO_DB_DIR.mkdir(parents=True, exist_ok=True)
_ACTIVE_DATABASE_URL = os.environ.setdefault("DATABASE_URL", f"sqlite:///{_DEMO_DB_PATH}")

# Also ensure PYTHONPATH includes the repo root so backend imports work when
# the script is invoked directly (without `python -m`).
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Now safe to import backend modules.
# ---------------------------------------------------------------------------
from backend.data.database import (  # noqa: E402
    ForwardThesis,
    IndexPrice,
    MemoryPromotionCandidate,
    Position,
    Price,
    ReviewCase,
    Signal,
    Stock,
    init_db,
)
from backend.data.session import SessionLocal  # noqa: E402


def _upsert_stocks(db) -> None:
    """Insert 3 sample A-share stocks; skip if already present (idempotent)."""
    samples = [
        Stock(symbol="600519", name="贵州茅台", market="CN", industry="食品饮料", active=True),
        Stock(symbol="300308", name="中际旭创", market="CN", industry="通信", active=True),
        Stock(symbol="601318", name="中国平安", market="CN", industry="非银金融", active=True),
    ]
    for s in samples:
        existing = db.query(Stock).filter(Stock.symbol == s.symbol).first()
        if existing is None:
            db.add(s)
    db.commit()


def _upsert_demo_market_rows(db) -> None:
    """Seed enough price/signal/index rows for the first frontend screen."""
    price_rows = {
        "600519": [
            ("2026-05-29", 1438.0),
            ("2026-06-01", 1446.5),
            ("2026-06-02", 1452.0),
            ("2026-06-03", 1460.8),
        ],
        "300308": [
            ("2026-05-29", 116.2),
            ("2026-06-01", 119.5),
            ("2026-06-02", 122.4),
            ("2026-06-03", 126.8),
        ],
        "601318": [
            ("2026-05-29", 47.8),
            ("2026-06-01", 48.2),
            ("2026-06-02", 48.6),
            ("2026-06-03", 49.1),
        ],
    }
    fetched_at = datetime(2026, 6, 3, 16, 0)
    for symbol, rows in price_rows.items():
        for idx, (day, close) in enumerate(rows):
            existing = (
                db.query(Price)
                .filter(Price.symbol == symbol, Price.date == day)
                .first()
            )
            if existing is not None:
                continue
            db.add(Price(
                symbol=symbol,
                date=day,
                open=round(close * 0.992, 2),
                high=round(close * 1.018, 2),
                low=round(close * 0.986, 2),
                close=close,
                volume=1_000_000 + idx * 125_000,
                atr14=round(close * 0.032, 2),
                source="demo_seed",
                fetched_at=fetched_at,
                adjustment="qfq",
            ))

    index_rows = [
        ("2026-05-29", 3840.0, 0.42),
        ("2026-06-01", 3856.2, 0.18),
        ("2026-06-02", 3869.4, 0.34),
        ("2026-06-03", 3882.6, 0.28),
    ]
    for day, close, change_pct in index_rows:
        existing = (
            db.query(IndexPrice)
            .filter(IndexPrice.symbol == "sh000300", IndexPrice.date == day)
            .first()
        )
        if existing is None:
            db.add(IndexPrice(
                symbol="sh000300",
                date=day,
                close=close,
                change_pct=change_pct,
                source="demo_seed",
                fetched_at=fetched_at,
                adjustment="qfq",
            ))

    signals = [
        {
            "symbol": "300308",
            "composite_score": 42.0,
            "recommendation": "可小仓试错",
            "confidence": "中",
            "technical_score": 58.0,
            "sentiment_score": 18.0,
            "stop_loss": 118.6,
            "take_profit": 143.2,
            "rationale": "订单景气与技术突破同向，但估值弹性需要复盘验证。",
        },
        {
            "symbol": "600519",
            "composite_score": 12.0,
            "recommendation": "可关注",
            "confidence": "中",
            "technical_score": 18.0,
            "sentiment_score": 2.0,
            "stop_loss": 1398.4,
            "take_profit": 1548.0,
            "rationale": "现金流质量稳定，短线更多是观察而不是追高。",
        },
        {
            "symbol": "601318",
            "composite_score": -8.0,
            "recommendation": "观望",
            "confidence": "中",
            "technical_score": -12.0,
            "sentiment_score": 6.0,
            "stop_loss": 46.7,
            "take_profit": 53.0,
            "rationale": "估值修复线索存在，但当前信号强度不足。",
        },
    ]
    for row in signals:
        existing = (
            db.query(Signal)
            .filter(Signal.symbol == row["symbol"], Signal.date == "2026-06-03")
            .first()
        )
        if existing is not None:
            continue
        db.add(Signal(
            symbol=row["symbol"],
            date="2026-06-03",
            quant_score=0.0,
            technical_score=row["technical_score"],
            sentiment_score=row["sentiment_score"],
            composite_score=row["composite_score"],
            recommendation=row["recommendation"],
            confidence=row["confidence"],
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
            limit_status="normal",
            llm_rationale=json.dumps({
                "bull_points": ["样例数据用于展示研究闭环"],
                "bear_points": ["不可作为真实投资建议"],
                "action_bias": "中性",
                "rationale": row["rationale"],
            }, ensure_ascii=False),
            rule_version="demo_seed:new_framework",
            data_timestamp="2026-06-03",
            created_at=fetched_at,
        ))
    db.commit()


def _upsert_demo_position(db) -> None:
    """Seed one open demo position so the dashboard has mark-to-market context."""
    existing = (
        db.query(Position)
        .filter(Position.symbol == "300308", Position.status == "open", Position.note == "Demo示例持仓")
        .first()
    )
    if existing is not None:
        return
    db.add(Position(
        symbol="300308",
        name="中际旭创",
        market="CN",
        quantity=100.0,
        avg_cost=120.5,
        opened_at="2026-06-01",
        stop_loss=118.6,
        take_profit=143.2,
        note="Demo示例持仓",
        status="open",
    ))
    db.commit()


def _upsert_forward_thesis(db) -> int:
    """Insert 1 ForwardThesis with a falsification condition; return its id."""
    statement = "AI算力景气持续，中际旭创CPO订单将在2026Q3前完成年度目标"
    existing = (
        db.query(ForwardThesis)
        .filter(ForwardThesis.symbol == "300308", ForwardThesis.statement == statement)
        .first()
    )
    if existing:
        return existing.id

    ft = ForwardThesis(
        symbol="300308",
        statement=statement,
        status="active",
        horizon_date="2026-09-30",
        confidence_low=0.55,
        confidence_high=0.75,
        invalidation_conditions_json=json.dumps(
            [
                "2026Q2财报CPO收入同比增速跌破20%",
                "北美大客户订单明确推迟超过两个季度",
                "行业主要竞争对手以低于成本价抢单",
            ],
            ensure_ascii=False,
        ),
        evidence_manifest_json=json.dumps(
            {
                "catalysts": ["AI训练集群扩张", "CPO技术渗透率提升"],
                "risks": ["海外订单兑现不足时避免追高"],
            },
            ensure_ascii=False,
        ),
        follow_up_metrics_json=json.dumps(
            ["季度CPO发货量", "北美数据中心资本开支"],
            ensure_ascii=False,
        ),
        next_review_date="2026-07-15",
        review_cadence_days=30,
    )
    db.add(ft)
    db.commit()
    db.refresh(ft)
    return ft.id


def _upsert_review_case(db, thesis_id: int) -> int:
    """Insert 1 ReviewCase (复盘) for 300308; return its id."""
    as_of = "2026-06-01"
    existing = (
        db.query(ReviewCase)
        .filter(ReviewCase.symbol == "300308", ReviewCase.as_of == as_of)
        .first()
    )
    if existing:
        return existing.id

    rc = ReviewCase(
        symbol="300308",
        as_of=as_of,
        thesis_id=thesis_id,
        outcome_correct=True,
        next_day_return=3.2,
        composite_score=68.0,
        recommendation="可关注",
        attribution_json=json.dumps(
            [
                "技术面突破短期阻力位，量能配合良好",
                "CPO出货量超预期，订单景气确认",
                "大盘RSRS处于强势区间，未触发宏观否决",
            ],
            ensure_ascii=False,
        ),
        review_payload_json=json.dumps(
            {
                "rule_version": "aggregate_v1:new_framework",
                "signals_checked": ["technical", "sentiment"],
                "long_term_label": "值得持有",
                "review_note": "Demo复盘：信号正确，订单数据兑现",
            },
            ensure_ascii=False,
        ),
    )
    db.add(rc)
    db.commit()
    db.refresh(rc)
    return rc.id


def _upsert_memory_promotion_candidate(db, review_case_id: int) -> None:
    """Insert 1 pending MemoryPromotionCandidate; skip if already present."""
    source_ref = "demo_review_300308_2026-06-01"
    existing = (
        db.query(MemoryPromotionCandidate)
        .filter(
            MemoryPromotionCandidate.symbol == "300308",
            MemoryPromotionCandidate.source_ref == source_ref,
        )
        .first()
    )
    if existing:
        return

    mc = MemoryPromotionCandidate(
        review_case_id=review_case_id,
        symbol="300308",
        summary=(
            "CPO订单兑现时，中际旭创短线技术突破信号可信度高；"
            "关键验证点为季度发货量数据与北美客户资本开支确认。"
        ),
        memory_type="research_pointer",
        source_trust="pending",  # awaiting explicit human promotion gate
        source_ref=source_ref,
        importance=4,
        confidence=0.68,
        note="Demo示例：待审核晋升，不影响生产决策",
    )
    db.add(mc)
    db.commit()


def seed_demo() -> None:
    """Run all demo seed steps, idempotently."""
    print(f"[demo_seed] Target DB: {_ACTIVE_DATABASE_URL.removeprefix('sqlite:///')}")

    # Bootstrap schema (create_all + runtime patches) against demo DB
    init_db()
    print("[demo_seed] Schema initialised.")

    db = SessionLocal()
    try:
        _upsert_stocks(db)
        print("[demo_seed] Stocks seeded: 600519, 300308, 601318")

        _upsert_demo_market_rows(db)
        print("[demo_seed] Prices, index, and latest signals seeded.")

        _upsert_demo_position(db)
        print("[demo_seed] Demo position seeded: 300308")

        ft_id = _upsert_forward_thesis(db)
        print(f"[demo_seed] ForwardThesis seeded (id={ft_id}): 300308 CPO订单论点")

        rc_id = _upsert_review_case(db, thesis_id=ft_id)
        print(f"[demo_seed] ReviewCase seeded (id={rc_id}): 300308 @ 2026-06-01")

        _upsert_memory_promotion_candidate(db, review_case_id=rc_id)
        print("[demo_seed] MemoryPromotionCandidate seeded (status=pending)")

    finally:
        db.close()

    print(f"\n[demo_seed] Done. Demo DB at: {_ACTIVE_DATABASE_URL.removeprefix('sqlite:///')}")
    print("[demo_seed] Start backend against demo DB:")
    print(f"  DATABASE_URL={_ACTIVE_DATABASE_URL} uvicorn backend.main:app --reload")


if __name__ == "__main__":
    seed_demo()
