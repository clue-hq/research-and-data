"""Website-mode agent turn + render endpoints.

The turn worker is exercised through the `app.state.web_turn_runner` test seam
(a stub returning a canned envelope) so no LLM/browser runs; the render endpoint
drives the real core helper. Both use temp DBs via the shared `client` fixture.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumen_api.database import Repository, connect
from lumen_api.main import create_app, workspace_asset_library_manifest
from lumen_ingestion.describe import DescriptionStore


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


def install_operations(before: dict, after: dict) -> list[dict]:
    """Canonical operations that install ``after`` page content into ``before``."""
    before_page = before["pages"][0]
    after_page = after["pages"][0]
    before_nodes = before_page["nodes"]
    after_nodes = after_page["nodes"]
    root_id = before_page["root"]
    operations: list[dict] = [
        {"kind": "remove_node", "page_id": before_page["id"], "id": child_id}
        for child_id in before_nodes[root_id].get("children") or []
    ]

    def subtree(root: str) -> list[dict]:
        ids: set[str] = set()
        stack = [root]
        while stack:
            current = stack.pop()
            if current in ids:
                continue
            ids.add(current)
            stack.extend(after_nodes[current].get("children") or [])
        return [node for node_id, node in after_nodes.items() if node_id in ids]

    for index, child_id in enumerate(after_nodes[root_id].get("children") or []):
        operations.append(
            {
                "kind": "insert_node",
                "page_id": after_page["id"],
                "parent": root_id,
                "index": index,
                "nodes": subtree(child_id),
                "root": child_id,
            }
        )
    if (before.get("custom_css") or "") != (after.get("custom_css") or ""):
        operations.append(
            {"kind": "set_custom_css", "css": after.get("custom_css") or ""}
        )
    return operations


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


# --- grounded asset manifest -----------------------------------------------


def test_workspace_asset_library_manifest_carries_descriptions_and_provenance(
    client: TestClient,
) -> None:
    record = json.loads(
        (
            REPO_ROOT
            / "crates/lumen-core/fixtures/assets/uploaded_logo_asset.json"
        ).read_text()
    )
    connection = connect(client.app.state.database_path)
    repo = Repository(connection)
    try:
        repo.create_asset_record(record)
        DescriptionStore(connection).put_human(
            record["id"],
            "Acme primary logo",
            "A navy Acme wordmark.",
            "Use on light backgrounds.",
            ["wordmark"],
        )
        manifest = workspace_asset_library_manifest(repo, connection)
    finally:
        connection.close()

    entry = manifest[record["id"]]
    assert entry["record"] == record
    assert entry["title"] == "Acme primary logo"
    assert entry["description"] == "A navy Acme wordmark."
    assert entry["usage"] == "Use on light backgrounds."
    assert entry["tags"] == ["wordmark"]
    assert entry["record"]["license"]["name"] == "client_owned"
    assert entry["record"]["provenance"]["source_label"] == "manual upload"


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


def test_web_render_bridge_includes_generic_node_metrics_protocol(
    client: TestClient,
) -> None:
    document = create_web_document(client)
    seed_web_doc(client, document["id"], ingest_content(client, document["id"]))
    response = client.get(
        f"/documents/{document['id']}/web/render"
        "?bridge=1&nonce=bridge-metrics-123"
    )
    assert response.status_code == 200, response.text
    html = response.json()["html"]
    assert 'post("node-info"' in html
    assert "window.getComputedStyle(el)" in html
    assert 'data.type === "inspect-node"' in html
    assert "new ResizeObserver" in html


def test_web_render_bridge_exposes_generic_reorder_and_reparent_capabilities(
    client: TestClient,
) -> None:
    document = create_web_document(client)
    web_doc = ingest_content(client, document["id"])
    seed_web_doc(client, document["id"], web_doc)
    response = client.get(
        f"/documents/{document['id']}/web/render"
        "?bridge=1&nonce=bridge-move-123"
    )
    assert response.status_code == 200, response.text
    html = response.json()["html"]
    assert "var MOVABLE_NODE_IDS = new Set(" in html
    assert "var DROP_PARENT_NODE_IDS = new Set(" in html
    assert 'post("move-node"' in html
    assert "newParentNodeId: destination.newParentNodeId" in html
    assert "candidate.axis === \"row\"" in html
    assert "lumen-drag-ghost" in html
    # Known rendered Sections are movable and legal drop parents; the page root
    # is configured separately for top-level Section reorder.
    assert '"hero"' in html
    assert f'var ROOT_NODE_ID = "{web_doc["pages"][0]["root"]}"' in html


def test_web_render_bridge_exposes_class_backed_resize_capabilities(
    client: TestClient,
) -> None:
    document = create_web_document(client)
    web_doc = ingest_content(client, document["id"])
    seed_web_doc(client, document["id"], web_doc)
    response = client.get(
        f"/documents/{document['id']}/web/render"
        "?bridge=1&nonce=bridge-resize-123"
    )
    assert response.status_code == 200, response.text
    html = response.json()["html"]
    assert "var RESIZABLE_NODE_IDS = new Set(" in html
    assert 'post("resize-node"' in html
    assert "lumen-resize-handle" in html
    assert '["width", "height", "both"]' in html
    # Text and buttons are resize-capable; Sections remain flow-width parents
    # and therefore do not receive a resize handle.
    page = web_doc["pages"][0]
    expected_ids = sorted(
        node_id
        for node_id, node in page["nodes"].items()
        if node.get("kind") in {"container", "text", "button", "image"}
        and node_id != page["root"]
    )
    assert expected_ids
    assert (
        f"var RESIZABLE_NODE_IDS = new Set("
        f"{json.dumps(expected_ids, separators=(',', ':'))});"
    ) in html


def test_web_render_rejects_scene_document(client: TestClient) -> None:
    scene = create_scene_document(client)
    response = client.get(f"/documents/{scene['id']}/web/render")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "document.kind_unsupported"


# --- turn gating ------------------------------------------------------------


def test_web_turn_rejects_scene_document(client: TestClient) -> None:
    scene = create_scene_document(client)
    response = client.post(
        f"/documents/{scene['id']}/web/turns",
        json={"prompt": "Build a page", "base_version": 0},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "document.kind_unsupported"


# --- turn worker: applied persists, failed leaves the document --------------


def test_web_turn_applied_replays_operations_and_writes_envelope(
    client: TestClient,
) -> None:
    document = create_web_document(client)
    content_doc = ingest_content(client, document["id"])

    def stub(doc, prompt, model, root):
        assert prompt == "Build a landing page"
        operations = install_operations(doc["scene"], content_doc)
        return {
            "schema_version": 1,
            "status": "applied",
            "outcome": "accepted",
            "summary": "Built the landing page.",
            "web_doc": content_doc,
            "operations": operations,
            "grounding": {
                "schema_version": 1,
                "sources": [
                    {
                        "source_id": "page_acme",
                        "kind": "page",
                        "final_url": "https://acme.test/about",
                        "title": "About Acme",
                    }
                ],
                "citations": [
                    {
                        "citation_id": "citation_1",
                        "source_ids": ["page_acme"],
                        "note": "Supports the hero claim.",
                        "node_ids": ["hero"],
                    }
                ],
            },
            "preview_paths": [],
            "doc_kind": "web",
        }

    client.app.state.web_turn_runner = stub
    response = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Build a landing page", "base_version": 0},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"
    run_id = response.json()["run_id"]

    run = wait_for_run(client, run_id)
    assert run["status"] == "succeeded", run
    assert run["result"]["doc_kind"] == "web"
    assert run["result"]["grounding"]["sources"][0]["source_id"] == "page_acme"
    assert run["result"]["grounding"]["citations"][0]["node_ids"] == ["hero"]
    assert any(e["type"] == "result" for e in run["events"])

    # Document row: operations replayed + version bumped.
    body = client.get(f"/documents/{document['id']}").json()
    assert body["current_version"] == 1
    assert body["scene"]["title"] == "My site"
    assert body["scene"]["pages"][0]["nodes"], "content installed"

    # The real operations and their checked inverses are persisted — no
    # replace_web_doc marker survives the agent handoff.
    store = Repository(connect(client.app.state.database_path))
    try:
        envelopes = store.list_envelopes(document["id"])
    finally:
        store.connection.close()
    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope["operations"]
    assert all(op["kind"] != "replace_web_doc" for op in envelope["operations"])
    assert {op["kind"] for op in envelope["operations"]} == {"insert_node"}
    assert envelope["inverse_operations"]
    assert {op["kind"] for op in envelope["inverse_operations"]} == {"remove_node"}


def test_web_turn_never_commits_candidate_without_operation_history(
    client: TestClient,
) -> None:
    document = create_web_document(client)
    content_doc = ingest_content(client, document["id"])

    def stub(doc, prompt, model, root):
        return {
            "schema_version": 1,
            "status": "applied",
            "outcome": "accepted",
            "summary": "Built it, but omitted the commit ledger.",
            "web_doc": content_doc,
            "preview_paths": [],
            "doc_kind": "web",
        }

    client.app.state.web_turn_runner = stub
    started = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Build it", "base_version": 0},
    )
    run = wait_for_run(client, started.json()["run_id"])
    assert run["status"] == "failed"
    assert (
        run["result"]["diagnostics"][0]["code"] == "web_turn.operations_missing"
    )
    stored = client.get(f"/documents/{document['id']}").json()
    assert stored["current_version"] == 0
    page = stored["scene"]["pages"][0]
    assert list(page["nodes"]) == [page["root"]]
    assert not page["nodes"][page["root"]].get("children")


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
            "operations": [],
            "preview_paths": [],
            "doc_kind": "web",
        }

    client.app.state.web_turn_runner = stub
    response = client.post(
        f"/documents/{document['id']}/web/turns",
        json={
            "prompt": "Tighten the hero",
            "base_version": 1,
            "target_node_ids": ["hero"],
        },
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]

    run = wait_for_run(client, run_id)
    assert run["status"] == "succeeded", run
    assert received["target_node_ids"] == ["hero"]


# --- account-aware turns (P5 D6) --------------------------------------------


def create_account(client: TestClient, **fields) -> str:
    response = client.post("/web/accounts", json={"name": "Privia", **fields})
    assert response.status_code == 200, response.text
    return response.json()["account_id"]


def applied_stub_capturing_account(content_doc: dict, received: dict):
    def stub(doc, prompt, model, root, account_card=None):
        received["account_card"] = account_card
        operations = install_operations(doc["scene"], content_doc)
        return {
            "schema_version": 1,
            "status": "applied",
            "outcome": "accepted",
            "summary": "Personalized the page.",
            "web_doc": content_doc,
            "operations": operations,
            "preview_paths": [],
            "doc_kind": "web",
        }

    return stub


def test_web_turn_unknown_account_404_before_run(client: TestClient) -> None:
    document = create_web_document(client)
    response = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Build it", "base_version": 0, "account_id": "acc_nope"},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "web_account.not_found"
    # No run was created for the rejected turn.
    store = Repository(connect(client.app.state.database_path))
    try:
        assert store.list_running_runs() == []
    finally:
        store.connection.close()


def test_web_turn_account_card_reaches_runner(client: TestClient) -> None:
    document = create_web_document(client)
    content_doc = ingest_content(client, document["id"])
    account_id = create_account(
        client, domain="privia.com", data={"cta": "Book a demo"}, notes="context"
    )

    received: dict = {}
    client.app.state.web_turn_runner = applied_stub_capturing_account(content_doc, received)
    response = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Personalize", "base_version": 0, "account_id": account_id},
    )
    assert response.status_code == 200, response.text
    wait_for_run(client, response.json()["run_id"])

    card = received["account_card"]
    assert card == {
        "name": "Privia",
        "domain": "privia.com",
        "logo_asset_id": None,
        "data": {"cta": "Book a demo"},
        "notes": "context",
    }


def test_web_turn_uses_document_account_when_request_omits_it(client: TestClient) -> None:
    document = create_web_document(client)
    content_doc = ingest_content(client, document["id"])
    account_id = create_account(client, domain="derived.com")

    # A derived doc carries its account_id on the row (the B2 derive path would
    # set this; here we set it directly since derive is out of B1 scope).
    store = Repository(connect(client.app.state.database_path))
    try:
        store.connection.execute(
            "UPDATE documents SET account_id = ? WHERE id = ?",
            (account_id, document["id"]),
        )
        store.connection.commit()
    finally:
        store.connection.close()

    received: dict = {}
    client.app.state.web_turn_runner = applied_stub_capturing_account(content_doc, received)
    response = client.post(
        f"/documents/{document['id']}/web/turns",
        json={
            "prompt": "Refine",
            "base_version": 0,
        },  # no account_id — falls back to the doc row
    )
    assert response.status_code == 200, response.text
    wait_for_run(client, response.json()["run_id"])
    assert received["account_card"]["name"] == "Privia"
    assert received["account_card"]["domain"] == "derived.com"


def test_web_turn_without_account_passes_none(client: TestClient) -> None:
    # The un-personalized 4-arg stub must remain callable (no account kwarg).
    document = create_web_document(client)
    content_doc = ingest_content(client, document["id"])

    def stub(doc, prompt, model, root):
        operations = install_operations(doc["scene"], content_doc)
        return {
            "schema_version": 1,
            "status": "applied",
            "outcome": "accepted",
            "summary": "Built it.",
            "web_doc": content_doc,
            "operations": operations,
            "preview_paths": [],
            "doc_kind": "web",
        }

    client.app.state.web_turn_runner = stub
    response = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Build it", "base_version": 0},
    )
    assert response.status_code == 200, response.text
    run = wait_for_run(client, response.json()["run_id"])
    assert run["status"] == "succeeded", run


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
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "make it", "base_version": 0},
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


def test_web_turn_requires_base_version(client: TestClient) -> None:
    document = create_web_document(client)
    response = client.post(
        f"/documents/{document['id']}/web/turns", json={"prompt": "Build it"}
    )
    assert response.status_code == 422, response.text


def test_web_turn_rejects_stale_base_version_before_start(client: TestClient) -> None:
    document = create_web_document(client)
    content = ingest_content(client, document["id"])
    seed_web_doc(client, document["id"], content)
    response = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Refine it", "base_version": 0},
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "edits.base_version_mismatch"
    assert detail["current_version"] == 1


def test_web_turn_conflict_preserves_edit_committed_while_agent_runs(
    client: TestClient,
) -> None:
    document = create_web_document(client)
    runner_started = threading.Event()
    release_runner = threading.Event()
    agent_operations = [{"kind": "set_custom_css", "css": "body { opacity: 0.9; }"}]

    def stub(doc, prompt, model, root):
        candidate = client.app.state.core.web_apply_ops(
            doc["scene"], agent_operations
        )["web_doc"]
        runner_started.set()
        assert release_runner.wait(timeout=10)
        return {
            "schema_version": 1,
            "status": "applied",
            "outcome": "accepted",
            "summary": "Adjusted the page.",
            "web_doc": candidate,
            "operations": agent_operations,
            "preview_paths": [],
            "doc_kind": "web",
        }

    client.app.state.web_turn_runner = stub
    started = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Adjust it", "base_version": 0},
    )
    assert started.status_code == 200, started.text
    assert runner_started.wait(timeout=10)

    human_css = "body { opacity: 1; }"
    edited = client.post(
        f"/documents/{document['id']}/web/operations",
        json={
            "operations": [{"kind": "set_custom_css", "css": human_css}],
            "base_version": 0,
            "intent": "human edit during turn",
        },
    )
    assert edited.status_code == 200, edited.text
    release_runner.set()

    run = wait_for_run(client, started.json()["run_id"])
    assert run["status"] == "failed"
    assert run["result"]["status"] == "conflicted"
    assert run["result"]["diagnostics"][0]["code"] == "web_turn.version_conflict"

    stored = client.get(f"/documents/{document['id']}").json()
    assert stored["current_version"] == 1
    assert stored["scene"]["custom_css"] == human_css
    store = Repository(connect(client.app.state.database_path))
    try:
        envelopes = store.list_envelopes(document["id"])
    finally:
        store.connection.close()
    assert len(envelopes) == 1
    assert envelopes[0]["source"] == "editor"
