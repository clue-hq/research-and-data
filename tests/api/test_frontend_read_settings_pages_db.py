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
from clue_api.cloudflare_custom_hostnames import CloudflareError, CustomHostnameRecord
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


async def _workspace_named(conn: Any, name: str) -> str:
    ws = await create_workspace(conn, name=f"{name} " + uuid4().hex[:4], pages_system_suffix=SUFFIX)
    await seed_principal(conn, workspace_id=ws.workspace_id, user_id=USER_ID)
    return ws.workspace_id


async def _workspace(conn: Any) -> str:
    return await _workspace_named(conn, "Acme")


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


class FakeCloudflare:
    def __init__(self) -> None:
        self.records: dict[str, Any] = {}
        self.create_error: CloudflareError | None = None
        self.delete_error: CloudflareError | None = None
        self.calls: list[tuple[str, str]] = []

    async def create(self, hostname: str):  # type: ignore[no-untyped-def]
        self.calls.append(("create", hostname))
        if self.create_error:
            raise self.create_error
        record = CustomHostnameRecord(
            id=f"cf_{hostname}",
            status="pending",
            ssl_status="pending_validation",
            ownership_txt_name=f"_cf-custom-hostname.{hostname}",
            ownership_txt_value="tok-" + hostname,
            verification_errors=(),
            ssl_validation_errors=(),
        )
        self.records[record.id] = record
        return record

    async def get(self, custom_hostname_id: str):  # type: ignore[no-untyped-def]
        self.calls.append(("get", custom_hostname_id))
        return self.records.get(custom_hostname_id)

    async def delete(self, custom_hostname_id: str) -> None:
        self.calls.append(("delete", custom_hostname_id))
        if self.delete_error:
            raise self.delete_error
        self.records.pop(custom_hostname_id, None)


class FakeResolver:
    def __init__(self) -> None:
        self.cname: dict[str, str] = {}
        self.txt: dict[str, list[str]] = {}

    def resolve(self, name: str, rdtype: str) -> list[str]:
        if rdtype == "CNAME":
            return [self.cname[name]] if name in self.cname else []
        return list(self.txt.get(name, []))


def test_connect_refusals_in_spec_order(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            other = await _workspace_named(conn, "Other")
            cf, dns = FakeCloudflare(), FakeResolver()
            app = _app(conn, tmp_path, role="admin", cloudflare=cf, resolver=dns)
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as client:
                for hostname, code in [
                    ("not a host", "hostname_invalid"),
                    ("acme.com", "hostname_is_apex"),
                    ("x.pages.test", "hostname_reserved"),
                ]:
                    r = await client.post(
                        f"{BASE}/custom-hostname",
                        json={"hostname": hostname},
                        headers={"X-Workspace-Id": ws},
                    )
                    assert (r.status_code, r.json()["error"]["code"]) == (422, code), r.text
                taken = await client.post(
                    f"{BASE}/custom-hostname",
                    json={"hostname": "go.acme.example"},
                    headers={"X-Workspace-Id": other},
                )
                assert taken.status_code == 201
                again = await client.post(
                    f"{BASE}/custom-hostname",
                    json={"hostname": "go.acme.example"},
                    headers={"X-Workspace-Id": ws},
                )
                assert (again.status_code, again.json()["error"]["code"]) == (409, "hostname_taken")
                assert "already connected to a workspace" in again.json()["error"]["message"]
                first = await client.post(
                    f"{BASE}/custom-hostname",
                    json={"hostname": "go.mine.example"},
                    headers={"X-Workspace-Id": ws},
                )
                assert first.status_code == 201
                second = await client.post(
                    f"{BASE}/custom-hostname",
                    json={"hostname": "go2.mine.example"},
                    headers={"X-Workspace-Id": ws},
                )
                assert (second.status_code, second.json()["error"]["code"]) == (
                    409,
                    "custom_hostname_exists",
                )
            assert cf.calls.count(("create", "go.mine.example")) == 1

    run_async(scenario())


def test_provider_refusal_leaves_no_row(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            cf, dns = FakeCloudflare(), FakeResolver()
            cf.create_error = CloudflareError(
                "Duplicate custom hostname found.", status=409, retryable=False
            )
            app = _app(conn, tmp_path, role="admin", cloudflare=cf, resolver=dns)
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as client:
                r = await client.post(
                    f"{BASE}/custom-hostname",
                    json={"hostname": "go.dup.example"},
                    headers={"X-Workspace-Id": ws},
                )
                assert (r.status_code, r.json()["error"]["code"]) == (502, "provider_error")
                assert "Duplicate" in r.json()["error"]["message"]
                read = await client.get(BASE, headers={"X-Workspace-Id": ws})
                assert read.json()["customHostname"] is None

    run_async(scenario())


def test_check_walks_the_ladder_and_read_refreshes(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            cf, dns, clock = FakeCloudflare(), FakeResolver(), TickingClock()
            app = _app(conn, tmp_path, role="admin", cloudflare=cf, resolver=dns, clock=clock)
            headers = {"X-Workspace-Id": ws}
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as client:
                created = (
                    await client.post(
                        f"{BASE}/custom-hostname",
                        json={"hostname": "go.walk.example"},
                        headers=headers,
                    )
                ).json()["customHostname"]
                assert created["status"] == "pending_dns"
                assert [r["type"] for r in created["records"]] == ["CNAME", "TXT"]
                assert created["records"][0]["required"] == "pages.test"
                assert created["records"][1]["name"] == "_cf-custom-hostname.go.walk.example"
                dns.cname["go.walk.example"] = "pages.test"
                step1 = (
                    await client.post(f"{BASE}/custom-hostname/check", headers=headers)
                ).json()["customHostname"]
                assert (
                    step1["status"] == "verifying_ownership"
                    and step1["records"][0]["ok"]
                    and not step1["records"][1]["ok"]
                )
                dns.txt["_cf-custom-hostname.go.walk.example"] = ["tok-go.walk.example"]
                step2 = (
                    await client.post(f"{BASE}/custom-hostname/check", headers=headers)
                ).json()["customHostname"]
                assert step2["status"] == "issuing_certificate"
                cf.records["cf_go.walk.example"] = CustomHostnameRecord(
                    id="cf_go.walk.example",
                    status="active",
                    ssl_status="active",
                    ownership_txt_name="_cf-custom-hostname.go.walk.example",
                    ownership_txt_value="tok-go.walk.example",
                    verification_errors=(),
                    ssl_validation_errors=(),
                )
                step3 = (
                    await client.post(f"{BASE}/custom-hostname/check", headers=headers)
                ).json()["customHostname"]
                assert (
                    step3["status"] == "active"
                    and step3["url"] == "https://go.walk.example"
                    and step3["error"] is None
                )
                # rate limit: a second check inside 5 s returns the stored state without touching
                # the provider
                clock.frozen = True
                calls_before = len(cf.calls)
                await client.post(f"{BASE}/custom-hostname/check", headers=headers)
                assert len(cf.calls) == calls_before

    run_async(scenario())


def test_remove_is_ordered_and_survives_a_provider_outage(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            cf, dns = FakeCloudflare(), FakeResolver()
            app = _app(
                conn, tmp_path, role="admin", cloudflare=cf, resolver=dns, clock=TickingClock()
            )
            headers = {"X-Workspace-Id": ws}
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as client:
                await client.post(
                    f"{BASE}/custom-hostname",
                    json={"hostname": "go.gone.example"},
                    headers=headers,
                )
                cf.delete_error = CloudflareError("down", status=503, retryable=True)
                failed = await client.delete(f"{BASE}/custom-hostname", headers=headers)
                assert failed.status_code == 502 and failed.json()["error"]["code"] == (
                    "provider_error"
                )
                assert failed.json()["error"]["retryable"] is True
                stuck = (await client.get(BASE, headers=headers)).json()["customHostname"]
                assert stuck["status"] == "disconnecting"
                cf.delete_error = None
                # check-now retries the delete
                completed = await client.post(f"{BASE}/custom-hostname/check", headers=headers)
                assert completed.json()["customHostname"] is None
                assert cf.calls[-1] == ("delete", "cf_go.gone.example")
                assert (
                    await client.delete(f"{BASE}/custom-hostname", headers=headers)
                ).status_code == 404
                await client.post(
                    f"{BASE}/custom-hostname",
                    json={"hostname": "go.gone2.example"},
                    headers=headers,
                )
                assert (
                    await client.delete(f"{BASE}/custom-hostname", headers=headers)
                ).status_code == 204
                assert (await client.get(BASE, headers=headers)).json()["customHostname"] is None

    run_async(scenario())


def test_connect_without_a_configured_provider_is_503(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            app = _app(conn, tmp_path, role="admin", cloudflare=None, resolver=FakeResolver())
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as client:
                r = await client.post(
                    f"{BASE}/custom-hostname",
                    json={"hostname": "go.nocf.example"},
                    headers={"X-Workspace-Id": ws},
                )
            assert (r.status_code, r.json()["error"]["code"]) == (503, "PROVIDER_NOT_CONFIGURED")

    run_async(scenario())


def test_check_now_retries_a_stuck_removal_even_inside_the_rate_limit(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            cf, dns, clock = FakeCloudflare(), FakeResolver(), TickingClock()
            app = _app(conn, tmp_path, role="admin", cloudflare=cf, resolver=dns, clock=clock)
            headers = {"X-Workspace-Id": ws}
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as client:
                await client.post(
                    f"{BASE}/custom-hostname",
                    json={"hostname": "go.stuck.example"},
                    headers=headers,
                )
                # stamps last_checked_at
                await client.post(f"{BASE}/custom-hostname/check", headers=headers)
                clock.frozen = True  # every later clock read is within 5 s of that stamp
                cf.delete_error = CloudflareError("down", status=503, retryable=True)
                assert (
                    await client.delete(f"{BASE}/custom-hostname", headers=headers)
                ).status_code == 502
                cf.delete_error = None
                # a passive GET must not retry (row stays disconnecting, no provider call)
                calls_before = len(cf.calls)
                assert (await client.get(BASE, headers=headers)).json()["customHostname"][
                    "status"
                ] == "disconnecting"
                assert len(cf.calls) == calls_before
                # Check now retries despite the rate limit and completes the removal
                done = await client.post(f"{BASE}/custom-hostname/check", headers=headers)
                assert done.status_code == 200 and done.json()["customHostname"] is None
                assert cf.calls[-1] == ("delete", "cf_go.stuck.example")

    run_async(scenario())
