"""The CRM lists and campaigns Clue uses: rows in ``crm_list`` and ``crm_list_project``
(migration ``crm_lists``).

Spec: docs/superpowers/specs/crm-integration/ (Phase 3 plan, Task 2); ruling R-11.11 — Clue keeps
the ids of the lists (HubSpot) and campaigns (Salesforce) it uses itself, rather than asking the
CRM or the agent to remember them. A list is one row per connection and CRM id; it serves every
project linked to it. Membership is not kept here: each member Clue added is a ``list_member``
record link (:func:`clue_api.crm.writes.record_membership_link`). Every function writes through
the ``conn`` it is given and never commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

__all__ = [
    "CrmList",
    "link_project",
    "lists_for_project",
    "mark_gone",
    "store_list",
]

CrmListObject = Literal["company", "contact"]
CrmListKind = Literal["hubspot_list", "salesforce_campaign"]
LinkedBy = Literal["clue_created", "person_named"]

_FIELDS = (
    "list_id",
    "workspace_id",
    "connection_id",
    "provider",
    "crm_object",
    "crm_list_id",
    "name",
    "kind",
    "created_by_clue",
    "created_by_write_id",
    "gone_at",
    "created_at",
)
_COLUMNS = ", ".join(_FIELDS)
_LIST_COLUMNS = ", ".join(f"l.{field}" for field in _FIELDS)


@dataclass(frozen=True)
class CrmList:
    list_id: UUID
    workspace_id: str
    connection_id: UUID
    provider: str
    crm_object: str
    crm_list_id: str
    name: str
    kind: str
    created_by_clue: bool
    created_by_write_id: UUID | None
    gone_at: datetime | None
    created_at: datetime


async def store_list(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    connection_id: UUID,
    provider: str,
    crm_object: CrmListObject,
    crm_list_id: str,
    name: str,
    kind: CrmListKind,
    created_by_clue: bool,
    created_by_write_id: UUID | None,
    project_id: str,
) -> CrmList:
    """Keep a list of this connection and link it to ``project_id``. Storing it again returns the
    row already kept: its name is refreshed, it never forgets that Clue created it, and a list
    marked gone is offered again (it was found again, R-11.11)."""
    row = (
        await conn.execute(
            text(
                "INSERT INTO crm_list (list_id, workspace_id, connection_id, provider, "
                "crm_object, crm_list_id, name, kind, created_by_clue, created_by_write_id) "
                "VALUES (:list_id, :ws, :connection_id, :provider, :crm_object, :crm_list_id, "
                ":name, :kind, :created_by_clue, :created_by_write_id) "
                "ON CONFLICT (connection_id, crm_list_id) DO UPDATE SET name = EXCLUDED.name, "
                "gone_at = NULL, "
                "created_by_clue = crm_list.created_by_clue OR EXCLUDED.created_by_clue, "
                "created_by_write_id = COALESCE(crm_list.created_by_write_id, "
                f"EXCLUDED.created_by_write_id) RETURNING {_COLUMNS}"
            ),
            {
                "list_id": uuid4(),
                "ws": workspace_id,
                "connection_id": connection_id,
                "provider": provider,
                "crm_object": crm_object,
                "crm_list_id": crm_list_id,
                "name": name,
                "kind": kind,
                "created_by_clue": created_by_clue,
                "created_by_write_id": created_by_write_id,
            },
        )
    ).one()
    stored = CrmList(**row._mapping)
    await link_project(
        conn,
        list_id=stored.list_id,
        project_id=project_id,
        workspace_id=workspace_id,
        linked_by="clue_created" if created_by_clue else "person_named",
    )
    return stored


async def link_project(
    conn: AsyncConnection,
    *,
    list_id: UUID,
    project_id: str,
    workspace_id: str,
    linked_by: LinkedBy,
) -> None:
    """Link a kept list to a project; linking it again changes nothing."""
    await conn.execute(
        text(
            "INSERT INTO crm_list_project (list_id, project_id, workspace_id, linked_by) "
            "VALUES (:list_id, :project_id, :ws, :linked_by) "
            "ON CONFLICT (list_id, project_id) DO NOTHING"
        ),
        {"list_id": list_id, "project_id": project_id, "ws": workspace_id, "linked_by": linked_by},
    )


async def lists_for_project(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, connection_id: UUID
) -> list[CrmList]:
    """The lists of this connection the project uses, oldest first; a gone list is left out."""
    rows = await conn.execute(
        text(
            f"SELECT {_LIST_COLUMNS} "
            "FROM crm_list l JOIN crm_list_project p ON p.list_id = l.list_id "
            "WHERE p.project_id = :project_id AND p.workspace_id = :ws "
            "AND l.workspace_id = :ws AND l.connection_id = :connection_id "
            "AND l.gone_at IS NULL ORDER BY l.created_at, l.crm_list_id"
        ),
        {"project_id": project_id, "ws": workspace_id, "connection_id": connection_id},
    )
    return [CrmList(**row._mapping) for row in rows]


async def mark_gone(conn: AsyncConnection, *, connection_id: UUID, crm_list_id: str) -> None:
    """Remember that the CRM no longer has this list (it is kept, and no longer offered)."""
    await conn.execute(
        text(
            "UPDATE crm_list SET gone_at = now() WHERE connection_id = :connection_id "
            "AND crm_list_id = :crm_list_id AND gone_at IS NULL"
        ),
        {"connection_id": connection_id, "crm_list_id": crm_list_id},
    )
