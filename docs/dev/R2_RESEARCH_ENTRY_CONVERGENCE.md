# R2 研究入口收敛设计（leader 草案，待 owner 拍板后派工）

> 背景：操作闭环一期裁决将 R2 降级为发布后 backlog（地图 + R1 论点合流已解决主要混乱，
> 发布前不动结构）。v0.6.1 已发布，本文是解锁后的设计稿。定位=**只收敛入口与文档，
> 不改任何研究逻辑/门/数据写路径**。

## 1. 入口盘点（现状）

| 入口 | 形态 | 现状问题 |
|---|---|---|
| `m63_research --target <代码\|主题>` | CLI，六命令面之一 | 已是设计上的唯一日常入口，无问题 |
| `python3 -m backend.research.deep_research --topic ... --symbols ...` | 模块直调 CLI | 与 m63_research(主题) 功能重叠；README/biaodi1.md 仍教用户直调 |
| `backend/agent/cli stock-context` | agent CLI | 读上下文（只读），与 m63_research(单股) 边界未写清：一个是"看"，一个是"研" |
| `paper_trading/biaodi1_runner.py` | 独立 runner | 买点扫描器，文档里混在"研究"叙述中，实际是信号面不是研究面 |
| 前端研究页（`backend/api/routes/research.py`） | Web | 与 CLI 共用服务层，无冲突，仅需文档定位 |
| a-teacher / serenity / jingqi 等 skill | 助手侧 | 软联动（reference-only）已定调，不在本次范围 |

## 2. 收敛决策（提案）

1. **唯一日常研究入口 = `m63_research`**：单股→dossier+copilot；主题→resolve→深研（已实现，不动代码）。
2. **`deep_research` 直调降级为高级用法**：模块与 CLI 保留（m63_research 内部消费者），
   但从 README/AGENTS.md/biaodi1.md 的用户面示例中移除或标注"高级：直调，绕过 m63 路由与队列登记"。
3. **`stock-context` 与 `m63_research` 边界写进 AGENTS.md 一句话**：
   看（读现有上下文，零成本）用 stock-context；研（产新结论、消耗 LLM）用 m63_research。
4. **`biaodi1_runner` 在文档中归入信号面**，从研究叙述中摘出。
5. 不新增代码路径；唯一可能的代码改动 = deep_research CLI 启动时打一行
   "提示：日常请用 m63_research"（可选，owner 定）。

## 3. 执行清单（owner 批准后派 codex，纯文档 + 一行提示）

- [ ] README（中英）研究节：只保留 m63_research 示例，深研直调移到"高级用法"。
- [ ] AGENTS.md Daily Routing 补"看 vs 研"一句话边界。
- [ ] paper_trading/biaodi1.md："行业深度研究"节改为指向 `m63_research --target <主题>`，直调示例标注高级。
- [ ] （可选）deep_research CLI 入口加提示行。
- [ ] PROJECT.md 研究模块地图行内补"入口：经 m63_research 路由"备注。

## 4. 不做什么（红线）

- 不动 gate-guarded（M39-M55）与 dormant（ATLAS）模块的任何 import/接线。
- 不改研究报告门、论点合流、观察哨消费路径。
- 不删任何 CLI——只调整文档定位，保持向后兼容。
