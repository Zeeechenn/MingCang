# 明仓 · MingCang

**明仓是一个本地优先的个人 A 股研究决策工作台。** 它把"看好一只票"这件事拆成一条可审计的闭环——**进口判断 → 记录证据 → 证伪 → 跟踪 → 复盘归因 → 记忆更新**——让每一次判断都能被回看、被反驳、被验证，让每一次结果都沉淀成下次能用的证据。

愿景不是做一个更聪明的"预测 AI"，而是给个人投资者一套**研究操作系统**：

- **你** 负责 alpha、行业认知和最终决策；
- **AI** 负责广度扫描、证伪和短期风险纪律；
- **系统** 负责把判断和结果沉淀成一套会成长的记忆。

[![CI](https://github.com/Zeeechenn/MingCang/actions/workflows/test.yml/badge.svg)](https://github.com/Zeeechenn/MingCang/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/Zeeechenn/MingCang?logo=github&color=success)](https://github.com/Zeeechenn/MingCang/releases)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-22c55e)
![Agent](https://img.shields.io/badge/agent--ready-Pi%20%7C%20Claude%20Code%20%7C%20Codex%20%7C%20Cursor-8957e5)
![License](https://img.shields.io/badge/license-MIT-blue)

**语言**：[简体中文](README.md) · [English](README_EN.md)

---

## 这个项目能帮你做什么

| 你想做的事 | 明仓怎么接 |
|---|---|
| **研究一只票** | `mingcang stock 000001` 拉出信号、新闻、标签、研究 copilot 影子结论，并把你的判断记成一条 `ResearchCase` |
| **跟踪一个长期主题/赛道** | 把外部研究员（如 A 老师）、机构、景气框架的论题进口为 `ForwardThesis`，带失效条件和复盘节奏，长期持续跟踪 |
| **盯住每天的信号和风险** | 技术因子 + LLM 新闻情感生成官方信号，ATR 移动止损保护浮盈，组合暴露和数据质量自动预警 |
| **复盘并积累经验** | 结果出来后做归因，证伪命中/错过都记分，经人工确认才促进成可信记忆，下次判断更有依据 |
| **让 AI 帮你干上面这些** | 自带 `mingcang` Pi 终端，也可接 Claude Code / Codex / Cursor，通过 CLI / MCP 调用全部能力 |

明仓不替你做主：**LLM 不预测价格、不下单、不自动改信号**，止盈止损是 ATR 公式算出来的规则，记忆要等结果和人工确认才升级。

---

## 核心理念：AI 做什么，人做什么

Alpha 来自人的判断——你的研究、行业认知、过滤和否决权。AI 不是主角，它只负责三件你一个人盯不过来的事：

| 角色 | 负责方 | 具体是什么 |
|---|---|---|
| Alpha / 方向 | **你** | 你的研究、直觉、行业认知 |
| 广度扫描 | AI | 你盯不过来的新闻、信号、关联线索 |
| 证伪 | AI | 反驳假设、检查止损/失效条件是否还成立 |
| 短期风险纪律 | AI + 规则 | ATR 止损、组合暴露、数据质量预警 |
| 最终决策 | **你** | 始终是你 |

---

## 架构：ATLAS L0–L4 研究决策闭环

0.3.0 把整套研究模型重做成 **ATLAS L0–L4 架构**：用四类"案卷"（Case）把研究、信号、持仓、复盘串成一条闭环，每一类只回答一个问题，彼此可链接、可审计。

![明仓 ATLAS 架构](docs/assets/architecture.svg)

```
进口（数据 + 新闻 + 你的判断 + 外部论题）
        │
        ▼
  ResearchCase ──▶ SignalCase ──▶ PositionCase ──▶ ReviewCase
   为什么值得研究    现在能交易吗     为何持有/何时退      结果教会了什么
        ▲                                                  │
        └────────── 记忆更新（outcome-gated，人工确认）◀────┘
```

| 层 | 名字 | 回答的问题 | 边界 |
|---|---|---|---|
| **L0** | 记忆 / 知识库 | 我以前学到过什么？ | 用户规则、复盘教训、研究记忆；LLM 产出默认 `pending`，不能自己变成可信记忆 |
| **L1** | 证据层 | 有哪些可靠证据？ | 带来源/时间/PIT/质量的证据卡，只打包不打分 |
| **L2** | 论题层 | 这值得研究吗？ | `ResearchCase`、`ForwardThesis`、主题假设；只是研究态，不覆盖官方动作 |
| **L3** | 信号 / 持仓层 | 现在能交易吗？怎么进出？ | `SignalCase` / `PositionCase`；提案与影子输出，不直接动真实仓位 |
| **L4** | 复盘 / 促进 / 校准层 | 结果教会了什么？ | `ReviewCase` 归因 → 记忆促进候选；可信促进仍需本地人工确认 |

### 那几样东西怎么融合到一起

- **个股研究** → 走 `ResearchCase → SignalCase → PositionCase` 这条单票线：`mingcang stock <代码>` 一次性给你官方信号、新闻、标签和研究 copilot 的影子结论。
- **长期 / 主题研究** → 落在 **L2 论题层**：外部研究员、机构、景气/财务框架的判断进口成 `ForwardThesis`（带失效条件、跟进指标、复盘节奏），作为慢证据长期跟踪，不直接抬买入分。
- **数据从哪来** → **L1 证据 + 数据层**：A 股行情/财务/QFII、新闻情感、A/HK/US 只读全球数据，全部落本地 SQLite，不上云；Provider Guard 做新鲜度和复权口径护栏。
- **记忆有什么用** → **L0 + L4**：规则、教训、研究索引分层存储；只有经过 ReviewCase 归因 + 人工确认的结果才会从 `pending` 升级为可信记忆，再作为上下文注入下一次判断——这就是闭环为什么"会成长"。

> **现状说明**：ATLAS L0–L4 架构已合入 `main`，但默认 `ATLAS_ENABLED=false` **休眠**——架构骨架先落地、生产信号零改动，等 M29 前向证据门控逐层通过后再激活。当前生产信号仍是技术 0.6 + 情感 0.4 + ATR 2.5 止损，量化 `WEIGHT_QUANT=0.0` 关闭待证据。

---

## 当前能力

| 层 | 做什么 |
|---|---|
| 数据 | 行情、新闻、财务、QFII、A/HK/US 只读全球数据，本地 SQLite，不上云 |
| 信号 | 技术因子 + LLM 新闻情感，生产权重 0.6 / 0.4，ATR 2.5 移动止损 |
| 研究 | 个股 dossier、deep research、假设进口、证伪记分牌、外部研究员 / 机构研究导入 |
| 记忆 | 分层记忆，outcome-gated 促进，审计日志可回溯 |
| Agent | 自带 `mingcang` Pi 终端 + MCP / CLI，供 Claude Code / Codex / Cursor 调用 |
| 界面 | React 前端 + REST API，本地优先 |

---

## 快速开始

明仓自带一个 **`mingcang` Pi 终端壳**——把整套 CLI、记忆、研究流程和安全边界打包成一个开箱即用的 agent 终端，不用记一堆命令就能用。

```bash
curl -fsSL https://raw.githubusercontent.com/Zeeechenn/MingCang/main/scripts/install.sh | sh
mingcang
```

装好后直接对它说人话即可（"看一下 300308"、"扫一遍自选"、"帮我复盘上周的票"），它会自己读项目上下文、跑 CLI、给出研究和风险结论。

手动安装 / 开发模式：

```bash
git clone https://github.com/Zeeechenn/MingCang.git
cd MingCang
make agent-setup   # 准备环境
make agent         # 启动 Pi 终端
```

默认 `AI_PROVIDER=local_cli`，走本机已登录的 Claude CLI，不需要云端 key。也可以直接用底层 CLI：

```bash
python3 -m backend.agent.cli health --pretty
python3 -m backend.agent.cli premarket --pretty
python3 -m backend.agent.cli stock-context 000001 --pretty
```

> 迁移说明：旧 `stocksage` 命令、`stock_sage_*` MCP 工具、`STOCKSAGE_AGENT_*` 环境变量在过渡期仍可用；新安装建议使用 `mingcang`。

---

## 下一步开发计划

明仓正从"造一个量化预测器"转向"放大人的判断、用前向证据守门"。当前路线：

1. **M45 · 放大器为主、源受门控**（进行中）— 把外部研究员/机构的判断结构化进口为论题，给每条论题配证伪记分牌和慢速前向影子证据；AI surfaced 的 alpha 必须先过前向、结果导向的证伪，才能影响真实决策。
2. **M29 · 前向证据门控** — 量化层 `WEIGHT_QUANT=0.0` 持续关闭，只在 IC / ICIR / 单调性 / 非重叠样本全部通过且人工确认后才讨论上生产。
3. **ATLAS L0–L4 逐层激活** — 架构已休眠落地，随门控通过把 `SignalCase` / `PositionCase` / `ReviewCase` 从影子态逐步接入。
4. **M32 · 前向假设桥** — 当复盘数据足够厚，把赛道/主题研究升级成可证伪的前向论题（带时限、证据、失效条件），而不是"强烈推荐"标签。

完整任务序列见 [docs/ROADMAP.md](docs/ROADMAP.md)。

---

## Agent 接入

外层 agent（Pi / Claude Code / Codex / Cursor）接入时，默认只需要：

1. 读 [AGENTS.md](AGENTS.md)——了解本地 / 远程边界
2. 按需加载 `STATUS.md` / `PROJECT.md` / `docs/ROADMAP.md`
3. 写操作先 dry-run，等用户确认

核心 MCP 工具：

| 工具 | 用途 |
|---|---|
| `mingcang_project_context` | 持仓、自选、记忆摘要、配置概况 |
| `mingcang_stock_context` | 单只股票：信号、新闻、标签、copilot shadow |
| `mingcang_memory_snapshot` | 分层记忆、审计日志、记忆促进状态 |
| `mingcang_health` | 数据库、依赖、权限健康检查 |

旧 `stock_sage_*` 工具名保留为兼容别名。

---

## 配置

<details>
<summary><b>本地与远程配置</b></summary>

```env
AI_PROVIDER=local_cli
DATABASE_URL=sqlite:////absolute/path/to/mingcang.db
MINGCANG_AGENT_MODE=local
```

远程暴露是 opt-in，默认只读：

```env
MINGCANG_AGENT_MODE=remote
MINGCANG_AGENT_API_KEY=your_secret_key
MINGCANG_AGENT_REMOTE_WRITE_ENABLED=false
MINGCANG_AGENT_REMOTE_WRITE_ACTIONS=
```

旧 `STOCKSAGE_AGENT_*` 变量名仍可读取，新部署推荐用 `MINGCANG_AGENT_*`。`.env`、数据库、个人交易记录、真实 key 不进 Git。

</details>

---

## 文档索引

| 文件 | 内容 |
|---|---|
| [AGENTS.md](AGENTS.md) | Agent 使用规则和安全边界 |
| [PROJECT.md](PROJECT.md) | 代码库导航和关键文件索引 |
| [docs/ATLAS.md](docs/ATLAS.md) | ATLAS 四类 Case 架构设计与里程碑 |
| [STATUS.md](STATUS.md) | 当前生产状态、信号权重、测试入口 |
| [CHANGELOG.md](CHANGELOG.md) | 版本历史和已完成里程碑 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 进行中和待做任务 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 开发环境和贡献流程 |

---

## 声明

明仓是个人研究工具，**不构成投资建议**。系统不自动下单，LLM 不做价格预测，止盈止损由 ATR 公式和风险约束生成。所有交易决策和资金风险由使用者自行承担。
