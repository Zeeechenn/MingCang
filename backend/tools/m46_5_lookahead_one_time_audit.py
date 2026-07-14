"""Compatibility CLI and import alias for :mod:`backend.evidence.lookahead_audit`."""
import sys

from backend.evidence import lookahead_audit as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())

sys.modules[__name__] = _implementation
sys.modules[__package__].__dict__["m46_5_lookahead_one_time_audit"] = _implementation
