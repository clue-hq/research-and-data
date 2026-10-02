"""Runtime-hygiene regressions for the living deepagent (sweep A1/A2/A3).

Covers three failures traced in .context/deepagent-v0/archetype-baseline-sweep:
  * A2 — a view() on an 8x8 asset thumbnail hit grok-4.5's <512px vision
    minimum; the provider rejection killed the turn unfinalized. Fixed by
    containment (no exception escapes view()) + normalization (upscale sub-512
    images before they are ever attached).
  * A3 — view("preview") served a stale black frame after the scene had been
    re-authored without a re-render; the loop burned rounds trusting it. Fixed
    by a staleness contract (refuse when the scene changed since the render).
  * A3 — `brand_logo_auto` was re-injected after the author removed it, because
    the deterministic placement re-ran every preflight. Fixed by place-once.
  * A1 — a leftover zero-children page shipped in the final scene. Fixed by
    finalize_run pruning empty pages with an announced note.
"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import replace
from pathlib import Path

from PIL import Image

from lumen_agent.tools.substrate import LumenDesignTools
from lumen_agent.tools import view as view_mod

from agent_fixtures import FakeCoreClient, prepare_acceptance_evidence, runtime_config


# --- helpers ----------------------------------------------------------------


def _png_bytes(size) -> bytes:
    if isinstance(size, int):
        size = (size, size)
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _tools(tmp_path, monkeypatch, kit=None):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path)
    if kit is not None:
        config = replace(config, brand_kit=kit, brand_kit_source="document")
    return LumenDesignTools(config, "Make a poster")


def _logo_kit() -> dict:
    return {
        "id": "brand_kit_test",
        "version": "1",
        "name": "Test",
        "approval_status": "approved",
        "modes": {
            "defaults": {
                "theme": "light",
                "density": "comfortable",
                "accessibility": "standard",
                "medium": "digital",
            }
        },
        "tokens": {},
        "assets": {
            "logos": {
                "primary": {
                    "variants": [
                        {"asset_id": "asset_logo_1", "width": 240, "height": 48}
                    ]
                }
            }
        },
    }


class _ApplyingCoreClient(FakeCoreClient):
    """A FakeCoreClient whose apply_operations actually mutates the scene for the
    ops these tests exercise (remove_page, insert_node) — the base fake only
    stamps a flag, which is enough for most tests but not for asserting the
    pruned/placed scene structure."""

    def apply_operations(self, scene, operations, scope=None):
        self.applied_operations.extend(operations)
        updated = json.loads(json.dumps(scene))
        pages = updated.setdefault("pages", {})
        nodes = updated.setdefault("nodes", {})
        for op in operations:
            kind = op.get("kind")
            if kind == "remove_page":
                pages.pop(op.get("page_id"), None)
            elif kind == "insert_node":
                node = op.get("node") or {}
                node_id = node.get("id")
                if node_id:
                    nodes[node_id] = node
                    parent = op.get("parent") or {}
                    if parent.get("kind") == "page":
                        page = pages.get(parent.get("id"))
                        if page is not None:
                            page.setdefault("children", []).append(node_id)
        return {"scene": updated, "applied_operations": len(operations), "diagnostics": []}


# --- Task 1: view containment ----------------------------------------------


def test_view_contains_provider_error_as_string(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    png_path = tools.trace_dir / "preview.png"
    png_path.write_bytes(_png_bytes(640))
    tools.latest_export_summary = {
        "status": "ok",
        "artifacts": [{"format": "png", "path": str(png_path), "width": 640, "height": 640}],
    }

    # Simulate any failure while building the image block (a provider rejection,
    # a corrupt image, an unreadable file): view() must NOT raise — it returns
    # an honest error string so the agent adapts and the turn continues.
    def _boom(_path):
        raise RuntimeError("Image has 64 total pixels (8x8), below the minimum")

    monkeypatch.setattr(view_mod, "_image_block", _boom)

    view = view_mod.make_view_tool(tools)
    msg = view.invoke({"name": "view", "args": {"target": "preview"}, "id": "c1", "type": "tool_call"})
    assert isinstance(msg.content, str)
    assert msg.content.startswith("view failed:")
    assert "below the minimum" in msg.content


def test_view_contains_corrupt_image_bytes(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    png_path = tools.trace_dir / "preview.png"
    png_path.write_bytes(b"not a real png")
    tools.latest_export_summary = {
        "status": "ok",
        "artifacts": [{"format": "png", "path": str(png_path), "width": 8, "height": 8}],
    }
    view = view_mod.make_view_tool(tools)
    msg = view.invoke({"name": "view", "args": {"target": "preview"}, "id": "c1", "type": "tool_call"})
    # Undecodable bytes -> contained into an error string, no raise.
    assert isinstance(msg.content, str)
    assert msg.content.startswith("view failed:")


# --- Task 1: tiny-image normalization --------------------------------------


def test_view_upscales_sub_minimum_image(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    png_path = tools.trace_dir / "preview.png"
    png_path.write_bytes(_png_bytes(8))  # the exact A2 failure: an 8x8 thumbnail
    tools.latest_export_summary = {
        "status": "ok",
        "artifacts": [{"format": "png", "path": str(png_path), "width": 8, "height": 8}],
    }
    view = view_mod.make_view_tool(tools)
    msg = view.invoke({"name": "view", "args": {"target": "preview"}, "id": "c1", "type": "tool_call"})
    image_blocks = [b for b in msg.content if b["type"] == "image"]
    assert len(image_blocks) == 1
    emitted = Image.open(io.BytesIO(base64.b64decode(image_blocks[0]["data"])))
    assert min(emitted.size) >= 512


def test_view_upscale_preserves_aspect_ratio(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    png_path = tools.trace_dir / "preview.png"
    png_path.write_bytes(_png_bytes((8, 16)))  # 1:2 portrait thumbnail
    tools.latest_export_summary = {
        "status": "ok",
        "artifacts": [{"format": "png", "path": str(png_path), "width": 8, "height": 16}],
    }
    view = view_mod.make_view_tool(tools)
    msg = view.invoke({"name": "view", "args": {"target": "preview"}, "id": "c1", "type": "tool_call"})
    emitted = Image.open(io.BytesIO(base64.b64decode(
        [b for b in msg.content if b["type"] == "image"][0]["data"]
    )))
    w, h = emitted.size
    assert min(w, h) >= 512
    assert abs((w / h) - 0.5) < 0.05  # aspect preserved


def test_normalize_leaves_large_images_untouched(tmp_path, monkeypatch):
    raw = _png_bytes(600)
    out, mime = view_mod._normalize_image_bytes(raw)
    assert out == raw
    assert mime == "image/png"


# --- Task 1b: the vision size CEILING (genweb slice 1) ----------------------
#
# The website reviewer captures whole pages: a realistic 3-4 section landing page
# renders 1440x14325 / 768x8095, and OpenRouter refuses those outright
# ("invalid_prompt ... image dimensions exceed max allowed size: 8000 pixels").
# The turn is transactional, so the refusal discarded every authored node.


def test_normalize_clamps_a_tall_page_capture_to_the_vision_ceiling():
    # The exact capture that killed the slice-0 generation run.
    raw = _png_bytes((1440, 14325))
    out, mime = view_mod._normalize_image_bytes(raw)
    assert mime == "image/png"
    clamped = Image.open(io.BytesIO(out))
    w, h = clamped.size
    assert max(w, h) <= view_mod._VISION_MAX_PX
    assert min(w, h) >= view_mod._VISION_MIN_PX
    # Aspect preserved: the reviewer must judge the page it rendered, not a squashed one.
    assert abs((w / h) - (1440 / 14325)) < 0.005


def test_normalize_clamps_the_narrow_tall_capture_too():
    raw = _png_bytes((768, 8095))
    out, _mime = view_mod._normalize_image_bytes(raw)
    w, h = Image.open(io.BytesIO(out)).size
    assert max(w, h) <= view_mod._VISION_MAX_PX
    assert abs((w / h) - (768 / 8095)) < 0.005


def test_normalize_ceiling_is_below_the_provider_limit():
    # The provider refuses AT 8000px; the ceiling leaves headroom for rounding.
    assert view_mod._VISION_MAX_PX < 8000


def test_normalize_ceiling_wins_when_both_bounds_are_violated():
    # A sliver: too narrow for the floor AND too tall for the ceiling. The two bounds
    # cannot both hold at a fixed aspect; the hard refusal we actually hit is the ceiling.
    raw = _png_bytes((120, 20000))
    out, _mime = view_mod._normalize_image_bytes(raw)
    w, h = Image.open(io.BytesIO(out)).size
    assert max(w, h) <= view_mod._VISION_MAX_PX


def test_normalize_leaves_an_in_range_image_byte_identical():
    raw = _png_bytes((1440, 3200))
    out, _mime = view_mod._normalize_image_bytes(raw)
    assert out == raw


def test_view_clamps_a_tall_preview_before_attaching_it(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    png_path = tools.trace_dir / "preview.png"
    png_path.write_bytes(_png_bytes((1440, 14325)))
    tools.latest_export_summary = {
        "status": "ok",
        "artifacts": [
            {"format": "png", "path": str(png_path), "width": 1440, "height": 14325}
        ],
    }
    view = view_mod.make_view_tool(tools)
    msg = view.invoke(
        {"name": "view", "args": {"target": "preview"}, "id": "c1", "type": "tool_call"}
    )
    image_blocks = [b for b in msg.content if b["type"] == "image"]
    assert len(image_blocks) == 1
    emitted = Image.open(io.BytesIO(base64.b64decode(image_blocks[0]["data"])))
    assert max(emitted.size) <= view_mod._VISION_MAX_PX


# --- G5: the MANY-IMAGE ceiling (genweb slice 2 blocker) --------------------
#
# The slice-1 ceiling above is the SINGLE-image limit. A request carrying many
# images has a lower per-image limit, and the web review conversation reaches it
# routinely: one render is three widths, plus state captures, and the
# orchestrator's history keeps every image it ever viewed. The first realistic
# chat-driven landing page died on the ORCHESTRATOR's own call after ~28 minutes:
#
#   invalid_prompt ... messages.1.content.39.image.source.base64.data: At least
#   one of the image dimensions exceed max allowed size for many-image requests:
#   2000 pixels
#
# Probed against the provider that refused it (anthropic/claude-opus-4.8 through
# OpenRouter's /responses endpoint — the one the runtime calls), 2026-08-19:
#
#   20 x 200x7500  ACCEPTED     |  21 x 200x7500  REFUSED   -> threshold is >20 images
#   40 x 200x3000  REFUSED      |  40 x 200x2000  ACCEPTED  -> 2000 is safe at any count
#
# and the vendor doc states the same rule: "If a single API request contains more
# than 20 images, a stricter per-image dimension limit applies ... resize each
# image so that neither dimension exceeds 2000 px, or keep the request to 20 or
# fewer image and document blocks."


def test_many_image_ceiling_is_the_limit_the_provider_states():
    # Not folklore: this is the number in the live refusal AND in the vendor doc.
    assert view_mod._VISION_MANY_IMAGE_MAX_PX == 2000
    assert view_mod._VISION_MANY_IMAGE_MAX_PX < view_mod._VISION_MAX_PX


def test_normalize_clamps_a_tall_page_capture_to_the_many_image_ceiling():
    # The exact capture the web reviewer attaches, three times per render.
    raw = _png_bytes((1440, 14325))
    out, mime = view_mod._normalize_image_bytes(
        raw, max_px=view_mod._VISION_MANY_IMAGE_MAX_PX
    )
    assert mime == "image/png"
    w, h = Image.open(io.BytesIO(out)).size
    assert max(w, h) <= view_mod._VISION_MANY_IMAGE_MAX_PX
    # Aspect preserved: the reviewer judges the page it rendered, not a squashed one.
    assert abs((w / h) - (1440 / 14325)) < 0.005


def test_normalize_clamps_the_narrow_capture_to_the_many_image_ceiling_too():
    raw = _png_bytes((768, 8095))
    out, _mime = view_mod._normalize_image_bytes(
        raw, max_px=view_mod._VISION_MANY_IMAGE_MAX_PX
    )
    w, h = Image.open(io.BytesIO(out)).size
    assert max(w, h) <= view_mod._VISION_MANY_IMAGE_MAX_PX
    assert abs((w / h) - (768 / 8095)) < 0.005


def test_normalize_defaults_to_the_single_image_ceiling():
    # The default is unchanged, so the scene path keeps its shipped behaviour.
    raw = _png_bytes((1440, 14325))
    assert view_mod._normalize_image_bytes(raw) == view_mod._normalize_image_bytes(
        raw, max_px=view_mod._VISION_MAX_PX
    )
    w, h = Image.open(io.BytesIO(view_mod._normalize_image_bytes(raw)[0])).size
    assert max(w, h) == view_mod._VISION_MAX_PX


def test_scene_view_keeps_the_single_image_ceiling(tmp_path, monkeypatch):
    """The scene harness attaches ONE artboard preview per view call and has never
    hit the many-image refusal; G5 deliberately leaves it on the single-image
    ceiling. If that ever changes, change this assertion with it."""
    tools = _tools(tmp_path, monkeypatch)
    png_path = tools.trace_dir / "preview.png"
    png_path.write_bytes(_png_bytes((1440, 14325)))
    tools.latest_export_summary = {
        "status": "ok",
        "artifacts": [
            {"format": "png", "path": str(png_path), "width": 1440, "height": 14325}
        ],
    }
    view = view_mod.make_view_tool(tools)
    msg = view.invoke(
        {"name": "view", "args": {"target": "preview"}, "id": "c1", "type": "tool_call"}
    )
    emitted = Image.open(
        io.BytesIO(base64.b64decode([b for b in msg.content if b["type"] == "image"][0]["data"]))
    )
    assert max(emitted.size) == view_mod._VISION_MAX_PX


# --- Task 2: preview staleness contract ------------------------------------


def test_view_preview_refuses_when_scene_changed_since_render(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    png_path = tools.trace_dir / "preview.png"
    png_path.write_bytes(_png_bytes(640))
    tools.latest_export_summary = {
        "status": "ok",
        "artifacts": [{"format": "png", "path": str(png_path), "width": 640, "height": 640}],
    }
    # Render was captured at the current mutation count.
    tools._stamp_preview_rendered()

    view = view_mod.make_view_tool(tools)
    # Fresh render -> served with an image block.
    fresh = view.invoke({"name": "view", "args": {"target": "preview"}, "id": "c1", "type": "tool_call"})
    assert any(b["type"] == "image" for b in fresh.content)

    # The scene mutates (a compile/edit) without a re-render.
    tools.scene["meta"]["title"] = "Changed scene"
    tools.scene_update_sources.append("compile_dsl_block")
    stale = view.invoke({"name": "view", "args": {"target": "preview"}, "id": "c2", "type": "tool_call"})
    assert isinstance(stale.content, list)
    assert len(stale.content) == 1
    assert "STALE" in stale.content[0]["text"]
    assert "render_preview" in stale.content[0]["text"]


def test_view_preview_survives_core_response_with_no_scene_change(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    png_path = tools.trace_dir / "preview.png"
    png_path.write_bytes(_png_bytes(640))
    tools.latest_export_summary = {
        "status": "ok",
        "artifacts": [{"format": "png", "path": str(png_path), "valid": True}],
    }
    tools._stamp_preview_rendered()
    # A rejected compile/preflight still returns the same canonical scene.
    # Logging that response is not a change to the pixels the agent must review.
    tools._replace_scene_from_core_response({"scene": tools.scene}, "compile_dsl_block")
    message = view_mod.make_view_tool(tools).invoke(
        {"name": "view", "args": {"target": "preview"}, "id": "noop", "type": "tool_call"}
    )
    assert any(block["type"] == "image" for block in message.content), message.content


def test_view_preview_refuses_changed_rendered_bytes(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    png_path = tools.trace_dir / "preview.png"
    png_path.write_bytes(_png_bytes(640))
    tools.latest_export_summary = {
        "status": "ok",
        "artifacts": [{"format": "png", "path": str(png_path), "valid": True}],
    }
    tools._stamp_preview_rendered()
    png_path.write_bytes(_png_bytes(320))
    message = view_mod.make_view_tool(tools).invoke(
        {"name": "view", "args": {"target": "preview"}, "id": "changed", "type": "tool_call"}
    )
    assert not any(block["type"] == "image" for block in message.content)
    assert "STALE" in message.content[0]["text"]


def test_view_preview_fresh_after_rerender(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    png_path = tools.trace_dir / "preview.png"
    png_path.write_bytes(_png_bytes(640))
    tools.latest_export_summary = {
        "status": "ok",
        "artifacts": [{"format": "png", "path": str(png_path), "width": 640, "height": 640}],
    }
    tools._stamp_preview_rendered()
    tools.scene_update_sources.append("compile_dsl_block")  # scene changed
    tools._stamp_preview_rendered()  # ... then re-rendered

    view = view_mod.make_view_tool(tools)
    msg = view.invoke({"name": "view", "args": {"target": "preview"}, "id": "c1", "type": "tool_call"})
    assert any(b["type"] == "image" for b in msg.content)


# --- Task 3: finalize prunes empty pages -----------------------------------


def test_finalize_prunes_empty_pages_with_announced_note(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _ApplyingCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Make a poster")
    tools.scene = {
        "meta": {"id": "doc", "title": "t"},
        "pages": {
            "keep": {"id": "keep", "children": ["n1"], "size": {"width": 1080.0, "height": 1080.0}},
            "empty": {"id": "empty", "children": [], "size": {"width": 1080.0, "height": 1080.0}},
        },
        "nodes": {"n1": {"id": "n1", "kind": {"kind": "text", "content": "hi"}, "children": []}},
        "slots": {},
        "assets": {},
    }

    prepare_acceptance_evidence(tools)
    # Finalize hygiene changes the reviewed scene; a fresh review is required.
    refused = tools.finalize_run("succeeded", "done", "Delivered the ad.")
    assert refused.startswith("REFUSED")
    assert not (tools.trace_dir / "final.json").exists()
    prepare_acceptance_evidence(tools)
    result = json.loads(tools.finalize_run("succeeded", "done", "Delivered the ad."))

    assert "empty" not in tools.scene["pages"]
    assert "keep" in tools.scene["pages"]
    assert "Pruned 1 empty page" in result["summary"]
    assert "empty" in result["summary"]
    # The prune rides the operations ledger so Accept drops it too.
    assert any(
        e["operation"]["kind"] == "remove_page" and e["operation"]["page_id"] == "empty"
        for e in tools.operations_ledger
    )


def test_finalize_keeps_a_single_empty_page(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _ApplyingCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Make a poster")
    tools.scene = {
        "meta": {"id": "doc", "title": "t"},
        "pages": {"only": {"id": "only", "children": [], "size": {"width": 1080.0, "height": 1080.0}}},
        "nodes": {},
        "slots": {},
        "assets": {},
    }
    prepare_acceptance_evidence(tools)
    result = json.loads(tools.finalize_run("succeeded", "done", "Delivered."))
    # Never strip to zero pages: a lone empty page is kept, no prune note.
    assert "only" in tools.scene["pages"]
    assert "Pruned" not in result["summary"]


# --- P0.3: the accepted-but-unexportable finalize guard ---------------------
#
# The 2026-08-24 baseline run finalized "succeeded" while EVERY export of its
# scene was refused by preflight. A run may no longer record acceptance while a
# blocking export error stands — but an advisory policy lint, which exports
# fine, must not refuse the finalize either.


def _diagnostic(code: str, severity: str = "error") -> dict:
    return {
        "code": code,
        "severity": severity,
        "message": f"{code} happened",
        "phase": "layout",
        "subject": None,
        "hint": None,
    }


def test_finalize_refuses_acceptance_while_a_blocking_export_error_stands(
    tmp_path, monkeypatch
):
    tools = _tools(tmp_path, monkeypatch)
    tools._latest_preflight_diagnostics = [_diagnostic("LUMV0821")]

    result = tools.finalize_run("accepted", "done", "Delivered the ad.")

    assert result.startswith("REFUSED:")
    assert "LUMV0821" in result
    # The refusal is a tool-level string, not a written final.json — nothing
    # recorded a success.
    assert not (tools.trace_dir / "final.json").exists()


def test_finalize_allows_acceptance_with_only_advisory_lints(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    real_preflight = tools.core.preflight_scene

    def advisory_preflight(*args, **kwargs):
        result = real_preflight(*args, **kwargs)
        result["diagnostics"] = [_diagnostic("LUMV0820")]
        result["preflight"]["has_errors"] = True
        return result

    monkeypatch.setattr(tools.core, "preflight_scene", advisory_preflight)
    prepare_acceptance_evidence(tools)

    result = json.loads(tools.finalize_run("accepted", "done", "Delivered the ad."))

    assert result["status"] == "accepted"
    # Announced, never silently dropped.
    assert "LUMV0820" in result["summary"]
    assert "advisory policy lint" in result["summary"]


def test_finalize_guard_only_binds_accepted_runs(tmp_path, monkeypatch):
    """An honest non-accepted finalize must still be able to record itself —
    the guard exists to stop false success, not to trap a failing run."""
    tools = _tools(tmp_path, monkeypatch)
    tools._latest_preflight_diagnostics = [_diagnostic("LUMV0821")]

    result = json.loads(tools.finalize_run("failed", "blocked", "Could not finish."))

    assert result["status"] == "failed"


def test_finalize_refuses_acceptance_when_preflight_never_ran(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    prepare_acceptance_evidence(tools, preflight=False)
    assert tools._latest_preflight_diagnostics is None

    result = tools.finalize_run("accepted", "done", "Delivered.")

    assert result.startswith("REFUSED")
    assert "preflight" in result.lower()
    assert not (tools.trace_dir / "final.json").exists()


# --- Task 3: brand_logo_auto place-once (no re-injection) -------------------


def test_logo_placed_once_not_reinjected_after_removal(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch, kit=_logo_kit())
    tools.compile_dsl_block("page page_test")  # gives a non-empty page to host the mark

    tools.preflight_design()
    first_placements = [
        op for op in tools.core.applied_operations
        if op.get("kind") == "insert_node" and (op.get("node") or {}).get("id") == "brand_logo_auto"
    ]
    assert len(first_placements) == 1
    assert tools._brand_logo_seen is True

    # Simulate the author removing the auto-placed mark (the base fake never
    # actually inserted it, so the scene already lacks brand_logo_auto — the
    # exact transient-absence that used to trigger re-injection every preflight).
    tools.preflight_design()
    all_placements = [
        op for op in tools.core.applied_operations
        if op.get("kind") == "insert_node" and (op.get("node") or {}).get("id") == "brand_logo_auto"
    ]
    # PLACE-ONCE: still exactly one placement across two preflights.
    assert len(all_placements) == 1


def test_no_auto_logo_when_author_placed_kit_logo(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch, kit=_logo_kit())
    tools.compile_dsl_block("page page_test")
    # Author placed the kit's own logo asset — the deterministic overlay must
    # not compete with it.
    tools.scene["nodes"]["author_logo"] = {
        "id": "author_logo",
        "kind": {"kind": "image", "asset_id": "asset_logo_1"},
        "children": [],
    }
    tools.scene["pages"]["page_test"]["children"].append("author_logo")

    tools.preflight_design()
    placements = [
        op for op in tools.core.applied_operations
        if op.get("kind") == "insert_node" and (op.get("node") or {}).get("id") == "brand_logo_auto"
    ]
    assert placements == []
    assert tools._brand_logo_seen is True
