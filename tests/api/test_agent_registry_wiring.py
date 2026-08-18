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
    PROJECT_CONVERSATION_SURFACE,
    ToolRegistryAgentCatalog,
    build_agent_profile_registry,
)
from clue_api.chat.composer_context import (
    PROJECT_CONVERSATION_AGENT_PROFILE_ID,
    PROJECT_CONVERSATION_MODEL_ID,
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
        # head-of-abm@v22 re-pins propose_field@2 (its input schema gained FI-2's
        # FieldDef.research_scope species declaration) through stage0-interview@v10; v21 and
        # research-specialist@v7 cut over entity research to the
        # separately launched M8D create_agent fleets while retaining historical exact replay;
        # the exact-set O2 launch and truthful A2 draft preview remain the governed primitives,
        # alongside S1/E1 targeted-enrichment and dynamic Client-KB proposal/materialization
        # guidance and propose_field@2, on top of PC-C8 §6c's quote-by-text bump. The statement
        # authors the verbatim span instead of character offsets, and a typed claim value is
        # admitted by the entailment judge, on top of slice 1's closing bump (the §7
        # inspection-tool grants + delegation withholding) and task 1.4's:
        # the trial capability surface, the 8 rewritten trusted-field descriptions, the hoisted
        # nested authority, and B1 layer 2's engine-defaulted claim entity.
        # FI Lane D D4 minted head-of-abm@v23: it pins `open_directive_confirmation_gate@1` and
        # re-pins account-deep-steering at v3, whose procedure is gate-first — draft, present the
        # gate, end the turn, and launch only after the human's own confirming turn.
        # Integration v35/v20 retains bounded ICP presentation and exact scope override, keeps
        # plan-safe directive @3, and pins the registered account-research field/source vocabulary.
        # v36 (part-iii merge) is v35 plus `open_design_leg@1` — P3.4's design delegation entry,
        # with P3.5's in-train schema revision (reopen_leg_id + reopened) in the pinned digests.
        # v37 (comprehensive research, Slice B wave 2) re-pins the directive draft tool at @4 and
        # account-deep-steering at v7: a normal full-profile request now compiles deterministically
        # to the fixed 21-field account profile instead of the v6 skill's three qualitative fields.
        # v38 (Slice B browser-gate repair) re-pins the draft tool at @5 (omittable
        # `directive.field_keys`) and account-deep-steering at v8.
        AgentRole.HEAD_OF_ABM: ("f47c6db797cd13a1c4d821488df6cdd09360df651ba1451b0d8350a525c0091e"),
        AgentRole.RESEARCH: "23cff2335bb82e0549ee0c830316968971146e8b90c8d2090447ee0ed92eed6f",
        AgentRole.CONTENT_DRAFTER: (
            "8985c13ead086350d952f76e6d3c0ed3f4162cc92de290f8dd7edd7fcab44cbf"
        ),
        AgentRole.REVIEWER: "1cd0fc4e5c8276983c5e0b8d9a83904be82a95ed57f27c9c1dfd9f5a3887df46",
    }
    toolbelt = build_toolbelt(storage=None, gateway=None)
    for role, digest in expected_manifests.items():
        resolved = registry.resolve(role)
        assert resolved.profile.model.model_id == "openai/gpt-5.6-terra"
        if role is AgentRole.HEAD_OF_ABM:
            assert (
                f"{resolved.profile_ref.name}@{resolved.profile_ref.version}"
                == PROJECT_CONVERSATION_AGENT_PROFILE_ID
            )
            assert resolved.profile.model.model_id == PROJECT_CONVERSATION_MODEL_ID
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


def test_registry_projection_is_body_free_host_free_and_marks_account_role_planned(
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
    # Part II D6 Round A registers the design subsystem's eight governed write tools; they are
    # RESERVED on every model surface until Part III wires the design deepagent (55 -> 63).
    # Round B adds twenty more (documents/history/diagnostics, website documents, turn
    # enqueues), reserved identically (63 -> 83); Round C adds the final twenty-one
    # (83 -> 104), completing the design write surface. The frontend×design integration merge
    # unions FI Lane D's five (four REQ-21 thread tools + the D4 directive-confirmation gate),
    # so the merged inventory is 104 + 5 = 109. PD-part3 P3.4 adds `open_design_leg@1` — the
    # head-of-abm's delegation entry onto the design leg (109 + 1 = 110) — and P3.5 adds
    # `finish_design_leg@1`, the DESIGN-granted leg exit, role-unavailable from this view
    # (110 + 1 = 111). The part-iii integration merge unions this branch's own additions since
    # the common base (readiness/synthesis @2s, company/product readers, the exact-subject
    # gates, FI-2's selected-Account launch and reads: 111 + 18 = 129).
    # Slice B wave 2 installs `draft_account_research_directive@4` alongside its replayable
    # predecessors, so the inventory gains exactly one address (129 -> 130), and the Slice B
    # browser-gate repair installs @5 the same way (130 -> 131).
    assert len(by_address) == 131
    assert by_address["finish_design_leg@1"].status is AgentCapabilityStatus.ROLE_UNAVAILABLE
    # P3.3 retired the Part II reservation: the 49 design tools are GRANTED to
    # AgentRole.DESIGN now. From head-of-abm's view they are role-unavailable with
    # NO reason code — the same honest shape as any tool granted to another role —
    # and the retired reason must never resurface.
    assert not any(
        item.reason_code == "design_agent_not_wired_until_part_iii" for item in by_address.values()
    )
    design_addresses = {
        "design_advance_instance_batch@1",
        "design_advance_web_batch@1",
        "design_apply_edits@1",
        "design_apply_operations@1",
        "design_apply_web_operations@1",
        "design_attach_brand_kit@1",
        "design_compile_component@1",
        "design_create_brand_compatibility_report@1",
        "design_create_brand_kit@1",
        "design_create_document@1",
        "design_create_instance_batch@1",
        "design_create_snapshot@1",
        "design_create_web_account@1",
        "design_create_web_batch@1",
        "design_create_web_template@1",
        "design_delete_asset@1",
        "design_delete_binding_set@1",
        "design_delete_web_account@1",
        "design_derive_instance@1",
        "design_derive_web_document@1",
        "design_finalize_document@1",
        "design_ingest_assets@1",
        "design_ingest_pdf@1",
        "design_ingest_website@1",
        "design_persist_preflight@1",
        "design_publish_brand_kit_version@1",
        "design_publish_web@1",
        "design_record_diagnostics@1",
        "design_redo_document@1",
        "design_redo_web_document@1",
        "design_register_asset_record@1",
        "design_register_captured_assets@1",
        "design_register_generated_asset@1",
        "design_register_qr_asset@1",
        "design_replace_scene@1",
        "design_rollback_web_publish@1",
        "design_set_agent_instructions@1",
        "design_set_asset_description@1",
        "design_set_asset_status@1",
        "design_set_brand_kit_approval@1",
        "design_set_layout_managed_editing@1",
        "design_start_agent_turn@1",
        "design_start_web_turn@1",
        "design_undo_document@1",
        "design_undo_web_document@1",
        "design_unpublish_web@1",
        "design_update_web_account@1",
        "design_upsert_binding_set@1",
        "design_write_component_source@1",
    }
    for address in design_addresses:
        item = by_address[address]
        assert item.status is AgentCapabilityStatus.ROLE_UNAVAILABLE
        assert item.reason_code == "not_admitted_for_role"
    #
    # FI Lane D D0 added four more inventory-only entries — the REQ-21 thread tools. They are
    # disclosed and refused for exactly the reason every other ungranted tool is: the inventory is
    # honest about what the platform can do and what *this role* may not, and a capability the
    # model can see it lacks is what stops it inventing a workaround. Withholding them through a
    # surface policy is not an option either — a policy may only narrow tools the role's profile
    # pins, and no profile pins these.
    #
    # Lane E E1's `synthesize_entity_prose@1` likewise adds an inventory entry with no role grant
    # (machine-invoked only), so it is disclosed as unavailable to every surface; E3's
    # `synthesize_value_narrative@1` is the same shape for the same reason. Merged count: the
    # The inventory retains both versions of readiness/synthesis and company reads, the separate
    # product readers, both gate tools, and FI-2's selected-Account launch. The part-iii merge
    # adds the 49 design_* write tools and the two design-leg tools to the disclosed inventory
    # (78 + 51 = 129); all but `open_design_leg` are role-unavailable to the Head of ABM.
    # Slice B wave 2 installs `draft_account_research_directive@4` alongside its replayable
    # predecessors, so the inventory gains exactly one address (129 -> 130), and the Slice B
    # browser-gate repair installs @5 the same way (130 -> 131).
    assert len(by_address) == 131
    for address in (
        "create_thread@1",
        "rename_thread@1",
        "set_thread_pinned@1",
        "archive_thread@1",
    ):
        assert by_address[address].status is AgentCapabilityStatus.ROLE_UNAVAILABLE
    assert by_address["synthesize_entity_prose@1"].status is not AgentCapabilityStatus.AVAILABLE
    assert by_address["synthesize_value_narrative@1"].status is not AgentCapabilityStatus.AVAILABLE
    assert by_address["inspect_statement_history@1"].status is AgentCapabilityStatus.AVAILABLE
    assert by_address["inspect_readiness_history@1"].status is AgentCapabilityStatus.AVAILABLE
    assert by_address["inspect_client_claim@1"].status is AgentCapabilityStatus.ROLE_UNAVAILABLE
    assert by_address["list_client_knowledge@1"].status is AgentCapabilityStatus.ROLE_UNAVAILABLE
    assert by_address["inspect_client_claim@2"].status is AgentCapabilityStatus.AVAILABLE
    assert by_address["list_client_knowledge@2"].status is AgentCapabilityStatus.AVAILABLE
    assert by_address["inspect_product_claim@1"].status is AgentCapabilityStatus.AVAILABLE
    assert by_address["list_product_knowledge@1"].status is AgentCapabilityStatus.AVAILABLE
    assert available == {
        "draft_account_research_directive@5",
        "evaluate_stage0_readiness@2",
        "get_research_view@1",
        "inspect_readiness_history@1",
        "inspect_client_claim@2",
        "inspect_product_claim@1",
        "inspect_statement_history@1",
        "list_client_knowledge@2",
        "list_product_knowledge@1",
        "launch_account_research@1",
        "launch_selected_account_research@1",
        "launch_contact_research@1",
        "open_design_leg@1",
        "open_directive_confirmation_gate@1",
        "open_icp_confirmation_gate@1",
        "open_product_selection_gate@1",
        "propose_field@2",
        "propose_source@1",
        "read_account_research_run@1",
        "read_contact_research_run@1",
        "record_interview_answer@1",
        "open_discovery_configuration_gate@1",
        "start_confirmed_project_run@3",
        "start_recon@1",
        "submit_ingestion@1",
        "submit_onboarding_input@1",
        "synthesize_icps@3",
    }
    assert by_address["confirm_project_product@1"].status is AgentCapabilityStatus.HUMAN_ONLY
    assert by_address["evaluate_stage0_readiness@1"].status is (
        AgentCapabilityStatus.ROLE_UNAVAILABLE
    )
    assert by_address["start_confirmed_project_run@1"].status is (
        AgentCapabilityStatus.ROLE_UNAVAILABLE
    )
    assert by_address["start_confirmed_project_run@2"].status is (
        AgentCapabilityStatus.ROLE_UNAVAILABLE
    )
    assert by_address["synthesize_icps@1"].status is AgentCapabilityStatus.ROLE_UNAVAILABLE
    assert by_address["synthesize_icps@2"].status is AgentCapabilityStatus.ROLE_UNAVAILABLE
    assert (
        by_address["confirm_account_research_directive@2"].status
        is AgentCapabilityStatus.HUMAN_ONLY
    )
    assert (
        by_address["approve_contact_research_selection@1"].status
        is AgentCapabilityStatus.HUMAN_ONLY
    )
    assert (
        by_address["draft_account_research_directive@1"].status
        is AgentCapabilityStatus.ROLE_UNAVAILABLE
    )
    assert by_address["confirm_icp@1"].status is AgentCapabilityStatus.HUMAN_ONLY
    assert by_address["override_stage0_readiness@1"].status is AgentCapabilityStatus.HUMAN_ONLY
    assert by_address["propose_field@1"].status is AgentCapabilityStatus.ROLE_UNAVAILABLE
    assert by_address["propose_field@2"].status is AgentCapabilityStatus.AVAILABLE
    assert by_address["enrich_account_gaps@1"].status is AgentCapabilityStatus.REPLAY_BLOCKED
    assert by_address["enrich_selected_accounts@1"].status is AgentCapabilityStatus.REPLAY_BLOCKED
    assert by_address["launch_account_deep@1"].status is AgentCapabilityStatus.REPLAY_BLOCKED
    assert by_address["research_account_gaps@1"].status is AgentCapabilityStatus.REPLAY_BLOCKED
    assert by_address["research_account_gaps@2"].status is AgentCapabilityStatus.REPLAY_BLOCKED
    assert by_address["profile_contact@1"].status is AgentCapabilityStatus.REPLAY_BLOCKED
    assert "framework task/subagent: unavailable" in head.generated_resource_map
    assert "delegate_specialist: available" in head.generated_resource_map
    assert "execute/shell/process: unavailable" in head.generated_resource_map
    assert "/Users/" not in head.generated_resource_map
    assert head.system_prompt.endswith("## End resolved resource and capability map")


def test_s4e_production_project_surface_resolves_strict_client_kb_v2_and_hardening() -> None:
    """The cutover must be on the real fleet surface, not only a base profile or test builder."""

    with hermetic_flag_env():
        toolbelt = build_toolbelt(storage=None, gateway=None)
        registry = build_agent_profile_registry(toolbelt)
    production = registry.resolve(
        AgentRole.HEAD_OF_ABM,
        surface=PROJECT_CONVERSATION_SURFACE,
    )

    addresses = {pin.address for pin in production.profile.tools}
    assert production.profile_ref.address == "profile:head-of-abm@v38"
    assert [item.resource.address for item in production.skill_disclosures()][0] == (
        "skill:stage0-interview@v20"
    )
    assert {"list_client_knowledge@2", "inspect_client_claim@2"} <= addresses
    assert {"list_product_knowledge@1", "inspect_product_claim@1"} <= addresses
    assert "open_product_selection_gate@1" in addresses
    assert {"list_client_knowledge@1", "inspect_client_claim@1"}.isdisjoint(addresses)
    assert toolbelt.descriptor("list_client_knowledge").address == "list_client_knowledge@2"
    assert toolbelt.descriptor("inspect_client_claim").address == "inspect_client_claim@2"


def test_stage0_skill_routes_first_selected_product_fact_without_a_product_kb() -> None:
    """No published Product-KB blocks reads, not the first governed human-authored write."""

    with hermetic_flag_env():
        registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    production = registry.resolve(
        AgentRole.HEAD_OF_ABM,
        surface=PROJECT_CONVERSATION_SURFACE,
    )
    body = production.open_skill("skill:stage0-interview@v20")

    assert "A missing Product-KB card blocks historical product-knowledge reads" in body
    assert "not block a human from supplying the first fact" in body
    assert "Never leave a clearly matching fact unmapped" in body
    assert "`client.product_use_case`" in body
    assert "publishes Product-KB v1" in body


def test_account_research_role_and_surface_are_not_active(
    registry: AgentProfileRegistry,
) -> None:
    assert AgentRole.ACCOUNT_RESEARCH not in C6_ACTIVE_PROFILE_VERSIONS
    with pytest.raises(AgentCatalogError, match="no active profile"):
        registry.resolve(AgentRole.ACCOUNT_RESEARCH)
    with pytest.raises(AgentCatalogError, match="no surface"):
        registry.resolve(AgentRole.ACCOUNT_RESEARCH, surface="account_research_unit")


def test_progressive_skill_disclosure_exposes_metadata_before_body(
    registry: AgentProfileRegistry,
) -> None:
    head = registry.resolve(AgentRole.HEAD_OF_ABM)
    disclosures = head.skill_disclosures()

    assert len(disclosures) == 2
    assert disclosures[0].resource.address == "skill:stage0-interview@v20"
    assert disclosures[1].resource.address == "skill:account-deep-steering@v8"
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
            "skill:research-task@v4",
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


def test_c67_account_deepagent_profile_is_historical_only(
    registry: AgentProfileRegistry,
) -> None:
    del registry
    historical = CATALOG_ROOT / "profiles" / "account-research" / "v3" / "profile.yaml"
    assert historical.is_file()
    assert "research_account_gaps" in historical.read_text()
    assert AgentRole.ACCOUNT_RESEARCH not in C6_ACTIVE_PROFILE_VERSIONS


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
        ("confirmed_start", "After the human approves the ICP"),
    ),
)
def test_stage0_quality_fixture_has_explicit_governed_behavior(
    registry: AgentProfileRegistry,
    fixture: str,
    required_guidance: str,
) -> None:
    del fixture
    head = registry.resolve(AgentRole.HEAD_OF_ABM)
    body = head.open_skill("skill:stage0-interview@v20")

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
    admitted.remove("evaluate_stage0_readiness@2")
    narrowed = AgentProfileRegistry(
        prompts=FolderPromptCatalog((CATALOG_ROOT / "prompts").resolve(strict=True)),
        skills=FolderSkillCatalog((CATALOG_ROOT / "skills").resolve(strict=True)),
        profiles=FolderProfileCatalog((CATALOG_ROOT / "profiles").resolve(strict=True)),
        tools=ToolRegistryAgentCatalog(toolbelt),
        engine_tool_ceiling=frozenset(admitted),
        selected_profile_versions=C6_ACTIVE_PROFILE_VERSIONS,
    )

    head = narrowed.resolve(AgentRole.HEAD_OF_ABM)
    assert "evaluate_stage0_readiness@2" not in {pin.address for pin in head.profile.tools}
    assert [item.resource.address for item in head.skill_disclosures()] == [
        "skill:account-deep-steering@v8"
    ]


def test_resolved_snapshot_materializes_through_c61_backend(
    registry: AgentProfileRegistry,
    tmp_path: Path,
) -> None:
    resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
    stage0_skill = next(
        skill for skill in resolved.profile.skills if skill.resource.name == "stage0-interview"
    )
    harness = make_workspace(tmp_path, active_policy=resolved.profile.workspace)
    try:
        AgentResourceMaterializer().materialize(
            lease=harness.lease,
            snapshot=resolved.resource_snapshot,
        )
        assert harness.lease.resources_frozen
        assert (
            harness.lease.backend.stat_entry_sync(stage0_skill.materialized_path).sha256
            == stage0_skill.resource.sha256
        )
    finally:
        harness.close()


def test_changed_resource_or_tool_schema_fails_before_profile_use(tmp_path: Path) -> None:
    copied = tmp_path / "catalog"
    shutil.copytree(CATALOG_ROOT, copied)
    prompt = copied / "prompts/head-of-abm/v4/SYSTEM.md"
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


def test_design_profile_resolves_with_the_full_granted_write_surface(
    registry: AgentProfileRegistry,
) -> None:
    """P3.3 (PD-part3): the composite design deepagent's platform-facing profile.

    One role, a doorway, not a container (ruling D2): design@v1 resolves with ALL 49
    governed design tools pinned and AVAILABLE from its own view — exactly the
    authority the C6 audit grants and nothing else — no delegation, and the
    P3.2-gate-ratified model policy on its face. P3.5 adds the fiftieth pin:
    `finish_design_leg@1`, the leg-level exit (§2.2) — the composite's one doorway
    back to head-of-abm.
    """
    resolved = registry.resolve(AgentRole.DESIGN)
    assert resolved.profile.version == "v1"
    assert len(resolved.profile.tools) == 50
    assert sum(1 for pin in resolved.profile.tools if pin.name.startswith("design_")) == 49
    assert any(pin.address == "finish_design_leg@1" for pin in resolved.profile.tools)

    by_address = {item.address: item for item in resolved.capabilities}
    available = {
        address
        for address, item in by_address.items()
        if item.status is AgentCapabilityStatus.AVAILABLE
    }
    assert available == {pin.address for pin in resolved.profile.tools}

    assert resolved.profile.delegation_roles == ()
    assert resolved.profile.model.model_id == "openai/gpt-5.6-terra"
    assert resolved.profile.max_delegation_depth == 0
