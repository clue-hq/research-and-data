"""The Brandfetch rung of the two-rung logo supply chain (vendor-first,
founder decision 2026-08-31; rulings 2026-09-02).

**This module is the only place in the repository that knows Brandfetch's
Brand API exists** -- the shape `ad_library/pdl.py` established for PDL.
Everything else consumes cells of the shared 2x2 (`logo_family`).

The endpoint contract, per the vendor's documented Brand API schema:

    GET {base}/v2/brands/domain/{domain}
    Authorization: Bearer <key>
    -> 200 {"logos": [{"theme": "dark"|"light"|null,
                        "type": "icon"|"logo"|"symbol"|"other",
                        "tags": [...],
                        "formats": [{"src", "format", "width", "height",
                                     "size", "background"}]}], ...}
    -> 404  # unknown brand -- an ANSWER (empty family), not a fault
    -> 429  # free-tier quota out -- a typed degrade, the ladder takes over

**Theme semantics are INVERTED here and nowhere else.** Brandfetch labels the
asset's own appearance (their "dark" = dark-colored art, which belongs on
LIGHT backgrounds); our cells name the background the asset is FOR. The
`_OUR_THEME_FOR_VENDOR_THEME` table is the entire inversion, and the tests pin
it, because shipping this backwards swaps every light/dark pairing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

JsonObject = dict[str, Any]

VENDOR_NAME = "brandfetch"

#: their theme -> our theme. See the module docstring; do not "simplify" this.
_OUR_THEME_FOR_VENDOR_THEME = {"dark": "light", "light": "dark"}

#: vendor `type` -> our completeness axis. `icon` is DELIBERATELY absent
#: (founder ruling 2026-09-02: the social-avatar icon never fills a cell), and
#: so is `other`.
_COMPLETENESS_FOR_VENDOR_TYPE = {"logo": "lockup", "symbol": "mark"}

_FORMAT_MIME = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "webp": "image/webp",
    "jpeg": "image/jpeg",
}


class VendorCredentialsMissing(Exception):
    """No BRANDFETCH_API_KEY configured. The dispatch treats this as
    "vendor rung disabled" and runs the ladder -- a degrade, not a failure."""

    def __init__(self, env_vars: tuple[str, ...] = ("BRANDFETCH_API_KEY",)) -> None:
        self.env_vars = env_vars
        super().__init__(f"missing credentials: {', '.join(env_vars)}")


class VendorLookupFailed(Exception):
    """The vendor was asked and could not answer (quota/timeout/http/malformed).
    Distinct from a 404, which IS an answer (empty family)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code  # "quota" | "timeout" | "http" | "malformed"
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass
class VendorAsset:
    """One entry of the Brand API `logos[]` array, vendor vocabulary intact.
    Parsing is faithful; filtering (icon/other/photographic) is mapping's job."""

    theme: str | None
    type: str
    tags: list[str] = field(default_factory=list)
    formats: list[JsonObject] = field(default_factory=list)


def parse_brand_payload(payload: JsonObject) -> list[VendorAsset]:
    """Normalize the Brand API response into typed assets. Non-dict entries
    drop; missing fields normalize to empty -- a malformed entry must never
    take the whole family down."""
    logos = payload.get("logos") if isinstance(payload, dict) else None
    if not isinstance(logos, list):
        return []
    out: list[VendorAsset] = []
    for entry in logos:
        if not isinstance(entry, dict):
            continue
        theme = entry.get("theme")
        out.append(
            VendorAsset(
                theme=theme if theme in ("dark", "light") else None,
                type=str(entry.get("type") or ""),
                tags=[str(t) for t in entry.get("tags") or [] if isinstance(t, str)],
                formats=[f for f in entry.get("formats") or [] if isinstance(f, dict)],
            )
        )
    return out


def pick_format(asset: VendorAsset) -> JsonObject | None:
    """SVG first (logos are vector art); else the largest transparent raster;
    else the largest raster. None when the asset ships no formats."""
    svgs = [f for f in asset.formats if f.get("format") == "svg" and f.get("src")]
    if svgs:
        return svgs[0]

    def area(f: JsonObject) -> int:
        return int(f.get("width") or 0) * int(f.get("height") or 0)

    rasters = [
        f for f in asset.formats
        if f.get("src") and f.get("format") in ("png", "webp", "jpeg")
    ]
    transparent = [f for f in rasters if f.get("background") == "transparent"]
    pool = transparent or rasters
    return max(pool, key=area) if pool else None
