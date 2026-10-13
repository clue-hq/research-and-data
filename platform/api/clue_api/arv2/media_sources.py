"""Official and public sources that turn a recording into something we may legitimately read.

Spec: docs/superpowers/specs/2026-10-13-legitimate-media-sources-design.md §3 step 2. Every call is
to an official API or a public directory: the YouTube Data API for a video's details, Apple's
podcast directory and Podcast Index for its show, and the show's own RSS feed for the episode.
Nothing here downloads or scrapes YouTube. Keys travel in headers the raw sink redacts.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from itertools import zip_longest
from typing import Any, Literal
from urllib.parse import quote_plus, urlsplit

from pydantic import SecretStr

from clue_api.arv2.calls import CallSpec, ProviderCaller
from clue_api.arv2.errors import ProviderTransportError, RawParseError
from clue_api.arv2.media_types import Candidate
from clue_api.arv2.transport import HttpRequest

YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
APPLE_SEARCH_URL = "https://itunes.apple.com/search"
PODCAST_INDEX_SEARCH_URL = "https://api.podcastindex.org/api/1.0/search/byterm"
USER_AGENT = "CluePodcastResearch/1.0"
#: The episode match (spec §3 step 2.4): published within a week of the video, the same length
#: within 5% (or 90 seconds), and shared title words. Title words alone never decide.
EPISODE_DATE_WINDOW = timedelta(days=7)
EPISODE_DURATION_SHARE = 0.05
EPISODE_DURATION_FLOOR_S = 90
#: Description links followed, and feeds read, per video.
MAX_LINKS = 4
MAX_FEEDS = 3
_STOP_WORDS = frozenset(
    [
        "the",
        "and",
        "with",
        "for",
        "from",
        "into",
        "about",
        "how",
        "what",
        "why",
        "who",
        "when",
        "our",
        "your",
        "their",
        "this",
        "that",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "episode",
        "ep",
        "part",
        "podcast",
        "show",
        "live",
        "video",
        "full",
        "interview",
    ]
)


@dataclass(frozen=True)
class MediaSourceKeys:
    youtube_api_key: SecretStr | None = None
    podcast_index_key: SecretStr | None = None
    podcast_index_secret: SecretStr | None = None


NO_KEYS = MediaSourceKeys()


def media_keys_of(runtime: Any) -> MediaSourceKeys:
    """The job's keys; a runtime built on fake clients (tests, tools) has none."""
    keys = getattr(runtime.clients, "media_source_keys", None)
    return keys if isinstance(keys, MediaSourceKeys) else NO_KEYS


@dataclass(frozen=True)
class VideoDetails:
    video_id: str
    title: str
    channel: str
    description: str
    published_at: datetime | None
    duration_s: int
    public: bool
    live: bool


@dataclass(frozen=True)
class Show:
    title: str
    feed_url: str
    source: str


_ISO_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?")


def iso_duration_seconds(value: str) -> int | None:
    match = _ISO_DURATION.fullmatch(value or "")
    if not match or not any(match.groups()):
        return None
    days, hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _get_json(
    caller: ProviderCaller,
    *,
    provider: str,
    operation: str,
    label: str,
    url: str,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One free GET to an official API. Any failure is a ``ValueError`` the caller records as a
    gap; only a provider halt (money truth) propagates."""
    try:
        result = caller.call(
            CallSpec(
                provider=provider,
                operation=operation,
                label=label,
                request=HttpRequest(
                    "GET", url, headers={"User-Agent": USER_AGENT, **(headers or {})}, timeout_s=30
                ),
                max_attempts=2,
            )
        )
    except ProviderTransportError as exc:
        raise ValueError(f"{provider} unreachable") from exc
    if not 200 <= result.response.status < 300:
        raise ValueError(f"{provider} HTTP {result.response.status}")
    try:
        body = json.loads(result.response.body)
    except ValueError as exc:
        raise ValueError(f"{provider} answered with invalid JSON") from exc
    if not isinstance(body, dict):
        raise ValueError(f"{provider} answered with no JSON object")
    return body


def youtube_details(caller: ProviderCaller, video_id: str, api_key: SecretStr) -> VideoDetails:
    """A video's details from the official YouTube Data API (``videos.list``, one quota unit)."""
    body = _get_json(
        caller,
        provider="youtube_data",
        operation="videos.list",
        label="media.youtube_details",
        url=f"{YOUTUBE_VIDEOS_URL}?part=snippet,contentDetails,status&id={video_id}",
        headers={"x-goog-api-key": api_key.get_secret_value()},
    )
    items = body.get("items") or []
    if not items or not isinstance(items[0], dict):
        raise ValueError("youtube_video_not_found")
    item = items[0]
    snippet = item.get("snippet") or {}
    duration = iso_duration_seconds(str((item.get("contentDetails") or {}).get("duration") or ""))
    if not duration:
        raise ValueError("youtube_duration_unknown")
    return VideoDetails(
        video_id=video_id,
        title=str(snippet.get("title") or ""),
        channel=str(snippet.get("channelTitle") or ""),
        description=str(snippet.get("description") or ""),
        published_at=_iso_datetime(snippet.get("publishedAt")),
        duration_s=duration,
        public=(item.get("status") or {}).get("privacyStatus") == "public",
        live=snippet.get("liveBroadcastContent") in {"live", "upcoming"},
    )


def apple_shows(caller: ProviderCaller, term: str, *, limit: int = 5) -> list[Show]:
    """Shows in Apple's public podcast directory (iTunes Search API; free, no key)."""
    body = _get_json(
        caller,
        provider="apple_podcasts",
        operation="search",
        label="media.podcast_search",
        url=f"{APPLE_SEARCH_URL}?media=podcast&entity=podcast&limit={limit}&term={quote_plus(term)}",
    )
    return [
        Show(str(r.get("collectionName") or ""), r["feedUrl"], "apple")
        for r in body.get("results", [])
        if isinstance(r, dict) and isinstance(r.get("feedUrl"), str)
    ]


def podcast_index_shows(
    caller: ProviderCaller,
    term: str,
    key: SecretStr,
    secret: SecretStr,
    *,
    now: Callable[[], float] = time.time,
    limit: int = 5,
) -> list[Show]:
    """Shows in Podcast Index. Each request is signed with sha1(key + secret + unix time)."""
    stamp = str(int(now()))
    digest = hashlib.sha1(
        (key.get_secret_value() + secret.get_secret_value() + stamp).encode(),
        usedforsecurity=False,
    ).hexdigest()
    body = _get_json(
        caller,
        provider="podcast_index",
        operation="search/byterm",
        label="media.podcast_search",
        url=f"{PODCAST_INDEX_SEARCH_URL}?max={limit}&q={quote_plus(term)}",
        headers={
            "X-Auth-Key": key.get_secret_value(),
            "X-Auth-Date": stamp,
            "Authorization": digest,
        },
    )
    return [
        Show(str(f.get("title") or ""), f["url"], "podcast_index")
        for f in body.get("feeds", [])
        if isinstance(f, dict) and isinstance(f.get("url"), str)
    ]


_URL = re.compile(r"https?://[^\s<>()\"']+")
#: A "/feed" or "/rss" path segment ("/feed", "/rss/", "/podcast/feed.xml"), never "/feedback".
_FEED_SEGMENT = re.compile(r"/(?:feed|rss)(?:[/.]|$)")


def podcast_links(text: str) -> list[str]:
    """Podcast links in a description: Apple, Spotify show/episode pages, and RSS feeds."""
    found: list[str] = []
    for raw in _URL.findall(text or ""):
        url = raw.rstrip(".,;:!?")
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        path = parts.path.lower()
        if (
            host == "podcasts.apple.com"
            or (host == "open.spotify.com" and path.startswith(("/show/", "/episode/")))
            or path.endswith((".rss", ".xml"))
            or _FEED_SEGMENT.search(path)
        ):
            found.append(url)
    return list(dict.fromkeys(found))


class _Meta(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            a = dict(attrs)
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.values.setdefault(key, a["content"] or "")


def spotify_show_name(html: str) -> str | None:
    """Spotify's public episode page names its show; the audio itself is DRM and never read."""
    parser = _Meta()
    parser.feed(html)
    match = re.search(
        r"episode from (.+?) on Spotify", parser.values.get("og:description", ""), re.I
    )
    return match[1].strip() if match else None


def title_words(text: str) -> frozenset[str]:
    return frozenset(
        w for w in re.findall(r"[a-z0-9]+", text.casefold()) if len(w) >= 3 and w not in _STOP_WORDS
    )


def episode_match(episode: Candidate, video: VideoDetails) -> Literal["match", "possible"] | None:
    """Spec §3 step 2.4: date, duration and title together make a ``match``; title words alone
    never decide. An episode whose feed gives no duration can only be ``possible``: it goes back
    to the agent to choose, never used automatically."""
    published, posted = _utc(episode.published_at), _utc(video.published_at)
    if published is None or posted is None or abs(published - posted) > EPISODE_DATE_WINDOW:
        return None
    ours, theirs = title_words(video.title), title_words(episode.title)
    shared = ours & theirs
    shorter = min(len(ours), len(theirs))
    if not (len(shared) >= 2 or (shorter > 0 and 2 * len(shared) >= shorter)):
        return None
    if not episode.duration_s:
        return "possible"
    tolerance = max(EPISODE_DURATION_FLOOR_S, video.duration_s * EPISODE_DURATION_SHARE)
    return "match" if abs(episode.duration_s - video.duration_s) <= tolerance else None


def same_episode(episode: Candidate, video: VideoDetails) -> bool:
    return episode_match(episode, video) == "match"


def _feeds_from_links(caller: ProviderCaller, video: VideoDetails, gaps: list[str]) -> list[str]:
    from clue_api.arv2.media_resolution import apple_feed_url, fetch

    feeds: list[str] = []
    for link in podcast_links(video.description)[:MAX_LINKS]:
        host = urlsplit(link).hostname
        try:
            if host == "podcasts.apple.com":
                if feed := apple_feed_url(caller, link):
                    feeds.append(feed)
            elif host == "open.spotify.com":
                name = spotify_show_name(fetch(caller, link).body.decode("utf-8", "replace"))
                if name:
                    feeds.extend(s.feed_url for s in apple_shows(caller, name)[:2])
            else:
                feeds.append(link)
        except ValueError as exc:
            gaps.append(f"podcast_link_unreadable: {exc}")
    return feeds


def _feeds_from_directories(
    caller: ProviderCaller, video: VideoDetails, keys: MediaSourceKeys, gaps: list[str]
) -> list[str]:
    """Shows found by the channel name and by the video title, taken in turn from each search so
    unrelated hits for one term cannot crowd out the other's within :data:`MAX_FEEDS`."""
    found: list[list[str]] = []
    for term in dict.fromkeys(t.strip() for t in (video.channel, video.title) if t.strip()):
        try:
            found.append([s.feed_url for s in apple_shows(caller, term)])
        except ValueError as exc:
            gaps.append(f"podcast_directory_unavailable: {exc}")
        if keys.podcast_index_key and keys.podcast_index_secret:
            try:
                found.append(
                    [
                        s.feed_url
                        for s in podcast_index_shows(
                            caller, term, keys.podcast_index_key, keys.podcast_index_secret
                        )
                    ]
                )
            except ValueError as exc:
                gaps.append(f"podcast_directory_unavailable: {exc}")
    return [feed for rank in zip_longest(*found) for feed in rank if feed is not None]


def podcast_twin(
    caller: ProviderCaller, video: VideoDetails, keys: MediaSourceKeys, *, visited: frozenset[str]
) -> tuple[list[Candidate], list[Candidate], list[str]]:
    """Feed episodes that are the same recording as this video (``match``), episodes that could be
    but whose feed gives no duration (``possible``), and the gaps met on the way."""
    from clue_api.arv2.media_resolution import feed_candidates, fetch

    gaps: list[str] = []
    feeds = _feeds_from_links(caller, video, gaps) or _feeds_from_directories(
        caller, video, keys, gaps
    )
    if not feeds:
        gaps.append("no_podcast_show_found")
        return [], [], gaps
    matches: dict[str, Candidate] = {}
    possible: dict[str, Candidate] = {}
    for feed in [f for f in dict.fromkeys(feeds) if f not in visited][:MAX_FEEDS]:
        try:
            body = fetch(caller, feed).body.decode("utf-8", errors="replace")
            candidates = feed_candidates(body, feed)
        except (ValueError, ET.ParseError, RawParseError) as exc:
            gaps.append(f"podcast_feed_unreadable: {exc}")
            continue
        for candidate in candidates:
            verdict = episode_match(candidate, video)
            if verdict == "match":
                matches[candidate.canonical_key or candidate.url] = candidate
            elif verdict == "possible":
                possible[candidate.canonical_key or candidate.url] = candidate
    if not matches and not possible:
        gaps.append("no_podcast_episode_match")
    return list(matches.values()), list(possible.values()), gaps


_LINKEDIN_PROFILE = re.compile(r"https://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?")


def linkedin_profiles(text: str) -> list[str]:
    return list(dict.fromkeys(_LINKEDIN_PROFILE.findall(text or "")))


def resolve_youtube(
    caller: ProviderCaller,
    watch: str,
    key: str,
    source_url: str,
    *,
    keys: MediaSourceKeys,
    hint: str | None,
    visited: frozenset[str],
) -> Any:
    """Spec §3 step 2 for a YouTube link: its podcast twin first, else the video for Gemini.

    The video's details come from the official Data API, never the watch page. ``hint`` is
    unused: a twin is matched on the video's own date, length and title, never a guess.
    """
    from clue_api.arv2.media_resolution import Resolution, with_feed_transcript

    del hint
    if keys.youtube_api_key is None:
        return Resolution("unavailable", gaps=("youtube_data_api_key_missing",))
    video = youtube_details(caller, key.removeprefix("youtube:"), keys.youtube_api_key)
    found = Candidate(
        url=watch,
        title=video.title,
        description=video.description[:4000],
        family="youtube",
        canonical_key=key,
        duration_s=video.duration_s,
        published_at=video.published_at,
        identity_evidence=[source_url, "youtube_data_api"],
        recognized_subject_urls=linkedin_profiles(video.description),
    )
    # An unreadable video still answers with its details: the agent can look for it elsewhere.
    if not video.public:
        return Resolution("unavailable", (found,), gaps=("youtube_not_public",))
    if video.live:
        return Resolution("unavailable", (found,), gaps=("youtube_live_or_upcoming",))
    matches, possible, gaps = podcast_twin(caller, video, keys, visited=visited)
    if len(matches) == 1:
        twin = matches[0].model_copy(
            update={
                "identity_evidence": [
                    *matches[0].identity_evidence,
                    f"podcast_twin_of:{watch}",
                    "matched_on:date,duration,title",
                ]
            }
        )
        return with_feed_transcript(
            caller,
            Resolution("resolved", (twin,), aliases=tuple(dict.fromkeys((source_url, watch)))),
        )
    if len(matches) > 1:
        return Resolution(
            "ambiguous",
            tuple(matches),
            gaps=("multiple_podcast_episode_matches",),
            aliases=(source_url,),
        )
    if possible:
        # Date and title fit but the feed gives no length: the agent chooses, the code never does.
        return Resolution(
            "ambiguous",
            tuple(possible),
            gaps=("podcast_episode_duration_unknown",),
            aliases=(source_url,),
        )
    return Resolution("resolved", (found,), gaps=tuple(gaps), aliases=(source_url,))
