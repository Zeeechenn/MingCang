"""Guards on the operator clearance channel for adjustment-basis drift.

A clearance suppresses a real gate, so the CLI has to be harder to misuse than
the thing it unblocks: it must refuse to clear an event that is not actually
gating (no pre-clearing a future day, no laundering a cross-source event), it
must refuse anonymous or unexplained clearances, and it must leave the original
degradation_events row untouched.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.data.database import Base
from backend.data.models.degradation import (
    AdjustmentBasisClearance,
    DegradationEvent,
)


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr("backend.tools.acknowledge_basis_drift.SessionLocal", factory)
    return factory


def _add_drift(factory, symbol: str, day: str, *, cross_source: bool | None):
    db = factory()
    try:
        db.add(
            DegradationEvent(
                ts=datetime.fromisoformat(f"{day} 14:38:53"),
                component="market_persistence",
                category="adjustment_basis_drift",
                provider="tickflow_cn",
                error=f"{symbol}: uniform additive offset",
                context_json=json.dumps({"symbol": symbol, "cross_source": cross_source}),
            )
        )
        db.commit()
    finally:
        db.close()


def _run(argv):
    from backend.tools.acknowledge_basis_drift import main

    return main(argv)


BASE_ARGS = ["--operator", "owner", "--reason", "provider cash-dividend re-base, reviewed"]


class TestClearanceGuards:
    def test_refuses_to_clear_a_day_with_no_gating_event(self, session_factory):
        assert _run(["--symbol", "603993", "--date", "2026-09-09", *BASE_ARGS, "--apply"]) == 4
        db = session_factory()
        try:
            assert db.query(AdjustmentBasisClearance).count() == 0
        finally:
            db.close()

    def test_refuses_to_clear_a_cross_source_event(self, session_factory):
        # Cross-source never gated; "clearing" it would only create a misleading
        # record that an operator resolved something.
        _add_drift(session_factory, "000858", "2026-09-09", cross_source=True)
        assert _run(["--symbol", "000858", "--date", "2026-09-09", *BASE_ARGS, "--apply"]) == 4

    @pytest.mark.parametrize("field, value", [("--operator", "   "), ("--reason", "")])
    def test_refuses_anonymous_or_unexplained_clearances(self, session_factory, field, value):
        _add_drift(session_factory, "603993", "2026-09-09", cross_source=False)
        argv = ["--symbol", "603993", "--date", "2026-09-09", *BASE_ARGS, "--apply"]
        argv[argv.index(field) + 1] = value
        assert _run(argv) == 2

    def test_rejects_a_malformed_date(self, session_factory):
        with pytest.raises(SystemExit):
            _run(["--symbol", "603993", "--date", "09/09/2026", *BASE_ARGS])


class TestClearanceWrite:
    def test_dry_run_is_the_default_and_writes_nothing(self, session_factory):
        _add_drift(session_factory, "603993", "2026-09-09", cross_source=False)
        assert _run(["--symbol", "603993", "--date", "2026-09-09", *BASE_ARGS]) == 0
        db = session_factory()
        try:
            assert db.query(AdjustmentBasisClearance).count() == 0
        finally:
            db.close()

    def test_apply_writes_an_attributable_row_and_keeps_the_event(self, session_factory):
        _add_drift(session_factory, "603993", "2026-09-09", cross_source=False)
        assert _run(["--symbol", "603993", "--date", "2026-09-09", *BASE_ARGS, "--apply"]) == 0
        db = session_factory()
        try:
            row = db.query(AdjustmentBasisClearance).one()
            assert (row.symbol, row.event_date, row.operator) == ("603993", "2026-09-09", "owner")
            assert row.reason
            # The evidence that drift happened must survive the acknowledgement.
            assert db.query(DegradationEvent).count() == 1
        finally:
            db.close()

    def test_re_running_is_idempotent(self, session_factory):
        _add_drift(session_factory, "603993", "2026-09-09", cross_source=False)
        argv = ["--symbol", "603993", "--date", "2026-09-09", *BASE_ARGS, "--apply"]
        assert _run(argv) == 0
        assert _run(argv) == 0
        db = session_factory()
        try:
            assert db.query(AdjustmentBasisClearance).count() == 1
        finally:
            db.close()

    def test_a_clearance_is_scoped_to_its_own_day(self, session_factory):
        _add_drift(session_factory, "603993", "2026-09-09", cross_source=False)
        _add_drift(session_factory, "603993", "2026-09-10", cross_source=False)
        assert _run(["--symbol", "603993", "--date", "2026-09-09", *BASE_ARGS, "--apply"]) == 0
        # The next day's drift is a new event and must still gate.
        from backend.tools.acknowledge_basis_drift import _gating_symbols

        db = session_factory()
        try:
            gating, _ = _gating_symbols(db, "2026-09-10")
            assert gating == {"603993"}
        finally:
            db.close()
