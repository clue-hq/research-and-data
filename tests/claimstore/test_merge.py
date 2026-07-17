"""M1.2 (ENG-110) — the merge DB seam: current_value / current_values / provenance_index.

Exercises the readers against live Postgres (skips without one). The merge *algorithm* itself is
unit-tested DB-free in ``tests/test_merge_policy.py``; here we prove the SQL fetch, the batch path,
superseded exclusion, and that the batch matches per-entity calls at Pass A scale.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest
from sqlalchemy import text

from clue_core import Claim, ExtractionMethod, new_entity_id, new_run_id
from clue_research.claimstore import (
    ALL_TENANTS,
    current_value,
    current_values,
    insert_claim,
    provenance_index,
    supersede_claim,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

_FIELD = "account.recent_funding"


def test_current_value_picks_lowest_tier(make_account: Callable[..., Claim]) -> None:
    """With a fresh tier-1, tier-3, and (unverified) tier-4 claim, current_value returns tier-1."""

    async def _run() -> None:
        t1 = make_account(value_json={"amount_usd": 10}, source_tier=1)
        t3 = make_account(
            value_json={"amount_usd": 30}, source_tier=3, extraction_method=ExtractionMethod.SCRAPE
        )
        t4 = make_account(
            value_json={"amount_usd": 40},
            source_tier=4,
            extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        )
        async with rollback_conn() as conn:
            for claim in (t3, t4, t1):
                await insert_claim(conn, claim)
            result = await current_value(conn, t1.entity_id, _FIELD, scope=ALL_TENANTS)
        assert result is not None
        assert result.value_json == {"amount_usd": 10}
        assert result.provenance.source_tier == 1

    run_async(_run())


def test_empty_when_no_eligible_claim(make_account: Callable[..., Claim]) -> None:
    """No claims, or only an unverified tier-4 claim, yields None (empty is correct)."""

    async def _run() -> None:
        lone_tier4 = make_account(
            value_json={"amount_usd": 4},
            source_tier=4,
            extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        )
        async with rollback_conn() as conn:
            assert (
                await current_value(conn, new_entity_id(), _FIELD, scope=ALL_TENANTS) is None
            )  # no claims
            await insert_claim(conn, lone_tier4)
            assert (
                await current_value(conn, lone_tier4.entity_id, _FIELD, scope=ALL_TENANTS) is None
            )  # only tier-4

    run_async(_run())


def test_superseded_claim_is_not_the_current_value(make_account: Callable[..., Claim]) -> None:
    """After supersession, current_value reflects only the live claim."""

    async def _run() -> None:
        old = make_account(value_json={"amount_usd": 1})
        new = make_account(value_json={"amount_usd": 2})
        async with rollback_conn() as conn:
            old_id = await insert_claim(conn, old)
            await supersede_claim(conn, old_id, new)
            result = await current_value(conn, old.entity_id, _FIELD, scope=ALL_TENANTS)
        assert result is not None
        assert result.value_json == {"amount_usd": 2}

    run_async(_run())


def test_batch_matches_per_entity(make_account: Callable[..., Claim]) -> None:
    """current_values() over several entities equals calling current_value() per entity."""

    async def _run() -> None:
        entities = [new_entity_id() for _ in range(5)]
        async with rollback_conn() as conn:
            for index, entity_id in enumerate(entities):
                await insert_claim(
                    conn, make_account(entity_id=entity_id, value_json={"amount_usd": index})
                )
            batch = await current_values(conn, entities, [_FIELD], scope=ALL_TENANTS)
            per_entity = {
                (entity_id, _FIELD): await current_value(conn, entity_id, _FIELD, scope=ALL_TENANTS)
                for entity_id in entities
            }
        assert len(batch) == len(entities)
        for key, expected in per_entity.items():
            assert batch[key] == expected

    run_async(_run())


def test_provenance_index_covers_each_field(make_account: Callable[..., Claim]) -> None:
    """provenance_index returns the winning provenance for every field with an eligible claim."""

    async def _run() -> None:
        funding = make_account(field_key="account.recent_funding", value_json={"amount_usd": 5})
        headcount = make_account(field_key="core.employee_count", value_json=250, source_tier=1)
        async with rollback_conn() as conn:
            await insert_claim(conn, funding)
            await insert_claim(conn, headcount)
            index = await provenance_index(conn, funding.entity_id, scope=ALL_TENANTS)
        assert set(index) == {"account.recent_funding", "core.employee_count"}
        assert index["core.employee_count"].source_tier == 1

    run_async(_run())


def test_batch_scales_to_1k_entities() -> None:
    """A 1k-entity batch returns a result per entity, matches per-entity, and is fast."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO claim (entity_id, entity_type, field_key, value_json, source_url,
                                       source_tier, extraction_method, confidence, run_id,
                                       research_mode)
                    SELECT gen_random_uuid(), 'account', :field,
                           jsonb_build_object('amount_usd', g), 'https://api.example', 1, 'api',
                           0.9, :run_id, 'account_profiling'
                    FROM generate_series(1, 1000) AS g
                    """
                ),
                {"field": _FIELD, "run_id": new_run_id()},
            )
            entity_ids = (
                (
                    await conn.execute(
                        text("SELECT entity_id FROM claim WHERE field_key = :f"), {"f": _FIELD}
                    )
                )
                .scalars()
                .all()
            )
            assert len(entity_ids) == 1000

            started = time.perf_counter()
            batch = await current_values(conn, entity_ids, [_FIELD], scope=ALL_TENANTS)
            elapsed = time.perf_counter() - started

            # a sample matches the per-entity call exactly
            for entity_id in entity_ids[:5]:
                assert batch[(entity_id, _FIELD)] == await current_value(
                    conn, entity_id, _FIELD, scope=ALL_TENANTS
                )

        assert len(batch) == 1000
        assert elapsed < 5.0, f"1k batch merge took {elapsed:.2f}s (budget 5s)"

    run_async(_run())
