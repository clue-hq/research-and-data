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

from typing import Any

from clue_fleet.enums import FleetTaskKind
from clue_fleet.work_worker import WorkHandler
from clue_obs import get_logger

log = get_logger("clue_api.design_fleet")


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
    "build_design_job_handler",
    "start_design_event_pruner",
    "start_design_reaper",
]
