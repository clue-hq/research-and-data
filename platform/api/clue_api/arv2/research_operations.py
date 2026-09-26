"""Durable references for ARV2 v2 paid operations. The shared ledger owns spend.

Only references and outcome codes live here. Replay reads the original, integrity-checked raw
artifact, never a copied profile in job JSON. An ambiguous dispatch is not automatically retried.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_refusals import RefusalError
from clue_api.arv2.ai_ark_research import enrichment_only
from clue_api.arv2.provider_ledger import ledger_id_for
from clue_api.arv2.sinks import LedgerRow
from clue_core import decode_jsonb
from clue_storage import StorageBackend, read_verified_artifact


def fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True)
class OperationScope:
    workspace_id: str
    run_id: UUID
    job_id: UUID
    account_id: UUID


@dataclass(frozen=True)
class Operation:
    operation_id: UUID
    kind: str
    state: str
    artifact_key: str | None
    ledger_id: UUID | None
    error_code: str | None
    owner_token: UUID
    request_data: Mapping[str, Any] | None = None


def _operation(row: Mapping[str, Any]) -> Operation:
    return Operation(**{key: row[key] for key in Operation.__dataclass_fields__ if key in row})


async def begin(
    conn: AsyncConnection,
    scope: OperationScope,
    kind: str,
    request: Mapping[str, Any],
) -> tuple[Operation, bool]:
    digest = fingerprint(request)
    oid = uuid5(
        NAMESPACE_URL, f"arv2-operation:v1:{scope.workspace_id}:{scope.job_id}:{kind}:{digest}"
    )
    owner = uuid4()
    result = await conn.execute(
        text("""
        INSERT INTO arv2_research_operation
          (operation_id,workspace_id,run_id,job_id,account_id,kind,request_sha256,
           owner_token,lease_until)
        SELECT :id,:ws,:run,:job,:account,:kind,:sha,:owner,now()+interval '2 hours'
        FROM arv2_research_job j WHERE j.job_id=:job AND j.workspace_id=:ws
          AND j.run_id=:run AND j.account_entity_id=:account
        ON CONFLICT DO NOTHING RETURNING operation_id
    """),
        {
            "id": oid,
            "ws": scope.workspace_id,
            "run": scope.run_id,
            "job": scope.job_id,
            "account": scope.account_id,
            "kind": kind,
            "sha": digest,
            "owner": owner,
        },
    )
    won = result.scalar_one_or_none() is not None
    await conn.execute(
        text("""
        UPDATE arv2_research_operation SET
        state='unknown',error_code='dispatch_outcome_unknown'
        WHERE operation_id=:id AND workspace_id=:ws AND state='running' AND lease_until<now()
    """),
        {"id": oid, "ws": scope.workspace_id},
    )
    return await get(conn, scope, oid), won


async def get(conn: AsyncConnection, scope: OperationScope, oid: UUID) -> Operation:
    row = (
        (
            await conn.execute(
                text("""
        SELECT * FROM arv2_research_operation WHERE operation_id=:id AND workspace_id=:ws
          AND run_id=:run AND job_id=:job AND account_id=:account
    """),
                {
                    "id": oid,
                    "ws": scope.workspace_id,
                    "run": scope.run_id,
                    "job": scope.job_id,
                    "account": scope.account_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise RefusalError(
            "subject_lock_failed", "operation does not belong to this research subject"
        )
    return _operation(dict(row))


async def finish(
    conn: AsyncConnection,
    scope: OperationScope,
    operation: Operation,
    rows: tuple[LedgerRow, ...],
    *,
    error: str | None = None,
    preferred_row: str | None = None,
    semantic_empty: bool = False,
) -> None:
    row = next((r for r in rows if r.row_id == preferred_row), rows[-1] if rows else None)
    ledger_id = ledger_id_for(row.row_id) if row else None
    status = row.http_status if row else None
    state = "succeeded" if status is not None and 200 <= status < 300 else "failed"
    if status == 404 and row and row.provider == "ai_ark" and not error:
        state = "empty"
    if semantic_empty and state == "succeeded":
        state = "empty"
    if error and state == "succeeded":
        state = "failed"
    if row is None or status is None:
        state = "unknown" if error and error != "provider_halted_pre_dispatch" else "failed"
    await conn.execute(
        text("""
        UPDATE arv2_research_operation SET state=:state,ledger_id=:ledger,
          artifact_key=(SELECT response_artifact_key FROM provider_call_ledger
                        WHERE ledger_id=:ledger),
          error_code=:error,finished_at=now()
        WHERE operation_id=:id AND workspace_id=:ws AND owner_token=:owner
          AND state IN ('running','unknown')
    """),
        {
            "state": state,
            "ledger": ledger_id,
            "error": error if state not in ("succeeded", "empty") else None,
            "id": operation.operation_id,
            "ws": scope.workspace_id,
            "owner": operation.owner_token,
        },
    )


async def body(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: OperationScope,
    oid: UUID,
) -> tuple[Operation, dict[str, Any]]:
    op = await get(conn, scope, oid)
    if not await job_available(conn, scope, op.kind):
        raise RefusalError("tool_error", "research authority was withdrawn for this job")
    if op.state not in ("succeeded", "empty"):
        raise RefusalError(
            "tool_error",
            f"saved operation is {op.state}: {op.error_code or 'in flight'}; "
            "do not repeat uncertain spending; record the gap",
        )
    if not op.artifact_key:
        raise RefusalError("tool_error", "operation has no reusable evidence")
    _, raw = await read_verified_artifact(
        conn, storage, storage_key=op.artifact_key, workspace_id=scope.workspace_id
    )
    envelope = json.loads(raw)
    request_text = envelope.get("record", {}).get("request", {}).get("body_text")
    if request_text:
        request_data = json.loads(request_text)
        if isinstance(request_data, dict):
            op = replace(op, request_data=request_data)
    try:
        result = json.loads(envelope["body_utf8"])
    except (ValueError, TypeError, KeyError) as exc:
        if op.state == "empty":
            return op, {}
        raise RefusalError("tool_error", "saved response is not valid JSON") from exc
    if not isinstance(result, dict):
        raise RefusalError("tool_error", "saved response is not a JSON object")
    if envelope.get("record", {}).get("provider") == "ai_ark":
        result = enrichment_only(result)
    return op, result


async def deep_attempted(conn: AsyncConnection, scope: OperationScope) -> bool:
    return bool(
        (
            await conn.execute(
                text("""
        SELECT EXISTS(SELECT 1 FROM arv2_research_operation WHERE workspace_id=:ws
          AND job_id=:job AND kind='account_deep' AND state<>'running')
    """),
                {"ws": scope.workspace_id, "job": scope.job_id},
            )
        ).scalar_one()
    )


async def checkpoint_selection(
    conn: AsyncConnection,
    scope: OperationScope,
    claim_ids: list[UUID],
) -> None:
    await conn.execute(
        text("""
        UPDATE arv2_research_job SET selection_claim_ids=:ids
        WHERE job_id=:job AND workspace_id=:ws AND selection_claim_ids IS NULL
    """),
        {"ids": claim_ids, "job": scope.job_id, "ws": scope.workspace_id},
    )


async def selected_candidates(conn: AsyncConnection, scope: OperationScope) -> list[dict[str, Any]]:
    rows = (
        (
            await conn.execute(
                text("""
        SELECT c.value_json,c.id FROM arv2_research_job j
        CROSS JOIN LATERAL unnest(j.selection_claim_ids) WITH ORDINALITY chosen(id,ordinal)
        JOIN claim c ON c.id=chosen.id AND c.workspace_id=j.workspace_id
        WHERE j.job_id=:job AND j.workspace_id=:ws AND c.superseded_by IS NULL
          AND c.field_key='account.committee_candidate'
        ORDER BY chosen.ordinal
    """),
                {"job": scope.job_id, "ws": scope.workspace_id},
            )
        )
        .mappings()
        .all()
    )
    return [
        dict(decode_jsonb(r["value_json"]) or {}, selection_claim_id=str(r["id"])) for r in rows
    ]


async def operation_states(conn: AsyncConnection, scope: OperationScope) -> dict[str, str]:
    rows = (
        await conn.execute(
            text("""
        SELECT kind,state FROM arv2_research_operation WHERE workspace_id=:ws AND job_id=:job
        ORDER BY created_at
    """),
            {"ws": scope.workspace_id, "job": scope.job_id},
        )
    ).all()
    return {str(row[0]): str(row[1]) for row in rows}


async def stop_contact_jobs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    contact_id: UUID,
    stop_external: bool,
    channel_fields: frozenset[str] | None,
) -> None:
    """API-root privacy hook: retain receipts but withdraw old jobs' authority to publish data."""
    blocked = sorted(
        channel_fields if channel_fields is not None else {"core.work_email", "core.direct_phone"}
    )
    await conn.execute(
        text("""
        UPDATE arv2_research_job SET input_refs=input_refs || jsonb_build_object(
          'privacy_stopped', COALESCE((input_refs->>'privacy_stopped')::boolean,false) OR
        :stop,
          'blocked_channels', COALESCE(input_refs->'blocked_channels','[]'::jsonb)
                              || CAST(:blocked AS jsonb))
        WHERE workspace_id=:ws AND subject_entity_id=:contact AND profile_ref IN
        ('agent-profile:arv2-person:v2','agent-profile:arv2-person:v3')
    """),
        {
            "ws": workspace_id,
            "contact": contact_id,
            "stop": stop_external,
            "blocked": json.dumps(blocked),
        },
    )
    await conn.execute(
        text("""
        UPDATE artifact SET
        privacy_erased=true,erasure_reason='privacy',erased_at=now(),source_url=NULL
        WHERE workspace_id=:ws AND storage_key IN (
          SELECT o.artifact_key FROM arv2_research_operation o
          JOIN arv2_research_job j USING(job_id)
          WHERE j.workspace_id=:ws AND j.subject_entity_id=:contact
            AND (:stop OR (o.kind='contact_email' AND 'core.work_email'=ANY(:fields))
                       OR (o.kind='contact_phone' AND 'core.direct_phone'=ANY(:fields))))
    """),
        {"ws": workspace_id, "contact": contact_id, "stop": stop_external, "fields": blocked},
    )


async def job_available(
    conn: AsyncConnection, scope: OperationScope, kind: str | None = None
) -> bool:
    row = (
        await conn.execute(
            text("""SELECT j.input_refs,j.status FROM arv2_research_job j
            WHERE j.job_id=:job AND j.workspace_id=:ws AND j.run_id=:run
              AND j.account_entity_id=:account
              AND NOT EXISTS (
                SELECT 1 FROM arv2_account_research_generation g
                WHERE g.workspace_id=j.workspace_id AND g.run_id=j.run_id
                  AND g.account_id=j.account_entity_id
                  AND g.state IN ('suspended','privacy_stopped'))"""),
            {
                "job": scope.job_id,
                "ws": scope.workspace_id,
                "run": scope.run_id,
                "account": scope.account_id,
            },
        )
    ).one_or_none()
    if row is None or row.status == "suspended":
        return False
    refs = decode_jsonb(row.input_refs) or {}
    field = {"contact_email": "core.work_email", "contact_phone": "core.direct_phone"}.get(
        kind or ""
    )
    return not refs.get("privacy_stopped") and field not in refs.get("blocked_channels", [])
