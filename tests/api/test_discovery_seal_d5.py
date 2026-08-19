"""M6A D5 database acceptance: closed discovery generations and the scoring barrier."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_api.discovery_seal import (
    DbSealedDiscoveryAccountManifestReader,
    DurableDiscoveryPhaseHandler,
)
from clue_core import (
    DiscoveryBatchState,
    DiscoveryEventDisposition,
    DiscoveryProviderEvent,
    DiscoveryWakeReason,
    DiscoveryWakeRequest,
    ExtractionMethod,
    PhaseContext,
    PhaseResult,
    PhaseStatus,
    ProjectPhase,
    ResearchMode,
    account_claim,
    new_discovery_batch_id,
    new_discovery_plan_id,
    revalidate_with,
)
from clue_core.entity_research import SealedDiscoveryLaunchReceipt
from clue_research.claimstore import insert_claim
from clue_research.durable import (
    DbProjectRunStore,
    DiscoveryReplayConflict,
    DiscoverySealConflict,
    PhaseCheckpointStatus,
    PhaseHandlerRegistry,
    ProjectRun,
    cancel_discovery_batch,
    claim_due_discovery_wakes,
    discovery_manifest_members,
    get_checkpoint,
    get_current_discovery_batch,
    get_discovery_batch,
    get_discovery_batch_manifest,
    get_discovery_batch_seal,
    get_discovery_plan,
    pause_discovery_batch,
    put_discovery_plan,
    record_discovery_event,
    replace_discovery_batch,
    resume_discovery_batch,
    schedule_discovery_wake,
    upsert_checkpoint,
)
from clue_research.identity import stamp_reuse
from clue_storage import FsStorage
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn
from tests.durable.test_discovery_batch_d1 import (
    _artifact,
    _complete_batch,
    _start_batch,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _FallbackMustNotRun:
    phase = ProjectPhase.DISCOVERY

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        raise AssertionError(f"durable run {ctx.project_run_id} escaped to legacy discovery")


def test_waits_then_seals_and_project_run_advances_once(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = f"d5-phase-{os.getpid()}"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started = await _start_batch(conn, storage, workspace_id=workspace_id)

            @asynccontextmanager
            async def same_connection():
                yield conn

            handler = DurableDiscoveryPhaseHandler(
                storage=storage,
                fallback=_FallbackMustNotRun(),
                conn_factory=same_connection,
            )
            registry = PhaseHandlerRegistry()
            registry.register(handler)
            machine = ProjectRun(
                store=DbProjectRunStore(conn_factory=same_connection),
                registry=registry,
            )

            waiting = await machine.advance(started.project_run_id)
            assert waiting.phase is ProjectPhase.DISCOVERY
            assert waiting.status.value == "active"
            checkpoint = await get_checkpoint(conn, started.project_run_id, ProjectPhase.DISCOVERY)
            assert checkpoint is not None
            assert checkpoint.status is PhaseCheckpointStatus.WAITING_EXTERNAL
            assert checkpoint.payload["discovery_batch_id"] == str(started.batch_id)
            assert checkpoint.payload["blockers"]

            # Once a run has entered durable discovery, deleting the active row cannot turn it
            # back into a legacy/no-batch run and bypass the barrier.
            savepoint = await conn.begin_nested()
            try:
                with pytest.raises(DBAPIError, match="durable discovery batch.*cannot be deleted"):
                    await conn.execute(
                        text("DELETE FROM discovery_batch WHERE id = :batch_id"),
                        {"batch_id": started.batch_id},
                    )
            finally:
                await savepoint.rollback()

            # The trigger protects the transition even when a caller bypasses ProjectRun.
            savepoint = await conn.begin_nested()
            try:
                with pytest.raises(DBAPIError, match="requires exact current discovery batch seal"):
                    await conn.execute(
                        text("UPDATE project_run SET phase = 'scoring' WHERE id = :run_id"),
                        {"run_id": started.project_run_id},
                    )
            finally:
                await savepoint.rollback()
            savepoint = await conn.begin_nested()
            try:
                with pytest.raises(DBAPIError, match="cannot skip scoring after discovery"):
                    await conn.execute(
                        text("UPDATE project_run SET phase = 'deep' WHERE id = :run_id"),
                        {"run_id": started.project_run_id},
                    )
            finally:
                await savepoint.rollback()

            # D4 has completed, but the API-root D5 handler still owns the canonical final
            # artifacts, relational manifest, seal, checkpoint, and transition.
            ready = await _complete_batch(
                conn,
                storage,
                started=started,
                persist_manifest=False,
            )
            assert (
                await get_discovery_batch_manifest(
                    conn, workspace_id=workspace_id, batch_id=started.batch_id
                )
                is None
            )
            sealed_without_checkpoint = await handler.run(
                PhaseContext(
                    project_run_id=started.project_run_id,
                    project_id=started.project_id,
                    brand_id=waiting.brand_id,
                    phase=ProjectPhase.DISCOVERY,
                    workspace_id=workspace_id,
                    icp_key=waiting.icp_key,
                    icp_version=waiting.icp_version,
                )
            )
            assert sealed_without_checkpoint.status is PhaseStatus.COMPLETED
            savepoint = await conn.begin_nested()
            try:
                with pytest.raises(
                    DBAPIError, match="requires exact committed discovery seal checkpoint"
                ):
                    await conn.execute(
                        text("UPDATE project_run SET phase = 'scoring' WHERE id = :run_id"),
                        {"run_id": started.project_run_id},
                    )
            finally:
                await savepoint.rollback()

            # Even a valid seal and checkpoint cannot advance after lifecycle erasure marks one
            # of the four final artifacts unavailable.
            savepoint = await conn.begin_nested()
            try:
                await conn.execute(
                    text(
                        "UPDATE project_phase_checkpoint SET status = 'committed', "
                        "payload_json = CAST(:payload AS jsonb), committed_at = now() "
                        "WHERE project_run_id = :run_id AND phase = 'discovery'"
                    ),
                    {
                        "run_id": started.project_run_id,
                        "payload": json.dumps(sealed_without_checkpoint.payload),
                    },
                )
                await conn.execute(
                    text(
                        "UPDATE artifact SET erased_at = now() "
                        "WHERE workspace_id = :workspace_id AND storage_key = :storage_key"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "storage_key": sealed_without_checkpoint.payload["account_manifest_ref"],
                    },
                )
                with pytest.raises(DBAPIError, match="requires live discovery manifest artifacts"):
                    await conn.execute(
                        text("UPDATE project_run SET phase = 'scoring' WHERE id = :run_id"),
                        {"run_id": started.project_run_id},
                    )
            finally:
                await savepoint.rollback()

            advanced = await machine.advance(started.project_run_id)
            assert advanced.phase is ProjectPhase.SCORING
            assert advanced.status.value == "active"

            # A caller cannot use the intentional no-numeric-scoring policy as a phase skip: the
            # durable SCORING checkpoint and the human TIER_CHECKPOINT must still occur.
            savepoint = await conn.begin_nested()
            try:
                with pytest.raises(
                    DBAPIError, match="cannot skip the tier checkpoint after scoring"
                ):
                    await conn.execute(
                        text("UPDATE project_run SET phase = 'deep' WHERE id = :run_id"),
                        {"run_id": started.project_run_id},
                    )
            finally:
                await savepoint.rollback()
            savepoint = await conn.begin_nested()
            try:
                with pytest.raises(DBAPIError, match="requires a committed scoring checkpoint"):
                    await conn.execute(
                        text("UPDATE project_run SET phase = 'tier_checkpoint' WHERE id = :run_id"),
                        {"run_id": started.project_run_id},
                    )
            finally:
                await savepoint.rollback()

            await upsert_checkpoint(
                conn,
                project_run_id=started.project_run_id,
                phase=ProjectPhase.SCORING,
                idempotency_key="d5-scoring-bypass-acceptance",
                status=PhaseCheckpointStatus.COMMITTED,
                payload={"scoring_mode": "disabled", "numeric_scores_written": 0},
            )
            await conn.execute(
                text("UPDATE project_run SET phase = 'tier_checkpoint' WHERE id = :run_id"),
                {"run_id": started.project_run_id},
            )
            savepoint = await conn.begin_nested()
            try:
                with pytest.raises(
                    DBAPIError, match="requires an approved committed tier checkpoint"
                ):
                    await conn.execute(
                        text("UPDATE project_run SET phase = 'deep' WHERE id = :run_id"),
                        {"run_id": started.project_run_id},
                    )
            finally:
                await savepoint.rollback()

            await upsert_checkpoint(
                conn,
                project_run_id=started.project_run_id,
                phase=ProjectPhase.TIER_CHECKPOINT,
                idempotency_key="d5-human-checkpoint-acceptance",
                status=PhaseCheckpointStatus.COMMITTED,
                payload={"checkpoint_status": "resumed", "decision_action": "approve"},
            )
            await conn.execute(
                text("UPDATE project_run SET phase = 'deep' WHERE id = :run_id"),
                {"run_id": started.project_run_id},
            )
            assert (
                await conn.execute(
                    text("SELECT phase::text FROM project_run WHERE id = :run_id"),
                    {"run_id": started.project_run_id},
                )
            ).scalar_one() == ProjectPhase.DEEP.value

            seal = await get_discovery_batch_seal(
                conn, workspace_id=workspace_id, batch_id=started.batch_id
            )
            bundle = await get_discovery_batch_manifest(
                conn, workspace_id=workspace_id, batch_id=started.batch_id
            )
            checkpoint = await get_checkpoint(conn, started.project_run_id, ProjectPhase.DISCOVERY)
            assert seal is not None and bundle is not None and checkpoint is not None
            assert checkpoint.status is PhaseCheckpointStatus.COMMITTED
            assert checkpoint.payload["discovery_batch_id"] == str(started.batch_id)
            assert checkpoint.payload["discovery_batch_seal_ref"] == seal.seal_sha256
            assert bundle.seal_draft == ready.draft
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM discovery_batch_manifest WHERE batch_id = :batch_id"
                    ),
                    {"batch_id": started.batch_id},
                )
            ).scalar_one() == 1
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM project_phase_checkpoint "
                        "WHERE project_run_id = :run_id AND phase = 'discovery'"
                    ),
                    {"run_id": started.project_run_id},
                )
            ).scalar_one() == 1

            reader = DbSealedDiscoveryAccountManifestReader(
                storage=storage,
                conn_factory=same_connection,
            )
            accounts = await reader.read(
                workspace_id=workspace_id,
                project_run_id=started.project_run_id,
                icp_key="independent-specialty-practices",
                icp_version=1,
            )
            assert accounts is not None
            assert accounts.account_ids == (ready.account_id,)
            assert accounts.discovery_batch_id == started.batch_id
            assert accounts.seal_sha256 == seal.seal_sha256
            assert accounts.claim_manifest_ref == bundle.claim_manifest_artifact_key
            assert accounts.claim_ids == tuple(bundle.claim_ids)
            assert accounts.required_criteria == ("is an independent practice",)
            assert accounts.required_account_fields
            assert len(accounts.field_resolutions) == len(accounts.required_account_fields)

            # Regression: later Account-profile claims can legitimately reuse the discovery
            # item's raw artifact. The historical live-membership query absorbs that claim, but
            # post-seal authority is the stored bundle/artifacts and must remain unchanged.
            raw_artifact_key = (
                await conn.execute(
                    text(
                        "SELECT item.raw_artifact_key FROM discovery_candidate_link candidate "
                        "JOIN discovery_item_snapshot item ON item.id=candidate.item_snapshot_id "
                        "AND item.workspace_id=candidate.workspace_id "
                        "WHERE candidate.workspace_id=:workspace_id "
                        "AND candidate.batch_id=:batch_id LIMIT 1"
                    ),
                    {"workspace_id": workspace_id, "batch_id": started.batch_id},
                )
            ).scalar_one()
            later_claim = revalidate_with(
                stamp_reuse(
                    account_claim(
                        entity_id=ready.account_id,
                        field_key="core.company_about",
                        value_json="Later Account profiling reused the discovery source artifact.",
                        source_tier=1,
                        extraction_method=ExtractionMethod.API,
                        confidence=0.95,
                        run_id=started.project_run_id,
                        research_mode=ResearchMode.ACCOUNT_PROFILING,
                        source_url="https://example.test/later-profile",
                        evidence_span="Later evidence-backed Account-profile observation.",
                    ),
                    workspace_id=workspace_id,
                ),
                # The regression is about membership's entity+artifact join, independent of the
                # provider. Reuse the fixture's registered discovery source so this focused D5
                # test does not have to fabricate an Exa Deep operation/snapshot/result chain.
                source_key="exa_websets",
                artifact_key=raw_artifact_key,
            )
            later_claim_id = await insert_claim(conn, later_claim, validate_field=False)
            _, live_claim_ids, _ = await discovery_manifest_members(
                conn, workspace_id=workspace_id, batch_id=started.batch_id
            )
            assert UUID(str(later_claim_id)) in live_claim_ids
            assert UUID(str(later_claim_id)) not in bundle.claim_ids

            receipt = SealedDiscoveryLaunchReceipt(
                discovery_batch_id=UUID(str(started.batch_id)),
                discovery_generation=bundle.generation,
                discovery_seal_sha256=seal.seal_sha256,
                account_manifest_ref=bundle.account_manifest_artifact_key,
                account_manifest_sha256=bundle.account_manifest_sha256,
                claim_manifest_ref=bundle.claim_manifest_artifact_key,
                claim_manifest_sha256=bundle.claim_manifest_sha256,
            )
            reread = await reader.read(
                workspace_id=workspace_id,
                project_run_id=started.project_run_id,
                icp_key="independent-specialty-practices",
                icp_version=1,
                discovery_receipt=receipt,
            )
            assert reread is not None
            assert reread.claim_ids == tuple(bundle.claim_ids)

            # A receipt is authority only while it still describes the stored lineage exactly.
            # Every field of it is compared, so a job whose pinned receipt disagrees with the seal
            # it names — a replaced generation, a re-pointed or re-hashed manifest — fails closed
            # instead of quietly researching against a lineage it was never authorized for.
            for mismatch in (
                {"discovery_generation": bundle.generation + 1},
                {"discovery_seal_sha256": "0" * 64},
                {"account_manifest_ref": f"{bundle.account_manifest_artifact_key}-other"},
                {"account_manifest_sha256": "1" * 64},
                {"claim_manifest_ref": f"{bundle.claim_manifest_artifact_key}-other"},
                {"claim_manifest_sha256": "2" * 64},
            ):
                with pytest.raises(DiscoverySealConflict, match="differs from launch receipt"):
                    await reader.read(
                        workspace_id=workspace_id,
                        project_run_id=started.project_run_id,
                        icp_key="independent-specialty-practices",
                        icp_version=1,
                        discovery_receipt=receipt.model_copy(update=mismatch),
                    )

            # A late team-level webhook remains auditable but is explicitly outside the sealed
            # generation. It cannot change candidate membership or field resolution.
            late_key = await _artifact(
                conn,
                storage,
                workspace_id=workspace_id,
                name="d5-late-event",
                body="after-seal",
            )
            _, inserted = await record_discovery_event(
                conn,
                workspace_id=workspace_id,
                event=DiscoveryProviderEvent(
                    operation_id=started.operation_id,
                    provider_event_id="d5-late-event",
                    event_type="webset.updated",
                    signature_verified=True,
                    payload_artifact_key=late_key,
                    provider_created_at=datetime.now(UTC),
                    received_at=datetime.now(UTC),
                ),
            )
            assert inserted is True
            disposition = (
                await conn.execute(
                    text(
                        "SELECT processing_disposition::text FROM discovery_provider_event "
                        "WHERE workspace_id = :workspace_id "
                        "AND provider_event_id = 'd5-late-event'"
                    ),
                    {"workspace_id": workspace_id},
                )
            ).scalar_one()
            assert disposition == DiscoveryEventDisposition.LATE_AFTER_SEAL.value

            for statement in (
                "UPDATE discovery_candidate_link SET raw_name = 'tampered' "
                "WHERE workspace_id = :workspace_id AND batch_id = :batch_id",
                "UPDATE discovery_field_resolution SET reason_code = 'tampered' "
                "WHERE workspace_id = :workspace_id AND batch_id = :batch_id",
                "UPDATE discovery_batch_manifest SET account_ids = '[]'::jsonb "
                "WHERE workspace_id = :workspace_id AND batch_id = :batch_id",
            ):
                savepoint = await conn.begin_nested()
                try:
                    with pytest.raises(DBAPIError, match="sealed|immutable"):
                        await conn.execute(
                            text(statement),
                            {"workspace_id": workspace_id, "batch_id": started.batch_id},
                        )
                finally:
                    await savepoint.rollback()

            replay = await handler.run(
                PhaseContext(
                    project_run_id=started.project_run_id,
                    project_id=started.project_id,
                    brand_id=advanced.brand_id,
                    phase=ProjectPhase.DISCOVERY,
                    workspace_id=workspace_id,
                    icp_key=advanced.icp_key,
                    icp_version=advanced.icp_version,
                )
            )
            assert replay.status is PhaseStatus.COMPLETED
            assert replay.payload["discovery_batch_seal_ref"] == seal.seal_sha256
            assert (
                await reader.read(
                    workspace_id=workspace_id,
                    project_run_id=started.project_run_id,
                    icp_key=advanced.icp_key,
                    icp_version=advanced.icp_version,
                )
            ) == accounts
            await storage.delete(bundle.account_manifest_artifact_key)
            with pytest.raises(
                DiscoverySealConflict, match="account manifest artifact body is absent"
            ):
                await reader.read(
                    workspace_id=workspace_id,
                    project_run_id=started.project_run_id,
                    icp_key=advanced.icp_key,
                    icp_version=advanced.icp_version,
                )

    run_async(_run())


def test_pause_cancel_replace_freezes_old_generation_and_retires_wakes(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = f"d5-generation-{os.getpid()}"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started = await _start_batch(conn, storage, workspace_id=workspace_id)
            wake_id = await schedule_discovery_wake(
                conn,
                workspace_id=workspace_id,
                request=DiscoveryWakeRequest(
                    workspace_id=workspace_id,
                    project_run_id=started.project_run_id,
                    discovery_batch_id=started.batch_id,
                    operation_id=started.operation_id,
                    reason=DiscoveryWakeReason.SCHEDULED_POLL,
                    available_at=datetime.now(UTC) - timedelta(seconds=1),
                    dedupe_key="d5-pause-wake",
                ),
            )
            paused = await pause_discovery_batch(
                conn, workspace_id=workspace_id, batch_id=started.batch_id
            )
            assert paused.state is DiscoveryBatchState.PAUSED_BY_USER
            due = await claim_due_discovery_wakes(conn, limit=100)
            assert wake_id not in {row.id for row in due}

            resumed = await resume_discovery_batch(
                conn, workspace_id=workspace_id, batch_id=started.batch_id
            )
            assert resumed.state is not DiscoveryBatchState.PAUSED_BY_USER
            cancelled = await cancel_discovery_batch(
                conn,
                workspace_id=workspace_id,
                batch_id=started.batch_id,
                reason_code="user_replaced_query",
            )
            assert cancelled.state is DiscoveryBatchState.CANCELLED_UNSEALED
            assert cancelled.failure_code == "user_replaced_query"

            late_key = await _artifact(
                conn,
                storage,
                workspace_id=workspace_id,
                name="cancelled-late-event",
                body="superseded",
            )
            event_id, inserted = await record_discovery_event(
                conn,
                workspace_id=workspace_id,
                event=DiscoveryProviderEvent(
                    operation_id=started.operation_id,
                    provider_event_id="cancelled-late-event",
                    event_type="webset.updated",
                    signature_verified=True,
                    payload_artifact_key=late_key,
                    provider_created_at=datetime.now(UTC),
                    received_at=datetime.now(UTC),
                ),
            )
            assert inserted is True
            disposition = (
                await conn.execute(
                    text(
                        "SELECT processing_disposition::text FROM discovery_provider_event "
                        "WHERE id = :event_id"
                    ),
                    {"event_id": event_id},
                )
            ).scalar_one()
            assert disposition == DiscoveryEventDisposition.SUPERSEDED.value

            batch = await get_discovery_batch(
                conn, workspace_id=workspace_id, batch_id=started.batch_id
            )
            assert batch is not None
            old_plan = await get_discovery_plan(
                conn, workspace_id=workspace_id, plan_id=batch.discovery_plan_id
            )
            assert old_plan is not None
            replacement_plan = old_plan.plan.model_copy(
                update={
                    "discovery_plan_id": new_discovery_plan_id(),
                    "plan_version": old_plan.plan.plan_version + 1,
                }
            )
            await put_discovery_plan(conn, workspace_id=workspace_id, plan=replacement_plan)
            replacement_id = new_discovery_batch_id()
            replacement = await replace_discovery_batch(
                conn,
                workspace_id=workspace_id,
                old_batch_id=started.batch_id,
                new_batch_id=replacement_id,
                new_plan_id=replacement_plan.discovery_plan_id,
            )
            assert replacement.id == replacement_id
            assert replacement.generation == 2
            assert replacement.state is DiscoveryBatchState.PLANNED
            old = await get_discovery_batch(
                conn, workspace_id=workspace_id, batch_id=started.batch_id
            )
            assert old is not None and old.replacement_batch_id == replacement_id
            current = await get_current_discovery_batch(
                conn,
                workspace_id=workspace_id,
                project_run_id=started.project_run_id,
            )
            assert current == replacement
            assert (
                await replace_discovery_batch(
                    conn,
                    workspace_id=workspace_id,
                    old_batch_id=started.batch_id,
                    new_batch_id=replacement_id,
                    new_plan_id=replacement_plan.discovery_plan_id,
                )
                == replacement
            )
            with pytest.raises(DiscoveryReplayConflict):
                await cancel_discovery_batch(
                    conn, workspace_id=workspace_id, batch_id=started.batch_id
                )

            savepoint = await conn.begin_nested()
            try:
                with pytest.raises(DBAPIError, match="terminal"):
                    await conn.execute(
                        text(
                            "UPDATE discovery_operation SET updated_at = now() "
                            "WHERE workspace_id = :workspace_id AND id = :operation_id"
                        ),
                        {
                            "workspace_id": workspace_id,
                            "operation_id": started.operation_id,
                        },
                    )
            finally:
                await savepoint.rollback()

    run_async(_run())
