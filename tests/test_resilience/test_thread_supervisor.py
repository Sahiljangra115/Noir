"""Tests for ThreadSupervisor restart logic."""
import threading
import time
import pytest
from backend.services.supervisor import ThreadSupervisor


@pytest.mark.unit
def test_registers_and_starts_thread():
    results = []

    def factory():
        def run():
            results.append("started")
        return threading.Thread(target=run, daemon=True)

    sup = ThreadSupervisor()
    sup.register("worker", factory)
    sup.start()
    time.sleep(0.05)
    sup.stop()
    assert "started" in results


@pytest.mark.unit
def test_restarts_crashed_thread():
    call_count = {"n": 0}
    event = threading.Event()

    def factory():
        call_count["n"] += 1
        if call_count["n"] >= 2:
            event.set()

        def run():
            pass  # exits immediately → looks crashed to supervisor

        return threading.Thread(target=run, daemon=False)

    sup = ThreadSupervisor()
    sup.POLL_S = 0.05
    sup.register("crasher", factory)
    sup.start()
    event.wait(timeout=3.0)
    sup.stop()
    assert call_count["n"] >= 2


@pytest.mark.unit
def test_max_restarts_respected():
    sup = ThreadSupervisor()
    sup.POLL_S = 0.01
    sup.WINDOW_S = 60.0

    def factory():
        return threading.Thread(target=lambda: None, daemon=False)

    sup.register("crasher", factory)
    sup.start()

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if sup.status().get("crasher") == "degraded":
            break
        time.sleep(0.05)

    sup.stop()
    assert sup.status().get("crasher") == "degraded"


@pytest.mark.unit
def test_status_returns_alive_for_running_thread():
    stop = threading.Event()

    def factory():
        return threading.Thread(target=lambda: stop.wait(), daemon=True)

    sup = ThreadSupervisor()
    sup.register("long", factory)
    sup.start()
    time.sleep(0.05)
    assert sup.status()["long"] == "alive"
    stop.set()
    sup.stop()
