"""The project's attachments directory is the project's uploads, byte for byte.

One scenario walked in four phases against real rows, real blobs and a real workspace factory:
the first sync writes every family (a PDF, a markdown file and a PNG) unconverted; a second sync
writes nothing; a re-upload of one name on a later submission replaces exactly that file; and an
erased artifact is removed from the directory rather than left behind for the model to read.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import ArtifactRef
from clue_agents.worker_area import ChatScope
from clue_api.agent_turn_submission import insert_submission
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.chat.attachments import ValidatedAttachment
from clue_api.chat.uploads import record_chat_upload
from clue_api.project_attachments import project_attachment_entries, sync_project_attachments
from clue_db import db_lifespan
from clue_storage.fs import FsStorage
from tests.agents.workspace_helpers import make_factory
from tests.api.test_project_document_context_refs_db import _seed, _submission_kwargs
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def _store(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    workspace_id: str,
    data: bytes,
    media_type: str,
) -> ArtifactRef:
    """One live artifact row plus its bytes — what an upload leaves behind."""

    sha = hashlib.sha256(data).hexdigest()
    key = f"{workspace_id}/{sha}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            " size_bytes) VALUES (:key, :ws, :sha, :media, :size) ON CONFLICT DO NOTHING"
        ),
        {"key": key, "ws": workspace_id, "sha": sha, "media": media_type, "size": len(data)},
    )
    await storage.put(key, data, media_type=media_type)
    return ArtifactRef(
        workspace_id=workspace_id,
        artifact_key=key,
        sha256=sha,
        media_type=media_type,
        byte_count=len(data),
    )


async def _attach(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    seeds: dict[str, object],
    tag: str,
    files: tuple[tuple[str, bytes, str, str], ...],
) -> None:
    """Upload each ``(filename, data, media_type, family)`` and submit them on one new turn."""

    workspace_id = str(seeds["ws"])
    attachments = []
    for filename, data, media_type, family in files:
        ref = await _store(
            conn, storage, workspace_id=workspace_id, data=data, media_type=media_type
        )
        upload = await record_chat_upload(
            conn,
            workspace_id=workspace_id,
            user_id=str(seeds["user_id"]),
            filename=filename,
            media_type=media_type,
            ref=ref,
        )
        attachments.append(
            ValidatedAttachment(
                upload_id=upload.upload_id,
                ref=ref,
                filename=filename,
                family=family,  # type: ignore[arg-type]
            )
        )
    _row, created = await insert_submission(
        conn, attachment_refs=tuple(attachments), **_submission_kwargs(seeds, tag)
    )
    assert created


def test_project_attachments_sync_writes_replaces_and_removes(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            storage = FsStorage(tmp_path / "blobs")
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=same_connection)
            _root, factory, _sink = make_factory(tmp_path / "agents")
            seeds = await _seed(conn, storage)
            ws = str(seeds["ws"])
            project_id = str(seeds["project_id"])
            chat = ChatScope(ws, project_id, "thread-1")

            await _attach(
                conn,
                storage,
                seeds=seeds,
                tag="attach-one",
                files=(
                    ("r.pdf", b"%PDF-1.4 x", "application/pdf", "document"),
                    ("brief.md", b"# Brief\n", "text/markdown", "text"),
                    ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png", "image"),
                ),
            )

            # 1. Every family lands unconverted, as the file the human sent.
            written = await sync_project_attachments(factory, artifacts, conn, chat=chat)
            assert written == 3
            root = factory.chat_host_path(chat) / "attachments"
            assert (root / "r.pdf").read_bytes() == b"%PDF-1.4 x"
            assert (root / "brief.md").read_text() == "# Brief\n"
            assert (root / "shot.png").exists()

            # 2. Idempotent: an unchanged project rewrites nothing.
            assert await sync_project_attachments(factory, artifacts, conn, chat=chat) == 0

            # 3. A re-upload of one name on a later turn replaces exactly that file.
            await _attach(
                conn,
                storage,
                seeds=seeds,
                tag="attach-two",
                files=(("brief.md", b"# Brief v2\n", "text/markdown", "text"),),
            )
            assert await sync_project_attachments(factory, artifacts, conn, chat=chat) == 1
            assert (root / "brief.md").read_text() == "# Brief v2\n"
            assert (root / "r.pdf").read_bytes() == b"%PDF-1.4 x"
            names = {
                entry.filename
                for entry in await project_attachment_entries(
                    conn, workspace_id=ws, project_id=project_id
                )
            }
            assert names == {"r.pdf", "brief.md", "shot.png"}

            # 4. Erasure: the bytes stop being readable, so the file stops being there.
            pdf_key = f"{ws}/{hashlib.sha256(b'%PDF-1.4 x').hexdigest()}"
            await conn.execute(
                text("UPDATE artifact SET erased_at = now() WHERE storage_key = :k"),
                {"k": pdf_key},
            )
            assert await sync_project_attachments(factory, artifacts, conn, chat=chat) == 0
            assert not (root / "r.pdf").exists()
            assert (root / "brief.md").read_text() == "# Brief v2\n"
            assert (root / "shot.png").exists()

            # 5. The directory holds uploads and nothing else. An entry this sync cannot have
            # written — here a directory standing where a live attachment's file belongs — is
            # dropped and the file written over it, rather than becoming a write that can never
            # succeed and so a turn that can never start.
            (root / "shot.png").unlink()
            (root / "shot.png").mkdir(mode=0o700)
            assert await sync_project_attachments(factory, artifacts, conn, chat=chat) == 1
            assert (root / "shot.png").read_bytes() == b"\x89PNG\r\n\x1a\n"
            assert (root / "brief.md").read_text() == "# Brief v2\n"

            await txn.rollback()

    run_async(scenario())
