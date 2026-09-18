"""DB proofs for the chat-attachment tables (spec 2026-09-18).

These assert the substrate guarantees the later tasks rely on: an upload's artifact key is
workspace-scoped by construction, and a stored filename can never carry a path separator.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from clue_db import db_lifespan
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_chat_upload_scope_check_rejects_a_foreign_key_shape() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = "ws_test_upload_tables"
            sha = "a" * 64
            await conn.execute(
                text(
                    "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
                    "size_bytes) VALUES (:key, :ws, :sha, 'image/png', 3)"
                ),
                {"key": f"{ws}/{sha}", "ws": ws, "sha": sha},
            )
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO chat_upload (upload_id, workspace_id, uploaded_by_user_id, "
                        "filename, media_type, artifact_key, sha256, byte_count) VALUES "
                        "(gen_random_uuid(), 'other_ws', 'usr', 'a.png', 'image/png', :key, :sha, 3)"
                    ),
                    {"key": f"{ws}/{sha}", "sha": sha},
                )
            await txn.rollback()

    run_async(scenario())


def test_chat_upload_filename_has_no_slash() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = "ws_test_upload_names"
            sha = "b" * 64
            await conn.execute(
                text(
                    "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
                    "size_bytes) VALUES (:key, :ws, :sha, 'text/plain', 3)"
                ),
                {"key": f"{ws}/{sha}", "ws": ws, "sha": sha},
            )
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO chat_upload (upload_id, workspace_id, uploaded_by_user_id, "
                        "filename, media_type, artifact_key, sha256, byte_count) VALUES "
                        "(gen_random_uuid(), :ws, 'usr', '../x.txt', 'text/plain', :key, :sha, 3)"
                    ),
                    {"ws": ws, "key": f"{ws}/{sha}", "sha": sha},
                )
            await txn.rollback()

    run_async(scenario())
