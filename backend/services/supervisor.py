"""Thread supervision: auto-restart background threads on crash."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable

log = logging.getLogger(__name__)


class ThreadSupervisor:
    """Supervises background threads. Restarts them when they die.

    Each registered factory must return a fresh `threading.Thread` each call.
    The supervisor itself is the only daemon thread.
    """
    MAX_RESTARTS = 10
    WINDOW_S = 60.0
    POLL_S = 1.0

    def __init__(self) -> None:
        self._registry: dict[str, Callable[[], threading.Thread]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._restart_history: dict[str, deque[float]] = {}
        self._degraded: set[str] = set()
        self._stop = threading.Event()
        self._sup_thread: threading.Thread | None = None

    def register(self, name: str, factory: Callable[[], threading.Thread]) -> None:
        self._registry[name] = factory
        self._restart_history[name] = deque(maxlen=self.MAX_RESTARTS)

    def start(self) -> None:
        for name, factory in self._registry.items():
            t = factory()
            t.start()
            self._threads[name] = t
        self._sup_thread = threading.Thread(target=self._loop, name="supervisor", daemon=True)
        self._sup_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._sup_thread:
            self._sup_thread.join(timeout=timeout)

    def status(self) -> dict[str, str]:
        out = {}
        for name, t in self._threads.items():
            if name in self._degraded:
                out[name] = "degraded"
            elif t.is_alive():
                out[name] = "alive"
            else:
                out[name] = "dead"
        return out

    def _loop(self) -> None:
        while not self._stop.is_set():
            for name, t in list(self._threads.items()):
                if name in self._degraded:
                    continue
                if not t.is_alive():
                    self._restart(name)
            time.sleep(self.POLL_S)

    def _restart(self, name: str) -> None:
        history = self._restart_history[name]
        now = time.monotonic()
        history.append(now)
        recent = [ts for ts in history if now - ts <= self.WINDOW_S]
        if len(recent) >= self.MAX_RESTARTS:
            log.error("[SUP] %s exceeded %d restarts in %ss; entering degraded mode",
                      name, self.MAX_RESTARTS, self.WINDOW_S)
            self._degraded.add(name)
            return
        log.warning("[SUP] restarting %s (attempt %d)", name, len(recent))
        try:
            t = self._registry[name]()
            t.start()
            self._threads[name] = t
        except Exception:
            log.exception("[SUP] failed to restart %s", name)
            self._degraded.add(name)
