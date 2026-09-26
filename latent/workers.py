"""Background work without touching Tk from other threads.

Tk is not thread-safe.  v1 called ``winfo_width()`` and ``root.after()`` from
worker threads, which can crash or deadlock on Windows.  Here workers only
compute; results are handed back through a queue that the Tk main loop drains
with :meth:`Dispatcher.pump`.
"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


class Dispatcher:
    """Runs callbacks on the Tk thread."""

    def __init__(self, root, interval_ms: int = 12):
        self._root = root
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._interval = interval_ms
        self._alive = True
        root.after(interval_ms, self.pump)

    def post(self, fn: Callable, *args: Any) -> None:
        self._queue.put((fn, args))

    def pump(self) -> None:
        if not self._alive:
            return
        deadline = 40  # max callbacks per tick keeps the UI responsive
        try:
            while deadline:
                fn, args = self._queue.get_nowait()
                deadline -= 1
                try:
                    fn(*args)
                except Exception:  # pragma: no cover - surfaced in log
                    log.exception("UI callback failed")
        except queue.Empty:
            pass
        try:
            self._root.after(self._interval, self.pump)
        except Exception:
            self._alive = False

    def stop(self) -> None:
        self._alive = False


class CancelToken:
    def __init__(self):
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


class Channel:
    """A worker thread that only ever runs the most recent job.

    Submitting while a job is pending replaces it (frame coalescing), so fast
    slider drags never queue up stale renders.  The running job gets a
    :class:`CancelToken` it can poll to bail out early.
    """

    def __init__(self, dispatcher: Dispatcher, name: str):
        self._dispatcher = dispatcher
        self._name = name
        self._cond = threading.Condition()
        self._pending: Optional[tuple] = None
        self._current_token: Optional[CancelToken] = None
        self._thread = threading.Thread(target=self._run, name=f"latent-{name}", daemon=True)
        self._thread.start()

    def submit(self, job: Callable[[CancelToken], Any], on_done: Optional[Callable[[Any], None]] = None,
               on_error: Optional[Callable[[BaseException], None]] = None, cancel_running: bool = False) -> CancelToken:
        token = CancelToken()
        with self._cond:
            if cancel_running and self._current_token is not None:
                self._current_token.cancel()
            self._pending = (job, on_done, on_error, token)
            self._cond.notify()
        return token

    def cancel(self) -> None:
        with self._cond:
            self._pending = None
            if self._current_token is not None:
                self._current_token.cancel()

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._pending is None:
                    self._cond.wait()
                job, on_done, on_error, token = self._pending
                self._pending = None
                self._current_token = token
            try:
                result = job(token)
                if not token.cancelled and on_done is not None:
                    self._dispatcher.post(on_done, result)
            except BaseException as exc:  # noqa: BLE001 - reported to UI
                log.exception("%s job failed", self._name)
                if on_error is not None and not token.cancelled:
                    self._dispatcher.post(on_error, exc)
            finally:
                with self._cond:
                    self._current_token = None
