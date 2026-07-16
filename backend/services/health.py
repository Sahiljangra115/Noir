"""
backend/services/health.py
───────────────────────────
Non-blocking startup health checks. Each check returns ``bool`` and never
raises so ``run_all()`` can build a complete picture and the caller decides
whether to abort or degrade (e.g. force IDLE on missing camera).
"""

import logging
import os
from pathlib import Path

import requests

log = logging.getLogger(__name__)


def check_ollama(url: str, timeout: float = 2.0) -> bool:
    """GET ``{url}/api/tags`` — True on HTTP 200, False otherwise. Logs on failure."""
    endpoint = url.rstrip("/") + "/api/tags"
    try:
        resp = requests.get(endpoint, timeout=timeout)
    except requests.RequestException as exc:
        log.warning("[HEALTH] Ollama unreachable at %s: %s", endpoint, exc)
        return False
    if resp.status_code != 200:
        log.warning("[HEALTH] Ollama %s returned %s", endpoint, resp.status_code)
        return False
    return True


def check_piper(piper_bin) -> bool:
    """Path exists and is executable."""
    if not piper_bin:
        return False
    path = Path(piper_bin).expanduser()
    if not path.exists():
        log.warning("[HEALTH] Piper binary missing: %s", path)
        return False
    if not os.access(path, os.X_OK):
        log.warning("[HEALTH] Piper binary not executable: %s", path)
        return False
    return True


def check_camera(device) -> bool:
    """Open + release ``cv2.VideoCapture(device)`` to verify the device is usable."""
    try:
        import cv2  # lazy import: keep this module light at startup
    except ImportError:
        log.warning("[HEALTH] cv2 not importable")
        return False

    dev = device
    if isinstance(dev, str) and dev.lstrip("-").isdigit():
        dev = int(dev)

    cap = cv2.VideoCapture(dev)
    try:
        if not cap.isOpened():
            log.warning("[HEALTH] Camera %r could not be opened", device)
            return False
        return True
    finally:
        cap.release()


def run_all(cfg) -> dict[str, bool]:
    """Run all checks and return a mapping. Caller decides on abort vs degrade."""
    results = {
        "ollama": check_ollama(cfg.OLLAMA_URL),
        "piper": check_piper(cfg.PIPER_BIN) if cfg.VOICE_ENABLED else True,
    }
    log.info("[HEALTH] checks: %s", results)
    return results
