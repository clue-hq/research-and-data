"""Production ``__main__`` for the detached PB-B1 fleet worker (``python -m clue_api.fleet_main``).

The worker deployment's process entrypoint (harness build step 0, treaty §3.4 — the composition
the fleet lane deliberately did not commit). Composition-only, no logic: open the process-wide
DB engine + Redis client, build the durable-backed ``RunDriver`` and the
:class:`~clue_fleet.ProjectRunWorker` from :class:`~clue_config.Settings` (all ``CLUE_FLEET_*``
knobs), then hand off to :func:`~clue_fleet.run_worker` (the shell that owns SIGTERM/SIGINT →
graceful drain). Structured logging via :func:`clue_obs.setup`.

The worker never composes phase handlers — it drives the injected ``CampaignRun`` seam, whose
handlers are registered elsewhere. The DEEP handler in particular is **campaign-scoped** (one
``ICPSpec``) and is registered per ``(client, icp)`` at run start, over the fleet
:func:`~clue_api.fleet_wiring.build_fleet_deep_scheduler` drain
(``register_deep_phase_handler(scheduler=…, lock_factory=build_account_lock_factory())``) — exactly
as the in-process path already registers it at run start (see
``clue_api.deep.composition``). This entrypoint owns the *process shell*; the per-run handler
registration is the enqueuing app's job (and the B4 toolbelt's, when it lands).
"""

from __future__ import annotations

import asyncio

from clue_api.fleet_wiring import build_fleet_run_driver, build_fleet_worker
from clue_config import load_settings
from clue_db import db_lifespan
from clue_fleet import run_worker
from clue_locks import redis_lifespan
from clue_obs import setup


async def _serve() -> None:
    """Open the process-wide DB + Redis lifecycles and drive the worker until a graceful stop."""
    settings = load_settings()
    async with db_lifespan(), redis_lifespan():
        driver = build_fleet_run_driver()
        worker = build_fleet_worker(settings, driver=driver)
        await run_worker(worker)


def main() -> None:
    """Configure logging and run the worker event loop (the ``python -m`` entrypoint)."""
    setup()
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
