"""Compatibility import alias for :mod:`backend.evidence.daily_accrual`."""
import sys

from backend.evidence import daily_accrual as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m54_daily_accrual"] = _implementation

if __name__ == "__main__":
    from backend.evidence.daily_accrual import main

    raise SystemExit(main())
