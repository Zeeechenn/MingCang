from __future__ import annotations

import json
from pathlib import Path

import pytest


def _fixture(
    root: Path,
    *,
    pyproject: str = "1.2.3",
    backend: str = "1.2.3",
    frontend: str = "1.2.3",
) -> None:
    (root / "backend").mkdir()
    (root / "frontend").mkdir()
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "fixture"\nversion = "{pyproject}"\n',
        encoding="utf-8",
    )
    (root / "backend/version.py").write_text(
        f'APP_VERSION = "{backend}"\n', encoding="utf-8"
    )
    (root / "frontend/package.json").write_text(
        json.dumps({"version": frontend}), encoding="utf-8"
    )


def test_release_consistency_accepts_matching_versions_and_tag(tmp_path):
    from scripts.check_release_consistency import check_release_consistency

    _fixture(tmp_path)

    assert check_release_consistency(tmp_path, expected_tag="v1.2.3") == "1.2.3"


@pytest.mark.parametrize(
    ("versions", "tag"),
    [({"frontend": "1.2.4"}, None), ({}, "v1.2.4")],
)
def test_release_consistency_rejects_drift(tmp_path, versions, tag):
    from scripts.check_release_consistency import check_release_consistency

    _fixture(tmp_path, **versions)

    with pytest.raises(ValueError):
        check_release_consistency(tmp_path, expected_tag=tag)
