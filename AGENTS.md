# MingCang Agent Instructions

## Project Identity

MingCang is a personal A-share research and decision-support system. It is
allowed to assist with research, tests, local validation analysis, configuration
review, and code changes. It must not place real trades or present output as
financial advice.

When a user refers to this project by an informal alias (for example
`项目s`, `项目S`, `project s`, or `Project s`), treat that as this
repository root.

## Local-First Agent Mode

Local Codex and Claude Code sessions are trusted development sessions. In local
mode, agents may directly:

- read and write project files as requested;
- inspect SQLite data and project memory;
- run tests, local validation checks, data coverage snapshots, and verification
  commands;
- call the paid data or LLM APIs already configured in the local `.env` when the
  requested MingCang workflow needs them;
- trigger project research, reviews, backfills, and local validation analysis.

Do not add extra confirmation gates for normal local development or validation
workflows.

Hard local boundaries:

- do not execute real broker orders or automatic trading;
- do not delete important local data, reset the git tree, publish, push, deploy,
  or release unless the user explicitly asks;
- do not commit secrets, local databases, model files, or personal trading
  records.

## Remote Agent Mode

Remote exposure is opt-in only. Use remote mode only when the environment
explicitly sets `MINGCANG_AGENT_MODE=remote`.

Remote mode must require `MINGCANG_AGENT_API_KEY` at the hosting/API layer.
Remote tools are read-only by default. Mutating remote tools require an explicit
allowlist and `MINGCANG_AGENT_REMOTE_WRITE_ENABLED=true`.
HTTP writes accept `X-MingCang-Agent-API-Key` or `Authorization: Bearer ...`;
when `MINGCANG_AGENT_REMOTE_WRITE_ACTIONS` is non-empty, the action name must
also be listed, for example `watchlist.add,memory.write,config.update`.

For the bundled stdio MCP bridge, remote-mode tool calls must pass the same key
as the optional `api_key` argument, for example
`mingcang_health(api_key="...")`. Local mode does not require this argument.
If a future HTTP/SSE transport validates the `Authorization` header before
forwarding requests, keep that gateway check equivalent to
`backend.agent.security.require_agent_access()`.

Keep real keys out of Git. `.env.example` may contain placeholders only.

## LLM/API Boundary

Codex and Claude Code use their own model access for development assistance.
That does not consume MingCang `.env` LLM keys.

MingCang `.env` keys such as `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`TAVILY_API_KEY`, and `ANSPIRE_API_KEY` are project runtime keys. They are used
only when running MingCang workflows that call the internal LLM, search, or data
provider chains.

For local agent development, cloud LLM keys are optional. To let MingCang's
internal LLM workflows run through local Claude Code CLI instead, set
`AI_PROVIDER=local_cli` and ensure `claude -p` works in the shell. Only
`AI_PROVIDER=anthropic` or `AI_PROVIDER=openai` requires and consumes the
matching cloud API key.

## Fresh Session Routing

Keep fresh-session context light. This file is the only default always-read
project instruction surface; load other project documents only when the task
needs them:

| Task | Read |
|---|---|
| current status, next step, testing, trading, milestone work | `STATUS.md` |
| architecture, repository navigation, ownership boundaries | `PROJECT.md` |
| onboarding, install, public copy, GitHub-facing docs | `README.md` |
| planning, continuation, governance sequencing, "what next" | `docs/ROADMAP.md` (the single active One Loop plan) |
| release notes, version history, historical verification | `CHANGELOG.md` only when explicitly relevant |

Do not preload `CHANGELOG.md`, `README_EN.md`, `docs/dev/*`, research reports,
or historical experiment notes for routine coding, triage, or "what next"
work. Follow links into those files only when the user asks for that history,
when a current doc points to a specific older claim, or when preparing a
release/audit answer.

For MingCang trading, testing, review, or research decisions, prefer
project-owned runtime truth over assistant-only chat memory:

1. current SQLite state: positions, watchlist, signals, labels, reviews
2. validated `stock_memory_items` outcomes/lessons and the compact calibration
   returned by `memory-context`
3. `ai_memory` rows for rules, preferences, research indexes, and risk notes
4. `decision_memory_layered`; legacy `~/.mingcang/memory/*.md` is fallback/cold
   history only
5. recent `audit_log_fts` entries

Do not inject raw daily judgment rows when validated outcome calibration exists.
Treat `watching`/`pending` memory as a question to re-check, not as current fact;
memory never directly changes official weights, stops, positions, or orders.

## Single-Stock Research Output

When Codex, Claude Code, pi, Cursor or another local agent runs single-stock
research, include the research copilot shadow conclusion in the answer whenever
available. This applies to terminal or agent-driven research even when the Web
copilot card is not being used.

For one-stock research, first load the stock context with:

```bash
python3 -m backend.agent.cli stock-context <symbol> --pretty
```

If the context contains `copilot`, report both tracks:

- official rule conclusion;
- copilot stance and summary;
- shadow position;
- risks and validation questions;
- whether it is marked as a reverse-risk shadow suggestion.

If no copilot record exists, say that the stock currently has no copilot shadow
opinion. Do not invent a shadow conclusion from the main signal, and do not let
the copilot modify official signals, stop loss, take profit, or real positions.

## Repository Structure And Incremental Migration

`PROJECT.md` is the canonical repository map. New internal imports must use the
canonical paths recorded there, even while older public commands and import
paths remain available for compatibility.

- Keep production logic in its owning domain (`data`, `analysis`, `backtest`,
  `evidence`, `research`, `memory`, `decision`, `portfolio`, or `workflows`).
- Treat `backend.tools` as a downstream CLI, maintenance, evaluation, or
  compatibility layer. Do not add new core or workflow dependencies on tool
  implementations. Existing workflow exceptions are migration debt and may
  only shrink.
- Keep API routes and scheduler jobs dependent on stable domain or
  `backend.workflows` facades. Do not call tool-private helpers from those
  surfaces.
- In frontend production code, import API and live-runtime capabilities from
  `frontend/src/services/`. Root `src/api.ts` and `src/live.ts` are compatibility
  exports, not new-code entry points.
- Migrate incrementally when touching an affected capability: move the smallest
  coherent implementation, update its internal consumers and related tests,
  then retain the old entry as a compatibility adapter. Do not perform unrelated
  mass moves or mix behavior changes into a structural batch.
- Move tests with the capability being migrated. Keep explicit compatibility
  tests for legacy public imports or commands; do not reduce coverage merely to
  make a move pass.
- Preserve legacy public CLI/import paths for at least one release cycle. Remove
  one only after internal consumers are zero, `PROJECT.md` and the tool registry
  are updated, the removal is documented in `CHANGELOG.md`, and the release
  explicitly approves the compatibility break.
- For each migration batch, update `PROJECT.md`, `STATUS.md`, `docs/ROADMAP.md`,
  and `CHANGELOG.md` only where their owned truth changes. Run focused tests,
  architecture-boundary tests, and `make verify` before committing.

The operator commands in `Daily Routing` intentionally keep their compatible
`backend.tools.*` CLI paths. That does not authorize production modules to use
those paths as implementation dependencies.

## One Loop Project Governance

`docs/ROADMAP.md` is the only active project-level plan. The former M-number
roadmap is frozen history: old identifiers may remain in compatibility paths,
schemas, tests, Git history, and `CHANGELOG.md`, but do not create new
M-numbered modules, files, workstreams, or product concepts.

Use the lifecycle vocabulary in the roadmap exactly: `proposed`,
`experimental`, `shadow`, `stable`, `dormant`, `rejected`, or `archived`.
Code existence is not evidence that a capability is active. Before calling a
capability stable or in use, verify its owner, runtime consumer, entrypoint,
job/run ledger, fresh output, evidence status, and rollback path.

Keep implementation work bounded:

- work from the earliest unblocked One Loop stage and satisfy its exit gate
  before advancing;
- at most two implementation batches may be in progress at once;
- do not combine structural migration with trading, provider, scheduler, DB,
  API, memory-routing, or risk-policy behavior changes;
- each batch must identify owner domain, invariants, tests, runtime evidence,
  and rollback before editing;
- one new top-level capability should normally replace, merge, or retire one
  existing capability.

### External Capability Admission

Before adapting an external repository, paper, skill, agent, model, or strategy,
record all of the following in the active roadmap proposal:

1. the existing MingCang problem it solves and the current baseline;
2. overlapping MingCang capabilities and why reuse is insufficient;
3. whether the adaptation is an idea, interface, algorithm, or code import;
4. owner domain, canonical entrypoint, and the single formal consumer;
5. input/output/failure/degradation contracts and affected safety surfaces;
6. experimental or shadow isolation, success metric, minimum sample, and expiry;
7. stop, rollback, deletion, and replacement/merge plan;
8. contract tests, runtime metrics, provenance, and required user decision gate.

Without an owner, consumer, metric, expiry, rollback, and replacement target,
the capability must remain outside production code. Prefer absorbing a useful
design into an existing domain over importing a parallel framework.

## Agent Runtime Checklist

For local agent work, start with the smallest command that matches the task:

- health / setup check: `python3 -m backend.agent.cli health --pretty`
- database bootstrap: `python3 backend/data/database.py`
- project context for one-stock work:
  `python3 -m backend.agent.cli project-context --symbol <symbol> --pretty`
- one-stock context:
  `python3 -m backend.agent.cli stock-context <symbol> --pretty`
- memory-sensitive work:
  `python3 -m backend.agent.cli memory-snapshot --pretty`
- local mutation preview:
  `python3 -m backend.agent.cli action <name> --payload-json '<json>' --pretty`
- confirmed local mutation: add `--confirm` only after explicit user approval

Native Pi, installer, and MCP setup details live in `README.md`. Keep this file
focused on agent rules and task routing.

## Trading And Risk Constraints

- Do not predict prices as certainty.
- Do not encourage "strong buy" behavior.
- Mention rule/profile version for trading or validation decisions.
- Respect configured position limits. Defaults trend toward 15% per stock, 30%
  per sector, and 80% total equity exposure.
- Position write paths are locked to positive quantities/costs/prices and reject
  duplicate close attempts from M22 onward.
- If long-term labels are missing, avoid stronger language than buy/watch-level
  suggestions.
- Stop loss / take profit are ATR-derived project rules, not LLM predictions.

## Memory Write Policy

Write to project memory when the user explicitly says to remember a MingCang
rule, risk preference, holding/test state, or durable research fact.

Do not write one-off questions, transient discussion, or normal coding
preferences into MingCang memory. Those belong in the local assistant context,
not the trading system.

## Documentation Workflow

Do not create generic planning files in this repository, including
`task_plan.md`, `progress.md`, `findings.md`, `review.md`, `notes.md`, or
`todo.md`.

Use existing durable docs:

- `AGENTS.md` for agent rules, safety, routing, and project governance.
- `PROJECT.md` for architecture, navigation, domain ownership, and canonical
  versus compatibility paths.
- `STATUS.md` for the current operational snapshot and runtime truth only.
- `docs/ROADMAP.md` for the single active One Loop plan, ordering, gates, and
  current blockers.
- `CHANGELOG.md` for completed history, release notes, and historical
  verification only.
- `docs_public/` for the public documentation site; one topic must have one
  authoritative source.
- `docs/ARCHITECTURE.md` and `docs/WHY_NOT_AI_STOCK_PICKER.md` are one-release
  compatibility stubs only; update public-facing links to `docs_public/`.
- `docs/data-sources/` and `docs/evidence/` are live internal contracts and
  reproducibility evidence, not public-site authority.
- `docs/dev/` only for living maintainer contracts that cannot yet be expressed
  in code/tests. Closed plans and experiment narratives belong in the external
  governance archive after their still-binding invariants are extracted.

Local research reports, review outputs, generated reports, logs, and planning
archives must live outside the MingCang repository directory, not merely outside
Git tracking. Do not maintain duplicate `docs/` and `docs_public/` authority for
the same topic. A compatibility stub may exist for one bounded release cycle.
Run `make doc-check` when changing documentation navigation, README docs
indexes, `docs_public/`, or `docs/dev/` authority.

## Common Commands

```bash
PYTHONPATH=. pytest -q
PYTHONPATH=. python3 -m backend.tools.coverage_snapshot
PYTHONPATH=. python3 -m backend.agent.cli health --pretty
PYTHONPATH=. uvicorn backend.main:app --reload
cd frontend && npm run dev
```

## Daily Routing

- 盘前/盘中/盘后 daily: `python3 -m backend.tools.m63_daily --mode premarket|intraday|postmarket`
- 周末 weekly: `python3 -m backend.tools.m63_weekly --no-llm`
- 研究 <目标> on-demand: `python3 -m backend.tools.m63_research --target <目标>`
- 喂观点: `python3 -m backend.tools.m63_opinion --text '<观点内容>' --source manual`
- 看 vs 研：只想读某只股票的现有上下文（零成本）用 `backend.agent.cli stock-context`；
  要产出新研究结论（消耗 LLM、登记研究队列）用 `m63_research`。深研模块直调
  （`backend.research.deep_research`）属高级用法，绕过 m63 路由与队列登记，日常勿用。
- 数据任务先查 `docs/data-sources/` 手册。
