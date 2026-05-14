"""Cooperative pause / stop signalling for a long-running pipeline.

`RunControl` is a tiny, thread-safe coordinator passed by the UI into the
pipeline so the user can pause or gracefully stop a run from the Streamlit
interface. The pipeline cooperatively consults it at safe checkpoints
(between seeds, between clusters) — in-flight LLM calls always complete
before pausing or stopping, since cancelling them mid-flight is unsafe and
not portable across providers.

Two `threading.Event`s back the state machine:

* `_pause_event` — *set* means "running"; *cleared* means "paused".
* `_stop_event`  — *set* means "stop requested"; once set, never cleared.

Calling `pause()` clears the pause event; `wait_if_paused()` therefore
blocks until either `resume()` or `request_stop()` is invoked. We always
re-set the pause event on stop so a paused worker can wake up and exit
cleanly instead of deadlocking.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class RunControl:
    """Pause/stop coordinator shared between the UI and the pipeline thread.

    The default-constructed state is "running, no stop requested" so that
    the pipeline runs unhindered unless the UI explicitly intervenes.
    """

    _pause_event: threading.Event = field(default_factory=threading.Event)
    _stop_event: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        # Default to "not paused" so `wait_if_paused()` is a no-op until the
        # UI calls `pause()`.
        self._pause_event.set()

    def pause(self) -> None:
        """Request the pipeline to block at its next checkpoint.

        Has no effect if a stop has already been requested — at that point
        the pipeline is on its way out and we don't want to risk wedging
        a worker thread behind a pause that will never be released.
        """
        if not self._stop_event.is_set():
            self._pause_event.clear()

    def resume(self) -> None:
        """Release any pause so the pipeline can continue past its checkpoint."""
        self._pause_event.set()

    def request_stop(self) -> None:
        """Request a graceful stop and wake any worker blocked in `wait_if_paused`."""
        self._stop_event.set()
        # Always release the pause so the worker can observe the stop flag
        # and exit instead of deadlocking inside `wait()`.
        self._pause_event.set()

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    @property
    def is_stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def wait_if_paused(self, timeout: float | None = None) -> bool:
        """Block while paused; return True iff a stop has been requested.

        Pipeline checkpoints call this and bail out of their loop when the
        return value is True.
        """
        self._pause_event.wait(timeout=timeout)
        return self._stop_event.is_set()
