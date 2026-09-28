"""Offline recordings exercise the actual resolver/client/offset logic without provider spend."""

import json
from datetime import UTC, datetime

import pytest

from clue_api.arv2.account_research_catalog import (
    has_capability,
    load_account_resources,
    load_person_resources,
)
from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.gemini_media_client import SpeakerContext, Transcript, TranscriptLine
from clue_api.arv2.media_acquisition import assess_transcript
from clue_api.arv2.media_resolution import (
    feed_candidates,
    match_episode,
    public_url,
    resolve,
    youtube_url,
)
from clue_api.arv2.media_retrieval import chunks, vector_string
from clue_api.arv2.media_types import Segment
from clue_api.arv2.sinks import MemoryLedger, MemoryRawSink
from clue_api.arv2.transport import HttpResponse, ScriptedTransport
from tests.arv2.test_gemini_media_client import _client


def response(body, mime="text/html"):
    return HttpResponse(200, {"content-type": mime}, body.encode())


def caller(wire):
    return ProviderCaller(
        transport=wire,
        raw_sink=MemoryRawSink(),
        ledger=MemoryLedger(),
        now=lambda: datetime.now(UTC),
        sleep=lambda _: None,
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://youtu.be/abcdefghijk?t=1",
        "https://youtube.com/watch?v=abcdefghijk",
        "https://www.youtube.com/embed/abcdefghijk",
        "https://youtube.com/shorts/abcdefghijk",
    ],
)
def test_video_identity(url):
    assert youtube_url(url) == (
        "https://www.youtube.com/watch?v=abcdefghijk",
        "youtube:abcdefghijk",
    )
    assert youtube_url("https://example.com/watch?v=abcdefghijk") is None


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@example.com/",
        "http://127.0.0.1/",
        "http://localhost/",
        "file:///tmp/file",
        "https://example.com:8000/x",
    ],
)
def test_public_url_rejects_unsafe_shapes(url):
    with pytest.raises(ValueError):
        public_url(url)


def test_landing_page_resolves_exact_episode_from_feed_description():
    page = '<link rel="alternate" type="application/rss+xml" href="/rss">'
    feed = """<rss><channel><title>Research show</title><item><guid>episode-42</guid>
    <title>Security teams</title>
    <description>Guest is Sanaz Yashar</description><link>https://example.com/ep</link>
    <enclosure url="https://example.com/42.mp3" type="audio/mpeg"/></item></channel></rss>"""
    wire = ScriptedTransport([response(page), response(feed, "application/rss+xml")])
    result = resolve(caller(wire), "https://example.com/ep")
    assert result.state == "resolved" and result.candidates[0].episode_id == "episode-42"
    candidates = feed_candidates(feed, "https://example.com/rss")
    assert match_episode(candidates, "Sanaz Yashar", "https://example.com/rss").state == "resolved"
    assert match_episode(candidates, "43", "https://example.com/rss").state == "no_match"
    assert (
        match_episode(candidates * 2, "Sanaz Yashar", "https://example.com/rss").state
        == "ambiguous"
    )


def test_description_is_not_transcript_and_xml_entities_refused():
    from clue_api.arv2.gemini_media_client import GeminiMediaClient

    assert (
        GeminiMediaClient.parse_recording_text(
            "## META\ntitle: A discussion about evidence\n## QUOTES\nNone",
            model="fixture",
            structured=True,
        ).text
        == ""
    )
    wire = ScriptedTransport([response("<html><p>An exciting episode about research</p></html>")])
    assert resolve(caller(wire), "https://example.com/episode").transcript is None
    with pytest.raises(ValueError, match="entities"):
        feed_candidates('<!DOCTYPE rss [<!ENTITY x "bad">]><rss/>', "https://example.com/rss")


def test_publisher_captions_keep_real_times_without_asserting_speaker_identity():
    from clue_api.arv2.media_resolution import caption_text

    value, segments = caption_text(
        "WEBVTT\n\n00:01.250 --> 00:03.500\n<v Host>First question.</v>\n\n"
        "00:04.000 --> 00:06.000\n<v Guest>Café 🙂 and evidence.</v>\n"
    )
    assert value == "First question.\nCafé 🙂 and evidence."
    assert [s.time_s for s in segments] == [1.25, 4.0]
    assert all(s.timing == "source_supplied" and s.attribution == "metadata" for s in segments)
    assert value[segments[1].start : segments[1].end] == "Café 🙂 and evidence."


def test_redirect_base_and_multiple_recording_choices_are_explicit():
    wire = ScriptedTransport(
        [
            HttpResponse(
                200,
                {
                    "content-type": "text/html",
                    "x-arv2-final-url": "https://publisher.example.com/shows/episode",
                },
                b'<audio src="recording.mp3"></audio>',
            ),
            HttpResponse(200, {"content-type": "audio/mpeg"}, b"fixture"),
        ]
    )
    result = resolve(caller(wire), "https://example.com/redirect")
    assert result.candidates[0].media_url == "https://publisher.example.com/shows/recording.mp3"
    assert "https://example.com/redirect" in result.aliases
    choices = resolve(
        caller(
            ScriptedTransport(
                [response('<audio src="/one.mp3"></audio><audio src="/two.mp3"></audio>')]
            )
        ),
        "https://example.com/two-recordings",
    )
    assert choices.state == "ambiguous" and len(choices.candidates) == 2


def test_source_qualifications_are_context_and_cannot_be_quoted_as_evidence():
    from clue_api.arv2.structuring_client import SourceBlock, build_bundle, source_of_span

    source = SourceBlock(
        url="https://example.com/episode",
        kind="transcript",
        text="Real speech.",
        annotations={"quote_verdict": "NOT_FOUND", "warning": "Unverified voice."},
    )
    bundle = build_bundle([source], None)
    assert "NOT_FOUND" in bundle and "qualifications (not evidence)" in bundle
    assert source_of_span([source], "Unverified voice.") is None
    assert source_of_span([source], "Real speech.") is source


def test_public_video_calls_native_transcription_instead_of_indexed_text():
    body = {
        "responseId": "native-request-1",
        "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 50},
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {
                            "text": "## TRANSCRIPT\n[00:01] Host: Why?\n"
                            "[00:03] Guest: We need better evidence."
                        }
                    ]
                },
            }
        ],
    }
    wire = ScriptedTransport([HttpResponse(200, body=json.dumps(body).encode())])
    ledger = MemoryLedger()
    client = _client(wire, ledger, ceiling_s=600)
    transcript = client.transcribe_video(
        "https://youtu.be/abcdefghijk",
        duration_s=60,
        context=SpeakerContext(person_name="Known Guest"),
    )
    request = json.loads(wire.requests[0].body)
    assert (
        request["contents"][0]["parts"][0]["fileData"]["fileUri"]
        == "https://www.youtube.com/watch?v=abcdefghijk"
    )
    assert "We need better evidence." in transcript.text
    result = next(row for row in ledger.rows if row.phase == "result")
    assert result.provider_request_id == "native-request-1"
    assert result.cost_usd is None and result.extras["cost_source"] == "unpriced"
    assert result.extras["prompt_tokens"] == 120 and result.extras["completion_tokens"] == 50
    assert result.extras["model"] == transcript.model and result.media_seconds == 60
    text, segments, quality = assess_transcript(transcript)
    assert all(s.attribution != "evidence_backed" for s in segments)
    assert quality.coverage == "unknown"
    assert any(s.timing == "model_estimated" for s in segments)


def test_loop_truncation_and_nullable_timing_are_independent():
    transcript = Transcript(
        model="fixture",
        text="\n".join(["Repeated sentence."] * 50),
        lines=tuple(TranscriptLine(None, "", "Repeated sentence.") for _ in range(50)),
        finish_reason="MAX_TOKENS",
    )
    _, segments, quality = assess_transcript(transcript)
    assert {"repetition_detected", "provider_incomplete"} <= set(quality.warnings)
    assert quality.coverage == "partial" and all(s.time_s is None for s in segments)
    with pytest.raises(ValueError):
        Segment(start=0, end=3, attribution="evidence_backed")


def test_chunks_cover_unicode_long_turns_without_loss():
    value = "Begin.\n" + ("你好 café 🙂 long turn " * 500) + "\nEnd."
    spans = chunks(value)
    covered = set()
    for start, end in spans:
        covered.update(range(start, end))
        assert len(value[start:end].encode()) <= 800
    assert covered == set(range(len(value)))
    assert spans[0][0] == 0 and spans[-1][1] == len(value)


def test_embedding_adapter_format_dimension_fallback_and_validation():
    vector = [1.0] + [0.0] * 767
    wire = ScriptedTransport(
        [
            HttpResponse(400, body=b"dimensions unsupported"),
            HttpResponse(
                200, body=json.dumps({"data": [{"index": 0, "embedding": vector}]}).encode()
            ),
        ]
    )
    result = _client(wire, MemoryLedger(), ceiling_s=600).embed_texts(
        ["Exact evidence"], query=True
    )
    assert result.dimensions == 768
    first, second = [json.loads(r.body) for r in wire.requests]
    assert first["input"] == ["search_query: Exact evidence"] and "dimensions" not in second
    with pytest.raises(ValueError):
        vector_string([float("nan")], 1)
    with pytest.raises(ValueError):
        vector_string([0.0], 1)
    with pytest.raises(ValueError):
        vector_string([1.0], 2)


def test_v3_keeps_committee_and_new_guidance():
    assert has_capability("v3", "committee_discovery") and has_capability("v3", "media_research")
    assert not has_capability("v2", "media_research")
    with pytest.raises(ValueError):
        has_capability("unregistered-version", "media_research")
    assert has_capability("v4", "media_research")
    for bundle in [load_account_resources(version="v3"), load_person_resources(version="v3")]:
        assert len(bundle.manifest()) == 5
        manual = bundle.skills[-1].body
        assert all(
            name in manual
            for name in ("discover_media", "read_media", "search_transcripts", "open_transcript")
        )
        assert "no fixed six-query" in manual
