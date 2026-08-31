"""W1.5 — `reference_fidelity` always lands in the TYPED field on a reference turn.

The RED CASE these tests hold is the exact Cursor-pilot outcome
(`.context/ref-ads-pilot-cursor-report.md` §6c): the author judged fidelity 2/3
and serialized it as a prose line inside `acceptance_notes` while the typed
`VisualCritique.reference_fidelity` field stayed `null`, so the RC finalize gate
would have refused a finalize the author had actually earned, and metrics saw
nothing at all. Every `_RED_*` fixture below is that shape verbatim.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lumen_agent.critique_fidelity import (
    UNJUDGED_REASONS,
    extract_reference_fidelity,
    normalize_critique_document,
    stamp_reference_fidelity,
)
from lumen_agent.fs_backend import AgentWorkspaceBackend
from lumen_agent.models.schemas import VisualCritique
from lumen_agent.prompts import build_author_prompt

# The Cursor run's critique.json, reduced to the load-bearing shape.
_RED_PROSE_ONLY = {
    "accepted": False,
    "summary": "A dark flat field with a centered lockup and one large light headline.",
    "issues": [],
    "acceptance_notes": [
        "safe-margins: 2 — pad(96) all sides, nothing clipped",
        "on-color-pairing: 2 — $text.inverse on $surface.inverse",
        "reference_fidelity: 2 — dark flat field, centered lockup, one large light "
        "headline, generous air, single light pill, no photo; held back by the plate "
        "and the Inter fallback",
    ],
    "confidence": 0.82,
}


def _critique(**overrides):
    payload = json.loads(json.dumps(_RED_PROSE_ONLY))
    payload.update(overrides)
    return payload


# ===========================================================================
# The defect itself
# ===========================================================================


def test_red_case_the_typed_field_is_null_when_the_score_is_prose_only() -> None:
    """RED: this is what the Cursor runs produced, and what the gate could not read."""
    critique = VisualCritique.model_validate(_RED_PROSE_ONLY)
    assert critique.reference_fidelity is None
    # ...even though the judgment is plainly there, in the checklist.
    assert any("reference_fidelity: 2" in note for note in critique.acceptance_notes)


def test_the_prose_score_and_its_reasons_are_recoverable() -> None:
    assert extract_reference_fidelity(_RED_PROSE_ONLY) == (
        2,
        "dark flat field, centered lockup, one large light headline, generous air, "
        "single light pill, no photo; held back by the plate and the Inter fallback",
    )


def test_stamping_promotes_the_prose_score_into_the_typed_field() -> None:
    """GREEN: the same self-audit, after the fix."""
    stamped = VisualCritique.model_validate(stamp_reference_fidelity(_RED_PROSE_ONLY))
    assert stamped.reference_fidelity is not None
    assert stamped.reference_fidelity.score == 2
    assert "dark flat field" in stamped.reference_fidelity.reasons
    assert stamped.reference_fidelity.regressed_to_house_style is False


@pytest.mark.parametrize(
    "note, expected",
    [
        ("reference_fidelity: 2 — held back by the plate", 2),
        ("reference_fidelity 2/3", 2),
        ("reference fidelity - 3 / 3 — a member of the system", 3),
        ("Reference-Fidelity: 0 (ignored the references entirely)", 0),
        ("reference_fidelity: 1", 1),
    ],
)
def test_the_prose_forms_the_pilots_actually_wrote(note: str, expected: int) -> None:
    stamped = stamp_reference_fidelity(_critique(acceptance_notes=[note]))
    assert stamped["reference_fidelity"]["score"] == expected


def test_a_score_in_the_summary_is_found_when_the_checklist_has_none() -> None:
    stamped = stamp_reference_fidelity(
        _critique(
            acceptance_notes=["safe-margins: 2"],
            summary="Overall reference_fidelity 3 — this is the references' system.",
        )
    )
    assert stamped["reference_fidelity"]["score"] == 3


# ===========================================================================
# The invariant: a reference turn ALWAYS gets the typed field
# ===========================================================================


def test_an_unjudged_self_audit_is_still_stamped_and_still_refused() -> None:
    """No prose score anywhere: the field is present, and it is honestly 0.

    0 is the model's own default and the RC gate refuses `score <= 1`, so this
    can never launder an unjudged run into an accepted one — it only makes the
    field readable by metrics.
    """
    stamped = stamp_reference_fidelity(_critique(acceptance_notes=["safe-margins: 2"]))
    assert stamped["reference_fidelity"]["score"] == 0
    assert stamped["reference_fidelity"]["reasons"] == UNJUDGED_REASONS
    assert VisualCritique.model_validate(stamped).reference_fidelity.score == 0


def test_a_real_typed_judgment_is_never_rewritten() -> None:
    typed = _critique(
        reference_fidelity={
            "score": 3,
            "reasons": "the author's own words",
            "regressed_to_house_style": True,
        }
    )
    assert stamp_reference_fidelity(typed) is typed


def test_a_score_the_gate_cannot_read_is_coerced_to_a_real_int() -> None:
    """`2.0` and `"2"` fail the gate's `isinstance(score, int)` check."""
    for raw in (2.0, "2"):
        stamped = stamp_reference_fidelity(
            _critique(reference_fidelity={"score": raw, "reasons": "borrowed the system"})
        )
        assert stamped["reference_fidelity"]["score"] == 2
        assert stamped["reference_fidelity"]["reasons"] == "borrowed the system"


def test_a_boolean_score_is_not_mistaken_for_a_judgment() -> None:
    """`isinstance(True, int)` is true; a boolean is not a fidelity score.

    With no prose score to fall back on, the audit is unjudged — not a `1`.
    """
    stamped = stamp_reference_fidelity(
        _critique(
            acceptance_notes=["safe-margins: 2"],
            reference_fidelity={"score": True, "reasons": ""},
        )
    )
    assert stamped["reference_fidelity"]["score"] == 0
    assert stamped["reference_fidelity"]["reasons"] == UNJUDGED_REASONS


def test_an_out_of_range_prose_score_cannot_be_promoted_past_the_clamp() -> None:
    stamped = stamp_reference_fidelity(
        _critique(acceptance_notes=["reference_fidelity: 9 — perfect"])
    )
    # 9 never matches the 0-3 pattern, so this is an unjudged audit, not a 3.
    assert stamped["reference_fidelity"]["score"] == 0


def test_a_non_dict_critique_is_returned_untouched() -> None:
    for payload in ([], "nope", None, 7):
        assert stamp_reference_fidelity(payload) is payload


# ===========================================================================
# The document seam
# ===========================================================================


def test_the_bare_critique_document_is_normalized() -> None:
    rewritten = normalize_critique_document(json.dumps(_RED_PROSE_ONLY))
    assert json.loads(rewritten)["reference_fidelity"]["score"] == 2


def test_the_submit_visual_critique_envelope_is_normalized_in_place() -> None:
    envelope = {"status": "ok", "critique": _RED_PROSE_ONLY}
    rewritten = json.loads(normalize_critique_document(json.dumps(envelope)))
    assert rewritten["status"] == "ok"
    assert rewritten["critique"]["reference_fidelity"]["score"] == 2


def test_an_unparseable_self_audit_is_left_verbatim() -> None:
    """A malformed critique must still reach the orchestrator as the real failure."""
    assert normalize_critique_document("{ this is not json") is None
    assert normalize_critique_document("[1, 2, 3]") is None


def test_an_already_typed_document_is_not_rewritten() -> None:
    typed = _critique(reference_fidelity={"score": 2, "reasons": "r"})
    assert normalize_critique_document(json.dumps(typed)) is None


# ===========================================================================
# The write seam — the fast loop's only choke point
# ===========================================================================


def _backend(tmp_path: Path, *, reference_turn: bool) -> AgentWorkspaceBackend:
    root = tmp_path / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    return AgentWorkspaceBackend(root_dir=str(root), reference_turn=reference_turn)


def test_a_reference_turn_stamps_the_critique_the_author_writes(tmp_path: Path) -> None:
    """RED→GREEN at the seam the fast-loop author actually uses: write_file."""
    backend = _backend(tmp_path, reference_turn=True)
    backend.write("/rounds/round_1/critique.json", json.dumps(_RED_PROSE_ONLY))

    on_disk = json.loads((tmp_path / "workspace/rounds/round_1/critique.json").read_text())
    assert on_disk["reference_fidelity"]["score"] == 2
    assert VisualCritique.model_validate(on_disk).reference_fidelity.score == 2


def test_a_reference_turn_stamps_even_an_unjudged_critique(tmp_path: Path) -> None:
    backend = _backend(tmp_path, reference_turn=True)
    backend.write(
        "/rounds/round_1/critique.json",
        json.dumps(_critique(acceptance_notes=["safe-margins: 2"])),
    )
    on_disk = json.loads((tmp_path / "workspace/rounds/round_1/critique.json").read_text())
    assert on_disk["reference_fidelity"]["score"] == 0


def test_a_turn_without_references_writes_the_critique_verbatim(tmp_path: Path) -> None:
    backend = _backend(tmp_path, reference_turn=False)
    raw = json.dumps(_RED_PROSE_ONLY)
    backend.write("/rounds/round_1/critique.json", raw)
    assert (tmp_path / "workspace/rounds/round_1/critique.json").read_text() == raw


def test_only_critique_json_is_touched(tmp_path: Path) -> None:
    backend = _backend(tmp_path, reference_turn=True)
    raw = json.dumps(_RED_PROSE_ONLY)
    backend.write("/rounds/round_1/gaps.json", raw)
    assert (tmp_path / "workspace/rounds/round_1/gaps.json").read_text() == raw


def test_a_non_json_write_to_critique_json_is_not_swallowed(tmp_path: Path) -> None:
    backend = _backend(tmp_path, reference_turn=True)
    backend.write("/rounds/round_1/critique.json", "the model wrote prose instead")
    path = tmp_path / "workspace/rounds/round_1/critique.json"
    assert path.read_text() == "the model wrote prose instead"


# ===========================================================================
# The prompt clause — reference turns only, flag-off untouched
# ===========================================================================

WS = "/run_test/workspace"


def test_the_fast_loop_author_is_told_to_type_the_field_on_a_reference_turn() -> None:
    author = build_author_prompt(WS, has_references=True, fast_loop=True)
    assert '"reference_fidelity"' in author
    assert "REFERENCE FIDELITY" in author
    assert "It is a\ntyped field." in author
    assert "inside acceptance_notes does not\ncount." in author


def test_a_fast_loop_turn_without_references_never_mentions_fidelity() -> None:
    assert "reference_fidelity" not in build_author_prompt(WS, fast_loop=True)


def test_the_flag_off_author_prompt_is_unchanged_on_a_reference_turn() -> None:
    """Flag-off (legacy-loop) prompt bytes must not move; the reviewer owns the field there."""
    assert "reference_fidelity" not in build_author_prompt(WS, has_references=True)
