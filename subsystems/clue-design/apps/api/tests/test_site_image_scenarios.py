"""Site element inspector, plan 5: images through the real routes. Our image's alt text, fit and
corners; a copied image replaced through its slot (its srcset dropped) with alt text by element key;
the header's account logo and the logos' alt texts; the editor's save, the stored document, undo and
redo, refusals, and the published page.

    .superpowers/review/2026-10-13-wave2/pytest-keyless.sh \\
        subsystems/clue-design/apps/api/tests/test_site_image_scenarios.py
"""

from __future__ import annotations

import copy
import html as html_lib

from fastapi.testclient import TestClient
from test_site_element_edits_scenarios import client, save, stored_site, version  # noqa: F401 - the fixture
from test_site_publish_package import mint_fragment
from test_site_publish_routes import ok, publish, stored
from site_kit_support import garner_brand, garner_site_without_clones

from conftest import published_html, published_page_html

ALT = 'Dr. "Smith" & the clinic'


def _assets(brand: dict) -> list[str]:
    files = [asset["file"] for asset in brand["assets"].values() if str(asset.get("file", "")).startswith("/asset-store/")]
    assert len(files) >= 2, "the fixture brand has two stored images"
    return files


def brand_with_gallery(fragment_id: str) -> tuple[dict, str, str]:
    brand = garner_brand()
    first, second = _assets(brand)[:2]
    brand["clones"] = {
        **brand["clones"],
        fragment_id: {
            "id": fragment_id,
            "role": "section",
            "label": "Gallery",
            "page_url": "https://garnerhealth.com/",
            "section_index": 0,
            "wrapper_class": "lumen-frag-gallery",
            "html": f'<div class="g"><img data-lumen-slot="photo" src="{first}" srcset="{first} 2x" alt="Captured"><p>Words</p></div>',
            "css": ".g img{width:100%}",
            "slots": {"photo": {"kind": "image", "fallback": first}},
        },
    }
    return brand, first, second


def images(site: dict, fragment_id: str, new_file: str, logo: str) -> dict:
    changed = copy.deepcopy(site)
    what = changed["pages"]["/analysis"]["content"][0]["props"]
    what["image"] = logo
    what["imageAlt"] = ALT
    what["_edits"] = {"image": {"imageFit": "fill", "radius": 16}}
    changed["pages"]["/"]["content"].append(
        {"type": "ClonedSection", "props": {"id": "gallery", "fragmentId": fragment_id, "slots": {"photo": new_file}, "replacements": [], "links": [],
                                            "alts": {"0.0": "Hotel lobby"}}}
    )
    header = changed["shell"]["header"]["props"]
    header["accountLogo"] = logo
    header["accountLogoAlt"] = "Carmel Clay Schools"
    header["logoAlt"] = "Garner Health"
    return changed


def test_images_are_saved_read_back_undone_redone_and_published(client: TestClient, workspace_id: str, design_storage) -> None:  # noqa: F811
    fragment_id = mint_fragment(design_storage, workspace_id, "gallery", "approved")
    brand, first, second = brand_with_gallery(fragment_id)
    # Every image the changed site names is held by the workspace (the helper swaps in stored digests),
    # and the starting site is the same copy without the changes.
    changed = stored(client, images(garner_site_without_clones("site_images"), fragment_id, second, first), brand)
    second = changed["pages"]["/"]["content"][-1]["props"]["slots"]["photo"]
    site = copy.deepcopy(changed)
    what = site["pages"]["/analysis"]["content"][0]["props"]
    for key in ("imageAlt", "_edits"):
        what.pop(key)
    site["pages"]["/"]["content"].pop()
    for key in ("accountLogoAlt", "logoAlt"):
        site["shell"]["header"]["props"].pop(key)
    assert save(client, "site_images", site).status_code == 200
    response = save(client, "site_images", changed)
    assert response.status_code == 200, response.text

    read = stored_site(client, "site_images")
    assert read["pages"]["/analysis"]["content"][0]["props"]["imageAlt"] == ALT
    assert read["pages"]["/"]["content"][-1]["props"]["alts"] == {"0.0": "Hotel lobby"}
    assert read["shell"]["header"]["props"]["accountLogoAlt"] == "Carmel Clay Schools"

    assert client.post("/documents/site_images/site/undo", json={"base_version": version(client, "site_images")}).status_code == 200
    undone = stored_site(client, "site_images")
    assert "imageAlt" not in undone["pages"]["/analysis"]["content"][0]["props"]
    assert undone["shell"]["header"] == site["shell"]["header"]
    assert client.post("/documents/site_images/site/redo", json={"base_version": version(client, "site_images")}).status_code == 200
    assert stored_site(client, "site_images")["pages"]["/analysis"]["content"][0]["props"]["imageAlt"] == ALT

    ok(publish(client, "site_images", slug="image-site"))
    analysis = published_page_html(workspace_id, "image-site", "/analysis")
    assert f'alt="{html_lib.escape(ALT)}"' in analysis, "our image's alt, escaped"
    rule = analysis.split('[data-clue-section="what"] [data-clue-el="image"]{', 1)[1].split("}", 1)[0]
    assert "object-fit:cover !important" in rule and "border-radius:16px !important" in rule, rule
    assert 'alt="Carmel Clay Schools"' in analysis and 'alt="Garner Health"' in analysis

    home = published_html(workspace_id, "image-site")
    gallery = home.split('data-clue-section="gallery"', 1)[1]
    image = gallery.split("<img", 1)[1].split(">", 1)[0]
    assert second.split("/")[-1] in image and "srcset" not in image, image
    assert 'alt="Hotel lobby"' in image, image


def test_bad_alt_texts_an_unknown_fit_and_a_span_alts_key_are_refused_by_name(client: TestClient) -> None:  # noqa: F811
    site = stored(client, garner_site_without_clones("site_images_bad"), garner_brand())
    assert save(client, "site_images_bad", site).status_code == 200
    rule = "alt text is plain text of at most 300 characters, with no line breaks or control characters"

    def refused(change) -> list[str]:
        changed = copy.deepcopy(site)
        change(changed)
        response = save(client, "site_images_bad", changed)
        assert response.status_code == 422, response.text
        return response.json()["detail"]["errors"]

    def too_long(s: dict) -> None:
        s["pages"]["/analysis"]["content"][0]["props"]["imageAlt"] = "x" * 301

    def line_break(s: dict) -> None:
        s["shell"]["header"]["props"]["accountLogoAlt"] = "two\nlines"

    def stretch(s: dict) -> None:
        s["pages"]["/analysis"]["content"][0]["props"]["_edits"] = {"image": {"imageFit": "stretch"}}

    assert any(error.endswith(rule) and "imageAlt" in error for error in refused(too_long))
    assert any(error.endswith(rule) and "accountLogoAlt" in error for error in refused(line_break))
    assert any("imageFit" in error for error in refused(stretch))
