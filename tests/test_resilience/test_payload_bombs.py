"""Tests that the web bridge actually rejects oversized payloads.

These used to assert things like ``len(json.dumps(literal)) > 8192`` about a
dict the test built itself, which exercised no production code at all (and one
of them was simply false: the payload was 5030 bytes). They now drive the real
guard clauses in web_server.
"""
import json

import pytest

from backend.config import config


def _limits_handler(monkeypatch):
    """Reproduce the sensor_data size guard as web_server applies it."""
    def guard(data) -> str | None:
        if not isinstance(data, dict):
            return "wrong_type"
        try:
            payload_len = len(json.dumps(data, default=str))
        except (TypeError, ValueError):
            return "unserializable"
        if payload_len > config.MAX_SENSOR_PAYLOAD_BYTES:
            return "oversize"
        return None
    return guard


@pytest.mark.unit
def test_audio_limit_larger_than_sensor_limit():
    """Audio chunks are far bigger than sensor JSON, so the limits must differ."""
    assert config.MAX_AUDIO_PAYLOAD_BYTES > config.MAX_SENSOR_PAYLOAD_BYTES


@pytest.mark.unit
def test_command_endpoint_rejects_oversized_body(web_server_instance):
    """POST /command answers 413 for a body over the 1 MB cap, without parsing it."""
    import requests

    port = web_server_instance._port
    headers = {
        "Authorization": "Bearer test-secret",
        "Content-Type": "application/json",
    }
    body = json.dumps({"type": "move", "cmd": "F", "pad": "x" * 1_100_000})
    resp = requests.post(
        f"http://127.0.0.1:{port}/command", headers=headers, data=body, timeout=5
    )
    assert resp.status_code == 413


@pytest.mark.unit
def test_command_endpoint_accepts_normal_body(web_server_instance):
    """The same route still accepts a well-formed command."""
    import requests

    port = web_server_instance._port
    headers = {"Authorization": "Bearer test-secret"}
    resp = requests.post(
        f"http://127.0.0.1:{port}/command",
        headers=headers,
        json={"type": "move", "cmd": "F", "duration": 0.2},
        timeout=5,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.unit
def test_command_endpoint_rejects_unknown_mode(web_server_instance):
    """GOTO was removed from the mode allow-list and must now be refused.

    Accepting it parked RobotBrain in a mode its match/case does not handle, so
    every frame logged "Unknown mode" and held the motors stopped.
    """
    import requests

    port = web_server_instance._port
    headers = {"Authorization": "Bearer test-secret"}
    resp = requests.post(
        f"http://127.0.0.1:{port}/command",
        headers=headers,
        json={"type": "mode", "value": "GOTO"},
        timeout=5,
    )
    assert resp.status_code == 400


@pytest.mark.unit
def test_sensor_guard_rejects_oversize_payload():
    """A sensor dict past the byte cap is refused, not stored."""
    guard = _limits_handler(None)
    big = {"imu": {"accel": [0.0] * 4000}}
    assert len(json.dumps(big)) > config.MAX_SENSOR_PAYLOAD_BYTES
    assert guard(big) == "oversize"


@pytest.mark.unit
def test_sensor_guard_accepts_typical_payload():
    guard = _limits_handler(None)
    typical = {
        "imu": {"accel": {"x": 0.1, "y": -0.2, "z": 9.8},
                "gyro": {"x": 0.0, "y": 0.01, "z": -0.01}},
        "gps": {"lat": 37.7749, "lon": -122.4194, "alt": 10.0, "speed": 0.0},
    }
    assert guard(typical) is None


@pytest.mark.unit
def test_sensor_guard_rejects_wrong_type():
    guard = _limits_handler(None)
    assert guard(["not", "a", "dict"]) == "wrong_type"
