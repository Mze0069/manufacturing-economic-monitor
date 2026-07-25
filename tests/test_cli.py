from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from manufacturing_monitor import cli
from manufacturing_monitor.analytics import (
    MultiSeriesResult,
    NormalizationResult,
    PercentageChangeResult,
    SeriesObservationRow,
    SeriesResult,
    SeriesSummary,
)
from manufacturing_monitor.db import FetchRunRecord, StoredSeriesMetadata
from manufacturing_monitor.workflow import (
    ApplicationResult,
    ApplicationSeriesResult,
    WorkflowError,
)


def _fake_series_result(
    *,
    series_id: str,
    display_name: str,
    source_kind: str,
    latest_value: str,
    latest_date: date,
    raw_values: tuple[tuple[date, str], ...],
    normalized_values: tuple[tuple[date, str | None], ...],
    fetch_timestamp: datetime,
) -> ApplicationSeriesResult:
    metadata = StoredSeriesMetadata(
        series_id=series_id,
        display_name=display_name,
        units="Index 2017=100, Seasonally Adjusted",
        frequency="Monthly",
        updated_at_utc=fetch_timestamp.isoformat(),
    )
    summary = SeriesSummary(
        series_id=series_id,
        series_name=display_name,
        units=metadata.units,
        frequency=metadata.frequency,
        latest_valid_value=Decimal(latest_value),
        latest_valid_date=latest_date,
        previous_month_change=PercentageChangeResult(
            status="ok",
            reason=None,
            value=Decimal("2.5"),
            latest_date=latest_date,
            latest_value=Decimal(latest_value),
            comparison_date=latest_date,
            comparison_value=Decimal(latest_value) - Decimal("2.5"),
        ),
        year_over_year_change=PercentageChangeResult(
            status="ok",
            reason=None,
            value=Decimal("4.0"),
            latest_date=latest_date,
            latest_value=Decimal(latest_value),
            comparison_date=latest_date,
            comparison_value=Decimal(latest_value) - Decimal("4.0"),
        ),
        minimum_value=min(Decimal(value) for _, value in raw_values if value != "."),
        maximum_value=max(Decimal(value) for _, value in raw_values if value != "."),
        arithmetic_mean=Decimal("100.5"),
        total_observations=len(raw_values),
        valid_numeric_observations=sum(1 for _, value in raw_values if value != "."),
        missing_observations=sum(1 for _, value in raw_values if value == "."),
        first_observation_date=raw_values[0][0],
        last_observation_date=raw_values[-1][0],
        status="ok",
        reason=None,
    )
    observations = tuple(
        SeriesObservationRow(
            series_id=series_id,
            series_name=display_name,
            units=metadata.units,
            date=observation_date,
            raw_value=value,
            is_missing=value == ".",
            normalized_value=None,
        )
        for observation_date, value in raw_values
    )
    normalized_rows = tuple(
        SeriesObservationRow(
            series_id=series_id,
            series_name=display_name,
            units=metadata.units,
            date=observation_date,
            raw_value=raw_value,
            is_missing=raw_value == ".",
            normalized_value=Decimal(normalized_value) if normalized_value is not None else None,
        )
        for (observation_date, raw_value), (_, normalized_value) in zip(
            raw_values,
            normalized_values,
            strict=True,
        )
    )
    result = SeriesResult(
        metadata=metadata,
        summary=summary,
        observations=observations,
        normalized=NormalizationResult(
            status="ok",
            reason=None,
            base_date=raw_values[0][0],
            base_value=Decimal("100"),
            rows=normalized_rows,
        ),
    )
    fetch_run = FetchRunRecord(
        series_id=series_id,
        requested_start_date=raw_values[0][0],
        requested_end_date=raw_values[-1][0],
        fetched_at_utc=fetch_timestamp,
        validated_observation_count=len(raw_values),
        source_kind=source_kind,
    )
    return ApplicationSeriesResult(
        series_id=series_id,
        source_kind=source_kind,
        raw_path=Path(f"data/raw/{series_id.lower()}_observations_raw.json"),
        fetch_run=fetch_run,
        result=result,
    )


def _fake_application_result(tmp_path: Path) -> ApplicationResult:
    fetched_at = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    ipman = _fake_series_result(
        series_id="IPMAN",
        display_name="Industrial Production: Manufacturing (NAICS)",
        source_kind="cache",
        latest_value="101.0",
        latest_date=date(2026, 5, 1),
        raw_values=((date(2026, 4, 1), "99.0"), (date(2026, 5, 1), "101.0")),
        normalized_values=((date(2026, 4, 1), "100"), (date(2026, 5, 1), "102")),
        fetch_timestamp=fetched_at,
    )
    ipdman = _fake_series_result(
        series_id="IPDMAN",
        display_name="Industrial Production: Durable Manufacturing (NAICS)",
        source_kind="live",
        latest_value="88.0",
        latest_date=date(2026, 5, 1),
        raw_values=((date(2026, 4, 1), "86.0"), (date(2026, 5, 1), "88.0")),
        normalized_values=((date(2026, 4, 1), "100"), (date(2026, 5, 1), "102.3255813953")),
        fetch_timestamp=fetched_at,
    )
    analysis = MultiSeriesResult(
        requested_series_ids=("IPMAN", "IPDMAN"),
        requested_start_date=date(2026, 4, 1),
        requested_end_date=date(2026, 5, 1),
        status="ok",
        reason=None,
        series_results=(ipman.result, ipdman.result),
        observation_rows=(ipman.result.observations + ipdman.result.observations),
        normalized_rows=(ipman.result.normalized.rows + ipdman.result.normalized.rows),
    )
    return ApplicationResult(
        requested_series_ids=("IPMAN", "IPDMAN"),
        requested_start_date=date(2026, 4, 1),
        requested_end_date=date(2026, 5, 1),
        source_status="mixed",
        source_reason=None,
        generated_at_utc=fetched_at,
        database_path=tmp_path / "monitor.db",
        raw_paths={
            "IPMAN": tmp_path / "data/raw/ipman_observations_raw.json",
            "IPDMAN": tmp_path / "data/raw/ipdman_observations_raw.json",
        },
        legacy_processed_path=None,
        processed_path=tmp_path / "data/processed/ipman_ipdman_combined_processed.json",
        csv_path=tmp_path / "exports" / "combined.csv",
        analysis=analysis,
        series_results=(ipman, ipdman),
    )


def test_project_info_does_not_contact_fred(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_application_workflow", lambda *_args, **_kwargs: None)

    cli.main(["--project-info"])

    assert "Network: not contacted" in capsys.readouterr().out


def test_cli_defaults_to_ipman(monkeypatch, capsys, tmp_path):
    captured: dict[str, object] = {}
    result = _fake_application_result(tmp_path)

    def fake_run(request):
        captured["request"] = request
        return result

    monkeypatch.setenv("FRED_API_KEY", "test-key")
    monkeypatch.setattr(cli, "run_application_workflow", fake_run)

    cli.main([])

    request = captured["request"]
    assert request.series_ids == ("IPMAN",)
    assert request.refresh is False
    assert "Industrial Production: Manufacturing (NAICS) (IPMAN)" in capsys.readouterr().out


def test_cli_repeated_series_and_date_options(monkeypatch, capsys, tmp_path):
    captured: dict[str, object] = {}
    result = _fake_application_result(tmp_path)

    def fake_run(request):
        captured["request"] = request
        return result

    monkeypatch.setenv("FRED_API_KEY", "test-key")
    monkeypatch.setattr(cli, "run_application_workflow", fake_run)

    cli.main(
        [
            "--series",
            "IPMAN",
            "--series",
            "IPDMAN",
            "--start-date",
            "2026-04-01",
            "--end-date",
            "2026-05-01",
            "--refresh",
            "--database",
            str(tmp_path / "monitor.db"),
            "--csv-output",
            str(tmp_path / "combined.csv"),
        ]
    )

    request = captured["request"]
    assert request.series_ids == ("IPMAN", "IPDMAN")
    assert request.observation_start == date(2026, 4, 1)
    assert request.observation_end == date(2026, 5, 1)
    assert request.refresh is True
    assert request.db_path == tmp_path / "monitor.db"
    assert request.csv_output == tmp_path / "combined.csv"
    output = capsys.readouterr().out
    assert "Data source: mixed" in output
    assert "CSV:" in output


def test_cli_summary_contents_and_secret_hygiene(monkeypatch, capsys, tmp_path):
    secret = "FAKE_SECRET_DO_NOT_PRINT"
    result = _fake_application_result(tmp_path)

    def fake_run(request):
        assert request.api_key == secret
        return result

    log_file = tmp_path / "logs" / "cli.log"
    monkeypatch.setenv("FRED_API_KEY", secret)
    monkeypatch.setattr(cli, "run_application_workflow", fake_run)

    cli.main(["--log-file", str(log_file)])

    output = capsys.readouterr().out
    assert secret not in output
    assert "Industrial Production: Manufacturing (NAICS) (IPMAN)" in output
    assert "Latest value: 101.0 on 2026-05-01" in output
    assert "Month-over-month: 2.50%" in output
    assert "Year-over-year: 4.00%" in output
    assert "Valid observations: 2" in output
    assert "Missing observations: 0" in output
    assert secret not in log_file.read_text(encoding="utf-8")


def test_cli_nonzero_failure_behavior(monkeypatch):
    monkeypatch.setattr(
        cli,
        "run_application_workflow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(WorkflowError("boom")),
    )

    with pytest.raises(SystemExit, match="boom"):
        cli.main([])
