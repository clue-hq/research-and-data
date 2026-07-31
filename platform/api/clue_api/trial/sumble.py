"""Durable Sumble acquisition receipts for the Clue Trial composition root.

The ordinary resolver protocol is synchronous and field-at-a-time. Calling Sumble from that seam
would pay repeatedly for one reusable organization response and could spend again after a process
crash. The trial therefore acquires each Sumble surface once before the waterfall:

1. claim a stable operation in the shared idempotency ledger;
2. issue exactly one provider request;
3. store the raw JSON in the existing content-addressed artifact substrate;
4. mark the operation succeeded with a reference-only receipt; and
5. hand the durable snapshot to the provider-neutral resolver registry.

A paid call whose outcome or response contract is indeterminate deliberately leaves its operation
``in_progress``. It never becomes automatically reclaimable: an operator must reconcile it rather
than allowing a restart to double-spend.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Protocol

from pydantic import JsonValue, TypeAdapter

from clue_core import (
    EntityId,
    IdempotencyScope,
    RawArtifact,
    RunId,
    idempotency_key,
    serialize_value_json,
)
from clue_db import ConnFactory, transaction
from clue_research.durable import (
    ClaimOutcome,
    DbIdempotencyStore,
    IdempotencyStatus,
    IdempotencyStore,
    finish_idempotency_step,
)
from clue_research.resolvers.sumble import (
    JOBS_SOURCE_KEY,
    ORGANIZATIONS_SOURCE_KEY,
    SUMBLE_API_BASE,
    TECH_STACK_SOURCE_KEY,
    SumbleClient,
    SumbleContractError,
    SumbleSnapshot,
    SumbleSourceKey,
    SumbleSpendOutcomeUnknown,
)
from clue_storage import SnapshotSink, StorageBackend, flush_snapshots

# A provider call with unknown spend must never be automatically stolen as a stale ordinary task.
# This effectively pins it for manual reconciliation while retaining the shared ledger schema.
_MANUAL_RECONCILIATION_WINDOW = timedelta(days=36_500)
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class SumbleAcquisitionPending(RuntimeError):
    """The operation is held by a live or spend-unknown acquisition and must not execute again."""


class SumbleReceiptPersistenceError(RuntimeError):
    """The provider answered, but its response receipt was not durably committed.

    ``snapshot`` lets an in-process operator retry receipt persistence without recalling Sumble.
    A process crash loses that convenience but leaves the ledger pending, still preventing an
    automatic second provider charge.
    """

    def __init__(self, operation_key: str, snapshot: SumbleSnapshot) -> None:
        super().__init__(
            f"Sumble response for {operation_key} was not durably committed; "
            "retry receipt persistence with the attached snapshot, not the provider request"
        )
        self.operation_key = operation_key
        self.snapshot = snapshot


class SumbleReceiptStore(Protocol):
    """Durable, provider-response idempotency seam used by the acquisition service."""

    async def claim(self, operation_key: str) -> SumbleSnapshot | None:
        """Return a prior snapshot on replay, or ``None`` when this caller owns execution."""
        ...

    async def succeed(self, operation_key: str, snapshot: SumbleSnapshot) -> SumbleSnapshot: ...

    async def fail(self, operation_key: str) -> None: ...


def sumble_acquisition_key(
    account_run_id: RunId,
    entity_id: EntityId,
    source_key: SumbleSourceKey,
) -> str:
    """Stable one-call key for an account/run/first-wave Sumble surface."""

    return idempotency_key(
        IdempotencyScope.ACCOUNT_STEP,
        "sumble-acquisition-v1",
        account_run_id,
        entity_id,
        source_key,
    )


def _source_ref(snapshot: SumbleSnapshot) -> str:
    if snapshot.source_key == ORGANIZATIONS_SOURCE_KEY:
        return f"{SUMBLE_API_BASE}/organizations"
    if snapshot.source_key == JOBS_SOURCE_KEY:
        return f"{SUMBLE_API_BASE}/jobs"
    organization_id = snapshot.payload.get("organization_id")
    if not isinstance(organization_id, int):
        raise SumbleContractError(
            "Sumble tech-stack receipt is missing its integer organization_id"
        )
    return f"{SUMBLE_API_BASE}/organizations/{organization_id}/techs"


def _receipt_ref(snapshot: SumbleSnapshot) -> dict[str, JsonValue]:
    if snapshot.artifact_key is None:
        raise ValueError("a successful Sumble receipt must reference its durable artifact")
    return {
        "schema_version": "1",
        "kind": "sumble_response_snapshot",
        "source_key": snapshot.source_key,
        "request_id": snapshot.request_id,
        "credits_used": snapshot.credits_used,
        "credits_remaining": snapshot.credits_remaining,
        "cost_cents": str(snapshot.cost_cents),
        "estimated_max_credits": snapshot.estimated_max_credits,
        "unbounded_call_approved": snapshot.unbounded_call_approved,
        "artifact_key": snapshot.artifact_key,
    }


class DbSumbleReceiptStore:
    """Postgres-ledger + clue-storage implementation of :class:`SumbleReceiptStore`."""

    def __init__(
        self,
        *,
        workspace_id: str,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
        ledger: IdempotencyStore | None = None,
    ) -> None:
        if not workspace_id:
            raise ValueError("Sumble receipt storage requires a non-empty workspace_id")
        self._workspace_id = workspace_id
        self._storage = storage
        self._conn_factory = conn_factory
        self._ledger = ledger or DbIdempotencyStore(conn_factory=conn_factory)

    async def claim(self, operation_key: str) -> SumbleSnapshot | None:
        prior = await self._ledger.get(operation_key)
        if prior is not None and prior.status is IdempotencyStatus.IN_PROGRESS:
            raise SumbleAcquisitionPending(
                f"Sumble acquisition {operation_key} is already pending; "
                "do not retry until its provider spend is reconciled"
            )
        result = await self._ledger.claim(
            key=operation_key,
            scope=IdempotencyScope.ACCOUNT_STEP,
            stale_after=_MANUAL_RECONCILIATION_WINDOW,
        )
        if result.outcome is ClaimOutcome.CONFLICT:
            raise SumbleAcquisitionPending(
                f"Sumble acquisition {operation_key} is already pending; "
                "do not retry until its provider spend is reconciled"
            )
        if result.outcome is ClaimOutcome.EXECUTE:
            return None
        return await self._load_snapshot(result.result_ref)

    async def succeed(self, operation_key: str, snapshot: SumbleSnapshot) -> SumbleSnapshot:
        raw = serialize_value_json(snapshot.payload).encode()
        sink = SnapshotSink(workspace_id=self._workspace_id)
        artifact_key = sink.capture(
            RawArtifact(
                ref=_source_ref(snapshot),
                media_type="application/json",
                content=raw,
                metadata={
                    "provider": "sumble",
                    "request_id": snapshot.request_id,
                    "credits_used": snapshot.credits_used,
                },
            ),
            source_key=snapshot.source_key,
        )
        durable = snapshot.model_copy(update={"artifact_key": artifact_key})
        async with self._conn_factory() as conn:
            await flush_snapshots(conn, self._storage, sink)
            await finish_idempotency_step(
                conn,
                key=operation_key,
                status=IdempotencyStatus.SUCCEEDED,
                result_ref=_receipt_ref(durable),
                cost_cents=durable.cost_cents,
            )
        return durable

    async def fail(self, operation_key: str) -> None:
        await self._ledger.fail(key=operation_key)

    async def _load_snapshot(self, result_ref: dict[str, JsonValue]) -> SumbleSnapshot:
        if result_ref.get("kind") != "sumble_response_snapshot":
            raise SumbleContractError("Sumble replay ledger contains an unexpected result kind")
        artifact_key = result_ref.get("artifact_key")
        if not isinstance(artifact_key, str) or not artifact_key:
            raise SumbleContractError("Sumble replay ledger is missing its artifact reference")
        payload = _JSON_OBJECT.validate_json(await self._storage.get(artifact_key))
        return SumbleSnapshot.model_validate(
            {
                "source_key": result_ref.get("source_key"),
                "request_id": result_ref.get("request_id"),
                "credits_used": result_ref.get("credits_used"),
                "credits_remaining": result_ref.get("credits_remaining"),
                "payload": payload,
                "cost_cents": Decimal(str(result_ref.get("cost_cents", "0"))),
                "estimated_max_credits": result_ref.get("estimated_max_credits"),
                "unbounded_call_approved": result_ref.get("unbounded_call_approved", False),
                "artifact_key": artifact_key,
            }
        )


class SumbleAcquisitionService:
    """Acquire each first-wave Sumble surface exactly once behind durable receipts."""

    def __init__(self, *, client: SumbleClient, receipts: SumbleReceiptStore) -> None:
        self._client = client
        self._receipts = receipts

    async def organization(
        self, *, account_run_id: RunId, entity_id: EntityId, domain: str
    ) -> SumbleSnapshot:
        return await self._execute(
            operation_key=sumble_acquisition_key(
                account_run_id, entity_id, ORGANIZATIONS_SOURCE_KEY
            ),
            acquire=lambda: self._client.resolve_organization(domain),
        )

    async def jobs(
        self, *, account_run_id: RunId, entity_id: EntityId, organization_id: int
    ) -> SumbleSnapshot:
        return await self._execute(
            operation_key=sumble_acquisition_key(account_run_id, entity_id, JOBS_SOURCE_KEY),
            acquire=lambda: self._client.engineering_jobs(organization_id),
        )

    async def tech_stack(
        self,
        *,
        account_run_id: RunId,
        entity_id: EntityId,
        organization_id: int,
        allow_unbounded: bool,
    ) -> SumbleSnapshot:
        return await self._execute(
            operation_key=sumble_acquisition_key(account_run_id, entity_id, TECH_STACK_SOURCE_KEY),
            acquire=lambda: self._client.tech_stack(
                organization_id,
                allow_unbounded=allow_unbounded,
            ),
        )

    async def retry_persistence(self, error: SumbleReceiptPersistenceError) -> SumbleSnapshot:
        """Retry only the durable write using the already-returned provider snapshot."""

        try:
            return await self._receipts.succeed(error.operation_key, error.snapshot)
        except Exception as exc:
            raise SumbleReceiptPersistenceError(error.operation_key, error.snapshot) from exc

    async def _execute(
        self,
        *,
        operation_key: str,
        acquire: Callable[[], SumbleSnapshot],
    ) -> SumbleSnapshot:
        prior = await self._receipts.claim(operation_key)
        if prior is not None:
            return prior
        try:
            snapshot = await asyncio.to_thread(acquire)
        except (SumbleSpendOutcomeUnknown, SumbleContractError):
            # Post-dispatch outcome is unsafe to repeat. Keep the ledger in-progress.
            raise
        except Exception:
            # Known failure (configuration, budget preflight, hard HTTP response) is safe to retry
            # after correction because no successful provider payload was observed.
            await self._receipts.fail(operation_key)
            raise
        try:
            return await self._receipts.succeed(operation_key, snapshot)
        except Exception as exc:
            # Never release the operation after a provider response. The caller can retry the
            # durable write with the attached snapshot without recalling the provider.
            raise SumbleReceiptPersistenceError(operation_key, snapshot) from exc
