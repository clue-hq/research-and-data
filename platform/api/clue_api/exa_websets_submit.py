"""Production composition for one durable Exa Websets discovery submit.

This is intentionally an API-root binding: the provider adapter and the durable worker remain
independent packages.  The composition reserves budget and request bytes in PostgreSQL/object
storage, claims one dispatch, performs HTTP outside the transaction, and then makes the response
durable.  Exact replays return the D1 operation without network I/O.

Webhooks, pagination, final cost settlement, items, account identity, claims, and batch sealing are
D3+ concerns. D3 extends this boundary only by transactionally enqueueing the initial poll after a
successful submit; that is lifecycle wiring, not provider retrieval.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from clue_core import (
    DiscoveryBatchId,
    DiscoveryBatchState,
    DiscoveryEnrichmentFormat,
    DiscoveryEntityKind,
    DiscoveryOperation,
    DiscoveryOperationId,
    DiscoveryOperationState,
    DiscoveryPlan,
    DiscoveryRequestFingerprintInput,
    DiscoverySearchPlan,
    DiscoverySpendOutcome,
    DiscoveryWakeReason,
    DiscoveryWakeRequest,
    discovery_provider_external_id,
    discovery_request_fingerprint,
    new_discovery_operation_id,
)
from clue_db import ConnFactory, transaction
from clue_obs.otel import apply_attributes, traced_step
from clue_research.adapters.exa_websets import (
    EXA_WEBSETS_API_BASE,
    EXA_WEBSETS_API_VERSION,
    EXA_WEBSETS_CONTRACT_VERSION,
    EXA_WEBSETS_SOURCE_KEY,
    ExaCreateCriterion,
    ExaCreateEnrichment,
    ExaCreateSearch,
    ExaCreateWebsetRequest,
    ExaEnrichmentOption,
    ExaWebsetDuplicateExternalId,
    ExaWebsetEnrichmentFormat,
    ExaWebsetEntity,
    ExaWebsetEntityType,
    ExaWebsetExchange,
    ExaWebsetsContractDrift,
    ExaWebsetsError,
    ExaWebsetsPreDispatchError,
    ExaWebsetsTransport,
)
from clue_research.durable import (
    DiscoveryNotFound,
    DiscoveryReplayConflict,
    capture_discovery_artifact,
    claim_discovery_operation_dispatch,
    find_reusable_discovery_operation,
    get_discovery_batch,
    get_discovery_operation,
    get_discovery_plan,
    reconcile_discovery_batch_costs,
    reconcile_discovery_batch_state,
    reserve_discovery_operation,
    schedule_discovery_wake,
    update_discovery_batch_state,
    update_discovery_operation,
)
from clue_storage import StorageBackend


class ExaSubmitOutcome(StrEnum):
    CREATED = "created"
    REPLAYED = "replayed"
    JOINED_IN_FLIGHT = "joined_in_flight"
    RECONCILED_DUPLICATE = "reconciled_duplicate"
    RECONCILED_UNCERTAIN = "reconciled_uncertain"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


class ExaWebsetsPricingPolicy(BaseModel):
    """Versioned credit rules plus the deployment's explicit credit valuation.

    Exa settles Websets in credits rather than returning a dollar amount per operation.  The
    monetary fields are therefore an allocation-equivalent attribution, not a claim that Exa
    charged a card for this operation.  The default values the public Pro-plan allocation
    (USD 449 / 100,000 credits); deployments on another plan must inject a differently-versioned
    policy instead of silently reusing this conversion.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "exa-websets-public-credit-policy-2026-08-03+pro-usd-allocation"
    base_result_credits: Decimal = Field(default=Decimal("10"), ge=0)
    standard_enrichment_credits: Decimal = Field(default=Decimal("2"), ge=0)
    contact_enrichment_credits: Decimal = Field(default=Decimal("5"), ge=0)
    import_resolution_credits: Decimal = Field(default=Decimal("2"), ge=0)
    credit_value_cents: Decimal = Field(default=Decimal("0.449"), gt=0)

    def maximum_units(self, search: DiscoverySearchPlan) -> Decimal:
        per_result = self.base_result_credits
        for enrichment in search.enrichments:
            if enrichment.format in {
                DiscoveryEnrichmentFormat.EMAIL,
                DiscoveryEnrichmentFormat.PHONE,
            }:
                per_result += self.contact_enrichment_credits
            else:
                per_result += self.standard_enrichment_credits
        return per_result * search.requested_count

    def monetary_value(self, units: Decimal) -> Decimal:
        return units * self.credit_value_cents

    def maximum_cost_cents(self, search: DiscoverySearchPlan) -> Decimal:
        return self.monetary_value(self.maximum_units(search))

    def maximum_targeted_import_units(
        self,
        *,
        account_count: int,
        formats: Sequence[DiscoveryEnrichmentFormat],
    ) -> Decimal:
        if account_count < 1:
            raise ValueError("targeted import account_count must be positive")
        per_account = self.import_resolution_credits
        for format_ in formats:
            per_account += (
                self.contact_enrichment_credits
                if format_
                in {
                    DiscoveryEnrichmentFormat.EMAIL,
                    DiscoveryEnrichmentFormat.PHONE,
                }
                else self.standard_enrichment_credits
            )
        return per_account * account_count

    def realized_units(
        self,
        *,
        matching_search_results: int,
        ordinary_enrichment_rows: int,
        contact_values: int,
        resolved_import_results: int = 0,
    ) -> ExaWebsetsChargeBreakdown:
        return ExaWebsetsChargeBreakdown(
            matching_search_results=matching_search_results,
            ordinary_enrichment_rows=ordinary_enrichment_rows,
            contact_values=contact_values,
            resolved_import_results=resolved_import_results,
            search_credits=self.base_result_credits * matching_search_results,
            ordinary_enrichment_credits=(
                self.standard_enrichment_credits * ordinary_enrichment_rows
            ),
            contact_enrichment_credits=self.contact_enrichment_credits * contact_values,
            import_credits=self.import_resolution_credits * resolved_import_results,
        )


class ExaWebsetsChargeBreakdown(BaseModel):
    """Auditable application of Exa's public credit rules to terminal provider facts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    matching_search_results: int = Field(ge=0)
    ordinary_enrichment_rows: int = Field(ge=0)
    contact_values: int = Field(ge=0)
    resolved_import_results: int = Field(ge=0)
    search_credits: Decimal = Field(ge=0)
    ordinary_enrichment_credits: Decimal = Field(ge=0)
    contact_enrichment_credits: Decimal = Field(ge=0)
    import_credits: Decimal = Field(ge=0)

    @property
    def total_units(self) -> Decimal:
        return (
            self.search_credits
            + self.ordinary_enrichment_credits
            + self.contact_enrichment_credits
            + self.import_credits
        )


DEFAULT_EXA_WEBSETS_PRICING = ExaWebsetsPricingPolicy()


class ExaSubmitResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: ExaSubmitOutcome
    operation: DiscoveryOperation
    provider_status: str | None = None
    provider_request_id: str | None = None
    dashboard_url: str | None = None
    create_calls: int = Field(ge=0, le=1)
    lookup_calls: int = Field(ge=0)


class ExaSubmitContractError(RuntimeError):
    """The plan, durable lineage, or provider response does not match the paid request."""


_ENTITY_TYPES = {
    DiscoveryEntityKind.COMPANY: ExaWebsetEntityType.COMPANY,
    DiscoveryEntityKind.PERSON: ExaWebsetEntityType.PERSON,
    DiscoveryEntityKind.ARTICLE: ExaWebsetEntityType.ARTICLE,
    DiscoveryEntityKind.RESEARCH_PAPER: ExaWebsetEntityType.RESEARCH_PAPER,
    DiscoveryEntityKind.CUSTOM: ExaWebsetEntityType.CUSTOM,
}

_ENRICHMENT_FORMATS = {
    DiscoveryEnrichmentFormat.TEXT: ExaWebsetEnrichmentFormat.TEXT,
    DiscoveryEnrichmentFormat.NUMBER: ExaWebsetEnrichmentFormat.NUMBER,
    DiscoveryEnrichmentFormat.DATE: ExaWebsetEnrichmentFormat.DATE,
    DiscoveryEnrichmentFormat.URL: ExaWebsetEnrichmentFormat.URL,
    DiscoveryEnrichmentFormat.EMAIL: ExaWebsetEnrichmentFormat.EMAIL,
    DiscoveryEnrichmentFormat.PHONE: ExaWebsetEnrichmentFormat.PHONE,
    DiscoveryEnrichmentFormat.OPTIONS: ExaWebsetEnrichmentFormat.OPTIONS,
}


def exa_request_fingerprint_input(
    *,
    plan: DiscoveryPlan,
    search: DiscoverySearchPlan,
    observation_window: str,
) -> DiscoveryRequestFingerprintInput:
    return DiscoveryRequestFingerprintInput(
        workspace_id=plan.workspace_id,
        source_key=EXA_WEBSETS_SOURCE_KEY,
        provider_api_version=EXA_WEBSETS_API_VERSION,
        entity_type=search.entity_type,
        custom_entity_description=search.custom_entity_description,
        normalized_query=search.normalized_query,
        criteria=search.criteria,
        requested_count=search.requested_count,
        search_behaviour=search.behaviour,
        enrichments=search.enrichments,
        max_people_per_company=search.max_people_per_company,
        icp_key=plan.icp_key,
        icp_version=plan.icp_version,
        discovery_plan_version=plan.plan_version,
        field_policy_version=plan.field_policy_version,
        provider_contract_version=plan.provider_contract_version,
        observation_window=observation_window,
    )


def build_exa_create_request(
    *,
    plan: DiscoveryPlan,
    search: DiscoverySearchPlan,
    observation_window: str,
) -> tuple[str, ExaCreateWebsetRequest]:
    """Compile the immutable platform search into exact Websets v0 wire bytes."""

    if search.channel_key != EXA_WEBSETS_SOURCE_KEY:
        raise ExaSubmitContractError("search is not assigned to the Exa Websets channel")
    if plan.provider_contract_version != EXA_WEBSETS_CONTRACT_VERSION:
        raise ExaSubmitContractError(
            "discovery plan is not pinned to the implemented Exa Websets contract"
        )
    fingerprint = discovery_request_fingerprint(
        exa_request_fingerprint_input(
            plan=plan,
            search=search,
            observation_window=observation_window,
        )
    )
    entity_type = _ENTITY_TYPES[search.entity_type]
    enrichments = tuple(
        ExaCreateEnrichment(
            description=enrichment.description,
            format=_ENRICHMENT_FORMATS[enrichment.format],
            options=tuple(ExaEnrichmentOption(label=option.label) for option in enrichment.options),
            metadata={"clueFieldKey": str(enrichment.field_key)},
        )
        for enrichment in search.enrichments
    )
    request = ExaCreateWebsetRequest(
        search=ExaCreateSearch(
            query=search.normalized_query,
            count=search.requested_count,
            entity=ExaWebsetEntity(
                type=entity_type,
                description=search.custom_entity_description,
            ),
            criteria=tuple(
                ExaCreateCriterion(description=criterion.description)
                for criterion in search.criteria
            ),
            max_people_per_company=search.max_people_per_company,
        ),
        enrichments=enrichments,
        external_id=discovery_provider_external_id(fingerprint),
        metadata={
            "clueFingerprint": fingerprint,
            "clueContractVersion": plan.provider_contract_version,
            "clueSearchKey": search.search_key,
            "clueObservationWindow": observation_window,
        },
    )
    return fingerprint, request


def _search_for(plan: DiscoveryPlan, search_key: str) -> DiscoverySearchPlan:
    matches = [search for search in plan.searches if search.search_key == search_key]
    if len(matches) != 1:
        raise ExaSubmitContractError(f"plan has no unique search {search_key!r}")
    return matches[0]


def assert_exa_response_matches_request(
    request: ExaCreateWebsetRequest,
    exchange: ExaWebsetExchange,
) -> None:
    if request.search is None:
        raise ExaSubmitContractError("discovery response matcher requires a search request")
    webset = exchange.webset
    mismatches: list[str] = []
    if webset.external_id != request.external_id:
        mismatches.append("external_id")
    if any(webset.metadata.get(key) != value for key, value in request.metadata.items()):
        mismatches.append("metadata")
    if webset.imports:
        mismatches.append("imports")
    if webset.excludes:
        mismatches.append("excludes")
    if webset.monitors:
        mismatches.append("monitors")
    if len(webset.searches) != 1:
        mismatches.append("search.count")
    else:
        response_search = webset.searches[0]
        if response_search.webset_id != webset.id:
            mismatches.append("search.webset_id")
        if response_search.query != request.search.query:
            mismatches.append("search.query")
        if response_search.count != request.search.count:
            mismatches.append("search.count_requested")
        requested_entity = request.search.entity
        if response_search.entity != requested_entity:
            mismatches.append("search.entity")
        if response_search.behavior.value != "override":
            mismatches.append("search.behavior")
        if response_search.max_people_per_company != request.search.max_people_per_company:
            mismatches.append("search.max_people_per_company")
        if response_search.exclude:
            mismatches.append("search.exclude")
        if response_search.scope:
            mismatches.append("search.scope")
        if request.search.recall is None and response_search.recall is not None:
            mismatches.append("search.recall")
        requested_criteria = {item.description for item in request.search.criteria}
        response_criteria = {item.description for item in response_search.criteria}
        if (
            len(response_search.criteria) != len(response_criteria)
            or response_criteria != requested_criteria
        ):
            mismatches.append("search.criteria")
    requested_enrichments = {
        item.metadata.get("clueFieldKey"): item for item in request.enrichments
    }
    response_enrichments = {item.metadata.get("clueFieldKey"): item for item in webset.enrichments}
    if (
        None in requested_enrichments
        or None in response_enrichments
        or len(requested_enrichments) != len(request.enrichments)
        or len(response_enrichments) != len(webset.enrichments)
        or requested_enrichments.keys() != response_enrichments.keys()
    ):
        mismatches.append("enrichments.identity")
    else:
        for field_key, requested in requested_enrichments.items():
            response = response_enrichments[field_key]
            if response.webset_id != webset.id:
                mismatches.append(f"enrichments.{field_key}.webset_id")
            if response.description != requested.description:
                mismatches.append(f"enrichments.{field_key}.description")
            requested_format = requested.format
            allowed_formats = {requested_format}
            # Live Websets v0 normalizes email/phone definitions to text while item-level results
            # retain the requested email/phone format.  The field-key metadata remains the stable
            # definition identity and terminal result reconciliation checks the original format.
            if requested_format in {
                ExaWebsetEnrichmentFormat.EMAIL,
                ExaWebsetEnrichmentFormat.PHONE,
            }:
                allowed_formats.add(ExaWebsetEnrichmentFormat.TEXT)
            if response.format not in allowed_formats:
                mismatches.append(f"enrichments.{field_key}.format")
            requested_options = tuple(option.label for option in requested.options)
            response_options = tuple(option.label for option in (response.options or ()))
            if response_options != requested_options:
                mismatches.append(f"enrichments.{field_key}.options")
            if any(
                response.metadata.get(key) != value for key, value in requested.metadata.items()
            ):
                mismatches.append(f"enrichments.{field_key}.metadata")
    if mismatches:
        raise ExaWebsetsContractDrift(
            "reconciled Exa Webset does not match the durable request: " + ", ".join(mismatches),
            status_code=exchange.status_code,
            request_id=exchange.request_id,
            response_body=exchange.response_body,
        )


def _receipt_envelope(
    *,
    kind: str,
    create_error: ExaWebsetsError | None = None,
    lookup_exchange: ExaWebsetExchange | None = None,
    lookup_error: ExaWebsetsError | None = None,
) -> bytes:
    """Preserve every available raw provider body without putting it in logs or relational rows."""

    def _body(raw: bytes | None) -> dict[str, str] | None:
        if raw is None:
            return None
        return {
            "base64": base64.b64encode(raw).decode("ascii"),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    payload = {
        "kind": kind,
        "create": {
            "status": create_error.status_code if create_error else None,
            "requestId": create_error.request_id if create_error else None,
            "errorTag": create_error.error_tag if create_error else None,
            "body": _body(create_error.response_body if create_error else None),
        },
        "lookup": {
            "status": (
                lookup_exchange.status_code
                if lookup_exchange
                else lookup_error.status_code
                if lookup_error
                else None
            ),
            "requestId": (
                lookup_exchange.request_id
                if lookup_exchange
                else lookup_error.request_id
                if lookup_error
                else None
            ),
            "errorTag": lookup_error.error_tag if lookup_error else None,
            "body": _body(
                lookup_exchange.response_body
                if lookup_exchange
                else lookup_error.response_body
                if lookup_error
                else None
            ),
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


class DurableExaWebsetSubmitter:
    """Reserve, submit, reconcile, and replay one Exa discovery operation safely."""

    def __init__(
        self,
        *,
        transport: ExaWebsetsTransport,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
        pricing: ExaWebsetsPricingPolicy = DEFAULT_EXA_WEBSETS_PRICING,
        poll_after_seconds: int = 15,
        in_flight_grace_seconds: int = 60,
    ) -> None:
        if poll_after_seconds < 1 or in_flight_grace_seconds < 1:
            raise ValueError("Exa submit timing values must be positive")
        self._transport = transport
        self._storage = storage
        self._conn_factory = conn_factory
        self._pricing = pricing
        self._poll_after = timedelta(seconds=poll_after_seconds)
        self._in_flight_grace = timedelta(seconds=in_flight_grace_seconds)

    async def submit(
        self,
        *,
        workspace_id: str,
        batch_id: DiscoveryBatchId,
        search_key: str,
        observation_window: str,
    ) -> ExaSubmitResult:
        with traced_step(
            "discovery.exa_websets.submit",
            workspace_id=workspace_id,
            source_key=EXA_WEBSETS_SOURCE_KEY,
            batch_id=str(batch_id),
            search_key=search_key,
            observation_window=observation_window,
        ) as span:
            plan, search = await self._load_lineage(
                workspace_id=workspace_id,
                batch_id=batch_id,
                search_key=search_key,
            )
            fingerprint, request = build_exa_create_request(
                plan=plan,
                search=search,
                observation_window=observation_window,
            )
            operation, created = await self._reserve(
                workspace_id=workspace_id,
                batch_id=batch_id,
                fingerprint=fingerprint,
                observation_window=observation_window,
                request=request,
                reserved_units=self._pricing.maximum_units(search),
                reserved_cost_cents=self._pricing.maximum_cost_cents(search),
            )
            apply_attributes(
                span,
                {
                    "request.fingerprint": fingerprint,
                    "provider.external_id": request.external_id,
                    "operation.id": str(operation.operation_id),
                    "provider.units_reserved": str(operation.provider_units_reserved),
                    "provider.cost_cents_reserved": str(operation.cost_cents_reserved),
                    "replay.hit": not created,
                },
            )

            if (
                not created
                and operation.submitted_receipt_ref
                and (
                    operation.provider_operation_id
                    or operation.state
                    in {
                        DiscoveryOperationState.FAILED_TERMINAL,
                        DiscoveryOperationState.ACCEPTED_TERMINAL_FAILURE,
                        DiscoveryOperationState.CANCELLED,
                    }
                )
            ):
                outcome = (
                    ExaSubmitOutcome.FAILED_TERMINAL
                    if operation.state is DiscoveryOperationState.FAILED_TERMINAL
                    else ExaSubmitOutcome.REPLAYED
                )
                result = ExaSubmitResult(
                    outcome=outcome,
                    operation=operation,
                    create_calls=0,
                    lookup_calls=0,
                )
                apply_attributes(span, {"submit.outcome": result.outcome.value})
                return result

            claimed = await self._claim_dispatch(
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
            )
            if claimed is None:
                fresh = await self._get_operation(
                    workspace_id=workspace_id,
                    operation_id=operation.operation_id,
                )
                if (
                    fresh.state is DiscoveryOperationState.SUBMITTING
                    and fresh.started_at is not None
                    and datetime.now(UTC) - fresh.started_at < self._in_flight_grace
                ):
                    result = ExaSubmitResult(
                        outcome=ExaSubmitOutcome.JOINED_IN_FLIGHT,
                        operation=fresh,
                        create_calls=0,
                        lookup_calls=0,
                    )
                    apply_attributes(span, {"submit.outcome": result.outcome.value})
                    return result
                return await self._reconcile_existing(
                    workspace_id=workspace_id,
                    request=request,
                    operation=fresh,
                )

            try:
                exchange = await self._transport.create_webset(request)
            except ExaWebsetsPreDispatchError:
                failed = await self._persist_predispatch_failure(
                    workspace_id=workspace_id,
                    operation=claimed,
                )
                return ExaSubmitResult(
                    outcome=ExaSubmitOutcome.FAILED_RETRYABLE,
                    operation=failed,
                    create_calls=1,
                    lookup_calls=0,
                )
            except ExaWebsetDuplicateExternalId as exc:
                return await self._lookup_after_create_error(
                    workspace_id=workspace_id,
                    request=request,
                    operation=claimed,
                    create_error=exc,
                    duplicate=True,
                )
            except ExaWebsetsError as exc:
                if exc.dispatch_uncertain:
                    return await self._lookup_after_create_error(
                        workspace_id=workspace_id,
                        request=request,
                        operation=claimed,
                        create_error=exc,
                        duplicate=False,
                    )
                failed = await self._persist_terminal_failure(
                    workspace_id=workspace_id,
                    operation=claimed,
                    error=exc,
                )
                return ExaSubmitResult(
                    outcome=ExaSubmitOutcome.FAILED_TERMINAL,
                    operation=failed,
                    provider_request_id=exc.request_id,
                    create_calls=1,
                    lookup_calls=0,
                )

            try:
                assert_exa_response_matches_request(request, exchange)
            except ExaWebsetsContractDrift as exc:
                return await self._lookup_after_create_error(
                    workspace_id=workspace_id,
                    request=request,
                    operation=claimed,
                    create_error=exc,
                    duplicate=False,
                )
            stored = await self._persist_success(
                workspace_id=workspace_id,
                operation=claimed,
                exchange=exchange,
                receipt_bytes=exchange.response_body,
            )
            result = ExaSubmitResult(
                outcome=ExaSubmitOutcome.CREATED,
                operation=stored,
                provider_status=exchange.webset.status.value,
                provider_request_id=exchange.request_id,
                dashboard_url=exchange.webset.dashboard_url,
                create_calls=1,
                lookup_calls=0,
            )
            apply_attributes(
                span,
                {
                    "submit.outcome": result.outcome.value,
                    "provider.operation_id": exchange.webset.id,
                    "provider.request_id": exchange.request_id or "",
                },
            )
            return result

    async def _load_lineage(
        self,
        *,
        workspace_id: str,
        batch_id: DiscoveryBatchId,
        search_key: str,
    ) -> tuple[DiscoveryPlan, DiscoverySearchPlan]:
        async with self._conn_factory() as conn:
            batch = await get_discovery_batch(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
            )
            if batch is None:
                raise DiscoveryNotFound(f"discovery batch {batch_id}")
            plan_row = await get_discovery_plan(
                conn,
                workspace_id=workspace_id,
                plan_id=batch.discovery_plan_id,
            )
            if plan_row is None:
                raise DiscoveryNotFound(f"discovery plan {batch.discovery_plan_id}")
            if plan_row.plan.provider_policy_version != self._pricing.version:
                raise ExaSubmitContractError(
                    "discovery plan pricing policy does not match the configured Exa policy"
                )
            return plan_row.plan, _search_for(plan_row.plan, search_key)

    async def _reserve(
        self,
        *,
        workspace_id: str,
        batch_id: DiscoveryBatchId,
        fingerprint: str,
        observation_window: str,
        request: ExaCreateWebsetRequest,
        reserved_units: Decimal,
        reserved_cost_cents: Decimal,
    ) -> tuple[DiscoveryOperation, bool]:
        async with self._conn_factory() as conn:
            existing = await find_reusable_discovery_operation(
                conn,
                workspace_id=workspace_id,
                source_key=EXA_WEBSETS_SOURCE_KEY,
                request_fingerprint=fingerprint,
                observation_window=observation_window,
            )
            if existing is not None:
                if existing.batch_id != batch_id:
                    raise DiscoveryReplayConflict(
                        "reusable Exa request belongs to a different discovery batch; explicit "
                        "cross-generation snapshot reuse is not implemented"
                    )
                return existing, False
            request_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=workspace_id,
                content=request.canonical_bytes(),
                media_type="application/json",
                source_key=EXA_WEBSETS_SOURCE_KEY,
                source_url=f"{EXA_WEBSETS_API_BASE}/websets",
            )
            operation = DiscoveryOperation(
                operation_id=new_discovery_operation_id(),
                batch_id=batch_id,
                workspace_id=workspace_id,
                source_key=EXA_WEBSETS_SOURCE_KEY,
                provider_api_version=EXA_WEBSETS_API_VERSION,
                request_fingerprint=fingerprint,
                observation_window=observation_window,
                provider_external_id=request.external_id,
                state=DiscoveryOperationState.PLANNED,
                spend_outcome=DiscoverySpendOutcome.NOT_DISPATCHED,
                raw_request_artifact_key=request_key,
                provider_units_reserved=reserved_units,
                cost_cents_reserved=reserved_cost_cents,
            )
            stored, created = await reserve_discovery_operation(
                conn,
                workspace_id=workspace_id,
                operation=operation,
            )
            if created:
                await update_discovery_batch_state(
                    conn,
                    workspace_id=workspace_id,
                    batch_id=batch_id,
                    state=DiscoveryBatchState.SUBMITTING,
                )
            return stored, created

    async def _claim_dispatch(
        self,
        *,
        workspace_id: str,
        operation_id: DiscoveryOperationId,
    ) -> DiscoveryOperation | None:
        async with self._conn_factory() as conn:
            return await claim_discovery_operation_dispatch(
                conn,
                workspace_id=workspace_id,
                operation_id=operation_id,
            )

    async def _get_operation(
        self,
        *,
        workspace_id: str,
        operation_id: DiscoveryOperationId,
    ) -> DiscoveryOperation:
        async with self._conn_factory() as conn:
            operation = await get_discovery_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=operation_id,
            )
            if operation is None:
                raise DiscoveryNotFound(f"discovery operation {operation_id}")
            return operation

    async def _persist_success(
        self,
        *,
        workspace_id: str,
        operation: DiscoveryOperation,
        exchange: ExaWebsetExchange,
        receipt_bytes: bytes,
    ) -> DiscoveryOperation:
        async with self._conn_factory() as conn:
            receipt_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=workspace_id,
                content=receipt_bytes,
                media_type="application/json",
                source_key=EXA_WEBSETS_SOURCE_KEY,
                source_url=f"{EXA_WEBSETS_API_BASE}/websets/{exchange.webset.id}",
            )
            current = await get_discovery_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
            )
            if current is None:
                raise DiscoveryNotFound(f"discovery operation {operation.operation_id}")
            next_poll_at = datetime.now(UTC) + self._poll_after
            updated = current.model_copy(
                update={
                    "provider_operation_id": exchange.webset.id,
                    "state": DiscoveryOperationState.PROVIDER_RUNNING,
                    # Exa accepts the paid operation, but does not report final realized credits on
                    # create.  D3 settles charged units from the completed operation; zero is the
                    # only honest realized value at this boundary.
                    "spend_outcome": DiscoverySpendOutcome.CHARGED,
                    "provider_units_charged": Decimal(0),
                    "cost_cents_charged": Decimal(0),
                    "submitted_receipt_ref": receipt_key,
                    "next_poll_at": next_poll_at,
                }
            )
            stored = await update_discovery_operation(
                conn,
                workspace_id=workspace_id,
                operation=updated,
            )
            await reconcile_discovery_batch_costs(
                conn,
                workspace_id=workspace_id,
                batch_id=operation.batch_id,
            )
            await reconcile_discovery_batch_state(
                conn, workspace_id=workspace_id, batch_id=operation.batch_id
            )
            batch = await get_discovery_batch(
                conn, workspace_id=workspace_id, batch_id=operation.batch_id
            )
            if batch is None:
                raise DiscoveryNotFound(f"discovery batch {operation.batch_id}")
            await schedule_discovery_wake(
                conn,
                workspace_id=workspace_id,
                request=DiscoveryWakeRequest(
                    workspace_id=workspace_id,
                    project_run_id=batch.project_run_id,
                    discovery_batch_id=batch.id,
                    operation_id=operation.operation_id,
                    reason=DiscoveryWakeReason.SCHEDULED_POLL,
                    available_at=next_poll_at,
                    dedupe_key=f"exa-initial-poll:{operation.operation_id}",
                ),
            )
            return stored

    async def _lookup_after_create_error(
        self,
        *,
        workspace_id: str,
        request: ExaCreateWebsetRequest,
        operation: DiscoveryOperation,
        create_error: ExaWebsetsError,
        duplicate: bool,
    ) -> ExaSubmitResult:
        try:
            exchange = await self._transport.get_webset(request.external_id)
            assert_exa_response_matches_request(request, exchange)
        except ExaWebsetsError as lookup_error:
            receipt = _receipt_envelope(
                kind="duplicate_lookup_failed" if duplicate else "uncertain_lookup_failed",
                create_error=create_error,
                lookup_error=lookup_error,
            )
            unknown = await self._persist_unknown_spend(
                workspace_id=workspace_id,
                operation=operation,
                receipt=receipt,
            )
            return ExaSubmitResult(
                outcome=ExaSubmitOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                provider_request_id=create_error.request_id,
                create_calls=1,
                lookup_calls=1,
            )
        receipt = _receipt_envelope(
            kind="duplicate_reconciled" if duplicate else "uncertain_reconciled",
            create_error=create_error,
            lookup_exchange=exchange,
        )
        stored = await self._persist_success(
            workspace_id=workspace_id,
            operation=operation,
            exchange=exchange,
            receipt_bytes=receipt,
        )
        return ExaSubmitResult(
            outcome=(
                ExaSubmitOutcome.RECONCILED_DUPLICATE
                if duplicate
                else ExaSubmitOutcome.RECONCILED_UNCERTAIN
            ),
            operation=stored,
            provider_status=exchange.webset.status.value,
            provider_request_id=exchange.request_id,
            dashboard_url=exchange.webset.dashboard_url,
            create_calls=1,
            lookup_calls=1,
        )

    async def _reconcile_existing(
        self,
        *,
        workspace_id: str,
        request: ExaCreateWebsetRequest,
        operation: DiscoveryOperation,
    ) -> ExaSubmitResult:
        try:
            exchange = await self._transport.get_webset(request.external_id)
            assert_exa_response_matches_request(request, exchange)
        except ExaWebsetsError as lookup_error:
            receipt = _receipt_envelope(
                kind="stale_submit_lookup_failed",
                lookup_error=lookup_error,
            )
            unknown = await self._persist_unknown_spend(
                workspace_id=workspace_id,
                operation=operation,
                receipt=receipt,
            )
            return ExaSubmitResult(
                outcome=ExaSubmitOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                provider_request_id=lookup_error.request_id,
                create_calls=0,
                lookup_calls=1,
            )
        stored = await self._persist_success(
            workspace_id=workspace_id,
            operation=operation,
            exchange=exchange,
            receipt_bytes=_receipt_envelope(
                kind="stale_submit_reconciled",
                lookup_exchange=exchange,
            ),
        )
        return ExaSubmitResult(
            outcome=ExaSubmitOutcome.RECONCILED_UNCERTAIN,
            operation=stored,
            provider_status=exchange.webset.status.value,
            provider_request_id=exchange.request_id,
            dashboard_url=exchange.webset.dashboard_url,
            create_calls=0,
            lookup_calls=1,
        )

    async def _persist_predispatch_failure(
        self,
        *,
        workspace_id: str,
        operation: DiscoveryOperation,
    ) -> DiscoveryOperation:
        async with self._conn_factory() as conn:
            current = await get_discovery_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
            )
            if current is None:
                raise DiscoveryNotFound(f"discovery operation {operation.operation_id}")
            failed = current.model_copy(
                update={
                    "state": DiscoveryOperationState.FAILED_RETRYABLE,
                    "spend_outcome": DiscoverySpendOutcome.NOT_DISPATCHED,
                    "next_poll_at": None,
                }
            )
            stored = await update_discovery_operation(
                conn,
                workspace_id=workspace_id,
                operation=failed,
            )
            await update_discovery_batch_state(
                conn,
                workspace_id=workspace_id,
                batch_id=operation.batch_id,
                state=DiscoveryBatchState.FAILED_RETRYABLE,
                failure_code="exa_predispatch_transport",
            )
            return stored

    async def _persist_unknown_spend(
        self,
        *,
        workspace_id: str,
        operation: DiscoveryOperation,
        receipt: bytes,
    ) -> DiscoveryOperation:
        async with self._conn_factory() as conn:
            receipt_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=workspace_id,
                content=receipt,
                media_type="application/json",
                source_key=EXA_WEBSETS_SOURCE_KEY,
                source_url=f"{EXA_WEBSETS_API_BASE}/websets/{operation.provider_external_id}",
            )
            current = await get_discovery_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
            )
            if current is None:
                raise DiscoveryNotFound(f"discovery operation {operation.operation_id}")
            unknown = current.model_copy(
                update={
                    "state": DiscoveryOperationState.SPEND_OUTCOME_UNKNOWN,
                    "spend_outcome": DiscoverySpendOutcome.UNKNOWN,
                    "submitted_receipt_ref": receipt_key,
                    "next_poll_at": None,
                }
            )
            stored = await update_discovery_operation(
                conn,
                workspace_id=workspace_id,
                operation=unknown,
            )
            await update_discovery_batch_state(
                conn,
                workspace_id=workspace_id,
                batch_id=operation.batch_id,
                state=DiscoveryBatchState.SPEND_OUTCOME_UNKNOWN,
                failure_code="exa_submit_outcome_unknown",
            )
            return stored

    async def _persist_terminal_failure(
        self,
        *,
        workspace_id: str,
        operation: DiscoveryOperation,
        error: ExaWebsetsError,
    ) -> DiscoveryOperation:
        receipt = _receipt_envelope(kind="terminal_create_failure", create_error=error)
        async with self._conn_factory() as conn:
            receipt_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=workspace_id,
                content=receipt,
                media_type="application/json",
                source_key=EXA_WEBSETS_SOURCE_KEY,
                source_url=f"{EXA_WEBSETS_API_BASE}/websets",
            )
            current = await get_discovery_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
            )
            if current is None:
                raise DiscoveryNotFound(f"discovery operation {operation.operation_id}")
            failed = current.model_copy(
                update={
                    "state": DiscoveryOperationState.FAILED_TERMINAL,
                    "spend_outcome": DiscoverySpendOutcome.NOT_CHARGED,
                    "submitted_receipt_ref": receipt_key,
                    "terminal_at": datetime.now(UTC),
                    "next_poll_at": None,
                }
            )
            stored = await update_discovery_operation(
                conn,
                workspace_id=workspace_id,
                operation=failed,
            )
            await reconcile_discovery_batch_costs(
                conn,
                workspace_id=workspace_id,
                batch_id=operation.batch_id,
            )
            await update_discovery_batch_state(
                conn,
                workspace_id=workspace_id,
                batch_id=operation.batch_id,
                state=DiscoveryBatchState.FAILED_TERMINAL,
                failure_code=f"exa_http_{error.status_code or 'error'}",
            )
            return stored


__all__ = [
    "DEFAULT_EXA_WEBSETS_PRICING",
    "DurableExaWebsetSubmitter",
    "ExaSubmitContractError",
    "ExaSubmitOutcome",
    "ExaSubmitResult",
    "ExaWebsetsPricingPolicy",
    "build_exa_create_request",
    "exa_request_fingerprint_input",
]
