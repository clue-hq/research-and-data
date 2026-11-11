"""Find videos a person may appear in, from the searches the agent writes.

Each search is run on YouTube, then each hit's details are read. ``search.list`` costs 100 of the
free 10,000 daily quota units, so about 100 searches a day. Each hit comes back with its full
description, tags, channel, length and the searches that found it, in the order found, for the
agent to judge before transcribing; nothing is filtered or ranked here.

Every search keeps its own results; a failure is counted and named in the returned
:class:`~clue_api.footprint.search_tally.Tally`, never turned into "no results" (review I2):

- YouTube refusing for its daily quota or a rate limit stops YouTube for this call, and that
  search and the ones after it go to the caller's Exa search. The quota is a note (asking again
  today would not help); a rate limit or any other YouTube failure is a failure.
- A search YouTube fails for any other reason is tried on Exa too.
- Exa failing is a failure; Exa out of credit (:class:`SourceStopped`) stops Exa for the rest.
- Details that cannot be read leave the videos as found, without them, and say so.
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
from clue_api.footprint.search_tally import SourceStopped, Tally
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


#: YouTube's reasons for refusing to answer at all (``error.errors[].reason``).
_QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}
_RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}


class _YouTubeStopped(Exception):
    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why
        self.quota = why == "its daily quota is used up"


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
        raise ValueError("YouTube did not answer") from exc
    status = result.response.status
    try:
        body = json.loads(result.response.body) if result.response.body else {}
    except ValueError:
        body = {}
    error = body.get("error") if isinstance(body, dict) else None
    error = error if isinstance(error, dict) else {}
    reasons = {e.get("reason") for e in error.get("errors") or [] if isinstance(e, dict)}
    if reasons & _QUOTA_REASONS:
        raise _YouTubeStopped("its daily quota is used up")
    if status == 429 or reasons & _RATE_REASONS:
        raise _YouTubeStopped(f"a rate limit (HTTP {status})")
    if not 200 <= status < 300 or not isinstance(body, dict):
        message = error.get("message")
        raise ValueError(f"YouTube HTTP {status}" + (f": {message}" if message else ""))
    return body


def _lead(item: dict[str, Any]) -> VideoLead:
    snippet = item.get("snippet") or {}
    description = str(snippet.get("description") or "")
    published = snippet.get("publishedAt")
    return VideoLead(
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


def _details(
    caller: ProviderCaller, key: str, ids: list[str], tally: Tally
) -> dict[str, VideoLead]:
    """Details for as many videos as YouTube will give; a chunk that fails is named and its
    videos keep only what the search gave."""
    out: dict[str, VideoLead] = {}
    for start in range(0, len(ids), 50):
        chunk = ids[start : start + 50]
        query = urlencode({"part": "snippet,contentDetails", "id": ",".join(chunk)})
        try:
            body = _youtube(caller, key, f"{YOUTUBE_VIDEOS_URL}?{query}", "videos.list")
        except _YouTubeStopped as stop:
            rest = len(ids) - start
            tally.fail(
                f"Details of {rest} video(s) not read: YouTube stopped answering ({stop.why})"
            )
            break
        except ValueError as exc:
            tally.fail(f"Details of {len(chunk)} video(s) not read: {exc}")
            continue
        tally.answer()
        for item in body.get("items") or []:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                out[item["id"]] = _lead(item)
    return out


def _video_id(url: str) -> str | None:
    try:
        found = youtube_url(url)
    except ValueError:
        return None
    return found[1].removeprefix("youtube:") if found else None


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
) -> tuple[list[VideoLead], Tally]:
    """``exa_fallback`` runs one search on Exa and returns its links; it raises ``ValueError``
    on a failure and :class:`SourceStopped` when Exa will not sell."""
    queries = list(dict.fromkeys(queries))
    tally = Tally()
    key = keys.youtube_api_key.get_secret_value() if keys.youtube_api_key else None
    if key is None:
        tally.note("No YouTube key is set: every search went to Exa.")
    youtube_stopped: _YouTubeStopped | None = None
    exa_stopped: str | None = None
    ids: list[str] = []
    source: dict[str, Literal["youtube", "exa"]] = {}
    found_by: dict[str, list[str]] = {}

    def found(video_id: str, query: str, origin: Literal["youtube", "exa"]) -> None:
        found_by.setdefault(video_id, []).append(query)
        if video_id not in ids:
            ids.append(video_id)
            source[video_id] = origin

    for number, query in enumerate(queries, 1):
        if key is not None and youtube_stopped is None:
            params = urlencode({"part": "snippet", "type": "video", "maxResults": 25, "q": query})
            try:
                body = _youtube(caller, key, f"{YOUTUBE_SEARCH_URL}?{params}", "search.list")
            except _YouTubeStopped as stop:
                youtube_stopped = stop
                text = (
                    f"YouTube stopped answering at search [{number}] ({stop.why}); that search "
                    "and the ones after it went to Exa."
                )
                tally.note(text) if stop.quota else tally.fail(text)
            except ValueError as exc:
                tally.fail(f"YouTube search [{number}] {query!r} failed ({exc}); tried on Exa.")
            else:
                tally.answer()
                for item in body.get("items") or []:
                    vid = (item.get("id") or {}).get("videoId") if isinstance(item, dict) else None
                    if isinstance(vid, str):
                        found(vid, query, "youtube")
                continue
        if exa_fallback is None:
            tally.fail(f"Search [{number}] {query!r} was not run: no Exa search is configured.")
            continue
        if exa_stopped is not None:
            tally.fail(
                f"Search [{number}] {query!r} was not run on Exa: Exa stopped ({exa_stopped})."
            )
            continue
        try:
            links = exa_fallback(query)
        except SourceStopped as stop:
            exa_stopped = stop.reason
            tally.stop(
                "exa",
                stop.reason,
                f"Exa stopped selling at search [{number}] ({stop.reason}); the searches left "
                "were not run on Exa.",
            )
            continue
        except ValueError as exc:
            tally.fail(f"Exa search [{number}] {query!r} failed: {exc}")
            continue
        tally.answer()
        for vid in map(_video_id, links):
            if vid:
                found(vid, query, "exa")

    detailed: dict[str, VideoLead] = {}
    if key is not None and youtube_stopped is None and ids:
        detailed = _details(caller, key, ids, tally)
    elif key is not None and youtube_stopped is not None and ids:
        tally.note(f"Details of {len(ids)} video(s) not read: YouTube stopped answering.")
    leads = [
        (detailed.get(v) or _bare(v, source[v])).model_copy(
            update={"source": source[v], "found_by": list(dict.fromkeys(found_by[v]))}
        )
        for v in ids
    ]
    return leads, tally


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
