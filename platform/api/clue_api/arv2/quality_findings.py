"""Plain research findings: source references and the agent's judgment, without field proofs."""

from dataclasses import asdict
from typing import ClassVar
from uuid import UUID

from pydantic import Field, JsonValue

from clue_api.arv2.quality_claims import (
    FindingProposal,
    SemanticAssessment,
    SourceSupport,
    submit_proposal,
)
from clue_api.arv2.quality_policy import advisory_research
from clue_api.arv2.quality_tools import ResearchClaimReceipt, _ResearchWriteTool
from clue_core import IdentityBinding, UseClass
from clue_core.equality import canonical_json
from clue_obs import get_logger
from clue_storage import content_address
from clue_toolbelt import ToolContext, ToolInput, ToolOutput, ToolResult

log = get_logger(__name__)


class RecordFindingInput(ToolInput):
    operation_key: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=200)
    finding: JsonValue
    source_ids: tuple[UUID, ...] = ()
    notes: str = ""


class RecordResearchFindingTool(_ResearchWriteTool):
    name = "record_research_finding"
    input_model: ClassVar[type[ToolInput]] = RecordFindingInput
    output_model: ClassVar[type[ToolOutput]] = ResearchClaimReceipt
    model_description = (
        "Save a research finding in plain language or JSON. Supply a topic, the finding, saved "
        "source IDs and optional uncertainty/context notes. No field catalog, quote offsets, "
        "employment proof or semantic-assessment form is required. Sources are accepted as "
        "reported. Findings and notes remain visible in page synthesis."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        args = RecordFindingInput.model_validate(inputs)
        authority = await self.authority(ctx)
        if not advisory_research(self.scope):
            raise ValueError("plain findings require research revision six")
        notes = tuple(
            n for n in (args.notes, "No source attached." if not args.source_ids else "") if n
        )
        proposal = FindingProposal(
            operation_key=args.operation_key,
            field_key=("contact" if self.scope.person_subject_id else "account")
            + ".research_finding",
            value={"topic": args.topic, "finding": args.finding, "notes": list(notes)},
            support=tuple(SourceSupport(source_id=id) for id in args.source_ids),
            assessment=SemanticAssessment(
                entity="supported",
                field_meaning="supported",
                entailment="supported",
                relationship_direction="not_applicable",
                temporal_scope="supported",
                explanation="Recorded from research; independent verification deferred.",
                qualifications=notes,
            ),
            identity_binding=IdentityBinding.WEAK if self.scope.person_subject_id else None,
            use_class=UseClass.PROFESSIONAL_PUBLIC if self.scope.person_subject_id else None,
            outreach_safe=False,
        )
        async with ctx.conn_factory() as conn:
            receipt = await submit_proposal(
                conn,
                self.storage,
                self.scope,
                authority.grant,
                proposal,
                context_id=authority.context_id,
                actor_ref=authority.actor_ref,
                purge_unevidenced=False,
            )
        log.info(
            "arv2.quality.finding_recorded",
            job_id=str(self.scope.job_id),
            operation_id=str(receipt.operation_id),
            claim_id=str(receipt.claim_id),
            status=receipt.status,
            source_count=len(args.source_ids),
            advisory=True,
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=ResearchClaimReceipt(**asdict(receipt)).model_dump(mode="json"),
        )


class RecordPathFindingInput(ToolInput):
    operation_key: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=200)
    finding: JsonValue
    source_paths: tuple[str, ...] = Field(
        default=(), description="Exact readable paths from /evidence/index.json."
    )
    notes: str = ""


class RecordPathResearchFindingTool(RecordResearchFindingTool):
    version = "2"
    input_model = RecordPathFindingInput
    model_description = RecordResearchFindingTool.model_description.replace(
        "source IDs", "source_paths copied from /evidence/index.json or ls /evidence"
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        from clue_api.arv2.quality_evidence import resolve_source

        args = RecordPathFindingInput.model_validate(inputs)
        authority = await self.authority(ctx)
        async with ctx.conn_factory() as conn:
            ids = tuple(
                [
                    (await resolve_source(conn, authority.grant, path)).source_id
                    for path in args.source_paths
                ]
            )
        return await super().invoke(
            RecordFindingInput(**args.model_dump(exclude={"source_paths"}), source_ids=ids), ctx
        )


class RecordContentFindingInput(ToolInput):
    topic: str = Field(min_length=1, max_length=200)
    finding: JsonValue
    source_paths: tuple[str, ...] = Field(
        default=(), description="Exact readable paths from /evidence/index.json."
    )
    notes: str = ""


class RecordContentResearchFindingTool(RecordResearchFindingTool):
    """New findings identify themselves by their canonical content within the research job.

    This is exact retry protection, not semantic deduplication or a correction mechanism.
    Old versions retain their immutable caller-key contract for already pinned executions.
    """

    version = "3"
    input_model = RecordContentFindingInput
    model_description = RecordPathResearchFindingTool.model_description + (
        " Write identity is assigned automatically. An identical finding and sources replay "
        "the existing receipt; different content creates a separate finding. Use correction "
        "tools to change an earlier finding. Do not invent an operation key."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        from clue_api.arv2.quality_evidence import resolve_source

        args = RecordContentFindingInput.model_validate(inputs)
        authority = await self.authority(ctx)
        async with ctx.conn_factory() as conn:
            ids = tuple(
                sorted(
                    {
                        (await resolve_source(conn, authority.grant, path)).source_id
                        for path in args.source_paths
                    }
                )
            )
        # Canonicalize object order as well as source order before both hashing and submission:
        # submit_proposal checks the bytes of the immutable proposal on a retry.
        import json

        payload = json.loads(
            canonical_json(
                {
                    **args.model_dump(mode="json", exclude={"source_paths"}),
                    "source_ids": [str(id) for id in ids],
                }
            )
        )
        key = "finding:" + content_address(canonical_json(payload).encode())
        return await super().invoke(RecordFindingInput(operation_key=key, **payload), ctx)
