"""Compatibility import alias for :mod:`backend.decision.readiness`."""
import sys

from backend.decision import readiness as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m59_readiness"] = _implementation

if __name__ == "__main__":
    from backend.decision.readiness import main

    raise SystemExit(main())
