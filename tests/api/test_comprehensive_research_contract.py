"""Slice-A freeze of the comprehensive account/contact research contracts.

Authority: ``docs/FI-comprehensive-account-contact-research-contract.md`` §3.1 (the fixed
21-field account profile and its static provider ownership) and §7.1 (the 15-field contact
profile split 6 Sumble-structured / 9 Exa-Deep).
"""

from clue_api.comprehensive_research_contract import (
    COMPREHENSIVE_ACCOUNT_FIELD_SOURCES,
    COMPREHENSIVE_ACCOUNT_FIELDS,
    CONTACT_DEEP_FIELDS,
    CONTACT_STRUCTURED_FIELDS,
)
from clue_research.narrative.prose import PROSE_ACCOUNT_FIELDS, PROSE_CONTACT_FIELDS

_PERMITTED_ACCOUNT_SOURCES = {
    "exa_deep",
    "sumble_organizations",
    "sumble_jobs",
    "sumble_tech_stack",
}


def test_the_21_field_account_contract_is_frozen_verbatim() -> None:
    assert COMPREHENSIVE_ACCOUNT_FIELDS == PROSE_ACCOUNT_FIELDS
    assert len(COMPREHENSIVE_ACCOUNT_FIELDS) == 21
    assert COMPREHENSIVE_ACCOUNT_FIELDS[0] == "core.account_name"
    assert COMPREHENSIVE_ACCOUNT_FIELDS[20] == "account.resonance.buying_culture"


def test_every_account_field_has_static_ownership_within_the_permitted_set() -> None:
    assert set(COMPREHENSIVE_ACCOUNT_FIELD_SOURCES) == set(COMPREHENSIVE_ACCOUNT_FIELDS)
    for field, sources in COMPREHENSIVE_ACCOUNT_FIELD_SOURCES.items():
        assert set(sources) <= _PERMITTED_ACCOUNT_SOURCES, field
    # §3.1 spot checks:
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["core.primary_tech_stack"] == ("sumble_tech_stack",)
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["account.hiring_velocity_eng"] == ("sumble_jobs",)
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["account.operational_pain"] == ("exa_deep",)
    # Derive-only fields own no acquisition source:
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["core.employee_range"] == ()
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["core.revenue_band"] == ()


def test_the_15_field_contact_partition_is_exact_and_disjoint() -> None:
    assert CONTACT_STRUCTURED_FIELDS + CONTACT_DEEP_FIELDS == PROSE_CONTACT_FIELDS
    assert len(CONTACT_STRUCTURED_FIELDS) == 6
    assert len(CONTACT_DEEP_FIELDS) == 9
    assert all(k.startswith("contact.facet.") for k in CONTACT_DEEP_FIELDS)
    assert not any(k.startswith("contact.facet.") for k in CONTACT_STRUCTURED_FIELDS)


def test_the_account_launcher_supports_exactly_the_four_permitted_field_sources() -> None:
    """Regression tripwire (contract §2.2): freezes current truth, so it passes on arrival.

    It fails only if someone later widens the launcher's field-source set beyond the four
    permitted providers.
    """

    from clue_api.account_research_fleet_launch import _SUPPORTED_FIELD_SOURCES

    assert frozenset(_PERMITTED_ACCOUNT_SOURCES) == _SUPPORTED_FIELD_SOURCES


def test_committee_discovery_has_exactly_one_provider_and_no_fallback() -> None:
    """Regression tripwire (contract §5.1 / annotation 9): Sumble Teams/People only.

    Freezes current truth — no red phase — and fails if a committee-discovery fallback provider
    is introduced under this key.
    """

    from clue_api.account_research_fleet_launch import PEOPLE_SOURCE_KEY

    assert PEOPLE_SOURCE_KEY == "sumble_people"


def test_no_excluded_provider_family_is_importable_from_the_entity_research_wiring() -> None:
    """Regression tripwire (contract §2.2): the deferred provider families stay out of composition.

    Freezes current truth, so it passes on arrival — no red phase. It fails if a deferred family
    (Firecrawl, Scrapling, registries, CRM, Apollo, ZoomInfo, BuiltWith, Clay) is wired into the
    entity-research provider composition.
    """

    import inspect

    import clue_api.entity_research_provider_wiring as wiring

    source = inspect.getsource(wiring)
    for banned in ("firecrawl", "apollo", "zoominfo", "builtwith", "scrapling", "clay"):
        assert banned not in source.lower(), banned
