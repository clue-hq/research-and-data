"""A design run reads the files sent in its chat thread (spec 2026-10-30 §3.3).

The envelope lists the thread's files by reference; this read fetches their bytes from platform
storage on the platform loop, the same seam the seller's documents travel. A file whose bytes were
erased, or are missing, comes back named with the reason and no bytes — the turn still runs.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image
from sqlalchemy import text

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_design.envelopes import DesignTurnEnvelope
from clue_design.runs import work_id_for_run
from clue_storage import FsStorage
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>'


def _tiff() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (6, 4), (9, 9, 9)).save(out, format="TIFF")
    return out.getvalue()


def _envelope(workspace_id: str, project_id: str, files: list[dict[str, Any]]) -> Any:
    run_id = f"run_{uuid4().hex}"
    return DesignTurnEnvelope(
        kind="agent_turn",
        work_id=work_id_for_run(run_id),
        workspace_id=workspace_id,
        run_id=run_id,
        checkpoint_thread_id=run_id,
        document_id=None,
        project_id=project_id,
        config={
            "request": {"prompt": "p", "scene": {}},
            "leg": {"leg_id": "leg-1"},
            "delegation_bundle": {"brief": "b"},
            "attachments": files,
        },
    )


def _listed(ref: Any, filename: str, *, current: bool) -> dict[str, Any]:
    return {
        "filename": filename,
        "media_type": ref.media_type,
        "artifact_key": ref.artifact_key,
        "sha256": ref.sha256,
        "byte_count": ref.byte_count,
        "current": current,
    }


def test_a_design_run_reads_the_threads_files(tmp_path: Path) -> None:
    from clue_api.design_platform_reads import build_design_platform_reads_factory

    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = f"ws_dpra_{uuid4().hex[:8]}"
            project = await seed_project(conn, workspace_id, name="attachments")
            cf = conn_session_factory(conn)
            storage = FsStorage(tmp_path / "artifacts")
            store = DurableAgentArtifactStore(storage=storage, conn_factory=cf)

            async def put(data: bytes, media: str) -> Any:
                return await store.persist_body(
                    workspace_id=workspace_id, data=data, media_type=media
                )

            brief = await put(b"# Brief", "text/markdown")
            tiff = _tiff()
            scan = await put(tiff, "image/tiff")
            logo = await put(SVG, "image/svg+xml")
            gone = await put(b"\x89PNG\r\n\x1a\nold", "image/png")
            await conn.execute(
                text("UPDATE artifact SET erased_at = now() WHERE storage_key = :k"),
                {"k": gone.artifact_key},
            )
            lost = gone.model_copy(update={"artifact_key": f"{workspace_id}/{'f' * 64}"})

            envelope = _envelope(
                workspace_id,
                project.project_id,
                [
                    _listed(brief, "../brief.md", current=True),
                    _listed(scan, "scan.tif", current=True),
                    _listed(logo, "logo.svg", current=False),
                    _listed(gone, "old.png", current=False),
                    _listed(lost, "lost.png", current=False),
                ],
            )
            factory = build_design_platform_reads_factory(
                invoker=None,  # type: ignore[arg-type]
                storage=storage,
                conn_factory=cf,
            )
            reads = await asyncio.to_thread(factory, envelope)
            files = await asyncio.to_thread(reads.thread_attachments)
            by_name = {item.filename: item for item in files}

            assert [item.filename for item in files] == [
                "brief.md",
                "scan.tif",
                "logo.svg",
                "old.png",
                "lost.png",
            ]
            assert by_name["brief.md"].data == b"# Brief"
            assert by_name["brief.md"].current and by_name["brief.md"].viewable is None
            assert by_name["brief.md"].unavailable is None
            png, shown = by_name["scan.tif"].viewable
            assert shown == "image/png" and Image.open(io.BytesIO(png)).size == (6, 4)
            assert by_name["scan.tif"].data == tiff, "the original file is never changed"
            assert by_name["logo.svg"].viewable == (SVG, "image/svg+xml")
            assert (by_name["old.png"].unavailable, by_name["old.png"].data) == ("erased", b"")
            assert (by_name["lost.png"].unavailable, by_name["lost.png"].data) == ("missing", b"")
            # Read once for the run: a second call answers from the same files.
            assert await asyncio.to_thread(reads.thread_attachments) is files

    run_async(scenario())


def test_a_run_without_files_reads_none(tmp_path: Path) -> None:
    from clue_api.design_platform_reads import build_design_platform_reads_factory

    async def scenario() -> None:
        async with rollback_conn() as conn:
            factory = build_design_platform_reads_factory(
                invoker=None,  # type: ignore[arg-type]
                storage=FsStorage(tmp_path),
                conn_factory=conn_session_factory(conn),
            )
            envelope = _envelope("ws_none", "prj_none", [])
            envelope.config.pop("attachments")
            reads = await asyncio.to_thread(factory, envelope)
            assert await asyncio.to_thread(reads.thread_attachments) == ()

    run_async(scenario())


def test_the_budget_is_applied_before_any_bytes_are_read_and_one_failure_stays_one(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Review I-4: a long thread's files are not all read into memory; the current message's
    files come first, anything past the budget is named and never fetched, and one file that
    cannot be read does not take the others down."""

    from clue_api import design_platform_reads
    from clue_api.design_platform_reads import build_design_platform_reads_factory

    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = f"ws_dpra_{uuid4().hex[:8]}"
            project = await seed_project(conn, workspace_id, name="budget")
            cf = conn_session_factory(conn)
            storage = FsStorage(tmp_path / "artifacts")
            store = DurableAgentArtifactStore(storage=storage, conn_factory=cf)

            async def put(data: bytes, media: str) -> Any:
                return await store.persist_body(
                    workspace_id=workspace_id, data=data, media_type=media
                )

            old = await put(b"o" * 600, "application/pdf")
            broken = await put(b"b" * 10, "text/plain")
            now = await put(b"n" * 600, "application/pdf")

            class _Storage:
                gets: list[str] = []

                async def get(self, key: str) -> bytes:
                    type(self).gets.append(key)
                    if key == broken.artifact_key:
                        raise OSError("bucket hiccup")
                    return await storage.get(key)

            monkeypatch.setattr(design_platform_reads, "THREAD_ATTACHMENTS_MAX_BYTES", 1000)
            envelope = _envelope(
                workspace_id,
                project.project_id,
                [
                    _listed(old, "old.pdf", current=False),
                    _listed(broken, "broken.txt", current=False),
                    _listed(now, "now.pdf", current=True),
                ],
            )
            factory = build_design_platform_reads_factory(
                invoker=None,  # type: ignore[arg-type]
                storage=_Storage(),  # type: ignore[arg-type]
                conn_factory=cf,
            )
            reads = await asyncio.to_thread(factory, envelope)
            files = {
                item.filename: item for item in await asyncio.to_thread(reads.thread_attachments)
            }
            assert files["now.pdf"].data == b"n" * 600
            assert (files["old.pdf"].unavailable, files["old.pdf"].data) == ("over_budget", b"")
            assert old.artifact_key not in _Storage.gets
            assert files["broken.txt"].unavailable == "missing"

    run_async(scenario())
