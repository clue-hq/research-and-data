"""A website capture must be born with the whole logo family.

Before the ladder was wired in, a website-captured kit could only ever carry
``logo.primary`` and an apple-touch ``logo.mark``: the website path never set
``color_mode_hint``, so ``logo.reversed`` was unreachable and
``surface.inverse`` never appeared in a logo's allowed backgrounds.
"""

from __future__ import annotations

import base64
import hashlib
import io
import tempfile

from lumen_ingestion.capture import CaptureOutcome
from lumen_ingestion.capture.evidence_builder import build_evidence
from lumen_ingestion.capture.snapshot import Download, SiteSnapshot, Stylesheet
from lumen_ingestion.capture.static import _collect_assets
from lumen_ingestion.normalizer import normalize_evidence


def _noop(stage: str, progress: float) -> None:
    return None


class _StubCore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ingest_asset(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "asset": {"record": {"id": kwargs["asset_id"]}}}


def _png(width: int, height: int, color=(18, 32, 48, 255)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _wordmark(width: int, height: int, fill: str) -> bytes:
    bars = "".join(
        f'<rect x="{x}" y="6" width="24" height="{height - 12}" fill="{fill}"/>'
        for x in (4, 34, 64, 94)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">{bars}</svg>'
    ).encode()


HTML = """
<html><head>
  <title>Acme Robotics | Autonomous logistics</title>
  <link rel="apple-touch-icon" href="/brand/acme-logomark.png">
  <script type="application/ld+json">
    {"@type": "Organization", "name": "Acme Robotics", "logo": "/brand/acme-jsonld.png"}
  </script>
</head><body>
  <header><a href="/">
    <img src="/brand/acme-logo.svg" alt="Acme Robotics" width="160" height="32">
  </a></header>
  <footer style="background:#101820">
    <img src="/brand/acme-logo-white.svg" alt="Acme Robotics" width="160" height="32">
  </footer>
</body></html>
"""

ASSETS = {
    "https://acme.com/brand/acme-logo.svg": (_wordmark(160, 32, "#101820"), "image/svg+xml"),
    "https://acme.com/brand/acme-logo-white.svg": (_wordmark(160, 32, "#ffffff"), "image/svg+xml"),
    "https://acme.com/brand/acme-logomark.png": (_png(180, 180), "image/png"),
    "https://acme.com/brand/acme-jsonld.png": (_png(512, 128), "image/png"),
    "https://acme.com/favicon.ico": (_png(32, 32), "image/x-icon"),
}


def _snapshot() -> SiteSnapshot:
    downloads = [
        Download(
            url=url,
            kind="logo",
            content_type=content_type,
            bytes_b64=base64.b64encode(body).decode("ascii"),
            sha256=hashlib.sha256(body).hexdigest(),
        )
        for url, (body, content_type) in ASSETS.items()
    ]
    return SiteSnapshot(
        requested_url="https://acme.com/",
        final_url="https://acme.com/",
        fetched_at="2026-08-26T00:00:00Z",
        tier="static",
        html=HTML,
        stylesheets=[Stylesheet(url="inline:0", text="body{background:#ffffff}")],
        downloads=downloads,
        meta={"title": "Acme Robotics | Autonomous logistics"},
    )


def _evidence():
    outcome = CaptureOutcome(
        snapshot=_snapshot(), tier="static", escalated=False,
        escalation_reason=None, diagnostics=[],
    )
    with tempfile.TemporaryDirectory() as store:
        return build_evidence(outcome, core=_StubCore(), store_root=store, reporter=_noop), outcome


def test_a_website_capture_yields_the_whole_logo_family() -> None:
    evidence, _ = _evidence()
    by_usage: dict[str, list] = {}
    for logo in evidence.logos:
        by_usage.setdefault(logo.usage_hint, []).append(logo)

    assert "primary" in by_usage, "the header lockup must fill the primary slot"
    modes = [logo.color_mode_hint for logo in by_usage["primary"]]
    assert modes[0] != "reversed", "the light asset must lead the primary group"
    assert "reversed" in modes, "the white footer asset must fill the reversed variant"
    assert "mark" in by_usage, "the apple-touch icon must fill the mark slot"

    reversed_logo = next(l for l in by_usage["primary"] if l.color_mode_hint == "reversed")
    assert reversed_logo.background_hint is not None
    assert reversed_logo.background_hint.startswith("#")

    # every emitted logo is content-addressed and traceable to its rung
    for logo in evidence.logos:
        assert logo.asset_id.startswith("asset_ing_")
        assert logo.pointer.locator.startswith("logo-ladder :: ")


def test_the_kit_carries_logo_reversed_and_the_inverse_surface() -> None:
    evidence, _ = _evidence()
    result = normalize_evidence(
        evidence, brand_kit_id="brand_kit_logo_family", version=1,
        name="Acme Robotics", created_at="2026-08-26",
    )
    kit = result.brand_kit

    logos = kit["assets"]["logos"]
    assert set(logos) >= {"primary", "mark"}

    primary = logos["primary"]
    assert "surface.inverse" in primary["allowed_backgrounds"], (
        "a reversed variant is what makes an inverse surface a legal background"
    )
    assert {v["color_mode"] for v in primary["variants"]} == {"full_color", "reversed"}
    assert primary["variants"][0]["color_mode"] == "full_color", (
        "logo.primary is filled from variants[0]; the reversed mark must not lead"
    )
    assert primary["provenance"]["source"].startswith("website:logo-ladder :: ")

    asset_tokens = kit["tokens"]["assets"]
    assert {"logo.primary", "logo.reversed", "logo.mark"} <= set(asset_tokens)
    assert (
        asset_tokens["logo.reversed"]["value"]["default"]["asset_id"]
        == primary["variants"][1]["asset_id"]
    )


def test_every_url_the_ladder_can_consider_is_downloaded() -> None:
    """The fetch-everything invariant at the capture seam: a JSON-LD
    Organization.logo used to be scored and never fetched, so the top candidate
    arrived byteless and the evidence builder dropped it without a word."""
    import asyncio

    from selectolax.parser import HTMLParser

    requested: list[str] = []

    class _Fetcher:
        async def fetch_many(self, requests):
            requested.extend(r.url for r in requests)
            return []

    asyncio.run(
        _collect_assets(HTMLParser(HTML), _Fetcher(), "https://acme.com/", [])
    )

    for url in (
        "https://acme.com/brand/acme-jsonld.png",
        "https://acme.com/brand/acme-logo-white.svg",
        "https://acme.com/brand/acme-logomark.png",
        "https://acme.com/brand/acme-logo.svg",
    ):
        assert url in requested, url

