"""Append-only S2D committee eligibility decision audit repository."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    CommitteeEligibilityDecision,
    CommitteeEligibilityDecisionId,
    EntityId,
    ProjectRunId,
    serialize_value_json,
)

_COLUMNS = (
    "id, workspace_id, project_id, project_run_id, account_id, request_fingerprint, "
    "authorization_fingerprint, policy_version, outcome::text, conditions_json, "
    "reusable_operation_id, created_at"
)


def _decision(row: object) -> CommitteeEligibilityDecision:
    data = dict(row._mapping)  # type: ignore[attr-defined]
    data["decision_id"] = data.pop("id")
    data["conditions"] = data.pop("conditions_json")
    return CommitteeEligibilityDecision.model_validate(data)


async def record_committee_eligibility_decision(
    conn: AsyncConnection, decision: CommitteeEligibilityDecision
) -> tuple[CommitteeEligibilityDecision, bool]:
    """Insert once by content fingerprint; immutable replay returns the original decision."""

    reasons = tuple(
        dict.fromkeys(reason for item in decision.conditions for reason in item.reason_codes)
    )
    evidence = tuple(
        dict.fromkeys(reference for item in decision.conditions for reference in item.evidence_refs)
    )
    inserted = (
        await conn.execute(
            text(
                "INSERT INTO committee_eligibility_decision ("
                "id, workspace_id, project_id, project_run_id, account_id, request_fingerprint, "
                "authorization_fingerprint, decision_fingerprint, policy_version, outcome, "
                "conditions_json, reason_codes_json, evidence_refs_json, reusable_operation_id"
                ") VALUES ("
                ":id, :workspace_id, :project_id, :project_run_id, :account_id, "
                ":request_fingerprint, :authorization_fingerprint, :decision_fingerprint, "
                ":policy_version, CAST(:outcome AS committee_eligibility_outcome), "
                "CAST(:conditions AS jsonb), CAST(:reasons AS jsonb), CAST(:evidence AS jsonb), "
                ":reusable_operation_id) ON CONFLICT (workspace_id, project_run_id, account_id, "
                "decision_fingerprint) DO NOTHING RETURNING " + _COLUMNS
            ),
            {
                "id": decision.decision_id,
                "workspace_id": decision.workspace_id,
                "project_id": decision.project_id,
                "project_run_id": decision.project_run_id,
                "account_id": decision.account_id,
                "request_fingerprint": decision.request_fingerprint,
                "authorization_fingerprint": decision.authorization_fingerprint,
                "decision_fingerprint": decision.decision_fingerprint,
                "policy_version": decision.policy_version,
                "outcome": decision.outcome.value,
                "conditions": serialize_value_json(
                    [item.model_dump(mode="json") for item in decision.conditions]
                ),
                "reasons": serialize_value_json(list(reasons)),
                "evidence": serialize_value_json(list(evidence)),
                "reusable_operation_id": decision.reusable_operation_id,
            },
        )
    ).one_or_none()
    if inserted is not None:
        return _decision(inserted), True
    replay = await find_committee_eligibility_decision(
        conn,
        workspace_id=decision.workspace_id,
        project_run_id=decision.project_run_id,
        account_id=decision.account_id,
        decision_fingerprint=decision.decision_fingerprint,
    )
    if replay is None:
        raise RuntimeError("committee eligibility decision conflict did not resolve")
    return replay, False


async def find_committee_eligibility_decision(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    account_id: EntityId,
    decision_fingerprint: str,
) -> CommitteeEligibilityDecision | None:
    row = (
        await conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM committee_eligibility_decision "
                "WHERE workspace_id=:workspace_id AND project_run_id=:project_run_id "
                "AND account_id=:account_id AND decision_fingerprint=:decision_fingerprint"
            ),
            {
                "workspace_id": workspace_id,
                "project_run_id": project_run_id,
                "account_id": account_id,
                "decision_fingerprint": decision_fingerprint,
            },
        )
    ).one_or_none()
    return _decision(row) if row is not None else None


async def get_committee_eligibility_decision(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    decision_id: CommitteeEligibilityDecisionId,
) -> CommitteeEligibilityDecision | None:
    row = (
        await conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM committee_eligibility_decision "
                "WHERE workspace_id=:workspace_id AND id=:decision_id"
            ),
            {"workspace_id": workspace_id, "decision_id": decision_id},
        )
    ).one_or_none()
    return _decision(row) if row is not None else None


__all__ = [
    "find_committee_eligibility_decision",
    "get_committee_eligibility_decision",
    "record_committee_eligibility_decision",
]
