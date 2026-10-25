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
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api import projections_app, projections_main, run_composition
from clue_api.brand_kit_ingestion import (
    INGEST_WEBSITE_PATH,
    ONBOARD_AD_ASSETS_PATH,
    AdHarvestConfig,
    BrandKitWebsiteIngestion,
    build_brand_kit_ingestion_trigger,
    company_domain,
)
from clue_api.stage0_setup import create_stage0_setup_router
from clue_auth import provision_self_serve_workspace
from clue_config import Secrets, Settings
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
    ad_harvest: AdHarvestConfig | None = None,
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
                ad_harvest=ad_harvest,
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


# --- 7. the production HTTP root actually passes the trigger through -------------------------


class _NoKeySecrets:
    """``Secrets`` with no model credential — composition only, never a model call."""

    openrouter_api_key = None


def _captured_setup_router(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture the kwargs the HTTP root hands ``create_stage0_setup_router``.

    The router keeps its trigger private and the root returns only the app, so the composed
    value is observed at the seam it is passed through. The real router is still built, so the
    root's own wiring is exercised rather than replaced.
    """
    seen: dict[str, Any] = {}
    real = projections_app.create_stage0_setup_router

    def capturing(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(projections_app, "create_stage0_setup_router", capturing)
    return seen


@pytest.mark.parametrize("configured", [True, False])
def test_the_http_root_composes_the_trigger_exactly_when_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, configured: bool
) -> None:
    monkeypatch.setattr(run_composition, "Secrets", _NoKeySecrets)
    seen = _captured_setup_router(monkeypatch)
    projections_main.build_application(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            storage_fs_root=str(tmp_path / "artifacts"),
            self_serve_provisioning_enabled=True,
            # The setup router rides the legacy-recon flag since 2026-09-12 (ledger A4).
            legacy_stage0_recon_enabled=True,
            design_api_base_url=(DESIGN_BASE_URL if configured else None),
        ),
        secrets=Secrets(_env_file=None),
    )
    trigger = seen["brand_kit_ingestion"]
    if configured:
        assert isinstance(trigger, BrandKitWebsiteIngestion)
    else:
        assert trigger is None


# --- 8. slice 3: GET /stage0/setup/current reports the job's live status ----------------------
#
# The onboarding checklist's "Creating brand kit" row stops being a dummy: the setup poll carries
# the workspace's newest ingestion job, honest job truth and nothing derived (the row mapping is
# the frontend's). These pin the wire half.


async def _current(conn_factory: Any, workspace_id: str) -> dict[str, Any]:
    app = _setup_app(conn_factory=conn_factory, design=_DesignApiDouble(), recon=_CaptureEnqueuer())
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/stage0/setup/current", headers={"X-Workspace-Id": workspace_id}
        )
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def test_setup_current_reports_no_ingestion_job_as_null() -> None:
    """No job row is honest null — never a fabricated "queued" the row would spin on."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_factory = _shared_conn_factory(conn)
            provisioned = await _provision(conn, "brandkit-current-none")
            body = await _current(conn_factory, provisioned.workspace.workspace_id)
            assert body["status"] == "none"
            # Present in the branch, and explicitly null.
            assert "brand_kit_ingestion" in body
            assert body["brand_kit_ingestion"] is None

    run_async(scenario())


def test_setup_current_reports_the_workspaces_job_and_its_live_status() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_factory = _shared_conn_factory(conn)
            provisioned = await _provision(conn, "brandkit-current-live")
            workspace_id = provisioned.workspace.workspace_id
            job = await design_ingestion.create_job(
                conn,
                workspace_id=workspace_id,
                kind="website",
                request={"url": PROFILE["company_website"]},
            )
            job_id = str(job["job_id"])

            queued = await _current(conn_factory, workspace_id)
            assert queued["brand_kit_ingestion"] == {"job_id": job_id, "status": "queued"}

            # The read is live truth, not a snapshot taken at enqueue time.
            await design_ingestion.set_running(conn, workspace_id=workspace_id, job_id=job_id)
            running = await _current(conn_factory, workspace_id)
            assert running["brand_kit_ingestion"] == {"job_id": job_id, "status": "running"}

            await design_ingestion.fail(
                conn,
                workspace_id=workspace_id,
                job_id=job_id,
                error={"code": "ingest.failed", "message": "no usable brand signal"},
            )
            failed = await _current(conn_factory, workspace_id)
            assert failed["brand_kit_ingestion"] == {"job_id": job_id, "status": "failed"}

    run_async(scenario())


def test_setup_current_serves_only_the_newest_job_and_never_another_workspaces() -> None:
    """Tenancy is the DAL's (`list_recent` is workspace-scoped); newest-first is its order."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_factory = _shared_conn_factory(conn)
            mine = await _provision(conn, "brandkit-current-mine")
            theirs = await _provision(conn, "brandkit-current-theirs")
            await design_ingestion.create_job(
                conn,
                workspace_id=theirs.workspace.workspace_id,
                kind="website",
                request={"url": "https://not-mine.example"},
            )
            body = await _current(conn_factory, mine.workspace.workspace_id)
            assert body["brand_kit_ingestion"] is None

            older = await design_ingestion.create_job(
                conn,
                workspace_id=mine.workspace.workspace_id,
                kind="website",
                request={"url": PROFILE["company_website"]},
            )
            newest = await design_ingestion.create_job(
                conn,
                workspace_id=mine.workspace.workspace_id,
                kind="asset_upload",
                request={"url": PROFILE["company_website"]},
            )
            served = await _current(conn_factory, mine.workspace.workspace_id)
            assert served["brand_kit_ingestion"]["job_id"] in {
                str(newest["job_id"]),
                str(older["job_id"]),
            }
            # Same created_at (one transaction, one now()); the ported tiebreak is job_id DESC.
            expected = max(str(older["job_id"]), str(newest["job_id"]))
            assert served["brand_kit_ingestion"]["job_id"] == expected

    run_async(scenario())


def test_setup_current_carries_the_field_in_the_unavailable_branch_too() -> None:
    """Every response branch answers the same question, so the client never sees the key vanish."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_factory = _shared_conn_factory(conn)
            body = await _current(conn_factory, f"ws_never_provisioned_{uuid4().hex[:10]}")
            assert body["status"] == "unavailable"
            assert "brand_kit_ingestion" in body
            assert body["brand_kit_ingestion"] is None

    run_async(scenario())


# --- 9. the ad harvest rides the same trigger (auto ad ingestion, 2026-09-28) -----------------
#
# Onboarding also offers ONE ad-assets harvest for the company's own LinkedIn ads, in parallel with
# the website ingestion. The harvest needs no brand kit (the card step that does runs later, on
# the design side), so it is offered at the same moment, independently fail-soft, once per kind.

AD_HARVEST = AdHarvestConfig(max_creatives=50, max_pages=8)


def test_first_time_setup_also_offers_the_ad_harvest() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_factory = _shared_conn_factory(conn)
            provisioned = await _provision(conn, "adharvest-once")
            workspace_id = provisioned.workspace.workspace_id
            design = _DesignApiDouble()
            app = _setup_app(
                conn_factory=conn_factory,
                design=design,
                recon=_CaptureEnqueuer(),
                ad_harvest=AD_HARVEST,
            )
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                started = await client.post(
                    "/stage0/setup", headers={"X-Workspace-Id": workspace_id}
                )
            assert started.status_code == 202

            assert [request.url.path for request in design.requests] == [
                INGEST_WEBSITE_PATH,
                ONBOARD_AD_ASSETS_PATH,
            ]
            ad = design.requests[1]
            assert ad.headers["X-Workspace-Id"] == workspace_id
            assert json.loads(ad.content) == {
                "phase": "harvest",
                "company_domain": "insight.health",
                "max_creatives": 50,
                "max_pages": 8,
            }

    run_async(scenario())


def test_an_ad_harvest_failure_leaves_the_website_ingestion_alone() -> None:
    async def scenario() -> None:
        workspace_id = f"ws_adharvest_failsoft_{uuid4().hex[:10]}"

        def responder(index: int) -> httpx.Response:
            if index == 1:
                raise httpx.ConnectError("the ad route is down")
            return _accepted(index)

        design = _DesignApiDouble(responder)
        async with db_lifespan() as engine:
            trigger = BrandKitWebsiteIngestion(
                base_url=DESIGN_BASE_URL,
                conn_factory=lambda: engine.begin(),
                client_factory=design.client,
                ad_harvest=AD_HARVEST,
            )
            website_job = await trigger.ensure(
                workspace_id=workspace_id, website="https://insight.health"
            )
        assert website_job is not None
        assert len(design.requests) == 2

    run_async(scenario())


def test_each_kind_is_offered_once_and_independently() -> None:
    """An ad job never stands in for a kit ingestion, and a kit ingestion never for an ad job."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_factory = _shared_conn_factory(conn)

            had_ads = await _provision(conn, "adharvest-had-ads")
            await design_ingestion.create_job(
                conn,
                workspace_id=had_ads.workspace.workspace_id,
                kind="ad_assets",
                request={"phase": "harvest", "company_domain": "insight.health"},
            )
            design = _DesignApiDouble()
            await BrandKitWebsiteIngestion(
                base_url=DESIGN_BASE_URL,
                conn_factory=conn_factory,
                client_factory=design.client,
                ad_harvest=AD_HARVEST,
            ).ensure(workspace_id=had_ads.workspace.workspace_id, website="https://insight.health")
            assert [r.url.path for r in design.requests] == [INGEST_WEBSITE_PATH]

            had_kit = await _provision(conn, "adharvest-had-kit")
            await design_ingestion.create_job(
                conn,
                workspace_id=had_kit.workspace.workspace_id,
                kind="website",
                request={"url": PROFILE["company_website"]},
            )
            design = _DesignApiDouble()
            await BrandKitWebsiteIngestion(
                base_url=DESIGN_BASE_URL,
                conn_factory=conn_factory,
                client_factory=design.client,
                ad_harvest=AD_HARVEST,
            ).ensure(workspace_id=had_kit.workspace.workspace_id, website="https://insight.health")
            assert [r.url.path for r in design.requests] == [ONBOARD_AD_ASSETS_PATH]

    run_async(scenario())


def test_setup_current_reports_the_kit_ingestion_not_the_ad_harvest() -> None:
    """The checklist row is "Creating brand kit"; an ad harvest builds no kit."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            conn_factory = _shared_conn_factory(conn)
            provisioned = await _provision(conn, "adharvest-checklist")
            workspace_id = provisioned.workspace.workspace_id
            website = await design_ingestion.create_job(
                conn,
                workspace_id=workspace_id,
                kind="website",
                request={"url": PROFILE["company_website"]},
            )
            await design_ingestion.create_job(
                conn,
                workspace_id=workspace_id,
                kind="ad_assets",
                request={"phase": "harvest", "company_domain": "insight.health"},
            )
            body = await _current(conn_factory, workspace_id)
            assert body["brand_kit_ingestion"]["job_id"] == str(website["job_id"])

    run_async(scenario())


@pytest.mark.parametrize(
    ("enabled", "expected"),
    [(True, AdHarvestConfig(max_creatives=50, max_pages=8)), (False, None)],
)
def test_the_builder_reads_the_ad_harvest_settings(
    enabled: bool, expected: AdHarvestConfig | None
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        design_api_base_url=DESIGN_BASE_URL,
        brand_ad_assets_auto_onboard=enabled,
    )
    trigger = build_brand_kit_ingestion_trigger(settings=settings, conn_factory=transaction)
    assert trigger is not None
    assert trigger._ad_harvest == expected  # noqa: SLF001 — the composed config is the contract


@pytest.mark.parametrize(
    ("website", "domain"),
    [
        ("https://insight.health", "insight.health"),
        ("https://www.Ramp.com/pricing?x=1", "ramp.com"),
        ("apollo.io", "apollo.io"),
        ("http://sub.example.co.uk:8080/", "sub.example.co.uk"),
        ("", None),
        ("   ", None),
    ],
)
def test_company_domain_is_the_bare_host(website: str, domain: str | None) -> None:
    assert company_domain(website) == domain


# --- gap-aware re-entry (spec 2026-10-25 §3.2, defect d) --------------------------------------


async def _job_with_status(conn: AsyncConnection, workspace_id: str, status: str,
                           *, kit: bool) -> None:
    from sqlalchemy import text

    kit_id = None
    if kit:
        kit_id = f"brand_kit_gap_{uuid4().hex[:8]}"
        await design_brand.create_brand_kit(
            conn, workspace_id=workspace_id,
            brand_kit={"id": kit_id, "version": 1, "name": "Kit", "approval_status": "approved"},
            brand_summary={"product_ready": False}, diagnostics=[], source="website",
        )
    job = await design_ingestion.create_job(
        conn, workspace_id=workspace_id, kind="website",
        request={"url": PROFILE["company_website"]},
    )
    await conn.execute(
        text("UPDATE design_ingestion_job SET status = CAST(:s AS design_ingestion_status),"
             " brand_kit_id = :k, brand_kit_version = :v WHERE job_id = :j"),
        {"s": status, "k": kit_id, "v": 1 if kit else None, "j": job["job_id"]},
    )


async def _replay_setup(conn: AsyncConnection, workspace_id: str) -> "_DesignApiDouble":
    design = _DesignApiDouble()
    app = _setup_app(conn_factory=_shared_conn_factory(conn), design=design,
                     recon=_CaptureEnqueuer())
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        replayed = await client.post("/stage0/setup", headers={"X-Workspace-Id": workspace_id})
    assert replayed.status_code == 202
    return design


def test_ensure_recaptures_when_the_newest_capture_failed_and_no_kit_exists() -> None:
    """A capture that died (the design API was down) must not block every later start."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            provisioned = await _provision(conn, "brandkit-recapture")
            workspace_id = provisioned.workspace.workspace_id
            await _job_with_status(conn, workspace_id, "failed", kit=False)
            design = await _replay_setup(conn, workspace_id)
            assert [request.url.path for request in design.requests].count(INGEST_WEBSITE_PATH) == 1

    run_async(scenario())


def test_ensure_skips_a_gapped_kit_which_repair_heals() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            provisioned = await _provision(conn, "brandkit-gapped")
            workspace_id = provisioned.workspace.workspace_id
            await _job_with_status(conn, workspace_id, "succeeded_with_gaps", kit=True)
            design = await _replay_setup(conn, workspace_id)
            assert INGEST_WEBSITE_PATH not in [request.url.path for request in design.requests]

    run_async(scenario())
