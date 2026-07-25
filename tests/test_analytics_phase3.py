from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from manufacturing_monitor.analytics import (
    calculate_series_summary,
    normalize_series_observations,
    process_multiple_series,
)
from manufacturing_monitor.db import (
    DatabaseError,
    ObservationRecord,
    StoredSeriesMetadata,
    ValidatedObservation,
    initialize_schema,
    upsert_validated_observations,
)


def _metadata(series_id: str = "IPMAN") -> StoredSeriesMetadata:
    return StoredSeriesMetadata(
        series_id=series_id,
        display_name="Industrial Production: Manufacturing (NAICS)",
        units="Index 2017=100, Seasonally Adjusted",
        frequency="Monthly",
        updated_at_utc="2026-07-24T00:00:00+00:00",
    )


def _record(series_id: str, date_text: str, value: str) -> ObservationRecord:
    numeric_value = None if value == "." else Decimal(value)
    return ObservationRecord(
        series_id=series_id,
        observation_date=date.fromisoformat(date_text),
        value=value,
        is_missing=value == ".",
        numeric_value=numeric_value,
    )


def _validated(*pairs: tuple[str, str]) -> tuple[ValidatedObservation, ...]:
    return tuple(ValidatedObservation(date=item[0], value=item[1]) for item in pairs)


def _series_db(tmp_path, series_id: str, pairs: tuple[tuple[str, str], ...]) -> str:
    db_path = initialize_schema(tmp_path / "monitor.db")
    upsert_validated_observations(db_path, series_id=series_id, observations=_validated(*pairs))
    return str(db_path)


def test_latest_value_date_and_exact_month_year_changes():
    metadata = _metadata()
    summary = calculate_series_summary(
        [
            _record("IPMAN", "2025-05-01", "50"),
            _record("IPMAN", "2026-04-01", "100"),
            _record("IPMAN", "2026-05-01", "120"),
        ],
        metadata,
    )

    assert summary.latest_valid_value == Decimal("120")
    assert summary.latest_valid_date == date(2026, 5, 1)
    assert summary.previous_month_change.status == "ok"
    assert summary.previous_month_change.value == Decimal("20")
    assert summary.year_over_year_change.status == "ok"
    assert summary.year_over_year_change.value == Decimal("140")


def test_missing_previous_month_returns_clear_status():
    metadata = _metadata()
    summary = calculate_series_summary(
        [
            _record("IPMAN", "2025-05-01", "50"),
            _record("IPMAN", "2026-05-01", "120"),
        ],
        metadata,
    )

    assert summary.previous_month_change.status == "missing_comparison_observation"
    assert "2026-04-01" in (summary.previous_month_change.reason or "")


def test_missing_previous_year_returns_clear_status_for_missing_placeholder():
    metadata = _metadata()
    summary = calculate_series_summary(
        [
            _record("IPMAN", "2025-05-01", "."),
            _record("IPMAN", "2026-05-01", "120"),
        ],
        metadata,
    )

    assert summary.year_over_year_change.status == "missing_comparison_value"
    assert "FRED '.' missing value" in (summary.year_over_year_change.reason or "")


def test_zero_comparison_value_returns_clear_status():
    metadata = _metadata()
    summary = calculate_series_summary(
        [
            _record("IPMAN", "2025-05-01", "0"),
            _record("IPMAN", "2026-05-01", "120"),
        ],
        metadata,
    )

    assert summary.year_over_year_change.status == "zero_comparison_value"
    assert summary.year_over_year_change.value is None


def test_missing_marker_counts_and_basic_statistics():
    metadata = _metadata()
    summary = calculate_series_summary(
        [
            _record("IPMAN", "2025-05-01", "50"),
            _record("IPMAN", "2025-06-01", "."),
            _record("IPMAN", "2026-04-01", "100"),
            _record("IPMAN", "2026-05-01", "120"),
        ],
        metadata,
    )

    assert summary.total_observations == 4
    assert summary.valid_numeric_observations == 3
    assert summary.missing_observations == 1
    assert summary.minimum_value == Decimal("50")
    assert summary.maximum_value == Decimal("120")
    assert summary.arithmetic_mean == Decimal("90")
    assert summary.first_observation_date == date(2025, 5, 1)
    assert summary.last_observation_date == date(2026, 5, 1)


def test_normalization_begins_at_100():
    metadata = _metadata()
    normalized = normalize_series_observations(
        [
            _record("IPMAN", "2025-05-01", "50"),
            _record("IPMAN", "2026-04-01", "100"),
            _record("IPMAN", "2026-05-01", "120"),
        ],
        metadata,
    )

    assert normalized.status == "ok"
    assert normalized.base_date == date(2025, 5, 1)
    assert normalized.rows[0].normalized_value == Decimal("100")
    assert normalized.rows[1].normalized_value == Decimal("200")
    assert normalized.rows[2].normalized_value == Decimal("240")


def test_normalization_with_leading_missing_values():
    metadata = _metadata()
    normalized = normalize_series_observations(
        [
            _record("IPMAN", "2025-03-01", "."),
            _record("IPMAN", "2025-04-01", "."),
            _record("IPMAN", "2025-05-01", "50"),
            _record("IPMAN", "2025-06-01", "100"),
        ],
        metadata,
    )

    assert normalized.rows[0].normalized_value is None
    assert normalized.rows[1].normalized_value is None
    assert normalized.rows[2].normalized_value == Decimal("100")
    assert normalized.rows[3].normalized_value == Decimal("200")


def test_normalization_with_no_valid_numeric_base():
    metadata = _metadata()
    normalized = normalize_series_observations(
        [
            _record("IPMAN", "2025-03-01", "."),
            _record("IPMAN", "2025-04-01", "."),
        ],
        metadata,
    )

    assert normalized.status == "no_valid_base_value"
    assert normalized.base_value is None
    assert all(row.normalized_value is None for row in normalized.rows)


def test_multi_series_sqlite_processing_and_date_range_filtering(tmp_path):
    db_path = initialize_schema(tmp_path / "monitor.db")
    upsert_validated_observations(
        db_path,
        series_id="IPMAN",
        observations=_validated(
            ("2025-05-01", "50"),
            ("2026-04-01", "100"),
            ("2026-05-01", "120"),
        ),
    )
    upsert_validated_observations(
        db_path,
        series_id="IPDMAN",
        observations=_validated(
            ("2025-05-01", "80"),
            ("2026-04-01", "."),
            ("2026-05-01", "90"),
        ),
    )

    result = process_multiple_series(
        db_path,
        series_ids=("IPDMAN", "IPMAN"),
        observation_start="2026-04-01",
        observation_end="2026-05-01",
    )

    assert result.status == "ok"
    assert result.requested_series_ids == ("IPDMAN", "IPMAN")
    assert [item.metadata.series_id for item in result.series_results] == ["IPDMAN", "IPMAN"]
    assert [row.series_id for row in result.observation_rows] == ["IPDMAN", "IPDMAN", "IPMAN", "IPMAN"]
    assert [row.date for row in result.observation_rows] == [
        date(2026, 4, 1),
        date(2026, 5, 1),
        date(2026, 4, 1),
        date(2026, 5, 1),
    ]
    assert result.series_results[1].summary.latest_valid_value == Decimal("120")
    assert result.series_results[0].normalized.rows[0].normalized_value is None


def test_empty_cached_result_behavior(tmp_path):
    db_path = initialize_schema(tmp_path / "monitor.db")

    result = process_multiple_series(
        db_path,
        series_ids=("IPMAN",),
        observation_start="2026-01-01",
        observation_end="2026-02-01",
    )

    assert result.status == "empty"
    assert result.observation_rows == ()
    assert result.normalized_rows == ()
    assert result.series_results[0].summary.status == "empty"


def test_unsupported_series_is_rejected(tmp_path):
    db_path = initialize_schema(tmp_path / "monitor.db")

    with pytest.raises(DatabaseError, match="Unsupported series ID"):
        process_multiple_series(db_path, series_ids=("NOTREAL",))


def test_invalid_date_range_is_rejected(tmp_path):
    db_path = initialize_schema(tmp_path / "monitor.db")

    with pytest.raises(ValueError, match="cannot be after observation_end"):
        process_multiple_series(
            db_path,
            series_ids=("IPMAN",),
            observation_start="2026-05-01",
            observation_end="2026-04-01",
        )


def test_normalization_with_multiple_series(tmp_path):
    db_path = initialize_schema(tmp_path / "monitor.db")
    upsert_validated_observations(
        db_path,
        series_id="IPMAN",
        observations=_validated(("2025-05-01", "50"), ("2025-06-01", "75")),
    )
    upsert_validated_observations(
        db_path,
        series_id="IPDMAN",
        observations=_validated(("2025-05-01", "25"), ("2025-06-01", "50")),
    )

    result = process_multiple_series(db_path, series_ids=("IPMAN", "IPDMAN"))

    normalized = {
        (row.series_id, row.date): row.normalized_value for row in result.normalized_rows
    }

    assert normalized[("IPMAN", date(2025, 5, 1))] == Decimal("100")
    assert normalized[("IPMAN", date(2025, 6, 1))] == Decimal("150")
    assert normalized[("IPDMAN", date(2025, 5, 1))] == Decimal("100")
    assert normalized[("IPDMAN", date(2025, 6, 1))] == Decimal("200")
