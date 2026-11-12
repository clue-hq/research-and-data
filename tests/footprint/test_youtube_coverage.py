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


# --- rebuilding a paid transcript from saved answers after a crash (review C3) -------------------
# Each saved answer carries the clip it was asked for (its request's videoMetadata). Recovery used
# to pair answers with windows by position, which the coverage re-ask (two answers for one window)
# broke: answers landed 23-40 minutes off, a window was never transcribed, and it read "complete".


def timed(last_ts: int, word: str) -> Transcript:
    lines = (TranscriptLine(0, "S1", f"{word} start"), TranscriptLine(last_ts, "S1", f"{word} end"))
    return Transcript(model="m", text="\n".join(line.text for line in lines), lines=lines)


WINDOWS = [(0, 2400), (2400, 4800), (4800, 7200)]


def test_a_reasked_window_and_a_missing_window_are_placed_by_their_own_clips():
    from clue_api.footprint.gemini_media_client import rebuild_windows

    answers = [  # saved in arrival order: window 1, its re-ask, window 2; window 3 never answered
        (0, timed(1000, "w1")),
        (1000, timed(1380, "w1b")),
        (2400, timed(2390, "w2")),
    ]
    joined = rebuild_windows(WINDOWS, answers)
    assert [(line.ts_s, line.text) for line in joined.lines] == [
        (0, "w1 start"),
        (1000, "w1 end"),
        (1000, "w1b start"),
        (2380, "w1b end"),
        (2400, "w2 start"),
        (4790, "w2 end"),
    ]
    assert joined.finish_reason == "MISSING_80:00-120:00"


def test_every_window_answered_with_a_reask_is_complete():
    from clue_api.footprint.gemini_media_client import rebuild_windows

    answers = [(0, timed(1000, "a")), (1000, timed(1380, "b")), (2400, timed(2390, "c"))]
    answers.append((4800, timed(2390, "d")))
    assert rebuild_windows(WINDOWS, answers).finish_reason == "STOP"


def test_the_order_answers_were_saved_in_does_not_matter():
    from clue_api.footprint.gemini_media_client import rebuild_windows

    answers = [(2400, timed(2390, "c")), (0, timed(1000, "a")), (1000, timed(1380, "b"))]
    joined = rebuild_windows(WINDOWS, answers)
    assert [line.ts_s for line in joined.lines] == [0, 1000, 1000, 2380, 2400, 4790]


def test_a_window_cut_short_with_no_reask_saved_is_partial_from_where_it_stopped():
    from clue_api.footprint.gemini_media_client import rebuild_windows

    joined = rebuild_windows([(0, 2400)], [(0, timed(1000, "a"))])
    assert joined.finish_reason == "MISSING_16:40-40:00"


def test_two_saved_answers_for_the_same_clip_count_once():
    from clue_api.footprint.gemini_media_client import rebuild_windows

    joined = rebuild_windows([(0, 2400)], [(0, timed(2390, "a")), (0, timed(2390, "a"))])
    assert len(joined.lines) == 2 and joined.finish_reason == "STOP"


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
