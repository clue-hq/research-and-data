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

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from .provider_identity import ProviderIdentityError, normalized_host, validate_vendor_identity

JsonObject = dict[str, Any]

VENDOR_NAME = "brandfetch"

#: their theme -> our theme. See the module docstring; do not "simplify" this.
_OUR_THEME_FOR_VENDOR_THEME = {"dark": "light", "light": "dark"}

#: vendor `type` -> our completeness axis. `icon` is DELIBERATELY absent
#: (founder ruling 2026-09-02: the social-avatar icon never fills a cell), and
#: so is `other`. Neither is thrown away: both leave as extras.
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
    """The vendor could not supply an eligible answer (lookup or identity failure).
    Distinct from a 404, which IS an answer (empty family)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
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
    """Vendor assets -> 2x2 cells, plus the EXTRAS that fill no cell.

    Inverts theme, classifies theme=None from the bytes, gates SVGs on
    renderability and rasters on decodability. First asset wins per cell.

    Returns (cells, extras, notes). `extras` holds, in payload order, every
    asset that downloads and paints but is not a cell: an `icon`/`other` type,
    and a `logo`/`symbol` whose cell was already filled. They are real assets
    for this brand, so the agent gets them as alternatives rather than losing
    them; each carries `competed_for` and a one-line `reason`. Photographic
    assets and anything that cannot be downloaded or painted stay skipped.
    """
    from .logo_family import SOURCE_BRANDFETCH, FamilyCell, cell_name
    from .logo_ladder import svg_is_renderable

    cells: dict[str, FamilyCell] = {}
    extras: list[FamilyCell] = []
    notes: list[str] = []
    for asset in assets:
        if "photographic" in asset.tags:
            notes.append(f"vendor {asset.type} skipped: tagged photographic")
            continue
        completeness = _COMPLETENESS_FOR_VENDOR_TYPE.get(asset.type)
        chosen = pick_format(asset)
        if chosen is None:
            notes.append(f"vendor {asset.type} skipped: no downloadable format")
            continue

        our_theme = _OUR_THEME_FOR_VENDOR_THEME.get(asset.theme or "")
        theme_basis = f"vendor theme={asset.theme!r} (inverted to ours)"
        vendor_named_the_theme = our_theme is not None

        # Everything downloads and paints before it is placed: an occupied cell
        # no longer ends the asset's life, so its bytes are needed either way.
        fetched = download(str(chosen.get("src")))
        if fetched is None:
            notes.append(f"vendor {asset.type} download failed: {chosen.get('src')}")
            continue
        body, content_type = fetched
        fmt = str(chosen.get("format") or "")
        if our_theme is None:
            our_theme, theme_basis = _classify_null_theme(body, fmt)
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

        evidence = {
            "vendor": VENDOR_NAME,
            "vendor_theme": asset.theme,
            "vendor_type": asset.type,
            "theme": our_theme,
            "theme_basis": theme_basis,
            "format": fmt,
            "width": chosen.get("width"),
            "height": chosen.get("height"),
        }

        # The bytes and where they came from; only the cell name and the extra
        # evidence differ between a cell and an extra.
        found = {
            "body": body,
            "content_type": content_type or _FORMAT_MIME.get(fmt, "image/png"),
            "source": SOURCE_BRANDFETCH,
            "origin_url": str(chosen.get("src")),
        }

        if completeness is None:  # icon/other: never a cell, still a real asset
            extras.append(FamilyCell(cell="", **found, evidence={
                **evidence,
                "competed_for": None,
                "reason": f"vendor type '{asset.type}' is not a family cell",
            }))
            continue

        name = cell_name(our_theme, completeness)
        if name in cells:
            notes.append(
                f"vendor {asset.type} ({asset.theme}) skipped: cell already filled"
                if vendor_named_the_theme
                else f"vendor {asset.type} skipped: cell {name} already filled"
            )
            extras.append(FamilyCell(cell=name, **found, evidence={
                **evidence,
                "competed_for": name,
                "reason": f"a vendor asset already filled {name}",
            }))
            continue
        cells[name] = FamilyCell(cell=name, **found, evidence=evidence)
    return cells, extras, notes


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


#: the Brand API path; the base-url normalizer strips it if the operator's
#: BRANDFETCH_API_BASE_URL already carries it (the PDL _normalize_base_url lesson).
BRAND_PATH_PREFIX = "/v2/brands/domain/"
_MAX_ASSET_BYTES = 15 * 1024 * 1024  # mirrors capture.net's logo cap
#: D6 — the only hosts an asset `src` may point at. Brandfetch serves logo files from its own
#: asset CDN; anything else in a `formats[].src` is not fetched, whatever the API said.
_ASSET_HOST_SUFFIXES = ("brandfetch.io",)
#: cdn.brandfetch.io answers 302 `x-bf-error=user_agent_required` to a request carrying NO
#: User-Agent (verified live 2026-09-02). httpx's default header happens to satisfy it, but a
#: library default is not a contract — we send our own, on the lookup AND every asset download.
_USER_AGENT = "clue-design-logo-vendor/1 (+httpx)"


def _asset_host_allowed(host: str) -> bool:
    """Exact match or subdomain of any allowed suffix — every suffix, not just the first."""
    return any(host == suffix or host.endswith("." + suffix) for suffix in _ASSET_HOST_SUFFIXES)


def _bare_domain(value: str) -> str:
    return normalized_host(value)


def fetch_vendor_family(
    domain, *, company_name=None, api_key=None, base_url=None, timeout_s=None, client=None,
):
    """One Brand API lookup + asset downloads -> (cells, extras, notes). The one
    impure entry point of this module. See the module docstring for the contract."""
    import httpx
    from clue_spend import (
        CallSpec,
        HttpRequest,
        ProviderTransportError,
        SpendEstimate,
    )
    from lumen_api import spend
    from py_lumen_config import settings

    key = (api_key if api_key is not None else settings.brandfetch_api_key).strip()
    if not key:
        raise VendorCredentialsMissing()
    base = (base_url if base_url is not None else settings.brandfetch_api_base_url)
    base = base.strip().rstrip("/")
    if base.lower().endswith(BRAND_PATH_PREFIX.rstrip("/")):
        base = base[: -len(BRAND_PATH_PREFIX.rstrip("/"))].rstrip("/")
    timeout = timeout_s if timeout_s is not None else settings.brandfetch_timeout_s
    host = _bare_domain(domain)
    if not host:
        raise VendorLookupFailed("http", f"could not read a host out of {domain!r}")

    def run(http: "httpx.Client"):
        # The BRAND API LOOKUP is the paid leg (one Brandfetch credit), so it goes through the
        # unit of work's ``ProviderCaller`` and lands on ``provider_call_ledger``. Brandfetch
        # reports no cost of its own, so the row is ``cost_source=free`` with ``credits=1``
        # (spec ruling 6.5). ``max_attempts=1``: a page costs a credit, and the 429 below is a
        # typed quota REFUSAL, not something to retry into. The ASSET DOWNLOADS below stay on
        # the injected httpx client — they are free CDN reads, not spend.
        try:
            resp = spend.caller().call(
                CallSpec(
                    provider="brandfetch",
                    operation="design.logo.brand_api",
                    label=f"brand:{host}",
                    request=HttpRequest(
                        method="GET",
                        url=f"{base}{BRAND_PATH_PREFIX}{host}",
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Accept": "application/json",
                            "User-Agent": _USER_AGENT,
                        },
                        timeout_s=float(timeout),
                    ),
                    estimate=SpendEstimate(credits=Decimal(1)),
                    max_attempts=1,
                )
            ).response
        except ProviderTransportError as error:
            if "Timeout" in error.last_error:
                raise VendorLookupFailed(
                    "timeout", f"brand lookup timed out: {error.last_error}"
                ) from error
            raise VendorLookupFailed(
                "http", f"brand lookup failed: {error.last_error}"
            ) from error
        if resp.status == 404:
            return {}, [], [f"brandfetch has no record of {host} — an answer, not an error"]
        if resp.status == 429:
            raise VendorLookupFailed(
                "quota", "brandfetch quota or throughput limit reached (HTTP 429)"
            )
        if resp.status in (401, 403):
            raise VendorLookupFailed(
                "auth",
                f"brandfetch rejected the API key (HTTP {resp.status}); "
                "check BRANDFETCH_API_KEY",
            )
        if resp.status != 200:
            raise VendorLookupFailed("http", f"brand lookup returned HTTP {resp.status}")
        try:
            payload = json.loads(resp.body)
        except ValueError as error:
            raise VendorLookupFailed("malformed", "brand response was not JSON") from error

        try:
            identity = validate_vendor_identity(
                payload, requested_domain=host, company_name=company_name,
            )
        except ProviderIdentityError as error:
            raise VendorLookupFailed(error.code, error.message) from error

        driver_notes: list[str] = []

        def download(src: str):
            host = (urlsplit(src).hostname or "").lower()
            if not _asset_host_allowed(host):
                driver_notes.append(
                    f"asset host {host or '?'} is not on the vendor allowlist; not fetched: {src}"
                )
                return None
            try:
                got = http.get(src, timeout=timeout, headers={"User-Agent": _USER_AGENT})
            except httpx.HTTPError:
                return None
            if got.status_code != 200 or not got.content:
                return None
            if len(got.content) > _MAX_ASSET_BYTES:
                return None
            return got.content, got.headers.get("content-type")

        cells, extras, notes = map_vendor_assets_to_cells(
            parse_brand_payload(payload), download
        )
        for candidate in [*cells.values(), *extras]:
            candidate.evidence["vendor_identity"] = dict(identity)
        return cells, extras, driver_notes + notes

    if client is not None:
        return run(client)
    with httpx.Client() as owned:
        return run(owned)
