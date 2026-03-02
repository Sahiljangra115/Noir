"""
scrcpy → OpenCV Tracker
──────────────────────
Reads the video stream from scrcpy (phone camera mirror),
detects humans (YOLOv8n) or small objects (contour-based),
and continuously prints movement commands (distance + rotation angle).

Requirements:
    pip install opencv-python-headless ultralytics numpy

Run scrcpy FIRST:
    scrcpy --video-source=camera --camera-facing=back --no-audio --window-title="scrcpy"

Then run this script:
    python tracker.py

Optional flags:
    python tracker.py --mode human        # detect humans only
    python tracker.py --mode object       # detect small objects only
    python tracker.py --mode both         # detect humans + objects
    python tracker.py --mode line         # line-following only (LFR)
    python tracker.py --mode all          # line-following + human + object
    python tracker.py --source file --path /tmp/scrcpy.mp4  # file input

Key bindings while running:
    q  - quit
    p  - pause / resume
    d  - toggle debug overlay
    l  - toggle line-following overlay (in line/all mode)
"""

import cv2
# For ML preview window
from pygame_preview import pygame_bgr_preview

import numpy as np
import argparse
import math
import time
import sys
from dataclasses import dataclass
from typing import Optional, Tuple, List
from collections import deque

# === ML model imports (PyTorch MobilenetV2 fine-tuned classifier) ===
import torch
import torch.nn as nn
from torchvision import models, transforms

ML_MODEL_AVAILABLE = True

# ─────────────────────────── config ───────────────────────────────────────────

# Model loader (MobilenetV2 fine-tuned classifier)
def load_line_model():
    import os
    if not os.path.exists(MODEL_PATH):
        print(f"❌ LineFollow model not found at: {MODEL_PATH}")
        return None, None
    model = models.mobilenet_v2(weights=None)
    model.classifier = nn.Sequential(
        nn.Dropout(p=0.3),
        nn.Linear(model.last_channel, len(CLASS_NAMES))
    )
    ckpt = torch.load(MODEL_PATH, map_location=DEVICE)
    model.load_state_dict(ckpt['model_state'])
    model.eval().to(DEVICE)
    print(f"✅ Line model loaded | Val acc: {ckpt.get('val_acc', 'N/A')}")
    print(f"✅ Running on: {DEVICE}")
    return model, ckpt.get('val_acc', None)


# MobilenetV2 model for line following
MODEL_PATH = '/home/ladliju/Developer/Model_finetune/line_classifier.pth'
IMG_SIZE = 224
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
CLASS_NAMES = ['Move Left', 'Move Right', 'No Line', 'Straight', 'Turn Left', 'Turn Right']
MODEL_TRANSFORM = transforms.Compose([
    transforms.ToPILImage(),
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])

# Camera / geometry constants (tune these to your actual setup)
# Typical phone main camera HFOV: 65–80°. Adjust to your phone for best accuracy.
HFOV_DEG        = 69.0          # Horizontal field-of-view of phone camera (degrees)
FOCAL_LENGTH_PX = None          # Computed from HFOV at runtime
KNOWN_HUMAN_HEIGHT_M  = 1.70    # Average human height for distance estimate
KNOWN_BOX_HEIGHT_M    = 0.10    # ~10 cm box height (tune per your box)

# Detection thresholds
YOLO_CONF       = 0.45          # Confidence threshold for YOLO
YOLO_IOU        = 0.45          # IOU threshold for NMS
BOX_YOLO_CONF   = 0.30          # Lower confidence for box (harder to detect)
BOX_ASPECT_MIN  = 0.50          # Min w/h ratio (reject very tall/thin)
BOX_ASPECT_MAX  = 2.00          # Max w/h ratio (reject very wide/flat)
BOX_MIN_AREA_PX = 400           # Ignore tiny detections (noise)

# COCO class IDs that look like boxes / boxy objects
# 24=backpack  25=umbrella  26=handbag  28=suitcase  39=bottle
# 56=chair  63=laptop  66=keyboard  73=book  76=scissors
BOX_COCO_CLASSES = [24, 26, 28, 73]  # tune: add/remove IDs for your box

# Command dead-zones (commands only issued if beyond these thresholds)
ANGLE_DEAD_ZONE_DEG  = 3.0      # degrees – ignore tiny jitter
DIST_DEAD_ZONE_M     = 0.03     # metres – ignore tiny distance changes

# Per-kind stop distances (how close the bot should get)
STOP_DISTANCE_HUMAN_M  = 1.0    # stay 1 m from a person
STOP_DISTANCE_OBJECT_M = 0.10   # stay ~10 cm from the box

# Smoothing (exponential moving average alpha)
SMOOTH_ALPHA = 0.25
# ── Line-follower (LFR) config ─────────────────────────────────────────────────
#    Tuned for: 2–3 cm dark-gray / black tape on white cloth surface
LINE_SCAN_TOP_FRAC    = 0.35    # start scanning from 35% down
LINE_SCAN_BOT_FRAC    = 0.97    # scan almost to the bottom
LINE_MIN_WIDTH_PX     = 4       # catches thin line at far distance
LINE_MAX_WIDTH_FRAC   = 0.85    # allow wide contours (line in horizontal turns)
LINE_STEER_DEAD_ZONE  = 0.05    # fraction of half-width – centre dead-zone
LINE_NUM_SCAN_ROWS    = 7       # horizontal slices to sample
LINE_SPEED_DEFAULT    = "CRUISE" # label when going straight

# Smoothing and threshold constants
LINE_STRAIGHT_THRESH  = 0.05    # threshold for considering line "straight"
LINE_SMOOTH          = 0.3     # smoothing factor for error

# CLAHE contrast enhancement (boosts dark-gray vs white before thresholding)
LINE_CLAHE_CLIP       = 4.0     # contrast limit (higher = more aggressive)
LINE_CLAHE_GRID       = (8, 8)  # tile grid size

# Adaptive threshold: block must be odd & > 1
# Block MUST be much larger than the tape width in pixels, otherwise the
# centre of the tape matches its own local mean and gets missed.
LINE_ADAPTIVE_BLOCK   = 201     # very large – always includes white around tape
LINE_ADAPTIVE_C       = 15      # how much darker than local mean = "line"
# ─────────────────────────── data structures ──────────────────────────────────

@dataclass
class Detection:
    label: str
    bbox: Tuple[int, int, int, int]   # x1 y1 x2 y2
    confidence: float
    kind: str                          # "human" | "object"

@dataclass
class Command:
    rotate_deg: float     # + = turn right, – = turn left
    move_m: float         # + = move forward, – = move backward
    description: str

@dataclass
class LineResult:
    """Result from the line-follower."""
    detected: bool
    error_frac: float         # –1.0 (line far left) … 0 (centred) … +1.0 (far right)
    steer: str                # "LEFT", "RIGHT", "STRAIGHT", "LOST"
    description: str
    centroids: List[Tuple[int, int]]   # (x, y) of line centre per scan row


# ─────────────────────────── geometry helpers ─────────────────────────────────

# Cache for expensive computations to avoid recalculation
_FOCAL_CACHE = {}
_DISTANCE_CACHE = {}

def compute_focal(frame_w: int, hfov_deg: float) -> float:
    """
    Compute focal length with caching for performance.
    """
    cache_key = (frame_w, hfov_deg)
    if cache_key in _FOCAL_CACHE:
        return _FOCAL_CACHE[cache_key]

    focal = (frame_w / 2.0) / math.tan(math.radians(hfov_deg / 2.0))
    _FOCAL_CACHE[cache_key] = focal
    return focal


def pixel_offset_to_angle(pixel_offset: float, focal_px: float) -> float:
    """Convert horizontal pixel offset from centre → angle in degrees."""
    return math.degrees(math.atan2(pixel_offset, focal_px))


def estimate_distance(
    bbox_height_px: int,
    focal_px: float,
    known_height_m: float,
) -> float:
    """
    Pinhole camera distance estimate:
        D = (known_height_m * focal_px) / bbox_height_px
    focal_px is the single pixel-focal-length (same horizontally & vertically
    for square pixels), already orientation-corrected in run().
    """
    if bbox_height_px < 5:
        return 9999.0
    distance = (known_height_m * focal_px) / bbox_height_px
    return round(distance, 2)


def build_command(
    cx: int, cy: int,
    frame_w: int, frame_h: int,
    focal_px: float,
    distance_m: float,
    kind: str,
) -> Command:
    """
    Given detection centre pixel (cx, cy) and estimated distance,
    build a human-readable movement command.
    """
    # Horizontal offset from image centre → rotation needed
    offset_x   = cx - frame_w // 2
    rotate_deg = pixel_offset_to_angle(offset_x, focal_px)

    # Pick the correct stop distance for this target kind
    stop_d = STOP_DISTANCE_HUMAN_M if kind == "human" else STOP_DISTANCE_OBJECT_M
    move_m = distance_m - stop_d

    # Build English command
    parts = []

    if abs(rotate_deg) > ANGLE_DEAD_ZONE_DEG:
        direction = "RIGHT" if rotate_deg > 0 else "LEFT"
        parts.append(f"ROTATE {direction} {abs(rotate_deg):.1f}°")

    if abs(move_m) > DIST_DEAD_ZONE_M:
        direction = "FORWARD" if move_m > 0 else "BACKWARD"
        parts.append(f"MOVE {direction} {abs(move_m):.2f} m")

    if not parts:
        description = f"✓ ON TARGET – hold position ({stop_d*100:.0f} cm)"
    else:
        description = "  |  ".join(parts)

    return Command(
        rotate_deg=rotate_deg,
        move_m=move_m,
        description=description,
    )


# ─────────────────────────── detectors ───────────────────────────────────────

class HumanDetector:
    """Wraps YOLOv8n for person detection with caching for performance."""

    def __init__(self):
        try:
            from ultralytics import YOLO
            self.model = YOLO("yolov8n.pt")  # downloads ~6 MB on first run

            # Model optimization settings
            self.model.overrides['verbose'] = False
            # Optimize model for inference (disable training features)
            if hasattr(self.model.model, 'eval'):
                self.model.model.eval()

            self.enabled = True
            print("[INFO] YOLOv8n loaded for human detection.")
        except ImportError:
            print("[WARN] ultralytics not installed. Human detection disabled.")
            print("       pip install ultralytics")
            self.enabled = False

        # Performance optimization: frame caching
        self._last_frame_hash = None
        self._last_detections = []
        self._frame_skip_count = 0
        self._max_skip_frames = 2  # Process every 3rd frame max for smoothness

        # Batch processing for efficiency
        self._batch_frames = []
        self._batch_size = 1  # Start with 1, could be increased for multiple cameras

    def _compute_frame_hash(self, frame: np.ndarray) -> int:
        """Compute a fast hash of frame content for change detection."""
        # Use a subset of pixels for fast comparison - optimized sampling
        h, w = frame.shape[:2]
        # Use stride sampling for better performance
        sample = frame[::max(h//16, 4), ::max(w//16, 4), 0]  # Green channel only
        return hash(sample.tobytes())

    def detect(self, frame: np.ndarray) -> List[Detection]:
        if not self.enabled:
            return []

        # Input validation
        if frame is None or frame.size == 0:
            return []

        if not isinstance(frame, np.ndarray) or len(frame.shape) != 3:
            return []

        try:
            # Performance optimization: skip similar frames
            current_hash = self._compute_frame_hash(frame)
            if (current_hash == self._last_frame_hash and
                self._frame_skip_count < self._max_skip_frames):
                self._frame_skip_count += 1
                return self._last_detections  # Return cached result

            # Reset skip counter and update hash
            self._frame_skip_count = 0
            self._last_frame_hash = current_hash

            # Run YOLO inference with error handling
            results = self.model(
                frame,
                conf=YOLO_CONF,
                iou=YOLO_IOU,
                classes=[0],        # class 0 = person in COCO
                verbose=False,
            )[0]

            detections = []
            if results.boxes is not None:
                for box in results.boxes:
                    try:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        conf = float(box.conf[0])

                        # Validate detection bounds
                        h, w = frame.shape[:2]
                        if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
                            continue

                        detections.append(Detection(
                            label="person",
                            bbox=(x1, y1, x2, y2),
                            confidence=conf,
                            kind="human",
                        ))
                    except (IndexError, TypeError, ValueError):
                        # Skip invalid detections gracefully
                        continue

            # Cache results for potential reuse
            self._last_detections = detections
            return detections

        except Exception:
            # Return empty list on any error - graceful degradation
            return []


class BoxDetector:
    """
    Detects box-like objects using YOLOv8n on a curated set of COCO classes
    (suitcase, handbag, backpack, book, etc.) that resemble boxy shapes,
    then filters by aspect ratio to keep only roughly-square detections.

    This reuses the same YOLO model the HumanDetector already loads
    (passed via share_model()), so there is zero extra model loading cost.

    If YOLO isn't enough for your specific box, you can also add a
    colour-range fallback — see the _colour_fallback() method.
    """

    def __init__(self):
        self.model   = None
        self.enabled = False

    def share_model(self, model) -> None:
        """Reuse the YOLO model already loaded by HumanDetector."""
        self.model   = model
        self.enabled = True
        class_names  = [model.names[c] for c in BOX_COCO_CLASSES if c in model.names]
        print(f"[INFO] BoxDetector ready – YOLO classes: {class_names}")

    def detect(self, frame: np.ndarray) -> List[Detection]:
        detections: List[Detection] = []

        # ── YOLO-based detection ──────────────────────────────────────────
        if not self.enabled or self.model is None:
            return detections

        results = self.model(
            frame,
            conf=BOX_YOLO_CONF,
            iou=YOLO_IOU,
            classes=BOX_COCO_CLASSES,
            verbose=False,
        )[0]

        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            w, h = x2 - x1, y2 - y1

            # Pixel-area gate
            if w * h < BOX_MIN_AREA_PX:
                continue

            # Aspect-ratio gate: your box is ~square
            ratio = w / max(h, 1)
            if not (BOX_ASPECT_MIN <= ratio <= BOX_ASPECT_MAX):
                continue

            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            cls_name = self.model.names.get(cls_id, "object")

            detections.append(Detection(
                label=f"box ({cls_name})",
                bbox=(x1, y1, x2, y2),
                confidence=conf,
                kind="object",
            ))

        # ── Colour-range fallback (optional) ──────────────────────────────
        # Uncomment & tune if YOLO alone doesn't catch your box.
        # This looks for a specific HSV colour range.
        # detections += self._colour_fallback(frame)

        # Keep best detection only
        detections.sort(key=lambda d: d.confidence, reverse=True)
        return detections[:1]

    # noinspection PyUnusedLocal
    @staticmethod
    def _colour_fallback(frame: np.ndarray) -> List[Detection]:
        """
        Optional fallback: detect a box by its colour if YOLO misses it.
        Tune the HSV range for YOUR box's colour.
        """
        hsv   = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        # Example: brown cardboard box
        lower = np.array([8,   40,  60])
        upper = np.array([25, 200, 220])
        mask  = cv2.inRange(hsv, lower, upper)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask   = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        dets: List[Detection] = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < BOX_MIN_AREA_PX:
                continue
            x, y, w, h = cv2.boundingRect(c)
            ratio = w / max(h, 1)
            if not (BOX_ASPECT_MIN <= ratio <= BOX_ASPECT_MAX):
                continue
            solidity = area / max(w * h, 1)
            if solidity < 0.6:
                continue
            dets.append(Detection(
                label="box (colour)",
                bbox=(x, y, x + w, y + h),
                confidence=round(solidity * 0.7, 2),  # lower than YOLO
                kind="object",
            ))
        dets.sort(key=lambda d: d.confidence, reverse=True)
        return dets[:1]

# ─────────────────────────── line follower ───────────────────────────────────────

# ----- OpenCV LineFollower (legacy, used as fallback) -----
class LineFollower:
    # Legacy OpenCV-based line tracker, used as fallback by HybridLineFollower
    def __init__(self):
        pass
    def scan(self, frame: np.ndarray):
        # Minimal stub fallback implementation, replace with your OpenCV logic
        # Or keep as a placeholder to allow import/run
        return LineResult(
            detected=False,
            error_frac=0.0,
            steer="LOST",
            description="LineFollower fallback not implemented",
            centroids=[]
        )

class HybridLineFollower:
    """
    Tries to use the HuggingFace MobileNetV2 model for line following.
    Falls back to OpenCV logic if model is missing or inference fails.
    """
    def __init__(self):
        self.model, self.val_acc = load_line_model()
        self.use_model = self.model is not None
        self.fallback = LineFollower()
        self.last_error = None

    def scan(self, frame: np.ndarray):
        if self.use_model and self.model is not None:
            try:
                tensor = MODEL_TRANSFORM(frame).unsqueeze(0).to(DEVICE)
                with torch.no_grad():
                    probs = torch.softmax(self.model(tensor), dim=1)
                    conf, pred = probs.max(dim=1)
                label = CLASS_NAMES[pred.item()]
                steer = self.map_label_to_steer(label)
                desc = f"ML: {label}" if label else "ML prediction failed"
                detected = label not in (None, 'No Line')
                return LineResult(
                    detected=detected,
                    error_frac=0.0,  # No “offset” output for classifier
                    steer=steer,
                    description=desc,
                    centroids=[]
                )
            except Exception as exc:
                print(f"[WARN] ML inference failed: {exc}. Fallback to OpenCV for rest of this session.")
                self.use_model = False
                self.last_error = str(exc)
        # Fallback
        return self.fallback.scan(frame)

    @staticmethod
    def map_label_to_steer(label):
        if label is None:
            return "LOST"
        label = label.lower()
        if "left" in label:
            return "LEFT"
        elif "right" in label:
            return "RIGHT"
        elif "straight" in label:
            return "STRAIGHT"
        elif "no line" in label:
            return "LOST"
        else:
            return label.upper()

    """
    Camera-based line follower (LFR).

    Scans the bottom portion of the frame for a black line on a lighter
    ground surface.  Outputs a normalised steering error and a human-
    readable steer command.

    Algorithm:
      1. Crop to the ground region (LINE_SCAN_TOP_FRAC → LINE_SCAN_BOT_FRAC)
      2. Convert to grayscale → binary threshold (black line = white in mask)
      3. Slice the ROI into LINE_NUM_SCAN_ROWS horizontal bands
      4. In each band, find the largest dark contour → its centroid
      5. Average the centroid x-positions → line’s position
      6. Compute error = (line_x – frame_centre_x) / half_width
      7. Output steer command (LEFT / STRAIGHT / RIGHT / LOST)
    """

    def __init__(self):
        self._prev_error: float = 0.0   # for smoothing
        self._debug_mask: Optional[np.ndarray] = None
        self._debug_y_top: int = 0

        # Performance optimization: pre-allocate arrays
        self._gray_cache: Optional[np.ndarray] = None
        self._mask_cache: Optional[np.ndarray] = None
        self._clahe = cv2.createCLAHE(
            clipLimit=LINE_CLAHE_CLIP,
            tileGridSize=LINE_CLAHE_GRID,
        )

        print("[INFO] LineFollower ready – scanning for black line")

    def scan(self, frame: np.ndarray) -> LineResult:
        # Input validation
        if frame is None or frame.size == 0:
            return LineResult(
                detected=False,
                error_frac=0.0,
                steer="LOST",
                description="Invalid frame",
                centroids=[]
            )

        if not isinstance(frame, np.ndarray) or len(frame.shape) != 3:
            return LineResult(
                detected=False,
                error_frac=0.0,
                steer="LOST",
                description="Invalid frame format",
                centroids=[]
            )

        try:
            fh, fw = frame.shape[:2]
            if fh < 10 or fw < 10:  # Minimum size check
                return LineResult(
                    detected=False,
                    error_frac=0.0,
                    steer="LOST",
                    description="Frame too small",
                    centroids=[]
                )

            y_top = int(fh * LINE_SCAN_TOP_FRAC)
            y_bot = int(fh * LINE_SCAN_BOT_FRAC)

            # Ensure valid ROI bounds
            y_top = max(0, min(y_top, fh - 1))
            y_bot = max(y_top + 1, min(y_bot, fh))

            roi = frame[y_top:y_bot, :]
            rh, rw = roi.shape[:2]

            if rh < 5 or rw < 5:  # ROI too small
                return LineResult(
                    detected=False,
                    error_frac=0.0,
                    steer="LOST",
                    description="ROI too small",
                    centroids=[]
                )

            # ── 1. Grayscale (reuse cache if possible) ────────────────────────────
            if (self._gray_cache is None or
                self._gray_cache.shape[:2] != (rh, rw)):
                self._gray_cache = np.empty((rh, rw), dtype=np.uint8)

            cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY, dst=self._gray_cache)

            # ── 2. CLAHE contrast enhancement ─────────────────────────────────────
            #    Boosts the contrast of dark-gray tape against the white cloth
            #    even under uneven / washed-out phone-camera lighting.
            self._gray_cache = self._clahe.apply(self._gray_cache)
            cv2.GaussianBlur(self._gray_cache, (3, 3), 0, dst=self._gray_cache)

            # ── 3. Adaptive threshold (reuse mask cache) ──────────────────────────
            #    Dark gray tape → white in mask.  Adaptive handles the
            #    brightness difference between white cloth and gray floor.
            if (self._mask_cache is None or
                self._mask_cache.shape[:2] != (rh, rw)):
                self._mask_cache = np.empty((rh, rw), dtype=np.uint8)

            cv2.adaptiveThreshold(
                self._gray_cache, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV,
                LINE_ADAPTIVE_BLOCK,
                LINE_ADAPTIVE_C,
                dst=self._mask_cache
            )

            # ── 4. Gentle morphological cleanup ───────────────────────────────────
            #    Only CLOSE (fill small gaps in the line).  NO OPEN – it
            #    erodes thin lines and kills detection.
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            cv2.morphologyEx(self._mask_cache, cv2.MORPH_CLOSE, kernel,
                            iterations=1, dst=self._mask_cache)

            # Store for debug display (defensive copy)
            try:
                self._debug_mask = self._mask_cache.copy()
                self._debug_y_top = y_top
            except Exception:
                # Non-critical operation - continue if it fails
                pass

            # ── 5. Multi-row scan ─────────────────────────────────────────────
            band_h = max(rh // LINE_NUM_SCAN_ROWS, 1)
            centroids: List[Tuple[int, int]] = []

            for i in range(LINE_NUM_SCAN_ROWS):
                try:
                    by = i * band_h
                    by_end = min(by + band_h, rh)  # Ensure we don't exceed bounds
                    band = self._mask_cache[by:by_end, :]

                    if band.size == 0:  # Skip empty bands
                        continue

                    contours, _ = cv2.findContours(
                        band, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                    best_cx: Optional[int] = None
                    best_area = 0
                    for c in contours:
                        try:
                            area = cv2.contourArea(c)
                            x, y, w, h = cv2.boundingRect(c)

                            # Min-width gate (noise filter)
                            if w < LINE_MIN_WIDTH_PX:
                                continue
                            # Max-width: skip contours that span nearly the whole frame
                            # (e.g. the sheet/floor boundary)
                            if w > rw * LINE_MAX_WIDTH_FRAC:
                                continue
                            if area > best_area:
                                best_area = area
                                # Use the centroid from image moments for accuracy
                                M = cv2.moments(c)
                                if M["m00"] > 0:
                                    best_cx = int(M["m10"] / M["m00"])
                                else:
                                    best_cx = x + w // 2
                        except Exception:
                            # Skip this contour if processing fails
                            continue

                    if best_cx is not None:
                        centroids.append((best_cx, by + band_h // 2))

                except Exception:
                    # Skip this band if processing fails
                    continue

            # ── 6. Average and normalise error ────────────────────────────────
            if not centroids:
                # No line detected → LOST
                return LineResult(
                    detected=False,
                    error_frac=0.0,
                    steer="LOST",
                    description="No line detected",
                    centroids=[]
                )
            else:
                try:
                    avg_x = sum(cx for cx, _ in centroids) / len(centroids)
                    centre_x = rw / 2
                    error = (avg_x - centre_x) / (rw / 2)  # normalised [-1, +1]

                    # Clamp error to reasonable bounds
                    error = max(-1.0, min(1.0, error))

                    # ── 7. Classify steering ──────────────────────────────────────
                    if abs(error) < LINE_STEER_DEAD_ZONE:
                        steer = "STRAIGHT"
                        desc = f"STRAIGHT (err={error:.2f})"
                    elif error > 0:
                        steer = "RIGHT"
                        desc = f"RIGHT (err={error:.2f})"
                    else:
                        steer = "LEFT"
                        desc = f"LEFT (err={error:.2f})"

                    return LineResult(
                        detected=True,
                        error_frac=error,
                        steer=steer,
                        description=desc,
                        centroids=centroids
                    )

                except (ZeroDivisionError, ArithmeticError):
                    return LineResult(
                        detected=False,
                        error_frac=0.0,
                        steer="LOST",
                        description="Calculation error",
                        centroids=[]
                    )

        except Exception as exc:
            # Log error but return safe default to prevent crash
            print(f"[ERROR] LineFollower scan failed: {exc}")
            return LineResult(
                detected=False,
                error_frac=0.0,
                steer="LOST",
                description=f"Error: {exc}",
                centroids=[]
            )
            contours, _ = cv2.findContours(
                band, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            best_cx: Optional[int] = None
            best_area = 0
            for c in contours:
                area = cv2.contourArea(c)
                x, y, w, h = cv2.boundingRect(c)
                # Min-width gate (noise filter)
                if w < LINE_MIN_WIDTH_PX:
                    continue
                # Max-width: skip contours that span nearly the whole frame
                # (e.g. the sheet/floor boundary)
                if w > rw * LINE_MAX_WIDTH_FRAC:
                    continue
                if area > best_area:
                    best_area = area
                    # Use the centroid from image moments for accuracy
                    M = cv2.moments(c)
                    if M["m00"] > 0:
                        best_cx = int(M["m10"] / M["m00"])
                    else:
                        best_cx = x + w // 2

            if best_cx is not None:
                centroids.append((best_cx, y_top + by + band_h // 2))

        if not centroids:
            result = LineResult(
                detected=False, error_frac=0.0,
                steer="LOST", description="⚠ LINE LOST – searching…",
                centroids=[],
            )
            self._prev_error = 0.0
            return result

        # Average x of all detected centroids
        avg_x     = sum(c[0] for c in centroids) / len(centroids)
        half_w    = fw / 2.0
        raw_error = (avg_x - half_w) / half_w          # –1 .. +1

        # Smooth with previous frame
        error = 0.6 * raw_error + 0.4 * self._prev_error
        self._prev_error = error

        # Steer command
        if abs(error) < LINE_STEER_DEAD_ZONE:
            steer = "STRAIGHT"
            desc  = f"── {LINE_SPEED_DEFAULT} ── line centred"
        elif error < 0:
            steer = "LEFT"
            desc  = f"◀ STEER LEFT  {abs(error)*100:.0f}%"
        else:
            steer = "RIGHT"
            desc  = f"STEER RIGHT ▶ {abs(error)*100:.0f}%"

        return LineResult(
            detected=True,
            error_frac=round(error, 3),
            steer=steer,
            description=desc,
            centroids=centroids,
        )


def draw_line_overlay(
    frame: np.ndarray,
    lr: LineResult,
    debug: bool,
) -> np.ndarray:
    """Draw line-following visualisation on the frame."""
    fh, fw = frame.shape[:2]
    y_top = int(fh * LINE_SCAN_TOP_FRAC)
    y_bot = int(fh * LINE_SCAN_BOT_FRAC)

    # Dim the area outside the scan region
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (fw, y_top), (0, 0, 0), -1)
    cv2.rectangle(overlay, (0, y_bot), (fw, fh), (0, 0, 0), -1)
    frame = cv2.addWeighted(frame, 0.7, overlay, 0.3, 0)

    # Scan-region border
    cv2.line(frame, (0, y_top), (fw, y_top), (80, 80, 80), 1)
    cv2.line(frame, (0, y_bot), (fw, y_bot), (80, 80, 80), 1)

    # Centre guide line
    mid_x = fw // 2
    cv2.line(frame, (mid_x, y_top), (mid_x, y_bot), (100, 100, 100), 1)

    if lr.detected and lr.centroids:
        # Draw detected centroids and connect them
        colour = (0, 255, 0) if lr.steer == "STRAIGHT" else (0, 200, 255)
        for j, (cx, cy) in enumerate(lr.centroids):
            cv2.circle(frame, (cx, cy), 6, colour, -1)
            if j > 0:
                cv2.line(frame, lr.centroids[j - 1], (cx, cy), colour, 2)

        # Arrow from frame centre-bottom toward average line position
        avg_x = int(sum(c[0] for c in lr.centroids) / len(lr.centroids))
        avg_y = int(sum(c[1] for c in lr.centroids) / len(lr.centroids))
        bot_mid = (mid_x, y_bot)
        cv2.arrowedLine(frame, bot_mid, (avg_x, avg_y), colour, 2, tipLength=0.15)

    # Steer banner
    banner_h = 48
    banner   = np.zeros((banner_h, fw, 3), dtype=np.uint8)
    cv2.putText(banner, f"LFR: {lr.description}", (12, 32),
                cv2.FONT_HERSHEY_DUPLEX, 0.65, (255, 255, 255), 1, cv2.LINE_AA)
    frame[-banner_h:] = cv2.addWeighted(
        frame[-banner_h:], 0.35, banner, 0.65, 0)

    if debug:
        dbg = [
            f"error: {lr.error_frac:+.3f}",
            f"steer: {lr.steer}",
            f"pts:   {len(lr.centroids)}",
        ]
        for i, line in enumerate(dbg):
            cv2.putText(frame, line, (8, 18 + i * 18),
                        cv2.FONT_HERSHEY_PLAIN, 1.1, (0, 255, 255), 1)

    return frame


def show_line_debug_mask(line_det: 'LineFollower') -> None:
    """Show the binary mask in a separate window for tuning."""
    if line_det._debug_mask is not None:
        cv2.imshow("LFR Mask (press 'd' to hide)", line_det._debug_mask)

# ─────────────────────────── smoothing ───────────────────────────────────────

class EMATracker:
    """
    Exponential Moving Average to smooth bounding-box jitter.
    Optimized with vectorized operations for better performance.
    """

    def __init__(self, alpha: float = SMOOTH_ALPHA):
        self.alpha = alpha
        self.prev = None

        # Memory optimization: pre-allocate arrays for calculations
        self._bbox_array = np.zeros(4, dtype=np.float32)
        self._prev_array = np.zeros(4, dtype=np.float32)
        self._result_array = np.zeros(4, dtype=np.int32)

    def update(self, bbox: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        if self.prev is None:
            self.prev = bbox
            return bbox

        # Vectorized smoothing - much faster than element-wise operations
        self._bbox_array[:] = bbox
        self._prev_array[:] = self.prev

        # Vectorized EMA calculation
        np.multiply(self._bbox_array, self.alpha, out=self._bbox_array)
        np.multiply(self._prev_array, 1 - self.alpha, out=self._prev_array)
        np.add(self._bbox_array, self._prev_array, out=self._bbox_array)

        # Convert to integers efficiently
        self._result_array[:] = self._bbox_array.astype(np.int32)
        smoothed = tuple(self._result_array)

        self.prev = smoothed
        return smoothed  # type: ignore


# ─────────────────────────── overlay drawing ──────────────────────────────────

def draw_overlay(
    frame: np.ndarray,
    det: Detection,
    cmd: Command,
    distance_m: float,
    debug: bool,
) -> np.ndarray:
    x1, y1, x2, y2 = det.bbox
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    fh, fw = frame.shape[:2]

    # Bounding box
    colour = (0, 200, 0) if det.kind == "human" else (0, 170, 255)
    cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)

    # Centre dot
    cv2.circle(frame, (cx, cy), 5, colour, -1)

    # Label above box
    label = f"{det.label} | {distance_m:.2f} m"
    cv2.putText(frame, label, (x1, max(y1 - 8, 20)),
                cv2.FONT_HERSHEY_DUPLEX, 0.65, colour, 1, cv2.LINE_AA)

    # Command banner at bottom
    banner_h = 48
    banner   = np.zeros((banner_h, fw, 3), dtype=np.uint8)
    cv2.putText(banner, cmd.description, (12, 32),
                cv2.FONT_HERSHEY_DUPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
    frame[-banner_h:] = cv2.addWeighted(
        frame[-banner_h:], 0.35, banner, 0.65, 0)

    # Crosshair at frame centre
    mid_x, mid_y = fw // 2, fh // 2
    cv2.line(frame, (mid_x - 20, mid_y), (mid_x + 20, mid_y), (200, 200, 200), 1)
    cv2.line(frame, (mid_x, mid_y - 20), (mid_x, mid_y + 20), (200, 200, 200), 1)

    # Debug info
    if debug:
        dbg_lines = [
            f"bbox: {x1},{y1}→{x2},{y2}",
            f"conf: {det.confidence:.2f}",
            f"rotate: {cmd.rotate_deg:+.1f}°",
            f"move:   {cmd.move_m:+.2f} m",
        ]
        for i, line in enumerate(dbg_lines):
            cv2.putText(frame, line, (8, 18 + i * 18),
                        cv2.FONT_HERSHEY_PLAIN, 1.1, (0, 255, 255), 1)

    # Arrow from centre toward target
    arrow_end = (
        mid_x + int((cx - mid_x) * 0.4),
        mid_y + int((cy - mid_y) * 0.4),
    )
    cv2.arrowedLine(frame, (mid_x, mid_y), arrow_end, (0, 255, 200), 2, tipLength=0.3)

    return frame


def draw_no_target(frame: np.ndarray) -> np.ndarray:
    fh, fw = frame.shape[:2]
    banner_h = 48
    banner   = np.zeros((banner_h, fw, 3), dtype=np.uint8)
    cv2.putText(banner, "⟳ SCANNING – no target detected", (12, 32),
                cv2.FONT_HERSHEY_DUPLEX, 0.65, (100, 100, 255), 1, cv2.LINE_AA)
    frame[-banner_h:] = cv2.addWeighted(frame[-banner_h:], 0.35, banner, 0.65, 0)
    return frame


# ─────────────────────────── source builders ─────────────────────────────────

def open_source(args) -> cv2.VideoCapture:
    """
    Open the video source. scrcpy by default pipes to a window you can
    grab with WindowCapture, OR you can run scrcpy with --v4l2-sink=/dev/video0
    to create a virtual webcam (cleanest method).

    Priority:
      1. Virtual webcam index (--source v4l2 --device /dev/videoN)  ← recommended
      2. Named window capture via winname (Linux: XCB / Windows: DXGI)
      3. File path
      4. Default webcam (index 0)  – for quick testing without scrcpy
    """
    if args.source == "v4l2":
        dev = args.device or "/dev/video2"
        cap = cv2.VideoCapture(dev)
        if not cap.isOpened():
            sys.exit(f"[ERROR] Cannot open v4l2 device {dev}.\n"
                     "Run: scrcpy --video-source=camera --v4l2-sink=/dev/video2 --no-audio")
        print(f"[INFO] Opened v4l2 device: {dev}")
        return cap

    if args.source == "file":
        if not args.path:
            sys.exit("[ERROR] --path required for file source")
        cap = cv2.VideoCapture(args.path)
        if not cap.isOpened():
            sys.exit(f"[ERROR] Cannot open file: {args.path}")
        print(f"[INFO] Opened file: {args.path}")
        return cap

    # Fallback: default camera (index 0) – useful for testing without phone
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        sys.exit("[ERROR] No camera found at index 0.")
    print("[INFO] Opened default webcam (index 0). "
          "Connect via scrcpy --v4l2-sink for phone camera.")
    return cap


# ─────────────────────────── main loop ───────────────────────────────────────

def run(args):
    cap          = open_source(args)
    ret, frame   = cap.read()
    if not ret:
        sys.exit("[ERROR] Could not read first frame.")

    fh, fw = frame.shape[:2]

    # The sensor's wide axis always carries HFOV_DEG.
    # In landscape (w >= h) that is frame_w; in portrait (h > w) it is frame_h.
    if fh > fw:          # portrait – phone held upright
        focal = compute_focal(fh, HFOV_DEG)
        orientation = "portrait"
    else:                # landscape
        focal = compute_focal(fw, HFOV_DEG)
        orientation = "landscape"
    print(f"[INFO] Frame: {fw}×{fh} ({orientation}) | Focal: {focal:.1f} px | HFOV: {HFOV_DEG}°")

    human_det  = HumanDetector()
    object_det = BoxDetector()
    # Share the YOLO model so we don't load it twice
    if human_det.enabled:
        object_det.share_model(human_det.model)
    else:
        print("[WARN] BoxDetector disabled – needs YOLO from HumanDetector")
    # line_det   = LineFollower()  # (legacy - commented for reference)
    tracker    = EMATracker()

    paused = False
    debug  = args.debug
    show_line_overlay = True
    mode   = args.mode    # "human" | "object" | "both" | "line" | "all"

    prev_cmd_time = 0.0
    CMD_INTERVAL  = 0.4   # seconds between console prints

    use_line  = mode in ("line", "all")
    use_human = mode in ("human", "both", "all")
    use_box   = mode in ("object", "both", "all")

    print(f"\n[RUNNING]  mode={mode}  Press  q=quit  p=pause  d=debug  l=line-overlay\n")

    while True:
        if not paused:
            ret, frame = cap.read()
            if not ret:
                print("[INFO] Stream ended.")
                break

        display = frame.copy()

        # ── Target detection (human / box) ────────────────────────────────
        detections: List[Detection] = []
        if use_human:
            detections += human_det.detect(frame)
        if use_box:
            detections += object_det.detect(frame)

        target_found = False
        if detections:
            target_found = True
            best = max(detections, key=lambda d: d.confidence)

            smooth_bbox = tracker.update(best.bbox)
            best = Detection(
                label=best.label,
                bbox=smooth_bbox,
                confidence=best.confidence,
                kind=best.kind,
            )

            x1, y1, x2, y2 = best.bbox
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            bbox_h = y2 - y1

            known_h = KNOWN_HUMAN_HEIGHT_M if best.kind == "human" else KNOWN_BOX_HEIGHT_M
            dist    = estimate_distance(bbox_h, focal, known_h)
            cmd     = build_command(cx, cy, fw, fh, focal, dist, best.kind)
            display = draw_overlay(display, best, cmd, dist, debug)

            now = time.time()
            if now - prev_cmd_time >= CMD_INTERVAL:
                print(f"  [{best.kind.upper():6s}] dist={dist:.2f}m  {cmd.description}")
                prev_cmd_time = now
        else:
            tracker.prev = None

        # ── Line following ────────────────────────────────────────────
        # In "all" mode: line-follow is the cruise behaviour,
        # target-tracking overrides when a target is visible.
        # In "line" mode: pure line following, no target detection.
        if use_line:
            # --- HuggingFace/MobileNet line model integration ---
            # Import block at top of file:
            # from huggingface_hub import hf_hub_download
            # import torch
            # import torch.nn as nn
            # from torchvision import transforms, models
            # DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
            # CLASS_NAMES = [...] as above
            if not hasattr(run, '_line_model'):
                from huggingface_hub import hf_hub_download
                import torch
                import torch.nn as nn
                from torchvision import transforms, models
                run._DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
                run._CLASS_NAMES = ['Move Left', 'Move Right', 'No Line', 'Straight', 'Turn Left', 'Turn Right']
                run._tf = transforms.Compose([
                    transforms.ToPILImage(), transforms.Resize((224, 224)), transforms.ToTensor(),
                    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
                ])
                run._line_model = None
            if run._line_model is None:
                path = hf_hub_download(repo_id='Archiebtw/Line_follower_mobilnetv2', filename='line_classifier.pth')
                model = models.mobilenet_v2(weights=None)
                model.classifier = nn.Sequential(
                    nn.Dropout(p=0.3),
                    nn.Linear(model.last_channel, len(run._CLASS_NAMES))
                )
                ckpt = torch.load(path, map_location=run._DEVICE)
                model.load_state_dict(ckpt['model_state'])
                model.eval().to(run._DEVICE)
                run._line_model = model
                print(f"✅ Loaded Huggingface Line Follower | Val acc: {ckpt['val_acc']:.1f}%")
            # Prediction helper
            def predict_line_label(frame):
                tensor = run._tf(frame).unsqueeze(0).to(run._DEVICE)
                with torch.no_grad():
                    probs = torch.softmax(run._line_model(tensor), dim=1)
                    conf, pred = probs.max(dim=1)
                labels = run._CLASS_NAMES
                return labels[pred.item()], conf.item(), probs.cpu().numpy()[0]
            # Proportional map
            def label_to_cmd(label):
                if label == "Move Left": return "L2"
                if label == "Turn Left": return "L3"
                if label == "Move Right": return "R2"
                if label == "Turn Right": return "R3"
                if label == "Straight": return "F1"
                if label == "No Line": return "S"
                return "S"
            label, conf, probvec = predict_line_label(frame)
            cmd = label_to_cmd(label)
            # Optionally print/log
            if mode == "line" or not target_found:
                print(f"  [LINE  ] Model: {label} (conf={conf*100:.1f}%) → Command: {cmd}")
                # There is no OpenCV overlay for model, could draw text/banner if desired
                now = time.time()
                if now - prev_cmd_time >= CMD_INTERVAL:
                    prev_cmd_time = now
            # ---- End HuggingFace block ----
            # --- Legacy OpenCV line follower (commented for reference) ---
            # lr = line_det.scan(frame)
            # if mode == "line" or not target_found:
            #     if show_line_overlay:
            #         display = draw_line_overlay(display, lr, debug)
            #     now = time.time()
            #     if now - prev_cmd_time >= CMD_INTERVAL:
            #         print(f"  [LINE  ] {lr.description}")
            #         prev_cmd_time = now
            # elif target_found and show_line_overlay:
            #     lr_overlay = draw_line_overlay(frame.copy(), lr, False)
            #     display = cv2.addWeighted(display, 0.75, lr_overlay, 0.25, 0)

        # No target and not line-following → show scanning banner
        if not target_found and not use_line:
            display = draw_no_target(display)

        if use_line and mode == "line":
            control_flags = pygame_bgr_preview(display, window_name="ML Line Tracking")
            if control_flags.get('quit'):
                break
            if control_flags.get('pause'):
                paused = not paused
                print(f"[{'PAUSED' if paused else 'RESUMED'}]")
            if control_flags.get('debug'):
                debug = not debug
                print(f"[DEBUG {'ON' if debug else 'OFF'}]")
            if control_flags.get('line'):
                show_line_overlay = not show_line_overlay
                print(f"[LINE OVERLAY {'ON' if show_line_overlay else 'OFF'}]")
            # Mask window behavior is disabled in ML/pygame mode, but could be implemented similarly if needed
        else:
            cv2.imshow("Tracker", display)
            if debug and use_line:
                show_line_debug_mask(line_det)
                _ml_prev_mask_shown = True
            else:
                try:
                    if '_ml_prev_mask_shown' in locals() and _ml_prev_mask_shown:
                        cv2.destroyWindow("LFR Mask (press 'd' to hide)")
                        _ml_prev_mask_shown = False
                except cv2.error:
                    pass
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('p'):
                paused = not paused
                print(f"[{'PAUSED' if paused else 'RESUMED'}]")
            elif key == ord('d'):
                debug = not debug
                print(f"[DEBUG {'ON' if debug else 'OFF'}]")
            elif key == ord('l'):
                show_line_overlay = not show_line_overlay
                print(f"[LINE OVERLAY {'ON' if show_line_overlay else 'OFF'}]")


    cap.release()
    # Cleanup pygame and OpenCV windows if used
    try:
        import pygame
        pygame.quit()
    except Exception:
        pass
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass
    print("[INFO] Stopped.")


# ─────────────────────────── entry point ─────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="scrcpy → OpenCV human/object tracker with movement commands"
    )
    parser.add_argument(
        "--mode",
        choices=["human", "object", "both", "line", "all"],
        default="both",
        help=(
            "human  → detect humans only\n"
            "object → detect box only\n"
            "both   → humans + box (default)\n"
            "line   → line-following only (LFR)\n"
            "all    → line-following + humans + box"
        ),
    )
    parser.add_argument(
        "--source", choices=["v4l2", "file", "webcam"],
        default="v4l2",
        help=(
            "v4l2   → virtual webcam from scrcpy --v4l2-sink (default, recommended)\n"
            "file   → video file (use --path)\n"
            "webcam → default camera index 0 (testing)"
        ),
    )
    parser.add_argument("--device", default="/dev/video2",
                        help="v4l2 device path (default: /dev/video2)")
    parser.add_argument("--path",   default=None,
                        help="File path when --source file")
    parser.add_argument("--debug",  action="store_true",
                        help="Show debug info overlay")
    args = parser.parse_args()
    run(args)
