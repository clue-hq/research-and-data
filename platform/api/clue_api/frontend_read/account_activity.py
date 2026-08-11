"""FI-2 Slice 6 — durable Account activity for ``GET /accounts/{id}/activity``.

The Activity tab is a projection, not an event generator.  It reads the append-only
``research_subject_activity`` reference ledger and serves a row only when that reference resolves
back to the exact authoritative ``research_view_event`` plus its project, project run, and account
run.  There is intentionally no fallback to membership timestamps, fixture prose, or relative
"time ago" labels: an unresolved event is omitted rather than made to look durable.

The small ``state`` block is composed from :func:`read_account_detail`, so committee count and
summary state are literally the same governed committee and Lane-E synthesis reads used by the
Contacts and Overview/Insights journey.  Activity therefore cannot claim that a summary exists or
that a committee has a different size merely because its own adapter drifted.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read.account_detail import (
    AccountNotFound,
    read_account_detail,
)
from clue_api.frontend_read.accounts_list import WireModel
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.prose import ProseRead
from clue_db import ConnFactory

MAX_ACTIVITY_EVENTS = 100


class AccountActivityKind(StrEnum):
    """The complete durable event vocabulary this projection understands."""

    RESEARCH_VIEW_UPDATED = "research_view.updated"
    RESEARCH_VIEW_SECTION_STALE = "research_view.section_stale"
    RESEARCH_VIEW_RECHECK_COMPLETED = "research_view.recheck_completed"


class AccountActivityActorCategory(StrEnum):
    """Non-human actors that can be honestly attributed without an actor identity row.

    ``research_subject_activity`` also permits ``human``, but currently stores no human actor id.
    Such a row cannot satisfy this endpoint's actor contract and is therefore omitted until the
    durable source can resolve it to an actual principal.
    """

    SYSTEM = "system"
    AGENT = "agent"
    WORKER = "worker"


class AccountActivityState(WireModel):
    """Current cross-tab state, composed through the existing Account detail helpers."""

    committee_count: int
    summary: ProseRead


class AccountActivityProject(WireModel):
    """The durable project context resolved by the source event's foreign keys."""

    id: str
    name: str


class AccountActivityReference(WireModel):
    """Safe source identifiers plus the Account tab that can inspect the research view.

    ``fetch_ref`` is deliberately absent: it is an internal owner/storage reference, not a
    browser capability.  Report ids are nullable because initial view updates have no recheck
    report.
    """

    target: Literal["account_insights", "contact_profile"]
    event_id: uuid.UUID
    snapshot_id: uuid.UUID
    report_id: uuid.UUID | None = None
    section_ids: tuple[str, ...] = ()
    item_ids: tuple[str, ...] = ()


class AccountActivitySubject(WireModel):
    """The governed Account or committee Contact whose research view changed."""

    type: Literal["account", "contact"]
    id: uuid.UUID
    name: str | None = None


class AccountActivityEvent(WireModel):
    """One fully resolved append-only Account event."""

    id: uuid.UUID
    kind: AccountActivityKind
    occurred_at: datetime
    actor_category: AccountActivityActorCategory
    subject: AccountActivitySubject
    project: AccountActivityProject
    project_run_id: uuid.UUID
    account_run_id: uuid.UUID
    reference: AccountActivityReference


class AccountActivity(WireModel):
    """The Account activity read model, newest event first."""

    account_id: uuid.UUID
    state: AccountActivityState
    events: tuple[AccountActivityEvent, ...] = ()


_ACTIVITY_SQL = text(
    """
    SELECT activity.activity_id,
           activity.event_kind,
           activity.actor_category,
           activity.occurred_at,
           activity.subject_entity_id,
           activity.subject_entity_type,
           activity.project_id,
           project.name AS project_name,
           activity.project_run_id,
           activity.account_run_id,
           source_event.event_id,
           source_event.snapshot_id,
           source_event.report_id,
           source_event.section_ids,
           source_event.item_ids
    FROM research_subject_activity activity
    JOIN research_view_event source_event
      ON activity.owner_event_ref = 'research-view-event:' || source_event.event_id::text
     AND source_event.workspace_id = activity.workspace_id
     AND source_event.project_id = activity.project_id
     AND source_event.project_run_id = activity.project_run_id
     AND source_event.subject_entity_id = activity.subject_entity_id
     AND source_event.topic = activity.event_kind
     AND source_event.created_at = activity.occurred_at
    JOIN project
      ON project.project_id = activity.project_id
     AND project.workspace_id = activity.workspace_id
    JOIN project_run
      ON project_run.id = activity.project_run_id
     AND project_run.workspace_id = activity.workspace_id
     AND project_run.project_id = activity.project_id
    JOIN account_run
      ON account_run.id = activity.account_run_id
     AND account_run.project_run_id = activity.project_run_id
     AND account_run.entity_id = :account_id
    WHERE activity.workspace_id = :workspace_id
      AND (
          (
              activity.subject_entity_type = 'account'
              AND activity.subject_entity_id = :account_id
          )
          OR
          (
              activity.subject_entity_type = 'contact'
              AND activity.subject_entity_id = ANY(CAST(:contact_ids AS uuid[]))
          )
      )
      AND activity.event_kind IN (
          'research_view.updated',
          'research_view.section_stale',
          'research_view.recheck_completed'
      )
      AND activity.actor_category IN ('system', 'agent', 'worker')
    ORDER BY activity.occurred_at DESC, activity.activity_id DESC
    LIMIT :limit
    """
)


async def _read_events(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: uuid.UUID,
    account_name: str,
    contacts: dict[uuid.UUID, tuple[str | None, frozenset[str]]],
) -> tuple[AccountActivityEvent, ...]:
    rows = (
        await conn.execute(
            _ACTIVITY_SQL,
            {
                "workspace_id": workspace_id,
                "account_id": account_id,
                "contact_ids": [str(contact_id) for contact_id in contacts],
                "limit": MAX_ACTIVITY_EVENTS,
            },
        )
    ).mappings()
    events: list[AccountActivityEvent] = []
    for row in rows:
        subject_type = str(row["subject_entity_type"])
        subject_id = uuid.UUID(str(row["subject_entity_id"]))
        if subject_type == "account":
            subject = AccountActivitySubject(type="account", id=subject_id, name=account_name)
            target: Literal["account_insights", "contact_profile"] = "account_insights"
        else:
            contact = contacts.get(subject_id)
            # The contact must still be displayable in this Account's governed committee, and this
            # exact project must be one of the projects that selected it. A durable source event is
            # not, by itself, permission to expose the person through the Account UI.
            if contact is None or str(row["project_id"]) not in contact[1]:
                continue
            subject = AccountActivitySubject(type="contact", id=subject_id, name=contact[0])
            target = "contact_profile"
        events.append(
            AccountActivityEvent(
                id=row["activity_id"],
                kind=AccountActivityKind(row["event_kind"]),
                occurred_at=row["occurred_at"],
                actor_category=AccountActivityActorCategory(row["actor_category"]),
                subject=subject,
                project=AccountActivityProject(
                    id=row["project_id"],
                    name=row["project_name"],
                ),
                project_run_id=row["project_run_id"],
                account_run_id=row["account_run_id"],
                reference=AccountActivityReference(
                    target=target,
                    event_id=row["event_id"],
                    snapshot_id=row["snapshot_id"],
                    report_id=row["report_id"],
                    section_ids=tuple(row["section_ids"]),
                    item_ids=tuple(row["item_ids"]),
                ),
            )
        )
    return tuple(events)


async def read_account_activity(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: uuid.UUID,
) -> AccountActivity:
    """Compose current cross-tab state and fully resolvable durable events for one Account."""

    detail = await read_account_detail(
        conn,
        workspace_id=workspace_id,
        account_id=account_id,
    )
    contacts = {
        member.contact_id: (member.name, frozenset(member.project_ids))
        for member in detail.committee
    }
    events = await _read_events(
        conn,
        workspace_id=workspace_id,
        account_id=detail.id,
        account_name=detail.name,
        contacts=contacts,
    )
    return AccountActivity(
        account_id=detail.id,
        state=AccountActivityState(
            committee_count=len(detail.committee),
            summary=detail.summary,
        ),
        events=events,
    )


def register_account_activity_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
) -> None:
    """Register the durable Activity endpoint on the workspace-scoped read router."""

    @router.get("/accounts/{account_id}/activity")
    async def get_account_activity(
        workspace_id: WorkspaceDep,
        account_id: uuid.UUID,
    ) -> AccountActivity:
        async with conn_factory() as conn:
            try:
                return await read_account_activity(
                    conn,
                    workspace_id=workspace_id,
                    account_id=account_id,
                )
            except AccountNotFound as exc:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "ACCOUNT_NOT_FOUND",
                        "message": "no such account in this workspace",
                    },
                ) from exc


__all__ = [
    "AccountActivity",
    "AccountActivityActorCategory",
    "AccountActivityEvent",
    "AccountActivityKind",
    "AccountActivityReference",
    "AccountActivityState",
    "AccountActivitySubject",
    "read_account_activity",
    "register_account_activity_routes",
]
