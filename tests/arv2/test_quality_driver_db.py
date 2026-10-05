"""Launch -> fleet -> real governed runtime -> durable continuation, without providers."""

import asyncio
import json
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import text

from clue_agents import AgentWorkspaceFactory, ScriptedAgentChatModel, WorkspaceRootPolicy
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.account_research_catalog import arv2_account_profile_sha256
from clue_api.arv2.account_research_driver import Arv2AccountResearchWorkHandler
from clue_api.arv2.account_research_launch import launch_arv2_account_research
from clue_api.arv2.account_research_store import read_job, read_run
from clue_api.arv2.claim_writer import LenientClaimWriter
from clue_api.arv2.display.recipes import load_display_recipes
from clue_api.arv2.page_writer import SECTIONS
from clue_api.arv2.page_writer_runtime import PageWriterModels
from clue_api.arv2.quality_catalog import CURRENT_RECIPE_VERSION
from clue_api.arv2.quality_context import read_context
from clue_api.arv2.quality_execution import Allowance
from clue_api.arv2.quality_pages import read_page
from clue_api.arv2.quality_results import QualityJobOutcome
from clue_api.quality_research_wiring import ResearchUnitRuntime, quality_tools
from clue_fleet import LeaseGeneration, WorkId
from clue_fleet.lease import acquire_work_lease
from clue_fleet.work_worker import WorkContext
from clue_storage.fs import FsStorage
from tests.arv2.icp_fixture import seed_icp_fixture, settings_for
from tests.arv2.test_account_research_driver_db import _Clients
from tests.arv2.test_account_research_launch_db import _request
from tests.arv2.test_quality_context_db import persona
from tests.arv2.test_quality_runtime_db import call
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


class Queue:
    def __init__(self):
        self.offers = {}

    async def enqueue(self, **kwargs):
        key = kwargs["dedup_key"]
        existed = key in self.offers
        self.offers[key] = kwargs
        return not existed


def work(job, run, ws):
    return WorkContext(
        task_id=uuid4(),
        work_id=WorkId(job),
        worker_id="offline-quality",
        lease_generation=LeaseGeneration(1),
        payload={"job_id": str(job), "run_id": str(run), "workspace_id": ws},
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )


def test_launch_pins_persona_and_worker_continuation_preserves_initial_result(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "blobs")
            fixture = await seed_icp_fixture(conn, storage)
            await load_display_recipes(conn)
            first_persona = await persona(
                conn,
                storage,
                fixture,
                source=fixture.icp_document_id,
                sha=fixture.icp_artifact_sha256,
            )
            # Exercise the public default, rather than opting a fixture into v4.
            settings = settings_for(arv2_account_research_enabled=True)
            assert settings.arv2_research_catalog_version == "v4"
            request = _request(fixture, account_entity_ids=(fixture.accounts[0],))
            launch = await launch_arv2_account_research(
                conn,
                request,
                settings=settings,
                storage=storage,
                profile_sha256=arv2_account_profile_sha256(version="v4"),
            )
            run = await read_run(conn, run_id=launch.run_id)
            assert run.context_id and run.persona_pin is None
            await persona(
                conn,
                storage,
                fixture,
                project=fixture.project_id,
                source=fixture.icp_document_id,
                sha=fixture.icp_artifact_sha256,
                path="audience/new-project-persona.md",
            )
            repeat = await launch_arv2_account_research(
                conn,
                request,
                settings=settings,
                storage=storage,
                profile_sha256=arv2_account_profile_sha256(version="v4"),
            )
            assert repeat.replayed and repeat.run_id == launch.run_id
            pinned = await read_context(
                conn,
                storage,
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_id,
                context_id=run.context_id,
            )
            assert pinned.personas[0].document_id == first_persona
            lock = asyncio.Lock()

            @asynccontextmanager
            async def connections():
                async with lock, conn.begin_nested():
                    yield conn

            saver = InMemorySaver()

            @asynccontextmanager
            async def checkpoints(execution_id):
                yield saver

            for name in ("source", "home"):
                (tmp_path / name).mkdir()
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=connections)
            workspaces = AgentWorkspaceFactory(
                prepared_root=WorkspaceRootPolicy(
                    configured_root=tmp_path / "runtime",
                    source_root=tmp_path / "source",
                    home_root=tmp_path / "home",
                ).prepare(),
                artifact_sink=artifacts,
            )
            calls = []
            scopes = []

            class NoLegacyModels:
                def build(self, **kwargs):
                    raise AssertionError("legacy agent must not run for a quality job")

            async def runner(*, scope, context_id, runtime, objective, model_id, unit_key=None):
                calls.append(unit_key)
                scopes.append(scope)
                assert scope.input_refs["quality_recipe_version"] == CURRENT_RECIPE_VERSION
                assert (
                    scope.persona_markdown
                    == "---\nkind: audience-persona\nicp_key: clue-abm-buyers\n"
                    "icp_version: 1\n---\nOperations buyer"
                )

                from langchain_core.messages import ToolMessage

                from clue_api.arv2.evidence_paths import source_path
                from clue_api.arv2.research_operations import OperationScope
                from tests.arv2.test_dossier_json import finding
                from tests.arv2.test_quality_evidence_db import save

                prefix = []
                if unit_key is None:
                    source = await save(
                        conn,
                        storage,
                        OperationScope(
                            scope.workspace_id, scope.run_id, scope.job_id, scope.account_id
                        ),
                        "We keep the original public wording.",
                    )
                    prefix.append(
                        call(
                            "save_dossier_section",
                            {
                                "section": "Voice",
                                "findings": [
                                    finding(
                                        source_paths=[source_path(source.model_dump())],
                                        finding="We keep the original public wording.",
                                    )
                                ],
                            },
                            "save-json",
                        )
                    )
                prefix.append(call("finish_dossier", {}, "import-json"))

                class ReceiptModel(ScriptedAgentChatModel):
                    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                        result = super()._generate(
                            messages, stop=stop, run_manager=run_manager, **kwargs
                        )
                        message = result.generations[0].message
                        if message.tool_calls[0]["id"] == "call-report":

                            def find(value):
                                if isinstance(value, dict):
                                    if value.get("finished") and "claim_ids" in value:
                                        return value["claim_ids"]
                                    for v in value.values():
                                        found = find(v)
                                        if found:
                                            return found
                                return None

                            ids = None
                            for m in reversed(messages):
                                if not isinstance(m, ToolMessage):
                                    continue
                                try:
                                    payload = json.loads(m.content)
                                except ValueError:
                                    continue
                                ids = find(payload)
                                if ids:
                                    break
                            assert ids
                            args = message.tool_calls[0]["args"]
                            report = json.loads(args["content"])
                            report["claim_ids"] = ids
                            args["content"] = json.dumps(report)
                        return result

                class Models:
                    def build(self, **kwargs):
                        return ReceiptModel(
                            responses=prefix
                            + [
                                call(
                                    "read_file", {"file_path": "/research/context.json"}, "context"
                                ),
                                call(
                                    "write_file",
                                    {
                                        "file_path": "outputs/research.json",
                                        "content": json.dumps(
                                            {
                                                "schema_version": "research-unit-v1",
                                                "job_id": str(scope.job_id),
                                                "context_id": str(context_id),
                                                "summary": "Offline integration fixture.",
                                                "gaps": ["No external research in this fixture."],
                                            }
                                        ),
                                    },
                                    "report",
                                ),
                                call(
                                    "finalize_turn",
                                    {
                                        "status": "completed",
                                        "user_message": "Offline unit complete.",
                                    },
                                    "final",
                                ),
                            ]
                        )

                owner = ResearchUnitRuntime(
                    scope=scope,
                    context_id=context_id,
                    settings=settings,
                    storage=storage,
                    connections=connections,
                    models=Models(),
                    workspaces=workspaces,
                    tools=quality_tools(scope, storage, purge=True, acquisition_runtime=runtime),
                    limits=Allowance(15, 25, 2),
                    unit_key=unit_key,
                    checkpointer_factory=checkpoints,
                )
                result = await owner.run(objective=objective)
                return QualityJobOutcome(
                    result.execution_id,
                    result.status.value,
                    result.finalization_ref.artifact_key if result.finalization_ref else None,
                    await owner.report(result),
                    result.failure_code,
                )

            writes = []

            async def writer_model(messages, json_mode):
                writes.append(json_mode)
                if not json_mode:
                    return "The seller sells account-based marketing."
                return json.dumps(
                    {
                        "pages": [
                            {
                                "page": page,
                                "sections": [
                                    {
                                        "key": key,
                                        "intro": [
                                            {
                                                "text": f"Story {len(writes)}.",
                                                "kind": "fact",
                                                "refs": ["F001"],
                                            }
                                        ]
                                        if key == "why-they-fit"
                                        else [],
                                        "items": [],
                                        "gaps": [],
                                    }
                                    for key in SECTIONS[page]
                                ],
                            }
                            for page in ("overview", "insights")
                        ]
                    }
                )

            queue = Queue()
            handler = Arv2AccountResearchWorkHandler(
                settings=settings,
                conn_factory=connections,
                artifacts=artifacts,
                storage=storage,
                clients=_Clients(),
                model_provider=NoLegacyModels(),
                model_id="fixture/research",
                writer=LenientClaimWriter(lenient=True),
                quality_runner=runner,
                page_writer=PageWriterModels(
                    call_for=lambda scope: writer_model, model_id="fixture/writer"
                ),
                queue=queue,
            )
            jid = launch.job_ids[0]
            result = await handler.handle(work(jid, launch.run_id, fixture.workspace_id))
            initial = await read_job(conn, job_id=jid)
            # Recipe 25: the researcher finalizes without pages; the driver's page writer
            # writes them (one seller-brief call, one page call) before the job settles.
            assert result.outcome == "completed", (result, initial.finalization)
            assert writes == [False, True]
            assert initial.finalization["coverage"]["missing_pages"] == []
            assert initial.finalization["coverage"]["published_pages"] == ["insights", "overview"]
            assert initial.finalization["spend"]["unpriced_model_calls"] == 5
            assert initial.finalization["spend"]["cost_complete"] is False
            assert initial.finalization["schema_version"] == "quality-job-v1"
            assert await handler.sweep_quality() == 1
            assert await handler.sweep_quality() == 0
            offer = next(iter(queue.offers.values()))
            assert offer["payload"]["continuation"] == "quality_reconciliation"
            # One live continuation per account lease: while one runs, newer revisions wait for
            # the next sweep instead of queueing siblings that spin on the held lease.
            assert offer["only_if_work_idle"] is True
            assert offer["payload"]["job_id"] == str(jid)
            assert offer["payload"]["run_id"] == str(initial.run_id)
            lease = await acquire_work_lease(
                conn, work_id=WorkId(offer["work_id"]), worker_id="offline-quality"
            )
            assert lease is not None
            continuation = WorkContext(
                task_id=uuid4(),
                work_id=offer["work_id"],
                worker_id="offline-quality",
                lease_generation=lease.generation,
                payload=offer["payload"],
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )
            # Once the people settle, the account is rewritten by the writer (the seller brief is
            # reused), not by continuing the researcher.
            rewrite = await handler.handle(continuation)
            assert rewrite.outcome == "completed" and rewrite.references["applied"] is True
            assert writes == [False, True, True]
            overview = await read_page(conn, scopes[0], context_id=run.context_id, page="overview")
            fit = next(
                s for s in overview["display_block"]["sections"] if s["key"] == "why-they-fit"
            )
            assert fit["intro"][0]["text"] == "Story 3."
            assert (await read_job(conn, job_id=jid)).finalization == initial.finalization
            assert (
                await conn.execute(
                    text(
                        "SELECT state FROM arv2_account_research_generation "
                        "WHERE initial_job_id=:id"
                    ),
                    {"id": jid},
                )
            ).scalar_one() == "reconciled"
            # A redelivered continuation is a no-op: no second rewrite, no researcher call.
            assert (await handler.handle(continuation)).outcome == "completed"
            assert writes == [False, True, True]
            assert len(calls) == 1
            # No legacy Luna display or repeat initial task was offered.
            assert len(queue.offers) == 1
            workspaces.close()

    run_async(case())
