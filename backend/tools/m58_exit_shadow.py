"""Compatibility import alias for :mod:`backend.portfolio.exit_shadow`."""
import sys

from backend.portfolio import exit_shadow as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m58_exit_shadow"] = _implementation

if __name__ == "__main__":
    from backend.portfolio.exit_shadow import main

    raise SystemExit(main())
