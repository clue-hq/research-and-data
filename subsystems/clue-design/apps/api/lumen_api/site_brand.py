"""The Puck site's BrandData, built from the stored brand kit (Lane B; the Wave 2 brand split).

ONE builder for every consumer of a site's brand: the site agent's workspace (Lane B), the
renderer, the write validator and publish (Lane A), and the editor read (Lane C). Every image and
font is named ``/asset-store/<sha256>``, a blob of this workspace (Contract 1); nothing names
``/brands/…``. There is no ``measured`` key: what the extraction measured reaches site-kit inside
``kit`` (its minted tokens, ``tokens.styles`` and ``measured_components``; Lane A's A9 rewrite), so
``kit`` is the stored ``brand_kit_json`` passed WHOLE — ``brief``, ``grammar_audit``,
``measured_components`` and ``tokens.styles`` included.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

__all__ = [
    "asset_store_file", "brand_asset", "captured_asset_id", "captured_image_descriptions",
    "clone_from_fragment", "clone_images", "clone_video_renditions", "site_brand_data",
]

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
#: A captured section's own image, already rehosted to the asset store at capture, and the alt
#: text that follows its src in the same tag (the optional group holds the gap, so it is tried).
_CLONE_IMAGE = re.compile(r'<img[^>]*?src="(/asset-store/[0-9a-f]{64})"(?:[^>]*?alt="([^"]*)")?')
#: A captured section's video, named on the <video> itself or on one of its <source>s.
_CLONE_VIDEO = re.compile(r'<(?:video|source)\b[^>]*?src="/asset-store/([0-9a-f]{64})"')


def asset_store_file(digest: str) -> str:
    return f"/asset-store/{digest}"


def _record_digest(record: Mapping[str, Any]) -> str | None:
    value = ((record.get("media") or {}).get("digest") or {}).get("value")
    return value if isinstance(value, str) and _DIGEST.fullmatch(value) else None


def brand_asset(record: Mapping[str, Any], *, description: str | None) -> dict | None:
    """One engine asset record as a site-kit BrandAsset, or None when it names no bytes."""

    digest = _record_digest(record)
    if digest is None:
        return None
    return {
        "kind": record.get("kind") or "other",
        "label": record.get("label"),
        "description": description,
        "mime": (record.get("media") or {}).get("mime_type"),
        "file": asset_store_file(digest),
        "logo": record.get("logo"),
    }


def captured_asset_id(digest: str) -> str:
    """The asset the capture ingested from a captured byte string: every captured image is ingested
    as ``asset_ing_<sha256[:16]>`` (``capture/evidence_builder._ingest_one``) and described there."""

    return f"asset_ing_{digest[:16]}"


def captured_image_descriptions(clones: list[Mapping[str, Any]], *, workspace_id: str) -> dict[str, str]:
    """``{digest: description}`` for the clones' images, read from the description cache the capture
    filled (the same cache kit assets use, keyed by the asset ingested from those bytes)."""

    digests = {
        match.group(1).rsplit("/", 1)[1]
        for clone in clones
        for match in _CLONE_IMAGE.finditer(str(clone.get("html") or ""))
    }
    if not digests:
        return {}
    from lumen_ingestion.describe import DescriptionStore

    rows = DescriptionStore(workspace_id=workspace_id).get_many([captured_asset_id(d) for d in sorted(digests)])
    found: dict[str, str] = {}
    for digest in digests:
        row = rows.get(captured_asset_id(digest)) or {}
        text = row.get("description") or row.get("title")
        if text:
            found[digest] = str(text)
    return found


def clone_video_renditions(clones: list[Mapping[str, Any]], *, workspace_id: str) -> dict[str, dict]:
    """``{video digest: {"poster", "rendition"}}`` for the clones' videos: what the capture made for
    them (``lumen_ingestion.capture.video_renditions``), kept beside the fragments."""

    digests = {digest for clone in clones for digest in _CLONE_VIDEO.findall(str(clone.get("html") or ""))}
    if not digests:
        return {}
    from lumen_ingestion.capture.video_renditions import video_renditions_for

    return video_renditions_for(digests, workspace_id=workspace_id)


def clone_images(
    clones: list[Mapping[str, Any]], descriptions: Mapping[str, str] | None = None
) -> dict[str, dict]:
    """Photos and graphics captured with the seller's own sections (site-kit's `cloneImages`): each
    described by its digest's stored description, else its alt text, else the section it came from."""

    found: dict[str, dict] = {}
    for clone in clones:
        for match in _CLONE_IMAGE.finditer(str(clone.get("html") or "")):
            file = match.group(1)
            if file in found:
                continue
            label = clone.get("label")
            found[file] = {
                "kind": "captured_image", "label": label,
                "description": (descriptions or {}).get(file.rsplit("/", 1)[1])
                or match.group(2) or f'From the seller\'s section "{label}"',
                "mime": None, "file": file, "logo": None,
            }
    return found


def site_brand_data(
    *,
    slug: str,
    kit: Mapping[str, Any],
    kit_assets: Mapping[str, Mapping[str, Any]],
    font_faces: list[Mapping[str, Any]],
    clones: list[Mapping[str, Any]],
    library_assets: Mapping[str, Mapping[str, Any]],
    captured_image_descriptions: Mapping[str, str] | None = None,
    video_renditions: Mapping[str, Mapping[str, Any]] | None = None,
    library_fonts: list[Mapping[str, Any]] | None = None,
) -> dict:
    """BrandData: the kit, its assets and fonts, the released clones and their images, and the
    workspace library assets the site already uses (a generated image is described by its prompt).
    ``captured_image_descriptions`` (``{digest: text}``) describes the clones' images;
    ``video_renditions`` (``{video digest: {poster, rendition}}``) rides on each clone as ``videos``
    (its own videos only), for site-kit's ``fillClone``. ``library_fonts`` is the font library as
    ``font_library.site_library_fonts`` gives it (``libraryFonts``: offered after the kit's fonts for
    manual styling, site element inspector plan 2)."""

    assets: dict[str, dict] = {}
    for asset_id, entry in kit_assets.items():
        record = entry.get("record") or {}
        built = brand_asset(record, description=entry.get("description") or record.get("description"))
        if built is not None:
            assets[asset_id] = built
    for asset_id, entry in library_assets.items():
        if asset_id in assets:
            continue
        record = entry.get("record") or {}
        generated = (record.get("source") or {}).get("kind") == "generated"
        description = f"generated: {record.get('label') or ''}" if generated else (
            entry.get("description") or record.get("description"))
        built = brand_asset(record, description=description)
        if built is not None:
            if generated:
                built["kind"] = "generated_image"
            assets[asset_id] = built
    for file, asset in clone_images(clones, captured_image_descriptions).items():
        assets.setdefault(file, asset)
    fonts = [
        {"family": face["family"], "weight": face.get("weight"), "style": face.get("style") or "normal",
         "file": asset_store_file(str(face["digest"]))}
        for face in font_faces
        if isinstance(face.get("family"), str) and face.get("family") and _DIGEST.fullmatch(str(face.get("digest") or ""))
    ]
    return {
        "slug": slug,
        "kit": dict(kit),
        "fonts": fonts,
        "assets": assets,
        "clones": {str(clone["id"]): _with_videos(clone, video_renditions or {}) for clone in clones},
        "libraryFonts": [dict(family) for family in library_fonts or []],
    }


def _with_videos(clone: Mapping[str, Any], renditions: Mapping[str, Mapping[str, Any]]) -> dict:
    videos = {
        digest: dict(renditions[digest])
        for digest in _CLONE_VIDEO.findall(str(clone.get("html") or ""))
        if digest in renditions
    }
    return {**clone, "videos": videos} if videos else dict(clone)


def clone_from_fragment(section: Mapping[str, Any], loaded: Any) -> dict:
    """A released clone (a registry row and its payload) as a site-kit Clone, with its degraded note."""

    from .fragments.refs import fragment_wrapper_class

    fragment_id = str(section["fragment_id"])
    slots = {
        str(key): {"kind": entry.get("kind"), "fallback": entry.get("fallback")}
        for key, entry in (loaded.slot_manifest or {}).items()
        if isinstance(entry, dict)
    }
    return {
        "id": fragment_id,
        "role": section.get("section_role") or "section",
        "label": section.get("label") or fragment_id,
        "page_url": section.get("page_url") or "",
        "section_index": section.get("section_index"),
        "wrapper_class": fragment_wrapper_class(fragment_id),
        "html": loaded.html,
        "css": loaded.css,
        "slots": slots,
        "degraded_note": section.get("degraded_note"),
    }
