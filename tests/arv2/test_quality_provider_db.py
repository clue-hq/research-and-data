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
from clue_core import ExecutionId, OperationId
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
                                    "summary": {"name": scope.account_name, "staff": {"total": 64}},
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

    run_async(case())
