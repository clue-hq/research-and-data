"""S3 acceptance for the production brand/Client-KB/project-context composition path."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import (
    AgentProfile,
    AgentResourceRef,
    AgentRole,
    AgentTurnRequest,
    ArtifactRef,
    ContextAssemblyPolicy,
    ContextAssemblyReceipt,
    ContextCandidate,
    ContextLayer,
    ContextLayerSource,
    DeterministicAgentContextAssembler,
    DomainObjectRef,
    LayerBudget,
    ModelPolicy,
    ProjectContextArtifact,
    ProjectLayerSource,
    ResourceKind,
    WorkspacePolicy,
    WorkspaceProductLayerSource,
)
from clue_agents.ports import HistoryMessageRef
from clue_api.account_research_turn_wiring import DbCompiledContextCardReader
from clue_api.agent_turn_fleet_wiring import (
    ProjectConversationTurnRunner,
    _ProjectScope,
    project_conversation_card_payload,
)
from clue_api.agent_turn_submission import AgentTurnSubmissionRow
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.brand_knowledge_context import (
    BrandKnowledgeIndexCard,
    KnowledgeDocumentRef,
    PinnedDocument,
    confirmed_icp_for_project,
)
from clue_api.client_context_binding import bind_workspace_client
from clue_core import EntityId, ExecutionId, OnboardingInputId, OnboardingInputKind
from clue_db import ConnFactory
from clue_projections import ProjectConversationCard
from clue_research.stage0 import (
    CLIENT_KNOWLEDGE_FIELDS,
    PRODUCT_KNOWLEDGE_FIELDS,
    ClientInput,
    StatementRoute,
    VolunteeredMaterial,
    record_statement,
    reverse_profile,
    submit_onboarding_input,
)
from clue_spine import Brand, Product, Project, create_brand, create_product, create_project
from clue_storage import ArtifactNotFound, FsStorage
from tests._workspace import seed_workspace
from tests.agents.conftest import constitution
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
_SHA = "a" * 64


def _pinned_document(
    *,
    path: str,
    kind: str,
    version: int,
    status: str,
    body: str,
) -> PinnedDocument:
    """One pinned knowledge document, built without the durable row the pin normally holds.

    Composition takes the pinned documents as an argument, so the compile path is exercisable
    without re-seeding onboarding here; the pin/read/verify half is covered by
    ``tests/api/test_brand_knowledge_context_db.py`` and end to end by
    ``tests/api/test_o6_conversation_composition_db.py``.
    """

    front, rest = parse_front_matter(body)
    return PinnedDocument(
        ref=KnowledgeDocumentRef(
            document_id=uuid4(),
            path=path,
            kind=kind,
            version=version,
            status=status,
            artifact_key=f"knowledge/{path}",
            artifact_sha256=hashlib.sha256(body.encode()).hexdigest(),
            updated_at=_NOW,
        ),
        body=body.encode(),
        front_matter=front,
        body_text=rest,
    )


def _pinned_documents(*, project_id: str) -> tuple[PinnedDocument, ...]:
    """A brand's overview plus the ICP a human confirmed for ``project_id``."""

    return (
        _pinned_document(
            path="company/overview.md",
            kind="company-overview",
            version=1,
            status="ready",
            body=(
                "---\nkind: company-overview\n---\n\n"
                "Acme builds scheduling software for gastroenterology clinics.\n"
            ),
        ),
        _pinned_document(
            path="audience/icp-gi-groups.md",
            kind="icp-definition",
            version=2,
            status="confirmed",
            body=(
                "---\nkind: icp-definition\nicp_key: gi-groups\nstatus: confirmed\n"
                f"confirmed_for_project_id: {project_id}\n---\n\n"
                "Independent GI groups with three to twelve physicians.\n"
            ),
        ),
    )


def _icp_document_id(documents: tuple[PinnedDocument, ...]) -> UUID:
    """The ICP document id a project would have pinned when it confirmed this set."""

    return next(
        document.ref.document_id for document in documents if document.ref.kind == "icp-definition"
    )


def _profile() -> AgentProfile:
    return AgentProfile(
        name="head-of-abm",
        version="1.0.0",
        role=AgentRole.HEAD_OF_ABM,
        prompt=AgentResourceRef(
            kind=ResourceKind.PROMPT,
            name="head-of-abm",
            version="1.0.0",
            sha256=_SHA,
        ),
        skills=(),
        tools=(),
        model=ModelPolicy(
            model_id="test/context",
            timeout_s=30,
            max_retries=0,
            max_output_tokens=1_024,
            temperature=0,
        ),
        workspace=WorkspacePolicy(
            max_total_bytes=100_000,
            max_file_bytes=100_000,
            max_file_count=20,
            allowed_extensions=(".json", ".md", ".txt"),
            readable_prefixes=("context", "inputs"),
            writable_prefixes=(),
            retention_class="agent-turn-standard",
        ),
        delegation_roles=(),
        max_delegation_depth=0,
        max_delegations=0,
        max_plan_nodes=1,
    )


@dataclass(frozen=True, slots=True)
class _Seeded:
    workspace_id: str
    brand: Brand
    product: Product
    project_a: Project
    project_b: Project
    client_entity_id: EntityId
    client_kb_version: int
    product_kb_version: int


@dataclass(frozen=True, slots=True)
class _StaticLayer:
    layer: ContextLayer
    candidates: tuple[ContextCandidate, ...] = ()

    async def load(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> Sequence[ContextCandidate]:
        del request, profile, history
        return self.candidates


class _Receipts:
    def __init__(self) -> None:
        self.values: list[ContextAssemblyReceipt] = []

    async def record(
        self,
        *,
        request: AgentTurnRequest,
        receipt: ContextAssemblyReceipt,
    ) -> None:
        del request
        self.values.append(receipt)


def _submission(*, workspace_id: str, project_id: str, suffix: str) -> AgentTurnSubmissionRow:
    return AgentTurnSubmissionRow(
        turn_id=uuid4(),
        workspace_id=workspace_id,
        project_id=project_id,
        thread_id=f"thread-{suffix}",
        submitted_by_user_id="user-s3",
        submitted_via_membership_id="membership-s3",
        onboarding_input_id=OnboardingInputId(uuid4()),
        message_artifact_key=f"{workspace_id}/{'0' * 64}",
        message_sha256="0" * 64,
        idempotency_key=f"s3-{suffix}",
        agent_profile_id=None,
        previous_turn_outcome=None,
        requested_at=_NOW,
    )


async def _seed_post_recon(conn: AsyncConnection, *, suffix: str) -> _Seeded:
    workspace_id = f"production-context-s3-{suffix}"
    await seed_workspace(conn, workspace_id)
    brand = await create_brand(
        conn,
        workspace_id=workspace_id,
        name="Production Context Brand",
    )
    product = await create_product(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        name="Confirmed Product",
        aliases=("Product Alias",),
    )
    project_a = await create_project(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        name="Project A",
    )
    project_b = await create_project(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        name="Project B",
    )
    profiled = await reverse_profile(
        conn,
        ClientInput(
            name="Production Context Customer",
            website=f"https://{suffix}.example",
            materials=(
                VolunteeredMaterial(
                    kind="onboarding",
                    label="grounded onboarding facts",
                    content="Facts supplied during production onboarding.",
                    asserted_fields={key: f"v1 grounded {key}" for key in CLIENT_KNOWLEDGE_FIELDS},
                ),
            ),
        ),
        workspace_id=workspace_id,
        product_id=None,
        budget_cap_cents=Decimal(0),
        max_source_tier=0,
    )
    # Product-scoped knowledge has an independent version sequence. Advance it past the shared
    # onboarding KB so the acceptance proves production composition does not select a product
    # marker merely because this project has that product confirmed.
    product_profile = profiled
    for product_revision in (1, 2):
        product_profile = await reverse_profile(
            conn,
            ClientInput(
                name="Production Context Customer",
                website=f"https://{suffix}.example",
                materials=(
                    VolunteeredMaterial(
                        kind="product_context",
                        label=f"product facts v{product_revision}",
                        content="Product-scoped facts must not replace account context.",
                        asserted_fields={
                            key: (
                                f"product v{product_revision} {key}"
                                if key
                                in {
                                    "client.product_overview",
                                    "client.product_differentiator",
                                    "client.product_positioning",
                                }
                                else {"summary": f"product v{product_revision} {key}"}
                            )
                            for key in PRODUCT_KNOWLEDGE_FIELDS
                        },
                    ),
                ),
            ),
            workspace_id=workspace_id,
            product_id=product.product_id,
            knowledge_scope="product",
            budget_cap_cents=Decimal(0),
            max_source_tier=0,
        )
    assert product_profile.ref.client_entity_id == profiled.ref.client_entity_id
    assert product_profile.ref.client_kb_version == 2
    await bind_workspace_client(
        conn,
        workspace_id=workspace_id,
        client_entity_id=profiled.ref.client_entity_id,
    )
    return _Seeded(
        workspace_id=workspace_id,
        brand=brand,
        product=product,
        project_a=project_a,
        project_b=project_b,
        client_entity_id=profiled.ref.client_entity_id,
        client_kb_version=profiled.ref.client_kb_version,
        product_kb_version=product_profile.ref.client_kb_version,
    )


async def _record_project_statement(
    conn: AsyncConnection,
    *,
    seeded: _Seeded,
    project: Project,
    artifacts: DurableAgentArtifactStore,
    route_key: str,
    quote: str,
) -> None:
    ref = await artifacts.persist_body(
        workspace_id=seeded.workspace_id,
        data=quote.encode(),
        media_type="text/plain",
        subject_bindings=((UUID(str(seeded.client_entity_id)), "context"),),
        project_bindings=((project.project_id, "project_conversation_context"),),
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=seeded.workspace_id,
        brand_id=seeded.brand.brand_id,
        product_id=project.product_id,
        project_id=project.project_id,
        client_entity_id=seeded.client_entity_id,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=ref.artifact_key,
        content_sha256=ref.sha256,
        actor="human",
        onboarding_input_id=OnboardingInputId(uuid4()),
    )
    await record_statement(
        conn,
        onboarding_input_id=captured.onboarding_input_id,
        workspace_id=seeded.workspace_id,
        brand_id=seeded.brand.brand_id,
        product_id=project.product_id,
        project_id=project.project_id,
        client_entity_id=seeded.client_entity_id,
        entity_id=seeded.client_entity_id,
        route_kind=StatementRoute.PROJECT_STATE,
        route_key=route_key,
        quote=quote,
        quote_start=0,
        quote_end=len(quote),
        created_by_actor="agent",
    )


def _runner(
    *,
    artifacts: DurableAgentArtifactStore,
    conn_factory: ConnFactory,
) -> ProjectConversationTurnRunner:
    unused = cast(Any, None)
    return ProjectConversationTurnRunner(
        engine=cast(Any, SimpleNamespace(artifacts=artifacts)),
        executor=unused,
        recipes=unused,
        starter=unused,
        parameters=unused,
        conn_factory=conn_factory,
        streaming=False,
    )


def test_pre_recon_composes_real_l2_and_honest_empty_l3(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = f"s3-pre-{uuid4().hex[:8]}"
            await seed_workspace(conn, workspace_id)
            brand = await create_brand(conn, workspace_id=workspace_id, name="Pre Recon Brand")
            project = await create_project(
                conn,
                workspace_id=workspace_id,
                brand_id=brand.brand_id,
                name="Pre Recon Project",
            )
            factory = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "pre-recon"),
                conn_factory=factory,
            )
            runner = _runner(artifacts=artifacts, conn_factory=factory)
            submission = _submission(
                workspace_id=workspace_id,
                project_id=project.project_id,
                suffix="pre",
            )
            scope = await runner._resolve_current_scope(conn, submission)
            bundle = await runner._compose_project_context(submission=submission, scope=scope)
            assert scope.client_entity_id is None
            assert scope.client_kb_version is None
            assert bundle.artifacts == ()

            envelope = ProjectConversationCard.model_validate(
                project_conversation_card_payload(
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    project_name=project.name,
                    project_status=project.status,
                    brand_id=brand.brand_id,
                    product_id=None,
                    thread_id=submission.thread_id,
                )
            )
            assert envelope.context_availability.client_knowledge.value == "unavailable"
            assert envelope.context_availability.stage0_project_state.value == "unavailable"
            assert envelope.context_availability.brand_profile.value == "minimal"

            reader = DbCompiledContextCardReader(conn_factory=factory)
            brand_card = await reader.read(
                workspace_id=workspace_id,
                object_type="brand",
                object_id=brand.brand_id,
            )
            assert brand_card is not None
            assert brand_card.ref == DomainObjectRef(
                workspace_id=workspace_id,
                object_type="brand",
                object_id=brand.brand_id,
                version=None,
            )
            assert json.loads(brand_card.body)["name"] == "Pre Recon Brand"

    run_async(scenario())


def test_post_recon_scope_composes_only_the_brand_knowledge_index(
    tmp_path: Path,
) -> None:
    """Ruling D5: a fully post-recon scope composes the knowledge index and nothing else.

    The workspace deliberately carries everything the retired compilers used to consume — a
    published account-wide Client-KB, a product-scoped KB, a confirmed product and per-project
    Stage-0 statements. None of it reaches L3 any more. What does is the brand's own knowledge,
    pinned per turn, indexed per project: the same documents, but the *confirmation* is per
    project, so two projects of one brand get two different index cards.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=uuid4().hex[:8])
            factory = conn_session_factory(conn)
            storage = FsStorage(tmp_path / "post-recon")
            artifacts = DurableAgentArtifactStore(
                storage=storage,
                conn_factory=factory,
            )
            await _record_project_statement(
                conn,
                seeded=seeded,
                project=seeded.project_a,
                artifacts=artifacts,
                route_key="goal_a",
                quote="Project A goal only",
            )
            runner = _runner(artifacts=artifacts, conn_factory=factory)
            submission_a = _submission(
                workspace_id=seeded.workspace_id,
                project_id=seeded.project_a.project_id,
                suffix="a",
            )
            submission_b = _submission(
                workspace_id=seeded.workspace_id,
                project_id=seeded.project_b.project_id,
                suffix="b",
            )
            scope_a = await runner._resolve_current_scope(conn, submission_a)
            scope_b = await runner._resolve_current_scope(conn, submission_b)
            # Everything the four retired compilers needed is present on scope A.
            assert scope_a.product_id == seeded.product.product_id
            assert scope_a.client_kb_version == seeded.client_kb_version
            assert scope_a.product_kb_version == seeded.product_kb_version

            # A brand whose knowledge pin holds no document composes honestly nothing — a pinned
            # ``client_kb_version`` no longer conjures a Client-KB card.
            empty = await runner._compose_project_context(submission=submission_a, scope=scope_a)
            assert empty.artifacts == ()
            assert empty.available is False

            documents = _pinned_documents(project_id=seeded.project_a.project_id)
            bundle_a = await runner._compose_project_context(
                submission=submission_a,
                scope=scope_a,
                documents=documents,
                confirmed_icp=confirmed_icp_for_project(
                    documents, pinned_document_id=_icp_document_id(documents)
                ),
            )
            bundle_b = await runner._compose_project_context(
                submission=submission_b,
                scope=scope_b,
                documents=documents,
                # Project B pinned nothing, so nothing is its confirmed ICP.
                confirmed_icp=confirmed_icp_for_project(documents, pinned_document_id=None),
            )
            assert tuple(item.name for item in bundle_a.artifacts) == ("brand_knowledge_index",)
            assert tuple(item.name for item in bundle_b.artifacts) == ("brand_knowledge_index",)
            index_a = bundle_a.artifacts[0]
            index_b = bundle_b.artifacts[0]
            assert index_a.domain_ref == DomainObjectRef(
                workspace_id=seeded.workspace_id,
                object_type="brand_knowledge_index",
                object_id=seeded.brand.brand_id,
                version=None,
            )

            card_a = BrandKnowledgeIndexCard.model_validate_json(
                await artifacts.read(index_a.artifact_ref)
            )
            card_b = BrandKnowledgeIndexCard.model_validate_json(
                await artifacts.read(index_b.artifact_ref)
            )
            assert card_a.brand_id == seeded.brand.brand_id
            assert [entry.path for entry in card_a.documents] == [
                "company/overview.md",
                "audience/icp-gi-groups.md",
            ]
            assert card_a.documents[0].workspace_path == "brand/knowledge/company/overview.md"
            # The ICP was confirmed for project A, so only project A's index carries it.
            assert card_a.confirmed_icp is not None
            assert card_a.confirmed_icp.icp_key == "gi-groups"
            assert card_b.confirmed_icp is None
            assert index_a.artifact_ref != index_b.artifact_ref
            # The persisted bytes are exactly the compiled card's canonical bytes.
            assert index_a.artifact_ref.sha256 == card_a.content_sha256().removeprefix("sha256:")

            assert tuple(
                (item.card_kind, item.schema_version, item.omitted_count)
                for item in bundle_a.observations
            ) == (("brand_knowledge_index", "1", 0),)

            # ``bind_project=False``: the index describes the brand, not one project, so it is
            # never bound to a project the way a Stage-0 card was.
            project_binding_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM agent_artifact_project "
                            "WHERE workspace_id=:workspace AND artifact_key=:key"
                        ),
                        {
                            "workspace": seeded.workspace_id,
                            "key": index_a.artifact_ref.artifact_key,
                        },
                    )
                ).scalar_one()
            )
            assert project_binding_count == 0

            request = await _context_request(
                artifacts=artifacts,
                submission=submission_a,
                scope=scope_a,
                bundle=bundle_a.artifacts,
            )
            l2 = await WorkspaceProductLayerSource(
                DbCompiledContextCardReader(conn_factory=factory)
            ).load(request=request, profile=_profile(), history=())
            l2_domain_refs = tuple(item.ref for item in l2 if isinstance(item.ref, DomainObjectRef))
            assert {(item.object_type, item.object_id) for item in l2_domain_refs} == {
                ("brand", seeded.brand.brand_id),
                ("product", seeded.product.product_id),
            }

    run_async(scenario())


async def _context_request(
    *,
    artifacts: DurableAgentArtifactStore,
    submission: AgentTurnSubmissionRow,
    scope: _ProjectScope,
    bundle: tuple[ProjectContextArtifact, ...],
) -> AgentTurnRequest:
    envelope_ref = await artifacts.persist_body(
        workspace_id=submission.workspace_id,
        data=json.dumps(
            project_conversation_card_payload(
                workspace_id=submission.workspace_id,
                project_id=scope.project_id,
                project_name=scope.name,
                project_status=scope.status,
                brand_id=scope.brand_id,
                product_id=scope.product_id,
                thread_id=submission.thread_id,
                client_knowledge_available=bool(bundle),
                stage0_project_state_available=bool(bundle),
            ),
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
        media_type="application/vnd.clue.project-conversation-card+json",
    )
    budget_ref = await artifacts.persist_body(
        workspace_id=submission.workspace_id,
        data=b'{"limit_millicents":1,"schema_version":"1"}',
        media_type="application/vnd.clue.agent-budget-envelope+json",
    )
    manifest_ref = await artifacts.persist_body(
        workspace_id=submission.workspace_id,
        data=b'{"schema_version":"test"}',
        media_type="application/vnd.clue.agent-resource-manifest+json",
    )
    message_ref = await artifacts.persist_body(
        workspace_id=submission.workspace_id,
        data=b"Current user instruction",
        media_type="text/plain",
    )
    base = constitution(
        workspace_id=submission.workspace_id,
        project_id=scope.project_id,
        execution_id=ExecutionId(uuid4()),
        actor_id=submission.submitted_by_user_id,
        brand_id=scope.brand_id,
        product_id=scope.product_id,
        client_entity_id=(None if scope.client_entity_id is None else str(scope.client_entity_id)),
        project_card_ref=envelope_ref,
        budget_envelope_ref=budget_ref,
        resource_manifest_ref=manifest_ref,
        project_context_artifacts=bundle,
        focus_refs=(),
    )
    return AgentTurnRequest(
        turn_id=submission.turn_id,
        thread_id=submission.thread_id,
        constitution=base,
        user_message_artifact_ref=message_ref,
        requested_at=submission.requested_at,
    )


def test_the_pinned_document_set_is_the_composition_authority(tmp_path: Path) -> None:
    """The pin decides, and the assembled receipt points at exactly those bytes.

    Re-composing a turn from its own pinned documents is byte-identical however much onboarding
    published in between; only a *different* pinned set produces a different card. The L3 receipt
    then carries the artifact identity of that exact card, and losing its bytes is a hard read
    failure — never a recompiled guess.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=uuid4().hex[:8])
            factory = conn_session_factory(conn)
            storage = FsStorage(tmp_path / "pin-and-receipt")
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=factory)
            runner = _runner(artifacts=artifacts, conn_factory=factory)
            submission = _submission(
                workspace_id=seeded.workspace_id,
                project_id=seeded.project_a.project_id,
                suffix="pin",
            )
            scope = await runner._resolve_current_scope(conn, submission)
            pinned = _pinned_documents(project_id=seeded.project_a.project_id)
            confirmed = confirmed_icp_for_project(
                pinned, pinned_document_id=_icp_document_id(pinned)
            )
            bundle = await runner._compose_project_context(
                submission=submission,
                scope=scope,
                documents=pinned,
                confirmed_icp=confirmed,
            )

            # Background recon advances the account-wide KB mid-turn. The composed bundle is
            # decided by the pinned documents alone, so it does not move.
            profiled_v2 = await reverse_profile(
                conn,
                ClientInput(
                    name="Production Context Customer",
                    website=f"https://{seeded.workspace_id.removeprefix('production-context-s3-')}.example",
                    materials=(
                        VolunteeredMaterial(
                            kind="background_recon",
                            label="background facts",
                            content="Background recon advanced the account-wide KB.",
                            asserted_fields={
                                key: f"v2 grounded {key}" for key in CLIENT_KNOWLEDGE_FIELDS
                            },
                        ),
                    ),
                ),
                workspace_id=seeded.workspace_id,
                product_id=None,
                budget_cap_cents=Decimal(0),
                max_source_tier=0,
            )
            assert profiled_v2.ref.client_kb_version == seeded.client_kb_version + 1
            again = await runner._compose_project_context(
                submission=submission,
                scope=scope,
                documents=pinned,
                confirmed_icp=confirmed,
            )
            assert again.artifacts == bundle.artifacts

            # A newer pinned set — what the *next* turn would pin — is a different card.
            newer = await runner._compose_project_context(
                submission=submission,
                scope=scope,
                documents=(
                    *pinned,
                    _pinned_document(
                        path="audience/persona-gi-groups.md",
                        kind="audience-persona",
                        version=1,
                        status="ready",
                        body="---\nkind: audience-persona\n---\n\nThe practice manager.\n",
                    ),
                ),
                confirmed_icp=confirmed,
            )
            assert newer.artifacts[0].artifact_ref != bundle.artifacts[0].artifact_ref

            request = await _context_request(
                artifacts=artifacts,
                submission=submission,
                scope=scope,
                bundle=bundle.artifacts,
            )
            receipts = _Receipts()
            l7 = _StaticLayer(
                ContextLayer.L7_TURN,
                (
                    ContextCandidate(
                        stable_key="current-user",
                        ref=request.user_message_artifact_ref,
                        body="Current user instruction",
                        role="user",
                        origin="current_user_instruction",
                        materialized_path="inputs/user-message.txt",
                        required=True,
                    ),
                ),
            )
            sources: list[ContextLayerSource] = [_StaticLayer(layer) for layer in ContextLayer]
            sources[2] = ProjectLayerSource(artifacts=artifacts)
            sources[6] = l7
            assembler = DeterministicAgentContextAssembler(
                sources=sources,
                policy=ContextAssemblyPolicy(
                    version="s3-receipt-v1",
                    token_counter_version="utf8-bytes-v1",
                    budgets=tuple(
                        LayerBudget(layer=layer, max_tokens=100_000) for layer in ContextLayer
                    ),
                ),
                receipts=receipts,
                clock=lambda: _NOW,
            )
            assembled = await assembler.assemble(
                request=request,
                profile=_profile(),
                history=(),
            )
            assert assembled.manifest.layers[2].materialized_paths == (
                "context/project/brand_knowledge_index.json",
                "context/project/budget.json",
                "context/project/project_card.json",
            )
            l3_refs = tuple(
                item for item in receipts.values[0].refs if item.layer is ContextLayer.L3_PROJECT
            )
            assert tuple(item.ref for item in l3_refs) == assembled.manifest.layers[2].source_refs
            assert all(isinstance(item.ref, ArtifactRef) for item in l3_refs)
            assert all(
                item.content_sha256 == item.ref.sha256
                for item in l3_refs
                if isinstance(item.ref, ArtifactRef)
            )
            assert all(item.materialized_path for item in l3_refs)

            # Required context bytes disappearing is a hard read failure before a model source can
            # be assembled; no guessed/recompiled replacement is admitted.
            missing_ref = bundle.artifacts[0].artifact_ref
            await storage.delete(missing_ref.artifact_key)
            with pytest.raises(ArtifactNotFound):
                await ProjectLayerSource(artifacts=artifacts).load(
                    request=request,
                    profile=_profile(),
                    history=(),
                )

    run_async(scenario())


def test_context_logs_are_body_free_by_construction() -> None:
    source = Path("platform/api/clue_api/agent_turn_fleet_wiring.py").read_text()
    event = source[
        source.index('"agent_turn.context_composed"') : source.index(
            ")\n        result = await self._execute_watched",
            source.index('"agent_turn.context_composed"'),
        )
    ]
    assert "brief_value" not in event
    assert "claim" not in event
    assert "email" not in event
    assert "token" not in event
    assert "password" not in event
    assert "artifact_key" not in event
    assert "sha256" in event
