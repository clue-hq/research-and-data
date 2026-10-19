"""generate_image (Lane B Task 10): the platform's image provider, stored as a library asset."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from lumen_agent.site.tools import SiteTools
from lumen_agent.site.workspace import materialize_workspace
from lumen_api.site_kit_cli import site_kit_toolchain_missing
from site_fixtures import FakeAssets, garner_brand, garner_site, inputs_for, png

needs_node = pytest.mark.skipif(site_kit_toolchain_missing() is not None, reason="site-kit toolchain missing")

PHOTO, MARK = "1" * 64, "2" * 64


class FakeImages:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("provider down")
        return SimpleNamespace(image_bytes=png("green", (32, 18)), mime_type="image/png", width=32, height=18,
                               model="test-image-model", license=None, provenance={"source": "test"})


def _tools(tmp_path: Path, images: FakeImages, assets: FakeAssets | None = None) -> SiteTools:
    brand = garner_brand()
    brand["assets"]["asset_photo"] = {"kind": "raster_image", "label": "Hallway", "description": "A school hallway",
                                      "mime": "image/png", "file": f"/asset-store/{PHOTO}", "logo": None}
    brand["assets"]["asset_mark"] = {"kind": "vector", "label": "Mark", "description": "The logo",
                                     "mime": "image/svg+xml", "file": f"/asset-store/{MARK}", "logo": None}
    assets = assets or FakeAssets(blobs={PHOTO: ("image/png", png()), MARK: ("image/svg+xml", b"<svg/>")})
    inputs = inputs_for(brand=brand, assets=assets, image_generate=images)
    workspace = tmp_path / "workspace"
    materialize_workspace(workspace, inputs, site=garner_site())
    return SiteTools(workspace=workspace, inputs=inputs, base_site=garner_site(), retry_delay_s=0)


def test_generate_image_stores_it_as_a_library_asset_and_shows_it(tmp_path: Path) -> None:
    images, assets = FakeImages(), FakeAssets(blobs={PHOTO: ("image/png", png())})
    tools = _tools(tmp_path, images, assets)
    blocks = tools.generate_image("A calm school-district scene at dusk", "16:9", [f"/asset-store/{PHOTO}"])
    text = blocks[0]["text"]
    file = text.split()[0]
    assert file.startswith("/asset-store/") and "32x18" in text and blocks[1]["type"] == "image"
    assert assets.generated[0]["prompt"] == "A calm school-district scene at dusk"
    call = images.calls[0]
    assert call["aspect_ratio"] == "16:9" and len(call["reference_images"]) == 1
    assert call["reference_images"][0][1] == "image/png"
    placed = {a["file"]: a for a in tools.brand["assets"].values()}[file]
    assert placed["kind"] == "generated_image" and placed["description"] == "generated: A calm school-district scene at dusk"
    assert tools.view_asset([file])[0]["text"].startswith(file)  # the turn can look at what it made


def test_generate_image_refuses_bad_references_and_reports_failures(tmp_path: Path) -> None:
    tools = _tools(tmp_path / "a", FakeImages())
    photo = f"/asset-store/{PHOTO}"
    assert "at most three" in tools.generate_image("x", "16:9", [photo] * 4)
    assert "not one of this brand's images" in tools.generate_image("x", "16:9", ["/asset-store/" + "9" * 64])
    assert "a photo or picture" in tools.generate_image("x", "16:9", [f"/asset-store/{MARK}"])
    failing = _tools(tmp_path / "b", FakeImages(fail=True))
    assert "could not make the image" in failing.generate_image("x", "16:9", [])
    unsaved = _tools(tmp_path / "c", FakeImages(), FakeAssets(blobs={PHOTO: ("image/png", png())}, fail_register=True))
    assert unsaved.generate_image("x", "1:1", []).startswith("The image was made but could not be saved (storage down).")


def test_fetch_logo_finds_a_companys_logos_and_makes_them_placeable(tmp_path: Path) -> None:
    mark, other = png("navy", (40, 20)), png("gray", (20, 20))
    assets = FakeAssets(blobs={PHOTO: ("image/png", png())}, logos={"lakeside.org": [
        ("light_lockup", mark, "image/png", None, False),
        ("unclassified", other, "image/png", "Lakeside (site header)", True)]})
    tools = _tools(tmp_path, FakeImages(), assets)
    text = tools.fetch_logo("lakeside.org", "Lakeside Hospital")
    assert assets.fetched == [("lakeside.org", "Lakeside Hospital")]
    by_file = {entry["file"]: entry for entry in tools.brand["assets"].values()}
    files = [line.split("`")[1] for line in text.splitlines() if line.startswith("- `")]
    assert len(files) == 2 and all(by_file[file]["kind"] == "account_logo" for file in files)
    assert "the full logo, for light backgrounds" in text and "Lakeside (site header)" in text
    assert tools.view_asset([files[0]])[0]["text"].startswith(files[0])  # it can look before it places


def test_fetch_logo_says_plainly_when_nothing_was_found_or_it_could_not_run(tmp_path: Path) -> None:
    tools = _tools(tmp_path / "a", FakeImages())
    assert tools.fetch_logo("nobody.example").startswith("No logo was found for nobody.example.")
    assert tools.fetch_logo("down.example").startswith("The logo search failed (vendor down).")
    assert tools.fetch_logo("  ").startswith("Give the company's website domain")


@needs_node
def test_a_logo_fetched_in_an_earlier_request_still_validates(tmp_path: Path) -> None:
    """A logo fetch_logo stored is a blob of this workspace, not one of the brand's assets: the next
    request's check holds it as the save does (siteImages), so an unrelated change stays valid."""

    held = "3" * 64
    site = garner_site()
    site["shell"]["header"]["props"]["accountLogo"] = f"/asset-store/{held}"
    assets = FakeAssets(blobs={held: ("image/png", png("navy"))})
    inputs = inputs_for(brand=garner_brand(), assets=assets)
    workspace = tmp_path / "workspace"
    materialize_workspace(workspace, inputs, site=site)
    tools = SiteTools(workspace=workspace, inputs=inputs, base_site=site, retry_delay_s=0)
    assert tools.validate_page() == "VALID."
    gone = SiteTools(workspace=workspace, inputs=inputs_for(brand=garner_brand(), assets=FakeAssets()), base_site=site,
                     retry_delay_s=0)
    assert "INVALID" in gone.validate_page()  # a file the workspace does not hold is still refused
