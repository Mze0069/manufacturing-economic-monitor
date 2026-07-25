from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from manufacturing_monitor import dashboard
from manufacturing_monitor.analytics import (
    MultiSeriesResult,
    NormalizationResult,
    PercentageChangeResult,
    SeriesObservationRow,
    SeriesResult,
    SeriesSummary,
)
from manufacturing_monitor.db import FetchRunRecord, StoredSeriesMetadata
from manufacturing_monitor.workflow import ApplicationResult, ApplicationSeriesResult, build_monitor_result


def test_dashboard_data_conversion_helpers():
    result = build_monitor_result(
        {
            "observations": [
                {"date": "2026-01-01", "value": "101.0"},
                {"date": "2026-02-01", "value": "."},
            ]
        }
    )

    assert dashboard._chart_rows(result.observations) == [
        {"date": "2026-01-01", "value": 101.0}
    ]

    normalized = dashboard._normalized_comparison_rows(
        [
            SeriesObservationRow(
                series_id="IPMAN",
                series_name="Industrial Production: Manufacturing (NAICS)",
                units="Index 2017=100",
                date=date(2026, 1, 1),
                raw_value="101.0",
                is_missing=False,
                normalized_value=Decimal("100"),
            ),
            SeriesObservationRow(
                series_id="IPMAN",
                series_name="Industrial Production: Manufacturing (NAICS)",
                units="Index 2017=100",
                date=date(2026, 2, 1),
                raw_value=".",
                is_missing=True,
                normalized_value=None,
            ),
        ]
    )

    assert normalized == [
        {
            "series_id": "IPMAN",
            "series_name": "Industrial Production: Manufacturing (NAICS)",
            "date": "2026-01-01",
            "raw_value": "101.0",
            "normalized_value": 100.0,
        }
    ]


def test_original_unit_chart_grouping_behavior():
    result = SimpleNamespace(
        series_results=(
            SimpleNamespace(
                result=SimpleNamespace(
                    metadata=SimpleNamespace(units="Index 2017=100"),
                    summary=SimpleNamespace(series_id="IPMAN", series_name="Manufacturing"),
                )
            ),
            SimpleNamespace(
                result=SimpleNamespace(
                    metadata=SimpleNamespace(units="Percent"),
                    summary=SimpleNamespace(series_id="MCUMFN", series_name="Capacity Utilization"),
                )
            ),
            SimpleNamespace(
                result=SimpleNamespace(
                    metadata=SimpleNamespace(units="Index 2017=100"),
                    summary=SimpleNamespace(series_id="IPDMAN", series_name="Durable Manufacturing"),
                )
            ),
        ),
        processed_path=Path("data/processed/ipman-ipdman_combined_processed.json"),
    )

    grouped = dashboard._group_series_by_units(result)

    assert list(grouped) == ["Index 2017=100", "Percent"]
    assert [item.result.summary.series_id for item in grouped["Index 2017=100"]] == [
        "IPMAN",
        "IPDMAN",
    ]


def test_dashboard_csv_download_helper():
    result = SimpleNamespace(
        processed_path=Path("data/processed/ipman-ipdman_combined_processed.json")
    )

    assert dashboard._csv_download_name(result) == "ipman-ipdman.csv"


def test_dashboard_smoke_behavior_without_contacting_fred(monkeypatch):
    calls = []

    class FakeSidebar:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def header(self, *_args, **_kwargs):
            return None

        def text_input(self, *_args, **_kwargs):
            return ""

        def multiselect(self, *_args, **kwargs):
            return kwargs.get("default", [])

        def date_input(self, *_args, **_kwargs):
            return None

        def button(self, *_args, **_kwargs):
            return False

    class FakeStreamlit:
        def __init__(self):
            self.session_state = {}
            self.sidebar = FakeSidebar()

        def set_page_config(self, **kwargs):
            calls.append(("set_page_config", kwargs))

        def title(self, *_args, **_kwargs):
            calls.append(("title", _args))

        def caption(self, *_args, **_kwargs):
            calls.append(("caption", _args))

        def info(self, *_args, **_kwargs):
            calls.append(("info", _args))

        def error(self, *_args, **_kwargs):
            calls.append(("error", _args))

        def subheader(self, *_args, **_kwargs):
            calls.append(("subheader", _args))

        def metric(self, *_args, **_kwargs):
            calls.append(("metric", _args))

        def columns(self, count):
            return [SimpleNamespace(__enter__=lambda self=None: self, __exit__=lambda *args: False) for _ in range(count)]

        def warning(self, *_args, **_kwargs):
            calls.append(("warning", _args))

        def header(self, *args, **kwargs):
            return self.sidebar.header(*args, **kwargs)

        def text_input(self, *args, **kwargs):
            return self.sidebar.text_input(*args, **kwargs)

        def multiselect(self, *args, **kwargs):
            return self.sidebar.multiselect(*args, **kwargs)

        def date_input(self, *args, **kwargs):
            return self.sidebar.date_input(*args, **kwargs)

        def button(self, *args, **kwargs):
            return self.sidebar.button(*args, **kwargs)

        def dataframe(self, *_args, **_kwargs):
            calls.append(("dataframe", _args))

        def plotly_chart(self, *_args, **_kwargs):
            calls.append(("plotly_chart", _args))

        def download_button(self, *_args, **_kwargs):
            calls.append(("download_button", _args))

    fake_streamlit = FakeStreamlit()
    workflow_called = Mock(side_effect=AssertionError("workflow should not be called on load"))

    monkeypatch.setattr(dashboard, "st", fake_streamlit)
    monkeypatch.setattr(dashboard, "run_application_workflow", workflow_called)

    dashboard.main()

    assert workflow_called.call_count == 0
    assert any(name == "info" for name, *_ in calls)


def test_dashboard_render_path_with_result(monkeypatch, tmp_path):
    calls = []
    result = _fake_application_result(tmp_path)

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeSidebar:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def header(self, *_args, **_kwargs):
            return None

        def text_input(self, *_args, **_kwargs):
            return ""

        def multiselect(self, *_args, **kwargs):
            return kwargs.get("default", [])

        def date_input(self, *_args, **_kwargs):
            return None

        def button(self, *_args, **_kwargs):
            return False

    class FakeStreamlit:
        def __init__(self):
            self.session_state = {"dashboard_result": result, "dashboard_error": None}
            self.sidebar = FakeSidebar()

        def set_page_config(self, **_kwargs):
            return None

        def title(self, *_args, **_kwargs):
            return None

        def caption(self, *_args, **_kwargs):
            return None

        def info(self, *_args, **_kwargs):
            calls.append("info")

        def error(self, *_args, **_kwargs):
            calls.append("error")

        def header(self, *args, **kwargs):
            return self.sidebar.header(*args, **kwargs)

        def text_input(self, *args, **kwargs):
            return self.sidebar.text_input(*args, **kwargs)

        def multiselect(self, *args, **kwargs):
            return self.sidebar.multiselect(*args, **kwargs)

        def date_input(self, *args, **kwargs):
            return self.sidebar.date_input(*args, **kwargs)

        def button(self, *args, **kwargs):
            return self.sidebar.button(*args, **kwargs)

        def subheader(self, *_args, **_kwargs):
            calls.append("subheader")

        def metric(self, *_args, **_kwargs):
            calls.append("metric")

        def columns(self, count):
            return [FakeColumn() for _ in range(count)]

        def warning(self, *_args, **_kwargs):
            calls.append("warning")

        def dataframe(self, *_args, **_kwargs):
            calls.append("dataframe")

        def plotly_chart(self, *_args, **_kwargs):
            calls.append("plotly_chart")

        def write(self, *_args, **_kwargs):
            calls.append("write")

        def download_button(self, *_args, **_kwargs):
            calls.append("download_button")

    monkeypatch.setattr(dashboard, "st", FakeStreamlit())

    dashboard.main()

    assert "plotly_chart" in calls
    assert "download_button" in calls
    assert "dataframe" in calls


def _fake_application_result(tmp_path: Path) -> ApplicationResult:
    fetched_timestamp = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)

    def build_series(
        series_id: str,
        display_name: str,
        units: str,
        source_kind: str,
        latest_value: str,
    ) -> ApplicationSeriesResult:
        metadata = StoredSeriesMetadata(
            series_id=series_id,
            display_name=display_name,
            units=units,
            frequency="Monthly",
            updated_at_utc=fetched_timestamp.isoformat(),
        )
        summary = SeriesSummary(
            series_id=series_id,
            series_name=display_name,
            units=units,
            frequency="Monthly",
            latest_valid_value=Decimal(latest_value),
            latest_valid_date=date(2026, 5, 1),
            previous_month_change=PercentageChangeResult(
                status="ok",
                reason=None,
                value=Decimal("2.5"),
                latest_date=date(2026, 5, 1),
                latest_value=Decimal(latest_value),
                comparison_date=date(2026, 4, 1),
                comparison_value=Decimal("98.5"),
            ),
            year_over_year_change=PercentageChangeResult(
                status="ok",
                reason=None,
                value=Decimal("4.0"),
                latest_date=date(2026, 5, 1),
                latest_value=Decimal(latest_value),
                comparison_date=date(2025, 5, 1),
                comparison_value=Decimal("97.0"),
            ),
            minimum_value=Decimal("99.0"),
            maximum_value=Decimal(latest_value),
            arithmetic_mean=Decimal("100.0"),
            total_observations=2,
            valid_numeric_observations=2,
            missing_observations=0,
            first_observation_date=date(2026, 4, 1),
            last_observation_date=date(2026, 5, 1),
            status="ok",
            reason=None,
        )
        observations = (
            SeriesObservationRow(
                series_id=series_id,
                series_name=display_name,
                units=units,
                date=date(2026, 4, 1),
                raw_value="99.0",
                is_missing=False,
                normalized_value=None,
            ),
            SeriesObservationRow(
                series_id=series_id,
                series_name=display_name,
                units=units,
                date=date(2026, 5, 1),
                raw_value=latest_value,
                is_missing=False,
                normalized_value=None,
            ),
        )
        normalized = NormalizationResult(
            status="ok",
            reason=None,
            base_date=date(2026, 4, 1),
            base_value=Decimal("99.0"),
            rows=(
                SeriesObservationRow(
                    series_id=series_id,
                    series_name=display_name,
                    units=units,
                    date=date(2026, 4, 1),
                    raw_value="99.0",
                    is_missing=False,
                    normalized_value=Decimal("100"),
                ),
                SeriesObservationRow(
                    series_id=series_id,
                    series_name=display_name,
                    units=units,
                    date=date(2026, 5, 1),
                    raw_value=latest_value,
                    is_missing=False,
                    normalized_value=Decimal("101"),
                ),
            ),
        )
        return ApplicationSeriesResult(
            series_id=series_id,
            source_kind=source_kind,
            raw_path=tmp_path / "data" / "raw" / f"{series_id.lower()}_observations_raw.json",
            fetch_run=FetchRunRecord(
                series_id=series_id,
                requested_start_date=date(2026, 4, 1),
                requested_end_date=date(2026, 5, 1),
                fetched_at_utc=fetched_timestamp,
                validated_observation_count=2,
                source_kind=source_kind,
            ),
            result=SeriesResult(
                metadata=metadata,
                summary=summary,
                observations=observations,
                normalized=normalized,
            ),
        )

    ipman = build_series("IPMAN", "Industrial Production: Manufacturing (NAICS)", "Index 2017=100", "cache", "101.0")
    ipdman = build_series("IPDMAN", "Industrial Production: Durable Manufacturing (NAICS)", "Index 2017=100", "live", "88.0")
    analysis = MultiSeriesResult(
        requested_series_ids=("IPMAN", "IPDMAN"),
        requested_start_date=date(2026, 4, 1),
        requested_end_date=date(2026, 5, 1),
        status="ok",
        reason=None,
        series_results=(ipman.result, ipdman.result),
        observation_rows=ipman.result.observations + ipdman.result.observations,
        normalized_rows=ipman.result.normalized.rows + ipdman.result.normalized.rows,
    )
    return ApplicationResult(
        requested_series_ids=("IPMAN", "IPDMAN"),
        requested_start_date=date(2026, 4, 1),
        requested_end_date=date(2026, 5, 1),
        source_status="mixed",
        source_reason=None,
        generated_at_utc=fetched_timestamp,
        database_path=tmp_path / "monitor.db",
        raw_paths={
            "IPMAN": tmp_path / "data" / "raw" / "ipman_observations_raw.json",
            "IPDMAN": tmp_path / "data" / "raw" / "ipdman_observations_raw.json",
        },
        legacy_processed_path=None,
        processed_path=tmp_path / "data" / "processed" / "ipman-ipdman_combined_processed.json",
        csv_path=tmp_path / "exports" / "combined.csv",
        analysis=analysis,
        series_results=(ipman, ipdman),
    )
