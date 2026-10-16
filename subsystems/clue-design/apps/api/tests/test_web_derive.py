"""Website-mode personalization derive (P5 D4 + editor-wave amendment):
POST /documents/{id}/web/derive.

Drives the real core helper (set LUMEN_CORE_HELPER to the release binary) against
a temp DB. account_id is OPTIONAL: absent → an empty-value marker-preserving copy;
present → the account's value map is applied. Unknown doc/account → 404; an engine
rejection (a bound Asset value with no asset record) → 422 with coverage.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app


# A marker template with an inline variable (data-var) and a node slot
# (data-slot). No when-gate, so an empty-value derive is a true identity copy.
MARKER_HTML = """
<section id="hero">
  <h1 id="head">Meet <span data-var="account.name">Acme Health</span></h1>
  <p id="tag" data-slot="account.tagline">A better way to work</p>
</section>
"""

# Smallest valid PNG (1x1) — a real logo asset for the resolution path.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "engine-cache")
    return make_client(app)


def create_web_document(client: TestClient, title: str = "Acme Site") -> dict:
    response = client.post("/documents", json={"doc_kind": "web", "title": title})
    assert response.status_code == 200, response.text
    return response.json()["document"]


def create_scene_document(client: TestClient) -> dict:
    scene_path = (
        Path(__file__).resolve().parents[3]
        / "crates/lumen-core/fixtures/minimal_scene.json"
    )
    response = client.post(
        "/documents", json={"title": "A scene", "scene": json.loads(scene_path.read_text())}
    )
    assert response.status_code == 200, response.text
    return response.json()["document"]


def seed_template(
    client: TestClient,
    document_id: str,
    html: str = MARKER_HTML,
    inject_assets: dict | None = None,
) -> None:
    """Ingest marker HTML through the real helper and persist it, so the doc is a
    ready template. `inject_assets` (id → engine AssetRecord) is merged into the
    web doc's assets map before ingest so a data-asset reference resolves."""
    web_doc = client.get(f"/documents/{document_id}").json()["scene"]
    if inject_assets:
        web_doc.setdefault("assets", {}).update(inject_assets)
    response = client.app.state.core.web_ingest_html(web_doc, "home", html, None, None)
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


def upload_asset_record(client: TestClient) -> tuple[str, dict]:
    """Upload a real logo asset and return (asset_id, engine AssetRecord)."""
    response = client.post(
        "/assets",
        files={"file": ("logo.png", TINY_PNG, "image/png")},
        data={"label": "Acme logo", "kind": "raster_image"},
    )
    assert response.status_code == 200, response.text
    asset_id = response.json()["asset"]["id"]
    store = HybridRepository()
    record = store.require_asset_record(asset_id)["asset"]
    return asset_id, record


# --- derive WITH an account -------------------------------------------------


def test_derive_with_account_applies_values(client: TestClient) -> None:
    document = create_web_document(client)
    seed_template(client, document["id"])
    source = client.get(f"/documents/{document['id']}").json()

    account = client.post(
        "/web/accounts",
        json={
            "name": "Privia Health",
            "domain": "priviahealth.com",
            "data": {"tagline": "AI scribing clinicians trust"},
        },
    ).json()

    response = client.post(
        f"/documents/{document['id']}/web/derive",
        json={"account_id": account["account_id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Acme Site — Privia Health"
    # Coverage names the keys that bound at least once.
    assert set(body["coverage"]["bound"]) >= {"account.name", "account.tagline"}

    derived = client.get(f"/documents/{body['document_id']}").json()
    # Provenance recorded on the derived web doc.
    assert derived["template_document_id"] == document["id"]
    assert derived["account_id"] == account["account_id"]
    assert derived["is_template"] is False

    # The content actually changed: the account's name/tagline are present, and
    # the derived payload differs from the template.
    derived_blob = json.dumps(derived["scene"])
    assert "Privia Health" in derived_blob
    assert "AI scribing clinicians trust" in derived_blob
    assert derived["scene"] != source["scene"]


def test_derive_default_title_and_custom_title(client: TestClient) -> None:
    document = create_web_document(client)
    seed_template(client, document["id"])
    account = client.post("/web/accounts", json={"name": "Beta Care"}).json()

    custom = client.post(
        f"/documents/{document['id']}/web/derive",
        json={"account_id": account["account_id"], "title": "Beta — landing"},
    )
    assert custom.status_code == 200
    assert custom.json()["title"] == "Beta — landing"


# --- derive WITHOUT an account (plain marker-preserving copy) ----------------


def test_derive_without_account_is_identity_copy(client: TestClient) -> None:
    document = create_web_document(client)
    seed_template(client, document["id"])
    source = client.get(f"/documents/{document['id']}").json()

    response = client.post(f"/documents/{document['id']}/web/derive", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Acme Site — copy"
    # No account → no keys bind.
    assert body["coverage"]["bound"] == []

    derived = client.get(f"/documents/{body['document_id']}").json()
    assert derived["account_id"] is None
    assert derived["template_document_id"] == document["id"]

    # Byte-identical payload except id + title; the markers survive intact.
    src = copy.deepcopy(source["scene"])
    got = copy.deepcopy(derived["scene"])
    for blob in (src, got):
        blob["id"] = "X"
        blob["title"] = "T"
    assert json.dumps(src, sort_keys=True) == json.dumps(got, sort_keys=True)
    variables = [
        child
        for page in derived["scene"]["pages"]
        for node in page["nodes"].values()
        for block in (node.get("content") or {}).get("blocks", [])
        for child in block.get("children", [])
        if child.get("type") == "variable"
    ]
    assert any(variable.get("key") == "account.name" for variable in variables)
    assert any(
        node.get("slot_key") == "account.tagline"
        for page in derived["scene"]["pages"]
        for node in page["nodes"].values()
    )


def test_a_derived_page_is_born_noindex_and_its_publish_serves_the_robots_meta(
    client: TestClient, workspace_id: str
) -> None:
    """Founder ruling 2026-10-16: the derive route births a NEW web document, so it is born with
    the durable noindex (with or without an account) and a publish that asks for nothing serves
    the robots meta. The template it came from keeps whatever it holds."""
    from conftest import published_html

    document = create_web_document(client)
    seed_template(client, document["id"])
    repo = HybridRepository()
    allowed = client.put(f"/documents/{document['id']}/web-noindex", json={"noindex": False})
    assert allowed.status_code == 200, allowed.text

    account = client.post(
        "/web/accounts", json={"name": "Privia Health", "data": {"tagline": "Better care"}}
    ).json()["account_id"]
    for body in ({"account_id": account}, {}):
        derived = client.post(f"/documents/{document['id']}/web/derive", json=body)
        assert derived.status_code == 200, derived.text
        assert repo.require_document(derived.json()["document_id"])["web_noindex"] is True
    assert repo.require_document(document["id"])["web_noindex"] is False

    published = client.post(
        f"/documents/{derived.json()['document_id']}/web/publish", json={"slug": "derived-page"}
    )
    assert published.status_code == 200, published.text
    assert '<meta name="robots" content="noindex">' in published_html(workspace_id, "derived-page")


# --- 404s + 422 rejection ----------------------------------------------------


def test_derive_unknown_document_404(client: TestClient) -> None:
    response = client.post("/documents/doc_missing/web/derive", json={})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "document.not_found"


def test_derive_unknown_account_404(client: TestClient) -> None:
    document = create_web_document(client)
    seed_template(client, document["id"])
    response = client.post(
        f"/documents/{document['id']}/web/derive",
        json={"account_id": "acc_missing"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "web_account.not_found"


def test_derive_rejects_scene_document_409(client: TestClient) -> None:
    scene = create_scene_document(client)
    response = client.post(f"/documents/{scene['id']}/web/derive", json={})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "document.kind_unsupported"


def test_account_logo_cannot_dangle_and_detaches_when_the_asset_goes(
    client: TestClient,
) -> None:
    """D2.4: the ghost-logo state this test used to construct is now impossible.

    It previously seeded an account whose ``logo_asset_id`` named no asset at all (SQLite
    validated the logo at write time only, with no FK) and asserted the derive rejected it
    with LUMW0605. On Postgres ``design_account_logo_fk`` refuses that row outright and
    ``ON DELETE SET NULL`` detaches the pointer when the asset is deleted, so an account can
    never carry a dangling logo for a derive to trip over. Both halves are asserted here;
    ``account_values``' defensive ``except NotFoundError`` (which still yields the unbound
    path) is now belt-and-braces rather than a reachable state.
    """
    asset_id, record = upload_asset_record(client)
    document = create_web_document(client)
    logo_html = (
        f'<section id="s"><img id="logo" data-slot="account.logo" '
        f'data-asset="{asset_id}" alt="logo"></section>'
    )
    seed_template(client, document["id"], html=logo_html, inject_assets={asset_id: record})

    store = HybridRepository()
    # A logo that resolves to nothing is refused BY THE SCHEMA, not by convention.
    with pytest.raises(sqlite3.IntegrityError):
        store.create_web_account(
            "acc_ghost", "Ghost Co", None, "asset_ghost_999", {}, None
        )
    # A real logo binds; deleting the asset SET-NULLs it instead of dangling.
    store.create_web_account("acc_ghost", "Ghost Co", None, asset_id, {}, None)
    assert store.require_web_account("acc_ghost")["logo_asset_id"] == asset_id
    store.delete_asset_record(asset_id)
    assert store.require_web_account("acc_ghost")["logo_asset_id"] is None

    # The derive still runs (the account simply has no logo to bind) and coverage rides it.
    response = client.post(
        f"/documents/{document['id']}/web/derive",
        json={"account_id": "acc_ghost"},
    )
    assert response.status_code == 200, response.text
    coverage = response.json()["coverage"]
    assert [slot["key"] for slot in coverage["unbound_slots"]] == ["account.logo"]
