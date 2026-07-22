"""M13 integration-join wiring (``api.review_feedback_wiring``), no DB.

Two joins the integration root performs over the otherwise-independent Wave-1 packages:

* the M13.1 ↔ M13.2 disposition emitter — ``build_reviewed_phase_handler`` wires M13.2's concrete
  ``ReviewDispositionEmitterImpl`` into the review surface (not the M13.1 no-op);
* the M10.5 → M13.2 tombstone cascade — ``TombstoneCascadingDataSubjectRights`` mirrors a contact's
  erasure/objection into ``DispositionStore.tombstone_for_contact`` while passing ``access``/
  ``rectify`` straight through.

Both are exercised with fakes (the DB end-to-end of the joined surface → emitter → disposition row
lives in ``tests/review/test_review_feedback_integration_db.py``)."""

from __future__ import annotations

import asyncio

from clue_api.review_feedback_wiring import (
    TombstoneCascadingDataSubjectRights,
    build_dsar_with_disposition_cascade,
    build_reviewed_phase_handler,
)
from clue_core import EntityId, ProjectPhase, new_claim_id, new_entity_id
from clue_research.compliance import ERASE_ALL, DataSubjectRights
from clue_research.review.disposition_store import ReviewDispositionEmitterImpl


class _FakeDsar:
    """Records each call and returns a sentinel the wrapper must pass through unchanged."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def access(self, contact_entity_id: EntityId) -> object:
        self.calls.append(("access", contact_entity_id))
        return ("export", contact_entity_id)

    async def rectify(self, claim_id: object, corrected: object) -> object:
        self.calls.append(("rectify", claim_id))
        return claim_id

    async def erase(self, contact_entity_id: EntityId, scope: object = ERASE_ALL) -> object:
        self.calls.append(("erase", contact_entity_id))
        return ("erased", contact_entity_id)

    async def record_objection(self, contact_entity_id: EntityId) -> object:
        self.calls.append(("record_objection", contact_entity_id))
        return ("objected", contact_entity_id)


class _FakeTombstoner:
    def __init__(self) -> None:
        self.tombstoned: list[EntityId] = []

    async def tombstone_for_contact(self, contact_entity_id: EntityId) -> int:
        self.tombstoned.append(contact_entity_id)
        return 1


# --- M10.5 → M13.2 tombstone cascade --------------------------------------------------------------


def test_erase_cascades_disposition_tombstone() -> None:
    dsar, tomb = _FakeDsar(), _FakeTombstoner()
    wrapper = build_dsar_with_disposition_cascade(dsar=dsar, disposition_tombstoner=tomb)
    contact = new_entity_id()

    result = asyncio.run(wrapper.erase(contact))

    assert dsar.calls == [("erase", contact)]  # delegated to the M10.5 service
    assert tomb.tombstoned == [contact]  # then cascaded to the disposition store
    assert result == ("erased", contact)  # the inner result is returned unchanged


def test_record_objection_cascades_disposition_tombstone() -> None:
    dsar, tomb = _FakeDsar(), _FakeTombstoner()
    wrapper = TombstoneCascadingDataSubjectRights(inner=dsar, disposition_tombstoner=tomb)
    contact = new_entity_id()

    result = asyncio.run(wrapper.record_objection(contact))

    assert dsar.calls == [("record_objection", contact)]
    assert tomb.tombstoned == [contact]
    assert result == ("objected", contact)


def test_access_and_rectify_pass_through_without_cascade() -> None:
    """A read (access) or claim-level rectify is not a data-subject erasure — no disposition is
    tombstoned."""
    dsar, tomb = _FakeDsar(), _FakeTombstoner()
    wrapper = TombstoneCascadingDataSubjectRights(inner=dsar, disposition_tombstoner=tomb)
    contact = new_entity_id()
    claim_id = new_claim_id()

    asyncio.run(wrapper.access(contact))
    asyncio.run(wrapper.rectify(claim_id, corrected=object()))

    assert [c[0] for c in dsar.calls] == ["access", "rectify"]
    assert tomb.tombstoned == []  # neither cascades


def test_cascade_wrapper_is_a_data_subject_rights() -> None:
    """The wrapper is a drop-in ``DataSubjectRights`` (runtime-checkable structural conformance), so
    any existing DSAR call site composes the cascade by wrapping its service."""
    wrapper = TombstoneCascadingDataSubjectRights(
        inner=_FakeDsar(), disposition_tombstoner=_FakeTombstoner()
    )
    assert isinstance(wrapper, DataSubjectRights)


# --- M13.1 ↔ M13.2 disposition emitter ------------------------------------------------------------


def test_build_reviewed_phase_handler_wires_the_concrete_emitter() -> None:
    """The production binder injects M13.2's concrete ``ReviewDispositionEmitterImpl`` into the
    review surface (replacing the M13.1 no-op), so every action is mirrored into a disposition.
    Construction touches no DB."""
    handler = build_reviewed_phase_handler()

    assert handler.phase is ProjectPhase.REVIEW
    assert isinstance(handler._surface._emit, ReviewDispositionEmitterImpl)


def test_build_reviewed_phase_handler_accepts_an_explicit_emitter() -> None:
    """An explicit emitter overrides the concrete default (e.g. a fake in tests)."""
    sentinel = object()  # identity sentinel — only its placement in the surface is asserted
    handler = build_reviewed_phase_handler(disposition_emitter=sentinel)

    assert handler._surface._emit is sentinel
