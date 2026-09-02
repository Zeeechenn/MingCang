# MingCang — Current Status Snapshot

> Runtime evidence is current through the 2026-09-02 close; the P0 development
> handoff was integrated on 2026-09-03. Read `docs/ROADMAP.md` for sequencing and
> `CHANGELOG.md` only for history. This file does not replace the live ledger,
> SQLite state, or fresh artifacts.

MingCang is a local-first A/HK/US equity research and decision-support workspace.
It does not place real trades or provide financial advice. Package, API, and
frontend versions are aligned at the `v0.8.1` patch-release candidate.

## Current Runtime Truth

| Area | Current state |
|---|---|
| production profile | `new_framework`; technical/sentiment `0.6/0.4`; `WEIGHT_QUANT=0.0`; entry threshold `25.0` |
| market rollout | CN unchanged; HK 2-name and US 3-name gray/shadow only, no alerts or orders |
| One Loop | `11/20` close-confirmed days, status `insufficient_days`; all 11 selected days are complete |
| One Loop quality | completeness `1.0`, degradation `0.0`, no day-level audit blockers; 9 qualifying days still required |
| daily evidence | each selected day has one authoritative RunEnvelope, exact official signal batch, and committed `daily_panel.v1` artifact |
| panel output | candidate card has one fresh producing day; `event_risk`, `watchtower`, and `daily_delta` product/producer gaps remain open |
| price basis | mixed provider/adjustment history remains a blocker for trustworthy return attribution; no production price repair was executed |
| memory decision routing | fail-closed/shadow-only; `MEMORY_DECISION_CONTEXT_ENABLED=false` |
| M68 direction | shadow/test2 comparison only; not production direction authority |
| production safety | signals, positions, weights, stops, scheduler, API contracts, and production database were unchanged by the P0 batch |

The 11 accepted dates are 2026-08-19, 20, 21, 24, 25, 26, 27, 28, 31,
2026-09-01, and 2026-09-02. The start date is intentionally non-rolling: an
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

## Open Gates

1. Continue the existing daily One Loop unchanged until 20 qualifying days are
   present; do not reinterpret this engineering gate as a return gate.
2. Keep the P0-B1 strict write guard disabled while the current continuity window
   runs. Investigate 601899 and prepare P0-B2 only as an impact/rollback proposal;
   do not modify production prices without separate approval.
3. At 20/20, freeze the old `daily_panel.v1` baseline, then decide whether P0-A
   may be implemented/merged. A new output-quality window starts after activation;
   the old 20 days do not prove the new contract.
4. Rerun P0-R only after price-basis blockers are zero. P2/P3/P4 cannot use its
   current NAV result for promotion.
5. Build P2 Candidate Manifest before any external strategy candidate. Select P3
   from measured loss attribution; P4 is a one-variable, frozen-control forward
   comparison with the same execution and cost model on both arms.

## Verification

The canonical code-quality gate is `make verify`. The 2026-09-03 isolated P0
integration candidate passed Ruff, release hygiene, documentation authority,
mypy, 2,088 backend tests (14 skipped), 37 frontend tests, production build,
ESLint, and desktop/mobile browser smoke. Exact release-tree details are recorded
in the `v0.8.1` entry of `CHANGELOG.md`; older verification snapshots remain in
Git history and are intentionally not repeated here.

Runtime acceptance must also rerun the immutable continuity audit:

```bash
python3 scripts/sqlite_consistent_snapshot.py --source <live.db> --output /private/tmp/mingcang.snapshot.db
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
