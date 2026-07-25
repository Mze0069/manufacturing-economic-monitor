import json

from manufacturing_monitor.output import write_processed_json, write_raw_json
from manufacturing_monitor.workflow import build_monitor_result


def test_raw_and_processed_output_writing(tmp_path):
    payload = {
        "observations": [
            {"date": "2026-01-01", "value": "101.0"},
            {"date": "2026-02-01", "value": "."},
        ]
    }
    result = build_monitor_result(payload)
    raw_path = tmp_path / "raw" / "ipman.json"
    processed_path = tmp_path / "processed" / "ipman.json"

    write_raw_json(payload, raw_path)
    write_processed_json(result.observations, processed_path)

    assert json.loads(raw_path.read_text(encoding="utf-8")) == payload
    assert json.loads(processed_path.read_text(encoding="utf-8")) == [
        {"date": "2026-01-01", "value": "101.0"},
        {"date": "2026-02-01", "value": "."},
    ]
