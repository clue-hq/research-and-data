"""`clue_research.review` — Review, Feedback & Observability (M13).

M13.1 (Tier-1 review surface) lives here: the read projection over one ``account_handoff`` candidate
(:class:`~clue_research.review.projection.ReviewProjector`) and the surface that drives the human
gate (:class:`~clue_research.review.surface.ReviewSurfaceImpl` — approve/correct/reject, finalize).
The frozen contract both this impl and the ``api`` composition root bind to is
:mod:`clue_research.core.review` (``ReviewSurface`` / ``VerificationAnnotationReader`` …); the
``CampaignPhase.REVIEW`` handler + its wiring live under ``api/review`` (the composition root).

M13.2 (disposition capture), M13.3 (learning loop), and M13.4 (observability surface) also land in
this package — see ``README.md`` and ``docs/specs/M13-review-feedback-observability.md``.

Modular boundary (import-linter ``independence`` contract): ``review`` may import the shared base
(``core``/``config``/``obs``) and the M1-M4 services (``claimstore``/``identity``/``icp``/
``sources``), but **never** a sibling worker (``verification``/``compliance``/``discovery_scoring``/
``narrative``/``durable``/…). Cross-package results arrive through injected ``core`` seams wired at
the ``api`` root.
"""

from __future__ import annotations

from clue_research.review.projection import (
    FIT_FIELD,
    INTENT_FIELD,
    InMemoryVerificationAnnotationReader,
    ReviewProjector,
)
from clue_research.review.repository import (
    ReviewSessionRow,
    count_open_sessions,
    ensure_review_session,
    finalize_review_session,
    finalized_review_account_ids,
    get_review_session,
    record_review_action,
)
from clue_research.review.surface import (
    ClaimNotInSession,
    ReviewError,
    ReviewSessionNotFound,
    ReviewSurfaceImpl,
    SessionFactory,
    SessionNotOpen,
)

__all__ = [
    # read projection (M13.1)
    "ReviewProjector",
    "InMemoryVerificationAnnotationReader",
    "FIT_FIELD",
    "INTENT_FIELD",
    # the surface (M13.1)
    "ReviewSurfaceImpl",
    "SessionFactory",
    "ReviewError",
    "ReviewSessionNotFound",
    "SessionNotOpen",
    "ClaimNotInSession",
    # repository (the review tables)
    "ReviewSessionRow",
    "ensure_review_session",
    "get_review_session",
    "finalize_review_session",
    "count_open_sessions",
    "finalized_review_account_ids",
    "record_review_action",
]
