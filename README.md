# 明仓 · LLM 驱动的 A 股 AI 研究工作台

> **AI 每天帮你出信号、读新闻情感、算止盈止损、做复盘 —— 数据不上传。**
> 更重要的是，**每一次研究、信号、持仓、复盘都会沉淀进一套会成长的分层研究记忆(L0–L4)，让下一次判断更有依据。**

**明仓是一个本地优先的个人 A 股研究操作系统**：你负责 alpha 与决策，AI 负责广度扫描与证伪，系统负责把判断和结果沉淀成一套会成长的记忆。

[![文档](https://img.shields.io/badge/%F0%9F%93%96_文档-mingcang.docs-ffd400?labelColor=07070d)](https://zeeechenn.github.io/MingCang/)
[![CI](https://github.com/Zeeechenn/MingCang/actions/workflows/test.yml/badge.svg)](https://github.com/Zeeechenn/MingCang/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/Zeeechenn/MingCang?logo=github&color=success)](https://github.com/Zeeechenn/MingCang/releases)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20Vite-22c55e)
![Agent](https://img.shields.io/badge/agent--ready-Pi%20%7C%20Claude%20Code%20%7C%20Codex%20%7C%20Cursor-8957e5)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue)

**📖 在线文档**：<https://zeeechenn.github.io/MingCang/>

**语言**：[简体中文](README.md) · [English](README_EN.md)

---

## 案例：一笔亏损如何沉淀成一条规则

明仓把研究做成一条闭环：判断 → 信号 → 持仓 → 复盘归因 → 记忆更新。下面是一个完整的纸上交易记录。

**宁德时代（300750）· 2026-05 · 纸上交易**

| 步骤 | 记录 |
|---|---|
| 入场 | 05-14 @ 449.38，止损 395.57 |
| 持仓 | 信号持续转弱；当时无"信号反转退出"规则，继续持有 |
| 平仓 | 05-25 @ 411.28，亏损 −8.48% |
| 复盘归因 | 根因：缺少信号反转退出规则 |
| 沉淀改进 | 据此在测试2新增"信号反转退出"规则 |

完整链路见 [宁德活样本](docs_public/ningde_live_sample.md)。

## 信号卡：每日输出示例

```
  600584 长电科技                                   2026-06-02
  ────────────────────────────────────────────────────────────
  综合分 25.8          建议  🟡 可小仓试错
  技术 28.6  ·  量化 25.8  ·  新闻情感 +18.0
  止损 64.66    止盈 98.17    (ATR 2.5 移动止损)
  ────────────────────────────────────────────────────────────
  rule: aggregate_v1  ·  数据不出本机
```

当日批量信号：

| 代码 | 名称 | 综合分 | 建议 | 技术 | 量化 | 新闻情感 | 止损 | 止盈 |
|---|---|---:|---|---:|---:|---:|---:|---:|
| 600584 | 长电科技 | **25.8** | 🟡 可小仓试错 | 28.6 | 25.8 | +18.0 | 64.66 | 98.17 |
| 603986 | 兆易创新 | 4.3 | 🔵 可关注 | 26.4 | 4.5 | −55.2 | 414.86 | 603.09 |
| 300750 | 宁德时代 | −1.7 | ⚪ 观望 | −12.5 | 1.3 | +18.0 | 397.42 | 488.68 |

> 信号给出分档建议与 ATR 止盈止损位，不预测涨跌、不喊"买入/必涨"。新闻情感由 LLM 读取当日新闻打分。

## 30秒看懂明仓

- **它帮你干什么**：每天替你扫一遍关注的股票，给出信号建议（试错/关注/观望/规避）、算好止损止盈价，读当日新闻打情感分；每次判断和结果都会存下来，供下次参考。
- **它不帮你干什么**：不预测涨跌、不自动下单、不替你拍板——AI 只负责"扫描 + 挑毛病"，买卖决定权始终在你自己手上。
- **数据在哪**：全部跑在你自己电脑上，行情/新闻/持仓数据不上传云端；只有主动开启新闻搜索等功能时才会联网查资料。
- **怎么开始**：先跑下面的 `make demo` 免安装体验；觉得有用再走[快速开始](#快速开始)装 `mingcang` 长期用。

## 测试1：纸上交易结果

```
  📒 测试1 · 纸上交易最终复盘                2026-05-12 ~ 06-01
  ────────────────────────────────────────────────────────────
  7 笔全平 · 每笔 20% 仓
  仓位加权合计  +3.79%          7 只合计  +18.94%
  ────────────────────────────────────────────────────────────
  盈利 2 笔    兆易创新 +34.26%   ·   长电科技 +11.33%
  止损 5 笔    平均 −5.33%（最大 −9.20%）

  盈亏比 ≈ 4.3 : 1（均盈 +22.8% / 均亏 −5.3%）
  ────────────────────────────────────────────────────────────
  纸上交易回放 · 非真金白银 · 历史结果不回改
```

> 7 笔全部平仓：2 笔盈利、5 笔止损；止损平均 −5.33%、最大 −9.20%，仓位加权合计 +3.79%。纸上交易回放，非真实下单，历史结果不回改。
>
> 实现机制见 [深入了解](#深入了解) 里的研究决策闭环架构。

---

## 明仓能帮你做什么

| 你想做的事 | 明仓怎么接 |
|---|---|
| **研究一只票** | `mingcang stock 000001` 拉出官方信号、新闻、标签和研究 copilot 影子结论，作为只读研究上下文 |
| **跟踪一个长期主题/赛道** | 把成熟外部研究者、券商/机构、景气与财务质量框架的论题进口为 `ForwardThesis`，带失效条件和复盘节奏，长期持续跟踪 |
| **盯住每天的信号和风险** | 技术因子 + LLM 新闻情感生成官方信号，ATR 移动止损保护浮盈，面板展示 `protective_action`、止损 ATR 距离、组合暴露和数据质量 / 财务质量旗标 |
| **复盘并积累经验** | 结果出来后做归因，证伪命中/错过都记分，经人工确认才促进成可信记忆，下次判断更有依据 |
| **让 AI 帮你干上面这些** | 自带 `mingcang` Pi 终端，也可接 Claude Code / Codex / Cursor，通过 CLI / MCP 调用全部能力 |

明仓不替你做主：**LLM 不预测价格、不下单、不自动改信号**，止盈止损是 ATR 公式算出来的规则，记忆要等结果和人工确认才升级。→ 详见 [为什么明仓不是 AI 选股器](docs/WHY_NOT_AI_STOCK_PICKER.md)

**底层**：本地 SQLite（行情 / 新闻 / 财务 / QFII + A/HK/US 只读全球数据，不上云）· React 前端 + REST API · 分层记忆 + 可回溯审计日志 · `mingcang` Pi 终端 / MCP / CLI。

---

> **第一次只做这个**：想先体验，不配 Key，跑下面的 `make demo`；想长期使用，走 [快速开始](#快速开始) 安装 `mingcang`；想开发，先 `make install` 再 `make dev` / `cd frontend && npm run dev`。

## 3 分钟上手（无需真实 Key / 网络）

```bash
git clone https://github.com/Zeeechenn/MingCang.git
cd MingCang
make demo        # 种子 mock 数据，并启动后端 + 前端
```

打开 <http://127.0.0.1:5173>。首页是新的明仓终端：可以用自然语言发起个股研究、复盘候选、自选动作和治理台草稿；导航可进入今日裁决、个股案卷、复盘案卷、研究副驾驶、持仓纪律、来源健康和治理台。demo 数据库还包含示例股票、长期论题、复盘和待确认记忆候选，供 [User Guide](docs_public/USER_GUIDE.md) 串成完整闭环。后端健康检查在 <http://127.0.0.1:8000/health>，交互式 API 文档（Swagger UI）在 <http://127.0.0.1:8000/docs>。按 `Ctrl+C` 停止 demo。

> demo 库和真实库是两套数据：demo 库只有贵州茅台 / 中际旭创 / 中国平安三只示例股。装好真实环境后再查这几只票，如果它们不在你自己追踪的股票池里，会查不到信号或长期标签（返回为空），这是正常的——换成你自己关注的股票代码即可。

![明仓前端界面预览：今日裁决案卷](docs/assets/screenshot-watchlist.png)

<!-- TODO: 后续可补一段操作 GIF（添加标的→研究卡→证伪→复盘→记忆候选）。 -->

已有 Python 环境、不想走 demo 直接看真实命令？

```bash
git clone https://github.com/Zeeechenn/MingCang.git
cd MingCang
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                            # 装依赖
python3 -m backend.agent.cli health --pretty       # 健康检查：库、依赖、权限
python3 -m backend.tools.m59_panel                 # 盘后面板：信号、持仓健康、protective_action、ATR 止损和质量旗标
```

---

## 快速开始

明仓自带一个 **`mingcang` Pi 终端壳**——把整套 CLI、记忆、研究流程和安全边界打包成一个开箱即用的 agent 终端，不用记一堆命令就能用。只想离线看 demo 时不需要安装它，直接用上面的 `make demo`。

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

默认 `AI_PROVIDER=local_cli`，走本机已登录的本地 CLI，不需要云端 key；demo 模式不需要任何 LLM / 数据源 key。也可以直接用底层 CLI：

```bash
python3 -m backend.agent.cli health --pretty
python3 -m backend.agent.cli premarket --pretty
python3 -m backend.agent.cli stock-context 000001 --pretty
```

---

## 使用指南

装好后，既能对 `mingcang` Pi 终端直接说人话，也能跑底层 CLI。下面是几个最常见的用法。

### 研究某一只股票

对 Pi 终端说："研究一下中际旭创"、"看看 300308 现在怎么样"。它会先拉股票上下文，再给结论：

```bash
mingcang stock 300308
# 或直接用底层 CLI：
python3 -m backend.agent.cli stock-context 300308 --pretty
```

你会拿到：官方信号（买入 / 关注 / 规避）、最近新闻与情感、长期标签、研究 copilot 的影子结论，以及它列出的风险和待验证问题。需要更深的调研时，让它跑一轮 deep research：

```bash
python3 -m backend.agent.cli action research.deep.run \
  --payload-json '{"topic":"光模块 1.6T 需求","symbols":["300308"]}' --pretty
```

### 每天看一遍信号

明仓按交易节奏分了六个工作流入口：盘前看、盘中记、盘后决、周末体检、研究 `<目标>`、喂观点；底层由 4 个模块命令承载，其中 `m63_daily` 通过 3 个 mode 覆盖盘前 / 盘中 / 盘后：

```bash
python3 -m backend.tools.m63_daily --mode premarket|intraday|postmarket
python3 -m backend.tools.m63_weekly --no-llm
python3 -m backend.tools.m63_research --target 300308 --no-llm
python3 -m backend.tools.m63_opinion --text '<观点内容>' --source manual --no-llm
```

Pi 终端里直接说"盘前扫一遍"、"收盘后复盘一下"即可。信号里包含当日建议、ATR 移动止损位、组合暴露和数据质量预警——明仓不替你下单，只给纪律。
盘后面板会同步给出风险对应的 `protective_action`、止损贴身程度和财务 / 数据质量旗标，方便把裁量动作落到可检查规则。
数据任务先查 `docs/data-sources/` 手册。

### 维护一个关注列表

加自选（默认 dry-run，确认后加 `--confirm` 落库）：

```bash
python3 -m backend.agent.cli action watchlist.add \
  --payload-json '{"symbol":"300308","name":"中际旭创","market":"CN"}' --pretty
```

移除用 `watchlist.remove`。之后用 `project-context` 或盘后工作流扫一遍整张自选表。对 Pi 终端说"把中际旭创加进自选"、"扫一遍我的关注列表"也可以。

### 做长期研究并持续跟踪

把一个赛道或主题的判断（来自你自己、成熟研究者或景气/财务框架）记成一条带失效条件的论题，系统会长期跟踪、到点提醒复盘：

```bash
python3 -m backend.agent.cli action long_term.run --payload-json '{"symbol":"300308"}' --pretty
```

它不会因为论题"听起来有道理"就抬高买入分——只有结果兑现、复盘通过，这条判断才会升级成可信记忆，喂给下一次研究。

### 让记忆为你工作

```bash
python3 -m backend.agent.cli memory-snapshot --pretty
```

这里能看到分层记忆、审计日志和记忆促进状态：哪些规则 / 教训已可信，哪些还在待定。可信记忆会在你下次研究同一只票或同一赛道时，自动作为上下文注入。

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

---

## 深入了解

前面几节够日常使用。这一节是给想搞清楚"底下到底怎么跑"的人看的，涉及一些内部术语，第一次看不用死抠，跳过不影响用产品。

### 研究框架分析师团 + 数据底座

明仓把一批**成熟的研究方法论编码成可复用的分析师模块**，各自从不同维度给一只票打长期判断，再加权融合：

| 分析师 | 方法论来源 | 看什么 |
|---|---|---|
| 📊 **Piotroski F-Score** | 经典学术 9 因子 | 财务质量：盈利 / 杠杆 / 经营效率 |
| 📈 **景气分析师** | 开源证券《景气投资方法论》7×34 框架 | Δ 边际变化：利润 / 收入 / ROE 的加速度 |
| 🔗 **赛道供应链分析师** | 产业链景气 · 五层框架 | 科技 / 硬件赛道：供应链核查 → 海外领先指标 → 周期 vs 结构 → 炒作过滤 → 高位过滤 |

> 三路分析师 → 加权综合 → **一票否决**融合 → 长期标签（值得持有 / 估值偏高 / 观望 / 规避），**默认开启、可逐个开关**。**供应链瓶颈分析方法论（Serenity）**已就绪、**observe-only**（只做研究观察，不接入任何交易或打分，纯只读），默认关闭（`long_term_serenity_enabled=False`）、暂无生产入口调用，尚未灰度接入长期标签；QFII 资金流等更多框架持续评估中。
>
> 注意：这是和**每日信号（朴素公式）**分开的**长期研究层**——它给的是赛道与个股的长期判断，不直接改每日信号。这些框架同时暴露为 **skills / CLI / MCP**，可被 `mingcang` 终端或 Claude Code / Codex / Cursor 直接调用。

上面这些信号和判断，站在一层**带审计的数据底座**上，而不是裸读 API key：

| 能力 | 做什么 |
|---|---|
| 🔀 **多源 + 自动回退** | provider 注册表，主源失败按冷却自动切备源 |
| ⏳ **防未来函数（PIT）** | 回测按 as-of 时点取数（PIT = Point-In-Time，只用当时能看到的数据），杜绝用未来数据"作弊" |
| 🧪 **质量门 + 覆盖度报告** | 价格质量校验、数据覆盖与源可靠性报告，脏数据自动预警 |
| 🗃️ **缓存与新鲜度策略** | 声明式缓存契约，控制何时允许走远端 |

> 信号和研究再好，**数据不干净就是空中楼阁**。这层底座让上面每一个判断都站在可复现、无未来污染的数据上。

### 架构：研究决策闭环

0.3.0 把整套研究模型重做成一套**案卷式闭环架构**：用四类"案卷"（Case）把研究、信号、持仓、复盘串成一条闭环，分五层（L0–L4）承载，每一类只回答一个问题，彼此可链接、可审计。

![明仓 研究决策闭环架构](docs/assets/architecture.svg)

```
进口（数据 + 新闻 + 你的判断 + 外部论题）
        │
        ▼
  ResearchCase ──▶ SignalCase ──▶ PositionCase ──▶ ReviewCase
   为什么值得研究    现在能交易吗     为何持有/何时退      结果教会了什么
        ▲                                                  │
        └────────── 记忆更新（outcome-gated，人工确认）◀────┘
```

四类"案卷"（Case）说人话就是：先记下"为什么值得研究"（ResearchCase），再判断"现在能不能交易"（SignalCase），交易后记"为何持有/何时退"（PositionCase），结果出来后复盘"这次教会了什么"（ReviewCase）——首尾相接成一个闭环。五层（L0 记忆 → L1 证据 → L2 论题 → L3 信号/持仓 → L4 复盘/校准）分别承载这几步，彼此可链接、可审计。→ [完整架构说明](docs/ARCHITECTURE.md)

> **现状说明**：这套闭环架构已经落地，但默认**休眠**——骨架先就位、生产信号零改动，等前向证据门控逐层通过后再激活。当前生产信号仍是技术 0.6 + 情感 0.4 + ATR 2.5 移动止损，量化层关闭（`WEIGHT_QUANT=0.0`）、等待证据。

---

## 配置

<details>
<summary><b>本地与远程配置</b></summary>

真实 key 只放本机 `.env` 或部署平台的 secret manager，不要提交到 Git。可以从 `.env.example` 复制一份开始：

```env
AI_PROVIDER=local_cli
DATABASE_URL=sqlite:////absolute/path/to/mingcang.db
MINGCANG_AGENT_MODE=local
```

### API Key 设置

默认本地模式使用 `AI_PROVIDER=local_cli`，优先走本机已登录的 Codex CLI，不需要云端 LLM key。只有启用对应 provider / 功能时，才需要填写下面的 key：

| 变量 | 默认 | 何时填写 | 说明 |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | empty | `AI_PROVIDER=anthropic` | Anthropic Claude 运行时 key；可配 `ANTHROPIC_MODEL_FAST` / `ANTHROPIC_MODEL_CAPABLE`。 |
| `OPENAI_API_KEY` | empty | `AI_PROVIDER=openai` | OpenAI 或兼容接口 key；DeepSeek、Moonshot、通义千问、Azure OpenAI 等兼容服务也走这里。 |
| `OPENAI_BASE_URL` | empty | 使用 OpenAI 兼容网关时 | 留空表示 OpenAI 官方地址；兼容服务填对应 base URL。 |
| `TUSHARE_TOKEN` | empty | 需要 Tushare Pro A 股数据补充时 | 可选行情 provider；`TUSHARE_QFQ_ENABLED=true` 才启用 qfq daily fallback。 |
| `TICKFLOW_API_KEY` | empty | `TICKFLOW_ENABLED=true` | TickFlow 行情 provider key；启用后作为 CN daily 优先来源。 |
| `IFIND_MCP_TOKEN` | empty | `IFIND_MCP_ENABLED=true` | iFinD MCP observe-only 适配器 token；用于显式 probe，不默认写入行情链路。 |
| `TAVILY_API_KEY` | empty | 需要实时新闻/搜索补充时 | DB 新闻不足时可补充 Tavily；阈值由 `TAVILY_SUPPLEMENT_THRESHOLD` 控制。 |
| `ANSPIRE_API_KEY` | empty | deep research 或严格事件新闻抓取 | Anspire 搜索 key；窗口和数量由 `ANSPIRE_NEWS_*` 控制。 |
| `BARK_KEY` | empty | 需要 iOS Bark 推送时 | 可选通知 key；自建服务可改 `BARK_SERVER`。 |
| `MINGCANG_AGENT_API_KEY` | empty | `MINGCANG_AGENT_MODE=remote` | 远程 agent 暴露必须设置；本地 `local` 模式不需要。 |

相关开关和限制：

```env
# 本地 LLM：默认不需要云 key
AI_PROVIDER=local_cli
LOCAL_CLI_PREFER_CODEX=true

# 云 LLM 二选一
# AI_PROVIDER=anthropic
# ANTHROPIC_API_KEY=...
# AI_PROVIDER=openai
# OPENAI_API_KEY=...
# OPENAI_BASE_URL=

# 可选数据/搜索/通知 provider
TUSHARE_TOKEN=
TICKFLOW_ENABLED=false
TICKFLOW_API_KEY=
IFIND_MCP_ENABLED=false
IFIND_MCP_TOKEN=
# TAVILY_API_KEY=
# ANSPIRE_API_KEY=
# BARK_KEY=
```

远程暴露是 opt-in，默认只读：

```env
MINGCANG_AGENT_MODE=remote
MINGCANG_AGENT_API_KEY=your_secret_key
MINGCANG_AGENT_REMOTE_WRITE_ENABLED=false
MINGCANG_AGENT_REMOTE_WRITE_ACTIONS=
```

`.env`、数据库、个人交易记录、真实 key 不进 Git。

</details>

---

## 文档索引

| 文件 | 内容 |
|---|---|
| [docs_public/index.md](docs_public/index.md) | 明仓公开文档首页：推荐导航、最短路径、核心能力 |
| [docs_public/USER_GUIDE.md](docs_public/USER_GUIDE.md) | 使用指南：demo、单股研究、每日扫描、长期论题、复盘记忆 |
| [docs_public/FEATURE_MAP.md](docs_public/FEATURE_MAP.md) | 功能目录：每个功能的说明、入口、状态、写入/信号/Key 边界 |
| [docs_public/DEVELOPER_GUIDE.md](docs_public/DEVELOPER_GUIDE.md) | 后续开发指南：加页面、API、action、研究模块、量化模块 |
| [docs_public/REFERENCE.md](docs_public/REFERENCE.md) | 参考手册：CLI、API、配置和关键文件 |
| [AGENTS.md](AGENTS.md) | Agent 使用规则和安全边界 |
| [PROJECT.md](PROJECT.md) | 代码库导航和关键文件索引 |
| [STATUS.md](STATUS.md) | 当前生产状态、信号权重、测试入口 |
| PAPER_TRADING.md | 纸上交易战绩入口（**本地文件**：纸上交易记录属个人数据不入公开库；公开读者看上方「测试1/测试2」战绩节即可） |
| [CHANGELOG.md](CHANGELOG.md) | 版本历史和已完成更新 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 开发环境和贡献流程 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | L0–L4 层架构、Case 类型、融合逻辑完整说明 |
| [docs/WHY_NOT_AI_STOCK_PICKER.md](docs/WHY_NOT_AI_STOCK_PICKER.md) | 为什么明仓不是 AI 选股器：LLM 边界、ATR 纪律、记忆门控 |

---

## MingCang 命名

0.5.0 起，公开文档、Pi 终端、安装器、launcher、MCP 工具示例和远程 agent 配置统一使用 **明仓 / MingCang** 命名。早期过渡期兼容入口已移除；新安装和本机启动入口只使用 `mingcang`。

- 把整套研究模型重做成案卷式研究决策闭环（研究 → 信号 → 持仓 → 复盘 → 记忆）；
- 定位转向"放大人的判断、用前向证据守门"，新增论题进口通道和证伪记分牌；
- 新增开箱即用的 `mingcang` Pi 终端壳，降低使用门槛；
- 扩展 A/HK/US 只读全球数据，强化数据质量与复权口径护栏。

---

## 许可证

明仓当前版本采用 [PolyForm Noncommercial License 1.0.0](LICENSE)：允许个人研究、学习、实验和非商业组织使用、修改与分发；不允许未经授权的商业使用、商业集成、商业托管或再销售。商业合作或授权请先联系维护者。

早期已经按 MIT License 获取的副本仍以其当时附带的许可文本为准；当前仓库和后续版本不再按 MIT 发布。

---

## 声明

明仓是个人研究工具，**不构成投资建议**。系统不自动下单，LLM 不做价格预测，止盈止损由 ATR 公式和风险约束生成。所有交易决策和资金风险由使用者自行承担。

---

## 未来方向

明仓的愿景，一句话：**让 AI 放大你的判断，而不是替你拍脑袋。** 你和你信得过的研究者、成熟框架负责判断；明仓负责盯住、查漏、复盘，并把验证过的经验沉淀成记忆。

**研究上坚持的原则：**

- **判断主要来自人和成熟框架，不靠模型猜价格。** 主力是你自己，以及景气、财务质量、供应链等框架给出的判断；靠价格走势"算命"这条路回测过，没有效果。
- **AI 只做两件事：扩广度、挑毛病。** 帮你扫到一个人看不过来的线索（永远是待验证的猜想），并替你反驳假设、盯失效条件、在亏损前预警。
- **新能力要先用真实结果证明，才能影响决策。** 这也是当前的实际状态：完整的研究闭环（L0–L4，见[深入了解](#深入了解)）已经落地，但默认休眠、量化层关闭；任何更强的信号或模型，都要先通过前向证据门控（IC / ICIR——衡量一个信号历史上到底有没有预测力的统计指标、独立样本、数据质量），并经你确认，才逐层激活。在那之前，生产信号只用一套朴素公式（技术 0.6 + 情感 0.4 + ATR 移动止损）。
- **只记住被结果验证过的经验。** 一条判断对不对，要等结果出来、复盘通过才算数——不会因为"讲得有道理"就被记成真理。

**工具上，接下来要做的：**

- **用前向证据逐层激活闭环。** 持续积累纸上交易和前向样本，验证一层、打开一层，而不是一次性上线。
- **接入港股和美股。** 现在 A 股是主战场，港 / 美股还是只读研究态；下一步做成和 A 股一样可研究、可跟踪、可复盘的完整链路。
- **打磨前端后端、做成好用的软件。** 让不写代码的人也能一键装好、开箱即用，而不只是一套给开发者的脚本。
