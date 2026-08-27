"""Turning one captured page's sections into real fragments (clone-fidelity F2.2).

Task 11 says where a page's sections are and what each one is. This is what makes them
**artifacts**: per section, extract the subtree, harvest the references it makes, sanitize it,
give it the page's rules that dress it, find the spots a document may re-fill, crop its preview
out of the screenshot F0 already took, and write the registry row — bound to the brand kit the
same ingestion published, born ``draft``, waiting on the same human approval the kit itself
waits on.

**Per-section failure, never per-job.** A section whose background image was never captured
refuses — that is the reference gate's fail-closed contract and it is right — but it refuses
ALONE. A page with one unmintable section still yields the others, and the refusal lands as a
loud ``LUMI0530`` naming the reference, so a human can see which asset to go and get. The
alternative (one bad section takes the ingest down) would mean the more of a site we clone, the
less likely any of it lands.

**The order the stages run in is load-bearing.** References are harvested from the RAW subtree
and the matched CSS *before* sanitization, because the sanitizer needs the finished rehost map
to gate against; slot detection runs *after* sanitization, because a slot must never be stamped
on an element the sanitizer was about to remove; and the preview is cropped last, because its
digest is part of the artifact's identity.

**The rehost map is keyed on the token as the page wrote it.** ``refs.resolve_asset_reference``
looks a reference up EXACTLY as it appears in the markup — Task 6's ruling, because normalising
a URL here would mean guessing which of two spellings the rehoster meant, and a wrong guess
serves the wrong bytes silently. Resolution against a base URL happens only to FIND the
captured bytes; the key stays raw.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import unquote_to_bytes, urljoin

import tinycss2
from lumen_api.fragments import (
    WEB_FRAGMENT_SOURCE_KEY,
    FragmentRefused,
    asset_url_digest,
    create_web_fragment,
    parse_srcset_candidates,
)
from lumen_api.fragments.cssscope import PRELUDE_REFERENCE_STRIP
from lumen_api.fragments.sanitize import sanitize_fragment_html
from selectolax.lexbor import LexborHTMLParser
from selectolax.parser import HTMLParser as SectionParser
from tinycss2 import ast

from .cssmatch import rules_for_subtree
from .segment import SectionRecord, SectionSegmentation, resolve_section
from .slotdetect import detect_slots

logger = logging.getLogger(__name__)

#: How many sections ONE ingestion may mint, across every page it captured.
#:
#: A fragment is not free: a payload blob, a preview blob, a row, and — much more expensively —
#: a line in a human's picker. Twelve is one homepage's worth of real sections (nav, hero, three
#: or four feature bands, proof, testimonial, pricing, FAQ, CTA, footer), which is the shape
#: this phase targets. Reaching it is reported, never silently truncated: an ingest that clones
#: twelve of forty sections and does not say so is an ingest nobody can trust.
SECTION_MINT_CAP = 12

#: A preview is a thumbnail in a picker, not a rendition. A 2x full-page shot of a tall hero is
#: megabytes; nothing that reads this blob wants them.
MAX_PREVIEW_WIDTH = 1200

#: One section could not be minted. Per-section and loud, with the reason and the reference.
MINT_FAILED_CODE = "LUMI0530"
#: A section minted, but no preview could be cropped for it (``preview_digest`` is NULL).
MINT_NO_PREVIEW_CODE = "LUMI0531"
#: The per-ingest section cap was reached; the tail was not minted.
MINT_CAPPED_CODE = "LUMI0532"
#: A re-mint met a row that already exists with different metadata. The content is the same
#: (the id is its content address); the label or the provenance is not, and first writer keeps
#: them — so the divergence is stated rather than lost.
MINT_METADATA_DIVERGED_CODE = "LUMI0533"

_PREVIEW_MEDIA_TYPE = "image/png"
_DEFAULT_INLINE_MEDIA_TYPE = "application/octet-stream"

#: Attributes whose value loads bytes. Mirrors ``sanitize._ASSET_ATTRS`` deliberately: the
#: harvest must cover exactly what the sanitizer will gate, or the map has a hole with the
#: shape of a refusal.
_ASSET_ATTRS = frozenset({"src", "poster", "background"})
_ASSET_LIST_ATTRS = frozenset({"srcset", "imagesrcset"})
_SVG_ASSET_ELEMENTS = frozenset({"use", "image", "feimage", "textpath", "mpath", "pattern"})
_IMAGE_SET_FUNCTIONS = frozenset({"image-set", "-webkit-image-set"})


# --------------------------------------------------------------------------- #
# what one ingestion has to hand
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CapturedAsset:
    """One file F0 downloaded, keyed by the absolute URL it was fetched from."""

    url: str
    data: bytes
    content_type: str | None = None

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def captured_assets(snapshot: Any) -> dict[str, CapturedAsset]:
    """Every byte string one captured page holds, by absolute url. Duck-typed on ``SiteSnapshot``.

    The screenshot is left out: it is the page's picture, not one of its references, and putting
    it in the rehost map would let a section point its ``<img>`` at a photograph of itself.
    """
    assets: dict[str, CapturedAsset] = {}
    for download in getattr(snapshot, "downloads", None) or []:
        if getattr(download, "kind", None) == "screenshot":
            continue
        url = getattr(download, "url", "") or ""
        if not url:
            continue
        try:
            data = base64.b64decode(getattr(download, "bytes_b64", "") or "")
        except (binascii.Error, ValueError):
            continue
        assets[url] = CapturedAsset(
            url=url, data=data, content_type=getattr(download, "content_type", None)
        )
    return assets


# --------------------------------------------------------------------------- #
# the reference harvest
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReferenceHarvest:
    """Every byte-loading reference one section makes, and what became of it."""

    #: raw token (as written) → the absolute url whose captured bytes it names
    resolved: dict[str, str] = field(default_factory=dict)
    #: raw ``data:`` token → the bytes it inlines and their media type, to be given custody
    inline: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    #: raw tokens nothing was captured for. These make the fragment refuse, by design.
    missing: tuple[str, ...] = ()
    #: raw tokens that would resolve two different ways. Dropped rather than guessed.
    conflicts: tuple[str, ...] = ()


def build_reference_harvest(
    *,
    subtree_html: str,
    page_url: str,
    css_blocks: Sequence[tuple[str, str]],
    captured: Mapping[str, CapturedAsset],
) -> ReferenceHarvest:
    """Read one section's markup and its matched CSS, and say what bytes each reference names.

    ``css_blocks`` is ``(sheet url, css text)`` because a ``url()`` resolves against the sheet
    it was written in, not against the page: an ``/assets/sprite.png`` in a stylesheet served
    from a CDN is a CDN url, and resolving it against the page would look up bytes nobody
    fetched and refuse a section that is perfectly fine.
    """
    found: dict[str, set[str]] = {}
    inline: dict[str, tuple[bytes, str]] = {}
    missing: list[str] = []

    def offer(token: str, base: str) -> None:
        raw = (token or "").strip()
        if not raw or raw.startswith("#"):
            return
        if asset_url_digest(raw) is not None:
            return  # already ours; the reference gate recognises it without a map
        if raw.startswith("data:"):
            decoded = _decode_data_uri(raw)
            if decoded is not None:
                inline.setdefault(raw, decoded)
            elif raw not in missing:
                missing.append(raw)
            return
        absolute = urljoin(base, raw)
        if absolute in captured:
            found.setdefault(raw, set()).add(absolute)
        elif raw not in missing:
            missing.append(raw)

    _harvest_html(subtree_html, page_url, offer)
    for sheet_url, text in css_blocks:
        # A sheet's own url is itself resolved against the page first: the capture records it
        # as the page wrote it, so a `<link href="/s.css">` arrives here as `/s.css`, and using
        # that raw as a base would make every reference inside it page-relative-to-nothing.
        base = (
            page_url
            if (not sheet_url or sheet_url.startswith("inline:"))
            else urljoin(page_url, sheet_url)
        )
        _harvest_css(text, base, offer)

    resolved: dict[str, str] = {}
    conflicts: list[str] = []
    for raw, urls in found.items():
        if len(urls) == 1:
            resolved[raw] = next(iter(urls))
        else:
            conflicts.append(raw)
    return ReferenceHarvest(
        resolved=resolved,
        inline=inline,
        missing=tuple(missing),
        conflicts=tuple(sorted(conflicts)),
    )


def _harvest_html(html: str, page_url: str, offer: Callable[[str, str], None]) -> None:
    tree = LexborHTMLParser(html or "")
    body = tree.body
    if body is None:
        return
    for node in body.traverse(include_text=False):
        tag = (node.tag or "").lower()
        if not tag or tag == "body":
            continue
        for name, value in node.attributes.items():
            lowered = name.lower()
            raw = value or ""
            if lowered in _ASSET_ATTRS or (
                lowered in ("href", "xlink:href") and tag in _SVG_ASSET_ELEMENTS
            ):
                offer(raw, page_url)
            elif lowered in _ASSET_LIST_ATTRS:
                for url, _descriptor in parse_srcset_candidates(raw):
                    offer(url, page_url)
            elif lowered == "style":
                _harvest_component_values(
                    tinycss2.parse_component_value_list(raw), page_url, offer
                )


def _harvest_css(text: str, base: str, offer: Callable[[str, str], None]) -> None:
    _harvest_component_values(tinycss2.parse_component_value_list(text or ""), base, offer)


def _harvest_component_values(
    tokens: Sequence[object], base: str, offer: Callable[[str, str], None]
) -> None:
    """Every ``url()`` and every ``image-set()`` string candidate, at any nesting depth.

    ``image-set()`` loads bytes through a BARE STRING rather than through ``url()``, which is
    exactly the shape the scoper had to grow a special case for; harvesting has to know the same
    thing or the map is missing the one reference the gate will refuse on.
    """
    for token in tokens:
        if isinstance(token, ast.URLToken):
            offer(token.value, base)
        elif isinstance(token, ast.FunctionBlock):
            if token.lower_name == "url":
                for argument in token.arguments:
                    if isinstance(argument, ast.StringToken):
                        offer(argument.value, base)
                        break
            elif token.lower_name in _IMAGE_SET_FUNCTIONS:
                for argument in token.arguments:
                    if isinstance(argument, ast.StringToken):
                        offer(argument.value, base)
                    else:
                        _harvest_component_values([argument], base, offer)
            else:
                _harvest_component_values(token.arguments, base, offer)
        elif isinstance(
            token, (ast.ParenthesesBlock, ast.SquareBracketsBlock, ast.CurlyBracketsBlock)
        ):
            _harvest_component_values(token.content, base, offer)


def _decode_data_uri(uri: str) -> tuple[bytes, str] | None:
    """``data:image/png;base64,…`` → its bytes and media type, or ``None`` if it is malformed.

    F1 ruled that a ``data:`` src refuses rather than being inlined, and named the correct fix
    as this one: F2 rehosts the bytes into the blob namespace before minting, so they are in
    custody like every other byte a fragment displays. Real pages need it — Webflow and Next
    both emit a base64 LQIP placeholder on every image.
    """
    if not uri.startswith("data:"):
        return None
    header, separator, payload = uri[len("data:") :].partition(",")
    if not separator:
        return None
    parameters = header.split(";")
    media_type = parameters[0].strip() or _DEFAULT_INLINE_MEDIA_TYPE
    try:
        if "base64" in (parameter.strip().lower() for parameter in parameters[1:]):
            data = base64.b64decode(payload, validate=False)
        else:
            data = unquote_to_bytes(payload)
    except (binascii.Error, ValueError):
        return None
    return (data, media_type) if data else None


# --------------------------------------------------------------------------- #
# preview crops
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CropExtent:
    """A section's vertical extent in CSS pixels, and how we came to believe it.

    ``bottom_px is None`` means "to the end of the page" — the honest shape for a footer whose
    extent is inferred, because the screenshot's own height IS the page's bottom and inventing a
    number for it would be a measurement we never made.
    """

    top_px: float
    bottom_px: float | None
    basis: str


def crop_extent(
    segmentation: SectionSegmentation, record: SectionRecord
) -> CropExtent | None:
    """Where in the full-page screenshot this section is, or ``None`` if nothing says.

    A measured section answers itself. **Nav and footer usually cannot** (Task 11's ``LUMI0524``
    carry: the capture probe roots at ``<main>``, so on a semantic page the two most-cloned
    sections of all are never measured), and a fragment with no preview is a fragment nobody
    picks — so those two are INFERRED from the measured band sequence: the nav is whatever sits
    above the first measured band, the footer whatever sits below the last. The basis says which
    it was, every time, so a preview that turns out wrong is traceable rather than mysterious.

    Everything else with no geometry gets ``None``. Guessing a middle section's extent would
    show a picture of its neighbour, and a picker that lies is worse than one with a gap.
    """
    geometry = record.geometry
    if geometry is not None and geometry.bottom_px > geometry.top_px:
        return CropExtent(
            top_px=geometry.top_px, bottom_px=geometry.bottom_px, basis=geometry.basis
        )

    measured = [
        section.geometry
        for section in segmentation.sections
        if section.geometry is not None and section.geometry.bottom_px > section.geometry.top_px
    ]
    if not measured:
        return None
    if record.role == "nav" and record.index < min(
        section.index for section in segmentation.sections if section.geometry is not None
    ):
        return CropExtent(top_px=0.0, bottom_px=measured[0].top_px, basis="inferred-above-first-band")
    if record.role == "footer" and record.index > max(
        section.index for section in segmentation.sections if section.geometry is not None
    ):
        return CropExtent(top_px=measured[-1].bottom_px, bottom_px=None, basis="inferred-below-last-band")
    return None


def crop_preview(
    screenshot: bytes, extent: CropExtent, *, viewport_width: int | None
) -> bytes | None:
    """Cut one section out of F0's full-page screenshot. ``None`` when the cut is not real.

    The shot is in DEVICE pixels and the extent is in CSS pixels, so the scale is the shot's own
    width over the width the page was measured at — read from the image rather than assumed,
    because a retina capture is 2x and a mobile one is not.

    No new browser pass: F0 already paid for this picture, and re-rendering a page months later
    to crop it would produce a picture of a DIFFERENT page.
    """
    from PIL import Image, UnidentifiedImageError

    if not screenshot:
        return None
    try:
        image = Image.open(io.BytesIO(screenshot))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return None

    scale = (image.width / viewport_width) if viewport_width else 1.0
    if scale <= 0:
        return None
    top = max(0, int(round(extent.top_px * scale)))
    bottom = image.height if extent.bottom_px is None else int(round(extent.bottom_px * scale))
    bottom = min(image.height, bottom)
    if bottom - top < 2 or top >= image.height:
        return None

    cropped = image.convert("RGB").crop((0, top, image.width, bottom))
    if cropped.width > MAX_PREVIEW_WIDTH:
        height = max(1, round(cropped.height * MAX_PREVIEW_WIDTH / cropped.width))
        cropped = cropped.resize((MAX_PREVIEW_WIDTH, height), Image.LANCZOS)
    buffer = io.BytesIO()
    cropped.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# the driver
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MintedSection:
    """One section that became a fragment."""

    fragment_id: str
    section_index: int
    role: str
    label: str
    page_url: str
    status: str
    slot_keys: tuple[str, ...]
    asset_digests: tuple[str, ...]
    preview_digest: str | None
    preview_basis: str | None
    rules_kept: int

    def as_job_ref(self) -> dict[str, Any]:
        """The bounded shape recorded on the ingestion job's evidence payload."""
        return {
            "fragment_id": self.fragment_id,
            "role": self.role,
            "label": self.label,
            "page_url": self.page_url,
            "status": self.status,
            "preview_digest": self.preview_digest,
            "slots": list(self.slot_keys),
        }


@dataclass(frozen=True)
class MintOutcome:
    minted: tuple[MintedSection, ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()


def mint_sections(
    segmentation: SectionSegmentation,
    *,
    html: str,
    stylesheets: Sequence[Any],
    captured: Mapping[str, CapturedAsset],
    screenshot: bytes | None,
    source_kit_id: str | None,
    source_kit_version: int | None,
    register_bytes: Callable[[bytes, str], str],
    create_fragment: Callable[..., tuple[dict[str, Any], Any]],
    limit: int = SECTION_MINT_CAP,
) -> MintOutcome:
    """Mint every section of one captured page, up to ``limit``. Never raises.

    The two durable seams are injected — ``register_bytes(data, media_type) -> digest`` and the
    F1 creation seam — so this driver is a pure function of its inputs plus two calls, and the
    whole pipeline can be exercised without a database. The pipeline stage passes the real ones.
    """
    minted: list[MintedSection] = []
    diagnostics: list[dict[str, Any]] = []

    # ONE parse for the whole page, shared by every section's re-find. `resolve_section` reads
    # and never mutates, and a marketing page's html runs to megabytes — re-parsing it twelve
    # times to extract twelve subtrees would be the most expensive thing this module does.
    tree = SectionParser(html or "")

    budget = max(0, limit)
    for record in segmentation.sections:
        if len(minted) >= budget:
            break
        try:
            result = _mint_one(
                segmentation,
                record,
                tree=tree,
                stylesheets=stylesheets,
                captured=captured,
                screenshot=screenshot,
                source_kit_id=source_kit_id,
                source_kit_version=source_kit_version,
                register_bytes=register_bytes,
                create_fragment=create_fragment,
                diagnostics=diagnostics,
            )
        except FragmentRefused as refusal:
            diagnostics.append(
                _diag(
                    MINT_FAILED_CODE,
                    f"section {record.index} ({record.role}) of {segmentation.page_url} was not "
                    f"minted: {refusal.message}",
                    section_index=record.index,
                    role=record.role,
                    reason=refusal.code,
                    reference=refusal.reference,
                )
            )
            continue
        except Exception as error:  # noqa: BLE001 — one section is not the ingest
            logger.exception(
                "fragment minting failed for section %s of %s", record.index, segmentation.page_url
            )
            diagnostics.append(
                _diag(
                    MINT_FAILED_CODE,
                    f"section {record.index} ({record.role}) of {segmentation.page_url} was not "
                    f"minted: {type(error).__name__}: {error}",
                    section_index=record.index,
                    role=record.role,
                    reason="unexpected_error",
                )
            )
            continue
        if result is not None:
            minted.append(result)

    remaining = len(segmentation.sections) - len(minted) - _refused_count(diagnostics)
    if remaining > 0 and len(minted) >= budget:
        diagnostics.append(
            _diag(
                MINT_CAPPED_CODE,
                f"minted the first {len(minted)} sections of {segmentation.page_url} and stopped; "
                f"{remaining} more were segmented and not cloned",
                page_url=segmentation.page_url,
                cap=budget,
                remaining=remaining,
            )
        )
    return MintOutcome(minted=tuple(minted), diagnostics=tuple(diagnostics))


def _mint_one(
    segmentation: SectionSegmentation,
    record: SectionRecord,
    *,
    tree: SectionParser,
    stylesheets: Sequence[Any],
    captured: Mapping[str, CapturedAsset],
    screenshot: bytes | None,
    source_kit_id: str | None,
    source_kit_version: int | None,
    register_bytes: Callable[[bytes, str], str],
    create_fragment: Callable[..., tuple[dict[str, Any], Any]],
    diagnostics: list[dict[str, Any]],
) -> MintedSection | None:
    node = resolve_section(tree, record)
    if node is None:
        diagnostics.append(
            _diag(
                MINT_FAILED_CODE,
                f"section {record.index} ({record.role}) of {segmentation.page_url} could not be "
                "re-found in the html it was segmented from, so nothing was minted rather than "
                "the wrong subtree",
                section_index=record.index,
                role=record.role,
                reason="unresolved_handle",
            )
        )
        return None
    subtree = node.html or ""

    matched = rules_for_subtree(stylesheets, subtree_html=subtree)
    harvest = build_reference_harvest(
        subtree_html=subtree,
        page_url=segmentation.page_url,
        css_blocks=matched.blocks,
        captured=captured,
    )

    rehosted: dict[str, str] = {}
    for token, url in sorted(harvest.resolved.items()):
        asset = captured[url]
        rehosted[token] = register_bytes(
            asset.data, asset.content_type or _DEFAULT_INLINE_MEDIA_TYPE
        )
    for token, (data, media_type) in sorted(harvest.inline.items()):
        rehosted[token] = register_bytes(data, media_type)

    # Sanitize BEFORE detection so a slot can never be offered on an element the sanitizer was
    # about to remove, and so an image slot's fallback is a digest the gate already vouched for.
    # An unrehostable reference raises here — the fail-closed refusal, per section.
    sanitized = sanitize_fragment_html(subtree, rehosted=rehosted)
    detected = detect_slots(sanitized.html)

    preview, extent = _preview(segmentation, record, screenshot, diagnostics)
    row, artifact = create_fragment(
        html=sanitized.html,
        css=matched.css,
        rehosted=rehosted,
        slots=list(detected.specs),
        source_url=segmentation.page_url,
        section_role=record.role,
        label=_label(record),
        source_kit_id=source_kit_id,
        source_kit_version=source_kit_version,
        preview=preview,
        preview_media_type=_PREVIEW_MEDIA_TYPE,
        provenance=_provenance(segmentation, record, matched, detected, harvest, extent),
        prelude_reference=PRELUDE_REFERENCE_STRIP,
    )
    _note_metadata_divergence(row, record, segmentation, diagnostics)

    return MintedSection(
        fragment_id=str(row["fragment_id"]),
        section_index=record.index,
        role=record.role,
        label=_label(record),
        page_url=segmentation.page_url,
        status=str(row.get("status") or "draft"),
        slot_keys=detected.keys,
        asset_digests=tuple(artifact.payload.get("asset_digests") or ()),
        preview_digest=row.get("preview_digest"),
        preview_basis=extent.basis if extent is not None else None,
        rules_kept=matched.rules_kept,
    )


def _preview(
    segmentation: SectionSegmentation,
    record: SectionRecord,
    screenshot: bytes | None,
    diagnostics: list[dict[str, Any]],
) -> tuple[bytes | None, CropExtent | None]:
    extent = crop_extent(segmentation, record)
    preview = (
        crop_preview(screenshot, extent, viewport_width=segmentation.viewport_width)
        if (screenshot and extent is not None)
        else None
    )
    if preview is None:
        diagnostics.append(
            _diag(
                MINT_NO_PREVIEW_CODE,
                f"section {record.index} ({record.role}) of {segmentation.page_url} was minted "
                "without a preview image: "
                + (
                    "this capture stored no full-page screenshot"
                    if not screenshot
                    else "no crop rectangle could be derived from what the browser measured"
                ),
                section_index=record.index,
                role=record.role,
                basis=extent.basis if extent is not None else None,
            )
        )
    return preview, extent


def _label(record: SectionRecord) -> str:
    """``Hero — Ship faster``: what a human reads in the picker.

    Role first because it is the reliable half; the heading second because it is the half that
    tells two heroes apart. A section with no heading gets its text preview, and one with
    neither gets its role alone — an honest label, not a fabricated one.
    """
    role = record.role.replace("_", " ").title()
    detail = (record.heading or record.text_preview or "").strip()
    if not detail:
        return role
    return f"{role} — {detail[:80]}".strip()


def _provenance(
    segmentation: SectionSegmentation,
    record: SectionRecord,
    matched: Any,
    detected: Any,
    harvest: ReferenceHarvest,
    extent: CropExtent | None,
) -> dict[str, Any]:
    """Everything needed to answer "where did this fragment come from, and how sure were we?".

    Bounded on purpose: the evidence list is Task 11's own (a handful of entries), the notes are
    capped by their producers, and no markup, CSS or byte string goes in here. This is a row.
    """
    return {
        "snapshot_id": segmentation.snapshot_id,
        "page_url": segmentation.page_url,
        "viewport_width": segmentation.viewport_width,
        "section_index": record.index,
        "dom_path": list(record.dom_path),
        "tag": record.tag,
        "element_id": record.element_id,
        "class_names": list(record.class_names),
        "band_index": record.band_index,
        "confidence": record.confidence,
        "heading": record.heading,
        "evidence": [
            {
                "signal": item.signal,
                "role": item.role,
                "weight": item.weight,
                "detail": item.detail,
            }
            for item in record.evidence
        ],
        "geometry": (
            {
                "top_px": record.geometry.top_px,
                "bottom_px": record.geometry.bottom_px,
                "basis": record.geometry.basis,
            }
            if record.geometry is not None
            else None
        ),
        "preview_basis": extent.basis if extent is not None else None,
        "css": {
            "rules_considered": matched.rules_considered,
            "rules_kept": matched.rules_kept,
            "sheets_read": matched.sheets_read,
            "byte_length": matched.byte_length,
        },
        "slots": list(detected.keys),
        "slot_notes": list(detected.notes),
        "reference_conflicts": list(harvest.conflicts),
    }


def _note_metadata_divergence(
    row: Mapping[str, Any],
    record: SectionRecord,
    segmentation: SectionSegmentation,
    diagnostics: list[dict[str, Any]],
) -> None:
    """A re-mint converges by construction; a re-mint that DISAGREES is worth saying out loud.

    ``insert_web_fragment`` is ``ON CONFLICT DO NOTHING``, so the first writer keeps the label
    and the provenance. That is the right rule (the content is identical — the id is its content
    address — and the row is immutable), but it means a second harvest that saw the section
    differently loses its reading silently. It does not have to be silent.
    """
    provenance = row.get("provenance") or {}
    stored_page = provenance.get("page_url")
    if not stored_page:
        return
    if stored_page == segmentation.page_url and provenance.get("dom_path") == list(
        record.dom_path
    ):
        return
    diagnostics.append(
        _diag(
            MINT_METADATA_DIVERGED_CODE,
            f"section {record.index} ({record.role}) of {segmentation.page_url} is byte-identical "
            f"to a fragment already held from {stored_page!r}; the first harvest's label and "
            "provenance were kept",
            severity="info",
            section_index=record.index,
            role=record.role,
            fragment_id=row.get("fragment_id"),
            held_from=stored_page,
        )
    )


def _refused_count(diagnostics: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for diag in diagnostics if diag.get("code") == MINT_FAILED_CODE)


def _diag(code: str, message: str, *, severity: str = "warning", **extra: Any) -> dict[str, Any]:
    """The same ``{code, severity, message, **extra}`` shape every ingestion diagnostic uses."""
    return {"code": code, "severity": severity, "message": message, **extra}


def make_fragment_writer(
    storage: Any, *, workspace_id: str
) -> Callable[..., tuple[dict[str, Any], Any]]:
    """The real F1 creation seam, bound to one workspace's storage."""

    def _create(**kwargs: Any) -> tuple[dict[str, Any], Any]:
        return create_web_fragment(storage, workspace_id=workspace_id, **kwargs)

    return _create


def make_asset_rehoster(blobs: Any) -> Callable[[bytes, str], str]:
    """Give one captured byte string durable custody, and answer with its **digest**.

    ``DesignBlobStore.register`` answers with the storage KEY (``{workspace}/design/{sha256}``),
    which is the storage layer's business and is emphatically not what a fragment cites — the
    artifact names ``/asset-store/<digest>``, and the reference gate refuses anything that is
    not a bare sha256. Computing the digest here rather than parsing it back out of a key keeps
    the two layers from having to agree on a key's shape.
    """

    def _rehost(data: bytes, media_type: str) -> str:
        blobs.register(data, media_type=media_type, source_key=WEB_FRAGMENT_SOURCE_KEY)
        return hashlib.sha256(data).hexdigest()

    return _rehost


__all__ = [
    "MAX_PREVIEW_WIDTH",
    "MINT_CAPPED_CODE",
    "MINT_FAILED_CODE",
    "MINT_METADATA_DIVERGED_CODE",
    "MINT_NO_PREVIEW_CODE",
    "SECTION_MINT_CAP",
    "CapturedAsset",
    "CropExtent",
    "MintOutcome",
    "MintedSection",
    "ReferenceHarvest",
    "build_reference_harvest",
    "captured_assets",
    "crop_extent",
    "crop_preview",
    "make_asset_rehoster",
    "make_fragment_writer",
    "mint_sections",
]
