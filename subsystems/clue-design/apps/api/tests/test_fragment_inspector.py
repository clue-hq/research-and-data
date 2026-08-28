"""The fragment inspector card, over HTTP (clone-fidelity F3.2).

Four routes, and each of them is a surface over a rule that already existed: the registry reads,
F3.0's activation gate, F3.1's lineage resolver, and P-7's isolation render. What this file pins
is the surface's own obligations — that the card SAYS the things D-F6 and D-F8 require it to say,
and that every refusal reaches the human as a 4xx carrying the reason they have to act on rather
than as a 500 or a sentence a UI has to parse.

The isolation render's browser half is injected here (the API's engine is a real one; the camera
is not), because what these tests are about is the surface, and a headless Chromium in a route
test buys nothing the F3.2 isolation suite has not already bought.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from clue_storage import FsStorage
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_api.fragments import (
    create_web_fragment,
    set_web_fragment_degraded,
    set_web_fragment_status,
)
from lumen_api.fragments.slots import SlotSpec
from lumen_api.main import create_app

SOURCE_URL = "https://insight.example/"
CLONE_DIGEST = "5e" * 32
PNG = b"\x89PNG\r\n\x1a\n-isolation"


def _html(sentinel: str) -> str:
    return (
        f'<section class="band"><h2 class="band-head">{sentinel}</h2>'
        f'<img class="band-art" src="/asset-store/{CLONE_DIGEST}" alt="Ward">'
        '<a class="band-cta" href="https://insight.example/demo">Book a demo</a></section>'
    )


SLOTS = (
    SlotSpec(selector="h2.band-head", key="headline", kind="text"),
    SlotSpec(selector="img.band-art", key="art", kind="image"),
    SlotSpec(selector="a.band-cta", key="cta", kind="href"),
    SlotSpec(selector="section.band", key="visible", kind="visibility"),
)


@pytest.fixture()
def client(tmp_path: Path, design_storage: FsStorage) -> TestClient:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    # The camera, injected at the seam the composition root uses (F3.4, ledger T18-M-13).
    # `render_isolation_preview` still builds the real isolation page out of the real artifact
    # (that is what `test_fragment_isolation_preview.py` asserts) and still runs the real
    # fail-closed asset route; only the shutter is this fake, so these tests need no browser.
    # Nothing is monkeypatched: `app.state.isolation_shooter` is how the browser half is supplied
    # in production too, so the test exercises the wiring rather than stepping around it.
    app.state.isolation_shooter = lambda page, assets: PNG
    yield make_client(app)


def _mint(
    workspace_id: str,
    storage: FsStorage,
    *,
    sentinel: str,
    status: str = "draft",
    label: str | None = None,
    section_index: int = 2,
    hidden: bool = False,
    derived_from: str | None = None,
    derived_reason: str | None = None,
) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "page_url": SOURCE_URL,
        "section_index": section_index,
        # A repair's provenance (`_repair_provenance`) names no basis at all — it was composed,
        # not cropped — and a hidden section was never rendered, so neither carries one. Only a
        # harvested visible section does, which is what makes the mislabel path above reachable.
        "preview_basis": None if (hidden or derived_from) else "measured",
    }
    if hidden:
        provenance["hidden_on_source"] = {
            "hidden": True,
            "evidence": [
                "class token 'w-condition-invisible'",
                "the probe recorded skipping this child",
            ],
        }
    row, _artifact = create_web_fragment(
        storage,
        workspace_id=workspace_id,
        html=_html(sentinel),
        css=".band { padding: 96px }",
        rehosted={f"/asset-store/{CLONE_DIGEST}": CLONE_DIGEST},
        source_url=SOURCE_URL,
        section_role="proof",
        slots=SLOTS,
        label=label or sentinel,
        status=status,
        provenance=provenance,
        derived_from=derived_from,
        derived_reason=derived_reason,
    )
    return row


# --------------------------------------------------------------------------- #
# The card
# --------------------------------------------------------------------------- #


def test_the_card_carries_the_slot_manifest_the_inspectors_controls_are_built_from(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    row = _mint(workspace_id, design_storage, sentinel="A visible band")
    card = client.get(f"/web/fragments/{row['fragment_id']}").json()
    assert card["fragment_id"] == row["fragment_id"]
    kinds = {slot["key"]: slot["kind"] for slot in card["slots"]}
    # One control per kind: a text field, an asset picker, a link field, a visibility toggle.
    assert kinds == {
        "headline": "text",
        "art": "image",
        "cta": "href",
        "visible": "visibility",
    }
    # The fallback is what the section says today, so a field can show it as a placeholder.
    assert next(slot for slot in card["slots"] if slot["key"] == "headline")["fallback"] == (
        "A visible band"
    )
    # An href is NOT a text slot to the inspector even though it rides the node's text tag.
    assert next(slot for slot in card["slots"] if slot["key"] == "cta")["kind"] == "href"


def test_the_card_reports_section_index_as_the_document_position_it_is(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    """M3: one document-order counter numbers both collections, so an index is a SORT KEY.

    Two visible sections at 0 and 4 (a hidden one sat between them) come back as 0 and 4 — the
    card does not renumber them into 0 and 1, which is what treating the index as an offset into
    the visible list would produce.
    """
    first = _mint(workspace_id, design_storage, sentinel="First band", section_index=0)
    later = _mint(workspace_id, design_storage, sentinel="Later band", section_index=4)
    assert client.get(f"/web/fragments/{first['fragment_id']}").json()["section_index"] == 0
    assert client.get(f"/web/fragments/{later['fragment_id']}").json()["section_index"] == 4


def test_a_fragment_this_workspace_does_not_hold_is_a_404_not_a_500(
    client: TestClient,
) -> None:
    response = client.get("/web/fragments/frag_" + "ab" * 8)
    assert response.status_code == 404, response.text


# --------------------------------------------------------------------------- #
# D-F8 — the dormant affordance
# --------------------------------------------------------------------------- #


def test_a_dormant_card_says_the_site_hides_it_and_shows_the_evidence(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    row = _mint(
        workspace_id,
        design_storage,
        sentinel="The pricing nobody sees",
        status="dormant",
        hidden=True,
        section_index=7,
    )
    listing = client.get("/web/fragments/dormant").json()
    assert [section["fragment_id"] for section in listing["sections"]] == [row["fragment_id"]]
    card = listing["sections"][0]
    assert card["status"] == "dormant"
    assert card["hidden_on_source"]["hidden"] is True
    assert any("w-condition-invisible" in item for item in card["hidden_on_source"]["evidence"])
    assert any("probe" in item for item in card["hidden_on_source"]["evidence"])
    # …and where on the page it sat, which is the other half of "hidden on source site".
    assert card["section_index"] == 7
    assert card["page_url"] == SOURCE_URL


def test_activating_without_a_preview_is_refused_with_the_reason_a_human_can_act_on(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    """T16 §6.6: a 4xx carrying the reason, never a 500 that says nothing."""
    row = _mint(
        workspace_id, design_storage, sentinel="Unphotographed", status="dormant", hidden=True
    )
    card = client.get(f"/web/fragments/{row['fragment_id']}").json()
    assert card["activation"] == {
        "activatable": False,
        "reason": "no_preview",
        "message": card["activation"]["message"],
    }
    assert "isolation render" in card["activation"]["message"]

    refusal = client.post(f"/web/fragments/{row['fragment_id']}/activate")
    assert refusal.status_code == 409, refusal.text
    detail = refusal.json()["detail"]
    assert detail["reason"] == "no_preview"
    assert detail["code"] == "fragment.activation_no_preview"
    assert detail["fragment_id"] == row["fragment_id"]
    assert "preview" in detail["message"]


def test_generate_the_isolation_preview_then_activate_and_it_joins_discovery(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    row = _mint(
        workspace_id, design_storage, sentinel="Hidden pricing", status="dormant", hidden=True
    )
    pictured = client.post(f"/web/fragments/{row['fragment_id']}/preview")
    assert pictured.status_code == 200, pictured.text
    card = pictured.json()
    assert card["preview"]["path"].startswith("/asset-store/")
    assert card["activation"]["activatable"] is True

    woken = client.post(f"/web/fragments/{row['fragment_id']}/activate")
    assert woken.status_code == 200, woken.text
    assert woken.json()["status"] == "approved"

    # It is approved now, so the agent's default (approved-only) discovery offers it.
    from lumen_api.agent_cloned_sections import DurableAgentClonedSectionRegistry
    from lumen_api.design_store import DesignBlobStore

    registry = DurableAgentClonedSectionRegistry(
        blobs=DesignBlobStore(design_storage, workspace_id), cache_dir=Path("/tmp/f32-cache")
    )
    offered = {section["fragment_id"] for section in registry.list_sections()["sections"]}
    assert row["fragment_id"] in offered


def test_a_preview_is_generated_once_and_the_second_attempt_says_so(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    row = _mint(
        workspace_id, design_storage, sentinel="Twice pictured", status="dormant", hidden=True
    )
    assert client.post(f"/web/fragments/{row['fragment_id']}/preview").status_code == 200
    again = client.post(f"/web/fragments/{row['fragment_id']}/preview")
    assert again.status_code == 409, again.text
    assert again.json()["detail"]["reason"] == "already_present"


def test_a_section_that_is_not_hidden_has_nothing_to_activate(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    row = _mint(workspace_id, design_storage, sentinel="An ordinary band")
    card = client.get(f"/web/fragments/{row['fragment_id']}").json()
    assert card["activation"]["reason"] == "not_dormant"
    refusal = client.post(f"/web/fragments/{row['fragment_id']}/activate")
    assert refusal.status_code == 409
    assert refusal.json()["detail"]["code"] == "fragment.not_dormant"


def test_an_isolation_render_is_never_reported_as_a_crop_of_the_live_site(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    """P-7's labelling clause, on the row that would otherwise lie about it.

    A section the capture MEASURED but could not crop (no screenshot stored — a branch the mint
    handles explicitly) is born with no picture and `provenance.preview_basis = "measured"`.
    Reading the mint's word for a photograph taken afterwards would present an isolation render
    our own engine drew as a crop of the live site, which is exactly the substitution the ruling
    forbids. The row's own basis, written by the attach, is what the card reports.
    """
    row = _mint(workspace_id, design_storage, sentinel="Measured but never cropped")
    before = client.get(f"/web/fragments/{row['fragment_id']}").json()
    assert before["preview"]["path"] is None
    assert before["preview"]["basis"] == "measured"  # the mint's own account, and it is stale

    after = client.post(f"/web/fragments/{row['fragment_id']}/preview").json()
    assert after["preview"]["path"].startswith("/asset-store/")
    assert after["preview"]["basis"] == "isolation_render"
    assert after["preview"]["basis"] != "measured"


def test_a_repairs_isolation_render_is_labelled_rather_than_left_blank(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    """The other half: a repair's provenance names no basis at all, so an unlabelled picture is
    what the human releasing it would otherwise be shown."""
    _original, repair = _degraded_original_with_repair(workspace_id, design_storage)
    assert client.get(f"/web/fragments/{repair['fragment_id']}").json()["preview"]["basis"] is None
    after = client.post(f"/web/fragments/{repair['fragment_id']}/preview").json()
    assert after["preview"]["basis"] == "isolation_render"


def test_a_picture_the_mint_itself_took_keeps_the_mints_own_account_of_it(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    """The fallback is right for exactly the rows it is about, and this pins that direction.

    A harvested section whose crop the mint made reports the mint's basis — the row's own column
    is NULL, because nothing was attached to it after the fact.
    """
    row, _artifact = create_web_fragment(
        design_storage,
        workspace_id=workspace_id,
        html=_html("A section the capture cropped"),
        css=".band { padding: 96px }",
        rehosted={f"/asset-store/{CLONE_DIGEST}": CLONE_DIGEST},
        source_url=SOURCE_URL,
        section_role="hero",
        slots=SLOTS,
        preview=b"\x89PNG\r\n\x1a\n-a-real-crop",
        provenance={"page_url": SOURCE_URL, "section_index": 2, "preview_basis": "measured"},
    )
    card = client.get(f"/web/fragments/{row['fragment_id']}").json()
    assert card["preview"]["path"].startswith("/asset-store/")
    assert card["preview"]["basis"] == "measured"
    # …and it cannot be re-pictured, so the label can never be overwritten either.
    assert client.post(f"/web/fragments/{row['fragment_id']}/preview").status_code == 409


# --------------------------------------------------------------------------- #
# D-F6 — the degraded → repaired lineage, and R17-2's retire
# --------------------------------------------------------------------------- #


def _degraded_original_with_repair(
    workspace_id: str, storage: FsStorage
) -> tuple[dict[str, Any], dict[str, Any]]:
    original = _mint(workspace_id, storage, sentinel="The broken band", label="Products")
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=original["fragment_id"], status="approved"
    )
    set_web_fragment_degraded(
        workspace_id=workspace_id,
        fragment_id=original["fragment_id"],
        degraded=True,
        reason="dead_height",
    )
    repair = _mint(
        workspace_id,
        storage,
        sentinel="The repaired band",
        label="Repaired — Other — Products",
        derived_from=original["fragment_id"],
        derived_reason=(
            "repair rung 3 (a deliberate, compact static fallback with the artificial height "
            "removed entirely); trigger dead_height; same three products, natural height"
        ),
    )
    return original, repair


def test_the_broken_originals_card_shows_the_marker_its_reason_and_its_repairs(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    original, repair = _degraded_original_with_repair(workspace_id, design_storage)
    card = client.get(f"/web/fragments/{original['fragment_id']}").json()
    assert card["degraded"] is True
    assert card["degraded_reason"] == "dead_height"
    # The reason CODE is not what a human reads; the note is what the decision turns on.
    assert "artificial scroll height" in card["degraded_note"]
    # The repair is reachable through the FAMILY, which is the card's one lineage list (R18-1).
    children = [entry for entry in card["family"] if entry["derived_from"] == original["fragment_id"]]
    assert [entry["fragment_id"] for entry in children] == [repair["fragment_id"]]
    # A repair is born draft, so it is listed and it is honestly unreleased.
    assert children[0]["status"] == "draft"
    assert card["superseded_by"] is None


def test_the_repairs_card_names_the_clone_it_repairs_and_why(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    original, repair = _degraded_original_with_repair(workspace_id, design_storage)
    card = client.get(f"/web/fragments/{repair['fragment_id']}").json()
    assert card["derived_from"] == original["fragment_id"]
    assert "repair rung 3" in card["derived_reason"]
    assert card["repairs_what"]["fragment_id"] == original["fragment_id"]
    assert card["repairs_what"]["label"] == "Products"
    assert card["repairs_what"]["degraded"] is True


def test_a_released_repair_supersedes_the_original_and_the_card_says_so(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    original, repair = _degraded_original_with_repair(workspace_id, design_storage)
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=repair["fragment_id"], status="approved"
    )
    card = client.get(f"/web/fragments/{original['fragment_id']}").json()
    assert card["superseded_by"] == repair["fragment_id"]
    assert card["lineage_ambiguous"] == []


def test_two_released_repairs_are_reported_as_contested_and_one_can_be_retired(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    """Ruling R17-2's whole reason: the recreate walk's ambiguity refusal needs a way out."""
    original, first = _degraded_original_with_repair(workspace_id, design_storage)
    second = _mint(
        workspace_id,
        design_storage,
        sentinel="A second repaired band",
        label="Repaired — Other — Products (again)",
        derived_from=original["fragment_id"],
        derived_reason="repair rung 2 (an equivalent interaction); trigger dead_height; carousel",
    )
    for repair in (first, second):
        set_web_fragment_status(
            workspace_id=workspace_id, fragment_id=repair["fragment_id"], status="approved"
        )

    card = client.get(f"/web/fragments/{original['fragment_id']}").json()
    assert sorted(card["lineage_ambiguous"]) == sorted(
        [first["fragment_id"], second["fragment_id"]]
    )
    assert card["superseded_by"] is None

    retired = client.post(f"/web/fragments/{second['fragment_id']}/retire")
    assert retired.status_code == 200, retired.text
    assert retired.json()["status"] == "deprecated"

    # The family can answer with one id again.
    settled = client.get(f"/web/fragments/{original['fragment_id']}").json()
    assert settled["lineage_ambiguous"] == []
    assert settled["superseded_by"] == first["fragment_id"]


def test_every_repair_in_the_family_is_retirable_from_any_members_card(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    """RULING R18-1, and the shape that made the old direct-children list unreachable.

    A repair-of-a-repair is nobody's direct child except its own parent's, and its parent is
    typically on no page — so a grandchild leaf got a Retire button nowhere at all, and the
    contested-lineage dead end R17-2 exists to end stayed a dead end with the affordance built.
    The card now carries the FAMILY, resolved by the lineage resolver, from every member.
    """
    original, child = _degraded_original_with_repair(workspace_id, design_storage)
    grandchild = _mint(
        workspace_id,
        design_storage,
        sentinel="A repair of the repair",
        label="Repaired — Repaired — Products",
        derived_from=child["fragment_id"],
        derived_reason="repair rung 2 (an equivalent interaction); trigger dead_height; carousel",
    )
    ids = {original["fragment_id"], child["fragment_id"], grandchild["fragment_id"]}

    for member in (original, child, grandchild):
        card = client.get(f"/web/fragments/{member['fragment_id']}").json()
        family = {entry["fragment_id"]: entry for entry in card["family"]}
        # Every member sees the whole family, from any end of the chain.
        assert set(family) == ids, member["fragment_id"]
        # The root is named, and it is the harvested original.
        assert card["lineage_root"] == original["fragment_id"]
        assert family[original["fragment_id"]]["is_root"] is True
        # Both repairs carry a lawful retire verdict; the original carries the refusal (R17-3).
        assert family[child["fragment_id"]]["retirement"]["retirable"] is True
        assert family[grandchild["fragment_id"]]["retirement"]["retirable"] is True
        assert family[original["fragment_id"]]["retirement"]["reason"] == "not_a_repair"
        # …and each names its own parent, so the chain is readable rather than a flat list.
        assert family[grandchild["fragment_id"]]["derived_from"] == child["fragment_id"]

    # The button the family offers is the one the route honours.
    retired = client.post(f"/web/fragments/{grandchild['fragment_id']}/retire")
    assert retired.status_code == 200, retired.text
    assert retired.json()["status"] == "deprecated"


def test_a_clone_with_no_repairs_is_a_family_of_one(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    row = _mint(workspace_id, design_storage, sentinel="An only child")
    card = client.get(f"/web/fragments/{row['fragment_id']}").json()
    assert [entry["fragment_id"] for entry in card["family"]] == [row["fragment_id"]]
    assert card["family"][0]["is_root"] is True
    assert card["family"][0]["retirement"]["retirable"] is False


def test_the_harvested_original_is_never_retired(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    """Ruling R17-3: the original is the evidence D-F6 exists to preserve."""
    original, _repair = _degraded_original_with_repair(workspace_id, design_storage)
    card = client.get(f"/web/fragments/{original['fragment_id']}").json()
    assert card["retirement"]["retirable"] is False
    assert card["retirement"]["reason"] == "not_a_repair"

    refusal = client.post(f"/web/fragments/{original['fragment_id']}/retire")
    assert refusal.status_code == 409, refusal.text
    assert refusal.json()["detail"]["code"] == "fragment.not_a_repair"
    # …and it is still there, still approved, still the evidence.
    assert client.get(f"/web/fragments/{original['fragment_id']}").json()["status"] == "approved"


def test_retiring_a_repair_twice_says_it_is_already_retired(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    _original, repair = _degraded_original_with_repair(workspace_id, design_storage)
    assert client.post(f"/web/fragments/{repair['fragment_id']}/retire").status_code == 200
    again = client.post(f"/web/fragments/{repair['fragment_id']}/retire")
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "fragment.already_retired"


def test_a_repair_can_be_photographed_too_so_the_human_releasing_it_can_look(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    """Ruling R17-2's other half — a repair is a fragment; render its own artifact bytes."""
    _original, repair = _degraded_original_with_repair(workspace_id, design_storage)
    assert repair["preview_digest"] is None
    card = client.post(f"/web/fragments/{repair['fragment_id']}/preview").json()
    assert card["preview"]["path"].startswith("/asset-store/")


# --------------------------------------------------------------------------- #
# The slot VALUES the card edits — and only the values (D-F3 / R1)
# --------------------------------------------------------------------------- #


def _document_pinning(workspace_id: str, storage: FsStorage, fragment_id: str) -> str:
    """A page carrying one released clone in the shape a pinned clone occupies."""
    from lumen_api.design_store import HybridRepository

    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=fragment_id, status="approved"
    )
    store = HybridRepository(workspace_id=workspace_id)
    document = store.create_document(
        {
            "schema_version": 1,
            "id": "doc_slots",
            "title": "Slots",
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
                            "children": ["sec_clone"],
                        },
                        "sec_clone": {
                            "id": "sec_clone",
                            "kind": "section",
                            "tag": "section",
                            "classes": "",
                            "children": ["frg_clone"],
                        },
                        "frg_clone": {
                            "id": "frg_clone",
                            "kind": "fragment",
                            "classes": "",
                            "fragment_id": fragment_id,
                            "slots": {},
                        },
                    },
                }
            ],
            "assets": {
                "asset_ward_1": {
                    "id": "asset_ward_1",
                    "label": "Ward",
                    "kind": "raster_image",
                    "status": "ready",
                    "source": {"kind": "generated", "model": "m", "request_id": None},
                }
            },
            "custom_css": "",
        },
        doc_kind="web",
    )
    return str(document["id"])


def _set_slots(
    client: TestClient, document_id: str, fragment_id: str, slots: dict[str, Any]
) -> Any:
    document = client.get(f"/documents/{document_id}").json()
    return client.post(
        f"/documents/{document_id}/web/operations",
        json={
            "base_version": document["current_version"],
            "intent": "edit cloned section slot values",
            "operations": [
                {
                    "kind": "set_node_props",
                    "page_id": "home",
                    "id": "frg_clone",
                    "props": {
                        "kind": "fragment",
                        "fragment_id": fragment_id,
                        "slots": slots,
                    },
                }
            ],
        },
    )


def test_every_slot_kind_round_trips_through_the_ordinary_props_write(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    """The card writes slot VALUES through SetNodeProps — the F1.1 path, not a new one.

    Four kinds, one write: a text field, an asset picker, a link field and a visibility toggle.
    The fragment's own markup is untouched by all of it, which is D-F3/R1: the inspector edits
    what the slots hold, never what the clone IS.
    """
    row = _mint(workspace_id, design_storage, sentinel="Slotted band")
    document_id = _document_pinning(workspace_id, design_storage, row["fragment_id"])
    response = _set_slots(
        client,
        document_id,
        row["fragment_id"],
        {
            "headline": {"text": "Care, on your terms"},
            "art": {"asset": "asset_ward_1"},
            "cta": {"text": "https://insight.example/book"},
            "visible": {"visible": False},
        },
    )
    assert response.status_code == 200, response.text
    from lumen_api.design_store import HybridRepository

    stored = HybridRepository(workspace_id=workspace_id).require_document(document_id)
    node = stored["scene"]["pages"][0]["nodes"]["frg_clone"]
    assert node["slots"] == {
        "headline": {"text": "Care, on your terms"},
        "art": {"asset": "asset_ward_1"},
        "cta": {"text": "https://insight.example/book"},
        "visible": {"visible": False},
    }
    # The pin itself did not move, and there is no markup on the node to have edited.
    assert node["fragment_id"] == row["fragment_id"]
    assert "html" not in node


def test_an_asset_slot_naming_a_picture_the_document_does_not_carry_is_refused(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    """F1 ruling #9 / LUMW0035: an asset slot resolves through ``doc.assets``, or it does not
    resolve. The asset picker offers the document's own assets for exactly this reason."""
    row = _mint(workspace_id, design_storage, sentinel="Unbacked art")
    document_id = _document_pinning(workspace_id, design_storage, row["fragment_id"])
    response = _set_slots(
        client, document_id, row["fragment_id"], {"art": {"asset": "asset_not_here"}}
    )
    assert response.status_code == 422, response.text
    codes = {
        diagnostic.get("code")
        for diagnostic in response.json()["detail"].get("diagnostics") or []
    }
    assert "LUMW0035" in codes, response.text


def test_an_unbroken_never_repaired_clone_carries_no_lineage_noise(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    row = _mint(workspace_id, design_storage, sentinel="A healthy band")
    card = client.get(f"/web/fragments/{row['fragment_id']}").json()
    assert card["degraded"] is False
    assert card["degraded_note"] is None
    assert [entry["fragment_id"] for entry in card["family"]] == [row["fragment_id"]]
    assert card["repairs_what"] is None
    assert card["superseded_by"] is None
    assert card["lineage_ambiguous"] == []
    assert card["hidden_on_source"] is None
