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
from clue_api.recipe_wiring import SYSTEM_RECIPE_FILENAMES
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

    assert CONVERSATION_RECIPE_VERSION == 17


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
        "draft_account_research_directive@3",
        "evaluate_stage0_readiness@2",
        "import_accounts@1",
        "profile_contact@1",
        "record_interview_answer@1",
        "research_account_gaps@2",
        "resolve_committee@1",
        "reverse_profile@1",
        "run_deep_account@1",
        "start_confirmed_project_run@3",
        "start_project_run@1",
        "start_recon@1",
        "submit_onboarding_input@1",
        "synthesize_icps@3",
    }

    exactly_operation_idempotent = {
        item.address for item in audit if item.replay_policy is ReplayPolicy.OPERATION_IDEMPOTENT
    }
    assert exactly_operation_idempotent == operation_bound - {"start_recon@1"}


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
