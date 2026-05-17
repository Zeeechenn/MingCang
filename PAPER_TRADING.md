# 纸上交易索引

测试详情已拆分到 `paper_trading/`。本文件只保留索引和当前快照，避免长文件继续膨胀。

- `paper_trading/test1.md`：测试 1 原始规则、持仓和每日信号日志。
- `paper_trading/test2.md`：测试 2 启动前计划与检查。
- `paper_trading/watchlist.md`：中长期关注池。
- `paper_trading/results.md`：测试结果汇总。

当前硬规则：测试 1 期间不修改 `paper_trading/test1.md` 中“测试 1 规则”段落。

## 当前快照（2026-05-16）

- 测试 1：进行中（2026-05-13 ~ 05-20，1 周），**含 5 日强平规则**。持仓与每日信号见 `paper_trading/test1.md`。
- 测试 2：**两个月强测试**（2026-05-21 ~ 2026-07-21），**无 5 日强平**。规则与启动 checklist 见 `paper_trading/test2.md`。
- 5 日强平规则**仅测试 1 适用**：A 股 5 个交易日（跳周末与节假日），不是 5 个自然日。
- 生产代码不强制时间退出（`time_exit_enabled=False`，`max_hold_days=10` 仅在显式开启时生效）。
- 生产信号语言：`可小仓试错 / 可关注 / 观望 / 规避`。
- 生产仓位默认：单股 15%，单板块 30%，总权益 80%，新信号试错仓 5%。
