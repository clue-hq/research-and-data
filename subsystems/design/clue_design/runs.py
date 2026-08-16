"""Agent-run DAL (Part II slices D2.5A + D5 + D7) — the design API's ``agent_runs`` domain, and
the design **durable-job** surface.

Faithful port of ``lumen_api.database.Repository``'s run methods onto ``design_agent_run``
(PD contract §5 row 16). D5 reshapes the run row onto the durable job pattern (``work_id``,
``checkpoint_thread_id``, ``kind``, the frozen ``payload`` envelope, lease observability) and adds
the claim CAS the fleet worker drives it through.

**D7 retired the run's event log from this module.** ``design_run_event`` (PD row 17, always
labelled temporary) is dropped; leg activity is now ``design.*`` topics on the platform
``run_event`` stream. ``append_run_event`` / ``list_run_events`` / ``complete_run`` are gone with
it, and so is the boot-sweep read ``list_running_runs_across_workspaces`` (caller-less since D5
Round B). What stays here is the run ROW — including the two facts the stream write is fenced and
clocked by, :func:`run_lease_generation` and :func:`touch_run`.

The D5 additions, in one place:

* :func:`work_id_for_run` — the one derivation of a run's fleet work id, strict by contract.
* :func:`create_run` — births a run ``queued`` with its work id, checkpoint thread, kind, and
  frozen turn envelope.
* :func:`claim_run_for_execution` — the generation-fenced CAS a worker claims a run through.
* :func:`get_run_by_work_id` — the fleet-plane read that resolves a work id back to its run.
* ``expected_generation=`` on :func:`set_run_result` (D5 Round B) — the zombie fence. A synchronous
  turn body abandoned by a fenced-out worker must not overwrite the takeover's run; the guard
  refuses those writes with :class:`~clue_design.errors.DesignRunFencedError` instead. Since D7 the
  same fence guards the run's stream writes, one level up, off :func:`run_lease_generation`.
* :func:`list_dispatched_running_runs` / :func:`reoffer_stranded_run` / :func:`fail_stranded_run`
  (D5 Round C) — the stranded-work surface. A run whose worker died without landing ANY terminal
  row would otherwise sit ``running`` forever; the reaper hands it back to ``queued`` once and
  terminalizes it after. Design rows only: whether the row is genuinely stranded needs the fleet
  task's state and the live lease, which are read at the composition root and passed in (S4).

What the port changes, and why:

* **Fail-closed tenancy.** Every read and write is keyed ``(run_id, workspace_id)``, so a run
  belonging to another tenant is indistinguishable from one that does not exist
  (:class:`DesignNotFoundError` either way — the D2 error-taxonomy rule).
* **``document_id`` is a real FK, so a dangling id is stored as NULL.**
  ``design_agent_run_document_fk`` references ``design_document (id, workspace_id)`` (SQLite
  deliberately had no FK). The live ``POST /agent/turns`` route passes the *editor's* document id
  with the scene inline in the payload — that document need not exist in the store at all — so
  refusing the insert would break a shipped route. :func:`create_run` therefore stores the
  reference only when the document exists in this workspace, and NULL otherwise. This is
  behaviour-preserving at the API surface: the only consumer of ``document_id`` was the
  ``LEFT JOIN documents`` that resolved ``doc_kind`` for the startup sweep, which yielded NULL
  for a dangling id anyway, and no endpoint echoes ``document_id`` back to a client. (D5's
  reshape owns the real answer: subject columns instead of a document pointer.)

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits. Mappers reproduce ``agent_run_from_row`` exactly, with ISO-string timestamps.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, dump_json_opt, iso, load_json, load_json_opt
from clue_design.enums import DesignRunKind, DesignRunStatus
from clue_design.errors import DesignNotFoundError, DesignRunFencedError

#: The shipped run-id shape (``run_<uuid4 hex>``), which :func:`work_id_for_run` inverts exactly.
#: Byte-identical to the D5 migration's backfill regex, deliberately — see that function.
_RUN_ID_WITH_UUID = re.compile(r"^run_([0-9a-f]{32})$")


def work_id_for_run(run_id: str) -> UUID:
    """The run's fleet work id, derived from the run id — the ONE place that derivation lives.

    A design run id is ``run_<uuid4 hex>``, so the uuid the fleet keys on is already *inside* it.
    Deriving rather than minting a second identifier means the two id spaces can never drift, and
    an operator holding either one can reach the other by hand.

    **Total and deterministic**, which matters more here than strictness. An id that is not the
    shipped shape (hand-made runs in tests and scripts) still gets a stable work id, from an MD5
    fold of the whole run id — used purely as an id derivation, never as a security primitive,
    hence ``usedforsecurity=False``. Refusing instead would make ``create_run`` reject ids it
    happily stored before D5, and a *random* fallback would break the one property every caller
    depends on: that the same run id always yields the same work id, so
    ``get_run_by_work_id(work_id_for_run(run_id))`` finds the run.

    This is exactly — same regex, same MD5 fold — what the D5 migration's backfill computes, so a
    row backfilled by the migration and a row created by this DAL carry the same work id for the
    same run id. That agreement is the point; keep the two in step if either ever changes.
    """
    matched = _RUN_ID_WITH_UUID.match(run_id)
    if matched is not None:
        return UUID(hex=matched.group(1))
    return UUID(hex=hashlib.md5(run_id.encode("utf-8"), usedforsecurity=False).hexdigest())


def _agent_run_from_row(row: Any) -> JsonObject:
    """The DTO the design API has always served. Deliberately NOT widened with the D5 columns:
    it is a shipped response shape, and the durable-job view has its own mapper below."""
    return {
        "run_id": row.run_id,
        "status": row.status,
        "document_id": row.document_id,
        "result": load_json_opt(row.result_json),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def _agent_run_job_from_row(row: Any) -> JsonObject:
    """The durable-job view of a run — what a worker (and an operator debugging a lease) needs.

    Carries ``workspace_id`` because its readers are fleet-plane: they resolve a work id first
    and only then know which tenant's store to work in (the same reason
    :func:`list_dispatched_running_runs` returns it).
    """
    return {
        "run_id": row.run_id,
        "workspace_id": row.workspace_id,
        "work_id": str(row.work_id),
        "checkpoint_thread_id": row.checkpoint_thread_id,
        "kind": row.kind,
        "status": row.status,
        "document_id": row.document_id,
        "payload": load_json(row.payload),
        "result": load_json_opt(row.result_json),
        "leased_by": row.leased_by,
        "lease_generation": row.lease_generation,
        "leased_at": iso(row.leased_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


# --- runs -------------------------------------------------------------------------------------


async def get_run(conn: AsyncConnection, *, workspace_id: str, run_id: str) -> JsonObject | None:
    """The optional read (the run-snapshot endpoint's probe): ``None``, never a raise."""
    row = (
        await conn.execute(
            text("SELECT * FROM design_agent_run WHERE run_id = :r AND workspace_id = :w"),
            {"r": run_id, "w": workspace_id},
        )
    ).first()
    return None if row is None else _agent_run_from_row(row)


async def require_run(conn: AsyncConnection, *, workspace_id: str, run_id: str) -> JsonObject:
    """Fetch or raise. ``kind='agent_run'`` keeps the ported ``NotFoundError`` detail string."""
    run = await get_run(conn, workspace_id=workspace_id, run_id=run_id)
    if run is None:
        raise DesignNotFoundError("agent_run", run_id)
    return run


async def create_run(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: str,
    document_id: str | None,
    kind: DesignRunKind = DesignRunKind.AGENT_TURN,
    payload: JsonObject | None = None,
    work_id: UUID | None = None,
    checkpoint_thread_id: str | None = None,
    leg_id: str | None = None,
    execution_id: UUID | None = None,
) -> JsonObject:
    """Open one **queued** run row and read it back (the ported DTO shape).

    D5 changes the birth status: a run is created ``queued`` and stamped ``running`` by the worker
    that claims it (:func:`claim_run_for_execution`). Under the pre-D5 daemon-thread path the
    creator *was* the executor, so ``running`` at insert was honest; once a queue sits between
    them, a row that claims to be running before any worker owns it is a lie that the restart
    sweep then has to clean up.

    ``kind`` defaults to ``AGENT_TURN`` and ``payload`` to ``{}`` so the shipped call sites keep
    working unchanged while Round B switches the API over to passing both explicitly; the
    defaults are a migration aid, not the end state.

    ``work_id`` and ``checkpoint_thread_id`` default to their canonical derivations —
    :func:`work_id_for_run` and ``run_id`` itself (the D5 ruling: the checkpoint thread IS the
    run). They are parameters only so a caller that already minted a work id can pass it rather
    than re-deriving it.

    ``document_id`` is retained only when it names a document of THIS workspace; an unknown id
    is stored as NULL rather than rejected by ``design_agent_run_document_fk`` — see the module
    docstring for why (the async agent-turn route legitimately carries an unstored id).

    ``leg_id`` / ``execution_id`` (Part III P3.1 linkage, stamped since P3.4): a run dispatched
    from a design leg records the leg it iterates and the platform execution its ``agent_turn``
    row is scoped under. Standalone-editor runs carry neither — the columns stay honestly NULL.
    """
    resolved: str | None = None
    if document_id is not None:
        found = (
            await conn.execute(
                text("SELECT 1 FROM design_document WHERE id = :d AND workspace_id = :w"),
                {"d": document_id, "w": workspace_id},
            )
        ).first()
        resolved = document_id if found is not None else None
    await conn.execute(
        text(
            "INSERT INTO design_agent_run"
            " (run_id, workspace_id, work_id, checkpoint_thread_id, kind, status,"
            "  document_id, payload, result_json, leg_id, execution_id)"
            " VALUES (:r, :w, :work_id, :thread, CAST(:kind AS design_run_kind),"
            "         CAST('queued' AS design_run_status), :d, CAST(:payload AS jsonb), NULL,"
            "         :leg, :execution)"
        ),
        {
            "r": run_id,
            "w": workspace_id,
            "work_id": work_id if work_id is not None else work_id_for_run(run_id),
            "thread": checkpoint_thread_id if checkpoint_thread_id is not None else run_id,
            "kind": str(kind),
            "d": resolved,
            "payload": dump_json(payload if payload is not None else {}),
            "leg": leg_id,
            "execution": execution_id,
        },
    )
    return await require_run(conn, workspace_id=workspace_id, run_id=run_id)


# --- the durable-job surface (D5): fleet-plane reads + the claim CAS ---------------------------


async def get_run_by_work_id(conn: AsyncConnection, *, work_id: UUID) -> JsonObject | None:
    """Resolve a fleet work id to its run's durable-job view, or ``None``.

    Deliberately **not** workspace-scoped — the second read in this module that is not, and for
    the same structural reason as :func:`list_dispatched_running_runs`: a worker pulling a
    task off the queue holds a work id and nothing else, so the workspace is what this read is
    *for*, not a predicate it could already supply. ``work_id`` is globally unique
    (``design_agent_run_work_id_unique``) and unguessable, and the returned row carries
    ``workspace_id`` precisely so the caller can continue through a workspace-CORRECT store.
    """
    row = (
        await conn.execute(
            text("SELECT * FROM design_agent_run WHERE work_id = :work_id"),
            {"work_id": work_id},
        )
    ).first()
    return None if row is None else _agent_run_job_from_row(row)


async def claim_run_for_execution(
    conn: AsyncConnection, *, work_id: UUID, worker_id: str, lease_generation: int
) -> JsonObject | None:
    """Claim a run for execution under ``lease_generation``; the durable-job CAS.

    One statement, so the claim is atomic against every other worker. The row moves to
    ``running`` and records who holds it, and the predicate encodes exactly these rules:

    * **queued → running.** The normal path: the API enqueued the work, this worker took it.
    * **Same generation re-claims (idempotent).** A worker that crashes *after* claiming and
      retries within the same lease, or an at-least-once redelivery of the same task, must not be
      refused — it already owns the lease, so re-claiming is a no-op that re-reads the row.
    * **A HIGHER generation may re-claim a ``running`` row (takeover).** A ``running`` row whose
      generation is below the claimant's means the previous holder is *gone*: generations are
      issued monotonically by the platform lease, so holding a newer one is proof the old lease
      expired and was re-granted. Refusing here would strand exactly the runs D5 exists to
      rescue — the ones whose worker died mid-turn.
    * **A LOWER generation is refused.** That claimant has been fenced out; its lease was
      superseded. It gets ``None`` and must stop, never overwrite the current holder's stamp.

    Terminal runs (``succeeded`` / ``failed``) are never re-claimed: finished work is not
    restarted by a takeover.

    Returns the claimed run's durable-job view, or ``None`` when the CAS refused (fenced out or
    already terminal). Raises :class:`DesignNotFoundError` when no run carries this work id at
    all — an unknown work id and a refused claim are genuinely different answers to a worker.

    Fleet-plane, so unscoped by workspace for the same reason as :func:`get_run_by_work_id`.
    The authoritative fence remains the platform ``work_lease`` row; these columns are the design
    subsystem's own record of who is driving, never its permission to drive.
    """
    row = (
        await conn.execute(
            text(
                "UPDATE design_agent_run"
                " SET status = CAST('running' AS design_run_status),"
                "     leased_by = :worker, lease_generation = :gen, leased_at = now(),"
                "     updated_at = now()"
                " WHERE work_id = :work_id"
                "   AND status IN ('queued', 'running')"
                "   AND (lease_generation IS NULL OR lease_generation <= :gen)"
                " RETURNING *"
            ),
            {"work_id": work_id, "worker": worker_id, "gen": lease_generation},
        )
    ).first()
    if row is not None:
        return _agent_run_job_from_row(row)
    if await get_run_by_work_id(conn, work_id=work_id) is None:
        raise DesignNotFoundError("agent_run", str(work_id))
    return None


async def _current_lease_generation(
    conn: AsyncConnection, *, workspace_id: str, run_id: str
) -> int | None:
    row = (
        await conn.execute(
            text(
                "SELECT lease_generation FROM design_agent_run"
                " WHERE run_id = :r AND workspace_id = :w"
            ),
            {"r": run_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("agent_run", run_id)
    generation: int | None = row.lease_generation
    return generation


async def set_run_result(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: str,
    status: str,
    result: JsonObject | None,
    expected_generation: int | None = None,
) -> None:
    """Write the terminal status + result. Fail-closed: an unknown (or cross-workspace) run
    raises rather than silently updating nothing, which is what the SQLite UPDATE did.

    ``expected_generation`` (D5) is the **zombie fence**. The turn body is synchronous and runs
    under ``asyncio.to_thread``, so a worker that loses its lease stops only cooperatively: the
    handler returns at once, but the abandoned thread keeps running and may land a terminal write
    long after a takeover worker re-claimed and re-ran the run. Passing the generation the writer
    holds makes the UPDATE refuse whenever the row has since moved to a HIGHER one, raising
    :class:`DesignRunFencedError` instead of clobbering the takeover's result.

    ``<=`` rather than ``=`` is deliberate on the permitted side: the in-flight holder is the row's
    own generation, and a row whose ``lease_generation`` is NULL has never been claimed at all
    (nothing to be fenced by). Omitting the argument keeps the pre-D5 unfenced behaviour, which is
    what the non-fleet callers (the SSE-visible ``set_run_result`` surface) still want.
    """
    if expected_generation is None:
        outcome = await conn.execute(
            text(
                "UPDATE design_agent_run SET status = CAST(:s AS design_run_status),"
                " result_json = CAST(:result AS jsonb), updated_at = now()"
                " WHERE run_id = :r AND workspace_id = :w"
            ),
            {"s": status, "result": dump_json_opt(result), "r": run_id, "w": workspace_id},
        )
        if outcome.rowcount == 0:
            raise DesignNotFoundError("agent_run", run_id)
        return
    outcome = await conn.execute(
        text(
            "UPDATE design_agent_run SET status = CAST(:s AS design_run_status),"
            " result_json = CAST(:result AS jsonb), updated_at = now()"
            " WHERE run_id = :r AND workspace_id = :w"
            "   AND (lease_generation IS NULL OR lease_generation <= :gen)"
        ),
        {
            "s": status,
            "result": dump_json_opt(result),
            "r": run_id,
            "w": workspace_id,
            "gen": expected_generation,
        },
    )
    if outcome.rowcount == 0:
        # Distinguish the two refusals rather than collapsing them: an absent run is a caller bug,
        # a fenced-out run is the expected outcome of a takeover and must be logged as such.
        current = await _current_lease_generation(conn, workspace_id=workspace_id, run_id=run_id)
        raise DesignRunFencedError(run_id, expected_generation, current)


async def list_running_runs(conn: AsyncConnection, *, workspace_id: str) -> list[JsonObject]:
    """Runs still 'running' in this workspace, each with its document's ``doc_kind`` (NULL when
    the run has no document) — the ported LEFT JOIN, now a real join in one query."""
    rows = (
        await conn.execute(
            text(
                "SELECT r.run_id, r.document_id, d.doc_kind FROM design_agent_run r"
                " LEFT JOIN design_document d"
                "   ON d.id = r.document_id AND d.workspace_id = r.workspace_id"
                " WHERE r.workspace_id = :w AND r.status = 'running'"
                " ORDER BY r.created_at ASC, r.run_id ASC"
            ),
            {"w": workspace_id},
        )
    ).fetchall()
    return [
        {"run_id": row.run_id, "document_id": row.document_id, "doc_kind": row.doc_kind}
        for row in rows
    ]


# --- the stranded-work surface (D5 Round C) ----------------------------------------------------
#
# S4 boundary: these three read and write the DESIGN row only. Whether a stranded-looking run's
# fleet task is actually dead — the queue state and the live-lease check — is decided by the
# reaper at the composition root and passed IN as a decision, because ``clue_design`` may not
# learn that ``clue_fleet`` exists.


async def list_dispatched_running_runs(conn: AsyncConnection) -> list[JsonObject]:
    """Every ``running`` run in the DATABASE with its lease facts — the reaper's input.

    Unscoped by workspace for the same structural reason as
    :func:`get_run_by_work_id`: a stranded run belongs to whichever tenant owns it, and a
    per-tenant sweep would leave every other tenant's runs stuck ``running`` forever.
    Nothing here writes and no turn payload is returned — only the identifiers and lease facts the
    reaper needs to decide.

    Every D5 run has a ``work_id`` (``NOT NULL``), so unlike the ingestion twin there is no
    never-dispatched shape to exclude.
    """
    rows = (
        await conn.execute(
            text(
                "SELECT run_id, workspace_id, kind, work_id, document_id, leased_by,"
                "       lease_generation, leased_at, reoffer_count, updated_at"
                " FROM design_agent_run WHERE status = 'running'"
                " ORDER BY updated_at ASC, run_id ASC"
            )
        )
    ).fetchall()
    return [
        {
            "run_id": row.run_id,
            "workspace_id": row.workspace_id,
            "kind": row.kind,
            "work_id": str(row.work_id),
            "document_id": row.document_id,
            "leased_by": row.leased_by,
            "lease_generation": row.lease_generation,
            "leased_at": iso(row.leased_at),
            "reoffer_count": row.reoffer_count,
            "updated_at": iso(row.updated_at),
        }
        for row in rows
    ]


async def reoffer_stranded_run(
    conn: AsyncConnection, *, work_id: UUID, max_reoffers: int = 1
) -> JsonObject | None:
    """Hand a stranded ``running`` run back to ``queued`` so a worker can claim it again.

    One CAS statement; ``reoffer_count < :max`` is the bound, durable in the row because a
    process-local memory of "I already retried this" dies with the process whose death caused the
    strand. ``None`` = refused: the run stopped being ``running``, or its budget is spent and the
    caller must terminalize it instead.

    The lease trio is CLEARED — the row is genuinely unowned again, and a stale
    ``lease_generation`` would fence the very writes the next claimant is supposed to make. The
    re-offered run re-executes through the checkpoint-restart path (``lumen_agent.checkpoint``):
    its frozen ``payload`` envelope is unchanged, so the takeover replays the same unit of work.
    """
    row = (
        await conn.execute(
            text(
                "UPDATE design_agent_run"
                " SET status = CAST('queued' AS design_run_status),"
                "     leased_by = NULL, lease_generation = NULL, leased_at = NULL,"
                "     reoffer_count = reoffer_count + 1, updated_at = now()"
                " WHERE work_id = :work_id AND status = 'running'"
                "   AND reoffer_count < :max"
                " RETURNING *"
            ),
            {"work_id": work_id, "max": max_reoffers},
        )
    ).first()
    return None if row is None else _agent_run_job_from_row(row)


async def fail_stranded_run(
    conn: AsyncConnection, *, work_id: UUID, result: JsonObject
) -> JsonObject | None:
    """Terminalize a stranded run ``failed`` with the reaper's result envelope.

    Guarded on ``status = 'running'`` so a run that finished between the reaper's read and its
    write is left alone — the reaper never overwrites a real outcome with ``stranded``. The
    terminal marker event is NOT emitted here: the reaper lands it in the same transaction
    through ``lumen_api.run_stream.fenced_emit``, which is what keeps the stream's terminal
    contract (result committed before the event that announces it) intact.
    """
    row = (
        await conn.execute(
            text(
                "UPDATE design_agent_run"
                " SET status = CAST('failed' AS design_run_status),"
                "     result_json = CAST(:result AS jsonb), updated_at = now()"
                " WHERE work_id = :work_id AND status = 'running'"
                " RETURNING *"
            ),
            {"work_id": work_id, "result": dump_json(result)},
        )
    ).first()
    return None if row is None else _agent_run_job_from_row(row)


#: The two terminal ``design_run_status`` labels. Named once here so the retention scan below and
#: any future reader agree on what "finished" means without restating the enum inline.
TERMINAL_RUN_STATUSES: tuple[str, ...] = (
    DesignRunStatus.SUCCEEDED.value,
    DesignRunStatus.FAILED.value,
)


async def list_prunable_terminal_runs(
    conn: AsyncConnection, *, terminal_before_s: float, limit: int = 500
) -> list[JsonObject]:
    """Runs that finished more than ``terminal_before_s`` seconds ago — the event pruner's input.

    The **eligibility half** of the D8 design-event pruner (ruling R-D8-4); the deletion itself is
    ``clue_execution.run_events.prune_design_run_progress_events``, which ``clue_design`` may not
    import. The split is the S4 boundary the reaper already draws: the design substrate answers
    questions about design rows and nothing else, and the composition root
    (``lumen_api.event_pruner``) joins the two halves.

    ``status`` is checked against the two terminal labels — a ``queued``/``running`` run is never
    returned, whatever its age, because its stream is still being written. "How long terminal" is
    measured on ``updated_at``, which the terminal write stamps (``set_run_result`` /
    ``fail_stranded_run``) and which nothing bumps afterwards: a terminal run is never touched
    again (``touch_run`` only rides an emit, and a terminal run emits nothing more).

    Unscoped by workspace for the same reason as :func:`list_dispatched_running_runs`: retention is
    a substrate property, and a per-tenant sweep would leave every unnamed tenant growing forever.
    ``limit`` bounds one pass so a large backlog is drained over several passes rather than in one
    long transaction; oldest first, so the drain is deterministic and makes progress.
    """
    rows = (
        await conn.execute(
            text(
                "SELECT run_id, workspace_id, status, updated_at"
                " FROM design_agent_run"
                " WHERE status = ANY(CAST(:terminal AS design_run_status[]))"
                "   AND updated_at < now() - make_interval(secs => :age_s)"
                " ORDER BY updated_at ASC, run_id ASC"
                " LIMIT :limit"
            ),
            {"terminal": list(TERMINAL_RUN_STATUSES), "age_s": terminal_before_s, "limit": limit},
        )
    ).fetchall()
    return [
        {
            "run_id": row.run_id,
            "workspace_id": row.workspace_id,
            "status": row.status,
            "updated_at": iso(row.updated_at),
        }
        for row in rows
    ]


# --- the run's activity stream: the fence primitives it is written under (D7) ------------------
#
# ``design_run_event`` and its DAL (``append_run_event`` / ``list_run_events``) are GONE. Design
# leg activity is now ``design.*`` topics on the platform ``run_event`` stream, written through
# ``clue_execution.run_events`` — which ``clue_design`` may not import (the design substrate imports
# only core + db + config + obs + storage). So the *stream* write lives at the composition root
# (``lumen_api.run_stream.fenced_emit``) and the two design-row facts that write depends on — the
# lease fence and the staleness clock — are exported here, where the run row lives.


async def run_lease_generation(
    conn: AsyncConnection, *, workspace_id: str, run_id: str
) -> int | None:
    """This run's current ``lease_generation`` (``None`` = never claimed).

    The public form of the fence read :func:`set_run_result` uses internally. Its caller is
    ``lumen_api.run_stream.fenced_emit``, which must refuse a taken-over worker's stream write
    exactly as ``append_run_event`` did — BEFORE anything is written, so a fenced writer leaves no
    trace at all. Raises :class:`DesignNotFoundError` for an unknown or cross-workspace run.
    """
    return await _current_lease_generation(conn, workspace_id=workspace_id, run_id=run_id)


async def touch_run(conn: AsyncConnection, *, workspace_id: str, run_id: str) -> None:
    """Bump the run's ``updated_at`` — the side effect ``append_run_event`` used to carry.

    Not cosmetic: ``updated_at`` is the **reaper's staleness clock**
    (:func:`list_dispatched_running_runs` orders by it and ``_old_enough`` gates on it), so a long
    turn that only ever emits progress
    events must keep proving it is alive. Losing this with the old table would have made a healthy
    but chatty run look stranded. Silent on an unknown run: the caller has already established
    existence through :func:`run_lease_generation`.
    """
    await conn.execute(
        text(
            "UPDATE design_agent_run SET updated_at = now() WHERE run_id = :r AND workspace_id = :w"
        ),
        {"r": run_id, "w": workspace_id},
    )
