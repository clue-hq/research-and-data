"""The API's pre-apply check on a fragment text override (slice 3, spec §3.6).

A `set_fragment_text_override` names the element it replaces by POSITION inside a clone's
markup — the same `:nth-child` address an annotation uses. The ENGINE only checks that the
address is *structural*; whether it lands on anything is a question about the artifact's HTML,
which the engine's op arena has never read. So the API asks it, once, before the batch applies:
"a path that does not resolve in the fragment's HTML at apply time is refused" (§3.6).

Refusing here is what keeps the document honest. An override stored against a dead path is a
human edit that renders as nothing (the render pass keeps the clone's own words and warns), and
nothing in the inspector would ever say so — the marketer would simply watch their edit not
happen.

DB-backed: a real fragment, a real document, the real endpoint.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from clue_storage import FsStorage
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_api.design_store import HybridRepository
from lumen_api.fragments import SlotSpec, create_web_fragment, set_web_fragment_status
from lumen_api.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The clone's stored markup. Two addresses matter below: `:nth-child(1) > :nth-child(1)` is the
#: badge, `:nth-child(1) > :nth-child(2)` the headline. The `data-lumen-slot` marker is NOT
#: written here — the mint's sanitizer strips any source-planted `data-lumen-*` and its annotator
#: plants the real ones from the declared specs, so the badge slot is declared, not typed.
FRAGMENT_HTML = "<section><span>New</span><h2>Card economics</h2></section>"

BADGE_SLOT = SlotSpec(selector="span", key="badge", kind="visibility")

OVERRIDE = {"text": "Better economics", "bold": True, "italic": False, "underline": False}


@pytest.fixture()
def client(tmp_path: Path, design_storage: FsStorage) -> TestClient:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    return make_client(app)


def _pinnable_fragment(storage: FsStorage, workspace_id: str, html: str = FRAGMENT_HTML) -> str:
    _row, artifact = create_web_fragment(
        storage,
        workspace_id=workspace_id,
        html=html,
        css=".clone { padding: 64px }",
        rehosted={},
        source_url="https://insight.example/",
        section_role="hero",
        slots=[BADGE_SLOT],
        preview=b"\x89PNG\r\n\x1a\nfake-preview-bytes",
    )
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=artifact.fragment_id, status="approved"
    )
    return artifact.fragment_id


def _seed(document_id: str, fragment_id: str, *, slots: dict | None = None) -> None:
    """A one-page document holding one pinned clone, wrapped in its section (LUMW0011)."""
    fragment_node = {
        "id": "frg_hero",
        "kind": "fragment",
        "fragment_id": fragment_id,
        "children": [],
    }
    if slots is not None:
        fragment_node["slots"] = slots
    web_doc = {
        "schema_version": 1,
        "id": document_id,
        "title": "My site",
        "custom_css": "",
        "assets": {},
        "pages": [
            {
                "id": "home",
                "name": "Home",
                "route": "/",
                "root": "root",
                "nodes": {
                    "root": {"id": "root", "kind": "container", "children": ["sec_hero"]},
                    "sec_hero": {
                        "id": "sec_hero",
                        "kind": "section",
                        "tag": "section",
                        "children": ["frg_hero"],
                    },
                    "frg_hero": fragment_node,
                },
            }
        ],
    }
    HybridRepository().update_web_document(
        document_id,
        web_doc,
        intent="seed",
        checkpoint_label="seed",
        operations=[{"kind": "replace_web_doc"}],
        inverse_operations=None,
        push_undo=False,
    )


def _document(client: TestClient) -> dict:
    response = client.post("/documents", json={"doc_kind": "web", "title": "My site"})
    assert response.status_code == 200, response.text
    return response.json()["document"]


def _apply(client: TestClient, document_id: str, operations: list[dict], version: int):
    return client.post(
        f"/documents/{document_id}/web/operations",
        json={"operations": operations, "base_version": version},
    )


def _override_op(path: str, override: dict | None = OVERRIDE) -> dict:
    op = {
        "kind": "set_fragment_text_override",
        "page_id": "home",
        "id": "frg_hero",
        "path": path,
    }
    if override is not None:
        op["override"] = override
    return op


def test_an_override_on_a_path_the_artifact_has_applies(
    client: TestClient, design_storage: FsStorage
) -> None:
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    fragment_id = _pinnable_fragment(design_storage, workspace_id)
    document = _document(client)
    _seed(document["id"], fragment_id)

    response = _apply(client, document["id"], [_override_op(":nth-child(1) > :nth-child(2)")], 1)

    assert response.status_code == 200, response.text
    scene = client.get(f"/documents/{document['id']}").json()["scene"]
    node = scene["pages"][0]["nodes"]["frg_hero"]
    assert node["text_overrides"][":nth-child(1) > :nth-child(2)"]["text"] == "Better economics"
    assert node["text_overrides"][":nth-child(1) > :nth-child(2)"]["bold"] is True


def test_an_override_on_a_dead_path_is_refused_before_the_engine_sees_it(
    client: TestClient, design_storage: FsStorage
) -> None:
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    fragment_id = _pinnable_fragment(design_storage, workspace_id)
    document = _document(client)
    _seed(document["id"], fragment_id)

    response = _apply(client, document["id"], [_override_op(":nth-child(9)")], 1)

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "web_operations.invalid"
    assert detail["engine_code"] == "op.override_path_unresolved"
    assert ":nth-child(9)" in detail["message"] and "frg_hero" in detail["message"]
    assert detail["diagnostics"] == []
    # Nothing was written: the document is still at the version it was seeded at.
    assert client.get(f"/documents/{document['id']}").json()["current_version"] == 1


def test_the_check_counts_the_way_the_render_does_when_a_slot_hides_an_element(
    client: TestClient, design_storage: FsStorage
) -> None:
    """The path the inspector sends was measured against the RENDERED clone, where a slot bound
    `{"visible": false}` has dropped its element. Checking it against the stored artifact
    without that knowledge would refuse the marketer's headline edit as "dead" (it lands on the
    element AFTER the one they clicked) — and accept an address that renders as nothing."""
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    fragment_id = _pinnable_fragment(design_storage, workspace_id)
    document = _document(client)
    _seed(document["id"], fragment_id, slots={"badge": {"visible": False}})

    # With the badge hidden the headline IS the first child, and the last child is gone.
    ok = _apply(client, document["id"], [_override_op(":nth-child(1) > :nth-child(1)")], 1)
    assert ok.status_code == 200, ok.text

    version = client.get(f"/documents/{document['id']}").json()["current_version"]
    dead = _apply(client, document["id"], [_override_op(":nth-child(1) > :nth-child(2)")], version)
    assert dead.status_code == 422, dead.text
    assert dead.json()["detail"]["engine_code"] == "op.override_path_unresolved"


def test_clearing_an_override_is_never_path_checked(
    client: TestClient, design_storage: FsStorage
) -> None:
    """A clear is a human taking their edit back. Refusing it because the address it was made
    against has since died would trap the override in the document forever — the one state
    from which a clear is the only way out."""
    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    fragment_id = _pinnable_fragment(design_storage, workspace_id)
    document = _document(client)
    _seed(document["id"], fragment_id)

    response = _apply(client, document["id"], [_override_op(":nth-child(9)", None)], 1)

    assert response.status_code == 200, response.text
