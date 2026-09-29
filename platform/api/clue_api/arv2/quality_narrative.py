"""Two-sided value arguments using the existing narrative claim/support substrate.

The specialist chooses the argument; trusted code fixes its context and resolves the seller's
original passage. Neither a product name nor the configured platform pitch counts as support.
"""

from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from pydantic import Field
from sqlalchemy import text

from clue_api.arv2.quality_claims import (
    ClaimSupport,
    NarrativeProposal,
    SellerDocumentSupport,
    SemanticAssessment,
    submit_proposal,
)
from clue_api.arv2.quality_context import read_context
from clue_api.arv2.quality_tools import ResearchClaimReceipt, _ResearchWriteTool
from clue_core import Persona
from clue_research.narrative.fields import VALUE_NARRATIVE
from clue_toolbelt import ToolContext, ToolInput, ToolOutput, ToolResult


class SubmitValueNarrativeInput(ToolInput):
    operation_key: str = Field(min_length=1, max_length=200)
    persona: Persona
    argument: str = Field(min_length=1, max_length=6000)
    angle_label: str = Field(min_length=1, max_length=200)
    target_claim_ids: tuple[UUID, ...] = Field(min_length=1, max_length=30)
    seller_support: tuple[SellerDocumentSupport, ...] = Field(min_length=1, max_length=10)
    assessment: SemanticAssessment


class SubmitValueNarrativeTool(_ResearchWriteTool):
    name = "submit_value_narrative"
    input_model = SubmitValueNarrativeInput
    output_model: ClassVar[type[ToolOutput]] = ResearchClaimReceipt
    model_description = (
        "Write one persona-keyed value argument supported on both sides: applicable target claim "
        "IDs and exact passages from selected seller capability documents. Read context.json and "
        "the original document paths first. Missing support is a gap, not an invented proposition."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        args = SubmitValueNarrativeInput.model_validate(inputs)
        authority = await self.authority(ctx)
        if authority.role != "research_narrative" or self.scope.person_subject_id:
            raise ValueError("account value narratives belong to the account narrative specialist")
        async with ctx.conn_factory() as conn:
            context = await read_context(
                conn,
                self.storage,
                workspace_id=self.scope.workspace_id,
                project_id=self.scope.project_id,
                context_id=authority.context_id,
            )
            pin = (
                await conn.execute(
                    text(
                        "SELECT icp_key,icp_version FROM arv2_research_run "
                        "WHERE run_id=:run AND context_id=:context"
                    ),
                    {"run": self.scope.run_id, "context": authority.context_id},
                )
            ).one()
            # The shared Output-4 shape and support table remain readable by downstream consumers.
            proposal = NarrativeProposal(
                operation_key=args.operation_key,
                field_key=VALUE_NARRATIVE,
                claim_kind="inference",
                value={
                    "persona": args.persona.value,
                    "argument": args.argument,
                    "angle_label": args.angle_label,
                    "icp_spec_version": pin.icp_version,
                    "icp_key": pin.icp_key,
                    "project_id": self.scope.project_id,
                    "context_id": str(authority.context_id),
                    "product_ids": [str(p) for p in sorted(context.products)],
                },
                support=(ClaimSupport(claim_ids=args.target_claim_ids), *args.seller_support),
                assessment=args.assessment,
                outreach_safe=False,
            )
            receipt = await submit_proposal(
                conn,
                self.storage,
                self.scope,
                authority.grant,
                proposal,
                context_id=authority.context_id,
                actor_ref=authority.actor_ref,
                purge_unevidenced=self.purge_unevidenced,
            )
        from dataclasses import asdict

        return ToolResult(
            tool=self.name,
            version=self.version,
            references=ResearchClaimReceipt(**asdict(receipt)).model_dump(mode="json"),
        )
