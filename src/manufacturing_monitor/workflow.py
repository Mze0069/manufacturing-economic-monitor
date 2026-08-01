"""Coordinate API retrieval, validation, caching, analytics, and output."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import logging
from pathlib import Path
from typing import Any

from manufacturing_monitor.analytics import (
    MultiSeriesResult,
    SeriesResult,
    process_multiple_series,
)
from manufacturing_monitor.api import fetch_observations
from manufacturing_monitor.db import (
    DEFAULT_DATABASE_PATH,
    FETCH_SOURCE_CACHE,
    FETCH_SOURCE_LIVE,
    DatabaseError,
    FetchRunRecord,
    ObservationRecord,
    ValidatedObservation,
    get_latest_fetch_information,
    initialize_schema,
    read_observations,
    store_validated_monitor_data,
)
from manufacturing_monitor.models import FredObservation, validate_fred_response
from manufacturing_monitor.output import (
    write_combined_processed_json,
    write_processed_csv,
    write_processed_json,
    write_raw_json,
)
from manufacturing_monitor.series_catalog import is_supported_series, supported_series_ids


logger = logging.getLogger(__name__)


class WorkflowError(RuntimeError):
    """Raised when the shared application workflow cannot complete safely."""


@dataclass(frozen=True, slots=True)
class MonitorRequest:
    """Request parameters for retrieving one manufacturing series."""
    api_key: str
    series_id: str = "IPMAN"
    observation_start: date | str | None = None
    observation_end: date | str | None = None


@dataclass(frozen=True, slots=True)
class ProcessedObservation:
    """Validated date and value pair used by the legacy workflow."""
    date: str
    value: str


@dataclass(frozen=True, slots=True)
class MonitorResult:
    """Validated observations and latest valid value for one series."""
    raw_payload: dict[str, Any]
    observations: tuple[ProcessedObservation, ...]
    latest: ProcessedObservation


@dataclass(frozen=True, slots=True)
class ApplicationRequest:
    """Complete multi-series application request."""
    series_ids: tuple[str, ...] = ("IPMAN",)
    api_key: str | None = None
    observation_start: date | str | None = None
    observation_end: date | str | None = None
    db_path: Path | str = DEFAULT_DATABASE_PATH
    refresh: bool = False
    cache_only: bool = False
    csv_output: Path | str | None = None


@dataclass(frozen=True, slots=True)
class ApplicationSeriesResult:
    """Per-series result including data source and refresh metadata."""
    series_id: str
    source_kind: str
    raw_path: Path | None
    fetch_run: FetchRunRecord | None
    result: SeriesResult


@dataclass(frozen=True, slots=True)
class ApplicationResult:
    """Combined application output for CLI and dashboard consumers."""
    requested_series_ids: tuple[str, ...]
    requested_start_date: date | None
    requested_end_date: date | None
    source_status: str
    source_reason: str | None
    generated_at_utc: datetime
    database_path: Path
    raw_paths: dict[str, Path]
    legacy_processed_path: Path | None
    processed_path: Path
    csv_path: Path | None
    analysis: MultiSeriesResult
    series_results: tuple[ApplicationSeriesResult, ...]


def fetch_monitor_data(request: MonitorRequest) -> dict[str, Any]:
    """Retrieve one FRED payload through the API boundary."""
    return fetch_observations(
        request.api_key,
        series_id=request.series_id,
        observation_start=request.observation_start,
        observation_end=request.observation_end,
    )


def build_monitor_result(payload: dict[str, Any]) -> MonitorResult:
    """Validate a payload and create a single-series result."""
    logger.info("Validating FRED response data.")
    validated = validate_fred_response(payload)
    observations = tuple(_processed_observation(item) for item in validated.observations)
    latest = latest_valid_observation(observations)
    logger.debug("Validated %d FRED observations.", len(observations))
    return MonitorResult(
        raw_payload=payload,
        observations=observations,
        latest=latest,
    )


def run_monitor(
    request: MonitorRequest,
    *,
    db_path: Path | str = DEFAULT_DATABASE_PATH,
    source_kind: str = FETCH_SOURCE_LIVE,
) -> MonitorResult:
    """Fetch, validate, and persist one series run."""

    result = build_monitor_result(fetch_monitor_data(request))
    store_validated_monitor_result(
        request=request,
        result=result,
        db_path=db_path,
        source_kind=source_kind,
    )
    return result


def store_validated_monitor_result(
    request: MonitorRequest,
    result: MonitorResult,
    *,
    db_path: Path | str = DEFAULT_DATABASE_PATH,
    source_kind: str = FETCH_SOURCE_LIVE,
) -> None:
    """Store already validated FRED data in SQLite."""

    observations = tuple(
        ValidatedObservation(date=item.date, value=item.value) for item in result.observations
    )
    store_validated_monitor_data(
        db_path,
        series_id=request.series_id,
        observations=observations,
        requested_start_date=request.observation_start,
        requested_end_date=request.observation_end,
        source_kind=source_kind,
    )


def run_application_workflow(request: ApplicationRequest) -> ApplicationResult:
    """Load cached observations, fetch missing data, and build the combined result."""

    series_ids = _unique_series_ids(request.series_ids)
    if not series_ids:
        raise WorkflowError("At least one supported series ID is required.")
    _validate_series_ids(series_ids)

    if request.refresh and not _api_key_is_present(request.api_key):
        raise WorkflowError("FRED_API_KEY is required when refresh mode is selected.")

    db_path = initialize_schema(request.db_path)
    cached_rows = _read_cached_rows(
        db_path,
        series_ids=series_ids,
        observation_start=request.observation_start,
        observation_end=request.observation_end,
    )
    cache_hits = {series_id: len(rows) > 0 for series_id, rows in cached_rows.items()}
    series_sources: dict[str, str] = {}
    raw_paths: dict[str, Path] = {}

    missing_series = [series_id for series_id in series_ids if not cache_hits[series_id]]
    if not request.cache_only and request.refresh:
        missing_series = list(series_ids)
    if not request.cache_only and missing_series and not _api_key_is_present(request.api_key):
        missing_text = ", ".join(missing_series)
        raise WorkflowError(
            "A FRED API key is required because cached data is missing for: "
            f"{missing_text}."
        )

    live_series_ids = list(series_ids) if request.refresh else list(missing_series)
    if request.cache_only:
        live_series_ids = []

    for series_id in live_series_ids:
        raw_path = _fetch_and_store_series(
            db_path,
            api_key=request.api_key or "",
            series_id=series_id,
            observation_start=request.observation_start,
            observation_end=request.observation_end,
        )
        raw_paths[series_id] = raw_path
        series_sources[series_id] = FETCH_SOURCE_LIVE

    for series_id in series_ids:
        if series_id not in series_sources:
            series_sources[series_id] = FETCH_SOURCE_CACHE

    analysis = process_multiple_series(
        db_path,
        series_ids=series_ids,
        observation_start=request.observation_start,
        observation_end=request.observation_end,
    )

    csv_path = Path(request.csv_output).expanduser() if request.csv_output is not None else None

    series_results = tuple(
        _build_application_series_result(
            series_result=series_result,
            source_kind=series_sources[series_result.metadata.series_id],
            raw_path=raw_paths.get(series_result.metadata.series_id),
            fetch_run=get_latest_fetch_information(
                db_path,
                series_id=series_result.metadata.series_id,
            ),
        )
        for series_result in analysis.series_results
    )

    source_status = _summarize_source_status(series_sources.values(), analysis)
    source_reason = analysis.reason
    generated_at_utc = datetime.now(timezone.utc)
    processed_path = _combined_processed_path(
        series_ids,
        request.observation_start,
        request.observation_end,
    )
    legacy_processed_path = _legacy_processed_path(
        series_ids,
        request.observation_start,
        request.observation_end,
    )
    if len(series_ids) == 1:
        legacy_rows = tuple(
            ProcessedObservation(date=row.date.isoformat(), value=row.raw_value)
            for row in analysis.series_results[0].observations
        )
        write_processed_json(legacy_rows, legacy_processed_path)
    else:
        legacy_processed_path = None

    if csv_path is not None:
        write_processed_csv(analysis.normalized_rows, csv_path)

    result = ApplicationResult(
        requested_series_ids=series_ids,
        requested_start_date=analysis.requested_start_date,
        requested_end_date=analysis.requested_end_date,
        source_status=source_status,
        source_reason=source_reason,
        generated_at_utc=generated_at_utc,
        database_path=db_path,
        raw_paths=raw_paths,
        legacy_processed_path=legacy_processed_path,
        processed_path=processed_path,
        csv_path=csv_path,
        analysis=analysis,
        series_results=series_results,
    )

    write_combined_processed_json(result, processed_path)

    return result


def run_monitor_application(
    request: MonitorRequest,
    *,
    db_path: Path | str = DEFAULT_DATABASE_PATH,
    refresh: bool = False,
) -> ApplicationResult:
    """Compatibility helper for single-series application runs."""

    return run_application_workflow(
        ApplicationRequest(
            series_ids=(request.series_id,),
            api_key=request.api_key,
            observation_start=request.observation_start,
            observation_end=request.observation_end,
            db_path=db_path,
            refresh=refresh,
        )
    )


def latest_valid_observation(
    observations: tuple[ProcessedObservation, ...],
) -> ProcessedObservation:
    """Return the latest numeric observation or raise when none exists."""
    for observation in reversed(observations):
        if observation.value == ".":
            continue
        Decimal(observation.value)
        return observation
    raise ValueError("No valid numeric manufacturing observations were available.")


def format_summary(result: MonitorResult) -> str:
    """Format an application result as readable command-line text."""
    return (
        "Manufacturing Economic Monitor\n"
        f"Latest manufacturing index: {result.latest.value} on {result.latest.date}\n"
        f"Validated observations: {len(result.observations)}"
    )


def _build_application_series_result(
    *,
    series_result: SeriesResult,
    source_kind: str,
    raw_path: Path | None,
    fetch_run: FetchRunRecord | None,
) -> ApplicationSeriesResult:
    return ApplicationSeriesResult(
        series_id=series_result.metadata.series_id,
        source_kind=source_kind,
        raw_path=raw_path,
        fetch_run=fetch_run,
        result=series_result,
    )


def _fetch_and_store_series(
    db_path: Path,
    *,
    api_key: str,
    series_id: str,
    observation_start: date | str | None,
    observation_end: date | str | None,
) -> Path:
    request = MonitorRequest(
        api_key=api_key,
        series_id=series_id,
        observation_start=observation_start,
        observation_end=observation_end,
    )
    legacy_result = build_monitor_result(fetch_monitor_data(request))
    raw_path = _raw_output_path(series_id, observation_start, observation_end)
    write_raw_json(legacy_result.raw_payload, raw_path)
    logger.info("Saved raw FRED response to %s.", raw_path)

    store_validated_monitor_data(
        db_path,
        series_id=series_id,
        observations=tuple(
            ValidatedObservation(date=item.date, value=item.value)
            for item in legacy_result.observations
        ),
        requested_start_date=observation_start,
        requested_end_date=observation_end,
        source_kind=FETCH_SOURCE_LIVE,
    )
    return raw_path


def _read_cached_rows(
    db_path: Path,
    *,
    series_ids: tuple[str, ...],
    observation_start: date | str | None,
    observation_end: date | str | None,
) -> dict[str, tuple[ObservationRecord, ...]]:
    cached: dict[str, tuple[ObservationRecord, ...]] = {}
    for series_id in series_ids:
        cached[series_id] = read_observations(
            db_path,
            series_id=series_id,
            observation_start=observation_start,
            observation_end=observation_end,
        )
    return cached


def _summarize_source_status(
    source_kinds: list[str] | tuple[str, ...],
    analysis: MultiSeriesResult,
) -> str:
    kinds = set(source_kinds)
    if FETCH_SOURCE_LIVE in kinds and FETCH_SOURCE_CACHE in kinds:
        return "mixed"
    if FETCH_SOURCE_LIVE in kinds:
        return "live"
    return "cache" if analysis.observation_rows or kinds else "empty"


def _validate_series_ids(series_ids: tuple[str, ...]) -> None:
    unsupported = [series_id for series_id in series_ids if not is_supported_series(series_id)]
    if unsupported:
        supported = ", ".join(supported_series_ids())
        raise WorkflowError(
            f"Unsupported series ID '{unsupported[0]}'; supported series: {supported}."
        )


def _unique_series_ids(series_ids: tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for series_id in series_ids:
        if series_id in seen:
            continue
        ordered.append(series_id)
        seen.add(series_id)
    return tuple(ordered)


def _api_key_is_present(api_key: str | None) -> bool:
    return bool(api_key and api_key.strip())


def _raw_output_path(
    series_id: str,
    observation_start: date | str | None,
    observation_end: date | str | None,
) -> Path:
    base = series_id.lower()
    if observation_start is None and observation_end is None:
        return Path("data/raw") / f"{base}_observations_raw.json"
    return Path("data/raw") / (
        f"{base}_{_date_token(observation_start)}_{_date_token(observation_end)}_observations_raw.json"
    )


def _legacy_processed_path(
    series_ids: tuple[str, ...],
    observation_start: date | str | None,
    observation_end: date | str | None,
) -> Path:
    if len(series_ids) == 1 and observation_start is None and observation_end is None:
        return Path("data/processed") / f"{series_ids[0].lower()}_observations_processed.json"
    slug = "_".join(series_id.lower() for series_id in series_ids)
    if observation_start is None and observation_end is None:
        return Path("data/processed") / f"{slug}_observations_processed.json"
    return Path("data/processed") / (
        f"{slug}_{_date_token(observation_start)}_{_date_token(observation_end)}_observations_processed.json"
    )


def _combined_processed_path(
    series_ids: tuple[str, ...],
    observation_start: date | str | None,
    observation_end: date | str | None,
) -> Path:
    slug = "-".join(series_id.lower() for series_id in series_ids)
    if observation_start is None and observation_end is None:
        return Path("data/processed") / f"{slug}_combined_processed.json"
    return Path("data/processed") / (
        f"{slug}_{_date_token(observation_start)}_{_date_token(observation_end)}_combined_processed.json"
    )


def _date_token(value: date | str | None) -> str:
    if value is None:
        return "all"
    if isinstance(value, date):
        return value.isoformat()
    return value


def _processed_observation(observation: FredObservation) -> ProcessedObservation:
    return ProcessedObservation(
        date=observation.date.isoformat(),
        value=observation.value,
    )
