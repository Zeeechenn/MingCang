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

---

## Amendment 1 — Stage-1 pre-flight finding (2026-06-03)

Made **before any fold was run** (no outcome data observed); the hypothesis,
metrics, and decision rule in §2/§5/§6 are **unchanged**. Only the §8 data-quality
precondition is corrected, because Stage-1 revealed it was based on a wrong
assumption about the data.

**Finding.** On the cleaned production DB, `Price.adjustment` is NULL for
99.94% of rows and **0.00% in the 2021-2024 window** — provenance was never
recorded historically. M42 *deletes* jump-contaminated rows (so they re-fetch as
qfq); it does **not** retroactively tag the `adjustment` column. Therefore the
original §8 gate `price_adjustment_pct >= 0.95` is **structurally unmeetable** and
is not a meaningful integrity signal here.

**Correction (supersedes the §8 `adjustment_pct` gate):**
1. **Jump-contamination gate (replaces adjustment_pct):** the eval window must
   have **zero** rows where `close > 3 × median(preceding 10 closes)` (the M42
   predicate). Verified satisfied on the cleaned live DB (0 flagged) after the
   M42 remediation deleted 84 rows on 2026-05-25/26.
2. **Whole-series-hfq exclusion:** a handful of symbols (e.g. 600601 ≈ ¥142,000)
   carry an entire price series on hfq basis — wrong absolute level but
   internally consistent (entry and exit share the basis, so *returns* are
   correct). These do not cause the artifact returns M42 fixed, but to be safe
   M43 **excludes symbols whose max close in the window exceeds ¥10,000** (a
   level impossible for a genuine qfq A-share; legitimately high names like
   贵州茅台 ≈ ¥1,900 are well below). Enumerate + log the excluded set in
   Stage-1; expected ≈ 8 symbols.
3. The §5 **M42 contamination sentinel** (mean |gross_return| ∈ [0.001, 0.30] per
   fold) remains as the run-time residual guard.

**Status:** Stage-1 jump-contamination gate PASSES (0 flagged). Whole-series-hfq
enumeration + M38 snapshot population are the remaining Stage-1 sub-steps before
the Stage-2 IC gate.

---

## Result — Stage 2 IC gate (2022 fold): **REJECT** (2026-06-03)

Ran on the cleaned work DB (`m43_work.db`), system Python 3.11 + lightgbm 4.6.0,
bounded to `date <= 2022-12-31` (2023+/2025 untouched). HFQ exclusions applied
(600601, 600602, **600519 贵州茅台** — its series is hfq-scaled in this DB).

| metric | value |
|---|---|
| train_rows (date & label_realized < 2022-01-01) | 50,253 |
| eval rows (2022) | 158,952 |
| stride ICIR (stride=5, score vs label_5d) | **−0.1116** |
| ic_mean | −0.0268 |
| ic_days / ic_positive_rate | 49 / 0.469 |

**Verdict: REJECT.** Per the frozen §6 rule, `ICIR ≤ 0` at the Stage-2 gate
stops the experiment — Stages 3–5 are NOT run. The M27 top-decile LightGBM
overlay (`top_decile_entry_timing_retrospective_v1`, frozen hyperparams) carries
**no positive forward-predictive information** on the 2022 OOS fold; the IC is in
fact slightly negative.

**Interpretation.** This is a clean pre-registered negative result, not a bug:
the overlay does not generalise out-of-sample, corroborating the project's
production stance of `weight_quant = 0.0`. It does NOT get wired into decisions.

**Follow-ups (each a SEPARATE, independently pre-registered experiment — not run):**
- M43.2: candidates 2–4 (sector-relative-strength, Amihud-liquidity filter,
  12-1 reversal), Bonferroni α/4, same harness.
- Data: 600519/600601/600602 carry hfq-scaled price series in production
  (absolute prices wrong, returns internally consistent) — a separate
  data-remediation item beyond M42's jump-contamination scope.

---

## M43.2 — single-factor candidates (Bonferroni α/4): **script-backed reproduction** (2026-06-03; harness expanded)

Pre-registered (rule frozen before computing): 3 single factors, OOS 2021-2024,
stride=5, active_only=False, hfq excluded, 2025 sealed. PROMOTE needs
|IC t-stat|>2.50 (α/4≈0.0125) AND |ic_mean|>0.02 AND |ICIR|>0.15 AND monotonic
quintile spread in the expected direction.

**Current reproducibility status.** The repository now contains a parameterized
M43.2 reproduction script, `m43_2_amihud_ic.py`, covering all three frozen
single-factor candidates:

```bash
python3 m43_2_amihud_ic.py --factor all --db-path ~/.stock-sage/m43_work.db
```

For single-factor checks, pass `--factor amihud_20`,
`--factor sector_rel_strength_20_z`, or `--factor rev_mom_12_1_z`. The script
keeps the sealed-2025 guard (`--end-date` must be `<= 2024-12-31`), refuses to
create a missing SQLite DB, and writes per-factor JSON containing IC summary,
t-stat, quintile/spread, and verdict when `--output-json` is provided.

The script keeps the IC and quintile-spread gates on cross-sectional footing:
IC is computed per date, and quintile spread is bucketed per date before
averaging bucket returns across dates. `rev_mom_12_1_z` matches the existing
M27 feature builder: it uses negative 12-1 momentum when 252-day lookback is
available and records a 60-day fallback share in JSON metadata for shorter
history rows.

The local work DB is not stored in the repository. The rows below are retained
as historical local `m43_work.db` run notes from 2026-06-03; rerun the command
above on the current work DB to refresh them. This section records script
support for all three factors, not a new real-DB rerun by this worker unless
such an artifact is explicitly added.

| factor | ICIR | ic_mean | IC t-stat | spread monotonic | verdict |
|---|---|---|---|---|---|
| sector_rel_strength_20_z | −0.015 | −0.0026 | −0.20 | no | **REJECT, script-supported** |
| amihud_20 (illiquidity) | −0.059 | −0.0105 | −0.82 | no (sign-mismatch) | **REJECT, script-backed** |
| rev_mom_12_1_z (reversal) | +0.097 | +0.017 | +1.35 | no (sign reversed) | **REJECT, script-supported** |

**Historical verdict: 0 of 3 promoted.** All three retained work-DB rows miss the
frozen promotion bars. The strongest retained row (`rev_mom_12_1_z`, t=1.35) is
still below the 2.50 Bonferroni threshold, and none has a monotonic quintile
spread in the expected direction.

**Interpretation.** Together with the M43 LightGBM REJECT, the script-backed
M43.2 harness provides no current reason to change the production
`weight_quant = 0.0` stance. No factor is wired into decisions. If the current
local work DB has drifted from the 2026-06-03 notes, rerun `--factor all` and
replace the table with the refreshed script output before making a stronger
claim.
