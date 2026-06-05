# Atlas test4 — Staged Investment-Effect Pre-Registration

> Durable, pre-registered plan for measuring whether Atlas behavior improves
> investment outcomes, WITHOUT contaminating test2. Thresholds are locked here
> before any Stage is run. This is the **investment-effect gate**, which is
> separate from the already-passed engineering merge gate. test4 alone never
> changes official signals, positions, stops, or execution.

## Boundaries (apply to every stage)

- Runs in the Atlas worktree only; Atlas stays dormant (`ATLAS_ENABLED=false`).
- No merge, no push, no rebase. Production DB is **read-only**; all writes go
  under `/private/tmp`. test2 stays frozen. M29 untouched.
- Promotion to the official path requires a passing Stage 2 **and** explicit
  user confirmation. Stage results are evidence, not authorization.

## Data reality (recorded 2026-06-05)

| Source | Range | Count | Note |
|---|---|---|---|
| `signals` | 2026-05-12 → 2026-06-04 | 879 | ~3.5 weeks, single regime |
| `prices` | 2017-01-23 → 2026-06-04 | 856,241 | deep history for forward returns AND signal backfill |

Implication: forward returns are abundant, but the **signal set the overlay
evaluates is tiny and single-regime**. Pure historical evaluation on the current
signals is low-power and is expected to land INCONCLUSIVE. A high-power historical
answer requires **signal backfill** over multi-year price history; a
promotion-grade answer requires forward OOS data accumulated over calendar time.

## What "Atlas overlay" means here

- **Signal / entry-quality overlay (M33 QualityGate, build_case gate)** — already
  has a PIT-correct historical+prospective harness: `backend.tools.gate_b_tracker`
  (`record` → `realize` → `report`). The gate is **rule-based, not fitted**, so
  historical evaluation is not parameter-overfit; its limits are sample size and
  regime coverage, not curve-fitting.
- **Exit overlay / entry+exit overlay** — Atlas thesis-invalidation-driven
  exits on top of base ATR rules. This is the genuinely new test4 surface and is
  not yet wired as a runnable backtest (see Stage 1B feasibility / Stage 2b).

## Stage map

| Stage | Question | Cost | Output |
|---|---|---|---|
| **Stage 1** (now) | Does the atlas signal overlay even discriminate — help or hurt — on available data? | cheap (minutes) | GREEN / RED / AMBER go-no-go. Diagnostic, NOT promotion. |
| **Stage 1B** (now, scoping) | How cheap is a high-power historical run via signal backfill? | cheap (inspect + tiny dry-run) | feasibility + runtime estimate for Stage 2a |
| **Stage 2a** (later) | High-power historical: backfilled multi-regime signals → Gate-B | medium (compute) | promotion-grade historical evidence |
| **Stage 2b** (later) | Forward shadow with test2-style arms | expensive (calendar time) | promotion-grade forward evidence |
| **Promotion** (later) | Influence official path | — | only if Stage 2 passes AND user confirms |

---

## Stage 1 — LOCKED design (historical diagnostic)

Engine: `backend.tools.gate_b_tracker`, with `--source-database-url` =
production (`sqlite:////Users/zeeechenn/stock-sage/stock-sage.db`, read-only) and
`--database-url` = a throwaway observations DB under `/private/tmp`.

Procedure, for each horizon `H ∈ {5, 10, 20}` trading days (separate obs DBs):

```
record  --as-of 2026-06-04 --horizon-days H
realize --as-of 2026-06-04
report  --format json
```

Metrics captured per horizon: `n_pass`, `n_fail`, `gate_pass_rate`,
`dq_exclusion_rate`, winsorized mean net return (pass / fail / delta), median net
return (pass / fail), hit rate (pass / fail), cross-sectional IC of `gate_score`
vs `forward_return_net`.

### Pre-registered Stage 1 decision matrix (locked)

Evaluate per horizon, then combine. `delta = winsorized_mean_net(pass) − winsorized_mean_net(fail)`.

1. **ABORT (data/bias — not a verdict):** `dq_exclusion_rate > 0.30`, OR
   `gate_pass_rate < 0.02`, OR `gate_pass_rate > 0.80`. → fix data first
   (inherits the Gate-B report rule).
2. **RED / STOP:** `delta < 0` **and** `IC ≤ −0.03`, directionally consistent on
   ≥2 of 3 horizons, with `n_pass ≥ 20` **and** `n_fail ≥ 20`. → the signal
   overlay is harmful; do **not** invest in the exit overlay on this premise.
3. **GREEN / PROCEED:** `delta > 0` **and** `IC ≥ +0.03`, consistent on ≥2 of 3
   horizons, with `n_pass ≥ 20` **and** `n_fail ≥ 20`, DQ clean. → build the exit
   overlay and proceed to Stage 2.
4. **AMBER / INCONCLUSIVE:** sample below thresholds (`n_pass < 20` or
   `n_fail < 20`) OR horizons disagree. → history cannot answer yet; choose the
   Stage 2 path (2a backfill vs 2b forward) by whether the direction is at least
   non-negative.

The Stage 1 IC screen (±0.03) is deliberately **looser** than the official
promotion gate (IC ≥ 0.04, ICIR ≥ 0.40, monotonic buckets) because Stage 1 is a
go/no-go diagnostic, not a promotion test.

Given the data reality above, **AMBER/INCONCLUSIVE is the most likely Stage 1
outcome**, and that is itself a useful result: it proves the effect cannot be
established from current history and forces the Stage 2 path decision.

## Stage 1B — backfill feasibility (scoping, runs with Stage 1)

Assess `backend/backtest/backfill_signals.py`: does signal generation require
only technical/price inputs (cheap, offline) or news/sentiment/LLM per day
(expensive, paid)? Do a tiny `/private/tmp` dry-run (1–2 symbols, ~1 month),
measure wall-time, and extrapolate to a 3–5 year × full-universe backfill.
Output: cheap / expensive / blocked, what it needs, runtime estimate, and a
recommendation between Stage 2a (backfill) and Stage 2b (forward).

---

## Stage 2 — LOCKED design (run later, not now)

### Stage 2a — high-power historical (if backfill is cheap)

Backfill signals over ≥3 years of multi-regime history → Gate-B. Promotion-grade
bar: `IC ≥ 0.04` and `ICIR ≥ 0.40` across non-overlapping time folds, monotonic
`gate_score` buckets, winsorized `delta > 0` with a bootstrap CI excluding 0.

### Stage 2b — forward shadow (test2-style arms)

Arms: `test2_baseline`, `atlas_signal_overlay`, `atlas_exit_overlay`,
`atlas_entry_exit_overlay`. test2 stays frozen (original rules, state, A/B
objective, runner inputs, signal loading, position sizing, exit/entry rules,
state JSON semantics); Atlas runs only as a shadow overlay. Metrics: return, max
drawdown, missed-upside rate, false-trend-kill rate, re-entry quality, proposal
hit rate, opportunity cost, extra drawdown, tail risk. Pre-register the proposal
hit-rate horizon, label source, adjudication rule, sample window (≥ defined
forward weeks / matured trades), and small-sample handling before evaluation.
Same-window replay is diagnostic only, never promotion proof.

### Promotion

Only after Stage 2a and/or 2b pass **and** the user confirms. test4 never changes
official signals by itself.

## Stage 1 results (2026-06-05)

Verdict per the locked matrix: **AMBER / INCONCLUSIVE** — but for a structural
reason, not just small sample. No valid two-arm comparison could be formed.

Run: `record→realize→report` at H∈{5,10,20}, 829 observations each, production
read-only, obs DBs in `/private/tmp/test4_stage1/`. DQ clean
(`dq_exclusion_rate=0`, `n_data_error=0`). Production DB mtime unchanged.

| Horizon | recorded | realized | gate_pass (realized) | report verdict |
|---|---|---|---|---|
| 5d | 829 | 423 | **0** | ABORT / gate_pass_rate_too_low |
| 10d | 829 | 130 | **0** | ABORT / gate_pass_rate_too_low |
| 20d | 829 | 0 | — | INCONCLUSIVE / insufficient_sample |

**Root cause (verified against obs DB):** the gate's pass set and its
matured-return set are temporally disjoint. The 39 gate-pass signals all date
2026-05-27→06-03 and are still *pending* (too recent for forward returns); the
423 realized signals all date 2026-05-12→05-26 and are 100% gate-fail. So the
realized pool has no pass arm → `gate_pass_rate=0` → ABORT.

**Why disjoint:** the gate passes largely on research-artifact *presence*
(`deep_research_present` in ~786/790 fail rows, plus `label_trusted`/
`label_present`), which accumulates over time and is therefore confounded with
recency. This is an operational-coverage gate, not a pure signal-quality gate.

**Consequences:**
- The atlas overlay's investment edge is currently **unmeasurable from history** —
  not harmful, not helpful, just unmeasurable on this window.
- A naive Stage 2a backfill would hit the same wall: a historical signal backfill
  has **no `deep_research`/trusted-label artifacts**, so nothing would pass the
  gate as currently defined.
- Decision needed before more compute: either (A) define a backfillable
  *quality-only* gate variant (no artifact-presence blockers) and test that
  historically, or (B) treat this artifact-presence gate as a forward-only object
  and start Stage 2b accrual, or (C) re-examine whether `deep_research_present`
  belongs in an investment-effect gate at all.

## Stage 1B results (2026-06-05)

Backfill feasibility: **CHEAP**. `backfill_signals.py` default path
(`use_llm_news=False`) is technical/price-only — no LLM, no network, qlib
lookahead-guarded off. Dry-run: 2 symbols × 20 trading days = 40 inputs in 2.1s
(0.0525s/point). Estimate (weekly sampling, `every_n_days=5`): 3yr×700 syms ≈
1.5h, 5yr×900 syms ≈ 3.2h. Caveat from Stage 1: backfill is cheap to *run* but
only useful once a backfillable gate variant is defined (see Stage 1 consequences).

## Route A analysis (2026-06-05) — backfillable quality-only gate

Read-only analysis of `backend/research/case.py` `_build_quality_gate` (9 checks)
and `gate_b_recorder.py`. Two design flaws found, plus a clean fix.

**Classification of the 9 gate checks:**

| Check | Type | Backfill-reproducible? |
|---|---|---|
| `signal_present` | precondition | yes (trivial) |
| `signal_fresh` | quality/validity (PIT, uses as_of) | yes |
| `cutoff_ok` | structural PIT guard | yes |
| `deep_research_present` | **operational artifact** (LLM research record) | **no** |
| `copilot_present` | **operational artifact** | **no** |
| `label_present` | **operational artifact** (labeling pipeline) | no (unless labels backfilled) |
| `label_trusted` | **operational artifact** | no |
| `no_pending_questions` | artifact-derived (copilot) | vacuously yes |
| `source_coverage_ok` | provenance completeness | partial |

**Flaw 1 — the gate discriminates only on artifact presence.** The binary
pass/fail is driven by `deep_research_present` / `label_trusted`, which accumulate
over time → confounded with recency, absent in any historical backfill. Stripping
them leaves no quantitative quality factor → gate would pass ~everything
(`gate_pass_rate > 0.80` → ABORT). So QualityGate v0 is a *research-completeness*
gate, not a *signal-quality* gate.

**Flaw 2 — IC is computed on the binary flag, not the score.** `report()` sets
`gate_score = 1.0 if gate_pass_variant else 0.0` (recorder line 682). In the
realized pool every row is gate-fail → the flag is constant → IC is null by
construction. Meanwhile the continuous **`composite_score` is recorded on every
observation and goes unused** for IC.

**Proposed backfillable quality-only discriminator:** use the continuous
`composite_score` (reproducible from a technical-only backfill, already recorded)
as the discriminator — cross-sectional IC + bucket monotonicity vs
`forward_return_net`. Keep `signal_fresh` / `cutoff_ok` as PIT/validity filters.
Drop artifact-presence checks from the discriminator. This requires a small report
change (IC on `composite_score`, not the binary flag); no change to `case.py`.

**Preliminary read on existing Stage-1 realized data** (pooled Spearman, single
~3.5-week regime — low power, NOT promotion evidence):

| Horizon | n | IC(composite, fwd_net) | rough z | top-quintile mean fwd_net |
|---|---|---|---|---|
| 5d | 423 | **+0.151** | +3.1 | +4.7% (vs bottom quintiles negative) |
| 10d | 130 | **+0.145** | +1.7 | +11.9% |

Direction is positive and the top quintile clearly leads, IC well above the 0.04
promotion bar — but this is one short regime, pooled (not date-neutral), and
measures the **base signal score's** edge, not an isolated Atlas increment.
Treat as "the test design is right and worth powering up," not as a verdict.

**Updated Stage 2a target:** technical-only signal backfill over ≥3yr
multi-regime → cross-sectional IC + ICIR of `composite_score` across
non-overlapping folds + bucket monotonicity. Promotion bar unchanged
(IC ≥ 0.04, ICIR ≥ 0.40, monotonic buckets, CI excluding 0).

## Stage 2a results (2026-06-05) — FAIL (no positive cross-regime edge)

Powered historical pilot: 90 symbols, 9,638 points, 2021-01-01→2025-12-31,
biweekly, 52.7s. Score tested = `technical_result.score` (backfittable component;
sentiment/quant = 0 historically). Independent re-verification (scipy) reproduced
every number to 4 decimals → computation trusted.

| Metric | H=5 | H=20 | Bar | Pass? |
|---|---|---|---|---|
| pooled Spearman IC | −0.030 | −0.017 | — | — |
| mean per-date IC | −0.016 | −0.012 | ≥ 0.04 | **FAIL** |
| ICIR | −0.10 | −0.07 | ≥ 0.40 | **FAIL** |
| decile monotonicity | inverted | flat | monotone | **FAIL** |
| bootstrap 95% CI (mean IC) | [−0.047, +0.018] | [−0.051, +0.022] | low > 0 | **FAIL** |
| significance | t≈−1.0, p≈0.30 | t≈−0.7, p≈0.47 | — | ≈ noise |

Per-year fold IC (H5 / H20): 2021 +0.013/−0.018, 2022 +0.020/−0.017,
2023 −0.058/+0.003, 2024 −0.071/−0.030, 2025 −0.043/−0.034 → **sign reversal
across regimes** (weakly positive 2021-22, negative 2023-25). Not regime-robust.

This **refutes the Stage-1 preliminary +0.15** as single-window (late-May 2026)
regime luck, exactly as flagged. The backfittable technical component has no
measurable positive forward edge and is slightly negative / mean-reverting.

Caveats: (1) tests the technical component only — not the full live composite
(sentiment 40%) and **not** an isolated Atlas increment (the overlay gate is not
backfittable). (2) Survivorship: universe = symbols with full 2021-25 coverage.
(3) Per-symbol biweekly sampling staggers dates (median 2 names/date; 107 dense
cross-sections) → the **pooled IC and per-year folds are the robust read; ICIR is
noisier**. Conclusion (no positive edge) holds across all three. (4) Backfill-scoring
sanity check (2026-06-05): **RESOLVED** — `technical_score` is pure price-based
(no sentiment/quant dependence) and the backfill reproduces the production-stored
`technical_score` at Pearson 0.978 (39/43 within ±5; score std 29.75, well-spread).
The negative result is real, not a backfill artifact.

## Status

| Item | State |
|---|---|
| Pre-registration | locked |
| Stage 1 | complete — AMBER/INCONCLUSIVE (artifact-gate / binary-IC confound) |
| Stage 1B | complete — backfill cheap (~1.5–3h) |
| Route A | analysis complete — discriminator = continuous technical/composite score |
| Stage 2a | complete — **FAIL**: no positive cross-regime edge, regime sign-reversal, ≈ noise |
| Stage 2b | not started — only remaining path to measure the Atlas overlay increment (forward shadow, slow) |
| Promotion | not authorized — no historical evidence of edge in backfittable components |
