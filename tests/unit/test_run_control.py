"""Tests for `multihop_eval.run_control.RunControl` — pause/stop semantics."""

from __future__ import annotations

import threading
import time

from multihop_eval.run_control import RunControl


def test_default_state_is_running_and_not_stopped() -> None:
    control = RunControl()
    assert control.is_paused is False
    assert control.is_stop_requested is False


def test_wait_if_paused_returns_immediately_when_not_paused() -> None:
    control = RunControl()
    started = time.monotonic()
    stopped = control.wait_if_paused(timeout=1.0)
    elapsed = time.monotonic() - started
    assert stopped is False
    # Should be near-instant — generous bound to avoid CI flakes.
    assert elapsed < 0.2


def test_pause_blocks_until_resume() -> None:
    """A worker thread paused via `wait_if_paused` should unblock on `resume`."""
    control = RunControl()
    control.pause()
    woke_up = threading.Event()

    def worker() -> None:
        # No timeout: this MUST block until resume() is called.
        stopped = control.wait_if_paused()
        assert stopped is False
        woke_up.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    # Give the worker time to actually enter the wait.
    time.sleep(0.05)
    assert woke_up.is_set() is False, "Worker should still be paused"

    control.resume()
    assert woke_up.wait(timeout=1.0) is True
    t.join(timeout=1.0)
    assert t.is_alive() is False


def test_pause_blocks_until_stop_requested() -> None:
    """`request_stop` must release any paused worker so it can exit."""
    control = RunControl()
    control.pause()
    return_value: dict[str, bool] = {}

    def worker() -> None:
        return_value["stopped"] = control.wait_if_paused()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    time.sleep(0.05)
    assert "stopped" not in return_value

    control.request_stop()
    t.join(timeout=1.0)
    assert t.is_alive() is False
    assert return_value["stopped"] is True


def test_request_stop_after_resume_is_idempotent() -> None:
    control = RunControl()
    control.pause()
    control.resume()
    assert control.is_paused is False
    control.request_stop()
    assert control.is_stop_requested is True
    # Subsequent waits return True immediately.
    assert control.wait_if_paused(timeout=0.1) is True


def test_pause_after_stop_is_a_noop() -> None:
    """Once stopped, `pause()` should not be able to wedge the worker."""
    control = RunControl()
    control.request_stop()
    control.pause()  # should NOT clear the pause event
    assert control.is_paused is False
    # And `wait_if_paused` should still return immediately with stop=True.
    assert control.wait_if_paused(timeout=0.1) is True


def test_resume_without_pause_is_safe() -> None:
    control = RunControl()
    control.resume()  # already not paused — should not raise
    assert control.is_paused is False
