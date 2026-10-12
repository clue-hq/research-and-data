"""Real C5 parent/child research, database and workspace; scripted models never spend."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import replace

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
from clue_api.arv2.account_research_catalog import RESEARCH_PROVIDER_POLICY
from clue_api.arv2.evidence_paths import source_path
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
    def __init__(self, source, scope, context_id, *, repair=False):
        self.repair = repair
        self.builds = []
        self.source = source
        self.scope, self.context_id = scope, context_id

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
                            "Inspect the original provider record through /evidence/index.json. "
                            "Record the supported count and processing receipt."
                        ),
                    },
                    "delegate",
                ),
                call("read_file", {"file_path": "/research/claims/0.json"}, "parent-read"),
                call(
                    "write_file",
                    {
                        "file_path": "outputs/research.json",
                        "content": json.dumps(
                            {
                                "schema_version": "research-unit-v1",
                                "job_id": str(self.scope.job_id),
                                "context_id": str(self.context_id),
                                "summary": "Supported staff count recorded.",
                                "gaps": [
                                    "This scripted fixture only processes the saved staff record."
                                ],
                            }
                        ),
                    },
                    "root-report",
                ),
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
                    {"file_path": source_path(self.source.model_dump())},
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
        if (
            role == "research_claims"
            and (self.scope.input_refs or {}).get("quality_recipe_version", 5) >= 6
        ):
            script[1] = call(
                "record_research_finding",
                {
                    **(
                        {"operation_key": "staff"}
                        if (self.scope.input_refs or {}).get("quality_recipe_version", 5) < 15
                        else {}
                    ),
                    "topic": "Staff count",
                    "finding": "64 employees",
                    **(
                        {"source_paths": [source_path(self.source.model_dump())]}
                        if (self.scope.input_refs or {}).get("quality_recipe_version", 5) >= 14
                        else {"source_ids": [str(self.source.source_id)]}
                    ),
                },
                "submit",
            )
        if (self.scope.input_refs or {}).get("quality_recipe_version", 5) >= 13:
            if role == "account_research":
                script.insert(
                    0,
                    call(
                        "write_file",
                        {
                            "file_path": "/outputs/account-dossier.md",
                            "content": (
                                "# Account findings\n\n64 employees. Source: "
                                f"{source_path(self.source.model_dump())}\n"
                            ),
                        },
                        "dossier",
                    ),
                )
            elif role == "research_claims":
                script.insert(
                    0,
                    call(
                        "read_file",
                        {
                            "file_path": "/research/account-dossier/1.json",
                        },
                        "dossier-read",
                    ),
                )
        if self.repair and role == "research_claims":
            import hashlib

            position = next(
                i
                for i, m in enumerate(script)
                if m.tool_calls[0]["name"] == "record_research_finding"
            )
            base = script[position].tool_calls[0]["args"]
            failed, corrected = [], []
            for i in range(7):
                call_id = f"call-invalid-{i}"
                args = {**base, "topic": f"Finding {i}"}
                failed.append(
                    {
                        "name": "record_research_finding",
                        "id": call_id,
                        "args": {**args, "source_paths": ["/evidence/nonexistent.json"]},
                        "type": "tool_call",
                    }
                )
                key = (
                    "agent_record_research_finding_"
                    + hashlib.sha256(call_id.encode()).hexdigest()[:24]
                )
                corrected.append(
                    {
                        "name": "record_research_finding",
                        "id": f"call-fixed-{i}",
                        "args": {**args, "retry_of": [key]},
                        "type": "tool_call",
                    }
                )
            script[position : position + 1] = [
                AIMessage(content="", tool_calls=failed),
                AIMessage(content="", tool_calls=corrected),
            ]
        return ScriptedAgentChatModel(responses=script)


@pytest.mark.parametrize(
    "revision,repair", [(v, False) for v in [5, 6, 9, 11, 13, 14, 15]] + [(15, True)]
)
def test_real_parent_delegates_in_slot_and_replays_committed_results(
    tmp_path, revision, repair, monkeypatch
):
    original_generate = ScriptedAgentChatModel._generate
    seen_prompts = []

    def capture(self, messages, *args, **kwargs):
        seen_prompts.append("\n".join(str(message.content) for message in messages))
        return original_generate(self, messages, *args, **kwargs)

    monkeypatch.setattr(ScriptedAgentChatModel, "_generate", capture)

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "blobs")
            op, scope, context_id = await setup(conn, storage)
            scope = replace(
                scope, catalog_version="v4", input_refs={"quality_recipe_version": revision}
            )
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
            models = Models(source, scope, context_id, repair=repair)
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
            # Step audit files expire after the configured retention (founder ruling 2026-10-12).
            assert runtime.artifacts.step_retention_days == 90
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
            assert len(claims) == (7 if repair else 1)
            assert all(c.conclusion == "supported" for c in claims)
            if repair:
                events = (
                    (
                        await conn.execute(
                            text(
                                "SELECT event_type FROM execution_event WHERE execution_id IN "
                                "(SELECT execution_id FROM arv2_quality_execution "
                                "WHERE job_id=:job)"
                            ),
                            {"job": scope.job_id},
                        )
                    )
                    .scalars()
                    .all()
                )
                assert events.count("node.failed") == 7
                assert events.count("node.recovered") == 7
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
                ("account_research", 5 if revision >= 13 else 4),
                ("research_claims", (5 if revision >= 13 else 4) + int(repair)),
            ]
            second = await runtime.run(
                objective="Read the complete saved report and delegate faithful claim processing."
            )
            # Cold replay returns the committed finalization, without the warm turn's receipts.
            assert second.model_dump(exclude={"operation_receipts"}) == result.model_dump(
                exclude={"operation_receipts"}
            )
            assert models.builds == ["account_research", "research_claims"]
            assert len(seen_prompts) == (10 if revision >= 13 else 8) + int(repair)
            assert all(RESEARCH_PROVIDER_POLICY in prompt for prompt in seen_prompts)
            parameters = (
                (
                    await conn.execute(
                        text("""SELECT n.parameter_artifact_key FROM execution_node n
                    JOIN arv2_quality_execution q ON q.execution_id=n.execution_id
                    WHERE q.job_id=:job AND n.tool_name=:tool"""),
                        {
                            "job": scope.job_id,
                            "tool": "record_research_finding"
                            if revision >= 6
                            else "submit_research_claim",
                        },
                    )
                )
                .scalars()
                .all()
            )
            assert parameters
            await conn.execute(
                text(
                    "UPDATE artifact SET privacy_erased=true,erased_at=now() WHERE storage_key=:key"
                ),
                {"key": source.artifact_key},
            )
            assert result.finalization_ref is not None
            erased = (
                await conn.execute(
                    text("SELECT erased_at FROM artifact WHERE storage_key=:key"),
                    {"key": result.finalization_ref.artifact_key},
                )
            ).scalar_one()
            assert erased is not None
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM artifact WHERE storage_key=ANY(:keys) "
                        "AND privacy_erased"
                    ),
                    {"keys": parameters},
                )
            ).scalar_one() == len(set(parameters))
            from clue_storage import ArtifactNotFound

            with pytest.raises(ArtifactNotFound):
                await runtime.artifacts.read(result.finalization_ref)

    run_async(case())


class PageModels:
    """Deterministic model responds to real tool receipts; never predicts DB identifiers."""

    def __init__(self, scope, cid, claim_id):
        self.scope, self.cid, self.claim_id = scope, cid, claim_id
        self.builds = []

    def build(self, **kwargs):
        role = kwargs["role"]
        self.builds.append(role)
        if role == "account_research":
            return ScriptedAgentChatModel(
                responses=[
                    call(
                        "delegate_specialist",
                        {
                            "role": "research_narrative",
                            "goal": "Publish the supported account page.",
                            "instructions": (
                                "Read exact context and page dependencies. Publish the overview "
                                "with a supported finding and explicit gaps."
                            ),
                        },
                        "delegate-page",
                    ),
                    call(
                        "write_file",
                        {
                            "file_path": "outputs/research.json",
                            "content": json.dumps(
                                {
                                    "schema_version": "research-unit-v1",
                                    "job_id": str(self.scope.job_id),
                                    "context_id": str(self.cid),
                                    "summary": "Published the scoped overview.",
                                    "claim_ids": [str(self.claim_id)],
                                    "gaps": ["No committee researched in this fixture"],
                                }
                            ),
                        },
                        "root-report",
                    ),
                    call(
                        "finalize_turn",
                        {"status": "completed", "user_message": "Page published."},
                        "root-final",
                    ),
                ]
            )
        assert role == "research_narrative"
        claim_id = self.claim_id

        class PageModel(ScriptedAgentChatModel):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                from langchain_core.messages import ToolMessage
                from langchain_core.outputs import ChatGeneration, ChatResult

                result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
                message = result.generations[0].message
                if message.tool_calls and message.tool_calls[0]["name"] == "publish_research_page":
                    receipt = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
                    payload = json.loads(receipt.content)

                    def find(value):
                        if isinstance(value, dict):
                            if "dependency_sha256" in value:
                                return value
                            for v in value.values():
                                found = find(v)
                                if found:
                                    return found
                        return None

                    current = find(payload)
                    assert current, payload
                    draft = {
                        "page": "overview",
                        "expected_dependency_sha256": current["dependency_sha256"],
                        "sections": [
                            {
                                "key": key,
                                "intro": [
                                    {
                                        "text": "Manual referral entry creates work.",
                                        "kind": "fact",
                                        "claimIds": [str(claim_id)],
                                    }
                                ]
                                if key == "why-they-fit"
                                else [],
                                "gaps": []
                                if key == "why-they-fit"
                                else ["Not established by saved evidence"],
                            }
                            for key in current["section_keys"]
                        ],
                    }
                    return ChatResult(
                        generations=[
                            ChatGeneration(
                                message=call("publish_research_page", {"draft": draft}, "publish")
                            )
                        ]
                    )
                return result

        return PageModel(
            responses=[
                call("read_file", {"file_path": "/research/context.json"}, "read-context"),
                call("read_research_page_inputs", {"page": "overview"}, "page-inputs"),
                call("publish_research_page", {}, "template"),
                call(
                    "write_file",
                    {
                        "file_path": "outputs/research-narrative.json",
                        "content": '{"status":"published","gaps":["Committee not researched"]}',
                    },
                    "page-output",
                ),
                call(
                    "finalize_turn",
                    {"status": "completed", "user_message": "Overview published with gaps."},
                    "page-final",
                ),
            ]
        )


def test_real_narrative_child_publishes_into_contextual_page(tmp_path):
    async def case():
        from uuid import uuid4

        from clue_api.arv2.quality_claims import ClaimProposal, submit_proposal
        from clue_api.arv2.quality_evidence import TextSupport, grant_manifest
        from clue_api.arv2.quality_pages import read_page
        from tests.arv2.test_quality_pages_db import clinical_context

        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "blobs")
            op, scope, _, cid, _, _ = await clinical_context(conn, storage)
            source = await save(conn, storage, op, "Manual referral entry creates work.")
            grant = await grant_manifest(conn, op, consumer_id=uuid4())
            claim = await submit_proposal(
                conn,
                storage,
                scope,
                grant,
                ClaimProposal(
                    operation_key="manual-entry",
                    field_key="account.operational_pain",
                    value="Manual referral entry",
                    assessment=assessment(),
                    support=(
                        TextSupport(
                            source_id=source.source_id,
                            start=0,
                            end=35,
                            quote="Manual referral entry creates work.",
                        ),
                    ),
                ),
                context_id=cid,
                actor_ref="offline-claim-specialist",
            )
            assert claim.status == "supported", claim
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
            models = PageModels(scope, cid, claim.claim_id)
            runtime = ResearchUnitRuntime(
                scope=scope,
                context_id=cid,
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
                objective="Delegate page synthesis with exact claims and gaps."
            )
            assert result.status is AgentExecutionStatus.COMPLETED, result
            visible = await read_page(conn, scope, context_id=cid, page="overview")
            assert visible["cited_claim_ids"] == (str(claim.claim_id),)
            assert not visible["research_quality"]["refreshPending"], visible
            assert models.builds == ["account_research", "research_narrative"]
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM agent_model_call WHERE execution_id=:id"),
                    {"id": result.execution_id},
                )
            ).scalar_one() == 3
            replay = await runtime.run(
                objective="Delegate page synthesis with exact claims and gaps."
            )
            assert replay.execution_id == result.execution_id
            assert models.builds == ["account_research", "research_narrative"]
            workspaces.close()

    run_async(case())
