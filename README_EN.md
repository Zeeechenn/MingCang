# MingCang

**MingCang is a local-first personal A-share research and decision workbench.** It breaks "I like this stock" into an auditable loop — **import judgment → record evidence → falsify → track → review & attribute → update memory** — so every judgment can be replayed, challenged, and verified, and every outcome becomes evidence you can use next time.

The goal isn't a smarter "prediction AI." It's a **research operating system** for the individual investor:

- **You** own alpha, sector knowledge, and the final decision;
- **AI** handles breadth sweeps, falsification, and short-term risk discipline;
- **the system** turns judgments and outcomes into memory that grows over time.

[![Docs](https://img.shields.io/badge/%F0%9F%93%96_Docs-mingcang.docs-ffd400?labelColor=07070d)](https://zeeechenn.github.io/MingCang/)
[![CI](https://github.com/Zeeechenn/MingCang/actions/workflows/test.yml/badge.svg)](https://github.com/Zeeechenn/MingCang/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/Zeeechenn/MingCang?logo=github&color=success)](https://github.com/Zeeechenn/MingCang/releases)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-22c55e)
![Agent](https://img.shields.io/badge/agent--ready-Pi%20%7C%20Claude%20Code%20%7C%20Codex%20%7C%20Cursor-8957e5)
![License](https://img.shields.io/badge/license-MIT-blue)

**📖 Online docs**: <https://zeeechenn.github.io/MingCang/>

**Language**: [简体中文](README.md) · [English](README_EN.md)

---

## What it helps you do

| You want to... | How MingCang plugs in |
|---|---|
| **Research one stock** | `mingcang stock 000001` pulls signals, news, labels, and the research-copilot shadow conclusion, and records your judgment as a `ResearchCase` |
| **Track a long-term theme/sector** | Import theses from external analysts, institutions, or prosperity frameworks as a `ForwardThesis` with invalidation conditions and a review cadence, tracked over time |
| **Stay on top of daily signals & risk** | Technical factors + LLM news sentiment generate the official signal; ATR trailing stops protect gains; exposure and data-quality alerts fire automatically |
| **Review and compound experience** | After outcomes land, attribute results; falsification hits/misses are scored; only human-confirmed lessons promote into trusted memory |
| **Let AI do all of the above** | A built-in `mingcang` Pi terminal, plus Claude Code / Codex / Cursor via CLI / MCP |

MingCang never decides for you: **LLMs don't predict prices, don't place orders, and don't silently change signals.** Stops are ATR-derived rules, and memory only promotes after outcomes and human confirmation.

---

> **First-time path:** use `make demo` below if you want a no-key trial; use [Quick start](#quick-start) when you want to install the `mingcang` terminal; use `make install` plus `make dev` / `cd frontend && npm run dev` if you are developing.

## 3-minute demo (no real keys / no provider network)

```bash
git clone https://github.com/Zeeechenn/MingCang.git
cd MingCang
make demo        # seed mock data, then start backend + frontend
```

Open <http://127.0.0.1:5173>. The first screen is the new MingCang terminal: you can ask for stock research, review candidates, watchlist actions, and governance drafts in natural language. The navigation opens the decision pulse, stock dossiers, review dossiers, research copilot, position discipline, source health, and governance console. The demo database also includes sample stocks, a long-term thesis, a review case, and one pending memory-promotion candidate for the full loop in the [User Guide](docs_public/USER_GUIDE.md). The backend health check is at <http://127.0.0.1:8000/health>, and the interactive API docs (Swagger UI) are at <http://127.0.0.1:8000/docs>. Press `Ctrl+C` to stop the demo.

![MingCang frontend preview: decision pulse dossier](docs/assets/screenshot-watchlist.png)

---

## Architecture: the research-to-decision loop

0.3.0 rebuilds the whole research model into a **case-based loop**: four "cases" wire research, signal, position, and review into one loop across five layers (L0–L4). Each case answers exactly one question, and they link to each other and stay auditable.

![MingCang research-to-decision architecture](docs/assets/architecture.svg)

```
Import (data + news + your judgment + external theses)
        │
        ▼
  ResearchCase ──▶ SignalCase ──▶ PositionCase ──▶ ReviewCase
   why study it?    tradable now?   why hold / when exit?  what did it teach?
        ▲                                                     │
        └──────────── memory update (outcome-gated, human-confirmed) ◀───┘
```

| Layer | Name | Question | Boundary |
|---|---|---|---|
| **L0** | Memory / Knowledge Base | What have I learned before? | User rules, reviewed lessons, research memory; LLM output defaults to `pending` and cannot self-promote to trusted |
| **L1** | Evidence | What reliable evidence exists? | Source/time/PIT/quality-aware evidence cards; packaging only, no scoring |
| **L2** | Thesis | Is this worth studying? | `ResearchCase`, `ForwardThesis`, theme hypotheses; advisory, never overrides official action |
| **L3** | Signal / Position | Tradable now? How to enter/exit? | `SignalCase` / `PositionCase` proposals and shadow output; doesn't touch real positions directly |
| **L4** | Review / Promotion / Calibration | What did the outcome teach? | `ReviewCase` attribution → memory-promotion candidate; trusted promotion stays human-gated |

### How the pieces fuse together

- **Single-stock research** → the `ResearchCase → SignalCase → PositionCase` path: `mingcang stock <symbol>` gives you the official signal, news, labels, and the research copilot's shadow conclusion in one shot.
- **Long-term / theme research** → lives in **L2 (Thesis)**: external analyst, institutional, and prosperity/financial-framework judgments are imported as a `ForwardThesis` (with invalidation conditions, follow-up metrics, review cadence) and tracked as slow evidence — never a shortcut to a buy score.
- **Where data comes from** → **L1 (Evidence) + the data layer**: A-share prices/financials/QFII, news sentiment, A/HK/US read-only global data, all in local SQLite, never the cloud; a Provider Guard enforces freshness and adjustment-basis sanity.
- **What memory is for** → **L0 + L4**: rules, lessons, and research indexes are stored in layers; only ReviewCase-attributed, human-confirmed outcomes promote from `pending` to trusted, then feed back as context for the next judgment — that's why the loop grows.

> **Status**: this case-based loop has landed but is **dormant by default** — the skeleton comes first with zero production-signal change, activating layer by layer as the forward-evidence gate clears. Production signals remain technical 0.6 + sentiment 0.4 + ATR 2.5 trailing stop; quant stays off pending evidence.

---

## What's working now

| Layer | What it does |
|---|---|
| Data | Market, news, fundamentals, QFII, A/HK/US read-only global data — local SQLite, stays on your machine |
| Signals | Technical factors + LLM news sentiment, weighted 0.6 / 0.4 in production, ATR 2.5 trailing stop |
| Research | Stock dossier, deep research, thesis import, falsification scoreboard, external analyst / institutional ingest |
| Memory | Layered memory, outcome-gated promotion, full audit log |
| Agent | Built-in `mingcang` Pi terminal + MCP / CLI for Claude Code, Codex, Cursor |
| UI | React frontend + REST API, local-first |

---

## Quick start

MingCang ships with a **`mingcang` Pi terminal shell** — it packages the whole CLI, memory, research flow, and safety boundaries into a ready-to-use agent terminal, so you don't have to memorize commands. If you only want the offline demo, use `make demo` above instead.

```bash
curl -fsSL https://raw.githubusercontent.com/Zeeechenn/MingCang/main/scripts/install.sh | sh
mingcang
```

Once installed, just talk to it in plain language ("look at 300308", "scan my watchlist", "review last week's positions") — it reads project context, runs the CLI, and returns research and risk conclusions itself.

Manual / dev mode:

```bash
git clone https://github.com/Zeeechenn/MingCang.git
cd MingCang
make agent-setup   # prepare environment
make agent         # launch the Pi terminal
```

Default `AI_PROVIDER=local_cli` routes internal LLM work through your logged-in local CLI — no cloud key needed. Demo mode does not require any LLM or market-data keys. You can also call the raw CLI:

```bash
python3 -m backend.agent.cli health --pretty
python3 -m backend.agent.cli premarket --pretty
python3 -m backend.agent.cli stock-context 000001 --pretty
```

---

## Usage guide

Once installed, you can either talk to the `mingcang` Pi terminal in plain language or run the raw CLI. Here are the most common flows.

### Research one stock

Tell the Pi terminal "research Zhongji Innolight" or "how does 300308 look right now?" — it pulls the stock context first, then concludes:

```bash
mingcang stock 300308
# Or call the raw CLI directly:
python3 -m backend.agent.cli stock-context 300308 --pretty
```

You get the official signal (buy / watch / avoid), recent news and sentiment, long-term labels, the research copilot's shadow conclusion, and the risks and open questions it lists. For deeper digging, have it run a deep-research pass:

```bash
python3 -m backend.agent.cli action research.deep.run \
  --payload-json '{"topic":"1.6T optical module demand","symbols":["300308"]}' --pretty
```

### Check signals every day

MingCang splits the trading rhythm into four one-line workflows:

```bash
python3 -m backend.agent.cli premarket  --pretty   # pre-market: pre-sync checks and entry points
python3 -m backend.agent.cli intraday   --pretty   # intraday: fast read-only local-cache stock lookups
python3 -m backend.agent.cli postmarket --pretty   # post-market: full-market signals and review report
python3 -m backend.agent.cli weekend    --pretty   # weekend: long-term label refresh and weekly reflection
```

In the Pi terminal just say "run the pre-market scan" or "review after close." Signals include the day's suggestion, the ATR trailing-stop level, portfolio exposure, and data-quality alerts — MingCang never places the order, it just enforces discipline.

### Maintain a watchlist

Add a name (dry-run by default; add `--confirm` to commit):

```bash
python3 -m backend.agent.cli action watchlist.add \
  --payload-json '{"symbol":"300308","name":"Zhongji Innolight","market":"CN"}' --pretty
```

Remove with `watchlist.remove`. Then scan the whole list via `project-context` or the post-market workflow. Or just tell the Pi terminal "add Zhongji Innolight to my watchlist" / "scan my watchlist."

### Run long-term research and keep tracking it

Record a sector or theme judgment (yours, a seasoned researcher's, or from a prosperity/financial framework) as a thesis with invalidation conditions; the system tracks it over time and reminds you to review on schedule:

```bash
python3 -m backend.agent.cli action long_term.run --payload-json '{"symbol":"300308"}' --pretty
```

It won't raise a buy score just because a thesis "sounds reasonable" — only after the outcome lands and the review passes does the judgment promote into trusted memory and feed the next round of research.

### Put memory to work

```bash
python3 -m backend.agent.cli memory-snapshot --pretty
```

This shows layered memory, the audit log, and promotion status: which rules/lessons are trusted and which are still pending. Trusted memory is injected automatically as context the next time you research the same stock or theme.

---

## Agent integration

For Pi / Claude Code / Codex / Cursor, the minimal setup is:

1. Read [AGENTS.md](AGENTS.md) — local/remote boundaries
2. Load `STATUS.md` / `PROJECT.md` / `docs/ROADMAP.md` as the task requires
3. Mutating actions dry-run first and wait for confirmation

Core MCP tools:

| Tool | Purpose |
|---|---|
| `mingcang_project_context` | Positions, watchlist, memory summary, config overview |
| `mingcang_stock_context` | Single-stock signals, news, labels, copilot shadow |
| `mingcang_memory_snapshot` | Layered memory, audit log, promotion pipeline state |
| `mingcang_health` | Database, dependency, permission health check |

---

## Configuration

<details>
<summary><b>Local and remote configuration</b></summary>

```env
AI_PROVIDER=local_cli
DATABASE_URL=sqlite:////absolute/path/to/mingcang.db
MINGCANG_AGENT_MODE=local
```

Remote exposure is opt-in and read-only by default:

```env
MINGCANG_AGENT_MODE=remote
MINGCANG_AGENT_API_KEY=your_secret_key
MINGCANG_AGENT_REMOTE_WRITE_ENABLED=false
MINGCANG_AGENT_REMOTE_WRITE_ACTIONS=
```

Keep `.env`, databases, personal trading records, and real keys out of Git.

</details>

---

## Docs

| File | Contents |
|---|---|
| [docs_public/index.md](docs_public/index.md) | MingCang public docs home: navigation, shortest path, core capabilities |
| [docs_public/USER_GUIDE.md](docs_public/USER_GUIDE.md) | User guide: demo, single-stock research, daily scan, long-term theses, review and memory |
| [docs_public/FEATURE_MAP.md](docs_public/FEATURE_MAP.md) | Feature catalog: explanation, entry point, status, write/signal/key boundary for each feature |
| [docs_public/DEVELOPER_GUIDE.md](docs_public/DEVELOPER_GUIDE.md) | Developer guide: pages, APIs, actions, research modules, quant modules |
| [docs_public/REFERENCE.md](docs_public/REFERENCE.md) | Reference: CLI, API groups, config, key files |
| [AGENTS.md](AGENTS.md) | Agent usage rules and safety boundaries |
| [PROJECT.md](PROJECT.md) | Codebase navigation and key file index |
| [STATUS.md](STATUS.md) | Current production state, signal weights, test entry points |
| [CHANGELOG.md](CHANGELOG.md) | Release history and completed work |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup and contribution flow |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full L0-L4 architecture and case-loop details (Chinese-first) |
| [docs/WHY_NOT_AI_STOCK_PICKER.md](docs/WHY_NOT_AI_STOCK_PICKER.md) | Why MingCang is not an AI stock picker: LLM boundary, ATR discipline, memory gates (Chinese-first) |

---

## MingCang Naming

As of 0.5.0, public docs, the Pi terminal, installer, launcher, MCP tool examples, and remote-agent configuration use **MingCang / 明仓** naming consistently. The transition compatibility entrypoints have been removed; new installs and local launch flows use `mingcang`.

- The whole research model was rebuilt into a case-based research-to-decision loop (research → signal → position → review → memory);
- Positioning shifted to "amplify human judgment, gated by forward evidence," adding thesis-import channels and a falsification scoreboard;
- A ready-to-use `mingcang` Pi terminal shell was added to lower the barrier to entry;
- A/HK/US read-only global data was expanded, with stronger data-quality and price-adjustment guards.

---

## Disclaimer

MingCang is a personal research tool, **not financial advice**. It doesn't place trades automatically. LLMs don't predict prices. Take-profit and stop-loss levels are generated from ATR formulas and risk constraints. All trading decisions and financial risk belong to the user.

---

## Where this is heading

In one line: **let AI amplify your judgment instead of guessing for you.** That splits into two tracks — how the research works, and making the tool easier to use.

**On research, a few principles:**

- **The judgment that actually makes money comes from people, not a model guessing.** The core is still you, plus researchers and proven frameworks you trust (prosperity, financial quality). MingCang's job is to watch those judgments, find holes, and warn you — not to "read tea leaves" from price action, a path we backtested and found has no edge.
- **AI does just two things: widen breadth and poke holes.** Breadth means surfacing news and leads one person can't cover — always as "unverified guesses." Poking holes means challenging your assumptions, tracking invalidation conditions, and alarming before a loss.
- **AI is welcome to get smarter, but it has to prove it with outcomes.** Any new model or capability may try, but it must prove itself on real results before it can influence your decisions; until then, the final call is always yours.
- **Only outcome-verified lessons are remembered.** Whether a judgment was right is settled only after the outcome lands and the review passes — never recorded as truth just because it "sounds reasonable."

**On the tool, what's coming next:**

- **Hong Kong and US markets.** A-shares are the main battleground today; HK/US are still read-only research context. Next we make them a full research → track → review pipeline like A-shares.
- **Polished frontend and backend.** Make the research console, signal views, and review records smoother to use, and the backend more stable, faster, and easier to maintain.
- **A genuinely usable piece of software.** The goal is a one-click, ready-to-use install that non-coders can run — not just a set of developer scripts.
