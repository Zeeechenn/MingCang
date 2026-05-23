import pandas as pd


def test_run_one_configures_a_share_slippage(monkeypatch):
    from backend.backtest import backtrader_eval

    calls = []

    class FakeBroker:
        def set_cash(self, cash):
            calls.append(("cash", cash))

        def addcommissioninfo(self, info):
            calls.append(("commission", type(info).__name__))

        def set_slippage_perc(self, perc):
            calls.append(("slippage", perc))

        def getvalue(self):
            return 100_000

    class FakeAnalyzer:
        def get_analysis(self):
            return {}

    class FakeStrategy:
        analyzers = type(
            "Analyzers",
            (),
            {"sharpe": FakeAnalyzer(), "dd": FakeAnalyzer(), "trades": FakeAnalyzer()},
        )()

    class FakeCerebro:
        def __init__(self):
            self.broker = FakeBroker()
            self.runstrats = [[FakeStrategy()]]

        def adddata(self, *args, **kwargs):
            pass

        def addstrategy(self, *args, **kwargs):
            pass

        def addanalyzer(self, *args, **kwargs):
            pass

        def run(self):
            return self.runstrats

    dates = pd.date_range("2026-01-01", periods=90)
    raw = pd.DataFrame(
        {
            "open": [10.0] * 90,
            "high": [10.2] * 90,
            "low": [9.8] * 90,
            "close": [10.0] * 90,
            "volume": [1_000_000] * 90,
        },
        index=dates,
    )

    monkeypatch.setattr(backtrader_eval.bt, "Cerebro", FakeCerebro)
    monkeypatch.setattr(backtrader_eval, "add_all_factors", lambda df: df.assign(atr14=0.3))
    monkeypatch.setattr(backtrader_eval, "compute_tech_scores", lambda df, apply_adx_filter=True: pd.Series(50.0, index=df.index))

    backtrader_eval.run_one(
        symbol="300308",
        name="中际旭创",
        df_raw=raw,
        start="2026-01-01",
        end="2026-03-31",
        cfg={"rr": 1.5, "max_hold": 5, "trailing": True, "trailing_mult": 1.5, "adx_filter": False},
    )

    assert ("slippage", backtrader_eval.A_SHARE_SLIPPAGE_PERC) in calls


def test_public_validation_snapshot_discloses_reproducible_scope():
    from backend.backtest.backtrader_eval import PUBLIC_VALIDATION_SNAPSHOT

    assert PUBLIC_VALIDATION_SNAPSHOT["metric_scope"] == "single_stock_cross_section_average"
    assert PUBLIC_VALIDATION_SNAPSHOT["universe"] == ["300308", "688008"]
    assert PUBLIC_VALIDATION_SNAPSHOT["n_symbols"] == 2
    assert PUBLIC_VALIDATION_SNAPSHOT["costs"]["commission_round_trip"] == 0.002
    assert PUBLIC_VALIDATION_SNAPSHOT["costs"]["slippage_per_trade"] == 0.001
    assert PUBLIC_VALIDATION_SNAPSHOT["command"]
