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

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits. The mapper reproduces ``jobs._job_from_row`` exactly.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, dump_json_opt, iso, load_json_opt
from clue_design.errors import DesignNotFoundError


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
    conn: AsyncConnection, *, workspace_id: str, kind: str, request: JsonObject
) -> JsonObject:
    """Queue one job (``status='queued'``, ``progress=0``, no stage/result/error yet)."""
    job_id = new_id("ingest")
    await conn.execute(
        text(
            """
            INSERT INTO design_ingestion_job (
              job_id, workspace_id, kind, status, stage, progress, request_json
            )
            VALUES (:j, :w, CAST(:kind AS design_ingestion_kind),
                    CAST('queued' AS design_ingestion_status), NULL, 0,
                    CAST(:request AS jsonb))
            """
        ),
        {"j": job_id, "w": workspace_id, "kind": kind, "request": dump_json(request)},
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
    conn: AsyncConnection, *, workspace_id: str, limit: int = 50
) -> list[JsonObject]:
    """Most-recent jobs first (created_at DESC, job_id DESC as the ported tiebreak)."""
    rows = await conn.execute(
        text(
            "SELECT * FROM design_ingestion_job WHERE workspace_id = :w"
            " ORDER BY created_at DESC, job_id DESC LIMIT :limit"
        ),
        {"w": workspace_id, "limit": limit},
    )
    return [_job_from_row(row) for row in rows]


async def set_running(conn: AsyncConnection, *, workspace_id: str, job_id: str) -> JsonObject:
    await conn.execute(
        text(
            "UPDATE design_ingestion_job"
            " SET status = CAST('running' AS design_ingestion_status), updated_at = now()"
            " WHERE job_id = :j AND workspace_id = :w"
        ),
        {"j": job_id, "w": workspace_id},
    )
    return await require_job(conn, workspace_id=workspace_id, job_id=job_id)


async def set_stage(
    conn: AsyncConnection, *, workspace_id: str, job_id: str, stage: str, progress: float
) -> JsonObject:
    """The progress reporter's write. ``progress`` is CHECK-bounded to [0, 1] by the schema."""
    await conn.execute(
        text(
            "UPDATE design_ingestion_job SET stage = :stage, progress = :progress,"
            " updated_at = now() WHERE job_id = :j AND workspace_id = :w"
        ),
        {"stage": stage, "progress": progress, "j": job_id, "w": workspace_id},
    )
    return await require_job(conn, workspace_id=workspace_id, job_id=job_id)


async def complete(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    job_id: str,
    brand_kit_id: str,
    version: int,
    evidence_json: str | None,
) -> JsonObject:
    """Terminal success: the result pointer + the (already-serialized) evidence document.

    ``evidence_json`` is a JSON *string* in the ported contract (the pipeline dumps the evidence
    once and hands the text through), so it is cast straight to ``jsonb`` rather than re-encoded.
    The composite FK means an unknown ``(brand_kit_id, version)`` in this workspace fails loudly
    here instead of leaving a job pointing at nothing.
    """
    await conn.execute(
        text(
            """
            UPDATE design_ingestion_job
            SET status = CAST('succeeded' AS design_ingestion_status), progress = 1,
                brand_kit_id = :b, brand_kit_version = :v,
                evidence_json = CAST(:evidence AS jsonb), updated_at = now()
            WHERE job_id = :j AND workspace_id = :w
            """
        ),
        {
            "b": brand_kit_id,
            "v": version,
            "evidence": evidence_json,
            "j": job_id,
            "w": workspace_id,
        },
    )
    return await require_job(conn, workspace_id=workspace_id, job_id=job_id)


async def fail(
    conn: AsyncConnection, *, workspace_id: str, job_id: str, error: JsonObject | None
) -> JsonObject:
    """Terminal failure: the typed error object (progress/stage keep their last values)."""
    await conn.execute(
        text(
            "UPDATE design_ingestion_job"
            " SET status = CAST('failed' AS design_ingestion_status),"
            " error_json = CAST(:error AS jsonb), updated_at = now()"
            " WHERE job_id = :j AND workspace_id = :w"
        ),
        {"error": dump_json_opt(error), "j": job_id, "w": workspace_id},
    )
    return await require_job(conn, workspace_id=workspace_id, job_id=job_id)
