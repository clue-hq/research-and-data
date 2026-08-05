"""Unified durable stop authority for active selected-contact research operations.

Selection cancellation, an outreach objection, and erasure are different legal/product events, but
they share one execution invariant: no operation may materialize or serve new contact data after
the stop commits.  Append-only stop rows enforce that invariant without rewriting an already
charged provider receipt.  Work that was never dispatched is terminally cancelled in the same
transaction; dispatched work remains reconcilable but unusable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ContactChannelOperationId,
    ContactResearchSelectionId,
    EntityId,
    ExternalResearchOperationId,
    Sha256Hex,
    UtcDatetime,
)


class ContactResearchOperationControlError(RuntimeError):
    pass


class ContactResearchOperationStop(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stop_id: UUID
    operation_id: UUID
    workspace_id: str
    reason_code: str
    authority_ref: str
    created_at: UtcDatetime


class ContactResearchStopSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    external_operation_ids: tuple[ExternalResearchOperationId, ...] = ()
    channel_operation_ids: tuple[ContactChannelOperationId, ...] = ()


def _stop(row: object) -> ContactResearchOperationStop:
    data = dict(row._mapping)  # type: ignore[attr-defined]
    data["stop_id"] = data.pop("id")
    return ContactResearchOperationStop.model_validate(data)


async def bind_external_research_contact_authority(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ExternalResearchOperationId,
    selection_id: ContactResearchSelectionId,
    selection_sha256: Sha256Hex,
    contact_intent_sha256: Sha256Hex,
) -> None:
    """Bind one C4 operation to its exact active selection before the transaction commits."""

    row = (
        await conn.execute(
            text(
                "SELECT subject_kind::text, contact_id, contact_selection_id, "
                "contact_selection_sha256, contact_intent_sha256 "
                "FROM external_research_operation WHERE workspace_id=:workspace_id "
                "AND id=:operation_id FOR UPDATE"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).first()
    if row is None or row.subject_kind != "contact" or row.contact_id is None:
        raise ContactResearchOperationControlError(
            "contact authority can bind only an exact contact operation"
        )
    existing = (
        row.contact_selection_id,
        row.contact_selection_sha256,
        row.contact_intent_sha256,
    )
    requested = (selection_id, selection_sha256, contact_intent_sha256)
    if any(existing):
        if existing != requested:
            raise ContactResearchOperationControlError(
                "external contact operation is already bound to different authority"
            )
        return
    updated = await conn.execute(
        text(
            "UPDATE external_research_operation SET contact_selection_id=:selection_id, "
            "contact_selection_sha256=:selection_sha256, "
            "contact_intent_sha256=:intent_sha256 WHERE workspace_id=:workspace_id "
            "AND id=:operation_id"
        ),
        {
            "workspace_id": workspace_id,
            "operation_id": operation_id,
            "selection_id": selection_id,
            "selection_sha256": selection_sha256,
            "intent_sha256": contact_intent_sha256,
        },
    )
    if updated.rowcount != 1:  # pragma: no cover - row is locked above
        raise ContactResearchOperationControlError("contact authority binding disappeared")


async def external_research_operation_stop(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ExternalResearchOperationId,
) -> ContactResearchOperationStop | None:
    row = (
        await conn.execute(
            text(
                "SELECT id, operation_id, workspace_id, reason_code, authority_ref, created_at "
                "FROM external_research_operation_stop WHERE workspace_id=:workspace_id "
                "AND operation_id=:operation_id"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).first()
    return None if row is None else _stop(row)


async def contact_channel_operation_stop(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ContactChannelOperationId,
) -> ContactResearchOperationStop | None:
    row = (
        await conn.execute(
            text(
                "SELECT id, operation_id, workspace_id, reason_code, authority_ref, created_at "
                "FROM contact_channel_operation_stop WHERE workspace_id=:workspace_id "
                "AND operation_id=:operation_id"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).first()
    return None if row is None else _stop(row)


async def stop_contact_research_operations(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    contact_id: EntityId | None,
    reason_code: str,
    authority_ref: str,
    selection_id: ContactResearchSelectionId | None = None,
    channel_field_keys: frozenset[str] | None = None,
    stop_external: bool = True,
    now: datetime | None = None,
) -> ContactResearchStopSummary:
    """Stop all in-scope C4/C5 operations and cancel work proven not to have dispatched.

    ``selection_id`` is used by steering cancellation; ``contact_id`` plus optional channel fields
    is used by objection/erasure.  At least one exact authority dimension is required.
    """

    if contact_id is None and selection_id is None:
        raise ValueError("an operation stop requires a contact or selection")
    if not reason_code.strip() or not authority_ref.strip():
        raise ValueError("an operation stop requires non-empty reason and authority")
    stopped_at = now or datetime.now(UTC)
    if contact_id is not None:
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:subject_lock, 0))"),
            {"subject_lock": f"contact-research:{workspace_id}:{contact_id}"},
        )
    external_ids: tuple[ExternalResearchOperationId, ...] = ()
    if stop_external:
        external_filters = ""
        external_params: dict[str, object] = {"workspace_id": workspace_id}
        if contact_id is not None:
            external_filters += "AND contact_id=:contact_id "
            external_params["contact_id"] = contact_id
        if selection_id is not None:
            external_filters += "AND contact_selection_id=:selection_id "
            external_params["selection_id"] = selection_id
        external_rows = (
            await conn.execute(
                text(
                    "SELECT id FROM external_research_operation WHERE workspace_id=:workspace_id "
                    "AND subject_kind='contact' "
                    f"{external_filters}"
                    "ORDER BY id FOR UPDATE"
                ),
                external_params,
            )
        ).scalars()
        external_ids = tuple(ExternalResearchOperationId(value) for value in external_rows)
        for operation_id in external_ids:
            await conn.execute(
                text(
                    "INSERT INTO external_research_operation_stop "
                    "(id, operation_id, workspace_id, reason_code, authority_ref) VALUES "
                    "(:id, :operation_id, :workspace_id, :reason_code, :authority_ref) "
                    "ON CONFLICT (operation_id) DO NOTHING"
                ),
                {
                    "id": uuid4(),
                    "operation_id": operation_id,
                    "workspace_id": workspace_id,
                    "reason_code": reason_code,
                    "authority_ref": authority_ref,
                },
            )
        if external_ids:
            await conn.execute(
                text(
                    "UPDATE external_research_operation SET state='cancelled', "
                    "failure_code=:reason_code, terminal_at=:now, updated_at=:now "
                    "WHERE id = ANY(:operation_ids) AND state='planned' "
                    "AND spend_outcome='not_dispatched'"
                ),
                {
                    "operation_ids": list(external_ids),
                    "reason_code": reason_code,
                    "now": stopped_at,
                },
            )

    channel_params: dict[str, object] = {"workspace_id": workspace_id}
    channel_scope_sql = ""
    if contact_id is not None:
        channel_scope_sql += "AND contact_id=:contact_id "
        channel_params["contact_id"] = contact_id
    if selection_id is not None:
        channel_scope_sql += "AND selection_id=:selection_id "
        channel_params["selection_id"] = selection_id
    channel_field_sql = ""
    if channel_field_keys is not None:
        if not channel_field_keys:
            return ContactResearchStopSummary(external_operation_ids=external_ids)
        channel_field_sql = "AND field_key = ANY(:field_keys) "
        channel_params["field_keys"] = list(channel_field_keys)
    channel_rows = (
        await conn.execute(
            text(
                "SELECT id FROM contact_channel_operation WHERE workspace_id=:workspace_id "
                f"{channel_scope_sql}"
                f"{channel_field_sql}"
                "ORDER BY id FOR UPDATE"
            ),
            channel_params,
        )
    ).scalars()
    channel_ids = tuple(ContactChannelOperationId(value) for value in channel_rows)
    for channel_operation_id in channel_ids:
        await conn.execute(
            text(
                "INSERT INTO contact_channel_operation_stop "
                "(id, operation_id, workspace_id, reason_code, authority_ref) VALUES "
                "(:id, :operation_id, :workspace_id, :reason_code, :authority_ref) "
                "ON CONFLICT (operation_id) DO NOTHING"
            ),
            {
                "id": uuid4(),
                "operation_id": channel_operation_id,
                "workspace_id": workspace_id,
                "reason_code": reason_code,
                "authority_ref": authority_ref,
            },
        )
    if channel_ids:
        await conn.execute(
            text(
                "UPDATE contact_channel_operation SET state='cancelled', "
                "failure_code=:reason_code, next_poll_at=NULL, terminal_at=:now, updated_at=:now "
                "WHERE id = ANY(:operation_ids) AND ((state IN ('planned', 'failed_retryable') "
                "AND acquisition_spend_outcome='not_dispatched') OR "
                "(state='ready_to_validate' AND validation_spend_outcome='not_dispatched'))"
            ),
            {
                "operation_ids": list(channel_ids),
                "reason_code": reason_code,
                "now": stopped_at,
            },
        )
    return ContactResearchStopSummary(
        external_operation_ids=external_ids,
        channel_operation_ids=channel_ids,
    )


__all__ = [
    "ContactResearchOperationControlError",
    "ContactResearchOperationStop",
    "ContactResearchStopSummary",
    "bind_external_research_contact_authority",
    "contact_channel_operation_stop",
    "external_research_operation_stop",
    "stop_contact_research_operations",
]
