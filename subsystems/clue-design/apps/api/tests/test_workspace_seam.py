"""D2.5A: the O4 workspace seam is STRICT — X-Workspace-Id or 401.

Before this slice an absent header silently resolved to the dev workspace, so a miswired caller
read and wrote another tenant's rows and looked perfectly healthy doing it. These tests pin both
halves of the new contract: the refusal, and the exact, deliberate list of routes exempt from it.

The exemptions are exactly two (they were three until the ``/w/`` group below was deleted),
each because the caller *cannot* send a header:

* ``/build-info`` — the editor's engine handshake, read before any workspace context exists.
* ``/asset-store/{digest}`` — content-addressed public bytes the PUBLISHED page and the
  origin-"null" preview iframe load; a custom header would make them preflighted requests the
  wildcard CORS response cannot satisfy.
* ``/w/{workspace_id}/...`` — the O6b public serving group, which named its tenant in the PATH
  because an anonymous visitor sends no headers at all. **DELETED by custom-domain publishing
  S1**: the page origin serves published pages, so this app has no public surface at all and the
  exemption list is down to two. The test below keeps a probe on the old prefix as the proof the
  group is gone.

There used to be a fourth, near-exemption: ``GET /agent/runs/{id}/events`` accepted
``?workspace_id=`` because ``EventSource`` cannot set request headers. **D7 closed it.** The stream
is now opened with a single-use token, minted through a header-authenticated ``POST
/agent/runs/{id}/stream-token``, and the tenant is read off the token row. So the events GET is
headerless-but-*token-gated* (not exempt: it is authenticated, just not by a header it cannot
send), and the mint POST is inside the seam like everything else. The two tests at the bottom pin
exactly that.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clue_design.storage import SOURCE_KEY_ASSET

from conftest import make_blob_store, make_client, unique_run_id
from lumen_api.main import create_app


@pytest.fixture()
def app(tmp_path: Path, design_storage):
    return create_app(tmp_path / "engine-cache", storage=design_storage)


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
    # D4: the bytes are durable in a WORKSPACE's storage, and this route resolves across
    # tenants (R-D4-7) — which is exactly what keeps it header-free.
    payload = b"font-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    make_blob_store(app).register(
        payload, media_type="font/woff2", source_key=SOURCE_KEY_ASSET
    )

    response = bare.get(f"/asset-store/{digest}")
    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["Access-Control-Allow-Origin"] == "*"


def test_the_public_publish_group_is_gone(bare: TestClient, workspace_id: str) -> None:
    """The O6b interim serving group no longer exists on this app (custom-domain publishing S1).

    A 404 here is route-table absence, not a fail-closed read: the design API serves no public
    page at all now — the page origin does, and ``tests/page_origin/test_routes.py`` owns that
    contract. This probe stays so a re-introduced ``/w/`` surface cannot land unnoticed.
    """
    assert bare.get(f"/w/{workspace_id}/p/seam-page").status_code == 404


def test_the_run_event_stream_is_token_gated_and_takes_no_workspace_parameter(
    client: TestClient, bare: TestClient, workspace_id: str
) -> None:
    from lumen_api.design_store import HybridRepository

    run_id = unique_run_id("seam")
    repo = HybridRepository(workspace_id=workspace_id)
    repo.create_run(run_id, None)
    repo.complete_run(
        run_id, "succeeded", {"status": "proposed"}, "result", {"status": "proposed"}
    )

    # The MINT is inside the seam: no header, no token.
    assert bare.post(f"/agent/runs/{run_id}/stream-token").status_code == 401
    minted = client.post(f"/agent/runs/{run_id}/stream-token")
    assert minted.status_code == 200
    token = minted.json()["stream_token"]

    # The GET needs no header — but a naked GET buys nothing, and neither does naming a workspace.
    assert bare.get(f"/agent/runs/{run_id}/events").status_code == 422
    assert (
        bare.get(f"/agent/runs/{run_id}/events?workspace_id={workspace_id}").status_code == 422
    )
    streamed = bare.get(f"/agent/runs/{run_id}/events?stream_token={token}")
    assert streamed.status_code == 200
    assert "event: done" in streamed.text


def test_the_stream_is_fail_closed_against_another_tenants_run(
    client: TestClient, bare: TestClient
) -> None:
    from lumen_api.design_store import HybridRepository

    run_id = unique_run_id("owned")
    repo = HybridRepository(workspace_id="ws_seam_owner")
    repo.create_run(run_id, None)

    # The intruder holds a valid workspace header — and still cannot reach another tenant's run:
    # the mint 404s (indistinguishable from absent), so no token for that stream can ever exist.
    intruder = TestClient(client.app, headers={"X-Workspace-Id": "ws_seam_intruder"})
    assert intruder.post(f"/agent/runs/{run_id}/stream-token").status_code == 404
