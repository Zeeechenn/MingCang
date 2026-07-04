# M59 裁量层四条硬规则 — 实现规格(2026-07-05)

> 依据:60 票双模型盲裁(证据 `paper_trading/m61_out/adjudication_h1_expansion_20260705.json`)。
> 病根:系统"诊断对、动作错"。四条规则把纪律写死进面板与 copilot。
> 红线:面板保持只读 DB;不改官方信号/止损/持仓写路径;规则版只**提示与标记**,不改写生产数据。

## R1 风险识别 → 保护动作强制映射

- `backend/tools/m59_panel.py`:`_build_risk_warnings` 与 `_build_event_warnings` 产出的每条 item 增加
  `protective_action` 字段(str):具体动作建议,格式如 `减仓至X%` / `止损上移至Y(=现价-1.5×ATR14)` / `观察触发:收盘跌破Z即减半`。
  - 规则版生成逻辑(确定性,无 LLM):
    - 事件类警示(解禁/减持):`protective_action = "事件日前评估减仓;若持仓,止损上移至 max(现止损, 现价-1.5×ATR14)"`(数值实算)。
    - 风险类警示(动量降级/集中度超限):给出对应的减仓百分比建议(沿用现有 regime 降级/集中度阈值,写明数字)。
  - 若某条警示无法生成动作(缺价格/ATR 数据),必须显式 `protective_action = "数据不足,无法给出动作(缺:xxx)"`,禁止字段缺省。
- `render_markdown`:警示区每条后追加 `→ 动作: {protective_action}`。
- 汇总区 `_build_summary`:统计 `action_missing_count`(protective_action 以"数据不足"开头的条数),进人话摘要。

## R2 触发条件必须可观测、快周期

- `backend/research/copilot.py` `_SYSTEM_PROMPT` 追加硬规则文本(中文):
  「任何『等待/观察』类结论必须附带可独立观测的触发条件(具体价格位/均线/已公告的公开事件),
  禁止把内部标签更新、下季财报披露作为唯一触发。」
- copilot 输出卡 schema 增加可选字段 `reentry_trigger`(str);`_parse` 后校验:若 `stance` 为观望/等待类
  且 `reentry_trigger` 缺失或含"标签/财报"字样而无价格/事件触发,则在卡上标记 `trigger_quality: "degraded"`
  (新增字段,默认 "ok"),不拦截输出。
- `m59_panel.py` 持仓体检 item:已有 `distance_to_stop_loss_pct`;新增 `reentry_hint`(对空仓候选不适用,仅
  跟进候选区/观察哨确认卡透传,若上游无则省略——本条面板侧只做透传,不造数据)。

## R3 止损校准纪律

- `m59_panel.py` `_build_position_health`:对每个持仓实算 ATR14(复用 `_price_series`,14 日 TR 均值;
  数据不足 15 行则标 `atr: null`)。新增字段:
  - `atr14`、`stop_gap_atr`(=(现价-止损)/ATR14,保留 2 位)。
  - `stop_flags`(list):
    - `stop_gap_atr < 1.5` → `"止损贴身(<1.5×ATR,易被正常波动洗出)"`;
    - `take_profit` 非空 且 20 日涨幅 > 15%(动量态)→ `"动量股用静态止盈位,建议改ATR追踪"`。
- `render_markdown` 持仓体检表增列 `止损/ATR`;`stop_flags` 非空在行尾标注。
- `_build_summary`:`tight_stop_count` 进人话摘要。
- copilot `_SYSTEM_PROMPT` 追加:「给出的初始止损不得小于 1.5×ATR14;20日涨幅>15% 的动量股止盈必须用
  ATR 追踪表述,禁止静态目标价一刀切。」

## R4 仓位 × 财务质量

- `m59_panel.py`:新增 `_quality_flags(db_session, symbol) -> list[str]`,读 `financial_metrics` 最新一期 +
  Piotroski 明细(复用 `_piotroski_display` 的数据来源):
  - `cfo_gt_ni == False` → `"CFO<净利"`;
  - `current_ratio < 1` → `"流动比率<1"`;
  - `gross_margin < 10` → `"毛利率过薄"`。
- 买入候选区(`_build_buy_candidates`)与持仓体检 item 增加 `quality_flags` 字段;候选区 markdown 渲染:
  flags 非空追加 `⚠质量: {flags} → 建议仓位上限减半`。
- copilot `_SYSTEM_PROMPT` 追加:「存在 CFO<净利、流动比率<1、毛利率异常任一项时,建议仓位必须显式下调并说明。」

## 测试(新增 tests/test_m59_rules.py,fixtures 参照 tests/test_m61_p3_*.py 造库方式)

1. R1:造一条解禁事件警示 → item 含 `protective_action` 且含实算数字;缺价格数据 → 字段为"数据不足"文案。
2. R3:持仓 stop_gap_atr=1.0 → `stop_flags` 含"止损贴身";=2.0 → 无该 flag;20日+20% 且有静态止盈 → 含追踪提示。
3. R4:cfo_gt_ni=False → `quality_flags` 含 "CFO<净利";候选区 markdown 含 "建议仓位上限减半"。
4. R2:`_SYSTEM_PROMPT` 文本包含四条规则关键词(断言子串);观望卡缺 `reentry_trigger` → `trigger_quality=="degraded"`。
5. 全量回归:`PYTHONPATH=. .venv/bin/python -m pytest tests -q` 全绿。

## 验收

- 实跑 `PYTHONPATH=. python3 -m backend.tools.m59_panel`(只读)生成一份真实面板,确认新字段/渲染出现且无异常。
- 不 git commit——leader 审 diff 后统一提交。
