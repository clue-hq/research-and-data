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
from typing import Callable, Literal, Optional

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
    snapshot: SiteSnapshot
    tier: Literal["static", "rendered"]
    escalated: bool
    escalation_reason: str | None
    diagnostics: list[dict] = field(default_factory=list)


def _playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def capture_website(
    url: str,
    *,
    reporter: Callable[[str, float], None],
    force_render: bool = False,
    render_available: bool | None = None,
    http_client: httpx.AsyncClient | None = None,
    fetched_at: str | None = None,
) -> CaptureOutcome:
    if render_available is None:
        render_available = _playwright_available()
    fetched_at = fetched_at or _now_iso()

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=15.0)
    diagnostics: list[dict] = []
    try:
        fetcher = BoundedFetcher(client)

        if force_render:
            from .rendered import fetch_rendered

            snapshot = await fetch_rendered(url, fetcher, reporter, fetched_at=fetched_at)
            diagnostics.extend(fetcher.diagnostics)
            diagnostics.extend(snapshot.diagnostics)
            return CaptureOutcome(
                snapshot=snapshot,
                tier="rendered",
                escalated=False,
                escalation_reason=None,
                diagnostics=diagnostics,
            )

        snapshot = await fetch_static(url, fetcher, reporter, fetched_at=fetched_at)
        static_fetch_diag_count = len(fetcher.diagnostics)
        diagnostics.extend(fetcher.diagnostics)
        diagnostics.extend(snapshot.diagnostics)

        parsed = parse_site(snapshot)
        gate = evaluate(snapshot, parsed)

        if not gate.escalate:
            return CaptureOutcome(
                snapshot=snapshot,
                tier="static",
                escalated=False,
                escalation_reason=None,
                diagnostics=diagnostics,
            )

        reason = "; ".join(gate.reasons)
        if not render_available:
            diagnostics.append(
                {
                    "code": "LUMI0506",
                    "severity": "warning",
                    "message": f"escalation needed but render unavailable — proceeding: {reason}",
                }
            )
            return CaptureOutcome(
                snapshot=snapshot,
                tier="static",
                escalated=False,
                escalation_reason=reason,
                diagnostics=diagnostics,
            )

        diagnostics.append(
            {
                "code": "LUMI0505",
                "severity": "info",
                "message": f"escalated to rendered capture: {reason}",
            }
        )
        from .rendered import fetch_rendered

        rendered_snapshot = await fetch_rendered(
            url, fetcher, reporter, fetched_at=fetched_at
        )
        diagnostics.extend(fetcher.diagnostics[static_fetch_diag_count:])
        diagnostics.extend(rendered_snapshot.diagnostics)
        return CaptureOutcome(
            snapshot=rendered_snapshot,
            tier="rendered",
            escalated=True,
            escalation_reason=reason,
            diagnostics=diagnostics,
        )
    finally:
        if owns_client:
            await client.aclose()


# Re-exported here so callers use `from lumen_ingestion.capture import build_evidence`.
from .evidence_builder import build_evidence  # noqa: E402  (avoids import cycle at top)
