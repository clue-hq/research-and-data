"""Composition-root coordinator for approved dynamic Client-KB field materialization.

The Stage-0 package owns the durable operation, but it deliberately cannot import either artifact
storage/projections or the M9.3 judge. This adapter joins those existing seams without duplicating
quote verification or entailment policy and never keeps a database transaction open across I/O.
"""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict

from clue_db import ConnFactory
from clue_projections.stage0 import ExcludedEvidence, ResolvedQuote, StatementEvidenceReader
from clue_research.proposals import FieldProposal
from clue_research.stage0 import (
    ClaimEntailmentJudge,
    InterviewEvidenceRefused,
    VolunteeredStatementRow,
    check_claim_value_entailment,
)
from clue_research.stage0.dynamic_client_kb import (
    FieldMaterializationReceipt,
    materialize_approved_field,
    prepare_field_materialization,
    record_field_materialization_refusal,
)


class MaterializedFieldRefs(BaseModel):
    """The reference-only result a governed tool may expose."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    materialization_id: str
    materialization_status: str
    claim_ref: str | None = None
    client_kb_version: int | None = None
    refusal_code: str | None = None


class DynamicClientKbMaterializer:
    """Run the durable materializer over the artifact-backed evidence and existing judge."""

    def __init__(
        self,
        *,
        evidence: StatementEvidenceReader,
        entailment_judge: ClaimEntailmentJudge | None,
    ) -> None:
        self._evidence = evidence
        self._entailment_judge = entailment_judge

    async def materialize(
        self,
        *,
        proposal: FieldProposal,
        workspace_id: str,
        conn_factory: ConnFactory,
    ) -> MaterializedFieldRefs:
        details = proposal.payload.client_kb
        if details is None:
            raise ValueError("field proposal is not a dynamic Client-KB proposal")

        # Transaction 1: re-resolve the independently committed promotion and immutable statement.
        async with conn_factory() as conn:
            plan, existing = await prepare_field_materialization(
                conn,
                workspace_id=workspace_id,
                proposal_id=proposal.id,
                statement_id=details.source_statement_id,
            )
        if existing is not None:
            return _refs(existing)

        # Artifact I/O + any LLM judgment happen with no transaction/connection held.
        evidence = await self._evidence.resolve_quote(
            workspace_id=workspace_id,
            statement=cast(VolunteeredStatementRow, plan.statement),
        )
        if isinstance(evidence, ExcludedEvidence):
            async with conn_factory() as conn:
                receipt = await record_field_materialization_refusal(
                    conn, plan=plan, reason_code="statement_evidence_missing"
                )
            return _refs(receipt)
        assert isinstance(evidence, ResolvedQuote)
        try:
            judged = await check_claim_value_entailment(
                field_key=plan.field_key,
                value=plan.candidate_value,
                quote=evidence.quote,
                entity_id=plan.client_entity_id,
                entailment_judge=self._entailment_judge,
            )
        except InterviewEvidenceRefused as exc:
            async with conn_factory() as conn:
                receipt = await record_field_materialization_refusal(
                    conn, plan=plan, reason_code=exc.reason_code
                )
            return _refs(receipt)

        # Transaction 2: recheck durable inputs (including corrections/retirement), then write one
        # claim and one receipt atomically. Replay returns the receipt before attempting either.
        async with conn_factory() as conn:
            current, existing = await prepare_field_materialization(
                conn,
                workspace_id=workspace_id,
                proposal_id=proposal.id,
                statement_id=details.source_statement_id,
            )
            if existing is not None:
                return _refs(existing)
            receipt = await materialize_approved_field(
                conn, plan=current, quote=evidence.quote, judged=judged
            )
        return _refs(receipt)


def _refs(receipt: FieldMaterializationReceipt) -> MaterializedFieldRefs:
    return MaterializedFieldRefs(
        materialization_id=str(receipt.id),
        materialization_status=receipt.status.value,
        claim_ref=str(receipt.claim_id) if receipt.claim_id is not None else None,
        client_kb_version=receipt.client_kb_version,
        refusal_code=receipt.refusal_code,
    )


__all__ = ["DynamicClientKbMaterializer", "MaterializedFieldRefs"]
