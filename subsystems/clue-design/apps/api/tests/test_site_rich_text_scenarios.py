"""Site element inspector, plan 2: rich text, links and library fonts through the real routes — the
editor's save, the stored document, undo and redo, refusals, and the published page.

    .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        subsystems/clue-design/apps/api/tests/test_site_rich_text_scenarios.py
"""

from __future__ import annotations

import copy

from fastapi.testclient import TestClient
from test_site_element_edits_scenarios import client, save, stored_site, version  # noqa: F401 - the fixture
from test_site_publish_routes import ok, publish, stored
from lumen_api.font_library import site_library_fonts
from site_kit_support import garner_brand, garner_site_without_clones

from conftest import published_html, published_manifest

def library_brand() -> dict:
    """Garner's brand with the checked-in font library, as the real brand loader gives it."""
    return {**garner_brand(), "libraryFonts": site_library_fonts()}


HEADING = 'Lower <strong>spend</strong> in <span data-s="heading~1">year one</span>'
INTRO = 'Read <a href="/analysis" data-new-tab="">the analysis</a> &amp; decide'


def rich(site: dict) -> dict:
    """The home page's stats band with rich words, a styled span, a new-tab link and a library font."""
    changed = copy.deepcopy(site)
    props = changed["pages"]["/"]["content"][0]["props"]
    props["heading"] = HEADING
    props["intro"] = INTRO
    props["_edits"] = {"heading~1": {"fontWeight": 700, "fontFamily": "Fraunces"}}
    changed["shell"]["header"]["props"]["menuExtra"] = [{"label": "The analysis", "href": "/analysis", "newTab": True}]
    return changed


def test_rich_text_is_saved_read_back_undone_redone_and_published(client: TestClient, workspace_id: str) -> None:  # noqa: F811
    site = stored(client, garner_site_without_clones("site_rich"), library_brand())
    section_id = site["pages"]["/"]["content"][0]["props"]["id"]
    assert save(client, "site_rich", site).status_code == 200
    response = save(client, "site_rich", rich(site))
    assert response.status_code == 200, response.text

    read = stored_site(client, "site_rich")["pages"]["/"]["content"][0]["props"]
    assert (read["heading"], read["intro"], read["_edits"]) == (HEADING, INTRO, {"heading~1": {"fontWeight": 700, "fontFamily": "Fraunces"}})

    assert client.post("/documents/site_rich/site/undo", json={"base_version": version(client, "site_rich")}).status_code == 200
    assert stored_site(client, "site_rich")["pages"]["/"]["content"][0]["props"]["heading"] == site["pages"]["/"]["content"][0]["props"]["heading"]
    assert client.post("/documents/site_rich/site/redo", json={"base_version": version(client, "site_rich")}).status_code == 200
    assert stored_site(client, "site_rich")["pages"]["/"]["content"][0]["props"]["heading"] == HEADING

    ok(publish(client, "site_rich", slug="rich-site"))
    html = published_html(workspace_id, "rich-site")
    assert 'Lower <strong>spend</strong> in <span data-s="heading~1">year one</span>' in html
    assert f'[data-clue-section="{section_id}"] [data-s="heading~1"]{{' in html
    rule = html.split(f'[data-clue-section="{section_id}"] [data-s="heading~1"]{{', 1)[1].split("}", 1)[0]
    assert 'font-family:"Fraunces", serif !important' in rule and "font-weight:700 !important" in rule, rule
    assert 'Read <a href="/rich-site/analysis" target="_blank" rel="noopener">the analysis</a> &amp; decide' in html
    assert 'target="_blank" rel="noopener" class="brand-navlink"' in html, "the header's new-tab link"


def test_a_library_font_whose_files_this_environment_lacks_publishes_with_a_warning(client: TestClient, workspace_id: str) -> None:  # noqa: F811
    site = stored(client, garner_site_without_clones("site_rich_font"), library_brand())
    assert save(client, "site_rich_font", site).status_code == 200
    assert save(client, "site_rich_font", rich(site)).status_code == 200
    ok(publish(client, "site_rich_font", slug="rich-font"))
    manifest = published_manifest(workspace_id, "rich-font")
    assert any("font library face Fraunces" in warning for warning in manifest["warnings"]), manifest["warnings"]


def test_rich_text_outside_the_grammar_and_a_link_to_no_page_are_refused_by_name(client: TestClient) -> None:  # noqa: F811
    site = stored(client, garner_site_without_clones("site_rich_bad"), library_brand())
    assert save(client, "site_rich_bad", site).status_code == 200
    for heading, expected in (
        ('<div class="x">Lower</div>', "<div> is not allowed in text"),
        ('<p style="color:red">Lower</p>', 'attribute "style" is not allowed on <p>'),
        ('<a href="/missing">Lower</a>', "links to /missing, which is not a page of this site"),
        ('<span data-s="a b">Lower</span>', "data-s must be an element key"),
    ):
        changed = copy.deepcopy(site)
        changed["pages"]["/"]["content"][0]["props"]["heading"] = heading
        response = save(client, "site_rich_bad", changed)
        assert response.status_code == 422, (heading, response.text)
        errors = response.json()["detail"]["errors"]
        assert any(".heading: " in error and expected in error for error in errors), (heading, errors)
    unknown_font = copy.deepcopy(site)
    unknown_font["pages"]["/"]["content"][0]["props"]["_edits"] = {"heading": {"fontFamily": "Comic Sans"}}
    response = save(client, "site_rich_bad", unknown_font)
    assert response.status_code == 422
    assert any("Comic Sans" in error and "font library" in error for error in response.json()["detail"]["errors"])
