"""PB-B2-backed page artifacts and recovery reads for official-site crawling (C4).

Provider bytes never enter the crawl ledger.  A successful response is content-addressed in the
shared artifact store, linked to its fenced fetch attempt, and then exposed to URL-level snapshot
persistence.  The attempt link is deliberately committed before the snapshot: a replacement
worker can finish persistence from the blob without issuing another provider request.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import text

from clue_db import ConnFactory, transaction
from clue_research.official_site.contracts import (
    OFFICIAL_SITE_SOURCE_KEY,
    ArtifactRef,
    CostKind,
    CrawlLease,
    FetchAttemptRef,
    FetchAttemptState,
    LinkObservation,
    PageFetchResult,
    ProviderResultMetadata,
    RedirectHop,
    RetryClass,
    SpendStatus,
)
from clue_research.official_site.discovery import extract_html_links
from clue_research.official_site.models import (
    CrawlReplayConflictError,
    CrawlStateConflictError,
)
from clue_storage import (
    ArtifactIntegrityError,
    ArtifactNotFound,
    StorageBackend,
    artifact_key,
    content_address,
)
from clue_storage.artifacts import read_verified_artifact, record_artifact

_MAX_RECEIPT_DEPTH = 4
_MAX_RECEIPT_ITEMS = 50
_MAX_RECEIPT_STRING = 1_000
_MAX_RECEIPT_BYTES = 16_384
_SENSITIVE_RECEIPT_KEYS = frozenset(
    {
        "apikey",
        "authorization",
        "body",
        "content",
        "cookie",
        "headers",
        "html",
        "markdown",
        "password",
        "raw",
        "rawbody",
        "rawresponse",
        "secret",
        "setcookie",
        "token",
    }
)


@dataclass(frozen=True, slots=True)
class RetainedPageSuccess:
    """A verified artifact plus the body-free metadata needed to finish one snapshot."""

    artifact: ArtifactRef
    metadata: ProviderResultMetadata
    content: bytes
    outgoing_links: tuple[LinkObservation, ...]


@dataclass(frozen=True, slots=True)
class OfficialSiteEvidenceReach:
    """Reference-only workspace/run reach used by DSAR and retention composition."""

    crawl_run_ids: tuple[UUID, ...]
    attempt_ids: tuple[UUID, ...]
    snapshot_ids: tuple[UUID, ...]
    artifact_keys: tuple[str, ...]
    link_expansion_ids: tuple[UUID, ...] = ()
    page_ids: tuple[UUID, ...] = ()
    observation_ids: tuple[UUID, ...] = ()
    link_edge_ids: tuple[UUID, ...] = ()
    alias_observation_ids: tuple[UUID, ...] = ()
    checkpoint_ids: tuple[UUID, ...] = ()
    extraction_operation_ids: tuple[UUID, ...] = ()
    claim_ids: tuple[UUID, ...] = ()


def _normalized_receipt_key(key: str) -> str:
    return "".join(character for character in key.casefold() if character.isalnum())


def _is_sensitive_receipt_key(key: str) -> bool:
    normalized = _normalized_receipt_key(key)
    return (
        normalized in _SENSITIVE_RECEIPT_KEYS
        or normalized.startswith("raw")
        or normalized.endswith(("body", "cookie", "headers", "password", "secret", "token"))
    )


def _sanitize_receipt_value(value: JsonValue, *, depth: int) -> JsonValue | None:
    if depth > _MAX_RECEIPT_DEPTH:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:_MAX_RECEIPT_STRING]
    if isinstance(value, list):
        sanitized_items = [
            _sanitize_receipt_value(item, depth=depth + 1) for item in value[:_MAX_RECEIPT_ITEMS]
        ]
        return [item for item in sanitized_items if item is not None]
    sanitized: dict[str, JsonValue] = {}
    for key, item in list(value.items())[:_MAX_RECEIPT_ITEMS]:
        if _is_sensitive_receipt_key(key):
            continue
        clean = _sanitize_receipt_value(item, depth=depth + 1)
        if clean is not None:
            sanitized[key[:200]] = clean
    return sanitized


def sanitize_provider_receipt(
    receipt: dict[str, JsonValue] | None,
) -> dict[str, JsonValue] | None:
    """Drop body/credential-shaped fields and bound the receipt before PostgreSQL persistence."""

    if receipt is None:
        return None
    sanitized = _sanitize_receipt_value(receipt, depth=0)
    assert isinstance(sanitized, dict)
    encoded = json.dumps(
        sanitized, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    if len(encoded) > _MAX_RECEIPT_BYTES:
        # The request ID has its own typed column. An oversized optional receipt must never turn a
        # known provider success into paid-call ambiguity, and it must never become a body store.
        return {"receipt_omitted": "sanitized_size_limit"}
    return sanitized or None


def sanitize_fetch_result(result: PageFetchResult) -> PageFetchResult:
    """Return the same typed result with only a bounded, privacy-safe receipt."""

    return result.model_copy(update={"receipt": sanitize_provider_receipt(result.receipt)})


class OfficialSiteArtifactStore:
    """Persist and reload successful page bytes without learning the provider implementation."""

    def __init__(
        self,
        *,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._storage = storage
        self._conn_factory = conn_factory

    async def persist_success(
        self,
        lease: CrawlLease,
        attempt: FetchAttemptRef,
        result: PageFetchResult,
    ) -> RetainedPageSuccess:
        """Content-address and attach one already-recorded provider success.

        The artifact row, blob put, and attempt reference are one database transaction around the
        external PB-B2 write.  If the transaction rolls back after the put, the blob is orphan-safe
        and the caller still owns ``result`` for a persistence-only retry; no code here can fetch.
        """

        if result.retry_class is not RetryClass.SUCCESS or result.content is None:
            raise ValueError("only a successful result with content can be persisted")
        if result.media_type is None:  # reinforced at the I/O seam beyond Pydantic's invariant
            raise ValueError("successful result must carry a media type")
        media_type = result.media_type
        if result.provider_key != attempt.provider_key:
            raise CrawlReplayConflictError("artifact provider does not match durable attempt")
        if result.requested_url != lease.requested_url:
            raise CrawlReplayConflictError("artifact URL does not match leased page")
        digest = content_address(result.content)
        key = artifact_key(lease.workspace_id, digest)
        artifact = ArtifactRef(
            workspace_id=lease.workspace_id,
            artifact_key=key,
            content_sha256=digest,
            size_bytes=len(result.content),
        )
        async with self._conn_factory() as conn:
            joined = (
                (
                    await conn.execute(
                        text(
                            """
                        SELECT attempt.state, attempt.artifact_key, attempt.content_sha256
                        FROM official_site_fetch_attempt AS attempt
                        JOIN official_site_crawl_page AS page
                          ON page.id = attempt.page_id
                         AND page.crawl_run_id = attempt.crawl_run_id
                         AND page.workspace_id = attempt.workspace_id
                        WHERE attempt.id = :attempt_id
                          AND attempt.workspace_id = :workspace_id
                          AND attempt.crawl_run_id = :crawl_run_id
                          AND attempt.page_id = :page_id
                          AND page.state = 'persistence_pending'
                          AND page.lease_owner = :worker_id
                          AND page.lease_generation = :lease_generation
                          AND page.lease_expires_at > now()
                        FOR UPDATE OF attempt, page
                        """
                        ),
                        {
                            "attempt_id": attempt.fetch_attempt_id,
                            "workspace_id": lease.workspace_id,
                            "crawl_run_id": lease.crawl_run_id,
                            "page_id": lease.page_id,
                            "worker_id": lease.worker_id,
                            "lease_generation": lease.lease_generation,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if joined is None:
                raise CrawlStateConflictError("persistence lease is stale or no longer eligible")
            durable_state = FetchAttemptState(joined["state"])
            if durable_state not in {
                FetchAttemptState.PROVIDER_SUCCEEDED,
                FetchAttemptState.RECONCILED_SUCCEEDED,
                FetchAttemptState.PERSISTED,
            }:
                raise CrawlStateConflictError("attempt has no recorded provider success")
            if joined["artifact_key"] is not None and (
                joined["artifact_key"] != key or joined["content_sha256"] != digest
            ):
                raise CrawlReplayConflictError("attempt already references different page bytes")

            await record_artifact(
                conn,
                storage_key=key,
                workspace_id=lease.workspace_id,
                content_sha256=digest,
                media_type=media_type,
                size_bytes=len(result.content),
                source_key=OFFICIAL_SITE_SOURCE_KEY,
                source_url=result.final_url or result.requested_url,
            )
            if not await self._storage.exists(key):
                await self._storage.put(
                    key,
                    result.content,
                    media_type=media_type,
                )
            _, verified = await read_verified_artifact(
                conn, self._storage, storage_key=key, workspace_id=lease.workspace_id
            )
            if verified != result.content:
                raise CrawlReplayConflictError("content-addressed artifact bytes changed")
            changed = await conn.execute(
                text(
                    """
                    UPDATE official_site_fetch_attempt
                    SET artifact_key = :artifact_key, content_sha256 = :content_sha256
                    WHERE id = :attempt_id AND workspace_id = :workspace_id
                      AND crawl_run_id = :crawl_run_id AND page_id = :page_id
                      AND state IN ('provider_succeeded', 'reconciled_succeeded', 'persisted')
                    """
                ),
                {
                    "artifact_key": key,
                    "content_sha256": digest,
                    "attempt_id": attempt.fetch_attempt_id,
                    "workspace_id": lease.workspace_id,
                    "crawl_run_id": lease.crawl_run_id,
                    "page_id": lease.page_id,
                },
            )
            if changed.rowcount != 1:
                raise CrawlStateConflictError("attempt artifact attachment lost its fence")
        return RetainedPageSuccess(
            artifact=artifact,
            metadata=result.metadata(),
            content=result.content,
            outgoing_links=result.outgoing_links,
        )

    async def load_success(
        self, lease: CrawlLease, attempt: FetchAttemptRef
    ) -> RetainedPageSuccess | None:
        """Reload a staged success for persistence/completion replay; never call a provider."""

        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                        SELECT attempt.*, captured.storage_key
                        FROM official_site_fetch_attempt AS attempt
                        JOIN official_site_crawl_page AS page
                          ON page.id = attempt.page_id
                         AND page.crawl_run_id = attempt.crawl_run_id
                         AND page.workspace_id = attempt.workspace_id
                        LEFT JOIN artifact AS captured
                          ON captured.storage_key = attempt.artifact_key
                         AND captured.workspace_id = attempt.workspace_id
                        WHERE attempt.id = :attempt_id
                          AND attempt.workspace_id = :workspace_id
                          AND attempt.crawl_run_id = :crawl_run_id
                          AND attempt.page_id = :page_id
                          AND attempt.state IN (
                              'provider_succeeded', 'reconciled_succeeded', 'persisted'
                          )
                          AND page.state = 'persistence_pending'
                          AND page.lease_owner = :worker_id
                          AND page.lease_generation = :lease_generation
                          AND page.lease_expires_at > now()
                        """
                        ),
                        {
                            "attempt_id": attempt.fetch_attempt_id,
                            "workspace_id": lease.workspace_id,
                            "crawl_run_id": lease.crawl_run_id,
                            "page_id": lease.page_id,
                            "worker_id": lease.worker_id,
                            "lease_generation": lease.lease_generation,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise CrawlStateConflictError("persistence claim is stale or no longer eligible")
            if row["artifact_key"] is None or row["storage_key"] is None:
                return None
            try:
                record, content = await read_verified_artifact(
                    conn,
                    self._storage,
                    storage_key=row["artifact_key"],
                    workspace_id=lease.workspace_id,
                )
            except ArtifactIntegrityError as exc:
                # Missing/erased/tampered bytes are unrecoverable from persistence alone and must
                # quarantine. A generic backend failure may be transient (for example S3 outage),
                # so preserve the claim for a later persistence retry instead of misclassifying it.
                if exc.__cause__ is None or isinstance(exc.__cause__, ArtifactNotFound):
                    return None
                raise
            artifact = ArtifactRef(
                workspace_id=lease.workspace_id,
                artifact_key=record.storage_key,
                content_sha256=record.content_sha256,
                size_bytes=record.size_bytes,
            )
            receipt = cast(dict[str, JsonValue] | None, row["provider_receipt_json"])
            metadata = ProviderResultMetadata(
                provider_key=row["provider_key"],
                provider_request_id=row["provider_request_id"],
                requested_url=row["requested_url"],
                final_url=row["final_url"],
                redirect_chain=tuple(
                    RedirectHop.model_validate(item) for item in row["redirect_chain_json"]
                ),
                provider_status=row["provider_status"],
                http_status=row["http_status"],
                media_type=row["media_type"],
                size_bytes=row["size_bytes"],
                # C1 stores the authoritative DB observation time, not a second client clock.
                fetched_at=row["provider_completed_at"],
                cost_cents=cast(Decimal | None, row["cost_cents"]),
                cost_kind=CostKind(row["cost_kind"]),
                spend_status=SpendStatus(row["spend_status"]),
                retry_class=RetryClass.SUCCESS,
                receipt=receipt,
            )
            extracted = (
                extract_html_links(content)
                if metadata.media_type in {"text/html", "application/xhtml+xml"}
                else None
            )
            outgoing = (
                (*extracted.links, *extracted.canonical_hints) if extracted is not None else ()
            )
            return RetainedPageSuccess(
                artifact=artifact,
                metadata=metadata,
                content=content,
                outgoing_links=tuple(outgoing),
            )

    async def evidence_reach(
        self, *, workspace_id: str, crawl_run_id: UUID | None = None
    ) -> OfficialSiteEvidenceReach:
        """Return every official-site ledger/blob/claim reference for one workspace/run.

        The seam began in C4 with attempt/snapshot/artifact reach. C9 closes the complete
        retention graph after C7 by also enumerating pages, observations, edges, aliases,
        checkpoints, extraction operations, retained model responses, and materialized claims.
        It remains read-only: physical erasure is owned by the existing workspace/claim artifact
        lifecycle after these references are retired in dependency order.
        """

        params: dict[str, Any] = {"workspace_id": workspace_id}
        run_predicate = ""
        if crawl_run_id is not None:
            run_predicate = " AND crawl_run_id = :crawl_run_id"
            params["crawl_run_id"] = crawl_run_id
        async with self._conn_factory() as conn:
            run_ids = tuple(
                sorted(
                    (
                        await conn.execute(
                            text(
                                "SELECT id FROM official_site_crawl_run "
                                "WHERE workspace_id = :workspace_id"
                                + (" AND id = :crawl_run_id" if crawl_run_id is not None else "")
                            ),
                            params,
                        )
                    ).scalars(),
                    key=str,
                )
            )
            attempt_rows = list(
                (
                    await conn.execute(
                        text(
                            "SELECT id, artifact_key FROM official_site_fetch_attempt "
                            "WHERE workspace_id = :workspace_id" + run_predicate
                        ),
                        params,
                    )
                ).all()
            )
            snapshot_rows = list(
                (
                    await conn.execute(
                        text(
                            "SELECT id, artifact_key FROM official_site_page_snapshot "
                            "WHERE workspace_id = :workspace_id" + run_predicate
                        ),
                        params,
                    )
                ).all()
            )
            table_ids: dict[str, tuple[UUID, ...]] = {}
            for label, table in (
                ("pages", "official_site_crawl_page"),
                ("observations", "official_site_url_observation"),
                ("edges", "official_site_link_edge"),
                ("aliases", "official_site_alias_observation"),
                ("checkpoints", "official_site_corpus_checkpoint"),
                ("link_expansions", "official_site_link_expansion"),
            ):
                table_ids[label] = tuple(
                    sorted(
                        (
                            await conn.execute(
                                text(
                                    f"SELECT id FROM {table} "  # noqa: S608 - frozen table list
                                    "WHERE workspace_id = :workspace_id" + run_predicate
                                ),
                                params,
                            )
                        ).scalars(),
                        key=str,
                    )
                )
            extraction_rows = list(
                (
                    await conn.execute(
                        text(
                            "SELECT id, response_artifact_key, claim_ids_json "
                            "FROM official_site_extraction_operation "
                            "WHERE workspace_id = :workspace_id" + run_predicate
                        ),
                        params,
                    )
                ).all()
            )
            declared_claim_ids = tuple(
                sorted(
                    {
                        UUID(value)
                        for row in extraction_rows
                        for value in row.claim_ids_json
                        if isinstance(value, str)
                    },
                    key=str,
                )
            )
            claim_artifact_keys: tuple[str, ...] = ()
            claim_ids: tuple[UUID, ...] = ()
            if extraction_rows:
                operation_refs = [f"official-site-extraction:{row.id}" for row in extraction_rows]
                claim_rows = list(
                    (
                        await conn.execute(
                            text(
                                "SELECT id, artifact_key FROM claim "
                                "WHERE workspace_id = :workspace_id "
                                "AND source_key = :source_key "
                                "AND source_operation_ref = ANY(CAST(:operation_refs AS text[]))"
                            ),
                            {
                                "workspace_id": workspace_id,
                                "source_key": OFFICIAL_SITE_SOURCE_KEY,
                                "operation_refs": operation_refs,
                            },
                        )
                    ).all()
                )
                claim_ids = tuple(sorted((row.id for row in claim_rows), key=str))
                if not set(declared_claim_ids).issubset(claim_ids):
                    raise CrawlStateConflictError(
                        "official-site extraction claim reach is incomplete or cross-workspace"
                    )
                claim_artifact_keys = tuple(
                    row.artifact_key for row in claim_rows if isinstance(row.artifact_key, str)
                )
        return OfficialSiteEvidenceReach(
            crawl_run_ids=run_ids,
            attempt_ids=tuple(sorted((row[0] for row in attempt_rows), key=str)),
            snapshot_ids=tuple(sorted((row[0] for row in snapshot_rows), key=str)),
            artifact_keys=tuple(
                sorted(
                    {
                        key
                        for key in (
                            *(row[1] for row in attempt_rows),
                            *(row[1] for row in snapshot_rows),
                            *(row.response_artifact_key for row in extraction_rows),
                            *claim_artifact_keys,
                        )
                        if isinstance(key, str)
                    }
                )
            ),
            page_ids=table_ids["pages"],
            link_expansion_ids=table_ids["link_expansions"],
            observation_ids=table_ids["observations"],
            link_edge_ids=table_ids["edges"],
            alias_observation_ids=table_ids["aliases"],
            checkpoint_ids=table_ids["checkpoints"],
            extraction_operation_ids=tuple(sorted((row.id for row in extraction_rows), key=str)),
            claim_ids=claim_ids,
        )


__all__ = [
    "OfficialSiteArtifactStore",
    "OfficialSiteEvidenceReach",
    "RetainedPageSuccess",
    "sanitize_fetch_result",
    "sanitize_provider_receipt",
]
