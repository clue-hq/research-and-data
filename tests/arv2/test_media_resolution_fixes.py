"""Resolution defects found replaying run 7's media links (2026-10-13). Offline.

Each test reproduces one link shape that failed on a real page: an Apple episode link matched by
title instead of its id, one MP3 counted twice because of tracking parameters, a page naming
itself as its own audio, a host that refuses a request naming no acceptable type, a recording
downloaded once to learn its type and again to transcribe it, and a "/feedback" page taken for
a feed.
"""

from __future__ import annotations

import json

import httpx

from clue_api.arv2.media_resolution import (
    PROBE_HEADER,
    match_episode,
    read_body,
    resolve,
)
from clue_api.arv2.media_sources import podcast_links
from clue_api.arv2.media_types import Candidate
from clue_api.arv2.transport import HttpResponse, ScriptedTransport
from tests.arv2.test_media_research import caller, response

SHOW = "1627593742"
EPISODE = "1000626303351"
APPLE_URL = f"https://podcasts.apple.com/us/podcast/dialpads-morgan-norman/id{SHOW}?i={EPISODE}"
FEED = "https://feeds.example.com/builders.xml"
GUID = "8c3c87d5-8676-4846-aa0f-1a0d7896bf06"


def json_reply(value):
    return HttpResponse(200, {"content-type": "application/json"}, json.dumps(value).encode())


def show_lookup():
    return json_reply({"results": [{"collectionId": int(SHOW), "feedUrl": FEED}]})


def episode_lookup(guid=GUID):
    return json_reply(
        {
            "results": [
                {"wrapperType": "track", "collectionId": int(SHOW), "feedUrl": FEED},
                {
                    "wrapperType": "podcastEpisode",
                    "trackId": 1000000000001,
                    "trackName": "Another guest",
                    "episodeGuid": "other",
                },
                {
                    "wrapperType": "podcastEpisode",
                    "trackId": int(EPISODE),
                    "trackName": "Dialpad’s Morgan Norman: Reducing Cognitive Load",
                    "episodeGuid": guid,
                    "episodeUrl": "https://cdn.example.com/morgan.mp3?aid=rss_feed",
                    "trackTimeMillis": 2752000,
                    "releaseDate": "2023-08-31T09:00:00Z",
                    "description": "An interview with Morgan Norman.",
                    "trackViewUrl": APPLE_URL + "&uo=4",
                },
            ]
        }
    )


def feed(*items):
    rows = "".join(
        f"<item><guid>{guid}</guid><title>{title}</title>"
        f"<itunes:duration>2752</itunes:duration>"
        f'<enclosure url="https://cdn.example.com/{n}.mp3" type="audio/mpeg"/></item>'
        for n, (guid, title) in enumerate(items)
    )
    return response(
        '<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>'
        f"<title>Builders Wanted</title>{rows}</channel></rss>",
        "application/rss+xml",
    )


def test_an_apple_episode_link_is_matched_by_its_episode_guid_not_by_the_hint():
    wire = ScriptedTransport(
        [
            show_lookup(),
            episode_lookup(),
            feed(("newer", "A newer episode"), (GUID, "Dialpad’s Morgan Norman")),
        ]
    )
    result = resolve(caller(wire), APPLE_URL, hint="Dialpad's Morgan Norman: Reduc… - Apple")
    assert result.state == "resolved"
    assert result.candidates[0].episode_id == GUID
    assert result.candidates[0].media_url == "https://cdn.example.com/1.mp3"
    assert "entity=podcastEpisode" in wire.requests[1].url


def test_an_apple_episode_missing_from_the_feed_uses_apples_own_episode_record():
    wire = ScriptedTransport([show_lookup(), episode_lookup(), feed(("newer", "A newer episode"))])
    result = resolve(caller(wire), APPLE_URL)
    assert result.state == "resolved"
    chosen = result.candidates[0]
    assert chosen.media_url == "https://cdn.example.com/morgan.mp3?aid=rss_feed"
    assert chosen.episode_id == GUID and chosen.feed_url == FEED
    assert chosen.duration_s == 2752
    assert chosen.published_at is not None and chosen.published_at.year == 2023
    assert "apple_episode:" + EPISODE in chosen.identity_evidence
    # The same key the feed would give this episode, so a later feed read reuses the transcript.
    from clue_api.arv2.media_types import content_hash

    assert chosen.canonical_key == "rss:" + content_hash(FEED + ":" + GUID)


def test_hint_matching_ignores_curly_quotes_and_spacing():
    episode = Candidate(url="https://e.example/1", title="Dialpad’s Morgan  Norman: PLG")
    other = Candidate(url="https://e.example/2", title="Another guest")
    result = match_episode([episode, other], "Dialpad's Morgan Norman", "https://x.example")
    assert result.state == "resolved" and result.candidates[0] == episode


def test_one_media_file_behind_different_tracking_parameters_is_one_recording():
    page = """<meta property="og:audio" content="https://cdn.example.com/ep.mp3?client_source=web&amp;referrer=x">
    <meta name="twitter:player" content="https://cdn.example.com/ep?client_source=card&amp;player_type=full">
    <meta name="twitter:player:stream" content="https://cdn.example.com/ep.mp3?client_source=card">"""
    wire = ScriptedTransport([response(page), response("recording", "audio/mpeg")])
    result = resolve(caller(wire), "https://show.example.com/episodes/1")
    assert result.state == "resolved"
    assert result.candidates[0].media_url.startswith("https://cdn.example.com/ep.mp3")
    origins = result.candidates[0].identity_evidence
    assert "html:meta:og:audio" in origins and "html:meta:twitter:player:stream" in origins


def test_a_page_naming_itself_as_its_audio_or_embed_is_not_a_recording():
    url = "https://www.iheart.example/podcast/show/episode/talk-284727545"
    page = f"""<meta name="twitter:player" content="{url}">
    <meta property="og:audio" content="{url}">
    <meta property="og:video:url" content="{url}?embed=true">"""
    result = resolve(caller(ScriptedTransport([response(page)])), url)
    assert result.state == "unsupported"
    assert result.gaps == ("no_supported_recording_link",)


def test_public_fetches_send_ordinary_browser_accept_headers():
    wire = ScriptedTransport([response("<p>No recording</p>")])
    resolve(caller(wire), "https://show.example.com/page")
    headers = {k.lower(): v for k, v in wire.requests[0].headers.items()}
    assert headers["accept"].startswith("text/html")
    assert headers["accept-language"].startswith("en")


def test_resolution_asks_the_transport_for_headers_only_when_the_link_is_a_recording():
    wire = ScriptedTransport([HttpResponse(200, {"content-type": "audio/mpeg"}, b"")])
    result = resolve(caller(wire), "https://cdn.example.com/talk.mp3")
    assert result.state == "resolved" and result.candidates[0].family == "audio"
    assert wire.requests[0].headers[PROBE_HEADER] == "1"


class _Stream(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.read = 0

    def __iter__(self):
        for chunk in self.chunks:
            self.read += 1
            yield chunk


def test_a_probed_recording_is_not_downloaded_but_a_probed_page_is_read_whole():
    stream = _Stream([b"a" * 10, b"b" * 10])
    audio = httpx.Response(200, headers={"content-type": "audio/mpeg"}, stream=stream)
    assert read_body(audio, probe=True) == b"" and stream.read == 0
    page = httpx.Response(200, headers={"content-type": "text/html"}, stream=_Stream([b"<p>"]))
    assert read_body(page, probe=True) == b"<p>"
    whole = httpx.Response(200, headers={"content-type": "audio/mpeg"}, stream=_Stream([b"x"]))
    assert read_body(whole, probe=False) == b"x"


def test_a_feedback_page_is_not_a_feed():
    text = "Send us https://example.com/feedback or subscribe https://example.com/feed"
    assert podcast_links(text) == ["https://example.com/feed"]


TRANSISTOR_PAGE = "https://share.transistor.fm/e/4f7793d7"
TRANSISTOR_FEED = "https://feeds.transistor.fm/the-modern-hotelier"
EPISODE_TITLE = "#276: Building a Tech-Forward Hotel Brand | with Roman Pedan of Kasa"
PLAYER_MP3 = "https://pdst.fm/e/media.transistor.fm/4f7793d7/46ec5b96.mp3"


def transistor_player(*episodes):
    """A Transistor embed: the player's data is JSON in an HTML-escaped Alpine ``x-data``."""
    import html

    data = {"id": 29433, "title": "The Modern Hotelier", "feed_url": TRANSISTOR_FEED}
    data["episodes"] = [
        {
            "id": 3250707 + n,
            "title": title,
            "duration": 3040,
            "trackable_media_url": PLAYER_MP3,
            "share_url": "https://themodernhotelier.com/episode/276",
            "transcript_url": "https://share.transistor.fm/s/4f7793d7/transcript",
        }
        for n, title in enumerate(episodes)
    ]
    attribute = html.escape(f"transistor.audioEmbedPlayer({json.dumps(data)})")
    return response(f'<html><body><div id="embed-player" x-data="{attribute}"></div></body></html>')


def transistor_feed(title):
    return response(
        '<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
        'xmlns:podcast="https://podcastindex.org/namespace/1.0"><channel>'
        f"<title>The Modern Hotelier</title><item><guid>ep-276</guid><title>{title}</title>"
        "<link>https://themodernhotelier.com/episode/276</link>"
        "<itunes:duration>3040</itunes:duration>"
        '<enclosure url="https://media.transistor.fm/4f7793d7/46ec5b96.mp3" type="audio/mpeg"/>'
        '<podcast:transcript url="https://share.transistor.fm/s/4f7793d7/transcript.txt" '
        'type="text/plain"/></item></channel></rss>',
        "application/rss+xml",
    )


def test_a_transistor_player_leads_to_its_episode_in_the_shows_feed_and_its_transcript():
    wire = ScriptedTransport(
        [
            transistor_player(EPISODE_TITLE),
            transistor_feed(EPISODE_TITLE.replace("&", "&amp;")),
            response("David Millili: Welcome.\nRoman Pedan: Thanks.", "text/plain"),
        ]
    )
    result = resolve(caller(wire), TRANSISTOR_PAGE)
    assert result.state == "resolved"
    assert result.candidates[0].title == EPISODE_TITLE
    assert result.candidates[0].feed_url == TRANSISTOR_FEED
    assert result.transcript and "Roman Pedan: Thanks." in result.transcript
    assert TRANSISTOR_PAGE in result.aliases
    assert [r.url for r in wire.requests][1] == TRANSISTOR_FEED


def test_a_transistor_player_whose_feed_lacks_the_episode_uses_the_players_own_recording():
    wire = ScriptedTransport(
        [
            transistor_player(EPISODE_TITLE),
            transistor_feed("#275: Another guest"),
            HttpResponse(200, {"content-type": "audio/mpeg"}, b""),
        ]
    )
    result = resolve(caller(wire), TRANSISTOR_PAGE)
    assert result.state == "resolved"
    assert result.candidates[0].media_url == PLAYER_MP3
    assert "html:transistor-player" in result.candidates[0].identity_evidence
