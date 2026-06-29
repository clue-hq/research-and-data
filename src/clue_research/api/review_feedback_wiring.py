"""M13 integration join — wire the Wave-1 cross-issue seams at the ``api`` composition root.

``api`` is the import-linter-exempt seam (nothing imports ``api`` — Rule 5), so it is the one place
the otherwise-independent ``review`` (M13.1/M13.2/M13.4) and ``compliance`` (M10.5) packages meet.
The three Wave-1 milestones each shipped a frozen ``core`` seam + a self-contained
``api/*_wiring`` builder and deferred the concrete cross-package binding to integration (the same
pattern as M9.1 AC-6 / M9.4's pre-insert stamp / M12.3's readiness reader). This module performs the
two joins that need new code:

* **M13.1 ↔ M13.2 (the disposition emitter).** :func:`register_reviewed_phase_handler` registers the
  ``CampaignPhase.REVIEW`` handler whose surface mirrors every approve/correct/reject into a
  ``disposition`` — replacing the M13.1 no-op with M13.2's concrete
  ``ReviewDispositionEmitterImpl`` (``build_review_disposition_emitter``). Until then,
  review actions are still durably recorded as ``review_action`` rows, so no disposition is lost.
* **M10.5 ↔ M13.2 (the tombstone cascade).** :class:`TombstoneCascadingDataSubjectRights` wraps the
  M10.5 ``DataSubjectRights`` service so an ``erase`` / ``record_objection`` on a contact also
  tombstones that contact's contact-keyed dispositions (``DispositionStore.tombstone_for_contact``)
  — ``compliance`` may not import ``review`` (the worker-independence contract), so the cascade is
  composed here. Audited (a stamped ``tombstoned_at``, not a hard delete) and idempotent; the
  tombstoned rows leave the ``labeled_dataset`` view (Doc D §4 / spec §M13.2 AC5).

The handoff gate needs no new code here: ``build_handoff_readiness_reader`` /
``build_handoff_phase_handler`` already carry ``require_finalized_review`` (M13.1, default OFF). The
production HANDOFF registration must opt in (``require_finalized_review=True``) so an account is
handoff-ready only once its Tier-1 review session is finalized; the gate's filtering is proven in
``tests/api/test_handoff_wiring.py``. There is no committed process-wide assembly yet, so flipping
the flag is the deploying caller's one-line opt-in, not a default.

**Scoped decision (documented divergence).** The cascade fires at the per-subject DSAR events
(``erase`` / ``record_objection``) where the contact is exactly identified — this is what spec
§M13.2 AC5 is about. Two gaps are known and tracked as follow-ups:

* The pre-handoff bulk sweeps (``RetentionSweepHandoffHandler``'s ``sweep_expired`` /
  ``sweep_objections``) are **not** re-cascaded: ``SweepResult`` exposes no per-contact breakdown,
  and a retention-TTL age-out is not a data-subject erasure (over-cascading would silently drop
  labeled training data). So a disposition ingested *after* an ``erase``/``record_objection`` —
  e.g. a late ``ingest_downstream`` outcome, before any re-sweep — is not re-tombstoned.
* ``DispositionStore.tombstone_for_contact`` (M13.2) tombstones a contact's dispositions across
  **all** controllers (no ``client_id`` predicate), while ``DataSubjectRights`` is per-controller —
  erasing a contact shared between two clients tombstones both clients' dispositions. Scoping the
  tombstone by ``client_id`` is the fix (an M13.2-owned change).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.api.disposition_wiring import build_review_disposition_emitter
from clue_research.api.review import (
    ReviewPhaseHandler,
    build_review_phase_handler,
    register_review_phase_handler,
)
from clue_research.compliance import (
    ERASE_ALL,
    DataSubjectExport,
    DataSubjectRights,
    ErasureResult,
    ErasureScope,
    ObjectionResult,
)
from clue_research.core import Claim, ClaimId, EntityId
from clue_research.core.review import ReviewDispositionEmitter
from clue_research.db import connection, transaction
from clue_research.durable.campaign import CampaignRun
from clue_research.obs import MetricSink
from clue_research.review import DispositionStore, SessionFactory

_ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]


# --- M13.1 ↔ M13.2: register the REVIEW handler with the concrete disposition emitter ------------


def _production_review_emitter(
    *,
    disposition_emitter: ReviewDispositionEmitter | None,
    emitter_conn_factory: _ConnFactory,
    emitter_sink: MetricSink | None,
) -> ReviewDispositionEmitter:
    """The disposition emitter the production REVIEW surface uses — M13.2's concrete
    ``ReviewDispositionEmitterImpl`` by default (override with an explicit emitter, e.g. a fake). It
    records on its own committed transaction (``emitter_conn_factory``) so it is durable
    independent of the review action's transaction."""
    return disposition_emitter or build_review_disposition_emitter(
        conn_factory=emitter_conn_factory, sink=emitter_sink
    )


def build_reviewed_phase_handler(
    *,
    conn_factory: _ConnFactory = connection,
    session_factory: SessionFactory = transaction,
    campaign_run: CampaignRun | None = None,
    disposition_emitter: ReviewDispositionEmitter | None = None,
    emitter_conn_factory: _ConnFactory = transaction,
    emitter_sink: MetricSink | None = None,
) -> ReviewPhaseHandler:
    """Build the ``CampaignPhase.REVIEW`` handler whose surface emits **real** dispositions (no
    registration) — the M13.1 ↔ M13.2 join. Defaults the surface's disposition emitter to M13.2's
    concrete ``ReviewDispositionEmitterImpl`` so every approve/correct/reject is mirrored into a
    ``disposition`` at the moment it occurs. Mirrors ``build_review_phase_handler``."""
    return build_review_phase_handler(
        conn_factory=conn_factory,
        session_factory=session_factory,
        campaign_run=campaign_run,
        disposition_emitter=_production_review_emitter(
            disposition_emitter=disposition_emitter,
            emitter_conn_factory=emitter_conn_factory,
            emitter_sink=emitter_sink,
        ),
    )


def register_reviewed_phase_handler(
    *,
    conn_factory: _ConnFactory = connection,
    session_factory: SessionFactory = transaction,
    campaign_run: CampaignRun | None = None,
    disposition_emitter: ReviewDispositionEmitter | None = None,
    emitter_conn_factory: _ConnFactory = transaction,
    emitter_sink: MetricSink | None = None,
) -> ReviewPhaseHandler:
    """Build + register the production ``CampaignPhase.REVIEW`` handler (emitting real dispositions)
    into the M7.3 process-default ``PhaseHandlerRegistry`` (the M13.1 ↔ M13.2 join). Mirrors
    ``register_review_phase_handler``; use this in the full M13 flow."""
    return register_review_phase_handler(
        conn_factory=conn_factory,
        session_factory=session_factory,
        campaign_run=campaign_run,
        disposition_emitter=_production_review_emitter(
            disposition_emitter=disposition_emitter,
            emitter_conn_factory=emitter_conn_factory,
            emitter_sink=emitter_sink,
        ),
    )


# --- M10.5 ↔ M13.2: cascade contact erasure/objection into disposition tombstoning ---------------


@runtime_checkable
class ContactDispositionTombstoner(Protocol):
    """The narrow slice of M13.2's ``DispositionStore`` the cascade drives.

    ``tombstone_for_contact`` stamps ``tombstoned_at`` on a contact's contact-keyed dispositions
    (audited, not deleted) so they leave the ``labeled_dataset`` view. Typed structurally so the
    wrapper is fake-testable; the real ``DispositionStore`` satisfies it (asserted below)."""

    async def tombstone_for_contact(self, contact_entity_id: EntityId) -> int: ...


class TombstoneCascadingDataSubjectRights:
    """Wraps a M10.5 :class:`~clue_research.compliance.DataSubjectRights` so a contact's
    erasure/objection also tombstones that contact's dispositions (the M10.5 → M13.2 cascade).

    ``access`` / ``rectify`` pass straight through (read / claim-level rectify do not erase a data
    subject). ``erase`` / ``record_objection`` delegate to the inner service first (the legal
    obligation on the claim store), then — after that commits — call
    :meth:`ContactDispositionTombstoner.tombstone_for_contact` for that contact. The two legs are
    separate transactions (not atomic); the order (erase → tombstone) fails safe — a crash between
    them never loses the erasure, and the next run's idempotent re-tombstone (``tombstoned_at`` only
    advances from NULL) heals the disposition. So a retry or double-erase is safe.

    Drop-in for ``DataSubjectRights``: an existing DSAR call site composes the cascade by wrapping
    its service, exactly as ``RetentionSweepHandoffHandler`` wraps the inner handoff handler."""

    def __init__(
        self,
        *,
        inner: DataSubjectRights,
        disposition_tombstoner: ContactDispositionTombstoner,
    ) -> None:
        self._inner = inner
        self._tombstoner = disposition_tombstoner

    async def access(self, contact_entity_id: EntityId) -> DataSubjectExport:
        return await self._inner.access(contact_entity_id)

    async def rectify(self, claim_id: ClaimId, corrected: Claim) -> ClaimId:
        return await self._inner.rectify(claim_id, corrected)

    async def erase(
        self, contact_entity_id: EntityId, scope: ErasureScope = ERASE_ALL
    ) -> ErasureResult:
        result = await self._inner.erase(contact_entity_id, scope)
        await self._tombstoner.tombstone_for_contact(contact_entity_id)
        return result

    async def record_objection(self, contact_entity_id: EntityId) -> ObjectionResult:
        result = await self._inner.record_objection(contact_entity_id)
        await self._tombstoner.tombstone_for_contact(contact_entity_id)
        return result


def build_dsar_with_disposition_cascade(
    *,
    dsar: DataSubjectRights,
    disposition_tombstoner: ContactDispositionTombstoner,
) -> TombstoneCascadingDataSubjectRights:
    """Wrap the M10.5 ``DataSubjectRights`` service with the M13.2 disposition tombstone cascade.

    Inject a concrete ``DispositionStore`` (``build_disposition_store``) as the tombstoner; the
    returned object is a drop-in ``DataSubjectRights`` for any DSAR call site."""
    return TombstoneCascadingDataSubjectRights(
        inner=dsar, disposition_tombstoner=disposition_tombstoner
    )


# Static-time conformance: the cascade wrapper is itself a ``DataSubjectRights`` (drop-in), and the
# real M13.2 ``DispositionStore`` satisfies the narrow ``ContactDispositionTombstoner`` seam.
_CASCADE_IS_A_DSR: type[DataSubjectRights] = TombstoneCascadingDataSubjectRights
_STORE_IS_A_TOMBSTONER: type[ContactDispositionTombstoner] = DispositionStore
