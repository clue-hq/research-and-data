"""A chat's cold load reads its stored texts together and from the content cache (2026-10-15).

Opening a chat with nine messages took 5.3 s: each message's text, then each tagged document's
label, was fetched from object storage one after another. These tests pin the fix — fetched
together, served from the cache on a reload — and that every reason a body is withheld survives
unchanged: unavailable, digest mismatch, not text, over budget, missing blob.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.chat.composer_context import context_ref_presentations
from clue_api.chat.message_bodies import hydrate_message_bodies
from clue_api.knowledge_bytes import clear_knowledge_byte_cache
from clue_storage import ArtifactNotFound
from tests._workspace import seed_project
from tests.api.test_knowledge_bytes_db import _SlowStorage
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401
    require_profiling_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _Storage(_MemoryStorage):
    """The in-memory double, raising what a real backend raises for a missing object."""

    async def get(self, key: str) -> bytes:
        if key not in self.blobs:
            raise ArtifactNotFound(key)
        return self.blobs[key]


async def _bodies(conn, ws: str, storage: _MemoryStorage, texts: list[str]):  # noqa: ANN001
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_session_factory(conn))
    refs = []
    for body in texts:
        ref = await artifacts.persist_body(
            workspace_id=ws, data=body.encode(), media_type="text/markdown"
        )
        refs.append((ref.artifact_key, ref.sha256))
    return refs


def test_a_pages_message_texts_are_fetched_together_and_a_reload_skips_storage() -> None:
    async def scenario() -> None:
        clear_knowledge_byte_cache()
        async with rollback_conn() as conn:
            ws = "ws-chat-speed-bodies"
            await seed_project(conn, ws, name="Chat speed")
            storage = _MemoryStorage()
            refs = await _bodies(conn, ws, storage, [f"message {n}" for n in range(9)])
            slow = _SlowStorage(storage)
            first = await hydrate_message_bodies(
                conn, storage=slow, workspace_id=ws, references=refs
            )
            assert [first[key].body for key, _ in refs] == [f"message {n}" for n in range(9)]
            assert slow.gets == 9 and slow.peak > 1
            slow.gets = 0
            again = await hydrate_message_bodies(
                conn, storage=slow, workspace_id=ws, references=refs
            )
            assert again == first
            assert slow.gets == 0

    run_async(scenario())


def test_every_reason_a_body_is_withheld_survives() -> None:
    async def scenario() -> None:
        clear_knowledge_byte_cache()
        async with rollback_conn() as conn:
            ws = "ws-chat-speed-reasons"
            await seed_project(conn, ws, name="Chat speed reasons")
            storage = _Storage()
            ok, gone, big_a, big_b = await _bodies(
                conn, ws, storage, ["fine", "lost", "a" * 600, "b" * 600]
            )
            del storage.blobs[gone[0]]
            unknown = ("ws-chat-speed-reasons/" + "0" * 64, "0" * 64)
            wrong_digest = (ok[0], "f" * 64)
            result = await hydrate_message_bodies(
                conn,
                storage=storage,
                workspace_id=ws,
                references=[ok, gone, unknown, big_a, big_b],
                budget_bytes=1000,
            )
            assert result[ok[0]].body == "fine"
            assert result[gone[0]].reason == "artifact_missing"
            assert result[unknown[0]].reason == "unavailable"
            assert result[big_a[0]].body == "a" * 600
            assert result[big_b[0]].reason == "budget"
            mismatch = await hydrate_message_bodies(
                conn, storage=storage, workspace_id=ws, references=[wrong_digest]
            )
            assert mismatch[ok[0]].reason == "digest_mismatch"
            # A blob whose bytes were changed in storage is withheld even when it was cached
            # before: the cache is keyed by the digest the message committed to.
            storage.blobs[big_a[0]] = b"tampered"
            clear_knowledge_byte_cache()
            tampered = await hydrate_message_bodies(
                conn, storage=storage, workspace_id=ws, references=[big_a]
            )
            assert tampered[big_a[0]].reason == "digest_mismatch"

    run_async(scenario())


def test_tagged_document_labels_are_read_together() -> None:
    async def scenario() -> None:
        clear_knowledge_byte_cache()
        async with rollback_conn() as conn:
            ws = "ws-chat-speed-labels"
            project = await seed_project(conn, ws, name="Chat speed labels")
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            refs = []
            for n in range(5):
                ref = await artifacts.persist_body(
                    workspace_id=ws,
                    data=f"---\ntitle: Plan {n}\n---\n\n# Plan {n}\n".encode(),
                    media_type="text/markdown",
                )
                document_id = uuid.uuid4()
                await conn.execute(
                    text(
                        "INSERT INTO brand_knowledge_document (document_id, workspace_id, "
                        " brand_id, project_id, folder, path, kind, version, status, "
                        " artifact_key, artifact_sha256) VALUES (:id, :ws, :brand, :project, "
                        " 'project', :path, 'project-plan', 1, 'ready', :key, :sha)"
                    ),
                    {
                        "id": document_id,
                        "ws": ws,
                        "brand": project.brand_id,
                        "project": project.project_id,
                        "path": f"project/plan-{n}.md",
                        "key": ref.artifact_key,
                        "sha": ref.sha256,
                    },
                )
                refs.append(
                    SimpleNamespace(object_type="project_document", object_id=str(document_id))
                )
            slow = _SlowStorage(storage)
            labels = await context_ref_presentations(
                conn, workspace_id=ws, refs=tuple(refs), storage=slow
            )
            assert sorted(v["label"] for v in labels.values()) == [f"Plan {n}" for n in range(5)]
            assert slow.gets == 5 and slow.peak > 1

    run_async(scenario())


def test_the_slow_storage_double_really_overlaps() -> None:
    # Guards the guard: the peak counter only rises above one when fetches truly overlap.
    async def scenario() -> None:
        storage = _MemoryStorage()
        storage.blobs["k"] = b"x"
        slow = _SlowStorage(storage)
        await slow.get("k")
        await slow.get("k")
        assert slow.peak == 1
        await asyncio.gather(slow.get("k"), slow.get("k"))
        assert slow.peak == 2

    run_async(scenario())
