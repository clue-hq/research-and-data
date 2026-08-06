"""PostgreSQL/object-store journal for governed Sumble MCP account-gap calls.

This adapter deliberately reuses the S1 ``account_gap_operation`` and
``account_gap_snapshot`` ledgers.  It introduces no new database head and does not compose itself
into the account-deep orchestrator.  A caller first reserves an ordinary account-gap operation;
this journal then proves that the exact MCP plan is covered by that reservation, claims one
per-tool snapshot, persists the response, and exposes database-only replay.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from clue_core import (
    AccountGapOperation,
    AccountGapOperationState,
    AccountGapSnapshot,
    AccountGapSnapshotState,
    AccountGapSpendOutcome,
)
from clue_db import ConnFactory, transaction
from clue_research.durable.account_gap_enrichment import (
    AccountGapNotFound,
    AccountGapReplayConflict,
    claim_account_gap_snapshot,
    get_account_gap_operation,
    get_account_gap_snapshot,
    list_account_gap_snapshots,
    reserve_account_gap_snapshot,
    terminal_now,
    update_account_gap_snapshot,
)
from clue_research.durable.discovery import (
    bind_discovery_artifact_subject,
    capture_discovery_artifact,
)
from clue_research.resolvers.sumble.mcp_adapter import (
    SumbleMcpAcquireResult,
    SumbleMcpAcquireState,
    SumbleMcpDurableAuthorization,
    SumbleMcpInvocationPlan,
    SumbleMcpSnapshot,
)
from clue_research.resolvers.sumble.mcp_client import SUMBLE_MCP_ENDPOINT, SumbleMcpToolExchange
from clue_storage import StorageBackend, content_address


class SumbleMcpJournalError(AccountGapReplayConflict):
    pass


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _reservation_key(operation: AccountGapOperation, plan: SumbleMcpInvocationPlan) -> str:
    return f"account-gap:{operation.operation_id}:{plan.source_key}:{plan.request_fingerprint}"


class AccountGapSumbleMcpJournal:
    """Concrete durable journal for one already-reserved account-gap operation."""

    def __init__(
        self,
        *,
        operation: AccountGapOperation,
        storage: StorageBackend,
        cents_per_credit: Decimal = Decimal(0),
        conn_factory: ConnFactory = transaction,
    ) -> None:
        if cents_per_credit < 0:
            raise ValueError("Sumble MCP cents-per-credit must be non-negative")
        self._operation = operation
        self._storage = storage
        self._cents_per_credit = cents_per_credit
        self._conn_factory = conn_factory

    async def authorization_for(
        self, plan: SumbleMcpInvocationPlan
    ) -> SumbleMcpDurableAuthorization:
        """Issue proof only after finding the exact parent reservation in PostgreSQL."""

        async with self._conn_factory() as conn:
            operation = await get_account_gap_operation(
                conn,
                workspace_id=plan.workspace_id,
                operation_id=self._operation.operation_id,
                for_update=True,
            )
            if operation is None:
                raise AccountGapNotFound("Sumble MCP parent account-gap operation")
            self._assert_parent(operation, plan)
        return SumbleMcpDurableAuthorization(
            operation_id=str(operation.operation_id),
            durable_reservation_key=_reservation_key(operation, plan),
            request_fingerprint=plan.request_fingerprint,
            catalog_fingerprint=plan.catalog_fingerprint,
            provider_units_reserved=plan.maximum_provider_units,
            cost_cents_reserved=plan.maximum_cost_cents,
        )

    async def acquire(
        self,
        *,
        plan: SumbleMcpInvocationPlan,
        authorization: SumbleMcpDurableAuthorization,
    ) -> SumbleMcpAcquireResult:
        async with self._conn_factory() as conn:
            operation = await get_account_gap_operation(
                conn,
                workspace_id=plan.workspace_id,
                operation_id=self._operation.operation_id,
                for_update=True,
            )
            if operation is None:
                raise AccountGapNotFound("Sumble MCP parent account-gap operation")
            self._assert_authorization(operation, plan, authorization)
            row = await get_account_gap_snapshot(
                conn,
                workspace_id=plan.workspace_id,
                operation_id=operation.operation_id,
                source_key=plan.source_key,
                for_update=True,
            )
            if row is None:
                snapshots = await list_account_gap_snapshots(
                    conn,
                    workspace_id=plan.workspace_id,
                    operation_id=operation.operation_id,
                )
                already_reserved = sum(
                    (item.provider_units_reserved for item in snapshots), Decimal(0)
                )
                if (
                    already_reserved + plan.maximum_provider_units
                    > operation.provider_units_reserved
                ):
                    raise SumbleMcpJournalError(
                        "Sumble MCP snapshot reservations exceed the durable parent reservation"
                    )
                already_reserved_cost = already_reserved * self._cents_per_credit
                if already_reserved_cost + plan.maximum_cost_cents > operation.cost_cents_reserved:
                    raise SumbleMcpJournalError(
                        "Sumble MCP snapshot costs exceed the durable parent reservation"
                    )
                request_payload = {
                    "contract": "sumble-mcp-invocation-v1",
                    "request_fingerprint": plan.request_fingerprint,
                    "catalog_fingerprint": plan.catalog_fingerprint,
                    "tool_name": plan.tool_name,
                    "arguments": plan.arguments,
                    "field_bindings": [
                        item.model_dump(mode="json") for item in plan.field_bindings
                    ],
                    "settlement": plan.settlement.model_dump(mode="json"),
                }
                request_key = await capture_discovery_artifact(
                    conn,
                    self._storage,
                    workspace_id=plan.workspace_id,
                    content=_json_bytes(request_payload),
                    media_type="application/json",
                    source_key=plan.source_key,
                    source_url=SUMBLE_MCP_ENDPOINT,
                )
                row, _ = await reserve_account_gap_snapshot(
                    conn,
                    snapshot=AccountGapSnapshot(
                        operation_id=operation.operation_id,
                        workspace_id=plan.workspace_id,
                        account_id=plan.account_id,
                        source_key=plan.source_key,
                        request_fingerprint=plan.request_fingerprint,
                        state=AccountGapSnapshotState.PLANNED,
                        spend_outcome=AccountGapSpendOutcome.NOT_DISPATCHED,
                        request_artifact_key=request_key,
                        provider_units_reserved=plan.maximum_provider_units,
                    ),
                )
                await self._bind(
                    conn,
                    operation,
                    request_key,
                    reference_kind="sumble_mcp_request",
                    reference_id=f"{operation.operation_id}:{plan.source_key}:request",
                )
            if row.request_fingerprint != plan.request_fingerprint:
                raise SumbleMcpJournalError("Sumble MCP source key was reused for another request")
            lease_key = authorization.durable_reservation_key
            if row.state is AccountGapSnapshotState.SUCCEEDED:
                return SumbleMcpAcquireResult(
                    state=SumbleMcpAcquireState.REPLAY,
                    lease_key=lease_key,
                    snapshot=await self._load_snapshot(row, plan),
                )
            if row.state is AccountGapSnapshotState.DISPATCHING:
                return SumbleMcpAcquireResult(
                    state=SumbleMcpAcquireState.IN_FLIGHT,
                    lease_key=lease_key,
                )
            if row.state is AccountGapSnapshotState.SPEND_OUTCOME_UNKNOWN:
                return SumbleMcpAcquireResult(
                    state=SumbleMcpAcquireState.SPEND_OUTCOME_UNKNOWN,
                    lease_key=lease_key,
                )
            if row.state not in {
                AccountGapSnapshotState.PLANNED,
                AccountGapSnapshotState.FAILED_RETRYABLE,
            }:
                raise SumbleMcpJournalError(
                    f"Sumble MCP snapshot cannot dispatch from state {row.state.value!r}"
                )
            claimed = await claim_account_gap_snapshot(
                conn,
                workspace_id=plan.workspace_id,
                operation_id=operation.operation_id,
                source_key=plan.source_key,
            )
            if claimed is None:
                return SumbleMcpAcquireResult(
                    state=SumbleMcpAcquireState.IN_FLIGHT,
                    lease_key=lease_key,
                )
            return SumbleMcpAcquireResult(
                state=SumbleMcpAcquireState.DISPATCH,
                lease_key=lease_key,
            )

    async def commit(
        self,
        *,
        plan: SumbleMcpInvocationPlan,
        authorization: SumbleMcpDurableAuthorization,
        lease_key: str,
        exchange: SumbleMcpToolExchange,
        provider_request_id: str,
        provider_units_charged: Decimal,
        credits_remaining: int | None,
    ) -> SumbleMcpSnapshot:
        async with self._conn_factory() as conn:
            operation, row = await self._locked_dispatch(
                conn, plan=plan, authorization=authorization, lease_key=lease_key
            )
            response_payload = {
                "contract": "sumble-mcp-response-v1",
                "request_fingerprint": plan.request_fingerprint,
                "catalog_fingerprint": plan.catalog_fingerprint,
                "tool_name": plan.tool_name,
                "session_id": exchange.session_id,
                "jsonrpc_request_id": exchange.jsonrpc_request_id,
                "raw_result": exchange.raw_response,
                "payload": exchange.payload,
                "provider_request_id": provider_request_id,
                "provider_units_charged": str(provider_units_charged),
                "credits_remaining": credits_remaining,
            }
            response_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=plan.workspace_id,
                content=_json_bytes(response_payload),
                media_type="application/json",
                source_key=plan.source_key,
                source_url=SUMBLE_MCP_ENDPOINT,
            )
            await self._bind(
                conn,
                operation,
                response_key,
                reference_kind="sumble_mcp_response",
                reference_id=f"{operation.operation_id}:{plan.source_key}:response",
            )
            cost = provider_units_charged * self._cents_per_credit
            stored = await update_account_gap_snapshot(
                conn,
                snapshot=row.model_copy(
                    update={
                        "state": AccountGapSnapshotState.SUCCEEDED,
                        "spend_outcome": AccountGapSpendOutcome.CHARGED,
                        "response_artifact_key": response_key,
                        "provider_request_id": provider_request_id,
                        "provider_units_charged": provider_units_charged,
                        "credits_remaining": credits_remaining,
                        "cost_cents_charged": cost,
                        "terminal_at": terminal_now(),
                    }
                ),
            )
            if stored.response_artifact_key is None:
                raise SumbleMcpJournalError(
                    "successful Sumble MCP snapshot lost its response artifact"
                )
        return SumbleMcpSnapshot(
            source_key=plan.source_key,
            tool_name=plan.tool_name,
            request_fingerprint=plan.request_fingerprint,
            catalog_fingerprint=plan.catalog_fingerprint,
            provider_request_id=provider_request_id,
            provider_units_charged=provider_units_charged,
            credits_remaining=credits_remaining,
            payload=exchange.payload,
            response_artifact_key=stored.response_artifact_key,
            cost_cents_charged=stored.cost_cents_charged,
        )

    async def mark_spend_unknown(
        self,
        *,
        plan: SumbleMcpInvocationPlan,
        authorization: SumbleMcpDurableAuthorization,
        lease_key: str,
        failure_code: str,
        exchange: SumbleMcpToolExchange | None,
    ) -> None:
        async with self._conn_factory() as conn:
            operation, row = await self._locked_dispatch(
                conn, plan=plan, authorization=authorization, lease_key=lease_key
            )
            response_key: str | None = None
            provider_request_id: str | None = None
            if exchange is not None:
                response_key = await capture_discovery_artifact(
                    conn,
                    self._storage,
                    workspace_id=plan.workspace_id,
                    content=_json_bytes(
                        {
                            "contract": "sumble-mcp-unreconciled-response-v1",
                            "request_fingerprint": plan.request_fingerprint,
                            "catalog_fingerprint": plan.catalog_fingerprint,
                            "tool_name": plan.tool_name,
                            "session_id": exchange.session_id,
                            "jsonrpc_request_id": exchange.jsonrpc_request_id,
                            "raw_result": exchange.raw_response,
                            "payload": exchange.payload,
                            "failure_code": failure_code,
                        }
                    ),
                    media_type="application/json",
                    source_key=plan.source_key,
                    source_url=SUMBLE_MCP_ENDPOINT,
                )
                provider_request_id = (
                    f"mcp:{exchange.session_id or 'stateless'}:{exchange.jsonrpc_request_id}"
                )
                await self._bind(
                    conn,
                    operation,
                    response_key,
                    reference_kind="sumble_mcp_unreconciled_response",
                    reference_id=f"{operation.operation_id}:{plan.source_key}:unknown",
                )
            await update_account_gap_snapshot(
                conn,
                snapshot=row.model_copy(
                    update={
                        "state": AccountGapSnapshotState.SPEND_OUTCOME_UNKNOWN,
                        "spend_outcome": AccountGapSpendOutcome.UNKNOWN,
                        "response_artifact_key": response_key,
                        "provider_request_id": provider_request_id,
                        "failure_code": failure_code,
                        "terminal_at": terminal_now(),
                    }
                ),
            )

    def _assert_parent(
        self,
        operation: AccountGapOperation,
        plan: SumbleMcpInvocationPlan,
    ) -> None:
        if (
            operation.operation_id != self._operation.operation_id
            or operation.request_fingerprint != self._operation.request_fingerprint
        ):
            raise SumbleMcpJournalError("Sumble MCP parent operation identity changed")
        if (
            operation.request.workspace_id != plan.workspace_id
            or operation.request.project_run_id != plan.project_run_id
            or operation.request.account_id != plan.account_id
        ):
            raise SumbleMcpJournalError("Sumble MCP plan has foreign account-gap lineage")
        if operation.state is not AccountGapOperationState.ACQUIRING:
            raise SumbleMcpJournalError(
                "Sumble MCP dispatch requires the durable parent operation lease"
            )
        if (
            operation.request.provider_contract_version != plan.provider_contract_version
            or operation.request.field_policy_version != plan.policy_version
            or operation.request.observation_window != plan.observation_window
        ):
            raise SumbleMcpJournalError(
                "Sumble MCP plan differs from the parent contract or observation window"
            )
        planned_fields = {
            str(item.field_key)
            for item in operation.request.fields
            if item.source_key == plan.source_key
        }
        binding_fields = {str(item.field_key) for item in plan.field_bindings}
        if planned_fields != binding_fields:
            raise SumbleMcpJournalError(
                "Sumble MCP bindings differ from the durably selected account-gap fields"
            )
        if plan.maximum_provider_units > operation.provider_units_reserved:
            raise SumbleMcpJournalError("Sumble MCP plan exceeds the parent provider reservation")
        if plan.maximum_cost_cents != plan.maximum_provider_units * self._cents_per_credit:
            raise SumbleMcpJournalError(
                "Sumble MCP monetary reservation does not match configured credit conversion"
            )
        if plan.maximum_cost_cents > operation.cost_cents_reserved:
            raise SumbleMcpJournalError("Sumble MCP plan exceeds the parent monetary reservation")

    def _assert_authorization(
        self,
        operation: AccountGapOperation,
        plan: SumbleMcpInvocationPlan,
        authorization: SumbleMcpDurableAuthorization,
    ) -> None:
        self._assert_parent(operation, plan)
        if (
            authorization.operation_id != str(operation.operation_id)
            or authorization.durable_reservation_key != _reservation_key(operation, plan)
            or authorization.request_fingerprint != plan.request_fingerprint
            or authorization.catalog_fingerprint != plan.catalog_fingerprint
            or authorization.provider_units_reserved != plan.maximum_provider_units
            or authorization.cost_cents_reserved != plan.maximum_cost_cents
        ):
            raise SumbleMcpJournalError("invalid Sumble MCP durable reservation proof")

    async def _locked_dispatch(
        self,
        conn: Any,
        *,
        plan: SumbleMcpInvocationPlan,
        authorization: SumbleMcpDurableAuthorization,
        lease_key: str,
    ) -> tuple[AccountGapOperation, AccountGapSnapshot]:
        operation = await get_account_gap_operation(
            conn,
            workspace_id=plan.workspace_id,
            operation_id=self._operation.operation_id,
            for_update=True,
        )
        if operation is None:
            raise AccountGapNotFound("Sumble MCP parent account-gap operation")
        self._assert_authorization(operation, plan, authorization)
        if lease_key != authorization.durable_reservation_key:
            raise SumbleMcpJournalError("Sumble MCP dispatch lease does not match authorization")
        row = await get_account_gap_snapshot(
            conn,
            workspace_id=plan.workspace_id,
            operation_id=operation.operation_id,
            source_key=plan.source_key,
            for_update=True,
        )
        if row is None or row.state is not AccountGapSnapshotState.DISPATCHING:
            raise SumbleMcpJournalError("Sumble MCP response has no live dispatch lease")
        if row.request_fingerprint != plan.request_fingerprint:
            raise SumbleMcpJournalError("Sumble MCP dispatch fingerprint changed")
        return operation, row

    async def _load_snapshot(
        self,
        row: AccountGapSnapshot,
        plan: SumbleMcpInvocationPlan,
    ) -> SumbleMcpSnapshot:
        if row.response_artifact_key is None or row.provider_request_id is None:
            raise SumbleMcpJournalError("successful Sumble MCP row lacks response evidence")
        body = await self._storage.get(row.response_artifact_key)
        if not row.response_artifact_key.endswith(content_address(body)):
            raise SumbleMcpJournalError("Sumble MCP response artifact hash mismatch")
        try:
            value = json.loads(body)
        except json.JSONDecodeError as exc:
            raise SumbleMcpJournalError("Sumble MCP response artifact is invalid JSON") from exc
        if not isinstance(value, dict) or value.get("contract") != "sumble-mcp-response-v1":
            raise SumbleMcpJournalError("Sumble MCP response artifact has the wrong contract")
        try:
            artifact_units = Decimal(str(value.get("provider_units_charged")))
        except ArithmeticError as exc:
            raise SumbleMcpJournalError(
                "Sumble MCP response artifact has an invalid credit receipt"
            ) from exc
        if (
            value.get("request_fingerprint") != plan.request_fingerprint
            or value.get("catalog_fingerprint") != plan.catalog_fingerprint
            or value.get("tool_name") != plan.tool_name
            or value.get("provider_request_id") != row.provider_request_id
            or not artifact_units.is_finite()
            or artifact_units != row.provider_units_charged
        ):
            raise SumbleMcpJournalError("Sumble MCP response differs from the durable ledger")
        return SumbleMcpSnapshot(
            source_key=plan.source_key,
            tool_name=plan.tool_name,
            request_fingerprint=plan.request_fingerprint,
            catalog_fingerprint=plan.catalog_fingerprint,
            provider_request_id=row.provider_request_id,
            provider_units_charged=row.provider_units_charged,
            credits_remaining=row.credits_remaining,
            payload=value.get("payload"),
            response_artifact_key=row.response_artifact_key,
            cost_cents_charged=row.cost_cents_charged,
        )

    async def _bind(
        self,
        conn: Any,
        operation: AccountGapOperation,
        artifact_key: str,
        *,
        reference_kind: str,
        reference_id: str,
    ) -> None:
        await bind_discovery_artifact_subject(
            conn,
            workspace_id=operation.request.workspace_id,
            artifact_key_value=artifact_key,
            subject_kind="account",
            subject_entity_id=operation.request.account_id,
            reference_kind=reference_kind,
            reference_id=reference_id,
        )


__all__ = ["AccountGapSumbleMcpJournal", "SumbleMcpJournalError"]
