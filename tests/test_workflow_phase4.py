from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from manufacturing_monitor.db import (
    get_latest_fetch_information,
    initialize_schema,
    read_observations,
    ValidatedObservation,
    upsert_validated_observations,
)
from manufacturing_monitor.workflow import ApplicationRequest, WorkflowError, run_application_workflow


def _payload(value_a: str, value_b: str) -> dict[str, object]:
    return {
        "observations": [
            {"date": "2026-04-01", "value": value_a},
            {"date": "2026-05-01", "value": value_b},
        ]
    }


def _seed_cache(db_path: Path, series_id: str, *values: str) -> None:
    initialize_schema(db_path)
    upsert_validated_observations(
        db_path,
        series_id=series_id,
        observations=tuple(
            ValidatedObservation(date=f"2026-0{index + 4}-01", value=value)
            for index, value in enumerate(values)
        ),
    )


def test_shared_workflow_cached_source_without_api_key(tmp_path, monkeypatch):
    db_path = tmp_path / "cache.db"
    _seed_cache(db_path, "IPMAN", "99.0", "101.0")
    fetch = Mock(side_effect=AssertionError("live fetch should not happen"))
    monkeypatch.setattr("manufacturing_monitor.workflow.fetch_monitor_data", fetch)
    monkeypatch.chdir(tmp_path)

    result = run_application_workflow(
        ApplicationRequest(
            series_ids=("IPMAN",),
            cache_only=True,
            db_path=db_path,
        )
    )

    assert result.source_status == "cache"
    assert result.analysis.status == "ok"
    assert result.series_results[0].source_kind == "cache"
    assert result.raw_paths == {}
    assert result.csv_path is None
    assert fetch.call_count == 0
    assert read_observations(db_path, series_id="IPMAN")[0].value == "99.0"


def test_shared_workflow_empty_cache_without_key_fails_clearly(tmp_path):
    db_path = tmp_path / "empty.db"
    initialize_schema(db_path)

    with pytest.raises(WorkflowError, match="API key is required"):
        run_application_workflow(
            ApplicationRequest(
                series_ids=("IPMAN",),
                db_path=db_path,
            )
        )


def test_shared_workflow_refresh_without_key_fails_clearly(tmp_path):
    db_path = tmp_path / "refresh.db"
    initialize_schema(db_path)

    with pytest.raises(WorkflowError, match="refresh mode is selected"):
        run_application_workflow(
            ApplicationRequest(
                series_ids=("IPMAN",),
                db_path=db_path,
                refresh=True,
            )
        )


def test_shared_workflow_mixed_or_partial_cache_behavior(tmp_path, monkeypatch):
    db_path = tmp_path / "mixed.db"
    _seed_cache(db_path, "IPMAN", "99.0", "101.0")
    fetch = Mock(side_effect=lambda request: _payload("86.0", "88.0"))
    monkeypatch.setattr("manufacturing_monitor.workflow.fetch_monitor_data", fetch)
    monkeypatch.chdir(tmp_path)

    result = run_application_workflow(
        ApplicationRequest(
            series_ids=("IPMAN", "IPDMAN"),
            api_key="test-key",
            db_path=db_path,
        )
    )

    assert result.source_status == "mixed"
    assert result.series_results[0].source_kind == "cache"
    assert result.series_results[1].source_kind == "live"
    assert set(result.raw_paths) == {"IPDMAN"}
    assert fetch.call_count == 1
    assert get_latest_fetch_information(db_path, series_id="IPDMAN").source_kind == "live"


def test_shared_workflow_live_refresh_writes_raw_processed_and_csv(tmp_path, monkeypatch):
    db_path = tmp_path / "live.db"
    output_csv = tmp_path / "exports" / "combined.csv"
    fetch = Mock(
        side_effect=lambda request: _payload(
            "99.0" if request.series_id == "IPMAN" else "86.0",
            "101.0" if request.series_id == "IPMAN" else "88.0",
        )
    )
    monkeypatch.setattr("manufacturing_monitor.workflow.fetch_monitor_data", fetch)
    monkeypatch.chdir(tmp_path)

    result = run_application_workflow(
        ApplicationRequest(
            series_ids=("IPMAN", "IPDMAN"),
            api_key="test-key",
            db_path=db_path,
            refresh=True,
            csv_output=output_csv,
        )
    )

    raw_one = tmp_path / "data" / "raw" / "ipman_observations_raw.json"
    raw_two = tmp_path / "data" / "raw" / "ipdman_observations_raw.json"
    processed = tmp_path / "data" / "processed" / "ipman-ipdman_combined_processed.json"

    assert result.source_status == "live"
    assert raw_one.exists()
    assert raw_two.exists()
    assert processed.exists()
    assert output_csv.exists()
    assert result.csv_path == output_csv
    assert read_observations(db_path, series_id="IPMAN")[0].value == "99.0"
    assert read_observations(db_path, series_id="IPDMAN")[1].value == "88.0"
    assert get_latest_fetch_information(db_path, series_id="IPMAN").source_kind == "live"

    payload = json.loads(processed.read_text(encoding="utf-8"))
    assert payload["requested_series_ids"] == ["IPMAN", "IPDMAN"]
    assert payload["source_status"] == "live"
    assert [series["series_id"] for series in payload["series"]] == ["IPMAN", "IPDMAN"]
    assert payload["series"][0]["summary"]["series_name"] == "Industrial Production: Manufacturing (NAICS)"
    assert {row["series_id"] for row in payload["combined_rows"]} == {"IPMAN", "IPDMAN"}
    assert {row["raw_value"] for row in payload["combined_rows"]} == {"99.0", "101.0", "86.0", "88.0"}
    assert {row["normalized_value"] for row in payload["normalized_rows"]} >= {"100"}
    assert "series_id,series_name,units,date,raw_value,is_missing,normalized_value" in output_csv.read_text(encoding="utf-8")
