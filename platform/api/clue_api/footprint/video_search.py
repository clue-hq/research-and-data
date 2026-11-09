"""Find videos a person may appear in: YouTube search by quoted name, then each hit's details.

``search.list`` costs 100 of the free 10,000 daily quota units, so about 100 searches a day. When
the quota is gone (or no key is configured) the caller's Exa search is used instead, and the
result says so. Each hit comes back with its full description, tags, channel and length for the
agent to judge before transcribing; nothing is filtered here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlencode

from pydantic import BaseModel, Field

from clue_api.footprint.media_resolution import youtube_url
from clue_api.footprint.media_sources import (
    _URL,
    USER_AGENT,
    YOUTUBE_VIDEOS_URL,
    MediaSourceKeys,
    iso_duration_seconds,
)
from clue_spend.calls import CallSpec, ProviderCaller
from clue_spend.errors import ProviderTransportError
from clue_spend.transport import HttpRequest

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


class VideoLead(BaseModel):
    video_id: str
    url: str
    title: str | None = None
    channel: str | None = None
    published_at: datetime | None = None
    duration_s: int | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    source: Literal["youtube", "exa"]


class _QuotaExhausted(Exception):
    pass


def _youtube(caller: ProviderCaller, key: str, url: str, operation: str) -> dict[str, Any]:
    try:
        result = caller.call(
            CallSpec(
                provider="youtube_data",
                operation=operation,
                label="footprint.find_videos",
                request=HttpRequest(
                    "GET",
                    url,
                    headers={"User-Agent": USER_AGENT, "x-goog-api-key": key},
                    timeout_s=30,
                ),
                max_attempts=2,
            )
        )
    except ProviderTransportError as exc:
        raise ValueError("youtube_data unreachable") from exc
    status = result.response.status
    try:
        body = json.loads(result.response.body) if result.response.body else {}
    except ValueError:
        body = {}
    if status == 403 and "quotaExceeded" in json.dumps(body):
        raise _QuotaExhausted
    if not 200 <= status < 300 or not isinstance(body, dict):
        raise ValueError(f"youtube_data HTTP {status}")
    return body


def _details(caller: ProviderCaller, key: str, ids: list[str]) -> dict[str, VideoLead]:
    out: dict[str, VideoLead] = {}
    for start in range(0, len(ids), 50):
        chunk = ids[start : start + 50]
        query = urlencode({"part": "snippet,contentDetails", "id": ",".join(chunk)})
        body = _youtube(caller, key, f"{YOUTUBE_VIDEOS_URL}?{query}", "videos.list")
        for item in body.get("items") or []:
            snippet = item.get("snippet") or {}
            description = str(snippet.get("description") or "")
            published = snippet.get("publishedAt")
            out[item["id"]] = VideoLead(
                video_id=item["id"],
                url=f"https://www.youtube.com/watch?v={item['id']}",
                title=snippet.get("title"),
                channel=snippet.get("channelTitle"),
                published_at=datetime.fromisoformat(published.replace("Z", "+00:00"))
                if isinstance(published, str)
                else None,
                duration_s=iso_duration_seconds(
                    str((item.get("contentDetails") or {}).get("duration") or "")
                ),
                description=description,
                tags=[str(t) for t in snippet.get("tags") or []],
                links=list(dict.fromkeys(u.rstrip(".,;:!?") for u in _URL.findall(description))),
                source="youtube",
            )
    return out


def _video_id(url: str) -> str | None:
    try:
        found = youtube_url(url)
    except ValueError:
        return None
    return found[1].removeprefix("youtube:") if found else None


def _from_exa(
    caller: ProviderCaller,
    key: str | None,
    queries: list[str],
    exa_fallback: Callable[[str], list[str]],
) -> list[VideoLead]:
    ids: list[str] = []
    for query in queries:
        ids += [v for v in map(_video_id, exa_fallback(query)) if v and v not in ids]
    detailed: dict[str, VideoLead] = {}
    if key and ids:
        try:
            detailed = _details(caller, key, ids)
        except (_QuotaExhausted, ValueError):
            detailed = {}
    return [
        (detailed[v].model_copy(update={"source": "exa"}) if v in detailed else None)
        or VideoLead(video_id=v, url=f"https://www.youtube.com/watch?v={v}", source="exa")
        for v in ids
    ]


def find_videos(
    caller: ProviderCaller,
    keys: MediaSourceKeys,
    name: str,
    company: str | None,
    *,
    exa_fallback: Callable[[str], list[str]] | None,
) -> tuple[list[VideoLead], list[str]]:
    queries = [f'"{name}"', *([f'"{name}" {company}'] if company else [])]
    key = keys.youtube_api_key.get_secret_value() if keys.youtube_api_key else None
    if key is None:
        if exa_fallback is None:
            return [], ["youtube_data_api_key_missing"]
        return _from_exa(caller, None, queries[:1], exa_fallback), [
            "youtube_data_api_key_missing_used_exa"
        ]
    ids: list[str] = []
    try:
        for query in queries:
            params = urlencode({"part": "snippet", "type": "video", "maxResults": 25, "q": query})
            body = _youtube(caller, key, f"{YOUTUBE_SEARCH_URL}?{params}", "search.list")
            for item in body.get("items") or []:
                vid = (item.get("id") or {}).get("videoId")
                if isinstance(vid, str) and vid not in ids:
                    ids.append(vid)
        detailed = _details(caller, key, ids) if ids else {}
    except _QuotaExhausted:
        if exa_fallback is None:
            return [], ["youtube_quota_exhausted"]
        return _from_exa(caller, key, queries[:1], exa_fallback), [
            "youtube_quota_exhausted_used_exa"
        ]
    except ValueError as exc:
        return [], [str(exc)]
    leads = [
        detailed.get(v)
        or VideoLead(video_id=v, url=f"https://www.youtube.com/watch?v={v}", source="youtube")
        for v in ids
    ]
    return leads, []
