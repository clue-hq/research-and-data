"""lumen_api.site_brand: the one BrandData builder (Lane B Task 8)."""

from __future__ import annotations

from types import SimpleNamespace

from lumen_api.site_brand import asset_store_file, clone_from_fragment, site_brand_data

D1, D2, D3, D4 = "1" * 64, "2" * 64, "3" * 64, "4" * 64


def _record(asset_id: str, digest: str | None, **extra) -> dict:
    media = {"mime_type": "image/png"} | ({"digest": {"algorithm": "sha256", "value": digest}} if digest else {})
    return {"id": asset_id, "kind": "raster_image", "label": asset_id, "media": media, **extra}


def test_every_file_is_a_workspace_blob_and_generated_images_say_so() -> None:
    clone = {"id": "frag_a", "label": "Hero", "html": f'<img src="/asset-store/{D4}" alt="A team">', "css": "",
             "slots": {}, "role": "hero", "page_url": "https://x.example/", "section_index": 1,
             "wrapper_class": "lumen-frag-a", "degraded_note": None}
    brand = site_brand_data(
        slug="kit_1",
        kit={"name": "Garner"},
        kit_assets={"asset_logo": {"record": _record("asset_logo", D1), "description": "The mark"},
                    "asset_nobytes": {"record": _record("asset_nobytes", None)}},
        font_faces=[{"digest": D2, "family": "Open Sans", "weight": 400}, {"digest": D3, "family": None}],
        clones=[clone],
        library_assets={"asset_gen_1": {"record": _record("asset_gen_1", D3, label="A calm classroom",
                                                          source={"kind": "generated"})}},
    )
    # The A9 rewrite (2026-10-12): BrandData has no `measured`; every value reaches site-kit in `kit`.
    assert "measured" not in brand and brand["slug"] == "kit_1" and brand["kit"] == {"name": "Garner"}
    assert brand["assets"]["asset_logo"] == {"kind": "raster_image", "label": "asset_logo", "description": "The mark",
                                             "mime": "image/png", "file": asset_store_file(D1), "logo": None}
    assert "asset_nobytes" not in brand["assets"]
    assert brand["assets"]["asset_gen_1"]["kind"] == "generated_image"
    assert brand["assets"]["asset_gen_1"]["description"] == "generated: A calm classroom"
    assert brand["assets"][asset_store_file(D4)] == {"kind": "captured_image", "label": "Hero", "description": "A team",
                                                     "mime": None, "file": asset_store_file(D4), "logo": None}
    assert brand["fonts"] == [{"family": "Open Sans", "weight": 400, "style": "normal", "file": asset_store_file(D2)}]
    assert brand["clones"] == {"frag_a": clone}


def test_a_registry_row_and_its_payload_become_a_site_kit_clone() -> None:
    section = {"fragment_id": "frag_95041c54da629d99", "section_role": "hero", "label": "Hero — Top Providers",
               "page_url": "https://garnerhealth.com/", "section_index": 1,
               "degraded_note": "this clone is marked broken, with no reason recorded."}
    loaded = SimpleNamespace(html="<section>Hi</section>", css=".x{}",
                             slot_manifest={"headline": {"kind": "text", "fallback": "Hi", "selector": "h1"}, "junk": 3})
    clone = clone_from_fragment(section, loaded)
    assert clone == {
        "id": "frag_95041c54da629d99", "role": "hero", "label": "Hero — Top Providers",
        "page_url": "https://garnerhealth.com/", "section_index": 1,
        "wrapper_class": "lumen-frag-95041c54da629d99", "html": "<section>Hi</section>", "css": ".x{}",
        "slots": {"headline": {"kind": "text", "fallback": "Hi"}},
        "degraded_note": "this clone is marked broken, with no reason recorded.",
    }
