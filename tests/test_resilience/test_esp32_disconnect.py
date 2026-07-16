"""Tests for RobotComms disconnect/reconnect and dedupe behavior."""
import threading
import pytest
from unittest.mock import MagicMock, patch
from backend.esp32.robot_comms import RobotComms


def _bare_comms():
    """Create a RobotComms instance without binding a server socket."""
    comms = RobotComms.__new__(RobotComms)
    comms._client = None
    comms._last_cmd = None
    comms._lock = threading.Lock()
    return comms


@pytest.mark.unit
def test_send_deduplicates_same_command():
    """Sending the same command twice only transmits once."""
    mock_sock = MagicMock()
    mock_sock.send.return_value = 1

    comms = _bare_comms()
    comms._client = mock_sock

    with patch("select.select", return_value=([], [mock_sock], [])):
        comms.send("F")
        comms.send("F")  # duplicate

    assert mock_sock.sendall.call_count == 1


@pytest.mark.unit
def test_send_transmits_different_commands():
    """Different successive commands are both transmitted."""
    mock_sock = MagicMock()
    mock_sock.send.return_value = 1

    comms = _bare_comms()
    comms._client = mock_sock

    with patch("select.select", return_value=([], [mock_sock], [])):
        comms.send("F")
        comms.send("S")

    assert mock_sock.sendall.call_count == 2


@pytest.mark.unit
def test_connected_false_when_no_client():
    comms = _bare_comms()
    assert comms.connected is False


@pytest.mark.unit
def test_connected_true_when_client_set():
    comms = _bare_comms()
    comms._client = MagicMock()
    assert comms.connected is True


@pytest.mark.unit
def test_send_returns_false_on_socket_error():
    """send() returns False and clears client on socket error."""
    mock_sock = MagicMock()
    mock_sock.sendall.side_effect = OSError("broken pipe")

    comms = _bare_comms()
    comms._client = mock_sock

    with patch("select.select", return_value=([], [mock_sock], [])):
        result = comms.send("F")

    assert result is False
