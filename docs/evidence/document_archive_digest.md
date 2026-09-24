# AI document archive digest

> Updated 2026-09-24. Provenance and retrieval metadata only, not another active plan.
> Shared rules: `AGENTS.md`; runtime evidence: `STATUS.md`; next steps: `docs/ROADMAP.md`.

## Archive identity and recovery

- Archive ID: `mingcang-release-20260924-ai-docs-originals`.
- File: `ai-docs-archive.zip` (outside the repository; its machine-local path is recorded
  in the private `LEADER.md` handoff, not as a repository-relative path).
- ZIP SHA-256: `e764891dd8b1af49d988ccd6b650d82236e0fb9398a59fda6f1fcebfa0e5e311`.
- Captured before compression on 2026-09-24. The ZIP contains complete originals of six
  files under `originals/`, plus `manifest.json` with each original's path, SHA-256,
  byte count and line count. The six originals total 1,149 lines / 94,220 bytes.
- Every member was extracted to a fresh temporary directory; per-file SHA-256 and bytes
  matched the archived manifest and the source files captured before editing.
- Restore a selected original to a separate directory for comparison. Do not overwrite
  current documents or treat old wording as renewed authorization. The archive contains
  documentation only; no DB, runtime ledger, secrets, code or session transcript.

## Disposition

| Original surface | Current disposition and surviving authority |
|---|---|
| `AGENTS.md` | Rules remain canonical. The archived original predates the later governance pass, which adds task-scoped contract routing and retains task-only loading |
| `STATUS.md` | Current runtime truth, 09-23 result, source/quota/experiment receipts and unresolved gates; detailed experiment rules route to scoped contracts |
| `PROJECT.md` | Architecture/ownership map retained; iFinD paths now point to actual source adapters and the handbook |
| `docs/ROADMAP.md` | Sole active queue. One Loop, data, economic, user-value and P2 boundaries remain; scoped contracts hold detailed acceptance. External-method proposals preserve owner/consumer/expiry without changing queue order |
| `docs/data-sources/ifind.md` | Replaced stale fixed tool-count/account claims with current code-path map, dated historic observations, 09-23 pricing-page snapshot and 09-24 quota-exhaustion receipt. Existing parse errors/failures remain in denominators |
| `docs/evidence/document_archive_digest.md` | Records the earlier ZIP identity and this later governance pass. The ZIP itself was not regenerated for this pass |

The 2026-09-17 archive is a separate historical archive of 16 AI handoff/implementation
originals: Archive ID `mingcang-ai-docs-20260917`, file
`mingcang-ai-docs-20260917-originals.zip`, SHA-256
`5aba5719e7e6ace96ae382b463e9a59112c921c2c591b7da38aaf8e2628792c0`; its machine-local
location is recorded in the private `LEADER.md` handoff. The 09-24 ZIP is a reversible
receipt for the earlier six-file compression only. Private local `CLAUDE.md`, `LEADER*.md` and
`.claude/RESUME.md` are handled by a separate private archive and are not part of this
public-repository ZIP.

## Later isolated governance pass

The documentation-governance implementation used a separate workspace copy with
an immutable sibling `baseline/` and `baseline-manifest.json`. It changed
`AGENTS.md`, `STATUS.md`, `docs/ROADMAP.md`, the task-scoped contracts under
`docs/dev/`, `docs/dev/README.md`, this digest, and the document-authority checker
and tests. These changes are not members of the ZIP identified above. No new ZIP
or checksum is claimed for this pass.

Runtime artifacts, frozen inputs and failed attempts remain untouched. The 09-22 formal
model session is still `missing`; its offline market check is not a backfill. The 09-23
pipeline is `PIPELINE_PARTIAL` because the One Loop basis-drift gate remains blocked.
Current iFinD account usage exhaustion is a source failure, not evidence of recovered
coverage. Current model/source/user/economic gates are in `STATUS.md`, the sole queue
in `ROADMAP.md`, and task-specific contracts linked there and from `AGENTS.md`.
