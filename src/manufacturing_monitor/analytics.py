from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from manufacturing_monitor.db import (
    DEFAULT_DATABASE_PATH,
    DatabaseError,
    ObservationRecord,
    StoredSeriesMetadata,
    read_multiple_observations,
    read_supported_series_metadata,
)
from manufacturing_monitor.series_catalog import is_supported_series, supported_series_ids


_HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class PercentageChangeResult:
    """Result of an exact date-based percentage-change calculation."""

    status: str
    reason: str | None
    value: Decimal | None
    latest_date: date | None
    latest_value: Decimal | None
    comparison_date: date | None
    comparison_value: Decimal | None


@dataclass(frozen=True, slots=True)
class SeriesSummary:
    """Shared analytics summary for one supported series."""

    series_id: str
    series_name: str
    units: str
    frequency: str
    latest_valid_value: Decimal | None
    latest_valid_date: date | None
    previous_month_change: PercentageChangeResult
    year_over_year_change: PercentageChangeResult
    minimum_value: Decimal | None
    maximum_value: Decimal | None
    arithmetic_mean: Decimal | None
    total_observations: int
    valid_numeric_observations: int
    missing_observations: int
    first_observation_date: date | None
    last_observation_date: date | None
    status: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class SeriesObservationRow:
    """Observation row prepared for comparison or export."""

    series_id: str
    series_name: str
    units: str
    date: date
    raw_value: str
    is_missing: bool
    normalized_value: Decimal | None = None


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """Normalized comparison rows for one series."""

    status: str
    reason: str | None
    base_date: date | None
    base_value: Decimal | None
    rows: tuple[SeriesObservationRow, ...]


@dataclass(frozen=True, slots=True)
class SeriesResult:
    """Processed observations and analytics for one series."""

    metadata: StoredSeriesMetadata
    summary: SeriesSummary
    observations: tuple[SeriesObservationRow, ...]
    normalized: NormalizationResult


@dataclass(frozen=True, slots=True)
class MultiSeriesResult:
    """Combined result for one or more supported series."""

    requested_series_ids: tuple[str, ...]
    requested_start_date: date | None
    requested_end_date: date | None
    status: str
    reason: str | None
    series_results: tuple[SeriesResult, ...]
    observation_rows: tuple[SeriesObservationRow, ...]
    normalized_rows: tuple[SeriesObservationRow, ...]


def calculate_series_summary(
    observations: Sequence[ObservationRecord],
    metadata: StoredSeriesMetadata,
) -> SeriesSummary:
    """Calculate descriptive statistics and exact-date changes for one series."""

    ordered = tuple(sorted(observations, key=lambda item: item.observation_date))
    numeric_values = tuple(
        record.numeric_value
        for record in ordered
        if record.numeric_value is not None and not record.is_missing
    )
    missing_observations = sum(1 for record in ordered if record.is_missing)
    first_observation_date = ordered[0].observation_date if ordered else None
    last_observation_date = ordered[-1].observation_date if ordered else None
    latest_valid_record = _latest_valid_numeric_record(ordered)

    if not ordered:
        status = "empty"
        reason = "No cached observations were available for the requested series."
        latest_valid_value = None
        latest_valid_date = None
    elif latest_valid_record is None:
        status = "no_valid_numeric_observations"
        reason = "No valid numeric observations were available for the requested series."
        latest_valid_value = None
        latest_valid_date = None
    else:
        status = "ok"
        reason = None
        latest_valid_value = latest_valid_record.numeric_value
        latest_valid_date = latest_valid_record.observation_date

    return SeriesSummary(
        series_id=metadata.series_id,
        series_name=metadata.display_name,
        units=metadata.units,
        frequency=metadata.frequency,
        latest_valid_value=latest_valid_value,
        latest_valid_date=latest_valid_date,
        previous_month_change=_calculate_exact_date_change(
            ordered,
            latest_valid_record=latest_valid_record,
            months_back=1,
            label="previous-month",
        ),
        year_over_year_change=_calculate_exact_date_change(
            ordered,
            latest_valid_record=latest_valid_record,
            months_back=12,
            label="year-over-year",
        ),
        minimum_value=min(numeric_values) if numeric_values else None,
        maximum_value=max(numeric_values) if numeric_values else None,
        arithmetic_mean=_mean(numeric_values) if numeric_values else None,
        total_observations=len(ordered),
        valid_numeric_observations=len(numeric_values),
        missing_observations=missing_observations,
        first_observation_date=first_observation_date,
        last_observation_date=last_observation_date,
        status=status,
        reason=reason,
    )


def normalize_series_observations(
    observations: Sequence[ObservationRecord],
    metadata: StoredSeriesMetadata,
) -> NormalizationResult:
    """Normalize one series so the first valid numeric observation equals 100."""

    ordered = tuple(sorted(observations, key=lambda item: item.observation_date))
    rows = tuple(_build_observation_row(record, metadata) for record in ordered)
    base_record = _first_valid_numeric_record(ordered)
    if base_record is None:
        return NormalizationResult(
            status="no_valid_base_value",
            reason="No valid numeric base observation was available for normalization.",
            base_date=None,
            base_value=None,
            rows=tuple(_with_normalized_value(row, None) for row in rows),
        )

    base_value = base_record.numeric_value
    if base_value is None or base_value == 0:
        return NormalizationResult(
            status="zero_base_value",
            reason="The first valid numeric observation was zero, so normalization could not be calculated.",
            base_date=base_record.observation_date,
            base_value=base_value,
            rows=tuple(_with_normalized_value(row, None) for row in rows),
        )

    return NormalizationResult(
        status="ok",
        reason=None,
        base_date=base_record.observation_date,
        base_value=base_value,
        rows=tuple(
            _with_normalized_value(
                row,
                (record.numeric_value / base_value) * _HUNDRED
                if not record.is_missing and record.numeric_value is not None
                else None,
            )
            for row, record in zip(rows, ordered, strict=True)
        ),
    )


def process_multiple_series(
    db_path: Path | str = DEFAULT_DATABASE_PATH,
    *,
    series_ids: Sequence[str],
    observation_start: date | str | None = None,
    observation_end: date | str | None = None,
) -> MultiSeriesResult:
    """Read cached series data, calculate analytics, and build comparison rows."""

    requested_series_ids = tuple(series_ids)
    if not requested_series_ids:
        raise ValueError("series_ids cannot be empty.")
    unsupported = [series_id for series_id in requested_series_ids if not is_supported_series(series_id)]
    if unsupported:
        supported = ", ".join(supported_series_ids())
        raise DatabaseError(
            f"Unsupported series ID '{unsupported[0]}'; supported series: {supported}."
        )

    observations_by_series = read_multiple_observations(
        db_path,
        series_ids=requested_series_ids,
        observation_start=observation_start,
        observation_end=observation_end,
    )
    metadata_by_series = read_supported_series_metadata(db_path, series_ids=requested_series_ids)

    series_results: list[SeriesResult] = []
    for series_id in requested_series_ids:
        metadata = metadata_by_series[series_id]
        observations = tuple(
            sorted(observations_by_series.get(series_id, ()), key=lambda item: item.observation_date)
        )
        series_results.append(
            SeriesResult(
                metadata=metadata,
                summary=calculate_series_summary(observations, metadata),
                observations=tuple(_build_observation_row(record, metadata) for record in observations),
                normalized=normalize_series_observations(observations, metadata),
            )
        )

    observation_rows = _flatten_rows(result.observations for result in series_results)
    normalized_rows = _flatten_rows(result.normalized.rows for result in series_results)

    if not observation_rows:
        status = "empty"
        reason = "No cached observations were available for the requested series and date range."
    elif any(result.summary.status == "empty" for result in series_results):
        status = "partial"
        reason = "At least one requested series had no cached observations in the selected date range."
    else:
        status = "ok"
        reason = None

    return MultiSeriesResult(
        requested_series_ids=requested_series_ids,
        requested_start_date=_coerce_date(observation_start),
        requested_end_date=_coerce_date(observation_end),
        status=status,
        reason=reason,
        series_results=tuple(series_results),
        observation_rows=observation_rows,
        normalized_rows=normalized_rows,
    )


def _calculate_exact_date_change(
    observations: Sequence[ObservationRecord],
    *,
    latest_valid_record: ObservationRecord | None,
    months_back: int,
    label: str,
) -> PercentageChangeResult:
    if latest_valid_record is None:
        return PercentageChangeResult(
            status="no_valid_numeric_observations",
            reason=f"No valid numeric observation was available for the {label} comparison.",
            value=None,
            latest_date=None,
            latest_value=None,
            comparison_date=None,
            comparison_value=None,
        )

    latest_date = latest_valid_record.observation_date
    latest_value = latest_valid_record.numeric_value
    comparison_date = _shift_calendar_months(latest_date, -months_back)
    if comparison_date is None:
        return PercentageChangeResult(
            status="comparison_date_unavailable",
            reason=f"The exact {label} comparison date does not exist for {latest_date.isoformat()}.",
            value=None,
            latest_date=latest_date,
            latest_value=latest_value,
            comparison_date=None,
            comparison_value=None,
        )

    records_by_date = {record.observation_date: record for record in observations}
    comparison_record = records_by_date.get(comparison_date)
    if comparison_record is None:
        return PercentageChangeResult(
            status="missing_comparison_observation",
            reason=f"No observation was available on {comparison_date.isoformat()}.",
            value=None,
            latest_date=latest_date,
            latest_value=latest_value,
            comparison_date=comparison_date,
            comparison_value=None,
        )
    if comparison_record.is_missing or comparison_record.numeric_value is None:
        return PercentageChangeResult(
            status="missing_comparison_value",
            reason=f"The observation on {comparison_date.isoformat()} was the FRED '.' missing value.",
            value=None,
            latest_date=latest_date,
            latest_value=latest_value,
            comparison_date=comparison_date,
            comparison_value=None,
        )
    if comparison_record.numeric_value == 0:
        return PercentageChangeResult(
            status="zero_comparison_value",
            reason=f"The comparison observation on {comparison_date.isoformat()} was zero.",
            value=None,
            latest_date=latest_date,
            latest_value=latest_value,
            comparison_date=comparison_date,
            comparison_value=comparison_record.numeric_value,
        )

    comparison_value = comparison_record.numeric_value
    value = ((latest_value - comparison_value) / comparison_value) * _HUNDRED
    return PercentageChangeResult(
        status="ok",
        reason=None,
        value=value,
        latest_date=latest_date,
        latest_value=latest_value,
        comparison_date=comparison_date,
        comparison_value=comparison_value,
    )


def _latest_valid_numeric_record(observations: Sequence[ObservationRecord]) -> ObservationRecord | None:
    for record in reversed(observations):
        if record.numeric_value is not None and not record.is_missing:
            return record
    return None


def _first_valid_numeric_record(observations: Sequence[ObservationRecord]) -> ObservationRecord | None:
    for record in observations:
        if record.numeric_value is not None and not record.is_missing:
            return record
    return None


def _build_observation_row(
    record: ObservationRecord,
    metadata: StoredSeriesMetadata,
) -> SeriesObservationRow:
    return SeriesObservationRow(
        series_id=record.series_id,
        series_name=metadata.display_name,
        units=metadata.units,
        date=record.observation_date,
        raw_value=record.value,
        is_missing=record.is_missing,
        normalized_value=None,
    )


def _with_normalized_value(
    row: SeriesObservationRow,
    normalized_value: Decimal | None,
) -> SeriesObservationRow:
    return SeriesObservationRow(
        series_id=row.series_id,
        series_name=row.series_name,
        units=row.units,
        date=row.date,
        raw_value=row.raw_value,
        is_missing=row.is_missing,
        normalized_value=normalized_value,
    )


def _mean(values: Sequence[Decimal]) -> Decimal:
    total = sum(values, start=Decimal("0"))
    return total / Decimal(len(values))


def _shift_calendar_months(value: date, months: int) -> date | None:
    total_months = value.year * 12 + (value.month - 1) + months
    if total_months < 0:
        return None
    year, month_index = divmod(total_months, 12)
    month = month_index + 1
    try:
        return date(year, month, value.day)
    except ValueError:
        return None


def _flatten_rows(rows: Sequence[Sequence[SeriesObservationRow]]) -> tuple[SeriesObservationRow, ...]:
    flattened = [row for sequence in rows for row in sequence]
    return tuple(sorted(flattened, key=lambda row: (row.series_id, row.date)))


def _coerce_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)
