# MingCang Agent Instructions

## Identity and authority

MingCang is a personal equity research and decision-support system. Informal
aliases `明仓`, `项目s`, `项目S`, `project s` and `Project s` refer to this repository.
Assist with research, reviews, tests and development; never place real broker
orders or present output as financial advice.

This is the shared, default instruction file. Claude imports it through
`CLAUDE.md`; local handoffs and Pi notes are task-specific routing, not separate
project plans. Read only the document needed:

| Task | Authority |
|---|---|
| current runtime, completed implementation, evidence gaps | `STATUS.md` |
| continuation, ordering, acceptance and next steps | `docs/ROADMAP.md` — sole active plan |
| architecture, ownership, canonical imports | `PROJECT.md` |
| M54/M68 event-risk or direction acceptance | `docs/dev/NEWS_EVENT_RISK_CONTRACT.md` |
| GPT-6/Claude experiment mechanics | `docs/dev/MODEL_COMPARISON_CONTRACT.md` |
| reviewed external-method microbatches | `docs/dev/EXTERNAL_METHODS_CONTRACT.md` |
| P0 price/data/NAV maintenance | `docs/dev/P0_DATA_FOUNDATION_CONTRACT.md` |
| implementation contracts and validation | `docs_public/DEVELOPER_GUIDE.md` |
| install or public onboarding | `README.md`, then `docs_public/` |
| “跑测试” / “run tests” | Real history: `make research-test`; code checks: `make research-check` |
| formal daily tests | local `LEADER.md` and `scripts/run_daily_tests.sh` |
| releases/history | `CHANGELOG.md`, only on demand |
| archived AI handoff/history | `docs/evidence/document_archive_digest.md`, only on demand |

Do not preload old reports, task-scoped `docs/dev/*` contracts, archives,
CHANGELOG or README_EN for routine coding. STATUS + ROADMAP contain the active
handoff; read a scoped contract only for its named task. Historical counts or
unchecked old plans are not current instructions. Consult external-quant evidence
only for that proposal.

## Local and remote permissions

Local Codex/Claude sessions are trusted development sessions: requested file
edits, SQLite/memory inspection, tests, validation, research, reviews and backfill
workflows may proceed in the authorized scope. Configured paid data/LLM APIs may
be used when the requested workflow needs them. Do not add confirmation gates
for ordinary authorized development or validation.

Preserve dirty worktrees. Do not reset, delete important data, commit secrets,
DBs, model files or personal trading records. Push, publish, deploy and release
require an explicit request. Historical maintenance and experiment activation
remain subject to the specific gates below; development is not real trading.

Remote mode is opt-in via `MINGCANG_AGENT_MODE=remote`; require
`MINGCANG_AGENT_API_KEY`. Remote tools default to read-only. Writes require the
explicit allowlist and `MINGCANG_AGENT_REMOTE_WRITE_ENABLED=true`; nonempty
`MINGCANG_AGENT_REMOTE_WRITE_ACTIONS` must include the exact action. HTTP accepts
`X-MingCang-Agent-API-Key` or `Authorization: Bearer ...`; stdio MCP passes
`api_key` (e.g. `mingcang_health(api_key="...")`). Local mode needs no key.
Any new HTTP/SSE gateway must match `backend.agent.security.require_agent_access()`.
Keep real keys out of Git; `.env.example` contains placeholders only.

Development-host model access is separate from MingCang runtime `.env` keys.
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `TAVILY_API_KEY`, `ANSPIRE_API_KEY` are used
by project workflows, not by ordinary editing. `AI_PROVIDER=local_cli` can use
local Claude (`claude -p`); `anthropic`/`openai` modes need the matching key.
Local CLI may still consume the user's subscription: inspect actual usage.
External experiments must retain approval for their exact data/model/window;
existing research-data approval does not include holdings/costs/account data.

## Runtime truth and memory

Prefer current SQLite positions/watchlist/signals/labels/reviews, then validated
`stock_memory_items` outcomes/lessons and `memory-context` calibration, then
`ai_memory` rules/preferences/indexes, `decision_memory_layered`, and relevant
`audit_log_fts`. Legacy `~/.mingcang/memory/*.md` is cold fallback only.
Do not inject raw judgments when validated outcome calibration exists.
`watching`/`pending` memories are questions to recheck, not facts; memory never
directly changes official weights, stops, positions or orders.

Write project memory only when explicitly asked to remember a durable project
rule, research fact, risk preference or holding/test state. One-off questions,
transient discussion and ordinary coding preferences do not belong there.

For one stock, start with `python3 -m backend.agent.cli stock-context <symbol> --pretty`.
When `copilot` exists, report the official rule conclusion AND shadow stance,
summary/position, risks, validation questions and any reverse-risk marker. When
absent, say no copilot opinion is available; never invent one or let it override
official signals, ATR stops/take profit or actual positions.
Mention rule/profile version in trading/validation conclusions; no certain price
predictions or strong-buy language. Respect configured limits (typical defaults:
15% per stock, 30% per sector, 80% equity), positive quantities/costs/prices and
no duplicate closes. Missing long-term labels do not justify stronger advice.

## Bounded development and governance

- Start from the earliest unblocked ROADMAP item. Before edits state owner,
  consumer, invariants, tests, runtime evidence and rollback; at most two batches.
- Keep structure-only migration separate from provider, scheduler, DB/API,
  trading/risk, replay and memory-routing behavior changes.
- Use `proposed`, `experimental`, `shadow`, `stable`, `dormant`, `rejected`,
  `archived`. Calling a capability stable/in use requires owner, consumer,
  entrypoint, job/run ledger, fresh output, evidence status and rollback.
- Old M numbers are historical/compatibility labels; create no new M-numbered
  modules, workstreams or product concepts. A new top-level capability normally
  replaces, merges or retires an existing one.
- Preserve One Loop behavior and frozen artifacts. The 20-day v1 gate is closed;
  new-date output quality, data and economic gates remain separate (STATUS).
  P0-A's 20/20 + freeze + renewed owner gate was met for the approved first batch;
  further activation follows ROADMAP. P0-B1 strict/warmup stays opt-in.
- P0-B2 always needs its own reviewed coverage/impact, backup, rollback,
  maintenance window and write approval. A drift clearance is not a price repair.
  Do not reset the canonical start date or regenerate an already complete day.
- External capabilities require, in ROADMAP: existing gap/baseline and overlap;
  idea/interface/algorithm/code scope; owner/canonical entry/one consumer;
  input/output/failure/degradation and safety contracts; experimental/shadow
  isolation; metric/sample/expiry; stop/rollback/deletion/replacement; tests,
  provenance/runtime evidence and owner gate. Missing these means no production.

## Structure and compatibility

`PROJECT.md` owns the canonical map. Domain logic stays in data/analysis/backtest/
evidence/research/memory/decision/portfolio/ops/jobs/workflows. `backend.tools`
is downstream CLI/maintenance/compatibility; core/workflows must not gain tool
implementation dependencies. API/scheduler consume stable domain/workflow facades.
Frontend API/live imports use `frontend/src/services/`, not root compatibility exports.

Migrate the smallest coherent capability with its consumers/tests; preserve public
adapters and explicit compatibility tests for at least one release cycle. Removal
requires zero internal consumers, PROJECT/registry updates, CHANGELOG and an
explicitly approved compatibility-breaking release. Operator `backend.tools.*`
commands do not authorize reverse implementation dependencies.
Update only the authority whose truth changes. Migration batches need focused
and architecture tests plus `make verify` before commit; meaningful UI changes
need browser-flow verification. No green tests alone prove fresh runtime or returns.

## Commands and document maintenance

- health: `python3 -m backend.agent.cli health --pretty`
- project context: `python3 -m backend.agent.cli project-context --symbol <symbol> --pretty`
- memory snapshot: `python3 -m backend.agent.cli memory-snapshot --pretty`
- DB bootstrap when requested: `python3 backend/data/database.py`
- action preview: `python3 -m backend.agent.cli action <name> --payload-json '<json>' --pretty`;
  add `--confirm` only after explicit action approval.
- daily: `python3 -m backend.tools.m63_daily --mode premarket|intraday|postmarket`;
  daily-test postmarket uses the existing `--no-llm` SOP.
- weekly: `python3 -m backend.tools.m63_weekly --no-llm`
- research: `python3 -m backend.tools.m63_research --target <symbol|theme>`
- opinion: `python3 -m backend.tools.m63_opinion --text '<opinion>' --source manual`

Reading stock-context is the zero-model-call path; new research consumes model
budget and registers the queue. Direct deep_research is advanced use, not daily
routing. Read `docs/data-sources/` before data work; installer/Pi details live in README.

Use consistent SQLite snapshots with `scripts/sqlite_consistent_snapshot.py`;
read snapshots with `mode=ro&immutable=1`, no WAL/SHM dependency, and compare hashes.
Keep scratch reports, reviews, logs, historical archives and generic plan/progress/
notes/todo files outside the repo. Tests write only isolated DB/cache/output.
`docs_public/` is the public authority; `docs/ARCHITECTURE.md` and
`docs/WHY_NOT_AI_STOCK_PICKER.md` are bounded compatibility stubs. `docs/dev/`
keeps only still-referenced contracts; archive completed narratives after extracting
surviving invariants. Local LEADER/archive stubs are navigation, not another plan.
Preserve released CHANGELOG history. Run `make doc-check` for documentation changes.
