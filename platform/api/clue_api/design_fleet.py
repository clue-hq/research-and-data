"""Design-job registration for the detached fleet worker (Part II slice D5 Round B — R-D5-B2).

A thin composition seam and nothing else. The design turn handler itself lives in
``lumen_api.fleet_handler``, next to the harnesses and by-value resolvers it drives, because
executing a turn needs ``lumen_agent`` and ``lumen_api.main`` — neither of which the platform
composition root has any business importing directly, and neither of which may import
``clue_api`` back (Rule 5: nothing imports the app layer).

So the direction is: ``clue_api.design_fleet`` -> ``lumen_api.fleet_handler``. Legal by
construction — the composition root is the one package allowed to import everything — and
deliberately narrow: this module knows the handler's *name*, never its internals.

The import is LAZY, inside :func:`build_design_job_handler`, for the same reason the design API
lazy-imports its own agent runtime: a platform worker deployed without the design extras must
start and drain everything else, not die at module load. ``settings.design_runtime_enabled``
is the production gate (the ``entity_research_runtime_enabled`` precedent); an unavailable
import behind an ENABLED switch is a hard, loud failure, because that combination means an
operator asked for design work and the deployment cannot do it.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from clue_db import transaction
from clue_fleet import (
    LeaseGeneration,
    WorkId,
    acquire_work_lease,
    release_work_lease,
)
from clue_fleet.enums import FleetTaskKind
from clue_fleet.work_worker import WorkContext, WorkHandler
from clue_obs import get_logger

log = get_logger("clue_api.design_fleet")

#: The worker identity the inline design-leg lane holds its work lease under.
_DESIGN_LEG_LANE_WORKER_ID = "design-leg-inline-lane"


class DesignRuntimeUnavailable(RuntimeError):
    """``design_runtime_enabled`` is on but the design app is not importable in this process."""


def build_design_job_handler(*, enabled: bool) -> WorkHandler | None:
    """The ``design_job`` handler for :func:`build_multi_work_worker`, or ``None`` when off.

    Returned handlers carry ``kind == FleetTaskKind.DESIGN_JOB``; the worker builder re-checks
    that, so a wiring mistake fails at construction rather than at claim time.
    """
    if not enabled:
        return None
    try:
        from lumen_api.fleet_handler import build_design_job_handler as _build
    except Exception as error:  # pragma: no cover - deployment shape, not logic
        raise DesignRuntimeUnavailable(
            "design_runtime_enabled is set but lumen_api.fleet_handler cannot be imported; "
            "install the design app (subsystems/clue-design/apps/{api,agent_runtime}) or "
            "unset CLUE_DESIGN_RUNTIME_ENABLED"
        ) from error
    handler: Any = _build()
    if handler.kind is not FleetTaskKind.DESIGN_JOB:
        raise DesignRuntimeUnavailable("the design handler does not own design_job tasks")
    log.info("design_fleet.handler_registered", kind=FleetTaskKind.DESIGN_JOB.value)
    return handler  # type: ignore[no-any-return]


class InlineDesignLaneDriver:
    """Drive one design-leg turn through the design fleet handler, inline, under a real lease.

    P3.4's execution seam (PD-part3 D3). The design turn still runs on the design lane in every
    sense that matters — the same :class:`~lumen_api.fleet_handler.DesignJobWorkHandler`, the
    same claim CAS, the same generation fences, the same run-event stream — but it is *driven by
    the agent-turn worker* instead of queued as a second fleet task. The platform fleet drains
    one task at a time per worker, so an ``AGENT_TURN`` handler that enqueued a ``design_job``
    and awaited it would deadlock a single-worker deployment against itself; holding the design
    work lease and calling the handler directly keeps single-flight, stop and fencing semantics
    without that hazard.
    """

    def __init__(self, *, handler: WorkHandler) -> None:
        self._handler = handler

    async def drive(self, *, envelope: Any) -> None:
        work_id = WorkId(envelope.work_id)
        async with transaction() as conn:
            lease = await acquire_work_lease(
                conn,
                work_id=work_id,
                worker_id=_DESIGN_LEG_LANE_WORKER_ID,
            )
        if lease is None:
            raise RuntimeError("this design-leg run is owned by another live worker")
        try:
            context = WorkContext(
                task_id=uuid4(),
                work_id=work_id,
                worker_id=_DESIGN_LEG_LANE_WORKER_ID,
                lease_generation=LeaseGeneration(lease.generation),
                payload=envelope.model_dump(mode="json"),
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )
            result = await self._handler.handle(context)
            log.info(
                "design_leg.lane_drive_finished",
                work_id=str(work_id),
                outcome=result.outcome,
            )
        finally:
            async with transaction() as conn:
                await release_work_lease(
                    conn,
                    work_id=work_id,
                    worker_id=_DESIGN_LEG_LANE_WORKER_ID,
                    generation=LeaseGeneration(lease.generation),
                )


def build_design_leg_lane_driver(*, enabled: bool) -> InlineDesignLaneDriver | None:
    """The design-leg lane for :func:`build_agent_turn_work_handler`, or ``None`` when off.

    Same switch, same lazy import, same fail-loud stance as :func:`build_design_job_handler` —
    a deployment that drains design work can also drive a leg's design turns; one that does not
    must refuse loudly rather than wedge the leg (the ``None`` composes the runner's
    unavailable-lane backstop).
    """
    handler = build_design_job_handler(enabled=enabled)
    if handler is None:
        return None
    return InlineDesignLaneDriver(handler=handler)


def start_design_reaper(*, enabled: bool, interval_s: float) -> Any:
    """Start the D5 Round C stranded-design-work reaper, or ``None`` when off.

    Same seam, same laziness and same switch as :func:`build_design_job_handler` — the reaper
    lives in ``lumen_api.fleet_reaper`` because judging a stranded design row means reading the
    design DAL, which the composition root does not otherwise touch. It is gated on the SAME
    ``design_runtime_enabled`` switch as the handler on purpose: a deployment that does not drain
    design work has no business re-offering it either.

    Must be called with a running event loop. Returns the task so the caller can cancel it on
    drain (``lumen_api.fleet_reaper.stop_reaper``).
    """
    if not enabled:
        return None
    try:
        from lumen_api.fleet_reaper import start_reaper
    except Exception as error:  # pragma: no cover - deployment shape, not logic
        raise DesignRuntimeUnavailable(
            "design_runtime_enabled is set but lumen_api.fleet_reaper cannot be imported; "
            "install the design app (subsystems/clue-design/apps/{api,agent_runtime}) or "
            "unset CLUE_DESIGN_RUNTIME_ENABLED"
        ) from error
    return start_reaper(interval_s=interval_s)


def start_design_event_pruner(*, interval_s: float, retention_s: float) -> Any:
    """Start the D8 design run-event pruner, or ``None`` when off (``interval_s <= 0``).

    Same lazy seam as the two above and, deliberately, a DIFFERENT switch. The handler and the
    reaper are gated on ``design_runtime_enabled`` because both act on work — a deployment that
    does not drain design turns must not claim or re-offer them. Retention is not work: it is a
    substrate property of a shared table, and it is governed by its own interval knob
    (``design_run_event_prune_interval_s``, **default 0 = disabled**), which is the founder-facing
    switch for the one sweep in the platform that destroys durable run-visibility history.

    Because that default is off, a platform worker without the design app installed never reaches
    the import; a deployment that turns the sweep on and cannot import the design app fails loudly,
    exactly as an enabled-but-unavailable handler does.

    The retention floor is applied inside ``lumen_api.event_pruner`` (never here), so every entry
    point into the pruner gets it. Must be called with a running event loop.
    """
    if interval_s <= 0:
        return None
    try:
        from lumen_api.event_pruner import start_pruner
    except Exception as error:  # pragma: no cover - deployment shape, not logic
        raise DesignRuntimeUnavailable(
            "design_run_event_prune_interval_s is set but lumen_api.event_pruner cannot be "
            "imported; install the design app (subsystems/clue-design/apps/{api,agent_runtime}) "
            "or unset CLUE_DESIGN_RUN_EVENT_PRUNE_INTERVAL_S"
        ) from error
    return start_pruner(interval_s=interval_s, retention_s=retention_s)


__all__ = [
    "DesignRuntimeUnavailable",
    "InlineDesignLaneDriver",
    "build_design_job_handler",
    "build_design_leg_lane_driver",
    "start_design_event_pruner",
    "start_design_reaper",
]
