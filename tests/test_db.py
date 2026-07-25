from __future__ import annotations

from contextlib import closing
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from manufacturing_monitor.db import (
    FETCH_SOURCE_FIXTURE_OR_CACHE,
    FETCH_SOURCE_LIVE,
    ValidatedObservation,
    cached_observations_exist,
    get_latest_fetch_information,
    initialize_schema,
    read_multiple_observations,
    read_observations,
    record_fetch_run,
    upsert_validated_observations,
)
from manufacturing_monitor.workflow import MonitorRequest, build_monitor_result, run_monitor


def _observations(*pairs: tuple[str, str]) -> tuple[ValidatedObservation, ...]:
    return tuple(ValidatedObservation(date=item[0], value=item[1]) for item in pairs)


def test_initialize_schema_creates_parent_directory_and_tables(tmp_path):
    db_path = tmp_path / "nested" / "monitor.db"

    path = initialize_schema(db_path)

    assert path == db_path
    assert db_path.exists()
    with closing(sqlite3.connect(db_path)) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        }

    assert {"fetch_runs", "supported_series", "validated_observations"} <= tables


def test_supported_series_metadata_is_saved(tmp_path):
    db_path = initialize_schema(tmp_path / "monitor.db")

    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute(
            """
            SELECT display_name, units, frequency
            FROM supported_series
            WHERE series_id = ?
            """,
            ("IPMAN",),
        ).fetchone()

    assert row == (
        "Industrial Production: Manufacturing (NAICS)",
        "Index 2017=100, Seasonally Adjusted",
        "Monthly",
    )


def test_observation_insertion_preserves_numeric_and_missing_values(tmp_path):
    db_path = initialize_schema(tmp_path / "monitor.db")
    upsert_validated_observations(
        db_path,
        series_id="IPMAN",
        observations=_observations(("2026-01-01", "101.0"), ("2026-02-01", ".")),
    )

    rows = read_observations(db_path, series_id="IPMAN")

    assert rows[0].series_id == "IPMAN"
    assert rows[0].observation_date == date(2026, 1, 1)
    assert rows[0].value == "101.0"
    assert rows[0].is_missing is False
    assert rows[0].numeric_value == Decimal("101.0")
    assert rows[1].value == "."
    assert rows[1].is_missing is True
    assert rows[1].numeric_value is None


def test_duplicate_safe_upsert_and_update_existing_row(tmp_path):
    db_path = initialize_schema(tmp_path / "monitor.db")
    upsert_validated_observations(
        db_path,
        series_id="IPMAN",
        observations=_observations(("2026-01-01", "101.0")),
    )
    upsert_validated_observations(
        db_path,
        series_id="IPMAN",
        observations=_observations(("2026-01-01", "102.5")),
    )

    with closing(sqlite3.connect(db_path)) as connection:
        count = connection.execute(
            """
            SELECT COUNT(*)
            FROM validated_observations
            WHERE series_id = ? AND observation_date = ?
            """,
            ("IPMAN", "2026-01-01"),
        ).fetchone()[0]

    assert count == 1
    assert read_observations(db_path, series_id="IPMAN")[0].numeric_value == Decimal(
        "102.5"
    )


def test_one_series_query_and_empty_results(tmp_path):
    db_path = initialize_schema(tmp_path / "monitor.db")
    upsert_validated_observations(
        db_path,
        series_id="IPMAN",
        observations=_observations(
            ("2026-01-01", "101.0"),
            ("2026-02-01", "102.0"),
            ("2026-03-01", "103.0"),
        ),
    )

    assert read_observations(
        db_path,
        series_id="IPMAN",
        observation_start="2026-02-01",
        observation_end="2026-03-01",
    ) == (
        read_observations(db_path, series_id="IPMAN")[1],
        read_observations(db_path, series_id="IPMAN")[2],
    )
    assert read_observations(
        db_path,
        series_id="IPMAN",
        observation_start="2027-01-01",
        observation_end="2027-02-01",
    ) == ()


def test_multiple_series_query_groups_results(tmp_path):
    db_path = initialize_schema(tmp_path / "monitor.db")
    upsert_validated_observations(
        db_path,
        series_id="IPMAN",
        observations=_observations(("2026-01-01", "101.0")),
    )
    upsert_validated_observations(
        db_path,
        series_id="IPDMAN",
        observations=_observations(("2026-01-01", "91.0"), ("2026-02-01", "92.0")),
    )

    rows = read_multiple_observations(
        db_path,
        series_ids=("IPDMAN", "IPMAN"),
        observation_start="2026-01-01",
        observation_end="2026-02-01",
    )

    assert list(rows) == ["IPDMAN", "IPMAN"]
    assert len(rows["IPDMAN"]) == 2
    assert len(rows["IPMAN"]) == 1


def test_invalid_date_ranges_are_rejected(tmp_path):
    db_path = initialize_schema(tmp_path / "monitor.db")

    with pytest.raises(ValueError, match="cannot be after observation_end"):
        read_observations(
            db_path,
            series_id="IPMAN",
            observation_start="2026-03-01",
            observation_end="2026-01-01",
        )


def test_cached_observations_exist_checks_requested_range(tmp_path):
    db_path = initialize_schema(tmp_path / "monitor.db")
    upsert_validated_observations(
        db_path,
        series_id="IPMAN",
        observations=_observations(("2026-01-01", "101.0")),
    )

    assert cached_observations_exist(
        db_path,
        series_id="IPMAN",
        observation_start="2026-01-01",
        observation_end="2026-01-01",
    )
    assert not cached_observations_exist(
        db_path,
        series_id="IPMAN",
        observation_start="2027-01-01",
        observation_end="2027-02-01",
    )


def test_fetch_run_recording_and_latest_fetch_information(tmp_path):
    db_path = initialize_schema(tmp_path / "monitor.db")
    first = record_fetch_run(
        db_path,
        series_id="IPMAN",
        requested_start_date=date(2026, 1, 1),
        requested_end_date=date(2026, 2, 1),
        validated_observation_count=2,
        source_kind=FETCH_SOURCE_LIVE,
        fetched_at_utc=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    second = record_fetch_run(
        db_path,
        series_id="IPDMAN",
        requested_start_date=None,
        requested_end_date=None,
        validated_observation_count=3,
        source_kind=FETCH_SOURCE_FIXTURE_OR_CACHE,
        fetched_at_utc=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
    )

    assert first.series_id == "IPMAN"
    assert second.source_kind == FETCH_SOURCE_FIXTURE_OR_CACHE
    assert get_latest_fetch_information(db_path) == second
    assert get_latest_fetch_information(db_path, series_id="IPMAN") == first


def test_workflow_storage_integration_uses_validated_data(tmp_path, monkeypatch):
    payload = {
        "observations": [
            {"date": "2026-01-01", "value": "101.0"},
            {"date": "2026-02-01", "value": "."},
        ]
    }
    db_path = tmp_path / "workflow.db"
    monkeypatch.setattr(
        "manufacturing_monitor.workflow.fetch_monitor_data",
        lambda _request: payload,
    )

    result = run_monitor(
        MonitorRequest(api_key="integration-test-key", series_id="IPMAN"),
        db_path=db_path,
        source_kind=FETCH_SOURCE_FIXTURE_OR_CACHE,
    )

    assert result.latest.value == "101.0"
    assert read_observations(db_path, series_id="IPMAN")[0].value == "101.0"
    assert get_latest_fetch_information(db_path, series_id="IPMAN").source_kind == (
        FETCH_SOURCE_FIXTURE_OR_CACHE
    )


def test_no_secret_is_stored_in_database(tmp_path, monkeypatch):
    secret = "FAKE_SECRET_DO_NOT_STORE"
    payload = build_monitor_result(
        {
            "observations": [
                {"date": "2026-01-01", "value": "101.0"},
            ]
        }
    )
    db_path = tmp_path / "secret-check.db"
    monkeypatch.setattr(
        "manufacturing_monitor.workflow.fetch_monitor_data",
        lambda _request: payload.raw_payload,
    )

    run_monitor(
        MonitorRequest(api_key=secret, series_id="IPMAN"),
        db_path=db_path,
        source_kind=FETCH_SOURCE_FIXTURE_OR_CACHE,
    )

    db_bytes = db_path.read_bytes()
    assert secret.encode("utf-8") not in db_bytes

    with closing(sqlite3.connect(db_path)) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(fetch_runs)").fetchall()
        }
        schema_text = "\n".join(
            row[0]
            for row in connection.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"
            ).fetchall()
        )

    assert "api_key" not in columns
    assert secret not in schema_text
