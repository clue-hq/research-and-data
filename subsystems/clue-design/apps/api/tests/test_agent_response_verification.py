"""Current draft diagnostics must not inherit repaired attempt failures."""

from __future__ import annotations

import json

from lumen_api.main import agent_response_from_trace


def _trace(tmp_path):
    failed = tmp_path / "iterations" / "001"
    failed.mkdir(parents=True)
    (failed / "compile.json").write_text(json.dumps({
        "compile": {"status": "error", "diagnostics": [{
            "severity": "error", "code": "dsl.unsupported_property",
            "message": "unsupported property syntax text",
        }]}, "operations": [],
    }))
    repaired = tmp_path / "iterations" / "002"
    repaired.mkdir()
    (repaired / "compile.json").write_text(json.dumps({
        "compile": {"status": "ok", "diagnostics": []},
        "operations": [{"kind": "set_node_name", "node_id": "hero", "name": "Repaired"}],
    }))


def _result(*, review_status="current", blocked=False):
    return {
        "status": "completed_with_warnings",
        "stop_reason": "budget_exhausted_wall_clock",
        "summary": "Current scene cannot export: radius.pill is unresolved.",
        "critique": {"accepted": False, "summary": "Current scene cannot export.", "issues": [{
            "message": "radius.pill is unresolved.", "severity": "error",
        }]},
        "draft_verification": {
            "scene_stamp": "repaired-scene",
            "preflight": {"status": "current", "scene_stamp": "repaired-scene", "iteration": 2,
                          "has_blocking_errors": blocked, "diagnostics": ([{
                              "severity": "error", "code": "LUMB0301", "message": "Undefined radius token.",
                          }] if blocked else [])},
            "preview": {"status": "missing" if blocked else "current", "scene_stamp": None, "iteration": None},
            "review": {"status": review_status, "scene_stamp": "old-scene", "iteration": 1},
        },
    }


def test_repaired_compile_errors_are_attributed_history_not_current_diagnostics(tmp_path):
    _trace(tmp_path)
    result = _result()
    result["critique"] = {"accepted": False, "summary": "Spacing needs work.", "issues": []}

    response = agent_response_from_trace(result, tmp_path)

    assert response["diagnostics"] == []
    assert response["diagnostic_history"][0]["iteration"] == 1
    assert response["diagnostic_history"][0]["phase"] == "dsl"
    assert response["diagnostic_history"][0]["diagnostics"][0]["message"] == "unsupported property syntax text"
    assert response["status"] == "proposed"
    assert response["acceptance_scope"] is None
    assert response["operations"][0]["name"] == "Repaired"
    assert response["draft_verification"] == result["draft_verification"]


def test_stale_critique_is_not_current_advisory_or_summary(tmp_path):
    _trace(tmp_path)

    response = agent_response_from_trace(_result(review_status="stale"), tmp_path)

    assert not any(d["code"] == "agent_runtime.visual_critique_advisory" for d in response["diagnostics"])
    assert "cannot export" not in response["summary"]
    assert "awaits review" in response["summary"]
    assert response["status"] == "proposed"
    assert response["acceptance_scope"] is None


def test_current_blocking_preflight_is_reported_without_discarding_the_draft(tmp_path):
    _trace(tmp_path)

    response = agent_response_from_trace(_result(review_status="missing", blocked=True), tmp_path)

    assert [d["code"] for d in response["diagnostics"]] == ["LUMB0301"]
    assert response["draft_verification"]["preflight"]["has_blocking_errors"] is True
    assert "blocking preflight errors" in response["summary"]
    assert response["status"] == "proposed"


def test_legacy_warning_review_without_receipts_is_unverified_history(tmp_path):
    _trace(tmp_path)
    result = _result()
    del result["draft_verification"]

    response = agent_response_from_trace(result, tmp_path)

    assert response["diagnostics"] == []
    assert response["draft_verification"] is None
    assert response["historical_critique"]["critique"] == result["critique"]
    assert response["historical_critique"]["status"] == "unbound"
    assert "cannot export" not in response["summary"]
    assert "awaits review" in response["summary"]
    assert "preflight is unverified" in response["summary"]
    assert response["acceptance_scope"] is None


def test_legacy_compile_errors_remain_history_when_validity_receipts_are_absent(tmp_path):
    _trace(tmp_path)

    response = agent_response_from_trace({"status": "completed_with_warnings"}, tmp_path)

    assert response["diagnostics"] == []
    assert response["diagnostic_history"][0]["diagnostics"][0]["severity"] == "error"
    assert response["draft_verification"] is None
    assert response["status"] == "proposed"
