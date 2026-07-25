from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from manufacturing_monitor import __version__
from manufacturing_monitor.api import AppError
from manufacturing_monitor.db import DatabaseError
from manufacturing_monitor.logging_config import LoggingSetupError, configure_logging
from manufacturing_monitor.models import FredDataValidationError
from manufacturing_monitor.output import OutputWriteError
from manufacturing_monitor.series_catalog import get_supported_series, supported_series_ids
from manufacturing_monitor.workflow import (
    ApplicationRequest,
    WorkflowError,
    run_application_workflow,
)


API_KEY_NAME = "FRED_API_KEY"
DEFAULT_SERIES_ID = "IPMAN"
DEFAULT_DATABASE_PATH = Path("data/manufacturing_monitor.db")
logger = logging.getLogger(__name__)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="manufacturing-monitor",
        description="Fetch and validate supported FRED manufacturing observations.",
    )
    parser.add_argument(
        "--series",
        action="append",
        dest="series_ids",
        metavar="SERIES_ID",
        help="request a supported FRED series; repeat for multiple series",
    )
    parser.add_argument(
        "--start-date",
        type=_parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="limit observations to dates on or after this ISO date",
    )
    parser.add_argument(
        "--end-date",
        type=_parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="limit observations to dates on or before this ISO date",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="refresh the selected series from FRED instead of relying on cache",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        metavar="PATH",
        help="SQLite cache path",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=None,
        metavar="PATH",
        help="write the combined normalized rows to CSV at PATH",
    )
    parser.add_argument(
        "--project-info",
        action="store_true",
        help="print project information and exit without contacting FRED",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="write operational diagnostic logs to stderr",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="write detailed diagnostic logs to PATH",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    load_dotenv()
    args = parse_args(argv)

    try:
        configure_logging(verbose=args.verbose, log_file=args.log_file)
    except LoggingSetupError as exc:
        raise SystemExit(str(exc)) from exc

    if args.project_info:
        _print_project_info()
        return

    series_ids = tuple(args.series_ids or (DEFAULT_SERIES_ID,))
    api_key = os.environ.get(API_KEY_NAME, "").strip() or None

    try:
        result = run_application_workflow(
            ApplicationRequest(
                series_ids=series_ids,
                api_key=api_key,
                observation_start=args.start_date,
                observation_end=args.end_date,
                db_path=args.database,
                refresh=args.refresh,
                csv_output=args.csv_output,
            )
        )
    except (AppError, DatabaseError, FredDataValidationError, OutputWriteError, ValueError, WorkflowError) as exc:
        logger.warning("Manufacturing monitor run failed.")
        raise SystemExit(str(exc)) from exc

    _print_result(result)


def _print_project_info() -> None:
    print("Manufacturing Economic Monitor")
    print(f"Version: {__version__}")
    print(f"Default series: {DEFAULT_SERIES_ID}")
    print("Supported series:")
    for series_id in supported_series_ids():
        series = get_supported_series(series_id)
        print(f"  - {series.display_name} ({series.series_id})")
    print("Network: not contacted")


def _print_result(result) -> None:
    print("Manufacturing Economic Monitor")
    print(f"Data source: {result.source_status}")
    if result.source_reason:
        print(f"Note: {result.source_reason}")
    print(f"Database: {result.database_path}")
    print(f"Processed JSON: {result.processed_path}")
    if result.legacy_processed_path is not None:
        print(f"Legacy processed JSON: {result.legacy_processed_path}")
    if result.csv_path is not None:
        print(f"CSV: {result.csv_path}")
    if result.raw_paths:
        for series_id, path in result.raw_paths.items():
            print(f"Raw {series_id}: {path}")
    print()
    for series_result in result.series_results:
        print(_format_series_summary(series_result))
        print()


def _format_series_summary(series_result) -> str:
    summary = series_result.result.summary
    lines = [
        f"{summary.series_name} ({summary.series_id})",
        f"  Latest value: {_format_optional_decimal(summary.latest_valid_value)}"
        f" on {_format_optional_date(summary.latest_valid_date)}",
        f"  Month-over-month: {_format_change(summary.previous_month_change)}",
        f"  Year-over-year: {_format_change(summary.year_over_year_change)}",
        f"  Minimum: {_format_optional_decimal(summary.minimum_value)}",
        f"  Maximum: {_format_optional_decimal(summary.maximum_value)}",
        f"  Mean: {_format_optional_decimal(summary.arithmetic_mean)}",
        f"  Valid observations: {summary.valid_numeric_observations}",
        f"  Missing observations: {summary.missing_observations}",
        f"  Source: {series_result.source_kind}",
    ]
    if series_result.fetch_run is not None:
        lines.append(f"  Last fetch: {series_result.fetch_run.fetched_at_utc.isoformat()}")
    return "\n".join(lines)


def _format_change(change) -> str:
    if change.value is not None:
        return f"{change.value:.2f}%"
    if change.reason:
        return f"unavailable ({change.reason})"
    return "unavailable"


def _format_optional_decimal(value) -> str:
    return format(value, "f") if value is not None else "unavailable"


def _format_optional_date(value: date | None) -> str:
    return value.isoformat() if value is not None else "unavailable"


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an ISO date in YYYY-MM-DD format") from exc
