"""
Unit tests for utility functions.
"""
import pytest
import numpy as np
import cv2
from utils.cv_text import draw_text, draw_detection_box
from utils.threading import create_daemon_thread, create_timer_thread
import threading
import time


class TestCvTextUtils:
    """Test OpenCV text utility functions."""

    def test_draw_text_basic(self, mock_frame):
        """Test basic text drawing functionality."""
        result = draw_text(mock_frame, "Test", (10, 30))
        assert result is mock_frame  # Should modify in place
        assert result.shape == (480, 640, 3)

    def test_draw_text_custom_params(self, mock_frame):
        """Test text drawing with custom parameters."""
        result = draw_text(
            mock_frame,
            "Custom Text",
            (50, 100),
            font=cv2.FONT_HERSHEY_SIMPLEX,
            size=1.2,
            color=(255, 0, 0),
            thickness=2
        )
        assert result is mock_frame

    def test_draw_detection_box(self, mock_frame):
        """Test detection box drawing."""
        bbox = (100, 100, 200, 200)
        result = draw_detection_box(
            mock_frame,
            bbox,
            "person",
            0.85,
            color=(0, 255, 0)
        )
        assert result is mock_frame


class TestThreadingUtils:
    """Test threading utility functions."""

    def test_create_daemon_thread(self):
        """Test daemon thread creation."""
        def dummy_target():
            time.sleep(0.01)

        thread = create_daemon_thread(dummy_target, "test-thread")

        assert isinstance(thread, threading.Thread)
        assert thread.daemon is True
        assert thread.name == "test-thread"
        assert not thread.is_alive()

        # Test that it can be started
        thread.start()
        assert thread.is_alive()
        thread.join(timeout=1.0)

    def test_create_timer_thread(self):
        """Test timer thread creation."""
        callback_called = threading.Event()

        def timer_callback():
            callback_called.set()

        timer = create_timer_thread(0.01, timer_callback)

        assert isinstance(timer, threading.Timer)
        assert timer.daemon is True

        timer.start()
        assert callback_called.wait(timeout=1.0), "Timer callback should have been called"
        timer.join(timeout=1.0)