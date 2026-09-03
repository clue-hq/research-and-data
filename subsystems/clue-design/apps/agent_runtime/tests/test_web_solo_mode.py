"""SOLO MODE (founder ruling 2026-09-04): one web deepagent, three pairs of eyes.

What is pinned here is the ruling itself, not implementation trivia:

* **Both subagents genuinely absent.** `LUMEN_AGENT_WEB_SOLO=1` registers NO subagents —
  tool-absence enforcement, the D-F7 pattern widened — and neither subagent model is even
  instrumented (an instrumented model that can never be called would lie in attribution).
* **The one agent holds the whole craft.** The director's read/render/judge tools AND the
  author's full write surface ride one tool list; the merged solo prompt replaces
  direction-by-delegation with plan → build → render → self-review, and carries the same
  shared rubric bytes every other reviewer of a page receives.
* **The trio path is untouched.** Flag off, the subagent list, prompts, and caps are exactly
  the pre-ruling composition — solo is a mode, not a migration.
* **The mutation budget is a backstop, not a pacing device.** 75, per the same ruling; the
  render reset is unchanged.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from lumen_agent import harness_web
from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.prompts_web import build_web_solo_prompt
from lumen_agent.rubrics import load_clone_review_rubric
from lumen_agent.tools import web_substrate

REPO_ROOT = Path(__file__).resolve().parents[3]
REVIEWER = "lumen-web-reviewer"
AUTHOR = "lumen-web-author"


def _create_web_agent(tmp_path, monkeypatch, config) -> dict:
    import deepagents

    import lumen_agent.llm as llm
    from lumen_api.core import CoreClient

    captured: dict = {}
    monkeypatch.setattr(deepagents, "create_deep_agent", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(harness_web, "materialize_agent_workspace", lambda _config: None)
    monkeypatch.setattr(
        harness_web, "_instrument", lambda _config, _tools, _model, role: f"{role}-model"
    )
    monkeypatch.setattr(llm, "assert_all_role_models_support_image_input", lambda _config: None)
    web_doc = CoreClient(repo_root=REPO_ROOT).web_new_doc("doc_solo", "Solo", None)["web_doc"]
    harness_web.create_web_deepagent("Build a page.", config, web_doc)
    return captured


def _solo_config(tmp_path):
    return replace(
        AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path / "ws", web_solo=True
    )


def test_solo_registers_no_subagents_and_carries_the_full_write_surface(
    tmp_path, monkeypatch
) -> None:
    captured = _create_web_agent(tmp_path, monkeypatch, _solo_config(tmp_path))
    assert captured["subagents"] == []
    tool_names = {getattr(t, "name", getattr(t, "__name__", "")) for t in captured["tools"]}
    # The director's surface survives...
    for name in ("render_web_preview", "review_cloned_page", "finalize_web_run"):
        assert name in tool_names, name
    # ...and the author's write surface joins it.
    for name in (
        "author_web_page",
        "patch_web_page",
        "author_web_subtree",
        "web_ops",
        "assemble_cloned_sections",
        "insert_cloned_section",
        "compose_web_section",
        "repair_cloned_section",
        "release_repair",
        "mint_campaign_shells",
        "assemble_abm_page",
        "asset",
    ):
        assert name in tool_names, name
    # The one agent is the skills reader now.
    assert captured["skills"] == ["/.deepagent/skills"]


def test_solo_prompt_is_the_merged_persona_with_the_shared_rubric(
    tmp_path, monkeypatch
) -> None:
    captured = _create_web_agent(tmp_path, monkeypatch, _solo_config(tmp_path))
    prompt = captured["system_prompt"]
    # The founder-specified persona: director, designer, judge-as-the-customer.
    assert "THE DIRECTOR" in prompt
    assert "THE DESIGNER" in prompt
    assert "THE JUDGE" in prompt
    assert "You never delegate" in prompt
    # The same rubric bytes every reviewer of a page receives.
    assert load_clone_review_rubric() in prompt
    # No delegation is promised that the runtime would reject.
    assert AUTHOR not in prompt
    assert REVIEWER not in prompt
    # The working memory law and the micro-loop are stated — and the plan path is
    # RUN-SCOPED (founder correction 2026-09-04: a bare relative `workspace/` resolved
    # to the shared backend root and leaked one brief's plan into the next run).
    assert "/workspace/plan.md" in prompt
    assert "first write is `workspace/plan.md`" not in prompt
    # The raw lane is the workspace-level default (the Ramp regression's fix): the
    # chicken-and-egg "page has no clones yet" reading is closed in the always-present
    # lanes block.
    assert "DEFAULT IN ANY WORKSPACE WITH RELEASED CLONES" in prompt
    assert "render_web_preview" in prompt


def test_flag_off_keeps_the_trio_composition_byte_identical(tmp_path, monkeypatch) -> None:
    config = replace(AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path / "ws")
    assert config.web_solo is False
    captured = _create_web_agent(tmp_path, monkeypatch, config)
    assert [sa["name"] for sa in captured["subagents"]] == [AUTHOR, REVIEWER]
    assert captured["skills"] is None
    assert "You direct a website-building turn" in captured["system_prompt"]
    tool_names = {getattr(t, "name", getattr(t, "__name__", "")) for t in captured["tools"]}
    assert "author_web_page" not in tool_names


def test_solo_account_blocks_render_only_with_an_account() -> None:
    base = dict(
        doc_title="T",
        has_existing_content=False,
        brand_card="BRAND",
        theme_token_names="primary accent",
    )
    with_account = build_web_solo_prompt(**base, account_card="ACME", brandfetch_client_id="cid")
    assert "this is a 1:1 page for one company" in with_account
    assert "bind_account_logo" in with_account
    assert "cdn.brandfetch.io" in with_account
    # The clone-first law survives the ABM marker pressure (the Ramp regression):
    # markers ride slot values, so pinning stays the top rung on account pages, and
    # COMPOSE-VOCAB must justify itself against every other source.
    assert "PINNING IS STILL THE TOP RUNG" in with_account
    assert '"it needs markers" is NOT a reason to compose' in with_account
    without = build_web_solo_prompt(**base)
    assert "this is a 1:1 page for one company" not in without
    assert "cdn.brandfetch.io" not in without


def test_the_mutation_budget_is_the_backstop_the_ruling_named() -> None:
    assert web_substrate._ROUND_MUTATION_BUDGET == 75
