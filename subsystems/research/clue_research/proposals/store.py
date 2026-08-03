"""Postgres stores for immutable Phase-C proposal payloads and decision audit."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import decode_jsonb, serialize_value_json
from clue_core.proposals import (
    FieldProposalId,
    ProposalAuthority,
    ProposalStatus,
    SourceProposalId,
    new_field_proposal_id,
    new_source_proposal_id,
)
from clue_research.proposals.models import (
    FieldProposal,
    FieldProposalPayload,
    ProposalScope,
    SourceProposal,
    SourceProposalPayload,
)

_FIELD_COLUMNS = (
    "id, workspace_id, brand_id, product_id, project_id, icp_key, icp_spec_version, field_key, "
    "payload_hash, payload_json, status, proposed_by_actor, proposed_by_ref, proposed_at, "
    "required_authority, decided_by, decision_authority, decided_at, decision_reason, "
    "applied_field_key, applied_version"
)
_SOURCE_COLUMNS = (
    "id, workspace_id, brand_id, product_id, project_id, icp_key, icp_spec_version, source_key, "
    "payload_hash, payload_json, status, proposed_by_actor, proposed_by_ref, proposed_at, "
    "required_authority, decided_by, decision_authority, decided_at, decision_reason, "
    "assigned_tier, "
    "applied_source_key, applied_version, yield_observations, yield_rate, demoted_at, demoted_by, "
    "demotion_reason, demoted_version"
)


class ProposalNotFound(LookupError):
    """The proposal is absent or belongs to another workspace."""


class ProposalScopeError(ValueError):
    """One of the supplied object-spine coordinates is absent or cross-workspace."""


class ProposalAlreadyDecided(RuntimeError):
    """A competing decision won the proposal row lock."""


def _scope_from_row(row: Mapping[str, Any]) -> ProposalScope:
    return ProposalScope(
        workspace_id=str(row["workspace_id"]),
        brand_id=str(row["brand_id"]),
        product_id=row["product_id"],
        project_id=row["project_id"],
        icp_key=row["icp_key"],
        icp_spec_version=row["icp_spec_version"],
    )


def _field_from_row(row: Mapping[str, Any]) -> FieldProposal:
    status = ProposalStatus(row["status"])
    return FieldProposal(
        id=row["id"],
        scope=_scope_from_row(row),
        payload=FieldProposalPayload.model_validate(
            decode_jsonb(row["payload_json"]),
            context={"allow_legacy_promoted_client_field": status is ProposalStatus.PROMOTED},
        ),
        payload_hash=str(row["payload_hash"]),
        status=status,
        proposed_by_actor=str(row["proposed_by_actor"]),
        proposed_by_ref=row["proposed_by_ref"],
        proposed_at=row["proposed_at"],
        required_authority=ProposalAuthority(row["required_authority"]),
        decided_by=row["decided_by"],
        decision_authority=(
            ProposalAuthority(row["decision_authority"])
            if row["decision_authority"] is not None
            else None
        ),
        decided_at=row["decided_at"],
        decision_reason=row["decision_reason"],
        applied_field_key=row["applied_field_key"],
        applied_version=row["applied_version"],
    )


def _source_from_row(row: Mapping[str, Any]) -> SourceProposal:
    return SourceProposal(
        id=row["id"],
        scope=_scope_from_row(row),
        payload=SourceProposalPayload.model_validate(decode_jsonb(row["payload_json"])),
        payload_hash=str(row["payload_hash"]),
        status=ProposalStatus(row["status"]),
        proposed_by_actor=str(row["proposed_by_actor"]),
        proposed_by_ref=row["proposed_by_ref"],
        proposed_at=row["proposed_at"],
        required_authority=ProposalAuthority(row["required_authority"]),
        decided_by=row["decided_by"],
        decision_authority=(
            ProposalAuthority(row["decision_authority"])
            if row["decision_authority"] is not None
            else None
        ),
        decided_at=row["decided_at"],
        decision_reason=row["decision_reason"],
        assigned_tier=row["assigned_tier"],
        applied_source_key=row["applied_source_key"],
        applied_version=row["applied_version"],
        yield_observations=int(row["yield_observations"]),
        yield_rate=float(row["yield_rate"]) if row["yield_rate"] is not None else None,
        demoted_at=row["demoted_at"],
        demoted_by=row["demoted_by"],
        demotion_reason=row["demotion_reason"],
        demoted_version=row["demoted_version"],
    )


def _scope_params(scope: ProposalScope) -> dict[str, object]:
    return {
        "workspace_id": scope.workspace_id,
        "brand_id": scope.brand_id,
        "product_id": scope.product_id,
        "project_id": scope.project_id,
        "icp_key": scope.icp_key,
        "icp_spec_version": scope.icp_spec_version,
    }


async def scope_exists(conn: AsyncConnection, scope: ProposalScope) -> bool:
    """Validate the complete object-spine scope without revealing which coordinate failed."""
    brand = (
        await conn.execute(
            text("SELECT 1 FROM brand WHERE brand_id = :brand_id AND workspace_id = :workspace_id"),
            _scope_params(scope),
        )
    ).first()
    if brand is None:
        return False
    if scope.product_id is not None:
        product = (
            await conn.execute(
                text(
                    "SELECT 1 FROM product WHERE product_id = :product_id "
                    "AND brand_id = :brand_id AND workspace_id = :workspace_id"
                ),
                _scope_params(scope),
            )
        ).first()
        if product is None:
            return False
    if scope.project_id is not None:
        project = (
            await conn.execute(
                text(
                    "SELECT 1 FROM project WHERE project_id = :project_id "
                    "AND brand_id = :brand_id AND workspace_id = :workspace_id "
                    "AND (CAST(:product_id AS text) IS NULL OR product_id = :product_id)"
                ),
                _scope_params(scope),
            )
        ).first()
        if project is None:
            return False
    if scope.icp_key is not None:
        icp = (
            await conn.execute(
                text(
                    "SELECT 1 FROM icp_spec WHERE workspace_id = :workspace_id "
                    "AND icp_key = :icp_key AND version = :icp_spec_version"
                ),
                _scope_params(scope),
            )
        ).first()
        if icp is None:
            return False
    return True


async def insert_field_proposal(
    conn: AsyncConnection,
    *,
    scope: ProposalScope,
    payload: FieldProposalPayload,
    payload_hash: str,
    required_authority: ProposalAuthority,
    proposed_by_actor: str,
    proposed_by_ref: str | None,
) -> FieldProposal:
    params = {
        **_scope_params(scope),
        "id": new_field_proposal_id(),
        "field_key": payload.field_def.field_key,
        "payload_hash": payload_hash,
        "payload_json": serialize_value_json(payload.model_dump(mode="json")),
        "required_authority": required_authority.value,
        "proposed_by_actor": proposed_by_actor,
        "proposed_by_ref": proposed_by_ref,
    }
    inserted = (
        (
            await conn.execute(
                text(
                    f"""
                    INSERT INTO field_definition_revision (
                        id, workspace_id, brand_id, product_id, project_id, icp_key,
                        icp_spec_version, field_key, payload_hash, payload_json,
                        required_authority, proposed_by_actor, proposed_by_ref
                    ) VALUES (
                        :id, :workspace_id, :brand_id, :product_id, :project_id, :icp_key,
                        :icp_spec_version, :field_key, :payload_hash, CAST(:payload_json AS jsonb),
                        CAST(:required_authority AS proposal_authority), :proposed_by_actor,
                        :proposed_by_ref
                    )
                    ON CONFLICT ON CONSTRAINT field_definition_revision_dedupe DO NOTHING
                    RETURNING {_FIELD_COLUMNS}
                    """
                ),
                params,
            )
        )
        .mappings()
        .first()
    )
    if inserted is not None:
        return _field_from_row(dict(inserted))
    existing = (
        (
            await conn.execute(
                text(
                    f"""
                    SELECT {_FIELD_COLUMNS} FROM field_definition_revision
                    WHERE workspace_id = :workspace_id AND brand_id = :brand_id
                      AND product_id IS NOT DISTINCT FROM :product_id
                      AND project_id IS NOT DISTINCT FROM :project_id
                      AND icp_key IS NOT DISTINCT FROM :icp_key
                      AND icp_spec_version IS NOT DISTINCT FROM :icp_spec_version
                      AND payload_hash = :payload_hash
                    """
                ),
                params,
            )
        )
        .mappings()
        .one()
    )
    return _field_from_row(dict(existing))


async def insert_source_proposal(
    conn: AsyncConnection,
    *,
    scope: ProposalScope,
    payload: SourceProposalPayload,
    payload_hash: str,
    required_authority: ProposalAuthority,
    proposed_by_actor: str,
    proposed_by_ref: str | None,
) -> SourceProposal:
    params = {
        **_scope_params(scope),
        "id": new_source_proposal_id(),
        "source_key": payload.manifest.source_key,
        "payload_hash": payload_hash,
        "payload_json": serialize_value_json(payload.model_dump(mode="json")),
        "required_authority": required_authority.value,
        "proposed_by_actor": proposed_by_actor,
        "proposed_by_ref": proposed_by_ref,
    }
    inserted = (
        (
            await conn.execute(
                text(
                    f"""
                    INSERT INTO source_manifest_revision (
                        id, workspace_id, brand_id, product_id, project_id, icp_key,
                        icp_spec_version, source_key, payload_hash, payload_json,
                        required_authority, proposed_by_actor, proposed_by_ref
                    ) VALUES (
                        :id, :workspace_id, :brand_id, :product_id, :project_id, :icp_key,
                        :icp_spec_version, :source_key, :payload_hash, CAST(:payload_json AS jsonb),
                        CAST(:required_authority AS proposal_authority), :proposed_by_actor,
                        :proposed_by_ref
                    )
                    ON CONFLICT ON CONSTRAINT source_manifest_revision_dedupe DO NOTHING
                    RETURNING {_SOURCE_COLUMNS}
                    """
                ),
                params,
            )
        )
        .mappings()
        .first()
    )
    if inserted is not None:
        return _source_from_row(dict(inserted))
    existing = (
        (
            await conn.execute(
                text(
                    f"""
                    SELECT {_SOURCE_COLUMNS} FROM source_manifest_revision
                    WHERE workspace_id = :workspace_id AND brand_id = :brand_id
                      AND product_id IS NOT DISTINCT FROM :product_id
                      AND project_id IS NOT DISTINCT FROM :project_id
                      AND icp_key IS NOT DISTINCT FROM :icp_key
                      AND icp_spec_version IS NOT DISTINCT FROM :icp_spec_version
                      AND payload_hash = :payload_hash
                    """
                ),
                params,
            )
        )
        .mappings()
        .one()
    )
    return _source_from_row(dict(existing))


async def get_field_proposal(
    conn: AsyncConnection,
    proposal_id: FieldProposalId,
    *,
    workspace_id: str,
    for_update: bool = False,
) -> FieldProposal | None:
    lock = " FOR UPDATE" if for_update else ""
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_FIELD_COLUMNS} FROM field_definition_revision "
                    "WHERE id = :id AND workspace_id = :workspace_id" + lock
                ),
                {"id": proposal_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .first()
    )
    return _field_from_row(dict(row)) if row is not None else None


async def get_source_proposal(
    conn: AsyncConnection,
    proposal_id: SourceProposalId,
    *,
    workspace_id: str,
    for_update: bool = False,
) -> SourceProposal | None:
    lock = " FOR UPDATE" if for_update else ""
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_SOURCE_COLUMNS} FROM source_manifest_revision "
                    "WHERE id = :id AND workspace_id = :workspace_id" + lock
                ),
                {"id": proposal_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .first()
    )
    return _source_from_row(dict(row)) if row is not None else None


async def list_field_proposals(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str | None = None,
    status: ProposalStatus | None = None,
) -> list[FieldProposal]:
    rows = (
        (
            await conn.execute(
                text(
                    f"""
                    SELECT {_FIELD_COLUMNS} FROM field_definition_revision
                    WHERE workspace_id = :workspace_id
                      AND (CAST(:brand_id AS text) IS NULL OR brand_id = :brand_id)
                      AND (CAST(:status AS text) IS NULL
                           OR status = CAST(:status AS proposal_status))
                    ORDER BY proposed_at DESC, id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "brand_id": brand_id,
                    "status": status.value if status is not None else None,
                },
            )
        )
        .mappings()
        .all()
    )
    return [_field_from_row(dict(row)) for row in rows]


async def list_source_proposals(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str | None = None,
    status: ProposalStatus | None = None,
) -> list[SourceProposal]:
    rows = (
        (
            await conn.execute(
                text(
                    f"""
                    SELECT {_SOURCE_COLUMNS} FROM source_manifest_revision
                    WHERE workspace_id = :workspace_id
                      AND (CAST(:brand_id AS text) IS NULL OR brand_id = :brand_id)
                      AND (CAST(:status AS text) IS NULL
                           OR status = CAST(:status AS proposal_status))
                    ORDER BY proposed_at DESC, id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "brand_id": brand_id,
                    "status": status.value if status is not None else None,
                },
            )
        )
        .mappings()
        .all()
    )
    return [_source_from_row(dict(row)) for row in rows]


async def stamp_field_decision(
    conn: AsyncConnection,
    *,
    proposal_id: FieldProposalId,
    status: Literal["promoted", "rejected", "withdrawn"],
    decided_by: str,
    authority: ProposalAuthority,
    reason: str,
    applied_field_key: str | None = None,
    applied_version: int | None = None,
) -> FieldProposal:
    row = (
        (
            await conn.execute(
                text(
                    f"""
                    UPDATE field_definition_revision
                    SET status = CAST(:status AS proposal_status),
                        decided_by = :decided_by,
                        decision_authority = CAST(:authority AS proposal_authority),
                        decided_at = now(),
                        decision_reason = :reason,
                        applied_field_key = :applied_field_key,
                        applied_version = :applied_version
                    WHERE id = :id AND status = 'proposed'
                    RETURNING {_FIELD_COLUMNS}
                    """
                ),
                {
                    "id": proposal_id,
                    "status": status,
                    "decided_by": decided_by,
                    "authority": authority.value,
                    "reason": reason,
                    "applied_field_key": applied_field_key,
                    "applied_version": applied_version,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ProposalAlreadyDecided(str(proposal_id))
    return _field_from_row(dict(row))


async def stamp_source_decision(
    conn: AsyncConnection,
    *,
    proposal_id: SourceProposalId,
    status: Literal["promoted", "rejected", "withdrawn"],
    decided_by: str,
    authority: ProposalAuthority,
    reason: str,
    assigned_tier: int | None = None,
    applied_source_key: str | None = None,
    applied_version: int | None = None,
) -> SourceProposal:
    row = (
        (
            await conn.execute(
                text(
                    f"""
                    UPDATE source_manifest_revision
                    SET status = CAST(:status AS proposal_status),
                        decided_by = :decided_by,
                        decision_authority = CAST(:authority AS proposal_authority),
                        decided_at = now(),
                        decision_reason = :reason,
                        assigned_tier = :assigned_tier,
                        applied_source_key = :applied_source_key,
                        applied_version = :applied_version
                    WHERE id = :id AND status = 'proposed'
                    RETURNING {_SOURCE_COLUMNS}
                    """
                ),
                {
                    "id": proposal_id,
                    "status": status,
                    "decided_by": decided_by,
                    "authority": authority.value,
                    "reason": reason,
                    "assigned_tier": assigned_tier,
                    "applied_source_key": applied_source_key,
                    "applied_version": applied_version,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ProposalAlreadyDecided(str(proposal_id))
    return _source_from_row(dict(row))


async def stamp_source_yield_review(
    conn: AsyncConnection,
    *,
    proposal_id: SourceProposalId,
    observations: int,
    yield_rate: float | None,
    demoted_by: str | None = None,
    demotion_reason: str | None = None,
    demoted_version: int | None = None,
) -> SourceProposal:
    row = (
        (
            await conn.execute(
                text(
                    f"""
                    UPDATE source_manifest_revision
                    SET yield_observations = :observations,
                        yield_rate = :yield_rate,
                        demoted_at = CASE WHEN CAST(:demoted_by AS text) IS NULL
                            THEN demoted_at ELSE now() END,
                        demoted_by = COALESCE(CAST(:demoted_by AS text), demoted_by),
                        demotion_reason = COALESCE(
                            CAST(:demotion_reason AS text), demotion_reason
                        ),
                        demoted_version = COALESCE(
                            CAST(:demoted_version AS int), demoted_version
                        )
                    WHERE id = :id
                    RETURNING {_SOURCE_COLUMNS}
                    """
                ),
                {
                    "id": proposal_id,
                    "observations": observations,
                    "yield_rate": yield_rate,
                    "demoted_by": demoted_by,
                    "demotion_reason": demotion_reason,
                    "demoted_version": demoted_version,
                },
            )
        )
        .mappings()
        .one()
    )
    return _source_from_row(dict(row))


__all__ = [
    "ProposalAlreadyDecided",
    "ProposalNotFound",
    "ProposalScopeError",
    "get_field_proposal",
    "get_source_proposal",
    "insert_field_proposal",
    "insert_source_proposal",
    "list_field_proposals",
    "list_source_proposals",
    "scope_exists",
    "stamp_field_decision",
    "stamp_source_decision",
    "stamp_source_yield_review",
]
