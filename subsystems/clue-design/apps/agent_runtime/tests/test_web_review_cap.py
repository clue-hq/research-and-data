"""G4 (founder ruling, 2026-08-19) — the web turn's review budget is mechanical.

A live chat-driven generation took ~13 minutes because the reviewer looped. The ruling:
at most SIX `lumen-web-reviewer` delegations per web turn, enforced in the harness rather
than asked for in prose, plus minimum-turns pressure in the prompts. Exceeding the cap
must not kill the turn — the 7th delegation gets an honest tool-level refusal telling the
orchestrator to finalize now with its standing critique.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from lumen_agent import harness_web
from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.harness_web import WEB_REVIEW_DELEGATION_CAP, WebReviewDelegationCap
from lumen_agent.prompts_web import (
    build_web_orchestrator_prompt,
    build_web_reviewer_prompt,
)
from lumen_api.core import CoreClient

REPO_ROOT = Path(__file__).resolve().parents[3]


def _delegation(subagent_type: str, call_id: str = "call_1") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={
            "name": "task",
            "args": {"description": "Review the page.", "subagent_type": subagent_type},
            "id": call_id,
            "type": "tool_call",
        },
        tool=None,
        state={},
        runtime=None,
    )


class _Handler:
    """Stands in for the real tool execution; counts how often it actually ran."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: ToolCallRequest) -> ToolMessage:
        self.calls += 1
        return ToolMessage(content="critique", tool_call_id=request.tool_call["id"])


def test_the_first_six_reviewer_delegations_execute_and_the_seventh_is_refused() -> None:
    cap = WebReviewDelegationCap()
    handler = _Handler()

    for index in range(WEB_REVIEW_DELEGATION_CAP):
        result = cap.wrap_tool_call(_delegation("lumen-web-reviewer", f"call_{index}"), handler)
        assert result.content == "critique"
    assert handler.calls == WEB_REVIEW_DELEGATION_CAP

    refused = cap.wrap_tool_call(_delegation("lumen-web-reviewer", "call_7"), handler)

    # The delegation did NOT run...
    assert handler.calls == WEB_REVIEW_DELEGATION_CAP
    # ...and the turn continues: a ToolMessage the orchestrator can act on, never a raise.
    assert isinstance(refused, ToolMessage)
    assert refused.tool_call_id == "call_7"
    body = refused.content.lower()
    assert "review" in body and "budget" in body
    assert str(WEB_REVIEW_DELEGATION_CAP) in refused.content
    assert "finalize_web_run" in refused.content


def test_the_cap_counts_only_reviewer_delegations() -> None:
    """Author rounds and ordinary tools are none of the review budget's business."""

    cap = WebReviewDelegationCap()
    handler = _Handler()

    for index in range(WEB_REVIEW_DELEGATION_CAP + 3):
        cap.wrap_tool_call(_delegation("lumen-web-author", f"author_{index}"), handler)
    other = ToolCallRequest(
        tool_call={"name": "render_web_preview", "args": {}, "id": "r1", "type": "tool_call"},
        tool=None,
        state={},
        runtime=None,
    )
    cap.wrap_tool_call(other, handler)

    assert handler.calls == WEB_REVIEW_DELEGATION_CAP + 4
    assert cap.delegations == 0
    # The reviewer's own budget is untouched by all of that.
    assert cap.wrap_tool_call(_delegation("lumen-web-reviewer"), handler).content == "critique"


def test_each_turn_gets_its_own_budget() -> None:
    """Turn-scoped by construction — the counter lives on the per-turn instance."""

    exhausted = WebReviewDelegationCap()
    handler = _Handler()
    for index in range(WEB_REVIEW_DELEGATION_CAP):
        exhausted.wrap_tool_call(_delegation("lumen-web-reviewer", f"c{index}"), handler)

    fresh = WebReviewDelegationCap()
    assert fresh.wrap_tool_call(_delegation("lumen-web-reviewer"), handler).content == "critique"


def test_the_web_harness_installs_the_review_cap(tmp_path: Path, monkeypatch) -> None:
    import deepagents

    import lumen_agent.llm as llm

    captured: dict = {}

    monkeypatch.setattr(deepagents, "create_deep_agent", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(harness_web, "materialize_agent_workspace", lambda _config: None)
    monkeypatch.setattr(
        harness_web, "_instrument", lambda _config, _tools, _model, role: f"{role}-model"
    )
    monkeypatch.setattr(llm, "assert_all_role_models_support_image_input", lambda _config: None)

    config = replace(AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path / "workspace")
    web_doc = CoreClient(repo_root=REPO_ROOT).web_new_doc("doc_alpha", "Alpha", None)["web_doc"]
    harness_web.create_web_deepagent("Build a page.", config, web_doc)

    caps = [m for m in captured["middleware"] if isinstance(m, WebReviewDelegationCap)]
    assert len(caps) == 1


# --- the prompting half --------------------------------------------------------------------------


def test_the_orchestrator_prompt_states_the_cap_and_pushes_for_the_fewest_rounds() -> None:
    prompt = build_web_orchestrator_prompt(
        doc_title="Harbor & Sage",
        has_existing_content=False,
        brand_card="warm, coastal",
        review_cap=WEB_REVIEW_DELEGATION_CAP,
    )

    assert str(WEB_REVIEW_DELEGATION_CAP) in prompt
    assert "lumen-web-reviewer" in prompt
    lowered = prompt.lower()
    assert "fewest" in lowered
    # The typical shape the ruling names: one author pass, one or two review rounds.
    assert "one author pass" in lowered
    assert "cosmetic" in lowered


def test_the_reviewer_prompt_keeps_advisories_out_of_another_round() -> None:
    prompt = build_web_reviewer_prompt().lower()

    assert "advisor" in prompt
    assert "summary" in prompt or "final" in prompt
