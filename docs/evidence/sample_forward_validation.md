# Methodology: Forward / Post-Event Shadow Validation

This note describes how MingCang uses forward and post-event shadow validation
to evaluate signal quality without lookahead contamination.

---

## What Is Shadow Validation?

Shadow validation means running a signal-generation or model-scoring pipeline
on data that was available at a specific point in time (the "as-of" date), then
comparing the output against what subsequently happened — but **never feeding
the outcome back into the model that generated the prediction**.

The term "shadow" emphasises that the validation lane runs in parallel with,
not inside, the production signal path.  A shadow run can read the production
database but writes only to an isolated evidence artifact or a Gate-B
observation table.

---

## Point-in-Time Discipline

The key safeguard is Point-in-Time (PIT) feature construction:

- Price and volume data are accessed only up to the as-of date.
- Financial fundamentals are pinned to the disclosure date, not the period-end
  date (e.g., a Q1 report disclosed on 30 April is only available from
  30 April onward).
- News and sentiment features are timestamped to the article fetch time, not
  the event date.

`backend/data/point_in_time.py` implements the PIT guards.  The M46.5 one-time
lookahead audit (`backend/tools/m46_5_lookahead_one_time_audit`) verified the
production feature pipeline against this requirement.

---

## Forward Validation Steps

A forward validation cycle proceeds in three phases:

### Phase 1: Pre-registration

Before running any new validation experiment, hypotheses must be pre-registered
in the M29 hypothesis registry (`backend/tools/m29_hypothesis_registry`).  This
prevents post-hoc selection of the best-looking result.

Pre-registration records:
- The hypothesis (e.g., "technical IC > 0.04 for the top-decile filter")
- The metric threshold that would constitute confirmation
- The validation window (start date, end date)
- The data snapshot hash

### Phase 2: Shadow run

The shadow validation (`backend/tools/m29_shadow_validation`) reads the
pre-registered hypotheses and validates them against the evidence artifacts
already on disk.  It does **not** call any paid API, retrain any model, or
write to the production signal tables.

For the sample database, a simplified version of this process is visible in
`scripts/reproduce_evidence.py`: the script reads the `ForwardThesis` record
(which contains the pre-registered invalidation conditions and follow-up
metrics) and shows the associated `ReviewCase` outcome — a manual analog of
the automated shadow validation flow.

### Phase 3: Promotion gate

A shadow validation result can only be promoted to production if:

1. The pre-registered metric thresholds were met.
2. No regime sign-flip was observed across sub-windows.
3. An operator explicitly confirms promotion (no auto-promote path).

---

## Sample Data Illustration

The demo database illustrates the structure without a live data feed:

| Object | Role in Forward Validation |
|---|---|
| `ForwardThesis` | Pre-registered thesis with falsification conditions |
| `Signal` (date=2026-06-03) | Point-in-time signal output (static demo seed) |
| `ReviewCase` (as_of=2026-06-01) | Post-event outcome and attribution |
| `MemoryPromotionCandidate` (pending) | Candidate surfaced by review; not yet promoted |

The `ForwardThesis.invalidation_conditions_json` field plays the role of the
pre-registration record: it states in advance what would falsify the thesis,
so the review cannot cherry-pick favorable interpretations.

---

## What This Methodology Does Not Claim

- The sample database does not demonstrate statistical significance.  Three
  stocks and one review case are illustrative, not a backtest.
- The `MemoryPromotionCandidate` being present does not mean the lesson is
  trusted.  `source_trust = "pending"` means it has no effect on any decision.
- The demo does not simulate the quant layer.  The `quant_score = 0.0` in the
  seeded `Signal` row reflects the production reality (WEIGHT_QUANT = 0.0);
  see `docs/evidence/m29_quant_off.md` for the rationale.

---

## Further Reading

- `docs/evidence/m29_quant_off.md` — why the quant layer is currently
  disconnected.
- `docs/evidence/reproducible_closed_loop.md` — the demo closed loop
  walkthrough.
- `backend/tools/m29_shadow_validation` — production shadow validation tool.
- `backend/tools/m46_5_lookahead_one_time_audit` — lookahead audit evidence.
