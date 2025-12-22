"""
Threading utilities to reduce code duplication.
"""
import threading
from typing import Any, Callable


def create_daemon_thread(target: Callable, name: str, **kwargs) -> threading.Thread:
    """Create a daemon thread with consistent configuration."""
    return threading.Thread(target=target, daemon=True, name=name, **kwargs)


def create_timer_thread(delay: float, target: Callable, **kwargs) -> threading.Timer:
    """Create a daemon timer thread."""
    timer = threading.Timer(delay, target, **kwargs)
    timer.daemon = True
    return timer