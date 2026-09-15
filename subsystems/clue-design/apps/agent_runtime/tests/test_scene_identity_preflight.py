"""Real-core preflight preserves the author's candidate identity composition.

The fixtures are synthetic logo assets, not evidence of creative quality. All
scene construction, placement, replacement and removal use checked core actions.
"""

import base64
import copy
import json
from dataclasses import replace

import pytest
from agent_fixtures import runtime_config
from lumen_agent.tools.substrate import LumenDesignTools
from test_asset_preview_real_engine import HELPER
from test_asset_preview_real_engine import real_core as real_core

pytestmark = pytest.mark.skipif(not HELPER.exists(), reason="release helper not built")


@pytest.fixture
def identity_runtime(real_core, tmp_path):
    records = {}
    for identity, color in (("advertiser", "#142838"), ("target", "#248648")):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40">'
            f'<rect width="120" height="40" fill="{color}"/></svg>'
        ).encode()
        records[identity] = real_core.ingest_asset(
            store_root=str(tmp_path / "assets"),
            bytes_base64=base64.b64encode(svg).decode(),
            asset_id=f"asset_{identity}",
            label=f"Synthetic {identity} logo fixture",
            declared_mime_type="image/svg+xml",
            filename=f"{identity}.svg",
            kind="logo",
        )["asset"]["record"]
    kit = real_core.platform_default_brand_kit()
    kit["assets"]["logos"] = {"primary": {"usage": "primary", "variants": [{
        "asset_id": "asset_advertiser", "name": "original", "color_mode": "full_color",
        "width": 120, "height": 40,
    }]}}
    kit["tokens"]["colors"]["surface.identity_fixture"] = {
        "value": {"default": {"kind": "hex", "value": "#142838"}},
    }

    def prepare(*, bundle="candidate", treatment="none", seeded=False):
        config = replace(
            runtime_config(tmp_path), repo_root=real_core.repo_root,
            asset_store_root=tmp_path / "assets", scene_skill_bundle=bundle,
            brand_kit=kit, brand_kit_source="config",
            brand_kit_assets={"asset_advertiser": {"record": records["advertiser"]}},
            asset_library={"asset_target": {"record": records["target"]}},
        )
        tools = LumenDesignTools(config, "Compose an account-specific awareness ad")
        source = (
            'page square size(1080,1080,px)\n'
            '  field fr p(0,0) s(1080,1080) fill(#142838)\n'
            '  headline text "Make the next step clear" p(80,300) s(850,150) '
            'font_size(48) fill(#FFFFFF)\n'
        )
        if treatment in {"target", "both"}:
            source += '  target_logo fr p(350,80) s(240,80)\n'
        if treatment in {"advertiser", "both"}:
            source += '  advertiser_logo fr p(80,80) s(240,80)\n'
        if treatment == "both":
            source += '  separator text "×" p(320,90) s(30,50) font_size(32) fill(#FFFFFF)\n'
        result = json.loads(tools.compile_dsl_block(source))
        assert result["compile"]["status"] == "ok", json.dumps(result)
        # The core requires a page before registration. Keep both source channels
        # available even if this composition deliberately uses one or neither.
        result = json.loads(tools.apply_operations(json.dumps([
            {"kind": "upsert_asset", "asset": record} for record in records.values()
        ])))
        assert result["operations"]["status"] == "ok", result
        for identity in ("advertiser", "target"):
            node_id = f"{identity}_logo"
            if node_id in tools.scene["nodes"]:
                result = json.loads(tools.asset(
                    action="place", asset_id=f"asset_{identity}", node_id=node_id, fit="contain",
                ))
                assert result["placement"]["status"] == "ok", result
        if seeded:
            # Use a canonical resolved user scene; preflight must preserve it and
            # must not rebind the user's literal values or introduce a new mark.
            initial = real_core.preflight_scene(tools.scene, kit)["scene"]
            tools = LumenDesignTools(config, "Preserve this approved ad", initial_scene=initial)
        return tools, records

    return prepare


@pytest.mark.parametrize("treatment", ["target", "both", "none"])
def test_candidate_preflight_preserves_deliberate_identity_choices(identity_runtime, treatment):
    """Catch candidate preflight inserting an advertiser into an authored composition."""
    tools, _ = identity_runtime(treatment=treatment)
    expected_nodes = set(tools.scene["nodes"])
    expected_logos = {
        node_id: copy.deepcopy(node) for node_id, node in tools.scene["nodes"].items()
        if node_id.endswith("_logo")
    }
    for _ in range(2):
        result = json.loads(tools.preflight_design())
        assert result["preflight"]["status"] == "ok", result
        assert set(tools.scene["nodes"]) == expected_nodes
        for node_id, original in expected_logos.items():
            assert tools.scene["nodes"][node_id]["kind"] == original["kind"]
            assert tools.scene["nodes"][node_id]["asset_placement"] == original["asset_placement"]
        authored = json.loads((tools._iteration_dir() / "authored_scene.json").read_text())["scene"]
        # Candidate-only identity policy must not bypass ordinary retokenization.
        assert authored["nodes"]["field"]["fills"][0]["paint"] == {
            "kind": "token", "token": "surface.identity_fixture",
        }
    assert not any(entry["source"] == "place_brand_logo" for entry in tools.operations_ledger)


@pytest.mark.parametrize("bundle", ["candidate", "legacy"])
@pytest.mark.parametrize("treatment", ["none", "target", "both"])
def test_seeded_preflight_preserves_user_identity_and_literals(identity_runtime, bundle, treatment):
    tools, _ = identity_runtime(bundle=bundle, treatment=treatment, seeded=True)
    before = copy.deepcopy(tools.scene)
    for _ in range(2):
        result = json.loads(tools.preflight_design())
        assert result["preflight"]["status"] == "ok", result
        assert tools.scene == before
    assert not tools.operations_ledger


@pytest.mark.parametrize("treatment", ["none", "advertiser"])
def test_legacy_places_once_and_respects_checked_removal(identity_runtime, treatment):
    tools, _ = identity_runtime(bundle="legacy", treatment=treatment)
    node_id = "brand_logo_auto" if treatment == "none" else "advertiser_logo"
    result = json.loads(tools.preflight_design())
    assert result["preflight"]["status"] == "ok", result
    assert tools.scene["nodes"][node_id]["kind"]["asset_id"] == "asset_advertiser"
    tools.preflight_design()
    assert {n for n in tools.scene["nodes"] if "logo" in n} == {node_id}
    removed = json.loads(tools.apply_operations(json.dumps([
        {"kind": "remove_node", "node_id": node_id},
    ])))
    assert removed["operations"]["status"] == "ok", removed
    for _ in range(2):
        tools.preflight_design()
        assert not any("logo" in n for n in tools.scene["nodes"])


def test_dual_identity_assets_and_native_separator_remain_independently_editable(identity_runtime):
    tools, records = identity_runtime(treatment="both")
    tools.preflight_design()
    before = copy.deepcopy(tools.scene)
    # Replacing only the target slot must not consume its neighbour or separator.
    placed = json.loads(tools.asset(
        action="place", asset_id="asset_advertiser", node_id="target_logo", fit="contain",
    ))
    assert placed["placement"]["status"] == "ok", placed
    assert tools.scene["nodes"]["target_logo"]["kind"]["asset_id"] == "asset_advertiser"
    assert tools.scene["nodes"]["advertiser_logo"] == before["nodes"]["advertiser_logo"]
    assert tools.scene["nodes"]["separator"] == before["nodes"]["separator"]
    assert tools.scene["nodes"]["separator"]["kind"]["kind"] == "text"
    assert tools.scene["nodes"]["separator"]["kind"]["content"] == "×"
    for identity, record in records.items():
        assert tools.scene["assets"][f"asset_{identity}"]["media"] == record["media"]
    removed = json.loads(tools.apply_operations(json.dumps([
        {"kind": "remove_node", "node_id": "separator"},
    ])))
    assert removed["operations"]["status"] == "ok", removed
    tools.preflight_design()
    assert "separator" not in tools.scene["nodes"]
    assert {"advertiser_logo", "target_logo"} <= tools.scene["nodes"].keys()
