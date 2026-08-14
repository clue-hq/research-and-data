"""PostgreSQL frontier and ledger for durable Stage-0 official-site crawling (C1).

Every public method is one database transaction. PostgreSQL time owns deadlines and leases;
``lease_generation`` plus worker identity fences every completion; workspace scope appears in
every read and write predicate. Provider I/O and URL-policy decisions remain outside this module.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import ConnFactory, transaction
from clue_research.official_site.contracts import (
    AliasKind,
    AliasVerificationStatus,
    ArtifactRef,
    AttemptOutcome,
    ClaimNextRequest,
    ClaimPersistenceRequest,
    ClaimReconciliationRequest,
    CorpusCheckpointRef,
    CrawlEligibility,
    CrawlLease,
    CrawlPageState,
    CrawlPhase,
    CrawlProgress,
    CrawlRunCreate,
    CrawlRunRef,
    CrawlRunStatus,
    DiscoveredVia,
    DiscoveryBatch,
    DiscoveryBatchResult,
    FetchAttemptRef,
    FetchAttemptState,
    LinkObservation,
    LinkRelation,
    PageSnapshotRef,
    PersistenceClaim,
    PolicyOutcome,
    ProviderResultMetadata,
    ReclaimResult,
    ReconciliationClaim,
    RetryClass,
    compute_snapshot_set_sha256,
)
from clue_research.official_site.models import (
    CrawlCapacityExceededError,
    CrawlReplayConflictError,
    CrawlRunNotFoundError,
    CrawlStateConflictError,
)
from clue_research.official_site.transitions import (
    ATTEMPT_TRANSITIONS,
    PAGE_TRANSITIONS,
    RUN_TRANSITIONS,
    allows_transition,
)

_ACTIVE_LEASE_STATES = (
    CrawlPageState.LEASED.value,
    CrawlPageState.PROVIDER_STARTED.value,
    CrawlPageState.RECONCILIATION_PENDING.value,
    CrawlPageState.PERSISTENCE_PENDING.value,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _row(result: Any) -> Mapping[str, Any] | None:
    return cast(Mapping[str, Any] | None, result.mappings().first())


def _host(fetch_key: str) -> str:
    host = urlsplit(fetch_key).hostname
    if not host:
        raise CrawlStateConflictError("admitted fetch key has no hostname")
    return host.lower()


def _lease_from_row(row: Mapping[str, Any], *, phase: CrawlPhase) -> CrawlLease:
    return CrawlLease(
        workspace_id=row["workspace_id"],
        crawl_run_id=row["crawl_run_id"],
        page_id=row["id"],
        worker_id=row["lease_owner"],
        lease_generation=row["lease_generation"],
        phase=phase,
        fetch_key=row["fetch_key"],
        requested_url=row["representative_requested_url"],
        host=row["host"],
        graph_depth=row["graph_depth"],
        expires_at=row["lease_expires_at"],
    )


def _attempt_from_row(row: Mapping[str, Any]) -> FetchAttemptRef:
    return FetchAttemptRef(
        fetch_attempt_id=row["id"],
        workspace_id=row["workspace_id"],
        crawl_run_id=row["crawl_run_id"],
        page_id=row["page_id"],
        attempt_number=row["attempt_number"],
        lease_generation=row["lease_generation"],
        operation_key=row["operation_key"],
        provider_key=row["provider_key"],
        state=FetchAttemptState(row["state"]),
    )


def _observation_replay_key(batch: DiscoveryBatch, index: int) -> str:
    payload = {
        "crawl_run_id": str(batch.crawl_run_id),
        "batch": [observation.model_dump(mode="json") for observation in batch.observations],
        "ordinal": index,
    }
    # The C0 seam has no parser operation ID. The canonical batch plus ordinal is the strongest
    # available replay identity: an exact batch replay collapses; identical links at different
    # positions and the same link in a materially different batch retain separate provenance.
    return hashlib.sha256(_json(payload).encode()).hexdigest()


def _merge_eligibility(old: str, new: CrawlEligibility) -> str:
    if old == new.value:
        return old
    if CrawlEligibility.BOTH.value in {old, new.value}:
        return CrawlEligibility.BOTH.value
    if {old, new.value} == {CrawlEligibility.FAST.value, CrawlEligibility.BACKGROUND.value}:
        return CrawlEligibility.BOTH.value
    if old == CrawlEligibility.REFUSED.value:
        return new.value
    return old


class PostgresCrawlRepository:
    """The C1 implementation of the frozen :class:`CrawlRepository` protocol."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def create_or_get_run(self, request: CrawlRunCreate) -> CrawlRunRef:
        config = request.config.model_dump(mode="json")
        async with self._conn_factory() as conn:
            await self._lock(conn, request.recon_run_id, "create")
            created_row = _row(
                await conn.execute(
                    text(
                        """
                        INSERT INTO official_site_crawl_run (
                            id, workspace_id, brand_id, client_entity_id, recon_run_id,
                            root_discovered_url, root_fetch_key, allowed_registrable_domain,
                            fast_claim_deadline_at, overall_page_ceiling, fast_page_ceiling,
                            provider_policy_version, url_policy_version, robots_policy_version,
                            config_json
                        ) VALUES (
                            :id, :workspace_id, :brand_id, :client_entity_id, :recon_run_id,
                            :root_discovered_url, :root_fetch_key, :allowed_domain,
                            now() + make_interval(secs => :fast_deadline_seconds),
                            :overall_page_ceiling, :fast_page_ceiling, :provider_policy_version,
                            :url_policy_version, :robots_policy_version, CAST(:config_json AS jsonb)
                        )
                        ON CONFLICT (workspace_id, recon_run_id) DO NOTHING
                        RETURNING id, workspace_id, recon_run_id, status
                        """
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": request.workspace_id,
                        "brand_id": request.brand_id,
                        "client_entity_id": request.client_entity_id,
                        "recon_run_id": request.recon_run_id,
                        "root_discovered_url": request.root_discovered_url,
                        "root_fetch_key": request.root_fetch_key,
                        "allowed_domain": request.allowed_registrable_domain,
                        "fast_deadline_seconds": request.config.fast_deadline_seconds,
                        "overall_page_ceiling": request.config.total_page_ceiling,
                        "fast_page_ceiling": request.config.fast_page_ceiling,
                        "provider_policy_version": request.config.provider_policy_version,
                        "url_policy_version": request.config.url_policy_version,
                        "robots_policy_version": request.config.robots_policy_version,
                        "config_json": _json(config),
                    },
                )
            )
            if created_row is not None:
                return CrawlRunRef(
                    crawl_run_id=created_row["id"],
                    workspace_id=created_row["workspace_id"],
                    recon_run_id=created_row["recon_run_id"],
                    status=CrawlRunStatus(created_row["status"]),
                    created=True,
                )

            existing = _row(
                await conn.execute(
                    text(
                        """
                        SELECT * FROM official_site_crawl_run
                        WHERE workspace_id = :workspace_id AND recon_run_id = :recon_run_id
                        FOR UPDATE
                        """
                    ),
                    {
                        "workspace_id": request.workspace_id,
                        "recon_run_id": request.recon_run_id,
                    },
                )
            )
            if existing is None:  # pragma: no cover - protected by lock + conflict target
                raise CrawlRunNotFoundError("crawl run disappeared during idempotent creation")
            expected = {
                "brand_id": request.brand_id,
                "client_entity_id": request.client_entity_id,
                "root_discovered_url": request.root_discovered_url,
                "root_fetch_key": request.root_fetch_key,
                "allowed_registrable_domain": request.allowed_registrable_domain,
                "overall_page_ceiling": request.config.total_page_ceiling,
                "fast_page_ceiling": request.config.fast_page_ceiling,
                "provider_policy_version": request.config.provider_policy_version,
                "url_policy_version": request.config.url_policy_version,
                "robots_policy_version": request.config.robots_policy_version,
                "config_json": config,
            }
            if any(existing[key] != value for key, value in expected.items()):
                raise CrawlReplayConflictError(
                    "recon run already owns an official-site crawl with different immutable input"
                )
            return CrawlRunRef(
                crawl_run_id=existing["id"],
                workspace_id=existing["workspace_id"],
                recon_run_id=existing["recon_run_id"],
                status=CrawlRunStatus(existing["status"]),
                created=False,
            )

    async def record_discoveries(self, batch: DiscoveryBatch) -> DiscoveryBatchResult:
        observations_recorded = 0
        pages_created = 0
        pages_reprioritized = 0
        saved_links_reexpanded = 0
        shortened_fetched_pages: dict[UUID, int] = {}
        expanded_sources: dict[UUID, int] = {}
        async with self._conn_factory() as conn:
            run = await self._run(conn, batch.workspace_id, batch.crawl_run_id, lock=True)
            current_pages = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM official_site_crawl_page "
                            "WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id"
                        ),
                        {
                            "workspace_id": batch.workspace_id,
                            "crawl_run_id": batch.crawl_run_id,
                        },
                    )
                ).scalar_one()
            )

            for index, observation in enumerate(batch.observations):
                source_page: Mapping[str, Any] | None = None
                if observation.source_page_id is not None:
                    source_page = _row(
                        await conn.execute(
                            text(
                                """
                                SELECT * FROM official_site_crawl_page
                                WHERE id = :page_id AND workspace_id = :workspace_id
                                  AND crawl_run_id = :crawl_run_id
                                FOR UPDATE
                                """
                            ),
                            {
                                "page_id": observation.source_page_id,
                                "workspace_id": batch.workspace_id,
                                "crawl_run_id": batch.crawl_run_id,
                            },
                        )
                    )
                    if source_page is None:
                        raise CrawlStateConflictError(
                            "discovery source page is absent or outside the workspace/run"
                        )
                    if observation.discovered_via is DiscoveredVia.LINK:
                        parent_depth = source_page["graph_depth"]
                        if parent_depth is None and observation.graph_depth is not None:
                            raise CrawlStateConflictError(
                                "an unknown-depth source cannot assign link graph depth"
                            )
                        if (
                            parent_depth is not None
                            and observation.policy_outcome is PolicyOutcome.ADMITTED
                            and (
                                parent_depth >= run["max_graph_depth"]
                                or observation.graph_depth != parent_depth + 1
                            )
                        ):
                            raise CrawlStateConflictError(
                                "link discovery violates the run-pinned graph-depth policy"
                            )
                page: Mapping[str, Any] | None = None
                if observation.policy_outcome is PolicyOutcome.ADMITTED:
                    assert observation.fetch_key is not None
                    assert observation.fetch_key_hash is not None
                    page = _row(
                        await conn.execute(
                            text(
                                """
                                SELECT * FROM official_site_crawl_page
                                WHERE workspace_id = :workspace_id
                                  AND crawl_run_id = :crawl_run_id
                                  AND fetch_key_hash = :fetch_key_hash
                                  AND fetch_key = :fetch_key
                                FOR UPDATE
                                """
                            ),
                            {
                                "workspace_id": batch.workspace_id,
                                "crawl_run_id": batch.crawl_run_id,
                                "fetch_key_hash": observation.fetch_key_hash,
                                "fetch_key": observation.fetch_key,
                            },
                        )
                    )
                    if page is None:
                        if current_pages >= run["overall_page_ceiling"]:
                            raise CrawlCapacityExceededError(
                                "discovery batch exceeds the run-pinned page ceiling"
                            )
                        parked_unknown_link = (
                            observation.discovered_via is DiscoveredVia.LINK
                            and observation.graph_depth is None
                        )
                        page = _row(
                            await conn.execute(
                                text(
                                    """
                                    INSERT INTO official_site_crawl_page (
                                        id, workspace_id, crawl_run_id, fetch_key, fetch_key_hash,
                                        representative_requested_url, host, graph_depth, priority,
                                        priority_reason_json, eligibility, state, queued_at
                                    ) VALUES (
                                        :id, :workspace_id, :crawl_run_id, :fetch_key,
                                        :fetch_key_hash, :requested_url, :host, :graph_depth,
                                        :priority, CAST(:priority_reasons AS jsonb), :eligibility,
                                        :state, CASE WHEN :state = 'queued' THEN now() ELSE NULL END
                                    )
                                    RETURNING *
                                    """
                                ),
                                {
                                    "id": uuid4(),
                                    "workspace_id": batch.workspace_id,
                                    "crawl_run_id": batch.crawl_run_id,
                                    "fetch_key": observation.fetch_key,
                                    "fetch_key_hash": observation.fetch_key_hash,
                                    # A relative/raw discovered spelling remains on the URL
                                    # observation; acquisition always receives an absolute safe key.
                                    "requested_url": observation.fetch_key,
                                    "host": _host(observation.fetch_key),
                                    "graph_depth": observation.graph_depth,
                                    "priority": observation.priority,
                                    "priority_reasons": _json(
                                        sorted(set(observation.priority_reason))
                                    ),
                                    "eligibility": observation.eligibility.value,
                                    "state": (
                                        CrawlPageState.DISCOVERED.value
                                        if parked_unknown_link
                                        else CrawlPageState.QUEUED.value
                                    ),
                                },
                            )
                        )
                        assert page is not None
                        current_pages += 1
                        pages_created += 1
                    else:
                        old_depth = page["graph_depth"]
                        new_depth = old_depth
                        if observation.graph_depth is not None and (
                            old_depth is None or observation.graph_depth < old_depth
                        ):
                            new_depth = observation.graph_depth
                        new_priority = min(page["priority"], observation.priority)
                        new_eligibility = _merge_eligibility(
                            page["eligibility"], observation.eligibility
                        )
                        new_state = page["state"]
                        if (
                            page["state"] == CrawlPageState.DISCOVERED.value
                            and new_depth is not None
                        ):
                            new_state = CrawlPageState.QUEUED.value
                        new_reasons = sorted(
                            set(page["priority_reason_json"] or ())
                            | set(observation.priority_reason)
                        )
                        changed = (
                            new_depth != old_depth
                            or new_priority != page["priority"]
                            or new_eligibility != page["eligibility"]
                            or new_state != page["state"]
                            or new_reasons != list(page["priority_reason_json"] or ())
                        )
                        if changed:
                            await conn.execute(
                                text(
                                    """
                                    UPDATE official_site_crawl_page
                                    SET graph_depth = :graph_depth,
                                        priority = :priority,
                                        priority_reason_json = CAST(:priority_reasons AS jsonb),
                                        eligibility = :eligibility,
                                        state = :state,
                                        queued_at = CASE
                                            WHEN :state = 'queued' THEN COALESCE(queued_at, now())
                                            ELSE queued_at
                                        END,
                                        updated_at = now()
                                    WHERE id = :page_id AND workspace_id = :workspace_id
                                      AND crawl_run_id = :crawl_run_id
                                    """
                                ),
                                {
                                    "graph_depth": new_depth,
                                    "priority": new_priority,
                                    "priority_reasons": _json(new_reasons),
                                    "eligibility": new_eligibility,
                                    "state": new_state,
                                    "page_id": page["id"],
                                    "workspace_id": batch.workspace_id,
                                    "crawl_run_id": batch.crawl_run_id,
                                },
                            )
                            pages_reprioritized += 1
                        if (
                            page["state"] == CrawlPageState.FETCHED.value
                            and observation.graph_depth is not None
                            and (
                                page["expanded_min_depth"] is None
                                or observation.graph_depth < page["expanded_min_depth"]
                            )
                        ):
                            prior = shortened_fetched_pages.get(page["id"])
                            shortened_fetched_pages[page["id"]] = (
                                observation.graph_depth
                                if prior is None
                                else min(prior, observation.graph_depth)
                            )
                elif (
                    observation.discovered_via in {DiscoveredVia.REDIRECT, DiscoveredVia.CANONICAL}
                    and observation.fetch_key is not None
                    and observation.fetch_key_hash is not None
                ):
                    # Same-domain aliases never create or queue a page.  If their target already
                    # has a page node, retain the optional target pointer without merging identity.
                    page = _row(
                        await conn.execute(
                            text(
                                """
                                SELECT * FROM official_site_crawl_page
                                WHERE workspace_id = :workspace_id
                                  AND crawl_run_id = :crawl_run_id
                                  AND fetch_key_hash = :fetch_key_hash
                                  AND fetch_key = :fetch_key
                                """
                            ),
                            {
                                "workspace_id": batch.workspace_id,
                                "crawl_run_id": batch.crawl_run_id,
                                "fetch_key_hash": observation.fetch_key_hash,
                                "fetch_key": observation.fetch_key,
                            },
                        )
                    )

                inserted = await conn.execute(
                    text(
                        """
                        INSERT INTO official_site_url_observation (
                            id, workspace_id, crawl_run_id, page_id, parser_replay_key,
                            discovered_url, discovered_via, source_page_id, graph_depth,
                            link_text_bounded, sitemap_url, policy_outcome, policy_reason
                        ) VALUES (
                            :id, :workspace_id, :crawl_run_id, :page_id, :parser_replay_key,
                            :discovered_url, :discovered_via, :source_page_id, :graph_depth,
                            :link_text, :sitemap_url, :policy_outcome, :policy_reason
                        )
                        ON CONFLICT (crawl_run_id, parser_replay_key) DO NOTHING
                        """
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": batch.workspace_id,
                        "crawl_run_id": batch.crawl_run_id,
                        "page_id": page["id"] if page is not None else None,
                        "parser_replay_key": _observation_replay_key(batch, index),
                        "discovered_url": observation.discovered_url,
                        "discovered_via": observation.discovered_via.value,
                        "source_page_id": observation.source_page_id,
                        "graph_depth": observation.graph_depth,
                        "link_text": observation.link_text,
                        "sitemap_url": observation.sitemap_url,
                        "policy_outcome": observation.policy_outcome.value,
                        "policy_reason": observation.policy_reason,
                    },
                )
                if inserted.rowcount:
                    observations_recorded += 1

                if observation.source_page_id is not None and observation.discovered_via in {
                    DiscoveredVia.REDIRECT,
                    DiscoveredVia.CANONICAL,
                }:
                    kind = (
                        AliasKind.REDIRECT
                        if observation.discovered_via is DiscoveredVia.REDIRECT
                        else AliasKind.CANONICAL_HINT
                    )
                    if observation.fetch_key is not None:
                        verification = (
                            AliasVerificationStatus.VERIFIED_REDIRECT
                            if kind is AliasKind.REDIRECT
                            else AliasVerificationStatus.OBSERVED
                        )
                    elif observation.policy_reason and any(
                        marker in observation.policy_reason
                        for marker in (
                            "external_domain",
                            "subdomain_not_allowed",
                            "non_public_network_target",
                        )
                    ):
                        verification = AliasVerificationStatus.REJECTED_EXTERNAL
                    else:
                        verification = AliasVerificationStatus.CONFLICTING
                    await conn.execute(
                        text(
                            """
                            INSERT INTO official_site_alias_observation (
                                id, workspace_id, crawl_run_id, source_page_id, alias_url,
                                kind, verification_status, target_page_id
                            ) VALUES (
                                :id, :workspace_id, :crawl_run_id, :source_page_id, :alias_url,
                                :kind, :verification_status, :target_page_id
                            )
                            ON CONFLICT (crawl_run_id, source_page_id, alias_url, kind) DO NOTHING
                            """
                        ),
                        {
                            "id": uuid4(),
                            "workspace_id": batch.workspace_id,
                            "crawl_run_id": batch.crawl_run_id,
                            "source_page_id": observation.source_page_id,
                            "alias_url": observation.discovered_url,
                            "kind": kind.value,
                            "verification_status": verification.value,
                            "target_page_id": (
                                page["id"]
                                if page is not None
                                and verification is not AliasVerificationStatus.REJECTED_EXTERNAL
                                else None
                            ),
                        },
                    )

                if observation.source_page_id is not None and page is not None:
                    relation = {
                        DiscoveredVia.REDIRECT: LinkRelation.REDIRECT,
                        DiscoveredVia.CANONICAL: LinkRelation.CANONICAL_HINT,
                    }.get(observation.discovered_via, LinkRelation.ANCHOR)
                    await conn.execute(
                        text(
                            """
                            INSERT INTO official_site_link_edge (
                                id, workspace_id, crawl_run_id, from_page_id, to_page_id,
                                discovered_url, link_relation
                            ) VALUES (
                                :id, :workspace_id, :crawl_run_id, :from_page_id, :to_page_id,
                                :discovered_url, :link_relation
                            )
                            ON CONFLICT (
                                crawl_run_id, from_page_id, to_page_id,
                                discovered_url, link_relation
                            ) DO NOTHING
                            """
                        ),
                        {
                            "id": uuid4(),
                            "workspace_id": batch.workspace_id,
                            "crawl_run_id": batch.crawl_run_id,
                            "from_page_id": observation.source_page_id,
                            "to_page_id": page["id"],
                            "discovered_url": observation.discovered_url,
                            "link_relation": relation.value,
                        },
                    )

                if (
                    source_page is not None
                    and source_page["state"] == CrawlPageState.FETCHED.value
                    and observation.discovered_via is DiscoveredVia.LINK
                    and observation.graph_depth is not None
                ):
                    source_depth = observation.graph_depth - 1
                    prior = expanded_sources.get(source_page["id"])
                    expanded_sources[source_page["id"]] = (
                        source_depth if prior is None else min(prior, source_depth)
                    )

            for source_page_id, depth in expanded_sources.items():
                await conn.execute(
                    text(
                        """
                        UPDATE official_site_crawl_page
                        SET expanded_min_depth = CASE
                                WHEN expanded_min_depth IS NULL THEN :depth
                                ELSE LEAST(expanded_min_depth, :depth)
                            END,
                            updated_at = now()
                        WHERE id = :page_id AND workspace_id = :workspace_id
                          AND crawl_run_id = :crawl_run_id AND state = 'fetched'
                        """
                    ),
                    {
                        "depth": depth,
                        "page_id": source_page_id,
                        "workspace_id": batch.workspace_id,
                        "crawl_run_id": batch.crawl_run_id,
                    },
                )
            for page_id, depth in shortened_fetched_pages.items():
                saved_links_reexpanded += await self._reexpand_saved_links(
                    conn,
                    workspace_id=batch.workspace_id,
                    crawl_run_id=batch.crawl_run_id,
                    page_id=page_id,
                    graph_depth=depth,
                    max_graph_depth=int(run["max_graph_depth"]),
                )

        return DiscoveryBatchResult(
            observations_recorded=observations_recorded,
            page_nodes_created=pages_created,
            page_nodes_reprioritized=pages_reprioritized,
            saved_links_reexpanded=saved_links_reexpanded,
        )

    async def claim_next(self, request: ClaimNextRequest) -> CrawlLease | None:
        async with self._conn_factory() as conn:
            await self._lock(conn, request.crawl_run_id, "claim")
            await self._reclaim(conn, request.workspace_id, request.crawl_run_id)
            run = await self._run(conn, request.workspace_id, request.crawl_run_id)
            if request.eligible_phase is CrawlPhase.FAST:
                if run["status"] != CrawlRunStatus.FAST_ACTIVE.value:
                    return None
                deadline_open = bool(
                    (
                        await conn.execute(
                            text("SELECT now() < :deadline"),
                            {"deadline": run["fast_claim_deadline_at"]},
                        )
                    ).scalar_one()
                )
                if not deadline_open:
                    return None
                eligibility = (CrawlEligibility.FAST.value, CrawlEligibility.BOTH.value)
            else:
                if run["status"] != CrawlRunStatus.BACKGROUND_ACTIVE.value:
                    return None
                eligibility = (CrawlEligibility.BACKGROUND.value, CrawlEligibility.BOTH.value)

            active = int(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT count(*) FROM official_site_crawl_page
                            WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id
                              AND state = ANY(CAST(:states AS text[]))
                              AND lease_expires_at > now()
                            """
                        ),
                        {
                            "workspace_id": request.workspace_id,
                            "crawl_run_id": request.crawl_run_id,
                            "states": list(_ACTIVE_LEASE_STATES),
                        },
                    )
                ).scalar_one()
            )
            worker_cap = int(run["config_json"]["worker_concurrency"])
            if active >= worker_cap:
                return None

            page = _row(
                await conn.execute(
                    text(
                        """
                        SELECT candidate.*
                        FROM official_site_crawl_page AS candidate
                        WHERE candidate.workspace_id = :workspace_id
                          AND candidate.crawl_run_id = :crawl_run_id
                          AND candidate.state = 'queued'
                          AND candidate.eligibility = ANY(CAST(:eligibility AS text[]))
                          AND (
                              SELECT count(*)
                              FROM official_site_crawl_page AS active
                              WHERE active.crawl_run_id = candidate.crawl_run_id
                                AND active.host = candidate.host
                                AND active.state = ANY(CAST(:states AS text[]))
                                AND active.lease_expires_at > now()
                          ) < :host_cap
                        ORDER BY candidate.priority, candidate.graph_depth NULLS LAST,
                                 candidate.discovered_at, candidate.id
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                        """
                    ),
                    {
                        "workspace_id": request.workspace_id,
                        "crawl_run_id": request.crawl_run_id,
                        "eligibility": list(eligibility),
                        "states": list(_ACTIVE_LEASE_STATES),
                        "host_cap": int(run["config_json"]["per_host_concurrency"]),
                    },
                )
            )
            if page is None:
                return None
            leased = _row(
                await conn.execute(
                    text(
                        """
                        UPDATE official_site_crawl_page
                        SET state = 'leased', lease_owner = :worker_id,
                            lease_generation = lease_generation + 1,
                            lease_acquired_at = now(),
                            lease_expires_at = now() + make_interval(secs => :ttl),
                            updated_at = now()
                        WHERE id = :page_id AND workspace_id = :workspace_id
                          AND crawl_run_id = :crawl_run_id AND state = 'queued'
                        RETURNING *
                        """
                    ),
                    {
                        "worker_id": request.worker_id,
                        "ttl": request.lease_ttl_seconds,
                        "page_id": page["id"],
                        "workspace_id": request.workspace_id,
                        "crawl_run_id": request.crawl_run_id,
                    },
                )
            )
            return (
                _lease_from_row(leased, phase=request.eligible_phase)
                if leased is not None
                else None
            )

    async def claim_reconciliation(
        self, request: ClaimReconciliationRequest
    ) -> ReconciliationClaim | None:
        async with self._conn_factory() as conn:
            await self._lock(conn, request.crawl_run_id, "claim")
            await self._reclaim(conn, request.workspace_id, request.crawl_run_id)
            run = await self._run(conn, request.workspace_id, request.crawl_run_id)
            phase = self._recovery_phase(run["status"])
            if phase is None:
                return None
            pair = _row(
                await conn.execute(
                    text(
                        """
                        SELECT page.id AS page_pk, attempt.id AS attempt_pk
                        FROM official_site_crawl_page AS page
                        JOIN LATERAL (
                            SELECT candidate.id
                            FROM official_site_fetch_attempt AS candidate
                            WHERE candidate.workspace_id = page.workspace_id
                              AND candidate.crawl_run_id = page.crawl_run_id
                              AND candidate.page_id = page.id
                              AND candidate.state = 'spend_unknown'
                            ORDER BY candidate.attempt_number DESC
                            LIMIT 1
                        ) AS attempt ON true
                        WHERE page.workspace_id = :workspace_id
                          AND page.crawl_run_id = :crawl_run_id
                          AND page.state = 'reconciliation_pending'
                          AND page.lease_owner IS NULL
                        ORDER BY page.priority, page.discovered_at, page.id
                        FOR UPDATE OF page SKIP LOCKED
                        LIMIT 1
                        """
                    ),
                    {
                        "workspace_id": request.workspace_id,
                        "crawl_run_id": request.crawl_run_id,
                    },
                )
            )
            if pair is None:
                return None
            leased = _row(
                await conn.execute(
                    text(
                        """
                        UPDATE official_site_crawl_page
                        SET lease_owner = :worker_id, lease_generation = lease_generation + 1,
                            lease_acquired_at = now(),
                            lease_expires_at = now() + make_interval(secs => :ttl),
                            updated_at = now()
                        WHERE id = :page_id AND workspace_id = :workspace_id
                          AND crawl_run_id = :crawl_run_id
                          AND state = 'reconciliation_pending' AND lease_owner IS NULL
                        RETURNING *
                        """
                    ),
                    {
                        "worker_id": request.worker_id,
                        "ttl": request.lease_ttl_seconds,
                        "page_id": pair["page_pk"],
                        "workspace_id": request.workspace_id,
                        "crawl_run_id": request.crawl_run_id,
                    },
                )
            )
            attempt = _row(
                await conn.execute(
                    text("SELECT * FROM official_site_fetch_attempt WHERE id = :attempt_id"),
                    {"attempt_id": pair["attempt_pk"]},
                )
            )
            if leased is None or attempt is None:  # pragma: no cover - same transaction
                return None
            return ReconciliationClaim(
                lease=_lease_from_row(leased, phase=phase),
                attempt=_attempt_from_row(attempt),
            )

    async def claim_persistence(self, request: ClaimPersistenceRequest) -> PersistenceClaim | None:
        async with self._conn_factory() as conn:
            await self._lock(conn, request.crawl_run_id, "claim")
            await self._reclaim(conn, request.workspace_id, request.crawl_run_id)
            run = await self._run(conn, request.workspace_id, request.crawl_run_id)
            phase = self._recovery_phase(run["status"])
            if phase is None:
                return None
            pair = _row(
                await conn.execute(
                    text(
                        """
                        SELECT page.id AS page_pk, attempt.id AS attempt_pk
                        FROM official_site_crawl_page AS page
                        JOIN LATERAL (
                            SELECT candidate.id
                            FROM official_site_fetch_attempt AS candidate
                            WHERE candidate.workspace_id = page.workspace_id
                              AND candidate.crawl_run_id = page.crawl_run_id
                              AND candidate.page_id = page.id
                              AND candidate.state IN (
                                  'provider_succeeded', 'reconciled_succeeded'
                              )
                            ORDER BY candidate.attempt_number DESC
                            LIMIT 1
                        ) AS attempt ON true
                        WHERE page.workspace_id = :workspace_id
                          AND page.crawl_run_id = :crawl_run_id
                          AND page.state = 'persistence_pending'
                          AND page.lease_owner IS NULL
                        ORDER BY page.priority, page.discovered_at, page.id
                        FOR UPDATE OF page SKIP LOCKED
                        LIMIT 1
                        """
                    ),
                    {
                        "workspace_id": request.workspace_id,
                        "crawl_run_id": request.crawl_run_id,
                    },
                )
            )
            if pair is None:
                return None
            leased = _row(
                await conn.execute(
                    text(
                        """
                        UPDATE official_site_crawl_page
                        SET lease_owner = :worker_id, lease_generation = lease_generation + 1,
                            lease_acquired_at = now(),
                            lease_expires_at = now() + make_interval(secs => :ttl),
                            updated_at = now()
                        WHERE id = :page_id AND workspace_id = :workspace_id
                          AND crawl_run_id = :crawl_run_id
                          AND state = 'persistence_pending' AND lease_owner IS NULL
                        RETURNING *
                        """
                    ),
                    {
                        "worker_id": request.worker_id,
                        "ttl": request.lease_ttl_seconds,
                        "page_id": pair["page_pk"],
                        "workspace_id": request.workspace_id,
                        "crawl_run_id": request.crawl_run_id,
                    },
                )
            )
            attempt = _row(
                await conn.execute(
                    text("SELECT * FROM official_site_fetch_attempt WHERE id = :attempt_id"),
                    {"attempt_id": pair["attempt_pk"]},
                )
            )
            if leased is None or attempt is None:  # pragma: no cover - same transaction
                return None
            return PersistenceClaim(
                lease=_lease_from_row(leased, phase=phase),
                attempt=_attempt_from_row(attempt),
            )

    async def renew_lease(self, lease: CrawlLease, *, lease_ttl_seconds: int) -> bool:
        if lease_ttl_seconds < 3:
            raise ValueError("lease_ttl_seconds must be at least 3")
        async with self._conn_factory() as conn:
            result = await conn.execute(
                text(
                    """
                    UPDATE official_site_crawl_page
                    SET lease_expires_at = now() + make_interval(secs => :ttl), updated_at = now()
                    WHERE id = :page_id AND workspace_id = :workspace_id
                      AND crawl_run_id = :crawl_run_id AND lease_owner = :worker_id
                      AND lease_generation = :lease_generation
                      AND state = ANY(CAST(:states AS text[]))
                      AND lease_expires_at > now()
                    """
                ),
                {
                    "ttl": lease_ttl_seconds,
                    "page_id": lease.page_id,
                    "workspace_id": lease.workspace_id,
                    "crawl_run_id": lease.crawl_run_id,
                    "worker_id": lease.worker_id,
                    "lease_generation": lease.lease_generation,
                    "states": list(_ACTIVE_LEASE_STATES),
                },
            )
            return result.rowcount == 1

    async def begin_attempt(
        self, lease: CrawlLease, *, provider_key: str, operation_key: str
    ) -> FetchAttemptRef:
        if not provider_key or not operation_key:
            raise ValueError("provider_key and operation_key are required")
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"official-site:operation:{operation_key}"},
            )
            existing = _row(
                await conn.execute(
                    text(
                        "SELECT * FROM official_site_fetch_attempt "
                        "WHERE operation_key = :operation_key FOR UPDATE"
                    ),
                    {"operation_key": operation_key},
                )
            )
            if existing is not None:
                exact = (
                    existing["workspace_id"] == lease.workspace_id
                    and existing["crawl_run_id"] == lease.crawl_run_id
                    and existing["page_id"] == lease.page_id
                    and existing["lease_generation"] == lease.lease_generation
                    and existing["worker_id"] == lease.worker_id
                    and existing["provider_key"] == provider_key
                )
                if not exact:
                    raise CrawlReplayConflictError(
                        "operation key already belongs to a different fenced attempt"
                    )
                return _attempt_from_row(existing)

            page = _row(
                await conn.execute(
                    text(
                        """
                        SELECT * FROM official_site_crawl_page
                        WHERE id = :page_id AND workspace_id = :workspace_id
                          AND crawl_run_id = :crawl_run_id AND state = 'leased'
                          AND lease_owner = :worker_id
                          AND lease_generation = :lease_generation
                          AND lease_expires_at > now()
                        FOR UPDATE
                        """
                    ),
                    self._lease_params(lease),
                )
            )
            if page is None:
                raise CrawlStateConflictError("lease is stale or cannot begin a provider attempt")
            attempt_number = page["attempt_count"] + 1
            attempt = _row(
                await conn.execute(
                    text(
                        """
                        INSERT INTO official_site_fetch_attempt (
                            id, workspace_id, crawl_run_id, page_id, attempt_number,
                            lease_generation, worker_id, operation_key, provider_key, requested_url
                        ) VALUES (
                            :id, :workspace_id, :crawl_run_id, :page_id, :attempt_number,
                            :lease_generation, :worker_id, :operation_key, :provider_key,
                            :requested_url
                        )
                        RETURNING *
                        """
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": lease.workspace_id,
                        "crawl_run_id": lease.crawl_run_id,
                        "page_id": lease.page_id,
                        "attempt_number": attempt_number,
                        "lease_generation": lease.lease_generation,
                        "worker_id": lease.worker_id,
                        "operation_key": operation_key,
                        "provider_key": provider_key,
                        "requested_url": lease.requested_url,
                    },
                )
            )
            await conn.execute(
                text(
                    """
                    UPDATE official_site_crawl_page
                    SET attempt_count = :attempt_number, updated_at = now()
                    WHERE id = :page_id AND workspace_id = :workspace_id
                      AND crawl_run_id = :crawl_run_id
                    """
                ),
                {
                    "attempt_number": attempt_number,
                    "page_id": lease.page_id,
                    "workspace_id": lease.workspace_id,
                    "crawl_run_id": lease.crawl_run_id,
                },
            )
            assert attempt is not None
            return _attempt_from_row(attempt)

    async def mark_attempt_dispatched(self, lease: CrawlLease, attempt: FetchAttemptRef) -> bool:
        if not self._attempt_matches_lease(attempt, lease, require_same_generation=True):
            return False
        async with self._conn_factory() as conn:
            page = _row(
                await conn.execute(
                    text(
                        """
                        SELECT id FROM official_site_crawl_page
                        WHERE id = :page_id AND workspace_id = :workspace_id
                          AND crawl_run_id = :crawl_run_id AND state = 'leased'
                          AND lease_owner = :worker_id
                          AND lease_generation = :lease_generation
                          AND lease_expires_at > now()
                        FOR UPDATE
                        """
                    ),
                    self._lease_params(lease),
                )
            )
            if page is None:
                return False
            changed = await conn.execute(
                text(
                    """
                    UPDATE official_site_fetch_attempt
                    SET state = 'dispatched', dispatched_at = now()
                    WHERE id = :attempt_id AND workspace_id = :workspace_id
                      AND crawl_run_id = :crawl_run_id AND page_id = :page_id
                      AND state = 'prepared' AND worker_id = :worker_id
                      AND lease_generation = :lease_generation
                    """
                ),
                {**self._lease_params(lease), "attempt_id": attempt.fetch_attempt_id},
            )
            if changed.rowcount != 1:
                return False
            await conn.execute(
                text(
                    """
                    UPDATE official_site_crawl_page
                    SET state = 'provider_started', updated_at = now()
                    WHERE id = :page_id AND workspace_id = :workspace_id
                      AND crawl_run_id = :crawl_run_id
                    """
                ),
                self._lease_params(lease),
            )
            return True

    async def record_provider_result(
        self,
        lease: CrawlLease,
        attempt: FetchAttemptRef,
        result: ProviderResultMetadata,
    ) -> bool:
        if not self._attempt_matches_lease(attempt, lease, require_same_generation=False):
            return False
        if (
            result.provider_key != attempt.provider_key
            or result.requested_url != lease.requested_url
        ):
            raise CrawlReplayConflictError("provider result does not match the durable attempt")
        async with self._conn_factory() as conn:
            joined = _row(
                await conn.execute(
                    text(
                        """
                        SELECT page.state AS page_state, attempt.state AS attempt_state
                        FROM official_site_crawl_page AS page
                        JOIN official_site_fetch_attempt AS attempt
                          ON attempt.page_id = page.id
                         AND attempt.crawl_run_id = page.crawl_run_id
                         AND attempt.workspace_id = page.workspace_id
                        WHERE page.id = :page_id AND page.workspace_id = :workspace_id
                          AND page.crawl_run_id = :crawl_run_id
                          AND page.lease_owner = :worker_id
                          AND page.lease_generation = :lease_generation
                          AND page.lease_expires_at > now()
                          AND attempt.id = :attempt_id
                        FOR UPDATE OF page, attempt
                        """
                    ),
                    {**self._lease_params(lease), "attempt_id": attempt.fetch_attempt_id},
                )
            )
            if joined is None:
                return False
            old_attempt = FetchAttemptState(joined["attempt_state"])
            old_page = CrawlPageState(joined["page_state"])
            next_attempt, next_page, terminal_reason, keep_lease = self._result_transition(
                old_attempt, old_page, result.retry_class
            )

            finished = next_attempt in {
                FetchAttemptState.RETRYABLE_NO_SPEND,
                FetchAttemptState.FAILED,
                FetchAttemptState.RECONCILED_NO_SPEND,
                FetchAttemptState.QUARANTINED,
            }
            await conn.execute(
                text(
                    """
                    UPDATE official_site_fetch_attempt
                    SET state = :state, provider_request_id = :provider_request_id,
                        provider_receipt_json = CAST(:receipt AS jsonb),
                        final_url = :final_url,
                        redirect_chain_json = CAST(:redirects AS jsonb),
                        provider_status = :provider_status, http_status = :http_status,
                        media_type = :media_type, size_bytes = :size_bytes,
                        cost_cents = :cost_cents, cost_kind = :cost_kind,
                        spend_status = :spend_status, retry_class = :retry_class,
                        provider_completed_at = now(),
                        finished_at = CASE WHEN :finished THEN now() ELSE NULL END
                    WHERE id = :attempt_id AND workspace_id = :workspace_id
                      AND crawl_run_id = :crawl_run_id AND page_id = :page_id
                    """
                ),
                {
                    "state": next_attempt.value,
                    "provider_request_id": result.provider_request_id,
                    "receipt": _json(result.receipt) if result.receipt is not None else None,
                    "final_url": result.final_url,
                    "redirects": _json(
                        [hop.model_dump(mode="json") for hop in result.redirect_chain]
                    ),
                    "provider_status": result.provider_status,
                    "http_status": result.http_status,
                    "media_type": result.media_type,
                    "size_bytes": result.size_bytes,
                    "cost_cents": result.cost_cents,
                    "cost_kind": result.cost_kind.value,
                    "spend_status": result.spend_status.value,
                    "retry_class": result.retry_class.value,
                    "finished": finished,
                    "attempt_id": attempt.fetch_attempt_id,
                    "workspace_id": lease.workspace_id,
                    "crawl_run_id": lease.crawl_run_id,
                    "page_id": lease.page_id,
                },
            )
            await conn.execute(
                text(
                    """
                    UPDATE official_site_crawl_page
                    SET state = :state,
                        next_attempt_at = CASE WHEN :state = 'retry_wait' THEN now() ELSE NULL END,
                        terminal_reason = :terminal_reason,
                        lease_owner = CASE WHEN :keep_lease THEN lease_owner ELSE NULL END,
                        lease_acquired_at = CASE
                            WHEN :keep_lease THEN lease_acquired_at ELSE NULL END,
                        lease_expires_at = CASE
                            WHEN :keep_lease THEN lease_expires_at ELSE NULL END,
                        updated_at = now()
                    WHERE id = :page_id AND workspace_id = :workspace_id
                      AND crawl_run_id = :crawl_run_id
                      AND lease_owner = :worker_id AND lease_generation = :lease_generation
                    """
                ),
                {
                    **self._lease_params(lease),
                    "state": next_page.value,
                    "terminal_reason": terminal_reason,
                    "keep_lease": keep_lease,
                },
            )
            return True

    async def persist_snapshot(
        self,
        lease: CrawlLease,
        attempt: FetchAttemptRef,
        artifact: ArtifactRef,
        result: ProviderResultMetadata,
        outgoing_links: tuple[LinkObservation, ...],
    ) -> PageSnapshotRef | None:
        # C2 normalizes/policy-checks the returned links and calls ``record_discoveries``. C1
        # receives them so the frozen seam stays acquisition-complete, but it must not invent URL
        # policy outcomes or frontier identities here.
        _ = outgoing_links
        if artifact.workspace_id != lease.workspace_id:
            return None
        if result.retry_class is not RetryClass.SUCCESS:
            raise CrawlStateConflictError("only a successful provider result can be snapshotted")
        if result.size_bytes != artifact.size_bytes:
            raise CrawlReplayConflictError("artifact size does not match provider result metadata")
        if (
            result.provider_key != attempt.provider_key
            or result.requested_url != lease.requested_url
        ):
            raise CrawlReplayConflictError("snapshot inputs do not match the durable attempt")
        async with self._conn_factory() as conn:
            joined = _row(
                await conn.execute(
                    text(
                        """
                        SELECT page.state AS page_state, attempt.state AS attempt_state,
                               attempt.requested_url AS attempt_requested_url,
                               run.robots_policy_version, run.url_policy_version
                        FROM official_site_crawl_page AS page
                        JOIN official_site_fetch_attempt AS attempt
                          ON attempt.id = :attempt_id
                         AND attempt.page_id = page.id
                         AND attempt.crawl_run_id = page.crawl_run_id
                         AND attempt.workspace_id = page.workspace_id
                        JOIN official_site_crawl_run AS run
                          ON run.id = page.crawl_run_id AND run.workspace_id = page.workspace_id
                        WHERE page.id = :page_id AND page.workspace_id = :workspace_id
                          AND page.crawl_run_id = :crawl_run_id
                          AND page.state = 'persistence_pending'
                          AND page.lease_owner = :worker_id
                          AND page.lease_generation = :lease_generation
                          AND page.lease_expires_at > now()
                        FOR UPDATE OF page, attempt
                        """
                    ),
                    {**self._lease_params(lease), "attempt_id": attempt.fetch_attempt_id},
                )
            )
            if joined is None:
                return None
            if joined["attempt_state"] == FetchAttemptState.PERSISTED.value:
                return await self._existing_snapshot(conn, attempt.fetch_attempt_id, artifact)
            if joined["attempt_state"] not in {
                FetchAttemptState.PROVIDER_SUCCEEDED.value,
                FetchAttemptState.RECONCILED_SUCCEEDED.value,
            }:
                return None

            captured = _row(
                await conn.execute(
                    text(
                        """
                        SELECT content_sha256, media_type, size_bytes, erased_at
                        FROM artifact
                        WHERE storage_key = :artifact_key AND workspace_id = :workspace_id
                        """
                    ),
                    {
                        "artifact_key": artifact.artifact_key,
                        "workspace_id": artifact.workspace_id,
                    },
                )
            )
            if captured is None or captured["erased_at"] is not None:
                raise CrawlStateConflictError("snapshot artifact is absent or erased")
            if (
                captured["content_sha256"] != artifact.content_sha256
                or captured["size_bytes"] != artifact.size_bytes
                or captured["media_type"] != result.media_type
            ):
                raise CrawlReplayConflictError("artifact row disagrees with snapshot metadata")

            snapshot_id = uuid4()
            snapshot = _row(
                await conn.execute(
                    text(
                        """
                        INSERT INTO official_site_page_snapshot (
                            id, workspace_id, crawl_run_id, page_id, fetch_attempt_id,
                            requested_url, final_url, redirect_chain_json, fetched_at,
                            provider_key, provider_request_id, http_status, media_type,
                            artifact_key, content_sha256, size_bytes,
                            robots_decision_ref, policy_version
                        ) VALUES (
                            :id, :workspace_id, :crawl_run_id, :page_id, :fetch_attempt_id,
                            :requested_url, :final_url, CAST(:redirects AS jsonb), :fetched_at,
                            :provider_key, :provider_request_id, :http_status, :media_type,
                            :artifact_key, :content_sha256, :size_bytes,
                            :robots_decision_ref, :policy_version
                        )
                        RETURNING *
                        """
                    ),
                    {
                        "id": snapshot_id,
                        "workspace_id": lease.workspace_id,
                        "crawl_run_id": lease.crawl_run_id,
                        "page_id": lease.page_id,
                        "fetch_attempt_id": attempt.fetch_attempt_id,
                        "requested_url": result.requested_url,
                        "final_url": result.final_url,
                        "redirects": _json(
                            [hop.model_dump(mode="json") for hop in result.redirect_chain]
                        ),
                        "fetched_at": result.fetched_at,
                        "provider_key": result.provider_key,
                        "provider_request_id": result.provider_request_id,
                        "http_status": result.http_status,
                        "media_type": result.media_type,
                        "artifact_key": artifact.artifact_key,
                        "content_sha256": artifact.content_sha256,
                        "size_bytes": artifact.size_bytes,
                        "robots_decision_ref": (
                            f"run:{lease.crawl_run_id}:robots:{joined['robots_policy_version']}"
                        ),
                        "policy_version": joined["url_policy_version"],
                    },
                )
            )
            await conn.execute(
                text(
                    """
                    UPDATE official_site_fetch_attempt
                    SET state = 'persisted', artifact_key = :artifact_key,
                        content_sha256 = :content_sha256, persisted_at = now(), finished_at = now()
                    WHERE id = :attempt_id AND workspace_id = :workspace_id
                      AND crawl_run_id = :crawl_run_id AND page_id = :page_id
                      AND state IN ('provider_succeeded', 'reconciled_succeeded')
                    """
                ),
                {
                    "artifact_key": artifact.artifact_key,
                    "content_sha256": artifact.content_sha256,
                    "attempt_id": attempt.fetch_attempt_id,
                    "workspace_id": lease.workspace_id,
                    "crawl_run_id": lease.crawl_run_id,
                    "page_id": lease.page_id,
                },
            )
            assert snapshot is not None
            return self._snapshot_ref(snapshot)

    async def complete_page(self, lease: CrawlLease, *, snapshot_id: UUID) -> bool:
        async with self._conn_factory() as conn:
            result = await conn.execute(
                text(
                    """
                    UPDATE official_site_crawl_page AS page
                    SET state = 'fetched', latest_snapshot_id = snapshot.id,
                        fetched_at = now(), lease_owner = NULL,
                        lease_acquired_at = NULL, lease_expires_at = NULL, updated_at = now()
                    FROM official_site_page_snapshot AS snapshot
                    JOIN official_site_fetch_attempt AS attempt
                      ON attempt.id = snapshot.fetch_attempt_id
                     AND attempt.workspace_id = snapshot.workspace_id
                     AND attempt.crawl_run_id = snapshot.crawl_run_id
                     AND attempt.page_id = snapshot.page_id
                    WHERE page.id = :page_id AND page.workspace_id = :workspace_id
                      AND page.crawl_run_id = :crawl_run_id
                      AND page.state = 'persistence_pending'
                      AND page.lease_owner = :worker_id
                      AND page.lease_generation = :lease_generation
                      AND page.lease_expires_at > now()
                      AND snapshot.id = :snapshot_id
                      AND snapshot.page_id = page.id
                      AND snapshot.workspace_id = page.workspace_id
                      AND snapshot.crawl_run_id = page.crawl_run_id
                      AND attempt.state = 'persisted'
                    """
                ),
                {**self._lease_params(lease), "snapshot_id": snapshot_id},
            )
            return result.rowcount == 1

    async def disposition_attempt(
        self,
        lease: CrawlLease,
        attempt: FetchAttemptRef,
        outcome: AttemptOutcome,
    ) -> bool:
        if not self._attempt_matches_lease(attempt, lease, require_same_generation=False):
            return False
        async with self._conn_factory() as conn:
            joined = _row(
                await conn.execute(
                    text(
                        """
                        SELECT page.state AS page_state, attempt.state AS attempt_state
                        FROM official_site_crawl_page AS page
                        JOIN official_site_fetch_attempt AS attempt
                          ON attempt.id = :attempt_id AND attempt.page_id = page.id
                         AND attempt.crawl_run_id = page.crawl_run_id
                         AND attempt.workspace_id = page.workspace_id
                        WHERE page.id = :page_id AND page.workspace_id = :workspace_id
                          AND page.crawl_run_id = :crawl_run_id
                          AND page.lease_owner = :worker_id
                          AND page.lease_generation = :lease_generation
                          AND page.lease_expires_at > now()
                        FOR UPDATE OF page, attempt
                        """
                    ),
                    {**self._lease_params(lease), "attempt_id": attempt.fetch_attempt_id},
                )
            )
            if joined is None:
                return False
            old_attempt = FetchAttemptState(joined["attempt_state"])
            old_page = CrawlPageState(joined["page_state"])
            if not allows_transition(ATTEMPT_TRANSITIONS, old_attempt, outcome.attempt_state):
                raise CrawlStateConflictError("attempt disposition violates the frozen state graph")
            if not allows_transition(PAGE_TRANSITIONS, old_page, outcome.page_state):
                raise CrawlStateConflictError("page disposition violates the frozen state graph")

            await conn.execute(
                text(
                    """
                    UPDATE official_site_fetch_attempt
                    SET state = :state,
                        spend_status = CASE
                            WHEN :state = 'spend_unknown' THEN 'spend_unknown'
                            WHEN :state IN ('retryable_no_spend', 'reconciled_no_spend')
                                THEN 'no_spend'
                            ELSE spend_status
                        END,
                        retry_class = CASE
                            WHEN :state = 'spend_unknown' THEN 'ambiguous'
                            WHEN :state IN ('retryable_no_spend', 'reconciled_no_spend')
                                THEN 'retryable_no_spend'
                            ELSE retry_class
                        END,
                        finished_at = CASE
                            WHEN :state IN ('spend_unknown') THEN NULL ELSE now()
                        END
                    WHERE id = :attempt_id AND workspace_id = :workspace_id
                      AND crawl_run_id = :crawl_run_id AND page_id = :page_id
                    """
                ),
                {
                    "state": outcome.attempt_state.value,
                    "attempt_id": attempt.fetch_attempt_id,
                    "workspace_id": lease.workspace_id,
                    "crawl_run_id": lease.crawl_run_id,
                    "page_id": lease.page_id,
                },
            )
            terminal_reason = (
                outcome.reason_code
                if outcome.page_state in {CrawlPageState.FAILED, CrawlPageState.QUARANTINED}
                else None
            )
            await conn.execute(
                text(
                    """
                    UPDATE official_site_crawl_page
                    SET state = :state, next_attempt_at = :retry_at,
                        terminal_reason = :terminal_reason,
                        lease_owner = NULL, lease_acquired_at = NULL, lease_expires_at = NULL,
                        updated_at = now()
                    WHERE id = :page_id AND workspace_id = :workspace_id
                      AND crawl_run_id = :crawl_run_id
                      AND lease_owner = :worker_id AND lease_generation = :lease_generation
                    """
                ),
                {
                    **self._lease_params(lease),
                    "state": outcome.page_state.value,
                    "retry_at": outcome.retry_at,
                    "terminal_reason": terminal_reason,
                },
            )
            return True

    async def reclaim_expired_leases(
        self, *, workspace_id: str, crawl_run_id: UUID
    ) -> ReclaimResult:
        async with self._conn_factory() as conn:
            await self._lock(conn, crawl_run_id, "claim")
            await self._run(conn, workspace_id, crawl_run_id)
            return await self._reclaim(conn, workspace_id, crawl_run_id)

    async def freeze_corpus_checkpoint(
        self, *, workspace_id: str, crawl_run_id: UUID, phase: CrawlPhase
    ) -> CorpusCheckpointRef:
        async with self._conn_factory() as conn:
            await self._lock(conn, crawl_run_id, f"checkpoint:{phase.value}")
            await self._run(conn, workspace_id, crawl_run_id)
            eligibility = (
                [CrawlEligibility.FAST.value, CrawlEligibility.BOTH.value]
                if phase is CrawlPhase.FAST
                else [
                    CrawlEligibility.FAST.value,
                    CrawlEligibility.BACKGROUND.value,
                    CrawlEligibility.BOTH.value,
                ]
            )
            snapshot_ids = tuple(
                sorted(
                    (
                        row[0]
                        for row in (
                            await conn.execute(
                                text(
                                    """
                                    SELECT latest_snapshot_id
                                    FROM official_site_crawl_page
                                    WHERE workspace_id = :workspace_id
                                      AND crawl_run_id = :crawl_run_id
                                      AND state = 'fetched'
                                      AND eligibility = ANY(CAST(:eligibility AS text[]))
                                    """
                                ),
                                {
                                    "workspace_id": workspace_id,
                                    "crawl_run_id": crawl_run_id,
                                    "eligibility": eligibility,
                                },
                            )
                        ).all()
                    ),
                    key=str,
                )
            )
            version = int(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT COALESCE(max(version), 0) + 1
                            FROM official_site_corpus_checkpoint
                            WHERE crawl_run_id = :crawl_run_id AND phase = :phase
                            """
                        ),
                        {"crawl_run_id": crawl_run_id, "phase": phase.value},
                    )
                ).scalar_one()
            )
            progress = await self._read_progress(conn, workspace_id, crawl_run_id)
            coverage = {
                "fetched": progress.fetched,
                "failed": progress.failed,
                "quarantined": progress.quarantined,
                "refused": progress.refused,
                "snapshot_count": len(snapshot_ids),
            }
            checkpoint = _row(
                await conn.execute(
                    text(
                        """
                        INSERT INTO official_site_corpus_checkpoint (
                            id, workspace_id, crawl_run_id, phase, version,
                            snapshot_ids_json, snapshot_set_sha256, coverage_json
                        ) VALUES (
                            :id, :workspace_id, :crawl_run_id, :phase, :version,
                            CAST(:snapshot_ids AS jsonb), :snapshot_hash,
                            CAST(:coverage AS jsonb)
                        )
                        RETURNING *
                        """
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": workspace_id,
                        "crawl_run_id": crawl_run_id,
                        "phase": phase.value,
                        "version": version,
                        "snapshot_ids": _json([str(snapshot_id) for snapshot_id in snapshot_ids]),
                        "snapshot_hash": compute_snapshot_set_sha256(snapshot_ids),
                        "coverage": _json(coverage),
                    },
                )
            )
            assert checkpoint is not None
            return CorpusCheckpointRef(
                checkpoint_id=checkpoint["id"],
                workspace_id=checkpoint["workspace_id"],
                crawl_run_id=checkpoint["crawl_run_id"],
                phase=CrawlPhase(checkpoint["phase"]),
                version=checkpoint["version"],
                snapshot_ids=tuple(UUID(value) for value in checkpoint["snapshot_ids_json"]),
                snapshot_set_sha256=checkpoint["snapshot_set_sha256"],
                coverage=checkpoint["coverage_json"],
                created_at=checkpoint["created_at"],
            )

    async def transition_run(
        self,
        *,
        workspace_id: str,
        crawl_run_id: UUID,
        expected: CrawlRunStatus,
        next_status: CrawlRunStatus,
    ) -> bool:
        if not allows_transition(RUN_TRANSITIONS, expected, next_status):
            raise CrawlStateConflictError("run transition violates the frozen state graph")
        async with self._conn_factory() as conn:
            result = await conn.execute(
                text(
                    """
                    UPDATE official_site_crawl_run
                    SET status = :next_status, updated_at = now(),
                        completed_at = CASE
                            WHEN :next_status = 'completed' THEN now() ELSE NULL END,
                        failed_at = CASE WHEN :next_status = 'failed' THEN now() ELSE NULL END,
                        cancelled_at = CASE
                            WHEN :next_status = 'cancelled' THEN now() ELSE NULL END,
                        failure_code = CASE
                            WHEN :next_status = 'failed' THEN 'crawl_run_failed'
                            ELSE NULL
                        END
                    WHERE id = :crawl_run_id AND workspace_id = :workspace_id
                      AND status = :expected
                    """
                ),
                {
                    "next_status": next_status.value,
                    "crawl_run_id": crawl_run_id,
                    "workspace_id": workspace_id,
                    "expected": expected.value,
                },
            )
            return result.rowcount == 1

    async def read_progress(self, *, workspace_id: str, crawl_run_id: UUID) -> CrawlProgress:
        async with self._conn_factory() as conn:
            return await self._read_progress(conn, workspace_id, crawl_run_id)

    @staticmethod
    async def _lock(conn: AsyncConnection, crawl_run_id: UUID, purpose: str) -> None:
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"official-site:{purpose}:{crawl_run_id}"},
        )

    @staticmethod
    async def _run(
        conn: AsyncConnection,
        workspace_id: str,
        crawl_run_id: UUID,
        *,
        lock: bool = False,
    ) -> Mapping[str, Any]:
        suffix = " FOR UPDATE" if lock else ""
        run = _row(
            await conn.execute(
                text(
                    "SELECT * FROM official_site_crawl_run "
                    "WHERE id = :crawl_run_id AND workspace_id = :workspace_id" + suffix
                ),
                {"crawl_run_id": crawl_run_id, "workspace_id": workspace_id},
            )
        )
        if run is None:
            raise CrawlRunNotFoundError("official-site crawl run not found in workspace")
        return run

    @staticmethod
    def _lease_params(lease: CrawlLease) -> dict[str, Any]:
        return {
            "page_id": lease.page_id,
            "workspace_id": lease.workspace_id,
            "crawl_run_id": lease.crawl_run_id,
            "worker_id": lease.worker_id,
            "lease_generation": lease.lease_generation,
        }

    @staticmethod
    def _attempt_matches_lease(
        attempt: FetchAttemptRef, lease: CrawlLease, *, require_same_generation: bool
    ) -> bool:
        return (
            attempt.workspace_id == lease.workspace_id
            and attempt.crawl_run_id == lease.crawl_run_id
            and attempt.page_id == lease.page_id
            and (not require_same_generation or attempt.lease_generation == lease.lease_generation)
        )

    @staticmethod
    def _recovery_phase(status: str) -> CrawlPhase | None:
        if status in {
            CrawlRunStatus.FAST_ACTIVE.value,
            CrawlRunStatus.FAST_CLOSING.value,
            CrawlRunStatus.FAST_COMPLETE.value,
        }:
            return CrawlPhase.FAST
        if status == CrawlRunStatus.BACKGROUND_ACTIVE.value:
            return CrawlPhase.BACKGROUND
        return None

    @staticmethod
    def _result_transition(
        old_attempt: FetchAttemptState,
        old_page: CrawlPageState,
        retry_class: RetryClass,
    ) -> tuple[FetchAttemptState, CrawlPageState, str | None, bool]:
        if (
            old_attempt is FetchAttemptState.DISPATCHED
            and old_page is CrawlPageState.PROVIDER_STARTED
        ):
            mapping = {
                RetryClass.SUCCESS: (
                    FetchAttemptState.PROVIDER_SUCCEEDED,
                    CrawlPageState.PERSISTENCE_PENDING,
                    None,
                    True,
                ),
                RetryClass.RETRYABLE_NO_SPEND: (
                    FetchAttemptState.RETRYABLE_NO_SPEND,
                    CrawlPageState.RETRY_WAIT,
                    None,
                    False,
                ),
                RetryClass.PERMANENT: (
                    FetchAttemptState.FAILED,
                    CrawlPageState.FAILED,
                    "provider_permanent",
                    False,
                ),
                RetryClass.ROBOTS_REFUSED: (
                    FetchAttemptState.FAILED,
                    CrawlPageState.REFUSED,
                    "robots_refused",
                    False,
                ),
                RetryClass.POLICY_REFUSED: (
                    FetchAttemptState.FAILED,
                    CrawlPageState.REFUSED,
                    "policy_refused",
                    False,
                ),
                RetryClass.AMBIGUOUS: (
                    FetchAttemptState.SPEND_UNKNOWN,
                    CrawlPageState.RECONCILIATION_PENDING,
                    None,
                    False,
                ),
            }
            return mapping[retry_class]
        if (
            old_attempt is FetchAttemptState.SPEND_UNKNOWN
            and old_page is CrawlPageState.RECONCILIATION_PENDING
        ):
            mapping = {
                RetryClass.SUCCESS: (
                    FetchAttemptState.RECONCILED_SUCCEEDED,
                    CrawlPageState.PERSISTENCE_PENDING,
                    None,
                    True,
                ),
                RetryClass.RETRYABLE_NO_SPEND: (
                    FetchAttemptState.RECONCILED_NO_SPEND,
                    CrawlPageState.RETRY_WAIT,
                    None,
                    False,
                ),
                RetryClass.AMBIGUOUS: (
                    FetchAttemptState.QUARANTINED,
                    CrawlPageState.QUARANTINED,
                    "reconciliation_ambiguous",
                    False,
                ),
                RetryClass.PERMANENT: (
                    FetchAttemptState.QUARANTINED,
                    CrawlPageState.QUARANTINED,
                    "reconciliation_permanent",
                    False,
                ),
                RetryClass.ROBOTS_REFUSED: (
                    FetchAttemptState.QUARANTINED,
                    CrawlPageState.QUARANTINED,
                    "reconciliation_robots_refused",
                    False,
                ),
                RetryClass.POLICY_REFUSED: (
                    FetchAttemptState.QUARANTINED,
                    CrawlPageState.QUARANTINED,
                    "reconciliation_policy_refused",
                    False,
                ),
            }
            return mapping[retry_class]
        raise CrawlStateConflictError("provider result is not valid from committed attempt state")

    async def _existing_snapshot(
        self, conn: AsyncConnection, fetch_attempt_id: UUID, artifact: ArtifactRef
    ) -> PageSnapshotRef:
        snapshot = _row(
            await conn.execute(
                text(
                    "SELECT * FROM official_site_page_snapshot "
                    "WHERE fetch_attempt_id = :fetch_attempt_id"
                ),
                {"fetch_attempt_id": fetch_attempt_id},
            )
        )
        if snapshot is None:  # pragma: no cover - persisted constraint + transaction coupling
            raise CrawlStateConflictError("persisted attempt is missing its snapshot")
        if (
            snapshot["workspace_id"] != artifact.workspace_id
            or snapshot["artifact_key"] != artifact.artifact_key
            or snapshot["content_sha256"] != artifact.content_sha256
        ):
            raise CrawlReplayConflictError("snapshot replay supplied a different artifact")
        return self._snapshot_ref(snapshot)

    @staticmethod
    def _snapshot_ref(snapshot: Mapping[str, Any]) -> PageSnapshotRef:
        return PageSnapshotRef(
            snapshot_id=snapshot["id"],
            workspace_id=snapshot["workspace_id"],
            crawl_run_id=snapshot["crawl_run_id"],
            page_id=snapshot["page_id"],
            fetch_attempt_id=snapshot["fetch_attempt_id"],
            requested_url=snapshot["requested_url"],
            final_url=snapshot["final_url"],
            artifact=ArtifactRef(
                workspace_id=snapshot["workspace_id"],
                artifact_key=snapshot["artifact_key"],
                content_sha256=snapshot["content_sha256"],
                size_bytes=snapshot["size_bytes"],
            ),
            fetched_at=snapshot["fetched_at"],
        )

    @staticmethod
    async def _reexpand_saved_links(
        conn: AsyncConnection,
        *,
        workspace_id: str,
        crawl_run_id: UUID,
        page_id: UUID,
        graph_depth: int,
        max_graph_depth: int,
    ) -> int:
        """Expand already-persisted anchor edges after a fetched page gains a shorter path.

        The page itself remains fetched.  Unknown-depth child nodes become queued only when the
        now-verified path reaches them at depth <= 2.  A fetched child can cascade the same repair
        without another provider call.
        """

        queue: list[tuple[UUID, int]] = [(page_id, graph_depth)]
        best_seen: dict[UUID, int] = {}
        expanded = 0
        while queue:
            source_id, source_depth = queue.pop(0)
            previous = best_seen.get(source_id)
            if previous is not None and previous <= source_depth:
                continue
            best_seen[source_id] = source_depth
            source = _row(
                await conn.execute(
                    text(
                        """
                        SELECT state, graph_depth, expanded_min_depth
                        FROM official_site_crawl_page
                        WHERE id = :page_id AND workspace_id = :workspace_id
                          AND crawl_run_id = :crawl_run_id
                        FOR UPDATE
                        """
                    ),
                    {
                        "page_id": source_id,
                        "workspace_id": workspace_id,
                        "crawl_run_id": crawl_run_id,
                    },
                )
            )
            if (
                source is None
                or source["state"] != CrawlPageState.FETCHED.value
                or source_depth >= max_graph_depth
                or (
                    source["expanded_min_depth"] is not None
                    and source["expanded_min_depth"] <= source_depth
                )
            ):
                continue
            child_rows = list(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT child.id, child.state, child.graph_depth
                            FROM official_site_link_edge AS edge
                            JOIN official_site_crawl_page AS child
                              ON child.id = edge.to_page_id
                             AND child.crawl_run_id = edge.crawl_run_id
                             AND child.workspace_id = edge.workspace_id
                            WHERE edge.workspace_id = :workspace_id
                              AND edge.crawl_run_id = :crawl_run_id
                              AND edge.from_page_id = :page_id
                              AND edge.link_relation = 'anchor'
                            ORDER BY edge.observed_at, edge.id
                            FOR UPDATE OF child
                            """
                        ),
                        {
                            "workspace_id": workspace_id,
                            "crawl_run_id": crawl_run_id,
                            "page_id": source_id,
                        },
                    )
                ).mappings()
            )
            child_depth = source_depth + 1
            for child in child_rows:
                old_depth = child["graph_depth"]
                shortened = old_depth is None or child_depth < old_depth
                if not shortened:
                    continue
                await conn.execute(
                    text(
                        """
                        UPDATE official_site_crawl_page
                        SET graph_depth = :graph_depth,
                            state = CASE WHEN state = 'discovered' THEN 'queued' ELSE state END,
                            queued_at = CASE
                                WHEN state = 'discovered' THEN COALESCE(queued_at, now())
                                ELSE queued_at
                            END,
                            updated_at = now()
                        WHERE id = :page_id AND workspace_id = :workspace_id
                          AND crawl_run_id = :crawl_run_id
                        """
                    ),
                    {
                        "graph_depth": child_depth,
                        "page_id": child["id"],
                        "workspace_id": workspace_id,
                        "crawl_run_id": crawl_run_id,
                    },
                )
                if child["state"] == CrawlPageState.FETCHED.value:
                    queue.append((child["id"], child_depth))
            await conn.execute(
                text(
                    """
                    UPDATE official_site_crawl_page
                    SET expanded_min_depth = CASE
                            WHEN expanded_min_depth IS NULL THEN :depth
                            ELSE LEAST(expanded_min_depth, :depth)
                        END,
                        updated_at = now()
                    WHERE id = :page_id AND workspace_id = :workspace_id
                      AND crawl_run_id = :crawl_run_id AND state = 'fetched'
                    """
                ),
                {
                    "depth": source_depth,
                    "page_id": source_id,
                    "workspace_id": workspace_id,
                    "crawl_run_id": crawl_run_id,
                },
            )
            if child_rows:
                expanded += 1
        return expanded

    @staticmethod
    async def _reclaim(
        conn: AsyncConnection, workspace_id: str, crawl_run_id: UUID
    ) -> ReclaimResult:
        params = {"workspace_id": workspace_id, "crawl_run_id": crawl_run_id}
        await conn.execute(
            text(
                """
                UPDATE official_site_fetch_attempt AS attempt
                SET state = 'failed', finished_at = now()
                FROM official_site_crawl_page AS page
                WHERE page.workspace_id = :workspace_id
                  AND page.crawl_run_id = :crawl_run_id
                  AND page.state = 'leased' AND page.lease_expires_at <= now()
                  AND attempt.workspace_id = page.workspace_id
                  AND attempt.crawl_run_id = page.crawl_run_id
                  AND attempt.page_id = page.id AND attempt.state = 'prepared'
                """
            ),
            params,
        )
        pre_dispatch = await conn.execute(
            text(
                """
                UPDATE official_site_crawl_page
                SET state = 'queued', lease_owner = NULL, lease_acquired_at = NULL,
                    lease_expires_at = NULL, queued_at = now(), updated_at = now()
                WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id
                  AND state = 'leased' AND lease_expires_at <= now()
                """
            ),
            params,
        )

        await conn.execute(
            text(
                """
                UPDATE official_site_fetch_attempt AS attempt
                SET state = 'spend_unknown', spend_status = 'spend_unknown',
                    retry_class = 'ambiguous', finished_at = NULL
                FROM official_site_crawl_page AS page
                WHERE page.workspace_id = :workspace_id
                  AND page.crawl_run_id = :crawl_run_id
                  AND page.state = 'provider_started' AND page.lease_expires_at <= now()
                  AND attempt.workspace_id = page.workspace_id
                  AND attempt.crawl_run_id = page.crawl_run_id
                  AND attempt.page_id = page.id AND attempt.state = 'dispatched'
                """
            ),
            params,
        )
        provider_started = await conn.execute(
            text(
                """
                UPDATE official_site_crawl_page
                SET state = 'reconciliation_pending', lease_owner = NULL,
                    lease_acquired_at = NULL, lease_expires_at = NULL, updated_at = now()
                WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id
                  AND state = 'provider_started' AND lease_expires_at <= now()
                """
            ),
            params,
        )
        await conn.execute(
            text(
                """
                UPDATE official_site_crawl_page
                SET lease_owner = NULL, lease_acquired_at = NULL,
                    lease_expires_at = NULL, updated_at = now()
                WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id
                  AND state = 'reconciliation_pending'
                  AND lease_expires_at IS NOT NULL AND lease_expires_at <= now()
                """
            ),
            params,
        )
        persistence = await conn.execute(
            text(
                """
                UPDATE official_site_crawl_page
                SET lease_owner = NULL, lease_acquired_at = NULL,
                    lease_expires_at = NULL, updated_at = now()
                WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id
                  AND state = 'persistence_pending'
                  AND lease_expires_at IS NOT NULL AND lease_expires_at <= now()
                """
            ),
            params,
        )
        await conn.execute(
            text(
                """
                UPDATE official_site_crawl_page
                SET state = 'queued', next_attempt_at = NULL, queued_at = now(), updated_at = now()
                WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id
                  AND state = 'retry_wait' AND next_attempt_at <= now()
                """
            ),
            params,
        )
        return ReclaimResult(
            requeued_pre_dispatch=pre_dispatch.rowcount,
            moved_to_reconciliation_pending=provider_started.rowcount,
            released_persistence_pending=persistence.rowcount,
        )

    async def _read_progress(
        self, conn: AsyncConnection, workspace_id: str, crawl_run_id: UUID
    ) -> CrawlProgress:
        run = await self._run(conn, workspace_id, crawl_run_id)
        counts = {
            row["state"]: row["count"]
            for row in (
                await conn.execute(
                    text(
                        """
                        SELECT state, count(*)::int AS count
                        FROM official_site_crawl_page
                        WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id
                        GROUP BY state
                        """
                    ),
                    {"workspace_id": workspace_id, "crawl_run_id": crawl_run_id},
                )
            ).mappings()
        }
        spend_unknown = int(
            (
                await conn.execute(
                    text(
                        """
                        SELECT count(*) FROM official_site_fetch_attempt
                        WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id
                          AND spend_status = 'spend_unknown'
                        """
                    ),
                    {"workspace_id": workspace_id, "crawl_run_id": crawl_run_id},
                )
            ).scalar_one()
        )
        return CrawlProgress(
            workspace_id=workspace_id,
            crawl_run_id=crawl_run_id,
            status=CrawlRunStatus(run["status"]),
            queued=counts.get(CrawlPageState.QUEUED.value, 0),
            leased=counts.get(CrawlPageState.LEASED.value, 0),
            provider_active=counts.get(CrawlPageState.PROVIDER_STARTED.value, 0),
            reconciliation_pending=counts.get(CrawlPageState.RECONCILIATION_PENDING.value, 0),
            persistence_pending=counts.get(CrawlPageState.PERSISTENCE_PENDING.value, 0),
            fetched=counts.get(CrawlPageState.FETCHED.value, 0),
            refused=counts.get(CrawlPageState.REFUSED.value, 0),
            failed=counts.get(CrawlPageState.FAILED.value, 0),
            quarantined=counts.get(CrawlPageState.QUARANTINED.value, 0),
            spend_unknown=spend_unknown,
        )


__all__ = ["PostgresCrawlRepository"]
