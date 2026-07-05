# MingCang

> **A local-first A-share research agent**: a conversational personal workbench for research, signals, position discipline, reviews, and memory.

MingCang is not a quant trading system and not an AI stock picker. It does not promise returns, place orders, or decide for you. It organizes the stocks, sectors, views, risks, and review outcomes you care about, then uses AI to widen the scan, challenge assumptions, gather evidence, and promote only outcome-tested lessons into memory.

**Recommended mode today: open the MingCang Agent and talk to it in natural language.** MingCang recently went through a major refactor, and the frontend experience is still being polished. The web UI is useful as a local visual workbench, but daily research, reviews, watchlist maintenance, and risk checks are currently best done through the agent.

[![Docs](https://img.shields.io/badge/%F0%9F%93%96_Docs-mingcang.docs-ffd400?labelColor=07070d)](https://zeeechenn.github.io/MingCang/)
[![CI](https://github.com/Zeeechenn/MingCang/actions/workflows/test.yml/badge.svg)](https://github.com/Zeeechenn/MingCang/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/Zeeechenn/MingCang?logo=github&color=success)](https://github.com/Zeeechenn/MingCang/releases)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-22c55e)
![Agent](https://img.shields.io/badge/agent--first-Pi%20%7C%20Claude%20Code%20%7C%20Codex%20%7C%20Cursor-8957e5)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue)

**Online docs**: <https://zeeechenn.github.io/MingCang/> | **Language**: [简体中文](README.md) · [English](README_EN.md)

---

## 30 Seconds

- **Research entry point**: ask in natural language; MingCang routes local research, signals, memory, and risk context for you.
- **Daily cadence**: pre-market risk scan, intraday notes, post-market signals/news/risk-line review, and weekend health checks.
- **Decision boundary**: AI scans wider, pokes holes, and gathers evidence; final judgment, sizing, and trading actions remain yours.
- **Data boundary**: local-first by default. Prices, news, positions, reviews, and memory stay on your machine unless you explicitly enable remote features.
- **Current shape**: agent-first. The frontend is still being product-polished after the refactor and is not the primary entry point yet.

---

## Say It Like This

| What you want | Say this to MingCang |
|---|---|
| Research one stock | "Look at 300308. Should I watch, try a small starter, or avoid it?" |
| Pre-market check | "Scan my watchlist before the open and tell me which risks matter first." |
| Post-market review | "Review today's signals, news, risk lines, and follow-up items after the close." |
| Maintain a watchlist | "Add Zhongji Innolight to my watchlist and keep tracking it." |
| Track a theme | "Track 1.6T optical-module demand as a long-term thesis and list invalidation conditions." |
| Feed an opinion | "I saw a view that advanced packaging may accelerate. Archive it and look for counterevidence." |
| Review a trade | "Review this CATL loss and see whether it should become a rule." |
| Inspect memory | "What mistakes have I made before in semiconductor names? Remind me next time." |

MingCang turns these natural-language requests into local tool calls. You do not need to memorize internal entry points or module names.

---

## Quick Start

### Recommended: Install The Agent Entry

```bash
curl -fsSL https://raw.githubusercontent.com/Zeeechenn/MingCang/main/scripts/install.sh | sh
mingcang
```

Then talk to it directly, for example:

```text
Look at 300308. Combine signals, news, long-term labels, and past memory, then give me a research conclusion.
```

The default local mode prefers your logged-in local AI runtime. You only need cloud model, search, or data-provider keys when you explicitly enable those features.

### Optional: Frontend Preview

The frontend can display local sample data, dossiers, and daily panels, but it is still being polished after the refactor. To take a quick look:

```bash
git clone https://github.com/Zeeechenn/MingCang.git
cd MingCang
make demo
```

Then open <http://127.0.0.1:5173>. Demo data and real data are separate; the demo is only for trying the flow and does not represent your actual watchlist or research conclusions.

![MingCang frontend preview: decision dossier](docs/assets/screenshot-watchlist.png)

---

## Signal Card Example

```
  600584 JCET                                       2026-06-02
  ────────────────────────────────────────────────────────────
  Composite 25.8        Call  🟡 Small starter
  Technical 28.6  ·  Quant 25.8  ·  News sent. +18.0
  Stop 64.66    Target 98.17    (ATR 2.5 trailing)
  ────────────────────────────────────────────────────────────
  rule: aggregate_v1  ·  stays on your machine
```

Same day, batch view:

| Code | Name | Composite | Call | Tech | Quant | News sent. | Stop | Target |
|---|---|---:|---|---:|---:|---:|---:|---:|
| 600584 | JCET | **25.8** | 🟡 Small starter | 28.6 | 25.8 | +18.0 | 64.66 | 98.17 |
| 603986 | GigaDevice | 4.3 | 🔵 Watch | 26.4 | 4.5 | −55.2 | 414.86 | 603.09 |
| 300750 | CATL | −1.7 | ⚪ Stand by | −12.5 | 1.3 | +18.0 | 397.42 | 488.68 |

Signals provide tiered calls and ATR risk lines. They do not predict price moves and do not use guaranteed-gain language. News sentiment is a research input, not a standalone buy/sell trigger.

---

## Core Capabilities

| Capability | What it does |
|---|---|
| Agent conversation entry | Turns stock research, watchlists, daily scans, reviews, and memory lookup into natural-language interaction. |
| Daily signals and risk lines | Combines technical factors, news sentiment, quality flags, and ATR trailing stops into discipline-oriented daily references. |
| Research analyst modules | Encodes finance-quality, prosperity, and supply-chain frameworks for long-term research without overriding daily signals. |
| Dossier loop | Links research, signals, positions, reviews, and memory so you can audit why a judgment was made. |
| Local data foundation | SQLite, cache contracts, quality gates, and point-in-time discipline reduce dirty data and hindsight bias. |
| Memory system | Promotes only outcome-tested, reviewed lessons into trusted memory. |
| Frontend workbench | Visualizes dossiers, signals, reviews, and source health; still in product-experience polishing. |

---

## Case Study: Turning A Loss Into A Rule

MingCang runs research as a loop: judgment -> signal -> position -> review attribution -> memory update. Here is one paper-trading record.

**CATL (300750) · 2026-05 · paper trading**

| Step | Record |
|---|---|
| Entry | 05-14 @ 449.38, stop 395.57 |
| Hold | Signal kept weakening; there was no "signal-reversal exit" rule yet, so the position stayed open. |
| Exit | 05-25 @ 411.28, loss −8.48% |
| Review | Root cause: missing signal-reversal exit rule. |
| Improvement | Add a "signal-reversal exit" rule and wait for future outcome validation. |

Full chain: [CATL live sample](docs_public/ningde_live_sample.md).

The point: **a loss is survivable; failing to learn from it is the real problem.** MingCang turns review attribution into candidate memory, and only confirmed lessons become trusted context for future research.

---

## Paper-Trading Results

```
  📒 Paper-trading final review              2026-05-12 ~ 06-01
  ────────────────────────────────────────────────────────────
  7 trades all closed · 20% size each
  Position-weighted total  +3.79%      Sum of 7 names  +18.94%
  ────────────────────────────────────────────────────────────
  2 winners   GigaDevice +34.26%   ·   JCET +11.33%
  5 stops     avg −5.33% (max −9.20%)

  Win/loss ratio ≈ 4.3 : 1 (avg win +22.8% / avg loss −5.3%)
  ────────────────────────────────────────────────────────────
  paper-trading replay · not real money · history not rewritten
```

Paper trading validates research flow and risk discipline. It is not real performance and is not investment advice.

---

## Agent Integration

MingCang's primary entry is the local agent. You can use the built-in `mingcang` Pi terminal, or let outer agents such as Claude Code, Codex, and Cursor read project rules and call MingCang capabilities.

Outer agents should start with [AGENTS.md](AGENTS.md), then read [STATUS.md](STATUS.md), [PROJECT.md](PROJECT.md), and public docs only as needed. Writes to watchlists, memory, config, or remote tools follow the local/remote boundary and dry-run rules.

Core context tools:

| Tool | Purpose |
|---|---|
| `mingcang_project_context` | Positions, watchlist, memory summary, configuration overview |
| `mingcang_stock_context` | One stock: signal, news, labels, research-copilot shadow conclusion |
| `mingcang_memory_snapshot` | Layered memory, audit logs, memory-promotion status |
| `mingcang_health` | Database, dependency, and permission health |

---

## Deep Dive

You do not need this section for daily use. It is here for readers who want to understand the internal design.

### Research Analyst Modules

MingCang encodes mature research methods as reusable analyst modules, each reading a stock from a different angle before the system fuses the long-term judgment:

| Analyst | Method source | What it reads |
|---|---|---|
| 📊 **Piotroski F-Score** | Classic academic 9-factor framework | Financial quality: profitability, leverage, operating efficiency |
| 📈 **Prosperity analyst** | Prosperity-investing framework | Marginal changes in profit, revenue, ROE, and related indicators |
| 🔗 **Supply-chain analyst** | Industry-chain and supply-chain checks | Leading indicators, cycle position, and hype filtering for tech/hardware sectors |
| 🧭 **Serenity chokepoint framework** | Serenity chokepoint skill / report-gate methodology | Supply-chain bottlenecks, evidence tiers, non-consensus leads, and falsification questions; currently a research checklist and stricter report-gate layer, not a production signal driver |

These belong to the long-term research layer. They do not directly change daily signals, which remain constrained by explicit rules, risk lines, and evidence gates.

### LLM Debate And Discretion Arm

MingCang does have an LLM layer, but its role is **research discretion and adversarial review**, not automatic trading.

| Capability | What it does | Boundary |
|---|---|---|
| Multi-round LLM debate | Director raises debate topics, Researcher runs bull/bear debate or fast consensus, and RiskManager vetoes or downgrades risky proposals. | Produces disagreement, counterevidence, and risk notes; does not directly change official signals. |
| LLM discretion arm | Generates reference cards for candidate comparison, watch/starter tilt, hold/exit interpretation, trim/exit inclination, timing notes, and review attribution. | Gray-release off by default; when enabled, still observe-only and cannot change stops, targets, positions, or official signals. |
| Adversarial review | Finds the strongest objection to each discretion card and checks for missing evidence or reasoning jumps. | Reviews only; it does not decide for the user. |

So the accurate public wording is not "LLM buys, sells, and picks stocks directly." It is: **LLM assists candidate comparison, position-exit interpretation, timing judgment, and review attribution while staying inside rule signals, ATR risk lines, and human confirmation boundaries.**

### Data Foundation

| Capability | What it does |
|---|---|
| Multi-source fallback | Provider registry with cooldown-based fallback when the primary source fails. |
| Point-in-time discipline | Historical checks only use data visible at the time, reducing hindsight contamination. |
| Quality gates and coverage reports | Validate prices, financials, news, and source coverage; dirty data raises warnings. |
| Cache and freshness contracts | Declare when local cache can be reused and when data should refresh. |

Research is only as good as its data. MingCang tries to make each judgment traceable and reviewable.

### Research-To-Decision Loop

MingCang models research as a dossier loop: four Case types connect research, signals, positions, and reviews.

![MingCang research-to-decision loop](docs/assets/architecture.svg)

```
Inputs (data + news + your judgment + external theses)
        │
        ▼
  ResearchCase ──▶ SignalCase ──▶ PositionCase ──▶ ReviewCase
   why research it     tradable now?    why hold/exit?     what did it teach?
        ▲                                                   │
        └────────── memory update (outcome-gated, human-confirmed) ◀────┘
```

Plain English: record why something is worth researching, decide whether it is actionable now, record why it is held or exited, then review what the result taught you. Only outcome-tested, human-confirmed lessons become trusted memory. Full architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Current Capability Status

| Capability | Current status |
|---|---|
| Post-market risk panel | Shows risk warnings, recheck triggers, ATR distance, financial quality, and data quality in one review surface. |
| Watchtower and triggers | Records price, fund-flow, news, and theme changes for tracked names; triggered items enter a review queue. |
| Daily reports | Cover pre-market, intraday, post-market, and weekend health checks, with internal terms translated into research questions. |
| LLM discretion layer | Supports candidate comparison, hold/exit interpretation, timing notes, and review attribution; gray-release off by default, and enabled output is still reference-only. |
| Blind judging | Judgment features can be evaluated through cross-model blind judging and forward validation before affecting production judgment. |
| Web frontend | Local workbench and daily pages exist, but the refactored product experience is still being polished; agent-first is recommended. |

---

## Configuration

<details>
<summary><b>Local And Remote Configuration</b></summary>

Keep real keys in your local `.env` or deployment secret manager. Do not commit them. Start from `.env.example`:

```env
AI_PROVIDER=local_cli
DATABASE_URL=sqlite:////absolute/path/to/mingcang.db
MINGCANG_AGENT_MODE=local
```

Default local mode uses `AI_PROVIDER=local_cli`, preferring your logged-in local AI runtime and requiring no cloud LLM key. Fill the keys below only when enabling the matching provider or feature:

| Variable | When to set | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | `AI_PROVIDER=anthropic` | Anthropic Claude runtime key. |
| `OPENAI_API_KEY` | `AI_PROVIDER=openai` | OpenAI or compatible API key. |
| `OPENAI_BASE_URL` | OpenAI-compatible gateway | Leave empty for OpenAI's official endpoint. |
| `TUSHARE_TOKEN` | Tushare Pro A-share data supplement | Optional market-data provider. |
| `TICKFLOW_API_KEY` | `TICKFLOW_ENABLED=true` | TickFlow market-data provider key. |
| `IFIND_MCP_TOKEN` | `IFIND_MCP_ENABLED=true` | iFinD observe-only adapter token. |
| `TAVILY_API_KEY` | Real-time news/search supplement | Used when DB news is insufficient. |
| `ANSPIRE_API_KEY` | Deep research or strict event-news retrieval | Anspire search key. |
| `BARK_KEY` | iOS Bark notifications | Optional notification key. |
| `MINGCANG_AGENT_API_KEY` | `MINGCANG_AGENT_MODE=remote` | Required for remote agent exposure; local mode does not need it. |

Remote exposure is opt-in and read-only by default:

```env
MINGCANG_AGENT_MODE=remote
MINGCANG_AGENT_API_KEY=your_secret_key
MINGCANG_AGENT_REMOTE_WRITE_ENABLED=false
MINGCANG_AGENT_REMOTE_WRITE_ACTIONS=
```

`.env`, local databases, personal trading records, and real keys do not go into Git.

</details>

---

## Docs Index

| File | What it contains |
|---|---|
| [docs_public/index.md](docs_public/index.md) | Public docs home: navigation, shortest path, core capabilities |
| [docs_public/USER_GUIDE.md](docs_public/USER_GUIDE.md) | Agent usage guide: natural-language stock research, daily scans, long-term theses, review memory |
| [docs_public/FEATURE_MAP.md](docs_public/FEATURE_MAP.md) | Feature map: description, entry, status, write/signal/key boundary |
| [docs_public/DEVELOPER_GUIDE.md](docs_public/DEVELOPER_GUIDE.md) | Development guide: pages, APIs, actions, research modules, quant modules |
| [docs_public/REFERENCE.md](docs_public/REFERENCE.md) | Reference: low-level interfaces, config, key files |
| [AGENTS.md](AGENTS.md) | Agent rules and safety boundaries |
| [PROJECT.md](PROJECT.md) | Repository navigation and key-file index |
| [STATUS.md](STATUS.md) | Current production status, signal weights, validation entry points |
| [CHANGELOG.md](CHANGELOG.md) | Version history and completed updates |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development environment and contribution flow |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layered architecture, Case types, fusion logic |
| [docs/WHY_NOT_AI_STOCK_PICKER.md](docs/WHY_NOT_AI_STOCK_PICKER.md) | Why MingCang is not an AI stock picker: LLM boundary, ATR discipline, memory gates |

---

## License And Disclaimer

MingCang currently uses the [PolyForm Noncommercial License 1.0.0](LICENSE): personal research, learning, experimentation, and noncommercial use/modification/distribution are allowed; unauthorized commercial use, commercial integration, hosted commercial service, or resale is not allowed. Contact the maintainer for commercial licensing.

Copies obtained under an earlier MIT License remain governed by the license text attached to those copies at the time. The current repository and future versions are no longer released under MIT.

MingCang is a personal research tool and **does not provide investment advice**. The system does not place orders. LLMs do not predict prices. Stops and targets come from ATR formulas and risk constraints. All trading decisions and capital risk remain with the user.

---

## Direction

MingCang's north star: **let AI amplify your judgment, not replace your brain.**

- **Keep strengthening agent-first usage**: users should complete research, reviews, watchlist updates, and memory lookups through natural language instead of learning internal entry points.
- **Keep polishing the frontend**: the web UI will move from "visible" to "pleasant and useful," but agent mode is still the primary path today.
- **Activate new capabilities through real outcomes**: new models, factors, and frameworks must pass forward samples, data-quality checks, and reviews before they influence production judgment.
- **Extend A/HK/US research chains**: A-shares remain the main battlefield; HK and US equities will gradually move from read-only research to trackable, reviewable workflows.
- **Remember only what has been validated**: a lesson becomes trusted memory only after outcome review, not because it sounds convincing.
