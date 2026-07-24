from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from clue_core import ExecutionId, operation_id_from_key
from clue_execution import (
    ExecutionEventType,
    ExecutionNodeKind,
    ExecutionStatus,
    PinRequest,
    RunAggregateSnapshot,
)


def test_closed_execution_vocabularies_are_stable_strings() -> None:
    assert ExecutionStatus.AWAITING_INPUT.value == "awaiting_input"
    assert ExecutionNodeKind.ACTIVITY.value == "activity"
    assert ExecutionEventType.STEERING_BEFORE.value == "steering.before"


def test_pin_request_requires_exact_version_or_digest() -> None:
    with pytest.raises(ValidationError, match="version or digest"):
        PinRequest(kind="tool", key="reverse_profile")
    pin = PinRequest(kind="tool", key="reverse_profile", version="1")
    assert pin.version == "1"
    with pytest.raises(ValidationError):
        PinRequest(kind="tool", key="reverse_profile", version="")
    with pytest.raises(ValidationError):
        PinRequest(kind="tool", key="reverse_profile", digest="not-a-sha256")


def test_aggregate_snapshot_is_frozen_and_strict() -> None:
    snapshot = RunAggregateSnapshot(
        execution_id=ExecutionId(uuid4()),
        policy_version="supervisor@1",
        counts={"attempts": 3},
        rates={"failure_rate": 0.0},
    )
    assert snapshot.counts == {"attempts": 3}
    with pytest.raises(ValidationError):
        snapshot.policy_version = "changed"  # type: ignore[misc]


def test_operation_id_from_scoped_key_is_stable_and_scoped() -> None:
    first = operation_id_from_key("ws-a", "recipe0:recon")
    assert operation_id_from_key("ws-a", "recipe0:recon") == first
    assert operation_id_from_key("ws-b", "recipe0:recon") != first
    assert operation_id_from_key("ws-a", "recipe0:other") != first
