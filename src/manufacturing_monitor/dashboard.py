from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
import streamlit as st

from manufacturing_monitor.api import AppError
from manufacturing_monitor.logging_config import configure_logging
from manufacturing_monitor.models import FredDataValidationError
from manufacturing_monitor.workflow import MonitorRequest, run_monitor


def main() -> None:
    load_dotenv()
    configure_logging(verbose=False, log_file=None)

    st.set_page_config(page_title="Manufacturing Economic Monitor")
    st.title("Manufacturing Economic Monitor")

    env_key = os.environ.get("FRED_API_KEY", "")
    typed_key = st.text_input("FRED API key", type="password")
    api_key = typed_key or env_key

    if st.button("Fetch data"):
        if not api_key:
            st.error("FRED_API_KEY is required. Enter a key or add one to .env.")
            return

        try:
            with st.spinner("Fetching and validating FRED data..."):
                result = run_monitor(MonitorRequest(api_key=api_key))
        except (AppError, FredDataValidationError, ValueError) as exc:
            st.error(str(exc))
            return

        st.metric(
            "Latest manufacturing index",
            result.latest.value,
            help=f"Observation date: {result.latest.date}",
        )
        st.write(f"Latest observation date: {result.latest.date}")
        rows = _chart_rows(result.observations)
        st.line_chart(rows, x="date", y="value")
        st.dataframe(list(reversed(rows[-10:])), hide_index=True)


def _chart_rows(observations: tuple[Any, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        if observation.value == ".":
            continue
        rows.append({"date": observation.date, "value": float(observation.value)})
    return rows


if __name__ == "__main__":
    main()
