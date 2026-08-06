"""S2D-gated composition of Sumble committee eligibility and S2B acquisition."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from clue_api.committee_eligibility import CommitteeEligibilityService
from clue_api.sumble_committee_acquisition import (
    SumbleCommitteePreflight,
    SumbleCommitteeResult,
)
from clue_core import (
    CommitteeEligibilityDecision,
    CommitteeEligibilityOutcome,
    CommitteeExecutionAuthorization,
)


class SumbleCommitteeStarter(Protocol):
    async def start(self, preflight: SumbleCommitteePreflight) -> SumbleCommitteeResult: ...


class GatedSumbleCommitteeResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    eligibility: CommitteeEligibilityDecision
    acquisition: SumbleCommitteeResult | None = None

    @model_validator(mode="after")
    def _coherent(self) -> GatedSumbleCommitteeResult:
        should_acquire = self.eligibility.outcome is CommitteeEligibilityOutcome.ELIGIBLE
        if should_acquire != (self.acquisition is not None):
            raise ValueError("only an eligible committee decision may start acquisition")
        return self


class GatedSumbleCommitteeLauncher:
    """The sole S2 composition path: no eligibility means no coordinator/provider call."""

    def __init__(
        self,
        *,
        eligibility: CommitteeEligibilityService,
        starter: SumbleCommitteeStarter,
    ) -> None:
        self._eligibility = eligibility
        self._starter = starter

    async def start(
        self,
        preflight: SumbleCommitteePreflight,
        *,
        authorization: CommitteeExecutionAuthorization,
    ) -> GatedSumbleCommitteeResult:
        decision = await self._eligibility.evaluate(
            preflight.request,
            authorization=authorization,
            proposed_cost_cents=preflight.maximum_cost_cents,
        )
        if decision.outcome is not CommitteeEligibilityOutcome.ELIGIBLE:
            return GatedSumbleCommitteeResult(eligibility=decision)
        acquisition = await self._starter.start(preflight)
        return GatedSumbleCommitteeResult(
            eligibility=decision,
            acquisition=acquisition,
        )


__all__ = [
    "GatedSumbleCommitteeLauncher",
    "GatedSumbleCommitteeResult",
    "SumbleCommitteeStarter",
]
