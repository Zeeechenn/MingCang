from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent.parent


@dataclass(frozen=True)
class SignalWeights:
    quant: float
    technical: float
    sentiment: float
    entry_threshold: float
    profile: str
    use_multi_agent: bool


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        validate_assignment=True,
    )

    # LLM 提供方（"anthropic" 或 "openai"）
    ai_provider: str = "anthropic"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model_fast: str = "claude-haiku-4-5-20251001"
    anthropic_model_capable: str = "claude-sonnet-4-6"

    # OpenAI / 兼容接口（DeepSeek、Moonshot、Azure 等）
    openai_api_key: str = ""
    openai_base_url: str = ""   # 留空使用 OpenAI 官方地址
    openai_model_fast: str = "gpt-4o-mini"
    openai_model_capable: str = "gpt-4o"
    local_cli_model_fast: str = "claude-haiku-4-5-20251001"
    local_cli_model_capable: str = "claude-sonnet-4-6"

    database_url: str = f"sqlite:///{BASE_DIR}/stock-sage.db"
    schedule_premarket: str = "08:30"
    schedule_postmarket: str = "16:00"
    tushare_token: str = ""
    tickflow_enabled: bool = False
    tickflow_api_key: str = ""
    tickflow_base_url: str = "https://api.tickflow.org"
    tickflow_timeout_seconds: float = 10.0
    log_level: str = "INFO"

    # Signal weights (must sum to 1.0)
    # 阶段A Qlib 有效性硬验证结论：IC=0.0228 / ICIR=0.062 / 分层非单调 → Qlib 不合格
    # 默认改为「技术 60% + 情感 40%」，weight_quant 归零。
    # Qlib 通过 RD-Agent 升级后可在 .env 中重新分配权重。
    weight_quant: float = 0.0
    weight_technical: float = 0.6
    weight_sentiment: float = 0.4
    new_framework_entry_threshold: float = 25.0

    # Signal profile: legacy Qlib framework or current new framework.
    paper_trading_profile: str = "auto"  # auto / test1_legacy_qlib / new_framework
    test1_start_date: str = "2026-05-13"
    test1_end_date: str = "2026-05-17"
    test1_multi_agent_enabled: bool = False
    test1_weight_quant: float = 0.45
    test1_weight_technical: float = 0.40
    test1_weight_sentiment: float = 0.15
    test1_entry_threshold: float = 20.0

    # Stop loss / take profit
    # 阶段B 参数扫描（8方案）后的最终默认：max_hold=10d 单点提升 Sharpe +0.16，
    # 其余"改进"（ADX 过滤、trailing 1.5×ATR、RR=1.5）单独或叠加都拖累 Sharpe。
    # 全部可通过 .env 覆盖，便于验证后再调参。
    atr_period: int = 14
    atr_multiplier: float = 2.0
    risk_reward_ratio: float = 2.0            # 固定止盈参考线仍按 1:2 RR 展示
    take_profit_exit_enabled: bool = False    # 默认不因固定止盈强平；作为提醒/分批决策参考
    time_exit_enabled: bool = False           # 实盘/持仓跟踪不做硬强平；回测实验可开启
    max_hold_days: int = 10                   # 仅在 time_exit_enabled=True 时作为评估窗口
    trailing_stop_enabled: bool = True        # 默认启用 ATR 移动止损保护趋势浮盈
    trailing_atr_mult: float = 2.5            # M4.9 exit sweep 推荐值（1.5 过紧）

    # 阶段A 大盘/板块择时过滤
    # 默认开启，但 dampen_factor 设为 0.7（不彻底归零）以保留学习空间
    regime_filter_enabled: bool = True
    rsrs_window: int = 18
    rsrs_lookback: int = 600
    rsrs_bearish_z: float = -0.7
    diffusion_threshold: float = 0.3
    regime_dampen_factor: float = 0.7

    # 阶段B ADX 震荡市过滤
    # 默认关闭：参数扫描显示 ADX 过滤减少入场但每笔质量未提升，Sharpe -0.18
    # 验证后如发现震荡市连环亏损可再启用
    adx_filter_enabled: bool = False
    adx_threshold: float = 20.0

    # 阶段B 综合分 → 仓位映射（每只股最大权重）
    position_sizing_enabled: bool = True
    max_position_per_stock: float = 0.15      # 单股最大仓位
    max_position_per_sector: float = 0.30     # 单板块最大仓位
    max_total_equity_pct: float = 0.80        # 股票总仓位上限
    new_signal_trial_pct: float = 0.05        # 新信号试错仓

    # 阶段C 多 Agent 决策。
    # 日常/批量产信号默认关闭以控制 token；单股研究、长期团、深度研究等手动研究入口可显式开启。
    multi_agent_enabled: bool = False
    risk_manager_enabled: bool = True         # 风险经理对最终建议有否决权
    layered_memory_enabled: bool = True       # FinMem 风格分层记忆

    # M4.1 多轮辩论（bull→bear反驳→bull回应→裁定）
    # 在 multi_agent_enabled=True 时生效，仅分歧 >= min_divergence 时触发
    multi_round_debate_enabled: bool = True
    multi_round_debate_min_divergence: float = 20.0   # 分析师分数标准差阈值
    multi_round_debate_max_rounds: int = 3            # 最多 3 轮（bull/bear/bull-final）

    # M4.2 Research Director（评估分析师报告质量 + 下达辩论议题）
    research_director_enabled: bool = True
    director_min_confidence: float = 0.25     # 平均置信度低于此值发出"数据不足"警告

    # M4.3 Portfolio Manager（组合层仓位统筹）
    portfolio_manager_enabled: bool = True

    # 长期分析师团 first batch（周频运行）
    long_term_team_enabled: bool = True
    long_term_a_teacher_enabled: bool = True
    long_term_piotroski_enabled: bool = True
    long_term_jingqi_enabled: bool = True
    long_term_a_teacher_weight: float = 0.3
    long_term_piotroski_weight: float = 0.3
    long_term_jingqi_weight: float = 0.4
    piotroski_strong_threshold: int = 7
    piotroski_weak_threshold: int = 4
    jingqi_strong_pctile: float = 0.70
    jingqi_weak_pctile: float = 0.30
    long_term_label_ttl_days: int = 10
    long_term_label_mirror_path: str = ""
    long_term_avoid_blocks_buy: bool = True
    long_term_overvalued_position_factor: float = 0.5
    long_term_watch_score_cap: float = 30.0
    long_term_max_llm_calls_per_week: int = 60   # 熔断
    financial_backfill_years: int = 5

    # QFII Outflow 反向规避分析师（2026-05-15）
    # 仅做反向规避，不做正向加分。原因详见 PROJECT.md「QFII Outflow 反向规避」段。
    # 通过一票否决机制发挥作用，weight 设小以免反噬正向分。
    long_term_qfii_flow_enabled: bool = True
    long_term_qfii_flow_weight: float = 0.1
    qfii_flow_lookback_quarters: int = 4          # 回看几个季度
    qfii_flow_min_holders: int = 2                # 至少多少家不同 QFII 同时减仓
    qfii_flow_min_drop_quarters: int = 2          # 单家最长连续减仓季度
    qfii_flow_drop_ratio: float = 0.20            # 累计净减仓占历史峰值比例阈值
    schedule_longterm_dow: str = "sun"
    schedule_longterm_time: str = "11:00"
    schedule_daily_review_time: str = "15:00"
    schedule_longterm_monday_dow: str = "mon"
    schedule_longterm_monday_time: str = "09:00"
    schedule_longterm_friday_dow: str = "fri"
    schedule_longterm_friday_time: str = "15:00"

    # Kronos (optional, requires CUDA GPU)
    kronos_enabled: bool = False          # 设为 True 后需有 GPU 且已安装 Kronos 依赖
    kronos_model: str = "NeoQuasar/Kronos-small"
    kronos_pred_len: int = 5              # 预测未来几个交易日
    kronos_weight_in_quant: float = 0.4  # Kronos 在量化信号层内的权重（其余归 Qlib）

    # Tavily Search API（补充实时新闻；配置 key 后每轮信号都会补充）
    tavily_api_key: str = ""             # 填入你的 Tavily API Key
    tavily_supplement_threshold: int = 3  # DB新闻 < 此值时先触发 Anspire 严格补缺

    # Anspire Search API（严格补缺：只补事件型新闻，不补行情/F10/资料页）
    anspire_api_key: str = ""             # 填入你的 Anspire API Key
    anspire_news_days: int = 2            # 短线新闻搜索窗口
    anspire_news_max_results: int = 5     # 每股最多读取的搜索结果
    anspire_news_max_add: int = 2         # 每股最多补入情感分析的标题
    anspire_news_min_score: int = 75      # Anspire 来源进入情感链路的最低审计分

    # Bark 推送通知（可选，iOS App）
    bark_key: str = ""                    # Bark App 设备密钥
    bark_server: str = "https://api.day.app"  # 自建 Bark 服务时可替换

    # 调度器开关（false = 手动触发，不自动跑定时任务）
    scheduler_enabled: bool = False

    # Agent local/remote guardrails. Local desktop use is trusted; remote writes
    # require an API key, explicit write enablement, and optional action allowlist.
    stocksage_agent_mode: str = "local"
    stocksage_agent_api_key: str = ""
    stocksage_agent_remote_write_enabled: bool = False
    stocksage_agent_remote_write_actions: str = ""

    @model_validator(mode="after")
    def _validate_runtime_invariants(self):
        for prefix in ("", "test1_"):
            values = [
                getattr(self, f"{prefix}weight_quant"),
                getattr(self, f"{prefix}weight_technical"),
                getattr(self, f"{prefix}weight_sentiment"),
            ]
            if any(v < 0 or v > 1 for v in values):
                raise ValueError(f"{prefix or 'default '}signal weights must be in [0, 1]")
            if abs(sum(values) - 1.0) > 1e-6:
                raise ValueError(f"{prefix or 'default '}signal weights must sum to 1.0")
        for key in ("max_position_per_stock", "max_position_per_sector", "max_total_equity_pct"):
            value = getattr(self, key)
            if value < 0 or value > 1:
                raise ValueError(f"{key} must be in [0, 1]")
        return self


settings = Settings()


def _parse_date(value: str) -> date:
    """Parse an ISO date string to a date object."""
    return date.fromisoformat(value)


def active_signal_weights(as_of: date | None = None) -> SignalWeights:
    """
    返回当前信号融合权重。

    Legacy profile keeps Qlib enabled. Production default uses new_framework,
    where Qlib weight is 0.
    """
    current = as_of or date.today()
    profile = settings.paper_trading_profile
    if profile == "auto":
        start = _parse_date(settings.test1_start_date)
        end = _parse_date(settings.test1_end_date)
        profile = "test1_legacy_qlib" if start <= current <= end else "new_framework"

    if profile == "test1_legacy_qlib":
        return SignalWeights(
            quant=settings.test1_weight_quant,
            technical=settings.test1_weight_technical,
            sentiment=settings.test1_weight_sentiment,
            entry_threshold=settings.test1_entry_threshold,
            profile=profile,
            use_multi_agent=settings.test1_multi_agent_enabled,
        )

    return SignalWeights(
        quant=settings.weight_quant,
        technical=settings.weight_technical,
        sentiment=settings.weight_sentiment,
        entry_threshold=settings.new_framework_entry_threshold,
        profile="new_framework",
        use_multi_agent=settings.multi_agent_enabled,
    )
