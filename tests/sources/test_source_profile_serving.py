"""M4.6 acceptance: source-profile serving + the registry-intersection allowed set (ENG-129).

Covers the AC "the three starter packs reproduce their staged-flow §7c orderings" (served from the
M3.3-authored priors, override > default) and "the allowed set is profile ∩ registry-capable" (a
profile source whose manifest is unregistered is dropped — can't plan what doesn't exist).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import (
    EntityScope,
    FieldClass,
    ICPCreatedFrom,
    ICPSpec,
    Modality,
    SourceManifest,
)
from clue_research.icp import (
    Pack,
    PackSourceSlot,
    SourceWeight,
    WeightedSource,
    create_icp_spec,
    load_starter_packs,
    register_pack_catalog,
    register_source_profile_override,
)
from clue_research.sources import (
    RegistrySourceManifest,
    register_source,
    resolve_allowed_set,
    seed_source_manifests,
    serve_source_profile,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

_CLIENT = "acme"
_ICP = "seg1"
_HI = SourceWeight.HIGH


async def _icp_with_packs(conn: AsyncConnection, *packs: str) -> ICPSpec:
    """Register the starter packs + an ICP spec enabling ``packs`` (returns the ``ICPSpec``)."""
    await load_starter_packs(conn)
    return await create_icp_spec(
        conn,
        client_id=_CLIENT,
        icp_key=_ICP,
        created_from=ICPCreatedFrom.SYNTHESIS,
        enabled_packs=packs,
    )


async def _manifest(
    conn: AsyncConnection,
    key: str,
    *,
    tier: int,
    modality: Modality = Modality.STRUCTURED,
    scope: EntityScope = EntityScope.ACCOUNT,
    yields: tuple[str, ...] = ("account",),
) -> None:
    await register_source(
        conn,
        RegistrySourceManifest(
            manifest=SourceManifest(
                source_key=key, modality=modality, entity_scope=scope, yields=yields, tier=tier
            )
        ),
    )


async def _icp_with_slots(conn: AsyncConnection, *slots: PackSourceSlot) -> ICPSpec:
    """Register a custom pack with the given source-profile ``slots`` + an ICP enabling it."""
    await register_pack_catalog(
        conn, Pack(pack_key="cpack", namespace="cpack", title="C", source_profile=slots)
    )
    return await create_icp_spec(
        conn,
        client_id=_CLIENT,
        icp_key=_ICP,
        created_from=ICPCreatedFrom.SYNTHESIS,
        enabled_packs=("cpack",),
    )


# --- §7c orderings reproduced from the served priors -------------------------


def test_frontier_ai_reproduces_7c_ordering() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            spec = await _icp_with_packs(conn, "frontier_ai")
            served = await serve_source_profile(conn, spec)
            keys = [s.source_key for s in served.default]
            assert keys == [
                "arxiv",
                "semantic_scholar",
                "github",
                "research_x",
                "press_releases",
                "glassdoor",
            ]
            # the §7c invariant: arXiv/GitHub (high) rank above Glassdoor (low).
            assert keys.index("arxiv") < keys.index("glassdoor")
            assert keys.index("github") < keys.index("glassdoor")

    run_async(_run())


def test_healthcare_reproduces_7c_ordering() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            spec = await _icp_with_packs(conn, "healthcare_practice")
            keys = [s.source_key for s in (await serve_source_profile(conn, spec)).default]
            assert keys == ["npi", "cms", "google_places", "job_boards", "journals"]
            # NPI/CMS + reviews (Places) rank above journals.
            assert keys.index("npi") < keys.index("journals")
            assert keys.index("google_places") < keys.index("journals")

    run_async(_run())


def test_data_infra_reproduces_7c_ordering() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            spec = await _icp_with_packs(conn, "data_infra")
            keys = [s.source_key for s in (await serve_source_profile(conn, spec)).default]
            assert keys == ["job_postings", "builtwith", "engineering_blogs"]

    run_async(_run())


# --- override > default (per-client/ICP) -------------------------------------


def test_client_override_beats_pack_default() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            spec = await _icp_with_packs(conn, "data_infra")
            # M13 / a client narrows the data_infra profile to just builtwith for this ICP.
            await register_source_profile_override(
                conn,
                "data_infra",
                _CLIENT,
                (WeightedSource(source_key="builtwith", weight=SourceWeight.HIGH, rank=1),),
                icp_key=_ICP,
            )
            served = await serve_source_profile(conn, spec)
            assert [s.source_key for s in served.default] == ["builtwith"]  # override replaced it

    run_async(_run())


# --- multi-pack ICP: profiles merge ------------------------------------------


def test_multi_pack_profile_merges_by_weight() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            spec = await _icp_with_packs(conn, "data_infra", "healthcare_practice")
            keys = [s.source_key for s in (await serve_source_profile(conn, spec)).default]
            high = {"job_postings", "builtwith", "npi", "cms", "google_places", "job_boards"}
            assert set(keys[:6]) == high  # every HIGH source ranks ahead of MED/LOW
            assert keys[6] == "engineering_blogs"  # the only MEDIUM
            assert keys[7] == "journals"  # the only LOW
            assert len(keys) == 8

    run_async(_run())


# --- the allowed set = profile ∩ registry-capable ----------------------------


def test_allowed_set_keeps_only_registered_capable_sources() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_source_manifests(
                conn
            )  # registers builtwith (and the rest), not job_postings
            spec = await _icp_with_packs(conn, "data_infra")
            allowed = await resolve_allowed_set(conn, spec, "core.primary_tech_stack", max_tier=1)
            # data_infra weights {job_postings, builtwith, engineering_blogs}; only builtwith is a
            # registered manifest that yields core.primary_tech_stack at tier 1 → the rest drop.
            assert [a.source_key for a in allowed] == ["builtwith"]
            assert allowed[0].tier == 1 and allowed[0].modality is Modality.STRUCTURED

    run_async(_run())


def test_allowed_set_empty_when_profile_sources_unregistered() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_source_manifests(conn)
            spec = await _icp_with_packs(conn, "frontier_ai")
            # frontier_ai weights {arxiv, semantic_scholar, github, …} — NONE are seeded manifests,
            # so nothing can be planned for it yet (the long-tail provider manifests are a backlog).
            allowed = await resolve_allowed_set(
                conn, spec, "account.resonance.research_prestige", max_tier=3
            )
            assert allowed == ()

    run_async(_run())


# --- per-field-class slot routing (the ICP-level analogue's field-class branch) ----


def test_field_class_specific_slot_routes_over_default() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            spec = await _icp_with_slots(
                conn,
                PackSourceSlot(
                    sources=(WeightedSource(source_key="default_src", weight=_HI, rank=1),)
                ),
                PackSourceSlot(
                    sources=(WeightedSource(source_key="resonance_src", weight=_HI, rank=1),),
                    field_class=FieldClass.ACCOUNT_RESONANCE,
                ),
            )
            served = await serve_source_profile(conn, spec)
            # the resonance-specific slot is served for resonance; everything else falls to default.
            assert [s.source_key for s in served.for_field_class(FieldClass.ACCOUNT_RESONANCE)] == [
                "resonance_src"
            ]
            assert [s.source_key for s in served.for_field_class(FieldClass.CORE)] == [
                "default_src"
            ]
            assert [s.source_key for s in served.default] == ["default_src"]

            # resolve_allowed_set routes by the FIELD: a resonance field → the specific slot.
            await _manifest(conn, "resonance_src", tier=3, yields=("account.resonance",))
            await _manifest(conn, "default_src", tier=1, yields=("account",))
            res = await resolve_allowed_set(conn, spec, "account.resonance.culture")
            assert [a.source_key for a in res] == ["resonance_src"]
            other = await resolve_allowed_set(conn, spec, "account.operational_pain")
            assert [a.source_key for a in other] == ["default_src"]

    run_async(_run())


# --- max_tier is an inclusive upper bound (tier-4 placeholders excluded at 1..3) ---


def test_max_tier_is_an_inclusive_upper_bound() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "t1", tier=1)
            await _manifest(conn, "t4", tier=4)  # a tier-4 (M11) placeholder-class source
            spec = await _icp_with_slots(
                conn,
                PackSourceSlot(
                    sources=(
                        WeightedSource(source_key="t1", weight=_HI, rank=1),
                        WeightedSource(source_key="t4", weight=_HI, rank=2),
                    )
                ),
            )
            all_tiers = await resolve_allowed_set(conn, spec, "account.operational_pain")
            assert {a.source_key for a in all_tiers} == {"t1", "t4"}  # None = every tier
            bounded = await resolve_allowed_set(conn, spec, "account.operational_pain", max_tier=3)
            assert [a.source_key for a in bounded] == ["t1"]  # tiers 1..3 exclude the tier-4 source

    run_async(_run())


# --- entity_scope filter widens 'both' and excludes a mismatched scope ----------


def test_entity_scope_filter_widens_both_and_excludes_mismatch() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "acct", tier=1, scope=EntityScope.ACCOUNT, yields=("contact",))
            await _manifest(conn, "cont", tier=1, scope=EntityScope.CONTACT, yields=("contact",))
            await _manifest(conn, "both", tier=1, scope=EntityScope.BOTH, yields=("contact",))
            spec = await _icp_with_slots(
                conn,
                PackSourceSlot(
                    sources=(
                        WeightedSource(source_key="acct", weight=_HI, rank=1),
                        WeightedSource(source_key="cont", weight=_HI, rank=2),
                        WeightedSource(source_key="both", weight=_HI, rank=3),
                    )
                ),
            )
            res = await resolve_allowed_set(conn, spec, "contact", entity_scope=EntityScope.CONTACT)
            # CONTACT + BOTH survive (widened); the ACCOUNT-scoped source is excluded by scope.
            assert {a.source_key for a in res} == {"cont", "both"}

    run_async(_run())


# --- multi-pack merge keeps the strongest weight on a shared source_key ----------


def test_multi_pack_merge_keeps_strongest_weight_on_overlap() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # two packs both weight 'builtwith' — pack A LOW, pack B HIGH; the merge keeps HIGH.
            await register_pack_catalog(
                conn,
                Pack(
                    pack_key="pa",
                    namespace="pa",
                    title="A",
                    source_profile=(
                        PackSourceSlot(
                            sources=(
                                WeightedSource(
                                    source_key="builtwith", weight=SourceWeight.LOW, rank=3
                                ),
                            )
                        ),
                    ),
                ),
            )
            await register_pack_catalog(
                conn,
                Pack(
                    pack_key="pb",
                    namespace="pb",
                    title="B",
                    source_profile=(
                        PackSourceSlot(
                            sources=(WeightedSource(source_key="builtwith", weight=_HI, rank=1),)
                        ),
                    ),
                ),
            )
            spec = await create_icp_spec(
                conn,
                client_id=_CLIENT,
                icp_key=_ICP,
                created_from=ICPCreatedFrom.SYNTHESIS,
                enabled_packs=("pa", "pb"),
            )
            served = await serve_source_profile(conn, spec)
            merged = {s.source_key: s for s in served.default}
            assert merged["builtwith"].weight is SourceWeight.HIGH  # strongest across packs wins

    run_async(_run())
