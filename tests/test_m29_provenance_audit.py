def test_build_audit_reports_price_schema_and_artifact_blockers(monkeypatch):
    from backend.tools import m29_provenance_audit as tool

    monkeypatch.setattr(
        tool.m29_evidence_ledger,
        "build_ledger",
        lambda paths: {
            "entries": [
                {
                    "candidate": "top_decile_entry_filter",
                    "variant": "rolling_1d",
                    "source_artifact": "/tmp/a.json",
                    "provenance": {
                        "missing_provenance_fields": ["data_source", "fetched_at", "adjustment"],
                    },
                },
                {
                    "candidate": "top_decile_entry_filter",
                    "variant": "rolling_3d",
                    "source_artifact": "/tmp/b.json",
                    "provenance": {"missing_provenance_fields": []},
                },
            ],
        },
    )

    report = tool.build_audit([])
    markdown = tool.report_to_markdown(report)

    assert report["run_mode"] == "read_only_provenance_audit"
    assert report["writes_db"] is False
    assert report["calls_llm_or_api"] is False
    assert report["saves_model"] is False
    assert report["price_schema"]["table"] == "prices"
    assert report["price_schema"]["missing"] == []
    assert report["index_price_schema"]["missing"] == []
    assert report["market_snapshot_schema"]["missing"] == []
    assert report["artifact_provenance"]["entries_with_missing_provenance"] == 1
    assert report["artifact_provenance"]["missing_by_field"]["data_source"] == 1
    assert "artifact_provenance_incomplete" in report["blockers"]
    assert "daily_price_provenance_not_in_schema" not in report["blockers"]
    assert "M29 Provenance Audit" in markdown


def test_entry_missing_summary_counts_fields():
    from backend.tools import m29_provenance_audit as tool

    summary = tool._entry_missing_summary({
        "entries": [
            {"provenance": {"missing_provenance_fields": ["data_source"]}},
            {"provenance": {"missing_provenance_fields": ["data_source", "universe_hash"]}},
            {"provenance": {"missing_provenance_fields": []}},
        ],
    })

    assert summary["entries"] == 3
    assert summary["entries_with_missing_provenance"] == 2
    assert summary["missing_by_field"]["data_source"] == 2
    assert summary["missing_by_field"]["universe_hash"] == 1
