"""F5 Task 14: the workspace handle over HTTP — and the publish that freezes it.

Founder ruling R-F5-5 (default): a workspace's published sites hang off
``{handle}.pages.cluehq.ai``. The handle is derived from the workspace name, a human may change
it while nothing is published, and the FIRST PUBLISH LOCKS IT — a live URL's host segment is
not something we let move under the links already sitting in somebody's inbox.

``public_host`` is answered by the API, never assembled in the client (R-F5-1): with no
``LUMEN_PUBLIC_PAGES_HOST_SUFFIX`` configured there is no public host at all and the routes say
so with ``null`` rather than inventing ``acme.pages.cluehq.ai`` for a deployment that has no
such DNS.

The publish walk uses the real pipeline (core helper + node static-css compile), like
``test_web_export.py`` — the lock has to be proven through an ACTUAL publish, because "the
publish route locks the handle" is the property, not "the DAL's lock function works".
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from conftest import make_client
from fastapi.testclient import TestClient

from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]


def unique_handle(workspace_id: str, label: str) -> str:
    """A handle nothing else in the database can already hold.

    Handles are GLOBALLY unique (that is the point — one host, one tenant), and this suite runs
    against a shared Postgres whose rows are not rolled back, so a literal ``"acme"`` would pass
    once and then answer ``workspace_handle.taken`` forever. Keying it to the test's own
    workspace keeps every run independent without weakening what is asserted.
    """
    return f"{label}-{workspace_id[-12:]}"


SAMPLE_HTML = """
<section id="hero" class="bg-light">
  <div class="mx-auto max-w-[1200px] px-6 py-24 flex flex-col items-center gap-6 text-center">
    <h1 data-variant="display" class="max-w-[820px]">Ship faster with Acme</h1>
    <p class="text-muted max-w-[640px]">Acme helps teams build and launch quickly.</p>
  </div>
</section>
"""


@pytest.fixture(autouse=True)
def _clean_pages_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither key is set in a developer's shell; do not inherit one from the runner's."""

    monkeypatch.delenv("LUMEN_PUBLIC_PAGES_HOST_SUFFIX", raising=False)
    monkeypatch.delenv("LUMEN_PUBLIC_PAGES_SCHEME", raising=False)


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    return make_client(app)


def seed_document(client: TestClient) -> dict:
    """A web document carrying a real landing page — publishable through the whole pipeline."""
    created = client.post("/documents", json={"doc_kind": "web", "title": "My site"})
    assert created.status_code == 200, created.text
    document = created.json()["document"]
    web_doc = client.get(f"/documents/{document['id']}").json()["scene"]
    response = client.app.state.core.web_ingest_html(web_doc, "home", SAMPLE_HTML, None, None)
    errors = [d for d in response.get("diagnostics", []) if d.get("severity") == "error"]
    assert not errors, response.get("diagnostics")
    HybridRepository().update_web_document(
        document["id"],
        response["web_doc"],
        intent="seed",
        checkpoint_label="seed",
        operations=[{"kind": "replace_web_doc"}],
        inverse_operations=None,
        push_undo=False,
    )
    return document


def test_a_fresh_workspace_already_has_a_handle(
    client: TestClient, workspace_id: str
) -> None:
    """The handle exists on first read — GET mints it rather than answering ``null`` and making
    every caller handle a workspace that has no address yet."""

    response = client.get("/workspace/handle")
    assert response.status_code == 200, response.text
    body = response.json()
    # The test workspace's `name` is its id, so the derived handle is that id as a DNS label.
    assert body["handle"] == workspace_id.replace("_", "-")
    assert body["locked"] is False
    # No host suffix configured (the dev default) → there is no public host to report.
    assert body["public_host"] is None


def test_the_public_host_appears_once_a_suffix_is_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LUMEN_PUBLIC_PAGES_HOST_SUFFIX", "pages.cluehq.ai")
    body = client.get("/workspace/handle").json()
    assert body["public_host"] == f"{body['handle']}.pages.cluehq.ai"


def test_put_changes_the_handle_while_nothing_is_published(
    client: TestClient, workspace_id: str
) -> None:
    chosen = unique_handle(workspace_id, "acme-eu")
    response = client.put("/workspace/handle", json={"handle": chosen})
    assert response.status_code == 200, response.text
    assert response.json()["handle"] == chosen
    assert response.json()["locked"] is False
    assert client.get("/workspace/handle").json()["handle"] == chosen


def test_put_refuses_a_handle_another_workspace_already_holds(
    client: TestClient,
    workspace_id: str,
    tmp_path: Path,
    design_storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One host, one tenant: a handle is globally unique, and the refusal is loud."""

    taken = unique_handle(workspace_id, "shared")
    assert client.put("/workspace/handle", json={"handle": taken}).status_code == 200

    # A SECOND workspace asking for the same label. `make_client` stamps whatever
    # `LUMEN_DEV_WORKSPACE_ID` says at call time, so re-pointing it is how a second tenant
    # exists in one test.
    monkeypatch.setenv("LUMEN_DEV_WORKSPACE_ID", f"ws_test_{uuid4().hex[:16]}")
    other = make_client(create_app(tmp_path / "engine-cache-2", storage=design_storage))

    refused = other.put("/workspace/handle", json={"handle": taken})
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "workspace_handle.taken"


def test_put_refuses_a_reserved_or_ill_shaped_handle(client: TestClient) -> None:
    for refused in ("www", "api", "-acme", "ac", "Acme Robotics"):
        response = client.put("/workspace/handle", json={"handle": refused})
        assert response.status_code == 422, (refused, response.text)
        assert response.json()["detail"]["code"] == "workspace_handle.invalid"


def test_publishing_locks_the_handle_and_a_later_put_is_refused(
    client: TestClient, workspace_id: str
) -> None:
    """The whole ruling in one walk: rename freely, publish, and the handle is frozen."""

    document = seed_document(client)
    chosen = unique_handle(workspace_id, "acme-launch")
    renamed = client.put("/workspace/handle", json={"handle": chosen})
    assert renamed.status_code == 200, renamed.text

    published = client.post(
        f"/documents/{document['id']}/web/publish", json={"slug": "launch"}
    )
    assert published.status_code == 200, published.text

    state = client.get("/workspace/handle").json()
    assert state["handle"] == chosen
    assert state["locked"] is True
    assert state["locked_at"] is not None

    refused = client.put(
        "/workspace/handle", json={"handle": unique_handle(workspace_id, "acme-later")}
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "workspace_handle.locked"
    assert client.get("/workspace/handle").json()["handle"] == chosen


def test_publish_reports_the_absolute_url_of_every_route_it_put_on_the_air(
    client: TestClient, workspace_id: str
) -> None:
    """The POST response carries ``page_urls`` (R-F5-1), so the share menu never has to join a
    site root to a route itself — and it agrees with the publish-state GET's own map."""

    document = seed_document(client)
    published = client.post(
        f"/documents/{document['id']}/web/publish", json={"slug": "routed"}
    )
    assert published.status_code == 200, published.text
    body = published.json()
    assert set(body["page_urls"]) == set(body["routes"] or ["/"])
    assert body["page_urls"]["/"] == body["url"]
    state = client.get(f"/documents/{document['id']}/web/publish").json()
    assert body["page_urls"] == state["page_urls"]
