"""M13.2 — the api-root disposition wiring (no DB): the builders return objects that conform to the
M13.2 / ``core`` seams, so integration can inject them without importing ``review``."""

from __future__ import annotations

from clue_research.api.disposition_wiring import (
    build_disposition_store,
    build_review_disposition_emitter,
)
from clue_research.core.review import ReviewDispositionEmitter
from clue_research.review import DispositionStore


def test_build_disposition_store_returns_a_store() -> None:
    assert isinstance(build_disposition_store(), DispositionStore)


def test_build_review_disposition_emitter_conforms_to_the_seam() -> None:
    """The emitter is a structural ``core.ReviewDispositionEmitter`` — the no-op replacement the
    M13.1 review surface is injected with at the composition root."""
    assert isinstance(build_review_disposition_emitter(), ReviewDispositionEmitter)
