# StockSage

An agent-ready personal A-share research and decision-support workspace. StockSage combines a local data foundation, multi-source market/news feeds, technical and sentiment analysis, long-term research, portfolio risk control and auditable memory into one traceable research system. It supports research, reviews and risk alerts only; it does not predict prices, place orders or make the final investment decision for the user.

![Tests](https://img.shields.io/badge/tests-300%20pytest%20%2B%209%20node-brightgreen)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-22c55e)
![License](https://img.shields.io/badge/license-MIT-blue)
![Status](https://img.shields.io/badge/status-M2%20paper%20trading-yellow)

[Agent Usage Guide](#agent-usage-guide) · [Product Preview](#product-preview) · [Recommended Usage](#recommended-usage) · [Cautions](#cautions) · [More Docs](#more-docs)

[简体中文](README.md) | [English](README_EN.md)

---

## Overview

StockSage is a local-first personal A-share research system and an already agentized investment-research kernel. It organizes market data, news, fundamentals, QFII holdings, index data, positions, reviews and long-term memory in local SQLite, then uses technical indicators, LLM news sentiment, long-term research, portfolio risk control and auditable memory to support traceable decisions.

The project currently focuses on paper-trading validation and agent-ready usage. It is not an automated trading system, does not ask LLMs to directly predict prices, and will evolve from the current Web console toward a fuller client experience.

## Agent Usage Guide

StockSage Agent is designed for agent clients such as Codex, Claude Code, Claude Desktop, Cursor and other tools that can run local commands or connect to MCP tools. The most useful guide for users is not only how to run it, but what research and review tasks they can delegate to it.

| User goal | Task to delegate | Typical output |
|---|---|
| Single-stock research | Read one stock's signals, news, positions, long-term labels, historical reviews and project memory. | Research summary, evidence trail, risks and follow-up questions. |
| Topic research | Investigate an industry, theme, value chain or group of stocks. | Theme conclusion, related symbols, source audit and questions to verify. |
| Long-term research | Run the long-term analyst team across sector thesis, financial quality, prosperity indicators and QFII flow. | Long-term label, score, key findings and hold/avoid rationale. |
| Deep research | Coordinate industry researcher, company researcher, risk reviewer, source auditor and report writer roles. | Markdown research report, core conclusion, risk review and cited sources. |
| Memory management | Read or write long-term rules, risk preferences, research indexes, chat summaries and layered decision memory. | Memory summary, recall results and memory-write confirmations. |
| Reviews and paper trading | Analyze test performance, signal attribution, win rate, drawdown, exit reasons and risk-rule execution. | Review summary, performance attribution and rule-calibration suggestions. |
| Project health | Check data coverage, scheduler, API, config, tests and docs. | Health report, anomalies and next maintenance steps. |

Example prompts:

```text
Read project memory, then research whether 300308 is still worth following.
Run an AI computing value-chain topic research report covering 300308 and 300394.
Run the long-term analyst team and refresh long-term labels for my watchlist.
Summarize test-2 paper-trading performance and identify whether risk rules need adjustment.
Check current data coverage and scheduler health.
```

Common MCP tools:

| Tool | Purpose |
|---|---|
| `stock_sage_project_context` | Project runtime overview, config, positions, watchlist and memory summary. |
| `stock_sage_memory_snapshot` | `ai_memory`, layered memory, audit log and chat-summary status. |
| `stock_sage_stock_context` | Single-stock signals, news, positions, long-term labels and memory context. |
| `stock_sage_health` | Agent mode, database, dependency and permission health. |

## Product Preview

![StockSage System Architecture](docs/assets/architecture.svg)

## Recommended Usage

**Option A: hand the project to Codex / Claude Code**

1. Send the GitHub homepage or repository URL to Codex / Claude Code.
2. Ask the agent to read `README.md` and [AGENTS.md](AGENTS.md) before running anything.
3. Ask the agent to run `python3 -m backend.agent.cli health --pretty` first, so it sees database, memory, watchlist and position state.
4. Configure `.env`, for example `AI_PROVIDER=local_cli`, or set runtime keys such as `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`.
5. Let the agent install dependencies, initialize the database, start services or MCP, and approve privileged steps when prompted.
6. Use natural-language tasks for research, reviews, memory or project health checks.

**Option A2: terminal pi Agent**

```bash
git clone <repo-url> && cd stock-sage
make agent-setup
make agent
```

`make agent-setup` checks Python, installs StockSage agent dependencies, creates `.env`, initializes the database and prompts for pi installation if needed. V1 defaults to reusing one Anthropic/OpenAI key for both the outer pi chat model and the StockSage internal LLM runtime. If you choose `AI_PROVIDER=local_cli`, StockSage internal LLM workflows use the local Claude CLI.

Once inside pi, you can ask:

```text
Check StockSage health.
Research 300308 with memory, news, positions and long-term labels.
Summarize test-2 paper-trading performance.
Add 300394 to my watchlist.
```

Research and health checks read local context directly. Mutating actions such as watchlist, position, memory and config changes are dry-run first and require explicit confirmation before `backend.agent.cli action ... --confirm` executes them.

**Option B: start the Web console**

```bash
git clone <repo-url> && cd stock-sage
pip install ".[dev]"
cp .env.example .env
python3 backend/data/database.py
PYTHONPATH=. uvicorn backend.main:app --reload
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 for the Web console. API docs are available at http://localhost:8000/docs.

**Option C: start with Docker / compose**

```bash
cp .env.example .env
make docker-up
```

Docker starts the backend and frontend. Open http://localhost for the local UI and http://localhost:8000/docs for API docs.

**Option D: connect MCP tools**

```bash
pip install -e ".[agent]"
PYTHONPATH=. python3 -m backend.agent.mcp_server
# Or:
make agent-mcp
make agent-mcp-config
```

Connect this MCP server to Claude Desktop, Claude Code, Cursor or any MCP-capable client so the outer agent can call StockSage project context, memory snapshot, stock context and health tools.

## Cautions

- StockSage is for research and decision support, not investment advice, and it must not place real orders.
- LLMs do not directly predict prices; take-profit and stop-loss levels come from ATR formulas, portfolio constraints and risk rules.
- Local Codex / Claude Code sessions are trusted by default; remote agents are read-only by default.
- Remote writes require an API key, the remote write switch and an action allowlist.
- Before trading, research or reviews, read project context and project memory instead of relying only on the current chat.
- Long-term memory writes require explicit user intent; one-off questions and ordinary coding preferences should not enter trading-system memory.
- Daily postmarket batch signals keep multi-agent off by default to avoid linear runtime LLM token spend across 25+ stocks.
- `.env`, databases, model files, personal trading records and real keys should never enter Git.

## More Docs

| Document | Description |
|---|---|
| [PROJECT.md](PROJECT.md) | Project index, milestones and key file map |
| [STATUS.md](STATUS.md) | Current snapshot, signal weights, schedules, tests and startup commands |
| [CHANGELOG.md](CHANGELOG.md) | Completed milestones and major changes |
| [docs/ROADMAP.md](docs/ROADMAP.md) | In-progress work, roadmap and deferred items |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup, test expectations and contribution flow |
| [AGENTS.md](AGENTS.md) | Codex / Claude Code / MCP local agent instructions |

## Disclaimer

StockSage is a personal research and decision-support tool, not investment advice. It does not place trades automatically. LLMs do not predict prices. Take-profit and stop-loss levels are generated from ATR formulas and risk constraints. Users are responsible for all trading decisions and financial risks.
