# Evidence

This page explains how to reproduce MingCang's key evidence claims offline,
and links to the methodology documentation.

---

## Quick Start: Reproduce the Demo Closed Loop

Run the following command from the repository root.  No API keys or network
access are required.

```bash
make reproduce-evidence
```

What it does:

1. Points `DATABASE_URL` at the sample database
   (`examples/sample_db/mingcang_demo.db`).
2. Runs `scripts/reproduce_evidence.py`, which reads and prints:
   - The three demo stocks (600519 贵州茅台, 300308 中际旭创, 601318 中国平安)
   - The `ForwardThesis` for 300308 — including its three falsification
     conditions and follow-up metrics
   - The `ReviewCase` outcome and attribution
   - The `MemoryPromotionCandidate` status (pending — not yet trusted)
   - The recorded rationale for `WEIGHT_QUANT = 0.0`

If the demo database does not exist, seed it first:

```bash
DATABASE_URL=sqlite:///$(pwd)/examples/sample_db/mingcang_demo.db \
    PYTHONPATH=. python scripts/demo_seed.py
```

Then re-run `make reproduce-evidence`.

---

## What the Evidence Covers

### 1. Quant Layer Off (WEIGHT_QUANT = 0.0)

The quantitative scoring layer is disconnected from the production signal.
The decision is based on three hard-gate checks that all failed:

| Metric | Measured | Gate | Result |
|---|---|---|---|
| IC (Information Coefficient) | 0.0228 | >= 0.04 | FAIL |
| ICIR | 0.062 | >= 0.40 | FAIL |
| Decile monotonicity | non-monotonic | required | FAIL |

In addition, a regime sign-flip was detected: the quant factor's direction
reversed between bull-market and range-bound windows, making a small non-zero
weight worse than zero in expectation.

Full methodology: [docs/evidence/m29_quant_off.md](../docs/evidence/m29_quant_off.md)

### 2. Demo Closed Loop

The sample database demonstrates the full L0–L4 research loop:

- **L2 (Thesis)**: a `ForwardThesis` with explicit falsification conditions,
  not a vague "watch this stock"
- **L4 (Review)**: a `ReviewCase` recording outcome and attribution
- **L0 (Memory gate)**: a `MemoryPromotionCandidate` in `pending` state —
  the system surfaces candidates but never auto-trusts them

Full walkthrough: [docs/evidence/reproducible_closed_loop.md](../docs/evidence/reproducible_closed_loop.md)

### 3. Forward Validation Methodology

A short methodology note covering:

- Point-in-Time (PIT) feature discipline
- Pre-registration before shadow runs
- The three-phase validation cycle (pre-register → shadow run → promotion gate)

Full methodology: [docs/evidence/sample_forward_validation.md](../docs/evidence/sample_forward_validation.md)

---

## What `make reproduce-evidence` Does NOT Claim

- It does not re-run a live backtest.  The demo database contains static seed
  data, not a live market feed.
- It does not prove statistical significance.  Three stocks and one review
  case are illustrative.
- The `MemoryPromotionCandidate` being present does not mean the lesson is
  trusted or affects any decision.  `source_trust = "pending"` means no
  production effect.

---

## Production Signal Profile

For reference, the current production signal weights are:

| Component | Weight |
|---|---|
| Technical | 0.6 |
| Sentiment | 0.4 |
| Quant | 0.0 (disconnected) |
| ATR trailing stop | 2.5× |

These are set in `backend/config.py` and can be overridden via `.env`.
