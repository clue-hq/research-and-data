"""Workspace-level erasure for tenant-local dynamic Client-KB state (Phase C Stage 0).

The operation owns the C8 dependency closure: local definitions, proposal payload/decision rows,
materialization receipts, readiness policy, claims (plus transitive derived claims), faithfulness
rationales, and unreferenced evidence artifacts. Content rows are removed where no audit history is
required; claims follow the platform's append-only redacted-tombstone convention. One durable
workspace marker is the no-resurrection barrier checked by every C8 writer.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ClaimId, UtcDatetime, new_run_id
from clue_research.claimstore import (
    WorkspaceScope,
    affected_derivations,
    claims_by_ids,
    redact_faithfulness_rationale,
    supersede_claims,
)
from clue_research.compliance.dsar import build_tombstone
from clue_storage import erase_if_unreferenced

_ERASURE_REASON = "workspace_dynamic_client_kb_erasure"


class WorkspaceDynamicClientKbErasureResult(BaseModel):
    """Bounded audit result; no erased field names, values, quotes, or rationale are returned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    erased_by: str
    reason_code: str
    definition_count: int
    proposal_count: int
    materialization_count: int
    readiness_policy_count: int
    claim_count: int
    artifact_count: int
    tombstoned_claim_ids: tuple[ClaimId, ...] = ()
    marked_artifact_keys: tuple[str, ...] = ()
    erased_at: UtcDatetime


async def get_workspace_dynamic_client_kb_erasure(
    conn: AsyncConnection, *, workspace_id: str
) -> WorkspaceDynamicClientKbErasureResult | None:
    row = (
        (
            await conn.execute(
                text(
                    """
                    SELECT workspace_id, erased_by, reason_code, definition_count,
                           proposal_count, materialization_count, readiness_policy_count,
                           claim_count, artifact_count, erased_at
                    FROM workspace_dynamic_client_kb_erasure
                    WHERE workspace_id = :workspace_id
                    """
                ),
                {"workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    tombstones = tuple(
        ClaimId(item)
        for item in (
            await conn.execute(
                text(
                    "SELECT tombstone_claim_id "
                    "FROM workspace_dynamic_client_kb_claim_erasure "
                    "WHERE workspace_id = :workspace_id ORDER BY erased_claim_id"
                ),
                {"workspace_id": workspace_id},
            )
        ).scalars()
    )
    artifact_keys = tuple(
        (
            await conn.execute(
                text(
                    "SELECT DISTINCT artifact_key FROM agent_artifact_tombstone "
                    "WHERE workspace_id = :workspace_id AND reason_code = :reason_code "
                    "ORDER BY artifact_key"
                ),
                {"workspace_id": workspace_id, "reason_code": row["reason_code"]},
            )
        ).scalars()
    )
    return WorkspaceDynamicClientKbErasureResult.model_validate(
        {
            **dict(row),
            "tombstoned_claim_ids": tombstones,
            "marked_artifact_keys": artifact_keys,
        }
    )


async def erase_workspace_dynamic_client_kb(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    erased_by: str,
) -> WorkspaceDynamicClientKbErasureResult:
    """Erase C8 state atomically and return artifact keys durably marked for post-commit purge.

    The caller must run :func:`clue_storage.purge_erased_artifacts` in a fresh transaction after
    this transaction commits. A crash between the phases is safe: ``artifact.erased_at`` is
    durable and the ordinary purge sweep converges it later.
    """

    if not 1 <= len(erased_by.strip()) <= 256:
        raise ValueError("workspace erasure actor must contain 1..256 characters")
    reason_code = _ERASURE_REASON

    workspace = (
        await conn.execute(
            text(
                "SELECT workspace_id FROM workspace WHERE workspace_id = :workspace_id FOR UPDATE"
            ),
            {"workspace_id": workspace_id},
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise ValueError("workspace not found")
    existing = await get_workspace_dynamic_client_kb_erasure(conn, workspace_id=workspace_id)
    if existing is not None:
        return existing

    field_keys = tuple(
        (
            await conn.execute(
                text(
                    "SELECT field_key FROM workspace_field_definition "
                    "WHERE workspace_id = :workspace_id ORDER BY field_key"
                ),
                {"workspace_id": workspace_id},
            )
        ).scalars()
    )
    proposal_rows = (
        (
            await conn.execute(
                text(
                    """
                    SELECT revision.id, input.artifact_key, statement.client_entity_id
                    FROM field_definition_revision revision
                    LEFT JOIN volunteered_statement statement
                      ON statement.workspace_id = revision.workspace_id
                     AND statement.id::text =
                         revision.payload_json->'client_kb'->>'source_statement_id'
                    LEFT JOIN onboarding_input input ON input.id = statement.onboarding_input_id
                    WHERE revision.workspace_id = :workspace_id
                      AND revision.field_key LIKE 'client.%'
                      AND revision.payload_json->'client_kb' IS NOT NULL
                      AND revision.payload_json->'client_kb' <> 'null'::jsonb
                    ORDER BY revision.id
                    """
                ),
                {"workspace_id": workspace_id},
            )
        )
        .mappings()
        .all()
    )
    proposal_ids = tuple(row["id"] for row in proposal_rows)
    artifact_subjects: dict[str, object] = {
        row["artifact_key"]: row["client_entity_id"]
        for row in proposal_rows
        if row["artifact_key"] is not None and row["client_entity_id"] is not None
    }

    materialization_count = int(
        (
            await conn.execute(
                text(
                    "SELECT count(*) FROM workspace_field_materialization "
                    "WHERE workspace_id = :workspace_id"
                ),
                {"workspace_id": workspace_id},
            )
        ).scalar_one()
    )
    readiness_policy_count = int(
        (
            await conn.execute(
                text(
                    "SELECT count(*) FROM workspace_client_kb_readiness_policy "
                    "WHERE workspace_id = :workspace_id"
                ),
                {"workspace_id": workspace_id},
            )
        ).scalar_one()
    )

    direct_ids: tuple[ClaimId, ...] = ()
    if field_keys:
        direct_stmt = text(
            "SELECT id FROM claim WHERE workspace_id = :workspace_id "
            "AND superseded_by IS NULL AND field_key IN :field_keys ORDER BY id"
        ).bindparams(bindparam("field_keys", expanding=True))
        direct_ids = tuple(
            ClaimId(item)
            for item in (
                await conn.execute(
                    direct_stmt,
                    {"workspace_id": workspace_id, "field_keys": list(field_keys)},
                )
            ).scalars()
        )
    dependent_ids = await affected_derivations(conn, direct_ids)
    selected = await claims_by_ids(
        conn,
        (*direct_ids, *dependent_ids),
        scope=WorkspaceScope.private_for_workspace(workspace_id),
    )
    targets = tuple(sorted(selected.values(), key=lambda claim: str(claim.id)))

    run_id = new_run_id()
    tombstone_ids: list[ClaimId] = []
    for target in targets:
        if target.artifact_key is not None:
            artifact_subjects.setdefault(target.artifact_key, target.entity_id)
        await redact_faithfulness_rationale(conn, target, reason_code=reason_code)
        tombstone = build_tombstone(target, run_id=run_id)
        tombstone_id = await supersede_claims(conn, (target.id,), tombstone, validate_field=False)
        tombstone_ids.append(tombstone_id)
        await conn.execute(
            text(
                """
                INSERT INTO workspace_dynamic_client_kb_claim_erasure
                    (workspace_id, erased_claim_id, tombstone_claim_id, reason_code)
                VALUES (:workspace_id, :erased_claim_id, :tombstone_claim_id, :reason_code)
                """
            ),
            {
                "workspace_id": workspace_id,
                "erased_claim_id": target.id,
                "tombstone_claim_id": tombstone_id,
                "reason_code": reason_code,
            },
        )

    marked_artifact_keys: list[str] = []
    for artifact_key, subject_entity_id in sorted(artifact_subjects.items()):
        if not await erase_if_unreferenced(conn, artifact_key):
            continue
        marked_artifact_keys.append(artifact_key)
        await conn.execute(
            text(
                """
                INSERT INTO agent_artifact_tombstone
                    (workspace_id, artifact_key, subject_entity_id, reason_code)
                SELECT :workspace_id, :artifact_key, CAST(:subject_entity_id AS uuid), :reason_code
                FROM artifact WHERE storage_key = :artifact_key
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "workspace_id": workspace_id,
                "artifact_key": artifact_key,
                "subject_entity_id": subject_entity_id,
                "reason_code": reason_code,
            },
        )

    # Remove content-bearing and replay-bearing C8 rows from leaves to roots. The marker written
    # below retains bounded counts/timestamps without keeping field meanings, values, or rationale.
    await conn.execute(
        text("DELETE FROM workspace_field_materialization WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )
    await conn.execute(
        text("DELETE FROM workspace_field_retirement WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )
    await conn.execute(
        text("DELETE FROM workspace_field_definition WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )
    await conn.execute(
        text("DELETE FROM workspace_client_kb_readiness_policy WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )
    if proposal_ids:
        proposal_delete = text(
            "DELETE FROM field_definition_revision WHERE id IN :proposal_ids"
        ).bindparams(bindparam("proposal_ids", expanding=True))
        await conn.execute(proposal_delete, {"proposal_ids": list(proposal_ids)})

    await conn.execute(
        text(
            """
            INSERT INTO workspace_dynamic_client_kb_erasure (
                workspace_id, erased_by, reason_code, definition_count, proposal_count,
                materialization_count, readiness_policy_count, claim_count, artifact_count
            ) VALUES (
                :workspace_id, :erased_by, :reason_code, :definition_count, :proposal_count,
                :materialization_count, :readiness_policy_count, :claim_count, :artifact_count
            )
            """
        ),
        {
            "workspace_id": workspace_id,
            "erased_by": erased_by,
            "reason_code": reason_code,
            "definition_count": len(field_keys),
            "proposal_count": len(proposal_ids),
            "materialization_count": materialization_count,
            "readiness_policy_count": readiness_policy_count,
            "claim_count": len(tombstone_ids),
            "artifact_count": len(marked_artifact_keys),
        },
    )
    created = await get_workspace_dynamic_client_kb_erasure(conn, workspace_id=workspace_id)
    assert created is not None
    return created


__all__ = [
    "WorkspaceDynamicClientKbErasureResult",
    "erase_workspace_dynamic_client_kb",
    "get_workspace_dynamic_client_kb_erasure",
]
