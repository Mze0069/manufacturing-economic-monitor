"""Call the FRED API and convert request failures into application errors."""

from __future__ import annotations

from datetime import date
import logging
from typing import Any

import requests

from manufacturing_monitor.models import FredRequestValidationError, validate_fred_request

FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
DEFAULT_TIMEOUT = 30.0
logger = logging.getLogger(__name__)


class AppError(RuntimeError):
    """User-facing application error."""


def fetch_observations(
    api_key: str,
    *,
    series_id: str = "IPMAN",
    observation_start: date | str | None = None,
    observation_end: date | str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Fetch FRED observations for one supported series."""

    if not api_key.strip():
        raise AppError("FRED_API_KEY is required.")

    try:
        request = validate_fred_request(
            series_id=series_id,
            observation_start=observation_start,
            observation_end=observation_end,
        )
    except FredRequestValidationError as exc:
        raise AppError(str(exc)) from exc

    params: dict[str, str] = {
        "series_id": request.series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    if request.observation_start is not None:
        params["observation_start"] = request.observation_start.isoformat()
    if request.observation_end is not None:
        params["observation_end"] = request.observation_end.isoformat()

    try:
        logger.info("Requesting FRED observations.")
        logger.debug("Using FRED request timeout of %.1f seconds.", timeout)
        response = requests.get(FRED_API_URL, params=params, timeout=timeout)
        response.raise_for_status()
    except requests.Timeout as exc:
        logger.warning("FRED request timed out.")
        raise AppError("FRED request timed out. Try again later.") from exc
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        logger.warning("FRED request failed with HTTP status %s.", status)
        raise AppError(f"FRED request failed with HTTP status {status}.") from exc
    except requests.RequestException as exc:
        logger.warning("FRED request failed due to a connection problem.")
        raise AppError("Could not connect to FRED. Check your network and try again.") from exc

    try:
        data = response.json()
    except ValueError as exc:
        logger.warning("FRED response was not valid JSON.")
        raise AppError("FRED returned a response that was not valid JSON.") from exc

    if not isinstance(data, dict):
        logger.warning("FRED response had an unexpected top-level shape.")
        raise AppError("FRED response must be a JSON object.")

    logger.debug("FRED response parsed as a JSON object.")
    return data
