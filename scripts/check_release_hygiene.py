from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ALLOW_MARKER = "# hygiene-allow"
SELF_PATH = "scripts/check_release_hygiene.py"
TEST_PATH = "tests/test_release_hygiene.py"
HOME_PATH_PLACEHOLDER_ALLOWLIST = (
    "/Users/you/",
    "/Users/<user>/",
)


@dataclass(frozen=True)
class HygieneFinding:
    path: str
    line_number: int
    snippet: str
    rule: str


@dataclass(frozen=True)
class HygieneResult:
    findings: list[HygieneFinding]
    allowed_lines: int
    scanned_files: int


RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("legacy-term:A老师", re.compile("A老师")),
    ("legacy-term:艾利克斯", re.compile("艾利克斯")),
    ("legacy-term:小红书", re.compile("小红书")),
    ("legacy-term:xiaohongshu", re.compile("xiaohongshu")),
    ("legacy-term:XHS", re.compile(r"(?<![A-Za-z0-9_])XHS(?![A-Za-z0-9_])")),
    ("personal-path:home", re.compile(r"/Users/[a-z0-9_]+/")),
    ("personal-path:private-tmp", re.compile(r"/private/tmp/")),
    ("personal-path:tmp-claude", re.compile(r"/tmp/claude-")),
    ("credential:openai-key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("credential:sk-ant", re.compile(r"sk-ant-")),
    ("credential:tavily-key", re.compile(r"tvly-[A-Za-z0-9]+")),
    ("credential:aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("credential:github-token", re.compile(r"ghp_[A-Za-z0-9]{30,}")),
    ("credential:slack-bot-token", re.compile(r"xoxb-")),
    ("credential:personal-email", re.compile(r"[a-zA-Z0-9._%+-]+@(gmail|qq|163|outlook)\.[a-z]+")),
)

ALLOWLISTED_FINDINGS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "tests/test_research_copilot.py",
        "personal-path:private-tmp",
        re.compile(r"/private/tmp/"),
    ),
)

ALLOWLISTED_FINDING_PATTERNS: tuple[tuple[re.Pattern[str], str, re.Pattern[str]], ...] = (
    (
        re.compile(r"backend/agent/chat_responder\.py"),
        "personal-path:home",
        re.compile(r"_LOCAL_PATH_RE"),
    ),
    (
        re.compile(r"backend/agent/chat_responder\.py"),
        "personal-path:private-tmp",
        re.compile(r"_LOCAL_PATH_RE"),
    ),
    (
        re.compile(r"backend/tools/.*\.py"),
        "personal-path:private-tmp",
        re.compile(r"/private/tmp/(mingcang_|m[0-9]+_|atlas_|reviewed_)"),
    ),
    (
        re.compile(r"(STATUS\.md|docs/.*\.md)"),
        "personal-path:private-tmp",
        re.compile(r"/private/tmp/"),
    ),
    (
        re.compile(r"frontend/smoke\.cjs"),
        "personal-path:private-tmp",
        re.compile(r"/private/tmp/mingcang_frontend_v2/"),
    ),
    (
        re.compile(r"tests/(test_core_paths_worker_d|test_m29_evidence_ledger|test_m31_cache_and_freshness|test_stock_memory)\.py"),
        "personal-path:private-tmp",
        re.compile(r"/private/tmp/"),
    ),
    (
        re.compile(r"tests/test_stock_memory\.py"),
        "personal-path:home",
        re.compile(r"/Users/example/"),
    ),
)


def repo_root() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(completed.stdout.strip())


def tracked_files(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    paths: list[Path] = []
    for relpath in completed.stdout.splitlines():
        if relpath in {SELF_PATH, TEST_PATH}:
            continue
        paths.append(root / relpath)
    return paths


def _display_path(path: Path, root: Path | None) -> str:
    if root is None:
        return str(path)
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _is_allowlisted_finding(path: str, rule: str, line: str) -> bool:
    if rule == "personal-path:home" and any(placeholder in line for placeholder in HOME_PATH_PLACEHOLDER_ALLOWLIST):
        return True
    for allowed_path, allowed_rule, allowed_pattern in ALLOWLISTED_FINDINGS:
        if path == allowed_path and rule == allowed_rule and allowed_pattern.search(line):
            return True
    for path_pattern, allowed_rule, line_pattern in ALLOWLISTED_FINDING_PATTERNS:
        if path_pattern.fullmatch(path) and rule == allowed_rule and line_pattern.search(line):
            return True
    return False


def scan_paths(paths: Iterable[Path], root: Path | None = None) -> HygieneResult:
    findings: list[HygieneFinding] = []
    allowed_lines = 0
    scanned_files = 0

    for path in paths:
        scanned_files += 1
        display_path = _display_path(path, root)
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if ALLOW_MARKER in line:
                allowed_lines += 1
                continue
            for rule, pattern in RULES:
                if pattern.search(line):
                    if _is_allowlisted_finding(display_path, rule, line):
                        allowed_lines += 1
                        continue
                    findings.append(
                        HygieneFinding(
                            path=display_path,
                            line_number=line_number,
                            snippet=line.strip(),
                            rule=rule,
                        )
                    )
                    break

    return HygieneResult(
        findings=findings,
        allowed_lines=allowed_lines,
        scanned_files=scanned_files,
    )


def scan_tracked_repo(root: Path | None = None) -> HygieneResult:
    scan_root = root if root is not None else repo_root()
    return scan_paths(tracked_files(scan_root), root=scan_root)


def main() -> int:
    result = scan_tracked_repo()
    if result.findings:
        for finding in result.findings:
            print(f"{finding.path}:{finding.line_number}:{finding.snippet}")
        print(
            "release hygiene failed: "
            f"{len(result.findings)} violation(s), "
            f"{result.allowed_lines} allowlisted line(s), "
            f"{result.scanned_files} scanned file(s)",
            file=sys.stderr,
        )
        return 1

    print(
        "release hygiene passed: "
        f"{result.allowed_lines} allowlisted line(s), "
        f"{result.scanned_files} scanned file(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
