"""Tests for structured logging and correlation ID propagation."""
import json
import logging
import pytest
from backend.services.logging_setup import corr_id_var, set_corr_id


@pytest.mark.unit
def test_set_corr_id_sets_contextvar():
    token = set_corr_id("test123")
    assert corr_id_var.get() == "test123"
    corr_id_var.reset(token)


@pytest.mark.unit
def test_corr_id_defaults_to_empty():
    assert corr_id_var.get("") == ""


@pytest.mark.unit
def test_corr_id_isolated_between_calls():
    """Setting and resetting corr_id restores prior value."""
    token1 = set_corr_id("first")
    token2 = set_corr_id("second")
    assert corr_id_var.get() == "second"
    corr_id_var.reset(token2)
    assert corr_id_var.get() == "first"
    corr_id_var.reset(token1)


@pytest.mark.unit
def test_json_formatter_includes_required_fields():
    """_JSONFormatter output contains ts, level, logger, corr_id, msg."""
    from backend.services.logging_setup import _JSONFormatter, _CorrIdFilter

    formatter = _JSONFormatter()
    filt = _CorrIdFilter()

    record = logging.LogRecord(
        name="mylogger", level=logging.WARNING,
        pathname="", lineno=0,
        msg="test message", args=(), exc_info=None,
    )
    filt.filter(record)
    output = json.loads(formatter.format(record))

    for field in ("ts", "level", "logger", "corr_id", "msg"):
        assert field in output, f"missing field: {field}"

    assert output["logger"] == "mylogger"
    assert output["level"] == "WARNING"
    assert output["msg"] == "test message"


@pytest.mark.unit
def test_json_formatter_injects_active_corr_id():
    """_JSONFormatter picks up corr_id from contextvar when set."""
    from backend.services.logging_setup import _JSONFormatter, _CorrIdFilter

    formatter = _JSONFormatter()
    filt = _CorrIdFilter()

    token = set_corr_id("corr-abc")
    try:
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        filt.filter(record)
        output = json.loads(formatter.format(record))
        assert output["corr_id"] == "corr-abc"
    finally:
        corr_id_var.reset(token)
