from unittest.mock import Mock

import pytest
import requests

from manufacturing_monitor.api import FRED_API_URL, AppError, fetch_observations


def test_fetch_observations_returns_json_object_and_passes_expected_params(monkeypatch):
    response = Mock()
    response.json.return_value = {"observations": []}
    get = Mock(return_value=response)
    monkeypatch.setattr("manufacturing_monitor.api.requests.get", get)

    payload = fetch_observations("test-key")

    assert payload == {"observations": []}
    get.assert_called_once_with(
        FRED_API_URL,
        params={
            "series_id": "IPMAN",
            "api_key": "test-key",
            "file_type": "json",
        },
        timeout=30.0,
    )
    response.raise_for_status.assert_called_once_with()


def test_fetch_observations_rejects_missing_api_key():
    with pytest.raises(AppError, match="FRED_API_KEY is required"):
        fetch_observations("  ")


def test_fetch_observations_explains_http_failure(monkeypatch):
    response = Mock()
    response.raise_for_status.side_effect = requests.HTTPError(
        response=Mock(status_code=429)
    )
    monkeypatch.setattr("manufacturing_monitor.api.requests.get", Mock(return_value=response))

    with pytest.raises(AppError, match="HTTP status 429"):
        fetch_observations("test-key")


def test_fetch_observations_explains_connection_failure(monkeypatch):
    monkeypatch.setattr(
        "manufacturing_monitor.api.requests.get",
        Mock(side_effect=requests.ConnectionError("network unavailable")),
    )

    with pytest.raises(AppError, match="network unavailable"):
        fetch_observations("test-key")


def test_fetch_observations_explains_timeout(monkeypatch):
    monkeypatch.setattr(
        "manufacturing_monitor.api.requests.get",
        Mock(side_effect=requests.Timeout("slow")),
    )

    with pytest.raises(AppError, match="timed out"):
        fetch_observations("test-key")


def test_fetch_observations_rejects_invalid_json(monkeypatch):
    response = Mock()
    response.json.side_effect = ValueError("not json")
    monkeypatch.setattr("manufacturing_monitor.api.requests.get", Mock(return_value=response))

    with pytest.raises(AppError, match="not valid JSON"):
        fetch_observations("test-key")


def test_fetch_observations_rejects_non_object_response(monkeypatch):
    response = Mock()
    response.json.return_value = ["not", "an", "object"]
    monkeypatch.setattr("manufacturing_monitor.api.requests.get", Mock(return_value=response))

    with pytest.raises(AppError, match="JSON object"):
        fetch_observations("test-key")
