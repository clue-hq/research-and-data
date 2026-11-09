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
