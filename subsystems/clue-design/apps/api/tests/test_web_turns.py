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

from conftest import make_client

from lumen_api.design_store import HybridRepository
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
    app = create_app(tmp_path / "engine-cache")
    return make_client(app)


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
    store = HybridRepository()
    store.update_web_document(
        document_id,
        web_doc,
        intent="seed",
        checkpoint_label="seed",
        operations=[{"kind": "replace_web_doc"}],
        inverse_operations=None,
    )


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
    repo = HybridRepository()
    repo.create_asset_record(record)
    DescriptionStore().put_human(
        record["id"],
        "Acme primary logo",
        "A navy Acme wordmark.",
        "Use on light backgrounds.",
        ["wordmark"],
    )
    manifest = workspace_asset_library_manifest(repo)

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


def test_web_render_bridge_carries_the_documents_route_map(
    client: TestClient,
) -> None:
    """F5 task 20: in-editor navigation. The bridge already swallows every
    anchor click; to turn a SITE-INTERNAL one into a page switch it needs to
    know which hrefs are routes of THIS document, so the script carries the
    whole document's `{route: page_id}` map — every page, not just the rendered
    one (the point is to leave the rendered page)."""
    document = create_web_document(client)
    client.post(
        f"/documents/{document['id']}/web/operations",
        json={
            "operations": [
                {
                    "kind": "add_page",
                    "page": {
                        "id": "pricing",
                        "name": "Pricing",
                        "route": "/pricing",
                        "root": "root_pricing",
                        "nodes": {
                            "root_pricing": {
                                "id": "root_pricing",
                                "kind": "container",
                                "classes": "",
                                "children": [],
                            }
                        },
                    },
                }
            ]
        },
    ).raise_for_status()
    response = client.get(
        f"/documents/{document['id']}/web/render"
        "?bridge=1&nonce=bridge-routes-123&page_id=home"
    )
    assert response.status_code == 200, response.text
    html = response.json()["html"]
    # The map is interpolated as compact JSON, the same escaped way every other
    # capability list is, so a route can never break out of the script string.
    assert "var PAGE_ROUTES = " in html
    assert '"/":"home"' in html
    assert '"/pricing":"pricing"' in html
    # ...and the click handler consults it before posting a navigation intent.
    assert 'post("lumen:navigate"' in html


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


def test_web_render_bridge_exposes_sandboxed_selected_range_rich_text(
    client: TestClient,
) -> None:
    document = create_web_document(client)
    seed_web_doc(client, document["id"], ingest_content(client, document["id"]))
    response = client.get(
        f"/documents/{document['id']}/web/render"
        "?bridge=1&nonce=bridge-rich-text-123"
    )
    assert response.status_code == 200, response.text
    html = response.json()["html"]
    assert (
        'script.src = "/vendor/web-rich-text-runtime.js?v=structured-blocks-v2"'
        in html
    )
    assert "list-style-type:disc" in html
    assert "list-style-type:decimal" in html
    assert "li:has(>ul:only-child,>ol:only-child)" in html
    assert 'post("rich-text-selection"' in html
    assert 'post("rich-text-commit"' in html
    assert 'data.type === "rich-text-command"' in html
    assert 'data.type === "rich-text-toolbar"' in html
    assert 'data.type === "rich-text-settle"' in html
    assert "editingSession.command(data.command)" in html
    assert "editingSession.setInteractionActive(editingToolbarActive)" in html
    assert "editingSession.refreshSelection()" in html
    assert 'textVariant: textVariant' in html
    assert 'structured ? "div" : "span"' in html
    assert "lumen-rich-editor-root.is-structured" in html
    assert "event.source !== parent" in html
    assert "session.getDocument()" in html


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
    # D5 Round B: the route offers the turn to the fleet; `queued` is the honest status of a run
    # no worker has claimed yet.
    assert response.json()["status"] == "queued"
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
    store = HybridRepository()
    envelopes = store.list_envelopes(document["id"])
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
    store = HybridRepository()
    assert store.list_running_runs() == []


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


def _plant_document_account(document_id: str, account_id: str) -> None:
    """Set a document's account column directly (test scaffolding — see the caller)."""
    from clue_design import documents as design_documents
    from lumen_api.design_store import DesignStoreBridge

    store = HybridRepository()
    DesignStoreBridge(store.workspace_id)._run(
        lambda conn: design_documents.set_document_account(
            conn,
            workspace_id=store.workspace_id,
            document_id=document_id,
            account_id=account_id,
        )
    )


def test_web_turn_uses_document_account_when_request_omits_it(client: TestClient) -> None:
    document = create_web_document(client)
    content_doc = ingest_content(client, document["id"])
    account_id = create_account(client, domain="derived.com")

    # A derived doc carries its account_id on the row (the B2 derive path would
    # set this; here we set it directly since derive is out of B1 scope).
    #
    # Straight to the DAL: D6 Round C deleted ``HybridRepository.set_document_account`` because
    # this scaffold was its ONLY caller in the whole tree, and the D6 gate's choice for a write
    # nothing performs is to remove it, not to mint a governed tool for it. A test may reach the
    # DAL; production code may not reach the store without a tool.
    _plant_document_account(document["id"], account_id)

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

    store = HybridRepository()
    assert store.list_envelopes(document["id"]) == []


def test_web_turn_failure_reason_lands_in_diagnostics(client: TestClient) -> None:
    """A failed website turn must say WHY in `diagnostics`, not only inside `summary`.

    The genweb slice-0 run died on the reviewer's vision call ("image dimensions exceed
    max allowed size: 8000 pixels"); the reason reached the editor stringified inside
    `summary` while `diagnostics` stayed empty, so every surface that reads diagnostics
    reported an unexplained failure. The scene path already synthesizes this entry
    (`agent_runtime.no_proposal`); the web path did not.
    """
    document = create_web_document(client)
    refusal = (
        "Error code: 400 - invalid_prompt: image dimensions exceed max allowed "
        "size: 8000 pixels"
    )

    def stub(doc, prompt, model, root):
        return {
            "schema_version": 1,
            "status": "failed",
            "outcome": "failed",
            "summary": refusal,
            "web_doc": doc["scene"],
            "operations": [],
            "preview_paths": [],
            "doc_kind": "web",
        }

    client.app.state.web_turn_runner = stub
    response = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Build a landing page", "base_version": 0},
    )
    run = wait_for_run(client, response.json()["run_id"])
    assert run["status"] == "failed"

    diagnostics = run["result"]["diagnostics"]
    assert len(diagnostics) == 1
    assert diagnostics[0]["severity"] == "error"
    assert diagnostics[0]["code"] == "web_turn.no_result"
    assert diagnostics[0]["message"] == refusal


def test_many_image_refusal_lands_in_diagnostics(client: TestClient) -> None:
    """The G5 refusal, verbatim, must reach `diagnostics` if it ever recurs.

    The clamp in `lumen_agent.tools.view` (every web view image rides the
    many-image ceiling) is what stops this from being reachable; this test pins
    the OTHER half of the contract — that a review-kill is explained rather than
    silent. The string is the one recorded live on run_c6f4485… (2026-08-19),
    which discarded a whole authored landing page after ~28 minutes.
    """
    document = create_web_document(client)
    refusal = (
        "ValueError: ResponseError(code='invalid_prompt', "
        "message='messages.1.content.39.image.source.base64.data: At least one of "
        "the image dimensions exceed max allowed size for many-image requests: "
        "2000 pixels')"
    )

    def stub(doc, prompt, model, root):
        return {
            "schema_version": 1,
            "status": "failed",
            "outcome": "failed",
            "summary": refusal,
            "web_doc": doc["scene"],
            "operations": [],
            "preview_paths": [],
            "doc_kind": "web",
        }

    client.app.state.web_turn_runner = stub
    response = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Build a landing page", "base_version": 0},
    )
    run = wait_for_run(client, response.json()["run_id"])
    assert run["status"] == "failed"

    diagnostics = run["result"]["diagnostics"]
    assert len(diagnostics) == 1
    assert diagnostics[0]["code"] == "web_turn.no_result"
    assert diagnostics[0]["severity"] == "error"
    # The reason is carried WHOLE — a reader must be able to see the pixel limit
    # and the image count position without going to the fleet log.
    assert diagnostics[0]["message"] == refusal
    assert "many-image requests: 2000 pixels" in diagnostics[0]["message"]


def test_web_turn_applied_carries_no_synthetic_diagnostic(client: TestClient) -> None:
    document = create_web_document(client)
    operations = [{"kind": "set_custom_css", "css": "body { opacity: 0.9; }"}]

    def stub(doc, prompt, model, root):
        candidate = client.app.state.core.web_apply_ops(doc["scene"], operations)["web_doc"]
        return {
            "schema_version": 1,
            "status": "applied",
            "outcome": "accepted",
            "summary": "Adjusted the page.",
            "web_doc": candidate,
            "operations": operations,
            "preview_paths": [],
            "doc_kind": "web",
        }

    client.app.state.web_turn_runner = stub
    response = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Soften it", "base_version": 0},
    )
    run = wait_for_run(client, response.json()["run_id"])
    assert run["status"] == "succeeded"
    assert run["result"].get("diagnostics", []) == []


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
    store = HybridRepository()
    envelopes = store.list_envelopes(document["id"])
    assert len(envelopes) == 1
    assert envelopes[0]["source"] == "editor"


# --- leg-dispatched turns (G9) ----------------------------------------------
#
# A chat-born generation arrives as a leg envelope: `config.request` is the user's latest
# message, and `config.delegation_bundle` / `config.history` carry the delegation's standing
# brief and the leg's prior conversation. The scene executor has composed all three into the
# turn prompt since P3.7; the web executor ignored the last two, so a "go ahead" second
# message generated from almost nothing. These drive the REAL `execute_web_turn_job` with a
# capturing runner, exactly as the platform's P3.7 scene tests do.


def _turn_host(client: TestClient, stub):
    """The embedded worker's turn host, built from `app.state` the way `create_app` does."""
    from lumen_api.fleet_handler import DesignTurnHost

    state = client.app.state
    return DesignTurnHost(
        web_turn_runner=stub,
        core=state.core,
        storage=state.storage,
        engine_cache_root=state.engine_cache_root,
    )


def _web_turn_envelope(document_id: str, workspace_id: str, config: dict):
    from uuid import uuid4

    from clue_design.envelopes import DesignTurnEnvelope

    run_id = f"run_{uuid4().hex[:12]}"
    return DesignTurnEnvelope(
        kind="web_turn",
        work_id=uuid4(),
        workspace_id=workspace_id,
        run_id=run_id,
        checkpoint_thread_id=run_id,
        document_id=document_id,
        config=config,
    )


def capturing_web_runner(received: dict, *, result=None):
    """A stub that records the prompt the runtime would receive and applies nothing."""

    def stub(doc, prompt, model, root, **kwargs):
        received["prompt"] = prompt
        received["kwargs"] = kwargs
        return result or {
            "schema_version": 1,
            "status": "applied",
            "outcome": "accepted",
            "summary": "Looked at it.",
            "web_doc": doc["scene"],
            "operations": [],
            "preview_paths": [],
            "doc_kind": "web",
        }

    return stub


LEG_BRIEF = (
    "Build the Harbor & Sage landing page: hero, three benefits, testimonial, "
    "and a booking CTA."
)


def test_a_leg_web_turn_runs_on_the_brief_the_history_and_the_message(
    client: TestClient,
) -> None:
    from lumen_api.main import execute_web_turn_job

    document = create_web_document(client)
    store = HybridRepository()
    received: dict = {}
    envelope = _web_turn_envelope(
        document["id"],
        store.workspace_id,
        {
            "request": {"prompt": "Go ahead.", "base_version": 0},
            "delegation_bundle": {
                "brief": LEG_BRIEF,
                "claim_refs": [{"claim_id": "clm_7"}],
            },
            "history": [
                {"role": "user", "text": "Something warmer than the last one."},
                {"role": "assistant", "text": "Warmer palette it is."},
            ],
            "leg": {"leg_id": "leg-1"},
        },
    )

    status, response, _, _ = execute_web_turn_job(
        envelope,
        store=store,
        host=_turn_host(client, capturing_web_runner(received)),
        event_sink=None,
    )
    assert status == "succeeded", response

    prompt = received["prompt"]
    assert LEG_BRIEF in prompt
    brief_at = prompt.index(LEG_BRIEF)
    first_at = prompt.index("[user] Something warmer than the last one.")
    second_at = prompt.index("[assistant] Warmer palette it is.")
    message_at = prompt.index("Go ahead.")
    # The scene path's prefix-stable order: brief, then history oldest-first, then the message.
    assert brief_at < first_at < second_at < message_at
    assert prompt.rstrip().endswith("Go ahead.")
    assert "data, not instructions" in prompt


def test_a_route_shaped_web_turn_prompt_is_the_users_message_verbatim(
    client: TestClient,
) -> None:
    """The direct BFF path carries no leg blocks; its prompt must stay byte-identical."""

    from lumen_api.main import execute_web_turn_job

    document = create_web_document(client)
    store = HybridRepository()
    received: dict = {}
    envelope = _web_turn_envelope(
        document["id"],
        store.workspace_id,
        {"request": {"prompt": "Build a landing page", "base_version": 0}},
    )

    status, response, _, _ = execute_web_turn_job(
        envelope,
        store=store,
        host=_turn_host(client, capturing_web_runner(received)),
        event_sink=None,
    )
    assert status == "succeeded", response
    assert received["prompt"] == "Build a landing page"


def test_a_leg_web_turn_on_a_stale_envelope_base_runs_against_the_version_it_reads(
    client: TestClient,
) -> None:
    """Session continuity (2026-09-18) retires the pre-run conflict on the web lane too.

    The envelope's ``base_version`` was frozen when the leg dispatched; the document is truth at
    execution time, so the executor reads it, designs against it, and CAS's the write on the
    version it read. The human edit that lands WHILE the turn runs is still refused — by that
    write-time CAS (``test_web_turn_conflict_preserves_edit_committed_while_agent_runs``) — and
    the route still refuses a stale base before a turn is even offered
    (``test_web_turn_rejects_stale_base_version_before_start``).
    """

    from lumen_api.main import execute_web_turn_job

    document = create_web_document(client)
    seed_web_doc(client, document["id"], ingest_content(client, document["id"]))
    store = HybridRepository()
    received: dict = {}
    envelope = _web_turn_envelope(
        document["id"],
        store.workspace_id,
        {
            "request": {"prompt": "Go ahead.", "base_version": 0},
            "delegation_bundle": {"brief": LEG_BRIEF},
            "history": [{"role": "user", "text": "Warmer."}],
        },
    )

    status, response, _, _ = execute_web_turn_job(
        envelope,
        store=store,
        host=_turn_host(client, capturing_web_runner(received)),
        event_sink=None,
    )
    assert status == "succeeded", response
    assert response["status"] == "applied"
    assert LEG_BRIEF in received["prompt"]
    # No prior agent run wrote this document, so there is no drift to report.
    assert "DOCUMENT CHANGED SINCE YOUR LAST TURN" not in received["prompt"]
    assert store.require_document(document["id"])["current_version"] == 1


def test_a_continued_web_session_is_told_what_moved_and_re_sends_no_history(
    client: TestClient,
) -> None:
    """The web twin of the scene executor's session gating and drift note."""

    from lumen_api.main import execute_web_turn_job

    document = create_web_document(client)
    content = ingest_content(client, document["id"])
    seed_web_doc(client, document["id"], content)
    store = HybridRepository()

    # Turn one, recorded the way the fleet worker records it: the succeeded run's stamped
    # `current_version` is what "the version this session last wrote" reads.
    first_received: dict = {}
    operations = [{"kind": "set_custom_css", "css": "body { letter-spacing: 0.01em; }"}]
    agent_doc = client.app.state.core.web_apply_ops(content, operations)["web_doc"]
    first = _web_turn_envelope(
        document["id"],
        store.workspace_id,
        {"request": {"prompt": "Go ahead.", "base_version": 1}, "leg": {"leg_id": "leg-1"}},
    )
    store.create_run(first.run_id, document["id"], kind="web_turn", payload={})
    status, response, event_type, event_data = execute_web_turn_job(
        first,
        store=store,
        host=_turn_host(
            client,
            capturing_web_runner(
                first_received,
                result={
                    "schema_version": 1,
                    "status": "applied",
                    "outcome": "accepted",
                    "summary": "Built it.",
                    "web_doc": agent_doc,
                    "operations": operations,
                    "preview_paths": [],
                    "doc_kind": "web",
                },
            ),
        ),
        event_sink=None,
    )
    assert status == "succeeded", response
    store.complete_run(first.run_id, status, response, event_type, event_data)
    written_version = response["current_version"]

    # The human edit between turns.
    edited = client.post(
        f"/documents/{document['id']}/web/operations",
        json={
            "operations": [{"kind": "set_custom_css", "css": "body { opacity: 1; }"}],
            "base_version": written_version,
            "intent": "human moved the logo",
        },
    )
    assert edited.status_code == 200, edited.text

    received: dict = {}
    second = _web_turn_envelope(
        document["id"],
        store.workspace_id,
        {
            "request": {"prompt": "Warmer.", "base_version": 1},
            "delegation_bundle": {"brief": LEG_BRIEF},
            "history": [{"role": "user", "text": "Go ahead."}],
            "leg": {"leg_id": "leg-1", "first_turn_of_leg": False},
        },
    )
    status, response, _, _ = execute_web_turn_job(
        second,
        store=store,
        host=_turn_host(client, capturing_web_runner(received)),
        event_sink=None,
        session_continued=True,
    )

    assert status == "succeeded", response
    prompt = received["prompt"]
    assert "DOCUMENT CHANGED SINCE YOUR LAST TURN" in prompt
    assert "human moved the logo" in prompt
    # A continued thread already holds the brief and every earlier message.
    assert "<<<HISTORY" not in prompt and "<<<BRIEF" not in prompt


def test_a_direct_bff_web_turn_joins_no_session_even_on_a_document_the_agent_wrote(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling T6-1, the web twin: no ``leg`` block, no session and no drift note.

    The route-shaped turn is threaded on its run id by the design API's own route, so joining the
    document's session folder would be a half-join. Proven on a document a prior (recorded) agent
    turn wrote and a human then moved — the exact state in which a LEG turn is told about drift.
    """

    import lumen_api.main as main

    document = create_web_document(client)
    content = ingest_content(client, document["id"])
    seed_web_doc(client, document["id"], content)
    store = HybridRepository()

    operations = [{"kind": "set_custom_css", "css": "body { letter-spacing: 0.01em; }"}]
    agent_doc = client.app.state.core.web_apply_ops(content, operations)["web_doc"]
    first = _web_turn_envelope(
        document["id"],
        store.workspace_id,
        {"request": {"prompt": "Go ahead.", "base_version": 1}, "leg": {"leg_id": "leg-1"}},
    )
    store.create_run(first.run_id, document["id"], kind="web_turn", payload={})
    status, response, event_type, event_data = main.execute_web_turn_job(
        first,
        store=store,
        host=_turn_host(
            client,
            capturing_web_runner(
                {},
                result={
                    "schema_version": 1,
                    "status": "applied",
                    "outcome": "accepted",
                    "summary": "Built it.",
                    "web_doc": agent_doc,
                    "operations": operations,
                    "preview_paths": [],
                    "doc_kind": "web",
                },
            ),
        ),
        event_sink=None,
    )
    assert status == "succeeded", response
    store.complete_run(first.run_id, status, response, event_type, event_data)
    edited = client.post(
        f"/documents/{document['id']}/web/operations",
        json={
            "operations": [{"kind": "set_custom_css", "css": "body { opacity: 1; }"}],
            "base_version": response["current_version"],
            "intent": "human moved the logo",
        },
    )
    assert edited.status_code == 200, edited.text

    captured: dict = {}

    def fake_web_turn(doc, prompt, model, root, **kwargs):
        captured["session_id"] = kwargs.get("session_id")
        captured["run_id"] = kwargs.get("run_id")
        captured["prompt"] = prompt
        return {
            "schema_version": 1,
            "status": "applied",
            "outcome": "accepted",
            "summary": "Looked at it.",
            "web_doc": doc["scene"],
            "operations": [],
            "preview_paths": [],
            "doc_kind": "web",
        }

    monkeypatch.setattr(main, "run_web_agent_turn", fake_web_turn)
    # No `leg` block, and no override runner: the (monkeypatched) runtime call is the probe.
    status, response, _, _ = main.execute_web_turn_job(
        _web_turn_envelope(
            document["id"],
            store.workspace_id,
            {"request": {"prompt": "Build a landing page", "base_version": 1}},
        ),
        store=store,
        host=_turn_host(client, None),
        event_sink=None,
    )

    assert status == "succeeded", response
    assert captured["session_id"] is None
    assert captured["run_id"] is None
    assert captured["prompt"] == "Build a landing page"


def test_a_leg_web_turn_hands_the_platform_reads_to_the_runtime_and_a_direct_turn_does_not(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Design note 2026-09-19: the web executor threads the platform's reads exactly as the
    scene one does — resolved for a LEG turn, absent for a direct BFF turn.

    Captured at the runtime call rather than inside it (the scene suite owns the
    ``AgentRuntimeConfig`` proof): what this file has to say is that the host's factory is
    consulted for a leg turn, its answer reaches ``run_web_agent_turn``, and a direct turn's
    call is unchanged.
    """

    from dataclasses import replace as dataclass_replace

    import lumen_api.main as main

    document = create_web_document(client)
    content = ingest_content(client, document["id"])
    seed_web_doc(client, document["id"], content)
    store = HybridRepository()
    seen: list = []

    def fake_web_turn(doc, prompt, model, root, **kwargs):
        seen.append(kwargs.get("platform_reads"))
        return {
            "schema_version": 1,
            "status": "applied",
            "outcome": "accepted",
            "summary": "Looked at it.",
            "web_doc": doc["scene"],
            "operations": [],
            "preview_paths": [],
            "doc_kind": "web",
        }

    monkeypatch.setattr(main, "run_web_agent_turn", fake_web_turn)

    sentinel = object()
    host = dataclass_replace(
        _turn_host(client, None),
        platform_reads_factory=lambda envelope: sentinel if "leg" in envelope.config else None,
    )

    status, response, _, _ = main.execute_web_turn_job(
        _web_turn_envelope(
            document["id"],
            store.workspace_id,
            {
                "request": {"prompt": "Go ahead.", "base_version": 1},
                "leg": {"leg_id": "leg-1"},
            },
        ),
        store=store,
        host=host,
        event_sink=None,
    )
    assert status == "succeeded", response

    status, response, _, _ = main.execute_web_turn_job(
        _web_turn_envelope(
            document["id"],
            store.workspace_id,
            {"request": {"prompt": "Build a landing page", "base_version": 1}},
        ),
        store=store,
        host=host,
        event_sink=None,
    )
    assert status == "succeeded", response

    assert seen == [sentinel, None]


def test_a_leg_web_turns_commit_is_labelled_with_the_users_message(
    client: TestClient,
) -> None:
    """The composed prompt is for the RUNTIME. The durable edit envelope's `intent` is a
    human-facing label, so it stays the user's own words — never the rendered brief block."""

    from lumen_api.main import execute_web_turn_job

    document = create_web_document(client)
    content_doc = ingest_content(client, document["id"])
    store = HybridRepository()
    received: dict = {}

    def stub(doc, prompt, model, root, **kwargs):
        received["prompt"] = prompt
        return {
            "schema_version": 1,
            "status": "applied",
            "outcome": "accepted",
            "summary": "Built the landing page.",
            "web_doc": content_doc,
            "operations": install_operations(doc["scene"], content_doc),
            "preview_paths": [],
            "doc_kind": "web",
        }

    envelope = _web_turn_envelope(
        document["id"],
        store.workspace_id,
        {
            "request": {"prompt": "Go ahead.", "base_version": 0},
            "delegation_bundle": {"brief": LEG_BRIEF},
            "history": [{"role": "user", "text": "Warmer."}],
        },
    )
    status, response, _, _ = execute_web_turn_job(
        envelope, store=store, host=_turn_host(client, stub), event_sink=None
    )
    assert status == "succeeded", response
    assert LEG_BRIEF in received["prompt"]

    envelopes = store.list_envelopes(document["id"])
    assert len(envelopes) == 1
    assert envelopes[0]["intent"] == "Go ahead."


# --- annotated targets (R-A2) -----------------------------------------------


def test_web_turn_accepts_annotated_targets_and_keeps_them_dict_shaped(
    client: TestClient,
) -> None:
    """R-A2: the request model is the validation gate, and what comes out the other side is
    the plain mapping every consumer downstream takes.

    `execute_web_turn_job` dumps the validated notes back to dicts before handing them to the
    brief builder and the runtime config, so this pins both halves: the wire shape the platform
    sends is accepted, and dumping it returns exactly that shape (a note's absent `path`/`note`
    stay explicit `None`s rather than disappearing, because submission ORDER and arity are part
    of what the human said)."""
    from lumen_api.models import WebTurnRequest

    wire = {
        "prompt": "Tighten the hero",
        "base_version": 1,
        "target_node_ids": ["frg_a", "sec_b"],
        "target_notes": [
            {
                "target": "frg_a",
                "path": ":nth-child(1) > :nth-child(2)",
                "note": "1. Make this shorter",
            },
            {"target": "sec_b", "path": None, "note": None},
        ],
    }
    payload = WebTurnRequest.model_validate(wire)
    assert [note.model_dump(mode="json") for note in payload.target_notes] == wire[
        "target_notes"
    ]

    document = create_web_document(client)
    content_doc = ingest_content(client, document["id"])
    seed_web_doc(client, document["id"], content_doc)

    received: dict = {}

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
        json={**wire, "target_node_ids": ["hero"], "target_notes": [
            {"target": "hero", "path": ":nth-child(1)", "note": "1. Shorter"}
        ]},
    )
    assert response.status_code == 200, response.text
    run = wait_for_run(client, response.json()["run_id"])
    assert run["status"] == "succeeded", run
    assert received["target_node_ids"] == ["hero"]


def test_web_turn_refuses_an_annotation_path_outside_the_closed_grammar(
    client: TestClient,
) -> None:
    """Spec §3.1's grammar is enforced at the HTTP boundary, not deep inside the prompt
    build: a path is interpolated into the brief and later resolved against real markup, so
    anything that is not a `:nth-child` chain is refused before a run row exists."""
    document = create_web_document(client)
    response = client.post(
        f"/documents/{document['id']}/web/turns",
        json={
            "prompt": "Tighten the hero",
            "base_version": 1,
            "target_node_ids": ["hero"],
            "target_notes": [{"target": "hero", "path": "div > h2", "note": "1. Shorter"}],
        },
    )
    assert response.status_code == 422, response.text
