"""The production conversation turn opens on the brand's knowledge (ARV2 onboarding O6, T7).

One deterministic model double is the only substituted boundary; everything else is the production
chain — the AGENT_TURN handler, the scope receipt, the knowledge pin, the recipe/executor, the
seven-layer assembler and the real workspace lease. Four properties are asserted from durable rows
and from the lease's own bytes, never from an in-memory convenience:

* the turn writes exactly one ``agent_turn_knowledge_pin`` row naming the brand's current documents;
* L3 carries exactly one composed project artifact — ``brand_knowledge_index`` — and none of the
  four cards the old production envelope compiled;
* the pinned documents are on the lease, read-only, under ``inputs/brand/knowledge/`` at the digest
  the pin recorded;
* publishing a newer document after the pin cannot change what a retry of that turn seeds.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentExecutionStatus, ScriptedAgentChatModel
from clue_api.agent_execution_wiring import postgres_agent_checkpointer
from clue_api.agent_platform_wiring import (
    AgentPlatformComponents,
    DbAgentOwnershipRouter,
)
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_turn_fleet_wiring import build_agent_turn_work_handler
from clue_api.agent_turn_submission import (
    dispatch_next_thread_turn,
    insert_submission,
    thread_work_id,
)
from clue_api.agent_turn_wiring import (
    AgentPrivacyService,
    DbAgentHistoryStore,
    DbAgentReplayReader,
    DbAgentTurnJournal,
    DurableAgentArtifactStore,
)
from clue_api.agent_workspace_wiring import build_agent_workspace_factory
from clue_api.brand_knowledge_context import (
    INPUT_PREFIX,
    BrandKnowledgeIndexCard,
    knowledge_seed_files,
    load_or_create_knowledge_pin,
    read_pinned_documents,
)
from clue_api.execution_wiring import (
    ExecutionRunEventWriter,
    StorageExecutionParameterStore,
    StorageParameterArtifactStore,
    build_tool_invoker,
)
from clue_api.recipe_wiring import (
    build_recipe_lifecycle,
    build_recipe_pin_registry,
    seed_system_recipes,
)
from clue_api.stage0_trial import stage0_trial_recipe_definitions
from clue_api.thread_store import create_thread
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Settings
from clue_core import AssemblyRequest, ExecutionId, MemoryBundle, OnboardingInputKind, ProjectRunId
from clue_execution import (
    CompatibilityLoader,
    DbExecutionJournal,
    DbExecutionStarter,
    DbRecipeReader,
    DbRecipeRepository,
    RecipeExecutor,
)
from clue_fleet import (
    FleetTaskKind,
    FleetTaskStatus,
    WorkContext,
    claim_next_task,
    finish_task,
)
from clue_research.stage0 import submit_onboarding_input
from clue_storage import FsStorage
from clue_toolbelt import DbIdempotencyStore
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

OVERVIEW = (
    "---\nkind: company-overview\n---\n\n"
    "Acme builds scheduling software for gastroenterology clinics.\n\n"
    "A second paragraph the summary never reaches.\n"
)
ICP = (
    "---\nkind: icp-definition\nicp_key: gi-groups\nstatus: proposed\n"
    "product_ids: [prd_aura]\n---\n\n"
    "Independent gastroenterology groups with three to twelve physicians.\n"
)
RESEARCH = "---\nkind: product-research\nproduct_id: prd_aura\n---\n\nAura schedules procedures.\n"
LATER = "---\nkind: audience-persona\n---\n\nPublished after this turn pinned its knowledge.\n"


class _ScriptedModels:
    def __init__(self, responses: Sequence[AIMessage]) -> None:
        self.responses = tuple(responses)
        self.build_count = 0

    def build(self, **kwargs: Any) -> ScriptedAgentChatModel:
        del kwargs
        self.build_count += 1
        return ScriptedAgentChatModel(responses=self.responses)


class _NoMemory:
    async def assemble(self, request: AssemblyRequest) -> MemoryBundle | None:
        del request
        return None


class _ConnQueue:
    """Use the real task rows while adapting the handler's three queue calls to one test conn."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def finish(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        status: FleetTaskStatus,
        result_ref: dict[str, Any] | None = None,
    ) -> bool:
        return await finish_task(
            self._conn,
            task_id=task_id,
            worker_id=worker_id,
            status=status,
            result_ref=result_ref,
        )

    async def touch(self, *, task_id: UUID, worker_id: str) -> bool:
        del task_id, worker_id
        return True

    async def requeue(self, *, task_id: UUID, worker_id: str) -> bool:
        del task_id, worker_id
        return True


class _RecordingWorkspaces:
    """The production workspace factory, plus a handle on the lease the turn actually used."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.leases: list[Any] = []

    def acquire(self, **kwargs: Any) -> Any:
        lease = self._inner.acquire(**kwargs)
        self.leases.append(lease)
        return lease

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def _seed_document(
    conn: AsyncConnection,
    *,
    artifacts: DurableAgentArtifactStore,
    workspace_id: str,
    brand_id: str,
    path: str,
    kind: str,
    version: int,
    status: str,
    body: str,
) -> tuple[UUID, str]:
    ref = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=body.encode(),
        media_type="text/markdown",
    )
    document_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, folder, "
            "path, kind, version, status, artifact_key, artifact_sha256) "
            "VALUES (:id, :ws, :brand, :folder, :path, :kind, :version, :status, :key, :sha)"
        ),
        {
            "id": document_id,
            "ws": workspace_id,
            "brand": brand_id,
            "folder": path.split("/", 1)[0],
            "path": path,
            "kind": kind,
            "version": version,
            "status": status,
            "key": ref.artifact_key,
            "sha": ref.sha256,
        },
    )
    return document_id, ref.sha256


async def _capture_submission(
    conn: AsyncConnection,
    *,
    artifacts: DurableAgentArtifactStore,
    workspace_id: str,
    project_id: str,
    brand_id: str,
    label: str,
) -> Any:
    principal = await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=f"usr-o6t7-{label}",
        membership_id=f"mem-o6t7-{label}",
    )
    thread_id = f"thr-o6t7-{label}-{uuid4().hex[:8]}"
    await create_thread(
        conn,
        thread_id=thread_id,
        workspace_id=workspace_id,
        project_id=project_id,
        created_by_user_id=principal.user_id,
        created_via_membership_id=principal.membership_id,
    )
    message = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=b"Who should we target first?",
        media_type="text/plain",
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=workspace_id,
        brand_id=brand_id,
        project_id=project_id,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=message.artifact_key,
        content_sha256=message.sha256,
        actor="human",
    )
    turn_id = uuid4()
    submission, created = await insert_submission(
        conn,
        turn_id=turn_id,
        workspace_id=workspace_id,
        project_id=project_id,
        thread_id=thread_id,
        submitted_by_user_id=principal.user_id,
        submitted_via_membership_id=principal.membership_id,
        onboarding_input_id=captured.onboarding_input_id,
        message_artifact_key=message.artifact_key,
        message_sha256=message.sha256,
        idempotency_key=f"o6t7-{label}-{turn_id}",
    )
    assert created is True
    return submission


def _responses() -> tuple[AIMessage, ...]:
    return (
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "finalize_turn",
                    "args": {
                        "status": "awaiting_input",
                        "user_message": "I read the brand's knowledge. Shall we start with GI?",
                    },
                    "id": "o6t7-finalize",
                    "type": "tool_call",
                }
            ],
        ),
    )


async def _l3_paths(conn: AsyncConnection, turn_id: UUID) -> tuple[str, ...]:
    rows = (
        await conn.execute(
            text(
                "SELECT r.materialized_path FROM agent_context_ref r "
                "JOIN agent_context_bundle b ON b.id = r.context_bundle_id "
                "WHERE b.turn_id = :turn AND r.disposition = 'included' "
                "AND r.materialized_path LIKE 'context/project/%' "
                "ORDER BY r.materialized_path"
            ),
            {"turn": turn_id},
        )
    ).scalars()
    return tuple(str(item) for item in rows)


def test_the_production_turn_pins_seeds_and_indexes_the_brand_knowledge(tmp_path: Path) -> None:
    async def scenario() -> None:
        # LangGraph installs a concurrent index; do it before the rollback fixture's transaction.
        async with postgres_agent_checkpointer(ExecutionId(uuid4())):
            pass
        async with rollback_conn() as conn:
            workspace_id = f"o6t7-{uuid4().hex[:8]}"
            project = await seed_project(conn, workspace_id, name="O6 T7 project")
            factory = conn_session_factory(conn)
            storage = FsStorage(tmp_path / "artifacts")
            settings = Settings(
                _env_file=None,
                chat_enabled=True,
                agent_workspace_root=str(tmp_path / "agent-workspaces"),
            )
            tools = build_toolbelt(
                storage=storage,
                settings=settings,
                gateway=None,
                conn_factory=factory,
            )
            profiles = build_agent_profile_registry(tools)
            pin_registry = build_recipe_pin_registry(tool_registry=tools, conn_factory=factory)
            compatibility = CompatibilityLoader(pin_registry)
            recipes = DbRecipeReader(conn_factory=factory)
            repository = DbRecipeRepository(conn_factory=factory)
            await seed_system_recipes(
                repository=repository,
                lifecycle=build_recipe_lifecycle(
                    tool_registry=tools,
                    conn_factory=factory,
                    pin_registry=pin_registry,
                ),
                definitions=stage0_trial_recipe_definitions(),
            )
            parameters = StorageExecutionParameterStore(
                StorageParameterArtifactStore(storage=storage, conn_factory=factory)
            )
            tool_invoker = build_tool_invoker(
                registry=tools,
                idempotency_store=DbIdempotencyStore(conn_factory=factory),
                storage=storage,
                settings=settings,
                conn_factory=factory,
            )
            journal = DbExecutionJournal(transport=ExecutionRunEventWriter())
            executor = RecipeExecutor(
                conn_factory=factory,
                recipes=recipes,
                compatibility=compatibility,
                journal=journal,
                parameters=parameters,
                tool_invoker=tool_invoker,
                max_concurrency=2,
            )
            starter = DbExecutionStarter(
                conn_factory=factory,
                recipes=recipes,
                compatibility=compatibility,
                journal=journal,
            )
            source_root = tmp_path / "source-root"
            home_root = tmp_path / "home-root"
            source_root.mkdir()
            home_root.mkdir()
            workspaces = _RecordingWorkspaces(
                build_agent_workspace_factory(
                    storage=storage,
                    settings=settings,
                    source_root=source_root,
                    home_root=home_root,
                )
            )
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=factory)
            models = _ScriptedModels(_responses())
            components = AgentPlatformComponents(
                profiles=profiles,
                models=models,
                workspaces=cast(Any, workspaces),
                artifacts=artifacts,
                turns=DbAgentTurnJournal(conn_factory=factory),
                history=DbAgentHistoryStore(conn_factory=factory),
                replay=DbAgentReplayReader(storage=storage, conn_factory=factory),
                privacy=AgentPrivacyService(
                    storage=storage,
                    workspaces=cast(Any, workspaces),
                    conn_factory=factory,
                ),
                ownership=DbAgentOwnershipRouter(settings=settings, conn_factory=factory),
            )
            try:
                overview_sha = (
                    await _seed_document(
                        conn,
                        artifacts=artifacts,
                        workspace_id=workspace_id,
                        brand_id=project.brand_id,
                        path="company/overview.md",
                        kind="company-overview",
                        version=1,
                        status="ready",
                        body=OVERVIEW,
                    )
                )[1]
                await _seed_document(
                    conn,
                    artifacts=artifacts,
                    workspace_id=workspace_id,
                    brand_id=project.brand_id,
                    path="audience/icp-gi-groups.md",
                    kind="icp-definition",
                    version=1,
                    status="proposed",
                    body=ICP,
                )
                await _seed_document(
                    conn,
                    artifacts=artifacts,
                    workspace_id=workspace_id,
                    brand_id=project.brand_id,
                    path="product/aura.md",
                    kind="product-research",
                    version=1,
                    status="ready",
                    body=RESEARCH,
                )

                submission = await _capture_submission(
                    conn,
                    artifacts=artifacts,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    brand_id=project.brand_id,
                    label="run",
                )
                await dispatch_next_thread_turn(
                    conn,
                    workspace_id=workspace_id,
                    thread_id=submission.thread_id,
                )
                work_id = ProjectRunId(
                    thread_work_id(
                        workspace_id=workspace_id,
                        thread_id=submission.thread_id,
                    )
                )
                claimed = await claim_next_task(
                    conn,
                    kind=FleetTaskKind.AGENT_TURN,
                    worker_id="o6t7-worker",
                    project_run_id=work_id,
                )
                assert claimed is not None
                handler = build_agent_turn_work_handler(
                    components=components,
                    tools=tools,
                    tool_invoker=tool_invoker,
                    executor=executor,
                    compatibility=compatibility,
                    recipes=recipes,
                    starter=starter,
                    parameters=parameters,
                    memory=_NoMemory(),
                    queue=_ConnQueue(conn),  # type: ignore[arg-type]
                    storage=storage,
                    conn_factory=factory,
                    streaming=False,
                )
                result = await handler.handle(
                    WorkContext(
                        task_id=claimed.task_id,
                        work_id=thread_work_id(
                            workspace_id=workspace_id,
                            thread_id=submission.thread_id,
                        ),
                        worker_id="o6t7-worker",
                        lease_generation=claimed.attempts,  # type: ignore[arg-type]
                        payload=claimed.payload,
                        stop_requested=asyncio.Event(),
                        lease_lost=asyncio.Event(),
                    )
                )
                assert result.outcome == AgentExecutionStatus.AWAITING_INPUT.value
                assert models.build_count == 1

                # 1. the pin — one row, this brand's three current documents.
                pin_rows = (
                    (
                        await conn.execute(
                            text(
                                "SELECT brand_id, documents, documents_sha256 "
                                "FROM agent_turn_knowledge_pin WHERE turn_id = :turn"
                            ),
                            {"turn": submission.turn_id},
                        )
                    )
                    .mappings()
                    .all()
                )
                assert len(pin_rows) == 1
                pinned = pin_rows[0]["documents"]
                if isinstance(pinned, bytes | bytearray | str):
                    pinned = json.loads(pinned)
                assert pin_rows[0]["brand_id"] == project.brand_id
                assert sorted(item["path"] for item in pinned) == [
                    "audience/icp-gi-groups.md",
                    "company/overview.md",
                    "product/aura.md",
                ]

                # 2. L3 carries the index and none of the four retired cards.
                assert await _l3_paths(conn, submission.turn_id) == (
                    "context/project/brand_knowledge_index.json",
                    "context/project/budget.json",
                    "context/project/project_card.json",
                )

                # 3. the pinned documents are on the lease, read-only, at the pinned digest.
                assert len(workspaces.leases) == 1
                lease = workspaces.leases[0]
                entry = lease.backend.stat_entry_sync(f"{INPUT_PREFIX}company/overview.md")
                assert entry.sha256 == overview_sha
                assert entry.read_only is True
                for path in ("audience/icp-gi-groups.md", "product/aura.md"):
                    assert lease.backend.stat_entry_sync(f"{INPUT_PREFIX}{path}").read_only is True

                # 4. the index card itself — three entries, no confirmed ICP for this project.
                index_key = (
                    await conn.execute(
                        text(
                            "SELECT r.artifact_key FROM agent_context_ref r "
                            "JOIN agent_context_bundle b ON b.id = r.context_bundle_id "
                            "WHERE b.turn_id = :turn AND r.disposition = 'included' "
                            "AND r.materialized_path = "
                            "'context/project/brand_knowledge_index.json'"
                        ),
                        {"turn": submission.turn_id},
                    )
                ).scalar_one()
                card = BrandKnowledgeIndexCard.model_validate_json(
                    await storage.get(str(index_key))
                )
                assert card.brand_id == project.brand_id
                assert [entry.path for entry in card.documents] == [
                    "company/overview.md",
                    "audience/icp-gi-groups.md",
                    "product/aura.md",
                ]
                assert card.documents[0].workspace_path == f"{INPUT_PREFIX}company/overview.md"
                assert card.confirmed_icp is None
                assert card.product_set is None
                assert card.omitted_count == 0

                # 5. a document published after the pin cannot change what a retry seeds.
                await _seed_document(
                    conn,
                    artifacts=artifacts,
                    workspace_id=workspace_id,
                    brand_id=project.brand_id,
                    path="audience/persona-gi-groups.md",
                    kind="audience-persona",
                    version=1,
                    status="ready",
                    body=LATER,
                )
                retry_pin, retry_created = await load_or_create_knowledge_pin(
                    conn,
                    workspace_id=workspace_id,
                    turn_id=submission.turn_id,
                    brand_id=project.brand_id,
                )
                assert retry_created is False
                assert retry_pin.documents_sha256 == pin_rows[0]["documents_sha256"]
                retry_seeds = knowledge_seed_files(
                    await read_pinned_documents(conn, storage, pin=retry_pin)
                )
                assert [seed.path for seed in retry_seeds] == [
                    f"{INPUT_PREFIX}audience/icp-gi-groups.md",
                    f"{INPUT_PREFIX}company/overview.md",
                    f"{INPUT_PREFIX}product/aura.md",
                ]
            finally:
                workspaces.close()

    run_async(scenario())
