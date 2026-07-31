"""Clue Trial Sumble acquisition idempotency and receipt-boundary tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from clue_api.trial import (
    DbSumbleReceiptStore,
    SumbleAcquisitionPending,
    SumbleAcquisitionService,
    SumbleReceiptPersistenceError,
)
from clue_core import new_entity_id, new_run_id
from clue_db import db_lifespan, transaction
from clue_research.durable import get_idempotency_ledger
from clue_research.resolvers.sumble import (
    SumbleClient,
    SumbleCreditBudget,
    SumbleCreditLimitExceeded,
    SumbleSnapshot,
    SumbleSpendOutcomeUnknown,
)
from clue_storage import FsStorage, get_artifact
from tests._workspace import seed_workspace
from tests.db.conftest import run_async

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "clue_trial" / "sumble"


def _fixture(name: str) -> dict[str, Any]:
    payload = json.loads((_FIXTURES / name).read_text())
    assert isinstance(payload, dict)
    return payload


class RecordingHttp:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> object:
        del args, kwargs
        self.calls += 1
        return self.payload


class MemoryReceiptStore:
    def __init__(self) -> None:
        self.records: dict[str, SumbleSnapshot | None] = {}
        self.failed: list[str] = []
        self.succeed_calls = 0

    async def claim(self, operation_key: str) -> SumbleSnapshot | None:
        if operation_key not in self.records:
            self.records[operation_key] = None
            return None
        snapshot = self.records[operation_key]
        if snapshot is None:
            raise SumbleAcquisitionPending(operation_key)
        return snapshot

    async def succeed(self, operation_key: str, snapshot: SumbleSnapshot) -> SumbleSnapshot:
        self.succeed_calls += 1
        durable = snapshot.model_copy(update={"artifact_key": "workspace/artifact"})
        self.records[operation_key] = durable
        return durable

    async def fail(self, operation_key: str) -> None:
        self.failed.append(operation_key)
        self.records.pop(operation_key, None)


async def _replay_scenario() -> None:
    http = RecordingHttp(_fixture("organizations_match.json"))
    receipts = MemoryReceiptStore()
    service = SumbleAcquisitionService(
        client=SumbleClient(
            api_key=SecretStr("fixture"),
            budget=SumbleCreditBudget(maximum=2),
            http=http,
        ),
        receipts=receipts,
    )
    account_run_id = new_run_id()
    entity_id = new_entity_id()

    first = await service.organization(
        account_run_id=account_run_id,
        entity_id=entity_id,
        domain="acme.example",
    )
    replay = await service.organization(
        account_run_id=account_run_id,
        entity_id=entity_id,
        domain="acme.example",
    )

    assert first == replay
    assert replay.artifact_key == "workspace/artifact"
    assert http.calls == 1
    assert receipts.succeed_calls == 1


def test_replay_returns_durable_receipt_without_second_provider_call() -> None:
    asyncio.run(_replay_scenario())


async def _spend_unknown_scenario() -> None:
    class UnknownHttp:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, *args: Any, **kwargs: Any) -> object:
            del args, kwargs
            self.calls += 1
            from clue_core import RetryableResolverError

            raise RetryableResolverError("lost after dispatch")

    http = UnknownHttp()
    service = SumbleAcquisitionService(
        client=SumbleClient(
            api_key=SecretStr("fixture"),
            budget=SumbleCreditBudget(maximum=2),
            http=http,
        ),
        receipts=MemoryReceiptStore(),
    )
    account_run_id = new_run_id()
    entity_id = new_entity_id()

    with pytest.raises(SumbleSpendOutcomeUnknown):
        await service.organization(
            account_run_id=account_run_id,
            entity_id=entity_id,
            domain="acme.example",
        )
    with pytest.raises(SumbleAcquisitionPending):
        await service.organization(
            account_run_id=account_run_id,
            entity_id=entity_id,
            domain="acme.example",
        )
    assert http.calls == 1


def test_spend_unknown_stays_pending_and_cannot_recall_provider() -> None:
    asyncio.run(_spend_unknown_scenario())


async def _preflight_failure_scenario() -> None:
    receipts = MemoryReceiptStore()
    service = SumbleAcquisitionService(
        client=SumbleClient(
            api_key=SecretStr("fixture"),
            budget=SumbleCreditBudget(maximum=1),
            http=RecordingHttp(_fixture("organizations_match.json")),
        ),
        receipts=receipts,
    )

    with pytest.raises(SumbleCreditLimitExceeded):
        await service.organization(
            account_run_id=new_run_id(),
            entity_id=new_entity_id(),
            domain="acme.example",
        )
    assert len(receipts.failed) == 1
    assert receipts.records == {}


def test_preflight_failure_releases_operation_for_corrected_retry() -> None:
    asyncio.run(_preflight_failure_scenario())


async def _receipt_write_failure_scenario() -> None:
    class FailOnceReceiptStore(MemoryReceiptStore):
        async def succeed(self, operation_key: str, snapshot: SumbleSnapshot) -> SumbleSnapshot:
            if self.succeed_calls == 0:
                self.succeed_calls += 1
                raise RuntimeError("storage temporarily unavailable")
            return await super().succeed(operation_key, snapshot)

    http = RecordingHttp(_fixture("organizations_match.json"))
    receipts = FailOnceReceiptStore()
    service = SumbleAcquisitionService(
        client=SumbleClient(
            api_key=SecretStr("fixture"),
            budget=SumbleCreditBudget(maximum=2),
            http=http,
        ),
        receipts=receipts,
    )

    with pytest.raises(SumbleReceiptPersistenceError) as caught:
        await service.organization(
            account_run_id=new_run_id(),
            entity_id=new_entity_id(),
            domain="acme.example",
        )
    durable = await service.retry_persistence(caught.value)

    assert durable.artifact_key == "workspace/artifact"
    assert http.calls == 1


def test_receipt_write_failure_can_retry_persistence_without_provider() -> None:
    asyncio.run(_receipt_write_failure_scenario())


@pytest.mark.usefixtures("require_profiling_db")
def test_db_receipt_store_commits_artifact_and_replays(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace_id = f"ws-sumble-receipt-{uuid4().hex[:12]}"
        storage = FsStorage(tmp_path)
        http = RecordingHttp(_fixture("organizations_match.json"))
        account_run_id = new_run_id()
        entity_id = new_entity_id()

        async with db_lifespan():
            async with transaction() as conn:
                await seed_workspace(conn, workspace_id)
            service = SumbleAcquisitionService(
                client=SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=2),
                    http=http,
                ),
                receipts=DbSumbleReceiptStore(
                    workspace_id=workspace_id,
                    storage=storage,
                ),
            )
            first = await service.organization(
                account_run_id=account_run_id,
                entity_id=entity_id,
                domain="acme.example",
            )
            replay = await service.organization(
                account_run_id=account_run_id,
                entity_id=entity_id,
                domain="acme.example",
            )

            assert first == replay
            assert first.artifact_key is not None
            assert http.calls == 1
            assert json.loads((await storage.get(first.artifact_key)).decode())["credits_used"] == 2
            async with transaction() as conn:
                assert await get_artifact(conn, first.artifact_key) is not None
                rows = await conn.execute(
                    text(
                        "SELECT key FROM idempotency_ledger "
                        "WHERE result_ref->>'artifact_key'=:artifact_key"
                    ),
                    {"artifact_key": first.artifact_key},
                )
                key = str(rows.scalar_one())
                ledger = await get_idempotency_ledger(conn, key)
                assert ledger is not None
                assert ledger.result_ref["credits_used"] == 2

    run_async(scenario())
