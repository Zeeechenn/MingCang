# StockSage

An agent-ready personal A-share research and decision-support workspace. StockSage combines a local data foundation, multi-source market/news feeds, technical and sentiment analysis, long-term research, portfolio risk control and auditable memory into one traceable research system. It supports research, reviews and risk alerts only; it does not predict prices, place orders or make the final investment decision for the user.

![Tests](https://img.shields.io/badge/tests-300%20pytest%20%2B%209%20node-brightgreen)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-22c55e)
![License](https://img.shields.io/badge/license-MIT-blue)
![Status](https://img.shields.io/badge/status-M2%20paper%20trading-yellow)

[Product Preview](#product-preview) · [Agent Usage Guide](#agent-usage-guide) · [Core Capabilities](#core-capabilities) · [Recommended Usage](#recommended-usage) · [Headless Usage](#headless-usage) · [Cautions](#cautions) · [More Docs](#more-docs)

[简体中文](README.md) | [English](README_EN.md)

---

## Overview

StockSage is a local-first personal A-share research system and an already agentized investment-research kernel. It stores market data, news, fundamentals, QFII holdings, index data, positions, reviews and long-term memory in local SQLite, then combines technical indicators, LLM news sentiment, a long-term analyst team, Research Director, Trader, Risk Manager and Portfolio Manager into auditable suggestions.

The project is intentionally not about asking an LLM to guess price moves. Its job is to keep data, evidence, risk constraints and historical memory in one workspace: sync data before market open, generate signals after close, check stop-loss risk during the session, refresh long-term labels weekly, and let the user explicitly trigger single-stock research, sector deep research, paper-trading statistics and project-memory retrieval.

The Agent-ready local/remote interface is now in place. Local agents such as Codex or Claude Code can read project context, inspect memory, run tests, produce reviews and call MCP tools. Remote agents are read-only by default and require explicit API-key auth, write enablement and an action allowlist. The product direction is to evolve from the current Web console into a fuller client experience, making daily research, alerts, reviews and agent collaboration feel natural in a personal workflow.

## Product Preview

![StockSage System Architecture](docs/assets/architecture.svg)

## Agent Usage Guide

StockSage Agent is a collaborative research assistant for personal A-share research. It is designed for agent clients such as Codex, Claude Code, Claude Desktop, Cursor and other tools that can run local commands or connect to MCP tools. It can read project data and memory, assist with single-stock research, topic research, long-term research, deep research, reviews and project maintenance. It is not an automated trading bot.

The recommended external-user flow is to send this GitHub page or repository URL to Codex / Claude Code and ask the agent to download, install, configure and run the project:

```text
Please read this project homepage and AGENTS.md, then download and run StockSage.
First explain which API keys I need to configure. Then initialize the database and start the backend/frontend or MCP tools.
Before running commands, list what you plan to execute. Ask for confirmation before writing files, installing dependencies, starting services or calling paid APIs.
```

## Core Capabilities

| Capability | Description |
|---|---|
| Single-stock research | Combine one stock's signals, news, positions, long-term labels, historical reviews and project memory. |
| Topic research | Generate structured reports for an industry, theme, value chain or group of stocks. |
| Long-term research | Run the long-term analyst team across sector thesis, financial quality, prosperity indicators and QFII flow. |
| Deep research | Coordinate industry researcher, company researcher, risk reviewer, source auditor and report writer roles. |
| Memory | Read and write long-term rules, risk preferences, research indexes, chat summaries, layered decision memory and audit logs. |
| Reviews and paper trading | Analyze test results, signal attribution, win rate, drawdown, exit reasons and risk-rule execution. |
| Project maintenance | Run tests, inspect data coverage, check scheduler / API / config health, update docs and diagnose runtime issues. |

Common MCP tools:

| Tool | Purpose |
|---|---|
| `stock_sage_project_context` | Project runtime overview, config, positions, watchlist and memory summary. |
| `stock_sage_memory_snapshot` | `ai_memory`, layered memory, audit log and chat-summary status. |
| `stock_sage_stock_context` | Single-stock signals, news, positions, long-term labels and memory context. |
| `stock_sage_health` | Agent mode, database, dependency and permission health. |

## Recommended Usage

**Option A: hand the project to Codex / Claude Code**

1. Send the GitHub homepage or repository URL to Codex / Claude Code.
2. Ask the agent to read `README.md` and [AGENTS.md](AGENTS.md) before running anything.
3. Configure `.env`, for example `AI_PROVIDER=local_cli`, or set runtime keys such as `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`.
4. Let the agent install dependencies, initialize the database, start services or MCP, and approve privileged steps when prompted.
5. Use natural-language tasks such as:

```text
Read project memory, then research whether 300308 is still worth following.
Run an AI computing value-chain topic research report covering 300308 and 300394.
Summarize test-2 paper-trading performance and identify whether risk rules need adjustment.
Check current data coverage and scheduler health.
```

**Option B: start locally by hand**

```bash
git clone <repo-url> && cd stock-sage
pip install ".[dev]"
cp .env.example .env
python3 backend/data/database.py
PYTHONPATH=. uvicorn backend.main:app --reload
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 for the Web console. API docs are available at http://localhost:8000/docs.

**Option C: start only the Agent MCP server**

```bash
pip install -e ".[agent]"
PYTHONPATH=. python3 -m backend.agent.mcp_server
```

## Headless Usage

If a user swaps in their own API keys but does not open the Web frontend, StockSage is still usable. The important distinction is that API keys are credentials for StockSage runtime calls to models, search or data providers; they do not create an interactive chat interface by themselves. Conversation, permission prompts and tool orchestration come from an outer agent client such as Codex or Claude Code.

| Entry | Best for |
|---|---|
| Codex / Claude Code + MCP | Closest natural-language experience: let the agent read the project, run commands, call tools and explain results. |
| FastAPI + curl / HTTP client | Scripted access to endpoints such as `/api/ai/chat` and `/api/research/deep/run`. |
| CLI scripts | Deterministic jobs such as deep research, coverage snapshots and paper-trading statistics. |

Examples:

```bash
PYTHONPATH=. python3 -m backend.research.deep_research \
  --topic "AI算力产业链" \
  --symbols 300308,300394

PYTHONPATH=. python3 -m backend.tools.coverage_snapshot
PYTHONPATH=. python3 -m paper_trading.stats
```

The project does not currently include a standalone `stocksage chat` terminal REPL. For Claude-Code-style terminal conversation, use Codex / Claude Code as the outer agent and let it connect to this project's MCP server or call project commands.

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
