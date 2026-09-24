# News and event-risk acceptance contract

This is a task-scoped contract for the existing M54/M68 shadow capability. It is
not a project plan, source authorization, frozen forward protocol, or production
enablement. The active queue and review date live in [ROADMAP](../ROADMAP.md);
current evidence lives in [STATUS](../../STATUS.md). Event-risk facts and news
direction are independent products with separate gates.

## Current boundary

- One capability owns both the M68 event-risk mirror and M54 direction research.
  Event-risk may reach only the existing `daily_panel.news_event_risk` consumer;
  direction remains shadow with zero official-signal weight. No parallel system,
  new M number, new source permission, or production switch is authorized.
- `backend.evidence.news_event_readiness` is an experimental explicit offline
  audit. It reads a caller-supplied immutable SQLite snapshot and writes an
  external report. It does not connect to sources, call models, or write the
  business DB or official panel. Missing evidence is blocked/unknown, never zero.
- Preparation owner is `evidence`; the event-fact contract owner is `data`.
  Batch 1's only new consumer is this explicit offline readiness CLI; the existing
  product consumer remains `daily_panel.news_event_risk`. Batch 2's direction
  consumer is an explicit offline validation report only.
- The readiness CLI and snapshot audit are implemented. A frozen protocol and
  sample-capacity assessment are not. Review is due 2026-10-23; expiry does not
  renew scope or authorize work.
- The v2 audit makes a narrow as-of availability-cohort change: freshness,
  status, trigger and token metrics include only runs with a known `created_at`
  on or before the inclusive cutoff. Late/unknown-created rows are excluded from
  those current metrics but kept visible in history/exclusion/failure reporting;
  no attempt is erased. This remains date-level filtering, not strict PIT proof.
- The portable `scripts/research_checks/joint.py` wrapper runs registered market
  preflight and snapshot readiness with separate stage outputs. `make research-test`
  runs news, universe and joint regression checks together; this is the default for
  “跑测试”. Logs go to a fresh external directory; `OUT_DIR` may choose that new
  directory. Formal daily tests remain an explicit, separate request.
- `prepare --market-input FILE --news-snapshot FILE --as-of YYYY-MM-DD --out-dir DIR`
  requires same-date market inputs and a checkpointed standalone immutable news
  snapshot. `demo --out-dir DIR` uses synthetic data. Run either with
  `python scripts/research_checks/joint.py`. Neither command calls sources/models,
  writes business data or activates a forward trial. The shared A/B candidate and
  holdings union is only a future raw-evidence plan, not news-universe coverage or
  measured token savings. Source/protocol hash mismatches fail closed.
- Original external trial records remain unchanged; the portable bundle has its
  own registration. This entry does not inherit the old fixed-25 channel trial's
  reservations or authorization. Rollback removes the new entry/route and retains
  reports and original experiments; no historical run is rewritten.

## Event-risk product gate

The proposed minimum product sample is at least 20 real run days and 30 verified
events. These are planning targets, not a frozen protocol or statistical
sufficiency claim. Before viewing this validation's outcomes, freeze final
targets, rules, universe, model, shared window, code/parameters, exact budget and
failure policy.

Blindly adjudicate triggered, untriggered, failed, and high-importance events.
Report each denominator, coverage, source and fact accuracy, timing, and
degradation. A major factual error or missed major event blocks acceptance.
Without an independently sourced reference universe, do not report recall or
present model-triggered events as the true event set. Events with no trigger may
be omitted from direction IC, but remain in overall decision-effectiveness,
trigger-quality, and missed-event review.

## Direction gate

Retain the historical preregistered thresholds in
[`M54_OOS_PREREGISTER.md` §§4, 13](M54_OOS_PREREGISTER.md): separately for h3d
and h5d, IC at least 0.04, ICIR at least 0.40, at least 20 non-overlapping IC
dates, and monotonic bucket returns; `v2-full` versus `legacy-fast` must have
delta IC at least 0.02 at each horizon and fallback below 10%. Also report the
pre-isolated holdout, cross-period stability, and economic costs. Twenty means
valid non-overlapping sample dates, not calendar days. A five-trading-day label
needs about 100 trading days plus the label tail from a zero start; more symbols
cannot replace time coverage. Price/adjustment drift blocks direction-return
judgment, but does not block independently verified event-fact review. Passing
event review never implies direction passes.

## Evidence, failure, and source boundary

For each item retain raw source, source publication time, fetch and revision
times, `as_of`, visible content, decision cutoff, raw and normalized content
hashes, universe, model, shared three-arm window, and request/response versions.
Unknown capacity, budget, usage, or cost stays `unknown`; call counts, token use,
and actual billing are separate measures. Current iFinD quota exhaustion does
not authorize a request, retry, or substitution of old data/models. Any future
external call needs a newly frozen exact scope, frequency, budget, and
exclusions, then its own authorization. This phase makes no external source/model
call. Production direction scoring requires
separate explicit user confirmation.

If sources, identity, sample, or cutoff cannot be verified, stop the affected
attempt and retain its failure. Do not silently renew, expand, or retry. Rollback
for the offline audit is to stop invoking it and remove its read-only adapter;
producer, panel defaults, and switches remain unchanged.

## Follow-on direction validation

If separately authorized, compare exactly `v2-full`, `legacy-fast`, and
`v2-pyramid` on one frozen universe/model/cutoff/common window. Before seeing
outcomes, jointly preflight identity, duplicate keys, source consistency and time
boundaries across all three arms; then freeze code, parameters, exact budget and
failure policy. Save each visible input and request/response bytes and hashes.
This follow-on trial is not frozen or started. If billing remains unknown, cost
assessment and promotion stay blocked. Independently verifiable event-fact review
may continue when source and timing are proven.

For an affected failed batch, retain the failure and stop its attempt. Batch 1
rollback stops the explicit CLI and removes its read-only adapter. Batch 2 rollback
stops only its new offline validation/report path; neither batch changes M54/M68
producers, panel defaults or switches. Expiry and event-fact acceptance never
enable direction scoring.
