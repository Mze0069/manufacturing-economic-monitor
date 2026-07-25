from manufacturing_monitor.dashboard import _chart_rows
from manufacturing_monitor.workflow import build_monitor_result


def test_chart_rows_skip_fred_placeholder_values():
    result = build_monitor_result(
        {
            "observations": [
                {"date": "2026-01-01", "value": "101.0"},
                {"date": "2026-02-01", "value": "."},
            ]
        }
    )

    assert _chart_rows(result.observations) == [
        {"date": "2026-01-01", "value": 101.0}
    ]
