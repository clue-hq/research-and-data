"""Site element inspector, plan 6: the header and footer as sections, through the real routes. A
kit's header template minted from a captured nav band and used as a site's header; its words, account
logo and placement saved, undone and published; the menu following the site's pages; one template
serving two accounts; an agent's own header checked and published; the old shell shape refused.

    .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \\
        subsystems/clue-design/apps/api/tests/test_site_shell_scenarios.py
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_site_element_edits_scenarios import client, save, stored_site, version  # noqa: F401 - the fixture
from test_site_publish_routes import ok, publish, stored
from site_kit_support import QUOTE_JS, QUOTE_SCHEMA, garner_brand, garner_site_without_clones, hold_site_images, section_module, store_site

from conftest import published_page_html
from lumen_api.agent_cloned_sections import DurableAgentClonedSectionRegistry
from lumen_api.design_store import DesignBlobStore, HybridRepository
from lumen_api.fragments import create_web_fragment
from lumen_api.fragments.cssscope import PRELUDE_REFERENCE_STRIP
from lumen_api.public_address import PublicSiteAddress
from lumen_api.site_publish import build_site_publish_package
from lumen_api.site_render import SiteRenderError, read_section_schema
from lumen_api.site_workspace_view import list_site_clones

NAV = (Path(__file__).parent / "fixtures" / "site_templates" / "webflow_header.html").read_text()


def template_brand(workspace_id: str, design_storage, tmp_path) -> tuple[dict, str, str]:
    """The Garner brand with a header template minted from a captured nav band, as the catalog offers
    it (the real clone shape), and the template's placeholder logo file."""
    _row, band = create_web_fragment(
        design_storage, workspace_id=workspace_id, html=NAV, css=".nav_link{color:#123456}", rehosted={},
        source_url="https://garnerhealth.com/", section_role="nav", label="Nav", preview=None,
        provenance={"page_url": "https://garnerhealth.com/", "section_index": 0}, prelude_reference=PRELUDE_REFERENCE_STRIP,
    )
    registry = DurableAgentClonedSectionRegistry(blobs=DesignBlobStore(design_storage, workspace_id), cache_dir=tmp_path / "cache")
    minted = registry.mint_site_template(role="site_header", source_fragment_id=band.fragment_id)
    [clone] = [c for c in list_site_clones(registry.blobs, tmp_path / "cache") if c["id"] == minted["fragment_id"]]
    brand = garner_brand()
    brand["clones"] = {**brand["clones"], clone["id"]: clone}
    placeholder = f"/asset-store/{registry.campaign_shell_placeholder()['digest']}"
    return brand, clone["id"], placeholder


def with_template_header(site: dict, template: str, slots: dict | None = None, **props) -> dict:
    changed = copy.deepcopy(site)
    changed["shell"]["header"] = {
        "type": "ClonedSection",
        "props": {"id": "header", "fragmentId": template, "slots": slots or {}, "replacements": [], "links": [], **props},
    }
    return changed


def header_of(html: str) -> str:
    start = html.index('data-clue-section="header"')
    return html[start:html.index('data-clue-section="', start + 30)]


def test_template_header_edited_undone_published(client: TestClient, workspace_id: str, design_storage, tmp_path) -> None:  # noqa: F811
    brand, template, _placeholder = template_brand(workspace_id, design_storage, tmp_path)
    logo = next(asset["file"] for asset in brand["assets"].values() if str(asset.get("file", "")).startswith("/asset-store/"))
    # Every image the changed site names is held by the workspace (the helper swaps in stored digests);
    # the starting site is the same copy without the changes.
    words = stored(client, with_template_header(garner_site_without_clones("site_shell"), template, {"account_line": "Built for Carmel <strong>Clay</strong>", "account_logo": logo}), brand)
    logo = words["shell"]["header"]["props"]["slots"]["account_logo"]
    site = with_template_header(words, template)
    assert save(client, "site_shell", site).status_code == 200
    assert save(client, "site_shell", words).status_code == 200
    sticky = copy.deepcopy(words)
    sticky["shell"]["header"]["props"]["_edits"] = {"root": {"sticky": True}}
    assert save(client, "site_shell", sticky).status_code == 200
    both = copy.deepcopy(sticky)
    both["shell"]["header"]["props"]["_edits"]["root"]["overlay"] = True
    response = save(client, "site_shell", both)
    assert response.status_code == 200, response.text
    assert stored_site(client, "site_shell")["shell"]["header"]["props"]["_edits"] == {"root": {"sticky": True, "overlay": True}}

    assert client.post("/documents/site_shell/site/undo", json={"base_version": version(client, "site_shell")}).status_code == 200
    assert stored_site(client, "site_shell")["shell"]["header"] == sticky["shell"]["header"]

    ok(publish(client, "site_shell", slug="shell-site"))
    home = published_page_html(workspace_id, "shell-site", "/")
    sections = [part.split('"', 1)[0] for part in home.split('data-clue-section="')[1:]]
    assert sections[0] == "header" and sections[-1] == "footer", sections
    header = header_of(home)
    assert "data-clue-sticky" in header and "data-clue-overlay" not in header
    assert "Built for Carmel <strong>Clay</strong>" in header
    assert logo.split("/")[-1] in header


def test_menu_follows_pages(client: TestClient, workspace_id: str, design_storage, tmp_path) -> None:  # noqa: F811
    brand, template, _placeholder = template_brand(workspace_id, design_storage, tmp_path)
    site = stored(client, with_template_header(garner_site_without_clones("site_menu"), template, menuLabels={"analysis": "The analysis"}), brand)
    assert save(client, "site_menu", site).status_code == 200
    grown = copy.deepcopy(site)
    team = copy.deepcopy(site["pages"]["/analysis"])
    team["root"]["props"]["title"] = "Team"
    grown["pages"]["/team"] = team
    response = save(client, "site_menu", grown)
    assert response.status_code == 200, response.text

    ok(publish(client, "site_menu", slug="menu-site"))
    for route in ("/", "/analysis", "/team"):
        header = header_of(published_page_html(workspace_id, "menu-site", route))
        keys = [part.split('"', 1)[0] for part in header.split('data-clue-el="menu.')[1:]]
        assert [key for key in keys if not key.endswith(".label")] == ["_home", "analysis", "team"], (route, keys)
        assert "The analysis" in header and ">Team<" in header and "Employers" not in header


def test_one_template_two_accounts(client: TestClient, workspace_id: str, design_storage, tmp_path) -> None:  # noqa: F811
    brand, template, placeholder = template_brand(workspace_id, design_storage, tmp_path)
    files = [asset["file"] for asset in brand["assets"].values() if str(asset.get("file", "")).startswith("/asset-store/")]
    for doc, line, logo in (("site_acct_a", "Built for Carmel Clay", files[0]), ("site_acct_b", "Made for Oliver Hotels", files[1])):
        site = stored(client, with_template_header(garner_site_without_clones(doc), template, {"account_line": line, "account_logo": logo}), brand)
        logo = site["shell"]["header"]["props"]["slots"]["account_logo"]
        response = save(client, doc, site)
        assert response.status_code == 200, response.text
        ok(publish(client, doc, slug=doc.replace("_", "-")))
        header = header_of(published_page_html(workspace_id, doc.replace("_", "-"), "/"))
        assert line in header and logo.split("/")[-1] in header
        assert placeholder not in header and "{{" not in header and "Prepared for you" not in header


def test_agent_header_checked_like_a_section(client: TestClient, workspace_id: str, design_storage) -> None:  # noqa: F811
    forbidden = QUOTE_JS.replace("quote: z.string().min(1) })", "quote: z.string().min(1), className: z.string() })")
    with pytest.raises(SiteRenderError) as refused:
        read_section_schema(forbidden)
    assert 'the props may not include "className"' in str(refused.value)

    module = section_module("SiteHeaderQuote", QUOTE_JS, QUOTE_SCHEMA)
    site = garner_site_without_clones("site_agent_header")
    site["shell"]["header"] = {"type": "SiteHeaderQuote", "props": {"id": "header", "surface": "page", "quote": "For Carmel Clay"}}
    site["agent_sections"] = {"SiteHeaderQuote": module.digest}
    blobs = DesignBlobStore(design_storage, workspace_id)
    site, brand = hold_site_images(site, garner_brand(), blobs)
    store_site(site)
    package = build_site_publish_package(
        HybridRepository(), HybridRepository().require_document(site["id"]), blobs=blobs, brand=brand, sections=[module],
        slug="agent-header", site_address=PublicSiteAddress(origin="https://a.pages.test", site_path="/agent-header", asset_origin="https://a.pages.test"),
        fragment_status=lambda fragment_id: "approved",
    )
    home = next(page for page in package.pages if page.route == "/")
    header = header_of(home.html)
    assert "For Carmel Clay" in header and 'data-agent-section="SiteHeaderQuote"' in header


def test_old_shell_refused_at_save(client: TestClient) -> None:  # noqa: F811
    site = stored(client, garner_site_without_clones("site_old_shell"), garner_brand())
    assert save(client, "site_old_shell", site).status_code == 200
    old = copy.deepcopy(site)
    old["shell"] = {"header": {"preparedFor": "SCSD", "ctaLabel": "Go", "ctaHref": "/"}, "footer": {"legal": "©"}}
    response = save(client, "site_old_shell", old)
    assert response.status_code == 422, response.text
    assert any(error.startswith("shell.json: the header and footer are sections") for error in response.json()["detail"]["errors"])
