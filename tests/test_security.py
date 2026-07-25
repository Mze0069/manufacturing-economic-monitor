import logging
from unittest.mock import Mock

import pytest
import requests

from manufacturing_monitor.api import AppError, fetch_observations


def test_request_exception_secret_is_not_leaked(monkeypatch, caplog):
    secret = "FAKE_SECRET_DO_NOT_LEAK"
    url = f"https://example.test/fred?api_key={secret}"
    exception = requests.RequestException(f"request failed for {url}")

    monkeypatch.setattr(
        "manufacturing_monitor.api.requests.get",
        Mock(side_effect=exception),
    )
    caplog.set_level(logging.WARNING, logger="manufacturing_monitor.api")

    with pytest.raises(AppError) as excinfo:
        fetch_observations("test-key")

    assert secret not in str(excinfo.value)
    assert secret not in caplog.text
    assert url not in caplog.text
    assert "Could not connect to FRED. Check your network and try again." in str(
        excinfo.value
    )
