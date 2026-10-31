"""Harvest: bounded pagination → filter → dedupe → byte custody (spec §4.1, §5 W2).

Three separable pieces, and they are separate on purpose:

* :func:`fetch_pages` is the only one that spends credits, and its bound is a parameter.
* :func:`select_creatives` is PURE — pages in, a kept list and a reasoned drop list out. Every
  filtering rule in the spec is decided here and nowhere else, so the rules can be proven
  against real vendor payloads without a transport, a database or a byte store.
* :func:`custody_creatives` gives the kept creatives durable bytes.

**Why bytes are downloaded at harvest time.** The library's creative URLs are signed CDN
links that expire (spec §2, "URLs expire → bytes custodied at fetch"). A row that stored only
the URL would be a row that stops resolving, so custody happens in the same step that
discovered the creative — before distillation, before pre-generation, before anything that
could fail and postpone it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .provider import AdLibraryAd, AdLibraryError, AdLibraryPage, AdLibraryProvider

__all__ = [
    "DEFAULT_MAX_CREATIVES",
    "DEFAULT_MAX_PAGES",
    "CreativeSelection",
    "HarvestedCreative",
    "ads_considered",
    "creative_id_for",
    "custody_creatives",
    "download_creative_bytes",
    "fetch_pages",
    "normalize_name",
    "select_creatives",
]

JsonObject = dict[str, Any]

#: Pages per harvest. One page is ~24–25 ads and ~1 credit (spec §5 W2), so eight pages is
#: ~200 ads for ~8 credits — room for the 50 creatives the lane keeps after filtering, and a
#: bound the caller can lower but never accidentally lose. Matches automatic onboarding's
#: ``CLUE_BRAND_AD_ASSETS_AUTO_MAX_PAGES``.
DEFAULT_MAX_PAGES = 8

#: Kept creatives per harvest (founder 2026-10-30: 50, matching automatic onboarding's
#: ``CLUE_BRAND_AD_ASSETS_AUTO_MAX_CREATIVES``). The cap is applied AFTER filtering and
#: de-duplication so it counts usable creatives, not raw ads.
DEFAULT_MAX_CREATIVES = 50

#: The media class the lane wants. Video, carousel and document creatives are out of scope
#: for v1 (spec §7) — a video's "image" is only its cover frame, and a carousel is several
#: creatives pretending to be one.
STATIC_AD_KIND = "image"

#: Byte ceiling for one downloaded creative. A LinkedIn creative is a web-sized raster; an
#: order of magnitude above the largest plausible one is a guard against a redirect to
#: something enormous, not a quality judgement.
MAX_CREATIVE_BYTES = 12 * 1024 * 1024


@dataclass(frozen=True)
class HarvestedCreative:
    """One kept creative: the ad it came from, its bytes, and where they landed."""

    creative_id: str
    ad: AdLibraryAd
    image_url: str
    image_bytes: bytes
    mime_type: str
    asset_id: str | None = None

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.image_bytes).hexdigest()


@dataclass(frozen=True)
class CreativeSelection:
    """What survived the filter, and — just as importantly — what did not and why.

    The drop list is durable evidence, not debug output: "we harvested 75 ads and kept 12" is
    only meaningful next to the reasons the other 63 went. It is bounded by the input.
    """

    kept: tuple[AdLibraryAd, ...] = ()
    dropped: tuple[tuple[str, str], ...] = ()
    advertiser_name: str | None = None
    considered: int = 0

    def drop_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _ad_id, reason in self.dropped:
            counts[reason] = counts.get(reason, 0) + 1
        return counts


# --------------------------------------------------------------------------------------
# 1. Bounded pagination
# --------------------------------------------------------------------------------------


def fetch_pages(
    provider: AdLibraryProvider,
    *,
    company_domain: str | None = None,
    page_id: str | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    date_filter: str | None = None,
) -> list[AdLibraryPage]:
    """Walk at most ``max_pages`` pages of one advertiser's library.

    Three independent stop conditions, and all three are needed:

    * the page cap — the spend bound, and the only one that cannot be talked out of stopping;
    * ``is_last_page`` — the vendor saying there is no more;
    * an EMPTY page — the vendor still handing back a continuation token past the end of the
      useful results. The frozen Ramp fetch does exactly this (page 2 answered
      ``total_ads: 0`` with a fresh token and ``is_last_page: false``), so a loop that trusted
      only the token would pay a credit per empty page until the cap caught it.

    A missing token also stops the walk: there is no cursor to ask with.
    """
    if max_pages < 1:
        raise AdLibraryError(
            "ad_library.bad_request", f"max_pages must be at least 1, got {max_pages}"
        )
    pages: list[AdLibraryPage] = []
    token: str | None = None
    for _index in range(max_pages):
        page = provider.fetch_page(
            company_domain=company_domain,
            page_id=page_id,
            continuation_token=token,
            date_filter=date_filter,
        )
        pages.append(page)
        if page.is_last_page or not page.ads or not page.continuation_token:
            break
        token = page.continuation_token
    return pages


# --------------------------------------------------------------------------------------
# 2. Filter + dedupe (pure)
# --------------------------------------------------------------------------------------


def ads_considered(pages: Sequence[AdLibraryPage]) -> int:
    """How many raw ads a fetch put in front of the filter — before any rule ran.

    One line, and it has a name because W-B3 gave it a SECOND caller. It is the number
    :attr:`CreativeSelection.considered` reports, and it is also the number the onboarding
    lane's domain-retry decides on ("the resolved page held nothing at all", as opposed to
    "the page held ads and the filter dropped them all"). Those two questions must never be
    answered by two subtly different counts, so they are answered by this one.
    """
    return sum(len(page.ads) for page in pages)


def select_creatives(
    pages: Sequence[AdLibraryPage],
    *,
    advertiser_name: str | None = None,
    max_creatives: int = DEFAULT_MAX_CREATIVES,
) -> CreativeSelection:
    """Keep this brand's own static company creatives, deduped by image URL.

    The rules, in the order they are applied:

    1. **``type == "image"``** — drops video and document ads outright.
    2. **no carousel block** — a carousel ad can arrive typed as an image; it is still
       several creatives in a trench coat and v1 does not take it (spec §7).
    3. **a usable ``image.url``** — nothing to custody otherwise.
    4. **``advertiser.promoted``** — an organic post that happens to be in the response is
       not an ad.
    5. **the advertiser is the COMPANY** — this is the thought-leader rule, and it is the one
       that needed real data to get right. ``advertiser.promoted`` is ``true`` for personal
       thought-leader promotions too (all four in the frozen Ramp fetch are), so it separates
       nothing; the advertiser NAME is the only field that does. When the caller does not
       supply the company's name, it is inferred as the most common advertiser name across
       the fetched ads — a company page's own creatives dominate its library by construction,
       and the individuals are a long tail of one each.
    6. **dedupe by creative image URL** — first occurrence wins. Real libraries re-run the
       same creative under different ad ids (the frozen Ramp fetch has such a pair), and the
       lane wants distinct *creatives*, not distinct campaigns.

    The cap is applied last, so it counts usable creatives.
    """
    ads = [ad for page in pages for ad in page.ads]
    resolved_name = advertiser_name or dominant_advertiser_name(ads)
    normalized = _normalize_name(resolved_name)

    kept: list[AdLibraryAd] = []
    dropped: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    for ad in ads:
        reason = _drop_reason(ad, normalized)
        if reason is not None:
            dropped.append((ad.ad_id, reason))
            continue
        assert ad.image_url is not None  # narrowed by _drop_reason
        if ad.image_url in seen_urls:
            dropped.append((ad.ad_id, "duplicate_creative"))
            continue
        if len(kept) >= max_creatives:
            dropped.append((ad.ad_id, "over_cap"))
            continue
        seen_urls.add(ad.image_url)
        kept.append(ad)

    return CreativeSelection(
        kept=tuple(kept),
        dropped=tuple(dropped),
        advertiser_name=resolved_name,
        considered=ads_considered(pages),
    )


def dominant_advertiser_name(ads: Iterable[AdLibraryAd]) -> str | None:
    """The most frequently occurring advertiser name, or ``None`` when there are no ads.

    Ties are broken by first appearance, so the answer is deterministic for a given page
    order rather than dependent on dictionary iteration luck.
    """
    counts: dict[str, int] = {}
    order: list[str] = []
    for ad in ads:
        name = ad.advertiser_name
        if not name:
            continue
        if name not in counts:
            order.append(name)
        counts[name] = counts.get(name, 0) + 1
    if not order:
        return None
    return max(order, key=lambda name: (counts[name], -order.index(name)))


def _drop_reason(ad: AdLibraryAd, company_name: str | None) -> str | None:
    if not ad.ad_id:
        return "no_ad_id"
    if ad.kind != STATIC_AD_KIND:
        return f"not_static:{ad.kind or 'unknown'}"
    if ad.has_carousel:
        return "carousel"
    if not ad.image_url:
        return "no_creative_url"
    if not ad.advertiser_promoted:
        return "not_promoted"
    if company_name is not None and _normalize_name(ad.advertiser_name) != company_name:
        return "thought_leader"
    return None


def normalize_name(name: str | None) -> str | None:
    """The subsystem's base company-name fold: whitespace collapsed, casefolded.

    Public since W5/R3-A because it now has a SECOND consumer. The advertiser cross-check
    (:func:`~.company_identity.company_name_key`) needs a stronger fold — punctuation and
    legal-form suffixes go too — and builds it on top of this one rather than beside it, so the
    filter below and the custody gate can never drift into disagreeing about what a name is.

    Deliberately left exactly as strict as it was. The thought-leader rule compares a person's
    name against a company's, where a fold that tried harder would start matching "Ramp" to a
    "Ramp" employee, and the extra folding therefore lives in the caller that wants it.
    """
    if name is None:
        return None
    return " ".join(name.split()).casefold() or None


#: The pre-R3-A spelling, kept so nothing in this module had to change to gain a public name.
_normalize_name = normalize_name


# --------------------------------------------------------------------------------------
# 3. Bytes + custody
# --------------------------------------------------------------------------------------


def creative_id_for(image_url: str) -> str:
    """The creative's durable identity: content-addressed on the URL that de-duped it.

    Deriving it from the URL rather than the ad id is what makes a re-run of the same harvest
    converge on the same rows instead of accumulating a second copy of every creative — and
    it keeps the row's identity aligned with the thing the dedupe rule actually compared.
    """
    return f"adcre_{hashlib.sha256(image_url.encode('utf-8')).hexdigest()[:24]}"


def asset_id_for(image_bytes: bytes) -> str:
    """Content-derived asset id, matching the ingestion lane's ``asset_ing_<sha[:16]>`` shape."""
    return f"asset_ad_{hashlib.sha256(image_bytes).hexdigest()[:16]}"


def download_creative_bytes(url: str, *, timeout_s: float = 30.0) -> tuple[bytes, str]:
    """Fetch one creative's bytes. ``httpx`` is imported here, never at module load."""
    import httpx  # lazy: only the real network path needs it

    try:
        response = httpx.get(url, timeout=timeout_s, follow_redirects=True)
    except Exception as error:  # noqa: BLE001
        raise AdLibraryError(
            "ad_library.creative_fetch_failed", f"{type(error).__name__}: {error}"
        ) from error
    if response.status_code >= 400:
        raise AdLibraryError(
            "ad_library.creative_fetch_failed",
            f"HTTP {response.status_code} fetching a creative",
        )
    data = response.content
    if len(data) > MAX_CREATIVE_BYTES:
        raise AdLibraryError(
            "ad_library.creative_too_large",
            f"creative of {len(data)} bytes exceeds the {MAX_CREATIVE_BYTES}-byte limit",
        )
    mime = (response.headers.get("content-type") or "image/png").split(";", 1)[0].strip()
    return data, mime or "image/png"


@dataclass
class CustodyOutcome:
    """What custody produced: the creatives that landed, and the ones that could not."""

    creatives: list[HarvestedCreative] = field(default_factory=list)
    asset_records: list[JsonObject] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)


def custody_creatives(
    selection: CreativeSelection,
    *,
    core: Any,
    cache_dir: str,
    fetched_at: str,
    provider_name: str,
    advertiser_page_id: str | None,
    fetch: Callable[[str], tuple[bytes, str]] | None = None,
    max_bytes: int | None = None,
) -> CustodyOutcome:
    """Download every kept creative and give it a design asset record.

    ``core`` is the ingestion lane's recording core proxy, so each ``ingest_asset`` call
    already writes the bytes back into durable platform storage and re-points the record's
    location — this function does not need to know how custody works, only to route through
    the one seam that does.

    ``fetched_at`` is PASSED IN rather than read from the clock here. Provenance that a caller
    supplies is provenance a caller can freeze, which is what makes a harvest reproducible in
    a test and consistent across the rows of one job; a clock read per creative would stamp a
    dozen slightly different times on one gesture.

    One creative failing (an expired URL, a 404, a byte ceiling) is recorded and skipped, not
    raised: the harvest's value is the creatives it DID get, and losing eleven because the
    twelfth link rotted would be the worst possible trade.
    """
    # Resolved at CALL time, never bound as a default argument. A default is captured when the
    # module is imported, so ``fetch=download_creative_bytes`` in the signature would make this
    # function unpatchable from the outside — and the failure mode of that is a test suite
    # quietly making real requests to a real CDN, which is the one thing this seam exists to
    # make impossible.
    fetch = fetch or download_creative_bytes
    outcome = CustodyOutcome()
    for ad in selection.kept:
        image_url = ad.image_url or ""
        creative_id = creative_id_for(image_url)
        try:
            data, mime = fetch(image_url)
        except AdLibraryError as error:
            outcome.failures.append((ad.ad_id, error.code))
            continue
        except Exception as error:  # noqa: BLE001 - an injected fetcher may raise anything
            outcome.failures.append((ad.ad_id, f"creative_fetch_failed:{type(error).__name__}"))
            continue

        asset_id = asset_id_for(data)
        response = core.ingest_asset(
            cache_dir,
            _b64(data),
            asset_id,
            _creative_label(ad),
            declared_mime_type=mime,
            filename=f"{creative_id}{_extension_for(mime)}",
            kind="raster_image",
            provenance=creative_provenance(
                ad,
                provider_name=provider_name,
                advertiser_page_id=advertiser_page_id,
                fetched_at=fetched_at,
                creative_id=creative_id,
            ),
            tags=["ad-reference", f"advertiser:{selection.advertiser_name or 'unknown'}"],
            max_bytes=max_bytes,
            raise_on_error=False,
        )
        record = ((response or {}).get("asset") or {}).get("record") or {}
        if not record.get("id"):
            outcome.failures.append((ad.ad_id, "asset_ingest_failed"))
            continue
        outcome.asset_records.append(record)
        outcome.creatives.append(
            HarvestedCreative(
                creative_id=creative_id,
                ad=ad,
                image_url=image_url,
                image_bytes=data,
                mime_type=mime,
                asset_id=str(record["id"]),
            )
        )
    return outcome


def creative_provenance(
    ad: AdLibraryAd,
    *,
    provider_name: str,
    advertiser_page_id: str | None,
    fetched_at: str,
    creative_id: str,
) -> JsonObject:
    """The provenance stamp every harvested creative carries (spec §4.1).

    Ad id, library detail link, advertiser page id, fetch time and the source provider — the
    five facts that let someone re-find the published ad this reference came from, months
    after its CDN link stopped resolving.
    """
    return {
        "source": "ad_library",
        "provider": provider_name,
        "creative_id": creative_id,
        "ad_id": ad.ad_id,
        "creative_type": ad.creative_type,
        "advertiser_name": ad.advertiser_name,
        "advertiser_page_id": advertiser_page_id,
        "view_details_link": ad.view_details_link,
        "creative_url": ad.image_url,
        "fetched_at": fetched_at,
    }


def _creative_label(ad: AdLibraryAd) -> str:
    for candidate in (ad.headline_title, ad.image_alt_text, ad.commentary_text):
        if candidate:
            return candidate[:120]
    return f"Ad {ad.ad_id}"


def _extension_for(mime: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(mime.lower(), ".img")


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode("ascii")
