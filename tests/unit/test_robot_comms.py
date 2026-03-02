"""
Unit tests for RobotComms functionality.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from backend.esp32.robot_comms import RobotComms


class TestRobotComms:
    """Test RobotComms class functionality."""

    @patch('socket.socket')
    def test_init_creates_socket(self, mock_socket):
        """Test that RobotComms initializes with socket."""
        comms = RobotComms(host="192.168.1.100", port=8888)

        assert comms.host == "192.168.1.100"
        assert comms.port == 8888
        assert not comms.connected

    def test_from_lfr_steering_mapping(self):
        """Test line following steering command mapping."""
        test_cases = [
            ("STRAIGHT", "F"),
            ("LEFT", "L"),
            ("RIGHT", "R"),
            ("LOST", "S"),
            ("UNKNOWN", "S")  # Default case
        ]

        for input_cmd, expected in test_cases:
            result = RobotComms.from_lfr(input_cmd)
            assert result == expected, f"Expected {expected} for {input_cmd}, got {result}"

    def test_from_intent_mapping(self):
        """Test VLA intent command mapping."""
        test_cases = [
            ("FOLLOW", "F"),
            ("SEARCH", "R"),
            ("STOP", "S"),
            ("AVOID", "B"),
            ("UNKNOWN_INTENT", "S")  # Default case
        ]

        for intent, expected in test_cases:
            result = RobotComms.from_intent(intent)
            assert result == expected, f"Expected {expected} for {intent}, got {result}"

    def test_from_human_bbox_center_tracking(self):
        """Test human bbox center calculation for tracking commands."""
        frame_w, frame_h = 640, 480

        # Person in center with small area - should go forward (too far)
        bbox_center = (300, 200, 340, 280)
        # Area = 40*80 = 3200, frame_area = 640*480 = 307200, ratio = ~1% < 15%
        result = RobotComms.from_human_bbox(bbox_center, frame_w, frame_h, rotate_deg=0)
        assert result == "F"

        # Person on left side with significant rotation
        bbox_left = (100, 200, 140, 280)
        result = RobotComms.from_human_bbox(bbox_left, frame_w, frame_h, rotate_deg=-10.0)
        assert result == "L"  # rotate_deg < -5, so turn left

        # Person on right side with significant rotation
        bbox_right = (500, 200, 540, 280)
        result = RobotComms.from_human_bbox(bbox_right, frame_w, frame_h, rotate_deg=10.0)
        assert result == "R"  # rotate_deg > +5, so turn right

    def test_from_human_bbox_distance_control(self):
        """Test human bbox size-based distance control."""
        frame_w, frame_h = 640, 480

        # Very large bbox (close person) - should stop (too close)
        bbox_large = (50, 50, 590, 430)
        # Area = 540*380 = 205,200, frame_area = 307,200, ratio = ~67% > 40%
        result = RobotComms.from_human_bbox(bbox_large, frame_w, frame_h, rotate_deg=0)
        assert result == "S"  # Safety stop when too close

        # Small bbox (distant person) - should move forward
        bbox_small = (310, 230, 330, 250)
        # Area = 20*20 = 400, ratio = ~0.13% < 15%
        result = RobotComms.from_human_bbox(bbox_small, frame_w, frame_h, rotate_deg=0)
        assert result == "F"

    @patch('socket.socket')
    def test_send_command_when_connected(self, mock_socket_class):
        """Test sending commands when socket is connected."""
        mock_socket = MagicMock()
        mock_socket_class.return_value = mock_socket

        comms = RobotComms()
        comms._client = mock_socket  # Simulate connected state

        result = comms.send("F")

        assert result is True
        mock_socket.sendall.assert_called_once_with(b"F")

    def test_send_command_when_disconnected(self):
        """Test sending commands when socket is not connected."""
        comms = RobotComms()
        comms._client = None  # Simulate disconnected state

        result = comms.send("F")

        assert result is False

    def test_close_socket(self):
        """Test socket cleanup on close."""
        with patch('socket.socket') as mock_socket_class:
            mock_client = MagicMock()
            mock_server = MagicMock()

            comms = RobotComms()
            comms._client = mock_client
            comms._server = mock_server

            comms.close()

            # After close, both should be None
            assert comms._client is None
            assert comms._server is None
            assert not comms.connected