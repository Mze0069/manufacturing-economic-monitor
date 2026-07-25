from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from manufacturing_monitor.api import AppError
from manufacturing_monitor.logging_config import LoggingSetupError, configure_logging
from manufacturing_monitor.models import FredDataValidationError
from manufacturing_monitor.output import (
    OutputWriteError,
    write_processed_json,
    write_raw_json,
)
from manufacturing_monitor.workflow import (
    MonitorRequest,
    build_monitor_result,
    fetch_monitor_data,
    format_summary,
)


RAW_OUTPUT_PATH = Path("data/raw/ipman_observations_raw.json")
PROCESSED_OUTPUT_PATH = Path("data/processed/ipman_observations_processed.json")
API_KEY_NAME = "FRED_API_KEY"
logger = logging.getLogger(__name__)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="manufacturing-monitor",
        description="Fetch and validate FRED IPMAN manufacturing observations.",
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
    parser.add_argument(
        "--project-info",
        action="store_true",
        help="print project information and exit without contacting FRED",
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
        print("Manufacturing Economic Monitor")
        print("Series: FRED IPMAN")
        print("Network: not contacted")
        return

    api_key = os.environ.get(API_KEY_NAME, "")
    if not api_key:
        raise SystemExit(
            f"{API_KEY_NAME} is required. Copy .env.example to .env and add a key."
        )

    try:
        request = MonitorRequest(api_key=api_key)
        raw_payload = fetch_monitor_data(request)
        write_raw_json(raw_payload, RAW_OUTPUT_PATH)
        logger.info("Saved raw FRED response to %s.", RAW_OUTPUT_PATH)
        result = build_monitor_result(raw_payload)
        write_processed_json(result.observations, PROCESSED_OUTPUT_PATH)
        logger.info("Saved processed FRED observations to %s.", PROCESSED_OUTPUT_PATH)
    except (AppError, FredDataValidationError, OutputWriteError, ValueError) as exc:
        logger.warning("Monitor run failed: %s", exc)
        raise SystemExit(str(exc)) from exc

    print(format_summary(result))
