"""Shared recording ownership; no change to AI Ark's job-scoped operation keys."""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from clue_api.arv2 import media_store as store
from clue_api.arv2 import media_telemetry as telemetry
from clue_api.arv2.research_operations import fingerprint, job_available
from clue_obs.langfuse import observation

active_resolution: ContextVar[list[str] | None] = ContextVar("arv2_media_resolution", default=None)

active_operation: ContextVar[UUID | None] = ContextVar("arv2_media_operation", default=None)


async def used_seconds(runtime: Any, conn: Any) -> int:
    """Media seconds this job has reserved or spent (failed steps hold none)."""
    return int(
        (
            await conn.execute(
                text("""SELECT COALESCE(sum(seconds),0) FROM arv2_media_operation
      WHERE workspace_id=:ws AND owner_job=:job AND state<>'failed'"""),
                {"ws": runtime.scope.workspace_id, "job": runtime.scope.job_id},
            )
        ).scalar_one()
    )


async def begin(
    runtime: Any, conn: Any, *, item_id: UUID, stage: str, request: dict[str, Any], seconds: int = 0
) -> tuple[dict[str, Any], bool]:
    await store.authority(runtime, conn)
    ws, job = runtime.scope.workspace_id, runtime.scope.job_id
    # Serialize source ownership and the owner's aggregate allowance across worker restarts.
    for key in sorted([f"media-source:{ws}:{item_id}", f"media-job:{ws}:{job}"]):
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key}
        )
    generation = (
        await conn.execute(
            text(
                "SELECT acquisition_generation FROM arv2_media_item WHERE "
                "workspace_id=:ws AND item_id=:id"
            ),
            {"ws": ws, "id": item_id},
        )
    ).scalar_one()
    params = {
        "ws": ws,
        "item": item_id,
        "stage": stage,
        "fp": fingerprint({**request, "acquisition_generation": generation}),
    }
    row = (
        (
            await conn.execute(
                text("""SELECT * FROM arv2_media_operation WHERE workspace_id=:ws
      AND item_id=:item AND stage=:stage AND fingerprint=:fp FOR UPDATE"""),
                params,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row:
        if row["state"] == "reserved":
            reclaimed = (
                (
                    await conn.execute(
                        text("""UPDATE arv2_media_operation SET owner_token=:owner,
                      lease_until=now()+interval '2 hours'
                      WHERE workspace_id=:ws AND operation_id=:id
                        AND state='reserved' AND lease_until<now() RETURNING *"""),
                        {"ws": ws, "id": row["operation_id"], "owner": uuid4()},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if reclaimed:
                # No dispatch occurred. The old owner's CAS can no longer send this request.
                decision(runtime, reclaimed, "reclaimed")
                return dict(reclaimed), True
        if row["state"] in ("reserved", "dispatched"):
            await conn.execute(
                text("""UPDATE arv2_media_operation SET
        state='unknown',error_code='dispatch_outcome_unknown'
              WHERE workspace_id=:ws AND operation_id=:id AND lease_until<now()"""),
                {"ws": ws, "id": row["operation_id"]},
            )
            row = (
                (
                    await conn.execute(
                        text(
                            (
                                "SELECT * FROM arv2_media_operation WHERE workspace_id=:ws AND "
                                "operation_id=:id"
                            )
                        ),
                        {"ws": ws, "id": row["operation_id"]},
                    )
                )
                .mappings()
                .one()
            )
        decision(runtime, row, "reuse_or_wait")
        return dict(row), False
    used = await used_seconds(runtime, conn)
    if used + seconds > runtime.settings.arv2_media_seconds_ceiling:
        telemetry.record(
            runtime,
            "allowance_refused",
            warning=True,
            stage=stage,
            item_id=str(item_id),
            used_seconds=used,
            requested_seconds=seconds,
        )
        raise store.unavailable("durable job media-seconds allowance exceeded")
    params.update(id=uuid4(), job=job, owner=uuid4(), seconds=seconds)
    row = (
        (
            await conn.execute(
                text("""INSERT INTO arv2_media_operation
      (workspace_id,operation_id,item_id,owner_job,fingerprint,stage,owner_token,seconds)
      SELECT :ws,:id,:item,:job,:fp,:stage,:owner,:seconds FROM arv2_media_item
      WHERE workspace_id=:ws AND item_id=:item AND erased_at IS NULL AND expires_at>now()
      RETURNING *"""),
                params,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise store.unavailable()
    decision(runtime, row, "reserved")
    return dict(row), True


def decision(runtime: Any, op: Any, outcome: str) -> None:
    # This is an observed ownership decision within a transaction, not a second state store.
    telemetry.record(
        runtime,
        "operation_decision",
        operation_id=str(op["operation_id"]),
        item_id=str(op["item_id"]),
        owner_job=str(op["owner_job"]),
        stage=op["stage"],
        state=op["state"],
        decision=outcome,
    )


async def dispatch(runtime: Any, conn: Any, op: dict[str, Any]) -> None:
    await store.authority(runtime, conn)
    updated = await conn.execute(
        text("""UPDATE arv2_media_operation SET state='dispatched'
      WHERE workspace_id=:ws AND operation_id=:id AND owner_token=:owner AND
        state='reserved'"""),
        {"ws": runtime.scope.workspace_id, "id": op["operation_id"], "owner": op["owner_token"]},
    )
    if updated.rowcount != 1:
        raise store.unavailable("media dispatch ownership lost")


async def attach_receipts(
    runtime: Any, conn: Any, keys: list[str], ledger_ids: list[UUID], error: str | None
) -> None:
    """Invoked by the existing shielded raw/ledger drain, including late and failed responses."""
    capture = active_resolution.get()
    if capture is not None:
        capture.extend(keys)
        for key in keys:
            await store.subjects(runtime, conn, key, [])
    oid = active_operation.get()
    if oid is None:
        return
    ws = runtime.scope.workspace_id
    row = (
        (
            await conn.execute(
                text("""UPDATE arv2_media_operation SET artifact_keys=artifact_keys ||
        CAST(:keys AS text[]),
      ledger_ids=ledger_ids || CAST(:ledgers AS uuid[]),error_code=:error
      WHERE workspace_id=:ws AND operation_id=:id RETURNING item_id,state"""),
                {"ws": ws, "id": oid, "keys": keys, "ledgers": ledger_ids, "error": error},
            )
        )
        .mappings()
        .one()
    )
    metadata = (
        await conn.execute(
            text("SELECT metadata FROM arv2_media_item WHERE workspace_id=:ws AND item_id=:item"),
            {"ws": ws, "item": row["item_id"]},
        )
    ).scalar_one()
    recognized = [("linkedin:" + url, url) for url in metadata.get("recognized_subject_urls", [])]
    for key in keys:
        await store.subjects(runtime, conn, key, recognized)
    telemetry.record(
        runtime,
        "receipts_attached",
        operation_id=str(oid),
        ledger_ids=[str(value) for value in ledger_ids],
        artifact_count=len(keys),
        error_code=error,
    )
    if row["state"] == "unavailable" or not await job_available(conn, runtime.operation_scope):
        await conn.execute(
            text(
                "UPDATE artifact SET "
                "erased_at=now(),privacy_erased=true,"
                "erasure_reason='privacy',source_url=NULL WHERE "
                "workspace_id=:ws AND storage_key=ANY(:keys)"
            ),
            {"ws": ws, "keys": keys},
        )


async def finish(
    runtime: Any,
    conn: Any,
    op: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    known_failure: bool = False,
) -> None:
    state = "succeeded" if error is None else "failed" if known_failure else "unknown"
    await conn.execute(
        text("""UPDATE arv2_media_operation SET state=:state,result=CAST(:result AS
        jsonb),error_code=:error
      WHERE workspace_id=:ws AND operation_id=:id AND owner_token=:owner AND state IN
        ('reserved','dispatched','unknown')"""),
        {
            "ws": runtime.scope.workspace_id,
            "id": op["operation_id"],
            "owner": op["owner_token"],
            "state": state,
            "result": json.dumps(result or {}, default=str),
            "error": error,
        },
    )


async def settle_seconds(runtime: Any, conn: Any, op: dict[str, Any], seconds: int) -> None:
    """A step reserved an estimate of the recording's length (a link-fed transcription); once
    the provider has measured it, the job's allowance holds the measured length."""
    await conn.execute(
        text("""UPDATE arv2_media_operation SET seconds=:seconds
      WHERE workspace_id=:ws AND operation_id=:id AND owner_token=:owner"""),
        {
            "ws": runtime.scope.workspace_id,
            "id": op["operation_id"],
            "owner": op["owner_token"],
            "seconds": seconds,
        },
    )


async def call(runtime: Any, op: dict[str, Any], provider: str, fn: Any) -> Any:
    async with runtime._conn_factory() as conn:
        await dispatch(runtime, conn, op)
    token = active_operation.set(op["operation_id"])
    try:
        with observation(
            "arv2.media.provider_stage",
            as_type="span",
            metadata={
                **telemetry.scope(runtime),
                "operation_id": str(op["operation_id"]),
                "item_id": str(op["item_id"]),
                "stage": op["stage"],
                "provider": provider,
            },
        ) as current:
            telemetry.record(
                runtime,
                "provider_stage_started",
                operation_id=str(op["operation_id"]),
                item_id=str(op["item_id"]),
                stage=op["stage"],
                provider=provider,
            )
            try:
                result = await runtime.call_provider(provider, fn)
            except Exception as exc:
                status = getattr(exc, "http_status", None)
                known_rejection = status in {400, 404, 413, 415, 422}
                async with runtime._conn_factory() as conn:
                    await finish(
                        runtime, conn, op, error=type(exc).__name__, known_failure=known_rejection
                    )
                    if known_rejection:
                        await store.release_item(runtime, conn, op["item_id"])
                state = "failed" if known_rejection else "unknown"
                current.update(
                    level="ERROR", status_message=type(exc).__name__, output={"state": state}
                )
                telemetry.record(
                    runtime,
                    "provider_stage_failed",
                    warning=True,
                    operation_id=str(op["operation_id"]),
                    stage=op["stage"],
                    state=state,
                    error_code=type(exc).__name__,
                )
                raise
            current.update(output={"state": "provider_returned"})
            telemetry.record(
                runtime,
                "provider_stage_completed",
                operation_id=str(op["operation_id"]),
                stage=op["stage"],
                state="provider_returned",
            )
            return result
    finally:
        active_operation.reset(token)
