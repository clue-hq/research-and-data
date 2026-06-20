"""M4.6 acceptance: per-source yield telemetry + config-driven learning (ENG-129).

Covers "``record_source_yield`` writes per-(ICP, field-class, source) telemetry" (and reads back
aggregated) and "a simulated M13 reweight changes the planner's subsequent ordering with no engine
change" — the learning loop is a config writer (a profile override), not a planner edit.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import (
    Entity,
    EntityScope,
    EntityType,
    FieldClass,
    ICPCreatedFrom,
    ICPSpec,
    Modality,
    ResearchMode,
    SourceManifest,
    new_entity_id,
    new_run_id,
)
from clue_research.icp import (
    Pack,
    PackSourceSlot,
    SourceWeight,
    WeightedSource,
    create_icp_spec,
    register_pack_catalog,
    register_source_profile_override,
)
from clue_research.sources import (
    RegistrySourceManifest,
    get_source_yield,
    plan_sources,
    record_source_yield,
    register_source,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

_CLIENT = "acme"
_ICP = "seg1"
_FIELD = "account.operational_pain"


# --- record + aggregate ------------------------------------------------------


def test_record_and_aggregate_source_yield() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await record_source_yield(
                conn,
                client_id=_CLIENT,
                icp_key=_ICP,
                source_key="arxiv",
                claims_total=10,
                claims_verified=8,
                fields_filled=3,
                cost_cents=Decimal(5),
            )
            await record_source_yield(
                conn,
                client_id=_CLIENT,
                icp_key=_ICP,
                source_key="arxiv",
                claims_total=5,
                claims_verified=5,
                fields_filled=2,
                cost_cents=Decimal(2),
            )
            stats = await get_source_yield(conn, client_id=_CLIENT, source_key="arxiv")
            assert len(stats) == 1
            stat = stats[0]
            assert stat.field_class is None and stat.source_key == "arxiv"
            assert stat.measurements == 2
            assert stat.claims_total == 15 and stat.claims_verified == 13
            assert stat.fields_filled == 5 and stat.cost_cents == Decimal(7)
            assert stat.precision == pytest.approx(13 / 15)  # survived / produced

    run_async(_run())


def test_yield_groups_by_field_class() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await record_source_yield(
                conn,
                client_id=_CLIENT,
                icp_key=_ICP,
                source_key="exa_deep",
                field_class=FieldClass.ACCOUNT_RESONANCE,
                claims_total=4,
                claims_verified=1,
            )
            await record_source_yield(
                conn,
                client_id=_CLIENT,
                icp_key=_ICP,
                source_key="exa_deep",
                field_class=FieldClass.CONTACT_FACET,
                claims_total=2,
                claims_verified=2,
            )
            stats = await get_source_yield(conn, client_id=_CLIENT, source_key="exa_deep")
            by_fc = {s.field_class: s for s in stats}
            assert by_fc[FieldClass.ACCOUNT_RESONANCE].precision == pytest.approx(0.25)
            assert by_fc[FieldClass.CONTACT_FACET].precision == 1.0

    run_async(_run())


def test_check_rejects_verified_greater_than_total() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(IntegrityError):
                await record_source_yield(
                    conn,
                    client_id=_CLIENT,
                    icp_key=_ICP,
                    source_key="arxiv",
                    claims_total=2,
                    claims_verified=3,  # a measurement can't verify more than it found
                )

    run_async(_run())


def test_check_rejects_negative_count_and_zero_icp_version() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(IntegrityError):
                await record_source_yield(
                    conn, client_id=_CLIENT, icp_key=_ICP, source_key="arxiv", claims_total=-1
                )

    async def _run2() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(IntegrityError):
                await record_source_yield(
                    conn, client_id=_CLIENT, icp_key=_ICP, source_key="arxiv", icp_version=0
                )

    run_async(_run())
    run_async(_run2())


def test_get_source_yield_narrows_by_icp_key_and_version() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # same source recorded under two ICP keys and two versions of one of them.
            await record_source_yield(
                conn,
                client_id=_CLIENT,
                icp_key="A",
                icp_version=1,
                source_key="arxiv",
                claims_total=4,
                claims_verified=2,
            )
            await record_source_yield(
                conn,
                client_id=_CLIENT,
                icp_key="B",
                icp_version=1,
                source_key="arxiv",
                claims_total=10,
                claims_verified=10,
            )
            await record_source_yield(
                conn,
                client_id=_CLIENT,
                icp_key="A",
                icp_version=2,
                source_key="arxiv",
                claims_total=6,
                claims_verified=0,
            )
            # icp_key=A pools A's versions only (4+6 total, 2+0 verified) — B is isolated out.
            a = await get_source_yield(conn, client_id=_CLIENT, icp_key="A", source_key="arxiv")
            assert (a[0].claims_total, a[0].claims_verified) == (10, 2)
            # narrowing to one version isolates that slot.
            a1 = await get_source_yield(
                conn, client_id=_CLIENT, icp_key="A", icp_version=1, source_key="arxiv"
            )
            assert (a1[0].claims_total, a1[0].claims_verified) == (4, 2)
            # B is never pooled into A (cross-ICP isolation).
            b = await get_source_yield(conn, client_id=_CLIENT, icp_key="B", source_key="arxiv")
            assert b[0].claims_total == 10

    run_async(_run())


def test_yield_forward_hooks_write_and_zero_claim_precision_is_none() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # exercise the forward-hook write paths: disposition (jsonb), freshness_seconds, run_id
            # (uuid), icp_version — and the zero-claim precision-None contract M13 branches on.
            await record_source_yield(
                conn,
                client_id=_CLIENT,
                icp_key=_ICP,
                source_key="exa_deep",
                field_class=FieldClass.ACCOUNT_RESONANCE,
                icp_version=2,
                run_id=new_run_id(),
                claims_total=0,
                claims_verified=0,
                fields_filled=0,
                cost_cents=Decimal("3.5"),
                freshness_seconds=86_400,
                disposition={"won": True, "stage": "closed"},
            )
            stats = await get_source_yield(conn, client_id=_CLIENT, source_key="exa_deep")
            assert len(stats) == 1
            assert stats[0].claims_total == 0
            assert stats[0].precision is None  # nothing produced ⇒ nothing to judge
            assert stats[0].cost_cents == Decimal("3.5")

    run_async(_run())


# --- the learning loop is config-driven (M13 reweight → reordering) ----------


async def _manifest(conn: AsyncConnection, source_key: str) -> None:
    await register_source(
        conn,
        RegistrySourceManifest(
            manifest=SourceManifest(
                source_key=source_key,
                modality=Modality.STRUCTURED,
                entity_scope=EntityScope.ACCOUNT,
                yields=("account",),
                tier=1,
            )
        ),
    )


async def _testpack(conn: AsyncConnection, *weighted: WeightedSource) -> ICPSpec:
    await register_pack_catalog(
        conn,
        Pack(
            pack_key="testpack",
            namespace="testpack",
            title="Test pack",
            source_profile=(PackSourceSlot(sources=weighted),),
        ),
    )
    return await create_icp_spec(
        conn,
        client_id=_CLIENT,
        icp_key=_ICP,
        created_from=ICPCreatedFrom.SYNTHESIS,
        enabled_packs=("testpack",),
    )


def test_simulated_reweight_changes_plan_order_no_engine_change() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "a")
            await _manifest(conn, "b")
            spec = await _testpack(
                conn,
                WeightedSource(source_key="a", weight=SourceWeight.HIGH, rank=1),
                WeightedSource(source_key="b", weight=SourceWeight.LOW, rank=2),
            )
            entity = Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)
            before = await plan_sources(
                conn, spec=spec, entity=entity, field=_FIELD, mode=ResearchMode.ACCOUNT_PROFILING
            )
            assert before.tier_plan() == ("a", "b")  # a (HIGH) ranks above b (LOW)

            # M13 measures yield (b out-performs a) and reweights — written as a profile override,
            # the same writable config seam. No planner/engine code changes.
            await record_source_yield(
                conn,
                client_id=_CLIENT,
                icp_key=_ICP,
                source_key="b",
                claims_total=10,
                claims_verified=10,
            )
            await register_source_profile_override(
                conn,
                "testpack",
                _CLIENT,
                (
                    WeightedSource(source_key="b", weight=SourceWeight.HIGH, rank=1),
                    WeightedSource(source_key="a", weight=SourceWeight.LOW, rank=2),
                ),
                icp_key=_ICP,
            )
            after = await plan_sources(
                conn, spec=spec, entity=entity, field=_FIELD, mode=ResearchMode.ACCOUNT_PROFILING
            )
            assert after.tier_plan() == ("b", "a")  # reordering is purely config-driven

    run_async(_run())
