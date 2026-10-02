"""Characterize the existing public scene seams behind the construction guidance.

These mechanics already pass; the observed defect was misleading tool guidance.
No provider, database, acceptance or compiler behavior is replaced here.
"""

from __future__ import annotations

import base64
import copy
import json
from dataclasses import replace

import pytest
from agent_fixtures import runtime_config
from lumen_agent.tools.substrate import LumenDesignTools
from test_asset_preview_real_engine import HELPER, SVG_BYTES
from test_asset_preview_real_engine import real_core as real_core
from test_scene_asset_library import _solid_png

pytestmark = pytest.mark.skipif(not HELPER.exists(), reason="release helper not built")


RESERVATION = """page sample size(640,240,px)
  artwork fr p(11,23) s(480,128) rd(12) clip(true)
  caption text "Independent native copy" p(11,170) s(480,hug) font_size(20)
"""


@pytest.fixture
def placement_runtime(real_core, tmp_path):
    """Use real ingested pixels and a by-value library/kit, with temporary custody."""

    def prepare(*, channel="library", kind="raster_image", dsl=RESERVATION):
        record = real_core.ingest_asset(
            store_root=str(tmp_path / "assets"),
            bytes_base64=base64.b64encode(_solid_png(16)).decode(),
            asset_id="asset_fixture_artwork",
            label="Fixture artwork",
            declared_mime_type="image/png",
            filename="artwork.png",
            kind=kind,
        )["asset"]["record"]
        manifest = {record["id"]: {"record": record, "title": record["label"]}}
        config = replace(
            runtime_config(tmp_path),
            repo_root=real_core.repo_root,
            asset_store_root=tmp_path / "assets",
            asset_library=manifest if channel == "library" else None,
            brand_kit_assets=manifest if channel == "kit" else None,
        )
        tools = LumenDesignTools(config, "Place independent artwork")
        compiled = json.loads(tools.compile_dsl_block(dsl))
        assert compiled["compile"]["status"] == "ok", compiled
        return tools, record

    return prepare


@pytest.mark.parametrize(
    ("channel", "kind", "action"),
    [("library", "raster_image", "place"), ("kit", "logo", "use_brand_asset")],
)
def test_public_placement_consumes_only_the_reserved_leaf_and_replays_exactly(
    placement_runtime, channel, kind, action
):
    """Catch image-only preconditions, collateral layout edits and lost ledger ops."""
    tools, record = placement_runtime(channel=channel, kind=kind)
    before = copy.deepcopy(tools.scene)
    ledger_start = len(tools.operations_ledger)

    result = json.loads(
        tools.asset(action=action, asset_id=record["id"], node_id="artwork", fit="contain")
    )

    assert result["placement"]["status"] == "ok", result
    target = tools.scene["nodes"]["artwork"]
    assert target["kind"]["kind"] == "image"
    assert target["kind"]["asset_id"] == target["source_asset_id"] == record["id"]
    assert target["asset_placement"]["fit"] == "contain"
    placement_fields = {"kind", "source_asset_id", "asset_placement"}
    assert {k: v for k, v in target.items() if k not in placement_fields} == {
        k: v for k, v in before["nodes"]["artwork"].items() if k not in placement_fields
    }
    assert tools.scene["nodes"]["caption"] == before["nodes"]["caption"]
    assert tools.scene["pages"] == before["pages"]
    assert set(tools.scene["nodes"]) == {"artwork", "caption"}
    stored = tools.scene["assets"][record["id"]]
    assert stored["media"] == record["media"]
    if channel == "library":
        assert stored == record
    else:
        assert stored["source"]["kind"] == "brand_guide"
        assert stored["source"]["source_asset_id"] == record["id"]

    operations = [entry["operation"] for entry in tools.operations_ledger[ledger_start:]]
    assert [op["kind"] for op in operations] == ["upsert_asset", "place_asset_in_node"]
    replay = tools.core.apply_operations(before, operations)
    assert replay["scene"] == tools.scene
    restored = tools.core.apply_operations(replay["scene"], replay["edit"]["inverse_operations"])
    assert restored["scene"] == before


@pytest.mark.parametrize(
    ("node_id", "asset_id", "code"),
    [
        ("container", "asset_fixture_artwork", "op.leaf_parent"),
        ("absent", "asset_fixture_artwork", "op.node_missing"),
        ("artwork", "asset_absent", "op.asset_missing"),
    ],
)
def test_public_placement_refuses_invalid_targets_and_sources_without_consuming_nodes(
    placement_runtime, node_id, asset_id, code
):
    """A library registration may succeed, but a refused placement must not land."""
    tools, _ = placement_runtime(
        dsl=RESERVATION + "  container fr p(500,0) s(100,100)\n"
        '    child text "Keep me" s(100,hug)\n'
    )
    before = copy.deepcopy(tools.scene)
    ledger_start = len(tools.operations_ledger)
    result = json.loads(tools.asset(action="place", asset_id=asset_id, node_id=node_id))
    assert result["placement"]["status"] == "error"
    assert result["placement"]["error_code"] == code
    assert tools.scene["nodes"] == before["nodes"]
    assert tools.scene["pages"] == before["pages"]
    assert all(
        entry["operation"]["kind"] == "upsert_asset"
        for entry in tools.operations_ledger[ledger_start:]
    )


def test_known_real_asset_can_be_authored_directly_or_as_a_container_child(placement_runtime):
    """Catch breaking the valid real-ID DSL route while teaching reservations."""
    tools, record = placement_runtime(
        dsl=RESERVATION + "  direct_image image asset(asset_fixture_artwork) p(500,140) s(100,80)\n"
    )
    result = json.loads(
        tools.compile_dsl_block(
            f"reconcile(artwork)\n  image_child image asset({record['id']}) p(0,0) s(480,128)\n"
        )
    )
    assert result["compile"]["status"] == "ok", result
    assert tools.scene["nodes"]["artwork"]["kind"]["kind"] == "frame"
    assert tools.scene["nodes"]["artwork"]["children"] == ["image_child"]
    for node_id in ("image_child", "direct_image"):
        assert tools.scene["nodes"][node_id]["kind"]["asset_id"] == record["id"]
    assert tools.scene["assets"][record["id"]] == record


def test_assetless_image_remains_a_compile_error_without_applied_operations(placement_runtime):
    """The AWS failed child declaration stays invalid; placement needs no dummy image."""
    tools, _ = placement_runtime(dsl=RESERVATION.replace("artwork", "hero_art"))
    before = copy.deepcopy(tools.scene)
    ledger_start = len(tools.operations_ledger)
    result = json.loads(
        tools.compile_dsl_block("reconcile(hero_art)\n  hero_img img p(0,0) s(1080,1080)\n")
    )
    assert result["compile"]["status"] == "error"
    assert result["compile"]["halted_at"] == {"code": "LUMD0403", "line": 2}
    assert result["compile"]["applied_operations"] == 0
    assert tools.scene == before
    assert len(tools.operations_ledger) == ledger_start


def test_native_vector_placement_stays_native_and_preserves_the_reservation(
    placement_runtime, tmp_path
):
    """The placement contract must not rasterize a vector that has native path data."""
    tools, record = placement_runtime()
    vector = tools.core.ingest_asset(
        store_root=str(tmp_path / "assets"),
        bytes_base64=base64.b64encode(SVG_BYTES).decode(),
        asset_id=record["id"],
        label="Native path fixture",
        declared_mime_type="image/svg+xml",
        filename="artwork.svg",
        kind="vector",
    )["asset"]["record"]
    # A native path-backed vector record may carry path_data, independent of
    # the SVG preview media; this is the core's existing native placement branch.
    vector.setdefault("vector", {})["path_data"] = "M0 0 L64 0 L64 64 L0 64 Z"
    tools.config.asset_library[record["id"]]["record"] = vector
    before = copy.deepcopy(tools.scene["nodes"]["artwork"])
    result = json.loads(tools.asset(action="place", asset_id=record["id"], node_id="artwork"))
    assert result["placement"]["status"] == "ok", result
    target = tools.scene["nodes"]["artwork"]
    assert target["kind"]["kind"] == "vector"
    assert target["kind"]["path_data"] == "M0 0 L64 0 L64 64 L0 64 Z"
    assert target["transform"] == before["transform"]
    assert target["size"] == before["size"]


def test_inspect_exposes_reparented_order_and_geometry_without_changing_scene(placement_runtime):
    """Catch a sorted/flattened tree hiding the Conduit reparent-to-index-zero trap."""
    tools, record = placement_runtime(
        dsl="""page ad_square size(1080,1080,px)
  artboard fr s(1080,1080) clip(true)
    bg_blur fr s(1080,1080)
    eyebrow_pill fr p(340,88) s(400,40)
      eyebrow text "Integration" s(400,hug) font_size(17)
    support text "Independent support" p(340,700) s(400,hug)
"""
    )
    result = json.loads(
        tools.compile_dsl_block(
            "parent(eyebrow, artboard)\ndelete(eyebrow_pill)\n"
            "#eyebrow p(340, 88) s(400, hug) fill(#ffffff) font_size(17)\n"
        )
    )
    assert result["compile"]["status"] == "ok", result
    placed = json.loads(tools.asset(action="place", asset_id=record["id"], node_id="bg_blur"))
    assert placed["placement"]["status"] == "ok", placed
    json.loads(tools.preflight_design())
    before, ledger = copy.deepcopy(tools.scene), copy.deepcopy(tools.operations_ledger)
    tree = json.loads(tools.inspect(view="node_tree", target="ad_square"))
    page = json.loads(tools.inspect(view="page", target="ad_square"))
    children = tree["node_tree"][0]["children"]
    assert [child["id"] for child in children] == ["eyebrow", "bg_blur", "support"]
    assert children[0]["text"] == "Integration"
    assert children[1]["source_asset_id"] == record["id"]
    assert page["node_tree"] == tree["node_tree"]
    geometry = json.loads(tools.inspect(view="geometry", target="eyebrow"))
    assert geometry["transform"]["x"] == 340
    assert geometry["transform"]["y"] == 88
    assert geometry["size"]["width"] == {"kind": "fixed", "value": 400.0}
    assert geometry["computed"]["layout_bounds"]["x"] == 340
    assert geometry["computed"]["layout_bounds"]["y"] == 88
    assert geometry["computed"]["layout_bounds"]["width"] == 400
    assert tools.scene == before and tools.operations_ledger == ledger
