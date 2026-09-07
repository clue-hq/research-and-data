"""The media client's three offline mechanisms: loop detection, speaker verdicts, the ceiling.

Global Constraint 3 makes live provider calls the rule, and these are not exceptions to it — none
of them touches a provider. Two are pure functions over a stored transcript, and the third is the
refusal that happens *instead of* a call: its whole claim is that no request is sent, which can
only be shown by watching a transport that receives nothing.

The synthetic transcripts reproduce the ``z4b`` measurement (329 lines, 120 unique, the loop
starting where the unique lines run out) rather than inventing numbers, so a threshold change here
fails against the run that motivated the thresholds.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.gemini_media_client import (
    METADATA_EVIDENCE,
    AudioFile,
    GeminiMediaClient,
    MediaBudget,
    MediaCeilingExceeded,
    SpeakerContext,
    Transcript,
    TranscriptLine,
    detect_loops,
    parse_transcript_lines,
    verify_speaker,
)
from clue_api.arv2.sinks import MemoryLedger, MemoryRawSink
from clue_api.arv2.transport import ScriptedTransport

SANAZ = SpeakerContext(
    person_name="Sanaz Yashar",
    person_role="co-founder and CEO",
    organisation="Zafran Security",
)

#: Any path at all: every test here refuses before the file would be read.
NEVER_READ = Path("/nonexistent/never-read.mp3")


def _transcript(lines: list[TranscriptLine], meta: Mapping[str, str] | None = None) -> Transcript:
    return Transcript(model="test", text="", lines=tuple(lines), meta=meta or {})


def _line(index: int, text: str) -> TranscriptLine:
    return TranscriptLine(ts_s=index * 8, speaker="S1", text=text)


def _client(
    transport: ScriptedTransport, ledger: MemoryLedger, *, ceiling_s: int
) -> GeminiMediaClient:
    caller = ProviderCaller(
        transport=transport,
        raw_sink=MemoryRawSink(),
        ledger=ledger,
        now=lambda: datetime.now(UTC),
    )
    return GeminiMediaClient(
        caller,
        openrouter_api_key=SecretStr("unused"),
        openrouter_base_url="https://openrouter.ai/api/v1",
        gemini_api_key=SecretStr("unused"),
        short_model="google/gemini-3.5-flash-lite",
        transcribe_model="gemini-3.5-transcribe",
        embedding_model="google/gemini-embedding-2",
        media_budget=MediaBudget(ceiling_s),
        short_max_seconds=600,
        ledger=ledger,
        sleep=lambda _seconds: None,
    )


# ------------------------------------------------------------------------------ detect_loops --


def test_detect_loops_trips_on_the_z4b_shape_329_lines_of_which_120_are_unique() -> None:
    """The real failure: a 120-line block re-emitted under new timestamps until 329 lines exist.

    No line repeats consecutively and no 30-line window is degenerate, so this trips on the
    unique-ratio rule alone — which is the rule the z4b run actually exercised.
    """
    block = [f"line {index} of the boardroom episode" for index in range(120)]
    lines = [_line(index, block[index % 120]) for index in range(329)]

    report = detect_loops(_transcript(lines))

    assert report.total_lines == 329
    assert report.unique_lines == 120
    assert report.unique_ratio == pytest.approx(120 / 329)
    assert report.max_consecutive_repeat == 1, "the block repeats, no line repeats back to back"
    assert report.first_loop_ts_s == 120 * 8, "the first re-emitted line is where evidence ends"
    assert report.tripped is True


def test_detect_loops_does_not_trip_on_300_distinct_lines() -> None:
    lines = [_line(index, f"a distinct sentence number {index}") for index in range(300)]

    report = detect_loops(_transcript(lines))

    assert report.total_lines == 300
    assert report.unique_lines == 300
    assert report.unique_ratio == 1.0
    assert report.max_consecutive_repeat == 1
    assert report.first_loop_ts_s is None
    assert report.tripped is False


def test_detect_loops_trips_on_three_consecutive_repeats_in_a_short_clip() -> None:
    """A stuck decoder in a six-line clip: too few lines for the ratio rule, still a loop."""
    lines = [
        _line(0, "welcome to the show"),
        _line(1, "so tell me about zafran"),
        _line(2, "thanks for having me"),
        _line(3, "thanks for having me"),
        _line(4, "thanks for having me"),
        _line(5, "and that is the story"),
    ]

    report = detect_loops(_transcript(lines))

    assert report.max_consecutive_repeat == 3
    assert report.unique_ratio > 0.6, "the ratio rule alone would have missed this"
    assert report.tripped is True


def test_detect_loops_trips_on_a_local_window_a_long_faithful_opening_would_dilute() -> None:
    """400 faithful lines then a 30-line stretch cycling five phrases: ratio high, still a loop."""
    faithful = [_line(index, f"faithful line {index}") for index in range(400)]
    looped = [_line(400 + index, f"repeated phrase {index % 5}") for index in range(30)]

    report = detect_loops(_transcript(faithful + looped))

    assert report.unique_ratio > 0.6, "the whole-transcript ratio rule would have missed this"
    assert report.max_consecutive_repeat == 1, "the consecutive rule would have missed this too"
    assert report.tripped is True


def test_detect_loops_reports_an_empty_transcript_without_tripping() -> None:
    report = detect_loops(_transcript([]))

    assert (report.total_lines, report.unique_lines, report.tripped) == (0, 0, False)
    assert report.first_loop_ts_s is None


# ---------------------------------------------------------------------------- verify_speaker --


def test_verify_speaker_accepts_spoken_self_identification_naming_the_surname() -> None:
    spoken = "I'm Sanaz Yashar, I'm the co-founder and CEO of Zafran"
    transcript = _transcript([], {"guest_identity_evidence": spoken})

    verdict = verify_speaker(transcript, SANAZ)

    assert verdict.verified is True
    assert verdict.evidence == spoken, "the evidence is the audio's own words, not a summary"


def test_verify_speaker_refuses_when_the_audio_never_names_the_person() -> None:
    transcript = _transcript([], {"guest_identity_evidence": "NOT STATED"})

    verdict = verify_speaker(transcript, SANAZ)

    assert verdict.verified is False
    assert verdict.evidence == "NOT STATED"


def test_verify_speaker_falls_back_to_the_items_own_metadata_and_labels_it_as_such() -> None:
    """The usual podcast case: the feed names the guest, the audio never does."""
    transcript = _transcript([], {"guest_identity_evidence": "NOT STATED"})
    context = SpeakerContext(person_name="Sanaz Yashar", named_in_metadata=True)

    verdict = verify_speaker(transcript, context)

    assert verdict.verified is True
    assert verdict.evidence == METADATA_EVIDENCE


def test_verify_speaker_refuses_a_stated_identity_that_names_someone_else() -> None:
    """Identity evidence exists, but it is the host's — a surname check is what separates them."""
    transcript = _transcript([], {"narrator_identity_evidence": "My name is Yosi Garmasin"})

    verdict = verify_speaker(transcript, SANAZ)

    assert verdict.verified is False


# ---------------------------------------------------------------------------------- parsing --


def test_the_transcript_parser_reads_timestamps_and_speaker_labels() -> None:
    lines = parse_transcript_lines(
        "[00:12] S1 (Yosi Garmasin): welcome to the boardroom club\n"
        "[03:41] Sanaz Yashar: thanks for having me\n"
    )

    assert lines == (
        TranscriptLine(ts_s=12, speaker="S1 (Yosi Garmasin)", text="welcome to the boardroom club"),
        TranscriptLine(ts_s=221, speaker="Sanaz Yashar", text="thanks for having me"),
    )


def test_a_sentence_containing_a_colon_keeps_every_one_of_its_words() -> None:
    """A colon mid-sentence is not a speaker label, and treating it as one deletes evidence.

    The dropped half would then be missing from the string every quote is verbatim-checked
    against — a fabricated-quote verdict caused by our own parser.
    """
    (line,) = parse_transcript_lines("[04:02] So here is the thing: we bought it that quarter")

    assert line.speaker == ""
    assert line.text == "So here is the thing: we bought it that quarter"


def test_an_untimestamped_line_is_kept_so_a_loop_cannot_hide_behind_missing_timestamps() -> None:
    (line,) = parse_transcript_lines("and then we shipped it")

    assert (line.ts_s, line.speaker, line.text) == (None, "", "and then we shipped it")


# ----------------------------------------------------------------------------- the media cap --


def test_the_media_ceiling_refuses_before_the_wire_and_leaves_the_transport_untouched() -> None:
    """Money truth blocks: the audio is never sent, so it is never paid for.

    The scripted transport is empty on purpose — it raises ``AssertionError`` on any request, so
    a refusal that leaked a call would fail here as loudly as one that never refused at all.
    """
    transport = ScriptedTransport([])
    client = _client(transport, MemoryLedger(), ceiling_s=100)

    with pytest.raises(MediaCeilingExceeded) as raised:
        client.transcribe_long(AudioFile(path=NEVER_READ, duration_s=2569), context=SANAZ)

    assert transport.requests == [], "the ceiling must refuse before any wire call"
    assert (raised.value.ceiling_s, raised.value.used_s, raised.value.requested_s) == (
        100,
        0,
        2569,
    )


def test_a_refused_media_call_still_leaves_one_halted_ledger_row() -> None:
    """No provider call happened, so the wrapper wrote nothing — the client writes the trace.

    Without this row a refusal is indistinguishable from a media item nobody ever tried.
    """
    ledger = MemoryLedger()
    client = _client(ScriptedTransport([]), ledger, ceiling_s=100)

    with pytest.raises(MediaCeilingExceeded):
        client.transcribe_long(AudioFile(path=NEVER_READ, duration_s=2569), context=SANAZ)

    assert len(ledger.rows) == 1, "exactly one row: a refusal is not an estimate plus a result"
    row = ledger.rows[0]
    assert (row.phase, row.outcome, row.error_code) == ("result", "halted", "media_ceiling")
    assert row.over_ceiling is True
    assert row.cost_usd == Decimal(0)
    assert row.media_seconds == 0, "refused seconds are not consumed seconds"
    assert row.estimate_media_seconds == 2569
    assert row.extras == {"ceiling_s": 100, "used_s": 0, "requested_s": 2569}


def test_a_refused_reservation_does_not_consume_the_run_budget() -> None:
    budget = MediaBudget(300)

    budget.reserve(180)
    assert budget.used_s == 180

    with pytest.raises(MediaCeilingExceeded):
        budget.reserve(121)

    assert budget.used_s == 180, "a refused reservation must leave the budget where it was"
    budget.reserve(120)
    assert budget.used_s == 300


def test_transcribe_short_refuses_a_long_item_rather_than_silently_routing_it() -> None:
    """The short/long decision belongs to the caller, who knows the run's budget."""
    transport = ScriptedTransport([])
    client = _client(transport, MemoryLedger(), ceiling_s=9000)

    with pytest.raises(ValueError, match="transcribe_long"):
        client.transcribe_short(AudioFile(path=NEVER_READ, duration_s=2569), context=SANAZ)

    assert transport.requests == []
