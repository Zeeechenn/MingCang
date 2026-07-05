# 明仓架构：研究决策闭环

0.3.0 把整套研究模型重做成一套**案卷式闭环架构**：用四类"案卷"（Case）把研究、信号、持仓、复盘串成一条闭环，分五层（L0–L4）承载，每一类只回答一个问题，彼此可链接、可审计。

![明仓 研究决策闭环架构](assets/architecture.svg)

```
进口（数据 + 新闻 + 你的判断 + 外部论题）
        │
        ▼
  ResearchCase ──▶ SignalCase ──▶ PositionCase ──▶ ReviewCase
   为什么值得研究    现在能交易吗     为何持有/何时退      结果教会了什么
        ▲                                                  │
        └────────── 记忆更新（outcome-gated，人工确认）◀────┘
```

## 五层架构（L0–L4）

| 层 | 名字 | 回答的问题 | 边界 |
|---|---|---|---|
| **L0** | 记忆 / 知识库 | 我以前学到过什么？ | 用户规则、复盘教训、研究记忆；LLM 产出默认 `pending`，不能自己变成可信记忆 |
| **L1** | 证据层 | 有哪些可靠证据？ | 带来源/时间/PIT/质量的证据卡，只打包不打分 |
| **L2** | 论题层 | 这值得研究吗？ | `ResearchCase`、`ForwardThesis`、主题假设；只是研究态，不覆盖官方动作 |
| **L3** | 信号 / 持仓层 | 现在能交易吗？怎么进出？ | `SignalCase` / `PositionCase`；提案与影子输出，不直接动真实仓位 |
| **L4** | 复盘 / 促进 / 校准层 | 结果教会了什么？ | `ReviewCase` 归因 → 记忆促进候选；可信促进仍需本地人工确认 |

## 各层怎么融合到一起

- **个股研究** → 走 `ResearchCase → SignalCase → PositionCase` 这条单票线：`mingcang stock <代码>` 一次性给你官方信号、新闻、标签和研究 copilot 的影子结论。
- **长期 / 主题研究** → 落在 **L2 论题层**：外部研究员、机构、景气/财务框架的判断进口成 `ForwardThesis`（带失效条件、跟进指标、复盘节奏），作为慢证据长期跟踪，不直接抬买入分。
- **数据从哪来** → **L1 证据 + 数据层**：A 股行情/财务/QFII、新闻情感、A/HK/US 只读全球数据，全部落本地 SQLite，不上云；Provider Guard 做新鲜度和复权口径护栏。
- **记忆有什么用** → **L0 + L4**：规则、教训、研究索引分层存储；只有经过 ReviewCase 归因 + 人工确认的结果才会从 `pending` 升级为可信记忆，再作为上下文注入下一次判断——这就是闭环为什么"会成长"。

## 当前状态

价格系选股打分经全量网格（695 支 × 966 日）证伪：选股位无统计可辩护优势（DSR=0.0 / p=1.0），价格系打分此问永久关闭。因此明仓不追短线 alpha，转为**研究驱动集中持仓 + 纪律执行 + AI 增强判断**：

- **官方信号**仍展示技术 0.6 + 情感 0.4 的综合分与 ATR 2.5× 移动止损，但不作为可辩护的选股 alpha 宣传。
- **现役操作闭环**（见 [Feature Map](FEATURE_MAP.md) §16）：论点触发（左侧入场时机）+ M60 观察哨（右侧异动检测）+ M59 盘后面板 / LLM 裁量层（默认关，灰度）+ 人工确认 + ATR 出场纪律。
- **L0–L4 案卷基础设施保留**并承载 M57 记忆自进化 Phase 1（Trace/胶囊/Governor，治理需人工复核）；已归档的 ATLAS/M44 综合大分线保持关闭、不驱动任何生产信号。

新闻情感腿、量化 v2、出场影子臂等仍在前向证据门控下积累，未判 GO 前不改生产。

更多信号纪律说明见 [WHY_NOT_AI_STOCK_PICKER.md](WHY_NOT_AI_STOCK_PICKER.md)。

---

## Call-Relation Map

This section traces how a user action in the frontend travels through every
layer of the system, from the browser to the database and back.

```
Browser (React/Vite)
    │  fetch('/api/...')          frontend/src/api.ts createRequestClient
    ▼
FastAPI application              backend/main.py  app = FastAPI(...)
    │  router                    backend/api/routes/__init__.py
    ▼
Route handlers                   backend/api/routes/{signals,stocks,research,...}.py
    │  validate request schema   backend/api/schemas.py (Pydantic models)
    │
    ├── Data layer ─────────────────────────────────────────────────────────
    │       Provider registry    backend/data/providers.py
    │         register_daily_provider / fetch_daily_with_fallback
    │       Market data          backend/data/market.py  (Tushare, TickFlow)
    │       Fundamentals         backend/data/fundamentals.py
    │       News / Sentiment     backend/data/news.py + backend/analysis/sentiment.py
    │       Point-in-Time guard  backend/data/point_in_time.py
    │       SQLAlchemy session   backend/data/session.py → SQLite (DATABASE_URL)
    │
    ├── Decision / Scoring layer ────────────────────────────────────────────
    │       Signal aggregation   backend/decision/aggregator.py
    │         active_signal_weights()  backend/config.py
    │         technical score    backend/analysis/technical.py
    │         sentiment score    backend/analysis/sentiment.py
    │         quant score        backend/analysis/qlib_engine.py  (weight=0 in production)
    │       Stop / take profit   backend/analysis/factors.py  calc_stop_take (ATR 2.5×)
    │       Regime filter        backend/decision/signal_policy.py  + RSRS/diffusion
    │       Decision harness     backend/decision/harness.py  (orchestrates above)
    │
    ├── Memory layer ────────────────────────────────────────────────────────
    │       Layered memory       backend/decision/memory_layered.py
    │         L0 stock memory    backend/memory/stock_memory.py
    │         L0 AI memory       backend/memory/ai_memory.py
    │         L0 research memory backend/memory/research_memory.py
    │       Bias overrides       backend/memory/bias_override.py
    │       Audit log            backend/memory/audit_log.py
    │
    ├── Research / Thesis layer ─────────────────────────────────────────────
    │       Research copilot     backend/research/copilot.py
    │       Deep research        backend/research/deep_research.py
    │       ForwardThesis        backend/data/database.py  ForwardThesis table
    │       ReviewCase / L4      backend/research/review_loop.py
    │       MemoryPromotionCandidates  (human-gated; pending by default)
    │
    └── Agent / Tools layer ──────────────────────────────────────────────────
            Agent CLI            backend/agent/cli.py
              action <name>      backend/agent/action_registry.py  (dry-run / confirm)
              tools              backend/tools/registry.py  (static governance list)
            Security guard       backend/agent/security.py
              local mode:        trusted (no key)
              remote mode:       requires MINGCANG_AGENT_API_KEY + optional allowlist
            MCP bridge           backend/agent/mcp_server.py  (stdio, opt-in)
```

### Key Design Decisions Visible in the Map

**Provider fallback chain**: `fetch_daily_with_fallback` tries providers in
priority order.  A custom provider can be injected at any priority without
touching the rest of the chain.  See `examples/provider_plugin/` for a
minimal example and `CONTRIBUTING_GUIDE.md` for full instructions.

**Signal weights are config, not code**: `active_signal_weights()` reads
`backend/config.py` (overridable via `.env`).  The current production values
are `technical=0.6, sentiment=0.4, quant=0.0`.  The quant layer is
architecturally wired in but its weight is zero; see `EVIDENCE.md` for why.

**Memory is gated, not auto-trusted**: `MemoryPromotionCandidate` rows have
`source_trust="pending"` by default.  They become active only after explicit
human confirmation — there is no code path that promotes them automatically.

**Agent actions follow dry-run / confirm**: the CLI runs any action in
preview mode by default; `--confirm` is required to write.  Remote mode
additionally requires an API key and optional action allowlist
(`MINGCANG_AGENT_REMOTE_WRITE_ACTIONS`).
