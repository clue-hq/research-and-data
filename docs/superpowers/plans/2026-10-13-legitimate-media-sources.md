# Research Media From Legitimate Sources — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `read_media` gets a transcript from a publisher transcript, a podcast feed (directly or as
the podcast twin of a YouTube video, transcribed by Deepgram), or Gemini reading the public YouTube
link, and never downloads or scrapes YouTube; production can actually run it.

**Architecture:** The resolver (`media_resolution.resolve`, one synchronous provider hop) keeps its
step-1 logic and gains feed transcripts and publish dates. A new module `media_sources.py` holds
the official/public lookups (YouTube Data API, Apple directory, Podcast Index, episode matching)
and the YouTube resolution that replaces the watch-page scrape. `media_acquisition.acquire`
replaces the yt-dlp download with Gemini in fixed windows for a YouTube candidate. `read_media`
gains an Exa page-links fallback for blocked or JavaScript-built pages. The backend image gains
`ffmpeg`/`ffprobe`; `yt-dlp` leaves the codebase.

**Tech Stack:** Python 3.12, httpx transports behind `ProviderCaller`/`CallSpec` (clue-spend),
pydantic settings/secrets (clue-config), Postgres via SQLAlchemy async, pytest, Docker
(Debian bookworm runtime image).

**Spec:** `docs/superpowers/specs/2026-10-13-legitimate-media-sources-design.md`

## Global Constraints

- Every source is one the publisher made available for that use: a publisher transcript, a podcast feed, a direct media file, or an official API.
- No `yt-dlp` and no scraping of YouTube pages, anywhere (local runs behave like production).
- LinkedIn- and X-native video stay unfetched (ruling 2026-09-03); the refusal tells the agent to look for the same talk elsewhere.
- No third-party transcript API.
- When several episodes could match, the agent chooses from the list; the code never guesses.
- Episode match: published within 7 days of the video, duration within 5% (or 90 seconds), and shared title words.
- Gemini YouTube: public videos only (Data API `privacyStatus == "public"`), paid tier, 40-minute windows (`CLUE_ARV2_MEDIA_GEMINI_WINDOW_SECONDS=2400`), switch `CLUE_ARV2_MEDIA_YOUTUBE_GEMINI_ENABLED` (default `true`), saved as `source_method="gemini_youtube"`.
- Keys travel only in headers the raw sink redacts (`x-goog-api-key`, `authorization`, and `x-auth-key` added here), never in URLs.
- Every new setting is in `libs/clue-config/clue_config/settings.py` or `secrets.py`, `.env` and `.env.example` at the moment it is introduced (env parity rule).
- Tests run only on the throwaway test DB via the scratchpad `pt.sh` (`clue_dushanbe_test`), never with live keys; `*_live.py` is ignored.
- Commits are local only (never push), no AI attribution lines.

## Review Focus

1. A weekly show with two episodes inside the 7-day window and similar lengths: `read_media` must return both for the agent to choose, never pick one. (Task 3 test `test_two_episodes_in_the_window_are_both_returned`.)
2. A feed `pubDate` without a time zone compared with the Data API's UTC timestamp: must compare as UTC, never raise. (Task 3 test `test_naive_feed_dates_compare_as_utc`.)
3. A video longer than what is left of the run's media budget: refused before any window is paid, not cut off after the first. (Task 6 test `test_a_video_over_the_remaining_budget_is_refused_before_any_window`.)
4. Apple or Podcast Index down (5xx, malformed JSON): the read falls through to Gemini with the outage recorded as a gap, never fails the call. (Task 4 test `test_a_directory_outage_falls_through_to_gemini`.)
5. A production worker missing the YouTube key, `ffprobe` or the Deepgram key: an explicit gap naming what is missing, never a stack trace that looks like the agent's fault. (Task 4 test `test_without_a_youtube_key_the_gap_says_so`, Task 6 test `test_a_worker_without_ffprobe_reports_the_media_lane_unavailable`.)

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `libs/clue-config/clue_config/settings.py` | Gemini YouTube switch, window, video prices | Modify |
| `libs/clue-config/clue_config/secrets.py` | YouTube Data API key, Podcast Index key/secret | Modify |
| `libs/clue-spend/clue_spend/sinks.py` | Redact `x-auth-key` | Modify |
| `platform/api/clue_api/arv2/media_types.py` | `Candidate.published_at`, `Candidate.transcript_type` | Modify |
| `platform/api/clue_api/arv2/media_feeds_client.py` | `Episode.transcripts` (`podcast:transcript`); LinkedIn refusal wording | Modify |
| `platform/api/clue_api/arv2/media_resolution.py` | Feed transcripts, `apple_feed_url`, YouTube branch delegates to `media_sources`, keys threaded through `resolve` | Modify |
| `platform/api/clue_api/arv2/media_sources.py` | Official/public lookups, episode matching, `resolve_youtube` | Create |
| `platform/api/clue_api/arv2/gemini_media_client.py` | `transcribe_video` windows (`videoMetadata`, low resolution), `join_windows`, video pricing | Modify |
| `platform/api/clue_api/arv2/media_acquisition.py` | Gemini YouTube route, feed transcript for a chosen candidate, media-lane check, shared save tail | Modify |
| `platform/api/clue_api/arv2/media_tools.py` | Exa page-links fallback, clearer `next_action`s, YouTube details on `unavailable` | Modify |
| `platform/api/clue_api/arv2/media_recording.py` | Remove yt-dlp download | Modify |
| `platform/api/clue_api/arv2/account_research_tools.py` | Remove `media_youtube` transport; legacy YouTube tool refuses | Modify |
| `platform/api/clue_api/arv2/account_research_driver.py` | `_LiveClients.media_source_keys`, `transcription_ready`, video prices; composition warning | Modify |
| `platform/api/clue_api/arv2/media_store.py` | `run_media_summary` | Modify |
| `scripts/arv2_media_report.py` | Per-run media line | Create |
| `platform/api/pyproject.toml`, `uv.lock` | Drop `yt-dlp` | Modify |
| `docker/backend/Dockerfile`, `docker/backend/smoke.sh` | `ffmpeg`/`ffprobe` installed and checked | Modify |
| `.env`, `.env.example` | New settings and secrets | Modify |
| Tests | `tests/arv2/test_media_feed_transcripts.py`, `tests/arv2/test_media_sources.py` (new); `test_media_research.py`, `test_media_source_links.py`, `test_media_store_db.py`, `test_media_recording.py`, `test_account_research_tools.py`, `test_settings.py`, clue-spend sink test (updated) | Create/Modify |

The test runner below is `zsh $S/pt.sh` where
`S=/private/tmp/claude-501/-Users-aryankeshri-conductor-workspaces-research-and-data-dushanbe/03c67e43-6e5f-458f-8b4a-8961a2a699b4/scratchpad`
(it sources `.env`, points `CLUE_DATABASE_URL` at `clue_dushanbe_test`, and ignores `*_live.py`).

---

### Task 1: Settings, secrets, env parity and header redaction

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (after `arv2_media_short_max_seconds`)
- Modify: `libs/clue-config/clue_config/secrets.py` (after `deepgram_api_key`)
- Modify: `libs/clue-spend/clue_spend/sinks.py:53-55`
- Modify: `.env`, `.env.example` (media block near `CLUE_DEEPGRAM_API_KEY`)
- Test: `tests/arv2/test_settings.py`, `tests/arv2/test_media_sources.py` (new, config section)

**Interfaces:**
- Produces: `Settings.arv2_media_youtube_gemini_enabled: bool`, `Settings.arv2_media_gemini_window_seconds: int`, `Settings.arv2_media_video_usd_per_m_input: Decimal`, `Settings.arv2_media_video_usd_per_m_output: Decimal`; `Secrets.youtube_data_api_key`, `Secrets.podcast_index_api_key`, `Secrets.podcast_index_api_secret` (all `SecretStr | None`); `"x-auth-key" in SECRET_HEADERS`.

- [ ] **Step 1: Write the failing tests**

Add to the expected-defaults dict in `tests/arv2/test_settings.py` (next to `arv2_media_short_max_seconds`):

```python
    "arv2_media_youtube_gemini_enabled": True,
    "arv2_media_gemini_window_seconds": 2400,
    "arv2_media_video_usd_per_m_input": Decimal("0.30"),
    "arv2_media_video_usd_per_m_output": Decimal("2.50"),
```

Create `tests/arv2/test_media_sources.py`:

```python
"""Official and public media sources (spec 2026-10-13-legitimate-media-sources-design). Offline."""

from __future__ import annotations

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
```

- [ ] **Step 2: Run them to see them fail**

Run: `zsh $S/pt.sh tests/arv2/test_settings.py tests/arv2/test_media_sources.py`
Expected: FAIL — unknown settings keys, `Secrets` has no `youtube_data_api_key`, `X-Auth-Key` not masked.

- [ ] **Step 3: Implement**

`settings.py`, after `arv2_media_short_max_seconds`:

```python
    # Research media from legitimate sources only (spec
    # docs/superpowers/specs/2026-10-13-legitimate-media-sources-design.md). A public YouTube video
    # is transcribed by Gemini from its link — Google reads the video, nothing is downloaded — in
    # back-to-back windows, so a long video is not cut off at one call's output cap.
    # Env: ``CLUE_ARV2_MEDIA_YOUTUBE_GEMINI_ENABLED`` / ``CLUE_ARV2_MEDIA_GEMINI_WINDOW_SECONDS``.
    arv2_media_youtube_gemini_enabled: bool = True
    arv2_media_gemini_window_seconds: int = Field(default=2400, ge=300, le=3600)
    # Paid-tier price of the video model per million tokens (Gemini 3.5 Flash-Lite, checked
    # 2026-10-13), so YouTube transcription is priced rather than recorded as unpriced.
    # Env: ``CLUE_ARV2_MEDIA_VIDEO_USD_PER_M_INPUT`` / ``CLUE_ARV2_MEDIA_VIDEO_USD_PER_M_OUTPUT``.
    arv2_media_video_usd_per_m_input: Decimal = Field(default=Decimal("0.30"), ge=0)
    arv2_media_video_usd_per_m_output: Decimal = Field(default=Decimal("2.50"), ge=0)
```

`secrets.py`, after `deepgram_api_key`:

```python
    # Env: CLUE_YOUTUBE_DATA_API_KEY. YouTube Data API v3 ``videos.list``: a video's title,
    # channel, date, length and whether it is public. Sent as ``x-goog-api-key`` (redacted).
    youtube_data_api_key: SecretStr | None = None
    # Env: CLUE_PODCAST_INDEX_API_KEY / CLUE_PODCAST_INDEX_API_SECRET. Podcast Index show search;
    # without them only Apple's directory is searched.
    podcast_index_api_key: SecretStr | None = None
    podcast_index_api_secret: SecretStr | None = None
```

`sinks.py`:

```python
SECRET_HEADERS: frozenset[str] = frozenset(
    {"authorization", "x-token", "x-api-key", "x-goog-api-key", "x-goog-upload-url", "x-auth-key"}
)
```

`.env.example` and `.env`, directly after `CLUE_ARV2_DEEPGRAM_MULTI_USD_PER_MINUTE`:

```
# Research media from legitimate sources (spec 2026-10-13). YouTube Data API v3 key (Google
# Cloud console; videos.list costs 1 quota unit). Without it a YouTube link is reported
# unavailable with the gap youtube_data_api_key_missing.
CLUE_YOUTUBE_DATA_API_KEY=
# Podcast Index (free key and secret at api.podcastindex.org); without them only Apple's
# directory is searched for a video's podcast twin.
CLUE_PODCAST_INDEX_API_KEY=
CLUE_PODCAST_INDEX_API_SECRET=
# A public YouTube video with no podcast twin is transcribed by Gemini from its link (paid-tier
# key required), in windows of this many seconds.
CLUE_ARV2_MEDIA_YOUTUBE_GEMINI_ENABLED=true
CLUE_ARV2_MEDIA_GEMINI_WINDOW_SECONDS=2400
# Gemini 3.5 Flash-Lite paid-tier USD per million tokens (checked 2026-10-13).
CLUE_ARV2_MEDIA_VIDEO_USD_PER_M_INPUT=0.30
CLUE_ARV2_MEDIA_VIDEO_USD_PER_M_OUTPUT=2.50
```

- [ ] **Step 4: Run the tests**

Run: `zsh $S/pt.sh tests/arv2/test_settings.py tests/arv2/test_media_sources.py libs/clue-spend/tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add libs/clue-config/clue_config/settings.py libs/clue-config/clue_config/secrets.py libs/clue-spend/clue_spend/sinks.py .env.example tests/arv2/test_settings.py tests/arv2/test_media_sources.py
git commit -m "Media sources: settings and keys for YouTube Data API, Podcast Index and windowed Gemini"
```

---

### Task 2: Podcast feed transcripts and publish dates

**Files:**
- Modify: `platform/api/clue_api/arv2/media_types.py` (`Candidate`)
- Modify: `platform/api/clue_api/arv2/media_feeds_client.py` (`Episode`, `_parse_item`, `PODCAST_NS`)
- Modify: `platform/api/clue_api/arv2/media_resolution.py` (`feed_candidates`, new `preferred_transcript`, `json_transcript`, `html_text`, `publisher_transcript`, `with_feed_transcript`; feed branch of `resolve`)
- Test: `tests/arv2/test_media_feed_transcripts.py` (new)

**Interfaces:**
- Produces: `Candidate.published_at: datetime | None = None`, `Candidate.transcript_type: str | None = None`; `Episode.transcripts: tuple[tuple[str, str], ...] = ()` (url, type); `publisher_transcript(caller, url, declared_type) -> tuple[str, tuple[Segment, ...]]`; `with_feed_transcript(caller, resolution: Resolution) -> Resolution`.

- [ ] **Step 1: Write the failing tests**

```python
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
                '<podcast:transcript url="https://example.com/ep-1.vtt" type="text/vtt"/>'
                '<podcast:transcript url="https://example.com/ep-1.html" type="text/html"/>'
            ),
            response(vtt, "text/vtt"),
        ]
    )
    result = resolve(caller(wire), "https://example.com/feed", hint="ep-1")
    assert result.state == "resolved" and result.transcript == "We buy on evidence."
    assert result.segments[0].timing == "source_supplied" and result.segments[0].speaker == "Host"
    assert result.candidates[0].published_at == datetime(2026, 4, 7, 10, tzinfo=UTC)
    assert [r.url for r in wire.requests][-1] == "https://example.com/ep-1.vtt"


def test_a_json_feed_transcript_keeps_speakers_and_times():
    body = {
        "version": "1.0.0",
        "segments": [
            {"speaker": "Guest", "startTime": 2.5, "endTime": 6.0, "body": "We measure pipeline."}
        ],
    }
    wire = ScriptedTransport(
        [
            feed('<podcast:transcript url="https://example.com/ep-1.json" type="application/json"/>'),
            HttpResponse(200, {"content-type": "application/json"}, json.dumps(body).encode()),
        ]
    )
    result = resolve(caller(wire), "https://example.com/feed", hint="ep-1")
    assert result.transcript == "We measure pipeline."
    assert result.segments[0].time_s == 2.5 and result.segments[0].speaker == "Guest"


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
```

- [ ] **Step 2: Run them to see them fail**

Run: `zsh $S/pt.sh tests/arv2/test_media_feed_transcripts.py`
Expected: FAIL — `Candidate` has no `published_at`; no transcript fetched.

- [ ] **Step 3: Implement**

`media_types.py`, in `Candidate` (add `from datetime import datetime` at the top):

```python
    published_at: datetime | None = None
    transcript_type: str | None = None
```

`media_feeds_client.py`: add next to `ITUNES_NS`

```python
#: The Podcasting 2.0 namespace — where a publisher's own transcript links live.
PODCAST_NS = "https://podcastindex.org/namespace/1.0"
```

add to `Episode` (last field, with default):

```python
    #: ``(url, type)`` of every ``<podcast:transcript>`` the publisher declared, in feed order.
    transcripts: tuple[tuple[str, str], ...] = ()
```

and in `_parse_item`, before building the `Episode`:

```python
    transcripts = tuple(
        (str(node.get("url")), str(node.get("type") or ""))
        for node in item.findall(f"{{{PODCAST_NS}}}transcript")
        if node.get("url")
    )
```

passing `transcripts=transcripts` into the `Episode(...)` call.

`media_resolution.py`: in `feed_candidates`, the RSS branch's `Candidate(...)` gains

```python
                published_at=ep.published_at,
                transcript_url=(chosen := preferred_transcript(ep.transcripts))
                and urljoin(url, chosen[0]),
                transcript_type=chosen[1] if chosen else None,
```

(compute `chosen = preferred_transcript(ep.transcripts)` on the line before the `Candidate(` call
instead of the walrus if ruff objects). Add after `caption_text`:

```python
#: A publisher transcript's formats in the order they are preferred: timed cues first.
TRANSCRIPT_TYPES = (
    "text/vtt",
    "application/x-subrip",
    "application/srt",
    "application/json",
    "text/plain",
    "text/html",
)


def preferred_transcript(transcripts: tuple[tuple[str, str], ...]) -> tuple[str, str] | None:
    """The best declared ``(url, type)``; an unknown type ranks after every known one."""
    if not transcripts:
        return None

    def rank(item: tuple[str, str]) -> int:
        kind = item[1].split(";")[0].strip().lower()
        return TRANSCRIPT_TYPES.index(kind) if kind in TRANSCRIPT_TYPES else len(TRANSCRIPT_TYPES)

    return min(transcripts, key=rank)


def json_transcript(body: str) -> tuple[str, tuple[Segment, ...]]:
    """The Podcasting 2.0 JSON transcript: ``segments[]`` of speaker, startTime, body."""
    data = json.loads(body)
    rows = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("json transcript has no segments")
    parts: list[str] = []
    segments: list[Segment] = []
    cursor = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = canonical_text(str(row.get("body") or "")).strip()
        if not text:
            continue
        if parts:
            parts.append("\n")
            cursor += 1
        start = row.get("startTime")
        speaker = row.get("speaker")
        segments.append(
            Segment(
                start=cursor,
                end=cursor + len(text),
                speaker=str(speaker) if speaker else None,
                attribution="metadata" if speaker else "unknown",
                time_s=float(start) if isinstance(start, int | float) else None,
                timing="source_supplied" if isinstance(start, int | float) else "unavailable",
            )
        )
        parts.append(text)
        cursor += len(text)
    return "".join(parts), tuple(segments)


class _TextOnly(HTMLParser):
    """Visible text of an HTML transcript; script and style bodies are dropped."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag in {"p", "br", "div", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_text(body: str) -> str:
    parser = _TextOnly()
    parser.feed(body)
    return re.sub(r"\n\s*\n+", "\n", "".join(parser.parts)).strip()


def publisher_transcript(
    caller: ProviderCaller, url: str, declared_type: str | None
) -> tuple[str, tuple[Segment, ...]]:
    """Fetch a transcript the publisher declared and read it in its own format."""
    result = fetch(caller, url)
    kind = (declared_type or result.headers.get("content-type", "")).split(";")[0].lower()
    body = result.body.decode("utf-8", errors="replace")
    if kind == "application/json" or body.lstrip().startswith("{"):
        return json_transcript(body)
    if kind == "text/html":
        return caption_text(html_text(body))
    return caption_text(body)


def with_feed_transcript(caller: ProviderCaller, resolution: Resolution) -> Resolution:
    """Use the matched episode's own transcript when the feed declares one; else keep the audio."""
    if resolution.state != "resolved" or resolution.transcript or not resolution.candidates:
        return resolution
    candidate = resolution.candidates[0]
    if not candidate.transcript_url:
        return resolution
    try:
        value, segments = publisher_transcript(
            caller, candidate.transcript_url, candidate.transcript_type
        )
    except (ValueError, KeyError) as exc:
        return replace(resolution, gaps=(*resolution.gaps, f"feed_transcript_unavailable: {exc}"))
    if not value.strip():
        return replace(resolution, gaps=(*resolution.gaps, "feed_transcript_empty"))
    return replace(
        resolution,
        transcript=value,
        segments=segments,
        aliases=tuple(dict.fromkeys((*resolution.aliases, candidate.transcript_url))),
    )
```

In `resolve`, the feed branch becomes:

```python
        return with_feed_transcript(caller, match_episode(feed_candidates(body, url), hint, url))
```

- [ ] **Step 4: Run the tests**

Run: `zsh $S/pt.sh tests/arv2/test_media_feed_transcripts.py tests/arv2/test_media_feeds_client.py tests/arv2/test_media_research.py tests/arv2/test_media_source_links.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/media_types.py platform/api/clue_api/arv2/media_feeds_client.py platform/api/clue_api/arv2/media_resolution.py tests/arv2/test_media_feed_transcripts.py
git commit -m "Media: use a podcast's own transcript when its feed declares one, and keep episode dates"
```

---

### Task 3: Official and public lookups and episode matching (`media_sources.py`)

**Files:**
- Create: `platform/api/clue_api/arv2/media_sources.py`
- Modify: `platform/api/clue_api/arv2/media_resolution.py` (extract `apple_feed_url`)
- Test: `tests/arv2/test_media_sources.py`

**Interfaces:**
- Consumes: `Candidate.published_at` (Task 2), `fetch`, `feed_candidates` from `media_resolution`.
- Produces:
  - `MediaSourceKeys(youtube_api_key, podcast_index_key, podcast_index_secret)`, `NO_KEYS`, `media_keys_of(runtime) -> MediaSourceKeys`
  - `VideoDetails(video_id, title, channel, description, published_at, duration_s, public, live)`
  - `iso_duration_seconds(str) -> int | None`
  - `youtube_details(caller, video_id, api_key) -> VideoDetails`
  - `Show(title, feed_url, source)`; `apple_shows(caller, term) -> list[Show]`; `podcast_index_shows(caller, term, key, secret, *, now=time.time) -> list[Show]`
  - `podcast_links(text) -> list[str]`; `spotify_show_name(html) -> str | None`
  - `same_episode(episode: Candidate, video: VideoDetails) -> bool`
  - `podcast_twin(caller, video, keys, *, visited) -> tuple[list[Candidate], list[str]]`
  - `media_resolution.apple_feed_url(caller, url) -> str | None`

- [ ] **Step 1: Write the failing tests** (append to `tests/arv2/test_media_sources.py`)

```python
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from clue_api.arv2.media_sources import (
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
from clue_api.arv2.media_types import Candidate
from clue_api.arv2.transport import HttpResponse, ScriptedTransport
from tests.arv2.test_media_research import caller, response

VIDEO_ID = "abcdefghijk"


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
    return HttpResponse(
        200, {"content-type": "application/json"}, json.dumps({"items": [item]}).encode()
    )


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
    return base.__class__(**{**base.__dict__, **changes})


def episode(title, published, duration=2470):
    return Candidate(
        url=f"https://example.com/{title}",
        title=title,
        family="audio",
        media_url="https://example.com/a.mp3",
        canonical_key="rss:" + title,
        duration_s=duration,
        published_at=published,
    )


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
    request = wire.requests[0]
    assert "key=" not in request.url and request.headers["x-goog-api-key"] == "yt-key"
    assert "part=snippet,contentDetails,status" in request.url


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


def test_podcast_index_signs_each_request():
    body = {"feeds": [{"title": "Revenue Room", "url": "https://feeds.example.com/rr.xml"}]}
    wire = ScriptedTransport(
        [HttpResponse(200, {"content-type": "application/json"}, json.dumps(body).encode())]
    )
    shows = podcast_index_shows(
        caller(wire), "Revenue Room", SecretStr("key"), SecretStr("secret"), now=lambda: 1700000000
    )
    assert [s.feed_url for s in shows] == ["https://feeds.example.com/rr.xml"]
    headers = wire.requests[0].headers
    expected = hashlib.sha1(b"keysecret1700000000", usedforsecurity=False).hexdigest()
    assert headers["Authorization"] == expected and headers["X-Auth-Date"] == "1700000000"


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
    html = '<meta property="og:description" content="Listen to this episode from Revenue Room on Spotify. More.">'
    assert spotify_show_name(html) == "Revenue Room"
    assert spotify_show_name("<html></html>") is None


def test_same_episode_needs_date_duration_and_title_together():
    day = datetime(2026, 4, 7, 10, tzinfo=UTC)
    assert same_episode(episode("Scaling field ABM with Emily Wall", day), video())
    assert not same_episode(episode("Scaling field ABM with Emily Wall", day - timedelta(days=9)), video())
    assert not same_episode(episode("Scaling field ABM with Emily Wall", day, duration=1800), video())
    assert not same_episode(episode("Quarterly earnings recap", day), video())


def test_naive_feed_dates_compare_as_utc():
    naive = datetime(2026, 4, 7, 10)
    assert same_episode(episode("Scaling field ABM with Emily Wall", naive), video())


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


def apple_lookup():
    body = {"results": [{"collectionId": 123456, "feedUrl": "https://feeds.example.com/rr.xml"}]}
    return HttpResponse(200, {"content-type": "application/json"}, json.dumps(body).encode())


def test_the_description_link_leads_to_the_matching_episode():
    wire = ScriptedTransport(
        [
            apple_lookup(),
            feed_xml(
                ("ep-41", "Scaling field ABM with Emily Wall", "Tue, 07 Apr 2026 10:00:00 GMT", 2470),
                ("ep-40", "Pricing pages", "Tue, 31 Mar 2026 10:00:00 GMT", 2400),
            ),
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
                ("ep-41", "Scaling field ABM with Emily Wall part 1", "Tue, 07 Apr 2026 10:00:00 GMT", 2470),
                ("ep-42", "Scaling field ABM with Emily Wall part 2", "Thu, 09 Apr 2026 10:00:00 GMT", 2480),
            ),
        ]
    )
    details = video(description="https://podcasts.apple.com/us/podcast/rr/id123456")
    matches, _ = podcast_twin(caller(wire), details, MediaSourceKeys(), visited=frozenset())
    assert sorted(m.episode_id for m in matches) == ["ep-41", "ep-42"]


def test_without_links_the_channel_is_searched_in_apples_directory():
    search = {"results": [{"collectionName": "Revenue Room", "feedUrl": "https://feeds.example.com/rr.xml"}]}
    wire = ScriptedTransport(
        [
            HttpResponse(200, {"content-type": "application/json"}, json.dumps(search).encode()),
            feed_xml(("ep-41", "Scaling field ABM with Emily Wall", "Tue, 07 Apr 2026 10:00:00 GMT", 2470)),
        ]
    )
    matches, _ = podcast_twin(caller(wire), video(), MediaSourceKeys(), visited=frozenset())
    assert [m.episode_id for m in matches] == ["ep-41"]
    assert "term=Revenue+Room" in wire.requests[0].url and "media=podcast" in wire.requests[0].url


def test_no_show_found_is_a_gap_not_an_error():
    wire = ScriptedTransport(
        [
            HttpResponse(200, {"content-type": "application/json"}, b'{"results": []}'),
            HttpResponse(200, {"content-type": "application/json"}, b'{"results": []}'),
        ]
    )
    matches, gaps = podcast_twin(caller(wire), video(), MediaSourceKeys(), visited=frozenset())
    assert matches == [] and gaps == ["no_podcast_show_found"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `zsh $S/pt.sh tests/arv2/test_media_sources.py`
Expected: FAIL — `ModuleNotFoundError: clue_api.arv2.media_sources`.

- [ ] **Step 3: Implement**

In `media_resolution.py`, replace the inline Apple branch of `resolve` with a call to a new
function (same behaviour):

```python
def apple_feed_url(caller: ProviderCaller, url: str) -> str | None:
    """The RSS feed Apple's directory lists for a podcasts.apple.com show or episode link."""
    match = re.search(r"/id(\d+)", urlsplit(url).path)
    if not match:
        raise ValueError("apple_show_id_missing")
    lookup = json.loads(
        fetch(caller, f"https://itunes.apple.com/lookup?id={match[1]}&entity=podcast").body
    )
    return next(
        (
            r.get("feedUrl")
            for r in lookup.get("results", [])
            if str(r.get("collectionId")) == match[1] and isinstance(r.get("feedUrl"), str)
        ),
        None,
    )
```

and in `resolve`:

```python
    if urlsplit(url).hostname == "podcasts.apple.com":
        try:
            feed = apple_feed_url(caller, url)
        except ValueError as exc:
            return Resolution("unsupported", gaps=(str(exc),))
        if feed:
            # An Apple episode id is not an RSS guid or an episode number. Unless the feed
            # explicitly links it (or the caller supplied an exact hint), do not guess.
            episode_hint = hint or (url if parse_qs(urlsplit(url).query).get("i") else None)
            return resolve(caller, feed, hint=episode_hint, visited=visited, keys=keys)
        return Resolution("no_match", gaps=("apple_feed_missing",))
```

Create `platform/api/clue_api/arv2/media_sources.py`:

```python
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
from typing import Any
from urllib.parse import quote_plus, urlsplit

from pydantic import SecretStr

from clue_api.arv2.calls import CallSpec, ProviderCaller
from clue_api.arv2.media_types import Candidate
from clue_api.arv2.transport import HttpRequest

YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
APPLE_SEARCH_URL = "https://itunes.apple.com/search"
PODCAST_INDEX_SEARCH_URL = "https://api.podcastindex.org/api/1.0/search/byterm"
USER_AGENT = "CluePodcastResearch/1.0"
#: The match window (spec §3 step 2.4).
EPISODE_DATE_WINDOW = timedelta(days=7)
EPISODE_DURATION_SHARE = 0.05
EPISODE_DURATION_FLOOR_S = 90
#: Feeds read per video; a show search returns its best matches first.
MAX_FEEDS = 3
_STOP_WORDS = frozenset(
    "the and with for from into about how what why who when our your their this that are was "
    "were has have had episode ep part podcast show live video full interview".split()
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
            or "/feed" in path
            or "/rss" in path
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


def same_episode(episode: Candidate, video: VideoDetails) -> bool:
    """Date, duration and title together (spec §3 step 2.4); title words alone never decide."""
    published, posted = _utc(episode.published_at), _utc(video.published_at)
    if published is None or posted is None or abs(published - posted) > EPISODE_DATE_WINDOW:
        return False
    if episode.duration_s and abs(episode.duration_s - video.duration_s) > max(
        EPISODE_DURATION_FLOOR_S, video.duration_s * EPISODE_DURATION_SHARE
    ):
        return False
    ours, theirs = title_words(video.title), title_words(episode.title)
    shared = ours & theirs
    shorter = min(len(ours), len(theirs))
    return len(shared) >= 2 or (shorter > 0 and 2 * len(shared) >= shorter)


def podcast_twin(
    caller: ProviderCaller, video: VideoDetails, keys: MediaSourceKeys, *, visited: frozenset[str]
) -> tuple[list[Candidate], list[str]]:
    """Episodes of a podcast feed that are the same recording as this video, and why not."""
    from clue_api.arv2.media_resolution import apple_feed_url, feed_candidates, fetch

    gaps: list[str] = []
    feeds: list[str] = []
    for link in podcast_links(video.description)[:4]:
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
    if not feeds:
        for term in dict.fromkeys(t.strip() for t in (video.channel, video.title) if t.strip()):
            try:
                shows = apple_shows(caller, term)
                if keys.podcast_index_key and keys.podcast_index_secret:
                    shows += podcast_index_shows(
                        caller, term, keys.podcast_index_key, keys.podcast_index_secret
                    )
            except ValueError as exc:
                gaps.append(f"podcast_directory_unavailable: {exc}")
                continue
            feeds.extend(s.feed_url for s in shows)
            if feeds:
                break
    if not feeds:
        gaps.append("no_podcast_show_found")
        return [], gaps
    matches: dict[str, Candidate] = {}
    for feed in [f for f in dict.fromkeys(feeds) if f not in visited][:MAX_FEEDS]:
        try:
            body = fetch(caller, feed).body.decode("utf-8", errors="replace")
            candidates = feed_candidates(body, feed)
        except (ValueError, ET.ParseError) as exc:
            gaps.append(f"podcast_feed_unreadable: {exc}")
            continue
        for candidate in candidates:
            if same_episode(candidate, video):
                matches[candidate.canonical_key or candidate.url] = candidate
    if not matches:
        gaps.append("no_podcast_episode_match")
    return list(matches.values()), gaps
```

- [ ] **Step 4: Run the tests**

Run: `zsh $S/pt.sh tests/arv2/test_media_sources.py tests/arv2/test_media_research.py tests/arv2/test_media_source_links.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/media_sources.py platform/api/clue_api/arv2/media_resolution.py tests/arv2/test_media_sources.py
git commit -m "Media: find a video's podcast twin through the YouTube Data API, Apple and Podcast Index"
```

---

### Task 4: YouTube resolution without the watch-page scrape

**Files:**
- Modify: `platform/api/clue_api/arv2/media_resolution.py` (`resolve(..., keys=None)`, YouTube branch)
- Modify: `platform/api/clue_api/arv2/media_sources.py` (`resolve_youtube`, `linkedin_profiles`)
- Modify: `platform/api/clue_api/arv2/media_acquisition.py:123-135` (`resolve_url` passes keys)
- Modify: `platform/api/clue_api/arv2/media_feeds_client.py:100-101` (refusal wording)
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` (`_LiveClients` keys)
- Test: `tests/arv2/test_media_sources.py`, `tests/arv2/test_media_source_links.py`

**Interfaces:**
- Consumes: Task 3's `MediaSourceKeys`, `youtube_details`, `podcast_twin`; Task 2's `with_feed_transcript`.
- Produces: `resolve(caller, url, *, hint=None, visited=frozenset(), _response=None, keys: MediaSourceKeys | None = None) -> Resolution`; `resolve_youtube(caller, watch, key, source_url, *, keys, hint, visited) -> Resolution`; `_LiveClients.media_source_keys: MediaSourceKeys` (property). A YouTube candidate with no twin is `Candidate(family="youtube", duration_s=…, published_at=…)` with the podcast gaps on `Resolution.gaps`.

- [ ] **Step 1: Write the failing tests** (append to `tests/arv2/test_media_sources.py`)

```python
from clue_api.arv2.media_resolution import resolve

KEYS = MediaSourceKeys(youtube_api_key=SecretStr("yt-key"))
WATCH = "https://www.youtube.com/watch?v=abcdefghijk"


def test_without_a_youtube_key_the_gap_says_so():
    wire = ScriptedTransport([])
    result = resolve(caller(wire), "https://youtu.be/abcdefghijk")
    assert result.state == "unavailable" and result.gaps == ("youtube_data_api_key_missing",)
    assert wire.requests == []


def test_a_video_with_a_podcast_twin_resolves_to_the_episode():
    wire = ScriptedTransport(
        [
            data_api(),
            apple_lookup(),
            feed_xml(("ep-41", "Scaling field ABM with Emily Wall", "Tue, 07 Apr 2026 10:00:00 GMT", 2470)),
        ]
    )
    result = resolve(caller(wire), "https://youtu.be/abcdefghijk", keys=KEYS)
    assert result.state == "resolved" and result.candidates[0].family == "audio"
    assert result.candidates[0].media_url == "https://example.com/ep-41.mp3"
    assert "https://youtu.be/abcdefghijk" in result.aliases
    assert not any("youtube.com/watch" in r.url for r in wire.requests)


def test_a_video_without_a_twin_resolves_to_a_youtube_candidate_with_its_details():
    wire = ScriptedTransport(
        [
            data_api(snippet={"description": "Talk recorded at HumanX."}),
            HttpResponse(200, {"content-type": "application/json"}, b'{"results": []}'),
            HttpResponse(200, {"content-type": "application/json"}, b'{"results": []}'),
        ]
    )
    result = resolve(caller(wire), WATCH, keys=KEYS)
    candidate = result.candidates[0]
    assert result.state == "resolved" and candidate.family == "youtube"
    assert candidate.duration_s == 2472 and candidate.title.startswith("Scaling field ABM")
    assert "no_podcast_show_found" in result.gaps


def test_an_unlisted_video_is_never_read():
    wire = ScriptedTransport([data_api(status={"privacyStatus": "unlisted"})])
    result = resolve(caller(wire), WATCH, keys=KEYS)
    assert result.state == "unavailable" and result.gaps == ("youtube_not_public",)


def test_a_directory_outage_falls_through_to_gemini():
    wire = ScriptedTransport(
        [
            data_api(snippet={"description": ""}),
            HttpResponse(503, {"content-type": "text/plain"}, b"down"),
            HttpResponse(503, {"content-type": "text/plain"}, b"down"),
            HttpResponse(200, {"content-type": "application/json"}, b"not json"),
            HttpResponse(200, {"content-type": "application/json"}, b"not json"),
        ]
    )
    result = resolve(caller(wire), WATCH, keys=KEYS)
    assert result.state == "resolved" and result.candidates[0].family == "youtube"
    assert any(g.startswith("podcast_directory_unavailable") for g in result.gaps)


def test_the_linkedin_refusal_points_to_other_places():
    from clue_api.arv2.media_feeds_client import UnsupportedMediaHost

    message = str(UnsupportedMediaHost("https://www.linkedin.com/posts/x", "linkedin.com"))
    assert "never fetched" in message and "YouTube" in message and "event" in message
```

(`MAX_ATTEMPTS=2` in `_get_json` makes each 503 consume two scripted responses, which is why the
outage test scripts two per search; if the transport's retry backoff sleeps, the shared `caller`
helper already passes `sleep=lambda _: None`.)

In `tests/arv2/test_media_source_links.py`, the two tests that scripted `youtube_player()` now
script the Data API instead: replace `youtube_player()` with
`tests.arv2.test_media_sources.data_api()` followed by two empty Apple searches, pass
`keys=MediaSourceKeys(youtube_api_key=SecretStr("k"))` to `resolve`, and change the asserted
second request URL from the watch page to `https://www.googleapis.com/youtube/v3/videos?...`.
Delete the `youtube_player` helper.

- [ ] **Step 2: Run them to see them fail**

Run: `zsh $S/pt.sh tests/arv2/test_media_sources.py tests/arv2/test_media_source_links.py`
Expected: FAIL — `resolve()` got an unexpected keyword `keys`; the watch page is still fetched.

- [ ] **Step 3: Implement**

`media_sources.py`, append:

```python
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
    """Spec §3 step 2 for a YouTube link: its podcast twin first, else the video for Gemini."""
    from clue_api.arv2.media_resolution import Resolution, with_feed_transcript

    if keys.youtube_api_key is None:
        return Resolution("unavailable", gaps=("youtube_data_api_key_missing",))
    video = youtube_details(caller, key.removeprefix("youtube:"), keys.youtube_api_key)
    if not video.public:
        return Resolution("unavailable", gaps=("youtube_not_public",))
    if video.live:
        return Resolution("unavailable", gaps=("youtube_live_or_upcoming",))
    matches, gaps = podcast_twin(caller, video, keys, visited=visited)
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
            caller, Resolution("resolved", (twin,), aliases=(source_url, watch))
        )
    if len(matches) > 1:
        return Resolution(
            "ambiguous",
            tuple(matches),
            gaps=("multiple_podcast_episode_matches",),
            aliases=(source_url,),
        )
    return Resolution(
        "resolved",
        (
            Candidate(
                url=watch,
                title=video.title,
                description=video.description[:4000],
                family="youtube",
                canonical_key=key,
                duration_s=video.duration_s,
                published_at=video.published_at,
                identity_evidence=[source_url, "youtube_data_api"],
                recognized_subject_urls=linkedin_profiles(video.description),
            ),
        ),
        gaps=tuple(gaps),
        aliases=(source_url,),
    )
```

`media_resolution.py`: `resolve` gains `keys: MediaSourceKeys | None = None` (import
`MediaSourceKeys` under `TYPE_CHECKING`, from `clue_api.arv2.media_sources`), every recursive
`resolve(...)` call passes `keys=keys`, and the YouTube branch becomes:

```python
    yt = youtube_url(url)
    if yt:
        from clue_api.arv2.media_sources import NO_KEYS, resolve_youtube

        return resolve_youtube(
            caller, yt[0], yt[1], url, keys=keys or NO_KEYS, hint=hint, visited=visited
        )
```

The import of `extract_player_response` from `media_feeds_client` is removed from
`media_resolution.py`.

`media_acquisition.resolve_url`:

```python
async def resolve_url(runtime: Any, url: str, hint: str | None) -> Resolution:
    from clue_api.arv2.media_sources import media_keys_of

    keys_used: list[str] = []
    token = ops.active_resolution.set(keys_used)
    media_keys = media_keys_of(runtime)
    try:
        result = cast(
            Resolution,
            await runtime.call_provider(
                "media_public", lambda caller: resolve(caller, url, hint=hint, keys=media_keys)
            ),
        )
        return replace(result, raw_keys=tuple(keys_used))
    finally:
        ops.active_resolution.reset(token)
```

`media_feeds_client.UnsupportedMediaHost.__init__`:

```python
        super().__init__(
            f"{host} serves only native video, which is never fetched: {url}. Look for the same "
            "talk elsewhere: YouTube, Vimeo, the event's own page or a podcast."
        )
```

`account_research_driver._LiveClients`: constructor gains
`youtube_data_api_key: SecretStr | None = None, podcast_index_api_key: SecretStr | None = None,
podcast_index_api_secret: SecretStr | None = None`, stored and passed through `for_job`, plus

```python
    @property
    def media_source_keys(self) -> MediaSourceKeys:
        return MediaSourceKeys(
            youtube_api_key=self._youtube_data_api_key,
            podcast_index_key=self._podcast_index_api_key,
            podcast_index_secret=self._podcast_index_api_secret,
        )
```

and `build_arv2_account_research_handler` passes `youtube_data_api_key=secrets.youtube_data_api_key,
podcast_index_api_key=secrets.podcast_index_api_key,
podcast_index_api_secret=secrets.podcast_index_api_secret` into `_LiveClients(...)`.

- [ ] **Step 4: Run the tests**

Run: `zsh $S/pt.sh tests/arv2/test_media_sources.py tests/arv2/test_media_source_links.py tests/arv2/test_media_research.py tests/arv2/test_media_feeds_client.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/media_sources.py platform/api/clue_api/arv2/media_resolution.py platform/api/clue_api/arv2/media_acquisition.py platform/api/clue_api/arv2/media_feeds_client.py platform/api/clue_api/arv2/account_research_driver.py tests/arv2/test_media_sources.py tests/arv2/test_media_source_links.py
git commit -m "Media: resolve YouTube through the Data API and its podcast twin, never the watch page"
```

---

### Task 5: Gemini reads a public YouTube link in windows, priced

**Files:**
- Modify: `platform/api/clue_api/arv2/gemini_media_client.py` (`transcribe_video`, `transcribe_native`, `gemini_cost_reader`, new `video_usage_cost`, `join_windows`, `youtube_windows`, client price params)
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` (`_LiveClients.media` passes prices)
- Test: `tests/arv2/test_media_research.py`

**Interfaces:**
- Produces: `GeminiMediaClient.transcribe_video(url, *, duration_s, context, start_s=0, end_s=None) -> Transcript`; `youtube_windows(duration_s: int, window_s: int) -> list[tuple[int, int]]`; `join_windows(parts: Sequence[tuple[int, Transcript]]) -> Transcript`; `GeminiMediaClient(..., video_input_usd_per_1m=Decimal("0.30"), video_output_usd_per_1m=Decimal("2.50"))`; `video_usage_cost(usage, *, input_rate, output_rate) -> Decimal`.

- [ ] **Step 1: Write the failing tests** (in `tests/arv2/test_media_research.py`)

Replace the body of `test_public_video_calls_native_transcription_instead_of_indexed_text` with a
windowed, priced version:

```python
def native_body(text, *, request_id="native-request-1", finish="STOP"):
    return {
        "responseId": request_id,
        "usageMetadata": {"promptTokenCount": 120000, "candidatesTokenCount": 4000},
        "candidates": [{"finishReason": finish, "content": {"parts": [{"text": text}]}}],
    }


def test_public_video_is_read_by_gemini_from_its_link_in_a_window_and_priced():
    wire = ScriptedTransport(
        [HttpResponse(200, body=json.dumps(native_body("## TRANSCRIPT\n[00:03] Guest: We need better evidence.")).encode())]
    )
    ledger = MemoryLedger()
    client = _client(wire, ledger, ceiling_s=3600)
    transcript = client.transcribe_video(
        "https://youtu.be/abcdefghijk",
        duration_s=2400,
        start_s=2400,
        end_s=4800,
        context=SpeakerContext(person_name="Known Guest"),
    )
    request = json.loads(wire.requests[0].body)
    part = request["contents"][0]["parts"][0]
    assert part["fileData"]["fileUri"] == "https://www.youtube.com/watch?v=abcdefghijk"
    assert part["videoMetadata"] == {"startOffset": "2400s", "endOffset": "4800s", "fps": 0.2}
    assert request["generationConfig"]["mediaResolution"] == "MEDIA_RESOLUTION_LOW"
    result = next(row for row in ledger.rows if row.phase == "result")
    # 120,000 input tokens at $0.30/M plus 4,000 output tokens at $2.50/M.
    assert result.cost_usd == Decimal("0.046") and result.media_seconds == 2400
    assert "We need better evidence." in transcript.text


def test_windows_cover_the_whole_video_and_join_in_order():
    from clue_api.arv2.gemini_media_client import Transcript, TranscriptLine, join_windows, youtube_windows

    assert youtube_windows(5000, 2400) == [(0, 2400), (2400, 4800), (4800, 5000)]
    assert youtube_windows(600, 2400) == [(0, 600)]
    first = Transcript(model="m", text="Hello.", lines=(TranscriptLine(5, "Host", "Hello."),))
    second = Transcript(
        model="m", text="Goodbye.", lines=(TranscriptLine(10, "Host", "Goodbye."),), finish_reason="MAX_TOKENS"
    )
    joined = join_windows([(0, first), (2400, second)])
    assert joined.text == "Hello.\nGoodbye."
    assert [line.ts_s for line in joined.lines] == [5, 2410]
    assert joined.finish_reason == "MAX_TOKENS"
```

(add `from decimal import Decimal` to the test imports.) The `_client` helper in this file gains
the default prices automatically from the new constructor defaults.

- [ ] **Step 2: Run them to see them fail**

Run: `zsh $S/pt.sh tests/arv2/test_media_research.py -k "gemini_from_its_link or windows_cover"`
Expected: FAIL — `transcribe_video()` got an unexpected keyword `start_s`; `youtube_windows` missing.

- [ ] **Step 3: Implement**

In `gemini_media_client.py`:

```python
#: Frames per second sent for a YouTube transcript: speech is what matters, frames cost tokens.
YOUTUBE_FPS = 0.2


def youtube_windows(duration_s: int, window_s: int) -> list[tuple[int, int]]:
    """Back-to-back ``(start, end)`` windows covering the whole video."""
    if duration_s <= 0 or window_s <= 0:
        raise ValueError("positive duration and window required")
    return [(start, min(start + window_s, duration_s)) for start in range(0, duration_s, window_s)]


def join_windows(parts: Sequence[tuple[int, Transcript]]) -> Transcript:
    """One transcript from windows in order; each window's timestamps are shifted by its start."""
    if not parts:
        raise ValueError("no windows to join")
    lines: list[TranscriptLine] = []
    quotes: list[QuoteCandidate] = []
    texts: list[str] = []
    finish = "STOP"
    for start, part in parts:
        texts.append(part.text)
        lines.extend(
            replace(line, ts_s=None if line.ts_s is None else line.ts_s + start)
            for line in part.lines
        )
        quotes.extend(
            replace(q, ts_s=None if q.ts_s is None else q.ts_s + start) for q in part.quotes
        )
        if part.finish_reason not in {None, "STOP", "stop"} and finish == "STOP":
            finish = part.finish_reason
    first = parts[0][1]
    return Transcript(
        model=first.model,
        text="\n".join(t for t in texts if t),
        lines=tuple(lines),
        meta=dict(first.meta),
        quotes=tuple(quotes),
        has_timestamps=any(p.has_timestamps for _, p in parts),
        finish_reason=finish,
    )


def video_usage_cost(
    usage: Mapping[str, object], *, input_rate: Decimal, output_rate: Decimal
) -> Decimal:
    """A native video call's price from its own token counts (prompt and output, incl. thinking)."""
    prompt = usage.get("promptTokenCount")
    output = sum(
        value
        for key in ("candidatesTokenCount", "thoughtsTokenCount")
        if isinstance(value := usage.get(key), int)
    )
    prompt_tokens = prompt if isinstance(prompt, int) else 0
    return (
        Decimal(prompt_tokens) / _PER_MILLION * input_rate
        + Decimal(output) / _PER_MILLION * output_rate
    )
```

`gemini_cost_reader(media_seconds, *, model=None, video=False, video_rates=None)`: when `video`
and `video_rates` is given, `cost_usd=video_usage_cost(usage, input_rate=video_rates[0],
output_rate=video_rates[1])` and no `usd_unpriced` extra; otherwise unchanged.

`GeminiMediaClient.__init__` gains keyword parameters
`video_input_usd_per_1m: Decimal = Decimal("0.30")` and `video_output_usd_per_1m: Decimal =
Decimal("2.50")`, stored on `self`.

`transcribe_video` becomes:

```python
    def transcribe_video(
        self,
        url: str,
        *,
        duration_s: int,
        context: SpeakerContext,
        start_s: int = 0,
        end_s: int | None = None,
    ) -> Transcript:
        """Gemini reads a public YouTube link on Google's side; nothing is downloaded.

        ``start_s``/``end_s`` clip one window (``videoMetadata``); ``duration_s`` is that window's
        length, reserved against the media budget and priced from the response's tokens.
        """
        from clue_api.arv2.media_resolution import youtube_url

        normalized = youtube_url(url)
        if normalized is None:
            raise ValueError("public YouTube URL required")
        end = start_s + duration_s if end_s is None else end_s
        return self.transcribe_native(
            normalized[0],
            mime_type="video/mp4",
            duration_s=duration_s,
            context=context,
            video=True,
            video_metadata={"startOffset": f"{start_s}s", "endOffset": f"{end}s", "fps": YOUTUBE_FPS},
        )
```

`transcribe_native` gains `video_metadata: Mapping[str, object] | None = None`; the file part
becomes `{"fileData": {...}, **({"videoMetadata": dict(video_metadata)} if video_metadata else {})}`;
`generationConfig` gains `"mediaResolution": "MEDIA_RESOLUTION_LOW"` when `video`; for `video` the
`SpendEstimate` usd is
`Decimal(duration_s * 100) / _PER_MILLION * self._video_input_usd_per_1m` (about 100 tokens per
second at low resolution), the `extras={"usd_unpriced": True}` stamp is removed, and the cost
reader is `gemini_cost_reader(duration_s, model=model, video=True,
video_rates=(self._video_input_usd_per_1m, self._video_output_usd_per_1m))`.

`_LiveClients.media` passes
`video_input_usd_per_1m=self._settings.arv2_media_video_usd_per_m_input,
video_output_usd_per_1m=self._settings.arv2_media_video_usd_per_m_output`.

- [ ] **Step 4: Run the tests**

Run: `zsh $S/pt.sh tests/arv2/test_media_research.py tests/arv2/test_gemini_media_client.py tests/arv2/test_calls_langfuse.py`
Expected: PASS (`test_calls_langfuse` still sees a native video generation span).

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/gemini_media_client.py platform/api/clue_api/arv2/account_research_driver.py tests/arv2/test_media_research.py
git commit -m "Media: Gemini reads a public YouTube link in back-to-back windows, priced from its tokens"
```

---

### Task 6: Acquisition — Gemini for YouTube, feed transcript for a chosen episode, honest media-lane gaps, no yt-dlp

**Files:**
- Modify: `platform/api/clue_api/arv2/media_acquisition.py` (extract `_save_transcript`, new `_acquire_youtube`, `attach_feed_transcript`, `media_lane_gap`)
- Modify: `platform/api/clue_api/arv2/media_tools.py:181-198` (chosen candidate gets its feed transcript)
- Modify: `platform/api/clue_api/arv2/media_recording.py` (delete `download_youtube`, `YouTubeAudioTransport`, `fetch_youtube`)
- Modify: `platform/api/clue_api/arv2/account_research_tools.py:572-575` (no `media_youtube` transport), `_youtube_hop` (refuses)
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` (`_LiveClients.transcription_ready`; composition warning)
- Modify: `platform/api/pyproject.toml`, `uv.lock` (drop `yt-dlp`)
- Test: `tests/arv2/test_media_store_db.py`, `tests/arv2/test_media_recording.py`, `tests/arv2/test_account_research_tools.py`

**Interfaces:**
- Consumes: Task 4 YouTube candidate (`family="youtube"`, `duration_s`), Task 5 `transcribe_video`, `youtube_windows`, `join_windows`; Task 2 `with_feed_transcript`.
- Produces: `media_lane_gap(runtime) -> str | None`; `attach_feed_transcript(runtime, resolution) -> Resolution`; transcripts saved with `source_method="gemini_youtube"`; `read_media` results for an unreadable YouTube video carry `"video": {"title","channel_or_uploader","published_at","duration_s","description"}` (Task 7 uses it).

- [ ] **Step 1: Write the failing tests** (in `tests/arv2/test_media_store_db.py`)

Replace `video_metadata()` with Data API and Gemini fixtures, give `MediaClients` keys, and rewrite
`test_native_video_hybrid_retrieval_and_cross_job_reuse` for the new route:

```python
class MediaClients:
    media_source_keys = MediaSourceKeys(youtube_api_key=SecretStr("yt-key"))
    transcription_ready = True

    # transcription() and media() unchanged


def youtube_data(duration="PT1M"):
    return json_response(
        {
            "items": [
                {
                    "id": "abcdefghijk",
                    "snippet": {
                        "publishedAt": "2026-04-08T15:00:00Z",
                        "title": "Research interview",
                        "channelTitle": "Interview channel",
                        "description": "",
                        "liveBroadcastContent": "none",
                    },
                    "contentDetails": {"duration": duration},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }
    )


def no_shows():
    return json_response({"results": []})


def gemini_window(text):
    return json_response(
        {
            "responseId": "native-1",
            "usageMetadata": {"promptTokenCount": 6000, "candidatesTokenCount": 200},
            "candidates": [
                {"finishReason": "STOP", "content": {"parts": [{"text": "## TRANSCRIPT\n" + text}]}}
            ],
        }
    )


def test_native_video_hybrid_retrieval_and_cross_job_reuse():
    # (same body as today, with this wire and these assertions)
    wire = ScriptedTransport(
        [
            youtube_data(),
            no_shows(),
            no_shows(),
            gemini_window("[00:05] Guest: We evaluate vendors by evidence quality."),
            embeddings(),
            embeddings(),
        ]
    )
    # ... read_media(url="https://youtu.be/abcdefghijk") ...
    # assert result["index"]["state"] == "ready" and len(wire.requests) == 6
    # assert no request URL contains "youtube.com/watch" and none is a download
    # source_method of the saved version == "gemini_youtube"
    # reuse in the second job: reused and len(wire.requests) == 6 (unchanged)


def test_a_long_video_is_read_in_windows_and_joined():
    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            rt.settings = rt.settings.model_copy(update={"arv2_media_gemini_window_seconds": 2400})
            wire = ScriptedTransport(
                [
                    youtube_data("PT1H10M"),
                    no_shows(),
                    no_shows(),
                    gemini_window("[00:10] Guest: First part."),
                    gemini_window("[00:20] Guest: Second part."),
                    embeddings(),
                ]
            )
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt, ReadMediaArgs(url="https://youtu.be/abcdefghijk", purpose="Long talk")
            )
            assert result["state"] == "available"
            bodies = [json.loads(r.body) for r in wire.requests if ":generateContent" in r.url]
            assert [b["contents"][0]["parts"][0]["videoMetadata"]["startOffset"] for b in bodies] == [
                "0s",
                "2400s",
            ]
            opened = await open_transcript(rt, OpenTranscriptArgs(version_ref=UUID(result["version_ref"])))
            assert "First part." in opened["text"] and "Second part." in opened["text"]

    run_async(scenario())


def test_a_video_over_the_remaining_budget_is_refused_before_any_window():
    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            rt.media_budget.reserve(rt.media_budget.ceiling_s - 60)
            wire = ScriptedTransport([youtube_data("PT10M"), no_shows(), no_shows()])
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt, ReadMediaArgs(url="https://youtu.be/abcdefghijk", purpose="Over budget")
            )
            assert result["state"] == "unavailable"
            assert "media_budget_exhausted" in json.dumps(result)
            assert not any(":generateContent" in r.url for r in wire.requests)

    run_async(scenario())


def test_gemini_switched_off_returns_the_video_details():
    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            rt.settings = rt.settings.model_copy(update={"arv2_media_youtube_gemini_enabled": False})
            wire = ScriptedTransport([youtube_data(), no_shows(), no_shows()])
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt, ReadMediaArgs(url="https://youtu.be/abcdefghijk", purpose="Switched off")
            )
            assert result["state"] == "unavailable"
            assert "youtube_transcription_disabled" in result["gaps"]
            assert result["video"]["title"] == "Research interview"

    run_async(scenario())


def test_a_worker_without_ffprobe_reports_the_media_lane_unavailable(monkeypatch):
    import shutil

    from clue_api.arv2 import media_acquisition

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            monkeypatch.setattr(
                media_acquisition.shutil, "which", lambda name: None if name == "ffprobe" else shutil.which(name)
            )
            feed = """<rss><channel><item><guid>ep-1</guid><title>E</title>
              <enclosure url="https://example.com/a.mp3" type="audio/mpeg"/></item></channel></rss>"""
            wire = ScriptedTransport(
                [HttpResponse(200, {"content-type": "application/rss+xml"}, feed.encode())]
            )
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt, ReadMediaArgs(url="https://example.com/feed", episode_hint="ep-1", purpose="Lane")
            )
            assert result["state"] == "unavailable"
            assert "media_lane_unavailable_on_worker: ffprobe" in json.dumps(result)

    run_async(scenario())
```

(Imports to add at the top of the test file: `json`, `UUID`, `SecretStr`,
`MediaSourceKeys` from `clue_api.arv2.media_sources`, and `OpenTranscriptArgs`, `open_transcript`,
`ReadMediaArgs`, `read_media` from `clue_api.arv2.media_tools`. The `prepared_offline_recording`
autouse fixture stays: it replaces `prepare_audio` for the feed tests, so the ffprobe test above
asserts the lane check runs *before* preparation.)

In `tests/arv2/test_media_recording.py`, delete the `YouTubeAudioTransport` tests and add:

```python
def test_youtube_is_never_downloaded():
    import clue_api.arv2.media_recording as recording

    assert not hasattr(recording, "download_youtube")
    assert not hasattr(recording, "YouTubeAudioTransport")
    assert not hasattr(recording, "fetch_youtube")
```

In `tests/arv2/test_account_research_tools.py`, the legacy YouTube read test asserts the refusal
instead of `youtube_metadata`/`youtube_words` results:
`refusal.code == "youtube_read_retired"` and that no request reached `youtube.com/watch`.

- [ ] **Step 2: Run them to see them fail**

Run: `zsh $S/pt.sh tests/arv2/test_media_store_db.py tests/arv2/test_media_recording.py tests/arv2/test_account_research_tools.py`
Expected: FAIL — acquisition still downloads (`fetch_youtube`), no windows, no lane gap.

- [ ] **Step 3: Implement**

`media_acquisition.py`:

1. Extract the tail of `acquire` (from `value, segments, quality = assess_transcript(transcript)`
   to the `return receipt(...)`) unchanged into

   ```python
   async def _save_transcript(
       runtime: Any,
       *,
       op: dict[str, Any],
       item: dict[str, Any],
       candidate: Candidate,
       resolution: Resolution,
       transcript: Transcript | DeepgramTranscript,
       request: dict[str, Any],
       purpose: str,
       repair_version: UUID | None,
       method: str,
   ) -> dict[str, Any]:
   ```

   using `method` instead of the inline `"publisher_transcript" if resolution.transcript else
   candidate.family`, and call it from `acquire` with that same expression.

2. Add:

   ```python
   def media_lane_gap(runtime: Any) -> str | None:
       """What this worker lacks to transcribe a recording, named, or ``None``."""
       missing = [tool for tool in ("ffprobe", "ffmpeg") if shutil.which(tool) is None]
       if not getattr(runtime.clients, "transcription_ready", True):
           missing.append("Deepgram key")
       return f"media_lane_unavailable_on_worker: {', '.join(missing)} missing" if missing else None


   async def attach_feed_transcript(runtime: Any, resolution: Resolution) -> Resolution:
       """A chosen feed episode still gets its publisher transcript before any audio is bought."""
       candidate = resolution.candidates[0] if resolution.candidates else None
       if candidate is None or not candidate.transcript_url or resolution.transcript:
           return resolution
       return cast(
           Resolution,
           await runtime.call_provider(
               "media_public", lambda caller: with_feed_transcript(caller, resolution)
           ),
       )


   def video_details(candidate: Candidate) -> dict[str, Any]:
       return {
           "title": candidate.title,
           "published_at": candidate.published_at.isoformat() if candidate.published_at else None,
           "duration_s": candidate.duration_s,
           "description": candidate.description[:1200],
           "url": candidate.url,
       }


   async def _acquire_youtube(
       runtime: Any,
       *,
       item: dict[str, Any],
       candidate: Candidate,
       resolution: Resolution,
       purpose: str,
       repair_version: UUID | None,
   ) -> dict[str, Any]:
       """Spec §3 step 3: Gemini reads the public link in windows; nothing is downloaded."""
       if not runtime.settings.arv2_media_youtube_gemini_enabled:
           async with runtime._conn_factory() as conn:
               await store.release_item(runtime, conn, item["item_id"])
           return {
               "state": "unavailable",
               "gap": "youtube_transcription_disabled",
               "video": video_details(candidate),
           }
       duration = candidate.duration_s or 0
       budget = runtime.media_budget
       if duration <= 0 or budget.used_s + duration > budget.ceiling_s:
           async with runtime._conn_factory() as conn:
               await store.release_item(runtime, conn, item["item_id"])
           return {
               "state": "unavailable",
               "gap": "media_budget_exhausted" if duration > 0 else "duration_unknown",
               "video": video_details(candidate),
           }
       windows = youtube_windows(duration, runtime.settings.arv2_media_gemini_window_seconds)
       request = {
           "recipe": "gemini-youtube-v1",
           "model": runtime.settings.arv2_media_video_model,
           "windows": windows,
           "repair": str(repair_version) if repair_version else None,
       }
       async with runtime._conn_factory() as conn:
           op, won = await ops.begin(
               runtime, conn, item_id=item["item_id"], stage="transcribe", request=request,
               seconds=duration,
           )
       if not won:
           if op["state"] == "succeeded" and op["result"].get("version_ref"):
               async with runtime._conn_factory() as conn:
                   await store.consume_reused_item(runtime, conn, item["item_id"])
                   saved = await store.load_transcript(runtime, conn, UUID(op["result"]["version_ref"]))
               return receipt(saved, reused=True)
           return {
               "state": op["state"],
               "operation_ref": str(op["operation_id"]),
               "gap": "acquisition_not_ready_no_automatic_repurchase",
           }
       person = runtime.scope.person_name or ""
       context = SpeakerContext(
           person_name=person,
           person_role=runtime.scope.person_title or "",
           organisation=runtime.scope.account_name or "",
           named_in_metadata=bool(person)
           and person.casefold() in f"{candidate.title} {candidate.description}".casefold(),
       )

       def hop(caller: Any) -> Transcript:
           client = runtime.clients.media(caller, runtime.ledger_of(caller))
           return join_windows(
               [
                   (
                       start,
                       client.transcribe_video(
                           candidate.url,
                           duration_s=end - start,
                           start_s=start,
                           end_s=end,
                           context=context,
                       ),
                   )
                   for start, end in windows
               ]
           )

       transcript = await ops.call(runtime, op, "gemini", hop)
       return await _save_transcript(
           runtime, op=op, item=item, candidate=candidate, resolution=resolution,
           transcript=transcript, request=request, purpose=purpose,
           repair_version=repair_version, method="gemini_youtube",
       )
   ```

3. In `acquire`, after the reuse/repair block and before `language = ...`:

   ```python
       if candidate.family == "youtube" and not resolution.transcript:
           return await _acquire_youtube(
               runtime, item=item, candidate=candidate, resolution=resolution,
               purpose=purpose, repair_version=repair_version,
           )
       if not resolution.transcript and (gap := media_lane_gap(runtime)):
           async with runtime._conn_factory() as conn:
               await store.release_item(runtime, conn, item["item_id"])
           return {"state": "unavailable", "gap": gap}
   ```

   and the download block's condition becomes `if not resolution.transcript and
   candidate.media_url:`, its fetch `fetch(caller, candidate.media_url, binary=True)` under
   provider `"media_public"`; the `fetch_youtube` import is removed. Imports added: `shutil`,
   `SpeakerContext`, `join_windows`, `youtube_windows` from `gemini_media_client`,
   `with_feed_transcript` from `media_resolution`.

`media_tools.read_media`: the chosen-candidate line becomes

```python
                resolved = (
                    await acquisition.attach_feed_transcript(
                        runtime, Resolution("resolved", (selected,))
                    )
                    if selected and target == url
                    else await acquisition.resolve_url(runtime, target, args.episode_hint)
                )
```

and when `acquire` returns a result with `"video"`, the final `unavailable` return carries it
(`video = result.get("video") or video`, initialised `video: dict | None = None`, added to the
returned dict when set).

`media_recording.py`: delete `download_youtube`, `YouTubeAudioTransport`, `fetch_youtube` and their
now-unused imports (`find_spec`, `sys`, `json` if unused, `youtube_url`).

`account_research_tools.py`: delete the `media_youtube` transport branch (lines 572-575); in
`_youtube_hop`'s inner `hop`, replace the body with

```python
        raise RefusalError(
            "youtube_read_retired",
            "YouTube pages are no longer read directly (2026-10-13). Use read_media: it finds the "
            "video's podcast or reads it through the official route.",
        )
```

and drop the `youtube_metadata`/`youtube_words` imports if no longer used.

`account_research_driver._LiveClients`:

```python
    @property
    def transcription_ready(self) -> bool:
        return self._deepgram_api_key is not None and bool(self._deepgram_api_key.get_secret_value())
```

and in `build_arv2_account_research_handler`, after the missing-keys check:

```python
    lane = [t for t in ("ffprobe", "ffmpeg") if shutil.which(t) is None]
    if not _present(secrets.deepgram_api_key):
        lane.append("CLUE_DEEPGRAM_API_KEY")
    if not _present(secrets.youtube_data_api_key):
        lane.append("CLUE_YOUTUBE_DATA_API_KEY")
    if lane:
        log.warning(
            "arv2.media_lane_degraded",
            missing=lane,
            detail="research media reads report these as unavailable on this worker",
        )
```

`platform/api/pyproject.toml`: delete the two `yt-dlp` lines (comment and dependency); run
`uv lock` and check `git diff uv.lock` removes only `yt-dlp` and its exclusive dependencies.

- [ ] **Step 4: Run the tests**

Run: `zsh $S/pt.sh tests/arv2/test_media_store_db.py tests/arv2/test_media_recording.py tests/arv2/test_account_research_tools.py tests/arv2/test_quality_media_db.py tests/arv2/test_media_research.py`
Expected: PASS. Then `grep -rn "yt_dlp\|yt-dlp\|ytInitialPlayerResponse" platform libs` — Expected: no
hits outside comments that state they were removed.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/media_acquisition.py platform/api/clue_api/arv2/media_tools.py platform/api/clue_api/arv2/media_recording.py platform/api/clue_api/arv2/account_research_tools.py platform/api/clue_api/arv2/account_research_driver.py platform/api/pyproject.toml uv.lock tests/arv2/test_media_store_db.py tests/arv2/test_media_recording.py tests/arv2/test_account_research_tools.py
git commit -m "Media: Gemini reads YouTube in windows, yt-dlp removed, and a worker says what it lacks"
```

---

### Task 7: Blocked and JavaScript-built pages, and clearer instructions to the agent

**Files:**
- Modify: `platform/api/clue_api/arv2/media_tools.py` (`page_recordings`, fallback in `read_media`, `next_action` wording)
- Test: `tests/arv2/test_media_store_db.py`

**Interfaces:**
- Consumes: `runtime.operate`, `exa_client.contents_body`, `recording_links`-style classification.
- Produces: `page_recordings(links: list[str]) -> list[str]` (YouTube, audio/video files, feeds, Apple/Spotify links, in page order); `read_media` retries a page that resolved `unsupported` or `HTTP 401/403` through Exa's `/contents` with `extras.links`.

- [ ] **Step 1: Write the failing tests**

```python
def test_page_recordings_keeps_only_recording_links_in_order():
    from clue_api.arv2.media_tools import page_recordings

    links = [
        "https://example.com/about",
        "https://www.youtube.com/embed/abcdefghijk",
        "https://cdn.example.com/talk.mp3",
        "https://podcasts.apple.com/us/podcast/x/id1",
        "https://www.youtube.com/watch?v=abcdefghijk",
    ]
    assert page_recordings(links) == [
        "https://www.youtube.com/watch?v=abcdefghijk",
        "https://cdn.example.com/talk.mp3",
        "https://podcasts.apple.com/us/podcast/x/id1",
    ]


def test_a_blocked_page_is_read_through_exa_and_its_one_recording_is_used():
    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            exa_page = {
                "results": [
                    {
                        "url": "https://events.example.com/talk",
                        "text": "Session page",
                        "extras": {"links": ["https://cdn.example.com/talk.mp3", "https://example.com/about"]},
                    }
                ]
            }
            wire = ScriptedTransport(
                [
                    HttpResponse(403, {"content-type": "text/html"}, b"blocked"),
                    json_response(exa_page),
                    offline_audio(60),
                    deepgram_speech("We hire for evidence."),
                    embeddings(),
                ]
            )
            rt._transport_factory = lambda: wire
            result = await read_media(
                rt, ReadMediaArgs(url="https://events.example.com/talk", purpose="Blocked page")
            )
            assert result["state"] == "available"
            exa = next(r for r in wire.requests if r.url.endswith("/contents"))
            assert json.loads(exa.body)["extras"] == {"links": 200}

    run_async(scenario())


def test_several_recordings_on_a_blocked_page_go_back_to_the_agent():
    # same as above, with two .mp3 links in extras.links
    # assert result["state"] == "ambiguous" and len(result["candidates"]) == 2
    ...


def test_unavailable_tells_the_agent_about_page_transcripts_and_linkedin():
    from clue_api.arv2.media_tools import UNAVAILABLE_NEXT_ACTION

    assert "fetch_page" in UNAVAILABLE_NEXT_ACTION and "podcast" in UNAVAILABLE_NEXT_ACTION
```

(Write the second test in full in the same shape as the first, with
`"extras": {"links": ["https://cdn.example.com/a.mp3", "https://cdn.example.com/b.mp3"]}` and a
wire of `[403 response, json_response(exa_page)]`.)

The Exa client in `MediaClients` needs `exa()`; add:

```python
    def exa(self, caller):
        from pydantic import SecretStr

        from clue_api.arv2.exa_client import ExaClient

        return ExaClient(caller, SecretStr("fixture"))
```

- [ ] **Step 2: Run them to see them fail**

Run: `zsh $S/pt.sh tests/arv2/test_media_store_db.py -k "page_recordings or blocked_page or unavailable_tells"`
Expected: FAIL — `page_recordings` missing; the blocked page ends `unavailable`.

- [ ] **Step 3: Implement**

In `media_tools.py`:

```python
#: Gaps after which the page is worth reading through Exa: blocked, or no recording in plain HTML.
_RETRY_THROUGH_EXA = ("public source HTTP 401", "public source HTTP 403", "no_supported_recording_link")
_RECORDING_SUFFIXES = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac", ".mp4", ".webm", ".mov")

UNAVAILABLE_NEXT_ACTION = (
    "No transcript obtained through this route. The gaps say which step failed. If the page itself "
    "prints a transcript, read it with fetch_page. Look for the same recording as a podcast "
    "episode, on YouTube, or on the event's own page, and pass that link. LinkedIn and X video is "
    "never read: find the same talk elsewhere. An unrecognised link does not prove the recording "
    "is unavailable."
)


def page_recordings(links: list[str]) -> list[str]:
    """Recording links among a page's links, deduplicated (YouTube by video id), in page order."""
    from clue_api.arv2.media_resolution import youtube_url
    from clue_api.arv2.media_sources import podcast_links

    found: list[str] = []
    for link in links:
        try:
            yt = youtube_url(link)
        except ValueError:
            continue
        if yt:
            found.append(yt[0])
        elif urlsplit(link).path.lower().endswith(_RECORDING_SUFFIXES) or podcast_links(link):
            found.append(link)
    return list(dict.fromkeys(found))


async def _links_through_exa(runtime: Any, url: str) -> list[str]:
    from clue_api.arv2.exa_client import contents_body

    body = contents_body([url], text_max_chars=2000, extras={"links": 200})
    _, raw = await runtime.operate(
        "exa",
        "media_page_links",
        body,
        lambda caller: runtime.clients.exa(caller).contents(
            [url], text_max_chars=2000, extras={"links": 200}, label="media.page_links"
        ),
    )
    results = raw.get("results") or []
    extras = (results[0].get("extras") or {}) if results and isinstance(results[0], dict) else {}
    return [str(link) for link in extras.get("links") or [] if isinstance(link, str)]
```

(`from urllib.parse import urlsplit` added to the imports.)

In `read_media`, where `resolved.state != "resolved"` (before recording the resolution attempt):

```python
            if resolved.state in {"unsupported", "unavailable"} and any(
                gap.startswith(_RETRY_THROUGH_EXA) for gap in resolved.gaps
            ):
                recordings = page_recordings(await _links_through_exa(runtime, target))
                if len(recordings) == 1:
                    resolved = await acquisition.resolve_url(runtime, recordings[0], args.episode_hint)
                elif len(recordings) > 1:
                    resolved = Resolution(
                        "ambiguous",
                        tuple(unresolved_recording(link, target, ["exa:links"]) for link in recordings),
                        gaps=("multiple_explicit_recordings",),
                    )
                else:
                    resolved = replace(
                        resolved, gaps=(*resolved.gaps, "no_recording_link_on_page_through_exa")
                    )
```

placed so that an `ambiguous` result flows into the existing ambiguous branch and a `resolved`
one into `acquire` (move the `if resolved.state == "ambiguous":` block after this fallback). Import
`unresolved_recording` from `media_resolution` and `replace` from `dataclasses`. The final
`unavailable` return uses `"next_action": UNAVAILABLE_NEXT_ACTION`.

- [ ] **Step 4: Run the tests**

Run: `zsh $S/pt.sh tests/arv2/test_media_store_db.py tests/arv2/test_quality_media_db.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/media_tools.py tests/arv2/test_media_store_db.py
git commit -m "Media: read blocked or script-built pages through Exa, and tell the agent where else to look"
```

---

### Task 8: The production image can transcribe

**Files:**
- Modify: `docker/backend/Dockerfile` (runtime stage `apt-get install`)
- Modify: `docker/backend/smoke.sh`

**Interfaces:**
- Produces: `ffmpeg` and `ffprobe` on `PATH` for uid 1000 in the backend image; smoke checks named `ffmpeg` and `ffprobe`.

- [ ] **Step 1: Prove the gap on a throwaway container (the failing check)**

Run: `docker run --rm --user 1000:1000 python:3.12-slim-bookworm sh -c 'command -v ffprobe || echo MISSING'`
Expected: `MISSING`.

- [ ] **Step 2: Implement**

Dockerfile runtime stage:

```dockerfile
# ffmpeg/ffprobe: research media prepares every recording for Deepgram with them (spec
# 2026-10-13-legitimate-media-sources-design §4); without them no transcript is ever produced.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates fontconfig libfontconfig1 libstdc++6 \
       libpq5 ffmpeg \
    && rm -rf /var/lib/apt/lists/*
```

smoke.sh, after the `node` check:

```bash
check "ffmpeg" quiet run ffmpeg -version
check "ffprobe" quiet run ffprobe -version
```

- [ ] **Step 3: Verify the package and the uid on the same base image**

Run:
```bash
docker run --rm python:3.12-slim-bookworm sh -c 'apt-get update -qq && apt-get install -y -qq --no-install-recommends ffmpeg >/dev/null && useradd -u 1000 clue && su clue -s /bin/sh -c "ffprobe -version | head -1 && ffmpeg -version | head -1"'
```
Expected: two version lines, no error.

- [ ] **Step 4: Build and smoke the real image (long; run in the background)**

Run: `docker build -f docker/backend/Dockerfile -t clue-backend:media-check . && docker/backend/smoke.sh clue-backend:media-check`
Expected: `SMOKE PASSED` including `ok: ffmpeg` and `ok: ffprobe`. If the build cannot finish on
this machine (the Skia helper stage is very long), record that in the ledger and rely on Step 3.

- [ ] **Step 5: Commit**

```bash
git add docker/backend/Dockerfile docker/backend/smoke.sh
git commit -m "Backend image: install ffmpeg and ffprobe so research media can be transcribed"
```

---

### Task 9: A media line for every run

**Files:**
- Modify: `platform/api/clue_api/arv2/media_store.py` (`run_media_summary`)
- Create: `scripts/arv2_media_report.py`
- Test: `tests/arv2/test_media_store_db.py`

**Interfaces:**
- Produces: `run_media_summary(conn, *, workspace_id: str, run_id: UUID) -> dict[str, Any]` with keys `discovered`, `attempted`, `transcribed` (dict method → count), `unavailable` (dict gap → count).

- [ ] **Step 1: Write the failing test**

```python
def test_run_media_summary_counts_reads_by_method_and_gap():
    from clue_api.arv2.media_store import run_media_summary

    async def scenario():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            rt.clients = MediaClients()
            # one transcribed feed episode (as in test_feed_enclosure_deepgram_whole_recording_and_reuse)
            # and one unavailable read with gaps ["no_supported_recording_link"]
            ...
            summary = await run_media_summary(conn, workspace_id=rt.scope.workspace_id, run_id=rt.scope.run_id)
            assert summary["transcribed"] == {"audio": 1}
            assert summary["unavailable"] == {"no_supported_recording_link": 1}
            assert summary["attempted"] == 2

    run_async(scenario())
```

(Write the setup in full: the feed read reuses the wire from
`test_feed_enclosure_deepgram_whole_recording_and_reuse` with `duration=60`; the unavailable read
is `read_media(url="https://example.com/plain", ...)` with a wire answering
`response("<html><p>No player</p></html>")`, then an Exa answer with no links.)

- [ ] **Step 2: Run it to see it fail**

Run: `zsh $S/pt.sh tests/arv2/test_media_store_db.py -k run_media_summary`
Expected: FAIL — `run_media_summary` missing.

- [ ] **Step 3: Implement**

```python
async def run_media_summary(conn: Any, *, workspace_id: str, run_id: UUID) -> dict[str, Any]:
    """What a run did with media: found, attempted, transcribed by method, unavailable by gap."""
    rows = (
        await conn.execute(
            text("""
        SELECT a.kind, a.outcome, a.data, t.source_method
        FROM arv2_media_attempt a
        JOIN arv2_research_job j ON j.job_id=a.job_id AND j.workspace_id=a.workspace_id
        LEFT JOIN arv2_media_transcript t
          ON t.workspace_id=a.workspace_id AND t.version_id=a.version_id
        WHERE a.workspace_id=:ws AND j.run_id=:run
    """),
            {"ws": workspace_id, "run": run_id},
        )
    ).mappings().all()
    transcribed: dict[str, int] = {}
    unavailable: dict[str, int] = {}
    discovered = attempted = 0
    for row in rows:
        if row["kind"] == "candidate" and row["outcome"] == "unverified":
            discovered += 1
        if row["kind"] != "read":
            continue
        attempted += 1
        if row["outcome"] in {"acquired", "reused"} and row["source_method"]:
            transcribed[row["source_method"]] = transcribed.get(row["source_method"], 0) + 1
        elif row["outcome"] == "unavailable":
            for gap in (decode_jsonb(row["data"]) or {}).get("gaps", []):
                key = str(gap).split(":", 1)[0]
                unavailable[key] = unavailable.get(key, 0) + 1
    return {
        "discovered": discovered,
        "attempted": attempted,
        "transcribed": transcribed,
        "unavailable": unavailable,
    }
```

(`decode_jsonb` from `clue_core` if not already imported in `media_store.py`.)

`scripts/arv2_media_report.py`:

```python
#!/usr/bin/env python3
"""Print one research run's media line (found, attempted, transcribed by method, why not).

    set -a; source .env; set +a
    uv run python scripts/arv2_media_report.py <workspace_id> <run_id>
"""

from __future__ import annotations

import asyncio
import json
import sys
from uuid import UUID

from clue_api.arv2.media_store import run_media_summary
from clue_db import db_lifespan, transaction


async def main(workspace_id: str, run_id: UUID) -> None:
    async with db_lifespan(), transaction() as conn:
        print(json.dumps(await run_media_summary(conn, workspace_id=workspace_id, run_id=run_id), indent=2))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], UUID(sys.argv[2])))
```

- [ ] **Step 4: Run the test**

Run: `zsh $S/pt.sh tests/arv2/test_media_store_db.py -k run_media_summary`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/media_store.py scripts/arv2_media_report.py tests/arv2/test_media_store_db.py
git commit -m "Media: a per-run media line — found, attempted, transcribed by method, and why not"
```

---

### Task 10: Free replay of runs 6 and 7's media links

**Files:**
- Create: scratchpad `media_replay.py` (not committed)

**Interfaces:**
- Consumes: `resolve` with real `ProviderCaller` over `PublicMediaTransport`, `MediaSourceKeys` from the environment.

- [ ] **Step 1: Write and run the replay**

The 14 `read_media` targets of runs 6 and 7 (listed in the 2026-10-13 media investigation:
Twilio podcast page, zkresearch article, schoolonwheels page, podparley episode, WorkOS HumanX
post, divatechtalk ep47, vimeo 823879709, blogtalkradio, mypodcastharmony, the two Apple-hinted
episodes, Outreach Unleash, and the two candidate-ref pages) are resolved through the new
`resolve` with `keys` from `Secrets()`, steps 1–2 only (no Deepgram, no Gemini, no Exa). For each:
state, family, gaps, and whether a podcast twin or publisher transcript was found.

Run: `set -a; source .env; set +a; uv run python $S/media_replay.py > $S/media_replay.txt`
Expected: a table; without `CLUE_YOUTUBE_DATA_API_KEY` the YouTube rows say
`youtube_data_api_key_missing` (recorded, not a failure).

- [ ] **Step 2: Record the numbers in the ledger and the session memory file**

---

### Task 11: Whole-branch verification

- [ ] **Step 1: Full ARV2 suite on the test DB**

Run: `zsh $S/pt.sh tests/arv2 -p no:randomly --tb=line --deselect 'tests/arv2/test_committee_discovery_v2_db.py::test_scripted_agent_account_then_person_depth_channels_receipt_and_erasure' > $S/media_suite.log 2>&1`
Expected: only the pre-existing failures (`test_discovery_driver::…not_composed_without_the_flag_or_the_key` with `.env` loaded). Every other failure is investigated.

- [ ] **Step 2: Lint and types**

Run: `uv run ruff check platform libs scripts tests/arv2 && uv run ruff format --check platform libs scripts tests/arv2 && uv run mypy platform/api/clue_api/arv2/media_sources.py platform/api/clue_api/arv2/media_resolution.py platform/api/clue_api/arv2/media_acquisition.py platform/api/clue_api/arv2/media_tools.py platform/api/clue_api/arv2/gemini_media_client.py platform/api/clue_api/arv2/account_research_driver.py`
Expected: clean.

- [ ] **Step 3: Worker restart and a no-cost smoke**

Restart the lane's fleet workers (`scripts/dev_stack.sh restart-workers` with `.env` sourced) and
confirm the boot log shows `arv2.media_lane_degraded` listing exactly what this machine lacks
(the YouTube key until the founder adds it).

- [ ] **Step 4: Fresh-context review of the whole branch** (superpowers:executing-plans Final Review), fixes with RED→GREEN tests, then the memory file's closing entry.
