"""Public recording resolution via explicit source links, never title-based identity merges."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass, replace
from html import unescape
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from clue_api.arv2.calls import CallSpec, ProviderCaller
from clue_api.arv2.media_feeds_client import (
    extract_player_response,
    parse_feed,
    reject_native_video,
)
from clue_api.arv2.media_types import Candidate, Segment, canonical_text, content_hash
from clue_api.arv2.transport import BROWSER_USER_AGENT, HttpRequest, HttpResponse
from clue_research.identity.normalize import registrable_domain
from clue_research.official_site.safety import (
    CrawlSafetyPolicy,
    SystemAddressResolver,
    make_pinned_resolver,
)
from clue_research.official_site.url_policy import ConservativeUrlPolicy, UrlPolicyConfig

MAX_MEDIA_BYTES = 200 * 1024 * 1024
MAX_DOCUMENT_BYTES = 5_000_000
YT_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


def public_url(url: str) -> str:
    if len(url.encode()) > 4096:
        raise ValueError("public media URL exceeds supported length")
    parts = urlsplit(url)
    if (
        parts.username
        or parts.password
        or parts.scheme not in {"https", "http"}
        or not parts.hostname
    ):
        raise ValueError("public HTTP URL without credentials required")
    try:
        address = ipaddress.ip_address(parts.hostname)
    except ValueError:
        address = None
    if address is not None and (not address.is_global or address.is_multicast):
        raise ValueError("non_public_network_target")
    if parts.hostname == "localhost" or parts.hostname.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise ValueError("non_public_network_target")
    if parts.port not in (None, 80, 443):
        raise ValueError("unsupported public port")
    policy = ConservativeUrlPolicy(
        UrlPolicyConfig(
            root_url=url,
            allowed_registrable_domain=registrable_domain(url) or parts.hostname,
            allow_subdomains=True,
        )
    )
    result = policy.decide(url)
    if not result.admitted or not result.fetch_key:
        raise ValueError(result.reason)
    reject_native_video(url)
    return result.fetch_key


def youtube_url(url: str) -> tuple[str, str] | None:
    parts = urlsplit(url)
    if parts.hostname not in YT_HOSTS:
        return None
    bits = parts.path.strip("/").split("/")
    vid = (
        bits[0]
        if parts.hostname == "youtu.be"
        else parse_qs(parts.query).get("v", [""])[0]
        if parts.path == "/watch"
        else bits[1]
        if len(bits) == 2 and bits[0] in {"embed", "shorts", "live"}
        else ""
    )
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
        raise ValueError("YouTube recording URL must contain an exact video ID")
    return f"https://www.youtube.com/watch?v={vid}", f"youtube:{vid}"


class PublicMediaTransport:
    """Bounded public GETs. Each redirect reconnects only to independently validated DNS IPs."""

    def send(self, request: HttpRequest) -> HttpResponse:
        import httpx

        if request.method not in {"GET", "HEAD"}:
            raise ValueError("public-media transport only admits reads")
        url = request.url
        for _ in range(6):
            url = public_url(url)
            parts = urlsplit(url)

            async def connect(
                target: str, addresses: tuple[str, ...], parts: Any = parts
            ) -> HttpResponse:
                ip = addresses[0]
                address = f"[{ip}]" if ":" in ip else ip
                if parts.port:
                    address += f":{parts.port}"
                pinned = urlunsplit((parts.scheme, address, parts.path, parts.query, ""))
                headers = {**request.headers, "Host": parts.netloc}
                with (
                    httpx.Client(
                        follow_redirects=False, trust_env=False, timeout=request.timeout_s
                    ) as client,
                    client.stream(
                        request.method,
                        pinned,
                        headers=headers,
                        extensions={"sni_hostname": parts.hostname},
                    ) as response,
                ):
                    mime = response.headers.get("content-type", "").split(";")[0].lower()
                    limit = (
                        MAX_MEDIA_BYTES
                        if mime.startswith(("audio/", "video/"))
                        else MAX_DOCUMENT_BYTES
                    )
                    if int(response.headers.get("content-length", "0")) > limit:
                        raise ValueError("media response exceeds byte ceiling")
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise ValueError("media response exceeds byte ceiling")
                        chunks.append(chunk)
                    return HttpResponse(
                        response.status_code, dict(response.headers), b"".join(chunks)
                    )

            async def checked_fetch(url: str = url) -> object:
                return await make_pinned_resolver(
                    SystemAddressResolver(), connect, safety=CrawlSafetyPolicy()
                )(url)

            result: object = asyncio.run(checked_fetch())
            assert isinstance(result, HttpResponse)
            if result.status not in {301, 302, 303, 307, 308}:
                return HttpResponse(
                    result.status, {**result.headers, "x-arv2-final-url": url}, result.body
                )
            if not result.headers.get("location"):
                raise ValueError("redirect missing location")
            url = urljoin(url, result.headers["location"])
        raise ValueError("redirect ceiling exceeded")


def fetch(caller: ProviderCaller, url: str, *, binary: bool = False) -> HttpResponse:
    url = public_url(url)
    result = caller.call(
        CallSpec(
            provider="public_media",
            operation="GET",
            label="media.resolve",
            request=HttpRequest(
                method="GET", url=url, headers={"User-Agent": BROWSER_USER_AGENT}, timeout_s=60
            ),
            binary=binary,
            max_attempts=1,
        )
    )
    if not 200 <= result.response.status < 300:
        raise ValueError(f"public source HTTP {result.response.status}")
    limit = MAX_MEDIA_BYTES if binary else MAX_DOCUMENT_BYTES
    if len(result.response.body) > limit:
        raise ValueError("media response exceeds byte ceiling")
    return result.response


class PageLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.subjects: list[str] = []
        self.feeds: list[str] = []
        self.media: list[str] = []
        self.media_origins: dict[str, list[str]] = {}
        self.player_metadata: dict[str, str] = {}
        self.transcripts: list[str] = []
        self.documents: list[object] = []
        self._script: list[str] | None = None
        self._anchor: tuple[str, list[str]] | None = None

    def add_media(self, url: str, origin: str) -> None:
        self.media.append(url)
        self.media_origins.setdefault(url, []).append(origin)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        href, src, kind = a.get("href"), a.get("src"), a.get("type") or ""
        if (
            tag == "link"
            and href
            and "alternate" in (a.get("rel") or "")
            and kind in {"application/rss+xml", "application/atom+xml"}
        ):
            self.feeds.append(href)
        if tag in {"iframe", "audio", "video", "source"} and src:
            self.add_media(src, f"html:{tag}:src")
        if tag == "meta" and a.get("content"):
            key = (a.get("property") or a.get("name") or "").lower()
            if key in {"twitter:player", "twitter:player:stream"}:
                self.player_metadata[key] = a["content"] or ""
            elif key in {
                "og:audio",
                "og:audio:url",
                "og:audio:secure_url",
                "og:video",
                "og:video:url",
                "og:video:secure_url",
            }:
                self.add_media(a["content"] or "", f"html:meta:{key}")
        if tag == "track" and src and a.get("kind") in {"captions", "subtitles"}:
            self.transcripts.append(src)
        if tag == "a" and href:
            target = urlsplit(href)
            if target.hostname in {"linkedin.com", "www.linkedin.com"} and target.path.startswith(
                "/in/"
            ):
                self.subjects.append(href)
            self._anchor = (href, [])
        if tag == "script" and kind == "application/ld+json":
            self._script = []

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script.append(data)
        if self._anchor is not None:
            self._anchor[1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            with suppress(ValueError):
                self.documents.append(json.loads("".join(self._script)))
            self._script = None
        if tag == "a" and self._anchor is not None:
            href, words = self._anchor
            if re.search(r"\btranscript\b", "".join(words), re.I):
                self.transcripts.append(href)
            self._anchor = None


def objects(value: object) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def recording_links(parser: PageLinks, page_url: str) -> dict[str, list[str]]:
    """Explicit recording links with extraction provenance, excluding non-media frames."""
    # A Twitter player and its declared stream describe the same card: prefer the stream.
    key = (
        "twitter:player:stream"
        if parser.player_metadata.get("twitter:player:stream")
        else "twitter:player"
    )
    if value := parser.player_metadata.get(key):
        parser.add_media(value, f"html:meta:{key}")
    links: dict[str, list[str]] = {}
    for value in parser.media:
        target = urljoin(page_url, value.strip())
        parts = urlsplit(target)
        if parts.scheme not in {"http", "https"}:
            continue
        if parts.hostname in {"googletagmanager.com", "www.googletagmanager.com"}:
            continue
        # Embed/watch forms of the same YouTube ID are one recording, not two choices.
        with suppress(ValueError):
            if yt := youtube_url(target):
                target = yt[0]
        origins = links.setdefault(target, [])
        origins.extend(o for o in parser.media_origins[value] if o not in origins)
    return links


def unresolved_recording(url: str, page_url: str, origins: list[str]) -> Candidate:
    """Type hints help selection; the actual media is still resolved on the next call."""
    family: Literal["page", "youtube", "audio", "video"] = "page"
    with suppress(ValueError):
        if youtube_url(url):
            family = "youtube"
    path = urlsplit(url).path.lower()
    if path.endswith((".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac")):
        family = "audio"
    elif path.endswith((".mp4", ".webm", ".mov")):
        family = "video"
    return Candidate(
        url=url,
        family=family,
        identity_evidence=[f"explicit_embed:{page_url}", *origins],
    )


@dataclass(frozen=True)
class Resolution:
    state: str
    candidates: tuple[Candidate, ...] = ()
    transcript: str | None = None
    gaps: tuple[str, ...] = ()
    # Only explicit cross-links, kept as provenance. No title similarity aliasing.
    aliases: tuple[str, ...] = ()
    raw_keys: tuple[str, ...] = ()
    segments: tuple[Segment, ...] = ()


def caption_text(value: str) -> tuple[str, tuple[Segment, ...]]:
    """Turn explicit publisher VTT/SRT cues into text with source-supplied timing."""
    stamp = r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})"
    cue = re.compile(rf"^\s*{stamp}\s+-->\s+.+$", re.M)
    matches = list(cue.finditer(canonical_text(value)))
    if not matches:
        return canonical_text(value), ()
    value = canonical_text(value)
    words: list[str] = []
    segments = []
    cursor = 0
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        body = value[match.end() : end].strip().split("\n\n", 1)[0]
        voice = re.search(r"<v(?:\.[^ >]+)?\s+([^>]+)>", body)
        body = unescape(re.sub(r"<[^>]+>", "", body)).strip()
        if not body:
            continue
        if words:
            words.append("\n")
            cursor += 1
        ts = float(int(match[1] or 0) * 3600 + int(match[2]) * 60 + int(match[3]))
        ts += int(match[4]) / 1000
        segments.append(
            Segment(
                start=cursor,
                end=cursor + len(body),
                speaker=voice[1] if voice else None,
                attribution="metadata" if voice else "unknown",
                time_s=ts,
                timing="source_supplied",
            )
        )
        words.append(body)
        cursor += len(body)
    return "".join(words), tuple(segments)


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
    """The Podcasting 2.0 JSON transcript: ``segments[]`` of speaker, startTime and body."""
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
        seconds = (
            float(start)
            if isinstance(start, int | float) and not isinstance(start, bool) and start >= 0
            else None
        )
        speaker = row.get("speaker")
        segments.append(
            Segment(
                start=cursor,
                end=cursor + len(text),
                speaker=str(speaker) if speaker else None,
                attribution="metadata" if speaker else "unknown",
                time_s=seconds,
                timing="source_supplied" if seconds is not None else "unavailable",
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
        elif tag in {"p", "br", "div", "li", "tr"}:
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
    """Use the matched episode's own transcript when its feed declares one; else keep the audio."""
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


def feed_candidates(xml: str, url: str) -> list[Candidate]:
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", xml, re.I):
        raise ValueError("XML entities/doctype not supported")
    root = ET.fromstring(xml)
    result = []
    if root.tag.endswith("feed"):
        ns = "{http://www.w3.org/2005/Atom}"
        for entry in root.findall(ns + "entry"):
            links = entry.findall(ns + "link")
            enclosure = next(
                (link.get("href") for link in links if link.get("rel") == "enclosure"), None
            )
            link = next(
                (link.get("href") for link in links if link.get("rel", "alternate") == "alternate"),
                None,
            )
            guid = entry.findtext(ns + "id")
            if enclosure:
                result.append(
                    Candidate(
                        url=link or enclosure,
                        title=entry.findtext(ns + "title") or "",
                        description=entry.findtext(ns + "summary") or "",
                        family="audio",
                        feed_url=url,
                        media_url=urljoin(url, enclosure),
                        episode_id=guid,
                        canonical_key="rss:" + content_hash(url + ":" + (guid or enclosure)),
                    )
                )
        return result
    parsed = parse_feed(xml)
    items = root.findall("channel/item")
    for ep, raw in zip(parsed.episodes, items, strict=True):
        if not ep.enclosure_url:
            continue
        guid = raw.findtext("guid")
        chosen = preferred_transcript(ep.transcripts)
        result.append(
            Candidate(
                url=ep.link or ep.enclosure_url,
                title=ep.title,
                description=ep.description or "",
                family="audio",
                duration_s=ep.duration_s,
                feed_url=url,
                episode_id=guid or (str(ep.number) if ep.number is not None else None),
                media_url=urljoin(url, ep.enclosure_url),
                canonical_key="rss:" + content_hash(url + ":" + (guid or ep.enclosure_url)),
                identity_evidence=[f"feed:{url}", f"episode_number:{ep.number}"],
                published_at=ep.published_at,
                transcript_url=urljoin(url, chosen[0]) if chosen else None,
                transcript_type=chosen[1] or None if chosen else None,
            )
        )
    return result


def match_episode(candidates: list[Candidate], hint: str | None, source_url: str) -> Resolution:
    exact = [
        c
        for c in candidates
        if c.url == source_url or c.url == hint or (hint is not None and c.episode_id == hint)
    ]
    if not exact and hint:
        number = re.fullmatch(r"(?:ep(?:isode)?\s*#?\s*|#)?(\d+)", hint.strip(), re.I)
        if number:
            exact = [
                c for c in candidates if f"episode_number:{int(number[1])}" in c.identity_evidence
            ]
        else:
            exact = [
                c
                for c in candidates
                if hint.casefold() in (c.title + " " + c.description).casefold()
            ]
    if not exact and len(candidates) == 1 and hint is None:
        exact = candidates
    if len(exact) == 1:
        return Resolution("resolved", tuple(exact))
    if exact:
        return Resolution("ambiguous", tuple(exact), gaps=("multiple_episode_matches",))
    return Resolution("no_match", tuple(candidates), gaps=("no_exact_episode_match",))


def resolve(
    caller: ProviderCaller,
    url: str,
    *,
    hint: str | None = None,
    visited: frozenset[str] = frozenset(),
    _response: HttpResponse | None = None,
) -> Resolution:
    url = public_url(url)
    if url in visited:
        return Resolution("unsupported", gaps=("resolution_cycle",))
    visited = visited | {url}
    yt = youtube_url(url)
    if yt:
        watch, key = yt
        response = _response or fetch(caller, watch)
        player = extract_player_response(response.body.decode("utf-8", errors="replace")) or {}
        raw_details = player.get("videoDetails")
        details = raw_details if isinstance(raw_details, dict) else {}
        raw_status = player.get("playabilityStatus")
        status = raw_status if isinstance(raw_status, dict) else {}
        raw_microformat = player.get("microformat")
        microformat = (
            raw_microformat.get("playerMicroformatRenderer", {})
            if isinstance(raw_microformat, dict)
            else {}
        )
        if (
            status.get("status") != "OK"
            or details.get("videoId") != key.removeprefix("youtube:")
            or details.get("isPrivate")
            or details.get("isUnlisted")
            or microformat.get("isUnlisted")
        ):
            return Resolution("unavailable", gaps=("youtube_public_access_unverified",))
        duration = int(details.get("lengthSeconds") or 0)
        if duration <= 0:
            return Resolution("unavailable", gaps=("duration_unknown",))
        return Resolution(
            "resolved",
            (
                Candidate(
                    url=watch,
                    title=details.get("title", ""),
                    description=details.get("shortDescription", ""),
                    family="youtube",
                    canonical_key=key,
                    duration_s=duration,
                    identity_evidence=[url],
                    recognized_subject_urls=list(
                        dict.fromkeys(
                            re.findall(
                                r"https://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?",
                                str(details.get("shortDescription", "")),
                            )
                        )
                    ),
                ),
            ),
            aliases=(url,),
        )
    if urlsplit(url).hostname == "podcasts.apple.com":
        match = re.search(r"/id(\d+)", urlsplit(url).path)
        if not match:
            return Resolution("unsupported", gaps=("apple_show_id_missing",))
        lookup = json.loads(
            fetch(caller, f"https://itunes.apple.com/lookup?id={match[1]}&entity=podcast").body
        )
        feed = next(
            (
                r.get("feedUrl")
                for r in lookup.get("results", [])
                if str(r.get("collectionId")) == match[1]
            ),
            None,
        )
        if feed:
            # An Apple episode id is not an RSS guid or an episode number. Unless the feed
            # explicitly links it (or the caller supplied an exact hint), do not guess.
            episode_hint = hint or (url if parse_qs(urlsplit(url).query).get("i") else None)
            return resolve(caller, feed, hint=episode_hint, visited=visited)
        return Resolution("no_match", gaps=("apple_feed_missing",))
    response = _response or fetch(caller, url, binary=True)
    final_url = public_url(response.headers.get("x-arv2-final-url", url))
    if final_url != url:
        result = resolve(caller, final_url, hint=hint, visited=visited, _response=response)
        if (
            result.state == "resolved"
            and result.candidates
            and result.candidates[0].feed_url != final_url
        ):
            return replace(result, aliases=(url, *result.aliases))
        return result
    mime = response.headers.get("content-type", "").split(";")[0].lower()
    if mime.startswith(("audio/", "video/")):
        return Resolution(
            "resolved",
            (
                Candidate(
                    url=url,
                    media_url=url,
                    family="audio" if mime.startswith("audio/") else "video",
                    canonical_key="media:" + content_hash(url),
                ),
            ),
        )
    body = response.body.decode("utf-8", errors="replace")
    if mime in {
        "application/rss+xml",
        "application/atom+xml",
        "application/xml",
        "text/xml",
    } or re.match(r"\s*(?:<\?xml[^>]+>\s*)?<(rss|feed)\b", body):
        return with_feed_transcript(caller, match_episode(feed_candidates(body, url), hint, url))
    parser = PageLinks()
    parser.feed(body)
    for obj in objects(parser.documents):
        kinds = obj.get("@type", [])
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if not set(kinds).intersection({"VideoObject", "AudioObject", "PodcastEpisode"}):
            continue
        media = obj.get("contentUrl") or obj.get("embedUrl")
        if isinstance(obj.get("transcript"), str) and obj["transcript"].strip():
            return Resolution(
                "resolved",
                (
                    Candidate(
                        url=url,
                        title=str(obj.get("name", "")),
                        family="transcript",
                        canonical_key="url:" + content_hash(url),
                        recognized_subject_urls=parser.subjects,
                    ),
                ),
                transcript=obj["transcript"],
                aliases=(url,),
            )
        if isinstance(media, str):
            parser.add_media(
                media,
                "html:json-ld:contentUrl" if obj.get("contentUrl") else "html:json-ld:embedUrl",
            )
    media_links = recording_links(parser, url)
    if len(media_links) > 1:
        return Resolution(
            "ambiguous",
            tuple(
                unresolved_recording(target, url, origins)
                for target, origins in media_links.items()
            ),
            gaps=("multiple_explicit_recordings",),
        )
    candidates = [*media_links, *[urljoin(url, f) for f in parser.feeds]]
    gaps = []
    # A publisher transcript link is explicit speech evidence; never use arbitrary page text.
    for link in parser.transcripts:
        target = urljoin(url, link)
        try:
            r = fetch(caller, target)
        except ValueError as exc:
            gaps.append(str(exc))
            continue
        if r.headers.get("content-type", "").split(";")[0] in {
            "text/plain",
            "text/vtt",
            "application/x-subrip",
        }:
            value, segments = caption_text(r.body.decode("utf-8", errors="replace"))
            if value.strip():
                return Resolution(
                    "resolved",
                    (
                        Candidate(
                            url=url,
                            title="",
                            family="transcript",
                            transcript_url=target,
                            canonical_key="url:" + content_hash(url),
                            recognized_subject_urls=parser.subjects,
                        ),
                    ),
                    transcript=value,
                    aliases=(url, target),
                    segments=segments,
                )
    for target in dict.fromkeys(candidates):
        if target in visited:
            continue
        try:
            result = resolve(caller, target, hint=hint or url, visited=visited)
        except ValueError as exc:
            gaps.append(str(exc))
            continue
        if result.state in {"resolved", "ambiguous"}:
            return Resolution(
                result.state,
                tuple(
                    c.model_copy(
                        update={
                            "identity_evidence": list(
                                dict.fromkeys(
                                    [
                                        *c.identity_evidence,
                                        *(
                                            [f"explicit_embed:{url}", *media_links[target]]
                                            if target in media_links
                                            else []
                                        ),
                                    ]
                                )
                            ),
                            "recognized_subject_urls": list(
                                dict.fromkeys([*c.recognized_subject_urls, *parser.subjects])
                            ),
                        }
                    )
                    for c in result.candidates
                ),
                result.transcript,
                result.gaps,
                (url, *result.aliases),
                segments=result.segments,
            )
        gaps.extend(result.gaps)
    return Resolution("unsupported", gaps=tuple(gaps or ["no_supported_recording_link"]))
