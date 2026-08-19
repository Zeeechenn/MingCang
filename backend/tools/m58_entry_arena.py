"""Compatibility import alias for :mod:`backend.backtest.entry_arena`."""
import sys

from backend.backtest import entry_arena as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m58_entry_arena"] = _implementation

if __name__ == "__main__":
    from backend.backtest.entry_arena import main

    raise SystemExit(main())
