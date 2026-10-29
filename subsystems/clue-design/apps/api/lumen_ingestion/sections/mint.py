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
retains exact URL/query spelling while allowing fragment-only aliases that name equal held
content. Conflicting aliases refuse rather than guessing. Resolution against a base URL
happens only to FIND the captured bytes; the rehost-map key stays raw and the authored
fragment suffix survives rewriting.
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
    FRAGMENT_STATUS_DORMANT,
    WEB_FRAGMENT_SOURCE_KEY,
    FragmentRefused,
    asset_url_digest,
    create_web_fragment,
    parse_srcset_candidates,
)
from lumen_api.fragments.cssscope import PRELUDE_REFERENCE_STRIP
from lumen_api.fragments.reference_identity import ReferenceConflict, ReferenceIndex
from lumen_api.fragments.sanitize import sanitize_fragment_html
from py_lumen_config import settings
from selectolax.lexbor import LexborHTMLParser
from selectolax.parser import HTMLParser as SectionParser
from tinycss2 import ast

from .budget import (
    MIN_PREVIEW_WIDTH,
    MINT_BUDGET_CODE,
    OUTCOME_DEGRADED,
    OUTCOME_REFUSED,
    OUTCOME_WARNED,
    PageWeight,
    budget_diagnostic,
)
from ..capture.svg_looks import lift_svg_looks
from .cssmatch import rules_for_subtree, unhide_root_markup, unhide_root_rules
from .deadheight import (
    DEAD_HEIGHT_REASON,
    DeadHeight,
    DeadHeightAssessment,
    assess_dead_height,
)
from .rootunits import RootUnits, prepare_root_units
from .segment import SectionRecord, SectionSegmentation, recovery_sections, resolve_section
from .slotdetect import detect_slots
from .source_context import SourceDocumentContext

logger = logging.getLogger(__name__)

#: The RUNAWAY BACKSTOP on how many sections one ingestion mints, across every page it captured.
#:
#: **Not a working limit.** FOUNDER RULING 2026-08-27: extraction yields as many fragments as the
#: page honestly offers, and the F2 acceptance's "at least five" is a floor, not a target. This
#: number exists so a pathological page cannot mint without bound; it must never be the reason a
#: real one comes back short. That is why it is the capture probe's own ``MAX_SECTIONS``
#: (``capture/geometry.py``), which is also the persisted-band ceiling (``sections/bands.py``),
#: rather than a guess about how many sections a homepage "should" have — minting is then
#: incapable of being a SECOND, tighter ceiling on a page the capture layer measured in full.
#:
#: Configurable as ``LUMEN_FRAGMENT_MINT_CAP``. Tripping it is reported loudly (``LUMI0532``),
#: for the sections of a page that were skipped and for whole later pages never reached.
SECTION_MINT_CAP = int(settings.lumen_fragment_mint_cap)
LIBRARY_MINT_CAP = int(settings.lumen_site_library_fragment_mint_cap)

#: A preview is a thumbnail in a picker, not a rendition. A 2x full-page shot of a tall hero is
#: megabytes; nothing that reads this blob wants them.
MAX_PREVIEW_WIDTH = 1200

#: One section could not be minted. Per-section and loud, with the reason and the reference.
MINT_FAILED_CODE = "LUMI0530"
#: A section minted, but no preview could be cropped for it (``preview_digest`` is NULL).
MINT_NO_PREVIEW_CODE = "LUMI0531"
#: The per-ingest section cap was reached; the tail was not minted.
MINT_CAPPED_CODE = "LUMI0532"
#: A section whose sanitized markup shows nothing. Same code as any other per-section refusal —
#: it is a refusal — with its own reason so the population is countable.
#:
#: (No new code: ``LUMI0530`` with ``reason="empty_after_sanitize"``.)
#: A re-mint met a row that already exists with different metadata. The content is the same
#: (the id is its content address); the label or the provenance is not, and first writer keeps
#: them — so the divergence is stated rather than lost.
MINT_METADATA_DIVERGED_CODE = "LUMI0533"
#: A section was minted and born ``degraded``: its captured band is mostly artificial scroll
#: height (F3.0, D-F6). Loud, because it is the repair ladder's trigger — a human or an agent has
#: to do something about this clone before it goes on a page.
MINT_DEGRADED_CODE = "LUMI0534"
#: A section the source site hides was minted ``dormant`` (F3.0, D-F8). Informational: it is off
#: the page and out of discovery by construction, and it is waiting in the inspector for a human.
MINT_DORMANT_CODE = "LUMI0535"
#: A re-mint converged onto an existing row whose degraded marker disagreed with what THIS
#: capture measured, and the newer measurement won (F3.0, ruling R-I1). Says both readings and
#: whether the row was actually updated, because a divergence nobody could write is still a
#: divergence somebody has to know about.
MINT_DEGRADED_RECONCILED_CODE = "LUMI0536"
#: A QUALITY CHECK did not run on a section that was minted anyway (F3.4 fix round, ruling
#: R20-3). Its own code because it is its own fact: `LUMI0537` says a budget refused some bytes,
#: and this says what stopped working as a result. A section minted `degraded=False` because
#: nobody could look at it must never read like a section that was looked at and found sound —
#: that is the honest-absence posture the whole detector is built on (`DeadHeightAssessment.judged`
#: exists for exactly this distinction), and the one place it could still be silent was here.
MINT_CHECK_NOT_RUN_CODE = "LUMI0538"
#: Independent authored descendants attempted after a wrapper refused a missing dependency.
MINT_RECOVERY_CODE = "LUMI0539"

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
    alias_conflicts: set[str] = set()
    references = ReferenceIndex(captured, identity=lambda asset: asset.data)

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
        try:
            captured_key = references.lookup_key(absolute)
        except ReferenceConflict:
            alias_conflicts.add(raw)
            return
        if captured_key is not None:
            found.setdefault(raw, set()).add(captured_key)
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
    conflicts: list[str] = list(alias_conflicts)
    for raw, urls in found.items():
        if raw in alias_conflicts:
            continue
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

    **A hidden-on-source section is never inferred** (F3.0). It was not rendered, so the pixels
    above the first band or below the last belong to the sections that WERE — and here that lie
    would cost more than a bad thumbnail: D-F8 makes a usable preview the condition on which a
    human activates a dormant clone, so a borrowed picture would be the evidence the decision is
    made from. A dormant section with no preview is honestly un-activatable until a capture can
    render it; a dormant section showing somebody else's picture is a trap.
    """
    geometry = record.geometry
    if geometry is not None and geometry.bottom_px > geometry.top_px:
        return CropExtent(
            top_px=geometry.top_px, bottom_px=geometry.bottom_px, basis=geometry.basis
        )
    # Inference only applies to the original top-level flow. Recovered descendants have no
    # measured placement; a footer-like label must not borrow the actual page footer's pixels.
    if record.hidden_on_source or record not in segmentation.sections:
        return None

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
    degraded: bool = False
    degraded_reason: str | None = None
    hidden_on_source: bool = False

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
            # Two facts a human reading the job needs BEFORE they open anything: which clones
            # arrived broken (F3.0's repair queue) and which arrived asleep (F3.0's dormant ones).
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "hidden_on_source": self.hidden_on_source,
        }


@dataclass(frozen=True)
class MintOutcome:
    minted: tuple[MintedSection, ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()


def _recovery_plan(
    segmentation: SectionSegmentation, tree: SectionParser
) -> dict[int, tuple[SectionRecord, ...]]:
    records = (*segmentation.sections, *segmentation.hidden_sections)
    index = max((r.index for r in records), default=-1) + 1
    plan = {}
    for record in segmentation.sections:
        children = recovery_sections(tree, record, start_index=index)
        if children:
            plan[record.index] = children
            index += len(children)
    return plan


def visible_mint_capacity(segmentation: SectionSegmentation, html: str) -> int:
    """Reserve fair page budget for recovery without minting parent AND children.

    The parent is preferred. Only a refused parent spends its reservation on descendants;
    planning with just top-level wrappers would allocate Google's entire body one slot.
    """
    plan = _recovery_plan(segmentation, SectionParser(html or ""))
    return sum(max(1, len(plan.get(record.index, ()))) for record in segmentation.sections)


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
    dormant_limit: int = SECTION_MINT_CAP,
    mark_degraded: Callable[..., dict[str, Any]] | None = None,
    weight: PageWeight | None = None,
    initial_font_px: float | None = None,
) -> MintOutcome:
    """Mint every section of one captured page. Never raises.

    The durable seams are injected — ``register_bytes(data, media_type) -> digest``, the F1
    creation seam, and (F3.0) the degraded-marker writer — so this driver is a pure function of
    its inputs plus those calls, and the whole pipeline can be exercised without a database. The
    pipeline stage passes the real ones.

    **The page's hidden sections are minted too** (F3.0, D-F8): the identical path — extract,
    harvest, sanitize, scope, detect slots — differing only in being born ``dormant``.

    **They draw on their OWN budget** (ruling R-I2), which is the whole reason there are two
    limits rather than one. The mint cap is ingestion-wide, spent across pages, so a single CMS
    homepage carrying a dozen ``w-condition-invisible`` variants could exhaust it and leave later
    pages' VISIBLE sections uncloned — the clone would lose the thing it exists for in order to
    keep sections nobody can see. A separate pool makes that structurally impossible: a hidden
    section can never starve a visible one, on this page or any later one, and each pool reports
    its own exhaustion.
    """
    diagnostics: list[dict[str, Any]] = []
    # ONE running weight for the page (F3.4), carrying all four byte limits. `mint_sections` is
    # called once per captured page, so this object's life is exactly the scope of the per-page
    # budgets it accounts for — and the hidden pool shares it deliberately: bytes at rest are
    # bytes at rest, whether or not a human ever activates the section they belong to.
    #
    # INJECTABLE, and that is the whole test seam. The production ceilings are 5 GiB by founder
    # ruling, so no real page can drive a single budget branch; a caller hands in small limits to
    # exercise them, rather than reaching in and rewriting a module constant.
    weight = weight if weight is not None else PageWeight()

    # ONE parse for the whole page, shared by every section's re-find. `resolve_section` reads
    # and never mutates, and a marketing page's html runs to megabytes — re-parsing it twelve
    # times to extract twelve subtrees would be the most expensive thing this module does.
    tree = SectionParser(html or "")
    root_units = prepare_root_units(stylesheets, html=html, initial_font_px=initial_font_px)
    source_context = SourceDocumentContext.prepare(html, stylesheets, root_units)
    if root_units.notes:
        diagnostics.append(_diag(
            "LUMI0540",
            "source root-unit context was not normalized: " + "; ".join(root_units.notes),
            reason="unsupported_root_units", page_url=segmentation.page_url,
        ))
    recovery_plan = _recovery_plan(segmentation, tree)
    recovery_parents = {
        child.index: parent
        for parent in segmentation.sections
        for child in recovery_plan.get(parent.index, ())
    }

    def _mint_bounded(
        records: Sequence[SectionRecord], budget: int, scope: str
    ) -> list[MintedSection]:
        minted: list[MintedSection] = []
        # Everything this pool ALREADY reported on, whether it raised or merely declined. Both
        # kinds have a `LUMI0530` line naming them, so counting only the raisers made the cap's
        # `remaining` — "segmented and not cloned, and not otherwise reported" — announce sections
        # the job had already explained twice over.
        reported = 0
        queue = list(records)
        for position, record in enumerate(queue):
            if len(minted) >= budget:
                break
            try:
                result = _mint_one(
                    segmentation,
                    record,
                    tree=tree,
                    stylesheets=root_units.stylesheets,
                    root_units=root_units,
                    source_context=source_context,
                    captured=captured,
                    screenshot=screenshot,
                    source_kit_id=source_kit_id,
                    source_kit_version=source_kit_version,
                    register_bytes=register_bytes,
                    create_fragment=create_fragment,
                    mark_degraded=mark_degraded,
                    diagnostics=diagnostics,
                    weight=weight,
                    recovery_parent=recovery_parents.get(record.index),
                )
            except FragmentRefused as refusal:
                # The diagnostic is for the human reading the job; this is for the operator
                # reading the logs, and it carries the refusal's own CODE — an unrehosted
                # reference and an unreadable stylesheet are one sentence to a marketer and two
                # different repairs to whoever has to fix the pipeline.
                logger.warning(
                    "fragment_mint_refused page=%s section=%s role=%s code=%s reference=%s",
                    segmentation.page_url,
                    record.index,
                    record.role,
                    refusal.code,
                    refusal.reference,
                )
                diagnostics.append(
                    _diag(
                        MINT_FAILED_CODE,
                        f"section {record.index} ({record.role}) of {segmentation.page_url} was "
                        f"not minted: {refusal.message}",
                        section_index=record.index,
                        role=record.role,
                        reason=refusal.code,
                        reference=refusal.reference,
                    )
                )
                reported += 1
                # Only dependency custody failures qualify. No fallback after writer errors,
                # security refusals, byte budgets or an empty sanitized shell. No recursive
                # recovery: this map contains original top-level wrapper indices only.
                children = recovery_plan.get(record.index, ())
                if refusal.code == "fragment.unrehosted_reference" and children:
                    omitted = max(0, len(children) - max(0, SECTION_MINT_CAP))
                    children = children[:max(0, SECTION_MINT_CAP)]
                    queue[position + 1 : position + 1] = children
                    diagnostics.append(_diag(
                        MINT_RECOVERY_CODE,
                        f"wrapper section {record.index} refused; attempting {len(children)} "
                        "independent authored descendants. The wrapper layout, decorations "
                        "and inherited context are not preserved; source fidelity is unverified.",
                        section_index=record.index,
                        parent_dom_path=list(record.dom_path),
                        parts=len(children),
                        omitted_parts=omitted,
                        wrapper_layout_preserved=False,
                        fidelity_verified=False,
                    ))
                    if omitted:
                        diagnostics.append(_diag(
                            MINT_CAPPED_CODE,
                            f"{omitted} authored descendants were not attempted because "
                            "the per-wrapper recovery candidate cap was reached",
                            section_index=record.index,
                            scope=scope,
                            cap=SECTION_MINT_CAP,
                            remaining=omitted,
                            reason="recovery_candidate_cap",
                        ))
                continue
            except Exception as error:  # noqa: BLE001 — one section is not the ingest
                logger.exception(
                    "fragment minting failed for section %s of %s",
                    record.index,
                    segmentation.page_url,
                )
                diagnostics.append(
                    _diag(
                        MINT_FAILED_CODE,
                        f"section {record.index} ({record.role}) of {segmentation.page_url} was "
                        f"not minted: {type(error).__name__}: {error}",
                        section_index=record.index,
                        role=record.role,
                        reason="unexpected_error",
                    )
                )
                reported += 1
                continue
            if result is None:
                # A declined section (unresolvable handle, empty after sanitizing) already has
                # its own LUMI0530 line — accounted for, not missing.
                reported += 1
                continue
            minted.append(result)

        remaining = len(queue) - len(minted) - reported
        if remaining > 0 and len(minted) >= budget:
            diagnostics.append(
                _diag(
                    MINT_CAPPED_CODE,
                    f"minted the first {len(minted)} {scope} section(s) of "
                    f"{segmentation.page_url} and stopped; {remaining} more were segmented and "
                    "not cloned",
                    page_url=segmentation.page_url,
                    scope=scope,
                    cap=budget,
                    remaining=remaining,
                )
            )
        return minted

    minted = _mint_bounded(segmentation.sections, max(0, limit), "visible")
    minted += _mint_bounded(segmentation.hidden_sections, max(0, dormant_limit), "dormant")
    return MintOutcome(minted=tuple(minted), diagnostics=tuple(diagnostics))


def _mint_one(
    segmentation: SectionSegmentation,
    record: SectionRecord,
    *,
    tree: SectionParser,
    stylesheets: Sequence[Any],
    root_units: RootUnits,
    source_context: SourceDocumentContext | None,
    captured: Mapping[str, CapturedAsset],
    screenshot: bytes | None,
    source_kit_id: str | None,
    source_kit_version: int | None,
    register_bytes: Callable[[bytes, str], str],
    create_fragment: Callable[..., tuple[dict[str, Any], Any]],
    mark_degraded: Callable[..., dict[str, Any]] | None,
    diagnostics: list[dict[str, Any]],
    weight: PageWeight | None = None,
    recovery_parent: SectionRecord | None = None,
) -> MintedSection | None:
    weight = weight if weight is not None else PageWeight()
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
    subtree = root_units.markup(node.html or "")
    # What capture observed on the section's SVGs becomes fallback rules (see `svg_looks`): they go
    # before the section's own rules, so the site's hover, focus and phone rules still reach them.
    subtree, svg_fallback_css = lift_svg_looks(subtree)

    root_classes = ((tree.root.attributes.get("class") or "").split() if tree.root else ())
    section_context = source_context.for_section(node) if source_context is not None else None
    context_gap = None
    if source_context is None:
        context_gap = {
            "mode": "unsupported", "fidelity_verified": False,
            "limitations": ["source document context could not allocate collision-free markers"],
        }
    elif section_context is None:
        context_gap = {
            "mode": "unsupported" if source_context.unsupported else "not_needed",
            "fidelity_verified": False,
            "limitations": list(source_context.notes) if source_context.unsupported else [],
        }
    try:
        matched = rules_for_subtree(
            stylesheets, subtree_html=subtree, source_root_classes=root_classes,
            source_context=section_context,
        )
    except ValueError as error:
        if section_context is None:
            raise
        context_gap = {"mode": "unsupported", "fidelity_verified": False,
                       "limitations": [*section_context.notes, str(error)]}
        section_context = None
        matched = rules_for_subtree(
            stylesheets, subtree_html=subtree, source_root_classes=root_classes,
        )
    harvest = build_reference_harvest(
        subtree_html=section_context.wrap(subtree) if section_context is not None else subtree,
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
    if not _shows_anything(sanitized.html):
        # A `<script>`/`<style>`/iframe embed sanitizes down to an empty wrapper. The F2
        # acceptance walk offered four of those to the agent as approved, reusable clones — each
        # one a row in a human's picker, ~28 KB of CSS at rest, and nothing at all on the page.
        # A fragment that renders nothing is not a faithful copy of a section; it is the absence
        # of one, and saying so is cheaper than storing it.
        diagnostics.append(
            _diag(
                MINT_FAILED_CODE,
                f"section {record.index} ({record.role}) of {segmentation.page_url} was not "
                "minted: after sanitizing, its markup shows nothing — no text and no image, "
                "video, canvas or svg (it was a script, style or embed shell)",
                section_index=record.index,
                role=record.role,
                reason="empty_after_sanitize",
            )
        )
        return None
    detected = detect_slots(sanitized.html)

    # Charged HERE, after the two refusal doors above (F3.4). The budget is about bytes AT REST —
    # what this page's clones carry — so a section that matched a megabyte of rules and was then
    # refused for showing nothing must not spend the page's budget on a fragment that does not
    # exist. Everything past this point either writes a row or raises into the driver's error
    # path, which is the one remaining over-count and is the rare case.
    _charge_css(matched.css, segmentation, record, weight, diagnostics)

    preview, extent, preview_refused_by = _preview(
        segmentation, record, screenshot, diagnostics, weight
    )
    assessment = _dead_height(
        segmentation, record, preview, extent, diagnostics, preview_refused_by
    )
    dead = assessment.finding
    # Born dormant, never minted ``draft`` and then demoted: the window between the two is
    # exactly long enough for a kit approval to release a section the site does not show.
    status = FRAGMENT_STATUS_DORMANT if record.hidden_on_source else None
    # A dormant section's harvested CSS carries the very rules that hide it (that is WHY it is
    # dormant), so the artifact appends counter-rules for the ones that hide its ROOT — the
    # isolation preview and any page an activated clone lands on read the same sheet, so they
    # agree by construction (walk finding F-3, final-review X3; shell-side un-hiding alone would
    # preview something the page never shows, which is P-7's forbidden shape one level up).
    css_for_artifact = matched.css
    html_for_artifact = sanitized.html
    unhidden_selectors: tuple[str, ...] = ()
    unhidden_inline: tuple[str, ...] = ()
    if record.hidden_on_source:
        css_for_artifact, unhidden_selectors = unhide_root_rules(
            matched.css,
            tag=record.tag,
            element_id=record.element_id,
            classes=record.class_names,
        )
        # The commonest dormancy cause is the root's OWN inline hiding (wave round 2, C1) —
        # `style="display:none"` beats any sheet when important, and the `hidden` attribute is
        # a UA rule no same-selector counter targets certainly. Both are stripped from the
        # stored root, named in provenance.
        html_for_artifact, unhidden_inline = unhide_root_markup(sanitized.html)
    if record.hidden_on_source:
        diagnostics.append(
            _diag(
                MINT_DORMANT_CODE,
                f"section {record.index} ({record.role}) of {segmentation.page_url} is hidden on "
                "the source site, so it was cloned and minted DORMANT: it is off any generated "
                "page, out of default agent discovery, and waiting for a human to activate it",
                severity="info",
                section_index=record.index,
                role=record.role,
                evidence=list(record.hidden_evidence),
            )
        )

    if section_context is not None:
        html_for_artifact = section_context.wrap(html_for_artifact)
        detected = section_context.wrap_slots(detected)

    provenance = _provenance(
        segmentation,
        record,
        matched,
        detected,
        harvest,
        extent,
        dead,
        assessment,
        preview_refused_by=preview_refused_by,
    )
    provenance["css"]["root_units"] = root_units.provenance()
    provenance["css"]["source_document_context"] = (
        section_context.provenance() if section_context is not None else context_gap
    )
    if recovery_parent is not None:
        provenance["recovery"] = {
            "mode": "authored-descendant-after-refusal",
            "parent_section_index": recovery_parent.index,
            "parent_dom_path": list(recovery_parent.dom_path),
            "wrapper_layout_preserved": False,
            "fidelity_verified": False,
        }
    if record.hidden_on_source:
        provenance["hidden_on_source"]["unhidden_selectors"] = list(unhidden_selectors)
        provenance["hidden_on_source"]["unhidden_inline"] = list(unhidden_inline)
    row, artifact = create_fragment(
        html=html_for_artifact,
        css=svg_fallback_css + css_for_artifact,
        rehosted=rehosted,
        slots=list(detected.specs),
        source_url=segmentation.page_url,
        section_role=record.role,
        label=_label(record),
        source_kit_id=source_kit_id,
        source_kit_version=source_kit_version,
        preview=preview,
        preview_media_type=_PREVIEW_MEDIA_TYPE,
        provenance=provenance,
        prelude_reference=PRELUDE_REFERENCE_STRIP,
        status=status,
        degraded=dead is not None,
        degraded_reason=dead.reason if dead is not None else None,
    )
    _note_metadata_divergence(row, record, segmentation, diagnostics)
    # PAST THE POINT OF NO RETURN. The row is committed; everything from here is bookkeeping ON
    # a fragment that exists. A raise escaping into the driver's broad `except` would report
    # `LUMI0530` — "this section was not minted" — and drop the ref, which claims absence where a
    # durable row sits. So the reconciliation's failure is reported as what it is.
    try:
        row = _reconcile_degraded(
            row, assessment, record, segmentation, mark_degraded, diagnostics
        )
    except Exception as error:  # noqa: BLE001 — the fragment is real; only the marker is not
        logger.exception(
            "fragment degraded-marker reconciliation failed for section %s of %s",
            record.index,
            segmentation.page_url,
        )
        diagnostics.append(
            _diag(
                MINT_DEGRADED_RECONCILED_CODE,
                f"section {record.index} ({record.role}) of {segmentation.page_url} WAS minted, "
                "but its degraded marker could not be brought into line with what this capture "
                f"measured: {type(error).__name__}: {error}. The fragment is real and usable; "
                "the row's marker is the stale one",
                section_index=record.index,
                role=record.role,
                fragment_id=row.get("fragment_id"),
                degraded=assessment.finding is not None,
                was_degraded=bool(row.get("degraded")),
                # Carried on the failure emission too (ledger T16-N5): every OTHER `LUMI0536`
                # has a `reason`, and a consumer reading `d["reason"]` should not KeyError on
                # whichever of the two emitters it happens to meet. `None` here is the honest
                # value — there is no reason code when the measurement found nothing wrong.
                reason=assessment.finding.reason if assessment.finding is not None else None,
                applied=False,
                error=f"{type(error).__name__}: {error}",
            )
        )

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
        degraded=bool(row.get("degraded")),
        degraded_reason=row.get("degraded_reason"),
        hidden_on_source=record.hidden_on_source,
    )


def _dead_height(
    segmentation: SectionSegmentation,
    record: SectionRecord,
    preview: bytes | None,
    extent: CropExtent | None,
    diagnostics: list[dict[str, Any]],
    preview_refused_by: str | None = None,
) -> DeadHeightAssessment:
    """Is this section mostly artificial scroll height? (F3.0, D-F6's trigger.)

    Runs on the crop that was ALREADY made for the preview, so noticing costs one image decode
    and no second opinion about where the section is: the picture judged is the picture a human
    will see in the picker. A finding is reported loudly — it is the repair ladder's entry
    condition, and a broken clone that nobody was told about is the exact failure D-F6 names.

    Returns the whole ASSESSMENT rather than the finding, because the caller needs to know the
    difference between "looked, and it is fine" and "could not look" — see
    :func:`_reconcile_degraded`.
    """
    assessment = assess_dead_height(
        preview,
        section_height_px=record.geometry.height_px if record.geometry is not None else None,
        basis=extent.basis if extent is not None else None,
        viewport_width=segmentation.viewport_width,
    )
    if not assessment.judged:
        # RULING R20-3, widened by final-review X2: a check that did not run is SAID — on EVERY
        # branch, not only the byte-budget one (which the founder's 5GiB ruling made
        # unreachable while the reachable branches — no screenshot, an inferred crop, a
        # compound-band part with no geometry — skipped in silence; the live walk minted five
        # such sections and nothing said so). This section is about to be written
        # `degraded=False`, and without this line that is indistinguishable from a band somebody
        # looked at and found sound. A dead-height finding is the repair ladder's entry
        # condition, so a silent clean bill here is a broken clone nobody is ever told about.
        if preview_refused_by is not None:
            why = (
                "the check reads the preview crop, and the "
                f"{preview_refused_by} budget refused to store one "
                f"({assessment.abstained_because})"
            )
        else:
            why = (
                "the check reads the preview crop, and this section has none it can trust "
                f"({assessment.abstained_because})"
            )
        extra = {"budget": preview_refused_by} if preview_refused_by is not None else {}
        diagnostics.append(
            _diag(
                MINT_CHECK_NOT_RUN_CODE,
                f"section {record.index} ({record.role}) of {segmentation.page_url} was minted "
                f"WITHOUT its dead-height check: {why}. This section is not marked degraded "
                "because nobody looked at it, which is not the same as looking and finding it "
                "sound — photograph it with an isolation render if the band looks tall on the "
                "page",
                section_index=record.index,
                role=record.role,
                check="dead_height",
                because=assessment.abstained_because,
                **extra,
            )
        )

    finding = assessment.finding
    if finding is None:
        return assessment
    logger.warning(
        "fragment_mint_dead_height page=%s section=%s role=%s height=%s content_fraction=%.3f",
        segmentation.page_url,
        record.index,
        record.role,
        finding.section_height_px,
        finding.content_fraction,
    )
    diagnostics.append(
        _diag(
            MINT_DEGRADED_CODE,
            f"section {record.index} ({record.role}) of {segmentation.page_url} was minted "
            f"DEGRADED: its captured band is {finding.section_height_px:g}px tall and only "
            f"{finding.content_fraction:.0%} of that shows anything at all, which is dead scroll "
            "height (a scroll-driven section whose script this clone does not carry). The "
            "harvested original is kept as evidence; the repair ladder replaces it",
            section_index=record.index,
            role=record.role,
            **finding.as_provenance(),
        )
    )
    return assessment


def _reconcile_degraded(
    row: Mapping[str, Any],
    assessment: DeadHeightAssessment,
    record: SectionRecord,
    segmentation: SectionSegmentation,
    mark_degraded: Callable[..., dict[str, Any]] | None,
    diagnostics: list[dict[str, Any]],
) -> Mapping[str, Any]:
    """Make an already-existing row agree with what THIS pass saw (F3.0, ruling R-I1).

    ``insert_web_fragment`` is ``ON CONFLICT DO NOTHING``, so a re-mint that converges keeps the
    FIRST writer's birth facts — which is right for the label and the provenance and quietly
    wrong for this one. The failure it caused: a page ingested at static tier has no screenshot,
    so the scroll-jacked band is born clean (correctly — nothing looked at it). The site is
    re-ingested with a dynamic capture, the band is measured, dead height is detected, the job
    says the section "was minted DEGRADED" — and because the markup is byte-identical the mint
    converges onto the existing row, which still says ``degraded = false``. The ladder reads the
    column, so it never sees it, and the two surfaces disagree with nobody saying so.

    The marker is a JUDGEMENT, and the trigger already admits it, so the newer look wins — **in
    both directions, but only on MEASURED evidence** (the ruling's condition, and the reason
    :class:`DeadHeightAssessment` distinguishes "judged" from "abstained"). A pass that could not
    look — no screenshot, an inferred crop, a crop the screenshot cut short — never CLEARS an
    existing marker: honest absence is not a clean bill of health, and treating it as one would
    silently retire a repair the ladder had been told to make.

    **And it only ever reconciles its OWN reason.** ``degraded`` is one column with several
    future authors — F3.3's behavioural gate will mark a clone broken for a blank mobile
    viewport or a dead control, reasons this detector knows nothing about and cannot re-measure.
    Clearing on "the band is full of content" would then quietly overrule a verdict that was
    never about the band. So a marker whose reason is not ``dead_height`` is left exactly as it
    is, whatever this pass saw.
    """
    existing = bool(row.get("degraded"))
    wanted = assessment.finding is not None
    if existing == wanted:
        return row
    if not wanted and not assessment.judged:
        return row  # no evidence this pass — the marker stands
    if existing and str(row.get("degraded_reason") or "") != DEAD_HEIGHT_REASON:
        return row  # somebody else's verdict, about something this detector cannot measure

    fragment_id = str(row.get("fragment_id") or "")
    reason = assessment.finding.reason if assessment.finding is not None else None
    applied = False
    if mark_degraded is not None and fragment_id:
        row = mark_degraded(fragment_id, degraded=wanted, reason=reason)
        applied = True
    diagnostics.append(
        _diag(
            MINT_DEGRADED_RECONCILED_CODE,
            f"section {record.index} ({record.role}) of {segmentation.page_url} is byte-identical "
            f"to a fragment already held, whose degraded marker said {existing!r} while this "
            f"capture measured {wanted!r}"
            + (
                f"; the row was updated to {wanted!r}"
                if applied
                else "; NOTHING was updated — this mint path was given no marker writer, so the "
                "row and this job now disagree"
            ),
            severity="warning" if wanted or not applied else "info",
            section_index=record.index,
            role=record.role,
            fragment_id=fragment_id,
            degraded=wanted,
            was_degraded=existing,
            reason=reason,
            applied=applied,
        )
    )
    return row


#: What counts as something a visitor can SEE, when the section has no words.
_MEDIA_TAGS = ("img", "svg", "video", "canvas", "picture", "iframe", "object")


def _shows_anything(html: str) -> bool:
    """Does this sanitized markup put anything on the page — words or a picture?

    Text first, because most sections are copy; media second, because a logo wall or a bare
    hero image is a real section with no prose in it at all. Anything that satisfies neither is
    an empty wrapper whatever its class list says.
    """
    tree = LexborHTMLParser(html or "")
    body = tree.body
    if body is None:
        return False
    if (body.text(deep=True) or "").strip():
        return True
    return any(body.css_first(tag) is not None for tag in _MEDIA_TAGS)


def _charge_css(
    css: str,
    segmentation: SectionSegmentation,
    record: SectionRecord,
    weight: PageWeight,
    diagnostics: list[dict[str, Any]],
) -> None:
    """Count this fragment's scoped CSS against both budgets, and SAY so when it is over (F3.4).

    Warned about, never truncated. The scoped stylesheet is what makes a cloned section look like
    itself, so dropping rules out of it would produce a fragment that renders subtly wrong and
    reports nothing — a silent cap, which is exactly what the register forbids. Saying "this
    clone carries 1.3 MB of CSS" with the number is the honest answer; what to do about a site
    that heavy is a judgement, and it belongs to a human.
    """
    size = len(css.encode("utf-8"))
    if not weight.fragment_css_fits(size):
        diagnostics.append(
            budget_diagnostic(
                budget="fragment scoped CSS bytes",
                limit=weight.fragment_css_limit,
                measured=size,
                outcome=OUTCOME_WARNED,
                message=(
                    f"section {record.index} ({record.role}) of {segmentation.page_url} carries "
                    f"{size} bytes of scoped CSS, over the {weight.fragment_css_limit}-byte "
                    "per-fragment budget; it was minted in full — a truncated stylesheet would "
                    "render this section wrong and say nothing"
                ),
                section_index=record.index,
                role=record.role,
            )
        )
    if weight.add_css(size):
        diagnostics.append(
            budget_diagnostic(
                budget="page scoped CSS bytes",
                # The limit the WEIGHT enforced (F3.4 fix round, F-4). Since the founder
                # ruling there is no other kind — every limit lives on the weight, and the
                # module constants are only its defaults.
                limit=weight.page_css_limit,
                measured=weight.css_bytes,
                outcome=OUTCOME_WARNED,
                message=(
                    f"the clones of {segmentation.page_url} now carry {weight.css_bytes} bytes of "
                    f"scoped CSS between {weight.fragment_count} fragment(s), over the "
                    f"{weight.page_css_limit}-byte per-page budget; every section is still minted "
                    "in full, and this page is an expensive one to clone"
                ),
                page_url=segmentation.page_url,
                fragments=weight.fragment_count,
            )
        )


def _fit_preview(
    preview: bytes,
    segmentation: SectionSegmentation,
    record: SectionRecord,
    weight: PageWeight,
    diagnostics: list[dict[str, Any]],
) -> tuple[bytes | None, str | None]:
    """Bring one preview inside the byte budgets, or give it up loudly (F3.4).

    A preview is a THUMBNAIL, so the first answer to "too many bytes" is fewer pixels: it is
    re-encoded at successively narrower widths until it fits. Only when it will not fit even at
    :data:`MIN_PREVIEW_WIDTH` is it dropped — and since F3.2 that is recoverable, because an
    isolation render photographs any fragment from its own bytes on demand.

    The page total is checked last and separately, because it is a different fact: a preview that
    fits perfectly well can still be the one that puts this page over its budget, and refusing it
    is not a statement about the picture.

    Returns ``(bytes-or-None, the budget that refused it)``. The second half exists because a
    refusal here does not only cost a thumbnail — it switches off the dead-height check, which
    reads the crop (ruling R20-3), and the caller has to be able to say so.
    """
    from PIL import Image, UnidentifiedImageError

    original = len(preview)
    width: int | None = None
    if original > weight.preview_limit:
        try:
            image = Image.open(io.BytesIO(preview))
            image.load()
        except (UnidentifiedImageError, OSError, ValueError):
            image = None
        while image is not None and len(preview) > weight.preview_limit:
            # Halve, floored at the minimum and never above what the crop already is: a preview
            # narrower than the floor is not worth keeping, and one "re-encoded" wider would be
            # this function inventing pixels to save bytes.
            width = min(image.width, max(MIN_PREVIEW_WIDTH, (width or image.width) // 2))
            height = max(1, round(image.height * width / image.width))
            buffer = io.BytesIO()
            image.resize((width, height), Image.LANCZOS).save(
                buffer, format="PNG", optimize=True
            )
            preview = buffer.getvalue()
            if width <= MIN_PREVIEW_WIDTH:
                break
        if len(preview) > weight.preview_limit:
            diagnostics.append(
                budget_diagnostic(
                    budget="preview bytes",
                    limit=weight.preview_limit,
                    measured=original,
                    outcome=OUTCOME_REFUSED,
                    message=(
                        f"section {record.index} ({record.role}) of {segmentation.page_url} was "
                        f"minted WITHOUT a preview: its crop was {original} bytes and does not "
                        f"fit the {weight.preview_limit}-byte budget"
                        + (
                            f", even re-encoded at {MIN_PREVIEW_WIDTH}px wide"
                            if width is not None
                            # The crop came out of PIL moments ago, so this is close to
                            # unreachable — and a message claiming a re-encode that never
                            # happened would be exactly the kind of confident wrongness the
                            # rest of this module is written against.
                            else "; it could not be re-encoded, because it did not decode as an "
                            "image"
                        )
                        + ". An isolation render can photograph it on demand"
                    ),
                    section_index=record.index,
                    role=record.role,
                    encoded_width=width,
                )
            )
            return None, "preview bytes"
        diagnostics.append(
            budget_diagnostic(
                budget="preview bytes",
                limit=weight.preview_limit,
                measured=original,
                outcome=OUTCOME_DEGRADED,
                severity="info",
                message=(
                    f"section {record.index} ({record.role}) of {segmentation.page_url} had a "
                    f"{original}-byte preview crop, over the {weight.preview_limit}-byte budget; it "
                    f"was re-encoded {width}px wide at {len(preview)} bytes. A preview is a "
                    "thumbnail, so this costs pixels rather than the picture"
                ),
                section_index=record.index,
                role=record.role,
                encoded_width=width,
                stored=len(preview),
            )
        )
    if not weight.preview_fits(len(preview)):
        diagnostics.append(
            budget_diagnostic(
                budget="page preview bytes",
                # The enforced limit, for the same reason (F-4).
                limit=weight.page_preview_limit,
                measured=weight.preview_bytes + len(preview),
                outcome=OUTCOME_REFUSED,
                message=(
                    f"section {record.index} ({record.role}) of {segmentation.page_url} was "
                    f"minted WITHOUT a preview: {segmentation.page_url} already holds "
                    f"{weight.preview_bytes} bytes of preview images and this one would take it "
                    f"past the {weight.page_preview_limit}-byte per-page budget. The section itself "
                    "is minted in full"
                ),
                section_index=record.index,
                role=record.role,
                page_url=segmentation.page_url,
            )
        )
        return None, "page preview bytes"
    weight.add_preview(len(preview))
    return preview, None


def _preview(
    segmentation: SectionSegmentation,
    record: SectionRecord,
    screenshot: bytes | None,
    diagnostics: list[dict[str, Any]],
    weight: PageWeight | None = None,
) -> tuple[bytes | None, CropExtent | None, str | None]:
    """``(the picture, its extent, the budget that refused it)``.

    The third value is ``None`` in every ordinary case. It is set only when a crop EXISTED and a
    byte budget would not store it, which is the one shape where "no preview" is not a statement
    about the capture — and which switches off a quality check downstream (ruling R20-3).
    """
    extent = crop_extent(segmentation, record)
    preview = (
        crop_preview(screenshot, extent, viewport_width=segmentation.viewport_width)
        if (screenshot and extent is not None)
        else None
    )
    if preview is not None:
        preview, refused_by = _fit_preview(
            preview,
            segmentation,
            record,
            weight if weight is not None else PageWeight(),
            diagnostics,
        )
        # A preview refused by a BUDGET has already said so, with the number and the budget. The
        # generic no-preview line below is about the capture, and repeating it here would report
        # a missing screenshot the capture actually took.
        return preview, extent, refused_by
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
    return preview, extent, None


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
    dead: DeadHeight | None = None,
    assessment: DeadHeightAssessment | None = None,
    preview_refused_by: str | None = None,
) -> dict[str, Any]:
    """Everything needed to answer "where did this fragment come from, and how sure were we?".

    Bounded on purpose: the evidence list is Task 11's own (a handful of entries), the notes are
    capped by their producers, and no markup, CSS or byte string goes in here. This is a row.

    The two F3.0 entries are the *why* behind the two columns beside them. ``degraded_reason`` on
    the row is a code; ``degraded`` here is the measurement that produced it, so a repair can be
    argued with rather than merely obeyed. ``hidden_on_source`` is the "hidden on source site"
    provenance D-F8 asks for, in the words the segmenter used when it decided.
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
            "root_variable_rules": matched.root_variable_rules,
        },
        "slots": list(detected.keys),
        "slot_notes": list(detected.notes),
        "reference_conflicts": list(harvest.conflicts),
        "degraded": dead.as_provenance() if dead is not None else None,
        # Present ONLY when the dead-height check did not run (F3.4 fix round, ruling R20-3), so
        # a row with no marker can be told apart from a row that was looked at. `degraded: null`
        # beside `dead_height_check: {"assessed": false, …}` is "nobody looked"; `degraded: null`
        # alone is "looked, and it is fine".
        # `refused_by` discriminates the two shapes that share `because: no_preview` (wave
        # round 2, M2): a byte budget refused to store the crop vs the capture never had a
        # screenshot to crop. Present only when a budget was the reason.
        "dead_height_check": (
            {
                "assessed": False,
                "because": assessment.abstained_because,
                **(
                    {"refused_by": preview_refused_by}
                    if preview_refused_by is not None
                    else {}
                ),
            }
            if assessment is not None and not assessment.judged
            else None
        ),
        "hidden_on_source": (
            {"hidden": True, "evidence": list(record.hidden_evidence)}
            if record.hidden_on_source
            else None
        ),
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


def make_degraded_marker(*, workspace_id: str) -> Callable[..., dict[str, Any]]:
    """The real F3.0 degraded-marker seam, bound to one workspace.

    Separate from the creation seam because it is used at a different moment and only sometimes:
    creation states a NEW row's birth facts, this reconciles an EXISTING row with a later look
    (see :func:`_reconcile_degraded`). Injected like the other two so the driver stays a pure
    function of its inputs plus its calls.
    """
    from lumen_api.fragments import set_web_fragment_degraded

    def _mark(fragment_id: str, *, degraded: bool, reason: str | None) -> dict[str, Any]:
        return set_web_fragment_degraded(
            workspace_id=workspace_id,
            fragment_id=fragment_id,
            degraded=degraded,
            reason=reason,
        )

    return _mark


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
    "MINT_BUDGET_CODE",
    "MINT_CHECK_NOT_RUN_CODE",
    "MINT_CAPPED_CODE",
    "MINT_DEGRADED_CODE",
    "MINT_DEGRADED_RECONCILED_CODE",
    "MINT_DORMANT_CODE",
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
    "make_degraded_marker",
    "make_fragment_writer",
    "mint_sections",
]
