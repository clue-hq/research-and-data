"""D2.5A: the O4 workspace seam is STRICT — X-Workspace-Id or 401.

Before this slice an absent header silently resolved to the dev workspace, so a miswired caller
read and wrote another tenant's rows and looked perfectly healthy doing it. These tests pin both
halves of the new contract: the refusal, and the exact, deliberate list of routes exempt from it.

The exemptions are exactly three, each because the caller *cannot* send a header:

* ``/build-info`` — the editor's engine handshake, read before any workspace context exists.
* ``/asset-store/{digest}`` — content-addressed public bytes the PUBLISHED page and the
  origin-"null" preview iframe load; a custom header would make them preflighted requests the
  wildcard CORS response cannot satisfy.
* ``/w/{workspace_id}/...`` — the O6b public serving group, which names its tenant in the PATH
  because an anonymous visitor sends no headers at all.

Plus one near-exemption: ``GET /agent/runs/{id}/events`` accepts ``?workspace_id=`` because
``EventSource`` cannot set request headers — same strictness, different carrier.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client, unique_run_id
from lumen_api.main import create_app


@pytest.fixture()
def app(tmp_path: Path):
    return create_app(tmp_path / "api.sqlite3")


@pytest.fixture()
def client(app) -> TestClient:
    return make_client(app)


@pytest.fixture()
def bare(app) -> TestClient:
    """A client that sends NO workspace header — the miswired caller."""
    return TestClient(app)


def test_a_request_without_the_workspace_header_is_refused(bare: TestClient) -> None:
    response = bare.get("/web/accounts")
    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["code"] == "workspace.header_required"
    assert detail["header"] == "X-Workspace-Id"


def test_the_refusal_covers_writes_and_tenant_free_editor_routes(bare: TestClient) -> None:
    # A write must not reach the store either...
    assert bare.post("/documents", json={"scene": {}}).status_code == 401
    # ...and a route that reads no tenant state but is still an editor call is inside the seam,
    # so the exemption list stays exactly three entries long.
    assert bare.get("/font-library").status_code == 401


def test_an_empty_header_is_treated_as_absent(app) -> None:
    empty = TestClient(app, headers={"X-Workspace-Id": ""})
    assert empty.get("/web/accounts").status_code == 401


def test_build_info_is_exempt(bare: TestClient) -> None:
    assert bare.get("/build-info").status_code == 200


def test_asset_store_bytes_are_exempt(bare: TestClient, app) -> None:
    # The published page and the origin-"null" preview iframe fetch these; they carry no header.
    payload = b"font-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    stored = Path(app.state.asset_store_root) / "sha256" / digest[:2] / digest
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(payload)

    response = bare.get(f"/asset-store/{digest}")
    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["Access-Control-Allow-Origin"] == "*"


def test_the_public_publish_group_is_exempt(bare: TestClient, workspace_id: str) -> None:
    """An anonymous visitor sends no header, so these routes must REACH their handler.

    A 404 (nothing published at that slug, through the fail-closed workspace-scoped read) is the
    proof: the request got past the seam. A 401 would mean the public page is unreachable. The
    happy path — a real publish rendering under ``/w/{ws}/p/{slug}`` — is covered by
    ``test_web_export.py``, which owns the export toolchain.
    """
    assert bare.get(f"/w/{workspace_id}/p/seam-page").status_code == 404
    assert bare.get(f"/w/{workspace_id}/p/seam-page/manifest.json").status_code == 404
    assert bare.get(f"/w/{workspace_id}/p-assets/{'a' * 64}.css").status_code == 404
    # An unknown tenant is refused the same way a missing page is — existence never leaks.
    assert bare.get("/w/ws_not_a_tenant/p/seam-page").status_code == 404


def test_the_run_event_stream_accepts_a_query_workspace_because_eventsource_cannot_send_headers(
    client: TestClient, bare: TestClient, workspace_id: str
) -> None:
    from lumen_api.design_store import HybridRepository

    run_id = unique_run_id("seam")
    repo = HybridRepository(workspace_id=workspace_id)
    repo.create_run(run_id, None)
    repo.complete_run(
        run_id, "succeeded", {"status": "proposed"}, "result", {"status": "proposed"}
    )

    # No header at all is still a 401 — strictness is not relaxed, only the carrier changes.
    assert bare.get(f"/agent/runs/{run_id}/events").status_code == 401
    streamed = bare.get(f"/agent/runs/{run_id}/events?workspace_id={workspace_id}")
    assert streamed.status_code == 200
    assert "event: done" in streamed.text
    # A header-carrying (non-browser) client needs no query param.
    assert "event: done" in client.get(f"/agent/runs/{run_id}/events").text


def test_the_stream_is_fail_closed_against_another_tenants_run(
    client: TestClient, bare: TestClient
) -> None:
    from lumen_api.design_store import HybridRepository

    run_id = unique_run_id("owned")
    repo = HybridRepository(workspace_id="ws_seam_owner")
    repo.create_run(run_id, None)

    # Naming someone else's workspace in the query string buys nothing you did not already have:
    # the run is simply absent from the caller's own tenant.
    assert (
        bare.get(f"/agent/runs/{run_id}/events?workspace_id=ws_seam_intruder").status_code
        == 404
    )
