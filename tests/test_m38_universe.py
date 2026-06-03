"""M38 Dynamic Universe / Survivorship Guard — hermetic isolated-sqlite tests."""
from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

import pytest

# ── hash determinism ──────────────────────────────────────────────────────────

def test_hash_determinism():
    """Same symbol list always yields the same 64-char hex string."""
    from backend.research.universe_guard import compute_universe_hash

    symbols = ["600519", "300308", "603986"]
    h1 = compute_universe_hash(symbols)
    h2 = compute_universe_hash(symbols)
    assert h1 == h2
    assert len(h1) == 64
    assert h1.isalnum()


def test_hash_order_independence():
    """Reversed input list yields identical hash as sorted input."""
    from backend.research.universe_guard import compute_universe_hash

    symbols = ["600519", "300308", "603986"]
    h_fwd = compute_universe_hash(symbols)
    h_rev = compute_universe_hash(list(reversed(symbols)))
    assert h_fwd == h_rev


def test_hash_matches_m27_algorithm():
    """compute_universe_hash({'A','B','C'}) matches the reference SHA-256 formula."""
    from backend.research.universe_guard import compute_universe_hash

    syms = {"A", "B", "C"}
    expected = hashlib.sha256(
        json.dumps(
            sorted(list(syms)),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert compute_universe_hash(syms) == expected


def test_hash_changes_on_different_membership():
    """Adding a symbol changes the universe_hash."""
    from backend.research.universe_guard import compute_universe_hash

    h1 = compute_universe_hash(["600519", "300308"])
    h2 = compute_universe_hash(["600519", "300308", "603986"])
    assert h1 != h2


# ── snapshot_universe ─────────────────────────────────────────────────────────

def test_snapshot_universe_returns_dict_with_expected_keys(test_db):
    from backend.research.universe_guard import snapshot_universe

    result = snapshot_universe(
        test_db,
        symbols=["600519", "300308", "603986"],
        cutoff_date="2024-01-01",
        market_filter="CN",
        context="backtest_test",
    )
    for key in ("id", "universe_hash", "cutoff_date", "market_filter", "symbols", "n_symbols", "created_at"):
        assert key in result, f"missing key: {key}"
    assert result["id"] is not None
    assert result["universe_hash"] is not None
    assert len(result["universe_hash"]) == 64
    assert result["cutoff_date"] == "2024-01-01"
    assert result["market_filter"] == "CN"
    assert result["n_symbols"] == 3
    assert result["created_at"] is not None


def test_snapshot_universe_idempotent_on_same_membership(test_db):
    """Two calls with identical symbols + cutoff_date return the same row id."""
    from backend.research.universe_guard import snapshot_universe

    r1 = snapshot_universe(test_db, symbols=["600519", "300308"], cutoff_date="2024-01-01")
    r2 = snapshot_universe(test_db, symbols=["600519", "300308"], cutoff_date="2024-01-01")
    assert r1["id"] == r2["id"]


def test_snapshot_universe_distinct_hash_on_different_membership(test_db):
    """Different symbol sets produce different hashes and different rows."""
    from backend.research.universe_guard import snapshot_universe

    r1 = snapshot_universe(test_db, symbols=["600519", "300308"], cutoff_date="2024-01-01")
    r2 = snapshot_universe(test_db, symbols=["600519", "300308", "603986"], cutoff_date="2024-01-01")
    assert r1["universe_hash"] != r2["universe_hash"]
    assert r1["id"] != r2["id"]


def test_snapshot_universe_stores_full_symbol_list(test_db):
    """symbols field in returned dict equals sorted input list."""
    from backend.research.universe_guard import snapshot_universe

    input_symbols = ["603986", "300308", "600519"]  # unsorted intentionally
    result = snapshot_universe(test_db, symbols=input_symbols, cutoff_date="2024-01-01")
    assert result["symbols"] == sorted(input_symbols)


def test_snapshot_universe_disabled_when_flag_false(test_db):
    """When universe_guard_enabled=False, snapshot_universe returns empty dict without writing."""
    from backend.research.universe_guard import snapshot_universe

    with patch("backend.research.universe_guard.settings") as mock_settings:
        mock_settings.universe_guard_enabled = False
        result = snapshot_universe(test_db, symbols=["600519", "300308"], cutoff_date="2024-01-01")
    assert result == {}

    # Confirm nothing was written
    from backend.data.database import UniverseSnapshot
    count = test_db.query(UniverseSnapshot).count()
    assert count == 0


# ── survivorship bias / current vs historical ────────────────────────────────

def test_current_vs_historical_survivorship(test_db, sample_stocks):
    """Snapshot at cutoff_date='2023-01-01' with 3 symbols; deactivate one;
    get_snapshot_for_cutoff still returns all 3 in symbols field."""
    from backend.data.database import Stock
    from backend.research.universe_guard import get_snapshot_for_cutoff, snapshot_universe

    original_symbols = ["600519", "300308", "603986"]
    snapshot_universe(test_db, symbols=original_symbols, cutoff_date="2023-01-01")

    # Deactivate one stock AFTER the snapshot was taken
    stock = test_db.query(Stock).filter(Stock.symbol == "603986").first()
    stock.active = False
    test_db.commit()

    # The historical snapshot must still contain the deactivated symbol
    snap = get_snapshot_for_cutoff(test_db, "2023-01-01")
    assert snap is not None
    assert set(snap["symbols"]) == set(original_symbols)
    assert "603986" in snap["symbols"]


# ── get_snapshot_for_cutoff ───────────────────────────────────────────────────

def test_get_snapshot_for_cutoff_returns_nearest_earlier(test_db):
    """Insert snapshot at '2023-01-01'; query '2023-06-01' returns it; '2022-12-31' returns None."""
    from backend.research.universe_guard import get_snapshot_for_cutoff, snapshot_universe

    snapshot_universe(test_db, symbols=["600519", "300308"], cutoff_date="2023-01-01")

    snap = get_snapshot_for_cutoff(test_db, "2023-06-01")
    assert snap is not None
    assert snap["cutoff_date"] == "2023-01-01"

    none_snap = get_snapshot_for_cutoff(test_db, "2022-12-31")
    assert none_snap is None


def test_get_snapshot_for_cutoff_market_filter_isolation(test_db):
    """CN snapshot and US snapshot at same cutoff_date do not collide."""
    from backend.research.universe_guard import get_snapshot_for_cutoff, snapshot_universe

    snapshot_universe(test_db, symbols=["600519"], cutoff_date="2024-01-01", market_filter="CN")
    snapshot_universe(test_db, symbols=["AAPL", "MSFT"], cutoff_date="2024-01-01", market_filter="US")

    cn = get_snapshot_for_cutoff(test_db, "2024-01-01", "CN")
    us = get_snapshot_for_cutoff(test_db, "2024-01-01", "US")

    assert cn is not None
    assert us is not None
    assert cn["symbols"] == ["600519"]
    assert set(us["symbols"]) == {"AAPL", "MSFT"}
    assert cn["universe_hash"] != us["universe_hash"]


# ── list_snapshots ────────────────────────────────────────────────────────────

def test_list_snapshots_ordered_by_cutoff_desc(test_db):
    """Three snapshots at different dates returned newest-first."""
    from backend.research.universe_guard import list_snapshots, snapshot_universe

    snapshot_universe(test_db, symbols=["600519"], cutoff_date="2023-01-01")
    snapshot_universe(test_db, symbols=["600519", "300308"], cutoff_date="2024-06-01")
    snapshot_universe(test_db, symbols=["600519", "300308", "603986"], cutoff_date="2022-01-01")

    snaps = list_snapshots(test_db)
    assert len(snaps) == 3
    dates = [s["cutoff_date"] for s in snaps]
    assert dates == sorted(dates, reverse=True)


def test_list_snapshots_returns_all_inserted(test_db):
    """list_snapshots returns all inserted rows."""
    from backend.research.universe_guard import list_snapshots, snapshot_universe

    snapshot_universe(test_db, symbols=["600519"], cutoff_date="2023-01-01", market_filter="CN")
    snapshot_universe(test_db, symbols=["AAPL"], cutoff_date="2023-01-01", market_filter="US")

    all_snaps = list_snapshots(test_db)
    assert len(all_snaps) == 2

    cn_snaps = list_snapshots(test_db, market_filter="CN")
    assert len(cn_snaps) == 1
    assert cn_snaps[0]["market_filter"] == "CN"


# ── get_snapshot ──────────────────────────────────────────────────────────────

def test_get_snapshot_returns_correct_row(test_db):
    from backend.research.universe_guard import get_snapshot, snapshot_universe

    created = snapshot_universe(test_db, symbols=["600519", "300308"], cutoff_date="2024-01-01")
    fetched = get_snapshot(test_db, created["id"])
    assert fetched is not None
    assert fetched["id"] == created["id"]
    assert fetched["universe_hash"] == created["universe_hash"]


def test_get_snapshot_returns_none_for_missing_id(test_db):
    from backend.research.universe_guard import get_snapshot

    assert get_snapshot(test_db, 999999) is None


# ── provenance_completeness_report ────────────────────────────────────────────

def test_provenance_completeness_report_keys(test_db):
    """report dict contains all required keys."""
    from backend.research.universe_guard import provenance_completeness_report

    report = provenance_completeness_report(test_db)
    expected_keys = {
        "price_source_pct",
        "price_fetched_at_pct",
        "price_adjustment_pct",
        "financial_fetched_at_pct",
        "financial_source_available",
        "price_rows_total",
        "financial_rows_total",
        "checked_at",
    }
    assert expected_keys.issubset(set(report.keys()))


def test_provenance_completeness_financial_source_available_false(test_db):
    """financial_source_available is always False (column does not exist on FinancialMetric)."""
    from backend.research.universe_guard import provenance_completeness_report

    report = provenance_completeness_report(test_db)
    assert report["financial_source_available"] is False


def test_provenance_completeness_report_runs_without_error(test_db, sample_stocks):
    """Report runs on an empty DB (no prices) without raising."""
    from backend.research.universe_guard import provenance_completeness_report

    report = provenance_completeness_report(test_db)
    assert report["price_rows_total"] == 0
    assert report["financial_rows_total"] == 0
    assert report["price_source_pct"] == 0.0
    assert isinstance(report["checked_at"], str)


def test_provenance_completeness_with_symbol_filter(test_db):
    """Passing symbols= filters price/financial rows to those symbols."""
    from datetime import datetime

    from backend.data.database import Price
    from backend.research.universe_guard import provenance_completeness_report

    # Insert price rows: one with source, one without
    p1 = Price(symbol="600519", date="2024-01-01", open=100.0, high=105.0, low=99.0,
               close=103.0, volume=1000.0, source="tushare", fetched_at=datetime.utcnow())
    p2 = Price(symbol="300308", date="2024-01-01", open=50.0, high=52.0, low=49.0,
               close=51.0, volume=500.0, source=None)
    test_db.add_all([p1, p2])
    test_db.commit()

    # Filtered to 600519 only — should see 100% source coverage
    report_filtered = provenance_completeness_report(test_db, symbols=["600519"])
    assert report_filtered["price_rows_total"] == 1
    assert report_filtered["price_source_pct"] == pytest.approx(1.0)

    # Unfiltered — should see 50% source coverage
    report_all = provenance_completeness_report(test_db)
    assert report_all["price_rows_total"] == 2
    assert report_all["price_source_pct"] == pytest.approx(0.5)
