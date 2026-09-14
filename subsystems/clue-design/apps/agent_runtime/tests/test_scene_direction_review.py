"""Candidate acceptance binds the chosen direction, without certifying visual truth."""

from __future__ import annotations

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
from lumen_agent.models.schemas import VisualCritique
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
        "page square size(1080,1080,px)\n  panel fr p(100,100) s(800,800) fill(#ff0000)"
    ))["compile"]["status"] == "ok"
    assert json.loads(runtime.preflight_design())["preflight"]["status"] == "ok"
    assert json.loads(runtime.export_preview("svg"))["export"]["status"] == "ok"
    return runtime


def write_direction(tools, payload=None, **dump_options):
    path = tools.trace_dir / "workspace/creative-direction.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload or direction(), **dump_options))
    return path


def validate(tools):
    write_direction(tools)
    result = json.loads(tools.validate_creative_direction())
    assert result["status"] == "ok"
    return result


def review(result):
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
            "checks": [
                {"section": item["section"], "index": item["index"],
                 "status": "met", "notes": "Observed this relationship in the current preview."}
                for item in requirements
            ],
        },
    }


def accept(tools):
    return tools.finalize_run("accepted", "review_complete", "Reviewed candidate")


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
