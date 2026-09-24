# MingCang — Current Status

> Updated 2026-09-24. Latest formal daily evidence is the 09-23 run, completed at
> 00:25 on 09-24 as `PIPELINE_PARTIAL` (exit 4): Track B completed; One Loop remains
> blocked by adjustment-basis drift. [ROADMAP](docs/ROADMAP.md) is the sole queue;
> [PROJECT](PROJECT.md) is the architecture map.

## Runtime truth

| Surface | Verified state |
|---|---|
| Release | Package/API/frontend version `v0.8.3`; publication requires the matching GitHub tag/release receipt. |
| Configuration (last inspected 09-17) | technical/sentiment 0.6/0.4, quant 0.0, entry 25.0; memory decision context and Atlas disabled; scheduler `manual` (not worker-liveness evidence). |
| Frozen One Loop v1 | 20/20 complete closes (08-19–09-15), 20 unique batches/envelopes, committed eight-card panels; 4/20 degraded. Immutable continuity baseline only. |
| Later dates | 21 complete / 26 compared dates; comparison counts do not make every date complete or clear quality/economic gates. |
| 09-17 | 25/25 official-pool prices refreshed later; original signal/job/panel evidence is absent and was not backfilled. |
| 09-18 | Track B complete; Track A `PIPELINE_PARTIAL` on basis drift for 300394 and 603993. Panel exists but fails integrity. |
| 09-22 | Offline check: 25/25 official and 56/56 watchlist OHLCV/technical checks. Historical rows are not certified PIT/adjusted prices or a same-day run. Formal run remains missing; available run used 09-21 data. |
| 09-23 formal run | 25/25 official signals, 8 committed panel cards, 56/56 broad scan, 6 new + 1 reused labels, 3/3 deep reviews. Track B complete; Track A remains `uncleared_adjustment_basis_drift`; final `PIPELINE_PARTIAL` (exit 4). |
| 09-23 recovery | First attempt stopped on expired OAuth with 11 partial signals in an error run. Recovery ended 00:25:27 with 85 logged calls (official 16, broad 54, labels 6, deep 9, panel 0); this is not token/billing evidence. Auth circuit breaker stops repeated calls after an auth failure but proves neither future login nor quality. |
| 09-24 iFinD | One approved `603986 search_news` request for 09-21–23, size 5, returned answer-only “当前账户MCP请求用量已耗尽”. No notice request or retry. Account quota exhaustion is confirmed; plan and refresh date unknown. Parser/provider now classifies quota failure and stops or falls back; coverage is not restored. |
| Price/NAV | `blocked_price_basis`; 20 saved-collection symbols affected; no authoritative complete corporate-action ledger. No trustworthy return promotion. |
| Scope | CN daily path. HK/US, news direction, and model experiments are shadow/experimental and do not imply production or trading activation. |

The 09-23 report and outputs are in the user-provided `明仓日测_2026-09-22_23/测试结果.md`
and its evidence directory. Recovery IDs: official `3bbeeeca7af249ed9d77951a9ebe70fa`,
panel `3785c5dac0ff4410ab09c4cfd0368c5d`, broad scan
`56ee6750357f4a089c1a27ac360f31ba`, deep review
`d3fb33bfe40e4885a8824a0836bd44ff`; first-attempt error
`f622a0d9236747c68e3df096fa44afdd`. The read-only final snapshot is
`/private/tmp/mingcang-daily-20260923/final.db`; do not write to it during review.
The canonical start date is non-rolling: preserve frozen artifacts. Clearance records
an operator fact; it does not repair prices or recreate a missing run.

## Implemented capabilities and gates

| Area | State and open gate |
|---|---|
| P0-A panel | Eight-card panel, same-run watchtower/prior-panel delta, explicit no-LLM state and append-only human observations. 09-23 Track B completed. Fresh content quality, real user completion, notification delivery and independently checked outcomes remain separate. Opinion or completed scan is not task completion, delivery, or trade. |
| P0-B price safety | Dry-run and opt-in strict/warmup guard; short-window ATR cause reproduced; 09-23 official prices fresh. Resolve basis/action/volume-unit evidence for current scope; five earlier TickFlow candidates were missing. Any write needs its own immutable backup, reviewed impact, maintenance window, rollback and explicit approval. Defaults unchanged. |
| P0-R NAV | Manual-only cash NAV with explicit next-open, costs, halts, partial fills and actions. Clean price basis and authoritative actions required; proxy diagnostics cannot promote returns. |
| P0-C research inputs | Strict financial/label/text context and account-aware pending drafts. Full current-period coverage, revision/disclosure time, intraday PIT and separately reviewed wiring remain open. |
| P1/P2 experiments | Four-gate audit, saved-window reader, recorder, frozen budgets, optional manifest v2/folds/holdout and bounded local process. Provider identity/billed usage, source/calendar truth, isolated account/credentials and economic approval remain open. See [model contract](docs/dev/MODEL_COMPARISON_CONTRACT.md) for that task only. |
| News/event risk | Explicit experimental offline audit CLI reads a caller-supplied immutable SQLite snapshot and writes an external report only. Snapshot has 50 shadow rows on two dates (07-16, 08-19; latest 36 days old) and zero feedback rows. Stored token values are zero but do not prove zero use/cost. PIT, independent human gold, reconciled cost and forward samples are unverified; direction remains shadow. See [news contract](docs/dev/NEWS_EVENT_RISK_CONTRACT.md) for that task only. |
| Stock-page evidence | Experimental opt-in context, citations, versioned judgments/history. Real source/model acceptance, user time/error baseline and follow-through remain open; fixtures do not establish utility or investment benefit. |
| `m63_research --preflight` | Opt-in experimental watchlist/universe validation and capacity/unknown-bound report. Not full-market scan, capacity reservation, source authorization or value acceptance; defaults unchanged. |
| Joint universe/news research package | `prepared_not_activated`; repo-owned `make research-test` checks news + universe together, with external logs and no model calls. `scripts/research_checks/joint.py prepare` accepts explicit same-date snapshots; `demo` uses synthetic inputs. Separate stage gates and candidate/holdings union plan; no production or schedule change. Audit v2 excludes late/unknown-created rows from as-of metrics and preserves history. Date-level, not strict PIT; no forward trial or measured savings. See [news contract](docs/dev/NEWS_EVENT_RISK_CONTRACT.md). |

Code or passing fixtures do not make a capability stable/default. Memory routing,
risk policy, historical prices, schedules and real trading actions are not promoted.

## Model and source boundary

The five-session GPT-6 heartbeat is expired/`PAUSED`; 09-22 is missing; 09-16 raw
failed initialization and desk never started. No paired result/provider/billing
receipt or economic treatment exists. Do not retry or replace those slots. The
separately approved fixed-25 channel check remains 1/60 reserved; v2 is frozen and
v3 is default-off, `prepared_not_activated`, fake-only. No evidence clears
source/provider truth, billing, isolation or economic approval. See the [model
contract](docs/dev/MODEL_COMPARISON_CONTRACT.md).

## Verification boundary

On 09-24, fresh-environment release verification passed: dependency audit, full
`make verify` (2,493 backend tests / 14 optional skips, 51 frontend tests, Ruff,
mypy 379 files, build, ESLint, desktop/mobile Chromium smoke), plus 71 candidate/
architecture tests and final lint/typecheck/document checks. Across those runs:
2,507 distinct passing cases. Warnings were third-party Starlette/httpx and
backtrader deprecations. Browser smoke covered questions, judgment/observation save,
reload and stale-selection handling, not every API error. Hosted CI supplies the
combined full-suite/coverage receipt for the published commit.

These checks do not clear source/model identity, billing, human completion or
economic gates; daily evidence remains separate. Recoverable
documentation originals and archive metadata are indexed in the
[archive digest](docs/evidence/document_archive_digest.md).
