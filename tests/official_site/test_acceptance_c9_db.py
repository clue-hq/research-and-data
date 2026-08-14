"""C9 cross-slice adversarial acceptance over a real isolated PostgreSQL database."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from tests.db.conftest import run_async
from tests.official_site.test_acquisition_c4_db import (
    _cleanup_scope as _cleanup_c4_scope,
)
from tests.official_site.test_acquisition_c4_db import (
    _CountingFetcher,
)
from tests.official_site.test_acquisition_c4_db import (
    _create_run as _create_c4_run,
)
from tests.official_site.test_acquisition_c4_db import (
    _request as _c4_request,
)
from tests.official_site.test_acquisition_c4_db import (
    _seed_scope as _seed_c4_scope,
)
from tests.official_site.test_coordinator_c5_db import (
    _PUBLIC_IP,
    _phase_request,
    _ScenarioFetcher,
    _url_policy,
)
from tests.official_site.test_coordinator_c5_db import (
    _cleanup_scope as _cleanup_c5_scope,
)
from tests.official_site.test_coordinator_c5_db import (
    _config as _c5_config,
)
from tests.official_site.test_coordinator_c5_db import (
    _create_run as _create_c5_run,
)
from tests.official_site.test_coordinator_c5_db import (
    _seed_scope as _seed_c5_scope,
)
from tests.official_site.test_materialization_c7_db import (
    _Gateway,
)
from tests.official_site.test_materialization_c7_db import (
    _request as _c7_request,
)
from tests.official_site.test_materialization_c7_db import (
    _seed_scope as _seed_c7_scope,
)

from clue_db import db_lifespan, transaction
from clue_research.official_site import (
    AcquisitionFenceLostError,
    ArtifactRef,
    AttemptDisposition,
    AttemptOutcome,
    ClaimNextRequest,
    ClaimReconciliationRequest,
    ConcurrentCrawlCoordinator,
    CostKind,
    CrawlPageState,
    CrawlPhase,
    CrawlSafetyPolicy,
    DurablePageAcquirer,
    FetchAttemptState,
    GroundedOfficialSiteMaterializer,
    OfficialSiteArtifactStore,
    OfficialSiteDiscoveryPolicy,
    PageFetcherCapabilities,
    PageFetchRequest,
    PageFetchResult,
    PostgresCrawlRepository,
    ProviderResultMetadata,
    RetryClass,
    SpendStatus,
    StaticAddressResolver,
    StaticRobotsAuthorizer,
)
from clue_storage import FsStorage

pytestmark = pytest.mark.usefixtures("require_official_site_db")


class _RejectDispatchRepository:
    """Crash/fence double: preparation commits, but dispatch ownership is lost."""

    def __init__(self, delegate: PostgresCrawlRepository) -> None:
        self.delegate = delegate

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    async def mark_attempt_dispatched(self, *_args: object, **_kwargs: object) -> bool:
        return False


class _RecordingLookup:
    capabilities = PageFetcherCapabilities(
        provider_key="fixture",
        supports_operation_lookup=True,
        supports_idempotency_key=True,
        reports_redirect_chain=True,
        reports_outgoing_links=True,
        reports_actual_cost=True,
        reports_provider_receipt=True,
        proves_no_spend_before_dispatch=False,
    )

    def __init__(self, result: PageFetchResult) -> None:
        self.result = result
        self.provider_request_ids: list[str | None] = []

    async def lookup_operation(
        self,
        request: PageFetchRequest,
        *,
        provider_request_id: str | None,
    ) -> PageFetchResult:
        assert request.requested_url
        self.provider_request_ids.append(provider_request_id)
        return self.result


def test_crash_before_dispatch_never_calls_the_provider(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_c4_scope(conn)
                base = PostgresCrawlRepository()
                run_id = await _create_c4_run(
                    base,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=("https://example.com/",),
                )
                lease = await base.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="dispatch-fence",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=90,
                    )
                )
                assert lease is not None
                fetcher = _CountingFetcher()
                with pytest.raises(AcquisitionFenceLostError, match="before provider dispatch"):
                    await DurablePageAcquirer(
                        repository=_RejectDispatchRepository(base),
                        artifacts=OfficialSiteArtifactStore(
                            storage=FsStorage(tmp_path / "before-dispatch")
                        ),
                        fetcher=fetcher,
                    ).acquire(
                        lease,
                        _c4_request(lease.requested_url, operation_key=f"c9:{run_id}:dispatch"),
                    )
                assert fetcher.calls == 0
                async with engine.connect() as conn:
                    assert (
                        await conn.execute(
                            text(
                                "SELECT state FROM official_site_fetch_attempt "
                                "WHERE crawl_run_id = :run_id"
                            ),
                            {"run_id": run_id},
                        )
                    ).scalar_one() == "prepared"
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_c4_scope(conn, workspace_id)

    run_async(scenario())


def test_same_url_in_a_later_run_is_independently_fetchable(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, first_recon = await _seed_c4_scope(conn)
                    second_recon = uuid4()
                    await conn.execute(
                        text(
                            """
                            INSERT INTO recon_run (
                                id, workspace_id, brand_id, dedupe_hash, dedupe_expires_at,
                                fast_run_id, background_run_id, fast_budget_cents,
                                background_budget_cents, recipe_version, skill_version
                            ) VALUES (
                                :id, :workspace_id, :brand_id, :dedupe_hash,
                                now() + interval '1 hour', :fast_run_id, :background_run_id,
                                0, 0, 'c9-v1', 'c9-v1'
                            )
                            """
                        ),
                        {
                            "id": second_recon,
                            "workspace_id": workspace_id,
                            "brand_id": brand_id,
                            "dedupe_hash": hashlib.sha256(str(second_recon).encode()).hexdigest(),
                            "fast_run_id": uuid4(),
                            "background_run_id": uuid4(),
                        },
                    )
                repository = PostgresCrawlRepository()
                url = "https://example.com/pricing"
                run_ids = (
                    await _create_c4_run(
                        repository,
                        workspace_id=workspace_id,
                        brand_id=brand_id,
                        recon_run_id=first_recon,
                        urls=(url,),
                    ),
                    await _create_c4_run(
                        repository,
                        workspace_id=workspace_id,
                        brand_id=brand_id,
                        recon_run_id=second_recon,
                        urls=(url,),
                    ),
                )
                assert run_ids[0] != run_ids[1]
                fetcher = _CountingFetcher(body=b"same fresh official page")
                artifacts = OfficialSiteArtifactStore(storage=FsStorage(tmp_path / "later-run"))
                for index, run_id in enumerate(run_ids):
                    lease = await repository.claim_next(
                        ClaimNextRequest(
                            workspace_id=workspace_id,
                            crawl_run_id=run_id,
                            worker_id=f"freshness-{index}",
                            eligible_phase=CrawlPhase.FAST,
                            lease_ttl_seconds=90,
                        )
                    )
                    assert lease is not None and lease.fetch_key == url
                    completed = await DurablePageAcquirer(
                        repository=repository,
                        artifacts=artifacts,
                        fetcher=fetcher,
                    ).acquire(
                        lease,
                        _c4_request(url, operation_key=f"c9:{run_id}:freshness"),
                    )
                    assert completed.page_completed
                assert fetcher.calls == 2
                async with engine.connect() as conn:
                    assert (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM official_site_page_snapshot "
                                "WHERE crawl_run_id = ANY(CAST(:run_ids AS uuid[]))"
                            ),
                            {"run_ids": list(run_ids)},
                        )
                    ).scalar_one() == 2
                    # Content-addressing deduplicates the immutable bytes, never the two run/URL
                    # provenance records or the legitimate later freshness acquisition.
                    assert (
                        await conn.execute(
                            text("SELECT count(*) FROM artifact WHERE workspace_id = :workspace"),
                            {"workspace": workspace_id},
                        )
                    ).scalar_one() == 1
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_c4_scope(conn, workspace_id)

    run_async(scenario())


def test_stale_generation_rejects_every_worker_publication() -> None:
    async def scenario() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_c4_scope(conn)
                repository = PostgresCrawlRepository()
                run_id = await _create_c4_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=("https://example.com/",),
                )
                stale = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="stale",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=90,
                    )
                )
                assert stale is not None
                attempt = await repository.begin_attempt(
                    stale,
                    provider_key="fixture",
                    operation_key=f"c9:{run_id}:stale",
                )
                assert await repository.mark_attempt_dispatched(stale, attempt)
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "UPDATE official_site_crawl_page "
                            "SET lease_acquired_at = now() - interval '2 minutes', "
                            "lease_expires_at = now() - interval '1 minute' WHERE id = :page_id"
                        ),
                        {"page_id": stale.page_id},
                    )
                reclaimed = await repository.reclaim_expired_leases(
                    workspace_id=workspace_id,
                    crawl_run_id=run_id,
                )
                assert reclaimed.moved_to_reconciliation_pending == 1
                fresh = await repository.claim_reconciliation(
                    ClaimReconciliationRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="fresh",
                        lease_ttl_seconds=90,
                    )
                )
                assert fresh is not None
                assert fresh.lease.lease_generation == stale.lease_generation + 1

                result = ProviderResultMetadata(
                    provider_key="fixture",
                    provider_request_id="stale-receipt",
                    requested_url=stale.requested_url,
                    final_url=stale.requested_url,
                    provider_status="ok",
                    http_status=200,
                    media_type="text/plain",
                    size_bytes=1,
                    fetched_at=datetime.now(UTC),
                    cost_cents=Decimal("1"),
                    cost_kind=CostKind.ACTUAL,
                    spend_status=SpendStatus.SPEND_CONFIRMED,
                    retry_class=RetryClass.SUCCESS,
                )
                artifact = ArtifactRef(
                    workspace_id=workspace_id,
                    artifact_key=f"{workspace_id}/{'a' * 64}",
                    content_sha256="a" * 64,
                    size_bytes=1,
                )
                assert not await repository.renew_lease(stale, lease_ttl_seconds=90)
                assert not await repository.mark_attempt_dispatched(stale, attempt)
                assert not await repository.record_provider_result(stale, attempt, result)
                assert (
                    await repository.persist_snapshot(stale, attempt, artifact, result, ()) is None
                )
                assert not await repository.complete_page(stale, snapshot_id=uuid4())
                assert not await repository.disposition_attempt(
                    stale,
                    attempt,
                    AttemptOutcome(
                        disposition=AttemptDisposition.QUARANTINE,
                        attempt_state=FetchAttemptState.QUARANTINED,
                        page_state=CrawlPageState.QUARANTINED,
                        reason_code="stale_must_not_publish",
                    ),
                )
                async with engine.connect() as conn:
                    page = (
                        await conn.execute(
                            text(
                                "SELECT lease_owner, lease_generation, state "
                                "FROM official_site_crawl_page WHERE id = :page_id"
                            ),
                            {"page_id": stale.page_id},
                        )
                    ).one()
                assert page == ("fresh", fresh.lease.lease_generation, "reconciliation_pending")
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_c4_scope(conn, workspace_id)

    run_async(scenario())


@pytest.mark.parametrize(
    "outcome",
    ("valid", "external", "oversize", "requested_mismatch", "provider_mismatch"),
)
def test_reconciliation_reuses_receipt_and_revalidates_provider_result(
    tmp_path: Path, outcome: str
) -> None:
    async def scenario() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_c5_scope(conn)
                config = _c5_config(workers=1, per_host=1).model_copy(
                    update={"max_response_bytes": 5}
                )
                repository = PostgresCrawlRepository()
                root = "https://example.com/"
                run_id = await _create_c5_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=(root,),
                    config=config,
                )
                lease = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="ambiguous",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=3,
                    )
                )
                assert lease is not None
                attempt = await repository.begin_attempt(
                    lease,
                    provider_key="fixture",
                    operation_key=f"c9:{run_id}:lookup",
                )
                assert await repository.mark_attempt_dispatched(lease, attempt)
                original_receipt = "charged-provider-receipt"
                ambiguous = ProviderResultMetadata(
                    provider_key="fixture",
                    provider_request_id=original_receipt,
                    requested_url=root,
                    final_url=None,
                    provider_status="provider_outcome_unknown",
                    fetched_at=datetime.now(UTC),
                    cost_kind=CostKind.NONE,
                    spend_status=SpendStatus.SPEND_UNKNOWN,
                    retry_class=RetryClass.AMBIGUOUS,
                )
                assert await repository.record_provider_result(lease, attempt, ambiguous)

                body = b"safe" if outcome != "oversize" else b"123456"
                final_url = root if outcome != "external" else "https://evil.test/steal"
                lookup = _RecordingLookup(
                    PageFetchResult(
                        provider_key=(
                            "forged-provider" if outcome == "provider_mismatch" else "fixture"
                        ),
                        provider_request_id="reconciled-receipt",
                        requested_url=(
                            "https://evil.test/forged-request"
                            if outcome == "requested_mismatch"
                            else root
                        ),
                        final_url=final_url,
                        provider_status="lookup_succeeded",
                        http_status=200,
                        content=body,
                        media_type="text/html",
                        fetched_at=datetime.now(UTC),
                        cost_cents=Decimal("1"),
                        cost_kind=CostKind.ACTUAL,
                        spend_status=SpendStatus.SPEND_CONFIRMED,
                        retry_class=RetryClass.SUCCESS,
                    )
                )
                fetcher = _ScenarioFetcher()
                policy = _url_policy(root)
                coordinator = ConcurrentCrawlCoordinator(
                    repository=repository,
                    artifacts=OfficialSiteArtifactStore(
                        storage=FsStorage(tmp_path / f"reconciliation-{outcome}")
                    ),
                    fetcher=fetcher,
                    discovery_policy=OfficialSiteDiscoveryPolicy(url_policy=policy),
                    url_policy=policy,
                    resolver=StaticAddressResolver({"example.com": (_PUBLIC_IP,)}),
                    safety=CrawlSafetyPolicy(max_response_bytes=5, max_redirects=5),
                    robots=StaticRobotsAuthorizer(policy_version="robots-v1"),
                    operation_lookup=lookup,
                )
                phase = await coordinator.run_phase(
                    _phase_request(workspace_id, run_id, config, idle_polls=4)
                )
                assert phase.reconciliation_claims == 1
                assert fetcher.calls == []
                assert lookup.provider_request_ids == [original_receipt]
                progress = await repository.read_progress(
                    workspace_id=workspace_id,
                    crawl_run_id=run_id,
                )
                async with engine.connect() as conn:
                    snapshots = (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM official_site_page_snapshot "
                                "WHERE crawl_run_id = :run_id"
                            ),
                            {"run_id": run_id},
                        )
                    ).scalar_one()
                if outcome == "valid":
                    assert progress.fetched == 1 and snapshots == 1
                else:
                    assert progress.quarantined == 1 and snapshots == 0
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_c5_scope(conn, workspace_id)

    run_async(scenario())


def test_robots_refusal_is_terminal_visible_and_provider_free(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_c5_scope(conn)
                config = _c5_config(workers=1, per_host=1)
                repository = PostgresCrawlRepository()
                root = "https://example.com/private"
                run_id = await _create_c5_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=(root,),
                    config=config,
                )
                fetcher = _ScenarioFetcher()
                policy = _url_policy(root)
                result = await ConcurrentCrawlCoordinator(
                    repository=repository,
                    artifacts=OfficialSiteArtifactStore(
                        storage=FsStorage(tmp_path / "robots-refusal")
                    ),
                    fetcher=fetcher,
                    discovery_policy=OfficialSiteDiscoveryPolicy(url_policy=policy),
                    url_policy=policy,
                    resolver=StaticAddressResolver({"example.com": (_PUBLIC_IP,)}),
                    safety=CrawlSafetyPolicy(max_response_bytes=1_000_000, max_redirects=5),
                    robots=StaticRobotsAuthorizer(policy_version="robots-v1", allowed=False),
                ).run_phase(_phase_request(workspace_id, run_id, config, idle_polls=4))
                assert result.ordinary_claims == 1
                assert fetcher.calls == []
                progress = await repository.read_progress(
                    workspace_id=workspace_id,
                    crawl_run_id=run_id,
                )
                assert progress.refused == 1
                async with engine.connect() as conn:
                    state, reason = (
                        await conn.execute(
                            text(
                                "SELECT state, terminal_reason FROM official_site_crawl_page "
                                "WHERE crawl_run_id = :run_id"
                            ),
                            {"run_id": run_id},
                        )
                    ).one()
                assert (state, reason) == ("refused", "robots_refused")
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_c5_scope(conn, workspace_id)

    run_async(scenario())


def test_missing_categories_commit_empty_without_gateway_calls(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "missing-categories")
        scope = await _seed_c7_scope(storage)
        async with transaction() as conn:
            await conn.execute(
                text(
                    "UPDATE official_site_crawl_page "
                    "SET priority_reason_json = '[\"category:product\"]'::jsonb "
                    "WHERE crawl_run_id = :run_id"
                ),
                {"run_id": scope.crawl_run_id},
            )
        gateway = _Gateway()
        result = await GroundedOfficialSiteMaterializer(
            gateway=gateway,  # type: ignore[arg-type]
            storage=storage,
            extraction_concurrency=4,
        ).materialize(_c7_request(scope))
        assert set(result.filled_fields) == {
            "client.value_prop",
            "client.product",
            "client.differentiator",
        }
        # Eleven category/field operations run, but the result reports unique fields and a field
        # filled by product evidence does not remain globally empty merely because the separate
        # company-context operation had no eligible page. Six of nine unique fields are empty.
        assert len(result.empty_fields) == 6
        assert result.failed_fields == ()
        assert len(gateway.calls) == 3
        async with transaction() as conn:
            states = dict(
                (
                    await conn.execute(
                        text(
                            "SELECT state, count(*) FROM official_site_extraction_operation "
                            "WHERE workspace_id = :workspace GROUP BY state"
                        ),
                        {"workspace": scope.workspace_id},
                    )
                ).all()
            )
        assert states == {"empty": 8, "materialized": 3}

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_complete_retention_reach_covers_every_table_blob_and_claim(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "complete-reach")
        scope = await _seed_c7_scope(storage)
        observation_id = uuid4()
        edge_id = uuid4()
        alias_id = uuid4()
        async with transaction() as conn:
            pages = list(
                (
                    await conn.execute(
                        text(
                            "SELECT official_site_crawl_page.id, "
                            "official_site_crawl_page.fetch_key, snapshot.artifact_key "
                            "FROM official_site_crawl_page "
                            "LEFT JOIN official_site_page_snapshot snapshot "
                            "ON snapshot.id = official_site_crawl_page.latest_snapshot_id "
                            "WHERE official_site_crawl_page.crawl_run_id = :run_id "
                            "ORDER BY official_site_crawl_page.fetch_key"
                        ),
                        {"run_id": scope.crawl_run_id},
                    )
                ).all()
            )
            source, target = pages[0], pages[1]
            await conn.execute(
                text(
                    """
                    INSERT INTO official_site_url_observation (
                        id, workspace_id, crawl_run_id, page_id, parser_replay_key,
                        discovered_url, discovered_via, source_page_id, graph_depth,
                        policy_outcome
                    ) VALUES (
                        :id, :workspace, :run_id, :page_id, :replay, :url,
                        'link', :source_page, 1, 'admitted'
                    )
                    """
                ),
                {
                    "id": observation_id,
                    "workspace": scope.workspace_id,
                    "run_id": scope.crawl_run_id,
                    "page_id": target.id,
                    "source_page": source.id,
                    "replay": f"c9:{observation_id}",
                    "url": target.fetch_key,
                },
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO official_site_link_edge (
                        id, workspace_id, crawl_run_id, from_page_id, to_page_id,
                        discovered_url, link_relation
                    ) VALUES (
                        :id, :workspace, :run_id, :source, :target, :url, 'canonical_hint'
                    )
                    """
                ),
                {
                    "id": edge_id,
                    "workspace": scope.workspace_id,
                    "run_id": scope.crawl_run_id,
                    "source": source.id,
                    "target": target.id,
                    "url": target.fetch_key,
                },
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO official_site_alias_observation (
                        id, workspace_id, crawl_run_id, source_page_id, alias_url,
                        kind, verification_status, target_page_id
                    ) VALUES (
                        :id, :workspace, :run_id, :source, :url,
                        'canonical_hint', 'conflicting', :target
                    )
                    """
                ),
                {
                    "id": alias_id,
                    "workspace": scope.workspace_id,
                    "run_id": scope.crawl_run_id,
                    "source": source.id,
                    "target": target.id,
                    "url": target.fetch_key,
                },
            )

        result = await GroundedOfficialSiteMaterializer(
            gateway=_Gateway(),  # type: ignore[arg-type]
            storage=storage,
            extraction_concurrency=4,
        ).materialize(_c7_request(scope))
        assert len(result.claim_ids) == 11
        # Model the crash boundary after a deterministic claim insert but before the operation's
        # terminal claim-id publication. Retention reach must follow the claim's durable operation
        # reference as well as the eventually consistent summary array.
        async with transaction() as conn:
            stranded = (
                await conn.execute(
                    text(
                        """
                        UPDATE official_site_extraction_operation
                        SET state = 'response_retained', claim_ids_json = '[]'::jsonb,
                            completed_at = NULL
                        WHERE workspace_id = :workspace
                          AND :claim_id IN (
                              SELECT jsonb_array_elements_text(claim_ids_json)
                          )
                        RETURNING id
                        """
                    ),
                    {
                        "workspace": scope.workspace_id,
                        "claim_id": str(result.claim_ids[0]),
                    },
                )
            ).scalar_one()
            assert stranded is not None
        reach = await OfficialSiteArtifactStore(storage=storage).evidence_reach(
            workspace_id=scope.workspace_id,
            crawl_run_id=scope.crawl_run_id,
        )
        assert reach.crawl_run_ids == (scope.crawl_run_id,)
        assert len(reach.page_ids) == 4
        assert reach.observation_ids == (observation_id,)
        assert reach.link_edge_ids == (edge_id,)
        assert reach.alias_observation_ids == (alias_id,)
        assert reach.checkpoint_ids == (scope.checkpoint_id,)
        assert len(reach.attempt_ids) == len(reach.snapshot_ids) == 4
        assert len(reach.extraction_operation_ids) == 11
        assert set(reach.claim_ids) == set(result.claim_ids)

        async with transaction() as conn:
            rows = list(
                (
                    await conn.execute(
                        text(
                            "SELECT id, artifact_key, source_operation_ref, "
                            "source_snapshot_ref, source_request_ref, source_tier "
                            "FROM claim WHERE workspace_id = :workspace "
                            "AND source_key = 'official_site'"
                        ),
                        {"workspace": scope.workspace_id},
                    )
                ).all()
            )
            response_keys = set(
                (
                    await conn.execute(
                        text(
                            "SELECT response_artifact_key "
                            "FROM official_site_extraction_operation "
                            "WHERE workspace_id = :workspace"
                        ),
                        {"workspace": scope.workspace_id},
                    )
                ).scalars()
            )
        for row in rows:
            assert (
                UUID(row.source_operation_ref.rsplit(":", 1)[1]) in reach.extraction_operation_ids
            )
            assert UUID(row.source_snapshot_ref.rsplit(":", 1)[1]) in reach.snapshot_ids
            assert UUID(row.source_request_ref.rsplit(":", 1)[1]) in reach.attempt_ids
            assert row.artifact_key in reach.artifact_keys
            assert row.source_tier == 2
        assert response_keys <= set(reach.artifact_keys)
        # The conflicting canonical hint did not collapse different captured bytes.
        assert source.artifact_key != target.artifact_key
        assert source.artifact_key in reach.artifact_keys
        assert target.artifact_key in reach.artifact_keys

        outside = await OfficialSiteArtifactStore(storage=storage).evidence_reach(
            workspace_id=f"other-{scope.workspace_id}"
        )
        assert not any(
            (
                outside.crawl_run_ids,
                outside.page_ids,
                outside.observation_ids,
                outside.link_edge_ids,
                outside.alias_observation_ids,
                outside.attempt_ids,
                outside.snapshot_ids,
                outside.checkpoint_ids,
                outside.extraction_operation_ids,
                outside.claim_ids,
                outside.artifact_keys,
            )
        )

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())
