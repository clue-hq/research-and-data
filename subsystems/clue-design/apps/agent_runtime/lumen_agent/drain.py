"""Draining running turns when their worker shuts down (site-turn durability, 2026-10-16).

On SIGTERM a fleet worker stops taking new work and lets its running turns finish. Once its drain
bound has passed (10 minutes by default), it asks every turn still running to stop at the next step
boundary. A site turn can stop there safely: its conversation checkpoint and its working copy are
already saved, so the worker that takes the run over continues it from that step.

The ask reaches a turn through a :class:`DrainScope`. The design job handler owns one scope and
selects it for the turns it runs (:func:`drain_scope`; ``asyncio.to_thread`` carries the selection
into the turn's thread). The site harness registers its LangGraph ``RunControl`` in the selected
scope while its graph runs (:func:`registered`). The handler's ``request_drain`` drains the scope:
every registered control is asked to drain, and a turn that registers later is drained as soon as
it registers, so a turn still in its preamble when the bound passes stops at its first step.

A drained turn raises :class:`TurnDrained`. It is a ``BaseException`` on purpose: it is not an
error, the run is not failed, nothing is saved and no history is written, so no ``except
Exception`` on the way up (the executors fold every ``Exception`` into a failed turn) may catch it.
The handler that owns the scope catches it and hands the run back to the queue.
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
from collections.abc import Iterator
from typing import Any


class TurnDrained(BaseException):
    """A turn stopped at a step boundary because its worker is shutting down.

    Not an error: its checkpoint and working copy are saved, and another worker continues it."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DrainScope:
    """The running turns one handler can ask to drain. Thread-safe: turns register from their own
    threads; the drain is requested from the worker's event loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._controls: set[Any] = set()
        self._reason: str | None = None

    @property
    def draining(self) -> bool:
        return self._reason is not None

    def request_drain(self, reason: str) -> None:
        """Ask every running turn in this scope, and every turn that registers later, to stop at its
        next step boundary."""
        with self._lock:
            self._reason = reason
            controls = tuple(self._controls)
        for control in controls:
            control.request_drain(reason)

    @contextlib.contextmanager
    def running(self, control: Any) -> Iterator[None]:
        with self._lock:
            self._controls.add(control)
            reason = self._reason
        if reason is not None:
            control.request_drain(reason)
        try:
            yield
        finally:
            with self._lock:
                self._controls.discard(control)


_CURRENT: contextvars.ContextVar[DrainScope | None] = contextvars.ContextVar("lumen_drain_scope", default=None)


@contextlib.contextmanager
def drain_scope(scope: DrainScope) -> Iterator[None]:
    """Select ``scope`` for the turns started in this context (and in threads started from it)."""
    token = _CURRENT.set(scope)
    try:
        yield
    finally:
        _CURRENT.reset(token)


@contextlib.contextmanager
def registered(control: Any) -> Iterator[None]:
    """Register a running graph's ``RunControl`` in the selected scope. With no scope selected (the
    CLI, a direct executor call) nothing can ask the turn to drain."""
    scope = _CURRENT.get()
    if scope is None:
        yield
        return
    with scope.running(control):
        yield


__all__ = ["DrainScope", "TurnDrained", "drain_scope", "registered"]
