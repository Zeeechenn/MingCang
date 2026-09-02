from __future__ import annotations

from pathlib import Path

from scripts.check_doc_authority import check_doc_authority


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _seed_minimal_repo(root: Path) -> None:
    public_paths = [
        "docs_public/index.md",
        "docs_public/USER_GUIDE.md",
        "docs_public/FEATURE_MAP.md",
        "docs_public/ARCHITECTURE.md",
        "docs_public/DEVELOPER_GUIDE.md",
        "docs_public/REFERENCE.md",
        "docs_public/WHY_NOT_AI_STOCK_PICKER.md",
        "docs_public/ningde_live_sample.md",
    ]
    table = "\n".join(f"| [{path}]({path}) | ok |" for path in public_paths)
    _write(root / "README.md", table)
    _write(root / "README_EN.md", table)
    _write(
        root / "docs/ARCHITECTURE.md",
        "Compatibility stub\n\n../docs_public/ARCHITECTURE.md\n",
    )
    _write(
        root / "docs/WHY_NOT_AI_STOCK_PICKER.md",
        "Compatibility stub\n\n../docs_public/WHY_NOT_AI_STOCK_PICKER.md\n",
    )
    _write(
        root / "mkdocs.yml",
        "docs_dir: docs_public\nnav:\n  - 宁德活样本: ningde_live_sample.md\n",
    )
    _write(root / "docs/dev/M54_OOS_PREREGISTER.md", "live contract\n")


def test_doc_authority_accepts_minimal_valid_repo(tmp_path: Path) -> None:
    _seed_minimal_repo(tmp_path)

    assert check_doc_authority(tmp_path) == []


def test_doc_authority_rejects_old_public_links(tmp_path: Path) -> None:
    _seed_minimal_repo(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\ndocs/ARCHITECTURE.md\n", encoding="utf-8")

    errors = check_doc_authority(tmp_path)

    assert any("README.md still links stale public authority docs/ARCHITECTURE.md" in error for error in errors)


def test_doc_authority_rejects_archived_docs_in_repo(tmp_path: Path) -> None:
    _seed_minimal_repo(tmp_path)
    _write(tmp_path / "docs/research/old-report.md", "historical output\n")
    _write(tmp_path / "docs/dev/M59_PANEL_SPEC.md", "closed plan\n")

    errors = check_doc_authority(tmp_path)

    assert any("docs/research still contains markdown artifacts" in error for error in errors)
    assert any("docs/dev contains non-live archived plans" in error for error in errors)


def test_doc_authority_rejects_restored_data_audit_narratives(tmp_path: Path) -> None:
    _seed_minimal_repo(tmp_path)
    _write(tmp_path / "docs/dev/DATA_AUDIT_EXTERNAL.md", "dated raw audit\n")

    errors = check_doc_authority(tmp_path)

    assert any("restored archived audit narratives" in error for error in errors)


def test_doc_authority_accepts_current_repo() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if not (repo_root / "mkdocs.yml").exists():
        repo_root = Path.cwd()

    errors = check_doc_authority(repo_root)

    assert errors == []
