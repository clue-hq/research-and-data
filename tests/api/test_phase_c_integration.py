"""C1-C3 integration-owned aggregation and cross-lane composition checks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from clue_api import (
    IngestionProposalSink,
    ProductionIngestionClaimErasureRoute,
    ProductionIngestionContactClaimRoute,
    build_tool_invoker,
    create_projections_app,
    register_generic_web_wiring,
)
from clue_config import load_settings
from clue_core import (
    ClaimDraft,
    Entity,
    EntityType,
    ExtractionMethod,
    FieldDef,
    IdentityBinding,
    NormalizedText,
    RawArtifact,
    ResearchMode,
    ResearchScope,
    ReuseScope,
    UseClass,
    account_claim,
    contact_claim,
    new_entity_id,
    new_run_id,
    revalidate_with,
)
from clue_core.ingestion import (
    IngestionStatus,
    new_ingestion_job_id,
    new_ingestion_segment_id,
)
from clue_core.proposals import FieldProposalId
from clue_projections import field_proposals
from clue_research.claimstore import (
    WorkspaceScope,
    claims_by_ids,
    get_field,
    insert_claim,
)
from clue_research.identity import (
    get_contact,
    insert_account_entity,
    insert_contact_entity,
)
from clue_research.ingestion import (
    DeclaredMaterialContext,
    IngestionJob,
    IngestionTarget,
    MaterialContext,
)
from clue_research.proposals import get_field_proposal
from clue_research.review import ObservabilitySurface
from clue_research.sources import get_source, is_resolver_bound, unbind_resolver
from clue_storage import StorageBackend
from clue_toolbelt import DbIdempotencyStore, ToolRegistry
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn


class _Extractor:
    def extract(
        self, normalized: NormalizedText, entity: Entity, field: FieldDef
    ) -> list[ClaimDraft]:
        return []


class _Targets:
    def target_for(self, entity_id, field_key):
        return None


class _Scraper:
    def scrape(self, ref: str, ctx: object) -> RawArtifact:
        return RawArtifact(ref=ref, media_type="text/markdown", content=b"")


def test_phase_c_routes_are_aggregated_at_the_http_root() -> None:
    settings = load_settings(_env_file=None)
    registry = ToolRegistry()
    idempotency_store = DbIdempotencyStore()
    storage = cast(StorageBackend, object())
    app = create_projections_app(
        surface=cast(ObservabilitySurface, object()),
        tool_invoker=build_tool_invoker(
            registry=registry,
            idempotency_store=idempotency_store,
            storage=storage,
            settings=settings,
        ),
        settings=settings,
        ingestion_storage=storage,
        manage_db_lifespan=False,
    )
    paths = set(app.openapi()["paths"])
    assert {
        "/research_coverage/{run_id}",
        "/research_attempt_history/{run_id}/{entity_id}/{field_key}",
        "/field_proposals",
        "/source_proposals",
        "/ingestion_status/{ingestion_job_id}",
        "/ingestion/uploads",
        "/stage0/recon/{recon_run_id}/brief",
        "/stage0/recon/{recon_run_id}/progress",
        "/stage0/readiness/{readiness_decision_id}",
    } <= paths


def test_ingestion_unmapped_target_routes_into_c2_proposals(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            project = await seed_project(conn, f"ws-phase-c-{uuid4().hex[:8]}")
            now = datetime.now(UTC)
            job = IngestionJob(
                id=new_ingestion_job_id(),
                workspace_id=project.workspace_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
                artifact_key=f"{project.workspace_id}/artifact",
                content_sha256="a" * 64,
                declared_context=DeclaredMaterialContext(
                    brand_id=project.brand_id,
                    project_id=project.project_id,
                ),
                declared_context_hash="b" * 64,
                media_type="text/plain",
                adapter_key="text",
                status=IngestionStatus.EXTRACTING,
                created_by_actor="agent",
                created_at=now,
                updated_at=now,
            )
            sink = IngestionProposalSink(conn_factory=conn_session_factory(conn))
            proposal_id = await sink.preserve_unmapped(
                job=job,
                segment_ids=(new_ingestion_segment_id(),),
                target=IngestionTarget(
                    entity_id=new_entity_id(),
                    entity_type="account",
                    field_key="account.upload_discovered_signal",
                    material_context=MaterialContext.CLIENT_ABOUT_TARGET,
                ),
            )
            cards = await field_proposals(
                conn_factory=conn_session_factory(conn),
                workspace_id=project.workspace_id,
            )
            assert [card.field_proposal_id for card in cards] == [proposal_id]
            assert cards[0].field_key == "account.upload_discovered_signal"
            assert cards[0].proposed_by_actor == "agent"

    run_async(scenario())


def test_ingestion_unmapped_pack_target_declares_a_species(
    require_profiling_db: None,
) -> None:
    """FI-2 P3: a ``<pack>.*`` field must declare a ``research_scope`` at *authoring*, so this sink
    has to stamp one — otherwise an unmapped vertical target raises out of the ingestion engine
    instead of being preserved as a reviewable proposal."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            project = await seed_project(conn, f"ws-phase-c-pack-{uuid4().hex[:8]}")
            now = datetime.now(UTC)
            job = IngestionJob(
                id=new_ingestion_job_id(),
                workspace_id=project.workspace_id,
                brand_id=project.brand_id,
                project_id=project.project_id,
                artifact_key=f"{project.workspace_id}/artifact",
                content_sha256="c" * 64,
                declared_context=DeclaredMaterialContext(
                    brand_id=project.brand_id,
                    project_id=project.project_id,
                ),
                declared_context_hash="d" * 64,
                media_type="text/plain",
                adapter_key="text",
                status=IngestionStatus.EXTRACTING,
                created_by_actor="agent",
                created_at=now,
                updated_at=now,
            )
            sink = IngestionProposalSink(conn_factory=conn_session_factory(conn))
            proposal_id = await sink.preserve_unmapped(
                job=job,
                segment_ids=(new_ingestion_segment_id(),),
                target=IngestionTarget(
                    entity_id=new_entity_id(),
                    entity_type="account",
                    field_key="new_vertical.upload_discovered_signal",
                    material_context=MaterialContext.CLIENT_ABOUT_TARGET,
                ),
            )
            stored = await get_field_proposal(
                conn,
                FieldProposalId(UUID(proposal_id)),
                workspace_id=project.workspace_id,
            )
            assert stored is not None
            assert stored.payload.pack == "new_vertical"
            # Neutral is the safe species (a wrong neutral costs a skipped re-spend, never a leak);
            # a reviewer widens it deliberately, exactly as with the tenant-private reuse stamp.
            assert stored.payload.field_def.research_scope is ResearchScope.PROJECT_NEUTRAL

    run_async(scenario())


def test_generic_web_manifest_and_resolver_bind_together(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            try:
                manifest = await register_generic_web_wiring(
                    conn,
                    targets=_Targets(),
                    extractor=_Extractor(),
                    scraper=_Scraper(),
                )
                stored = await get_source(conn, manifest.source_key)
                assert stored is not None
                assert stored.tier == 3
                assert is_resolver_bound(manifest.source_key)
            finally:
                unbind_resolver("generic_web")

    run_async(scenario())


def test_ingestion_contact_route_ignores_caller_binding_hint(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            project = await seed_project(conn, f"ws-phase-c-contact-{uuid4().hex[:8]}")
            account_id = await insert_account_entity(
                conn,
                canonical_name="Acme",
                primary_domain="acme.example",
                workspace_id=project.workspace_id,
            )
            contact_id = await insert_contact_entity(
                conn,
                account_entity_id=account_id,
                full_name="Ada Example",
                linkedin_url="https://linkedin.com/in/ada-example",
            )
            contact = await get_contact(conn, contact_id)
            field = await get_field(conn, "contact.facet.recent_post")
            assert contact is not None
            assert field is not None
            target = IngestionTarget(
                entity_id=contact_id,
                entity_type=EntityType.CONTACT,
                field_key=field.field_key,
                material_context=MaterialContext.CLIENT_ABOUT_TARGET,
                use_class=UseClass.PROFESSIONAL_PUBLIC,
                manifest_identity_binding=IdentityBinding.STRONG,
            )
            untrusted_hint = revalidate_with(
                contact_claim(
                    entity_id=contact_id,
                    field_key=str(field.field_key),
                    value_json="A public post",
                    source_tier=3,
                    extraction_method=ExtractionMethod.HUMAN,
                    confidence=0.9,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.CONTACT_PROFILING,
                    identity_binding=IdentityBinding.STRONG,
                    use_class=UseClass.PROFESSIONAL_PUBLIC,
                    source_url="ingestion://job/segment",
                    evidence_span="Ada Example published a public post.",
                ),
                source_key="client_upload",
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=project.workspace_id,
            )
            governed = await ProductionIngestionContactClaimRoute().tag(
                conn,
                claim=untrusted_hint,
                contact=contact,
                field=field,
                target=target,
            )
            assert governed is not None
            assert governed.identity_binding is IdentityBinding.WEAK
            assert governed.use_class is UseClass.PROFESSIONAL_PUBLIC

    run_async(scenario())


def test_ingestion_erasure_tombstones_exact_workspace_claims_idempotently(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            project = await seed_project(conn, f"ws-phase-c-erase-{uuid4().hex[:8]}")
            account_id = await insert_account_entity(
                conn,
                canonical_name="Acme",
                primary_domain="acme.example",
                workspace_id=project.workspace_id,
            )
            claim = revalidate_with(
                account_claim(
                    entity_id=account_id,
                    field_key="core.primary_domain",
                    value_json="acme.example",
                    source_tier=1,
                    extraction_method=ExtractionMethod.HUMAN,
                    confidence=1,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    source_url="ingestion://job/segment",
                    evidence_span="acme.example",
                ),
                source_key="client_upload",
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=project.workspace_id,
            )
            claim_id = await insert_claim(conn, claim)
            route = ProductionIngestionClaimErasureRoute(conn_factory=conn_session_factory(conn))
            await route.erase_claims(
                workspace_id=project.workspace_id,
                claim_ids=(claim_id,),
            )
            await route.erase_claims(
                workspace_id=project.workspace_id,
                claim_ids=(claim_id,),
            )
            scope = WorkspaceScope.private_for_workspace(project.workspace_id)
            assert await claims_by_ids(conn, (claim_id,), scope=scope) == {}
            history = await claims_by_ids(
                conn,
                (claim_id,),
                scope=scope,
                include_superseded=True,
            )
            assert history[claim_id].superseded_by is not None
            tombstones = await claims_by_ids(
                conn,
                (history[claim_id].superseded_by,),
                scope=scope,
            )
            tombstone = tombstones[history[claim_id].superseded_by]
            assert tombstone.value_json == {"__erased__": True}

    run_async(scenario())
