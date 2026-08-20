"""Durable S1 account-gap operations and independently replayable provider snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountGapFieldResult,
    AccountGapFieldState,
    AccountGapOperation,
    AccountGapOperationId,
    AccountGapOperationState,
    AccountGapRequest,
    AccountGapSnapshot,
    AccountGapSnapshotState,
    AccountGapSpendOutcome,
    EntityId,
    ProjectPhase,
    ProjectRunId,
    decode_jsonb,
    serialize_value_json,
)
from clue_research.durable.provider_spend import (
    ProviderSpendGuardError,
    require_provider_spend_capacity,
)
from clue_research.durable.spend_posture import cap_refusal_is_enforced

#: Attribution for the record-only spend-cap posture (founder ruling 2026-08-20).
_SITE_GAP_RESERVATION: Final = "sumble_account_gap_reservation"


class AccountGapRepositoryError(RuntimeError):
    pass


class AccountGapNotFound(AccountGapRepositoryError):
    pass


class AccountGapReplayConflict(AccountGapRepositoryError):
    pass


class AccountGapBudgetExceeded(AccountGapRepositoryError):
    pass


class AccountGapFieldWindowConflict(AccountGapRepositoryError):
    """This account's field was already acquired by another operation in the same window.

    The S1 ``account_gap_field_no_overlap`` trigger is the anti-double-spend authority: one
    ``(workspace, account, field)`` may be bought once per observation window, and the window is
    per *project run*, not per job, deliberately. Callers pre-check
    :func:`account_gap_window_field_owners` and refuse before compiling anything, so reaching
    this class means two creates raced past that read — and it is still a statement about the
    *request* ("that field is already bought; read the operation that owns it"), never about
    money or truth. It is therefore typed and model-repairable rather than a raw ``DBAPIError``
    escaping as a job-killing ``execution_failed``, which is exactly what live job ``3cc0a4f2``
    did on 2026-08-20.
    """

    def __init__(self, message: str, *, fields: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.fields = fields


#: The exact ``RAISE EXCEPTION`` text of ``account_gap_reject_overlapping_field`` (migration
#: ``bd0b7e62a2b4``). Matched verbatim, together with the plpgsql ``raise_exception`` SQLSTATE, so
#: the conversion below stays narrow: every other database error on the same statement — an
#: integrity violation, a lineage mismatch, unknown spend — must keep propagating and suspending.
_FIELD_WINDOW_ACQUIRED_MESSAGE: Final = (
    "account-gap field already acquired in this observation window"
)
_RAISE_EXCEPTION_SQLSTATE: Final = "P0001"


def _is_field_window_conflict(error: DBAPIError) -> bool:
    original = error.orig
    if original is None:
        return False
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if sqlstate is None:
        cause = getattr(original, "__cause__", None)
        sqlstate = getattr(cause, "sqlstate", None)
    return sqlstate == _RAISE_EXCEPTION_SQLSTATE and _FIELD_WINDOW_ACQUIRED_MESSAGE in str(original)


_REQUEST_ADAPTER = TypeAdapter(AccountGapRequest)
_OPERATION_COLUMNS = (
    "id, workspace_id, project_id, project_run_id, icp_key, icp_version, "
    "discovery_batch_id, discovery_seal_sha256, account_id, primary_domain, tier_claim_id, "
    "provider_api_version, provider_contract_version, pricing_policy_version, "
    "field_policy_version, observation_window, request_fingerprint, request_json, state::text, "
    "spend_outcome::text, input_artifact_key, receipt_manifest_key, provider_units_reserved, "
    "provider_units_charged, cost_cents_reserved, cost_cents_charged, failure_code, started_at, "
    "unbounded_call_approved, terminal_at, created_at, updated_at"
)
_SNAPSHOT_COLUMNS = (
    "operation_id, workspace_id, account_id, source_key, request_fingerprint, state::text, "
    "spend_outcome::text, request_artifact_key, response_artifact_key, provider_request_id, "
    "provider_units_reserved, provider_units_charged, credits_remaining, cost_cents_charged, "
    "unbounded_call_approved, failure_code, started_at, terminal_at, created_at, updated_at"
)

_REQUEST_IDENTITY_COLUMNS = (
    "workspace_id",
    "project_id",
    "project_run_id",
    "icp_key",
    "icp_version",
    "discovery_batch_id",
    "discovery_seal_sha256",
    "account_id",
    "primary_domain",
    "tier_claim_id",
    "provider_api_version",
    "provider_contract_version",
    "pricing_policy_version",
    "field_policy_version",
    "observation_window",
)


def _operation(row: object) -> AccountGapOperation:
    data = dict(row._mapping)  # type: ignore[attr-defined]
    request = _REQUEST_ADAPTER.validate_python(decode_jsonb(data.pop("request_json")))
    for column in _REQUEST_IDENTITY_COLUMNS:
        stored = data.pop(column)
        if stored != getattr(request, column):
            raise AccountGapRepositoryError(
                f"account-gap indexed request identity differs at {column}"
            )
    data["operation_id"] = data.pop("id")
    data["request"] = request
    return AccountGapOperation.model_validate(data)


def _snapshot(row: object) -> AccountGapSnapshot:
    return AccountGapSnapshot.model_validate(dict(row._mapping))  # type: ignore[attr-defined]


async def find_account_gap_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: object,
    request_fingerprint: str,
    observation_window: str,
) -> AccountGapOperation | None:
    row = (
        await conn.execute(
            text(
                f"SELECT {_OPERATION_COLUMNS} FROM account_gap_operation "
                "WHERE workspace_id=:workspace_id AND account_id=:account_id "
                "AND request_fingerprint=:fingerprint AND observation_window=:window"
            ),
            {
                "workspace_id": workspace_id,
                "account_id": account_id,
                "fingerprint": request_fingerprint,
                "window": observation_window,
            },
        )
    ).one_or_none()
    return _operation(row) if row is not None else None


async def find_account_gap_operation_for_fields(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: object,
    observation_window: str,
    field_keys: tuple[str, ...],
) -> AccountGapOperation | None:
    """Find the durable same-window request before mutable current-value gap re-evaluation."""

    rows = (
        await conn.execute(
            text(
                f"SELECT {_OPERATION_COLUMNS} FROM account_gap_operation "
                "WHERE workspace_id=:workspace_id AND account_id=:account_id "
                "AND observation_window=:window ORDER BY created_at"
            ),
            {
                "workspace_id": workspace_id,
                "account_id": account_id,
                "window": observation_window,
            },
        )
    ).all()
    matches = [
        operation
        for operation in (_operation(row) for row in rows)
        if tuple(str(item.field_key) for item in operation.request.fields) == field_keys
    ]
    if len(matches) > 1:
        raise AccountGapReplayConflict("multiple same-window account-gap operations for field set")
    return matches[0] if matches else None


async def account_gap_window_field_owners(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: object,
    observation_window: str,
    field_keys: Sequence[str],
) -> tuple[tuple[str, ...], ...]:
    """The exact field set of every operation in this window that owns a requested field.

    The pre-check in front of the ``account_gap_field_no_overlap`` trigger. The trigger stays the
    authority (this read can be raced); it exists so the ordinary, entirely expected case — a
    later job in the same project run asking again for a field an earlier job already bought —
    is refused as a plain, zero-state request refusal instead of a raw database error.

    It returns the owning operations' **whole** field sets, not just the overlap, because the
    caller's refusal has to name them: re-asking an owning set *exactly* is what
    :func:`find_account_gap_operation_for_fields` rejoins and replays zero-spend, and that replay
    is the only way a later job makes an already-bought pair terminal for its own coverage. A
    refusal that named only the overlap left the live agent (job ``3cc0a4f2``) with no discoverable
    legal move: it re-read state, tried subsets, and wedged.
    """

    requested = set(field_keys)
    if not requested:
        return ()
    rows = (
        await conn.execute(
            text(
                "SELECT result.operation_id, result.field_key FROM account_gap_field_result result "
                "JOIN account_gap_operation op ON op.id = result.operation_id "
                "WHERE result.workspace_id=:workspace_id AND result.account_id=:account_id "
                "AND op.observation_window=:window"
            ),
            {
                "workspace_id": workspace_id,
                "account_id": account_id,
                "window": observation_window,
            },
        )
    ).all()
    owned: dict[object, set[str]] = {}
    for operation_id, field_key in rows:
        owned.setdefault(operation_id, set()).add(field_key)
    return tuple(sorted(tuple(sorted(fields)) for fields in owned.values() if fields & requested))


async def get_account_gap_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: AccountGapOperationId,
    for_update: bool = False,
) -> AccountGapOperation | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        await conn.execute(
            text(
                f"SELECT {_OPERATION_COLUMNS} FROM account_gap_operation "
                "WHERE workspace_id=:workspace_id AND id=:operation_id" + suffix
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).one_or_none()
    return _operation(row) if row is not None else None


def _assert_replay(stored: AccountGapOperation, proposed: AccountGapOperation) -> None:
    if (
        stored.request != proposed.request
        or stored.input_artifact_key != proposed.input_artifact_key
        or stored.provider_units_reserved != proposed.provider_units_reserved
        or stored.cost_cents_reserved != proposed.cost_cents_reserved
    ):
        raise AccountGapReplayConflict(
            "account-gap fingerprint was reused with different immutable content"
        )


async def reserve_account_gap_operation(
    conn: AsyncConnection,
    *,
    operation: AccountGapOperation,
    snapshots: tuple[AccountGapSnapshot, ...],
    enforce_budget: bool = True,
) -> tuple[AccountGapOperation, bool]:
    """Reserve one bounded account-gap enrichment operation.

    ``enforce_budget`` is the FI pilot budget-controls switch. It gates the project-run money check
    **and** — since the 2026-08-20 ruling that our own spend caps are record-only in the pilot
    posture — this operation's three reserved-vs-cap comparisons. Each one is still computed and
    announced (:mod:`clue_research.durable.spend_posture`); only the refusal goes inert. The
    ledger's own invariants (``charged <= reserved``, the CHECKs) are untouched in both modes: an
    operation that may be charged more reserves more, it does not compare less.
    """

    request = operation.request
    if operation.provider_units_reserved > Decimal(
        request.provider_credit_cap
    ) and cap_refusal_is_enforced(
        enforce_budget,
        site=_SITE_GAP_RESERVATION,
        reason="reserved_units_above_cap",
        amounts={
            "provider_units_reserved": operation.provider_units_reserved,
            "provider_credit_cap": request.provider_credit_cap,
        },
    ):
        raise AccountGapBudgetExceeded("account-gap provider cap exceeded")
    if operation.cost_cents_reserved > Decimal(
        request.money_budget_cap_cents
    ) and cap_refusal_is_enforced(
        enforce_budget,
        site=_SITE_GAP_RESERVATION,
        reason="reserved_cost_above_cap",
        amounts={
            "cost_cents_reserved": operation.cost_cents_reserved,
            "money_budget_cap_cents": request.money_budget_cap_cents,
        },
    ):
        raise AccountGapBudgetExceeded("account-gap money cap exceeded")
    if request.expected_value_credits < operation.provider_units_reserved and (
        cap_refusal_is_enforced(
            enforce_budget,
            site=_SITE_GAP_RESERVATION,
            reason="value_below_reserved_units",
            amounts={
                "expected_value_credits": request.expected_value_credits,
                "provider_units_reserved": operation.provider_units_reserved,
            },
        )
    ):
        raise AccountGapBudgetExceeded(
            "account-gap expected value does not justify the bounded credit reservation"
        )
    existing = await find_account_gap_operation(
        conn,
        workspace_id=request.workspace_id,
        account_id=request.account_id,
        request_fingerprint=operation.request_fingerprint,
        observation_window=request.observation_window,
    )
    if existing is not None:
        _assert_replay(existing, operation)
        return existing, False
    try:
        await require_provider_spend_capacity(
            conn,
            project_run_id=request.project_run_id,
            proposed_cents=operation.cost_cents_reserved,
            allowed_phases=frozenset({ProjectPhase.DEEP}),
            entity_research_job_id=request.entity_research_job_id,
            enforce_budget=enforce_budget,
        )
    except ProviderSpendGuardError as exc:
        raise AccountGapBudgetExceeded(str(exc)) from exc
    existing = await find_account_gap_operation(
        conn,
        workspace_id=request.workspace_id,
        account_id=request.account_id,
        request_fingerprint=operation.request_fingerprint,
        observation_window=request.observation_window,
    )
    if existing is not None:
        _assert_replay(existing, operation)
        return existing, False
    inserted = await conn.execute(
        text(
            "INSERT INTO account_gap_operation ("
            "id, workspace_id, project_id, project_run_id, icp_key, icp_version, "
            "discovery_batch_id, discovery_seal_sha256, account_id, primary_domain, tier_claim_id, "
            "provider_api_version, provider_contract_version, pricing_policy_version, "
            "field_policy_version, observation_window, request_fingerprint, request_json, state, "
            "spend_outcome, input_artifact_key, provider_units_reserved, cost_cents_reserved, "
            "unbounded_call_approved) "
            "VALUES (:id, :workspace_id, :project_id, :project_run_id, :icp_key, :icp_version, "
            ":batch_id, :seal, :account_id, :domain, :tier_claim_id, :api_version, "
            ":contract_version, :pricing_version, :field_version, :window, :fingerprint, "
            "CAST(:request_json AS jsonb), CAST(:state AS account_gap_operation_state), "
            "CAST(:spend AS account_gap_spend_outcome), :input_key, :reserved_units, "
            ":reserved_cost, :unbounded) ON CONFLICT DO NOTHING RETURNING id"
        ),
        {
            "id": operation.operation_id,
            "workspace_id": request.workspace_id,
            "project_id": request.project_id,
            "project_run_id": request.project_run_id,
            "icp_key": request.icp_key,
            "icp_version": request.icp_version,
            "batch_id": request.discovery_batch_id,
            "seal": request.discovery_seal_sha256,
            "account_id": request.account_id,
            "domain": request.primary_domain,
            "tier_claim_id": request.tier_claim_id,
            "api_version": request.provider_api_version,
            "contract_version": request.provider_contract_version,
            "pricing_version": request.pricing_policy_version,
            "field_version": request.field_policy_version,
            "window": request.observation_window,
            "fingerprint": operation.request_fingerprint,
            "request_json": request.model_dump_json(),
            "state": operation.state.value,
            "spend": operation.spend_outcome.value,
            "input_key": operation.input_artifact_key,
            "reserved_units": operation.provider_units_reserved,
            "reserved_cost": operation.cost_cents_reserved,
            "unbounded": request.allow_unbounded_tech,
        },
    )
    created = inserted.scalar_one_or_none() is not None
    stored = await find_account_gap_operation(
        conn,
        workspace_id=request.workspace_id,
        account_id=request.account_id,
        request_fingerprint=operation.request_fingerprint,
        observation_window=request.observation_window,
    )
    if stored is None:
        raise AccountGapNotFound("reserved account-gap operation")
    _assert_replay(stored, operation)
    if not created:
        return stored, False
    for snapshot in snapshots:
        if snapshot.operation_id != stored.operation_id:
            raise AccountGapReplayConflict("account-gap snapshot operation lineage mismatch")
        await conn.execute(
            text(
                "INSERT INTO account_gap_snapshot (operation_id, workspace_id, account_id, "
                "source_key, request_fingerprint, state, spend_outcome, request_artifact_key, "
                "provider_units_reserved, unbounded_call_approved) VALUES ("
                ":operation_id, :workspace_id, :account_id, :source_key, :fingerprint, "
                "CAST(:state AS account_gap_snapshot_state), "
                "CAST(:spend AS account_gap_spend_outcome), :request_key, :reserved, :unbounded)"
            ),
            {
                "operation_id": snapshot.operation_id,
                "workspace_id": snapshot.workspace_id,
                "account_id": snapshot.account_id,
                "source_key": snapshot.source_key,
                "fingerprint": snapshot.request_fingerprint,
                "state": snapshot.state.value,
                "spend": snapshot.spend_outcome.value,
                "request_key": snapshot.request_artifact_key,
                "reserved": snapshot.provider_units_reserved,
                "unbounded": snapshot.unbounded_call_approved,
            },
        )
    for plan in request.fields:
        try:
            await conn.execute(
                text(
                    "INSERT INTO account_gap_field_result (operation_id, workspace_id, "
                    "account_id, field_key, source_key, selection_reason, expected_value_credits, "
                    "basis_claim_ids, state, reason_code) VALUES (:operation_id, :workspace_id, "
                    ":account_id, :field_key, :source_key, :reason, :expected, "
                    "CAST(:basis AS jsonb), 'pending', 'awaiting_sumble_snapshot')"
                ),
                {
                    "operation_id": stored.operation_id,
                    "workspace_id": request.workspace_id,
                    "account_id": request.account_id,
                    "field_key": str(plan.field_key),
                    "source_key": plan.source_key,
                    "reason": plan.reason.value,
                    "expected": plan.expected_value_credits,
                    "basis": serialize_value_json([str(value) for value in plan.basis_claim_ids]),
                },
            )
        except DBAPIError as error:
            # Narrow on purpose: only ``account_gap_field_no_overlap``'s own raise becomes the
            # typed, model-repairable conflict. Anything else — a lineage mismatch, an integrity
            # violation — keeps propagating, because that boundary is what stops a real
            # money-or-truth failure from being talked past as an ordinary refused turn. The
            # caller owns the transaction, so raising here rolls the whole reservation back:
            # zero operation row, zero snapshots, zero spend.
            if not _is_field_window_conflict(error):
                raise
            raise AccountGapFieldWindowConflict(
                f"{plan.field_key} was already acquired for this account in observation window "
                f"{request.observation_window}",
                fields=(str(plan.field_key),),
            ) from error
    return stored, True


async def claim_account_gap_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: AccountGapOperationId,
) -> AccountGapOperation | None:
    row = (
        await conn.execute(
            text(
                "UPDATE account_gap_operation SET state='acquiring', "
                "started_at=COALESCE(started_at, now()), updated_at=now(), failure_code=NULL "
                "WHERE workspace_id=:workspace_id AND id=:operation_id "
                "AND state IN ('planned', 'failed_retryable') "
                "AND spend_outcome IN ('not_dispatched', 'not_charged') "
                f"RETURNING {_OPERATION_COLUMNS}"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).one_or_none()
    return _operation(row) if row is not None else None


async def list_account_gap_snapshots(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: AccountGapOperationId,
) -> tuple[AccountGapSnapshot, ...]:
    rows = (
        await conn.execute(
            text(
                f"SELECT {_SNAPSHOT_COLUMNS} FROM account_gap_snapshot "
                "WHERE workspace_id=:workspace_id AND operation_id=:operation_id "
                "ORDER BY source_key"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).all()
    return tuple(_snapshot(row) for row in rows)


async def get_account_gap_snapshot(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: AccountGapOperationId,
    source_key: str,
    for_update: bool = False,
) -> AccountGapSnapshot | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        await conn.execute(
            text(
                f"SELECT {_SNAPSHOT_COLUMNS} FROM account_gap_snapshot "
                "WHERE workspace_id=:workspace_id AND operation_id=:operation_id "
                "AND source_key=:source_key" + suffix
            ),
            {
                "workspace_id": workspace_id,
                "operation_id": operation_id,
                "source_key": source_key,
            },
        )
    ).one_or_none()
    return _snapshot(row) if row is not None else None


async def latest_succeeded_account_gap_snapshot(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    account_id: EntityId,
    source_key: str,
) -> AccountGapSnapshot | None:
    """Return the latest successful S1 snapshot for one exact run/account/source lineage."""

    row = (
        await conn.execute(
            text(
                "SELECT "
                + ", ".join(f"snapshot.{column.strip()}" for column in _SNAPSHOT_COLUMNS.split(","))
                + " "
                "FROM account_gap_operation operation "
                "JOIN account_gap_snapshot snapshot ON snapshot.operation_id=operation.id "
                "AND snapshot.workspace_id=operation.workspace_id "
                "WHERE operation.workspace_id=:workspace_id "
                "AND operation.project_run_id=:project_run_id "
                "AND operation.account_id=:account_id AND operation.state='succeeded' "
                "AND snapshot.source_key=:source_key AND snapshot.state='succeeded' "
                "AND snapshot.response_artifact_key IS NOT NULL "
                "ORDER BY operation.terminal_at DESC NULLS LAST, operation.created_at DESC "
                "LIMIT 1"
            ),
            {
                "workspace_id": workspace_id,
                "project_run_id": project_run_id,
                "account_id": account_id,
                "source_key": source_key,
            },
        )
    ).one_or_none()
    return _snapshot(row) if row is not None else None


async def claim_account_gap_snapshot(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: AccountGapOperationId,
    source_key: str,
) -> AccountGapSnapshot | None:
    row = (
        await conn.execute(
            text(
                "UPDATE account_gap_snapshot SET state='dispatching', "
                "started_at=COALESCE(started_at, now()), updated_at=now(), failure_code=NULL "
                "WHERE workspace_id=:workspace_id AND operation_id=:operation_id "
                "AND source_key=:source_key AND state IN ('planned', 'failed_retryable') "
                "AND spend_outcome IN ('not_dispatched', 'not_charged') "
                f"RETURNING {_SNAPSHOT_COLUMNS}"
            ),
            {
                "workspace_id": workspace_id,
                "operation_id": operation_id,
                "source_key": source_key,
            },
        )
    ).one_or_none()
    return _snapshot(row) if row is not None else None


async def reserve_account_gap_snapshot(
    conn: AsyncConnection,
    *,
    snapshot: AccountGapSnapshot,
) -> tuple[AccountGapSnapshot, bool]:
    """Insert one exact dependent-source request after organization identity resolves."""

    inserted = await conn.execute(
        text(
            "INSERT INTO account_gap_snapshot (operation_id, workspace_id, account_id, "
            "source_key, request_fingerprint, state, spend_outcome, request_artifact_key, "
            "provider_units_reserved, unbounded_call_approved) VALUES ("
            ":operation_id, :workspace_id, :account_id, :source_key, :fingerprint, "
            "CAST(:state AS account_gap_snapshot_state), "
            "CAST(:spend AS account_gap_spend_outcome), :request_key, :reserved, :unbounded) "
            "ON CONFLICT DO NOTHING RETURNING operation_id"
        ),
        {
            "operation_id": snapshot.operation_id,
            "workspace_id": snapshot.workspace_id,
            "account_id": snapshot.account_id,
            "source_key": snapshot.source_key,
            "fingerprint": snapshot.request_fingerprint,
            "state": snapshot.state.value,
            "spend": snapshot.spend_outcome.value,
            "request_key": snapshot.request_artifact_key,
            "reserved": snapshot.provider_units_reserved,
            "unbounded": snapshot.unbounded_call_approved,
        },
    )
    stored = await get_account_gap_snapshot(
        conn,
        workspace_id=snapshot.workspace_id,
        operation_id=snapshot.operation_id,
        source_key=snapshot.source_key,
    )
    if stored is None:
        raise AccountGapNotFound("dependent account-gap snapshot")
    if (
        stored.request_fingerprint != snapshot.request_fingerprint
        or stored.request_artifact_key != snapshot.request_artifact_key
        or stored.provider_units_reserved != snapshot.provider_units_reserved
        or stored.unbounded_call_approved != snapshot.unbounded_call_approved
    ):
        raise AccountGapReplayConflict("dependent account-gap request changed on replay")
    return stored, inserted.scalar_one_or_none() is not None


async def update_account_gap_snapshot(
    conn: AsyncConnection,
    *,
    snapshot: AccountGapSnapshot,
) -> AccountGapSnapshot:
    row = (
        await conn.execute(
            text(
                "UPDATE account_gap_snapshot SET state=CAST(:state AS account_gap_snapshot_state), "
                "spend_outcome=CAST(:spend AS account_gap_spend_outcome), "
                "response_artifact_key=:response_key, provider_request_id=:request_id, "
                "provider_units_charged=:charged, credits_remaining=:remaining, "
                "cost_cents_charged=:cost, failure_code=:failure, started_at=:started_at, "
                "terminal_at=:terminal_at, updated_at=now() WHERE workspace_id=:workspace_id "
                "AND operation_id=:operation_id AND source_key=:source_key "
                "AND request_fingerprint=:fingerprint "
                f"RETURNING {_SNAPSHOT_COLUMNS}"
            ),
            {
                "state": snapshot.state.value,
                "spend": snapshot.spend_outcome.value,
                "response_key": snapshot.response_artifact_key,
                "request_id": snapshot.provider_request_id,
                "charged": snapshot.provider_units_charged,
                "remaining": snapshot.credits_remaining,
                "cost": snapshot.cost_cents_charged,
                "failure": snapshot.failure_code,
                "started_at": snapshot.started_at,
                "terminal_at": snapshot.terminal_at,
                "workspace_id": snapshot.workspace_id,
                "operation_id": snapshot.operation_id,
                "source_key": snapshot.source_key,
                "fingerprint": snapshot.request_fingerprint,
            },
        )
    ).one_or_none()
    if row is None:
        raise AccountGapReplayConflict("account-gap snapshot update lost request lineage")
    return _snapshot(row)


async def put_account_gap_field_result(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    result: AccountGapFieldResult,
) -> AccountGapFieldResult:
    row = (
        (
            await conn.execute(
                text(
                    "UPDATE account_gap_field_result SET "
                    "state=CAST(:state AS account_gap_field_state), "
                    "sumble_claim_id=:sumble_claim_id, current_claim_id=:current_claim_id, "
                    "conflicting_claim_ids=CAST(:conflicts AS jsonb), reason_code=:reason, "
                    "updated_at=now() WHERE workspace_id=:workspace_id "
                    "AND operation_id=:operation_id AND account_id=:account_id "
                    "AND field_key=:field_key AND source_key=:source_key "
                    "RETURNING operation_id, account_id, field_key, source_key, state::text, "
                    "sumble_claim_id, current_claim_id, conflicting_claim_ids, reason_code, "
                    "updated_at"
                ),
                {
                    "state": result.state.value,
                    "sumble_claim_id": result.sumble_claim_id,
                    "current_claim_id": result.current_claim_id,
                    "conflicts": serialize_value_json(
                        [str(value) for value in result.conflicting_claim_ids]
                    ),
                    "reason": result.reason_code,
                    "workspace_id": workspace_id,
                    "operation_id": result.operation_id,
                    "account_id": result.account_id,
                    "field_key": str(result.field_key),
                    "source_key": result.source_key,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise AccountGapNotFound("account-gap field result")
    data = dict(row)
    data["conflicting_claim_ids"] = tuple(decode_jsonb(data["conflicting_claim_ids"]))
    return AccountGapFieldResult.model_validate(data)


async def list_account_gap_field_results(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: AccountGapOperationId,
) -> tuple[AccountGapFieldResult, ...]:
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT operation_id, account_id, field_key, source_key, state::text, "
                    "sumble_claim_id, current_claim_id, conflicting_claim_ids, reason_code, "
                    "updated_at "
                    "FROM account_gap_field_result WHERE workspace_id=:workspace_id "
                    "AND operation_id=:operation_id ORDER BY field_key"
                ),
                {"workspace_id": workspace_id, "operation_id": operation_id},
            )
        )
        .mappings()
        .all()
    )
    results: list[AccountGapFieldResult] = []
    for row in rows:
        data = dict(row)
        data["conflicting_claim_ids"] = tuple(decode_jsonb(data["conflicting_claim_ids"]))
        results.append(AccountGapFieldResult.model_validate(data))
    return tuple(results)


async def update_account_gap_operation(
    conn: AsyncConnection,
    *,
    operation: AccountGapOperation,
) -> AccountGapOperation:
    current = await get_account_gap_operation(
        conn,
        workspace_id=operation.request.workspace_id,
        operation_id=operation.operation_id,
        for_update=True,
    )
    if current is None:
        raise AccountGapNotFound("account-gap operation")
    if current.terminal_at is not None:
        if current == operation:
            return current
        raise AccountGapReplayConflict("terminal account-gap operation is immutable")
    if operation.state is AccountGapOperationState.SUCCEEDED:
        snapshots = await list_account_gap_snapshots(
            conn,
            workspace_id=operation.request.workspace_id,
            operation_id=operation.operation_id,
        )
        if not snapshots or any(
            item.state
            not in {AccountGapSnapshotState.SUCCEEDED, AccountGapSnapshotState.NOT_APPLICABLE}
            for item in snapshots
        ):
            raise AccountGapReplayConflict("account-gap success requires terminal snapshots")
        fields = await list_account_gap_field_results(
            conn,
            workspace_id=operation.request.workspace_id,
            operation_id=operation.operation_id,
        )
        if not fields or any(
            item.state in {AccountGapFieldState.PENDING, AccountGapFieldState.FAILED_TERMINAL}
            for item in fields
        ):
            raise AccountGapReplayConflict("account-gap success requires terminal field outcomes")
    if (
        operation.state
        in {
            AccountGapOperationState.SUCCEEDED,
            AccountGapOperationState.FAILED_TERMINAL,
            AccountGapOperationState.SPEND_OUTCOME_UNKNOWN,
        }
        and operation.spend_outcome
        in {AccountGapSpendOutcome.CHARGED, AccountGapSpendOutcome.UNKNOWN}
        and operation.cost_cents_charged
    ):
        settled = await conn.execute(
            text(
                "UPDATE project_run SET spent_cents=spent_cents+:cost, updated_at=now() "
                "WHERE id=:run_id AND workspace_id=:workspace_id"
            ),
            {
                "cost": operation.cost_cents_charged,
                "run_id": operation.request.project_run_id,
                "workspace_id": operation.request.workspace_id,
            },
        )
        if settled.rowcount != 1:
            raise AccountGapReplayConflict("account-gap project settlement lost run lineage")
    row = (
        await conn.execute(
            text(
                "UPDATE account_gap_operation SET "
                "state=CAST(:state AS account_gap_operation_state), "
                "spend_outcome=CAST(:spend AS account_gap_spend_outcome), "
                "receipt_manifest_key=:manifest, provider_units_charged=:charged, "
                "cost_cents_charged=:cost, failure_code=:failure, started_at=:started_at, "
                "terminal_at=:terminal_at, updated_at=now() WHERE workspace_id=:workspace_id "
                "AND id=:operation_id AND request_fingerprint=:fingerprint "
                f"RETURNING {_OPERATION_COLUMNS}"
            ),
            {
                "state": operation.state.value,
                "spend": operation.spend_outcome.value,
                "manifest": operation.receipt_manifest_key,
                "charged": operation.provider_units_charged,
                "cost": operation.cost_cents_charged,
                "failure": operation.failure_code,
                "started_at": operation.started_at,
                "terminal_at": operation.terminal_at,
                "workspace_id": operation.request.workspace_id,
                "operation_id": operation.operation_id,
                "fingerprint": operation.request_fingerprint,
            },
        )
    ).one_or_none()
    if row is None:
        raise AccountGapReplayConflict("account-gap operation update lost request lineage")
    return _operation(row)


async def quarantine_dispatching_account_gap_snapshots(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: AccountGapOperationId,
) -> int:
    """Crash recovery: a persisted DISPATCHING row may already have consumed credits."""

    result = await conn.execute(
        text(
            "UPDATE account_gap_snapshot SET state='spend_outcome_unknown', "
            "spend_outcome='unknown', "
            "failure_code='crash_after_possible_dispatch', terminal_at=now(), updated_at=now() "
            "WHERE workspace_id=:workspace_id AND operation_id=:operation_id "
            "AND state='dispatching'"
        ),
        {"workspace_id": workspace_id, "operation_id": operation_id},
    )
    return result.rowcount


def terminal_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "AccountGapBudgetExceeded",
    "AccountGapFieldWindowConflict",
    "AccountGapNotFound",
    "AccountGapReplayConflict",
    "AccountGapRepositoryError",
    "account_gap_window_field_owners",
    "claim_account_gap_operation",
    "claim_account_gap_snapshot",
    "find_account_gap_operation",
    "find_account_gap_operation_for_fields",
    "get_account_gap_operation",
    "get_account_gap_snapshot",
    "list_account_gap_field_results",
    "list_account_gap_snapshots",
    "latest_succeeded_account_gap_snapshot",
    "put_account_gap_field_result",
    "quarantine_dispatching_account_gap_snapshots",
    "reserve_account_gap_snapshot",
    "reserve_account_gap_operation",
    "terminal_now",
    "update_account_gap_operation",
    "update_account_gap_snapshot",
]
