"""Brief-clarification capability — offline unit tests (no LLM calls).

Covers: request_clarification payload validation, the clarification_requested
turn envelope, and the two STRUCTURAL suppressors of the tool (auto_defaults and
a prior clarification round). deepagents is stubbed exactly as
test_deepagent_harness does, so create_deep_agent never builds a real model.
"""

from __future__ import annotations

import json
from dataclasses import replace as dc_replace

import pytest

from lumen_agent.harness import create_design_deepagent
from lumen_agent.tools.substrate import LumenDesignTools

from agent_fixtures import FakeCoreClient, runtime_config
from test_deepagent_harness import _install_deepagents_stub, _tool_name


# --- payload validation -----------------------------------------------------


def _tools(tmp_path, monkeypatch, **config_overrides):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path)
    if config_overrides:
        config = dc_replace(config, **config_overrides)
    return LumenDesignTools(config, "Make us a social ad")


def _valid_question(qid="format", default="an Instagram square (1080x1080)"):
    return {
        "id": qid,
        "question": "What surface is this for?",
        "why_it_matters": "It fixes the canvas size and the whole layout.",
        "options": ["Instagram square", "LinkedIn landscape"],
        "default": default,
        "allow_freeform": True,
    }


def test_seven_questions_rejected(tmp_path, monkeypatch):
    # Cap is six since harness alignment I6 (founder ruling 2026-10-17).
    tools = _tools(tmp_path, monkeypatch)
    result = json.loads(
        tools.request_clarification([_valid_question(qid=f"q{i}") for i in range(7)])
    )
    assert result["status"] == "error"
    assert result["error_code"] == "clarification.invalid_payload"
    # It is a validation rejection, not a written turn envelope.
    assert not (tools.trace_dir / "final.json").exists()


def test_six_questions_accepted(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    result = json.loads(
        tools.request_clarification([_valid_question(qid=f"q{i}") for i in range(6)])
    )
    assert result.get("status") != "error", result


def test_registered_tool_hands_the_model_a_typed_schema(tmp_path, monkeypatch):
    """The agent sees every field, its description and the 1-6 limit before it calls."""
    from langchain_core.utils.function_calling import convert_to_openai_tool
    from lumen_agent.harness import _make_request_clarification_tool

    tools = _tools(tmp_path, monkeypatch)
    params = convert_to_openai_tool(_make_request_clarification_tool(tools))["function"]["parameters"]
    questions = params["properties"]["questions"]
    assert (questions["minItems"], questions["maxItems"]) == (1, 6)
    item = questions["items"]
    if "$ref" in item:
        item = params["$defs"][item["$ref"].split("/")[-1]]
    assert {"id", "question", "why_it_matters", "default"} <= set(item["required"])
    for field in ("id", "question", "why_it_matters", "options", "default", "allow_freeform"):
        assert item["properties"][field].get("description"), field


def test_missing_default_rejected(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    question = _valid_question()
    del question["default"]
    result = json.loads(tools.request_clarification([question]))
    assert result["status"] == "error"
    assert result["error_code"] == "clarification.invalid_payload"
    # The pydantic error names the missing field so the model can fix it.
    assert any("default" in item.get("loc", []) for item in result["errors"])


def test_blank_default_rejected(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    result = json.loads(
        tools.request_clarification([_valid_question(default="   ")])
    )
    assert result["status"] == "error"
    assert result["error_code"] == "clarification.invalid_payload"


def test_empty_questions_rejected(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    result = json.loads(tools.request_clarification([]))
    assert result["status"] == "error"


# --- the clarification_requested envelope -----------------------------------


def test_request_clarification_produces_honest_envelope(tmp_path, monkeypatch):
    tools = _tools(tmp_path, monkeypatch)
    questions = [_valid_question(qid="format"), _valid_question(qid="message_focus")]
    raw = tools.request_clarification(questions)
    payload = json.loads(raw)

    assert payload["status"] == "clarification_requested"
    assert payload["stop_reason"] == "clarification_requested"
    assert payload["outcome"] == "clarification_requested"
    # Questions ride through intact (ids + defaults preserved).
    returned = payload["clarification"]["questions"]
    assert [q["id"] for q in returned] == ["format", "message_focus"]
    assert all(q["default"] for q in returned)
    # Summary is human-readable text for the pre-R2 chat surface.
    assert "go with your defaults" in payload["summary"].lower()
    assert "What surface is this for?" in payload["summary"]

    # Written to the SAME final.json the runner reads (sibling of finalize_run).
    final = json.loads((tools.trace_dir / "final.json").read_text(encoding="utf-8"))
    assert final["outcome"] == "clarification_requested"
    assert final["clarification"]["questions"] == returned
    # Traced honestly.
    trace = (tools.trace_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert "clarification_requested" in trace


# --- structural suppressors -------------------------------------------------


def _orchestrator_tool_names(tmp_path, monkeypatch, **kwargs):
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    config = runtime_config(tmp_path)
    auto_defaults = kwargs.pop("auto_defaults", False)
    if auto_defaults:
        config = dc_replace(config, auto_defaults=True)
    create_design_deepagent("Make us a social ad", config, **kwargs)
    return {_tool_name(t) for t in capture["kwargs"]["tools"]}


def test_tool_present_on_default_turn(tmp_path, monkeypatch):
    names = _orchestrator_tool_names(tmp_path, monkeypatch)
    assert "request_clarification" in names


def test_tool_absent_under_auto_defaults(tmp_path, monkeypatch):
    names = _orchestrator_tool_names(tmp_path, monkeypatch, auto_defaults=True)
    assert "request_clarification" not in names
    # The rest of the surface is unchanged.
    assert "finalize_run" in names and "record_gap" in names


def test_tool_absent_after_prior_clarification_round(tmp_path, monkeypatch):
    names = _orchestrator_tool_names(
        tmp_path, monkeypatch, clarification_already_requested=True
    )
    assert "request_clarification" not in names
    assert "finalize_run" in names and "record_gap" in names
