"""The stranded-design-work reaper (design-integration Part II, slice D5 Round C).

**The invariant this exists to hold: no design row may sit ``running`` forever.**

D5's in-handler containment covers almost everything — a failed turn lands ``failed``, a fenced
zombie's write is refused, and since Round C a handler EXCEPTION terminalizes the row before the
task is reported. What none of that covers is the case where the containment write itself cannot
land: the process is SIGKILLed between the claim and the terminal write, or the database is
unreachable for exactly as long as it takes for the worker to give up. Then the fleet task ends
FAILED (or is simply gone) while the design row stays ``running``, and nothing re-offers it. That
row is stranded: the editor's SSE stream never settles, the job list shows work that is not
happening, and no amount of restarting helps.

THE POLICY, AS SHIPPED: **re-offer once, then fail.**

A ``running`` design row whose fleet task is terminal (or absent) and which holds no live lease is
stranded. The first time the reaper sees such a row it hands it back — ``running`` → ``queued``,
lease cleared, ``reoffer_count`` incremented, and the same ``design_job`` task re-enqueued from
the row's own frozen envelope, all in ONE transaction. A worker then claims it and re-executes it
through the ordinary path (for a turn that is the checkpoint-RESTART branch, per
``lumen_agent.checkpoint``: the envelope is unchanged, so it replays the same unit of work). The
SECOND time — the re-offer was used and the row is stranded again — the reaper terminalizes it
``failed`` with a ``design.stranded`` error code.

Why exactly once, rather than N times or never:

* **Never** (terminalize immediately) throws away recoverable work for what is usually a
  transient fault, and the whole point of moving design onto the fleet was that a dead worker no
  longer kills a turn.
* **N times** turns a poison job — one that reliably kills its worker — into an infinite,
  expensive retry loop across the whole fleet. One retry distinguishes "the machine died" from
  "this work kills machines" and costs at most one extra execution.

The counter is a DURABLE column (``design_agent_run.reoffer_count`` /
``design_ingestion_job.reoffer_count``) rather than reaper memory, because a process-local memory
of "I already retried this" dies with exactly the kind of process death that caused the strand.

THE S4 BOUNDARY
---------------
``clue_design`` may not learn that ``clue_fleet`` exists. So the *design* half — find ``running``
rows, hand one back to ``queued``, terminalize one ``failed`` — is three DAL functions that read
and write the design row only, and the *fleet* half — what state is this work id's task in, does
a live lease still cover it — is read HERE and passed IN as a decision. The design substrate never
sees a task or a lease; this module is where the two planes meet, exactly as the handler is.

WHERE IT RUNS
-------------
Both deployments, one implementation: ``clue_api.fleet_main`` starts it beside the B2 orphan-blob
sweep (the pattern this loop copies), and the design API's lifespan starts it beside its embedded
worker for development. Every pass is fully isolated — a reaper fault is logged and the loop
continues, because a sweep must never sink the worker it rides on.

WHAT IT DELIBERATELY DOES NOT TOUCH
-----------------------------------
* A row whose work id still holds a **live** lease. It is being driven right now.
* A row whose task is ``queued`` or ``claimed``. It is on its way to a worker; re-offering would
  duplicate the work and racing the claimant would fight the CAS.
* An ingestion job with no ``work_id`` — never dispatched to the fleet, so there is no task to
  judge it against (a direct/CLI run owns its own lifecycle).
* Anything terminal. Every write below is guarded on ``status = 'running'``, so a row that
  finished between the reaper's read and its write keeps its real outcome.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional
from uuid import UUID

from clue_core import ProjectRunId
from clue_design import ingestion as design_ingestion
from clue_design import runs as design_runs
from clue_design.site_turn_workspace import prune_expired_site_turn_checkpoints
from clue_fleet.enums import FleetTaskKind, FleetTaskStatus
from clue_fleet.lease import WorkId, get_work_lease
from clue_fleet.queue import enqueue_task
from py_lumen_obs import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from . import run_stream

JsonObject = Dict[str, Any]

logger = get_logger("lumen_api.fleet_reaper")

#: The reaper's terminal error/result code. One string, asserted by the tests, so an operator
#: grepping for "why did this run fail" gets a single unambiguous answer.
STRANDED_CODE = "design.stranded"

#: The reconciliation code (R3-B). A row whose backing fleet task is terminal or gone while the
#: row itself never left ``queued`` was never *stranded* mid-execution — it was orphaned before
#: execution began — so it gets its own code rather than borrowing ``design.stranded``. An
#: operator grepping either string gets one unambiguous story about what happened.
ORPHANED_CODE = "design.task_orphaned"

#: A ``running`` row younger than this is left alone. It is not a correctness knob — every write
#: is CAS-guarded and the live-lease check is authoritative — but a grace window keeps the reaper
#: away from the narrow interval in which a worker has claimed a row and not yet landed its first
#: lease renewal, which is the one moment the queue/lease join can look momentarily inconsistent.
DEFAULT_STRANDED_AFTER_S = 120.0

#: Exactly one re-offer per row. See the module docstring for why this is 1 and not 0 or N.
MAX_REOFFERS = 1


@dataclass(frozen=True)
class ReaperSweep:
    """What one pass did — returned so the loop can log it and tests can assert on it."""

    considered: int = 0
    skipped_live: int = 0
    skipped_queued: int = 0
    reoffered: int = 0
    failed: int = 0

    @property
    def acted(self) -> int:
        return self.reoffered + self.failed


async def _design_task_status(
    conn: AsyncConnection, work_id: UUID
) -> Optional[FleetTaskStatus]:
    """The ``design_job`` task's status for this work id, or ``None`` when there is no task.

    Read directly rather than through ``clue_fleet.queue.get_task`` because the reaper holds a
    WORK id, not a task id — the queue's by-task read cannot answer this question. ``ORDER BY
    enqueue_seq DESC LIMIT 1`` because a re-offered work id can, in principle, own more than one
    row over its life and only the newest one describes the present.
    """
    row = (
        await conn.execute(
            text(
                "SELECT status FROM fleet_task"
                " WHERE work_id = :work_id AND kind = CAST(:kind AS fleet_task_kind)"
                " ORDER BY enqueue_seq DESC LIMIT 1"
            ),
            {"work_id": work_id, "kind": FleetTaskKind.DESIGN_JOB.value},
        )
    ).first()
    return None if row is None else FleetTaskStatus(row.status)


async def _is_stranded(conn: AsyncConnection, work_id: UUID) -> Optional[str]:
    """``None`` when the row is healthy; otherwise the reason string for the log line.

    The two questions, in the order that matters: a LIVE lease means someone is driving this
    right now and the answer is "healthy" whatever the task row says (the lease is the
    authoritative fence — Rule F1); only then does the task's own state decide.
    """
    lease = await get_work_lease(conn, WorkId(work_id))
    if lease is not None and lease.live:
        return None
    status = await _design_task_status(conn, work_id)
    if status is None:
        return "task_missing"
    if status in (FleetTaskStatus.QUEUED, FleetTaskStatus.CLAIMED):
        return None
    return f"task_{status.value}"


async def _reoffer(
    conn: AsyncConnection, *, work_id: UUID, envelope: JsonObject, priority: int = 0
) -> bool:
    """Re-enqueue the design task for a row the DAL has just handed back to ``queued``.

    ``reopen_terminal=True`` is required and load-bearing: the stranded row's task is DONE or
    FAILED, and the default enqueue is a pure no-op on a duplicate ``(kind, work_id, dedup_key)``
    whatever its state — so without it the row would return to ``queued`` with no task to bring a
    worker back, which is a *worse* strand than the one being repaired.

    The payload is the row's own frozen envelope, re-read from the design row rather than rebuilt:
    a re-offer must replay the SAME unit of work, and reconstructing it here would silently
    introduce a second authority for what the job is.
    """
    return await enqueue_task(
        conn,
        kind=FleetTaskKind.DESIGN_JOB,
        project_run_id=ProjectRunId(work_id),  # the fleet's compatibility spelling of work_id
        dedup_key=str(work_id),
        payload=envelope,
        priority=priority,
        reopen_terminal=True,
    )


async def reconcile_dispatched_failure(
    conn: AsyncConnection,
    *,
    work_id: UUID,
    code: str,
    message: str,
    lease_generation: Optional[int] = None,
) -> str:
    """Fail the design row behind ``work_id`` — the ONE reconciliation both callers use (R3-B).

    Two callers, one policy: the fleet handler's preamble containment (synchronous — the worker
    that could not run the job says so immediately, under its own lease generation) and the
    orphan sweeps below (after the fact, judging by task state instead of by a generation).

    It lives here, beside the reaper's other design↔fleet joins, because it *is* one: reading a
    work id and terminalizing whichever design row owns it needs both DAL twins and — for a run
    — the terminal stream event, and the handler has no business learning the stream's contract
    to say "this job died".

    The returned string is the honest outcome, never a bool:

    * ``job_failed`` / ``run_failed`` — the row was terminalized with ``code``.
    * ``job_refused`` / ``run_refused`` — a row exists but the write was refused: it is already
      terminal (its real outcome stands) or a newer lease generation owns it (a capable takeover
      is running it). Both are correct non-actions.
    * ``unknown_work`` — no design row carries this work id. A poison task; there is nothing to
      reconcile and nothing is invented.
    """
    error: JsonObject = {"code": code, "message": message}
    job = await design_ingestion.fail_dispatched_job(
        conn, work_id=work_id, error=error, lease_generation=lease_generation
    )
    if job is not None:
        logger.error(
            "design_reaper.job_reconciled",
            job_id=job["job_id"],
            work_id=str(work_id),
            workspace_id=job["workspace_id"],
            code=code,
        )
        return "job_failed"

    run = await design_runs.fail_dispatched_run(
        conn,
        work_id=work_id,
        result={"schema_version": 1, "status": "failed", "error": error},
        lease_generation=lease_generation,
    )
    if run is not None:
        # Same transaction as the result, exactly as the stranded path does it: the editor's SSE
        # stream settles on the event, so a terminal row with no event is a stream that hangs on
        # a finished run forever.
        await run_stream.fenced_emit(
            conn,
            workspace_id=run["workspace_id"],
            run_id=run["run_id"],
            topic=run_stream.FAILED_TOPIC,
            payload=run_stream.terminal_payload(
                "error", {"message": f"{code}: {message}"}, run["result"]
            ),
        )
        logger.error(
            "design_reaper.run_reconciled",
            run_id=run["run_id"],
            work_id=str(work_id),
            workspace_id=run["workspace_id"],
            code=code,
        )
        return "run_failed"

    if await design_ingestion.get_job_by_work_id(conn, work_id=work_id) is not None:
        return "job_refused"
    if await design_runs.get_run_by_work_id(conn, work_id=work_id) is not None:
        return "run_refused"
    return "unknown_work"


async def _orphan_reason(conn: AsyncConnection, work_id: UUID) -> Optional[str]:
    """Why this still-``queued`` row is orphaned, or ``None`` when it is simply waiting.

    Deliberately the same judgement as :func:`_is_stranded` — a live lease means someone is
    driving; a ``queued``/``claimed`` task means a worker is still coming; anything else means
    the task that was supposed to bring one is terminal or gone. Only the REMEDY differs, and it
    differs on purpose: a stranded ``running`` row is re-offered once because its work was
    interrupted mid-flight and may well complete on a retry, whereas an orphaned ``queued`` row's
    task was already claimed and terminalized by a worker that decided it could not run it. A
    re-offer would hand the same payload to the same fleet for the same verdict; the honest
    answer is a failed job with a message that names the reconciliation.
    """
    return await _is_stranded(conn, work_id)


async def sweep_orphaned_jobs(
    conn: AsyncConnection, *, stranded_after_s: float = DEFAULT_STRANDED_AFTER_S
) -> ReaperSweep:
    """Fail every dispatched ingestion job left ``queued`` behind a dead task (R3-B).

    The backstop for the case the handler's synchronous containment cannot reach: a worker that
    died outright between claiming the task and reconciling, a row orphaned by a build that
    predates the containment, or an operator-cancelled task. ``reoffered`` is always 0 — see
    :func:`_orphan_reason` for why this policy fails rather than re-offers.
    """
    considered = skipped_live = skipped_queued = failed = 0
    for row in await design_ingestion.list_dispatched_queued_jobs(conn):
        if not _old_enough(row, stranded_after_s):
            continue
        considered += 1
        work_id = UUID(row["work_id"])
        reason = await _orphan_reason(conn, work_id)
        if reason is None:
            skipped_live += 1
            continue
        terminal = await design_ingestion.fail_dispatched_job(
            conn,
            work_id=work_id,
            error={
                "code": ORPHANED_CODE,
                "message": (
                    f"the ingestion job's fleet task is {reason.removeprefix('task_')} while the "
                    "job never left 'queued'; no worker is coming for it"
                ),
            },
        )
        if terminal is None:
            skipped_queued += 1
            continue
        failed += 1
        logger.error(
            "design_reaper.job_orphaned",
            job_id=row["job_id"],
            work_id=row["work_id"],
            workspace_id=row["workspace_id"],
            kind=row["kind"],
            reason=reason,
        )
    return ReaperSweep(considered, skipped_live, skipped_queued, 0, failed)


async def sweep_orphaned_runs(
    conn: AsyncConnection, *, stranded_after_s: float = DEFAULT_STRANDED_AFTER_S
) -> ReaperSweep:
    """The run twin of :func:`sweep_orphaned_jobs` — identical policy, different row."""
    considered = skipped_live = skipped_queued = failed = 0
    for row in await design_runs.list_dispatched_queued_runs(conn):
        if not _old_enough(row, stranded_after_s):
            continue
        considered += 1
        work_id = UUID(row["work_id"])
        reason = await _orphan_reason(conn, work_id)
        if reason is None:
            skipped_live += 1
            continue
        message = (
            f"the design run's fleet task is {reason.removeprefix('task_')} while the run never "
            "left 'queued'; no worker is coming for it"
        )
        terminal = await design_runs.fail_dispatched_run(
            conn,
            work_id=work_id,
            result={
                "schema_version": 1,
                "status": "failed",
                "error": {"code": ORPHANED_CODE, "message": message},
            },
        )
        if terminal is None:
            skipped_queued += 1
            continue
        await run_stream.fenced_emit(
            conn,
            workspace_id=row["workspace_id"],
            run_id=row["run_id"],
            topic=run_stream.FAILED_TOPIC,
            payload=run_stream.terminal_payload(
                "error", {"message": f"{ORPHANED_CODE}: {message}"}, terminal["result"]
            ),
        )
        failed += 1
        logger.error(
            "design_reaper.run_orphaned",
            run_id=row["run_id"],
            work_id=row["work_id"],
            workspace_id=row["workspace_id"],
            reason=reason,
        )
    return ReaperSweep(considered, skipped_live, skipped_queued, 0, failed)


async def sweep_stranded_runs(
    conn: AsyncConnection, *, stranded_after_s: float = DEFAULT_STRANDED_AFTER_S
) -> ReaperSweep:
    """One pass over stranded design RUNS. See the module docstring for the policy."""
    considered = skipped_live = skipped_queued = reoffered = failed = 0
    for row in await design_runs.list_dispatched_running_runs(conn):
        if not _old_enough(row, stranded_after_s):
            continue
        considered += 1
        work_id = UUID(row["work_id"])
        reason = await _is_stranded(conn, work_id)
        if reason is None:
            skipped_live += 1
            continue
        if row["reoffer_count"] < MAX_REOFFERS:
            handed_back = await design_runs.reoffer_stranded_run(
                conn, work_id=work_id, max_reoffers=MAX_REOFFERS
            )
            if handed_back is None:
                # The CAS refused — the row stopped being ``running`` between the read and the
                # write. Someone finished it; nothing to do.
                skipped_queued += 1
                continue
            await _reoffer(conn, work_id=work_id, envelope=handed_back["payload"])
            reoffered += 1
            logger.warning(
                "design_reaper.run_reoffered",
                run_id=row["run_id"],
                work_id=row["work_id"],
                workspace_id=row["workspace_id"],
                reason=reason,
            )
            continue
        terminal = await design_runs.fail_stranded_run(
            conn, work_id=work_id, result=_stranded_result(reason, row["reoffer_count"])
        )
        if terminal is None:
            skipped_queued += 1
            continue
        # The terminal stream event, in the SAME transaction as the result — the contract
        # ``run_stream.complete_run_and_emit`` holds for the worker path (result committed before
        # the event that announces it) must hold for the reaper's terminal write too, or the
        # editor's SSE stream would sit on a finished run forever waiting for an event that never
        # came. D7: it is a ``design.run.failed`` on the platform outbox now, and it carries the
        # stranded result envelope IN its payload — so the stream serves the reaper's ``done``
        # frame from the event alone, with no read-back of the run row.
        await run_stream.fenced_emit(
            conn,
            workspace_id=row["workspace_id"],
            run_id=row["run_id"],
            topic=run_stream.FAILED_TOPIC,
            payload=run_stream.terminal_payload(
                "error", {"message": f"{STRANDED_CODE}: {reason}"}, terminal["result"]
            ),
        )
        failed += 1
        logger.error(
            "design_reaper.run_stranded",
            run_id=row["run_id"],
            work_id=row["work_id"],
            workspace_id=row["workspace_id"],
            reason=reason,
            reoffer_count=row["reoffer_count"],
        )
    return ReaperSweep(considered, skipped_live, skipped_queued, reoffered, failed)


async def sweep_stranded_jobs(
    conn: AsyncConnection, *, stranded_after_s: float = DEFAULT_STRANDED_AFTER_S
) -> ReaperSweep:
    """One pass over stranded INGESTION jobs — identical policy, different row."""
    considered = skipped_live = skipped_queued = reoffered = failed = 0
    for row in await design_ingestion.list_dispatched_running_jobs(conn):
        if not _old_enough(row, stranded_after_s):
            continue
        considered += 1
        work_id = UUID(row["work_id"])
        reason = await _is_stranded(conn, work_id)
        if reason is None:
            skipped_live += 1
            continue
        if row["reoffer_count"] < MAX_REOFFERS:
            handed_back = await design_ingestion.reoffer_stranded_job(
                conn, work_id=work_id, max_reoffers=MAX_REOFFERS
            )
            if handed_back is None:
                skipped_queued += 1
                continue
            # An ingestion job's envelope is not stored on its row (its durable authority is
            # ``request_json``, which the worker re-reads), so it is rebuilt from the row's own
            # columns — the same three fields the route minted it from, and all of them
            # immutable since.
            await _reoffer(
                conn,
                work_id=work_id,
                envelope={
                    "work_id": row["work_id"],
                    "workspace_id": row["workspace_id"],
                    "config": {},
                    "kind": "ingestion",
                    "job_id": row["job_id"],
                    "ingestion_kind": row["kind"],
                },
            )
            reoffered += 1
            logger.warning(
                "design_reaper.job_reoffered",
                job_id=row["job_id"],
                work_id=row["work_id"],
                workspace_id=row["workspace_id"],
                reason=reason,
            )
            continue
        terminal = await design_ingestion.fail_stranded_job(
            conn,
            work_id=work_id,
            error={
                "code": STRANDED_CODE,
                "message": (
                    f"ingestion job was stranded ({reason}) after "
                    f"{row['reoffer_count']} re-offer(s)"
                ),
            },
        )
        if terminal is None:
            skipped_queued += 1
            continue
        failed += 1
        logger.error(
            "design_reaper.job_stranded",
            job_id=row["job_id"],
            work_id=row["work_id"],
            workspace_id=row["workspace_id"],
            reason=reason,
            reoffer_count=row["reoffer_count"],
        )
    return ReaperSweep(considered, skipped_live, skipped_queued, reoffered, failed)


def _stranded_result(reason: str, reoffer_count: int) -> JsonObject:
    """The terminal ``result_json`` a stranded run gets — the shape the SSE stream already reads."""
    return {
        "schema_version": 1,
        "status": "failed",
        "error": {
            "code": STRANDED_CODE,
            "message": (
                f"design run was stranded ({reason}) after {reoffer_count} re-offer(s); "
                "its worker died without landing a terminal result"
            ),
        },
    }


def _old_enough(row: JsonObject, stranded_after_s: float) -> bool:
    """Whether the row has been untouched long enough to be judged (the grace window).

    Compares against ``updated_at``, which every claim, progress event and lease stamp bumps —
    so an actively-progressing row is never even considered, independently of the lease check.
    A row with no parseable timestamp is judged (fail-toward-inspection: the CAS-guarded writes
    below cannot damage a healthy row).
    """
    if stranded_after_s <= 0:
        return True
    raw = row.get("updated_at")
    if not isinstance(raw, str):
        return True
    try:
        seen = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - seen).total_seconds() >= stranded_after_s


async def run_reaper_pass(
    conn_factory: Callable[[], Any], *, stranded_after_s: float = DEFAULT_STRANDED_AFTER_S
) -> ReaperSweep:
    """All four sweeps in ONE transaction; the combined counts.

    One transaction because the sweeps read the same ``fleet_task`` / ``work_lease`` rows and a
    split would let a later one see a queue an earlier one had already changed. It is a short,
    read-mostly pass over indexed status predicates — not a long-held lock.

    The ``running`` sweeps go FIRST, and the order is load-bearing: a stranded ``running`` row
    may be handed back to ``queued`` by its sweep, and the orphan sweeps must not then judge
    that fresh hand-back as an orphan. They cannot — the hand-back re-enqueues the task to
    ``queued`` in the same transaction, which reads as healthy — but relying on evaluation order
    for that would be luck, so the deliberate order is stated rather than assumed.
    """
    async with conn_factory() as conn:
        sweeps = (
            await sweep_stranded_runs(conn, stranded_after_s=stranded_after_s),
            await sweep_stranded_jobs(conn, stranded_after_s=stranded_after_s),
            await sweep_orphaned_runs(conn, stranded_after_s=stranded_after_s),
            await sweep_orphaned_jobs(conn, stranded_after_s=stranded_after_s),
        )
    return ReaperSweep(
        considered=sum(sweep.considered for sweep in sweeps),
        skipped_live=sum(sweep.skipped_live for sweep in sweeps),
        skipped_queued=sum(sweep.skipped_queued for sweep in sweeps),
        reoffered=sum(sweep.reoffered for sweep in sweeps),
        failed=sum(sweep.failed for sweep in sweeps),
    )


async def reaper_loop(
    *,
    interval_s: float,
    stranded_after_s: float = DEFAULT_STRANDED_AFTER_S,
    conn_factory: Optional[Callable[[], Any]] = None,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    conversation_retention_s: Optional[float] = None,
) -> None:
    """Sweep every ``interval_s`` seconds until cancelled. Copies ``_orphan_sweep_loop`` (B2).

    Each pass also deletes the conversations of site turns that finished more than
    ``conversation_retention_s`` ago (``LUMEN_SITE_TURN_CONVERSATION_RETENTION_S``, 96 h).

    Every pass is fully isolated: a fault is logged and the loop continues. A reaper that could
    sink its host worker would trade "some rows are stranded" for "no work is drained at all".
    """
    if conn_factory is None:
        from clue_db import transaction

        conn_factory = transaction
    if conversation_retention_s is None:
        from py_lumen_config import settings

        conversation_retention_s = settings.lumen_site_turn_conversation_retention_s
    while True:
        await sleep(interval_s)
        try:
            sweep = await run_reaper_pass(conn_factory, stranded_after_s=stranded_after_s)
            if sweep.acted:
                logger.info(
                    "design_reaper.swept",
                    considered=sweep.considered,
                    reoffered=sweep.reoffered,
                    failed=sweep.failed,
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a reaper fault must never sink its host
            logger.warning("design_reaper.error", exc_info=True)
        try:
            # Its own transaction, so a fault here never undoes the sweeps above.
            async with conn_factory() as conn:
                deleted = await prune_expired_site_turn_checkpoints(
                    conn, retain_s=conversation_retention_s
                )
            if deleted:
                logger.info("design_reaper.conversations_deleted", runs=deleted)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a reaper fault must never sink its host
            logger.warning("design_reaper.conversation_prune_error", exc_info=True)


def start_reaper(
    *,
    interval_s: float,
    stranded_after_s: float = DEFAULT_STRANDED_AFTER_S,
) -> Optional["asyncio.Task[None]"]:
    """Start the background reaper task, or ``None`` when disabled (``interval_s <= 0``).

    Must be called with a running event loop. Mirrors
    ``clue_api.fleet_main._start_orphan_sweep`` exactly, including the disabled-by-non-positive
    -interval convention.
    """
    if interval_s <= 0:
        logger.info("design_reaper.disabled")
        return None
    logger.info(
        "design_reaper.started",
        interval_s=interval_s,
        stranded_after_s=stranded_after_s,
        max_reoffers=MAX_REOFFERS,
    )
    return asyncio.create_task(
        reaper_loop(interval_s=interval_s, stranded_after_s=stranded_after_s)
    )


async def stop_reaper(task: Optional["asyncio.Task[None]"]) -> None:
    """Cancel and await a started reaper (no-op for ``None``)."""
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


__all__: List[str] = [
    "DEFAULT_STRANDED_AFTER_S",
    "MAX_REOFFERS",
    "ORPHANED_CODE",
    "STRANDED_CODE",
    "ReaperSweep",
    "reaper_loop",
    "reconcile_dispatched_failure",
    "run_reaper_pass",
    "start_reaper",
    "stop_reaper",
    "sweep_orphaned_jobs",
    "sweep_orphaned_runs",
    "sweep_stranded_jobs",
    "sweep_stranded_runs",
]
