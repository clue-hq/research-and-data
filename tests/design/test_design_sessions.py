"""Design-session substrate (design note 2026-09-18) — the offline half.

One design document = one design session. These pin the two pure pieces that identity rests
on: the derived session id (no table, so it must be deterministic and document-scoped) and the
drift note a continued session is told when the document moved under it. The prompt-placement
test pins the drift note's position in the turn prompt, because the block order is what keeps
the prefill prefix byte-identical across turns.
"""

from __future__ import annotations

from clue_design.leg_context import render_leg_turn_prompt
from clue_design.sessions import design_session_id, render_document_drift_note


def test_session_id_is_deterministic_and_document_scoped() -> None:
    a = design_session_id("ws_1", "doc_1")
    assert a == design_session_id("ws_1", "doc_1")
    assert a != design_session_id("ws_1", "doc_2")
    assert a != design_session_id("ws_2", "doc_1")
    assert a.startswith("dsess_") and len(a) == len("dsess_") + 32


def test_drift_note_names_versions_and_intents() -> None:
    note = render_document_drift_note(
        previous_version=4,
        current_version=7,
        envelopes=[
            {"base_revision": 4, "intent": "Move headline up", "actor_kind": "human"},
            {"base_revision": 5, "intent": None, "actor_kind": "human"},
            {"base_revision": 6, "intent": "Swap logo", "actor_kind": "human"},
        ],
    )
    assert note.startswith("DOCUMENT CHANGED SINCE YOUR LAST TURN")
    assert "version 4" in note and "version 7" in note
    assert "- Move headline up" in note and "- Swap logo" in note
    assert "(no description)" in note
    assert "Re-read the scene before editing" in note


def test_drift_note_lists_no_more_than_twenty_edits() -> None:
    envelopes = [
        {"base_revision": i, "intent": f"edit {i}", "actor_kind": "human"} for i in range(30)
    ]
    note = render_document_drift_note(previous_version=0, current_version=30, envelopes=envelopes)
    assert note.count("\n- ") == 20 and "10 more" in note


def test_drift_note_drops_edits_older_than_the_last_written_version() -> None:
    """An edit whose base predates what the agent last saved is already in the scene it holds."""
    note = render_document_drift_note(
        previous_version=4,
        current_version=6,
        envelopes=[
            {"base_revision": 2, "intent": "ancient", "actor_kind": "human"},
            {"base_revision": 5, "intent": "recent", "actor_kind": "human"},
        ],
    )
    assert "ancient" not in note
    assert "- recent" in note


def test_leg_prompt_places_the_drift_note_after_history_and_before_the_message() -> None:
    out = render_leg_turn_prompt(
        bundle={"brief": "B"},
        history=[{"role": "user", "text": "first"}],
        prompt="MSG",
        drift_note="DOCUMENT CHANGED SINCE YOUR LAST TURN\nx",
    )
    assert out.index("BRIEF>>>") < out.index("HISTORY>>>") < out.index("DOCUMENT CHANGED")
    assert out.index("DOCUMENT CHANGED") < out.index("MSG")


def test_leg_prompt_without_any_block_is_untouched() -> None:
    assert render_leg_turn_prompt(bundle=None, history=None, prompt="MSG", drift_note=None) == "MSG"


def test_leg_prompt_carries_a_drift_note_with_no_other_block() -> None:
    """A standalone-editor session still has a document that can move under it."""
    out = render_leg_turn_prompt(bundle=None, history=None, prompt="MSG", drift_note="DRIFT")
    assert out == "DRIFT\n\nMSG"
