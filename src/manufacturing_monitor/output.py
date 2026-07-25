from __future__ import annotations

import csv
import json
import os
from collections.abc import Sequence
from tempfile import NamedTemporaryFile
from pathlib import Path

from manufacturing_monitor.analytics import SeriesObservationRow
from manufacturing_monitor.workflow import ProcessedObservation


class OutputWriteError(RuntimeError):
    """Raised when an output file cannot be written."""


def write_raw_json(payload: dict, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise OutputWriteError(f"Could not write raw output to {path}.") from exc


def write_processed_json(
    observations: tuple[ProcessedObservation, ...],
    path: Path,
) -> None:
    rows = [{"date": item.date, "value": item.value} for item in observations]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise OutputWriteError(f"Could not write processed output to {path}.") from exc


def write_processed_csv(
    rows: Sequence[SeriesObservationRow],
    path: Path,
) -> None:
    """Write combined processed rows to CSV with deterministic ordering."""

    ordered_rows = sorted(rows, key=lambda row: (row.series_id, row.date))
    fieldnames = [
        "series_id",
        "series_name",
        "units",
        "date",
        "raw_value",
        "is_missing",
        "normalized_value",
    ]
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
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
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
                            format(row.normalized_value, "f")
                            if row.normalized_value is not None
                            else ""
                        ),
                    }
                )
        os.replace(temp_path, path)
    except OSError as exc:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise OutputWriteError(f"Could not write CSV output to {path}.") from exc
