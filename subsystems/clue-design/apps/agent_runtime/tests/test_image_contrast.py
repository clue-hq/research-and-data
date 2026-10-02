"""Image-region measurements catch the live white-on-pale false acceptance."""

import io
import json

import pytest
from PIL import Image
from test_scene_asset_library import _library_tools


def _png(color, size=(20, 20)):
    output = io.BytesIO()
    Image.new("RGBA", size, color).save(output, format="PNG")
    return output.getvalue()


def test_pale_ground_rejects_white_and_supports_dark_ink():
    from lumen_agent.image_contrast import measure_image_contrast

    pixels = _png((211, 239, 245, 255))
    white = measure_image_contrast(pixels, "#FFFFFF", [0, 0, 1, 1])
    dark = measure_image_contrast(pixels, "#24231D", [0, 0, 1, 1])
    assert white["maximum"] < 1.3
    assert not white["all_sampled_at_least_3"]
    assert not white["all_sampled_at_least_4_5"]
    assert dark["minimum"] > 12
    assert dark["all_sampled_at_least_4_5"]


def test_regions_are_source_normalized_and_do_not_average_away_failures():
    from lumen_agent.image_contrast import measure_image_contrast

    image = Image.new("RGB", (20, 20), "black")
    image.paste("white", (10, 0, 20, 20))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    left = measure_image_contrast(stream.getvalue(), "#FFFFFF", [0, 0, 0.5, 1])
    whole = measure_image_contrast(stream.getvalue(), "#FFFFFF", [0, 0, 1, 1])
    assert left["minimum"] == pytest.approx(21)
    assert left["sample_count"] == 200
    assert whole["minimum"] == pytest.approx(1)
    assert whole["fraction_below_3"] == 0.5
    assert not whole["all_sampled_at_least_3"]


@pytest.mark.parametrize(
    "region", [[0, 0, 0, 1], [-0.1, 0, 1, 1], [0, 0, 2, 1], [0, 0], [0, 0, float("nan"), 1]]
)
def test_invalid_region_cannot_report_a_contrast_pass(region):
    from lumen_agent.image_contrast import measure_image_contrast

    with pytest.raises(ValueError):
        measure_image_contrast(_png((0, 0, 0, 255)), "#FFFFFF", region)


@pytest.mark.parametrize("foreground", ["#FFF", "#FFFFFF00", "white", "#zzzzzz"])
def test_requires_an_explicit_opaque_resolved_foreground(foreground):
    from lumen_agent.image_contrast import measure_image_contrast

    with pytest.raises(ValueError):
        measure_image_contrast(_png((0, 0, 0, 255)), foreground, [0, 0, 1, 1])


def test_transparent_ground_requires_composited_evidence():
    from lumen_agent.image_contrast import measure_image_contrast

    with pytest.raises(ValueError, match="transparent"):
        measure_image_contrast(_png((0, 0, 0, 0)), "#FFFFFF", [0, 0, 1, 1])


def test_threshold_is_not_rounded_up_to_pass():
    from lumen_agent.image_contrast import measure_image_contrast

    measured = measure_image_contrast(_png((119, 119, 119, 255)), "#FFFFFF", [0, 0, 1, 1])
    assert 4.47 < measured["minimum"] < 4.5
    assert not measured["all_sampled_at_least_4_5"]


def test_public_inspection_is_read_only_and_identifies_the_measured_pixels(tmp_path, monkeypatch):
    tools, record, _ = _library_tools(tmp_path, monkeypatch)
    before = json.dumps(tools.scene, sort_keys=True)
    result = json.loads(
        tools.inspect(
            view="image_contrast",
            target=record["id"],
            foreground_color="#FFFFFF",
            region=[0, 0, 1, 1],
        )
    )
    assert result["status"] == "ok"
    assert result["source_digest"] == record["media"]["digest"]["value"]
    assert result["contrast"]["maximum"] < 2
    assert json.dumps(tools.scene, sort_keys=True) == before
