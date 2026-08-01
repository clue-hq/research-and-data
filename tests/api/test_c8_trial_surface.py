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
    STAGE0_CONVERSATION_TRIAL_SURFACE,
    ToolRegistryAgentCatalog,
    build_agent_profile_registry,
)
from clue_api.toolbelt_wiring import build_toolbelt
from tests.api.conftest import hermetic_flag_env
from tests.api.test_agent_registry_wiring import CATALOG_ROOT

_WITHHELD = {"start_recon", "submit_onboarding_input", "synthesize_icps"}


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
    assert "start_recon" not in trial_names
    assert "synthesize_icps" not in trial_names
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
        disclosure = by_address[f"{name}@1"]
        assert disclosure.status is AgentCapabilityStatus.PROFILE_UNAVAILABLE
        assert disclosure.reason_code == "trial_manual_conversation_only"
        assert f"- {name}@1 effect=" not in generated

    assert "manual-conversation-only" in generated
    assert f"surface={STAGE0_CONVERSATION_TRIAL_SURFACE}" in generated


def test_the_stage0_skill_survives_the_narrowed_surface(
    registry: AgentProfileRegistry,
) -> None:
    """The regression this design could most easily have shipped, silently.

    Skills are dropped when a required tool is not effective, so a skill that still *required*
    ``start_recon``/``synthesize_icps``/``submit_onboarding_input`` would vanish from the trial
    entirely — restricting three tools would quietly also remove all of Stage-0's routing
    procedure, and nothing else in this file would have noticed.
    """

    trial = registry.resolve(AgentRole.HEAD_OF_ABM, surface=STAGE0_CONVERSATION_TRIAL_SURFACE)
    disclosures = trial.skill_disclosures()

    assert [item.resource.address for item in disclosures] == ["skill:stage0-interview@v7"]
    required = {address.partition("@")[0] for address in disclosures[0].required_tool_addresses}
    assert required & _WITHHELD == set()
    body = trial.open_skill("skill:stage0-interview@v7")
    assert "Ask one compact question" in body
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
        "delegate_specialist",
    )

    async def handler(_request: Any) -> Any:
        return _Response()

    ok = _ModelRequest(installed)
    _run(middleware.awrap_model_call(ok, handler))
    assert ok.overrides is not None
    assert set(ok.overrides["tool_names"]) & _WITHHELD == set()

    smuggled = _ModelRequest((*installed, "start_recon"))
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
                withheld_tools=frozenset({"start_recon", "start_reccon"}),
                withheld_reason_code="typo",
                framing="typo",
            )
        )

    with pytest.raises(AgentCatalogError, match="withholds no tool"):
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
