"""Observe scene previews at full and illustrative feed scale without mutating evidence."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, PngImagePlugin

from agent_fixtures import FakeCoreClient, runtime_config
from lumen_agent.tools.substrate import LumenDesignTools
from lumen_agent.tools.view import _normalize_image_bytes, make_view_tool


def _png(size=(1080, 1080)):
    # Distinct opaque and transparent regions expose accidental compositing/cropping.
    image = Image.new("RGBA", size, (12, 34, 56, 255))
    image.paste((200, 40, 70, 128), (0, 0, size[0] // 2, size[1] // 2))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("custody", "keep the exact source bytes")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", pnginfo=metadata)
    return buffer.getvalue()


def _runtime(tmp_path, monkeypatch, raw, bundle="candidate"):
    class PreviewCore(FakeCoreClient):
        def export_preview(self, *args, **kwargs):
            return {
                "diagnostics": [],
                "export": {"artifacts": [{
                    "format": "png", "mime_type": "image/png",
                    "page_id": "page_test", "bytes": list(raw),
                }]},
            }

    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", PreviewCore)
    tools = LumenDesignTools(
        replace(runtime_config(tmp_path), scene_skill_bundle=bundle), "Make a scene"
    )
    assert json.loads(tools.compile_dsl_block("page page_test size(1080,1080,px)"))["compile"]["status"] == "ok"
    assert json.loads(tools.preflight_design())["preflight"]["status"] == "ok"
    assert json.loads(tools.export_preview("png"))["export"]["status"] == "ok"
    return tools


def _view(tools, target="preview"):
    return make_view_tool(tools).invoke({
        "name": "view", "args": {"target": target}, "id": "observe", "type": "tool_call",
    }).content


def _decode(block):
    return base64.b64decode(block["data"])


def _metadata(content):
    text = next(block["text"] for block in content if block["type"] == "text" and "source_preview_sha256" in block["text"])
    return json.JSONDecoder().raw_decode(text.split("\n", 1)[1])[0], text


@pytest.mark.parametrize("size", [(1080, 1080), (1080, 1920), (1200, 628)])
def test_candidate_preview_preserves_full_pixels_and_exposes_unmagnified_scale(tmp_path, monkeypatch, size):
    raw = _png(size)
    tools = _runtime(tmp_path, monkeypatch, raw)
    content = _view(tools)

    assert [block["type"] for block in content] == ["text", "image", "text", "image"]
    assert _decode(content[1]) == raw
    metadata, caption = _metadata(content)
    assert metadata["source_preview_sha256"] == hashlib.sha256(raw).hexdigest()
    assert metadata["source_size_px"] == list(size)
    assert metadata["scale"] == 360 / size[0]
    assert "not a platform specification" in caption
    assert "legibility" in caption and "preflight" in caption

    proxy_bytes = _decode(content[3])
    assert _normalize_image_bytes(proxy_bytes)[0] == proxy_bytes
    with Image.open(io.BytesIO(proxy_bytes)) as proxy, Image.open(io.BytesIO(raw)) as source:
        expected_size = (360, round(size[1] * 360 / size[0]))
        assert metadata["content_size_px"] == list(expected_size)
        assert metadata["canvas_size_px"] == list(proxy.size)
        assert min(proxy.size) >= 512
        assert max(proxy.size) <= 2000
        x, y, width, height = metadata["content_rect_px"]
        assert (width, height) == expected_size
        assert x >= 32 and y >= 32
        assert proxy.width - x - width >= 32 and proxy.height - y - height >= 32
        actual = proxy.crop((x, y, x + width, y + height)).convert("RGBA")
        expected = source.resize(expected_size, Image.Resampling.LANCZOS)
        assert actual.tobytes() == expected.tobytes()
        # Observation padding has opaque neutral pixels, distinguishable from artwork.
        assert proxy.getpixel((0, 0)) == (224, 224, 224, 255)


def test_view_addition_does_not_change_scene_artifacts_or_acceptance_receipts(tmp_path, monkeypatch):
    from test_scene_direction_review import review
    from test_scene_skill_family import direction

    tools = _runtime(tmp_path, monkeypatch, _png())
    path = tools.trace_dir / "workspace/creative-direction.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    planned = direction()
    planned["copy"][0]["text"] = "Plan"  # The actual FakeCore fixture's native text.
    path.write_text(json.dumps(planned))
    validated = json.loads(tools.validate_creative_direction())
    assert validated["status"] == "ok"
    critique = review(validated, page_id="page_test", node_id="headline", text="Plan")
    assert json.loads(tools.submit_visual_critique(json.dumps(critique)))["status"] == "ok"
    assert tools._acceptance_error(critique) is None
    scene = copy.deepcopy(tools.scene)
    receipt = copy.deepcopy(tools._preview_receipt)
    review_receipt = copy.deepcopy(tools._review_receipt)
    artifact_paths = list(tools.preview_paths)
    files_before = {str(path.relative_to(tools.trace_dir)) for path in tools.trace_dir.rglob("*") if path.is_file()}

    content = _view(tools)

    assert len([block for block in content if block["type"] == "image"]) == 2
    assert tools.scene == scene
    assert tools.preview_paths == artifact_paths
    assert tools._current_preview_receipt() == receipt == tools._preview_receipt
    assert tools._review_receipt == review_receipt
    assert tools._acceptance_error(critique) is None
    assert {str(path.relative_to(tools.trace_dir)) for path in tools.trace_dir.rglob("*") if path.is_file()} == files_before


def test_legacy_preview_stays_exactly_the_original_two_blocks(tmp_path, monkeypatch):
    raw = _png()
    tools = _runtime(tmp_path, monkeypatch, raw, bundle="legacy")
    legacy = _view(tools)
    tools.config = replace(tools.config, scene_skill_bundle="candidate")
    candidate = _view(tools)
    assert len(legacy) == 2
    assert candidate[:2] == legacy
    assert _decode(legacy[1]) == raw


@pytest.mark.parametrize("size, reason", [((1080, 7000), "exceeds"), ((240, 240), "smaller")])
def test_unrepresentable_proxy_is_explicitly_unavailable_and_full_view_remains(tmp_path, monkeypatch, size, reason):
    raw = _png(size)
    tools = _runtime(tmp_path, monkeypatch, raw)
    content = _view(tools)
    assert len(content) == 3
    assert _decode(content[1]) == _normalize_image_bytes(raw)[0]
    assert "readability proxy unavailable" in content[2]["text"]
    assert reason in content[2]["text"]
    metadata, _ = _metadata(content)
    assert metadata["source_preview_sha256"] == hashlib.sha256(raw).hexdigest()
    assert metadata["status"] == "unavailable"


def test_missing_changed_and_non_image_previews_never_gain_a_proxy(tmp_path, monkeypatch):
    tools = _runtime(tmp_path, monkeypatch, _png())
    path = tools.latest_export_summary["artifacts"][0]["path"]
    Path(path).write_bytes(_png((600, 600)))
    content = _view(tools)
    assert len(content) == 1 and "STALE" in content[0]["text"]
    Path(path).unlink()
    content = _view(tools)
    assert len(content) == 1 and "no preview" in content[0]["text"]
    # A malformed historical preview without a receipt must fail honestly, too.
    Path(path).write_text("not an image")
    tools._preview_receipt = None
    content = _view(tools)
    assert isinstance(content, str) and content.startswith("view failed:")


def test_proxy_preparation_failure_keeps_the_full_observation(tmp_path, monkeypatch):
    raw = _png()
    tools = _runtime(tmp_path, monkeypatch, raw)

    def fail_drawing(*args, **kwargs):
        raise OSError("observation annotation unavailable")

    monkeypatch.setattr(ImageDraw, "Draw", fail_drawing)
    content = _view(tools)
    assert len(content) == 3
    assert _decode(content[1]) == raw
    metadata, caption = _metadata(content)
    assert metadata["status"] == "unavailable"
    assert "OSError" in caption


def test_oversized_full_preview_keeps_existing_normalization_and_source_digest(tmp_path, monkeypatch):
    raw = _png((8000, 600))
    tools = _runtime(tmp_path, monkeypatch, raw)
    content = _view(tools)
    assert len(content) == 4
    assert _decode(content[1]) == _normalize_image_bytes(raw)[0]
    metadata, _ = _metadata(content)
    assert metadata["source_preview_sha256"] == hashlib.sha256(raw).hexdigest()
    assert metadata["source_size_px"] == [8000, 600]
    assert metadata["content_size_px"] == [360, 27]
    assert Path(tools.latest_export_summary["artifacts"][0]["path"]).read_bytes() == raw


def test_website_preview_is_byte_identical_when_candidate_bundle_is_configured(tmp_path):
    from lumen_agent.tools.web_substrate import LumenWebTools, make_web_view_tool

    config = runtime_config(tmp_path)
    seed = {
        "schema_version": 1, "id": "web_test", "title": "Site", "theme": {},
        "custom_css": "", "assets": {},
        "pages": [{"id": "home", "name": "Home", "route": "/", "root": "root", "nodes": {
            "root": {"id": "root", "kind": "container", "classes": "", "new_tab": False},
        }}],
    }
    tools = LumenWebTools(config, "Build a site", initial_web_doc=seed)
    raw = _png((1440, 900))
    path = tools.trace_dir / "preview.png"
    path.write_bytes(raw)
    tools._preview_by_width[1440] = str(path)
    tools._preview_doc_version = tools._doc_version
    tools._preview_iteration = 1

    def observe():
        return make_web_view_tool(tools).invoke({
            "name": "view", "args": {"target": "preview:1440"}, "id": "web-observe", "type": "tool_call",
        }).content

    legacy = observe()
    tools.config = replace(config, scene_skill_bundle="candidate")
    assert observe() == legacy
    assert len(legacy) == 2
    assert _decode(legacy[1]) == raw


def test_preview_freshness_check_and_pixel_read_share_the_scene_transaction(tmp_path, monkeypatch):
    """Pause a verified red preview while a real blue-panel edit tries to finish."""
    from lumen_agent.tools import substrate, view as view_module
    from lumen_api import core as core_module

    root = Path(__file__).resolve().parents[3]
    helper = root / "target/release/lumen-api-helper"
    if not helper.exists():
        pytest.skip("release helper not built")
    monkeypatch.setattr(core_module.settings, "lumen_core_helper", str(helper))
    core = core_module.CoreClient(repo_root=root)
    monkeypatch.setattr(substrate, "CoreClient", lambda **_: core)
    tools = LumenDesignTools(
        replace(runtime_config(tmp_path), scene_skill_bundle="candidate"), "Color panel"
    )
    assert json.loads(tools.compile_dsl_block(
        "page square size(1080,1080,px)\n  hero fr p(100,100) s(800,800) fill(#ff0000)"
    ))["compile"]["status"] == "ok"
    assert json.loads(tools.preflight_design())["preflight"]["status"] == "ok"
    assert json.loads(tools.export_preview("png"))["export"]["status"] == "ok"
    rendered_stamp = tools._preview_receipt["scene"]
    raw = Path(tools.latest_export_summary["artifacts"][0]["path"]).read_bytes()
    checked, contender_reached, release_check = (threading.Event() for _ in range(3))
    original_receipt = tools._current_preview_receipt
    original_image = view_module._image_bytes_block
    observed_stamps = []

    def pause_after_receipt_check():
        result = original_receipt()
        checked.set()
        # Cover both bounded controller waits even on a heavily loaded runner.
        assert release_check.wait(timeout=15)
        return result

    def observe_pixels(*args, **kwargs):
        observed_stamps.append(tools._scene_stamp())
        return original_image(*args, **kwargs)

    def mutate():
        # Probe the actual runtime RLock. Signal only after the edit completes
        # or reaches contention, avoiding a sleep-based "probably blocked" test.
        acquired = tools._scene_mutation_lock.acquire(blocking=False)
        if not acquired:
            contender_reached.set()
        try:
            return json.loads(tools.compile_dsl_block("#hero fill(#0000ff)"))
        finally:
            if acquired:
                tools._scene_mutation_lock.release()
            contender_reached.set()

    monkeypatch.setattr(tools, "_current_preview_receipt", pause_after_receipt_check)
    monkeypatch.setattr(view_module, "_image_bytes_block", observe_pixels)
    with ThreadPoolExecutor(max_workers=2) as pool:
        observation = pool.submit(_view, tools)
        try:
            assert checked.wait(timeout=5)
            mutation = pool.submit(mutate)
            assert contender_reached.wait(timeout=5)
        finally:
            release_check.set()
        content = observation.result(timeout=5)
        assert mutation.result(timeout=5)["compile"]["status"] == "ok"

    assert _decode(content[1]) == raw
    assert observed_stamps and all(stamp == rendered_stamp for stamp in observed_stamps)
    assert tools._scene_stamp() != rendered_stamp
    assert "STALE" in _view(tools)[0]["text"]
