"""`clue_research.review` — Review, Feedback & Observability (M13).

M13.1 (Tier-1 review surface) lives here: the read projection over one ``account_handoff`` candidate
(:class:`~clue_research.review.projection.ReviewProjector`) and the surface that drives the human
gate (:class:`~clue_research.review.surface.ReviewSurfaceImpl` — approve/correct/reject, finalize).
The frozen contract both this impl and the ``api`` composition root bind to is
:mod:`clue_research.core.review` (``ReviewSurface`` / ``VerificationAnnotationReader`` …); the
``CampaignPhase.REVIEW`` handler + its wiring live under ``api/review`` (the composition root).

M13.2 (disposition capture) lives here too: :class:`FeedbackDisposition` (named to avoid colliding
with ``clue_research.identity.Disposition``) + its taxonomies, the :class:`DispositionStore` capture
substrate and the concrete :class:`ReviewDispositionEmitterImpl` (the M13.1 ↔ M13.2 seam), and the
:class:`LabeledRow` read view M13.3 consumes via :func:`read_labeled_dataset`.

M13.4 (observability surface) lives here too: the read-only :class:`ObservabilitySurface` (phase
progress, cost burn-down, pre-run estimate, per-source yield, verification health, coverage
confidence), its panel projections, the injected reader Protocols whose concrete impls are wired at
the ``api`` composition root, and their in-memory fakes. M13.3 (learning loop) also lands here — see
``README.md`` and ``docs/specs/M13-review-feedback-observability.md``.

Modular boundary (import-linter ``independence`` contract): ``review`` may import the shared base
(``core``/``config``/``obs``) and the M1-M4 services (``claimstore``/``identity``/``icp``/
``sources``), but **never** a sibling worker (``verification``/``compliance``/``discovery_scoring``/
``narrative``/``durable``/…). Cross-package results arrive through injected ``core`` seams wired at
the ``api`` root.
"""

from __future__ import annotations

from clue_research.review.disposition import (
    ACCOUNT_DISPOSITION_TYPES,
    CLAIM_DISPOSITION_TYPES,
    REVIEW_ACTION_TO_DISPOSITION,
    DispositionActor,
    DispositionId,
    DispositionOrigin,
    DispositionType,
    DownstreamOutcome,
    FeedbackDisposition,
    IngestRejection,
    IngestReport,
    new_disposition_id,
)
from clue_research.review.disposition_store import (
    DispositionCaptureError,
    DispositionStore,
    ReviewDispositionEmitterImpl,
    capture_downstream,
    capture_review_action,
    ingest_downstream,
    record_disposition,
    snapshot_claim_provenance,
    tombstone_contact_dispositions,
)
from clue_research.review.labeled_dataset import LabeledRow, read_labeled_dataset
from clue_research.review.observability import (
    COST_STATUS_GRACEFUL_STOP,
    COST_STATUS_NEAR_CAP,
    COST_STATUS_OK,
    CampaignProgress,
    CampaignStateReader,
    CostBurnDown,
    CostBurnDownReader,
    CoverageReportReader,
    InMemoryCampaignStateReader,
    InMemoryCostBurnDownReader,
    InMemoryCoverageReportReader,
    InMemoryPreRunEstimator,
    InMemoryVerificationHealthReader,
    ObservabilitySurface,
    PhaseProgress,
    PreRunEstimate,
    PreRunEstimator,
    RunPhaseState,
    VerificationHealth,
    VerificationHealthCounts,
    VerificationHealthReader,
    observability_is_client_facing,
)
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
    # repository (the review tables) (M13.1)
    "ReviewSessionRow",
    "ensure_review_session",
    "get_review_session",
    "finalize_review_session",
    "count_open_sessions",
    "finalized_review_account_ids",
    "record_review_action",
    # disposition records + taxonomies (M13.2)
    "FeedbackDisposition",
    "DispositionType",
    "DispositionActor",
    "DispositionOrigin",
    "DispositionId",
    "new_disposition_id",
    "CLAIM_DISPOSITION_TYPES",
    "ACCOUNT_DISPOSITION_TYPES",
    "REVIEW_ACTION_TO_DISPOSITION",
    # downstream ingest contract (M13.2)
    "DownstreamOutcome",
    "IngestReport",
    "IngestRejection",
    # store + emitter + conn-in primitives (M13.2)
    "DispositionStore",
    "ReviewDispositionEmitterImpl",
    "DispositionCaptureError",
    "record_disposition",
    "snapshot_claim_provenance",
    "capture_review_action",
    "capture_downstream",
    "ingest_downstream",
    "tombstone_contact_dispositions",
    # labeled-dataset read view (M13.2)
    "LabeledRow",
    "read_labeled_dataset",
    # observability surface (M13.4)
    "ObservabilitySurface",
    "observability_is_client_facing",
    # panel projections (M13.4)
    "CampaignProgress",
    "PhaseProgress",
    "CostBurnDown",
    "PreRunEstimate",
    "VerificationHealth",
    "VerificationHealthCounts",
    "RunPhaseState",
    # cost-status tokens (M13.4)
    "COST_STATUS_OK",
    "COST_STATUS_NEAR_CAP",
    "COST_STATUS_GRACEFUL_STOP",
    # injected reader protocols — concrete impls at the api root (M13.4)
    "CampaignStateReader",
    "CostBurnDownReader",
    "PreRunEstimator",
    "VerificationHealthReader",
    "CoverageReportReader",
    # in-memory fakes (M13.4)
    "InMemoryCampaignStateReader",
    "InMemoryCostBurnDownReader",
    "InMemoryPreRunEstimator",
    "InMemoryVerificationHealthReader",
    "InMemoryCoverageReportReader",
]
