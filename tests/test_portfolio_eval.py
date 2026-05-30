import subprocess
import sys

import pandas as pd


def test_portfolio_snapshot_discloses_scope_and_caveats():
    from backend.backtest.portfolio_eval import PORTFOLIO_VALIDATION_SNAPSHOT

    assert PORTFOLIO_VALIDATION_SNAPSHOT["metric_scope"] == "portfolio_equity_curve"
    assert PORTFOLIO_VALIDATION_SNAPSHOT["min_window_bars"] == 720
    assert PORTFOLIO_VALIDATION_SNAPSHOT["expected_n_symbols_at_creation"] == 92
    assert "survivorship-biased current universe" in PORTFOLIO_VALIDATION_SNAPSHOT["caveats"]
    assert "technical-only" in PORTFOLIO_VALIDATION_SNAPSHOT["caveats"]
    assert "not a production full-stack backtest" in PORTFOLIO_VALIDATION_SNAPSHOT["caveats"]


def test_equity_metrics_compute_portfolio_curve_stats():
    from backend.backtest.portfolio_eval import annualized_sharpe_from_daily_returns, equity_metrics

    curve = [
        {"date": "2026-01-01", "value": 100.0, "cash": 10.0},
        {"date": "2026-01-02", "value": 110.0, "cash": 10.0},
        {"date": "2026-01-03", "value": 99.0, "cash": 10.0},
        {"date": "2026-01-04", "value": 121.0, "cash": 10.0},
    ]

    out = equity_metrics(curve, 100.0, "2026-01-01", "2026-01-04")

    assert out["final_value"] == 121.0
    assert out["total_return_pct"] == 21.0
    assert out["max_drawdown_pct"] == 10.0
    assert out["daily_return_count"] == 3
    assert out["sharpe"] is not None
    assert annualized_sharpe_from_daily_returns([0.01, -0.01, 0.02]) is not None


def test_prepare_feed_filters_by_window_bars_and_defaults_industry(monkeypatch):
    from backend.backtest import portfolio_eval

    class Stock:
        symbol = "600519"
        name = "贵州茅台"
        industry = None

    dates = pd.date_range("2026-01-01", periods=5)
    raw = pd.DataFrame(
        {
            "open": [10.0] * 5,
            "high": [10.5] * 5,
            "low": [9.5] * 5,
            "close": [10.0] * 5,
            "volume": [1000] * 5,
        },
        index=dates,
    )

    monkeypatch.setattr(portfolio_eval, "load_data", lambda *args, **kwargs: raw)
    monkeypatch.setattr(portfolio_eval, "add_all_factors", lambda df: df.assign(atr14=0.3))
    monkeypatch.setattr(
        portfolio_eval,
        "compute_tech_scores",
        lambda df, apply_adx_filter=True: pd.Series(50.0, index=df.index),
    )

    assert portfolio_eval.prepare_feed(
        Stock(), object(), "2026-01-01", "2026-01-05", {"adx_filter": False}, 6,
    ) is None

    df_bt, meta = portfolio_eval.prepare_feed(
        Stock(), object(), "2026-01-01", "2026-01-05", {"adx_filter": False}, 5,
    )

    assert len(df_bt) == 5
    assert meta.industry == "未分类"


def test_prepare_feed_excludes_empty_price_history(monkeypatch):
    from backend.backtest import portfolio_eval

    class Stock:
        symbol = "300001"
        name = "空数据"
        industry = "电子"

    monkeypatch.setattr(portfolio_eval, "load_data", lambda *args, **kwargs: (_ for _ in ()).throw(KeyError("datetime")))

    assert portfolio_eval.prepare_feed(
        Stock(), object(), "2026-01-01", "2026-01-05", {"adx_filter": False}, 5,
    ) is None


def test_run_portfolio_backtest_uses_single_cerebro_and_costs(monkeypatch):
    from backend.backtest import portfolio_eval

    calls = []

    class FakeBroker:
        def set_cash(self, cash):
            calls.append(("cash", cash))
            self.cash = cash

        def addcommissioninfo(self, info):
            calls.append(("commission", type(info).__name__))

        def set_slippage_perc(self, perc):
            calls.append(("slippage", perc))

        def getvalue(self):
            return self.cash

        def get_cash(self):
            return self.cash

    class FakeAnalyzer:
        def __init__(self, analysis):
            self.analysis = analysis

        def get_analysis(self):
            return self.analysis

    class FakeStrategy:
        max_single_exposure = 0.14
        max_sector_exposure = 0.29
        max_total_exposure = 0.79
        max_decision_single_exposure = 0.15
        max_decision_sector_exposure = 0.30
        max_decision_total_exposure = 0.80
        analyzers = type(
            "Analyzers",
            (),
            {
                "values": FakeAnalyzer([
                    {"date": "2026-01-01", "value": 1000.0, "cash": 1000.0},
                    {"date": "2026-01-02", "value": 1010.0, "cash": 100.0},
                ]),
                "trades": FakeAnalyzer({"total": {"closed": 2}, "won": {"total": 1}}),
            },
        )()

    class FakeCerebro:
        instances = 0

        def __init__(self):
            FakeCerebro.instances += 1
            self.broker = FakeBroker()
            self.runstrats = [[FakeStrategy()]]
            self.data_count = 0

        def adddata(self, *args, **kwargs):
            self.data_count += 1
            calls.append(("data", kwargs.get("name")))

        def addstrategy(self, *args, **kwargs):
            calls.append(("strategy", args[0].__name__, kwargs))

        def addanalyzer(self, *args, **kwargs):
            calls.append(("analyzer", kwargs.get("_name")))

        def run(self):
            return self.runstrats

    class Stock:
        def __init__(self, symbol, industry):
            self.symbol = symbol
            self.name = symbol
            self.industry = industry

    dates = pd.date_range("2026-01-01", periods=3)
    feed = pd.DataFrame(
        {
            "open": [10.0] * 3,
            "high": [10.5] * 3,
            "low": [9.5] * 3,
            "close": [10.0] * 3,
            "volume": [1000] * 3,
            "tech_score": [50.0] * 3,
            "atr14": [0.3] * 3,
        },
        index=dates,
    )

    monkeypatch.setattr(portfolio_eval.bt, "Cerebro", FakeCerebro)
    monkeypatch.setattr(
        portfolio_eval,
        "prepare_feed",
        lambda stock, *args, **kwargs: (feed, portfolio_eval.FeedMeta(stock.symbol, stock.name, stock.industry, 3)),
    )

    result = portfolio_eval.run_portfolio_backtest(
        [Stock("a", "电子"), Stock("b", "电子")],
        object(),
        start="2026-01-01",
        end="2026-01-03",
        cfg=portfolio_eval.LEGACY_PORTFOLIO_CFG,
        cash=1000.0,
        min_window_bars=3,
    )

    assert FakeCerebro.instances == 1
    assert ("slippage", portfolio_eval.A_SHARE_SLIPPAGE_PERC) in calls
    assert ("commission", "AShareCommission") in calls
    assert [c for c in calls if c[0] == "data"] == [("data", "a"), ("data", "b")]
    assert result["metric_scope"] == "portfolio_equity_curve"
    assert result["n_symbols"] == 2
    assert result["metrics"]["trades"] == 2
    assert result["metrics"]["max_decision_total_exposure_pct"] == 80.0
    assert result["metrics"]["max_mark_to_market_total_exposure_pct"] == 79.0


def test_portfolio_strategy_records_exposure_caps():
    from backend.backtest.portfolio_eval import PortfolioTechStrategy

    class Pos:
        def __init__(self, size):
            self.size = size

    class Data:
        def __init__(self, name, close):
            self._name = name
            self.close = [close]

    class Broker:
        def getvalue(self):
            return 1000.0

    strategy = object.__new__(PortfolioTechStrategy)
    strategy.datas = [Data("a", 10.0), Data("b", 20.0), Data("c", 10.0)]
    strategy.broker = Broker()
    strategy.p = type("P", (), {"symbol_industries": {"a": "电子", "b": "电子", "c": "银行"}})()
    strategy.max_single_exposure = 0.0
    strategy.max_sector_exposure = 0.0
    strategy.max_total_exposure = 0.0
    strategy.max_decision_single_exposure = 0.0
    strategy.max_decision_sector_exposure = 0.0
    strategy.max_decision_total_exposure = 0.0

    positions = {"a": Pos(10), "b": Pos(5), "c": Pos(10)}
    strategy.getposition = lambda data: positions[data._name]

    strategy._record_exposures()

    assert strategy.max_single_exposure == 0.1
    assert strategy.max_sector_exposure == 0.2
    assert strategy.max_total_exposure == 0.3


def test_portfolio_strategy_counts_pending_orders_against_budget():
    from backend.backtest.portfolio_eval import PortfolioTechStrategy

    class Line:
        def __init__(self, value):
            self.value = value

        def __getitem__(self, index):
            return self.value

    class Pos:
        size = 0

    class Data:
        def __init__(self, name, score):
            self._name = name
            self.close = Line(10.0)
            self.low = Line(9.5)
            self.high = Line(10.5)
            self.tech_score = Line(score)
            self.atr14 = Line(0.3)

    class Broker:
        def getvalue(self):
            return 1000.0

    strategy = object.__new__(PortfolioTechStrategy)
    strategy.datas = [Data(f"s{i}", 100 - i) for i in range(10)]
    strategy.broker = Broker()
    strategy.p = type(
        "P",
        (),
        {
            "entry_threshold": 20.0,
            "atr_mult": 2.0,
            "rr": 2.0,
            "max_hold_days": 5,
            "trailing_enabled": False,
            "trailing_atr_mult": 1.5,
            "symbol_industries": {f"s{i}": f"行业{i}" for i in range(10)},
            "max_position_per_stock": 0.15,
            "max_position_per_sector": 0.30,
            "max_total_equity_pct": 0.80,
        },
    )()
    strategy.state = {}
    strategy.pending = set()
    strategy.max_single_exposure = 0.0
    strategy.max_sector_exposure = 0.0
    strategy.max_total_exposure = 0.0
    strategy.max_decision_single_exposure = 0.0
    strategy.max_decision_sector_exposure = 0.0
    strategy.max_decision_total_exposure = 0.0
    strategy.getposition = lambda data: Pos()
    orders = []
    strategy.buy = lambda data, size: orders.append((data._name, size)) or object()
    strategy.close = lambda data: object()

    strategy.next()

    planned_value = sum(size * 10.0 for _, size in orders)
    assert planned_value <= 800.0
    assert strategy.max_decision_single_exposure <= 0.15
    assert strategy.max_decision_total_exposure <= 0.80


def test_portfolio_eval_cli_help():
    res = subprocess.run(
        [sys.executable, "-m", "backend.backtest.portfolio_eval", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert res.returncode == 0
    assert "--min-window-bars" in res.stdout
    assert "--equity-csv" in res.stdout
