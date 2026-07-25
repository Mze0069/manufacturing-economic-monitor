from __future__ import annotations

from datetime import date
from dataclasses import dataclass
from decimal import Decimal
import logging
from pathlib import Path
from typing import Any

from manufacturing_monitor.api import fetch_observations
from manufacturing_monitor.db import (
    DEFAULT_DATABASE_PATH,
    FETCH_SOURCE_LIVE,
    ValidatedObservation,
    store_validated_monitor_data,
)
from manufacturing_monitor.models import FredObservation, validate_fred_response


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MonitorRequest:
    api_key: str
    series_id: str = "IPMAN"
    observation_start: date | str | None = None
    observation_end: date | str | None = None


@dataclass(frozen=True)
class ProcessedObservation:
    date: str
    value: str


@dataclass(frozen=True)
class MonitorResult:
    raw_payload: dict[str, Any]
    observations: tuple[ProcessedObservation, ...]
    latest: ProcessedObservation


def fetch_monitor_data(request: MonitorRequest) -> dict[str, Any]:
    return fetch_observations(
        request.api_key,
        series_id=request.series_id,
        observation_start=request.observation_start,
        observation_end=request.observation_end,
    )


def build_monitor_result(payload: dict[str, Any]) -> MonitorResult:
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


def latest_valid_observation(
    observations: tuple[ProcessedObservation, ...],
) -> ProcessedObservation:
    for observation in reversed(observations):
        if observation.value == ".":
            continue
        Decimal(observation.value)
        return observation
    raise ValueError("No valid numeric manufacturing observations were available.")


def format_summary(result: MonitorResult) -> str:
    return (
        "Manufacturing Economic Monitor\n"
        f"Latest manufacturing index: {result.latest.value} on {result.latest.date}\n"
        f"Validated observations: {len(result.observations)}"
    )


def _processed_observation(observation: FredObservation) -> ProcessedObservation:
    return ProcessedObservation(
        date=observation.date.isoformat(),
        value=observation.value,
    )
