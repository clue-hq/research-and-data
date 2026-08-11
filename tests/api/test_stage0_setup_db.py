"""FI-4 slice 2: the /stage0/setup composition (capture → onboarding_input → recon driver)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.stage0_setup import create_stage0_setup_router
from clue_auth import provision_self_serve_workspace
from clue_core import OnboardingInputId, ReconRunId
from clue_research.stage0 import (
    ReconLaneStatus,
    recon_dedupe_hash,
    start_recon,
    transition_recon_lane,
)
from clue_toolbelt import ToolContext, ToolResult
from tests.auth.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

PROFILE = {
    "first_name": "Aakash",
    "last_name": "Shrivastava",
    "job_role": "Founder",
    "company_name": "Insight Health",
    "company_website": "https://insight.health",
}


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


class _LaneDrivingInvoker:
    """A stub start_recon: each invocation drives exactly one queued lane to completed,
    writing the same durable rows the real tool writes (the setup surface reads only rows).
    Acquires the shared test connection through the serialized factory — in production each
    conn_factory() call is its own pooled connection."""

    def __init__(self, conn_factory: Any) -> None:
        self._conn_factory = conn_factory
        self.invocations: list[dict[str, Any]] = []

    async def invoke(
        self,
        name: str,
        body: dict[str, Any],
        context: ToolContext,
        *,
        version: str | None = None,
        idempotency_key: str | None = None,
    ) -> ToolResult:
        del version, idempotency_key
        assert name == "start_recon"
        self.invocations.append(dict(body))
        dedupe = recon_dedupe_hash(
            workspace_id=context.workspace_id,
            brand_id=body["brand_id"],
            product_id=None,
            identity=body["website"],
        )
        async with self._conn_factory() as conn:
            recon = await start_recon(
                conn,
                workspace_id=context.workspace_id,
                brand_id=body["brand_id"],
                dedupe_hash=dedupe,
                onboarding_input_ids=tuple(
                    OnboardingInputId(UUID(item)) for item in body["onboarding_input_ids"]
                ),
                fast_budget_cents=5,
                background_budget_cents=100,
                dedupe_ttl_seconds=86_400,
                recon_run_id=ReconRunId(context.operation_id),
            )
            if recon.fast_status is not ReconLaneStatus.COMPLETED:
                lane = "fast"
            elif recon.background_status is not ReconLaneStatus.COMPLETED:
                lane = "background"
            else:
                lane = None
            if lane is not None:
                await transition_recon_lane(
                    conn,
                    recon_run_id=recon.id,
                    workspace_id=context.workspace_id,
                    lane=lane,
                    status=ReconLaneStatus.COMPLETED,
                    cost_cents=3,
                    client_kb_version=1,
                )
        refreshed_fast = "completed" if lane in ("fast", None) else recon.fast_status.value
        refreshed_background = "completed" if lane in ("background", None) else "queued"
        return ToolResult(
            tool="start_recon",
            version="1",
            references={
                "recon_run_id": str(recon.id),
                "fast_status": refreshed_fast,
                "background_status": refreshed_background,
            },
        )


def test_setup_route_captures_drives_lanes_and_serves_lane_truth() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_lock = asyncio.Lock()

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                # One shared rollback connection; serialized because the driver task and the
                # HTTP polls run concurrently (production uses one pooled conn per call).
                async with conn_lock:
                    yield conn

            provisioned = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="setup-subject-1",
                **PROFILE,
            )
            workspace_id = provisioned.workspace.workspace_id
            invoker = _LaneDrivingInvoker(conn_factory)
            app = FastAPI()
            app.include_router(
                create_stage0_setup_router(
                    tool_invoker=invoker,  # type: ignore[arg-type]
                    conn_factory=conn_factory,
                    storage=_MemoryStorage(),  # type: ignore[arg-type]
                )
            )
            headers = {"X-Workspace-Id": workspace_id}
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                before = await client.get("/stage0/setup/current", headers=headers)
                assert before.status_code == 200
                assert before.json()["status"] == "none"

                started = await client.post("/stage0/setup", headers=headers)
                assert started.status_code == 202

                # The driver runs as a background task on this loop; let it settle.
                for _ in range(500):
                    await asyncio.sleep(0.01)
                    if len(invoker.invocations) >= 2:
                        break

                current = await client.get("/stage0/setup/current", headers=headers)
                assert current.status_code == 200
                payload = current.json()
                assert payload["status"] == "complete"
                assert payload["fast_status"] == "completed"
                assert payload["background_status"] == "completed"
                assert payload["recon_run_id"] is not None

            # Capture-before-use is durable: the website submission is an onboarding_input
            # whose artifact FK proves the bytes existed first.
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT kind, actor, source_ref FROM onboarding_input "
                            "WHERE workspace_id = :ws"
                        ),
                        {"ws": workspace_id},
                    )
                )
                .mappings()
                .one()
            )
            assert row["kind"] == "website"
            assert row["actor"] == "human"
            assert row["source_ref"] == "https://insight.health"
            # The kicker drove both lanes: fast first, then background (two invocations).
            assert len(invoker.invocations) == 2

    run_async(scenario())


def test_setup_routes_refuse_workspaces_without_provisioning() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_lock = asyncio.Lock()

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                async with conn_lock:
                    yield conn

            from clue_spine import create_workspace

            workspace = await create_workspace(conn, name="No Provisioning Co")
            app = FastAPI()
            app.include_router(
                create_stage0_setup_router(
                    tool_invoker=_LaneDrivingInvoker(conn_factory),  # type: ignore[arg-type]
                    conn_factory=conn_factory,
                    storage=_MemoryStorage(),  # type: ignore[arg-type]
                )
            )
            headers = {"X-Workspace-Id": workspace.workspace_id}
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                current = await client.get("/stage0/setup/current", headers=headers)
                assert current.status_code == 200
                assert current.json()["status"] == "unavailable"

                refused = await client.post("/stage0/setup", headers=headers)
                assert refused.status_code == 409

    run_async(scenario())
