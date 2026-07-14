"""Compatibility import alias for :mod:`backend.workflows.render`."""
import sys

from backend.workflows import render as _implementation

sys.modules[__name__] = _implementation
sys.modules[__package__].__dict__["m63_render"] = _implementation
