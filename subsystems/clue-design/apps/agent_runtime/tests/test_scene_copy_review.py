"""Actual helper exports, not a met checklist, define candidate copy coverage."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from lumen_agent import harness
from lumen_agent.models.schemas import SceneVisualCritique
from lumen_agent.tools import substrate
from lumen_agent.tools.render import _render_preview_text
from test_candidate_finalization_runtime import candidate_graph
from test_scene_direction_review import accept, review, validate, write_direction
from test_scene_direction_review import tools as tools
from test_scene_skill_family import direction


def render(runtime):
    assert json.loads(runtime.preflight_design())["preflight"]["status"] == "ok"
    assert json.loads(runtime.export_preview("svg"))["export"]["status"] == "ok"


def set_text(runtime, text):
    result = json.loads(
        runtime.apply_structured_edit(
            json.dumps(
                {
                    "kind": "modify",
                    "target": {"kind": "node", "id": "actual_headline"},
                    "patch": {
                        "kind": "node",
                        "value": {"text": {"content": {"kind": "set", "value": text}}},
                    },
                }
            )
        )
    )
    assert result["structured_edit"]["status"] == "ok", result
    assert runtime.scene["nodes"]["actual_headline"]["kind"]["content"] == text
    render(runtime)


def add_text(runtime, node_id, text, *, y=None):
    node = copy.deepcopy(runtime.scene["nodes"]["actual_headline"])
    node.update(id=node_id, children=[])
    node["kind"]["content"] = text
    if y is not None:
        node["transform"]["y"] = y
    result = json.loads(
        runtime.apply_operations(
            json.dumps(
                [
                    {
                        "kind": "insert_node",
                        "parent": {"kind": "page", "id": "square"},
                        "index": len(runtime.scene["pages"]["square"]["children"]),
                        "node": node,
                    }
                ]
            )
        )
    )
    assert result["operations"]["status"] == "ok"


def inventory(runtime):
    return json.loads(runtime.inspect("copy_review"))


def submit(runtime, body):
    return json.loads(runtime.submit_visual_critique(json.dumps(body)))


def test_observation_returns_full_native_copy_for_each_exported_page(tools):
    long_text = (
        "Exact punctuation and scope matter: "
        + "every current word remains visible in this inventory. " * 4
    )
    assert (
        json.loads(
            tools.compile_dsl_block(
                "page other size(1080,1080,px)\n"
                '  second text "Second page copy" p(20,20) s(400,80) font_size(17)'
            )
        )["compile"]["status"]
        == "ok"
    )
    set_text(tools, long_text)
    render(tools)
    result = inventory(tools)
    assert result["status"] == "ok"
    assert [(r["page_id"], r["node_id"], r["text"]) for r in result["occurrences"]] == [
        ("other", "second", "Second page copy"),
        ("square", "actual_headline", long_text),
    ]
    assert result["scene_stamp"] == tools._scene_stamp()
    assert result["preview_receipt"]["scene"] == tools._preview_receipt["scene"]
    assert [a["sha256"] for a in result["preview_receipt"]["artifacts"]] == [
        a["sha256"] for a in tools._preview_receipt["artifacts"]
    ]
    assert result["evidence_verified"] is False


@pytest.mark.parametrize("solo", [True, False])
def test_registered_copy_inspect_virtualizes_paths_without_changing_receipt_or_freshness(
    tmp_path, monkeypatch, solo
):
    graph, runtime, _ = candidate_graph(tmp_path, monkeypatch, solo=solo)
    assert json.loads(runtime.compile_dsl_block("page page_test size(1080,1080,px)"))[
        "compile"
    ]["status"] == "ok"
    render(runtime)
    registered_inspect = graph.nodes["tools"].bound.tools_by_name["inspect"]
    original_receipt = copy.deepcopy(runtime._preview_receipt)
    original_export = copy.deepcopy(runtime.latest_export_summary)

    observed = registered_inspect.invoke({"view": "copy_review"})
    assert str(runtime.config.workspace_root) not in observed
    result = json.loads(observed)
    assert result["status"] == "ok"
    assert result["occurrences"][0]["text"] == "Plan"
    assert result["preview_receipt"]["scene"] == original_receipt["scene"]
    for shown, internal in zip(
        result["preview_receipt"]["artifacts"], original_receipt["artifacts"], strict=True
    ):
        assert shown["path"].startswith("/")
        assert (runtime.config.workspace_root / shown["path"].lstrip("/")).resolve() == Path(
            internal["path"]
        ).resolve()
        assert shown["sha256"] == internal["sha256"]
    assert runtime._preview_receipt == original_receipt
    assert runtime.latest_export_summary == original_export
    assert runtime._current_preview_receipt() == original_receipt

    # The public serialization must not weaken byte custody or replace its host paths.
    Path(original_receipt["artifacts"][0]["path"]).write_text("Changed preview bytes")
    stale = json.loads(registered_inspect.invoke({"view": "copy_review"}))
    assert stale["status"] == "unavailable"
    assert "No current preview" in stale["reason"]
    assert runtime._preview_receipt == original_receipt


def test_existing_render_returns_bindable_copy_without_another_observation_call(tools):
    # Exercise the actual agent-visible render, including its reusable bundle path.
    first = _render_preview_text(tools, checkpoint=False)
    assert str(tools.trace_dir) not in first
    assert '"node_id": "actual_headline"' in first
    assert '"text": "Make the next step clear"' in first
    assert '"preview_receipt"' in first
    original_receipt = copy.deepcopy(tools._preview_receipt)
    assert "Native copy review inventory: " + tools.inspect("copy_review") in first
    second = _render_preview_text(tools, checkpoint=False)
    assert str(tools.trace_dir) not in second
    assert '"node_id": "actual_headline"' in second
    assert '"text": "Make the next step clear"' in second
    assert "Native copy review inventory: " + tools.inspect("copy_review") in second
    assert tools._preview_receipt == original_receipt
    assert tools._current_preview_receipt() == original_receipt


@pytest.mark.parametrize(
    "defect",
    [
        "absent_rows",
        "unknown_copy",
        "unknown_node",
        "wrong_page",
        "wrong_text",
        "duplicate_node",
        "missing_support",
        "missing_readability",
        "unsupported",
        "unverified_support",
        "unreadable",
        "unverified_readability",
        "blank_reason",
        "blank_limits",
        "unknown_evidence",
        "supported_without_evidence",
    ],
)
def test_copy_binding_and_judgment_defects_block_whole_acceptance(tools, defect):
    body = review(validate(tools))
    rows = body["direction_review"]["copy_occurrences"]
    row = rows[0]
    if defect == "absent_rows":
        rows.clear()
    elif defect == "unknown_copy":
        row["copy_id"] = "unknown"
    elif defect in {"unknown_node", "wrong_page", "wrong_text"}:
        field = {"unknown_node": "node_id", "wrong_page": "page_id", "wrong_text": "text"}[defect]
        row["fragments"][0][field] = "unknown"
    elif defect == "duplicate_node":
        rows.append(copy.deepcopy(row))
    elif defect.startswith("missing_"):
        row.pop(defect.removeprefix("missing_"))
    elif defect in {"unsupported", "unverified_support", "supported_without_evidence"}:
        row["support"]["status"] = {
            "unverified_support": "unverified",
            "supported_without_evidence": "supported",
        }.get(defect, defect)
    elif defect in {"unreadable", "unverified_readability"}:
        row["readability"]["status"] = (
            "unverified" if defect == "unverified_readability" else defect
        )
    elif defect == "blank_reason":
        row["support"]["reason"] = "  "
    elif defect == "blank_limits":
        row["support"]["source_limits"] = "\n"
    else:
        row["support"]["evidence_refs"] = ["invented"]
    assert submit(tools, body)["status"] == "error"
    assert accept(tools).startswith("REFUSED")


@pytest.mark.parametrize("assessment", ["missing", "null"])
def test_accepted_copy_requires_an_explicit_source_gap_assessment(tools, assessment):
    """A passing label must not bypass assessment of omitted or added meaning."""
    body = review(validate(tools))
    support = body["direction_review"]["copy_occurrences"][0]["support"]
    support.pop("source_gaps", None)
    if assessment == "null":
        support["source_gaps"] = None
    assert submit(tools, body)["status"] == "error"
    assert accept(tools).startswith("REFUSED")


@pytest.mark.parametrize(
    ("text", "claim_kind", "status", "excerpt", "gap"),
    [
        (
            "Comment on the draft before it goes out.", "positioning", "nonfactual",
            "Review controls include Add comment and Approve; no send relationship is shown.",
            {"kind": "added_meaning",
             "reason": "The imperative adds before-send timing absent from the source."},
        ),
        (
            "92%", "statistic", "supported",
            "The pilot's resolution rate went from 56% to 92%.",
            {"kind": "omitted_necessary_context",
             "reason": "The rendered number has no metric, subject or comparison context."},
        ),
        (
            "Available to every team.", "assertion", "supported",
            "Access is limited to invited pilot teams.",
            {"kind": "unresolved_contradiction",
             "reason": "Universal access conflicts with the supplied invitation-only scope."},
        ),
    ],
)
def test_reported_source_gap_cannot_be_overridden_by_passing_copy_status(
    tools, text, claim_kind, status, excerpt, gap,
):
    """Frozen Q failures: matching numbers or imperative grammar waived known gaps.

    These declared judgments test enforcement, not automated semantic inference.
    """
    set_text(tools, text)
    payload = direction()
    payload["copy"][0].update(text=text, claim_kind=claim_kind, evidence_refs=["source"])
    payload["evidence"] = [
        {"id": "source", "source": "Supplied campaign material", "excerpt": excerpt}
    ]
    body = review(validate(tools, payload), text=text)
    body["direction_review"]["copy_occurrences"][0]["support"].update(
        status=status, evidence_refs=["source"],
        reason="The reviewer assigned a passing label despite the recorded gap.",
        source_limits=excerpt, source_gaps=[gap],
    )
    assert submit(tools, body)["status"] == "error"
    assert accept(tools).startswith("REFUSED")
    # The same assessment remains useful in a rejected repair report.
    body["accepted"] = False
    assert submit(tools, body)["status"] == "ok"
    assert accept(tools).startswith("REFUSED")


def test_complete_quantitative_context_can_be_reviewed_across_native_layers(tools):
    """Supplied-assertion scope can pass without pretending it is independently verified."""
    blocks = [
        ("headline", "actual_headline", "Pilot resolution rate", "assertion"),
        ("result", "actual_result", "92%", "statistic"),
        ("comparison", "actual_comparison", "After the pilot, up from 56% before", "assertion"),
    ]
    set_text(tools, blocks[0][2])
    for y, (_, node_id, text, _) in zip((440, 700), blocks[1:], strict=True):
        add_text(tools, node_id, text, y=y)
    render(tools)
    payload = direction()
    payload["copy"] = [
        {"id": copy_id, "role": "support", "text": text,
         "claim_kind": kind, "evidence_refs": ["source"]}
        for copy_id, _, text, kind in blocks
    ]
    payload["evidence"] = [{
        "id": "source", "source": "Supplied campaign statement; author not independently verified",
        "excerpt": "The pilot's resolution rate went from 56% before to 92% after the pilot.",
    }]
    layer = payload["layers"][0]
    payload["layers"] = [dict(layer, id=copy_id, copy_id=copy_id) for copy_id, *_ in blocks]
    result = validate(tools, payload)
    body = review(result)
    rows = []
    for copy_id, node_id, text, _ in blocks:
        row = review(result, node_id=node_id, text=text)["direction_review"]["copy_occurrences"][0]
        row["copy_id"] = copy_id
        row["support"].update(
            status="supported", evidence_refs=["source"], source_gaps=[],
            reason=(
                "Companion layers retain the supplied metric, pilot subject "
                "and before/after comparison."
            ),
            source_limits=(
                "Faithful to the supplied statement; authorship and result "
                "are not independently verified."
            ),
        )
        rows.append(row)
    body["direction_review"]["copy_occurrences"] = rows
    assert submit(tools, body)["status"] == "ok"
    final = json.loads(accept(tools))
    assert final["status"] == "accepted"
    assert final["critique"]["direction_review"]["copy_occurrences"] == rows


@pytest.mark.parametrize("gap", [
    {"kind": "added_meaning", "reason": "  "},
    {"kind": "other", "reason": "A concrete but unclassified concern"},
])
def test_source_gap_requires_a_known_kind_and_concrete_reason(tools, gap):
    body = review(validate(tools))
    body["accepted"] = False
    body["direction_review"]["copy_occurrences"][0]["support"]["source_gaps"] = [gap]
    assert submit(tools, body)["status"] == "error"


def test_history_and_rejected_reviews_can_omit_source_gap_assessment(tools):
    body = review(validate(tools))
    body["direction_review"]["copy_occurrences"][0]["support"].pop("source_gaps")
    historical = SceneVisualCritique.model_validate(body)
    assert historical.direction_review.copy_occurrences[0].support.source_gaps is None
    body["accepted"] = False
    assert submit(tools, body)["status"] == "ok"
    assert accept(tools).startswith("REFUSED")


@pytest.mark.parametrize(
    ("actual", "passes"),
    [
        ("Make the next step clear", True),
        ("Make  the\nnext step\tclear", True),
        ("Make every next step clear", False),
        ("make the next step clear", False),
        ("Make the next step clear!", False),
    ],
)
def test_actual_copy_allows_whitespace_reflow_but_no_changed_words(tools, actual, passes):
    set_text(tools, actual)
    body = review(validate(tools))
    # The review also has to name the current actual text, not invent a match.
    body["direction_review"]["copy_occurrences"][0]["fragments"][0]["text"] = actual
    assert (submit(tools, body)["status"] == "ok") is passes
    assert accept(tools).startswith("REFUSED") is not passes


def test_fragmented_and_repeated_copy_requires_explicit_complete_occurrences(tools):
    set_text(tools, "Make the")
    add_text(tools, "rest", "next step clear")
    add_text(tools, "repeated", "Make the next step clear")
    render(tools)
    body = review(validate(tools))
    rows = body["direction_review"]["copy_occurrences"]
    repeated = copy.deepcopy(rows[0])
    repeated["fragments"][0]["node_id"] = "repeated"
    rows[0]["fragments"][0]["text"] = "Make the"
    rows[0]["fragments"].append(
        {"page_id": "square", "node_id": "rest", "text": "next step clear", "join_before": " "}
    )
    assert submit(tools, body)["status"] == "error"  # repeated placement is unreviewed
    rows.append(repeated)
    assert submit(tools, body)["status"] == "ok"
    assert json.loads(accept(tools))["status"] == "accepted"
    rows[0]["fragments"].reverse()
    assert submit(tools, body)["status"] == "error"


def test_fragments_on_different_pages_do_not_form_one_readable_occurrence(tools):
    assert (
        json.loads(
            tools.compile_dsl_block(
                "page other size(1080,1080,px)\n"
                '  rest text "next step clear" p(20,20) s(400,80) font_size(48)'
            )
        )["compile"]["status"]
        == "ok"
    )
    set_text(tools, "Make the")
    body = review(validate(tools))
    fragments = body["direction_review"]["copy_occurrences"][0]["fragments"]
    fragments[0]["text"] = "Make the"
    fragments.append(
        {"page_id": "other", "node_id": "rest", "text": "next step clear", "join_before": " "}
    )
    assert submit(tools, body)["status"] == "error"
    assert accept(tools).startswith("REFUSED")


def test_extra_native_copy_cannot_hide_after_forty_display_rows(tools):
    for i in range(41):
        add_text(tools, f"extra_{i}", f"Additional {i}")
    render(tools)
    assert len(inventory(tools)["occurrences"]) == 42
    assert submit(tools, review(validate(tools)))["status"] == "error"


def test_empty_native_text_is_not_an_extra_copy_obligation(tools):
    add_text(tools, "empty", "   ")
    render(tools)
    assert [r["node_id"] for r in inventory(tools)["occurrences"]] == ["actual_headline"]
    assert submit(tools, review(validate(tools)))["status"] == "ok"


def test_supported_judgment_must_cite_this_copy_blocks_declared_evidence(tools):
    payload = direction()
    payload["evidence"] = [
        {"id": "declared", "source": "Supplied context", "excerpt": "An author supplied excerpt."},
        {"id": "other", "source": "Other context", "excerpt": "Not declared for this copy."},
    ]
    payload["copy"][0]["evidence_refs"] = ["declared"]
    write_direction(tools, payload)
    result = json.loads(tools.validate_creative_direction())
    body = review(result)
    support = body["direction_review"]["copy_occurrences"][0]["support"]
    support.update(status="supported", evidence_refs=["other"])
    assert submit(tools, body)["status"] == "error"
    support["evidence_refs"] = ["declared"]
    assert submit(tools, body)["status"] == "ok"
    assert json.loads(accept(tools))["status"] == "accepted"
    assert inventory(tools)["evidence_verified"] is False  # identity is not entailment


def test_changed_source_excerpt_invalidates_a_registered_copy_support_review(tools):
    planned = direction()
    planned["evidence"] = [
        {"id": "declared", "source": "Supplied context", "excerpt": "Original supplied note."}
    ]
    planned["copy"][0]["evidence_refs"] = ["declared"]
    first = validate(tools, planned)
    body = review(first)
    assert submit(tools, body)["status"] == "ok"
    assert json.loads(accept(tools))["status"] == "accepted"
    planned["evidence"][0]["excerpt"] = "A different source statement."
    write_direction(tools, planned)
    assert accept(tools).startswith("REFUSED")
    assert json.loads(tools.validate_creative_direction())["status"] == "error"
    revised = json.loads(
        tools.validate_creative_direction(revision_reason="Corrected the source note.")
    )
    assert revised["status"] == "ok"
    assert submit(tools, body)["status"] == "error"
    assert submit(tools, review(revised))["status"] == "ok"
    assert json.loads(accept(tools))["status"] == "accepted"


@pytest.mark.parametrize("change", ["scene", "preview"])
def test_copy_inventory_and_registered_review_do_not_survive_changed_evidence(tools, change):
    assert submit(tools, review(validate(tools)))["status"] == "ok"
    if change == "scene":
        tools.compile_dsl_block("#actual_headline p(160,180)")
    else:
        path = Path(tools.latest_export_summary["artifacts"][0]["path"])
        path.write_text(path.read_text() + "\n")
    assert inventory(tools)["status"] == "unavailable"
    assert accept(tools).startswith("REFUSED")


def test_rejected_copy_review_can_keep_partial_failing_judgments(tools):
    body = review(validate(tools))
    body["accepted"] = False
    body["direction_review"]["checks"] = []
    body["direction_review"]["copy_occurrences"][0]["support"]["status"] = "unverified"
    assert submit(tools, body)["status"] == "ok"
    body["direction_review"]["copy_occurrences"] = []
    assert submit(tools, body)["status"] == "ok"


def test_scoped_edit_can_leave_unrelated_native_copy_without_whole_acceptance(tools, monkeypatch):
    add_text(tools, "unrelated", "Unrelated statement")
    render(tools)
    edited = substrate.LumenDesignTools(
        tools.config, "Move the headline", initial_scene=tools.scene
    )
    outcome = json.loads(
        edited.apply_structured_edit(
            json.dumps(
                {
                    "kind": "modify",
                    "target": {"kind": "node", "id": "actual_headline"},
                    "patch": {"kind": "node", "value": {"opacity": {"kind": "set", "value": 0.9}}},
                    "scope": {
                        "mode": "strict",
                        "allowed": [{"kind": "node", "id": "actual_headline"}],
                    },
                }
            )
        )
    )
    assert outcome["structured_edit"]["status"] == "ok"
    render(edited)
    payload = direction()
    payload["intent"] = "edit"
    write_direction(edited, payload)
    body = review(json.loads(edited.validate_creative_direction()))
    body["direction_review"]["scope"] = "scoped_edit"
    assert submit(edited, body)["status"] == "ok"
    assert accept(edited).startswith("REFUSED")
    result = json.loads(
        edited.finalize_run("edit_applied", "edit_scoped_acceptance", "Applied scoped opacity edit")
    )
    assert result["status"] == "edit_applied"
    assert result["acceptance_receipt"] is None
    assert edited.scene["nodes"]["unrelated"] == tools.scene["nodes"]["unrelated"]
    monkeypatch.setattr(
        harness,
        "create_design_deepagent",
        lambda *_a, **_k: (SimpleNamespace(invoke=lambda *_a, **_k: {}), edited),
    )
    returned, _ = harness.run_deepagent_turn("Scoped edit done", edited.config)
    assert returned["status"] == "edit_applied"
    # A substituted final status cannot promote even a current scoped review.
    substituted = {**result, "status": "accepted", "acceptance_receipt": edited._review_receipt}
    (edited.trace_dir / "final.json").write_text(json.dumps(substituted))
    returned, _ = harness.run_deepagent_turn("Check final scope", edited.config)
    assert returned["status"] == "completed_with_warnings"
    assert returned["stop_reason"] == "acceptance_stale_at_return"
    assert returned["acceptance_receipt"] is None
    body["direction_review"]["scope"] = "whole_creative"
    assert submit(edited, body)["status"] == "error"


def test_edit_intent_on_new_scene_cannot_use_scoped_passing_review(tools):
    payload = direction()
    payload["intent"] = "edit"
    write_direction(tools, payload)
    body = review(json.loads(tools.validate_creative_direction()))
    body["direction_review"]["scope"] = "scoped_edit"
    assert submit(tools, body)["status"] == "error"


@pytest.mark.parametrize("directive", ["opacity(0)", "opacity($opacity.missing)"])
def test_hidden_or_unresolved_opacity_cannot_fulfill_visible_copy(tools, directive):
    assert (
        json.loads(tools.compile_dsl_block(f"#actual_headline {directive}"))["compile"]["status"]
        == "ok"
    )
    render(tools)
    result = inventory(tools)
    if directive == "opacity(0)":
        assert result["occurrences"] == []
        assert result["excluded"][0]["node_id"] == "actual_headline"
    else:
        assert result["occurrences"][0]["observation_issue"] == "unresolved opacity"
    assert submit(tools, review(validate(tools)))["status"] == "error"


def test_rotated_known_copy_is_bindable_when_readability_is_judged_visually(tools):
    assert (
        json.loads(tools.compile_dsl_block("#actual_headline rot(15)"))["compile"]["status"] == "ok"
    )
    render(tools)
    result = inventory(tools)
    assert result["occurrences"][0]["observation_issue"] == "unsupported transform"
    body = review(validate(tools))
    body["direction_review"]["copy_occurrences"][0]["readability"]["reason"] = (
        "Reviewed rotated copy in the full preview and feed proxy; no reliable em metric."
    )
    assert submit(tools, body)["status"] == "ok"
    assert json.loads(accept(tools))["status"] == "accepted"


def test_pinned_native_copy_escapes_hidden_rotated_parent(tools):
    tools.apply_operations(
        json.dumps(
            [
                {
                    "kind": "move_node",
                    "node_id": "actual_headline",
                    "new_parent": {"kind": "node", "id": "panel"},
                    "index": 0,
                }
            ]
        )
    )
    assert (
        json.loads(
            tools.compile_dsl_block(
                "#panel opacity(0) rot(15)\ndetach_to_freehand(actual_headline)"
            )
        )["compile"]["status"]
        == "ok"
    )
    render(tools)
    assert inventory(tools)["occurrences"][0]["node_id"] == "actual_headline"
    assert inventory(tools)["occurrences"][0]["observation_issue"] is None
    assert submit(tools, review(validate(tools)))["status"] == "ok"


def test_unreachable_historical_text_cannot_fulfill_visible_copy(tools):
    # Historical input may contain a node dictionary entry with no reachable
    # page parent. Send that fixture through real preflight/export unchanged.
    historical = copy.deepcopy(tools.scene)
    historical["pages"]["square"]["children"].remove("actual_headline")
    runtime = substrate.LumenDesignTools(
        tools.config, "Review historical scene", initial_scene=historical
    )
    render(runtime)
    assert "actual_headline" in runtime.scene["nodes"]
    assert inventory(runtime)["occurrences"] == []
    assert submit(runtime, review(validate(runtime)))["status"] == "error"


def test_unexpanded_instance_reports_its_limit_without_inventing_text(tools):
    historical = copy.deepcopy(tools.scene)
    instance = copy.deepcopy(historical["nodes"]["panel"])
    instance.update(
        id="copy_instance", kind={"kind": "instance", "source_node_id": "actual_headline"}
    )
    historical["nodes"]["copy_instance"] = instance
    historical["pages"]["square"]["children"].append("copy_instance")
    runtime = substrate.LumenDesignTools(tools.config, "Review instance", initial_scene=historical)
    render(runtime)
    result = inventory(runtime)
    assert result["unresolved"] == [
        {
            "page_id": "square",
            "node_id": "copy_instance",
            "reason": "instance text expansion is unsupported",
        }
    ]
    assert [row["node_id"] for row in result["occurrences"]] == ["actual_headline"]
    assert submit(runtime, review(validate(runtime)))["status"] == "error"
