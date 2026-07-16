"""Runtime identity helpers shared by monitoring and task ledgers."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend.config import BASE_DIR, sqlite_path_from_url
from backend.version import APP_VERSION

UNKNOWN_BUILD_COMMIT = "unknown"


def _read_git_commit(repo_root: Path = BASE_DIR) -> str:
    """Read the current commit without invoking git or exposing repository paths."""
    configured = os.environ.get("MINGCANG_BUILD_COMMIT", "").strip()
    if configured:
        return configured[:12]

    git_dir = repo_root / ".git"
    head_path = git_dir / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return UNKNOWN_BUILD_COMMIT

    if not head.startswith("ref: "):
        return head[:12] if head else UNKNOWN_BUILD_COMMIT

    ref = head.removeprefix("ref: ").strip()
    try:
        commit = (git_dir / ref).read_text(encoding="utf-8").strip()
        if commit:
            return commit[:12]
    except OSError:
        pass

    try:
        for line in (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines():
            if not line or line.startswith(("#", "^")):
                continue
            commit, packed_ref = line.split(" ", 1)
            if packed_ref == ref:
                return commit[:12]
    except (OSError, ValueError):
        pass
    return UNKNOWN_BUILD_COMMIT


def database_role(settings: Any) -> str:
    """Classify the configured database without returning its absolute path."""
    configured = str(getattr(settings, "database_role", "auto") or "auto").strip().lower()
    if configured != "auto":
        return configured

    database_url = str(getattr(settings, "database_url", "") or "")
    if database_url == "sqlite:///:memory:":
        return "test"
    path = sqlite_path_from_url(database_url)
    if path is None:
        return "external" if database_url else "unknown"

    lowered_parts = {part.lower() for part in path.parts}
    lowered_name = path.name.lower()
    if (
        "sample_db" in lowered_parts
        or "examples" in lowered_parts
        or "demo" in lowered_name
        or "sample" in lowered_name
    ):
        return "demo"
    try:
        if path.resolve() == (BASE_DIR / "mingcang.db").resolve():
            return "primary"
    except OSError:
        pass
    return "custom"


def scheduler_mode(settings: Any) -> str:
    """Return the effective scheduler ownership mode for this API process."""
    if bool(getattr(settings, "scheduler_enabled", False)):
        return "embedded"
    configured = str(getattr(settings, "scheduler_mode", "manual") or "manual").strip().lower()
    return configured if configured in {"manual", "external"} else "manual"


def build_runtime_identity(settings: Any, *, db_latest_date: str | None = None) -> dict[str, Any]:
    """Build the public, path-safe runtime identity contract."""
    path = sqlite_path_from_url(str(getattr(settings, "database_url", "") or ""))
    return {
        "version": APP_VERSION,
        "build_commit": _read_git_commit(),
        "db_role": database_role(settings),
        "db_name": path.name if path is not None else None,
        "db_latest_date": db_latest_date,
        "scheduler_mode": scheduler_mode(settings),
    }
