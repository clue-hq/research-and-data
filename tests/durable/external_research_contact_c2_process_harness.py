"""Fresh-process harness for M8C C2 contact-subject durability acceptance."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text

from clue_core import ExternalResearchAcquisitionRequest, ExternalResearchSubjectKind
from clue_db import db_lifespan
from clue_research.durable import (
    ExternalResearchResultArtifactInput,
    adopt_external_research_snapshot,
    claim_external_research_dispatch,
    complete_external_research_success,
    find_external_research_operation,
    find_reusable_external_research_operation,
    reserve_external_research_operation,
)
from clue_research.durable.discovery import capture_discovery_artifact
from clue_research.identity import insert_contact_entity
from clue_storage import FsStorage
from tests.api.test_sumble_committee_acquisition_s2b import _setup
from tests.profiling.conftest import seed_packs

_START = datetime(2026, 8, 5, 6, 0, tzinfo=UTC)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request(seed: Any, *, contact_id: Any, label: str) -> ExternalResearchAcquisitionRequest:
    subject = f"{seed.workspace_id}:{seed.account_id}:{contact_id}:{label}"
    return ExternalResearchAcquisitionRequest(
        workspace_id=seed.workspace_id,
        project_id=seed.project_id,
        project_run_id=seed.project_run_id,
        subject_kind=ExternalResearchSubjectKind.CONTACT,
        account_id=seed.account_id,
        contact_id=contact_id,
        icp_key=seed.icp_key,
        icp_version=seed.icp_version,
        research_directive=seed.research_directive,
        source_key="exa_deep",
        observation_window=f"window:m8c-c2:{label}",
        freshness_policy_ref="freshness:m8c-c2-process:v1",
        freshness_seconds=3600,
        reuse_fingerprint=_sha(f"reuse:{subject}"),
        request_fingerprint=_sha(f"request:{subject}:{seed.project_run_id}"),
        wire_request_sha256=_sha(f"wire:{subject}"),
        request_payload={
            "subject_kind": "contact",
            "account_id": str(seed.account_id),
            "contact_id": str(contact_id),
            "strong_identity": f"linkedin:{label}",
        },
        cost_cents_reserved=Decimal(10),
    )


async def _capture(
    conn: Any,
    storage: FsStorage,
    *,
    workspace_id: str,
    label: str,
    content: bytes | None = None,
) -> str:
    return await capture_discovery_artifact(
        conn,
        storage,
        workspace_id=workspace_id,
        content=content or json.dumps({"c2": label}, sort_keys=True).encode(),
        media_type="application/json",
        source_key="exa_deep",
        source_url=f"https://evidence.example/{label}" if label.startswith("result") else None,
    )


def _read_state(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("C2 process state must be an object")
    return value


def _request_from(state: dict[str, Any], key: str) -> ExternalResearchAcquisitionRequest:
    return ExternalResearchAcquisitionRequest.model_validate(state[key])


async def _seed(state_path: Path, storage_root: Path) -> dict[str, object]:
    storage = FsStorage(storage_root)
    async with db_lifespan() as engine, engine.begin() as conn:
        await seed_packs(conn)
        seed = await _setup(conn, storage, workspace_id="ws-m8c-c2-process")
        ready_contact = await insert_contact_entity(
            conn,
            account_entity_id=seed.account_id,
            full_name="Morgan Process",
            linkedin_url="https://linkedin.com/in/morgan-process-c2-ready",
        )
        crash_contact = await insert_contact_entity(
            conn,
            account_entity_id=seed.account_id,
            full_name="Morgan Process",
            linkedin_url="https://linkedin.com/in/morgan-process-c2-crash",
        )
        ready_request = _request(seed, contact_id=ready_contact, label="ready")
        crash_request = _request(seed, contact_id=crash_contact, label="crash")
        ready_key = await _capture(
            conn,
            storage,
            workspace_id=seed.workspace_id,
            label="request-ready",
            content=ready_request.model_dump_json().encode(),
        )
        crash_key = await _capture(
            conn,
            storage,
            workspace_id=seed.workspace_id,
            label="request-crash",
            content=crash_request.model_dump_json().encode(),
        )
        spent = str(
            Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:run"),
                        {"run": seed.project_run_id},
                    )
                ).scalar_one()
            )
        )
    state = {
        "ready_request": ready_request.model_dump(mode="json"),
        "crash_request": crash_request.model_dump(mode="json"),
        "ready_request_key": ready_key,
        "crash_request_key": crash_key,
        "spent_before": spent,
    }
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    return {"seeded": True, "provider_calls": 0}


async def _reserve(state_path: Path, key: str) -> dict[str, object]:
    state = _read_state(state_path)
    request = _request_from(state, key)
    artifact_key = str(state[f"{key.removesuffix('_request')}_request_key"])
    async with db_lifespan() as engine, engine.begin() as conn:
        operation, created = await reserve_external_research_operation(
            conn,
            request=request,
            request_artifact_key=artifact_key,
            now=_START,
        )
    return {
        "operation_id": str(operation.operation_id),
        "created": created,
        "subject_kind": operation.subject_kind.value,
        "contact_id": str(operation.contact_id),
        "provider_calls": 0,
    }


async def _settle(state_path: Path, storage_root: Path) -> dict[str, object]:
    state = _read_state(state_path)
    request = _request_from(state, "ready_request")
    storage = FsStorage(storage_root)
    async with db_lifespan() as engine, engine.begin() as conn:
        operation = await find_external_research_operation(
            conn,
            workspace_id=request.workspace_id,
            source_key=request.source_key,
            request_fingerprint=request.request_fingerprint,
            observation_window=request.observation_window,
        )
        if operation is None:
            raise RuntimeError("ready operation was not reserved")
        dispatch = await claim_external_research_dispatch(
            conn,
            workspace_id=request.workspace_id,
            operation_id=operation.operation_id,
            now=_START,
            lease_expires_at=_START + timedelta(seconds=60),
        )
        if dispatch.attempt_ordinal is None:
            raise RuntimeError("ready operation did not elect a dispatcher")
        response = await _capture(
            conn, storage, workspace_id=request.workspace_id, label="response-ready"
        )
        normalization = await _capture(
            conn, storage, workspace_id=request.workspace_id, label="normalization-ready"
        )
        result = await _capture(
            conn, storage, workspace_id=request.workspace_id, label="result-ready"
        )
        receipt = await _capture(
            conn, storage, workspace_id=request.workspace_id, label="receipt-ready"
        )
        snapshot = await complete_external_research_success(
            conn,
            workspace_id=request.workspace_id,
            operation_id=operation.operation_id,
            attempt_ordinal=dispatch.attempt_ordinal,
            response_artifact_key=response,
            normalization_artifact_key=normalization,
            provider_request_id="provider-c2-process-ready",
            provider_reported_cost_cents=Decimal(3),
            all_null=False,
            fresh_until=_START + timedelta(hours=1),
            result_artifacts=(
                ExternalResearchResultArtifactInput(
                    artifact_key=result,
                    source_url="https://evidence.example/result-ready",
                    source_title="C2 process evidence",
                ),
            ),
            receipt_artifact_key=receipt,
            now=_START,
        )
    return {
        "operation_id": str(operation.operation_id),
        "snapshot_id": str(snapshot.snapshot_id),
        "subject_kind": snapshot.subject_kind.value,
        "contact_id": str(snapshot.contact_id),
        "provider_calls": 0,
    }


async def _replay(state_path: Path) -> dict[str, object]:
    state = _read_state(state_path)
    request = _request_from(state, "ready_request")
    async with db_lifespan() as engine, engine.begin() as conn:
        operation = await find_reusable_external_research_operation(
            conn,
            request=request,
            now=_START + timedelta(seconds=1),
        )
        if operation is None:
            raise RuntimeError("fresh process did not find its exact ready operation")
        snapshot = await adopt_external_research_snapshot(
            conn,
            request=request,
            operation_id=operation.operation_id,
            now=_START + timedelta(seconds=1),
        )
        attempts, receipts, uses, spent = (
            await conn.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM external_research_attempt WHERE operation_id=:op), "
                    "(SELECT count(*) FROM external_research_receipt WHERE operation_id=:op), "
                    "(SELECT count(*) FROM external_research_snapshot_use "
                    " WHERE snapshot_id=:snapshot), "
                    "(SELECT spent_cents FROM project_run WHERE id=:run)"
                ),
                {
                    "op": operation.operation_id,
                    "snapshot": snapshot.snapshot_id,
                    "run": request.project_run_id,
                },
            )
        ).one()
    return {
        "operation_id": str(operation.operation_id),
        "snapshot_id": str(snapshot.snapshot_id),
        "attempts": int(attempts),
        "receipts": int(receipts),
        "uses": int(uses),
        "spent_cents": str(Decimal(spent)),
        "provider_calls": 0,
    }


async def _dispatch_crash(state_path: Path) -> dict[str, object]:
    reserved = await _reserve(state_path, "crash_request")
    state = _read_state(state_path)
    request = _request_from(state, "crash_request")
    async with db_lifespan() as engine, engine.begin() as conn:
        operation = await find_external_research_operation(
            conn,
            workspace_id=request.workspace_id,
            source_key=request.source_key,
            request_fingerprint=request.request_fingerprint,
            observation_window=request.observation_window,
        )
        if operation is None:
            raise RuntimeError("crash operation was not reserved")
        dispatch = await claim_external_research_dispatch(
            conn,
            workspace_id=request.workspace_id,
            operation_id=operation.operation_id,
            now=_START,
            lease_expires_at=_START + timedelta(seconds=60),
        )
    return {
        **reserved,
        "decision": dispatch.decision.value,
        "attempt_ordinal": dispatch.attempt_ordinal,
        "simulated_crash_after_dispatch_claim": True,
    }


async def _resume_crash(state_path: Path, *, expired: bool) -> dict[str, object]:
    state = _read_state(state_path)
    request = _request_from(state, "crash_request")
    now = _START + timedelta(seconds=61 if expired else 30)
    async with db_lifespan() as engine, engine.begin() as conn:
        operation = await find_external_research_operation(
            conn,
            workspace_id=request.workspace_id,
            source_key=request.source_key,
            request_fingerprint=request.request_fingerprint,
            observation_window=request.observation_window,
        )
        if operation is None:
            raise RuntimeError("crash operation is missing")
        claim = await claim_external_research_dispatch(
            conn,
            workspace_id=request.workspace_id,
            operation_id=operation.operation_id,
            now=now,
            lease_expires_at=now + timedelta(seconds=60),
        )
        attempts, receipts, snapshots, spent = (
            await conn.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM external_research_attempt WHERE operation_id=:op), "
                    "(SELECT count(*) FROM external_research_receipt WHERE operation_id=:op), "
                    "(SELECT count(*) FROM external_research_snapshot WHERE operation_id=:op), "
                    "(SELECT spent_cents FROM project_run WHERE id=:run)"
                ),
                {"op": operation.operation_id, "run": request.project_run_id},
            )
        ).one()
    return {
        "operation_id": str(operation.operation_id),
        "decision": claim.decision.value,
        "attempts": int(attempts),
        "receipts": int(receipts),
        "snapshots": int(snapshots),
        "spent_cents": str(Decimal(spent)),
        "provider_calls": 0,
    }


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=("seed", "reserve", "settle", "replay", "dispatch-crash", "join", "expire"),
    )
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "seed":
        result = await _seed(args.state, args.storage_root)
    elif args.mode == "reserve":
        result = await _reserve(args.state, "ready_request")
    elif args.mode == "settle":
        result = await _settle(args.state, args.storage_root)
    elif args.mode == "replay":
        result = await _replay(args.state)
    elif args.mode == "dispatch-crash":
        result = await _dispatch_crash(args.state)
    elif args.mode == "join":
        result = await _resume_crash(args.state, expired=False)
    else:
        result = await _resume_crash(args.state, expired=True)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(_main())
