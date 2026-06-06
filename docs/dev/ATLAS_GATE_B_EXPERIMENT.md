# ATLAS Gate-B Experiment (Pre-Registration v1)

> **Question:** does an ATLAS advisory overlay carry *forward-predictive value* —
> i.e. is it worth wiring into decisions? Gate A proved ATLAS is safe to merge
> without changing behaviour; Gate B is the only way to show a capability is
> *better*.
> **Status:** DESIGN + pre-registration. No experiment has been run. No
> production behaviour is changed by this document. Metrics and the decision
> rule below are frozen *before* any run (pre-registration) to avoid
> data-dredging.
> Grounding: every reused entry point was fact-checked to exist at the cited
> location; see "Tooling (verified)".

## 1. Capability under test
**M33 QualityGate** — the deterministic `gate_pass` boolean from
`backend/research/case.py::_build_quality_gate` (and, secondarily, the
`card_pass` of the StructuralValidityCard). Chosen first because it is **pure,
deterministic, zero-cost, reproducible** — unlike the M34 LLM stress test, which
is per-signal-LLM (expensive, non-deterministic) and is therefore **deferred to
a later, sampled experiment.**

## 2. Hypothesis (frozen)
- **H1:** signals with `gate_pass=True` have higher mean *after-cost* forward
  return than `gate_pass=False`, expressed as a positive trade-weighted
  `avg_net_return_delta` (gate-pass arm − baseline) across non-overlapping
  rolling forward windows.
- **H0 (null):** `gate_pass` carries no forward information — the trade-weighted
  delta is ≤ 0 (or below the pre-registered floor) and the stride ICIR ≤ 0.15.

## 3. Prerequisite fixes & gate variant
1. **DONE — point-in-time fix (commit `5ec3aa6`):** `signal_fresh` now honours
   `as_of` instead of the wall clock. Without it every historical signal looked
   stale and `gate_pass` would be uniformly False. Verified by
   `test_signal_fresh_uses_as_of_not_wall_clock`.
2. **Experiment gate variant — exclude `copilot_present`:** `ResearchState` has
   **no history table** (one mutable row per symbol), so the copilot card is
   unrecoverable as-of a past date and `copilot_present` would be permanently
   False in replay, forcing `gate_pass=False` everywhere. For this experiment,
   evaluate a `gate_pass'` that drops `copilot_present` from the blocker set.
   **This is an experiment-only variant; production M33 is NOT changed.**
3. **Dossiers MUST be built by raw as-of SQL, NOT `build_research_dossier()`** —
   that function calls `get_active_label()` (hardcodes `expires_at >= now`) and
   `latest_signal()` (no as_of filter); both leak the present. See §5.

## 4. Data & windows (frozen)
- **Source:** production `stock-sage.db` (signals, long_term_labels, prices,
  decision_runs), mounted **READ-ONLY** (`DATABASE_URL` override). *(Operational
  prerequisite — see §10; the atlas worktree DB has only sentiment_cache.)*
- **Eval window:** 2025-11-01 → 2026-04-30 (6 months); 2026-05+ left unseen.
- **Folds:** 6 non-overlapping monthly windows (`window_days=30, stride_days=30`;
  stride ≥ exit_days so folds are independent). NB: the rolling harness defaults
  are 7/7 — the runner must pass 30/30 explicitly.
- **Horizons:** primary `exit_days=5` (matches production exit); secondary
  `exit_days=10` for sensitivity (run only after primary is locked).
- **Universe:** survivorship-corrected per window via M38
  `get_snapshot_for_cutoff(cutoff=W_start)`; panel built `active_only=False`.

## 5. Point-in-time safety (each input)
For a signal evaluated at window start `W_start`, the overlay may use ONLY data
with date ≤ `W_start`:
- **latest_signal:** `SELECT * FROM signals WHERE symbol=? AND date<=W_start ORDER BY date DESC LIMIT 1` (bypass `latest_signal()`).
- **long_term_label:** `... WHERE date<=W_start AND expires_at>=W_start ORDER BY date DESC` (bypass `get_active_label()`).
- **decision_runs / evidence:** `... WHERE as_of<=W_start ORDER BY as_of DESC LIMIT 3`.
- **research_state / copilot:** unavailable historically → excluded (see §3.2).
- **signal_fresh:** fixed (§3.1); freshness vs `W_start`.
- **forward returns / quant:** `backfill_window(..., allow_lookahead_quant=False)`; forward prices strictly `date > W_start`. Both verified as-of-safe.

## 6. Metrics (PRE-REGISTERED, frozen)
| Role | Metric | Source |
|---|---|---|
| PRIMARY | trade-weighted `avg_net_return_delta` (after 0.4% round-trip cost) | `m27_top_decile_forward_shadow._trade_weighted_delta`, `backtest/costs.net_return` |
| PRIMARY | # windows with positive delta (of 6) | rolling report |
| SECONDARY | stride ICIR of `gate_pass` as a 0/1 rank score vs 5d fwd return | `m27_alpha_diagnostic.cross_sectional_ic`+`summarize_ic`, `stride_predictions(stride=exit_days)` |
| SECONDARY | win-rate delta; after-cost return spread | rolling report |
| BIAS | `coverage_loss` (baseline trades with no dossier) | runner |
| BIAS | `gate_pass_rate` per window | runner |

## 7. Decision rule (PRE-REGISTERED, frozen)
- **PROMOTE** (→ wire behind a flag): trade-weighted delta **> +0.003 (30 bps)**
  AND positive-delta windows **≥ 4/6** AND stride ICIR **> 0.15** AND
  coverage_loss **≤ 0.30** AND gate_pass_rate **∈ [0.05, 0.80]** AND total
  filtered trades **≥ 30**.
- **REJECT:** delta ≤ 0 OR positive windows < 3/6 OR stride ICIR ≤ 0 OR filtered
  trades < 30.
- **INCONCLUSIVE:** anything else → extend window / widen universe, re-run.
- **ABORT (bias threat):** coverage_loss > 0.30 OR gate_pass_rate < 0.02 (PIT fix
  not effective) OR any window with < 5 baseline trades.
- The 30 bp PROMOTE bar sits *below* the 40 bp round-trip cost deliberately: the
  gate must yield net-positive alpha to be worth wiring. **No post-hoc metric
  selection:** if ICIR is positive but trade-weighted delta is not, the result
  is REJECT.
- The row-level `gate_b_tracker report` is conservative: if stride ICIR,
  positive-window stability, or coverage_loss is unavailable, it must not emit
  PROMOTE. Stage 2 must supply those pre-registered gates before promotion is
  possible.

## 8. Bias controls
- **Single hypothesis:** `gate_pass` is the one pre-registered composite feature;
  sub-checks (signal_present, label_trusted, …) are **not** tested separately
  post-hoc (no multiple-comparison fishing).
- **Sign-stability hard gate:** delta sign must be positive in ≥ 4/6 folds — one
  lucky window cannot carry the aggregate.
- **Over-strictness guard (Piotroski lesson):** if `gate_pass_rate < 5%`, the
  gate is too harsh (cf. Piotroski over-penalising expansion-phase growth) →
  INCONCLUSIVE, not PROMOTE.
- **Coverage floor:** abort if > 30% of baseline trades lack a dossier; do **not**
  impute missing dossiers as `gate_pass=False` (that would cherry-pick).
- **Regime split:** report separately any window with > 15% market drawdown.
- **Overlap-inflation guard:** `stride_predictions(stride=exit_days)` before any
  IC; raw overlapping ICIR is reported only as "inflated — informational".
- **Thin sample:** ~25-symbol × 6mo ⇒ filtered trades likely < `MIN_TRADES_FOR_SHARPE=50`,
  so **Sharpe is unreliable** — the decision rule relies on trade-weighted delta
  + sign-stability, not Sharpe.

## 9. Staged plan
- **Stage 0 — PIT fix (DONE):** commit `5ec3aa6` + regression test.
- **Stage 1 — information-content (no wiring, no backfill):** materialise as-of
  dossiers, compute `gate_pass'`, measure coverage_loss & gate_pass_rate (abort
  checks), then stride ICIR of `gate_pass'` vs 5d forward returns on the panel.
  **ICIR ≤ 0 here ⇒ REJECT without running Stage 2.**
- **Stage 2 — A/B replay (only if Stage 1 ICIR > 0):** build
  `backend/tools/gate_b_atlas_overlay_ab.py` (TO BE BUILT) wrapping
  `build_profile_ab(allowed_filter_keys=atlas_filter_keys)` +
  `build_rolling_report` over the 6 windows; apply §7 thresholds.
- **Stage 3 — flag-gated wiring (only if Stage 2 PROMOTE):** register
  `atlas_quality_gate_overlay_v1` in `m29_hypothesis_registry`; run
  `m29_shadow_validation` for an evidence record; wire `gate_pass` as a **soft**
  `composite_score` penalty (not a hard block) behind `settings.atlas_gate_enabled`,
  default off. Soft penalty avoids the over-strictness failure mode.

## 10. Operational prerequisites & open decisions (need user input)
1. **Read-only access to production `stock-sage.db`** (it lives in the protected
   main checkout; the atlas DB lacks signals/labels). The experiment only READS
   it. Confirm this is acceptable, or provide a copy/snapshot.
2. **`copilot_present` exclusion** for the experiment gate variant — confirm.
3. **`_SIGNAL_STALE_DAYS` for the experiment:** at 30-day window boundaries the
   most-recent signal can be ~30d old and fail the 7-day freshness check. Either
   accept (structurally correct) or use a larger threshold *as an experiment-only
   constant* (not a production change).
4. **M38 snapshots must be pre-populated** for each window cutoff; there is no
   safe fallback to today's `Stock.active`.

## 11. Stage-3-only gaps (deferrable; do NOT block Stages 0-2)
- `gate_b_atlas_overlay_ab.py` does not exist (build in Stage 2).
- `atlas_quality_gate_overlay_v1` not in `m29_hypothesis_registry` / `m29_shadow_validation.SUPPORTED_HYPOTHESES`.
- `m29_shadow_validation` hard-checks `exit_days == 1`; exit_days=5 needs a new hypothesis handler.

## 12. Tooling (verified to exist)
`build_profile_ab` / `delta_filtered_minus_baseline` (m27_test3_production_profile_ab),
`build_rolling_report` / `rolling_windows` / `_trade_weighted_delta`
(m27_top_decile_forward_shadow), `cross_sectional_ic` / `summarize_ic`
(m27_alpha_diagnostic), `stride_predictions` / `load_or_build_panel`
(m27_label_objective_eval), `build_readiness` (m29_forward_readiness),
`net_return` / `annualized_sharpe` (backtest/costs, round-trip 0.4%),
`get_snapshot_for_cutoff` (research/universe_guard). Production tables Signal /
LongTermLabel / DecisionRun / Price / ResearchState confirmed with the columns
relied on above.

---
**Bottom line:** this experiment answers "is M33's gate informative enough to
wire in?" *before* any wiring. A PROMOTE is required before ATLAS changes a
single decision; a REJECT keeps ATLAS as advisory-only. Either outcome is a
real, pre-registered answer — which is the standard by which ATLAS can earn (or
be denied) the right to replace any of main's behaviour.
