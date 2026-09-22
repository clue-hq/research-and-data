"""Typed specialist proposals: resolve originals, validate shape, then assess the stored claim."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import ALWAYS_UNSAFE_FIELDS, JobScope
from clue_api.arv2.claim_writer import ClaimDraft, DerivedClaimInput, LenientClaimWriter
from clue_api.arv2.quality_context import read_context
from clue_api.arv2.quality_evidence import (
    EvidenceGrant,
    EvidenceUnavailable,
    JsonSupport,
    SourceRef,
    TextSupport,
    authorize_grant,
    record_disposition,
    validate_support,
)
from clue_api.arv2.quality_relationships import (
    EMPLOYMENT,
    CommitteeAssessment,
    validate_relationship,
)
from clue_core import (
    ClaimId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    OperationId,
    ResearchMode,
    ResearchSubjectRef,
    ResearchSupportRef,
    ResearchSupportRole,
    ReuseScope,
    RunId,
    UseClass,
)
from clue_research.claimstore import WorkspaceScope, claims_by_ids
from clue_research.claimstore.derivations import (
    DerivationDependencyResolver,
    DerivationDependencyState,
)
from clue_research.claimstore.quality import Quality, assess_claim
from clue_research.claimstore.registry import (
    FieldRegistryScope,
    ValueSchemaError,
    check_claim_writable,
    get_effective_field,
    list_research_fields,
    register_agent_research_field,
)
from clue_research.identity import get_account, get_contact
from clue_storage import (
    ArtifactIntegrityError,
    StorageBackend,
    artifact_key,
    content_address,
    read_verified_artifact,
    record_artifact,
    retain_artifact,
)


class ClaimSupport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["claims"] = "claims"
    claim_ids: tuple[UUID, ...] = Field(min_length=1, max_length=30)


class SemanticAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    entity: Literal["supported", "uncertain", "contradicted"]
    field_meaning: Literal["supported", "uncertain", "contradicted"]
    entailment: Literal["supported", "uncertain", "contradicted"]
    relationship_direction: Literal["supported", "uncertain", "contradicted", "not_applicable"]
    temporal_scope: Literal["supported", "uncertain", "contradicted"]
    explanation: str = Field(min_length=1, max_length=6000)
    qualifications: tuple[str, ...] = ()

    def conclusion(self) -> Quality:
        values = (
            self.entity,
            self.field_meaning,
            self.entailment,
            self.relationship_direction,
            self.temporal_scope,
        )
        if "contradicted" in values:
            return "invalid"
        if "uncertain" in values:
            return "unresolved"
        return "qualified" if self.qualifications else "supported"


class ClaimProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_key: str = Field(min_length=1, max_length=200)
    field_key: str = Field(min_length=1, max_length=200)
    field_version: int | None = Field(default=None, ge=1)
    value: JsonValue
    claim_kind: Literal["observation", "attributed_statement", "inference"] = "observation"
    support: tuple[
        Annotated[TextSupport | JsonSupport | ClaimSupport, Field(discriminator="kind")], ...
    ] = Field(min_length=1, max_length=30)
    assessment: SemanticAssessment
    identity_binding: IdentityBinding | None = None
    use_class: UseClass | None = None
    outreach_safe: bool = True


@dataclass(frozen=True)
class ProposalReceipt:
    operation_id: UUID
    claim_id: UUID | None
    status: str
    error_code: str | None = None
    replayed: bool = False


async def submit_proposal(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    grant: EvidenceGrant,
    proposal: ClaimProposal,
    *,
    context_id: UUID,
    actor_ref: str,
    purge_unevidenced: bool = True,
) -> ProposalReceipt:
    subject = scope.person_subject_id or scope.account_id
    if (
        grant.scope.workspace_id,
        grant.scope.run_id,
        grant.scope.job_id,
        grant.scope.account_id,
    ) != (scope.workspace_id, scope.run_id, scope.job_id, scope.account_id):
        raise EvidenceUnavailable("proposal grant belongs to another research subject")
    pinned = (
        await conn.execute(
            text(
                "SELECT context_id FROM arv2_research_run WHERE run_id=:run "
                "AND workspace_id=:ws AND project_id=:project"
            ),
            {"run": scope.run_id, "ws": scope.workspace_id, "project": scope.project_id},
        )
    ).scalar_one_or_none()
    if pinned != context_id:
        raise EvidenceUnavailable("proposal requires the exact run context")
    await authorize_grant(conn, grant)
    raw = proposal.model_dump_json().encode()
    sha = content_address(raw)
    oid = uuid5(NAMESPACE_URL, f"claim-proposal:{scope.job_id}:{proposal.operation_key}")
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"quality-proposal:{oid}"},
    )
    old = (
        (
            await conn.execute(
                text("SELECT * FROM arv2_quality_proposal WHERE operation_id=:id"), {"id": oid}
            )
        )
        .mappings()
        .one_or_none()
    )
    if old is not None:
        if old["workspace_id"] != scope.workspace_id or old["request_sha256"] != sha:
            raise ValueError("proposal operation key already has different content; use a new key")
        return ProposalReceipt(oid, old["claim_id"], old["status"], old["error_code"], True)
    refs: list[SourceRef] = []
    support_keys: set[str] = set()
    supporting: dict[UUID, ResearchSupportRole] = {}
    error = None
    assessment = proposal.assessment.conclusion()
    field = await get_effective_field(
        conn,
        scope=FieldRegistryScope.for_workspace(scope.workspace_id),
        field_key=proposal.field_key,
    )
    # Scope is checked independently of whether a globally registered key happens to exist.
    prefix = "contact." if scope.subject_kind == "person" else "account."
    menu = await list_research_fields(
        conn,
        workspace_id=scope.workspace_id,
        entity="contacts" if scope.subject_kind == "person" else "accounts",
    )
    allowed_keys = {item.field_def.field_key for item in menu}
    if proposal.field_key not in allowed_keys and (
        field is not None or not proposal.field_key.startswith(prefix)
    ):
        error = "field_subject_mismatch"
    if field is not None and proposal.field_version not in (None, field.definition_version):
        error = "field_definition_changed"
    context = await read_context(
        conn,
        storage,
        workspace_id=scope.workspace_id,
        project_id=scope.project_id,
        context_id=context_id,
    )
    catalog_pin = next(
        (
            p
            for p in context.field_catalog
            if p.field_key == proposal.field_key
            and p.entity == ("contacts" if scope.person_subject_id else "accounts")
        ),
        None,
    )
    if catalog_pin is not None and (
        field is None
        or catalog_pin.version != field.definition_version
        or catalog_pin.value_type != field.field_def.value_type
        or catalog_pin.validation != field.field_def.validation
        or catalog_pin.value_schema != field.value_schema
        or catalog_pin.description != field.description
    ):
        error = "field_definition_changed"
    relationship = None
    try:
        relationship = await validate_relationship(
            conn,
            workspace_id=scope.workspace_id,
            account_id=scope.account_id,
            contact_id=scope.person_subject_id,
            context_id=context_id,
            field_key=proposal.field_key,
            value=proposal.value,
            support_claim_ids={
                cid for s in proposal.support if isinstance(s, ClaimSupport) for cid in s.claim_ids
            },
        )
    except ValueError:
        error = "relationship_assessment_invalid"
    try:
        for support in proposal.support:
            if isinstance(support, ClaimSupport):
                if proposal.claim_kind != "inference":
                    raise EvidenceUnavailable(
                        "claim references require an explicitly labelled inference"
                    )
                if len(proposal.support) != 1:
                    raise EvidenceUnavailable("use one complete claim support set for an inference")
                claims = await claims_by_ids(
                    conn,
                    [ClaimId(cid) for cid in support.claim_ids],
                    scope=WorkspaceScope.for_workspace(scope.workspace_id),
                )
                if len(claims) != len(set(support.claim_ids)):
                    raise EvidenceUnavailable("supporting claim is no longer applicable")
                for claim in claims.values():
                    committee_support = (
                        isinstance(relationship, CommitteeAssessment)
                        and claim.entity_id == relationship.contact_id
                        and claim.id in relationship.employment_claim_ids
                        and claim.field_key == EMPLOYMENT
                    )
                    if (
                        claim.entity_id not in (subject, scope.account_id) and not committee_support
                    ) or not claim.artifact_key:
                        raise EvidenceUnavailable(
                            "supporting claim is outside subject or lacks original evidence"
                        )
                    support_keys.add(claim.artifact_key)
                    resolved = await DerivationDependencyResolver().resolve(
                        conn, claim.id, scope=WorkspaceScope.for_workspace(scope.workspace_id)
                    )
                    if resolved.state is not DerivationDependencyState.ELIGIBLE_FRESH:
                        raise EvidenceUnavailable("supporting claim needs review or recheck")
                    supporting[claim.id] = (
                        ResearchSupportRole.DIRECT_EVIDENCE
                        if claim.entity_id == subject
                        else ResearchSupportRole.ACCOUNT_SIGNAL
                    )
                    await read_verified_artifact(
                        conn,
                        storage,
                        workspace_id=scope.workspace_id,
                        storage_key=claim.artifact_key,
                    )
                    # An inference cannot quietly import another project's interpretation.
                    marker_context = (claim.write_markers or {}).get("context_id")
                    if marker_context and marker_context != str(context_id):
                        raise EvidenceUnavailable("supporting claim has another context")
            else:
                ref = await validate_support(conn, storage, grant, support)
                if ref.kind == "seller_document":
                    raise EvidenceUnavailable("seller material cannot establish a target fact")
                if ref.kind == "research_report" and proposal.claim_kind == "observation":
                    raise EvidenceUnavailable(
                        "research reports require attributed_statement or inference"
                    )
                refs.append(ref)
                support_keys.add(ref.artifact_key)
                if ref.original_key:
                    support_keys.add(ref.original_key)
                if ref.kind == "transcript":
                    # No blanket speaker promotion: the media-specific submission adapter must
                    # prove a current version and binding before asserting personal words.
                    raise EvidenceUnavailable(
                        "transcript requires the version-and-speaker support adapter"
                    )
    except (EvidenceUnavailable, ArtifactIntegrityError):
        error = "evidence_not_resolved"
        # Refused references may point at erased or foreign data. Retain a receipt, never a
        # fresh copy of the unverified value/quote the caller supplied with that reference.
        raw = json.dumps({"operation_id": str(oid), "error": error}).encode()
    stored_sha = content_address(raw)
    key = artifact_key(scope.workspace_id, stored_sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=scope.workspace_id,
        content_sha256=stored_sha,
        media_type="application/json",
        size_bytes=len(raw),
    )
    await storage.put(key, raw, media_type="application/json")
    await retain_artifact(
        conn,
        workspace_id=scope.workspace_id,
        storage_key=key,
        reference_kind="claim_proposal",
        reference_id=str(oid),
    )
    # Erasing source bytes also erases a draft that copied their quotation, not just live claims.
    for source_key in sorted(support_keys):
        if source_key != key:
            await conn.execute(
                text(
                    "INSERT INTO artifact_derivation(workspace_id,parent_key,child_key) "
                    "VALUES(:ws,:parent,:child) ON CONFLICT DO NOTHING"
                ),
                {"ws": scope.workspace_id, "parent": source_key, "child": key},
            )
    cid = None
    if not error:
        if field is None:
            await register_agent_research_field(
                conn,
                workspace_id=scope.workspace_id,
                field_key=proposal.field_key,
                run_id=str(scope.run_id),
            )
        try:
            await check_claim_writable(
                conn,
                field_key=proposal.field_key,
                value_json=proposal.value,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=scope.workspace_id,
                product_id=None,
            )
        except ValueSchemaError:
            error = "value_schema_invalid"
    if not error:
        provider = (
            actor_ref == "deterministic-provider-mapping:v1"
            and bool(refs)
            and all(r.kind == "provider_record" for r in refs)
            and proposal.claim_kind == "observation"
        )
        method = ExtractionMethod.API if provider else ExtractionMethod.LLM_SYNTHESIS
        first = refs[0] if refs else None
        quotes = [s.quote for s in proposal.support if isinstance(s, TextSupport)]
        markers: dict[str, JsonValue] = {
            "quality_required": True,
            "claim_kind": proposal.claim_kind,
            "support": [s.model_dump(mode="json") for s in proposal.support],
            "qualifications": list(proposal.assessment.qualifications),
            "proposal_ref": str(oid),
            "context_id": str(context_id),
        }
        draft = ClaimDraft(
            entity_id=subject,
            entity_type=EntityType.CONTACT
            if scope.subject_kind == "person"
            else EntityType.ACCOUNT,
            field_key=proposal.field_key,
            value_json=proposal.value,
            extraction_method=method,
            run_id=RunId(scope.run_id),
            research_mode=(
                ResearchMode.CONTACT_PROFILING
                if scope.subject_kind == "person"
                else ResearchMode.ACCOUNT_PROFILING
            ),
            workspace_id=scope.workspace_id,
            source_url=first.source_url if first else None,
            source_key=f"research:{first.kind}" if first else "research:inference",
            evidence_span=quotes[0] if quotes else None,
            artifact_key=first.artifact_key if first else key,
            observed_at=first.observed_at if first else None,
            confidence=0.5,
            identity_binding=proposal.identity_binding,
            use_class=proposal.use_class,
            outreach_safe=proposal.outreach_safe
            and assessment == "supported"
            and proposal.field_key not in ALWAYS_UNSAFE_FIELDS
            and (
                not isinstance(relationship, CommitteeAssessment)
                or relationship.state == "supported"
            ),
            markers=markers,
        )
        if scope.subject_kind == "person":
            from clue_api.arv2.person_compliance import apply_person_floor

            kept, _ = apply_person_floor([draft], purge_unevidenced=purge_unevidenced)
            if not kept:
                error = "personal_use_refused"
            else:
                draft = kept[0]
        if not error:
            derivation = None
            if supporting:
                entity = await (
                    get_contact(conn, subject)
                    if scope.subject_kind == "person"
                    else get_account(conn, subject)
                )
                if entity is None:
                    raise EvidenceUnavailable("subject identity unavailable")
                derivation = DerivedClaimInput(
                    target=ResearchSubjectRef(
                        entity_id=subject,
                        entity_type=draft.entity_type,
                        canonical_entity_version=entity.canonical_version,
                    ),
                    supports=tuple(
                        ResearchSupportRef(claim_id=ClaimId(id), role=role, ordinal=i)
                        for i, (id, role) in enumerate(supporting.items())
                    ),
                    operation_id=OperationId(oid),
                )
            receipt = await LenientClaimWriter(lenient=True, scoped_proposals=True).write(
                conn, draft, derivation=derivation
            )
            cid = UUID(str(receipt.claim_id))
            await assess_claim(
                conn,
                workspace_id=scope.workspace_id,
                entity_id=subject,
                claim_id=cid,
                operation_id=oid,
                expected_revision=0,
                conclusion=assessment,
                rationale_key=key,
                actor_ref=actor_ref,
                support_artifacts=tuple(sorted(support_keys)),
                context_id=context_id,
            )
            for ref in refs:
                await record_disposition(
                    conn,
                    storage,
                    grant,
                    source_id=ref.source_id,
                    unit_locator=proposal.operation_key,
                    decision="written"
                    if assessment in ("supported", "qualified")
                    else "conflict"
                    if assessment == "unresolved"
                    else "excluded",
                    receipt={"claim_id": str(cid), "assessment": assessment},
                )
    status = "refused" if error else assessment
    await conn.execute(
        text(
            "INSERT INTO arv2_quality_proposal(operation_id,workspace_id,job_id,"
            "subject_id,proposal_key,request_sha256,claim_id,status,error_code) "
            "VALUES(:id,:ws,:job,:subject,:key,:sha,:claim,:status,:error)"
        ),
        {
            "id": oid,
            "ws": scope.workspace_id,
            "job": scope.job_id,
            "subject": subject,
            "key": key,
            "sha": sha,
            "claim": cid,
            "status": status,
            "error": error,
        },
    )
    return ProposalReceipt(oid, cid, status, error)
