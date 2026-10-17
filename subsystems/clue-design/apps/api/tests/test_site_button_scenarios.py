"""Site element inspector, plan 3: buttons through the real routes — a button's box styling and its
words' look, the header's button opening in a new tab, a copied section's button words through its
slot; the editor's save, the stored document, undo and redo, refusals, and the published page.

    .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        subsystems/clue-design/apps/api/tests/test_site_button_scenarios.py
"""

from __future__ import annotations

import copy

from fastapi.testclient import TestClient
from test_site_element_edits_scenarios import client, save, stored_site, version  # noqa: F401 - the fixture
from test_site_publish_package import mint_fragment
from test_site_publish_routes import ok, publish, stored
from site_kit_support import garner_brand, garner_site_without_clones

from conftest import published_html, published_page_html

# A copied section whose button holds its words in a text slot (key 0.1, its words 0.1.0).
CLOSE = {
    "id": "frag_00000000000000c1",
    "role": "section",
    "label": "Close",
    "page_url": "https://garnerhealth.com/",
    "section_index": 0,
    "wrapper_class": "lumen-frag-close",
    "html": (
        '<div class="close"><h2 data-lumen-slot="headline">Ready to see it?</h2>'
        '<a href="/book-a-demo" class="btn" data-lumen-slot="cta_href">'
        '<span data-lumen-slot="cta_label">Book a demo</span></a></div>'
    ),
    "css": ".close .btn{background:#0F59B0;color:#fff;padding:12px 20px}",
    "slots": {
        "headline": {"kind": "text", "fallback": "Ready to see it?"},
        "cta_label": {"kind": "text", "fallback": "Book a demo"},
        "cta_href": {"kind": "href", "fallback": "/book-a-demo"},
    },
}

BOX = {
    "fill": {"token": "surface.brand"},
    "borderColor": {"hex": "#000000", "opacity": 50},
    "borderWidth": 2,
    "radius": "pill",
    "padding": {"y": 10, "x": 28},
    "width": "fill",
}
LABEL = 'Request <span data-s="button.label~1">the analysis</span>'


def brand_with_close(fragment_id: str = CLOSE["id"]) -> dict:
    brand = garner_brand()
    brand["clones"] = {**brand["clones"], fragment_id: {**CLOSE, "id": fragment_id}}
    return brand


def buttons(site: dict, fragment_id: str = CLOSE["id"]) -> dict:
    """The analysis page's FeatureSplit button styled by hand with a styled word, the header's button
    in a new tab, and a copied close section whose button words are set through their slot."""
    changed = copy.deepcopy(site)
    what = changed["pages"]["/analysis"]["content"][0]["props"]
    what["buttonLabel"] = LABEL
    what["buttonNewTab"] = True
    what["_edits"] = {"button": BOX, "button.label~1": {"italic": True}}
    changed["shell"]["header"]["ctaNewTab"] = True
    changed["shell"]["header"]["ctaLabel"] = "Request <strong>the analysis</strong>"
    changed["pages"]["/"]["content"].append(
        {
            "type": "ClonedSection",
            "props": {
                "id": "close",
                "fragmentId": fragment_id,
                "slots": {"cta_label": 'Book <span data-s="0.1.0~1">a demo</span>'},
                "replacements": [],
                "links": [],
                "_edits": {"0.1": {"radius": [0, 12, 0, 12], "width": 240}, "0.1.0~1": {"fontWeight": 700}},
            },
        }
    )
    return changed


def rule(html: str, section: str, key: str, attr: str = "data-clue-el") -> str:
    selector = f'[data-clue-section="{section}"] [{attr}="{key}"]{{'
    assert selector in html, selector
    return html.split(selector, 1)[1].split("}", 1)[0]


def test_buttons_are_saved_read_back_undone_redone_and_published(client: TestClient, workspace_id: str, design_storage) -> None:  # noqa: F811
    fragment_id = mint_fragment(design_storage, workspace_id, "buttons", "approved")
    site = stored(client, garner_site_without_clones("site_buttons"), brand_with_close(fragment_id))
    assert save(client, "site_buttons", site).status_code == 200
    response = save(client, "site_buttons", buttons(site, fragment_id))
    assert response.status_code == 200, response.text

    read = stored_site(client, "site_buttons")
    what = read["pages"]["/analysis"]["content"][0]["props"]
    assert (what["buttonLabel"], what["buttonNewTab"], what["_edits"]["button"]) == (LABEL, True, BOX)
    assert read["shell"]["header"]["ctaNewTab"] is True
    close = read["pages"]["/"]["content"][-1]["props"]
    assert close["slots"] == {"cta_label": 'Book <span data-s="0.1.0~1">a demo</span>'}

    assert client.post("/documents/site_buttons/site/undo", json={"base_version": version(client, "site_buttons")}).status_code == 200
    undone = stored_site(client, "site_buttons")
    assert "_edits" not in undone["pages"]["/analysis"]["content"][0]["props"]
    assert "ctaNewTab" not in undone["shell"]["header"]
    assert client.post("/documents/site_buttons/site/redo", json={"base_version": version(client, "site_buttons")}).status_code == 200
    assert stored_site(client, "site_buttons")["pages"]["/analysis"]["content"][0]["props"]["_edits"]["button"] == BOX

    ok(publish(client, "site_buttons", slug="button-site"))
    analysis = published_page_html(workspace_id, "button-site", "/analysis")
    box = rule(analysis, "what", "button")
    for expected in (
        "background-color:var(--brand-",
        "background-image:none !important",
        "border-color:#00000080 !important",
        "border-width:2px !important",
        "border-style:solid !important",
        "border-radius:9999px !important",
        "padding:10px 28px !important",
        "width:100% !important",
    ):
        assert expected in box, (expected, box)
    assert "font-style:italic !important" in rule(analysis, "what", "button.label~1", "data-s")
    assert 'data-clue-el="button"' in analysis and 'data-clue-el="button.label"' in analysis
    assert 'Request <span data-s="button.label~1">the analysis</span>' in analysis
    assert 'href="https://garnerhealth.com/provider-impact-analysis" target="_blank" rel="noopener"' in analysis, "the button opens in a new tab"
    assert 'data-clue-el="cta"' in analysis and "Request <strong>the analysis</strong>" in analysis
    header = analysis.split('data-clue-el="cta"', 1)[0].rsplit("<a", 1)[1] + analysis.split('data-clue-el="cta"', 1)[1].split(">", 1)[0]
    assert 'target="_blank"' in header and 'rel="noopener"' in header, header

    home = published_html(workspace_id, "button-site")
    assert 'Book <span data-s="0.1.0~1">a demo</span>' in home
    corners = rule(home, "close", "0.1")
    assert "border-radius:0px 12px 0px 12px !important" in corners and "width:240px !important" in corners, corners
    assert "font-weight:700 !important" in rule(home, "close", "0.1.0~1", "data-s")


def test_a_radius_past_the_limit_and_a_link_inside_a_button_are_refused_by_name(client: TestClient) -> None:  # noqa: F811
    site = stored(client, garner_site_without_clones("site_buttons_bad"), brand_with_close())
    assert save(client, "site_buttons_bad", site).status_code == 200

    too_round = copy.deepcopy(site)
    too_round["pages"]["/analysis"]["content"][0]["props"]["_edits"] = {"button": {"radius": 300}}
    response = save(client, "site_buttons_bad", too_round)
    assert response.status_code == 422, response.text
    assert any("radius" in error for error in response.json()["detail"]["errors"]), response.json()

    linked = copy.deepcopy(site)
    linked["pages"]["/analysis"]["content"][0]["props"]["buttonLabel"] = 'Request <a href="/">the analysis</a>'
    response = save(client, "site_buttons_bad", linked)
    assert response.status_code == 422, response.text
    assert any(".buttonLabel: a button's words may not hold a link" in error for error in response.json()["detail"]["errors"]), response.json()


def test_buttons_may_go_to_different_outside_addresses(client: TestClient) -> None:  # noqa: F811
    site = stored(client, garner_site_without_clones("site_buttons_two"))
    assert save(client, "site_buttons_two", site).status_code == 200
    two = copy.deepcopy(site)
    content = two["pages"]["/analysis"]["content"]
    next(item for item in content if item["type"] == "FeatureSplit")["props"]["buttonHref"] = "https://garnerhealth.com/demo"
    next(item for item in content if item["type"] == "CtaBand")["props"]["buttonHref"] = "https://garnerhealth.com/contact"
    two["shell"]["header"]["ctaHref"] = "https://garnerhealth.com/pricing"
    response = save(client, "site_buttons_two", two)
    assert response.status_code == 200, response.text
