"""Web capture package: tiered (static → gate → rendered) site capture that
produces a replayable ``SiteSnapshot`` and a ``CaptureOutcome``.

Importing this package pulls in httpx + selectolax + tinycss2 only — never
playwright (lazy inside ``rendered.py``) nor pillow/pymupdf. Verify with::

    python -c "import lumen_ingestion.capture"
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Literal, Optional, Sequence

import httpx

from .net import BoundedFetcher, CaptureError, guard_url
from .page_plan import (
    MAX_CAPTURE_PAGES, ROLE_LIMITS, canonical_page_url, discover_reference_pages,
    page_coverage, page_role,
)
from .parse import parse_site
from .quality_gate import evaluate
from .snapshot import SiteSnapshot, load_snapshot, save_snapshot
from .static import fetch_static

__all__ = [
    "CaptureOutcome",
    "capture_website",
    "build_evidence",
    "guard_url",
    "CaptureError",
    "SiteSnapshot",
    "load_snapshot",
    "save_snapshot",
]


@dataclass
class CaptureOutcome:
    """What one capture produced.

    ``snapshot`` is the ENTRY page and has been since slice 1 — every consumer (the evidence
    builder, the quality gate's callers, every capture stub in the suites) reads it and none of
    them moved. ``snapshots`` (F0.4) is the full ordered page list, entry page first, and equals
    ``[snapshot]`` for the single-page captures that are still the only kind a caller asks for.
    """

    snapshot: SiteSnapshot
    tier: Literal["static", "rendered"]
    escalated: bool
    escalation_reason: str | None
    diagnostics: list[dict] = field(default_factory=list)
    snapshots: list[SiteSnapshot] = field(default_factory=list)
    page_coverage: list[dict] = field(default_factory=list)
    missing_page_roles: list[str] = field(default_factory=list)
    library_capture: bool = False

    def __post_init__(self) -> None:
        if not self.snapshots:
            self.snapshots = [self.snapshot]


@dataclass
class _PageCapture:
    """One page's tiering result, before it is folded into the outcome."""

    snapshot: SiteSnapshot
    tier: Literal["static", "rendered"]
    escalated: bool
    escalation_reason: str | None
    diagnostics: list[dict]


def _diagnostic_key(entry: dict) -> str:
    """A stable identity for one diagnostic: same fields, same values ⇒ same event.

    Built out of ``repr`` rather than ``json.dumps`` so it is TOTAL — no diagnostic, however
    oddly shaped, can raise here. This function runs on the honest-partial path whose whole
    promise is that a failure gets REPORTED; throwing while keying a report would be the one
    way to lose the capture over it. A shape it cannot key collapses to "not seen before",
    which keeps a duplicate — the harmless direction.
    """
    return repr(sorted((str(key), repr(value)) for key, value in entry.items()))


class _Diagnostics:
    """A capture's diagnostics, each recorded once however many sources report it.

    A failed fetch is reported TWICE by construction. ``net.BoundedFetcher`` puts the
    diagnostic on the per-item ``FetchResult`` — which ``static._collect_assets`` folds into
    the SNAPSHOT — *and* on its own accumulating list, which the caller reads as a delta. Both
    reads are deliberate: the fetcher can record something no snapshot ever carries (a capped
    page body), and a snapshot carries plenty the fetcher never saw (budget drops, html
    truncation). So the fix is to drop the TWIN here rather than to stop reading either
    source. Two further doublings collapse here for free: an escalated capture whose rendered
    tier re-requests a URL the static tier already failed on gets the identical entry back off
    the fetch cache, and a multi-page capture replays page one's failures into page two's
    snapshot the same way.

    Why it matters: these entries reach the PUBLISHED KIT uncapped (``pipeline`` concatenates
    the outcome's diagnostics verbatim; ``budget.MAX_NAMED_DROPS`` bounds the evidence
    builder's ``LUMI0515``/``LUMI0516`` lists, not this one). So a doubled report is both
    twice the noise a human reads and a wrong answer to "how much did this capture lose" —
    the insighthealth.ai walk turned three dead assets into six ``LUMI0503``.

    Cost of the collapse: two genuinely separate events that are byte-identical become one
    line. Since a diagnostic carries no page or attempt key, the second copy told a human
    nothing the first did not.
    """

    def __init__(self) -> None:
        self.entries: list[dict] = []
        self._seen: set[str] = set()

    def record(self, incoming: Iterable[dict]) -> None:
        for entry in incoming:
            key = _diagnostic_key(entry)
            if key in self._seen:
                continue
            self._seen.add(key)
            self.entries.append(entry)

    def record_one(self, entry: dict) -> None:
        self.record((entry,))


def _playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pages_to_capture(url: str, page_urls: Optional[Sequence[str]]) -> list[str]:
    """The ordered page list: the entry ``url`` first, then anything else asked for, deduped.

    ``url`` stays the entry page whatever ``page_urls`` says, so the parameter reads the same
    under both natural interpretations — "the pages to capture" and "the extra pages to capture"
    — and a caller that repeats the entry url in the list does not capture it twice.
    """
    pages = [canonical_page_url(url, url)]
    for page in page_urls or ():
        candidate = canonical_page_url(page, url)
        if candidate and candidate not in pages:
            pages.append(candidate)
    if len(pages) > MAX_CAPTURE_PAGES:
        raise CaptureError("LUMI0514", f"capture allows at most {MAX_CAPTURE_PAGES} pages")
    return pages



def _silent(stage: str, progress: float) -> None:
    """The reporter non-entry pages get.

    The reporter drives the ingestion job's stage line and progress bar, and every per-page
    fetch walks the same 0.05→0.55 script. Letting page two re-run it would rewind the bar in
    front of the human watching it, which reads as the job restarting.
    """
    return None


async def capture_website(
    url: str,
    *,
    reporter: Callable[[str, float], None],
    force_render: bool = False,
    render_available: bool | None = None,
    http_client: httpx.AsyncClient | None = None,
    fetched_at: str | None = None,
    page_urls: Optional[Sequence[str]] = None,
    discover_pages: bool = False,
) -> CaptureOutcome:
    """Capture one site. ``page_urls`` (F0.4) asks for more of it than the entry page.

    ``None`` — every caller today — is exactly the single-page capture this has always been.
    Given a list, each page is captured with the same per-page machinery (same client, same
    fetcher, so a stylesheet shared across pages is pulled once) and contributes its own
    ``SiteSnapshot`` to ``outcome.snapshots``, in order.

    **The entry page is the job.** A failure capturing it propagates, exactly as before — an
    ingestion with no entry page has nothing to be about. A failure on any OTHER page is a
    ``LUMI0513`` diagnostic and that page contributes nothing; the capture, and the job, carry
    on with the pages that worked. Automatic discovery is opt-in for low-level
    callers; the website API enables it.
    Discovery follows observed same-origin product/customer links within category budgets.
    """
    if render_available is None:
        render_available = _playwright_available()
    fetched_at = fetched_at or _now_iso()

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=15.0)
    diagnostics = _Diagnostics()
    try:
        fetcher = BoundedFetcher(client)
        pages = _pages_to_capture(url, page_urls)

        entry = await _capture_page(
            pages[0],
            fetcher,
            reporter,
            force_render=force_render,
            render_available=render_available,
            fetched_at=fetched_at,
            measure_states=True,
        )
        diagnostics.record(entry.diagnostics)
        snapshots = [entry.snapshot]
        plan = [
            {"url": page, "role": "homepage" if i == 0 else page_role(page)}
            for i, page in enumerate(pages)
        ]
        coverage = [page_coverage(entry.snapshot, role="homepage", diagnostics=entry.diagnostics)]
        if discover_pages:
            plan.extend(
                discover_reference_pages(
                    entry.snapshot.html,
                    entry.snapshot.final_url or pages[0],
                    existing=plan,
                )
            )
        cursor = 1
        while cursor < len(plan):
            planned = plan[cursor]
            page = planned["url"]
            cursor += 1
            reporter(f"Capturing source page {cursor} of {len(plan)}…", 0.55)
            try:
                extra = await _capture_page(
                    page,
                    fetcher,
                    _silent,
                    force_render=force_render,
                    render_available=render_available,
                    fetched_at=fetched_at,
                )
            except Exception as error:  # noqa: BLE001 — one page is not the job
                diagnostic = {
                    "code": "LUMI0513",
                    "severity": "warning",
                    "url": page,
                    "message": f"page capture failed for {page}: {type(error).__name__}: {error}",
                }
                diagnostics.record_one(diagnostic)
                coverage.append(
                    {
                        **planned,
                        "status": "failed",
                        "diagnostics": [diagnostic],
                        "fidelity_verified": False,
                    }
                )
                continue
            diagnostics.record(extra.diagnostics)
            snapshots.append(extra.snapshot)
            coverage.append(
                page_coverage(extra.snapshot, role=planned["role"], diagnostics=extra.diagnostics)
            )
            if discover_pages:
                # One bounded library plan; customer indexes can supply actual story URLs.
                # Never recurse into unselected unrelated links or exceed category budgets.
                plan.extend(
                    discover_reference_pages(
                        extra.snapshot.html,
                        extra.snapshot.final_url or page,
                        existing=plan,
                    )
                )
        missing_roles = (
            [
                role
                for role in ROLE_LIMITS
                if not any(row["role"] == role and row["status"] != "failed" for row in coverage)
            ]
            if discover_pages
            else []
        )
        if missing_roles:
            diagnostics.record_one(
                {
                    "code": "LUMI0540",
                    "severity": "warning",
                    "message": "No captured source page for categories: "
                    + ", ".join(missing_roles),
                    "missing_page_roles": missing_roles,
                }
            )

        return CaptureOutcome(
            snapshot=entry.snapshot,
            tier=entry.tier,
            escalated=entry.escalated,
            escalation_reason=entry.escalation_reason,
            diagnostics=diagnostics.entries,
            snapshots=snapshots,
            page_coverage=coverage,
            missing_page_roles=missing_roles,
            library_capture=discover_pages or len(plan) > 1,
        )
    finally:
        if owns_client:
            await client.aclose()


async def _capture_page(
    url: str,
    fetcher: BoundedFetcher,
    reporter: Callable[[str, float], None],
    *,
    force_render: bool,
    render_available: bool,
    fetched_at: str,
    measure_states: bool = False,
) -> _PageCapture:
    """One page through the tiered walk: static → quality gate → rendered.

    Split out of :func:`capture_website` for F0.4 so the page loop has a body; the tiering,
    the gate and the diagnostics it emits are untouched. The one thing the split had to be
    careful about is the fetcher's diagnostics: it is SHARED across pages and accumulates, so
    each read is a delta from where this page started rather than the whole list.

    Both the fetcher delta and the snapshot are still read in full, and :class:`_Diagnostics`
    drops the entries that are the same event seen from both (see its docstring).
    """
    diagnostics = _Diagnostics()
    before = len(fetcher.diagnostics)

    if force_render:
        from .rendered import fetch_rendered

        snapshot = await fetch_rendered(
            url, fetcher, reporter, fetched_at=fetched_at, measure_states=measure_states
        )
        diagnostics.record(fetcher.diagnostics[before:])
        diagnostics.record(snapshot.diagnostics)
        return _PageCapture(snapshot, "rendered", False, None, diagnostics.entries)

    snapshot = await fetch_static(url, fetcher, reporter, fetched_at=fetched_at)
    after_static = len(fetcher.diagnostics)
    diagnostics.record(fetcher.diagnostics[before:after_static])
    diagnostics.record(snapshot.diagnostics)

    parsed = parse_site(snapshot)
    gate = evaluate(snapshot, parsed)

    if not gate.escalate:
        return _PageCapture(snapshot, "static", False, None, diagnostics.entries)

    reason = "; ".join(gate.reasons)
    if not render_available:
        diagnostics.record_one(
            {
                "code": "LUMI0506",
                "severity": "warning",
                "message": f"escalation needed but render unavailable — proceeding: {reason}",
            }
        )
        return _PageCapture(snapshot, "static", False, reason, diagnostics.entries)

    diagnostics.record_one(
        {
            "code": "LUMI0505",
            "severity": "info",
            "message": f"escalated to rendered capture: {reason}",
        }
    )
    from .rendered import fetch_rendered

    rendered_snapshot = await fetch_rendered(
        url, fetcher, reporter, fetched_at=fetched_at, measure_states=measure_states
    )
    diagnostics.record(fetcher.diagnostics[after_static:])
    diagnostics.record(rendered_snapshot.diagnostics)
    return _PageCapture(rendered_snapshot, "rendered", True, reason, diagnostics.entries)


# Re-exported here so callers use `from lumen_ingestion.capture import build_evidence`.
from .evidence_builder import build_evidence  # noqa: E402  (avoids import cycle at top)
