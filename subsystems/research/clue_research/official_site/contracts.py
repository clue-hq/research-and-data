"""Provider-neutral C0 contracts for durable Stage-0 official-site crawling.

This module is deliberately pure: no provider SDK, SQLAlchemy, storage implementation, network
client, or composition-root import is allowed. C1-C7 implement these values behind the seams in
``seams.py``; changing a frozen enum/model after C0 requires an explicit contract revision.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from clue_core import UtcDatetime

CONTRACT_VERSION = "stage0-official-site-c0-v1"
OFFICIAL_SITE_SOURCE_KEY = "official_site"
HISTORICAL_OFFICIAL_SITE_SOURCE_KEYS: tuple[str, ...] = (
    "firecrawl_site",
    "scrapling_site",
)

OFFICIAL_SITE_TABLE_NAMES: tuple[str, ...] = (
    "official_site_crawl_run",
    "official_site_crawl_page",
    "official_site_url_observation",
    "official_site_link_edge",
    "official_site_fetch_attempt",
    "official_site_page_snapshot",
    "official_site_alias_observation",
    "official_site_corpus_checkpoint",
)


class FrozenContractModel(BaseModel):
    """Closed immutable base for every persisted or cross-component C0 value."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CrawlMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    AUTHORITATIVE = "authoritative"


class CrawlPhase(StrEnum):
    FAST = "fast"
    BACKGROUND = "background"


class CrawlRunStatus(StrEnum):
    QUEUED = "queued"
    FAST_ACTIVE = "fast_active"
    FAST_CLOSING = "fast_closing"
    FAST_COMPLETE = "fast_complete"
    BACKGROUND_ACTIVE = "background_active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CrawlPageState(StrEnum):
    DISCOVERED = "discovered"
    QUEUED = "queued"
    LEASED = "leased"
    PROVIDER_STARTED = "provider_started"
    RECONCILIATION_PENDING = "reconciliation_pending"
    PERSISTENCE_PENDING = "persistence_pending"
    RETRY_WAIT = "retry_wait"
    FETCHED = "fetched"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    REFUSED = "refused"


class FetchAttemptState(StrEnum):
    PREPARED = "prepared"
    DISPATCHED = "dispatched"
    PROVIDER_SUCCEEDED = "provider_succeeded"
    PERSISTED = "persisted"
    RETRYABLE_NO_SPEND = "retryable_no_spend"
    FAILED = "failed"
    SPEND_UNKNOWN = "spend_unknown"
    RECONCILED_NO_SPEND = "reconciled_no_spend"
    RECONCILED_SUCCEEDED = "reconciled_succeeded"
    QUARANTINED = "quarantined"


class DiscoveredVia(StrEnum):
    ROOT = "root"
    LINK = "link"
    SITEMAP = "sitemap"
    REDIRECT = "redirect"
    CANONICAL = "canonical"


class LinkRelation(StrEnum):
    ANCHOR = "anchor"
    REDIRECT = "redirect"
    CANONICAL_HINT = "canonical_hint"


class CrawlEligibility(StrEnum):
    FAST = "fast"
    BACKGROUND = "background"
    BOTH = "both"
    REFUSED = "refused"


class AliasKind(StrEnum):
    REDIRECT = "redirect"
    CANONICAL_HINT = "canonical_hint"


class AliasVerificationStatus(StrEnum):
    OBSERVED = "observed"
    VERIFIED_SAME_CONTENT = "verified_same_content"
    VERIFIED_REDIRECT = "verified_redirect"
    REJECTED_EXTERNAL = "rejected_external"
    CONFLICTING = "conflicting"


class PolicyOutcome(StrEnum):
    ADMITTED = "admitted"
    REFUSED = "refused"


class SpendStatus(StrEnum):
    SPEND_CONFIRMED = "spend_confirmed"
    SPEND_UNKNOWN = "spend_unknown"
    NO_SPEND = "no_spend"


class CostKind(StrEnum):
    ACTUAL = "actual"
    ESTIMATED = "estimated"
    NONE = "none"


class RetryClass(StrEnum):
    SUCCESS = "success"
    RETRYABLE_NO_SPEND = "retryable_no_spend"
    PERMANENT = "permanent"
    ROBOTS_REFUSED = "robots_refused"
    POLICY_REFUSED = "policy_refused"
    AMBIGUOUS = "ambiguous"


class AttemptDisposition(StrEnum):
    RETRY_NO_SPEND = "retry_no_spend"
    FAIL_PERMANENT = "fail_permanent"
    RECONCILE = "reconcile"
    QUARANTINE = "quarantine"


class OfficialSiteCrawlContractConfig(FrozenContractModel):
    """Validated run-pinned knobs; environment loading remains composition-root owned."""

    contract_version: Literal["stage0-official-site-c0-v1"] = "stage0-official-site-c0-v1"
    crawl_mode: CrawlMode = CrawlMode.OFF
    provider_key: str = Field(min_length=1, max_length=64)
    max_graph_depth: Literal[2] = 2
    fast_deadline_seconds: int = Field(default=40, ge=1, le=40)
    fast_page_ceiling: int = Field(default=12, ge=1)
    total_page_ceiling: int = Field(default=100, ge=1)
    worker_concurrency: int = Field(default=8, ge=1)
    per_host_concurrency: int = Field(default=3, ge=1)
    lease_ttl_seconds: int = Field(default=90, ge=3)
    heartbeat_seconds: int = Field(default=20, ge=1)
    request_timeout_seconds: int = Field(default=30, ge=1)
    max_response_bytes: int = Field(default=5_000_000, ge=1)
    max_redirects: int = Field(default=5, ge=0)
    allow_subdomains: bool = False
    url_policy_version: str = Field(min_length=1)
    provider_policy_version: str = Field(min_length=1)
    robots_policy_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_bounds(self) -> OfficialSiteCrawlContractConfig:
        if self.fast_page_ceiling > self.total_page_ceiling:
            raise ValueError("fast_page_ceiling cannot exceed total_page_ceiling")
        if self.per_host_concurrency > self.worker_concurrency:
            raise ValueError("per_host_concurrency cannot exceed worker_concurrency")
        if 2 * self.heartbeat_seconds >= self.lease_ttl_seconds:
            raise ValueError("two heartbeat intervals must fit strictly inside the lease TTL")
        return self


class RedirectHop(FrozenContractModel):
    from_url: str = Field(min_length=1)
    to_url: str = Field(min_length=1)
    http_status: int = Field(ge=300, le=399)


class LinkObservation(FrozenContractModel):
    discovered_url: str = Field(min_length=1)
    relation: LinkRelation = LinkRelation.ANCHOR
    link_text: str | None = Field(default=None, max_length=500)


class PageFetcherCapabilities(FrozenContractModel):
    provider_key: str = Field(min_length=1, max_length=64)
    single_page_only: Literal[True] = True
    supports_operation_lookup: bool
    supports_idempotency_key: bool
    reports_redirect_chain: bool
    reports_outgoing_links: bool
    reports_actual_cost: bool
    reports_provider_receipt: bool
    proves_no_spend_before_dispatch: bool


class PageFetchRequest(FrozenContractModel):
    operation_key: str = Field(min_length=1, max_length=200)
    requested_url: str = Field(min_length=1)
    allowed_hosts: tuple[str, ...] = Field(min_length=1)
    timeout_seconds: float = Field(gt=0)
    max_response_bytes: int = Field(gt=0)
    accepted_mime_types: tuple[str, ...] = Field(min_length=1)
    max_redirects: int = Field(ge=0)
    robots_decision_ref: str = Field(min_length=1)


class PageFetchResult(FrozenContractModel):
    provider_key: str = Field(min_length=1, max_length=64)
    provider_request_id: str | None = None
    requested_url: str = Field(min_length=1)
    final_url: str | None = None
    redirect_chain: tuple[RedirectHop, ...] = ()
    provider_status: str = Field(min_length=1)
    http_status: int | None = Field(default=None, ge=100, le=599)
    content: bytes | None = None
    media_type: str | None = None
    outgoing_links: tuple[LinkObservation, ...] = ()
    fetched_at: UtcDatetime
    cost_cents: Decimal | None = Field(default=None, ge=0)
    cost_kind: CostKind
    spend_status: SpendStatus
    retry_class: RetryClass
    receipt: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def _validate_outcome(self) -> PageFetchResult:
        if self.cost_kind is CostKind.NONE and self.cost_cents is not None:
            raise ValueError("cost_kind=none requires cost_cents=None")
        if self.cost_kind is not CostKind.NONE and self.cost_cents is None:
            raise ValueError("actual/estimated cost requires cost_cents")
        if self.spend_status is SpendStatus.NO_SPEND and self.cost_cents not in (None, Decimal(0)):
            raise ValueError("no_spend cannot carry a positive cost")
        if self.retry_class is RetryClass.SUCCESS and (
            self.content is None or self.final_url is None or self.media_type is None
        ):
            raise ValueError("success requires content, final_url, and media_type")
        if (
            self.retry_class is RetryClass.AMBIGUOUS
            and self.spend_status is not SpendStatus.SPEND_UNKNOWN
        ):
            raise ValueError("ambiguous retry class requires spend_unknown")
        if (
            self.spend_status is SpendStatus.SPEND_UNKNOWN
            and self.retry_class is not RetryClass.AMBIGUOUS
        ):
            raise ValueError("spend_unknown requires ambiguous retry class")
        return self

    def metadata(self) -> ProviderResultMetadata:
        """Drop page bytes/links before the durable attempt-metadata write."""

        return ProviderResultMetadata(
            provider_key=self.provider_key,
            provider_request_id=self.provider_request_id,
            requested_url=self.requested_url,
            final_url=self.final_url,
            redirect_chain=self.redirect_chain,
            provider_status=self.provider_status,
            http_status=self.http_status,
            media_type=self.media_type,
            size_bytes=len(self.content) if self.content is not None else None,
            fetched_at=self.fetched_at,
            cost_cents=self.cost_cents,
            cost_kind=self.cost_kind,
            spend_status=self.spend_status,
            retry_class=self.retry_class,
            receipt=self.receipt,
        )


class ProviderResultMetadata(FrozenContractModel):
    """Body-free result/receipt metadata safe for the attempt ledger."""

    provider_key: str = Field(min_length=1, max_length=64)
    provider_request_id: str | None = None
    requested_url: str = Field(min_length=1)
    final_url: str | None = None
    redirect_chain: tuple[RedirectHop, ...] = ()
    provider_status: str = Field(min_length=1)
    http_status: int | None = Field(default=None, ge=100, le=599)
    media_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    fetched_at: UtcDatetime
    cost_cents: Decimal | None = Field(default=None, ge=0)
    cost_kind: CostKind
    spend_status: SpendStatus
    retry_class: RetryClass
    receipt: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def _validate_outcome(self) -> ProviderResultMetadata:
        if self.cost_kind is CostKind.NONE and self.cost_cents is not None:
            raise ValueError("cost_kind=none requires cost_cents=None")
        if self.cost_kind is not CostKind.NONE and self.cost_cents is None:
            raise ValueError("actual/estimated cost requires cost_cents")
        if self.spend_status is SpendStatus.NO_SPEND and self.cost_cents not in (None, Decimal(0)):
            raise ValueError("no_spend cannot carry a positive cost")
        if self.retry_class is RetryClass.SUCCESS and (
            self.final_url is None or self.media_type is None or self.size_bytes is None
        ):
            raise ValueError("success metadata requires final_url, media_type, and size_bytes")
        if (
            self.retry_class is RetryClass.AMBIGUOUS
            and self.spend_status is not SpendStatus.SPEND_UNKNOWN
        ):
            raise ValueError("ambiguous retry class requires spend_unknown")
        if (
            self.spend_status is SpendStatus.SPEND_UNKNOWN
            and self.retry_class is not RetryClass.AMBIGUOUS
        ):
            raise ValueError("spend_unknown requires ambiguous retry class")
        return self


class CrawlRunCreate(FrozenContractModel):
    workspace_id: str = Field(min_length=1)
    brand_id: str = Field(min_length=1)
    client_entity_id: UUID | None = None
    recon_run_id: UUID
    root_discovered_url: str = Field(min_length=1)
    root_fetch_key: str = Field(min_length=1)
    allowed_registrable_domain: str = Field(min_length=1)
    config: OfficialSiteCrawlContractConfig


class CrawlRunRef(FrozenContractModel):
    crawl_run_id: UUID
    workspace_id: str = Field(min_length=1)
    recon_run_id: UUID
    status: CrawlRunStatus
    created: bool


class UrlObservation(FrozenContractModel):
    discovered_url: str = Field(min_length=1)
    discovered_via: DiscoveredVia
    # Additive C2 provenance delta: the frozen table already had this column, while the C0
    # transport model accidentally omitted the source sitemap URL.  Optional preserves C0 replay;
    # every C2 sitemap planner populates it.
    sitemap_url: str | None = Field(default=None, min_length=1)
    fetch_key: str | None = None
    fetch_key_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_page_id: UUID | None = None
    graph_depth: int | None = Field(default=None, ge=0, le=2)
    link_text: str | None = Field(default=None, max_length=500)
    priority: int = Field(default=100, ge=0)
    priority_reason: tuple[str, ...] = ()
    eligibility: CrawlEligibility
    policy_outcome: PolicyOutcome
    policy_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validate_identity(self) -> UrlObservation:
        page_origins = {
            DiscoveredVia.LINK,
            DiscoveredVia.REDIRECT,
            DiscoveredVia.CANONICAL,
        }
        if self.discovered_via in page_origins and self.source_page_id is None:
            raise ValueError("page-derived discovery requires source_page_id")
        if self.discovered_via not in page_origins and self.source_page_id is not None:
            raise ValueError("root/sitemap discovery cannot carry source_page_id")
        if self.discovered_via is DiscoveredVia.ROOT and (
            self.policy_outcome is PolicyOutcome.ADMITTED and self.graph_depth != 0
        ):
            raise ValueError("admitted root discovery requires graph depth zero")
        if self.discovered_via in {DiscoveredVia.REDIRECT, DiscoveredVia.CANONICAL} and (
            self.graph_depth is not None
        ):
            raise ValueError("alias discovery cannot assign graph depth")
        if self.discovered_via is DiscoveredVia.SITEMAP and self.graph_depth is not None:
            raise ValueError("sitemap discovery cannot assign graph depth")
        if self.discovered_via is not DiscoveredVia.SITEMAP and self.sitemap_url is not None:
            raise ValueError("only sitemap discovery may carry sitemap_url")
        if self.policy_outcome is PolicyOutcome.ADMITTED and (
            self.fetch_key is None or self.fetch_key_hash is None
        ):
            raise ValueError("admitted observations require fetch key and hash")
        if (
            self.policy_outcome is PolicyOutcome.REFUSED
            and self.eligibility is not CrawlEligibility.REFUSED
        ):
            raise ValueError("refused policy outcome requires refused eligibility")
        return self


class DiscoveryBatch(FrozenContractModel):
    workspace_id: str = Field(min_length=1)
    crawl_run_id: UUID
    observations: tuple[UrlObservation, ...] = Field(min_length=1)


class DiscoveryBatchResult(FrozenContractModel):
    observations_recorded: int = Field(ge=0)
    page_nodes_created: int = Field(ge=0)
    page_nodes_reprioritized: int = Field(ge=0)
    saved_links_reexpanded: int = Field(ge=0)


class ClaimNextRequest(FrozenContractModel):
    workspace_id: str = Field(min_length=1)
    crawl_run_id: UUID
    worker_id: str = Field(min_length=1, max_length=200)
    eligible_phase: CrawlPhase
    lease_ttl_seconds: int = Field(ge=3)


class ClaimReconciliationRequest(FrozenContractModel):
    """Claim one ambiguous attempt without authorizing another provider call."""

    workspace_id: str = Field(min_length=1)
    crawl_run_id: UUID
    worker_id: str = Field(min_length=1, max_length=200)
    lease_ttl_seconds: int = Field(ge=3)


class ClaimPersistenceRequest(FrozenContractModel):
    """Resume durable persistence for a recorded provider success; never fetch again."""

    workspace_id: str = Field(min_length=1)
    crawl_run_id: UUID
    worker_id: str = Field(min_length=1, max_length=200)
    lease_ttl_seconds: int = Field(ge=3)


class CrawlLease(FrozenContractModel):
    workspace_id: str = Field(min_length=1)
    crawl_run_id: UUID
    page_id: UUID
    worker_id: str = Field(min_length=1, max_length=200)
    lease_generation: int = Field(ge=1)
    phase: CrawlPhase
    fetch_key: str = Field(min_length=1)
    requested_url: str = Field(min_length=1)
    host: str = Field(min_length=1)
    graph_depth: int | None = Field(default=None, ge=0, le=2)
    expires_at: UtcDatetime


class FetchAttemptRef(FrozenContractModel):
    fetch_attempt_id: UUID
    workspace_id: str = Field(min_length=1)
    crawl_run_id: UUID
    page_id: UUID
    attempt_number: int = Field(ge=1)
    lease_generation: int = Field(ge=1)
    operation_key: str = Field(min_length=1, max_length=200)
    provider_key: str = Field(min_length=1, max_length=64)
    state: FetchAttemptState


class ReconciliationClaim(FrozenContractModel):
    """A new fenced page lease paired with the original ambiguous attempt identity."""

    lease: CrawlLease
    attempt: FetchAttemptRef

    @model_validator(mode="after")
    def _validate_scope_and_state(self) -> ReconciliationClaim:
        if self.lease.workspace_id != self.attempt.workspace_id:
            raise ValueError("reconciliation claim workspace mismatch")
        if self.lease.crawl_run_id != self.attempt.crawl_run_id:
            raise ValueError("reconciliation claim run mismatch")
        if self.lease.page_id != self.attempt.page_id:
            raise ValueError("reconciliation claim page mismatch")
        if self.attempt.state is not FetchAttemptState.SPEND_UNKNOWN:
            raise ValueError("reconciliation claims require a spend_unknown attempt")
        return self


class PersistenceClaim(FrozenContractModel):
    """A new fenced page lease paired with a success waiting for durable persistence."""

    lease: CrawlLease
    attempt: FetchAttemptRef

    @model_validator(mode="after")
    def _validate_scope_and_state(self) -> PersistenceClaim:
        if self.lease.workspace_id != self.attempt.workspace_id:
            raise ValueError("persistence claim workspace mismatch")
        if self.lease.crawl_run_id != self.attempt.crawl_run_id:
            raise ValueError("persistence claim run mismatch")
        if self.lease.page_id != self.attempt.page_id:
            raise ValueError("persistence claim page mismatch")
        if self.attempt.state not in {
            FetchAttemptState.PROVIDER_SUCCEEDED,
            FetchAttemptState.RECONCILED_SUCCEEDED,
            # C4 recovery also owns the narrow crash boundary after the URL-level snapshot commits
            # but before ``complete_page`` clears the page lease. Replaying ``persist_snapshot``
            # returns the existing immutable row and then completes the page without provider I/O.
            FetchAttemptState.PERSISTED,
        }:
            raise ValueError("persistence claims require a recorded or persisted success")
        return self


class ArtifactRef(FrozenContractModel):
    workspace_id: str = Field(min_length=1)
    artifact_key: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_workspace_key(self) -> ArtifactRef:
        if self.artifact_key != f"{self.workspace_id}/{self.content_sha256}":
            raise ValueError("artifact_key must be workspace/content-sha256 addressed")
        return self


class PageSnapshotRef(FrozenContractModel):
    snapshot_id: UUID
    workspace_id: str = Field(min_length=1)
    crawl_run_id: UUID
    page_id: UUID
    fetch_attempt_id: UUID
    requested_url: str = Field(min_length=1)
    final_url: str = Field(min_length=1)
    artifact: ArtifactRef
    fetched_at: UtcDatetime

    @model_validator(mode="after")
    def _validate_artifact_scope(self) -> PageSnapshotRef:
        if self.workspace_id != self.artifact.workspace_id:
            raise ValueError("snapshot and artifact workspace must match")
        return self


class CorpusCheckpointRef(FrozenContractModel):
    checkpoint_id: UUID
    workspace_id: str = Field(min_length=1)
    crawl_run_id: UUID
    phase: CrawlPhase
    version: int = Field(ge=1)
    snapshot_ids: tuple[UUID, ...]
    snapshot_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    coverage: dict[str, JsonValue]
    created_at: UtcDatetime

    @model_validator(mode="after")
    def _validate_snapshot_set(self) -> CorpusCheckpointRef:
        canonical_ids = tuple(sorted(self.snapshot_ids, key=str))
        if self.snapshot_ids != canonical_ids or len(self.snapshot_ids) != len(
            set(self.snapshot_ids)
        ):
            raise ValueError("checkpoint snapshot_ids must be unique and lexically sorted")
        if self.snapshot_set_sha256 != compute_snapshot_set_sha256(self.snapshot_ids):
            raise ValueError("checkpoint snapshot_set_sha256 does not match snapshot_ids")
        return self


class AttemptOutcome(FrozenContractModel):
    disposition: AttemptDisposition
    attempt_state: FetchAttemptState
    page_state: CrawlPageState
    reason_code: str = Field(min_length=1, max_length=120)
    retry_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _validate_disposition(self) -> AttemptOutcome:
        expected: dict[AttemptDisposition, tuple[frozenset[FetchAttemptState], CrawlPageState]] = {
            AttemptDisposition.RETRY_NO_SPEND: (
                frozenset(
                    {
                        FetchAttemptState.RETRYABLE_NO_SPEND,
                        FetchAttemptState.RECONCILED_NO_SPEND,
                    }
                ),
                CrawlPageState.RETRY_WAIT,
            ),
            AttemptDisposition.FAIL_PERMANENT: (
                frozenset({FetchAttemptState.FAILED}),
                CrawlPageState.FAILED,
            ),
            AttemptDisposition.RECONCILE: (
                frozenset({FetchAttemptState.SPEND_UNKNOWN}),
                CrawlPageState.RECONCILIATION_PENDING,
            ),
            AttemptDisposition.QUARANTINE: (
                frozenset({FetchAttemptState.QUARANTINED}),
                CrawlPageState.QUARANTINED,
            ),
        }
        attempt_states, page_state = expected[self.disposition]
        if self.attempt_state not in attempt_states or self.page_state is not page_state:
            raise ValueError("attempt disposition has incompatible attempt/page state")
        if self.disposition is AttemptDisposition.RETRY_NO_SPEND and self.retry_at is None:
            raise ValueError("retry_no_spend requires retry_at")
        if self.disposition is not AttemptDisposition.RETRY_NO_SPEND and self.retry_at is not None:
            raise ValueError("only retry_no_spend may carry retry_at")
        return self


class ReclaimResult(FrozenContractModel):
    requeued_pre_dispatch: int = Field(ge=0)
    moved_to_reconciliation_pending: int = Field(ge=0)
    released_persistence_pending: int = Field(ge=0)


class CrawlProgress(FrozenContractModel):
    workspace_id: str = Field(min_length=1)
    crawl_run_id: UUID
    status: CrawlRunStatus
    queued: int = Field(ge=0)
    leased: int = Field(ge=0)
    provider_active: int = Field(ge=0)
    reconciliation_pending: int = Field(ge=0)
    persistence_pending: int = Field(ge=0)
    fetched: int = Field(ge=0)
    refused: int = Field(ge=0)
    failed: int = Field(ge=0)
    quarantined: int = Field(ge=0)
    spend_unknown: int = Field(ge=0)


class OfficialSiteMaterializationRequest(FrozenContractModel):
    contract_version: Literal["stage0-official-site-c0-v1"] = "stage0-official-site-c0-v1"
    workspace_id: str = Field(min_length=1)
    crawl_run_id: UUID
    recon_run_id: UUID
    claim_run_id: UUID
    client_entity_id: UUID
    checkpoint_id: UUID
    phase: CrawlPhase
    model_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)


class OfficialSiteMaterializationResult(FrozenContractModel):
    workspace_id: str = Field(min_length=1)
    crawl_run_id: UUID
    claim_run_id: UUID
    checkpoint_id: UUID
    source_key: Literal["official_site"] = "official_site"
    client_kb_version: int = Field(ge=1)
    claim_ids: tuple[UUID, ...]
    filled_fields: tuple[str, ...]
    empty_fields: tuple[str, ...]
    failed_fields: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_field_partition(self) -> OfficialSiteMaterializationResult:
        groups = (self.filled_fields, self.empty_fields, self.failed_fields)
        flattened = tuple(field for group in groups for field in group)
        if len(flattened) != len(set(flattened)):
            raise ValueError("materialization field outcomes must be disjoint")
        return self


def enum_manifest() -> dict[str, list[str]]:
    """Stable JSON-ready enum vocabulary pinned by the canonical C0 fixture."""

    enum_types: tuple[type[StrEnum], ...] = (
        CrawlMode,
        CrawlPhase,
        CrawlRunStatus,
        CrawlPageState,
        FetchAttemptState,
        DiscoveredVia,
        LinkRelation,
        CrawlEligibility,
        AliasKind,
        AliasVerificationStatus,
        PolicyOutcome,
        SpendStatus,
        CostKind,
        RetryClass,
        AttemptDisposition,
    )
    return {enum_type.__name__: [member.value for member in enum_type] for enum_type in enum_types}


def compute_snapshot_set_sha256(snapshot_ids: tuple[UUID, ...]) -> str:
    """Hash canonical compact JSON of sorted lowercase UUID strings."""

    payload = json.dumps(
        [str(snapshot_id) for snapshot_id in snapshot_ids],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "AliasKind",
    "AliasVerificationStatus",
    "ArtifactRef",
    "AttemptDisposition",
    "AttemptOutcome",
    "CONTRACT_VERSION",
    "ClaimPersistenceRequest",
    "ClaimReconciliationRequest",
    "ClaimNextRequest",
    "CorpusCheckpointRef",
    "CostKind",
    "CrawlEligibility",
    "CrawlLease",
    "CrawlMode",
    "CrawlPageState",
    "CrawlPhase",
    "CrawlProgress",
    "CrawlRunCreate",
    "CrawlRunRef",
    "CrawlRunStatus",
    "DiscoveryBatch",
    "DiscoveryBatchResult",
    "DiscoveredVia",
    "FetchAttemptRef",
    "FetchAttemptState",
    "HISTORICAL_OFFICIAL_SITE_SOURCE_KEYS",
    "LinkObservation",
    "LinkRelation",
    "OFFICIAL_SITE_SOURCE_KEY",
    "OFFICIAL_SITE_TABLE_NAMES",
    "OfficialSiteCrawlContractConfig",
    "OfficialSiteMaterializationRequest",
    "OfficialSiteMaterializationResult",
    "PageFetchRequest",
    "PageFetchResult",
    "PageFetcherCapabilities",
    "PageSnapshotRef",
    "PersistenceClaim",
    "PolicyOutcome",
    "ProviderResultMetadata",
    "ReconciliationClaim",
    "ReclaimResult",
    "RedirectHop",
    "RetryClass",
    "SpendStatus",
    "UrlObservation",
    "compute_snapshot_set_sha256",
    "enum_manifest",
]
