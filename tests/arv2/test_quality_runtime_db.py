"""Real C5 parent/child research, database and workspace; scripted models never spend."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from langchain_core.messages import AIMessage
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
from clue_storage.fs import FsStorage
from tests.arv2.test_quality_claims_db import assessment, setup
from tests.arv2.test_quality_evidence_db import save
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def call(name, args, index):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"call-{index}", "type": "tool_call"}],
    )


class Models:
    def __init__(self, source):
        self.builds = []
        self.source = source

    def build(self, **kwargs):
        role = kwargs["role"]
        self.builds.append(role)
        if role == "account_research":
            script = [
                call(
                    "delegate_specialist",
                    {
                        "role": "research_claims",
                        "goal": "Map the saved staff count.",
                        "instructions": (
                            "Inspect the original provider record through /evidence/index/0.json. "
                            "Record the supported count and processing receipt."
                        ),
                    },
                    "delegate",
                ),
                call("read_file", {"file_path": "/research/claims/0.json"}, "parent-read"),
                call(
                    "finalize_turn",
                    {"status": "completed", "user_message": "Claim processing completed."},
                    "parent-final",
                ),
            ]
        elif role == "research_claims":
            script = [
                call(
                    "read_file",
                    {"file_path": f"/evidence/{self.source.source_id}/0.json"},
                    "child-read",
                ),
                call(
                    "submit_research_claim",
                    {
                        "proposal": {
                            "operation_key": "staff",
                            "field_key": "core.employee_count",
                            "value": 64,
                            "assessment": assessment().model_dump(mode="json"),
                            "support": [
                                {
                                    "kind": "json",
                                    "source_id": str(self.source.source_id),
                                    "pointer": "/employees",
                                    "expected_value": 64,
                                }
                            ],
                        }
                    },
                    "submit",
                ),
                call(
                    "write_file",
                    {
                        "file_path": "outputs/claim-processing.json",
                        "content": '{"status":"processed","gaps":[]}',
                    },
                    "report",
                ),
                call(
                    "finalize_turn",
                    {
                        "status": "completed",
                        "user_message": "Staff count processed with original provider support.",
                    },
                    "child-final",
                ),
            ]
        else:
            raise AssertionError(f"unexpected model role {role}")
        return ScriptedAgentChatModel(responses=script)


def test_real_parent_delegates_in_slot_and_replays_committed_results(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "blobs")
            op, scope, context_id = await setup(conn, storage)
            source = await save(
                conn, storage, op, {"employees": 64}, kind="provider_record", url=None
            )

            connection_lock = asyncio.Lock()

            @asynccontextmanager
            async def connections():
                async with connection_lock, conn.begin_nested():
                    yield conn

            checkpointer = InMemorySaver()

            @asynccontextmanager
            async def checkpoints(execution_id):
                yield checkpointer

            for directory in ("source", "home"):
                (tmp_path / directory).mkdir(mode=0o700)
            workspaces = AgentWorkspaceFactory(
                prepared_root=WorkspaceRootPolicy(
                    configured_root=tmp_path / "runtime",
                    source_root=tmp_path / "source",
                    home_root=tmp_path / "home",
                ).prepare(),
                artifact_sink=DurableAgentArtifactStore(storage=storage, conn_factory=connections),
            )
            models = Models(source)
            runtime = ResearchUnitRuntime(
                scope=scope,
                context_id=context_id,
                settings=load_settings(_env_file=None),
                storage=storage,
                connections=connections,
                models=models,
                workspaces=workspaces,
                tools=quality_tools(scope, storage, purge=True),
                limits=Allowance(20, 30, 4),
                checkpointer_factory=checkpoints,
            )
            result = await runtime.run(
                objective="Read the complete saved report and delegate faithful claim processing."
            )
            assert result.status is AgentExecutionStatus.COMPLETED, result
            claims = (
                await conn.execute(
                    text(
                        "SELECT c.id,q.conclusion FROM claim c JOIN claim_quality_current q "
                        "ON q.claim_id=c.id WHERE c.workspace_id=:ws"
                    ),
                    {"ws": scope.workspace_id},
                )
            ).all()
            assert len(claims) == 1 and claims[0].conclusion == "supported"
            executions = (
                await conn.execute(
                    text(
                        "SELECT e.role,x.status FROM arv2_quality_execution e "
                        "JOIN execution_cursor x ON x.execution_id=e.execution_id "
                        "WHERE e.job_id=:job ORDER BY e.role"
                    ),
                    {"job": scope.job_id},
                )
            ).all()
            assert [r.role for r in executions] == ["account_research", "research_claims"]
            assert all(r.status == "completed" for r in executions)
            assert models.builds == ["account_research", "research_claims"]
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM agent_delegation_result r JOIN agent_delegation d "
                        "ON d.id=r.delegation_id WHERE d.parent_execution_id=:id"
                    ),
                    {"id": result.execution_id},
                )
            ).scalar_one() == 1
            calls = (
                await conn.execute(
                    text(
                        "SELECT e.role,count(*) AS n FROM agent_model_call m "
                        "JOIN arv2_quality_execution e ON e.execution_id=m.execution_id "
                        "WHERE e.job_id=:job GROUP BY e.role ORDER BY e.role"
                    ),
                    {"job": scope.job_id},
                )
            ).all()
            assert [(r.role, r.n) for r in calls] == [
                ("account_research", 3),
                ("research_claims", 4),
            ]
            second = await runtime.run(
                objective="Read the complete saved report and delegate faithful claim processing."
            )
            # Cold replay returns the committed finalization, without the warm turn's receipts.
            assert second.model_dump(exclude={"operation_receipts"}) == result.model_dump(
                exclude={"operation_receipts"}
            )
            assert models.builds == ["account_research", "research_claims"]

    run_async(case())
