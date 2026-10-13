"""Official and public media sources (spec 2026-10-13-legitimate-media-sources-design). Offline."""

from __future__ import annotations

import pytest

from clue_config.secrets import Secrets
from clue_spend import redact_headers


def test_media_source_keys_load_from_the_environment(monkeypatch):
    monkeypatch.setenv("CLUE_YOUTUBE_DATA_API_KEY", "yt-key")
    monkeypatch.setenv("CLUE_PODCAST_INDEX_API_KEY", "pi-key")
    monkeypatch.setenv("CLUE_PODCAST_INDEX_API_SECRET", "pi-secret")
    secrets = Secrets(_env_file=None)
    assert secrets.youtube_data_api_key.get_secret_value() == "yt-key"
    assert secrets.podcast_index_api_key.get_secret_value() == "pi-key"
    assert secrets.podcast_index_api_secret.get_secret_value() == "pi-secret"


def test_podcast_index_key_header_is_redacted_in_raw_records():
    headers = redact_headers(
        {"X-Auth-Key": "pi-key", "Authorization": "digest", "X-Auth-Date": "1700000000"}
    )
    assert headers["X-Auth-Key"] == "***" and headers["Authorization"] == "***"
    assert headers["X-Auth-Date"] == "1700000000"


# --- Task 3: official and public lookups and episode matching ---------------------------------

import hashlib  # noqa: E402
import json  # noqa: E402
from dataclasses import replace  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

from pydantic import SecretStr  # noqa: E402

from clue_api.arv2.media_sources import (  # noqa: E402
    MediaSourceKeys,
    VideoDetails,
    iso_duration_seconds,
    podcast_index_shows,
    podcast_links,
    podcast_twin,
    same_episode,
    spotify_show_name,
    youtube_details,
)
from clue_api.arv2.media_types import Candidate  # noqa: E402
from clue_api.arv2.transport import HttpResponse, ScriptedTransport  # noqa: E402
from tests.arv2.test_media_research import caller, response  # noqa: E402

VIDEO_ID = "abcdefghijk"


def json_reply(value, status=200):
    return HttpResponse(status, {"content-type": "application/json"}, json.dumps(value).encode())


def data_api(**overrides):
    item = {
        "id": VIDEO_ID,
        "snippet": {
            "publishedAt": "2026-04-08T15:00:00Z",
            "title": "Scaling field ABM with Emily Wall",
            "channelTitle": "Revenue Room",
            "description": "Listen: https://podcasts.apple.com/us/podcast/revenue-room/id123456",
            "liveBroadcastContent": "none",
        },
        "contentDetails": {"duration": "PT41M12S"},
        "status": {"privacyStatus": "public"},
    }
    for key, value in overrides.items():
        item[key] = {**item[key], **value}
    return json_reply({"items": [item]})


def video(**changes):
    base = VideoDetails(
        video_id=VIDEO_ID,
        title="Scaling field ABM with Emily Wall",
        channel="Revenue Room",
        description="",
        published_at=datetime(2026, 4, 8, 15, tzinfo=UTC),
        duration_s=2472,
        public=True,
        live=False,
    )
    return replace(base, **changes)


def episode(title, published, duration=2470):
    return Candidate(
        url=f"https://example.com/{title.replace(' ', '-')}",
        title=title,
        family="audio",
        media_url="https://example.com/a.mp3",
        canonical_key="rss:" + title,
        duration_s=duration,
        published_at=published,
    )


def empty_search():
    return json_reply({"results": []})


def apple_lookup():
    return json_reply(
        {"results": [{"collectionId": 123456, "feedUrl": "https://feeds.example.com/rr.xml"}]}
    )


def feed_xml(*items):
    rows = "".join(
        f"<item><guid>{guid}</guid><title>{title}</title><pubDate>{date}</pubDate>"
        f"<itunes:duration>{seconds}</itunes:duration>"
        f'<enclosure url="https://example.com/{guid}.mp3" type="audio/mpeg"/></item>'
        for guid, title, date, seconds in items
    )
    return response(
        '<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>'
        f"<title>Revenue Room</title>{rows}</channel></rss>",
        "application/rss+xml",
    )


EP41 = ("ep-41", "Scaling field ABM with Emily Wall", "Tue, 07 Apr 2026 10:00:00 GMT", 2470)


def test_iso_durations():
    assert iso_duration_seconds("PT41M12S") == 2472
    assert iso_duration_seconds("PT1H") == 3600
    assert iso_duration_seconds("P1DT2S") == 86402
    assert iso_duration_seconds("") is None and iso_duration_seconds("PT") is None


def test_youtube_details_come_from_the_data_api_with_the_key_in_a_header():
    wire = ScriptedTransport([data_api()])
    details = youtube_details(caller(wire), VIDEO_ID, SecretStr("yt-key"))
    assert details.duration_s == 2472 and details.public and not details.live
    assert details.channel == "Revenue Room"
    assert details.published_at == datetime(2026, 4, 8, 15, tzinfo=UTC)
    request = wire.requests[0]
    assert "key=" not in request.url and request.headers["x-goog-api-key"] == "yt-key"
    assert "part=snippet,contentDetails,status" in request.url and f"id={VIDEO_ID}" in request.url


def test_an_unlisted_or_live_video_is_flagged():
    unlisted = youtube_details(
        caller(ScriptedTransport([data_api(status={"privacyStatus": "unlisted"})])),
        VIDEO_ID,
        SecretStr("k"),
    )
    live = youtube_details(
        caller(ScriptedTransport([data_api(snippet={"liveBroadcastContent": "live"})])),
        VIDEO_ID,
        SecretStr("k"),
    )
    assert not unlisted.public and live.live


def test_a_missing_video_is_a_value_error():
    with pytest.raises(ValueError, match="youtube_video_not_found"):
        youtube_details(
            caller(ScriptedTransport([json_reply({"items": []})])), VIDEO_ID, SecretStr("k")
        )


def test_podcast_index_signs_each_request():
    wire = ScriptedTransport(
        [
            json_reply(
                {"feeds": [{"title": "Revenue Room", "url": "https://feeds.example.com/rr.xml"}]}
            )
        ]
    )
    shows = podcast_index_shows(
        caller(wire), "Revenue Room", SecretStr("key"), SecretStr("secret"), now=lambda: 1700000000
    )
    assert [s.feed_url for s in shows] == ["https://feeds.example.com/rr.xml"]
    headers = wire.requests[0].headers
    expected = hashlib.sha1(b"keysecret1700000000", usedforsecurity=False).hexdigest()
    assert headers["Authorization"] == expected and headers["X-Auth-Date"] == "1700000000"
    assert headers["X-Auth-Key"] == "key" and "q=Revenue+Room" in wire.requests[0].url


def test_podcast_links_in_a_description():
    text = (
        "Apple: https://podcasts.apple.com/us/podcast/x/id1. Spotify: "
        "https://open.spotify.com/episode/abc. RSS https://feeds.example.com/show.xml, "
        "site https://example.com/about"
    )
    assert podcast_links(text) == [
        "https://podcasts.apple.com/us/podcast/x/id1",
        "https://open.spotify.com/episode/abc",
        "https://feeds.example.com/show.xml",
    ]


def test_spotify_page_names_the_show():
    html = (
        '<meta property="og:description" '
        'content="Listen to this episode from Revenue Room on Spotify. More.">'
    )
    assert spotify_show_name(html) == "Revenue Room"
    assert spotify_show_name("<html></html>") is None


def test_same_episode_needs_date_duration_and_title_together():
    day = datetime(2026, 4, 7, 10, tzinfo=UTC)
    title = "Scaling field ABM with Emily Wall"
    assert same_episode(episode(title, day), video())
    assert not same_episode(episode(title, day - timedelta(days=9)), video())
    assert not same_episode(episode(title, day, duration=1800), video())
    assert not same_episode(episode("Quarterly earnings recap", day), video())
    assert not same_episode(episode(title, None), video())


def test_naive_feed_dates_compare_as_utc():
    assert same_episode(
        episode("Scaling field ABM with Emily Wall", datetime(2026, 4, 7, 10)), video()
    )


def test_the_description_link_leads_to_the_matching_episode():
    wire = ScriptedTransport(
        [
            apple_lookup(),
            feed_xml(EP41, ("ep-40", "Pricing pages", "Tue, 31 Mar 2026 10:00:00 GMT", 2400)),
        ]
    )
    details = video(description="Listen: https://podcasts.apple.com/us/podcast/rr/id123456")
    matches, gaps = podcast_twin(caller(wire), details, MediaSourceKeys(), visited=frozenset())
    assert [m.episode_id for m in matches] == ["ep-41"] and gaps == []


def test_two_episodes_in_the_window_are_both_returned():
    wire = ScriptedTransport(
        [
            apple_lookup(),
            feed_xml(
                (
                    "ep-41",
                    "Scaling field ABM with Emily Wall part 1",
                    "Tue, 07 Apr 2026 10:00:00 GMT",
                    2470,
                ),
                (
                    "ep-42",
                    "Scaling field ABM with Emily Wall part 2",
                    "Thu, 09 Apr 2026 10:00:00 GMT",
                    2480,
                ),
            ),
        ]
    )
    details = video(description="https://podcasts.apple.com/us/podcast/rr/id123456")
    matches, _ = podcast_twin(caller(wire), details, MediaSourceKeys(), visited=frozenset())
    assert sorted(m.episode_id for m in matches) == ["ep-41", "ep-42"]


def test_without_links_the_channel_is_searched_in_apples_directory():
    search = {
        "results": [
            {"collectionName": "Revenue Room", "feedUrl": "https://feeds.example.com/rr.xml"}
        ]
    }
    wire = ScriptedTransport([json_reply(search), feed_xml(EP41)])
    matches, _ = podcast_twin(caller(wire), video(), MediaSourceKeys(), visited=frozenset())
    assert [m.episode_id for m in matches] == ["ep-41"]
    assert "term=Revenue+Room" in wire.requests[0].url and "media=podcast" in wire.requests[0].url


def test_podcast_index_is_searched_too_when_its_keys_are_set():
    keys = MediaSourceKeys(podcast_index_key=SecretStr("k"), podcast_index_secret=SecretStr("s"))
    wire = ScriptedTransport(
        [
            empty_search(),
            json_reply(
                {"feeds": [{"title": "Revenue Room", "url": "https://feeds.example.com/rr.xml"}]}
            ),
            feed_xml(EP41),
        ]
    )
    matches, _ = podcast_twin(caller(wire), video(), keys, visited=frozenset())
    assert [m.episode_id for m in matches] == ["ep-41"]
    assert "api.podcastindex.org" in wire.requests[1].url


def test_no_show_found_is_a_gap_not_an_error():
    wire = ScriptedTransport([empty_search(), empty_search()])
    matches, gaps = podcast_twin(caller(wire), video(), MediaSourceKeys(), visited=frozenset())
    assert matches == [] and gaps == ["no_podcast_show_found"]


def test_an_unreadable_feed_is_a_gap():
    search = {
        "results": [
            {"collectionName": "Revenue Room", "feedUrl": "https://feeds.example.com/rr.xml"}
        ]
    }
    wire = ScriptedTransport(
        [json_reply(search), response("<rss><channel>broken", "application/rss+xml")]
    )
    matches, gaps = podcast_twin(caller(wire), video(), MediaSourceKeys(), visited=frozenset())
    assert matches == [] and any(g.startswith("podcast_feed_unreadable") for g in gaps)


# --- Task 4: YouTube resolution without the watch page -----------------------------------------

from clue_api.arv2.media_resolution import resolve  # noqa: E402

KEYS = MediaSourceKeys(youtube_api_key=SecretStr("yt-key"))
WATCH = "https://www.youtube.com/watch?v=abcdefghijk"


def test_without_a_youtube_key_the_gap_says_so():
    wire = ScriptedTransport([])
    result = resolve(caller(wire), "https://youtu.be/abcdefghijk")
    assert result.state == "unavailable" and result.gaps == ("youtube_data_api_key_missing",)
    assert wire.requests == []


def test_a_video_with_a_podcast_twin_resolves_to_the_episode():
    wire = ScriptedTransport([data_api(), apple_lookup(), feed_xml(EP41)])
    result = resolve(caller(wire), "https://youtu.be/abcdefghijk", keys=KEYS)
    assert result.state == "resolved" and result.candidates[0].family == "audio"
    assert result.candidates[0].media_url == "https://example.com/ep-41.mp3"
    assert "https://youtu.be/abcdefghijk" in result.aliases
    assert "podcast_twin_of:" + WATCH in result.candidates[0].identity_evidence
    assert not any("youtube.com/watch" in r.url for r in wire.requests)


def test_a_twin_with_its_own_transcript_needs_no_audio():
    feed = response(
        '<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
        'xmlns:podcast="https://podcastindex.org/namespace/1.0"><channel><title>RR</title>'
        "<item><guid>ep-41</guid><title>Scaling field ABM with Emily Wall</title>"
        "<pubDate>Tue, 07 Apr 2026 10:00:00 GMT</pubDate><itunes:duration>2470</itunes:duration>"
        '<enclosure url="https://example.com/ep-41.mp3" type="audio/mpeg"/>'
        '<podcast:transcript url="https://example.com/ep-41.vtt" type="text/vtt"/>'
        "</item></channel></rss>",
        "application/rss+xml",
    )
    vtt = response("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nWe run field ABM.\n", "text/vtt")
    wire = ScriptedTransport([data_api(), apple_lookup(), feed, vtt])
    result = resolve(caller(wire), WATCH, keys=KEYS)
    assert result.state == "resolved" and result.transcript == "We run field ABM."


def test_a_video_without_a_twin_resolves_to_a_youtube_candidate_with_its_details():
    wire = ScriptedTransport(
        [
            data_api(snippet={"description": "Talk at HumanX https://linkedin.com/in/ewall"}),
            empty_search(),
            empty_search(),
        ]
    )
    result = resolve(caller(wire), WATCH, keys=KEYS)
    candidate = result.candidates[0]
    assert result.state == "resolved" and candidate.family == "youtube"
    assert candidate.duration_s == 2472 and candidate.title.startswith("Scaling field ABM")
    assert candidate.published_at == datetime(2026, 4, 8, 15, tzinfo=UTC)
    assert candidate.recognized_subject_urls == ["https://linkedin.com/in/ewall"]
    assert "no_podcast_show_found" in result.gaps


def test_several_twins_go_back_to_the_agent():
    wire = ScriptedTransport(
        [
            data_api(),
            apple_lookup(),
            feed_xml(
                (
                    "ep-41",
                    "Scaling field ABM with Emily Wall part 1",
                    "Tue, 07 Apr 2026 10:00:00 GMT",
                    2470,
                ),
                (
                    "ep-42",
                    "Scaling field ABM with Emily Wall part 2",
                    "Thu, 09 Apr 2026 10:00:00 GMT",
                    2480,
                ),
            ),
        ]
    )
    result = resolve(caller(wire), WATCH, keys=KEYS)
    assert result.state == "ambiguous" and len(result.candidates) == 2


def test_an_unlisted_video_is_never_read():
    wire = ScriptedTransport([data_api(status={"privacyStatus": "unlisted"})])
    result = resolve(caller(wire), WATCH, keys=KEYS)
    assert result.state == "unavailable" and result.gaps == ("youtube_not_public",)


def test_a_directory_outage_falls_through_to_gemini():
    down = HttpResponse(503, {"content-type": "text/plain"}, b"down")
    wire = ScriptedTransport(
        [data_api(snippet={"description": ""}), down, down, json_reply_text("not json")]
    )
    result = resolve(caller(wire), WATCH, keys=KEYS)
    assert result.state == "resolved" and result.candidates[0].family == "youtube"
    assert any(g.startswith("podcast_directory_unavailable") for g in result.gaps)


def json_reply_text(body):
    return HttpResponse(200, {"content-type": "application/json"}, body.encode())


def test_the_linkedin_refusal_points_to_other_places():
    from clue_api.arv2.media_feeds_client import UnsupportedMediaHost

    message = str(UnsupportedMediaHost("https://www.linkedin.com/posts/x", "linkedin.com"))
    assert "never fetched" in message and "YouTube" in message and "event" in message


# --- Task 6: what a worker lacks for media -------------------------------------------------------


def test_a_worker_names_what_it_lacks_for_media(monkeypatch):
    import shutil

    from clue_api.arv2 import account_research_driver as driver

    real_which = shutil.which
    monkeypatch.setattr(
        driver.shutil, "which", lambda name: None if name == "ffprobe" else real_which(name)
    )
    # Explicit, so the test never depends on the keys a developer's environment carries.
    bare = Secrets(_env_file=None).model_copy(
        update={"deepgram_api_key": None, "youtube_data_api_key": None}
    )
    assert driver.media_lane_missing(bare) == [
        "ffprobe",
        "CLUE_DEEPGRAM_API_KEY",
        "CLUE_YOUTUBE_DATA_API_KEY",
    ]
    monkeypatch.setattr(driver.shutil, "which", lambda name: f"/usr/bin/{name}")
    full = bare.model_copy(
        update={
            "deepgram_api_key": SecretStr("dg"),
            "youtube_data_api_key": SecretStr("yt"),
        }
    )
    assert driver.media_lane_missing(full) == []


def test_live_clients_carry_media_keys_and_readiness():
    from clue_api.arv2.account_research_driver import _LiveClients
    from clue_config import Settings

    def clients(**keys):
        return _LiveClients(
            settings=Settings(_env_file=None),
            exa_api_key=SecretStr("e"),
            ai_ark_api_key=SecretStr("a"),
            gemini_api_key=SecretStr("g"),
            openrouter_api_key=SecretStr("o"),
            openrouter_base_url="https://openrouter.ai/api/v1",
            **keys,
        )

    assert not clients().transcription_ready
    ready = clients(deepgram_api_key=SecretStr("dg"), youtube_data_api_key=SecretStr("yt"))
    assert ready.transcription_ready
    from clue_api.arv2.gemini_media_client import MediaBudget

    job = ready.for_job(media_budget=MediaBudget(60))
    assert job.media_source_keys.youtube_api_key.get_secret_value() == "yt"
    assert job.transcription_ready
