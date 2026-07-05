"""M63 tool wiring disposition registry."""

from __future__ import annotations

from typing import Literal, TypedDict

Bucket = Literal[
    "daily_premarket",
    "daily_intraday",
    "daily_postmarket",
    "research",
    "weekly",
    "trigger",
    "manual_only",
]


class WiringEntry(TypedDict):
    bucket: Bucket
    reason: str


WIRING_MAP: dict[str, WiringEntry] = {
    "backend.tools.coverage_snapshot": {"bucket": "daily_postmarket", "reason": "日常数据覆盖快照"},
    "backend.tools.check_sensitive_paths": {"bucket": "manual_only", "reason": "提交前敏感路径检查,人工触发"},
    "backend.tools.gate_b_tracker": {"bucket": "manual_only", "reason": "Gate-B观察台账,验收/研究时人工触发"},
    "backend.tools.long_term_constraint_impact": {"bucket": "daily_postmarket", "reason": "长期标签与日信号约束影响读数"},
    "backend.tools.m59_panel": {"bucket": "daily_postmarket", "reason": "盘后核心面板"},
    "backend.tools.m59_discretion": {"bucket": "daily_postmarket", "reason": "盘后LLM裁量参考层,灰度开关控制"},
    "backend.tools.m52_flow_floor": {"bucket": "daily_postmarket", "reason": "资金流融合库函数,由日常评分/面板间接使用"},
    "backend.tools.m61_backfill": {"bucket": "daily_postmarket", "reason": "盘后滴灌补数为主,深研也会调用"},
    "backend.tools.m63_render": {"bucket": "manual_only", "reason": "M63渲染库本体,由其他M63工具调用"},
    "backend.tools.m63_daily": {"bucket": "daily_postmarket", "reason": "M63盘前/盘中/盘后主入口;主接线按盘后"},
    "backend.tools.m63_research": {"bucket": "research", "reason": "随时式深研入口"},
    "backend.tools.m63_opinion": {"bucket": "trigger", "reason": "喂观点生成R4触发队列"},
    "backend.tools.m63_weekly": {"bucket": "weekly", "reason": "固定式周末体检入口"},
    "backend.tools.m63_wiring": {"bucket": "manual_only", "reason": "接线登记表本体"},
    "backend.tools.m61_source_health": {"bucket": "manual_only", "reason": "数据源验收打分卡,证据类人工触发"},
    "backend.tools.blind_adjudication": {"bucket": "manual_only", "reason": "验收类盲裁,人工触发"},
    "backend.tools.m61_quant_features": {"bucket": "manual_only", "reason": "量化证据库函数,实验人工触发"},
    "backend.tools.m61_quant_walkforward": {"bucket": "manual_only", "reason": "量化walk-forward实验,人工触发"},
    "backend.tools.m61_judgment_gate": {"bucket": "manual_only", "reason": "判断门验收实验,人工触发"},
    "backend.tools.m60_watchtower": {"bucket": "daily_intraday", "reason": "盘中/盘后观察哨触发源"},
    "backend.tools.m60_second_entry": {"bucket": "daily_postmarket", "reason": "M60第二时间入场影子台账,盘后只读累计"},
    "backend.tools.m60_thesis_sync": {"bucket": "manual_only", "reason": "M60 watchlist thesis 到 ForwardThesis 的维护同步,人工触发"},
    "backend.tools.m31_cache_benchmark": {"bucket": "manual_only", "reason": "缓存基准测试,人工诊断触发"},
    "backend.tools.m41_probe_health_ledger": {"bucket": "manual_only", "reason": "探针健康台账,维护/验收人工触发"},
    "backend.tools.m54_content_probe": {"bucket": "manual_only", "reason": "新闻内容可行性探针,证据类人工触发"},
    "backend.tools.m54_content_backfill": {"bucket": "manual_only", "reason": "历史内容回填,维护人工触发"},
    "backend.tools.m54_news_v2_oos": {"bucket": "manual_only", "reason": "新闻层OOS实验,人工触发"},
    "backend.tools.m54_daily_accrual": {"bucket": "daily_postmarket", "reason": "盘后accrual前向累计"},
    "backend.tools.backfill_coverage": {"bucket": "manual_only", "reason": "覆盖率维护回填,人工触发"},
    "backend.tools.m26_expand_universe": {"bucket": "manual_only", "reason": "训练池扩展维护,人工确认触发"},
    "backend.tools.m27_build_test3_universe": {"bucket": "manual_only", "reason": "test3 universe构建维护,人工触发"},
    "backend.tools.m27_kronos_finetune_data": {"bucket": "manual_only", "reason": "Kronos训练数据准备,人工触发"},
    "backend.tools.m27_kronos_path_a_launch": {"bucket": "manual_only", "reason": "Kronos训练/启动计划,人工确认触发"},
    "backend.tools.m27_sentiment_cache_backfill": {"bucket": "manual_only", "reason": "情感缓存回填,维护人工触发"},
    "backend.tools.m27_sentiment_cache_batch_runner": {"bucket": "manual_only", "reason": "情感缓存批跑,维护人工触发"},
    "backend.tools.m27_sentiment_cache_plan": {"bucket": "manual_only", "reason": "情感缓存计划生成,维护人工触发"},
    "backend.tools.m29_price_coverage_refresh": {"bucket": "manual_only", "reason": "价格覆盖刷新,维护人工触发"},
    "backend.tools.m42_remediate_hfq_contamination": {"bucket": "manual_only", "reason": "价格污染修复,维护人工确认触发"},
    "backend.tools.m58_remediate_adjustment_splice": {"bucket": "manual_only", "reason": "复权拼接修复,维护人工确认触发"},
    "backend.tools.m45_track_hook_update": {"bucket": "manual_only", "reason": "M45 track hook导入,维护人工触发"},
    "backend.tools.m45_falsification_scoreboard": {"bucket": "manual_only", "reason": "M45证伪记分牌,维护人工触发"},
    "backend.tools.m45_import_track_theses": {"bucket": "manual_only", "reason": "M45 thesis导入,维护人工触发"},
    "backend.tools.atlas_test4_stage2b_shadow": {"bucket": "manual_only", "reason": "Atlas影子证据实验,人工触发"},
    "backend.tools.atlas_stage2b_strict_gate": {"bucket": "manual_only", "reason": "Atlas严格门验收,人工触发"},
    "backend.tools.m26_kronos_eval": {"bucket": "manual_only", "reason": "Kronos评估实验,人工触发"},
    "backend.tools.m26_quant_baseline": {"bucket": "manual_only", "reason": "量化baseline证据报告,人工触发"},
    "backend.tools.m58_grid_backtest": {"bucket": "manual_only", "reason": "M58参数网格回测,人工触发"},
    "backend.tools.m58_exit_sweep": {"bucket": "manual_only", "reason": "M58出场参数扫描,人工触发"},
    "backend.tools.m58_exit_shadow": {"bucket": "daily_postmarket", "reason": "盘后影子出场只读对照"},
    "backend.tools.m58_lgbm_walkforward": {"bucket": "manual_only", "reason": "LGBM walk-forward证据实验,人工触发"},
    "backend.tools.m27_alpha_diagnostic": {"bucket": "manual_only", "reason": "alpha诊断实验,人工触发"},
    "backend.tools.m27_kronos_preflight": {"bucket": "manual_only", "reason": "Kronos训练前检查,人工触发"},
    "backend.tools.m27_label_objective_eval": {"bucket": "manual_only", "reason": "标签目标评估实验,人工触发"},
    "backend.tools.m27_test3_production_profile_ab": {"bucket": "manual_only", "reason": "test3生产画像A/B诊断,人工触发"},
    "backend.tools.m27_top_decile_filter_ab": {"bucket": "manual_only", "reason": "top-decile过滤A/B诊断,人工触发"},
    "backend.tools.m27_top_decile_forward_shadow": {"bucket": "manual_only", "reason": "top-decile前向影子实验,人工触发"},
    "backend.tools.m29_evidence_ledger": {"bucket": "manual_only", "reason": "M29证据台账,人工触发"},
    "backend.tools.m29_forward_readiness": {"bucket": "manual_only", "reason": "M29前向准备检查,人工触发"},
    "backend.tools.m29_hypothesis_registry": {"bucket": "manual_only", "reason": "M29假设注册,人工触发"},
    "backend.tools.m29_provenance_audit": {"bucket": "manual_only", "reason": "M29来源审计,人工触发"},
    "backend.tools.m29_quant_residual_attribution": {"bucket": "manual_only", "reason": "M29残差归因实验,人工触发"},
    "backend.tools.m29_shadow_validation": {"bucket": "manual_only", "reason": "M29影子验证,人工触发"},
    "backend.tools.m46_5_lookahead_one_time_audit": {"bucket": "manual_only", "reason": "一次性lookahead审计,人工触发"},
    "backend.tools.attic.backfill_and_run": {"bucket": "manual_only", "reason": "attic归档脚本,不接日常自动线"},
    "backend.tools.attic.rerun_failed_6": {"bucket": "manual_only", "reason": "attic归档脚本,不接日常自动线"},
}
