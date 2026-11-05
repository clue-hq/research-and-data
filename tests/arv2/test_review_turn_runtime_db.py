"""Recipe 40: the review turn through the real agent runtime, with a scripted model."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import replace

import deepagents.graph as deep_graph
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import text

from clue_agents import (
    AgentExecutionStatus,
    AgentWorkspaceFactory,
    ScriptedAgentChatModel,
    WorkspaceRootPolicy,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.quality_execution import Allowance
from clue_api.quality_research_wiring import ResearchUnitRuntime, quality_tools
from clue_config import load_settings
from tests.arv2.test_quality_reconciliation_db import fixture
from tests.arv2.test_quality_runtime_db import call
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


class _Models:
    def __init__(self, responses):
        self.responses = responses

    def build(self, **kwargs):
        return ScriptedAgentChatModel(responses=tuple(self.responses))


def _review_script(marker):
    return _Models(
        [
            call("read_file", {"file_path": "/work/review/input.json"}, "read-input"),
            # Finalizing with no brief is refused, and the agent is told to write it.
            call("finalize_turn", {"status": "completed", "user_message": "Done."}, "too-soon"),
            call(
                "write_file",
                {"file_path": "/outputs/page-brief.md", "content": f"Pursue. {marker}"},
                "brief",
            ),
            call("finalize_turn", {"status": "completed", "user_message": marker}, "final"),
        ]
    )


def test_review_resumes_the_conversation_and_writes_the_brief(tmp_path, monkeypatch):
    captured = []
    generate = ScriptedAgentChatModel._generate

    def capture(self, messages, *args, **kwargs):
        captured.append(messages)
        return generate(self, messages, *args, **kwargs)

    monkeypatch.setattr(ScriptedAgentChatModel, "_generate", capture)
    tool_names = []
    create_agent = deep_graph.create_agent

    def spy(*args, **kwargs):
        tool_names.append({getattr(t, "name", "") for t in kwargs.get("tools", ())})
        return create_agent(*args, **kwargs)

    monkeypatch.setattr(deep_graph, "create_agent", spy)

    async def case():
        saver = InMemorySaver()
        async with rollback_conn() as conn:
            scope, _, cid, storage, gen, rev, _ = await fixture(conn, tmp_path)
            scope = replace(scope, input_refs={**scope.input_refs, "quality_recipe_version": 40})
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET input_refs=input_refs || "
                    "jsonb_build_object('quality_recipe_version',40) WHERE job_id=:id"
                ),
                {"id": scope.job_id},
            )
            lock = asyncio.Lock()

            @asynccontextmanager
            async def connections():
                async with lock, conn.begin_nested():
                    yield conn

            @asynccontextmanager
            async def checkpoints(_execution_id):
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

            first_turn = owner(
                _Models(
                    [
                        call(
                            "finalize_turn",
                            {"status": "completed", "user_message": "First-turn memory."},
                            "first-final",
                        )
                    ]
                )
            )
            outcome = await first_turn.run(
                objective="First-turn memory.", model_id="test/account-model"
            )
            assert outcome.status is AgentExecutionStatus.COMPLETED, outcome

            first_review = owner(
                _review_script("First review note."),
                unit_key=f"review:{gen.generation_id}:{rev}",
                review={"people": [{"name": "First input person"}]},
            )
            outcome = await first_review.run(objective="First review note.", model_id="ignored")
            assert outcome.status is AgentExecutionStatus.COMPLETED, outcome
            combined = "\n".join(str(m.content) for batch in captured for m in batch)
            assert "First-turn memory." in combined
            assert "First input person" in combined
            assert "outputs/page-brief.md" in combined  # the refusal names the missing file
            # All the agent's tools, not the old continuation's finalize_turn alone.
            assert {"finalize_turn", "search_evidence", "nominate_web_committee_candidate"} <= (
                tool_names[-1]
            )

            captured.clear()
            second_review = owner(
                _review_script("Second review note."),
                unit_key=f"review:{gen.generation_id}:{rev + 1}",
                review={
                    "people": [{"name": "Second input person"}],
                    "_source_execution": str(first_review.execution_id),
                },
            )
            outcome = await second_review.run(objective="Second review.", model_id="ignored")
            assert outcome.status is AgentExecutionStatus.COMPLETED, outcome
            combined = "\n".join(str(m.content) for batch in captured for m in batch)
            # The second review remembers the first, and reads the new input, not the old file.
            assert "First review note." in combined
            read_results = [
                str(m.content)
                for batch in captured
                for m in batch
                if "input person" in str(m.content)
            ]
            assert any(json.dumps("Second input person") in r for r in read_results)
            workspaces.close()

    run_async(case())
