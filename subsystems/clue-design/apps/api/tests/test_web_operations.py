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


def install_operations(before: dict, after: dict) -> list[dict]:
    before_page = before["pages"][0]
    after_page = after["pages"][0]
    root_id = before_page["root"]
    before_nodes = before_page["nodes"]
    after_nodes = after_page["nodes"]
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
    return operations


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


def test_selected_range_rich_text_commits_atomically_and_undoes(
    client: TestClient,
) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    before = get_document(client, document["id"])
    page = before["scene"]["pages"][0]
    headline = next(
        node
        for node in page["nodes"].values()
        if node.get("kind") == "text" and node.get("variant") == "display"
    )
    original = headline["content"]
    rich_content = {
        "schema_version": 1,
        "blocks": [
            {
                "type": "paragraph",
                "children": [
                    {"type": "text", "text": "Ship "},
                    {
                        "type": "text",
                        "text": "faster",
                        "marks": {
                            "bold": True,
                            "italic": True,
                            "underline": True,
                            "strikethrough": True,
                        },
                    },
                    {"type": "text", "text": " with Acme"},
                ],
            }
        ],
    }
    operation = {
        "kind": "set_rich_text",
        "page_id": "home",
        "id": headline["id"],
        "content": rich_content,
    }

    response = client.post(
        f"/documents/{document['id']}/web/operations",
        json={"operations": [operation], "base_version": before["current_version"]},
    )
    assert response.status_code == 200, response.text
    after = get_document(client, document["id"])
    assert after["current_version"] == before["current_version"] + 1
    assert (
        after["scene"]["pages"][0]["nodes"][headline["id"]]["content"]
        == rich_content
    )
    tail = envelopes(client, document["id"])[-1]
    assert tail["operations"] == [operation]
    assert tail["inverse_operations"] == [
        {
            "kind": "set_rich_text",
            "page_id": "home",
            "id": headline["id"],
            "content": original,
        }
    ]

    undo = client.post(f"/documents/{document['id']}/web/undo")
    assert undo.status_code == 200, undo.text
    restored = get_document(client, document["id"])
    assert (
        restored["scene"]["pages"][0]["nodes"][headline["id"]]["content"]
        == original
    )


def test_rich_text_rejects_unsafe_links_and_missing_variable_fallback(
    client: TestClient,
) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    before = get_document(client, document["id"])
    headline = next(
        node
        for node in before["scene"]["pages"][0]["nodes"].values()
        if node.get("kind") == "text"
    )

    def apply(content: dict[str, object]):
        return client.post(
            f"/documents/{document['id']}/web/operations",
            json={
                "base_version": before["current_version"],
                "operations": [
                    {
                        "kind": "set_rich_text",
                        "page_id": "home",
                        "id": headline["id"],
                        "content": content,
                    }
                ],
            },
        )

    unsafe = apply(
        {
            "schema_version": 1,
            "blocks": [
                {
                    "type": "paragraph",
                    "children": [
                        {
                            "type": "text",
                            "text": "unsafe",
                            "link": {"href": "javascript:alert(1)"},
                        }
                    ],
                }
            ],
        }
    )
    assert unsafe.status_code == 422, unsafe.text
    assert "rich-text link href is not allowed" in unsafe.text

    no_fallback = apply(
        {
            "schema_version": 1,
            "blocks": [
                {
                    "type": "paragraph",
                    "children": [
                        {
                            "type": "variable",
                            "key": "account.name",
                            "fallback": "   ",
                        }
                    ],
                }
            ],
        }
    )
    assert no_fallback.status_code == 422, no_fallback.text
    assert "visible fallback text" in no_fallback.text
    assert get_document(client, document["id"])["current_version"] == before["current_version"]


def test_clickable_container_and_background_semantics_persist_render_and_undo(
    client: TestClient,
) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    before = get_document(client, document["id"])
    page = before["scene"]["pages"][0]
    hero_container_id = page["nodes"]["hero"]["children"][0]
    asset = {
        "id": "hero_background",
        "label": "Hero background",
        "kind": "raster_image",
        "status": "ready",
        "source": {"kind": "generated", "model": "test", "request_id": None},
        "media": {
            "mime_type": "image/webp",
            "filename": "hero.webp",
            "byte_length": 16,
            "digest": None,
            "location": {
                "provider": "test",
                "opaque_ref": "hero",
                "url": "https://assets.example.test/hero.webp",
            },
        },
    }
    operations = [
        {"kind": "upsert_asset", "record": asset},
        {
            "kind": "set_node_props",
            "page_id": "home",
            "id": "hero",
            "props": {
                "kind": "section",
                "tag": "section",
                "anchor_id": "hero",
                "background": {
                    "asset_id": "hero_background",
                    "fit": "cover",
                    "position": "top",
                    "scrim": {"color": "dark", "opacity": 60},
                },
            },
        },
        {
            "kind": "insert_node",
            "page_id": "home",
            "parent": hero_container_id,
            "index": len(page["nodes"][hero_container_id]["children"]),
            "nodes": [
                {
                    "id": "story_text",
                    "kind": "text",
                    "variant": "body",
                    "content": "Read the story",
                    "classes": "",
                },
                {
                    "id": "story_card",
                    "kind": "container",
                    "href": "/story",
                    "new_tab": True,
                    "classes": "p-6",
                    "children": ["story_text"],
                },
            ],
            "root": "story_card",
        },
    ]
    response = client.post(
        f"/documents/{document['id']}/web/operations",
        json={
            "operations": operations,
            "base_version": before["current_version"],
        },
    )
    assert response.status_code == 200, response.text

    after = get_document(client, document["id"])
    nodes = after["scene"]["pages"][0]["nodes"]
    assert nodes["story_card"]["href"] == "/story"
    assert nodes["story_card"]["new_tab"] is True
    assert nodes["hero"]["background"]["scrim"] == {
        "color": "dark",
        "opacity": 60,
    }

    rendered = client.get(f"/documents/{document['id']}/web/render")
    assert rendered.status_code == 200, rendered.text
    html = rendered.json()["html"]
    assert 'href="/story"' in html
    assert 'data-node-id="story_card"' in html
    assert "background-position:top" in html
    assert "var(--color-dark) 60%" in html

    undo = client.post(f"/documents/{document['id']}/web/undo")
    assert undo.status_code == 200, undo.text
    restored = get_document(client, document["id"])["scene"]
    restored_nodes = restored["pages"][0]["nodes"]
    assert "story_card" not in restored_nodes
    assert restored_nodes["hero"].get("background") is None
    assert "hero_background" not in restored["assets"]


def test_move_node_reorders_siblings_and_undo_restores_order(
    client: TestClient,
) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    before = get_document(client, document["id"])
    page = before["scene"]["pages"][0]
    nodes = page["nodes"]
    hero_container_id = nodes["hero"]["children"][0]
    original = list(nodes[hero_container_id]["children"])
    assert len(original) >= 3

    move = {
        "kind": "move_node",
        "page_id": page["id"],
        "id": original[0],
        "new_parent": hero_container_id,
        # MoveNode removes the source first, so the end index is len - 1.
        "index": len(original) - 1,
    }
    response = client.post(
        f"/documents/{document['id']}/web/operations",
        json={"operations": [move], "base_version": before["current_version"]},
    )
    assert response.status_code == 200, response.text
    reordered = get_document(client, document["id"])
    assert reordered["scene"]["pages"][0]["nodes"][hero_container_id]["children"] == [
        *original[1:],
        original[0],
    ]

    undo = client.post(f"/documents/{document['id']}/web/undo")
    assert undo.status_code == 200, undo.text
    restored = get_document(client, document["id"])
    assert restored["scene"]["pages"][0]["nodes"][hero_container_id]["children"] == original


def test_move_node_reparents_between_section_containers_and_redo_reapplies(
    client: TestClient,
) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    before = get_document(client, document["id"])
    page = before["scene"]["pages"][0]
    nodes = page["nodes"]
    source_parent_id = nodes["hero"]["children"][0]
    target_parent_id = nodes["site_footer"]["children"][0]
    source_children = list(nodes[source_parent_id]["children"])
    target_children = list(nodes[target_parent_id]["children"])
    source_id = source_children[-1]

    move = {
        "kind": "move_node",
        "page_id": page["id"],
        "id": source_id,
        "new_parent": target_parent_id,
        "index": len(target_children),
    }
    response = client.post(
        f"/documents/{document['id']}/web/operations",
        json={"operations": [move], "base_version": before["current_version"]},
    )
    assert response.status_code == 200, response.text
    reparented = get_document(client, document["id"])
    after_nodes = reparented["scene"]["pages"][0]["nodes"]
    assert source_id not in after_nodes[source_parent_id]["children"]
    assert after_nodes[target_parent_id]["children"] == [*target_children, source_id]

    undo = client.post(f"/documents/{document['id']}/web/undo")
    assert undo.status_code == 200, undo.text
    undone = get_document(client, document["id"])
    assert undone["scene"] == before["scene"]

    redo = client.post(f"/documents/{document['id']}/web/redo")
    assert redo.status_code == 200, redo.text
    redone_nodes = get_document(client, document["id"])["scene"]["pages"][0]["nodes"]
    assert source_id not in redone_nodes[source_parent_id]["children"]
    assert redone_nodes[target_parent_id]["children"] == [*target_children, source_id]


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


# --- (e) undo of an operation-preserving agent-turn envelope ----------------


def test_web_undo_of_agent_turn_restores_prior_doc(client: TestClient) -> None:
    document = create_web_document(client)  # empty "My site" WebDoc
    prior_scene = get_document(client, document["id"])["scene"]
    content_doc = ingest_content(client, document["id"])

    def stub(doc, prompt, model, root):
        operations = install_operations(doc["scene"], content_doc)
        return {
            "schema_version": 1,
            "status": "applied",
            "outcome": "accepted",
            "summary": "Built the landing page.",
            "web_doc": content_doc,
            "operations": operations,
            "preview_paths": [],
            "doc_kind": "web",
        }

    client.app.state.web_turn_runner = stub
    started = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Build a landing page", "base_version": 0},
    )
    assert started.status_code == 200, started.text
    wait_for_run(client, started.json()["run_id"])

    applied = get_document(client, document["id"])
    assert applied["current_version"] == 1
    assert applied["scene"]["title"] == "My site"
    # The turn worker pushed the turn batch onto the undo stack (push_undo
    # default) and cleared redo.
    assert len(applied["undo_stack"]) == 1
    assert applied["redo_stack"] == []
    turn_batch = applied["undo_stack"][-1]

    # Undo the agent turn → checked inverse WebOperations restore the prior doc.
    undo = client.post(f"/documents/{document['id']}/web/undo")
    assert undo.status_code == 200, undo.text
    assert undo.json()["undone_batch_id"] == turn_batch
    undone = get_document(client, document["id"])
    assert undone["scene"]["title"] == "My site"
    # Byte-identical restoration of the pre-turn doc via canonical inverses.
    assert undone["scene"] == prior_scene
    assert undone["undo_stack"] == []
    assert undone["redo_stack"] == [turn_batch]

    # Redo the agent turn → the applied content comes back.
    redo = client.post(f"/documents/{document['id']}/web/redo")
    assert redo.status_code == 200, redo.text
    redone = get_document(client, document["id"])
    assert redone["scene"]["title"] == "My site"
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
