"""Typed specialist proposals: resolve originals, validate shape, then assess the stored claim."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Generic, Literal, TypeVar
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import ALWAYS_UNSAFE_FIELDS, JobScope
from clue_api.arv2.claim_writer import ClaimDraft, DerivedClaimInput, LenientClaimWriter
from clue_api.arv2.quality_context import read_context, read_document
from clue_api.arv2.quality_evidence import (
    EvidenceGrant,
    EvidenceUnavailable,
    JsonSupport,
    SourceRef,
    TextSupport,
    authorize_grant,
    record_disposition,
    resolve_source,
    validate_support,
)
from clue_api.arv2.quality_media import TranscriptSupport, validate_transcript
from clue_api.arv2.quality_policy import advisory_research
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


SupportT = TypeVar("SupportT")


class _ProposalBase(BaseModel, Generic[SupportT]):  # noqa: UP046 -- keep pinned tool schema names
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_key: str = Field(min_length=1, max_length=200)
    field_key: str = Field(min_length=1, max_length=200)
    field_version: int | None = Field(default=None, ge=1)
    value: JsonValue
    claim_kind: Literal["observation", "attributed_statement", "inference"] = "observation"
    support: tuple[SupportT, ...] = Field(min_length=1, max_length=30)
    assessment: SemanticAssessment
    identity_binding: IdentityBinding | None = None
    use_class: UseClass | None = None
    outreach_safe: bool = True


class ClaimProposal(
    _ProposalBase[Annotated[TextSupport | JsonSupport | ClaimSupport, Field(discriminator="kind")]]
):
    pass


class TranscriptProposal(_ProposalBase[TranscriptSupport]):
    pass


class SourceSupport(BaseModel):
    """A source reference, without requiring the model to prove offsets or field semantics."""

    kind: Literal["source"] = "source"
    source_id: UUID


class FindingProposal(_ProposalBase[SourceSupport]):
    support: tuple[SourceSupport, ...] = ()


class SellerDocumentSupport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["seller_document"] = "seller_document"
    document_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=8000)


class NarrativeProposal(
    _ProposalBase[Annotated[ClaimSupport | SellerDocumentSupport, Field(discriminator="kind")]]
):
    pass


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
    proposal: ClaimProposal | NarrativeProposal | TranscriptProposal | FindingProposal,
    *,
    context_id: UUID,
    actor_ref: str,
    purge_unevidenced: bool = True,
    claim_id: UUID | None = None,
) -> ProposalReceipt:
    subject = scope.person_subject_id or scope.account_id
    advisory = advisory_research(scope)
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
        if claim_id is not None and old["claim_id"] != claim_id:
            raise ValueError("Proposal replay does not match its allocated claim ID")
        return ProposalReceipt(oid, old["claim_id"], old["status"], old["error_code"], True)
    refs: list[SourceRef] = []
    support_keys: set[str] = set()
    supporting: dict[UUID, ResearchSupportRole] = {}
    inherited_safe = True
    inherited_class = proposal.use_class
    inherited_binding = proposal.identity_binding
    media_markers: list[dict[str, JsonValue]] = []
    qualifications = list(proposal.assessment.qualifications)
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
    if (
        not advisory
        and proposal.field_key not in allowed_keys
        and (field is not None or not proposal.field_key.startswith(prefix))
    ):
        error = "field_subject_mismatch"
    if (
        not advisory
        and field is not None
        and proposal.field_version not in (None, field.definition_version)
    ):
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
    if (
        not advisory
        and catalog_pin is not None
        and (
            field is None
            or catalog_pin.version != field.definition_version
            or catalog_pin.value_type != field.field_def.value_type
            or catalog_pin.validation != field.field_def.validation
            or catalog_pin.value_schema != field.value_schema
            or catalog_pin.description != field.description
        )
    ):
        error = "field_definition_changed"
    if proposal.field_key == "account.value_narrative" and (
        not isinstance(proposal, NarrativeProposal)
        or proposal.claim_kind != "inference"
        or not any(isinstance(s, SellerDocumentSupport) for s in proposal.support)
        or not any(isinstance(s, ClaimSupport) for s in proposal.support)
    ):
        error = "narrative_requires_both_sides"
    if isinstance(proposal, NarrativeProposal):
        run_pin = (
            await conn.execute(
                text("SELECT icp_key,icp_version FROM arv2_research_run WHERE run_id=:run"),
                {"run": scope.run_id},
            )
        ).one()
        value = proposal.value
        if not isinstance(value, dict) or (
            value.get("project_id") != scope.project_id
            or value.get("context_id") != str(context_id)
            or value.get("icp_key") != run_pin.icp_key
            or value.get("icp_spec_version") != run_pin.icp_version
            or value.get("product_ids") != [str(p) for p in sorted(context.products)]
        ):
            error = "narrative_context_mismatch"
    relationship = None
    try:
        relationship = (
            None
            if advisory
            else await validate_relationship(
                conn,
                workspace_id=scope.workspace_id,
                account_id=scope.account_id,
                contact_id=scope.person_subject_id,
                context_id=context_id,
                field_key=proposal.field_key,
                value=proposal.value,
                support_claim_ids={
                    cid
                    for s in proposal.support
                    if isinstance(s, ClaimSupport)
                    for cid in s.claim_ids
                },
            )
        )
    except ValueError:
        error = "relationship_assessment_invalid"
    try:
        for support in proposal.support:
            if isinstance(support, SourceSupport):
                if not advisory:
                    raise EvidenceUnavailable("source findings require research revision six")
                ref = await resolve_source(conn, grant, support.source_id)
                await read_verified_artifact(
                    conn, storage, workspace_id=scope.workspace_id, storage_key=ref.artifact_key
                )
                refs.append(ref)
                support_keys.update(k for k in (ref.artifact_key, ref.original_key) if k)
            elif isinstance(support, ClaimSupport):
                if proposal.claim_kind != "inference":
                    raise EvidenceUnavailable(
                        "claim references require an explicitly labelled inference"
                    )
                if sum(isinstance(s, ClaimSupport) for s in proposal.support) != 1 or (
                    isinstance(proposal, ClaimProposal) and len(proposal.support) != 1
                ):
                    raise EvidenceUnavailable("use one complete claim support set for an inference")
                claims = await claims_by_ids(
                    conn,
                    [ClaimId(cid) for cid in support.claim_ids],
                    scope=WorkspaceScope.for_workspace(scope.workspace_id),
                )
                if len(claims) != len(set(support.claim_ids)):
                    raise EvidenceUnavailable("supporting claim is no longer applicable")
                for claim in claims.values():
                    inherited_safe = inherited_safe and claim.outreach_safe
                    if claim.entity_type is EntityType.CONTACT:
                        # Moving personal evidence into an account argument must not strip
                        # its use restrictions. Account summaries have no personal-use gate.
                        if scope.subject_kind != "person" and (
                            claim.use_class is not UseClass.PROFESSIONAL_PUBLIC
                            or claim.identity_binding is not IdentityBinding.STRONG
                        ):
                            raise EvidenceUnavailable(
                                "personal support cannot become account truth"
                            )
                        ranks = {
                            None: -1,
                            UseClass.PROFESSIONAL_PUBLIC: 0,
                            UseClass.PERSONAL_PUBLIC_NON_SENSITIVE: 1,
                            UseClass.SENSITIVE: 2,
                        }
                        if claim.use_class is None:
                            raise EvidenceUnavailable("personal support lacks a use classification")
                        if ranks[claim.use_class] > ranks[inherited_class]:
                            inherited_class = claim.use_class
                        if claim.identity_binding is not IdentityBinding.STRONG:
                            inherited_binding = IdentityBinding.WEAK
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
            elif isinstance(support, TranscriptSupport):
                if proposal.claim_kind != "attributed_statement" or len(proposal.support) != 1:
                    raise EvidenceUnavailable(
                        "a transcript establishes a single attributed statement"
                    )
                ref, media, warnings = await validate_transcript(
                    conn, storage, grant, scope, support
                )
                refs.append(ref)
                support_keys.update((ref.artifact_key, str(media["segments_key"])))
                media_markers.append(media)
                qualifications.extend(warnings)
                if warnings and assessment == "supported":
                    assessment = "qualified"
                inherited_safe = inherited_safe and not warnings
            elif isinstance(support, SellerDocumentSupport):
                if (
                    not isinstance(proposal, NarrativeProposal)
                    or proposal.field_key != "account.value_narrative"
                ):
                    raise EvidenceUnavailable("seller support belongs only to value arguments")
                pin = next(
                    (p for p in context.seller_documents if p.document_id == support.document_id),
                    None,
                )
                if pin is None or pin.sha256 != support.sha256:
                    raise EvidenceUnavailable(
                        "seller document is not in the selected project context"
                    )
                original = await read_document(
                    conn, storage, workspace_id=scope.workspace_id, pin=pin
                )
                if (
                    support.end <= support.start
                    or support.end > len(original)
                    or original[support.start : support.end] != support.quote
                ):
                    raise EvidenceUnavailable("seller passage does not match its pinned original")
                support_keys.add(pin.artifact_key)
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
            if not advisory:
                error = "value_schema_invalid"
            else:
                qualifications.append("Stored as reported; catalog value shape was not enforced.")
    if not error:
        provider = (
            actor_ref == "deterministic-provider-mapping:v1"
            and bool(refs)
            and all(r.kind == "provider_record" for r in refs)
            and proposal.claim_kind == "observation"
        )
        method = ExtractionMethod.API if provider else ExtractionMethod.LLM_SYNTHESIS
        first = refs[0] if refs else None
        quotes = [
            s.quote for s in proposal.support if isinstance(s, (TextSupport, TranscriptSupport))
        ]
        markers: dict[str, JsonValue] = {
            "quality_required": True,
            "claim_kind": proposal.claim_kind,
            "support": [s.model_dump(mode="json") for s in proposal.support],
            "qualifications": [str(q) for q in qualifications],
            "proposal_ref": str(oid),
            "context_id": str(context_id),
            "quality_advisory": advisory,
        }
        if media_markers:
            markers["media"] = media_markers[0]
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
            identity_binding=inherited_binding,
            use_class=inherited_class,
            outreach_safe=proposal.outreach_safe
            and inherited_safe
            and assessment == "supported"
            and proposal.field_key not in ALWAYS_UNSAFE_FIELDS
            and (
                not isinstance(relationship, CommitteeAssessment)
                or relationship.state == "supported"
            ),
            markers=markers,
        )
        if scope.subject_kind == "person" and not advisory:
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
                conn,
                draft,
                derivation=derivation,
                claim_id=ClaimId(claim_id) if claim_id is not None else None,
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
                support_artifacts=tuple(sorted(support_keys or ({key} if advisory else set()))),
                context_id=context_id,
            )
            if isinstance(proposal, NarrativeProposal):
                from clue_research.narrative.support import write_claim_support

                await write_claim_support(
                    conn,
                    ClaimId(cid),
                    account_evidence_ids=[ClaimId(id) for id in supporting],
                    client_knowledge_ids=[
                        f"document:{s.document_id}@{s.sha256}:{s.start}:{s.end}"
                        for s in proposal.support
                        if isinstance(s, SellerDocumentSupport)
                    ],
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
