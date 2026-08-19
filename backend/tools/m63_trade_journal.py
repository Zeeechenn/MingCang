"""Compatibility import alias for :mod:`backend.portfolio.trade_journal`."""
import sys

from backend.portfolio import trade_journal as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m63_trade_journal"] = _implementation

if __name__ == "__main__":
    from backend.portfolio.trade_journal import main

    raise SystemExit(main())
