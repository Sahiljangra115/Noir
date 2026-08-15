"""Tests for the OpenCV line scanner that backs HybridLineFollower.

This is the fallback path that runs whenever the MobileNetV2 weights are
absent, which is every machine that does not have the .pth file. It used to be
commented out entirely while three docs claimed a "hybrid ML + OpenCV" follower,
so LFR mode silently reported LOST forever.
"""
import numpy as np
import pytest

from tracker import LineFollower, HybridLineFollower


def _frame_with_line(width=640, height=480, line_x=320, line_w=40):
    """Light floor with one dark vertical stripe, i.e. a line to follow."""
    frame = np.full((height, width, 3), 220, dtype=np.uint8)
    half = line_w // 2
    frame[:, max(line_x - half, 0):line_x + half] = 20
    return frame


@pytest.mark.unit
def test_centred_line_reads_straight():
    lr = LineFollower().scan(_frame_with_line(line_x=320))
    assert lr.detected
    assert lr.steer == "STRAIGHT"
    assert abs(lr.error_frac) < 0.1


@pytest.mark.unit
def test_line_left_of_centre_steers_left():
    lr = LineFollower().scan(_frame_with_line(line_x=160))
    assert lr.detected
    assert lr.steer == "LEFT"
    assert lr.error_frac < 0


@pytest.mark.unit
def test_line_right_of_centre_steers_right():
    lr = LineFollower().scan(_frame_with_line(line_x=480))
    assert lr.detected
    assert lr.steer == "RIGHT"
    assert lr.error_frac > 0


@pytest.mark.unit
def test_blank_frame_reports_lost():
    blank = np.full((480, 640, 3), 220, dtype=np.uint8)
    lr = LineFollower().scan(blank)
    assert not lr.detected
    assert lr.steer == "LOST"


@pytest.mark.unit
def test_fallback_result_is_not_labelled_ml():
    """A CV-scanner result must not claim to be a model prediction.

    The HUD prints "AI ACTIVE" plus a confidence bar whenever is_ml is set. It
    used to be hardcoded True even with no weights loaded, so the overlay
    advertised a model confidence that no model had produced.
    """
    lr = LineFollower().scan(_frame_with_line())
    assert lr.is_ml is False
    assert lr.confidence == 0.0


@pytest.mark.unit
def test_hybrid_falls_back_when_model_absent():
    follower = HybridLineFollower()
    follower.use_model = False
    follower._line_model = None

    lr = follower.scan(_frame_with_line(line_x=320))
    # Real steering from the CV path, not the old permanent "LOST".
    assert lr.detected
    assert lr.steer == "STRAIGHT"
    assert lr.is_ml is False
