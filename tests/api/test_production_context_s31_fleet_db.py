"""S3.1 real production-chain acceptance.

One deterministic model double is the only substituted external boundary.  Everything around it is
the production composition: AGENT_TURN handler, scope receipt, recipe/executor, cards, seven-layer
assembler, governed S4 tool, Postgres LangGraph saver, finalization authority, and cold replay.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import text

from clue_agents import AgentExecutionStatus, ScriptedAgentChatModel
from clue_api.agent_execution_wiring import postgres_agent_checkpointer
from clue_api.agent_platform_wiring import (
    AgentPlatformComponents,
    DbAgentOwnershipRouter,
)
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_turn_fleet_wiring import build_agent_turn_work_handler
from clue_api.agent_turn_scope_pin import load_or_create_agent_turn_scope_pin
from clue_api.agent_turn_submission import (
    dispatch_next_thread_turn,
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
from clue_api.stage0_card_dsar import (
    STAGE0_CARD_QUOTE_BINDING_KIND,
    Stage0StatementEraser,
)
from clue_api.stage0_trial import stage0_trial_recipe_definitions
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Settings
from clue_core import AssemblyRequest, ExecutionId, MemoryBundle, ProjectRunId
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
from clue_research.stage0 import (
    CLIENT_KNOWLEDGE_FIELDS,
    ClientInput,
    VolunteeredMaterial,
    reverse_profile,
)
from clue_storage import ArtifactNotFound, FsStorage
from clue_toolbelt import DbIdempotencyStore
from tests.api.test_production_context_s3_db import _record_project_statement, _seed_post_recon
from tests.api.test_production_context_s31_scope_pin_db import _capture_submission
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


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


def _responses() -> tuple[AIMessage, ...]:
    return (
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "list_client_knowledge",
                    "args": {"limit": 3},
                    "id": "s31-list-kb",
                    "type": "tool_call",
                }
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "finalize_turn",
                    "args": {
                        "status": "awaiting_input",
                        "user_message": "Which of these products should this project focus on?",
                    },
                    "id": "s31-finalize",
                    "type": "tool_call",
                }
            ],
        ),
    )


def test_real_fleet_chain_keeps_original_pin_through_checkpoint_finalization_and_replay(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        # LangGraph installs a concurrent index. Do that before the rollback-only fixture opens
        # its long transaction; otherwise PostgreSQL correctly waits for that transaction's
        # virtual xid even though the actual turn composition is healthy.
        async with postgres_agent_checkpointer(ExecutionId(uuid4())):
            pass
        async with rollback_conn() as conn:
            seeded = await _seed_post_recon(conn, suffix=uuid4().hex[:8])
            factory = conn_session_factory(conn)
            storage = FsStorage(tmp_path / "fleet-artifacts")
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
            workspaces = build_agent_workspace_factory(
                storage=storage,
                settings=settings,
                source_root=source_root,
                home_root=home_root,
            )
            models = _ScriptedModels(_responses())
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=factory)
            components = AgentPlatformComponents(
                profiles=profiles,
                models=models,
                workspaces=workspaces,
                artifacts=artifacts,
                turns=DbAgentTurnJournal(conn_factory=factory),
                history=DbAgentHistoryStore(conn_factory=factory),
                replay=DbAgentReplayReader(storage=storage, conn_factory=factory),
                privacy=AgentPrivacyService(
                    storage=storage,
                    workspaces=workspaces,
                    conn_factory=factory,
                ),
                ownership=DbAgentOwnershipRouter(settings=settings, conn_factory=factory),
            )
            try:
                statement_quote = "Fleet-composed Stage-0 goal"
                await _record_project_statement(
                    conn,
                    seeded=seeded,
                    project=seeded.project_a,
                    artifacts=artifacts,
                    route_key="fleet_goal",
                    quote=statement_quote,
                )
                statement_id = (
                    await conn.execute(
                        text(
                            "SELECT id FROM volunteered_statement "
                            "WHERE workspace_id=:workspace AND project_id=:project "
                            "AND route_key='fleet_goal'"
                        ),
                        {
                            "workspace": seeded.workspace_id,
                            "project": seeded.project_a.project_id,
                        },
                    )
                ).scalar_one()
                submission = await _capture_submission(
                    conn,
                    artifacts=artifacts,
                    workspace_id=seeded.workspace_id,
                    project_id=seeded.project_a.project_id,
                    brand_id=seeded.brand.brand_id,
                    product_id=seeded.product.product_id,
                    client_entity_id=seeded.client_entity_id,
                    label="fleet",
                )

                # Attempt 1 pins vN and dies before card/model work. Background recon then commits
                # vN+1. The reclaimed production task must finish entirely on the original vN.
                original_pin, created = await load_or_create_agent_turn_scope_pin(
                    conn,
                    submission=submission,
                )
                assert created is True
                background = await reverse_profile(
                    conn,
                    ClientInput(
                        name="Production Context Customer",
                        website=(
                            "https://"
                            f"{seeded.workspace_id.removeprefix('production-context-s3-')}.example"
                        ),
                        materials=(
                            VolunteeredMaterial(
                                kind="background_recon",
                                label="fleet vN+1",
                                content="Background recon advanced during the pinned turn.",
                                asserted_fields={
                                    key: f"fleet vN+1 {key}" for key in CLIENT_KNOWLEDGE_FIELDS
                                },
                            ),
                        ),
                    ),
                    workspace_id=seeded.workspace_id,
                    product_id=None,
                    budget_cap_cents=Decimal(0),
                    max_source_tier=0,
                )
                assert original_pin.client_kb_version is not None
                assert background.ref.client_kb_version == original_pin.client_kb_version + 1

                await dispatch_next_thread_turn(
                    conn,
                    workspace_id=seeded.workspace_id,
                    thread_id=submission.thread_id,
                )
                work_id = ProjectRunId(
                    thread_work_id(
                        workspace_id=seeded.workspace_id,
                        thread_id=submission.thread_id,
                    )
                )
                claimed = await claim_next_task(
                    conn,
                    kind=FleetTaskKind.AGENT_TURN,
                    worker_id="s31-fleet-worker",
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
                    conn_factory=factory,
                    streaming=False,
                )
                result = await handler.handle(
                    WorkContext(
                        task_id=claimed.task_id,
                        work_id=thread_work_id(
                            workspace_id=seeded.workspace_id,
                            thread_id=submission.thread_id,
                        ),
                        worker_id="s31-fleet-worker",
                        lease_generation=claimed.attempts,  # type: ignore[arg-type]
                        payload=claimed.payload,
                        stop_requested=__import__("asyncio").Event(),
                        lease_lost=__import__("asyncio").Event(),
                    )
                )
                assert result.outcome == AgentExecutionStatus.AWAITING_INPUT.value
                assert models.build_count == 1

                pin_row = (
                    (
                        await conn.execute(
                            text(
                                "SELECT client_kb_version, knowledge_scope_policy_version "
                                "FROM agent_turn_scope_pin WHERE turn_id=:turn"
                            ),
                            {"turn": submission.turn_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                assert int(pin_row["client_kb_version"]) == original_pin.client_kb_version

                # L3 receipts point at the exact immutable card artifact fed to the model. The
                # card's domain ref is metadata for governed tools; the assembly receipt retains
                # the stronger byte-level artifact identity. Inspect those actual bytes.
                context_card_key = (
                    await conn.execute(
                        text(
                            "SELECT r.artifact_key FROM agent_context_ref r "
                            "JOIN agent_context_bundle b ON b.id=r.context_bundle_id "
                            "WHERE b.turn_id=:turn AND r.disposition='included' "
                            "AND r.materialized_path='context/project/client_knowledge.json'"
                        ),
                        {"turn": submission.turn_id},
                    )
                ).scalar_one()
                context_card = json.loads(await storage.get(str(context_card_key)))
                assert context_card["client"]["client_kb_version"] == original_pin.client_kb_version
                assert (
                    context_card["compiled_from"]["client_kb_version"]
                    == original_pin.client_kb_version
                )
                assert (
                    context_card["client"]["client_kb_version"] != background.ref.client_kb_version
                )

                stage0_card_key = (
                    await conn.execute(
                        text(
                            "SELECT r.artifact_key FROM agent_context_ref r "
                            "JOIN agent_context_bundle b ON b.id=r.context_bundle_id "
                            "WHERE b.turn_id=:turn AND r.disposition='included' "
                            "AND r.materialized_path="
                            "'context/project/stage0_project_state.json'"
                        ),
                        {"turn": submission.turn_id},
                    )
                ).scalar_one()
                stage0_card = json.loads(await storage.get(str(stage0_card_key)))
                assert {
                    item["quoted_text"]
                    for item in stage0_card["interview"]["current_effective_statements"]
                } == {statement_quote}
                assert (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM agent_artifact_subject "
                            "WHERE workspace_id=:workspace AND artifact_key=:key "
                            "AND subject_entity_id=:statement AND binding_kind=:kind"
                        ),
                        {
                            "workspace": seeded.workspace_id,
                            "key": stage0_card_key,
                            "statement": statement_id,
                            "kind": STAGE0_CARD_QUOTE_BINDING_KIND,
                        },
                    )
                ).scalar_one() == 1

                tool_result_key = (
                    await conn.execute(
                        text(
                            "SELECT r.result_artifact_key FROM agent_tool_result r "
                            "JOIN agent_plan_operation o ON o.operation_id=r.operation_id "
                            "WHERE o.address='list_client_knowledge@2'"
                        )
                    )
                ).scalar_one()
                tool_body = json.loads(await storage.get(str(tool_result_key)))
                assert (
                    tool_body["references"]["client_kb_version"] == original_pin.client_kb_version
                )
                assert (
                    tool_body["references"]["client_kb_version"] != background.ref.client_kb_version
                )

                assert (
                    int(
                        (
                            await conn.execute(
                                text(
                                    "SELECT count(*) FROM checkpoints "
                                    "WHERE thread_id=(SELECT execution_id::text FROM agent_turn "
                                    "WHERE id=:turn)"
                                ),
                                {"turn": submission.turn_id},
                            )
                        ).scalar_one()
                    )
                    >= 1
                )
                assert (
                    int(
                        (
                            await conn.execute(
                                text(
                                    "SELECT count(*) FROM agent_finalization_commit "
                                    "WHERE turn_id=:turn"
                                ),
                                {"turn": submission.turn_id},
                            )
                        ).scalar_one()
                    )
                    == 1
                )

                # Cold replay follows the production runner's committed-outcome short circuit.
                # The exhausted scripted model would fail loudly if replay reached it.
                replayed = await handler._runner.run(  # noqa: SLF001 - production-path acceptance
                    turn_id=submission.turn_id,
                    workspace_id=seeded.workspace_id,
                )
                assert replayed.replayed is True
                assert replayed.outcome.status is AgentExecutionStatus.AWAITING_INPUT
                assert models.build_count == 1
                assert (
                    int(
                        (
                            await conn.execute(
                                text(
                                    "SELECT count(*) FROM agent_finalization_commit "
                                    "WHERE turn_id=:turn"
                                ),
                                {"turn": submission.turn_id},
                            )
                        ).scalar_one()
                    )
                    == 1
                )

                # Statement DSAR now starts from the exact quote embedded by the real fleet path.
                # It reaches the production L3 artifact, its evidence and propagated turn copies,
                # deletes the LangGraph namespace, and makes subsequent replay fail closed.
                erased = await Stage0StatementEraser(
                    privacy=components.privacy,
                    conn_factory=factory,
                ).erase_statement(
                    workspace_id=seeded.workspace_id,
                    statement_id=statement_id,
                )
                assert str(stage0_card_key) in erased.card_artifact_keys
                assert submission.turn_id in erased.erase.affected_turn_ids
                with pytest.raises(ArtifactNotFound):
                    await storage.get(str(stage0_card_key))
                remaining_checkpoint_namespaces = tuple(
                    (
                        await conn.execute(
                            text(
                                "SELECT DISTINCT checkpoint_ns FROM checkpoints "
                                "WHERE thread_id=(SELECT execution_id::text FROM agent_turn "
                                "WHERE id=:turn) ORDER BY checkpoint_ns"
                            ),
                            {"turn": submission.turn_id},
                        )
                    ).scalars()
                )
                assert remaining_checkpoint_namespaces == ()
                blocked_replay = await components.replay.inspect(
                    workspace_id=seeded.workspace_id,
                    turn_id=submission.turn_id,
                )
                assert blocked_replay.replayable is False
                assert any(
                    reason.startswith("artifact_erased:") for reason in blocked_replay.blocker_codes
                )
                assert models.build_count == 1
            finally:
                workspaces.close()

    run_async(scenario())
