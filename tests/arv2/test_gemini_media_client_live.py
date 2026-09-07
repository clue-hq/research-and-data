"""The media client against the real providers — Global Constraint 3: no replay, no mocked bodies.

The subject is Global Constraint 11's answer key: Sanaz Yashar's 42:49 Boardroom Club appearance,
downloaded here through the wrapper rather than through the RSS client (which a sibling task owns),
so this file has no cross-task dependency.

One session pays for four things: a 180 s clip on the cheap OpenRouter path, the whole episode on
the native transcription endpoint, six mined quotes verbatim-checked against that transcript, and
the transcript's chunks embedded. Roughly $0.05, and the long transcription is measured in minutes,
not seconds — hence the generous per-request timeouts in the client.

``ffmpeg`` is a **test** dependency and only for the 180 s cut: production never cuts audio, it
routes a long item to :meth:`GeminiMediaClient.transcribe_long` instead.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

from clue_api.arv2.calls import CallSpec, ProviderCaller
from clue_api.arv2.gemini_media_client import (
    AudioFile,
    GeminiMediaClient,
    MediaBudget,
    MediaCeilingExceeded,
    SpeakerContext,
    Transcript,
    detect_loops,
    verify_speaker,
)
from clue_api.arv2.sinks import FileRawSink, JsonlLedger
from clue_api.arv2.transport import (
    BROWSER_USER_AGENT,
    HttpRequest,
    HttpxTransport,
    ScriptedTransport,
)
from clue_config import Secrets, Settings
from clue_config.gateway import GatewayConfig
from tests.arv2.conftest import require_secret

#: The MP3 enclosure of the Boardroom Club episode (Global Constraint 11).
SANAZ_MP3_URL = (
    "https://anchor.fm/s/f695d6d8/podcast/play/106390290/"
    "https%3A%2F%2Fd3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2025-7-9%2F"
    "405396769-44100-2-7287bb9271f44.mp3"
)
#: 42:49, the duration the feed states.
SANAZ_DURATION_S = 2569
#: The cut fed to the cheap path — comfortably under the 600 s short-item ceiling.
SHORT_SECONDS = 180

SANAZ = SpeakerContext(
    person_name="Sanaz Yashar",
    person_role="co-founder and CEO",
    organisation="Zafran Security",
)
#: The same subject as the feed presents her: the episode title names the guest.
SANAZ_NAMED = SpeakerContext(
    person_name="Sanaz Yashar",
    person_role="co-founder and CEO",
    organisation="Zafran Security",
    named_in_metadata=True,
)


@dataclass(frozen=True)
class LongRun:
    """The one long transcription of the session, plus the ledger rows it wrote."""

    transcript: Transcript
    rows: list[dict[str, object]]


def _ledger_path(root: Path) -> Path:
    return root / "ledger.jsonl"


def _ledger_line_count(root: Path) -> int:
    path = _ledger_path(root)
    if not path.exists():
        return 0
    return len([line for line in path.read_text(encoding="utf-8").splitlines() if line])


def _rows_after(root: Path, before: int) -> list[dict[str, object]]:
    lines = [line for line in _ledger_path(root).read_text(encoding="utf-8").splitlines() if line]
    return [json.loads(line) for line in lines[before:]]


def _result_row(rows: list[dict[str, object]], label: str) -> dict[str, object]:
    matches = [row for row in rows if row["label"] == label and row["phase"] == "result"]
    assert matches, f"no result ledger row labelled {label}"
    return matches[-1]


@pytest.fixture(scope="session")
def session_caller(arv2_raw_root: Path) -> ProviderCaller:
    """One caller for the whole session, so the media budget and the ledger see every call."""
    return ProviderCaller(
        transport=HttpxTransport(),
        raw_sink=FileRawSink(arv2_raw_root / "raw"),
        ledger=JsonlLedger(_ledger_path(arv2_raw_root)),
        now=lambda: datetime.now(UTC),
    )


@pytest.fixture(scope="session")
def live_client(
    session_caller: ProviderCaller, live_secrets: Secrets, arv2_raw_root: Path
) -> GeminiMediaClient:
    """The client wired from the shipped knobs — never from literals restated in the test."""
    require_secret(live_secrets, "openrouter_api_key")
    require_secret(live_secrets, "gemini_api_key")
    openrouter_key = live_secrets.openrouter_api_key
    gemini_key = live_secrets.gemini_api_key
    assert openrouter_key is not None and gemini_key is not None
    settings = Settings()
    return GeminiMediaClient(
        session_caller,
        openrouter_api_key=openrouter_key,
        openrouter_base_url=GatewayConfig().base_url,
        gemini_api_key=gemini_key,
        short_model=settings.arv2_media_short_model,
        transcribe_model=settings.arv2_media_transcribe_model,
        embedding_model=settings.arv2_embedding_model,
        media_budget=MediaBudget(settings.arv2_media_seconds_ceiling),
        short_max_seconds=settings.arv2_media_short_max_seconds,
        ledger=JsonlLedger(_ledger_path(arv2_raw_root)),
    )


@pytest.fixture(scope="session")
def sanaz_mp3(session_caller: ProviderCaller, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The episode's MP3, fetched once per session through the wrapper (a free ledger row)."""
    result = session_caller.call(
        CallSpec(
            provider="live_http",
            operation="GET",
            label="media.sanaz_mp3",
            request=HttpRequest(
                method="GET",
                url=SANAZ_MP3_URL,
                headers={"User-Agent": BROWSER_USER_AGENT},
                timeout_s=600.0,
            ),
            binary=True,
        )
    )
    assert result.response.status == 200
    path = tmp_path_factory.mktemp("arv2-media") / "sanaz_boardroom.mp3"
    path.write_bytes(result.response.body)
    assert path.stat().st_size > 1_000_000, "a truncated download would fail the wrong test later"
    return path


@pytest.fixture(scope="session")
def sanaz_short_mp3(sanaz_mp3: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The first 180 s, stream-copied. A **test** convenience: production never cuts audio."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required to cut the short-item clip")
    path = tmp_path_factory.mktemp("arv2-media-short") / "sanaz_180s.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(sanaz_mp3),
            "-t",
            str(SHORT_SECONDS),
            "-c",
            "copy",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture(scope="session")
def long_run(live_client: GeminiMediaClient, sanaz_mp3: Path, arv2_raw_root: Path) -> LongRun:
    """The session's one full transcription — minutes of wall clock, so it is paid for once."""
    before = _ledger_line_count(arv2_raw_root)
    transcript = live_client.transcribe_long(
        AudioFile(
            path=sanaz_mp3,
            duration_s=SANAZ_DURATION_S,
            display_name="boardroom-sanaz-yashar",
        ),
        context=SANAZ_NAMED,
    )
    return LongRun(transcript=transcript, rows=_rows_after(arv2_raw_root, before))


def test_a_short_clip_transcribes_with_timestamps_and_does_not_loop(
    live_client: GeminiMediaClient, sanaz_short_mp3: Path
) -> None:
    """The cheap OpenRouter path over 180 s of audio, which is where it is known to be faithful."""
    transcript = live_client.transcribe_short(
        AudioFile(path=sanaz_short_mp3, duration_s=SHORT_SECONDS), context=SANAZ_NAMED
    )

    timestamped = [line for line in transcript.lines if line.ts_s is not None]
    assert len(timestamped) >= 10, f"only {len(timestamped)} timestamped lines"
    assert transcript.has_timestamps is True
    first_ts = timestamped[0].ts_s
    assert first_ts is not None and first_ts < 30, "a transcript that starts late skipped audio"
    assert transcript.meta.get("speakers"), f"META carried no speakers: {dict(transcript.meta)}"

    report = detect_loops(transcript)
    assert report.tripped is False, f"the short path looped: {report}"

    assert transcript.cost is not None
    assert transcript.cost.cost_source == "metered"
    assert transcript.cost.media_seconds == SHORT_SECONDS
    assert (transcript.cost.provider, transcript.cost.operation) == (
        "openrouter",
        "chat/completions",
    )
    assert transcript.upload_costs == (), "the short path uploads nothing, so there are no legs"


def test_the_whole_episode_transcribes_on_the_native_endpoint_without_looping(
    long_run: LongRun,
) -> None:
    """The founder ruling's one off-OpenRouter call, and the loop the cheap model could not avoid.

    ``has_timestamps`` is false by design: the dedicated transcription model returns prose, which
    is exactly the trade the re-run bought — faithfulness instead of timestamps.
    """
    transcript = long_run.transcript
    assert len(transcript.text) >= 25_000, f"only {len(transcript.text)} chars"
    assert transcript.has_timestamps is False
    report = detect_loops(transcript)
    assert report.tripped is False, f"the transcription model looped: {report}"


def test_the_long_transcription_ledger_row_carries_its_seconds_and_its_computed_cost(
    long_run: LongRun,
) -> None:
    """The native endpoint reports tokens, never money, so the row's cost is computed — not zero.

    Media seconds are the lane's third currency; a transcription row without them cannot answer
    "how much audio did this account cost us".
    """
    row = _result_row(long_run.rows, "media.transcribe_long")

    assert row["media_seconds"] == SANAZ_DURATION_S
    assert Decimal(str(row["cost_usd"])) > 0
    assert row["outcome"] == "ok"
    assert row["provider"] == "gemini"
    assert row["extras"]["cost_source"] == "metered", (
        "the cost came from usageMetadata, not from the estimate standing in for it"
    )

    cost = long_run.transcript.cost
    assert cost is not None, "a transcript carries the cost of the call that produced it"
    assert cost.cost_source == "metered"
    assert cost.media_seconds == SANAZ_DURATION_S
    assert cost.ledger_row_id == row["row_id"]


def test_the_upload_leg_is_free_and_never_persists_the_api_key(long_run: LongRun) -> None:
    """The Files API upload costs nothing, and ``x-goog-api-key`` is masked before disk."""
    row = _result_row(long_run.rows, "media.upload")
    assert Decimal(str(row["cost_usd"])) == 0
    assert row["extras"]["cost_source"] == "free"

    # The upload legs are separate free rows, kept separate on the transcript: start, the upload
    # itself, and one row per poll. Summing them into `cost` would hide how many calls were made.
    uploads = long_run.transcript.upload_costs
    assert len(uploads) >= 3, [c.operation for c in uploads]
    assert [c.operation for c in uploads[:2]] == ["files.start", "files.upload"]
    assert all(c.cost_source == "free" for c in uploads), [c.operation for c in uploads]
    assert all(c.provider == "gemini" for c in uploads)
    assert {row["row_id"] for row in long_run.rows} >= {c.ledger_row_id for c in uploads}

    raw_ref = row["raw_ref"]
    assert isinstance(raw_ref, str)
    record = json.loads(Path(raw_ref).read_text(encoding="utf-8"))
    start = _result_row(long_run.rows, "media.upload_start")
    start_ref = start["raw_ref"]
    assert isinstance(start_ref, str)
    start_record = json.loads(Path(start_ref).read_text(encoding="utf-8"))
    assert start_record["request"]["headers"]["x-goog-api-key"] == "***", "Constraint 5"
    assert "key=" not in start_record["request"]["url"], "the key never rides the query string"
    assert record["response"]["status"] == 200


def test_the_named_guest_is_verified_and_mined_quotes_are_verbatim(
    live_client: GeminiMediaClient, long_run: LongRun
) -> None:
    """Both gates on a quote: it is really in the transcript, and it is really this person.

    The transcription model emits no ``META``, so the audio never self-identifies her here — the
    verdict rests on the feed naming the guest, and says so.
    """
    verdict = verify_speaker(long_run.transcript, SANAZ_NAMED)
    assert verdict.verified is True
    assert verdict.evidence

    quotes = live_client.mine_quotes(
        long_run.transcript.text, context=SANAZ_NAMED, speaker_verified=verdict.verified
    )

    assert quotes, "the miner returned nothing at all"
    exact = [quote for quote in quotes if quote.verdict == "EXACT"]
    assert len(exact) >= 3, [(quote.verdict, quote.text[:80]) for quote in quotes]
    assert all(quote.usable for quote in exact), "EXACT plus a verified speaker means usable"
    assert all(quote.verdict is not None for quote in quotes), "nothing is dropped, only flagged"
    # One completion bought the whole set, so the cost is on the set — charging it per quote
    # would multiply the run's real spend by however many quotes the model happened to emit.
    assert quotes.cost.cost_source == "metered"
    assert quotes.cost.cost_usd is not None and quotes.cost.cost_usd > 0
    assert (quotes.cost.provider, quotes.cost.operation) == ("openrouter", "chat/completions")
    assert not any(hasattr(quote, "cost") for quote in quotes)


def test_the_transcript_embeds_at_the_served_dimension_and_the_ledger_shows_the_cost(
    live_client: GeminiMediaClient, long_run: LongRun, arv2_raw_root: Path
) -> None:
    """Text embeddings only (law 11), one batched call, every vector the same served width."""
    before = _ledger_line_count(arv2_raw_root)

    embedded = live_client.embed_chunks(long_run.transcript)

    assert embedded, "a 37 000-character transcript must chunk into something"
    served = len(embedded[0].vector)
    assert served > 0
    assert all(len(chunk.vector) == served for chunk in embedded), "a ragged batch is a defect"
    assert all(chunk.text for chunk in embedded)
    assert embedded.dimensions == served, "the reported width is the one the provider served"

    row = _result_row(_rows_after(arv2_raw_root, before), "media.embed_chunks")
    assert Decimal(str(row["cost_usd"])) > 0
    assert embedded.cost is not None
    assert embedded.cost.cost_source == "metered"
    assert embedded.cost.ledger_row_id == row["row_id"]


def test_a_hundred_second_ceiling_refuses_the_real_episode_without_sending_it(
    sanaz_mp3: Path, arv2_raw_root: Path
) -> None:
    """Money truth over a real 41 MB file: the ceiling refuses before the upload is attempted.

    The scripted transport is the assertion — it raises on any request it receives, so a refusal
    that leaked a call could not pass here.
    """
    transport = ScriptedTransport([])
    ledger = JsonlLedger(_ledger_path(arv2_raw_root))
    before = _ledger_line_count(arv2_raw_root)
    client = GeminiMediaClient(
        ProviderCaller(
            transport=transport,
            raw_sink=FileRawSink(arv2_raw_root / "raw"),
            ledger=ledger,
            now=lambda: datetime.now(UTC),
        ),
        openrouter_api_key=SecretStr("unused"),
        openrouter_base_url=GatewayConfig().base_url,
        gemini_api_key=SecretStr("unused"),
        short_model="google/gemini-3.5-flash-lite",
        transcribe_model="gemini-3.5-transcribe",
        embedding_model="google/gemini-embedding-2",
        media_budget=MediaBudget(100),
        short_max_seconds=600,
        ledger=ledger,
    )

    with pytest.raises(MediaCeilingExceeded):
        client.transcribe_long(
            AudioFile(path=sanaz_mp3, duration_s=SANAZ_DURATION_S), context=SANAZ
        )

    assert transport.requests == []
    row = _result_row(_rows_after(arv2_raw_root, before), "media.transcribe_long")
    assert (row["outcome"], row["error_code"]) == ("halted", "media_ceiling")
