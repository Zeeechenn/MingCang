# M43 — Backtestable Capability Experiment (Pre-Registration v1)

> The retrospective complement to the prospective Gate-B tracker. Gate-B tests
> the live-state M33 gate (no historical counterfactual). M43 tests a capability
> that **is** reconstructable from the deep price history (2018+), so it can be
> backtested with real statistical power.
> **Status:** DESIGN FREEZE. No fold has been run. Metrics + decision rule below
> are frozen *before* any run. **Depends on M42 (clean prices).**

## 1. Overlay under test
**M27 top-decile LightGBM classifier probability** — hypothesis id
`top_decile_entry_timing_retrospective_v1`. Per (symbol, date) the classifier
(features = `PRODUCTION_FEATURE_COLS + M27_ALPHA_FEATURE_COLS`, OHLCV/technical-
derived) predicts P(forward return in top decile); overlay score = `predict_proba[:,1]`.
Chosen over the other candidates (sector-relative-strength, Amihud filter,
12-1 reversal) because its PIT walk-forward train/predict harness already exists
(`m27_top_decile_forward_shadow._target_predictions`), it is zero-LLM/zero-news,
and it yields BOTH an IC channel and an A/B return channel in one pass. Those
other candidates are features *inside* this classifier — testing them separately
in the same run would be multiple-comparison fishing (deferred to a separately
pre-registered M43.2 with Bonferroni α/4).

## 2. Hypotheses (frozen)
- **H1:** at `top_pct=0.20`, top-decile-scored signals have a higher trade-weighted
  after-cost 5-day forward return than the full-universe baseline — a positive
  `trade_weighted_avg_net_return_delta`, sign-stable across folds, exceeding the
  30 bp floor; secondary: stride ICIR of the continuous score vs `label_5d` > 0.15.
- **H0:** delta ≤ 0, OR positive in < 3 of 4 folds, OR stride ICIR ≤ 0.

## 3. Data & folds (frozen)
- Source: clean prices (post-M42). Full history 2018-10-18 → 2026-06-02 / 713 symbols.
- **OOS eval window: 2021-01-01 → 2024-12-31.** Pre-2021 (13–18 symbols) is
  training-only, never OOS.
- **2025 is SEALED** until this freeze is committed — reading it to calibrate
  invalidates pre-registration (separate Stage-5.1 confirmation artifact).
- **4 non-overlapping annual folds** (eval 2021/2022/2023/2024); each trains on
  rows with `date < fold_start AND label_realized_date < fold_start`;
  `stride = window = 365d` (override the harness default 7d).
- Horizon: train label `horizon=20`, `exit_days=5` (primary). Panel:
  `load_or_build_panel(active_only=False, min_rows=120)` (M38 include_inactive).
- Classifier hyperparams FROZEN: n_estimators=120, lr=0.05, num_leaves=31,
  min_child_samples=20, subsample=0.8, colsample_bytree=0.8, seed=42.

## 4. Point-in-time + survivorship
- PIT: dual cutoff in `_target_predictions` (date & label_realized_date < fold_start,
  ~20-trading-day buffer); `backfill_window(allow_lookahead_quant=False)`; forward
  prices strictly `date > entry`.
- Survivorship (M38): **populate `universe_snapshots` via `snapshot_universe()`
  for cutoffs 2021/2022/2023/2024-01-01** and use `get_snapshot_for_cutoff()`.
  Fallback `include_inactive=True` is a documented DEGRADED path → blocks PROMOTE.

## 5. Metrics (PRE-REGISTERED)
- PRIMARY: `trade_weighted_avg_net_return_delta` (after 0.4% round-trip cost);
  `positive_delta_fold_count` (of 4).
- SECONDARY: stride ICIR (score vs label_5d, `stride_predictions(stride=5)` first);
  per-fold filtered-arm Sharpe (trades ≥ 50); win-rate delta.
- BIAS sentinels: `top_decile_pass_rate` per fold; `train_rows` per fold;
  **M42 contamination sentinel** = mean |gross_return| per fold (expect 0.01–0.10).

## 6. Decision rule (PRE-REGISTERED, frozen)
- **PROMOTE:** delta > **+0.003 (30 bps)** AND positive folds **≥ 3/4** AND stride
  ICIR **> 0.15** AND top_decile_pass_rate ∈ [0.15, 0.25] all folds AND total
  filtered trades **≥ 200** AND contamination sentinel ∈ [0.001, 0.30] all folds.
- **REJECT:** delta ≤ 0 OR positive folds < 2/4 OR stride ICIR ≤ 0.
- **ABORT (bias/contamination):** delta > +0.20 AND ICIR > 1.0 (lookahead);
  OR contamination sentinel out of [0.001, 0.30]; OR Folds 2-4 train_rows < 50k;
  OR M38 snapshots absent (degraded fallback) → block PROMOTE; OR pass_rate
  outside [0.05, 0.40] any fold.
- **INCONCLUSIVE:** anything else (e.g. delta>0 but ICIR≤0.15) → widen / regime-split.
- No post-hoc metric selection: ICIR>0 but delta≤0 ⇒ REJECT, not INCONCLUSIVE.
- Pre-registered Fold-1 contingency: if Fold-1 `train_rows < 200`
  (`status=insufficient_data`), it contributes zero weight and PROMOTE adjusts to
  **≥ 2 of 3** remaining folds (no other threshold changes).

## 7. Bias controls
Single overlay (top_pct=0.20 only); sign-stability hard gate (≥3/4);
overlap-inflation guard (stride before ICIR); over-strictness floor (pass_rate
≥ 0.15, per the Piotroski lesson); 2025 sealed; per-fold regime (CSI-300 drawdown)
annotation; hyperparameters frozen; artifacts carry
`non_promoting/production_unchanged/writes_db=False`.

## 8. Dependency on M42 + residual guard
Clean prices are a hard prerequisite: contaminated closes would (a) poison the
top-decile boundary the classifier trains on, and (b) corrupt the after-cost
delta. Run-time guard: record `provenance_completeness_report().price_adjustment_pct`
in the artifact header; if < 0.95 emit `insufficient_m42_adjustment_coverage` and
do not PROMOTE. The contamination sentinel (§5) is the second layer.

## 9. Staged plan
- **Stage 0 — freeze (this doc):** commit + register
  `top_decile_entry_timing_retrospective_v1` in `m29_hypothesis_registry`. No fold runs before this.
- **Stage 1 — pre-flight (read-only):** `m29_forward_readiness` + provenance ≥ 0.95;
  populate M38 snapshots for the 4 cutoffs.
- **Stage 2 — IC gate (Fold-2/2022 only):** stride ICIR; **ICIR ≤ 0 ⇒ REJECT** without running the rest.
- **Stage 3 — full 4-fold A/B** (only if Stage 2 ICIR > 0): `build_report` per fold
  (stride=window=365) → `build_rolling_report` → apply §6.
- **Stage 4 — residual attribution** (only if PROMOTE): `m29_quant_residual_attribution`
  to confirm incremental value over single factors / QUANT_OFF baseline.
- **Stage 5 — M29 evidence ledger** (only if PROMOTE): `m29_shadow_validation`
  (`non_promoting=True`); schedule the sealed-2025 fresh-forward confirmation.
  Production wiring only after human confirmation + 2025 confirmation + M29 gate.

## 10. Open risks
M38 `universe_snapshots` absent in the copy (populate first, else degraded);
Fold-1 sparse training (contingency in §6); `m29_shadow_validation` hard-checks
`exit_days==1` (Stage-5-only gap, needs a new hypothesis handler); fundamental
feature filing-date vs report_date lookahead (pure-price sensitivity re-run
available); 2025 must stay sealed (pass `end='2024-12-31'` everywhere).

---
**Bottom line:** unlike Gate-B (prospective, slow, live-state), M43 can deliver a
powered PROMOTE/REJECT on real history — but only on clean prices (M42) and only
under this frozen protocol. A PROMOTE here is the first ATLAS capability with a
statistically-grounded claim to influence decisions; even then it enters behind a
flag via the M29 evidence gate, never as a wholesale replacement.
