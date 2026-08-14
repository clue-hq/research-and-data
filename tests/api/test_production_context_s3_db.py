"""S3 acceptance for the production brand/Client-KB/project-context composition path."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
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
from clue_api.agent_turn_wiring import AgentPrivacyService, DurableAgentArtifactStore
from clue_api.client_context_binding import bind_workspace_client
from clue_api.stage0_card_dsar import (
    STAGE0_CARD_QUOTE_BINDING_KIND,
    Stage0StatementEraser,
)
from clue_core import EntityId, ExecutionId, OnboardingInputId, OnboardingInputKind
from clue_db import ConnFactory
from clue_projections import (
    ClientKnowledgeCardV2,
    ProductKnowledgeCard,
    ProductProfileCard,
    ProjectConversationCard,
    Stage0ProjectStateCard,
)
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


def test_post_recon_projects_share_client_card_and_isolate_stage0(
    tmp_path: Path,
) -> None:
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
            await _record_project_statement(
                conn,
                seeded=seeded,
                project=seeded.project_b,
                artifacts=artifacts,
                route_key="goal_b",
                quote="Project B goal only",
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
            # Project A has a confirmed product, but its KB pin is still the account-wide marker.
            assert scope_a.product_id == seeded.product.product_id
            assert scope_a.client_kb_version == seeded.client_kb_version
            assert scope_a.product_kb_version == seeded.product_kb_version
            assert scope_b.client_kb_version == seeded.client_kb_version
            assert scope_b.product_kb_version is None

            bundle_a = await runner._compose_project_context(
                submission=submission_a,
                scope=scope_a,
            )
            bundle_b = await runner._compose_project_context(
                submission=submission_b,
                scope=scope_b,
            )
            assert tuple(item.name for item in bundle_a.artifacts) == (
                "client_knowledge",
                "stage0_project_state",
                "product_profile",
                "product_knowledge",
            )
            client_a, stage_a, profile_a, product_a = bundle_a.artifacts
            client_b, stage_b = bundle_b.artifacts
            assert client_a.artifact_ref == client_b.artifact_ref
            assert client_a.domain_ref.object_id == str(seeded.client_entity_id)
            assert client_a.domain_ref.version == seeded.client_kb_version
            assert stage_a.domain_ref.object_id == seeded.project_a.project_id
            assert stage_b.domain_ref.object_id == seeded.project_b.project_id
            assert stage_a.artifact_ref != stage_b.artifact_ref
            assert profile_a.domain_ref.object_id == seeded.product.product_id
            assert product_a.domain_ref.object_id == seeded.product.product_id
            assert product_a.domain_ref.version == seeded.product_kb_version

            client_card = ClientKnowledgeCardV2.model_validate_json(
                await artifacts.read(client_a.artifact_ref)
            )
            profile_card = ProductProfileCard.model_validate_json(
                await artifacts.read(profile_a.artifact_ref)
            )
            product_card = ProductKnowledgeCard.model_validate_json(
                await artifacts.read(product_a.artifact_ref)
            )
            card_a = Stage0ProjectStateCard.model_validate_json(
                await artifacts.read(stage_a.artifact_ref)
            )
            card_b = Stage0ProjectStateCard.model_validate_json(
                await artifacts.read(stage_b.artifact_ref)
            )
            assert client_card.company_client_kb_version == seeded.client_kb_version
            assert profile_card.product_id == seeded.product.product_id
            assert product_card.product_kb_version == seeded.product_kb_version
            quotes_a = {item.quoted_text for item in card_a.interview.current_effective_statements}
            quotes_b = {item.quoted_text for item in card_b.interview.current_effective_statements}
            assert quotes_a == {"Project A goal only"}
            assert quotes_b == {"Project B goal only"}
            assert quotes_a.isdisjoint(quotes_b)

            # S3.1: the production persistence path reverse-binds each embedded quote to its exact
            # statement. Client-level binding alone cannot answer a statement DSAR.
            statement_a_id = (
                await conn.execute(
                    text(
                        "SELECT id FROM volunteered_statement "
                        "WHERE workspace_id=:workspace AND project_id=:project"
                    ),
                    {
                        "workspace": seeded.workspace_id,
                        "project": seeded.project_a.project_id,
                    },
                )
            ).scalar_one()
            stage_a_bindings = {
                (UUID(str(row["subject_entity_id"])), str(row["binding_kind"]))
                for row in (
                    (
                        await conn.execute(
                            text(
                                "SELECT subject_entity_id, binding_kind "
                                "FROM agent_artifact_subject "
                                "WHERE workspace_id=:workspace AND artifact_key=:key"
                            ),
                            {
                                "workspace": seeded.workspace_id,
                                "key": stage_a.artifact_ref.artifact_key,
                            },
                        )
                    )
                    .mappings()
                    .all()
                )
            }
            assert stage_a_bindings == {
                (UUID(str(seeded.client_entity_id)), "context"),
                (UUID(str(statement_a_id)), STAGE0_CARD_QUOTE_BINDING_KIND),
            }

            project_binding_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM agent_artifact_project "
                            "WHERE workspace_id=:workspace AND artifact_key=:key"
                        ),
                        {
                            "workspace": seeded.workspace_id,
                            "key": client_a.artifact_ref.artifact_key,
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

            # Execute the existing governed statement-erasure path against the artifact emitted by
            # this production composer. It must discover A through the new reverse binding, purge
            # A and its captured quote, and leave project B's independently scoped card readable.
            erasure = await Stage0StatementEraser(
                privacy=AgentPrivacyService(
                    storage=storage,
                    # This fixture has no journaled AgentTurn, so the workspace closure is empty.
                    # Keep the production service while providing the unused port explicitly.
                    workspaces=cast(
                        Any,
                        SimpleNamespace(erase_for_privacy=lambda **_kwargs: False),
                    ),
                    conn_factory=factory,
                ),
                conn_factory=factory,
            ).erase_statement(
                workspace_id=seeded.workspace_id,
                statement_id=UUID(str(statement_a_id)),
            )
            assert stage_a.artifact_ref.artifact_key in erasure.card_artifact_keys
            assert stage_b.artifact_ref.artifact_key not in erasure.card_artifact_keys
            assert stage_a.artifact_ref.artifact_key in erasure.erase.tombstoned_artifact_keys
            with pytest.raises(ArtifactNotFound):
                await artifacts.read(stage_a.artifact_ref)
            assert (
                Stage0ProjectStateCard.model_validate_json(
                    await artifacts.read(stage_b.artifact_ref)
                )
                == card_b
            )

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


def test_kb_pin_receipt_and_missing_or_foreign_context_fail_closed(tmp_path: Path) -> None:
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
            pinned_v1 = await runner._resolve_current_scope(conn, submission)
            bundle_v1 = await runner._compose_project_context(
                submission=submission,
                scope=pinned_v1,
            )

            # Background recon publishes v2 after the turn pin. Reusing pinned_v1 remains v1;
            # resolving the next turn observes v2.
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
            assert profiled_v2.ref.client_entity_id == seeded.client_entity_id
            assert profiled_v2.ref.client_kb_version == seeded.client_kb_version + 1
            pinned_again = await runner._compose_project_context(
                submission=submission,
                scope=pinned_v1,
            )
            assert pinned_again.artifacts == bundle_v1.artifacts
            next_scope = await runner._resolve_current_scope(conn, submission)
            assert next_scope.client_kb_version == profiled_v2.ref.client_kb_version
            bundle_v2 = await runner._compose_project_context(
                submission=submission,
                scope=next_scope,
            )
            assert bundle_v2.artifacts[0].artifact_ref != bundle_v1.artifacts[0].artifact_ref

            request_v1 = await _context_request(
                artifacts=artifacts,
                submission=submission,
                scope=pinned_v1,
                bundle=bundle_v1.artifacts,
            )
            receipts = _Receipts()
            l7 = _StaticLayer(
                ContextLayer.L7_TURN,
                (
                    ContextCandidate(
                        stable_key="current-user",
                        ref=request_v1.user_message_artifact_ref,
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
                request=request_v1,
                profile=_profile(),
                history=(),
            )
            assert assembled.manifest.layers[2].materialized_paths == (
                "context/project/budget.json",
                "context/project/client_knowledge.json",
                "context/project/product_knowledge.json",
                "context/project/product_profile.json",
                "context/project/project_card.json",
                "context/project/stage0_project_state.json",
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
            missing_ref = bundle_v1.artifacts[0].artifact_ref
            await storage.delete(missing_ref.artifact_key)
            with pytest.raises(ArtifactNotFound):
                await ProjectLayerSource(artifacts=artifacts).load(
                    request=request_v1,
                    profile=_profile(),
                    history=(),
                )

            foreign_workspace = f"s3-foreign-{uuid4().hex[:8]}"
            await seed_workspace(conn, foreign_workspace)
            foreign_brand = await create_brand(
                conn,
                workspace_id=foreign_workspace,
                name="Foreign Brand",
            )
            foreign_project = await create_project(
                conn,
                workspace_id=foreign_workspace,
                brand_id=foreign_brand.brand_id,
                name="Foreign Project",
            )
            foreign_submission = _submission(
                workspace_id=foreign_workspace,
                project_id=foreign_project.project_id,
                suffix="foreign",
            )
            foreign_scope = replace(
                pinned_v1,
                project_id=foreign_project.project_id,
                name=foreign_project.name,
                status=foreign_project.status,
                brand_id=foreign_brand.brand_id,
                product_id=None,
            )
            with pytest.raises(LookupError, match="unavailable in this workspace"):
                await runner._compose_project_context(
                    submission=foreign_submission,
                    scope=foreign_scope,
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
