"""Regression shapes observed in the saved Oktane and podcast pages; no live calls."""

from pydantic import SecretStr

from clue_api.arv2.media_resolution import resolve
from clue_api.arv2.media_sources import MediaSourceKeys
from clue_api.arv2.transport import ScriptedTransport
from tests.arv2.test_media_research import caller, response
from tests.arv2.test_media_sources import data_api, empty_search


def test_analytics_frame_and_duplicate_youtube_forms_are_not_recording_choices():
    page = """<iframe src="https://www.youtube.com/embed/abcdefghijk"></iframe>
    <iframe src="https://www.googletagmanager.com/ns.html?id=GTM-example"></iframe>
    <iframe src="about:blank"></iframe>
    <meta property="og:video" content="https://www.youtube.com/watch?v=abcdefghijk">"""
    wire = ScriptedTransport(
        [response(page), data_api(snippet={"description": ""}), empty_search(), empty_search()]
    )
    keys = MediaSourceKeys(youtube_api_key=SecretStr("k"))
    result = resolve(caller(wire), "https://example.com/interview", keys=keys)
    assert result.state == "resolved"
    assert result.candidates[0].family == "youtube"
    assert len(wire.requests) == 4
    assert wire.requests[1].url.startswith("https://www.googleapis.com/youtube/v3/videos?")
    assert not any("youtube.com/watch" in r.url for r in wire.requests)
    assert "html:iframe:src" in result.candidates[0].identity_evidence
    assert "html:meta:og:video" in result.candidates[0].identity_evidence


def test_declared_twitter_stream_resolves_without_fetching_its_player():
    page = """<meta name="twitter:player" content="https://example.com/player/42">
    <meta name="twitter:player:stream" content="https://cdn.example.com/42.mp3?x=1&amp;y=2">
    <meta name="twitter:player:stream:content_type" content="audio/mpeg">"""
    wire = ScriptedTransport([response(page), response("recording", "audio/mpeg")])
    result = resolve(caller(wire), "https://example.com/episode")
    assert result.state == "resolved"
    assert result.candidates[0].media_url == "https://cdn.example.com/42.mp3?x=1&y=2"
    assert "html:meta:twitter:player:stream" in result.candidates[0].identity_evidence
    assert len(wire.requests) == 2


def test_genuine_audio_video_choices_retain_types_origins_and_allow_selection():
    page = """<audio src="https://cdn.example.com/one.mp3"></audio>
    <iframe src="https://www.youtube.com/embed/abcdefghijk"></iframe>"""
    wire = ScriptedTransport([response(page), response("recording", "audio/mpeg")])
    calls = caller(wire)
    result = resolve(calls, "https://example.com/interview")
    assert result.state == "ambiguous"
    assert [c.family for c in result.candidates] == ["audio", "youtube"]
    assert result.candidates[0].identity_evidence == [
        "explicit_embed:https://example.com/interview",
        "html:audio:src",
    ]
    assert len(wire.requests) == 1  # no arbitrary choice/purchase
    selected = resolve(calls, result.candidates[0].url)
    assert selected.state == "resolved" and selected.candidates[0].family == "audio"


def test_player_metadata_and_unknown_publisher_embed_remain_discoverable():
    page = """<meta name="twitter:player" content="/player">
    <iframe src="https://publisher.example.com/alternate-player"></iframe>"""
    result = resolve(caller(ScriptedTransport([response(page)])), "https://example.com/show")
    assert result.state == "ambiguous"
    assert {c.url for c in result.candidates} == {
        "https://example.com/player",
        "https://publisher.example.com/alternate-player",
    }


def test_open_graph_audio_is_recording_not_transcript_or_page_description():
    page = """<meta property="og:audio:secure_url" content="/one.m4a">
    <meta property="og:description" content="A discussion about research">"""
    result = resolve(
        caller(ScriptedTransport([response(page), response("recording", "audio/mp4")])),
        "https://example.com/show",
    )
    assert result.state == "resolved" and result.transcript is None
    assert result.candidates[0].media_url == "https://example.com/one.m4a"
