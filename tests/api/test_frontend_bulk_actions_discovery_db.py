"""ARV2 R4 — the accounts table is the approval surface (spec §5, rulings 2 and 1′).

Ticking a discovered account and using the existing "Add to project" bulk action *is* the human's
approval, so the action stamps the candidate rows behind the accounts it actually added. A row it
did not add keeps whatever decision it already had, and a row nobody ticked stays unapproved —
which is not a rejection.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.discovery_store import (
    CandidateRow,
    DiscoveryRunRow,
    create_discovery_run,
    list_candidates,
    upsert_candidate,
)
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_core import AccountStatus, ProjectPhase, ProjectRunId
from clue_research.durable.project_run import ensure_project_run
from clue_research.identity import insert_account_entity
from clue_spine import Project
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_WS = "r4-bulk-approval"
_BASE = f"{FRONTEND_READ_PREFIX}/accounts"
#: What ``_requester`` resolves to in the local-header auth mode these tests run under.
_LOCAL_ACTOR = "local-development-user"
#: An approval an earlier human already made, far enough back that the transaction's ``now()``
#: could never coincide with it.
_EARLIER = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _app(conn: AsyncConnection):
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(_env_file=None, frontend_read_enabled=True),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
    )


async def _account(conn: AsyncConnection, *, name: str) -> uuid.UUID:
    return uuid.UUID(
        str(
            await insert_account_entity(
                conn,
                canonical_name=name,
                primary_domain=f"{name.lower()}.test",
                status=AccountStatus.ACTIVE,
                workspace_id=_WS,
            )
        )
    )


async def _discovery_run(conn: AsyncConnection, project: Project) -> DiscoveryRunRow:
    """A discovery run hanging off a real ``project_run``, the way the launch route makes one."""
    project_run_id = uuid.uuid4()
    await ensure_project_run(
        conn,
        project_run_id=ProjectRunId(project_run_id),
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="clue-abm-buyers",
        icp_version=1,
        phase=ProjectPhase.DEEP,
    )
    row = DiscoveryRunRow(
        run_id=uuid.uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        brand_id=str(project.brand_id),
        project_run_id=project_run_id,
        icp_artifact_key=f"{_WS}/icp",
        icp_artifact_sha256="b" * 64,
        icp_key="clue-abm-buyers",
        icp_version=1,
        requested_by_user_id="user-1",
        request_sha256="a" * 64,
        target_count=20,
        relaxed_enabled=True,
        criteria_gate_keys=("geography", "stage"),
    )
    await create_discovery_run(conn, row)
    return row


async def _candidate(
    conn: AsyncConnection,
    run: DiscoveryRunRow,
    *,
    name: str,
    account_entity_id: uuid.UUID,
    decision: str | None = None,
    decided_by_user_id: str | None = None,
    decided_at: datetime | None = None,
) -> None:
    await upsert_candidate(
        conn,
        CandidateRow(
            candidate_id=uuid.uuid4(),
            run_id=run.run_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            pass_="strict",
            domain=f"{name.lower()}.test",
            websets_url=f"https://websets.test/{name.lower()}",
            name=name,
            provider_snapshot={"name": name},
            fit=1.0,
            disposition="pass",
            decision=decision,
            decided_by_user_id=decided_by_user_id,
            decided_at=decided_at,
            account_entity_id=account_entity_id,
        ),
    )


def test_add_to_project_marks_the_discovered_candidate_approved() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, _WS, name="Discovery ABM")
            fresh = await _account(conn, name="Fresh")
            already = await _account(conn, name="Already")
            run = await _discovery_run(conn, project)
            await _candidate(conn, run, name="Fresh", account_entity_id=fresh)
            # An account an earlier human already approved, still absent from the project — so the
            # action does add it, and its existing decision is the one the guard must protect.
            await _candidate(
                conn,
                run,
                name="Already",
                account_entity_id=already,
                decision="approved",
                decided_by_user_id="earlier-approver",
                decided_at=_EARLIER,
            )

            body = {
                "accountIds": [str(fresh), str(already)],
                "projectId": project.project_id,
            }
            async with httpx.AsyncClient(
                transport=ASGITransport(app=_app(conn)), base_url="http://t"
            ) as client:
                first = await client.post(
                    f"{_BASE}/bulk-actions/add-to-project",
                    headers={"X-Workspace-Id": _WS, "Idempotency-Key": "discovery-approve-1"},
                    json=body,
                )
                assert first.status_code == 200
                assert {item["subjectId"]: item["outcome"] for item in first.json()["items"]} == {
                    str(fresh): "completed",
                    str(already): "completed",
                }

                members = {
                    uuid.UUID(str(row[0]))
                    for row in (
                        await conn.execute(
                            text(
                                "SELECT account_entity_id FROM project_account "
                                "WHERE workspace_id=:workspace_id AND project_id=:project_id"
                            ),
                            {"workspace_id": _WS, "project_id": project.project_id},
                        )
                    ).all()
                }
                assert members == {fresh, already}

                decided = {row.name: row for row in await list_candidates(conn, run_id=run.run_id)}
                assert decided["Fresh"].decision == "approved"
                assert decided["Fresh"].decided_by_user_id == _LOCAL_ACTOR
                assert decided["Fresh"].decided_at is not None
                # ``decision IS NULL`` guards the write, so the earlier human keeps the credit.
                assert decided["Already"].decided_by_user_id == "earlier-approver"
                assert decided["Already"].decided_at == _EARLIER

                # A second bulk action over the same selection decides nobody again.
                second = await client.post(
                    f"{_BASE}/bulk-actions/add-to-project",
                    headers={"X-Workspace-Id": _WS, "Idempotency-Key": "discovery-approve-2"},
                    json=body,
                )
                assert second.status_code == 200
                assert {item["outcome"] for item in second.json()["items"]} == {"unchanged"}

            after = {row.name: row for row in await list_candidates(conn, run_id=run.run_id)}
            assert after["Fresh"].decided_at == decided["Fresh"].decided_at
            assert after["Fresh"].decided_by_user_id == _LOCAL_ACTOR
            assert after["Already"].decided_at == _EARLIER
            assert after["Already"].decided_by_user_id == "earlier-approver"

    run_async(scenario())
