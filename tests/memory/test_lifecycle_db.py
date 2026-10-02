"""Lifecycle battery (Doc M §19 "lifecycle"): caps → dormancy, eviction = ranking inverted,
backfill, cycle-relative freshness (the no-wall-clock fixture), off-cycle fairness."""

from __future__ import annotations

import random

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    BORN_TRUST,
    MemoryAccepted,
    MemoryProvenanceClass,
    MemoryScopeType,
    MemoryStatus,
    MemoryType,
    ScopeStack,
)
from clue_memory import (
    WriteSeam,
    _store,  # test setup/inspection only
    rank_key,
    record_kickoff,
    retire,
    set_memory_enabled,
)

from .conftest import (
    add_judge,
    make_caps,
    make_settings,
    rollback_conn,
    run_async,
    seed_spine,
    submission,
)

pytestmark = pytest.mark.usefixtures("require_memory_db")


async def _write(
    conn: AsyncConnection, spine: object, body: str, caps: object = None, **kwargs: object
) -> str:
    outcome = await WriteSeam(
        conn, add_judge(), settings=make_settings(), caps=caps or make_caps()
    ).submit(submission(spine.workspace_id, body=body, **kwargs))  # type: ignore[attr-defined, arg-type]
    assert isinstance(outcome, MemoryAccepted)
    return outcome.memory_id


def test_store_cap_evicts_lowest_ranked_to_dormant_with_the_losing_comparison() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            caps = make_caps(store_caps={"brand": 2})
            first = await _write(conn, spine, "Guidance one.", caps, scope_id=spine.brand_id)
            second = await _write(conn, spine, "Guidance two.", caps, scope_id=spine.brand_id)
            # Confirm the first two so the third is strictly lowest-ranked.
            await _store.record_confirmation(conn, first, trust_grade=4)
            await _store.record_confirmation(conn, second, trust_grade=4)
            third = await _write(conn, spine, "Guidance three.", caps, scope_id=spine.brand_id)
            row = await _store.get_memory(conn, third)
            assert row is not None and row.status is MemoryStatus.DORMANT  # crowded out
            events = await _store.list_events(conn, third)
            evicted = [e for e in events if e["event_type"] == "evicted"]
            assert len(evicted) == 1
            assert "store cap 2" in (evicted[0]["cause"] or "")
            assert "lost to" in (evicted[0]["cause"] or "")

    run_async(scenario())


def test_eviction_order_equals_bundle_ranking_inverted_property() -> None:
    """Property over generated stores: the records a small cap would evict are EXACTLY the
    tail of the bundle ranking — one sort, two consumers, read from opposite ends."""
    rng = random.Random(42)

    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            ids: list[str] = []
            for i in range(8):
                provenance = rng.choice(list(MemoryProvenanceClass))
                memory = await _store.insert_memory(
                    conn,
                    workspace_id=spine.workspace_id,
                    scope_type=MemoryScopeType.BRAND,
                    scope_id=spine.brand_id,
                    type_=MemoryType.PREFERENCE,
                    trigger="t",
                    body=f"Generated guidance {i}.",
                    provenance_class=provenance.value,
                    trust_grade=BORN_TRUST[provenance],
                    status=MemoryStatus.ACTIVE,
                    creating_quote=None,
                    subject_entity_id=None,
                    claim_refs=(),
                )
                ids.append(memory.memory_id)
                for _ in range(rng.randrange(3)):
                    row = await _store.get_memory(conn, memory.memory_id)
                    assert row is not None
                    await _store.record_confirmation(
                        conn, memory.memory_id, trust_grade=min(4, row.trust_grade + 1)
                    )
            cap = 5
            records = await _store.list_records(
                conn,
                workspace_id=spine.workspace_id,
                statuses=(MemoryStatus.ACTIVE,),
                scope_type=MemoryScopeType.BRAND,
                scope_id=spine.brand_id,
            )
            expected_evictees = {m.memory_id for m in sorted(records, key=rank_key)[cap:]}
            from clue_memory import enforce_store_cap

            evicted = await enforce_store_cap(
                conn,
                workspace_id=spine.workspace_id,
                scope_type=MemoryScopeType.BRAND,
                scope_id=spine.brand_id,
                caps=make_caps(store_caps={"brand": cap}),
            )
            assert set(evicted) == expected_evictees

    run_async(scenario())


def test_annual_campaign_fixture_no_wall_clock_trust_inversion_impossible() -> None:
    """An 11-month-old, once-cycle-old, confirmed user_stated memory outranks a week-old
    unconfirmed agent_observed record: wall-clock appears nowhere in the ranking."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            veteran = await _write(
                conn, spine, "ROI framing wins with clinical buyers.", scope_id=spine.brand_id
            )
            await _store.record_confirmation(conn, veteran, trust_grade=4)
            # One kickoff since confirmation — a cycle old, not "stale by calendar".
            await record_kickoff(
                conn,
                scope_stack=ScopeStack(workspace_id=spine.workspace_id, brand_id=spine.brand_id),
                settings=make_settings(),
                actor="test",
            )
            # A "week-old" unconfirmed agent hunch, ACTIVE (simulating a Phase-C review
            # approval — the queue producer does not exist yet).
            hunch = await _store.insert_memory(
                conn,
                workspace_id=spine.workspace_id,
                scope_type=MemoryScopeType.BRAND,
                scope_id=spine.brand_id,
                type_=MemoryType.PREFERENCE,
                trigger="t",
                body="Maybe try memes in outreach.",
                provenance_class=MemoryProvenanceClass.AGENT_OBSERVED.value,
                trust_grade=BORN_TRUST[MemoryProvenanceClass.AGENT_OBSERVED],
                status=MemoryStatus.ACTIVE,
                creating_quote=None,
                subject_entity_id=None,
                claim_refs=(),
            )
            records = await _store.list_records(
                conn,
                workspace_id=spine.workspace_id,
                statuses=(MemoryStatus.ACTIVE,),
                scope_type=MemoryScopeType.BRAND,
                scope_id=spine.brand_id,
            )
            ranked = sorted(records, key=rank_key)
            assert [m.memory_id for m in ranked] == [veteran, hunch.memory_id]

    run_async(scenario())


def test_backfill_promotes_highest_ranked_dormant_on_freed_slot() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            caps = make_caps(store_caps={"brand": 2})
            first = await _write(conn, spine, "Guidance one.", caps, scope_id=spine.brand_id)
            second = await _write(conn, spine, "Guidance two.", caps, scope_id=spine.brand_id)
            await _store.record_confirmation(conn, first, trust_grade=4)
            await _store.record_confirmation(conn, second, trust_grade=4)
            third = await _write(conn, spine, "Guidance three.", caps, scope_id=spine.brand_id)
            assert (await _store.get_memory(conn, third)).status is MemoryStatus.DORMANT  # type: ignore[union-attr]

            from clue_memory import lock_memory

            await lock_memory(conn, first, caps=caps, actor="dsar-surface")
            promoted = await _store.get_memory(conn, third)
            assert promoted is not None and promoted.status is MemoryStatus.ACTIVE
            events = {e["event_type"] for e in await _store.list_events(conn, third)}
            assert "backfilled" in events

    run_async(scenario())


def test_off_cycles_do_not_age_memories() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            memory_id = await _write(conn, spine, "Guidance one.", scope_id=spine.brand_id)
            stack = ScopeStack(workspace_id=spine.workspace_id, brand_id=spine.brand_id)
            settings = make_settings()

            # Memory off → the kickoff is an off-cycle: counters must not move (§17b).
            await set_memory_enabled(conn, spine.workspace_id, False, actor="admin")
            assert await record_kickoff(conn, scope_stack=stack, settings=settings, actor="t") == []
            row = await _store.get_memory(conn, memory_id)
            assert row is not None and row.cycles_since_confirmed == 0

            # Back on → the kickoff counts.
            await set_memory_enabled(conn, spine.workspace_id, True, actor="admin")
            aged = await record_kickoff(conn, scope_stack=stack, settings=settings, actor="t")
            assert memory_id in aged
            row = await _store.get_memory(conn, memory_id)
            assert row is not None and row.cycles_since_confirmed == 1
            events = {e["event_type"] for e in await _store.list_events(conn, memory_id)}
            assert "kickoff_cycle" in events

    run_async(scenario())


def test_retire_refuses_a_record_that_is_not_active_and_journals_nothing() -> None:
    """The human verb is active-only: a crowded-out dormant record (and a missing id) is
    refused without a journal entry, so *Remove memory* can never fake a transition."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            caps = make_caps(store_caps={"brand": 1})
            first = await _write(conn, spine, "Guidance one.", caps, scope_id=spine.brand_id)
            await _store.record_confirmation(conn, first, trust_grade=4)
            dormant = await _write(conn, spine, "Guidance two.", caps, scope_id=spine.brand_id)
            row = await _store.get_memory(conn, dormant)
            assert row is not None and row.status is MemoryStatus.DORMANT

            assert (
                await retire(
                    conn,
                    memory_id=dormant,
                    workspace_id=spine.workspace_id,
                    actor="usr_home",
                    cause="removed on project home",
                )
                is False
            )
            still = await _store.get_memory(conn, dormant)
            assert still is not None and still.status is MemoryStatus.DORMANT
            events = {e["event_type"] for e in await _store.list_events(conn, dormant)}
            assert "invalidated" not in events

            assert (
                await retire(
                    conn,
                    memory_id="mem_does_not_exist",
                    workspace_id=spine.workspace_id,
                    actor="usr_home",
                    cause="ghost",
                )
                is False
            )

    run_async(scenario())
