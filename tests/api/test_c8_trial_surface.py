"""PC-C8 §8 / AC-7: the Stage-0 trial's restrictions are tools that are not installed.

The rules the retired stage-snapshot prose used to carry — "this is a manual-conversation-only
trial", "do not call `start_recon`", "do not call `synthesize_icps`" — now live on a *capability
surface* instead. Ruling §2.4: a prompt saying "do not call it" is guidance; governance is a tool
that is not there. This file is the evidence that the surface is real and that everything the model
is shown follows it, because a filtered tool list that the manifest, the capability map, or the
runtime middleware disagreed with would be exactly the fake-agency failure the ruling forbids.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from clue_agents import AgentRole
from clue_agents.catalog import (
    AgentCatalogError,
    FolderProfileCatalog,
    FolderPromptCatalog,
    FolderSkillCatalog,
)
from clue_agents.manual.build import MANUAL_CHAPTERS
from clue_agents.registry import (
    AgentCapabilityStatus,
    AgentProfileRegistry,
    AgentSurfacePolicy,
)
from clue_agents.runtime import ExactAgentToolSurfaceMiddleware
from clue_api.agent_registry_wiring import (
    C6_ACTIVE_PROFILE_VERSIONS,
    C6_AGENT_TOOL_AUTHORITY,
    C6_SURFACE_POLICIES,
    PROJECT_CONVERSATION_SURFACE,
    STAGE0_CONVERSATION_TRIAL_SURFACE,
    ToolRegistryAgentCatalog,
    build_agent_profile_registry,
)
from clue_api.entity_research_quarantine import QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES
from clue_api.toolbelt_wiring import build_toolbelt
from tests.api.conftest import hermetic_flag_env
from tests.api.test_agent_registry_wiring import CATALOG_ROOT

# Mirrors C6_SURFACE_POLICIES for the trial surface. M8D R10 retired the account-deep launch and
# gap-enrichment tools from every active role (they are no longer *grantable*, so there is nothing
# to withhold) and put the promoted separately confirmed launches behind the same trial withhold.
# FI Lane D D4 added `open_directive_confirmation_gate` to the same set, for the same sentence: a
# dev harness that could present a real, addressed, durable confirmation gate — but could never act
# on the answer — would be inviting a human to approve spend no surface here can perform. S5-F
# applies the same fail-closed rule to the product-selection gate: the shared skill may explain the
# procedure, but this trial cannot present a control whose answer it cannot compose.
# ARV2 onboarding O6 shortened this set without relaxing it. `head-of-abm@v44` drops
# `start_recon`, `submit_onboarding_input`, `synthesize_icps`, `open_product_selection_gate`,
# `open_discovery_configuration_gate` and — per founder ruling 2, 2026-09-10 — the five
# old-research-lane tools from the ROLE, so there is nothing left for this surface to withhold on
# any of them, and a policy may only narrow tools the profile pins. Ungranted on every surface is a
# stronger statement than withheld on one, which is what the assertions below now say.
_WITHHELD = {
    # P3.4: the design delegation entry is withheld on the trial for the same sentence as
    # delegation itself — a leg opened from a dev CLI would durably reroute a thread no
    # design runtime here can serve.
    "open_design_leg",
    "open_directive_confirmation_gate",
    # ARV2 onboarding O6: the new lane's two launches and its two gates, for the same sentence.
    # Each launch queues real research jobs against external providers; each gate writes a real,
    # durable, human-addressed decision control whose answer no surface here can act on.
    # `read_arv2_account_research_run` is deliberately NOT here — read-only, spends nothing,
    # addresses nobody. The three old-lane launches that used to head this set are gone from it
    # because `head-of-abm@v44` no longer grants them at all (see `_ROLE_DROPPED`), which is the
    # stronger statement.
    "launch_arv2_account_research",
    "launch_arv2_person_research",
    # ARV2 Track R, R4: the discovery launch joins them for the same sentence — it queues a real
    # discovery run against external providers.
    "launch_arv2_discovery",
    # Automatic project targeting (head-of-abm@v61): the two gates are UNGRANTED now, which is the
    # stronger statement, and `configure_project_targeting` — a durable write of the project's ICP
    # pin and product set — is withheld on the trial for the same sentence the gates were.
    "configure_project_targeting",
    # The ICP-authoring pair and the plan write used to head this group. They are gone from it
    # because `head-of-abm@v55` no longer grants any of them (see `_ROLE_DROPPED`), which is the
    # stronger statement — the same move the old-lane launches made at v44.
    # The three ARV2 reads are withheld for the OTHER reason: they spend nothing and address
    # nobody, but the trial's own `build_toolbelt` passes no `arv2_reads`, so installed they would
    # be advertised and then refuse `arv2_reads_not_composed` at call time — restriction by
    # refusal, which PC-C8 §2.4 rejects. Withheld, this surface's framing is true.
    # `read_claims` joins them at `head-of-abm@v56` for the identical sentence — same uncomposed
    # `arv2_reads` service — and `read_artifact` for the nearest thing to it: it needs no service,
    # but a dev-harness turn carries no project, so installed it could only refuse
    # `project_not_found`.
    "read_project_accounts",
    "read_account_research",
    "read_claims",
    "read_artifact",
    "read_discovery_run",
}

# The tools the trial used to withhold that `head-of-abm@v44` no longer grants at all. They must
# be absent from the trial surface for a stronger reason than a policy — the role does not hold
# them — and this set is what keeps the two facts from silently swapping places.
_ROLE_DROPPED = {
    "start_recon",
    "submit_onboarding_input",
    "synthesize_icps",
    "open_product_selection_gate",
    "open_discovery_configuration_gate",
    "evaluate_stage0_readiness",
    "start_confirmed_project_run",
    "list_client_knowledge",
    "inspect_client_claim",
    "list_product_knowledge",
    "inspect_product_claim",
    "inspect_readiness_history",
    # FOUNDER RULING 2 (2026-09-10): the five old-research-lane tools. The trial used to withhold
    # the three launches; v44 drops all five from the ROLE, so there is nothing left to withhold.
    "launch_account_research",
    "launch_selected_account_research",
    "launch_contact_research",
    "read_account_research_run",
    "read_contact_research_run",
    # The versioned project root (2026-09-14): the three document tools. The trial used to
    # withhold all three; `head-of-abm@v55` drops them from the ROLE, because the documents they
    # wrote are written as files under the `project/` mount now, so there is nothing left to
    # withhold. What the trial does NOT get from that is a write surface: `project/` is not on
    # this deployment's workspace for a dev harness turn, and the file tools refuse it there.
    "author_icp_document",
    "request_persona_synthesis",
    "write_project_document",
}

# The production conversation's own subtraction, which D4 made genuinely different from the trial's:
# it keeps the drafting, gate, and launch tools (that flow is the whole point of the surface) and
# withholds only the two trial restrictions that still hold here — this surface does no external
# research and never captures on the client's behalf. Trusted durable ICP synthesis is now present.
# ARV2 onboarding O6 empties it: neither tool is pinned by `head-of-abm@v44` on any surface, and
# the registry refuses a policy that withholds a tool the profile never grants. The policy remains
# for its delegation ceiling and its framing.
_PROJECT_WITHHELD: set[str] = set()


@pytest.fixture(scope="module")
def registry() -> AgentProfileRegistry:
    with hermetic_flag_env():
        return build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))


def test_the_trial_surface_withholds_exactly_the_prohibited_tools(
    registry: AgentProfileRegistry,
) -> None:
    base = registry.resolve(AgentRole.HEAD_OF_ABM)
    trial = registry.resolve(AgentRole.HEAD_OF_ABM, surface=STAGE0_CONVERSATION_TRIAL_SURFACE)

    base_names = {pin.name for pin in base.profile.tools}
    trial_names = {pin.name for pin in trial.profile.tools}

    assert base_names >= _WITHHELD, "the full role must still hold the authority being withheld"
    assert base_names - trial_names == _WITHHELD
    assert base_names.isdisjoint(_ROLE_DROPPED), "v44 must not re-grant a dropped old-lane tool"
    assert trial_names.isdisjoint(_ROLE_DROPPED)
    assert "enrich_selected_accounts" not in trial_names
    assert "enrich_account_gaps" not in trial_names
    # The surface narrows authority only — same reviewed profile resource, same prompt.
    assert trial.profile_ref == base.profile_ref
    assert trial.prompt_body == base.prompt_body


def test_the_resource_manifest_shown_to_the_model_is_the_filtered_surface(
    registry: AgentProfileRegistry,
) -> None:
    """AC-7's load-bearing half: the manifest the constitution pins *is* the narrowed set.

    The manifest is what the turn's ``resource_manifest_sha256`` commits to and what the trial
    persists as an artifact, so a manifest still listing a withheld tool would advertise authority
    the middleware then refuses — the model would be told it has a capability it cannot use.
    """

    base = registry.resolve(AgentRole.HEAD_OF_ABM)
    trial = registry.resolve(AgentRole.HEAD_OF_ABM, surface=STAGE0_CONVERSATION_TRIAL_SURFACE)

    manifest_names = {pin.name for pin in trial.resource_manifest.tools}
    assert manifest_names == {pin.name for pin in trial.profile.tools}
    assert manifest_names & _WITHHELD == set()
    assert trial.resource_manifest.aggregate_sha256 != base.resource_manifest.aggregate_sha256


def test_the_capability_map_names_the_surface_and_its_withheld_tools_honestly(
    registry: AgentProfileRegistry,
) -> None:
    trial = registry.resolve(AgentRole.HEAD_OF_ABM, surface=STAGE0_CONVERSATION_TRIAL_SURFACE)
    by_address = {item.address: item for item in trial.capabilities}
    generated = trial.generated_resource_map

    for name in sorted(_WITHHELD):
        # genweb slice 2 promoted the design delegation entry to @2 (web document birth at
        # leg-open), genad promoted it again to @3 (ad document birth), genad2 to @4 (zero-page
        # scene birth) and multi-artifact legs to @5 (an `artifacts` list in place of the one
        # `title`); the trial withholds it at whatever version the belt carries.
        _promoted = {"open_design_leg": "5"}
        address = f"{name}@{_promoted.get(name, '1')}"
        disclosure = by_address[address]
        assert disclosure.status is AgentCapabilityStatus.PROFILE_UNAVAILABLE
        assert disclosure.reason_code == "trial_manual_conversation_only"
        assert f"- {address} effect=" not in generated

    assert "manual-conversation-only" in generated
    assert f"surface={STAGE0_CONVERSATION_TRIAL_SURFACE}" in generated


_ADVERTISING_SECTIONS = (
    "Governed platform tools available to this role:",
    "Delegation:",
)


def _advertised_capabilities(generated: str) -> set[str]:
    """Parse the generated map into the set of capabilities it tells the model it *has*.

    Structural, not a substring scan: the map deliberately also *names* what is unavailable (that
    is the honest half), and a plain `in` test cannot tell "research is withheld" from
    "get_research_view is available". Each bullet under an advertising heading contributes the
    identifier it names — a tool name for the available list, a role for the delegation block —
    plus `delegate_specialist` when the capability line says it is available.
    """

    advertised: set[str] = set()
    section: str | None = None
    for line in generated.splitlines():
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith("-"):
            section = stripped
            continue
        if not stripped.startswith("- "):
            continue
        body = stripped[2:]
        if body.startswith("delegate_specialist: available"):
            advertised.add("delegate_specialist")
        if section not in _ADVERTISING_SECTIONS or body == "none":
            continue
        head = body.split(" ", 1)[0].rstrip(":")
        advertised.add(head.partition("@")[0])
    return advertised


def test_the_map_never_advertises_anything_the_surface_withholds(
    registry: AgentProfileRegistry,
) -> None:
    """The general property, not one instance of it.

    The first version of this file checked only that three tool *addresses* were missing from the
    available list. That passed while the very same map still rendered a Delegation block naming
    `delegate_specialist` and the three specialist roles — one of which is the research role the
    surface's own framing promises it does not use. The map contradicted its own first paragraph,
    and the only thing preventing the delegation was a child runner raising at call time.

    So this derives what is withheld from the policy itself and asserts none of it is advertised —
    which means a future withheld capability rendered through a new path is covered the day it is
    added, without anyone remembering to extend this test.
    """

    trial = registry.resolve(AgentRole.HEAD_OF_ABM, surface=STAGE0_CONVERSATION_TRIAL_SURFACE)
    policy = trial.surface_policy
    assert policy is not None

    advertised = _advertised_capabilities(trial.generated_resource_map)
    withheld = set(policy.withheld_tools) | {
        role.value for role in policy.withheld_delegation_roles
    }
    if policy.withheld_delegation_roles >= set(
        registry.resolve(policy.role).profile.delegation_roles
    ):
        withheld.add("delegate_specialist")

    assert sorted(advertised & withheld) == []
    # Positive control: the parser really does find things, so the assertion above is not passing
    # because `_advertised_capabilities` returned an empty set.
    assert {"record_interview_answer", "inspect_statement_history"} <= advertised
    # And the same parser over the *unrestricted* role does see everything the surface removed —
    # otherwise this test would keep passing if the map stopped advertising anything at all.
    replay_only_names = {
        address.partition("@")[0] for address in QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES
    }
    assert withheld - replay_only_names <= _advertised_capabilities(
        registry.resolve(AgentRole.HEAD_OF_ABM).generated_resource_map
    )


def test_the_trial_surface_withholds_delegation_rather_than_crashing_on_it(
    registry: AgentProfileRegistry,
) -> None:
    """`_DelegationDisabled` must be an unreachable backstop, not the restriction (ruling §2.4)."""

    base = registry.resolve(AgentRole.HEAD_OF_ABM)
    trial = registry.resolve(AgentRole.HEAD_OF_ABM, surface=STAGE0_CONVERSATION_TRIAL_SURFACE)

    assert base.profile.delegation_roles, "the full role must still delegate"
    assert trial.profile.delegation_roles == ()
    assert trial.delegation_tool_grants == {}
    # A surface with nobody to delegate to has no delegation budget to advertise either.
    assert trial.profile.max_delegation_depth == 0
    assert trial.profile.max_delegations == 0
    # ExactAgentToolSurfaceMiddleware installs `delegate_specialist` iff `delegation_roles`.
    assert "delegate_specialist: unavailable" in trial.generated_resource_map

    with pytest.raises(AgentCatalogError, match="is not delegated by"):
        registry.resolve_delegation(parent=trial, child_role=AgentRole.RESEARCH, current_depth=0)


def test_the_stage0_skill_no_longer_survives_the_narrowed_surface(
    registry: AgentProfileRegistry,
) -> None:
    """INVERTED by ARV2 onboarding O6 — deliberately, with the consequence stated out loud.

    This test was written to catch the regression this design could most easily have shipped
    silently: skills are dropped when a required tool is not effective, so withholding tools can
    quietly also remove all of Stage-0's routing procedure, and nothing else in this file would
    notice. Under stage0-interview v20 the withheld set and the skill's required set were
    disjoint, so the skill survived and this test said so.

    stage0-interview v21 requires the product-set gate, the ICP gate and the ARV2 launch — which
    are exactly the three tools this surface now withholds (fix round 1, coordinator ruling: a dev
    harness must not present a real, durable, addressed gate or hold launch authority it cannot
    act on). The consequence is that **the trial surface discloses no skill at all**: it keeps the
    prompt, the constitution and its read/route tools, and has no Stage-0 procedure.

    That is a genuine degradation of the trial, accepted because the trial is quarantine-bound
    (master plan Phase 6). It is asserted here rather than discovered later — which is the job the
    original guard was doing, and the reason this test is inverted instead of deleted.

    head-of-abm@v54 pins the fifteen operating-manual chapters beside it. A chapter requires no
    tool, so no withholding can drop one, and the trial keeps the whole reference library while
    losing the procedure. The manual describes the UNNARROWED grant, so on this surface its tools
    chapter names tools the trial withholds; the trial's own refusals remain the truth there.

    head-of-abm@v55 adds the three document skills on the same terms: none of them requires a
    tool, so all three survive the narrowing too. They describe writing under `project/`, which
    this surface's workspace does not mount — the same over-description the manual already has,
    and the same answer: the refusal the file tool gives here is the truth.
    """

    trial = registry.resolve(AgentRole.HEAD_OF_ABM, surface=STAGE0_CONVERSATION_TRIAL_SURFACE)
    base = registry.resolve(AgentRole.HEAD_OF_ABM)

    trial_disclosures = [item.resource.address for item in trial.skill_disclosures()]
    assert "skill:stage0-interview@v35" not in trial_disclosures
    assert trial_disclosures == [
        "skill:icp-authoring@v3",
        "skill:persona-authoring@v2",
        "skill:plan-authoring@v2",
        # v58 adds the sandbox skill after them and before the reference shelf: the whole
        # procedure for `run_python@1`, which it is the one disclosed skill to require.
        "skill:code-execution@v1",
        *(f"skill:manual-{name}@v9" for name in MANUAL_CHAPTERS),
    ]
    # The withholding is what removed it — not a catalog break, not a missing resource. The
    # unnarrowed role still discloses the same skill from the same profile.
    base_disclosures = {item.resource.address for item in base.skill_disclosures()}
    assert "skill:stage0-interview@v35" in base_disclosures
    assert trial.profile_ref == base.profile_ref

    stage0 = next(
        item for item in base.skill_disclosures() if item.resource.name == "stage0-interview"
    )
    required = {address.partition("@")[0] for address in stage0.required_tool_addresses}
    assert required & _WITHHELD == {
        "launch_arv2_account_research",
        # Automatic project targeting (v61): the skill requires the targeting write in place of
        # the two gates, and the trial withholds it for the same sentence.
        "configure_project_targeting",
        # Founder ruling 3 (2026-09-10): the person launch is granted to the role and taught by
        # stage0-interview v22 §8; the trial withholds it with its account sibling.
        "launch_arv2_person_research",
        # ARV2 Track R, R4: the discovery launch is granted to the role and taught by
        # stage0-interview v22 §7b; the trial withholds it with its siblings.
        "launch_arv2_discovery",
        # The ICP-authoring pair and the plan write are gone from the skill's own required set at
        # v32: `head-of-abm@v55` grants none of them, and §5b/§5c/§6b are pointers at the three
        # document skills now, so there is nothing here for the trial to withhold.
        # The three reads are granted at `head-of-abm@v48` and taught by stage0-interview v25
        # §7b/§7c; the trial withholds them because it composes no read service, so installed they
        # could only refuse. `read_claims` and `read_artifact` join the skill's required set at
        # v33, granted at `head-of-abm@v56`, and the trial withholds them for the same sentence.
        "read_project_accounts",
        "read_account_research",
        "read_claims",
        "read_artifact",
        "read_discovery_run",
    }

    body = base.open_skill("skill:stage0-interview@v35")
    assert "Ask one question at a time" in body
    # The trial's framing lives on the surface policy, never in the shared skill.
    assert "manual-conversation-only" not in body
    assert "trial" not in body.casefold()


def test_the_runtime_middleware_refuses_a_withheld_tool_on_the_trial_surface(
    registry: AgentProfileRegistry,
) -> None:
    """The enforcement itself: the middleware's allowed set follows the surface automatically."""

    trial = registry.resolve(AgentRole.HEAD_OF_ABM, surface=STAGE0_CONVERSATION_TRIAL_SURFACE)
    middleware = ExactAgentToolSurfaceMiddleware(profile=trial)

    installed = tuple(pin.name for pin in trial.profile.tools) + (
        "write_todos",
        "ls",
        "read_file",
        "glob",
        "grep",
        "write_file",
        "edit_file",
        "finalize_turn",
        # No `delegate_specialist`: the surface withholds every delegable role, so the framework
        # tool is not part of the allowed set either. Installing it is one of the smuggle cases.
    )

    async def handler(_request: Any) -> Any:
        return _Response()

    ok = _ModelRequest(installed)
    _run(middleware.awrap_model_call(ok, handler))
    assert ok.overrides is not None
    filtered = set(ok.overrides["tool_names"])
    assert filtered & _WITHHELD == set()
    # Delegation is withheld too, so the framework tool that reaches a specialist is not installed.
    assert "delegate_specialist" not in filtered

    for smuggled_name in ("start_recon", "delegate_specialist"):
        smuggled = _ModelRequest((*installed, smuggled_name))
        with pytest.raises(RuntimeError, match="undeclared runtime tools were installed"):
            _run(middleware.awrap_model_call(smuggled, handler))


def test_a_surface_policy_cannot_withhold_a_tool_the_profile_never_pinned() -> None:
    """A withheld name that matches nothing is how a restriction rots back into decoration."""

    toolbelt = build_toolbelt(storage=None, gateway=None)
    admitted = frozenset(
        toolbelt.descriptor(name).address
        for name, roles in C6_AGENT_TOOL_AUTHORITY.items()
        if roles
    )

    def build(policy: AgentSurfacePolicy) -> AgentProfileRegistry:
        return AgentProfileRegistry(
            prompts=FolderPromptCatalog((CATALOG_ROOT / "prompts").resolve(strict=True)),
            skills=FolderSkillCatalog((CATALOG_ROOT / "skills").resolve(strict=True)),
            profiles=FolderProfileCatalog((CATALOG_ROOT / "profiles").resolve(strict=True)),
            tools=ToolRegistryAgentCatalog(toolbelt),
            engine_tool_ceiling=admitted,
            selected_profile_versions=C6_ACTIVE_PROFILE_VERSIONS,
            surface_policies=(policy,),
        )

    with pytest.raises(AgentCatalogError, match="does not pin"):
        build(
            AgentSurfacePolicy(
                surface="typo",
                role=AgentRole.HEAD_OF_ABM,
                withheld_tools=frozenset({"submit_ingestion", "submit_ingesstion"}),
                withheld_reason_code="typo",
                framing="typo",
            )
        )

    with pytest.raises(AgentCatalogError, match="does not delegate"):
        build(
            AgentSurfacePolicy(
                surface="undelegated",
                role=AgentRole.HEAD_OF_ABM,
                withheld_tools=frozenset({"submit_ingestion"}),
                withheld_delegation_roles=frozenset({AgentRole.ACCOUNT_RESEARCH}),
                withheld_reason_code="undelegated",
                framing="undelegated",
            )
        )

    with pytest.raises(AgentCatalogError, match="withholds nothing"):
        build(
            AgentSurfacePolicy(
                surface="empty",
                role=AgentRole.HEAD_OF_ABM,
                withheld_tools=frozenset(),
                withheld_reason_code="empty",
                framing="empty",
            )
        )


def test_an_undeclared_surface_is_an_error_not_a_fall_through_to_full_authority(
    registry: AgentProfileRegistry,
) -> None:
    with pytest.raises(AgentCatalogError, match="has no surface"):
        registry.resolve(AgentRole.HEAD_OF_ABM, surface="not_a_surface")


def test_every_declared_surface_policy_resolves_at_composition(
    registry: AgentProfileRegistry,
) -> None:
    assert C6_SURFACE_POLICIES
    for policy in C6_SURFACE_POLICIES:
        resolved = registry.resolve(policy.role, surface=policy.surface)
        assert resolved.surface_policy == policy
        assert {pin.name for pin in resolved.profile.tools} & policy.withheld_tools == set()
        assert set(resolved.profile.delegation_roles) & policy.withheld_delegation_roles == set()


def test_the_operator_projection_reports_the_narrowed_surface_not_just_the_full_role(
    registry: AgentProfileRegistry,
) -> None:
    """`/agent/registry` is what an operator reads to answer "what can this agent do".

    Reporting only the role's full authority would tell them the trial can call `start_recon` and
    delegate to the research specialist. It cannot, and the projection is now the only place that
    difference is legible without reading the composition root.
    """

    entries = {entry.role: entry for entry in registry.projection().roles}
    head = entries[AgentRole.HEAD_OF_ABM]

    assert head.profile is not None
    # Every declared surface of the role is legible here, each with its own withheld set. Lane D
    # D2 added `project_conversation` (the production conversation the fleet worker runs), so the
    # projection now reports two — an operator must be able to tell them apart, which is exactly
    # what this test guards; asserting a single surface would have made adding one a silent change.
    by_surface = {item.surface: item for item in head.surfaces}
    assert set(by_surface) == {STAGE0_CONVERSATION_TRIAL_SURFACE, PROJECT_CONVERSATION_SURFACE}
    trial = by_surface[STAGE0_CONVERSATION_TRIAL_SURFACE]

    assert trial.reason_code == "trial_manual_conversation_only"
    assert set(trial.withheld_tool_names) == _WITHHELD
    assert {address.partition("@")[0] for address in trial.tool_addresses} & _WITHHELD == set()
    assert trial.delegation_roles == ()
    assert set(trial.withheld_delegation_roles) == set(head.profile.delegation_roles)
    # The digest an operator can compare against a turn's constitution.
    assert trial.resource_manifest_sha256 != head.profile.resource_manifest_sha256
    assert (
        trial.resource_manifest_sha256
        == registry.resolve(
            AgentRole.HEAD_OF_ABM, surface=STAGE0_CONVERSATION_TRIAL_SURFACE
        ).resource_manifest.aggregate_sha256
    )
    # The production conversation is reported with its own reason code and its own, *narrower*
    # subtraction: D4 earned the drafting/gate/launch tools here, and only here.
    production = by_surface[PROJECT_CONVERSATION_SURFACE]
    assert production.reason_code == "project_conversation_no_autonomous_research"
    assert set(production.withheld_tool_names) == _PROJECT_WITHHELD
    assert production.delegation_roles == ()
    # Roles with no declared surface report none rather than an empty-ish placeholder.
    assert entries[AgentRole.RESEARCH].surfaces == ()


class _Response:
    result = (AIMessage(content="ok"),)


class _ModelRequest:
    """The minimum of LangChain's model request the surface middleware actually reads."""

    def __init__(self, tool_names: tuple[str, ...]) -> None:
        self.tools = tuple(_named_tool(name) for name in tool_names)
        self.system_message = SystemMessage(content="You are the platform Head of ABM.")
        self.messages: tuple[Any, ...] = ()
        self.overrides: dict[str, Any] | None = None

    def override(self, **kwargs: Any) -> _ModelRequest:
        self.overrides = {
            **kwargs,
            "tool_names": tuple(_name(tool) for tool in kwargs.get("tools", ())),
        }
        return self


def _named_tool(name: str) -> dict[str, Any]:
    """``_tool_name`` accepts a ``BaseTool`` or the dict form; the dict is the cheap one here."""

    return {"name": name}


def _name(tool: Any) -> str:
    return str(tool["name"])


def _run(coroutine: Any) -> Any:
    from tests.db.conftest import run_async

    return run_async(coroutine)
