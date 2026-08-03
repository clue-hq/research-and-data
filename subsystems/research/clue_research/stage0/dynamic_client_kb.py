"""Tenant-local dynamic Client-KB proposal materialization.

Promotion defines meaning; this module performs the separate, replay-safe effect that turns one
already-preserved interview statement into a typed claim. Artifact bytes and the entailment judge
remain injected composition-root concerns. This layer accepts only the verified quote and the
judge/non-judge admission result, then rechecks every durable scope/registry invariant before write.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    OnboardingInputId,
    ResearchMode,
    ReuseScope,
    RunId,
    VolunteeredStatementId,
    canonical_json,
)
from clue_core.proposals import FieldProposalId, ProposalStatus
from clue_research.claimstore import (
    FieldRegistryOrigin,
    FieldRegistryScope,
    assert_workspace_dynamic_client_kb_active,
    get_effective_field,
    insert_claim,
    validate_effective_value,
)
from clue_research.proposals import get_field_proposal
from clue_research.stage0.client_kb import client_kb_write_target_for_materialization
from clue_research.stage0.interview import (
    SOURCE_CLIENT_INTERVIEW,
    SOURCE_CLIENT_INTERVIEW_JUDGED,
    register_client_interview_source,
)


class FieldMaterializationStatus(StrEnum):
    MATERIALIZED = "materialized"
    REFUSED = "refused"


class DynamicClientKbRefused(ValueError):
    """One bounded, durable refusal code for a non-materializable proposal/statement pair."""

    def __init__(self, *, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class FieldMaterializationStatement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: VolunteeredStatementId
    onboarding_input_id: OnboardingInputId
    artifact_key: str
    workspace_id: str
    brand_id: str
    product_id: str | None
    project_id: str | None
    client_entity_id: EntityId | None
    route_kind: str
    route_key: str
    route_ref: str | None
    quote_start: int
    quote_end: int
    quote_sha256: str


class FieldMaterializationPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    workspace_id: str
    proposal_id: FieldProposalId
    statement: FieldMaterializationStatement
    field_key: str
    candidate_value: JsonValue
    value_digest: str
    client_entity_id: EntityId
    product_id: str | None


class FieldMaterializationReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    workspace_id: str
    proposal_id: FieldProposalId
    statement_id: VolunteeredStatementId
    field_key: str
    value_digest: str
    status: FieldMaterializationStatus
    claim_id: ClaimId | None = None
    client_entity_id: EntityId | None = None
    client_kb_version: int | None = None
    run_id: RunId | None = None
    refusal_code: str | None = None


_RECEIPT_COLUMNS = (
    "id, workspace_id, field_proposal_id, statement_id, field_key, value_digest, status, "
    "claim_id, client_entity_id, client_kb_version, run_id, refusal_code"
)


def statement_evidence_ref(statement_id: VolunteeredStatementId) -> str:
    """The canonical proposal evidence ref for one durable interview statement."""

    return f"volunteered_statement:{statement_id}"


def _evidence_ref_matches(ref: str, statement_id: VolunteeredStatementId) -> bool:
    raw = str(statement_id)
    return ref in {raw, f"statement:{raw}", statement_evidence_ref(statement_id)}


def _receipt(row: dict[str, object]) -> FieldMaterializationReceipt:
    proposal_id = row.pop("field_proposal_id")
    return FieldMaterializationReceipt.model_validate(
        {
            **row,
            "proposal_id": proposal_id,
        }
    )


async def get_field_materialization(
    conn: AsyncConnection, *, workspace_id: str, materialization_id: UUID
) -> FieldMaterializationReceipt | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_RECEIPT_COLUMNS} FROM workspace_field_materialization "
                    "WHERE id = :id AND workspace_id = :workspace_id"
                ),
                {"id": materialization_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return _receipt(dict(row)) if row is not None else None


async def prepare_field_materialization(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    proposal_id: FieldProposalId,
    statement_id: VolunteeredStatementId,
) -> tuple[FieldMaterializationPlan, FieldMaterializationReceipt | None]:
    """Resolve and validate a promoted proposal plus same-workspace preserved statement."""

    await assert_workspace_dynamic_client_kb_active(conn, workspace_id=workspace_id)
    proposal = await get_field_proposal(
        conn, proposal_id, workspace_id=workspace_id, for_update=False
    )
    if proposal is None:
        raise DynamicClientKbRefused(
            reason_code="field_proposal_not_found", message="field proposal not found"
        )
    if proposal.status is not ProposalStatus.PROMOTED:
        raise DynamicClientKbRefused(
            reason_code="field_proposal_not_promoted",
            message="field proposal must be promoted before materialization",
        )
    details = proposal.payload.client_kb
    if details is None:
        raise DynamicClientKbRefused(
            reason_code="field_proposal_not_client_kb",
            message="field proposal has no dynamic Client-KB materialization value",
        )
    if details.source_statement_id != statement_id:
        raise DynamicClientKbRefused(
            reason_code="statement_not_proposal_source",
            message="the selected statement is not the proposal's materialization source",
        )
    if not any(_evidence_ref_matches(ref, statement_id) for ref in proposal.payload.evidence_refs):
        raise DynamicClientKbRefused(
            reason_code="statement_not_proposal_evidence",
            message="the selected statement is not an evidence ref on this proposal",
        )

    row = (
        (
            await conn.execute(
                text(
                    """
                    SELECT s.id, s.onboarding_input_id, i.artifact_key, s.workspace_id,
                           s.brand_id, s.product_id, s.project_id, s.client_entity_id,
                           s.route_kind, s.route_key, s.route_ref, s.quote_start, s.quote_end,
                           s.quote_sha256
                    FROM volunteered_statement s
                    JOIN onboarding_input i ON i.id = s.onboarding_input_id
                    WHERE s.id = :statement_id AND s.workspace_id = :workspace_id
                      AND NOT EXISTS (
                          SELECT 1 FROM volunteered_statement correction
                          WHERE correction.correction_of_id = s.id
                            AND correction.workspace_id = s.workspace_id
                      )
                    """
                ),
                {"statement_id": statement_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise DynamicClientKbRefused(
            reason_code="statement_not_found_or_superseded",
            message="statement is absent, belongs to another workspace, or was corrected",
        )
    statement = FieldMaterializationStatement.model_validate(dict(row))
    if statement.brand_id != proposal.scope.brand_id:
        raise DynamicClientKbRefused(
            reason_code="proposal_statement_scope_mismatch",
            message="proposal and statement do not share one brand scope",
        )
    if proposal.scope.product_id is not None and statement.product_id != proposal.scope.product_id:
        raise DynamicClientKbRefused(
            reason_code="proposal_statement_scope_mismatch",
            message="proposal and statement do not share one product scope",
        )
    if proposal.scope.project_id is not None and statement.project_id != proposal.scope.project_id:
        raise DynamicClientKbRefused(
            reason_code="proposal_statement_scope_mismatch",
            message="proposal and statement do not share one project scope",
        )
    if statement.client_entity_id is None:
        raise DynamicClientKbRefused(
            reason_code="statement_client_missing",
            message="statement is not bound to a resolved client entity",
        )

    definition = await get_effective_field(
        conn,
        scope=FieldRegistryScope.for_workspace(workspace_id),
        field_key=proposal.payload.field_def.field_key,
    )
    if (
        definition is None
        or definition.origin is not FieldRegistryOrigin.WORKSPACE
        or definition.promoted_from_proposal_id != proposal.id
    ):
        raise DynamicClientKbRefused(
            reason_code="promoted_workspace_field_not_found",
            message="the proposal's promoted workspace field is not effective",
        )
    await validate_effective_value(
        conn,
        scope=FieldRegistryScope.for_workspace(workspace_id),
        field_key=proposal.payload.field_def.field_key,
        value_json=details.candidate_value,
    )

    value_digest = hashlib.sha256(canonical_json(details.candidate_value).encode()).hexdigest()
    materialization_id = uuid5(
        NAMESPACE_URL,
        "\0".join(
            (
                "dynamic-client-kb-materialization-v1",
                workspace_id,
                str(proposal.id),
                str(statement_id),
                proposal.payload.field_def.field_key,
                value_digest,
            )
        ),
    )
    plan = FieldMaterializationPlan(
        id=materialization_id,
        workspace_id=workspace_id,
        proposal_id=proposal.id,
        statement=statement,
        field_key=proposal.payload.field_def.field_key,
        candidate_value=details.candidate_value,
        value_digest=value_digest,
        client_entity_id=statement.client_entity_id,
        product_id=statement.product_id or proposal.scope.product_id,
    )
    return plan, await get_field_materialization(
        conn, workspace_id=workspace_id, materialization_id=materialization_id
    )


async def record_field_materialization_refusal(
    conn: AsyncConnection,
    *,
    plan: FieldMaterializationPlan,
    reason_code: str,
) -> FieldMaterializationReceipt:
    """Persist one bounded terminal refusal; replay returns the same receipt."""

    await conn.execute(
        text(
            """
            INSERT INTO workspace_field_materialization (
                id, workspace_id, field_proposal_id, statement_id, field_key, value_digest,
                status, refusal_code
            ) VALUES (
                :id, :workspace_id, :proposal_id, :statement_id, :field_key, :value_digest,
                'refused', :reason_code
            )
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": plan.id,
            "workspace_id": plan.workspace_id,
            "proposal_id": plan.proposal_id,
            "statement_id": plan.statement.id,
            "field_key": plan.field_key,
            "value_digest": plan.value_digest,
            "reason_code": reason_code,
        },
    )
    receipt = await get_field_materialization(
        conn, workspace_id=plan.workspace_id, materialization_id=plan.id
    )
    assert receipt is not None
    return receipt


async def materialize_approved_field(
    conn: AsyncConnection,
    *,
    plan: FieldMaterializationPlan,
    quote: str,
    judged: bool,
) -> FieldMaterializationReceipt:
    """Write exactly one typed claim plus terminal receipt into the correct KB version."""

    # Serialize only the final durable effect. Evidence resolution and any judgment happen before
    # this transaction at the composition root; once they converge here, concurrent retries for
    # the same content-addressed plan cannot both pass the receipt check and race the deterministic
    # claim INSERT. The transaction-scoped lock releases on commit/rollback and needs no cleanup.
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:materialization_id, 0))"),
        {"materialization_id": str(plan.id)},
    )
    existing = await get_field_materialization(
        conn, workspace_id=plan.workspace_id, materialization_id=plan.id
    )
    if existing is not None:
        return existing
    target = await client_kb_write_target_for_materialization(
        conn,
        workspace_id=plan.workspace_id,
        client_entity_id=plan.client_entity_id,
        product_id=plan.product_id,
        operation_key=str(plan.id),
    )
    await register_client_interview_source(conn)
    claim_id = ClaimId(uuid5(NAMESPACE_URL, f"dynamic-client-kb-claim:{plan.id}"))
    claim = Claim(
        id=claim_id,
        entity_id=plan.client_entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key=plan.field_key,
        value_json=plan.candidate_value,
        source_url=f"interview://{plan.statement.onboarding_input_id}",
        source_key=(SOURCE_CLIENT_INTERVIEW_JUDGED if judged else SOURCE_CLIENT_INTERVIEW),
        artifact_key=plan.statement.artifact_key,
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,
        evidence_span=quote,
        confidence=1.0,
        run_id=target.run_id,
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id=plan.workspace_id,
        product_id=plan.product_id,
    )
    await insert_claim(conn, claim)
    await conn.execute(
        text(
            """
            INSERT INTO workspace_field_materialization (
                id, workspace_id, field_proposal_id, statement_id, field_key, value_digest,
                status, claim_id, client_entity_id, client_kb_version, run_id
            ) VALUES (
                :id, :workspace_id, :proposal_id, :statement_id, :field_key, :value_digest,
                'materialized', :claim_id, :client_entity_id, :client_kb_version, :run_id
            )
            """
        ),
        {
            "id": plan.id,
            "workspace_id": plan.workspace_id,
            "proposal_id": plan.proposal_id,
            "statement_id": plan.statement.id,
            "field_key": plan.field_key,
            "value_digest": plan.value_digest,
            "claim_id": claim_id,
            "client_entity_id": plan.client_entity_id,
            "client_kb_version": target.version,
            "run_id": target.run_id,
        },
    )
    receipt = await get_field_materialization(
        conn, workspace_id=plan.workspace_id, materialization_id=plan.id
    )
    assert receipt is not None
    return receipt


__all__ = [
    "DynamicClientKbRefused",
    "FieldMaterializationPlan",
    "FieldMaterializationReceipt",
    "FieldMaterializationStatement",
    "FieldMaterializationStatus",
    "get_field_materialization",
    "materialize_approved_field",
    "prepare_field_materialization",
    "record_field_materialization_refusal",
    "statement_evidence_ref",
]
