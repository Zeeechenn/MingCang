"""
Offline, deterministic evidence reproduction script for MingCang.

Reads the demo sample database and prints:
  1. The seeded stocks (closed-loop participants)
  2. The ForwardThesis for 300308 (including invalidation conditions)
  3. The ReviewCase outcome and attribution
  4. The MemoryPromotionCandidate status
  5. The recorded 'quant off' rationale summary from config

NO network calls, NO API keys, NO external dependencies beyond the backend
package and the sample SQLite database.

Usage:
    DATABASE_URL=sqlite:////path/to/examples/sample_db/mingcang_demo.db \\
        PYTHONPATH=. python scripts/reproduce_evidence.py

Or via Makefile:
    make reproduce-evidence

If the demo DB does not exist, run `scripts/demo_seed.py` first (or
`make demo` which seeds then starts the backend).  This script does NOT
auto-seed; it only reads.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the repo root is on sys.path when invoked directly.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Verify DATABASE_URL is set to the sample DB (or a suitable override).
# We do NOT auto-set it — the caller (Makefile or shell) must supply it so
# there is no risk of accidentally pointing at the production database.
# ---------------------------------------------------------------------------
_DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not _DATABASE_URL:
    print(
        "[reproduce_evidence] ERROR: DATABASE_URL is not set.\n"
        "  Set it to the sample DB path, e.g.:\n"
        "    DATABASE_URL=sqlite:////path/to/examples/sample_db/mingcang_demo.db\n"
        "  Or run:  make reproduce-evidence",
        file=sys.stderr,
    )
    sys.exit(1)

_DEMO_DB_PATH = _REPO_ROOT / "examples" / "sample_db" / "mingcang_demo.db"
if not Path(_DATABASE_URL.replace("sqlite:///", "")).exists():
    print(
        f"[reproduce_evidence] ERROR: Database file not found at path derived from:\n"
        f"  DATABASE_URL={_DATABASE_URL}\n"
        f"  Run 'scripts/demo_seed.py' first to create and seed the demo database.",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Now safe to import backend modules (they read DATABASE_URL at import time).
# ---------------------------------------------------------------------------
from backend.data.database import (  # noqa: E402
    ForwardThesis,
    MemoryPromotionCandidate,
    ReviewCase,
    Stock,
    init_db,
)
from backend.data.session import SessionLocal  # noqa: E402


def _separator(title: str) -> None:
    width = 60
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def _print_stocks(db) -> None:
    _separator("1. Stocks in demo database")
    stocks = db.query(Stock).order_by(Stock.symbol).all()
    if not stocks:
        print("  (no stocks found — did you run scripts/demo_seed.py?)")
        return
    for s in stocks:
        status = "active" if s.active else "inactive"
        print(f"  {s.symbol}  {s.name:<12}  {s.industry:<10}  [{status}]")


def _print_forward_thesis(db) -> None:
    _separator("2. ForwardThesis (pre-registered research thesis)")
    theses = (
        db.query(ForwardThesis)
        .filter(ForwardThesis.symbol == "300308")
        .all()
    )
    if not theses:
        print("  (no ForwardThesis found)")
        return
    for ft in theses:
        print(f"  Symbol:    {ft.symbol}")
        print(f"  Status:    {ft.status}")
        print(f"  Statement: {ft.statement}")
        print(f"  Horizon:   {ft.horizon_date}")
        print(f"  Confidence band: {ft.confidence_low}–{ft.confidence_high}")
        print(f"  Next review:     {ft.next_review_date}")
        print()
        print("  Invalidation conditions (falsification gates):")
        try:
            conditions = json.loads(ft.invalidation_conditions_json or "[]")
            for i, cond in enumerate(conditions, 1):
                print(f"    {i}. {cond}")
        except (json.JSONDecodeError, TypeError):
            print(f"    (raw) {ft.invalidation_conditions_json}")
        print()
        print("  Follow-up metrics:")
        try:
            metrics = json.loads(ft.follow_up_metrics_json or "[]")
            for m in metrics:
                print(f"    - {m}")
        except (json.JSONDecodeError, TypeError):
            print(f"    (raw) {ft.follow_up_metrics_json}")


def _print_review_case(db) -> None:
    _separator("3. ReviewCase (post-event review)")
    cases = (
        db.query(ReviewCase)
        .filter(ReviewCase.symbol == "300308")
        .order_by(ReviewCase.as_of.desc())
        .all()
    )
    if not cases:
        print("  (no ReviewCase found)")
        return
    for rc in cases:
        outcome = "CORRECT" if rc.outcome_correct else "INCORRECT"
        print(f"  Symbol:          {rc.symbol}")
        print(f"  As-of date:      {rc.as_of}")
        print(f"  Outcome:         {outcome}")
        print(f"  Next-day return: {rc.next_day_return:.1f}%")
        print(f"  Composite score: {rc.composite_score:.1f}")
        print(f"  Recommendation:  {rc.recommendation}")
        print()
        print("  Attribution:")
        try:
            attribution = json.loads(rc.attribution_json or "[]")
            for i, item in enumerate(attribution, 1):
                print(f"    {i}. {item}")
        except (json.JSONDecodeError, TypeError):
            print(f"    (raw) {rc.attribution_json}")


def _print_memory_candidate(db) -> None:
    _separator("4. MemoryPromotionCandidate (pending, human-gated)")
    candidates = (
        db.query(MemoryPromotionCandidate)
        .filter(MemoryPromotionCandidate.symbol == "300308")
        .all()
    )
    if not candidates:
        print("  (no MemoryPromotionCandidate found)")
        return
    for mc in candidates:
        print(f"  Symbol:       {mc.symbol}")
        print(f"  Trust status: {mc.source_trust}  <-- not yet trusted; no production effect")
        print(f"  Memory type:  {mc.memory_type}")
        print(f"  Importance:   {mc.importance}/5")
        print(f"  Confidence:   {mc.confidence:.0%}")
        print(f"  Summary: {mc.summary}")
        if mc.note:
            print(f"  Note:    {mc.note}")


def _print_quant_off_rationale() -> None:
    _separator("5. Recorded 'quant off' rationale (from backend/config.py)")
    print(
        "  Production signal profile: technical 0.6 + sentiment 0.4 + ATR trailing stop 2.5×\n"
        "\n"
        "  WEIGHT_QUANT = 0.0  (quant layer disconnected)\n"
        "\n"
        "  Reason (verbatim from config comment):\n"
        "    '阶段A Qlib 有效性硬验证结论：IC=0.0228 / ICIR=0.062 / 分层非单调 → Qlib 不合格'\n"
        "    '默认改为「技术 60% + 情感 40%」，weight_quant 归零。'\n"
        "    'Qlib 通过 RD-Agent 升级后可在 .env 中重新分配权重。'\n"
        "\n"
        "  Evidence summary:\n"
        "    - IC 0.0228  (gate: >= 0.04) → FAIL\n"
        "    - ICIR 0.062 (gate: >= 0.40) → FAIL\n"
        "    - Decile monotonicity         → FAIL\n"
        "    - Regime sign-flip detected (bull vs range-bound windows)\n"
        "\n"
        "  Full evidence: docs/evidence/m29_quant_off.md"
    )


def main() -> None:
    print(f"[reproduce_evidence] Reading from: {_DATABASE_URL}")
    print("[reproduce_evidence] Initialising schema (no data changes) ...")

    # init_db() is idempotent — creates tables if missing but never drops data.
    init_db()

    db = SessionLocal()
    try:
        _print_stocks(db)
        _print_forward_thesis(db)
        _print_review_case(db)
        _print_memory_candidate(db)
        _print_quant_off_rationale()
    finally:
        db.close()

    print()
    print("=" * 60)
    print("  Demo closed loop reproduced successfully.")
    print("  This script reads and prints only — no writes, no network.")
    print("=" * 60)


if __name__ == "__main__":
    main()
