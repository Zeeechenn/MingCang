# Reproducible Closed Loop: Demo Walkthrough

This document narrates the demo closed loop that can be reproduced entirely
offline against the sample database.  No API keys or network access are
required.

---

## What the Demo Shows

The sample database (`examples/sample_db/mingcang_demo.db`) contains a
coherent, minimal closed loop for the stock **300308 (中际旭创)**:

| Step | Object | Description |
|---|---|---|
| 1 | `Stock` | Three A-share stocks seeded: 600519, 300308, 601318 |
| 2 | `ForwardThesis` | A falsifiable research thesis for 300308 |
| 3 | `ReviewCase` | A post-event review confirming the thesis partially held |
| 4 | `MemoryPromotionCandidate` | A pending memory item awaiting human promotion |

This is the L0→L2→L4 loop described in the architecture: thesis imported,
invalidation conditions recorded, review executed, candidate surfaced — but
**not auto-promoted**.

---

## Step-by-Step Loop

### 1. Import a Research Thesis (L2)

The `ForwardThesis` for 300308 captures:

- **Statement**: "AI算力景气持续，中际旭创CPO订单将在2026Q3前完成年度目标"
- **Horizon**: 2026-09-30
- **Confidence band**: 55–75%
- **Invalidation conditions** (falsification gates):
  1. 2026Q2财报CPO收入同比增速跌破20%
  2. 北美大客户订单明确推迟超过两个季度
  3. 行业主要竞争对手以低于成本价抢单
- **Follow-up metrics**: 季度CPO发货量, 北美数据中心资本开支
- **Review cadence**: every 30 days, next review 2026-07-15

The invalidation conditions are stored in the database as JSON and inspected
at each scheduled review.  If any condition is met, the thesis moves to
`invalidated` status and downstream memory candidates are blocked.

### 2. Signal Generation (L3, skipped in demo)

A demo `Signal` row for 2026-06-03 is also seeded for completeness
(composite_score=42.0, recommendation="可小仓试错").  In production this
would come from the daily signal pipeline.  In the demo it is a static seed.

### 3. Post-Event Review (L4)

The `ReviewCase` (as_of 2026-06-01) records:

- `outcome_correct = True` — the signal direction was confirmed by the 3.2%
  next-day return.
- Attribution:
  1. 技术面突破短期阻力位，量能配合良好
  2. CPO出货量超预期，订单景气确认
  3. 大盘RSRS处于强势区间，未触发宏观否决

This is the "结果教会了什么" L4 step: the system records *why* the outcome
was what it was, not just *that* the outcome occurred.

### 4. Pending Memory Candidate (L0 gate, human-gated)

A `MemoryPromotionCandidate` is created with:

- `source_trust = "pending"` — it cannot influence any decision until promoted
- `summary`: "CPO订单兑现时，中际旭创短线技术突破信号可信度高；关键验证点为季度发货量数据与北美客户资本开支确认"
- `importance = 4`, `confidence = 0.68`
- `note`: "Demo示例：待审核晋升，不影响生产决策"

**This is the critical design choice**: the system surfaces learned candidates
but does not auto-trust them.  Only an explicit human confirmation step
upgrades `source_trust` from `pending` to a trusted level, at which point the
memory can be injected as context for future decisions.

---

## How to Reproduce

```bash
# 1. Seed (idempotent — safe to re-run)
DATABASE_URL=sqlite:///$(pwd)/examples/sample_db/mingcang_demo.db \
  PYTHONPATH=. python scripts/demo_seed.py

# 2. Print the closed loop
DATABASE_URL=sqlite:///$(pwd)/examples/sample_db/mingcang_demo.db \
  PYTHONPATH=. python scripts/reproduce_evidence.py

# Or via Makefile:
make reproduce-evidence
```

Expected output: the script prints each layer of the loop in order —
stocks, thesis + invalidation conditions, review attribution, and the pending
candidate status — then exits 0.

---

## Why This Design Matters

The closed loop is intentionally conservative:

- Theses have **explicit falsification conditions**, not just a vague
  "monitor".
- Reviews record **attribution**, not just outcome.
- Memory candidates are **pending by default** — the system cannot silently
  accumulate unjustified convictions.

This is documented in the architecture as the "成长"（grow with experience）
property of the L0–L4 loop: it grows only through reviewed, human-confirmed
evidence.
