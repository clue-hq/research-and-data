"""Actual specialist tools and framework mounts share scope, correction and revocation rules."""

import json
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from deepagents.backends.protocol import BackendProtocol
from sqlalchemy import text

from clue_api.arv2.evidence_paths import source_path
from clue_api.arv2.quality_authority import resolve_authority
from clue_api.arv2.quality_claims import ClaimProposal
from clue_api.arv2.quality_evidence import EvidenceUnavailable, JsonSupport, revoke_grant
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_tools import (
    CorrectResearchClaimInput,
    CorrectResearchClaimTool,
    ProcessingDispositionInput,
    ProcessingDispositionTool,
    SearchEvidenceInput,
    SearchEvidenceTool,
    SubmitResearchClaimInput,
    SubmitResearchClaimTool,
)
from clue_api.arv2.quality_views import research_backend
from clue_core import ExecutionId, OperationId
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_storage.fs import FsStorage
from clue_toolbelt import ToolContext
from tests.arv2.test_quality_claims_db import assessment, setup
from tests.arv2.test_quality_evidence_db import save
from tests.arv2.test_quality_execution_db import execution
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def read(backend, path):
    result = await backend.aread(path)
    assert result.error is None, result.error
    return json.loads(result.file_data["content"])


async def read_document(backend, path):
    body = ""
    while path:
        data = await read(backend, path)
        body += "".join(s["text"] for s in data["text_segments"])
        path = data["next_path"]
    return body


def test_claim_tool_correction_changes_live_view_and_revocation_denies_replay(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, cid = await setup(conn, storage)
            source = await save(
                conn, storage, op, {"employees": 64}, kind="provider_record", url=None
            )
            parent = await execution(conn, op, scope.project_id)
            child = await execution(conn, op, scope.project_id, parent)
            narrative = await execution(conn, op, scope.project_id, parent)
            for eid, role, pid in [
                (parent, "account_research", None),
                (child, "research_claims", parent),
                (narrative, "research_narrative", parent),
            ]:
                await bind_execution(
                    conn,
                    op,
                    execution_id=eid,
                    context_id=cid,
                    role=role,
                    limits=Allowance(20, 30, 10),
                    parent_execution_id=pid,
                )

            @asynccontextmanager
            async def connections():
                yield conn

            backend = research_backend(BackendProtocol(), connections, storage, scope, child)
            context = await read(backend, "/research/context.json")
            assert context["context_id"] == str(cid)
            assert (await read(backend, "/research/catalog/0.json"))[
                "kind"
            ] == "field_definitions_not_evidence"
            source_body = await read_document(backend, source_path(source.model_dump()))
            assert json.loads(source_body) == {"employees": 64}
            for path in ("/evidence/../secret", "/research/documents/" + str(uuid4()) + "/0.json"):
                assert (await backend.aread(path)).error
                assert (await backend.awrite(path, "injected")).error
            ctx = ToolContext(
                workspace_id=op.workspace_id,
                actor="agent",
                conn_factory=connections,
                operation_id=OperationId(uuid4()),
                execution_id=ExecutionId(child),
            )
            submit = SubmitResearchClaimTool(scope, storage, purge_unevidenced=True)
            args = SubmitResearchClaimInput(
                proposal=ClaimProposal(
                    operation_key="count",
                    field_key="core.employee_count",
                    value=64,
                    assessment=assessment(),
                    support=(
                        JsonSupport(
                            source_id=source.source_id, pointer="/employees", expected_value=64
                        ),
                    ),
                )
            )
            result = await submit.invoke(args, ctx)
            assert result.references["status"] == "supported"
            assert (await submit.invoke(args, ctx)).references["replayed"]
            claim_id = result.references["claim_id"]
            search = await SearchEvidenceTool(scope, storage, purge_unevidenced=True).invoke(
                SearchEvidenceInput(source_id=source.source_id, query="employees"), ctx
            )
            assert len(search.references["matches"]) == 1
            assert "text" not in search.references
            disposition = await ProcessingDispositionTool(
                scope, storage, purge_unevidenced=True
            ).invoke(
                ProcessingDispositionInput(
                    source_id=source.source_id,
                    unit_locator="staff",
                    decision="written",
                    reason="Mapped the provider employee count.",
                    claim_ids=(claim_id,),
                ),
                ctx,
            )
            assert disposition.references["decision"] == "written"
            page = await read(backend, "/research/claims/0.json")
            assert page["claims"][0]["revision"] == 1
            nbackend = research_backend(BackendProtocol(), connections, storage, scope, narrative)
            path = page["claims"][0]["path"]
            assert json.loads(await read_document(nbackend, path))["value_json"] == 64
            correction = CorrectResearchClaimTool(scope, storage, purge_unevidenced=True)
            reply = await correction.invoke(
                CorrectResearchClaimInput(
                    operation_key="withdraw",
                    claim_id=claim_id,
                    expected_revision=1,
                    action="withdrawal",
                    reason="The count is historical.",
                ),
                ctx,
            )
            assert reply.references["status"] == "invalid"
            assert not await claims_for(
                conn, op.account_id, scope=WorkspaceScope.for_workspace(op.workspace_id)
            )
            # Withdrawal blocks the next narrative read before any asynchronous display refresh.
            assert "value_json" not in json.loads(await read_document(nbackend, path))
            assert json.loads(await read_document(backend, path))["value_json"] == 64
            authority = await resolve_authority(conn, scope, child)
            await revoke_grant(conn, authority.grant)
            assert (await backend.aread(source_path(source.model_dump()))).error
            assert (await backend.aread(path)).error
            with pytest.raises(EvidenceUnavailable):
                await submit.invoke(args, ctx)
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM claim WHERE id=:id"), {"id": claim_id}
                )
            ).scalar_one() == 1

    run_async(case())


def test_child_manifest_is_fixed_parent_can_read_later_sources(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, cid = await setup(conn, storage)
            parent = await execution(conn, op, scope.project_id)
            child = await execution(conn, op, scope.project_id, parent)
            for eid, role, pid in [
                (parent, "account_research", None),
                (child, "research_claims", parent),
            ]:
                await bind_execution(
                    conn,
                    op,
                    execution_id=eid,
                    context_id=cid,
                    role=role,
                    limits=Allowance(20, 30, 10),
                    parent_execution_id=pid,
                )

            @asynccontextmanager
            async def connections():
                yield conn

            backend = research_backend(BackendProtocol(), connections, storage, scope, child)
            assert (await read(backend, "/evidence/index.json"))["sources"] == []
            original = "Complete original report. " * 1200
            source = await save(conn, storage, op, original)
            assert (await backend.aread(source_path(source.model_dump()))).error
            pbackend = research_backend(BackendProtocol(), connections, storage, scope, parent)
            assert await read_document(pbackend, source_path(source.model_dump())) == original

    run_async(case())
