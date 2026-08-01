"""Validate FRED requests, responses, dates, and observation values."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from manufacturing_monitor.series_catalog import supported_series_ids


class FredDataValidationError(ValueError):
    """Raised when FRED response data cannot be safely used."""


class FredRequestValidationError(ValueError):
    """Raised when a FRED request cannot be constructed safely."""


class FredSeriesRequest(BaseModel):
    """Validated parameters for one supported FRED series request."""
    model_config = ConfigDict(extra="ignore", validate_default=True)

    series_id: str = "IPMAN"
    observation_start: date | None = None
    observation_end: date | None = None

    @field_validator("series_id")
    @classmethod
    def series_id_must_be_supported(cls, value: str) -> str:
        """Reject series identifiers outside the supported catalog."""
        if value not in supported_series_ids():
            supported = ", ".join(supported_series_ids())
            raise ValueError(
                f"unsupported FRED series ID '{value}'; supported series: {supported}"
            )
        return value

    @field_validator("observation_start", "observation_end", mode="before")
    @classmethod
    def observation_dates_must_be_iso_dates(cls, value: Any) -> Any:
        """Validate optional observation dates as ISO dates."""
        if value is None:
            return None
        if isinstance(value, date):
            return value
        if not isinstance(value, str):
            raise ValueError("must be an ISO date in YYYY-MM-DD format")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("must be an ISO date in YYYY-MM-DD format") from exc

    @model_validator(mode="after")
    def start_date_must_not_follow_end_date(self) -> "FredSeriesRequest":
        """Reject request ranges whose start date follows the end date."""
        if (
            self.observation_start is not None
            and self.observation_end is not None
            and self.observation_start > self.observation_end
        ):
            raise ValueError("observation_start cannot be after observation_end")
        return self


class FredObservation(BaseModel):
    """Validated monthly observation returned by FRED."""
    model_config = ConfigDict(extra="ignore")

    date: date
    value: str = Field(strict=True)

    @field_validator("value")
    @classmethod
    def value_must_be_number_or_placeholder(cls, value: str) -> str:
        """Accept finite numeric values or the documented FRED missing placeholder."""
        if value == ".":
            return value
        try:
            numeric_value = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("must be a finite numeric string or the FRED '.' placeholder") from exc
        if not numeric_value.is_finite():
            raise ValueError("must be a finite numeric string or the FRED '.' placeholder")
        return value


class FredResponse(BaseModel):
    """Validated FRED response containing observation records."""
    model_config = ConfigDict(extra="ignore")

    observations: list[FredObservation] = Field(min_length=1)


def validate_fred_request(
    *,
    series_id: str = "IPMAN",
    observation_start: date | str | None = None,
    observation_end: date | str | None = None,
) -> FredSeriesRequest:
    """Validate request parameters and return a typed request model."""
    try:
        return FredSeriesRequest.model_validate(
            {
                "series_id": series_id,
                "observation_start": observation_start,
                "observation_end": observation_end,
            }
        )
    except ValidationError as exc:
        first_problem = exc.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first_problem["loc"])
        message = first_problem["msg"]
        prefix = "FRED request could not be used"
        if location:
            raise FredRequestValidationError(
                f"{prefix} at {location}: {message}"
            ) from exc
        raise FredRequestValidationError(f"{prefix}: {message}") from exc


def validate_fred_response(payload: dict[str, Any]) -> FredResponse:
    """Validate a FRED payload and return a typed response model."""
    try:
        return FredResponse.model_validate(payload)
    except ValidationError as exc:
        first_problem = exc.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first_problem["loc"])
        message = first_problem["msg"]
        raise FredDataValidationError(
            f"FRED data could not be used at {location}: {message}"
        ) from exc
