"""Exact durable dossiers survive downstream failure and retain scoped source lineage."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from deepagents.backends.protocol import BackendProtocol
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from sqlalchemy import text

from clue_api.arv2.quality_authority import resolve_authority
from clue_api.arv2.quality_dossier import (
    AccountDossierPersistence,
    read_dossier,
    save_dossier,
)
from clue_api.arv2.quality_evidence import revoke_grant
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_views import research_backend
from clue_storage import read_verified_artifact
from clue_storage.fs import FsStorage
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_evidence_db import save
from tests.arv2.test_quality_execution_db import execution
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_file_save_survives_failed_child_versioning_source_inventory_and_revocation(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, job, cid = await setup(conn, storage)
            job = replace(job, catalog_version="v4", input_refs={"quality_recipe_version": 13})
            used = await save(
                conn, storage, op, "The team uses a named system.", url="https://example.test/jobs"
            )
            extra = await save(
                conn, storage, op, "Another acquired page.", url="https://example.test/news"
            )
            parent = await execution(conn, op, job.project_id)
            child = await execution(conn, op, job.project_id, parent)
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

            markdown = "# Findings — complete\n\n[Team workflow](https://example.test/jobs).\n"

            async def read_text(path):
                assert path == "outputs/account-dossier.md"
                return markdown

            middleware = AccountDossierPersistence(
                connections, storage, job, parent, SimpleNamespace(read_text=read_text)
            )

            async def wrote(request):
                return ToolMessage(content="Written", tool_call_id="write", status="success")

            response = await middleware.awrap_tool_call(
                SimpleNamespace(
                    tool_call={
                        "name": "write_file",
                        "id": "write",
                        "args": {"file_path": "/outputs/account-dossier.md", "content": markdown},
                    }
                ),
                wrote,
            )
            assert "durably saved" in response.content
            first = await read_dossier(conn, storage, job, context_id=cid)
            assert first["markdown"] == markdown and first["version"] == 1
            _, raw = await read_verified_artifact(
                conn,
                storage,
                workspace_id=job.workspace_id,
                storage_key=first["report"]["artifact_key"],
            )
            assert raw == markdown.encode()
            inventory = {s["source_id"]: s for s in first["source_inventory"]["sources"]}
            assert inventory[str(used.source_id)]["citation_match"] == "url"
            assert inventory[str(extra.source_id)]["citation_match"] is None
            assert await save_dossier(
                conn, storage, job, execution_id=parent, markdown=markdown
            ) == {k: v for k, v in first.items() if k != "markdown"}

            # The real request object preserves the amended instructions through override.
            request = ToolCallRequest(
                tool_call={
                    "name": "delegate_specialist",
                    "id": "child",
                    "args": {"role": "research_claims", "instructions": "Inspect workflow."},
                },
                tool=None,
                state={},
                runtime=None,
            )

            async def failed_child(request):
                assert (
                    "/research/account-dossier/1.json" in request.tool_call["args"]["instructions"]
                )
                assert "not an external" in request.tool_call["args"]["instructions"]
                view = research_backend(BackendProtocol(), connections, storage, job, child)
                response = await view.aread("/research/account-dossier/1.json")
                assert response.error is None
                assert json.loads(response.file_data["content"])["markdown"] == markdown
                raise RuntimeError("simulated specialist failure")

            with pytest.raises(RuntimeError, match="simulated specialist"):
                await middleware.awrap_tool_call(request, failed_child)
            assert (await read_dossier(conn, storage, job, context_id=cid))["markdown"] == markdown

            updated = (
                markdown + "\n## Update\nNew person evidence; interpretation remains uncertain.\n"
            )
            second = await save_dossier(conn, storage, job, execution_id=parent, markdown=updated)
            assert second["version"] == 2
            assert second["previous_version_path"] == first["path"]
            assert (await read_dossier(conn, storage, job, context_id=cid, version=1))[
                "markdown"
            ] == markdown
            assert (await read_dossier(conn, storage, job, context_id=cid))["markdown"] == updated
            # Dossier prose never enters the acquired-evidence collection.
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM arv2_evidence_source WHERE job_id=:job"),
                    {"job": job.job_id},
                )
            ).scalar_one() == 2
            with pytest.raises(ValueError, match="outside"):
                await read_dossier(conn, storage, replace(job, account_id=child), context_id=cid)
            with pytest.raises(ValueError, match="only the account"):
                await save_dossier(conn, storage, job, execution_id=child, markdown="replacement")
            authority = await resolve_authority(conn, job, child)
            await revoke_grant(conn, authority.grant)
            view = research_backend(BackendProtocol(), connections, storage, job, child)
            assert (await view.aread("/research/account-dossier/latest.json")).error
            # Erasing a source the report used erases the report (its lineage watermark, since
            # 2026-10-12; previously one derivation link per source).
            savepoint = await conn.begin_nested()
            await conn.execute(
                text(
                    "UPDATE artifact SET privacy_erased=true, erasure_reason='privacy', "
                    "erased_at=now() WHERE storage_key=:source"
                ),
                {"source": used.artifact_key},
            )
            assert (
                await conn.execute(
                    text("SELECT privacy_erased FROM artifact WHERE storage_key=:report"),
                    {"report": first["report"]["artifact_key"]},
                )
            ).scalar_one()
            await savepoint.rollback()

    run_async(case())
