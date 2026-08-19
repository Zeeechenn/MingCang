"""Compatibility import alias for :mod:`backend.research.thesis_conditions`."""
import sys

from backend.research import thesis_conditions as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m60_thesis_conditions"] = _implementation

if __name__ == "__main__":
    from backend.research.thesis_conditions import main

    main()
    raise SystemExit(0)
