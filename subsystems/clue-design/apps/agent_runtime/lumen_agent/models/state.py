"""Turn state model (constitution) for the lumen_agent deepagent."""

from __future__ import annotations

from typing import Optional, TypedDict



try:  # pragma: no cover - exercised whenever deepagents is installed
    from deepagents import DeepAgentState as _DeepAgentStateBase
except Exception:  # pragma: no cover - keeps import-time failures out of tests
    _DeepAgentStateBase = TypedDict  # type: ignore[misc,assignment]


class LumenTurnState(_DeepAgentStateBase):  # type: ignore[misc,valid-type]
    """The turn constitution — tiny typed fields that ride shared state into
    every subagent (S3: propagated automatically minus messages/todos/
    structured_response). Round PATHS in task descriptions stay authoritative;
    `current_round` is a field, not the source of truth for delegation."""

    seeded: bool
    chip_target_node_ids: list[str]
    brand_kit_ref: dict
    artboard_id: Optional[str]
    turn_request: str
    current_round: int
    # RC: the user-attached reference image asset ids for THIS turn, in attachment
    # order. Always present (empty list when no references rode the turn — the same
    # always-present-but-possibly-empty shape as chip_target_node_ids), so every
    # subagent can see whether references are in play from shared state alone.
    reference_asset_ids: list[str]


# The constitution fields, in declaration order — pinned by the state-schema
# test and reused when building the initial invoke state.
CONSTITUTION_FIELDS = (
    "seeded",
    "chip_target_node_ids",
    "brand_kit_ref",
    "artboard_id",
    "turn_request",
    "current_round",
    "reference_asset_ids",
)
