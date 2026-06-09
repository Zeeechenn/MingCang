# MingCang — Project Index

个人 A 股研究循环工作台。核心目标不是造一个更聪明的 AI，而是建立一个可审计的判断循环：进口假设 → 证伪 → 归因 → 记忆更新。

Alpha 来自人的判断；AI 负责广度扫描、证伪和短期风险纪律；最终决策始终由用户负责。

**核心约束**：止盈止损由 ATR 公式计算；默认用 ATR 2.5 移动止损保护浮盈；LLM 不做价格预测，不做自动交易；记忆促进需要 outcome 结果和人工确认。

---

## 快速导航

| 文件 | 何时读取 |
|------|------|
| [AGENTS.md](AGENTS.md) | 默认 agent 规则、任务路由和安全边界 |
| [STATUS.md](STATUS.md) | 当前状态、生产权重、验证快照和下一步入口 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 当前/未来工作，使用 M-numbered 结构 |
| [CHANGELOG.md](CHANGELOG.md) | 版本、历史变更、历史验证记录；不要默认读取 |
| [README.md](README.md) | GitHub 门面、安装、配置和公开说明 |
| [docs/ATLAS_MERGE.md](docs/ATLAS_MERGE.md) | Atlas dormant merge 的详细核验记录 |
| [docs/dev/](docs/dev/) | 历史实验、旧计划、维护者参考；按名称需要时再读 |

---

## Agent-Ready Boundary

MingCang can be used as regular software and as an agent-ready codebase. Public
agent instructions belong in `AGENTS.md`; private local notes, generated
reports, runtime databases and personal trading records stay outside Git
tracking.

---

## 里程碑总览

- M0-M28: closed historical buildout; details live in `CHANGELOG.md`.
- M29: active read-only alpha-reset / forward-evidence work; no promotion yet.
- M30: completed engineering-quality convergence.
- M31: completed cache / provider fallback / rhythm CLI / postmarket exports.
- M32: planned forward-hypothesis bridge.
- M41: completed read-only A/HK/US global data/research facade.
- M42: completed qfq/hfq contamination guard and dry-run remediation.
- M43: completed architecture boundary hardening.
- M44: completed dormant Atlas L0-L4 merge; Atlas/test4 Stage 2b signal-overlay shadow starter exists; `ATLAS_ENABLED=false`.
- M45: completed amplifier-primary, source-gated research-positioning tools.
- M46: completed user discoverability and first-run documentation cleanup.
- M47-M48: completed evidence-trust CLI/API visibility and frontend reliability.
- M49: completed tools registry / CLI observability and request correlation tracing.

Current production conclusion: quant remains disabled
(`WEIGHT_QUANT=0.0`), Kronos remains off, and M29 evidence is still
non-promoting.

---

## Repository Map

Use this as a navigation map, not a full file inventory. For symbol-level
questions, use CodeGraph first; for literal strings, use `rg`.

| Area | Path | Notes |
|---|---|---|
| Runtime config | `backend/config.py` | env vars, paths, scheduling, profile knobs |
| Database/runtime schema | `backend/data/database.py`, `backend/data/schema_runtime.py`, `backend/data/seed.py` | ORM/session/init compatibility, runtime patches, memory seeds |
| Market data | `backend/data/market*.py`, `backend/data/providers.py`, `backend/data/global_data.py` | A/HK/US read-only facades, provider fallback, M41 envelopes, M42 write guard |
| Decision layer | `backend/decision/` | aggregation, harness, signal policy, decision memory |
| Research and memory | `backend/research/`, `backend/memory/`, `backend/agents/` | dossier/deep research, layered memory, multi-agent pipelines |
| Portfolio and risk | `backend/portfolio/`, `backend/ops/kill_switch.py` | sizing, trailing stops, kill switch |
| API routes | `backend/api/routes/`, `backend/api/schemas.py`, `backend/main.py` | FastAPI app and REST surfaces |
| Scheduler jobs | `backend/scheduler.py`, `backend/jobs/` | premarket / intraday / postmarket / weekend workflows |
| Agent bridge | `backend/agent/` | local CLI, action registry, MCP/tool context |
| Analysis and backtests | `backend/analysis/`, `backend/backtest/`, `backend/tools/m29_*`, `backend/tools/atlas_test4_stage2b_shadow.py` | quant engine, statistics, forward-evidence tooling, Atlas/test4 non-promoting shadow starter |
| Tools registry | `backend/tools/registry.py`, `python3 -m backend.agent.cli tools` | M49 classification for retained tools: stable / maintenance / evidence / attic, with purpose and read/write boundaries |
| M31/M41/M42/M45 tools | `backend/tools/m31_*`, `backend/tools/m41_*`, `backend/tools/m42_*`, `backend/tools/m45_*` | cache benchmark, probe health, qfq/hfq remediation, source-gated import/scoreboard |
| Frontend | `frontend/src/pages/`, `frontend/src/components/` | dashboard pages and evidence/review components |
| Public docs | `README.md`, `docs/WHY_NOT_AI_STOCK_PICKER.md`, `docs/assets/` | GitHub-facing product explanation and visuals |
