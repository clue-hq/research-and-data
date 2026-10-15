"""The agent reuses one readable source path through read/search/write/receipt."""

from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from deepagents.backends.protocol import BackendProtocol
from sqlalchemy import text

from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_findings import (
    RecordContentFindingInput,
    RecordContentResearchFindingTool,
    RecordPathFindingInput,
    RecordPathResearchFindingTool,
)
from clue_api.arv2.quality_tools import (
    PathProcessingDispositionInput,
    PathProcessingDispositionTool,
    SearchPathEvidenceInput,
    SearchPathEvidenceTool,
)
from clue_api.arv2.quality_views import research_backend
from clue_core import ExecutionId, OperationId
from clue_storage.fs import FsStorage
from clue_toolbelt import ToolContext
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_evidence_db import save
from tests.arv2.test_quality_execution_db import execution
from tests.arv2.test_quality_tools_db import read
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_path_tools_preserve_canonical_evidence_and_reject_invented_names(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, job, cid = await setup(conn, storage)
            job = replace(job, catalog_version="v4", input_refs={"quality_recipe_version": 14})
            source = await save(conn, storage, op, "Staff count reported as 64.")
            eid = await execution(conn, op, job.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=eid,
                context_id=cid,
                role="account_research",
                limits=Allowance(30, 60, 20),
            )

            @asynccontextmanager
            async def connections():
                yield conn

            ctx = ToolContext(
                workspace_id=job.workspace_id,
                actor="agent",
                conn_factory=connections,
                operation_id=OperationId(uuid4()),
                execution_id=ExecutionId(eid),
            )
            backend = research_backend(BackendProtocol(), connections, storage, job, eid)
            index = await read(backend, "/evidence/index.json")
            path = index["sources"][0]["path"]
            assert (await backend.als("/evidence/")).entries[1]["path"] == path
            assert (await backend.aglob("*example-test*", "/evidence/")).matches[0]["path"] == path
            assert "64" in str(await read(backend, path))
            search = SearchPathEvidenceTool(job, storage, purge_unevidenced=False)
            hits = await search.invoke(SearchPathEvidenceInput(source_path=path, query="64"), ctx)
            assert hits.references["matches"][0]["path"] == path
            writer = RecordPathResearchFindingTool(job, storage, purge_unevidenced=False)
            args = RecordPathFindingInput(
                operation_key="staff",
                topic="Headcount",
                finding="64 staff reported",
                source_paths=(path,),
            )
            receipt = await writer.invoke(args, ctx)
            assert receipt.version == "2"
            assert (await writer.invoke(args, ctx)).references["replayed"]
            content_writer = RecordContentResearchFindingTool(job, storage, purge_unevidenced=False)
            content = RecordContentFindingInput(
                topic="staff",
                finding={"count": 64, "qualifier": "reported"},
                source_paths=(path,),
            )
            first = await content_writer.invoke(content, ctx)
            assert first.version == "3"
            # Equivalent object/source order reuses both the receipt and canonical proposal bytes.
            retry = await content_writer.invoke(
                content.model_copy(
                    update={
                        "finding": {"qualifier": "reported", "count": 64},
                        "source_paths": (path, path),
                    }
                ),
                ctx,
            )
            assert retry.references["replayed"]
            assert retry.references["claim_id"] == first.references["claim_id"]
            # Reusing the topic for a different fact can never cause the old key collision.
            other = await content_writer.invoke(
                content.model_copy(update={"finding": "Other fact"}), ctx
            )
            assert other.references["claim_id"] != first.references["claim_id"]
            assert "operation_key" not in RecordContentFindingInput.model_fields
            claim = UUID(receipt.references["claim_id"])
            disposition = await PathProcessingDispositionTool(
                job, storage, purge_unevidenced=False
            ).invoke(
                PathProcessingDispositionInput(
                    source_path=path,
                    unit_locator="staff",
                    decision="written",
                    reason="Saved staff count",
                    claim_ids=(claim,),
                ),
                ctx,
            )
            assert disposition.references["source_id"] == str(source.source_id)
            with pytest.raises(ValueError, match="exact path"):
                await writer.invoke(
                    args.model_copy(
                        update={"source_paths": (path.replace("example-test-source", "invented"),)}
                    ),
                    ctx,
                )
            # The alias is only navigation; claim evidence keeps the real immutable source ID.
            stored = (
                await conn.execute(text("SELECT value_json FROM claim WHERE id=:id"), {"id": claim})
            ).scalar_one()
            assert stored["finding"] == "64 staff reported"

    run_async(case())


@pytest.mark.parametrize("recipe", [25, 26])
def test_a_research_view_search_is_a_refusal_not_a_failure_from_recipe_26(tmp_path, recipe):
    """Production 2026-10-06: grep on a research view said "use search_evidence"; search_evidence
    then failed on that path, and the failed attempt blocked finalize_turn in 7 of 12 jobs."""
    from clue_api.arv2.quality_evidence import EvidenceUnavailable
    from clue_toolbelt import PreconditionFailed

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, job, cid = await setup(conn, storage)
            job = replace(job, catalog_version="v4", input_refs={"quality_recipe_version": recipe})
            await save(conn, storage, op, "Dialpad's CMO seat has been vacant since Sept 2025.")
            eid = await execution(conn, op, job.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=eid,
                context_id=cid,
                role="account_research",
                limits=Allowance(30, 60, 20),
            )

            @asynccontextmanager
            async def connections():
                yield conn

            ctx = ToolContext(
                workspace_id=job.workspace_id,
                actor="agent",
                conn_factory=connections,
                operation_id=OperationId(uuid4()),
                execution_id=ExecutionId(eid),
            )
            search = SearchPathEvidenceTool(job, storage, purge_unevidenced=False)
            view = f"/research/operations/{uuid4()}/0.json"
            expected = PreconditionFailed if recipe >= 26 else EvidenceUnavailable
            with pytest.raises(expected) as raised:
                await search.invoke(SearchPathEvidenceInput(source_path=view, query="CMO"), ctx)
            if recipe >= 26:
                assert "grep" in raised.value.failures[0].message

            backend = research_backend(BackendProtocol(), connections, storage, job, eid)
            path = (await read(backend, "/evidence/index.json"))["sources"][0]["path"]
            found = await backend.agrep("vacant", path=path)
            if recipe >= 26:
                assert found.error is None
                assert [m["path"] for m in found.matches] == [path]
                assert "vacant" in found.matches[0]["text"]
                assert (await backend.agrep("vacant", path="/evidence")).error
            else:
                assert "search_evidence" in found.error

    run_async(case())
