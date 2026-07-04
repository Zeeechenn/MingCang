# MingCang · LLM-Powered A-Share AI Research Workbench

> **Every day, AI gives you signals, news sentiment, stop-loss/take-profit, and reviews — runs locally, no data upload.**
> And more than that — **every research call, signal, position, and review is distilled into a growing, layered research memory (L0–L4) that sharpens your next decision.**

**MingCang is a local-first personal A-share research operating system**: you own alpha and the final call, AI handles breadth sweeps and falsification, and the system turns judgments and outcomes into memory that grows over time.

[![Docs](https://img.shields.io/badge/%F0%9F%93%96_Docs-mingcang.docs-ffd400?labelColor=07070d)](https://zeeechenn.github.io/MingCang/)
[![CI](https://github.com/Zeeechenn/MingCang/actions/workflows/test.yml/badge.svg)](https://github.com/Zeeechenn/MingCang/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/Zeeechenn/MingCang?logo=github&color=success)](https://github.com/Zeeechenn/MingCang/releases)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-22c55e)
![Agent](https://img.shields.io/badge/agent--ready-Pi%20%7C%20Claude%20Code%20%7C%20Codex%20%7C%20Cursor-8957e5)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue)

**📖 Online docs**: <https://zeeechenn.github.io/MingCang/>

**Language**: [简体中文](README.md) · [English](README_EN.md)

---

## Case study: how one loss became a rule

MingCang runs research as a loop: judgment → signal → position → review → memory. Here is one complete paper-trading record.

**CATL (300750) · 2026-05 · paper trading**

| Step | Record |
|---|---|
| Entry | 05-14 @ 449.38, stop 395.57 |
| Hold | signal kept weakening; no "signal-reversal exit" rule existed, position held |
| Exit | 05-25 @ 411.28, loss −8.48% |
| Review | root cause: missing signal-reversal exit rule |
| Improvement | added a "signal-reversal exit" rule in Test 2 |

Full chain: [CATL live sample](docs_public/ningde_live_sample.md).

## Signal card: daily output example

```
  600584 JCET                                       2026-06-02
  ────────────────────────────────────────────────────────────
  Composite 25.8        Call  🟡 Small starter
  Technical 28.6  ·  Quant 25.8  ·  News sent. +18.0
  Stop 64.66    Target 98.17    (ATR 2.5 trailing)
  ────────────────────────────────────────────────────────────
  rule: aggregate_v1  ·  stays on your box
```

Same day, full batch:

| Code | Name | Composite | Call | Tech | Quant | News sent. | Stop | Target |
|---|---|---:|---|---:|---:|---:|---:|---:|
| 600584 | JCET | **25.8** | 🟡 Small starter | 28.6 | 25.8 | +18.0 | 64.66 | 98.17 |
| 603986 | GigaDevice | 4.3 | 🔵 Watch | 26.4 | 4.5 | −55.2 | 414.86 | 603.09 |
| 300750 | CATL | −1.7 | ⚪ Stand by | −12.5 | 1.3 | +18.0 | 397.42 | 488.68 |

> Tiered calls with ATR stop/target levels; no price predictions, no "buy / guaranteed gains." News sentiment is scored by an LLM reading the day's news.

## MingCang in 30 seconds

- **What it does**: every day it scans the stocks you follow, gives a tiered call (small starter / watch / stand by / avoid), pre-computes stop-loss/target levels, and scores the day's news sentiment; every judgment and outcome gets saved for next time.
- **What it doesn't do**: it doesn't predict price moves, doesn't place orders, and doesn't decide for you — AI only "scans wider and pokes holes," the buy/sell call is always yours.
- **Where your data lives**: everything runs on your own machine; prices/news/positions never leave it. It only reaches the network when you turn on a feature like news search.
- **How to start**: run `make demo` below for a no-install trial; once it clicks, install `mingcang` via [Quick start](#quick-start) for daily use.

## Test 1: paper-trading results

```
  📒 Test 1 · paper-trading final review        2026-05-12 ~ 06-01
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

> 7 trades all closed: 2 winners, 5 stops; stops averaged −5.33% (max −9.20%), position-weighted total +3.79%. Paper-trading replay, not real money, history not rewritten.
>
> Mechanism: see the research-to-decision loop in [Deep dive](#deep-dive) below.

---

## What MingCang helps you do

| You want to... | How MingCang plugs in |
|---|---|
| **Research one stock** | `mingcang stock 000001` pulls signals, news, labels, and the research-copilot shadow conclusion, and records your judgment as a `ResearchCase` |
| **Track a long-term theme/sector** | Import theses from external analysts, institutions, or prosperity frameworks as a `ForwardThesis` with invalidation conditions and a review cadence, tracked over time |
| **Stay on top of daily signals & risk** | Technical factors + LLM news sentiment generate the official signal; ATR trailing stops protect gains; panels show `protective_action`, ATR stop distance, exposure, and data/financial-quality flags |
| **Review and compound experience** | After outcomes land, attribute results; falsification hits/misses are scored; only human-confirmed lessons promote into trusted memory |
| **Let AI do all of the above** | A built-in `mingcang` Pi terminal, plus Claude Code / Codex / Cursor via CLI / MCP |

MingCang never decides for you: **LLMs don't predict prices, don't place orders, and don't silently change signals.** Stops are ATR-derived rules, and memory only promotes after outcomes and human confirmation.

**Under the hood**: local SQLite (prices / news / financials / QFII + A/HK/US read-only global data, never the cloud) · React frontend + REST API · layered memory + auditable logs · `mingcang` Pi terminal / MCP / CLI.

---

> **First-time path:** use `make demo` below if you want a no-key trial; use [Quick start](#quick-start) when you want to install the `mingcang` terminal; use `make install` plus `make dev` / `cd frontend && npm run dev` if you are developing.

## 3-minute demo (no real keys / no provider network)

```bash
git clone https://github.com/Zeeechenn/MingCang.git
cd MingCang
make demo        # seed mock data, then start backend + frontend
```

Open <http://127.0.0.1:5173>. The first screen is the new MingCang terminal: you can ask for stock research, review candidates, watchlist actions, and governance drafts in natural language. The navigation opens the decision pulse, stock dossiers, review dossiers, research copilot, position discipline, source health, and governance console. The demo database also includes sample stocks, a long-term thesis, a review case, and one pending memory-promotion candidate for the full loop in the [User Guide](docs_public/USER_GUIDE.md). The backend health check is at <http://127.0.0.1:8000/health>, and the interactive API docs (Swagger UI) are at <http://127.0.0.1:8000/docs>. Press `Ctrl+C` to stop the demo.

> The demo DB and the real DB are two separate datasets: the demo only has three sample stocks (Kweichow Moutai, Zhongji Innolight, Ping An). Once you switch to a real environment and look up those same tickers, you may get empty signals/labels if they aren't in your own tracked pool — that's expected, just use your own watchlist symbols instead.

![MingCang frontend preview: decision pulse dossier](docs/assets/screenshot-watchlist.png)

Already have a Python environment and want the real commands instead of the demo?

```bash
git clone https://github.com/Zeeechenn/MingCang.git
cd MingCang
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                            # install dependencies
python3 -m backend.agent.cli health --pretty       # health check: DB, deps, permissions
python3 -m backend.tools.m59_panel                 # post-market panel: signals, position health, protective_action, ATR stops, quality flags
```

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

MingCang exposes six release workflows: pre-market read, intraday note, post-market decision, weekend health check, research `<target>`, and opinion intake:

```bash
python3 -m backend.tools.m63_daily --mode premarket|intraday|postmarket
python3 -m backend.tools.m63_weekly --no-llm
python3 -m backend.tools.m63_research --target 300308 --no-llm
python3 -m backend.tools.m63_opinion --text '<opinion text>' --source manual --no-llm
```

In the Pi terminal just say "run the pre-market scan" or "review after close." Signals include the day's suggestion, the ATR trailing-stop level, portfolio exposure, and data-quality alerts — MingCang never places the order, it just enforces discipline.
The post-market panel also renders risk-specific `protective_action`, stop-distance pressure, and financial/data-quality flags so discretionary action stays tied to checkable rules.

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

## Deep dive

Everything above covers daily use. This section is for readers who want to know how it actually runs under the hood — it uses some internal terms; skip it and you can still use the product fine.

### Research-framework analysts + data layer

MingCang **encodes mature research methodologies into reusable analyst modules** that each judge a stock from a different angle, then fuses them:

| Analyst | Methodology source | Looks at |
|---|---|---|
| 📊 **Piotroski F-Score** | classic academic 9 factors | financial quality: profitability / leverage / efficiency |
| 📈 **Prosperity analyst** | Kaiyuan Securities "Prosperity Investing" 7×34 framework | Δ marginal change: acceleration of profit / revenue / ROE |
| 🔗 **Supply-chain analyst** | industry-chain · five-layer framework | tech/hardware sectors: supply-chain check → overseas leading indicators → cyclical vs structural → hype filter → overbought filter |

> Three analysts → weighted blend → **one-veto** fusion → long-term label (Hold-worthy / Overvalued / Stand by / Avoid), **on by default, each toggleable.** A **supply-chain chokepoint research methodology (Serenity)** is ready and **observe-only** (research-observation only — it never feeds a trade or a score, strictly read-only), but disabled by default (`long_term_serenity_enabled=False`) with no production entry point yet — it is not currently rolled out into the long-term label. QFII flow and more frameworks are under evaluation.
>
> Note: this is a **long-term research layer** separate from the **daily signal (plain formula)** — it never changes the daily signal directly. These frameworks are also exposed as **skills / CLI / MCP**, callable from Claude Code / Codex / Cursor.

The signals and judgments above sit on an **audited data foundation**, not raw key reads:

| Capability | What it does |
|---|---|
| 🔀 **Multi-source + auto-fallback** | a provider registry; on failure it switches to a backup source with cooldowns |
| ⏳ **Point-in-Time (PIT)** | backtests read data as-of the decision date — no "cheating" with future data (PIT = only using data that was actually available at that point in time) |
| 🧪 **Quality gates + coverage reports** | price-quality checks, data-coverage and source-reliability reports, auto-alerts on dirty data |
| 🗃️ **Cache & freshness policy** | a declarative contract for when remote data may be fetched |

> No matter how good the signals are, **dirty data makes it all a castle in the air.** This foundation keeps every judgment above standing on reproducible, lookahead-free data.

### Architecture: the research-to-decision loop

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

In plain terms, the four "cases" are: first record "why this is worth studying" (ResearchCase), then judge "is it tradable now" (SignalCase), then after trading record "why hold / when to exit" (PositionCase), then once the outcome lands review "what this taught us" (ReviewCase) — the four link end-to-end into one loop.

### How the pieces fuse together

- **Single-stock research** → the `ResearchCase → SignalCase → PositionCase` path: `mingcang stock <symbol>` gives you the official signal, news, labels, and the research copilot's shadow conclusion in one shot.
- **Long-term / theme research** → lives in **L2 (Thesis)**: external analyst, institutional, and prosperity/financial-framework judgments are imported as a `ForwardThesis` (with invalidation conditions, follow-up metrics, review cadence) and tracked as slow evidence — never a shortcut to a buy score.
- **Where data comes from** → **L1 (Evidence) + the data layer**: A-share prices/financials/QFII, news sentiment, A/HK/US read-only global data, all in local SQLite, never the cloud; a Provider Guard enforces freshness and adjustment-basis sanity.
- **What memory is for** → **L0 + L4**: rules, lessons, and research indexes are stored in layers; only ReviewCase-attributed, human-confirmed outcomes promote from `pending` to trusted, then feed back as context for the next judgment — that's why the loop grows.

> **Status**: this case-based loop has landed but is **dormant by default** — the skeleton comes first with zero production-signal change, activating layer by layer as the forward-evidence gate clears. Production signals remain technical 0.6 + sentiment 0.4 + ATR 2.5 trailing stop; quant stays off pending evidence.

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
| PAPER_TRADING.md | Paper-trading track record entry point (**local-only file**: paper-trading records are personal data and stay out of the public repo; public readers: see the Test 1 / Test 2 sections above) |
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

## License

Current versions of MingCang are licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE): personal research, study, experimentation, and noncommercial organizational use are permitted, along with noncommercial modification and distribution. Unauthorized commercial use, commercial integration, commercial hosting, and resale are not permitted. Contact the maintainer for commercial licensing.

Copies previously received under the MIT License remain governed by the license text that accompanied those copies. The current repository and future versions are no longer released under MIT.

---

## Disclaimer

MingCang is a personal research tool, **not financial advice**. It doesn't place trades automatically. LLMs don't predict prices. Take-profit and stop-loss levels are generated from ATR formulas and risk constraints. All trading decisions and financial risk belong to the user.

---

## Where this is heading

In one line: **let AI amplify your judgment instead of guessing for you.** You and the researchers and proven frameworks you trust make the calls; MingCang watches them, finds holes, runs reviews, and distills verified lessons into memory.

**On research, the principles we hold:**

- **Judgment mainly comes from people and proven frameworks, not a model guessing prices.** The core is you, plus prosperity, financial-quality, and supply-chain frameworks; reading price action like tea leaves is a path we backtested and found has no edge.
- **AI does just two things: widen breadth and poke holes.** Breadth means surfacing news and leads one person can't cover — always as "unverified guesses." Poking holes means challenging your assumptions, tracking invalidation conditions, and alarming before a loss.
- **A new capability must prove itself on real results before it influences decisions.** This is also the current reality: the full research loop (L0–L4, see [Deep dive](#deep-dive)) has landed but is dormant by default, with the quant layer off; any stronger signal or model must first clear forward-evidence gates (IC / ICIR — statistical measures of whether a signal actually had predictive power historically, independent samples, data quality) and your confirmation before it activates, layer by layer. Until then, production signals use a plain formula (technical 0.6 + sentiment 0.4 + ATR trailing stop).
- **Only outcome-verified lessons are remembered.** Whether a judgment was right is settled only after the outcome lands and the review passes — never recorded as truth just because it "sounds reasonable."

**On the tool, what's coming next:**

- **Activate the loop layer by layer, on forward evidence.** Keep accruing paper-trading and forward samples; verify a layer, then open it — not all at once.
- **Hong Kong and US markets.** A-shares are the main battleground today; HK/US are still read-only research context. Next we make them a full research → track → review pipeline like A-shares.
- **A polished frontend/backend and a genuinely usable tool.** A one-click, ready-to-use install non-coders can run — not just a set of developer scripts.
