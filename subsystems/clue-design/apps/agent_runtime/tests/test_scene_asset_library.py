"""W1.1 — the workspace asset library → SCENE-turn channel.

The bug this file pins (proven live, Apollo reference-ads POC 2026-08-26,
`.context/ref-ads-pilot-apollo-report.md` §6.1): the scene-turn runtime received
only `brand_kit_assets` (the kit's own logos/images) and `reference_assets` (this
turn's attachments). A workspace-library asset that was neither — in particular a
PRE-GENERATED `asset_gen_*` background — was invisible: `view("asset:<id>")`
answered `asset_unavailable` and `place_asset_in_node` refused it, while the very
same asset attached as `reference:4` viewed perfectly. References are a
CONDITIONING channel; they were never a path to a placeable scene asset.

`config.asset_library` already existed — website mode has consumed it since the
grounded-asset wave. These tests hold the scene substrate to the same contract:
an asset in the by-value library manifest is viewable, and placing it registers
its record into the scene FIRST (which is what stops the engine's
`LUME0211 op.asset_missing`, without any engine change).

Offline: no LLM, no network, `CoreClient` stubbed by `FakeCoreClient`.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

from lumen_agent import harness as harness_mod
from lumen_agent.tools.substrate import LumenDesignTools

from agent_fixtures import FakeCoreClient, runtime_config


def _solid_png(size: int = 640, color=(250, 214, 18)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _generated_library_record(
    workspace_id: str, source_bytes: bytes, thumb_bytes: bytes
) -> dict:
    """A GENERATED workspace-library asset exactly as the platform leaves one:
    durable `clue-storage` locations, `image_generation` provenance, and an id in
    the `asset_gen_*` family the POC produced."""
    from clue_design.storage import design_location, design_storage_key

    source_digest = hashlib.sha256(source_bytes).hexdigest()
    thumb_digest = hashlib.sha256(thumb_bytes).hexdigest()
    return {
        "id": "asset_gen_68b01141cc0b",
        "label": "apollo-bg-holo-yellow-wash",
        "kind": "raster_image",
        "status": "ready",
        "media": {
            "mime_type": "image/png",
            "digest": {"algorithm": "sha256", "value": source_digest},
            "location": design_location(design_storage_key(workspace_id, source_digest)),
            "thumbnail": {
                "location": design_location(
                    design_storage_key(workspace_id, thumb_digest)
                ),
                "mime_type": "image/png",
                "pixel_width": 256,
                "pixel_height": 256,
            },
        },
        "raster": {"pixel_width": 2048, "pixel_height": 1152},
        "license": {"name": "client_owned"},
        "provenance": {"source_label": "image generation"},
        "source": {"kind": "generated", "prompt": "holographic yellow wash"},
    }


def _library_tools(tmp_path: Path, monkeypatch, *, with_library: bool = True):
    """Scene-turn tools whose ONLY channel to the asset is the workspace library:
    no brand kit, no turn references — the exact Apollo shape."""
    from lumen_api.asset_custody import write_cache_blob

    workspace_id = "ws_w1_library"
    cache_dir = tmp_path / "engine-cache" / workspace_id
    source_bytes = _solid_png(1024)
    thumb_bytes = _solid_png(640)
    record = _generated_library_record(workspace_id, source_bytes, thumb_bytes)
    # The API's read-through (`ensure_materialized`) lands durable bytes in the
    # per-workspace engine cache by digest; this is the very writer it uses.
    write_cache_blob(cache_dir, hashlib.sha256(thumb_bytes).hexdigest(), thumb_bytes)
    write_cache_blob(cache_dir, hashlib.sha256(source_bytes).hexdigest(), source_bytes)

    entry = {
        "record": record,
        "title": "Apollo holographic yellow wash",
        "description": "Full-bleed lemon field with cyan/pink holographic grain.",
        "usage": "Ground layer for card-on-field ads.",
        "created_at": "2026-08-26T00:00:00Z",
        "updated_at": "2026-08-26T00:00:00Z",
    }
    config = replace(
        runtime_config(tmp_path),
        asset_store_root=cache_dir,
        brand_kit_assets=None,
        reference_assets=None,
        asset_library={record["id"]: entry} if with_library else None,
    )
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(config, "Design an Apollo ad")
    return tools, record, thumb_bytes


# --- view -------------------------------------------------------------------


def test_view_asset_resolves_a_workspace_library_asset(tmp_path, monkeypatch):
    """RED before W1.1: `view` consulted `brand_kit_assets` alone, so this
    returned the `asset_unavailable` text block the Apollo run hit three times."""
    tools, record, thumb_bytes = _library_tools(tmp_path, monkeypatch)

    view = harness_mod.make_view_tool(tools)
    msg = view.invoke(
        {
            "name": "view",
            "args": {"target": f"asset:{record['id']}"},
            "id": "v1",
            "type": "tool_call",
        }
    )
    content = msg.content
    assert isinstance(content, list), content
    image_blocks = [b for b in content if b["type"] == "image"]
    assert len(image_blocks) == 1, content
    assert base64.b64decode(image_blocks[0]["data"]) == thumb_bytes

    trace = (tools.trace_dir / "trace.jsonl").read_text()
    assert "asset_unavailable" not in trace


def test_older_asset_is_searchable_and_context_is_shared_with_web_mode(tmp_path, monkeypatch):
    from test_web_search_assets import _tools as web_tools

    tools, record, _ = _library_tools(tmp_path, monkeypatch)
    entry = tools.config.asset_library[record["id"]]
    context = {"revision": 7, "description": "Pinned context", "source_occurrences": []}
    entry.update(creative_type="product_screenshot", usage_roles=["card_image"],
                 revision=7, sources=["linkedin_ad"], asset_context=context)
    # An older relevant asset lies past both former scene and first-page caps.
    library = {f"recent_{i}": {"record": {"id": f"recent_{i}", "status": "ready", "kind": "raster_image"}}
               for i in range(501)}
    library[record["id"]] = entry
    materialized = []
    tools.config = replace(tools.config, asset_library=library, asset_materializer=materialized.append)
    web = web_tools(tmp_path / "web", asset_library=library, asset_materializer=materialized.append)
    scene_results = json.loads(tools.search_assets("product_screenshot"))["results"]
    assert scene_results[0]["asset_id"] == record["id"] and scene_results[0]["revision"] == 7
    assert record["id"] in web.search_assets("product_screenshot")
    assert materialized == []  # Discovery never fetches bytes.
    scene_view = harness_mod.make_view_tool(tools).invoke({"name": "view",
        "args": {"target": f"asset:{record['id']}"}, "id": "context", "type": "tool_call"})
    assert "Pinned context" in str(scene_view.content)
    assert "Pinned context" in str(web._view_asset(f"asset:{record['id']}"))
    assert materialized == [record["id"], record["id"]]


def test_view_unknown_asset_lists_library_ids_too(tmp_path, monkeypatch):
    """The honest-miss surface has to name what IS available, or the agent cannot
    discover the library at all (the Apollo run guessed ids from its brief)."""
    tools, record, _thumb = _library_tools(tmp_path, monkeypatch)

    view = harness_mod.make_view_tool(tools)
    msg = view.invoke(
        {
            "name": "view",
            "args": {"target": "asset:asset_does_not_exist"},
            "id": "v2",
            "type": "tool_call",
        }
    )
    text = "\n".join(b["text"] for b in msg.content if b["type"] == "text")
    assert record["id"] in text


def test_view_without_a_library_is_unchanged(tmp_path, monkeypatch):
    """No-op guarantee: a turn with no library manifest behaves exactly as before."""
    tools, record, _thumb = _library_tools(tmp_path, monkeypatch, with_library=False)

    view = harness_mod.make_view_tool(tools)
    msg = view.invoke(
        {
            "name": "view",
            "args": {"target": f"asset:{record['id']}"},
            "id": "v3",
            "type": "tool_call",
        }
    )
    assert all(b["type"] == "text" for b in msg.content)
    trace = (tools.trace_dir / "trace.jsonl").read_text()
    assert "asset_unavailable" in trace


# --- placement --------------------------------------------------------------


def _seeded_scene_with_ground() -> dict:
    return {
        "meta": {"id": "doc_ad", "title": "Apollo ad"},
        "pages": {"page_ad": {"id": "page_ad", "children": ["ground"]}},
        "nodes": {
            "ground": {
                "id": "ground",
                "kind": {"kind": "image", "asset_id": None},
                "children": [],
            }
        },
        "slots": {},
        "assets": {},
    }


def _placing_tools(tmp_path, monkeypatch, *, with_library: bool = True):
    tools, record, thumb = _library_tools(tmp_path, monkeypatch, with_library=with_library)
    tools.scene = _seeded_scene_with_ground()
    return tools, record, thumb


def test_place_registers_the_library_record_before_the_placement_op(
    tmp_path, monkeypatch
):
    """RED before W1.1: the substrate emitted the bare `place_asset_in_node` op and
    the engine answered `LUME0211 op.asset_missing` — the scene carried no asset
    record for the id. Placement must upsert the library record FIRST, exactly as
    `use_brand_asset` does for a kit asset."""
    tools, record, _thumb = _placing_tools(tmp_path, monkeypatch)

    result = json.loads(
        tools.asset(action="place", asset_id=record["id"], node_id="ground")
    )
    assert result["placement"]["status"] == "ok", result

    kinds = [op["kind"] for op in tools.core.applied_operations]
    assert kinds == ["upsert_asset", "place_asset_in_node"], kinds
    upserted = tools.core.applied_operations[0]["asset"]
    assert upserted["id"] == record["id"]
    # A library asset's own licence/provenance is the truth the placement
    # preserves — unlike a kit asset, whose source is rewritten to brand_guide.
    assert upserted["license"] == record["license"]
    assert upserted["provenance"] == record["provenance"]
    assert upserted["source"] == record["source"]


def test_place_does_not_re_register_an_asset_already_in_the_scene(
    tmp_path, monkeypatch
):
    tools, record, _thumb = _placing_tools(tmp_path, monkeypatch)
    tools.scene["assets"] = {record["id"]: record}

    json.loads(tools.asset(action="place", asset_id=record["id"], node_id="ground"))
    kinds = [op["kind"] for op in tools.core.applied_operations]
    assert kinds == ["place_asset_in_node"], kinds


def test_place_of_an_unknown_asset_invents_nothing(tmp_path, monkeypatch):
    """The repair only ever registers a record the library actually holds — an id
    the manifest does not carry still reaches the engine bare, so the honest
    `op.asset_missing` refusal survives."""
    tools, _record, _thumb = _placing_tools(tmp_path, monkeypatch)

    json.loads(tools.asset(action="place", asset_id="asset_ghost", node_id="ground"))
    kinds = [op["kind"] for op in tools.core.applied_operations]
    assert kinds == ["place_asset_in_node"], kinds


def test_place_without_a_library_is_unchanged(tmp_path, monkeypatch):
    tools, record, _thumb = _placing_tools(tmp_path, monkeypatch, with_library=False)

    json.loads(tools.asset(action="place", asset_id=record["id"], node_id="ground"))
    kinds = [op["kind"] for op in tools.core.applied_operations]
    assert kinds == ["place_asset_in_node"], kinds


# --- DSL-authored reference (the LUME0211 preflight repair) ------------------


def test_dsl_referenced_library_asset_is_auto_registered(tmp_path, monkeypatch):
    """The Apollo scene node cited the generated ground directly
    (`image asset(asset_gen_…)`), a form the compiler accepts but which registers
    nothing — the same dangling-reference class `_register_referenced_brand_assets`
    already repairs for KIT assets. It must repair library assets too."""
    tools, record, _thumb = _placing_tools(tmp_path, monkeypatch)
    tools.scene["nodes"]["ground"]["kind"] = {
        "kind": "image",
        "asset_id": record["id"],
    }

    tools._register_referenced_brand_assets("preflight_design")

    kinds = [op["kind"] for op in tools.core.applied_operations]
    assert kinds == ["upsert_asset"], kinds
    assert tools.core.applied_operations[0]["asset"]["id"] == record["id"]


def test_kit_membership_still_wins_over_the_library(tmp_path, monkeypatch):
    """An id in BOTH manifests is a kit asset: it keeps brand_guide provenance so
    LUMB0809/LUMB0810 logo governance (which matches on kit variant ids) stays on."""
    tools, record, _thumb = _placing_tools(tmp_path, monkeypatch)
    tools.config = replace(
        tools.config,
        brand_kit_assets={record["id"]: {"record": record, "title": "Kit copy"}},
    )
    tools.scene["nodes"]["ground"]["kind"] = {
        "kind": "image",
        "asset_id": record["id"],
    }

    tools._register_referenced_brand_assets("compile_dsl_block")
    upserted = tools.core.applied_operations[0]["asset"]
    assert upserted["source"]["kind"] == "brand_guide"
