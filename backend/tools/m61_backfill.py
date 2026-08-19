"""Compatibility import alias for :mod:`backend.data.category_backfill`."""
import sys

from backend.data import category_backfill as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m61_backfill"] = _implementation

if __name__ == "__main__":
    from backend.data.category_backfill import main

    raise SystemExit(main())
