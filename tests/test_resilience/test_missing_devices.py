"""Tests for graceful degradation when devices/services are missing."""
import pytest
from unittest.mock import patch, MagicMock
import requests as req_lib


@pytest.mark.unit
def test_check_ollama_returns_false_when_down():
    from backend.services.health import check_ollama

    with patch("backend.services.health.requests.get", side_effect=req_lib.ConnectionError("down")):
        result = check_ollama("http://localhost:11434")

    assert result is False


@pytest.mark.unit
def test_check_ollama_returns_false_on_non_200():
    from backend.services.health import check_ollama

    mock_resp = MagicMock()
    mock_resp.status_code = 503
    with patch("backend.services.health.requests.get", return_value=mock_resp):
        result = check_ollama("http://localhost:11434")

    assert result is False


@pytest.mark.unit
def test_check_ollama_returns_true_on_200():
    from backend.services.health import check_ollama

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("backend.services.health.requests.get", return_value=mock_resp):
        result = check_ollama("http://localhost:11434")

    assert result is True


@pytest.mark.unit
def test_check_piper_returns_false_for_missing_path(tmp_path):
    from backend.services.health import check_piper

    result = check_piper(str(tmp_path / "nonexistent_piper"))
    assert result is False


@pytest.mark.unit
def test_check_piper_returns_false_for_empty_path():
    from backend.services.health import check_piper

    assert check_piper("") is False
    assert check_piper(None) is False


@pytest.mark.unit
def test_check_piper_returns_true_for_executable(tmp_path):
    from backend.services.health import check_piper

    bin_path = tmp_path / "piper"
    bin_path.write_text("#!/bin/sh\n")
    bin_path.chmod(0o755)
    assert check_piper(str(bin_path)) is True
