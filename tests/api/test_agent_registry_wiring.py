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
from clue_agents.manual.build import MANUAL_CHAPTERS
from clue_api.agent_registry_wiring import (
    C6_ACTIVE_PROFILE_VERSIONS,
    C6_AGENT_TOOL_AUTHORITY,
    ONBOARDING_ICP_SURFACE,
    PROJECT_CONVERSATION_SURFACE,
    ToolRegistryAgentCatalog,
    build_agent_profile_registry,
)
from clue_api.chat.composer_context import (
    PROJECT_CONVERSATION_AGENT_PROFILE_ID,
    PROJECT_CONVERSATION_MODEL_ID,
)
from clue_api.toolbelt_wiring import build_toolbelt
from tests._model_ids import assert_well_formed_model_id
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
    # The same reasoning covers the per-role model channel. ``_env_model_policy`` reads
    # ``<ROLE>_AGENT_MODEL`` straight from ``os.environ`` (not through ``Settings``), so
    # ``hermetic_flag_env`` cannot reach it, and an operator shell that sourced the repo ``.env``
    # — which pins every role to grok-4.6 — would make this file assert the deployment setting
    # instead of the reviewed catalog pin. Resolution is eager, so stripping the overrides around
    # the build is enough.
    with hermetic_flag_env(), pytest.MonkeyPatch.context() as mp:
        for role in AgentRole:
            mp.delenv(f"{role.value.upper()}_AGENT_MODEL", raising=False)
        # The deployment-wide per-call timeout override (2026-09-08) rides the same seam.
        mp.delenv("CLUE_AGENT_MODEL_TIMEOUT_S", raising=False)
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
        # v37 (genweb slice 2) is v36 with that entry promoted to `open_design_leg@2` (a
        # document-less open births the web document) and prompt v5's design-delegation teaching.
        # v38 (genad) is v37 with the entry promoted again to `open_design_leg@3` (a document-less
        # `doc_kind='scene'` open births the ad document at a named format) and prompt v6's
        # infer-and-state ad-format guidance.
        # v39 (genad2) is v38 with the entry promoted once more to `open_design_leg@4` (the scene
        # births ZERO pages; the design agent authors them, and the format inputs are deleted) and
        # prompt v7's route-and-delegate guidance, which states no dimension at all.
        # v41 (comprehensive research, Slice B wave 2) re-pins the directive draft tool at @4 and
        # account-deep-steering at v7: a normal full-profile request now compiles deterministically
        # to the fixed 21-field account profile instead of the v6 skill's three qualitative fields.
        # v42 (Slice B browser-gate repair) re-pins the draft tool at @5 (omittable
        # `directive.field_keys`) and account-deep-steering at v8, and re-pins the amended v8 sha
        # after the committee co-definition section (founder ruling 2026-08-20: the deepagent
        # settles product and the four persona positions with the user before drafting a
        # committee-discovering directive, and the plan carries the outcome).
        # v43 (ARV2-R0 merge) is v40 plus v42's directive contract — `draft_account_research_
        # directive@5` and account-deep-steering v8 — and nothing else; v40 and v42 were divergent
        # siblings (v42 pins the retired `open_design_leg@1`), so the merge minted the join rather
        # than promoting either. Digest measured off the merged tree.
        # v44 (ARV2 onboarding O6) is v43 with the new-lane Stage-0 surface: prompt v8 and
        # stage0-interview v21 (read the brand's knowledge documents, propose from the ICP files,
        # open the product-set and ICP gates, launch on the ARV2 lane), the twelve old-lane
        # recon/readiness/Client-KB/Product-KB/`icp_spec` tools dropped, and
        # `open_product_set_selection_gate@1`, `open_icp_confirmation_gate@2`,
        # `launch_arv2_account_research@1` and `read_arv2_account_research_run@1` pinned in their
        # place. Founder rulings 2 and 3 (2026-09-10) finish the swap: the five old-research-lane
        # tools and the `account-deep-steering@v8` skill that required all five are dropped, and
        # `launch_arv2_person_research@1` is pinned — so stage0-interview v21 is the profile's one
        # skill and the ARV2 trio is its one research lane. Model, workspace, delegation and limits
        # are v43's. Digest measured off this tree.
        # v45 (ARV2 R4) is v44 plus `launch_arv2_discovery@1` and stage0-interview v22 (§7b,
        # discover accounts for the project). v46 (ARV2 context and authoring) is v45 plus
        # `author_icp_document@1` and `request_persona_synthesis@1` and stage0-interview v23
        # (§5b authoring, §5c personas). v47 (the project plan) is v46 plus
        # `write_project_document@1` and stage0-interview v24 (§6b, write the plan). v48 (the ARV2
        # reads) is v47 plus `read_project_accounts@1`, `read_account_research@1` and
        # `read_discovery_run@1` and stage0-interview v25 (§7c, read before you speak). v49 and
        # v50 add no address: v49 re-pinned the three reads' typed contracts with
        # stage0-interview v26, and v50 re-pins the hotfix contracts (`read_account_research`
        # paged and prefix-naming, `read_discovery_run`'s repaired input) with
        # stage0-interview v27. v51 adds no address either: it moves the workspace block to the
        # thread layout (`scratch/`/`reads/` granted, `work/` dropped, quota raised) and pins
        # stage0-interview v28, whose §1 names the notebook — the skill body is in the manifest,
        # so the digest moves. v52 adds no address either: it grants the `brand/` and `project/`
        # read-only library mounts and pins stage0-interview v29 and prompt head-of-abm v9, which
        # name those mounted paths instead of the per-turn seeds under `inputs/`; the prompt and
        # the skill body are both in the manifest, so the digest moves again. v53 adds no address
        # either: it pins stage0-interview v30, which names the brand library's manifest at its
        # real mounted path (`brand/index.json`, the tree root) — the skill body is in the
        # manifest, so the digest moves once more. v54 adds no address either: it discloses the
        # fifteen `manual-*@v1` chapters (each granting no tool), pins prompt v10 and skill v31,
        # and every one of those bodies is in the manifest, so the digest moves again. v55 is the
        # first version that SUBTRACTS: `author_icp_document@1`, `request_persona_synthesis@1` and
        # `write_project_document@1` are ungranted, because `project/` is writable now and the
        # three documents they wrote are written as files. It pins stage0-interview v32, the three
        # document skills (`icp-authoring@v1`, `persona-authoring@v1`, `plan-authoring@v1`, none of
        # which grants a tool) and the re-minted `manual-*@v2` chapters, so the digest moves for
        # both reasons at once. v56 moves it for three reasons: two granted addresses change
        # version (`read_account_research@1`/`read_discovery_run@1` -> their paged `@2`s, a
        # different input digest), two are added (`read_claims@1`, `read_artifact@1`), and every
        # pinned skill body in the manifest is new — stage0-interview v33, the document skills at
        # v2, the re-minted `manual-*@v3`. v57 moves it for neither reason: no tool and no grant
        # change at all. It raises `turn_timeout_s` to 1800 and `max_model_rounds` to 100 — the
        # founder's numbers, after a real plan-draft turn was cut mid-thought at the 300-second
        # cap — and the manifest carries the limits and the `manual-*@v4` bodies its generated
        # `limits` chapter renders them into, so the digest moves on those alone. v58 moves it for
        # both reasons at once: one address is ADDED (`run_python@1`, the code sandbox, granted
        # here for the first time) and every pinned body in the manifest is new — prompt v11,
        # stage0-interview v34, the new `code-execution@v1`, and the re-minted `manual-*@v5`.
        # v59 moves it for both reasons again: one granted address changes version
        # (`open_design_leg@4` -> `@5`, a different input digest, so one ask can open one leg that
        # births many artifacts) and two pinned bodies in the manifest are new — prompt v12 and
        # the re-minted `manual-*@v6`. v60 moves it for neither reason: no tool and no grant
        # change at all, just prompt v13 (one sentence: opening a leg starts generation at once)
        # and the `manual-*@v7` bodies that render this profile version into their title.
        # v65 moves it for no tool or grant change either: prompt v17, stage0-interview v38 and
        # account-research-briefing v2 (repointed paths, one worded example) and the re-minted
        # `manual-*@v11` bodies that state the turn limits without numbers.
        # Digest measured off this tree.
        # v66 (discovery rebuild, 2026-09-28): stage0-interview@v39 and manual-*@v12.
        # v67 (2026-09-29): briefing v3 without the one-person trial scope; prompt v18,
        # stage0-interview@v40 and manual-*@v13 repointed.
        # v68 (2026-09-29): three retired-lane tools dropped; stage0-interview@v41, manual-*@v14.
        # v69 (2026-09-29): 4 MB workspace files for offloaded history; stage0@v42, manual@v15.
        # v70 (2026-09-30): the agent writes the discovery brief — `launch_arv2_discovery@2` and
        # `read_discovery_run@3`; stage0@v43 (section 7b), manual@v16.
        # v71 (2026-10-15, main): `manage_products@1` granted; stage0@v44 and manual@v17 repointed.
        # v74 (2026-10-16, the website release): the website line's v73 (design-leg first turn,
        # page briefs, ad headline suggestions) re-minted on main's v71; stage0@v47, manual@v20.
        # v75 (2026-10-19, merges research-streaming's v72): `launch_arv2_discovery@3`; stage0@v48,
        # manual@v21.
        # v76 (2026-10-20, CRM integration Phase 1): four CRM-integration tools granted; the new
        # `crm-sales-analysis@v1`, stage0-interview@v49 and manual@v22.
        # v77 (2026-10-22, CRM integration Phase 2): three CRM write tools granted; the new
        # `crm-writing@v1`, stage0-interview@v50 and manual@v23.
        # v78 (2026-10-23, F3 Phase 2): no tool moves; stage0-interview@v51 and manual@v24 carry
        # the founder-approved retention text.
        AgentRole.HEAD_OF_ABM: ("4bb42c8ed7855d2ee5ade7a3225c09074234cd9d0c969f7d81d838ac8e2600d0"),
        AgentRole.RESEARCH: "23cff2335bb82e0549ee0c830316968971146e8b90c8d2090447ee0ed92eed6f",
        AgentRole.CONTENT_DRAFTER: (
            "8985c13ead086350d952f76e6d3c0ed3f4162cc92de290f8dd7edd7fcab44cbf"
        ),
        AgentRole.REVIEWER: "1cd0fc4e5c8276983c5e0b8d9a83904be82a95ed57f27c9c1dfd9f5a3887df46",
        # ARV2 Track O, O4: onboarding-synthesis@v4 — prompt v2, icp-synthesis v4 (block YAML
        # with quoted values; v3 batched the product-file reads) and audience-persona v2 skills,
        # and the single `exa_search_evidence@1` grant. v2 is the
        # synthesis split: one task per turn, the known-ICPs reuse rule in the ICP skill, and a
        # persona skill that writes the one document for the one ICP its user message names.
        # Digest measured off this tree.
        AgentRole.ONBOARDING_SYNTHESIS: (
            "586e32b5b6e810f4a10292e2c62710fac61acd69dac2acd85aac1ca5ddd769b8"
        ),
    }
    # The model pin is per role, not blanket: the 2026-08-27 demo-night correction moved the
    # conversation profile to grok-4.6 (head-of-abm@v43), and ruling O-D1 puts the onboarding
    # synthesis agent on the same model. The specialists stay on gpt-5.6-terra.
    expected_models = {
        AgentRole.HEAD_OF_ABM: "x-ai/grok-4.6",
        AgentRole.RESEARCH: "openai/gpt-5.6-terra",
        AgentRole.CONTENT_DRAFTER: "openai/gpt-5.6-terra",
        AgentRole.REVIEWER: "openai/gpt-5.6-terra",
        AgentRole.ONBOARDING_SYNTHESIS: "x-ai/grok-4.6",
    }
    toolbelt = build_toolbelt(storage=None, gateway=None)
    for role, digest in expected_manifests.items():
        resolved = registry.resolve(role)
        assert resolved.profile.model.model_id == expected_models[role]
        if role is AgentRole.HEAD_OF_ABM:
            assert (
                f"{resolved.profile_ref.name}@{resolved.profile_ref.version}"
                == PROJECT_CONVERSATION_AGENT_PROFILE_ID
            )
            assert resolved.profile.model.model_id == PROJECT_CONVERSATION_MODEL_ID
        # One name is granted at an address other than its name-only default:
        # `research_account_gaps@2`. (`head-of-abm@v70` pins the defaults of
        # `launch_arv2_discovery` and `read_discovery_run`, `@2` and `@3`.)
        pinned_away_from_default = {
            "research_account_gaps": "research_account_gaps@2",
        }
        expected_tools = {
            pinned_away_from_default.get(name, f"{name}@{toolbelt.descriptor(name).version}")
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
    # gates, FI-2's selected-Account launch and reads: 111 + 18 = 129). Brand Ad Assets v1 W2
    # adds its four ungranted lane envelopes, disclosed unavailable to every surface
    # (129 + 4 = 133).
    # Slice B wave 2 installs `draft_account_research_directive@4` alongside its replayable
    # predecessors, so the inventory gains exactly one address, and the Slice B browser-gate
    # repair installs @5 the same way. The ARV2-R0 merge unions both lines' additions; 136 is
    # measured off the merged tree, not derived from either side's arithmetic. ARV2 Track O, O4
    # installs `exa_search_evidence@1` — the onboarding synthesis agent's one governed evidence
    # call, granted to `onboarding_synthesis` alone, so it is role-unavailable from this view
    # (136 + 1 = 137).
    # ARV2 onboarding O6 re-measures this off the tree rather than continuing the arithmetic: the
    # standing 137 had already drifted to 139 before this lane (two installs landed without moving
    # the number), and O6's own seams install `open_icp_confirmation_gate@2` and
    # `open_product_set_selection_gate@1` (139 + 2 = 141). The ARV2 launch/read pair was already
    # installed and merely ungranted, so promoting it moves grants, not inventory. The pre-existing
    # 137 -> 139 drift is folded into this one re-pin. ARV2 Track R, R3 installs
    # `launch_arv2_person_research@1`, registered ungranted (141 + 1 = 142).
    # ARV2 Track R, R4 registers `launch_arv2_discovery@1`, ungranted (142 -> 143).
    # Project-label renaming is registered for the human UI and granted to no agent (143 -> 144).
    # ICP authoring installs `author_icp_document@1`, registered ungranted (144 -> 145), and
    # the persona request `request_persona_synthesis@1` on the same terms (145 -> 146).
    # The project plan's `write_project_document@1` installs ungranted (146 -> 147), and the
    # three ARV2 reads install on the same terms (147 -> 150).
    # The paged reads install `read_account_research@2` and `read_discovery_run@2`, both UNGRANTED
    # (150 -> 152): `head-of-abm@v55` pins the `@1` contracts by digest, so the new inputs land at
    # new addresses and the grant moves with a later, reviewed profile version.
    # The general claims query `read_claims@1` installs UNGRANTED beside them (152 -> 153): one
    # new name at one address, granted to nobody until a profile pins its contract. The gallery
    # read `read_artifact@1` installs on exactly the same terms (153 -> 154).
    # Artifacts page (2026-09-15): design_rename_document and design_set_document_archived,
    # ungranted (154 -> 156).
    # The code sandbox installs `run_python@1` (156 -> 157). It arrived ungranted and is
    # GRANTED as of `head-of-abm@v58`, the reviewed bump that pins its two schema digests, so
    # the head now sees it AVAILABLE rather than role-unavailable.
    assert by_address["run_python@1"].status is AgentCapabilityStatus.AVAILABLE
    # Projects directory (2026-09-19): four project-row tools, ungranted (157 -> 161).
    # Asset ingestion adds two @2 contracts and its ungranted enrichment retry (161 -> 164).
    # web_search@1 (2026-09-22): granted at head-of-abm@v62 (165 -> 166).
    # Agent-authored discovery (2026-09-30) installs `launch_arv2_discovery@2` beside the retired
    # `@1` (166 -> 167), and `read_discovery_run@3` (summary, end reason, exclusions) beside `@2`
    # (167 -> 168). `head-of-abm@v70` pins both new addresses, so they are available and the
    # addresses they replace drop to role-unavailable.
    # 2026-10-05 installs `read_account_research@3` for the design role (168 -> 169); head-of-abm
    # does not pin it, so from this view it is role-unavailable.
    # + design_write_site@1, design_undo_site@1, design_redo_site@1, ungranted (Wave 2 Lane A)
    # + design_publish_site@1, ungranted (Wave 2 Lane A, Task 21)
    # + read_cited_claims@1 (2026-10-11, Lane B), ungranted until the design profile bump
    # Wave 2 Lane B: design_record_site_section (+1 name, +1 address)
    # Product management (2026-10-15, main): `manage_products@1`, granted at head-of-abm@v71
    # (175 -> 176).
    # launch_arv2_discovery@3 (2026-10-16, research-streaming: the brief's exclude list)
    # (176 -> 177).
    # connect_crm@1 (CRM integration Phase 1), ungranted until Task 11 (177 -> 178);
    # find_crm_actions@1 and run_crm_action@1 likewise (178 -> 180); write_brand_document@1
    # (180 -> 181).
    # propose_crm_changes@1 (CRM integration Phase 2), ungranted until the catalog bump
    # (181 -> 182); crm_write_log@1 and manage_crm_grants@1 likewise (182 -> 184). All three are
    # granted at head-of-abm@v77; the count is unmoved.
    assert len(by_address) == 184
    assert by_address["manage_products@1"].status is AgentCapabilityStatus.AVAILABLE
    assert by_address["launch_arv2_discovery@3"].status is AgentCapabilityStatus.AVAILABLE
    assert by_address["launch_arv2_discovery@1"].status is AgentCapabilityStatus.ROLE_UNAVAILABLE
    assert by_address["read_discovery_run@3"].status is AgentCapabilityStatus.AVAILABLE
    assert by_address["read_discovery_run@2"].status is AgentCapabilityStatus.ROLE_UNAVAILABLE
    assert by_address["web_search@1"].status is AgentCapabilityStatus.AVAILABLE
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
        "design_record_site_section@1",
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
    # Brand Ad Assets v1 W2's four ungranted lane envelopes join on the same terms as
    # `synthesize_entity_prose@1`: machine-invoked, disclosed, granted to nobody (129 + 4 = 133).
    # Slice B wave 2 and the browser-gate repair install `draft_account_research_directive@4`
    # and @5 alongside their replayable predecessors. The ARV2-R0 merge unions both lines'
    # additions; 136 is measured off the merged tree, not derived from either side's arithmetic.
    # ARV2 Track O, O4's `exa_search_evidence@1` joins on the same terms: installed, disclosed,
    # and granted only to `onboarding_synthesis`, so it is unavailable here (136 + 1 = 137).
    # ARV2 onboarding O6 re-measures this off the tree rather than continuing the arithmetic: the
    # standing 137 had already drifted to 139 before this lane (two installs landed without moving
    # the number), and O6's own seams install `open_icp_confirmation_gate@2` and
    # `open_product_set_selection_gate@1` (139 + 2 = 141). The ARV2 launch/read pair was already
    # installed and merely ungranted, so promoting it moves grants, not inventory. The pre-existing
    # 137 -> 139 drift is folded into this one re-pin.
    # ARV2 Track R, R3 installs `launch_arv2_person_research@1`, registered ungranted
    # (141 + 1 = 142).
    # ARV2 Track R, R4 registers `launch_arv2_discovery@1`, ungranted (142 -> 143).
    # Human project-label rename adds one ungranted address (143 -> 144), ICP authoring's
    # `author_icp_document@1` adds the next one on the same terms (144 -> 145), and the persona
    # request `request_persona_synthesis@1` the one after (145 -> 146).
    # The project plan's `write_project_document@1` installs ungranted (146 -> 147), and the
    # three ARV2 reads install on the same terms (147 -> 150).
    # The paged reads install `read_account_research@2` and `read_discovery_run@2`, both UNGRANTED
    # (150 -> 152): `head-of-abm@v55` pins the `@1` contracts by digest, so the new inputs land at
    # new addresses and the grant moves with a later, reviewed profile version.
    # The general claims query `read_claims@1` installs UNGRANTED beside them (152 -> 153): one
    # new name at one address, granted to nobody until a profile pins its contract. The gallery
    # read `read_artifact@1` installs on exactly the same terms (153 -> 154).
    # Artifacts page (2026-09-15): design_rename_document and design_set_document_archived,
    # ungranted (154 -> 156).
    # The code sandbox installs `run_python@1` (156 -> 157). It arrived ungranted and is
    # GRANTED as of `head-of-abm@v58`, the reviewed bump that pins its two schema digests, so
    # the head now sees it AVAILABLE rather than role-unavailable.
    assert by_address["run_python@1"].status is AgentCapabilityStatus.AVAILABLE
    # Projects directory (2026-09-19): four project-row tools, ungranted (157 -> 161).
    # Asset ingestion adds two @2 contracts and its ungranted enrichment retry (161 -> 164).
    # web_search@1 (2026-09-22): granted at head-of-abm@v62 (165 -> 166).
    # launch_arv2_discovery@2 (2026-09-30) (166 -> 167) and read_discovery_run@3 (167 -> 168),
    # both granted at head-of-abm@v70.
    # + design_write_site@1, design_undo_site@1, design_redo_site@1, ungranted (Wave 2 Lane A)
    # + design_publish_site@1, ungranted (Wave 2 Lane A, Task 21)
    # + read_cited_claims@1 (2026-10-11, Lane B), ungranted until the design profile bump
    # Wave 2 Lane B: design_record_site_section (+1 name, +1 address)
    # + manage_products@1 (2026-10-15, main), granted at head-of-abm@v71.
    # launch_arv2_discovery@3 (2026-10-16, research-streaming: the brief's exclude list)
    # (176 -> 177).
    # connect_crm@1 (CRM integration Phase 1), ungranted until Task 11 (177 -> 178);
    # find_crm_actions@1 and run_crm_action@1 likewise (178 -> 180); write_brand_document@1
    # (180 -> 181); propose_crm_changes@1 (CRM integration Phase 2), ungranted (181 -> 182);
    # crm_write_log@1 and manage_crm_grants@1 likewise (182 -> 184); all three granted at
    # head-of-abm@v77, the count unmoved.
    assert len(by_address) == 184  # + read_account_research@3 (2026-10-05)
    assert by_address["web_search@1"].status is AgentCapabilityStatus.AVAILABLE
    for address in (
        "create_thread@1",
        "rename_thread@1",
        "rename_project@1",
        "set_thread_pinned@1",
        "archive_thread@1",
        "create_project@1",
        "update_project_details@1",
        "set_project_pinned@1",
        "set_project_archived@1",
    ):
        assert by_address[address].status is AgentCapabilityStatus.ROLE_UNAVAILABLE
    assert by_address["synthesize_entity_prose@1"].status is not AgentCapabilityStatus.AVAILABLE
    assert by_address["synthesize_value_narrative@1"].status is not AgentCapabilityStatus.AVAILABLE
    assert by_address["inspect_statement_history@1"].status is AgentCapabilityStatus.AVAILABLE
    # ARV2 onboarding O6: every Client-KB / Product-KB / readiness reader left the Head-of-ABM
    # surface with `head-of-abm@v44`, both versions of each. The map must disclose them — the model
    # seeing a capability it lacks is what stops it inventing a workaround — but never as available.
    for address in (
        "evaluate_stage0_readiness@1",
        "evaluate_stage0_readiness@2",
        "inspect_readiness_history@1",
        "inspect_client_claim@1",
        "inspect_client_claim@2",
        "list_client_knowledge@1",
        "list_client_knowledge@2",
        "inspect_product_claim@1",
        "list_product_knowledge@1",
        "open_product_selection_gate@1",
        "open_discovery_configuration_gate@1",
        "start_recon@1",
        "submit_onboarding_input@1",
        "start_confirmed_project_run@3",
        "synthesize_icps@3",
        "open_icp_confirmation_gate@1",
    ):
        assert by_address[address].status is AgentCapabilityStatus.ROLE_UNAVAILABLE, address
    # The whole model-invocable surface of the new Stage-0 lane. `open_icp_confirmation_gate@2`
    # replaces `@1` (a knowledge document instead of a draft `icp_spec` row),
    # `open_product_set_selection_gate@1` replaces the single-product gate, and the ARV2 launch
    # tools — installed but ungranted since Track R R2/R3 — are granted here for the first time,
    # with stage0-interview v21 stating what must be confirmed before either may be called.
    #
    # FOUNDER RULING 2 (2026-09-10): the five old-research-lane tools are NOT here. There is one
    # research lane on this surface now, and the launch/read pair above is it. `read_arv2_account_
    # research_run@1` is the only run read; the old lane's two read tools resolve
    # `account_research_run` rows the new lane never writes, so leaving them installed-and-granted
    # would advertise a status surface that answers about nothing this agent can start.
    #
    # ARV2 Track R, R4 adds `launch_arv2_discovery@1`: finding candidate accounts from the
    # project's own pinned ICP is the same act on the same lane as researching the accounts a
    # human named, so it is granted with `head-of-abm@v45` and taught by stage0-interview v22 §7b.
    #
    # ARV2 context and authoring adds `author_icp_document@1` and `request_persona_synthesis@1`:
    # writing the profile down and asking for its personas are the two halves of the ICP flow the
    # agent may perform itself, granted with `head-of-abm@v46` and taught by stage0-interview v23
    # §5b/§5c. Neither confirms anything — the ICP gate is still the human's.
    #
    # The project plan adds `write_project_document@1`: writing the plan down is the same act
    # as saying it in the reply, except that the written version is a durable document the
    # human can edit. Granted with `head-of-abm@v47` and taught by stage0-interview v24 §6b.
    #
    # The ARV2 reads add `read_project_accounts@1`, `read_account_research@1` and
    # `read_discovery_run@1`: the project's own rows, read. They spend nothing and start nothing,
    # so the skill can require them before the agent speaks about an account at all. Granted with
    # `head-of-abm@v48` and taught by stage0-interview v25 §7b/§7c.
    #
    # The versioned project root takes three away. `author_icp_document@1`,
    # `request_persona_synthesis@1` and `write_project_document@1` are ungranted at
    # `head-of-abm@v55`: `project/` is a writable prefix now, so the ICP, the personas and the plan
    # are written with `write_file` and taught by `icp-authoring@v1`, `persona-authoring@v1` and
    # `plan-authoring@v1`. They stay installed and disclosed as ROLE_UNAVAILABLE below, which is
    # the whole point of disclosing a capability the role lacks: the model is not left to invent a
    # workaround for a tool that vanished.
    #
    # Paged and spilled reads move two and add two. `read_account_research` and
    # `read_discovery_run` are available at their PAGED `@2` — `head-of-abm@v56` pins those exact
    # contracts, so the `@1`s drop to ROLE_UNAVAILABLE beside the retired document tools — and
    # `read_claims@1` and `read_artifact@1` join, granted at the same version and taught by
    # stage0-interview v33 §7c.
    #
    # The code sandbox adds `run_python@1`: one short Python script per call, in a locked-down
    # container over the turn's own workspace, and the only way to open the PDFs, decks,
    # spreadsheets and images the project's `attachments/` holds. Granted at `head-of-abm@v58`
    # and taught by `code-execution@v1`. It spends nothing and starts nothing — its only effect
    # is on files in the agent's own workspace, swept against the profile's policy on exit.
    #
    # Multi-artifact legs move one: `open_design_leg` is available at `@5` — `head-of-abm@v59`
    # pins that exact contract, whose input carries an `artifacts` list instead of one `title` —
    # so `@4` drops to ROLE_UNAVAILABLE beside the other superseded addresses.
    #
    # Agent-authored discovery moves two: the Head of ABM writes the discovery brief, so
    # `launch_arv2_discovery` is available at `@2` (the brief in its input) and `read_discovery_run`
    # at `@3` (summary, end reason, exclusions) — `head-of-abm@v70` pins both exact contracts —
    # and `@1` / `@2` drop to ROLE_UNAVAILABLE. Taught by stage0-interview v43 section 7b.
    # `head-of-abm@v72` re-pins discovery at `@3` (the brief's exclude list, spec 2026-10-16).
    assert available == {
        "inspect_statement_history@1",
        "launch_arv2_account_research@1",
        "launch_arv2_discovery@3",
        "launch_arv2_person_research@1",
        "open_design_leg@5",
        "configure_project_targeting@1",
        # Product management (head-of-abm@v71, 2026-10-15).
        "manage_products@1",
        # CRM integration Phase 1 (head-of-abm@v76, 2026-10-20).
        "connect_crm@1",
        "find_crm_actions@1",
        "run_crm_action@1",
        "write_brand_document@1",
        # CRM integration Phase 2 (head-of-abm@v77, 2026-10-22).
        "propose_crm_changes@1",
        "crm_write_log@1",
        "manage_crm_grants@1",
        "propose_field@2",
        "propose_source@1",
        "read_account_research@2",
        "read_artifact@1",
        "read_arv2_account_research_run@1",
        "read_claims@1",
        "read_discovery_run@3",
        "read_project_accounts@1",
        "record_interview_answer@1",
        "run_python@1",
        "submit_ingestion@1",
        "web_search@1",
    }
    # Every dropped old-lane tool stays disclosed — the model seeing a capability it lacks is what
    # stops it inventing a workaround — and every one of them names WHY.
    for address in (
        "launch_account_research@1",
        "launch_selected_account_research@1",
        "launch_contact_research@1",
        "read_account_research_run@1",
        "read_contact_research_run@1",
    ):
        assert by_address[address].status is AgentCapabilityStatus.ROLE_UNAVAILABLE, address
        assert by_address[address].reason_code == "superseded_by_onboarding_v2", address
    assert by_address["confirm_project_product@1"].status is AgentCapabilityStatus.HUMAN_ONLY
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
    # Turn limits are operator settings (ruling 2026-09-27): the map never quotes the profile's
    # own round or timeout numbers, which are not the ones the runtime applies.
    assert "set by the deployment" in head.generated_resource_map
    assert "max_model_rounds=" not in head.generated_resource_map
    assert "turn_timeout_s=" not in head.generated_resource_map
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
    assert production.profile_ref.address == "profile:head-of-abm@v78"
    assert [item.resource.address for item in production.skill_disclosures()][0] == (
        "skill:stage0-interview@v51"
    )
    # ARV2 onboarding O6 retired the S4-E Client-KB/Product-KB reader surface from this role: the
    # new lane's Stage-0 knowledge is brand knowledge documents the agent reads off its workspace,
    # so the strictness this test was written to guard is now enforced by the tools' ABSENCE.
    # Every version of every retired reader must be gone from the production surface, not merely
    # narrowed to its safe version.
    assert {
        "list_client_knowledge@1",
        "list_client_knowledge@2",
        "inspect_client_claim@1",
        "inspect_client_claim@2",
        "list_product_knowledge@1",
        "inspect_product_claim@1",
        "open_product_selection_gate@1",
        "evaluate_stage0_readiness@1",
        "evaluate_stage0_readiness@2",
        "start_recon@1",
    }.isdisjoint(addresses)
    # What replaces them: the set-valued product gate and the ICP gate over the knowledge document.
    assert "configure_project_targeting@1" in addresses
    assert {"open_product_set_selection_gate@1", "open_icp_confirmation_gate@2"}.isdisjoint(
        addresses
    )
    assert "open_icp_confirmation_gate@1" not in addresses
    assert toolbelt.descriptor("open_icp_confirmation_gate").address == (
        "open_icp_confirmation_gate@2"
    )


def test_v70_grants_the_agent_authored_discovery_pair_and_its_teaching(
    registry: AgentProfileRegistry,
) -> None:
    """`head-of-abm@v70` is where the agent starts writing the discovery brief; v71 and v74 keep it.

    It grants `launch_arv2_discovery@2` (the brief in the input) and `read_discovery_run@3`
    (summary, end reason, exclusions) and neither address they replace, and it pins the
    stage0-interview version whose section 7b teaches how to write the brief.
    """

    assert C6_ACTIVE_PROFILE_VERSIONS[AgentRole.HEAD_OF_ABM] == "v78"
    head = registry.resolve(AgentRole.HEAD_OF_ABM)
    granted = {pin.address for pin in head.profile.tools}
    # v72 re-pins it at `@3` (the brief's exclude list, spec 2026-10-16).
    assert "launch_arv2_discovery@3" in granted
    assert "launch_arv2_discovery@2" not in granted
    assert "launch_arv2_discovery@1" not in granted
    assert "read_discovery_run@3" in granted
    assert "read_discovery_run@2" not in granted
    assert head.profile.skills[0].resource.address == "skill:stage0-interview@v51"
    body = head.open_skill("skill:stage0-interview@v51")
    assert "## 7b. Discover accounts for this project" in body
    assert "`must_not`" in body
    assert "discovery_in_progress" in body


def test_stage0_skill_says_what_to_do_when_the_brand_has_no_knowledge_documents() -> None:
    """The honest empty state replaces S4-E's missing-Product-KB carve-out.

    The ancestor of this test guarded that a missing Product-KB card could not block a human from
    supplying the first product fact. ARV2 onboarding O6 removed the Client-KB/Product-KB readers
    from this surface entirely, so the equivalent guarantee is now about the brand's knowledge
    documents: when there are none the agent says so plainly and points at onboarding — it does not
    research the company itself and does not invent a profile — while routing what the human says
    stays unconditional, with `unmapped` as the honest floor.
    """

    with hermetic_flag_env():
        registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    production = registry.resolve(
        AgentRole.HEAD_OF_ABM,
        surface=PROJECT_CONVERSATION_SURFACE,
    )
    body = production.open_skill("skill:stage0-interview@v51")

    assert "onboarding has not produced knowledge for this brand yet" in body
    assert "brand onboarding runs from the workspace's onboarding flow" in body
    assert "Do not research the company yourself and do not invent a profile." in body
    assert "Never state a fact a file does not contain" in body
    assert "is routed `unmapped` with its exact quote" in body


def test_onboarding_icp_surface_withholds_the_evidence_tool_under_one_profile() -> None:
    """The ICP turn writes from the files: the evidence tool is not installed, not discouraged."""

    with hermetic_flag_env():
        registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    full = registry.resolve(AgentRole.ONBOARDING_SYNTHESIS)
    icp = registry.resolve(AgentRole.ONBOARDING_SYNTHESIS, surface=ONBOARDING_ICP_SURFACE)

    assert "exa_search_evidence@1" in {pin.address for pin in full.profile.tools}
    assert {pin.address for pin in icp.profile.tools} == set()
    # A surface is a ceiling on one reviewed profile, never a second profile: the ICP turn and the
    # persona turns resolve the same profile resource and the same prompt.
    assert icp.profile_ref == full.profile_ref
    assert icp.profile_ref.address == "profile:onboarding-synthesis@v4"
    assert icp.resource_manifest.prompt == full.resource_manifest.prompt
    assert icp.resource_manifest.profile == full.resource_manifest.profile
    # The manifest binds the EFFECTIVE authority, not the reviewed ceiling, so the narrowed
    # resolution has its own aggregate digest — that is the manifest doing its job, and the
    # equality that matters (same reviewed resources) is asserted above. The persona skill goes
    # with the tool it requires, which is the outcome we want: the ICP turn is not handed a skill
    # whose whole procedure is an evidence pass it cannot run.
    assert icp.resource_manifest.aggregate_sha256 != full.resource_manifest.aggregate_sha256
    assert [ref.address for ref in full.resource_manifest.skills] == [
        "skill:icp-synthesis@v4",
        "skill:audience-persona@v2",
    ]
    assert [ref.address for ref in icp.resource_manifest.skills] == ["skill:icp-synthesis@v4"]


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

    # One procedure skill, since founder ruling 2 (2026-09-10) dropped `account-deep-steering@v8`
    # with the five old-lane tools its frontmatter required. A skill cannot grant a tool its
    # profile does not pin, so keeping it would have disclosed a procedure whose every step is
    # uncallable. v54 adds the fifteen manual chapters after it, in profile order: reference, not
    # procedure, each granting no tool.
    assert [item.resource.address for item in disclosures] == [
        "skill:stage0-interview@v51",
        # v55 adds the three document skills between the procedure and the reference shelf: each
        # one is the whole procedure for one document written under `project/`, and grants no tool.
        "skill:account-research-briefing@v3",
        "skill:icp-authoring@v3",
        "skill:persona-authoring@v2",
        "skill:plan-authoring@v2",
        # v58 adds the sandbox skill after them and before the reference shelf: the whole
        # procedure for `run_python@1`, which it is the one disclosed skill to require.
        "skill:code-execution@v1",
        # v76 adds the CRM sales analysis after it: the procedure for the four CRM-integration
        # tools (and `run_python@1`) granted with it.
        # v77 re-pins it at v2, whose read-only sentence points to crm-writing.
        "skill:crm-sales-analysis@v2",
        # v77 adds the CRM writes after it: the procedure for the three CRM write tools granted
        # with it (and `connect_crm@1` and `find_crm_actions@1`).
        "skill:crm-writing@v1",
        *(f"skill:manual-{name}@v24" for name in MANUAL_CHAPTERS),
    ]
    assert "Ask one compact question" not in disclosures[0].model_dump_json()
    body = head.open_skill(disclosures[0].resource.address)
    assert "Ask one question at a time" in body
    briefing_path = ".deepagent/skills/account-research-briefing/v3/SKILL.md"
    launch = build_toolbelt(storage=None, gateway=None).descriptor("launch_arv2_account_research")
    assert briefing_path in body
    assert briefing_path in head.prompt_body
    assert briefing_path in launch.model_description
    assert briefing_path in head.open_skill("skill:manual-tools@v24")
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
        # ARV2 onboarding O6 re-pins these to the situations the NEW lane actually meets. The
        # v20 fixtures named recon, readiness floors and readiness overrides — three mechanisms
        # `head-of-abm@v44` no longer has. The rule the test enforces is unchanged: every Stage-0
        # situation a human can walk into has one explicit governed behaviour written down, not an
        # inference the model is trusted to make.
        ("no_knowledge_documents", "onboarding has not produced knowledge for this brand yet"),
        ("read_before_speaking", "before your first reply on a project, also read"),
        ("unknown_product_fact", "Never state a fact a file does not contain"),
        ("automatic_targeting", "call `configure_project_targeting` with the `icp_key`"),
        ("possible_duplicate", "A candidate marked as a possible duplicate"),
        ("no_approval_pause", "Do not open an approval card"),
        # ARV2 context and authoring re-pins this one situation: a Revised gate receipt is no
        # longer a dead end the agent records and hands back to onboarding — it is drafted, in the
        # reviewed profile's own scope, and re-gated. The two new situations the same version
        # creates get their own fixtures beside it.
        ("icp_revised", "profile (section 5b) in the same scope"),
        # The versioned project root moves three situations out of this skill and into their own.
        # What v32 must still do is ROUTE them: each section names the skill that carries the
        # procedure and the path to open it, so a model that reaches §5b, §5c or §6b is one read
        # away from the whole rule rather than left with a sentence about a tool it no longer has.
        ("author_icp", "open the `icp-authoring` skill"),
        ("personas_after_confirmation", "open the `persona-authoring` skill"),
        ("write_plan", "open the `plan-authoring` skill"),
        ("document_skill_paths", "`.deepagent/skills/plan-authoring/v2/SKILL.md`"),
        # The ARV2 reads: the one situation v25 creates. Speaking about an account is gated on
        # reading it, and a read is never a launch — both are governed behaviours, not inferences.
        # v33 widens the same rule past accounts, because the grant did: a claim and a gallery
        # artifact are read before they are described too, and every read is walked to the end of
        # its pages before a count is stated.
        ("read_accounts_before_speaking", "Never state a fact from memory of an earlier thread"),
        ("read_claims_for_a_specific_question", "**A specific question about claims**"),
        ("read_the_artifact_before_describing_it", "**What a gallery artifact is or says:**"),
        ("read_every_page_before_counting", "read again with `offset: next_offset` before you"),
        ("a_spilled_result_is_read_from_its_file", "the receipt says `spilled_to`"),
        ("read_discovery_before_relaunching", "call `read_discovery_run` first"),
        ("prose_is_not_a_receipt", "ordinary file writes do not move a pin."),
        ("contradictory_correction", "**Corrections carry lineage.**"),
        ("upload", "goes through `submit_ingestion` with its material context"),
        ("novel_field", "goes through `propose_field` or `propose_source`"),
        ("unmappable", "is routed `unmapped` with its exact quote"),
        ("launch_preconditions", "apply the ICP and products before launching"),
        ("launch_is_not_completion", "It is never completed research"),
    ),
)
def test_stage0_quality_fixture_has_explicit_governed_behavior(
    registry: AgentProfileRegistry,
    fixture: str,
    required_guidance: str,
) -> None:
    del fixture
    head = registry.resolve(AgentRole.HEAD_OF_ABM)
    body = head.open_skill("skill:stage0-interview@v51")

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
    # ARV2 onboarding O6: `evaluate_stage0_readiness@2` is no longer granted anywhere, so it can
    # no longer stand for "a tool the Stage-0 skill needs". `record_interview_answer@1` is the
    # v21 skill's own routing tool and belongs to no other skill on this profile, so withdrawing it
    # is the same proof: the ceiling drops the tool AND the skill that depends on it.
    admitted.remove("record_interview_answer@1")
    narrowed = AgentProfileRegistry(
        prompts=FolderPromptCatalog((CATALOG_ROOT / "prompts").resolve(strict=True)),
        skills=FolderSkillCatalog((CATALOG_ROOT / "skills").resolve(strict=True)),
        profiles=FolderProfileCatalog((CATALOG_ROOT / "profiles").resolve(strict=True)),
        tools=ToolRegistryAgentCatalog(toolbelt),
        engine_tool_ceiling=frozenset(admitted),
        selected_profile_versions=C6_ACTIVE_PROFILE_VERSIONS,
    )

    head = narrowed.resolve(AgentRole.HEAD_OF_ABM)
    assert "record_interview_answer@1" not in {pin.address for pin in head.profile.tools}
    # Withdrawing the Stage-0 skill's own routing tool takes the skill with it, which is the
    # ceiling doing its whole job rather than a weaker version of it. v54's fifteen manual
    # chapters survive, and must: a chapter requires no tool, so no withdrawal can make its
    # procedure uncallable. What it can make is a chapter that over-describes the narrowed
    # surface, which is the manual's honesty problem, not the ceiling's.
    remaining = [item.resource.address for item in head.skill_disclosures()]
    assert "skill:stage0-interview@v51" not in remaining
    # v55's three document skills survive with the manual chapters, and for the same reason: a
    # skill that requires no tool cannot be made uncallable by withdrawing one.
    assert remaining == [
        "skill:account-research-briefing@v3",
        "skill:icp-authoring@v3",
        "skill:persona-authoring@v2",
        "skill:plan-authoring@v2",
        # v58 adds the sandbox skill after them and before the reference shelf: the whole
        # procedure for `run_python@1`, which it is the one disclosed skill to require.
        "skill:code-execution@v1",
        # v76 adds the CRM sales analysis after it: the procedure for the four CRM-integration
        # tools (and `run_python@1`) granted with it.
        # v77 re-pins it at v2, whose read-only sentence points to crm-writing.
        "skill:crm-sales-analysis@v2",
        # v77 adds the CRM writes after it: the procedure for the three CRM write tools granted
        # with it (and `connect_crm@1` and `find_crm_actions@1`).
        "skill:crm-writing@v1",
        *(f"skill:manual-{name}@v24" for name in MANUAL_CHAPTERS),
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
    prompt = copied / "prompts/head-of-abm/v18/SYSTEM.md"
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


@pytest.mark.parametrize("name", ["design_register_asset_record", "design_set_asset_description"])
def test_asset_api_versions_do_not_expand_the_reviewed_design_profile(
    registry: AgentProfileRegistry, name: str
) -> None:
    capabilities = {item.address: item for item in registry.resolve(AgentRole.DESIGN).capabilities}
    assert capabilities[f"{name}@1"].status is AgentCapabilityStatus.AVAILABLE
    assert capabilities[f"{name}@2"].status is AgentCapabilityStatus.ROLE_UNAVAILABLE
    assert capabilities[f"{name}@2"].reason_code == "not_admitted_for_role"


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

    2026-09-19 adds three pins: the account reads, granted so a 1:1 creative can open
    the account's research itself.
    """
    resolved = registry.resolve(AgentRole.DESIGN)
    assert resolved.profile.version == "v5"
    assert len(resolved.profile.tools) == 56
    assert sum(1 for pin in resolved.profile.tools if pin.name.startswith("design_")) == 50
    assert any(pin.address == "finish_design_leg@1" for pin in resolved.profile.tools)
    # 2026-09-19: the design agent reads the target account the way head-of-abm does.
    # `read_account_research` is pinned at `@2` — the PAGED contract head-of-abm holds since
    # `head-of-abm@v56`. `@1` is registered-but-ungranted (frozen for replay), so the design
    # note's `@1` naming cannot be composed: see the module comment at `_roles_for`.
    # 2026-09-22 adds the fourth: web_search@1, the open-web search, used last.
    # 2026-10-05 (design@v4): the research read moves to `@3` — the insights page and the
    # committee with each person's contact page.
    for address in (
        "read_project_accounts@1",
        "read_account_research@3",
        "read_claims@1",
        "web_search@1",
        "read_cited_claims@1",
    ):
        assert any(pin.address == address for pin in resolved.profile.tools), address

    by_address = {item.address: item for item in resolved.capabilities}
    available = {
        address
        for address, item in by_address.items()
        if item.status is AgentCapabilityStatus.AVAILABLE
    }
    assert available == {pin.address for pin in resolved.profile.tools}

    assert resolved.profile.delegation_roles == ()
    # The pin is well-formed (one vendor segment); which model it names is an env setting.
    assert_well_formed_model_id(resolved.profile.model.model_id)
    assert resolved.profile.max_delegation_depth == 0
