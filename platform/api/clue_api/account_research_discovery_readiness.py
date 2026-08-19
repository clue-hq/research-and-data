"""Sealed-discovery authority required before account profiling can launch."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import DiscoveryBatchId, DiscoveryBatchState, ProjectRunId
from clue_research.durable import get_current_discovery_batch, get_discovery_batch_seal

ACCOUNT_DISCOVERY_IN_PROGRESS_REASON = "account_discovery_in_progress"
ACCOUNT_DISCOVERY_IN_PROGRESS_MESSAGE = (
    "Account discovery is still in progress. Please wait and try account profiling again after "
    "discovery finishes."
)


class AccountResearchDiscoveryNotReady(RuntimeError):
    """The current run has no immutable discovery receipt that can authorize profiling."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class AccountResearchDiscoveryReceipt:
    discovery_batch_id: DiscoveryBatchId
    discovery_generation: int
    discovery_seal_sha256: str


async def require_sealed_account_discovery(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    icp_key: str,
    icp_version: int,
    for_update: bool = False,
) -> AccountResearchDiscoveryReceipt:
    """Return the current immutable seal receipt or refuse before any research write/spend."""

    batch = await get_current_discovery_batch(
        conn,
        workspace_id=workspace_id,
        project_run_id=project_run_id,
        for_update=for_update,
    )
    if batch is None:
        raise AccountResearchDiscoveryNotReady(
            "Account discovery is not complete. Please finish account discovery before starting "
            "account profiling.",
            reason_code="account_discovery_not_started",
        )
    if batch.state is not DiscoveryBatchState.SEALED:
        if batch.state in {
            DiscoveryBatchState.FAILED_TERMINAL,
            DiscoveryBatchState.CANCELLED_UNSEALED,
        }:
            raise AccountResearchDiscoveryNotReady(
                "Account discovery did not finish with a final seal. Please retry discovery "
                "before starting account profiling.",
                reason_code="account_discovery_not_sealed",
            )
        raise AccountResearchDiscoveryNotReady(
            ACCOUNT_DISCOVERY_IN_PROGRESS_MESSAGE,
            reason_code=ACCOUNT_DISCOVERY_IN_PROGRESS_REASON,
        )
    seal = await get_discovery_batch_seal(
        conn,
        workspace_id=workspace_id,
        batch_id=batch.id,
    )
    if (
        seal is None
        or batch.icp_key != icp_key
        or batch.icp_version != icp_version
        or seal.project_run_id != project_run_id
        or seal.icp_key != icp_key
        or seal.icp_version != icp_version
        or seal.discovery_plan_id != batch.discovery_plan_id
    ):
        raise AccountResearchDiscoveryNotReady(
            "Account discovery's final seal is incomplete. Please retry discovery before "
            "starting account profiling.",
            reason_code="account_discovery_seal_invalid",
        )
    return AccountResearchDiscoveryReceipt(
        discovery_batch_id=batch.id,
        discovery_generation=batch.generation,
        discovery_seal_sha256=seal.seal_sha256,
    )


__all__ = [
    "ACCOUNT_DISCOVERY_IN_PROGRESS_MESSAGE",
    "ACCOUNT_DISCOVERY_IN_PROGRESS_REASON",
    "AccountResearchDiscoveryNotReady",
    "AccountResearchDiscoveryReceipt",
    "require_sealed_account_discovery",
]
