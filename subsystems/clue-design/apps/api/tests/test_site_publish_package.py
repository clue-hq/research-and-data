"""The site publish package (Wave 2 Contract 3) — the master plan's Review focus 5 and 7."""

from __future__ import annotations

import pytest

from clue_design.publishes import SITE_DELIVERY_CSP_META
from lumen_api.design_store import DesignBlobStore, HybridRepository
from lumen_api.public_address import PublicSiteAddress
from lumen_api.site_publish import SitePublishRefused, build_site_publish_package
from lumen_api.site_render import SECTION_MODULE_MISSING, SiteRenderError
from site_kit_support import (
    QUOTE_SCHEMA,
    chromium_available,
    ensure_site_kit_dist,
    garner_brand,
    garner_site,
    garner_site_without_clones,
    hold_site_images,
    section_module,
    store_site,
)

ADDRESS = PublicSiteAddress(origin="https://acme.pages.test", site_path="/acme-site", asset_origin="https://acme.pages.test")
HOSTILE_JS = """import { jsx, jsxs } from "react/jsx-runtime";
import { z } from "zod";
export const schema = z.object({ id: z.string(), surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]), quote: z.string().min(1) }).strict();
export function render(props, kit) {
  return jsxs(kit.Shell, { surface: props.surface, children: [
    jsx("div", { dangerouslySetInnerHTML: { __html: '<script>steal()</script><img src="https://collector.example/p.gif" onerror="steal()"><a href="javascript:steal()">x</a><iframe src="https://collector.example/f"></iframe><div style="background:url(https://collector.example/bg.png)">y</div>' } }),
    jsx("img", { src: "https://collector.example/direct.png", alt: "" }),
    jsx("p", { children: props.quote }),
  ] });
}
"""


@pytest.fixture(autouse=True)
def _browser_and_bundle() -> None:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()


@pytest.fixture()
def blobs(design_storage, workspace_id: str) -> DesignBlobStore:
    return DesignBlobStore(design_storage, workspace_id)


def build(document_id: str, site: dict, brand: dict, sections: list, **extra):
    store_site(site)
    document = HybridRepository().require_document(document_id)
    return build_site_publish_package(
        HybridRepository(), document, blobs=extra.pop("blobs"), brand=brand, sections=sections, slug="acme-site", site_address=ADDRESS, **extra
    )


def test_a_site_package_is_script_free_with_its_policy_manifest_and_rebased_links(blobs: DesignBlobStore) -> None:
    site, brand = hold_site_images(garner_site_without_clones("pub_pkg"), garner_brand(), blobs)
    package = build("pub_pkg", site, brand, [], blobs=blobs, default_description="An analysis for SCSD")
    assert [page.route for page in package.pages] == ["/", "/analysis"]
    home = package.html
    assert f'<meta http-equiv="Content-Security-Policy" content="{SITE_DELIVERY_CSP_META}">' in home
    assert '<meta name="description" content="An analysis for SCSD">' in home
    assert 'href="/acme-site/analysis"' in home
    assert 'id="site-static-css"' in home and "<script" not in home.lower()
    manifest = package.manifest
    assert manifest["delivery"] == "site" and manifest["custom_components"] == {}
    assert [entry["route"] for entry in manifest["pages"]] == ["/", "/analysis"]
    assert manifest["canonical_url"] == "https://acme.pages.test/acme-site"
    assert "font_families_included" in manifest and package.assets == {} and package.runtime_version is None


def test_agent_html_publishes_without_script_handlers_or_foreign_urls(blobs: DesignBlobStore) -> None:
    module = section_module("Hostile", HOSTILE_JS, props_schema=QUOTE_SCHEMA)
    site, brand = hold_site_images(garner_site_without_clones("pub_hostile"), garner_brand(), blobs)
    site["agent_sections"] = {"Hostile": module.digest}
    site["pages"]["/"]["content"].append({"type": "Hostile", "props": {"id": "h", "surface": "page", "quote": "Still here."}})
    package = build("pub_hostile", site, brand, [module], blobs=blobs)
    html = package.html.lower()
    for gone in ("<script", "onerror", "javascript:", "<iframe", "collector.example"):
        assert gone not in html, gone
    assert "still here." in html


def test_a_missing_or_stale_module_refuses_the_publish(blobs: DesignBlobStore) -> None:
    module = section_module("Quote", HOSTILE_JS)
    site, brand = hold_site_images(garner_site_without_clones("pub_missing"), garner_brand(), blobs)
    site["agent_sections"] = {"Quote": module.digest}
    with pytest.raises(SiteRenderError) as refused:
        build("pub_missing", site, brand, [], blobs=blobs)
    assert refused.value.code == SECTION_MODULE_MISSING


def test_clone_pins_are_checked_at_publish(blobs: DesignBlobStore) -> None:
    site, brand = hold_site_images(garner_site("pub_clones"), garner_brand(), blobs)
    with pytest.raises(SitePublishRefused) as unresolved:
        build("pub_clones", site, brand, [], blobs=blobs, fragment_status=lambda fragment_id: None)
    assert unresolved.value.code == "site_publish.clone_unresolved"
    assert unresolved.value.message == (
        "This page uses a section that isn't in your brand's library. Ask the agent to replace it, then publish again."
    )
    document = HybridRepository().require_document("pub_clones")
    with pytest.raises(SitePublishRefused) as draft:
        build_site_publish_package(HybridRepository(), document, blobs=blobs, brand=brand, sections=[], slug="acme-site", site_address=ADDRESS, fragment_status=lambda fragment_id: "draft")
    assert draft.value.code == "site_publish.clone_not_approved"
    pinned = next(
        item["props"]["fragmentId"]
        for page in site["pages"].values()
        for item in page["content"]
        if item["type"] == "ClonedSection"
    )
    label = brand["clones"][pinned]["label"]
    assert draft.value.message == f'This page uses a section that isn\'t approved yet: "{label}". Approve your brand kit, then publish again.'
    assert "frag_" not in draft.value.message and "clone" not in draft.value.message.lower()
    package = build_site_publish_package(HybridRepository(), document, blobs=blobs, brand=brand, sections=[], slug="acme-site", site_address=ADDRESS, fragment_status=lambda fragment_id: "deprecated")
    assert package.manifest["fragments"]["ids"]
