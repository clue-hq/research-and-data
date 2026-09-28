"""The lenient claim write gate (master plan §2 principle 2, §4).

Rule: storing information is never blocked. The gate stamps what the writer did not say (tier from
the method, tenant-private scope, facet governance defaults), stores a schema miss with
``schema_valid=false``, registers an unknown key as a proposed field, and stores a research claim
with no source URL under a ``source_missing`` marker. With ``lenient=False`` every one of those is
the strict refusal the claim store already implements.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimFlavor,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldClass,
    FieldDef,
    IdentityBinding,
    OperationId,
    PassKind,
    ResearchMode,
    ResearchScope,
    ResearchSubjectRef,
    ResearchSupportRef,
    ReuseScope,
    RunId,
    UseClass,
    classify_field_key,
    field_namespace,
)
from clue_research.claimstore.claims import insert_claim
from clue_research.claimstore.registry import (
    UnknownFieldError,
    ValueSchemaError,
    check_claim_writable,
    register_field,
)

#: Appendix A / master plan §4: the tier is stamped from the tool of origin, never chosen.
TIER_FOR_METHOD: dict[ExtractionMethod, int] = {
    ExtractionMethod.API: 1,
    ExtractionMethod.CRM_IMPORT: 1,
    ExtractionMethod.HUMAN: 1,
    ExtractionMethod.SCRAPE: 2,
    ExtractionMethod.LLM_SYNTHESIS: 4,
}

_URL_REQUIRED = frozenset(
    {ExtractionMethod.API, ExtractionMethod.SCRAPE, ExtractionMethod.LLM_SYNTHESIS}
)
_PROPOSED_DESCRIPTION = "Proposed field (unregistered key written in lenient mode)"


@dataclass(frozen=True)
class ClaimDraft:
    """What a writer knows about one fact; the gate fills in everything it did not say."""

    entity_id: EntityId
    entity_type: EntityType
    field_key: str
    value_json: JsonValue
    extraction_method: ExtractionMethod
    run_id: RunId
    research_mode: ResearchMode
    workspace_id: str
    source_url: str | None = None
    source_key: str | None = None
    evidence_span: str | None = None
    observed_at: datetime | None = None
    confidence: float = 0.5
    identity_binding: IdentityBinding | None = None
    use_class: UseClass | None = None
    signal_priority: int = 3
    outreach_safe: bool = True
    artifact_key: str | None = None
    product_id: str | None = None
    field_description: str | None = None
    markers: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class WriteReceipt:
    """What the gate did: the claim it stored, what it had to stamp, whether it registered a key."""

    claim_id: ClaimId
    field_key: str
    markers: dict[str, JsonValue]
    registered_field: bool


@dataclass(frozen=True)
class DerivedClaimInput:
    """Support lineage consumed by the shared derivation store, not copied into a quotation."""

    target: ResearchSubjectRef
    supports: tuple[ResearchSupportRef, ...]
    operation_id: OperationId


class LenientClaimWriter:
    """The one write path into the claim store for the ARV2 lane.

    ``lenient=True`` is the research posture: everything observed is stored, and what the store
    would have refused becomes a durable ``write_markers`` annotation instead. ``lenient=False``
    restores the substrate's own refusals so a caller that wants the strict contract still gets it.
    """

    def __init__(self, *, lenient: bool, scoped_proposals: bool = False) -> None:
        self._lenient = lenient
        self._scoped_proposals = scoped_proposals

    async def write(
        self,
        conn: AsyncConnection,
        draft: ClaimDraft,
        *,
        derivation: DerivedClaimInput | None = None,
        claim_id: ClaimId | None = None,
    ) -> WriteReceipt:
        if draft.entity_type is EntityType.CONTACT:
            from sqlalchemy import text

            # Same authority lock as the shared privacy controller; a late write must serialize
            # behind its stop before deciding whether this run still owns the subject.
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"contact-research:{draft.workspace_id}:{draft.entity_id}"},
            )
            blocked = (
                await conn.execute(
                    text("""
                SELECT EXISTS(SELECT 1 FROM arv2_research_job WHERE run_id=:run
                  AND workspace_id=:ws AND subject_entity_id=:contact AND profile_ref IN
        ('agent-profile:arv2-person:v2','agent-profile:arv2-person:v3')
                  AND ((input_refs->>'privacy_stopped')::boolean IS TRUE
                       OR COALESCE(input_refs->'blocked_channels','[]'::jsonb) ? :field))
            """),
                    {
                        "run": draft.run_id,
                        "ws": draft.workspace_id,
                        "contact": draft.entity_id,
                        "field": draft.field_key,
                    },
                )
            ).scalar_one()
            if blocked:
                raise ValueError("research authority was withdrawn for this subject")
        if draft.artifact_key and draft.markers.get("provider_subject_id"):
            from clue_research.identity.provider import lock_provider_evidence

            await lock_provider_evidence(
                conn,
                workspace_id=draft.workspace_id,
                provider="ai_ark",
                subject_id=str(draft.markers["provider_subject_id"]),
                artifact_key=draft.artifact_key,
            )
        if draft.markers.get("media"):
            from sqlalchemy import text

            media = draft.markers["media"]
            if not isinstance(media, dict):
                raise ValueError("invalid media provenance")
            available = (
                await conn.execute(
                    text("""
                SELECT EXISTS(SELECT 1 FROM arv2_media_transcript t
                  JOIN arv2_media_item i USING(workspace_id,item_id)
                  JOIN artifact a ON a.storage_key=t.text_key AND a.workspace_id=t.workspace_id
                  WHERE t.workspace_id=:ws AND t.version_id=CAST(:version AS uuid)
                    AND t.text_key=:key AND i.erased_at IS NULL AND a.erased_at IS NULL
                    AND t.expires_at>now() AND i.expires_at>now()
                    AND (a.expires_at IS NULL OR a.expires_at>now()))
            """),
                    {
                        "ws": draft.workspace_id,
                        "version": media.get("version_ref"),
                        "key": draft.artifact_key,
                    },
                )
            ).scalar_one()
            if not available:
                raise ValueError("media evidence unavailable")
            locked = await conn.execute(
                text(
                    "SELECT storage_key FROM artifact WHERE workspace_id=:ws AND "
                    "storage_key=:key AND erased_at IS NULL AND "
                    "(expires_at IS NULL OR expires_at>now()) FOR UPDATE"
                ),
                {"ws": draft.workspace_id, "key": draft.artifact_key},
            )
            if locked.scalar_one_or_none() is None:
                raise ValueError("media evidence became unavailable before claim write")
        markers: dict[str, JsonValue] = dict(draft.markers)
        registered = False

        binding, use_class = draft.identity_binding, draft.use_class
        if (
            draft.entity_type is EntityType.CONTACT
            and classify_field_key(draft.field_key) is FieldClass.CONTACT_FACET
        ):
            if binding is None:
                binding, markers["identity_binding_defaulted"] = IdentityBinding.WEAK, True
            if use_class is None:
                use_class, markers["use_class_defaulted"] = UseClass.PROFESSIONAL_PUBLIC, True

        if draft.extraction_method in _URL_REQUIRED and not draft.source_url:
            if not self._lenient:
                raise ValueError(
                    f"extraction_method {draft.extraction_method} requires a source_url "
                    "(strict mode)"
                )
            markers["source_missing"] = True

        async def gate() -> None:
            # Decision 9: every ARV2 claim is tenant-private, scoped to the workspace that
            # bought it — so that is the scope the registry gate is asked about too.
            await check_claim_writable(
                conn,
                field_key=draft.field_key,
                value_json=draft.value_json,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=draft.workspace_id,
                product_id=draft.product_id,
            )

        try:
            await gate()
        except UnknownFieldError:
            if not self._lenient:
                raise
            if self._scoped_proposals:
                from clue_research.claimstore.registry import register_agent_research_field

                await register_agent_research_field(
                    conn,
                    workspace_id=draft.workspace_id,
                    field_key=draft.field_key,
                    run_id=str(draft.run_id),
                )
            else:
                await _register_proposed_field(conn, draft)
            registered, markers["proposed_field"] = True, True
            await gate()
        except ValueSchemaError:
            if not self._lenient:
                raise
            markers["schema_valid"] = False

        claim = Claim(
            entity_id=draft.entity_id,
            entity_type=draft.entity_type,
            field_key=draft.field_key,
            value_json=draft.value_json,
            source_url=None if derivation else draft.source_url,
            source_key=draft.source_key,
            artifact_key=draft.artifact_key,
            source_tier=TIER_FOR_METHOD[draft.extraction_method],
            extraction_method=draft.extraction_method,
            evidence_span=None if derivation else draft.evidence_span,
            confidence=draft.confidence,
            observed_at=draft.observed_at,
            run_id=draft.run_id,
            research_mode=draft.research_mode,
            identity_binding=binding,
            use_class=use_class,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
            workspace_id=draft.workspace_id,
            product_id=draft.product_id,
            signal_priority=draft.signal_priority,
            outreach_safe=draft.outreach_safe,
            write_markers=markers or None,
            claim_flavor=ClaimFlavor.DERIVED if derivation else ClaimFlavor.FIELD_CLAIM,
        )
        if claim_id is not None:
            claim = claim.model_copy(update={"id": claim_id})
        if derivation:
            from clue_research.claimstore import DerivationStore, WorkspaceScope

            stored = await DerivationStore().create(
                conn,
                claim,
                derivation.target,
                derivation.supports,
                workspace_id=draft.workspace_id,
                operation_id=derivation.operation_id,
                scope=WorkspaceScope.for_workspace(draft.workspace_id),
            )
            claim_id = stored.derived_claim_id
        else:
            claim_id = await insert_claim(conn, claim, validate_field=False)
        return WriteReceipt(
            claim_id=claim_id,
            field_key=draft.field_key,
            markers=markers,
            registered_field=registered,
        )


async def _register_proposed_field(conn: AsyncConnection, draft: ClaimDraft) -> None:
    """Master plan §4: an unregistered key is stored and auto-registered as a proposed field."""
    is_pack = classify_field_key(draft.field_key) is FieldClass.PACK
    field_def = FieldDef(
        field_key=draft.field_key,
        value_type="json",
        validation=None,
        tier_plan=(),
        freshness_ttl=None,
        pass_kind=PassKind.DEEP,
        gate=None,
        # A ``<pack>.*`` field has no safe species or reuse default, and the claim-write boundary is
        # fail-closed on both — so a proposed pack field declares them. Decision 9 makes the reuse
        # answer obvious: every ARV2 claim is tenant-private anyway. A canonical key keeps its
        # class defaults.
        research_scope=ResearchScope.PROJECT_NEUTRAL if is_pack else None,
        reuse_scope=ReuseScope.TENANT_PRIVATE if is_pack else None,
    )
    await register_field(
        conn,
        field_def,
        value_schema=None,
        description=draft.field_description or _PROPOSED_DESCRIPTION,
        pack=field_namespace(draft.field_key) if is_pack else None,
    )
