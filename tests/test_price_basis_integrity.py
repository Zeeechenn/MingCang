"""M69 follow-up (2026-09-02 audit): provider-aware drift classification.

The audit found that a drift event on its own could not distinguish "the
provider re-based this series" from "a different provider answered today" —
the 47 recorded events split across four providers — and that the detector
under-reports splicing because it only sees a symbol when a backfill overlaps
stored rows.  These tests pin the three follow-ups: recording the stored rows'
provider, reporting source mixing as its own metric, and gating a day whose
drift nobody cleared.
"""
from __future__ import annotations

import json

import pytest

from backend.data.price_quality import (
    UNKNOWN_PRICE_SOURCE,
    classify_drift_source,
    summarize_basis_drift_events,
    summarize_source_mixing,
)
from backend.ops.one_loop_continuity import (
    PANEL_WORK_METRIC_INPUTS,
    _daily_panel_work_metrics,
)


class TestClassifyDriftSource:
    def test_same_provider_is_a_genuine_rebasing(self):
        assert classify_drift_source("tickflow_cn", ["tickflow_cn"]) is False

    def test_different_provider_is_a_cross_source_comparison(self):
        assert classify_drift_source("tickflow_cn", ["akshare_sina_cn"]) is True

    def test_spliced_history_counts_as_cross_source_even_if_fetch_source_appears(self):
        assert classify_drift_source("tickflow_cn", ["tickflow_cn", "akshare_sina_cn"]) is True

    @pytest.mark.parametrize(
        "fetch, stored",
        [(None, ["tickflow_cn"]), ("tickflow_cn", []), ("tickflow_cn", None), ("tickflow_cn", [""])],
    )
    def test_unknown_when_either_side_is_missing(self, fetch, stored):
        assert classify_drift_source(fetch, stored) is None


class TestSummarizeSourceMixing:
    def test_counts_symbols_by_number_of_distinct_sources(self):
        report = summarize_source_mixing(
            [("A", "x"), ("A", "x"), ("B", "x"), ("B", "y"), ("C", "x"), ("C", "y"), ("C", "z")]
        )
        assert report.total_symbols == 3
        assert report.single_source_symbols == 1
        assert report.mixed_symbols == 2
        assert report.distribution == {1: 1, 2: 1, 3: 1}
        assert report.clean is False

    def test_null_source_is_its_own_bucket_not_silently_merged(self):
        # Rows written before provenance existed have an unknown basis; folding
        # them into whatever sits next to them is what hid the seams.
        report = summarize_source_mixing([("A", None), ("A", "x")])
        assert report.mixed_symbols == 1
        assert report.worst == [("A", [UNKNOWN_PRICE_SOURCE, "x"])]

    def test_all_single_source_is_clean(self):
        report = summarize_source_mixing([("A", "x"), ("B", "x")])
        assert report.clean is True
        assert report.mixed_symbols == 0
        assert "all single-source" in report.describe()

    def test_worst_is_ordered_by_source_count_then_symbol_and_capped(self):
        rows = [("A", "x"), ("A", "y"), ("B", "x"), ("B", "y"), ("B", "z")]
        report = summarize_source_mixing(rows, worst_limit=1)
        assert report.worst == [("B", ["x", "y", "z"])]

    def test_payload_is_json_serializable(self):
        report = summarize_source_mixing([("A", "x"), ("A", None)])
        assert json.loads(json.dumps(report.to_payload()))["mixed_symbols"] == 1


class TestSummarizeBasisDriftEvents:
    def test_same_source_events_gate_the_day(self):
        result = summarize_basis_drift_events([{"symbol": "600547", "cross_source": False}])
        assert result["same_source"] == ["600547"]
        assert result["uncleared_symbols"] == ["600547"]
        assert result["clean"] is False

    def test_cross_source_events_are_reported_but_do_not_gate(self):
        # Rebasing onto whichever provider answered today would just move the
        # seam, so a spliced series is a cleanup task, not a same-day blocker.
        result = summarize_basis_drift_events([{"symbol": "000858", "cross_source": True}])
        assert result["cross_source"] == ["000858"]
        assert result["uncleared_symbols"] == []
        assert result["clean"] is True

    def test_unknown_classification_gates_fail_closed(self):
        result = summarize_basis_drift_events([{"symbol": "601899", "cross_source": None}])
        assert result["unknown_source"] == ["601899"]
        assert result["clean"] is False

    def test_no_events_is_clean(self):
        result = summarize_basis_drift_events([])
        assert result == {
            "status": "available",
            "events": 0,
            "same_source": [],
            "cross_source": [],
            "unknown_source": [],
            "uncleared_symbols": [],
            "uncleared": 0,
            "clean": True,
        }

    def test_mixed_batch_deduplicates_symbols(self):
        result = summarize_basis_drift_events([
            {"symbol": "600547", "cross_source": False},
            {"symbol": "600547", "cross_source": False},
            {"symbol": "000858", "cross_source": True},
        ])
        assert result["events"] == 3
        assert result["same_source"] == ["600547"]
        assert result["uncleared"] == 1


def _panel(work_metrics: dict) -> dict:
    base = {name: {"status": "available"} for name in PANEL_WORK_METRIC_INPUTS}
    base.update(work_metrics)
    return {"work_metrics": base}


class TestContinuityBlocker:
    def test_absent_metric_is_not_a_blocker(self):
        # Panels written before this follow-up must not retroactively invalidate
        # days that are otherwise complete.
        metrics, blockers = _daily_panel_work_metrics(_panel({}))
        assert blockers == []
        assert "price_basis_integrity" not in metrics

    def test_clean_metric_is_not_a_blocker(self):
        metrics, blockers = _daily_panel_work_metrics(
            _panel({"price_basis_integrity": {"status": "available", "clean": True}})
        )
        assert blockers == []
        assert metrics["price_basis_integrity"]["clean"] is True

    def test_uncleared_drift_blocks_the_day(self):
        _, blockers = _daily_panel_work_metrics(
            _panel({
                "price_basis_integrity": {
                    "status": "available",
                    "clean": False,
                    "uncleared_symbols": ["600547"],
                }
            })
        )
        assert blockers == ["uncleared_adjustment_basis_drift"]

    def test_unavailable_metric_is_ignored_rather_than_guessed(self):
        _, blockers = _daily_panel_work_metrics(
            _panel({"price_basis_integrity": {"status": "unavailable", "reason": "query_failed"}})
        )
        assert blockers == []

    def test_price_basis_is_not_a_required_input(self):
        # Adding it to PANEL_WORK_METRIC_INPUTS would blank every historical day.
        assert "price_basis_integrity" not in PANEL_WORK_METRIC_INPUTS


class TestDriftEventRecordsStoredProvider:
    """The write path must record BOTH providers, or the event stays ambiguous."""

    @staticmethod
    def _seed(db, *, source: str | None, close: float = 30.0, rows: int = 20):
        from backend.data.database import Price

        for i in range(rows):
            db.add(Price(
                symbol="600547", asset_key="CN:600547", market="CN", currency="CNY",
                date=f"2026-08-{i + 1:02d}", open=close, high=close, low=close,
                close=close, volume=1000.0, source=source,
            ))
        db.commit()

    @staticmethod
    def _fetched(close: float = 30.0, rows: int = 20):
        pd = pytest.importorskip("pandas")
        return pd.DataFrame(
            {"close": [close] * rows},
            index=[f"2026-08-{i + 1:02d}" for i in range(rows)],
        )

    @staticmethod
    def _events(db):
        from backend.data.models.degradation import DegradationEvent

        return [
            json.loads(row.context_json)
            for row in db.query(DegradationEvent)
            .filter(DegradationEvent.category == "adjustment_basis_drift")
            .all()
        ]

    def test_same_provider_drift_is_recorded_as_a_rebasing(self, test_db):
        from backend.data.market_persistence import _check_adjustment_basis_drift

        self._seed(test_db, source="tickflow_cn", close=30.0)
        _check_adjustment_basis_drift(
            test_db, symbol="600547", asset_key="CN:600547",
            fetched=self._fetched(close=29.5), source="tickflow_cn",
        )
        events = self._events(test_db)
        assert len(events) == 1
        assert events[0]["stored_sources"] == ["tickflow_cn"]
        assert events[0]["cross_source"] is False

    def test_different_provider_drift_is_recorded_as_cross_source(self, test_db):
        from backend.data.market_persistence import _check_adjustment_basis_drift

        self._seed(test_db, source="akshare_sina_cn", close=30.0)
        _check_adjustment_basis_drift(
            test_db, symbol="600547", asset_key="CN:600547",
            fetched=self._fetched(close=29.5), source="tickflow_cn",
        )
        events = self._events(test_db)
        assert len(events) == 1
        assert events[0]["stored_sources"] == ["akshare_sina_cn"]
        assert events[0]["cross_source"] is True

    def test_missing_stored_provider_is_recorded_as_unknown_not_guessed(self, test_db):
        from backend.data.market_persistence import _check_adjustment_basis_drift

        self._seed(test_db, source=None, close=30.0)
        _check_adjustment_basis_drift(
            test_db, symbol="600547", asset_key="CN:600547",
            fetched=self._fetched(close=29.5), source="tickflow_cn",
        )
        events = self._events(test_db)
        assert len(events) == 1
        assert events[0]["stored_sources"] == []
        assert events[0]["cross_source"] is None

    def test_clean_series_records_nothing(self, test_db):
        from backend.data.market_persistence import _check_adjustment_basis_drift

        self._seed(test_db, source="tickflow_cn", close=30.0)
        _check_adjustment_basis_drift(
            test_db, symbol="600547", asset_key="CN:600547",
            fetched=self._fetched(close=30.0), source="tickflow_cn",
        )
        assert self._events(test_db) == []
