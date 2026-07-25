from __future__ import annotations

import json
from pathlib import Path

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
