"""DSAR verbs for the memory substrate (Doc M Part V) — person-adjacent memories are personal
data, full stop, and erasure resolves to a deterministic query, never a substring scan.

These are the in-package verbs; the cross-subsystem cascade (a claim erasure tombstoning
subject-bound memories) wires at the api composition root with the Doc D backlog (PB-B3 §9.3).
Both verbs operate regardless of the kill-switch — obligations attach to *holding* data.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import MemoryCaps
from clue_core import MemoryEventType, MemoryStatus
from clue_memory import _store
from clue_memory.lifecycle import ENGINE_ACTOR, backfill_slot
from clue_memory.model import ERASED, Memory

_ALL_STATUSES = tuple(MemoryStatus)


async def erase_subject(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject_entity_id: UUID,
    caps: MemoryCaps,
    actor: str = ENGINE_ACTOR,
) -> list[str]:
    """Art. 17 erasure: tombstone every memory bound to the subject — status →``tombstoned``,
    content redacted to the sentinel (the sanctioned mutation: no personal substring survives
    at rest — deliberately not a second ``faithfulness_verdict.rationale`` debt), refs severed.
    Freed active slots backfill deterministically. Returns the tombstoned ids."""
    records = await _store.list_records(
        conn,
        workspace_id=workspace_id,
        statuses=_ALL_STATUSES,
        subject_entity_id=subject_entity_id,
    )
    erased: list[str] = []
    for memory in records:
        if memory.status is MemoryStatus.TOMBSTONED:
            continue
        await _store.redact_content(conn, memory.memory_id, ERASED)
        await _store.set_status(conn, memory.memory_id, MemoryStatus.TOMBSTONED)
        await _store.insert_event(
            conn,
            memory_id=memory.memory_id,
            workspace_id=workspace_id,
            event_type=MemoryEventType.TOMBSTONED,
            actor=actor,
            from_status=memory.status,
            to_status=MemoryStatus.TOMBSTONED,
            cause="DSAR erasure of subject",
        )
        erased.append(memory.memory_id)
        if memory.status is MemoryStatus.ACTIVE:
            await backfill_slot(
                conn,
                workspace_id=workspace_id,
                scope_type=memory.scope_type,
                scope_id=memory.scope_id,
                caps=caps,
            )
    return erased


async def lock_memory(
    conn: AsyncConnection, memory_id: str, *, caps: MemoryCaps, actor: str
) -> Memory | None:
    """Art. 21 objection lock (near-absolute for direct marketing): the record SURVIVES —
    content intact, distinct from tombstone — but is excluded from every subsequent bundle
    (the assembly gate selects ``active`` only). Frees its active slot for backfill."""
    memory = await _store.get_memory(conn, memory_id)
    if memory is None or memory.status is MemoryStatus.LOCKED:
        return memory
    await _store.set_status(conn, memory_id, MemoryStatus.LOCKED)
    await _store.insert_event(
        conn,
        memory_id=memory_id,
        workspace_id=memory.workspace_id,
        event_type=MemoryEventType.LOCKED,
        actor=actor,
        from_status=memory.status,
        to_status=MemoryStatus.LOCKED,
        cause="Art. 21 objection lock",
    )
    if memory.status is MemoryStatus.ACTIVE:
        await backfill_slot(
            conn,
            workspace_id=memory.workspace_id,
            scope_type=memory.scope_type,
            scope_id=memory.scope_id,
            caps=caps,
        )
    return await _store.get_memory(conn, memory_id)
