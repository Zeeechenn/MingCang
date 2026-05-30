# M28 调研模块整合执行计划

## 1. 总体判断

项目已有完整的深度研究基础设施（deep_research / copilot / dossier / researcher），问题不在于缺模块，而在于三个内部缺陷导致研究质量偏低：

1. **信息源闭环**：evaluator/planner 的 `web_search` action 已声明但 execute 层未实现通用 Web 检索；Tavily 只作新闻 fallback
2. **辩论无信息差**：`multi_round_debate` 的 bull/bear 论据来自同一批量化分数，LLM 无差异信息可辩
3. **三模块割裂**：copilot 的 `validation_questions` 生成后无下游；dossier 的 `missing` 不触发补全

**不接入 Claude Financial Plugin**：该插件是 Cowork/Claude Code 插件（markdown+JSON），运行在 Claude 会话层；项目是调用 Claude API 的 Python 后端，两者架构层不同，无接口可对接。但可借鉴其 IC Memo 结构化 schema。

本计划不改变项目核心边界：LLM 不预测价格，不自动交易；deep_research 只服务手动专题研究，不接入日常信号路径。

---

## 2. 根因与改造映射

| 根因 | 受影响模块 | 改造动作 |
|---|---|---|
| Tavily web_search 分支空实现 | `deep_research.py::_execute_plan` | M28.2 补全执行逻辑 |
| ResearchSection 纯文本无结构 | `research/agents.py` | M28.1 升级为 IC Memo schema |
| bull/bear 论据同源 | `agents/researcher.py` | M28.3 注入结构化 research_context |
| copilot 问题无下游 | `research/copilot.py` + `deep_research.py` | M28.4 建立信息流 |
| dossier 不触发补全 | `research/dossier.py` | M28.4 暴露 pending_questions |

---

## 3. 详细设计

### 3.1 M28.1 ResearchSection IC Memo Schema

**M28.1 文件**：`backend/research/agents.py`

当前 `ResearchSection` 只有 `role / title / content` 三个字段（自由文本），LLM 无法在结构层引用催化剂或风险条目。

借鉴 Anthropic equity-research plugin 的 IC Memo 结构，扩展如下：

```python
@dataclass(frozen=True)
class ResearchSection:
    role: str
    title: str
    content: str                          # 保留，向后兼容
    catalysts: tuple[str, ...] = ()       # 正面催化剂
    risks: tuple[str, ...] = ()           # 风险条目
    valuation_anchor: str = ""            # 估值锚（PE/PB 区间或历史分位）
    evidence_snippets: tuple[str, ...] = ()  # 摘要级证据（含来源标注）
    stance: str = ""                      # 偏多 / 中性 / 偏空
    confidence: float = 0.5              # 来源数量/质量派生，0.0–1.0
```

注：dataclass frozen=True 要求用 tuple 而非 list。

各 builder 填充策略：

| Builder | catalysts | risks | valuation_anchor | stance |
|---|---|---|---|---|
| `_sector_researcher` | 产业景气 / 政策催化 / 订单兑现 | 估值拥挤 / 景气反转 | 行业均值 PE | 由 topic 上下文判断 |
| `_company_researcher` | ROE 改善 / 价格趋势 | 财务恶化 / 下跌趋势 | 个股 PE/PB | 由 change_20d + ROE |
| `_risk_reviewer` | （不填）| 来源/数据风险标记 | （不填）| 偏空（如有硬风险） |
| `_source_auditor` | （不填）| （不填）| （不填）| 中性 |
| `_research_writer` | 汇总正面证据 | 汇总负面证据 | 综合估值区间 | 综合判断 |

`_render_report` 在每个 section 后追加结构化字段 block（仅当字段非空时显示）。

---

### 3.2 M28.2 Tavily 实时 Web 搜索

**M28.2 文件**：`backend/research/deep_research.py`

当前 `EvidenceEvaluation.next_action` 已有 `"web_search"` 选项，`_execute_plan` 里只处理了 anspire / tavily（走 `_fetch_tavily_news`），通用搜索路径从未被执行。

新增纯内存搜索函数：

```python
def _tavily_web_search(
    queries: list[str],
    *,
    max_results_per_query: int = 5,
) -> list[dict]:
    """调用 Tavily search API，返回纯内存结果列表，不写 DB。"""
    ...
    # 返回 [{title, url, snippet, published_date, source="tavily_web"}]
```

`_execute_plan` 增加分支：

```python
elif action == "web_search":
    queries = plan.get("search_queries", [topic])
    results = _tavily_web_search(queries[:3])
    # 注入当次 local_news，标记 source="tavily_web"
```

`_render_report` 对 `source="tavily_web"` 条目展示来源 URL（Markdown 链接格式）。

保留不动：`_fetch_tavily_news`（走 DB 的股票新闻抓取）、`_fetch_external_news` 逻辑。

---

### 3.3 M28.3 辩论注入结构化信息差

**M28.3 文件**：`backend/agents/researcher.py`、`backend/agents/pipeline.py`

新增参数（向后兼容，默认 None）：

```python
def multi_round_debate(
    reports: list[AnalystReport],
    llm_arbitration: dict | None = None,
    *,
    research_context: dict | None = None,   # 新增
) -> ResearcherConclusion:
```

`research_context` 结构：

```python
{
    "catalysts": ["催化剂1", "催化剂2"],
    "risks": ["风险1", "风险2"],
    "evidence_snippets": ["某事件摘要（来源：XX）", ...],
    "stance": "偏多",        # 来自 deep_research writer section
    "confidence": 0.7,
}
```

prompt 注入策略：

- **bull 轮**：在 system prompt 中附加 `catalysts` + evidence_snippets 中正面条目
- **bear 轮**：在 system prompt 中附加 `risks` + evidence_snippets 中负面条目
- **adjudicator 轮**：两组证据均可见，要求裁定时引用具体条目

`pipeline.py` 调用位置：在触发 `multi_round_debate` 前，查询 `memory_rows` 中最新 `research_pointer` 类型的记忆，提取其 `evidence.sections` 的 writer 字段，构造 `research_context` 传入。

---

### 3.4 M28.4 copilot → deep_research 信息流

**M28.4 文件**：`backend/research/copilot.py`、`backend/research/deep_research.py`、`backend/research/dossier.py`

#### copilot 侧
`validation_questions` 已写入 ResearchState JSON blob（字段路径：`research_state["copilot"]["validation_questions"]`）。无需改 DB schema，只需在 dossier 读取时显式提取。

#### deep_research 侧
```python
def run_deep_research(
    ...
    seed_queries: list[str] | None = None,   # 新增
) -> DeepResearchReport:
```

若 `seed_queries` 非空，在首轮 evaluator 评估前直接执行 `_tavily_web_search(seed_queries)`，结果注入初始 `local_news`，再进入闭环。

CLI 新增参数：

```bash
python3 -m backend.research.deep_research \
  --topic "AI算力" --symbols 300308 \
  --seed-queries "AI算力订单兑现,光模块库存周期,英伟达H20出货"
```

#### dossier 侧
`build_research_dossier` 返回新增字段：

```python
"pending_questions": research_state.get("copilot", {}).get("validation_questions", []),
```

`missing` 字段新增条件：`if pending_questions: missing.append("pending_questions")`

---

## 4. 边界约束

| 约束 | 说明 |
|---|---|
| 所有新参数默认 None / 空 | 不破坏现有 CLI / API / scheduler 调用路径 |
| `_fetch_tavily_news` 保留 | 走 DB 的新闻抓取路径不变 |
| deep_research 不接入日常信号 | M8 约束：不创建 Signal，不接入 job_postmarket |
| research_context 为 None 时辩论行为不变 | quick_consensus / debate 路径完全不受影响 |
| ResearchSection 新字段用 tuple | frozen dataclass 不支持 list；builder 内部用 list 再转 tuple |

---

## 5. 实现顺序建议

```
M28.1（agents.py 结构化）
  ↓ 有了结构化字段才能填充 catalysts/risks
M28.2（Tavily web_search 补全）
  ↓ 有了实时搜索才能产生有意义的 evidence_snippets
M28.3（辩论注入）
  ↓ 依赖 M28.1 的 ResearchSection + M28.2 的 research_context 来源
M28.4（copilot 信息流）
  最后做；seed_queries 依赖 M28.2 的搜索基础设施
```
