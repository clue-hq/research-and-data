"""Brand-kit slice 2: first-time onboarding auto-enqueues ONE draft brand-kit ingestion.

``POST /stage0/setup`` already holds the provisioned ``brand_id`` + ``company_website``; this
slice hangs one server-side call to the design API's guarded ingest route off the same captured
website. The contract these tests pin:

* **once** — a first-time setup POST makes exactly one enqueue call, to the design API's
  ``POST /brand-kits/ingest/website``, stamped with the PROVISIONED workspace (never a
  request-supplied one) and carrying the captured URL;
* **idempotent** — any existing ``design_ingestion_job`` row for the workspace suppresses it,
  while a FAILED enqueue (which leaves no row) is re-attempted by the next replay;
* **fail-soft** — a design API that refuses, hangs, or is unreachable never fails the setup
  request and never leaves a job row behind;
* **serialized** — two concurrent first-time setups produce ONE job, not two (a per-workspace
  advisory transaction lock spans the check and the enqueue);
* **brand-stamped** — a self-serve-provisioned workspace has exactly one brand, so the kit-birth
  path's exactly-one-brand heuristic stamps that brand with no explicit threading.

No test opens a socket: the design API is a :class:`httpx.MockTransport` behind the trigger's
own client seam.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.brand_kit_ingestion import (
    INGEST_WEBSITE_PATH,
    BrandKitWebsiteIngestion,
    build_brand_kit_ingestion_trigger,
)
from clue_api.stage0_setup import create_stage0_setup_router
from clue_auth import provision_self_serve_workspace
from clue_config import Settings
from clue_db import db_lifespan, transaction
from clue_design import brand as design_brand
from clue_design import ingestion as design_ingestion
from clue_toolbelt import ToolResult
from tests.auth.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

PROFILE = {
    "first_name": "Aakash",
    "last_name": "Shrivastava",
    "job_role": "Founder",
    "company_name": "Insight Health",
    "company_website": "https://insight.health",
}

DESIGN_BASE_URL = "http://design.test:8010"


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


class _ForbiddenWebInvoker:
    async def invoke(self, *_args: object, **_kwargs: object) -> ToolResult:
        raise AssertionError("setup must not invoke recon on the API event loop in these tests")


class _CaptureEnqueuer:
    """Stands in for the production fleet recon enqueuer: records, never spends."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def enqueue(self, **kwargs: object) -> bool:
        self.calls.append(kwargs)
        return True


def _accepted(index: int = 0) -> httpx.Response:
    """The design API's real success envelope for an offered ingestion."""
    return httpx.Response(
        200,
        json={
            "schema_version": 1,
            "job": {
                "job_id": f"ingest_{index}_{uuid4().hex}",
                "kind": "website",
                "status": "queued",
            },
        },
    )


class _DesignApiDouble:
    """A design API that records every ingest request and answers however the test says.

    ``responder`` receives the call index (0-based) and either returns the HTTP response or
    raises the transport error under test.
    """

    def __init__(self, responder: Callable[[int], httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._responder: Callable[[int], httpx.Response] = responder or _accepted

    def _handle(self, request: httpx.Request) -> httpx.Response:
        index = len(self.requests)
        self.requests.append(request)
        return self._responder(index)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))


async def _provision(conn: AsyncConnection, subject: str) -> Any:
    return await provision_self_serve_workspace(
        conn,
        provider_key="clerk",
        provider_subject=f"{subject}-{uuid4()}",
        **PROFILE,
    )


def _setup_app(
    *,
    conn_factory: Any,
    design: _DesignApiDouble,
    recon: _CaptureEnqueuer,
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_stage0_setup_router(
            tool_invoker=_ForbiddenWebInvoker(),  # type: ignore[arg-type]
            conn_factory=conn_factory,
            storage=_MemoryStorage(),  # type: ignore[arg-type]
            recon_enqueuer=recon,  # type: ignore[arg-type]
            brand_kit_ingestion=BrandKitWebsiteIngestion(
                base_url=DESIGN_BASE_URL,
                conn_factory=conn_factory,
                client_factory=design.client,
            ),
        )
    )
    return app


def _shared_conn_factory(conn: AsyncConnection) -> Any:
    """The house test seam: every layer shares the one rolled-back connection."""
    lock = asyncio.Lock()

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        async with lock:
            yield conn

    return factory


async def _jobs(conn: AsyncConnection, workspace_id: str) -> list[dict[str, Any]]:
    return await design_ingestion.list_recent(conn, workspace_id=workspace_id)


# --- 1. the trigger fires exactly once, with the provisioned scope --------------------------


def test_first_time_setup_enqueues_one_website_ingestion() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_factory = _shared_conn_factory(conn)
            provisioned = await _provision(conn, "brandkit-once")
            workspace_id = provisioned.workspace.workspace_id
            design = _DesignApiDouble()
            app = _setup_app(conn_factory=conn_factory, design=design, recon=_CaptureEnqueuer())
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                started = await client.post(
                    "/stage0/setup", headers={"X-Workspace-Id": workspace_id}
                )
            assert started.status_code == 202

            assert len(design.requests) == 1
            request = design.requests[0]
            assert str(request.url) == f"{DESIGN_BASE_URL}{INGEST_WEBSITE_PATH}"
            # The tenant stamp comes from the resolved provisioning scope, and the body carries
            # the captured company website verbatim.
            assert request.headers["X-Workspace-Id"] == workspace_id
            assert json.loads(request.content) == {"url": PROFILE["company_website"]}

    run_async(scenario())


# --- 2. idempotency: an existing job suppresses; a failed enqueue re-attempts ---------------


def test_an_existing_ingestion_job_suppresses_the_trigger() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_factory = _shared_conn_factory(conn)
            provisioned = await _provision(conn, "brandkit-idem")
            workspace_id = provisioned.workspace.workspace_id
            # ANY job for the workspace counts — the auto-trigger exists to give a first-time
            # client a kit, not to add one to a workspace that already has an ingestion.
            await design_ingestion.create_job(
                conn,
                workspace_id=workspace_id,
                kind="website",
                request={"url": PROFILE["company_website"]},
            )
            design = _DesignApiDouble()
            app = _setup_app(conn_factory=conn_factory, design=design, recon=_CaptureEnqueuer())
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                replayed = await client.post(
                    "/stage0/setup", headers={"X-Workspace-Id": workspace_id}
                )
            assert replayed.status_code == 202
            assert design.requests == []
            assert len(await _jobs(conn, workspace_id)) == 1

    run_async(scenario())


def test_a_failed_enqueue_is_re_attempted_by_the_next_replay() -> None:
    """Fail-soft's other half: nothing was written, so the next setup POST tries again."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_factory = _shared_conn_factory(conn)
            provisioned = await _provision(conn, "brandkit-heal")
            workspace_id = provisioned.workspace.workspace_id

            def responder(index: int) -> httpx.Response:
                if index == 0:
                    raise httpx.ConnectError("design API is down")
                return _accepted(index)

            design = _DesignApiDouble(responder)
            app = _setup_app(conn_factory=conn_factory, design=design, recon=_CaptureEnqueuer())
            headers = {"X-Workspace-Id": workspace_id}
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                first = await client.post("/stage0/setup", headers=headers)
                assert first.status_code == 202
                assert len(design.requests) == 1
                assert await _jobs(conn, workspace_id) == []

                second = await client.post("/stage0/setup", headers=headers)
                assert second.status_code == 202
            # The replay re-attempted rather than concluding "already handled".
            assert len(design.requests) == 2

    run_async(scenario())


# --- 3. fail-soft: setup succeeds regardless -------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(httpx.ConnectError("design API is unreachable"), id="unreachable"),
        pytest.param(httpx.ReadTimeout("design API is too slow"), id="timeout"),
    ],
)
def test_an_enqueue_failure_never_blocks_setup(failure: Exception) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_factory = _shared_conn_factory(conn)
            provisioned = await _provision(conn, "brandkit-failsoft")
            workspace_id = provisioned.workspace.workspace_id

            def responder(_index: int) -> httpx.Response:
                raise failure

            design = _DesignApiDouble(responder)
            recon = _CaptureEnqueuer()
            app = _setup_app(conn_factory=conn_factory, design=design, recon=recon)
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                started = await client.post(
                    "/stage0/setup", headers={"X-Workspace-Id": workspace_id}
                )
            assert started.status_code == 202
            assert started.json()["status"] == "started"
            # Onboarding's own work still happened, and no half-written job row survives.
            assert len(recon.calls) == 1
            assert await _jobs(conn, workspace_id) == []

    run_async(scenario())


def test_a_refusing_design_api_is_also_fail_soft() -> None:
    """The SSRF guard's 422 is a refusal, not an outage — same fail-soft handling."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_factory = _shared_conn_factory(conn)
            provisioned = await _provision(conn, "brandkit-refused")
            workspace_id = provisioned.workspace.workspace_id
            design = _DesignApiDouble(
                lambda _index: httpx.Response(
                    422, json={"code": "ingest.url_rejected", "message": "blocked host"}
                )
            )
            app = _setup_app(conn_factory=conn_factory, design=design, recon=_CaptureEnqueuer())
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                started = await client.post(
                    "/stage0/setup", headers={"X-Workspace-Id": workspace_id}
                )
            assert started.status_code == 202
            assert len(design.requests) == 1
            assert await _jobs(conn, workspace_id) == []

    run_async(scenario())


# --- 4. concurrency: the check+enqueue window is serialized ----------------------------------


def test_two_concurrent_triggers_enqueue_only_one_ingestion() -> None:
    """Real connections, real advisory lock: the loser declines instead of double-enqueueing.

    The trigger writes no rows itself (the design API owns the job row, and here it is a mock),
    so this runs against real connections without leaving anything behind.
    """

    async def scenario() -> None:
        workspace_id = f"ws_brandkit_race_{uuid4().hex[:10]}"
        holding = asyncio.Event()
        release = asyncio.Event()

        requests: list[httpx.Request] = []

        async def recording(request: httpx.Request) -> httpx.Response:
            # Park the winner INSIDE the design call, so its advisory lock is provably still
            # held when the second trigger runs.
            requests.append(request)
            holding.set()
            await release.wait()
            return _accepted()

        async with db_lifespan() as engine:

            def conn_factory() -> Any:
                return engine.begin()

            trigger = BrandKitWebsiteIngestion(
                base_url=DESIGN_BASE_URL,
                conn_factory=conn_factory,
                client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(recording)),
            )
            first = asyncio.create_task(
                trigger.ensure(workspace_id=workspace_id, website="https://insight.health")
            )
            await asyncio.wait_for(holding.wait(), timeout=10)
            # The winner is mid-enqueue, still holding its transaction's advisory lock.
            second = await trigger.ensure(
                workspace_id=workspace_id, website="https://insight.health"
            )
            release.set()
            winner = await asyncio.wait_for(first, timeout=10)

        assert second is None
        assert winner is not None
        assert len(requests) == 1

    run_async(scenario())


# --- 5. brand stamping on the kit-birth path -------------------------------------------------


def test_a_provisioned_workspace_stamps_its_one_brand_on_the_born_kit() -> None:
    """Why slice 2 threads no ``brand_id``: self-serve provisioning creates exactly one brand,
    and the kit-birth path's exactly-one-brand heuristic (``joins.resolve_brand_id``) finds it.

    The heuristic's own one/none/several rules are covered by
    ``tests/design/test_concept_joins_dal_db.py``; what is asserted here is the premise this
    slice depends on — that an onboarding workspace is the "exactly one" case, and that a kit
    born from ingestion in it carries the PROVISIONED brand.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            provisioned = await _provision(conn, "brandkit-brand")
            workspace_id = provisioned.workspace.workspace_id
            kit_id = f"brand_kit_ing_{uuid4().hex}"
            created = await design_brand.create_brand_kit(
                conn,
                workspace_id=workspace_id,
                brand_kit={
                    "id": kit_id,
                    "version": 1,
                    "name": "Insight Health",
                    "approval_status": "draft",
                    "tokens": {},
                },
                brand_summary={"product_ready": True},
                diagnostics=[],
                # The source a website ingestion actually publishes under (verified against the
                # live kit the slice-1 harvest produced).
                source="website",
            )
            assert created["brand_id"] == provisioned.brand.brand_id
            # And the human gate is intact: ingestion never approves.
            assert created["approval_status"] == "draft"

    run_async(scenario())


# --- 6. config-off is a clean no-op ----------------------------------------------------------


def test_no_design_api_base_url_means_no_trigger() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.design_api_base_url is None
    assert build_brand_kit_ingestion_trigger(settings=settings, conn_factory=transaction) is None


def test_a_configured_base_url_builds_the_trigger() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, design_api_base_url=f"{DESIGN_BASE_URL}/"
    )
    trigger = build_brand_kit_ingestion_trigger(settings=settings, conn_factory=transaction)
    assert isinstance(trigger, BrandKitWebsiteIngestion)
    # A trailing slash in the configured base must not double up in the request URL.
    assert trigger._base_url == DESIGN_BASE_URL  # noqa: SLF001 — one-line normalization check
