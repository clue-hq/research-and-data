"""The brand-context Knowledge reads (ARV2 O5): tree, document, onboarding status."""

from __future__ import annotations

import uuid
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.onboarding_store import create_run, finish_step, mark_run_running, start_step
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_spine import create_brand
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_WS = "ws-o5-knowledge"
_USER = "usr_o5"
_BASE = f"{FRONTEND_READ_PREFIX}/brand-context"

OVERVIEW = """---
kind: company-overview
as_of: '2026-09-08'
company_domain: insighthealth.ai
sources:
  facts.legal_name:
    citations:
    - url: https://www.insighthealth.ai/
      title: Insight Health
    confidence: high
---

# Insight Health overview

Body.
"""
ICP = """---
kind: icp-definition
icp_key: gi-groups
product_ids: [prd_a]
---

# GI groups

Body.
"""
PRODUCT = """---
kind: product-research
product_id: prd_a
---

# Aura AI Scribe

Body.
"""


def _app(conn: AsyncConnection, storage: _MemoryStorage | None) -> FastAPI:
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(_env_file=None, frontend_read_enabled=True),
        conn_factory=conn_session_factory(conn),
        ingestion_storage=storage,
        manage_db_lifespan=False,
    )


async def _get(
    conn: AsyncConnection, storage: _MemoryStorage | None, path: str, *, ws: str = _WS
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_app(conn, storage)), base_url="http://knowledge"
    ) as client:
        return await client.get(f"{_BASE}{path}", headers={"X-Workspace-Id": ws})


async def _document(
    conn,
    artifacts,
    *,
    ws,
    brand_id,
    folder,
    path,
    kind,
    version,
    status,
    body,
    produced_by_step_id=None,
):
    ref = await artifacts.persist_body(
        workspace_id=ws, data=body.encode(), media_type="text/markdown"
    )
    document_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, folder, "
            " path, kind, version, status, artifact_key, artifact_sha256, produced_by_step_id) "
            "VALUES (:id, :ws, :brand, :folder, :path, :kind, :version, :status, :key, :sha, "
            " :step)"
        ),
        {
            "id": document_id,
            "ws": ws,
            "brand": brand_id,
            "folder": folder,
            "path": path,
            "kind": kind,
            "version": version,
            "status": status,
            "key": ref.artifact_key,
            "sha": ref.sha256,
            "step": produced_by_step_id,
        },
    )
    return document_id


async def _seed(conn, storage):
    project = await seed_project(conn, _WS, name="O5")
    await seed_principal(conn, workspace_id=_WS, user_id=_USER)
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_session_factory(conn))
    brand = project.brand_id
    ids = {}
    ids["overview_v1"] = await _document(
        conn,
        artifacts,
        ws=_WS,
        brand_id=brand,
        folder="company",
        path="company/overview.md",
        kind="company-overview",
        version=1,
        status="superseded",
        body=OVERVIEW.replace("Body.", "Old body."),
    )
    ids["overview_v2"] = await _document(
        conn,
        artifacts,
        ws=_WS,
        brand_id=brand,
        folder="company",
        path="company/overview.md",
        kind="company-overview",
        version=2,
        status="ready",
        body=OVERVIEW,
    )
    ids["catalog_running"] = await _document(
        conn,
        artifacts,
        ws=_WS,
        brand_id=brand,
        folder="product",
        path="product/catalog.md",
        kind="product-catalog",
        version=1,
        status="running",
        body="---\nkind: product-catalog\n---\n\n# Catalog\n",
    )
    ids["product"] = await _document(
        conn,
        artifacts,
        ws=_WS,
        brand_id=brand,
        folder="product",
        path="product/aura-ai-scribe.md",
        kind="product-research",
        version=1,
        status="ready",
        body=PRODUCT,
    )
    ids["icp"] = await _document(
        conn,
        artifacts,
        ws=_WS,
        brand_id=brand,
        folder="audience",
        path="audience/icp-gi-groups.md",
        kind="icp-definition",
        version=1,
        status="proposed",
        body=ICP,
    )
    ids["reviews_empty"] = await _document(
        conn,
        artifacts,
        ws=_WS,
        brand_id=brand,
        folder="proof",
        path="proof/customer-reviews.md",
        kind="customer-reviews",
        version=1,
        status="empty",
        body="---\nkind: customer-reviews\n---\n\n# Reviews\n",
    )
    return brand, ids


def test_the_tree_lists_servable_current_documents_in_the_dummy_folder_order() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = _MemoryStorage()
            brand, ids = await _seed(conn, storage)
            response = await _get(conn, storage, "/knowledge")
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["brandId"] == brand
            assert [f["key"] for f in body["folders"]] == [
                "company",
                "product",
                "audience",
                "proof",
            ]
            assert [f["label"] for f in body["folders"]] == [
                "Company",
                "Product",
                "Audience",
                "Proof",
            ]
            by_key = {f["key"]: f["documents"] for f in body["folders"]}
            assert [d["path"] for d in by_key["company"]] == ["company/overview.md"]
            assert (
                by_key["company"][0]["version"] == 2 and by_key["company"][0]["status"] == "ready"
            )
            assert by_key["company"][0]["id"] == str(ids["overview_v2"])
            assert by_key["company"][0]["title"] == "Insight Health overview"
            # running catalog and empty reviews are not servable → absent; the product report is
            assert [d["path"] for d in by_key["product"]] == ["product/aura-ai-scribe.md"]
            assert by_key["product"][0]["productId"] == "prd_a"
            assert (
                by_key["audience"][0]["icpKey"] == "gi-groups"
                and by_key["audience"][0]["status"] == "proposed"
            )
            assert by_key["proof"] == []
            assert set(by_key["company"][0]) == {
                "id",
                "path",
                "title",
                "kind",
                "version",
                "status",
                "updatedAt",
                "productId",
                "icpKey",
            }

    run_async(scenario())


def test_a_document_serves_markdown_front_matter_and_flattened_sources() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = _MemoryStorage()
            _, ids = await _seed(conn, storage)
            response = await _get(conn, storage, f"/knowledge/documents/{ids['overview_v2']}")
            assert response.status_code == 200, response.text
            body = response.json()
            assert (
                body["id"] == str(ids["overview_v2"]) and body["title"] == "Insight Health overview"
            )
            assert body["markdown"].startswith("# Insight Health overview")
            assert body["frontMatter"]["kind"] == "company-overview"
            assert body["sources"] == [
                {
                    "section": "facts.legal_name",
                    "url": "https://www.insighthealth.ai/",
                    "title": "Insight Health",
                    "confidence": "high",
                }
            ]
            # non-servable, other-workspace, unknown → 404 with the envelope code
            for missing in (ids["catalog_running"], ids["reviews_empty"], uuid.uuid4()):
                refused = await _get(conn, storage, f"/knowledge/documents/{missing}")
                assert refused.status_code == 404, refused.text
                assert refused.json()["error"]["code"] == "KNOWLEDGE_DOCUMENT_NOT_FOUND"
            foreign = await _get(
                conn, storage, f"/knowledge/documents/{ids['overview_v2']}", ws="ws-someone-else"
            )
            assert foreign.status_code == 404

    run_async(scenario())


def test_without_a_storage_backend_the_tree_serves_and_the_document_refuses_loudly() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = _MemoryStorage()
            _, ids = await _seed(conn, storage)
            tree = await _get(conn, None, "/knowledge")
            assert tree.status_code == 200
            detail = await _get(conn, None, f"/knowledge/documents/{ids['overview_v2']}")
            assert (
                detail.status_code == 503
                and detail.json()["error"]["code"] == "KNOWLEDGE_STORAGE_UNAVAILABLE"
            )

    run_async(scenario())


def test_the_brand_is_the_newest_onboarding_runs_brand_or_the_only_brand_or_explicit() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = _MemoryStorage()
            brand_a, _ = await _seed(conn, storage)
            brand_b = (await create_brand(conn, workspace_id=_WS, name="Second brand")).brand_id
            # two brands, no run → no brand → empty folders
            none = (await _get(conn, storage, "/knowledge")).json()
            assert none["brandId"] is None and all(f["documents"] == [] for f in none["folders"])
            # a run on brand B makes B the default
            run_id = uuid.uuid4()
            await create_run(
                conn,
                run_id=run_id,
                workspace_id=_WS,
                brand_id=brand_b,
                company_domain="x.io",
                requested_by_user_id=_USER,
            )
            assert (await _get(conn, storage, "/knowledge")).json()["brandId"] == brand_b
            # explicit brand wins; a foreign brand id is refused as none
            assert (await _get(conn, storage, f"/knowledge?brandId={brand_a}")).json()[
                "brandId"
            ] == brand_a
            assert (await _get(conn, storage, "/knowledge?brandId=brd_not_mine")).json()[
                "brandId"
            ] is None

    run_async(scenario())


def test_onboarding_current_mirrors_the_run_and_its_steps() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = _MemoryStorage()
            brand, _ = await _seed(conn, storage)
            nothing = (await _get(conn, storage, "/onboarding/current")).json()
            assert nothing == {"runId": None, "status": "none", "steps": [], "costUsd": "0"}
            run_id = uuid.uuid4()
            await create_run(
                conn,
                run_id=run_id,
                workspace_id=_WS,
                brand_id=brand,
                company_domain="insighthealth.ai",
                requested_by_user_id=_USER,
            )
            await mark_run_running(conn, run_id=run_id)
            step = uuid.uuid4()
            await start_step(
                conn, step_id=step, run_id=run_id, workspace_id=_WS, kind="overview", phase="fast"
            )
            await finish_step(conn, step_id=step, status="completed", cost_usd=Decimal("0.5"))
            body = (await _get(conn, storage, "/onboarding/current")).json()
            assert (
                body["runId"] == str(run_id)
                and body["status"] == "running"
                and body["costUsd"] == "0.500000"
            )
            (only,) = body["steps"]
            assert (only["kind"], only["status"], only["failureCode"], only["costUsd"]) == (
                "overview",
                "completed",
                None,
                "0.500000",
            )
            assert only["startedAt"].endswith("Z") and only["finishedAt"].endswith("Z")

    run_async(scenario())
