"""Find podcast episodes a person may appear on, from the searches the agent writes.

Each search the agent gives is run on Apple's episode search, Podcast Index (``byperson`` returns
episodes, ``byterm`` shows) and Exa's podcast transcripts, which match what was said in an episode,
so an episode whose title and description never name its guest can still be found (founder ruling
2026-11-11). The same episode found by several searches or sources is listed once, with every
search that found it; a missing feed link is filled from Apple's lookup.

Nothing is dropped or ranked by name: the list keeps the order the searches found it, and whether
an episode is really this person is the agent's judgement. A transcript often spells a name
wrongly, so no code may judge an episode by its spelling.

Every call is counted in the returned :class:`~clue_api.footprint.search_tally.Tally`: a source
that fails is a named failure and the others still answer; a source with no key is a note; Exa out
of credit (:class:`SourceStopped`) stops Exa for the searches left, and only Exa (review I2, I3).
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from urllib.parse import quote_plus, unquote, urlsplit

from pydantic import BaseModel, Field

from clue_api.footprint.media_sources import (
    _URL,
    APPLE_SEARCH_URL,
    MediaSourceKeys,
    _get_json,
    podcast_index_headers,
)
from clue_api.footprint.search_tally import SourceStopped, Tally
from clue_spend.calls import ProviderCaller

PODCAST_INDEX_API = "https://api.podcastindex.org/api/1.0"
#: Exa's podcast index lives under this path; searches are limited to it.
EXA_PODCAST_DOMAIN = "exa.ai/library/podcast"


class ExaPodcastHit(Protocol):
    """One Exa result: an episode page (header, then the speaker-labelled transcript)."""

    url: str | None
    title: str | None
    published_date: str | None
    text: str | None
    highlights: Sequence[str]


#: Runs one search on Exa's podcast index and returns its hits; raises ``ValueError`` on failure
#: and :class:`SourceStopped` when Exa will not sell.
ExaPodcastSearch = Callable[[str], Sequence[ExaPodcastHit]]
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
    duration_s: int | None = None
    sources: list[str] = Field(default_factory=list)
    #: Every search (as the agent wrote it) that found this episode.
    found_by: list[str] = Field(default_factory=list)
    #: Exa's page for the episode, with its whole speaker-labelled transcript.
    exa_url: str | None = None
    #: The transcript passages that matched the search (Exa).
    passages: list[str] = Field(default_factory=list)
    #: Hosts and guests as Exa's transcription heard them: its reading of the audio, not a fact.
    heard_hosts: list[str] = Field(default_factory=list)
    heard_guests: list[str] = Field(default_factory=list)
    #: The publisher's own id for the episode (the RSS item's GUID), as the source gave it.
    guid: str | None = None
    #: Apple's id for the show: Apple ``collectionId``, Podcast Index ``feedItunesId``.
    show_id: str | None = None
    #: Each source's own id for this result: ``apple:<trackId>``, ``pi:<id>``,
    #: ``pi_show:<id>``, ``exa:<url>``.
    source_ids: list[str] = Field(default_factory=list)


def _when(value: Any) -> datetime | None:
    try:
        if isinstance(value, (int, float)) and value > 0:
            return datetime.fromtimestamp(value, tz=UTC)
        if isinstance(value, str) and value:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError, OSError):
        return None
    return None


def _text_id(value: Any) -> str | None:
    """An identifier as a trimmed string; ``None`` when absent or empty."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


#: A path segment that is itself a host name: where a tracker's redirect wraps the real address.
_HOST_SEGMENT = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}")
#: The last path segment of an audio or media file.
_FILE_SEGMENT = re.compile(r"\.(?:mp3|m4a|mp4|aac|ogg|oga|opus|wav|flac|webm|m4v|mov)$")


def audio_key(url: str | None) -> str | None:
    """The audio file a link points at, seen through tracking redirects.

    Trackers wrap the real address in their own path (``dts.podtrac.com/redirect.mp3/<host>/…``,
    ``chrt.fm/track/<id>/<host>/…``, anchor.fm's percent-encoded ``…/play/<id>/https%3A%2F%2F…``),
    sometimes several in a chain; the file starts at the last path segment that is a host name.
    The scheme, host case and a leading ``www.`` are ignored, and so is the query of a file name
    (it carries per-request tokens); a path with no file name keeps its query, because some hosts
    serve every episode from one path.
    """
    if not url or not url.strip():
        return None
    parts = urlsplit(unquote(url.strip()))
    segments = [seg for seg in f"{parts.netloc}{parts.path}".split("/") if seg]
    if not segments:
        return None
    start = 0
    for index, segment in enumerate(segments[1:], 1):
        lowered = segment.lower().split(":")[0]
        if _HOST_SEGMENT.fullmatch(lowered) and not _FILE_SEGMENT.search(lowered):
            start = index
    tail = segments[start:]
    if tail and tail[0].lower() in ("http:", "https:"):
        tail = tail[1:]
    key = "/".join(tail).lower().removeprefix("www.")
    if not _FILE_SEGMENT.search(key) and parts.query:
        key = f"{key}?{parts.query}"
    return key or None


def feed_key(url: str | None) -> str | None:
    """A feed link with the scheme, case, a leading ``www.`` and a trailing slash ignored."""
    if not url or not url.strip():
        return None
    parts = urlsplit(url.strip())
    key = f"{parts.netloc}{parts.path}".lower().removeprefix("www.").rstrip("/")
    if parts.query:
        key = f"{key}?{parts.query}"
    return key or None


def _links(text: str) -> list[str]:
    return list(dict.fromkeys(u.rstrip(".,;:!?") for u in _URL.findall(text or "")))


def _apple(caller: ProviderCaller, name: str) -> list[EpisodeLead]:
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
            EpisodeLead(
                show=r.get("collectionName"),
                title=str(r["trackName"]),
                published_at=_when(r.get("releaseDate")),
                description=desc,
                links=_links(desc),
                feed_url=r.get("feedUrl") or None,
                audio_url=r.get("episodeUrl") or None,
                episode_url=r.get("trackViewUrl") or None,
                duration_s=int(r["trackTimeMillis"]) // 1000
                if isinstance(r.get("trackTimeMillis"), int)
                else None,
                sources=["apple"],
                guid=_text_id(r.get("episodeGuid")),
                show_id=_text_id(r.get("collectionId")),
                source_ids=[f"apple:{t}"] if (t := _text_id(r.get("trackId"))) else [],
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
                duration_s=r["duration"] if isinstance(r.get("duration"), int) else None,
                sources=["podcast_index"],
                guid=_text_id(r.get("guid")),
                show_id=_text_id(r.get("feedItunesId")),
                source_ids=[f"pi:{i}"] if (i := _text_id(r.get("id"))) else [],
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
            show_id=_text_id(f.get("itunesId")),
            source_ids=[f"pi_show:{i}"] if (i := _text_id(f.get("id"))) else [],
        )
        for f in body.get("feeds") or []
        if isinstance(f, dict) and isinstance(f.get("url"), str)
    ]


_HEADER = re.compile(r"^- \*\*(Podcast|Published|Duration|Hosts|Guests):\*\* (.*)$", re.M)
#: A passage can start with the episode page's header (show, date, hosts, guests), which the lead
#: already carries in its own fields; it is left out, up to Exa's "..." separator.
_PASSAGE_HEADER = re.compile(r"\A(?:- \*\*[^*\n]+:\*\*[^\n]*\n)+\s*(?:\.\.\.\s*)?")
_LINK_TEXT = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def _people(value: str) -> list[str]:
    plain = _LINK_TEXT.sub(r"\1", value)
    return [name.strip() for name in plain.split(",") if name.strip()]


def _clock(value: str) -> int | None:
    parts = value.strip().split(":")
    try:
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + float(part)
    except ValueError:
        return None
    return int(seconds)


def _exa_lead(hit: ExaPodcastHit) -> EpisodeLead | None:
    if not hit.title:
        return None
    header = dict(_HEADER.findall((hit.text or "").split("## Transcript", 1)[0]))
    show = _LINK_TEXT.sub(r"\1", header.get("Podcast", "")).strip() or None
    return EpisodeLead(
        show=show,
        title=hit.title,
        published_at=_when(header.get("Published") or hit.published_date),
        description="",
        duration_s=_clock(header["Duration"]) if "Duration" in header else None,
        sources=["exa_podcasts"],
        exa_url=hit.url,
        passages=[q for q in (_PASSAGE_HEADER.sub("", p).strip() for p in hit.highlights) if q],
        heard_hosts=_people(header.get("Hosts", "")),
        heard_guests=_people(header.get("Guests", "")),
        source_ids=[f"exa:{hit.url}"] if hit.url else [],
    )


#: Proven-same results take their links, dates and ids from sources in this order.
_SOURCE_ORDER = {"podcast_index": 0, "apple": 1, "exa_podcasts": 2}
#: Two copies of one episode in different feeds (a mirror, a moved host) publish within this
#: window and differ by at most this many seconds of length.
_SAME_DAY_S = 86_400
_SAME_LENGTH_S = 60


def _plain(value: str | None) -> str | None:
    text = " ".join((value or "").lower().split())
    return text or None


def _is_exa_only(lead: EpisodeLead) -> bool:
    return lead.sources == ["exa_podcasts"]


def _close(a: EpisodeLead, b: EpisodeLead, *, length: bool) -> bool:
    """Both dates present and within a day; with ``length``, both durations present and close."""
    if a.published_at is None or b.published_at is None:
        return False
    if abs((a.published_at - b.published_at).total_seconds()) > _SAME_DAY_S:
        return False
    if not length:
        return True
    if not a.duration_s or not b.duration_s:
        return False
    return abs(a.duration_s - b.duration_s) <= _SAME_LENGTH_S


def _shows(lead: EpisodeLead) -> list[str]:
    """Every way this lead names its show by proof: Apple's show id and the feed."""
    out = [f"id={lead.show_id}"] if lead.show_id else []
    if feed := feed_key(lead.feed_url):
        out.append(f"feed={feed}")
    return out


class _Groups:
    """Union-find over result positions; a group is listed at its first member's position."""

    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def join(self, i: int, j: int) -> None:
        a, b = self.find(i), self.find(j)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def _group(leads: Sequence[EpisodeLead]) -> list[EpisodeLead]:
    """One lead per episode (or show) that the publishers' own ids prove the same (review I14).

    Two episodes are one when they share a source's own id, the same GUID within the same show,
    the same audio file, or the same show, title, day and length; an Exa result (no feed, GUID
    or audio) joins on the same show name, title and day. Two shows are one when they share
    Apple's show id or the feed. A value missing on either side never matches, and anything less
    than proof stays two lines for the agent to judge.
    """
    groups = _Groups(len(leads))
    exact: dict[str, int] = {}
    near: dict[str, list[int]] = {}

    def same(key: str, i: int) -> None:
        if key in exact:
            groups.join(exact[key], i)
        else:
            exact[key] = i

    for i, lead in enumerate(leads):
        kind = lead.kind
        for sid in lead.source_ids:
            same(f"{kind}|source|{sid}", i)
        if kind == "show":
            for show in _shows(lead):
                same(f"show|{show}", i)
            continue
        if audio := audio_key(lead.audio_url):
            same(f"episode|audio|{audio}", i)
        if lead.guid:
            for show in _shows(lead):
                same(f"episode|guid|{lead.guid}|{show}", i)
        title = _plain(lead.title)
        if title:
            for show in _shows(lead):
                near.setdefault(f"feed|{show}|{title}", []).append(i)
            if name := _plain(lead.show):
                near.setdefault(f"name|{name}|{title}", []).append(i)

    for key, members in near.items():
        by_name = key.startswith("name|")
        for i, j in itertools.combinations(members, 2):
            a, b = leads[i], leads[j]
            if by_name:
                if (_is_exa_only(a) or _is_exa_only(b)) and _close(a, b, length=False):
                    groups.join(i, j)
            elif _close(a, b, length=True):
                groups.join(i, j)

    members: dict[int, list[EpisodeLead]] = {}
    for i, lead in enumerate(leads):
        members.setdefault(groups.find(i), []).append(lead)
    return [_combine(group) for _, group in sorted(members.items())]


def _combine(members: Sequence[EpisodeLead]) -> EpisodeLead:
    """One lead from results proven to be the same episode; never mixes in any other episode."""
    if len(members) == 1:
        return members[0]
    ranked = sorted(
        members,
        key=lambda m: (min(_SOURCE_ORDER.get(s, 9) for s in m.sources), m.model_dump_json()),
    )
    first = ranked[0]
    picked = {
        field: next((v for m in ranked if (v := getattr(m, field))), getattr(first, field))
        for field in (
            "show",
            "feed_url",
            "audio_url",
            "transcript_url",
            "episode_url",
            "published_at",
            "duration_s",
            "exa_url",
            "guid",
            "show_id",
        )
    }
    exa = [m for m in members if "exa_podcasts" in m.sources]

    def union(field: str, among: Sequence[EpisodeLead]) -> list[str]:
        return list(dict.fromkeys(v for m in among for v in getattr(m, field)))

    return first.model_copy(
        update={
            **picked,
            "description": max((m.description for m in members), key=lambda d: (len(d), d)),
            "links": union("links", members),
            "sources": sorted({s for m in members for s in m.sources}),
            "found_by": union("found_by", members),
            "passages": union("passages", members),
            "heard_hosts": union("heard_hosts", exa),
            "heard_guests": union("heard_guests", exa),
            "source_ids": sorted({s for m in members for s in m.source_ids}),
        }
    )


def _one_search(
    caller: ProviderCaller,
    keys: MediaSourceKeys,
    number: int,
    query: str,
    exa_search: ExaPodcastSearch | None,
    tally: Tally,
) -> list[EpisodeLead]:
    found: list[EpisodeLead] = []
    try:
        found.extend(_apple(caller, query))
        tally.answer()
    except ValueError as exc:
        tally.fail(f"Apple search [{number}] {query!r} failed: {exc}")
    if keys.podcast_index_key and keys.podcast_index_secret:
        for path, limit, parse in (
            ("search/byperson", 40, _pi_episodes),
            ("search/byterm", 20, _pi_shows),
        ):
            try:
                found.extend(parse(_podcast_index(caller, keys, path, query, limit)))
                tally.answer()
            except ValueError as exc:
                tally.fail(f"Podcast Index {path} [{number}] {query!r} failed: {exc}")
    if exa_search is not None and "exa" not in tally.stopped:
        try:
            found.extend(lead for lead in map(_exa_lead, exa_search(query)) if lead)
            tally.answer()
        except SourceStopped as stop:
            tally.stop(
                "exa",
                stop.reason,
                f"Exa stopped selling at search [{number}] ({stop.reason}); the searches left "
                "were run without Exa's transcripts.",
            )
        except ValueError as exc:
            tally.fail(f"Exa podcast search [{number}] {query!r} failed: {exc}")
    return [lead.model_copy(update={"found_by": [query]}) for lead in found]


def find_podcasts(
    caller: ProviderCaller,
    keys: MediaSourceKeys,
    queries: Sequence[str],
    *,
    exa_search: ExaPodcastSearch | None,
) -> tuple[list[EpisodeLead], Tally]:
    tally = Tally()
    if not (keys.podcast_index_key and keys.podcast_index_secret):
        tally.note("Podcast Index keys are not set: it was not searched.")
    if exa_search is None:
        tally.note("Exa's podcast transcripts are not available in this job: not searched.")
    found: list[EpisodeLead] = []
    for number, query in enumerate(dict.fromkeys(queries), 1):
        found.extend(_one_search(caller, keys, number, query, exa_search, tally))
    leads = _group(found)

    # Apple's episode search can leave out the feed; its show id finds it.
    feeds: dict[str, str | None] = {}
    for index, lead in enumerate(leads):
        if lead.feed_url or not lead.show_id:
            continue
        if lead.show_id not in feeds:
            try:
                body = _get_json(
                    caller,
                    provider="apple_podcasts",
                    operation="lookup",
                    label="footprint.find_podcasts",
                    url=f"{APPLE_LOOKUP_URL}?id={lead.show_id}",
                )
                results = body.get("results") or []
                first = results[0] if results and isinstance(results[0], dict) else {}
                feeds[lead.show_id] = first.get("feedUrl") or None
                tally.answer()
            except ValueError as exc:
                feeds[lead.show_id] = None
                tally.fail(
                    f"Apple lookup of the feed for {lead.show or lead.title!r} failed: {exc}"
                )
        leads[index] = lead.model_copy(update={"feed_url": feeds[lead.show_id]})
    return leads, tally


#: Overview lines name sources briefly.
_SOURCE_SHORT = {"apple": "apple", "podcast_index": "pi", "exa_podcasts": "exa"}
#: An overview line keeps this much of "show — title".
OVERVIEW_TITLE_CHARS = 90


def overview(leads: Sequence[EpisodeLead], queries: Sequence[str]) -> list[str]:
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
        "Sources: apple = Apple Podcasts, pi = Podcast Index, exa = Exa transcripts (matched what "
        "was said; heard = the guests Exa's transcription names, its reading of the audio).",
        "",
        "  # | date | show — title | length | found by | sources",
    ]
    for n, lead in enumerate(leads, 1):
        if lead.kind == "show":
            name = f"SHOW: {lead.title}"
        else:
            name = f"{lead.show} — {lead.title}" if lead.show else lead.title
        if len(name) > OVERVIEW_TITLE_CHARS:
            name = name[: OVERVIEW_TITLE_CHARS - 1] + "…"
        date = lead.published_at.date().isoformat() if lead.published_at else "-"
        length = f"{round(lead.duration_s / 60)} min" if lead.duration_s else "-"
        found = ",".join(str(number[q]) for q in lead.found_by if q in number) or "-"
        sources = "+".join(_SOURCE_SHORT.get(src, src) for src in lead.sources)
        line = f"{n:3d} | {date} | {name} | {length} | {found} | {sources}"
        if lead.heard_guests:
            line += f" | heard: {', '.join(lead.heard_guests)}"
        lines.append(line)
    return lines
