"""``/frontend/v1/uploads`` — the receipt a person gets, and the bytes behind the chip.

The walk is an attachment's whole life on this surface against the real tables: a PNG posted as
multipart comes back as a receipt naming the file the person chose, its bytes are served again
under the stored media type, a PDF is refused by type rather than stored, and another workspace's
upload is *absent* — the same 404 an upload that never existed gets.

The client is ``httpx`` over ``ASGITransport`` rather than ``TestClient``, and the connection seam
is the test's own rolled-back transaction: ``TestClient`` opens a fresh event loop per request, and
an asyncpg connection cannot be used from a loop other than the one that opened it. This is the
same shape ``test_frontend_read_project_documents_db`` uses for the same reason.

Refusals are asserted as ``{"detail": {"code", "message"}}`` because the router is mounted on a
bare app here: the FI-1 envelope that turns that into ``{"error": {"code", "message",
"requestId"}}`` is installed by ``install_frontend_read_surface``, not by the router under test
(its own mapping of a ``detail`` dict's ``code`` is covered in ``test_frontend_read_app``).

Spec: docs/superpowers/specs/archive/2026-09-18-chat-attachments-design.md.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read.app import build_frontend_read_router
from clue_config import Secrets, Settings
from clue_storage.fs import FsStorage
from tests._workspace import seed_workspace
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _client(conn: AsyncConnection, tmp_path: Path, ws: str) -> httpx.AsyncClient:
    settings = Settings(
        _env_file=None,
        frontend_read_enabled=True,
        projections_auth_mode="local_header",
        auth_enabled=False,
    )
    app = FastAPI()
    app.include_router(
        build_frontend_read_router(
            settings=settings,
            secrets=Secrets(),
            conn_factory=conn_session_factory(conn),
            evidence_storage=FsStorage(tmp_path),
        )
    )
    return httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://uploads",
        headers={"X-Workspace-Id": ws},
    )


def test_upload_then_read_bytes(tmp_path: Path) -> None:
    run_async(_upload_then_read_bytes(tmp_path))


async def _upload_then_read_bytes(tmp_path: Path) -> None:
    async with rollback_conn(seed_pack=False) as conn:
        ws = await seed_workspace(conn, f"ws_upl_route_{uuid4().hex[:8]}")
        async with _client(conn, tmp_path, ws) as client:
            response = await client.post(
                "/frontend/v1/uploads", files={"file": ("shot.png", PNG, "image/png")}
            )
            assert response.status_code == 201, response.text
            data = response.json()["data"]
            assert data["filename"] == "shot.png" and data["media_type"] == "image/png"
            assert data["byte_count"] == len(PNG)
            served = await client.get(f"/frontend/v1/uploads/{data['upload_id']}/bytes")
        assert served.status_code == 200 and served.content == PNG
        assert served.headers["content-type"].startswith("image/png")
        assert served.headers["content-disposition"] == 'inline; filename="shot.png"'


def test_upload_refuses_a_pdf(tmp_path: Path) -> None:
    run_async(_upload_refuses_a_pdf(tmp_path))


async def _upload_refuses_a_pdf(tmp_path: Path) -> None:
    async with rollback_conn(seed_pack=False) as conn:
        ws = await seed_workspace(conn, f"ws_upl_route_{uuid4().hex[:8]}")
        async with _client(conn, tmp_path, ws) as client:
            response = await client.post(
                "/frontend/v1/uploads", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}
            )
        assert response.status_code == 415
        assert response.json()["detail"]["code"] == "UPLOAD_UNSUPPORTED_TYPE"


def test_bytes_are_absent_for_another_workspace(tmp_path: Path) -> None:
    run_async(_bytes_are_absent_for_another_workspace(tmp_path))


async def _bytes_are_absent_for_another_workspace(tmp_path: Path) -> None:
    async with rollback_conn(seed_pack=False) as conn:
        ws = await seed_workspace(conn, f"ws_upl_route_{uuid4().hex[:8]}")
        other = await seed_workspace(conn, f"ws_upl_route_{uuid4().hex[:8]}")
        async with _client(conn, tmp_path, ws) as client:
            posted = await client.post(
                "/frontend/v1/uploads", files={"file": ("n.md", b"# n", "text/markdown")}
            )
        assert posted.status_code == 201, posted.text
        upload_id = posted.json()["data"]["upload_id"]
        async with _client(conn, tmp_path, other) as foreign:
            absent = await foreign.get(f"/frontend/v1/uploads/{upload_id}/bytes")
        assert absent.status_code == 404


def test_bytes_are_absent_once_the_artifact_is_erased(tmp_path: Path) -> None:
    run_async(_bytes_are_absent_once_the_artifact_is_erased(tmp_path))


async def _bytes_are_absent_once_the_artifact_is_erased(tmp_path: Path) -> None:
    """An erased artifact is a 404 with the route's own code, never a 500 from the store."""

    async with rollback_conn(seed_pack=False) as conn:
        ws = await seed_workspace(conn, f"ws_upl_route_{uuid4().hex[:8]}")
        async with _client(conn, tmp_path, ws) as client:
            posted = await client.post(
                "/frontend/v1/uploads", files={"file": ("gone.png", PNG, "image/png")}
            )
            assert posted.status_code == 201, posted.text
            data = posted.json()["data"]
            await conn.execute(
                text("UPDATE artifact SET erased_at = now() WHERE storage_key = :key"),
                {"key": data["artifact_key"]},
            )
            served = await client.get(f"/frontend/v1/uploads/{data['upload_id']}/bytes")
        assert served.status_code == 404
        assert served.json()["detail"]["code"] == "UPLOAD_NOT_FOUND"


def test_an_uploaded_svg_is_served_sandboxed(tmp_path: Path) -> None:
    """Review I-5 (2026-10-30): an SVG is served from the app's own origin, so a script inside it
    would run with the viewer's session if opened in a tab. The bytes are served sandboxed."""

    run_async(_an_uploaded_svg_is_served_sandboxed(tmp_path))


async def _an_uploaded_svg_is_served_sandboxed(tmp_path: Path) -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    async with rollback_conn(seed_pack=False) as conn:
        ws = await seed_workspace(conn, f"ws_upl_route_{uuid4().hex[:8]}")
        async with _client(conn, tmp_path, ws) as client:
            response = await client.post(
                "/frontend/v1/uploads", files={"file": ("logo.svg", svg, "image/svg+xml")}
            )
            assert response.status_code == 201, response.text
            served = await client.get(
                f"/frontend/v1/uploads/{response.json()['data']['upload_id']}/bytes"
            )
        assert served.status_code == 200
        assert served.headers["content-security-policy"] == "sandbox; default-src 'none'"
        assert served.headers["x-content-type-options"] == "nosniff"
