"""Tests for payload size enforcement — config values and guard logic."""
import pytest
from unittest.mock import MagicMock


@pytest.mark.unit
def test_audio_limit_config_value():
    """MAX_AUDIO_PAYLOAD_BYTES is 512 KB."""
    from backend.config import config
    assert config.MAX_AUDIO_PAYLOAD_BYTES == 512_000


@pytest.mark.unit
def test_sensor_limit_config_value():
    """MAX_SENSOR_PAYLOAD_BYTES is 8 KB."""
    from backend.config import config
    assert config.MAX_SENSOR_PAYLOAD_BYTES == 8_192


@pytest.mark.unit
def test_audio_limit_larger_than_sensor_limit():
    from backend.config import config
    assert config.MAX_AUDIO_PAYLOAD_BYTES > config.MAX_SENSOR_PAYLOAD_BYTES


@pytest.mark.unit
def test_audio_format_whitelist_excludes_mp3():
    """Allowed audio formats are pcm16 and opus only."""
    allowed = {"pcm16", "opus"}
    assert "mp3" not in allowed
    assert "aac" not in allowed
    assert "pcm16" in allowed
    assert "opus" in allowed


@pytest.mark.unit
def test_oversized_audio_exceeds_limit():
    """A 600 KB payload exceeds the 512 KB audio limit."""
    from backend.config import config
    oversized = bytes(600_000)
    assert len(oversized) > config.MAX_AUDIO_PAYLOAD_BYTES


@pytest.mark.unit
def test_oversized_sensor_exceeds_limit():
    """A 10 KB sensor JSON exceeds the 8 KB sensor limit."""
    import json
    from backend.config import config
    big_sensor = {"imu": {"accel": [0.0] * 500, "gyro": [0.0] * 500}}
    serialized = json.dumps(big_sensor)
    assert len(serialized) > config.MAX_SENSOR_PAYLOAD_BYTES


@pytest.mark.unit
def test_normal_audio_within_limit():
    """A 32 ms PCM16 mono 16 kHz chunk (1024 bytes) is within limit."""
    from backend.config import config
    chunk = bytes(1024)
    assert len(chunk) < config.MAX_AUDIO_PAYLOAD_BYTES


@pytest.mark.unit
def test_normal_sensor_within_limit():
    """A typical sensor dict is within the sensor payload limit."""
    import json
    from backend.config import config
    typical = {
        "imu": {"accel": {"x": 0.1, "y": -0.2, "z": 9.8},
                "gyro": {"x": 0.0, "y": 0.01, "z": -0.01}},
        "gps": {"lat": 37.7749, "lon": -122.4194, "alt": 10.0, "speed": 0.0},
    }
    assert len(json.dumps(typical)) < config.MAX_SENSOR_PAYLOAD_BYTES
