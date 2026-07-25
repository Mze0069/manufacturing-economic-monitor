from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
import logging
import os
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from dotenv import load_dotenv
import streamlit as st

from manufacturing_monitor.logging_config import configure_logging
from manufacturing_monitor.output import build_processed_csv_text
from manufacturing_monitor.series_catalog import get_supported_series, supported_series_ids
from manufacturing_monitor.workflow import (
    ApplicationRequest,
    ApplicationResult,
    WorkflowError,
    run_application_workflow,
)


DEFAULT_DASHBOARD_SERIES = ("IPMAN", "IPDMAN", "IPNMAN")
logger = logging.getLogger(__name__)


def main() -> None:
    load_dotenv()
    configure_logging(verbose=False, log_file=None)

    st.set_page_config(
        page_title="Manufacturing Economic Intelligence Dashboard",
        page_icon="M",
        layout="wide",
    )

    _render_sidebar()
    st.title("Manufacturing Economic Intelligence Dashboard")
    st.caption(
        "Compare supported manufacturing indicators, review cache status, and refresh selected "
        "series from FRED only when you choose to do so."
    )
    st.info(
        "Interpretation note: charts keep original units separate by unit group, and the "
        "normalized comparison chart starts every selected series at 100."
    )

    result = st.session_state.get("dashboard_result")
    error = st.session_state.get("dashboard_error")
    if error:
        st.error(error)

    if result is None:
        st.info("Choose cached or refresh mode in the sidebar to load data.")
        return

    _render_result(result)


def _render_sidebar() -> None:
    with st.sidebar:
        st.header("Controls")
        typed_key = st.text_input("FRED API key", type="password", help="Optional unless you refresh.")
        env_key = os.environ.get("FRED_API_KEY", "").strip()
        api_key = typed_key.strip() or env_key or None

        series_ids = supported_series_ids()
        selected_series = st.multiselect(
            "Supported series",
            options=series_ids,
            default=[series_id for series_id in DEFAULT_DASHBOARD_SERIES if series_id in series_ids],
            format_func=_series_label,
        )

        start_date = st.date_input("Start date", value=None)
        end_date = st.date_input("End date", value=None)
        database_path = st.text_input("Database path", value=str(Path("data/manufacturing_monitor.db")))

        load_cached = st.button("Load cached data")
        refresh = st.button("Refresh selected series from FRED")

    if refresh or load_cached:
        if not selected_series:
            st.session_state["dashboard_error"] = "Select at least one supported series."
            st.session_state["dashboard_result"] = None
            return

        if refresh and not api_key:
            st.session_state["dashboard_error"] = "A FRED API key is required to refresh selected series."
            st.session_state["dashboard_result"] = None
            return

        try:
            with st.spinner("Loading manufacturing data..."):
                st.session_state["dashboard_result"] = run_application_workflow(
                    ApplicationRequest(
                        series_ids=tuple(selected_series),
                        api_key=api_key,
                        observation_start=start_date,
                        observation_end=end_date,
                        db_path=Path(database_path),
                        refresh=refresh,
                        cache_only=load_cached and not refresh,
                    )
                )
                st.session_state["dashboard_error"] = None
        except (WorkflowError, ValueError, OSError) as exc:
            logger.warning("Dashboard request failed.")
            st.session_state["dashboard_error"] = str(exc)
            st.session_state["dashboard_result"] = None


def _render_result(result: ApplicationResult) -> None:
    _render_overview(result)
    _render_latest_cards(result)
    _render_original_unit_charts(result)
    _render_normalized_chart(result)
    _render_summary_table(result)
    _render_recent_observations(result)
    _render_missing_information(result)
    _render_status_and_download(result)


def _render_overview(result: ApplicationResult) -> None:
    st.subheader("Run overview")
    left, middle, right = st.columns(3)
    with left:
        st.metric("Source status", result.source_status)
    with middle:
        st.metric(
            "Date range",
            _format_date(result.requested_start_date),
            help=_format_date(result.requested_end_date),
        )
    with right:
        st.metric("Database", str(result.database_path))
    if result.source_reason:
        st.warning(result.source_reason)


def _render_latest_cards(result: ApplicationResult) -> None:
    st.subheader("Latest values")
    columns = st.columns(max(len(result.series_results), 1))
    for column, series_result in zip(columns, result.series_results, strict=False):
        summary = series_result.result.summary
        with column:
            st.metric(
                f"{summary.series_name} ({summary.series_id})",
                _format_decimal(summary.latest_valid_value),
                delta=_format_change_delta(summary.previous_month_change),
            )
            st.caption(f"Latest date: {_format_date(summary.latest_valid_date)}")
            st.caption(f"Year-over-year: {_format_change(summary.year_over_year_change)}")
            st.caption(
                f"Valid: {summary.valid_numeric_observations} | Missing: {summary.missing_observations}"
            )


def _render_original_unit_charts(result: ApplicationResult) -> None:
    st.subheader("Original-unit charts")
    groups = _group_series_by_units(result)
    if not groups:
        st.info("No observations are available for the selected series and date range.")
        return

    for units, series_results in groups.items():
        figure = go.Figure()
        for series_result in series_results:
            rows = _chart_rows(series_result.result.observations)
            if not rows:
                continue
            figure.add_trace(
                go.Scatter(
                    x=[row["date"] for row in rows],
                    y=[row["value"] for row in rows],
                    mode="lines+markers",
                    name=f"{series_result.result.summary.series_id} - {series_result.result.summary.series_name}",
                )
            )
        figure.update_layout(
            title=units,
            xaxis_title="Date",
            yaxis_title=units,
            legend_title="Series",
            height=380,
            margin={"l": 24, "r": 24, "t": 48, "b": 24},
        )
        st.plotly_chart(figure, use_container_width=True)


def _render_normalized_chart(result: ApplicationResult) -> None:
    st.subheader("Normalized comparison")
    rows = _normalized_comparison_rows(result.analysis.normalized_rows)
    if not rows:
        st.info("No normalized comparison rows are available.")
        return

    figure = go.Figure()
    by_series: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_series[row["series_id"]].append(row)

    for series_id, series_rows in by_series.items():
        figure.add_trace(
            go.Scatter(
                x=[row["date"] for row in series_rows],
                y=[row["normalized_value"] for row in series_rows],
                mode="lines+markers",
                name=f"{series_id} - {series_rows[0]['series_name']}",
            )
        )

    figure.update_layout(
        title="Every selected series starts at 100",
        xaxis_title="Date",
        yaxis_title="Normalized index",
        legend_title="Series",
        height=420,
        margin={"l": 24, "r": 24, "t": 48, "b": 24},
    )
    st.plotly_chart(figure, use_container_width=True)


def _render_summary_table(result: ApplicationResult) -> None:
    st.subheader("Summary statistics")
    st.dataframe(_summary_rows(result), hide_index=True, use_container_width=True)


def _render_recent_observations(result: ApplicationResult) -> None:
    st.subheader("Recent observations")
    recent_rows = _recent_observation_rows(result.analysis.observation_rows, limit=20)
    if not recent_rows:
        st.info("No observation rows are available.")
        return
    st.dataframe(recent_rows, hide_index=True, use_container_width=True)


def _render_missing_information(result: ApplicationResult) -> None:
    st.subheader("Missing-value information")
    rows = [
        {
            "series_id": series_result.result.summary.series_id,
            "series_name": series_result.result.summary.series_name,
            "missing_observations": series_result.result.summary.missing_observations,
            "valid_numeric_observations": series_result.result.summary.valid_numeric_observations,
            "status": series_result.result.summary.status,
        }
        for series_result in result.series_results
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)


def _render_status_and_download(result: ApplicationResult) -> None:
    st.subheader("Cache and export")
    left, right = st.columns(2)
    with left:
        st.write(f"Source status: {result.source_status}")
        st.write(f"Database path: {result.database_path}")
        st.write(f"Processed JSON: {result.processed_path}")
        if result.legacy_processed_path is not None:
            st.write(f"Legacy processed JSON: {result.legacy_processed_path}")
        for series_result in result.series_results:
            if series_result.fetch_run is None:
                continue
            st.write(
                f"{series_result.series_id} last refresh: "
                f"{series_result.fetch_run.fetched_at_utc.isoformat()}"
            )
    with right:
        csv_text = build_processed_csv_text(result.analysis.normalized_rows)
        st.download_button(
            "Download CSV",
            data=csv_text,
            file_name=_csv_download_name(result),
            mime="text/csv",
            use_container_width=True,
        )


def _chart_rows(observations: Sequence[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        value = getattr(observation, "value", getattr(observation, "raw_value", None))
        if value in {None, "."}:
            continue
        rows.append(
            {
                "date": _date_text(getattr(observation, "date", None)),
                "value": float(value),
            }
        )
    return rows


def _normalized_comparison_rows(rows: Sequence[Any]) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if row.normalized_value is None:
            continue
        normalized_rows.append(
            {
                "series_id": row.series_id,
                "series_name": row.series_name,
                "date": row.date.isoformat(),
                "raw_value": row.raw_value,
                "normalized_value": float(row.normalized_value),
            }
        )
    return normalized_rows


def _group_series_by_units(result: ApplicationResult) -> dict[str, tuple[Any, ...]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for series_result in result.series_results:
        units = series_result.result.metadata.units
        grouped[units].append(series_result)
    return {units: tuple(series_results) for units, series_results in grouped.items()}


def _summary_rows(result: ApplicationResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for series_result in result.series_results:
        summary = series_result.result.summary
        rows.append(
            {
                "series_id": summary.series_id,
                "series_name": summary.series_name,
                "latest_value": _format_decimal(summary.latest_valid_value),
                "latest_date": _format_date(summary.latest_valid_date),
                "month_over_month": _format_change(summary.previous_month_change),
                "year_over_year": _format_change(summary.year_over_year_change),
                "minimum": _format_decimal(summary.minimum_value),
                "maximum": _format_decimal(summary.maximum_value),
                "mean": _format_decimal(summary.arithmetic_mean),
                "valid": summary.valid_numeric_observations,
                "missing": summary.missing_observations,
                "source": series_result.source_kind,
            }
        )
    return rows


def _recent_observation_rows(observations: Sequence[Any], *, limit: int) -> list[dict[str, Any]]:
    ordered = sorted(
        observations,
        key=lambda row: (row.date, row.series_id),
        reverse=True,
    )[:limit]
    rows: list[dict[str, Any]] = []
    for row in ordered:
        rows.append(
            {
                "series_id": row.series_id,
                "series_name": row.series_name,
                "date": row.date.isoformat(),
                "raw_value": row.raw_value,
                "is_missing": row.is_missing,
                "normalized_value": (
                    float(row.normalized_value) if row.normalized_value is not None else None
                ),
            }
        )
    return rows


def _format_change(change: Any) -> str:
    if change.value is not None:
        return f"{change.value:.2f}%"
    if change.reason:
        return f"unavailable ({change.reason})"
    return "unavailable"


def _format_change_delta(change: Any) -> str:
    if change.value is not None:
        return f"{change.value:.2f}%"
    return "unavailable"


def _format_decimal(value: Any) -> str:
    return format(value, "f") if value is not None else "unavailable"


def _format_date(value: date | str | None) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, str):
        return value
    return value.isoformat()


def _date_text(value: date | str | None) -> str:
    return _format_date(value)


def _series_label(series_id: str) -> str:
    series = get_supported_series(series_id)
    return f"{series.display_name} ({series.series_id})"


def _csv_download_name(result: ApplicationResult) -> str:
    stem = result.processed_path.stem.replace("_combined_processed", "")
    return f"{stem}.csv"


if __name__ == "__main__":
    main()
