"""Compatibility CLI and import alias for :mod:`backend.workflows.m63_daily`."""
from __future__ import annotations

import sys

from backend.workflows import m63_daily as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())

sys.modules[__name__] = _implementation
sys.modules[__package__].__dict__["m63_daily"] = _implementation
