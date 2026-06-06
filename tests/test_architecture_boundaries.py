"""Architecture boundary checks for the StockSage modular monolith.

These tests intentionally parse source with ``ast`` instead of importing backend
modules, so they cannot trigger provider registration, network clients, or DB
initialization while checking import boundaries.
"""
import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"


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
