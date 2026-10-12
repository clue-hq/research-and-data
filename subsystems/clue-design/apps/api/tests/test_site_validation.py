"""Contract checks on a site before it is stored (Wave 2 Lane A, Task 11)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from clue_design.storage import SOURCE_KEY_ASSET
from lumen_api.design_store import DesignBlobStore
from lumen_api.site_doc_inputs import (
    SiteInputsUnavailable,
    brand_loader_not_composed,
    load_section_modules,
    sections_not_stored,
)
from lumen_api.site_doc_validate import (
    SiteValidatorUnavailable,
    check_site_document,
    custody_errors,
    prepare_site_for_write,
    run_site_validator,
    shape_errors,
    site_asset_digests,
)
from lumen_api.site_render import SECTION_MODULE_MISSING, SectionModule, SiteRenderError
from site_kit_support import ensure_site_kit_dist, garner_brand, garner_site, hold_site_images, png

QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "surface": {"type": "string", "enum": ["page", "card", "muted", "brandSubtle", "brand", "inverse"]},
        "quote": {"type": "string", "minLength": 1},
    },
    "required": ["id", "surface", "quote"],
    "additionalProperties": False,
}


def quote_module(module_js: str = "export const schema = null;\n") -> SectionModule:
    # The bytes are only hashed here; nothing in this suite runs them.
    return SectionModule(
        name="QuoteBand", digest=hashlib.sha256(module_js.encode()).hexdigest(),
        module_js=module_js, css="", props_schema=QUOTE_SCHEMA,
    )


@pytest.fixture()
def blobs(design_storage, workspace_id: str) -> DesignBlobStore:
    return DesignBlobStore(design_storage, workspace_id)


def test_shape_errors_name_each_problem() -> None:
    site = garner_site("doc_a")
    assert shape_errors(site, document_id="doc_a") == []
    assert shape_errors({**site, "id": "doc_b"}, document_id="doc_a") == ["site.id: must be this document's id 'doc_a'"]
    assert shape_errors({**site, "extra": 1}, document_id="doc_a") == [
        "site.extra: not a site field (the fields are id, title, theme, pages, shell, agent_sections)"
    ]
    bad_route = {**site, "pages": {**site["pages"], "/Pricing": {"root": {"props": {}}, "content": []}}}
    assert shape_errors(bad_route, document_id="doc_a") == [
        "site.pages['/Pricing']: a route is / or /<name> (lowercase letters, digits, dashes)"
    ]
    assert shape_errors({**site, "agent_sections": {"QuoteBand": "nope"}}, document_id="doc_a") == [
        "site.agent_sections: must map a section name to the sha256 of its compiled module"
    ]
    no_home = {**site, "pages": {"/analysis": site["pages"]["/analysis"]}}
    assert shape_errors(no_home, document_id="doc_a") == ['site.pages: must be an object of route -> page that includes "/"']


def test_a_manual_save_keeps_the_stored_theme_and_cannot_add_an_agent_section() -> None:
    stored = {"id": "doc_a", "scene": {**garner_site("doc_a"), "theme": {"brand_kit": {"id": "kit_1", "version": 2}}}}
    incoming = {**garner_site("doc_a"), "theme": {"brand_kit": {"id": "kit_other", "version": 9}}, "agent_sections": {"QuoteBand": "a" * 64}}
    prepared, errors = prepare_site_for_write(stored, incoming, allow_new_sections=False)
    assert prepared["theme"] == {"brand_kit": {"id": "kit_1", "version": 2}}
    assert errors == ["agent_sections.QuoteBand: a manual save cannot add or change an agent section"]
    _, agent_errors = prepare_site_for_write(stored, incoming, allow_new_sections=True)
    assert agent_errors == []


def test_custody_refuses_a_digest_this_workspace_does_not_hold(blobs: DesignBlobStore) -> None:
    data = png((1, 2, 3))
    blobs.register(data, media_type="image/png", source_key=SOURCE_KEY_ASSET)
    held, foreign = hashlib.sha256(data).hexdigest(), "f" * 64
    site = garner_site("doc_a")
    site["pages"]["/analysis"]["content"][0]["props"]["image"] = f"/asset-store/{held}"
    site["pages"]["/analysis"]["content"][2]["props"]["image"] = f"/asset-store/{foreign}"
    assert site_asset_digests(site) == [held, foreign]
    errors, urls = custody_errors(site, blobs)
    assert errors == [
        f"image /asset-store/{foreign} is not stored in this workspace; use one of the brand's assets or an image generated for this site"
    ]
    assert urls == [f"/asset-store/{held}"]


def test_the_site_kit_validator_runs_over_json() -> None:
    ensure_site_kit_dist()
    assert run_site_validator(garner_site("doc_a"), garner_brand(), section_schemas={}, site_images=[]) == []
    broken = garner_site("doc_a")
    broken["pages"]["/analysis"]["content"][0]["props"]["surface"] = "green"
    errors = run_site_validator(broken, garner_brand(), section_schemas={}, site_images=[])
    assert any(error.startswith("pages/analysis.content.0(what).surface") for error in errors), errors


def test_a_missing_validator_is_a_typed_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUMEN_SITE_KIT_DIST", str(tmp_path))
    with pytest.raises(SiteValidatorUnavailable):
        run_site_validator(garner_site("doc_a"), garner_brand(), section_schemas={}, site_images=[])


def test_check_site_document_checks_an_agent_section_against_its_stored_schema(blobs: DesignBlobStore) -> None:
    ensure_site_kit_dist()
    module = quote_module()
    site, brand = hold_site_images(garner_site("doc_a"), garner_brand(), blobs)
    site["agent_sections"] = {"QuoteBand": module.digest}
    site["pages"]["/"]["content"].append({"type": "QuoteBand", "props": {"id": "quote", "surface": "page", "quote": "Fewer surprises."}})
    assert check_site_document(site, document_id="doc_a", brand=brand, sections=[module], blobs=blobs) == []
    site["pages"]["/"]["content"][-1]["props"]["surface"] = "green"
    errors = check_site_document(site, document_id="doc_a", brand=brand, sections=[module], blobs=blobs)
    assert any(error.startswith("page.content.5(quote).surface") for error in errors), errors


def test_the_section_loader_is_checked_against_the_sites_own_pins() -> None:
    module = quote_module()
    site = {**garner_site("doc_a"), "agent_sections": {"QuoteBand": module.digest}}
    assert load_section_modules(lambda repo, blobs, pins: [module], None, None, site) == [module]
    with pytest.raises(SiteRenderError) as missing:
        load_section_modules(lambda repo, blobs, pins: [], None, None, site)
    assert missing.value.code == SECTION_MODULE_MISSING
    stale = SectionModule(name="QuoteBand", digest=module.digest, module_js=module.module_js + "// changed\n", css="", props_schema=QUOTE_SCHEMA)
    with pytest.raises(SiteRenderError) as tampered:
        load_section_modules(lambda repo, blobs, pins: [stale], None, None, site)
    assert tampered.value.code == SECTION_MODULE_MISSING and "stale" in tampered.value.message


def test_the_default_seams_refuse_until_lane_b_composes_them() -> None:
    assert sections_not_stored(None, None, {}) == []
    with pytest.raises(SiteRenderError) as refused:
        sections_not_stored(None, None, {"QuoteBand": "a" * 64})
    assert refused.value.code == SECTION_MODULE_MISSING
    with pytest.raises(SiteInputsUnavailable) as unavailable:
        brand_loader_not_composed(None, None, {"id": "doc_a"})
    assert unavailable.value.code == "site_inputs.unavailable"
