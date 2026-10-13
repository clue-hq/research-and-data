"""Wave 2 Lane A, Task 28 — a person's publish waits while the design agent works on the document.

THE RULE (founder, 2026-10-13): "it should wait for the run to finish." While a design run drives a
web page or a Puck site, the person's publish routes refuse with **409 `document.agent_run_active`**
naming the run — the same answer the six manual scene-write routes give
(``test_agent_run_write_lock.py``) — because a publish taken mid-run ships a half-edited page.

What the lock does NOT cover, each pinned here:

* **reading** the publish state (``GET …/publish``) — looking is not changing;
* **unpublish** and **rollback** of an earlier publish — they change what is live, not the document
  the agent is editing;
* **the agent's own publish** through the governed tool during its own run — a lock that reached the
  tool would deadlock the run against itself, the same reason the manual-write lock lives on the
  routes only.

And the ABM batch, which publishes one page per account: an account page the agent is working on is
that account's failure on the batch manifest — nothing derived onto it, nothing published — while
every other account publishes as before.

Each scenario runs the real composed app over the Postgres test database, the blob store and (for a
site) the site-kit bundles and Chromium, through the HTTP routes; the run is a REAL leg run row,
claimed by the fleet worker's own CAS (``start_leg_run``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest
from fastapi.testclient import TestClient
from py_lumen_config import settings

from conftest import is_served, make_client, published, published_html
from lumen_api.design_store import HybridRepository
from lumen_api.main import abm_derived_document_id, create_app
from site_kit_support import chromium_available, ensure_site_kit_dist, garner_site_without_clones

from test_abm_batch_publish import _abm_template, _account
from test_agent_run_write_lock import assert_locked, finish_run, start_leg_run
from test_site_publish_routes import revisions, save_site, stored, with_home_heading
from test_web_export import find_node, get_document, seed_document

MARKER = "Marker heading two for Syracuse"


@pytest.fixture()
def client(tmp_path: Path, design_storage, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """The lock suites' client: it seeds running run rows directly and offers no fleet work, so no
    embedded worker drains the shared queue beside it."""
    monkeypatch.setattr(settings, "lumen_embedded_fleet_worker", False, raising=False)
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def ok(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()


# --- one scenario, both document kinds -----------------------------------------------------------


def _seed_web(client: TestClient) -> str:
    return seed_document(client)["id"]


def _edit_web(client: TestClient, document_id: str) -> None:
    """A real manual edit through the web lane's own route, so the next publish is a new revision."""
    document = get_document(client, document_id)
    ok(
        client.post(
            f"/documents/{document_id}/web/operations",
            json={
                "operations": [
                    {
                        "kind": "set_text",
                        "page_id": "home",
                        "id": find_node(document["scene"], "text"),
                        "content": MARKER,
                    }
                ],
                "base_version": document["current_version"],
            },
        )
    )


def _seed_site(client: TestClient) -> str:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()
    return stored(client, garner_site_without_clones("site_run_lock"))["id"]


def _edit_site(client: TestClient, document_id: str) -> None:
    site = client.get(f"/documents/{document_id}").json()["scene"]
    save_site(client, document_id, with_home_heading(site, MARKER))


KINDS: dict[str, tuple[Callable[[TestClient], str], Callable[[TestClient, str], None]]] = {
    "web": (_seed_web, _edit_web),
    "site": (_seed_site, _edit_site),
}


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_a_persons_publish_waits_while_the_agent_works_on_the_document(
    client: TestClient, workspace_id: str, kind: str
) -> None:
    seed, edit = KINDS[kind]
    document_id = seed(client)
    publish_path = f"/documents/{document_id}/{kind}/publish"
    slug = f"run-lock-{kind}"
    repo = HybridRepository()

    # 1. Never published: a publish taken while the agent works puts NOTHING on the air.
    run_id = start_leg_run(repo, document_id)
    try:
        assert_locked(client.post(publish_path, json={"slug": slug}), run_id)
        assert published(workspace_id, slug) is None
        assert revisions(document_id) == []
        # Reading the state is not publishing: it still answers, and says "not published".
        assert ok(client.get(publish_path))["published"] is False
    finally:
        finish_run(repo, run_id)

    # 2. Between runs the person publishes, edits and republishes as before.
    first = ok(client.post(publish_path, json={"slug": slug}))
    edit(client, document_id)
    second = ok(client.post(publish_path, json={"slug": slug}))
    assert second["previous_available"] is True
    assert MARKER in published_html(workspace_id, slug)
    before = revisions(document_id)
    assert [row["publish_id"] for row in before] == [first["publish_id"], second["publish_id"]]

    run_id = start_leg_run(repo, document_id)
    try:
        # 3. A republish waits too — at the live address and at a new one.
        assert_locked(client.post(publish_path, json={"slug": slug}), run_id)
        assert_locked(client.post(publish_path, json={"slug": f"{slug}-moved"}), run_id)
        assert published(workspace_id, f"{slug}-moved") is None
        assert revisions(document_id) == before
        assert MARKER in published_html(workspace_id, slug)  # the live page is untouched
        state = ok(client.get(publish_path))
        assert (state["slug"], state["publish_id"]) == (slug, second["publish_id"])

        # 4. Rollback and unpublish change what is LIVE, not the document: both stay open.
        rolled = ok(client.post(f"/web/publishes/{slug}/rollback"))
        assert rolled["publish_id"] == first["publish_id"]
        assert MARKER not in published_html(workspace_id, slug)
        assert ok(client.delete(f"/web/publishes/{slug}"))["status"] == "unpublished"
        assert not is_served(workspace_id, slug)

        # 5. The agent's OWN publish, through the governed tool during its own run, goes through.
        client.app.state.design_tools.invoke(
            f"design_publish_{kind}",
            {"document_id": document_id, "slug": slug},
            workspace_id=workspace_id,
        )
        assert is_served(workspace_id, slug)
        assert MARKER in published_html(workspace_id, slug)
        # ...and the person is still waiting while that same run keeps going.
        assert_locked(client.post(publish_path, json={"slug": slug}), run_id)
    finally:
        finish_run(repo, run_id)

    # 6. The run is over: the same publish goes through.
    after = ok(client.post(publish_path, json={"slug": slug}))
    assert after["slug"] == slug and is_served(workspace_id, slug)


def test_a_run_on_another_document_does_not_hold_this_ones_publish(
    client: TestClient, workspace_id: str
) -> None:
    """The lock is per document: one busy page never stops the workspace publishing another."""
    busy = _seed_web(client)
    free = _seed_web(client)
    repo = HybridRepository()
    run_id = start_leg_run(repo, busy)
    try:
        ok(client.post(f"/documents/{free}/web/publish", json={"slug": "free-page"}))
        assert is_served(workspace_id, "free-page")
        # ...and the busy one is still busy, so the pass above is not a lock that never armed.
        assert_locked(client.post(f"/documents/{busy}/web/publish", json={"slug": "busy-page"}), run_id)
    finally:
        finish_run(repo, run_id)


# --- the ABM batch: the busy account fails on its manifest row, the rest publish ----------------


def test_an_abm_batch_leaves_the_account_page_the_agent_is_working_on_alone(
    client: TestClient, workspace_id: str, design_storage, tmp_path: Path
) -> None:
    template = _abm_template(client, workspace_id, design_storage, tmp_path / "cache")
    busy = _account(client, "Goodman Campbell")
    free = _account(client, "Harbor Sage")

    def batch() -> dict[str, dict]:
        body = ok(
            client.post(
                f"/documents/{template}/web/batch",
                json={"account_ids": [busy, free], "publish": True, "abm": True},
            )
        )
        return {row["account_id"]: row for row in body["manifest"]}

    first = batch()
    assert {row["status"] for row in first.values()} == {"published"}
    busy_document = abm_derived_document_id(template, busy)
    busy_slug = first[busy]["slug"]
    repo = HybridRepository()
    version_before = repo.require_document(busy_document)["current_version"]
    revisions_before = revisions(busy_document)
    html_before = published_html(workspace_id, busy_slug)

    run_id = start_leg_run(repo, busy_document)
    try:
        rows = batch()
        # The busy account is that account's failure, in the batch's own per-account channel...
        assert rows[busy]["status"] == "failed"
        assert "document.agent_run_active" in rows[busy]["error"]
        assert run_id in rows[busy]["error"]
        assert rows[busy]["slug"] is None and rows[busy]["url"] is None
        # ...nothing was derived onto the page the agent is editing, and its live page stands.
        assert repo.require_document(busy_document)["current_version"] == version_before
        assert revisions(busy_document) == revisions_before
        assert published_html(workspace_id, busy_slug) == html_before
        # One busy account never kills the batch: the other account still publishes.
        assert rows[free]["status"] == "published"
        assert is_served(workspace_id, rows[free]["slug"])
    finally:
        finish_run(repo, run_id)

    # The run is over: the next batch publishes the account page again.
    again = batch()
    assert again[busy]["status"] == "published" and again[busy]["slug"] == busy_slug
