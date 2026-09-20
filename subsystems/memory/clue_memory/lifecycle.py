"""Lifecycle machinery (Doc M §12–§15): the one ranking, store caps → dormancy, eviction,
backfill, and cycle-relative freshness.

**One lexicographic sort, two consumers** (Doc M §15): what enters a bundle and what stays
active are decided by the same transparent order — :func:`rank_key` — read from opposite ends.
The structural guarantee follows: an unconfirmed ``agent_observed`` hunch can never stay active
while a multiply-confirmed ``user_stated`` rule goes dormant. No blended scores, no wall-clock
anywhere: trust, then cycle-relative freshness, then confirmations, then id (a total order, so
every decision is reproducible and every eviction explains itself as a sentence, not a number).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import MemoryCaps, Settings
from clue_core import (
    MemoryEventType,
    MemoryScopeType,
    MemoryStatus,
    ScopeStack,
)
from clue_memory import _store
from clue_memory.model import Memory
from clue_memory.switch import is_memory_enabled

ENGINE_ACTOR = "engine"


def rank_key(memory: Memory) -> tuple[int, int, int, str]:
    """Best-first bundle order == worst-last eviction order (ascending sort):
    trust desc, cycles-since-confirmed asc, confirmations desc, id asc (total order)."""
    return (
        -memory.trust_grade,
        memory.cycles_since_confirmed,
        -memory.confirmation_count,
        memory.memory_id,
    )


def losing_comparison(loser: Memory, winner: Memory) -> str:
    """The auditable sentence for an eviction/exclusion: WHY the loser ranked below the last
    winner — the first differing sort component, spelled out (never a score)."""
    if loser.trust_grade != winner.trust_grade:
        return f"lost to {winner.memory_id} on trust ({loser.trust_grade} < {winner.trust_grade})"
    if loser.cycles_since_confirmed != winner.cycles_since_confirmed:
        return (
            f"lost to {winner.memory_id} on freshness (cycles since confirmed "
            f"{loser.cycles_since_confirmed} > {winner.cycles_since_confirmed})"
        )
    if loser.confirmation_count != winner.confirmation_count:
        return (
            f"lost to {winner.memory_id} on confirmations "
            f"({loser.confirmation_count} < {winner.confirmation_count})"
        )
    return f"lost to {winner.memory_id} on id order (full tie)"


async def enforce_store_cap(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    scope_type: MemoryScopeType,
    scope_id: str,
    caps: MemoryCaps,
) -> list[str]:
    """Evict beyond-cap active records of one scope instance → ``dormant`` (crowded out, not
    wrong — Doc M §14), lowest-ranked first, each journaled with its losing comparison.
    Returns evicted ids."""
    active = await _store.list_records(
        conn,
        workspace_id=workspace_id,
        statuses=(MemoryStatus.ACTIVE,),
        scope_type=scope_type,
        scope_id=scope_id,
    )
    cap = caps.store_cap_for(scope_type.value)
    if len(active) <= cap:
        return []
    ranked = sorted(active, key=rank_key)
    survivors, evictees = ranked[:cap], ranked[cap:]
    last_survivor = survivors[-1]
    evicted: list[str] = []
    for memory in evictees:
        await _store.set_status(conn, memory.memory_id, MemoryStatus.DORMANT)
        await _store.insert_event(
            conn,
            memory_id=memory.memory_id,
            workspace_id=workspace_id,
            event_type=MemoryEventType.EVICTED,
            actor=ENGINE_ACTOR,
            from_status=MemoryStatus.ACTIVE,
            to_status=MemoryStatus.DORMANT,
            cause=f"store cap {cap} for {scope_type.value} scope: "
            + losing_comparison(memory, last_survivor),
        )
        evicted.append(memory.memory_id)
    return evicted


async def retire(
    conn: AsyncConnection, *, memory_id: str, workspace_id: str, actor: str, cause: str
) -> bool:
    """A human removes a note: ``active → invalidated``, journaled. Never deletes (Doc M §5).

    Fail-closed and idempotent-by-refusal: returns ``False`` — writing nothing — when the row is
    absent, belongs to another workspace, or is not currently active, so a repeat click and a
    cross-tenant caller are indistinguishable from the outside.
    """
    memory = await _store.get_memory(conn, memory_id)
    if (
        memory is None
        or memory.workspace_id != workspace_id
        or memory.status is not MemoryStatus.ACTIVE
    ):
        return False
    await _store.set_status(conn, memory_id, MemoryStatus.INVALIDATED)
    await _store.insert_event(
        conn,
        memory_id=memory_id,
        workspace_id=workspace_id,
        event_type=MemoryEventType.INVALIDATED,
        actor=actor,
        from_status=MemoryStatus.ACTIVE,
        to_status=MemoryStatus.INVALIDATED,
        cause=cause,
    )
    return True


async def backfill_slot(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    scope_type: MemoryScopeType,
    scope_id: str,
    caps: MemoryCaps,
) -> str | None:
    """A freed active slot (supersession/invalidate/tombstone/lock) goes to the highest-ranked
    dormant record, deterministically, journaled (Doc M §15 path 1). Returns the promoted id."""
    active = await _store.list_records(
        conn,
        workspace_id=workspace_id,
        statuses=(MemoryStatus.ACTIVE,),
        scope_type=scope_type,
        scope_id=scope_id,
    )
    if len(active) >= caps.store_cap_for(scope_type.value):
        return None
    dormant = await _store.list_records(
        conn,
        workspace_id=workspace_id,
        statuses=(MemoryStatus.DORMANT,),
        scope_type=scope_type,
        scope_id=scope_id,
    )
    if not dormant:
        return None
    best = min(dormant, key=rank_key)
    await _store.set_status(conn, best.memory_id, MemoryStatus.ACTIVE)
    await _store.insert_event(
        conn,
        memory_id=best.memory_id,
        workspace_id=workspace_id,
        event_type=MemoryEventType.BACKFILLED,
        actor=ENGINE_ACTOR,
        from_status=MemoryStatus.DORMANT,
        to_status=MemoryStatus.ACTIVE,
        cause="freed active slot — highest-ranked dormant record promoted",
    )
    return best.memory_id


async def record_kickoff(
    conn: AsyncConnection,
    *,
    scope_stack: ScopeStack,
    settings: Settings,
    actor: str,
) -> list[str]:
    """A kickoff of these scopes: age every live (active ∪ dormant) record by one cycle
    (Doc M §12). **Off-cycles do not count** (§17b): when memory is off for the workspace this
    is a no-op — a client returning from off-campaigns must not find a store wrongly stale.
    The Phase-C kickoff interview is the caller. Returns the aged ids.

    Account-scoped memories persist across campaigns (Doc M §4); a kickoff of a stack carrying an
    ``account_entity_id`` ages that account's records like any other scope.
    """
    if not await is_memory_enabled(conn, scope_stack.workspace_id, settings):
        return []
    scopes: list[tuple[MemoryScopeType, str]] = [
        (MemoryScopeType.WORKSPACE, scope_stack.workspace_id),
        (MemoryScopeType.BRAND, scope_stack.brand_id),
    ]
    if scope_stack.product_id is not None:
        scopes.append((MemoryScopeType.PRODUCT, scope_stack.product_id))
    if scope_stack.project_id is not None:
        scopes.append((MemoryScopeType.PROJECT, scope_stack.project_id))
    if scope_stack.account_entity_id is not None:
        scopes.append((MemoryScopeType.ACCOUNT, str(scope_stack.account_entity_id)))
    aged: list[str] = []
    for scope_type, scope_id in scopes:
        ids = await _store.increment_cycles(
            conn,
            workspace_id=scope_stack.workspace_id,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        for memory_id in ids:
            await _store.insert_event(
                conn,
                memory_id=memory_id,
                workspace_id=scope_stack.workspace_id,
                event_type=MemoryEventType.KICKOFF_CYCLE,
                actor=actor,
                cause=f"kickoff of {scope_type.value} scope {scope_id}",
            )
        aged.extend(ids)
    return aged
