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
from typing import Callable, Literal, Optional, Sequence

import httpx

from .net import BoundedFetcher, CaptureError, guard_url
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
    pages = [url]
    for page in page_urls or ():
        if page and page not in pages:
            pages.append(page)
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
) -> CaptureOutcome:
    """Capture one site. ``page_urls`` (F0.4) asks for more of it than the entry page.

    ``None`` — every caller today — is exactly the single-page capture this has always been.
    Given a list, each page is captured with the same per-page machinery (same client, same
    fetcher, so a stylesheet shared across pages is pulled once) and contributes its own
    ``SiteSnapshot`` to ``outcome.snapshots``, in order.

    **The entry page is the job.** A failure capturing it propagates, exactly as before — an
    ingestion with no entry page has nothing to be about. A failure on any OTHER page is a
    ``LUMI0513`` diagnostic and that page contributes nothing; the capture, and the job, carry
    on with the pages that worked. Nothing here discovers pages: crawling and nav-following are
    later work, and this is the seam they will arrive through.
    """
    if render_available is None:
        render_available = _playwright_available()
    fetched_at = fetched_at or _now_iso()

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=15.0)
    diagnostics: list[dict] = []
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
        )
        diagnostics.extend(entry.diagnostics)
        snapshots = [entry.snapshot]

        for page in pages[1:]:
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
                diagnostics.append(
                    {
                        "code": "LUMI0513",
                        "severity": "warning",
                        "message": (
                            f"page capture failed for {page}; it contributes no snapshot: "
                            f"{type(error).__name__}: {error}"
                        ),
                    }
                )
                continue
            diagnostics.extend(extra.diagnostics)
            snapshots.append(extra.snapshot)

        return CaptureOutcome(
            snapshot=entry.snapshot,
            tier=entry.tier,
            escalated=entry.escalated,
            escalation_reason=entry.escalation_reason,
            diagnostics=diagnostics,
            snapshots=snapshots,
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
) -> _PageCapture:
    """One page through the tiered walk: static → quality gate → rendered.

    Split out of :func:`capture_website` for F0.4 so the page loop has a body; the tiering,
    the gate and the diagnostics it emits are untouched. The one thing the split had to be
    careful about is the fetcher's diagnostics: it is SHARED across pages and accumulates, so
    each read is a delta from where this page started rather than the whole list.
    """
    diagnostics: list[dict] = []
    before = len(fetcher.diagnostics)

    if force_render:
        from .rendered import fetch_rendered

        snapshot = await fetch_rendered(url, fetcher, reporter, fetched_at=fetched_at)
        diagnostics.extend(fetcher.diagnostics[before:])
        diagnostics.extend(snapshot.diagnostics)
        return _PageCapture(snapshot, "rendered", False, None, diagnostics)

    snapshot = await fetch_static(url, fetcher, reporter, fetched_at=fetched_at)
    after_static = len(fetcher.diagnostics)
    diagnostics.extend(fetcher.diagnostics[before:after_static])
    diagnostics.extend(snapshot.diagnostics)

    parsed = parse_site(snapshot)
    gate = evaluate(snapshot, parsed)

    if not gate.escalate:
        return _PageCapture(snapshot, "static", False, None, diagnostics)

    reason = "; ".join(gate.reasons)
    if not render_available:
        diagnostics.append(
            {
                "code": "LUMI0506",
                "severity": "warning",
                "message": f"escalation needed but render unavailable — proceeding: {reason}",
            }
        )
        return _PageCapture(snapshot, "static", False, reason, diagnostics)

    diagnostics.append(
        {
            "code": "LUMI0505",
            "severity": "info",
            "message": f"escalated to rendered capture: {reason}",
        }
    )
    from .rendered import fetch_rendered

    rendered_snapshot = await fetch_rendered(url, fetcher, reporter, fetched_at=fetched_at)
    diagnostics.extend(fetcher.diagnostics[after_static:])
    diagnostics.extend(rendered_snapshot.diagnostics)
    return _PageCapture(rendered_snapshot, "rendered", True, reason, diagnostics)


# Re-exported here so callers use `from lumen_ingestion.capture import build_evidence`.
from .evidence_builder import build_evidence  # noqa: E402  (avoids import cycle at top)
