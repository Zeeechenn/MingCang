"""Compatibility import alias for :mod:`backend.decision.discretion`."""
import sys

from backend.decision import discretion as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m59_discretion"] = _implementation

if __name__ == "__main__":
    from backend.decision.discretion import main

    raise SystemExit(main())
