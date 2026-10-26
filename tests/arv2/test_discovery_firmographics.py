"""Choosing the one AI Ark record a discovered account is (spec 2026-10-27, the strict rule).

The cases are the ones the trial on 135 real accounts met: a group's own page among its hotels'
pages (Wanda, Provenance), a parent whose own website has a route (Shangri-La), duplicate pages of
one company, stray tiny pages (Toro), a single record that is a different company (Mitsubishi
Materials) and a domain that only hosts customers' pages (Main Street Hub).
"""

from __future__ import annotations

from typing import Any

from clue_api.arv2.ai_ark_client import company_from_record
from clue_api.arv2.discovery_firmographics import (
    FIRMOGRAPHIC_FIELDS,
    names_match,
    resolve_company,
)


def _record(name: str, domain: str, *, website: str | None = None, staff: int = 100) -> Any:
    return company_from_record(
        {
            "id": f"id-{name}",
            "summary": {"name": name, "staff": {"total": staff}},
            "link": {"domain": domain, "website": website or f"http://www.{domain}"},
        }
    )


def test_the_table_fields_are_the_ones_discovery_fills() -> None:
    assert (
        frozenset(
            {
                "core.industry",
                "core.industries_all",
                "core.revenue_band",
                "core.employee_count",
                "core.employee_range",
                "core.hq_location",
                "core.company_linkedin_url",
                "core.company_twitter_url",
            }
        )
        == FIRMOGRAPHIC_FIELDS
    )


def test_names_match_sets_aside_case_accents_punctuation_and_company_suffixes() -> None:
    assert names_match("Wanda Hotels & Resorts", "wanda hotels and resorts")
    assert names_match("Germain Hôtels", "Germain Hotels")
    assert names_match("Saia", "Saia Inc.")
    assert names_match("The Kessler Collection", "Kessler Collection")
    assert not names_match("Champion Hotels & Development", "Champion Hotels Management")
    assert not names_match("Shangri-La Group", "Shangri-La Academy")
    assert not names_match("", "Anything")


def test_the_groups_own_page_wins_over_a_bigger_hotel_page() -> None:
    records = [
        _record("Wanda Vista Lanzhou", "wandahotels.com", staff=1035),
        _record("Wanda Hotels & Resorts", "wandahotels.com", staff=749),
        _record("Wanda Reign Chengdu", "wandahotels.com", staff=217),
    ]
    chosen = resolve_company("wandahotels.com", "Wanda Hotels & Resorts", records)
    assert chosen is not None
    assert chosen.company.name == "Wanda Hotels & Resorts"
    assert chosen.how == "exact_name"


def test_a_parent_whose_website_has_a_route_is_still_found_by_name() -> None:
    records = [
        _record("Shangri-La Academy", "shangri-la.com"),
        _record("Shangri-La Group", "shangri-la.com", website="http://www.shangri-la.com/group"),
    ]
    chosen = resolve_company("shangri-la.com", "Shangri-La Group", records)
    assert chosen is not None and chosen.company.name == "Shangri-La Group"


def test_duplicate_pages_of_one_company_prefer_the_homepage_then_staff() -> None:
    records = [
        _record(
            "Crescent Hotels & Resorts",
            "crescenthotels.com",
            website="http://crescenthotels.com/careers",
            staff=2000,
        ),
        _record("Crescent Hotels & Resorts", "crescenthotels.com", staff=1125),
        _record("Crescent Hotels & Resorts", "crescenthotels.com", staff=40),
    ]
    chosen = resolve_company("crescenthotels.com", "Crescent Hotels & Resorts", records)
    assert chosen is not None
    assert chosen.company.employee_count == 1125
    assert chosen.how == "exact_name_tiebreak"


def test_stray_tiny_pages_are_set_aside_when_a_domain_has_several() -> None:
    records = [
        _record("TORO EUROPE NV", "toro.com", website="http://www.toro.be", staff=7),
        _record("Toro Inc", "toro.com", staff=2),
        _record("Toro Asia", "toro.com", staff=0),
    ]
    assert resolve_company("toro.com", "The Toro Company", records) is None


def test_a_single_record_must_still_carry_the_accounts_name() -> None:
    only = [
        _record(
            "MMC Hardmetal UK Ltd", "mitsubishicarbide.com", website="http://www.mmc-carbide.com"
        )
    ]
    assert resolve_company("mitsubishicarbide.com", "Mitsubishi Materials", only) is None

    small = [_record("SBM Hospitality", "sbmhospitality.com", staff=3)]
    chosen = resolve_company("sbmhospitality.com", "SBM Hospitality LLC", small)
    assert chosen is not None and chosen.how == "single_record"


def test_a_domain_hosting_only_other_companies_pages_resolves_to_nothing() -> None:
    records = [
        _record(
            "Ginghams Homestyle Restaurant",
            "mainstreethub.com",
            website="http://m.mainstreethub.com/ginghamsrestaurant",
        ),
        _record(
            "A Spot Of Tea", "mainstreethub.com", website="http://m.mainstreethub.com/spotoftea"
        ),
    ]
    assert resolve_company("mainstreethub.com", "Main Street Hub", records) is None


def test_only_records_of_the_accounts_own_domain_are_considered() -> None:
    records = [_record("Banner Health", "bannerbank.com"), _record("Banner Bank", "bannerbank.com")]
    assert resolve_company("bannerhealth.com", "Banner Health", records) is None


def test_a_record_filed_under_another_domain_counts_when_its_website_is_the_account_domain() -> (
    None
):
    """Live run 2026-10-27: AI Ark files eHealth, Inc. under ``ehealthinsurance.com`` while its
    website is ``eHealth.com`` — the domain discovery found. The record's own website places it
    on the account's domain; the name rule still keeps "eHealth Jamaica Limited" out."""
    records = [
        _record(
            "eHealth, Inc.", "ehealthinsurance.com", website="http://www.eHealth.com", staff=2077
        ),
        _record(
            "eHealth Jamaica Limited",
            "endelevufinancial.com",
            website="http://www.eHealth.com",
            staff=0,
        ),
    ]
    chosen = resolve_company("ehealth.com", "eHealth, Inc.", records)
    assert chosen is not None and chosen.company.name == "eHealth, Inc."


def test_a_domain_filed_as_a_full_url_still_matches() -> None:
    records = [_record("HM Alpha Hotels & Resorts", "http://www.hmalpha.com", website="")]
    chosen = resolve_company("hmalpha.com", "HM Alpha Hotels & Resorts", records)
    assert chosen is not None and chosen.how == "single_record"
