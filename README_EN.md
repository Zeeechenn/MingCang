# StockSage

> 🎯 A local-first personal A-share research workspace · Agent-ready · Auditable & traceable

StockSage organizes market data, news, fundamentals, QFII flows, positions, reviews and long-term memory in a single local SQLite store, then layers technical indicators, LLM news sentiment, long-term research, portfolio risk control and auditable memory on top — to give individual investors **a traceable research workspace**.

It supports research, reviews and risk alerts only — **it does not predict prices, place orders, or make the final investment decision for the user**.

StockSage positions itself as **a research substrate for agents, not an agent itself** — it exposes context, memory and health checks as a tool set via MCP / CLI so outer agents like Codex, Claude Code, or Cursor can drive it directly. Research conclusions are anchored by an institutional-grade audit layer (DSR, PBO, Walk-Forward, Point-in-Time interception, IC significance, Kill Switch), and every decision leaves a traceable evidence trail through FinMem-style layered decision memory and full-text-search audit logs.

A complete multi-agent pipeline — Bull/Bear three-round debate + Research Director + Risk Manager + Portfolio Manager — is built in, enabled on demand and defaulting to single-agent for daily postmarket runs to control token spend. Local dev sessions are trusted by default; remote exposure requires an API key + write switch + action allowlist (three gates) and stays read-only by default.

[![CI](https://github.com/Zeeechenn/stock-sage/actions/workflows/test.yml/badge.svg)](https://github.com/Zeeechenn/stock-sage/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/Zeeechenn/stock-sage?logo=github&color=success)](https://github.com/Zeeechenn/stock-sage/releases)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-22c55e)
![Agent](https://img.shields.io/badge/agent--ready-Codex%20%7C%20Claude%20Code%20%7C%20Cursor-8957e5)
![License](https://img.shields.io/badge/license-MIT-blue)
![Status](https://img.shields.io/badge/status-agent%20research-yellow)

**Language**: [简体中文](README.md) · [English](README_EN.md)

**Contents**: [Current Release](#-current-release) · [Highlights](#-highlights) · [Quick Start](#-quick-start) · [Recommended Usage](#-recommended-usage) · [Agent Usage Guide](#-agent-usage-guide) · [Configuration](#-configuration) · [Architecture](#-architecture) · [Roadmap](#-roadmap) · [Cautions](#-cautions) · [More Docs](#-more-docs) · [Disclaimer](#-disclaimer)

---

## 📦 Current Release

**v0.2.2 (2026-06-03)** ships the M41 A/HK/US read-only data facade: a three-market seven-layer capability catalog, HK/US daily price bridge, explicit external-data probes, probe summaries, global-data API/CLI, canonical schema/PIT gates, price quality gates, and probe health ledger are now on the public line.

HK/US remain read-only research context: they do not generate official signals and do not enter postmarket batch, stop-loss checks, long-term constraints, position sizing, or composite_score. The M26 / M27 quant and Kronos evidence conclusion is unchanged, so production keeps `WEIGHT_QUANT=0.0` / `kronos_enabled=false`.

---

## ✨ Highlights

| | |
|---|---|
| 🗂 **Local-first** | Market data, news, fundamentals, QFII, positions, reviews and long-term memory all live in a local SQLite — offline-capable and auditable. |
| 🤖 **Agent-ready** | Natively works with Codex, Claude Code, Claude Desktop, and Cursor over both CLI and MCP. |
| 🔗 **Multi-source data** | Eastmoney / AkShare market-data fallback by default; optional efinance, Tushare qfq, yfinance and TickFlow; news supplements can use iFinD MCP and Tavily, while Anspire remains for explicit deep research / manual strict news fetches. |
| 🧩 **Layered signals** | Technical indicators + LLM news sentiment + long-term analyst team + portfolio risk — each layer independently reviewable. |
| 📒 **Auditable memory** | Project memory, layered decision memory and chat summaries each stored in their own bucket, every write audit-logged. |
| 🛡 **Risk-first** | Stop-loss / take-profit levels come from ATR formulas and portfolio constraints — LLMs never predict prices directly. |

> Current focus: **M29 forward evidence and pre-registered alpha hypotheses**, agent-ready usage, data quality and research-review workflows. Not an automated trading system. The Web console is still evolving.

---

## 🚀 Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/Zeeechenn/stock-sage/main/scripts/install.sh | sh
stocksage               # Enter the native Pi terminal workspace
```

Developers can also clone and run manually:

```bash
git clone <repo-url> && cd stock-sage
make agent-setup        # Check Python, install deps, create .env, init the DB
make agent              # Enter the native Pi shell and start asking in natural language
```

The default local setup uses `AI_PROVIDER=local_cli` (your logged-in Claude / Codex CLI) — **no cloud LLM key required**. If no local CLI is available, health checks report the runtime readiness reason directly.

If you prefer to use your own Anthropic / OpenAI or OpenAI-compatible key, copy and edit `.env` first:

```bash
cp .env.example .env
# Set AI_PROVIDER=anthropic + ANTHROPIC_API_KEY
# Or AI_PROVIDER=openai + OPENAI_API_KEY (and OPENAI_BASE_URL for compatible endpoints)
```

After configuration, run `stocksage configure && stocksage`, or enter the project
with `make agent-setup && make agent`; the Web console and MCP entry points are
listed in Recommended Usage below.

Verify things are healthy:

```bash
python3 -m backend.agent.cli health --pretty
```

Trading-rhythm quick entries (all are dry-run orchestration contracts and do not
run heavy jobs by default):

```bash
python3 -m backend.agent.cli premarket --pretty
python3 -m backend.agent.cli intraday --symbol 300308 --pretty
python3 -m backend.agent.cli postmarket --pretty
# The native launcher also supports: stocksage premarket / intraday / postmarket
```

M31 cache-layer SLA baseline (2026-06-02, local SQLite,
`backend.tools.m31_cache_benchmark --iterations 20`): L1 in-process lookup
p50≈0.0001ms; L2 single-stock latest-price lookup p50≈0.0982ms; L2 market scan
counts p50≈18.8607ms. Intraday workflows explicitly read L1/L2 only; the L3
remote API incremental layer is not triggered by default and is excluded from
intraday benchmarks.

Inside the terminal shell you can ask directly:

```text
Check StockSage health.
Research 300308 with memory, news, positions and long-term labels.
Add 300394 to my watchlist.
```

> Research and health checks read local context directly. Mutating actions (watchlist, positions, memory, config) are dry-run first and require explicit confirmation before `backend.agent.cli action ... --confirm` executes them.

---

## 📋 Recommended Usage

| Option | When to use | Entry |
|---|---|---|
| **A. Hand the project to Codex / Claude Code** | Drop the repo at an agent and let it read the README, run health, configure `.env` itself | Any agent client |
| **A2. Native Pi Terminal Agent** | You want a built-in research / review chat interface | `stocksage` or `make agent-setup && make agent` |
| **B. Web console** (in development) | You want a graphical research dashboard | <http://localhost:5173> (API: <http://localhost:8000/docs>) |
| **C. Docker / compose** | You want a one-shot deployment of backend + frontend | `cp .env.example .env && make docker-up` |
| **D. Connect MCP tools** | You want StockSage as a tool surface for an outer agent | `make agent-mcp && make agent-mcp-config` |

<details>
<summary><b>Option A — hand the project to Codex / Claude Code</b></summary>

1. Send the GitHub homepage or repository URL to Codex / Claude Code.
2. Ask the agent to read `README.md` and [AGENTS.md](AGENTS.md) before running anything.
3. Ask the agent to run `python3 -m backend.agent.cli health --pretty` first to see database, memory, watchlist and position state.
4. Configure `.env` — for example `AI_PROVIDER=local_cli`, or set runtime keys such as `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`.
5. Let the agent install dependencies, initialize the database, start services or MCP, and approve privileged steps when prompted.
6. Use natural-language tasks for research, reviews, memory or project health checks.

</details>

<details>
<summary><b>Option A2 — terminal Agent</b></summary>

`make agent-setup` checks Python, installs StockSage agent dependencies, creates `.env`, initializes the database, and prompts for native Pi installation if needed. To let setup install Pi directly, run `INSTALL_PI=1 make agent-setup`. The default is `AI_PROVIDER=local_cli`, so internal LLM workflows use your local Claude / Codex CLI; switch to `anthropic` or `openai` only when you want cloud runtime keys.

`make agent` / `stocksage` starts the native Pi CLI and loads project-local `.pi/skills`, `.pi/prompts` and `.pi/extensions`. The project `.env` is read by the StockSage Python runtime and is not bulk-exported into the Pi process.

</details>

<details>
<summary><b>Option D — connect MCP tools</b></summary>

```bash
pip install -e ".[agent]"
PYTHONPATH=. python3 -m backend.agent.mcp_server
# Or:
make agent-mcp
make agent-mcp-config
```

Connect this MCP server to Claude Desktop, Claude Code, Cursor or any MCP-capable client, and the outer agent can call StockSage's project context, memory snapshot, stock context and health tools.

</details>

---

## 🤖 Agent Usage Guide

StockSage already agent-ifies research, memory, reviews and health checks. The point is not "how to run it" — it's **what to delegate to it**.

### Tasks you can delegate

| User goal | Task to delegate | Typical output |
|---|---|---|
| **Single-stock research** | Read one stock's signals, news, positions, long-term labels, historical reviews and project memory. | Research summary, evidence trail, risks, follow-up questions. |
| **Prepare a stock** | Add/reactivate a symbol, best-effort backfill prices and financials, then return the dossier and missing items. | Research readiness, missing data list, next steps. |
| **Topic research** | Investigate an industry, theme, value chain or group of stocks. | Theme conclusion, related symbols, source audit, questions to verify. |
| **Long-term research** | Run the long-term analyst team across sector thesis, financial quality, prosperity indicators and QFII flow. | Long-term label, score, key findings, hold / avoid rationale. |
| **Deep research** | Coordinate industry researcher, company researcher, risk reviewer, source auditor and report writer. | Markdown report, core conclusion, risk review, cited sources. |
| **Memory management** | Read or write long-term rules, risk preferences, research indexes, chat summaries and layered decision memory. | Memory summary, recall results, memory-write confirmations. |
| **Reviews and validation** | Analyze signal performance, attribution, win rate, drawdown, exit reasons and risk-rule execution. | Review summary, performance attribution, rule-calibration suggestions. |
| **Project health** | Check data coverage, scheduler, API, config, tests and docs. | Health report, anomalies, next maintenance steps. |

### Example prompts

```text
Read project memory, then research whether 300308 is still worth following.
Run an AI computing value-chain topic research report covering 300308 and 300394.
Run the long-term analyst team and refresh long-term labels for my watchlist.
Prepare a single-stock research dossier for 300308.
Run the long-term expert team once for 300308.
Check current data coverage and scheduler health.
```

### Common MCP tools

| Tool | Purpose |
|---|---|
| `stock_sage_project_context` | Project runtime overview, config, positions, watchlist, memory summary. |
| `stock_sage_memory_snapshot` | `ai_memory`, layered memory, audit log, chat-summary status. |
| `stock_sage_stock_context` | Single-stock signals, news, positions, long-term labels and memory context. |
| `stock_sage_health` | Agent mode, database, dependency and permission health. |

---

## ⚙️ Configuration

### API Keys

StockSage reads all external keys from `.env` in the project root. **Never commit `.env`, real keys, the database or personal trading records to Git.** The default local setup uses `AI_PROVIDER=local_cli`; enable news enrichment, push notifications and remote-agent exposure on demand. Empty keys and `your_*` placeholders are treated as unconfigured.

| Variable | Purpose | Required? | How to obtain |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Powers StockSage internal LLM calls when `AI_PROVIDER=anthropic`. | Optional; required for the Anthropic runtime | Create a key in the Anthropic Console |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | Used by `AI_PROVIDER=openai` for OpenAI or OpenAI-compatible endpoints. | Optional; required for the OpenAI runtime | Create a key on the provider's platform; for third-party endpoints also set `OPENAI_BASE_URL` |
| `TAVILY_API_KEY` | Real-time search supplement when local DB and iFinD MCP headlines are still insufficient; also used by `backfill_coverage --use-tavily` and long-term A-teacher evidence search. | Optional | Create an API key at [Tavily](https://app.tavily.com/) |
| `ANSPIRE_API_KEY` | Retained for explicit deep research / manual strict event-style news fetches; daily postmarket sentiment supplement now uses iFinD MCP → Tavily. | Optional | Register at [Anspire AI Search](https://aisearch.anspire.cn), create a key on the API Keys page |
| `BARK_KEY` / `BARK_SERVER` | iOS Bark push for postmarket signals, stop-loss alerts and circuit-breaker warnings. | Optional; pushes silently skipped if unset | Copy the device key from the Bark app; default server is `https://api.day.app` — override `BARK_SERVER` if self-hosting |
| `STOCKSAGE_AGENT_API_KEY` | Authenticates remote agent / MCP / HTTP writes when `STOCKSAGE_AGENT_MODE=remote`. | Not needed locally; required when exposing the agent remotely | Generate a long random string; enable `STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED` and the action allowlist on demand |
| `TUSHARE_TOKEN` / `TUSHARE_QFQ_ENABLED` | Optional Tushare qfq daily-bar fallback; disabled by default and registered after TickFlow / Eastmoney / AkShare (and optional efinance when installed). The raw `daily` endpoint remains debug-only because it is unadjusted. | Optional; requires `TUSHARE_QFQ_ENABLED=true` for qfq fallback | Get a token from [Tushare](https://tushare.pro/) |
| `TICKFLOW_ENABLED` / `TICKFLOW_API_KEY` / `TICKFLOW_BASE_URL` | TickFlow A-share daily-bar source; disabled by default, and when enabled uses `forward_additive` adjusted prices as the preferred CN provider. | Optional; requires `TICKFLOW_ENABLED=true` | Get a key from [TickFlow](https://tickflow.org/); default base URL is `https://api.tickflow.org` |
| `IFIND_MCP_ENABLED` / `IFIND_MCP_TOKEN` / `IFIND_MCP_BASE_URL` | Tonghuashun iFinD MCP adapter; when enabled, postmarket sentiment first uses `search_news` / `search_notice` for stock headlines and announcements. It is still not an A-share OHLCV market-data ingestion source. | Optional; requires `IFIND_MCP_ENABLED=true`, `IFIND_MCP_TOKEN` and `IFIND_MCP_BASE_URL` | Create or copy the token from the Tonghuashun iFinD MCP profile page; default base URL is `https://api-mcp.51ifind.com:8643/ds-mcp-servers` |

**A typical local setup**:

```env
AI_PROVIDER=local_cli
TUSHARE_TOKEN=your_tushare_token_here
TUSHARE_QFQ_ENABLED=false
TICKFLOW_ENABLED=false
TICKFLOW_API_KEY=your_tickflow_api_key_here
IFIND_MCP_ENABLED=false
IFIND_MCP_BASE_URL=https://api-mcp.51ifind.com:8643/ds-mcp-servers
IFIND_MCP_TOKEN=your_ifind_mcp_token_here
TAVILY_API_KEY=your_tavily_api_key_here
ANSPIRE_API_KEY=your_anspire_api_key_here
BARK_KEY=your_bark_device_key_here
BARK_SERVER=https://api.day.app
```

### Public Research Entry Points

| Capability | HTTP entry | Notes |
|---|---|---|
| Single-stock dossier | `GET /api/research/{symbol}/dossier` | Reads signal, long-term label, copilot, memory, deep-research pointers and missing items. |
| Prepare a stock | `POST /api/research/{symbol}/prepare` | Write action; adds/reactivates a stock, best-effort backfills data, then returns the dossier. |
| Single-symbol expert team | `POST /api/long-term/{symbol}/run` | Write action; synchronously runs the long-term team and saves the label. |
| Deep research | `POST /api/research/deep/run` | Write action; manually generates a local research report and never creates daily trading signals. |

Long-term labels include `quality`, `constraint_eligible` and `quality_notes`. Only trusted labels with `constraint_eligible=true` may block entries, reduce position size or cap scores; failed, stale, low-confidence or evidence-poor labels are display-only.

**For remote deployment / exposing MCP / HTTP to other machines, also add**:

```env
STOCKSAGE_AGENT_MODE=remote
STOCKSAGE_AGENT_API_KEY=replace_with_a_long_random_secret
STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED=false
STOCKSAGE_AGENT_REMOTE_WRITE_ACTIONS=
```

### Recommended Signal Weights

Production currently defaults to the `new_framework` weighting. Based on existing backtests and validation results, the recommendation is to **temporarily exclude the quant layer from the composite score** and keep only technical and news-sentiment signals:

| Variable | Recommended | Meaning |
|---|---:|---|
| `WEIGHT_QUANT` | `0.0` | Quant layers like Qlib / Kronos are still computed and logged but do not affect the composite score by default |
| `WEIGHT_TECHNICAL` | `0.6` | Weight of technical signals |
| `WEIGHT_SENTIMENT` | `0.4` | Weight of news-sentiment / event signals |
| `NEW_FRAMEWORK_ENTRY_THRESHOLD` | `25.0` | Composite score must exceed this to become a small-position trial candidate |

These are **current project recommendations, not hard-coded trading advice**. Adjust on the Web config page or in `.env`, and validate your own parameter mix with backtests and reviews.

---

## 🖼 Architecture

![StockSage System Architecture](docs/assets/architecture.svg)

---

## 🗺 Roadmap

The next phase expands StockSage along three axes — taking it from "personal A-share research" to **a cross-market, cross-device research workspace**.

| Direction | Plan | Status |
|---|---|---|
| 🌐 **Multi-market support** | Beyond A-shares, ingest HKEX (HK) and US-market quotes, news, and basic fundamentals; reuse the existing layered signals, long-term research and memory stack. | Planned |
| 🎨 **Frontend polish** | Web console UX work — research dashboards, signal detail views, portfolio views, memory browser, and mobile responsiveness. | In progress |
| 📱 **Client apps** | Native desktop / mobile clients so local data and the agent workflow work without a CLI or a browser. | Upcoming |

> Detailed milestones, sub-tasks and timelines live in [docs/ROADMAP.md](docs/ROADMAP.md). Suggestions welcome via GitHub Issues / Discussions.

---

## ⚠️ Cautions

### 🛡 Risk & Scope

- StockSage is a research and decision-support tool — **not investment advice, and it never places real orders**.
- LLMs do not directly predict prices; take-profit and stop-loss levels come from ATR formulas, portfolio constraints and risk rules.

### 🔐 Security & Permissions

- Local Codex / Claude Code sessions are trusted by default; remote agents are read-only by default.
- Remote writes require **all of** an API key, the remote-write switch, and an action allowlist.
- API keys are StockSage **runtime** credentials, not Codex / Claude Code chat credentials; they are consumed only when running the internal LLM, search, push or remote-agent pipelines.
- `.env`, databases, model files, personal trading records and real keys should never enter Git.

### 📊 Data & Quotas

- **Data sources and corresponding API keys**: A-share daily bars use the Eastmoney / AkShare fallback chain by default; `efinance` is now an optional extra because of upstream dependency-audit debt, and installing `pip install -e ".[efinance]"` adds it back to the CN daily and index fallback chains. Setting `TICKFLOW_ENABLED=true` with `TICKFLOW_API_KEY` makes TickFlow the preferred CN provider using `forward_additive` adjusted prices, with the original fallback chain retained behind it. Setting `TUSHARE_QFQ_ENABLED=true` adds Tushare qfq as a late, normalized fallback while the raw `daily` endpoint stays debug-only. A-share fundamentals, QFII and base news go through AkShare / Eastmoney (no key required). When `IFIND_MCP_ENABLED=true` and a token is configured, postmarket news sentiment first supplements with iFinD MCP `search_news` / `search_notice`; if headlines are still insufficient, it falls back to `TAVILY_API_KEY`. Anspire is retained for explicit deep research / manual strict event-style news fetches, not the daily postmarket batch path. iOS push uses `BARK_KEY`; remote agent auth uses `STOCKSAGE_AGENT_API_KEY`.
- **Free / trial quotas** (public information as of 2026-05-23):
  - **Tavily** Researcher free tier offers 1,000 credits / month; StockSage currently uses basic search (~1 credit per request); development keys default to 100 RPM, production keys to 1,000 RPM (paid plan or PAYGO required). See [Tavily Credits](https://docs.tavily.com/documentation/api-credits) · [Rate Limits](https://docs.tavily.com/documentation/rate-limits).
  - **Anspire** is currently retained for explicit deep research / manual strict news fetches. Public docs mention checking each resource package's total quota and usage in the console but give no fixed free-quota figure; treat the [Anspire console](https://aisearch.anspire.cn) resource-package page as authoritative. See [usage guide](https://open.anspire.cn/document/docs/openPlatform/).
  - **Tushare** now has an optional qfq daily fallback (`TUSHARE_QFQ_ENABLED=true`) that joins `daily` with `adj_factor` and normalizes OHLCV before returning data. The unadjusted `daily` endpoint remains debug-only. See [daily bars](https://www.tushare.pro/document/2?doc_id=27) · [adj_factor](https://www.tushare.pro/document/2?doc_id=28) · [permissions](https://www.tushare.pro/document/2?doc_id=108).
  - **TickFlow** can optionally become the preferred A-share daily source; StockSage currently uses `forward_additive`, which TickFlow documents as aligned with Eastmoney / Tonghuashun-style adjusted prices. Realtime quotes, minute bars, and higher-frequency access depend on the plan. See [quickstart](https://docs.tickflow.org/zh-Hans/quickstart) · [API overview](https://docs.tickflow.org/zh-Hans/api-reference/introduction).
  - **Tonghuashun iFinD MCP** supplements postmarket sentiment with `search_news` / `search_notice` when enabled. It is still not a stable OHLCV market-data source; A-share daily-bar writes continue to use fieldized market-data providers.
  - **Bark**'s `api.day.app` is the push entry point; the key comes from the app's test URL / device key. Public tutorials make no guarantee of free quota or SLA — self-host for high-frequency push. See [Bark tutorial](https://github.com/Finb/Bark/blob/master/docs/en-us/tutorial.md).

### 💡 Usage Habits

- Before trading, research or reviews, read project context and project memory — **do not rely on the current chat window alone**.
- Long-term memory writes require explicit user intent; one-off questions and ordinary coding preferences should **not** enter trading-system memory.
- Daily postmarket batch signals keep multi-agent off by default to avoid linear runtime LLM token spend across 25+ stocks.

---

## 📚 More Docs

| Document | Description |
|---|---|
| [PROJECT.md](PROJECT.md) | Project index, milestones and key file map |
| [STATUS.md](STATUS.md) | Current snapshot, signal weights, schedules, tests and startup commands |
| [CHANGELOG.md](CHANGELOG.md) | Completed milestones and major changes |
| [docs/ROADMAP.md](docs/ROADMAP.md) | In-progress work, roadmap and deferred items |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup, test expectations and contribution flow |
| [AGENTS.md](AGENTS.md) | Codex / Claude Code / MCP local-agent instructions |

---

## ⚖️ Disclaimer

StockSage is a personal research and decision-support tool, **not investment advice**. It does not place trades automatically. LLMs do not predict prices. Take-profit and stop-loss levels are generated from ATR formulas and risk constraints. **Users are responsible for all trading decisions and financial risks.**
