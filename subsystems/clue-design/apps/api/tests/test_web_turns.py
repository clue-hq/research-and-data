"""Website-mode agent turn + render endpoints.

The turn worker is exercised through the `app.state.web_turn_runner` test seam
(a stub returning a canned envelope) so no LLM/browser runs; the render endpoint
drives the real core helper. Both use temp DBs via the shared `client` fixture.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumen_api.database import Repository, connect
from lumen_api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"

# A valid constrained-HTML landing page (header + hero + footer, no imagery) that
# ingests clean against the platform default theme — tokens only, real links.
SAMPLE_HTML = """
<header id="site_header" class="bg-light border-b border-border">
  <div class="mx-auto max-w-[1200px] px-6 py-4 flex items-center justify-between">
    <p data-variant="overline" class="text-primary">Acme</p>
    <a data-button="primary" href="https://acme.test/demo">Get started</a>
  </div>
</header>
<section id="hero" class="bg-light">
  <div class="mx-auto max-w-[1200px] px-6 py-24 flex flex-col items-center gap-6 text-center">
    <p data-variant="overline" class="text-primary">Developer tools</p>
    <h1 data-variant="display" class="max-w-[820px]">Ship faster with Acme</h1>
    <p class="text-muted max-w-[640px]">Acme helps teams build and launch quickly.</p>
    <a data-button="primary" href="https://acme.test/demo">Get started</a>
  </div>
</section>
<footer id="site_footer" class="bg-dark">
  <div class="mx-auto max-w-[1200px] px-6 py-12 flex items-center justify-between">
    <p data-variant="small" class="text-inverse">Acme</p>
    <a data-button="link" href="https://acme.test/privacy">Privacy</a>
  </div>
</footer>
"""


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "api.sqlite3")
    return TestClient(app)


def minimal_scene() -> dict:
    return json.loads(MINIMAL_SCENE_PATH.read_text())


def create_web_document(client: TestClient, **extra) -> dict:
    response = client.post(
        "/documents", json={"doc_kind": "web", "title": "My site", **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()["document"]


def create_scene_document(client: TestClient) -> dict:
    response = client.post(
        "/documents", json={"title": "A scene", "scene": minimal_scene()}
    )
    assert response.status_code == 200, response.text
    return response.json()["document"]


def ingest_content(client: TestClient, document_id: str) -> dict:
    """Produce a valid content WebDoc from the stored empty doc via the real
    helper — used as the canned 'applied' payload and as render seed."""
    web_doc = client.get(f"/documents/{document_id}").json()["scene"]
    response = client.app.state.core.web_ingest_html(
        web_doc, "home", SAMPLE_HTML, None, None
    )
    errors = [d for d in response.get("diagnostics", []) if d.get("severity") == "error"]
    assert not errors, response.get("diagnostics")
    return response["web_doc"]


def seed_web_doc(client: TestClient, document_id: str, web_doc: dict) -> None:
    store = Repository(connect(client.app.state.database_path))
    try:
        store.update_web_document(
            document_id,
            web_doc,
            intent="seed",
            checkpoint_label="seed",
            operations=[{"kind": "replace_web_doc"}],
            inverse_operations=None,
        )
    finally:
        store.connection.close()


def wait_for_run(client: TestClient, run_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/agent/runs/{run_id}").json()
        if run["status"] in ("succeeded", "failed"):
            return run
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish within {timeout}s")


# --- render endpoint --------------------------------------------------------


def test_web_render_editor_contains_node_ids(client: TestClient) -> None:
    document = create_web_document(client)
    seed_web_doc(client, document["id"], ingest_content(client, document["id"]))

    response = client.get(f"/documents/{document['id']}/web/render")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == 1
    # Editor mode is instrumented: authored sections carry data-node-id.
    assert 'data-node-id="hero"' in body["html"]
    assert 'data-node-id="site_footer"' in body["html"]


def test_web_render_rejects_scene_document(client: TestClient) -> None:
    scene = create_scene_document(client)
    response = client.get(f"/documents/{scene['id']}/web/render")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "document.kind_unsupported"


# --- turn gating ------------------------------------------------------------


def test_web_turn_rejects_scene_document(client: TestClient) -> None:
    scene = create_scene_document(client)
    response = client.post(
        f"/documents/{scene['id']}/web/turns", json={"prompt": "Build a page"}
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "document.kind_unsupported"


# --- turn worker: applied persists, failed leaves the document --------------


def test_web_turn_applied_replaces_doc_and_writes_envelope(client: TestClient) -> None:
    document = create_web_document(client)
    content_doc = ingest_content(client, document["id"])
    content_doc["title"] = "Applied Site"

    def stub(doc, prompt, model, root):
        assert prompt == "Build a landing page"
        return {
            "schema_version": 1,
            "status": "applied",
            "outcome": "accepted",
            "summary": "Built the landing page.",
            "web_doc": content_doc,
            "preview_paths": [],
            "doc_kind": "web",
        }

    client.app.state.web_turn_runner = stub
    response = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Build a landing page"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"
    run_id = response.json()["run_id"]

    run = wait_for_run(client, run_id)
    assert run["status"] == "succeeded"
    assert run["result"]["doc_kind"] == "web"
    assert any(e["type"] == "result" for e in run["events"])

    # Document row: doc replaced + version bumped.
    body = client.get(f"/documents/{document['id']}").json()
    assert body["current_version"] == 1
    assert body["scene"]["title"] == "Applied Site"
    assert body["scene"]["pages"][0]["nodes"], "content installed"

    # An invertible replace_web_doc envelope was written.
    store = Repository(connect(client.app.state.database_path))
    try:
        envelopes = store.list_envelopes(document["id"])
    finally:
        store.connection.close()
    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope["operations"] == [{"kind": "replace_web_doc"}]
    assert envelope["inverse_operations"][0]["kind"] == "replace_web_doc"
    # The inverse carries the PRIOR (empty) doc so undo is a whole-doc swap.
    assert envelope["inverse_operations"][0]["web_doc"]["title"] == "My site"


def test_web_turn_threads_target_node_ids_to_runner(client: TestClient) -> None:
    document = create_web_document(client)
    content_doc = ingest_content(client, document["id"])
    seed_web_doc(client, document["id"], content_doc)

    received: dict = {}

    # The scoped-turn stub takes the extra positional arg the seam passes when
    # the request carries target_node_ids (backward compatible with the 4-arg
    # stubs the other cases use).
    def stub(doc, prompt, model, root, target_node_ids):
        received["target_node_ids"] = target_node_ids
        return {
            "schema_version": 1,
            "status": "applied",
            "outcome": "accepted",
            "summary": "Scoped the hero.",
            "web_doc": doc["scene"],
            "preview_paths": [],
            "doc_kind": "web",
        }

    client.app.state.web_turn_runner = stub
    response = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Tighten the hero", "target_node_ids": ["hero"]},
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]

    run = wait_for_run(client, run_id)
    assert run["status"] == "succeeded"
    assert received["target_node_ids"] == ["hero"]


def test_web_turn_failed_leaves_document_unchanged(client: TestClient) -> None:
    document = create_web_document(client)
    before = client.get(f"/documents/{document['id']}").json()

    def stub(doc, prompt, model, root):
        return {
            "schema_version": 1,
            "status": "failed",
            "outcome": "failed",
            "summary": "Could not produce a usable page.",
            "web_doc": doc["scene"],
            "preview_paths": [],
            "doc_kind": "web",
        }

    client.app.state.web_turn_runner = stub
    response = client.post(
        f"/documents/{document['id']}/web/turns", json={"prompt": "make it"}
    )
    run_id = response.json()["run_id"]

    run = wait_for_run(client, run_id)
    assert run["status"] == "failed"

    after = client.get(f"/documents/{document['id']}").json()
    assert after["current_version"] == before["current_version"] == 0

    store = Repository(connect(client.app.state.database_path))
    try:
        assert store.list_envelopes(document["id"]) == []
    finally:
        store.connection.close()
