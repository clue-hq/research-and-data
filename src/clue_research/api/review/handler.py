"""The ``CampaignPhase.REVIEW`` phase handler (M13.1) — the Tier-1 human gate.

When the campaign-run state machine enters the REVIEW phase (between VERIFICATION and HANDOFF), this
handler opens a durable ``review_session`` per ready high-tier account and returns ``PAUSED`` — the
state machine then parks the run at an ``AWAITING_INPUT`` checkpoint (Option B: the human gate
reuses the M7.3 suspend/resume the state machine already reserves for M13, not a per-account
``interrupt()``). A human works the sessions through the :class:`~clue_research.core.ReviewSurface`;
the last ``finalize`` resumes the campaign (via the surface's injected resume hook), which advances
to HANDOFF — and HANDOFF only emits the accounts whose session finalized (the readiness gate).

The handler imports only ``core`` + the injected seams (the ``ReviewSurface`` contract + the
account resolver), so it is fake-testable with no DB; the concrete surface/resolver are wired at the
``api`` composition root (``composition.py``)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from clue_research.core import (
    CampaignPhase,
    PhaseContext,
    PhaseHandler,
    PhaseResult,
    PhaseStatus,
    ReviewSurface,
)
from clue_research.durable import AccountSpec

# Resolves the accounts to open a review session for — the M12-ready set (account_run DONE +
# CONTACTS_COMPLETE), *without* the review-finalized gate (which HANDOFF applies). Injected so the
# handler never imports the durable readiness reader.
ReviewAccountResolver = Callable[[PhaseContext], Awaitable[Sequence[AccountSpec]]]


class ReviewPhaseHandler:
    """The ``CampaignPhase.REVIEW`` :class:`~clue_research.core.PhaseHandler` (M13.1).

    Opens a session per ready account (idempotent — a crash-resume re-opens onto the same row) and
    returns ``PAUSED`` so the run suspends for human review. An empty ready set is a clean
    ``COMPLETED`` no-op (nothing to review → do not pause the run). Per-account isolation: one
    account's open-session fault does not sink the batch (coverage-confidence, not all-or-none)."""

    phase: CampaignPhase = CampaignPhase.REVIEW

    def __init__(
        self,
        *,
        account_resolver: ReviewAccountResolver,
        surface: ReviewSurface,
    ) -> None:
        self._account_resolver = account_resolver
        self._surface = surface

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        accounts = tuple(await self._account_resolver(ctx))
        if not accounts:
            return PhaseResult(
                status=PhaseStatus.COMPLETED,
                accounts_processed=0,
                payload={"sessions_opened": 0, "sessions_failed": 0},
            )
        opened = 0
        failed = 0
        for spec in accounts:
            try:
                await self._surface.open_session(
                    account_entity_id=spec.entity_id,
                    campaign_run_id=ctx.campaign_run_id,
                    client_id=ctx.client_id,
                    opened_by="review_phase",
                )
                opened += 1
            except Exception:  # noqa: BLE001 — isolate one account; record failed and continue
                failed += 1
        return PhaseResult(
            status=PhaseStatus.PAUSED,
            accounts_processed=opened,
            payload={
                "checkpoint": "awaiting_review",
                "sessions_opened": opened,
                "sessions_failed": failed,
            },
        )


# Static-time conformance: the handler must satisfy the core PhaseHandler protocol (mypy-checked).
_HANDLER_IS_A_PHASE_HANDLER: type[PhaseHandler] = ReviewPhaseHandler
