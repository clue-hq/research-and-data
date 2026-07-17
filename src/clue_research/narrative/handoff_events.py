"""The ``handoff_event`` outbox — the durable emit/notify path to the content layer (M12.3).

When an account reaches the ``handoff`` phase (overview §2 / Doc C §4) the subsystem emits a durable
event carrying *enough to fetch the assembled object* — ``(campaign_run_id, account_entity_id,
icp_spec_version, icp_key, handoff_ref)`` — so a content-layer consumer can pull it (or be pushed to
via a :class:`~clue_research.narrative.publisher.HandoffPublisher`). The outbox row is the **durable
record of intent**, Postgres-backed (conventions §6); the optional push is best-effort on top of it.

This is a **one-directional** seam (research → content): nothing the content/design layer does ever
writes back through here into the claim store (substrate §5c — "never write-through it"). The only
writer is the research side recording that a handoff is ready.

Emission is **idempotent on ``(campaign_run_id, account_entity_id, icp_spec_version, icp_key)``**
(an
``ON CONFLICT DO NOTHING`` on the unique scope key) — re-entering the handoff phase, or a
crash-resume
of the campaign-run state machine, never double-emits (M12.3 AC; mirrors the campaign-phase
idempotency on ``(campaign_run, phase)``, Doc C §4 / M7.4). ``emit_handoff_event`` returns whether
the
row was *newly* inserted so the caller fires the push exactly once.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import CampaignRunId, EntityId, UtcDatetime


class HandoffEventStatus(StrEnum):
    """Delivery lifecycle of one ``handoff_event`` outbox row.

    * ``PENDING`` — emitted (durable); a pull consumer has not yet been served / a push not yet
      acknowledged.
    * ``DELIVERED`` — a push consumer acknowledged it (``delivered_at`` stamped) — the durable proof
      the content layer received the notification.
    * ``FAILED`` — a push attempt failed terminally; the row stays for retry/audit (the outbox is
      still the source of truth, so a puller can always fetch regardless).

    Stored as ``text`` + a DB ``CHECK`` (an operational delivery lifecycle, not a domain enum
    mirrored
    in ``core.enums``); :func:`_STATUSES` keeps the Python members and the CHECK aligned (drift
    test).
    """

    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


# The CHECK-constraint allow-list (kept == the enum by ``tests/narrative/test_handoff_events`` so a
# new member can never silently violate the column CHECK).
HANDOFF_EVENT_STATUSES: tuple[str, ...] = tuple(s.value for s in HandoffEventStatus)


def handoff_ref_for(account_entity_id: EntityId, icp_spec_version: int, icp_key: str = "") -> str:
    """The canonical fetch ref carried on an emitted event — the read-API path a consumer GETs to
    retrieve the assembled object (M12.3 ``GET /accounts/{id}/handoff``). ``icp_key`` is appended
    only
    for a multi-segment account (D5) so a single-segment ref stays clean."""
    ref = f"/accounts/{account_entity_id}/handoff?icp_spec_version={icp_spec_version}"
    if icp_key:
        ref += f"&icp_key={icp_key}"
    return ref


class HandoffEvent(BaseModel):
    """The emit payload — everything a consumer needs to fetch one assembled handoff (M12.3).

    ``workspace_id`` is the owning tenant (a consumer is served only its own events — substrate §2);
    ``handoff_ref`` is the read-API path (:func:`handoff_ref_for`); ``schema_version`` pins the
    ``AccountHandoff`` contract version at emit so a pinned consumer reads the right shape (AC5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_run_id: CampaignRunId
    account_entity_id: EntityId
    icp_spec_version: int
    icp_key: str = ""
    workspace_id: str
    handoff_ref: str
    schema_version: str


class HandoffEventRow(BaseModel):
    """A persisted ``handoff_event`` row — the :class:`HandoffEvent` payload + its delivery
    state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    campaign_run_id: CampaignRunId
    account_entity_id: EntityId
    icp_spec_version: int
    icp_key: str
    workspace_id: str
    handoff_ref: str
    schema_version: str
    status: HandoffEventStatus
    emitted_at: UtcDatetime
    delivered_at: UtcDatetime | None


_EVENT_COLUMNS = (
    "id, campaign_run_id, account_entity_id, icp_spec_version, icp_key, workspace_id, handoff_ref, "
    "schema_version, status, emitted_at, delivered_at"
)

_EMIT_SQL = text(
    """
    INSERT INTO handoff_event
        (id, campaign_run_id, account_entity_id, icp_spec_version, icp_key, workspace_id,
         handoff_ref, schema_version, status)
    VALUES
        (:id, :campaign_run_id, :account_entity_id, :icp_spec_version, :icp_key, :workspace_id,
         :handoff_ref, :schema_version, 'pending')
    ON CONFLICT (campaign_run_id, account_entity_id, icp_spec_version, icp_key) DO NOTHING
    """
)


async def emit_handoff_event(conn: AsyncConnection, event: HandoffEvent) -> bool:
    """Emit ``event`` to the durable outbox (idempotent on the
    ``(campaign_run_id, account_entity_id, icp_spec_version, icp_key)`` scope key).

    Returns ``True`` iff a new row was inserted — so the caller fires the optional push exactly once
    even across a re-entry / crash-resume (a duplicate emit returns ``False`` and is a no-op)."""
    result = await conn.execute(
        _EMIT_SQL,
        {
            "id": uuid4(),
            "campaign_run_id": event.campaign_run_id,
            "account_entity_id": str(event.account_entity_id),
            "icp_spec_version": event.icp_spec_version,
            "icp_key": event.icp_key,
            "workspace_id": event.workspace_id,
            "handoff_ref": event.handoff_ref,
            "schema_version": event.schema_version,
        },
    )
    return result.rowcount > 0


async def get_handoff_event(
    conn: AsyncConnection,
    *,
    campaign_run_id: CampaignRunId,
    account_entity_id: EntityId,
    icp_spec_version: int,
    icp_key: str = "",
    workspace_id: str,
) -> HandoffEventRow | None:
    """Read one outbox row by its scope key, tenant-scoped on ``workspace_id``, or ``None``."""
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_EVENT_COLUMNS} FROM handoff_event "
                    "WHERE campaign_run_id = :run AND account_entity_id = :account "
                    "AND icp_spec_version = :icp_spec_version AND icp_key = :icp_key "
                    "AND workspace_id = :workspace_id"
                ),
                {
                    "run": campaign_run_id,
                    "account": str(account_entity_id),
                    "icp_spec_version": icp_spec_version,
                    "icp_key": icp_key,
                    "workspace_id": workspace_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return _row_to_event(dict(row)) if row is not None else None


async def list_handoff_events(
    conn: AsyncConnection,
    *,
    campaign_run_id: CampaignRunId,
    workspace_id: str,
    status: HandoffEventStatus | None = None,
) -> list[HandoffEventRow]:
    """All outbox rows for a ``(campaign_run_id, workspace_id)`` (optionally filtered to one
    ``status``),
    oldest first — the pull surface a consumer polls. Tenant-scoped on ``workspace_id``."""
    status_clause = "AND status = CAST(:status AS text) " if status is not None else ""
    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_EVENT_COLUMNS} FROM handoff_event "
                    "WHERE campaign_run_id = :run AND workspace_id = :workspace_id "
                    f"{status_clause}"
                    "ORDER BY emitted_at, account_entity_id, icp_spec_version, icp_key"
                ),
                {
                    "run": campaign_run_id,
                    "workspace_id": workspace_id,
                    **({"status": status.value} if status is not None else {}),
                },
            )
        )
        .mappings()
        .all()
    )
    return [_row_to_event(dict(r)) for r in rows]


async def mark_handoff_event(
    conn: AsyncConnection, event_id: UUID, *, status: HandoffEventStatus
) -> None:
    """Set an outbox row's delivery ``status`` (push acknowledgement / failure). ``delivered_at`` is
    stamped in SQL iff the status is ``DELIVERED`` so the column CHECK (delivered_at iff delivered)
    can never be violated and the caller never supplies a timestamp."""
    await conn.execute(
        text(
            "UPDATE handoff_event "
            "SET status = CAST(:status AS text), "
            "    delivered_at = CASE WHEN :status = 'delivered' THEN now() ELSE NULL END "
            "WHERE id = :id"
        ),
        {"id": event_id, "status": status.value},
    )


def _row_to_event(row: dict[str, object]) -> HandoffEventRow:
    return HandoffEventRow.model_validate(
        {
            "id": row["id"],
            "campaign_run_id": row["campaign_run_id"],
            "account_entity_id": row["account_entity_id"],
            "icp_spec_version": row["icp_spec_version"],
            "icp_key": row["icp_key"],
            "workspace_id": row["workspace_id"],
            "handoff_ref": row["handoff_ref"],
            "schema_version": row["schema_version"],
            "status": row["status"],
            "emitted_at": row["emitted_at"],
            "delivered_at": row["delivered_at"],
        }
    )
