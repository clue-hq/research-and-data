"""L7's attachment names come from the durable rows: one path per file, whatever its family."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import AgentTurnRequest
from clue_api.agent_turn_submission import insert_submission
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.attachment_binding import DbAttachmentDescriber
from clue_api.chat.attachments import ValidatedAttachment
from clue_api.chat.uploads import record_chat_upload
from clue_db import db_lifespan
from clue_storage.fs import FsStorage
from tests.agents.conftest import artifact, constitution, domain_ref
from tests.api.test_project_document_context_refs_db import _seed, _submission_kwargs
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def _constitution(seeds: dict[str, Any]) -> Any:
    """The seeded workspace/project, with every constitution ref inside that workspace."""

    ws = seeds["ws"]
    return constitution(
        workspace_id=ws,
        project_id=seeds["project_id"],
        brand_id=seeds["brand_id"],
        project_card_ref=artifact("project-card.json", workspace_id=ws),
        budget_envelope_ref=artifact("budget.json", workspace_id=ws),
        resource_manifest_ref=artifact("resource-manifest.json", workspace_id=ws),
        focus_refs=(domain_ref("account-1", workspace_id=ws),),
    )


def test_every_family_is_named_at_its_one_attachments_path(tmp_path: Path) -> None:
    """Text, document and image alike: the worker syncs each to ``attachments/<filename>``."""

    async def scenario() -> None:
        storage = FsStorage(tmp_path)
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed(conn, storage)
            ws = seeds["ws"]

            @asynccontextmanager
            async def bound() -> AsyncIterator[AsyncConnection]:
                yield conn

            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=bound)

            async def attach(
                body: bytes, *, filename: str, media_type: str, family: Any
            ) -> ValidatedAttachment:
                ref = await artifacts.persist_body(
                    workspace_id=ws, data=body, media_type=media_type
                )
                row = await record_chat_upload(
                    conn,
                    workspace_id=ws,
                    user_id=seeds["user_id"],
                    filename=filename,
                    media_type=media_type,
                    ref=ref,
                )
                return ValidatedAttachment(
                    upload_id=row.upload_id, ref=ref, filename=filename, family=family
                )

            brief = await attach(
                b"# Brief\n\nWhat we want.\n",
                filename="brief.md",
                media_type="text/markdown",
                family="text",
            )
            report = await attach(
                b"%PDF-1.7\n",
                filename="report.pdf",
                media_type="application/pdf",
                family="document",
            )
            shot = await attach(
                b"png-bytes", filename="shot.png", media_type="image/png", family="image"
            )
            kwargs = _submission_kwargs(seeds, "describe")
            _row, created = await insert_submission(
                conn, attachment_refs=(brief, report, shot), **kwargs
            )
            assert created

            request = AgentTurnRequest(
                turn_id=kwargs["turn_id"],
                thread_id=seeds["thread_id"],
                constitution=_constitution(seeds),
                user_message_artifact_ref=artifact("user-message.txt", workspace_id=ws),
                attachment_refs=(brief.ref, report.ref, shot.ref),
                requested_at=datetime.now(UTC),
            )
            described = await DbAttachmentDescriber(conn_factory=bound).describe(request)

            for attached in (brief, report, shot):
                named = described[attached.ref.artifact_key]
                assert named.filename == attached.filename
                assert named.workspace_path == f"attachments/{attached.filename}"
                assert named.family == attached.family
            await txn.rollback()

    run_async(scenario())
