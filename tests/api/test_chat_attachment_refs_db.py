"""Attachments persist with the submission they were attached to, in order, and read back."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_agents.contracts import ArtifactRef
from clue_api.agent_turn_submission import insert_submission, submission_attachment_refs
from clue_api.chat.attachments import ValidatedAttachment
from clue_api.chat.uploads import record_chat_upload
from clue_db import db_lifespan
from clue_storage.fs import FsStorage
from tests.api.test_project_document_context_refs_db import _seed, _submission_kwargs
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_attachments_persist_with_the_submission(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed(conn, FsStorage(tmp_path))
            ws = seeds["ws"]
            sha = "e" * 64
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
                filename="shot.png",
                media_type="image/png",
                ref=ref,
            )
            kwargs = _submission_kwargs(seeds, "attach")
            _row, created = await insert_submission(
                conn,
                attachment_refs=(
                    ValidatedAttachment(
                        upload_id=upload.upload_id,
                        ref=ref,
                        filename="shot.png",
                        family="image",
                    ),
                ),
                **kwargs,
            )
            assert created
            (stored,) = await submission_attachment_refs(
                conn, workspace_id=ws, turn_id=kwargs["turn_id"]
            )
            assert stored.upload_id == upload.upload_id and stored.filename == "shot.png"
            assert stored.ref == ref
            await txn.rollback()

    run_async(scenario())


def test_attachment_from_another_workspace_is_refused_early(tmp_path: Path) -> None:
    """The guard names the crossed boundary before any row is written."""

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed(conn, FsStorage(tmp_path))
            sha = "f" * 64
            foreign = ArtifactRef(
                workspace_id="ws_some_other_tenant",
                artifact_key=f"ws_some_other_tenant/{sha}",
                sha256=sha,
                media_type="image/png",
                byte_count=8,
            )
            kwargs = _submission_kwargs(seeds, "attach-foreign")
            with pytest.raises(ValueError, match="attachment refs cross the workspace boundary"):
                await insert_submission(
                    conn,
                    attachment_refs=(
                        ValidatedAttachment(
                            upload_id=uuid4(),
                            ref=foreign,
                            filename="shot.png",
                            family="image",
                        ),
                    ),
                    **kwargs,
                )
            await txn.rollback()

    run_async(scenario())
