"""Tests for CommandQueue drop-oldest behavior and corr_id threading."""
import logging
import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.unit
def test_drops_oldest_when_full():
    """Queue with small maxsize: pushing many items must not block and caps at maxsize."""
    with patch("backend.config.config.CMD_QUEUE_MAX", 3):
        from backend.services.command_queue import CommandQueue
        comms = MagicMock()
        state = MagicMock()
        state.mode = "IDLE"
        cq = CommandQueue(comms=comms, robot_state=state)
        cq._stop_event.set()  # freeze executor so queue fills

        for i in range(10):
            cq.push({"type": "mode", "value": "IDLE"})

        assert cq._q.qsize() <= 3


@pytest.mark.unit
def test_push_all_does_not_hang_on_full_queue():
    """push_all with many actions into a tiny queue must return without blocking."""
    with patch("backend.config.config.CMD_QUEUE_MAX", 2):
        from backend.services.command_queue import CommandQueue
        comms = MagicMock()
        state = MagicMock()
        state.mode = "IDLE"
        cq = CommandQueue(comms=comms, robot_state=state)
        cq._stop_event.set()

        actions = [{"type": "mode", "value": "IDLE"}] * 10
        cq.push_all(actions)
        assert cq._q.qsize() <= 2


@pytest.mark.unit
def test_corr_id_logged_on_push(caplog):
    """push() with corr_id must include it in log output."""
    with patch("backend.config.config.CMD_QUEUE_MAX", 128):
        from backend.services.command_queue import CommandQueue
        comms = MagicMock()
        state = MagicMock()
        state.mode = "IDLE"
        cq = CommandQueue(comms=comms, robot_state=state)
        cq._stop_event.set()

        with caplog.at_level(logging.INFO, logger="backend.services.command_queue"):
            cq.push({"type": "mode", "value": "IDLE"}, corr_id="abc123")

        assert "abc123" in caplog.text
