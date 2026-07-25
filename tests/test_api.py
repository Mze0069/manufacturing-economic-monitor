from datetime import date
from unittest.mock import Mock

import pytest
import requests

from manufacturing_monitor.api import FRED_API_URL, AppError, fetch_observations
from manufacturing_monitor.series_catalog import SUPPORTED_SERIES_BY_ID


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


def test_fetch_observations_accepts_any_supported_series_with_dates(monkeypatch):
    response = Mock()
    response.json.return_value = {"observations": []}
    get = Mock(return_value=response)
    monkeypatch.setattr("manufacturing_monitor.api.requests.get", get)

    payload = fetch_observations(
        "test-key",
        series_id="IPDMAN",
        observation_start="2026-01-01",
        observation_end=date(2026, 6, 1),
    )

    assert payload == {"observations": []}
    get.assert_called_once_with(
        FRED_API_URL,
        params={
            "series_id": "IPDMAN",
            "api_key": "test-key",
            "file_type": "json",
            "observation_start": "2026-01-01",
            "observation_end": "2026-06-01",
        },
        timeout=30.0,
    )


def test_fetch_observations_rejects_missing_api_key():
    with pytest.raises(AppError, match="FRED_API_KEY is required"):
        fetch_observations("  ")


def test_fetch_observations_rejects_unsupported_series(monkeypatch):
    get = Mock()
    monkeypatch.setattr("manufacturing_monitor.api.requests.get", get)

    with pytest.raises(AppError, match="supported series"):
        fetch_observations("test-key", series_id="NOT-A-SUPPORTED-SERIES")

    get.assert_not_called()


def test_fetch_observations_rejects_invalid_date_range(monkeypatch):
    get = Mock()
    monkeypatch.setattr("manufacturing_monitor.api.requests.get", get)

    with pytest.raises(AppError, match="cannot be after observation_end"):
        fetch_observations(
            "test-key",
            series_id="IPMAN",
            observation_start="2026-06-01",
            observation_end="2026-05-01",
        )

    get.assert_not_called()


def test_fetch_observations_rejects_invalid_iso_date(monkeypatch):
    get = Mock()
    monkeypatch.setattr("manufacturing_monitor.api.requests.get", get)

    with pytest.raises(AppError, match="ISO date"):
        fetch_observations(
            "test-key",
            series_id="IPMAN",
            observation_start="2026-13-01",
        )

    get.assert_not_called()


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

    with pytest.raises(AppError, match="Could not connect to FRED"):
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


def test_supported_series_catalog_exposes_expected_metadata():
    assert SUPPORTED_SERIES_BY_ID["IPMAN"].display_name == (
        "Industrial Production: Manufacturing (NAICS)"
    )
    assert SUPPORTED_SERIES_BY_ID["MCUMFN"].units == "Percent, Seasonally Adjusted"
