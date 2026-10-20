"""Caller-selected compact display review rejects tiny native copy, not visual taste."""

import copy
import json
import math

import pytest
from lumen_agent import materialize, native_copy
from lumen_agent.tools import substrate
from pydantic import ValidationError
from test_scene_copy_review import add_text, inventory, render, set_text, submit
from test_scene_direction_review import accept, review, validate
from test_scene_direction_review import tools as tools
from test_scene_preview_text_metrics import scene_runtime as scene_runtime
from test_scene_skill_family import direction


@pytest.mark.parametrize("selector", ["", "compact-feed-v1", " compact-feed-v1 "])
def test_documented_profile_env_reaches_runtime_config(monkeypatch, tmp_path, selector):
    from lumen_agent import config as runtime_config_module
    from py_lumen_config.config import Settings

    monkeypatch.setenv("LUMEN_AGENT_SCENE_REVIEW_PROFILE", selector)
    parsed = Settings(_env_file=None)
    monkeypatch.setattr(runtime_config_module, "settings", parsed)
    configured = runtime_config_module.AgentRuntimeConfig.from_env(tmp_path)
    assert configured.scene_review_profile == selector.strip()


def test_absent_profile_env_defaults_off(monkeypatch, tmp_path):
    from lumen_agent import config as runtime_config_module
    from py_lumen_config.config import Settings

    monkeypatch.delenv("LUMEN_AGENT_SCENE_REVIEW_PROFILE", raising=False)
    parsed = Settings(_env_file=None)
    monkeypatch.setattr(runtime_config_module, "settings", parsed)
    assert runtime_config_module.AgentRuntimeConfig.from_env(tmp_path).scene_review_profile == ""


@pytest.mark.parametrize(("profile", "minimum", "size", "passes"), [
    ("compact-feed-v1", 8, 21, False),
    ("compact-feed-v1", 8, 23.999, False),
    ("compact-feed-v1", 8, 24, True),
    ("compact-feed-v1", 8, 32, True),
    ("legible-feed-v1", 10, 25, False),
    ("legible-feed-v1", 10, 29.999, False),
    ("legible-feed-v1", 10, 30, True),
    ("legible-feed-v1", 10, 32, True),
])
def test_selected_profile_checks_support_at_its_documented_floor(tools, profile, minimum, size, passes):
    object.__setattr__(tools.config, "scene_review_profile", profile)
    deliver_profile(tools)
    add_text(tools, "support", "Explore the possibilities", y=480)
    assert json.loads(tools.compile_dsl_block(f"#support font_size({size})"))["compile"][
        "status"
    ] == "ok"
    render(tools)
    planned = direction()
    planned["copy"].append({
        "id": "support", "role": "support", "text": "Explore the possibilities",
        "claim_kind": "positioning", "evidence_refs": [],
    })
    planned["layers"].append({
        "id": "support", "kind": "native_text", "copy_id": "support",
        "purpose": "A supporting invitation below the headline",
        "placement": {"x": 0.1, "y": 0.45, "width": 0.8, "height": 0.1},
    })
    validated = validate(tools, planned)
    body = review(validated)
    supporting = copy.deepcopy(body["direction_review"]["copy_occurrences"][0])
    supporting["copy_id"] = "support"
    supporting["fragments"][0].update(node_id="support", text="Explore the possibilities")
    body["direction_review"]["copy_occurrences"].append(supporting)

    assert supporting["readability"]["status"] == "readable"
    assert (submit(tools, body)["status"] == "ok") is passes
    if passes:
        result = json.loads(accept(tools))
        assert result["status"] == "accepted"
        assert result["acceptance_receipt"]["native_copy_review_profile"] == {
            "id": profile, "display_width_px": 360, "minimum_nominal_em_px": minimum,
        }
    else:
        assert accept(tools).startswith("REFUSED")


def test_selected_profile_is_delivered_in_initial_workspace_gather(tools):
    from lumen_agent.fs_backend import AgentWorkspaceBackend
    from lumen_agent.workspace import scaffold_workspace

    # Use the existing profile to isolate early delivery from adding a new profile.
    enable_profile(tools)
    descriptor = deliver_profile(tools)
    manifest = json.loads(descriptor.read_text())
    manifest["review_profiles"]["compact-feed-v1"]["minimum_nominal_em_px"] = 11
    descriptor.write_text(json.dumps(manifest))
    workspace = scaffold_workspace(tools, "Make a square ad")
    backend = AgentWorkspaceBackend(tools.config.workspace_root, active_run_id=tools.run_id)
    state, brief = backend.download_files([
        f"/{tools.run_id}/workspace/state.json", f"/{tools.run_id}/workspace/brief.md",
    ])
    assert state.error is None and brief.error is None
    assert json.loads(state.content)["native_copy_review_profile"] == {
        "id": "compact-feed-v1", "display_width_px": 360, "minimum_nominal_em_px": 11,
    }
    # Harness alignment I9 (founder ruling 2026-10-17): the selected values reach the agent once,
    # in the system prompt written from the same delivered profile; the brief no longer repeats them.
    assert "compact-feed-v1" not in brief.content.decode()
    from lumen_agent.prompts import build_scene_solo_prompt

    prompt = " ".join(build_scene_solo_prompt(
        "/w", review_profile=tools._native_copy_review_profile()
    ).split())
    assert "at least 11px when the ad is shown 360px wide" in prompt
    assert workspace == tools.trace_dir / "workspace"


@pytest.mark.parametrize(("bundle", "profile"), [("candidate", ""), ("legacy", "unknown")])
def test_initial_workspace_does_not_add_an_unselected_profile(tools, bundle, profile):
    from lumen_agent.workspace import scaffold_workspace

    object.__setattr__(tools.config, "scene_skill_bundle", bundle)
    object.__setattr__(tools.config, "scene_review_profile", profile)
    workspace = scaffold_workspace(tools, "Make a square ad")
    assert "native_copy_review_profile" not in json.loads((workspace / "state.json").read_text())
    assert (workspace / "brief.md").read_text() == (
        f"# Design turn brief — run {tools.run_id}\n\nMake a square ad"
    )


def measure(scene, page_id="square", row=None, display_width=360):
    if row is None:
        row = native_copy.observe_native_text(scene, page_id)["occurrences"][0]
    function = getattr(native_copy, "native_nominal_em_at_width", None)
    assert callable(function), "the shared nominal-em measurement is not implemented"
    return function(scene, page_id, row, display_width)


def enable_profile(runtime):
    # RunConfig is frozen; this also exercises the missing-policy RED before
    # the caller-owned field lands, without changing the direction or scene.
    object.__setattr__(runtime.config, "scene_review_profile", "compact-feed-v1")


def test_compact_profile_rejects_tiny_native_copy_despite_readable_judgment(tools):
    enable_profile(tools)
    assert (
        json.loads(tools.compile_dsl_block("#actual_headline font_size(17)"))["compile"]["status"]
        == "ok"
    )
    render(tools)
    body = review(validate(tools))
    assert body["direction_review"]["copy_occurrences"][0]["readability"]["status"] == "readable"

    assert submit(tools, body)["status"] == "error"
    assert accept(tools).startswith("REFUSED")


@pytest.mark.parametrize(("size", "passes"), [(23.999, False), (24, True), (24.001, True)])
def test_minimum_uses_unrounded_nominal_size_and_includes_the_boundary(tools, size, passes):
    enable_profile(tools)
    assert (
        json.loads(tools.compile_dsl_block(f"#actual_headline font_size({size})"))["compile"][
            "status"
        ]
        == "ok"
    )
    render(tools)
    observed = inventory(tools)
    assert observed["review_profile"]["id"] == "compact-feed-v1"
    measurement = observed["occurrences"][0]["nominal_size_review"]
    assert measurement["status"] == "ok"
    assert measurement["passes_minimum"] is passes
    assert (measurement["nominal_em_px"] >= 8) is passes
    assert (submit(tools, review(validate(tools)))["status"] == "ok") is passes
    assert accept(tools).startswith("REFUSED") is not passes


@pytest.mark.parametrize("directive", ["rot(0.01)", "rot(90)", "skew(35,0)"])
def test_transform_cannot_exempt_tiny_nominal_type(tools, directive):
    enable_profile(tools)
    assert (
        json.loads(tools.compile_dsl_block(f"#actual_headline font_size(17) {directive}"))[
            "compile"
        ]["status"]
        == "ok"
    )
    render(tools)
    row = inventory(tools)["occurrences"][0]
    assert row["observation_issue"] == "unsupported transform"
    assert row["nominal_size_review"]["nominal_em_px"] == pytest.approx(5.666666666666667)
    assert submit(tools, review(validate(tools)))["status"] == "error"


@pytest.mark.parametrize("tiny_node", ["actual_headline", "rest"])
def test_each_fragment_must_satisfy_the_profile(tools, tiny_node):
    enable_profile(tools)
    set_text(tools, "Make the")
    add_text(tools, "rest", "next step clear")
    assert (
        json.loads(tools.compile_dsl_block(f"#{tiny_node} font_size(17)"))["compile"]["status"]
        == "ok"
    )
    render(tools)
    body = review(validate(tools))
    fragments = body["direction_review"]["copy_occurrences"][0]["fragments"]
    fragments[0]["text"] = "Make the"
    fragments.append(
        {"page_id": "square", "node_id": "rest", "text": "next step clear", "join_before": " "}
    )
    assert submit(tools, body)["status"] == "error"
    assert accept(tools).startswith("REFUSED")


def test_tiny_copy_after_the_display_table_cap_still_blocks_acceptance(tools):
    enable_profile(tools)
    for index in range(41):
        add_text(tools, f"repeat_{index}", "Make the next step clear")
    assert (
        json.loads(tools.compile_dsl_block("#repeat_40 font_size(17)"))["compile"]["status"] == "ok"
    )
    render(tools)
    body = review(validate(tools))
    occurrences = body["direction_review"]["copy_occurrences"]
    for index in range(41):
        repeated = copy.deepcopy(occurrences[0])
        repeated["fragments"][0]["node_id"] = f"repeat_{index}"
        occurrences.append(repeated)
    rows = inventory(tools)["occurrences"]
    assert len(rows) == 42
    assert rows[-1]["node_id"] == "repeat_40"
    assert rows[-1]["nominal_size_review"]["passes_minimum"] is False
    assert submit(tools, body)["status"] == "error"


def test_pixel_units_do_not_enable_a_profile_for_the_caller(tools):
    assert (
        json.loads(tools.compile_dsl_block("#actual_headline font_size(17)"))["compile"]["status"]
        == "ok"
    )
    render(tools)
    observed = inventory(tools)
    assert not observed.get("review_profile")
    assert "nominal_size_review" not in observed["occurrences"][0]
    assert submit(tools, review(validate(tools)))["status"] == "ok"
    assert json.loads(accept(tools))["status"] == "accepted"


def test_profile_does_not_reject_a_scoped_user_edit_for_unchanged_tiny_type(tools):
    enable_profile(tools)
    assert (
        json.loads(tools.compile_dsl_block("#actual_headline font_size(17)"))["compile"]["status"]
        == "ok"
    )
    render(tools)
    edited = substrate.LumenDesignTools(
        tools.config, "Move the headline", initial_scene=tools.scene
    )
    assert (
        json.loads(edited.compile_dsl_block("#actual_headline p(140,180)"))["compile"]["status"]
        == "ok"
    )
    render(edited)
    planned = direction()
    planned["intent"] = "edit"
    body = review(validate(edited, planned))
    body["direction_review"]["scope"] = "scoped_edit"
    assert submit(edited, body)["status"] == "ok"
    result = json.loads(
        edited.finalize_run("edit_applied", "edit_scoped_acceptance", "Moved headline")
    )
    assert result["status"] == "edit_applied"
    assert result["acceptance_receipt"] is None


@pytest.mark.parametrize(
    ("page", "size", "expected"),
    [
        ("size(1080,1080,px)", 17, 5.666666666666667),
        ("size(1080,1080,px)", 24, 8),
        ("size(2160,1080,px)", 48, 8),
        ("size(1080,1920,px)", 17, 5.666666666666667),
        ("size(1200,628,px)", 17, 5.1),
        ("size(254,127,mm)", 17, 8.5),
        ("size(10,5,in)", 17, 8.5),
    ],
)
def test_nominal_measurement_uses_canonical_width_not_authored_units_or_proxy_rounding(
    scene_runtime,
    page,
    size,
    expected,
):
    runtime, _ = scene_runtime(
        f"page square {page}\n"
        f'  text text "Readable invitation" p(20,20) s(400,80) font_size({size})'
    )
    assert runtime.scene["pages"]["square"]["size"]["unit"] == "pt"
    assert not getattr(runtime.config, "scene_review_profile", "")
    before = copy.deepcopy(runtime.scene)
    result = measure(runtime.scene)
    assert result["status"] == "ok"
    assert result["nominal_em_px"] == pytest.approx(expected)
    assert result.get("reason") is None
    assert runtime.scene == before


def test_untransformed_metric_keeps_pinned_ancestor_visibility_rules(scene_runtime):
    runtime, _ = scene_runtime("""page square size(1080,1080,px)
  parent fr p(20,20) s(500,200) opacity(0) rot(15)
    text text "Pinned invitation" s(400,80) font_size(17)
""")
    assert native_copy.observe_native_text(runtime.scene, "square")["occurrences"] == []
    assert (
        json.loads(runtime.compile_dsl_block("detach_to_freehand(text)"))["compile"]["status"]
        == "ok"
    )
    render(runtime)
    assert measure(runtime.scene)["nominal_em_px"] == pytest.approx(5.666666666666667)


@pytest.mark.parametrize(
    "directive", ["font_size($type.size.missing)", "opacity($opacity.missing)"]
)
def test_unresolved_source_typography_or_opacity_has_no_nominal_measurement(
    scene_runtime, directive
):
    runtime, _ = scene_runtime(
        "page square size(1080,1080,px)\n"
        f'  text text "Unresolved invitation" p(20,20) s(400,80) {directive}'
    )
    result = measure(runtime.scene)
    assert result["status"] == "unavailable"
    assert result.get("nominal_em_px") is None
    assert result.get("reason")


def test_rotated_unresolved_parent_opacity_is_not_a_measurement_escape(scene_runtime):
    runtime, _ = scene_runtime("""page square size(1080,1080,px)
  parent fr p(20,20) s(500,200) opacity($opacity.missing) rot(15)
    text text "Unknown visibility" s(400,80) font_size(17)
""")
    row = native_copy.observe_native_text(runtime.scene, "square")["occurrences"][0]
    assert row["binding_issue"] == "unresolved opacity"
    result = measure(runtime.scene, row=row)
    assert result["status"] == "unavailable"
    assert result["reason"] == "unresolved opacity"


@pytest.mark.parametrize("invalid", [None, True, 0, -1, math.nan, math.inf, "17"])
def test_invalid_native_size_is_not_measured_from_a_row_fallback(tools, invalid):
    # Malformed imported data exercises the pure boundary only; it is never
    # installed into a runtime or submitted to the engine as a successful scene.
    source = copy.deepcopy(tools.scene)
    row = native_copy.observe_native_text(source, "square")["occurrences"][0]
    source["nodes"][row["node_id"]]["kind"]["font_size"] = invalid
    result = measure(source, row=row)
    assert result["status"] == "unavailable"
    assert result.get("nominal_em_px") is None


@pytest.mark.parametrize(
    ("axis", "invalid"),
    [("width", 0), ("height", -1), ("width", True), ("height", math.inf), ("width", None)],
)
def test_invalid_page_dimensions_never_gain_a_nominal_measurement(tools, axis, invalid):
    source = copy.deepcopy(tools.scene)
    source["pages"]["square"]["size"][axis] = invalid
    assert measure(source)["status"] == "unavailable"


@pytest.mark.parametrize("unit", [None, "px", "mm", "in"])
def test_uncanonical_imported_units_are_not_reinterpreted(tools, unit):
    source = copy.deepcopy(tools.scene)
    source["pages"]["square"]["size"]["unit"] = unit
    assert measure(source)["status"] == "unavailable"


@pytest.mark.parametrize("invalid", [None, True, 0, -1, math.nan, math.inf, "360"])
def test_invalid_display_width_is_unavailable(tools, invalid):
    assert measure(tools.scene, display_width=invalid)["status"] == "unavailable"


@pytest.mark.parametrize("field", ["display_width_px", "minimum_nominal_em_px"])
@pytest.mark.parametrize("invalid", [None, True, 0, -1, math.nan, math.inf, "8"])
def test_profile_rejects_invalid_or_coerced_policy_numbers(field, invalid):
    model = getattr(native_copy, "NativeCopyReviewProfile", None)
    assert model is not None, "shared policy validation is not implemented"
    data = {"display_width_px": 360, "minimum_nominal_em_px": 8, field: invalid}
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_profile_is_frozen_and_rejects_unknown_policy_fields():
    model = getattr(native_copy, "NativeCopyReviewProfile", None)
    assert model is not None, "shared policy validation is not implemented"
    data = {"display_width_px": 360, "minimum_nominal_em_px": 8}
    profile = model.model_validate(data)
    with pytest.raises(ValidationError):
        profile.minimum_nominal_em_px = 1
    with pytest.raises(ValidationError):
        model.model_validate({**data, "exempt_roles": ["attribution"]})


def deliver_profile(runtime):
    materialize.materialize_agent_workspace(runtime.config, knowledge_view="scene")
    return runtime.config.workspace_root / ".deepagent/knowledge-view.json"


def test_selected_delivered_profile_is_bound_in_direction_and_acceptance(tools):
    enable_profile(tools)
    deliver_profile(tools)
    validated = validate(tools)
    expected = {
        "id": "compact-feed-v1",
        "display_width_px": 360,
        "minimum_nominal_em_px": 8,
    }
    assert validated["native_copy_review_profile"] == expected
    assert submit(tools, review(validated))["status"] == "ok"
    final = json.loads(accept(tools))
    assert final["status"] == "accepted"
    assert final["acceptance_receipt"]["native_copy_review_profile"] == expected


@pytest.mark.parametrize("change", ["remove", "different_profile", "width", "minimum"])
def test_profile_changes_stale_acceptance_even_when_copy_still_exceeds_the_floor(tools, change):
    enable_profile(tools)
    descriptor = deliver_profile(tools)
    manifest = json.loads(descriptor.read_text())
    manifest["review_profiles"]["alternate-feed-v1"] = {
        "display_width_px": 400,
        "minimum_nominal_em_px": 9,
    }
    descriptor.write_text(json.dumps(manifest))
    assert submit(tools, review(validate(tools)))["status"] == "ok"
    assert json.loads(accept(tools))["status"] == "accepted"
    scene, preview = copy.deepcopy(tools.scene), copy.deepcopy(tools._preview_receipt)

    if change == "remove":
        object.__setattr__(tools.config, "scene_review_profile", "")
    elif change == "different_profile":
        object.__setattr__(tools.config, "scene_review_profile", "alternate-feed-v1")
    else:
        key, value = (
            ("display_width_px", 480) if change == "width" else ("minimum_nominal_em_px", 9)
        )
        manifest["review_profiles"]["compact-feed-v1"][key] = value
        descriptor.write_text(json.dumps(manifest))

    observed = inventory(tools)
    assert observed["status"] == "ok"
    if change != "remove":
        assert all(row["nominal_size_review"]["passes_minimum"] for row in observed["occurrences"])
    assert tools.scene == scene and tools._preview_receipt == preview
    assert accept(tools).startswith("REFUSED")


@pytest.mark.parametrize(
    "defect",
    ["missing_profile", "bad_number", "unknown_id", "invalid_json", "bad_table", "bad_root"],
)
def test_invalid_delivered_profile_never_falls_back_to_authored_policy(tools, defect):
    enable_profile(tools)
    descriptor = deliver_profile(tools)
    body = review(validate(tools))
    manifest = json.loads(descriptor.read_text())
    if defect == "missing_profile":
        manifest["review_profiles"] = {}
    elif defect == "bad_number":
        manifest["review_profiles"]["compact-feed-v1"]["minimum_nominal_em_px"] = 0
    elif defect == "unknown_id":
        object.__setattr__(tools.config, "scene_review_profile", "unknown-profile")
    elif defect == "bad_table":
        manifest["review_profiles"] = ["compact-feed-v1"]
    elif defect == "bad_root":
        manifest = []
    descriptor.write_text("{" if defect == "invalid_json" else json.dumps(manifest))

    assert inventory(tools)["status"] == "unavailable"
    assert json.loads(tools.validate_creative_direction())["status"] == "error"
    assert submit(tools, body)["status"] == "error"
    assert accept(tools).startswith("REFUSED")


def test_legacy_ignores_a_configured_compact_profile(tools):
    object.__setattr__(tools.config, "scene_review_profile", "unknown-profile")
    object.__setattr__(tools.config, "scene_skill_bundle", "legacy")
    assert (
        json.loads(tools.compile_dsl_block("#actual_headline font_size(17)"))["compile"]["status"]
        == "ok"
    )
    render(tools)
    assert (
        submit(tools, {"accepted": True, "summary": "Legacy review is unchanged."})["status"]
        == "ok"
    )
    final = json.loads(accept(tools))
    assert final["status"] == "accepted"
    assert "native_copy_review_profile" not in final["acceptance_receipt"]
