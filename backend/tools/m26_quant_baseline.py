"""Compatibility CLI and import alias for :mod:`backend.backtest.quant_baseline`."""
import sys

from backend.backtest import quant_baseline as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())

sys.modules[__name__] = _implementation
sys.modules[__package__].__dict__["m26_quant_baseline"] = _implementation
