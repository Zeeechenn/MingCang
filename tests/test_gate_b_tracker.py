"""Hermetic pytest tests for the Gate-B prospective tracker.

Uses the test_db in-memory SQLite fixture (from conftest.py).
All data is synthetic — no real DB is touched.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from backend.config import settings
from backend.data.database import (
    DecisionRun,
    LongTermLabel,
    Price,
    ResearchState,
    Signal,
    StockMemoryItem,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def enable_gate_b(monkeypatch):
    """Enable gate_b_tracker_enabled for every test in this module."""
    monkeypatch.setattr(settings, "gate_b_tracker_enabled", True)
    yield


def _seed_signal(
    db,
    symbol: str = "600519",
    sig_date: str = "2025-11-15",
    score: float = 55.0,
    recommendation: str = "买入",
) -> Signal:
    sig = Signal(
        symbol=symbol,
        date=sig_date,
        composite_score=score,
        recommendation=recommendation,
        confidence="高",
        rule_version="v1",
    )
    db.add(sig)
    db.flush()
    return sig


def _seed_label(
    db,
    symbol: str = "600519",
    ldate: str = "2025-11-10",
    expires: str = "2025-11-25",
    quality: str = "trusted",
) -> LongTermLabel:
    lbl = LongTermLabel(
        symbol=symbol,
        date=ldate,
        label="值得持有",
        score=70.0,
        expires_at=expires,
        quality=quality,
        constraint_eligible=True,
    )
    db.add(lbl)
    db.flush()
    return lbl


def _seed_decision_run(
    db,
    symbol: str = "600519",
    as_of: str = "2025-11-14",
) -> DecisionRun:
    snap = json.dumps(
        {
            "universe_hash": "abc123",
            "data_source": "tushare",
            "fetched_at": "2025-11-14",
            "adjustment": "qfq",
        }
    )
    dr = DecisionRun(
        run_id=f"dr-{symbol}-{as_of}",
        run_type="postmarket",
        symbol=symbol,
        as_of=as_of,
        input_snapshot_json=snap,
    )
    db.add(dr)
    db.flush()
    return dr


def _seed_prices(
    db,
    symbol: str = "600519",
    entry_date: str = "2025-11-15",
    closes: tuple = (100.0, 101.0, 102.5, 101.5, 103.0, 104.0),
) -> None:
    """Seed `len(closes)` prices starting at entry_date (entry + 0..N-1 calendar days)."""
    for i, c in enumerate(closes):
        d = (date.fromisoformat(entry_date) + timedelta(days=i)).isoformat()
        db.add(
            Price(
                symbol=symbol,
                date=d,
                open=c,
                high=c + 1,
                low=c - 1,
                close=c,
                volume=1_000_000,
            )
        )
    db.commit()


def _seed_deep_research(
    db,
    symbol: str = "600519",
    created_at: str = "2025-11-14",
) -> StockMemoryItem:
    item = StockMemoryItem(
        symbol=symbol,
        memory_type="research_pointer",
        summary="synthetic deep research",
        source_type="test",
        source_ref=f"test-{symbol}-{created_at}",
        status="active",
        created_at=datetime.fromisoformat(created_at),
        updated_at=datetime.fromisoformat(created_at),
    )
    db.add(item)
    db.flush()
    return item


def _record(db, as_of: str = "2025-11-15", horizon_days: int = 5):
    from backend.research.gate_b_recorder import record_observations
    return record_observations(db, as_of=as_of, horizon_days=horizon_days)


def _realize(db, as_of: str = "2025-11-25"):
    from backend.research.gate_b_recorder import realize_returns
    return realize_returns(db, as_of=as_of)


# ---------------------------------------------------------------------------
# TestRecordObservations
# ---------------------------------------------------------------------------

class TestRecordObservations:
    def test_basic_record(self, test_db):
        """A valid Signal+Label+DecisionRun yields one observation row."""
        _seed_signal(test_db)
        _seed_label(test_db)
        _seed_decision_run(test_db)
        _seed_prices(test_db)
        test_db.commit()

        rows = _record(test_db)

        assert len(rows) == 1
        r = rows[0]
        assert r["symbol"] == "600519"
        assert r["signal_date"] == "2025-11-15"
        assert r["as_of"] == "2025-11-15"
        assert r["entry_close"] == pytest.approx(100.0)
        assert r["forward_status"] == "pending"
        assert r["gate_b_tracker_version"] == "v1"

    def test_idempotent_second_call(self, test_db):
        """Calling record_observations twice with same as_of yields no duplicate."""
        _seed_signal(test_db)
        _seed_label(test_db)
        _seed_decision_run(test_db)
        _seed_prices(test_db)
        test_db.commit()

        rows1 = _record(test_db)
        rows2 = _record(test_db)

        assert len(rows1) == 1
        assert len(rows2) == 0  # second call: already recorded, nothing new

        from backend.data.database import GateBObservation
        all_obs = test_db.query(GateBObservation).all()
        assert len(all_obs) == 1
        assert all_obs[0].id == rows1[0]["id"]

    def test_copilot_excluded_from_variant(self, test_db):
        """
        gate_pass_variant should exclude copilot_present from blockers.

        With no ResearchState, copilot_present IS a blocker in gate_pass_full,
        but gate_pass_variant removes it so only the remaining blockers count.
        We seed a trusted label + decision run so all other required blockers
        are satisfied; the ONLY remaining blocker in variant should be
        deep_research_present (no StockMemoryItem seeded).
        """
        _seed_signal(test_db)
        _seed_label(test_db)
        _seed_decision_run(test_db)
        _seed_prices(test_db)
        test_db.commit()

        rows = _record(test_db)
        assert len(rows) == 1
        r = rows[0]

        # copilot_present is always a blocker when no ResearchState row exists
        assert "copilot_present" in r["blockers"]
        # but NOT in the variant blockers
        assert "copilot_present" not in r["blockers_variant"]

    def test_gate_pass_full_reflects_raw_blockers(self, test_db):
        """gate_pass_full == False when copilot is missing (raw M33 blockers include it)."""
        _seed_signal(test_db)
        _seed_label(test_db)
        _seed_decision_run(test_db)
        _seed_prices(test_db)
        test_db.commit()

        rows = _record(test_db)
        r = rows[0]
        # copilot_present is a blocker → gate_pass_full must be False
        assert r["gate_pass_full"] is False

    def test_current_open_questions_do_not_pollute_pit_variant(self, test_db):
        """Current ResearchState.open_questions has no PIT history and must not block the variant."""
        test_db.add(ResearchState(
            symbol="600519",
            thesis="current mutable thesis",
            risks_json="[]",
            open_questions_json=json.dumps(["current-only question"], ensure_ascii=False),
            copilot_json=None,
            created_at=datetime.fromisoformat("2025-12-01"),
            updated_at=datetime.fromisoformat("2025-12-01"),
        ))
        _seed_signal(test_db)
        _seed_label(test_db)
        _seed_decision_run(test_db)
        _seed_deep_research(test_db)
        _seed_prices(test_db)
        test_db.commit()

        rows = _record(test_db)

        assert len(rows) == 1
        assert "no_pending_questions" not in rows[0]["blockers_variant"]
        assert rows[0]["gate_pass_variant"] is True

    def test_pit_label_expiry_respected(self, test_db):
        """A label that expired before signal_date must not be used (label_id == None)."""
        _seed_signal(test_db, sig_date="2025-11-15")
        # Label expires BEFORE the signal date
        _seed_label(test_db, ldate="2025-11-01", expires="2025-11-12")
        _seed_decision_run(test_db)
        _seed_prices(test_db)
        test_db.commit()

        rows = _record(test_db)
        assert len(rows) == 1
        r = rows[0]
        assert r["label_id"] is None
        # label_present should be a blocker since no valid label exists
        assert "label_present" in r["blockers"]

    def test_future_signal_excluded(self, test_db):
        """A signal dated after as_of must NOT be recorded."""
        _seed_signal(test_db, sig_date="2025-11-15")
        _seed_prices(test_db)
        test_db.commit()

        # as_of is one day before the signal
        rows = _record(test_db, as_of="2025-11-14")
        assert len(rows) == 0

    def test_disabled_flag_returns_empty(self, test_db, monkeypatch):
        """When gate_b_tracker_enabled is False, record_observations returns []."""
        monkeypatch.setattr(settings, "gate_b_tracker_enabled", False)
        _seed_signal(test_db)
        _seed_prices(test_db)
        test_db.commit()

        from backend.research.gate_b_recorder import record_observations
        rows = record_observations(test_db, as_of="2025-11-15")
        assert rows == []


# ---------------------------------------------------------------------------
# TestRealizeReturns
# ---------------------------------------------------------------------------

class TestRealizeReturns:
    def test_correct_net_return(self, test_db):
        """
        With 6 prices (entry=100.0, fwd=[101,102.5,101.5,103,104]),
        the 5th forward close is 104; gross = (104-100)/100 = 0.04;
        net = 0.04 - round_trip_cost.  Verify against net_return_from_prices.
        """
        from backend.backtest.costs import net_return_from_prices

        _seed_signal(test_db)
        _seed_label(test_db)
        _seed_decision_run(test_db)
        # 6 prices: index 0 = entry date, indices 1-5 = 5 forward trading days
        _seed_prices(test_db, closes=(100.0, 101.0, 102.5, 101.5, 103.0, 104.0))
        test_db.commit()

        _record(test_db)
        realized = _realize(test_db)

        assert len(realized) == 1
        r = realized[0]
        expected_net = net_return_from_prices(100.0, 104.0)
        assert r["forward_return_net"] == pytest.approx(expected_net, abs=1e-6)
        assert r["forward_status"] == "realized"

    def test_pending_when_fewer_than_5_prices(self, test_db):
        """Only 3 forward prices → observation stays 'pending'."""
        _seed_signal(test_db)
        _seed_label(test_db)
        _seed_decision_run(test_db)
        # 4 total prices: 1 entry + 3 forward
        _seed_prices(test_db, closes=(100.0, 101.0, 102.0, 103.0))
        test_db.commit()

        _record(test_db)
        realized = _realize(test_db, as_of="2025-11-25")

        assert len(realized) == 0

        from backend.data.database import GateBObservation
        obs = test_db.query(GateBObservation).first()
        assert obs is not None
        assert obs.forward_status == "pending"

    def test_pending_until_horizon_matures_as_of(self, test_db):
        """Forward prices after as_of are invisible, so an immature horizon stays pending."""
        _seed_signal(test_db)
        _seed_label(test_db)
        _seed_decision_run(test_db)
        _seed_prices(test_db, closes=(100.0, 101.0, 102.0, 103.0, 104.0, 105.0))
        test_db.commit()

        _record(test_db, horizon_days=5)
        early = _realize(test_db, as_of="2025-11-18")

        assert early == []
        from backend.data.database import GateBObservation
        obs = test_db.query(GateBObservation).first()
        assert obs.forward_status == "pending"
        assert obs.forward_return_net is None

        mature = _realize(test_db, as_of="2025-11-20")
        assert len(mature) == 1
        assert mature[0]["forward_status"] == "realized"

    def test_uses_observation_horizon_days(self, test_db):
        """A 3-day observation exits on the 3rd forward close, not a fixed 5th close."""
        from backend.backtest.costs import net_return_from_prices

        _seed_signal(test_db)
        _seed_label(test_db)
        _seed_decision_run(test_db)
        _seed_prices(test_db, closes=(100.0, 101.0, 102.0, 103.0, 104.0, 105.0))
        test_db.commit()

        _record(test_db, horizon_days=3)
        realized = _realize(test_db, as_of="2025-11-18")

        assert len(realized) == 1
        assert realized[0]["forward_return_net"] == pytest.approx(
            net_return_from_prices(100.0, 103.0),
            abs=1e-6,
        )

    def test_idempotent_realize(self, test_db):
        """Calling realize_returns twice returns results only once (no double-write)."""
        from backend.backtest.costs import net_return_from_prices

        _seed_signal(test_db)
        _seed_label(test_db)
        _seed_decision_run(test_db)
        _seed_prices(test_db, closes=(100.0, 101.0, 102.5, 101.5, 103.0, 104.0))
        test_db.commit()

        _record(test_db)
        realized1 = _realize(test_db)
        realized2 = _realize(test_db)

        assert len(realized1) == 1
        assert len(realized2) == 0  # already realized — not processed again

        from backend.data.database import GateBObservation
        obs = test_db.query(GateBObservation).first()
        assert obs.forward_status == "realized"
        expected_net = net_return_from_prices(100.0, 104.0)
        assert obs.forward_return_net == pytest.approx(expected_net, abs=1e-6)


# ---------------------------------------------------------------------------
# TestReport
# ---------------------------------------------------------------------------

class TestReport:
    def test_inconclusive_on_tiny_sample(self, test_db):
        """report() with 0 realized rows → INCONCLUSIVE / insufficient_sample."""
        from backend.research.gate_b_recorder import report

        result = report(test_db)
        assert result["verdict"] == "INCONCLUSIVE"
        assert result.get("reason") == "insufficient_sample"
        assert result["n_total"] == 0

    def test_inconclusive_on_small_sample(self, test_db):
        """report() with 5 realized rows (< 30 threshold) → INCONCLUSIVE."""
        _seed_signal(test_db)
        _seed_label(test_db)
        _seed_decision_run(test_db)
        _seed_prices(test_db, closes=(100.0, 101.0, 102.5, 101.5, 103.0, 104.0))
        test_db.commit()

        _record(test_db)
        _realize(test_db)

        from backend.research.gate_b_recorder import report
        result = report(test_db)
        assert result["verdict"] == "INCONCLUSIVE"
        assert result.get("reason") == "insufficient_sample"

    def test_no_production_table_written(self, test_db):
        """
        After record + realize, Signal / LongTermLabel / DecisionRun row counts
        must exactly match what was seeded (no extra writes to production tables).
        """
        _seed_signal(test_db)
        _seed_label(test_db)
        _seed_decision_run(test_db)
        _seed_prices(test_db, closes=(100.0, 101.0, 102.5, 101.5, 103.0, 104.0))
        test_db.commit()

        _record(test_db)
        _realize(test_db)

        assert test_db.query(Signal).count() == 1
        assert test_db.query(LongTermLabel).count() == 1
        assert test_db.query(DecisionRun).count() == 1


def test_source_dest_split_writes_only_to_dest(test_db):
    """record_observations(dest, source_db=src) reads signals/prices from src and
    writes observations ONLY to dest — the production-read / isolated-write split
    the scheduled CLI relies on (so production stock-sage.db is never written)."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.data.database import Base, GateBObservation
    from backend.research.gate_b_recorder import record_observations

    src_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(src_engine)
    src = sessionmaker(bind=src_engine)()
    _seed_signal(src, symbol="600519", sig_date="2025-11-15")
    _seed_prices(src, symbol="600519", entry_date="2025-11-15")
    src.commit()

    rows = record_observations(test_db, source_db=src, as_of="2025-11-20")
    assert len(rows) == 1
    assert test_db.query(GateBObservation).count() == 1          # written to dest
    assert src.execute(text("SELECT COUNT(*) FROM gate_b_observations")).scalar() == 0  # never to source
    src.close()


def _insert_realized(db, *, signal_id, gate_pass_variant, net, symbol="600519", signal_date="2026-05-15"):
    """Insert a realized GateBObservation directly (bypasses record/realize) for report() tests."""
    from datetime import UTC, datetime

    from backend.data.database import GateBObservation
    now = datetime.now(UTC).replace(tzinfo=None)
    obs = GateBObservation(
        symbol=symbol, signal_date=signal_date, as_of=signal_date,
        signal_id=signal_id, label_id=None,
        gate_pass_full=False, gate_pass_variant=gate_pass_variant,
        card_pass=False, ready_variant=False,
        recommendation="买入", composite_score=0.5, entry_close=100.0,
        horizon_days=5, forward_status="realized", realized_at=signal_date,
        forward_return_raw=net, forward_return_net=net,
        blockers_json="[]", blockers_variant_json="[]", checks_json="{}",
        gate_b_tracker_version="v1", recorded_at=now, updated_at=now,
    )
    db.add(obs)
    db.commit()
    return obs


def _insert_data_error(db, *, signal_id, gate_pass_variant=False, symbol="600519", signal_date="2026-05-15"):
    """Insert a data_error GateBObservation directly for report() DQ tests."""
    from datetime import UTC, datetime

    from backend.data.database import GateBObservation
    now = datetime.now(UTC).replace(tzinfo=None)
    obs = GateBObservation(
        symbol=symbol, signal_date=signal_date, as_of=signal_date,
        signal_id=signal_id, label_id=None,
        gate_pass_full=False, gate_pass_variant=gate_pass_variant,
        card_pass=False, ready_variant=False,
        recommendation="买入", composite_score=0.5, entry_close=100.0,
        horizon_days=5, forward_status="data_error", realized_at=None,
        forward_return_raw=None, forward_return_net=None,
        blockers_json="[]", blockers_variant_json="[]", checks_json="{}",
        gate_b_tracker_version="v1", recorded_at=now, updated_at=now,
    )
    db.add(obs)
    db.commit()
    return obs


def test_report_aborts_when_gate_never_passes(test_db):
    """gate_pass_rate < 0.02 must yield ABORT (bias threat), not REJECT —
    ABORT precedence per pre-registered §7."""
    from backend.research.gate_b_recorder import report
    for i in range(35):
        _insert_realized(test_db, signal_id=i, gate_pass_variant=False, net=0.01)
    r = report(test_db)
    assert r["n_total"] == 35
    assert r["gate_pass_rate"] == 0.0
    assert r["verdict"] == "ABORT", r
    assert r["reason"] == "gate_pass_rate_too_low"


def test_report_excludes_implausible_returns(test_db):
    """A single implausible 5-day return (data artifact) must be excluded as a
    data-quality failure, not averaged into the mean."""
    from backend.research.gate_b_recorder import report
    for i in range(30):
        _insert_realized(test_db, signal_id=i, gate_pass_variant=False, net=0.02)
    _insert_realized(test_db, signal_id=999, gate_pass_variant=False, net=10.0)  # 1000% — bad data
    r = report(test_db)
    assert r["n_realized"] == 31
    assert r["n_excluded_dq"] == 1
    assert r["n_total"] == 30
    # mean reflects the sane 0.02, not dragged toward 10.0
    assert r["avg_net_return_fail"] is not None and abs(r["avg_net_return_fail"] - 0.02) < 1e-6


def test_report_counts_data_error_rows_in_dq_abort_denominator(test_db):
    """data_error rows must remain visible to DQ stats and can trigger ABORT."""
    from backend.research.gate_b_recorder import report
    for i in range(20):
        _insert_realized(test_db, signal_id=i, gate_pass_variant=False, net=0.02)
    for i in range(20, 40):
        _insert_data_error(test_db, signal_id=i)

    r = report(test_db)

    assert r["n_realized"] == 20
    assert r["n_data_error"] == 20
    assert r["n_quality_total"] == 40
    assert r["n_excluded_dq"] == 20
    assert r["dq_exclusion_rate"] == pytest.approx(0.5)
    assert r["verdict"] == "ABORT"
    assert r["reason"] == "data_quality_exclusion_rate"


def test_report_does_not_promote_without_icir_stability_and_coverage(test_db, monkeypatch):
    """A positive spread alone is not enough to PROMOTE under the pre-registered gates."""
    import backend.tools.m27_alpha_diagnostic as diag
    from backend.research.gate_b_recorder import report
    monkeypatch.setattr(diag, "summarize_ic", lambda _series: {"icir": None, "ic_days": 0})

    for i in range(30):
        _insert_realized(test_db, signal_id=i, gate_pass_variant=True, net=0.02)
    for i in range(30, 60):
        _insert_realized(test_db, signal_id=i, gate_pass_variant=False, net=0.0)

    r = report(test_db)

    assert r["avg_net_return_delta"] is not None and r["avg_net_return_delta"] > 0.003
    assert r["icir"] is None
    assert r["stability_gate_pass"] is False
    assert r["coverage_gate_pass"] is False
    assert r["verdict"] == "INCONCLUSIVE"


def test_markdown_report_shows_promotion_blockers():
    from backend.tools.gate_b_tracker import _format_markdown

    body = _format_markdown({
        "verdict": "INCONCLUSIVE",
        "n_total": 30,
        "n_quality_total": 30,
        "n_data_error": 0,
        "n_excluded_dq": 0,
        "dq_exclusion_rate": 0.0,
        "n_pass": 30,
        "n_fail": 0,
        "gate_pass_rate": 1.0,
        "avg_net_return_pass": 0.01,
        "avg_net_return_fail": None,
        "avg_net_return_delta": None,
        "hit_rate_pass": 0.6,
        "icir": None,
        "ic_days": 0,
        "positive_delta_windows": None,
        "total_delta_windows": None,
        "coverage_loss": None,
        "stability_gate_pass": False,
        "coverage_gate_pass": False,
    })

    assert "| stability_gate_pass | False |" in body
    assert "| coverage_gate_pass | False |" in body
    assert "| positive_delta_windows | None |" in body


def test_realize_marks_hfq_artifact_as_data_error(test_db):
    """A 5-trading-day exit landing on an hfq-scale price (ratio >> 3x) is marked
    data_error, not realized — robust to the prices table's NULL adjustment tag."""
    from datetime import UTC, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.data.database import Base, GateBObservation
    from backend.research.gate_b_recorder import realize_returns

    src_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(src_engine)
    src = sessionmaker(bind=src_engine)()
    # 5 forward prices; the 5th is an hfq artifact (¥1225 vs qfq entry ¥3.71)
    _seed_prices(src, symbol="000002", entry_date="2026-05-20",
                 closes=(3.60, 3.50, 3.50, 3.50, 1225.49))
    src.commit()

    now = datetime.now(UTC).replace(tzinfo=None)
    obs = GateBObservation(
        symbol="000002", signal_date="2026-05-19", as_of="2026-05-19", signal_id=1,
        gate_pass_full=False, gate_pass_variant=False, card_pass=False, ready_variant=False,
        entry_close=3.71, horizon_days=5, forward_status="pending",
        blockers_json="[]", blockers_variant_json="[]", checks_json="{}",
        gate_b_tracker_version="v1", recorded_at=now, updated_at=now,
    )
    test_db.add(obs)
    test_db.commit()

    realize_returns(test_db, source_db=src, as_of="2026-06-02")
    refreshed = test_db.query(GateBObservation).filter(GateBObservation.id == obs.id).first()
    assert refreshed.forward_status == "data_error"
    assert refreshed.forward_return_net is None
    src.close()
