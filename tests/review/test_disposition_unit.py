"""M13.2 — pure (no-DB) unit tests: natural keys, the record validators, the review-action mapping,
and the store/emitter Protocol conformance. These run in plain ``make check`` (no Postgres)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from clue_core import (
    EntityType,
    ReviewAction,
    new_campaign_run_id,
    new_claim_id,
    new_entity_id,
)
from clue_core.review import ReviewDispositionEmitter
from clue_research.review import (
    ACCOUNT_DISPOSITION_TYPES,
    CLAIM_DISPOSITION_TYPES,
    REVIEW_ACTION_TO_DISPOSITION,
    DispositionActor,
    DispositionOrigin,
    DispositionStore,
    DispositionType,
    DownstreamOutcome,
    FeedbackDisposition,
    ReviewDispositionEmitterImpl,
)
from clue_research.review.disposition import downstream_natural_key, review_natural_key

_NOW = datetime(2026, 6, 26, tzinfo=UTC)


def test_taxonomy_partitions_cleanly() -> None:
    """The claim-level and account-level halves are disjoint and cover the whole taxonomy."""
    assert CLAIM_DISPOSITION_TYPES.isdisjoint(ACCOUNT_DISPOSITION_TYPES)
    assert set(DispositionType) == CLAIM_DISPOSITION_TYPES | ACCOUNT_DISPOSITION_TYPES
    # every review action maps to a claim-level type.
    assert set(REVIEW_ACTION_TO_DISPOSITION) == set(ReviewAction)
    assert set(REVIEW_ACTION_TO_DISPOSITION.values()) == CLAIM_DISPOSITION_TYPES


def test_natural_keys() -> None:
    rid = uuid4()
    assert review_natural_key(rid) == f"review_surface:{rid}"
    assert (
        downstream_natural_key(
            origin=DispositionOrigin.CRM_INGEST,
            client_id="acme",
            external_id="op-7",
            disposition_type=DispositionType.MEETING_BOOKED,
        )
        == "crm_ingest:acme:op-7:meeting_booked"
    )


def test_for_review_action_builds_a_valid_record() -> None:
    account = new_entity_id()
    claim = new_claim_id()
    rid = uuid4()
    d = FeedbackDisposition.for_review_action(
        disposition_type=DispositionType.CLAIM_REJECTED,
        entity_id=account,
        entity_type=EntityType.ACCOUNT,
        account_entity_id=account,
        claim_id=claim,
        campaign_run_id=new_campaign_run_id(),
        client_id="acme",
        icp_key="seg",
        icp_spec_version=3,
        review_action_id=rid,
        occurred_at=_NOW,
        reason_code="inaccurate",
    )
    assert d.actor is DispositionActor.INTERNAL_REVIEWER
    assert d.origin is DispositionOrigin.REVIEW_SURFACE
    assert d.review_action_id == rid
    assert d.natural_key == f"review_surface:{rid}"


def test_for_downstream_builds_account_level_record() -> None:
    account = new_entity_id()
    d = FeedbackDisposition.for_downstream(
        disposition_type=DispositionType.ACCOUNT_ACCEPTED,
        account_entity_id=account,
        client_id="acme",
        external_id="crm-1",
        occurred_at=_NOW,
        icp_key="seg",
        icp_spec_version=2,
    )
    assert d.entity_type is EntityType.ACCOUNT
    assert d.entity_id == d.account_entity_id == account
    assert d.actor is DispositionActor.CLIENT_SALES
    assert d.origin is DispositionOrigin.CRM_INGEST
    assert d.review_action_id is None
    assert d.natural_key == "crm_ingest:acme:crm-1:account_accepted"


def test_record_validators_reject_malformed_shapes() -> None:
    account = new_entity_id()
    # a claim_* type with no claim_id.
    with pytest.raises(ValueError, match="requires a claim_id"):
        FeedbackDisposition.for_review_action(
            disposition_type=DispositionType.CLAIM_APPROVED,
            entity_id=account,
            entity_type=EntityType.ACCOUNT,
            account_entity_id=account,
            claim_id=None,  # type: ignore[arg-type]
            campaign_run_id=new_campaign_run_id(),
            client_id="acme",
            icp_key="",
            icp_spec_version=1,
            review_action_id=uuid4(),
            occurred_at=_NOW,
        )
    # for_review_action refuses an account-level type.
    with pytest.raises(ValueError, match="not a review-origin"):
        FeedbackDisposition.for_review_action(
            disposition_type=DispositionType.ACCOUNT_ACCEPTED,
            entity_id=account,
            entity_type=EntityType.ACCOUNT,
            account_entity_id=account,
            claim_id=new_claim_id(),
            campaign_run_id=new_campaign_run_id(),
            client_id="acme",
            icp_key="",
            icp_spec_version=1,
            review_action_id=uuid4(),
            occurred_at=_NOW,
        )


def test_downstream_outcome_requires_an_identity_hint_and_account_type() -> None:
    with pytest.raises(ValueError, match="account_entity_id or company_name"):
        DownstreamOutcome(
            external_id="x",
            disposition_type=DispositionType.ACCOUNT_ACCEPTED,
            client_id="acme",
            occurred_at=_NOW,
        )
    with pytest.raises(ValueError, match="not an account-level outcome"):
        DownstreamOutcome(
            external_id="x",
            disposition_type=DispositionType.CLAIM_APPROVED,
            client_id="acme",
            occurred_at=_NOW,
            account_entity_id=new_entity_id(),
        )


def test_emitter_and_store_conform_to_the_seam() -> None:
    """The concrete emitter is a structural ``core.ReviewDispositionEmitter``; the store exposes the
    M13.2 contract methods. (Constructed without touching the DB — conn_factory is lazy.)"""
    emitter = ReviewDispositionEmitterImpl()
    assert isinstance(emitter, ReviewDispositionEmitter)
    store = DispositionStore()
    for method in ("record", "ingest_downstream", "labeled_dataset", "tombstone_for_contact"):
        assert callable(getattr(store, method))
