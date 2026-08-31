"""FI-2 Slice 6 — the durable Account activity projection.

The real projections app runs against a rolled-back Postgres connection.  Every displayed event is
seeded through the production append-only research-view event + subject-activity writers, then
compared with its source database row.  Unresolvable references and human rows without a durable
actor identity are planted deliberately and must not leak into the response.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_core import (
    AccountStatus,
    Confidence,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    Persona,
    ProjectRunId,
    ResearchMode,
    ResearchViewSnapshotId,
    RunId,
    UseClass,
    VerificationStatus,
    contact_claim,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import insert_claim
from clue_research.durable import (
    AccountRunStatus,
    append_subject_activity,
    ensure_project_run,
    insert_account_run,
    save_references,
)
from clue_research.identity import (
    insert_account_entity,
    insert_contact_entity,
    stamp_reuse,
)
from clue_research.membership import ensure_project_account
from clue_research.narrative import append_research_view_event
from clue_research.profiling.committee import PERSONA, ROLE_ON_COMMITTEE, load_committee_pack
from tests._workspace import seed_project, seed_workspace
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_WS = "fi2-slice6-activity"
_OTHER_WS = "fi2-slice6-activity-other"
_BASE = f"{FRONTEND_READ_PREFIX}/accounts"


def _wire_time(value: datetime) -> str:
    """FastAPI's UTC JSON rendering uses ``Z``; keep the assertion explicit."""

    return value.isoformat().replace("+00:00", "Z")


def _app(conn: AsyncConnection) -> FastAPI:
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(_env_file=None, frontend_read_enabled=True),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
    )


async def _get(
    conn: AsyncConnection,
    account_id: uuid.UUID | str,
    *,
    workspace_id: str = _WS,
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_app(conn)),
        base_url="http://activity",
    ) as client:
        return await client.get(
            f"{_BASE}/{account_id}/activity",
            headers={"X-Workspace-Id": workspace_id},
        )


async def _get_detail(conn: AsyncConnection, account_id: uuid.UUID | str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_app(conn)),
        base_url="http://activity",
    ) as client:
        return await client.get(
            f"{_BASE}/{account_id}",
            headers={"X-Workspace-Id": _WS},
        )


async def _seed_scope(
    conn: AsyncConnection,
) -> tuple[EntityId, EntityId, str, ProjectRunId, RunId]:
    project = await seed_project(conn, _WS, name="Insight Health campaign")
    account_id = await insert_account_entity(
        conn,
        canonical_name="Durable Activity Account",
        primary_domain="activity.example",
        status=AccountStatus.ACTIVE,
        workspace_id=_WS,
    )
    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project.project_id,
        workspace_id=_WS,
        icp_key="default",
        icp_version=1,
    )
    account_run_id = new_run_id()
    await insert_account_run(
        conn,
        account_run_id=account_run_id,
        project_run_id=project_run_id,
        entity_id=account_id,
        tier="top",
        status=AccountRunStatus.DONE,
    )
    await ensure_project_account(
        conn,
        workspace_id=_WS,
        project_id=project.project_id,
        account_entity_id=uuid.UUID(str(account_id)),
        added_via="discovered",
    )
    await load_committee_pack(conn)
    contact_id = await insert_contact_entity(
        conn,
        account_entity_id=account_id,
        full_name="Dana Durable",
        linkedin_url="https://linkedin.com/in/dana-durable",
        status=AccountStatus.ACTIVE,
    )
    claim_ids: list[str] = []
    for field_key, value in (
        (
            ROLE_ON_COMMITTEE,
            {
                "role": Persona.ECONOMIC_BUYER.value,
                "confidence": 1.0,
                "plausible": True,
                "rationale": "seeded",
            },
        ),
        (PERSONA, Persona.ECONOMIC_BUYER.value),
    ):
        claim = stamp_reuse(
            contact_claim(
                entity_id=contact_id,
                field_key=field_key,
                value_json=value,  # type: ignore[arg-type]
                source_tier=1,
                extraction_method=ExtractionMethod.HUMAN,
                confidence=Confidence(1.0),
                run_id=account_run_id,
                research_mode=ResearchMode.COMMITTEE_DISCOVERY,
                identity_binding=IdentityBinding.STRONG,
                use_class=UseClass.PROFESSIONAL_PUBLIC,
                evidence_span=f"evidence for {field_key}",
            ),
            workspace_id=_WS,
        ).model_copy(update={"verification_status": VerificationStatus.VERIFIED})
        await insert_claim(conn, claim)
        claim_ids.append(str(claim.id))
    await save_references(
        conn,
        account_run_id,
        references_index={"committee": claim_ids},
        cost_cents=Decimal("0"),
        status=AccountRunStatus.DONE,
    )
    return account_id, contact_id, project.project_id, project_run_id, account_run_id


async def _snapshot(
    conn: AsyncConnection,
    *,
    subject_entity_id: EntityId,
    subject_entity_type: EntityType,
    parent_account_id: EntityId,
    project_id: str,
    project_run_id: ProjectRunId,
    created_at: datetime,
) -> ResearchViewSnapshotId:
    snapshot_id = ResearchViewSnapshotId(uuid.uuid4())
    await conn.execute(
        text(
            """
            INSERT INTO research_view_snapshot (
                snapshot_id, operation_id, workspace_id, project_id, project_run_id,
                view_id, subject_entity_id, subject_entity_type, subject_entity_version,
                parent_account_entity_id, product_id, schema_version, source_state_sha256,
                composition_sha256, supersedes_snapshot_id, created_at
            ) VALUES (
                :snapshot_id, :operation_id, :workspace_id, :project_id, :project_run_id,
                :view_id, :subject_entity_id, CAST(:subject_entity_type AS entity_type), 1,
                :parent_account_id, NULL, '1.0', :source_hash, :composition_hash, NULL, :created_at
            )
            """
        ),
        {
            "snapshot_id": snapshot_id,
            "operation_id": uuid.uuid4(),
            "workspace_id": _WS,
            "project_id": project_id,
            "project_run_id": project_run_id,
            "view_id": uuid.uuid4(),
            "subject_entity_id": subject_entity_id,
            "subject_entity_type": subject_entity_type.value,
            "parent_account_id": (
                None if subject_entity_type is EntityType.ACCOUNT else parent_account_id
            ),
            "source_hash": "a" * 64,
            "composition_hash": "b" * 64,
            "created_at": created_at,
        },
    )
    return snapshot_id


async def _event(
    conn: AsyncConnection,
    *,
    event_key: str,
    topic: str,
    account_id: EntityId,
    project_id: str,
    project_run_id: ProjectRunId,
    created_at: datetime,
    subject_entity_id: EntityId | None = None,
    subject_entity_type: EntityType = EntityType.ACCOUNT,
    actor_category: str = "system",
) -> None:
    subject_id = subject_entity_id or account_id
    snapshot_id = await _snapshot(
        conn,
        subject_entity_id=subject_id,
        subject_entity_type=subject_entity_type,
        parent_account_id=account_id,
        project_id=project_id,
        project_run_id=project_run_id,
        created_at=created_at,
    )
    if actor_category == "system":
        await append_research_view_event(
            conn,
            event_key=event_key,
            topic=topic,
            workspace_id=_WS,
            project_id=project_id,
            project_run_id=project_run_id,
            subject_entity_id=subject_id,
            snapshot_id=snapshot_id,
            report_id=None,
            section_ids=("summary",),
            item_ids=(f"{event_key}-item",),
            reason_codes=(),
            fetch_ref=f"research-view-snapshot:{snapshot_id}",
            created_at=created_at,
            subject_activity_appender=append_subject_activity,
        )
        return

    # The source event is durable, but a human subject-activity row cannot be displayed until it
    # carries a resolvable principal id.  Plant that exact omission case.
    await append_research_view_event(
        conn,
        event_key=event_key,
        topic=topic,
        workspace_id=_WS,
        project_id=project_id,
        project_run_id=project_run_id,
        subject_entity_id=subject_id,
        snapshot_id=snapshot_id,
        report_id=None,
        section_ids=("summary",),
        item_ids=(f"{event_key}-item",),
        reason_codes=(),
        fetch_ref=f"research-view-snapshot:{snapshot_id}",
        created_at=created_at,
    )
    source_event_id = (
        await conn.execute(
            text(
                "SELECT event_id FROM research_view_event "
                "WHERE workspace_id=:workspace_id AND event_key=:event_key"
            ),
            {"workspace_id": _WS, "event_key": event_key},
        )
    ).scalar_one()
    account_run_id = (
        await conn.execute(
            text(
                "SELECT id FROM account_run "
                "WHERE project_run_id=:project_run_id AND entity_id=:account_id"
            ),
            {"project_run_id": project_run_id, "account_id": account_id},
        )
    ).scalar_one()
    await append_subject_activity(
        conn,
        workspace_id=_WS,
        project_id=project_id,
        project_run_id=project_run_id,
        account_run_id=account_run_id,
        subject_entity_id=subject_id,
        subject_entity_type=subject_entity_type,
        product_id=None,
        owner_event_ref=f"research-view-event:{source_event_id}",
        event_kind=topic,
        actor_category=actor_category,
        occurred_at=created_at,
    )


def test_activity_is_source_exact_stable_and_cross_tab_consistent() -> None:
    async def scenario() -> None:
        context = rollback_conn()
        conn = await context.__aenter__()
        try:
            account_id, contact_id, project_id, project_run_id, account_run_id = await _seed_scope(
                conn
            )
            older = datetime(2026, 8, 12, 8, 15, tzinfo=UTC)
            contact_time = older + timedelta(minutes=30)
            newer = older + timedelta(hours=1)
            await _event(
                conn,
                event_key="view-updated",
                topic="research_view.updated",
                account_id=account_id,
                project_id=project_id,
                project_run_id=project_run_id,
                created_at=older,
            )
            await _event(
                conn,
                event_key="contact-view-updated",
                topic="research_view.updated",
                account_id=account_id,
                project_id=project_id,
                project_run_id=project_run_id,
                created_at=contact_time,
                subject_entity_id=contact_id,
                subject_entity_type=EntityType.CONTACT,
            )
            await _event(
                conn,
                event_key="view-stale",
                topic="research_view.section_stale",
                account_id=account_id,
                project_id=project_id,
                project_run_id=project_run_id,
                created_at=newer,
            )
            await _event(
                conn,
                event_key="human-without-principal",
                topic="research_view.updated",
                account_id=account_id,
                project_id=project_id,
                project_run_id=project_run_id,
                created_at=newer + timedelta(minutes=1),
                actor_category="human",
            )
            ungoverned_contact_id = await insert_contact_entity(
                conn,
                account_entity_id=account_id,
                full_name="Not in committee",
                linkedin_url=None,
                status=AccountStatus.ACTIVE,
            )
            await _event(
                conn,
                event_key="ungoverned-contact-view-updated",
                topic="research_view.updated",
                account_id=account_id,
                project_id=project_id,
                project_run_id=project_run_id,
                created_at=newer + timedelta(minutes=2),
                subject_entity_id=ungoverned_contact_id,
                subject_entity_type=EntityType.CONTACT,
            )
            await append_subject_activity(
                conn,
                workspace_id=_WS,
                project_id=project_id,
                project_run_id=project_run_id,
                account_run_id=account_run_id,
                subject_entity_id=account_id,
                subject_entity_type=EntityType.ACCOUNT,
                product_id=None,
                owner_event_ref="missing-source-event",
                event_kind="research_view.updated",
                actor_category="system",
                occurred_at=newer + timedelta(minutes=3),
            )

            first = await _get(conn, uuid.UUID(str(account_id)))
            second = await _get(conn, uuid.UUID(str(account_id)))
            detail = await _get_detail(conn, uuid.UUID(str(account_id)))
            assert first.status_code == second.status_code == detail.status_code == 200
            assert first.json() == second.json()

            payload = first.json()
            detail_payload = detail.json()
            assert payload["state"] == {
                "committeeCount": len(detail_payload["committee"]),
                "summary": detail_payload["summary"],
            }
            assert payload["state"]["committeeCount"] == 1
            assert payload["state"]["summary"]["state"] == "not_composed"
            assert [event["kind"] for event in payload["events"]] == [
                "research_view.section_stale",
                "research_view.updated",
                "research_view.updated",
            ]
            assert [event["occurredAt"] for event in payload["events"]] == [
                _wire_time(newer),
                _wire_time(contact_time),
                _wire_time(older),
            ]
            assert payload["events"][0]["subject"] == {
                "type": "account",
                "id": str(account_id),
                "name": "Durable Activity Account",
            }
            assert payload["events"][0]["reference"]["target"] == "account_insights"
            assert payload["events"][1]["subject"] == {
                "type": "contact",
                "id": str(contact_id),
                "name": "Dana Durable",
            }
            assert payload["events"][1]["reference"]["target"] == "contact_profile"

            source_rows = (
                (
                    await conn.execute(
                        text(
                            """
                        SELECT activity.activity_id, activity.occurred_at,
                               source_event.event_id, source_event.snapshot_id
                        FROM research_subject_activity activity
                        JOIN research_view_event source_event
                          ON activity.owner_event_ref =
                             'research-view-event:' || source_event.event_id::text
                        WHERE activity.workspace_id=:workspace_id
                          AND activity.subject_entity_id IN (:account_id, :contact_id)
                          AND activity.actor_category='system'
                        ORDER BY activity.occurred_at DESC, activity.activity_id DESC
                        """
                        ),
                        {
                            "workspace_id": _WS,
                            "account_id": account_id,
                            "contact_id": contact_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            assert len(source_rows) == len(payload["events"]) == 3
            for event, source in zip(payload["events"], source_rows, strict=True):
                assert event["id"] == str(source["activity_id"])
                assert event["occurredAt"] == _wire_time(source["occurred_at"])
                assert event["reference"]["eventId"] == str(source["event_id"])
                assert event["reference"]["snapshotId"] == str(source["snapshot_id"])
                assert event["project"] == {
                    "id": project_id,
                    "name": "Insight Health campaign",
                }
                assert event["projectRunId"] == str(project_run_id)
                assert event["accountRunId"] == str(account_run_id)

            foreign = await _get(
                conn,
                uuid.UUID(str(account_id)),
                workspace_id=_OTHER_WS,
            )
            assert foreign.status_code == 404
            assert foreign.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"
        finally:
            await context.__aexit__(None, None, None)

    from tests.db.conftest import run_async

    run_async(scenario())


def test_activity_empty_state_is_an_honest_empty_event_set() -> None:
    async def scenario() -> None:
        context = rollback_conn()
        conn = await context.__aenter__()
        try:
            await seed_workspace(conn, _WS)
            account_id = await insert_account_entity(
                conn,
                canonical_name="No Activity Account",
                primary_domain=None,
                status=AccountStatus.ACTIVE,
                workspace_id=_WS,
            )
            response = await _get(conn, uuid.UUID(str(account_id)))
            assert response.status_code == 200
            assert response.json()["events"] == []
            assert response.json()["state"]["summary"]["state"] == "not_composed"
        finally:
            await context.__aexit__(None, None, None)

    from tests.db.conftest import run_async

    run_async(scenario())
