"""Nominate an identity-resolved candidate without asserting employment or buying influence."""

from __future__ import annotations

import json
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import text

from clue_api.arv2.account_research_catalog import bundle_pin
from clue_api.arv2.account_research_launch import quality_person_job_id
from clue_api.arv2.account_research_store import create_job
from clue_api.arv2.committee_discovery import read_candidate, reference_data
from clue_api.arv2.quality_catalog import load_quality_resources
from clue_api.arv2.quality_claims import ClaimProposal, SemanticAssessment, submit_proposal
from clue_api.arv2.quality_evidence import JsonSupport, resolve_source
from clue_api.arv2.quality_generation import ensure_generation, register_child
from clue_api.arv2.quality_relationships import COMMITTEE, CommitteeAssessment, OrganizationScope
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


class NominateCommitteeReceipt(ToolOutput):
    contact_id: UUID
    assessment_claim_id: UUID
    person_job_id: UUID
    generation_id: UUID
    state: Literal["candidate"] = "candidate"
    replayed: bool


class NominateCommitteeTool(_ResearchWriteTool):
    name = "nominate_committee_candidate"
    input_model = NominateCommitteeInput
    output_model: ClassVar[type[ToolOutput]] = NominateCommitteeReceipt
    model_description = (
        "Nominate a candidate from an exact saved AI Ark result. Explain the persona, potential "
        "buying role and organization/location scope. Resolves identity and prepares person "
        "research with the original profile reference. This creates a provisional candidate, "
        "never an established champion or permission for outreach. No provider purchase occurs."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        args = NominateCommitteeInput.model_validate(inputs)
        authority = await self.authority(ctx)
        if authority.role != "account_research" or self.scope.person_subject_id:
            raise ValueError("only the account parent may nominate candidates")
        async with ctx.conn_factory() as conn:
            # One lock enforces the account's cap across simultaneous tool calls and retries.
            await conn.execute(
                text("SELECT job_id FROM arv2_research_job WHERE job_id=:id FOR UPDATE"),
                {"id": self.scope.job_id},
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
            supports = []
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
                raise ValueError(
                    "candidate original is missing or ambiguous; recover its source index"
                )
            proposal = ClaimProposal(
                operation_key=f"nominate:{ctx.operation_id}",
                field_key=COMMITTEE,
                claim_kind="inference",
                value=CommitteeAssessment(
                    account_id=self.scope.account_id,
                    contact_id=contact,
                    context_id=authority.context_id,
                    persona_key=args.persona_key,
                    role=args.role,
                    state="candidate",
                    remit="hypothesis",
                    organization_scope=args.organization_scope,
                    rationale=args.rationale,
                ).model_dump(mode="json"),
                support=tuple(supports),
                outreach_safe=False,
                assessment=SemanticAssessment(
                    entity="supported",
                    field_meaning="supported",
                    entailment="supported",
                    relationship_direction="supported",
                    temporal_scope="supported",
                    explanation="A provisional buying-role hypothesis "
                    "based on the saved provider profile. "
                    "Employment and buying responsibility require person research. "
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
            refs = reference_data(op, person.ark_id, self.scope.job_id)
            refs.update(
                subject_scope="account",
                committee_assessment_id=str(receipt.claim_id),
                generation_id=str(generation.generation_id),
            )
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
                        version=int((self.scope.input_refs or {}).get("quality_recipe_version", 4)),
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
