"""The site publish package (Wave 2 Contract 3) — the master plan's Review focus 5 and 7."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from pathlib import Path

import pytest

from clue_design.publishes import SITE_DELIVERY_CSP_META, site_live_csp
from clue_design.storage import SOURCE_KEY_ASSET, design_storage_key
from lumen_api import site_publish, web_export
from lumen_api.database import NotFoundError
from lumen_api.design_store import CustodyState, DesignBlobStore, HybridRepository
from lumen_api.fragments import create_web_fragment, set_web_fragment_status
from lumen_api.public_address import PublicSiteAddress
from lumen_api.site_doc_validate import SiteDocumentInvalid
from lumen_api.toolbelt.publishes import publish_site_document
from lumen_api.toolbelt.site_documents import write_site_document
from lumen_api.site_live import live_page_html, live_runtime, script_hash
from lumen_api.site_publish import SitePublishRefused, build_site_publish_package
from lumen_api.site_render import SECTION_MODULE_MISSING, SiteRenderError
from conftest import published_manifest
from site_kit_support import (
    QUOTE_JS,
    QUOTE_SCHEMA,
    chromium_available,
    ensure_site_kit_dist,
    garner_brand,
    garner_site,
    garner_site_without_clones,
    hold_site_images,
    png,
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


# --- Scenarios ------------------------------------------------------------------------------------
# Whole publishes over the real pieces: the Postgres test database (documents, artifact rows,
# fragment rows), this test's blob store, the real site-kit validator and render bundles, and real
# hardened Chromium. Each one builds the package a publish would persist and reads it the way the
# page origin and a visitor would.

INTER_TTF = Path(__file__).resolve().parents[3] / "fonts" / "Inter-Regular.ttf"
_ASSET_REF = re.compile(r"/asset-store/([0-9a-f]{64})")
_FONT_FACE = re.compile(r"@font-face\s*\{([^}]*)\}")
_ANCHOR = re.compile(r"<a\b[^>]*>", re.I)
_HREF = re.compile(r'\bhref="([^"]*)"')
DESCRIPTION = "An analysis for SCSD"


def page_html(package, route: str) -> str:
    return next(page.html for page in package.pages if page.route == route)


def head_of(html: str) -> str:
    return html[: html.index("</head>")]


def font_faces(html: str) -> list[tuple[str, str]]:
    """(family, src url) for every @font-face rule on the page."""
    faces = []
    for body in _FONT_FACE.findall(html):
        family = re.search(r'font-family:\s*"?([^";]+)"?', body)
        src = re.search(r'url\(\s*"?([^")]+)"?\s*\)', body)
        faces.append((family.group(1) if family else "", src.group(1) if src else ""))
    return faces


def anchor_hrefs(html: str) -> list[str]:
    return [match.group(1) for tag in _ANCHOR.findall(html) if (match := _HREF.search(tag))]


def again(document_id: str, brand: dict, sections: list, blobs: DesignBlobStore, **extra):
    """Build the package of the document as it is stored now (no new version)."""
    extra.setdefault("site_address", ADDRESS)
    return build_site_publish_package(
        HybridRepository(),
        HybridRepository().require_document(document_id),
        blobs=blobs,
        brand=brand,
        sections=sections,
        slug="acme-site",
        **extra,
    )


def cleaner_inputs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every page handed to the cleaner, recorded by a call-through wrapper, so a test can show the
    hostile bytes really reached it (a strip assertion over bytes that never arrived proves nothing)."""
    seen: list[str] = []
    real = site_publish.sanitize_site_html

    def recording(html: str):
        seen.append(html)
        return real(html)

    monkeypatch.setattr(site_publish, "sanitize_site_html", recording)
    return seen


def section_on_every_page(site: dict, module, props: dict) -> dict:
    site["agent_sections"] = {**site["agent_sections"], module.name: module.digest}
    for route, page in site["pages"].items():
        page["content"].append({"type": module.name, "props": {**props, "id": f"{props['id']}-{route.strip('/') or 'home'}"}})
    return site


# a. Font licence gate ----------------------------------------------------------------------------


def seed_font_face(blobs: DesignBlobStore, asset_id: str, data: bytes, mime_type: str) -> str:
    """Face bytes in this workspace's durable custody plus the asset record the kit names
    (tests/test_web_export.py's seed_font_asset, over this test's blob store)."""
    blobs.register(data, media_type=mime_type, source_key=SOURCE_KEY_ASSET)
    digest = hashlib.sha256(data).hexdigest()
    HybridRepository().create_asset_record(
        {
            "id": asset_id,
            "label": asset_id,
            "kind": "font",
            "status": "ready",
            "source": {"kind": "uploaded"},
            "media": {
                "mime_type": mime_type,
                "digest": {"algorithm": "sha256", "value": digest},
                "filename": f"{asset_id}.{mime_type.rsplit('/', 1)[-1]}",
                "byte_length": len(data),
                "location": None,
            },
        }
    )
    return digest


def test_only_the_embeddable_family_ships_and_the_manifest_says_why_the_other_did_not(blobs: DesignBlobStore) -> None:
    stored_ttf = seed_font_face(blobs, "asset_site_font_ofl", INTER_TTF.read_bytes(), "font/ttf")
    seed_font_face(blobs, "asset_site_font_locked", b"wOF2" + b"\x33" * 96, "font/woff2")
    brand = garner_brand()
    fonts = brand["kit"]["assets"]["fonts"]
    open_sans, stix = fonts["body"]["family"], fonts["brand"]["family"]
    fonts["body"] = {
        **fonts["body"],
        # The OFL by name: embeddable even though the flag says no (web_export._family_embeddable).
        "license": {"name": "OFL-1.1", "embeddable": False, "subsettable": True, "source_url": None, "restrictions": []},
        "faces": [{"weight": 400, "style": "normal", "asset_id": "asset_site_font_ofl", "source_url": None}],
    }
    fonts["brand"] = {
        **fonts["brand"],
        "license": {"name": "Commercial", "embeddable": False, "subsettable": False, "source_url": None, "restrictions": []},
        "faces": [{"weight": 400, "style": "normal", "asset_id": "asset_site_font_locked", "source_url": None}],
    }
    site, brand = hold_site_images(garner_site_without_clones("pub_fonts"), brand, blobs)
    package = build("pub_fonts", site, brand, [], blobs=blobs)

    faces = {route: font_faces(page_html(package, route)) for route in ("/", "/analysis")}
    shipped = faces["/"]
    assert len(shipped) == 1 and shipped[0][0] == open_sans, faces
    assert faces["/analysis"] == shipped
    digest = _ASSET_REF.fullmatch(shipped[0][1]).group(1)
    # The WOFF2 the gate encoded and registered, not the stored TTF: it is held, readable, WOFF2.
    assert digest != stored_ttf
    assert blobs.custody_states([digest])[digest] is CustodyState.READABLE
    assert blobs.read_blob(digest)[1][:4] == b"wOF2"
    # Its name stays in the type tokens' font stacks (the page falls back to the stack's next
    # family); what the gate withholds is the face: no @font-face anywhere names it.
    assert all(family != stix for route in faces for family, _src in faces[route])
    manifest = package.manifest
    assert manifest["font_families_included"] == [open_sans]
    assert manifest["font_families_excluded"] == [{"family": stix, "reason": "license not embeddable"}]
    assert digest in manifest["fragments"]["asset_digests"] and digest not in manifest["fragments"]["missing_asset_digests"]
    assert any(stix in warning and "license not embeddable" in warning for warning in package.warnings)
    assert package.warnings == manifest["warnings"]


# b. Bytes that cannot be read ---------------------------------------------------------------------


def test_unreadable_bytes_publish_with_a_warning_and_another_tenants_image_refuses(
    blobs: DesignBlobStore, design_storage, workspace_id: str
) -> None:
    site, brand = hold_site_images(garner_site_without_clones("pub_row_only"), garner_brand(), blobs)
    digest = _ASSET_REF.search(site["pages"]["/analysis"]["content"][0]["props"]["image"]).group(1)
    # The artifact row stays; the bytes go (a moved backend root, a restore without the object store).
    design_storage._path(design_storage_key(workspace_id, digest)).unlink()
    assert blobs.custody_states([digest])[digest] is CustodyState.ROW_ONLY

    package = build("pub_row_only", site, brand, [], blobs=blobs)
    assert f"/asset-store/{digest}" in page_html(package, "/analysis")
    assert digest in package.manifest["fragments"]["missing_asset_digests"]
    assert any(digest[:12] in warning and "not readable" in warning for warning in package.warnings)

    # Bytes another workspace holds: this workspace has no row naming them, so the site may not
    # show them (the public byte route would serve them; the custody check is the tenancy line).
    other = DesignBlobStore(design_storage, f"ws_test_other_{uuid.uuid4().hex[:12]}")
    foreign_bytes = png((3, 141, 59))
    other.register(foreign_bytes, media_type="image/png", source_key=SOURCE_KEY_ASSET)
    foreign = hashlib.sha256(foreign_bytes).hexdigest()
    assert blobs.custody_states([foreign])[foreign] is CustodyState.ABSENT
    site, brand = hold_site_images(garner_site_without_clones("pub_foreign"), garner_brand(), blobs)
    site["pages"]["/analysis"]["content"][2]["props"]["image"] = f"/asset-store/{foreign}"
    with pytest.raises(SiteDocumentInvalid) as refused:
        build("pub_foreign", site, brand, [], blobs=blobs)
    assert any(f"/asset-store/{foreign} is not stored in this workspace" in error for error in refused.value.errors), refused.value.errors


# c. Determinism and digests -----------------------------------------------------------------------


def manifest_back_reference(package) -> str:
    """The three lines the builder injects once the manifest is final."""
    return (
        f'<meta http-equiv="Content-Security-Policy" content="{SITE_DELIVERY_CSP_META}">\n'
        f'<meta name="lumen-publish-manifest-digest" content="{package.manifest_digest}">\n'
        '<link rel="lumen-publish-manifest" href="/acme-site/manifest.json">\n'
    )


def assert_digests_are_of_what_they_name(package) -> None:
    assert package.manifest_digest == web_export._sha256(web_export._canonical_json(package.manifest))
    recorded = {entry["route"]: entry["html_digest"] for entry in package.manifest["pages"]}
    for page in package.pages:
        assert page.html_digest == web_export._sha256(page.html)
        assert page.html.count('name="lumen-publish-manifest-digest"') == 1
        assert f'<meta name="lumen-publish-manifest-digest" content="{package.manifest_digest}">' in page.html
        # The manifest's page digest is the page before its own back-reference went in.
        assert recorded[page.route] == web_export._sha256(page.html.replace(manifest_back_reference(package), "", 1))
    assert package.html == page_html(package, "/") and package.html_digest == package.pages[0].html_digest
    assert package.package_digest == web_export._sha256(
        web_export._canonical_json(
            {"manifest_digest": package.manifest_digest, "page_html_digests": sorted(p.html_digest for p in package.pages), "asset_digests": []}
        )
    )


def test_the_package_is_deterministic_and_its_digests_follow_the_content(blobs: DesignBlobStore) -> None:
    site, brand = hold_site_images(garner_site_without_clones("pub_digests"), garner_brand(), blobs)
    first = build("pub_digests", site, brand, [], blobs=blobs, default_description=DESCRIPTION)
    second = again("pub_digests", brand, [], blobs, default_description=DESCRIPTION)
    assert second.package_digest == first.package_digest
    assert second.manifest_digest == first.manifest_digest
    assert [(p.route, p.html_digest) for p in second.pages] == [(p.route, p.html_digest) for p in first.pages]
    assert second.manifest == first.manifest
    assert_digests_are_of_what_they_name(first)

    # A new version whose home-page heading changed (words that mint no utility class, so the
    # shared stylesheet is unchanged and only the home page's own bytes move).
    edited = copy.deepcopy(site)
    heading = "Seventy four percent lower spend for SCSD"
    assert edited["pages"]["/"]["content"][0]["type"] == "StatsBand"
    edited["pages"]["/"]["content"][0]["props"]["heading"] = heading
    # Saved the way the editor saves (the governed write: contract checks, one new version).
    write_site_document(
        repository=HybridRepository(),
        blobs=blobs,
        node_bin="node",
        brand_loader=lambda repo, store, document: brand,
        section_loader=lambda repo, store, agent_sections: [],
        document_id="pub_digests",
        site=edited,
        intent="Manual edit",
        checkpoint_label="Manual edit",
        actor_kind="editor",
        source="editor",
        expected_base_version=0,
    )
    changed = again("pub_digests", brand, [], blobs, default_description=DESCRIPTION)
    assert changed.manifest["doc_version"] == 1 and heading in page_html(changed, "/")
    assert changed.package_digest != first.package_digest
    before = {entry["route"]: entry["html_digest"] for entry in first.manifest["pages"]}
    after = {entry["route"]: entry["html_digest"] for entry in changed.manifest["pages"]}
    assert after["/"] != before["/"]
    assert after["/analysis"] == before["/analysis"]
    assert_digests_are_of_what_they_name(changed)


# d. Head and policy on every page ---------------------------------------------------------------

HEAD_GRABBING_JS = """import { jsx, jsxs } from "react/jsx-runtime";
import { z } from "zod";
export const schema = z.object({ id: z.string(), surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]), quote: z.string().min(1) }).strict();
export function render(props, kit) {
  return jsxs(kit.Shell, { surface: props.surface, children: [
    jsx("div", { dangerouslySetInnerHTML: { __html: '<meta http-equiv="refresh" content="0;url=https://collector.example/r"><link rel="stylesheet" href="https://collector.example/s.css"><meta charset="iso-8859-1"><meta name="viewport" content="width=10"><link rel="icon" href="https://collector.example/i.ico">' } }),
    jsx("p", { children: props.quote }),
  ] });
}
"""


def test_every_page_carries_our_head_and_policy_and_none_of_a_sections(blobs: DesignBlobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = cleaner_inputs(monkeypatch)
    module = section_module("HeadGrabber", HEAD_GRABBING_JS)
    site, brand = hold_site_images(garner_site_without_clones("pub_head"), garner_brand(), blobs)
    site = section_on_every_page(site, module, {"id": "grab", "surface": "page", "quote": "Our words stay."})
    package = build("pub_head", site, brand, [module], blobs=blobs, default_description=DESCRIPTION)
    assert [page.route for page in package.pages] == ["/", "/analysis"]
    assert len(seen) == 2 and all('http-equiv="refresh"' in raw and "collector.example/s.css" in raw for raw in seen)
    for page in package.pages:
        html, head = page.html, head_of(page.html)
        for ours in (
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f'<meta http-equiv="Content-Security-Policy" content="{SITE_DELIVERY_CSP_META}">',
            f'<meta name="description" content="{DESCRIPTION}">',
            '<link rel="icon" href="/favicon.ico">',
            '<link rel="lumen-publish-manifest" href="/acme-site/manifest.json">',
        ):
            assert html.count(ours) == 1 and ours in head, (page.route, ours)
        assert html.lower().count("<meta charset") == 1, page.route
        assert html.count('name="viewport"') == 1 and html.count("Content-Security-Policy") == 1, page.route
        assert html.count('rel="icon"') == 1 and html.count('name="description"') == 1, page.route
        for gone in ('http-equiv="refresh"', 'rel="stylesheet"', "iso-8859-1", "width=10", "collector.example"):
            assert gone not in html, (page.route, gone)
        assert "Our words stay." in html


# e. Links -----------------------------------------------------------------------------------------

LINKS_JS = """import { jsx, jsxs } from "react/jsx-runtime";
import { z } from "zod";
export const schema = z.object({ id: z.string(), surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]), quote: z.string().min(1) }).strict();
export function render(props, kit) {
  return jsxs(kit.Shell, { surface: props.surface, children: [
    jsx(kit.Link, { href: "/analysis", children: "Read the analysis" }),
    jsx(kit.Link, { href: "/", children: "Back to the start" }),
    jsx(kit.Link, { href: "mailto:hello@garner.example", children: "Write to us" }),
    jsx(kit.Link, { href: "https://garnerhealth.com/about", children: "About Garner" }),
    jsx(kit.Link, { href: "javascript:steal()", children: "Not a link" }),
    jsx(kit.Button, { label: "See the analysis", href: "/analysis", surface: props.surface }),
    jsx("p", { children: props.quote }),
  ] });
}
"""


def linked_site(document_id: str, module) -> dict:
    site = garner_site_without_clones(document_id)
    site["shell"]["header"]["nav"] = [
        {"label": "The analysis", "href": "/analysis"},
        {"label": "Home", "href": "/"},
        {"label": "Email", "href": "mailto:team@garner.example"},
    ]
    cta = site["pages"]["/analysis"]["content"][-1]
    assert cta["type"] == "CtaBand"
    cta["props"]["buttonHref"] = "/"
    return section_on_every_page(site, module, {"id": "links", "surface": "page", "quote": "Linked."})


def test_internal_links_are_rebased_on_every_page_and_nothing_else_moves(blobs: DesignBlobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = cleaner_inputs(monkeypatch)
    module = section_module("Links", LINKS_JS)
    site, brand = hold_site_images(linked_site("pub_links", module), garner_brand(), blobs)
    package = build("pub_links", site, brand, [module], blobs=blobs)
    # React renders a javascript: href as its own javascript:throw guard; either way the cleaner
    # gets a javascript: link on every page.
    assert len(seen) == 2 and all('href="javascript:' in raw for raw in seen)
    for page in package.pages:
        html = page.html
        hrefs = anchor_hrefs(html)
        internal = [href for href in hrefs if href.startswith("/")]
        assert internal and all(href == "/acme-site" or href.startswith("/acme-site/") for href in internal), (page.route, internal)
        assert 'href="/analysis"' not in html and 'href="/"' not in html, page.route
        assert hrefs.count("/acme-site/analysis") >= 3, (page.route, hrefs)  # nav, kit.Link, kit.Button
        assert hrefs.count("/acme-site") >= 2, (page.route, hrefs)  # nav home, kit.Link home
        for untouched in (
            "https://garnerhealth.com/about",
            "mailto:hello@garner.example",
            "mailto:team@garner.example",
            "https://garnerhealth.com/privacy-policy",
            "https://garnerhealth.com/provider-impact-analysis",
        ):
            assert untouched in hrefs, (page.route, untouched)
        assert "javascript:" not in html.lower(), page.route
    assert "/acme-site" in anchor_hrefs(page_html(package, "/analysis"))  # the CtaBand's button home

    mounted = PublicSiteAddress(origin="http://localhost:8047/p", site_path="/acme-site", asset_origin="http://localhost:8047/p")
    package = again("pub_links", brand, [module], blobs, site_address=mounted)
    assert package.manifest["canonical_url"] == "http://localhost:8047/p/acme-site"
    for page in package.pages:
        internal = [href for href in anchor_hrefs(page.html) if href.startswith("/")]
        assert internal and all(href == "/p/acme-site" or href.startswith("/p/acme-site/") for href in internal), (page.route, internal)
        assert "/p/acme-site/analysis" in internal and "/p/acme-site" in internal
        assert not any(href.startswith("/acme-site") for href in anchor_hrefs(page.html)), page.route

    # A javascript: link written into the shell never gets as far as the render: the site-kit
    # validator refuses it at publish, by where it is.
    site, brand = hold_site_images(linked_site("pub_links_js", module), garner_brand(), blobs)
    site["shell"]["header"]["nav"].append({"label": "Steal", "href": "javascript:steal()"})
    with pytest.raises(SiteDocumentInvalid) as refused:
        build("pub_links_js", site, brand, [module], blobs=blobs)
    assert any(error.startswith("shell.header.nav.3.href:") for error in refused.value.errors), refused.value.errors


# f. noindex ---------------------------------------------------------------------------------------


def test_noindex_marks_every_page_and_the_manifest_and_the_default_marks_none(blobs: DesignBlobStore) -> None:
    site, brand = hold_site_images(garner_site_without_clones("pub_noindex"), garner_brand(), blobs)
    hidden = build("pub_noindex", site, brand, [], blobs=blobs, noindex=True)
    for page in hidden.pages:
        assert page.html.count(web_export.ROBOTS_NOINDEX_META) == 1 and web_export.ROBOTS_NOINDEX_META in head_of(page.html)
    assert hidden.manifest["robots"] == "noindex"
    shown = again("pub_noindex", brand, [], blobs)
    for page in shown.pages:
        assert web_export.ROBOTS_NOINDEX_META not in page.html and 'name="robots"' not in page.html
    assert "robots" not in shown.manifest
    assert shown.package_digest != hidden.package_digest


# g. Titles and the social image -------------------------------------------------------------------


def test_each_page_is_titled_by_its_root_or_the_site_and_shares_one_social_image(blobs: DesignBlobStore) -> None:
    site = garner_site_without_clones("pub_titles")
    site["title"] = "Garner for SCSD"
    site, brand = hold_site_images(site, garner_brand(), blobs)
    home_title = site["pages"]["/"]["root"]["props"]["title"]
    site["pages"]["/analysis"]["root"] = {"props": {}}
    social = _ASSET_REF.search(site["pages"]["/analysis"]["content"][0]["props"]["image"]).group(1)
    package = build("pub_titles", site, brand, [], blobs=blobs, default_social_preview_sha256=social)
    for route, title in (("/", home_title), ("/analysis", "Garner for SCSD")):
        html = page_html(package, route)
        assert html.count("<title>") == 1 and f"<title>{title}</title>" in head_of(html), route
        assert f'<meta property="og:title" content="{title}">' in html, route
        og = f'<meta property="og:image" content="https://acme.pages.test/asset-store/{social}">'
        assert html.count('property="og:image"') == 1 and og in head_of(html), route


# h. Clone pins over real fragment rows ------------------------------------------------------------

CLOSE_CLONE = "frag_9fa31f37a0b94447"
CLONE_CSS = ".garner-close-band-mark{color:#0b1c2d}"


def mint_fragment(design_storage, workspace_id: str, marker: str, status: str | None = None) -> str:
    """A real fragment row in this workspace (born draft), moved to ``status`` the way a human does."""
    _row, artifact = create_web_fragment(
        design_storage,
        workspace_id=workspace_id,
        html=f'<section class="clone-{marker}"><h2>{marker}</h2></section>',
        css=f".clone-{marker}{{padding:4px}}",
        rehosted={},
        source_url="https://garnerhealth.com/",
        section_role="cta",
        label=f"Closing band {marker}",
    )
    for step in {"approved": ["approved"], "deprecated": ["approved", "deprecated"]}.get(status or "", []):
        set_web_fragment_status(workspace_id=workspace_id, fragment_id=artifact.fragment_id, status=step)
    return artifact.fragment_id


def cloned_site(document_id: str, fragment_id: str) -> dict:
    """Garner's own sections plus its closing clone (whose second CTA links to /analysis), pinned
    to ``fragment_id``."""
    site = garner_site_without_clones(document_id)
    close = copy.deepcopy(next(item for item in garner_site(document_id)["pages"]["/"]["content"] if item["props"].get("fragmentId") == CLOSE_CLONE))
    close["props"]["fragmentId"] = fragment_id
    site["pages"]["/"]["content"].append(close)
    return site


def cloned_brand(fragment_id: str | None) -> dict:
    """Garner's brand with the closing clone registered under ``fragment_id``: its own CSS rule and
    a script smuggled into its captured markup."""
    brand = garner_brand()
    template = brand["clones"][CLOSE_CLONE]
    if fragment_id is not None:
        html = template["html"].replace("<section", "<script>steal()</script><section", 1)
        assert "steal()" in html
        brand["clones"][fragment_id] = {**template, "id": fragment_id, "css": CLONE_CSS, "html": html}
    return brand


def test_clone_pins_resolve_against_real_fragment_rows(
    blobs: DesignBlobStore, design_storage, workspace_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = cleaner_inputs(monkeypatch)
    approved = mint_fragment(design_storage, workspace_id, "approved", "approved")
    assert HybridRepository().find_web_fragment(approved)["status"] == "approved"
    site, brand = hold_site_images(cloned_site("pub_clone_ok", approved), cloned_brand(approved), blobs)
    package = build("pub_clone_ok", site, brand, [], blobs=blobs)
    assert "<script>steal()</script>" in seen[0]  # the smuggled script reached the cleaner
    home = page_html(package, "/")
    assert f'data-fragment-id="{approved}"' in home
    assert CLONE_CSS in home
    assert "steal()" not in home and "<script" not in home.lower()
    fragment = home[home.index(f'data-fragment-id="{approved}"') :]
    assert 'href="/acme-site/analysis"' in fragment  # the clone's href slot, rebased
    assert package.manifest["fragments"]["ids"] == [approved]

    retired = mint_fragment(design_storage, workspace_id, "retired", "deprecated")
    assert HybridRepository().find_web_fragment(retired)["status"] == "deprecated"
    site, brand = hold_site_images(cloned_site("pub_clone_retired", retired), cloned_brand(retired), blobs)
    assert build("pub_clone_retired", site, brand, [], blobs=blobs).manifest["fragments"]["ids"] == [retired]

    draft = mint_fragment(design_storage, workspace_id, "draft")
    assert HybridRepository().find_web_fragment(draft)["status"] == "draft"
    site, brand = hold_site_images(cloned_site("pub_clone_draft", draft), cloned_brand(draft), blobs)
    with pytest.raises(SitePublishRefused) as refused:
        build("pub_clone_draft", site, brand, [], blobs=blobs)
    assert refused.value.code == "site_publish.clone_not_approved"
    assert brand["clones"][draft]["label"] in refused.value.message

    nobody = "frag_" + uuid.uuid4().hex[:16]
    assert HybridRepository().find_web_fragment(nobody) is None
    site, brand = hold_site_images(cloned_site("pub_clone_norow", nobody), cloned_brand(nobody), blobs)
    with pytest.raises(SitePublishRefused) as refused:
        build("pub_clone_norow", site, brand, [], blobs=blobs)
    assert refused.value.code == "site_publish.clone_unresolved"

    unlisted = mint_fragment(design_storage, workspace_id, "unlisted", "approved")
    site, brand = hold_site_images(cloned_site("pub_clone_unlisted", unlisted), cloned_brand(None), blobs)
    assert unlisted not in brand["clones"]
    with pytest.raises(SitePublishRefused) as refused:
        build("pub_clone_unlisted", site, brand, [], blobs=blobs)
    assert refused.value.code == "site_publish.clone_unresolved"


# i. Agent-section CSS -----------------------------------------------------------------------------


def test_an_agent_sections_css_keeps_its_rules_and_loses_its_foreign_urls(blobs: DesignBlobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = cleaner_inputs(monkeypatch)
    css = ".quote-band-mark{color:#1a2b3c}\n.quote-band-bg{background:url(https://collector.example/x.png)}"
    module = section_module("QuoteBand", QUOTE_JS, QUOTE_SCHEMA, css=css)
    site, brand = hold_site_images(garner_site_without_clones("pub_css"), garner_brand(), blobs)
    site = section_on_every_page(site, module, {"id": "quote", "surface": "page", "quote": "Fewer surprises."})
    package = build("pub_css", site, brand, [module], blobs=blobs)
    assert seen and all("url(https://collector.example/x.png)" in raw for raw in seen)
    for page in package.pages:
        assert ".quote-band-mark{color:#1a2b3c}" in page.html, page.route
        assert ".quote-band-bg{background:none}" in page.html, page.route
        assert "collector.example" not in page.html, page.route


# j. A section that changes the URL in place -------------------------------------------------------

PUSH_STATE_JS = """import { jsx } from "react/jsx-runtime";
import { z } from "zod";
export const schema = z.object({ id: z.string(), surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]), quote: z.string().min(1) }).strict();
export function render(props, kit) {
  history.pushState({}, "", "/pricing");
  return jsx(kit.Shell, { surface: props.surface, children: jsx("p", { children: props.quote }) });
}
"""


def test_a_section_that_changes_the_url_in_place_publishes_with_one_warning(blobs: DesignBlobStore) -> None:
    """Founder ruling 2026-10-13: the change is a warning, not a failed publish. The section renders
    on both pages, so it asks twice; the package names the change once."""
    module = section_module("PushState", PUSH_STATE_JS)
    site, brand = hold_site_images(garner_site_without_clones("pub_push_state"), garner_brand(), blobs)
    site = section_on_every_page(site, module, {"id": "push", "surface": "page", "quote": "Still published."})
    package = build("pub_push_state", site, brand, [module], blobs=blobs)
    assert [page.route for page in package.pages] == ["/", "/analysis"]
    for page in package.pages:
        assert "<script" not in page.html.lower(), page.route
        assert "Still published." in page.html, page.route
    line = "a section changed the page URL in place (pushState /pricing); this has no effect on the published page, which runs no script"
    assert package.warnings.count(line) == 1, package.warnings
    assert package.manifest["warnings"] == package.warnings


# k. The publish core accepts it -------------------------------------------------------------------


def test_the_publish_core_persists_a_site_package(blobs: DesignBlobStore) -> None:
    site, brand = hold_site_images(garner_site_without_clones("pub_core"), garner_brand(), blobs)
    package = build("pub_core", site, brand, [], blobs=blobs)
    web_export.persist_publish_assets(blobs, package.assets, package.manifest["custom_components"].get("assets"))
    assert package.manifest["custom_components"] == {} and package.assets == {}


def _publish_through_the_core(blobs: DesignBlobStore, document_id: str) -> None:
    """Garner's site with the Quote agent section, published at ``acme-site`` through the one
    publish write sequence (``publish_site_document``), as the publish tool runs it."""
    site, brand = hold_site_images(garner_site_without_clones(document_id), garner_brand(), blobs)
    module = section_module("Quote", QUOTE_JS)
    site["agent_sections"] = {"Quote": module.digest}
    site["pages"]["/"]["content"].append({"type": "Quote", "props": {"id": "q", "surface": "page", "quote": "Live and well."}})
    store_site(site)
    repository = HybridRepository()
    publish_site_document(
        repository=repository,
        blobs=blobs,
        node_bin="node",
        brand_loader=lambda repo, store, document: brand,
        section_loader=lambda repo, store, pins: [m for m in [module] if pins.get(m.name) == m.digest],
        document=repository.require_document(document_id),
        slug="acme-site",
    )


def _stored_manifest(blobs: DesignBlobStore) -> dict:
    return published_manifest(blobs.workspace_id, "acme-site")


def test_the_publish_core_persists_a_live_sites_javascript_by_digest(blobs: DesignBlobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUMEN_SITE_LIVE_WORKSPACES", blobs.workspace_id)
    _publish_through_the_core(blobs, "pub_core_live")
    manifest = _stored_manifest(blobs)
    assert manifest["delivery"] == "site_live"
    assert len(manifest["live"]["assets"]) == 5  # the runtime, three shims and the Quote section
    for record in manifest["live"]["assets"]:
        media_type, data = blobs.read_blob(record["digest"])
        assert media_type == "text/javascript; charset=utf-8"
        assert hashlib.sha256(data).hexdigest() == record["digest"]


def test_a_workspace_off_the_list_publishes_the_static_page_exactly_as_before(blobs: DesignBlobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUMEN_SITE_LIVE_WORKSPACES", "")
    _publish_through_the_core(blobs, "pub_core_static")
    manifest = _stored_manifest(blobs)
    assert manifest["delivery"] == "site" and "live" not in manifest


def test_a_star_puts_every_workspace_on_the_live_list(blobs: DesignBlobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """Founder 2026-10-15: every workspace publishes live by default; production sets `*`."""
    from lumen_api.site_live import live_sites_enabled

    for listed, expected in (("*", True), ("ws_other, *", True), (" * ", True), ("ws_other", False), ("", False)):
        monkeypatch.setenv("LUMEN_SITE_LIVE_WORKSPACES", listed)
        assert live_sites_enabled(blobs.workspace_id) is expected, listed
    monkeypatch.setenv("LUMEN_SITE_LIVE_WORKSPACES", "*")
    _publish_through_the_core(blobs, "pub_core_star")
    assert _stored_manifest(blobs)["delivery"] == "site_live"


# --- Live sites (publishing live sites, phase 1) ---------------------------------------------------


def _build(blobs: DesignBlobStore, *, live: bool = False, with_agent_section: bool = True):
    """Garner's site (our own sections, plus the Quote agent section unless told otherwise) through
    ``build`` on first use, then ``again`` over the stored document, so two calls build the same
    version."""
    document_id = "pub_live_quote" if with_agent_section else "pub_live_plain"
    site, brand = hold_site_images(garner_site_without_clones(document_id), garner_brand(), blobs)
    sections = []
    if with_agent_section:
        module = section_module("Quote", QUOTE_JS)
        site["agent_sections"] = {"Quote": module.digest}
        site["pages"]["/"]["content"].append({"type": "Quote", "props": {"id": "q", "surface": "page", "quote": "Live and well."}})
        sections = [module]
    try:
        HybridRepository().require_document(document_id)
    except NotFoundError:
        return build(document_id, site, brand, sections, blobs=blobs, live=live)
    return again(document_id, brand, sections, blobs, live=live)


def test_a_live_package_ships_its_runtime_shims_and_sections_and_is_served_under_its_own_policy(blobs: DesignBlobStore) -> None:
    package = _build(blobs, live=True)
    manifest = package.manifest
    assert manifest["delivery"] == "site_live"
    live = manifest["live"]
    runtime = live_runtime()
    assert live["runtime"] == hashlib.sha256(runtime.runtime_js).hexdigest()
    assert set(package.assets) == {r["digest"] for r in live["assets"]}
    assert all(r["extension"] == "js" and r["media_type"] == "text/javascript; charset=utf-8" for r in live["assets"])
    home = next(page for page in package.pages if page.route == "/")
    import_map = re.search(r'<script type="importmap">(.*?)</script>', home.html).group(1)
    assert live["script_hashes"] == [script_hash(import_map)]
    assert f'<meta http-equiv="Content-Security-Policy" content="{web_export._escape_attr(site_live_csp(live["script_hashes"], meta=True))}">' in home.html
    assert f'<script type="module" src="/p-assets/{live["runtime"]}.js"></script>' in home.html
    data = json.loads(re.search(r'<script type="application/json" id="clue-page-data">(.*?)</script>', home.html).group(1))
    assert data["route"] == "/" and data["basePath"] == ADDRESS.link_path


def test_review_focus_2_page_data_cannot_end_its_element_early(blobs: DesignBlobStore) -> None:
    page = live_page_html(
        "<!doctype html><html><head></head><body><div id=\"clue-site\"></div></body></html>",
        {"title": "</script><script>alert(1)</script>"},
        section_urls={}, import_map="{}", runtime_url="/p-assets/x.js",
    )
    assert "</script><script>alert(1)" not in page
    assert "\\u003c/script>" in page


def test_review_focus_3_a_live_site_without_agent_sections_still_ships_the_host_shims(blobs: DesignBlobStore) -> None:
    package = _build(blobs, live=True, with_agent_section=False)
    assert len(package.manifest["live"]["assets"]) == 4  # the runtime and three shims


def test_markup_a_published_page_cannot_carry_refuses_the_live_publish(blobs: DesignBlobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(site_publish, "site_html_problems", lambda html: ("stripped <iframe> and its content",))
    with pytest.raises(SitePublishRefused) as refused:
        _build(blobs, live=True)
    assert refused.value.code == "site_publish.unsafe_markup"


def test_a_live_package_is_deterministic(blobs: DesignBlobStore) -> None:
    assert _build(blobs, live=True).package_digest == _build(blobs, live=True).package_digest


def test_without_live_the_package_is_byte_identical(blobs: DesignBlobStore) -> None:
    assert _build(blobs).package_digest == _build(blobs, live=False).package_digest


def test_a_live_pages_policy_comes_before_its_import_map_and_is_its_only_policy(blobs: DesignBlobStore) -> None:
    """A meta policy governs only what the parser meets after it: on a copy served without the page
    origin's header, the import map must already be under it."""
    package = _build(blobs, live=True)
    assert [page.route for page in package.pages] == ["/", "/analysis"]
    for page in package.pages:
        assert page.html.count('<meta http-equiv="Content-Security-Policy"') == 1, page.route
        policy = page.html.index('<meta http-equiv="Content-Security-Policy"')
        assert policy < page.html.index('<script type="importmap">'), page.route
        assert policy < page.html.lower().index("<script"), page.route
    assert_digests_are_of_what_they_name_live(package)


def assert_digests_are_of_what_they_name_live(package) -> None:
    """The manifest's page digest is still the page before its back-reference went in."""
    recorded = {entry["route"]: entry["html_digest"] for entry in package.manifest["pages"]}
    policy = web_export._escape_attr(site_live_csp(package.manifest["live"]["script_hashes"], meta=True))
    back_reference = (
        f'<meta http-equiv="Content-Security-Policy" content="{policy}">\n'
        f'<meta name="lumen-publish-manifest-digest" content="{package.manifest_digest}">\n'
        '<link rel="lumen-publish-manifest" href="/acme-site/manifest.json">\n'
    )
    for page in package.pages:
        assert page.html_digest == web_export._sha256(page.html)
        assert recorded[page.route] == web_export._sha256(page.html.replace(back_reference, "", 1))


# Site element inspector, plan 2: the font library's families the site's manual styling uses ship as
# WOFF2 from this workspace's store; no other library family rides along.
def test_a_library_family_the_styling_uses_ships_as_woff2_and_no_other_does(blobs: DesignBlobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    lora, unused = "1" * 64, "2" * 64
    brand = garner_brand()
    brand["libraryFonts"] = [
        {"family": "Lora", "category": "serif", "faces": [{"weight": 400, "style": "normal", "file": f"/asset-store/{lora}", "asset_id": "asset_font_lib_lora_w400"}]},
        {"family": "Unused Sans", "category": "sans", "faces": [{"weight": 400, "style": "normal", "file": f"/asset-store/{unused}", "asset_id": "asset_font_lib_unused"}]},
    ]
    asked: list[str] = []
    monkeypatch.setattr(site_publish, "_library_face_bytes", lambda face, _storage: asked.append(face["asset_id"]) or INTER_TTF.read_bytes())
    site = garner_site_without_clones("pub_library")
    proof = next(item for item in site["pages"]["/"]["content"] if item["props"]["id"] == "proof")
    proof["props"]["_edits"] = {"heading": {"fontFamily": "Lora"}}
    site, brand = hold_site_images(site, brand, blobs)
    package = build("pub_library", site, brand, [], blobs=blobs)

    assert asked == ["asset_font_lib_lora_w400"], "only the family the styling uses is read"
    lora_faces = [src for family, src in font_faces(page_html(package, "/")) if family == "Lora"]
    assert len(lora_faces) == 1, font_faces(page_html(package, "/"))
    digest = _ASSET_REF.fullmatch(lora_faces[0]).group(1)
    assert digest != lora, "the face is the WOFF2 re-encode, held by this workspace"
    assert blobs.custody_states([digest])[digest] is CustodyState.READABLE
    assert blobs.read_blob(digest)[1][:4] == b"wOF2"
    assert 'font-family:"Lora", serif !important' in page_html(package, "/")
    assert not any(family == "Unused Sans" for family, _src in font_faces(page_html(package, "/")))
    assert "Lora" in package.manifest["font_families_included"], "the licence record names the library family it shipped"
    assert "Unused Sans" not in package.manifest["font_families_included"]


def test_styling_that_names_a_brand_font_held_back_by_its_licence_still_publishes(blobs: DesignBlobStore) -> None:
    """The contract is checked against the fonts as offered; the held-back face is simply not shipped
    (found while building plan 2: the gated brand used to refuse the whole publish)."""
    seed_font_face(blobs, "asset_site_font_locked", b"wOF2" + b"\x33" * 96, "font/woff2")
    brand = garner_brand()
    fonts = brand["kit"]["assets"]["fonts"]
    stix = fonts["brand"]["family"]
    fonts["brand"] = {
        **fonts["brand"],
        "license": {"name": "Commercial", "embeddable": False, "subsettable": False, "source_url": None, "restrictions": []},
        "faces": [{"weight": 400, "style": "normal", "asset_id": "asset_site_font_locked", "source_url": None}],
    }
    site = garner_site_without_clones("pub_locked_style")
    proof = next(item for item in site["pages"]["/"]["content"] if item["props"]["id"] == "proof")
    proof["props"]["_edits"] = {"heading": {"fontFamily": stix}}
    site, brand = hold_site_images(site, brand, blobs)
    package = build("pub_locked_style", site, brand, [], blobs=blobs)
    assert f'font-family:"{stix}"' in page_html(package, "/")
    assert not any(family == stix for family, _src in font_faces(page_html(package, "/")))
