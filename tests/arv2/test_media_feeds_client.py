"""Unit tests for the media client's pure logic — feed parsing, matching, host refusal.

These three things are the ones a live feed cannot demonstrate on demand: an episode with no
``itunes:episode`` tag, a title that *nearly* matches, and a walled host. They run on inline
strings (Global Constraint 3 permits it — no provider is called and no body is mocked; the
input is literally the test's own data). Everything that touches a provider is in the live file.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from clue_api.arv2.errors import RawParseError
from clue_api.arv2.media_feeds_client import (
    MAX_FEED_BYTES,
    MAX_LABEL_CHARS,
    Episode,
    UnsupportedMediaHost,
    _label_for,
    download_enclosure,
    episode_number_from_title,
    extract_player_response,
    find_episode,
    is_youtube,
    parse_duration,
    parse_feed,
    reject_native_video,
    video_id,
)

#: The real Boardroom Club feed URL, used here only to pin the derived ledger label.
BOARDROOM_FEED_URL = "https://anchor.fm/s/f695d6d8/podcast/rss"

#: A feed exercising every shape the parser has to survive: the iTunes namespace, CDATA titles,
#: an episode whose number lives only in its title, one with no enclosure and no duration at all,
#: and a self-link the parser is expected to read as the feed URL.
FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title><![CDATA[Boardroom Club]]></title>
    <atom:link href="https://example.test/feed.rss" rel="self" type="application/rss+xml"/>
    <item>
      <title><![CDATA[AI Summit: Sanaz Yashar, Co-Founder and CEO at Zafran Security]]></title>
      <description><![CDATA[<p>A conversation about exposure management.</p>]]></description>
      <link>https://example.test/episodes/sanaz</link>
      <pubDate>Sun, 10 Aug 2025 14:00:00 GMT</pubDate>
      <itunes:episode>5</itunes:episode>
      <itunes:duration>00:42:49</itunes:duration>
      <enclosure url="https://cdn.example.test/sanaz.mp3" length="41116315" type="audio/mpeg"/>
    </item>
    <item>
      <title>Ep 297 AI, Cybersecurity &amp; the Future of Business</title>
      <itunes:duration>58:20</itunes:duration>
      <enclosure url="https://cdn.example.test/297.mp3" length="not-a-number" type="audio/mpeg"/>
    </item>
    <item>
      <title>A 2026 Outlook On 300 Enterprise Buyers</title>
      <pubDate>not a date at all</pubDate>
    </item>
  </channel>
</rss>
"""


def test_parse_feed_reads_the_channel_the_self_link_and_every_item() -> None:
    podcast = parse_feed(FEED_XML)

    assert podcast.title == "Boardroom Club"
    assert podcast.feed_url == "https://example.test/feed.rss"
    assert [episode.title[:12] for episode in podcast.episodes] == [
        "AI Summit: S",
        "Ep 297 AI, C",
        "A 2026 Outlo",
    ]


def test_parse_feed_reads_the_itunes_fields_and_the_enclosure_of_a_full_item() -> None:
    sanaz = parse_feed(FEED_XML).episodes[0]

    assert sanaz.number == 5
    assert sanaz.duration_s == 2569, "00:42:49 is 42*60 + 49"
    assert sanaz.enclosure_url == "https://cdn.example.test/sanaz.mp3"
    assert sanaz.enclosure_bytes == 41116315
    assert sanaz.published_at == datetime(2025, 8, 10, 14, 0, tzinfo=UTC)
    assert sanaz.link == "https://example.test/episodes/sanaz"
    assert sanaz.description is not None and "exposure management" in sanaz.description


def test_parse_feed_falls_back_to_the_title_for_a_number_and_never_invents_a_value() -> None:
    """An absent tag becomes ``None``, not zero — a missing duration is not a silent 0 seconds."""
    _, numbered, bare = parse_feed(FEED_XML).episodes

    assert numbered.number == 297, "read from the leading 'Ep 297' when itunes:episode is absent"
    assert numbered.enclosure_bytes is None, "an unparseable length is unknown, not zero"
    assert (bare.number, bare.duration_s, bare.enclosure_url, bare.enclosure_bytes) == (
        None,
        None,
        None,
        None,
    )
    assert bare.published_at is None, "an unparseable pubDate is unknown, never 'now'"


def test_parse_feed_refuses_a_document_that_is_not_a_feed() -> None:
    with pytest.raises(RawParseError):
        parse_feed("<html><body>not a feed</body></html>")
    with pytest.raises(RawParseError):
        parse_feed("this is not xml at <all")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("00:42:49", 2569),
        ("1:02:03", 3723),
        ("58:20", 3500),
        ("2569", 2569),
        ("2569.0", 2569),
        (" 42:49 ", 2569),
        ("", None),
        (None, None),
        ("about an hour", None),
        ("1:2:3:4", None),
        ("-5", None),
    ],
)
def test_parse_duration_reads_the_three_itunes_forms_and_nothing_else(
    text: str | None, expected: int | None
) -> None:
    assert parse_duration(text) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Ep 297 AI and the Future", 297),
        ("EP265 Beyond Shadow IT", 265),
        ("#297 AI and the Future", 297),
        ("Episode 297: AI and the Future", 297),
        ("episode 12 - something", 12),
        ("Ep. 8 A short one", 8),
        ("A 2026 Outlook On 300 Buyers", None),
        ("Talking about Ep 297 later on", None),
        ("", None),
    ],
)
def test_episode_number_from_title_is_anchored_so_a_year_is_never_an_episode(
    title: str, expected: int | None
) -> None:
    assert episode_number_from_title(title) == expected


def test_find_episode_matches_an_exact_number_before_anything_else() -> None:
    podcast = parse_feed(FEED_XML)

    found = find_episode(podcast, number=297)

    assert found is not None and found.title.startswith("Ep 297")


def test_find_episode_matches_a_title_substring_case_insensitively() -> None:
    podcast = parse_feed(FEED_XML)

    found = find_episode(podcast, title_contains="sanaz")

    assert found is not None and found.number == 5


def test_find_episode_prefers_the_number_when_both_criteria_are_given() -> None:
    podcast = parse_feed(FEED_XML)

    found = find_episode(podcast, number=5, title_contains="Ep 297")

    assert found is not None and found.number == 5


def test_find_episode_falls_through_to_the_title_when_the_number_misses() -> None:
    podcast = parse_feed(FEED_XML)

    found = find_episode(podcast, number=999, title_contains="Sanaz")

    assert found is not None and found.number == 5


def test_find_episode_returns_none_rather_than_the_closest_thing() -> None:
    """Law 10: no fuzzy scoring. The proof-of-concept's word overlap returned EP280 for EP265."""
    podcast = parse_feed(FEED_XML)

    assert find_episode(podcast, number=265) is None
    assert find_episode(podcast, title_contains="Beyond Shadow IT") is None


def test_find_episode_refuses_to_search_with_no_criteria() -> None:
    with pytest.raises(ValueError, match="will not guess"):
        find_episode(parse_feed(FEED_XML))


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/posts/cogentsecurity_head-of-growth-video-activity-7460449",
        "https://linkedin.com/feed/update/urn:li:activity:7452",
        "https://www.x.com/someone/status/1234567890",
        "https://x.com/someone/status/1234567890",
        "https://twitter.com/someone/status/1234567890",
        "https://mobile.twitter.com/someone/status/1234567890",
    ],
)
def test_reject_native_video_refuses_every_walled_host(url: str) -> None:
    with pytest.raises(UnsupportedMediaHost):
        reject_native_video(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=avcD5WVLCYs",
        "https://anchor.fm/s/f695d6d8/podcast/rss",
        "https://notlinkedin.com/posts/whatever",
        "https://example.com/x.com/not-really",
    ],
)
def test_reject_native_video_lets_a_fetchable_host_through(url: str) -> None:
    assert reject_native_video(url) is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/watch?v=avcD5WVLCYs", True),
        ("https://m.youtube.com/watch?v=avcD5WVLCYs", True),
        ("https://youtu.be/avcD5WVLCYs", True),
        ("https://vimeo.com/12345", False),
        ("https://anchor.fm/s/f695d6d8/podcast/rss", False),
    ],
)
def test_is_youtube_decides_on_the_host(url: str, expected: bool) -> None:
    assert is_youtube(url) is expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/watch?v=avcD5WVLCYs", "avcD5WVLCYs"),
        ("https://youtu.be/8_YWBtq4eic", "8_YWBtq4eic"),
        ("https://www.youtube.com/live/8_YWBtq4eic", "8_YWBtq4eic"),
        ("https://www.youtube.com/watch?v=short", None),
        ("https://example.com/nothing", None),
    ],
)
def test_video_id_reads_the_three_url_forms(url: str, expected: str | None) -> None:
    assert video_id(url) == expected


def test_the_ledger_label_stays_short_enough_to_be_a_filename() -> None:
    """A real anchor.fm enclosure percent-encodes the whole CDN URL into its last segment.

    ``FileRawSink`` builds a filename from the label, so an untruncated one lands within a few
    bytes of the 255-byte limit and law 1's raw record becomes unwritable.
    """
    enclosure = (
        "https://anchor.fm/s/f695d6d8/podcast/play/106390290/https%3A%2F%2F"
        "d3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2025-7-9%2F405396769-44100-2-7287bb9271f44.mp3"
    )

    assert len(_label_for(enclosure)) <= MAX_LABEL_CHARS
    assert _label_for(BOARDROOM_FEED_URL) == "anchor.fm-rss"
    assert _label_for("https://example.test/") == "example.test"


def test_extract_player_response_survives_braces_inside_strings() -> None:
    """A naive depth counter (or a non-greedy regex) truncates here; the scanner must not."""
    html = (
        "<script>var meta = {};"
        'ytInitialPlayerResponse = {"videoDetails":{"title":"a } brace \\" and {more}",'
        '"lengthSeconds":"254"}};var after = 1;</script>'
    )

    player = extract_player_response(html)

    assert player is not None
    details = player["videoDetails"]
    assert isinstance(details, dict)
    assert details["lengthSeconds"] == "254"
    assert details["title"] == 'a } brace " and {more}'


def test_extract_player_response_reads_the_bracketed_assignment_form() -> None:
    html = 'window["ytInitialPlayerResponse"] = {"videoDetails":{"title":"x"}};'

    player = extract_player_response(html)

    assert player is not None and "videoDetails" in player


def test_extract_player_response_is_none_on_a_consent_wall() -> None:
    assert extract_player_response("<html>Sign in to confirm you are not a bot</html>") is None
    assert extract_player_response('ytInitialPlayerResponse = {"unclosed": 1') is None


def test_an_oversized_feed_is_refused_before_it_is_parsed() -> None:
    """A feed is third-party XML on a fleet worker; ``ET.fromstring`` builds the whole tree.

    The refusal is a typed :class:`RawParseError` naming the record on disk, so an operator can
    look at what the host actually served — not an unbounded allocation and not a silent empty
    result.
    """
    padding = "<item><title>x</title></item>" * 200_000
    oversized = f"<rss><channel><title>Big</title>{padding}</channel></rss>"
    assert len(oversized.encode("utf-8")) > MAX_FEED_BYTES

    with pytest.raises(RawParseError) as excinfo:
        parse_feed(oversized)

    assert "over the" in str(excinfo.value)
    assert str(MAX_FEED_BYTES) in str(excinfo.value)


def test_a_feed_just_under_the_cap_still_parses() -> None:
    """The cap is a refusal for the pathological case, not a limit real feeds run into."""
    padding = "<item><title>ok</title></item>" * 100
    document = f"<rss><channel><title>Small</title>{padding}</channel></rss>"
    assert len(document.encode("utf-8")) < MAX_FEED_BYTES

    podcast = parse_feed(document)

    assert podcast.title == "Small"
    assert len(podcast.episodes) == 100


def test_a_failed_or_retryable_head_never_costs_the_download_or_a_backoff(tmp_path: Path) -> None:
    """The HEAD precheck is an opportunity, not a gate (re-review 2026-09-07).

    A transport failure on the HEAD, or a retryable status, falls straight through to the GET —
    no exception escapes, and no ``12·(n+1)`` s backoff is spent on a probe the item does not
    depend on.
    """
    from datetime import UTC, datetime

    from clue_api.arv2.calls import ProviderCaller
    from clue_api.arv2.sinks import MemoryLedger, MemoryRawSink
    from clue_api.arv2.transport import HttpResponse, ScriptedTransport, TransportFailure

    audio = b"\xff\xfb\x90\x00" * 8
    episode = Episode(
        number=None,
        title="ep",
        enclosure_url="https://cdn.example/ep.mp3",
        enclosure_bytes=None,
        duration_s=30,
        published_at=None,
        link=None,
        description=None,
    )
    for head_outcome in (TransportFailure("reset"), HttpResponse(503, {}, b"")):
        sleeps: list[float] = []
        transport = ScriptedTransport(
            [head_outcome, HttpResponse(200, {"content-type": "audio/mpeg"}, audio)]
        )
        caller = ProviderCaller(
            transport=transport,
            raw_sink=MemoryRawSink(),
            ledger=MemoryLedger(),
            sleep=sleeps.append,
            now=lambda: datetime.now(UTC),
        )
        result = download_enclosure(episode, tmp_path / "ep.mp3", caller, max_bytes=1_000_000)
        assert result.bytes == len(audio)
        assert sleeps == [], "a probe must never spend the backoff"
        assert [request.method for request in transport.requests] == ["HEAD", "GET"]
