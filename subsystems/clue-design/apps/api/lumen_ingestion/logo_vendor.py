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


def _classify_null_theme(body: bytes, fmt: str) -> tuple[str, str]:
    """Our theme for a vendor asset that carries none, read off the bytes with
    the ladder's own appearance analyzer (one classifier, no drift).
    Returns (our_theme, basis)."""
    from .logo_ladder import LadderCandidate, analyze_appearance

    probe = LadderCandidate(url="", fmt=fmt, body=body)
    verdict = analyze_appearance(probe).get("verdict")
    if verdict == "dark_variant":  # light/white ink -> made for dark surfaces
        return "dark", "classified from bytes: light ink (dark_variant)"
    if verdict == "light_variant":
        return "light", "classified from bytes: dark ink (light_variant)"
    if verdict == "adaptive":
        return "light", "classified from bytes: adaptive (one file, filed under light)"
    return "light", "classified from bytes: no verdict; vendor-attributed, filed light"


def map_vendor_assets_to_cells(assets, download):
    """Vendor assets -> 2x2 cells. Filters (icon/other/photographic), inverts
    theme, classifies theme=None from the bytes, gates SVGs on renderability.
    First asset wins per cell. Returns (cells, notes)."""
    from .logo_family import SOURCE_BRANDFETCH, FamilyCell, cell_name
    from .logo_ladder import svg_is_renderable

    cells: dict[str, FamilyCell] = {}
    notes: list[str] = []
    for asset in assets:
        completeness = _COMPLETENESS_FOR_VENDOR_TYPE.get(asset.type)
        if completeness is None:
            continue  # icon/other: ruled out, silently -- they are not skips gone wrong
        if "photographic" in asset.tags:
            notes.append(f"vendor {asset.type} skipped: tagged photographic")
            continue
        chosen = pick_format(asset)
        if chosen is None:
            notes.append(f"vendor {asset.type} skipped: no downloadable format")
            continue

        our_theme = _OUR_THEME_FOR_VENDOR_THEME.get(asset.theme or "")
        theme_basis = f"vendor theme={asset.theme!r} (inverted to ours)"
        # theme=None needs the bytes to classify, so only pre-check occupancy
        # when the theme is already known.
        if our_theme is not None and cell_name(our_theme, completeness) in cells:
            notes.append(f"vendor {asset.type} ({asset.theme}) skipped: cell already filled")
            continue

        fetched = download(str(chosen.get("src")))
        if fetched is None:
            notes.append(f"vendor {asset.type} download failed: {chosen.get('src')}")
            continue
        body, content_type = fetched
        fmt = str(chosen.get("format") or "")
        if our_theme is None:
            our_theme, theme_basis = _classify_null_theme(body, fmt)

        name = cell_name(our_theme, completeness)
        if name in cells:
            notes.append(f"vendor {asset.type} skipped: cell {name} already filled")
            continue
        if fmt == "svg" and not svg_is_renderable(body):
            notes.append(
                f"vendor {asset.type} refused: SVG cannot paint standalone "
                f"(no intrinsic geometry or no drawable artwork, not renderable)"
            )
            continue
        if fmt in ("png", "webp", "jpeg") and not _raster_decodes(body):
            notes.append(
                f"vendor {asset.type} refused: {fmt} bytes cannot be decoded as an image"
            )
            continue
        cells[name] = FamilyCell(
            cell=name,
            body=body,
            content_type=content_type or _FORMAT_MIME.get(fmt, "image/png"),
            source=SOURCE_BRANDFETCH,
            origin_url=str(chosen.get("src")),
            evidence={
                "vendor": VENDOR_NAME,
                "vendor_theme": asset.theme,
                "vendor_type": asset.type,
                "theme_basis": theme_basis,
                "format": fmt,
                "width": chosen.get("width"),
                "height": chosen.get("height"),
            },
        )
    return cells, notes


def _raster_decodes(body: bytes) -> bool:
    """Can Pillow open these bytes? The raster twin of `svg_is_renderable`: a
    vendor cell must hold a file that PAINTS, whatever its format, and an
    undecodable raster would otherwise travel all the way to `core.ingest_asset`
    before anything said so."""
    import io

    from PIL import Image  # lazy, like the ladder: `capture` must import PIL-free

    try:
        with Image.open(io.BytesIO(body)) as image:
            image.verify()
        return True
    except Exception:  # noqa: BLE001 - undecodable is the answer, not an error
        return False
