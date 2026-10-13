"""Section links (Lane B Task 16, Contract 4): the editor loads an agent module through a
10-minute signed link, never through /asset-store."""

from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from conftest import make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from lumen_api.site_section_links import mint_section_token

SECRET = b"test-section-link-secret"
MODULE = 'export const schema = 1;\nexport function render() { return null; }\n'
SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}, "surface": {"type": "string"}}}


@pytest.fixture()
def app(tmp_path: Path, design_storage, monkeypatch: pytest.MonkeyPatch):
    from lumen_api import site_render

    monkeypatch.setattr(site_render, "read_section_schema", lambda module_js, **_: SCHEMA)
    application = create_app(tmp_path / "engine-cache", storage=design_storage)
    application.state.site_section_link_secret = lambda: SECRET
    return application


def _site_with_section(client: TestClient, workspace_id: str) -> tuple[dict, str]:
    digest = client.app.state.design_tools.invoke(
        "design_record_site_section",
        {"name": "StepsBand", "source": "src", "module_js": MODULE, "css": ".a{}"},
        workspace_id=workspace_id, actor="agent", actor_id="run_links",
    ).references["digest"]
    doc_id = f"doc_site_{uuid4().hex[:10]}"
    site = {"id": doc_id, "title": "S", "theme": {}, "shell": None, "agent_sections": {"StepsBand": digest},
            "pages": {"/": {"root": {"props": {"title": "S"}}, "content": []}}}
    return HybridRepository(workspace_id).create_document(site, doc_kind="site"), digest


def test_a_link_is_minted_for_a_placed_section_and_serves_its_module(app, workspace_id: str) -> None:
    client = make_client(app)
    document, digest = _site_with_section(client, workspace_id)
    response = client.post(f"/documents/{document['id']}/site/section-links", json={})
    assert response.status_code == 200, response.text
    (link,) = response.json()["links"]
    assert (link["name"], link["digest"], link["props_schema"]) == ("StepsBand", digest, SCHEMA)
    assert link["expires_at"].endswith("Z") and link["token"]
    bare = TestClient(app)  # the editor's server sends no workspace header
    served = bare.get(f"/site-sections/{digest}.mjs", params={"t": link["token"]})
    assert served.status_code == 200 and served.content == MODULE.encode()
    assert served.headers["content-type"].startswith("text/javascript")
    assert served.headers["cache-control"] == "no-store" and served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["x-clue-workspace-id"] == workspace_id  # ruling R2: the editor checks its Host
    styles = bare.get(f"/site-sections/{digest}.css", params={"t": link["token"]})
    assert styles.status_code == 200 and styles.content == b".a{}"
    assert styles.headers["content-type"].startswith("text/css")
    assert styles.headers["x-clue-workspace-id"] == workspace_id


def test_a_token_for_another_digest_or_after_expiry_is_refused(app, workspace_id: str) -> None:
    """Review focus 3."""

    client = make_client(app)
    document, digest = _site_with_section(client, workspace_id)
    bare = TestClient(app)
    now = int(time.time())
    good = mint_section_token(secret=SECRET, workspace_id=workspace_id, document_id=document["id"], digest=digest, expires_at=now + 600)
    other_digest = "0" * 64
    assert bare.get(f"/site-sections/{other_digest}.mjs", params={"t": good}).json()["detail"]["code"] == "site_section_link.invalid"
    expired = mint_section_token(secret=SECRET, workspace_id=workspace_id, document_id=document["id"], digest=digest, expires_at=now - 1)
    refused = bare.get(f"/site-sections/{digest}.mjs", params={"t": expired})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "site_section_link.expired"
    forged = mint_section_token(secret=b"another-secret", workspace_id=workspace_id, document_id=document["id"], digest=digest, expires_at=now + 600)
    assert bare.get(f"/site-sections/{digest}.css", params={"t": forged}).json()["detail"]["code"] == "site_section_link.invalid"
    assert bare.get(f"/site-sections/{digest}.mjs", params={"t": "not-a-token"}).status_code == 403
    # A link minted for another workspace reads only that workspace, which does not hold the module.
    elsewhere = mint_section_token(secret=SECRET, workspace_id=f"ws_other_{uuid4().hex[:8]}", document_id="doc_x", digest=digest, expires_at=now + 600)
    not_held = bare.get(f"/site-sections/{digest}.mjs", params={"t": elsewhere})
    assert not_held.status_code == 404 and not_held.json()["detail"]["code"] == "site_section.not_found"
    # And the module never comes out of the public byte route.
    assert bare.get(f"/asset-store/{digest}").status_code == 404


def test_a_digest_the_document_does_not_place_is_not_linked(app, workspace_id: str) -> None:
    client = make_client(app)
    document, _ = _site_with_section(client, workspace_id)
    response = client.post(f"/documents/{document['id']}/site/section-links", json={"digests": ["0" * 64]})
    assert response.status_code == 404 and response.json()["detail"]["code"] == "site_section.not_referenced"


def test_without_a_secret_no_link_is_minted_or_honoured(app, workspace_id: str) -> None:
    client = make_client(app)
    document, digest = _site_with_section(client, workspace_id)
    app.state.site_section_link_secret = lambda: None
    minted = client.post(f"/documents/{document['id']}/site/section-links", json={})
    assert minted.status_code == 503 and minted.json()["detail"]["code"] == "site_section_links.unconfigured"
    assert TestClient(app).get(f"/site-sections/{digest}.mjs", params={"t": "x"}).status_code == 503
