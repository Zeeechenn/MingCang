# News and event-risk acceptance contract

This is a task-scoped contract for the existing M54/M68 shadow capability. It is
not a project plan, source authorization, frozen forward protocol, or production
enablement. The active queue and review date live in [ROADMAP](../ROADMAP.md);
current evidence lives in [STATUS](../../STATUS.md). Event-risk facts and news
direction are independent products with separate gates.

## Owner-prioritized historical research (09-24)

The owner now asks for actual historical stock/news experiments before waiting for
new daily data. This supersedes the generic request's offline-check routing, not
the frozen files or results of prior experiments. `make research-test` is the new
explicit historical entry; `make research-check` preserves the old regression
suite. Missing inputs or model execution must never silently fall back to fixtures.

The explicit adapter uses `backend.backtest.historical_technical` and
`backend.evidence.historical_news_inputs`; the only consumer is the manual joint
CLI. It reuses the existing technical score and cross-sectional statistics, not a
new NAV engine. Inputs/outputs remain external to the repository and production
DB. No scheduler/provider default, official signal, position or ledger is changed.
Rollback removes the new opt-in entry while preserving source and failed-run data.

Two real market source windows were collected independently of old reservations:
2025-09-16..12-31 (71 sessions, 385,922 rows, 5,474 observed codes) and
2026-05-22..08-28 (70 sessions, 386,560 rows, 5,564 observed codes). Historical
source-day rows define the observed market sample; suspended/omitted securities,
retirements, industry changes and complete historical membership remain separate
coverage questions. Current stock_basic labels are descriptive only. Raw prices
are not QFQ or certified economic returns. The 2026 calendar is derived from
identified exchange holiday notices; the rate-limited Tushare attempt is retained,
not retried or presented as successful. Local source receipts/inputs are under
`mingcang-historical-tests-20260924/` in the Codex workspace.

The optional factor source reuses `backend.data.tushare_qfq._normalize_qfq`,
anchored to each decision date, with per-key factor and residual price-continuity
checks. It must not silently fall back to raw prices when factors are incomplete.
The first actual factor request returned API 40203 (one request/hour); the other
69 dates were not requested. Thus adjusted replay remains unexecuted. Raw replay
retains its own exclusions and results; a tested adapter is not successful data
acquisition or price repair.

The shared pilot decisions are 2026-08-17..21, with labels through 08-28. Freeze
candidate lists using only decision-time features; future missing labels never
cause replacement selections. Five dates are an engineering pilot, not statistical
acceptance. Report raw-direction IC separately from execution-aware NAV, costs,
company actions and strategy claims. The original fixed-25 file remains pinned;
this technical-only comparison is not the GPT-6 experiment.

Installed v4 replay completed both predefined windows. The 2025 December pilot
scored 4,533–4,565 observed names/day (fixed-25: 13–14); full-market h3/h5 mean
RankIC was -0.052673/-0.040616. The August 2026 pilot scored 2,463–2,635/day
(fixed-25: 4–6); full-market means were +0.007972/-0.009912. The fixed-25 August
arm had only two eligible IC dates. Both are conditional raw-price diagnostics,
not statistically accepted performance; historical availability of the fixed
comparison list is unproven. Full scores and pre-label selections are receipted.
The installed joint entry completed technical replay and news extraction, returned
`partial_news_models_blocked` (child exit 4, make exit 2), and preserved source
hashes. 38 focused/document/architecture tests plus 6 subtests and the 44-case
registered regression entry passed; lint, targeted typing, doc/hygiene passed.
No actual model inference or adjusted-data replay is implied by those checks.

News inputs use a three-calendar-day lookback and publication/fetch timestamps
strictly before each decision date at 00:00 Asia/Shanghai, preserving source
fields and hashes. Technical inputs include that date’s close: the shared dates
do not imply identical intraday information cutoffs. Unknown
market identity, missing/inconsistent timestamps and missing records are explicit
exclusions; no cached sentiment or summary may enter the model input whitelist.
Timestamp filtering does not establish historical revision truth or rule out LLM
training leakage. Inputs can be shared; arm-specific judgments/cache identities
must bind model, prompt, code, cutoff and input hash. Record overlap reduction
separately from actual token use and billing.

**Actual news/model inference remains unrun.** The historical orchestration must
report partial/blocked and a non-success exit when only inputs were prepared.
The three-arm adapter, exact requested/resolved identities, common eligible
sample and receipts must be frozen before calls. The owner permits existing
subscription quota only, with zero new API fees. Check the authenticated subscription
channel; never fall back to pay-as-you-go API keys. Domestic models are under
discussion, not authorized replacements. Do not reuse prior reservations, silently
switch experiment models, or treat a model failure as zero.
Claude first-party CLI is currently logged out; the owner explicitly deferred
login and asked to finish the other work. No news model calls were attempted.
The old preregistration requests Sonnet 4.6 for all arms, while current legacy-fast
code hardcodes the fast tier (configured Haiku); local CLI routing also prefers
Codex by default. A later isolated adapter must resolve and receipt this mismatch,
reuse the actual arm algorithms, disable fallback/retry, and never call the current
production/cache-writing harness unchanged. Do not treat CLI presence as auth.
A technical run, an input package and a completed model experiment are three
different states. Longer historical validation and later forward checks remain
necessary; thresholds below are not met by this pilot.

## Original offline audit boundary

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
  preflight and snapshot readiness with separate stage outputs. `make research-check`
  runs news, universe and joint code regressions together. Logs go to a fresh
  external directory; `OUT_DIR` may choose that new
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
