"""Compatibility import alias for :mod:`backend.backtest.grid_backtest`."""
import sys

from backend.backtest import grid_backtest as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m58_grid_backtest"] = _implementation

if __name__ == "__main__":
    from backend.backtest.grid_backtest import main

    raise SystemExit(main())
