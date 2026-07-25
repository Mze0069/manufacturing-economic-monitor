from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any

from manufacturing_monitor.analytics import SeriesObservationRow

if TYPE_CHECKING:
    from manufacturing_monitor.workflow import ApplicationResult, ProcessedObservation


CSV_FIELDNAMES = [
    "series_id",
    "series_name",
    "units",
    "date",
    "raw_value",
    "is_missing",
    "normalized_value",
]


class OutputWriteError(RuntimeError):
    """Raised when an output file cannot be written."""


def write_raw_json(payload: dict[str, Any], path: Path) -> None:
    _write_json(payload, path, error_prefix="raw output")


def write_processed_json(
    observations: tuple["ProcessedObservation", ...],
    path: Path,
) -> None:
    rows = [{"date": item.date, "value": item.value} for item in observations]
    _write_json(rows, path, error_prefix="processed output")


def build_processed_csv_text(rows: Sequence[SeriesObservationRow]) -> str:
    """Build the combined CSV representation used by the CLI and dashboard."""

    ordered_rows = sorted(rows, key=lambda row: (row.series_id, row.date))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDNAMES)
    writer.writeheader()
    for row in ordered_rows:
        writer.writerow(
            {
                "series_id": row.series_id,
                "series_name": row.series_name,
                "units": row.units,
                "date": row.date.isoformat(),
                "raw_value": row.raw_value,
                "is_missing": str(row.is_missing).lower(),
                "normalized_value": (
                    format(row.normalized_value, "f") if row.normalized_value is not None else ""
                ),
            }
        )
    return buffer.getvalue()


def write_processed_csv(
    rows: Sequence[SeriesObservationRow],
    path: Path,
) -> None:
    """Write combined processed rows to CSV with deterministic ordering."""

    text = build_processed_csv_text(rows)
    _write_text_atomic(text, path, error_prefix="CSV output")


def build_combined_processed_payload(result: "ApplicationResult") -> dict[str, Any]:
    """Build the combined processed JSON payload for a workflow result."""

    series_payloads: list[dict[str, Any]] = []
    for series_result in result.series_results:
        summary = series_result.result.summary
        series_payloads.append(
            {
                "series_id": series_result.series_id,
                "display_name": series_result.result.metadata.display_name,
                "units": series_result.result.metadata.units,
                "frequency": series_result.result.metadata.frequency,
                "source": series_result.source_kind,
                "raw_path": str(series_result.raw_path) if series_result.raw_path else None,
                "latest": (
                    {
                        "date": summary.latest_valid_date.isoformat()
                        if summary.latest_valid_date is not None
                        else None,
                        "value": format(summary.latest_valid_value, "f")
                        if summary.latest_valid_value is not None
                        else None,
                    }
                    if summary.latest_valid_date is not None or summary.latest_valid_value is not None
                    else None
                ),
                "summary": _summary_payload(summary),
                "observations": [
                    {"date": row.date.isoformat(), "value": row.raw_value}
                    for row in series_result.result.observations
                ],
                "normalized_rows": [
                    {
                        "date": row.date.isoformat(),
                        "normalized_value": (
                            format(row.normalized_value, "f")
                            if row.normalized_value is not None
                            else "."
                        ),
                    }
                    for row in series_result.result.normalized.rows
                ],
            }
        )

    return {
        "generated_at_utc": result.generated_at_utc.isoformat(),
        "requested_series_ids": list(result.requested_series_ids),
        "requested_start_date": (
            result.requested_start_date.isoformat()
            if result.requested_start_date is not None
            else None
        ),
        "requested_end_date": (
            result.requested_end_date.isoformat()
            if result.requested_end_date is not None
            else None
        ),
        "source_status": result.source_status,
        "source_reason": result.source_reason,
        "database_path": str(result.database_path),
        "processed_path": str(result.processed_path),
        "csv_path": str(result.csv_path) if result.csv_path is not None else None,
        "series": series_payloads,
        "combined_rows": [
            {
                "series_id": row.series_id,
                "series_name": row.series_name,
                "units": row.units,
                "date": row.date.isoformat(),
                "raw_value": row.raw_value,
                "is_missing": row.is_missing,
            }
            for row in result.analysis.observation_rows
        ],
        "normalized_rows": [
            {
                "series_id": row.series_id,
                "series_name": row.series_name,
                "units": row.units,
                "date": row.date.isoformat(),
                "raw_value": row.raw_value,
                "is_missing": row.is_missing,
                "normalized_value": (
                    format(row.normalized_value, "f") if row.normalized_value is not None else None
                ),
            }
            for row in result.analysis.normalized_rows
        ],
    }


def write_combined_processed_json(result: "ApplicationResult", path: Path) -> None:
    _write_json(build_combined_processed_payload(result), path, error_prefix="processed output")


def _summary_payload(summary: Any) -> dict[str, Any]:
    def _change_payload(change: Any) -> dict[str, Any]:
        return {
            "status": change.status,
            "reason": change.reason,
            "value": format(change.value, "f") if change.value is not None else None,
            "latest_date": change.latest_date.isoformat() if change.latest_date else None,
            "latest_value": format(change.latest_value, "f") if change.latest_value is not None else None,
            "comparison_date": (
                change.comparison_date.isoformat() if change.comparison_date else None
            ),
            "comparison_value": (
                format(change.comparison_value, "f")
                if change.comparison_value is not None
                else None
            ),
        }

    return {
        "series_id": summary.series_id,
        "series_name": summary.series_name,
        "units": summary.units,
        "frequency": summary.frequency,
        "latest_valid_value": (
            format(summary.latest_valid_value, "f")
            if summary.latest_valid_value is not None
            else None
        ),
        "latest_valid_date": (
            summary.latest_valid_date.isoformat() if summary.latest_valid_date else None
        ),
        "previous_month_change": _change_payload(summary.previous_month_change),
        "year_over_year_change": _change_payload(summary.year_over_year_change),
        "minimum_value": format(summary.minimum_value, "f") if summary.minimum_value is not None else None,
        "maximum_value": format(summary.maximum_value, "f") if summary.maximum_value is not None else None,
        "arithmetic_mean": (
            format(summary.arithmetic_mean, "f")
            if summary.arithmetic_mean is not None
            else None
        ),
        "total_observations": summary.total_observations,
        "valid_numeric_observations": summary.valid_numeric_observations,
        "missing_observations": summary.missing_observations,
        "first_observation_date": (
            summary.first_observation_date.isoformat()
            if summary.first_observation_date is not None
            else None
        ),
        "last_observation_date": (
            summary.last_observation_date.isoformat()
            if summary.last_observation_date is not None
            else None
        ),
        "status": summary.status,
        "reason": summary.reason,
    }


def _write_json(payload: Any, path: Path, *, error_prefix: str) -> None:
    try:
        _write_text_atomic(json.dumps(payload, indent=2) + "\n", path, error_prefix=error_prefix)
    except OSError as exc:
        raise OutputWriteError(f"Could not write {error_prefix} to {path}.") from exc


def _write_text_atomic(text: str, path: Path, *, error_prefix: str) -> None:
    temp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            delete=False,
            dir=str(path.parent),
            prefix=f"{path.name}.",
            suffix=".tmp",
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(text)
        os.replace(temp_path, path)
    except OSError as exc:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise OutputWriteError(f"Could not write {error_prefix} to {path}.") from exc
