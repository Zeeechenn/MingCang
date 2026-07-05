# 明仓

本地优先的股票研究工作台。把自选、行情、新闻、官方信号、AI 研究、长期论题、复盘和记忆，放进同一个**可审计**的研究流程。

[开始使用 →](USER_GUIDE.md){ .md-button .md-button--primary }
[功能地图](FEATURE_MAP.md){ .md-button }
[在 GitHub 查看](https://github.com/Zeeechenn/MingCang){ .md-button }

## 快速安装

=== "体验 demo"

    ```bash
    make demo
    ```

    启动后打开浏览器：

    ```text
    http://127.0.0.1:5173
    ```

=== "安装命令行"

    ```bash
    curl -fsSL https://raw.githubusercontent.com/Zeeechenn/MingCang/main/scripts/install.sh | sh
    mingcang
    ```

=== "最快路径"

    ```bash
    mingcang doctor
    mingcang stock 300308
    mingcang project
    python3 -m backend.tools.m63_daily --mode postmarket
    ```

## 快速链接

<div class="grid cards" markdown>

-   :material-rocket-launch-outline:{ .lg .middle } &nbsp; __快速开始__

    ---

    跑 demo、研究第一只股票、建立每日使用节奏。

    [:octicons-arrow-right-24: 阅读指南](USER_GUIDE.md)

-   :material-map-outline:{ .lg .middle } &nbsp; __功能地图__

    ---

    查看全部功能、入口、状态、写入边界、信号影响和 key 要求。

    [:octicons-arrow-right-24: 浏览功能](FEATURE_MAP.md)

-   :material-shield-check-outline:{ .lg .middle } &nbsp; __安全边界__

    ---

    理解明仓为什么不做自动荐股和自动交易。

    [:octicons-arrow-right-24: 了解边界](WHY_NOT_AI_STOCK_PICKER.md)

-   :material-graph-outline:{ .lg .middle } &nbsp; __架构__

    ---

    研究闭环、证据对象、复盘和记忆促进模型。

    [:octicons-arrow-right-24: 看架构](ARCHITECTURE.md)

-   :material-book-open-variant:{ .lg .middle } &nbsp; __参考手册__

    ---

    前端页面、后端 API、CLI、action registry 和配置项。

    [:octicons-arrow-right-24: 查手册](REFERENCE.md)

-   :material-code-tags:{ .lg .middle } &nbsp; __开发指南__

    ---

    后续开发和扩展功能时阅读。

    [:octicons-arrow-right-24: 开始开发](DEVELOPER_GUIDE.md)

</div>

## 明仓是什么？

明仓**不是** AI 荐股器，也**不是**自动交易系统。它不接券商，不自动下单，不让 LLM 替你买卖。

它更像一个研究操作台：把每只股票的价格、新闻、官方信号、长期论题、AI 研究、复盘记录和记忆上下文放在一起，让你能看清——一次判断来自哪里、哪些内容只是影子研究、哪些动作会写入本地状态。

## 核心功能

<div class="grid cards" markdown>

-   __单股研究__

    ---

    聚合官方信号、新闻、长期标签、research copilot 和记忆上下文。

-   __每日扫描__

    ---

    M63 六命令按盘前看、盘中记、盘后决、周末体检、随时研究、喂观点组织日常节奏。

-   __盘后操作面板__

    ---

    买入候选 + 持仓体检 + 风险警示→保护动作 + 财务质量旗标，面板只读、LLM 做裁量不打分。

-   __LLM 研究__

    ---

    用于资料整理、反方质询、风险提示和候选动作生成，不覆盖官方信号。

-   __长期论题__

    ---

    记录外部判断、失效条件、跟踪指标和复盘节奏。

-   __复盘记忆__

    ---

    通过 ReviewCase 归因，再由人工确认升级可信记忆。

-   __风控纪律__

    ---

    ATR、trailing stop、仓位上限、组合暴露和 kill switch。

-   __数据系统__

    ---

    行情、新闻、财务、QFII、provider 健康和只读 global data。

-   __量化验证__

    ---

    Qlib、Kronos、回测和 shadow evidence；当前不进正式信号。

</div>

## 核心边界

| 边界 | 行为 |
|---|---|
| 官方信号 | 规则系统输出，当前主要由技术、情绪和风控组成。 |
| LLM 研究 | 负责整理、反问、辩论和风险提示；默认不覆盖官方信号。 |
| 量化系统 | 当前是验证和影子证据路径，不进正式信号。 |
| 写入动作 | 自选、持仓、配置、记忆等高风险动作必须显式确认。 |
| 交易执行 | 不接券商，不自动下单。 |
