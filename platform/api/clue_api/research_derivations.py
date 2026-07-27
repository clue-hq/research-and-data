"""API-root C7.2 orchestration for governed derived claims.

The independent claimstore and verification packages meet only here. The service validates the
live support graph before spend, invokes the injected entailment judge, conservatively computes
confidence, and atomically writes the final immutable claim, support set, and bounded verdict.
It returns references and bounded states only.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimFlavor,
    ClaimId,
    DerivationEntailmentJudge,
    EntailmentJudgeRequest,
    EntailmentReasonCode,
    EntailmentSupport,
    EntailmentVerdictKind,
    OperationId,
    ResearchSubjectRef,
    ResearchSupportRef,
    VerificationStatus,
    can_be_promoted,
)
from clue_db import ConnFactory, transaction
from clue_research.claimstore import (
    DerivationStore,
    WorkspaceScope,
    claims_by_ids,
)
from clue_research.verification import (
    insert_entailment_verdict,
    load_entailment_by_operation,
)


class DerivedClaimPolicy(BaseModel):
    """Versioned engine-owned promotion limits; requests cannot override these values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(default=1, ge=1)
    entailment_threshold: float = Field(default=0.7, ge=0, le=1)
    confidence_ceiling: float = Field(default=0.85, ge=0, le=1)


DEFAULT_DERIVED_CLAIM_POLICY = DerivedClaimPolicy()


class DerivedClaimProposal(BaseModel):
    """One idempotent proposal. Supports are references; the service loads live bodies itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str = Field(min_length=1)
    operation_id: OperationId
    target: ResearchSubjectRef
    derived_claim: Claim
    supports: tuple[ResearchSupportRef, ...]

    @model_validator(mode="after")
    def _proposal_is_pre_verdict(self) -> DerivedClaimProposal:
        if self.derived_claim.claim_flavor is not ClaimFlavor.DERIVED:
            raise ValueError("proposal requires claim_flavor=derived")
        if self.derived_claim.verification_status is not VerificationStatus.UNVERIFIED:
            raise ValueError("proposal must be unverified; the engine owns the terminal state")
        return self


class DerivedClaimResultRef(BaseModel):
    """Reference-only durable result of one derivation operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    operation_id: OperationId
    derived_claim_id: ClaimId
    entailment_verdict_id: UUID
    support_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: EntailmentVerdictKind
    accepted: bool
    confidence: float = Field(ge=0, le=1)
    reason_codes: tuple[EntailmentReasonCode, ...]
    cost_cents: Decimal = Field(ge=0)


class DerivedClaimService:
    """The one authority that coordinates structural validation, judging, and terminal write."""

    def __init__(
        self,
        *,
        judge: DerivationEntailmentJudge,
        policy: DerivedClaimPolicy = DEFAULT_DERIVED_CLAIM_POLICY,
        store: DerivationStore | None = None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._judge = judge
        self._policy = policy
        self._store = store or DerivationStore()
        self._conn_factory = conn_factory

    async def derive(self, proposal: DerivedClaimProposal) -> DerivedClaimResultRef:
        existing = await self._existing(proposal.workspace_id, proposal.operation_id)
        if existing is not None:
            return existing

        scope = WorkspaceScope.for_workspace(proposal.workspace_id)
        async with self._conn_factory() as conn:
            prepared = await self._store.validate(
                conn,
                proposal.derived_claim,
                proposal.target,
                proposal.supports,
                workspace_id=proposal.workspace_id,
                scope=scope,
            )
            support_map = await claims_by_ids(
                conn,
                (support.claim_id for support in prepared.supports),
                scope=scope,
            )
        judge_supports = tuple(
            EntailmentSupport(
                claim=support_map[support.claim_id],
                role=support.role,
                ordinal=support.ordinal,
                required=support.required,
            )
            for support in prepared.supports
        )
        judge_request = EntailmentJudgeRequest(
            derived_claim=proposal.derived_claim,
            target=proposal.target,
            supports=judge_supports,
            support_set_sha256=prepared.support_set_sha256,
            policy_version=self._policy.version,
        )
        verdict = await self._judge.judge(judge_request)
        if (
            verdict.derived_claim_id != proposal.derived_claim.id
            or verdict.support_set_sha256 != prepared.support_set_sha256
        ):
            # A buggy/injected judge cannot redirect a verdict to another claim/support graph.
            # Preserve its model/cost attribution, but turn the outcome into a bounded fail-closed
            # result tied to the exact proposal the engine validated.
            verdict = verdict.model_copy(
                update={
                    "derived_claim_id": proposal.derived_claim.id,
                    "support_set_sha256": prepared.support_set_sha256,
                    "verdict": EntailmentVerdictKind.UNSUPPORTED,
                    "confidence": 0.0,
                    "reason_codes": (EntailmentReasonCode.MALFORMED_RESPONSE,),
                }
            )

        required_confidences = [
            support.claim.confidence for support in judge_supports if support.required
        ]
        propagated_confidence = min(
            min(required_confidences),
            verdict.confidence,
            self._policy.confidence_ceiling,
        )
        candidate = proposal.derived_claim.model_copy(update={"confidence": propagated_confidence})
        accepted = (
            verdict.verdict is EntailmentVerdictKind.SUPPORTED
            and verdict.confidence >= self._policy.entailment_threshold
            and can_be_promoted(candidate)
        )
        terminal_claim = candidate.model_copy(
            update={
                "verification_status": (
                    VerificationStatus.VERIFIED if accepted else VerificationStatus.REJECTED
                )
            }
        )

        async with self._conn_factory() as conn:
            # Close the pre-spend race: an operation committed while this judge was running wins.
            existing = await self._existing_in_conn(
                conn, proposal.workspace_id, proposal.operation_id
            )
            if existing is not None:
                return existing
            created = await self._store.create(
                conn,
                terminal_claim,
                proposal.target,
                proposal.supports,
                workspace_id=proposal.workspace_id,
                operation_id=proposal.operation_id,
                scope=scope,
            )
            won_by_other = await self._existing_in_conn(
                conn, proposal.workspace_id, proposal.operation_id
            )
            if won_by_other is not None:
                # ``DerivationStore.create`` rechecks after its deterministic support locks. If it
                # found another transaction's complete operation, its verdict is authoritative
                # even when this service instance uses a different model/policy configuration.
                return won_by_other
            await insert_entailment_verdict(
                conn,
                verdict,
                workspace_id=proposal.workspace_id,
                policy_version=self._policy.version,
                operation_id=proposal.operation_id,
            )
            # If another transaction won after the pre-spend check, ``create`` and verdict insert
            # resolve their existing rows. Always return the canonical durable result rather than
            # this request's potentially different model sample.
            durable = await self._existing_in_conn(
                conn, proposal.workspace_id, proposal.operation_id
            )
            if durable is None:  # pragma: no cover - guarded by the atomic inserts above
                raise RuntimeError("derived claim operation committed without a durable result")
            if durable.derived_claim_id != created.derived_claim_id:
                raise RuntimeError("derived claim operation resolved to inconsistent lineage")
            return durable

    async def _existing(
        self, workspace_id: str, operation_id: OperationId
    ) -> DerivedClaimResultRef | None:
        async with self._conn_factory() as conn:
            return await self._existing_in_conn(conn, workspace_id, operation_id)

    async def _existing_in_conn(
        self,
        conn: AsyncConnection,
        workspace_id: str,
        operation_id: OperationId,
    ) -> DerivedClaimResultRef | None:
        verdict = await load_entailment_by_operation(
            conn,
            workspace_id=workspace_id,
            operation_id=operation_id,
        )
        if verdict is None:
            return None
        row = (
            await conn.execute(
                text(
                    """
                    SELECT ev.id, c.verification_status, c.confidence
                    FROM entailment_verdict ev
                    JOIN claim c ON c.id = ev.derived_claim_id
                    WHERE ev.workspace_id = :workspace_id AND ev.operation_id = :operation_id
                    """
                ),
                {"workspace_id": workspace_id, "operation_id": operation_id},
            )
        ).one()
        return DerivedClaimResultRef(
            workspace_id=workspace_id,
            operation_id=operation_id,
            derived_claim_id=verdict.derived_claim_id,
            entailment_verdict_id=UUID(str(row[0])),
            support_set_sha256=verdict.support_set_sha256,
            verdict=verdict.verdict,
            accepted=VerificationStatus(row[1]) is VerificationStatus.VERIFIED,
            confidence=float(row[2]),
            reason_codes=verdict.reason_codes,
            cost_cents=verdict.cost_cents,
        )


__all__ = [
    "DerivedClaimPolicy",
    "DEFAULT_DERIVED_CLAIM_POLICY",
    "DerivedClaimProposal",
    "DerivedClaimResultRef",
    "DerivedClaimService",
]
