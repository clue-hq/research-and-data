"""Chat attachments (spec 2026-09-18), Task 4: the upload row round-trips, workspace-scoped.

``record_chat_upload`` writes the filename beside the content-addressed artifact, and
``get_chat_uploads`` reads it back only for the workspace that owns it — a foreign workspace sees
nothing, not a redacted row.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_agents.contracts import ArtifactRef
from clue_api.chat.uploads import get_chat_uploads, record_chat_upload
from clue_db import db_lifespan
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_record_then_get_is_workspace_scoped() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = f"ws_upl_{uuid4().hex[:8]}"
            sha = "c" * 64
            key = f"{ws}/{sha}"
            await conn.execute(
                text(
                    "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
                    "size_bytes) VALUES (:key, :ws, :sha, 'text/markdown', 4)"
                ),
                {"key": key, "ws": ws, "sha": sha},
            )
            ref = ArtifactRef(
                workspace_id=ws,
                artifact_key=key,
                sha256=sha,
                media_type="text/markdown",
                byte_count=4,
            )
            row = await record_chat_upload(
                conn,
                workspace_id=ws,
                user_id="usr_a",
                filename="notes.md",
                media_type="text/markdown",
                ref=ref,
            )
            assert row.filename == "notes.md"
            assert row.artifact_key == key
            found = await get_chat_uploads(conn, workspace_id=ws, upload_ids=[row.upload_id])
            assert found[row.upload_id] == row
            foreign = await get_chat_uploads(
                conn, workspace_id="ws_other", upload_ids=[row.upload_id]
            )
            assert foreign == {}
            await txn.rollback()

    run_async(scenario())
