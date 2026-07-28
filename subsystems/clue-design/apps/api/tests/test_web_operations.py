"""Website-mode manual-editing API: /web/operations, /web/undo, /web/redo,
/web/theme.

The manual-edit path drives the real core helper (checked apply + validate);
agent-turn undo is exercised through the `app.state.web_turn_runner` test seam
(a stub returning a canned applied envelope with a distinct doc). All temp DBs
via the shared `client` fixture. Set LUMEN_CORE_HELPER to the release binary to
skip the per-call cargo build.
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

# The same clean landing-page fixture the turn tests ingest (header + hero +
# footer, tokens only). Ingest yields stable section ids: hero / site_header /
# site_footer, page id "home".
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

SET_HERO_CLASSES = {
    "kind": "set_node_classes",
    "page_id": "home",
    "id": "hero",
    "classes": "bg-dark",
}
# set_text on a container node (hero is a section) — the checked helper rejects
# the batch (op.not_text) and never returns a mutated doc.
SET_TEXT_ON_CONTAINER = {
    "kind": "set_text",
    "page_id": "home",
    "id": "hero",
    "content": "boom",
}


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
    web_doc = client.get(f"/documents/{document_id}").json()["scene"]
    response = client.app.state.core.web_ingest_html(
        web_doc, "home", SAMPLE_HTML, None, None
    )
    errors = [d for d in response.get("diagnostics", []) if d.get("severity") == "error"]
    assert not errors, response.get("diagnostics")
    return response["web_doc"]


def seed_content(client: TestClient, document_id: str, web_doc: dict) -> None:
    """Install a starting content doc WITHOUT creating an undo entry, so the
    manual-edit stack starts clean (push_undo=False)."""
    store = Repository(connect(client.app.state.database_path))
    try:
        store.update_web_document(
            document_id,
            web_doc,
            intent="seed",
            checkpoint_label="seed",
            operations=[{"kind": "replace_web_doc"}],
            inverse_operations=None,
            push_undo=False,
        )
    finally:
        store.connection.close()


def get_document(client: TestClient, document_id: str) -> dict:
    return client.get(f"/documents/{document_id}").json()


def envelopes(client: TestClient, document_id: str) -> list:
    store = Repository(connect(client.app.state.database_path))
    try:
        return store.list_envelopes(document_id, newest_first=False)
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


# --- (a) apply a manual op --------------------------------------------------


def test_web_operations_applies_and_pushes_undo(client: TestClient) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    base = get_document(client, document["id"])
    assert base["current_version"] == 1
    assert base["scene"]["pages"][0]["nodes"]["hero"]["classes"] == "bg-light"

    response = client.post(
        f"/documents/{document['id']}/web/operations",
        json={"operations": [SET_HERO_CLASSES], "base_version": 1},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == 1
    assert body["document"]["current_version"] == 2
    assert body["document"]["doc_kind"] == "web"

    after = get_document(client, document["id"])
    assert after["scene"]["pages"][0]["nodes"]["hero"]["classes"] == "bg-dark"
    # Undo stack carries exactly the one manual batch; redo cleared.
    assert len(after["undo_stack"]) == 1
    assert after["redo_stack"] == []

    # The envelope carries the real forward op + the helper's real inverse.
    tail = envelopes(client, document["id"])[-1]
    assert tail["operations"] == [SET_HERO_CLASSES]
    assert tail["inverse_operations"] == [
        {
            "kind": "set_node_classes",
            "page_id": "home",
            "id": "hero",
            "classes": "bg-light",
        }
    ]
    assert tail["batch_id"] == after["undo_stack"][-1]


# --- (b) base_version mismatch ----------------------------------------------


def test_web_operations_base_version_mismatch(client: TestClient) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))

    response = client.post(
        f"/documents/{document['id']}/web/operations",
        json={"operations": [SET_HERO_CLASSES], "base_version": 999},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "edits.base_version_mismatch"


# --- (c) invalid batch is rejected, doc unchanged ---------------------------


def test_web_operations_invalid_batch_rejected(client: TestClient) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    before = get_document(client, document["id"])

    response = client.post(
        f"/documents/{document['id']}/web/operations",
        json={"operations": [SET_TEXT_ON_CONTAINER]},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "web_operations.invalid"

    after = get_document(client, document["id"])
    assert after["current_version"] == before["current_version"]
    assert after["scene"] == before["scene"]


def test_web_operations_empty_rejected(client: TestClient) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    response = client.post(
        f"/documents/{document['id']}/web/operations", json={"operations": []}
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "web_operations.empty"


# --- (d) undo restores byte-identical, redo re-applies ----------------------


def test_web_undo_redo_round_trip(client: TestClient) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    base_scene = get_document(client, document["id"])["scene"]

    apply = client.post(
        f"/documents/{document['id']}/web/operations",
        json={"operations": [SET_HERO_CLASSES], "base_version": 1},
    )
    assert apply.status_code == 200, apply.text
    edited_scene = get_document(client, document["id"])["scene"]
    batch_id = get_document(client, document["id"])["undo_stack"][-1]

    # Undo → doc restored byte-identical to the seed.
    undo = client.post(f"/documents/{document['id']}/web/undo")
    assert undo.status_code == 200, undo.text
    assert undo.json()["undone_batch_id"] == batch_id
    undone = get_document(client, document["id"])
    assert undone["scene"] == base_scene
    assert undone["undo_stack"] == []
    assert undone["redo_stack"] == [batch_id]

    # Redo → re-applied.
    redo = client.post(f"/documents/{document['id']}/web/redo")
    assert redo.status_code == 200, redo.text
    assert redo.json()["reapplied_batch_id"] == batch_id
    redone = get_document(client, document["id"])
    assert redone["scene"] == edited_scene
    assert redone["undo_stack"] == [batch_id]
    assert redone["redo_stack"] == []


def test_web_undo_empty_stack(client: TestClient) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    response = client.post(f"/documents/{document['id']}/web/undo")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "undo.empty"


def test_web_redo_empty_stack(client: TestClient) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    response = client.post(f"/documents/{document['id']}/web/redo")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "redo.empty"


# --- (e) undo of an agent-turn replace_web_doc envelope ---------------------


def test_web_undo_of_agent_turn_restores_prior_doc(client: TestClient) -> None:
    document = create_web_document(client)  # empty "My site" WebDoc
    prior_scene = get_document(client, document["id"])["scene"]
    content_doc = ingest_content(client, document["id"])
    content_doc["title"] = "Applied Site"

    def stub(doc, prompt, model, root):
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
    started = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Build a landing page"},
    )
    assert started.status_code == 200, started.text
    wait_for_run(client, started.json()["run_id"])

    applied = get_document(client, document["id"])
    assert applied["current_version"] == 1
    assert applied["scene"]["title"] == "Applied Site"
    # The turn worker pushed the turn batch onto the undo stack (push_undo
    # default) and cleared redo.
    assert len(applied["undo_stack"]) == 1
    assert applied["redo_stack"] == []
    turn_batch = applied["undo_stack"][-1]

    # Undo the agent turn → the prior (empty "My site") doc is restored via the
    # whole-document replace_web_doc swap.
    undo = client.post(f"/documents/{document['id']}/web/undo")
    assert undo.status_code == 200, undo.text
    assert undo.json()["undone_batch_id"] == turn_batch
    undone = get_document(client, document["id"])
    assert undone["scene"]["title"] == "My site"
    # Byte-identical restoration of the pre-turn doc via the whole-doc swap.
    assert undone["scene"] == prior_scene
    assert undone["undo_stack"] == []
    assert undone["redo_stack"] == [turn_batch]

    # Redo the agent turn → the applied content comes back.
    redo = client.post(f"/documents/{document['id']}/web/redo")
    assert redo.status_code == 200, redo.text
    redone = get_document(client, document["id"])
    assert redone["scene"]["title"] == "Applied Site"
    assert redone["scene"]["pages"][0]["nodes"], "content reinstalled"
    assert redone["undo_stack"] == [turn_batch]
    assert redone["redo_stack"] == []


# --- (f) a new manual edit after undo clears redo ---------------------------


def test_web_new_edit_after_undo_clears_redo(client: TestClient) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))

    client.post(
        f"/documents/{document['id']}/web/operations",
        json={"operations": [SET_HERO_CLASSES], "base_version": 1},
    )
    client.post(f"/documents/{document['id']}/web/undo")
    after_undo = get_document(client, document["id"])
    assert after_undo["redo_stack"], "redo populated after undo"

    # A fresh manual edit while a redo entry is pending must clear it.
    current = after_undo["current_version"]
    fresh = client.post(
        f"/documents/{document['id']}/web/operations",
        json={
            "operations": [
                {
                    "kind": "set_node_classes",
                    "page_id": "home",
                    "id": "site_footer",
                    "classes": "bg-light",
                }
            ],
            "base_version": current,
        },
    )
    assert fresh.status_code == 200, fresh.text
    after = get_document(client, document["id"])
    assert after["redo_stack"] == []
    assert len(after["undo_stack"]) == 1


# --- (g) theme surface ------------------------------------------------------


def test_web_theme_returns_tokens(client: TestClient) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))

    response = client.get(f"/documents/{document['id']}/web/theme")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == 1
    tokens = body["theme"]["tokens"]
    assert "primary" in tokens
    assert body["theme"]["display_family"]
    # Diagnostics surface only error-severity entries.
    assert all(d.get("severity") == "error" for d in body["diagnostics"])


# --- (h) scene documents are rejected on every new endpoint -----------------


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("post", "/web/operations", {"operations": [SET_HERO_CLASSES]}),
        ("post", "/web/undo", None),
        ("post", "/web/redo", None),
        ("get", "/web/theme", None),
    ],
)
def test_new_web_endpoints_reject_scene_documents(
    client: TestClient, method: str, path: str, payload
) -> None:
    scene = create_scene_document(client)
    url = f"/documents/{scene['id']}{path}"
    response = (
        client.post(url, json=payload) if method == "post" else client.get(url)
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "document.kind_unsupported"
