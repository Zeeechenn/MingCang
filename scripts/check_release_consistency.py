"""Fail closed when public package versions and a requested release tag disagree."""
from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path


def release_versions(root: Path) -> dict[str, str]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    frontend = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    backend_text = (root / "backend/version.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', backend_text, re.MULTILINE)
    if match is None:
        raise ValueError("backend/version.py does not define APP_VERSION")
    return {
        "pyproject": str(pyproject["project"]["version"]),
        "backend": match.group(1),
        "frontend": str(frontend["version"]),
    }


def check_release_consistency(root: Path, *, expected_tag: str | None = None) -> str:
    versions = release_versions(root)
    unique = set(versions.values())
    if len(unique) != 1:
        rendered = ", ".join(f"{name}={version}" for name, version in versions.items())
        raise ValueError(f"release versions disagree: {rendered}")
    version = unique.pop()
    if expected_tag is not None and expected_tag != f"v{version}":
        raise ValueError(f"release tag {expected_tag!r} does not match v{version}")
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=None, help="Expected release tag, for example v0.7.1")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    version = check_release_consistency(root, expected_tag=args.tag)
    print(f"release consistency passed: v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
