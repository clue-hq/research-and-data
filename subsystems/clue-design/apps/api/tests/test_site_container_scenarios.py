"""Site element inspector, plan 4: boxes through the real routes. A card's and a section's own box
styled by hand, a stat moved with its styling, a copied section's children reordered, the header's
parts reordered and its logo hidden: the editor's save, the stored document, undo and redo, refusals,
and the published page.

    .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        subsystems/clue-design/apps/api/tests/test_site_container_scenarios.py
"""

from __future__ import annotations

import copy

from fastapi.testclient import TestClient
from test_site_element_edits_scenarios import client, save, stored_site, version  # noqa: F401 - the fixture
from test_site_publish_package import mint_fragment
from test_site_publish_routes import ok, publish, stored
from site_kit_support import garner_brand, garner_site_without_clones

from conftest import published_html, published_page_html

# A copied section of three cards (keys 0.0, 0.1, 0.2 under the row 0).
CARDS = {
    "id": "frag_00000000000000c4",
    "role": "section",
    "label": "Cards",
    "page_url": "https://garnerhealth.com/",
    "section_index": 0,
    "wrapper_class": "lumen-frag-cards",
    "html": (
        '<div class="cards"><div class="card"><h3>Alpha</h3></div>'
        '<div class="card"><h3>Beta</h3></div><div class="card"><h3>Gamma</h3></div></div>'
    ),
    "css": ".cards{display:flex;gap:12px}",
    "slots": {},
}

CARD_BOX = {
    "fill": {"hex": "#F4F6F5", "opacity": 100},
    "borderColor": {"hex": "#0F59B0", "opacity": 100},
    "borderWidth": 2,
    "radius": 16,
    "padding": {"y": 24, "x": 32},
    "gap": 12,
    "contentAlign": {"along": "grid", "to": "center"},
}
PROOF = {
    "id": "card_proof",
    "surface": "card",
    "kicker": "Carmel Clay",
    "metric": "13%",
    "metricLabel": "lower cost",
    "heading": "What changed",
    "body": "",
    "source": "",
    "linkLabel": "",
    "linkHref": "",
}


def brand_with_cards(fragment_id: str = CARDS["id"]) -> dict:
    brand = garner_brand()
    brand["clones"] = {**brand["clones"], fragment_id: {**CARDS, "id": fragment_id}}
    return brand


def boxes(site: dict, fragment_id: str = CARDS["id"]) -> dict:
    """A ProofCard's card and its section box styled; the stats band's second stat moved first with its
    styling (as the editor writes it); a copied row of cards reordered; the header's button put before
    its menu, its menu reordered and its logo hidden."""
    changed = copy.deepcopy(site)
    changed["pages"]["/analysis"]["content"].append(
        {"type": "ProofCard", "props": {**PROOF, "_edits": {"card": CARD_BOX, "root": {"fill": {"hex": "#112233", "opacity": 100}}, "root.inner": {"padding": 40}}}}
    )
    proof = next(item for item in changed["pages"]["/"]["content"] if item["props"]["id"] == "proof")["props"]
    proof["stats"] = [proof["stats"][1], proof["stats"][0], *proof["stats"][2:]]
    proof["_edits"] = {"stats.0.value": {"color": {"hex": "#0F59B0", "opacity": 100}}, "stats.1": {"fill": {"hex": "#FFFFFF", "opacity": 100}}}
    changed["pages"]["/"]["content"].append(
        {
            "type": "ClonedSection",
            "props": {"id": "cards", "fragmentId": fragment_id, "slots": {}, "replacements": [], "links": [], "_edits": {"0": {"order": ["0.2", "0.0", "0.1"]}}},
        }
    )
    header = changed["shell"]["header"]
    header["nav"] = [{"label": "Contact", "href": "/"}, {"label": "The analysis", "href": "/analysis"}]
    header["_edits"] = {"actions": {"order": ["ctaArea", "nav"]}, "logo": {"hidden": True}}
    return changed


def rule(html: str, section: str, key: str) -> str:
    selector = f'[data-clue-section="{section}"] [data-clue-el="{key}"]{{'
    assert selector in html, selector
    return html.split(selector, 1)[1].split("}", 1)[0]


def before(html: str, first: str, second: str) -> bool:
    return html.index(first) < html.index(second)


def test_boxes_moves_and_hidden_parts_are_saved_read_back_undone_redone_and_published(client: TestClient, workspace_id: str, design_storage) -> None:  # noqa: F811
    fragment_id = mint_fragment(design_storage, workspace_id, "cards", "approved")
    site = stored(client, garner_site_without_clones("site_boxes"), brand_with_cards(fragment_id))
    proof_stats = next(item for item in site["pages"]["/"]["content"] if item["props"]["id"] == "proof")["props"]["stats"]
    assert len(proof_stats) >= 2, "the fixture's stats band has stats to move"
    assert save(client, "site_boxes", site).status_code == 200
    changed = boxes(site, fragment_id)
    response = save(client, "site_boxes", changed)
    assert response.status_code == 200, response.text

    read = stored_site(client, "site_boxes")
    card = read["pages"]["/analysis"]["content"][-1]["props"]
    assert card["_edits"]["card"] == CARD_BOX
    proof = next(item for item in read["pages"]["/"]["content"] if item["props"]["id"] == "proof")["props"]
    assert proof["stats"][0] == proof_stats[1] and proof["_edits"]["stats.1"] == {"fill": {"hex": "#FFFFFF", "opacity": 100}}
    assert read["pages"]["/"]["content"][-1]["props"]["_edits"] == {"0": {"order": ["0.2", "0.0", "0.1"]}}
    assert read["shell"]["header"]["_edits"] == {"actions": {"order": ["ctaArea", "nav"]}, "logo": {"hidden": True}}

    # Undo takes the whole change back, the header included; redo brings it again.
    assert client.post("/documents/site_boxes/site/undo", json={"base_version": version(client, "site_boxes")}).status_code == 200
    undone = stored_site(client, "site_boxes")
    assert undone["shell"]["header"] == site["shell"]["header"]
    assert all(item["props"]["id"] != "card_proof" for item in undone["pages"]["/analysis"]["content"])
    assert client.post("/documents/site_boxes/site/redo", json={"base_version": version(client, "site_boxes")}).status_code == 200
    assert stored_site(client, "site_boxes")["shell"]["header"]["_edits"]["logo"] == {"hidden": True}

    ok(publish(client, "site_boxes", slug="box-site"))
    analysis = published_page_html(workspace_id, "box-site", "/analysis")
    painted = rule(analysis, "card_proof", "card")
    for expected in (
        "background-color:#F4F6F5FF !important",
        "border-color:#0F59B0FF !important",
        "border-width:2px !important",
        "border-radius:16px !important",
        "padding:24px 32px !important",
        "gap:12px !important",
        "justify-items:center !important",
    ):
        assert expected in painted, (expected, painted)
    assert "background-color:#112233FF !important" in rule(analysis, "card_proof", "root")
    assert "padding:40px !important" in rule(analysis, "card_proof", "root.inner")
    assert 'data-clue-el="card"' in analysis and 'data-clue-el="root.inner"' in analysis

    home = published_html(workspace_id, "box-site")
    assert before(home, ">Gamma<", ">Alpha<") and before(home, ">Alpha<", ">Beta<"), "the copied cards in their order"
    assert 'data-clue-el="0.2"' in home, "a moved copied card keeps its captured key"
    assert before(home, f">{proof_stats[1]['value']}<", f">{proof_stats[0]['value']}<"), "the moved stat comes first"
    assert "color:#0F59B0FF !important" in rule(home, "proof", "stats.0.value")
    assert before(home, 'data-clue-el="ctaArea"', 'data-clue-el="nav"'), "the header's button before its menu"
    assert before(home, ">Contact<", ">The analysis<"), "the menu in its new order"
    assert "display:none !important" in rule(home, "shell-header", "logo")


def test_a_hidden_section_part_a_repeated_order_key_a_wide_gap_and_an_unknown_alignment_are_refused_by_name(client: TestClient) -> None:  # noqa: F811
    site = stored(client, garner_site_without_clones("site_boxes_bad"), brand_with_cards())
    assert save(client, "site_boxes_bad", site).status_code == 200

    def refused(edits: dict) -> list[str]:
        changed = copy.deepcopy(site)
        changed["pages"]["/analysis"]["content"][0]["props"]["_edits"] = edits
        response = save(client, "site_boxes_bad", changed)
        assert response.status_code == 422, response.text
        return response.json()["detail"]["errors"]

    assert any("hidden is for the header and footer" in error for error in refused({"heading": {"hidden": True}}))
    assert any("each key once in an order" in error for error in refused({"row": {"order": ["column", "column"]}}))
    assert any("gap" in error for error in refused({"row": {"gap": 300}}))
    assert any("contentAlign" in error for error in refused({"row": {"contentAlign": {"along": "column", "to": "center"}}}))
