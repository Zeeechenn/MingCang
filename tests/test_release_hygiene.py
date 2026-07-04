from __future__ import annotations

from pathlib import Path

from scripts.check_release_hygiene import scan_paths, scan_tracked_repo


def test_release_hygiene_passes_for_current_tracked_repo():
    result = scan_tracked_repo(Path(__file__).resolve().parents[1])

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
            ]
        ),
        encoding="utf-8",
    )

    result = scan_paths([candidate], root=tmp_path)

    assert result.allowed_lines == 1
    assert [(finding.line_number, finding.snippet) for finding in result.findings] == [
        (1, "plain XHS mention"),
        (4, "token ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ"),
    ]
