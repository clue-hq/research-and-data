"""The design run-event pruner (design-integration Part II, slice D8 — ruling R-D8-4).

**The problem this exists for.** ``run_event`` has no FK to its subject, no CASCADE and — until
D8 — no sweep. Design payloads are markedly heavier than project-run ones (a ``dsl_compiled``
progress event carries the compile's whole applied-``operations`` array) and a chatty turn emits
dozens, so the design half of the outbox is the only half that grows without bound.

**Why this is the one destructive sweep in the platform, and how it is contained.** Everything
else D8 deletes is provably unreadable first (a spent ``stream_token`` cannot be consumed by any
code path). This one is different: it removes durable history a client *could* still have asked
for. So it is the only sweep in the repo that is **disabled by default**
(``Settings.design_run_event_prune_interval_s = 0``) and the only one whose safety properties are
written as floors in code rather than as configuration.

THE FLOORS
----------
Five, none of them configurable. Each one is enforced at the site named, not by this docstring:

1. **Only design progress rows.** The delete filters ``subject_kind = 'design_run'`` AND
   ``topic = 'design.run.event'`` as SQL literals
   (``clue_execution.run_events.prune_design_run_progress_events``). A ``project_run`` subject is
   unreachable from here, so the platform stream's reset-then-backlog completeness — the standing
   [B4×SSE] question — is untouched by construction, not by promise.
2. **A terminal row is never deleted, and one must survive.** The two terminal topics are outside
   the delete's topic filter, and the statement additionally *requires* a surviving terminal row
   (an ``EXISTS``), so a subject with no terminal event is skipped whole. This is the hard
   constraint D8 inherited when it removed the SSE loop's idle liveness net: the terminal event is
   now the ONLY thing that closes a subscriber's stream (``lumen_api.run_stream``), so a sweep that
   could remove one would silently reintroduce hang-forever streams.
3. **Only terminal runs.** Eligibility comes from ``clue_design.runs.list_prunable_terminal_runs``,
   which returns only ``succeeded``/``failed`` rows. A ``running`` run's stream is still being
   written; age is irrelevant.
4. **Retention strictly exceeds the replay horizon.** :data:`RETENTION_FLOOR_SECONDS` is 7 days;
   the design stream's ``REPLAY_HORIZON_SECONDS`` is 24 hours. A configured retention below the
   floor is **clamped up** and logged — never honoured. That inequality is what makes the
   [B4×SSE] answer true for the design stream too: a cursor young enough to be replayed gaplessly
   points at a run far too young to prune, and a cursor older than the horizon is reset to 0
   anyway, where the surviving terminal row still closes the stream correctly.
5. **Prefix-only deletion.** A design run's terminal event is its last durable write, so removing
   every progress row of a terminal run removes a contiguous *prefix* of that subject's seq range.
   No mid-range hole is ever created — a reader sees progress-then-terminal, or terminal-only.

WHAT AN OPERATOR LOSES WHEN THIS IS ON
--------------------------------------
The run-snapshot endpoint (``GET /agent/runs/{id}``) replays that run's whole stream from seq 0.
After a pruning pass, an *old, finished* run's snapshot returns its terminal event only — the
progress trail is gone. That is accepted by ruling for a default-OFF sweep scoped to runs that
finished at least a week ago; the run row itself, with its full ``result_json``, is untouched.

WHERE IT RUNS
-------------
``clue_api.fleet_main`` starts it beside the D5 Round C reaper and the B2 orphan-blob sweep, whose
loop shape this file copies exactly (config-gated interval, ``<= 0`` disables, one transaction per
pass, a pass fault logged and never fatal). The S4 split is the reaper's: the *design* half — which
runs are terminal and how long they have been — is a ``clue_design`` DAL read; the *outbox* half —
the row deletion — is a ``clue_execution`` DAL write; this module is where the two meet, because it
is the composition root and neither substrate may import the other.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, List, Optional

from clue_design import runs as design_runs
from clue_execution.run_events import prune_design_run_progress_events
from py_lumen_obs import get_logger

from .run_stream import REPLAY_HORIZON_SECONDS

logger = get_logger("lumen_api.event_pruner")

#: The hard retention floor: a design run's progress events survive at least this long after the
#: run finished, whatever the configuration says. Seven days, chosen to STRICTLY exceed the design
#: stream's 24h ``REPLAY_HORIZON_SECONDS`` by a wide margin — the inequality is the property
#: (a within-horizon cursor can never point into a pruned run), the margin is the safety.
RETENTION_FLOOR_SECONDS = 7 * 86_400.0

#: Runs examined in one pass. A large backlog drains over several passes rather than in one long
#: transaction; the scan is oldest-first, so every pass makes progress.
DEFAULT_SCAN_LIMIT = 500


@dataclass(frozen=True)
class PrunerSweep:
    """What one pass did — returned so the loop can log it and tests can assert on it.

    Shaped after ``fleet_reaper.ReaperSweep`` deliberately: the two sweeps run side by side in the
    same worker and an operator should not have to learn two summary vocabularies.
    """

    considered: int = 0
    pruned_runs: int = 0
    deleted_events: int = 0
    skipped_no_terminal_event: int = 0

    @property
    def acted(self) -> int:
        return self.deleted_events


def effective_retention_s(configured_s: float) -> float:
    """The retention actually applied: ``max(configured, RETENTION_FLOOR_SECONDS)``.

    Clamped UP with a loud warning rather than refused, because refusing would mean a deployment
    that mis-set one number silently stops reclaiming anything, and clamping is the conservative
    direction — it deletes strictly *less*. A configuration below the floor is a mistake, never an
    override: the floor is what keeps the replay horizon inside the retained window.
    """
    if configured_s < RETENTION_FLOOR_SECONDS:
        logger.warning(
            "design_event_pruner.retention_clamped",
            configured_s=configured_s,
            applied_s=RETENTION_FLOOR_SECONDS,
            replay_horizon_s=REPLAY_HORIZON_SECONDS,
            detail=(
                "configured retention is below the hard floor; the floor is applied instead so "
                "retention keeps strictly exceeding the design stream's replay horizon"
            ),
        )
        return RETENTION_FLOOR_SECONDS
    return configured_s


async def prune_design_run_events(
    conn: Any, *, retention_s: float, limit: int = DEFAULT_SCAN_LIMIT
) -> PrunerSweep:
    """One pass: for every long-finished design run, drop its progress events. Idempotent.

    ``retention_s`` is passed through :func:`effective_retention_s` here rather than at the caller,
    so *every* entry point — the loop, a test, an operator's one-off — gets the floor. A second
    immediate pass deletes nothing: the runs are still eligible, but their progress rows are gone.
    """
    applied_s = effective_retention_s(retention_s)
    considered = pruned_runs = deleted_events = skipped = 0
    for row in await design_runs.list_prunable_terminal_runs(
        conn, terminal_before_s=applied_s, limit=limit
    ):
        considered += 1
        deleted = await prune_design_run_progress_events(
            conn, workspace_id=row["workspace_id"], subject_id=row["run_id"]
        )
        if deleted == 0:
            # Either already pruned (the idempotent case, by far the common one) or the subject
            # carries no terminal row and the DAL's EXISTS refused the delete whole. The second is
            # the interesting one — a terminal run whose terminal event never landed, or one that
            # finished before the D7 outbox existed — and it is left ALONE on purpose.
            skipped += 1
            continue
        pruned_runs += 1
        deleted_events += deleted
    return PrunerSweep(
        considered=considered,
        pruned_runs=pruned_runs,
        deleted_events=deleted_events,
        skipped_no_terminal_event=skipped,
    )


async def run_pruner_pass(
    conn_factory: Callable[[], Any],
    *,
    retention_s: float,
    limit: int = DEFAULT_SCAN_LIMIT,
) -> PrunerSweep:
    """One pass in ONE transaction — the eligibility read and its deletes commit together."""
    async with conn_factory() as conn:
        return await prune_design_run_events(conn, retention_s=retention_s, limit=limit)


async def pruner_loop(
    *,
    interval_s: float,
    retention_s: float,
    conn_factory: Optional[Callable[[], Any]] = None,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> None:
    """Prune every ``interval_s`` seconds until cancelled. Copies ``fleet_reaper.reaper_loop``.

    Every pass is fully isolated: a fault is logged and the loop continues. A retention sweep that
    could sink its host worker would trade "the outbox grows" for "no work is drained at all".
    """
    if conn_factory is None:
        from clue_db import transaction

        conn_factory = transaction
    while True:
        await sleep(interval_s)
        try:
            sweep = await run_pruner_pass(conn_factory, retention_s=retention_s)
            if sweep.acted:
                logger.info(
                    "design_event_pruner.swept",
                    considered=sweep.considered,
                    pruned_runs=sweep.pruned_runs,
                    deleted_events=sweep.deleted_events,
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a pruner fault must never sink its host
            logger.warning("design_event_pruner.error", exc_info=True)


def start_pruner(*, interval_s: float, retention_s: float) -> Optional["asyncio.Task[None]"]:
    """Start the background pruner, or ``None`` when disabled (``interval_s <= 0``).

    Disabled is the DEFAULT and the founder-facing switch: this is the one sweep that destroys
    durable run-visibility history, so a deployment gets it only by asking for it. Must be called
    with a running event loop. Mirrors ``fleet_reaper.start_reaper``, including the
    disabled-by-non-positive-interval convention.
    """
    if interval_s <= 0:
        logger.info("design_event_pruner.disabled")
        return None
    applied_s = effective_retention_s(retention_s)
    logger.warning(
        "design_event_pruner.started",
        interval_s=interval_s,
        retention_s=applied_s,
        retention_floor_s=RETENTION_FLOOR_SECONDS,
        replay_horizon_s=REPLAY_HORIZON_SECONDS,
        detail=(
            "progress events of long-finished design runs will be deleted; "
            "terminal events are never pruned"
        ),
    )
    return asyncio.create_task(pruner_loop(interval_s=interval_s, retention_s=applied_s))


async def stop_pruner(task: Optional["asyncio.Task[None]"]) -> None:
    """Cancel and await a started pruner (no-op for ``None``)."""
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


__all__: List[str] = [
    "DEFAULT_SCAN_LIMIT",
    "RETENTION_FLOOR_SECONDS",
    "PrunerSweep",
    "effective_retention_s",
    "prune_design_run_events",
    "pruner_loop",
    "run_pruner_pass",
    "start_pruner",
    "stop_pruner",
]
