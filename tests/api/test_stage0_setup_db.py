"""FI-4 slice 2: the /stage0/setup composition (capture → onboarding_input → recon driver)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.client_context_binding import get_workspace_client_binding
from clue_api.execution_wiring import build_tool_invoker
from clue_api.stage0_setup import create_stage0_setup_router, setup_workspace_resolver
from clue_api.stage0_setup_fleet import Stage0ReconWorkHandler, iteration_operation_id
from clue_api.tool_outputs import ReconOutput
from clue_auth import RequestPrincipal, permissions_for_role, provision_self_serve_workspace
from clue_auth.errors import PermissionDenied
from clue_config import Settings
from clue_core import (
    RECON_FIELD_PROGRESS_KIND,
    RECON_TRANSITION_KIND,
    AccountStatus,
    OnboardingInputId,
    ProjectRunId,
    ReconRunId,
    RunEventTopic,
)
from clue_execution.run_events import emit_run_event
from clue_fleet import LeaseGeneration, WorkContext, WorkId
from clue_research.identity import insert_account_entity
from clue_research.stage0 import (
    CLIENT_PRODUCT_CATALOG,
    ReconLaneStatus,
    recon_dedupe_hash,
    start_recon,
    transition_recon_lane,
)
from clue_toolbelt import (
    DbIdempotencyStore,
    Tool,
    ToolContext,
    ToolInput,
    ToolRegistry,
    ToolResult,
)
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


async def _emit_lane_progress(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    recon_run_id: UUID,
    lane: str,
) -> None:
    """The per-field + terminal events the REAL start_recon tool writes for one lane.

    The setup surface reads only durable rows, so a lane stand-in that skips these leaves the
    progress read with nothing to serve. Two fields with a status correction each (started →
    terminal) also exercise the reader's last-writer-wins reduction."""
    for field_key, terminal in (("client.value_prop", "resolved"), ("client.product", "empty")):
        for status in ("started", terminal):
            await emit_run_event(
                conn,
                workspace_id=workspace_id,
                run_id=ProjectRunId(recon_run_id),
                topic=RunEventTopic.STEP_PROGRESS.value,
                payload={
                    "kind": RECON_FIELD_PROGRESS_KIND,
                    "recon_run_id": str(recon_run_id),
                    "lane": lane,
                    "field_key": field_key,
                    "status": status,
                },
            )
    await emit_run_event(
        conn,
        workspace_id=workspace_id,
        run_id=ProjectRunId(recon_run_id),
        topic=RunEventTopic.STEP_PROGRESS.value,
        payload={
            "kind": RECON_TRANSITION_KIND,
            "recon_run_id": str(recon_run_id),
            "lane": lane,
            "status": "completed",
            "budget_exhausted": False,
        },
    )


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
                await _emit_lane_progress(
                    conn,
                    workspace_id=context.workspace_id,
                    recon_run_id=recon.id,
                    lane=lane,
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


class _BlockingReconEnqueuer:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls: list[dict[str, object]] = []

    async def enqueue(self, **kwargs: object) -> bool:
        self.calls.append(kwargs)
        self.entered.set()
        await self.release.wait()
        return True


class _ForbiddenWebInvoker:
    async def invoke(self, *_args: object, **_kwargs: object) -> ToolResult:
        raise AssertionError("production C6 setup must never invoke recon on the API event loop")


class _CaptureEnqueuer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def enqueue(self, **kwargs: object) -> bool:
        self.calls.append(kwargs)
        return True


def test_authoritative_fleet_bootstrap_never_invokes_legacy_resolver() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            provisioned = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject=f"c10-cutover-{uuid4()}",
                **PROFILE,
            )
            workspace_id = provisioned.workspace.workspace_id
            recon_queue = _CaptureEnqueuer()
            app = FastAPI()
            app.include_router(
                create_stage0_setup_router(
                    tool_invoker=_ForbiddenWebInvoker(),  # type: ignore[arg-type]
                    conn_factory=conn_factory,
                    storage=_MemoryStorage(),  # type: ignore[arg-type]
                    recon_enqueuer=recon_queue,  # type: ignore[arg-type]
                )
            )
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                started = await client.post(
                    "/stage0/setup", headers={"X-Workspace-Id": workspace_id}
                )
            assert started.status_code == 202
            queued = recon_queue.calls[-1]
            digest = str(queued["website_digest"])
            onboarding_input_id = str(queued["onboarding_input_id"])
            attempt = int(queued["attempt"])
            work_id = UUID(str(iteration_operation_id(workspace_id, digest, attempt, 0)))
            crawl_queue = _CaptureEnqueuer()
            handler = Stage0ReconWorkHandler(
                tool_invoker=_ForbiddenWebInvoker(),  # type: ignore[arg-type]
                conn_factory=conn_factory,
                crawl_enqueuer=crawl_queue,  # type: ignore[arg-type]
                settings=Settings(  # type: ignore[call-arg]
                    _env_file=None,
                    stage0_official_site_crawl_mode="authoritative",
                    stage0_page_fetcher="scrapling",
                    stage0_official_site_crawl_workspace_allowlist=(workspace_id,),
                ),
            )
            untrusted_target = await insert_account_entity(
                conn,
                canonical_name="Untrusted Target Account",
                primary_domain="target-account.example",
                workspace_id=workspace_id,
                status=AccountStatus.ACTIVE,
            )
            context = WorkContext(
                task_id=uuid4(),
                work_id=WorkId(work_id),
                worker_id="c10-test",
                lease_generation=LeaseGeneration(1),
                payload={
                    "workspace_id": workspace_id,
                    "onboarding_input_id": onboarding_input_id,
                    "website_digest": digest,
                    "attempt": attempt,
                    # User/model task data cannot select the customer account. The handler must
                    # derive it from the trusted onboarding scope and recon transaction.
                    "client_entity_id": str(untrusted_target),
                },
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )

            first = await handler.handle(context)
            replay = await handler.handle(context)
            assert first.outcome == replay.outcome == "authoritative_crawl_enqueued"
            assert first.references["fast_status"] == "running"
            assert first.references["background_status"] == "queued"
            assert [str(call["recon_run_id"]) for call in crawl_queue.calls] == [
                str(work_id),
                str(work_id),
            ]

            recon = (
                (
                    await conn.execute(
                        text(
                            "SELECT client_entity_id, fast_run_id, background_run_id, "
                            "fast_status, background_status, fast_client_kb_version "
                            "FROM recon_run WHERE id = :id"
                        ),
                        {"id": work_id},
                    )
                )
                .mappings()
                .one()
            )
            assert recon["client_entity_id"] is not None
            canonical_binding = await get_workspace_client_binding(
                conn,
                workspace_id=workspace_id,
            )
            assert canonical_binding is not None
            assert canonical_binding.client_entity_id == recon["client_entity_id"]
            assert canonical_binding.source_recon_run_id == ReconRunId(work_id)
            assert canonical_binding.client_entity_id != untrusted_target
            assert recon["fast_status"] == "running"
            assert recon["background_status"] == "queued"
            assert recon["fast_client_kb_version"] is None
            lineage = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM run_lineage WHERE workspace_id = :workspace_id "
                        "AND run_id IN (:fast_run_id, :background_run_id) AND kind = 'stage0'"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "fast_run_id": recon["fast_run_id"],
                        "background_run_id": recon["background_run_id"],
                    },
                )
            ).scalar_one()
            markers = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM claim WHERE workspace_id = :workspace_id "
                        "AND field_key = 'client.kb_version'"
                    ),
                    {"workspace_id": workspace_id},
                )
            ).scalar_one()
            assert lineage == 2
            assert markers == 0

    run_async(scenario())


def test_legacy_fleet_binds_recon_client_for_every_project() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            provisioned = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject=f"legacy-fleet-binding-{uuid4()}",
                **PROFILE,
            )
            workspace_id = provisioned.workspace.workspace_id
            recon_queue = _CaptureEnqueuer()
            app = FastAPI()
            app.include_router(
                create_stage0_setup_router(
                    tool_invoker=_ForbiddenWebInvoker(),  # type: ignore[arg-type]
                    conn_factory=conn_factory,
                    storage=_MemoryStorage(),  # type: ignore[arg-type]
                    recon_enqueuer=recon_queue,  # type: ignore[arg-type]
                )
            )
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                started = await client.post(
                    "/stage0/setup", headers={"X-Workspace-Id": workspace_id}
                )
            assert started.status_code == 202

            queued = recon_queue.calls[-1]
            digest = str(queued["website_digest"])
            attempt = int(queued["attempt"])
            work_id = UUID(str(iteration_operation_id(workspace_id, digest, attempt, 0)))
            fake = _FakeStartReconTool(conn_factory)
            registry = ToolRegistry()
            registry.register(fake, make_default=True)
            from clue_config import load_settings

            invoker = build_tool_invoker(
                registry=registry,
                idempotency_store=DbIdempotencyStore(conn_factory=conn_factory),
                storage=_MemoryStorage(),
                settings=load_settings(_env_file=None),
                conn_factory=conn_factory,
            )
            handler = Stage0ReconWorkHandler(
                tool_invoker=invoker,
                conn_factory=conn_factory,
            )
            context = WorkContext(
                task_id=uuid4(),
                work_id=WorkId(work_id),
                worker_id="s2-legacy-fleet",
                lease_generation=LeaseGeneration(1),
                payload={
                    "workspace_id": workspace_id,
                    "onboarding_input_id": str(queued["onboarding_input_id"]),
                    "website_digest": digest,
                    "attempt": attempt,
                },
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )

            fast = await handler.handle(context)
            background = await handler.handle(context)
            assert fast.outcome == "lane_committed"
            assert fast.requeue is True
            assert background.outcome == "completed"
            assert background.requeue is False
            assert len(fake.executions) == 2

            binding = await get_workspace_client_binding(conn, workspace_id=workspace_id)
            assert binding is not None
            assert binding.source_recon_run_id == ReconRunId(work_id)
            recon_client = (
                await conn.execute(
                    text(
                        "SELECT client_entity_id FROM recon_run "
                        "WHERE id = :id AND workspace_id = :workspace_id"
                    ),
                    {"id": work_id, "workspace_id": workspace_id},
                )
            ).scalar_one()
            assert binding.client_entity_id == recon_client

    run_async(scenario())


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
                # Per-field truth: what the recon lanes actually reached, one row per field
                # (last writer by seq wins — a field's `started` is superseded by its
                # terminal status, never listed twice).
                fields = payload["fields"]
                assert isinstance(fields, list)
                assert fields
                assert len({entry["field_key"] for entry in fields}) == len(fields)
                for entry in fields:
                    assert entry["field_key"].startswith("client.")
                    assert entry["lane"] in {"fast", "background"}
                    assert entry["status"] in {"started", "resolved", "empty", "failed"}
                assert {entry["field_key"]: entry["status"] for entry in fields} == {
                    "client.value_prop": "resolved",
                    "client.product": "empty",
                }
                # Budget honesty: both lanes finished inside their caps, and the surface says
                # so rather than leaving the caller to assume it.
                assert payload["fast_budget_exhausted"] is False
                assert payload["background_budget_exhausted"] is False

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
            # DSAR (review BE-M7): the URL is carried by the artifact bytes only; the
            # append-only (un-redactable) capture row holds no copy.
            assert row["source_ref"] is None
            # The kicker drove both lanes: fast first, then background (two invocations).
            assert len(invoker.invocations) == 2

    run_async(scenario())


def test_c6_setup_enqueues_detached_recon_and_polling_remains_responsive() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_lock = asyncio.Lock()

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                async with conn_lock:
                    yield conn

            provisioned = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="setup-c6-detached-subject",
                **PROFILE,
            )
            workspace_id = provisioned.workspace.workspace_id
            enqueuer = _BlockingReconEnqueuer()
            app = FastAPI()
            app.include_router(
                create_stage0_setup_router(
                    tool_invoker=_ForbiddenWebInvoker(),  # type: ignore[arg-type]
                    conn_factory=conn_factory,
                    storage=_MemoryStorage(),  # type: ignore[arg-type]
                    recon_enqueuer=enqueuer,
                )
            )
            headers = {"X-Workspace-Id": workspace_id}
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                posting = asyncio.create_task(client.post("/stage0/setup", headers=headers))
                await asyncio.wait_for(enqueuer.entered.wait(), timeout=1)
                # The enqueue is deliberately suspended. A setup poll still completes because
                # no scrape/model call owns this web process's event loop or DB connection.
                current = await asyncio.wait_for(
                    client.get("/stage0/setup/current", headers=headers), timeout=0.5
                )
                assert current.status_code == 200
                assert current.json()["status"] == "starting"
                enqueuer.release.set()
                started = await posting
                assert started.status_code == 202
            assert len(enqueuer.calls) == 1
            call = enqueuer.calls[0]
            assert call["workspace_id"] == workspace_id
            assert call["website_digest"]
            assert call["attempt"] == 0

    run_async(scenario())


class _MidLaneInvoker:
    """A start_recon stand-in frozen mid-fast-lane: it emits per-field progress on its own
    (autonomous) connection — exactly what the production emitter does — but writes no
    ``recon_run`` row, because production's fast lane holds that insert in the same
    uncommitted transaction until the whole lane ends."""

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
        if len(self.invocations) == 1:
            recon_run_id = UUID(str(context.operation_id))
            async with self._conn_factory() as conn:
                for field_key, status in (
                    ("client.value_prop", "started"),
                    ("client.value_prop", "resolved"),
                    ("client.product", "started"),
                    # Company navigation can progress concurrently, but it is not one of the
                    # founder-ratified eleven onboarding checklist rows.
                    (CLIENT_PRODUCT_CATALOG, "resolved"),
                ):
                    await emit_run_event(
                        conn,
                        workspace_id=context.workspace_id,
                        run_id=ProjectRunId(recon_run_id),
                        topic=RunEventTopic.STEP_PROGRESS.value,
                        payload={
                            "kind": RECON_FIELD_PROGRESS_KIND,
                            "recon_run_id": str(recon_run_id),
                            "lane": "fast",
                            "field_key": field_key,
                            "status": status,
                        },
                    )
        return ToolResult(
            tool="start_recon",
            version="1",
            references={"fast_status": "running", "background_status": "queued"},
        )


def test_starting_setup_serves_the_fields_the_running_fast_lane_has_reached() -> None:
    """The point of the field events: motion while the fast lane runs. Its ``recon_run`` row
    is invisible until the lane's single transaction commits, so ``starting`` must serve the
    per-field truth or the screen shows nothing at all for the whole lane."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_lock = asyncio.Lock()

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                async with conn_lock:
                    yield conn

            provisioned = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="mid-lane-subject",
                **PROFILE,
            )
            workspace_id = provisioned.workspace.workspace_id
            invoker = _MidLaneInvoker(conn_factory)
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
                started = await client.post("/stage0/setup", headers=headers)
                assert started.status_code == 202
                for _ in range(500):
                    await asyncio.sleep(0.01)
                    if invoker.invocations:
                        break

                payload = await _read_status(client, headers)
                assert payload["status"] == "starting"
                assert payload["recon_run_id"] is None
                assert [(entry["field_key"], entry["status"]) for entry in payload["fields"]] == [
                    ("client.value_prop", "resolved"),
                    ("client.product", "started"),
                ]
                # Nothing has completed, so no budget verdict may be invented.
                assert payload["fast_budget_exhausted"] is None
                assert payload["background_budget_exhausted"] is None

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


class _FakeReconInput(ToolInput):
    brand_id: str
    name: str
    website: str
    onboarding_input_ids: list[str]
    product_id: str | None = None
    project_id: str | None = None


class _FakeStartReconTool(Tool):
    """A start_recon stand-in that writes the REAL durable lane rows, registered into the
    REAL invoker (journal + idempotency) — the BE-B1 regression guard: with a shared
    operation id the journal would replay iteration 2 and the background lane would never
    run; per-iteration ids must produce two genuine tool executions."""

    name: ClassVar[str] = "start_recon"
    version: ClassVar[str] = "1"
    input_model: ClassVar[type[ToolInput]] = _FakeReconInput
    output_model = ReconOutput

    def __init__(self, conn_factory: Any, *, fail_first_fast: bool = False) -> None:
        self._conn_factory = conn_factory
        self._fail_first_fast = fail_first_fast
        self._failed_once = False
        self.executions: list[str] = []

    async def invoke(self, inputs: _FakeReconInput, ctx: ToolContext) -> ToolResult:
        self.executions.append(str(ctx.operation_id))
        dedupe = recon_dedupe_hash(
            workspace_id=ctx.workspace_id,
            brand_id=inputs.brand_id,
            product_id=None,
            identity=inputs.website,
        )
        async with self._conn_factory() as conn:
            recon = await start_recon(
                conn,
                workspace_id=ctx.workspace_id,
                brand_id=inputs.brand_id,
                dedupe_hash=dedupe,
                onboarding_input_ids=tuple(
                    OnboardingInputId(UUID(item)) for item in inputs.onboarding_input_ids
                ),
                fast_budget_cents=5,
                background_budget_cents=100,
                dedupe_ttl_seconds=86_400,
                recon_run_id=ReconRunId(ctx.operation_id),
            )
            if (
                self._fail_first_fast
                and not self._failed_once
                and recon.fast_status is ReconLaneStatus.QUEUED
            ):
                self._failed_once = True
                await transition_recon_lane(
                    conn,
                    recon_run_id=recon.id,
                    workspace_id=ctx.workspace_id,
                    lane="fast",
                    status=ReconLaneStatus.FAILED,
                    failure_code="TestBoom",
                )
                return ToolResult(
                    tool=self.name,
                    version=self.version,
                    references={
                        "recon_run_id": str(recon.id),
                        "client_entity_id": None,
                        "fast_client_kb_version": None,
                        "fast_status": "failed",
                        "background_status": "queued",
                        "background_run_id": str(recon.background_run_id),
                    },
                )
            if recon.fast_status not in (
                ReconLaneStatus.COMPLETED,
                ReconLaneStatus.FAILED,
            ):
                lane = "fast"
            elif recon.background_status is not ReconLaneStatus.COMPLETED:
                lane = "background"
            else:
                lane = None
            if lane is not None:
                client_entity_id = recon.client_entity_id
                if client_entity_id is None:
                    client_entity_id = await insert_account_entity(
                        conn,
                        canonical_name=inputs.name,
                        workspace_id=ctx.workspace_id,
                        status=AccountStatus.ACTIVE,
                    )
                await transition_recon_lane(
                    conn,
                    recon_run_id=recon.id,
                    workspace_id=ctx.workspace_id,
                    lane=lane,
                    status=ReconLaneStatus.COMPLETED,
                    cost_cents=3,
                    client_kb_version=1,
                    client_entity_id=client_entity_id,
                )
                await _emit_lane_progress(
                    conn,
                    workspace_id=ctx.workspace_id,
                    recon_run_id=recon.id,
                    lane=lane,
                )
            refreshed = await start_recon(
                conn,
                workspace_id=ctx.workspace_id,
                brand_id=inputs.brand_id,
                dedupe_hash=dedupe,
                onboarding_input_ids=tuple(
                    OnboardingInputId(UUID(item)) for item in inputs.onboarding_input_ids
                ),
                fast_budget_cents=5,
                background_budget_cents=100,
                dedupe_ttl_seconds=86_400,
                recon_run_id=recon.id,
            )
            if lane is not None:
                assert refreshed.client_entity_id == client_entity_id
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "recon_run_id": str(refreshed.id),
                "client_entity_id": (
                    None if refreshed.client_entity_id is None else str(refreshed.client_entity_id)
                ),
                "fast_client_kb_version": refreshed.fast_client_kb_version,
                "fast_status": refreshed.fast_status.value,
                "background_status": refreshed.background_status.value,
                "background_run_id": str(refreshed.background_run_id),
            },
        )


async def _wait_for_executions(fake: _FakeStartReconTool, count: int) -> None:
    """Wait for the driver (same event loop) without touching the DB concurrently — the
    shared rollback connection must not be polled while the real invoker drives."""
    for _ in range(600):
        await asyncio.sleep(0.01)
        if len(fake.executions) >= count:
            await asyncio.sleep(0.05)
            return
    raise AssertionError(f"driver never reached {count} executions: {fake.executions}")


async def _read_status(client: httpx.AsyncClient, headers: dict[str, str]) -> dict:
    current = await client.get("/stage0/setup/current", headers=headers)
    assert current.status_code == 200
    return current.json()


def test_kicker_drives_both_lanes_through_the_real_invoker() -> None:
    """BE-B1 regression guard: the journal must not swallow the second lane invocation."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_lock = asyncio.Lock()

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                async with conn_lock:
                    yield conn

            provisioned = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="real-invoker-subject",
                **PROFILE,
            )
            workspace_id = provisioned.workspace.workspace_id
            fake = _FakeStartReconTool(conn_factory)
            registry = ToolRegistry()
            registry.register(fake, make_default=True)
            from clue_config import load_settings

            invoker = build_tool_invoker(
                registry=registry,
                idempotency_store=DbIdempotencyStore(conn_factory=conn_factory),
                storage=_MemoryStorage(),
                settings=load_settings(_env_file=None),
                conn_factory=conn_factory,
            )
            app = FastAPI()
            app.include_router(
                create_stage0_setup_router(
                    tool_invoker=invoker,
                    conn_factory=conn_factory,
                    storage=_MemoryStorage(),  # type: ignore[arg-type]
                )
            )
            headers = {"X-Workspace-Id": workspace_id}
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                started = await client.post("/stage0/setup", headers=headers)
                assert started.status_code == 202
                await _wait_for_executions(fake, 2)
                payload = await _read_status(client, headers)
                assert payload["status"] == "complete"
                assert payload["background_status"] == "completed"
                assert payload["fast_client_kb_version"] == 1
                assert payload["fact_count"] is not None
            # Two REAL executions — one per lane. A journal replay would have left this
            # at 1 with the background lane queued forever (the pre-fix production bug).
            assert len(fake.executions) == 2
            assert len(set(fake.executions)) == 2

    run_async(scenario())


def test_failed_fast_lane_is_retryable_via_a_fresh_attempt() -> None:
    """BE-B2 regression guard: failure surfaces, releases its dedupe slot, and a re-POST
    mints a genuinely new run instead of replaying the failure."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_lock = asyncio.Lock()

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                async with conn_lock:
                    yield conn

            provisioned = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="retry-subject",
                **PROFILE,
            )
            workspace_id = provisioned.workspace.workspace_id
            fake = _FakeStartReconTool(conn_factory, fail_first_fast=True)
            registry = ToolRegistry()
            registry.register(fake, make_default=True)
            from clue_config import load_settings

            invoker = build_tool_invoker(
                registry=registry,
                idempotency_store=DbIdempotencyStore(conn_factory=conn_factory),
                storage=_MemoryStorage(),
                settings=load_settings(_env_file=None),
                conn_factory=conn_factory,
            )
            app = FastAPI()
            app.include_router(
                create_stage0_setup_router(
                    tool_invoker=invoker,
                    conn_factory=conn_factory,
                    storage=_MemoryStorage(),  # type: ignore[arg-type]
                )
            )
            headers = {"X-Workspace-Id": workspace_id}
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                first = await client.post("/stage0/setup", headers=headers)
                assert first.status_code == 202
                await _wait_for_executions(fake, 1)
                failed = await _read_status(client, headers)
                assert failed["status"] == "failed"
                failed_run_id = failed["recon_run_id"]
                assert failed_run_id is not None

                released = (
                    await conn.execute(
                        text("SELECT dedupe_expires_at <= now() FROM recon_run WHERE id = :id"),
                        {"id": failed_run_id},
                    )
                ).scalar_one()
                assert released is True

                retried = await client.post("/stage0/setup", headers=headers)
                assert retried.status_code == 202
                await _wait_for_executions(fake, 3)
                recovered = await _read_status(client, headers)
                assert recovered["status"] == "complete"
                assert recovered["recon_run_id"] != failed_run_id
                assert recovered["background_status"] == "completed"

    run_async(scenario())


def test_a_viewer_principal_cannot_trigger_setup_spend() -> None:
    """BE-M3 regression guard: recon is SPEND — research.launch is required."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_lock = asyncio.Lock()

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                async with conn_lock:
                    yield conn

            provisioned = await provision_self_serve_workspace(
                conn,
                provider_key="clerk",
                provider_subject="viewer-subject",
                **PROFILE,
            )
            workspace_id = provisioned.workspace.workspace_id
            viewer = RequestPrincipal(
                user_id="usr_viewer",
                membership_id="wsm_viewer",
                workspace_id=workspace_id,
                role_key="viewer",
                permissions=permissions_for_role("viewer"),
                authenticated_at=datetime.now(UTC),
            )

            def viewer_workspace(request: Request) -> str:
                request.state.clue_principal = viewer
                return workspace_id

            app = FastAPI()
            app.include_router(
                create_stage0_setup_router(
                    tool_invoker=_LaneDrivingInvoker(conn_factory),  # type: ignore[arg-type]
                    conn_factory=conn_factory,
                    storage=_MemoryStorage(),  # type: ignore[arg-type]
                )
            )
            app.dependency_overrides[setup_workspace_resolver] = viewer_workspace
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                with pytest.raises(PermissionDenied):
                    await client.post("/stage0/setup")

    run_async(scenario())


def test_setup_routes_mount_only_behind_the_flag() -> None:
    """BE-M4 companion: an unconfigured deployment serves no setup routes (and composes no
    binder — asserted at the composition sites by code inspection; here the app mount)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            from clue_api.projections_app import create_projections_app
            from clue_config import load_settings
            from tests.profiling.conftest import conn_session_factory
            from tests.projections._helpers import build_surface

            cf = conn_session_factory(conn)
            base = load_settings(_env_file=None)

            def app_for(enabled: bool):
                settings = base.model_copy(update={"legacy_stage0_recon_enabled": enabled})
                registry = ToolRegistry()
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
                    sse_live_tail=False,
                    manage_db_lifespan=False,
                    ingestion_storage=_MemoryStorage(),
                )

            on_paths = set(app_for(True).openapi()["paths"])
            off_paths = set(app_for(False).openapi()["paths"])
            assert "/stage0/setup" in on_paths
            assert "/stage0/setup/current" in on_paths
            assert "/stage0/setup" not in off_paths
            assert "/stage0/setup/current" not in off_paths

    run_async(scenario())
