"""The ad-library provider seam + the Adyntel implementation (Brand Ad Assets v1, W2).

**The fixtures are the real wire shape.** ``tests/fixtures/ad_library/ramp_page{1,2}.json`` are
the frozen Ramp fetch from the POC (spec §2), copied field-for-field: the same top-level keys,
the same nested ``advertiser`` / ``image`` / ``headline`` / ``commentary`` blocks, the same
explicit ``null``s, the same continuation tokens, and the real duplicate-creative pair. Two
deliberate edits, both documented where they matter:

* the four individuals whose promoted posts appear in Ramp's library are renamed to
  ``Thought Leader N`` — the SHAPE (a person's name where the company's name belongs) is what
  the filter reads, and real people's identities have no business in a checked-in fixture;
* one extra ad, ``9000000001``, is synthetic: an image-typed thought-leader promotion. Every
  real thought-leader ad in the frozen fetch happens to be a video, so without it the
  advertiser-name rule would pass while doing nothing, carried entirely by the type filter.

Nothing here touches the network. The provider's transport is exercised only through its two
pure halves (``build_request_body`` / ``parse_page``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lumen_ingestion.ad_library import (
    AdLibraryCredentialsMissing,
    AdLibraryError,
    AdLibraryProvider,
    resolve_provider,
)
from lumen_ingestion.ad_library.adyntel import AdyntelProvider

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ad_library"


def load_page(number: int) -> dict:
    return json.loads((FIXTURES / f"ramp_page{number}.json").read_text())


@pytest.fixture
def provider() -> AdyntelProvider:
    return AdyntelProvider(
        api_key="test-key", email="tester@example.com", base_url="https://api.example.com"
    )


# --- credentials ---------------------------------------------------------------------------


def test_a_provider_with_no_credentials_refuses_before_building_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED CASE: the failure has to be typed and immediate, not a guessed-at 401 later."""
    from py_lumen_config import settings

    monkeypatch.setattr(settings, "adyntel_api_key", "", raising=False)
    monkeypatch.setattr(settings, "adyntel_email", "", raising=False)

    with pytest.raises(AdLibraryCredentialsMissing) as caught:
        AdyntelProvider()

    assert caught.value.code == "ad_library.credentials_missing"
    assert caught.value.variables == ("ADYNTEL_API_KEY", "ADYNTEL_EMAIL")
    # The message names the variables, never any value.
    assert "ADYNTEL_API_KEY" in str(caught.value)


def test_a_half_configured_provider_is_still_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from py_lumen_config import settings

    monkeypatch.setattr(settings, "adyntel_api_key", "a-key", raising=False)
    monkeypatch.setattr(settings, "adyntel_email", "", raising=False)

    with pytest.raises(AdLibraryCredentialsMissing):
        AdyntelProvider()


# --- the request body ----------------------------------------------------------------------


def test_the_request_body_matches_the_documented_endpoint_contract(
    provider: AdyntelProvider,
) -> None:
    body = provider.build_request_body(company_domain="ramp.com")
    assert body == {
        "api_key": "test-key",
        "email": "tester@example.com",
        "company_domain": "ramp.com",
    }

    paged = provider.build_request_body(
        page_id="1406226", continuation_token="1456531893-1785278227477", date_filter="last_30"
    )
    assert paged["linkedin_page_id"] == "1406226"
    assert paged["continuation_token"] == "1456531893-1785278227477"
    assert paged["date_filter"] == "last_30"
    assert "company_domain" not in paged


def test_all_ads_is_never_on_the_wire() -> None:
    """RED CASE: ``all_ads: true`` starts an unstoppable webhook delivery.

    Asserted over every request the builder can produce rather than by reading the code, so a
    later branch that adds the key fails here.
    """
    provider = AdyntelProvider(api_key="k", email="e@example.com")
    bodies = [
        provider.build_request_body(company_domain="ramp.com"),
        provider.build_request_body(company_domain="ramp.com", continuation_token="t"),
        provider.build_request_body(page_id="1406226", date_filter="last_30"),
    ]
    for body in bodies:
        assert "all_ads" not in body
        assert not any("all_ads" in str(value) for value in body.values())


def test_the_advertiser_selector_must_be_exactly_one(provider: AdyntelProvider) -> None:
    with pytest.raises(AdLibraryError) as neither:
        provider.build_request_body()
    assert neither.value.code == "ad_library.bad_request"

    with pytest.raises(AdLibraryError):
        provider.build_request_body(company_domain="ramp.com", page_id="1406226")


# --- parsing the real wire shape -------------------------------------------------------------


def test_the_real_page_shape_parses_into_typed_ads(provider: AdyntelProvider) -> None:
    page = provider.parse_page(load_page(1))

    assert page.provider == "adyntel"
    assert page.page_id == "1406226"
    assert page.total_ads == 11990
    assert page.continuation_token == "1456531893-1785278227477"
    assert page.is_last_page is False
    assert len(page.ads) == 25

    first = page.ads[0]
    assert first.ad_id == "1473633543"
    assert first.kind == "image"
    assert first.creative_type == "SPONSORED_STATUS_UPDATE"
    assert first.advertiser_name == "Ramp"
    assert first.advertiser_promoted is True
    assert first.image_url and first.image_url.startswith("https://media.licdn.com/")
    assert first.view_details_link == "https://www.linkedin.com/ad-library/detail/1473633543"
    assert first.has_carousel is False


def test_null_blocks_become_none_not_the_string_none(provider: AdyntelProvider) -> None:
    """The endpoint serves explicit ``null`` for ``headline.title`` and friends."""
    page = provider.parse_page(load_page(1))
    # Ad 1478270053 is one of the real thought-leader video promotions: its headline carries a
    # description but a null title, and its "image" is a video cover with null alt text.
    promotion = next(ad for ad in page.ads if ad.ad_id == "1478270053")
    assert promotion.headline_title is None
    assert promotion.image_alt_text is None
    assert promotion.headline_description is not None


def test_a_malformed_record_is_dropped_rather_than_failing_the_page(
    provider: AdyntelProvider,
) -> None:
    payload = load_page(1)
    payload["ads"] = [payload["ads"][0], "not-an-object", None, {}]
    page = provider.parse_page(payload)
    # The string and the None are dropped; the empty object survives with a blank ad_id, which
    # is what the harvest filter is there to reject.
    assert [ad.ad_id for ad in page.ads] == ["1473633543", ""]


def test_a_non_object_response_is_a_typed_failure(provider: AdyntelProvider) -> None:
    with pytest.raises(AdLibraryError) as caught:
        provider.parse_page(["not", "a", "page"])  # type: ignore[arg-type]
    assert caught.value.code == "ad_library.malformed_response"


# --- the seam ------------------------------------------------------------------------------


def test_the_resolved_provider_satisfies_the_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    from py_lumen_config import settings

    monkeypatch.setattr(settings, "adyntel_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "adyntel_email", "e@example.com", raising=False)
    assert isinstance(resolve_provider(), AdLibraryProvider)


def test_an_unknown_provider_is_refused_by_name() -> None:
    with pytest.raises(AdLibraryError) as caught:
        resolve_provider("meta")
    assert caught.value.code == "ad_library.unknown_provider"


def test_no_module_outside_the_provider_package_names_the_vendor() -> None:
    """D3: the provider is swappable — nothing else may know who it is.

    A textual guard rather than a reading, because the whole value of the seam is that a
    future Meta/Google fetcher is a new file and not a grep-and-replace.
    """
    api_root = Path(__file__).resolve().parents[1]
    allowed = {
        "lumen_ingestion/ad_library/adyntel.py",
        "lumen_ingestion/ad_library/provider.py",
        # The package docstring records which vendor v1 ships and where the seam is; that is
        # documentation of the boundary, not a caller reaching across it.
        "lumen_ingestion/ad_library/__init__.py",
    }
    offenders = []
    for path in sorted(
        [*(api_root / "lumen_api").rglob("*.py"), *(api_root / "lumen_ingestion").rglob("*.py")]
    ):
        relative = str(path.relative_to(api_root))
        if relative in allowed:
            continue
        if "adyntel" in path.read_text().lower():
            offenders.append(relative)
    assert not offenders, f"these modules name the v1 ad-library vendor directly: {offenders}"
