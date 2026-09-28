"""Attachment refs read back with the human's filename, the media type, and their upload id.

The durable turn receipt records *which artifact* the human sent; the filename lives on the
``agent_turn_submission_attachment`` row beside it. The transcript joins that presentation at read
time, exactly as it already does for design assets and project files — so a chip can say
``shot.png`` and an image chip can fetch its own bytes, without denormalizing a label into the
append-only receipt.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_agents.contracts import ArtifactRef
from clue_api.agent_turn_submission import insert_submission
from clue_api.chat.attachments import ValidatedAttachment
from clue_api.chat.composer_context import context_ref_presentations
from clue_api.chat.uploads import record_chat_upload
from clue_db import db_lifespan
from clue_projections.thread_refs import MessageObjectRef
from clue_storage.fs import FsStorage
from tests.api.test_project_document_context_refs_db import _seed, _submission_kwargs
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_attachment_refs_present_filename_media_type_and_upload_id(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed(conn, FsStorage(tmp_path))
            ws = seeds["ws"]

            image_sha = "c" * 64
            image_key = f"{ws}/{image_sha}"
            text_sha = "d" * 64
            text_key = f"{ws}/{text_sha}"
            await conn.execute(
                text(
                    "INSERT INTO artifact (storage_key, workspace_id, content_sha256, "
                    "media_type, size_bytes) VALUES "
                    "(:image_key, :ws, :image_sha, 'image/png', 8), "
                    "(:text_key, :ws, :text_sha, 'text/markdown', 5)"
                ),
                {
                    "image_key": image_key,
                    "image_sha": image_sha,
                    "text_key": text_key,
                    "text_sha": text_sha,
                    "ws": ws,
                },
            )
            image_ref = ArtifactRef(
                workspace_id=ws,
                artifact_key=image_key,
                sha256=image_sha,
                media_type="image/png",
                byte_count=8,
            )
            text_ref = ArtifactRef(
                workspace_id=ws,
                artifact_key=text_key,
                sha256=text_sha,
                media_type="text/markdown",
                byte_count=5,
            )
            image_upload = await record_chat_upload(
                conn,
                workspace_id=ws,
                user_id=seeds["user_id"],
                filename="shot.png",
                media_type="image/png",
                ref=image_ref,
            )
            text_upload = await record_chat_upload(
                conn,
                workspace_id=ws,
                user_id=seeds["user_id"],
                filename="brief.md",
                media_type="text/markdown",
                ref=text_ref,
            )
            kwargs = _submission_kwargs(seeds, "present")
            _row, created = await insert_submission(
                conn,
                attachment_refs=(
                    ValidatedAttachment(
                        upload_id=image_upload.upload_id,
                        ref=image_ref,
                        filename="shot.png",
                        family="image",
                    ),
                    ValidatedAttachment(
                        upload_id=text_upload.upload_id,
                        ref=text_ref,
                        filename="brief.md",
                        family="text",
                    ),
                ),
                **kwargs,
            )
            assert created

            presentations = await context_ref_presentations(
                conn,
                workspace_id=ws,
                refs=(
                    MessageObjectRef(
                        flavor="attachment",
                        workspace_id=ws,
                        object_type="artifact",
                        object_id=image_key,
                        version=None,
                        ordinal=0,
                    ),
                    MessageObjectRef(
                        flavor="attachment",
                        workspace_id=ws,
                        object_type="artifact",
                        object_id=text_key,
                        version=None,
                        ordinal=1,
                    ),
                ),
                storage=None,
            )

            assert presentations[("artifact", image_key)] == {
                "label": "shot.png",
                "media_type": "image/png",
                "upload_id": str(image_upload.upload_id),
            }
            assert presentations[("artifact", text_key)] == {
                "label": "brief.md",
                "media_type": "text/markdown",
                "upload_id": str(text_upload.upload_id),
            }
            await txn.rollback()

    run_async(scenario())


def test_another_workspaces_attachment_is_not_presented(tmp_path: Path) -> None:
    """The join is workspace-scoped: a foreign artifact key resolves to no presentation."""

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed(conn, FsStorage(tmp_path))
            ws = seeds["ws"]
            sha = "f" * 64
            key = f"{ws}/{sha}"
            await conn.execute(
                text(
                    "INSERT INTO artifact (storage_key, workspace_id, content_sha256, "
                    "media_type, size_bytes) VALUES (:key, :ws, :sha, 'image/png', 8)"
                ),
                {"key": key, "ws": ws, "sha": sha},
            )
            ref = ArtifactRef(
                workspace_id=ws,
                artifact_key=key,
                sha256=sha,
                media_type="image/png",
                byte_count=8,
            )
            upload = await record_chat_upload(
                conn,
                workspace_id=ws,
                user_id=seeds["user_id"],
                filename="private.png",
                media_type="image/png",
                ref=ref,
            )
            kwargs = _submission_kwargs(seeds, "scoped")
            _row, created = await insert_submission(
                conn,
                attachment_refs=(
                    ValidatedAttachment(
                        upload_id=upload.upload_id,
                        ref=ref,
                        filename="private.png",
                        family="image",
                    ),
                ),
                **kwargs,
            )
            assert created

            presentations = await context_ref_presentations(
                conn,
                workspace_id=f"ws_test_other_{uuid4().hex[:12]}",
                refs=(
                    MessageObjectRef(
                        flavor="attachment",
                        workspace_id=ws,
                        object_type="artifact",
                        object_id=key,
                        version=None,
                        ordinal=0,
                    ),
                ),
                storage=None,
            )
            assert presentations == {}
            await txn.rollback()

    run_async(scenario())
