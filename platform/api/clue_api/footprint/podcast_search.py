"""Find podcast episodes a person may appear on: Apple and Podcast Index in one list.

Apple's episode search and Podcast Index's ``byperson`` search return episodes; ``byterm`` returns
shows (a person who hosts a show). Duplicates across sources are merged; a missing feed link is
filled from Apple's lookup. Results that name the person or the company come first, then newest.
Nothing is dropped: whether an episode is really this person is the agent's judgement, not ours.
A source that fails or has no key is reported as a gap and the others still answer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import quote_plus

from pydantic import BaseModel, Field

from clue_api.footprint.media_sources import (
    _URL,
    APPLE_SEARCH_URL,
    MediaSourceKeys,
    _get_json,
    podcast_index_headers,
)
from clue_spend.calls import ProviderCaller

PODCAST_INDEX_API = "https://api.podcastindex.org/api/1.0"
APPLE_LOOKUP_URL = "https://itunes.apple.com/lookup"


class EpisodeLead(BaseModel):
    kind: Literal["episode", "show"] = "episode"
    show: str | None
    title: str
    published_at: datetime | None
    description: str
    links: list[str] = Field(default_factory=list)
    feed_url: str | None = None
    audio_url: str | None = None
    transcript_url: str | None = None
    episode_url: str | None = None
    sources: list[str] = Field(default_factory=list)
    #: The title or description contains the person's name or the company. Ordering only.
    names_match: bool = False


def _when(value: Any) -> datetime | None:
    try:
        if isinstance(value, (int, float)) and value > 0:
            return datetime.fromtimestamp(value, tz=UTC)
        if isinstance(value, str) and value:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError, OSError):
        return None
    return None


def _links(text: str) -> list[str]:
    return list(dict.fromkeys(u.rstrip(".,;:!?") for u in _URL.findall(text or "")))


def _apple(caller: ProviderCaller, name: str) -> list[tuple[EpisodeLead, int | None]]:
    body = _get_json(
        caller,
        provider="apple_podcasts",
        operation="search",
        label="footprint.find_podcasts",
        url=f"{APPLE_SEARCH_URL}?media=podcast&entity=podcastEpisode&limit=50"
        f"&term={quote_plus(name)}",
    )
    out = []
    for r in body.get("results") or []:
        if not isinstance(r, dict) or not r.get("trackName"):
            continue
        desc = str(r.get("description") or "")
        out.append(
            (
                EpisodeLead(
                    show=r.get("collectionName"),
                    title=str(r["trackName"]),
                    published_at=_when(r.get("releaseDate")),
                    description=desc,
                    links=_links(desc),
                    feed_url=r.get("feedUrl") or None,
                    audio_url=r.get("episodeUrl") or None,
                    episode_url=r.get("trackViewUrl") or None,
                    sources=["apple"],
                ),
                r.get("collectionId"),
            )
        )
    return out


def _podcast_index(
    caller: ProviderCaller, keys: MediaSourceKeys, path: str, name: str, limit: int
) -> dict[str, Any]:
    assert keys.podcast_index_key and keys.podcast_index_secret
    return _get_json(
        caller,
        provider="podcast_index",
        operation=path,
        label="footprint.find_podcasts",
        url=f"{PODCAST_INDEX_API}/{path}?max={limit}&q={quote_plus(name)}",
        headers=podcast_index_headers(keys.podcast_index_key, keys.podcast_index_secret),
    )


def _pi_episodes(body: dict[str, Any]) -> list[EpisodeLead]:
    out = []
    for r in body.get("items") or []:
        if not isinstance(r, dict) or not r.get("title"):
            continue
        desc = str(r.get("description") or "")
        transcript = r.get("transcriptUrl") or next(
            (t.get("url") for t in r.get("transcripts") or [] if isinstance(t, dict)), None
        )
        out.append(
            EpisodeLead(
                show=r.get("feedTitle"),
                title=str(r["title"]),
                published_at=_when(r.get("datePublished")),
                description=desc,
                links=_links(desc),
                feed_url=r.get("feedUrl") or None,
                audio_url=r.get("enclosureUrl") or None,
                transcript_url=transcript or None,
                episode_url=r.get("link") or None,
                sources=["podcast_index"],
            )
        )
    return out


def _pi_shows(body: dict[str, Any]) -> list[EpisodeLead]:
    return [
        EpisodeLead(
            kind="show",
            show=str(f.get("title") or ""),
            title=str(f.get("title") or ""),
            published_at=_when(f.get("newestItemPublishTime")),
            description=str(f.get("description") or ""),
            links=_links(str(f.get("description") or "")),
            feed_url=f["url"],
            episode_url=f.get("link") or None,
            sources=["podcast_index"],
        )
        for f in body.get("feeds") or []
        if isinstance(f, dict) and isinstance(f.get("url"), str)
    ]


def _key(lead: EpisodeLead) -> str:
    title = " ".join(lead.title.lower().split())
    return f"{lead.kind}|{(lead.show or '').lower().strip()}|{title}"


def _merge(into: EpisodeLead, other: EpisodeLead) -> EpisodeLead:
    filled = {
        field: getattr(into, field) or getattr(other, field)
        for field in ("feed_url", "audio_url", "transcript_url", "episode_url", "published_at")
    }
    return into.model_copy(
        update={
            **filled,
            "description": max(into.description, other.description, key=len),
            "links": list(dict.fromkeys([*into.links, *other.links])),
            "sources": sorted({*into.sources, *other.sources}),
        }
    )


def find_podcasts(
    caller: ProviderCaller, keys: MediaSourceKeys, name: str, company: str | None
) -> tuple[list[EpisodeLead], list[str]]:
    gaps: list[str] = []
    collections: dict[str, int | None] = {}
    found: list[EpisodeLead] = []
    try:
        for lead, collection in _apple(caller, name):
            found.append(lead)
            collections[_key(lead)] = collection
    except ValueError as exc:
        gaps.append(f"apple_podcasts: {exc}")
    if keys.podcast_index_key and keys.podcast_index_secret:
        for path, limit, parse in (
            ("search/byperson", 40, _pi_episodes),
            ("search/byterm", 20, _pi_shows),
        ):
            try:
                found.extend(parse(_podcast_index(caller, keys, path, name, limit)))
            except ValueError as exc:
                gaps.append(f"podcast_index {path}: {exc}")
    else:
        gaps.append("podcast_index_keys_missing")

    merged: dict[str, EpisodeLead] = {}
    for lead in found:
        key = _key(lead)
        merged[key] = _merge(merged[key], lead) if key in merged else lead

    feeds: dict[int, str | None] = {}
    for key, lead in merged.items():
        collection = collections.get(key)
        if lead.feed_url or not collection:
            continue
        if collection not in feeds:
            try:
                body = _get_json(
                    caller,
                    provider="apple_podcasts",
                    operation="lookup",
                    label="footprint.find_podcasts",
                    url=f"{APPLE_LOOKUP_URL}?id={collection}",
                )
                results = body.get("results") or []
                feeds[collection] = (results[0] or {}).get("feedUrl") if results else None
            except ValueError:
                feeds[collection] = None
        merged[key] = lead.model_copy(update={"feed_url": feeds[collection]})

    needles = [n.lower() for n in (name, name.split()[-1] if name.split() else "", company) if n]
    leads = [
        lead.model_copy(
            update={
                "names_match": any(n in f"{lead.title} {lead.description}".lower() for n in needles)
            }
        )
        for lead in merged.values()
    ]
    oldest = datetime.min.replace(tzinfo=UTC)
    leads.sort(key=lambda lead: lead.published_at or oldest, reverse=True)
    leads.sort(key=lambda lead: not lead.names_match)
    return leads, gaps
