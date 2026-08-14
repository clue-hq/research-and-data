from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

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


def test_s4d_mints_recipe_v8_and_preserves_v7_for_exact_replay() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v7 = json.loads((root / "recipe0-stage0-v7.json").read_text())
    v8 = json.loads((root / "recipe0-stage0-v8.json").read_text())
    client_addresses = {"list_client_knowledge", "inspect_client_claim"}

    v7_index = SYSTEM_RECIPE_FILENAMES.index("recipe0-stage0-v7.json")
    assert SYSTEM_RECIPE_FILENAMES[v7_index : v7_index + 2] == (
        "recipe0-stage0-v7.json",
        "recipe0-stage0-v8.json",
    )
    assert v7["version"] == 7
    assert v8["version"] == 8
    assert {
        address
        for address in v7["graph"]["tool_allowlist"]
        if address.split("@")[0] in client_addresses
    } == {
        "list_client_knowledge@1",
        "inspect_client_claim@1",
    }
    assert {
        address
        for address in v8["graph"]["tool_allowlist"]
        if address.split("@")[0] in client_addresses
    } == {
        "list_client_knowledge@2",
        "inspect_client_claim@2",
    }
    for requirement in v8["compatibility"]["nodes"]["stage0_interactions"]:
        if requirement["kind"] == "tool" and requirement["key"] in client_addresses:
            assert requirement["version"] == "2"


def test_operation_id_requirements_are_explicit() -> None:
    audit = build_replay_safety_audit(_standing_recipe_registry())
    operation_bound = {item.address for item in audit if item.operation_id_required}
    assert operation_bound == {
        # FI Lane D D4 added three tools to recipe0-stage0@6; only the draft is operation-bound.
        # Its durable identity *is* the operation (``ResearchDirectiveId(operation_id)``), so a
        # retry lands on the same directive. The gate and the launch are domain-idempotent —
        # a gate is identified by the turn plus the exact revision it presents, and a launch by
        # the confirmed directive plus its account set and budget.
        "draft_account_research_directive@2",
        "evaluate_stage0_readiness@1",
        "import_accounts@1",
        "profile_contact@1",
        "record_interview_answer@1",
        "research_account_gaps@2",
        "resolve_committee@1",
        "reverse_profile@1",
        "run_deep_account@1",
        "start_confirmed_project_run@1",
        "start_project_run@1",
        "start_recon@1",
        "submit_onboarding_input@1",
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
