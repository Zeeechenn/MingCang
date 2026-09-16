# ResearchReportGate — retained contract (legacy M50 path)

Updated 2026-09-17. Gate/shared definitions and the deep-research pre-write hook
exist; the original “Phase 0 / zero code” and uncompleted implementation checklist
are archived. This is a live contract, not a new milestone. Independent Serenity
analyze() is retired; its optional report shape does not imply a running analyzer.
Scope remains observe-only/source-gated/non-promoting; no official signal/risk/
scheduler/test2/weight changes. Methodology reference: `.pi/skills/serenity-chokepoint/SKILL.md`.

## 1. 共享定义（只定义一次，Serenity 与 Gate 同 import）

现有共享实现：`backend/research/research_evidence_defs.py`（共享枚举/词表）。

### 1.1 `SOURCE_TIER`（证据来源等级枚举）

```
primary       # 一手：原始公告/招股书/问询函/电话会记录
official      # 官方：交易所/监管/政府产业数据
filing        # 定期报告：年报/半年报/季报
ir            # 投资者关系：调研纪要、互动易（公司回复≠审计事实）
industry      # 可信行业媒体/产业数据库/海外龙头披露
social_lead   # 社媒/KOL/传闻 —— 仅 lead，不能作唯一证据
```

强度序：`primary > official > filing > ir > industry > social_lead`。

### 1.2 `FORBIDDEN_REPORT_WORDING`（输出文本禁用措辞）

> ⚠️ 与输入侧 `ai_supply_chain_template.FORBIDDEN_TEMPLATE_KEYS` **是两套常量、两种检查**（落实 C1）：
> - `FORBIDDEN_TEMPLATE_KEYS` 查**输入字段名**（buy_score / price_target / position_pct …）。
> - `FORBIDDEN_REPORT_WORDING` 查**最终文本措辞**。
> 同一检查不在两处写。

建议词表（中英）：

```
强烈买入 / 强烈推荐 / 确定上涨 / 必涨 / 火速上车 / 满仓 / 加仓 / 减仓 /
目标价 / 买入价 / 建仓价 / 抄底 / 梭哈 /
strong buy / must rise / guaranteed / load up / price target
```

（实现时用正则/分词，避免误伤"目标价位区间属于压力测试情景"这类引用上下文——出现即 warning，明确荐股式断言才 blocked。）

### 1.3 `pass / warning / blocked` 语义（复用 M46.5 / M47 口径，不新造）

- `pass`：正常输出。
- `warning`：允许输出，但报告文本和持久化 snapshot 必须携带 gate warnings。
- `blocked`：物理上发不出（见 §3 挂点）。

与既有口径一致：warning 不自动影响生产信号；blocked 不自动触发 memory promotion。

---

## 2. Gate 检查项清单

**作用域（S7）：所有 deep research 报告**，以 `DeepResearchReport` + `audits` 为基线；Serenity 字段（若该次跑过结构化器）作可选加严层，**不假设 Serenity 一定跑过**。

下表保留设计约束；具体判定以现有实现及对应反例测试为准（见 §3）。

| 检查 | blocked 条件 | warning 条件 | 基线字段来源 |
|---|---|---|---|
| 来源完整性 | `source_count == 0` 或无任何 `audit.usable` | 有源但全是非直接来源（audit 含 `网传/传闻` risk_flag） | `source_count`、`audits[].usable`、`audits[].risk_flags`、`audits[].news.url/source` |
| 时间线（lookahead） | 任一关键证据日期晚于 `as_of` | 证据粒度只到月/季 | `as_of`、`audits[].news.published_at`、`financials[].report_date` |
| 主题/标的匹配 | 标的行业与论题核心链路明显冲突 | 暴露度不清 | `topic`、`symbols`、（行业需 join Stock.industry） |
| 数据覆盖 | **永不 blocked**（最终决定，见下） | symbols 指定且 prices+financials 全不可用 → warning | `report.symbols` + 从 hook 传入的 `prices[].available`/`financials[].available`（无则回退 sections 代理） |
| 叙事证据 | 只有媒体叙事、无公告/财报/订单（最强证据 = `social_lead`/`industry`） | 弱证据（`weak_source_count`）占比过高 | `audits`、Serenity `evidence_tier`（若有）、`weak_source_count` |
| LLM 越界措辞 | 文本出现荐股式断言（`FORBIDDEN_REPORT_WORDING` 强命中） | 语气过强 | 渲染出的 `text`（render 后、write 前） |
| 复盘闭环 | promotion 候选缺 ReviewCase | ReviewCase 证据不足 | 仅当该路径要创建 memory candidate 时检查；纯报告默认 N/A |

加严层（仅当 Serenity 结构化器跑过）：
- 主题级 `quick_filter_pass == false` → 至少 warning。
- `research_priority_band == 证据不足` 却仍要 promotion → blocked。
- `falsification_questions` 为空 → warning（反方先行未做）。

`SerenityChokepointReport` 的 `quick_filter` **按 chain_layer 分层记录**（见 SKILL.md 第二步）：
schema 用 `quick_filter_by_layer: list[{layer, forced_demand, size_mismatch, no_substitute, outside_voice}]`
+ 派生的主题级 `quick_filter_pass: bool`（取 `scarce_layer` 那层的判定）。Gate 的加严只看主题级布尔；
分层明细供报告展示与"分层错位"洞察，不参与 Gate 阻断逻辑。

---

## 3. 写前挂点与调用方合同

既有 `deep_research` 先构造报告、运行 gate，再决定是否写 Markdown/persist。
blocked 时不 write_text、不 record_decision_run/remember_deep_research、不创建 memory candidate。
warning 允许输出但文本和持久化 snapshot 带 warning；pass 保留原行为。

- 使用 `report.gate_status` / `gate_reasons` 判断 pass/warning/blocked/gate_disabled。
  blocked 的 path 可以是“将写未写”的路径，不能靠 path 非空或 path.exists() 判断 gate。
- 数据覆盖缺失只 warning，不单独 blocked；无 symbols 的纯主题研究跳过此项。
  实际 prices/financials 优先，没传才使用 sections 代理；证据全空仍由来源完整性硬门拦住。
- 可选 Serenity 加严层是类型/显式数据消费，不恢复旧独立分析器，不进入长期标签聚合。
- 具体回归维护 `tests/test_research_report_gate.py`、深研写前门和 Serenity 隔离测试；
  不用旧行号或旧 Phase 清单驱动代码改动，先核对实际函数/测试。

## 4. 验收边界

维护时覆盖来源缺失/不可用、未来证据、越界措辞、warning 可输出、blocked 零写入、
正常输入保持原行为和研究/正式信号隔离。本文不宣称研究结论真实或投资增益。
历史设计取舍/人工预演原文见 `docs/evidence/document_archive_digest.md`，新工作回 ROADMAP。
