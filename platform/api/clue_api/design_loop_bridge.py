"""One rule for calling the platform from a design worker thread.

The design runtime runs its turn synchronously on a worker thread while the platform owns the
event loop and the connection pool. Anything the design side needs from the platform mid-turn
therefore runs as a coroutine ON the platform loop, with the worker thread blocked for a bounded
wait. First written for the scoped-preference resolver (``design_memory_runtime``); the account
reads (``design_platform_reads``) use the same bridge, so there is exactly one place that knows
the four ways this can go wrong.

The four are named, not described: ``platform_loop`` (the caller is ON the loop it wants to block
for — a deadlock, refused before it happens), ``loop_unavailable`` (the loop is closed or not
running), ``timeout`` (the platform did not answer inside the bound), and whatever the operation
itself raised, which is the caller's to classify. The exception TYPE is the caller's too: each
surface keeps its own error class and its own code spelling by handing in ``error``.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Coroutine
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, TypeVar

_T = TypeVar("_T")


class PlatformLoopBridge:
    """Run a coroutine on the captured platform loop and block the calling thread for it."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        timeout_s: float = 10.0,
        error: Callable[[str], Exception] = RuntimeError,
    ) -> None:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("platform_loop_timeout_must_be_positive")
        self._loop = loop if loop is not None else asyncio.get_running_loop()
        self._timeout_s = timeout_s
        self._error = error

    def wait(self, operation: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
        """Block until ``operation`` answers on the platform loop, or raise one of the four.

        ``operation`` is a *factory*, not a coroutine: a coroutine built before the liveness checks
        would be an un-awaited coroutine whenever a check refuses, which is a warning and a leak
        rather than a clean refusal.
        """

        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is self._loop:
            raise self._error("platform_loop")
        if self._loop.is_closed() or not self._loop.is_running():
            raise self._error("loop_unavailable")
        pending = operation()
        try:
            future = asyncio.run_coroutine_threadsafe(pending, self._loop)
        except RuntimeError:
            pending.close()
            raise self._error("loop_unavailable") from None
        try:
            return future.result(timeout=self._timeout_s)
        except FutureTimeoutError:
            future.cancel()
            raise self._error("timeout") from None


__all__ = ["PlatformLoopBridge"]
