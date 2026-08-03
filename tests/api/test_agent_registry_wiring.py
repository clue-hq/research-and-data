from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from clue_agents import (
    AgentCapabilityStatus,
    AgentCatalogError,
    AgentProfileRegistry,
    AgentResourceMaterializer,
    AgentRole,
    AgentToolContract,
    FolderProfileCatalog,
    FolderPromptCatalog,
    FolderSkillCatalog,
    RoleRegistryStatus,
    ToolPin,
)
from clue_api.agent_registry_wiring import (
    C6_ACTIVE_PROFILE_VERSIONS,
    C6_AGENT_TOOL_AUTHORITY,
    ToolRegistryAgentCatalog,
    build_agent_profile_registry,
)
from clue_api.toolbelt_wiring import build_toolbelt
from tests.agents.workspace_helpers import make_workspace
from tests.api.conftest import hermetic_flag_env

CATALOG_ROOT = Path(__file__).resolve().parents[2] / "platform" / "agents" / "catalog"


@pytest.fixture(scope="module")
def registry() -> AgentProfileRegistry:
    # ``build_toolbelt`` falls back to the production ``load_settings()``, so this registry would
    # otherwise resolve tools against the operator's live activation flags: pytest builds a
    # module-scoped fixture *before* the autouse function-scoped ``_hermetic_feature_flags``, so
    # this one enters the shared neutralisation itself. (Kept module-scoped — rebuilding the
    # catalog per test costs ~5s across this file.)
    with hermetic_flag_env():
        return build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))


def test_registry_resolves_exact_reviewed_profiles_and_stable_manifests(
    registry: AgentProfileRegistry,
) -> None:
    expected_manifests = {
        # head-of-abm@v12 / stage0-interview@v9 — dynamic Client-KB proposal/materialization
        # guidance and propose_field@2, on top of PC-C8 §6c's quote-by-text bump. The statement
        # authors the verbatim span instead of character offsets, and a typed claim value is
        # admitted by the entailment judge, on top of slice 1's closing bump (the §7
        # inspection-tool grants + delegation withholding) and task 1.4's:
        # the trial capability surface, the 8 rewritten trusted-field descriptions, the hoisted
        # nested authority, and B1 layer 2's engine-defaulted claim entity.
        AgentRole.HEAD_OF_ABM: "d5df9357891f3894e9182331842469aa7f27c53b3040eac8b47966940d7f05c9",
        AgentRole.RESEARCH: "4bf40eee2b8e6f6d98a0ee295e3ff900243e162eae53cc6c8852e70521aef391",
        AgentRole.CONTENT_DRAFTER: (
            "f4095d62dfc9bc734aa2acb111270a3f10e2242a252e96c229d464435b7a90bc"
        ),
        AgentRole.REVIEWER: "b4859443637154e4e10a6598f17c2f54b0688f6faea2696e9a7ff4cf3a3f0deb",
        AgentRole.ACCOUNT_RESEARCH: (
            "c4aa0f4f8c3d660d0dc5ef2ee85b7e39077c07f918d22118a5800cb63da35b06"
        ),
    }
    toolbelt = build_toolbelt(storage=None, gateway=None)
    for role, digest in expected_manifests.items():
        resolved = registry.resolve(role)
        assert resolved.profile.model.model_id == "openai/gpt-5.6-terra"
        expected_tools = {
            (
                "research_account_gaps@2"
                if name == "research_account_gaps"
                else f"{name}@{toolbelt.descriptor(name).version}"
            )
            for name, roles in C6_AGENT_TOOL_AUTHORITY.items()
            if role in roles
        }
        assert {pin.address for pin in resolved.profile.tools} == expected_tools
        assert resolved.resource_manifest.aggregate_sha256 == digest
        assert all(body.ref in resolved.resource_map for body in resolved.resource_snapshot.bodies)


def test_registry_projection_is_body_free_host_free_and_marks_account_role_active(
    registry: AgentProfileRegistry,
) -> None:
    projection = registry.projection()
    payload = json.dumps(projection.model_dump(mode="json"), sort_keys=True)
    entries = {entry.role: entry for entry in projection.roles}

    assert entries[AgentRole.ACCOUNT_RESEARCH].status is RoleRegistryStatus.ACTIVE
    assert entries[AgentRole.ACCOUNT_RESEARCH].profile is not None
    assert entries[AgentRole.HEAD_OF_ABM].status is RoleRegistryStatus.ACTIVE
    assert "You are the platform Head of ABM" not in payload
    assert "Ask from the current readiness gaps" not in payload
    assert str(CATALOG_ROOT) not in payload
    assert "/Users/" not in payload


def test_head_resource_map_is_exhaustive_generated_and_structurally_minimal(
    registry: AgentProfileRegistry,
) -> None:
    head = registry.resolve(AgentRole.HEAD_OF_ABM)
    by_address = {item.address: item for item in head.capabilities}
    available = {
        address
        for address, item in by_address.items()
        if item.status is AgentCapabilityStatus.AVAILABLE
    }

    # The two proposal v1 addresses remain installed only for historical recipe replay. They add
    # inventory entries but cannot enter the current model surface; only propose_field@2 carries
    # the dynamic Client-KB authority.
    assert len(by_address) == 40
    assert by_address["inspect_statement_history@1"].status is AgentCapabilityStatus.AVAILABLE
    assert by_address["inspect_readiness_history@1"].status is AgentCapabilityStatus.AVAILABLE
    assert available == {
        "evaluate_stage0_readiness@1",
        "get_research_view@1",
        "inspect_readiness_history@1",
        "inspect_statement_history@1",
        "propose_field@2",
        "propose_source@1",
        "record_interview_answer@1",
        "start_confirmed_project_run@1",
        "start_recon@1",
        "submit_ingestion@1",
        "submit_onboarding_input@1",
        "synthesize_icps@1",
    }
    assert by_address["confirm_project_product@1"].status is AgentCapabilityStatus.HUMAN_ONLY
    assert by_address["confirm_icp@1"].status is AgentCapabilityStatus.HUMAN_ONLY
    assert by_address["override_stage0_readiness@1"].status is AgentCapabilityStatus.HUMAN_ONLY
    assert by_address["propose_field@1"].status is AgentCapabilityStatus.ROLE_UNAVAILABLE
    assert by_address["propose_field@2"].status is AgentCapabilityStatus.AVAILABLE
    assert by_address["research_account_gaps@1"].status is AgentCapabilityStatus.REPLAY_BLOCKED
    assert by_address["research_account_gaps@2"].status is AgentCapabilityStatus.ROLE_UNAVAILABLE
    assert "framework task/subagent: unavailable" in head.generated_resource_map
    assert "delegate_specialist: available" in head.generated_resource_map
    assert "execute/shell/process: unavailable" in head.generated_resource_map
    assert "/Users/" not in head.generated_resource_map
    assert head.system_prompt.endswith("## End resolved resource and capability map")


def test_progressive_skill_disclosure_exposes_metadata_before_body(
    registry: AgentProfileRegistry,
) -> None:
    head = registry.resolve(AgentRole.HEAD_OF_ABM)
    disclosures = head.skill_disclosures()

    assert len(disclosures) == 1
    assert disclosures[0].resource.address == "skill:stage0-interview@v9"
    assert "Ask one compact question" not in disclosures[0].model_dump_json()
    body = head.open_skill(disclosures[0].resource.address)
    assert "Ask one compact question" in body
    with pytest.raises(AgentCatalogError, match="not disclosed"):
        head.open_skill("skill:unknown@v1")


@pytest.mark.parametrize(
    ("role", "skill_address", "required_output", "timeout", "rounds"),
    (
        (
            AgentRole.RESEARCH,
            "skill:research-task@v1",
            "outputs/research-strategy.md",
            180.0,
            16,
        ),
        (
            AgentRole.CONTENT_DRAFTER,
            "skill:content-exemplar@v1",
            "outputs/content-exemplar.md",
            120.0,
            12,
        ),
        (
            AgentRole.REVIEWER,
            "skill:artifact-review@v1",
            "outputs/review-verdict.md",
            90.0,
            10,
        ),
    ),
)
def test_c66_specialists_freeze_skill_output_budget_and_no_child_delegation(
    registry: AgentProfileRegistry,
    role: AgentRole,
    skill_address: str,
    required_output: str,
    timeout: float,
    rounds: int,
) -> None:
    resolved = registry.resolve(role)

    assert [item.resource.address for item in resolved.skill_disclosures()] == [skill_address]
    assert required_output in resolved.open_skill(skill_address)
    assert resolved.profile.turn_timeout_s == timeout
    assert resolved.profile.max_model_rounds == rounds
    assert resolved.profile.delegation_roles == ()
    assert "delegate_specialist: unavailable" in resolved.generated_resource_map


def test_c67_account_profile_has_read_plus_one_write_tool_and_no_self_evaluator_or_delegation(
    registry: AgentProfileRegistry,
) -> None:
    resolved = registry.resolve(AgentRole.ACCOUNT_RESEARCH)

    assert [item.address for item in resolved.profile.tools] == [
        "get_research_view@1",
        "research_account_gaps@2",
    ]
    assert [item.resource.address for item in resolved.skill_disclosures()] == [
        "skill:account-gap-research@v1"
    ]
    assert resolved.profile.delegation_roles == ()
    assert resolved.profile.max_delegations == 0
    assert "The independent C1 evaluator is not you" in resolved.prompt_body
    skill = resolved.open_skill("skill:account-gap-research@v1")
    assert "creates no attempt or terminal decision" in skill
    assert "GoalJudge" not in resolved.generated_resource_map


@pytest.mark.parametrize(
    ("fixture", "required_guidance"),
    (
        ("url_only", "capture the URL as onboarding input, then start one governed recon"),
        ("known_product", "show the current product candidate and ask the human to confirm"),
        ("stale_product", "name the stale evidence and ask for the smallest refresh needed"),
        ("contradictory_correction", "preserve the new exact quote and route it as a correction"),
        ("upload", "submit an already captured workspace artifact through `submit_ingestion`"),
        ("novel_field", "goes through `propose_field` or"),
        ("novel_source", "or\n  `propose_source`"),
        ("missing_readiness_floor", "cannot turn a failing deterministic result into ready"),
        ("human_override", "records a readiness override"),
        ("confirmed_start", "durable product and ICP confirmations exist"),
    ),
)
def test_stage0_quality_fixture_has_explicit_governed_behavior(
    registry: AgentProfileRegistry,
    fixture: str,
    required_guidance: str,
) -> None:
    del fixture
    head = registry.resolve(AgentRole.HEAD_OF_ABM)
    body = head.open_skill("skill:stage0-interview@v9")

    assert required_guidance in body


def test_head_delegates_only_to_c66_specialists_with_narrowed_authority(
    registry: AgentProfileRegistry,
) -> None:
    head = registry.resolve(AgentRole.HEAD_OF_ABM)
    assert head.profile.delegation_roles == (
        AgentRole.RESEARCH,
        AgentRole.CONTENT_DRAFTER,
        AgentRole.REVIEWER,
    )
    for role in head.profile.delegation_roles:
        child = registry.resolve_delegation(
            parent=head,
            child_role=role,
            current_depth=0,
        )
        assert child.profile.role is role
        assert child.profile.delegation_roles == ()
        assert set(child.profile.tools) <= set(head.delegation_tool_grants[role])


def test_engine_ceiling_removes_tools_and_skills_that_depend_on_them() -> None:
    toolbelt = build_toolbelt(storage=None, gateway=None)
    admitted = {
        toolbelt.descriptor(name).address
        for name, roles in C6_AGENT_TOOL_AUTHORITY.items()
        if roles
    }
    admitted.remove("evaluate_stage0_readiness@1")
    narrowed = AgentProfileRegistry(
        prompts=FolderPromptCatalog((CATALOG_ROOT / "prompts").resolve(strict=True)),
        skills=FolderSkillCatalog((CATALOG_ROOT / "skills").resolve(strict=True)),
        profiles=FolderProfileCatalog((CATALOG_ROOT / "profiles").resolve(strict=True)),
        tools=ToolRegistryAgentCatalog(toolbelt),
        engine_tool_ceiling=frozenset(admitted),
        selected_profile_versions=C6_ACTIVE_PROFILE_VERSIONS,
    )

    head = narrowed.resolve(AgentRole.HEAD_OF_ABM)
    assert "evaluate_stage0_readiness@1" not in {pin.address for pin in head.profile.tools}
    assert head.profile.skills == ()
    assert head.skill_disclosures() == ()


def test_resolved_snapshot_materializes_through_c61_backend(
    registry: AgentProfileRegistry,
    tmp_path: Path,
) -> None:
    resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
    harness = make_workspace(tmp_path, active_policy=resolved.profile.workspace)
    try:
        AgentResourceMaterializer().materialize(
            lease=harness.lease,
            snapshot=resolved.resource_snapshot,
        )
        assert harness.lease.resources_frozen
        assert (
            harness.lease.backend.stat_entry_sync(
                ".deepagent/skills/stage0-interview/v9/SKILL.md"
            ).sha256
            == resolved.profile.skills[0].resource.sha256
        )
    finally:
        harness.close()


def test_changed_resource_or_tool_schema_fails_before_profile_use(tmp_path: Path) -> None:
    copied = tmp_path / "catalog"
    shutil.copytree(CATALOG_ROOT, copied)
    prompt = copied / "prompts/head-of-abm/v3/SYSTEM.md"
    prompt.write_text(prompt.read_text() + "\nChanged under the same version.\n")
    toolbelt = build_toolbelt(storage=None, gateway=None)
    admitted = frozenset(
        toolbelt.descriptor(name).address
        for name, roles in C6_AGENT_TOOL_AUTHORITY.items()
        if roles
    )
    with pytest.raises(AgentCatalogError, match="content digest changed"):
        AgentProfileRegistry(
            prompts=FolderPromptCatalog((copied / "prompts").resolve(strict=True)),
            skills=FolderSkillCatalog((copied / "skills").resolve(strict=True)),
            profiles=FolderProfileCatalog((copied / "profiles").resolve(strict=True)),
            tools=ToolRegistryAgentCatalog(toolbelt),
            engine_tool_ceiling=admitted,
            selected_profile_versions=C6_ACTIVE_PROFILE_VERSIONS,
        )

    class _DriftedTools:
        def resolve(self, pin: ToolPin) -> AgentToolContract:
            return AgentToolContract(
                pin=pin.model_copy(update={"input_schema_sha256": "0" * 64}),
                recipe_safe=True,
                steering=False,
            )

    with pytest.raises(AgentCatalogError, match="schema digest changed"):
        AgentProfileRegistry(
            prompts=FolderPromptCatalog((CATALOG_ROOT / "prompts").resolve(strict=True)),
            skills=FolderSkillCatalog((CATALOG_ROOT / "skills").resolve(strict=True)),
            profiles=FolderProfileCatalog((CATALOG_ROOT / "profiles").resolve(strict=True)),
            tools=_DriftedTools(),
            engine_tool_ceiling=admitted,
            selected_profile_versions=C6_ACTIVE_PROFILE_VERSIONS,
        )
