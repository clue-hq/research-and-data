"""A process-local event loop for synchronous callers that must await.

deepagents calls its file backend **synchronously** — the tool implementation returns a value,
it does not return an awaitable.  The document writers behind that backend are async: they talk
to the database, and a database connection is bound to the loop that created it.  Those two
facts cannot both be served on the caller's own loop.  Calling ``asyncio.run`` inside a running
loop raises; calling it inside a worker's *main* loop would build (and tear down) a second
connection pool on a loop that is already busy driving the turn.

This module is the seam between them.  ``AsyncBridge`` owns one background thread running one
event loop, forever, for the life of the process.  A sync caller hands it a coroutine, blocks
on the result, and gets a value or an exception back — nothing else about the caller's world
changes.  Whatever loop-bound resources the async side needs (an engine, a pool, a session
factory) are built *on this loop* by the layer that owns them and reached through
:attr:`AsyncBridge.loop`; the bridge itself deliberately knows nothing about databases, so this
module imports nothing but the standard library and stays trivially testable offline.

Three rules keep the bridge honest, and each is a named failure rather than a hang:

* Re-entering the bridge from its own loop would block the loop on itself — a guaranteed
  deadlock — so it raises ``RuntimeError("bridge re-entered")`` instead.
* A call that outruns ``timeout_s`` cancels its coroutine and raises :class:`BridgeTimeout`.
  The loop survives: the abandoned work settles in the background while later calls run.
* A call after :meth:`AsyncBridge.close` raises :class:`BridgeClosed` rather than waiting on a
  loop that will never turn again.
"""

from __future__ import annotations

import asyncio
import atexit
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

__all__ = ["AsyncBridge", "BridgeClosed", "BridgeTimeout", "process_bridge"]

#: How long :meth:`AsyncBridge.close` waits for the loop thread to finish.  It is a *bounded*
#: join on purpose: a wedged coroutine must not stop a process from exiting, and the thread is
#: a daemon precisely so the interpreter can leave without it.
_JOIN_TIMEOUT_S = 5.0


class BridgeTimeout(TimeoutError):
    """A submitted coroutine did not finish within ``timeout_s``; it has been cancelled.

    Subclasses ``TimeoutError`` so callers that already handle deadlines catch it naturally,
    while callers that care *whose* deadline fired can still tell the two apart.
    """


class BridgeClosed(RuntimeError):
    """Work was submitted to a bridge whose loop has been shut down."""


class AsyncBridge:
    """One background event loop per process for sync callers that must await.

    The loop runs on a daemon thread started in ``__init__`` and keeps running until
    :meth:`close`.  It is *shared*: submissions from different threads interleave on it as
    ordinary concurrent tasks, so one slow writer does not block another.  The only thing that
    may not submit is the loop thread itself.
    """

    def __init__(self, *, name: str = "clue-agent-bridge") -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._closed = False
        self._close_lock = threading.Lock()
        self._thread = threading.Thread(target=self._serve, name=name, daemon=True)
        self._thread.start()
        # Block until the loop is actually turning.  Without this a `run` racing construction
        # could submit to a loop that has not started, and `run_coroutine_threadsafe` would
        # queue the callback with nothing to execute it.
        self._ready.wait()

    def _serve(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._ready.set)
        try:
            self._loop.run_forever()
        finally:
            asyncio.set_event_loop(None)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """The running loop, for callers that must *build* loop-bound resources on it.

        Read-only by design.  A database engine created here belongs to this loop for its whole
        life; handing out the loop is what lets its owner honour that, without the bridge taking
        on any knowledge of engines or pools.
        """

        return self._loop

    def run(self, coro: Coroutine[Any, Any, T], *, timeout_s: float = 30.0) -> T:
        """Submit ``coro`` to the bridge loop, block, and return its result.

        Exceptions raised by the coroutine propagate unchanged to this call site — the bridge is
        transparent to failure.  A deadline miss raises :class:`BridgeTimeout` after cancelling
        the coroutine; the loop stays usable for subsequent calls.
        """

        if self._closed:
            coro.close()
            raise BridgeClosed("the async bridge is closed; its loop no longer runs")
        if threading.get_ident() == self._thread.ident:
            # Blocking the loop thread on a coroutine that only the loop thread could advance
            # is a deadlock with a friendly face.  Refuse it where the mistake was made.
            coro.close()
            raise RuntimeError("bridge re-entered")

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout_s)
        except TimeoutError:
            if future.done():
                # `concurrent.futures.TimeoutError` IS the builtin `TimeoutError`, so the work's
                # own TimeoutError lands here too.  A settled future means the coroutine raised
                # it — not us — so it travels on unchanged.
                raise
            # Cancellation is a request, not a guarantee: a coroutine already past its last
            # suspension point keeps running to completion on the loop.  That is fine — it runs
            # concurrently with whatever is submitted next, and its result is simply dropped.
            future.cancel()
            raise BridgeTimeout(f"bridge call exceeded timeout_s={timeout_s}") from None

    def close(self) -> None:
        """Stop the loop and join its thread.  Idempotent, and safe to call from atexit."""

        with self._close_lock:
            if self._closed:
                return
            self._closed = True

        self._loop.call_soon_threadsafe(self._loop.stop)
        if threading.get_ident() != self._thread.ident:
            self._thread.join(timeout=_JOIN_TIMEOUT_S)
            if not self._thread.is_alive():
                self._loop.close()


_bridge: AsyncBridge | None = None
_bridge_lock = threading.Lock()


def process_bridge() -> AsyncBridge:
    """The one bridge this process shares, created on first use.

    A per-call bridge would mean a thread and a loop (and, for its users, a connection pool) per
    call — so the loop is a singleton, exactly like the resources that will be built on it.
    """

    global _bridge
    with _bridge_lock:
        if _bridge is None:
            _bridge = AsyncBridge()
        return _bridge


def _close_process_bridge() -> None:
    """Shut the singleton down at interpreter exit, if it was ever created."""

    global _bridge
    with _bridge_lock:
        bridge, _bridge = _bridge, None
    if bridge is not None:
        bridge.close()


# Registered once at import, rather than at each creation, so the hook cannot accumulate.  It is
# a no-op when `process_bridge()` was never called.
atexit.register(_close_process_bridge)
