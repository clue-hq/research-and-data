"""Provider-neutral durable selected-contact channel ledger (M8C C5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ContactChannel,
    ContactChannelAcquisitionRequest,
    ContactChannelOperation,
    ContactChannelOperationId,
    ContactResearchSelectionId,
    EntityId,
    ProjectPhase,
    ProjectRunId,
    Sha256Hex,
    new_contact_channel_operation_id,
)
from clue_research.durable.provider_spend import (
    ProviderSpendGuardError,
    require_provider_spend_capacity,
)


class ContactChannelRepositoryError(RuntimeError):
    pass


class ContactChannelNotFound(ContactChannelRepositoryError):
    pass


class ContactChannelReplayConflict(ContactChannelRepositoryError):
    pass


class ContactChannelBudgetExceeded(ContactChannelRepositoryError):
    pass


@dataclass(frozen=True)
class ContactChannelAuthorizedOperation:
    """One validated source operation plus its exact-selection authorization receipt."""

    operation: ContactChannelOperation
    authorization_ref: str
    authorized_at: datetime
    reused: bool = False


_COLUMNS = (
    "id, workspace_id, project_id, project_run_id, account_id, contact_id, selection_id, "
    "selection_sha256, contact_intent_sha256, channel::text, field_key, "
    "acquisition_source_key, validation_source_key, observation_window, request_fingerprint, "
    "request_json, state::text, acquisition_spend_outcome::text, "
    "validation_spend_outcome::text, input_artifact_key, csv_artifact_key, provider_import_id, "
    "provider_operation_id, observed_claim_id, observation_artifact_key, "
    "validation_artifact_key, receipt_artifact_key, acquisition_units_charged, "
    "acquisition_cost_cents_charged, validation_units_charged, "
    "validation_cost_cents_charged, validation_json, next_poll_at, failure_code, started_at, "
    "terminal_at, created_at, updated_at"
)


def _operation(row: object) -> ContactChannelOperation:
    data = dict(row._mapping)  # type: ignore[attr-defined]
    request = ContactChannelAcquisitionRequest.model_validate(data.pop("request_json"))
    for key in (
        "workspace_id",
        "project_id",
        "project_run_id",
        "account_id",
        "contact_id",
        "selection_id",
        "selection_sha256",
        "contact_intent_sha256",
        "channel",
        "field_key",
        "acquisition_source_key",
        "validation_source_key",
        "observation_window",
    ):
        data.pop(key)
    data["operation_id"] = data.pop("id")
    data["request"] = request
    data["validation"] = data.pop("validation_json")
    return ContactChannelOperation.model_validate(data)


async def get_contact_channel_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ContactChannelOperationId,
    for_update: bool = False,
) -> ContactChannelOperation:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        await conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM contact_channel_operation "
                f"WHERE workspace_id=:workspace_id AND id=:operation_id{suffix}"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).first()
    if row is None:
        raise ContactChannelNotFound(str(operation_id))
    return _operation(row)


async def list_contact_channel_operations_for_contact(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    account_id: EntityId,
    contact_id: EntityId,
) -> tuple[ContactChannelOperation, ...]:
    """Read exact-run channel history for C7 coverage/delivery projection.

    The rows contain request and validation receipts but never the observed email/phone value.
    Newest rows are first so a projection can choose one current disposition per channel.
    """

    rows = (
        await conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM contact_channel_operation "
                "WHERE workspace_id=:workspace_id AND project_run_id=:project_run_id "
                "AND account_id=:account_id AND contact_id=:contact_id "
                "ORDER BY created_at DESC, id DESC"
            ),
            {
                "workspace_id": workspace_id,
                "project_run_id": project_run_id,
                "account_id": account_id,
                "contact_id": contact_id,
            },
        )
    ).all()
    return tuple(_operation(row) for row in rows)


async def list_contact_channel_operations_for_selection(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    account_id: EntityId,
    contact_id: EntityId,
    selection_id: ContactResearchSelectionId,
    selection_sha256: Sha256Hex,
) -> tuple[ContactChannelAuthorizedOperation, ...]:
    """Read only channel operations authorized by the exact current selection.

    A fresh result may be reused across observation windows or project runs, but C7 may expose it
    only through the immutable reuse receipt created for this exact selection. Merely finding an
    older successful operation for the same contact/channel is not delivery authority.
    """

    history = await list_contact_channel_operations_for_contact(
        conn,
        workspace_id=workspace_id,
        project_run_id=project_run_id,
        account_id=account_id,
        contact_id=contact_id,
    )
    authorized: list[ContactChannelAuthorizedOperation] = [
        ContactChannelAuthorizedOperation(
            operation=operation,
            authorization_ref=f"contact-channel-operation:{operation.operation_id}",
            authorized_at=operation.created_at or datetime.min.replace(tzinfo=UTC),
        )
        for operation in history
        if operation.request.selection_id == selection_id
        and operation.request.selection_sha256 == selection_sha256
    ]
    reuse_rows = (
        await conn.execute(
            text(
                "SELECT id, request_json, source_operation_id, created_at "
                "FROM contact_channel_reuse WHERE workspace_id=:workspace_id "
                "AND project_run_id=:project_run_id AND selection_id=:selection_id "
                "AND selection_sha256=:selection_sha256 ORDER BY created_at DESC, id DESC"
            ),
            {
                "workspace_id": workspace_id,
                "project_run_id": project_run_id,
                "selection_id": selection_id,
                "selection_sha256": selection_sha256,
            },
        )
    ).mappings()
    for row in reuse_rows:
        request = ContactChannelAcquisitionRequest.model_validate(row["request_json"])
        if (
            request.workspace_id != workspace_id
            or request.project_run_id != project_run_id
            or request.account_id != account_id
            or request.contact_id != contact_id
            or request.selection_id != selection_id
            or request.selection_sha256 != selection_sha256
        ):
            raise ContactChannelReplayConflict(
                "contact channel reuse receipt crosses its exact selection subject"
            )
        operation = await get_contact_channel_operation(
            conn,
            workspace_id=workspace_id,
            operation_id=row["source_operation_id"],
        )
        if (
            operation.request.account_id != account_id
            or operation.request.contact_id != contact_id
            or operation.request.channel is not request.channel
            or operation.request.field_key != request.field_key
            or operation.request.acquisition_source_key != request.acquisition_source_key
            or operation.request.validation_source_key != request.validation_source_key
        ):
            raise ContactChannelReplayConflict(
                "contact channel reuse receipt differs from its validated source operation"
            )
        authorized.append(
            ContactChannelAuthorizedOperation(
                operation=operation,
                authorization_ref=(
                    f"contact-channel-reuse:{row['id']}:source:{operation.operation_id}"
                ),
                authorized_at=row["created_at"],
                reused=True,
            )
        )

    by_operation: dict[ContactChannelOperationId, ContactChannelAuthorizedOperation] = {}
    for item in authorized:
        previous = by_operation.get(item.operation.operation_id)
        if previous is None or (item.authorized_at, item.reused, item.authorization_ref) > (
            previous.authorized_at,
            previous.reused,
            previous.authorization_ref,
        ):
            by_operation[item.operation.operation_id] = item
    return tuple(
        sorted(
            by_operation.values(),
            key=lambda item: (item.authorized_at, item.reused, item.authorization_ref),
            reverse=True,
        )
    )


async def find_contact_channel_operation(
    conn: AsyncConnection,
    *,
    request: ContactChannelAcquisitionRequest,
) -> ContactChannelOperation | None:
    row = (
        await conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM contact_channel_operation "
                "WHERE workspace_id=:workspace_id "
                "AND acquisition_source_key=:source_key "
                "AND request_fingerprint=:fingerprint "
                "AND observation_window=:window"
            ),
            {
                "workspace_id": request.workspace_id,
                "source_key": request.acquisition_source_key,
                "fingerprint": request.request_fingerprint,
                "window": request.observation_window,
            },
        )
    ).first()
    return None if row is None else _operation(row)


async def list_due_contact_channel_project_runs(
    conn: AsyncConnection,
    *,
    now: datetime,
    limit: int = 100,
) -> tuple[ProjectRunId, ...]:
    """Return owning runs for due C5 polls/validation recovery; never call a provider here."""

    if limit < 1:
        raise ValueError("contact channel due-run limit must be positive")
    rows = (
        await conn.execute(
            text(
                "SELECT project_run_id, min(next_poll_at) AS due_at "
                "FROM contact_channel_operation WHERE next_poll_at IS NOT NULL "
                "AND next_poll_at <= :now AND state IN "
                "('waiting_external', 'ready_to_validate', 'validating', 'failed_retryable') "
                "GROUP BY project_run_id ORDER BY due_at, project_run_id LIMIT :limit"
            ),
            {"now": now, "limit": limit},
        )
    ).all()
    return tuple(ProjectRunId(row.project_run_id) for row in rows)


async def find_fresh_reusable_contact_channel_operation(
    conn: AsyncConnection,
    *,
    request: ContactChannelAcquisitionRequest,
    now: datetime,
) -> ContactChannelOperation | None:
    """Find a still-usable validated result for the exact contact/channel policy contract."""

    row = (
        await conn.execute(
            text(
                f"""
                SELECT {_COLUMNS}
                FROM contact_channel_operation operation
                WHERE operation.workspace_id=:workspace_id
                  AND operation.account_id=:account_id
                  AND operation.contact_id=:contact_id
                  AND operation.channel=CAST(:channel AS contact_channel_kind)
                  AND operation.field_key=:field_key
                  AND operation.acquisition_source_key=:acquisition_source_key
                  AND operation.validation_source_key=:validation_source_key
                  AND operation.state='succeeded'
                  AND NOT EXISTS (
                      SELECT 1 FROM contact_channel_operation_stop stop
                      WHERE stop.operation_id=operation.id
                  )
                  AND operation.request_json->>'provider_contract_version'=
                      :provider_contract_version
                  AND operation.request_json->>'validation_contract_version'=
                      :validation_contract_version
                  AND operation.request_json->>'pricing_policy_version'=:pricing_policy_version
                  AND operation.request_json->>'effective_policy_sha256'=
                      :effective_policy_sha256
                  AND operation.request_json->>'canonical_profile_url'=:canonical_profile_url
                  AND operation.terminal_at
                      + make_interval(secs =>
                          (operation.request_json->>'freshness_seconds')::integer) > :now
                  AND operation.terminal_at
                      + make_interval(secs =>
                          (operation.request_json->>'retention_seconds')::integer) > :now
                  AND NOT EXISTS (
                      SELECT 1 FROM contact_channel_suppression suppression
                      WHERE suppression.workspace_id=operation.workspace_id
                        AND suppression.contact_id=operation.contact_id
                        AND suppression.channel=operation.channel
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM outreach_objected objection
                      WHERE objection.workspace_id=operation.workspace_id
                        AND objection.contact_entity_id=operation.contact_id
                  )
                ORDER BY operation.terminal_at DESC, operation.id
                LIMIT 1
                """
            ),
            {
                "workspace_id": request.workspace_id,
                "account_id": request.account_id,
                "contact_id": request.contact_id,
                "channel": request.channel.value,
                "field_key": request.field_key,
                "acquisition_source_key": request.acquisition_source_key,
                "validation_source_key": request.validation_source_key,
                "provider_contract_version": request.provider_contract_version,
                "validation_contract_version": request.validation_contract_version,
                "pricing_policy_version": request.pricing_policy_version,
                "effective_policy_sha256": request.effective_policy_sha256,
                "canonical_profile_url": request.canonical_profile_url,
                "now": now,
            },
        )
    ).first()
    return None if row is None else _operation(row)


async def record_contact_channel_reuse(
    conn: AsyncConnection,
    *,
    request: ContactChannelAcquisitionRequest,
    source_operation: ContactChannelOperation,
) -> None:
    """Append an authorization-scoped receipt for reuse without provider or validator spend."""

    result = await conn.execute(
        text(
            "INSERT INTO contact_channel_reuse (workspace_id, project_id, project_run_id, "
            "selection_id, selection_sha256, request_fingerprint, observation_window, "
            "request_json, source_operation_id) VALUES (:workspace_id, :project_id, "
            ":project_run_id, :selection_id, :selection_sha256, :request_fingerprint, "
            ":observation_window, CAST(:request_json AS jsonb), :source_operation_id) "
            "ON CONFLICT (workspace_id, request_fingerprint) DO NOTHING"
        ),
        {
            "workspace_id": request.workspace_id,
            "project_id": request.project_id,
            "project_run_id": request.project_run_id,
            "selection_id": request.selection_id,
            "selection_sha256": request.selection_sha256,
            "request_fingerprint": request.request_fingerprint,
            "observation_window": request.observation_window,
            "request_json": request.model_dump_json(),
            "source_operation_id": source_operation.operation_id,
        },
    )
    if result.rowcount == 0:
        existing = (
            await conn.execute(
                text(
                    "SELECT source_operation_id FROM contact_channel_reuse "
                    "WHERE workspace_id=:workspace_id AND request_fingerprint=:fingerprint"
                ),
                {
                    "workspace_id": request.workspace_id,
                    "fingerprint": request.request_fingerprint,
                },
            )
        ).scalar_one()
        if existing != source_operation.operation_id:
            raise ContactChannelReplayConflict(
                "contact channel reuse fingerprint points at another source operation"
            )


def _assert_replay(
    stored: ContactChannelOperation,
    request: ContactChannelAcquisitionRequest,
    *,
    input_artifact_key: str,
    csv_artifact_key: str,
) -> None:
    if (
        stored.request != request
        or stored.request_fingerprint != request.request_fingerprint
        or stored.input_artifact_key != input_artifact_key
        or stored.csv_artifact_key != csv_artifact_key
    ):
        raise ContactChannelReplayConflict(
            "contact channel fingerprint reused with different immutable content"
        )


async def reserve_contact_channel_operation(
    conn: AsyncConnection,
    *,
    request: ContactChannelAcquisitionRequest,
    input_artifact_key: str,
    csv_artifact_key: str,
) -> tuple[ContactChannelOperation, bool]:
    """Atomically reserve both channel and validator budgets for one exact receipt."""

    existing = await find_contact_channel_operation(conn, request=request)
    if existing is not None:
        _assert_replay(
            existing,
            request,
            input_artifact_key=input_artifact_key,
            csv_artifact_key=csv_artifact_key,
        )
        return existing, False
    total = request.acquisition_budget_cap_cents + request.validation_budget_cap_cents
    try:
        await require_provider_spend_capacity(
            conn,
            project_run_id=request.project_run_id,
            proposed_cents=total,
            allowed_phases=frozenset({ProjectPhase.DEEP}),
        )
    except ProviderSpendGuardError as exc:
        raise ContactChannelBudgetExceeded(str(exc)) from exc
    # The run lock above serializes competing reservations. Recheck after taking it so a replay
    # that raced the initial read never consumes a second reservation.
    existing = await find_contact_channel_operation(conn, request=request)
    if existing is not None:
        _assert_replay(
            existing,
            request,
            input_artifact_key=input_artifact_key,
            csv_artifact_key=csv_artifact_key,
        )
        return existing, False
    operation_id = new_contact_channel_operation_id()
    inserted = await conn.execute(
        text(
            """
            INSERT INTO contact_channel_operation (
                id, workspace_id, project_id, project_run_id, account_id, contact_id,
                selection_id, selection_sha256, contact_intent_sha256, channel, field_key,
                acquisition_source_key, validation_source_key, observation_window,
                request_fingerprint, request_json, provider_external_id, state,
                acquisition_spend_outcome, validation_spend_outcome,
                input_artifact_key, csv_artifact_key
            ) VALUES (
                :id, :workspace_id, :project_id, :project_run_id, :account_id, :contact_id,
                :selection_id, :selection_sha256, :intent_sha256,
                CAST(:channel AS contact_channel_kind), :field_key, :acquisition_source_key,
                :validation_source_key, :window, :fingerprint, CAST(:request_json AS jsonb),
                :external_id, 'planned', 'not_dispatched', 'not_dispatched', :input_key, :csv_key
            ) ON CONFLICT (
                workspace_id, acquisition_source_key, request_fingerprint, observation_window
            ) DO NOTHING RETURNING id
            """
        ),
        {
            "id": operation_id,
            "workspace_id": request.workspace_id,
            "project_id": request.project_id,
            "project_run_id": request.project_run_id,
            "account_id": request.account_id,
            "contact_id": request.contact_id,
            "selection_id": request.selection_id,
            "selection_sha256": request.selection_sha256,
            "intent_sha256": request.contact_intent_sha256,
            "channel": request.channel.value,
            "field_key": request.field_key,
            "acquisition_source_key": request.acquisition_source_key,
            "validation_source_key": request.validation_source_key,
            "window": request.observation_window,
            "fingerprint": request.request_fingerprint,
            "request_json": request.model_dump_json(),
            "external_id": request.provider_external_id,
            "input_key": input_artifact_key,
            "csv_key": csv_artifact_key,
        },
    )
    created = inserted.scalar_one_or_none() is not None
    stored = await find_contact_channel_operation(conn, request=request)
    if stored is None:
        raise ContactChannelNotFound("reserved contact channel operation")
    _assert_replay(
        stored,
        request,
        input_artifact_key=input_artifact_key,
        csv_artifact_key=csv_artifact_key,
    )
    return stored, created


async def claim_contact_channel_submit(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ContactChannelOperationId,
    now: datetime,
) -> ContactChannelOperation | None:
    row = (
        await conn.execute(
            text(
                "UPDATE contact_channel_operation SET state='submitting', started_at=:now "
                "WHERE workspace_id=:workspace_id AND id=:operation_id AND state IN "
                "('planned', 'failed_retryable') AND NOT EXISTS (SELECT 1 FROM "
                "contact_channel_operation_stop stop WHERE stop.operation_id="
                "contact_channel_operation.id) RETURNING id"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id, "now": now},
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return await get_contact_channel_operation(
        conn, workspace_id=workspace_id, operation_id=operation_id
    )


async def claim_contact_channel_validation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ContactChannelOperationId,
    now: datetime,
    lease_until: datetime,
) -> ContactChannelOperation | None:
    """Lease one ready observation immediately before the possibly-paid validator dispatch."""

    row = (
        await conn.execute(
            text(
                "UPDATE contact_channel_operation SET state='validating', started_at=:now, "
                "next_poll_at=:lease_until, validation_spend_outcome='unknown' "
                "WHERE workspace_id=:workspace_id AND id=:operation_id "
                "AND state='ready_to_validate' AND NOT EXISTS (SELECT 1 FROM "
                "contact_channel_operation_stop stop WHERE stop.operation_id="
                "contact_channel_operation.id) RETURNING id"
            ),
            {
                "workspace_id": workspace_id,
                "operation_id": operation_id,
                "now": now,
                "lease_until": lease_until,
            },
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return await get_contact_channel_operation(
        conn, workspace_id=workspace_id, operation_id=operation_id
    )


async def update_contact_channel_operation(
    conn: AsyncConnection,
    *,
    operation: ContactChannelOperation,
) -> ContactChannelOperation:
    request = operation.request
    await conn.execute(
        text(
            """
            UPDATE contact_channel_operation SET
                state=CAST(:state AS contact_channel_operation_state),
                acquisition_spend_outcome=CAST(:acquisition_spend AS contact_channel_spend_outcome),
                validation_spend_outcome=CAST(:validation_spend AS contact_channel_spend_outcome),
                provider_import_id=:import_id, provider_operation_id=:provider_operation_id,
                observed_claim_id=:observed_claim_id,
                observation_artifact_key=:observation_artifact_key,
                validation_artifact_key=:validation_artifact_key,
                receipt_artifact_key=:receipt_artifact_key,
                acquisition_units_charged=:acquisition_units,
                acquisition_cost_cents_charged=:acquisition_cost,
                validation_units_charged=:validation_units,
                validation_cost_cents_charged=:validation_cost,
                validation_json=CAST(:validation_json AS jsonb), next_poll_at=:next_poll_at,
                failure_code=:failure_code, started_at=:started_at, terminal_at=:terminal_at
            WHERE workspace_id=:workspace_id AND id=:operation_id
            """
        ),
        {
            "workspace_id": request.workspace_id,
            "operation_id": operation.operation_id,
            "state": operation.state.value,
            "acquisition_spend": operation.acquisition_spend_outcome.value,
            "validation_spend": operation.validation_spend_outcome.value,
            "import_id": operation.provider_import_id,
            "provider_operation_id": operation.provider_operation_id,
            "observed_claim_id": operation.observed_claim_id,
            "observation_artifact_key": operation.observation_artifact_key,
            "validation_artifact_key": operation.validation_artifact_key,
            "receipt_artifact_key": operation.receipt_artifact_key,
            "acquisition_units": operation.acquisition_units_charged,
            "acquisition_cost": operation.acquisition_cost_cents_charged,
            "validation_units": operation.validation_units_charged,
            "validation_cost": operation.validation_cost_cents_charged,
            "validation_json": (
                None if operation.validation is None else operation.validation.model_dump_json()
            ),
            "next_poll_at": operation.next_poll_at,
            "failure_code": operation.failure_code,
            "started_at": operation.started_at,
            "terminal_at": operation.terminal_at,
        },
    )
    return await get_contact_channel_operation(
        conn,
        workspace_id=request.workspace_id,
        operation_id=operation.operation_id,
    )


async def append_contact_channel_artifact(
    conn: AsyncConnection,
    *,
    operation: ContactChannelOperation,
    artifact_kind: str,
    artifact_key: str,
    content_sha256: str,
    provider_request_id: str | None = None,
) -> int:
    ordinal = int(
        (
            await conn.execute(
                text(
                    "SELECT COALESCE(max(ordinal), -1) + 1 FROM contact_channel_artifact "
                    "WHERE operation_id=:operation_id"
                ),
                {"operation_id": operation.operation_id},
            )
        ).scalar_one()
    )
    await conn.execute(
        text(
            "INSERT INTO contact_channel_artifact (operation_id, workspace_id, ordinal, "
            "artifact_kind, artifact_key, content_sha256, provider_request_id) VALUES "
            "(:operation_id, :workspace_id, :ordinal, :kind, :key, :sha, :request_id)"
        ),
        {
            "operation_id": operation.operation_id,
            "workspace_id": operation.request.workspace_id,
            "ordinal": ordinal,
            "kind": artifact_kind,
            "key": artifact_key,
            "sha": content_sha256,
            "request_id": provider_request_id,
        },
    )
    return ordinal


async def suppress_contact_channels(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    contact_id: EntityId,
    reason: str,
    channels: tuple[ContactChannel, ...] = (ContactChannel.EMAIL, ContactChannel.PHONE),
) -> None:
    for channel in channels:
        await conn.execute(
            text(
                "INSERT INTO contact_channel_suppression "
                "(workspace_id, contact_id, channel, reason) "
                "VALUES (:workspace_id, :contact_id, "
                "CAST(:channel AS contact_channel_kind), :reason) "
                "ON CONFLICT (workspace_id, contact_id, channel) "
                "DO UPDATE SET reason=EXCLUDED.reason"
            ),
            {
                "workspace_id": workspace_id,
                "contact_id": contact_id,
                "channel": channel.value,
                "reason": reason,
            },
        )


async def contact_channel_is_usable(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    contact_id: EntityId,
    channel: ContactChannel,
    now: datetime,
) -> bool:
    value = (
        await conn.execute(
            text(
                """
                SELECT 1 FROM contact_channel_operation operation
                WHERE operation.workspace_id=:workspace_id
                  AND operation.contact_id=:contact_id
                  AND operation.channel=CAST(:channel AS contact_channel_kind)
                  AND operation.state='succeeded'
                  AND NOT EXISTS (
                      SELECT 1 FROM contact_channel_operation_stop stop
                      WHERE stop.operation_id=operation.id
                  )
                  AND operation.terminal_at
                      + make_interval(secs =>
                          (operation.request_json->>'retention_seconds')::integer) > :now
                  AND (operation.request_json->>'freshness_seconds')::integer >
                      EXTRACT(EPOCH FROM (:now - operation.terminal_at))
                  AND NOT EXISTS (
                      SELECT 1 FROM contact_channel_suppression suppression
                      WHERE suppression.workspace_id=operation.workspace_id
                        AND suppression.contact_id=operation.contact_id
                        AND suppression.channel=operation.channel
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM outreach_objected objection
                      WHERE objection.workspace_id=operation.workspace_id
                        AND objection.contact_entity_id=operation.contact_id
                  )
                LIMIT 1
                """
            ),
            {
                "workspace_id": workspace_id,
                "contact_id": contact_id,
                "channel": channel.value,
                "now": now,
            },
        )
    ).scalar_one_or_none()
    return value is not None


async def contact_channel_operation_is_usable(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: ContactChannelOperationId,
    now: datetime,
) -> bool:
    """Apply current retention/suppression/objection policy to one exact C5 receipt."""

    value = (
        await conn.execute(
            text(
                """
                SELECT 1 FROM contact_channel_operation operation
                WHERE operation.workspace_id=:workspace_id
                  AND operation.id=:operation_id
                  AND operation.state='succeeded'
                  AND NOT EXISTS (
                      SELECT 1 FROM contact_channel_operation_stop stop
                      WHERE stop.operation_id=operation.id
                  )
                  AND operation.terminal_at
                      + make_interval(secs =>
                          (operation.request_json->>'retention_seconds')::integer) > :now
                  AND operation.terminal_at
                      + make_interval(secs =>
                          (operation.request_json->>'freshness_seconds')::integer) > :now
                  AND NOT EXISTS (
                      SELECT 1 FROM contact_channel_suppression suppression
                      WHERE suppression.workspace_id=operation.workspace_id
                        AND suppression.contact_id=operation.contact_id
                        AND suppression.channel=operation.channel
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM outreach_objected objection
                      WHERE objection.workspace_id=operation.workspace_id
                        AND objection.contact_entity_id=operation.contact_id
                  )
                """
            ),
            {
                "workspace_id": workspace_id,
                "operation_id": operation_id,
                "now": now,
            },
        )
    ).scalar_one_or_none()
    return value is not None


__all__ = [
    "ContactChannelAuthorizedOperation",
    "ContactChannelBudgetExceeded",
    "ContactChannelNotFound",
    "ContactChannelReplayConflict",
    "ContactChannelRepositoryError",
    "append_contact_channel_artifact",
    "claim_contact_channel_submit",
    "claim_contact_channel_validation",
    "contact_channel_is_usable",
    "contact_channel_operation_is_usable",
    "find_contact_channel_operation",
    "find_fresh_reusable_contact_channel_operation",
    "get_contact_channel_operation",
    "list_contact_channel_operations_for_contact",
    "list_contact_channel_operations_for_selection",
    "reserve_contact_channel_operation",
    "record_contact_channel_reuse",
    "suppress_contact_channels",
    "update_contact_channel_operation",
]
