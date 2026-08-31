"""A cloned section personalizes per account (clone-fidelity F1.4).

This is the phase's payoff, end to end and through the REAL path: a fragment artifact minted
into the registry, a template document that pins it and authors ``{{account.*}}`` into its slot
values, a real account with a name, a domain and a logo asset — then ``POST
/documents/{id}/web/derive`` (the same composition the batch derive uses: ``account_values`` →
``core.web_derive`` → the governed persist tool) and the render route on the result.

What it proves, and why each half matters:

* **Derive binds the node, not the artifact.** The artifact is immutable and shared; a second
  account deriving the same template gets its own document with its own slot values, and the
  template keeps its ``{{…}}`` untouched.
* **Zero new plumbing.** ``account_values`` already emits ``account.name`` / ``account.domain``
  as text and ``account.logo`` as an asset with its record — the same map every ``data-var`` span
  and ``data-slot`` carrier reads. A fragment slot reads it too.
* **Render substitutes.** The account's name lands in a text slot, its logo's digest URL in an
  image slot, its domain in an href — and every ``data-lumen-slot`` marker survives, so the
  rendered section can be re-rendered (or re-derived) rather than being a one-way bake.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from clue_storage import FsStorage
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_api.design_store import HybridRepository
from lumen_api.fragments import create_web_fragment, set_web_fragment_status
from lumen_api.fragments.slots import SlotSpec
from lumen_api.main import create_app

SENTINEL = "Care, on your terms"
CLONE_LOGO_DIGEST = "11" * 32
HTML = (
    '<section class="clone-hero">'
    f'<h1 class="clone-head">{SENTINEL}</h1>'
    f'<img class="clone-logo" src="/asset-store/{CLONE_LOGO_DIGEST}" alt="Clone Co">'
    '<a class="clone-cta" href="https://insight.example/demo">Book a demo</a>'
    '<aside class="clone-badge">Award winner</aside>'
    "</section>"
)
CSS = ".clone-hero { padding: 64px } .clone-head { color: #123456 }"
SOURCE_URL = "https://insight.example/"
SLOT_SPECS = (
    SlotSpec(selector="h1.clone-head", key="headline", kind="text"),
    SlotSpec(selector="img.clone-logo", key="logo", kind="image"),
    SlotSpec(selector="a.clone-cta", key="cta", kind="href"),
    SlotSpec(selector="aside.clone-badge", key="badge", kind="visibility"),
)

# Smallest valid PNG (1x1) — a real logo asset, so the derive resolves real bytes.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


@pytest.fixture()
def client(tmp_path: Path, design_storage: FsStorage) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def _mint(workspace_id: str, storage: FsStorage):
    _row, artifact = create_web_fragment(
        storage,
        workspace_id=workspace_id,
        html=HTML,
        css=CSS,
        rehosted={},
        source_url=SOURCE_URL,
        section_role="hero",
        slots=SLOT_SPECS,
    )
    # Released before it is pinned. A fragment is born `draft` and a document may only pin an
    # APPROVED one (F2.2's half of the reference gate); this file is about the DERIVE walk, not
    # about the gate, so it takes the production path — approve, then pin — and gets on with it.
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=artifact.fragment_id, status="approved"
    )
    return artifact


def _template_doc(
    document_id: str, fragment_id: str, slots: dict[str, Any]
) -> dict[str, Any]:
    """A one-section page whose only content is the cloned section, slots authored as templates."""
    return {
        "schema_version": 1,
        "id": document_id,
        "title": "Clone template",
        "pages": [
            {
                "id": "home",
                "name": "Home",
                "route": "/",
                "root": "root",
                "nodes": {
                    "root": {
                        "id": "root",
                        "kind": "container",
                        "classes": "",
                        "children": ["sec"],
                    },
                    "sec": {
                        "id": "sec",
                        "kind": "section",
                        "tag": "section",
                        "classes": "",
                        "children": ["frg_hero"],
                    },
                    "frg_hero": {
                        "id": "frg_hero",
                        "kind": "fragment",
                        "fragment_id": fragment_id,
                        "slots": slots,
                        "classes": "w-full",
                    },
                },
            }
        ],
        "assets": {},
        "custom_css": "",
    }


def _upload_logo(client: TestClient) -> str:
    response = client.post(
        "/assets",
        files={"file": ("privia.png", TINY_PNG, "image/png")},
        data={"label": "Privia logo", "kind": "raster_image"},
    )
    assert response.status_code == 200, response.text
    return response.json()["asset"]["id"]


def _fragment_node(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["pages"][0]["nodes"]["frg_hero"]


def test_a_cloned_section_personalizes_per_account_end_to_end(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    artifact = _mint(workspace_id, design_storage)
    # The artifact really is marked: the walk has something to substitute into.
    assert set(artifact.payload["slot_manifest"]) == {"headline", "logo", "cta", "badge"}

    logo_asset_id = _upload_logo(client)
    store = HybridRepository(workspace_id=workspace_id)
    store.create_document(
        _template_doc(
            "doc_clone_tmpl",
            artifact.fragment_id,
            {
                "headline": {"text": "Care for {{account.name}}"},
                "logo": {"text": "{{account.logo}}"},
                "cta": {"text": "https://{{account.domain}}/demo"},
            },
        ),
        doc_kind="web",
    )

    account = client.post(
        "/web/accounts",
        json={
            "name": "Privia Health",
            "domain": "priviahealth.com",
            "logo_asset_id": logo_asset_id,
        },
    ).json()

    derived = client.post(
        "/documents/doc_clone_tmpl/web/derive",
        json={"account_id": account["account_id"]},
    )
    assert derived.status_code == 200, derived.text
    body = derived.json()
    # The account's own keys bound — the SAME keys a data-var span binds.
    assert set(body["coverage"]["bound"]) >= {
        "account.name",
        "account.domain",
        "account.logo",
    }

    derived_doc = client.get(f"/documents/{body['document_id']}").json()["scene"]
    slots = _fragment_node(derived_doc)["slots"]
    assert slots["headline"] == {"text": "Care for Privia Health"}
    assert slots["cta"] == {"text": "https://priviahealth.com/demo"}
    # A whole-value template bound to the account's logo became an ASSET slot,
    # and the record rode along so the render can resolve real bytes.
    assert slots["logo"] == {"asset": logo_asset_id}
    assert logo_asset_id in derived_doc["assets"]

    # The template is untouched: the next account derives from the same `{{…}}`.
    template_doc = client.get("/documents/doc_clone_tmpl").json()["scene"]
    assert _fragment_node(template_doc)["slots"]["headline"] == {
        "text": "Care for {{account.name}}"
    }

    rendered = client.get(f"/documents/{body['document_id']}/web/render")
    assert rendered.status_code == 200, rendered.text
    html = rendered.json()["html"]

    logo_digest = store.require_asset_record(logo_asset_id)["asset"]["media"]["digest"][
        "value"
    ]
    assert "Care for Privia Health" in html
    # The route serves an absolute asset base, so match the digest tail — the
    # point is that the src is the ACCOUNT's bytes, resolved the same way an
    # Image node's are.
    assert f"/asset-store/{logo_digest}" in html
    assert 'href="https://priviahealth.com/demo"' in html
    # The clone's own words are the FALLBACK, and a bound slot replaces them.
    assert SENTINEL not in html
    assert f"/asset-store/{CLONE_LOGO_DIGEST}" not in html
    assert "https://insight.example/demo" not in html
    # An unbound slot keeps the clone's own content (the badge nobody bound).
    assert "Award winner" in html
    # Every marker survives: this render is re-derivable, not a one-way bake.
    for key in ("headline", "logo", "cta", "badge"):
        assert f'data-lumen-slot="{key}"' in html
    assert not rendered.json()["diagnostics"], rendered.json()["diagnostics"]


def test_two_accounts_derive_two_documents_from_one_immutable_artifact(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    artifact = _mint(workspace_id, design_storage)
    store = HybridRepository(workspace_id=workspace_id)
    store.create_document(
        _template_doc(
            "doc_clone_two",
            artifact.fragment_id,
            {"headline": {"text": "{{account.name}}"}},
        ),
        doc_kind="web",
    )

    pages = []
    for name in ("Privia Health", "Sutter Care"):
        account = client.post("/web/accounts", json={"name": name}).json()
        response = client.post(
            "/documents/doc_clone_two/web/derive",
            json={"account_id": account["account_id"]},
        )
        assert response.status_code == 200, response.text
        rendered = client.get(
            f"/documents/{response.json()['document_id']}/web/render"
        ).json()
        pages.append(rendered["html"])

    assert "Privia Health" in pages[0] and "Sutter Care" not in pages[0]
    assert "Sutter Care" in pages[1] and "Privia Health" not in pages[1]
    # One artifact, two personalizations: the section's own CSS is the same
    # scoped block on both pages.
    assert artifact.payload["css"].split("{")[0].strip() not in ("",)
    for page in pages:
        assert f"lumen-frag-{artifact.fragment_id[len('frag_'):]}" in page


def test_an_account_without_a_domain_keeps_the_clones_own_link(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    """An unbound key must not put `{{account.domain}}` on a live page — the artifact's own href
    is the fallback, and the coverage report says so."""
    artifact = _mint(workspace_id, design_storage)
    store = HybridRepository(workspace_id=workspace_id)
    store.create_document(
        _template_doc(
            "doc_clone_nodomain",
            artifact.fragment_id,
            {"cta": {"text": "https://{{account.domain}}/demo"}},
        ),
        doc_kind="web",
    )
    account = client.post("/web/accounts", json={"name": "No Domain Co"}).json()
    response = client.post(
        "/documents/doc_clone_nodomain/web/derive",
        json={"account_id": account["account_id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [entry["key"] for entry in body["coverage"]["unbound_slots"]] == [
        "account.domain"
    ]

    derived_doc = client.get(f"/documents/{body['document_id']}").json()["scene"]
    assert _fragment_node(derived_doc).get("slots", {}) == {}

    html = client.get(f"/documents/{body['document_id']}/web/render").json()["html"]
    assert "{{" not in html
    assert 'href="https://insight.example/demo"' in html
