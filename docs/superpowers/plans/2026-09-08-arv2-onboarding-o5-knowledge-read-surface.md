# ARV2 Onboarding O5 — Brand-context Knowledge Read Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The brand-context page's Knowledge section lists the onboarding documents (`company/`, `product/`, `audience/`, `proof/`) from the real `brand_knowledge_document` store through three workspace-scoped read endpoints, renders each as markdown with no edit control, and fills in as an onboarding run publishes documents.

**Architecture:** One new read module on the existing flag-gated `/frontend/v1` router (auth, tenant scoping, error envelope and CORS come for free) serves the folder tree, one document with its markdown and sources, and the onboarding-run status. The frontend's brand-context repository gains a second source next to the brand-kit read: it fetches the tree and the bodies through the authenticated Clue-backend seam and maps them onto the dummy's existing `BrandKnowledgeFolder` shape, keeping the kit's Design folder. The page's edit toggle is removed. A small client hook polls the status read while a run is live and refreshes the server-rendered page when a step lands.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy async `text()` SQL / `clue_storage.read_verified_artifact` / pytest with `rollback_conn`; Next.js App Router / TypeScript / Zod / `tsx --test`.

**Spec:** `docs/specs/ARV2-ONBOARDING-PLAN.md` §7 (the read contract and rendering rules), §9 O5 row; `docs/specs/ARV2-AGENT-BRIEFING.md` §2 items 6–7 and §3 (dummy is presentation truth; never invent UI); `apps/frontend/docs/api-contracts/brand-context.md` (the frontend proposal and every prior resolution). Founder rulings 2026-09-08: **no status chip — only servable documents are listed; the edit control is removed from the whole page (Design.md included).**

## Global Constraints

- **Dummy is presentation truth.** The Knowledge section's wire shape is the lifted `BrandKnowledgeFolderSchema` / `BrandKnowledgeDocumentSchema` (`apps/frontend/src/features/brand-context/model/brand-context.ts:76-89`): `{ documents: [{ body, folderId, id, name, path, updatedLabel }], id, label }`. No new UI element; anything the dummy has no slot for (status, kind, version, sources, dates) rides the wire and is not rendered. `updatedLabel` is on the wire but never rendered (§7 R1).
- **Servable only (ruling):** the tree lists documents whose status is `ready`, `proposed` or `confirmed`, the highest such version per path. `running`/`empty`/`failed`/`superseded` never appear.
- **Folder order and labels (dummy):** `company` "Company", `product` "Product", `audience` "Audience", `proof` "Proof". The `design` folder stays the brand kit's (served from `brand_kit_json.brief` as today) — the platform read never serves `design`.
- **Read-only:** no mutation endpoints; the proposed `POST/PUT` in the contract doc stay proposals; the page's Preview/Edit control is removed (ruling).
- **Mount:** the `/frontend/v1` router (`platform/api/clue_api/frontend_read/app.py`, `FRONTEND_READ_PREFIX = "/frontend/v1"`), behind `settings.frontend_read_enabled`, with the router-level `frontend_read_workspace_resolver` dependency. Paths: `GET /frontend/v1/brand-context/knowledge`, `GET /frontend/v1/brand-context/knowledge/documents/{document_id}`, `GET /frontend/v1/brand-context/onboarding/current`. §7 wrote `/api/v1/...`; the contract doc records the real prefix (Task 2).
- **Wire convention:** camelCase JSON via `WireModel` (`frontend_read/accounts_list.py:141`: frozen, `extra="forbid"`, `alias_generator=to_camel`, `populate_by_name=True`).
- **Standing rule (catalog contract §10):** no Client-KB version, readiness decision or Stage-0 pin on any path. The reads touch only `brand_knowledge_document`, `brand`, `onboarding_run`/`onboarding_step`, `artifact`.
- **Import guard:** `clue_api/arv2/**` may not import other `clue_api` modules; the read module lives in `clue_api/frontend_read/` and imports `clue_api.arv2.knowledge_frontmatter` (allowed direction) and `clue_api.arv2.onboarding_store.read_current_run`.
- **Money/tests:** never `make check` or a broad pytest (live tests spend); DB tests on the throwaway DB only (`clue_o4_agent`, head `9f81e5692fea`); frontend gate `npm run design-system:build && npm run lint && npm run build` plus `npm test` in `apps/frontend`.
- **Commits:** local only, never push; no AI attribution; one commit per task with the message given.

---

## File Structure

| Path | Responsibility |
|---|---|
| `platform/api/clue_api/frontend_read/brand_knowledge.py` | **Create.** The three reads: `read_knowledge_tree`, `read_knowledge_document`, `read_onboarding_status`, their wire models, `register_brand_knowledge_routes`. Pure SQL + storage read; no provider. |
| `platform/api/clue_api/frontend_read/app.py:214-256` | **Modify.** Register the routes on the scoped router (storage seam = `evidence_storage`). |
| `platform/api/clue_api/frontend_read/__init__.py` | **Modify.** Export the new names. |
| `apps/frontend/docs/api-contracts/brand-context.md` | **Modify.** Append "Resolution (2026-09-08, O5)". |
| `platform/api/clue_api/arv2/README.md` | **Modify.** One "O5" paragraph. |
| `apps/frontend/src/features/brand-context/model/brand-knowledge.ts` | **Create.** Zod schemas for the three wire payloads + `toKnowledgeFolders` mapping onto the dummy shape. |
| `apps/frontend/src/features/brand-context/data/brand-knowledge.repository.ts` | **Create.** `readBrandKnowledgeFolders(clueFetch)` and `readOnboardingStatus(clueFetch)`; never reject. |
| `apps/frontend/src/features/brand-context/data/brand-context.repository.ts` | **Modify.** `httpBrandContextRepository({ designFetch, clueFetch })` merges platform folders + the kit's Design folder. |
| `apps/frontend/src/app/(protected)/brand-context/page.tsx` | **Modify.** Build `clueFetch` on the shared context; pass the onboarding status to the screen; drop the `mode` query. |
| `apps/frontend/src/features/brand-context/components/brand-context-header.tsx`, `knowledge-panel.tsx`, `hooks/use-brand-context-controller.ts`, `model/brand-context.ts` | **Modify.** Remove the Preview/Edit control and the `documentMode` plumbing. |
| `apps/frontend/src/features/brand-context/hooks/use-knowledge-refresh.ts` | **Create.** Poll the status read while a run is live; `router.refresh()` when a step lands. |
| `apps/frontend/src/features/brand-context/components/brand-context-screen.tsx` | **Modify.** Mount the hook; accept `onboarding` prop. |
| Tests | `tests/api/test_frontend_read_brand_knowledge.py` (create); `tests/api/test_frontend_read_app.py` (modify: path inventory); `apps/frontend/src/features/brand-context/data/brand-knowledge.repository.test.ts`, `model/brand-knowledge.test.ts` (create); `brand-context.repository.test.ts`, `model/brand-context.test.ts` (modify). |

---

### Task 1: The backend reads — tree, document, onboarding status

**Files:**
- Create: `platform/api/clue_api/frontend_read/brand_knowledge.py`
- Test: `tests/api/test_frontend_read_brand_knowledge.py`

**Interfaces:**
- Produces (all `async`, first arg `conn: AsyncConnection`):
  - `resolve_knowledge_brand(conn, *, workspace_id: str, brand_id: str | None) -> str | None` — the explicit `brand_id` when it belongs to the workspace (else `None`); otherwise the brand of the workspace's newest `onboarding_run`; otherwise the workspace's only brand; otherwise `None`.
  - `read_knowledge_tree(conn, *, workspace_id, brand_id, storage: StorageBackend | None) -> KnowledgeTreeWire` — folders in the fixed order, each with its servable current documents (`KnowledgeDocumentWire`); with `storage=None` titles fall back to file names and `product_id`/`icp_key` are `None`.
  - `read_knowledge_document(conn, storage: StorageBackend, *, workspace_id, document_id: UUID) -> KnowledgeDocumentDetailWire | None` — `None` when the row is missing, in another workspace, or not servable.
  - `read_onboarding_status(conn, *, workspace_id) -> OnboardingStatusWire` — the O3 shape.
  - `register_brand_knowledge_routes(router: APIRouter, *, conn_factory: ConnFactory, storage: StorageBackend | None) -> None`.
- Wire models (`WireModel` subclasses; camelCase on the wire): `KnowledgeDocumentWire(id: str, path: str, title: str, kind: str, version: int, status: str, updated_at: str, product_id: str | None, icp_key: str | None)`; `KnowledgeFolderWire(key: str, label: str, documents: list[KnowledgeDocumentWire])`; `KnowledgeTreeWire(brand_id: str | None, folders: list[KnowledgeFolderWire])`; `KnowledgeSourceWire(section: str, url: str, title: str | None, confidence: str | None)`; `KnowledgeDocumentDetailWire(id, path, title, kind, version, status, updated_at, product_id, icp_key, markdown: str, front_matter: dict[str, Any], sources: list[KnowledgeSourceWire])`; `OnboardingStepWire(kind, subject_ref, phase, status, started_at, finished_at, cost_usd: str, failure_code)`; `OnboardingStatusWire(run_id: str | None, status: str, steps: list[OnboardingStepWire], cost_usd: str)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_frontend_read_brand_knowledge.py
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


async def _get(conn: AsyncConnection, storage: _MemoryStorage | None, path: str, *, ws: str = _WS) -> httpx.Response:
    async with httpx.AsyncClient(transport=ASGITransport(app=_app(conn, storage)), base_url="http://knowledge") as client:
        return await client.get(f"{_BASE}{path}", headers={"X-Workspace-Id": ws})


async def _document(conn, artifacts, *, ws, brand_id, folder, path, kind, version, status, body, produced_by_step_id=None):
    ref = await artifacts.persist_body(workspace_id=ws, data=body.encode(), media_type="text/markdown")
    document_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, folder, path, kind, "
            " version, status, artifact_key, artifact_sha256, produced_by_step_id) VALUES (:id, :ws, :brand, "
            " :folder, :path, :kind, :version, :status, :key, :sha, :step)"
        ),
        {"id": document_id, "ws": ws, "brand": brand_id, "folder": folder, "path": path, "kind": kind,
         "version": version, "status": status, "key": ref.artifact_key, "sha": ref.sha256, "step": produced_by_step_id},
    )
    return document_id


async def _seed(conn, storage):
    project = await seed_project(conn, _WS, name="O5")
    await seed_principal(conn, workspace_id=_WS, user_id=_USER)
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_session_factory(conn))
    brand = project.brand_id
    ids = {}
    ids["overview_v1"] = await _document(conn, artifacts, ws=_WS, brand_id=brand, folder="company", path="company/overview.md", kind="company-overview", version=1, status="superseded", body=OVERVIEW.replace("Body.", "Old body."))
    ids["overview_v2"] = await _document(conn, artifacts, ws=_WS, brand_id=brand, folder="company", path="company/overview.md", kind="company-overview", version=2, status="ready", body=OVERVIEW)
    ids["catalog_running"] = await _document(conn, artifacts, ws=_WS, brand_id=brand, folder="product", path="product/catalog.md", kind="product-catalog", version=1, status="running", body="---\nkind: product-catalog\n---\n\n# Catalog\n")
    ids["product"] = await _document(conn, artifacts, ws=_WS, brand_id=brand, folder="product", path="product/aura-ai-scribe.md", kind="product-research", version=1, status="ready", body=PRODUCT)
    ids["icp"] = await _document(conn, artifacts, ws=_WS, brand_id=brand, folder="audience", path="audience/icp-gi-groups.md", kind="icp-definition", version=1, status="proposed", body=ICP)
    ids["reviews_empty"] = await _document(conn, artifacts, ws=_WS, brand_id=brand, folder="proof", path="proof/customer-reviews.md", kind="customer-reviews", version=1, status="empty", body="---\nkind: customer-reviews\n---\n\n# Reviews\n")
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
            assert [f["key"] for f in body["folders"]] == ["company", "product", "audience", "proof"]
            assert [f["label"] for f in body["folders"]] == ["Company", "Product", "Audience", "Proof"]
            by_key = {f["key"]: f["documents"] for f in body["folders"]}
            assert [d["path"] for d in by_key["company"]] == ["company/overview.md"]
            assert by_key["company"][0]["version"] == 2 and by_key["company"][0]["status"] == "ready"
            assert by_key["company"][0]["id"] == str(ids["overview_v2"])
            assert by_key["company"][0]["title"] == "Insight Health overview"
            # running catalog and empty reviews are not servable → absent; the product report is
            assert [d["path"] for d in by_key["product"]] == ["product/aura-ai-scribe.md"]
            assert by_key["product"][0]["productId"] == "prd_a"
            assert by_key["audience"][0]["icpKey"] == "gi-groups" and by_key["audience"][0]["status"] == "proposed"
            assert by_key["proof"] == []
            assert set(by_key["company"][0]) == {"id", "path", "title", "kind", "version", "status", "updatedAt", "productId", "icpKey"}

    run_async(scenario())


def test_a_document_serves_markdown_front_matter_and_flattened_sources() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = _MemoryStorage()
            _, ids = await _seed(conn, storage)
            response = await _get(conn, storage, f"/knowledge/documents/{ids['overview_v2']}")
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["id"] == str(ids["overview_v2"]) and body["title"] == "Insight Health overview"
            assert body["markdown"].startswith("# Insight Health overview")
            assert body["frontMatter"]["kind"] == "company-overview"
            assert body["sources"] == [
                {"section": "facts.legal_name", "url": "https://www.insighthealth.ai/", "title": "Insight Health", "confidence": "high"}
            ]
            # non-servable, other-workspace, unknown → 404 with the envelope code
            for missing in (ids["catalog_running"], ids["reviews_empty"], uuid.uuid4()):
                refused = await _get(conn, storage, f"/knowledge/documents/{missing}")
                assert refused.status_code == 404, refused.text
                assert refused.json()["error"]["code"] == "KNOWLEDGE_DOCUMENT_NOT_FOUND"
            foreign = await _get(conn, storage, f"/knowledge/documents/{ids['overview_v2']}", ws="ws-someone-else")
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
            assert detail.status_code == 503 and detail.json()["error"]["code"] == "KNOWLEDGE_STORAGE_UNAVAILABLE"

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
            await create_run(conn, run_id=run_id, workspace_id=_WS, brand_id=brand_b, company_domain="x.io", requested_by_user_id=_USER)
            assert (await _get(conn, storage, "/knowledge")).json()["brandId"] == brand_b
            # explicit brand wins; a foreign brand id is refused as none
            assert (await _get(conn, storage, f"/knowledge?brandId={brand_a}")).json()["brandId"] == brand_a
            assert (await _get(conn, storage, "/knowledge?brandId=brd_not_mine")).json()["brandId"] is None

    run_async(scenario())


def test_onboarding_current_mirrors_the_run_and_its_steps() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = _MemoryStorage()
            brand, _ = await _seed(conn, storage)
            nothing = (await _get(conn, storage, "/onboarding/current")).json()
            assert nothing == {"runId": None, "status": "none", "steps": [], "costUsd": "0"}
            run_id = uuid.uuid4()
            await create_run(conn, run_id=run_id, workspace_id=_WS, brand_id=brand, company_domain="insighthealth.ai", requested_by_user_id=_USER)
            await mark_run_running(conn, run_id=run_id)
            step = uuid.uuid4()
            await start_step(conn, step_id=step, run_id=run_id, workspace_id=_WS, kind="overview", phase="fast")
            await finish_step(conn, step_id=step, status="completed", cost_usd=Decimal("0.5"))
            body = (await _get(conn, storage, "/onboarding/current")).json()
            assert body["runId"] == str(run_id) and body["status"] == "running" and body["costUsd"] == "0.500000"
            (only,) = body["steps"]
            assert (only["kind"], only["status"], only["failureCode"], only["costUsd"]) == ("overview", "completed", None, "0.500000")
            assert only["startedAt"].endswith("Z") and only["finishedAt"].endswith("Z")

    run_async(scenario())
```

`_MemoryStorage` lives in `tests/api/test_stage0_setup_db.py:67` (the same in-memory `StorageBackend` the O3/O4 DB tests use). `costUsd` strings: `str(Decimal)` of a `numeric(12,6)` column renders six decimals — assert exactly what the store returns (adjust the literal to the observed rendering if it differs, and say so in the report).

- [ ] **Step 2: Run to verify failure**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="$(echo "$CLUE_DATABASE_URL" | sed -E 's#/[^/]+$#/clue_o4_agent#')"; uv run pytest tests/api/test_frontend_read_brand_knowledge.py -v`
Expected: FAIL — 404s (routes absent) / `ModuleNotFoundError` once the module import is added.

- [ ] **Step 3: Write the module**

```python
# platform/api/clue_api/frontend_read/brand_knowledge.py
"""The brand-context Knowledge reads (ARV2-ONBOARDING-PLAN.md §7; O5).

Three workspace-scoped, read-only endpoints on the ``/frontend/v1`` router: the folder tree of the
brand's *servable* knowledge documents (``ready`` / ``proposed`` / ``confirmed``, highest such
version per path — founder ruling 2026-09-08: no status chip, so nothing else is listed), one
document with its markdown, front matter and flattened sources, and the onboarding run's status
(the O3 read, mirrored here so the page has one surface). Folder order and labels are the
dummy's. The ``design`` folder is the brand kit's and is never served here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.arv2.onboarding_store import read_current_run
from clue_api.frontend_read.accounts_list import WireModel
from clue_db import ConnFactory
from clue_storage import StorageBackend, read_verified_artifact

__all__ = [
    "KnowledgeDocumentDetailWire",
    "KnowledgeDocumentWire",
    "KnowledgeFolderWire",
    "KnowledgeSourceWire",
    "KnowledgeTreeWire",
    "OnboardingStatusWire",
    "OnboardingStepWire",
    "SERVABLE_STATUSES",
    "read_knowledge_document",
    "read_knowledge_tree",
    "read_onboarding_status",
    "register_brand_knowledge_routes",
    "resolve_knowledge_brand",
]

SERVABLE_STATUSES: tuple[str, ...] = ("ready", "proposed", "confirmed")
#: The dummy's folder order and labels (`brand-context.fixture.ts`); ``design`` is the kit's.
FOLDERS: tuple[tuple[str, str], ...] = (
    ("company", "Company"),
    ("product", "Product"),
    ("audience", "Audience"),
    ("proof", "Proof"),
)


class KnowledgeDocumentWire(WireModel):
    id: str
    path: str
    title: str
    kind: str
    version: int
    status: str
    updated_at: str
    product_id: str | None
    icp_key: str | None


class KnowledgeFolderWire(WireModel):
    key: str
    label: str
    documents: list[KnowledgeDocumentWire]


class KnowledgeTreeWire(WireModel):
    brand_id: str | None
    folders: list[KnowledgeFolderWire]


class KnowledgeSourceWire(WireModel):
    section: str
    url: str
    title: str | None
    confidence: str | None


class KnowledgeDocumentDetailWire(WireModel):
    id: str
    path: str
    title: str
    kind: str
    version: int
    status: str
    updated_at: str
    product_id: str | None
    icp_key: str | None
    markdown: str
    front_matter: dict[str, Any]
    sources: list[KnowledgeSourceWire]


class OnboardingStepWire(WireModel):
    kind: str
    subject_ref: str | None
    phase: str
    status: str
    started_at: str | None
    finished_at: str | None
    cost_usd: str
    failure_code: str | None


class OnboardingStatusWire(WireModel):
    run_id: str | None
    status: str
    steps: list[OnboardingStepWire]
    cost_usd: str


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _title(path: str, body: str) -> str:
    """The first ``# `` heading of the body, else the file name without ``.md``."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    name = path.rsplit("/", 1)[-1]
    return name[:-3] if name.endswith(".md") else name


def _optional_str(front: Mapping[str, Any], key: str) -> str | None:
    value = front.get(key)
    return value if isinstance(value, str) and value else None


def _sources(front: Mapping[str, Any]) -> list[KnowledgeSourceWire]:
    """Flatten the mappers' ``sources`` map (field → {citations[], confidence}) — O2's shape."""
    raw = front.get("sources")
    if not isinstance(raw, dict):
        return []
    out: list[KnowledgeSourceWire] = []
    for section in sorted(raw):
        entry = raw[section]
        if not isinstance(entry, dict):
            continue
        confidence = entry.get("confidence")
        for citation in entry.get("citations") or []:
            if isinstance(citation, dict) and isinstance(citation.get("url"), str):
                out.append(
                    KnowledgeSourceWire(
                        section=str(section),
                        url=citation["url"],
                        title=citation.get("title") if isinstance(citation.get("title"), str) else None,
                        confidence=confidence if isinstance(confidence, str) else None,
                    )
                )
    return out


async def resolve_knowledge_brand(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str | None
) -> str | None:
    if brand_id is not None:
        owned = (
            await conn.execute(
                text("SELECT brand_id FROM brand WHERE workspace_id = :ws AND brand_id = :brand"),
                {"ws": workspace_id, "brand": brand_id},
            )
        ).scalar_one_or_none()
        return str(owned) if owned is not None else None
    newest_run = (
        await conn.execute(
            text(
                "SELECT brand_id FROM onboarding_run WHERE workspace_id = :ws "
                "ORDER BY requested_at DESC LIMIT 1"
            ),
            {"ws": workspace_id},
        )
    ).scalar_one_or_none()
    if newest_run is not None:
        return str(newest_run)
    brands = (
        await conn.execute(
            text("SELECT brand_id FROM brand WHERE workspace_id = :ws ORDER BY created_at, brand_id"),
            {"ws": workspace_id},
        )
    ).scalars().all()
    return str(brands[0]) if len(brands) == 1 else None


_CURRENT_SERVABLE_SQL = text(
    "SELECT d.document_id, d.folder, d.path, d.kind, d.version, d.status, d.updated_at, "
    " d.artifact_key, d.artifact_sha256 "
    "FROM brand_knowledge_document d "
    "WHERE d.workspace_id = :ws AND d.brand_id = :brand AND d.folder IN :folders "
    " AND d.status IN :servable "
    " AND d.version = (SELECT MAX(d2.version) FROM brand_knowledge_document d2 "
    "   WHERE d2.workspace_id = d.workspace_id AND d2.brand_id = d.brand_id "
    "     AND d2.path = d.path AND d2.status IN :servable) "
    "ORDER BY d.folder, d.path"
).bindparams(bindparam("folders", expanding=True), bindparam("servable", expanding=True))


async def _current_servable(conn: AsyncConnection, *, workspace_id: str, brand_id: str) -> list[Mapping[str, Any]]:
    rows = await conn.execute(
        _CURRENT_SERVABLE_SQL,
        {"ws": workspace_id, "brand": brand_id, "folders": [key for key, _ in FOLDERS], "servable": list(SERVABLE_STATUSES)},
    )
    return list(rows.mappings().all())


async def _front_and_body(conn: AsyncConnection, storage: StorageBackend, *, workspace_id: str, row: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    _, raw = await read_verified_artifact(conn, storage, storage_key=str(row["artifact_key"]), workspace_id=workspace_id)
    try:
        return parse_front_matter(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}, raw.decode("utf-8", errors="replace")
```

Continue the module — the tree reads each current document's artifact for its title, product id and ICP key (sequentially; a tree is at most a few dozen documents), and falls back to the file-name title with `None` ids when the process has no storage:


```python
async def read_knowledge_tree(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str | None, storage: StorageBackend | None
) -> KnowledgeTreeWire:
    documents: dict[str, list[KnowledgeDocumentWire]] = {key: [] for key, _ in FOLDERS}
    if brand_id is not None:
        for row in await _current_servable(conn, workspace_id=workspace_id, brand_id=brand_id):
            front: dict[str, Any] = {}
            body = ""
            if storage is not None:
                try:
                    front, body = await _front_and_body(conn, storage, workspace_id=workspace_id, row=row)
                except Exception:  # noqa: BLE001 — a missing blob lists the document by name, never 500s the tree
                    front, body = {}, ""
            documents[str(row["folder"])].append(_document_wire(row, front=front, body=body))
    return KnowledgeTreeWire(
        brand_id=brand_id,
        folders=[KnowledgeFolderWire(key=key, label=label, documents=documents[key]) for key, label in FOLDERS],
    )


def _document_wire(row: Mapping[str, Any], *, front: Mapping[str, Any], body: str) -> KnowledgeDocumentWire:
    return KnowledgeDocumentWire(
        id=str(row["document_id"]),
        path=str(row["path"]),
        title=_title(str(row["path"]), body),
        kind=str(row["kind"]),
        version=int(row["version"]),
        status=str(row["status"]),
        updated_at=_iso(row["updated_at"]) or "",
        product_id=_optional_str(front, "product_id"),
        icp_key=_optional_str(front, "icp_key"),
    )


async def read_knowledge_document(
    conn: AsyncConnection, storage: StorageBackend, *, workspace_id: str, document_id: UUID
) -> KnowledgeDocumentDetailWire | None:
    row = (
        await conn.execute(
            text(
                "SELECT document_id, folder, path, kind, version, status, updated_at, artifact_key, "
                " artifact_sha256 FROM brand_knowledge_document "
                "WHERE workspace_id = :ws AND document_id = :id AND status IN :servable "
                " AND folder IN :folders"
            ).bindparams(bindparam("servable", expanding=True), bindparam("folders", expanding=True)),
            {"ws": workspace_id, "id": document_id, "servable": list(SERVABLE_STATUSES), "folders": [key for key, _ in FOLDERS]},
        )
    ).mappings().first()
    if row is None:
        return None
    front, body = await _front_and_body(conn, storage, workspace_id=workspace_id, row=row)
    base = _document_wire(row, front=front, body=body)
    return KnowledgeDocumentDetailWire(
        **base.model_dump(),
        markdown=body,
        front_matter=dict(front),
        sources=_sources(front),
    )


async def read_onboarding_status(conn: AsyncConnection, *, workspace_id: str) -> OnboardingStatusWire:
    status = await read_current_run(conn, workspace_id=workspace_id)
    if status is None:
        return OnboardingStatusWire(run_id=None, status="none", steps=[], cost_usd="0")
    return OnboardingStatusWire(
        run_id=str(status.run_id),
        status=status.status,
        steps=[
            OnboardingStepWire(
                kind=step.kind, subject_ref=step.subject_ref, phase=step.phase, status=step.status,
                started_at=_iso(step.started_at), finished_at=_iso(step.finished_at),
                cost_usd=str(step.cost_usd), failure_code=step.failure_code,
            )
            for step in status.steps
        ],
        cost_usd=str(status.cost_usd),
    )


def register_brand_knowledge_routes(
    router: APIRouter, *, conn_factory: ConnFactory, storage: StorageBackend | None
) -> None:
    # Imported here: ``app`` imports this module, and ``WorkspaceDep`` lives in ``app``.
    from clue_api.frontend_read.app import WorkspaceDep

    @router.get("/brand-context/knowledge", response_model=KnowledgeTreeWire)
    async def get_knowledge_tree(
        workspace_id: WorkspaceDep,
        brand_id: str | None = Query(default=None, alias="brandId"),
    ) -> KnowledgeTreeWire:
        async with conn_factory() as conn:
            resolved = await resolve_knowledge_brand(conn, workspace_id=workspace_id, brand_id=brand_id)
            return await read_knowledge_tree(conn, workspace_id=workspace_id, brand_id=resolved, storage=storage)

    @router.get("/brand-context/knowledge/documents/{document_id}", response_model=KnowledgeDocumentDetailWire)
    async def get_knowledge_document(workspace_id: WorkspaceDep, document_id: UUID) -> KnowledgeDocumentDetailWire:
        if storage is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "KNOWLEDGE_STORAGE_UNAVAILABLE", "message": "this process has no artifact storage configured"},
            )
        async with conn_factory() as conn:
            document = await read_knowledge_document(conn, storage, workspace_id=workspace_id, document_id=document_id)
        if document is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "KNOWLEDGE_DOCUMENT_NOT_FOUND", "message": "no servable knowledge document with this id in this workspace"},
            )
        return document

    @router.get("/brand-context/onboarding/current", response_model=OnboardingStatusWire)
    async def get_onboarding_current(workspace_id: WorkspaceDep) -> OnboardingStatusWire:
        async with conn_factory() as conn:
            return await read_onboarding_status(conn, workspace_id=workspace_id)
```

Read `frontend_read/account_detail.py:690-720` for how the router's error envelope expects `HTTPException(detail={"code": ..., "message": ...})` to be shaped (the test asserts `response.json()["error"]["code"]`); match that exactly. 

- [ ] **Step 4: Register on the scoped router (temporarily, to run the tests — Task 2 finalizes)**

In `platform/api/clue_api/frontend_read/app.py::build_frontend_read_router`, after `register_contact_routes(...)`:

```python
    from clue_api.frontend_read.brand_knowledge import register_brand_knowledge_routes

    register_brand_knowledge_routes(router, conn_factory=conn_factory, storage=evidence_storage)
```

(add the import beside the other lazy imports at the top of the function).

- [ ] **Step 5: Run, ruff, mypy**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="$(echo "$CLUE_DATABASE_URL" | sed -E 's#/[^/]+$#/clue_o4_agent#')"; uv run pytest tests/api/test_frontend_read_brand_knowledge.py -v && uv run ruff check platform/api/clue_api/frontend_read tests/api/test_frontend_read_brand_knowledge.py && uv run ruff format --check platform/api/clue_api/frontend_read tests/api/test_frontend_read_brand_knowledge.py && uv run mypy platform/api/clue_api/frontend_read/brand_knowledge.py`
Expected: 5 passed; clean.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/frontend_read/brand_knowledge.py platform/api/clue_api/frontend_read/app.py tests/api/test_frontend_read_brand_knowledge.py
git commit -m "feat(frontend-read): brand-context Knowledge reads — servable document tree, one document with markdown/front matter/sources, onboarding status; on /frontend/v1 behind the read flag"
```

---

### Task 2: Router inventory, exports, contract doc, README

**Files:**
- Modify: `platform/api/clue_api/frontend_read/__init__.py`
- Modify: `tests/api/test_frontend_read_app.py` (the path inventory test)
- Modify: `apps/frontend/docs/api-contracts/brand-context.md` (append)
- Modify: `platform/api/clue_api/arv2/README.md` (append)

- [ ] **Step 1: Extend the path inventory test**

`tests/api/test_frontend_read_app.py` has a test that enumerates the scoped router's `(method, path)` pairs when the flag is on (find it via `_scoped_paths`). Add the three new pairs to its expected set:

```python
        ("GET", "/frontend/v1/brand-context/knowledge"),
        ("GET", "/frontend/v1/brand-context/knowledge/documents/{document_id}"),
        ("GET", "/frontend/v1/brand-context/onboarding/current"),
```

and assert they are absent when the flag is off (the existing off-flag assertion covers it if it asserts an empty set — read the test).

- [ ] **Step 2: Export**

In `platform/api/clue_api/frontend_read/__init__.py` add, in the import block's alphabetical place:

```python
from clue_api.frontend_read.brand_knowledge import (
    KnowledgeDocumentDetailWire,
    KnowledgeTreeWire,
    OnboardingStatusWire,
    read_knowledge_document,
    read_knowledge_tree,
    read_onboarding_status,
    resolve_knowledge_brand,
)
```

and the seven names to `__all__`.

- [ ] **Step 3: Contract doc resolution**

Append to `apps/frontend/docs/api-contracts/brand-context.md`:

```markdown
## Resolution (2026-09-08, ARV2 O5) — the Knowledge folders serve the onboarding documents

This supersedes "Still future work" above for the Company, Product, Audience and Proof
folders. They are served from the platform's `brand_knowledge_document` store — the artifacts the
ARV2 onboarding run (`POST /onboarding`, O3) and the synthesis agent (O4) publish. Design keeps
riding the brand-kit read. Memories stays absent.

### Endpoints (platform API, `/frontend/v1`, `X-Workspace-Id` via the BFF / server seam)

`ARV2-ONBOARDING-PLAN.md` §7 wrote these under `/api/v1/brand-context/...`; they live on the
existing flag-gated read surface instead (same auth, tenant scoping, envelope and CORS as the
accounts screens):

| Read | Endpoint | Purpose |
| --- | --- | --- |
| Tree | `GET /frontend/v1/brand-context/knowledge[?brandId=]` | `{ brandId, folders: [{ key, label, documents: [{ id, path, title, kind, version, status, updatedAt, productId, icpKey }] }] }` |
| Document | `GET /frontend/v1/brand-context/knowledge/documents/{id}` | `{ …tree fields, markdown, frontMatter, sources: [{ section, url, title, confidence }] }` — 404 `KNOWLEDGE_DOCUMENT_NOT_FOUND`; 503 `KNOWLEDGE_STORAGE_UNAVAILABLE` |
| Onboarding status | `GET /frontend/v1/brand-context/onboarding/current` | `{ runId, status, steps: [{ kind, subjectRef, phase, status, startedAt, finishedAt, costUsd, failureCode }], costUsd }`; `status: "none"` when no run |

- **Which brand:** `brandId` when given and owned by the workspace; else the brand of the
  workspace's newest onboarding run; else the workspace's only brand; else an empty tree.
- **Servable only (founder ruling 2026-09-08):** `ready`, `proposed`, `confirmed`, highest such
  version per path. Running, empty, failed and superseded versions are not listed. The dummy has
  no status chip, so none is rendered; `status` rides the wire for a future slot.
- **Progressive fill:** the page polls the onboarding status while a run is `queued`/`running`
  and re-reads the tree when a step lands. No progress UI.

### What the page does with it

- Folders map onto the lifted `BrandKnowledgeFolderSchema` in the dummy's order — Company,
  Product, Audience, Proof, then Design (kit). `updatedLabel` is derived from `updatedAt` and
  not rendered. `title` is the document name.
- Bodies are read per document (parallel), like the asset registry reads.
- **Edit is gone (founder ruling 2026-09-08):** the Preview/Edit control is removed from the
  page for every document, Design.md included; the `mode` query parameter is ignored.
- Configured and refused → the four folders are honest empties; the fixture never serves a
  configured deployment.

The proposed mutation endpoints remain proposals.
```

- [ ] **Step 4: README paragraph**

Append to `platform/api/clue_api/arv2/README.md`, after the O4 section:

```markdown
## O5 — the Knowledge read surface

`clue_api/frontend_read/brand_knowledge.py` serves the onboarding documents to the brand-context
page: the servable tree, one document (verified artifact read → front matter + markdown + flattened
sources), and the onboarding status, on `/frontend/v1/brand-context/...`. Only `ready`/`proposed`/
`confirmed` versions are listed (no status chip — founder ruling 2026-09-08); the `design` folder
is the brand kit's. The store's `list_documents` stays status-blind for the page's own reasons; this
read filters.
```

- [ ] **Step 5: Run and commit**

Run: `set -a; source .env; set +a; export CLUE_DATABASE_URL="$(echo "$CLUE_DATABASE_URL" | sed -E 's#/[^/]+$#/clue_o4_agent#')"; uv run pytest tests/api/test_frontend_read_app.py tests/api/test_frontend_read_brand_knowledge.py -q && uv run ruff check platform/api/clue_api/frontend_read`

```bash
git add platform/api/clue_api/frontend_read/__init__.py tests/api/test_frontend_read_app.py apps/frontend/docs/api-contracts/brand-context.md platform/api/clue_api/arv2/README.md
git commit -m "docs(contracts): brand-context Knowledge folders serve the onboarding documents on /frontend/v1 (O5 resolution); export the reads; README"
```

---

### Task 3: Frontend wire model and the knowledge repository

**Files:**
- Create: `apps/frontend/src/features/brand-context/model/brand-knowledge.ts`
- Create: `apps/frontend/src/features/brand-context/data/brand-knowledge.repository.ts`
- Test: `apps/frontend/src/features/brand-context/model/brand-knowledge.test.ts`, `apps/frontend/src/features/brand-context/data/brand-knowledge.repository.test.ts`

**Interfaces:**
- Produces: `KnowledgeTreeSchema`, `KnowledgeDocumentDetailSchema`, `OnboardingStatusSchema` (Zod, camelCase per the wire); `toKnowledgeFolders(tree, bodies: Map<string, string>): BrandKnowledgeFolder[]` (pure; dummy shape; folders in wire order, empty folders kept); `readBrandKnowledgeFolders(clueFetch: typeof fetch): Promise<BrandKnowledgeFolder[]>` (tree + one body read per document in parallel; a failed body read lists the document with an empty body; any tree failure → `[]`; never rejects); `readOnboardingStatus(clueFetch): Promise<OnboardingStatus | null>` (never rejects).
- `updatedLabel`: `Updated <dateLabel(updatedAt)>` using the existing `dateLabel` helper in `model/brand-context-mapping.ts` (export it if it is module-private).

- [ ] **Step 1: Write the failing tests**

```ts
// apps/frontend/src/features/brand-context/model/brand-knowledge.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { KnowledgeTreeSchema, toKnowledgeFolders } from "./brand-knowledge";

const tree = KnowledgeTreeSchema.parse({
  brandId: "brd_1",
  folders: [
    { key: "company", label: "Company", documents: [
      { id: "doc-1", path: "company/overview.md", title: "Insight Health overview", kind: "company-overview", version: 2, status: "ready", updatedAt: "2026-09-08T03:55:00Z", productId: null, icpKey: null },
    ] },
    { key: "product", label: "Product", documents: [] },
    { key: "audience", label: "Audience", documents: [
      { id: "doc-2", path: "audience/icp-gi-groups.md", title: "GI groups", kind: "icp-definition", version: 1, status: "proposed", updatedAt: "2026-09-08T03:55:00Z", productId: null, icpKey: "gi-groups" },
    ] },
    { key: "proof", label: "Proof", documents: [] },
  ],
});

test("folders map onto the dummy shape in wire order, keeping empty folders", () => {
  const folders = toKnowledgeFolders(tree, new Map([["doc-1", "# Insight Health overview\n\nBody."]]));
  assert.deepEqual(folders.map((f) => [f.id, f.label, f.documents.length]), [
    ["company", "Company", 1], ["product", "Product", 0], ["audience", "Audience", 1], ["proof", "Proof", 0],
  ]);
  const [overview] = folders[0].documents;
  assert.equal(overview.id, "doc-1");
  assert.equal(overview.folderId, "company");
  assert.equal(overview.name, "Insight Health overview");
  assert.equal(overview.path, "company/overview.md");
  assert.equal(overview.body, "# Insight Health overview\n\nBody.");
  assert.match(overview.updatedLabel, /^Updated /);
  // a document whose body was not read still lists, with an empty body
  assert.equal(folders[2].documents[0].body, "");
});

test("the tree schema refuses an unknown folder key and tolerates additive document keys", () => {
  assert.throws(() => KnowledgeTreeSchema.parse({ brandId: null, folders: [{ key: "memories", label: "M", documents: [] }] }));
  const parsed = KnowledgeTreeSchema.parse({ brandId: null, folders: [{ key: "proof", label: "Proof", documents: [{ id: "x", path: "proof/a.md", title: "A", kind: "customer-reviews", version: 1, status: "ready", updatedAt: "2026-09-08T00:00:00Z", productId: null, icpKey: null, extra: 1 }] }] });
  assert.equal(parsed.folders[0].documents[0].id, "x");
});
```

```ts
// apps/frontend/src/features/brand-context/data/brand-knowledge.repository.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { readBrandKnowledgeFolders, readOnboardingStatus } from "./brand-knowledge.repository";

function fetchOf(routes: Record<string, unknown | Error>): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const path = String(input);
    const hit = Object.entries(routes).find(([key]) => path.endsWith(key));
    if (!hit) return new Response("nope", { status: 404 });
    if (hit[1] instanceof Error) throw hit[1];
    return new Response(JSON.stringify(hit[1]), { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
}

const TREE = {
  brandId: "brd_1",
  folders: [
    { key: "company", label: "Company", documents: [{ id: "doc-1", path: "company/overview.md", title: "Overview", kind: "company-overview", version: 1, status: "ready", updatedAt: "2026-09-08T00:00:00Z", productId: null, icpKey: null }] },
    { key: "product", label: "Product", documents: [{ id: "doc-2", path: "product/aura.md", title: "Aura", kind: "product-research", version: 1, status: "ready", updatedAt: "2026-09-08T00:00:00Z", productId: "prd_a", icpKey: null }] },
    { key: "audience", label: "Audience", documents: [] },
    { key: "proof", label: "Proof", documents: [] },
  ],
};

test("reads the tree, then every body in parallel, and maps to folders", async () => {
  const fetch = fetchOf({
    "/frontend/v1/brand-context/knowledge": TREE,
    "/knowledge/documents/doc-1": { id: "doc-1", path: "company/overview.md", title: "Overview", kind: "company-overview", version: 1, status: "ready", updatedAt: "2026-09-08T00:00:00Z", productId: null, icpKey: null, markdown: "# Overview\n", frontMatter: {}, sources: [] },
    "/knowledge/documents/doc-2": new Error("boom"),
  });
  const folders = await readBrandKnowledgeFolders(fetch);
  assert.equal(folders[0].documents[0].body, "# Overview\n");
  assert.equal(folders[1].documents[0].body, "");
  assert.equal(folders[1].documents[0].name, "Aura");
});

test("a refused tree yields no folders and never rejects", async () => {
  assert.deepEqual(await readBrandKnowledgeFolders(fetchOf({})), []);
  assert.deepEqual(await readBrandKnowledgeFolders(fetchOf({ "/frontend/v1/brand-context/knowledge": new Error("down") })), []);
});

test("the onboarding status parses and a refusal is null", async () => {
  const status = await readOnboardingStatus(fetchOf({ "/brand-context/onboarding/current": { runId: "r", status: "running", steps: [{ kind: "overview", subjectRef: null, phase: "fast", status: "completed", startedAt: "2026-09-08T00:00:00Z", finishedAt: "2026-09-08T00:01:00Z", costUsd: "0.5", failureCode: null }], costUsd: "0.5" } }));
  assert.equal(status?.status, "running");
  assert.equal(await readOnboardingStatus(fetchOf({})), null);
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `apps/frontend`): `npx tsx --test src/features/brand-context/model/brand-knowledge.test.ts src/features/brand-context/data/brand-knowledge.repository.test.ts`
Expected: FAIL — cannot resolve `./brand-knowledge`.

- [ ] **Step 3: Write the model**

```ts
// apps/frontend/src/features/brand-context/model/brand-knowledge.ts
import { z } from "zod";

import type { BrandKnowledgeFolder } from "./brand-context";
import { dateLabel } from "./brand-context-mapping";

/** The four platform-served folders, in the dummy's order. Design is the brand kit's. */
export const KnowledgeFolderKeySchema = z.enum(["company", "product", "audience", "proof"]);

export const KnowledgeDocumentSchema = z
  .object({
    icpKey: z.string().nullable(),
    id: z.string(),
    kind: z.string(),
    path: z.string(),
    productId: z.string().nullable(),
    status: z.string(),
    title: z.string(),
    updatedAt: z.string(),
    version: z.number().int(),
  })
  .passthrough();

export const KnowledgeTreeSchema = z.object({
  brandId: z.string().nullable(),
  folders: z.array(
    z.object({
      documents: z.array(KnowledgeDocumentSchema),
      key: KnowledgeFolderKeySchema,
      label: z.string(),
    }),
  ),
});

export const KnowledgeSourceSchema = z.object({
  confidence: z.string().nullable(),
  section: z.string(),
  title: z.string().nullable(),
  url: z.string(),
});

export const KnowledgeDocumentDetailSchema = KnowledgeDocumentSchema.extend({
  frontMatter: z.record(z.string(), z.unknown()),
  markdown: z.string(),
  sources: z.array(KnowledgeSourceSchema),
});

export const OnboardingStepSchema = z.object({
  costUsd: z.string(),
  failureCode: z.string().nullable(),
  finishedAt: z.string().nullable(),
  kind: z.string(),
  phase: z.string(),
  startedAt: z.string().nullable(),
  status: z.string(),
  subjectRef: z.string().nullable(),
});

export const OnboardingStatusSchema = z.object({
  costUsd: z.string(),
  runId: z.string().nullable(),
  status: z.string(),
  steps: z.array(OnboardingStepSchema),
});

export type KnowledgeTree = z.infer<typeof KnowledgeTreeSchema>;
export type KnowledgeDocumentDetail = z.infer<typeof KnowledgeDocumentDetailSchema>;
export type OnboardingStatus = z.infer<typeof OnboardingStatusSchema>;

/** A run that can still publish documents. */
export function onboardingRunIsLive(status: OnboardingStatus | null): boolean {
  return status?.status === "queued" || status?.status === "running";
}

/**
 * Map the platform tree onto the dummy's Knowledge shape. `bodies` holds the markdown per
 * document id; a document whose body was not read lists with an empty body (the page then
 * shows an empty preview, never an error surface it does not have).
 */
export function toKnowledgeFolders(tree: KnowledgeTree, bodies: Map<string, string>): BrandKnowledgeFolder[] {
  return tree.folders.map((folder) => ({
    documents: folder.documents.map((document) => ({
      body: bodies.get(document.id) ?? "",
      folderId: folder.key,
      id: document.id,
      name: document.title,
      path: document.path,
      updatedLabel: `Updated ${dateLabel(document.updatedAt)}`,
    })),
    id: folder.key,
    label: folder.label,
  }));
}
```

If `dateLabel` is module-private in `brand-context-mapping.ts`, export it (no behaviour change).

- [ ] **Step 4: Write the repository**

```ts
// apps/frontend/src/features/brand-context/data/brand-knowledge.repository.ts
import type { BrandKnowledgeFolder } from "../model/brand-context";
import {
  KnowledgeDocumentDetailSchema,
  KnowledgeTreeSchema,
  OnboardingStatusSchema,
  toKnowledgeFolders,
  type OnboardingStatus,
} from "../model/brand-knowledge";

const READ_PREFIX = "/frontend/v1/brand-context";

async function readJson(clueFetch: typeof fetch, path: string): Promise<unknown> {
  const response = await clueFetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`platform API ${path} responded ${response.status}`);
  return response.json();
}

/**
 * The Knowledge folders the platform serves (Company, Product, Audience, Proof). The tree is
 * one read; each document's body is one more, issued in parallel like the asset-registry reads.
 * A refused body lists the document with an empty body; a refused tree yields no folders.
 * Never rejects — the page is a review surface, and a 500 would be a lie about the brand.
 */
export async function readBrandKnowledgeFolders(clueFetch: typeof fetch): Promise<BrandKnowledgeFolder[]> {
  let tree;
  try {
    tree = KnowledgeTreeSchema.parse(await readJson(clueFetch, `${READ_PREFIX}/knowledge`));
  } catch (error) {
    console.warn("[brand-context] knowledge folders unavailable; serving none:", error);
    return [];
  }
  const bodies = new Map<string, string>();
  await Promise.all(
    tree.folders.flatMap((folder) => folder.documents).map(async (document) => {
      try {
        const detail = KnowledgeDocumentDetailSchema.parse(
          await readJson(clueFetch, `${READ_PREFIX}/knowledge/documents/${encodeURIComponent(document.id)}`),
        );
        bodies.set(document.id, detail.markdown);
      } catch {
        // Listed by name, body empty — honest, and the tree is unaffected.
      }
    }),
  );
  return toKnowledgeFolders(tree, bodies);
}

/** The onboarding run's status, or `null` when the read is refused or there is no surface. */
export async function readOnboardingStatus(clueFetch: typeof fetch): Promise<OnboardingStatus | null> {
  try {
    return OnboardingStatusSchema.parse(await readJson(clueFetch, `${READ_PREFIX}/onboarding/current`));
  } catch {
    return null;
  }
}
```

- [ ] **Step 5: Run, lint, commit**

Run (from `apps/frontend`): `npx tsx --test src/features/brand-context/model/brand-knowledge.test.ts src/features/brand-context/data/brand-knowledge.repository.test.ts && npx eslint src/features/brand-context`

```bash
git add apps/frontend/src/features/brand-context/model/brand-knowledge.ts apps/frontend/src/features/brand-context/model/brand-knowledge.test.ts apps/frontend/src/features/brand-context/data/brand-knowledge.repository.ts apps/frontend/src/features/brand-context/data/brand-knowledge.repository.test.ts apps/frontend/src/features/brand-context/model/brand-context-mapping.ts
git commit -m "feat(frontend): brand-context knowledge wire model and repository — platform folders mapped onto the dummy shape, bodies read in parallel, never rejects"
```

---

### Task 4: Merge the platform folders into the page read; remove the edit control

**Files:**
- Modify: `apps/frontend/src/features/brand-context/data/brand-context.repository.ts`
- Modify: `apps/frontend/src/app/(protected)/brand-context/page.tsx`
- Modify: `apps/frontend/src/features/brand-context/components/brand-context-header.tsx:86-96`, `components/knowledge-panel.tsx`, `hooks/use-brand-context-controller.ts` (`documentMode` plumbing), `model/brand-context.ts` (`BrandDocumentModeSchema`, `BrandContextInitialState.documentMode`)
- Test: `apps/frontend/src/features/brand-context/data/brand-context.repository.test.ts` (extend), `model/brand-context.test.ts` and any test that references `documentMode` (adjust)

**Interfaces:**
- `httpBrandContextRepository({ designFetch, clueFetch })` — `clueFetch: () => Promise<typeof fetch> | typeof fetch`, the Clue-backend sibling of `designFetch` (server side: `fetchAuthenticatedClueBackend(path, init, context)` on the page's shared `authenticatedBackendContext()`). `getBrandContextRepository(designFetch, clueFetch)` and `getBrandContextWorkspace(designFetch, clueFetch)` gain the second argument. Folder order in the merged workspace: platform folders (Company, Product, Audience, Proof) then the kit's Design folder.
- The page keeps the fixture path when `CLUE_API_BASE_URL` is unset (unchanged).

- [ ] **Step 1: Extend the repository test**

Read `brand-context.repository.test.ts` to see how it builds a `designFetch` double and asserts `getWorkspace()`. Add one test: with a kit that has a brief AND a `clueFetch` double serving the Task 3 `TREE` (two documents) plus their detail reads, `getWorkspace()` returns `knowledgeFolders` whose ids are `["company", "product", "audience", "proof", "design"]` in that order, and whose Design document is the brief render as before. Add a second: a `clueFetch` that throws leaves the four platform folders out entirely (Design still present) — the honest empties.

- [ ] **Step 2: Merge in the repository**

In `httpBrandContextRepository`, accept `clueFetch` beside `designFetch`; in `readWorkspace(designFetch, clueFetch)` after the kit read (or when there is no kit — the platform folders do not need a kit):

```ts
  const platformFolders = await readBrandKnowledgeFolders(await clueFetch());
  const workspace = selected ? toBrandContextWorkspace(kit, { assetRecords }) : emptyBrandContextWorkspace();
  return {
    kit: selected ? toBrandKitMeta(kit) : null,
    workspace: BrandContextWorkspaceSchema.parse({
      ...workspace,
      knowledgeFolders: [...platformFolders, ...workspace.knowledgeFolders],
    }),
  };
```

Restructure `readWorkspace` so the "no kit" early return still reads the platform folders (the onboarding documents exist before any kit is ingested). Keep the outer `try/catch` that serves the empty workspace on any failure. Thread `clueFetch` through `getBrandContextRepository` / `getBrandContextWorkspace`; the fixture repository ignores it.

- [ ] **Step 3: Page**

In `page.tsx`, resolve the context once and build both fetches on it:

```ts
async function backendFetches(): Promise<{ designFetch: typeof fetch; clueFetch: typeof fetch }> {
  const context = await authenticatedBackendContext();
  return {
    designFetch: (input, init) => fetchAuthenticatedDesignBackend(String(input), init, context),
    clueFetch: (input, init) => fetchAuthenticatedClueBackend(String(input), init, context),
  };
}
```

(`fetchAuthenticatedClueBackend(path, init, context)` — `src/auth/authenticated-backend.ts:99`.) Call `getBrandContextWorkspace(() => fetches.designFetch, () => fetches.clueFetch)`. Remove the `mode` query parse and the `documentMode` initial-state field.

- [ ] **Step 4: Remove the edit control (ruling)**

- `brand-context-header.tsx:86-96`: delete the `Document mode` `<div …documentModeControl>` block (both `Segment`s). If `Segment` and the `eye`/`code` icons are now unused in the file, remove those imports.
- `knowledge-panel.tsx`: delete the `documentMode === "edit"` branch and the `MarkdownSourceEditor` import; the panel always renders the preview article.
- `use-brand-context-controller.ts`: remove `documentMode` state, `setDocumentMode`, the `mode` param in `syncRoute`, and `documentBody`/`setDocumentBody` if they exist only for editing (the preview reads `selectedDocument.body`; keep `markdownBlocks` derived from it). Read the whole hook before cutting: anything else that reads `documentBody` (breadcrumb, tests) must keep working.
- `model/brand-context.ts`: remove `BrandDocumentModeSchema` and `BrandDocumentMode`; remove `documentMode` from `BrandContextInitialState`.
- `components/markdown-source-editor.tsx`: delete it if `grep -rn MarkdownSourceEditor apps/frontend/src` shows no other user; otherwise leave it.
- Update every test that referenced `documentMode`/`mode`.

- [ ] **Step 5: Run, gates, commit**

Run (from `apps/frontend`): `npm test && npm run lint && npm run build`

```bash
git add apps/frontend/src/features/brand-context apps/frontend/src/app/\(protected\)/brand-context/page.tsx
git commit -m "feat(frontend): brand-context Knowledge lists the onboarding documents from the platform read beside the kit's Design brief; the Preview/Edit control is removed (founder ruling 2026-09-08)"
```

---

### Task 5: Progressive fill — poll the run, refresh when a step lands

**Files:**
- Create: `apps/frontend/src/features/brand-context/hooks/use-knowledge-refresh.ts`
- Modify: `apps/frontend/src/features/brand-context/components/brand-context-screen.tsx`, `apps/frontend/src/app/(protected)/brand-context/page.tsx`
- Test: `apps/frontend/src/features/brand-context/hooks/use-knowledge-refresh.test.ts`

**Interfaces:**
- `page.tsx` reads `readOnboardingStatus(clueFetch)` alongside the workspace (same `Promise.all`) and passes `onboarding={status}` to `BrandContextScreen`.
- `useKnowledgeRefresh({ initial, source, intervalMs = 5000 })` where `source: KnowledgeRefreshSource = { read(): Promise<OnboardingStatus | null> }`; the hook polls while `onboardingRunIsLive(status)`, and calls `refresh()` (default `useRouter().refresh`) whenever the count of steps with a `finishedAt` grows; it stops when the run is terminal or the read returns `null` three times in a row. Pure decision helper exported for the test: `shouldRefresh(previous: OnboardingStatus | null, next: OnboardingStatus | null): boolean`.
- Browser source: `httpKnowledgeRefreshSource` reads `/api/clue/frontend/v1/brand-context/onboarding/current` (the same-origin BFF, `frontend-mutation.ts` `BFF_PREFIX = "/api/clue/frontend/v1"`) with `fetch(..., { cache: "no-store" })` and parses with `OnboardingStatusSchema`; refusal → `null`.

- [ ] **Step 1: Write the failing test (the pure part)**

```ts
// apps/frontend/src/features/brand-context/hooks/use-knowledge-refresh.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { shouldRefresh } from "./use-knowledge-refresh";

const step = (kind: string, finishedAt: string | null) => ({ costUsd: "0", failureCode: null, finishedAt, kind, phase: "fast", startedAt: "2026-09-08T00:00:00Z", status: finishedAt ? "completed" : "running", subjectRef: null });
const status = (steps: ReturnType<typeof step>[], runStatus = "running") => ({ costUsd: "0", runId: "r", status: runStatus, steps });

test("a newly finished step asks for a refresh; nothing else does", () => {
  assert.equal(shouldRefresh(status([step("overview", null)]), status([step("overview", "2026-09-08T00:01:00Z")])), true);
  assert.equal(shouldRefresh(status([step("overview", null)]), status([step("overview", null)])), false);
  assert.equal(shouldRefresh(null, status([step("overview", "2026-09-08T00:01:00Z")])), true);
  assert.equal(shouldRefresh(status([step("overview", "2026-09-08T00:01:00Z")]), null), false);
});

test("a run going terminal refreshes once so the last documents land", () => {
  const before = status([step("overview", "2026-09-08T00:01:00Z")]);
  const after = status([step("overview", "2026-09-08T00:01:00Z")], "completed");
  assert.equal(shouldRefresh(before, after), true);
});
```

- [ ] **Step 2: Write the hook**

```ts
// apps/frontend/src/features/brand-context/hooks/use-knowledge-refresh.ts
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { OnboardingStatusSchema, onboardingRunIsLive, type OnboardingStatus } from "../model/brand-knowledge";

const BFF_PATH = "/api/clue/frontend/v1/brand-context/onboarding/current";
const DEFAULT_INTERVAL_MS = 5000;
const MAX_CONSECUTIVE_REFUSALS = 3;

export interface KnowledgeRefreshSource {
  read(): Promise<OnboardingStatus | null>;
}

/** The browser path: the same-origin BFF proves the session and stamps the workspace. */
export const httpKnowledgeRefreshSource: KnowledgeRefreshSource = {
  async read() {
    try {
      const response = await fetch(BFF_PATH, { cache: "no-store" });
      if (!response.ok) return null;
      return OnboardingStatusSchema.parse(await response.json());
    } catch {
      return null;
    }
  },
};

function finishedCount(status: OnboardingStatus | null): number {
  return status?.steps.filter((step) => step.finishedAt !== null).length ?? 0;
}

/** Refresh when a step landed since the last observation, or when the run just went terminal. */
export function shouldRefresh(previous: OnboardingStatus | null, next: OnboardingStatus | null): boolean {
  if (next === null) return false;
  if (finishedCount(next) > finishedCount(previous)) return true;
  return onboardingRunIsLive(previous) && !onboardingRunIsLive(next);
}

/**
 * Progressive fill (ARV2-ONBOARDING-PLAN.md §7): while an onboarding run is queued or running,
 * poll its status and re-render the server page whenever a step finishes, so documents appear
 * as the run publishes them. No progress UI — the dummy has no slot for one.
 */
export function useKnowledgeRefresh({
  initial,
  source = httpKnowledgeRefreshSource,
  intervalMs = DEFAULT_INTERVAL_MS,
  refresh,
}: {
  initial: OnboardingStatus | null;
  source?: KnowledgeRefreshSource;
  intervalMs?: number;
  refresh?: () => void;
}): void {
  const router = useRouter();
  const last = useRef<OnboardingStatus | null>(initial);
  const refusals = useRef(0);
  const doRefresh = refresh ?? (() => router.refresh());

  useEffect(() => {
    if (!onboardingRunIsLive(initial)) return;
    let interval: number | null = null;
    const stop = () => {
      if (interval !== null) window.clearInterval(interval);
      interval = null;
    };
    const poll = async () => {
      const next = await source.read();
      if (next === null) {
        refusals.current += 1;
        if (refusals.current >= MAX_CONSECUTIVE_REFUSALS) stop();
        return;
      }
      refusals.current = 0;
      if (shouldRefresh(last.current, next)) doRefresh();
      last.current = next;
      if (!onboardingRunIsLive(next)) stop();
    };
    interval = window.setInterval(() => void poll(), intervalMs);
    return stop;
    // `initial` is the server's snapshot for this render; the loop re-arms on each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial?.runId, initial?.status]);
}
```

If the project's ESLint config rejects the disable comment, restructure with the `initial` fields in the dependency list instead (same behaviour).

- [ ] **Step 3: Mount**

- `brand-context-screen.tsx`: add prop `onboarding: OnboardingStatus | null` and call `useKnowledgeRefresh({ initial: onboarding })` at the top of the component.
- `page.tsx`: `const [view, onboarding, query] = await Promise.all([getBrandContextWorkspace(...), readOnboardingStatus(fetches.clueFetch), searchParams])` and pass `onboarding={onboarding}`. With `CLUE_API_BASE_URL` unset, skip the status read (`null`) so the fixture path issues no request — read how `getBrandContextRepository` decides the fixture path and mirror the condition.

- [ ] **Step 4: Run, gates, commit**

Run (from `apps/frontend`): `npx tsx --test src/features/brand-context/hooks/use-knowledge-refresh.test.ts && npm test && npm run lint && npm run build`

```bash
git add apps/frontend/src/features/brand-context/hooks/use-knowledge-refresh.ts apps/frontend/src/features/brand-context/hooks/use-knowledge-refresh.test.ts apps/frontend/src/features/brand-context/components/brand-context-screen.tsx apps/frontend/src/app/\(protected\)/brand-context/page.tsx
git commit -m "feat(frontend): brand-context Knowledge fills progressively — poll the onboarding status while a run is live and refresh the page when a step lands"
```

---

### Task 6: Gates, standing-rule check, memory note

**Files:**
- Create: `_memory/2026-09-08-arv2-onboarding-o5-knowledge-read-surface.md`
- Modify: `_memory/README.md`

- [ ] **Step 1: Gates**

Backend (throwaway DB): `set -a; source .env; set +a; export CLUE_DATABASE_URL="$(echo "$CLUE_DATABASE_URL" | sed -E 's#/[^/]+$#/clue_o4_agent#')"; uv run pytest tests/api/test_frontend_read_brand_knowledge.py tests/api/test_frontend_read_app.py tests/arv2 --ignore-glob='*_live.py' -q && uv run ruff check platform/api/clue_api/frontend_read && uv run mypy platform/api/clue_api/frontend_read/brand_knowledge.py`.
Frontend (`apps/frontend`): `npm run design-system:build && npm run lint && npm run build && npm test`.
Standing rule: `grep -rn "client_kb_version\|readiness_decision\|project_run_stage0_pins\|evaluate_stage0_readiness" platform/api/clue_api/frontend_read/brand_knowledge.py apps/frontend/src/features/brand-context` → zero hits.

- [ ] **Step 2: Memory note**

Write `_memory/2026-09-08-arv2-onboarding-o5-knowledge-read-surface.md`: what landed (the three reads and their real paths, the merged folders, the removed edit control, the refresh hook), the two founder rulings (no chip / servable only; edit removed page-wide), the plan's own rulings (brand resolution order; title from the first H1; sources flattened from O2's front matter; tree bodies read sequentially server-side, page bodies in parallel; refusal → honest empties; 503 when no storage), test files and counts, and "acceptance NOT run — Task 7 is founder-triggered". Add a `_memory/README.md` pointer beside the O4 line.

```bash
git add _memory/2026-09-08-arv2-onboarding-o5-knowledge-read-surface.md _memory/README.md
git commit -m "memory: ARV2 onboarding O5 close-out — the Knowledge read surface, the re-lifted folders, the removed edit control, progressive fill"
```

---

### Task 7: Acceptance (founder-triggered)

**Do not execute without Aryan's go.** The O5 exit gate: with `CLUE_API_BASE_URL` set, the brand-context page renders the real tree and fills as steps land.

- [ ] **Step 1:** A platform API from this checkout (`uvicorn clue_api.projections_main:app` on a port of its own; `CLUE_FRONTEND_READ_ENABLED=true` in `.env`) against `clue_semarang`, which holds Insight Health's run-3 documents; the semarang fleet worker.
- [ ] **Step 2:** A frontend dev server on its own port with `apps/frontend/.env.local` pointing `CLUE_API_BASE_URL` at that API and the Clerk authorized-party list including that port (`DEV_STACK.md` explains each guard); sign in with the dev login.
- [ ] **Step 3:** Open `/brand-context?section=knowledge`: Company, Product, Audience, Proof folders list the run-3 documents; `audience/icp-*.md` and `persona-*.md` render; no Edit control anywhere; Design.md still present when a kit exists.
- [ ] **Step 4:** `POST /onboarding` again (through the API with the workspace header) and watch the page fill as steps land without a manual reload; screenshots + the API's request log into `.context/arv2-onboarding-o5-acceptance/`; append numbers to the memory note; commit the note only.
