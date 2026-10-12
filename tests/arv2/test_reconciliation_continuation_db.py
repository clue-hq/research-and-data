"""Native Deep Agent history continuation, file submission repair, and replay without spend."""

import asyncio
import json
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace

import deepagents.graph as deep_graph
import pytest
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from clue_agents import (
    AgentExecutionStatus,
    AgentWorkspaceFactory,
    ScriptedAgentChatModel,
    WorkspaceRootPolicy,
)
from clue_agents.compaction import ClueSummarizationMiddleware
from clue_agents.tool_result_clearing import BatchedToolResultClearing
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.quality_execution import Allowance
from clue_api.arv2.quality_reconciliation import run_reconciliation
from clue_api.quality_research_wiring import ResearchUnitRuntime, quality_tools
from clue_config import load_settings
from clue_db import database_url
from tests.arv2.test_quality_reconciliation_db import fixture
from tests.arv2.test_quality_runtime_db import call
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


IDENTITY = "You are the account research analyst on the seller's account-based marketing team"


def identity_copies(messages):
    return sum(str(m.content).count(IDENTITY) for m in messages if isinstance(m, SystemMessage))


@pytest.mark.parametrize("recipe", [24, 26])
@pytest.mark.parametrize("compacted", [False, True])
@pytest.mark.parametrize("persistent", [False, True])
def test_account_continues_native_history_repairs_submission_and_replays(
    tmp_path, monkeypatch, compacted, persistent, recipe
):
    captured = []
    generate = ScriptedAgentChatModel._generate

    def capture(self, messages, *args, **kwargs):
        captured.append(messages)
        return generate(self, messages, *args, **kwargs)

    monkeypatch.setattr(ScriptedAgentChatModel, "_generate", capture)
    stacks = []
    create_agent = deep_graph.create_agent

    def spy(*args, **kwargs):
        stacks.append(list(kwargs["middleware"]))
        return create_agent(*args, **kwargs)

    monkeypatch.setattr(deep_graph, "create_agent", spy)
    original_bindings = ResearchUnitRuntime.bindings

    class SavedSummary(AgentMiddleware):
        async def abefore_model(self, state, runtime):
            if not state.get("_summarization_event"):
                return {
                    "_summarization_event": {
                        "cutoff_index": 1,
                        "summary_message": HumanMessage(content="Native retained summary marker."),
                        "file_path": "/work/account-note.md",
                    }
                }
            return None

    async def bindings(self, *args):
        result = await original_bindings(self, *args)
        if compacted and self.reconciliation is None:
            return replace(result, middleware=(*result.middleware, SavedSummary()))
        return result

    monkeypatch.setattr(ResearchUnitRuntime, "bindings", bindings)

    async def case():
        async with AsyncExitStack() as stack:
            if persistent:
                saver = await stack.enter_async_context(
                    AsyncPostgresSaver.from_conn_string(
                        database_url().replace("postgresql+asyncpg://", "postgresql://")
                    )
                )
                await saver.setup()
            else:
                saver = InMemorySaver()
            conn = await stack.enter_async_context(rollback_conn())
            scope, child, cid, storage, gen, rev, _ = await fixture(conn, tmp_path)
            if recipe != 24:
                scope = replace(
                    scope, input_refs={**scope.input_refs, "quality_recipe_version": recipe}
                )
                await conn.execute(
                    text(
                        "UPDATE arv2_research_job SET input_refs=input_refs || "
                        "jsonb_build_object('quality_recipe_version',CAST(:r AS int)) "
                        "WHERE job_id=:id"
                    ),
                    {"r": recipe, "id": scope.job_id},
                )
            lock = asyncio.Lock()

            @asynccontextmanager
            async def connections():
                async with lock, conn.begin_nested():
                    yield conn

            @asynccontextmanager
            async def checkpoints(execution_id):
                yield saver

            for name in ("source", "home"):
                (tmp_path / name).mkdir(mode=0o700)
            workspaces = AgentWorkspaceFactory(
                prepared_root=WorkspaceRootPolicy(
                    configured_root=tmp_path / "workspaces",
                    source_root=tmp_path / "source",
                    home_root=tmp_path / "home",
                ).prepare(),
                artifact_sink=DurableAgentArtifactStore(storage=storage, conn_factory=connections),
            )

            class Models:
                def __init__(self, responses):
                    self.responses, self.builds = responses, []

                def build(self, **kwargs):
                    self.builds.append(kwargs)
                    return ScriptedAgentChatModel(responses=tuple(self.responses))

            initial_models = Models(
                [
                    call(
                        "write_file",
                        {
                            "file_path": "/work/account-note.md",
                            "content": "Retained account memory.",
                        },
                        "note",
                    ),
                    call(
                        "finalize_turn",
                        {"status": "completed", "user_message": "Original account research saved."},
                        "initial-final",
                    ),
                ]
            )

            def owner(models, **kwargs):
                return ResearchUnitRuntime(
                    scope=scope,
                    context_id=cid,
                    settings=load_settings(_env_file=None),
                    storage=storage,
                    connections=connections,
                    models=models,
                    workspaces=workspaces,
                    tools=quality_tools(scope, storage, purge=True),
                    limits=Allowance(100, 100, 10),
                    checkpointer_factory=checkpoints,
                    **kwargs,
                )

            initial = owner(initial_models)
            result = await initial.run(
                objective="Account-specific remembered context: distinctive workflow.",
                model_id="test/account-model",
            )
            assert result.status is AgentExecutionStatus.COMPLETED, result
            source_config = {
                "configurable": {
                    "thread_id": str(initial.execution_id),
                    "checkpoint_ns": "",
                }
            }
            original_checkpoint = await saver.aget_tuple(source_config)
            assert original_checkpoint is not None
            claims_before = (
                await conn.execute(
                    text("SELECT count(*) FROM claim WHERE workspace_id=:ws"),
                    {"ws": scope.workspace_id},
                )
            ).scalar_one()
            replay_models = []

            async def continue_agent(packet):
                person = next(
                    c for c in packet["claims"] if c["entity_id"] == str(child.contact_id)
                )
                valid = (
                    {
                        "updates": [
                            {
                                "page": "overview",
                                "section": {
                                    "key": "why-they-fit",
                                    "intro": [
                                        {
                                            "text": "Their own public statement matters.",
                                            "claimIds": [person["id"]],
                                        }
                                    ],
                                },
                            }
                        ],
                        "notes": [],
                    }
                    if persistent
                    else {"updates": [], "notes": []}
                )
                invalid = {
                    "updates": [
                        {
                            "page": "overview",
                            "title": "Wrong level",
                            "section": {"key": "what-they-do"},
                        }
                    ]
                }
                bad, good = json.dumps(invalid), json.dumps(valid)
                models = Models(
                    [
                        call("read_file", {"file_path": "/work/account-note.md"}, "read-memory"),
                        call(
                            "write_file",
                            {"file_path": "/outputs/reconciliation.json", "content": bad},
                            "invalid",
                        ),
                        call(
                            "finalize_turn",
                            {"status": "completed", "user_message": "Update ready."},
                            "reject",
                        ),
                        call(
                            "edit_file",
                            {
                                "file_path": "/outputs/reconciliation.json",
                                "old_string": bad,
                                "new_string": good,
                            },
                            "repair",
                        ),
                        call(
                            "finalize_turn",
                            {"status": "completed", "user_message": "No useful account changes."},
                            "accepted",
                        ),
                    ]
                )
                replay_models.append(models)
                start_capture = len(captured)
                runtime = owner(
                    models, unit_key=f"reconcile:{gen.generation_id}:{rev}", reconciliation=packet
                )
                outcome = await runtime.run(
                    objective="Continue with person findings; submit reconciliation.",
                    model_id="must-not-replace-original",
                )
                assert outcome.status is AgentExecutionStatus.COMPLETED, outcome
                if compacted:
                    assert "Native retained summary marker." in str(captured[start_capture])
                reply = await runtime.reconciliation_output(outcome)
                calls = len(captured)
                again = await runtime.run(
                    objective="Continue with person findings; submit reconciliation.",
                    model_id="must-not-replace-original",
                )
                assert again == outcome
                assert len(captured) == calls
                assert models.builds[0]["model_id"] == "test/account-model"
                assert models.builds[0]["role"] == "account_research"
                return reply

            result = await run_reconciliation(
                conn_factory=connections,
                storage=storage,
                scope=scope,
                context_id=cid,
                generation_id=gen.generation_id,
                revision=rev,
                generate=continue_agent,
                model="test/account-model",
                stopped=lambda: False,
            )
            assert result
            if persistent:
                from clue_api.arv2.quality_pages import read_page

                page = await read_page(conn, scope, context_id=cid, page="overview")
                assert "Their own public statement matters." in str(page)
            assert len(replay_models) == 1
            # Recipe 26 sends the identity prompt once per request: first turn and continuation.
            assert captured
            copies = {identity_copies(batch) for batch in captured}
            assert copies == {1} if recipe >= 26 else max(copies) >= 2
            # Recipe 26: batched clearing runs outside the summariser, which compacts at 150k.
            assert stacks
            for stack in stacks:
                kinds = [type(m) for m in stack]
                summariser = next(m for m in stack if isinstance(m, ClueSummarizationMiddleware))
                if recipe >= 26:
                    clearing = kinds.index(BatchedToolResultClearing)
                    assert clearing < kinds.index(ClueSummarizationMiddleware)
                    assert summariser._lc_helper.trigger == ("tokens", 240_000)
                else:
                    assert BatchedToolResultClearing not in kinds
                    assert summariser._lc_helper.trigger != ("tokens", 240_000)
            combined = "\n".join(str(m.content) for batch in captured for m in batch)
            assert "distinctive workflow" in combined
            assert "Retained account memory." in combined
            assert "updates.0.title" in combined
            assert "No sections were changed" in combined
            assert (await saver.aget_tuple(source_config)) == original_checkpoint
            claims_after = (
                await conn.execute(
                    text("SELECT count(*) FROM claim WHERE workspace_id=:ws"),
                    {"ws": scope.workspace_id},
                )
            ).scalar_one()
            assert claims_after == claims_before
            workspaces.close()

    run_async(case())
