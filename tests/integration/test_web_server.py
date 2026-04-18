"""
Integration tests for the web server functionality.
"""
import pytest
import json
import time
import threading
from unittest.mock import Mock, patch
from web_server import WebServer


class TestWebServerIntegration:
    """Integration tests for WebServer class."""

    @pytest.fixture
    def web_server_setup(self, mock_robot_state, mock_robot_comms):
        """Set up web server for testing."""
        server = WebServer(
            state=mock_robot_state,
            comms=mock_robot_comms,
            host="127.0.0.1",
            port=5001  # Use different port for testing
        )
        return server, mock_robot_state, mock_robot_comms

    def test_web_server_initialization(self, web_server_setup):
        """Test web server initializes correctly."""
        server, state, comms = web_server_setup

        assert server._state is state
        assert server._comms is comms
        assert server._host == "127.0.0.1"
        assert server._port == 5001
        assert server._voice_pipeline is None
        assert server._frame_bytes is None

    def test_voice_pipeline_registration(self, web_server_setup):
        """Test voice pipeline registration."""
        server, state, comms = web_server_setup

        mock_pipeline = Mock()
        mock_tts = Mock()
        mock_pipeline.tts = mock_tts

        server.set_voice_pipeline(mock_pipeline)

        assert server._voice_pipeline is mock_pipeline
        mock_tts.set_wav_callback.assert_called_once()

    def test_frame_pushing_without_clients(self, web_server_setup, mock_frame):
        """Test frame pushing when no clients connected."""
        server, state, comms = web_server_setup

        # Initially no clients
        assert server._has_clients is False

        # Push frame should not encode
        server.push_frame(mock_frame)

        # Frame bytes should remain None
        assert server._frame_bytes is None

    def test_frame_pushing_with_clients(self, web_server_setup, mock_frame):
        """Test frame pushing when clients are connected."""
        server, state, comms = web_server_setup

        # Simulate client connection
        server._has_clients = True

        # Push frame should encode
        server.push_frame(mock_frame)

        # Frame bytes should be set
        assert server._frame_bytes is not None
        assert isinstance(server._frame_bytes, bytes)

    def test_full_snapshot_method(self, web_server_setup):
        """Test full snapshot retrieval."""
        server, state, comms = web_server_setup

        expected_snapshot = {
            "mode": "IDLE",
            "last_cmd": "S",
            "phone_connected": False
        }
        state.snapshot.return_value = expected_snapshot

        snapshot = server._full_snapshot()

        assert snapshot == expected_snapshot
        state.snapshot.assert_called_once()

    @patch('threading.Thread')
    def test_start_method_creates_thread(self, mock_thread_class, web_server_setup):
        """Test that start method creates daemon thread."""
        server, state, comms = web_server_setup

        mock_thread = Mock()
        mock_thread_class.return_value = mock_thread

        server.start()

        mock_thread_class.assert_called_once()
        call_args = mock_thread_class.call_args
        assert call_args[1]['daemon'] is True
        assert call_args[1]['name'] == 'web-server'
        mock_thread.start.assert_called_once()

    def test_tts_audio_relay(self, web_server_setup):
        """Test TTS audio relay to phone."""
        server, state, comms = web_server_setup

        mock_sio = Mock()
        server._sio = mock_sio

        test_audio = b'fake_wav_data'

        server._send_tts_audio(test_audio)

        mock_sio.emit.assert_called_once_with("tts_audio", test_audio)

    def test_tts_audio_relay_no_connection(self, web_server_setup):
        """Test TTS audio relay when no SocketIO connection."""
        server, state, comms = web_server_setup

        # No SocketIO connection
        server._sio = None

        test_audio = b'fake_wav_data'

        # Should not raise exception
        server._send_tts_audio(test_audio)

    def test_update_conversation_compatibility(self, web_server_setup):
        """Test update_conversation method for backward compatibility."""
        server, state, comms = web_server_setup

        # Method should exist and not raise errors
        server.update_conversation("Hello", "Hi there")

        # Should be a no-op for compatibility

    def test_handle_command_payload_mode(self, web_server_setup):
        """Test shared command handler for mode updates."""
        server, state, comms = web_server_setup

        payload = {"type": "mode", "value": "VLA"}
        body, status = server._handle_command_payload(payload)

        assert status == 200
        assert body["status"] == "ok"
        assert body["mode"] == "VLA"
        assert state.mode == "VLA"

    def test_handle_command_payload_move(self, web_server_setup):
        """Test shared command handler for movement commands."""
        server, state, comms = web_server_setup

        payload = {"type": "move", "cmd": "F", "duration": 0.2}
        body, status = server._handle_command_payload(payload)

        assert status == 200
        assert body["status"] == "ok"
        assert body["cmd"] == "F"
        comms.send.assert_called_with("F")

    def test_handle_command_payload_invalid(self, web_server_setup):
        """Test shared command handler rejects unsupported payload."""
        server, state, comms = web_server_setup

        body, status = server._handle_command_payload({"type": "unknown"})

        assert status == 400
        assert body["status"] == "error"
