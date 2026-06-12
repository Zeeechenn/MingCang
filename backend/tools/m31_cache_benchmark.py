"""M31 read-only cache-layer latency benchmark.

Default mode measures L1/L2 only. L3 is described by policy and intentionally
not called, so the benchmark is safe to run during market hours.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func

from backend.data.cache_policy import cache_policy_payload
from backend.data.database import Price, SessionLocal, Stock
from backend.data.market import register_default_market_providers
from backend.data.providers import provider_fallback_chains

DEFAULT_ITERATIONS = 20
DEFAULT_JSON_OUTPUT = Path("/private/tmp/m31_cache_benchmark.json")
DEFAULT_MARKDOWN_OUTPUT = Path("/private/tmp/m31_cache_benchmark.md")


def _duration_ms(fn: Callable[[], Any]) -> float:
    start = time.perf_counter_ns()
    fn()
    return (time.perf_counter_ns() - start) / 1_000_000


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return ordered[index]


def _measure_layer(layer: str, concept: str, fn: Callable[[], Any], iterations: int) -> dict[str, Any]:
    durations = [_duration_ms(fn) for _ in range(iterations)]
    return {
        "layer": layer,
        "concept": concept,
        "iterations": iterations,
        "min_ms": round(min(durations), 4),
        "p50_ms": round(statistics.median(durations), 4),
        "p95_ms": round(_percentile(durations, 0.95), 4),
        "max_ms": round(max(durations), 4),
        "mean_ms": round(statistics.fmean(durations), 4),
    }


def _unmeasured_layer(layer: str, concept: str, reason: str) -> dict[str, Any]:
    return {
        "layer": layer,
        "concept": concept,
        "measured": False,
        "reason": reason,
    }


def run_benchmark(
    iterations: int = DEFAULT_ITERATIONS,
    symbol: str = "600519",
    session_factory=SessionLocal,
) -> dict[str, Any]:
    """Run the M31 cache benchmark without provider/network calls or DB writes."""
    if iterations <= 0:
        raise ValueError("iterations must be positive")

    register_default_market_providers()
    l1_cache = {"symbol": symbol, "close": 100.0}
    layers = [
        _measure_layer(
            "L1",
            "in_process_memory_lookup",
            lambda: l1_cache["close"],
            iterations,
        ),
    ]
    db = None
    try:
        db = session_factory()
        layers.extend([
            _measure_layer(
                "L2",
                "sqlite_single_stock_latest_price",
                lambda: (
                    db.query(Price.date, Price.close)
                    .filter(Price.symbol == symbol)
                    .order_by(Price.date.desc())
                    .first()
                ),
                iterations,
            ),
            _measure_layer(
                "L2",
                "sqlite_market_scan_counts",
                lambda: {
                    "active_stocks": int(db.query(func.count(Stock.symbol)).filter(Stock.active).scalar() or 0),
                    "price_rows": int(db.query(func.count(Price.id)).scalar() or 0),
                    "latest_price_date": db.query(func.max(Price.date)).scalar(),
                },
                iterations,
            ),
        ])
    except Exception as exc:
        layers.extend([
            _unmeasured_layer("L2", "sqlite_single_stock_latest_price", str(exc)),
            _unmeasured_layer("L2", "sqlite_market_scan_counts", str(exc)),
        ])
    finally:
        if db is not None:
            db.close()

    layers.append(_unmeasured_layer(
        "L3",
        "remote_api_incremental",
        "default benchmark does not call remote providers",
    ))

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "benchmark_id": "m31_cache_latency_readonly",
        "iterations": iterations,
        "symbol": symbol,
        "safety": {
            "network_calls_attempted": False,
            "mingcang_db_writes_attempted": False,
            "llm_calls_attempted": False,
            "default_outputs_under_private_tmp": True,
        },
        "cache_policy": cache_policy_payload(),
        "provider_fallback_chains": provider_fallback_chains("CN"),
        "layers": layers,
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    """Render a compact Markdown benchmark report."""
    lines = [
        "# M31 Cache Benchmark",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- iterations: {report['iterations']}",
        f"- network_calls_attempted: {report['safety']['network_calls_attempted']}",
        f"- mingcang_db_writes_attempted: {report['safety']['mingcang_db_writes_attempted']}",
        "",
        "| Layer | Concept | measured | p50 ms | p95 ms | min ms | max ms |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["layers"]:
        lines.append(
            "| {layer} | {concept} | {measured} | {p50} | {p95} | {min_} | {max_} |".format(
                layer=row["layer"],
                concept=row["concept"],
                measured=row.get("measured", True),
                p50=row.get("p50_ms", ""),
                p95=row.get("p95_ms", ""),
                min_=row.get("min_ms", ""),
                max_=row.get("max_ms", ""),
            )
        )
    lines.extend([
        "",
        "## Intraday Policy",
        f"- allowed_layers: {', '.join(report['cache_policy']['workflow_policies']['intraday']['allowed_layers'])}",
        f"- remote_fetch_allowed: {report['cache_policy']['workflow_policies']['intraday']['remote_fetch_allowed']}",
    ])
    return "\n".join(lines) + "\n"


def write_reports(report: dict[str, Any], json_output: Path, markdown_output: Path) -> None:
    """Write benchmark JSON and Markdown reports."""
    json_path = json_output.expanduser()
    markdown_path = markdown_output.expanduser()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(report_to_markdown(report), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--symbol", default="600519")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true", help="Print the Markdown report.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    report = run_benchmark(iterations=args.iterations, symbol=args.symbol)
    write_reports(report, args.json_output, args.markdown_output)
    if args.print:
        print(report_to_markdown(report))
    print(f"JSON report: {args.json_output.expanduser()}")
    print(f"Markdown report: {args.markdown_output.expanduser()}")
    return report


if __name__ == "__main__":
    main()
