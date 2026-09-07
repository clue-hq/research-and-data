"""The free ATS job-board client — Ashby, Greenhouse and Lever, read never guessed.

A company's public job board is the cheapest high-value account signal ARV2 has: it answers "is
this req still open, and what is this company staffing right now" for $0 in about a second. All
three providers serve it over an unauthenticated GET, so every call here carries a zero estimate
and still gets the full Appendix A treatment — a raw record per attempt and both ledger rows —
because "free" is a cost, not an exemption from the money trail.

The one rule this module exists to enforce is **slugs are read, never guessed**. The smoke test
(``.context/arv2-smoke-cluehq/SMOKE-TEST-REPORT.md`` §"Eight ATS slug guesses returned 404")
burned eight calls on plausible-looking slugs and learned nothing from any of them: a 404 from a
guessed slug is indistinguishable from a company that has no board, so a guess can only ever
manufacture a false negative. :func:`find_board` therefore reads the slug out of a link the
company itself published, and returns ``None`` — never a guess — when it finds no such link.

Everything here goes through :class:`~clue_api.arv2.calls.ProviderCaller`; this module opens no
socket of its own.
"""

from __future__ import annotations

import html as html_entities
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

from clue_api.arv2.calls import CallCost, CallSpec, ProviderCaller
from clue_api.arv2.errors import Arv2Error, ProviderTransportError
from clue_api.arv2.transport import BROWSER_USER_AGENT, HttpRequest

#: The three public boards ARV2 reads. Each serves a JSON endpoint with no key and no quota.
AtsKind = Literal["ashby", "greenhouse", "lever"]

#: Career-page candidates tried, in this order, when the homepage itself names no board.
CAREER_PATHS: tuple[str, ...] = (
    "/careers",
    "/careers/",
    "/jobs",
    "/company/careers",
    "/about/careers",
)

#: Hard cap on candidate career pages per company (the homepage is fetched on top of this).
#: Board hunting is a *cheap* signal; an unbounded crawl would stop being one.
MAX_CANDIDATE_PAGES = 6

#: Timeout for a board API call. These endpoints answer in well under a second when they answer.
BOARD_TIMEOUT_S = 45.0

#: Timeout for a company page. Marketing sites are slower and more variable than JSON APIs.
PAGE_TIMEOUT_S = 30.0

_SLUG = r"([A-Za-z0-9][A-Za-z0-9._-]*)"

#: First path segments that are part of a provider's own routing, never a company slug. Without
#: this, ``boards.greenhouse.io/embed/job_board?for=acme`` would yield the board "embed".
_RESERVED_SLUGS: frozenset[str] = frozenset({"embed", "job_board", "jobs", "boards", "v0", "v1"})

#: Ordered detection patterns. Order matters: the ``embed`` forms must be tried before the bare
#: ``<host>/<slug>`` forms that would otherwise match their routing segment. ``(?<![\w.-])``
#: anchors each host so ``boards.greenhouse.io`` cannot match inside ``boards-api.greenhouse.io``.
_BOARD_PATTERNS: tuple[tuple[AtsKind, re.Pattern[str]], ...] = (
    (
        "greenhouse",
        re.compile(
            r"(?<![\w.-])(?:[\w.-]*\.)?greenhouse\.io/embed/job_board(?:/js)?"
            r"[^\"'\s<>]*[?&]for=" + _SLUG,
            re.IGNORECASE,
        ),
    ),
    (
        "greenhouse",
        re.compile(r"(?<![\w.-])boards-api\.greenhouse\.io/v1/boards/" + _SLUG, re.IGNORECASE),
    ),
    (
        "greenhouse",
        re.compile(r"(?<![\w.-])job-boards\.greenhouse\.io/" + _SLUG, re.IGNORECASE),
    ),
    (
        "greenhouse",
        re.compile(r"(?<![\w.-])boards\.greenhouse\.io/" + _SLUG, re.IGNORECASE),
    ),
    (
        "ashby",
        re.compile(
            r"(?<![\w.-])api\.ashbyhq\.com/posting-api/job-board/" + _SLUG,
            re.IGNORECASE,
        ),
    ),
    ("ashby", re.compile(r"(?<![\w.-])jobs\.ashbyhq\.com/" + _SLUG, re.IGNORECASE)),
    ("lever", re.compile(r"(?<![\w.-])api\.lever\.co/v0/postings/" + _SLUG, re.IGNORECASE)),
    ("lever", re.compile(r"(?<![\w.-])jobs\.lever\.co/" + _SLUG, re.IGNORECASE)),
)

#: ``<a href="...">text</a>`` — enough to read a navigation bar without a parser dependency.
_ANCHOR = re.compile(
    r"<a\b[^>]*\bhref=[\"']([^\"'>]+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL
)

_TAG = re.compile(r"<[^>]+>")
_BLOCK_BREAK = re.compile(r"</(?:p|div|li|tr|h[1-6])\s*>|<br\s*/?>", re.IGNORECASE)
_BLANK_RUN = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t]+")

#: A href pointing at one of these is an asset, not a careers page. Filtering them keeps the
#: six-page budget for pages that could actually carry a board link (probook.ai's homepage links
#: ``/v5/careers-office.jpg``, whose path contains "careers" and whose body never will).
_ASSET_SUFFIXES: tuple[str, ...] = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".css",
    ".js",
    ".json",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".mp4",
    ".zip",
)


class BoardNotFound(Arv2Error):
    """The board endpoint answered 404: this ``(kind, slug)`` pair does not exist.

    Typed rather than a crash because a missing board is a *normal* research outcome — the
    company moved ATS, closed its board, or (the thing this module refuses to do) somebody
    guessed the slug. The caller records an honest zero-yield, and ``url`` says exactly what was
    asked so the negative is replayable.
    """

    def __init__(self, kind: str, slug: str, url: str) -> None:
        super().__init__(f"no {kind} board at {url}")
        self.kind = kind
        self.slug = slug
        self.url = url


class BoardFetchFailed(Arv2Error):
    """The board endpoint answered a non-2xx that is not a 404 — the board's state is unknown.

    Kept distinct from :class:`BoardNotFound` on purpose: "there is no board" and "the provider
    would not tell us today" are different facts, and collapsing them would let a 503 be recorded
    as a company that stopped hiring.
    """

    def __init__(self, kind: str, slug: str, url: str, status: int) -> None:
        super().__init__(f"{kind} board {slug} returned HTTP {status} ({url})")
        self.kind = kind
        self.slug = slug
        self.url = url
        self.status = status


@dataclass(frozen=True)
class AtsBoard:
    """A board reference that was *read* off a page, not constructed from a company name.

    ``source_url`` is the page the slug was read from. It is the provenance of the whole record:
    with it, "why do we think this company's Ashby board is ``zafran-security``" is answerable by
    re-fetching one URL rather than by trusting the pipeline.
    """

    kind: AtsKind
    slug: str
    source_url: str


@dataclass(frozen=True)
class JobPosting:
    """One posting, in the shape the research lane reads, plus the provider's own record.

    Every derived field is optional because each provider omits a different subset, and a board
    that does not publish (say) a compensation band must produce ``None`` rather than an invented
    one. ``provider_fields`` carries the untouched provider record so nothing is lost by the
    normalisation and a later reader never has to go back to the raw file to find one key.
    """

    title: str | None
    department: str | None
    team: str | None
    location: str | None
    published_at: date | None
    days_open: int | None
    is_listed: bool | None
    compensation: str | None
    description_plain: str | None
    url: str | None
    apply_url: str | None
    provider_fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class BoardPostings:
    """A board fetch's result: the normalised postings plus the references that audit them.

    ``cost`` is the whole money view of the fetch that produced these postings — free, on every
    board this client knows, and labelled ``cost_source='free'`` rather than left to be inferred.
    ``raw_ref`` and ``ledger_row_id`` are kept as their own fields because callers already read
    them; they are the same two references ``cost`` carries.
    """

    board: AtsBoard
    url: str
    postings: tuple[JobPosting, ...]
    raw_ref: str | None
    ledger_row_id: str
    cost: CallCost


def board_url(board: AtsBoard) -> str:
    """The exact public endpoint for a board — the three URLs the brief pins, verbatim."""
    if board.kind == "ashby":
        return (
            f"https://api.ashbyhq.com/posting-api/job-board/{board.slug}?includeCompensation=true"
        )
    if board.kind == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{board.slug}/jobs?content=true"
    return f"https://api.lever.co/v0/postings/{board.slug}?mode=json"


def detect_boards(html: str, page_url: str) -> list[AtsBoard]:
    """Every board reference this page publishes, in the order it publishes them.

    Enforces "read, never guessed": the only slugs that can come out of here are substrings of
    ``html``. The page is first unescaped twice over — HTML entities (``&#x2F;``) and JavaScript
    string escapes (``https:\\/\\/jobs.ashbyhq.com\\/acme``) — because a slug that a framework
    happened to serialise into a JSON payload is just as much a published fact as one in an
    ``href``, and reading only raw ``href``s would miss most modern careers pages.

    Duplicates collapse on ``(kind, slug)``: one board named eleven times is one board.
    """
    scannable = html_entities.unescape(html).replace("\\/", "/")
    found: list[AtsBoard] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern in _BOARD_PATTERNS:
        for match in pattern.finditer(scannable):
            slug = match.group(1)
            if slug.lower() in _RESERVED_SLUGS:
                continue
            key = (kind, slug)
            if key in seen:
                continue
            seen.add(key)
            found.append(AtsBoard(kind=kind, slug=slug, source_url=page_url))
    return found


def career_page_candidates(homepage_html: str, homepage_url: str) -> list[str]:
    """Career-page URLs worth trying for this company, best-evidenced first, capped at six.

    **The homepage's own links come first, then the fixed paths.** A link this company published,
    whose path or anchor text says "careers", is *evidence about this company*; a fixed path is a
    guess about companies in general. With five fixed paths under a six-page cap, ordering the
    guesses first meant at most one evidenced link was ever tried — and the evidenced link is
    exactly what rescues a site whose careers section is not at a conventional path (probook.ai
    publishes its board under ``/company``, reachable only via an anchor whose *text*, not path,
    says "Careers"). The fixed paths still follow, and still carry most companies, because a site
    that links its careers page from the homepage usually links it at a conventional path anyway,
    so the two lists overlap and dedupe rather than compete.

    Assets and off-site links are dropped: the budget is small and exists to be spent on pages
    that could plausibly carry a board link.
    """
    origin = _origin(homepage_url)
    evidenced: list[str] = []
    for href, text in _anchor_links(homepage_html):
        absolute = _absolutise(href, homepage_url)
        if absolute is None or _origin(absolute) != origin:
            continue
        path = urlsplit(absolute).path.lower()
        if not _mentions_careers(path) and not _mentions_careers(text):
            continue
        if path.endswith(_ASSET_SUFFIXES):
            continue
        evidenced.append(absolute)
    fixed = [urljoin(origin, path) for path in CAREER_PATHS]
    return _dedupe([*evidenced, *fixed])[:MAX_CANDIDATE_PAGES]


def find_board(company_url: str, caller: ProviderCaller) -> AtsBoard | None:
    """The company's own published board, or ``None``. Never a guessed slug.

    Fetches the homepage, then up to :data:`MAX_CANDIDATE_PAGES` career-page candidates derived
    from it, each as a free ``live_http`` call through the wrapper, and returns the first board
    any of them names. ``None`` means "no page this company publishes names a board" — which is
    a *finding*, and a far more useful one than a 404 from a slug nobody published.

    A candidate page that fails below the HTTP layer is skipped rather than fatal: the candidate
    list is speculative by construction, so one dead guess must not sink the search. A homepage
    that cannot be reached is a different matter and propagates, because the caller named it.
    """
    homepage_url = _with_scheme(company_url)
    homepage = _fetch_page(homepage_url, caller)
    boards = detect_boards(homepage, homepage_url)
    if boards:
        return boards[0]

    for candidate in career_page_candidates(homepage, homepage_url):
        if candidate == homepage_url:
            continue
        try:
            page = _fetch_page(candidate, caller)
        except ProviderTransportError:
            continue
        boards = detect_boards(page, candidate)
        if boards:
            return boards[0]
    return None


def fetch_postings(board: AtsBoard, caller: ProviderCaller) -> BoardPostings:
    """Fetch and normalise one board. A 404 is :class:`BoardNotFound`, never an exception leak.

    The call is free, so the estimate is zero — but it is still a :class:`CallSpec`, so the raw
    body lands on disk before anything parses it and two ledger rows record the fetch. That is
    what lets "how many provider calls did this account cost" stay a query when most of the
    answer is free calls.
    """
    url = board_url(board)
    spec = CallSpec(
        provider=board.kind,
        operation=_BOARD_OPERATIONS[board.kind],
        label=board.slug,
        request=HttpRequest(
            method="GET",
            url=url,
            headers={"User-Agent": BROWSER_USER_AGENT, "Accept": "application/json"},
            timeout_s=BOARD_TIMEOUT_S,
        ),
    )
    result = caller.call(spec)
    if result.response.status == 404:
        raise BoardNotFound(board.kind, board.slug, url)
    if not 200 <= result.response.status < 300:
        raise BoardFetchFailed(board.kind, board.slug, url, result.response.status)
    return BoardPostings(
        board=board,
        url=url,
        postings=normalise_postings(board, result.json()),
        raw_ref=result.raw_ref,
        ledger_row_id=result.ledger_row_id,
        cost=result.call_cost,
    )


def normalise_postings(
    board: AtsBoard, payload: object, *, today: date | None = None
) -> tuple[JobPosting, ...]:
    """Turn one board's payload into :class:`JobPosting` records.

    Split out from :func:`fetch_postings` so the three providers' very different envelopes —
    Ashby and Greenhouse wrap their jobs in ``{"jobs": [...]}``, Lever returns a bare array — are
    one testable function rather than a branch inside a network call. ``today`` is injectable so
    ``days_open`` can be asserted against a fixed date.
    """
    reference = today or datetime.now(UTC).date()
    jobs = _job_records(payload)
    if board.kind == "ashby":
        return tuple(_ashby_posting(job, reference) for job in jobs)
    if board.kind == "greenhouse":
        return tuple(_greenhouse_posting(job, reference) for job in jobs)
    return tuple(_lever_posting(job, reference) for job in jobs)


# -- provider normalisation --------------------------------------------------------------------

#: Operation names for the ledger, one per provider, matching each endpoint's own path shape.
_BOARD_OPERATIONS: Mapping[AtsKind, str] = {
    "ashby": "posting-api/job-board",
    "greenhouse": "v1/boards/jobs",
    "lever": "v0/postings",
}


def _job_records(payload: object) -> list[Mapping[str, object]]:
    """The job array, whichever envelope the provider chose to put it in."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        jobs = payload.get("jobs")
        if isinstance(jobs, list):
            return [item for item in jobs if isinstance(item, Mapping)]
    return []


def _ashby_posting(job: Mapping[str, object], today: date) -> JobPosting:
    """Ashby's posting API: the richest of the three, and the only one that states ``isListed``."""
    published = _iso_date(job.get("publishedAt"))
    compensation = job.get("compensation")
    summary = (
        _text(compensation.get("compensationTierSummary"))
        if isinstance(compensation, Mapping)
        else None
    )
    return JobPosting(
        title=_text(job.get("title")),
        department=_text(job.get("department")),
        team=_text(job.get("team")),
        location=_text(job.get("location")),
        published_at=published,
        days_open=_days_open(published, today),
        is_listed=_flag(job.get("isListed")),
        compensation=summary,
        description_plain=_text(job.get("descriptionPlain")),
        url=_text(job.get("jobUrl")),
        apply_url=_text(job.get("applyUrl")),
        provider_fields=dict(job),
    )


def _greenhouse_posting(job: Mapping[str, object], today: date) -> JobPosting:
    """Greenhouse: departments nest, the location is an object, and ``content`` is escaped HTML.

    ``is_listed`` is ``None``, not ``True``: the board only ever serves live jobs, so the
    provider states nothing about listing and neither do we.

    ``first_published`` is preferred over ``updated_at`` for ``published_at`` because a re-saved
    req would otherwise look brand new, which is exactly backwards for a "how long has this been
    open" signal; ``updated_at`` stands in only when the board omits the first publication.
    """
    departments = _mapping_list(job.get("departments"))
    parents = [d for d in departments if d.get("parent_id") in (None, 0)]
    children = [d for d in departments if d.get("parent_id") not in (None, 0)]
    location = job.get("location")
    published = _iso_date(job.get("first_published")) or _iso_date(job.get("updated_at"))
    content = _text(job.get("content"))
    return JobPosting(
        title=_text(job.get("title")),
        department=_text((parents or departments or [{}])[0].get("name")),
        team=_text(children[0].get("name")) if children else None,
        location=_text(location.get("name")) if isinstance(location, Mapping) else None,
        published_at=published,
        days_open=_days_open(published, today),
        is_listed=None,
        compensation=_greenhouse_pay(job.get("pay_input_ranges")),
        description_plain=html_to_text(content) if content else None,
        url=_text(job.get("absolute_url")),
        apply_url=_text(job.get("absolute_url")),
        provider_fields=dict(job),
    )


def _lever_posting(job: Mapping[str, object], today: date) -> JobPosting:
    """Lever: the title is ``text``, the taxonomy lives under ``categories``, dates are ms epoch."""
    categories = job.get("categories")
    facets = categories if isinstance(categories, Mapping) else {}
    published = _epoch_ms_date(job.get("createdAt"))
    return JobPosting(
        title=_text(job.get("text")),
        department=_text(facets.get("department")),
        team=_text(facets.get("team")),
        location=_text(facets.get("location")),
        published_at=published,
        days_open=_days_open(published, today),
        is_listed=None,
        compensation=_lever_salary(job.get("salaryRange")),
        description_plain=_text(job.get("descriptionPlain")),
        url=_text(job.get("hostedUrl")),
        apply_url=_text(job.get("applyUrl")),
        provider_fields=dict(job),
    )


def _greenhouse_pay(value: object) -> str | None:
    """Greenhouse's optional pay bands, rendered as one line. Absent on most boards."""
    ranges = _mapping_list(value)
    rendered = [line for line in (_greenhouse_pay_line(item) for item in ranges) if line]
    return "; ".join(rendered) or None


def _greenhouse_pay_line(item: Mapping[str, object]) -> str | None:
    minimum = _money(item.get("min_cents"))
    maximum = _money(item.get("max_cents"))
    if minimum is None and maximum is None:
        return None
    currency = _text(item.get("currency_type")) or ""
    band = f"{minimum}–{maximum}" if minimum and maximum else (minimum or maximum)
    title = _text(item.get("title"))
    line = f"{band} {currency}".strip()
    return f"{title}: {line}" if title else line


def _lever_salary(value: object) -> str | None:
    """Lever's ``salaryRange`` as one line, or ``None`` when the posting carries no band."""
    if not isinstance(value, Mapping):
        return None
    minimum = value.get("min")
    maximum = value.get("max")
    if not isinstance(minimum, (int, float)) or not isinstance(maximum, (int, float)):
        return None
    currency = _text(value.get("currency")) or ""
    interval = _text(value.get("interval"))
    band = f"{currency} {int(minimum):,}–{int(maximum):,}".strip()
    return f"{band} ({interval})" if interval else band


def _money(cents: object) -> str | None:
    if not isinstance(cents, (int, float)) or isinstance(cents, bool):
        return None
    return f"{int(cents) // 100:,}"


# -- parsing primitives ------------------------------------------------------------------------


def html_to_text(raw: str) -> str:
    """Flatten a job description's HTML to readable plain text, preserving block breaks.

    Greenhouse serves ``content`` *entity-escaped* (``&lt;p&gt;``), so the unescape runs before
    tags are stripped and again afterwards — the second pass resolves the entities that were
    inside the text all along (``&nbsp;``, ``&amp;``) and that the first pass only half-decoded.
    A body that is already plain HTML is unharmed by the extra pass.
    """
    unescaped = html_entities.unescape(raw)
    with_breaks = _BLOCK_BREAK.sub("\n", unescaped)
    stripped = html_entities.unescape(_TAG.sub("", with_breaks))
    lines = [_SPACES.sub(" ", line).strip() for line in stripped.replace("\r\n", "\n").split("\n")]
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()


def _iso_date(value: object) -> date | None:
    """An ISO-8601 timestamp's date, tolerating the ``Z`` suffix ``fromisoformat`` long refused."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _epoch_ms_date(value: object) -> date | None:
    """Lever's millisecond epoch, read in UTC. Non-numeric or nonsensical input is ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC).date()
    except (OverflowError, OSError, ValueError):
        return None


def _days_open(published: date | None, today: date) -> int | None:
    """How long the req has been up. Unknown publication date means unknown age, never zero.

    A publication date in the future (a scheduled posting) floors at 0 rather than going
    negative: "open for -3 days" is not a fact about anything.
    """
    if published is None:
        return None
    return max(0, (today - published).days)


def _text(value: object) -> str | None:
    """A non-empty string, or ``None``. Whitespace-only provider fields count as absent."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _flag(value: object) -> bool | None:
    """A real boolean, or ``None``. A provider that omits the field has not said "false"."""
    return value if isinstance(value, bool) else None


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


# -- page fetching -----------------------------------------------------------------------------


def _fetch_page(url: str, caller: ProviderCaller) -> str:
    """One free company-page GET through the wrapper, as provider ``live_http``.

    The browser user-agent is not cosmetic: several of these sites (and Ashby's own API) answer
    403 to a default client string. A non-200 is returned as its body rather than raised — a 404
    careers page simply contains no board link, which is all this function is asked to determine.
    """
    spec = CallSpec(
        provider="live_http",
        operation="careers-page",
        label=_page_label(url),
        request=HttpRequest(
            method="GET",
            url=url,
            headers={
                "User-Agent": BROWSER_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout_s=PAGE_TIMEOUT_S,
        ),
    )
    return caller.call(spec).text()


def _page_label(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.netloc}{parts.path}".rstrip("/") or parts.netloc


def _anchor_links(html: str) -> list[tuple[str, str]]:
    """``(href, visible text)`` for every anchor, with the text's own markup stripped."""
    return [
        (match.group(1).strip(), _TAG.sub(" ", match.group(2))) for match in _ANCHOR.finditer(html)
    ]


def _mentions_careers(text: str) -> bool:
    lowered = text.lower()
    return "career" in lowered or "jobs" in lowered


def _with_scheme(url: str) -> str:
    """Accept ``example.com`` as readily as ``https://example.com`` — callers pass both."""
    stripped = url.strip()
    return stripped if "://" in stripped else f"https://{stripped}"


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


def _absolutise(href: str, base: str) -> str | None:
    """Resolve a href against the page, dropping fragments and non-HTTP schemes."""
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    absolute = urljoin(base, href)
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https"):
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _dedupe(urls: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered
