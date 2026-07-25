import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from manufacturing_monitor.models import FredDataValidationError, validate_fred_response
from manufacturing_monitor.workflow import (
    MonitorRequest,
    build_monitor_result,
    fetch_monitor_data,
    latest_valid_observation,
)


FIXTURE = Path(__file__).parent / "fixtures" / "fred-ipman-sample.json"
INVALID_FIXTURE = Path(__file__).parent / "fixtures" / "fred-ipman-invalid.json"


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_build_monitor_result_validates_and_finds_latest_numeric_before_placeholder():
    result = build_monitor_result(load_fixture())

    assert len(result.observations) == 6
    assert result.latest.date == "2026-05-01"
    assert result.latest.value == "103.1189"


def test_validation_rejects_malformed_response():
    with pytest.raises(FredDataValidationError, match="value"):
        validate_fred_response(json.loads(INVALID_FIXTURE.read_text(encoding="utf-8")))


def test_validation_rejects_missing_observations():
    with pytest.raises(FredDataValidationError, match="observations"):
        validate_fred_response({"count": 0})


def test_validation_rejects_invalid_observation_date():
    payload = load_fixture()
    payload["observations"][0]["date"] = "not-a-date"

    with pytest.raises(FredDataValidationError, match="date"):
        validate_fred_response(payload)


def test_latest_valid_observation_rejects_all_placeholders():
    result = build_monitor_result(load_fixture())
    placeholders = tuple(
        type(observation)(date=observation.date, value=".")
        for observation in result.observations
    )

    with pytest.raises(ValueError, match="No valid numeric"):
        latest_valid_observation(placeholders)


def test_fetch_monitor_data_uses_api_boundary(monkeypatch):
    fetch = Mock(return_value={"observations": []})
    monkeypatch.setattr("manufacturing_monitor.workflow.fetch_observations", fetch)

    payload = fetch_monitor_data(
        MonitorRequest(
            api_key="test-key",
            series_id="IPDMAN",
            observation_start="2026-01-01",
            observation_end="2026-06-01",
        )
    )

    assert payload == {"observations": []}
    fetch.assert_called_once_with(
        "test-key",
        series_id="IPDMAN",
        observation_start="2026-01-01",
        observation_end="2026-06-01",
    )


def test_monitor_request_defaults_preserve_backwards_compatibility(monkeypatch):
    fetch = Mock(return_value={"observations": []})
    monkeypatch.setattr("manufacturing_monitor.workflow.fetch_observations", fetch)

    fetch_monitor_data(MonitorRequest(api_key="test-key"))

    fetch.assert_called_once_with(
        "test-key",
        series_id="IPMAN",
        observation_start=None,
        observation_end=None,
    )
