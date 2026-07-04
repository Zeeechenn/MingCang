from __future__ import annotations

from backend.tools import m61_source_health as health


def test_registry_lists_probes() -> None:
    probes = health.registered_probe_matrix()

    assert len(probes) > 0
    assert all({"source", "category"} <= set(item) for item in probes)


def test_failing_probe_does_not_break_sweep() -> None:
    def failing_probe(symbols: list[str]) -> health.ProbeResult:
        raise RuntimeError("boom from unit test")

    registry = [
        health.ProbeSpec("unit", "news", failing_probe),
        health.ProbeSpec(
            "unit",
            "quotes",
            lambda symbols: health.ProbeResult(
                calls=[health.CallSample(rows=2, content_non_empty=2, latency_ms=1.0)]
            ),
        ),
    ]

    payload = health.run_sweep(source="unit", category=None, registry=registry)

    assert payload["summary"]["n_probed"] == 2
    assert payload["summary"]["n_available"] == 1
    failed = next(item for item in payload["results"] if item["category"] == "news")
    assert failed["available"] is False
    assert failed["stability"]["failures"] == 1
    assert "boom from unit test" in failed["stability"]["error_samples"][0]


def test_sweep_json_schema_keys_present() -> None:
    registry = [
        health.ProbeSpec(
            "unit",
            "news",
            lambda symbols: health.ProbeResult(
                calls=[
                    health.CallSample(
                        rows=1,
                        content_non_empty=1,
                        latency_ms=2.0,
                        supports_date_range=True,
                        dates=["2026-02-10"],
                    )
                ]
            ),
        )
    ]

    payload = health.run_sweep(source="unit", category="news", registry=registry)
    result = payload["results"][0]

    assert payload["schema_version"] == "m61_source_health.v1"
    assert {"generated_at", "results", "summary"} <= set(payload)
    assert {
        "source",
        "category",
        "available",
        "coverage",
        "backfill",
        "completeness",
        "latency_ms",
        "stability",
        "pit_verdict",
    } <= set(result)
    assert result["backfill"]["supports_date_range"] is True
    assert result["pit_verdict"] == "clean"
