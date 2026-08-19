"""The web turn's delegation budgets are mechanical — G4 (reviewer), G6 lever 1 (author).

G4 (founder ruling, 2026-08-19): a live chat-driven generation took ~13 minutes because the
reviewer looped, so at most SIX `lumen-web-reviewer` delegations per web turn, enforced in
the harness rather than asked for in prose.

G6 (founder ruling, 2026-08-19): the benchmark then proved the 3.25 -> 10 minute spread is
agent-CHOSEN SCOPE, not model latency — the fast run used 2 `lumen-web-author` delegations,
the slow one 5, with an identical mean author-call latency. So the author gets a budget of
FOUR by the same mechanism.

Either budget exceeded must not kill the turn: the delegation past the cap gets an honest
tool-level refusal telling the orchestrator what it has left and to finalize.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from lumen_agent import harness_web
from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.harness_web import (
    WEB_AUTHOR_DELEGATION_CAP,
    WEB_REVIEW_DELEGATION_CAP,
    WebDelegationCap,
)
from lumen_agent.prompts_web import (
    build_web_orchestrator_prompt,
    build_web_reviewer_prompt,
)
from lumen_api.core import CoreClient

REPO_ROOT = Path(__file__).resolve().parents[3]

AUTHOR = "lumen-web-author"
REVIEWER = "lumen-web-reviewer"


def _delegation(subagent_type: str, call_id: str = "call_1") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={
            "name": "task",
            "args": {"description": "Do the work.", "subagent_type": subagent_type},
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
        return ToolMessage(content="delegated", tool_call_id=request.tool_call["id"])


def test_the_first_six_reviewer_delegations_execute_and_the_seventh_is_refused() -> None:
    cap = WebDelegationCap()
    handler = _Handler()

    for index in range(WEB_REVIEW_DELEGATION_CAP):
        result = cap.wrap_tool_call(_delegation(REVIEWER, f"call_{index}"), handler)
        assert result.content == "delegated"
    assert handler.calls == WEB_REVIEW_DELEGATION_CAP

    refused = cap.wrap_tool_call(_delegation(REVIEWER, "call_7"), handler)

    # The delegation did NOT run...
    assert handler.calls == WEB_REVIEW_DELEGATION_CAP
    # ...and the turn continues: a ToolMessage the orchestrator can act on, never a raise.
    assert isinstance(refused, ToolMessage)
    assert refused.tool_call_id == "call_7"
    body = refused.content.lower()
    assert "review" in body and "budget" in body
    assert str(WEB_REVIEW_DELEGATION_CAP) in refused.content
    assert "finalize_web_run" in refused.content


def test_the_first_four_author_delegations_execute_and_the_fifth_is_refused() -> None:
    cap = WebDelegationCap()
    handler = _Handler()

    for index in range(WEB_AUTHOR_DELEGATION_CAP):
        result = cap.wrap_tool_call(_delegation(AUTHOR, f"author_{index}"), handler)
        assert result.content == "delegated"
    assert handler.calls == WEB_AUTHOR_DELEGATION_CAP

    refused = cap.wrap_tool_call(_delegation(AUTHOR, "author_5"), handler)

    assert handler.calls == WEB_AUTHOR_DELEGATION_CAP
    assert isinstance(refused, ToolMessage)
    assert refused.tool_call_id == "author_5"
    assert refused.name == "task"
    body = refused.content.lower()
    assert "author" in body and "budget" in body
    assert str(WEB_AUTHOR_DELEGATION_CAP) in refused.content
    # It must tell the orchestrator how to END the turn, not just that it failed.
    assert "finalize_web_run" in refused.content


def test_the_author_refusal_names_no_tool_the_orchestrator_cannot_call() -> None:
    """The 2026-07-29 live failure (see harness_web): a refusal naming an uncallable tool
    sends the role into blind churn. The orchestrator holds no editing tool at all — it
    views, renders, and finalizes — so the refusal must ask for exactly that."""

    cap = WebDelegationCap()
    handler = _Handler()
    for index in range(WEB_AUTHOR_DELEGATION_CAP):
        cap.wrap_tool_call(_delegation(AUTHOR, f"a{index}"), handler)
    refused = cap.wrap_tool_call(_delegation(AUTHOR, "a_last"), handler)

    for uncallable in ("web_ops", "author_web_page", "author_web_subtree", "patch_web_page"):
        assert uncallable not in refused.content


def test_the_author_and_reviewer_budgets_are_independent() -> None:
    cap = WebDelegationCap()
    handler = _Handler()

    for index in range(WEB_AUTHOR_DELEGATION_CAP + 2):
        cap.wrap_tool_call(_delegation(AUTHOR, f"author_{index}"), handler)
    assert handler.calls == WEB_AUTHOR_DELEGATION_CAP  # two refusals, no exception

    # The reviewer's own budget is untouched by all of that.
    assert cap.wrap_tool_call(_delegation(REVIEWER, "r1"), handler).content == "delegated"
    assert cap.delegations[REVIEWER] == 1
    assert cap.delegations[AUTHOR] == WEB_AUTHOR_DELEGATION_CAP


def test_ordinary_tools_and_unknown_subagents_are_none_of_the_caps_business() -> None:
    cap = WebDelegationCap()
    handler = _Handler()

    other = ToolCallRequest(
        tool_call={"name": "render_web_preview", "args": {}, "id": "r1", "type": "tool_call"},
        tool=None,
        state={},
        runtime=None,
    )
    cap.wrap_tool_call(other, handler)
    for index in range(9):
        cap.wrap_tool_call(_delegation("general-purpose", f"g{index}"), handler)

    assert handler.calls == 10
    assert cap.delegations == {AUTHOR: 0, REVIEWER: 0}


def test_each_turn_gets_its_own_budget() -> None:
    """Turn-scoped by construction — the counters live on the per-turn instance."""

    exhausted = WebDelegationCap()
    handler = _Handler()
    for index in range(WEB_REVIEW_DELEGATION_CAP):
        exhausted.wrap_tool_call(_delegation(REVIEWER, f"c{index}"), handler)
    for index in range(WEB_AUTHOR_DELEGATION_CAP):
        exhausted.wrap_tool_call(_delegation(AUTHOR, f"a{index}"), handler)

    fresh = WebDelegationCap()
    assert fresh.wrap_tool_call(_delegation(REVIEWER), handler).content == "delegated"
    assert fresh.wrap_tool_call(_delegation(AUTHOR, "a"), handler).content == "delegated"


def test_the_web_harness_installs_the_delegation_cap(tmp_path: Path, monkeypatch) -> None:
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

    caps = [m for m in captured["middleware"] if isinstance(m, WebDelegationCap)]
    assert len(caps) == 1
    # One instance, both budgets, fresh counters.
    assert caps[0].delegations == {AUTHOR: 0, REVIEWER: 0}


# --- the prompting half --------------------------------------------------------------------------


def _orchestrator_prompt() -> str:
    return build_web_orchestrator_prompt(
        doc_title="Harbor & Sage",
        has_existing_content=False,
        brand_card="warm, coastal",
        review_cap=WEB_REVIEW_DELEGATION_CAP,
        author_cap=WEB_AUTHOR_DELEGATION_CAP,
    )


def test_the_orchestrator_prompt_states_both_caps_and_pushes_for_the_fewest_rounds() -> None:
    prompt = _orchestrator_prompt()

    assert str(WEB_REVIEW_DELEGATION_CAP) in prompt
    assert str(WEB_AUTHOR_DELEGATION_CAP) in prompt
    assert "lumen-web-reviewer" in prompt
    assert "lumen-web-author" in prompt
    lowered = prompt.lower()
    assert "fewest" in lowered
    # The typical shape the ruling names: one author pass, one or two review rounds.
    assert "one author pass" in lowered
    assert "cosmetic" in lowered


def test_the_orchestrator_prompt_teaches_one_brief_planning_and_view_discipline() -> None:
    """G6 lever 1 + the light half of lever 2: the whole page goes into ONE author brief,
    and each render's widths are viewed once."""

    lowered = _orchestrator_prompt().lower()

    assert "one author brief" in lowered
    assert "never re-view" in lowered


def test_the_reviewer_prompt_keeps_advisories_out_of_another_round() -> None:
    prompt = build_web_reviewer_prompt().lower()

    assert "advisor" in prompt
    assert "summary" in prompt or "final" in prompt
