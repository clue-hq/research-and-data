from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from clue_api.conversation_turns import CONVERSATION_RECIPE_VERSION
from clue_api.execution_tools import AdvanceProjectPhaseTool, ExecutionControlServices
from clue_api.recipe_contracts import (
    ACCOUNT_RESEARCH_TOOL_ADDRESSES,
    RECIPE_0_TOOL_ADDRESSES,
    RECIPE_1_TOOL_ADDRESSES,
    build_replay_safety_audit,
    standing_recipe_addresses,
)
from clue_api.recipe_wiring import HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES, SYSTEM_RECIPE_FILENAMES
from clue_api.stage0_recipe import RecipeStep
from clue_api.toolbelt_wiring import build_toolbelt
from clue_toolbelt import ReplayPolicy, ToolRegistry


def _standing_recipe_registry() -> ToolRegistry:
    registry = build_toolbelt(storage=None)
    # The phase-advance capability is composed with the execution services, after the base
    # toolbelt is built. Its descriptor itself is service-independent, so a deliberately inert
    # service reference is sufficient for this contract-only audit.
    registry.register(
        AdvanceProjectPhaseTool(cast(ExecutionControlServices, None)),
        make_default=True,
    )
    return registry


def test_every_registered_tool_has_a_typed_output_contract() -> None:
    registry = build_toolbelt(storage=None)
    missing = [
        descriptor.address
        for descriptor in registry.descriptors()
        if not descriptor.has_typed_output
    ]
    assert missing == []


def test_conversation_runtime_pins_the_promoted_integration_recipe() -> None:
    """The combined recipe is inert if the detached turn runner still asks for a predecessor."""

    assert CONVERSATION_RECIPE_VERSION == 33


def test_every_standing_recipe_tool_is_exact_typed_pinned_and_replay_certified() -> None:
    registry = _standing_recipe_registry()
    audit = build_replay_safety_audit(registry)

    assert tuple(item.address for item in audit) == standing_recipe_addresses()
    assert set(RECIPE_0_TOOL_ADDRESSES) <= {item.address for item in audit}
    assert set(RECIPE_1_TOOL_ADDRESSES) <= {item.address for item in audit}
    assert set(ACCOUNT_RESEARCH_TOOL_ADDRESSES) <= {item.address for item in audit}
    assert all(item.replay_policy is not ReplayPolicy.UNCERTIFIED for item in audit)
    assert all(item.durable_identity for item in audit)
    assert all(item.pin_requirements for item in audit)
    assert all(len(item.input_schema_sha256) == 64 for item in audit)
    assert all(len(item.output_schema_sha256) == 64 for item in audit)
    by_address = {item.address: item for item in audit}
    for address in ("list_client_knowledge@2", "inspect_client_claim@2"):
        assert by_address[address].replay_policy is ReplayPolicy.EFFECT_FREE
        assert by_address[address].pin_requirements == ("client_kb",)
    for address in ("list_product_knowledge@1", "inspect_product_claim@1"):
        assert by_address[address].replay_policy is ReplayPolicy.EFFECT_FREE
        assert by_address[address].pin_requirements == ("product_kb",)


def test_the_onboarding_synthesis_unit_recipe_pins_exactly_the_evidence_tool() -> None:
    """ARV2 O4: one gate, one spendable tool, and the skill that says what evidence is for."""

    from clue_api.recipe_contracts import ONBOARDING_SYNTHESIS_TOOL_ADDRESSES
    from clue_api.recipe_wiring import load_system_recipe_definitions

    assert ONBOARDING_SYNTHESIS_TOOL_ADDRESSES == ("exa_search_evidence@1",)
    definitions = {
        definition.recipe_key: definition
        for definition in load_system_recipe_definitions()
        if definition.recipe_key == "onboarding-synthesis-unit"
    }
    recipe = definitions["onboarding-synthesis-unit"]
    gate = next(
        node for node in recipe.graph.nodes if node.node_key == "onboarding_synthesis_interactions"
    )
    assert list(gate.dynamic_tool_allowlist) == ["exa_search_evidence@1"]
    assert any(
        item.kind == "skill" and item.key == "audience-persona" for item in gate.requirements
    )


def test_integration_preserves_pilot_recipe_v7_and_v8_bytes() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"

    v7_index = SYSTEM_RECIPE_FILENAMES.index("recipe0-stage0-v7.json")
    assert SYSTEM_RECIPE_FILENAMES[v7_index : v7_index + 2] == (
        "recipe0-stage0-v7.json",
        "recipe0-stage0-v8.json",
    )
    assert hashlib.sha256((root / "recipe0-stage0-v7.json").read_bytes()).hexdigest() == (
        "67d86848497a9f6e884961eb31f127d70a32578c10e5c07cc80272fb7a539c7a"
    )
    assert hashlib.sha256((root / "recipe0-stage0-v8.json").read_bytes()).hexdigest() == (
        "cbe23f9a48caa5e7672c0ddbbad9f7f5604b4c84d6b2030da0661784e771fe8e"
    )


def test_s5d_mints_recipe_v9_and_preserves_v8_for_exact_replay() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v8 = json.loads((root / "recipe0-stage0-v8.json").read_text())
    v9 = json.loads((root / "recipe0-stage0-v9.json").read_text())
    product_addresses = {
        "list_product_knowledge@1",
        "inspect_product_claim@1",
        "open_product_selection_gate@1",
    }

    v8_index = SYSTEM_RECIPE_FILENAMES.index("recipe0-stage0-v8.json")
    assert SYSTEM_RECIPE_FILENAMES[v8_index : v8_index + 2] == (
        "recipe0-stage0-v8.json",
        "recipe0-stage0-v9.json",
    )
    assert v8["version"] == 8
    assert v9["version"] == 9
    assert product_addresses.isdisjoint(v8["graph"]["tool_allowlist"])
    assert product_addresses <= set(v9["graph"]["tool_allowlist"])
    slot = next(node for node in v9["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert product_addresses <= set(slot["dynamic_tool_allowlist"])
    assert "product_kb" in slot["dynamic_pin_kinds"]
    assert {
        (item["key"], item["version"])
        for item in v9["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
        and item["key"]
        in {
            "list_product_knowledge",
            "inspect_product_claim",
            "open_product_selection_gate",
        }
    } == {
        ("list_product_knowledge", "1"),
        ("inspect_product_claim", "1"),
        ("open_product_selection_gate", "1"),
    }


def test_integration_recipe_v10_composes_both_resource_lineages() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v9 = json.loads((root / "recipe0-stage0-v9.json").read_text())
    v10 = json.loads((root / "recipe0-stage0-v10.json").read_text())
    expected = {
        "evaluate_stage0_readiness@2",
        "synthesize_icps@2",
        "open_icp_confirmation_gate@1",
        "launch_selected_account_research@1",
        "list_client_knowledge@2",
        "inspect_client_claim@2",
        "list_product_knowledge@1",
        "inspect_product_claim@1",
        "open_product_selection_gate@1",
    }

    v9_index = SYSTEM_RECIPE_FILENAMES.index("recipe0-stage0-v9.json")
    assert SYSTEM_RECIPE_FILENAMES[v9_index : v9_index + 2] == (
        "recipe0-stage0-v9.json",
        "recipe0-stage0-v10.json",
    )
    assert v9["version"] == 9
    assert v10["version"] == 10
    assert expected <= set(v10["graph"]["tool_allowlist"])
    slot = next(node for node in v10["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert expected <= set(slot["dynamic_tool_allowlist"])


def test_confirmed_run_v2_mints_recipe_v11_without_rewriting_v10() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v10 = json.loads((root / "recipe0-stage0-v10.json").read_text())
    v11 = json.loads((root / "recipe0-stage0-v11.json").read_text())

    v10_index = SYSTEM_RECIPE_FILENAMES.index("recipe0-stage0-v10.json")
    assert SYSTEM_RECIPE_FILENAMES[v10_index : v10_index + 2] == (
        "recipe0-stage0-v10.json",
        "recipe0-stage0-v11.json",
    )
    assert "start_confirmed_project_run@1" in v10["graph"]["tool_allowlist"]
    assert "start_confirmed_project_run@2" in v11["graph"]["tool_allowlist"]
    assert "start_confirmed_project_run@1" not in v11["graph"]["tool_allowlist"]
    assert v11["version"] == 11


def test_provider_neutral_discovery_mints_recipe_v12_without_rewriting_v11() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v11 = json.loads((root / "recipe0-stage0-v11.json").read_text())
    v12 = json.loads((root / "recipe0-stage0-v12.json").read_text())

    v11_index = SYSTEM_RECIPE_FILENAMES.index("recipe0-stage0-v11.json")
    assert SYSTEM_RECIPE_FILENAMES[v11_index : v11_index + 2] == (
        "recipe0-stage0-v11.json",
        "recipe0-stage0-v12.json",
    )
    assert "start_confirmed_project_run@2" in v11["graph"]["tool_allowlist"]
    assert "start_confirmed_project_run@3" in v12["graph"]["tool_allowlist"]
    assert "open_discovery_configuration_gate@1" in v12["graph"]["tool_allowlist"]
    assert "start_confirmed_project_run@2" not in v12["graph"]["tool_allowlist"]
    assert v12["version"] == 12


def test_icp_presentation_mints_recipe_v13_without_rewriting_v12() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v12 = json.loads((root / "recipe0-stage0-v12.json").read_text())
    v13 = json.loads((root / "recipe0-stage0-v13.json").read_text())

    v12_index = SYSTEM_RECIPE_FILENAMES.index("recipe0-stage0-v12.json")
    assert SYSTEM_RECIPE_FILENAMES[v12_index : v12_index + 2] == (
        "recipe0-stage0-v12.json",
        "recipe0-stage0-v13.json",
    )
    assert "synthesize_icps@2" in v12["graph"]["tool_allowlist"]
    assert "synthesize_icps@3" in v13["graph"]["tool_allowlist"]
    assert "synthesize_icps@2" not in v13["graph"]["tool_allowlist"]
    assert v13["version"] == 13


def test_selected_account_reads_mint_recipe_v14_without_rewriting_v13() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v13 = json.loads((root / "recipe0-stage0-v13.json").read_text())
    v14 = json.loads((root / "recipe0-stage0-v14.json").read_text())
    added = {"get_research_view@1", "read_account_research_run@1"}

    v13_index = SYSTEM_RECIPE_FILENAMES.index("recipe0-stage0-v13.json")
    assert SYSTEM_RECIPE_FILENAMES[v13_index : v13_index + 2] == (
        "recipe0-stage0-v13.json",
        "recipe0-stage0-v14.json",
    )
    assert added.isdisjoint(v13["graph"]["tool_allowlist"])
    assert added <= set(v14["graph"]["tool_allowlist"])
    slot = next(node for node in v14["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert added <= set(slot["dynamic_tool_allowlist"])
    assert {"account_research_run", "verification_policy"} <= set(slot["dynamic_pin_kinds"])
    assert v14["version"] == 14


def test_plan_safe_directive_mints_recipe_v15_without_rewriting_v14() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v14 = json.loads((root / "recipe0-stage0-v14.json").read_text())
    v15 = json.loads((root / "recipe0-stage0-v15.json").read_text())

    v14_index = SYSTEM_RECIPE_FILENAMES.index("recipe0-stage0-v14.json")
    assert SYSTEM_RECIPE_FILENAMES[v14_index : v14_index + 2] == (
        "recipe0-stage0-v14.json",
        "recipe0-stage0-v15.json",
    )
    assert "draft_account_research_directive@2" in v14["graph"]["tool_allowlist"]
    assert "draft_account_research_directive@3" in v15["graph"]["tool_allowlist"]
    assert "draft_account_research_directive@2" not in v15["graph"]["tool_allowlist"]
    assert v15["version"] == 15


def test_o6_head_of_abm_mints_recipe_v22_without_rewriting_v19() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v19 = json.loads((root / "recipe0-stage0-v19.json").read_text())
    v22 = json.loads((root / "recipe0-stage0-v22.json").read_text())
    added = {
        "open_product_set_selection_gate@1",
        "open_icp_confirmation_gate@2",
        "launch_arv2_account_research@1",
        # FOUNDER RULING 3 (2026-09-10): the person launch is the Head of ABM's own act on the same
        # lane, so it is admitted to the conversation slot beside its account sibling.
        "launch_arv2_person_research@1",
        "read_arv2_account_research_run@1",
    }

    # v19 pins the retired `open_design_leg@4`: replay-only since 2026-09-28, so a fresh
    # database never re-validates it against today's registry. Its bytes are what is pinned.
    assert "recipe0-stage0-v19.json" in HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES
    assert "recipe0-stage0-v19.json" not in SYSTEM_RECIPE_FILENAMES
    assert added.isdisjoint(v19["graph"]["tool_allowlist"])
    assert added <= set(v22["graph"]["tool_allowlist"])
    slot = next(node for node in v22["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert added <= set(slot["dynamic_tool_allowlist"])
    slot_requirements = {
        (item["key"], item["version"]) for item in slot["requirements"] if item["kind"] == "tool"
    }
    node_compatibility = {
        (item["key"], item["version"])
        for item in v22["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    expected = {tuple(address.split("@")) for address in added}
    assert expected <= slot_requirements
    assert expected <= node_compatibility
    # The promoted profile pins the directive draft at @5; v19 admitted only @3, so the draft was
    # refused by plan validation. v22 re-pins the slot at @5 everywhere the address appears.
    assert "draft_account_research_directive@5" in v22["graph"]["tool_allowlist"]
    assert "draft_account_research_directive@3" not in v22["graph"]["tool_allowlist"]
    assert ("draft_account_research_directive", "5") in slot_requirements
    assert ("draft_account_research_directive", "3") not in slot_requirements
    assert ("draft_account_research_directive", "5") in node_compatibility
    assert ("draft_account_research_directive", "3") not in node_compatibility
    assert "draft_account_research_directive@5" in slot["dynamic_tool_allowlist"]
    assert "draft_account_research_directive@3" not in slot["dynamic_tool_allowlist"]
    # A requirement set resolves one version per ``(kind, key)`` (``conflicting_requirement``), so
    # admitting the artifact-shaped ICP gate at ``@2`` RE-PINS the key: ``@1`` leaves v22 the way
    # ``draft_account_research_directive@3`` does. v19 stays its exact replay input.
    assert "open_icp_confirmation_gate@1" in v19["graph"]["tool_allowlist"]
    assert "open_icp_confirmation_gate@1" not in v22["graph"]["tool_allowlist"]
    assert "open_icp_confirmation_gate@1" not in slot["dynamic_tool_allowlist"]
    assert ("open_icp_confirmation_gate", "1") not in slot_requirements
    assert ("open_icp_confirmation_gate", "1") not in node_compatibility
    assert v22["version"] == 22
    assert (
        slot["dynamic_pin_kinds"]
        == (
            next(
                node for node in v19["graph"]["nodes"] if node["node_key"] == "stage0_interactions"
            )["dynamic_pin_kinds"]
        )
    )


def test_r4_mints_recipe_v23_without_rewriting_v22() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v22 = json.loads((root / "recipe0-stage0-v22.json").read_text())
    v23 = json.loads((root / "recipe0-stage0-v23.json").read_text())
    # ARV2 Track R, R4 adds exactly one address: verified account discovery for the project, on the
    # same lane and behind the same confirmations as the two launches already in this slot.
    added = {"launch_arv2_discovery@1"}

    # v22 pins the retired `open_design_leg@4`: replay-only since 2026-09-28, so a fresh
    # database never re-validates it against today's registry. Its bytes are what is pinned.
    assert "recipe0-stage0-v22.json" in HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES
    assert "recipe0-stage0-v22.json" not in SYSTEM_RECIPE_FILENAMES
    assert added.isdisjoint(v22["graph"]["tool_allowlist"])
    assert added <= set(v23["graph"]["tool_allowlist"])
    slot = next(node for node in v23["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert added <= set(slot["dynamic_tool_allowlist"])
    slot_requirements = {
        (item["key"], item["version"]) for item in slot["requirements"] if item["kind"] == "tool"
    }
    node_compatibility = {
        (item["key"], item["version"])
        for item in v23["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    expected = {tuple(address.split("@")) for address in added}
    assert expected <= slot_requirements
    assert expected <= node_compatibility
    # v23 is v22 PLUS the one address and nothing else: every address v22 admitted still resolves,
    # so an execution pinned to either revision keeps the surface it was validated against.
    v22_slot = next(
        node for node in v22["graph"]["nodes"] if node["node_key"] == "stage0_interactions"
    )
    assert set(v22["graph"]["tool_allowlist"]) | added == set(v23["graph"]["tool_allowlist"])
    assert set(v22_slot["dynamic_tool_allowlist"]) | added == set(slot["dynamic_tool_allowlist"])
    # `@1` stood in the standing set until recipe0-stage0@33 re-pinned the launch at `@2` (the
    # brief the agent writes); v23's own bytes are unchanged.
    assert "launch_arv2_discovery@1" not in RECIPE_0_TOOL_ADDRESSES
    assert "launch_arv2_discovery@2" in RECIPE_0_TOOL_ADDRESSES
    assert v22["version"] == 22
    assert v23["version"] == 23
    assert slot["dynamic_pin_kinds"] == v22_slot["dynamic_pin_kinds"]


def test_icp_authoring_mints_recipe_v24_without_rewriting_v23() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v23 = json.loads((root / "recipe0-stage0-v23.json").read_text())
    v24 = json.loads((root / "recipe0-stage0-v24.json").read_text())
    # ARV2 context and authoring adds exactly two addresses: the proposed ICP document the agent
    # may write, and the personas it may request for a profile the human already confirmed.
    added = {"author_icp_document@1", "request_persona_synthesis@1"}

    # v23 pins the retired `open_design_leg@4`: replay-only since 2026-09-28, so a fresh
    # database never re-validates it against today's registry. Its bytes are what is pinned.
    assert "recipe0-stage0-v23.json" in HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES
    assert "recipe0-stage0-v23.json" not in SYSTEM_RECIPE_FILENAMES
    assert added.isdisjoint(v23["graph"]["tool_allowlist"])
    assert added <= set(v24["graph"]["tool_allowlist"])
    slot = next(node for node in v24["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert added <= set(slot["dynamic_tool_allowlist"])
    slot_requirements = {
        (item["key"], item["version"]) for item in slot["requirements"] if item["kind"] == "tool"
    }
    node_compatibility = {
        (item["key"], item["version"])
        for item in v24["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    expected = {tuple(address.split("@")) for address in added}
    assert expected <= slot_requirements
    assert expected <= node_compatibility
    # v24 is v23 PLUS the two addresses and nothing else: every address v23 admitted still
    # resolves, so an execution pinned to either revision keeps the surface it was validated
    # against.
    v23_slot = next(
        node for node in v23["graph"]["nodes"] if node["node_key"] == "stage0_interactions"
    )
    assert set(v23["graph"]["tool_allowlist"]) | added == set(v24["graph"]["tool_allowlist"])
    assert set(v23_slot["dynamic_tool_allowlist"]) | added == set(slot["dynamic_tool_allowlist"])
    # Retired at recipe0-stage0@27: `head-of-abm@v55` writes these documents as files under the
    # versioned `project/` mount, so the addresses left the standing set. They stay REGISTERED, so
    # this revision's own pinned executions still replay — which is exactly what the json-vs-json
    # assertions above are here to prove.
    assert added.isdisjoint(RECIPE_0_TOOL_ADDRESSES)
    assert v23["version"] == 23
    assert v24["version"] == 24
    assert slot["dynamic_pin_kinds"] == v23_slot["dynamic_pin_kinds"]


def test_project_plan_mints_recipe_v25_without_rewriting_v24() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v24 = json.loads((root / "recipe0-stage0-v24.json").read_text())
    v25 = json.loads((root / "recipe0-stage0-v25.json").read_text())
    # The project plan adds exactly one address: the plan the agent writes for this project,
    # version-checked against the human's own edits in the Plan tab.
    added = {"write_project_document@1"}

    # v24 pins the retired `open_design_leg@4`: replay-only since 2026-09-28, so a fresh
    # database never re-validates it against today's registry. Its bytes are what is pinned.
    assert "recipe0-stage0-v24.json" in HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES
    assert "recipe0-stage0-v24.json" not in SYSTEM_RECIPE_FILENAMES
    assert added.isdisjoint(v24["graph"]["tool_allowlist"])
    assert added <= set(v25["graph"]["tool_allowlist"])
    slot = next(node for node in v25["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert added <= set(slot["dynamic_tool_allowlist"])
    slot_requirements = {
        (item["key"], item["version"]) for item in slot["requirements"] if item["kind"] == "tool"
    }
    node_compatibility = {
        (item["key"], item["version"])
        for item in v25["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    expected = {tuple(address.split("@")) for address in added}
    assert expected <= slot_requirements
    assert expected <= node_compatibility
    # v25 is v24 PLUS the one address and nothing else: every address v24 admitted still resolves,
    # so an execution pinned to either revision keeps the surface it was validated against.
    v24_slot = next(
        node for node in v24["graph"]["nodes"] if node["node_key"] == "stage0_interactions"
    )
    assert set(v24["graph"]["tool_allowlist"]) | added == set(v25["graph"]["tool_allowlist"])
    assert set(v24_slot["dynamic_tool_allowlist"]) | added == set(slot["dynamic_tool_allowlist"])
    # Retired at recipe0-stage0@27: `head-of-abm@v55` writes these documents as files under the
    # versioned `project/` mount, so the addresses left the standing set. They stay REGISTERED, so
    # this revision's own pinned executions still replay — which is exactly what the json-vs-json
    # assertions above are here to prove.
    assert added.isdisjoint(RECIPE_0_TOOL_ADDRESSES)
    assert v24["version"] == 24
    assert v25["version"] == 25
    assert slot["dynamic_pin_kinds"] == v24_slot["dynamic_pin_kinds"]


def test_read_tools_mint_recipe_v26_without_rewriting_v25() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v25 = json.loads((root / "recipe0-stage0-v25.json").read_text())
    v26 = json.loads((root / "recipe0-stage0-v26.json").read_text())
    # The ARV2 reads add exactly three addresses: the project's accounts, one account's research,
    # and the discovery run — effect-free reads over rows that already exist.
    added = {"read_project_accounts@1", "read_account_research@1", "read_discovery_run@1"}

    # v25 pins the retired `open_design_leg@4`: replay-only since 2026-09-28, so a fresh
    # database never re-validates it against today's registry. Its bytes are what is pinned.
    assert "recipe0-stage0-v25.json" in HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES
    assert "recipe0-stage0-v25.json" not in SYSTEM_RECIPE_FILENAMES
    assert added.isdisjoint(v25["graph"]["tool_allowlist"])
    assert added <= set(v26["graph"]["tool_allowlist"])
    slot = next(node for node in v26["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert added <= set(slot["dynamic_tool_allowlist"])
    slot_requirements = {
        (item["key"], item["version"]) for item in slot["requirements"] if item["kind"] == "tool"
    }
    node_compatibility = {
        (item["key"], item["version"])
        for item in v26["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    expected = {tuple(address.split("@")) for address in added}
    assert expected <= slot_requirements
    assert expected <= node_compatibility
    # v26 is v25 PLUS the three addresses and nothing else: every address v25 admitted still
    # resolves, so an execution pinned to either revision keeps the surface it was validated
    # against.
    v25_slot = next(
        node for node in v25["graph"]["nodes"] if node["node_key"] == "stage0_interactions"
    )
    assert set(v25["graph"]["tool_allowlist"]) | added == set(v26["graph"]["tool_allowlist"])
    assert set(v25_slot["dynamic_tool_allowlist"]) | added == set(slot["dynamic_tool_allowlist"])
    # Only `read_project_accounts@1` is still STANDING. recipe0-stage0@28 re-pinned the other two
    # to their paged `@2`, so the unpaged addresses resolve for a turn pinned to @26 or @27 and
    # nowhere else — which is exactly what the json-vs-json assertions above are here to prove.
    assert added & set(RECIPE_0_TOOL_ADDRESSES) == {"read_project_accounts@1"}
    assert v25["version"] == 25
    assert v26["version"] == 26
    assert slot["dynamic_pin_kinds"] == v25_slot["dynamic_pin_kinds"]


def test_document_skills_mint_recipe_v27_without_rewriting_v26() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v26 = json.loads((root / "recipe0-stage0-v26.json").read_text())
    v27 = json.loads((root / "recipe0-stage0-v27.json").read_text())
    # The versioned project root REMOVES exactly three addresses — the first revision on this
    # lineage that subtracts. `head-of-abm@v55` grants none of them: the proposed ICP, the personas
    # and the plan are written as files under `project/`, so leaving them admitted here would keep
    # saying the conversation may still call them.
    removed = {"author_icp_document@1", "request_persona_synthesis@1", "write_project_document@1"}

    # v26 pins the retired `open_design_leg@4`: replay-only since 2026-09-28, so a fresh
    # database never re-validates it against today's registry. Its bytes are what is pinned.
    assert "recipe0-stage0-v26.json" in HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES
    assert "recipe0-stage0-v26.json" not in SYSTEM_RECIPE_FILENAMES
    assert removed <= set(v26["graph"]["tool_allowlist"])
    assert removed.isdisjoint(v27["graph"]["tool_allowlist"])
    slot = next(node for node in v27["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert removed.isdisjoint(slot["dynamic_tool_allowlist"])
    slot_requirements = {
        (item["key"], item["version"]) for item in slot["requirements"] if item["kind"] == "tool"
    }
    node_compatibility = {
        (item["key"], item["version"])
        for item in v27["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    gone = {tuple(address.split("@")) for address in removed}
    assert gone.isdisjoint(slot_requirements)
    assert gone.isdisjoint(node_compatibility)
    # v27 is v26 MINUS the three addresses and nothing else: v26 is untouched on disk, so an
    # execution pinned to it still validates against the surface it was validated against.
    v26_slot = next(
        node for node in v26["graph"]["nodes"] if node["node_key"] == "stage0_interactions"
    )
    assert set(v27["graph"]["tool_allowlist"]) | removed == set(v26["graph"]["tool_allowlist"])
    assert set(slot["dynamic_tool_allowlist"]) | removed == set(v26_slot["dynamic_tool_allowlist"])
    v26_requirements = {
        (item["key"], item["version"])
        for item in v26_slot["requirements"]
        if item["kind"] == "tool"
    }
    v26_compatibility = {
        (item["key"], item["version"])
        for item in v26["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    assert slot_requirements | gone == v26_requirements
    assert node_compatibility | gone == v26_compatibility
    assert v26["version"] == 26
    assert v27["version"] == 27
    assert slot["dynamic_pin_kinds"] == v26_slot["dynamic_pin_kinds"]


def test_paged_and_new_reads_mint_recipe_v28_without_rewriting_v27() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v27 = json.loads((root / "recipe0-stage0-v27.json").read_text())
    v28 = json.loads((root / "recipe0-stage0-v28.json").read_text())
    # Four addresses join the interaction slot: the PAGED `@2` of two reads `head-of-abm@v56` now
    # pins, and the two reads that version grants for the first time. The `@1`s of the paged pair
    # LEAVE in the same revision — they are re-pinned, not doubled — because one requirement set
    # resolves one version per (kind, key) and both at once is a `conflicting_requirement` that
    # refuses promotion, exactly as `open_icp_confirmation_gate@1` left at @22. v27 stays the exact
    # replay input for a turn pinned to it, which is where the unpaged addresses still resolve.
    added = {
        "read_account_research@2",
        "read_discovery_run@2",
        "read_claims@1",
        "read_artifact@1",
    }
    removed = {"read_account_research@1", "read_discovery_run@1"}

    # v27 pins the retired `open_design_leg@4`: replay-only since 2026-09-28, so a fresh
    # database never re-validates it against today's registry. Its bytes are what is pinned.
    assert "recipe0-stage0-v27.json" in HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES
    assert "recipe0-stage0-v27.json" not in SYSTEM_RECIPE_FILENAMES
    assert added.isdisjoint(v27["graph"]["tool_allowlist"])
    assert added <= set(v28["graph"]["tool_allowlist"])
    assert removed <= set(v27["graph"]["tool_allowlist"])
    assert removed.isdisjoint(v28["graph"]["tool_allowlist"])
    slot = next(node for node in v28["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert added <= set(slot["dynamic_tool_allowlist"])
    assert removed.isdisjoint(slot["dynamic_tool_allowlist"])
    slot_requirements = {
        (item["key"], item["version"]) for item in slot["requirements"] if item["kind"] == "tool"
    }
    node_compatibility = {
        (item["key"], item["version"])
        for item in v28["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    joined = {tuple(address.split("@")) for address in added}
    gone = {tuple(address.split("@")) for address in removed}
    assert joined <= slot_requirements
    assert joined <= node_compatibility
    assert gone.isdisjoint(slot_requirements)
    assert gone.isdisjoint(node_compatibility)
    # One version per (kind, key) in the resolved set: `read_account_research` and
    # `read_discovery_run` each appear exactly once, at `@2`. This is the property whose violation
    # refuses promotion, so it is asserted rather than implied by the set arithmetic below.
    assert sorted(version for key, version in slot_requirements if key == "read_account_research")
    for key in ("read_account_research", "read_discovery_run"):
        assert [item for item in slot_requirements if item[0] == key] == [(key, "2")]
    # v28 is v27 MINUS the two unpaged addresses PLUS the four: v27 is untouched on disk, so an
    # execution pinned to it still validates against the surface it was validated against.
    v27_slot = next(
        node for node in v27["graph"]["nodes"] if node["node_key"] == "stage0_interactions"
    )
    assert (set(v27["graph"]["tool_allowlist"]) - removed) | added == set(
        v28["graph"]["tool_allowlist"]
    )
    assert (set(v27_slot["dynamic_tool_allowlist"]) - removed) | added == set(
        slot["dynamic_tool_allowlist"]
    )
    v27_requirements = {
        (item["key"], item["version"])
        for item in v27_slot["requirements"]
        if item["kind"] == "tool"
    }
    v27_compatibility = {
        (item["key"], item["version"])
        for item in v27["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    assert (v27_requirements - gone) | joined == slot_requirements
    assert (v27_compatibility - gone) | joined == node_compatibility
    # `read_discovery_run@2` stood in the standing set until recipe0-stage0@33 re-pinned the read
    # at `@3`; v28's own bytes are unchanged.
    assert added - {"read_discovery_run@2"} <= set(RECIPE_0_TOOL_ADDRESSES)
    assert "read_discovery_run@3" in RECIPE_0_TOOL_ADDRESSES
    assert removed.isdisjoint(RECIPE_0_TOOL_ADDRESSES)
    assert v27["version"] == 27
    assert v28["version"] == 28
    assert slot["dynamic_pin_kinds"] == v27_slot["dynamic_pin_kinds"]


def test_the_code_sandbox_mints_recipe_v29_without_rewriting_v28() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v28 = json.loads((root / "recipe0-stage0-v28.json").read_text())
    v29 = json.loads((root / "recipe0-stage0-v29.json").read_text())
    # One address JOINS and none leaves: `run_python@1`, granted for the first time at
    # `head-of-abm@v58`. There is no `@1`/`@2` question to settle here — the tool has one
    # version — so v29 is v28 plus exactly this address, and v28 stays the exact replay input
    # for a turn pinned to it.
    added = {"run_python@1"}

    assert "recipe0-stage0-v29.json" in HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES
    assert "recipe0-stage0-v29.json" not in SYSTEM_RECIPE_FILENAMES
    assert added.isdisjoint(v28["graph"]["tool_allowlist"])
    assert added <= set(v29["graph"]["tool_allowlist"])
    slot = next(node for node in v29["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert added <= set(slot["dynamic_tool_allowlist"])
    slot_requirements = {
        (item["key"], item["version"]) for item in slot["requirements"] if item["kind"] == "tool"
    }
    node_compatibility = {
        (item["key"], item["version"])
        for item in v29["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    joined = {tuple(address.split("@")) for address in added}
    assert joined <= slot_requirements
    assert joined <= node_compatibility
    # One version per (kind, key) in the resolved set, which is what keeps promotion from
    # refusing with `conflicting_requirement`.
    assert [item for item in slot_requirements if item[0] == "run_python"] == [("run_python", "1")]
    # v29 is v28 PLUS that one address and nothing else: v28 is untouched on disk, so an
    # execution pinned to it still validates against the surface it was validated against.
    v28_slot = next(
        node for node in v28["graph"]["nodes"] if node["node_key"] == "stage0_interactions"
    )
    assert set(v28["graph"]["tool_allowlist"]) | added == set(v29["graph"]["tool_allowlist"])
    assert set(v28_slot["dynamic_tool_allowlist"]) | added == set(slot["dynamic_tool_allowlist"])
    v28_requirements = {
        (item["key"], item["version"])
        for item in v28_slot["requirements"]
        if item["kind"] == "tool"
    }
    v28_compatibility = {
        (item["key"], item["version"])
        for item in v28["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    assert v28_requirements | joined == slot_requirements
    assert v28_compatibility | joined == node_compatibility
    assert added <= set(RECIPE_0_TOOL_ADDRESSES)
    assert v28["version"] == 28
    assert v29["version"] == 29
    assert slot["dynamic_pin_kinds"] == v28_slot["dynamic_pin_kinds"]


def test_multi_artifact_legs_mint_recipe_v30_without_rewriting_v29() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v29 = json.loads((root / "recipe0-stage0-v29.json").read_text())
    v30 = json.loads((root / "recipe0-stage0-v30.json").read_text())
    # One address is RE-PINNED and none joins: `open_design_leg` moves to `@5`, the contract
    # `head-of-abm@v59` grants — its input carries an `artifacts` list, so one open births one
    # document per item. `@4` LEAVES the slot rather than stand beside `@5`: a requirement set
    # resolves one version per (kind, key), so both at once refuses promotion.
    added = {"open_design_leg@5"}
    removed = {"open_design_leg@4"}

    # v28 pins the retired `open_design_leg@4`: replay-only since 2026-09-28, so a fresh
    # database never re-validates it against today's registry. Its bytes are what is pinned.
    assert "recipe0-stage0-v28.json" in HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES
    assert "recipe0-stage0-v28.json" not in SYSTEM_RECIPE_FILENAMES
    assert "recipe0-stage0-v30.json" in SYSTEM_RECIPE_FILENAMES
    assert added.isdisjoint(v29["graph"]["tool_allowlist"])
    assert added <= set(v30["graph"]["tool_allowlist"])
    assert removed <= set(v29["graph"]["tool_allowlist"])
    assert removed.isdisjoint(v30["graph"]["tool_allowlist"])
    slot = next(node for node in v30["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert added <= set(slot["dynamic_tool_allowlist"])
    assert removed.isdisjoint(slot["dynamic_tool_allowlist"])
    slot_requirements = {
        (item["key"], item["version"]) for item in slot["requirements"] if item["kind"] == "tool"
    }
    node_compatibility = {
        (item["key"], item["version"])
        for item in v30["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    joined = {tuple(address.split("@")) for address in added}
    gone = {tuple(address.split("@")) for address in removed}
    assert joined <= slot_requirements
    assert joined <= node_compatibility
    assert gone.isdisjoint(slot_requirements)
    assert gone.isdisjoint(node_compatibility)
    # One version per (kind, key) in the resolved set, which is what keeps promotion from
    # refusing with `conflicting_requirement`.
    assert [item for item in slot_requirements if item[0] == "open_design_leg"] == [
        ("open_design_leg", "5")
    ]
    # The code sandbox stays where revision 29 put it: this revision moves one address, not two.
    assert "run_python@1" in set(slot["dynamic_tool_allowlist"])
    # v30 is v29 with that one address moved and nothing else: v29 is untouched on disk, so an
    # execution pinned to it still validates against the surface it was validated against.
    v29_slot = next(
        node for node in v29["graph"]["nodes"] if node["node_key"] == "stage0_interactions"
    )
    assert (set(v29["graph"]["tool_allowlist"]) - removed) | added == set(
        v30["graph"]["tool_allowlist"]
    )
    assert (set(v29_slot["dynamic_tool_allowlist"]) - removed) | added == set(
        slot["dynamic_tool_allowlist"]
    )
    v29_requirements = {
        (item["key"], item["version"])
        for item in v29_slot["requirements"]
        if item["kind"] == "tool"
    }
    v29_compatibility = {
        (item["key"], item["version"])
        for item in v29["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    assert (v29_requirements - gone) | joined == slot_requirements
    assert (v29_compatibility - gone) | joined == node_compatibility
    assert added <= set(RECIPE_0_TOOL_ADDRESSES)
    assert removed.isdisjoint(RECIPE_0_TOOL_ADDRESSES)
    assert v29["version"] == 29
    assert v30["version"] == 30
    assert slot["dynamic_pin_kinds"] == v29_slot["dynamic_pin_kinds"]


def test_web_search_mints_recipe_v32_without_rewriting_v31() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v31 = json.loads((root / "recipe0-stage0-v31.json").read_text())
    v32 = json.loads((root / "recipe0-stage0-v32.json").read_text())
    # One address JOINS and none leaves: `web_search@1`, granted for the first time at
    # `head-of-abm@v62`. The tool has one version, so v32 is v31 plus exactly this address, and
    # v31 stays the exact replay input for a turn pinned to it.
    added = {"web_search@1"}

    v31_index = SYSTEM_RECIPE_FILENAMES.index("recipe0-stage0-v31.json")
    assert SYSTEM_RECIPE_FILENAMES[v31_index : v31_index + 2] == (
        "recipe0-stage0-v31.json",
        "recipe0-stage0-v32.json",
    )
    assert added.isdisjoint(v31["graph"]["tool_allowlist"])
    assert added <= set(v32["graph"]["tool_allowlist"])
    slot = next(node for node in v32["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert added <= set(slot["dynamic_tool_allowlist"])
    slot_requirements = {
        (item["key"], item["version"]) for item in slot["requirements"] if item["kind"] == "tool"
    }
    node_compatibility = {
        (item["key"], item["version"])
        for item in v32["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    joined = {tuple(address.split("@")) for address in added}
    assert joined <= slot_requirements
    assert joined <= node_compatibility
    assert [item for item in slot_requirements if item[0] == "web_search"] == [("web_search", "1")]
    v31_slot = next(
        node for node in v31["graph"]["nodes"] if node["node_key"] == "stage0_interactions"
    )
    assert set(v31["graph"]["tool_allowlist"]) | added == set(v32["graph"]["tool_allowlist"])
    assert set(v31_slot["dynamic_tool_allowlist"]) | added == set(slot["dynamic_tool_allowlist"])
    v31_requirements = {
        (item["key"], item["version"])
        for item in v31_slot["requirements"]
        if item["kind"] == "tool"
    }
    v31_compatibility = {
        (item["key"], item["version"])
        for item in v31["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    assert v31_requirements | joined == slot_requirements
    assert v31_compatibility | joined == node_compatibility
    assert added <= set(RECIPE_0_TOOL_ADDRESSES)
    assert v31["version"] == 31
    assert v32["version"] == 32
    assert slot["dynamic_pin_kinds"] == v31_slot["dynamic_pin_kinds"]


def test_agent_authored_discovery_mints_recipe_v33_without_rewriting_v32() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v32 = json.loads((root / "recipe0-stage0-v32.json").read_text())
    v33 = json.loads((root / "recipe0-stage0-v33.json").read_text())
    # Two addresses are RE-PINNED and none joins: `launch_arv2_discovery` moves to `@2` (the
    # brief the Head of ABM writes) and `read_discovery_run` to `@3` (summary, end reason,
    # exclusions), the contracts `head-of-abm@v70` grants. `@1` and `@2` LEAVE the slot rather
    # than stand beside their successors: a requirement set resolves one version per (kind, key),
    # so both at once refuses promotion. Both stay registered, so v32 stays promotable and is the
    # exact replay input for a turn pinned to it.
    added = {"launch_arv2_discovery@2", "read_discovery_run@3"}
    removed = {"launch_arv2_discovery@1", "read_discovery_run@2"}

    v32_index = SYSTEM_RECIPE_FILENAMES.index("recipe0-stage0-v32.json")
    assert SYSTEM_RECIPE_FILENAMES[v32_index : v32_index + 2] == (
        "recipe0-stage0-v32.json",
        "recipe0-stage0-v33.json",
    )
    assert added.isdisjoint(v32["graph"]["tool_allowlist"])
    assert added <= set(v33["graph"]["tool_allowlist"])
    assert removed <= set(v32["graph"]["tool_allowlist"])
    assert removed.isdisjoint(v33["graph"]["tool_allowlist"])
    slot = next(node for node in v33["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert added <= set(slot["dynamic_tool_allowlist"])
    assert removed.isdisjoint(slot["dynamic_tool_allowlist"])
    slot_requirements = {
        (item["key"], item["version"]) for item in slot["requirements"] if item["kind"] == "tool"
    }
    node_compatibility = {
        (item["key"], item["version"])
        for item in v33["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    joined = {tuple(address.split("@")) for address in added}
    gone = {tuple(address.split("@")) for address in removed}
    assert joined <= slot_requirements
    assert joined <= node_compatibility
    assert gone.isdisjoint(slot_requirements)
    assert gone.isdisjoint(node_compatibility)
    # One version per (kind, key) in the resolved set.
    assert [item for item in slot_requirements if item[0] == "launch_arv2_discovery"] == [
        ("launch_arv2_discovery", "2")
    ]
    assert [item for item in slot_requirements if item[0] == "read_discovery_run"] == [
        ("read_discovery_run", "3")
    ]
    v32_slot = next(
        node for node in v32["graph"]["nodes"] if node["node_key"] == "stage0_interactions"
    )
    assert (set(v32["graph"]["tool_allowlist"]) - removed) | added == set(
        v33["graph"]["tool_allowlist"]
    )
    assert (set(v32_slot["dynamic_tool_allowlist"]) - removed) | added == set(
        slot["dynamic_tool_allowlist"]
    )
    v32_requirements = {
        (item["key"], item["version"])
        for item in v32_slot["requirements"]
        if item["kind"] == "tool"
    }
    v32_compatibility = {
        (item["key"], item["version"])
        for item in v32["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    assert (v32_requirements - gone) | joined == slot_requirements
    assert (v32_compatibility - gone) | joined == node_compatibility
    assert added <= set(RECIPE_0_TOOL_ADDRESSES)
    assert removed.isdisjoint(RECIPE_0_TOOL_ADDRESSES)
    assert v32["version"] == 32
    assert v33["version"] == 33
    assert slot["dynamic_pin_kinds"] == v32_slot["dynamic_pin_kinds"]


def test_operation_id_requirements_are_explicit() -> None:
    audit = build_replay_safety_audit(_standing_recipe_registry())
    operation_bound = {item.address for item in audit if item.operation_id_required}
    assert operation_bound == {
        # FI Lane D D4 added three tools to recipe0-stage0@6; only the draft is operation-bound.
        # Its durable identity *is* the operation (``ResearchDirectiveId(operation_id)``), so a
        # retry lands on the same directive. The gate and the launch are domain-idempotent —
        # a gate is identified by the turn plus the exact revision it presents, and a launch by
        # the confirmed directive plus its account set and budget. Slice 1's trusted readiness
        # decision and synthesis ledger are also operation-bound.
        # The Slice B browser-gate repair replaced @4 with @5 in the promoted revision; @5
        # inherits @4's operation-bound identity unchanged.
        "draft_account_research_directive@5",
        "evaluate_stage0_readiness@2",
        # ARV2 O4: the synthesis unit's evidence call is operation-bound because its ARV2 ledger
        # row is keyed on the operation; like `start_recon@1` it is AT_LEAST_ONCE rather than
        # operation-idempotent, since a retried Exa search cannot converge on one provider call.
        "exa_search_evidence@1",
        "import_accounts@1",
        "profile_contact@1",
        "record_interview_answer@1",
        "research_account_gaps@2",
        "resolve_committee@1",
        "reverse_profile@1",
        "run_deep_account@1",
        "start_confirmed_project_run@3",
        "start_project_run@1",
        # The code sandbox is operation-bound because its durable identity IS the operation's
        # journaled receipt: a retried call converges on the run that already happened rather
        # than running the script a second time over the same workspace.
        "run_python@1",
        # web_search@1 (2026-09-22): operation-bound because its ledger row is keyed on the
        # operation; AT_LEAST_ONCE like `exa_search_evidence@1`, since a retried search cannot
        # converge on one provider call.
        "web_search@1",
        "start_recon@1",
        "submit_onboarding_input@1",
        "synthesize_icps@3",
    }

    exactly_operation_idempotent = {
        item.address for item in audit if item.replay_policy is ReplayPolicy.OPERATION_IDEMPOTENT
    }
    assert exactly_operation_idempotent == operation_bound - {
        "start_recon@1",
        "exa_search_evidence@1",
        "web_search@1",
    }


def test_narrow_recipe_step_requires_an_exact_tool_version() -> None:
    step = RecipeStep(
        step_id="recon",
        tool_name="start_recon",
        tool_version="1",
        input_refs={},
    )
    assert step.tool_version == "1"

    with pytest.raises(ValidationError, match="tool_version"):
        RecipeStep.model_validate(
            {
                "step_id": "recon",
                "tool_name": "start_recon",
                "input_refs": {},
            }
        )
