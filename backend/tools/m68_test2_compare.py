"""Compatibility import alias for :mod:`backend.backtest.test2_compare`."""
import sys

from backend.backtest import test2_compare as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m68_test2_compare"] = _implementation

if __name__ == "__main__":
    from backend.backtest.test2_compare import main

    raise SystemExit(main())
