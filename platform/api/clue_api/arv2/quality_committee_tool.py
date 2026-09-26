"""Nominate an identity-resolved candidate without asserting employment or buying influence."""

from __future__ import annotations

import json
from typing import Any, ClassVar, Literal, cast
from uuid import UUID

from pydantic import Field, JsonValue
from sqlalchemy import text

from clue_api.arv2.account_research_catalog import bundle_pin
from clue_api.arv2.account_research_launch import quality_person_job_id
from clue_api.arv2.account_research_store import create_job
from clue_api.arv2.committee_discovery import read_candidate, reference_data
from clue_api.arv2.person_research_brief import save_person_brief
from clue_api.arv2.quality_catalog import load_quality_resources
from clue_api.arv2.quality_claims import ClaimProposal, SemanticAssessment, submit_proposal
from clue_api.arv2.quality_evidence import (
    JsonSupport,
    TextSupport,
    resolve_source,
    validate_support,
)
from clue_api.arv2.quality_generation import ensure_generation, register_child
from clue_api.arv2.quality_policy import advisory_research
from clue_api.arv2.quality_relationships import (
    COMMITTEE,
    SELECTION,
    CommitteeAssessment,
    OrganizationScope,
)
from clue_api.arv2.quality_tools import _ResearchWriteTool
from clue_core import EntityId
from clue_obs import get_logger
from clue_research.identity.provider import link_selection_claim, resolve_provider_contact
from clue_storage import read_verified_artifact
from clue_toolbelt import ToolContext, ToolInput, ToolOutput, ToolResult

log = get_logger("arv2.quality.committee")


class NominateCommitteeInput(ToolInput):
    candidate_ref: str = Field(min_length=1, max_length=250)
    persona_key: str = Field(min_length=1, max_length=200)
    role: Literal["champion", "economic_buyer", "technical_evaluator", "blocker", "other"]
    organization_scope: OrganizationScope
    rationale: str = Field(min_length=1, max_length=6000)


class NominateWebCommitteeInput(ToolInput):
    name: str = Field(min_length=2, max_length=200)
    linkedin_url: str | None = None
    source: TextSupport
    persona_key: str = Field(min_length=1, max_length=200)
    role: Literal["champion", "economic_buyer", "technical_evaluator", "blocker", "other"]
    organization_scope: OrganizationScope
    rationale: str = Field(min_length=1, max_length=6000)


class NominateCommitteeReceipt(ToolOutput):
    contact_id: UUID
    assessment_claim_id: UUID
    person_job_id: UUID
    generation_id: UUID
    state: Literal["candidate"] = "candidate"
    replayed: bool


class NominateCommitteeTool(_ResearchWriteTool):
    name = "nominate_committee_candidate"
    input_model: ClassVar[type[ToolInput]] = NominateCommitteeInput
    output_model: ClassVar[type[ToolOutput]] = NominateCommitteeReceipt
    model_description = (
        "Nominate a candidate from an exact saved AI Ark result. Explain the persona, potential "
        "buying role and organization/location scope. Resolves identity and prepares person "
        "research with the original profile reference. This creates a provisional candidate, "
        "never an established champion or permission for outreach. No provider purchase occurs."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        args = cast(
            "NominateCommitteeInput | NominateWebCommitteeInput "
            "| NominateSourceInput | NominateSourceWebInput",
            self.input_model.model_validate(inputs),
        )
        authority = await self.authority(ctx)
        if authority.role != "account_research" or self.scope.person_subject_id:
            raise ValueError("only the account parent may nominate candidates")
        async with ctx.conn_factory() as conn:
            # Serialize nominees/cap checks, but permit FK KEY SHARE checks from generation
            # signals. UPDATE here caused the r18 job -> generation -> job lock cycle.
            await conn.execute(
                text("SELECT job_id FROM arv2_research_job WHERE job_id=:id FOR NO KEY UPDATE"),
                {"id": self.scope.job_id},
            )
            contact, supports, refs = await self.candidate(conn, authority, args)
            generation = await ensure_generation(
                conn, authority.grant.scope, context_id=authority.context_id
            )
            job_id = quality_person_job_id(self.scope.run_id, self.scope.account_id, contact)
            count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM arv2_generation_child "
                        "WHERE generation_id=:id AND job_id<>:job"
                    ),
                    {"id": generation.generation_id, "job": job_id},
                )
            ).scalar_one()
            if count >= self.scope.committee_cap:
                raise ValueError("committee candidate cap reached; reconcile existing candidates")
            advisory = advisory_research(self.scope)
            selection: dict[str, JsonValue]
            if advisory:
                selection = {
                    "contact_id": str(contact),
                    "persona_key": args.persona_key,
                    "role": args.role,
                    "rationale": args.rationale,
                }
            else:
                assert isinstance(args, (NominateCommitteeInput, NominateWebCommitteeInput))
                selection = CommitteeAssessment(
                    account_id=self.scope.account_id,
                    contact_id=contact,
                    context_id=authority.context_id,
                    persona_key=args.persona_key,
                    role=args.role,
                    state="candidate",
                    remit="hypothesis",
                    organization_scope=args.organization_scope,
                    rationale=args.rationale,
                ).model_dump(mode="json")
            proposal = ClaimProposal(
                operation_key=f"nominate:{ctx.operation_id}",
                field_key=SELECTION if advisory else COMMITTEE,
                claim_kind="inference",
                value=selection,
                support=tuple(supports),
                outreach_safe=advisory,
                assessment=SemanticAssessment(
                    entity="supported",
                    field_meaning="supported",
                    entailment="supported",
                    relationship_direction="supported",
                    temporal_scope="supported",
                    explanation=(
                        "Source-reported affiliation and agent-selected buying role. "
                        if advisory
                        else "A provisional buying-role hypothesis "
                        "based on the exact saved discovery evidence. "
                        "Employment and buying responsibility require person research. "
                    )
                    + args.rationale[:5700],
                ),
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
            if receipt.claim_id is None:
                raise ValueError(f"candidate proposal refused: {receipt.error_code}")
            await link_selection_claim(
                conn,
                workspace_id=self.scope.workspace_id,
                contact_id=contact,
                claim_id=receipt.claim_id,
            )
            refs.update(
                subject_scope="account",
                quality_recipe_version=int(
                    (self.scope.input_refs or {}).get("quality_recipe_version", 5)
                ),
                committee_assessment_id=str(receipt.claim_id),
                generation_id=str(generation.generation_id),
            )
            if isinstance(args, (NominateBriefedInput, NominateBriefedWebInput)):
                # The parent-job lock above serializes duplicate nominations. Keep the first
                # assignment immutable if the same person is selected again or the tool replays.
                existing = (
                    await conn.execute(
                        text("SELECT input_refs FROM arv2_research_job WHERE job_id=:id"),
                        {"id": job_id},
                    )
                ).one_or_none()
                if existing is None:
                    refs["person_research_brief"] = await save_person_brief(
                        conn,
                        self.storage,
                        self.scope,
                        context_id=authority.context_id,
                        person_job_id=job_id,
                        contact_id=contact,
                        brief=args.research_brief,
                    )
                else:
                    refs = dict(existing.input_refs)
            created = await create_job(
                conn,
                job_id=job_id,
                run_id=self.scope.run_id,
                workspace_id=self.scope.workspace_id,
                account_entity_id=self.scope.account_id,
                subject_type="person",
                subject_entity_id=contact,
                profile_sha256=bundle_pin(
                    load_quality_resources(
                        "arv2-person",
                        version=int((self.scope.input_refs or {}).get("quality_recipe_version", 5)),
                    )
                ),
                profile_ref=f"agent-profile:arv2-person:{self.scope.catalog_version}",
                input_refs=refs,
            )
            await register_child(conn, generation, job_id=job_id)
            log.info(
                "arv2.quality.candidate_nominated",
                job_id=str(self.scope.job_id),
                contact_id=str(contact),
                generation_id=str(generation.generation_id),
                assessment_claim_id=str(receipt.claim_id),
                person_job_id=str(job_id),
                created=created,
                brief_sha256=(refs.get("person_research_brief") or {}).get("sha256"),
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=NominateCommitteeReceipt(
                contact_id=contact,
                assessment_claim_id=receipt.claim_id,
                person_job_id=job_id,
                generation_id=generation.generation_id,
                replayed=not created,
            ).model_dump(mode="json"),
        )

    async def candidate(
        self,
        conn: Any,
        authority: Any,
        args: NominateCommitteeInput
        | NominateWebCommitteeInput
        | NominateSourceInput
        | NominateSourceWebInput,
    ) -> tuple[EntityId, list[JsonSupport | TextSupport], dict[str, Any]]:
        if isinstance(args, (NominateWebCommitteeInput, NominateSourceWebInput)):
            from clue_api.arv2.account_research_store import read_run
            from clue_api.arv2.committee_step import _resolve_contact

            if isinstance(args, NominateSourceWebInput):
                ref = await resolve_source(conn, authority.grant, args.source_id)
                _, raw = await read_verified_artifact(
                    conn,
                    self.storage,
                    workspace_id=self.scope.workspace_id,
                    storage_key=ref.artifact_key,
                )
                passage = raw.decode()[:8000]
                web_support = TextSupport(
                    source_id=ref.source_id, start=0, end=len(passage), quote=passage
                )
            else:
                web_support = args.source
                ref = await validate_support(conn, self.storage, authority.grant, web_support)
            if not advisory_research(self.scope) and (
                ref.kind != "web_snapshot"
                or args.name.casefold() not in web_support.quote.casefold()
            ):
                raise ValueError(
                    "web nomination needs the candidate's name in an exact saved page passage"
                )
            if (
                not advisory_research(self.scope)
                and args.linkedin_url
                and args.linkedin_url not in web_support.quote
                and args.linkedin_url != ref.source_url
            ):
                raise ValueError(
                    "the LinkedIn identity must appear in the saved supporting passage"
                )
            run = await read_run(conn, run_id=self.scope.run_id)
            if run is None:
                raise ValueError("research run unavailable")
            contact, _, _ = await _resolve_contact(
                conn,
                run=run,
                account_id=self.scope.account_id,
                name=args.name,
                linkedin_url=args.linkedin_url,
            )
            return (
                contact,
                [web_support],
                {
                    "parent_job_id": str(self.scope.job_id),
                    "discovered_via": "web_gap",
                    "discovered_profile_source_id": str(ref.source_id),
                },
            )
        op, person = await read_candidate(
            conn, self.storage, authority.grant.scope, args.candidate_ref
        )
        if not person.full_name or not person.ark_id or not op.artifact_key:
            raise ValueError("provider candidate lacks a stable identity or saved original")
        contact, _ = await resolve_provider_contact(
            conn,
            workspace_id=self.scope.workspace_id,
            account_id=EntityId(self.scope.account_id),
            provider="ai_ark",
            subject_id=person.ark_id,
            name=person.full_name,
            linkedin_url=person.linkedin_url,
            artifact_key=op.artifact_key,
            require_account_match=False,
        )
        source_ids = (
            (
                await conn.execute(
                    text("""SELECT source_id FROM arv2_evidence_source
            WHERE workspace_id=:ws AND run_id=:run AND account_id=:account
              AND operation_id=:operation AND kind='provider_record' ORDER BY revision"""),
                    {
                        "ws": self.scope.workspace_id,
                        "run": self.scope.run_id,
                        "account": self.scope.account_id,
                        "operation": op.operation_id,
                    },
                )
            )
            .scalars()
            .all()
        )
        supports: list[JsonSupport | TextSupport] = []
        for source_id in source_ids:
            source = await resolve_source(conn, authority.grant, source_id)
            _, raw = await read_verified_artifact(
                conn,
                self.storage,
                workspace_id=self.scope.workspace_id,
                storage_key=source.artifact_key,
            )
            body = json.loads(raw)
            for i, row in enumerate(body.get("content", [])):
                if isinstance(row, dict) and str(row.get("id")) == person.ark_id:
                    supports.append(
                        JsonSupport(
                            source_id=source_id, pointer=f"/content/{i}", expected_value=row
                        )
                    )
        if len(supports) != 1:
            raise ValueError("candidate original is missing or ambiguous; recover its source index")
        return contact, supports, reference_data(op, person.ark_id, self.scope.job_id)


class NominateWebCommitteeTool(NominateCommitteeTool):
    name = "nominate_web_committee_candidate"
    input_model = NominateWebCommitteeInput
    model_description = (
        "Fill a committee gap left after AI Ark discovery using an exact saved web-page passage. "
        "The passage must name the candidate and any LinkedIn identity provided. Explain the "
        "specific gap, potential role and adaptive location/remit. Uses canonical identity, "
        "candidate assessment, person job and cap as AI Ark nominations; never confirms employment."
    )


class NominateSourceInput(ToolInput):
    candidate_ref: str
    persona_key: str = "general"
    role: str = "other"
    rationale: str


class NominateSourceWebInput(ToolInput):
    name: str
    linkedin_url: str | None = None
    source_id: UUID
    persona_key: str = "general"
    role: str = "other"
    rationale: str


class NominateSourceCommitteeTool(NominateCommitteeTool):
    version = "2"
    input_model = NominateSourceInput
    model_description = (
        "Select a person from a saved AI Ark company search and start their person research. "
        "Trust the source-reported affiliation and use your judgment for the buying role. "
        "No employment, location, organization or remit proof is required."
    )


class NominateSourceWebCommitteeTool(NominateCommitteeTool):
    name = "nominate_web_committee_candidate"
    version = "2"
    input_model = NominateSourceWebInput
    model_description = (
        "Select a person from a saved web source and start person research. "
        "Use source-reported affiliation and your judgment; relationship verification is deferred."
    )


class NominateBriefedInput(NominateSourceInput):
    research_brief: str = Field(
        min_length=1,
        description=(
            "Your concise person-specific delegation: purpose, seller and account context, "
            "known findings, research direction and references. Follow "
            "person-research-briefing "
            "skill; preserve the full person charter's scope."
        ),
    )


class NominateBriefedWebInput(NominateSourceWebInput):
    research_brief: str = Field(
        min_length=1,
        description=(
            "Your concise person-specific delegation: purpose, seller and account context, "
            "known findings, research direction and references. Follow "
            "person-research-briefing "
            "skill; preserve the full person charter's scope."
        ),
    )


class NominateBriefedCommitteeTool(NominateCommitteeTool):
    version = "3"
    input_model = NominateBriefedInput
    model_description = (
        "Select an already discovered person from a saved AI Ark result and delegate person "
        "research. Read person-research-briefing and write research_brief with the mission, "
        "seller/account context, known findings, questions and original-source references. "
        "Full pinned documents and account evidence remain accessible to the person worker. "
        "Source-reported affiliation is sufficient; no relationship/location proof required. "
        "Repeated nomination reuses the existing job and its original brief."
    )


class NominateBriefedWebCommitteeTool(NominateCommitteeTool):
    name = "nominate_web_committee_candidate"
    version = "3"
    input_model = NominateBriefedWebInput
    model_description = (
        "Select an already discovered person from a saved web source and delegate person "
        "research. Read person-research-briefing and write research_brief with the mission, "
        "seller/account context, known findings, questions and original-source references. "
        "Full pinned documents and account evidence remain accessible to the person worker. "
        "Source-reported affiliation is sufficient; no relationship/location proof required. "
        "Repeated nomination reuses the existing job and its original brief."
    )
