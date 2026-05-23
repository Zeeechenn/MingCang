"""
单元测试：Piotroski F-Score 9 因子计算 + 景气投资 Δ 类指标计算

不依赖网络：用 fixture 直接喂入 FinancialMetric 数据。
"""

from backend.data.database import FinancialMetric
from backend.data.fundamentals import (
    compute_asset_turnover,
    compute_jingqi_deltas,
    compute_piotroski_factors,
    compute_roe,
    list_peers,
)

# ── 数据 helper ───────────────────────────────────────────────────────

def _add_metric(db, symbol, report_date, **kwargs):
    defaults = dict(
        symbol=symbol, report_date=report_date, period_type="Q3",
        revenue=None, revenue_yoy=None, net_profit=None, net_profit_yoy=None,
        total_assets=None, total_equity=None, long_term_debt=None,
        current_ratio=None, operating_cf=None, shares_outstanding=None,
        gross_margin=None, roe=None, asset_turnover=None,
    )
    defaults.update(kwargs)
    m = FinancialMetric(**defaults)
    db.add(m)
    db.commit()
    return m


# ── compute_roe / compute_asset_turnover ──────────────────────────────

def test_compute_roe_basic():
    assert compute_roe(100, 1000) == 10.0
    assert compute_roe(-50, 500) == -10.0


def test_compute_roe_handles_none_and_zero():
    assert compute_roe(None, 1000) is None
    assert compute_roe(100, None) is None
    assert compute_roe(100, 0) is None


def test_compute_asset_turnover():
    assert compute_asset_turnover(1000, 5000) == 0.2
    assert compute_asset_turnover(None, 5000) is None
    assert compute_asset_turnover(1000, 0) is None


def test_disclosure_period_names_cover_q1_and_q3():
    from backend.data.fundamentals import _period_to_report_date

    assert _period_to_report_date(2024, "一季") == "2024-03-31"
    assert _period_to_report_date(2024, "三季") == "2024-09-30"


# ── Piotroski F-Score ─────────────────────────────────────────────────

def test_piotroski_data_insufficient(test_db):
    """无数据 → available=False, score=0"""
    result = compute_piotroski_factors("600519", test_db)
    assert result["available"] is False
    assert result["score"] == 0


def test_piotroski_only_one_period(test_db):
    """只有 1 期 → 不够对比"""
    _add_metric(test_db, "600519", "2024-09-30", net_profit=100, total_assets=1000)
    result = compute_piotroski_factors("600519", test_db)
    assert result["available"] is False


def test_piotroski_perfect_9_factors(test_db):
    """构造满分 9 分公司"""
    # 去年同期（差）
    _add_metric(test_db, "600519", "2023-09-30",
                net_profit=50, total_assets=1000, total_equity=500,
                long_term_debt=200, current_ratio=1.5, shares_outstanding=10000,
                gross_margin=30.0, operating_cf=40,
                asset_turnover=0.5)
    # 当期（全面优于去年）
    _add_metric(test_db, "600519", "2024-09-30",
                net_profit=120, total_assets=1100, total_equity=700,
                long_term_debt=150,  # 长债下降
                current_ratio=2.0,   # 流动比率上升
                shares_outstanding=10000,  # 股本未变
                gross_margin=40.0,   # 毛利率上升
                operating_cf=150,    # CFO > NI (150>120)
                asset_turnover=0.65) # 周转率上升

    result = compute_piotroski_factors("600519", test_db)
    assert result["available"] is True
    assert result["score"] == 9, f"应该满分 9，实际 {result['score']}, factors={result['factors']}"
    assert result["report_period"] == "2024-09-30"
    assert result["comparison_period"] == "2023-09-30"
    for f, v in result["factors"].items():
        assert v is True, f"因子 {f} 应为 True"


def test_piotroski_zero_score_failing_company(test_db):
    """构造极差公司：所有指标恶化"""
    _add_metric(test_db, "600519", "2023-09-30",
                net_profit=100, total_assets=1000, total_equity=500,
                long_term_debt=200, current_ratio=2.0, shares_outstanding=10000,
                gross_margin=40.0, operating_cf=80,
                asset_turnover=0.8)
    _add_metric(test_db, "600519", "2024-09-30",
                net_profit=-50, total_assets=1100, total_equity=400,
                long_term_debt=500,   # 长债飙升
                current_ratio=1.0,    # 流动比率下降
                shares_outstanding=12000,  # 股本扩张
                gross_margin=20.0,    # 毛利率下降
                operating_cf=-80,     # CFO 负
                asset_turnover=0.5)   # 周转率下降

    result = compute_piotroski_factors("600519", test_db)
    assert result["score"] == 0
    assert result["factors"]["roa_positive"] is False
    assert result["factors"]["cfo_positive"] is False


def test_piotroski_finds_correct_comparison_period(test_db):
    """有多期数据时，应找去年同期(同月份)而非最近一期"""
    _add_metric(test_db, "600519", "2024-06-30", net_profit=50, total_assets=1000,
                total_equity=500, long_term_debt=100, current_ratio=1.0,
                shares_outstanding=10000, gross_margin=35, operating_cf=60,
                asset_turnover=0.5)
    _add_metric(test_db, "600519", "2023-09-30", net_profit=80, total_assets=1000,
                total_equity=500, long_term_debt=100, current_ratio=1.0,
                shares_outstanding=10000, gross_margin=35, operating_cf=60,
                asset_turnover=0.5)
    _add_metric(test_db, "600519", "2024-09-30", net_profit=120, total_assets=1000,
                total_equity=500, long_term_debt=100, current_ratio=1.0,
                shares_outstanding=10000, gross_margin=35, operating_cf=60,
                asset_turnover=0.5)
    result = compute_piotroski_factors("600519", test_db)
    assert result["comparison_period"] == "2023-09-30"


# ── 景气投资 jingqi Δ 类指标 ─────────────────────────────────────────

def test_jingqi_data_insufficient(test_db):
    result = compute_jingqi_deltas("600519", test_db)
    assert result["available"] is False


def test_jingqi_delta_calculation(test_db):
    """两期数据，验证 Δ 计算"""
    _add_metric(test_db, "600519", "2024-06-30",
                net_profit_yoy=10.0, revenue_yoy=5.0, roe=12.0)
    _add_metric(test_db, "600519", "2024-09-30",
                net_profit_yoy=30.0, revenue_yoy=15.0, roe=15.5)

    result = compute_jingqi_deltas("600519", test_db)
    assert result["available"] is True
    assert result["delta_net_profit_yoy"] == 20.0   # 30 - 10
    assert result["delta_revenue_yoy"] == 10.0      # 15 - 5
    assert result["delta_roe"] == 3.5               # 15.5 - 12


def test_jingqi_transition_negative_to_positive(test_db):
    """Δ 利润增速从负转正"""
    _add_metric(test_db, "600519", "2024-03-30",
                net_profit_yoy=30.0, revenue_yoy=20.0)
    _add_metric(test_db, "600519", "2024-06-30",
                net_profit_yoy=20.0, revenue_yoy=10.0)   # Δ = -10
    _add_metric(test_db, "600519", "2024-09-30",
                net_profit_yoy=40.0, revenue_yoy=25.0)   # Δ = +20，转折

    result = compute_jingqi_deltas("600519", test_db)
    assert result["transitions"]["profit_negative_to_positive"] is True
    assert result["transitions"]["revenue_negative_to_positive"] is True


def test_jingqi_industry_pctile(test_db, sample_stocks):
    """3 只电子股，验证行业分位"""
    # 中际旭创 Δ 最强
    _add_metric(test_db, "300308", "2024-06-30", net_profit_yoy=10.0, revenue_yoy=5.0, roe=12.0)
    _add_metric(test_db, "300308", "2024-09-30", net_profit_yoy=50.0, revenue_yoy=30.0, roe=18.0)
    # 兆易创新 Δ 中等
    _add_metric(test_db, "603986", "2024-06-30", net_profit_yoy=15.0, revenue_yoy=10.0, roe=10.0)
    _add_metric(test_db, "603986", "2024-09-30", net_profit_yoy=20.0, revenue_yoy=15.0, roe=11.0)
    # 茅台 不同行业，但有数据
    _add_metric(test_db, "600519", "2024-06-30", net_profit_yoy=8.0, revenue_yoy=6.0, roe=20.0)
    _add_metric(test_db, "600519", "2024-09-30", net_profit_yoy=10.0, revenue_yoy=8.0, roe=21.0)

    peers = list_peers("300308", test_db)
    assert "603986" in peers
    assert "600519" not in peers   # 不同行业
    assert "300308" not in peers   # 不含自己

    result = compute_jingqi_deltas("300308", test_db, peers=peers)
    assert result["available"] is True
    # 中际旭创 Δ 利润 = 40, 兆易 Δ 利润 = 5 → 中际应分位 100%
    assert result["industry_pctile"]["delta_net_profit_yoy"] == 1.0
