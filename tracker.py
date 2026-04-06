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
"""

import cv2
from pygame_preview import pygame_bgr_preview
import numpy as np
import argparse
import math
import time
import sys
from dataclasses import dataclass
from typing import Optional, Tuple, List
from collections import deque

import torch
import torch.nn as nn
from torchvision import models, transforms

# ─────────────────────────── config ───────────────────────────────────────────

MODEL_PATH = '/home/ladliju/Developer/Model_finetune/line_classifier.pth'
IMG_SIZE = 224
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
CLASS_NAMES = ['Move Left', 'Move Right', 'No Line', 'Straight', 'Turn Left', 'Turn Right']

HFOV_DEG        = 69.0
KNOWN_HUMAN_HEIGHT_M  = 1.70
KNOWN_BOX_HEIGHT_M    = 0.10

YOLO_CONF       = 0.45
YOLO_IOU        = 0.45
BOX_YOLO_CONF   = 0.30
BOX_ASPECT_MIN  = 0.50
BOX_ASPECT_MAX  = 2.00
BOX_MIN_AREA_PX = 400
BOX_COCO_CLASSES = [24, 26, 28, 73]

ANGLE_DEAD_ZONE_DEG  = 3.0
DIST_DEAD_ZONE_M     = 0.03
STOP_DISTANCE_HUMAN_M  = 1.0
STOP_DISTANCE_OBJECT_M = 0.10

SMOOTH_ALPHA = 0.25

LINE_SCAN_TOP_FRAC    = 0.35
LINE_SCAN_BOT_FRAC    = 0.97
LINE_MIN_WIDTH_PX     = 4
LINE_MAX_WIDTH_FRAC   = 0.85
LINE_STEER_DEAD_ZONE  = 0.05
LINE_NUM_SCAN_ROWS    = 7
LINE_SPEED_DEFAULT    = "CRUISE"

LINE_CLAHE_CLIP       = 4.0
LINE_CLAHE_GRID       = (8, 8)
LINE_ADAPTIVE_BLOCK   = 201
LINE_ADAPTIVE_C       = 15

# ─────────────────────────── data structures ──────────────────────────────────

@dataclass
class Detection:
    label: str
    bbox: Tuple[int, int, int, int]
    confidence: float
    kind: str

@dataclass
class Command:
    rotate_deg: float
    move_m: float
    description: str

@dataclass
class LineResult:
    detected: bool
    error_frac: float
    steer: str
    description: str
    centroids: List[Tuple[int, int]]
    is_ml: bool = False
    confidence: float = 0.0

# ─────────────────────────── geometry helpers ─────────────────────────────────

_FOCAL_CACHE = {}

def compute_focal(frame_w: int, hfov_deg: float) -> float:
    cache_key = (frame_w, hfov_deg)
    if cache_key in _FOCAL_CACHE: return _FOCAL_CACHE[cache_key]
    focal = (frame_w / 2.0) / math.tan(math.radians(hfov_deg / 2.0))
    _FOCAL_CACHE[cache_key] = focal
    return focal

def pixel_offset_to_angle(pixel_offset: float, focal_px: float) -> float:
    return math.degrees(math.atan2(pixel_offset, focal_px))

def estimate_distance(bbox_height_px: int, focal_px: float, known_height_m: float) -> float:
    if bbox_height_px < 5: return 9999.0
    return round((known_height_m * focal_px) / bbox_height_px, 2)

def build_command(cx, cy, frame_w, frame_h, focal_px, distance_m, kind) -> Command:
    offset_x = cx - frame_w // 2
    rotate_deg = pixel_offset_to_angle(offset_x, focal_px)
    stop_d = STOP_DISTANCE_HUMAN_M if kind == "human" else STOP_DISTANCE_OBJECT_M
    move_m = distance_m - stop_d
    parts = []
    if abs(rotate_deg) > ANGLE_DEAD_ZONE_DEG:
        parts.append(f"ROTATE {'RIGHT' if rotate_deg > 0 else 'LEFT'} {abs(rotate_deg):.1f}°")
    if abs(move_m) > DIST_DEAD_ZONE_M:
        parts.append(f"MOVE {'FORWARD' if move_m > 0 else 'BACKWARD'} {abs(move_m):.2f} m")
    return Command(rotate_deg, move_m, "  |  ".join(parts) if parts else f"✓ ON TARGET ({stop_d*100:.0f} cm)")

# ─────────────────────────── detectors ───────────────────────────────────────

class HumanDetector:
    def __init__(self):
        try:
            from ultralytics import YOLO
            self.model = YOLO("yolov8n.pt")
            self.model.overrides['verbose'] = False
            self.enabled = True
        except ImportError:
            self.enabled = False

    def detect(self, frame: np.ndarray) -> List[Detection]:
        if not self.enabled or frame is None: return []
        results = self.model(frame, conf=YOLO_CONF, iou=YOLO_IOU, classes=[0], verbose=False)[0]
        detections = []
        if results.boxes is not None:
            for box in results.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                detections.append(Detection("person", (x1, y1, x2, y2), float(box.conf[0]), "human"))
        return detections

class BoxDetector:
    def __init__(self):
        self.model = None
        self.enabled = False

    def share_model(self, model):
        self.model = model
        self.enabled = True

    def detect(self, frame: np.ndarray) -> List[Detection]:
        if not self.enabled or self.model is None: return []
        results = self.model(frame, conf=BOX_YOLO_CONF, iou=YOLO_IOU, classes=BOX_COCO_CLASSES, verbose=False)[0]
        detections = []
        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            w, h = x2 - x1, y2 - y1
            if w * h < BOX_MIN_AREA_PX or not (BOX_ASPECT_MIN <= w/max(h,1) <= BOX_ASPECT_MAX): continue
            detections.append(Detection(f"box", (x1, y1, x2, y2), float(box.conf[0]), "object"))
        detections.sort(key=lambda d: d.confidence, reverse=True)
        return detections[:1]

# ─────────────────────────── line follower ───────────────────────────────────────

# Legacy OpenCV logic disabled to enforce ML-only operation
"""
class LineFollower:
    # ... logic for classic CV line following ...
"""

class HybridLineFollower:
    def __init__(self):
        self.use_model = False
        self._line_model = None
        self._tf = transforms.Compose([
            transforms.ToPILImage(), transforms.Resize((224, 224)), transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
        
        import os
        path = None
        if os.path.exists(MODEL_PATH):
            print(f"[ML-CHECK] Attempting to load local weights: {MODEL_PATH}")
            path = MODEL_PATH
        else:
            try:
                from huggingface_hub import hf_hub_download
                print("[ML-CHECK] Local weights not found. Trying HuggingFace...")
                path = hf_hub_download(repo_id='Archiebtw/Line_follower_mobilnetv2', filename='line_classifier.pth')
            except Exception as e:
                print(f"[ML-CHECK] HuggingFace download failed: {e}")

        if path:
            try:
                model = models.mobilenet_v2(weights=None)
                model.classifier = nn.Sequential(nn.Dropout(p=0.3), nn.Linear(model.last_channel, len(CLASS_NAMES)))
                checkpoint = torch.load(path, map_location=DEVICE)
                if isinstance(checkpoint, dict) and 'model_state' in checkpoint:
                    model.load_state_dict(checkpoint['model_state'])
                    acc = checkpoint.get('val_acc', 'N/A')
                    print(f"✅ ML SUCCESS: Model loaded (Acc: {acc})")
                else:
                    model.load_state_dict(checkpoint)
                    print(f"✅ ML SUCCESS: Model loaded (Raw Weights)")
                model.eval().to(DEVICE)
                self._line_model = model
                self.use_model = True
            except Exception as e:
                print(f"❌ ML ERROR: Load Failed: {e}")

    def scan(self, frame: np.ndarray) -> LineResult:
        if self.use_model and self._line_model is not None:
            try:
                tensor = self._tf(frame).unsqueeze(0).to(DEVICE)
                with torch.no_grad():
                    probs = torch.softmax(self._line_model(tensor), dim=1)
                    conf, pred = probs.max(dim=1)
                label = CLASS_NAMES[pred.item()]
                steer = self.map_label_to_steer(label)
                fh, fw = frame.shape[:2]
                mid_x = fw // 2
                target_x = mid_x
                if steer == "LEFT": target_x = mid_x - int(mid_x * 0.4)
                elif steer == "RIGHT": target_x = mid_x + int(mid_x * 0.4)
                y_top, y_bot = int(fh * LINE_SCAN_TOP_FRAC), int(fh * LINE_SCAN_BOT_FRAC)
                centroids = [(target_x, y_top + 20), (target_x, (y_top + y_bot)//2), (target_x, y_bot - 20)]
                return LineResult(label != "No Line", 0.0, steer, f"ML: {label} ({conf.item()*100:.1f}%)", centroids if label != "No Line" else [], True, conf.item())
            except Exception as e:
                print(f"❌ ML RUNTIME ERROR: {e}")
        return LineResult(False, 0.0, "LOST", "ML Active - Searching...", [], True)

    @staticmethod
    def map_label_to_steer(label):
        label = label.lower()
        if "left" in label: return "LEFT"
        if "right" in label: return "RIGHT"
        if "straight" in label: return "STRAIGHT"
        return "LOST"

def draw_line_overlay(frame, lr, debug):
    fh, fw = frame.shape[:2]
    y_top, y_bot = int(fh * LINE_SCAN_TOP_FRAC), int(fh * LINE_SCAN_BOT_FRAC)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (fw, y_top), (0,0,0), -1)
    cv2.rectangle(overlay, (0, y_bot), (fw, fh), (0,0,0), -1)
    frame = cv2.addWeighted(frame, 0.7, overlay, 0.3, 0)
    colour = (255, 0, 255) if lr.is_ml else (255, 255, 0)
    if lr.detected and lr.steer == "STRAIGHT": colour = (0, 255, 0)
    mid_x = fw // 2
    cv2.line(frame, (mid_x, y_top), (mid_x, y_bot), (80, 80, 80), 1)
    if lr.detected and lr.centroids:
        for j, (cx, cy) in enumerate(lr.centroids):
            cv2.circle(frame, (cx, cy), 6, colour, -1)
            if j > 0: cv2.line(frame, lr.centroids[j-1], (cx, cy), colour, 2)
    banner_h = 48
    cv2.rectangle(frame, (0, fh - banner_h), (fw, fh), (20, 20, 20), -1)
    cv2.putText(frame, f"LFR | {lr.description}", (15, fh - 15), cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 1)
    if lr.is_ml:
        cv2.putText(frame, "AI ACTIVE", (fw - 100, fh - 15), cv2.FONT_HERSHEY_DUPLEX, 0.5, (255, 0, 255), 1)
        bar_w = int(lr.confidence * 150)
        cv2.rectangle(frame, (15, fh - 65), (15 + bar_w, fh - 55), colour, -1)
    return frame

# ─────────────────────────── main loop ───────────────────────────────────────

class EMATracker:
    def __init__(self, alpha=SMOOTH_ALPHA):
        self.alpha = alpha
        self.prev = None
    def update(self, bbox):
        if self.prev is None: self.prev = bbox; return bbox
        smoothed = tuple(int(bbox[i]*self.alpha + self.prev[i]*(1-self.alpha)) for i in range(4))
        self.prev = smoothed; return smoothed

def draw_overlay(frame, det, cmd, distance_m, debug):
    x1, y1, x2, y2 = det.bbox
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    colour = (0, 200, 0) if det.kind == "human" else (0, 170, 255)
    cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
    cv2.putText(frame, f"{det.label} | {distance_m:.2f} m", (x1, max(y1-8, 20)), cv2.FONT_HERSHEY_DUPLEX, 0.65, colour, 1)
    return frame

def run(args):
    dev = args.device if args.source != "webcam" else 0
    cap = cv2.VideoCapture(dev)
    if not cap.isOpened(): sys.exit(f"[ERROR] Cannot open camera {dev}")
    
    human_det = HumanDetector()
    object_det = BoxDetector()
    if human_det.enabled: object_det.share_model(human_det.model)
    line_det = HybridLineFollower()
    tracker = EMATracker()
    
    print(f"\n[RUNNING] mode={args.mode} Press q=quit\n")
    while True:
        ret, frame = cap.read()
        if not ret: break
        display = frame.copy()
        target_found = False
        
        if args.mode in ("human", "both", "all"):
            dets = human_det.detect(frame)
            if dets:
                target_found = True
                best = max(dets, key=lambda d: d.confidence)
                dist = estimate_distance(best.bbox[3]-best.bbox[1], compute_focal(frame.shape[1], HFOV_DEG), KNOWN_HUMAN_HEIGHT_M)
                cmd = build_command((best.bbox[0]+best.bbox[2])//2, 0, frame.shape[1], frame.shape[0], compute_focal(frame.shape[1], HFOV_DEG), dist, "human")
                display = draw_overlay(display, best, cmd, dist, args.debug)
                print(f"[HUMAN] dist={dist:.2f}m {cmd.description}")

        if args.mode in ("line", "all") and (not target_found or args.mode == "all"):
            lr = line_det.scan(frame)
            display = draw_line_overlay(display, lr, args.debug)
            print(f"[LINE] {lr.description} -> {lr.steer}")

        try:
            cv2.imshow("Tracker", display)
        except Exception:
            pygame_bgr_preview(display)
        if cv2.waitKey(1) & 0xFF == ord('q'): break
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["human", "object", "both", "line", "all"], default="line")
    parser.add_argument("--source", choices=["v4l2", "file", "webcam"], default="webcam")
    parser.add_argument("--device", default="/dev/video2")
    parser.add_argument("--debug", action="store_true")
    run(parser.parse_args())
