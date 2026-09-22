"""Framework filesystem reads cannot bypass grant revocation or expose worker files."""

import json
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

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
            original = "A long paragraph. " * 1200
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
            assert (await backend.aread(f"/evidence/{foreign.source_id}/0.json")).error
            for path in ("/etc/passwd", "/evidence/../secret", "/evidence/%2e%2e/key"):
                assert (await backend.aread(path)).error
                assert (await backend.awrite(path, "replacement")).error
                assert (await backend.aedit(path, "x", "y")).error
            await revoke_grant(conn, grant)
            assert (await backend.aread(f"/evidence/{source.source_id}/0.json")).error
            assert (await backend.als("/evidence")).error

    run_async(case())
