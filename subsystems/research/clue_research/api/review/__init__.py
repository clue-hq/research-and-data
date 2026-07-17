"""api composition for the ``CampaignPhase.REVIEW`` Tier-1 human gate (M13.1).

The phase handler (``handler.py``) + its composition root (``composition.py``): the production
review surface (over the M9/M10 annotation reader + the campaign resume hook + the M13.2 no-op
emitter), the M12-ready account resolver, and the build/register factories that bind the REVIEW
handler into the M7.3 phase registry. Mirrors ``api/verification``."""

from __future__ import annotations

from clue_research.api.review.composition import (
    CampaignRunResumeHook,
    DbVerificationAnnotationReader,
    NoopReviewDispositionEmitter,
    build_review_account_resolver,
    build_review_phase_handler,
    build_review_surface,
    register_review_phase_handler,
)
from clue_research.api.review.handler import ReviewAccountResolver, ReviewPhaseHandler

__all__ = [
    "ReviewPhaseHandler",
    "ReviewAccountResolver",
    "DbVerificationAnnotationReader",
    "CampaignRunResumeHook",
    "NoopReviewDispositionEmitter",
    "build_review_account_resolver",
    "build_review_surface",
    "build_review_phase_handler",
    "register_review_phase_handler",
]
