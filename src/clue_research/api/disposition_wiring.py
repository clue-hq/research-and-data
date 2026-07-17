"""M13.2 — wire the disposition-capture substrate at the ``api`` composition root.

Builds the two M13.2 seam impls the integration root injects (this module is **self-contained** — it
never edits ``api/composition.py``; the actual injection happens at integration, "the single join",
exactly like ``handoff_wiring`` / ``narrative_wiring`` / ``compliance_wiring``):

* :func:`build_review_disposition_emitter` → the concrete ``core.ReviewDispositionEmitter`` that
  replaces the M13.1 **no-op**. Integration passes it to the M13.1 review surface so every
  approve/correct/reject is mirrored into a ``disposition`` (the no-op kept the signal in the
  durable
  ``review_action`` audit until M13.2 shipped — now it is normalized at the moment it occurs).
* :func:`build_disposition_store` → the ``DispositionStore`` (downstream ``ingest_downstream``, the
  ``labeled_dataset`` read M13.3 consumes, and ``tombstone_for_contact``).

**Deferred to the integration root** (the cross-package wiring ``review`` cannot do itself, the same
pattern as M9.1 AC-6 / M9.4's pre-insert stamp): the **M10.5 →
``DispositionStore.tombstone_for_contact``
cascade**. ``compliance`` cannot import ``review`` (the worker-independence contract), so the api
root
calls ``tombstone_for_contact(contact_entity_id)`` alongside ``erase`` / ``record_objection`` /
``sweep_expired`` so an erased contact's contact-keyed dispositions are tombstoned (audited, not
deleted) and leave the ``labeled_dataset`` view (Doc D §4 / spec §M13.2 AC5).
"""

from __future__ import annotations

from clue_core.review import ReviewDispositionEmitter
from clue_research.db import ConnFactory, transaction
from clue_research.obs import MetricSink
from clue_research.review.disposition_store import DispositionStore, ReviewDispositionEmitterImpl


def build_disposition_store(
    *, conn_factory: ConnFactory = transaction, sink: MetricSink | None = None
) -> DispositionStore:
    """Construct the M13.2 ``DispositionStore`` (one committed transaction per call by default)."""
    return DispositionStore(conn_factory=conn_factory, sink=sink)


def build_review_disposition_emitter(
    *, conn_factory: ConnFactory = transaction, sink: MetricSink | None = None
) -> ReviewDispositionEmitter:
    """Construct the concrete ``core.ReviewDispositionEmitter`` to inject into the M13.1 review
    surface in place of the no-op (the M13.1 ↔ M13.2 seam)."""
    return ReviewDispositionEmitterImpl(conn_factory=conn_factory, sink=sink)
