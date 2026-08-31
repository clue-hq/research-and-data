"""C7 database acceptance: concurrent grounded writes, partial failure, and cold replay."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from tests.db.conftest import run_async

from clue_api.client_context_binding import bind_workspace_client
from clue_api.official_site_crawl_wiring import _AuthoritativeClientKbCommitter
from clue_api.product_catalog_sync import ProductCatalogSynchronizer
from clue_core import (
    Claim,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    ReuseScope,
    RunId,
)
from clue_core.gateway import Completion, Message, TokenUsage
from clue_db import db_lifespan, transaction
from clue_research.claimstore import insert_claim, load_core_pack, record_run_lineage
from clue_research.identity import insert_account_entity
from clue_research.official_site import (
    EXTRACTION_MAX_OUTPUT_TOKENS,
    EXTRACTION_PROMPT_VERSION,
    EXTRACTION_REASONING_EFFORT,
    EXTRACTION_SCHEMA_VERSION,
    CrawlPhase,
    GroundedOfficialSiteMaterializer,
    OfficialSiteMaterializationRequest,
    compute_snapshot_set_sha256,
)
from clue_research.sources import seed_source_manifests
from clue_research.stage0 import finalize_client_kb_version, read_client_kb_claims
from clue_research.stage0.fields import load_client_knowledge_pack
from clue_spine import create_product, list_products
from clue_storage import FsStorage, artifact_key, content_address
from clue_storage.artifacts import record_artifact

pytestmark = pytest.mark.usefixtures("require_official_site_db")


@dataclass(frozen=True, slots=True)
class _Scope:
    workspace_id: str
    brand_id: str
    recon_run_id: UUID
    claim_run_id: UUID
    client_entity_id: UUID
    crawl_run_id: UUID
    checkpoint_id: UUID
    phase: CrawlPhase = CrawlPhase.FAST


class _Gateway:
    def __init__(
        self,
        *,
        invalid_fields: frozenset[str] = frozenset(),
        raising_fields: frozenset[str] = frozenset(),
        terminal_failure_fields: frozenset[str] = frozenset(),
    ) -> None:
        self.invalid_fields = invalid_fields
        self.raising_fields = raising_fields
        self.terminal_failure_fields = terminal_failure_fields
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self._active = 0
        self.max_active = 0

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        assert opts["max_tokens"] == EXTRACTION_MAX_OUTPUT_TOKENS
        assert opts["reasoning"] == {"effort": EXTRACTION_REASONING_EFFORT}
        user = messages[-1].content
        field = re.search(r"^FIELD: ([^\n]+)$", user, re.MULTILINE)
        assert field is not None
        field_key = field.group(1)
        with self._lock:
            self.calls.append((model, field_key))
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            time.sleep(0.03)
            if field_key in self.raising_fields:
                raise RuntimeError("ambiguous model failure")
            if field_key in self.terminal_failure_fields:
                failure = RuntimeError("known terminal model response")
                failure.completion = Completion(  # type: ignore[attr-defined]
                    model=model,
                    text="",
                    usage=TokenUsage(prompt_tokens=321, completion_tokens=1_024),
                    cost_cents=Decimal("1.75"),
                    finish_reason="max_output_tokens",
                )
                failure.failure_code = (  # type: ignore[attr-defined]
                    "gateway_no_output_max_output_tokens"
                )
                raise failure
            block = re.search(
                r"SNAPSHOT_ID: ([0-9a-f-]+)\nSOURCE_URL: ([^\n]+)\n"
                r"<<<UNTRUSTED_PAGE_TEXT>>>\n(.*?)\n<<<END_UNTRUSTED_PAGE_TEXT>>>",
                user,
                re.DOTALL,
            )
            assert block is not None
            snapshot_id, source_url, body = block.groups()
            quote = next(line for line in body.splitlines() if line.strip())
            if field_key in self.invalid_fields:
                snapshot_id = str(uuid4())
                source_url = "https://evil.example/forged"
            if field_key == "client.customer":
                value: object = [{"name": "Northstar Health", "domain": "northstar.test"}]
            elif field_key == "client.icp_evidence":
                value = {"industries": ["healthcare"]}
            elif field_key == "client.product_catalog":
                value = [
                    {
                        "name": "Acme Phone Agents",
                        "short_description": "AI agents for healthcare scheduling calls",
                        "aliases": ["Acme Voice"],
                    }
                ]
            elif field_key in {
                "client.product_capability",
                "client.product_use_case",
                "client.product_pricing",
                "client.product_integration",
                "client.product_customer_evidence",
            }:
                value = {"summary": f"Grounded {field_key}"}
            else:
                value = f"Grounded {field_key}"
            response = {
                "claims": [
                    {
                        "snapshot_id": snapshot_id,
                        "source_url": source_url,
                        "value": value,
                        "quote": quote,
                        "confidence": 0.91,
                    }
                ]
            }
            return Completion(
                model=model,
                text=json.dumps(response),
                usage=TokenUsage(prompt_tokens=100, completion_tokens=25),
                cost_cents=Decimal("0.25"),
                finish_reason="completed",
            )
        finally:
            with self._lock:
                self._active -= 1

    def embed(self, *, model: str, inputs: list[str]) -> object:  # pragma: no cover - never called
        raise AssertionError((model, inputs))


class _TrackingContext(AbstractAsyncContextManager[Any]):
    def __init__(self, owner: _TrackingFactory) -> None:
        self.owner = owner
        self.inner = transaction()
        self.connection: object | None = None

    async def __aenter__(self) -> Any:
        connection = await self.inner.__aenter__()
        self.connection = connection
        key = id(connection)
        with self.owner.lock:
            if key in self.owner.active:
                self.owner.shared_while_active = True
            self.owner.active.add(key)
            self.owner.max_active = max(self.owner.max_active, len(self.owner.active))
        return connection

    async def __aexit__(self, *args: object) -> bool | None:
        assert self.connection is not None
        with self.owner.lock:
            self.owner.active.remove(id(self.connection))
        return await self.inner.__aexit__(*args)


class _TrackingFactory:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active: set[int] = set()
        self.max_active = 0
        self.shared_while_active = False

    def __call__(self) -> _TrackingContext:
        return _TrackingContext(self)


async def _seed_scope(
    storage: FsStorage,
    *,
    include_marker: bool = True,
    phase: CrawlPhase = CrawlPhase.FAST,
) -> _Scope:
    workspace_id = f"official-site-c7-{uuid4()}"
    brand_id = f"brand-{uuid4()}"
    recon_run_id = uuid4()
    fast_run_id = uuid4()
    background_run_id = uuid4()
    claim_run_id = fast_run_id if phase is CrawlPhase.FAST else background_run_id
    crawl_run_id = uuid4()
    checkpoint_id = uuid4()

    async with transaction() as conn:
        await conn.execute(
            text("INSERT INTO workspace (workspace_id, name) VALUES (:id, 'C7 Test')"),
            {"id": workspace_id},
        )
        await conn.execute(
            text(
                "INSERT INTO brand (brand_id, workspace_id, name) "
                "VALUES (:brand_id, :workspace_id, 'C7 Brand')"
            ),
            {"brand_id": brand_id, "workspace_id": workspace_id},
        )
        client_entity_id = UUID(
            str(
                await insert_account_entity(
                    conn,
                    canonical_name="C7 Example",
                    primary_domain="example.com",
                    workspace_id=workspace_id,
                )
            )
        )
        await conn.execute(
            text(
                """
                INSERT INTO recon_run (
                    id, workspace_id, brand_id, dedupe_hash, dedupe_expires_at,
                    fast_run_id, background_run_id, fast_budget_cents,
                    background_budget_cents, recipe_version, skill_version,
                    client_entity_id
                ) VALUES (
                    :id, :workspace_id, :brand_id, :dedupe_hash, now() + interval '1 hour',
                    :fast_run_id, :background_run_id, 0, 0, 'test-v1', 'test-v1',
                    :client_entity_id
                )
                """
            ),
            {
                "id": recon_run_id,
                "workspace_id": workspace_id,
                "brand_id": brand_id,
                "dedupe_hash": hashlib.sha256(str(recon_run_id).encode()).hexdigest(),
                "fast_run_id": fast_run_id,
                "background_run_id": background_run_id,
                "client_entity_id": client_entity_id,
            },
        )
        await load_core_pack(conn)
        await load_client_knowledge_pack(conn)
        await seed_source_manifests(conn)
        await record_run_lineage(
            conn, run_id=RunId(claim_run_id), workspace_id=workspace_id, kind="stage0"
        )
        if include_marker:
            marker = Claim(
                entity_id=client_entity_id,
                entity_type=EntityType.ACCOUNT,
                field_key="client.kb_version",
                value_json={"version": 1, "run_id": str(claim_run_id)},
                source_tier=1,
                extraction_method=ExtractionMethod.HUMAN,
                confidence=1.0,
                run_id=RunId(claim_run_id),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=workspace_id,
            )
            await insert_claim(conn, marker)
        await conn.execute(
            text(
                """
                INSERT INTO official_site_crawl_run (
                    id, workspace_id, brand_id, client_entity_id, recon_run_id,
                    root_discovered_url, root_fetch_key, allowed_registrable_domain,
                    status, max_graph_depth, fast_claim_deadline_at,
                    overall_page_ceiling, fast_page_ceiling, provider_policy_version,
                    url_policy_version, robots_policy_version, config_json, completed_at
                ) VALUES (
                    :id, :workspace_id, :brand_id, :client_entity_id, :recon_run_id,
                    'https://example.com/', 'https://example.com/', 'example.com',
                    'completed', 2, now() + interval '40 seconds', 20, 12,
                    'provider-v1', 'official-site-url-v1', 'official-site-robots-v1',
                    '{}'::jsonb, now()
                )
                """
            ),
            {
                "id": crawl_run_id,
                "workspace_id": workspace_id,
                "brand_id": brand_id,
                "client_entity_id": client_entity_id,
                "recon_run_id": recon_run_id,
            },
        )

    page_specs = (
        (
            "https://example.com/",
            "homepage",
            "Acme automates patient scheduling for healthcare providers.",
        ),
        (
            "https://example.com/pricing",
            "pricing",
            "Pricing is custom and customers should contact sales.",
        ),
        (
            "https://example.com/customers/northstar",
            "customer_proof",
            "Northstar Health reduced call wait times by 40 percent.",
        ),
        (
            "https://example.com/about",
            "company",
            "Founded by clinicians and built for HIPAA-compliant care teams.",
        ),
    )
    snapshots: list[UUID] = []
    for url, category, body in page_specs:
        page_id = uuid4()
        attempt_id = uuid4()
        snapshot_id = uuid4()
        snapshots.append(snapshot_id)
        content = f"<html><body><p>{body}</p></body></html>".encode()
        digest = content_address(content)
        key = artifact_key(workspace_id, digest)
        async with transaction() as conn:
            await record_artifact(
                conn,
                storage_key=key,
                workspace_id=workspace_id,
                content_sha256=digest,
                media_type="text/html",
                size_bytes=len(content),
                source_key="official_site",
                source_url=url,
            )
            await storage.put(key, content, media_type="text/html")
            await conn.execute(
                text(
                    """
                    INSERT INTO official_site_crawl_page (
                        id, workspace_id, crawl_run_id, fetch_key, fetch_key_hash,
                        representative_requested_url, host, graph_depth, priority,
                        priority_reason_json, eligibility, state, attempt_count,
                        discovered_at, queued_at
                    ) VALUES (
                        :id, :workspace_id, :crawl_run_id, :url, :hash, :url,
                        'example.com', 1, 0, CAST(:reasons AS jsonb), 'both', 'queued', 1,
                        now(), now()
                    )
                    """
                ),
                {
                    "id": page_id,
                    "workspace_id": workspace_id,
                    "crawl_run_id": crawl_run_id,
                    "url": url,
                    "hash": hashlib.sha256(url.encode()).hexdigest(),
                    "reasons": json.dumps([f"category:{category}", "via:link"]),
                },
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO official_site_fetch_attempt (
                        id, workspace_id, crawl_run_id, page_id, attempt_number,
                        lease_generation, worker_id, operation_key, provider_key, state,
                        requested_url, final_url, redirect_chain_json, provider_status,
                        http_status, media_type, size_bytes, cost_kind, spend_status,
                        retry_class, artifact_key, content_sha256, started_at, dispatched_at,
                        provider_completed_at, persisted_at, finished_at
                    ) VALUES (
                        :id, :workspace_id, :crawl_run_id, :page_id, 1, 1, 'c7-test',
                        :operation_key, 'fixture', 'persisted', :url, :url, '[]'::jsonb, 'ok',
                        200, 'text/html', :size_bytes, 'none', 'no_spend', 'success',
                        :artifact_key, :content_sha256, now(), now(), now(), now(), now()
                    )
                    """
                ),
                {
                    "id": attempt_id,
                    "workspace_id": workspace_id,
                    "crawl_run_id": crawl_run_id,
                    "page_id": page_id,
                    "operation_key": f"c7-test:{attempt_id}",
                    "url": url,
                    "size_bytes": len(content),
                    "artifact_key": key,
                    "content_sha256": digest,
                },
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO official_site_page_snapshot (
                        id, workspace_id, crawl_run_id, page_id, fetch_attempt_id,
                        requested_url, final_url, redirect_chain_json, fetched_at,
                        provider_key, http_status, media_type, artifact_key, content_sha256,
                        size_bytes, robots_decision_ref, policy_version
                    ) VALUES (
                        :id, :workspace_id, :crawl_run_id, :page_id, :attempt_id,
                        :url, :url, '[]'::jsonb, now(), 'fixture', 200, 'text/html',
                        :artifact_key, :content_sha256, :size_bytes, 'robots:test', 'safety-v1'
                    )
                    """
                ),
                {
                    "id": snapshot_id,
                    "workspace_id": workspace_id,
                    "crawl_run_id": crawl_run_id,
                    "page_id": page_id,
                    "attempt_id": attempt_id,
                    "url": url,
                    "artifact_key": key,
                    "content_sha256": digest,
                    "size_bytes": len(content),
                },
            )
            await conn.execute(
                text(
                    "UPDATE official_site_crawl_page "
                    "SET state = 'fetched', latest_snapshot_id = :snapshot_id, fetched_at = now() "
                    "WHERE id = :page_id"
                ),
                {"snapshot_id": snapshot_id, "page_id": page_id},
            )

    ordered = tuple(sorted(snapshots, key=str))
    async with transaction() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO official_site_corpus_checkpoint (
                    id, workspace_id, crawl_run_id, phase, version, snapshot_ids_json,
                    snapshot_set_sha256, coverage_json
                ) VALUES (
                    :id, :workspace_id, :crawl_run_id, :phase, 1,
                    CAST(:snapshot_ids AS jsonb), :snapshot_hash,
                    CAST(:coverage AS jsonb)
                )
                """
            ),
            {
                "id": checkpoint_id,
                "workspace_id": workspace_id,
                "crawl_run_id": crawl_run_id,
                "phase": phase.value,
                "snapshot_ids": json.dumps([str(item) for item in ordered]),
                "snapshot_hash": compute_snapshot_set_sha256(ordered),
                "coverage": json.dumps({"snapshot_count": len(ordered)}),
            },
        )
    return _Scope(
        workspace_id=workspace_id,
        brand_id=brand_id,
        recon_run_id=recon_run_id,
        claim_run_id=claim_run_id,
        client_entity_id=client_entity_id,
        crawl_run_id=crawl_run_id,
        checkpoint_id=checkpoint_id,
        phase=phase,
    )


def _request(scope: _Scope, *, model: str = "openai/gpt-5.6-luna") -> Any:
    return OfficialSiteMaterializationRequest(
        workspace_id=scope.workspace_id,
        crawl_run_id=scope.crawl_run_id,
        recon_run_id=scope.recon_run_id,
        claim_run_id=scope.claim_run_id,
        client_entity_id=scope.client_entity_id,
        checkpoint_id=scope.checkpoint_id,
        phase=scope.phase,
        model_id=model,
        prompt_version=EXTRACTION_PROMPT_VERSION,
        schema_version=EXTRACTION_SCHEMA_VERSION,
    )


async def _cleanup(scope: _Scope) -> None:
    # Claims are intentionally append-only and the database gate explicitly requires a disposable
    # database.  Unique workspace ids isolate every scenario; retaining its rows also exercises the
    # same durable/auditable behavior used in production instead of disabling authority triggers in
    # a test cleanup path.
    del scope


def test_concurrent_grounded_materialization_and_replay_are_exactly_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        scope = await _seed_scope(storage)
        gateway = _Gateway()
        connections = _TrackingFactory()
        materializer = GroundedOfficialSiteMaterializer(
            gateway=gateway,  # type: ignore[arg-type]
            storage=storage,
            conn_factory=connections,  # type: ignore[arg-type]
            extraction_concurrency=4,
        )
        try:
            result = await materializer.materialize(_request(scope))
            assert result.failed_fields == ()
            assert result.empty_fields == ()
            assert set(result.filled_fields) == {
                "client.value_prop",
                "client.product",
                "client.differentiator",
                "client.pricing_posture",
                "client.proof_point",
                "client.customer",
                "client.icp_evidence",
                "client.delivered_value",
                "client.market_reputation",
                "client.product_catalog",
            }
            assert len(result.claim_ids) == 12
            assert len(gateway.calls) == 12
            assert gateway.max_active >= 2
            assert connections.max_active >= 2
            assert not connections.shared_while_active

            async with transaction() as conn:
                before = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM claim WHERE workspace_id = :workspace_id "
                            "AND source_key = 'official_site'"
                        ),
                        {"workspace_id": scope.workspace_id},
                    )
                ).scalar_one()
                provenance = list(
                    (
                        await conn.execute(
                            text(
                                "SELECT source_url, source_snapshot_ref, artifact_key "
                                "FROM claim WHERE workspace_id = :workspace_id "
                                "AND source_key = 'official_site'"
                            ),
                            {"workspace_id": scope.workspace_id},
                        )
                    ).all()
                )
                assert all(row.source_url.startswith("https://example.com/") for row in provenance)
                assert all(
                    row.source_snapshot_ref.startswith("official-site-page:") for row in provenance
                )
                assert all(
                    row.artifact_key.startswith(f"{scope.workspace_id}/") for row in provenance
                )

            replay = await materializer.materialize(_request(scope))
            assert replay == result
            assert len(gateway.calls) == 12
            async with transaction() as conn:
                after = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM claim WHERE workspace_id = :workspace_id "
                            "AND source_key = 'official_site'"
                        ),
                        {"workspace_id": scope.workspace_id},
                    )
                ).scalar_one()
                operations = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM official_site_extraction_operation "
                            "WHERE workspace_id = :workspace_id"
                        ),
                        {"workspace_id": scope.workspace_id},
                    )
                ).scalar_one()
            assert before == after == 12
            assert operations == 12

            with pytest.raises(ValueError, match="outside workspace/run"):
                await materializer.materialize(
                    _request(scope).model_copy(update={"workspace_id": "another-workspace"})
                )
        finally:
            await _cleanup(scope)

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_catalog_materialization_synchronizes_product_once_and_replays_without_spend(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "s5-catalog-artifacts")
        scope = await _seed_scope(storage)
        gateway = _Gateway()
        async with transaction() as conn:
            await bind_workspace_client(
                conn,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                source_recon_run_id=scope.recon_run_id,
            )
        materializer = GroundedOfficialSiteMaterializer(
            gateway=gateway,  # type: ignore[arg-type]
            storage=storage,
            product_catalog_synchronizer=ProductCatalogSynchronizer(transaction),
        )
        result = await materializer.materialize(_request(scope))
        assert "client.product_catalog" in result.filled_fields
        calls = len(gateway.calls)
        async with transaction() as conn:
            products = await list_products(conn, scope.brand_id)
            lineage = (
                await conn.execute(
                    text(
                        "SELECT resolution_state, product_id FROM product_catalog_lineage "
                        "WHERE workspace_id=:workspace_id"
                    ),
                    {"workspace_id": scope.workspace_id},
                )
            ).one()
        assert [(item.name, item.aliases) for item in products] == [
            ("Acme Phone Agents", ("Acme Voice",))
        ]
        assert lineage.resolution_state == "created"
        assert lineage.product_id == products[0].product_id

        replay = await materializer.materialize(_request(scope))
        assert replay == result
        assert len(gateway.calls) == calls
        async with transaction() as conn:
            assert len(await list_products(conn, scope.brand_id)) == 1
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM product_catalog_lineage "
                        "WHERE workspace_id=:workspace_id"
                    ),
                    {"workspace_id": scope.workspace_id},
                )
            ).scalar_one() == 1

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_company_materialization_stays_account_wide_when_recon_has_a_product(
    tmp_path: Path,
) -> None:
    """A legacy/project recon product is not authority to relabel company facts as product facts."""

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "s5-company-scope-artifacts")
        scope = await _seed_scope(storage, include_marker=False)
        gateway = _Gateway()
        async with transaction() as conn:
            await bind_workspace_client(
                conn,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                source_recon_run_id=scope.recon_run_id,
            )
            selected = await create_product(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                name="Human-selected legacy product",
            )
            await conn.execute(
                text(
                    "UPDATE recon_run SET product_id=:product_id "
                    "WHERE id=:recon_run_id AND workspace_id=:workspace_id"
                ),
                {
                    "product_id": selected.product_id,
                    "recon_run_id": scope.recon_run_id,
                    "workspace_id": scope.workspace_id,
                },
            )
        materializer = GroundedOfficialSiteMaterializer(
            gateway=gateway,  # type: ignore[arg-type]
            storage=storage,
            client_kb_committer=_AuthoritativeClientKbCommitter(transaction),
            product_catalog_synchronizer=ProductCatalogSynchronizer(transaction),
        )

        result = await materializer.materialize(_request(scope))
        assert result.client_kb_version == 1
        async with transaction() as conn:
            rows = list(
                (
                    await conn.execute(
                        text(
                            "SELECT field_key, product_id FROM claim "
                            "WHERE workspace_id=:workspace_id AND run_id=:run_id "
                            "ORDER BY field_key"
                        ),
                        {
                            "workspace_id": scope.workspace_id,
                            "run_id": scope.claim_run_id,
                        },
                    )
                ).all()
            )
        assert rows
        assert {row.product_id for row in rows} == {None}
        assert "client.product_catalog" in {row.field_key for row in rows}

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_background_catalog_materializes_exact_product_knowledge_without_refetch_or_replay_spend(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "s5-product-artifacts")
        scope = await _seed_scope(
            storage,
            include_marker=False,
            phase=CrawlPhase.BACKGROUND,
        )
        gateway = _Gateway()
        async with transaction() as conn:
            await bind_workspace_client(
                conn,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                source_recon_run_id=scope.recon_run_id,
            )
        materializer = GroundedOfficialSiteMaterializer(
            gateway=gateway,  # type: ignore[arg-type]
            storage=storage,
            client_kb_committer=_AuthoritativeClientKbCommitter(transaction),
            product_catalog_synchronizer=ProductCatalogSynchronizer(transaction),
            extraction_concurrency=4,
        )

        result = await materializer.materialize(_request(scope))
        calls = len(gateway.calls)
        assert calls == 20  # 12 company/category operations + 8 official product fields.
        async with transaction() as conn:
            products = await list_products(conn, scope.brand_id)
            assert len(products) == 1
            product = products[0]
            rows = list(
                (
                    await conn.execute(
                        text(
                            "SELECT field_key, product_id FROM claim "
                            "WHERE workspace_id=:workspace_id AND run_id=:run_id "
                            "AND product_id IS NOT NULL ORDER BY field_key"
                        ),
                        {
                            "workspace_id": scope.workspace_id,
                            "run_id": scope.claim_run_id,
                        },
                    )
                ).all()
            )
            product_fields = {row.field_key for row in rows if row.field_key != "client.kb_version"}
            assert product_fields == {
                "client.product_overview",
                "client.product_capability",
                "client.product_use_case",
                "client.product_differentiator",
                "client.product_pricing",
                "client.product_integration",
                "client.product_customer_evidence",
                "client.product_positioning",
            }
            assert {row.product_id for row in rows} == {product.product_id}
            marker = (
                await conn.execute(
                    text(
                        "SELECT value_json FROM claim WHERE workspace_id=:workspace_id "
                        "AND entity_id=:client_entity_id AND field_key='client.kb_version' "
                        "AND product_id=:product_id"
                    ),
                    {
                        "workspace_id": scope.workspace_id,
                        "client_entity_id": scope.client_entity_id,
                        "product_id": product.product_id,
                    },
                )
            ).scalar_one()
            assert marker["version"] == 1
            operation_rows = list(
                (
                    await conn.execute(
                        text(
                            "SELECT DISTINCT product_id FROM official_site_extraction_operation "
                            "WHERE workspace_id=:workspace_id AND product_id IS NOT NULL"
                        ),
                        {"workspace_id": scope.workspace_id},
                    )
                ).scalars()
            )
            assert operation_rows == [product.product_id]
            recon = (
                await conn.execute(
                    text("SELECT background_status FROM recon_run WHERE id=:id"),
                    {"id": scope.recon_run_id},
                )
            ).scalar_one()
            assert recon == "completed"

        replay = await materializer.materialize(_request(scope))
        assert replay == result
        assert len(gateway.calls) == calls
        async with transaction() as conn:
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM official_site_extraction_operation "
                        "WHERE workspace_id=:workspace_id"
                    ),
                    {"workspace_id": scope.workspace_id},
                )
            ).scalar_one() == 20

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_catalog_sync_uses_alias_authority_refuses_name_only_merge_and_is_dsar_reachable(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        scope = await _seed_scope(FsStorage(tmp_path / "s5-catalog-policy"))
        async with transaction() as conn:
            await bind_workspace_client(
                conn,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                source_recon_run_id=scope.recon_run_id,
            )
            aliased = await create_product(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=scope.brand_id,
                name="Durable Existing Product",
                aliases=("Known Alias",),
            )
            claim = Claim(
                entity_id=scope.client_entity_id,
                entity_type=EntityType.ACCOUNT,
                field_key="client.product_catalog",
                value_json=[
                    {
                        "name": "Alpha",
                        "short_description": "First explicit product",
                        "aliases": [],
                    },
                    {
                        "name": "Known Alias",
                        "short_description": "Alias-authorized existing product",
                        "aliases": [],
                    },
                    {
                        "name": " alpha ",
                        "short_description": "A second explicit same-name observation",
                        "aliases": [],
                    },
                ],
                source_tier=2,
                source_url="https://example.com/products",
                extraction_method=ExtractionMethod.SCRAPE,
                confidence=0.9,
                run_id=RunId(scope.claim_run_id),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=scope.workspace_id,
            )
            await insert_claim(conn, claim)
        synchronizer = ProductCatalogSynchronizer(transaction)
        first = await synchronizer.synchronize(_request(scope), company_client_kb_version=1)
        second = await synchronizer.synchronize(_request(scope), company_client_kb_version=1)
        assert first == second
        assert [item.resolution_state for item in first.lineages] == [
            "created",
            "alias_reused",
            "unresolved_ambiguous",
        ]
        assert first.lineages[1].product_id == aliased.product_id
        assert first.lineages[2].product_id is None
        async with transaction() as conn:
            assert len(await list_products(conn, scope.brand_id)) == 2
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM product_catalog_lineage "
                        "WHERE catalog_claim_id=:claim_id"
                    ),
                    {"claim_id": claim.id},
                )
            ).scalar_one() == 3
            reach = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM product_catalog_lineage AS lineage "
                        "JOIN claim ON claim.id=lineage.catalog_claim_id "
                        "WHERE claim.entity_id=:client_entity_id "
                        "AND lineage.workspace_id=:workspace_id"
                    ),
                    {
                        "client_entity_id": scope.client_entity_id,
                        "workspace_id": scope.workspace_id,
                    },
                )
            ).scalar_one()
            assert reach == 3
            lineage_columns = set(
                (
                    await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name='product_catalog_lineage'"
                        )
                    )
                ).scalars()
            )
            assert lineage_columns.isdisjoint(
                {"name", "aliases", "short_description", "value_json", "evidence_span"}
            )

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_catalog_sync_reuses_exact_prior_lineage_across_company_versions(tmp_path: Path) -> None:
    async def scenario() -> None:
        scope = await _seed_scope(FsStorage(tmp_path / "s5-catalog-version-reuse"))
        catalog_value = [
            {
                "name": "Acme Phone Agents",
                "short_description": "AI agents for healthcare scheduling calls",
                "aliases": ["Acme Voice"],
            }
        ]
        async with transaction() as conn:
            await bind_workspace_client(
                conn,
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                source_recon_run_id=scope.recon_run_id,
            )
            claim_v1 = Claim(
                entity_id=scope.client_entity_id,
                entity_type=EntityType.ACCOUNT,
                field_key="client.product_catalog",
                value_json=catalog_value,
                source_tier=2,
                source_url="https://example.com/products",
                extraction_method=ExtractionMethod.SCRAPE,
                confidence=0.9,
                run_id=RunId(scope.claim_run_id),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=scope.workspace_id,
            )
            await insert_claim(conn, claim_v1)
        synchronizer = ProductCatalogSynchronizer(transaction)
        first = await synchronizer.synchronize(_request(scope), company_client_kb_version=1)
        assert first.lineages[0].resolution_state == "created"

        second_run = RunId(uuid4())
        async with transaction() as conn:
            await record_run_lineage(
                conn,
                run_id=second_run,
                workspace_id=scope.workspace_id,
                kind="stage0",
            )
            claim_v2 = claim_v1.model_copy(update={"id": uuid4(), "run_id": second_run})
            await insert_claim(conn, claim_v2)
            version = await finalize_client_kb_version(
                conn,
                client_entity_id=scope.client_entity_id,
                workspace_id=scope.workspace_id,
                run_id=second_run,
                filled_fields={"client.product_catalog"},
                attempted_fields={"client.product_catalog"},
                product_id=None,
            )
        assert version == 2
        second = await synchronizer.synchronize(
            _request(scope).model_copy(update={"claim_run_id": second_run}),
            company_client_kb_version=2,
        )
        assert second.lineages[0].resolution_state == "lineage_reused"
        assert second.lineages[0].product_id == first.lineages[0].product_id
        assert second.product_targets == first.product_targets
        async with transaction() as conn:
            assert len(await list_products(conn, scope.brand_id)) == 1

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_authoritative_committer_publishes_marker_and_fast_lane_after_claims(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        scope = await _seed_scope(FsStorage(tmp_path / "cutover-artifacts"), include_marker=False)
        async with transaction() as conn:
            await insert_claim(
                conn,
                Claim(
                    entity_id=scope.client_entity_id,
                    entity_type=EntityType.ACCOUNT,
                    field_key="client.value_prop",
                    value_json="Grounded value",
                    source_tier=1,
                    extraction_method=ExtractionMethod.HUMAN,
                    confidence=0.9,
                    run_id=RunId(scope.claim_run_id),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    reuse_scope=ReuseScope.TENANT_PRIVATE,
                    workspace_id=scope.workspace_id,
                ),
            )
        committer = _AuthoritativeClientKbCommitter(transaction)
        version = await committer.commit(
            _request(scope),
            filled_fields={"client.value_prop"},
            attempted_fields={"client.value_prop", "client.product"},
        )
        assert version == 1
        await committer.complete(
            _request(scope),
            company_client_kb_version=version,
        )
        async with transaction() as conn:
            marker = (
                (
                    await conn.execute(
                        text(
                            "SELECT value_json FROM claim WHERE workspace_id = :workspace_id "
                            "AND run_id = :run_id AND field_key = 'client.kb_version'"
                        ),
                        {"workspace_id": scope.workspace_id, "run_id": scope.claim_run_id},
                    )
                )
                .mappings()
                .one()
            )
            recon = (
                await conn.execute(
                    text(
                        "SELECT fast_status, fast_client_kb_version FROM recon_run WHERE id = :id"
                    ),
                    {"id": scope.recon_run_id},
                )
            ).one()
        assert marker["value_json"]["filled_fields"] == 1
        assert marker["value_json"]["total_fields"] == 12
        assert recon.fast_status == "completed"
        assert recon.fast_client_kb_version == 1

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_authoritative_background_version_overlays_fast_snapshot_on_partial_failure(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        scope = await _seed_scope(FsStorage(tmp_path / "background-overlay"), include_marker=False)
        fast_request = _request(scope)
        committer = _AuthoritativeClientKbCommitter(transaction)
        async with transaction() as conn:
            await insert_claim(
                conn,
                Claim(
                    entity_id=scope.client_entity_id,
                    entity_type=EntityType.ACCOUNT,
                    field_key="client.product_catalog",
                    value_json=[
                        {
                            "name": "Acme Phone Agents",
                            "short_description": "Healthcare call automation",
                            "aliases": ["Acme Voice"],
                        }
                    ],
                    source_tier=1,
                    extraction_method=ExtractionMethod.HUMAN,
                    confidence=0.9,
                    run_id=RunId(scope.claim_run_id),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    reuse_scope=ReuseScope.TENANT_PRIVATE,
                    workspace_id=scope.workspace_id,
                ),
            )
        fast_version = await committer.commit(
            fast_request,
            filled_fields={"client.product_catalog"},
            attempted_fields={"client.product_catalog"},
        )
        assert fast_version == 1
        await committer.complete(fast_request, company_client_kb_version=fast_version)

        async with transaction() as conn:
            background_run_id = (
                await conn.execute(
                    text("SELECT background_run_id FROM recon_run WHERE id=:id"),
                    {"id": scope.recon_run_id},
                )
            ).scalar_one()
            await insert_claim(
                conn,
                Claim(
                    entity_id=scope.client_entity_id,
                    entity_type=EntityType.ACCOUNT,
                    field_key="client.differentiator",
                    value_json="Grounded background differentiator",
                    source_tier=1,
                    extraction_method=ExtractionMethod.HUMAN,
                    confidence=0.9,
                    run_id=RunId(background_run_id),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    reuse_scope=ReuseScope.TENANT_PRIVATE,
                    workspace_id=scope.workspace_id,
                ),
            )
        background_request = fast_request.model_copy(
            update={
                "phase": CrawlPhase.BACKGROUND,
                "claim_run_id": background_run_id,
            }
        )
        background_version = await committer.commit(
            background_request,
            filled_fields={"client.differentiator"},
            # The catalog extractor was attempted but failed ambiguously. The exact fast claim
            # remains a member through the marker's base-version edge; no claim body is copied.
            attempted_fields={"client.differentiator", "client.product_catalog"},
        )
        assert background_version == 2
        async with transaction() as conn:
            claims = await read_client_kb_claims(
                conn,
                scope.client_entity_id,
                workspace_id=scope.workspace_id,
                version=background_version,
            )
            marker = (
                await conn.execute(
                    text(
                        "SELECT value_json FROM claim WHERE workspace_id=:workspace_id "
                        "AND run_id=:run_id AND field_key='client.kb_version'"
                    ),
                    {"workspace_id": scope.workspace_id, "run_id": background_run_id},
                )
            ).scalar_one()
        assert set(claims) >= {"client.product_catalog", "client.differentiator"}
        assert claims["client.product_catalog"].run_id == RunId(scope.claim_run_id)
        assert claims["client.differentiator"].run_id == RunId(background_run_id)
        assert marker["base_version"] == 1

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_field_failures_and_ambiguous_model_calls_preserve_sibling_successes(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "partial-artifacts")
        scope = await _seed_scope(storage)
        gateway = _Gateway(
            invalid_fields=frozenset({"client.pricing_posture"}),
            raising_fields=frozenset({"client.market_reputation"}),
        )
        materializer = GroundedOfficialSiteMaterializer(
            gateway=gateway,  # type: ignore[arg-type]
            storage=storage,
            extraction_concurrency=4,
        )
        try:
            result = await materializer.materialize(_request(scope, model="openai/gpt-5.6-terra"))
            assert set(result.failed_fields) == {
                "client.pricing_posture",
                "client.market_reputation",
            }
            assert "client.product" in result.filled_fields
            assert "client.customer" in result.filled_fields
            calls = len(gateway.calls)
            replay = await materializer.materialize(_request(scope, model="openai/gpt-5.6-terra"))
            assert replay == result
            assert len(gateway.calls) == calls
            async with transaction() as conn:
                states = dict(
                    (
                        await conn.execute(
                            text(
                                "SELECT field_key, state FROM official_site_extraction_operation "
                                "WHERE workspace_id = :workspace_id "
                                "AND field_key IN ('client.pricing_posture', "
                                "'client.market_reputation')"
                            ),
                            {"workspace_id": scope.workspace_id},
                        )
                    ).all()
                )
            assert states == {
                "client.pricing_posture": "failed",
                "client.market_reputation": "spend_unknown",
            }
        finally:
            await _cleanup(scope)

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_known_terminal_gateway_response_is_failed_and_costed_without_recall(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "known-terminal-artifacts")
        scope = await _seed_scope(storage)
        gateway = _Gateway(terminal_failure_fields=frozenset({"client.product_catalog"}))
        materializer = GroundedOfficialSiteMaterializer(
            gateway=gateway,  # type: ignore[arg-type]
            storage=storage,
            extraction_concurrency=4,
        )
        try:
            result = await materializer.materialize(_request(scope))
            assert "client.product_catalog" in result.failed_fields
            calls = len(gateway.calls)
            replay = await materializer.materialize(_request(scope))
            assert replay == result
            assert len(gateway.calls) == calls
            async with transaction() as conn:
                row = (
                    (
                        await conn.execute(
                            text(
                                "SELECT state, failure_code, answering_model_id, prompt_tokens, "
                                "completion_tokens, cost_cents FROM "
                                "official_site_extraction_operation "
                                "WHERE workspace_id=:workspace_id "
                                "AND field_key='client.product_catalog'"
                            ),
                            {"workspace_id": scope.workspace_id},
                        )
                    )
                    .mappings()
                    .one()
                )
            assert dict(row) == {
                "state": "failed",
                "failure_code": "gateway_no_output_max_output_tokens",
                "answering_model_id": "openai/gpt-5.6-luna",
                "prompt_tokens": 321,
                "completion_tokens": 1_024,
                "cost_cents": Decimal("1.75"),
            }
        finally:
            await _cleanup(scope)

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())
