from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from manufacturing_monitor.analytics import SeriesObservationRow
from manufacturing_monitor.output import OutputWriteError, write_processed_csv


def _row(series_id: str, day: str, raw_value: str, normalized_value: Decimal | None) -> SeriesObservationRow:
    return SeriesObservationRow(
        series_id=series_id,
        series_name=f"{series_id} Series",
        units="Index 2017=100, Seasonally Adjusted",
        date=date.fromisoformat(day),
        raw_value=raw_value,
        is_missing=raw_value == ".",
        normalized_value=normalized_value,
    )


def test_csv_deterministic_ordering_and_contents(tmp_path):
    output_path = tmp_path / "exports" / "combined.csv"
    rows = [
        _row("IPMAN", "2026-05-01", "120", Decimal("240")),
        _row("IPDMAN", "2026-04-01", "80", Decimal("100")),
        _row("IPMAN", "2026-04-01", "100", Decimal("200")),
        _row("IPDMAN", "2026-05-01", "90", Decimal("112.5")),
    ]

    write_processed_csv(rows, output_path)

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "series_id,series_name,units,date,raw_value,is_missing,normalized_value"
    assert lines[1].startswith("IPDMAN,")
    assert lines[2].startswith("IPDMAN,")
    assert lines[3].startswith("IPMAN,")
    assert lines[4].startswith("IPMAN,")


def test_csv_write_failure_cleans_up_temp_file(tmp_path, monkeypatch):
    output_path = tmp_path / "exports" / "combined.csv"
    rows = [_row("IPMAN", "2026-05-01", "120", Decimal("100"))]

    def fail_replace(*_args, **_kwargs):
        raise OSError("boom")

    monkeypatch.setattr("manufacturing_monitor.output.os.replace", fail_replace)

    with pytest.raises(OutputWriteError, match="Could not write CSV output"):
        write_processed_csv(rows, output_path)

    assert not list(output_path.parent.glob("*.tmp"))


def test_csv_utf8_and_no_secret_material(tmp_path):
    output_path = tmp_path / "exports" / "combined.csv"
    secret = "FAKE_SECRET_DO_NOT_EXPORT"
    rows = [
        SeriesObservationRow(
            series_id="IPMAN",
            series_name="Industrial Production: Manufacturing (NAICS)",
            units="Index 2017=100, Seasonally Adjusted",
            date=date(2026, 5, 1),
            raw_value="120",
            is_missing=False,
            normalized_value=Decimal("100"),
        ),
        SeriesObservationRow(
            series_id="IPDMAN",
            series_name="Durable Manufacturing",
            units="Index 2017=100, Seasonally Adjusted",
            date=date(2026, 5, 1),
            raw_value="90",
            is_missing=False,
            normalized_value=Decimal("100"),
        ),
    ]

    write_processed_csv(rows, output_path)

    contents = output_path.read_text(encoding="utf-8")
    assert secret not in contents
    assert "UTF-8" not in contents
    assert "Industrial Production: Manufacturing (NAICS)" in contents
