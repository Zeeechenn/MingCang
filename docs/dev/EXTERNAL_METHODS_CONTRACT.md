# External methods and bounded maintenance contract

This is a task-scoped acceptance record, not another queue. It carries forward
2026-09-24 reviewed proposals; source links establish provenance, not truth of
claims in a post. Review expiry is `2026-10-08T23:59:59+08:00`. See
[ROADMAP](../ROADMAP.md) for the single project queue and ordering.

## Global boundary

Use fixtures and immutable snapshots first. Keep live coverage, source/model
identity, user value and economic evidence as separate gates. At most two batches
at once. Snapshot SQLite with `scripts/sqlite_consistent_snapshot.py`, read
`mode=ro&immutable=1`, compare SHA-256, and put derived reports/tests/cache/output
outside the repo. Reject sidecars, source mixing, incomplete coverage, hash changes
or date-set drift. Do not patch official cards, test2, prices or ledgers. A proposal
or review date authorizes no runtime change.

## Market breadth to sector/theme explanation

Proposal source: [market-breadth share](https://www.xiaohongshu.com/explore/6ab3975b000000001a027fba "# hygiene-allow: reviewed proposal source URL; provenance only").

Status `proposed`; source/mapping gate has not passed. Owner `data` verifies source
and historical sector mapping; `research` defines interpretation. The only possible
consumer is existing `ResearchCase` theme context and
`backend/research/theme_hypothesis_engine.py`. Explore breadth → industry diffusion
→ theme mapping → candidates; do not import the post's 25% risk threshold or build
an empty panel.

Before implementation, freeze at least three public `as_of` cross-sections and
verify universe, effective dates of sector membership, mapping version,
numerator/denominator, missingness, source and hashes. If mappings cannot be
reconstructed, allow current observation only. Every number must be reproducible;
mixed dates/sources must block a single summary and missing values stay unknown.
The user must confirm on three themes that this reduces lookup steps. No increment
means no integration. Rollback closes the optional explanation entry and retains
the original ResearchCase.

## PanWatch workflow-difference review

Proposal source: [PanWatch share](https://www.xiaohongshu.com/explore/6ab1e6010000000034015b39 "# hygiene-allow: reviewed proposal source URL; provenance only").

Status `proposed`; reuse the existing eight-card Daily panel. Owner `portfolio/ops`;
sole consumer remains P0-A. Do not create a holdings page, nine agents, or parallel
notification system. Compare the 09-23 successful Track B artifact with the first
OAuth-failed run. Delivery without a source receipt is unknown.

If existing cards show complete/failed state and next action, add no code.
Otherwise freeze a minimal UI/data contract and fixture only after the user confirms
a specific gap. Acceptance requires both a real success and a real failure case:
locate holdings, inspect current run/evidence, confirm delivery state/next step. A
scan is not delivery; opinion is not completion. Rollback hides only the added
entry and retains cards/records.

## Batch screening and deep-research preflight

Proposal source: [batch-screening shares](https://www.xiaohongshu.com/explore/6aa95cdc000000002b01d50f "# hygiene-allow: reviewed proposal source URL; provenance only").

Owner `research`; sole consumer existing manual `backend.tools.m63_research`.
Optional `--preflight` is implemented as `experimental`: it reads watchlist/universe
input and prints target scope, submitted/unique counts, duplicates, format errors,
phase attempt caps, and unknown API/model/billing capacity. It does not invoke the
default pipeline, connect to DB, use network, write files, reserve providers, scan
the full market, or establish user value. Thirty-one focused m63/iFinD checks cover
this local contract. Default duplicate handling is unchanged. Default output
compatibility, clean price/action evidence and separate economic registration still
apply to strategy studies. Rollback removes only preflight; the existing CLI,
scanner and history remain.

## Source net increment

Owner `data`, acceptance by `evidence`; sole consumer explicit offline
source-acceptance report. First audit a consistent snapshot for missing fields,
symbols, dates/report periods, sources, disclosure times, definitions and
registered failures. iFinD and Financial-API are not independent confirmations. If
a remaining offline gap requires probing, freeze one source/category/symbol and
required fields; allow at most one request at repository QPS 1, write temporary
output outside the repo, and do not backfill or write production. Retain every
boundary sample and failure. Require at least one verifiable key-field net
increment; otherwise stop. Partial coverage limits use to covered fields. Remove
the experimental adapter/entry to roll back. P0-B2 write permission is separate;
current iFinD quota exhaustion grants no probe.

## Stock-page evidence context B1 and deferred B2

B1 is implemented as an opt-in `experimental` CN stock-page research section.
Owner `research`; rollback disables only that branch, retaining copilot, sessions
and judgments. The ten fixed acceptance questions are:

| Question | Required check |
|---|---|
| Latest visible financial report at cutoff? | Disclosure date, report period, source; never infer unknown. |
| Is revenue growth supported by profit? | Original values, comparable periods and YoY basis. |
| Is profit supported by operating cash flow? | Same-period cash flow; missing field stays missing. |
| How did earnings quality change over the last two visible periods? | Original values, revisions and visibility time. |
| What risks do current balance-sheet facts support? | Cite existing fields; do not invent ratios. |
| Does the selected price interval describe volatility? | Date coverage, gaps and stored price basis. |
| Could price change reflect corporate action/adjustment? | No definitive conclusion without action ledger. |
| Do facts support “cheap valuation”? | Reject strong conclusion without valuation/share-count inputs. |
| Can an old answer be reused after changing cutoff or symbol? | Cross-date/symbol isolation and citation version. |
| What new fact would overturn this view? | Verifiable condition/source and follow-up; no certain price prediction. |

Questions are fixed, but actual answer/source quality and user-time baseline are
unaccepted. Bind real current market/financial sources, model receipts and
human-check time; test cross-symbol/date, adjustment and unit failures. Fixtures
do not count as real results and do not erase the historical strict-data coverage
result of 0/26 or clear price/financial gates.

B2 is deferred, owner `research`, sole consumer existing ResearchCase. Start only
after B1 real acceptance and user value confirmation; first build 8–10
versioned/page-cited questions for each of three companies from public reports.
Objective answers must be quote-checkable; do not score subjective questions. A
correction pauses old questions. Remove the optional entry if there is no evidence
benefit or it adds burden.

## Macro / earnings breadth template

No separate capability. Owner `research`; consumer existing theme scenario card.
Wait for source timing/denominator and B1/B2 review. Validate at least three public
historical cross-sections for negative/zero bases, undisclosed items, revisions and
missingness. Separate macro facts, model interpretation and conditional judgment.
Without PIT or a verifiable denominator, current observation only: never feed
weights, sentiment veto, scheduler or trading.

## Conditional compatibility/runtime items

`require_signal_run_context` remains false. Tightening requires caller coverage,
old-output comparison and explicit enablement review; never auto-enable on the old
weekly-check date. Remove a compatibility entry only with zero internal consumers,
one release cycle and explicit approval. Atlas integration/shadow remains dormant;
archives do not restore or delete it. Historical maintenance closed 09-18 (live
subset path handling and panel production-shape regressions); old outputs were not
rewritten.
