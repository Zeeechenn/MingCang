"""M3 audit-layer integration tests."""
import subprocess
import sys


def test_exit_logic_run_wraps_owned_session_with_pit(monkeypatch):
    from backend.backtest import exit_logic_experiment as exp

    calls = []

    class FakeSignal:
        symbol = "symbol"
        date = "date"

    class FakePrice:
        symbol = "symbol"
        date = "date"

    class FakeQuery:
        def __init__(self, rows=None):
            self.rows = rows or []

        def distinct(self):
            return self

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def all(self):
            return self.rows

    class FakeDb:
        def query(self, entity):
            if entity == FakeSignal.symbol:
                return FakeQuery([])
            return FakeQuery([])

        def close(self):
            pass

    class FakePit:
        def __init__(self, db, as_of):
            self.db = db
            self.as_of = as_of

        def __enter__(self):
            calls.append(self.as_of)
            return self.db

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(exp, "Signal", FakeSignal)
    monkeypatch.setattr(exp, "Price", FakePrice)
    monkeypatch.setattr(exp, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(exp, "pit_session", lambda db, as_of: FakePit(db, as_of))

    exp.run(as_of_end="2026-01-31")

    assert calls == ["2026-01-31"]


def test_scheduler_postmarket_runs_kill_switch_checks(monkeypatch):
    import backend.ops as ops
    from backend import scheduler

    calls = []

    class FakeColumn:
        def __init__(self, name):
            self.name = name

        def desc(self):
            return self

        def asc(self):
            return self

        def in_(self, values):
            return True

        def __eq__(self, other):
            return True

        def __gt__(self, other):
            return True

    class FakeDateQuery:
        def order_by(self, *args):
            return self

        def first(self):
            return ("2026-05-15",)

    class FakeStockQuery:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def limit(self, *args):
            return self

        def all(self):
            return []

    class FakeDb:
        def query(self, entity):
            if getattr(entity, "name", None) == "date":
                return FakeDateQuery()
            return FakeStockQuery()

        def close(self):
            pass

    class FakeStock:
        active = True

    class FakeSignal:
        recommendation = FakeColumn("recommendation")
        date = FakeColumn("date")

    class FakePrice:
        date = FakeColumn("date")
        close = FakeColumn("close")
        symbol = FakeColumn("symbol")

    class FakeKillSwitch:
        @staticmethod
        def is_active():
            return False

        @staticmethod
        def run_all_checks(**kwargs):
            calls.append(kwargs)
            return None

    monkeypatch.setattr(scheduler, "_kill_switch_guard", lambda name: False)
    monkeypatch.setattr(scheduler.settings, "regime_filter_enabled", False)
    monkeypatch.setattr(scheduler.settings, "long_term_team_enabled", False)
    monkeypatch.setattr(ops, "kill_switch", FakeKillSwitch, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "backend.ops.kill_switch", FakeKillSwitch)
    monkeypatch.setattr("backend.data.database.SessionLocal", lambda: FakeDb())
    monkeypatch.setattr("backend.data.database.Stock", FakeStock)
    monkeypatch.setattr("backend.data.database.Signal", FakeSignal)
    monkeypatch.setattr("backend.data.database.Price", FakePrice)

    scheduler.job_postmarket()

    assert calls == [{"trade_returns": [], "latest_price_date": "2026-05-15"}]


def test_postmarket_batch_applies_portfolio_manager_before_persist(monkeypatch):
    from backend import scheduler

    persisted = []
    alerts = []

    class FakeStock:
        active = True

        def __init__(self, symbol, name, industry):
            self.symbol = symbol
            self.name = name
            self.market = "CN"
            self.industry = industry

    class FakeStockQuery:
        def filter(self, *args):
            return self

        def all(self):
            return [
                FakeStock("HIGH", "高分股", "半导体"),
                FakeStock("LOW", "低分股", "半导体"),
            ]

    class FakeDb:
        def query(self, entity):
            return FakeStockQuery()

    analyses = {
        "HIGH": {
            "date": "2026-05-21",
            "result": {
                "recommendation": "可小仓试错",
                "confidence": "中",
                "composite_score": 80,
                "trader_position_pct": 0.20,
                "risk_position_pct": 0.15,
                "position_pct": 0.15,
            },
            "quant_result": {"score": 80, "model": "fake"},
            "technical_result": {"score": 80},
            "sentiment_result": {"sentiment": 0.8},
        },
        "LOW": {
            "date": "2026-05-21",
            "result": {
                "recommendation": "可小仓试错",
                "confidence": "中",
                "composite_score": 70,
                "trader_position_pct": 0.20,
                "risk_position_pct": 0.15,
                "position_pct": 0.15,
            },
            "quant_result": {"score": 70, "model": "fake"},
            "technical_result": {"score": 70},
            "sentiment_result": {"sentiment": 0.7},
        },
    }

    monkeypatch.setattr(scheduler, "_load_postmarket_context", lambda db, stocks: {})
    monkeypatch.setattr(scheduler, "_run_kill_switch_checks", lambda db: None)
    monkeypatch.setattr(scheduler, "_analyze_postmarket_stock", lambda stock, db, context: analyses[stock.symbol])
    monkeypatch.setattr(
        scheduler,
        "_persist_postmarket_stock",
        lambda stock, analysis, db: persisted.append((stock.symbol, analysis["result"].copy())),
    )
    monkeypatch.setattr(
        scheduler,
        "_maybe_send_postmarket_alert",
        lambda stock, result: alerts.append((stock.symbol, result.get("position_pct"))) or False,
    )
    monkeypatch.setattr(scheduler.settings, "portfolio_manager_enabled", True)
    monkeypatch.setattr(scheduler.settings, "max_position_per_stock", 0.15)
    monkeypatch.setattr(scheduler.settings, "max_position_per_sector", 0.15)
    monkeypatch.setattr(scheduler.settings, "max_total_equity_pct", 0.80)

    stats = scheduler.run_postmarket_batch(FakeDb())

    by_symbol = dict(persisted)
    assert stats["portfolio_allocated"] == 2
    assert by_symbol["HIGH"]["position_pct"] == 0.15
    assert by_symbol["HIGH"]["trader_position_pct"] == 0.20
    assert by_symbol["HIGH"]["risk_position_pct"] == 0.15
    assert by_symbol["HIGH"]["portfolio_decision"]["action"] == "open"
    assert by_symbol["LOW"]["position_pct"] == 0.0
    assert by_symbol["LOW"]["trader_position_pct"] == 0.20
    assert by_symbol["LOW"]["risk_position_pct"] == 0.15
    assert by_symbol["LOW"]["portfolio_decision"]["action"] == "reject"
    assert alerts == [("HIGH", 0.15), ("LOW", 0.0)]


def test_walk_forward_module_exposes_cli_help():
    res = subprocess.run(
        [sys.executable, "-m", "backend.backtest.walk_forward", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert res.returncode == 0
    assert "--mode" in res.stdout
    assert "holdout" in res.stdout


def test_backtrader_load_data_filters_prices_by_as_of_end(monkeypatch):
    from backend.backtest import backtrader_eval

    class FakeColumn:
        def __init__(self, name):
            self.name = name

        def __eq__(self, other):
            return ("eq", self.name, other)

        def __le__(self, other):
            return ("le", self.name, other)

        def asc(self):
            return self

    class FakePrice:
        symbol = FakeColumn("symbol")
        date = FakeColumn("date")

    class Row:
        def __init__(self, date, close):
            self.date = date
            self.open = close
            self.high = close
            self.low = close
            self.close = close
            self.volume = 1000

    class FakeQuery:
        def __init__(self):
            self.cutoff = None

        def filter(self, *conditions):
            for cond in conditions:
                if cond[0] == "le" and cond[1] == "date":
                    self.cutoff = cond[2]
            return self

        def order_by(self, *args):
            return self

        def all(self):
            rows = [
                Row("2026-01-01", 10),
                Row("2026-02-01", 11),
                Row("2026-03-01", 12),
            ]
            if self.cutoff:
                rows = [r for r in rows if r.date <= self.cutoff]
            return rows

    class FakeDb:
        def query(self, model):
            return FakeQuery()

    monkeypatch.setattr(backtrader_eval, "Price", FakePrice)

    df = backtrader_eval.load_data("600519", FakeDb(), as_of_end="2026-02-01")

    assert list(df.index.strftime("%Y-%m-%d")) == ["2026-01-01", "2026-02-01"]
