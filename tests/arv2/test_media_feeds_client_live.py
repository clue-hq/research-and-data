"""The media client against the real feeds and pages — Global Constraint 3: no replay, no mocks.

Four live proofs, all free except the last: the Boardroom Club feed really carries Sanaz Yashar's
episode at the duration the answer key names, that episode's enclosure really downloads to a
content-addressed MP3, a real YouTube watch page really yields its length, and a real contents
provider really has indexed words for it.

The ~40 MB enclosure download is deliberate and costs nothing: it is the only way to prove the
``binary=True`` path writes a ``.bin`` sidecar and a sha instead of base64-ing audio into JSON.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from clue_api.arv2.calls import CallSpec, ProviderCaller
from clue_api.arv2.media_feeds_client import (
    EnclosureTooLarge,
    UnsupportedMediaHost,
    download_enclosure,
    fetch_feed,
    find_episode,
    reject_native_video,
    youtube_metadata,
    youtube_words,
)
from clue_api.arv2.transport import BROWSER_USER_AGENT, json_request
from clue_config import Secrets
from tests.arv2.conftest import require_secret

#: Global Constraint 11's answer key: the Boardroom Club feed and Sanaz Yashar's episode.
BOARDROOM_RSS = "https://anchor.fm/s/f695d6d8/podcast/rss"
SANAZ_DURATION_S = 2569
SANAZ_ENCLOSURE_PREFIX = "https://anchor.fm/s/f695d6d8/podcast/play/"

#: Nick Fisher's Cocktail Chemistry video (04:14 per the answer key).
COCKTAIL_CHEMISTRY_WATCH = "https://www.youtube.com/watch?v=avcD5WVLCYs"

#: A LinkedIn post carrying native video — the thing that must never be fetched (law 11).
LINKEDIN_NATIVE_VIDEO = (
    "https://www.linkedin.com/posts/cogentsecurity_cogents-head-of-growth-alexander-semien"
    "-activity-7460449"
)

#: Two hundred megabytes: comfortably above a long interview, far below anything a research run
#: should be pulling down by accident.
MAX_ENCLOSURE_BYTES = 200 * 1024 * 1024


def _exa_page_text(
    caller: ProviderCaller, api_key: str
) -> Callable[[Sequence[str]], Mapping[str, str]]:
    """The ten-line ``PageTextFetcher`` this test supplies — the only Exa knowledge in Task 5.

    It goes through the wrapper like every other call, so its raw record and cost row land in the
    same ledger as the free ones. Task 3's Exa client will satisfy the same protocol.
    """

    def fetch(urls: Sequence[str]) -> Mapping[str, str]:
        request = json_request(
            "POST",
            "https://api.exa.ai/contents",
            headers={"x-api-key": api_key, "User-Agent": BROWSER_USER_AGENT},
            json_body={"urls": list(urls), "text": {"maxCharacters": 8000}},
            timeout_s=180.0,
        )
        result = caller.call(
            CallSpec(provider="exa", operation="contents", label="media-words", request=request)
        )
        body = result.json()
        assert isinstance(body, dict)
        print(f"exa /contents cost: {(body.get('costDollars') or {}).get('total')}")
        results = body.get("results") or []
        assert isinstance(results, list)
        return {
            str(item["url"]): str(item.get("text") or "")
            for item in results
            if isinstance(item, dict) and item.get("url")
        }

    return fetch


def test_the_boardroom_feed_yields_sanaz_yashars_episode_at_the_recorded_duration(
    make_caller: Callable[..., ProviderCaller],
) -> None:
    """The answer key, end to end: 65 items, an exact substring match, 42:49, an anchor.fm MP3."""
    caller = make_caller()

    podcast = fetch_feed(BOARDROOM_RSS, caller)

    assert podcast.title
    assert podcast.feed_url == BOARDROOM_RSS
    assert len(podcast.episodes) >= 60, f"feed shrank to {len(podcast.episodes)} items"

    episode = find_episode(podcast, title_contains="Sanaz")
    assert episode is not None, "Sanaz Yashar's episode is no longer in the Boardroom Club feed"
    assert episode.duration_s == SANAZ_DURATION_S
    assert episode.enclosure_url is not None
    assert episode.enclosure_url.startswith(SANAZ_ENCLOSURE_PREFIX)
    print(
        f"feed: {podcast.title!r} episodes={len(podcast.episodes)}\n"
        f"episode: {episode.title!r} number={episode.number} duration_s={episode.duration_s} "
        f"declared_bytes={episode.enclosure_bytes} published={episode.published_at}\n"
        f"enclosure_url: {episode.enclosure_url}"
    )


def test_the_enclosure_downloads_to_a_content_addressed_file_with_a_binary_raw_record(
    make_caller: Callable[..., ProviderCaller], tmp_path: Path
) -> None:
    """The ``binary=True`` path: audio on disk, sha and byte count in the record, no base64."""
    caller = make_caller()
    podcast = fetch_feed(BOARDROOM_RSS, caller)
    episode = find_episode(podcast, title_contains="Sanaz")
    assert episode is not None

    audio = download_enclosure(
        episode, tmp_path / "sanaz-yashar.mp3", caller, max_bytes=MAX_ENCLOSURE_BYTES
    )

    assert audio.path.exists()
    assert audio.bytes > 10 * 1024 * 1024, f"only {audio.bytes} bytes came back"
    assert audio.bytes == audio.path.stat().st_size
    assert len(audio.sha256) == 64
    assert audio.duration_s == SANAZ_DURATION_S
    assert audio.content_type is not None and "audio" in audio.content_type
    print(f"enclosure: bytes={audio.bytes} sha256={audio.sha256} content_type={audio.content_type}")

    raw_records = sorted(Path(".artifacts/arv2/raw/live_http").glob("*.json"))
    assert raw_records, "the binary call wrote no raw record"
    record = json.loads(raw_records[-1].read_text(encoding="utf-8"))
    assert record["response"]["body_sha256"] == audio.sha256
    assert record["response"]["body_bytes"] == audio.bytes
    assert record["response"]["body_text"] is None, "audio must never be inlined into the JSON"
    sidecar = Path(record["response"]["body_path"])
    assert sidecar.exists() and sidecar.suffix == ".bin"
    print(f"raw record: {raw_records[-1]} sidecar={sidecar}")


def test_an_undeclared_enclosure_is_refused_on_a_real_head_before_a_byte_is_downloaded(
    make_caller: Callable[..., ProviderCaller], tmp_path: Path
) -> None:
    """When the feed declares no ``length``, a HEAD reads ``Content-Length`` and refuses there.

    The declared-length precheck only helps when the feed publishes one; most do not. This drops
    the feed's own ``length`` to reproduce that case against the real host, then sets a one-byte
    budget: the refusal must arrive from the HEAD (``declared=True``, no transfer), not from a
    40 MB download nobody wanted.
    """
    caller = make_caller()
    podcast = fetch_feed(BOARDROOM_RSS, caller)
    episode = find_episode(podcast, title_contains="Sanaz")
    assert episode is not None
    undeclared = replace(episode, enclosure_bytes=None)

    with pytest.raises(EnclosureTooLarge) as excinfo:
        download_enclosure(undeclared, tmp_path / "never.mp3", caller, max_bytes=1)

    assert excinfo.value.declared is True, "the refusal came from the HEAD, not from a download"
    assert excinfo.value.size_bytes > 10 * 1024 * 1024
    assert not (tmp_path / "never.mp3").exists()
    print(f"HEAD refused {excinfo.value.size_bytes} bytes against a 1-byte budget")


def test_a_real_watch_page_yields_its_title_and_length(
    make_caller: Callable[..., ProviderCaller],
) -> None:
    """The watch page's own ``ytInitialPlayerResponse``: no API key, no caption endpoint."""
    caller = make_caller()

    meta = youtube_metadata(COCKTAIL_CHEMISTRY_WATCH, caller)

    assert meta.video_id == "avcD5WVLCYs"
    assert meta.title
    assert meta.length_s is not None
    assert 250 <= meta.length_s <= 260, f"answer key says 04:14, page says {meta.length_s}"
    print(f"youtube: id={meta.video_id} title={meta.title!r} length_s={meta.length_s}")


def test_indexed_page_text_comes_back_for_a_real_watch_page(
    make_caller: Callable[..., ProviderCaller], live_secrets: Secrets
) -> None:
    """The caption fallback over a real contents provider, through the wrapper like everything."""
    api_key = require_secret(live_secrets, "exa_api_key")
    caller = make_caller()

    words = youtube_words(
        COCKTAIL_CHEMISTRY_WATCH, _exa_page_text(caller, api_key), title="Cocktail Chemistry"
    )

    assert words.url == COCKTAIL_CHEMISTRY_WATCH
    assert words.title == "Cocktail Chemistry"
    assert words.text.strip(), "the contents provider returned no indexed text at all"
    print(f"indexed text: {len(words.text)} chars; head={words.text[:120]!r}")


def test_a_linkedin_native_video_is_refused_before_anything_is_fetched() -> None:
    """Law 11's walled-media clause. No caller is involved: the refusal precedes the wire."""
    with pytest.raises(UnsupportedMediaHost) as raised:
        reject_native_video(LINKEDIN_NATIVE_VIDEO)

    assert raised.value.host == "linkedin.com"
