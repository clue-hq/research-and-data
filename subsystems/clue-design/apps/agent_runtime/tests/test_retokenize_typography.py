"""Live retokenization preserves effective type through core and authored replay."""

import copy
from pathlib import Path

import pytest
from lumen_agent.retokenize import build_retokenize_operations
from lumen_api.core import CoreClient

FIELDS = ("font_family", "font_weight", "font_size", "line_height", "letter_spacing")


@pytest.fixture
def typography_fixture():
    core = CoreClient(repo_root=Path(__file__).resolve().parents[3])
    kit = core.platform_default_brand_kit()
    for entry in kit["tokens"]["typography"].values():
        value = entry["value"]
        if value["default"].get("kind") == "style":
            value["default"].update(
                font_family="Inter", font_weight=400, font_size=48.0,
                line_height=1.05, letter_spacing=-0.03, font_asset=None, color=None,
            )
            value["modes"] = {}
    kit["tokens"]["typography"]["type.zz_equivalent"] = {"value": {"default": {
        "kind": "style", "font_family": "Inter", "font_weight": 400,
        "font_size": 56.0, "line_height": 1.4, "letter_spacing": 0.7,
    }}}
    kit["tokens"]["numbers"]["type.size.probe"] = {"value": {"default": {
        "kind": "number", "unit": "px", "value": 67.5,
    }}}
    seed = core.new_scene("doc_equivalent_type", "Equivalent typography")
    authored = core.compile_dsl_into_scene(
        seed,
        'page square size(1080,1080,px)\n'
        '  artboard fr s(fill,fill)\n'
        '    headline text "One clear idea" s(900,hug) style($type.zz_equivalent) '
        'font_size($type.size.probe) fill($text.primary)\n',
    )["scene"]
    return core, kit, authored


def text_fields(scene):
    kind = scene["nodes"]["headline"]["kind"]
    return {key: kind[key] for key in FIELDS}


def resolve(core, scene, kit, mode=None):
    result = core.preflight_scene(scene, kit, mode)
    assert not result["preflight"]["has_errors"], result["diagnostics"]
    return result["scene"]


def cycle(core, kit, runtime, ledger, expected, *, mode=None, tolerance=0.0):
    for _ in range(2):
        before = copy.deepcopy(runtime)
        operations = build_retokenize_operations(runtime, kit, size_snap_tolerance=tolerance)
        assert runtime == before
        runtime = resolve(core, core.apply_operations(runtime, operations)["scene"], kit, mode)
        ledger = core.apply_operations(ledger, operations)["scene"]
        replay = resolve(core, ledger, kit, mode)
        assert text_fields(runtime) == expected
        assert text_fields(replay) == expected
        assert runtime["nodes"]["headline"]["computed"] == replay["nodes"]["headline"]["computed"]
    return runtime


@pytest.mark.parametrize(("repair", "style", "size_token"), [
    (None, "type.zz_equivalent", "type.size.probe"),
    ("lh(1.8)", None, "type.size.probe"),
    ("ls(0.9)", None, "type.size.probe"),
    ("font_size(56.1)", None, None),
    ("font_size(68)", None, None),
    ("font_size(56)", "type.zz_equivalent", None),
])
def test_two_preflights_and_authored_ledger_preserve_all_type_fields(
    typography_fixture, repair, style, size_token,
):
    core, kit, authored = typography_fixture
    runtime = resolve(core, authored, kit)
    ledger = authored
    if repair:
        result = core.compile_dsl_into_scene(runtime, f"#headline {repair}", brand_kit=kit)
        runtime = result["scene"]
        ledger = core.apply_operations(
            ledger, result["dsl"]["compile_output"]["operations"]
        )["scene"]
    expected = text_fields(resolve(core, runtime, kit))
    operations = build_retokenize_operations(runtime, kit)
    rebound = core.apply_operations(runtime, operations)["scene"]["nodes"]["headline"]["kind"]
    assert rebound.get("style_token") == style
    assert rebound.get("font_size_token") == size_token
    cycle(core, kit, runtime, ledger, expected)


@pytest.mark.parametrize("repair", ["font_size(68)", "font_size(68) lh(1.8)"])
def test_positive_size_tolerance_is_opt_in_and_changes_only_size(typography_fixture, repair):
    core, kit, authored = typography_fixture
    runtime = resolve(core, authored, kit)
    repaired = core.compile_dsl_into_scene(runtime, f"#headline {repair}")
    runtime = repaired["scene"]
    ledger = core.apply_operations(
        authored, repaired["dsl"]["compile_output"]["operations"]
    )["scene"]
    expected = text_fields(runtime)
    unchanged = core.apply_operations(runtime, build_retokenize_operations(runtime, kit))["scene"]
    assert text_fields(resolve(core, unchanged, kit)) == expected
    expected["font_size"] = 67.5
    cycle(core, kit, runtime, ledger, expected, tolerance=0.06)


@pytest.mark.parametrize("optional", ["line_height", "letter_spacing"])
def test_absent_optional_role_field_preserves_literal(typography_fixture, optional):
    core, kit, authored = typography_fixture
    runtime = resolve(core, authored, kit)
    expected = text_fields(runtime)
    kit["tokens"]["typography"]["type.zz_equivalent"]["value"]["default"][optional] = None
    operations = build_retokenize_operations(runtime, kit)
    rebound = core.apply_operations(runtime, operations)["scene"]
    assert rebound["nodes"]["headline"]["kind"]["style_token"] == "type.zz_equivalent"
    cycle(core, kit, runtime, authored, expected)


@pytest.mark.parametrize("ambiguity", ["mode", "alias", "font_asset", "ramp_mode", "ramp_alias"])
def test_ambiguous_candidates_are_not_inferred_from_defaults(typography_fixture, ambiguity):
    core, kit, authored = typography_fixture
    runtime = resolve(core, authored, kit)
    expected = text_fields(runtime)
    style = kit["tokens"]["typography"]["type.zz_equivalent"]["value"]
    mode = {"values": {"theme": "dark"}}
    if ambiguity == "mode":
        style["modes"] = {"theme.dark": {**style["default"], "line_height": 1.9}}
    elif ambiguity == "alias":
        kit["tokens"]["aliases"]["type.zz_equivalent"] = {"token": "type.body"}
    elif ambiguity == "font_asset":
        style["default"]["font_asset"] = "font.brand"
    elif ambiguity == "ramp_mode":
        kit["tokens"]["numbers"]["type.size.probe"]["value"]["modes"] = {
            "theme.dark": {"kind": "number", "unit": "px", "value": 72.0},
        }
    else:
        kit["tokens"]["aliases"]["type.size.probe"] = {"token": "type.size.xl"}
    if ambiguity in ("mode", "ramp_mode", "alias", "ramp_alias"):
        assert text_fields(resolve(core, authored, kit, mode)) != expected
    operations = build_retokenize_operations(runtime, kit)
    rebound = core.apply_operations(runtime, operations)["scene"]
    assert rebound["nodes"]["headline"]["kind"].get("style_token") is None
    if ambiguity.startswith("ramp"):
        assert rebound["nodes"]["headline"]["kind"].get("font_size_token") is None
    # The old authored tokens intentionally mean something else under this kit;
    # preservation is measured against this already-resolved literal starting state.
    cycle(core, kit, runtime, runtime, expected, mode=mode)


@pytest.mark.parametrize("fill_owner", ["none", "author", "role"])
def test_role_color_is_only_inferred_when_core_would_keep_authored_fill(
    typography_fixture, fill_owner,
):
    core, kit, _ = typography_fixture
    style = kit["tokens"]["typography"]["type.zz_equivalent"]["value"]["default"]
    style["color"] = "text.brand"
    seed = core.new_scene("doc_color_candidate", "Color ownership")
    fill = "fill(#F24822)" if fill_owner == "author" else ""
    type_style = (
        "style($type.zz_equivalent)" if fill_owner == "role"
        else 'font("Inter",56,400,left) lh(1.4) ls(0.7)'
    )
    authored = core.compile_dsl_into_scene(seed, f'''page square size(1080,1080,px)
  artboard fr s(fill,fill)
    headline text "One clear idea" s(900,hug) {type_style} {fill}
''')["scene"]
    runtime = resolve(core, authored, kit)
    if fill_owner == "role":
        assert runtime["nodes"]["headline"]["fills"][0]["id"] == "headline_text_fill"
        style["color"] = "text.primary"
    operations = build_retokenize_operations(runtime, kit)
    rebound = core.apply_operations(runtime, operations)["scene"]
    assert rebound["nodes"]["headline"]["kind"].get("style_token") == (
        "type.zz_equivalent" if fill_owner == "author" else None
    )
    final = cycle(core, kit, runtime, authored, text_fields(runtime))
    assert final["nodes"]["headline"]["fills"] == runtime["nodes"]["headline"]["fills"]
