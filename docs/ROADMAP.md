# MingCang One Loop — Sole Active Queue

> Updated 2026-09-24. The frozen 20-day v1 continuity gate is complete. The
> 09-23 formal run completed Track B and remains `PIPELINE_PARTIAL` on adjustment-
> basis drift. Current observed facts are in [STATUS](../STATUS.md); architecture
> and ownership are in [PROJECT](../PROJECT.md); shared rules are in [AGENTS](../AGENTS.md).

## Product and acceptance boundary

MingCang is a user-controlled research and decision-support system, not an
automated trader. Its goal is one source-timed daily evidence path from data and
positions through review to independently checked outcomes. Deterministic code
owns data/risk bounds; model suggestions, risk handling, human choices and actual
trades stay separately attributable.

This file alone orders active project work. STATUS records runtime truth;
PROJECT maps code/owners; CHANGELOG and archived reports are history. M numbers
are historical labels, not new workstreams. `proposed`, `experimental`, `shadow`,
`stable`, `dormant`, `rejected`, and `archived` have distinct meanings. A new
capability needs an owner, one consumer/entry, input/output/failure and safety
contract, sample/metric/expiry, provenance, tests, stop/rollback and replacement.
Stable status also needs a fresh run/output receipt. At most two implementation
batches at once; separate structural work from provider, DB/API, scheduling,
memory, replay or risk behavior changes.

## Active queue

### 1. New-date panel quality and human completion — P0-A/P1

Prove the full path: see a change, inspect evidence, accept/modify/reject, then
check the result. Keep the eight-card identity/order and frozen dates unchanged.
New-date output quality, actual human completion, delivery and outcome attribution
are separate gates. A saved opinion, scan, or committed panel is not task
completion, notification delivery, or a trade.

- Bind same-day watchtower to `as_of`/`run_id` and existing JobRun/committed artifact;
  temporary files cannot substitute. `ready_zero` requires complete coverage and
  a reason; it does not prove notification delivery or suppressed-event coverage.
- With zero LLM, event risk is `shadow`/`not_applicable` with reason, not “no risk”.
  Delta compares the previous price date's unique committed panel and records both
  dates, prior run, structured changes or `no_previous_reason`; it never infers
  actual trades or NAV.
- Human records bind original panel date/run/hash, reason and revised judgment;
  duplicates are idempotent, stale submissions rejected, observations append-only
  and version checked. A user “do not buy” applies only to the explicit symbol,
  scope and time; it does not auto-liquidate or broaden to a sector. No reply stays
  pending. Records do not rewrite the task, position, `ResearchState`, validated
  memory or old completion metric.
- Preserve fixed quality-window outcomes `passed/blocked/failed/missing/not_due`,
  denominators, source hashes and failures. The original five-session window expired
  2026-09-22 23:59:59 +08:00; heartbeat is paused. 09-22 remains missing; offline
  refresh is not backfill. Do not retry or consume the original reservation. New
  experiments need a new window and authorization. Rollback stops the new entry and
  retains records/panels; it does not rewrite sealed dates.

### 2. Data foundation and independent maintenance — P0-C, P0-B1/B2, then P0-R

First cover the official pool and **current actual holdings** together, then clear
price/action evidence before NAV work. See the task-scoped
[`P0_DATA_FOUNDATION_CONTRACT.md`](dev/P0_DATA_FOUNDATION_CONTRACT.md) for exact
P0-C point-in-time, P0-B1/B2 write-safety, 09-17 data-scope and 09-24 iFinD
constraints, and P0-R conservation cases. No clearance, coverage result or
sensitivity analysis is write permission or strategy evidence.

### 3. Independent shadow branch — news event-risk/direction (no queue reprioritization)

Keep one news capability with two independently evaluated products: event-risk
facts and direction scores. Direction remains shadow with zero official signal
weight. Event risk may use only existing `daily_panel.news_event_risk`; no new
source permission, M-number, parallel system or production switch. The explicit
offline readiness audit is implemented, but protocol and sample-capacity freeze
are not; review due 2026-10-23. Follow
[`NEWS_EVENT_RISK_CONTRACT.md`](dev/NEWS_EVENT_RISK_CONTRACT.md) only for this work.
It preserves the proposed (not frozen) 20 real run days / 30 verified-event
minimum, direction thresholds, distinct denominators, unknown-as-unknown, and the
prohibition on a recall claim without an independent reference universe. Event
review passing never clears direction scoring. A skipped `no-llm` run is not news
coverage or evidence of zero risk.

### 4. Bounded model research and universe comparison — P2

Do not merge model research with daily production runs or the existing authorized
fixed-25 channel check. That older non-economic check covers 25 public-pool inputs,
two destinations and at most 60 periods; it permits only invocation/identity/usage/
isolation/recording acceptance, not NAV or strategy claims. Preserve failed and
missing periods, fixed denominators and exact scope; no retry, substitution, refund
or silent fallback. Economic replay requires trusted prices/actions, source truth,
isolated accounts, actual provider/usage/billing receipts and separate owner/economic
approval. The v3 candidate stays default-off, `prepared_not_activated`, and fake-only.
See the task-scoped [model contract](dev/MODEL_COMPARISON_CONTRACT.md) for the old
channel experiment.

The proposed **full-market versus fixed-25 GPT-6 universe trial** is a separate
research item, distinct from the daily run and from that existing authorization.
Keep its candidate, scope, data authorization, denominator, failure rules and
acceptance in its own trial record; do not inherit the old 60-period approval or
change daily behavior. Do not execute until that trial's own frozen contract and
gates are satisfied.

### 5. Trusted attribution and one-variable improvement — P3/P4

After the data and economic gates clear, first independently replay old decisions
without new model calls or rewriting history. Then choose one change based on
attributed loss (holding/exit, opportunity discovery, portfolio choice, second
opinion, or memory) and compare one variable in a new shared window. Historical
model replay may contain training leakage and is exploratory only. Full-window
failure denominator, fee-net return/IR/NAV, tail-risk, concentration and
block-bootstrap requirements are in the [model comparison contract](dev/MODEL_COMPARISON_CONTRACT.md#later-economic-comparison-reporting). Use the same
start, close-confirmed data/universe, fills, costs and risk; freeze cash, executable
buy-and-hold and a simple-rule baseline. If a whole tool path may query, report that
as the treatment. Whole-lot affordability stays in exposure and is not strict
equal-weight. Do not assume relaxing stops or extending holds is the answer.

## Deferred history

The prior 20-day v1 gate, completed M lines, external project reviews and old
implementation narratives are not queue items. Find their records in CHANGELOG,
Git or the [archive digest](evidence/document_archive_digest.md). Do not use
historical counts or old proposals as current runtime evidence or renewed approval.

## Other bounded proposals (not a queue ordering)

The reviewed external-method microbatches retain their own owner, consumer,
acceptance and rollback contracts in
[`EXTERNAL_METHODS_CONTRACT.md`](dev/EXTERNAL_METHODS_CONTRACT.md); all share the
2026-10-08 23:59:59 +08:00 review expiry. Market breadth is `proposed` behind its
source/mapping gate; PanWatch is `proposed` pending real success/failure workflow
comparison; existing `m63_research --preflight` is opt-in `experimental`; source
net-increment remains offline-first and no iFinD probe is authorized; stock-page
B1 is implemented but real source/user-value gates remain; B2 waits for B1 and
user confirmation; macro/earnings breadth is a research template only. These do
not reorder the P0/P1/P2 queue above. `require_signal_run_context` stays false
pending caller coverage/output review/explicit enablement; Atlas stays dormant.
