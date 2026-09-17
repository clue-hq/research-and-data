"""Settings → Pages control plane (custom-domain publishing §7).

Harness: the projections app with the frontend-read flag on, the DB seam bound to one rolled-back
connection, and a principal whose role decides whether ``workspace.manage_settings`` is held.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import Request
from httpx import ASGITransport

from clue_api.chat import RequestPrincipal
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.frontend_read.app import frontend_read_workspace_resolver
from clue_api.projections_app import create_projections_app
from clue_auth.policy import permissions_for_role
from clue_config import load_settings
from clue_spine import create_workspace
from clue_storage import FsStorage
from tests._identity import fixture_membership_id, seed_principal
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

BASE = f"{FRONTEND_READ_PREFIX}/settings/pages"
USER_ID = "usr_pages_settings"
SUFFIX = "pages.test"


def _settings(**overrides: Any) -> Any:
    return load_settings(
        _env_file=None,
        frontend_read_enabled=True,
        arv2_display_generate_on_read=False,
        pages_system_suffix=SUFFIX,
        pages_public_scheme="https",
        pages_public_port=None,
        pages_cname_target="pages.test",
        **overrides,
    )


class TickingClock:
    """Each call is 10 s later than the last, so consecutive checks clear the 5 s rate limit;
    ``hold()`` freezes it to prove the limit."""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
        self.frozen = False

    def hold(self) -> None:
        self.frozen = True

    def __call__(self) -> datetime:
        if not self.frozen:
            self.now = self.now + timedelta(seconds=10)
        return self.now


def _app(
    conn: Any,
    tmp_path: Any,
    *,
    role: str,
    cloudflare: Any = None,
    resolver: Any = None,
    clock: Any = None,
) -> Any:
    app = create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=_settings(),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
        ingestion_storage=FsStorage(tmp_path / "blobs"),
    )
    # The route builder accepts injected fakes for the provider, the resolver and the clock; they
    # ride on ``app.state`` so a test can swap them without rebuilding the composition root.
    if cloudflare is not None:
        app.state.pages_cloudflare = cloudflare
    if resolver is not None:
        app.state.pages_resolver = resolver
    if clock is not None:
        app.state.pages_clock = clock

    async def _resolver(request: Request) -> str:
        workspace_id = request.headers["X-Workspace-Id"]
        request.state.clue_principal = RequestPrincipal(
            user_id=USER_ID,
            membership_id=fixture_membership_id(workspace_id=workspace_id, user_id=USER_ID),
            workspace_id=workspace_id,
            role_key=role,  # type: ignore[arg-type]
            permissions=permissions_for_role(role),
            authenticated_at=datetime(2026, 9, 17, 9, 0, tzinfo=UTC),
        )
        return workspace_id

    app.dependency_overrides[frontend_read_workspace_resolver] = _resolver
    return app


async def _workspace(conn: Any) -> str:
    ws = await create_workspace(conn, name="Acme " + uuid4().hex[:4], pages_system_suffix=SUFFIX)
    await seed_principal(conn, workspace_id=ws.workspace_id, user_id=USER_ID)
    return ws.workspace_id


def test_read_defaults_and_the_system_hostname(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            async with httpx.AsyncClient(
                transport=ASGITransport(app=_app(conn, tmp_path, role="viewer")),
                base_url="http://t",
            ) as client:
                response = await client.get(BASE, headers={"X-Workspace-Id": ws})
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["settings"] == {
                "fallbackUrl": None,
                "pageTitle": None,
                "pageDescription": None,
                "faviconUrl": None,
                "socialPreviewUrl": None,
            }
            assert body["systemHostname"]["hostname"].endswith("." + SUFFIX)
            assert body["systemHostname"]["url"] == "https://" + body["systemHostname"]["hostname"]
            assert body["systemHostname"]["label"] == body["systemHostname"][
                "hostname"
            ].removesuffix("." + SUFFIX)
            assert body["customHostname"] is None

    run_async(scenario())


def test_patch_needs_manage_settings_and_clears_with_null(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            headers = {"X-Workspace-Id": ws}
            async with httpx.AsyncClient(
                transport=ASGITransport(app=_app(conn, tmp_path, role="operator")),
                base_url="http://t",
            ) as client:
                denied = await client.patch(
                    BASE, json={"fallbackUrl": "https://www.acme.com"}, headers=headers
                )
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "PERMISSION_REQUIRED"
            async with httpx.AsyncClient(
                transport=ASGITransport(app=_app(conn, tmp_path, role="admin")),
                base_url="http://t",
            ) as client:
                ok = await client.patch(
                    BASE,
                    json={"fallbackUrl": "https://www.acme.com", "pageTitle": "Acme"},
                    headers=headers,
                )
                assert ok.status_code == 200, ok.text
                assert ok.json()["settings"]["fallbackUrl"] == "https://www.acme.com"
                cleared = await client.patch(BASE, json={"fallbackUrl": None}, headers=headers)
                assert cleared.json()["settings"]["fallbackUrl"] is None
                assert cleared.json()["settings"]["pageTitle"] == "Acme"
                bad = await client.patch(
                    BASE, json={"fallbackUrl": "http://insecure.example"}, headers=headers
                )
                assert bad.status_code == 422

    run_async(scenario())


def test_favicon_and_social_preview_uploads(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            headers = {"X-Workspace-Id": ws}
            async with httpx.AsyncClient(
                transport=ASGITransport(app=_app(conn, tmp_path, role="owner")),
                base_url="http://t",
            ) as client:
                favicon = await client.post(
                    f"{BASE}/favicon",
                    files={"file": ("f.png", b"\x89PNGfake", "image/png")},
                    headers=headers,
                )
                assert favicon.status_code == 200, favicon.text
                assert favicon.json()["settings"]["faviconUrl"].endswith("/favicon.ico")
                too_big = await client.post(
                    f"{BASE}/favicon",
                    files={"file": ("f.png", b"x" * (256 * 1024 + 1), "image/png")},
                    headers=headers,
                )
                assert too_big.status_code == 413
                wrong_type = await client.post(
                    f"{BASE}/favicon",
                    files={"file": ("f.gif", b"GIF89a", "image/gif")},
                    headers=headers,
                )
                assert wrong_type.status_code == 415
                social = await client.post(
                    f"{BASE}/social-preview",
                    files={"file": ("s.jpg", b"\xff\xd8fake", "image/jpeg")},
                    headers=headers,
                )
                assert social.status_code == 200
                assert "/asset-store/" in social.json()["settings"]["socialPreviewUrl"]

    run_async(scenario())


def test_label_change_is_validated_and_atomic(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            headers = {"X-Workspace-Id": ws}
            async with httpx.AsyncClient(
                transport=ASGITransport(app=_app(conn, tmp_path, role="admin")),
                base_url="http://t",
            ) as client:
                label = "acme-hq-" + uuid4().hex[:4]
                ok = await client.patch(
                    f"{BASE}/system-hostname", json={"label": label}, headers=headers
                )
                assert ok.status_code == 200, ok.text
                assert ok.json()["systemHostname"]["label"] == label
                reserved = await client.patch(
                    f"{BASE}/system-hostname", json={"label": "www"}, headers=headers
                )
                assert reserved.status_code == 422
                assert reserved.json()["error"]["code"] == "label_reserved"

    run_async(scenario())
