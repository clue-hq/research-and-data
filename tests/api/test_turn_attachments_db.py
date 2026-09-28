"""A past turn's image attachments read back for the conversation layer; text stays out."""

from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from sqlalchemy import text

from clue_agents.contracts import ArtifactRef
from clue_api.agent_turn_submission import insert_submission
from clue_api.chat.attachments import ValidatedAttachment
from clue_api.chat.uploads import record_chat_upload
from clue_api.turn_attachments import turn_image_refs
from clue_db import db_lifespan
from clue_storage.fs import FsStorage
from tests.api.test_project_document_context_refs_db import _seed, _submission_kwargs
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

# agent_turn_wiring._REF_NAMESPACE: the rows this test plants carry the same deterministic ids a
# real submission's would, so they are the rows the loader will meet in production.
_REF_NAMESPACE = UUID("9431adab-a359-59ee-b2f3-af522f93016b")


async def _upload(conn, seeds, *, sha: str, media_type: str) -> ArtifactRef:
    ws = seeds["ws"]
    key = f"{ws}/{sha}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            " size_bytes) VALUES (:key, :ws, :sha, :media, 8)"
        ),
        {"key": key, "ws": ws, "sha": sha, "media": media_type},
    )
    return ArtifactRef(
        workspace_id=ws,
        artifact_key=key,
        sha256=sha,
        media_type=media_type,
        byte_count=8,
    )


async def _insert_turn(conn, seeds, turn_id) -> None:
    execution_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
            " pin_manifest_hash) VALUES (:id, :ws, :project, 'human', :sha, :sha)"
        ),
        {
            "id": execution_id,
            "ws": seeds["ws"],
            "project": seeds["project_id"],
            "sha": seeds["sha"],
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, "
            " resource_manifest_sha256, retention_class, requested_at) "
            "VALUES (:id, :execution, :ws, :project, :thread, :actor, 'head_of_abm', "
            " 'root-turn-attachments', 'head-of-abm', 'v1', :sha, :key, :sha, :sha, "
            " 'standard', now())"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "ws": seeds["ws"],
            "project": seeds["project_id"],
            "thread": seeds["thread_id"],
            "actor": seeds["user_id"],
            "sha": seeds["sha"],
            "key": seeds["artifact_key"],
        },
    )


async def _insert_attachment_ref(conn, *, turn_id, ordinal: int, ref: ArtifactRef) -> None:
    """Plant the row agent_turn_wiring._insert_artifact_ref writes for an attachment."""

    await conn.execute(
        text(
            "INSERT INTO agent_artifact_ref "
            "(id, turn_id, workspace_id, owner_kind, owner_id, ref_role, ordinal, "
            " artifact_key, artifact_sha256, retention_class) "
            "SELECT :id, :turn_id, :ws, 'turn', :turn_id, 'attachment', :ordinal, "
            " :key, :sha, t.retention_class FROM agent_turn t "
            "WHERE t.id=:turn_id AND t.workspace_id=:ws"
        ),
        {
            "id": uuid5(_REF_NAMESPACE, f"{turn_id}:attachment:{ordinal}"),
            "turn_id": turn_id,
            "ws": ref.workspace_id,
            "ordinal": ordinal,
            "key": ref.artifact_key,
            "sha": ref.sha256,
        },
    )


def test_a_turns_images_read_back_and_its_text_files_do_not(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed(conn, FsStorage(tmp_path))
            ws = seeds["ws"]
            image = await _upload(conn, seeds, sha="e" * 64, media_type="image/png")
            note = await _upload(conn, seeds, sha="f" * 64, media_type="text/markdown")
            uploads = [
                await record_chat_upload(
                    conn,
                    workspace_id=ws,
                    user_id=seeds["user_id"],
                    filename=filename,
                    media_type=ref.media_type,
                    ref=ref,
                )
                for ref, filename in ((image, "shot.png"), (note, "note.md"))
            ]
            kwargs = _submission_kwargs(seeds, "turn-images")
            turn_id = kwargs["turn_id"]
            _row, created = await insert_submission(
                conn,
                attachment_refs=(
                    ValidatedAttachment(
                        upload_id=uploads[0].upload_id,
                        ref=image,
                        filename="shot.png",
                        family="image",
                    ),
                    ValidatedAttachment(
                        upload_id=uploads[1].upload_id,
                        ref=note,
                        filename="note.md",
                        family="text",
                    ),
                ),
                **kwargs,
            )
            assert created
            await _insert_turn(conn, seeds, turn_id)
            await _insert_attachment_ref(conn, turn_id=turn_id, ordinal=0, ref=image)
            await _insert_attachment_ref(conn, turn_id=turn_id, ordinal=1, ref=note)

            assert await turn_image_refs(conn, workspace_id=ws, turn_ids=[turn_id]) == {
                turn_id: (image,)
            }
            await txn.rollback()

    run_async(scenario())


def test_another_workspace_sees_none_of_the_turns_images(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed(conn, FsStorage(tmp_path))
            image = await _upload(conn, seeds, sha="a" * 64, media_type="image/jpeg")
            turn_id = uuid5(NAMESPACE_URL, f"turn-attachments-scope:{seeds['ws']}")
            await _insert_turn(conn, seeds, turn_id)
            await _insert_attachment_ref(conn, turn_id=turn_id, ordinal=0, ref=image)

            assert (
                await turn_image_refs(conn, workspace_id="ws_someone_else", turn_ids=[turn_id])
                == {}
            )
            await txn.rollback()

    run_async(scenario())


def test_an_erased_image_is_never_named_again(tmp_path: Path) -> None:
    """A tombstoned image must drop out of history, not merely fail to read.

    The durable store refuses to read a tombstoned artifact, so naming one here would raise
    ArtifactNotFound on every later turn of the thread — the image would take the conversation
    down with it.
    """

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed(conn, FsStorage(tmp_path))
            ws = seeds["ws"]
            kept = await _upload(conn, seeds, sha="c" * 64, media_type="image/png")
            erased = await _upload(conn, seeds, sha="d" * 64, media_type="image/png")
            turn_id = uuid5(NAMESPACE_URL, f"turn-attachments-erased:{ws}")
            await _insert_turn(conn, seeds, turn_id)
            await _insert_attachment_ref(conn, turn_id=turn_id, ordinal=0, ref=kept)
            await _insert_attachment_ref(conn, turn_id=turn_id, ordinal=1, ref=erased)
            await conn.execute(
                text(
                    "INSERT INTO agent_artifact_tombstone "
                    "(workspace_id, artifact_key, subject_entity_id, reason_code) "
                    "VALUES (:ws, :key, :subject, 'dsar_erasure')"
                ),
                {"ws": ws, "key": erased.artifact_key, "subject": uuid4()},
            )

            assert await turn_image_refs(conn, workspace_id=ws, turn_ids=[turn_id]) == {
                turn_id: (kept,)
            }
            await txn.rollback()

    run_async(scenario())
