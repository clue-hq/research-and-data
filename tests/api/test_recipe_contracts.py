from __future__ import annotations

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


def test_operation_id_requirements_are_explicit() -> None:
    audit = build_replay_safety_audit(_standing_recipe_registry())
    operation_bound = {item.address for item in audit if item.operation_id_required}
    assert operation_bound == {
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
