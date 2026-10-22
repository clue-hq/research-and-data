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

from clue_obs import get_logger

if TYPE_CHECKING:
    from clue_api.crm.write_prepare import PreparedChange

log = get_logger("clue_api.crm.writes")

__all__ = [
    "Grant",
    "MEMBERSHIP_LINK_OBJECT",
    "WriteCounts",
    "WriteProposal",
    "clue_added_members",
    "clue_wrote_current_value",
    "forget_membership_link",
    "get_proposal",
    "proposal_counts",
    "proposal_linked_records",
    "membership_link_id",
    "record_membership_link",
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


@dataclass(frozen=True)
class WriteProposal:
    proposal_id: UUID
    workspace_id: str
    connection_id: UUID
    project_id: str
    thread_id: str
    turn_id: UUID
    status: str


@dataclass(frozen=True)
class WriteCounts:
    done: int
    failed: int
    #: Chosen changes Clue did not send (the record changed, or already held the value).
    skipped: int
    #: Changes the person did not tick on the card.
    not_chosen: int
    #: Chosen changes not yet sent.
    waiting: int
    #: Chosen changes closed because the CRM was reconnected or switched (also counted in
    #: ``skipped``, or in ``failed`` when sent but not confirmed).
    reconnected: int = 0


async def get_proposal(conn: AsyncConnection, *, proposal_id: UUID) -> WriteProposal | None:
    row = (
        await conn.execute(
            text(
                "SELECT proposal_id, workspace_id, connection_id, project_id, thread_id, turn_id, "
                "status FROM crm_write_proposal WHERE proposal_id = :id"
            ),
            {"id": proposal_id},
        )
    ).first()
    return None if row is None else WriteProposal(**dict(row._mapping))


async def proposal_counts(conn: AsyncConnection, *, proposal_id: UUID) -> WriteCounts:
    row = (
        await conn.execute(
            text(
                "SELECT count(*) FILTER (WHERE status = 'succeeded') AS done, "
                "count(*) FILTER (WHERE status = 'failed') AS failed, "
                "count(*) FILTER (WHERE status = 'skipped' AND selected) AS skipped, "
                "count(*) FILTER (WHERE NOT selected) AS not_chosen, "
                "count(*) FILTER (WHERE selected AND status NOT IN "
                "('succeeded', 'failed', 'skipped')) AS waiting, "
                "count(*) FILTER (WHERE selected AND status IN ('skipped', 'failed') "
                "AND failure_kind = 'connection_expired') AS reconnected "
                "FROM crm_write WHERE proposal_id = :id"
            ),
            {"id": proposal_id},
        )
    ).one()
    return WriteCounts(**{key: int(value) for key, value in row._mapping.items()})


async def proposal_created_records(
    conn: AsyncConnection, *, proposal_id: UUID
) -> list[tuple[str, str]]:
    """``(record_label, new CRM id)`` of each record — and each list or campaign — the proposal's
    succeeded creates made."""
    rows = await conn.execute(
        text(
            "SELECT record_label, record_ref FROM crm_write WHERE proposal_id = :id "
            "AND kind IN ('create_contact', 'create_company', 'list_create') "
            "AND status = 'succeeded' "
            "AND record_ref IS NOT NULL ORDER BY ordinal"
        ),
        {"id": proposal_id},
    )
    return [(str(row.record_label), str(row.record_ref)) for row in rows]


async def proposal_linked_records(conn: AsyncConnection, *, proposal_id: UUID) -> int:
    """How many existing CRM records the proposal's succeeded updates linked to their Clue
    entities (Task 6): links an update made, not ones that were there already."""
    count = await conn.scalar(
        text(
            "SELECT count(*) FROM crm_record_link l JOIN crm_write w "
            "ON w.write_id = l.created_by_write_id WHERE w.proposal_id = :id "
            "AND w.kind = 'field_update' AND w.status = 'succeeded' AND NOT l.created_by_clue "
            "AND l.clue_entity_id IS NOT NULL"
        ),
        {"id": proposal_id},
    )
    return int(count or 0)


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
                "reverses_write_id, scope_key, covered_by, selected, status, idempotency_key, "
                "source_claim_ids, clue_entity_id) "
                "VALUES (:write_id, :proposal_id, :workspace_id, :connection_id, :ordinal, :slug, "
                "CAST(:arguments AS jsonb), :kind, :object, :record_ref, :record_label, :field, "
                "CAST(:before AS jsonb), CAST(:after AS jsonb), :overwrites_person, :reason, "
                ":source_ref, :reverses_write_id, :scope_key, :covered_by, :selected, "
                "'proposed', :idempotency_key, CAST(:source_claim_ids AS uuid[]), "
                ":clue_entity_id)"
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
                # The change's own object: a HubSpot list holds companies or contacts.
                "object": change.parsed.object,
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
                # R-8.7: the claims the value came from, so an erasure can list what Clue wrote.
                "source_claim_ids": list(change.source_claim_ids),
                "clue_entity_id": change.clue_entity_id,
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
    never forgets that Clue created the record.

    A CRM record's link is never overwritten (Task 6 policy): a record already linked to another
    Clue entity keeps that entity, and the attempt is logged. One Clue entity may be linked to
    several records (through creates or finds); reads take its most recent link."""
    params: dict[str, Any] = {
        "workspace_id": workspace_id,
        "connection_id": connection_id,
        "crm_object": crm_object,
        "crm_id": crm_id,
        "clue_entity_id": clue_entity_id,
        "created_by_clue": created_by_clue,
        "created_by_write_id": created_by_write_id,
    }
    result = await conn.execute(
        text(
            "INSERT INTO crm_record_link (workspace_id, connection_id, crm_object, crm_id, "
            "clue_entity_id, created_by_clue, created_by_write_id) VALUES (:workspace_id, "
            ":connection_id, :crm_object, :crm_id, :clue_entity_id, :created_by_clue, "
            ":created_by_write_id) ON CONFLICT (connection_id, crm_object, crm_id) DO UPDATE SET "
            "clue_entity_id = COALESCE(crm_record_link.clue_entity_id, "
            "EXCLUDED.clue_entity_id), "
            "created_by_clue = crm_record_link.created_by_clue OR EXCLUDED.created_by_clue, "
            # The write that made the link: a link that already named its entity keeps
            # whatever it had (an update of an already-linked record links nothing new).
            "created_by_write_id = CASE WHEN crm_record_link.clue_entity_id IS NULL "
            "THEN COALESCE(crm_record_link.created_by_write_id, EXCLUDED.created_by_write_id) "
            "ELSE crm_record_link.created_by_write_id END "
            "RETURNING clue_entity_id"
        ),
        params,
    )
    kept = result.scalar_one()
    if clue_entity_id is not None and kept is not None and kept != clue_entity_id:
        log.warning(
            "crm.record_link.kept_existing_entity",
            connection_id=str(connection_id),
            crm_object=crm_object,
            crm_id=crm_id,
            kept=str(kept),
            offered=str(clue_entity_id),
        )


#: A list (HubSpot) or campaign (Salesforce) membership Clue added is remembered as a record link
#: of this object, its ``crm_id`` being :func:`membership_link_id`. Clue removes only members it
#: added itself (R-6.25 call 12), so a removal is proposed only when this link exists.
MEMBERSHIP_LINK_OBJECT = "list_member"


def membership_link_id(list_ref: str, record_ref: str) -> str:
    return f"{list_ref}:{record_ref}"


async def record_membership_link(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    connection_id: UUID,
    list_ref: str,
    record_ref: str,
    write_id: UUID | None,
) -> None:
    """Remember that Clue added this member to this list or campaign (the executor calls it
    when an add succeeds)."""
    await record_link(
        conn,
        workspace_id=workspace_id,
        connection_id=connection_id,
        crm_object=MEMBERSHIP_LINK_OBJECT,
        crm_id=membership_link_id(list_ref, record_ref),
        created_by_clue=True,
        created_by_write_id=write_id,
    )


async def forget_membership_link(
    conn: AsyncConnection, *, workspace_id: str, list_ref: str, record_ref: str
) -> None:
    """Forget that Clue added this member (the executor calls it when a removal succeeds), so it
    cannot be removed twice and a later add is tracked afresh. Any connection of the workspace:
    a removal proposed before a reconnect is sent on the new connection."""
    await conn.execute(
        text(
            "DELETE FROM crm_record_link WHERE workspace_id = :ws AND crm_object = :object "
            "AND crm_id = :crm_id"
        ),
        {
            "ws": workspace_id,
            "object": MEMBERSHIP_LINK_OBJECT,
            "crm_id": membership_link_id(list_ref, record_ref),
        },
    )


async def clue_added_members(
    conn: AsyncConnection,
    *,
    connection_id: UUID,
    pairs: Sequence[tuple[str, str]],
    project_id: str | None = None,
) -> set[tuple[str, str]]:
    """Which (list, record) memberships of this connection Clue added itself.

    With ``project_id``, only those a proposal of that project added: a list can serve several
    projects (R-11.11), and one project never removes a member another project added. The project
    is the one of the proposal whose write created the link; a link no write created belongs to
    no project.
    """
    wanted = {
        membership_link_id(list_ref, record): (list_ref, record) for list_ref, record in pairs
    }
    if not wanted:
        return set()
    project_clause = (
        ""
        if project_id is None
        else "AND EXISTS (SELECT 1 FROM crm_write w JOIN crm_write_proposal p "
        "ON p.proposal_id = w.proposal_id WHERE w.write_id = l.created_by_write_id "
        "AND p.project_id = :project_id) "
    )
    rows = await conn.execute(
        text(
            "SELECT l.crm_id FROM crm_record_link l WHERE l.connection_id = :connection_id "
            "AND l.crm_object = :object AND l.created_by_clue AND l.crm_id = ANY(:ids) "
            + project_clause
        ),
        {
            "connection_id": connection_id,
            "object": MEMBERSHIP_LINK_OBJECT,
            "ids": list(wanted),
            "project_id": project_id,
        },
    )
    return {wanted[crm_id] for (crm_id,) in rows}
