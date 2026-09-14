"""A draft's retokenize operations must mean the same thing on ledger replay."""

from pathlib import Path

import pytest

from lumen_agent.retokenize import build_retokenize_operations
from lumen_api.core import CoreClient


@pytest.mark.parametrize(("step", "expected_size"), [("7xl", 80.0), ("xl", 24.0)])
def test_active_retokenize_preserves_size_on_unresolved_ledger_replay(
    step: str, expected_size: float
) -> None:
    core = CoreClient(repo_root=Path(__file__).resolve().parents[3])
    kit = core.platform_default_brand_kit()
    # Valid kit fixture with one family/weight and distinct role defaults:
    # rebinding may select another role, but the requested size must survive.
    for name, entry in kit["tokens"]["typography"].items():
        style = entry["value"]["default"]
        if style.get("kind") == "style":
            style.update(
                font_family="Inter",
                font_weight=400,
                font_size=51.0 if name == "type.display" else 16.0,
            )
    seed = core.new_scene("doc_replay_type", "Typography replay")
    compiled = core.compile_dsl_into_scene(seed, f'''page square size(1080,1080,px)
  artboard fr s(fill,fill) fill($surface.page)
    headline text "One clear idea" s(900,hug) style($type.display) font_size($type.size.{step}) fill($text.primary)
''')
    unresolved = compiled["scene"]
    resolved = core.preflight_scene(unresolved, kit)
    assert not resolved["preflight"]["has_errors"]
    assert resolved["scene"]["nodes"]["headline"]["kind"]["font_size"] == expected_size
    operations = build_retokenize_operations(resolved["scene"], kit)
    runtime = core.apply_operations(resolved["scene"], operations)["scene"]
    replayed = core.apply_operations(unresolved, operations)["scene"]
    assert replayed["nodes"]["headline"]["kind"].get("font_size_token") == f"type.size.{step}"
    text_kinds = []
    for scene in (runtime, replayed):
        preflight = core.preflight_scene(scene, kit)
        assert not preflight["preflight"]["has_errors"]
        assert preflight["scene"]["nodes"]["headline"]["kind"]["font_size"] == expected_size
        text_kinds.append(preflight["scene"]["nodes"]["headline"]["kind"])
    assert text_kinds[0] == text_kinds[1]


def test_explicit_size_repair_survives_retokenization_before_resolution() -> None:
    core = CoreClient(repo_root=Path(__file__).resolve().parents[3])
    kit = core.platform_default_brand_kit()
    for entry in kit["tokens"]["typography"].values():
        style = entry["value"]["default"]
        if style.get("kind") == "style":
            style.update(font_family="Inter", font_weight=400, font_size=17.0)
    seed = core.new_scene("doc_size_repair", "Explicit typography repair")
    first = core.compile_dsl_into_scene(seed, '''page square size(1080,1080,px)
  artboard fr s(fill,fill)
    support text "Readable supporting copy" s(780,hug) style($type.body) font_size($type.size.lg)
''')
    resolved = core.preflight_scene(first["scene"], kit)["scene"]
    repaired = core.compile_dsl_into_scene(
        resolved, "#support font_size($type.size.xl) lh(1.35)"
    )["scene"]
    assert repaired["nodes"]["support"]["kind"]["font_size_token"] == "type.size.xl"
    # The numeric size is still the old resolved value until core resolves the
    # explicitly authored token. Guessing a role from that value undoes repair.
    operations = build_retokenize_operations(repaired, kit)
    retokenized = core.apply_operations(repaired, operations)["scene"]
    final = core.preflight_scene(retokenized, kit)
    assert not final["preflight"]["has_errors"]
    assert final["scene"]["nodes"]["support"]["kind"]["font_size"] == 24.0


@pytest.mark.parametrize(
    "binding", ["font_size_token", "line_height_token", "letter_spacing_token"]
)
@pytest.mark.parametrize("token", ["authored.binding", ""])
def test_explicit_scalar_typography_is_not_reinterpreted_from_old_literals(binding, token) -> None:
    kind = {
        "kind": "text", "content": "Keep this decision", "font_family": "Inter",
        "font_size": 16.0, "font_weight": 400, binding: token,
    }
    kit = {"tokens": {"typography": {"type.body": {"value": {"default": {
        "kind": "style", "font_family": "Inter", "font_size": 16.0,
        "font_weight": 400,
    }}}}}}
    # This pass must not add a competing role or silently repair an unknown
    # token. The actual core resolver remains responsible for token validity.
    assert build_retokenize_operations({"nodes": {"support": {"kind": kind}}}, kit) == []
