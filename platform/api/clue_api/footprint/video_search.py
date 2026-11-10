"""Find videos a person may appear in, from the searches the agent writes.

Each search is run on YouTube, then each hit's details are read. ``search.list`` costs 100 of the
free 10,000 daily quota units, so about 100 searches a day. When the quota is gone (or no key is
configured) the caller's Exa search is used instead, and the result says so. Each hit comes back
with its full description, tags, channel, length and the searches that found it, in the order
found, for the agent to judge before transcribing; nothing is filtered or ranked here.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
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
    #: Every search (as the agent wrote it) that found this video.
    found_by: list[str] = Field(default_factory=list)


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
    found_by: dict[str, list[str]] = {}
    for query in queries:
        for v in map(_video_id, exa_fallback(query)):
            if v:
                found_by.setdefault(v, []).append(query)
                if v not in ids:
                    ids.append(v)
    detailed: dict[str, VideoLead] = {}
    if key and ids:
        try:
            detailed = _details(caller, key, ids)
        except (_QuotaExhausted, ValueError):
            detailed = {}
    return [
        (detailed.get(v) or _bare(v, "exa")).model_copy(
            update={"source": "exa", "found_by": list(dict.fromkeys(found_by[v]))}
        )
        for v in ids
    ]


def _bare(video_id: str, source: Literal["youtube", "exa"]) -> VideoLead:
    return VideoLead(
        video_id=video_id, url=f"https://www.youtube.com/watch?v={video_id}", source=source
    )


def find_videos(
    caller: ProviderCaller,
    keys: MediaSourceKeys,
    queries: Sequence[str],
    *,
    exa_fallback: Callable[[str], list[str]] | None,
) -> tuple[list[VideoLead], list[str]]:
    queries = list(dict.fromkeys(queries))
    key = keys.youtube_api_key.get_secret_value() if keys.youtube_api_key else None
    if key is None:
        if exa_fallback is None:
            return [], ["youtube_data_api_key_missing"]
        return _from_exa(caller, None, queries, exa_fallback), [
            "youtube_data_api_key_missing_used_exa"
        ]
    ids: list[str] = []
    found_by: dict[str, list[str]] = {}
    try:
        for query in queries:
            params = urlencode({"part": "snippet", "type": "video", "maxResults": 25, "q": query})
            body = _youtube(caller, key, f"{YOUTUBE_SEARCH_URL}?{params}", "search.list")
            for item in body.get("items") or []:
                vid = (item.get("id") or {}).get("videoId")
                if isinstance(vid, str):
                    found_by.setdefault(vid, []).append(query)
                    if vid not in ids:
                        ids.append(vid)
        detailed = _details(caller, key, ids) if ids else {}
    except _QuotaExhausted:
        if exa_fallback is None:
            return [], ["youtube_quota_exhausted"]
        return _from_exa(caller, key, queries, exa_fallback), ["youtube_quota_exhausted_used_exa"]
    except ValueError as exc:
        return [], [str(exc)]
    leads = [
        (detailed.get(v) or _bare(v, "youtube")).model_copy(
            update={"found_by": list(dict.fromkeys(found_by[v]))}
        )
        for v in ids
    ]
    return leads, []


#: An overview line keeps this much of "channel — title".
OVERVIEW_TITLE_CHARS = 90


def overview(leads: Sequence[VideoLead], queries: Sequence[str]) -> list[str]:
    """One short line per result, in the order found, so the agent can scan many results before
    opening any. Line N is entry N of the full list. Nothing is ranked or left out."""
    searches = list(dict.fromkeys(queries))
    number = {q: i for i, q in enumerate(searches, 1)}
    lines = [
        f"{len(leads)} results, in the order found (not ranked). Line N is entry N of the full "
        "list below it.",
        "Searches:",
        *(
            f"[{number[q]}] {q} — {sum(q in lead.found_by for lead in leads)} results"
            for q in searches
        ),
        "Sources: youtube = YouTube search, exa = Exa web search (used when YouTube's daily "
        "quota is gone).",
        "",
        "  # | date | channel — title | length | found by | source",
    ]
    for n, lead in enumerate(leads, 1):
        if lead.title:
            name = f"{lead.channel} — {lead.title}" if lead.channel else lead.title
        else:
            name = f"(no details) {lead.url}"
        if len(name) > OVERVIEW_TITLE_CHARS and lead.title:
            name = name[: OVERVIEW_TITLE_CHARS - 1] + "…"
        date = lead.published_at.date().isoformat() if lead.published_at else "-"
        length = f"{round(lead.duration_s / 60)} min" if lead.duration_s else "-"
        found = ",".join(str(number[q]) for q in lead.found_by if q in number) or "-"
        lines.append(f"{n:3d} | {date} | {name} | {length} | {found} | {lead.source}")
    return lines
