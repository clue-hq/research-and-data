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

A3 (defect R3-D) adds the run's one human control:

* :func:`request_run_cancellation` — stamp ``cancel_requested_at`` on a live run, write-once and
  idempotent, and :func:`cancellation_requested` — the boolean the driving worker polls at its
  model-call boundaries. The request is durable precisely because the asker and the driver share
  nothing but this row; see migration ``518a3784f3a4`` for why an in-memory signal cannot work.
  Neither function touches ``status``: the request is not the outcome.

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
from typing import Any, cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, dump_json_opt, iso, load_json, load_json_opt
from clue_design.enums import DesignRunKind, DesignRunStatus
from clue_design.errors import (
    DesignNotFoundError,
    DesignRunAlreadySavedError,
    DesignRunFencedError,
    DesignRunSaveFencedError,
)
from clue_design.site_turn_workspace import prune_site_turn_state

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
    holds makes the UPDATE refuse unless the row still records exactly that generation, raising
    :class:`DesignRunFencedError` instead of clobbering the takeover's result.

    **Equality** (site-turn durability, 2026-10-16; it was ``<=``). Lease generations never
    repeat any more, and the claim CAS stamps the claimant's generation on the row, so the row's
    ``lease_generation`` names exactly one attempt: the one that may land the result. A lower
    generation is a fenced-out attempt; a higher one is a writer that never claimed this run under
    it. A row whose ``lease_generation`` is NULL has never been claimed at all — nothing to be
    fenced by — and since the reaper's re-offer stopped clearing the stamp, NULL can only mean
    that. Omitting the argument keeps the pre-D5 unfenced behaviour, which is what the non-fleet
    callers (the SSE-visible ``set_run_result`` surface) still want.

    A terminal write also prunes a site turn's working copy and conversation checkpoints, in the
    same transaction (:func:`clue_design.site_turn_workspace.prune_site_turn_state`), as do
    :func:`fail_dispatched_run` and :func:`fail_stranded_run`.
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
        await prune_site_turn_state(conn, run_id=run_id)
        return
    outcome = await conn.execute(
        text(
            "UPDATE design_agent_run SET status = CAST(:s AS design_run_status),"
            " result_json = CAST(:result AS jsonb), updated_at = now()"
            " WHERE run_id = :r AND workspace_id = :w"
            "   AND (lease_generation IS NULL OR lease_generation = :gen)"
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
    await prune_site_turn_state(conn, run_id=run_id)


async def hold_run_for_save(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: str,
    document_id: str,
    lease_generation: int,
) -> UUID:
    """The run half of an agent-run save's fence; returns the run's work id.

    Called inside the save's own transaction, before the document is written (site-turn
    durability, 2026-10-16). It locks the run row ``FOR SHARE`` until that transaction ends, so a
    takeover's claim (an UPDATE of this row) waits for the save to commit or roll back and can
    never interleave with it. Then:

    * the run must be ``running`` with ``lease_generation`` EXACTLY this attempt's — a NULL
      (never-claimed) row does not pass here, unlike :func:`set_run_result`: an agent save only
      ever comes from an attempt that claimed its run. Otherwise
      :class:`DesignRunSaveFencedError`.
    * the run must not have saved this document already: one run makes at most one version. An
      earlier attempt's save is found by its history envelope, which an agent-run save stamps
      with the run id as ``actor_id``. Otherwise :class:`DesignRunAlreadySavedError` naming the
      version it saved.

    The work-lease half of the fence is the caller's (Rule S4: this substrate never learns the
    fleet exists); it keys on the work id returned here.
    """
    row = (
        await conn.execute(
            text(
                "SELECT work_id, status, lease_generation FROM design_agent_run"
                " WHERE run_id = :r AND workspace_id = :w FOR SHARE"
            ),
            {"r": run_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("agent_run", run_id)
    if row.status != DesignRunStatus.RUNNING.value:
        raise DesignRunSaveFencedError(
            run_id, lease_generation, row.lease_generation, reason="run_status"
        )
    if row.lease_generation != lease_generation:
        raise DesignRunSaveFencedError(
            run_id, lease_generation, row.lease_generation, reason="run_generation"
        )
    saved = (
        await conn.execute(
            text(
                "SELECT base_revision FROM design_edit_envelope"
                " WHERE workspace_id = :w AND document_id = :d"
                "   AND actor_kind = 'agent' AND actor_id = :r"
                " ORDER BY seq LIMIT 1"
            ),
            {"w": workspace_id, "d": document_id, "r": run_id},
        )
    ).first()
    if saved is not None:
        raise DesignRunAlreadySavedError(run_id, document_id, int(saved.base_revision) + 1)
    return cast(UUID, row.work_id)


# --- the cancellation request (A3, defect R3-D) ------------------------------------------------


async def request_run_cancellation(
    conn: AsyncConnection, *, workspace_id: str, run_id: str
) -> JsonObject:
    """Ask a non-terminal run to stop, durably. Returns the run's DTO plus the outcome of the ask.

    IDEMPOTENT AND WRITE-ONCE. ``cancel_requested_at`` is stamped only when it is still NULL and
    the run has not finished, so asking twice returns the FIRST request's timestamp rather than
    moving it — "when was this cancelled" must keep answering the same thing however many times
    the button is pressed.

    THE THREE HONEST ANSWERS, in the ``outcome`` key:

    * ``requested`` — the ask landed on a live run; a worker will honour it at its next model-call
      boundary.
    * ``already_requested`` — someone asked before. Nothing changed; the standing request stands.
    * ``already_terminal`` — the run had already finished (or was never claimed and then failed).
      Deliberately NOT an error: a human racing a run that ended a second ago has done nothing
      wrong, and a refusal would only invite a retry loop against a row that will never move.

    Fail-closed tenancy like every other read here: a run of another workspace is
    :class:`DesignNotFoundError`, indistinguishable from one that does not exist.

    The status column is deliberately untouched. The request is not the outcome — what the run
    ends up as is the driving worker's terminal write, which is the only writer of that column
    while a lease is live. Stamping a terminal status here would race the worker and could
    overwrite a real result with a guess.
    """
    row = (
        await conn.execute(
            text(
                "UPDATE design_agent_run SET cancel_requested_at = now(), updated_at = now()"
                " WHERE run_id = :r AND workspace_id = :w"
                "   AND cancel_requested_at IS NULL"
                "   AND status NOT IN :terminal"
                " RETURNING *"
            ).bindparams(bindparam("terminal", expanding=True)),
            {"r": run_id, "w": workspace_id, "terminal": list(TERMINAL_RUN_STATUSES)},
        )
    ).first()
    if row is not None:
        return {
            **_agent_run_from_row(row),
            "outcome": "requested",
            "cancel_requested_at": iso(row.cancel_requested_at),
        }
    # The UPDATE matched nothing: either the run is gone/foreign (raise), or one of the two
    # no-op cases below. One read decides which, so the answer is never guessed.
    current = (
        await conn.execute(
            text("SELECT * FROM design_agent_run WHERE run_id = :r AND workspace_id = :w"),
            {"r": run_id, "w": workspace_id},
        )
    ).first()
    if current is None:
        raise DesignNotFoundError("agent_run", run_id)
    outcome = "already_requested" if current.cancel_requested_at is not None else "already_terminal"
    return {
        **_agent_run_from_row(current),
        "outcome": outcome,
        "cancel_requested_at": iso(current.cancel_requested_at),
    }


async def cancellation_requested(conn: AsyncConnection, *, workspace_id: str, run_id: str) -> bool:
    """Has this run been asked to stop? The probe the driving worker polls at call boundaries.

    Deliberately narrow — one boolean off one indexed key lookup, not the whole row — because it
    is read once per model call for the life of the run. A run that has vanished answers ``False``
    rather than raising: this probe is consulted from inside a synchronous turn body, where an
    exception would become the run's cause of death instead of its stop signal.
    """
    row = (
        await conn.execute(
            text(
                "SELECT cancel_requested_at FROM design_agent_run"
                " WHERE run_id = :r AND workspace_id = :w"
            ),
            {"r": run_id, "w": workspace_id},
        )
    ).first()
    return row is not None and row.cancel_requested_at is not None


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


async def runs_for_execution(
    conn: AsyncConnection, *, workspace_id: str, execution_id: UUID
) -> list[JsonObject]:
    """Every run dispatched under one platform execution, oldest first (spec §3.3/§3.9: the
    batch of one leg turn is the runs stamped with that turn's execution id)."""
    rows = await conn.execute(
        text(
            "SELECT * FROM design_agent_run WHERE workspace_id = :w AND execution_id = :e "
            "ORDER BY created_at ASC, run_id ASC"
        ),
        {"w": workspace_id, "e": execution_id},
    )
    return [_agent_run_from_row(row) for row in rows]


async def active_run_for_document(
    conn: AsyncConnection, *, workspace_id: str, document_id: str
) -> str | None:
    """The id of a RUNNING run whose frozen envelope targets ``document_id``, else ``None``.

    The write-lock read: while a design run is driving a document, the design API refuses manual
    writes to that document (409 ``document.agent_run_active``), so a human and an agent can never
    author the same scene at the same time.

    The predicate is the run's own PAYLOAD, not the ``document_id`` column, because the payload is
    the frozen ``DesignTurnEnvelope`` — the immutable statement of what this run was dispatched to
    do. The column is a nullable convenience (:func:`create_run` stores an id it cannot resolve as
    NULL), so a run whose envelope names a document is the honest question to ask.

    Only ``running`` counts. A ``queued`` run has nobody driving it yet and a terminal one is over;
    locking either would refuse edits for work that is not happening. The lock is therefore a state
    that lifts by itself — including when a lease expires and the reaper fails the row.
    """
    row = (
        await conn.execute(
            text(
                "SELECT run_id FROM design_agent_run"
                " WHERE workspace_id = :w AND status = 'running'"
                "   AND payload ->> 'document_id' = :d"
                " ORDER BY created_at ASC, run_id ASC"
                " LIMIT 1"
            ),
            {"w": workspace_id, "d": document_id},
        )
    ).first()
    return None if row is None else str(row.run_id)


async def latest_terminal_run_for_document(
    conn: AsyncConnection, *, workspace_id: str, document_id: str
) -> JsonObject | None:
    """The newest TERMINAL run whose frozen envelope targets ``document_id``, else ``None``.

    Spec 2026-09-20 (clarification cards) §2.3: "this document has an open question" is derived
    — its latest terminal run's result status is ``clarification_requested`` — never stored.
    Same predicate as :func:`active_run_for_document` (the payload, not the nullable column).

    Terminal means ``succeeded`` or ``failed``: a ``queued`` or ``running`` run has not said
    anything yet, so letting one answer this read would report a stale question (or none) while
    the current turn is still deciding.
    """
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_agent_run"
                " WHERE workspace_id = :w AND status IN ('succeeded', 'failed')"
                "   AND payload ->> 'document_id' = :d"
                " ORDER BY created_at DESC, run_id DESC"
                " LIMIT 1"
            ),
            {"w": workspace_id, "d": document_id},
        )
    ).first()
    return None if row is None else _agent_run_from_row(row)


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

    The lease stamp is KEPT (site-turn durability, 2026-10-16; it used to be cleared). Lease
    generations never repeat, so the next attempt's claim always carries a higher generation and
    re-stamps the row; until then the row still fences on the dead attempt's generation, where a
    cleared one let a writer under ANY generation land a result. The re-offered run re-executes
    through the checkpoint-restart path (``lumen_agent.checkpoint``): its frozen ``payload``
    envelope is unchanged, so the takeover replays the same unit of work.
    """
    row = (
        await conn.execute(
            text(
                "UPDATE design_agent_run"
                " SET status = CAST('queued' AS design_run_status),"
                "     reoffer_count = reoffer_count + 1, updated_at = now()"
                " WHERE work_id = :work_id AND status = 'running'"
                "   AND reoffer_count < :max"
                " RETURNING *"
            ),
            {"work_id": work_id, "max": max_reoffers},
        )
    ).first()
    return None if row is None else _agent_run_job_from_row(row)


async def list_dispatched_queued_runs(conn: AsyncConnection) -> list[JsonObject]:
    """Every run still ``queued`` with its lease facts — the reaper's orphan input (R3-B).

    The twin of :func:`list_dispatched_running_runs`, for the same reason its ingestion
    counterpart exists: a worker that fails *before* the claim CAS leaves the run exactly where
    the route left it, ``queued``, while its fleet task ends terminally FAILED — a state neither
    the ``running`` sweep nor any re-offer path can see. Every D5 run has a ``work_id``
    (``NOT NULL``), so there is no never-dispatched shape to exclude here either.
    """
    rows = (
        await conn.execute(
            text(
                "SELECT run_id, workspace_id, kind, work_id, document_id, leased_by,"
                "       lease_generation, leased_at, reoffer_count, updated_at"
                " FROM design_agent_run WHERE status = 'queued'"
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


async def fail_dispatched_run(
    conn: AsyncConnection,
    *,
    work_id: UUID,
    result: JsonObject,
    lease_generation: int | None = None,
) -> JsonObject | None:
    """Terminalize a dispatched run ``failed`` from the FLEET plane, keyed on work id (R3-B).

    The run twin of :func:`clue_design.ingestion.fail_dispatched_job` — see it for the full
    rationale. It accepts a ``queued`` row as well as a ``running`` one because the defect it
    repairs is a run whose worker died before the claim CAS could move it.

    ``None`` means refused: the row is already terminal, or a NEWER lease generation owns it
    (the claim CAS's own fence predicate). As with :func:`fail_stranded_run`, the terminal
    marker event is NOT emitted here — the caller lands it in the same transaction through
    ``lumen_api.run_stream.fenced_emit``, which keeps the stream's terminal contract intact.
    """
    fence = (
        ""
        if lease_generation is None
        else " AND (lease_generation IS NULL OR lease_generation <= :gen)"
    )
    params: dict[str, Any] = {"work_id": work_id, "result": dump_json(result)}
    if lease_generation is not None:
        params["gen"] = lease_generation
    row = (
        await conn.execute(
            text(
                "UPDATE design_agent_run"
                " SET status = CAST('failed' AS design_run_status),"
                "     result_json = CAST(:result AS jsonb), updated_at = now()"
                " WHERE work_id = :work_id AND status IN ('queued', 'running')"
                + fence
                + " RETURNING *"
            ),
            params,
        )
    ).first()
    if row is None:
        return None
    await prune_site_turn_state(conn, run_id=row.run_id)
    return _agent_run_job_from_row(row)


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
    if row is None:
        return None
    await prune_site_turn_state(conn, run_id=row.run_id)
    return _agent_run_job_from_row(row)


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


async def asset_context_snapshot(
    conn: AsyncConnection, *, workspace_id: str, run_id: str
) -> JsonObject | None:
    row = (
        await conn.execute(
            text(
                "SELECT asset_context_snapshot FROM design_agent_run"
                " WHERE workspace_id = :w AND run_id = :r"
            ),
            {"w": workspace_id, "r": run_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("agent_run", run_id)
    return cast(JsonObject | None, load_json_opt(row.asset_context_snapshot))


async def pin_asset_context_snapshot(
    conn: AsyncConnection, *, workspace_id: str, run_id: str, snapshot: JsonObject
) -> JsonObject:
    row = (
        await conn.execute(
            text("""
        UPDATE design_agent_run SET
          asset_context_snapshot = COALESCE(asset_context_snapshot, CAST(:snapshot AS jsonb))
        WHERE workspace_id = :w AND run_id = :r RETURNING asset_context_snapshot
    """),
            {"w": workspace_id, "r": run_id, "snapshot": dump_json(snapshot)},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("agent_run", run_id)
    return cast(JsonObject, load_json(row.asset_context_snapshot))
