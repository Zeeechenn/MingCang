#!/usr/bin/env python3
"""Guard MingCang documentation authority and navigation invariants."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PUBLIC_AUTHORITY_PATHS = {
    "docs_public/index.md",
    "docs_public/USER_GUIDE.md",
    "docs_public/FEATURE_MAP.md",
    "docs_public/ARCHITECTURE.md",
    "docs_public/DEVELOPER_GUIDE.md",
    "docs_public/REFERENCE.md",
    "docs_public/WHY_NOT_AI_STOCK_PICKER.md",
    "docs_public/ningde_live_sample.md",
}

OLD_PUBLIC_LINKS = {
    "docs/ARCHITECTURE.md",
    "docs/WHY_NOT_AI_STOCK_PICKER.md",
}

STUB_TARGETS = {
    "docs/ARCHITECTURE.md": "../docs_public/ARCHITECTURE.md",
    "docs/WHY_NOT_AI_STOCK_PICKER.md": "../docs_public/WHY_NOT_AI_STOCK_PICKER.md",
}

ALLOWED_DEV_CONTRACTS = {
    "2026-07-07-live-track-design.md",
    "M54_OOS_PREREGISTER.md",
    "M55_SERENITY_CONVERGENCE_PLAN.md",
    "README.md",
    "m50_research_report_gate_spec.md",
    "NEWS_EVENT_RISK_CONTRACT.md",
    "MODEL_COMPARISON_CONTRACT.md",
    "EXTERNAL_METHODS_CONTRACT.md",
    "P0_DATA_FOUNDATION_CONTRACT.md",
}

ARCHIVED_DEV_NARRATIVES = {
    "DATA_AUDIT_EXTERNAL.md",
    "DATA_AUDIT_IFIND.md",
}

CORE_CONTEXT_PATHS = ("AGENTS.md", "STATUS.md", "docs/ROADMAP.md")
CORE_CONTEXT_BASELINE_CHARS = 39_300
CORE_CONTEXT_MAX_CHARS = CORE_CONTEXT_BASELINE_CHARS * 67 // 100
SCOPED_CONTRACTS = {
    "docs/dev/NEWS_EVENT_RISK_CONTRACT.md": "docs/dev/NEWS_EVENT_RISK_CONTRACT.md",
    "docs/dev/MODEL_COMPARISON_CONTRACT.md": "docs/dev/MODEL_COMPARISON_CONTRACT.md",
    "docs/dev/EXTERNAL_METHODS_CONTRACT.md": "docs/dev/EXTERNAL_METHODS_CONTRACT.md",
    "docs/dev/P0_DATA_FOUNDATION_CONTRACT.md": "docs/dev/P0_DATA_FOUNDATION_CONTRACT.md",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _require(condition: bool, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)


def _check_readme_parity(root: Path, errors: list[str]) -> None:
    readme = _read(root / "README.md")
    readme_en = _read(root / "README_EN.md")

    for stale in OLD_PUBLIC_LINKS:
        _require(stale not in readme, errors, f"README.md still links stale public authority {stale}")
        _require(stale not in readme_en, errors, f"README_EN.md still links stale public authority {stale}")

    for public_path in sorted(PUBLIC_AUTHORITY_PATHS):
        _require(public_path in readme, errors, f"README.md missing {public_path}")
        _require(public_path in readme_en, errors, f"README_EN.md missing {public_path}")


def _check_public_stubs(root: Path, errors: list[str]) -> None:
    for stub_path, target in STUB_TARGETS.items():
        content = _read(root / stub_path)
        _require("Compatibility stub" in content, errors, f"{stub_path} must be a compatibility stub")
        _require(target in content, errors, f"{stub_path} must point to {target}")


def _check_nav(root: Path, errors: list[str]) -> None:
    mkdocs = _read(root / "mkdocs.yml")
    _require("docs_dir: docs_public" in mkdocs, errors, "mkdocs.yml must use docs_public as docs_dir")
    _require("ningde_live_sample.md" in mkdocs, errors, "mkdocs.yml nav must include ningde_live_sample.md")


def _check_internal_archive_boundaries(root: Path, errors: list[str]) -> None:
    for directory in ("docs/research", "docs/reviews"):
        path = root / directory
        if path.exists():
            leftovers = sorted(p.relative_to(root).as_posix() for p in path.glob("*.md"))
            _require(not leftovers, errors, f"{directory} still contains markdown artifacts: {leftovers}")

    dev_dir = root / "docs/dev"
    if dev_dir.exists():
        current = {path.name for path in dev_dir.glob("*.md")}
        unexpected = sorted(current - ALLOWED_DEV_CONTRACTS - ARCHIVED_DEV_NARRATIVES)
        _require(not unexpected, errors, f"docs/dev contains non-live archived plans: {unexpected}")
        restored = sorted(current & ARCHIVED_DEV_NARRATIVES)
        _require(not restored, errors, f"docs/dev restored archived audit narratives: {restored}")


def core_context_char_count(root: Path) -> int:
    """Count the default instruction, status, and sole-plan context in characters."""
    return sum(len(_read(root / relative)) for relative in CORE_CONTEXT_PATHS)


def _check_core_context_and_scoped_routes(root: Path, errors: list[str]) -> None:
    missing = [relative for relative in CORE_CONTEXT_PATHS if not (root / relative).is_file()]
    _require(not missing, errors, f"core context documents missing: {missing}")
    if not missing:
        count = core_context_char_count(root)
        _require(
            count <= CORE_CONTEXT_MAX_CHARS,
            errors,
            f"default core context is {count} chars; maximum is {CORE_CONTEXT_MAX_CHARS}",
        )

    agents_path = root / "AGENTS.md"
    if agents_path.is_file():
        agents = _read(agents_path)
        for relative, route in SCOPED_CONTRACTS.items():
            target = root / relative
            _require(target.is_file(), errors, f"task-scoped contract missing: {relative}")
            _require(route in agents, errors, f"AGENTS.md must route its task to {route}")

    historical = root / "docs/dev/M54_OOS_PREREGISTER.md"
    if historical.is_file():
        content = _read(historical)
        _require(
            "历史预注册/结果记录" in content and "不授权新调用" in content,
            errors,
            "M54 preregistration must remain explicitly historical and non-authorizing",
        )


def check_doc_authority(root: Path) -> list[str]:
    errors: list[str] = []
    _check_readme_parity(root, errors)
    _check_public_stubs(root, errors)
    _check_nav(root, errors)
    _check_internal_archive_boundaries(root, errors)
    _check_core_context_and_scoped_routes(root, errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    args = parser.parse_args(argv)

    errors = check_doc_authority(args.root.resolve())
    if errors:
        for error in errors:
            print(f"doc-authority: {error}", file=sys.stderr)
        return 1
    print("doc-authority: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
