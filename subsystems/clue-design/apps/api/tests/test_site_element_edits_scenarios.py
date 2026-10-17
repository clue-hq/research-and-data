"""Site element inspector, plan 1: a section's manual styling (`_edits`) through the real routes —
the editor's save, the stored document, undo and redo, refusals, and the published page.

    .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \
        subsystems/clue-design/apps/api/tests/test_site_element_edits_scenarios.py
"""

from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from conftest import published_html
from site_kit_support import garner_site_without_clones
from test_site_publish_routes import client, ok, publish, stored  # noqa: F401 - `client` is a fixture

STYLE = {"color": {"token": "text.primary"}, "fontSize": 48, "fontWeight": 600, "italic": True, "textAlign": "center"}


def stored_site(client: TestClient, document_id: str) -> dict:
    return client.get(f"/documents/{document_id}").json()["scene"]


def version(client: TestClient, document_id: str) -> int:
    return client.get(f"/documents/{document_id}").json()["current_version"]


def save(client: TestClient, document_id: str, site: dict):
    return client.put(f"/documents/{document_id}/site", json={"site": site, "base_version": version(client, document_id)})


def styled(site: dict, edits: dict, header_edits: dict | None = None) -> dict:
    """The site with the home page's first section (Garner's StatsBand) styled by hand."""
    changed = copy.deepcopy(site)
    changed["pages"]["/"]["content"][0]["props"]["_edits"] = edits
    if header_edits is not None:
        changed["shell"]["header"]["_edits"] = header_edits
    return changed


def test_manual_styling_is_saved_read_back_undone_redone_and_published(client: TestClient, workspace_id: str) -> None:
    site = stored(client, garner_site_without_clones("site_style"))
    section_id = site["pages"]["/"]["content"][0]["props"]["id"]
    assert save(client, "site_style", site).status_code == 200
    with_style = styled(site, {"heading": STYLE}, {"preparedFor": {"fontWeight": 700}})
    response = save(client, "site_style", with_style)
    assert response.status_code == 200, response.text

    read = stored_site(client, "site_style")
    assert read["pages"]["/"]["content"][0]["props"]["_edits"] == {"heading": STYLE}
    assert read["shell"]["header"]["_edits"] == {"preparedFor": {"fontWeight": 700}}

    undone = client.post("/documents/site_style/site/undo", json={"base_version": version(client, "site_style")})
    assert undone.status_code == 200, undone.text
    assert "_edits" not in stored_site(client, "site_style")["pages"]["/"]["content"][0]["props"]
    redone = client.post("/documents/site_style/site/redo", json={"base_version": version(client, "site_style")})
    assert redone.status_code == 200, redone.text
    assert stored_site(client, "site_style")["pages"]["/"]["content"][0]["props"]["_edits"] == {"heading": STYLE}

    ok(publish(client, "site_style", slug="style-site"))
    html = published_html(workspace_id, "style-site")
    assert f'data-clue-section="{section_id}"' in html
    rule = f'[data-clue-section="{section_id}"] [data-clue-el="heading"]{{'
    assert rule in html, "the section's manual styling is drawn beside it on the published page"
    declarations = html.split(rule, 1)[1].split("}", 1)[0]
    for expected in ("color:var(--brand-", "font-size:48px !important", "font-weight:600 !important",
                     "font-style:italic !important", "text-align:center !important"):
        assert expected in declarations, (expected, declarations)
    assert '[data-clue-section="shell-header"] [data-clue-el="preparedFor"]{font-weight:700 !important}' in html
    assert 'data-clue-el="heading"' in html, "the styled element carries its key on the published page"


def test_a_malformed_or_off_brand_style_is_refused_by_name(client: TestClient) -> None:
    site = stored(client, garner_site_without_clones("site_style_bad"))
    assert save(client, "site_style_bad", site).status_code == 200

    too_small = save(client, "site_style_bad", styled(site, {"heading": {"fontSize": 1}}))
    assert too_small.status_code == 422, too_small.text
    assert too_small.json()["detail"]["code"] == "site.invalid"
    assert any("_edits" in error and "heading" in error for error in too_small.json()["detail"]["errors"])

    off_brand = save(client, "site_style_bad", styled(site, {"heading": {"color": {"token": "no.such.colour"}}}))
    assert off_brand.status_code == 422, off_brand.text
    errors = off_brand.json()["detail"]["errors"]
    assert any("_edits.heading" in error and "no.such.colour" in error for error in errors), errors

    free_css = save(client, "site_style_bad", styled(site, {"heading": {"background": "url(x)"}}))
    assert free_css.status_code == 422, free_css.text


def test_styling_for_an_element_the_section_no_longer_has_is_kept_and_harmless(client: TestClient, workspace_id: str) -> None:
    site = stored(client, garner_site_without_clones("site_style_gone"))
    assert save(client, "site_style_gone", site).status_code == 200
    response = save(client, "site_style_gone", styled(site, {"gone": {"italic": True}}))
    assert response.status_code == 200, response.text
    ok(publish(client, "site_style_gone", slug="style-gone"))
    assert 'data-clue-el="gone"' not in published_html(workspace_id, "style-gone").split("</style>")[-1]
