"""Explicit offline acceptance command; real fleet/DB/storage and scripted model decisions.

Run only against a disposable database named clue_arv3_quality_load_*. External provider factories
raise if called. Output contains synthetic IDs/metrics, never customer documents or credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import resource
import sys
import time
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr
from sqlalchemy import text
from sqlalchemy.engine import make_url

from clue_agents import AgentWorkspaceFactory, ScriptedAgentChatModel, WorkspaceRootPolicy
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.account_research_catalog import arv2_account_profile_sha256
from clue_api.arv2.account_research_driver import Arv2AccountResearchWorkHandler
from clue_api.arv2.account_research_launch import (
    enqueue_launched_jobs,
    launch_arv2_account_research,
)
from clue_api.arv2.claim_writer import LenientClaimWriter
from clue_api.arv2.display.recipes import load_display_recipes
from clue_api.arv2.quality_evidence import EvidenceUnavailable, grant_manifest, read_source
from clue_api.arv2.quality_execution import Allowance
from clue_api.arv2.quality_results import QualityJobOutcome
from clue_api.arv2.research_operations import OperationScope
from clue_api.quality_research_wiring import ResearchUnitRuntime, quality_tools
from clue_db import database_url, db_lifespan, transaction
from clue_fleet import DbWorkQueue, FleetTaskKind
from clue_fleet.work_worker import LeasedWorkWorker
from clue_research.claimstore import load_core_pack
from clue_storage.fs import FsStorage
from tests.arv2.icp_fixture import seed_icp_fixture, settings_for
from tests.arv2.test_account_research_driver_db import _Clients
from tests.arv2.test_account_research_launch_db import _request
from tests.arv2.test_quality_evidence_db import save
from tests.arv2.test_quality_runtime_db import Models, call


def find_inputs(value):
    if isinstance(value, dict):
        if "dependency_sha256" in value:
            return value
        return next((r for v in value.values() if (r := find_inputs(v))), None)
    return None


class PageModel(ScriptedAgentChatModel):
    _page: str = PrivateAttr(default="")
    _retry_read: bool = PrivateAttr(default=False)
    _retries: int = PrivateAttr(default=0)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        latest = next((m for m in reversed(messages) if isinstance(m, ToolMessage)), None)
        if latest and latest.name == "publish_research_page":
            receipt = json.loads(latest.content)
            refs = receipt.get("reference_values", receipt.get("references", {}))
            if refs.get("status") == "refused":
                # Follow the real specialist's recovery contract. This fixture must not claim
                # success after a refused publication while concurrent child results arrive.
                assert refs.get("recovery", "").startswith("stale_page_inputs"), refs
                self._retries += 1
                assert self._retries <= 4, refs
                self._retry_read = True
                return ChatResult(
                    generations=[
                        ChatGeneration(
                            message=call(
                                "read_research_page_inputs",
                                {"page": self._page},
                                f"retry-inputs-{self._page}-{self._retries}",
                            )
                        )
                    ]
                )
        if self._retry_read:
            self._retry_read = False
            result = ChatResult(
                generations=[
                    ChatGeneration(
                        message=call(
                            "publish_research_page",
                            {"page": self._page},
                            f"retry-publish-{self._page}-{self._retries}",
                        )
                    )
                ]
            )
        else:
            result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        message = result.generations[0].message
        if message.tool_calls and message.tool_calls[0]["name"] == "publish_research_page":
            latest = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
            inputs = find_inputs(json.loads(latest.content))
            assert inputs, latest.content
            self._page = message.tool_calls[0]["args"]["page"]
            draft = {
                "page": message.tool_calls[0]["args"]["page"],
                "expected_dependency_sha256": inputs["dependency_sha256"],
                "sections": [
                    {
                        "key": key,
                        "gaps": ["Synthetic load case; substantive research not assessed."],
                    }
                    for key in inputs["section_keys"]
                ],
            }
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=call(
                            "publish_research_page", {"draft": draft}, message.tool_calls[0]["id"]
                        )
                    )
                ]
            )
        return result


class LoadModels(Models):
    def __init__(self, source, scope, context_id, people, unit_key):
        super().__init__(source, scope, context_id)
        self.people, self.unit_key = people, unit_key

    def build(self, **kwargs):
        role = kwargs["role"]
        if role == "research_claims":
            return super().build(**kwargs)
        if role == "research_narrative":
            pages = ["contact"] if self.scope.person_subject_id else ["overview", "insights"]
            script = []
            for page in pages:
                script += [
                    call("read_research_page_inputs", {"page": page}, f"inputs-{page}"),
                    call("publish_research_page", {"page": page}, f"publish-{page}"),
                ]
            script += [
                call(
                    "write_file",
                    {
                        "file_path": "outputs/research-narrative.json",
                        "content": '{"status":"published","gaps":["Synthetic load case"]}',
                    },
                    "out",
                ),
                call(
                    "finalize_turn", {"status": "completed", "user_message": "Pages saved."}, "end"
                ),
            ]
            return PageModel(responses=script)
        assert role == "account_research"
        script = [call("read_file", {"file_path": "/research/context.json"}, "context")]
        if not self.scope.person_subject_id and not self.unit_key:
            for index, (source, name, body) in enumerate(self.people):
                script.append(
                    call(
                        "nominate_web_committee_candidate",
                        {
                            "name": name,
                            "source": {
                                "source_id": str(source.source_id),
                                "start": 0,
                                "end": len(body),
                                "quote": body,
                            },
                            "persona_key": "operations",
                            "role": "champion",
                            "organization_scope": {
                                "relationship": "exact_company",
                                "geography": "global",
                                "location_relevance": "supporting",
                                "rationale": "Verify company remit.",
                            },
                            "rationale": "Discovery gap; affiliation unverified.",
                        },
                        f"person-{index}",
                    )
                )
            script.append(
                call(
                    "delegate_specialist",
                    {
                        "role": "research_claims",
                        "goal": "Process saved provider count.",
                        "instructions": "Read the provider count and write a supported claim.",
                    },
                    "claim-child",
                )
            )
        script += [
            call(
                "delegate_specialist",
                {
                    "role": "research_narrative",
                    "goal": "Publish scoped pages.",
                    "instructions": "Read current inputs and publish explicit gaps.",
                },
                "page-child",
            ),
            call(
                "write_file",
                {
                    "file_path": "outputs/research.json",
                    "content": json.dumps(
                        {
                            "schema_version": "research-unit-v1",
                            "job_id": str(self.scope.job_id),
                            "context_id": str(self.context_id),
                            "summary": "Synthetic offline load unit.",
                            "gaps": ["Synthetic load case, not a model-quality assessment."],
                        }
                    ),
                },
                "output",
            ),
            call("finalize_turn", {"status": "completed", "user_message": "Unit recorded."}, "end"),
        ]
        return ScriptedAgentChatModel(responses=script)


async def database_metrics(conn):
    """Read-only collector: also usable after an interrupted report-writing process."""
    counts = {}
    for table in (
        "arv2_research_job",
        "arv2_generation_child",
        "arv2_quality_execution",
        "claim_quality_current",
        "arv2_research_page_current",
        "agent_model_call",
        "provider_call_ledger",
    ):
        counts[table] = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
    bytes_ = (
        await conn.execute(text("SELECT COALESCE(sum(size_bytes),0) FROM artifact"))
    ).scalar_one()
    unresolved = (
        await conn.execute(
            text(
                "SELECT count(*) FROM arv2_account_research_generation "
                "WHERE input_revision>reconciled_revision"
            )
        )
    ).scalar_one()
    queue_rows = (await conn.execute(text("SELECT payload_json FROM fleet_task"))).scalars()
    queue_payloads = [json.dumps(value, sort_keys=True) for value in queue_rows]
    allowed_payload_keys = {
        "job_id",
        "run_id",
        "workspace_id",
        "project_id",
        "account_id",
        "continuation",
        "generation_id",
        "input_revision",
        "traceparent",
        "tracestate",
    }
    # Durable work carries references, never the provider report or contact profiles.
    assert all(set(json.loads(value)) <= allowed_payload_keys for value in queue_payloads)
    unpriced_models = (
        await conn.execute(text("SELECT count(*) FROM agent_model_call WHERE cost_usd IS NULL"))
    ).scalar_one()
    orphan_models = (
        await conn.execute(
            text(
                "SELECT count(*) FROM agent_model_call m "
                "LEFT JOIN arv2_quality_execution q "
                "ON q.execution_id=m.execution_id AND q.workspace_id=m.workspace_id "
                "WHERE q.execution_id IS NULL"
            )
        )
    ).scalar_one()
    return {
        "counts": counts,
        "artifact_bytes": int(bytes_),
        "unreconciled_generations": unresolved,
        "maximum_queue_payload_bytes": max(map(len, queue_payloads), default=0),
        "unpriced_model_calls": unpriced_models,
        "model_calls_without_research_execution": orphan_models,
    }


async def run(output: Path, accounts: int, workers: int, concurrency: int):
    assert (make_url(database_url()).database or "").startswith("clue_arv3_quality_load_")
    output.mkdir(parents=True, exist_ok=True)
    storage = FsStorage(output / "blobs")
    settings = settings_for(arv2_account_research_enabled=True).model_copy(
        # Five logical workers share one handler in this process. Give that shared semaphore
        # their aggregate capacity rather than accidentally applying one process's default cap.
        update={
            "arv2_research_catalog_version": "v4",
            "arv2_account_max_parallel_jobs": workers * concurrency,
        }
    )
    start = time.monotonic()
    scopes, sources, launches, completed = {}, {}, [], []
    active, maximum, child_builds = 0, 0, Counter()
    failures = []
    tag = uuid4().hex[:10]
    async with db_lifespan():
        async with transaction() as conn:
            await load_core_pack(conn)
            await load_display_recipes(conn)
        # Two projects in each of two tenants, at least 50 unique accounts per tenant.
        for tenant in range(2):
            for project in range(2):
                count = accounts // 2 + (accounts % 2 if project == 0 else 0)
                async with transaction() as conn:
                    user = f"quality_{tag}_{tenant}_{project}"
                    fixture = await seed_icp_fixture(
                        conn,
                        storage,
                        workspace_id=f"ws_quality_load_{tag}_{tenant}",
                        user_id=user,
                        document_path=f"audience/icp-{tenant}-{project}.md",
                        account_records=tuple(
                            (
                                f"Synthetic {tenant}-{project}-{i}",
                                f"t{tenant}-p{project}-a{i}.example.test",
                            )
                            for i in range(count)
                        ),
                    )
                    launch = await launch_arv2_account_research(
                        conn,
                        _request(fixture, requested_by_user_id=user),
                        settings=settings,
                        storage=storage,
                        profile_sha256=arv2_account_profile_sha256(version="v4"),
                    )
                    launches.append(launch)
        queue = DbWorkQueue()
        for folder in ("source", "home"):
            (output / folder).mkdir(exist_ok=True)
        artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=transaction)
        workspaces = AgentWorkspaceFactory(
            prepared_root=WorkspaceRootPolicy(
                configured_root=output / "runtime",
                source_root=output / "source",
                home_root=output / "home",
            ).prepare(),
            artifact_sink=artifacts,
        )

        async def runner(*, scope, context_id, runtime, objective, model_id, unit_key=None):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                op = OperationScope(
                    scope.workspace_id, scope.run_id, scope.job_id, scope.account_id
                )
                people = []
                async with transaction() as conn:
                    source = await save(
                        conn,
                        storage,
                        op,
                        {"employees": 64, "fixture_account": str(scope.account_id)},
                        kind="provider_record",
                        url=None,
                    )
                    if not scope.person_subject_id and not unit_key:
                        for i in range(2):
                            name = f"Synthetic Person {scope.account_id.hex[:10]} {i}"
                            body = f"{name} leads operations at {scope.account_name}."
                            person = await save(
                                conn,
                                storage,
                                op,
                                body,
                                url=f"https://{scope.account_domain}/team/{i}",
                            )
                            people.append((person, name, body))
                    scopes[scope.job_id], sources[scope.job_id] = op, source
                saver = InMemorySaver()

                @asynccontextmanager
                async def checkpoints(execution_id):
                    yield saver

                models = LoadModels(source, scope, context_id, people, unit_key)
                owner = ResearchUnitRuntime(
                    scope=scope,
                    context_id=context_id,
                    settings=settings,
                    storage=storage,
                    connections=transaction,
                    models=models,
                    workspaces=workspaces,
                    tools=quality_tools(scope, storage, purge=True, acquisition_runtime=runtime),
                    limits=Allowance(120, 160, 16),
                    unit_key=unit_key,
                    checkpointer_factory=checkpoints,
                )
                result = await owner.run(objective=objective)
                if result.status.value != "completed":
                    failures.append({"job_id": str(scope.job_id), "failure": result.failure_code})
                child_builds.update(models.builds)
                completed.append(
                    {
                        "workspace": scope.workspace_id,
                        "job": str(scope.job_id),
                        "continuation": bool(unit_key),
                        "elapsed_s": round(time.monotonic() - start, 3),
                    }
                )
                return QualityJobOutcome(
                    result.execution_id,
                    result.status.value,
                    result.finalization_ref.artifact_key if result.finalization_ref else None,
                    await owner.report(result),
                    result.failure_code,
                )
            finally:
                active -= 1

        handler = Arv2AccountResearchWorkHandler(
            settings=settings,
            conn_factory=transaction,
            artifacts=artifacts,
            storage=storage,
            clients=_Clients(),
            model_provider=None,
            model_id="fixture/offline",
            writer=LenientClaimWriter(lenient=True),
            quality_runner=runner,
            queue=queue,
        )
        # Interleave tenant offers without changing the production queue's FIFO scheduler.
        for entries in zip(*(launch.to_enqueue for launch in launches), strict=False):
            for entry, launch in zip(entries, launches, strict=True):
                await enqueue_launched_jobs(queue, replace(launch, to_enqueue=(entry,)))
        fleet = [
            LeasedWorkWorker(
                handlers=(handler,),
                queue=queue,
                worker_id=f"quality-{tag}-{i}",
                concurrency=concurrency,
                poll_interval=0.03,
            )
            for i in range(workers)
        ]
        tasks = [asyncio.create_task(w.run()) for w in fleet]
        restarted = False
        try:
            async with asyncio.timeout(1800):
                while True:
                    await handler.sweep_quality()
                    async with transaction() as conn:
                        pending = (
                            await conn.execute(
                                text(
                                    "SELECT count(*) FROM fleet_task "
                                    "WHERE kind=:kind AND status IN ('queued','claimed')"
                                ),
                                {"kind": FleetTaskKind.ARV2_ACCOUNT_RESEARCH.value},
                            )
                        ).scalar_one()
                        jobs = (
                            await conn.execute(
                                text(
                                    "SELECT status,count(*) FROM arv2_research_job GROUP BY status"
                                )
                            )
                        ).all()
                    if not restarted and len(completed) >= workers * concurrency:
                        # Lose warm model/checkpoint state at a committed-unit boundary. The DB
                        # queue and durable outputs are consumed by replacement workers.
                        for worker in fleet:
                            worker.stop()
                        await asyncio.gather(*tasks)
                        workspaces = AgentWorkspaceFactory(
                            prepared_root=WorkspaceRootPolicy(
                                configured_root=output / "cold-runtime",
                                source_root=output / "source",
                                home_root=output / "home",
                            ).prepare(),
                            artifact_sink=artifacts,
                        )
                        fleet = [
                            LeasedWorkWorker(
                                handlers=(handler,),
                                queue=queue,
                                worker_id=f"quality-cold-{tag}-{i}",
                                concurrency=concurrency,
                                poll_interval=0.03,
                            )
                            for i in range(workers)
                        ]
                        tasks = [asyncio.create_task(w.run()) for w in fleet]
                        restarted = True
                    if not pending and active == 0:
                        break
                    if any(task.done() and task.exception() for task in tasks):
                        raise RuntimeError("fleet worker died")
                    await asyncio.sleep(1)
        finally:
            for worker in fleet:
                worker.stop()
            await asyncio.gather(*tasks)
        runtime_metrics = {
            "max_active_research_units": maximum,
            "cold_restart": restarted,
            "elapsed_s": round(time.monotonic() - start, 3),
            "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            * (1 if sys.platform == "darwin" else 1024),
            "failed_agent_units": failures,
            "completion_order": completed,
        }
        (output / "runtime-metrics.json").write_text(json.dumps(runtime_metrics, indent=2))
        async with transaction() as conn:
            # All grants are reconstructed; guessed foreign IDs cannot authorize a read.
            selected = list(scopes)
            denied = 0
            for jid in selected[:20]:
                foreign = next(
                    k for k in selected if scopes[k].workspace_id != scopes[jid].workspace_id
                )
                grant = await grant_manifest(conn, scopes[jid], consumer_id=uuid4())
                try:
                    await read_source(conn, storage, grant, sources[foreign].source_id)
                except EvidenceUnavailable:
                    denied += 1
                else:
                    raise AssertionError("cross-tenant evidence read succeeded")
            db = await database_metrics(conn)
        result = {
            "schema": "quality-offline-load-v1",
            "accounts_per_workspace": accounts,
            "workspaces": 2,
            "projects": 4,
            "workers": workers,
            "concurrency_per_worker": concurrency,
            "max_active_research_units": maximum,
            "effective_handler_capacity": workers * concurrency,
            "cold_restart": restarted,
            "cross_workspace_denials": denied,
            "elapsed_s": round(time.monotonic() - start, 3),
            "process_peak_rss_bytes": runtime_metrics["process_peak_rss_bytes"],
            **db,
            "jobs": dict(jobs),
            "failed_agent_units": failures,
            "completion_order": completed,
            "limitations": [
                "Scripted models; no factual-quality or provider-rate proof.",
                "Cold restart at unit boundary; interruption tested separately.",
                "Workers share one Python process, each has independent leases and capacity.",
            ],
        }
        (output / "report.json").write_text(json.dumps(result, indent=2))
        counts = db["counts"]
        assert counts["arv2_research_job"] == accounts * 2 * 3, result
        assert counts["arv2_generation_child"] == accounts * 2 * 2, result
        assert counts["arv2_research_page_current"] == accounts * 2 * 4, result
        assert (
            maximum <= workers * concurrency
            and restarted
            and not failures
            and not db["unreconciled_generations"]
        ), result
        assert counts["provider_call_ledger"] == 0, result
        assert not db["model_calls_without_research_execution"], result
        assert db["unpriced_model_calls"] == counts["agent_model_call"], result
        print(json.dumps({k: v for k, v in result.items() if k != "completion_order"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--accounts", type=int, default=50)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(run(args.output.resolve(), args.accounts, args.workers, args.concurrency))
