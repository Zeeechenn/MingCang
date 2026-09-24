from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_historical_technical():
    root = Path(__file__).resolve().parents[1]
    path = root / "backend/backtest/historical_technical.py"
    spec = importlib.util.spec_from_file_location("candidate_historical_technical", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load candidate technical module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
