"""Pure contract checks for M8D R2's shared account/contact fleet envelope."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest
from pydantic import ValidationError
from tests.fleet.entity_research_r2_helpers import run_envelope

from clue_core.entity_research import ResearchRunKind, ResearchSubjectType
from clue_fleet import (
    EntityResearchDriverDisposition,
    EntityResearchDriverResult,
    EntityResearchJobDriver,
    EntityResearchJobStore,
    EntityResearchJobWorkHandler,
    EntityResearchRunEnvelope,
    FleetTaskKind,
)


def test_account_and_contact_runs_are_distinct_authority_over_one_job_shape() -> None:
    account = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH)
    contact = run_envelope(ResearchRunKind.CONTACT_RESEARCH)

    assert type(account) is type(contact) is EntityResearchRunEnvelope
    assert account.lifecycle.run_kind is ResearchRunKind.ACCOUNT_RESEARCH
    assert contact.lifecycle.run_kind is ResearchRunKind.CONTACT_RESEARCH
    assert {job.authorization.subject_type for job in account.jobs} == {ResearchSubjectType.ACCOUNT}
    assert {job.authorization.subject_type for job in contact.jobs} == {ResearchSubjectType.CONTACT}
    assert account.lifecycle.run_id != contact.lifecycle.run_id
    assert account.lifecycle.selection.selection_id != contact.lifecycle.selection.selection_id
    assert account.concurrency_limit == 1
    assert contact.concurrency_limit == 2


def test_run_envelope_rejects_job_scope_or_budget_widening() -> None:
    account = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH)
    payload = account.model_dump(mode="python")
    payload["jobs"][0]["budget_cap_cents"] = Decimal("10.01")
    with pytest.raises(ValidationError, match="job budget cannot exceed"):
        EntityResearchRunEnvelope.model_validate(payload)

    contact = run_envelope(ResearchRunKind.CONTACT_RESEARCH)
    widened = contact.model_dump(mode="python")
    widened["jobs"] = widened["jobs"][:1]
    with pytest.raises(ValidationError, match="exactly cover the confirmed selection"):
        EntityResearchRunEnvelope.model_validate(widened)


def test_driver_boundary_is_only_complete_wait_or_accepted_finalization() -> None:
    waiting = EntityResearchDriverResult(
        disposition=EntityResearchDriverDisposition.WAITING_EXTERNAL,
        wait_ref="provider-operation:1",
        checkpoint_ref="checkpoint:1",
        checkpoint_sha256="a" * 64,
        current_state_sha256="b" * 64,
    )
    assert waiting.disposition is EntityResearchDriverDisposition.WAITING_EXTERNAL

    with pytest.raises(ValidationError, match="exact wait and checkpoint state"):
        EntityResearchDriverResult(
            disposition=EntityResearchDriverDisposition.WAITING_EXTERNAL,
            wait_ref="provider-operation:1",
        )
    with pytest.raises(ValidationError, match="accepted engine receipt"):
        EntityResearchDriverResult(disposition=EntityResearchDriverDisposition.FINALIZED)


def test_one_subject_neutral_handler_kind_serves_both_run_kinds() -> None:
    handler = EntityResearchJobWorkHandler(
        store=cast(EntityResearchJobStore, object()),
        driver=cast(EntityResearchJobDriver, object()),
    )
    assert handler.kind is FleetTaskKind.ENTITY_RESEARCH_JOB
    assert "account" not in handler.kind.value
    assert "contact" not in handler.kind.value
