"""Conservative, read-only rendition families for scoped asset-search results.

Only known Next image-optimizer URLs from the same capture are grouped. An
inner crop, deployment, unknown query parameter or aspect mismatch is evidence
against substituting files. Stored records and exact asset references never move.
"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit

from .engine_mirror import record_pixel_dims

_VARIANT_SUMMARY_LIMIT = 8


def decoded_dimensions(record: dict) -> tuple[int, int] | None:
    """Read measured dimensions, never a width promised by a source URL."""
    dims = record_pixel_dims(record)
    if dims and all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in dims):
        return dims
    return None


def _family_key(record: dict) -> str | None:
    source = record.get("source") or {}
    if record.get("kind") != "raster_image" or source.get("kind") != "website":
        return None
    capture = source.get("captured_at")
    url = source.get("url")
    if not isinstance(capture, str) or not capture or not isinstance(url, str):
        return None
    if not decoded_dimensions(record):
        return None
    try:
        parts = urlsplit(url)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path != "/_next/image"
            or parts.fragment
        ):
            return None
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
        query = dict(pairs)
        if len(query) != len(pairs) or not query.get("url"):
            return None
        width = query.get("w", "")
        if not width.isascii() or not width.isdecimal() or int(width) < 1:
            return None
        # Preserve the full inner source including its crop. Preserve q, dpl,
        # and every unknown outer parameter. Only the rendition width varies.
        identity = urlencode(sorted((k, v) for k, v in pairs if k != "w"))
        key = f"{capture}\n{parts.scheme}://{parts.netloc}{parts.path}?{identity}"
        return sha256(key.encode()).hexdigest()
    except (ValueError, UnicodeError):
        return None


def rendition_families(candidates: dict) -> dict[str, tuple[str, ...]]:
    """Index family members using only the already-scoped candidate records."""
    buckets: dict[str, list[str]] = defaultdict(list)
    for asset_id, (entry, _origin) in candidates.items():
        key = _family_key(entry["record"])
        if key is not None:
            buckets[key].append(asset_id)
    families = {}
    for ids in buckets.values():
        if len(ids) < 2:
            continue

        # Largest READY pixels win; unavailable files cannot displace a usable
        # source. The id tie-break keeps repeated searches reproducible.
        def rank(asset_id: str) -> tuple:
            record = candidates[asset_id][0]["record"]
            width, height = decoded_dimensions(record)  # type: ignore[misc]
            return record.get("status") != "ready", -(width * height), asset_id

        members = tuple(sorted(ids, key=rank))
        dimensions = [decoded_dimensions(candidates[i][0]["record"]) for i in members]
        largest_w, largest_h = max(dimensions, key=lambda d: d[0] * d[1])
        # A one-pixel rounding tolerance at each rendition's native size. A
        # changed aspect could be another crop: keep that whole bucket separate.
        if any(abs(h - largest_h * w / largest_w) > 1 for w, h in dimensions):
            continue
        for asset_id in members:
            families[asset_id] = members
    return families


def family_summary(members: tuple[str, ...], candidates: dict, *, matched_id: str) -> dict:
    variants = []
    for asset_id in members[:_VARIANT_SUMMARY_LIMIT]:
        entry, origin = candidates[asset_id]
        record = entry["record"]
        width, height = decoded_dimensions(record)  # type: ignore[misc]
        variants.append(
            {
                "asset_id": asset_id,
                "width_px": width,
                "height_px": height,
                "status": record.get("status"),
                "origin": origin,
            }
        )
    return {
        "variant_count": len(members),
        "preferred_asset_id": members[0],
        "matched_asset_id": matched_id,
        "variants": variants,
        "variants_truncated": len(members) > len(variants),
    }


def resolution_summary(record: dict, min_width_px: int | None, min_height_px: int | None) -> dict:
    """Advisory placement suitability; no upscaling or readiness promises."""
    mime = (record.get("media") or {}).get("mime_type")
    if record.get("kind") == "vector" or mime == "image/svg+xml":
        return {
            "type": "vector",
            "meets_requested_pixels": None,
            "guidance": "Vector dimensions are not a raster pixel limit; inspect the artwork.",
        }
    dims = decoded_dimensions(record)
    requested = min_width_px is not None or min_height_px is not None
    meets = (
        None
        if not requested or not dims
        else (dims[0] >= (min_width_px or 0) and dims[1] >= (min_height_px or 0))
    )
    if not dims:
        guidance = "Decoded pixel dimensions unavailable; verify resolution before placement."
    elif meets is False:
        guidance = (
            "Insufficient decoded pixels: fetch a larger source or use a smaller placement. "
            "Upscaling does not restore detail."
        )
    elif max(dims) < 256:
        guidance = (
            "Small raster: suitable for a small UI placement, not a hero image. "
            "Check required pixels at the intended display density."
        )
    else:
        guidance = (
            "Compare decoded pixels with rendered width and height at the intended "
            "display density; inspect crop and sharpness."
        )
    return {
        "type": "raster" if dims else "unknown",
        "width_px": dims[0] if dims else None,
        "height_px": dims[1] if dims else None,
        "requested_width_px": min_width_px,
        "requested_height_px": min_height_px,
        "meets_requested_pixels": meets,
        "guidance": guidance,
    }
