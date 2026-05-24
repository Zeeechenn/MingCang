# StockSage

> An agent-ready personal A-share research and decision-support workspace

StockSage combines a local data foundation, multi-source market/news feeds, technical and sentiment analysis, long-term research, portfolio risk control and auditable memory into one traceable research system. It supports research, reviews and risk alerts only — **it does not predict prices, place orders or make the final investment decision for the user**.

[![CI](https://github.com/Zeeechenn/stock-sage/actions/workflows/test.yml/badge.svg)](https://github.com/Zeeechenn/stock-sage/actions/workflows/test.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-22c55e)
![License](https://img.shields.io/badge/license-MIT-blue)
![Status](https://img.shields.io/badge/status-agent%20research-yellow)

**Language**: [简体中文](README.md) · [English](README_EN.md)

**Navigation**: [Overview](#overview) · [Agent Usage Guide](#agent-usage-guide) · [Product Preview](#product-preview) · [Recommended Usage](#recommended-usage) · [API Key Configuration](#api-key-configuration) · [Recommended Configuration](#recommended-configuration) · [Cautions](#cautions) · [More Docs](#more-docs) · [Disclaimer](#disclaimer)

---

## Overview

StockSage is a **local-first** personal A-share research system and an already-agentized investment-research kernel. It organizes market data, news, fundamentals, QFII holdings, index data, positions, reviews and long-term memory in local SQLite, then uses technical indicators, LLM news sentiment, long-term research, portfolio risk control and auditable memory to support traceable decisions.

The project currently focuses on **agent-ready usage**, data quality and research-review workflows. It is not an automated trading system, does not ask LLMs to directly predict prices, and will evolve from the current Web console toward a fuller client experience.

## Agent Usage Guide

StockSage Agent is designed for agent clients such as Codex, Claude Code, Claude Desktop, Cursor and other tools that can run local commands or connect to MCP tools. The most useful guide for users is not only how to run it, but **what research and review tasks they can delegate to it**.

| User goal | Task to delegate | Typical output |
|---|---|---|
| **Single-stock research** | Read one stock's signals, news, positions, long-term labels, historical reviews and project memory. | Research summary, evidence trail, risks and follow-up questions. |
| **Topic research** | Investigate an industry, theme, value chain or group of stocks. | Theme conclusion, related symbols, source audit and questions to verify. |
| **Long-term research** | Run the long-term analyst team across sector thesis, financial quality, prosperity indicators and QFII flow. | Long-term label, score, key findings and hold/avoid rationale. |
| **Deep research** | Coordinate industry researcher, company researcher, risk reviewer, source auditor and report writer roles. | Markdown research report, core conclusion, risk review and cited sources. |
| **Memory management** | Read or write long-term rules, risk preferences, research indexes, chat summaries and layered decision memory. | Memory summary, recall results and memory-write confirmations. |
| **Reviews and validation** | Analyze signal performance, attribution, win rate, drawdown, exit reasons and risk-rule execution. | Review summary, performance attribution and rule-calibration suggestions. |
| **Project health** | Check data coverage, scheduler, API, config, tests and docs. | Health report, anomalies and next maintenance steps. |

**Example prompts**:

```text
Read project memory, then research whether 300308 is still worth following.
Run an AI computing value-chain topic research report covering 300308 and 300394.
Run the long-term analyst team and refresh long-term labels for my watchlist.
Check current data coverage and scheduler health.
```

**Common MCP tools**:

| Tool | Purpose |
|---|---|
| `stock_sage_project_context` | Project runtime overview, config, positions, watchlist and memory summary. |
| `stock_sage_memory_snapshot` | `ai_memory`, layered memory, audit log and chat-summary status. |
| `stock_sage_stock_context` | Single-stock signals, news, positions, long-term labels and memory context. |
| `stock_sage_health` | Agent mode, database, dependency and permission health. |

## Product Preview

![StockSage System Architecture](docs/assets/architecture.svg)

## Recommended Usage

### Option A: hand the project to Codex / Claude Code

1. Send the GitHub homepage or repository URL to Codex / Claude Code.
2. Ask the agent to read `README.md` and [AGENTS.md](AGENTS.md) before running anything.
3. Ask the agent to run `python3 -m backend.agent.cli health --pretty` first, so it sees database, memory, watchlist and position state.
4. Configure `.env` — for example `AI_PROVIDER=local_cli`, or set runtime keys such as `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`.
5. Let the agent install dependencies, initialize the database, start services or MCP, and approve privileged steps when prompted.
6. Use natural-language tasks for research, reviews, memory or project health checks.

### Option A2: terminal pi Agent

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
Add 300394 to my watchlist.
```

Research and health checks read local context directly. Mutating actions such as watchlist, position, memory and config changes are dry-run first and require explicit confirmation before `backend.agent.cli action ... --confirm` executes them.

### Option B: start the Web console (in development)

Open <http://localhost:5173> for the Web console; backend API docs are at <http://localhost:8000/docs>.

### Option C: start with Docker / compose

```bash
cp .env.example .env
make docker-up
```

Docker starts the backend and frontend. Open <http://localhost> for the local UI and <http://localhost:8000/docs> for API docs.

### Option D: connect MCP tools

```bash
pip install -e ".[agent]"
PYTHONPATH=. python3 -m backend.agent.mcp_server
# Or:
make agent-mcp
make agent-mcp-config
```

Connect this MCP server to Claude Desktop, Claude Code, Cursor or any MCP-capable client so the outer agent can call StockSage project context, memory snapshot, stock context and health tools.

## API Key Configuration

StockSage reads all external keys from `.env` in the project root. **Never commit `.env`, real keys, the database or personal trading records to Git.** The minimum local setup needs only `AI_PROVIDER=local_cli` with no cloud LLM key; enable news enrichment, push notifications and remote agent exposure on demand.

| Variable | Purpose | Required? | How to obtain / configure |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Powers StockSage internal LLM calls when `AI_PROVIDER=anthropic`. | Optional; required for the Anthropic runtime. | Create a key in the Anthropic Console and write it to `.env`. |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | Used by `AI_PROVIDER=openai` for OpenAI or OpenAI-compatible endpoints. | Optional; required for the OpenAI runtime. | Create a key on the provider's platform; for third-party compatible endpoints, also set `OPENAI_BASE_URL`. |
| `TAVILY_API_KEY` | Supplements real-time search headlines when the DB has insufficient news in the last 24 hours; also used by `backfill_coverage --use-tavily` and long-term A-teacher evidence search. | Optional fallback key. | Create an API key at [Tavily](https://app.tavily.com/) and write it to `.env`. |
| `ANSPIRE_API_KEY` | Fills strict event-style news gaps for the postmarket sentiment pipeline, filtering out market pages, profile pages and noisy sources. | Optional fallback key. | Register at [Anspire AI Search](https://aisearch.anspire.cn), create a key on the API Keys page and write it to `.env`. |
| `BARK_KEY` / `BARK_SERVER` | iOS Bark push notifications for postmarket signals, stop-loss alerts and circuit-breaker warnings. | Optional; pushes are silently skipped if unset. | Copy the device key from the Bark app; the default server is `https://api.day.app` — override `BARK_SERVER` if self-hosting. |
| `STOCKSAGE_AGENT_API_KEY` | Authenticates remote agent / MCP / HTTP writes when `STOCKSAGE_AGENT_MODE=remote`. | Not needed locally; required when exposing the agent remotely. | Generate a long random string, write it to `.env` and enable `STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED` plus the action allowlist on demand. |
| `TUSHARE_TOKEN` | Supplementary A-share daily-bar provider; once configured, joins the CN fallback chain to pull unadjusted OHLCV via Tushare `daily`. | Optional fallback key. | Get a token from [Tushare](https://tushare.pro/) and write it to `.env`; Tushare is skipped automatically if unset. |

**Recommended personal setup**:

```bash
cp .env.example .env
```

Then fill in only the keys you actually plan to enable. A common local fallback configuration:

```env
AI_PROVIDER=local_cli
TUSHARE_TOKEN=your_tushare_token_here
TAVILY_API_KEY=your_tavily_api_key_here
ANSPIRE_API_KEY=your_anspire_api_key_here
BARK_KEY=your_bark_device_key_here
BARK_SERVER=https://api.day.app
```

For remote deployment or exposing MCP / HTTP to other machines, also add:

```env
STOCKSAGE_AGENT_MODE=remote
STOCKSAGE_AGENT_API_KEY=replace_with_a_long_random_secret
STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED=false
STOCKSAGE_AGENT_REMOTE_WRITE_ACTIONS=
```

Once configured, verify with:

```bash
python3 -m backend.agent.cli health --pretty
```

## Recommended Configuration

Production currently defaults to the `new_framework` signal weighting. Based on existing backtests and validation results, the recommendation is to **temporarily exclude the quant layer from the composite score** and keep only technical and news-sentiment signals:

| Variable | Recommended value | Meaning |
|---|---:|---|
| `WEIGHT_QUANT` | `0.0` | Quant layers like Qlib / Kronos are still computed and logged but do not affect the composite score by default. |
| `WEIGHT_TECHNICAL` | `0.6` | Weight of technical signals. |
| `WEIGHT_SENTIMENT` | `0.4` | Weight of news-sentiment / event signals. |
| `NEW_FRAMEWORK_ENTRY_THRESHOLD` | `25.0` | Composite score must exceed this to become a small-position trial candidate. |

These are current project recommendations, **not hard-coded trading advice**. Users can adjust them on the Web config page or in `.env`, and validate their own parameter mix with backtests and reviews.

## Cautions

- StockSage is a research and decision-support tool — **not investment advice, and it never places real orders**.
- LLMs do not directly predict prices; take-profit and stop-loss levels come from ATR formulas, portfolio constraints and risk rules.
- Local Codex / Claude Code sessions are trusted by default; remote agents are read-only by default.
- Remote writes require **all of** an API key, the remote-write switch and an action allowlist.
- API keys are StockSage runtime credentials, not Codex / Claude Code chat credentials; they are consumed only when running the internal LLM, search, push or remote-agent pipelines.
- **Data sources and corresponding API keys**: A-share daily bars currently use the efinance / Eastmoney / AkShare fallback chain; setting `TUSHARE_TOKEN` appends Tushare `daily` as a supplementary source, with yfinance as the final fallback. A-share fundamentals, QFII and base news data primarily go through AkShare / Eastmoney and need no key. Real-time news enrichment uses `TAVILY_API_KEY`; strict event-style news gap-filling uses `ANSPIRE_API_KEY`; iOS push uses `BARK_KEY`; remote agent auth uses `STOCKSAGE_AGENT_API_KEY`.
- **Free / trial key quota notes** (public information as of 2026-05-23):
  - **Tavily** Researcher free tier offers 1,000 API credits / month; StockSage currently uses basic search, ~1 credit per request; development keys default to 100 RPM, production keys to 1,000 RPM, and production keys require a paid plan or PAYGO. See [Tavily Credits & Pricing](https://docs.tavily.com/documentation/api-credits) and [Tavily Rate Limits](https://docs.tavily.com/documentation/rate-limits).
  - **Anspire** public docs mention checking each resource package's total quota and usage in the console but give no fixed free-quota figure; treat the resource-package page on the [Anspire console](https://aisearch.anspire.cn) as authoritative. See [Anspire usage guide](https://open.anspire.cn/document/docs/openPlatform/).
  - **Tushare** is used only as a supplementary A-share daily-bar source in StockSage, calling the `daily` unadjusted endpoint; the official permission docs state `daily` requires 120+ points, with the basic tier allowing 500 calls/minute at up to 6,000 rows per call. Other Tushare data requires higher points or separate permissions. See [Tushare A-share daily bars](https://www.tushare.pro/document/2?doc_id=27) and [Tushare permissions](https://www.tushare.pro/document/2?doc_id=108).
  - **Bark**'s `api.day.app` is the push-service entry point; the project only sends notifications once `BARK_KEY` is set. Public tutorials note the key comes from the app's test URL / device key, with no guaranteed free quota or SLA. Self-host the Bark server for high-frequency pushes. See [Bark tutorial](https://github.com/Finb/Bark/blob/master/docs/en-us/tutorial.md).
- Before trading, research or reviews, read project context and project memory — **don't rely on the current chat window alone**.
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

StockSage is a personal research and decision-support tool, **not investment advice**. It does not place trades automatically. LLMs do not predict prices. Take-profit and stop-loss levels are generated from ATR formulas and risk constraints. Users are responsible for all trading decisions and financial risks.
