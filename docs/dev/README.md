# docs/dev live contracts

`docs/dev/` is no longer a general planning archive. It keeps live referenced
contracts plus narrowly scoped acceptance contracts routed from `AGENTS.md` or
`docs/ROADMAP.md`. A task-scoped contract is read only for its named work; it is
not routine startup context or another queue.

Closed plans, experiment narratives, generated research reports, and review
outputs belong in the external One Loop governance archive, which lives on the
owner's machine outside this repository. Per `docs/ROADMAP.md` §1 its absolute
path is deliberately not recorded here; use `docs/evidence/document_archive_digest.md` for archive identity/hash, then the local LEADER handoff for its machine-specific location.

Current allowlist:

| File | Surface | Why it remains live |
|---|---|---|
| `2026-07-07-live-track-design.md` | live contract | Referenced by `live_trading/LIVE.md` as the live-track design contract. |
| `M54_OOS_PREREGISTER.md` | research/evidence contract | Referenced by runtime config and OOS tooling as preregistered validation rules. |
| `M55_SERENITY_CONVERGENCE_PLAN.md` | research gate contract | Referenced by serenity chokepoint code/tests while the gate remains present. |
| `m50_research_report_gate_spec.md` | report-gate contract | Referenced by `backend/research/research_report_gate.py`. |
| `NEWS_EVENT_RISK_CONTRACT.md` | task-scoped acceptance | M54/M68 event-risk facts and direction research; separate gates, no production authorization. |
| `MODEL_COMPARISON_CONTRACT.md` | task-scoped acceptance | Fixed-scope model experiments and economic gates; does not renew authorization. |
| `EXTERNAL_METHODS_CONTRACT.md` | task-scoped acceptance | Reviewed external-method microbatches and their owner/consumer/expiry gates. |
| `P0_DATA_FOUNDATION_CONTRACT.md` | task-scoped acceptance | P0 price, data and NAV contracts; does not authorize writes. |

The former `DATA_AUDIT_EXTERNAL.md` and `DATA_AUDIT_IFIND.md` narratives were
archived outside the repository on 2026-09-03. Their binding conclusions live
in `docs/data-sources/`; provenance and hashes live in
`docs/evidence/data_source_audit_digest.md`.

When one of these contracts becomes fully encoded in code/tests or is retired,
move it to the external archive first, update all references, and keep
`make doc-check` green.

2026-09-17 refresh: M50/M55 old implementation queues were archived after retaining
referenced semantic sections. M54 preregistration remains intact as a historical,
code-linked threshold/result record; it does not authorize a new run. The local
live-track contract remains intact.
