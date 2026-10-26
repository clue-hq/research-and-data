"""Ingestion-job DAL (Part II slice D2.3) — the port of the design API's ingestion domain.

Faithful port of ``lumen_ingestion.jobs.IngestionJobStore``'s SQL surface onto
``design_ingestion_job`` (PD contract §5), with the D1/D2 upgrades the contract mandates:

* **Fail-closed tenancy.** Every function takes ``workspace_id`` and locates rows by
  ``(job_id, workspace_id)``; a foreign-workspace job id raises the same
  :class:`DesignNotFoundError` an absent one does, and an UPDATE scoped to another workspace
  writes nothing and then raises on the read-back. Job ids are server-minted (``ingest_<uuid4>``)
  so the primary key stays global — unlike the content-derived asset/document ids.
* **Closed vocabularies are enum columns**, not free text: ``kind`` and ``status`` cast to
  ``design_ingestion_kind`` / ``design_ingestion_status``.
* **The result pointer is a real composite FK** (``brand_kit_id, brand_kit_version,
  workspace_id`` → ``design_brand_kit``), which SQLite only back-linked by convention: a job can
  no longer complete against a kit version that does not exist in its own workspace.
* **Timestamps are the database's** (``now()`` defaults / ``updated_at = now()``), replacing the
  SQLite layer's caller-minted ``now_iso`` strings; the mapper renders them to the same ISO-8601
  shape the API has always served, so the DTO is byte-identical.

Slice **D5** adds the durable-execution handle: :func:`set_work_id` / :func:`get_job_by_work_id`
join a job to its fleet task, and :func:`read_staged_request` is the side-effect-free input read
a requeued worker recovers from. **Round C completed the move**: ingestion execution is off
``BackgroundTasks`` (which a restart stranded as ``running`` forever) and onto the fleet, which
brings three more surfaces here, all twins of the ones ``clue_design.runs`` already carries:

* :func:`claim_job_for_execution` — the generation-fenced CAS a worker claims a job through,
  case-for-case identical to the run CAS (a turn and an ingestion are two shapes of ONE fleet
  kind, so they must agree on what claiming means).
* ``expected_generation=`` on :func:`set_running` / :func:`set_stage` / :func:`complete` /
  :func:`fail` — the zombie fence. The pipeline is a long synchronous body run under
  ``asyncio.to_thread``, so a fenced-out worker stops only cooperatively and its abandoned thread
  must not stamp progress or a result over the takeover's
  (:class:`~clue_design.errors.DesignJobFencedError`).
* :func:`list_dispatched_running_jobs` / :func:`reoffer_stranded_job` / :func:`fail_stranded_job`
  — the stranded-work surface the Round C reaper drives. Design rows only; the fleet-side join
  (task state, live lease) is made at the composition root and passed in (Rule S4).

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits. The mapper reproduces ``jobs._job_from_row`` exactly — the D5 columns are served
only by the fleet-plane reads, never bolted onto the shipped job DTO.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, dump_json_opt, iso, load_json_opt
from clue_design.errors import DesignJobFencedError, DesignNotFoundError


def new_id(prefix: str) -> str:
    """The ported id minter (``ingest_<uuid4 hex>``) — server-side, never client-supplied."""
    return f"{prefix}_{uuid4().hex}"


def _job_from_row(row: Any) -> JsonObject:
    return {
        "job_id": row.job_id,
        "kind": row.kind,
        "status": row.status,
        "stage": row.stage,
        "progress": row.progress,
        "request": load_json_opt(row.request_json),
        "evidence": load_json_opt(row.evidence_json),
        "brand_kit_id": row.brand_kit_id,
        "brand_kit_version": row.brand_kit_version,
        "error": load_json_opt(row.error_json),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


async def get_job(conn: AsyncConnection, *, workspace_id: str, job_id: str) -> JsonObject | None:
    """The ``store.get`` port: the job, or ``None`` when this workspace has no such job."""
    row = (
        await conn.execute(
            text("SELECT * FROM design_ingestion_job WHERE job_id = :j AND workspace_id = :w"),
            {"j": job_id, "w": workspace_id},
        )
    ).first()
    return None if row is None else _job_from_row(row)


async def require_job(conn: AsyncConnection, *, workspace_id: str, job_id: str) -> JsonObject:
    """The ``store.require`` port: fetch or raise the fail-closed refusal."""
    job = await get_job(conn, workspace_id=workspace_id, job_id=job_id)
    if job is None:
        raise DesignNotFoundError("ingestion_job", job_id)
    return job


async def create_job(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    kind: str,
    request: JsonObject,
    job_id: str | None = None,
    work_id: UUID | None = None,
) -> JsonObject:
    """Queue one job (``status='queued'``, ``progress=0``, no stage/result/error yet).

    ``job_id`` and ``work_id`` (D5 Round C) let the ONE fleet-dispatch transaction mint both ids
    up front: the envelope a ``design_job`` task carries names the job, so the id cannot be a
    server-side surprise discovered only after the INSERT. Omitting them keeps the ported
    behaviour exactly (``ingest_<uuid4>``, no fleet handle) for the direct callers — the CLI,
    fixtures, and any path that has not been switched onto the queue.
    """
    job_id = job_id if job_id is not None else new_id("ingest")
    await conn.execute(
        text(
            """
            INSERT INTO design_ingestion_job (
              job_id, workspace_id, kind, status, stage, progress, request_json, work_id
            )
            VALUES (:j, :w, CAST(:kind AS design_ingestion_kind),
                    CAST('queued' AS design_ingestion_status), NULL, 0,
                    CAST(:request AS jsonb), :work_id)
            """
        ),
        {
            "j": job_id,
            "w": workspace_id,
            "kind": kind,
            "request": dump_json(request),
            "work_id": work_id,
        },
    )
    return await require_job(conn, workspace_id=workspace_id, job_id=job_id)


async def update_request(
    conn: AsyncConnection, *, workspace_id: str, job_id: str, request: JsonObject
) -> JsonObject:
    """Replace the stored request (e.g. recording a tmp-file path once it is known).

    Terminal columns are untouched — the ported semantics exactly.
    """
    await conn.execute(
        text(
            "UPDATE design_ingestion_job SET request_json = CAST(:request AS jsonb),"
            " updated_at = now() WHERE job_id = :j AND workspace_id = :w"
        ),
        {"request": dump_json(request), "j": job_id, "w": workspace_id},
    )
    return await require_job(conn, workspace_id=workspace_id, job_id=job_id)


async def list_recent(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    limit: int = 50,
    kinds: Sequence[str] | None = None,
) -> list[JsonObject]:
    """Most-recent jobs first (created_at DESC, job_id DESC as the ported tiebreak).

    ``kinds`` narrows the read to those ingestion kinds; ``None`` is every kind.
    """
    kind_clause = " AND kind::text = ANY(:kinds)" if kinds is not None else ""
    params: dict[str, Any] = {"w": workspace_id, "limit": limit}
    if kinds is not None:
        params["kinds"] = list(kinds)
    rows = await conn.execute(
        text(
            "SELECT * FROM design_ingestion_job WHERE workspace_id = :w"
            + kind_clause
            + " ORDER BY created_at DESC, job_id DESC LIMIT :limit"
        ),
        params,
    )
    return [_job_from_row(row) for row in rows]


async def _current_lease_generation(
    conn: AsyncConnection, *, workspace_id: str, job_id: str
) -> int | None:
    row = (
        await conn.execute(
            text(
                "SELECT lease_generation FROM design_ingestion_job"
                " WHERE job_id = :j AND workspace_id = :w"
            ),
            {"j": job_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("ingestion_job", job_id)
    generation: int | None = row.lease_generation
    return generation


def _fence_clause(expected_generation: int | None) -> str:
    """The trailing predicate that makes a write refuse once the row's lease has moved on.

    ``<=`` rather than ``=`` on the permitted side, and NULL passes: the in-flight holder is the
    row's own generation, and a row that was never claimed (a direct, queue-less caller) has
    nothing to be fenced by. See :func:`clue_design.runs.set_run_result` — identical rule.
    """
    if expected_generation is None:
        return ""
    return " AND (lease_generation IS NULL OR lease_generation <= :gen)"


async def _write_or_fence(
    conn: AsyncConnection,
    statement: str,
    params: dict[str, Any],
    *,
    workspace_id: str,
    job_id: str,
    expected_generation: int | None,
) -> JsonObject:
    """Run one fenced UPDATE and read the job back, or raise the right refusal.

    An UPDATE that matched nothing is genuinely ambiguous — the job may be absent, in another
    workspace, or owned by a newer lease — so the two are separated here rather than collapsed:
    an absent job is a caller bug (:class:`DesignNotFoundError`), a fenced-out job is the expected
    outcome of a takeover (:class:`DesignJobFencedError`) and its writer must stop, not retry.
    """
    outcome = await conn.execute(
        text(statement + _fence_clause(expected_generation)),
        params if expected_generation is None else {**params, "gen": expected_generation},
    )
    if outcome.rowcount == 0 and expected_generation is not None:
        current = await _current_lease_generation(conn, workspace_id=workspace_id, job_id=job_id)
        raise DesignJobFencedError(job_id, expected_generation, current)
    return await require_job(conn, workspace_id=workspace_id, job_id=job_id)


async def set_running(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    job_id: str,
    expected_generation: int | None = None,
) -> JsonObject:
    return await _write_or_fence(
        conn,
        "UPDATE design_ingestion_job"
        " SET status = CAST('running' AS design_ingestion_status), updated_at = now()"
        " WHERE job_id = :j AND workspace_id = :w",
        {"j": job_id, "w": workspace_id},
        workspace_id=workspace_id,
        job_id=job_id,
        expected_generation=expected_generation,
    )


async def set_stage(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    job_id: str,
    stage: str,
    progress: float,
    expected_generation: int | None = None,
) -> JsonObject:
    """The progress reporter's write. ``progress`` is CHECK-bounded to [0, 1] by the schema."""
    return await _write_or_fence(
        conn,
        "UPDATE design_ingestion_job SET stage = :stage, progress = :progress,"
        " updated_at = now() WHERE job_id = :j AND workspace_id = :w",
        {"stage": stage, "progress": progress, "j": job_id, "w": workspace_id},
        workspace_id=workspace_id,
        job_id=job_id,
        expected_generation=expected_generation,
    )


async def complete(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    job_id: str,
    brand_kit_id: str | None,
    version: int | None,
    evidence_json: str | None,
    expected_generation: int | None = None,
) -> JsonObject:
    """Terminal success: the result pointer + the (already-serialized) evidence document.

    ``evidence_json`` is a JSON *string* in the ported contract (the pipeline dumps the evidence
    once and hands the text through), so it is cast straight to ``jsonb`` rather than re-encoded.
    The composite FK means an unknown ``(brand_kit_id, version)`` in this workspace fails loudly
    here instead of leaving a job pointing at nothing.

    ``expected_generation`` (D5 Round C) is the zombie fence — an abandoned ingestion thread must
    not stamp its result over the takeover worker's.

    The status is derived HERE, from the evidence itself (spec 2026-10-25 §5.1): a non-empty
    ``gaps`` list — failed descriptions, ad analyses, card, brief or grammar audit — makes the job
    ``succeeded_with_gaps``, everything else ``succeeded``. One place decides, so a producer that
    records a gap cannot also forget to say so in the status.
    """
    return await _write_or_fence(
        conn,
        """
        UPDATE design_ingestion_job
        SET status = CAST(
              CASE WHEN jsonb_typeof(CAST(:evidence AS jsonb) -> 'gaps') = 'array'
                        AND jsonb_array_length(CAST(:evidence AS jsonb) -> 'gaps') > 0
                   THEN 'succeeded_with_gaps' ELSE 'succeeded' END
              AS design_ingestion_status),
            progress = 1,
            brand_kit_id = :b, brand_kit_version = :v,
            evidence_json = CAST(:evidence AS jsonb), updated_at = now()
        WHERE job_id = :j AND workspace_id = :w
        """,
        {
            "b": brand_kit_id,
            "v": version,
            "evidence": evidence_json,
            "j": job_id,
            "w": workspace_id,
        },
        workspace_id=workspace_id,
        job_id=job_id,
        expected_generation=expected_generation,
    )


async def fail(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    job_id: str,
    error: JsonObject | None,
    expected_generation: int | None = None,
) -> JsonObject:
    """Terminal failure: the typed error object (progress/stage keep their last values)."""
    result = await _write_or_fence(
        conn,
        "UPDATE design_ingestion_job"
        " SET status = CAST('failed' AS design_ingestion_status),"
        " error_json = CAST(:error AS jsonb), updated_at = now()"
        " WHERE job_id = :j AND workspace_id = :w",
        {"error": dump_json_opt(error), "j": job_id, "w": workspace_id},
        workspace_id=workspace_id,
        job_id=job_id,
        expected_generation=expected_generation,
    )

    from clue_design.descriptions import fail_queued_analysis

    await fail_queued_analysis(
        conn,
        workspace_id=workspace_id,
        asset_ids=None,
        job_id=job_id,
        reason=(error or {}).get("message", "Ingestion job failed; analysis can be retried"),
    )
    return result


# --- the durable-job surface (D5): the fleet handle + the requeue-safe input read --------------


async def set_work_id(
    conn: AsyncConnection, *, workspace_id: str, job_id: str, work_id: UUID
) -> JsonObject:
    """Stamp the fleet work id this job was dispatched under.

    A separate write rather than a ``create_job`` argument because the two events are genuinely
    separate: the job row must exist (and own its staged inputs) *before* anything is enqueued,
    or a worker could claim a task whose job is not yet visible.

    Idempotent for the same value. Re-stamping a *different* work id repoints the job at the new
    task (last write wins) — deliberate, so a requeue after a failed dispatch is a plain update;
    what the partial UNIQUE index forbids is the dangerous direction, two different jobs claiming
    the same work id. Fail-closed on workspace: an update scoped to another tenant writes nothing
    and the read-back raises.
    """
    await conn.execute(
        text(
            "UPDATE design_ingestion_job SET work_id = :work_id, updated_at = now()"
            " WHERE job_id = :j AND workspace_id = :w"
        ),
        {"work_id": work_id, "j": job_id, "w": workspace_id},
    )
    return await require_job(conn, workspace_id=workspace_id, job_id=job_id)


async def get_job_by_work_id(conn: AsyncConnection, *, work_id: UUID) -> JsonObject | None:
    """Resolve a fleet work id to its job, or ``None``.

    Fleet-plane, so deliberately **not** workspace-scoped — a worker pulling a task holds a work
    id and nothing else, and the workspace is what this read is *for* (the same structural
    exemption as :func:`clue_design.runs.get_run_by_work_id`). ``work_id`` is unique among
    stamped jobs (``design_ingestion_job_work_id``) and unguessable; ``workspace_id`` rides in
    the result so the caller continues through a workspace-CORRECT store.
    """
    row = (
        await conn.execute(
            text("SELECT * FROM design_ingestion_job WHERE work_id = :work_id"),
            {"work_id": work_id},
        )
    ).first()
    if row is None:
        return None
    return _job_execution_from_row(row)


def _job_execution_from_row(row: Any) -> JsonObject:
    """The durable-job view of an ingestion job — what a worker and the reaper need.

    The shipped job DTO plus the fleet-plane columns (tenancy anchor, work handle, lease trio,
    re-offer counter). Kept separate from :func:`_job_from_row` for the same reason
    ``clue_design.runs`` keeps two mappers: the public DTO is a shipped response shape and must
    not silently grow durable-execution internals.
    """
    job = _job_from_row(row)
    job["workspace_id"] = row.workspace_id
    job["work_id"] = None if row.work_id is None else str(row.work_id)
    job["leased_by"] = row.leased_by
    job["lease_generation"] = row.lease_generation
    job["leased_at"] = iso(row.leased_at)
    job["reoffer_count"] = row.reoffer_count
    return job


async def claim_job_for_execution(
    conn: AsyncConnection, *, work_id: UUID, worker_id: str, lease_generation: int
) -> JsonObject | None:
    """Claim an ingestion job for execution under ``lease_generation``; the durable-job CAS.

    The exact twin of :func:`clue_design.runs.claim_run_for_execution`, deliberately — a design
    turn and a brand-kit ingestion are two shapes of the SAME mechanical fleet kind
    (``design_job``), so they must agree on what claiming means:

    * **queued → running.** The route enqueued the work, this worker took it.
    * **Same generation re-claims (idempotent)** — at-least-once redelivery of a task whose lease
      this worker already holds must not stall it.
    * **A HIGHER generation may re-claim a ``running`` row (takeover).** Generations are issued
      monotonically by the platform lease, so holding a newer one is proof the previous holder's
      lease expired. This is the case that matters for a *re-offered* job: the reaper hands a
      stranded row back to ``queued`` with its lease cleared, and the next claimant — arriving
      under whatever generation the platform grants it — takes it either way (NULL passes too).
    * **A LOWER generation is refused** (``None``): that claimant has been fenced out.

    Terminal jobs (``succeeded`` / ``failed``) are never re-claimed. An unknown ``work_id`` raises
    :class:`DesignNotFoundError` — a poison task is a different answer from "someone else owns
    this", and the handler treats it differently (finalize, never requeue).

    Fleet-plane, so unscoped by workspace: a worker holds a work id and nothing else, and the
    workspace is what this call *returns*.
    """
    row = (
        await conn.execute(
            text(
                "UPDATE design_ingestion_job"
                " SET status = CAST('running' AS design_ingestion_status),"
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
        return _job_execution_from_row(row)
    if await get_job_by_work_id(conn, work_id=work_id) is None:
        raise DesignNotFoundError("ingestion_job", str(work_id))
    return None


async def read_staged_request(
    conn: AsyncConnection, *, workspace_id: str, job_id: str
) -> JsonObject:
    """The job's staged input request — safe to call any number of times, at any status.

    This is the read a **requeued** worker performs: after a restart or a takeover the worker
    knows only the job id, and it must recover the same inputs the original attempt had. That
    works because the request is immutable-in-practice staged state — since D4 its uploads are
    platform-storage digests, not ``tmp_path``s that a restart would have lost — and because
    this read touches nothing: no status transition, no ``updated_at`` bump, no progress reset.
    Re-reading is therefore not a retry side effect, which is exactly what makes a requeue safe.

    Raises :class:`DesignNotFoundError` for an unknown or cross-workspace job (fail-closed). The
    ``or {}`` below is unreachable in practice — ``request_json`` is ``NOT NULL`` — and is there
    only so a decode returning ``None`` cannot hand a caller ``None`` typed as an object.
    """
    row = (
        await conn.execute(
            text(
                "SELECT request_json FROM design_ingestion_job"
                " WHERE job_id = :j AND workspace_id = :w"
            ),
            {"j": job_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("ingestion_job", job_id)
    request: JsonObject = load_json_opt(row.request_json) or {}
    return request


# --- the stranded-work surface (D5 Round C) ----------------------------------------------------
#
# S4 boundary: these three read and write the DESIGN row only. Whether a stranded-looking job's
# fleet task is actually dead — the queue state and the live-lease check — is decided by the
# reaper at the composition root and passed IN as a decision, because ``clue_design`` may not
# learn that ``clue_fleet`` exists.


async def list_dispatched_running_jobs(conn: AsyncConnection) -> list[JsonObject]:
    """Every fleet-DISPATCHED job currently ``running``, across all workspaces — reaper input.

    Unscoped by workspace for the same structural reason as :func:`get_job_by_work_id`: a
    stranded job belongs to whichever tenant owns it, and a per-tenant sweep would leave every
    other tenant's jobs stuck ``running`` forever. Nothing here writes and no staged request is
    returned — only the identifiers and lease facts the reaper needs to make its decision.

    ``work_id IS NOT NULL`` is the filter that keeps this honest: a job that was never offered to
    the fleet (a direct/CLI run) has no task to be judged against, so the reaper must not touch it.
    """
    rows = (
        await conn.execute(
            text(
                "SELECT job_id, workspace_id, kind, work_id, leased_by, lease_generation,"
                "       leased_at, reoffer_count, updated_at"
                " FROM design_ingestion_job"
                " WHERE status = 'running' AND work_id IS NOT NULL"
                " ORDER BY updated_at ASC, job_id ASC"
            )
        )
    ).fetchall()
    return [
        {
            "job_id": row.job_id,
            "workspace_id": row.workspace_id,
            "kind": row.kind,
            "work_id": str(row.work_id),
            "leased_by": row.leased_by,
            "lease_generation": row.lease_generation,
            "leased_at": iso(row.leased_at),
            "reoffer_count": row.reoffer_count,
            "updated_at": iso(row.updated_at),
        }
        for row in rows
    ]


async def reoffer_stranded_job(
    conn: AsyncConnection, *, work_id: UUID, max_reoffers: int = 1
) -> JsonObject | None:
    """Hand a stranded ``running`` job back to ``queued`` so a worker can claim it again.

    One CAS statement, and the ``reoffer_count < :max`` predicate is the bound: the counter is a
    durable column precisely because a process-local "I already retried this" dies with the
    process whose death caused the strand. ``None`` means the CAS refused — the job stopped being
    ``running`` (someone finished it), or its re-offer budget is spent and the caller must
    terminalize it instead.

    The lease trio is CLEARED, not left behind: the row is genuinely unowned again, and a stale
    ``lease_generation`` would fence the very writes the next claimant is supposed to make.
    """
    row = (
        await conn.execute(
            text(
                "UPDATE design_ingestion_job"
                " SET status = CAST('queued' AS design_ingestion_status),"
                "     leased_by = NULL, lease_generation = NULL, leased_at = NULL,"
                "     reoffer_count = reoffer_count + 1, updated_at = now()"
                " WHERE work_id = :work_id AND status = 'running'"
                "   AND reoffer_count < :max"
                " RETURNING *"
            ),
            {"work_id": work_id, "max": max_reoffers},
        )
    ).first()
    return None if row is None else _job_execution_from_row(row)


async def list_dispatched_queued_jobs(conn: AsyncConnection) -> list[JsonObject]:
    """Every fleet-DISPATCHED job still ``queued``, across all workspaces — reaper input (R3-B).

    The twin of :func:`list_dispatched_running_jobs`, and it exists because ``running`` is not
    the only status a job can be abandoned in. A worker that fails *before* the claim CAS — the
    envelope will not parse in this build, the claim read itself faults — leaves the job exactly
    where the route left it, ``queued`` with ``error_json`` NULL, while its fleet task ends
    terminally FAILED. Nothing then re-offers the task and nothing fails the job, so a client
    polling the documented endpoint waits on a job that died in half a second. The W5 acceptance
    walk watched one such row for nine minutes.

    Same two honesty filters as the running twin: ``work_id IS NOT NULL`` (a job never offered
    to the fleet has no task to be judged against) and no staged request in the result.
    """
    rows = (
        await conn.execute(
            text(
                "SELECT job_id, workspace_id, kind, work_id, leased_by, lease_generation,"
                "       leased_at, reoffer_count, updated_at"
                " FROM design_ingestion_job"
                " WHERE status = 'queued' AND work_id IS NOT NULL"
                " ORDER BY updated_at ASC, job_id ASC"
            )
        )
    ).fetchall()
    return [
        {
            "job_id": row.job_id,
            "workspace_id": row.workspace_id,
            "kind": row.kind,
            "work_id": str(row.work_id),
            "leased_by": row.leased_by,
            "lease_generation": row.lease_generation,
            "leased_at": iso(row.leased_at),
            "reoffer_count": row.reoffer_count,
            "updated_at": iso(row.updated_at),
        }
        for row in rows
    ]


async def fail_dispatched_job(
    conn: AsyncConnection,
    *,
    work_id: UUID,
    error: JsonObject,
    lease_generation: int | None = None,
) -> JsonObject | None:
    """Terminalize a dispatched job ``failed`` from the FLEET plane, keyed on work id (R3-B).

    The reconciliation write. Unlike :func:`fail` it takes no workspace and no job id — the
    caller is a worker or a sweep that holds a work id and nothing else — and unlike
    :func:`fail_stranded_job` it accepts a ``queued`` row as well as a ``running`` one, because
    the defect it repairs is precisely a job that never left ``queued`` while its task died.

    ``None`` means the write was refused and the caller must not treat the job as failed:

    * the row is already terminal (its real outcome stands — a reconciliation never overwrites
      one), or
    * a NEWER lease generation owns it. The fence predicate is the claim CAS's own
      (``lease_generation IS NULL OR lease_generation <= :gen``), so a worker that could not run
      this job cannot stamp ``failed`` over the row a capable takeover is already executing.
      ``lease_generation=None`` skips the fence — the sweep's stance, which judges by task state
      and live-lease absence instead.
    """
    fence = (
        ""
        if lease_generation is None
        else " AND (lease_generation IS NULL OR lease_generation <= :gen)"
    )
    params: dict[str, Any] = {"work_id": work_id, "error": dump_json(error)}
    if lease_generation is not None:
        params["gen"] = lease_generation
    row = (
        await conn.execute(
            text(
                "UPDATE design_ingestion_job"
                " SET status = CAST('failed' AS design_ingestion_status),"
                "     error_json = CAST(:error AS jsonb), updated_at = now()"
                " WHERE work_id = :work_id AND status IN ('queued', 'running')"
                + fence
                + " RETURNING *"
            ),
            params,
        )
    ).first()
    if row is not None:
        from clue_design.descriptions import fail_queued_analysis

        await fail_queued_analysis(
            conn,
            workspace_id=row.workspace_id,
            asset_ids=None,
            job_id=row.job_id,
            reason=error.get("message", "Ingestion job failed; analysis can be retried"),
        )
    return None if row is None else _job_execution_from_row(row)


async def fail_stranded_job(
    conn: AsyncConnection, *, work_id: UUID, error: JsonObject
) -> JsonObject | None:
    """Terminalize a stranded job ``failed`` with the reaper's error envelope.

    Guarded on ``status = 'running'`` so a job that finished between the reaper's read and its
    write is left alone — the reaper never overwrites a real outcome with ``stranded``.
    """
    row = (
        await conn.execute(
            text(
                "UPDATE design_ingestion_job"
                " SET status = CAST('failed' AS design_ingestion_status),"
                "     error_json = CAST(:error AS jsonb), updated_at = now()"
                " WHERE work_id = :work_id AND status = 'running'"
                " RETURNING *"
            ),
            {"work_id": work_id, "error": dump_json(error)},
        )
    ).first()
    if row is not None:
        from clue_design.descriptions import fail_queued_analysis

        await fail_queued_analysis(
            conn,
            workspace_id=row.workspace_id,
            asset_ids=None,
            job_id=row.job_id,
            reason=error.get("message", "Ingestion job failed; analysis can be retried"),
        )
    return None if row is None else _job_execution_from_row(row)
