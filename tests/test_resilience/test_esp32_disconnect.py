"""Tests for RobotComms disconnect/reconnect and dedupe behavior."""
import threading
import pytest
from unittest.mock import MagicMock, patch
from backend.esp32.robot_comms import RobotComms


def _bare_comms():
    """Create a RobotComms instance without binding a server socket.

    Mirrors every attribute ``RobotComms.__init__`` sets, so error paths that
    touch the reconnect supervision state (``_stop_event``, ``_reconnect_lock``)
    behave exactly as they do on a real instance.
    """
    comms = RobotComms.__new__(RobotComms)
    comms.host = "127.0.0.1"
    comms.port = 9999
    comms._server = None
    comms._client = None
    comms._last_cmd = ""
    comms._last_sent_at = 0.0
    comms._stop_event = threading.Event()
    comms._reconnect_thread = None
    comms._reconnect_attempt = 0
    comms._reconnect_lock = threading.Lock()
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
    """send() returns False, clears client and schedules a reconnect."""
    mock_sock = MagicMock()
    mock_sock.sendall.side_effect = OSError("broken pipe")

    comms = _bare_comms()
    comms._client = mock_sock

    # Stubbed so the failure path does not spawn a real thread that binds a port.
    with patch("select.select", return_value=([], [mock_sock], [])), \
         patch.object(RobotComms, "_schedule_reconnect") as sched:
        result = comms.send("F")

    assert result is False
    assert comms._client is None
    sched.assert_called_once()
