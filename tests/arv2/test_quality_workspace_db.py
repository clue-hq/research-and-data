"""Framework filesystem reads cannot bypass grant revocation or expose worker files."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from deepagents.middleware.filesystem import FilesystemMiddleware

from clue_api.arv2.quality_evidence import grant_manifest, revoke_grant
from clue_api.arv2.quality_workspace import EvidenceWorkspace
from clue_storage.fs import FsStorage
from tests.arv2.test_quality_evidence_db import save, seed
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_original_continuation_and_revocation_on_every_virtual_read(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            scope, other = await seed(conn, storage)
            original = "A long paragraph. " * 2400
            source = await save(conn, storage, scope, original)
            foreign = await save(conn, storage, other, "Other account source")
            grant = await grant_manifest(conn, scope, consumer_id=uuid4())

            @asynccontextmanager
            async def connections():
                yield conn

            backend = EvidenceWorkspace(connections, storage, grant)
            index = await backend.aread("/evidence/index/0.json")
            assert index.error is None
            path = json.loads(index.file_data["content"])["sources"][0]["path"]
            rebuilt = ""
            while path:
                view = await backend.aread(path)
                assert view.error is None
                body = json.loads(view.file_data["content"])
                rebuilt += "".join(s["text"] for s in body["text_segments"])
                path = body["next_path"]
            assert rebuilt == original
            assert body["next_path"] is None
            unbounded = await backend.aread(f"/evidence/{source.source_id}/0.json", limit=0)
            assert not unbounded.error
            assert original == "".join(
                s["text"] for s in json.loads(unbounded.file_data["content"])["text_segments"]
            )
            path = f"/evidence/{source.source_id}/0.json"
            full = (await backend.aread(path)).file_data["content"]
            rebuilt_view = ""
            for offset in range(0, len(full.splitlines()), 20):
                page = await backend.aread(path, offset=offset, limit=20)
                assert not page.error
                rebuilt_view += page.file_data["content"]
            assert rebuilt_view == full
            # Exercise the actual framework tool with its recommended small line windows.
            tool = FilesystemMiddleware(backend=backend)._create_read_file_tool()
            first = await tool.coroutine(
                file_path=path, runtime=SimpleNamespace(tool_call_id="read-1"), offset=0, limit=20
            )
            following = await tool.coroutine(
                file_path=path, runtime=SimpleNamespace(tool_call_id="read-2"), offset=20, limit=20
            )
            assert first.status == following.status == "success"
            assert "text_segments" in first.content
            assert "A long paragraph" in following.content
            assert (await backend.aread(f"/evidence/{foreign.source_id}/0.json")).error
            for path in ("/etc/passwd", "/evidence/../secret", "/evidence/%2e%2e/key"):
                assert (await backend.aread(path)).error
                assert (await backend.awrite(path, "replacement")).error
                assert (await backend.aedit(path, "x", "y")).error
            await revoke_grant(conn, grant)
            denied = await tool.coroutine(
                file_path=path,
                runtime=SimpleNamespace(tool_call_id="read-revoked"),
                offset=20,
                limit=20,
            )
            assert denied.status == "error"
            assert (await backend.aread(f"/evidence/{source.source_id}/0.json")).error
            assert (await backend.als("/evidence")).error

    run_async(case())
