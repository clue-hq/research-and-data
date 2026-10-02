"""Conflict links in the isolated writer remain scoped and preserve both findings."""

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import trial_account_claims as trial  # noqa: E402


def finding(review):
    return trial.Finding(
        topic="Current role",
        claim_type="reported_statement",
        finding="The company announcement reports the role.",
        source_paths=[],
        review=review,
    )


def test_potential_conflict_requires_real_link_shape_and_preserves_other_statuses():
    with pytest.raises(ValidationError, match="requires conflicts_with"):
        trial.Review(status="potential_conflict", reason="Different current roles")
    target = uuid4()
    args = finding(
        trial.Review(
            status="potential_conflict", reason="Relevant dates unclear", conflicts_with=[target]
        )
    )
    assessment = trial.assessment_for(args)
    assert assessment.conclusion() == "qualified"
    assert str(target) in " ".join(assessment.qualifications)
    args.review.status = "insufficient_context"
    assert trial.assessment_for(args).conclusion() == "unresolved"
    args.review.status = "wrong_entity"
    assert trial.assessment_for(args).conclusion() == "invalid"


def test_conflict_links_normalize_for_replay_without_erasing_duplicates():
    a, b = uuid4(), uuid4()
    first = trial.Review(
        status="potential_conflict", reason="Conflicting dates", conflicts_with=[a, b, a]
    )
    second = trial.Review(
        status="potential_conflict", reason="Conflicting dates", conflicts_with=[b, a]
    )
    assert first.model_dump() == second.model_dump()
    old_payload = trial.Review(status="supported", reason="Original trial contract")
    assert old_payload.conflicts_with == []
    with pytest.raises(ValidationError):
        trial.Review(status="duplicate", reason="No canonical claim")
    with pytest.raises(ValidationError):
        trial.Finding(topic="Fit", claim_type="inference", finding="Good fit", review=old_payload)


def writer_with_claims(claims):
    writer = object.__new__(trial.Writer)
    writer.sources = {}
    writer.rows = AsyncMock(return_value=claims)
    writer.prefix = "trial:isolated:"
    writer.storage = object()
    writer.scope = SimpleNamespace()
    writer.grant = object()
    writer.context = uuid4()
    writer.m = {"trial_id": str(uuid4())}
    return writer


def test_foreign_conflict_reference_rejected_before_persistence(monkeypatch):
    submit = AsyncMock()
    monkeypatch.setattr(trial, "submit_proposal", submit)
    writer = writer_with_claims([])
    with pytest.raises(ValueError, match="from this isolated trial"):
        asyncio.run(
            writer.write(
                object(),
                finding(
                    trial.Review(
                        status="potential_conflict",
                        reason="Uncertain date",
                        conflicts_with=[uuid4()],
                    )
                ),
            )
        )
    submit.assert_not_awaited()


def test_linked_conflict_written_through_shared_writer_without_replacing_other_claim(
    monkeypatch,
):
    prior, new = uuid4(), uuid4()
    original = {"id": prior, "value_json": {"review": {"status": "supported"}}}
    writer = writer_with_claims([original])

    @dataclass
    class Receipt:
        claim_id: UUID
        status: str = "qualified"

    submit = AsyncMock(return_value=Receipt(new))
    monkeypatch.setattr(trial, "submit_proposal", submit)
    receipt = asyncio.run(
        writer.write(
            object(),
            finding(
                trial.Review(
                    status="potential_conflict",
                    reason="Same period, unclear update",
                    conflicts_with=[prior],
                )
            ),
        )
    )
    proposal = submit.await_args.args[4]
    assert proposal.value["review"]["conflicts_with"] == [str(prior)]
    assert proposal.claim_kind == "attributed_statement"
    assert proposal.assessment.conclusion() == "qualified"
    assert receipt["claim_id"] == new
    assert receipt["review_status"] == "potential_conflict"
    assert original["value_json"]["review"]["status"] == "supported"
    assert "superseded_by" not in proposal.value


def test_numbered_runs_have_distinct_output_and_database_without_reusing_original():
    first_path, first_db = trial.run_paths(1)
    next_path, next_db = trial.run_paths(2)
    assert first_path.name == "run-01" and next_path.name == "run-02"
    assert next_path != first_path and next_db != first_db
    assert next_db != trial.SOURCE_DB
    with pytest.raises(ValueError, match="positive"):
        trial.run_paths(0)
