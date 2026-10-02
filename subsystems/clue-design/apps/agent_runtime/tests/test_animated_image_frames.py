"""Explicit GIF frames: real local palettes, disposal, custody and current tools."""

import base64
import copy
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest
from langchain_core.tools import StructuredTool
from lumen_agent.image_crop import ImageCropError, crop_source_pixels
from lumen_agent.tools.asset_preview import blob_path_for_digest
from lumen_agent.tools.view import make_view_tool
from PIL import GifImagePlugin, Image
from pydantic import ValidationError
from test_image_crop import HELPER
from test_image_crop import crop_context as crop_context

CLEAR = (0, 0, 0, 0)
RED = (255, 0, 0, 255)
BLUE = (0, 0, 255, 255)
GREEN = (0, 255, 0, 255)
YELLOW = (255, 255, 0, 255)
ROWS = [
    [RED, CLEAR, CLEAR, CLEAR],
    [RED, BLUE, CLEAR, CLEAR],
    [RED, CLEAR, GREEN, CLEAR],
    [RED, CLEAR, CLEAR, YELLOW],
]


def disposal_gif():
    """Hand-positioned GIF patches: retain, clear background, restore previous.

    Each patch uses its own local palette, with a different color at index 1.
    Logical canvas is 4x3; later 1x1 patch dimensions are NOT frame dimensions.
    """
    first = Image.new("P", (4, 3), 0)
    first.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
    first.putpixel((0, 0), 1)
    output = io.BytesIO()
    header, _ = GifImagePlugin.getheader(first, info={"transparency": 0})
    for block in header:
        output.write(block)
    for block in GifImagePlugin.getdata(first, transparency=0, disposal=1):
        output.write(block)
    for x, color, disposal in [(1, BLUE, 2), (2, GREEN, 3), (3, YELLOW, 1)]:
        patch = Image.new("P", (1, 1), 1)
        patch.putpalette([0, 0, 0, *color[:3]] + [0] * 762)
        for block in GifImagePlugin.getdata(
            patch, offset=(x, 0), transparency=0, disposal=disposal, include_color_table=True
        ):
            output.write(block)
    output.write(b";")
    return output.getvalue()


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("rect", [[0, 0, 4, 3], [1, 0, 4, 2]])
def test_selected_frame_preserves_composited_pixels_and_receipt(index, rect):
    raw = disposal_gif()
    original_digest = hashlib.sha256(raw).hexdigest()
    result = crop_source_pixels(
        raw, source_asset_id="gif", mime_type="image/gif", rect=rect, frame_index=index
    )
    left, top, right, bottom = rect
    expected = [ROWS[index], [CLEAR] * 4, [CLEAR] * 4]
    with Image.open(io.BytesIO(result.png_bytes)) as image:
        assert image.format == "PNG" and not getattr(image, "is_animated", False)
        assert image.size == (right - left, bottom - top)
        assert list(image.convert("RGBA").getdata()) == [
            pixel for row in expected[top:bottom] for pixel in row[left:right]
        ]
    receipt = result.receipt
    assert receipt["source_asset_id"] == "gif"
    assert receipt["source_digest"] == original_digest
    assert receipt["source_frame_index"] == index
    assert receipt["source_frame_count"] == 4
    assert receipt["source_dimensions"] == {"width": 4, "height": 3}
    assert receipt["source_rect"] == rect
    assert receipt["coordinate_system"] == "decoded_composited_frame_pixels"
    assert receipt["output_digest"] == hashlib.sha256(result.png_bytes).hexdigest()
    assert hashlib.sha256(raw).hexdigest() == original_digest


@pytest.mark.parametrize("index", [-1, True, False, 1.0, 1.5, "1", [], {}, 4, 1000000])
def test_bad_frame_indices_refuse_without_coercion(index):
    with pytest.raises(ImageCropError):
        crop_source_pixels(
            disposal_gif(),
            source_asset_id="gif",
            mime_type="image/gif",
            rect=[0, 0, 4, 3],
            frame_index=index,
        )


@pytest.mark.parametrize("fmt,mime", [("PNG", "image/png"), ("WEBP", "image/webp")])
def test_explicit_selection_refuses_other_formats_until_supported(fmt, mime):
    output = io.BytesIO()
    Image.new("RGB", (4, 3), "red").save(
        output, format=fmt, save_all=True, append_images=[Image.new("RGB", (4, 3), "blue")]
    )
    with pytest.raises(ImageCropError, match="GIF"):
        crop_source_pixels(
            output.getvalue(),
            source_asset_id="other",
            mime_type=mime,
            rect=[0, 0, 4, 3],
            frame_index=1,
        )


@pytest.fixture
def animated_context(request):
    if not HELPER.exists():
        pytest.skip("release helper not built")
    tools, record, _, store = request.getfixturevalue("crop_context")
    raw = disposal_gif()
    digest = hashlib.sha256(raw).hexdigest()
    source = tools.scene["assets"]["source"]
    source["media"]["mime_type"] = "image/gif"
    source["media"]["digest"]["value"] = digest
    path = blob_path_for_digest(store, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    tools.config = replace(
        tools.config, asset_library={"source": {"record": copy.deepcopy(source)}}
    )
    return tools, source, raw, store


def _observed_image(content):
    assert isinstance(content, list), content
    blocks = [block for block in content if block["type"] == "image"]
    assert len(blocks) == 1, content
    return Image.open(io.BytesIO(base64.b64decode(blocks[0]["data"])))


@pytest.mark.parametrize(
    "scope,target",
    [
        ("scene", "asset:source"),
        ("brand_kit_assets", "asset:source"),
        ("asset_library", "asset:source"),
        ("reference_assets", "reference:1"),
        ("reference_assets", "reference:source"),
    ],
)
def test_view_selects_original_frame_in_authorized_scope_without_writes(
    animated_context, scope, target
):
    tools, record, raw, store = animated_context
    # Viewing does not require permission to modify the source.
    record["license"]["allow_modification"] = False
    if scope != "scene":
        tools.config = replace(tools.config, asset_library=None)
        tools.config = replace(
            tools.config, **{scope: {"source": {"record": copy.deepcopy(record), "order": 0}}}
        )
        del tools.scene["assets"]["source"]
    before = copy.deepcopy(tools.scene)
    paths = sorted(store.rglob("*"))
    content = make_view_tool(tools).invoke({"target": target, "frame_index": 2})
    with _observed_image(content) as image:
        # Existing view magnifies small images with nearest-neighbor.
        assert image.convert("RGBA").getpixel((int(image.width * 0.625), 0)) == GREEN
        assert image.convert("RGBA").getpixel((int(image.width * 0.375), 0)) == CLEAR
    text = " ".join(block["text"] for block in content if block["type"] == "text")
    assert "frame index 2" in text and "4 frames" in text and "4x3" in text
    assert hashlib.sha256(raw).hexdigest() in text
    assert "animation not reviewed" in text
    assert tools.scene == before and tools.operations_ledger == []
    assert sorted(store.rglob("*")) == paths


@pytest.mark.parametrize("generated", [False, True])
def test_public_crop_frame_is_independent_inspectable_placeable_and_keeps_ancestry(
    animated_context, generated
):
    tools, record, raw, store = animated_context
    if generated:
        record["source"] = {"kind": "generated", "model": "test/model", "request_id": None}
    before = copy.deepcopy(tools.scene)
    result = json.loads(
        StructuredTool.from_function(tools.asset).invoke(
            {
                "action": "crop_image",
                "asset_id": "source",
                "crop_rect": [0, 0, 4, 3],
                "frame_index": 3,
            }
        )
    )
    assert result.get("image_crop", {}).get("status") == "ok", result
    created = result["image_crop"]
    derived_id = created["asset_id"]
    assert created["crop_receipt"]["source_frame_index"] == 3
    assert tools.scene["nodes"] == before["nodes"]
    assert tools.scene["assets"]["source"] == before["assets"]["source"]
    assert blob_path_for_digest(store, hashlib.sha256(raw).hexdigest()).read_bytes() == raw
    assert tools.scene["assets"][derived_id]["source"]["kind"] == "manual"
    assert tools.scene["assets"][derived_id]["license"] == record["license"]
    with _observed_image(make_view_tool(tools).invoke({"target": f"asset:{derived_id}"})) as image:
        assert image.convert("RGBA").getpixel((image.width - 1, 0)) == YELLOW
    second = json.loads(
        tools.asset(action="crop_image", asset_id=derived_id, crop_rect=[0, 0, 4, 1])
    )
    second_id = second["image_crop"]["asset_id"]
    placed = json.loads(
        tools.asset(action="place", asset_id=second_id, node_id="svg_raster_image", fit="contain")
    )
    assert placed["placement"]["status"] == "ok"
    assert tools.scene_has_generated_imagery() is generated
    # Older derivatives cannot erase a subsequently recovered stub ancestor.
    tools.scene["assets"]["source"]["source"] = {"kind": "generated", "model": "stub-image-v0"}
    refused = json.loads(
        tools.asset(action="crop_image", asset_id=second_id, crop_rect=[0, 0, 1, 1])
    )
    assert refused.get("error_code") == "asset.crop_unsupported_source"


@pytest.mark.parametrize("index", [True, False, 1.0, 1.5, "1", -1, 4])
@pytest.mark.parametrize("action", ["view", "crop"])
def test_public_tools_cannot_coerce_invalid_index_into_selected_pixels(
    animated_context, index, action
):
    tools, _, _, _ = animated_context
    before = copy.deepcopy(tools.scene)
    public = (
        make_view_tool(tools) if action == "view" else StructuredTool.from_function(tools.asset)
    )
    args = (
        {"target": "asset:source"}
        if action == "view"
        else {"action": "crop_image", "asset_id": "source", "crop_rect": [0, 0, 4, 3]}
    )
    try:
        result = public.invoke({**args, "frame_index": index})
    except ValidationError:
        pass  # Strict public schema rejects before the source tools execute.
    else:
        if action == "view":
            assert not any(block["type"] == "image" for block in result), result
        else:
            assert json.loads(result).get("status") == "error", result
    assert tools.scene == before and tools.operations_ledger == []


@pytest.mark.parametrize(
    "problem",
    ["missing", "corrupt", "bad_digest", "mime", "archived", "wrong_id", "path_id", "truncated"],
)
@pytest.mark.parametrize("action", ["view", "crop"])
def test_explicit_frame_refuses_unverified_original_instead_of_thumbnail(
    animated_context, problem, action
):
    tools, record, raw, store = animated_context
    path = blob_path_for_digest(store, hashlib.sha256(raw).hexdigest())
    asset_id = "source"
    if problem == "missing":
        path.unlink()
    elif problem == "corrupt":
        path.write_bytes(b"substituted source")
    elif problem == "bad_digest":
        record["media"]["digest"]["value"] = "../../outside"
    elif problem == "mime":
        record["media"]["mime_type"] = "image/png"
    elif problem == "archived":
        record["status"] = "archived"
    elif problem == "wrong_id":
        record["id"] = "foreign"
    elif problem == "path_id":
        asset_id = str(path)
    else:
        broken = raw[:40]
        digest = hashlib.sha256(broken).hexdigest()
        record["media"]["digest"]["value"] = digest
        broken_path = blob_path_for_digest(store, digest)
        broken_path.parent.mkdir(parents=True, exist_ok=True)
        broken_path.write_bytes(broken)
    before = copy.deepcopy(tools.scene)
    if action == "view":
        result = make_view_tool(tools).invoke({"target": f"asset:{asset_id}", "frame_index": 2})
        assert isinstance(result, list), result
        assert not any(block["type"] == "image" for block in result), result
        assert "view.frame_" in str(result), result
    else:
        result = json.loads(
            tools.asset(
                action="crop_image", asset_id=asset_id, crop_rect=[0, 0, 4, 3], frame_index=2
            )
        )
        assert result.get("status") == "error", result
    assert tools.scene == before and tools.operations_ledger == []


def test_default_thumbnail_remains_unknown_frame_but_advertises_verified_original_count(
    animated_context,
):
    tools, record, raw, store = animated_context
    # Existing PNG thumbnail belongs to the original static engine fixture.
    content = make_view_tool(tools).invoke({"target": "asset:source"})
    text = " ".join(block["text"] for block in content if block["type"] == "text")
    assert "source frame index unknown" in text
    assert "4 frames" in text and "frame_index" in text
    assert hashlib.sha256(raw).hexdigest() in text
    result = json.loads(tools.asset(action="crop_image", asset_id="source", crop_rect=[0, 0, 4, 3]))
    assert result.get("error_code") == "asset.crop_unsupported"


def test_frame_selection_is_not_silently_ignored_for_preview_or_other_asset_actions(
    animated_context,
):
    tools, _, _, _ = animated_context
    content = make_view_tool(tools).invoke({"target": "preview", "frame_index": 2})
    assert "view.frame_unsupported_target" in str(content), content
    for action in ("generate_image", "edit_image", "place", "list"):
        result = json.loads(
            StructuredTool.from_function(tools.asset).invoke({"action": action, "frame_index": 2})
        )
        assert result.get("error_code") == "asset.frame_unsupported_action", result
    assert tools.operations_ledger == []


def test_frame_crop_still_enforces_license_and_placeholder_refusal(animated_context):
    tools, record, _, _ = animated_context
    record["license"]["allow_modification"] = False
    result = json.loads(
        tools.asset(action="crop_image", asset_id="source", crop_rect=[0, 0, 4, 3], frame_index=2)
    )
    assert result.get("error_code") == "asset.crop_license"
    record["license"]["allow_modification"] = True
    record["kind"] = "placeholder"
    result = json.loads(
        tools.asset(action="crop_image", asset_id="source", crop_rect=[0, 0, 4, 3], frame_index=2)
    )
    assert result.get("error_code") == "asset.crop_unsupported_source"
    assert tools.operations_ledger == []


def test_selected_frame_respects_existing_decoded_pixel_limit(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(ImageCropError, match="safely decoded"):
        crop_source_pixels(
            disposal_gif(),
            source_asset_id="gif",
            mime_type="image/gif",
            rect=[0, 0, 4, 3],
            frame_index=2,
        )


@pytest.mark.parametrize("scope", ["brand_kit_assets", "asset_library", "reference_assets"])
def test_frame_crop_resolves_authorized_unplaced_original(animated_context, scope):
    tools, record, raw, store = animated_context
    tools.config = replace(tools.config, asset_library=None)
    tools.config = replace(tools.config, **{scope: {"source": {"record": copy.deepcopy(record)}}})
    del tools.scene["assets"]["source"]
    before = copy.deepcopy(tools.config)
    result = json.loads(
        tools.asset(
            action="crop_image",
            asset_id="source",
            crop_rect=[0, 0, 4, 3],
            frame_index=1,
        )
    )
    assert result.get("image_crop", {}).get("status") == "ok", result
    assert result["image_crop"]["crop_receipt"]["source_frame_index"] == 1
    assert tools.config == before
    assert blob_path_for_digest(store, hashlib.sha256(raw).hexdigest()).read_bytes() == raw


def test_reference_alias_cannot_select_library_original_without_turn_reference(animated_context):
    tools, _, _, _ = animated_context
    public = make_view_tool(tools)
    for target in ("reference:1", "reference:source"):
        content = public.invoke({"target": target, "frame_index": 2})
        assert not any(block["type"] == "image" for block in content), content
        assert "unknown reference" in str(content), content


def test_missing_reference_thumbnail_still_describes_verified_original_frames(animated_context):
    tools, record, _, _ = animated_context
    tools.config = replace(
        tools.config, reference_assets={"source": {"record": copy.deepcopy(record)}}
    )
    content = make_view_tool(tools).invoke({"target": "reference:1"})
    assert not any(block["type"] == "image" for block in content)
    assert "4 frames" in str(content) and "frame_index" in str(content), content


def test_missing_asset_thumbnail_keeps_original_frame_discovery_and_explicit_recovery(
    animated_context,
):
    tools, record, raw, store = animated_context
    preview_path, _, _ = tools._asset_preview_path(record)
    Path(preview_path).unlink()
    before = copy.deepcopy(tools.scene)
    public = make_view_tool(tools)
    content = public.invoke({"target": "asset:source"})
    assert not any(block["type"] == "image" for block in content)
    text = " ".join(block["text"] for block in content if block["type"] == "text")
    assert "preview file is missing" in text
    assert "4 frames" in text and "frame_index" in text
    assert hashlib.sha256(raw).hexdigest() in text
    selected = public.invoke({"target": "asset:source", "frame_index": 2})
    with _observed_image(selected) as image:
        assert image.convert("RGBA").getpixel((int(image.width * 0.625), 0)) == GREEN
    assert tools.scene == before and tools.operations_ledger == []
    assert blob_path_for_digest(store, hashlib.sha256(raw).hexdigest()).read_bytes() == raw
    assert not Path(preview_path).exists()
