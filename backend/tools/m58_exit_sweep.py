"""Compatibility import alias for :mod:`backend.backtest.exit_sweep_m58`."""
import sys

from backend.backtest import exit_sweep_m58 as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m58_exit_sweep"] = _implementation

if __name__ == "__main__":
    from backend.backtest.exit_sweep_m58 import main

    raise SystemExit(main())
