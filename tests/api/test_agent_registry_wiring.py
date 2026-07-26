from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from clue_agents import (
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
    C6_AGENT_TOOL_AUTHORITY,
    ToolRegistryAgentCatalog,
    build_agent_profile_registry,
)
from clue_api.toolbelt_wiring import build_toolbelt
from tests.agents.workspace_helpers import make_workspace

CATALOG_ROOT = Path(__file__).resolve().parents[2] / "platform" / "agents" / "catalog"


@pytest.fixture(scope="module")
def registry() -> AgentProfileRegistry:
    return build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))


def test_registry_resolves_exact_reviewed_profiles_and_stable_manifests(
    registry: AgentProfileRegistry,
) -> None:
    expected_manifests = {
        AgentRole.HEAD_OF_ABM: "6b15dab49e5ad1a05ebe109818da734ae65863be8be8cd27bd0d6061908d6737",
        AgentRole.RESEARCH: "8cec89e9cb14b542a398c9bb269edaac694b89f01f280a2904f452aab0c83d72",
        AgentRole.CONTENT_DRAFTER: (
            "b18a15731fe2b494f6ece1ca0a39fbc22464eabc2d966e6d84229cc5f637facd"
        ),
        AgentRole.REVIEWER: "d1564ba5a8ae37a7704d7ccb2c080767236b81bb7979eecf1027fafd92681c32",
    }
    toolbelt = build_toolbelt(storage=None, gateway=None)
    for role, digest in expected_manifests.items():
        resolved = registry.resolve(role)
        expected_tools = {
            f"{name}@{toolbelt.descriptor(name).version}"
            for name, roles in C6_AGENT_TOOL_AUTHORITY.items()
            if role in roles
        }
        assert {pin.address for pin in resolved.profile.tools} == expected_tools
        assert resolved.resource_manifest.aggregate_sha256 == digest
        assert all(body.ref in resolved.resource_map for body in resolved.resource_snapshot.bodies)


def test_registry_projection_is_body_free_host_free_and_marks_future_role_planned(
    registry: AgentProfileRegistry,
) -> None:
    projection = registry.projection()
    payload = json.dumps(projection.model_dump(mode="json"), sort_keys=True)
    entries = {entry.role: entry for entry in projection.roles}

    assert entries[AgentRole.ACCOUNT_RESEARCH].status is RoleRegistryStatus.PLANNED
    assert entries[AgentRole.ACCOUNT_RESEARCH].profile is None
    assert entries[AgentRole.HEAD_OF_ABM].status is RoleRegistryStatus.ACTIVE
    assert "You are the platform Head of ABM" not in payload
    assert "Ask from the current readiness gaps" not in payload
    assert str(CATALOG_ROOT) not in payload
    assert "/Users/" not in payload


def test_progressive_skill_disclosure_exposes_metadata_before_body(
    registry: AgentProfileRegistry,
) -> None:
    head = registry.resolve(AgentRole.HEAD_OF_ABM)
    disclosures = head.skill_disclosures()

    assert len(disclosures) == 1
    assert disclosures[0].resource.address == "skill:stage0-interview@v2"
    assert "Ask from the current readiness gaps" not in disclosures[0].model_dump_json()
    body = head.open_skill(disclosures[0].resource.address)
    assert "Ask from the current readiness gaps" in body
    with pytest.raises(AgentCatalogError, match="not disclosed"):
        head.open_skill("skill:unknown@v1")


def test_delegation_compiles_strict_tool_and_workspace_subsets(
    registry: AgentProfileRegistry,
) -> None:
    head = registry.resolve(AgentRole.HEAD_OF_ABM)
    research = registry.resolve_delegation(
        parent=head,
        child_role=AgentRole.RESEARCH,
        current_depth=0,
    )
    grant = {pin.address for pin in head.delegation_tool_grants[AgentRole.RESEARCH]}

    assert {pin.address for pin in research.profile.tools} <= grant
    assert research.profile.workspace.max_total_bytes <= head.profile.workspace.max_total_bytes
    assert set(research.profile.workspace.writable_prefixes) <= set(
        head.profile.workspace.writable_prefixes
    )
    with pytest.raises(AgentCatalogError, match="not delegated"):
        registry.resolve_delegation(
            parent=head,
            child_role=AgentRole.ACCOUNT_RESEARCH,
            current_depth=0,
        )
    with pytest.raises(AgentCatalogError, match="depth"):
        registry.resolve_delegation(
            parent=head,
            child_role=AgentRole.RESEARCH,
            current_depth=1,
        )


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
                ".deepagent/skills/stage0-interview/v2/SKILL.md"
            ).sha256
            == resolved.profile.skills[0].resource.sha256
        )
    finally:
        harness.close()


def test_changed_resource_or_tool_schema_fails_before_profile_use(tmp_path: Path) -> None:
    copied = tmp_path / "catalog"
    shutil.copytree(CATALOG_ROOT, copied)
    prompt = copied / "prompts/head-of-abm/v1/SYSTEM.md"
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
        )
