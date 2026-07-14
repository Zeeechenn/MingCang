"""Shared local artifact paths for watchtower research workflows."""
from pathlib import Path

DEFAULT_WATCHTOWER_OUTPUT_DIR = Path("/private/tmp")

__all__ = ["DEFAULT_WATCHTOWER_OUTPUT_DIR"]
