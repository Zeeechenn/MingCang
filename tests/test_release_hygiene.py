from __future__ import annotations

import ast
import re
from pathlib import Path

from scripts.check_release_hygiene import scan_paths, scan_tracked_repo

ROOT = Path(__file__).resolve().parents[1]


def test_release_hygiene_passes_for_current_tracked_repo():
    result = scan_tracked_repo(ROOT)

    assert result.findings == []


def test_release_hygiene_detects_blocked_terms_and_allows_marked_lines(tmp_path):
    candidate = tmp_path / "candidate.md"
    candidate.write_text(
        "\n".join(
            [
                "plain XHS mention",
                "embedded NOXHSVALUE should not match",
                "old name A老师 # hygiene-allow",
                "token ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ",
                "placeholder /Users/you/mingcang is allowed",
                "real path /Users/alice/mingcang is blocked",
                "tmp path /private/tmp/report.json",
                "claude tmp /tmp/claude-session/log.txt",
                "openai sk-abcdefghijklmnopqrstuvwxyz",
                "tavily tvly-abcdef123456",
                "aws AKIAABCDEFGHIJKLMNOP",
                "mail person@gmail.com",
            ]
        ),
        encoding="utf-8",
    )

    result = scan_paths([candidate], root=tmp_path)

    assert result.allowed_lines == 2
    assert [(finding.line_number, finding.snippet) for finding in result.findings] == [
        (1, "plain XHS mention"),
        (4, "token ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ"),
        (6, "real path /Users/alice/mingcang is blocked"),
        (7, "tmp path /private/tmp/report.json"),
        (8, "claude tmp /tmp/claude-session/log.txt"),
        (9, "openai sk-abcdefghijklmnopqrstuvwxyz"),
        (10, "tavily tvly-abcdef123456"),
        (11, "aws AKIAABCDEFGHIJKLMNOP"),
        (12, "mail person@gmail.com"),
    ]


def _settings_field_names() -> set[str]:
    tree = ast.parse((ROOT / "backend/config.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            names: set[str] = set()
            for item in node.body:
                if (
                    isinstance(item, ast.AnnAssign)
                    and isinstance(item.target, ast.Name)
                    and not item.target.id.startswith("_")
                ):
                    names.add(item.target.id.upper())
            return names
    raise AssertionError("Settings class not found in backend/config.py")


def test_env_example_covers_all_settings_fields():
    env_text = (ROOT / ".env.example").read_text(encoding="utf-8")
    declared_keys = set(re.findall(r"(?m)^#?\s*([A-Z][A-Z0-9_]*)=", env_text))

    assert _settings_field_names() <= declared_keys
