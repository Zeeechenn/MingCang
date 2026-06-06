# MingCang Docs

明仓是一个本地优先的股票研究循环工作台。它把自选、行情、新闻、官方信号、AI 研究、长期论题、复盘和记忆放进同一个可审计闭环。

> 明仓不自动下单，不接券商，不让 LLM 替你买卖。它帮助你研究、记录、证伪、复盘和沉淀经验。

## 推荐导航

这套导航按明仓自己的实际功能组织，不照搬通用项目模板。

| 导航 | 面向谁 | 进入页面 | 你会学到什么 |
|---|---|---|---|
| 开始使用 | 第一次打开项目的人 | [User Guide](USER_GUIDE.md) | 安装、demo、第一只股票、每日节奏。 |
| 研究工作流 | 普通用户 / 研究者 | [User Guide](USER_GUIDE.md) | 单股研究、每日扫描、长期论题、复盘记忆。 |
| 功能目录 | 想知道明仓全部能力的人 | [Feature Map](FEATURE_MAP.md) | 每个功能是什么、入口在哪、是否写入、是否影响信号。 |
| 前端与后台 | 想理解系统页面和 API 的人 | [Reference](REFERENCE.md) | 前端页面、后端路由、CLI、action、配置项。 |
| 开发者指南 | 后续开发者 | [Developer Guide](DEVELOPER_GUIDE.md) | 如何加页面、API、action、研究模块、量化模块。 |
| 架构 | 想理解闭环模型的人 | [Architecture](ARCHITECTURE.md) | L0-L4、ResearchCase、SignalCase、ReviewCase、记忆促进。 |
| 安全边界 | 想确认“不是 AI 荐股器”的人 | [Why Not AI Stock Picker](WHY_NOT_AI_STOCK_PICKER.md) | LLM、量化、信号、交易边界。 |

## 最短路径

如果你第一次使用，按这个顺序：

1. 跑 demo：

```bash
make demo
```

2. 打开前端：

```text
http://127.0.0.1:5173
```

3. 研究一只股票：

```bash
mingcang stock 300308
```

4. 看完整功能目录：

```text
docs/FEATURE_MAP.md
```

## 核心能力

| 能力 | 一句话说明 |
|---|---|
| 自选和候选池 | 管理关注标的，快速进入单股研究。 |
| 单股研究 | 把价格、信号、新闻、长期标签、copilot 和记忆上下文聚合到一起。 |
| 每日扫描 | 按盘前、盘中、盘后、周末组织研究节奏。 |
| 官方信号 | 技术 0.6 + 情绪 0.4，量化当前为 0。 |
| LLM 研究 | 用 AI 做资料整理、反方质询、风险提示和候选动作生成。 |
| 长期论题 | 把外部判断、失效条件、跟踪指标沉淀成 ForwardThesis。 |
| 复盘记忆 | 用 ReviewCase 归因，再由人工确认升级可信记忆。 |
| 风控纪律 | ATR、trailing stop、仓位上限、组合暴露和 kill switch。 |
| 数据系统 | 行情、新闻、财务、QFII、provider 健康、A/HK/US 只读数据。 |
| 量化验证 | Qlib、Kronos、回测、M29 shadow evidence；当前不进正式信号。 |

## 文档站部署建议

当前内容已经按 GitHub Pages / MkDocs / VitePress 都容易接入的 Markdown 页面组织。公开站点只从 `docs_public/` 构建，内部规划、历史研究记录和开发归档仍留在 `docs/`：

```text
docs_public/
  index.md
  USER_GUIDE.md
  FEATURE_MAP.md
  DEVELOPER_GUIDE.md
  REFERENCE.md
  ARCHITECTURE.md
  WHY_NOT_AI_STOCK_PICKER.md
```

后续如果要真的做成站点，可以选一个轻量方案：

- GitHub Pages：用 GitHub Actions 构建 `docs_public/`。
- MkDocs：用 `mkdocs.yml` 配置左侧导航。
- VitePress：保留 Markdown，额外加 `.vitepress/config`。
