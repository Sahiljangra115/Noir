"""
OpenCV text rendering utilities to reduce duplication.
"""
import cv2
import numpy as np
from typing import Tuple


def draw_text(
    frame: np.ndarray,
    text: str,
    pos: Tuple[int, int],
    font: int = cv2.FONT_HERSHEY_DUPLEX,
    size: float = 0.7,
    color: Tuple[int, int, int] = (255, 255, 255),
    thickness: int = 1
) -> np.ndarray:
    """Draw text on frame with consistent styling."""
    return cv2.putText(frame, text, pos, font, size, color, thickness, cv2.LINE_AA)


def draw_status_text(
    frame: np.ndarray,
    text: str,
    line: int,
    x_offset: int = 10,
    line_height: int = 32
) -> np.ndarray:
    """Draw status text at a specific line number from top."""
    y_pos = line * line_height
    return draw_text(frame, text, (x_offset, y_pos))


def draw_detection_box(
    frame: np.ndarray,
    bbox: Tuple[int, int, int, int],
    label: str,
    confidence: float,
    color: Tuple[int, int, int] = (0, 200, 0)
) -> np.ndarray:
    """Draw detection bounding box with label."""
    x1, y1, x2, y2 = bbox
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    label_text = f"{label} {confidence:.0%}"
    draw_text(frame, label_text, (x1, max(y1 - 8, 20)), size=0.65, color=color)

    return frame