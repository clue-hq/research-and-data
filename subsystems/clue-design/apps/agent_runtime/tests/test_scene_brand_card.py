"""The scene card must advertise handles the native engine can actually consume."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from agent_fixtures import runtime_config
from lumen_agent.brand_card import build_brand_card
from lumen_agent.frame import build_frame_payload
from lumen_agent.retokenize import build_retokenize_operations
from lumen_agent.tools.substrate import LumenDesignTools
from lumen_agent.tools.web_substrate import LumenWebTools
from lumen_agent.workspace import scaffold_workspace
from lumen_api.core import CoreClient


@pytest.fixture
def core():
    return CoreClient(repo_root=Path(__file__).resolve().parents[3])


@pytest.fixture
def kit(core):
    kit = core.platform_default_brand_kit()
    # Measured values from the approved Google kit that exposed the bug. Keep
    # the test self-contained, with the platform fixture's locally usable font.
    for role, color in {
        "surface.page": "#EEEEEE",
        "text.primary": "#5F6368",
        "text.brand": "#2051DA",
    }.items():
        kit["tokens"]["colors"][role]["value"]["default"] = {
            "kind": "hex", "value": color,
        }
    kit["tokens"]["typography"]["type.display"]["value"]["default"]["font_size"] = 32.0
    kit["tokens"]["numbers"]["type.size.6xl"]["value"]["default"]["value"] = 68.5
    kit["tokens"]["numbers"]["type.size.measured"] = {
        "role": "font_size",
        "value": {"default": {"kind": "number", "value": 73.25, "unit": "px"}},
    }
    return kit


def scene_tools(tmp_path, kit, *, bundle="candidate"):
    return LumenDesignTools(
        replace(
            runtime_config(tmp_path),
            repo_root=Path(__file__).resolve().parents[3],
            brand_kit=kit,
            scene_skill_bundle=bundle,
        ),
        "Make an ad",
    )


def test_scene_card_color_handles_resolve_in_native_dsl(tmp_path, core, kit):
    """Following the card must not produce undefined hyphenated web tokens."""
    tools = scene_tools(tmp_path, kit)
    workspace = scaffold_workspace(tools, "Make an ad")
    card = json.loads((workspace / "brand_card.json").read_text())
    roles = card["color_roles"]["roles"]
    source = (
        'page square size(1080,1080,px)\n'
        f'  artboard fr s(fill,fill) fill(${roles["surface.page"]["token"]})\n'
        '    headline text "One clear idea" s(900,hug) style($type.display) '
        f'fill(${roles["text.brand"]["token"]})\n'
    )
    unresolved = core.compile_dsl_into_scene(tools.scene, source)["scene"]
    result = core.preflight_scene(unresolved, kit)
    assert not result["preflight"]["has_errors"], result["diagnostics"]
    assert result["scene"]["nodes"]["artboard"]["fills"][0]["paint"]["color"]["value"] == "#EEEEEE"
    assert result["scene"]["nodes"]["headline"]["fills"][0]["paint"]["color"]["value"] == "#2051DA"
    # The director's file and author's injected frame share the same card.
    assert json.dumps(card, indent=2) in build_frame_payload(tools)


@pytest.mark.parametrize(("token", "expected_size"), [
    ("type.size.6xl", 68.5), ("type.size.measured", 73.25),
])
def test_advertised_size_step_survives_preflight_and_retokenize(
    tmp_path, core, kit, token, expected_size,
):
    tools = scene_tools(tmp_path, kit)
    sizes = tools.brand_card.get("type_sizes", {}).get("tokens", {})
    assert token in sizes, "The scene author cannot discover this kit's real size step"
    assert sizes[token] == {"value": expected_size, "unit": "px"}
    source = (
        'page square size(1080,1080,px)\n'
        '  artboard fr s(fill,fill) fill($surface.page)\n'
        '    headline text "One clear idea" s(900,hug) style($type.display) '
        f'font_size(${token}) fill($text.primary)\n'
    )
    unresolved = core.compile_dsl_into_scene(tools.scene, source)["scene"]
    resolved = core.preflight_scene(unresolved, kit)
    assert not resolved["preflight"]["has_errors"]
    assert resolved["scene"]["nodes"]["headline"]["kind"]["font_size"] == expected_size
    operations = build_retokenize_operations(resolved["scene"], kit)
    replayed = core.apply_operations(unresolved, operations)["scene"]
    assert replayed["nodes"]["headline"]["kind"]["font_size_token"] == token
    checked = core.preflight_scene(replayed, kit)
    assert not checked["preflight"]["has_errors"]
    assert checked["scene"]["nodes"]["headline"]["kind"]["font_size"] == expected_size


def test_candidate_references_do_not_invent_user_attachment_origin(tmp_path, kit):
    tools = scene_tools(tmp_path, kit)
    tools.config = replace(tools.config, reference_assets={
        "auto_ad": {"order": 0, "record": {"label": "Existing advertiser example"},
                    "mime_type": "image/jpeg", "width": 1200, "height": 1200},
    })
    path = scaffold_workspace(tools, "Make an ad")
    refs = (path / "references.md").read_text()
    assert "user attached" not in refs.lower()
    assert "1 reference image(s)" in refs
    assert "| 1 | auto_ad | Existing advertiser example | image/jpeg | 1200×1200 |" in refs
    assert json.loads((path / "state.json").read_text())["reference_asset_ids"] == ["auto_ad"]


def test_candidate_card_does_not_change_default_legacy_or_web_card(tmp_path, core, kit):
    original = copy.deepcopy(kit)
    default = build_brand_card(kit)
    legacy = scene_tools(tmp_path / "legacy", kit, bundle="legacy")
    web_config = replace(legacy.config, scene_skill_bundle="candidate")
    web = LumenWebTools(
        web_config, "Make a site", core.web_new_doc("doc_card", "Site", None)["web_doc"]
    )
    assert legacy.brand_card == default == web.brand_card
    assert default["color_roles"]["roles"]["surface.page"] == {
        "token": "surface-page", "value": "#EEEEEE",
    }
    assert "type_sizes" not in default
    assert "bg-surface-brand" in default["color_roles"]["note"]
    scene_tools(tmp_path / "candidate", kit)
    assert kit == original


def test_candidate_can_read_and_use_color_outside_compact_roles(tmp_path, core, kit):
    """A muted body role must not hide a supplied dark display-ink choice."""
    kit["tokens"]["colors"]["palette.neutral.950"]["value"]["default"] = {
        "kind": "hex", "value": "#171B1F",
    }
    original = copy.deepcopy(kit)
    tools = scene_tools(tmp_path, kit)
    workspace = scaffold_workspace(tools, "Make an ad")
    catalog_path = workspace / "brand_colors.json"
    assert catalog_path.is_file(), "The compact card hides the kit's other usable colors"
    card = json.loads((workspace / "brand_card.json").read_text())
    assert card["color_catalog"]["path"] == "brand_colors.json"
    catalog = json.loads(catalog_path.read_text())
    assert catalog["kit"] == {"id": kit["id"], "version": kit["version"]}
    assert catalog["colors"]["palette.neutral.950"]["value"]["default"] == {
        "kind": "hex", "value": "#171B1F",
    }
    token = next(name for name, row in catalog["colors"].items()
                 if row["value"]["default"] == {"kind": "hex", "value": "#171B1F"})
    source = (
        'page square size(1080,1080,px)\n'
        '  artboard fr s(fill,fill) fill($surface.page)\n'
        '    headline text "One clear idea" s(900,hug) style($type.display) '
        f'fill(${token})\n'
    )
    scene = core.compile_dsl_into_scene(tools.scene, source)["scene"]
    result = core.preflight_scene(scene, kit)
    assert not result["preflight"]["has_errors"], result["diagnostics"]
    assert result["scene"]["nodes"]["headline"]["fills"][0]["paint"]["color"]["value"] == "#171B1F"
    assert kit == original


def test_scene_color_catalog_preserves_modes_aliases_without_exporting_full_kit(tmp_path, kit):
    kit["tokens"]["colors"]["text.source"] = {
        "role": "text",
        "description": "Display ink on light campaign backgrounds",
        "provenance": {"source": "official_style_guide", "confidence": 1.0},
        "value": {"default": {"kind": "alias", "token": "palette.neutral.950"},
                  "modes": {"theme.dark": {"kind": "hex", "value": "#FAFAFA"}}},
    }
    tools = scene_tools(tmp_path / "candidate", kit)
    workspace = scaffold_workspace(tools, "Make an ad")
    catalog_path = workspace / "brand_colors.json"
    assert catalog_path.is_file()
    catalog = json.loads(catalog_path.read_text())
    assert catalog["colors"]["text.source"] == kit["tokens"]["colors"]["text.source"]
    assert catalog["modes"] == kit["modes"]
    assert "assets" not in catalog and "typography" not in catalog
    legacy = scene_tools(tmp_path / "legacy", kit, bundle="legacy")
    legacy_workspace = scaffold_workspace(legacy, "Make an ad")
    assert not (legacy_workspace / "brand_colors.json").exists()
    assert "color_catalog" not in legacy.brand_card
