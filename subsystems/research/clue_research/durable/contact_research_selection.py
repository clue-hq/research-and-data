"""Immutable post-committee contact-research selections (M8C C6).

The receipt is action-scoped authority, not mutable orchestration state.  A successor is a new
row, cancellation is an append-only control row, and replay of the same content digest returns the
original receipt.  Provider adapters consume only the validated core model reconstructed here.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ContactResearchSelection,
    ContactResearchSelectionId,
    EntityId,
    ProjectRunId,
    ResearchDirectiveId,
    RunId,
)
from clue_research.durable.contact_research_control import stop_contact_research_operations


class ContactResearchSelectionRepositoryError(RuntimeError):
    pass


class ContactResearchSelectionNotFound(ContactResearchSelectionRepositoryError):
    pass


class ContactResearchSelectionReplayConflict(ContactResearchSelectionRepositoryError):
    pass


class ContactResearchSelectionApprovalKind(StrEnum):
    DIRECTIVE_CONFIRMATION = "directive_confirmation"
    HUMAN_SUCCESSOR = "human_successor"


class ContactResearchSelectionApprovalAuthority(BaseModel):
    """Trusted ambient approval captured by a platform service, never from selection inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ContactResearchSelectionApprovalKind
    operation_id: UUID
    approved_by: str
    action_ref: str
    approved_at: datetime


class ContactResearchSelectionCancellation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cancellation_id: UUID
    selection_id: ContactResearchSelectionId
    workspace_id: str
    cancelled_by: str
    reason_code: str
    created_at: datetime


def _selection(row: object) -> tuple[ContactResearchSelection, RunId]:
    data = dict(row._mapping)  # type: ignore[attr-defined]
    selection = ContactResearchSelection.model_validate(
        {
            "selection_id": data["id"],
            "body": data["body_json"],
            "selection_sha256": data["selection_sha256"],
        }
    )
    return selection, RunId(data["account_run_id"])


def _cancellation(row: object) -> ContactResearchSelectionCancellation:
    data = dict(row._mapping)  # type: ignore[attr-defined]
    data["cancellation_id"] = data.pop("id")
    return ContactResearchSelectionCancellation.model_validate(data)


_SELECTION_COLUMNS = "id, account_run_id, selection_sha256, body_json, predecessor_id, created_at"


async def directive_confirmation_selection_approval(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    directive_id: ResearchDirectiveId,
) -> ContactResearchSelectionApprovalAuthority:
    """Resolve the trusted human confirmation receipt for an initial automatic selection."""

    row = (
        await conn.execute(
            text(
                "SELECT confirmation_operation_id, confirmed_by, confirming_turn_ref, "
                "confirmed_at FROM account_research_directive WHERE workspace_id=:workspace_id "
                "AND directive_id=:directive_id AND status IN ('confirmed', 'superseded')"
            ),
            {"workspace_id": workspace_id, "directive_id": directive_id},
        )
    ).first()
    if row is None or any(
        value is None
        for value in (
            row.confirmation_operation_id,
            row.confirmed_by,
            row.confirming_turn_ref,
            row.confirmed_at,
        )
    ):
        raise ContactResearchSelectionRepositoryError(
            "initial contact selection requires a durable human directive confirmation"
        )
    return ContactResearchSelectionApprovalAuthority(
        kind=ContactResearchSelectionApprovalKind.DIRECTIVE_CONFIRMATION,
        operation_id=row.confirmation_operation_id,
        approved_by=row.confirmed_by,
        action_ref=row.confirming_turn_ref,
        approved_at=row.confirmed_at,
    )


async def store_contact_research_selection(
    conn: AsyncConnection,
    selection: ContactResearchSelection,
    *,
    account_run_id: RunId,
    approval: ContactResearchSelectionApprovalAuthority | None = None,
    predecessor_id: ContactResearchSelectionId | None = None,
) -> ContactResearchSelection:
    """Persist one approved selection or exact replay under a linear current-head lock."""

    body = selection.body
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope_lock, 0))"),
        {"scope_lock": (f"{body.workspace_id}:{body.project_run_id}:{body.account_entity_id}")},
    )
    existing_row = (
        await conn.execute(
            text(
                f"SELECT {_SELECTION_COLUMNS} FROM contact_research_selection "
                "WHERE workspace_id=:workspace_id AND project_run_id=:project_run_id "
                "AND account_id=:account_id AND selection_sha256=:selection_sha256"
            ),
            {
                "workspace_id": body.workspace_id,
                "project_run_id": body.project_run_id,
                "account_id": body.account_entity_id,
                "selection_sha256": selection.selection_sha256,
            },
        )
    ).first()
    if existing_row is not None:
        stored, stored_account_run_id = _selection(existing_row)
        if stored.body != body or stored_account_run_id != account_run_id:
            raise ContactResearchSelectionReplayConflict(
                "contact research selection digest was reused with different immutable authority"
            )
        return stored

    if approval is None:
        raise ContactResearchSelectionRepositoryError(
            "a new contact research selection requires trusted approval authority"
        )
    if approval.approved_by != body.approved_by or approval.approved_at != body.approved_at:
        raise ContactResearchSelectionRepositoryError(
            "selection body approval differs from trusted approval authority"
        )
    if (approval.kind is ContactResearchSelectionApprovalKind.DIRECTIVE_CONFIRMATION) != (
        predecessor_id is None
    ):
        raise ContactResearchSelectionRepositoryError(
            "only directive confirmation can approve an initial selection; "
            "a successor requires explicit human authority"
        )

    approval_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO contact_research_selection_approval (id, workspace_id, project_id, "
            "project_run_id, account_run_id, account_id, directive_id, directive_version, "
            "directive_sha256, selection_sha256, predecessor_id, authority_kind, "
            "approval_operation_id, approved_by, action_ref, approved_at) VALUES "
            "(:id, :workspace_id, :project_id, :project_run_id, :account_run_id, :account_id, "
            ":directive_id, :directive_version, :directive_sha256, :selection_sha256, "
            ":predecessor_id, :authority_kind, :approval_operation_id, :approved_by, "
            ":action_ref, :approved_at)"
        ),
        {
            "id": approval_id,
            "workspace_id": body.workspace_id,
            "project_id": body.project_id,
            "project_run_id": body.project_run_id,
            "account_run_id": account_run_id,
            "account_id": body.account_entity_id,
            "directive_id": body.research_directive.directive_id,
            "directive_version": body.research_directive.version,
            "directive_sha256": body.research_directive.canonical_json_sha256,
            "selection_sha256": selection.selection_sha256,
            "predecessor_id": predecessor_id,
            "authority_kind": approval.kind.value,
            "approval_operation_id": approval.operation_id,
            "approved_by": approval.approved_by,
            "action_ref": approval.action_ref,
            "approved_at": approval.approved_at,
        },
    )
    result = await conn.execute(
        text(
            "INSERT INTO contact_research_selection (id, workspace_id, project_id, "
            "project_run_id, account_run_id, account_id, directive_id, directive_version, "
            "directive_sha256, selection_sha256, body_json, predecessor_id, approval_id) VALUES "
            "(:id, :workspace_id, :project_id, :project_run_id, :account_run_id, :account_id, "
            ":directive_id, :directive_version, :directive_sha256, :selection_sha256, "
            "CAST(:body_json AS jsonb), :predecessor_id, :approval_id) ON CONFLICT "
            "(workspace_id, project_run_id, account_id, selection_sha256) DO NOTHING"
        ),
        {
            "id": selection.selection_id,
            "workspace_id": body.workspace_id,
            "project_id": body.project_id,
            "project_run_id": body.project_run_id,
            "account_run_id": account_run_id,
            "account_id": body.account_entity_id,
            "directive_id": body.research_directive.directive_id,
            "directive_version": body.research_directive.version,
            "directive_sha256": body.research_directive.canonical_json_sha256,
            "selection_sha256": selection.selection_sha256,
            "body_json": body.model_dump_json(),
            "predecessor_id": predecessor_id,
            "approval_id": approval_id,
        },
    )
    row = (
        await conn.execute(
            text(
                f"SELECT {_SELECTION_COLUMNS} FROM contact_research_selection "
                "WHERE workspace_id=:workspace_id AND project_run_id=:project_run_id "
                "AND account_id=:account_id AND selection_sha256=:selection_sha256"
            ),
            {
                "workspace_id": body.workspace_id,
                "project_run_id": body.project_run_id,
                "account_id": body.account_entity_id,
                "selection_sha256": selection.selection_sha256,
            },
        )
    ).first()
    if row is None:  # pragma: no cover - INSERT/SELECT share one transaction
        raise ContactResearchSelectionRepositoryError("selection insert was not readable")
    stored, stored_account_run_id = _selection(row)
    if (
        stored.selection_sha256 != selection.selection_sha256
        or stored.body != selection.body
        or stored_account_run_id != account_run_id
    ):
        raise ContactResearchSelectionReplayConflict(
            "contact research selection digest was reused with different immutable authority"
        )
    if result.rowcount == 0:
        # Content-addressed replay intentionally returns the elected first id.
        return stored
    if stored.selection_id != selection.selection_id:
        raise ContactResearchSelectionReplayConflict(
            "new contact research selection insert returned a different immutable id"
        )
    return stored


async def get_contact_research_selection(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    selection_id: ContactResearchSelectionId,
) -> ContactResearchSelection:
    row = (
        await conn.execute(
            text(
                f"SELECT {_SELECTION_COLUMNS} FROM contact_research_selection "
                "WHERE workspace_id=:workspace_id AND id=:selection_id"
            ),
            {"workspace_id": workspace_id, "selection_id": selection_id},
        )
    ).first()
    if row is None:
        raise ContactResearchSelectionNotFound(str(selection_id))
    return _selection(row)[0]


async def latest_contact_research_selection(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    account_id: EntityId,
    include_cancelled: bool = False,
) -> ContactResearchSelection | None:
    cancelled_sql = (
        ""
        if include_cancelled
        else "AND NOT EXISTS (SELECT 1 FROM contact_research_selection_cancellation cancel "
        "WHERE cancel.selection_id=selection.id)"
    )
    row = (
        await conn.execute(
            text(
                f"SELECT {_SELECTION_COLUMNS} FROM contact_research_selection selection "
                "WHERE selection.workspace_id=:workspace_id "
                "AND selection.project_run_id=:project_run_id "
                "AND selection.account_id=:account_id "
                "AND NOT EXISTS (SELECT 1 FROM contact_research_selection successor "
                "WHERE successor.predecessor_id=selection.id) "
                f"{cancelled_sql} LIMIT 1"
            ),
            {
                "workspace_id": workspace_id,
                "project_run_id": project_run_id,
                "account_id": account_id,
            },
        )
    ).first()
    return None if row is None else _selection(row)[0]


async def cancel_contact_research_selection(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    selection_id: ContactResearchSelectionId,
    cancelled_by: str,
    reason_code: str,
) -> ContactResearchSelectionCancellation:
    """Append one durable stop control; exact retries are idempotent, changes conflict."""

    locked = (
        await conn.execute(
            text(
                "SELECT id FROM contact_research_selection "
                "WHERE workspace_id=:workspace_id AND id=:selection_id FOR UPDATE"
            ),
            {"workspace_id": workspace_id, "selection_id": selection_id},
        )
    ).scalar_one_or_none()
    if locked is None:
        raise ContactResearchSelectionNotFound(str(selection_id))
    cancellation_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO contact_research_selection_cancellation "
            "(id, selection_id, workspace_id, cancelled_by, reason_code) VALUES "
            "(:id, :selection_id, :workspace_id, :cancelled_by, :reason_code) "
            "ON CONFLICT (selection_id) DO NOTHING"
        ),
        {
            "id": cancellation_id,
            "selection_id": selection_id,
            "workspace_id": workspace_id,
            "cancelled_by": cancelled_by,
            "reason_code": reason_code,
        },
    )
    row = (
        await conn.execute(
            text(
                "SELECT id, selection_id, workspace_id, cancelled_by, reason_code, created_at "
                "FROM contact_research_selection_cancellation WHERE selection_id=:selection_id"
            ),
            {"selection_id": selection_id},
        )
    ).first()
    if row is None:
        raise ContactResearchSelectionNotFound(str(selection_id))
    stored = _cancellation(row)
    if (
        stored.workspace_id != workspace_id
        or stored.cancelled_by != cancelled_by
        or stored.reason_code != reason_code
    ):
        raise ContactResearchSelectionReplayConflict(
            "contact research cancellation was replayed with different authority"
        )
    await stop_contact_research_operations(
        conn,
        workspace_id=workspace_id,
        contact_id=None,
        selection_id=selection_id,
        reason_code=f"selection_cancelled:{reason_code}",
        authority_ref=f"contact-research-selection-cancellation:{stored.cancellation_id}",
    )
    return stored


async def contact_research_selection_cancellation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    selection_id: ContactResearchSelectionId,
) -> ContactResearchSelectionCancellation | None:
    row = (
        await conn.execute(
            text(
                "SELECT id, selection_id, workspace_id, cancelled_by, reason_code, created_at "
                "FROM contact_research_selection_cancellation "
                "WHERE selection_id=:selection_id AND workspace_id=:workspace_id"
            ),
            {"selection_id": selection_id, "workspace_id": workspace_id},
        )
    ).first()
    return None if row is None else _cancellation(row)


__all__ = [
    "ContactResearchSelectionApprovalAuthority",
    "ContactResearchSelectionApprovalKind",
    "ContactResearchSelectionCancellation",
    "ContactResearchSelectionNotFound",
    "ContactResearchSelectionReplayConflict",
    "ContactResearchSelectionRepositoryError",
    "cancel_contact_research_selection",
    "contact_research_selection_cancellation",
    "directive_confirmation_selection_approval",
    "get_contact_research_selection",
    "latest_contact_research_selection",
    "store_contact_research_selection",
]
