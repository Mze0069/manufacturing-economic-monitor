from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class FredDataValidationError(ValueError):
    """Raised when FRED response data cannot be safely used."""


class FredObservation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: date
    value: str

    @field_validator("value")
    @classmethod
    def value_must_be_number_or_placeholder(cls, value: str) -> str:
        if value == ".":
            return value
        try:
            Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("must be numeric or the FRED '.' placeholder") from exc
        return value


class FredResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    observations: list[FredObservation] = Field(min_length=1)


def validate_fred_response(payload: dict[str, Any]) -> FredResponse:
    try:
        return FredResponse.model_validate(payload)
    except ValidationError as exc:
        first_problem = exc.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first_problem["loc"])
        message = first_problem["msg"]
        raise FredDataValidationError(
            f"FRED data could not be used at {location}: {message}"
        ) from exc
