"""Tests for LLMParser retry behavior on network failures."""
import pytest
from unittest.mock import patch, MagicMock
import requests as req_lib


@pytest.mark.unit
def test_retries_on_connection_error():
    """_post_with_retry retries on ConnectionError and succeeds on final attempt."""
    from backend.services.llm_parser import _post_with_retry

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    call_count = {"n": 0}

    def fake_post(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise req_lib.ConnectionError("refused")
        return mock_resp

    with patch("backend.services.llm_parser.requests.post", side_effect=fake_post):
        result = _post_with_retry(
            "http://localhost:11434/api/generate",
            json={"model": "test", "prompt": "hi"},
            timeout=1.0,
            retries=3,
            base=0.0,
        )

    assert result is mock_resp
    assert call_count["n"] == 3


@pytest.mark.unit
def test_retries_on_timeout():
    """_post_with_retry retries on Timeout and succeeds on second attempt."""
    from backend.services.llm_parser import _post_with_retry

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    call_count = {"n": 0}

    def fake_post(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise req_lib.Timeout("timed out")
        return mock_resp

    with patch("backend.services.llm_parser.requests.post", side_effect=fake_post):
        result = _post_with_retry(
            "http://localhost:11434/api/generate",
            json={},
            timeout=1.0,
            retries=3,
            base=0.0,
        )

    assert result is mock_resp
    assert call_count["n"] == 2


@pytest.mark.unit
def test_raises_after_max_retries():
    """_post_with_retry raises last exception when all retries exhausted."""
    from backend.services.llm_parser import _post_with_retry

    with patch(
        "backend.services.llm_parser.requests.post",
        side_effect=req_lib.ConnectionError("always down"),
    ):
        with pytest.raises(req_lib.ConnectionError):
            _post_with_retry(
                "http://localhost:11434/api/generate",
                json={},
                timeout=0.1,
                retries=2,
                base=0.0,
            )
