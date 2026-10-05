"""The worker-process shell (PB-B1) — run a :class:`~clue_fleet.worker.ProjectRunWorker` as a
detached OS process with signal-driven graceful drain.

This is the *shell only*: it owns the event-loop entry and SIGTERM/SIGINT → :meth:`stop` wiring.
Composition — which :class:`~clue_fleet.worker.RunDriver` the worker drives, with which phase
handlers, ledger, and budget engine — is injected by the caller: the production ``__main__``
lands with the ``clue_api`` wiring commit at integration (treaty §3.4); the exit-gate test
composes its own stub-handler harness process.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol


class RunnableWorker(Protocol):
    def stop(self) -> None: ...

    async def run(self) -> None: ...


_DRAIN_SIGNALS = (signal.SIGTERM, signal.SIGINT)


def install_thread_pool(loop: asyncio.AbstractEventLoop, *, max_workers: int) -> None:
    """Give a worker process's loop a default thread pool sized for its blocking calls.

    Every provider call runs in ``asyncio.to_thread``, and so does the loop's own DNS lookup for a
    fresh database connection — the lease heartbeat's included. The default pool is
    ``min(32, cpu + 4)`` threads; a few research jobs, each allowed several provider calls at once
    and some held for minutes, fill it, and the heartbeat then waits behind them (2026-10-05).
    Threads are started only as calls need them, so an idle worker costs nothing.
    """
    loop.set_default_executor(
        ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="clue-fleet")
    )


async def run_worker(worker: RunnableWorker, *, install_signal_handlers: bool = True) -> None:
    """Drive ``worker.run()`` to completion, draining gracefully on SIGTERM/SIGINT.

    A second signal does not escalate — kill -9 is the unclean path the lease/queue staleness
    machinery exists for; there is nothing for the process to do about it."""
    if install_signal_handlers:
        loop = asyncio.get_running_loop()
        for sig in _DRAIN_SIGNALS:
            # Not every environment allows loop signal handlers (e.g. non-main threads in
            # tests) — the worker is still stoppable via worker.stop().
            with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                loop.add_signal_handler(sig, worker.stop)
    await worker.run()
