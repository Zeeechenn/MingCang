"""Compatibility import alias for :mod:`backend.data.flow_floor`."""
import sys

from backend.data import flow_floor as _implementation

sys.modules[__name__] = _implementation
sys.modules[__package__].__dict__["m52_flow_floor"] = _implementation
