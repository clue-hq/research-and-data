"""generate_image (Lane B Task 10): the platform's image provider, stored as a library asset."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from lumen_agent.site.tools import SiteTools
from lumen_agent.site.workspace import materialize_workspace
from site_fixtures import FakeAssets, garner_brand, garner_site, inputs_for, png

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
