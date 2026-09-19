"""A text attachment becomes a versioned project document the Gallery lists and the agent reads."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.project_documents import list_project_documents, read_project_document
from clue_api.chat.attachments import ValidatedAttachment, materialize_text_attachments
from clue_api.chat.uploads import record_chat_upload
from clue_db import db_lifespan
from clue_storage.fs import FsStorage
from tests._workspace import seed_project
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_text_upload_becomes_a_versioned_project_document(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path)
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = f"ws_attdoc_{uuid4().hex[:8]}"
            project = await seed_project(conn, ws, name="Attachment docs")

            @asynccontextmanager
            async def bound() -> AsyncIterator[AsyncConnection]:
                yield conn

            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=bound)

            async def attach(body: bytes) -> ValidatedAttachment:
                ref = await artifacts.persist_body(
                    workspace_id=ws, data=body, media_type="text/markdown"
                )
                row = await record_chat_upload(
                    conn,
                    workspace_id=ws,
                    user_id="usr",
                    filename="brief.md",
                    media_type="text/markdown",
                    ref=ref,
                )
                return ValidatedAttachment(
                    upload_id=row.upload_id, ref=ref, filename="brief.md", family="text"
                )

            first = await attach(b"# Brief\n\nFirst cut.\n")
            (written,) = await materialize_text_attachments(
                conn,
                storage,
                artifacts,
                workspace_id=ws,
                brand_id=str(project.brand_id),
                project_id=project.project_id,
                turn_id=uuid4(),
                user_id="usr",
                attachments=[first],
            )
            assert written.path == "attachments/brief.md" and written.version == 1
            assert written.workspace_path == "project/attachments/brief.md"
            found = await read_project_document(
                conn,
                storage,
                workspace_id=ws,
                project_id=project.project_id,
                document_id=written.document_id,
            )
            assert found is not None
            row, front, body = found
            assert row.kind == "attachment" and front["source"] == "user_upload"
            assert front["upload_id"] == str(first.upload_id)
            assert "First cut." in body

            # Same bytes, same name: no new version.
            again = await attach(b"# Brief\n\nFirst cut.\n")
            (replayed,) = await materialize_text_attachments(
                conn,
                storage,
                artifacts,
                workspace_id=ws,
                brand_id=str(project.brand_id),
                project_id=project.project_id,
                turn_id=uuid4(),
                user_id="usr",
                attachments=[again],
            )
            assert replayed.version == 1

            # Changed bytes, same name: version 2.
            changed = await attach(b"# Brief\n\nSecond cut.\n")
            (second,) = await materialize_text_attachments(
                conn,
                storage,
                artifacts,
                workspace_id=ws,
                brand_id=str(project.brand_id),
                project_id=project.project_id,
                turn_id=uuid4(),
                user_id="usr",
                attachments=[changed],
            )
            assert second.version == 2
            listed = await list_project_documents(
                conn, workspace_id=ws, project_id=project.project_id
            )
            assert [d.path for d in listed] == ["attachments/brief.md"]
            await txn.rollback()

    run_async(scenario())


def test_image_attachments_are_not_documents(tmp_path: Path) -> None:
    """Only text becomes a document: an image is shown, never written into the project tree."""

    async def scenario() -> None:
        storage = FsStorage(tmp_path)
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = f"ws_attimg_{uuid4().hex[:8]}"
            project = await seed_project(conn, ws, name="Attachment images")

            @asynccontextmanager
            async def bound() -> AsyncIterator[AsyncConnection]:
                yield conn

            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=bound)
            ref = await artifacts.persist_body(
                workspace_id=ws, data=b"\x89PNG\r\n\x1a\n0000", media_type="image/png"
            )
            row = await record_chat_upload(
                conn,
                workspace_id=ws,
                user_id="usr",
                filename="shot.png",
                media_type="image/png",
                ref=ref,
            )
            written = await materialize_text_attachments(
                conn,
                storage,
                artifacts,
                workspace_id=ws,
                brand_id=str(project.brand_id),
                project_id=project.project_id,
                turn_id=uuid4(),
                user_id="usr",
                attachments=[
                    ValidatedAttachment(
                        upload_id=row.upload_id, ref=ref, filename="shot.png", family="image"
                    )
                ],
            )
            assert written == ()
            assert (
                await list_project_documents(conn, workspace_id=ws, project_id=project.project_id)
                == ()
            )
            await txn.rollback()

    run_async(scenario())
