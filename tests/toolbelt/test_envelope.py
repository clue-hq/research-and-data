"""Envelope value types: PreconditionFailure, ToolEstimate, ToolResult round-trip, ToolInput."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from clue_toolbelt import (
    ExternalReplayBoundary,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    ToolEstimate,
    ToolResult,
)
from tests.toolbelt.conftest import EchoInput, EchoTool


def test_precondition_failure_is_machine_readable() -> None:
    f = PreconditionFailure(reason_code="no_active_icp", message="confirm an ICP first")
    assert f.reason_code == "no_active_icp"
    assert "ICP" in f.message


def test_tool_estimate_free_is_zero() -> None:
    assert ToolEstimate.free().cost_cents == Decimal(0)
    assert ToolEstimate(cost_cents=Decimal("12.5")).cost_cents == Decimal("12.5")


def test_tool_result_round_trips_through_json() -> None:
    """The idempotency store replays a stored response — the result must survive a JSON dump/load
    byte-for-byte so a replay reconstructs it."""
    result = ToolResult(tool="echo", version="1", references={"echoed": 7})
    reloaded = ToolResult.model_validate(result.model_dump(mode="json"))
    assert reloaded == result
    assert reloaded.replayed is False


def test_tool_input_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        EchoInput.model_validate({"value": 1, "typo": 2})


def test_tool_input_is_frozen() -> None:
    inputs = EchoInput(value=3)
    with pytest.raises(ValidationError):
        inputs.value = 4  # type: ignore[misc]


def test_descriptor_freezes_exact_schemas_and_recipe_safety() -> None:
    descriptor = EchoTool().descriptor
    assert descriptor.address == "echo@1"
    assert descriptor.has_typed_output is True
    assert descriptor.recipe_safe is False  # test double deliberately has no replay certification
    assert len(descriptor.input_schema_sha256) == 64
    assert len(descriptor.output_schema_sha256) == 64


def test_replay_safety_rejects_contradictory_external_boundary() -> None:
    with pytest.raises(ValueError, match="at-least-once external boundary"):
        ReplaySafety(
            policy=ReplayPolicy.AT_LEAST_ONCE,
            durable_identity="provider request",
        )

    with pytest.raises(ValueError, match="effect-free"):
        ReplaySafety(
            policy=ReplayPolicy.EFFECT_FREE,
            durable_identity="none",
            external_boundary=ExternalReplayBoundary.IDEMPOTENCY_KEY,
        )
