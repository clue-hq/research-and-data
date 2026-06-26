"""`clue_research.review` — Review, Feedback & Observability (M13).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live in this package's
``README.md``. Implemented by M13.

M13.2 (disposition capture) lives here: :class:`FeedbackDisposition` (named so to avoid colliding
with ``clue_research.identity.Disposition``) + its taxonomies, the :class:`DispositionStore` capture
substrate and the concrete :class:`ReviewDispositionEmitterImpl` (the M13.1 ↔ M13.2 seam), and the
:class:`LabeledRow` read view M13.3 consumes via :func:`read_labeled_dataset`.
"""

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

__all__ = [
    # records + taxonomies
    "FeedbackDisposition",
    "DispositionType",
    "DispositionActor",
    "DispositionOrigin",
    "DispositionId",
    "new_disposition_id",
    "CLAIM_DISPOSITION_TYPES",
    "ACCOUNT_DISPOSITION_TYPES",
    "REVIEW_ACTION_TO_DISPOSITION",
    # downstream ingest contract
    "DownstreamOutcome",
    "IngestReport",
    "IngestRejection",
    # store + emitter + conn-in primitives
    "DispositionStore",
    "ReviewDispositionEmitterImpl",
    "DispositionCaptureError",
    "record_disposition",
    "snapshot_claim_provenance",
    "capture_review_action",
    "capture_downstream",
    "ingest_downstream",
    "tombstone_contact_dispositions",
    # labeled-dataset read view
    "LabeledRow",
    "read_labeled_dataset",
]
