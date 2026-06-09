# M29 Evidence: Why WEIGHT_QUANT = 0.0

**Status:** Production-locked. Revisit only after a new quant cycle passes the
forward-readiness gate.

---

## Production Signal Profile (Current)

| Component | Weight | Source |
|---|---|---|
| Technical | 0.6 | `backend/config.py` `weight_technical` |
| Sentiment | 0.4 | `backend/config.py` `weight_sentiment` |
| Quant (Qlib/Kronos) | **0.0** | `backend/config.py` `weight_quant` |
| ATR trailing stop | 2.5× | `trailing_atr_mult` |

The comment in `backend/config.py` lines 106–109 captures the formal decision:

```
# 阶段A Qlib 有效性硬验证结论：IC=0.0228 / ICIR=0.062 / 分层非单调 → Qlib 不合格
# 默认改为「技术 60% + 情感 40%」，weight_quant 归零。
# Qlib 通过 RD-Agent 升级后可在 .env 中重新分配权重。
weight_quant: float = 0.0
```

---

## Evidence Chain

### Stage A: Qlib hard-validity check (M26–M27)

The M26 baseline run evaluated the LightGBM Qlib model against realized
A-share price labels.  Key measured statistics:

- **IC = 0.0228** — Information Coefficient against the 5-day forward return.
  An IC below ~0.04 is conventionally treated as noise on Chinese A-share
  intraday data.
- **ICIR = 0.062** — IC divided by its own standard deviation.  A value below
  0.40 means the IC itself is not stable enough to be tradable.
- **Decile monotonicity: FAIL** — The model's top-decile portfolio did not
  consistently outperform lower deciles.  The rank ordering necessary for a
  long/short overlay was absent.

These three checks are hard gates, not advisory: all three must pass before a
quant score is eligible for any production weight.

> **Caveat (recorded in `docs/dev/BUGS_FIXED.md`):** the bare `IC < 0.04`
> threshold should **not** be read as the decisive reason on its own. A later
> DSR recheck found that at N=12797 the IC=0.0228 was actually statistically
> significant (t=2.58, p=0.0099) — a naked IC cutoff ignores sample size. The
> "quant = 0.0" decision is **retained** because of the *independent* evidence
> below (decile non-monotonicity, regime sign-flip, ~zero residual
> attribution), not because of the IC threshold. The lesson logged: do not use
> a single IC threshold nakedly.

> Reference: `backend/tools/m26_quant_baseline` (evidence category);
> training gate constants in `backend/config.py`:
> `qlib_train_ic_floor = 0.04`, `qlib_train_icir_floor = 0.40`,
> `qlib_train_require_monotonic = True`.

### Stage A continued: M27 Alpha Diagnostic

The M27 alpha diagnostic tool (`backend/tools/m27_alpha_diagnostic`) went
deeper on the label objective.  Findings:

- **Regime sign-flip**: the Qlib factor's direction flipped sign between
  bull-market and bear/range-bound regime windows.  A signal that predicts
  +returns in one regime but −returns in another provides negative value in
  live operation unless the regime itself is reliably identified in real time.
- **Residual quant contribution audit** (`backend/tools/m29_quant_residual_attribution`):
  after netting out the technical and sentiment components, the residual
  attributable to the quant layer was not significantly different from zero
  across rolling out-of-sample windows.

### Stage A conclusion: M29 gate

The M29 evidence ledger (`backend/tools/m29_evidence_ledger`) compiled the
above findings into a single readable verdict:

> _"Technical IC flat/negative; regime sign-flip across market conditions.
> Quant signal provides no reliable edge independent of technical momentum and
> sentiment event scores. Weight set to 0.0 pending a new validated cycle."_

This verdict was accepted without override and encoded as the production
default.

---

## Why Not Just Set a Small Non-Zero Quant Weight?

Even a weight of 0.05 (5%) that points the wrong direction in a bear/range
regime will:

1. Systematically reduce composite scores for stocks whose technical setup is
   correct, causing missed entries.
2. Increase composite scores for stocks in downtrends that exhibit
   "value-factor" characteristics — exactly the wrong direction in a
   momentum-led market.

The regime sign-flip finding means a small non-zero weight is worse than zero
in expectation.  The decision is conservative and honest: keep quant
disconnected until forward/out-of-sample evidence shows a reliable edge.

---

## Reinstatement Criteria

The quant layer can be re-enabled by updating `.env` or environment, but only
after:

1. A fresh Qlib/Kronos training cycle on updated data.
2. The three hard-gate metrics (IC ≥ 0.04, ICIR ≥ 0.40, monotonic deciles)
   pass on a held-out validation window.
3. A forward-shadow run (`backend/tools/m29_forward_readiness` then
   `backend/tools/m29_shadow_validation`) shows positive out-of-sample IC for
   at least one full market cycle.
4. An explicit operator decision — not an automated promotion.

---

## Relationship to ATR Stop (2.5×)

The ATR trailing stop multiplier of 2.5 was set independently by the M4.9
exit sweep (see `docs/dev/M4.9_EXIT_SWEEP_2026-05-16.md`).  It is not a
compensation for removing quant; it is the standalone exit-discipline
conclusion from that sweep.  The two decisions are orthogonal.
