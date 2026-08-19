"""Compatibility import alias for :mod:`backend.portfolio.daily_panel`."""
import sys

from backend.portfolio import daily_panel as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m59_panel"] = _implementation

if __name__ == "__main__":
    from backend.portfolio.daily_panel import main

    main()
