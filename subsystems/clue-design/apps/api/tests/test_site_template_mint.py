"""Site element inspector, plan 6 (rulings R4, R13): a kit's header and footer templates minted from its
captured nav and footer through the fragment door, released at once (founder: no approval gate)."""

from __future__ import annotations

from pathlib import Path

from clue_storage import FsStorage

from lumen_api.agent_cloned_sections import DurableAgentClonedSectionRegistry
from lumen_api.design_store import DesignBlobStore, HybridRepository
from lumen_api.fragments import create_web_fragment, set_web_fragment_degraded
from lumen_api.fragments.cssscope import PRELUDE_REFERENCE_STRIP
from lumen_api.fragments.site_templates import MENU_ATTR, SITE_HEADER_ROLE
from lumen_api.site_workspace_view import list_site_clones

FIXTURES = Path(__file__).parent / "fixtures" / "site_templates"
KIT = "brand_kit_site_tmpl_1"
FOOTER = (
    '<footer class="footer"><div class="row"><a class="logo" href="/"><svg viewBox="0 0 4 4"><path d="M0 0h4"></path></svg></a>'
    '<ul class="cols"><li><a href="/careers">Careers</a></li></ul></div><div class="bottom"><p>© 2026 Seller Inc.</p>'
    '<a href="/privacy">Privacy</a><a href="/terms">Terms</a></div></footer>'
)


def _kit(workspace_id: str) -> dict:
    return HybridRepository(workspace_id=workspace_id).create_brand_kit(
        {"id": KIT, "version": 2, "name": "Seller", "approval_status": "approved"}, {}, [], "website"
    )


def _registry(workspace_id: str, storage: FsStorage, tmp_path) -> DurableAgentClonedSectionRegistry:
    return DurableAgentClonedSectionRegistry(blobs=DesignBlobStore(storage, workspace_id), cache_dir=tmp_path / "cache")


def _band(workspace_id: str, storage: FsStorage, *, role: str, html: str, page: str, index: int = 0) -> str:
    row, artifact = create_web_fragment(
        storage, workspace_id=workspace_id, html=html, css=".nav_link{color:#123456}", rehosted={},
        source_url=f"https://seller.example{page}", section_role=role, label=f"{role} {page}",
        source_kit_id=KIT, source_kit_version=2, preview=None,
        provenance={"page_url": f"https://seller.example{page}", "section_index": index}, prelude_reference=PRELUDE_REFERENCE_STRIP,
    )
    return artifact.fragment_id


def _header(word: str = "Employers") -> str:
    return (FIXTURES / "webflow_header.html").read_text().replace("Employers", word)


def test_mint_site_template_releases_an_approved_clone(workspace_id: str, design_storage: FsStorage, tmp_path) -> None:
    _kit(workspace_id)
    source = _band(workspace_id, design_storage, role="nav", html=_header(), page="/")
    registry = _registry(workspace_id, design_storage, tmp_path)
    minted = registry.mint_site_template(role=SITE_HEADER_ROLE, source_fragment_id=source, layout="with_menu")
    assert minted["status"] == "approved" and minted["role"] == SITE_HEADER_ROLE and minted["layout"] == "with_menu"
    assert {"account_line", "account_logo", "account_shown", "cta_href"} <= set(minted["slot_keys"])
    row = HybridRepository(workspace_id=workspace_id).require_web_fragment(minted["fragment_id"])
    assert row["section_role"] == SITE_HEADER_ROLE and row["status"] == "approved"
    assert row["derived_from"] == source and row["source_kit_id"] == KIT
    assert minted["label"] == "Header template, with page menu — seller.example"
    [clone] = [c for c in list_site_clones(registry.blobs, tmp_path / "cache") if c["id"] == minted["fragment_id"]]
    assert clone["role"] == SITE_HEADER_ROLE
    assert f"{MENU_ATTR}=" in clone["html"] and "data-clue-menu-item" in clone["html"] and "data-clue-menu-label" in clone["html"]
    wrapper = "lumen-frag-" + minted["fragment_id"].removeprefix("frag_")
    assert f".{wrapper} .clue-account-logo" in clone["css"], "the account rules are scoped to the template"
    assert f".{wrapper} .nav_link" in clone["css"], "the captured rules move to the template's wrapper"


def test_mint_site_templates_prefers_the_home_page_and_skips_degraded(workspace_id: str, design_storage: FsStorage, tmp_path) -> None:
    _kit(workspace_id)
    home = _band(workspace_id, design_storage, role="nav", html=_header("Home"), page="/")
    about = _band(workspace_id, design_storage, role="nav", html=_header("About"), page="/about")
    _band(workspace_id, design_storage, role="nav", html=_header("Pricing"), page="/pricing")
    _band(workspace_id, design_storage, role="footer", html=FOOTER, page="/careers")
    set_web_fragment_degraded(workspace_id=workspace_id, fragment_id=home, degraded=True, reason="blank_render")
    results = {(result["role"], result.get("layout")): result for result in _registry(workspace_id, design_storage, tmp_path).mint_site_templates(kit_id=KIT, kit_version=2)}
    header = HybridRepository(workspace_id=workspace_id).require_web_fragment(results[("site_header", "one_page")]["fragment_id"])
    assert header["derived_from"] == about, "the degraded home page is skipped; the shortest path wins"
    assert results[("site_footer", None)]["status"] == "approved"


def test_mint_site_templates_reports_not_derivable(workspace_id: str, design_storage: FsStorage, tmp_path) -> None:
    _kit(workspace_id)
    _band(workspace_id, design_storage, role="nav", html='<header><nav><a href="/a">A</a><a href="/b">B</a></nav></header>', page="/")
    results = {(result["role"], result.get("layout")): result for result in _registry(workspace_id, design_storage, tmp_path).mint_site_templates(kit_id=KIT, kit_version=2)}
    assert results[("site_header", "one_page")] == {"role": "site_header", "layout": "one_page", "skipped": "no logo"}
    assert results[("site_header", "with_menu")] == {"role": "site_header", "layout": "with_menu", "skipped": "no logo"}
    assert results[("site_footer", None)] == {"role": "site_footer", "skipped": "no captured footer"}


def test_the_capture_mints_templates_and_reports_what_it_could_not(workspace_id: str, design_storage: FsStorage, tmp_path) -> None:
    from lumen_ingestion.pipeline import SITE_TEMPLATE_CODE, mint_site_templates_after_capture

    _kit(workspace_id)
    _band(workspace_id, design_storage, role="nav", html=_header(), page="/")
    diagnostics = mint_site_templates_after_capture(DesignBlobStore(design_storage, workspace_id), kit_id=KIT, kit_version=2)
    assert diagnostics == [{"code": SITE_TEMPLATE_CODE, "severity": "warning", "message": "site footer template not made: no captured footer"}]
    roles = {row["section_role"] for row in HybridRepository(workspace_id=workspace_id).list_web_fragments()}
    assert SITE_HEADER_ROLE in roles


def _logo_record(asset_id: str, digest: str) -> dict:
    return {
        "id": asset_id, "label": "Seller logo", "kind": "vector", "status": "ready", "tags": [],
        "media": {"mime_type": "image/svg+xml", "byte_length": 10,
                  "digest": {"algorithm": "sha256", "value": digest},
                  "location": {"provider": "local-store", "opaque_ref": f"sha256/{digest[:2]}/{digest}", "url": None}},
    }


def test_a_header_whose_logo_is_drawn_in_code_takes_the_kits_primary_logo(workspace_id: str, design_storage: FsStorage, tmp_path) -> None:
    """Final review I3 (founder, option a): the kit's primary logo (else its wordmark) stands in for an
    inline-SVG logo so the template's seller logo can be replaced."""
    repo = HybridRepository(workspace_id=workspace_id)
    primary, mark = "a" * 64, "b" * 64
    repo.create_asset_record(_logo_record("asset_seller_primary", primary))
    repo.create_asset_record(_logo_record("asset_seller_mark", mark))
    repo.create_brand_kit(
        {"id": KIT, "version": 2, "name": "Seller", "approval_status": "approved",
         "assets": {"logos": {"mark": {"usage": "mark", "variants": [{"name": "full_color", "asset_id": "asset_seller_mark"}]},
                              "primary": {"usage": "primary", "variants": [{"name": "one_color", "asset_id": "asset_seller_primary"}]}}}},
        {}, [], "website",
    )
    source = _band(workspace_id, design_storage, role="footer", html=FOOTER, page="/")
    minted = _registry(workspace_id, design_storage, tmp_path).mint_site_template(role="site_footer", source_fragment_id=source)
    row = HybridRepository(workspace_id=workspace_id).require_web_fragment(minted["fragment_id"])
    [clone] = [c for c in list_site_clones(_registry(workspace_id, design_storage, tmp_path).blobs, tmp_path / "cache")
               if c["id"] == row["fragment_id"]]
    assert f"/asset-store/{primary}" in clone["html"] and "<svg" not in clone["html"]
    assert f"/asset-store/{mark}" not in clone["html"]


def test_a_template_leaves_its_source_band_offered(workspace_id: str, design_storage: FsStorage, tmp_path) -> None:
    """Live check, plan 6: a template is made FROM a band, it does not repair it. The seller's own nav
    and footer stay in the catalog (founder answer 2026-10-12: every role is offered)."""
    _kit(workspace_id)
    source = _band(workspace_id, design_storage, role="nav", html=_header(), page="/")
    registry = _registry(workspace_id, design_storage, tmp_path)
    minted = registry.mint_site_template(role=SITE_HEADER_ROLE, source_fragment_id=source)
    rows = {row["fragment_id"]: row for row in registry.list_sections()["sections"]}
    assert rows[source]["superseded_by"] is None
    offered = {clone["id"] for clone in list_site_clones(registry.blobs, tmp_path / "cache")}
    assert {source, minted["fragment_id"]} <= offered


def test_a_template_made_again_replaces_the_one_before(workspace_id: str, design_storage: FsStorage, tmp_path) -> None:
    """Live check, plan 6: deriving a kit's header again (after a derivation fix, or from a newer
    capture) leaves one header template on offer, not two."""
    _kit(workspace_id)
    home = _band(workspace_id, design_storage, role="nav", html=_header("Home"), page="/")
    registry = _registry(workspace_id, design_storage, tmp_path)
    # The bands differ in a menu word, so the menu layout derives two different templates.
    first = registry.mint_site_template(role=SITE_HEADER_ROLE, source_fragment_id=home, layout="with_menu")
    about = _band(workspace_id, design_storage, role="nav", html=_header("About"), page="/about")
    second = registry.mint_site_template(role=SITE_HEADER_ROLE, source_fragment_id=about, layout="with_menu")
    assert second["fragment_id"] != first["fragment_id"]
    rows = {row["fragment_id"]: row for row in registry.list_sections()["sections"]}
    assert rows[first["fragment_id"]]["superseded_by"] == second["fragment_id"]
    headers = [c["id"] for c in list_site_clones(registry.blobs, tmp_path / "cache") if c["role"] == SITE_HEADER_ROLE]
    assert headers == [second["fragment_id"]]
    assert {home, about} <= {c["id"] for c in list_site_clones(registry.blobs, tmp_path / "cache")}, "both bands stay offered"


def test_a_template_made_again_unchanged_settles_on_the_same_template(workspace_id: str, design_storage: FsStorage, tmp_path) -> None:
    """Live check, plan 6: re-running the derivation over an unchanged band is a no-op (it once
    refused with "cannot be derived from itself")."""
    _kit(workspace_id)
    source = _band(workspace_id, design_storage, role="footer", html=FOOTER, page="/")
    registry = _registry(workspace_id, design_storage, tmp_path)
    first = registry.mint_site_template(role="site_footer", source_fragment_id=source)
    again = registry.mint_site_template(role="site_footer", source_fragment_id=source)
    assert again["fragment_id"] == first["fragment_id"] and again["status"] == "approved" and again["converged"]
    assert [result.get("skipped") for result in registry.mint_site_templates(kit_id=KIT, kit_version=2)
            if result["role"] == "site_footer"] == [None]


def test_a_kit_offers_both_header_templates_the_agent_chooses_between(workspace_id: str, design_storage: FsStorage, tmp_path) -> None:
    """Founder 2026-10-19: a one-page header ("Prepared for …" in the centre) and a header with the
    page menu, side by side in the catalog; making one again never replaces the other."""
    _kit(workspace_id)
    _band(workspace_id, design_storage, role="nav", html=_header(), page="/")
    registry = _registry(workspace_id, design_storage, tmp_path)
    results = [r for r in registry.mint_site_templates(kit_id=KIT, kit_version=2) if r["role"] == SITE_HEADER_ROLE]
    assert sorted(r["layout"] for r in results) == ["one_page", "with_menu"] and all(r["status"] == "approved" for r in results)
    by_layout = {r["layout"]: r for r in results}
    assert by_layout["one_page"]["label"] == "Header template, one page — seller.example"
    assert by_layout["with_menu"]["label"] == "Header template, with page menu — seller.example"
    clones = {c["id"]: c for c in list_site_clones(registry.blobs, tmp_path / "cache") if c["role"] == SITE_HEADER_ROLE}
    assert set(clones) == {by_layout["one_page"]["fragment_id"], by_layout["with_menu"]["fragment_id"]}
    assert MENU_ATTR not in clones[by_layout["one_page"]["fragment_id"]]["html"]
    assert MENU_ATTR in clones[by_layout["with_menu"]["fragment_id"]]["html"]
    again = [r for r in registry.mint_site_templates(kit_id=KIT, kit_version=2) if r["role"] == SITE_HEADER_ROLE]
    assert {r["fragment_id"] for r in again} == set(clones), "made again unchanged: the same two"
