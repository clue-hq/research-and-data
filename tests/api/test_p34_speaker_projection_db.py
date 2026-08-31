"""P3.4 acceptance — the speaker-state projection (PD-part3 §4 "speaker-state projection").

Who owns the thread right now? While a design leg is open, Design does — and both read
surfaces must say so without the frontend inferring it: the thread listing carries the
speaker (role + leg state) and the turn-accept response says which agent the message was
routed to (accept-time visibility at the router). Part IV renders the chip; this is the
data it reads.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_api.design_leg_wiring import design_legs_for_threads
from clue_api.execution_wiring import build_tool_invoker
from clue_api.projections_app import create_projections_app
from clue_api.thread_wiring import register_thread_tools
from clue_config import Settings, load_settings
from clue_design import legs as design_legs
from clue_toolbelt import DbIdempotencyStore, ToolRegistry
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)
from tests.projections._helpers import build_surface

USER_ID = "usr_p34_speaker"
_AUTHENTICATED_AT = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)


class _MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        del media_type
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        del expires_in
        return f"memory://{key}"

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return
        yield


def _settings(**kwargs: object) -> Settings:
    return load_settings(_env_file=None, chat_enabled=True, **kwargs)


def _app(conn: Any, *, settings: Settings, storage: Any) -> Any:
    cf = conn_session_factory(conn)
    registry = ToolRegistry()
    register_thread_tools(registry, conn_factory=cf)

    def _principal(workspace_id: str) -> RequestPrincipal:
        return RequestPrincipal(
            user_id=USER_ID,
            membership_id=f"wsm_p34s_{workspace_id}",
            workspace_id=workspace_id,
            role_key="owner",
            permissions=CHAT_PERMISSIONS,
            authenticated_at=_AUTHENTICATED_AT,
        )

    return create_projections_app(
        surface=build_surface(conn),
        tool_invoker=build_tool_invoker(
            registry=registry,
            idempotency_store=DbIdempotencyStore(conn_factory=cf),
            storage=_MemoryStorage(),
            settings=settings,
            conn_factory=cf,
        ),
        settings=settings,
        conn_factory=cf,
        manage_db_lifespan=False,
        ingestion_storage=storage,
        chat_principal_resolver=_principal,
    )


async def _seed_thread(conn: Any, *, workspace_id: str, project_id: str, label: str) -> str:
    thread_id = f"thr_p34s_{label}"
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id, created_by_user_id) "
            "VALUES (:id, :workspace, :project, :user)"
        ),
        {"id": thread_id, "workspace": workspace_id, "project": project_id, "user": USER_ID},
    )
    return thread_id


async def _seed_open_leg(conn: Any, *, workspace_id: str, project_id: str, thread_id: str) -> Any:
    execution_id = uuid5(NAMESPACE_URL, f"p34s:{thread_id}:execution")
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
            " pin_manifest_hash) "
            "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
        ),
        {
            "id": execution_id,
            "workspace": workspace_id,
            "project": project_id,
            "hash": "0" * 64,
        },
    )
    return await design_legs.open_leg(
        conn,
        workspace_id=workspace_id,
        thread_id=thread_id,
        parent_execution_id=execution_id,
    )


def test_design_legs_for_threads_answers_the_speaker_in_one_read(
    migrated_db: bool,  # noqa: F811
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = f"ws_p34s_read_{uuid4().hex[:8]}"
            project = await seed_project(conn, workspace_id, name="P3.4 speaker read")
            await seed_principal(
                conn,
                workspace_id=workspace_id,
                user_id=USER_ID,
                membership_id=f"wsm_p34s_{workspace_id}",
            )
            with_leg = await _seed_thread(
                conn, workspace_id=workspace_id, project_id=project.project_id, label="leg"
            )
            without_leg = await _seed_thread(
                conn, workspace_id=workspace_id, project_id=project.project_id, label="free"
            )
            leg = await _seed_open_leg(
                conn,
                workspace_id=workspace_id,
                project_id=project.project_id,
                thread_id=with_leg,
            )
            cf = conn_session_factory(conn)
            legs_map = await design_legs_for_threads(
                cf,
                workspace_id=workspace_id,
                thread_ids=(with_leg, without_leg),
            )
            assert set(legs_map) == {with_leg}
            assert legs_map[with_leg]["id"] == leg["id"]
            assert legs_map[with_leg]["state"] == "open_awaiting_user"
            assert await design_legs_for_threads(cf, workspace_id=workspace_id, thread_ids=()) == {}

    run_async(scenario())


def test_thread_listing_and_turn_accept_carry_the_speaker(
    migrated_db: bool,  # noqa: F811
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = f"ws_p34s_http_{uuid4().hex[:8]}"
            project = await seed_project(conn, workspace_id, name="P3.4 speaker http")
            await seed_principal(
                conn,
                workspace_id=workspace_id,
                user_id=USER_ID,
                membership_id=f"wsm_p34s_{workspace_id}",
            )
            with_leg = await _seed_thread(
                conn, workspace_id=workspace_id, project_id=project.project_id, label="design"
            )
            without_leg = await _seed_thread(
                conn, workspace_id=workspace_id, project_id=project.project_id, label="abm"
            )
            leg = await _seed_open_leg(
                conn,
                workspace_id=workspace_id,
                project_id=project.project_id,
                thread_id=with_leg,
            )
            storage = _MemoryStorage()
            app = _app(conn, settings=_settings(), storage=storage)
            client = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
            headers = {"X-Workspace-Id": workspace_id}

            listing = await client.get(
                f"/api/v1/projects/{project.project_id}/threads", headers=headers
            )
            assert listing.status_code == 200
            by_id = {item["id"]: item for item in listing.json()["data"]}
            assert by_id[with_leg]["speaker"] == {
                "role": "design",
                "design_leg_id": leg["id"],
                "design_leg_state": "open_awaiting_user",
            }
            assert by_id[without_leg]["speaker"] == {
                "role": "head_of_abm",
                "design_leg_id": None,
                "design_leg_state": None,
            }

            # Accept-time visibility: the 202 says which agent will receive the message.
            to_design = await client.post(
                f"/api/v1/projects/{project.project_id}/threads/{with_leg}/turns",
                json={"message": "Bigger logo."},
                headers={**headers, "Idempotency-Key": "p34s-design"},
            )
            assert to_design.status_code == 202
            assert to_design.json()["data"]["routed_to"] == "design"

            to_abm = await client.post(
                f"/api/v1/projects/{project.project_id}/threads/{without_leg}/turns",
                json={"message": "What accounts should we target?"},
                headers={**headers, "Idempotency-Key": "p34s-abm"},
            )
            assert to_abm.status_code == 202
            assert to_abm.json()["data"]["routed_to"] == "head_of_abm"

            # The replay answer carries the same visibility.
            replay = await client.post(
                f"/api/v1/projects/{project.project_id}/threads/{with_leg}/turns",
                json={"message": "Bigger logo."},
                headers={**headers, "Idempotency-Key": "p34s-design"},
            )
            assert replay.status_code == 202
            assert replay.json()["data"]["replayed"] is True
            assert replay.json()["data"]["routed_to"] == "design"

    run_async(scenario())
