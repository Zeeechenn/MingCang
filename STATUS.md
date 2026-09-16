# MingCang — Current Status

> Updated 2026-09-17. Latest saved runtime evidence ends at the 2026-09-16 close;
> no 09-17 close exists yet. This is a dated snapshot, not proof a worker is running.
> Plan: [ROADMAP](docs/ROADMAP.md). Architecture: [PROJECT](PROJECT.md).
> Completed implementation history: [CHANGELOG](CHANGELOG.md), read on demand.

## Runtime and evidence

| Surface | Verified state / boundary |
|---|---|
| Version | package/API/frontend `v0.8.2`; later working-tree changes are unreleased |
| Configuration, read 09-17 | technical/sentiment `0.6/0.4`, quant `0.0`, entry `25.0`; memory decision context and Atlas disabled; scheduler mode `manual` (not worker liveness) |
| Frozen One Loop v1 | 20/20 complete closes, 2026-08-19–09-15; 20 unique batches/envelopes and committed eight-card panels; 4/20 degraded days |
| Continued operation, 09-16 | 21/20 complete closes, 21 matched batches/panels, 4/21 degraded days; separate from the frozen 20-day baseline |
| Daily pipeline, 09-16 | Track A and B complete, `PIPELINE_DONE`; first partial attempt remains recorded; owner-approved same-day drift clearance did not repair prices or rerun the successful artifacts |
| New output window, 09-16 | operational gate passed; output gate blocked by `watchtower:degraded` and `human_confirmation:degraded`; event risk `not_applicable`, daily delta ready |
| Existing review metrics | completed/required `0/92`; fresh/total `92/2913`, cross-day aggregated task metrics, not a count of new human review records |
| Price/NAV evidence | `blocked_price_basis`, 20 affected symbols in the saved collection; authoritative corporate-action ledger unavailable; no trustworthy return promotion |
| Research/market scope | CN daily path; HK/US gray/shadow and news direction research do not imply official production or trading activation |

Runtime sources: `paper_trading/_run_state_20260916.json`, the saved 09-16 quality
collection's `continuity.json`, `panel.json`, `nav.json`, `readiness.json` and manifest.
The private LEADER handoff locates local evidence; do not load it for ordinary coding.
The canonical start date is non-rolling. Keep the frozen baseline and old artifacts
immutable; 21/20 does not upgrade new output quality or economic evidence.

## Implemented capabilities and open gates

| Work | Already implemented — do not reopen as missing | Still open |
|---|---|---|
| P0-G | one canonical start date and explicit compared/complete date sets | only a reviewed migration may change the date |
| P0-A | same-run durable watchtower, previous committed-panel delta, zero-LLM shadow reason, 1/5/2 metadata, visible empty states; accept/modify/reject and appended human observations | fresh output quality, real user completion and independently checked outcomes; a saved opinion is not task completion or a trade |
| P0-B1/B2 | immutable dry-run, opt-in strict/warmup guard; short-window ATR cause reproduced; full-history candidates for 25 official-pool symbols | current holding coverage, authoritative actions and separately approved maintenance; default strict/warmup callers unchanged |
| P0-R | manual-only cash NAV with explicit execution/cost/halts/partial-fill/action semantics | clean price basis and authoritative action inputs; proxy diagnostics cannot promote returns |
| P0-C | strict financial/label/text context, account-aware pending drafts and read-only copilot candidate | full current financial coverage/revisions/intraday PIT and separately reviewed consumer wiring |
| P1/P2 | four gates, saved-window audit, recorder, frozen budget sessions, optional manifest v2/folds/holdout control and bounded diagnostic processes | trustworthy provider identity/billed cost, account isolation, source/calendar truth and economic launch gate |

These are implementation facts, not blanket `stable` or default-consumer claims.
Memory routing, production risk settings and historical prices were not promoted.
The frontend redesign remains a separate isolated preview; it is not evidence of
live model/account/data integration in this checkout.

## Five-session GPT-6 factual-quality diagnostic

- Frozen dates: 09-16, 17, 18, 21, 22 at 23:30 Asia/Singapore; each raw/desk arm
  at most once/day, empty initial memory, no tools/retries/fallback.
- Approved payload: the frozen 25-stock research inputs to OpenAI Codex GPT-6;
  excludes actual holdings, costs and account data. Preserve its approval receipt.
- 09-16 collection complete. Raw failed during local provider initialization;
  desk was not started. No answer to score, no same-day retry, no model-quality result.
- Missing resolved-model/billed-cost receipts still fail closed. Preparatory
  rehearsals are historical diagnostics, not successful economic treatment arms.
- As of the 09-17 pre-run inspection, one due output day is blocked and four
  slots are not yet due. The new window reader does not evaluate human/model quality.
- This is an external local task arrangement, not a production scheduler feature.
  Inspect the actual schedule/receipts before discussing a future execution state.

## Verification baseline

09-17 implementation baseline: `make verify` passed with **2,396 backend tests**,
**42 frontend tests**, mypy 376 files, Ruff, doc/release hygiene, build/ESLint and
desktop/mobile smoke (zero console/page errors). Fourteen environment skips:
5 need optional torch; 9 need local-only replay/watchlist assets. One existing
Starlette deprecation warning. The two Seatbelt tests passed unchanged under
system test permissions after nested-sandbox initialization was rejected.

The saved-window batch preserved 43 frozen files, 40 old live artifacts and the
exact frozen 20/20 audit (excluding path/generation time); its original single-day
readiness and memory functions stayed unchanged. This documentation-only refresh
uses that code baseline; document/archive/hash checks are separate from a new full
code verification. No real model trial or daily pipeline was rerun to edit docs.

## Resume

Continue with ROADMAP's first unblocked batch: new-date output/user evidence,
then data provenance and the separate maintenance gate, then provider receipts/
isolation before economic forward tests. Historical counts, incident narratives
and completed implementation instructions were archived on 09-17; see
[archive digest](docs/evidence/document_archive_digest.md) only when needed.
