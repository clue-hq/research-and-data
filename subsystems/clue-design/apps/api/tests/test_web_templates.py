"""Website-mode templates (P5 D4): clone a web doc into a template row + list +
the personalization passthrough on GET /documents/{id}.

Clones run the real helper (HTML ingest only, no LLM/browser) against a temp DB.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"

SAMPLE_HTML = """
<header id="site_header" class="bg-light border-b border-border">
  <div class="mx-auto max-w-[1200px] px-6 py-4 flex items-center justify-between">
    <p data-variant="overline" class="text-primary">Acme</p>
    <a data-button="primary" href="https://acme.test/demo">Get started</a>
  </div>
</header>
<section id="hero" class="bg-light">
  <div class="mx-auto max-w-[1200px] px-6 py-24 flex flex-col items-center gap-6 text-center">
    <h1 data-variant="display" class="max-w-[820px]">Ship faster with Acme</h1>
    <p class="text-muted max-w-[640px]">Acme helps teams build and launch quickly.</p>
    <a data-button="primary" href="https://acme.test/demo">Get started</a>
  </div>
</section>
"""


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "engine-cache")
    return make_client(app)


def create_web_document(client: TestClient, **extra) -> dict:
    response = client.post(
        "/documents", json={"doc_kind": "web", "title": "My site", **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()["document"]


def create_scene_document(client: TestClient) -> dict:
    response = client.post(
        "/documents",
        json={"title": "A scene", "scene": json.loads(MINIMAL_SCENE_PATH.read_text())},
    )
    assert response.status_code == 200, response.text
    return response.json()["document"]


def seed_content(client: TestClient, document_id: str) -> None:
    """Author content through the real helper + persist it (bumps version and
    pushes an undo entry, so the clone's fresh-stack invariant is observable)."""
    web_doc = client.get(f"/documents/{document_id}").json()["scene"]
    response = client.app.state.core.web_ingest_html(
        web_doc, "home", SAMPLE_HTML, None, None
    )
    errors = [d for d in response.get("diagnostics", []) if d.get("severity") == "error"]
    assert not errors, response.get("diagnostics")
    store = HybridRepository()
    store.update_web_document(
        document_id,
        response["web_doc"],
        intent="seed",
        checkpoint_label="seed",
        operations=[{"kind": "replace_web_doc"}],
        inverse_operations=None,
    )


def test_save_as_template_clones_fresh_row(client: TestClient) -> None:
    document = create_web_document(client)
    seed_content(client, document["id"])
    source = client.get(f"/documents/{document['id']}").json()
    assert source["current_version"] == 1  # seeded

    response = client.post(f"/documents/{document['id']}/web/template", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    template_id = body["document_id"]
    assert template_id != document["id"]
    assert body["title"] == "My site — template"

    template = client.get(f"/documents/{template_id}").json()
    # Fresh row: version 0, is_template, empty undo/redo stacks.
    assert template["current_version"] == 0
    assert template["is_template"] is True
    assert template["scene"]["title"] == "My site — template"
    assert template["scene"]["id"] == template_id

    # Payload identity: same sections, only id + title changed.
    src_nodes = source["scene"]["pages"][0]["nodes"]
    tpl_nodes = template["scene"]["pages"][0]["nodes"]
    assert set(tpl_nodes) == set(src_nodes)

    store = HybridRepository()
    row = store.require_document(template_id)
    assert not (row.get("undo_stack") or [])
    assert not (row.get("redo_stack") or [])


def test_save_as_template_custom_title(client: TestClient) -> None:
    document = create_web_document(client)
    response = client.post(
        f"/documents/{document['id']}/web/template", json={"title": "ABM base"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "ABM base"


def test_a_template_is_born_noindex_and_its_publish_serves_the_robots_meta(
    client: TestClient, workspace_id: str
) -> None:
    """Founder ruling 2026-10-16: saving as a template births a NEW web document, so it is born
    with the durable noindex — even when the page it was cloned from was made indexable — and
    a publish that asks for nothing serves the robots meta."""
    from conftest import published_html

    document = create_web_document(client)
    seed_content(client, document["id"])
    allowed = client.put(f"/documents/{document['id']}/web-noindex", json={"noindex": False})
    assert allowed.status_code == 200, allowed.text

    template_id = client.post(
        f"/documents/{document['id']}/web/template", json={}
    ).json()["document_id"]
    store = HybridRepository()
    assert store.require_document(template_id)["web_noindex"] is True
    assert store.require_document(document["id"])["web_noindex"] is False

    published = client.post(f"/documents/{template_id}/web/publish", json={"slug": "tpl-page"})
    assert published.status_code == 200, published.text
    assert '<meta name="robots" content="noindex">' in published_html(workspace_id, "tpl-page")


def test_save_as_template_rejects_scene_document(client: TestClient) -> None:
    scene = create_scene_document(client)
    response = client.post(f"/documents/{scene['id']}/web/template", json={})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "document.kind_unsupported"


def test_list_templates(client: TestClient) -> None:
    # A plain web doc is not a template; a cloned one is.
    document = create_web_document(client)
    assert client.get("/web/templates").json()["templates"] == []
    template_id = client.post(
        f"/documents/{document['id']}/web/template", json={}
    ).json()["document_id"]
    templates = client.get("/web/templates").json()["templates"]
    assert len(templates) == 1
    entry = templates[0]
    assert entry["document_id"] == template_id
    assert entry["version"] == 0
    assert "updated_at" in entry
    assert "brand_kit_ref" in entry


def test_get_document_passes_personalization_fields_for_web(client: TestClient) -> None:
    document = create_web_document(client)
    body = client.get(f"/documents/{document['id']}").json()
    # A plain web doc: the three fields are present with their defaults.
    assert body["is_template"] is False
    assert body["template_document_id"] is None
    assert body["account_id"] is None
    # template_doc_version stays internal — not part of the public shape.
    assert "template_doc_version" not in body


def test_get_document_omits_personalization_fields_for_scene(client: TestClient) -> None:
    scene = create_scene_document(client)
    body = client.get(f"/documents/{scene['id']}").json()
    for field in ("is_template", "template_document_id", "account_id", "template_doc_version"):
        assert field not in body
