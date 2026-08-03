"""Provider-neutral external-research preparation and DEEP wait contracts.

External acquisition happens before a short claim-materialization transaction.  These value types
carry only durable references and scheduling metadata, so a project checkpoint can sleep on
provider-owned time without persisting response bodies or provider-specific state.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from clue_core.primitives import EntityId, RunId, UtcDatetime

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ExternalResearchPreparationOutcome(StrEnum):
    READY = "ready"
    WAITING_EXTERNAL = "waiting_external"
    INELIGIBLE = "ineligible"
    FAILED = "failed"


class ExternalResearchPreparation(BaseModel):
    """One provider-neutral acquisition result, containing references rather than payloads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: ExternalResearchPreparationOutcome
    operation_ref: NonEmptyStr | None = None
    snapshot_refs: tuple[NonEmptyStr, ...] = ()
    retry_after: UtcDatetime | None = None
    cost_receipt_ref: NonEmptyStr | None = None
    audit_refs: tuple[NonEmptyStr, ...] = ()
    reason_code: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _coherent(self) -> ExternalResearchPreparation:
        if len(self.snapshot_refs) != len(set(self.snapshot_refs)):
            raise ValueError("external-research snapshot references must be unique")
        if len(self.audit_refs) != len(set(self.audit_refs)):
            raise ValueError("external-research audit references must be unique")
        if self.outcome is ExternalResearchPreparationOutcome.WAITING_EXTERNAL:
            if self.operation_ref is None or self.retry_after is None:
                raise ValueError("an external wait requires an operation reference and retry time")
        elif self.retry_after is not None:
            raise ValueError("only an external wait may carry a retry time")
        if (
            self.outcome
            in {
                ExternalResearchPreparationOutcome.INELIGIBLE,
                ExternalResearchPreparationOutcome.FAILED,
            }
            and self.reason_code is None
        ):
            raise ValueError("an ineligible or failed preparation requires a reason code")
        return self


class DeepAccountExternalWait(BaseModel):
    """The pending external operation for one resumable account-deep run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    account_run_id: RunId
    preparation: ExternalResearchPreparation

    @model_validator(mode="after")
    def _is_waiting(self) -> DeepAccountExternalWait:
        if self.preparation.outcome is not ExternalResearchPreparationOutcome.WAITING_EXTERNAL:
            raise ValueError("a deep external wait must carry a waiting preparation")
        return self


class DeepExternalWakeReason(StrEnum):
    SCHEDULED_POLL = "scheduled_poll"
    PROVIDER_EVENT = "provider_event"
    MANUAL_RECONCILE = "manual_reconcile"
    CRASH_RECOVERY = "crash_recovery"


class DeepExternalWait(BaseModel):
    """Reference-only DEEP phase checkpoint while account operations wait externally."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pending_accounts: tuple[DeepAccountExternalWait, ...]
    next_poll_at: UtcDatetime
    wake_reason: DeepExternalWakeReason = DeepExternalWakeReason.SCHEDULED_POLL

    @model_validator(mode="after")
    def _bounded_and_consistent(self) -> DeepExternalWait:
        if not self.pending_accounts:
            raise ValueError("a deep external wait requires at least one pending account")
        account_ids = tuple(item.account_entity_id for item in self.pending_accounts)
        run_ids = tuple(item.account_run_id for item in self.pending_accounts)
        if len(account_ids) != len(set(account_ids)) or len(run_ids) != len(set(run_ids)):
            raise ValueError("deep external wait accounts and account runs must be unique")
        retry_times = tuple(item.preparation.retry_after for item in self.pending_accounts)
        if any(value is None for value in retry_times):  # defended by the nested model
            raise ValueError("every pending account requires a retry time")
        if self.next_poll_at != min(value for value in retry_times if value is not None):
            raise ValueError("deep next_poll_at must be the earliest pending retry")
        return self


__all__ = [
    "DeepAccountExternalWait",
    "DeepExternalWait",
    "DeepExternalWakeReason",
    "ExternalResearchPreparation",
    "ExternalResearchPreparationOutcome",
]
