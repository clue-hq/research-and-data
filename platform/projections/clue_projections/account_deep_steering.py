"""Bounded current-state card for Head-of-ABM account-deep planning and steering (M8B O3).

The card is a read projection, not a workflow state and not authorization. It puts the exact
human-approved account set, newest directive preview, immutable launch receipt, and current
per-account execution cursors in one deterministic L3 artifact. The Head may discuss any next
move; engines and human gates remain authoritative for confirmation and spend.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from clue_core import EntityId, ProjectRunId
from clue_projections.research_directives import ResearchDirectivePreview

ACCOUNT_DEEP_STEERING_CARD_MEDIA_TYPE = "application/vnd.clue.account-deep-steering-card+json"


class AccountDeepSteeringAccount(BaseModel):
    """One canonical account and its independent planning/execution memberships."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    canonical_name: str
    primary_domain: str | None = None
    tier_approved: bool
    approved_tier: str | None = None
    in_latest_directive: bool
    in_launch: bool
    account_run_id: str | None = None
    account_run_status: str | None = None
    account_run_sub_phase: str | None = None
    account_run_cost_cents: Decimal | None = None


class AccountDeepSteeringLaunch(BaseModel):
    """The immutable O2 launch receipt. Presence means authorized launch, never completion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    launch_ref: str
    launch_id: str
    directive_id: str
    directive_version: int
    directive_sha256: str
    account_entity_ids: tuple[EntityId, ...]
    estimated_cost_cents: Decimal
    approved_budget_cap_cents: Decimal
    created_at: str


class AccountDeepSteeringCard(BaseModel):
    """Current durable inputs for a non-linear Head-of-ABM conversation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    card_kind: Literal["account_deep_steering"] = "account_deep_steering"
    workspace_id: str
    project_id: str
    project_run_id: ProjectRunId
    project_run_phase: str
    project_run_status: str
    icp_key: str
    icp_version: int
    run_budget_cap_cents: Decimal | None
    run_spent_cents: Decimal
    tier_checkpoint_status: str | None
    approved_tier: str | None
    approved_account_count: int
    accounts: tuple[AccountDeepSteeringAccount, ...]
    latest_directive: ResearchDirectivePreview | None
    latest_directive_sha256: str | None
    launch_state: Literal["not_launched", "receipt_created"]
    launch: AccountDeepSteeringLaunch | None

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()

    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


__all__ = [
    "ACCOUNT_DEEP_STEERING_CARD_MEDIA_TYPE",
    "AccountDeepSteeringAccount",
    "AccountDeepSteeringCard",
    "AccountDeepSteeringLaunch",
]
