"""Scoring-owned exact fit projection for C7 owner references."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import Claim, ClaimId, EntityId, ProjectRunId, VerificationStatus
from clue_research.claimstore import WorkspaceScope, claims_by_ids, claims_for_entities
from clue_research.discovery_scoring.scoring import FIT_FIELD


class AmbiguousFitProjection(ValueError):
    """More than one live score exists for the exact pinned scope."""


@dataclass(frozen=True)
class FitProjection:
    claim: Claim
    evidence_claim_ids: tuple[ClaimId, ...]


def _component_evidence(claim: Claim) -> tuple[ClaimId, ...]:
    value = claim.value_json
    if not isinstance(value, dict):
        return ()
    components = value.get("components")
    if not isinstance(components, list):
        return ()
    ids: list[ClaimId] = []
    for component in components:
        if not isinstance(component, dict):
            continue
        raw_ids = component.get("evidence_claim_ids")
        if not isinstance(raw_ids, list):
            continue
        for raw in raw_ids:
            try:
                claim_id = ClaimId(UUID(str(raw)))
            except (TypeError, ValueError):
                continue
            if claim_id not in ids:
                ids.append(claim_id)
    return tuple(ids)


async def exact_fit_projection(
    conn: AsyncConnection,
    *,
    member_entity_ids: Sequence[EntityId],
    workspace_id: str,
    project_run_id: ProjectRunId,
    icp_key: str,
    icp_version: int,
    product_id: str,
) -> FitProjection | None:
    """Load, never recompute, one exact product/ICP fit and validate its evidence refs."""

    scope = WorkspaceScope.for_workspace(workspace_id)
    claims = await claims_for_entities(
        conn,
        member_entity_ids,
        (FIT_FIELD,),
        scope=scope,
    )
    matches: list[Claim] = []
    for claim in claims:
        value = claim.value_json
        if (
            claim.product_id != product_id
            or claim.verification_status
            not in {VerificationStatus.VERIFIED, VerificationStatus.FLAGGED}
            or not isinstance(value, dict)
            or value.get("icp_key") != icp_key
            or value.get("icp_version") != icp_version
            or value.get("project_run_id") != str(project_run_id)
        ):
            continue
        matches.append(claim)
    if len(matches) > 1:
        raise AmbiguousFitProjection(
            "multiple live fit claims exist in the exact product/ICP scope"
        )
    if not matches:
        return None
    claim = matches[0]
    evidence_ids = _component_evidence(claim)
    if not evidence_ids:
        return None
    evidence = await claims_by_ids(conn, evidence_ids, scope=scope)
    if set(evidence) != set(evidence_ids):
        return None
    if any(
        item.product_id not in {None, product_id} or item.entity_id not in set(member_entity_ids)
        for item in evidence.values()
    ):
        return None
    return FitProjection(claim=claim, evidence_claim_ids=evidence_ids)


__all__ = ["AmbiguousFitProjection", "FitProjection", "exact_fit_projection"]
