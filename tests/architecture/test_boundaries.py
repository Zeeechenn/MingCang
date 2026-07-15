"""Architecture boundary checks for the 明仓 / MingCang modular monolith.

These tests intentionally parse source with ``ast`` instead of importing backend
modules, so they cannot trigger provider registration, network clients, or DB
initialization while checking import boundaries.
"""
import ast
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
FRONTEND_ROOT = PROJECT_ROOT / "frontend" / "src"
CORE_DOMAIN_DIRS = (
    "analysis",
    "api",
    "backtest",
    "data",
    "decision",
    "evidence",
    "jobs",
    "llm",
    "memory",
    "ops",
    "portfolio",
    "research",
)
WORKFLOW_TOOL_MIGRATION_ALLOWLIST = {
    "backend.tools.m54_daily_accrual",
    "backend.tools.m58_exit_shadow",
    "backend.tools.m59_discretion",
    "backend.tools.m59_panel",
    "backend.tools.m60_second_entry",
    "backend.tools.m60_watchtower",
    "backend.tools.m61_backfill",
    "backend.tools.m63_trade_journal",
}
LEGACY_FRONTEND_IMPORT = re.compile(
    r"(?:from\s+|import\s*\(\s*)['\"](?:\.\.?/)+(?:api|live)['\"]"
)


def _backend_modules() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in BACKEND_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        module = ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts)
        modules[module] = path
    return modules


def _top_level_backend_imports(path: Path, known_modules: set[str]) -> set[str]:
    tree = ast.parse(path.read_text())
    imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("backend.") and alias.name in known_modules:
                    imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if not node.module or not node.module.startswith("backend."):
                continue
            if node.module in known_modules:
                imports.add(node.module)
            for alias in node.names:
                candidate = f"{node.module}.{alias.name}"
                if candidate in known_modules:
                    imports.add(candidate)
    return imports


def _find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    visited: set[str] = set()
    visiting: set[str] = set()
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(module: str) -> None:
        if module in visited:
            return
        if module in visiting:
            cycle_start = stack.index(module)
            cycles.append(stack[cycle_start:] + [module])
            return

        visiting.add(module)
        stack.append(module)
        for dep in sorted(graph[module]):
            visit(dep)
        stack.pop()
        visiting.remove(module)
        visited.add(module)

    for module in sorted(graph):
        visit(module)
    return cycles


def test_backend_top_level_import_graph_has_no_cycles():
    modules = _backend_modules()
    graph = {
        module: _top_level_backend_imports(path, set(modules))
        for module, path in modules.items()
    }

    cycles = _find_cycles(graph)

    assert cycles == []


def test_api_routes_do_not_directly_import_heavy_provider_clients():
    heavy_clients = {"akshare", "efinance", "requests", "tushare", "yfinance"}
    offenders: list[str] = []
    for path in (BACKEND_ROOT / "api" / "routes").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            imported: set[str] = set()
            if isinstance(node, ast.Import):
                imported = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = {node.module.split(".")[0]}
            for module in sorted(imported & heavy_clients):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")

    assert offenders == []


def test_core_domains_do_not_import_tool_implementations():
    """Keep CLI/maintenance adapters downstream of stable domain modules."""
    offenders: list[str] = []
    for directory in CORE_DOMAIN_DIRS:
        for path in (BACKEND_ROOT / directory).rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = [node.module]
                else:
                    imported = []
                for module in imported:
                    if module == "backend.tools" or module.startswith("backend.tools."):
                        offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")

    assert offenders == []


def test_workflow_tool_migration_allowlist_can_only_shrink():
    """Prevent Phase 1b debt from expanding while capabilities migrate."""
    imported: set[str] = set()
    for path in (BACKEND_ROOT / "workflows").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(
                    alias.name
                    for alias in node.names
                    if alias.name.startswith("backend.tools.")
                )
            elif isinstance(node, ast.ImportFrom) and node.module == "backend.tools":
                imported.update(f"backend.tools.{alias.name}" for alias in node.names)
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("backend.tools.")
            ):
                imported.add(node.module)

    assert imported <= WORKFLOW_TOOL_MIGRATION_ALLOWLIST


def test_frontend_production_code_uses_service_boundaries():
    """Keep root API/live files as compatibility exports, not new imports."""
    offenders: list[str] = []
    for path in FRONTEND_ROOT.rglob("*"):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        if "__tests__" in path.parts or path.name in {"api.ts", "live.ts"}:
            continue
        if LEGACY_FRONTEND_IMPORT.search(path.read_text()):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []


def test_m66_legacy_modules_alias_canonical_implementations():
    from backend.backtest import quant_baseline
    from backend.data import flow_floor
    from backend.evidence import lookahead_audit
    from backend.tools import (
        m26_quant_baseline,
        m46_5_lookahead_one_time_audit,
        m52_flow_floor,
        m63_daily,
        m63_render,
    )
    from backend.workflows import m63_daily as daily_workflow
    from backend.workflows import render

    assert m26_quant_baseline is quant_baseline
    assert m46_5_lookahead_one_time_audit is lookahead_audit
    assert m52_flow_floor is flow_floor
    assert m63_daily is daily_workflow
    assert m63_render is render


def test_core_facades_stay_below_growth_thresholds():
    thresholds = {
        "backend/data/market.py": 220,
        "backend/api/routes/ai.py": 380,
        "backend/scheduler.py": 365,
    }
    offenders = []
    for relpath, max_lines in thresholds.items():
        line_count = len((PROJECT_ROOT / relpath).read_text().splitlines())
        if line_count > max_lines:
            offenders.append(f"{relpath}: {line_count} > {max_lines}")

    assert offenders == []
