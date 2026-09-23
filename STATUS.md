# MingCang — Current Status

> Updated 2026-09-24. Latest formal daily evidence is the 2026-09-23 run, which ended
> at 00:25 on 09-24 as `PIPELINE_PARTIAL` (exit 4). Track B completed; One Loop remains
> blocked by uncleared adjustment-basis drift. Plan: [ROADMAP](docs/ROADMAP.md).
> Architecture: [PROJECT](PROJECT.md). History: [CHANGELOG](CHANGELOG.md).

## Runtime and evidence

| Surface | Current verified state |
|---|---|
| Version | Package/API/frontend version `v0.8.3`; publication receipt is the matching GitHub tag/release |
| Configuration, last inspected 09-17 | technical/sentiment `0.6/0.4`, quant `0.0`, entry `25.0`; memory decision context and Atlas disabled; scheduler `manual` (not proof of worker liveness) |
| Frozen One Loop v1 | 20/20 complete closes, 2026-08-19–09-15; 20 unique batches/envelopes and committed eight-card panels; 4/20 degraded days |
| Continued complete dates | 21 complete dates / 26 comparison dates; this does not make every comparison date complete or upgrade quality/economic gates |
| 09-17 | 25/25 official-pool prices were refreshed later; original signal/job/panel evidence is absent and was not backfilled |
| 09-18 | Track B complete; Track A retained `PIPELINE_PARTIAL` due uncleared basis drift for 300394 and 603993; panel exists but fails the integrity gate |
| 09-22 offline check | 25/25 official and 56/56 watchlist OHLCV/technical checks; historical rows are not certified PIT/adjusted prices and do not constitute a same-day run |
| 09-23 formal run | Resumed after user restored local Claude OAuth; 25/25 official signals, 8 committed panel cards, 56/56 broad scan, 6 new + 1 reused labels, 3/3 deep reviews. Track B complete; Track A remains `uncleared_adjustment_basis_drift`, so final state is `PIPELINE_PARTIAL` (exit 4) |
| 09-23 recovery evidence | First attempt stopped on expired OAuth and retained 11 partial signals in an `error` run. Recovery finished 00:25:27 on 09-24 with 85 logged calls: official 16, broad 54, labels 6, deep 9, panel 0. This is not token or billing evidence. A process-level auth circuit breaker now stops repeated calls after an auth failure; it does not certify future login or output quality |
| 09-24 iFinD check | One approved `603986 search_news` request for 09-21–23, size 5, returned answer-only “当前账户MCP请求用量已耗尽”; no notice request or retry. Current account quota exhaustion is confirmed; plan tier and refresh date remain unknown. Parser/provider handling now classifies this as quota failure and stops or falls back; coverage is not restored |
| Price/NAV | `blocked_price_basis`; 20 saved-collection symbols affected and no authoritative complete corporate-action ledger. No trustworthy return promotion |
| Research/market scope | CN daily path; HK/US gray/shadow and news direction research do not imply official production or trading activation |

The 09-23 evidence is in the user-provided `明仓日测_2026-09-22_23/测试结果.md`; run logs,
batch IDs and saved outputs are retained there and under its evidence directory. The
09-22 formal run remains `missing`: its available run used 09-21 market data, and the
09-22 refresh was offline-only. Do not synthesize that date's signals, jobs, panels,
labels or human decisions. The 09-23 report records a read-only final DB snapshot at
`/private/tmp/mingcang-daily-20260923/final.db`; never write it during this review.
Recovery IDs: official run `3bbeeeca7af249ed9d77951a9ebe70fa`, panel
`3785c5dac0ff4410ab09c4cfd0368c5d`, broad scan `56ee6750357f4a089c1a27ac360f31ba`,
deep review `d3fb33bfe40e4885a8824a0836bd44ff`; first-attempt error
`f622a0d9236747c68e3df096fa44afdd`.

The canonical start date remains non-rolling. Preserve frozen artifacts. A clearance
records an operator fact; it does not repair prices, recreate a missing run or release
the current drift blocker.

## Implemented capabilities and open gates

| Area | Implemented | Still open |
|---|---|---|
| One Loop / P0-G | One canonical start date, explicit compared/complete date sets, durable run/panel identity | New-date quality and complete evidence remain separate from continuity counts |
| P0-A operator flow | Eight-card panel, same-run watchtower and prior-panel delta, explicit no-LLM state, manual accept/modify/reject and append-only observations; 09-23 Track B completed | Fresh output quality, real user completion, notification delivery, and independently checked outcomes. A saved opinion or a completed scan is not task completion, delivery, or a trade |
| P0-B price safety | Dry-run and opt-in strict/warmup guard; short-window ATR cause reproduced; 09-23 official prices fresh | Resolve basis/action/volume-unit evidence for the current affected scope; five earlier TickFlow candidates were missing. Any write still requires its own immutable backup, reviewed impact, maintenance window, rollback, and explicit approval. Default strict/warmup callers remain unchanged |
| P0-R NAV | Manual-only cash NAV with explicit next-open, cost, halt, partial-fill, and action semantics | Clean price basis and authoritative action inputs. Proxy diagnostics cannot promote returns |
| P0-C research inputs | Strict financial/label/text context and account-aware pending drafts | Full current-period financial coverage, revision/disclosure time, intraday PIT and separately reviewed consumer wiring |
| P1/P2 experiments | Four-gate audit, saved-window reader, recorder, frozen budgets, optional manifest v2/folds/holdout, bounded local diagnostic process | Provider identity and billed usage, source/calendar truth, isolated account/credentials and economic launch gate |
| Stock-page evidence workspace | Experimental opt-in evidence context, citations, versioned judgments and history | Real source/model acceptance, user time/error baseline and follow-through. Engineering fixtures do not establish utility or investment benefit |
| `m63_research --preflight` | Opt-in `experimental` report reads watchlist/universe input, identifies duplicate/invalid targets and describes phase capacity and unknown model/API/billing bounds; default execution and duplicate behavior are unchanged | It is not a full-market scan, capacity reservation, source authorization or user-value acceptance |

Do not label a capability stable or default merely because code exists or fixtures pass.
Memory routing, risk policy, historical prices, schedules and real trading actions have
not been promoted by this work.

## Model experiments and current boundary

The separate five-session GPT-6 factual-quality heartbeat is expired and `PAUSED`.
09-22 remains missing; its offline refresh does not create a formal session and must not
be backfilled. The 09-16 raw arm failed during local initialization; desk was not started.
There is no paired model result, resolved model receipt, billed-cost evidence or successful
economic treatment. Do not retry its failed/missing slots, replace its runner, or infer
model quality from the successful 09-23 production pipeline.

Separate GPT-6 / Claude model-agent work remains `experimental`, not economic activation.
The already approved non-economic channel-check scope is 25 public-pool inputs, two
destinations and at most 60 periods. The candidate is `trial_canonical_v2.py`; the
`backend.tools.model_comparison` v2 verifies registration and authorization hashes,
reports 1 reserved / 59 remaining under the shared 60-period scope, and has an explicit
`--request-context` mode that emits only the selected arm's close-time account context.
Its 48 focused CLI/account-adaptation tests prove local behavior, not a provider result.
The frozen runner still resets cash each period; continuous-account wiring needs raw
price/action gates and a separately registered version. A real-channel acceptance may
run at 23:00 on a later eligible workday within the prior scope; it does not require the
price-basis gate that blocks economic NAV evaluation. Freeze the exact input and cutoff,
then capture actual requested/resolved provider and usage receipts during the call.
Preserve failures in the fixed denominator. Do not require provider identity before the
call, ask for the same scope again, or retry a failed period. Economic replay requires
trusted prices/actions, account isolation and separate owner/economic approval. The
09-23 OAuth recovery shows only that local login was available for that daily run.

## Retained historical constraints

- New source capability proposals remain research-only until their own acceptance; existing source routing is documented in the data handbooks. Keep QPS limits, source provenance,
  disclosure dates, price bases, units, and failed/unknown requests explicit.
- M67 HK/US full promotion remains on hold; M68 news direction remains shadow; M57
  decision-memory routing stays disabled; P0-B2 writes require a separate gate.
- P0-B1 does not alter routine callers. P0-B2 requires an immutable backup, coverage
  review, write approval, maintenance window, rollback and owner acceptance.
- The 20-day v1 baseline, frozen daily artifacts, audit ledgers and experiment receipts
  remain immutable. Return claims require a clean independent NAV and separate economic
  evidence.

## Verification boundary

Release verification on 2026-09-24 passed isolated `make verify`: 2,492 backend tests
passed / 14 optional tests skipped, 51 frontend tests passed, Ruff, mypy (379 source
files), build, ESLint and desktop/mobile Chromium smoke passed. One new announcement
quota regression was added after collection; its targeted run passed 19 tests (18
already counted), giving 2,493 distinct passing tests. The sole warning is an existing
Starlette/httpx test-client deprecation. Version/lock consistency, release hygiene,
document authority and strict MkDocs build passed. Browser smoke covered questions,
judgment/observation saving, reload and stale-selection handling, not every API error.

The 09-23 daily report remains the separate runtime evidence. These checks do not
clear source/model identity, billing, human-completion or economic gates. Current
implementation narratives and recoverable originals are indexed in the
[archive digest](docs/evidence/document_archive_digest.md).
