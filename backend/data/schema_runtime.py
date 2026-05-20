"""Runtime schema patch exports.

The implementation remains in database.py for compatibility. This module gives
future migrations a narrower home without changing existing imports.
"""
from backend.data.database import _ensure_runtime_schema

__all__ = ["_ensure_runtime_schema"]
