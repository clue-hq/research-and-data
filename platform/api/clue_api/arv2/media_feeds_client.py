"""Podcast RSS and the YouTube probe — resolving a media mention to a fetchable artifact.

This is the free, deterministic half of the media lane. Nothing here transcribes or reasons: it
turns "Sanaz was on the Boardroom Club podcast" into an MP3 URL with a known duration, and
"Nick Fisher is Cocktail Chemistry" into a video id with a known length, so the paid Gemini pass
downstream knows exactly what it is about to spend media-seconds on.

Three of Appendix A's laws shape the module:

* **Law 9 — free-first, and a known URL is fetched, never searched for.** Every call here is an
  unpaid GET with the browser user-agent; the episode is found in the feed the account already
  named, not by asking a search provider which episode it might have been.
* **Law 10 — one broad call never decides something does not exist.** :func:`find_episode` is
  exact: an episode number or a case-insensitive substring, no fuzzy scoring. The
  proof-of-concept's word-overlap scorer confidently returned EP280 when asked for EP265, and a
  wrong episode is worse than no episode.
* **Law 11's walled-media clause — LinkedIn-native and X-native video is never fetched.**
  :func:`reject_native_video` is the refusal, raised before any request is built.

The YouTube caption endpoint (``timedtext``) is **dead** — HTTP 200 with an empty body on every
documented form — so it is not called. Indexed page text comes from a
:data:`PageTextFetcher` the caller supplies instead.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

from clue_api.arv2.calls import CallCost, CallSpec, ProviderCaller
from clue_api.arv2.errors import Arv2Error, ProviderTransportError, RawParseError
from clue_api.arv2.sinks import sha256_hex
from clue_api.arv2.transport import BROWSER_USER_AGENT, HttpRequest

#: What a podcast host expects to be asked for. A bare ``*/*`` gets an HTML landing page from
#: several hosts; this is the header the proof-of-concept fetched every feed with.
FEED_ACCEPT = "application/rss+xml,application/xml;q=0.9,*/*;q=0.8"

#: The iTunes podcast namespace — where the episode number and the duration actually live.
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"

#: The Atom namespace, for the ``rel="self"`` link a feed uses to name its own canonical URL.
ATOM_NS = "http://www.w3.org/2005/Atom"

#: Hosts whose only media artifact is native video, which cannot be fetched at all (law 11).
#: Membership is decided on the **host**, not the path: a URL shape is no evidence either way,
#: and guessing wrong here means fetching something we promised never to fetch.
WALLED_MEDIA_HOSTS: frozenset[str] = frozenset({"linkedin.com", "x.com", "twitter.com"})

#: Hosts that serve a YouTube watch page.
YOUTUBE_HOSTS: frozenset[str] = frozenset({"youtube.com", "youtu.be", "youtube-nocookie.com"})

#: Ceiling on a derived ledger label, so the raw record's filename always fits on disk.
MAX_LABEL_CHARS = 60

FEED_TIMEOUT_S = 60.0
WATCH_TIMEOUT_S = 45.0
ENCLOSURE_TIMEOUT_S = 300.0
#: A HEAD to read an enclosure's ``Content-Length`` is a metadata round-trip, not a download.
ENCLOSURE_HEAD_TIMEOUT_S = 30.0

#: The largest feed document this client will parse. Feeds are third-party XML we do not control,
#: and ``ET.fromstring`` builds the whole tree in memory; a show with thousands of episodes (or a
#: host serving something that is not a feed at all) should be refused with the raw record named,
#: not turned into an unbounded allocation on a fleet worker. Five megabytes is ~an order of
#: magnitude above the largest real podcast feed observed.
MAX_FEED_BYTES = 5_000_000

#: The three URL forms a video id appears in, ported verbatim from the proof-of-concept probe.
_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/live/)([A-Za-z0-9_-]{11})")

#: ``Ep 297`` / ``#297`` / ``Episode 297`` at the *start* of an episode title. Anchored on
#: purpose: a bare number anywhere in a title is a year, a headcount or a funding round far more
#: often than it is an episode number.
_TITLE_NUMBER_RE = re.compile(r"^\s*(?:#|ep(?:isode)?\.?\s*#?)\s*(\d+)\b", re.IGNORECASE)

#: Both spellings of the player-response assignment seen in served watch-page HTML.
_PLAYER_RESPONSE_RE = re.compile(r'ytInitialPlayerResponse(?:"\])?\s*=\s*\{')

#: Maps each requested URL to the indexed page text a contents provider holds for it. The Exa
#: contents client satisfies this; so does a ten-line test fetcher. Declaring the seam this way
#: is what keeps this module free of any provider knowledge at all.
PageTextFetcher = Callable[[Sequence[str]], Mapping[str, str]]


class UnsupportedMediaHost(Arv2Error):
    """The URL is on a host whose media is walled — LinkedIn-native or X-native video.

    Raised *before* a request is built, so the law "never fetch LinkedIn- or X-native video" is a
    property of the code path rather than a rule someone remembered to follow.
    """

    def __init__(self, url: str, host: str) -> None:
        super().__init__(f"{host} serves only native video, which is never fetched: {url}")
        self.url = url
        self.host = host


class EnclosureTooLarge(Arv2Error):
    """The episode's audio is bigger than the caller is willing to download.

    Carries both numbers so a supervisor can raise the budget deliberately rather than guess.
    ``declared`` is ``True`` when the feed's own ``length`` attribute triggered the refusal, in
    which case no bytes were transferred at all.
    """

    def __init__(self, url: str, size_bytes: int, max_bytes: int, *, declared: bool) -> None:
        source = "feed-declared" if declared else "downloaded"
        super().__init__(f"{source} enclosure is {size_bytes} bytes, over {max_bytes}: {url}")
        self.url = url
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes
        self.declared = declared


class MediaFetchError(Arv2Error):
    """A feed, watch page or enclosure answered with a non-2xx status.

    Carries the ``raw_ref`` of the record the wrapper already wrote (law 1), so the refusal is
    replayable from disk without re-fetching anything.
    """

    def __init__(self, url: str, status: int, raw_ref: str | None) -> None:
        super().__init__(f"{url} returned HTTP {status} (raw_ref={raw_ref})")
        self.url = url
        self.status = status
        self.raw_ref = raw_ref


@dataclass(frozen=True)
class Episode:
    """One ``<item>`` of a podcast feed, reduced to what the media lane actually spends on."""

    number: int | None
    title: str
    enclosure_url: str | None
    enclosure_bytes: int | None
    duration_s: int | None
    published_at: datetime | None
    link: str | None
    description: str | None


@dataclass(frozen=True)
class Podcast:
    """A parsed feed: the show and its episodes, in the order the document listed them.

    Feed order is preserved rather than sorted: a feed's own ordering is usually newest-first but
    is not guaranteed to be, and re-sorting on a ``pubDate`` that :func:`parse_feed` may have read
    as ``None`` would silently move undated episodes to one end.

    ``cost`` is the fetch's money view. Feeds are free (law 9), so it is a real row reading
    ``cost_source='free'`` — not an absent one: "this call cost nothing" and "nobody recorded
    this call" are different facts and the ledger has to be able to tell them apart. It is
    ``None`` only on a :class:`Podcast` built by :func:`parse_feed`, which parses a document
    somebody else fetched.
    """

    title: str
    feed_url: str
    episodes: tuple[Episode, ...]
    cost: CallCost | None = None


@dataclass(frozen=True)
class AudioFile:
    """A downloaded enclosure on local disk, content-addressed.

    ``cost`` is the download's money view — free (law 9), so ``cost_source='free'``. The optional
    ``HEAD`` probe that may precede the download is its own free row and is not folded in here:
    two requests are two rows, and a caller counting calls must see both. It is ``None`` only on
    an :class:`AudioFile` a caller assembled without going through :func:`download_enclosure`.
    """

    path: Path
    bytes: int
    sha256: str
    duration_s: int | None
    content_type: str | None
    cost: CallCost | None = None


@dataclass(frozen=True)
class YouTubeMeta:
    """What the watch page's own player response says about a video.

    ``cost`` is the watch-page fetch's money view — free (law 9), so ``cost_source='free'``.
    """

    video_id: str | None
    title: str | None
    length_s: int | None
    cost: CallCost


@dataclass(frozen=True)
class YouTubeWords:
    """Indexed page text for a watch page — the transcript substitute when captions are dead.

    ``title`` is optional because a :data:`PageTextFetcher` yields URL-keyed text and nothing
    else; a caller that also ran :func:`youtube_metadata` passes the real title in.

    ``cost`` is ``None`` unless the caller supplied it. This is the one value in the lane whose
    request this module does not make: the page text comes from a caller-supplied
    :data:`PageTextFetcher`, so only the caller knows what its own provider charged. A fabricated
    zero here would be a claim about a call we never saw.
    """

    url: str
    title: str | None
    text: str
    cost: CallCost | None = None


# -- podcast feeds -----------------------------------------------------------------------------


def parse_duration(text: str | None) -> int | None:
    """``H:MM:SS``, ``MM:SS`` or bare seconds → whole seconds. Anything else is ``None``.

    ``None`` rather than ``0``: a duration we could not read is not a zero-length episode, and
    the media-seconds ceiling downstream must not be handed a fabricated zero.
    """
    if text is None:
        return None
    parts = text.strip().split(":")
    if not parts or len(parts) > 3:
        return None
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    if any(number < 0 for number in numbers):
        return None
    total = 0.0
    for number in numbers:
        total = total * 60 + number
    return int(total)


def episode_number_from_title(title: str) -> int | None:
    """The number in a leading ``Ep 297`` / ``#297`` / ``Episode 297``, else ``None``.

    Used only when the feed omits ``itunes:episode``. The pattern is anchored at the start of the
    title so that a year or a metric elsewhere in the title can never be read as an episode.
    """
    match = _TITLE_NUMBER_RE.match(title)
    return int(match.group(1)) if match else None


def _text(element: ET.Element | None) -> str | None:
    """The stripped text of an element, or ``None`` when it is absent or empty."""
    if element is None or element.text is None:
        return None
    stripped = element.text.strip()
    return stripped or None


def _published(raw: str | None) -> datetime | None:
    """An RFC-2822 ``pubDate`` as a datetime; an unparseable date is ``None``, never today."""
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw.strip())
    except (TypeError, ValueError):
        return None


def _parse_item(item: ET.Element) -> Episode:
    """One ``<item>`` → :class:`Episode`. The episode number prefers the tag over the title."""
    title = _text(item.find("title")) or ""
    enclosure = item.find("enclosure")
    enclosure_url = enclosure.get("url") if enclosure is not None else None
    declared_length = enclosure.get("length") if enclosure is not None else None
    try:
        enclosure_bytes = int(declared_length) if declared_length else None
    except ValueError:
        enclosure_bytes = None

    tagged = _text(item.find(f"{{{ITUNES_NS}}}episode"))
    number: int | None = None
    if tagged is not None:
        try:
            number = int(tagged)
        except ValueError:
            number = None
    if number is None:
        number = episode_number_from_title(title)

    return Episode(
        number=number,
        title=title,
        enclosure_url=enclosure_url,
        enclosure_bytes=enclosure_bytes,
        duration_s=parse_duration(_text(item.find(f"{{{ITUNES_NS}}}duration"))),
        published_at=_published(_text(item.find("pubDate"))),
        link=_text(item.find("link")),
        description=_text(item.find("description")),
    )


def _parse_feed(xml: str, raw_ref: str | None) -> Podcast:
    """The parser proper. ``raw_ref`` is threaded in so a failure names the record on disk.

    The size cap is applied **before** ``ET.fromstring``, because the element tree is where the
    memory actually goes: the document itself is already in hand, but parsing it multiplies it. A
    feed is third-party XML on a fleet worker, so an oversized one is a typed refusal naming the
    saved record — never an unbounded allocation.
    """
    size = len(xml.encode("utf-8"))
    if size > MAX_FEED_BYTES:
        raise RawParseError(raw_ref, f"feed is {size} bytes, over the {MAX_FEED_BYTES} cap")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise RawParseError(raw_ref, f"feed is not parseable XML: {exc}") from exc

    channel = root.find("channel")
    if channel is None:
        raise RawParseError(raw_ref, "feed has no <channel> element")

    feed_url = ""
    for link in channel.findall(f"{{{ATOM_NS}}}link"):
        if link.get("rel") == "self" and link.get("href"):
            feed_url = link.get("href") or ""
            break

    return Podcast(
        title=_text(channel.find("title")) or "",
        feed_url=feed_url,
        episodes=tuple(_parse_item(item) for item in channel.findall("item")),
    )


def parse_feed(xml: str) -> Podcast:
    """Parse an RSS document into a :class:`Podcast` with ``xml.etree`` and the iTunes namespace.

    ``feed_url`` comes from the feed's own ``<atom:link rel="self">`` when it publishes one;
    :func:`fetch_feed` overwrites it with the URL actually fetched, which is the stronger truth.
    """
    return _parse_feed(xml, None)


def _label_for(url: str) -> str:
    """A stable, human-readable ledger label derived from the URL — host plus last path segment.

    Truncated to :data:`MAX_LABEL_CHARS`: a podcast enclosure URL percent-encodes the whole CDN
    address into its last segment, and :class:`~clue_api.arv2.sinks.FileRawSink` builds a
    filename out of the label — an untruncated one lands within a few bytes of the filesystem's
    255-byte limit, so one longer URL would make law 1's raw record unwritable.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "unknown").removeprefix("www.")
    segment = parts.path.rstrip("/").rsplit("/", 1)[-1]
    return f"{host}-{segment}"[:MAX_LABEL_CHARS] if segment else host[:MAX_LABEL_CHARS]


def fetch_feed(url: str, caller: ProviderCaller) -> Podcast:
    """Fetch and parse a podcast feed. Free (law 9), browser user-agent, through the wrapper.

    ``feed_url`` on the result is the URL actually requested, not whatever the document claims.
    """
    spec = CallSpec(
        provider="rss",
        operation="feed",
        label=_label_for(url),
        request=HttpRequest(
            method="GET",
            url=url,
            headers={"User-Agent": BROWSER_USER_AGENT, "Accept": FEED_ACCEPT},
            timeout_s=FEED_TIMEOUT_S,
        ),
    )
    result = caller.call(spec)
    if not 200 <= result.response.status < 300:
        raise MediaFetchError(url, result.response.status, result.raw_ref)
    return replace(_parse_feed(result.text(), result.raw_ref), feed_url=url, cost=result.call_cost)


def find_episode(
    podcast: Podcast,
    *,
    number: int | None = None,
    title_contains: str | None = None,
) -> Episode | None:
    """Find one episode by exact number, then by case-insensitive substring. No fuzzy matching.

    Law 10 in miniature. The proof-of-concept scored episodes by shared words and handed back
    EP280 when asked for EP265 — a confident wrong answer. Here, an episode number is an equality
    test and a title is a substring test; when neither matches, the answer is ``None``, which is
    the honest one.
    """
    if number is None and title_contains is None:
        raise ValueError("find_episode needs a number or a title_contains; it will not guess")
    if number is not None:
        for episode in podcast.episodes:
            if episode.number == number:
                return episode
    if title_contains is not None:
        needle = title_contains.casefold()
        for episode in podcast.episodes:
            if needle in episode.title.casefold():
                return episode
    return None


def _head_content_length(url: str, caller: ProviderCaller) -> int | None:
    """The enclosure's ``Content-Length`` per a HEAD, or ``None`` when the host does not say.

    Goes through the wrapper like every other request in the lane — free (law 9), so the estimate
    is zero, but the attempt still gets a raw record and a ledger row. A non-2xx, a missing header
    or an unreadable one all yield ``None``: this is a cheap *opportunity* to refuse early, never
    a gate the download depends on, so an uninformative HEAD must not fail the item.
    """
    # One attempt, no retry statuses: this probe is an opportunity, not a dependency, so a flaky
    # host must cost neither the 12·(n+1) s backoff nor the download itself (re-review, 2026-09-07).
    try:
        result = caller.call(
            CallSpec(
                provider="live_http",
                operation="enclosure-head",
                label=_label_for(url),
                request=HttpRequest(
                    method="HEAD",
                    url=url,
                    headers={"User-Agent": BROWSER_USER_AGENT, "Accept": "audio/*,*/*;q=0.8"},
                    timeout_s=ENCLOSURE_HEAD_TIMEOUT_S,
                ),
                binary=True,
                max_attempts=1,
                retry_statuses=frozenset(),
            )
        )
    except ProviderTransportError:
        return None
    if not 200 <= result.response.status < 300:
        return None
    stated = result.response.headers.get("content-length")
    if stated is None:
        return None
    try:
        return int(stated.strip())
    except ValueError:
        return None


def download_enclosure(
    episode: Episode,
    dest: Path,
    caller: ProviderCaller,
    *,
    max_bytes: int,
) -> AudioFile:
    """Download an episode's audio to ``dest``, refusing anything over ``max_bytes``.

    Three checks, cheapest first. The feed's declared ``length`` is checked **first**, so an
    over-budget episode costs no bandwidth at all. When the feed declares no length, a **HEAD** is
    issued and its ``Content-Length`` checked, so the common case of an undeclared enclosure still
    costs one metadata round-trip rather than the whole file. The transferred size is checked
    again afterwards, because neither a feed nor a host is obliged to tell the truth.

    That last check is a *refusal*, not a bound on memory: the ``Transport`` seam returns a fully
    materialised body, so a host that both lies about ``Content-Length`` and serves a huge file
    is still read into memory once. A streaming transport is the real fix and is recorded as R2
    work in the package README; the HEAD closes the case we can actually see coming.

    ``dest`` is the file to write, and its parent is created. The call is ``binary=True``, so the
    raw record carries the body's sha and byte count with a ``.bin`` sidecar instead of inlining
    megabytes of audio into JSON.
    """
    url = episode.enclosure_url
    if not url:
        raise ValueError(f"episode {episode.title!r} has no enclosure to download")
    if episode.enclosure_bytes is not None:
        if episode.enclosure_bytes > max_bytes:
            raise EnclosureTooLarge(url, episode.enclosure_bytes, max_bytes, declared=True)
    else:
        declared = _head_content_length(url, caller)
        if declared is not None and declared > max_bytes:
            raise EnclosureTooLarge(url, declared, max_bytes, declared=True)

    spec = CallSpec(
        provider="live_http",
        operation="enclosure",
        label=_label_for(url),
        request=HttpRequest(
            method="GET",
            url=url,
            headers={"User-Agent": BROWSER_USER_AGENT, "Accept": "audio/*,*/*;q=0.8"},
            timeout_s=ENCLOSURE_TIMEOUT_S,
        ),
        binary=True,
    )
    result = caller.call(spec)
    if not 200 <= result.response.status < 300:
        raise MediaFetchError(url, result.response.status, result.raw_ref)

    body = result.response.body
    if len(body) > max_bytes:
        raise EnclosureTooLarge(url, len(body), max_bytes, declared=False)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return AudioFile(
        path=dest,
        bytes=len(body),
        sha256=sha256_hex(body),
        duration_s=episode.duration_s,
        content_type=result.response.headers.get("content-type"),
        cost=result.call_cost,
    )


# -- YouTube -----------------------------------------------------------------------------------


def _host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _host_matches(host: str, domains: frozenset[str]) -> str | None:
    """The domain in ``domains`` that ``host`` belongs to, or ``None``. Subdomains count."""
    for domain in domains:
        if host == domain or host.endswith("." + domain):
            return domain
    return None


def is_youtube(url: str) -> bool:
    """Is this a YouTube URL? Host-based, so ``youtu.be`` and ``m.youtube.com`` both count."""
    return _host_matches(_host_of(url), YOUTUBE_HOSTS) is not None


def reject_native_video(url: str) -> None:
    """Refuse a walled media host before anything is fetched (law 11's walled-media clause).

    LinkedIn and X serve their video only to their own player; there is no artifact to download
    and no lawful way to take one. The test is the **host**, not the path, because the URL of a
    post carrying native video is indistinguishable from one that does not — and the direction to
    be wrong in is "refused something fetchable", never "fetched something walled".
    """
    host = _host_of(url)
    walled = _host_matches(host, WALLED_MEDIA_HOSTS)
    if walled is not None:
        raise UnsupportedMediaHost(url, walled)


def video_id(url: str) -> str | None:
    """The eleven-character video id in a watch, ``youtu.be`` or ``/live/`` URL."""
    match = _VIDEO_ID_RE.search(url)
    return match.group(1) if match else None


def _json_object_at(text: str, start: int) -> str | None:
    """The balanced ``{...}`` beginning at ``start``, or ``None`` if it never closes.

    String- and escape-aware on purpose: a watch page's player response is full of titles
    containing braces, and a naive depth counter (or a non-greedy regex) truncates the object
    mid-way and turns a perfectly good page into a parse error.
    """
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def extract_player_response(html: str) -> Mapping[str, object] | None:
    """The ``ytInitialPlayerResponse`` object embedded in a watch page, or ``None``."""
    match = _PLAYER_RESPONSE_RE.search(html)
    if match is None:
        return None
    blob = _json_object_at(html, match.end() - 1)
    if blob is None:
        return None
    try:
        parsed = json.loads(blob)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def youtube_metadata(watch_url: str, caller: ProviderCaller) -> YouTubeMeta:
    """Read a video's title and length from its own watch page. Free (law 9), no API key.

    The caption endpoint is not touched: YouTube's public ``timedtext`` service answers 200 with
    an empty body on every documented form, so calling it would only manufacture a raw record of
    nothing. A page that serves no ``ytInitialPlayerResponse`` (a consent wall, a bot check)
    raises :class:`RawParseError` naming the saved record, because the served HTML is the
    evidence and it is already on disk.
    """
    reject_native_video(watch_url)
    spec = CallSpec(
        provider="youtube",
        operation="watch",
        label=video_id(watch_url) or _label_for(watch_url),
        request=HttpRequest(
            method="GET",
            url=watch_url,
            headers={"User-Agent": BROWSER_USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
            timeout_s=WATCH_TIMEOUT_S,
        ),
    )
    result = caller.call(spec)
    if not 200 <= result.response.status < 300:
        raise MediaFetchError(watch_url, result.response.status, result.raw_ref)

    player = extract_player_response(result.text())
    if player is None:
        raise RawParseError(result.raw_ref, "ytInitialPlayerResponse not present in served HTML")

    details = player.get("videoDetails")
    details = details if isinstance(details, dict) else {}
    raw_title = details.get("title")
    raw_length = details.get("lengthSeconds")
    try:
        length_s = int(raw_length) if raw_length is not None else None
    except (TypeError, ValueError):
        length_s = None
    return YouTubeMeta(
        video_id=video_id(watch_url),
        title=raw_title if isinstance(raw_title, str) else None,
        length_s=length_s,
        cost=result.call_cost,
    )


def youtube_words(
    watch_url: str,
    page_text: PageTextFetcher,
    *,
    title: str | None = None,
    cost: CallCost | None = None,
) -> YouTubeWords:
    """Indexed page text for a watch page, via a caller-supplied contents fetcher.

    This is the caption fallback: ``timedtext`` is dead, so the words — when there are any — come
    from a provider's indexed copy of the page. An empty result is a legitimate terminal answer
    (law 12), returned as empty text rather than raised: plenty of watch pages carry no indexed
    transcript, and that is a fact about the video, not a failure of the fetch.

    ``title`` is optional because a :data:`PageTextFetcher` returns URL-keyed text only; a caller
    that already ran :func:`youtube_metadata` passes the real title through. ``cost`` is the same
    kind of pass-through: the fetcher makes the request, so only its owner can say what it cost,
    and this function will not invent a number for a call it did not make.
    """
    if not is_youtube(watch_url):
        raise ValueError(f"youtube_words expects a YouTube watch URL, got {watch_url!r}")
    fetched = page_text([watch_url])
    normalized = {key.rstrip("/"): value for key, value in fetched.items()}
    text = normalized.get(watch_url.rstrip("/")) or ""
    return YouTubeWords(url=watch_url, title=title, text=text, cost=cost)
