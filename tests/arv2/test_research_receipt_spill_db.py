"""Large real dossier imports finish/recover through C5 with all tool spans retained."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import text

from clue_agents import (
    AgentExecutionStatus,
    AgentWorkspaceFactory,
    ScriptedAgentChatModel,
    WorkspaceRootPolicy,
)
from clue_agents.workspace import AnchoredAgentWorkspaceBackend
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.evidence_paths import source_path
from clue_api.arv2.quality_execution import Allowance
from clue_api.quality_research_wiring import ResearchUnitRuntime, quality_tools
from clue_config import Settings
from clue_storage.fs import FsStorage
from tests._langfuse import finished_spans, langfuse_installed
from tests.arv2.test_dossier_json import finding
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_evidence_db import save
from tests.arv2.test_quality_runtime_db import call
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_large_dossier_import_replay_and_finalization_are_lossless_and_traced(
    tmp_path, monkeypatch
):
    spills = []
    original_spill = AnchoredAgentWorkspaceBackend.write_spill
    original_generate = ScriptedAgentChatModel._generate

    def record_spill(self, operation_id, data):
        path = original_spill(self, operation_id, data)
        # Exercise the real workspace read; the small receipt never replaces these bytes.
        assert self.read_text_sync(path).encode() == data
        spills.append((path, json.loads(data)))
        return path

    def generate(self, *args, **kwargs):
        result = original_generate(self, *args, **kwargs)
        for tool in result.generations[0].message.tool_calls:
            if tool["name"] == "read_file" and tool["args"]["file_path"] == "SPILLED":
                tool["args"]["file_path"] = spills[-1][0]
            if tool["name"] == "write_file":
                report = json.loads(tool["args"]["content"])
                report["claim_ids"] = spills[-1][1]["result"]["claim_ids"]
                tool["args"]["content"] = json.dumps(report)
        return result

    monkeypatch.setattr(AnchoredAgentWorkspaceBackend, "write_spill", record_spill)
    monkeypatch.setattr(ScriptedAgentChatModel, "_generate", generate)

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "blobs")
            op, scope, cid = await setup(conn, storage)
            scope = replace(scope, catalog_version="v4", input_refs={"quality_recipe_version": 19})
            source = await save(conn, storage, op, "A retained public statement.")
            lock = asyncio.Lock()

            @asynccontextmanager
            async def connections():
                async with lock, conn.begin_nested():
                    yield conn

            @asynccontextmanager
            async def checkpoints(execution_id):
                yield InMemorySaver()

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
            entries = [
                finding(f"F{i:03}", source_paths=[source_path(source.model_dump())])
                for i in range(1, 83)
            ]
            script = [
                call(
                    "save_dossier_section", {"section": "Public voice", "findings": entries}, "save"
                ),
                call("finish_dossier", {}, "finish"),
                call("read_file", {"file_path": "SPILLED"}, "read-receipt"),
                call("finish_dossier", {}, "replay"),
                call(
                    "write_file",
                    {
                        "file_path": "outputs/research.json",
                        "content": json.dumps(
                            {
                                "job_id": str(scope.job_id),
                                "context_id": str(cid),
                                "summary": "Fixture imported.",
                            }
                        ),
                    },
                    "report",
                ),
                call(
                    "finalize_turn", {"status": "completed", "user_message": "Imported."}, "final"
                ),
            ]

            class Models:
                def build(self, **kwargs):
                    return ScriptedAgentChatModel(responses=script)

            runtime = ResearchUnitRuntime(
                scope=scope,
                context_id=cid,
                settings=Settings(_env_file=None),
                storage=storage,
                connections=connections,
                models=Models(),
                workspaces=workspaces,
                tools=quality_tools(scope, storage, purge=False),
                limits=Allowance(20, 30, 4),
                checkpointer_factory=checkpoints,
            )
            try:
                outcome = await runtime.run(
                    objective="Import retained fixture findings and finalize."
                )
                assert outcome.status is AgentExecutionStatus.COMPLETED, outcome
                assert spills and all(len(json.dumps(s[1]).encode()) > 16384 for s in spills)
                assert all(len(s[1]["result"]["entries"]) == 82 for s in spills)
                assert len({tuple(s[1]["result"]["claim_ids"]) for s in spills}) == 1
                assert (
                    await conn.execute(
                        text("SELECT count(*) FROM claim WHERE workspace_id=:ws"),
                        {"ws": scope.workspace_id},
                    )
                ).scalar_one() == 82
            finally:
                workspaces.close()

    with langfuse_installed() as (exporter, _):
        run_async(case())
        spans = finished_spans(exporter)
    for name, count in [
        ("save_dossier_section", 1),
        ("finish_dossier", 2),
        ("read_file", 1),
        ("write_file", 1),
        ("finalize_turn", 1),
    ]:
        observed = [s for s in spans if s.name == name]
        assert len(observed) == count, (name, [s.name for s in spans])
        assert all(s.attributes.get("langfuse.observation.type") == "tool" for s in observed)
