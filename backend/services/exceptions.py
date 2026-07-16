"""
backend/services/exceptions.py
───────────────────────────────
Custom exceptions raised across the backend so callers can catch a single
``JarvisError`` base class and degrade gracefully instead of crashing.
"""


class JarvisError(Exception):
    """Base class for all JARVIS-specific runtime errors."""


class CameraUnavailable(JarvisError):
    def __init__(self, device):
        super().__init__(f"Camera device {device!r} could not be opened")
        self.device = device


class OllamaUnavailable(JarvisError):
    pass


class PiperUnavailable(JarvisError):
    pass


class ESP32Unreachable(JarvisError):
    pass
