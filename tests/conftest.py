"""
Test configuration and fixtures for JARVIS Robot project.
"""
import pytest
import tempfile
import os
import socket
from unittest.mock import Mock, MagicMock
import numpy as np
import cv2


@pytest.fixture
def mock_frame():
    """Create a mock OpenCV frame for testing."""
    return np.zeros((480, 640, 3), dtype=np.uint8)


@pytest.fixture
def mock_robot_comms():
    """Mock RobotComms for testing without hardware."""
    mock = Mock()
    mock.connected = True
    mock.send.return_value = True
    return mock


@pytest.fixture
def mock_robot_state():
    """Mock RobotState for testing."""
    mock = Mock()
    mock.mode = "IDLE"
    mock.last_cmd = "S"
    mock.phone_connected = False
    mock.yolo_info = ""
    mock.last_heard = ""
    mock.jarvis_response = ""
    mock.imu = {}
    mock.gps = {}
    mock.snapshot.return_value = {
        "mode": "IDLE",
        "last_cmd": "S",
        "phone_connected": False,
        "yolo_info": "",
        "last_heard": "",
        "jarvis_response": "",
        "imu": {},
        "gps": {}
    }
    return mock


@pytest.fixture
def temp_audio_file():
    """Create a temporary audio file for testing."""
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        # Create minimal WAV header
        f.write(b'RIFF$$$$WAVEfmt ')
        f.write(b'\x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x80\x3e\x00\x00\x02\x00\x10\x00')
        f.write(b'data')
        f.write(b'\x00\x00\x00\x00')
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def disable_hardware():
    """Disable hardware dependencies for testing."""
    import sys
    from unittest.mock import patch

    # Mock hardware-dependent modules
    mock_modules = {
        'pvporcupine': MagicMock(),
        'sounddevice': MagicMock(),
        'serial': MagicMock(),
    }

    for module_name, mock_module in mock_modules.items():
        sys.modules[module_name] = mock_module

    yield

    # Clean up
    for module_name in mock_modules:
        if module_name in sys.modules:
            del sys.modules[module_name]


@pytest.fixture
def web_server_instance(mock_robot_state, mock_robot_comms):
    """Start the WebServer in a background thread for testing."""
    from web_server import WebServer
    import time
    import requests

    os.environ["JARVIS_SECRET_KEY"] = "test-secret"

    # Pick a free port dynamically to avoid conflicts
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        test_port = s.getsockname()[1]

    server = WebServer(state=mock_robot_state, comms=mock_robot_comms, port=test_port)
    server.start()

    headers = {"Authorization": "Bearer test-secret"}

    # Wait for server to start with retries
    max_retries = 10
    started = False
    for i in range(max_retries):
        try:
            requests.get(f"http://127.0.0.1:{test_port}/status", headers=headers, timeout=0.5)
            started = True
            break
        except requests.exceptions.ConnectionError:
            time.sleep(0.5)

    if not started:
        # Fallback wait if health check fails but server might be up
        time.sleep(2.0)

    yield server
    server.stop()
