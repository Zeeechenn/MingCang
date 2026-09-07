# MingCang — Current Status Snapshot

> One Loop evidence was refreshed from an immutable snapshot on 2026-09-08
> through the 2026-09-07 close. Configuration rows below retain the 2026-09-02
> inspection unless explicitly dated; they are not a claim that a worker is running. Read `docs/ROADMAP.md` for sequencing and
> `CHANGELOG.md` only for history. This file does not replace the live ledger,
> SQLite state, or fresh artifacts.

MingCang is a local-first A/HK/US equity research and decision-support workspace.
It does not place real trades or provide financial advice. Package, API, and
frontend versions are aligned at `v0.8.2` for the decision-desk research and experiment-control patch release.

## Current Runtime Truth

| Area | Current state |
|---|---|
| production profile | `new_framework`; technical/sentiment `0.6/0.4`; `WEIGHT_QUANT=0.0`; entry threshold `25.0` |
| market rollout | CN unchanged; HK 2-name and US 3-name gray/shadow only, no alerts or orders |
| One Loop | `14/20` close-confirmed days through 2026-09-07, status `insufficient_days`; all 14 selected days are complete |
| One Loop quality | completeness `1.0`, 3 degraded days out of 14 (`0.214286`); 6 qualifying days still required |
| daily evidence | each selected day has one authoritative RunEnvelope, exact official signal batch, and committed `daily_panel.v1` artifact |
| panel output | candidate card has one fresh producing day; `event_risk`, `watchtower`, and `daily_delta` product/producer gaps remain open |
| price basis | mixed provider/adjustment history remains a blocker for trustworthy return attribution; no production price repair was executed |
| memory decision routing | fail-closed/shadow-only; `MEMORY_DECISION_CONTEXT_ENABLED=false` |
| M68 direction | shadow/test2 comparison only; not production direction authority |
| production safety | signals, positions, weights, stops, scheduler, API contracts, and production database were unchanged by the P0 batch |

The 14 accepted dates are 2026-08-19, 20, 21, 24, 25, 26, 27, 28, 31,
2026-09-01, 02, 03, 04, and 07. The start date is intentionally non-rolling: an
incomplete accepted day does not age out of the set.

## Active P0 Handoff

`docs/ROADMAP.md` is the authority for scope and next steps. The merged code is
deliberately narrower than the full development plan:

| Work | Integrated capability | Still open |
|---|---|---|
| P0-G | complete: one canonical start date; operator CLIs reject ad-hoc overrides; output directly lists compared and complete close dates | a future date change requires a reviewed code migration; no current implementation work remains |
| P0-B1 | immutable rebase dry-run plus an opt-in strict write guard that rejects mixed/missing provenance and overlap drift in temporary tests | strict mode remains disabled for routine One Loop callers; explain the 601899 ATR anomaly and separately approve any activation/B2 repair |
| P0-R | `manual_only` NAV v2 adds explicit halts, volume-capped partial fills, split/dividend events and deterministic control/execution/input/replay IDs | snapshot adapter still lacks an authoritative corporate-action ledger; candidate ID belongs to P2; clean price-basis rerun remains blocked |
| P0-A | G1 category decision is recorded; a disabled preview exists only in external review history | not merged: stable/shadow product contract, three missing-card producers, human-readable empty states, real workflow regression, and post-20/20 activation gate |
| P0-B2 | none | production/history repair requires a separate owner-approved impact list, full-history source coverage, backup, rollback and maintenance window |

Latest read-only diagnostics from the frozen 2026-09-02 snapshot:

- P0-G now prints the same 11 compared and complete dates directly; after removing
  the two additive date-list fields plus generation path/time, output is identical
  to the pre-change audit;
- the P0-B1 `000568` dry-run found 6 disagreements in 14 fetched rows and did not
  cover 2,487 of 2,501 stored rows, so execute correctly refused to proceed;
- P0-R v2 returned `blocked_price_basis` with 19 affected signal symbols and
  `promotion_eligible=false`; its frozen control/replay IDs are recorded and the
  snapshot SHA-256 stayed unchanged. Its diagnostic NAV is not return evidence.

## Decision-Desk Development — 2026-09-08

The approved direction is a human-controlled decision desk. Candidate development
uses explicit inputs and separate evidence; it does not activate a new daily
strategy. The sole active plan remains `docs/ROADMAP.md`, with implementation
instructions in `docs_public/DEVELOPER_GUIDE.md`.

Implemented research-only entries now include strict financial/label/context
reads, account-aware decision drafts, a non-persistent copilot preview, experiment
record validation, injected-provider observation recording, and an offline frozen
budget session with durable pre-call reservations and restart inspection. Default consumers
remain unchanged. No real model treatment arm was started; these are preparatory
capabilities, not evidence of improved investment returns. The session freezes only
a small budget/input plan, not the complete research protocol. Failed or interrupted
attempts retain reservations; a known overrun in either arm blocks new calls.
Real-provider timeouts, process isolation, billing caps, and treatment launch remain open.

The fresh immutable snapshot shows 20 symbols blocked by price-source or
adjustment provenance in P0-R; the corporate-action ledger is still unavailable.
`blocked_price_basis` and `promotion_eligible=false` remain in force. No repair was
performed and the snapshot hash was unchanged by the replay.

The official 25-name pool plus the three holdings in the dated 2026-09-04 local
state yields 28 distinct symbols. All latest financial rows remain 2026-Q1.
Publication dates exist, but this does not prove current coverage, intraday
visibility, or historical revision correctness. Backfill must first specify
source coverage, publication/revision provenance, changed rows, and rollback;
strict reads alone cannot manufacture newer data.

## Open Gates

1. Continue the existing daily One Loop unchanged until 20 qualifying days are
   present; do not reinterpret this engineering gate as a return gate.
2. Keep the P0-B1 strict write guard disabled while the current continuity window
   runs. Investigate 601899 and prepare P0-B2 only as an impact/rollback proposal;
   do not modify production prices without separate approval.
3. At 20/20, freeze the old `daily_panel.v1` baseline, then decide whether P0-A
   may be implemented/merged. A new output-quality window starts after activation;
   the old 20 days do not prove the new contract.
4. Read-only P0-R diagnostics may run on snapshots now; promote return evidence only after price-basis blockers are zero. P2/P3/P4 cannot use its
   current NAV result for promotion.
5. Freeze the P2 experiment specification before any real treatment decision. Select P3
   from measured loss attribution; P4 is a one-variable, frozen-control forward
   comparison with the same execution and cost model on both arms.

## Verification

The canonical code-quality gate is `make verify`. The isolated v0.8.2 release
candidate passed the full gate on 2026-09-08: Ruff, release hygiene (785 tracked
files), documentation authority, mypy (370 source files), 2,228 backend tests
(14 skipped), 37 frontend tests, TypeScript/production build, ESLint, and
desktop/mobile browser smoke with no console or page errors. Release version
consistency and the Python lockfile check also passed. One existing Starlette
deprecation warning remains non-blocking.

The 42 new session tests cover actual subprocess exit/restart, concurrent budget
reservation, cross-arm overrun, record corruption, frozen experiment identity,
and cutoff timezone boundaries. The new module has no existing production
consumer and is available only through explicit offline Python calls. The release
version change updates package/API metadata; it does not activate a new daily path.

In the earlier batch, the same immutable DB produced byte-identical default context/render/factor
outputs across 1,128 symbol/date pairs. Existing copilot function definitions
were unchanged. This session batch rechecked the full One Loop audit: it was
identical except `generated_at`;
AGENTS/CLAUDE instructions, production DB and 293 paper/live artifacts were
unchanged. This is code compatibility evidence, not a real-model equivalence
experiment or return certification. Historical release checks remain in Git.

Runtime acceptance must also rerun the immutable continuity audit:

```bash
python3 scripts/sqlite_consistent_snapshot.py --source <live.db> --destination /private/tmp/mingcang.snapshot.db
python3 scripts/audit_one_loop_continuity.py --db /private/tmp/mingcang.snapshot.db --repo-root .
```

## Runtime Truth Order

For trading, testing, review, or research decisions, prefer:

1. a fresh immutable snapshot of the current SQLite database;
2. authoritative `job_runs`/RunEnvelope and exact signal batch identity;
3. committed local artifacts and structured replay JSON;
4. `STATUS.md`, then the active roadmap;
5. `CHANGELOG.md` and external archives only for dated history.

## Agent Boundary

Local agents may inspect data, run checks, and make requested code/documentation
changes. They must not place broker orders, silently alter trading/risk policy,
write production data without the relevant approval gate, delete important local
data, or push/publish/release without explicit user authorization.
