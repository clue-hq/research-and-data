"""YouTube coverage check: a window Gemini stopped early is re-asked once for the missing part."""

from __future__ import annotations

from clue_api.footprint.gemini_media_client import (
    Transcript,
    TranscriptLine,
    covered_window,
    join_windows,
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


def test_full_transcript_not_rerun():
    fake = Fake(part(2350))
    parts = covered_window(fake, 0, 2400)
    assert fake.asked == [(0, 2400)] and len(parts) == 1


def test_short_transcript_rerun_once():
    fake = Fake(part(1200), part(1150, "rest"))
    parts = covered_window(fake, 2400, 4800)
    assert fake.asked == [(2400, 4800), (3600, 4800)]
    joined = join_windows(parts)
    assert joined.finish_reason == "STOP" and "rest" in joined.text
    assert max(line.ts_s for line in joined.lines) == 3600 + 1150


def test_still_short_marked_partial():
    fake = Fake(part(600), part(300))
    parts = covered_window(fake, 0, 2400)
    assert len(fake.asked) == 2
    joined = join_windows(parts)
    assert joined.finish_reason == "STOPPED_EARLY_AT_15:00"


def test_no_timestamps_is_left_as_is():
    fake = Fake(part(None))
    assert len(covered_window(fake, 0, 2400)) == 1 and len(fake.asked) == 1


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
