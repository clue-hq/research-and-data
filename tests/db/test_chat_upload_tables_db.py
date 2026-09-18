"""DB proofs for the chat-attachment tables (spec 2026-09-18).

These assert the substrate guarantees the later tasks rely on: an upload's artifact key is
workspace-scoped by construction, a stored filename can never carry a path separator, a submission
can only attach uploads from its own workspace, and a captured attachment never changes.
"""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from tests._workspace import seed_project
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
                        "(gen_random_uuid(), 'other_ws', 'usr', 'a.png', 'image/png', :key, "
                        ":sha, 3)"
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


async def _insert_artifact(conn: AsyncConnection, *, ws: str, sha: str) -> str:
    """Create the content-addressed artifact row an upload cites, and return its storage key."""
    key = f"{ws}/{sha}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            "size_bytes) VALUES (:key, :ws, :sha, 'text/plain', 3)"
        ),
        {"key": key, "ws": ws, "sha": sha},
    )
    return key


async def _insert_upload(conn: AsyncConnection, *, ws: str, sha: str) -> Any:
    """Create one ``chat_upload`` (with its artifact) in ``ws`` and return its id."""
    key = await _insert_artifact(conn, ws=ws, sha=sha)
    upload_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO chat_upload (upload_id, workspace_id, uploaded_by_user_id, filename, "
            "media_type, artifact_key, sha256, byte_count) VALUES "
            "(:id, :ws, 'usr', 'notes.txt', 'text/plain', :key, :sha, 3)"
        ),
        {"id": upload_id, "ws": ws, "key": key, "sha": sha},
    )
    return upload_id


async def _seed_submission(conn: AsyncConnection, ws: str) -> Any:
    """Seed the workspace/project/thread/user chain one ``agent_turn_submission`` needs.

    Direct SQL rather than ``clue_api.agent_turn_submission.insert_submission``: these tests care
    only that a submission row exists to hang attachments from, so the smaller dependency wins.
    """
    project = await seed_project(conn, ws, name="Chat attachments")
    sha = "c" * 64
    key = await _insert_artifact(conn, ws=ws, sha=sha)
    onboarding_input_id = uuid5(NAMESPACE_URL, f"chat-upload-onb:{ws}")
    await conn.execute(
        text(
            "INSERT INTO onboarding_input (id, workspace_id, brand_id, kind, artifact_key, "
            "content_sha256, actor) "
            "VALUES (:id, :ws, :brand, 'user_turn', :key, :sha, 'human')"
        ),
        {"id": onboarding_input_id, "ws": ws, "brand": project.brand_id, "key": key, "sha": sha},
    )
    thread_id = f"thr_upload_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :project)"),
        {"id": thread_id, "ws": ws, "project": project.project_id},
    )
    user_id = f"user_upload_{uuid4().hex[:8]}"
    membership_id = f"member_upload_{uuid4().hex[:8]}"
    await conn.execute(
        text("INSERT INTO platform_user (user_id) VALUES (:user)"), {"user": user_id}
    )
    await conn.execute(
        text(
            "INSERT INTO workspace_membership (membership_id, workspace_id, user_id, role_key, "
            "status, activated_at) "
            "VALUES (:membership, :ws, :user, 'owner', 'active', now())"
        ),
        {"membership": membership_id, "ws": ws, "user": user_id},
    )
    turn_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO agent_turn_submission (turn_id, workspace_id, project_id, thread_id, "
            "submitted_by_user_id, submitted_via_membership_id, onboarding_input_id, "
            "message_artifact_key, message_sha256) "
            "VALUES (:turn, :ws, :project, :thread, :user, :membership, :onb, :key, :sha)"
        ),
        {
            "turn": turn_id,
            "ws": ws,
            "project": project.project_id,
            "thread": thread_id,
            "user": user_id,
            "membership": membership_id,
            "onb": onboarding_input_id,
            "key": key,
            "sha": sha,
        },
    )
    return turn_id


def test_attachment_cannot_cite_an_upload_from_another_workspace() -> None:
    """The composite upload FK makes a cross-workspace citation structurally impossible."""

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = f"ws_test_att_own_{uuid4().hex[:8]}"
            other_ws = f"ws_test_att_other_{uuid4().hex[:8]}"
            turn_id = await _seed_submission(conn, ws)
            foreign_upload = await _insert_upload(conn, ws=other_ws, sha="d" * 64)
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO agent_turn_submission_attachment (turn_id, workspace_id, "
                        "ordinal, upload_id, artifact_key, sha256, media_type, byte_count, "
                        "filename) VALUES (:turn, :ws, 0, :upload, :key, :sha, 'text/plain', 3, "
                        "'notes.txt')"
                    ),
                    {
                        "turn": turn_id,
                        "ws": ws,
                        "upload": foreign_upload,
                        "key": f"{other_ws}/{'d' * 64}",
                        "sha": "d" * 64,
                    },
                )
            await txn.rollback()

    run_async(scenario())


def test_attachment_rows_are_append_only() -> None:
    """The append-only trigger refuses an UPDATE on a captured attachment."""

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = f"ws_test_att_immut_{uuid4().hex[:8]}"
            turn_id = await _seed_submission(conn, ws)
            sha = "e" * 64
            upload_id = await _insert_upload(conn, ws=ws, sha=sha)
            await conn.execute(
                text(
                    "INSERT INTO agent_turn_submission_attachment (turn_id, workspace_id, "
                    "ordinal, upload_id, artifact_key, sha256, media_type, byte_count, filename) "
                    "VALUES (:turn, :ws, 0, :upload, :key, :sha, 'text/plain', 3, 'notes.txt')"
                ),
                {
                    "turn": turn_id,
                    "ws": ws,
                    "upload": upload_id,
                    "key": f"{ws}/{sha}",
                    "sha": sha,
                },
            )
            with pytest.raises(DBAPIError, match="append-only"):
                await conn.execute(
                    text(
                        "UPDATE agent_turn_submission_attachment SET filename = 'renamed.txt' "
                        "WHERE turn_id = :turn AND ordinal = 0"
                    ),
                    {"turn": turn_id},
                )
            await txn.rollback()

    run_async(scenario())


def test_attachment_artifact_lookup_is_indexed() -> None:
    """The transcript's presentation join filters on ``(workspace_id, artifact_key)``."""

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            found = await conn.execute(
                text(
                    "SELECT 1 FROM pg_indexes "
                    "WHERE indexname = 'agent_turn_submission_attachment_artifact'"
                )
            )
            assert found.first() is not None
            await txn.rollback()

    run_async(scenario())
