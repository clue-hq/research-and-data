"""M12.3 — the FastAPI handoff HTTP surface (the terminal subsystem seam).

Drives the ASGI app in-process via ``httpx.ASGITransport`` on the same event loop as the rollback
connection (the dependency is overridden to yield it). Covers: GET one handoff + schema header (AC1/
AC5); a mid-run / cross-tenant / missing fetch is ``404`` and a missing tenant header is ``401``
(AC2/AC6); the list endpoint; provenance resolution; and that the surface is **read-only** — no
write route exists (AC4). DB-backed (skips without one)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api import HANDOFF_SCHEMA_HEADER, create_handoff_app
from clue_core import (
    AccountHandoff,
    EntityId,
    NarrativeSupport,
    Persona,
    ProjectPhase,
    ProjectRunId,
    ProvenanceRef,
    Score,
    ScoreComponent,
    ValueNarrativeItem,
    new_claim_id,
    new_entity_id,
    new_project_run_id,
)
from clue_research.narrative import (
    HANDOFF_SCHEMA_VERSION,
    AssembledHandoff,
    HandoffService,
    InMemoryHandoffReadinessReader,
    RunReadiness,
    write_handoff,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

_CLIENT = "client-acme"
_OTHER = "client-other"
_AT = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def _conn_dependency(conn: AsyncConnection):
    async def dep() -> AsyncIterator[AsyncConnection]:
        yield conn

    return dep


def _assembled(*, account: EntityId, run: ProjectRunId, claim_id=None) -> AssembledHandoff:
    cid = claim_id or new_claim_id()
    handoff = AccountHandoff(
        account_entity_id=account,
        fit_score=Score(
            value=0.8,
            components=(
                ScoreComponent(name="x", weight=1.0, value=0.8, evidence_claim_ids=(cid,)),
            ),
        ),
        intent_score=Score(value=0.5),
        committee=(),
        value_narrative=(
            ValueNarrativeItem(
                claim_id=new_claim_id(),
                persona=Persona.ECONOMIC_BUYER,
                argument="why",
                supporting=NarrativeSupport(),
            ),
        ),
        provenance_index={str(cid): ProvenanceRef(source_url="https://src/x", source_tier=1)},
        icp_spec_version=1,
        project_run_id=run,
        assembled_at=_AT,
    )
    return AssembledHandoff(handoff=handoff)


def _app(conn: AsyncConnection, *, run: ProjectRunId, phase: ProjectPhase = ProjectPhase.HANDOFF):
    reader = InMemoryHandoffReadinessReader(
        runs={run: RunReadiness(project_run_id=run, workspace_id=_CLIENT, phase=phase)}
    )
    service = HandoffService(readiness_reader=reader)
    return create_handoff_app(
        service, conn_dependency=_conn_dependency(conn), manage_db_lifespan=False
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def test_get_handoff_200_with_schema_header() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            acc, run, cid = new_entity_id(), new_project_run_id(), new_claim_id()
            await write_handoff(
                conn, _assembled(account=acc, run=run, claim_id=cid), workspace_id=_CLIENT
            )
            async with _client(_app(conn, run=run)) as client:
                r = await client.get(
                    f"/accounts/{acc}/handoff",
                    params={"icp_spec_version": 1},
                    headers={"X-Workspace-Id": _CLIENT},
                )
            assert r.status_code == 200
            assert r.headers[HANDOFF_SCHEMA_HEADER] == HANDOFF_SCHEMA_VERSION
            body = r.json()
            assert body["schema_version"] == HANDOFF_SCHEMA_VERSION
            assert body["assembled"]["handoff"]["account_entity_id"] == str(acc)
            # AC1: the provenance entry resolves to a real source, not just a key present.
            index = body["assembled"]["handoff"]["provenance_index"]
            assert str(cid) in index
            ref = index[str(cid)]
            assert ref["source_url"] == "https://src/x"
            assert ref["source_tier"] == 1

    run_async(_run())


def test_get_handoff_product_query_is_exact() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            account, run = new_entity_id(), new_project_run_id()
            await write_handoff(
                conn,
                _assembled(account=account, run=run),
                workspace_id=_CLIENT,
                product_id="product-a",
            )
            async with _client(_app(conn, run=run)) as client:
                exact = await client.get(
                    f"/accounts/{account}/handoff",
                    params={"icp_spec_version": 1, "product_id": "product-a"},
                    headers={"X-Workspace-Id": _CLIENT},
                )
                neutral = await client.get(
                    f"/accounts/{account}/handoff",
                    params={"icp_spec_version": 1},
                    headers={"X-Workspace-Id": _CLIENT},
                )
            assert exact.status_code == 200
            assert neutral.status_code == 404

    run_async(_run())


def test_missing_handoff_is_404() -> None:
    """AC2: an account with no materialised handoff (still in deep/verification) is not servable."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run = new_project_run_id()
            async with _client(_app(conn, run=run, phase=ProjectPhase.DEEP)) as client:
                r = await client.get(
                    f"/accounts/{new_entity_id()}/handoff",
                    params={"icp_spec_version": 1},
                    headers={"X-Workspace-Id": _CLIENT},
                )
            assert r.status_code == 404

    run_async(_run())


def test_cross_tenant_is_404() -> None:
    """AC6: a client cannot fetch another client's handoff (cross-tenant → 404, not 403/leak)."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            acc, run = new_entity_id(), new_project_run_id()
            await write_handoff(conn, _assembled(account=acc, run=run), workspace_id=_CLIENT)
            async with _client(_app(conn, run=run)) as client:
                r = await client.get(
                    f"/accounts/{acc}/handoff",
                    params={"icp_spec_version": 1},
                    headers={"X-Workspace-Id": _OTHER},
                )
            assert r.status_code == 404

    run_async(_run())


def test_missing_tenant_header_is_401() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            acc, run = new_entity_id(), new_project_run_id()
            await write_handoff(conn, _assembled(account=acc, run=run), workspace_id=_CLIENT)
            async with _client(_app(conn, run=run)) as client:
                r = await client.get(f"/accounts/{acc}/handoff", params={"icp_spec_version": 1})
            assert r.status_code == 401

    run_async(_run())


def test_list_endpoint_returns_ready_with_phase() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run, acc = new_project_run_id(), new_entity_id()
            await write_handoff(conn, _assembled(account=acc, run=run), workspace_id=_CLIENT)
            async with _client(_app(conn, run=run)) as client:
                r = await client.get(
                    f"/project_runs/{run}/handoffs", headers={"X-Workspace-Id": _CLIENT}
                )
            assert r.status_code == 200
            body = r.json()
            assert body["total"] == 1
            assert body["run_phase"] == ProjectPhase.HANDOFF.value
            assert body["items"][0]["account_entity_id"] == str(acc)

    run_async(_run())


def test_list_excludes_unmaterialised_mid_run_account() -> None:
    """AC2: only ready (materialised) accounts appear in the list — an account still mid-run (no
    materialised handoff) is absent even though it belongs to the run."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run, ready_acc, mid_run_acc = (
                new_project_run_id(),
                new_entity_id(),
                new_entity_id(),
            )
            # only ready_acc has a materialised handoff; mid_run_acc has none.
            await write_handoff(conn, _assembled(account=ready_acc, run=run), workspace_id=_CLIENT)
            async with _client(_app(conn, run=run)) as client:
                r = await client.get(
                    f"/project_runs/{run}/handoffs", headers={"X-Workspace-Id": _CLIENT}
                )
            assert r.status_code == 200
            body = r.json()
            served = {item["account_entity_id"] for item in body["items"]}
            assert served == {str(ready_acc)}
            assert str(mid_run_acc) not in served

    run_async(_run())


def test_provenance_endpoint_resolves_and_404s() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            acc, run, cid = new_entity_id(), new_project_run_id(), new_claim_id()
            await write_handoff(
                conn, _assembled(account=acc, run=run, claim_id=cid), workspace_id=_CLIENT
            )
            async with _client(_app(conn, run=run)) as client:
                ok = await client.get(
                    f"/accounts/{acc}/handoff/provenance/{cid}",
                    params={"icp_spec_version": 1},
                    headers={"X-Workspace-Id": _CLIENT},
                )
                miss = await client.get(
                    f"/accounts/{acc}/handoff/provenance/{new_claim_id()}",
                    params={"icp_spec_version": 1},
                    headers={"X-Workspace-Id": _CLIENT},
                )
            assert ok.status_code == 200
            assert ok.json()["provenance"]["source_url"] == "https://src/x"
            assert miss.status_code == 404

    run_async(_run())


def test_surface_is_read_only_no_write_routes() -> None:
    """AC4: the handoff API has no write path — every route method is read-only (GET/HEAD)."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            app = _app(conn, run=new_project_run_id())
            write_methods = {"POST", "PUT", "PATCH", "DELETE"}
            for route in app.routes:
                if isinstance(route, APIRoute):
                    assert not (route.methods & write_methods), (
                        f"{route.path} exposes a write method"
                    )

    run_async(_run())
