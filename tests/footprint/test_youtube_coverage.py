"""Long YouTube videos: one Gemini answer per window, accepted as it is.

Founder ruling 2026-11-12: whatever Gemini returns for a window on the first attempt is kept; it is
never re-asked for a part it seems to have missed (the coverage re-ask, built on Gemini's own
timestamps, transcribed the last 8 minutes of r44a's FINOS panel twice).
"""

from __future__ import annotations

from clue_api.footprint.gemini_media_client import (
    Transcript,
    TranscriptLine,
    join_windows,
    transcribe_windows,
)


def part(last_ts: int | None, text: str = "words") -> Transcript:
    first_ts = 0 if last_ts is not None else None
    lines = (TranscriptLine(ts_s=first_ts, speaker="Speaker 0", text="start"),) + (
        (TranscriptLine(ts_s=last_ts, speaker="Speaker 0", text=text),)
        if last_ts is not None
        else ()
    )
    return Transcript(
        model="m", text="\n".join(line.text for line in lines), lines=lines, finish_reason="STOP"
    )


class Fake:
    def __init__(self, *answers: Transcript) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[int, int]] = []

    def __call__(self, start: int, end: int) -> Transcript:
        self.asked.append((start, end))
        return self.answers.pop(0)


def test_every_window_is_asked_once_and_a_short_answer_is_kept():
    fake = Fake(part(600, "first"), part(2350, "second"))
    joined = transcribe_windows(fake, [(0, 2400), (2400, 4800)])
    assert fake.asked == [(0, 2400), (2400, 4800)]
    assert [line.text for line in joined.lines] == ["start", "first", "start", "second"]
    assert joined.finish_reason == "STOP"


def said(*lines: tuple[int, str, str]) -> Transcript:
    parsed = tuple(TranscriptLine(ts_s=ts, speaker=who, text=words) for ts, who, words in lines)
    return Transcript(model="m", text="\n".join(t for _, _, t in lines), lines=parsed)


def test_a_named_speaker_is_one_label_across_parts():
    """Founder ruling 2026-11-11: attribute by the name Gemini wrote on each line. Each part is a
    separate Gemini answer that numbers its speakers afresh (r44a: Ann was S5, then S2)."""
    first = said((10, "S2", "Panelist one."), (20, "S5 (Ann Barron-DiCamillo)", "Ann early."))
    second = said((5, "S2 (Ann Barron-DiCamillo)", "Ann late."), (9, "S5", "Someone else."))
    joined = join_windows([(0, first), (1500, second)])
    assert [line.speaker for line in joined.lines] == [
        "S2 (part 1 of 2)",
        "Ann Barron-DiCamillo",
        "Ann Barron-DiCamillo",
        "S5 (part 2 of 2)",
    ]


def test_an_unidentified_speaker_is_never_merged_across_parts():
    first = said((10, "S3 (unknown)", "One."))
    second = said((10, "S3 (Unidentified speaker)", "Two."))
    joined = join_windows([(0, first), (1500, second)])
    assert [line.speaker for line in joined.lines] == ["S3 (part 1 of 2)", "S3 (part 2 of 2)"]


def test_one_part_keeps_its_numbers_and_names_its_speakers():
    joined = join_windows([(0, said((1, "S1", "Hi."), (2, "S2 (Pete Carrara)", "Hello.")))])
    assert [line.speaker for line in joined.lines] == ["S1", "Pete Carrara"]


def test_labels_in_other_forms_are_left_alone():
    joined = join_windows(
        [(0, said((1, "Host", "Hi."), (2, "", "Untagged."))), (60, said((1, "Ann", "Yes.")))]
    )
    assert [line.speaker for line in joined.lines] == ["Host", "", "Ann"]


def test_the_text_the_agent_reads_carries_the_same_labels():
    first = Transcript(
        model="m",
        text="[00:10] S2: Panelist one.\n[00:20] S5 (Ann Barron-DiCamillo): Ann early.",
        lines=(
            TranscriptLine(10, "S2", "Panelist one."),
            TranscriptLine(20, "S5 (Ann Barron-DiCamillo)", "Ann early."),
        ),
    )
    second = Transcript(
        model="m",
        text="[00:05] S2 (Ann Barron-DiCamillo): Ann late.\nA line with: a colon and no label.",
        lines=(
            TranscriptLine(5, "S2 (Ann Barron-DiCamillo)", "Ann late."),
            TranscriptLine(None, "", "A line with: a colon and no label."),
        ),
    )
    joined = join_windows([(0, first), (1500, second)])
    assert joined.text == (
        "[00:10] S2 (part 1 of 2): Panelist one.\n"
        "[00:20] Ann Barron-DiCamillo: Ann early.\n"
        "[00:05] Ann Barron-DiCamillo: Ann late.\n"
        "A line with: a colon and no label."
    )


# --- rebuilding a paid transcript from saved answers after a crash (review C3) -------------------
# Each saved answer carries the clip it was asked for (its request's videoMetadata). Recovery used
# to pair answers with windows by position, which slipped as soon as one window had two answers.


def timed(last_ts: int, word: str) -> Transcript:
    lines = (TranscriptLine(0, "S1", f"{word} start"), TranscriptLine(last_ts, "S1", f"{word} end"))
    return Transcript(model="m", text="\n".join(line.text for line in lines), lines=lines)


WINDOWS = [(0, 2400), (2400, 4800), (4800, 7200)]


def test_answers_are_placed_by_their_own_clips_and_an_unanswered_window_is_named():
    from clue_api.footprint.gemini_media_client import rebuild_windows

    answers = [(2400, timed(2390, "w2")), (0, timed(1000, "w1"))]  # window 3 never answered
    joined = rebuild_windows(WINDOWS, answers)
    assert [(line.ts_s, line.text) for line in joined.lines] == [
        (0, "w1 start"),
        (1000, "w1 end"),
        (2400, "w2 start"),
        (4790, "w2 end"),
    ]
    assert joined.finish_reason == "MISSING_80:00-120:00"


def test_a_short_answer_is_accepted_as_it_is():
    from clue_api.footprint.gemini_media_client import rebuild_windows

    joined = rebuild_windows([(0, 2400)], [(0, timed(1000, "a"))])
    assert joined.finish_reason == "STOP" and len(joined.lines) == 2


def test_the_first_saved_answer_for_a_window_is_kept():
    from clue_api.footprint.gemini_media_client import rebuild_windows

    joined = rebuild_windows([(0, 2400)], [(0, timed(900, "first")), (0, timed(2390, "later"))])
    assert [line.text for line in joined.lines] == ["first start", "first end"]


def test_the_clip_is_read_from_the_saved_request():
    from clue_api.footprint.gemini_media_client import clip_of_request

    body = (
        '{"contents":[{"parts":[{"fileData":{"fileUri":"https://www.youtube.com/watch?v=x",'
        '"mimeType":"video/mp4"},"videoMetadata":{"endOffset":"2293s","fps":0.2,'
        '"startOffset":"1000s"}},{"text":"prompt"}]}]}'
    )
    assert clip_of_request(body) == (1000, 2293)
    assert clip_of_request('{"contents":[{"parts":[{"text":"no clip"}]}]}') is None
    assert clip_of_request("not json") is None
