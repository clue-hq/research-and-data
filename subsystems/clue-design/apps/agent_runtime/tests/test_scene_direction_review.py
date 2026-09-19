"""Candidate acceptance binds the chosen direction, without certifying visual truth."""

from __future__ import annotations

import asyncio
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_fixtures import runtime_config
from lumen_agent import harness
from lumen_agent.fs_backend import AgentWorkspaceBackend
from lumen_agent.models.schemas import SceneVisualCritique, VisualCritique
from lumen_agent.tools import substrate
from lumen_api import core as core_module
from test_scene_skill_family import direction

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "target/release/lumen-api-helper"
pytestmark = pytest.mark.skipif(not HELPER.exists(), reason="release helper not built")


@pytest.fixture
def tools(tmp_path, monkeypatch):
    monkeypatch.setattr(core_module.settings, "lumen_core_helper", str(HELPER))
    core = core_module.CoreClient(repo_root=ROOT)
    monkeypatch.setattr(substrate, "CoreClient", lambda **_: core)
    runtime = substrate.LumenDesignTools(
        replace(runtime_config(tmp_path), repo_root=ROOT, scene_skill_bundle="candidate"),
        "Make a square awareness creative",
    )
    assert json.loads(runtime.compile_dsl_block(
        "page square size(1080,1080,px)\n  panel fr p(100,100) s(800,800) fill(#ff0000)\n"
        '  actual_headline text "Make the next step clear" '
        'p(120,180) s(800,240) font_size(48) fill(#ffffff)'
    ))["compile"]["status"] == "ok"
    assert json.loads(runtime.preflight_design())["preflight"]["status"] == "ok"
    assert json.loads(runtime.export_preview("svg"))["export"]["status"] == "ok"
    return runtime


def write_direction(tools, payload=None, **dump_options):
    path = tools.trace_dir / "workspace/creative-direction.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload or direction(), **dump_options))
    return path


def validate(tools, payload=None):
    write_direction(tools, payload)
    result = json.loads(tools.validate_creative_direction())
    assert result["status"] == "ok"
    return result


def review(result, *, page_id="square", node_id="actual_headline", text="Make the next step clear"):
    # The pre-change runtime ignores this whole field; exercise that refusal
    # gap even before it exposes a digest/requirements response.
    requirements = result.get("review_requirements", [
        {"section": section, "index": index}
        for section in ("preserve", "review_needs")
        for index, _ in enumerate(result["direction"][section])
    ])
    return {
        "accepted": True,
        "summary": "Reviewed the current scene against these direction requirements.",
        "direction_review": {
            "direction_digest": result.get("direction_digest", "unbound-before-contract"),
            "scope": "whole_creative",
            "checks": [
                {"section": item["section"], "index": item["index"],
                 "status": "met", "notes": "Observed this relationship in the current preview."}
                for item in requirements
            ],
            "copy_occurrences": [{
                "copy_id": "headline",
                "fragments": [{"page_id": page_id, "node_id": node_id,
                               "text": text, "join_before": ""}],
                "support": {"status": "nonfactual", "evidence_refs": [],
                            "reason": "An invitation with no product performance promise.",
                            "source_limits": "No empirical product claim or source is asserted.",
                            "source_gaps": []},
                "readability": {"status": "readable",
                                "reason": "All words read clearly in preview and feed proxy."},
            }],
        },
    }


def accept(tools):
    return tools.finalize_run("accepted", "review_complete", "Reviewed candidate")


def test_declared_headline_cannot_accept_a_real_render_with_only_a_panel(tools):
    """A self-authored met checklist cannot stand in for absent native copy."""
    tools.apply_operations(json.dumps([{"kind": "remove_node", "node_id": "actual_headline"}]))
    tools.preflight_design()
    tools.export_preview("svg")
    assert "actual_headline" not in tools.scene["nodes"]
    result = validate(tools)
    tools.submit_visual_critique(json.dumps(review(result)))
    assert accept(tools).startswith("REFUSED")


def test_candidate_score_only_review_cannot_accept_without_validated_direction(tools):
    tools.submit_visual_critique(json.dumps({"accepted": True, "summary": "Looks good"}))
    assert accept(tools).startswith("REFUSED")


def test_validated_direction_and_fidelity_score_cannot_replace_direction_coverage(tools):
    validate(tools)
    tools.config = replace(tools.config, reference_assets={"source-ad": {}})
    body = {
        "accepted": True,
        "summary": "The reference looks close enough.",
        "reference_fidelity": {"score": 2},
    }
    # Scene, preflight, preview bytes and a validated direction all exist.
    # The score still does not establish coverage of the declared requirements.
    result = json.loads(tools.submit_visual_critique(json.dumps(body)))
    assert result["status"] == "error"
    assert "direction_review" in result["message"]
    assert accept(tools).startswith("REFUSED")


def test_complete_direction_review_survives_registration_finalizer_and_runner(tools, monkeypatch):
    result = validate(tools)
    assert result["review_requirements"] == [
        {"section": "preserve", "index": 0, "text": "brand type"},
        {"section": "review_needs", "index": 0, "text": "Read the headline at feed size"},
    ]
    body = review(result)
    registered = json.loads(tools.submit_visual_critique(json.dumps(body)))
    assert registered["status"] == "ok"
    assert registered["critique"]["direction_review"] == body["direction_review"]
    final = json.loads(accept(tools))
    assert final["status"] == "accepted"
    assert final["critique"]["direction_review"] == body["direction_review"]
    monkeypatch.setattr(harness, "create_design_deepagent", lambda *a, **k: (
        SimpleNamespace(invoke=lambda *a, **k: {}), tools
    ))
    returned, _ = harness.run_deepagent_turn("Make a creative", tools.config)
    assert returned == final


@pytest.mark.parametrize(
    "defect", ["missing", "duplicate", "unknown", "blank", "deviation", "unverified"]
)
def test_unresolved_or_invalid_direction_coverage_cannot_accept(tools, defect):
    body = review(validate(tools))
    rows = body["direction_review"]["checks"]
    if defect == "missing":
        rows.pop()
    elif defect == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif defect == "unknown":
        rows[0]["index"] = 999
    elif defect == "blank":
        rows[0]["notes"] = " \n "
    else:
        rows[0]["status"] = defect
    tools.submit_visual_critique(json.dumps(body))
    assert accept(tools).startswith("REFUSED")


def test_rejected_review_remains_useful_without_complete_direction_coverage(tools):
    body = {"accepted": False, "summary": "The headline is not readable; repair its measure."}
    registered = json.loads(tools.submit_visual_critique(json.dumps(body)))
    assert registered["status"] == "ok"
    assert registered["critique"]["summary"] == body["summary"]
    draft = json.loads(tools.finalize_run("completed_with_warnings", "review_rejected", "Draft"))
    assert draft["status"] == "completed_with_warnings"


def test_canonical_whitespace_and_key_order_do_not_stale_review(tools):
    first = validate(tools)
    assert json.loads(tools.submit_visual_critique(json.dumps(review(first))))["status"] == "ok"
    write_direction(tools, indent=4, sort_keys=True)
    second = json.loads(tools.validate_creative_direction())
    assert second["direction_digest"] == first["direction_digest"]
    assert json.loads(accept(tools))["status"] == "accepted"


def test_semantic_revision_requires_reason_and_a_new_review(tools):
    first = validate(tools)
    assert json.loads(tools.submit_visual_critique(json.dumps(review(first))))["status"] == "ok"
    revised = direction()
    revised["preserve"] = ["Supported lighter treatment"]
    write_direction(tools, revised)
    assert accept(tools).startswith("REFUSED")
    assert json.loads(tools.validate_creative_direction())["status"] == "error"
    second = json.loads(tools.validate_creative_direction(
        revision_reason="Choose the lighter treatment to preserve contrast for the requested copy."
    ))
    assert second["status"] == "ok"
    assert second["direction_digest"] != first["direction_digest"]
    assert accept(tools).startswith("REFUSED")
    assert json.loads(tools.submit_visual_critique(json.dumps(review(second))))["status"] == "ok"
    assert json.loads(accept(tools))["status"] == "accepted"
    events = [
        json.loads(line) for line in (tools.trace_dir / "trace.jsonl").read_text().splitlines()
    ]
    event = [e for e in events if e["event"] == "creative_direction_validated"][-1]
    assert event["payload"]["previous_direction_digest"] == first["direction_digest"]
    assert event["payload"]["direction_digest"] == second["direction_digest"]
    assert "lighter treatment" in event["payload"]["revision_reason"]


def test_runner_downgrades_direction_change_after_finalization(tools, monkeypatch):
    body = review(validate(tools))
    tools.submit_visual_critique(json.dumps(body))
    assert json.loads(accept(tools))["status"] == "accepted"
    revised = direction()
    revised["review_needs"].append("Review the new product relationship")
    write_direction(tools, revised)
    monkeypatch.setattr(harness, "create_design_deepagent", lambda *a, **k: (
        SimpleNamespace(invoke=lambda *a, **k: {}), tools
    ))
    result, _ = harness.run_deepagent_turn("Review the new direction", tools.config)
    assert result["status"] == "completed_with_warnings"
    assert result["stop_reason"] == "acceptance_stale_at_return"
    assert result["acceptance_receipt"] is None


def test_new_runtime_requires_revalidation_even_if_old_direction_file_is_copied(tools):
    validated = validate(tools)
    other = substrate.LumenDesignTools(tools.config, "Restart attempt", initial_scene=tools.scene)
    write_direction(other)
    other.preflight_design()
    other.export_preview("svg")
    other.submit_visual_critique(json.dumps(review(validated)))
    assert accept(other).startswith("REFUSED")
    assert json.loads(other.validate_creative_direction())["status"] == "ok"


def test_legacy_review_serialization_and_acceptance_are_unchanged(tools):
    tools.config = replace(tools.config, scene_skill_bundle="legacy")
    body = {"accepted": True, "summary": "Legacy reviewed fixture"}
    registered = json.loads(tools.submit_visual_critique(json.dumps(body)))
    assert registered["critique"] == VisualCritique.model_validate(body).model_dump(mode="json")
    assert "direction_review" not in registered["critique"]
    assert json.loads(accept(tools))["status"] == "accepted"


def test_direction_validation_contends_with_scene_review_transaction(tools, monkeypatch):
    """A stale critique cannot be registered as a newer direction's review."""
    first = validate(tools)
    body = review(first)
    entered, release = threading.Event(), threading.Event()
    original_write = tools._write_json

    def paused_write(path, value):
        if path.name == "critique.json":
            entered.set()
            assert release.wait(10)
        return original_write(path, value)

    monkeypatch.setattr(tools, "_write_json", paused_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        submission = pool.submit(tools.submit_visual_critique, json.dumps(body))
        try:
            assert entered.wait(5)
            assert not tools._scene_mutation_lock.acquire(blocking=False)
            revised = direction()
            revised["review_needs"] = ["A different review decision"]
            write_direction(tools, revised)
            revision = pool.submit(tools.validate_creative_direction, "Changed review decision")
        finally:
            release.set()
        assert json.loads(submission.result(5))["status"] == "ok"
        assert json.loads(revision.result(5))["status"] == "ok"
    assert accept(tools).startswith("REFUSED")


def review_backend(tools):
    tools.config = replace(tools.config, reference_assets={"source-ad": {}})
    return AgentWorkspaceBackend(
        tools.trace_dir.parent,
        active_run_id=tools.run_id,
        reference_turn=True,
        critique_observer=tools.observe_written_critique,
    )


@pytest.mark.parametrize("operation", ["write", "edit", "awrite", "aedit"])
@pytest.mark.parametrize("defect", ["undeclared_evidence", "duplicate_binding"])
def test_file_review_rejection_reports_the_registration_error_and_allows_repair(
    tools, operation, defect,
):
    """A saved critique must expose the real rejection before finalize is called."""
    body = review(validate(tools))
    body["reference_fidelity"] = {"score": 2}
    broken = copy.deepcopy(body)
    if defect == "undeclared_evidence":
        support = broken["direction_review"]["copy_occurrences"][0]["support"]
        support.update(status="supported", evidence_refs=["undeclared-evidence"])
        # Conduit's failure: schema-valid fidelity=2, but the direction join fails.
        assert SceneVisualCritique.model_validate(broken).reference_fidelity.score == 2
        reason = "Copy headline cites evidence not declared for that copy block."
    else:
        # Clue's failure: the same native placement is reviewed twice.
        rows = broken["direction_review"]["copy_occurrences"]
        rows.append(copy.deepcopy(rows[0]))
        reason = "duplicate native copy binding"
    backend = review_backend(tools)
    path = tools.trace_dir / "workspace/rounds/round_2/critique.json"
    key = f"/{tools.run_id}/workspace/rounds/round_2/critique.json"
    if operation in {"edit", "aedit"}:
        assert backend.write(key, json.dumps(body)).error is None
        assert json.loads(accept(tools))["status"] == "accepted"
        args = (str(path), path.read_text(), json.dumps(broken))
    else:
        args = (key, json.dumps(broken))
    result = getattr(backend, operation)(*args)
    if operation.startswith("a"):
        result = asyncio.run(result)

    assert json.loads(path.read_text()) == broken
    assert tools._latest_visual_critique is None
    assert tools._review_receipt is None
    assert accept(tools).startswith("REFUSED")
    assert result.error and reason in result.error
    assert "saved" in result.error.lower() and "not registered" in result.error.lower()
    assert "edit" in result.error.lower()

    # Inline passing JSON cannot resurrect the invalidated registration.
    assert tools.finalize_run(
        "accepted", "review_complete", "Unregistered", json.dumps(body),
    ).startswith("REFUSED")
    repaired = backend.edit(key, path.read_text(), json.dumps(body))
    assert repaired.error is None and repaired.occurrences == 1
    final = json.loads(accept(tools))
    assert final["status"] == "accepted"
    assert final["critique"]["reference_fidelity"]["score"] == 2


@pytest.mark.parametrize("defect", ["negative", "malformed", "low_fidelity"])
def test_file_review_cannot_keep_an_earlier_passing_registration(tools, defect):
    body = review(validate(tools))
    body["reference_fidelity"] = {"score": 2}
    backend = review_backend(tools)
    path = tools.trace_dir / "workspace/critique.json"
    assert backend.write(str(path), json.dumps(body)).error is None
    assert json.loads(accept(tools))["status"] == "accepted"
    if defect == "negative":
        body["accepted"] = False
    elif defect == "low_fidelity":
        body["reference_fidelity"]["score"] = 1
    content = "{invalid json" if defect == "malformed" else json.dumps(body)
    result = backend.edit(str(path), path.read_text(), content)
    assert path.read_text() == content
    assert accept(tools).startswith("REFUSED")
    if defect == "malformed":
        assert result.error and "not registered" in result.error.lower()
        assert tools._latest_visual_critique is None
    else:
        # A negative judgment is valid review data, but cannot authorize acceptance.
        assert result.error is None


@pytest.mark.parametrize("path_kind", ["sibling_run", "old_round", "wrong_path"])
def test_file_review_registration_preserves_current_run_and_round_binding(tools, path_kind):
    body = review(validate(tools))
    body["reference_fidelity"] = {"score": 2}
    backend = review_backend(tools)
    (tools.trace_dir / "workspace/rounds/round_2").mkdir(parents=True)
    key = {
        "sibling_run": "/run_other/workspace/rounds/round_2/critique.json",
        "old_round": f"/{tools.run_id}/workspace/rounds/round_1/critique.json",
        "wrong_path": f"/{tools.run_id}/workspace/critique.json",
    }[path_kind]
    result = backend.write(key, json.dumps(body))
    assert bool(result.error) == (path_kind == "sibling_run")
    assert tools._latest_visual_critique is None
    assert accept(tools).startswith("REFUSED")


@pytest.mark.parametrize("changed", ["scene", "direction", "preview"])
def test_file_review_registration_does_not_bypass_evidence_freshness(tools, changed):
    body = review(validate(tools))
    body["reference_fidelity"] = {"score": 2}
    backend = review_backend(tools)
    path = tools.trace_dir / "workspace/critique.json"
    assert backend.write(str(path), json.dumps(body)).error is None
    assert json.loads(accept(tools))["status"] == "accepted"
    if changed == "scene":
        tools.apply_operations(json.dumps([{"kind": "remove_node", "node_id": "panel"}]))
        tools.preflight_design()
        tools.export_preview("svg")
    elif changed == "direction":
        revised = direction()
        revised["review_needs"].append("Check another requirement")
        write_direction(tools, revised)
    else:
        Path(tools.latest_export_summary["artifacts"][0]["path"]).write_text("changed bytes")
    assert accept(tools).startswith("REFUSED")
