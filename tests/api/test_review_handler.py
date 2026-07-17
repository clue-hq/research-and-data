"""M13.1 — ``ReviewPhaseHandler`` unit tests (fakes only, no DB).

Drives the REVIEW phase handler with a fake :class:`~clue_core.ReviewSurface` and a fake
account resolver, asserting: protocol conformance + registration, the empty-set COMPLETED no-op, the
populated-set PAUSED-after-opening-sessions path (the human gate), per-account isolation, and the
``build_review_phase_handler`` composition smoke (construction touches no DB)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from uuid import uuid4

from clue_core import (
    CampaignPhase,
    CampaignRunId,
    EntityId,
    PhaseContext,
    PhaseHandler,
    PhaseStatus,
    ReviewAction,
    ReviewActionOutcome,
    ReviewRejectReason,
    ReviewSession,
    ReviewSessionStatus,
    new_campaign_run_id,
    new_entity_id,
)
from clue_core.review import ReviewSessionId
from clue_research.api.review import ReviewPhaseHandler, build_review_phase_handler
from clue_research.api.review.handler import ReviewAccountResolver
from clue_research.durable import AccountSpec, PhaseHandlerRegistry

_CLIENT = "client-acme"


class FakeReviewSurface:
    """A fake :class:`~clue_core.ReviewSurface` — records opened sessions; the handler only
    calls ``open_session``. ``raise_for`` makes one account's open fail (isolation test)."""

    def __init__(self, *, raise_for: EntityId | None = None) -> None:
        self.opened: list[EntityId] = []
        self._raise_for = raise_for

    async def open_session(
        self,
        *,
        account_entity_id: EntityId,
        campaign_run_id: CampaignRunId,
        client_id: str,
        review_round: int = 1,
        opened_by: str | None = None,
    ) -> ReviewSession:
        if self._raise_for is not None and account_entity_id == self._raise_for:
            raise RuntimeError("boom")
        self.opened.append(account_entity_id)
        return ReviewSession(
            session_id=ReviewSessionId(uuid4()),
            account_entity_id=account_entity_id,
            campaign_run_id=campaign_run_id,
            review_round=review_round,
            status=ReviewSessionStatus.OPEN,
        )

    async def apply_action(
        self,
        *,
        session_id: ReviewSessionId,
        claim_id: object,
        action: ReviewAction,
        actor: str,
        corrected_value_json: object = None,
        reason_code: ReviewRejectReason | None = None,
        note: str | None = None,
    ) -> ReviewActionOutcome:
        raise NotImplementedError

    async def finalize(self, *, session_id: ReviewSessionId, actor: str) -> ReviewSession:
        raise NotImplementedError


def _resolver(specs: Sequence[AccountSpec]) -> ReviewAccountResolver:
    async def _r(ctx: PhaseContext) -> Sequence[AccountSpec]:
        return specs

    return _r


def _spec(entity_id: EntityId) -> AccountSpec:
    return AccountSpec(entity_id=entity_id, tier="top", tenant_id=_CLIENT)


def _ctx() -> PhaseContext:
    return PhaseContext(
        campaign_run_id=new_campaign_run_id(),
        phase=CampaignPhase.REVIEW,
        client_id=_CLIENT,
        icp_key="icp-1",
        icp_version=1,
    )


def test_handler_conforms_to_protocol_and_registers() -> None:
    handler = ReviewPhaseHandler(account_resolver=_resolver(()), surface=FakeReviewSurface())
    assert isinstance(handler, PhaseHandler)
    assert handler.phase is CampaignPhase.REVIEW
    registry = PhaseHandlerRegistry()
    assert registry.get(CampaignPhase.REVIEW) is None
    registry.register(handler)
    assert registry.get(CampaignPhase.REVIEW) is handler


def test_empty_account_set_is_a_completed_no_op() -> None:
    surface = FakeReviewSurface()
    handler = ReviewPhaseHandler(account_resolver=_resolver(()), surface=surface)

    async def _run() -> None:
        result = await handler.run(_ctx())
        assert result.status is PhaseStatus.COMPLETED  # nothing to review → do not pause the run
        assert result.accounts_processed == 0
        assert result.payload["sessions_opened"] == 0
        assert not surface.opened

    asyncio.run(_run())


def test_ready_accounts_open_sessions_and_pause() -> None:
    e1, e2 = new_entity_id(), new_entity_id()
    surface = FakeReviewSurface()
    handler = ReviewPhaseHandler(
        account_resolver=_resolver((_spec(e1), _spec(e2))), surface=surface
    )

    async def _run() -> None:
        result = await handler.run(_ctx())
        # The human gate: a session per ready account, then PAUSED (→ AWAITING_INPUT checkpoint).
        assert result.status is PhaseStatus.PAUSED
        assert result.accounts_processed == 2
        assert result.payload["sessions_opened"] == 2
        assert result.payload["checkpoint"] == "awaiting_review"
        assert set(surface.opened) == {e1, e2}

    asyncio.run(_run())


def test_one_account_open_failing_is_isolated_and_batch_survives() -> None:
    e1, e2 = new_entity_id(), new_entity_id()
    surface = FakeReviewSurface(raise_for=e1)
    handler = ReviewPhaseHandler(
        account_resolver=_resolver((_spec(e1), _spec(e2))), surface=surface
    )

    async def _run() -> None:
        result = await handler.run(_ctx())
        assert result.status is PhaseStatus.PAUSED  # still pauses for the account that opened
        assert result.accounts_processed == 1
        assert result.payload["sessions_opened"] == 1
        assert result.payload["sessions_failed"] == 1
        assert surface.opened == [e2]

    asyncio.run(_run())


def test_build_review_phase_handler_wires_the_concrete_seams() -> None:
    # Construction touches no DB (the readers/resolvers are lazy); proves the composition wiring.
    handler = build_review_phase_handler()
    assert isinstance(handler, PhaseHandler)
    assert handler.phase is CampaignPhase.REVIEW
