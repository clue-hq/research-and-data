"""The CRM write log and standing permissions: rows in ``crm_write_proposal``, ``crm_write``,
``crm_write_grant`` and ``crm_record_link`` (migration ``ebf28e41a6a4``).

Spec: docs/superpowers/specs/crm-integration/ (Phase 2 plan, Task 4); rulings R-6.5 (an overwrite
always asks), R-6.7 (a standing permission covers one field of an object or one kind of change),
R-6.25 (call 11: when the CRM cannot tell who set a value, a person did). Every function writes
through the ``conn`` it is given and never commits.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

if TYPE_CHECKING:
    from clue_api.crm.write_prepare import PreparedChange

__all__ = [
    "Grant",
    "clue_wrote_current_value",
    "covering_grant",
    "grant_scope_key",
    "insert_grant",
    "insert_proposal",
    "insert_writes",
    "live_grants",
    "record_link",
    "revoke_grant",
    "same_value",
    "set_proposal_status",
]

FULLY_AUTOMATIC = "fully_automatic"
_ENDED = ("finished", "declined", "replaced")


@dataclass(frozen=True)
class Grant:
    grant_id: UUID
    scope_kind: str
    kind: str | None
    object: str | None
    field: str | None


# --- proposals and the write log ---------------------------------------------------------------


async def insert_proposal(
    conn: AsyncConnection,
    *,
    proposal_id: UUID,
    workspace_id: str,
    connection_id: UUID,
    project_id: str,
    thread_id: str,
    turn_id: UUID,
    status: str = "prepared",
) -> None:
    await conn.execute(
        text(
            "INSERT INTO crm_write_proposal (proposal_id, workspace_id, connection_id, "
            "project_id, thread_id, turn_id, status) VALUES (:proposal_id, :workspace_id, "
            ":connection_id, :project_id, :thread_id, :turn_id, :status)"
        ),
        {
            "proposal_id": proposal_id,
            "workspace_id": workspace_id,
            "connection_id": connection_id,
            "project_id": project_id,
            "thread_id": thread_id,
            "turn_id": turn_id,
            "status": status,
        },
    )


async def set_proposal_status(
    conn: AsyncConnection,
    *,
    proposal_id: UUID,
    status: str,
    gate_id: UUID | None = None,
    answered_by_user_id: str | None = None,
) -> None:
    """Move a proposal on; an answer stamps who and when, an ending stamps ``finished_at``."""
    await conn.execute(
        text(
            "UPDATE crm_write_proposal SET status = :status, "
            "gate_id = COALESCE(:gate_id, gate_id), "
            "answered_by_user_id = COALESCE(:answered_by, answered_by_user_id), "
            "answered_at = CASE WHEN CAST(:answered_by AS text) IS NULL THEN answered_at "
            "ELSE now() END, "
            "finished_at = CASE WHEN :ended THEN now() ELSE finished_at END "
            "WHERE proposal_id = :proposal_id"
        ),
        {
            "proposal_id": proposal_id,
            "status": status,
            "gate_id": gate_id,
            "answered_by": answered_by_user_id,
            "ended": status in _ENDED,
        },
    )


async def insert_writes(
    conn: AsyncConnection,
    *,
    proposal_id: UUID,
    workspace_id: str,
    connection_id: UUID,
    prepared: Sequence[PreparedChange],
) -> None:
    """Log the prepared changes in order, before anything is sent (R-7.1).

    A change is ticked unless it overwrites a value a person set (R-6.5: each one is approved
    explicitly).
    """
    for ordinal, change in enumerate(prepared):
        await conn.execute(
            text(
                "INSERT INTO crm_write (write_id, proposal_id, workspace_id, connection_id, "
                "ordinal, slug, arguments, kind, object, record_ref, record_label, field, "
                "before_value, after_value, overwrites_person, reason, source_ref, "
                "reverses_write_id, scope_key, covered_by, selected, status, idempotency_key) "
                "VALUES (:write_id, :proposal_id, :workspace_id, :connection_id, :ordinal, :slug, "
                "CAST(:arguments AS jsonb), :kind, :object, :record_ref, :record_label, :field, "
                "CAST(:before AS jsonb), CAST(:after AS jsonb), :overwrites_person, :reason, "
                ":source_ref, :reverses_write_id, :scope_key, :covered_by, :selected, "
                "'proposed', :idempotency_key)"
            ),
            {
                "write_id": change.write_id,
                "proposal_id": proposal_id,
                "workspace_id": workspace_id,
                "connection_id": connection_id,
                "ordinal": ordinal,
                "slug": change.spec.slug,
                "arguments": json.dumps(change.arguments, default=str),
                "kind": change.parsed.change_kind(change.spec),
                "object": change.spec.object,
                "record_ref": change.parsed.record_ref,
                "record_label": change.parsed.label,
                "field": change.field,
                "before": _json_or_null(change.before),
                "after": _json_or_null(change.after),
                "overwrites_person": change.overwrites_person,
                "reason": change.reason,
                "source_ref": change.source_ref,
                "reverses_write_id": change.reverses_write_id,
                "scope_key": change.scope_key,
                "covered_by": change.covered_by,
                "selected": not change.overwrites_person,
                "idempotency_key": f"crm_write:{change.write_id}",
            },
        )


def _json_or_null(value: object) -> str | None:
    return None if value is None else json.dumps(value, default=str)


def same_value(a: object, b: object) -> bool:
    """Whether two CRM values are the same: ``None`` and ``""`` are both empty, and HubSpot
    answers every value as a string (``"5"`` for 5, ``"true"`` for True)."""
    return _normal(a) == _normal(b)


def _normal(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, list | dict):
        return json.dumps(value, sort_keys=True, default=str)
    normal = str(value).strip()
    return normal or None


async def clue_wrote_current_value(
    conn: AsyncConnection, *, connection_id: UUID, record_ref: str, field: str, value: object
) -> bool:
    """Whether Clue itself set this record's field to exactly ``value`` (a succeeded write).

    Anything else counts as a person's value (R-6.25 call 11), so overwriting it always asks.
    """
    rows = await conn.execute(
        text(
            "SELECT after_value::text FROM crm_write WHERE connection_id = :connection_id "
            "AND record_ref = :record_ref AND field = :field AND status = 'succeeded'"
        ),
        {"connection_id": connection_id, "record_ref": record_ref, "field": field},
    )
    return any(same_value(None if after is None else json.loads(after), value) for (after,) in rows)


# --- standing permissions ------------------------------------------------------------------


def grant_scope_key(grant: Grant) -> str:
    """The :func:`~clue_api.crm.write_actions.scope_key` a grant covers."""
    if grant.scope_kind == "field":
        return f"field:{grant.object}.{grant.field}"
    if grant.scope_kind == "kind":
        return f"kind:{grant.kind}"
    return FULLY_AUTOMATIC


def _scope_columns(scope_key: str) -> dict[str, str | None]:
    if scope_key == FULLY_AUTOMATIC:
        return {"scope_kind": FULLY_AUTOMATIC, "kind": None, "object": None, "field": None}
    if scope_key.startswith("kind:"):
        return {"scope_kind": "kind", "kind": scope_key[5:], "object": None, "field": None}
    if scope_key.startswith("field:") and "." in scope_key:
        object_name, field = scope_key[6:].split(".", 1)
        return {
            "scope_kind": "field",
            "kind": "field_update",
            "object": object_name,
            "field": field,
        }
    raise ValueError(f"Not a write scope: {scope_key!r}.")


async def live_grants(conn: AsyncConnection, *, connection_id: UUID) -> list[Grant]:
    """The connection's standing permissions that are not revoked (R-6.25 calls 1, 8)."""
    rows = await conn.execute(
        text(
            "SELECT grant_id, scope_kind, kind, object, field FROM crm_write_grant "
            "WHERE connection_id = :connection_id AND revoked_at IS NULL ORDER BY granted_at"
        ),
        {"connection_id": connection_id},
    )
    return [Grant(**dict(row._mapping)) for row in rows]


def covering_grant(grants: Sequence[Grant], scope_key: str, kind: str) -> UUID | None:
    """The grant that covers a change of this scope and kind, if any.

    The caller never asks for an overwrite of a person's value: no grant covers one (R-6.5).
    """
    for grant in grants:
        if grant.scope_kind == FULLY_AUTOMATIC:
            return grant.grant_id
        if grant.scope_kind == "kind" and grant.kind == kind:
            return grant.grant_id
        if grant.scope_kind == "field" and grant_scope_key(grant) == scope_key:
            return grant.grant_id
    return None


async def insert_grant(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    connection_id: UUID,
    scope_key: str,
    granted_by_user_id: str,
) -> UUID:
    """Grant a standing permission; granting a scope already granted returns the live grant."""
    columns = _scope_columns(scope_key)
    await conn.execute(
        text(
            "INSERT INTO crm_write_grant (grant_id, workspace_id, connection_id, scope_kind, "
            "kind, object, field, granted_by_user_id) VALUES (:grant_id, :workspace_id, "
            ":connection_id, :scope_kind, :kind, :object, :field, :granted_by) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "grant_id": uuid4(),
            "workspace_id": workspace_id,
            "connection_id": connection_id,
            "granted_by": granted_by_user_id,
            **columns,
        },
    )
    row = await conn.execute(
        text(
            "SELECT grant_id FROM crm_write_grant WHERE connection_id = :connection_id "
            "AND scope_kind = :scope_kind AND kind IS NOT DISTINCT FROM :kind "
            "AND object IS NOT DISTINCT FROM :object AND field IS NOT DISTINCT FROM :field "
            "AND revoked_at IS NULL"
        ),
        {"connection_id": connection_id, **columns},
    )
    return UUID(str(row.scalar_one()))


async def revoke_grant(conn: AsyncConnection, *, grant_id: UUID, revoked_by_user_id: str) -> bool:
    """Revoke a live grant; ``False`` when it was already revoked or does not exist."""
    result = await conn.execute(
        text(
            "UPDATE crm_write_grant SET revoked_at = now(), revoked_by_user_id = :user "
            "WHERE grant_id = :grant_id AND revoked_at IS NULL"
        ),
        {"grant_id": grant_id, "user": revoked_by_user_id},
    )
    return bool(result.rowcount)


# --- record links --------------------------------------------------------------------------


async def record_link(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    connection_id: UUID,
    crm_object: str,
    crm_id: str,
    created_by_clue: bool,
    clue_entity_id: UUID | None = None,
    created_by_write_id: UUID | None = None,
) -> None:
    """Remember which CRM record a Clue entity is. A later link fills a missing entity id but
    never forgets that Clue created the record."""
    params: dict[str, Any] = {
        "workspace_id": workspace_id,
        "connection_id": connection_id,
        "crm_object": crm_object,
        "crm_id": crm_id,
        "clue_entity_id": clue_entity_id,
        "created_by_clue": created_by_clue,
        "created_by_write_id": created_by_write_id,
    }
    await conn.execute(
        text(
            "INSERT INTO crm_record_link (workspace_id, connection_id, crm_object, crm_id, "
            "clue_entity_id, created_by_clue, created_by_write_id) VALUES (:workspace_id, "
            ":connection_id, :crm_object, :crm_id, :clue_entity_id, :created_by_clue, "
            ":created_by_write_id) ON CONFLICT (connection_id, crm_object, crm_id) DO UPDATE SET "
            "clue_entity_id = COALESCE(crm_record_link.clue_entity_id, "
            "EXCLUDED.clue_entity_id), "
            "created_by_clue = crm_record_link.created_by_clue OR EXCLUDED.created_by_clue, "
            "created_by_write_id = COALESCE(crm_record_link.created_by_write_id, "
            "EXCLUDED.created_by_write_id)"
        ),
        params,
    )
