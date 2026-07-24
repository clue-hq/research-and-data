"""C1-C3 integration composition over the shared tool, registry, and governance seams."""

from __future__ import annotations

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.composition import production_binding_classifier
from clue_config.ingestion import DEFAULT_INGESTION_POLICY, IngestionPolicy
from clue_core import (
    Claim,
    ClaimId,
    ContactEntity,
    FieldClass,
    FieldDef,
    IdentityBinding,
    PassKind,
    ReuseScope,
    SourceGate,
    UseClass,
    classify_field_key,
    field_namespace,
    new_run_id,
    revalidate_with,
)
from clue_core.ingestion import IngestionSegmentId
from clue_db import ConnFactory, transaction
from clue_research.adapters import ClaimExtractor, ScrapeBackend
from clue_research.claimstore import WorkspaceScope, claims_by_ids, supersede_claim
from clue_research.compliance import build_tombstone
from clue_research.identity import get_account
from clue_research.ingestion import (
    DocumentAdapterRegistry,
    IngestionEngine,
    IngestionJob,
    IngestionTarget,
)
from clue_research.ingestion.seams import (
    ClaimConstructionRoute,
    ClaimErasureRoute,
    ContactClaimRoute,
    MemoryRoute,
    ProjectStateRoute,
    ProposalSink,
)
from clue_research.profiling.contact.binding import BindingClassifier, BindingInput
from clue_research.profiling.contact.use_class import (
    DEFAULT_USE_CLASS_TAGGER,
    UseClassTagger,
)
from clue_research.proposals import (
    FieldProposalPayload,
    ProposalScope,
    propose_field,
)
from clue_research.resolvers.generic_web import (
    GenericWebPolicy,
    GenericWebTargetLookup,
    register_generic_web_resolver,
)
from clue_research.sources import RegistrySourceManifest, register_source
from clue_storage import SnapshotSink, StorageBackend

_USE_CLASS_RANK = {
    UseClass.PROFESSIONAL_PUBLIC: 0,
    UseClass.PERSONAL_PUBLIC_NON_SENSITIVE: 1,
    UseClass.SENSITIVE: 2,
}


class ProductionIngestionContactClaimRoute:
    """Apply the same binding and use classifiers as the live contact-profile path."""

    def __init__(
        self,
        *,
        binding_classifier: BindingClassifier | None = None,
        use_class_tagger: UseClassTagger = DEFAULT_USE_CLASS_TAGGER,
    ) -> None:
        self._binding_classifier = binding_classifier or production_binding_classifier()
        self._use_class_tagger = use_class_tagger

    async def tag(
        self,
        conn: AsyncConnection,
        *,
        claim: Claim,
        contact: ContactEntity,
        field: FieldDef,
        target: IngestionTarget,
    ) -> Claim | None:
        del target  # caller-supplied binding hints are never authoritative
        account = await get_account(conn, contact.account_entity_id)
        if account is None or account.workspace_id != contact.workspace_id:
            return None
        binding = self._binding_classifier.classify(
            BindingInput(
                contact=contact,
                evidence_span=claim.evidence_span,
                source_url=claim.source_url,
                source_key=claim.source_key or "",
                # A client upload is not a verified personal handle by source prior alone.
                manifest_prior=IdentityBinding.WEAK,
                account_name=account.canonical_name,
                account_aliases=account.aliases,
            )
        )
        if claim.source_tier >= 4 and binding is IdentityBinding.WEAK:
            return None
        inferred_use = self._use_class_tagger.tag(field, claim.value_json, claim.evidence_span)
        declared_use = claim.use_class
        use_class = (
            inferred_use
            if declared_use is None
            else max((declared_use, inferred_use), key=_USE_CLASS_RANK.__getitem__)
        )
        return revalidate_with(
            claim,
            identity_binding=binding,
            use_class=use_class,
        )


class IngestionProposalSink:
    """Route an unmapped C3 target into C2's immutable field-proposal ledger."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def preserve_unmapped(
        self,
        *,
        job: IngestionJob,
        segment_ids: tuple[IngestionSegmentId, ...],
        target: IngestionTarget,
    ) -> str:
        field_class = classify_field_key(target.field_key)
        is_sensitive = target.use_class is UseClass.SENSITIVE
        payload = FieldProposalPayload(
            field_def=FieldDef(
                field_key=target.field_key,
                value_type="str",
                pass_kind=PassKind.DEEP,
                gate="outreach-disabled" if is_sensitive else None,
                # An upload-discovered fact shape is tenant-private until a reviewer explicitly
                # authors a broader replacement proposal. Never infer public reuse from a prompt.
                reuse_scope=ReuseScope.TENANT_PRIVATE,
            ),
            description="Field shape nominated from an unmapped ingestion target",
            pack=field_namespace(target.field_key) if field_class is FieldClass.PACK else None,
            sensitive=is_sensitive,
            rationale="Uploaded material targeted a well-formed field absent from the registry",
            evidence_refs=tuple(str(segment_id) for segment_id in segment_ids),
        )
        scope = ProposalScope(
            workspace_id=job.workspace_id,
            brand_id=job.brand_id,
            product_id=job.product_id,
            project_id=job.project_id,
        )
        async with self._conn_factory() as conn:
            proposal = await propose_field(
                conn,
                scope=scope,
                payload=payload,
                proposed_by_actor=job.created_by_actor,
                proposed_by_ref=f"ingestion:{job.id}",
            )
        return str(proposal.id)


class ProductionIngestionClaimErasureRoute:
    """Tombstone the exact tenant-private claims produced by one erased ingestion job."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def erase_claims(self, *, workspace_id: str, claim_ids: tuple[ClaimId, ...]) -> None:
        if not claim_ids:
            return
        ids = sorted(str(claim_id) for claim_id in claim_ids)
        async with self._conn_factory() as conn:
            # Serialize two erasures of the same job before deciding which original claims remain
            # live. This keeps the append-only tombstone operation idempotent under retries/races.
            lock_stmt = text(
                """
                SELECT id
                FROM claim
                WHERE id IN :ids
                  AND workspace_id = :workspace_id
                  AND reuse_scope = 'tenant_private'
                ORDER BY id
                FOR UPDATE
                """
            ).bindparams(bindparam("ids", expanding=True))
            await conn.execute(lock_stmt, {"ids": ids, "workspace_id": workspace_id})
            targets = await claims_by_ids(
                conn,
                claim_ids,
                scope=WorkspaceScope.private_for_workspace(workspace_id),
                include_superseded=True,
            )
            if len(targets) != len(set(claim_ids)):
                raise ValueError("ingestion claim erasure references an absent or foreign claim")
            run_id = new_run_id()
            for claim_id in sorted(targets, key=str):
                target = targets[claim_id]
                if target.superseded_by is not None:
                    continue
                await supersede_claim(
                    conn,
                    claim_id,
                    build_tombstone(target, run_id=run_id),
                    validate_field=False,
                )


def build_ingestion_engine(
    *,
    storage: StorageBackend,
    extractor: ClaimExtractor,
    claim_erasure_route: ClaimErasureRoute | None = None,
    conn_factory: ConnFactory = transaction,
    policy: IngestionPolicy = DEFAULT_INGESTION_POLICY,
    adapters: DocumentAdapterRegistry | None = None,
    source_gate: SourceGate | None = None,
    proposal_sink: ProposalSink | None = None,
    memory_route: MemoryRoute | None = None,
    project_state_route: ProjectStateRoute | None = None,
    claim_construction_route: ClaimConstructionRoute | None = None,
    contact_claim_route: ContactClaimRoute | None = None,
) -> IngestionEngine:
    """Build C3 fail-closed: extraction, contact governance, and erasure are mandatory.

    C4 may add memory/project/product routes later. C2 proposal routing is live by default now.
    """
    return IngestionEngine(
        storage=storage,
        extractor=extractor,
        policy=policy,
        adapters=adapters,
        conn_factory=conn_factory,
        source_gate=source_gate,
        proposal_sink=proposal_sink or IngestionProposalSink(conn_factory=conn_factory),
        memory_route=memory_route,
        project_state_route=project_state_route,
        claim_construction_route=claim_construction_route,
        claim_erasure_route=claim_erasure_route
        or ProductionIngestionClaimErasureRoute(conn_factory=conn_factory),
        contact_claim_route=contact_claim_route or ProductionIngestionContactClaimRoute(),
    )


async def register_generic_web_wiring(
    conn: AsyncConnection,
    *,
    targets: GenericWebTargetLookup,
    extractor: ClaimExtractor,
    scraper: ScrapeBackend | None = None,
    policy: GenericWebPolicy | None = None,
    snapshots: SnapshotSink | None = None,
) -> RegistrySourceManifest:
    """Bind C2's generic resolver and register its fixed tier-3 manifest as one operation."""
    manifest = register_generic_web_resolver(
        targets=targets,
        extractor=extractor,
        scraper=scraper,
        policy=policy,
        snapshots=snapshots,
    )
    await register_source(conn, manifest)
    return manifest


__all__ = [
    "IngestionProposalSink",
    "ProductionIngestionClaimErasureRoute",
    "ProductionIngestionContactClaimRoute",
    "build_ingestion_engine",
    "register_generic_web_wiring",
]
