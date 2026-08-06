"""M8C C2 exact contact-subject durability and replay acceptance."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    EntityType,
    ExternalResearchAcquisitionRequest,
    ExternalResearchSnapshotRef,
    ExternalResearchSubjectKind,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
    contact_claim,
    new_claim_id,
    new_run_id,
)
from clue_research.claimstore import insert_claim
from clue_research.durable import (
    ExternalResearchDispatchDecision,
    ExternalResearchOperationRow,
    ExternalResearchReplayConflict,
    ExternalResearchResultArtifactInput,
    adopt_external_research_snapshot,
    claim_external_research_dispatch,
    complete_external_research_success,
    find_active_external_research_operation_for_materialization,
    find_reusable_external_research_operation,
    get_external_research_operation,
    get_external_research_snapshot,
    list_external_research_result_artifacts,
    list_ready_external_research_snapshots,
    reserve_external_research_operation,
)
from clue_research.durable.discovery import capture_discovery_artifact
from clue_research.identity import insert_contact_entity, mark_merged, stamp_reuse
from clue_storage import FsStorage
from tests.api.test_sumble_committee_acquisition_s2b import _setup
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_durable_db")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request(
    seed: Any,
    *,
    contact_id: Any,
    identity_label: str,
    observation_window: str,
    request_fingerprint: str | None = None,
    reuse_fingerprint: str | None = None,
) -> ExternalResearchAcquisitionRequest:
    subject_material = (
        f"{seed.workspace_id}:{seed.project_id}:{seed.account_id}:{contact_id}:{identity_label}"
    )
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
        observation_window=observation_window,
        freshness_policy_ref="freshness:m8c-c2:v1",
        freshness_seconds=3600,
        reuse_fingerprint=reuse_fingerprint or _sha(f"reuse:{subject_material}"),
        request_fingerprint=request_fingerprint
        or _sha(f"request:{subject_material}:{seed.project_run_id}:{observation_window}"),
        wire_request_sha256=_sha(f"wire:{subject_material}"),
        request_payload={
            "subject_kind": "contact",
            "account_id": str(seed.account_id),
            "contact_id": str(contact_id),
            "strong_identity": identity_label,
        },
        cost_cents_reserved=Decimal(10),
    )


async def _artifact(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    workspace_id: str,
    label: str,
) -> str:
    return await capture_discovery_artifact(
        conn,
        storage,
        workspace_id=workspace_id,
        content=f'{{"c2":"{label}"}}'.encode(),
        media_type="application/json",
        source_key="exa_deep",
        source_url=f"https://evidence.example/{label}" if label.startswith("result") else None,
    )


async def _ready_contact_snapshot(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    request: ExternalResearchAcquisitionRequest,
    now: datetime,
) -> tuple[ExternalResearchOperationRow, ExternalResearchSnapshotRef, str]:
    request_key = await _artifact(
        conn, storage, workspace_id=request.workspace_id, label=f"request-{request.contact_id}"
    )
    operation, created = await reserve_external_research_operation(
        conn,
        request=request,
        request_artifact_key=request_key,
        now=now,
    )
    assert created
    dispatch = await claim_external_research_dispatch(
        conn,
        workspace_id=request.workspace_id,
        operation_id=operation.operation_id,
        now=now,
        lease_expires_at=now + timedelta(seconds=60),
    )
    assert dispatch.decision is ExternalResearchDispatchDecision.ACQUIRED
    assert dispatch.attempt_ordinal == 0
    response_key = await _artifact(
        conn, storage, workspace_id=request.workspace_id, label=f"response-{request.contact_id}"
    )
    normalization_key = await _artifact(
        conn,
        storage,
        workspace_id=request.workspace_id,
        label=f"normalization-{request.contact_id}",
    )
    result_key = await _artifact(
        conn, storage, workspace_id=request.workspace_id, label=f"result-{request.contact_id}"
    )
    receipt_key = await _artifact(
        conn, storage, workspace_id=request.workspace_id, label=f"receipt-{request.contact_id}"
    )
    snapshot = await complete_external_research_success(
        conn,
        workspace_id=request.workspace_id,
        operation_id=operation.operation_id,
        attempt_ordinal=0,
        response_artifact_key=response_key,
        normalization_artifact_key=normalization_key,
        provider_request_id=f"provider-{request.contact_id}",
        provider_reported_cost_cents=Decimal(3),
        all_null=False,
        fresh_until=now + timedelta(hours=1),
        result_artifacts=(
            ExternalResearchResultArtifactInput(
                artifact_key=result_key,
                source_url=f"https://evidence.example/result-{request.contact_id}",
                source_title="Exact contact evidence",
            ),
        ),
        receipt_artifact_key=receipt_key,
        now=now,
    )
    return operation, snapshot, request_key


def test_c2_projects_exact_subject_and_blocks_account_or_same_name_cross_reuse(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            seed = await _setup(conn, storage, workspace_id="ws-m8c-c2-subject")
            contact_a = await insert_contact_entity(
                conn,
                account_entity_id=seed.account_id,
                full_name="Alex Morgan",
                linkedin_url="https://linkedin.com/in/alex-morgan-c2-a",
            )
            contact_b = await insert_contact_entity(
                conn,
                account_entity_id=seed.account_id,
                full_name="Alex Morgan",
                linkedin_url="https://linkedin.com/in/alex-morgan-c2-b",
            )
            now = datetime(2026, 8, 5, 4, 30, tzinfo=UTC)
            request_a = _request(
                seed,
                contact_id=contact_a,
                identity_label="linkedin:alex-morgan-c2-a",
                observation_window="window:c2:a",
            )
            request_b = _request(
                seed,
                contact_id=contact_b,
                identity_label="linkedin:alex-morgan-c2-b",
                observation_window="window:c2:b",
            )
            assert request_a.request_fingerprint != request_b.request_fingerprint
            assert request_a.reuse_fingerprint != request_b.reuse_fingerprint

            operation, snapshot, request_key = await _ready_contact_snapshot(
                conn, storage, request=request_a, now=now
            )
            persisted_operation = await get_external_research_operation(
                conn,
                workspace_id=seed.workspace_id,
                operation_id=operation.operation_id,
            )
            persisted_snapshot = await get_external_research_snapshot(
                conn,
                workspace_id=seed.workspace_id,
                operation_id=operation.operation_id,
            )
            assert persisted_operation.subject_kind is ExternalResearchSubjectKind.CONTACT
            assert persisted_operation.subject_entity_id == contact_a
            assert persisted_operation.contact_id == contact_a
            assert persisted_snapshot.subject_kind is ExternalResearchSubjectKind.CONTACT
            assert persisted_snapshot.contact_id == contact_a
            with pytest.raises(ValidationError, match="account external research"):
                ExternalResearchOperationRow.model_validate(
                    {
                        **persisted_operation.model_dump(),
                        "subject_kind": ExternalResearchSubjectKind.ACCOUNT,
                    }
                )
            with pytest.raises(ValidationError, match="contact snapshot requires"):
                ExternalResearchSnapshotRef.model_validate(
                    {**persisted_snapshot.model_dump(), "contact_id": None}
                )

            result_artifact = (
                await list_external_research_result_artifacts(
                    conn,
                    workspace_id=seed.workspace_id,
                    snapshot_id=snapshot.snapshot_id,
                )
            )[0]
            exact_claim = stamp_reuse(
                contact_claim(
                    entity_id=contact_a,
                    field_key="contact.facet.recent_post",
                    value_json="A strongly bound public statement.",
                    source_tier=4,
                    extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                    confidence=0.82,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.CONTACT_PROFILING,
                    identity_binding=IdentityBinding.STRONG,
                    use_class=UseClass.PROFESSIONAL_PUBLIC,
                    source_url=result_artifact.source_url,
                    evidence_span="A strongly bound public statement.",
                ),
                workspace_id=seed.workspace_id,
            ).model_copy(
                update={
                    "source_key": "exa_deep",
                    "artifact_key": result_artifact.artifact_key,
                    "source_operation_ref": str(snapshot.operation_id),
                    "source_snapshot_ref": str(snapshot.snapshot_id),
                    "source_request_ref": snapshot.provider_request_id,
                }
            )
            await insert_claim(conn, exact_claim)
            for missing_refs in (
                {
                    "source_operation_ref": None,
                    "source_snapshot_ref": None,
                    "source_request_ref": None,
                },
                {"source_snapshot_ref": None},
            ):
                missing_lineage_claim = exact_claim.model_copy(
                    update={"id": new_claim_id(), **missing_refs}
                )
                lineage_savepoint = await conn.begin_nested()
                with pytest.raises(DBAPIError, match="require complete operation"):
                    await insert_claim(conn, missing_lineage_claim)
                await lineage_savepoint.rollback()

            wrong_contact_claim = exact_claim.model_copy(
                update={"id": new_claim_id(), "entity_id": contact_b}
            )
            for mismatched_claim in (
                wrong_contact_claim,
                exact_claim.model_copy(
                    update={"id": new_claim_id(), "source_snapshot_ref": str(uuid4())}
                ),
                exact_claim.model_copy(update={"id": new_claim_id(), "artifact_key": request_key}),
            ):
                lineage_savepoint = await conn.begin_nested()
                with pytest.raises(DBAPIError, match="lineage does not match"):
                    await insert_claim(conn, mismatched_claim)
                await lineage_savepoint.rollback()

            exact = await list_ready_external_research_snapshots(
                conn,
                workspace_id=seed.workspace_id,
                project_run_id=seed.project_run_id,
                subject_kind=ExternalResearchSubjectKind.CONTACT,
                account_id=seed.account_id,
                contact_id=contact_a,
                source_key="exa_deep",
                research_directive_id=seed.research_directive.directive_id,
                research_directive_version=seed.research_directive.version,
                research_directive_sha256=seed.research_directive.canonical_json_sha256,
                research_override_id=None,
                research_override_sha256=None,
                now=now,
            )
            assert exact == (snapshot,)
            same_name_other_identity = await list_ready_external_research_snapshots(
                conn,
                workspace_id=seed.workspace_id,
                project_run_id=seed.project_run_id,
                subject_kind=ExternalResearchSubjectKind.CONTACT,
                account_id=seed.account_id,
                contact_id=contact_b,
                source_key="exa_deep",
                research_directive_id=seed.research_directive.directive_id,
                research_directive_version=seed.research_directive.version,
                research_directive_sha256=seed.research_directive.canonical_json_sha256,
                research_override_id=None,
                research_override_sha256=None,
                now=now,
            )
            assert same_name_other_identity == ()
            account_lookup = await list_ready_external_research_snapshots(
                conn,
                workspace_id=seed.workspace_id,
                project_run_id=seed.project_run_id,
                account_id=seed.account_id,
                source_key="exa_deep",
                research_directive_id=seed.research_directive.directive_id,
                research_directive_version=seed.research_directive.version,
                research_directive_sha256=seed.research_directive.canonical_json_sha256,
                research_override_id=None,
                research_override_sha256=None,
                now=now,
            )
            assert account_lookup == ()

            tampered = request_b.model_copy(
                update={
                    "request_fingerprint": request_a.request_fingerprint,
                    "reuse_fingerprint": request_a.reuse_fingerprint,
                    "observation_window": request_a.observation_window,
                    "wire_request_sha256": request_a.wire_request_sha256,
                }
            )
            with pytest.raises(ExternalResearchReplayConflict):
                await reserve_external_research_operation(
                    conn,
                    request=tampered,
                    request_artifact_key=request_key,
                    now=now,
                )
            with pytest.raises(ExternalResearchReplayConflict):
                await adopt_external_research_snapshot(
                    conn,
                    request=request_b,
                    operation_id=operation.operation_id,
                    now=now,
                )

            savepoint = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="matching fresh ready acquisition"):
                await conn.execute(
                    text(
                        "INSERT INTO external_research_snapshot_use ("
                        "workspace_id, project_id, project_run_id, subject_kind, account_id, "
                        "contact_id, source_key, snapshot_id, reuse_fingerprint, "
                        "consumer_request_fingerprint, consumer_observation_window, adopted_at) "
                        "VALUES (:workspace, :project, :run, 'contact', :account, :contact, "
                        "'exa_deep', :snapshot, :reuse, :request, 'window:tampered', :now)"
                    ),
                    {
                        "workspace": seed.workspace_id,
                        "project": seed.project_id,
                        "run": seed.project_run_id,
                        "account": seed.account_id,
                        "contact": contact_b,
                        "snapshot": snapshot.snapshot_id,
                        "reuse": request_a.reuse_fingerprint,
                        "request": request_b.request_fingerprint,
                        "now": now,
                    },
                )
            await savepoint.rollback()

    run_async(scenario())


def test_c2_merged_loser_requires_recompile_for_survivor_and_never_reuses_by_name(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            seed = await _setup(conn, storage, workspace_id="ws-m8c-c2-merge")
            loser = await insert_contact_entity(
                conn,
                account_entity_id=seed.account_id,
                full_name="Jordan Lee",
                linkedin_url="https://linkedin.com/in/jordan-lee-c2-loser",
            )
            survivor = await insert_contact_entity(
                conn,
                account_entity_id=seed.account_id,
                full_name="Jordan Lee",
                linkedin_url="https://linkedin.com/in/jordan-lee-c2-survivor",
            )
            now = datetime(2026, 8, 5, 5, 0, tzinfo=UTC)
            loser_request = _request(
                seed,
                contact_id=loser,
                identity_label="linkedin:jordan-lee-c2-loser",
                observation_window="window:c2:loser",
            )
            operation, snapshot, _ = await _ready_contact_snapshot(
                conn, storage, request=loser_request, now=now
            )
            await mark_merged(conn, EntityType.CONTACT, loser, survivor)

            with pytest.raises(ExternalResearchReplayConflict, match="canonical contact"):
                await find_reusable_external_research_operation(
                    conn,
                    request=loser_request,
                    now=now,
                )
            with pytest.raises(ExternalResearchReplayConflict, match="canonical contact"):
                await list_ready_external_research_snapshots(
                    conn,
                    workspace_id=seed.workspace_id,
                    project_run_id=seed.project_run_id,
                    subject_kind=ExternalResearchSubjectKind.CONTACT,
                    account_id=seed.account_id,
                    contact_id=loser,
                    source_key="exa_deep",
                    research_directive_id=seed.research_directive.directive_id,
                    research_directive_version=seed.research_directive.version,
                    research_directive_sha256=seed.research_directive.canonical_json_sha256,
                    research_override_id=None,
                    research_override_sha256=None,
                    now=now,
                )
            survivor_request = _request(
                seed,
                contact_id=survivor,
                identity_label="linkedin:jordan-lee-c2-survivor",
                observation_window="window:c2:survivor",
            )
            assert survivor_request.request_fingerprint != loser_request.request_fingerprint
            assert (
                await find_reusable_external_research_operation(
                    conn,
                    request=survivor_request,
                    now=now,
                )
                is None
            )
            survivor_ready = await list_ready_external_research_snapshots(
                conn,
                workspace_id=seed.workspace_id,
                project_run_id=seed.project_run_id,
                subject_kind=ExternalResearchSubjectKind.CONTACT,
                account_id=seed.account_id,
                contact_id=survivor,
                source_key="exa_deep",
                research_directive_id=seed.research_directive.directive_id,
                research_directive_version=seed.research_directive.version,
                research_directive_sha256=seed.research_directive.canonical_json_sha256,
                research_override_id=None,
                research_override_sha256=None,
                now=now,
            )
            assert survivor_ready == ()
            assert (
                await get_external_research_snapshot(
                    conn,
                    workspace_id=seed.workspace_id,
                    operation_id=operation.operation_id,
                )
            ) == snapshot, "immutable loser history remains auditable but is not reusable"

    run_async(scenario())


def test_c2_active_materialization_lookup_is_subject_exact(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            seed = await _setup(conn, storage, workspace_id="ws-m8c-c2-active")
            contact = await insert_contact_entity(
                conn,
                account_entity_id=seed.account_id,
                full_name="Taylor Smith",
                linkedin_url="https://linkedin.com/in/taylor-smith-c2",
            )
            request = _request(
                seed,
                contact_id=contact,
                identity_label="linkedin:taylor-smith-c2",
                observation_window="window:c2:active",
            )
            request_key = await _artifact(
                conn, storage, workspace_id=seed.workspace_id, label="request-active"
            )
            operation, created = await reserve_external_research_operation(
                conn,
                request=request,
                request_artifact_key=request_key,
                now=datetime(2026, 8, 5, 5, 30, tzinfo=UTC),
            )
            assert created
            semantic_alias = request.model_copy(
                update={
                    "request_fingerprint": _sha("request:semantic-alias"),
                    "observation_window": "window:c2:semantic-alias",
                }
            )
            reused, alias_created = await reserve_external_research_operation(
                conn,
                request=semantic_alias,
                request_artifact_key=request_key,
                now=datetime(2026, 8, 5, 5, 30, tzinfo=UTC),
            )
            assert not alias_created
            assert reused.operation_id == operation.operation_id
            exact = await find_active_external_research_operation_for_materialization(
                conn,
                workspace_id=seed.workspace_id,
                project_run_id=seed.project_run_id,
                subject_kind=ExternalResearchSubjectKind.CONTACT,
                account_id=seed.account_id,
                contact_id=contact,
                source_key="exa_deep",
                research_directive_id=seed.research_directive.directive_id,
                research_directive_version=seed.research_directive.version,
                research_directive_sha256=seed.research_directive.canonical_json_sha256,
                research_override_id=None,
                research_override_sha256=None,
            )
            assert exact == operation
            account = await find_active_external_research_operation_for_materialization(
                conn,
                workspace_id=seed.workspace_id,
                project_run_id=seed.project_run_id,
                account_id=seed.account_id,
                source_key="exa_deep",
                research_directive_id=seed.research_directive.directive_id,
                research_directive_version=seed.research_directive.version,
                research_directive_sha256=seed.research_directive.canonical_json_sha256,
                research_override_id=None,
                research_override_sha256=None,
            )
            assert account is None

    run_async(scenario())
