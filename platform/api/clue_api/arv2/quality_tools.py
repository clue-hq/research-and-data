"""Governed specialist write tools; all scope comes from the execution, never arguments.

Read originals through the revocable workspace. These tools return durable receipt identities,
not copied documents. Provider acquisition remains the existing ARV2 tool runtime's responsibility.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Annotated, ClassVar, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.evidence_paths import source_path
from clue_api.arv2.quality_authority import ResearchAuthority, resolve_authority
from clue_api.arv2.quality_claims import ClaimProposal, ClaimSupport, submit_proposal
from clue_api.arv2.quality_evidence import JsonSupport, TextSupport, validate_support
from clue_api.arv2.quality_execution import reserve, retry_lock_conflict
from clue_research.claimstore.quality import assess_claim
from clue_storage import StorageBackend, artifact_key, content_address, record_artifact
from clue_toolbelt import (
    PreconditionFailed,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
    ToolResult,
)


class SubmitResearchClaimInput(ToolInput):
    proposal: ClaimProposal


class CorrectResearchClaimInput(ToolInput):
    operation_key: str = Field(min_length=1, max_length=200)
    claim_id: UUID
    expected_revision: int = Field(ge=0)
    action: Literal["withdrawal", "correction", "conflict"]
    replacement_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=6000)
    support: tuple[Annotated[TextSupport | JsonSupport, Field(discriminator="kind")], ...] = Field(
        default=(), max_length=30
    )

    @model_validator(mode="after")
    def replacement_matches_action(self) -> CorrectResearchClaimInput:
        if (self.action == "correction") != (self.replacement_id is not None):
            raise ValueError("correction requires a replacement; withdrawal/conflict do not")
        return self


class ResearchClaimReceipt(ToolOutput):
    operation_id: UUID
    claim_id: UUID | None
    status: str
    error_code: str | None = None
    replayed: bool = False
    assessment_id: UUID | None = None
    revision: int | None = None
    replacement_id: UUID | None = None


class _ResearchWriteTool(Tool):
    output_model: ClassVar[type[ToolOutput]] = ResearchClaimReceipt
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="research job + proposal/correction key + immutable request digest",
        operation_id_required=True,
    )

    def __init__(self, scope: JobScope, storage: StorageBackend, *, purge_unevidenced: bool):
        self.scope = scope
        self.storage = storage
        self.purge_unevidenced = purge_unevidenced

    async def authority(self, ctx: ToolContext) -> ResearchAuthority:
        if ctx.workspace_id != self.scope.workspace_id or ctx.execution_id is None:
            raise ValueError("research tool requires its bound workspace execution")
        execution_id = ctx.execution_id

        async def authorize(conn: AsyncConnection) -> ResearchAuthority:
            authority = await resolve_authority(conn, self.scope, execution_id)
            if authority.role not in ("account_research", "research_claims", "research_narrative"):
                raise ValueError("role has no research claim authority")
            await reserve(
                conn,
                authority.grant.scope,
                execution_id=authority.execution_id,
                kind="tool",
                activity_id=UUID(str(ctx.operation_id)),
            )
            return authority

        return await retry_lock_conflict(ctx.conn_factory, authorize)


class SubmitResearchClaimTool(_ResearchWriteTool):
    name = "submit_research_claim"
    input_model = SubmitResearchClaimInput
    model_description = (
        "Propose one supported observation, attributed statement or claim-backed inference. "
        "Use exact original source IDs and contiguous text offsets, provider JSON pointers, or "
        "applicable claim IDs. Assess entity, field meaning, relationship direction and time. "
        "A refusal returns its reason; the same operation key must never identify changed content."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        args = SubmitResearchClaimInput.model_validate(inputs)
        authority = await self.authority(ctx)
        if authority.role == "research_narrative" and (
            args.proposal.claim_kind != "inference"
            or not all(isinstance(s, ClaimSupport) for s in args.proposal.support)
            or not args.proposal.field_key.startswith(("account.narrative.", "contact.narrative."))
        ):
            raise ValueError(
                "narrative specialist may only write claim-backed narrative inferences"
            )
        async with ctx.conn_factory() as conn:
            receipt = await submit_proposal(
                conn,
                self.storage,
                self.scope,
                authority.grant,
                args.proposal,
                context_id=authority.context_id,
                actor_ref=authority.actor_ref,
                purge_unevidenced=self.purge_unevidenced,
            )
        result = ResearchClaimReceipt(**asdict(receipt))
        return ToolResult(
            tool=self.name, version=self.version, references=result.model_dump(mode="json")
        )


class CorrectResearchClaimTool(_ResearchWriteTool):
    name = "correct_research_claim"
    input_model = CorrectResearchClaimInput
    model_description = (
        "Withdraw an invalid observation, replace it with an already supported claim, or mark an "
        "unresolved conflict. Read the current assessment revision first. Corrections affect "
        "current factual readers and invalidate dependent output while preserving audit history. "
        "This tool cannot promote a claim; submit a properly evidenced proposal for that."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        args = CorrectResearchClaimInput.model_validate(inputs)
        authority = await self.authority(ctx)
        if authority.role == "research_narrative":
            raise ValueError("request a claim specialist to correct supporting facts")
        async with ctx.conn_factory() as conn:
            # Recheck immediately before the write transaction, after any prior tool wake.
            authority = await resolve_authority(conn, self.scope, authority.execution_id)
            refs = [
                await validate_support(conn, self.storage, authority.grant, s) for s in args.support
            ]
            # A project-specific replacement cannot smuggle another project's interpretation.
            if args.replacement_id:
                replacement = (
                    await conn.execute(
                        text("""SELECT write_markers FROM claim
                  WHERE id=:id AND workspace_id=:ws AND entity_id=:subject"""),
                        {
                            "id": args.replacement_id,
                            "ws": self.scope.workspace_id,
                            "subject": self.scope.person_subject_id or self.scope.account_id,
                        },
                    )
                ).scalar_one_or_none()
                if replacement is None or replacement.get("context_id") not in (
                    None,
                    str(authority.context_id),
                ):
                    raise ValueError("replacement belongs to another context or subject")
            raw = json.dumps(
                {"request": args.model_dump(mode="json"), "context_id": str(authority.context_id)},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            sha = content_address(raw)
            key = artifact_key(self.scope.workspace_id, sha)
            await record_artifact(
                conn,
                storage_key=key,
                workspace_id=self.scope.workspace_id,
                content_sha256=sha,
                media_type="application/json",
                size_bytes=len(raw),
            )
            await self.storage.put(key, raw, media_type="application/json")
            supports = tuple(
                sorted({k for ref in refs for k in (ref.artifact_key, ref.original_key) if k})
            )
            for source in supports:
                await conn.execute(
                    text("""INSERT INTO artifact_derivation(workspace_id,parent_key,child_key)
                  VALUES (:ws,:parent,:child) ON CONFLICT DO NOTHING"""),
                    {"ws": self.scope.workspace_id, "parent": source, "child": key},
                )
            oid = uuid5(
                NAMESPACE_URL, f"research-correction:{self.scope.job_id}:{args.operation_key}"
            )
            receipt = await assess_claim(
                conn,
                workspace_id=self.scope.workspace_id,
                entity_id=self.scope.person_subject_id or self.scope.account_id,
                claim_id=args.claim_id,
                operation_id=oid,
                expected_revision=args.expected_revision,
                conclusion="unresolved" if args.action == "conflict" else "invalid",
                rationale_key=key,
                actor_ref=authority.actor_ref,
                support_artifacts=supports,
                context_id=authority.context_id,
                kind=args.action,
                replacement_id=args.replacement_id,
            )
        value = asdict(receipt)
        value["status"] = value.pop("conclusion")
        result = ResearchClaimReceipt(**value)
        return ToolResult(
            tool=self.name, version=self.version, references=result.model_dump(mode="json")
        )


class SearchEvidenceInput(ToolInput):
    source_id: UUID
    query: str = Field(min_length=1, max_length=500)
    start: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=20)


class EvidenceMatch(ToolOutput):
    start: int
    end: int
    path: str


class SearchEvidenceOutput(ToolOutput):
    source_id: UUID
    matches: tuple[EvidenceMatch, ...]
    next_start: int | None


class SearchEvidenceTool(_ResearchWriteTool):
    name = "search_evidence"
    input_model: ClassVar[type[ToolInput]] = SearchEvidenceInput
    output_model = SearchEvidenceOutput
    effect_class = ToolEffectClass.READ
    model_description = (
        "Find exact literal text in one granted original, with bounded results and continuation. "
        "Returns source offsets and authorized virtual paths; read those paths to inspect wording. "
        "A search hit is not a processed source or a supported claim."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        from clue_api.arv2.quality_evidence import resolve_source, search_source

        args = SearchEvidenceInput.model_validate(inputs)
        authority = await self.authority(ctx)
        async with ctx.conn_factory() as conn:
            source = await resolve_source(conn, authority.grant, args.source_id)
            result = await search_source(
                conn,
                self.storage,
                authority.grant,
                args.source_id,
                query=args.query,
                start=args.start,
                limit=args.limit,
            )
        value = SearchEvidenceOutput(
            source_id=args.source_id,
            next_start=result["next_start"],
            matches=tuple(
                EvidenceMatch(
                    start=m["start"],
                    end=m["end"],
                    path=source_path(source.model_dump()),
                )
                for m in result["matches"]
            ),
        )
        return ToolResult(
            tool=self.name, version=self.version, references=value.model_dump(mode="json")
        )


class ProcessingDispositionInput(ToolInput):
    source_id: UUID
    unit_locator: str = Field(min_length=1, max_length=300)
    decision: Literal["written", "reused", "excluded", "conflict", "unprocessed", "gap"]
    reason: str = Field(min_length=1, max_length=4000)
    claim_ids: tuple[UUID, ...] = Field(default=(), max_length=50)


class ProcessingDispositionOutput(ToolOutput):
    disposition_id: UUID
    source_id: UUID
    decision: str


class ProcessingDispositionTool(_ResearchWriteTool):
    name = "record_research_disposition"
    input_model: ClassVar[type[ToolInput]] = ProcessingDispositionInput
    output_model = ProcessingDispositionOutput
    model_description = (
        "Record which source unit was processed, excluded, conflicted, or needs follow-up and why. "
        "Name the exact source and a stable unit locator. Written findings must reference real "
        "claims; a receipt records work, not a guarantee that all useful findings were discovered."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        from clue_api.arv2.quality_evidence import record_disposition

        args = ProcessingDispositionInput.model_validate(inputs)
        authority = await self.authority(ctx)
        if authority.role == "research_narrative":
            raise ValueError("source processing belongs to research and claim specialists")
        async with ctx.conn_factory() as conn:
            if args.decision == "written" and not args.claim_ids:
                raise ValueError("written disposition requires claim references")
            if args.claim_ids:
                count = (
                    await conn.execute(
                        text("""SELECT count(*) FROM claim WHERE id=ANY(:ids)
                  AND workspace_id=:ws AND entity_id=:subject"""),
                        {
                            "ids": list(set(args.claim_ids)),
                            "ws": self.scope.workspace_id,
                            "subject": self.scope.person_subject_id or self.scope.account_id,
                        },
                    )
                ).scalar_one()
                if count != len(set(args.claim_ids)):
                    raise ValueError("disposition claims are outside this research subject")
            did = await record_disposition(
                conn,
                self.storage,
                authority.grant,
                source_id=args.source_id,
                unit_locator=args.unit_locator,
                decision=args.decision,
                receipt={"reason": args.reason, "claim_ids": [str(i) for i in args.claim_ids]},
            )
        value = ProcessingDispositionOutput(
            disposition_id=did, source_id=args.source_id, decision=args.decision
        )
        return ToolResult(
            tool=self.name, version=self.version, references=value.model_dump(mode="json")
        )


class SearchPathEvidenceInput(ToolInput):
    source_path: str = Field(description="Exact readable path from /evidence/index.json.")
    query: str = Field(min_length=1, max_length=500)
    start: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=20)


class SearchPathEvidenceTool(SearchEvidenceTool):
    version = "2"
    input_model = SearchPathEvidenceInput
    model_description = (
        SearchEvidenceTool.model_description
        + " Supply the readable source_path from the evidence index."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        from clue_api.arv2.quality_evidence import EvidenceUnavailable, resolve_source
        from clue_api.arv2.quality_recipe import RECIPE_26, at_least

        args = SearchPathEvidenceInput.model_validate(inputs)
        authority = await self.authority(ctx)
        async with ctx.conn_factory() as conn:
            try:
                source = await resolve_source(conn, authority.grant, args.source_path)
            except EvidenceUnavailable as exc:
                if not at_least(self.scope, RECIPE_26):
                    raise
                # Recipe 26+: a wrong reference is a refused read, not a failed attempt that
                # blocks finalize_turn until repaired (7 of 12 production jobs, 2026-10-06).
                hint = (
                    " search_evidence searches original sources under /evidence/. To search "
                    "a research view, use grep on that file, or read it."
                    if args.source_path.startswith("/research/")
                    else ""
                )
                raise PreconditionFailed(
                    [PreconditionFailure("invalid_source_reference", f"{exc}{hint}")]
                ) from exc
        return await super().invoke(
            SearchEvidenceInput(
                **args.model_dump(exclude={"source_path"}), source_id=source.source_id
            ),
            ctx,
        )


class PathProcessingDispositionInput(ToolInput):
    source_path: str = Field(description="Exact readable path from /evidence/index.json.")
    unit_locator: str = Field(min_length=1, max_length=300)
    decision: Literal["written", "reused", "excluded", "conflict", "unprocessed", "gap"]
    reason: str = Field(min_length=1, max_length=4000)
    claim_ids: tuple[UUID, ...] = Field(default=(), max_length=50)


class PathProcessingDispositionTool(ProcessingDispositionTool):
    version = "2"
    input_model = PathProcessingDispositionInput
    model_description = (
        ProcessingDispositionTool.model_description
        + " Supply the readable source_path from the evidence index."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        from clue_api.arv2.quality_evidence import resolve_source

        args = PathProcessingDispositionInput.model_validate(inputs)
        authority = await self.authority(ctx)
        async with ctx.conn_factory() as conn:
            source = await resolve_source(conn, authority.grant, args.source_path)
        return await super().invoke(
            ProcessingDispositionInput(
                **args.model_dump(exclude={"source_path"}), source_id=source.source_id
            ),
            ctx,
        )
