"""Slice-A freeze of the comprehensive account/contact research contracts.

Authority: ``docs/FI-comprehensive-account-contact-research-contract.md`` §3.1 (the fixed
21-field account profile and its static provider ownership) and §7.1 (the 15-field contact
profile split 6 Sumble-structured / 9 Exa-Deep).
"""

import pytest

from clue_api.comprehensive_research_contract import (
    COMPREHENSIVE_ACCOUNT_FIELD_SOURCES,
    COMPREHENSIVE_ACCOUNT_FIELDS,
    CONTACT_DEEP_FIELDS,
    CONTACT_STRUCTURED_FIELDS,
)
from clue_core import (
    Entity,
    EntityScope,
    EntityType,
    ICPCreatedFrom,
    ResearchMode,
    new_entity_id,
)
from clue_research.icp import (
    Pack,
    PackSourceSlot,
    SourceWeight,
    WeightedSource,
    create_icp_spec,
    register_pack_catalog,
)
from clue_research.narrative.prose import PROSE_ACCOUNT_FIELDS, PROSE_CONTACT_FIELDS
from clue_research.sources import plan_sources, seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

_PERMITTED_ACCOUNT_SOURCES = {
    "exa_deep",
    "sumble_organizations",
    "sumble_jobs",
    "sumble_tech_stack",
}

#: The §3.1 rows that own at least one acquisition source — everything the launcher must be able to
#: plan. Derived from the contract map, never retyped.
_ACQUISITION_FIELDS = tuple(
    field for field in COMPREHENSIVE_ACCOUNT_FIELDS if COMPREHENSIVE_ACCOUNT_FIELD_SOURCES[field]
)


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


def test_the_static_ownership_table_is_pinned_row_for_row() -> None:
    """Carry-forward 3a — the whole §3.1 table, not five spot checks.

    Every row is a founder-adjudicated ownership decision; a silent edit to any of them changes
    which provider is bought for a field, so the literal below is the contract's durable pin.
    """

    assert dict(COMPREHENSIVE_ACCOUNT_FIELD_SOURCES) == {
        "core.account_name": (),
        "core.industry": ("sumble_organizations", "exa_deep"),
        "core.company_about": ("exa_deep", "sumble_organizations"),
        "core.employee_count": ("sumble_organizations",),
        "core.employee_range": (),
        "core.hq_location": ("sumble_organizations",),
        "core.annual_revenue": ("exa_deep",),
        "core.revenue_band": (),
        "core.primary_tech_stack": ("sumble_tech_stack",),
        "core.company_linkedin_url": ("sumble_organizations",),
        "account.total_funding": ("sumble_organizations", "exa_deep"),
        "account.recent_funding": ("sumble_organizations", "exa_deep"),
        "account.hiring_velocity_eng": ("sumble_jobs",),
        "account.operational_pain": ("exa_deep",),
        "account.strategic_moves": ("exa_deep",),
        "account.resonance.culture": ("exa_deep",),
        "account.resonance.employee_sentiment": ("exa_deep",),
        "account.resonance.attrition_signal": ("exa_deep",),
        "account.resonance.eng_blog_tone": ("exa_deep",),
        "account.resonance.public_frustrations": ("exa_deep",),
        "account.resonance.buying_culture": ("exa_deep",),
    }
    # The map is frozen at runtime too, not merely by convention (carry-forward 3b).
    with pytest.raises(TypeError):
        COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["core.industry"] = ()  # type: ignore[index]


@pytest.mark.usefixtures("require_profiling_db")
def test_every_acquisition_field_plans_a_permitted_source() -> None:
    """§3.1 ownership must reach the planner the launcher actually calls.

    ``AccountResearchFleetLauncher`` plans each confirmed field with ``plan_sources`` and then
    intersects the result with the four permitted field-sources; a field no permitted source
    *yields* leaves that intersection empty and raises ``no composed R5 source is authorized``.
    So for every §3.1 row that owns an acquisition source, the planned set must be non-empty and
    must stay inside that row's ownership — an extra permitted source would buy a provider §3.1
    never granted the field.
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            await load_client_knowledge_pack(conn)
            await seed_source_manifests(conn)
            await register_pack_catalog(
                conn,
                Pack(
                    pack_key="permitted_four",
                    namespace="permitted_four",
                    title="The four permitted account field-sources (§2.2)",
                    source_profile=(
                        PackSourceSlot(
                            sources=tuple(
                                WeightedSource(source_key=key, weight=SourceWeight.HIGH, rank=rank)
                                for rank, key in enumerate(
                                    (
                                        "sumble_organizations",
                                        "sumble_jobs",
                                        "sumble_tech_stack",
                                        "exa_deep",
                                    ),
                                    start=1,
                                )
                            )
                        ),
                    ),
                ),
            )
            spec = await create_icp_spec(
                conn,
                workspace_id="acme",
                icp_key="comprehensive",
                created_from=ICPCreatedFrom.SYNTHESIS,
                enabled_packs=("permitted_four",),
            )
            entity = Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)

            unplanned: list[str] = []
            overreaching: dict[str, set[str]] = {}
            for field in _ACQUISITION_FIELDS:
                plan = await plan_sources(
                    conn,
                    spec=spec,
                    entity=entity,
                    field=field,
                    mode=ResearchMode.ACCOUNT_PROFILING,
                    entity_scope=EntityScope.ACCOUNT,
                )
                planned = {source.source_key for source in plan.ordered_sources}
                if not planned:
                    unplanned.append(field)
                extra = planned - set(COMPREHENSIVE_ACCOUNT_FIELD_SOURCES[field])
                if extra:
                    overreaching[field] = extra
            assert not unplanned and not overreaching, (
                f"no permitted source yields: {unplanned}; "
                f"planned outside §3.1 ownership: {overreaching}"
            )

    run_async(_run())


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
