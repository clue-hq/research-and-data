"""PRIVATE storage access for the memory substrate — raw SQL in the spine style.

Underscore-private on purpose: the two seams (``write.py`` / ``assembly.py``) and the lifecycle/
compliance/switch verbs are the only callers (a structure-guard test enforces it, and Rule S1
keeps every other package out entirely). Constraint violations surface as raw
:class:`sqlalchemy.exc.IntegrityError` — the schema IS the enforcement (cross-workspace scope
refs, dangling scopes, malformed person-adjacency all die here, not in handler code).

Append-only in spirit: content columns are written once; the sanctioned mutations are status
transitions, counter/trust updates (confirmation, cycle aging, contradiction), the
``superseded_by`` link, and DSAR redaction (:data:`~clue_memory.model.ERASED`).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    MemoryEventType,
    MemoryScopeType,
    MemoryStatus,
    MemoryType,
)
from clue_memory.model import Memory, new_memory_id

_MEMORY_COLUMNS = (
    "memory_id, workspace_id, scope_type, scope_id, type, trigger, body, provenance_class, "
    "trust_grade, creating_quote, status, superseded_by, confirmation_count, last_confirmed_at, "
    "cycles_since_confirmed, subject_entity_id, source_thread_id, retention_class, created_at"
)


def _row_to_memory(row: dict[str, Any], claim_refs: tuple[UUID, ...] = ()) -> Memory:
    return Memory(**row, claim_refs=claim_refs)


async def _refs_for(conn: AsyncConnection, memory_ids: list[str]) -> dict[str, tuple[UUID, ...]]:
    """Claim refs for a batch of memories, sorted per memory (deterministic labels)."""
    if not memory_ids:
        return {}
    result = await conn.execute(
        text(
            "SELECT memory_id, claim_id FROM memory_claim_ref "
            "WHERE memory_id = ANY(:ids) ORDER BY memory_id, claim_id"
        ),
        {"ids": memory_ids},
    )
    refs: dict[str, tuple[UUID, ...]] = {}
    for row in result.mappings().all():
        refs[row["memory_id"]] = (*refs.get(row["memory_id"], ()), row["claim_id"])
    return refs


async def insert_memory(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    scope_type: MemoryScopeType,
    scope_id: str | None,
    type_: MemoryType,
    trigger: str,
    body: str,
    provenance_class: str,
    trust_grade: int,
    status: MemoryStatus,
    creating_quote: str | None,
    subject_entity_id: UUID | None,
    claim_refs: tuple[UUID, ...],
    memory_id: str | None = None,
    source_thread_id: str | None = None,
) -> Memory:
    """Insert one record (+ its claim refs). Scope validity is the composite FKs' job: a
    cross-workspace or dangling scope id raises ``IntegrityError`` here — by design."""
    scope_columns = {
        MemoryScopeType.WORKSPACE: None,
        MemoryScopeType.BRAND: "scope_brand_id",
        MemoryScopeType.PRODUCT: "scope_product_id",
        MemoryScopeType.PROJECT: "scope_project_id",
        MemoryScopeType.ACCOUNT: "scope_account_entity_id",
    }[scope_type]
    params: dict[str, Any] = {
        "memory_id": memory_id or new_memory_id(),
        "workspace_id": workspace_id,
        "scope_type": scope_type.value,
        "scope_brand_id": None,
        "scope_product_id": None,
        "scope_project_id": None,
        "scope_account_entity_id": None,
        "type": type_.value,
        "trigger": trigger,
        "body": body,
        "provenance_class": provenance_class,
        "trust_grade": trust_grade,
        "creating_quote": creating_quote,
        "status": status.value,
        "subject_entity_id": subject_entity_id,
        "source_thread_id": source_thread_id,
        "retention_class": "person_adjacent" if subject_entity_id is not None else "standard",
    }
    if scope_columns is not None:
        # account scope_id is the account_entity uuid carried as a string — bind the uuid type
        # (asyncpg needs it; the column is uuid, unlike the other scope FKs which are text).
        params[scope_columns] = (
            UUID(scope_id)
            if scope_type is MemoryScopeType.ACCOUNT and scope_id is not None
            else scope_id
        )
    result = await conn.execute(
        text(
            "INSERT INTO memory (memory_id, workspace_id, scope_type, scope_brand_id, "
            "scope_product_id, scope_project_id, scope_account_entity_id, type, trigger, body, "
            "provenance_class, trust_grade, creating_quote, status, subject_entity_id, "
            "source_thread_id, retention_class) "
            "VALUES (:memory_id, :workspace_id, :scope_type, :scope_brand_id, "
            ":scope_product_id, :scope_project_id, :scope_account_entity_id, :type, :trigger, "
            ":body, :provenance_class, :trust_grade, :creating_quote, :status, "
            ":subject_entity_id, :source_thread_id, :retention_class) "
            f"RETURNING {_MEMORY_COLUMNS}"
        ),
        params,
    )
    row = dict(result.mappings().one())
    for claim_id in claim_refs:
        await conn.execute(
            text(
                "INSERT INTO memory_claim_ref (memory_id, claim_id) "
                "VALUES (:memory_id, :claim_id) ON CONFLICT DO NOTHING"
            ),
            {"memory_id": row["memory_id"], "claim_id": claim_id},
        )
    return _row_to_memory(row, tuple(sorted(set(claim_refs), key=str)))


async def get_memory(conn: AsyncConnection, memory_id: str) -> Memory | None:
    result = await conn.execute(
        text(f"SELECT {_MEMORY_COLUMNS} FROM memory WHERE memory_id = :memory_id"),
        {"memory_id": memory_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    refs = await _refs_for(conn, [memory_id])
    return _row_to_memory(dict(row), refs.get(memory_id, ()))


async def get_selected_records(
    conn: AsyncConnection, *, workspace_id: str, memory_ids: tuple[str, ...]
) -> list[Memory]:
    """Fetch only selected tenant rows and their labels in one SQL snapshot.

    Resolution must not combine a pre-erasure body with post-erasure refs/status from another
    statement. Status is deliberately returned for the read seam's fail-closed eligibility check.
    """
    result = await conn.execute(
        text(
            f"SELECT {_MEMORY_COLUMNS}, ARRAY(SELECT claim_id FROM memory_claim_ref r "
            "WHERE r.memory_id = memory.memory_id ORDER BY claim_id) AS claim_refs "
            "FROM memory WHERE workspace_id = :workspace_id AND memory_id = ANY(:ids)"
        ),
        {"workspace_id": workspace_id, "ids": list(memory_ids)},
    )
    return [Memory(**dict(row)) for row in result.mappings().all()]


async def list_records(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    statuses: tuple[MemoryStatus, ...],
    scope_type: MemoryScopeType | None = None,
    scope_id: str | None = None,
    type_: MemoryType | None = None,
    types: tuple[MemoryType, ...] | None = None,
    subject_entity_id: UUID | None = None,
) -> list[Memory]:
    """Records of one workspace, filtered — ALWAYS tenant-filtered (fail-closed: the
    ``workspace_id`` parameter is mandatory, there is no unfiltered query)."""
    where = ["workspace_id = :workspace_id", "status = ANY(:statuses)"]
    params: dict[str, Any] = {
        "workspace_id": workspace_id,
        "statuses": [s.value for s in statuses],
    }
    if scope_type is not None:
        where.append("scope_type = :scope_type")
        params["scope_type"] = scope_type.value
    if scope_id is not None:
        where.append("scope_id = :scope_id")
        params["scope_id"] = scope_id
    if type_ is not None:
        where.append("type = :type")
        params["type"] = type_.value
    if types is not None:
        where.append("type = ANY(:types)")
        params["types"] = [t.value for t in types]
    if subject_entity_id is not None:
        where.append("subject_entity_id = :subject_entity_id")
        params["subject_entity_id"] = subject_entity_id
    result = await conn.execute(
        text(
            f"SELECT {_MEMORY_COLUMNS} FROM memory WHERE {' AND '.join(where)} ORDER BY memory_id"
        ),
        params,
    )
    rows = [dict(r) for r in result.mappings().all()]
    refs = await _refs_for(conn, [r["memory_id"] for r in rows])
    return [_row_to_memory(r, refs.get(r["memory_id"], ())) for r in rows]


async def set_status(
    conn: AsyncConnection,
    memory_id: str,
    status: MemoryStatus,
    *,
    superseded_by: str | None = None,
) -> None:
    await conn.execute(
        text(
            "UPDATE memory SET status = :status, superseded_by = :superseded_by "
            "WHERE memory_id = :memory_id"
        ),
        {"memory_id": memory_id, "status": status.value, "superseded_by": superseded_by},
    )


async def record_confirmation(conn: AsyncConnection, memory_id: str, *, trust_grade: int) -> None:
    """A restatement confirmed the record: counter up, freshness reset, trust raised (capped
    by the caller)."""
    await conn.execute(
        text(
            "UPDATE memory SET confirmation_count = confirmation_count + 1, "
            "last_confirmed_at = now(), cycles_since_confirmed = 0, trust_grade = :trust_grade "
            "WHERE memory_id = :memory_id"
        ),
        {"memory_id": memory_id, "trust_grade": trust_grade},
    )


async def set_trust(conn: AsyncConnection, memory_id: str, trust_grade: int) -> None:
    await conn.execute(
        text("UPDATE memory SET trust_grade = :trust_grade WHERE memory_id = :memory_id"),
        {"memory_id": memory_id, "trust_grade": trust_grade},
    )


async def redact_content(conn: AsyncConnection, memory_id: str, sentinel: str) -> None:
    """DSAR tombstoning's content redaction (the sanctioned mutation): body/trigger to the
    sentinel, quote dropped, refs severed."""
    await conn.execute(
        text(
            "UPDATE memory SET body = :sentinel, trigger = :sentinel, creating_quote = NULL "
            "WHERE memory_id = :memory_id"
        ),
        {"memory_id": memory_id, "sentinel": sentinel},
    )
    await conn.execute(
        text("DELETE FROM memory_claim_ref WHERE memory_id = :memory_id"),
        {"memory_id": memory_id},
    )


async def increment_cycles(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    scope_type: MemoryScopeType,
    scope_id: str,
) -> list[str]:
    """Age one scope instance's live records by one kickoff cycle (Doc M §12); returns the
    affected ids for journaling. Dormant records age too — their staleness keeps computing."""
    result = await conn.execute(
        text(
            "UPDATE memory SET cycles_since_confirmed = cycles_since_confirmed + 1 "
            "WHERE workspace_id = :workspace_id AND scope_type = :scope_type "
            "AND scope_id = :scope_id AND status = ANY(:statuses) RETURNING memory_id"
        ),
        {
            "workspace_id": workspace_id,
            "scope_type": scope_type.value,
            "scope_id": scope_id,
            "statuses": [MemoryStatus.ACTIVE.value, MemoryStatus.DORMANT.value],
        },
    )
    return [row[0] for row in result.all()]


async def insert_event(
    conn: AsyncConnection,
    *,
    memory_id: str,
    workspace_id: str,
    event_type: MemoryEventType,
    actor: str,
    from_status: MemoryStatus | None = None,
    to_status: MemoryStatus | None = None,
    cause: str | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO memory_event (memory_id, workspace_id, event_type, from_status, "
            "to_status, actor, cause) VALUES (:memory_id, :workspace_id, :event_type, "
            ":from_status, :to_status, :actor, :cause)"
        ),
        {
            "memory_id": memory_id,
            "workspace_id": workspace_id,
            "event_type": event_type.value,
            "from_status": from_status.value if from_status else None,
            "to_status": to_status.value if to_status else None,
            "actor": actor,
            "cause": cause,
        },
    )


async def list_events(conn: AsyncConnection, memory_id: str) -> list[dict[str, Any]]:
    result = await conn.execute(
        text(
            "SELECT event_type, from_status, to_status, actor, cause, created_at "
            "FROM memory_event WHERE memory_id = :memory_id ORDER BY created_at, event_type"
        ),
        {"memory_id": memory_id},
    )
    return [dict(r) for r in result.mappings().all()]


async def insert_bundle_journal(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    recipe: str,
    requested_types: str,
    scope_stack: str,
    included: str,
    excluded: str,
    cross_branch_pairs: str,
    bundle_hash: str,
) -> str:
    result = await conn.execute(
        text(
            "INSERT INTO memory_bundle_journal (workspace_id, recipe, requested_types, "
            "scope_stack, included, excluded, cross_branch_pairs, bundle_hash) "
            "VALUES (:workspace_id, :recipe, CAST(:requested_types AS jsonb), "
            "CAST(:scope_stack AS jsonb), CAST(:included AS jsonb), CAST(:excluded AS jsonb), "
            "CAST(:cross_branch_pairs AS jsonb), :bundle_hash) RETURNING journal_id"
        ),
        {
            "workspace_id": workspace_id,
            "recipe": recipe,
            "requested_types": requested_types,
            "scope_stack": scope_stack,
            "included": included,
            "excluded": excluded,
            "cross_branch_pairs": cross_branch_pairs,
            "bundle_hash": bundle_hash,
        },
    )
    return str(result.scalar_one())


async def get_bundle_journal(conn: AsyncConnection, journal_id: str) -> dict[str, Any] | None:
    result = await conn.execute(
        text(
            "SELECT journal_id, workspace_id, recipe, requested_types, scope_stack, included, "
            "excluded, cross_branch_pairs, bundle_hash, created_at "
            "FROM memory_bundle_journal WHERE journal_id = :journal_id"
        ),
        {"journal_id": journal_id},
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


# --- kill-switch ------------------------------------------------------------


async def get_switch(conn: AsyncConnection, workspace_id: str) -> bool | None:
    """The workspace toggle; ``None`` = no row = never flipped (default: enabled)."""
    result = await conn.execute(
        text("SELECT enabled FROM memory_switch WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )
    row = result.first()
    return None if row is None else bool(row[0])


async def set_switch(conn: AsyncConnection, workspace_id: str, enabled: bool, actor: str) -> None:
    """Instant-effect toggle + the audit entry that makes 'memory was off' verifiable."""
    await conn.execute(
        text(
            "INSERT INTO memory_switch (workspace_id, enabled, updated_by) "
            "VALUES (:workspace_id, :enabled, :actor) "
            "ON CONFLICT (workspace_id) DO UPDATE "
            "SET enabled = :enabled, updated_at = now(), updated_by = :actor"
        ),
        {"workspace_id": workspace_id, "enabled": enabled, "actor": actor},
    )
    await conn.execute(
        text(
            "INSERT INTO memory_switch_audit (workspace_id, enabled, actor) "
            "VALUES (:workspace_id, :enabled, :actor)"
        ),
        {"workspace_id": workspace_id, "enabled": enabled, "actor": actor},
    )


async def list_switch_audit(conn: AsyncConnection, workspace_id: str) -> list[dict[str, Any]]:
    result = await conn.execute(
        text(
            "SELECT enabled, actor, created_at FROM memory_switch_audit "
            "WHERE workspace_id = :workspace_id ORDER BY created_at"
        ),
        {"workspace_id": workspace_id},
    )
    return [dict(r) for r in result.mappings().all()]
