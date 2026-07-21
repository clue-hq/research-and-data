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

from clue_fleet.worker import ProjectRunWorker

_DRAIN_SIGNALS = (signal.SIGTERM, signal.SIGINT)


async def run_worker(worker: ProjectRunWorker, *, install_signal_handlers: bool = True) -> None:
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
