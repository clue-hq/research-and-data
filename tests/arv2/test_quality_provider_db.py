"""Saved real client receipts feed governed mappings; external transport is deterministic."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import pytest
from deepagents.backends.protocol import BackendProtocol
from sqlalchemy import text

from clue_api.arv2 import research_operations as operations
from clue_api.arv2.account_research_tools import LookupCompanyArgs, _lookup_company
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_mapping import QualityProviderWriter
from clue_api.arv2.quality_provider_tools import AcquireResearchInput, AcquireResearchTool
from clue_api.arv2.quality_views import research_backend
from clue_api.arv2.transport import ScriptedTransport
from clue_config import Settings
from clue_core import ExecutionId, OperationId
from clue_storage import read_verified_artifact
from clue_storage.fs import FsStorage
from clue_toolbelt import ToolContext
from tests.arv2.test_committee_discovery_v2_db import response, runtime
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_execution_db import execution
from tests.arv2.test_quality_tools_db import read_document
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_company_mapping_reuses_exact_claims_and_tool_results_without_purchase(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, cid = await setup(conn, storage)
            scope = replace(scope, catalog_version="v4")
            parent = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=parent,
                context_id=cid,
                role="account_research",
                limits=Allowance(20, 40, 4),
            )
            wire = ScriptedTransport(
                [
                    response(
                        {
                            "content": [
                                {
                                    "id": "exact-company",
                                    "link": {"domain": scope.account_domain},
                                    "summary": {
                                        "name": scope.account_name,
                                        "staff": {"total": 64},
                                        "description": "Provider promotional description.",
                                    },
                                }
                            ]
                        }
                    )
                ]
            )
            rt = runtime(conn, scope, storage, wire)
            rt._writer = QualityProviderWriter(scope, storage, parent, rt.catalog, purge=True)

            @asynccontextmanager
            async def connections():
                yield conn

            ctx = ToolContext(
                workspace_id=scope.workspace_id,
                actor="agent",
                conn_factory=connections,
                execution_id=ExecutionId(parent),
                operation_id=OperationId(uuid4()),
            )
            tool = AcquireResearchTool(rt)
            inputs = AcquireResearchInput(
                operation="lookup_company", arguments={"domain": scope.account_domain}
            )
            result = await tool.invoke(inputs, ctx)
            assert result.references["status"] == "completed", result
            claims = (
                await conn.execute(
                    text("""
              SELECT c.id,c.value_json,q.conclusion FROM claim c
              JOIN claim_quality_current q ON q.claim_id=c.id
              WHERE c.run_id=:run AND c.field_key='core.employee_count'
            """),
                    {"run": scope.run_id},
                )
            ).all()
            assert len(claims) == 1 and claims[0].value_json == 64
            assert claims[0].conclusion == "supported"
            backend = research_backend(
                BackendProtocol(),
                connections,
                storage,
                scope,
                parent,
                capabilities=tool.capabilities(),
            )
            saved = json.loads(await read_document(backend, result.references["result_path"]))
            assert "error" not in saved
            index = await backend.aread("/evidence/index.json")
            originals = [
                await read_document(backend, row["path"])
                for row in json.loads(index.file_data["content"])["sources"]
                if row.get("available")
            ]
            assert originals
            assert all("Provider promotional description." not in body for body in originals)
            # The agent reads a projection; the immutable audit still retains the wire response.
            original_key = (
                await conn.execute(
                    text("""SELECT original_key FROM arv2_evidence_source
                      WHERE run_id=:run AND normalizer_version='ai_ark:enrichment-v2'"""),
                    {"run": scope.run_id},
                )
            ).scalar_one()
            _, audit = await read_verified_artifact(
                conn, storage, workspace_id=scope.workspace_id, storage_key=original_key
            )
            assert "Provider promotional description." in audit.decode()
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM claim WHERE run_id=:run "
                        "AND field_key='core.company_about'"
                    ),
                    {"run": scope.run_id},
                )
            ).scalar_one() == 0
            replay = await tool.invoke(inputs, ctx)
            assert replay.references["replayed"]
            assert replay.references["operation_id"] == result.references["operation_id"]
            # Recompute the mapper from the saved original as a restarted mapping phase would.
            await _lookup_company(rt, LookupCompanyArgs(domain=scope.account_domain))
            assert len(wire.requests) == 1
            ids = (
                (
                    await conn.execute(
                        text(
                            "SELECT id FROM claim WHERE run_id=:run "
                            "AND field_key='core.employee_count'"
                        ),
                        {"run": scope.run_id},
                    )
                )
                .scalars()
                .all()
            )
            assert ids == [claims[0].id]
            # A claimed but unfinished dispatch never causes a second purchase.
            pending_args = {"query": "specific missing fact"}
            await operations.begin(conn, op, "quality_tool:search_web", pending_args)
            unknown = await tool.invoke(
                AcquireResearchInput(operation="search_web", arguments=pending_args), ctx
            )
            assert unknown.references["status"] == "outcome_unknown"
            assert len(wire.requests) == 1

    run_async(case())


def test_provider_refusal_is_visible_and_cannot_be_retried_as_success(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, cid = await setup(conn, storage)
            scope = replace(scope, catalog_version="v4")
            parent = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=parent,
                context_id=cid,
                role="account_research",
                limits=Allowance(20, 40, 4),
            )
            wire = ScriptedTransport([response({"error": "credit unavailable"}, status=402)])
            rt = runtime(conn, scope, storage, wire)
            tool = AcquireResearchTool(rt)

            @asynccontextmanager
            async def connections():
                yield conn

            ctx = ToolContext(
                workspace_id=scope.workspace_id,
                actor="agent",
                conn_factory=connections,
                execution_id=ExecutionId(parent),
                operation_id=OperationId(uuid4()),
            )
            args = AcquireResearchInput(
                operation="lookup_company", arguments={"domain": scope.account_domain}
            )
            result = await tool.invoke(args, ctx)
            assert result.references["status"] == "refused"
            assert result.references["error_code"].startswith("provider_halted")
            assert (await tool.invoke(args, ctx)).references["status"] == "refused"
            assert len(wire.requests) == 1
            child = await execution(conn, op, scope.project_id, parent)
            await bind_execution(
                conn,
                op,
                execution_id=child,
                context_id=cid,
                role="research_claims",
                limits=Allowance(20, 40, 4),
                parent_execution_id=parent,
            )
            with pytest.raises(ValueError, match="through their parent"):
                await tool.invoke(args, replace(ctx, execution_id=ExecutionId(child)))

    run_async(case())


def test_invalid_transcript_reads_are_durable_refusals_without_transport(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, context = await setup(conn, storage)
            scope = replace(scope, catalog_version="v4")
            parent = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=parent,
                context_id=context,
                role="account_research",
                limits=Allowance(20, 40, 4),
            )
            wire = ScriptedTransport([])
            rt = runtime(conn, scope, storage, wire)

            @asynccontextmanager
            async def connections():
                yield conn

            tool = AcquireResearchTool(rt)
            ctx = ToolContext(
                workspace_id=scope.workspace_id,
                actor="agent",
                conn_factory=connections,
                execution_id=ExecutionId(parent),
                operation_id=OperationId(uuid4()),
            )
            args = AcquireResearchInput(
                operation="open_transcript",
                arguments={"version_ref": str(uuid4()), "start": 0, "end": 10},
            )
            first = await tool.invoke(args, ctx)
            second = await tool.invoke(args, ctx)
            assert first.references["status"] == second.references["status"] == "refused"
            assert second.references["replayed"]
            assert not wire.requests

            # Model planning mistakes must not consume the runtime's infrastructure failure
            # budget, and a replay must not redispatch them or acquire any paid material.
            malformed = AcquireResearchInput(operation="research_deep", arguments={"domain": "x"})
            refused = await tool.invoke(malformed, replace(ctx, operation_id=OperationId(uuid4())))
            assert refused.references["status"] == "refused"
            assert refused.references["error_code"] == "invalid_acquisition_arguments"
            assert "/research/capabilities/0.json" in refused.references["recovery"]
            assert (await tool.invoke(malformed, ctx)).references["replayed"]
            del tool.operations["lookup_company"]
            unavailable = AcquireResearchInput(
                operation="lookup_company", arguments={"domain": "x"}
            )
            refused = await tool.invoke(
                unavailable, replace(ctx, operation_id=OperationId(uuid4()))
            )
            assert refused.references["status"] == "refused"
            assert refused.references["error_code"] == "operation_unavailable_for_subject"
            assert (await tool.invoke(unavailable, ctx)).references["replayed"]
            assert not wire.requests

    run_async(case())


@pytest.mark.parametrize("version", ["1", "2"])
def test_account_deep_receipt_links_sources_and_replay_does_not_repurchase(tmp_path, version):
    from clue_api.arv2.quality_provider_tools import AcquireResearchToolV2

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, cid = await setup(conn, storage)
            scope = replace(scope, catalog_version="v4", input_refs={"quality_recipe_version": 8})
            parent = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=parent,
                context_id=cid,
                role="account_research",
                limits=Allowance(20, 40, 4),
            )
            body = {
                "output": {"content": "A substantive report. " * 200},
                "costDollars": {"total": 0.05},
                "results": [
                    {
                        "url": "https://example.test/bdr",
                        "title": "BDR",
                        "highlights": ["The role uses a named sales tool."],
                    }
                ],
            }
            wire = ScriptedTransport([response(body)])
            rt = runtime(conn, scope, storage, wire)

            @asynccontextmanager
            async def connections():
                yield conn

            ctx = ToolContext(
                workspace_id=scope.workspace_id,
                actor="agent",
                conn_factory=connections,
                execution_id=ExecutionId(parent),
                operation_id=OperationId(uuid4()),
            )
            tool = AcquireResearchTool(rt) if version == "1" else AcquireResearchToolV2(rt)
            inputs = AcquireResearchInput(
                operation="research_deep",
                arguments={
                    "charter": "Investigate the company and its operating workflows. " * 8,
                    "additional_queries": ["company leadership"],
                    "num_results": 40,
                },
            )
            result = await tool.invoke(inputs, ctx)
            assert result.references["status"] == "completed", result
            if version == "2":
                # Recipe 26 receipts preview what came back, so no round is spent opening it.
                preview = result.references["preview"]
                assert preview and preview[0]["title"] == "Report"
                assert any(h["url"] == "https://example.test/bdr" for h in preview)
                assert result.references["result_count"]
            else:
                assert "preview" not in result.references
            backend = research_backend(BackendProtocol(), connections, storage, scope, parent)
            saved = json.loads(await read_document(backend, result.references["result_path"]))
            sources = saved["source_navigation"]["sources"]
            assert {r["kind"] for r in sources} == {
                "provider_record",
                "research_report",
                "web_snapshot",
            }
            excerpt = next(r for r in sources if r["kind"] == "web_snapshot")
            assert excerpt["url"] == "https://example.test/bdr"
            assert excerpt["content_kind"] == "highlight"
            assert "named sales tool" in await read_document(backend, excerpt["path"])
            replay = await tool.invoke(inputs, ctx)
            assert replay.references["replayed"] is True
            assert len(wire.requests) == 1

    run_async(case())


@pytest.mark.parametrize("recover_on_success", [False, True])
def test_an_evidence_call_logs_how_long_draining_indexing_and_recovery_took(
    tmp_path, monkeypatch, recover_on_success
):
    """W2-20: the per-call platform steps are timed, so slow indexing is visible in the logs.

    W2-17: a call that won its operation and indexed its own result runs the recovery check only
    when ``arv2_recover_on_success`` is on; the job's settle step runs it once either way.
    """
    import clue_api.arv2.account_research_tools as tools_module

    lines: list[tuple[str, dict]] = []

    class Recording:
        def _record(self, event, **fields):
            lines.append((event, fields))

        info = warning = error = exception = debug = _record

    monkeypatch.setattr(tools_module, "log", Recording())

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, cid = await setup(conn, storage)
            scope = replace(scope, catalog_version="v4", input_refs={"quality_recipe_version": 8})
            parent = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=parent,
                context_id=cid,
                role="account_research",
                limits=Allowance(20, 40, 4),
            )
            body = {
                "output": {"content": "A substantive report. " * 200},
                "costDollars": {"total": 0.05},
                "results": [{"url": "https://example.test/bdr", "title": "BDR"}],
            }
            rt = runtime(conn, scope, storage, ScriptedTransport([response(body)]))
            rt.settings = Settings(
                _env_file=None,  # type: ignore[call-arg]
                arv2_ai_ark_min_gap_s=0,
                arv2_recover_on_success=recover_on_success,
            )

            @asynccontextmanager
            async def connections():
                yield conn

            ctx = ToolContext(
                workspace_id=scope.workspace_id,
                actor="agent",
                conn_factory=connections,
                execution_id=ExecutionId(parent),
                operation_id=OperationId(uuid4()),
            )
            result = await AcquireResearchTool(rt).invoke(
                AcquireResearchInput(
                    operation="research_deep",
                    arguments={
                        "charter": "Investigate the company and its operating workflows. " * 8,
                        "additional_queries": ["company leadership"],
                        "num_results": 40,
                    },
                ),
                ctx,
            )
            assert result.references["status"] == "completed", result

    run_async(case())
    drained = [f for e, f in lines if e == "arv2.drain_completed"]
    assert len(drained) == 1
    assert drained[0]["drain_ms"] >= 0 and drained[0]["index_ms"] >= 0
    assert drained[0]["job_id"] and drained[0]["provider"]
    recovered = [f for e, f in lines if e == "arv2.acquisition_recovered"]
    assert len(recovered) == (1 if recover_on_success else 0)
    assert all(r["recover_ms"] >= 0 for r in recovered)
