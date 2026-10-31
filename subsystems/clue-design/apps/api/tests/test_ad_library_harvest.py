"""Harvest: bounded pagination, the filter, the dedupe, and byte custody (W2).

Every assertion runs against the frozen real-shape Ramp fixtures (see
``test_ad_library_provider`` for exactly how they were made and what the two deliberate edits
are). No network, no database, no engine.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from lumen_ingestion.ad_library.adyntel import AdyntelProvider
from lumen_ingestion.ad_library.harvest import (
    DEFAULT_MAX_CREATIVES,
    creative_id_for,
    custody_creatives,
    fetch_pages,
    select_creatives,
)
from lumen_ingestion.ad_library.provider import AdLibraryError, AdLibraryPage

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ad_library"

#: The one image URL that two different real Ramp ads (1473633543 / 1473650383) both serve.
DUPLICATED_AD_IDS = ("1473633543", "1473650383")


def load_pages() -> list[AdLibraryPage]:
    provider = AdyntelProvider(api_key="k", email="e@example.com")
    return [
        provider.parse_page(json.loads((FIXTURES / f"ramp_page{n}.json").read_text()))
        for n in (1, 2)
    ]


class _RecordingProvider:
    """A provider stub that answers from the fixtures and records what it was asked."""

    name = "stub"

    def __init__(self, pages: list[AdLibraryPage], *, last_on: int | None = None) -> None:
        self._pages = pages
        self._last_on = last_on
        self.calls: list[dict[str, Any]] = []

    def fetch_page(self, **kwargs: Any) -> AdLibraryPage:
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self._pages) - 1)
        page = self._pages[index]
        if self._last_on is not None and len(self.calls) >= self._last_on:
            page = AdLibraryPage(
                page_id=page.page_id,
                total_ads=page.total_ads,
                ads=page.ads,
                continuation_token=page.continuation_token,
                is_last_page=True,
                provider=page.provider,
            )
        return page


# --- pagination bounds -----------------------------------------------------------------------


def test_pagination_never_exceeds_the_page_cap() -> None:
    """RED CASE: the fixtures never say ``is_last_page``, so only the cap can stop the walk."""
    provider = _RecordingProvider(load_pages())
    pages = fetch_pages(provider, company_domain="ramp.com", max_pages=3)

    assert len(pages) == 3
    assert len(provider.calls) == 3
    # The cursor is threaded: first call has no token, later ones carry the previous page's.
    assert provider.calls[0]["continuation_token"] is None
    assert provider.calls[1]["continuation_token"] == pages[0].continuation_token
    assert all(call["company_domain"] == "ramp.com" for call in provider.calls)


def test_pagination_stops_when_the_vendor_says_last_page() -> None:
    provider = _RecordingProvider(load_pages(), last_on=2)
    pages = fetch_pages(provider, company_domain="ramp.com", max_pages=10)
    assert len(pages) == 2


def test_pagination_stops_on_an_empty_page_even_with_a_fresh_token() -> None:
    """The real page 2 answers ``total_ads: 0`` with a token and ``is_last_page: false``.

    Trusting the token alone would spend a credit per empty page until the cap.
    """
    empty = AdLibraryPage(
        page_id="1406226",
        total_ads=0,
        ads=(),
        continuation_token="1452455953-1784241663820",
        is_last_page=False,
        provider="stub",
    )
    provider = _RecordingProvider([load_pages()[0], empty, empty])
    pages = fetch_pages(provider, company_domain="ramp.com", max_pages=5)
    assert len(pages) == 2
    assert len(provider.calls) == 2


def test_a_zero_page_cap_is_refused_rather_than_looping_forever() -> None:
    with pytest.raises(AdLibraryError) as caught:
        fetch_pages(_RecordingProvider(load_pages()), company_domain="ramp.com", max_pages=0)
    assert caught.value.code == "ad_library.bad_request"


# --- the filter ------------------------------------------------------------------------------


def test_only_static_company_creatives_survive_the_filter() -> None:
    selection = select_creatives(load_pages(), advertiser_name="Ramp")

    assert selection.kept, "the frozen fetch has real static company ads"
    for ad in selection.kept:
        assert ad.kind == "image"
        assert ad.advertiser_name == "Ramp"
        assert ad.advertiser_promoted is True
        assert ad.image_url
        assert ad.has_carousel is False


def test_video_and_document_creatives_are_dropped_with_a_reason() -> None:
    selection = select_creatives(load_pages(), advertiser_name="Ramp")
    reasons = selection.drop_counts()
    assert reasons.get("not_static:video"), reasons
    assert reasons.get("not_static:document"), reasons


def test_the_thought_leader_promotion_is_dropped_by_advertiser_name() -> None:
    """RED CASE, and the one that needed real data.

    ``advertiser.promoted`` is ``true`` for personal thought-leader promotions too, so it
    separates nothing. Ad 9000000001 is an IMAGE-typed thought-leader promotion, so the type
    filter cannot be what drops it — only the advertiser-name rule can.
    """
    selection = select_creatives(load_pages(), advertiser_name="Ramp")

    dropped = dict(selection.dropped)
    assert dropped["9000000001"] == "thought_leader"
    assert "9000000001" not in {ad.ad_id for ad in selection.kept}
    # The four real (video-typed) personal promotions are dropped as well — by whichever rule
    # reaches them first, but dropped either way.
    for ad_id in ("1478270053", "1478249973", "1478290033", "1478230043"):
        assert ad_id in dropped


def test_the_company_name_is_inferred_when_the_caller_does_not_supply_one() -> None:
    """A company page's own creatives dominate its library; the individuals are a long tail."""
    selection = select_creatives(load_pages())
    assert selection.advertiser_name == "Ramp"
    assert dict(selection.dropped)["9000000001"] == "thought_leader"


# --- dedupe ----------------------------------------------------------------------------------


def test_the_real_duplicate_creative_pair_is_deduped_to_one() -> None:
    """RED CASE: two different real ad ids serve the identical creative URL."""
    pages = load_pages()
    first, second = DUPLICATED_AD_IDS
    urls = {
        ad.ad_id: ad.image_url for page in pages for ad in page.ads if ad.ad_id in DUPLICATED_AD_IDS
    }
    assert urls[first] == urls[second], "fixture no longer carries the real duplicate pair"

    selection = select_creatives(pages, advertiser_name="Ramp", max_creatives=100)
    kept_ids = [ad.ad_id for ad in selection.kept]
    assert first in kept_ids, "first occurrence wins"
    assert second not in kept_ids
    assert dict(selection.dropped)[second] == "duplicate_creative"

    kept_urls = [ad.image_url for ad in selection.kept]
    assert len(kept_urls) == len(set(kept_urls))


def test_the_kept_count_is_bounded_and_the_overflow_is_recorded() -> None:
    selection = select_creatives(load_pages(), advertiser_name="Ramp", max_creatives=5)
    assert len(selection.kept) == 5
    assert selection.drop_counts().get("over_cap")

    default = select_creatives(load_pages(), advertiser_name="Ramp")
    assert len(default.kept) <= DEFAULT_MAX_CREATIVES


# --- custody ---------------------------------------------------------------------------------


class _FakeCore:
    """Stands in for the ingestion lane's recording core: records what it was asked to ingest."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def ingest_asset(self, store_root: str, bytes_base64: str, asset_id: str, label: str, **kw: Any):
        self.calls.append({"asset_id": asset_id, "label": label, "store_root": store_root, **kw})
        data = base64.b64decode(bytes_base64)
        return {
            "asset": {
                "record": {
                    "id": asset_id,
                    "label": label,
                    "kind": kw.get("kind"),
                    "media": {
                        "mime_type": kw.get("declared_mime_type"),
                        "byte_length": len(data),
                        "digest": {
                            "algorithm": "sha256",
                            "value": hashlib.sha256(data).hexdigest(),
                        },
                    },
                    "provenance": kw.get("provenance"),
                }
            }
        }


def _fetcher(payload: bytes = b"\x89PNG\r\n\x1a\nfake", mime: str = "image/png"):
    def fetch(url: str) -> tuple[bytes, str]:
        # Distinct bytes per url so asset ids do not collide across creatives.
        return payload + url.encode("utf-8")[-16:], mime

    return fetch


def test_custody_downloads_bytes_and_stamps_the_full_provenance() -> None:
    selection = select_creatives(load_pages(), advertiser_name="Ramp", max_creatives=3)
    core = _FakeCore()

    outcome = custody_creatives(
        selection,
        core=core,
        cache_dir="/tmp/engine-cache",
        fetched_at="2026-08-26T00:00:00+00:00",
        provider_name="adyntel",
        advertiser_page_id="1406226",
        fetch=_fetcher(),
    )

    assert len(outcome.creatives) == 3
    assert len(outcome.asset_records) == 3
    assert not outcome.failures

    creative = outcome.creatives[0]
    provenance = core.calls[0]["provenance"]
    assert provenance["provider"] == "adyntel"
    assert provenance["ad_id"] == creative.ad.ad_id
    assert provenance["advertiser_page_id"] == "1406226"
    assert provenance["view_details_link"] == creative.ad.view_details_link
    assert provenance["fetched_at"] == "2026-08-26T00:00:00+00:00"
    assert provenance["creative_url"] == creative.image_url
    assert provenance["creative_id"] == creative_id_for(creative.image_url)
    # The bytes really were downloaded, not just the URL recorded.
    assert creative.image_bytes
    assert creative.asset_id


def test_the_fetch_time_is_the_callers_not_the_clocks() -> None:
    """One harvest is one gesture, so all of its rows carry one timestamp."""
    selection = select_creatives(load_pages(), advertiser_name="Ramp", max_creatives=4)
    core = _FakeCore()
    custody_creatives(
        selection,
        core=core,
        cache_dir="/tmp/engine-cache",
        fetched_at="2026-01-01T12:00:00+00:00",
        provider_name="adyntel",
        advertiser_page_id="1406226",
        fetch=_fetcher(),
    )
    stamps = {call["provenance"]["fetched_at"] for call in core.calls}
    assert stamps == {"2026-01-01T12:00:00+00:00"}


def test_one_rotten_creative_url_does_not_lose_the_others() -> None:
    """RED CASE: expired CDN links are the normal case, not the exception."""
    selection = select_creatives(load_pages(), advertiser_name="Ramp", max_creatives=3)
    doomed = selection.kept[1].image_url

    def fetch(url: str) -> tuple[bytes, str]:
        if url == doomed:
            raise AdLibraryError("ad_library.creative_fetch_failed", "HTTP 403")
        return b"\x89PNG\r\n\x1a\n" + url.encode("utf-8")[-16:], "image/png"

    outcome = custody_creatives(
        selection,
        core=_FakeCore(),
        cache_dir="/tmp/engine-cache",
        fetched_at="2026-08-26T00:00:00+00:00",
        provider_name="adyntel",
        advertiser_page_id="1406226",
        fetch=fetch,
    )

    assert len(outcome.creatives) == 2
    assert outcome.failures == [(selection.kept[1].ad_id, "ad_library.creative_fetch_failed")]


def test_creative_ids_are_content_addressed_on_the_url_so_a_re_run_converges() -> None:
    url = "https://media.licdn.com/dms/image/v2/example/0/1"
    assert creative_id_for(url) == creative_id_for(url)
    assert creative_id_for(url) != creative_id_for(url + "?v=2")
    assert creative_id_for(url).startswith("adcre_")


def test_the_route_and_the_harvest_default_to_fifty_ads_over_eight_pages() -> None:
    """Founder 2026-10-30: 50 ads, matching automatic onboarding (CLUE_BRAND_AD_ASSETS_AUTO_*)."""
    from lumen_api.models import OnboardAdAssetsRequest
    from lumen_ingestion.ad_library.harvest import DEFAULT_MAX_CREATIVES, DEFAULT_MAX_PAGES

    request = OnboardAdAssetsRequest(company_domain="example.com")
    assert (DEFAULT_MAX_CREATIVES, DEFAULT_MAX_PAGES) == (50, 8)
    assert (request.max_creatives, request.max_pages) == (50, 8)
