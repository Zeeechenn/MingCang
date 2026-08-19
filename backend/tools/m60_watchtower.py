"""Compatibility import alias for :mod:`backend.research.watchtower`."""
import sys

from backend.research import watchtower as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m60_watchtower"] = _implementation

if __name__ == "__main__":
    from backend.research.watchtower import main

    main()
