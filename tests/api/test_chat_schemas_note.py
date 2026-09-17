"""A context ref may carry the marketer's own words about that one ref.

The web editor's annotation ("1. Make this shorter", written onto a specific element) rides the
turn as a ``note`` on the ref it is about, instead of dissolving into the free-text message where
nothing binds it to its target. No DB: this pins the request shape and its bound only.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_api.chat.schemas import ContextRefRequest


def test_a_context_ref_note_is_optional() -> None:
    assert ContextRefRequest(object_type="design_node", object_id="headline").note is None


def test_a_context_ref_carries_the_annotation_verbatim() -> None:
    ref = ContextRefRequest(
        object_type="design_node",
        object_id="frg_a#:nth-child(2)",
        version=9,
        note="1. Make this shorter",
    )
    assert ref.note == "1. Make this shorter"


def test_a_note_is_bounded() -> None:
    assert (
        ContextRefRequest(
            object_type="design_node",
            object_id="headline",
            note="x" * 2_000,
        ).note
        == "x" * 2_000
    )
    with pytest.raises(ValidationError):
        ContextRefRequest(object_type="design_node", object_id="headline", note="x" * 2_001)
