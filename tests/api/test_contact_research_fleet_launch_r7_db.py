"""Postgres acceptance for M8D R7 exact contact selection and independent launch."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.contact_research_fleet_launch import (
    ContactResearchFleetLauncher,
    ContactResearchFleetLaunchError,
    ContactResearchFleetLaunchRequest,
    ContactResearchSelectionApprovalError,
    ContactResearchSelectionApprovalRequest,
    ContactResearchSelectionApprover,
    ContactResearchTargetApproval,
)
from clue_api.trial.discovery_fixture import WORKSPACE_ID
from clue_core import (
    EntityType,
    ExtractionMethod,
    ResearchMode,
    discovery_claim,
)
from clue_core.entity_research import ResearchRunKind, ResearchSelectionBasis
from clue_fleet import launch_entity_research_run
from clue_research.claimstore import insert_claim
from clue_research.durable import cancel_contact_research_selection
from clue_research.identity import insert_contact_entity, stamp_reuse
from clue_research.profiling.committee import PERSONA, ROLE_ON_COMMITTEE
from clue_research.profiling.committee.admission import DISCOVERY_PROVENANCE_FIELD
from clue_storage import FsStorage
from tests.contact_research.test_c6_contact_selection_db import (
    _materialize,
    _selection_seed,
)
from tests.db.conftest import run_async
from tests.fleet.entity_research_r2_helpers import run_envelope
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


@asynccontextmanager
async def _same_connection(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    yield conn


async def _non_committee_identity_claim(
    conn: AsyncConnection,
    *,
    account_id: UUID,
    account_run_id: UUID,
    suffix: str,
) -> tuple[UUID, UUID]:
    contact_id = await insert_contact_entity(
        conn,
        account_entity_id=account_id,
        full_name=f"Jordan Lee {suffix}",
        linkedin_url=f"https://www.linkedin.com/in/jordan-lee-{suffix}",
        geo={"city": "Portland", "region": "Oregon"},
    )
    identity = stamp_reuse(
        discovery_claim(
            entity_id=contact_id,
            entity_type=EntityType.CONTACT,
            field_key=DISCOVERY_PROVENANCE_FIELD,
            value_json={
                "matched_channel": "sumble_people",
                "matched_signal": "exact LinkedIn identity and current employer",
                "discovery_confidence": 0.99,
            },
            source_tier=1,
            extraction_method=ExtractionMethod.API,
            confidence=0.99,
            run_id=account_run_id,
            research_mode=ResearchMode.COMMITTEE_DISCOVERY,
            found_via="sumble_people",
            matched_signal="exact LinkedIn identity and current employer",
            discovery_confidence=0.99,
            source_url=f"https://www.linkedin.com/in/jordan-lee-{suffix}",
        ),
        workspace_id=WORKSPACE_ID,
    )
    return UUID(str(contact_id)), UUID(str(await insert_claim(conn, identity)))


async def _approved_mixed_selection(
    conn: AsyncConnection,
    tmp_path: Path,
    *,
    suffix: str,
):
    seed = await _selection_seed(
        conn,
        FsStorage(tmp_path / f"artifacts-{suffix}"),
        suffix=suffix,
    )
    initial = await _materialize(seed)
    committee_target = initial.body.targets[0]
    non_committee_id, non_committee_identity_id = await _non_committee_identity_claim(
        conn,
        account_id=UUID(str(seed.account_id)),
        account_run_id=UUID(str(seed.account_run_id)),
        suffix=suffix,
    )
    committee_claim_ids = tuple(
        UUID(str(value))
        for value in committee_target.committee_claim_ids
        if value != committee_target.strong_identity_claim_ids[0]
    )
    approval = ContactResearchSelectionApprovalRequest(
        workspace_id=WORKSPACE_ID,
        project_run_id=UUID(str(seed.project_run_id)),
        account_run_id=UUID(str(seed.account_run_id)),
        account_entity_id=UUID(str(seed.account_id)),
        targets=(
            ContactResearchTargetApproval(
                contact_entity_id=UUID(str(seed.contact_id)),
                selection_basis=ResearchSelectionBasis.COMMITTEE_MEMBER,
                strong_identity_claim_ids=tuple(
                    UUID(str(value)) for value in committee_target.strong_identity_claim_ids
                ),
                association_evidence_claim_ids=tuple(
                    UUID(str(value))
                    for value in committee_target.effective_association_evidence_claim_ids
                ),
                committee_claim_ids=committee_claim_ids,
                field_keys=tuple(str(value) for value in committee_target.field_keys),
                field_source_authority=committee_target.field_source_authority,
                directional_question_ids=committee_target.directional_question_ids,
                facet_keys=tuple(str(value) for value in committee_target.effective_facet_keys),
                budget_cap_cents=Decimal("5.00"),
            ),
            ContactResearchTargetApproval(
                contact_entity_id=non_committee_id,
                selection_basis=(ResearchSelectionBasis.USER_SELECTED_ASSOCIATED_CONTACT),
                strong_identity_claim_ids=(non_committee_identity_id,),
                association_evidence_claim_ids=(non_committee_identity_id,),
                field_keys=tuple(str(value) for value in committee_target.field_keys),
                field_source_authority=committee_target.field_source_authority,
                directional_question_ids=committee_target.directional_question_ids,
                facet_keys=tuple(str(value) for value in committee_target.effective_facet_keys),
                budget_cap_cents=Decimal("7.00"),
            ),
        ),
    )
    approved_at = datetime.now(UTC)
    operation_id = uuid4()
    approver = ContactResearchSelectionApprover(conn_factory=conn_session_factory(conn))
    selection = await approver.approve(
        approval,
        approved_by="human:r7-owner",
        action_ref=f"turn:r7-select:{suffix}",
        approval_operation_id=operation_id,
        approved_at=approved_at,
    )
    return seed, initial, selection, approval, operation_id, approved_at, non_committee_id


def test_non_committee_and_committee_contacts_launch_with_exact_local_authority(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            (
                seed,
                initial,
                selection,
                approval,
                approval_operation_id,
                approved_at,
                non_committee_id,
            ) = await _approved_mixed_selection(
                conn,
                tmp_path,
                suffix="r7-mixed-launch",
            )
            predecessor_id = (
                await conn.execute(
                    text("SELECT predecessor_id FROM contact_research_selection WHERE id=:id"),
                    {"id": selection.selection_id},
                )
            ).scalar_one()
            assert predecessor_id == initial.selection_id
            assert {target.selection_basis for target in selection.body.targets} == {
                ResearchSelectionBasis.COMMITTEE_MEMBER,
                ResearchSelectionBasis.USER_SELECTED_ASSOCIATED_CONTACT,
            }
            assert selection.body.budget_cap_cents == Decimal("12.00")
            assert all(
                target.field_source_authority and target.facet_keys == target.effective_facet_keys
                for target in selection.body.targets
            )

            # The attributed approval operation is replay-safe and cannot change the approved
            # contact set or target-local research authority.
            replay = await ContactResearchSelectionApprover(
                conn_factory=conn_session_factory(conn)
            ).approve(
                approval,
                approved_by="human:r7-owner",
                action_ref="turn:r7-select:r7-mixed-launch",
                approval_operation_id=approval_operation_id,
                approved_at=approved_at,
            )
            assert replay == selection

            launch_request = ContactResearchFleetLaunchRequest(
                workspace_id=WORKSPACE_ID,
                selection_id=UUID(str(selection.selection_id)),
                selection_sha256=selection.selection_sha256,
                approved_budget_cap_cents=Decimal("12.00"),
                expected_estimated_cost_cents=Decimal("12.00"),
                concurrency_limit=2,
            )
            launch_operation_id = uuid4()
            launched_at = approved_at + timedelta(seconds=1)
            launcher = ContactResearchFleetLauncher(conn_factory=conn_session_factory(conn))
            launched = await launcher.launch(
                launch_request,
                actor="human:r7-owner",
                source_action_ref="turn:r7-launch:mixed",
                source_operation_id=launch_operation_id,
                confirmed_at=launched_at,
            )
            assert launched.contact_selection_id == UUID(str(selection.selection_id))
            assert launched.budget_cap_cents == Decimal("12.00")
            assert launched.concurrency_limit == 2
            assert len(launched.jobs) == 2
            by_contact = {job.contact_entity_id: job for job in launched.jobs}
            non_committee = by_contact[non_committee_id]
            assert (
                non_committee.selection_basis
                is ResearchSelectionBasis.USER_SELECTED_ASSOCIATED_CONTACT
            )
            assert non_committee.budget_cap_cents == Decimal("7.00")
            assert non_committee.field_keys == tuple(
                str(value) for value in selection.body.targets[1].field_keys
            )
            assert non_committee.field_source_authority == (
                selection.body.targets[1].field_source_authority
            )
            assert non_committee.source_keys == tuple(
                source
                for authority in non_committee.field_source_authority
                for source in authority.source_keys
            )
            assert non_committee.facet_keys == tuple(
                str(value) for value in selection.body.targets[1].facet_keys
            )
            assert non_committee.channel_permissions == ()
            assert non_committee.channel_source_keys == ()
            assert len(non_committee.policy_refs) == 6
            selection_approval_id = (
                await conn.execute(
                    text("SELECT approval_id FROM contact_research_selection WHERE id=:id"),
                    {"id": selection.selection_id},
                )
            ).scalar_one()
            assert non_committee.approval_refs == (
                f"contact-selection-approval:{selection_approval_id}",
                f"contact-launch-operation:{launch_operation_id}",
                "turn:r7-select:r7-mixed-launch",
                "turn:r7-launch:mixed",
            )

            # This person has no committee classification; explicit governed association was the
            # only admission route.
            non_committee_roles = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM claim WHERE entity_id=:contact_id "
                            "AND field_key IN (:role, :persona)"
                        ),
                        {
                            "contact_id": non_committee_id,
                            "role": ROLE_ON_COMMITTEE,
                            "persona": PERSONA,
                        },
                    )
                ).scalar_one()
            )
            assert non_committee_roles == 0

            counts = (
                (
                    await conn.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM entity_research_job "
                            " WHERE research_run_id=:run_id) AS jobs, "
                            "(SELECT count(*) FROM entity_research_contact_job_authority "
                            " WHERE research_run_id=:run_id) AS authorities, "
                            "(SELECT count(*) FROM fleet_task task JOIN entity_research_job job "
                            " ON task.work_id=job.job_id WHERE job.research_run_id=:run_id "
                            " AND task.kind='entity_research_job') AS tasks, "
                            "(SELECT count(*) FROM entity_research_provider_operation "
                            " WHERE project_run_id=:project_run_id AND subject_type='contact' "
                            " AND target_entity_id=ANY(CAST(:contact_ids AS uuid[]))) "
                            "AS provider_operations, "
                            "(SELECT count(*) FROM external_research_operation "
                            " WHERE project_run_id=:project_run_id "
                            " AND contact_id=ANY(CAST(:contact_ids AS uuid[]))) AS external_ops, "
                            "(SELECT count(*) FROM contact_channel_operation "
                            " WHERE project_run_id=:project_run_id "
                            " AND contact_id=ANY(CAST(:contact_ids AS uuid[]))) AS channel_ops"
                        ),
                        {
                            "run_id": launched.research_run_id,
                            "project_run_id": seed.project_run_id,
                            "contact_ids": [seed.contact_id, non_committee_id],
                        },
                    )
                )
                .mappings()
                .one()
            )
            assert counts == {
                "jobs": 2,
                "authorities": 2,
                "tasks": 2,
                "provider_operations": 0,
                "external_ops": 0,
                "channel_ops": 0,
            }

            launch_replay = await launcher.launch(
                launch_request,
                actor="human:r7-owner",
                source_action_ref="turn:r7-launch:mixed",
                source_operation_id=launch_operation_id,
                confirmed_at=launched_at,
            )
            assert launch_replay == launched
            with pytest.raises(
                ContactResearchFleetLaunchError,
                match="operation was replayed with changed authority",
            ):
                await launcher.launch(
                    launch_request,
                    actor="human:r7-owner",
                    source_action_ref="turn:r7-launch:changed",
                    source_operation_id=launch_operation_id,
                    confirmed_at=launched_at,
                )
            replay_counts = (
                (
                    await conn.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM entity_research_run "
                            " WHERE research_run_id=:run_id) AS runs, "
                            "(SELECT count(*) FROM entity_research_job "
                            " WHERE research_run_id=:run_id) AS jobs, "
                            "(SELECT count(*) FROM entity_research_contact_launch "
                            " WHERE workspace_id=:workspace_id "
                            " AND source_operation_id=:operation_id) AS launches"
                        ),
                        {
                            "run_id": launched.research_run_id,
                            "workspace_id": WORKSPACE_ID,
                            "operation_id": launch_operation_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            assert replay_counts == {"runs": 1, "jobs": 2, "launches": 1}

            # The selection cannot be invalidated underneath active R2 jobs. A caller must first
            # cancel/finalize the contact run through the shared fleet's receipt boundary.
            with pytest.raises(
                ContactResearchSelectionApprovalError,
                match="active contact research must be cancelled or terminal",
            ):
                await ContactResearchSelectionApprover(
                    conn_factory=conn_session_factory(conn)
                ).approve(
                    approval,
                    approved_by="human:r7-owner",
                    action_ref="turn:r7-select:while-active",
                    approval_operation_id=uuid4(),
                    approved_at=launched_at + timedelta(seconds=1),
                )
            with pytest.raises(DBAPIError, match="active contact research must terminate"):
                async with conn.begin_nested():
                    await cancel_contact_research_selection(
                        conn,
                        workspace_id=WORKSPACE_ID,
                        selection_id=selection.selection_id,
                        cancelled_by="human:r7-owner",
                        reason_code="changed_while_active",
                    )
            assert (
                int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM "
                                "contact_research_selection_cancellation "
                                "WHERE selection_id=:selection_id"
                            ),
                            {"selection_id": selection.selection_id},
                        )
                    ).scalar_one()
                )
                == 0
            )

    run_async(scenario())


def test_invalid_cancelled_or_superseded_selection_creates_zero_contact_jobs(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            (
                _seed,
                _initial,
                selection,
                approval,
                _approval_operation_id,
                approved_at,
                _non_committee_id,
            ) = await _approved_mixed_selection(
                conn,
                tmp_path,
                suffix="r7-invalid-selection",
            )
            stale_request = ContactResearchFleetLaunchRequest(
                workspace_id=WORKSPACE_ID,
                selection_id=UUID(str(selection.selection_id)),
                selection_sha256=selection.selection_sha256,
                approved_budget_cap_cents=Decimal("12.00"),
                expected_estimated_cost_cents=Decimal("12.00"),
            )
            runs_before = int(
                (await conn.execute(text("SELECT count(*) FROM entity_research_run"))).scalar_one()
            )
            successor = await ContactResearchSelectionApprover(
                conn_factory=conn_session_factory(conn)
            ).approve(
                approval,
                approved_by="human:r7-owner",
                action_ref="turn:r7-select:successor",
                approval_operation_id=uuid4(),
                approved_at=approved_at + timedelta(seconds=1),
            )
            launcher = ContactResearchFleetLauncher(conn_factory=conn_session_factory(conn))
            with pytest.raises(
                ContactResearchFleetLaunchError,
                match="exact active current selection",
            ):
                await launcher.launch(
                    stale_request,
                    actor="human:r7-owner",
                    source_action_ref="turn:r7-launch:stale",
                    source_operation_id=uuid4(),
                    confirmed_at=approved_at + timedelta(seconds=2),
                )
            await cancel_contact_research_selection(
                conn,
                workspace_id=WORKSPACE_ID,
                selection_id=successor.selection_id,
                cancelled_by="human:r7-owner",
                reason_code="selection_changed",
            )
            cancelled_request = stale_request.model_copy(
                update={
                    "selection_id": UUID(str(successor.selection_id)),
                    "selection_sha256": successor.selection_sha256,
                }
            )
            with pytest.raises(
                ContactResearchFleetLaunchError,
                match="exact active current selection",
            ):
                await launcher.launch(
                    cancelled_request,
                    actor="human:r7-owner",
                    source_action_ref="turn:r7-launch:cancelled",
                    source_operation_id=uuid4(),
                    confirmed_at=approved_at + timedelta(seconds=3),
                )
            assert (
                int(
                    (
                        await conn.execute(text("SELECT count(*) FROM entity_research_run"))
                    ).scalar_one()
                )
                == runs_before
            )

    run_async(scenario())


def test_automatic_committee_materialization_is_not_contact_launch_authority(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _selection_seed(
                conn,
                FsStorage(tmp_path / "artifacts-r7-auto-selection"),
                suffix="r7-auto-selection",
            )
            automatic = await _materialize(seed)
            jobs_before = int(
                (await conn.execute(text("SELECT count(*) FROM entity_research_job"))).scalar_one()
            )
            with pytest.raises(
                ContactResearchFleetLaunchError,
                match="explicit human contact-selection approval",
            ):
                await ContactResearchFleetLauncher(conn_factory=conn_session_factory(conn)).launch(
                    ContactResearchFleetLaunchRequest(
                        workspace_id=WORKSPACE_ID,
                        selection_id=UUID(str(automatic.selection_id)),
                        selection_sha256=automatic.selection_sha256,
                        approved_budget_cap_cents=Decimal("1.00"),
                        expected_estimated_cost_cents=Decimal("1.00"),
                    ),
                    actor="human:r7-owner",
                    source_action_ref="turn:r7-launch:auto-selection-forbidden",
                    source_operation_id=uuid4(),
                    confirmed_at=datetime.now(UTC),
                )
            assert (
                int(
                    (
                        await conn.execute(text("SELECT count(*) FROM entity_research_job"))
                    ).scalar_one()
                )
                == jobs_before
            )

    run_async(scenario())


def test_cross_contact_evidence_is_rejected_before_selection_or_job_persistence(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _selection_seed(
                conn,
                FsStorage(tmp_path / "artifacts-r7-cross-contact"),
                suffix="r7-cross-contact",
            )
            initial = await _materialize(seed)
            target = initial.body.targets[0]
            other_contact_id, _ = await _non_committee_identity_claim(
                conn,
                account_id=UUID(str(seed.account_id)),
                account_run_id=UUID(str(seed.account_run_id)),
                suffix="r7-cross-contact",
            )
            request = ContactResearchSelectionApprovalRequest(
                workspace_id=WORKSPACE_ID,
                project_run_id=UUID(str(seed.project_run_id)),
                account_run_id=UUID(str(seed.account_run_id)),
                account_entity_id=UUID(str(seed.account_id)),
                targets=(
                    ContactResearchTargetApproval(
                        contact_entity_id=other_contact_id,
                        selection_basis=(ResearchSelectionBasis.USER_SELECTED_ASSOCIATED_CONTACT),
                        # Both refs belong to the committee contact, not this contact.
                        strong_identity_claim_ids=(UUID(str(target.strong_identity_claim_ids[0])),),
                        association_evidence_claim_ids=(
                            UUID(str(target.strong_identity_claim_ids[0])),
                        ),
                        field_keys=tuple(str(value) for value in target.field_keys),
                        field_source_authority=target.field_source_authority,
                        directional_question_ids=target.directional_question_ids,
                        facet_keys=tuple(str(value) for value in target.effective_facet_keys),
                        budget_cap_cents=Decimal("5.00"),
                    ),
                ),
            )
            jobs_before = int(
                (await conn.execute(text("SELECT count(*) FROM entity_research_job"))).scalar_one()
            )
            with pytest.raises(
                ContactResearchSelectionApprovalError,
                match="missing, stale, or foreign",
            ):
                await ContactResearchSelectionApprover(
                    conn_factory=conn_session_factory(conn)
                ).approve(
                    request,
                    approved_by="human:r7-owner",
                    action_ref="turn:r7-select:foreign-evidence",
                    approval_operation_id=uuid4(),
                    approved_at=datetime.now(UTC),
                )
            counts = (
                (
                    await conn.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM contact_research_selection "
                            " WHERE project_run_id=:project_run_id) AS selections, "
                            "(SELECT count(*) FROM entity_research_job) AS jobs"
                        ),
                        {"project_run_id": seed.project_run_id},
                    )
                )
                .mappings()
                .one()
            )
            assert counts == {"selections": 1, "jobs": jobs_before}

    run_async(scenario())


def test_database_rejects_contact_run_without_durable_selection_and_launch() -> None:
    async def direct_scenario() -> None:
        async with rollback_conn() as conn:
            envelope = run_envelope(ResearchRunKind.CONTACT_RESEARCH)
            with pytest.raises(DBAPIError):
                async with conn.begin_nested():
                    await launch_entity_research_run(conn, envelope)
                    await conn.execute(
                        text("SET CONSTRAINTS entity_research_contact_run_complete IMMEDIATE")
                    )
            assert (
                int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM entity_research_run "
                                "WHERE research_run_id=:run_id"
                            ),
                            {"run_id": envelope.lifecycle.run_id},
                        )
                    ).scalar_one()
                )
                == 0
            )

    run_async(direct_scenario())
