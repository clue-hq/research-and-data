"""M8B O3 scripted conversation contract over the promoted Head/research resources.

The steering card this file pins — ``skill:account-deep-steering@v8`` — left the Head-of-ABM
profile at ``head-of-abm@v44`` (founder ruling 2, 2026-09-10): its frontmatter requires the five
old-research-lane tools, and v44 grants none of them, so a profile that still disclosed it would be
advertising a procedure whose every step is uncallable. The card itself is immutable reviewed
evidence and its contract still governs every already-pinned execution that replays it, so this
file now reads it from the folder catalog directly and asserts, first, that no current profile
discloses it. A steering skill written against the ARV2 launch tools is a follow-up before O7.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clue_agents import AgentRole
from clue_agents.catalog import AgentCatalogError, FolderSkillCatalog
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.toolbelt_wiring import build_toolbelt
from tests.api.conftest import hermetic_flag_env
from tests.api.test_agent_registry_wiring import CATALOG_ROOT

_SCENARIOS = (
    Path(__file__).parents[1] / "fixtures" / "agents" / "o3_account_deep_conversations.yaml"
)


def test_scripted_o3_conversations_cover_the_non_linear_gate() -> None:
    payload = yaml.safe_load(_SCENARIOS.read_text())
    scenarios = payload["scenarios"]
    assert {item["name"] for item in scenarios} == {
        "show_accounts_only",
        "discover_more",
        "five_accounts_with_fax_referral_direction",
        "remove_phone_reveals",
        "edit_before_confirm",
        "edit_after_launch",
        "explicit_launch",
    }

    with hermetic_flag_env():
        registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    head = registry.resolve(AgentRole.HEAD_OF_ABM)
    # The promoted profile disclosed this steering skill at exactly one version through v43 (v4 →
    # v8 across the Slice B waves). ``head-of-abm@v44`` discloses it at NO version, so the
    # disclosure assertion is now the negative one, and the body is read from the reviewed folder
    # catalog — where it stays immutable for the executions that replay it.
    with pytest.raises(AgentCatalogError, match="not disclosed"):
        head.open_skill("skill:account-deep-steering@v8")
    skill = (
        FolderSkillCatalog((CATALOG_ROOT / "skills").resolve(strict=True))
        .get("account-deep-steering", "v8")
        .body
    )

    for scenario in scenarios:
        assert scenario["user_turns"]
        assert scenario["required_guidance"] in skill
        actions = scenario["scripted_actions"]
        has_launch = bool(
            {"launch_account_research", "launch_selected_account_research"} & set(actions)
        )
        assert has_launch is scenario["explicit_launch_go_ahead"]
        if not scenario["explicit_launch_go_ahead"]:
            assert "launch_account_research" not in actions
            assert "launch_selected_account_research" not in actions

    discovery_completion_actions = next(
        item["scripted_actions"] for item in scenarios if item["name"] == "show_accounts_only"
    )
    assert "draft_directive" not in discovery_completion_actions
    assert "launch_account_research" not in discovery_completion_actions

    # The steering skill — not the launch tool's registered description — carries the
    # human-approval gate and the "a receipt is not completed research" reading rule, so the
    # contract is pinned where it actually lives.
    assert (
        "Call `launch_account_research@1` only after the current user action explicitly approves "
        "the exact\nconfirmed directive, account set, estimate, and cap." in skill
    )
    assert "A queue receipt or provider wait is not completed research." in skill
    assert (
        "Never translate a successful tool call, launch receipt, replay, or model stop into "
        "successful research." in " ".join(skill.split())
    )

    # Founder ruling 2026-08-20: the committee is co-defined with the user *before* a
    # committee-discovering directive is drafted, and the ratified plan carries the outcome —
    # taught by prompt emphasis, deliberately with no mechanical gate anywhere. Live motivation:
    # a ratified plan whose selectors were all empty let the account agent improvise target
    # functions at call time, and the vocabulary mismatch excluded two real physician-executives.
    # Pinned here because the steering card is where the contract actually lives.
    flat_skill = " ".join(skill.split())
    assert "## Co-define the buying committee with the user before you draft one" in skill
    assert (
        "Before drafting any account-research directive that will discover a committee — any "
        "directive whose sources include `sumble_people` — settle two things in conversation:"
        in flat_skill
    )
    assert "**What this project is selling.**" in flat_skill
    assert (
        "Champion, economic buyer, technical evaluator, blocker — for the target companies "
        "actually in front of you, expressed as functions, seniority levels, and job titles the "
        "user recognizes." in flat_skill
    )
    assert (
        "Then encode the outcome into `directive.committee_plan` — the only committee authority "
        "the per-account research agents ever receive. They copy it and never invent position "
        "specs of their own" in flat_skill
    )
    for selector in ("`personas`", "`functions`", "`levels` and `teams`", "`candidate_cap`"):
        assert selector in skill
    assert "`champion`, `economic_buyer`, `technical_evaluator`, `blocker`" in flat_skill
    # The provider-vocabulary lesson: admission never filters on functions (founder ruling), but the
    # account agent may narrow but never widen, so synonyms belong in the plan itself.
    assert "**Speak the provider's vocabulary as well as the user's.**" in flat_skill
    assert (
        "the account agent may narrow your `functions` but may never invent one, so a function "
        "the plan omits cannot be recovered later" in flat_skill
    )
    assert "`Clinical` alongside `Physician` in healthcare" in flat_skill
    # Declining to specify is answered by a stated proposal at the human gate, never by an empty
    # plan and never by stalling — and no new refusal is introduced.
    assert (
        "If the user will not work through the personas, neither stall nor leave the plan empty: "
        "propose the persona-to-position mapping yourself, put it in the plan, and state it in "
        "plain words" in flat_skill
    )
    assert (
        "in the same message that carries the directive confirmation gate, so the human approving "
        "the directive is approving that mapping too." in flat_skill
    )
    assert (
        "This is a conversation you owe the user, not a check anything will enforce on you."
        in flat_skill
    )

    # The registered launch tool is the exact governed spend-class contract that gate steers, and
    # its durable identity is the approved directive/selection/budget triple — so a replay is the
    # same launch, never a second one.
    descriptor = build_toolbelt(storage=None, gateway=None).descriptor("launch_account_research")
    assert "only after the current user action explicitly approves" in descriptor.model_description
    assert (
        "it never means account or committee research has completed" in descriptor.model_description
    )
    assert "never authorizes contact research" in descriptor.model_description
    assert descriptor.effect_class.value == "spend"
    assert descriptor.replay.policy.value == "domain_idempotent"
    assert (
        descriptor.replay.durable_identity
        == "confirmed directive + exact account selection + approved budget"
    )
    assert descriptor.pin_requirements == (
        "project_run",
        "research_directive",
        "account_research_selection",
    )


def test_research_specialist_separates_plan_review_from_admitted_execution() -> None:
    with hermetic_flag_env():
        registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    specialist = registry.resolve(AgentRole.RESEARCH)
    body = specialist.open_skill("skill:research-task@v4")

    assert "For a pre-launch review, analyze only." in body
    assert "Do not imitate, launch, or replace those units." in body
    assert (
        "Inventory exact entities, fields, directional\nquestions, evidence gaps, source plans"
        in body
    )
    assert (
        "A provider receipt, fleet return, or partial claim set is not verified merely because it\n"
        "exists." in body
    )
    assert (
        "Never claim completion for an account/contact job whose\n"
        "accepted finalization receipt is absent." in body
    )
