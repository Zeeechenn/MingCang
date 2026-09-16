# MingCang Pi Agent

Read `AGENTS.md` as the shared rule source; `STATUS.md` owns current evidence and
`docs/ROADMAP.md` owns work order. This is a local-first personal equity research
and decision-support shell, never real broker execution or financial advice.
Do not load historical handoffs/archives as current instructions.

For trading/research/review questions, inspect the project first:

```bash
python3 -m backend.agent.cli health --pretty
python3 -m backend.agent.cli project-context --pretty
python3 -m backend.agent.cli stock-context <symbol> --pretty
python3 -m backend.agent.cli memory-snapshot --pretty
python3 -m backend.agent.cli actions --pretty
```

Use only the commands relevant to the task. Project-owned context/memory takes
precedence over conversation memory. A one-stock answer includes the available
copilot shadow track; absent data stays absent, official and shadow views stay distinct.

Daily/weekly/research routing follows AGENTS. An owner request to run daily tests
uses local LEADER + `bash scripts/run_daily_tests.sh`, not a hand-built pipeline.
The daily-test postmarket step is `--no-llm`; other research can consume model budget.
A zero-LLM shadow `not_applicable` is not “no risk.” Do not rerun a successful day
or a failed date in the separately frozen GPT-6 diagnostic.

Use the project CLI or `.pi/extensions/mingcang.ts` for health, state, watchlists,
positions and memory. Verification uses `make test`, `make verify`,
`make coverage-snapshot`; read-only work is allowed in local mode. Discover actions
and preview before mutation; add `--confirm` only after explicit action approval:

```bash
python3 -m backend.agent.cli action <name> --payload-json '<json>' --pretty
python3 -m backend.agent.cli action <name> --payload-json '<json>' --confirm --pretty
```

Python project commands read `.env`; do not assume it was exported into Pi.
Keep keys, databases, model files and personal trading records out of Git.
Respect ATR and configured portfolio limits; no certain price forecasts or
strong-buy behavior. Surface protective_action, stop_flags, quality_flags and
trigger_quality when relevant. LLM discretion is reference-only and gated by
`M59_DISCRETION_ENABLED`; reporting must keep the existing language guard.
The research queue uses `~/.mingcang/m63_research_queue.json`; new research follows
m63 routing, not direct deep-research calls assembled outside the queue.
