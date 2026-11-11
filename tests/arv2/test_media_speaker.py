"""The transcript lines the speaker check (Jev) reads.

In r44a half the lines Jev got for a Gemini transcript were noise: the text between two parsed lines
(the next line's ``[00:27] S2 (Ann Barron-DiCamillo):`` prefix) was saved as its own unlabelled
segment and sent as ``[00:00] Unlabelled: [00:27] S2 (Ann Barron-DiCamillo):``. The earlier Jev
test, 15 of 15 right, read clean ``[mm:ss] Speaker N: text`` lines.
"""

from __future__ import annotations

from clue_api.arv2.media_speaker import diarised_lines
from clue_api.footprint.media_types import Segment


def saved(*parts: tuple[str, str | None, float | None]) -> dict[str, object]:
    text, segments, cursor = "", [], 0
    for words, speaker, time_s in parts:
        text += words
        segments.append(
            Segment(
                start=cursor,
                end=cursor + len(words),
                speaker=speaker,
                time_s=time_s,
                timing="unavailable" if time_s is None else "model_estimated",
            )
        )
        cursor += len(words)
    return {"text": text, "segments": segments}


def test_the_label_prefixes_between_lines_are_not_sent_as_lines():
    gemini = saved(
        ("[00:07] S1 (Host): ", None, None),
        ("Please welcome Ann.", "S1 (Host)", 7),
        ("\n[00:27] S2 (Ann Barron-DiCamillo): ", None, None),
        ("Thank you for having me.", "S2 (Ann Barron-DiCamillo)", 27),
    )
    assert diarised_lines(gemini) == [
        "[00:07] S1 (Host): Please welcome Ann.",
        "[00:27] S2 (Ann Barron-DiCamillo): Thank you for having me.",
    ]


def test_words_nobody_was_given_still_reach_the_check():
    untagged = saved(("Thanks everyone for joining.", None, None), ("Hi.", "Speaker 0", 3))
    assert diarised_lines(untagged) == [
        "[00:00] Unlabelled: Thanks everyone for joining.",
        "[00:03] Speaker 0: Hi.",
    ]


# --- the identity note the agent writes for the speaker check (founder-approved 2026-11-12) -------


def test_read_media_takes_an_identity_note_with_the_approved_description():
    import pytest
    from pydantic import ValidationError

    from clue_api.arv2.media_tools import ReadMediaArgs

    schema = ReadMediaArgs.model_json_schema()["properties"]["identity_note"]
    assert schema["description"].startswith(
        "What identifies the person we research, for the speaker check."
    )
    assert "Write only what your research found; never guess." in schema["description"]
    assert "also written Jon Doe" in schema["description"]
    args = ReadMediaArgs(url="https://example.com/a.mp3", purpose="p", identity_note="CISO, Acme")
    assert args.identity_note == "CISO, Acme"
    with pytest.raises(ValidationError):
        ReadMediaArgs(url="https://example.com/a.mp3", purpose="p", identity_note="x" * 1501)
