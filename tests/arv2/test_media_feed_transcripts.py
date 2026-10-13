"""Podcast feeds: the publisher's own transcript and the episode's date. Offline."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from clue_api.arv2.media_resolution import resolve
from clue_api.arv2.transport import HttpResponse, ScriptedTransport
from tests.arv2.test_media_research import caller, response

FEED = """<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
  xmlns:podcast="https://podcastindex.org/namespace/1.0"><channel><title>Show</title>
  <item><guid>ep-1</guid><title>Evidence episode</title><link>https://example.com/ep-1</link>
  <pubDate>Tue, 07 Apr 2026 10:00:00 GMT</pubDate><itunes:duration>3600</itunes:duration>
  <enclosure url="https://example.com/ep-1.mp3" type="audio/mpeg"/>
  {transcripts}</item></channel></rss>"""


def feed(transcripts=""):
    return response(FEED.format(transcripts=transcripts), "application/rss+xml")


def test_a_feed_transcript_is_used_instead_of_the_audio():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v Host>We buy on evidence.\n"
    wire = ScriptedTransport(
        [
            feed(
                '<podcast:transcript url="https://example.com/ep-1.html" type="text/html"/>'
                '<podcast:transcript url="https://example.com/ep-1.vtt" type="text/vtt"/>'
            ),
            response(vtt, "text/vtt"),
        ]
    )
    result = resolve(caller(wire), "https://example.com/feed", hint="ep-1")
    assert result.state == "resolved" and result.transcript == "We buy on evidence."
    assert result.segments[0].timing == "source_supplied" and result.segments[0].speaker == "Host"
    assert result.candidates[0].published_at == datetime(2026, 4, 7, 10, tzinfo=UTC)
    assert wire.requests[-1].url == "https://example.com/ep-1.vtt"


def test_a_json_feed_transcript_keeps_speakers_and_times():
    body = {
        "version": "1.0.0",
        "segments": [
            {"speaker": "Guest", "startTime": 2.5, "endTime": 6.0, "body": "We measure pipeline."}
        ],
    }
    wire = ScriptedTransport(
        [
            feed(
                '<podcast:transcript url="https://example.com/ep-1.json" type="application/json"/>'
            ),
            HttpResponse(200, {"content-type": "application/json"}, json.dumps(body).encode()),
        ]
    )
    result = resolve(caller(wire), "https://example.com/feed", hint="ep-1")
    assert result.transcript == "We measure pipeline."
    assert result.segments[0].time_s == 2.5 and result.segments[0].speaker == "Guest"


def test_an_html_feed_transcript_is_read_as_text():
    html = "<html><style>p{}</style><p>Host: Welcome.</p><p>Guest: Thanks.</p></html>"
    wire = ScriptedTransport(
        [
            feed('<podcast:transcript url="https://example.com/ep-1.html" type="text/html"/>'),
            response(html),
        ]
    )
    result = resolve(caller(wire), "https://example.com/feed", hint="ep-1")
    assert result.transcript == "Host: Welcome.\nGuest: Thanks."


def test_an_unreachable_feed_transcript_falls_back_to_the_audio():
    wire = ScriptedTransport(
        [
            feed('<podcast:transcript url="https://example.com/ep-1.vtt" type="text/vtt"/>'),
            HttpResponse(404, {"content-type": "text/plain"}, b"gone"),
        ]
    )
    result = resolve(caller(wire), "https://example.com/feed", hint="ep-1")
    assert result.state == "resolved" and result.transcript is None
    assert result.candidates[0].media_url == "https://example.com/ep-1.mp3"
    assert any(gap.startswith("feed_transcript_unavailable") for gap in result.gaps)
