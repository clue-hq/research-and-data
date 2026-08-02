"""M6A D1 durable discovery-batch PostgreSQL acceptance tests.

The ordinary tests run inside the shared rollback fixture.  The committed gate is opt-in because
it deliberately spans independent transactions/connections to prove crash recovery and seal-lock
serialization; CI or a developer must point it at a throwaway database and set
``CLUE_D1_COMMITTED_GATE=1``.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    DiscoveryBatchId,
    DiscoveryCandidateAdmissionState,
    DiscoveryCriterionPlan,
    DiscoveryEntityKind,
    DiscoveryEventDisposition,
    DiscoveryFieldResolution,
    DiscoveryFieldResolutionState,
    DiscoveryItemSnapshot,
    DiscoveryItemSnapshotId,
    DiscoveryOperation,
    DiscoveryOperationId,
    DiscoveryOperationState,
    DiscoveryPageReceipt,
    DiscoveryPageResource,
    DiscoveryPlan,
    DiscoveryProviderEvent,
    DiscoverySearchPlan,
    DiscoverySpendOutcome,
    DiscoveryWakeReason,
    DiscoveryWakeRequest,
    ExtractionMethod,
    ICPCreatedFrom,
    ProjectPhase,
    ResearchMode,
    account_claim,
    discovery_provider_external_id,
    new_discovery_batch_id,
    new_discovery_item_snapshot_id,
    new_discovery_operation_id,
    new_discovery_plan_id,
    new_project_run_id,
    revalidate_with,
)
from clue_db import db_lifespan
from clue_research.claimstore import insert_claim, load_core_pack
from clue_research.discovery_scoring import DISCOVERY_ENVELOPE_POLICY_V1
from clue_research.durable import (
    DiscoveryNotFound,
    DiscoveryReplayConflict,
    DiscoverySealBlocked,
    DiscoverySealDraft,
    bind_discovery_artifact_subject,
    capture_discovery_artifact,
    claim_due_discovery_wakes,
    complete_discovery_wake,
    create_discovery_batch,
    ensure_project_run,
    enumerate_discovery_subject_artifacts,
    find_reusable_discovery_operation,
    finish_discovery_event,
    get_discovery_batch,
    get_discovery_batch_status,
    get_discovery_item,
    get_discovery_operation,
    get_discovery_page,
    get_discovery_plan,
    index_account_discovery_artifacts,
    link_discovery_page_item,
    mark_discovery_operation_reconciled,
    normalize_discovery_item,
    put_discovery_candidate_link,
    put_discovery_event,
    put_discovery_field_resolution,
    put_discovery_item,
    put_discovery_operation,
    put_discovery_page,
    put_discovery_plan,
    read_discovery_seal_readiness,
    reconcile_discovery_batch_costs,
    schedule_discovery_wake,
    seal_discovery_batch,
    update_discovery_operation,
)
from clue_research.durable.enums import ProjectRunStatus
from clue_research.icp import create_icp_spec
from clue_research.identity import insert_account_entity
from clue_storage import FsStorage, content_address
from tests._workspace import seed_project, seed_workspace
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_durable_db")


@dataclass(frozen=True)
class _StartedBatch:
    workspace_id: str
    project_id: str
    project_run_id: UUID
    batch_id: DiscoveryBatchId
    operation_id: DiscoveryOperationId
    page_id: UUID | None
    page: DiscoveryPageReceipt | None


@dataclass(frozen=True)
class _ReadyBatch:
    started: _StartedBatch
    item_id: DiscoveryItemSnapshotId
    account_id: UUID
    event_ids: tuple[UUID, ...]
    draft: DiscoverySealDraft
    raw_operation_artifacts: tuple[str, ...]


def _fingerprint(workspace_id: str) -> str:
    return hashlib.sha256(f"{workspace_id}:exa:search-1:2026-08".encode()).hexdigest()


async def _artifact(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    workspace_id: str,
    name: str,
    body: str,
) -> str:
    return await capture_discovery_artifact(
        conn,
        storage,
        workspace_id=workspace_id,
        content=(f'{{"kind":"{name}","body":"{body}"}}').encode(),
        media_type="application/json",
        source_key="exa_websets",
        source_url="https://api.exa.ai/websets/v0",
    )


async def _start_batch(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    workspace_id: str,
    persist_first_page: bool = True,
) -> _StartedBatch:
    project = await seed_project(conn, workspace_id, name="D1 account discovery")
    icp = await create_icp_spec(
        conn,
        workspace_id=workspace_id,
        icp_key="independent-specialty-practices",
        created_from=ICPCreatedFrom.SYNTHESIS,
        field_keys=("core.employee_count", "core.primary_domain"),
        activate=True,
    )
    run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=run_id,
        project_id=project.project_id,
        workspace_id=workspace_id,
        icp_key=icp.icp_key,
        icp_version=icp.version,
        phase=ProjectPhase.DISCOVERY,
        status=ProjectRunStatus.ACTIVE,
    )
    plan = DiscoveryPlan(
        discovery_plan_id=new_discovery_plan_id(),
        plan_version=1,
        workspace_id=workspace_id,
        project_id=project.project_id,
        project_run_id=run_id,
        icp_key=icp.icp_key,
        icp_version=icp.version,
        provider_policy_version="exa-websets-company-v1",
        field_policy_version=DISCOVERY_ENVELOPE_POLICY_V1.version,
        provider_contract_version="exa-websets-v0-2026-08-02",
        channels=("exa_websets",),
        searches=(
            DiscoverySearchPlan(
                search_key="search-1",
                channel_key="exa_websets",
                normalized_query="independent neurosurgery practices in the United States",
                entity_type=DiscoveryEntityKind.COMPANY,
                requested_count=1,
                criteria=(DiscoveryCriterionPlan(description="is an independent practice"),),
            ),
        ),
        required_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.required_fields,
        optional_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.optional_fields,
        provider_credit_cap=50,
        money_budget_cap_cents=Decimal("500"),
        stopping_policy={"requested_count": 1},
        snapshot_reuse_policy="same_observation_window",
    )
    await put_discovery_plan(conn, workspace_id=workspace_id, plan=plan)
    batch_id = new_discovery_batch_id()
    await create_discovery_batch(
        conn,
        workspace_id=workspace_id,
        batch_id=batch_id,
        plan_id=plan.discovery_plan_id,
        generation=1,
    )
    operation_id = new_discovery_operation_id()
    fingerprint = _fingerprint(workspace_id)
    planned = DiscoveryOperation(
        operation_id=operation_id,
        batch_id=batch_id,
        workspace_id=workspace_id,
        source_key="exa_websets",
        provider_api_version="v0",
        request_fingerprint=fingerprint,
        observation_window="2026-08",
        provider_external_id=discovery_provider_external_id(fingerprint),
        state=DiscoveryOperationState.PLANNED,
        spend_outcome=DiscoverySpendOutcome.NOT_DISPATCHED,
        provider_units_reserved=Decimal("20"),
    )
    assert (
        await put_discovery_operation(conn, workspace_id=workspace_id, operation=planned) == planned
    )
    # Same semantic request reuses the row.  A separately minted operation cannot purchase it
    # again: the persisted request fingerprint is the durable idempotency key.
    assert (
        await put_discovery_operation(conn, workspace_id=workspace_id, operation=planned) == planned
    )
    with pytest.raises(DiscoveryReplayConflict):
        await put_discovery_operation(
            conn,
            workspace_id=workspace_id,
            operation=planned.model_copy(update={"operation_id": new_discovery_operation_id()}),
        )

    page_id: UUID | None = None
    page: DiscoveryPageReceipt | None = None
    if persist_first_page:
        page_bytes = b'{"kind":"items-page","items":["insighthealth.ai"]}'
        page_key = await capture_discovery_artifact(
            conn,
            storage,
            workspace_id=workspace_id,
            content=page_bytes,
            media_type="application/json",
            source_key="exa_websets",
            source_url="https://api.exa.ai/websets/v0/items",
        )
        page = DiscoveryPageReceipt(
            operation_id=operation_id,
            resource_kind=DiscoveryPageResource.ITEMS,
            has_more=False,
            payload_artifact_key=page_key,
            payload_sha256=content_address(page_bytes),
            item_count=1,
            fetched_at=datetime.now(UTC),
        )
        page_id = await put_discovery_page(conn, workspace_id=workspace_id, page=page)
        assert await put_discovery_page(conn, workspace_id=workspace_id, page=page) == page_id
        assert (
            await get_discovery_page(
                conn,
                workspace_id=workspace_id,
                operation_id=operation_id,
                resource_kind="items",
            )
            == page
        )
    return _StartedBatch(
        workspace_id=workspace_id,
        project_id=project.project_id,
        project_run_id=run_id,
        batch_id=batch_id,
        operation_id=operation_id,
        page_id=page_id,
        page=page,
    )


async def _complete_batch(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    started: _StartedBatch,
) -> _ReadyBatch:
    workspace_id = started.workspace_id
    assert started.page_id is not None
    request_key = await _artifact(
        conn, storage, workspace_id=workspace_id, name="request", body="search-1"
    )
    submit_key = await _artifact(
        conn, storage, workspace_id=workspace_id, name="submit-receipt", body="accepted"
    )
    final_key = await _artifact(
        conn, storage, workspace_id=workspace_id, name="final-receipt", body="completed"
    )
    response_key = await _artifact(
        conn, storage, workspace_id=workspace_id, name="response-manifest", body="page-1"
    )

    item_bytes = b'{"id":"exa-item-1","name":"Insight Health AI"}'
    item_key = await capture_discovery_artifact(
        conn,
        storage,
        workspace_id=workspace_id,
        content=item_bytes,
        media_type="application/json",
        source_key="exa_websets",
        source_url="https://www.insighthealth.ai/",
    )
    item_id = new_discovery_item_snapshot_id()
    item = DiscoveryItemSnapshot(
        item_snapshot_id=item_id,
        operation_id=started.operation_id,
        provider_item_id="exa-item-1",
        source_kind="webset_item",
        source_id="https://www.insighthealth.ai/",
        raw_artifact_key=item_key,
        item_sha256=content_address(item_bytes),
        observed_at=datetime.now(UTC),
    )
    assert await put_discovery_item(conn, workspace_id=workspace_id, item=item) == item
    assert await put_discovery_item(conn, workspace_id=workspace_id, item=item) == item
    await link_discovery_page_item(
        conn,
        workspace_id=workspace_id,
        operation_id=started.operation_id,
        page_receipt_id=started.page_id,
        item_snapshot_id=item_id,
        ordinal=0,
    )
    normalized = await normalize_discovery_item(
        conn, workspace_id=workspace_id, item_snapshot_id=item_id
    )
    assert normalized.normalized_at is not None
    assert (
        await get_discovery_item(conn, workspace_id=workspace_id, item_snapshot_id=item_id)
        == normalized
    )

    account_id = await insert_account_entity(
        conn,
        workspace_id=workspace_id,
        canonical_name="Insight Health AI",
        primary_domain="insighthealth.ai",
        hq_geo={"country": "US"},
    )
    await put_discovery_candidate_link(
        conn,
        workspace_id=workspace_id,
        batch_id=started.batch_id,
        item_snapshot_id=item_id,
        admission_status=DiscoveryCandidateAdmissionState.ADMITTED,
        raw_name="Insight Health AI",
        candidate_domain="insighthealth.ai",
        source_url="https://www.insighthealth.ai/",
        account_entity_id=account_id,
        survivor_entity_id=account_id,
    )

    claim_ids = []
    for field_key, value in (
        ("core.industry", "Insight Health AI"),
        ("core.primary_domain", "insighthealth.ai"),
    ):
        claim = revalidate_with(
            account_claim(
                entity_id=account_id,
                field_key=field_key,
                value_json=value,
                source_tier=2,
                extraction_method=ExtractionMethod.API,
                confidence=0.95,
                run_id=started.project_run_id,
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://www.insighthealth.ai/",
                evidence_span=value,
            ),
            source_key="exa_websets",
        )
        claim_ids.append(await insert_claim(conn, claim, validate_field=False))

    now = datetime.now(UTC)
    for index, logical_field in enumerate(DISCOVERY_ENVELOPE_POLICY_V1.required_fields):
        if index < 2:
            resolution = DiscoveryFieldResolution(
                batch_id=started.batch_id,
                account_entity_id=account_id,
                logical_field_key=logical_field,
                state=DiscoveryFieldResolutionState.RESOLVED,
                claim_ids=(claim_ids[index],),
                winning_claim_id=claim_ids[index],
                source_item_ids=(item_id,),
                updated_at=now,
            )
        else:
            resolution = DiscoveryFieldResolution(
                batch_id=started.batch_id,
                account_entity_id=account_id,
                logical_field_key=logical_field,
                state=DiscoveryFieldResolutionState.CONFIRMED_MISSING,
                source_item_ids=(item_id,),
                reason_code="provider_exhausted",
                updated_at=now,
            )
        assert (
            await put_discovery_field_resolution(
                conn, workspace_id=workspace_id, resolution=resolution
            )
            == resolution
        )

    event_ids: list[UUID] = []
    # Deliberately persist event 2 before event 1 and replay event 2: delivery order and duplicate
    # delivery cannot be lifecycle authority.
    for provider_event_id, created_offset in (("evt-2", 2), ("evt-1", 1)):
        event_key = await _artifact(
            conn,
            storage,
            workspace_id=workspace_id,
            name=provider_event_id,
            body="completed",
        )
        event = DiscoveryProviderEvent(
            operation_id=started.operation_id,
            provider_event_id=provider_event_id,
            event_type="webset.completed",
            signature_verified=True,
            payload_artifact_key=event_key,
            provider_created_at=now + timedelta(seconds=created_offset),
            received_at=now + timedelta(seconds=3),
        )
        event_id = await put_discovery_event(conn, workspace_id=workspace_id, event=event)
        assert await put_discovery_event(conn, workspace_id=workspace_id, event=event) == event_id
        await finish_discovery_event(
            conn,
            workspace_id=workspace_id,
            operation_id=started.operation_id,
            provider_event_id=provider_event_id,
            disposition=DiscoveryEventDisposition.PROCESSED,
        )
        await finish_discovery_event(
            conn,
            workspace_id=workspace_id,
            operation_id=started.operation_id,
            provider_event_id=provider_event_id,
            disposition=DiscoveryEventDisposition.PROCESSED,
        )
        event_ids.append(event_id)

    planned = await get_discovery_operation(
        conn, workspace_id=workspace_id, operation_id=started.operation_id
    )
    assert planned is not None
    terminal = DiscoveryOperation.model_validate(
        {
            **planned.model_dump(mode="python"),
            "provider_operation_id": f"exa-webset-{workspace_id}",
            "state": DiscoveryOperationState.SUCCEEDED,
            "spend_outcome": DiscoverySpendOutcome.CHARGED,
            "submitted_receipt_ref": submit_key,
            "final_receipt_ref": final_key,
            "raw_request_artifact_key": request_key,
            "raw_response_manifest_key": response_key,
            "provider_units_charged": Decimal("12"),
            "cost_cents_charged": Decimal("125"),
            "started_at": now,
            "terminal_at": now + timedelta(seconds=4),
        }
    )
    assert (
        await update_discovery_operation(conn, workspace_id=workspace_id, operation=terminal)
        == terminal
    )
    assert (
        await update_discovery_operation(conn, workspace_id=workspace_id, operation=terminal)
        == terminal
    )
    await mark_discovery_operation_reconciled(
        conn,
        workspace_id=workspace_id,
        operation_id=started.operation_id,
        final_reconciliation=True,
        pagination_exhausted=True,
    )
    await reconcile_discovery_batch_costs(
        conn, workspace_id=workspace_id, batch_id=started.batch_id
    )
    raw_refs = await index_account_discovery_artifacts(
        conn,
        workspace_id=workspace_id,
        batch_id=started.batch_id,
        account_entity_id=account_id,
    )

    account_manifest_bytes = b'{"accounts":["insighthealth.ai"]}'
    account_manifest_key = await capture_discovery_artifact(
        conn,
        storage,
        workspace_id=workspace_id,
        content=account_manifest_bytes,
        media_type="application/json",
        source_key="discovery_seal",
    )
    raw_manifest_key = await _artifact(
        conn, storage, workspace_id=workspace_id, name="raw-manifest", body="all-raw-refs"
    )
    claim_manifest_key = await _artifact(
        conn, storage, workspace_id=workspace_id, name="claim-manifest", body="all-claim-ids"
    )
    coverage_key = await _artifact(
        conn, storage, workspace_id=workspace_id, name="coverage", body="one-of-one"
    )
    draft = DiscoverySealDraft(
        account_manifest_artifact_key=account_manifest_key,
        account_manifest_sha256=content_address(account_manifest_bytes),
        raw_artifact_manifest_key=raw_manifest_key,
        claim_id_manifest_key=claim_manifest_key,
        coverage_report_ref=coverage_key,
    )
    return _ReadyBatch(
        started=started,
        item_id=item_id,
        account_id=account_id,
        event_ids=tuple(event_ids),
        draft=draft,
        raw_operation_artifacts=raw_refs,
    )


def test_repository_roundtrip_replay_barrier_wake_and_subject_index(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = f"d1-roundtrip-{os.getpid()}"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started = await _start_batch(conn, storage, workspace_id=workspace_id)
            ready = await _complete_batch(conn, storage, started=started)

            plan_row = await get_discovery_plan(
                conn,
                workspace_id=workspace_id,
                plan_id=(
                    await get_discovery_batch(
                        conn, workspace_id=workspace_id, batch_id=started.batch_id
                    )
                ).discovery_plan_id,  # type: ignore[union-attr]
            )
            assert plan_row is not None
            assert plan_row.plan.workspace_id == workspace_id
            assert (
                await find_reusable_discovery_operation(
                    conn,
                    workspace_id=workspace_id,
                    source_key="exa_websets",
                    request_fingerprint=_fingerprint(workspace_id),
                    observation_window="2026-08",
                )
                is not None
            )

            readiness = await read_discovery_seal_readiness(
                conn,
                workspace_id=workspace_id,
                batch_id=started.batch_id,
                draft=ready.draft,
            )
            assert all(readiness.model_dump().values())

            wake_request = DiscoveryWakeRequest(
                workspace_id=workspace_id,
                project_run_id=started.project_run_id,
                discovery_batch_id=started.batch_id,
                operation_id=started.operation_id,
                reason=DiscoveryWakeReason.SCHEDULED_POLL,
                available_at=datetime.now(UTC) - timedelta(seconds=1),
                dedupe_key=f"{started.operation_id}:terminal-reconcile",
            )
            wake_id = await schedule_discovery_wake(
                conn, workspace_id=workspace_id, request=wake_request
            )
            assert (
                await schedule_discovery_wake(conn, workspace_id=workspace_id, request=wake_request)
                == wake_id
            )
            claimed = await claim_due_discovery_wakes(conn, limit=100)
            assert wake_id in {row.id for row in claimed}
            await complete_discovery_wake(conn, workspace_id=workspace_id, wake_id=wake_id)

            # The finalizer consumes SQL-derived truth only.  A missing artifact blocks even when
            # every caller-side object otherwise looks complete.
            invalid_draft = ready.draft.model_copy(
                update={"coverage_report_ref": f"{workspace_id}/missing"}
            )
            with pytest.raises(DiscoverySealBlocked):
                await seal_discovery_batch(
                    conn,
                    workspace_id=workspace_id,
                    batch_id=started.batch_id,
                    draft=invalid_draft,
                )

            seal = await seal_discovery_batch(
                conn,
                workspace_id=workspace_id,
                batch_id=started.batch_id,
                draft=ready.draft,
            )
            assert (
                await seal_discovery_batch(
                    conn,
                    workspace_id=workspace_id,
                    batch_id=started.batch_id,
                    draft=ready.draft,
                )
                == seal
            )
            status = await get_discovery_batch_status(
                conn, workspace_id=workspace_id, batch_id=started.batch_id
            )
            assert status.batch.state.value == "sealed"
            assert status.seal_blockers == ()
            assert status.seal_sha256 == seal.seal_sha256
            assert status.item_count == 1

            late_key = await _artifact(
                conn,
                storage,
                workspace_id=workspace_id,
                name="late-event",
                body="delivery-after-seal",
            )
            late_event = DiscoveryProviderEvent(
                operation_id=started.operation_id,
                provider_event_id="evt-late",
                event_type="webset.updated",
                signature_verified=True,
                payload_artifact_key=late_key,
                provider_created_at=datetime.now(UTC),
                received_at=datetime.now(UTC),
            )
            late_id = await put_discovery_event(conn, workspace_id=workspace_id, event=late_event)
            late_state = (
                await conn.execute(
                    text(
                        "SELECT processing_disposition::text FROM discovery_provider_event "
                        "WHERE id = :id"
                    ),
                    {"id": late_id},
                )
            ).scalar_one()
            assert late_state == DiscoveryEventDisposition.LATE_AFTER_SEAL.value
            await finish_discovery_event(
                conn,
                workspace_id=workspace_id,
                operation_id=started.operation_id,
                provider_event_id="evt-late",
                disposition=DiscoveryEventDisposition.PROCESSED,
            )
            savepoint = await conn.begin_nested()
            try:
                with pytest.raises(DBAPIError, match="is sealed"):
                    await conn.execute(
                        text(
                            "UPDATE discovery_operation SET updated_at = now() "
                            "WHERE id = :operation_id"
                        ),
                        {"operation_id": started.operation_id},
                    )
            finally:
                await savepoint.rollback()

            subjects = await enumerate_discovery_subject_artifacts(
                conn,
                workspace_id=workspace_id,
                subject_kind="account",
                subject_entity_id=ready.account_id,
            )
            subject_keys = {row.artifact_key for row in subjects}
            assert set(ready.raw_operation_artifacts) <= subject_keys
            assert {
                ready.draft.account_manifest_artifact_key,
                ready.draft.raw_artifact_manifest_key,
                ready.draft.claim_id_manifest_key,
                ready.draft.coverage_report_ref,
            } <= subject_keys

            assert (
                await get_discovery_batch(
                    conn, workspace_id="different-workspace", batch_id=started.batch_id
                )
                is None
            )
            with pytest.raises(DiscoveryNotFound):
                await bind_discovery_artifact_subject(
                    conn,
                    workspace_id="different-workspace",
                    artifact_key_value=ready.draft.account_manifest_artifact_key,
                    subject_kind="account",
                    subject_entity_id=ready.account_id,
                    reference_kind="cross_workspace_probe",
                    reference_id="forbidden",
                )

            other_workspace = await seed_workspace(conn, f"{workspace_id}-other")
            cross_workspace = DiscoveryOperation(
                operation_id=new_discovery_operation_id(),
                batch_id=started.batch_id,
                workspace_id=other_workspace,
                source_key="exa_websets",
                provider_api_version="v0",
                request_fingerprint=hashlib.sha256(b"cross-workspace").hexdigest(),
                observation_window="2026-08",
                provider_external_id="clue-cross-workspace",
                state=DiscoveryOperationState.PLANNED,
                spend_outcome=DiscoverySpendOutcome.NOT_DISPATCHED,
            )
            savepoint = await conn.begin_nested()
            try:
                with pytest.raises(IntegrityError):
                    await put_discovery_operation(
                        conn, workspace_id=other_workspace, operation=cross_workspace
                    )
            finally:
                await savepoint.rollback()

            with pytest.raises(ValueError, match="forbidden credential"):
                await capture_discovery_artifact(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    content=b'{"api_key":"must-never-persist"}',
                    media_type="application/json",
                    source_key="exa_websets",
                )

    run_async(_run())


def test_all_fourteen_sql_readiness_predicates_can_independently_block(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = f"d1-predicates-{os.getpid()}"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started = await _start_batch(conn, storage, workspace_id=workspace_id)
            ready = await _complete_batch(conn, storage, started=started)
            baseline = await read_discovery_seal_readiness(
                conn,
                workspace_id=workspace_id,
                batch_id=started.batch_id,
                draft=ready.draft,
            )
            assert all(baseline.model_dump().values())

            other_account = await insert_account_entity(
                conn,
                workspace_id=workspace_id,
                canonical_name="Other account",
                primary_domain="other-d1.example",
            )
            tests: tuple[tuple[str, str, dict[str, object]], ...] = (
                (
                    "plan_lineage_matches",
                    "UPDATE project_run SET icp_version = 99 WHERE id = :run_id",
                    {"run_id": started.project_run_id},
                ),
                (
                    "operations_terminal",
                    "UPDATE discovery_operation SET state = 'provider_running', terminal_at = NULL "
                    "WHERE id = :operation_id",
                    {"operation_id": started.operation_id},
                ),
                (
                    "dispatch_receipts_complete",
                    "UPDATE discovery_operation SET state = 'provider_running', "
                    "terminal_at = NULL, "
                    "submitted_receipt_ref = NULL WHERE id = :operation_id",
                    {"operation_id": started.operation_id},
                ),
                (
                    "provider_events_accounted",
                    "UPDATE discovery_provider_event SET processing_disposition = 'pending', "
                    "processed_at = NULL WHERE id = :event_id",
                    {"event_id": ready.event_ids[0]},
                ),
                (
                    "final_reconciliation_complete",
                    "UPDATE discovery_operation SET final_reconciled_at = NULL "
                    "WHERE id = :operation_id",
                    {"operation_id": started.operation_id},
                ),
                (
                    "pagination_exhausted",
                    "UPDATE discovery_operation SET pagination_exhausted_at = NULL "
                    "WHERE id = :operation_id",
                    {"operation_id": started.operation_id},
                ),
                (
                    "items_materialized",
                    "UPDATE discovery_item_snapshot SET normalization_state = 'raw', "
                    "normalized_at = NULL WHERE id = :item_id",
                    {"item_id": ready.item_id},
                ),
                (
                    "candidate_identities_terminal",
                    "UPDATE discovery_candidate_link SET admission_status = 'pending', "
                    "account_entity_id = NULL, survivor_entity_id = NULL, "
                    "disposition_reason = NULL "
                    "WHERE batch_id = :batch_id AND item_snapshot_id = :item_id",
                    {"batch_id": started.batch_id, "item_id": ready.item_id},
                ),
                (
                    "hard_identities_complete",
                    "UPDATE account_entity SET primary_domain = NULL WHERE id = :account_id",
                    {"account_id": ready.account_id},
                ),
                (
                    "required_fields_terminal",
                    "UPDATE discovery_field_resolution SET state = 'pending', reason_code = NULL "
                    "WHERE batch_id = :batch_id AND logical_field_key = "
                    "'discovery.company_linkedin_url'",
                    {"batch_id": started.batch_id},
                ),
                (
                    "claims_or_dispositions_complete",
                    "DELETE FROM discovery_field_claim WHERE resolution_id = "
                    "(SELECT id FROM discovery_field_resolution WHERE batch_id = :batch_id "
                    "AND logical_field_key = 'identity.account_name')",
                    {"batch_id": started.batch_id},
                ),
                (
                    "survivor_links_complete",
                    "UPDATE account_entity SET status = 'merged', merged_into = :other "
                    "WHERE id = :account_id",
                    {"other": other_account, "account_id": ready.account_id},
                ),
                (
                    "spend_reconciled",
                    "UPDATE discovery_batch SET cost_cents_charged = cost_cents_charged + 1 "
                    "WHERE id = :batch_id",
                    {"batch_id": started.batch_id},
                ),
            )
            for attribute, statement, params in tests:
                savepoint = await conn.begin_nested()
                try:
                    await conn.execute(text(statement), params)
                    readiness = await read_discovery_seal_readiness(
                        conn,
                        workspace_id=workspace_id,
                        batch_id=started.batch_id,
                        draft=ready.draft,
                    )
                    assert getattr(readiness, attribute) is False, attribute
                    with pytest.raises(DiscoverySealBlocked):
                        await seal_discovery_batch(
                            conn,
                            workspace_id=workspace_id,
                            batch_id=started.batch_id,
                            draft=ready.draft,
                        )
                finally:
                    await savepoint.rollback()

            missing_manifest = ready.draft.model_copy(
                update={"raw_artifact_manifest_key": f"{workspace_id}/absent"}
            )
            manifest_readiness = await read_discovery_seal_readiness(
                conn,
                workspace_id=workspace_id,
                batch_id=started.batch_id,
                draft=missing_manifest,
            )
            assert manifest_readiness.final_manifests_exist is False
            with pytest.raises(DiscoverySealBlocked):
                await seal_discovery_batch(
                    conn,
                    workspace_id=workspace_id,
                    batch_id=started.batch_id,
                    draft=missing_manifest,
                )

            # Immutable pages cannot be rewritten to make the barrier say something convenient.
            assert started.page_id is not None
            savepoint = await conn.begin_nested()
            try:
                with pytest.raises(DBAPIError, match="immutable"):
                    await conn.execute(
                        text("UPDATE discovery_page_receipt SET item_count = 0 WHERE id = :id"),
                        {"id": started.page_id},
                    )
            finally:
                await savepoint.rollback()

    run_async(_run())


def test_accepted_terminal_failure_seals_without_fabricating_items(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = f"d1-accepted-failure-{os.getpid()}"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started = await _start_batch(
                conn,
                storage,
                workspace_id=workspace_id,
                persist_first_page=False,
            )
            assert started.page_id is None
            request_key = await _artifact(
                conn, storage, workspace_id=workspace_id, name="request", body="search-1"
            )
            submit_key = await _artifact(
                conn, storage, workspace_id=workspace_id, name="submit", body="accepted"
            )
            failure_key = await _artifact(
                conn,
                storage,
                workspace_id=workspace_id,
                name="terminal-failure",
                body="provider-cancelled-no-charge",
            )
            planned = await get_discovery_operation(
                conn, workspace_id=workspace_id, operation_id=started.operation_id
            )
            assert planned is not None
            terminal = DiscoveryOperation.model_validate(
                {
                    **planned.model_dump(mode="python"),
                    "state": DiscoveryOperationState.ACCEPTED_TERMINAL_FAILURE,
                    "spend_outcome": DiscoverySpendOutcome.NOT_CHARGED,
                    "submitted_receipt_ref": submit_key,
                    "final_receipt_ref": failure_key,
                    "raw_request_artifact_key": request_key,
                    "started_at": datetime.now(UTC),
                    "terminal_at": datetime.now(UTC),
                }
            )
            await update_discovery_operation(conn, workspace_id=workspace_id, operation=terminal)
            await mark_discovery_operation_reconciled(
                conn,
                workspace_id=workspace_id,
                operation_id=started.operation_id,
                final_reconciliation=True,
                pagination_exhausted=True,
            )
            await reconcile_discovery_batch_costs(
                conn, workspace_id=workspace_id, batch_id=started.batch_id
            )
            account_bytes = b'{"accounts":[]}'
            account_key = await capture_discovery_artifact(
                conn,
                storage,
                workspace_id=workspace_id,
                content=account_bytes,
                media_type="application/json",
                source_key="discovery_seal",
            )
            raw_key = await _artifact(
                conn, storage, workspace_id=workspace_id, name="raw-manifest", body="failure"
            )
            claim_key = await _artifact(
                conn, storage, workspace_id=workspace_id, name="claim-manifest", body="empty"
            )
            coverage_key = await _artifact(
                conn,
                storage,
                workspace_id=workspace_id,
                name="coverage",
                body="accepted-terminal-failure",
            )
            draft = DiscoverySealDraft(
                account_manifest_artifact_key=account_key,
                account_manifest_sha256=content_address(account_bytes),
                raw_artifact_manifest_key=raw_key,
                claim_id_manifest_key=claim_key,
                coverage_report_ref=coverage_key,
            )
            readiness = await read_discovery_seal_readiness(
                conn,
                workspace_id=workspace_id,
                batch_id=started.batch_id,
                draft=draft,
            )
            assert all(readiness.model_dump().values())
            seal = await seal_discovery_batch(
                conn,
                workspace_id=workspace_id,
                batch_id=started.batch_id,
                draft=draft,
            )
            assert seal.account_count == 0
            assert seal.provider_units_charged == 0
            assert seal.cost_cents_charged == 0

    run_async(_run())


@pytest.mark.skipif(
    os.getenv("CLUE_D1_COMMITTED_GATE") != "1",
    reason="set CLUE_D1_COMMITTED_GATE=1 only with a throwaway PostgreSQL database",
)
def test_committed_crash_resume_and_concurrent_seal_are_identical(tmp_path: Path) -> None:
    """Real commits prove raw-page recovery and two-connection seal serialization."""

    async def _run() -> None:
        workspace_id = f"d1-committed-{os.getpid()}-{datetime.now(UTC).timestamp()}"
        storage = FsStorage(tmp_path / "artifacts")
        async with db_lifespan() as engine:
            # Process A commits the paid operation identity and raw page, then "crashes" before
            # normalization.  Nothing provider-side must be called again on process B.
            async with engine.begin() as conn:
                await load_core_pack(conn)
                started = await _start_batch(conn, storage, workspace_id=workspace_id)

            async with engine.begin() as conn:
                recovered_page = await get_discovery_page(
                    conn,
                    workspace_id=workspace_id,
                    operation_id=started.operation_id,
                    resource_kind="items",
                )
                assert started.page is not None
                assert recovered_page == started.page
                reusable = await find_reusable_discovery_operation(
                    conn,
                    workspace_id=workspace_id,
                    source_key="exa_websets",
                    request_fingerprint=_fingerprint(workspace_id),
                    observation_window="2026-08",
                )
                assert reusable is not None
                assert reusable.operation_id == started.operation_id
                ready = await _complete_batch(conn, storage, started=started)

            async def _seal_from_independent_process() -> object:
                async with engine.begin() as conn:
                    return await seal_discovery_batch(
                        conn,
                        workspace_id=workspace_id,
                        batch_id=started.batch_id,
                        draft=ready.draft,
                    )

            first, second = await asyncio.gather(
                _seal_from_independent_process(), _seal_from_independent_process()
            )
            assert first == second

            async with engine.begin() as conn:
                count = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM discovery_batch_seal "
                            "WHERE workspace_id = :workspace_id AND batch_id = :batch_id"
                        ),
                        {"workspace_id": workspace_id, "batch_id": started.batch_id},
                    )
                ).scalar_one()
                assert count == 1

    run_async(_run())
