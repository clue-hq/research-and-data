"""Canonical builders shared by the M8D R2 pure and Postgres acceptance tests."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    FinalizationVerification,
    ResearchFinalizationOutcome,
    ResearchFinalizationProposal,
    ResearchFinalizationReceipt,
    ResearchRunKind,
    ResearchRunLifecycleContract,
    ResearchSubjectType,
)
from clue_fleet import EntityResearchJobEnvelope, EntityResearchRunEnvelope

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "entity_research" / "r0_contract_fixture.json"


def _lookup(root: Any, path: str) -> Any:
    current = root
    for part in path.split("."):
        current = current[int(part)] if part.isdigit() else current[part]
    return current


def _resolve(value: Any, root: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return _resolve(copy.deepcopy(_lookup(root, value[1:])), root)
    if isinstance(value, dict):
        return {key: _resolve(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, root) for item in value]
    return value


def lifecycle_fixture(run_kind: ResearchRunKind) -> ResearchRunLifecycleContract:
    root = cast(dict[str, Any], json.loads(_FIXTURE.read_text()))
    key = (
        "account_lifecycle" if run_kind is ResearchRunKind.ACCOUNT_RESEARCH else "contact_lifecycle"
    )
    payload = cast(dict[str, Any], _resolve(copy.deepcopy(root[key]), root))
    # Every database test receives independent identities while retaining the frozen R0 shape.
    payload["run_id"] = str(uuid4())
    selection = cast(dict[str, Any], payload["selection"])
    selection["selection_id"] = str(uuid4())
    selection["workspace_id"] = str(uuid4())
    selection["project_id"] = str(uuid4())
    selection["product_id"] = str(uuid4())
    selection["project_run_id"] = str(uuid4())
    selection["confirmed_at"] = datetime.now(UTC).isoformat()
    if run_kind is ResearchRunKind.ACCOUNT_RESEARCH:
        selection["subjects"][0]["subject_entity_id"] = str(uuid4())
    else:
        selection["account_entity_id"] = str(uuid4())
        for subject in selection["subjects"]:
            subject["subject_entity_id"] = str(uuid4())
    return ResearchRunLifecycleContract.model_validate(payload)


def run_envelope(
    run_kind: ResearchRunKind,
    *,
    concurrency_limit: int | None = None,
) -> EntityResearchRunEnvelope:
    lifecycle = lifecycle_fixture(run_kind)
    jobs: list[EntityResearchJobEnvelope] = []
    for priority, subject in enumerate(lifecycle.selection.subjects):
        authorization = EntityResearchJobAuthorization(
            job_id=uuid4(),
            research_run_id=lifecycle.run_id,
            subject_type=lifecycle.selection.subject_type,
            subject_entity_id=subject.subject_entity_id,
            parent_account_id=lifecycle.selection.account_entity_id,
            workspace_id=lifecycle.selection.workspace_id,
            project_id=lifecycle.selection.project_id,
            product_id=lifecycle.selection.product_id,
            project_run_id=lifecycle.selection.project_run_id,
            selection=lifecycle.selection,
            agent_profile_ref=f"agent-profile:{lifecycle.selection.subject_type.value}:v1",
            agent_profile_sha256=("c" if priority == 0 else "d") * 64,
            checkpoint_thread_id=f"checkpoint:{lifecycle.run_id}:{subject.subject_entity_id}",
            attempt_id=uuid4(),
            lease_id=uuid4(),
        )
        jobs.append(
            EntityResearchJobEnvelope(
                authorization=authorization,
                priority=priority,
                budget_envelope_ref=f"budget:job:{authorization.job_id}",
                budget_cap_cents=Decimal("4.00"),
            )
        )
    return EntityResearchRunEnvelope(
        lifecycle=lifecycle,
        jobs=tuple(jobs),
        budget_cap_cents=Decimal("10.00"),
        concurrency_limit=(
            concurrency_limit
            if concurrency_limit is not None
            else (1 if run_kind is ResearchRunKind.ACCOUNT_RESEARCH else 2)
        ),
    )


def finalization_receipt(
    *,
    job_id: UUID,
    subject_type: ResearchSubjectType,
    target_entity_id: UUID,
    current_state_sha256: str,
    outcome: ResearchFinalizationOutcome = ResearchFinalizationOutcome.COMPLETED,
) -> ResearchFinalizationReceipt:
    completed = (
        (f"{subject_type.value}.research_complete",)
        if outcome is ResearchFinalizationOutcome.COMPLETED
        else ()
    )
    # A ``needs_review`` proposal is only well-formed with durable review flags, so the helper
    # supplies one rather than leaving that outcome unusable for callers.
    review_flags = (
        (f"{subject_type.value}.needs_review",)
        if outcome is ResearchFinalizationOutcome.NEEDS_REVIEW
        else ()
    )
    proposal = ResearchFinalizationProposal(
        proposal_id=uuid4(),
        subject_type=subject_type,
        target_entity_id=target_entity_id,
        outcome=outcome,
        current_state_sha256=current_state_sha256,
        coverage_ledger_ref=f"coverage:{job_id}",
        claim_delta_ledger_ref=f"claim-delta:{job_id}",
        spend_reconciliation_ref=f"spend:{job_id}",
        identity_use_verification_ref=f"identity-use:{job_id}",
        completed_field_keys=completed,
        review_flags=review_flags,
    )
    return ResearchFinalizationReceipt(
        receipt_id=uuid4(),
        proposal=proposal,
        proposal_ref=f"finalization-proposal:{proposal.proposal_id}",
        engine_actor="engine:entity-research-finalizer",
        accepted_at=datetime.now(UTC),
        accepted_state_sha256=current_state_sha256,
        verification=FinalizationVerification(
            no_pending_operations=True,
            evidence_complete=True,
            coverage_matches=True,
            spend_reconciled=True,
            identity_use_verification_complete=True,
            policy_scope_respected=True,
            current_state_matches=True,
        ),
    )


__all__ = ["finalization_receipt", "lifecycle_fixture", "run_envelope"]
