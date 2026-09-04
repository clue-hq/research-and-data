"""M6A E1: seal-bound, import-only Exa enrichment for selected accounts.

The coordinator is deliberately outside the discovery phase. It reads the immutable D5 manifest
and human tier claims, reserves a separate durable operation, then performs Exa's documented CSV
import -> upload -> import-only Webset flow. No discovery operation or sealed field decision is
updated by this module.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.discovery_seal import DbSealedDiscoveryAccountManifestReader
from clue_api.exa_websets_materialization import (
    ensure_exa_company_field_claim,
    exa_enrichment_value,
)
from clue_api.exa_websets_submit import (
    DEFAULT_EXA_WEBSETS_PRICING,
    ExaWebsetsPricingPolicy,
)
from clue_config import Secrets, Settings
from clue_core import (
    BudgetScope,
    DiscoveryEnrichmentFormat,
    EntityId,
    EntityType,
    ProjectPhase,
    ProjectRunId,
    ResearchMode,
    RunId,
    TargetedEnrichmentFieldPlan,
    TargetedEnrichmentFieldResult,
    TargetedEnrichmentFieldState,
    TargetedEnrichmentOperation,
    TargetedEnrichmentOperationId,
    TargetedEnrichmentRequest,
    TargetedEnrichmentSpendOutcome,
    TargetedEnrichmentState,
    TargetedEnrichmentTarget,
    new_targeted_enrichment_operation_id,
)
from clue_db import ConnFactory, transaction
from clue_obs.otel import apply_attributes, traced_step
from clue_research.adapters.exa_websets import (
    EXA_WEBSETS_API_BASE,
    EXA_WEBSETS_API_VERSION,
    EXA_WEBSETS_CONTRACT_VERSION,
    EXA_WEBSETS_SOURCE_KEY,
    ExaCreateEnrichment,
    ExaCreateImportRef,
    ExaCreateImportRequest,
    ExaCreateWebsetRequest,
    ExaEnrichmentOption,
    ExaImport,
    ExaImportStatus,
    ExaResponseEnrichment,
    ExaWebsetEnrichmentFormat,
    ExaWebsetEntity,
    ExaWebsetEntityType,
    ExaWebsetExchange,
    ExaWebsetItem,
    ExaWebsetItemCompanyProperties,
    ExaWebsetNotFound,
    ExaWebsetsClient,
    ExaWebsetsContractDrift,
    ExaWebsetsError,
    ExaWebsetsImportTransport,
    ExaWebsetsPreDispatchError,
    ExaWebsetStatus,
    normalize_exa_discovery_company_item,
)
from clue_research.claimstore import (
    WorkspaceScope,
    claims_for,
    load_core_pack,
    record_run_lineage,
)
from clue_research.discovery_scoring.discovery import REVENUE_BAND_OPTIONS
from clue_research.discovery_scoring.tiering import (
    ACCOUNT_RESEARCH_ELIGIBLE_TIERS,
    TIER_CLAIM_MAX_SOURCE_TIER,
    TIER_FIELD,
)
from clue_research.durable import (
    BudgetEngine,
    DbBudgetStore,
    DiscoverySealConflict,
    ProjectRunStatus,
    TargetedEnrichmentItemSnapshot,
    TargetedEnrichmentNotFound,
    TargetedEnrichmentReplayConflict,
    append_targeted_enrichment_artifact,
    bind_discovery_artifact_subject,
    capture_discovery_artifact,
    claim_due_targeted_enrichment_operations,
    claim_targeted_enrichment_dispatch,
    fail_targeted_enrichment_predispatch,
    find_targeted_enrichment_operation,
    get_project_run,
    get_targeted_enrichment_operation,
    list_targeted_enrichment_artifacts,
    put_targeted_enrichment_field_result,
    put_targeted_enrichment_item,
    reserve_targeted_enrichment_operation,
    update_targeted_enrichment_operation,
)
from clue_research.identity import canonical_member_ids, get_account, surviving_id
from clue_research.sources import seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack
from clue_storage import StorageBackend, content_address

EXA_TARGETED_FIELD_POLICY_VERSION = "exa-targeted-company-fields-v1"

_FORMATS = {
    DiscoveryEnrichmentFormat.TEXT: ExaWebsetEnrichmentFormat.TEXT,
    DiscoveryEnrichmentFormat.NUMBER: ExaWebsetEnrichmentFormat.NUMBER,
    DiscoveryEnrichmentFormat.DATE: ExaWebsetEnrichmentFormat.DATE,
    DiscoveryEnrichmentFormat.URL: ExaWebsetEnrichmentFormat.URL,
    DiscoveryEnrichmentFormat.EMAIL: ExaWebsetEnrichmentFormat.EMAIL,
    DiscoveryEnrichmentFormat.PHONE: ExaWebsetEnrichmentFormat.PHONE,
    DiscoveryEnrichmentFormat.OPTIONS: ExaWebsetEnrichmentFormat.OPTIONS,
}

_APPROVED_FIELD_PLANS: dict[str, TargetedEnrichmentFieldPlan] = {
    "core.annual_revenue": TargetedEnrichmentFieldPlan(
        field_key="core.annual_revenue",
        description="Find the latest supported annual revenue amount in USD.",
        format=DiscoveryEnrichmentFormat.NUMBER,
    ),
    "core.company_email": TargetedEnrichmentFieldPlan(
        field_key="core.company_email",
        description="Find one official public company contact email address.",
        format=DiscoveryEnrichmentFormat.EMAIL,
    ),
    "core.company_linkedin_url": TargetedEnrichmentFieldPlan(
        field_key="core.company_linkedin_url",
        description="Find the official LinkedIn company URL.",
        format=DiscoveryEnrichmentFormat.URL,
    ),
    "core.company_phone": TargetedEnrichmentFieldPlan(
        field_key="core.company_phone",
        description="Find one official public company phone number.",
        format=DiscoveryEnrichmentFormat.PHONE,
    ),
    "core.revenue_band": TargetedEnrichmentFieldPlan(
        field_key="core.revenue_band",
        description="Select the best supported annual revenue band.",
        format=DiscoveryEnrichmentFormat.OPTIONS,
        options=REVENUE_BAND_OPTIONS,
    ),
}

TargetedTransportFactory = Callable[[], AbstractAsyncContextManager[ExaWebsetsImportTransport]]


class ExaTargetedEnrichmentError(RuntimeError):
    pass


class ExaTargetedEligibilityError(ExaTargetedEnrichmentError):
    pass


class ExaTargetedOutcome(StrEnum):
    CREATED = "created"
    WAITING_EXTERNAL = "waiting_external"
    SUCCEEDED = "succeeded"
    REPLAYED = "replayed"
    JOINED_IN_FLIGHT = "joined_in_flight"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"


class ExaTargetedEnrichmentPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = EXA_TARGETED_FIELD_POLICY_VERSION
    maximum_accounts: int = Field(default=10, ge=1, le=100)
    maximum_fields: int = Field(default=5, ge=1, le=10)
    maximum_provider_credits: int = Field(default=200, ge=1)
    eligible_tiers: frozenset[str] = ACCOUNT_RESEARCH_ELIGIBLE_TIERS


DEFAULT_EXA_TARGETED_ENRICHMENT_POLICY = ExaTargetedEnrichmentPolicy()


def approved_targeted_field_plans(
    field_keys: Sequence[str],
) -> tuple[TargetedEnrichmentFieldPlan, ...]:
    """Resolve caller field keys through the versioned E1 allowlist.

    Provider prompts/formats/options are platform policy, never caller-controlled free text.
    """

    unique = tuple(sorted(set(field_keys)))
    if not unique:
        raise ExaTargetedEligibilityError("targeted enrichment requires at least one field")
    unknown = tuple(value for value in unique if value not in _APPROVED_FIELD_PLANS)
    if unknown:
        raise ExaTargetedEligibilityError(
            f"targeted enrichment field(s) are not approved: {', '.join(unknown)}"
        )
    return tuple(_APPROVED_FIELD_PLANS[value] for value in unique)


class ExaTargetedPreflight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    request: TargetedEnrichmentRequest
    csv_bytes: bytes
    maximum_provider_credits: Decimal
    maximum_cost_cents: Decimal


class ExaTargetedResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: ExaTargetedOutcome
    operation: TargetedEnrichmentOperation
    import_calls: int = Field(default=0, ge=0)
    upload_calls: int = Field(default=0, ge=0)
    create_calls: int = Field(default=0, ge=0)
    lookup_calls: int = Field(default=0, ge=0)
    poll_calls: int = Field(default=0, ge=0)
    item_page_calls: int = Field(default=0, ge=0)
    claims_created: int = Field(default=0, ge=0)
    claims_reused: int = Field(default=0, ge=0)
    resolved_fields: int = Field(default=0, ge=0)
    missing_fields: int = Field(default=0, ge=0)
    unresolved_import_fields: int = Field(default=0, ge=0)


def _csv_bytes(targets: Sequence[TargetedEnrichmentTarget]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["url"])
    for target in targets:
        writer.writerow([target.identifier_url])
    return output.getvalue().encode("utf-8")


def _identifier_url(primary_domain: str) -> str:
    domain = primary_domain.strip().lower().rstrip(".")
    if not domain or "/" in domain or ":" in domain or "@" in domain:
        raise ExaTargetedEligibilityError("selected account has an invalid primary domain")
    return f"https://{domain}/"


def _canonical_identifier(value: str) -> str:
    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.").rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host:
        raise ExaWebsetsContractDrift("Exa import item returned an invalid sourceEntityId")
    port = f":{parsed.port}" if parsed.port not in {None, 80, 443} else ""
    return f"{host}{port}"


def _provider_external_id(fingerprint: str) -> str:
    return f"clue-e1-{fingerprint}"


async def _bind_targeted_artifact_subjects(
    conn: AsyncConnection,
    *,
    operation: TargetedEnrichmentOperation,
    artifact_key: str,
    reference_kind: str,
    reference_id: str,
) -> None:
    for target in operation.request.targets:
        await bind_discovery_artifact_subject(
            conn,
            workspace_id=operation.request.workspace_id,
            artifact_key_value=artifact_key,
            subject_kind="account",
            subject_entity_id=target.account_id,
            reference_kind=reference_kind,
            reference_id=reference_id,
        )


async def compile_exa_targeted_preflight(
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    account_ids: Sequence[EntityId],
    fields: Sequence[TargetedEnrichmentFieldPlan],
    observation_window: str,
    storage: StorageBackend,
    conn_factory: ConnFactory = transaction,
    policy: ExaTargetedEnrichmentPolicy = DEFAULT_EXA_TARGETED_ENRICHMENT_POLICY,
    pricing: ExaWebsetsPricingPolicy = DEFAULT_EXA_WEBSETS_PRICING,
) -> ExaTargetedPreflight:
    """Resolve seal/tier/account lineage and produce the exact bounded paid request."""

    canonical_accounts = tuple(sorted(set(account_ids), key=str))
    canonical_fields = tuple(sorted(fields, key=lambda field: str(field.field_key)))
    if not canonical_accounts:
        raise ExaTargetedEligibilityError("targeted enrichment requires at least one account")
    if len(canonical_accounts) > policy.maximum_accounts:
        raise ExaTargetedEligibilityError("targeted enrichment account count exceeds policy")
    if not canonical_fields or len(canonical_fields) > policy.maximum_fields:
        raise ExaTargetedEligibilityError("targeted enrichment field count exceeds policy")
    if len(canonical_fields) != len({field.field_key for field in canonical_fields}):
        raise ExaTargetedEligibilityError("targeted enrichment fields must be unique")
    for field in canonical_fields:
        expected = _APPROVED_FIELD_PLANS.get(str(field.field_key))
        if expected is None or field != expected:
            raise ExaTargetedEligibilityError(
                f"field {field.field_key!s} does not match the approved field plan"
            )

    reader = DbSealedDiscoveryAccountManifestReader(storage=storage, conn_factory=conn_factory)
    async with conn_factory() as conn:
        run = await get_project_run(conn, project_run_id)
        if run is None:
            raise ExaTargetedEligibilityError("targeted enrichment project run does not exist")
        if run.workspace_id != workspace_id:
            raise ExaTargetedEligibilityError("targeted enrichment project run is cross-workspace")
        if run.status is not ProjectRunStatus.ACTIVE or run.phase is not ProjectPhase.DEEP:
            raise ExaTargetedEligibilityError(
                "targeted enrichment requires an active project run in deep phase"
            )
    try:
        sealed = await reader.read(
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            icp_key=run.icp_key,
            icp_version=run.icp_version,
        )
    except DiscoverySealConflict as exc:
        raise ExaTargetedEligibilityError(
            "targeted enrichment requires an intact sealed discovery batch"
        ) from exc
    if sealed is None:
        raise ExaTargetedEligibilityError("targeted enrichment requires a sealed discovery batch")
    sealed_ids = set(sealed.account_ids)
    scope = WorkspaceScope.for_workspace(workspace_id)
    targets: list[TargetedEnrichmentTarget] = []
    async with conn_factory() as conn:
        for account_id in canonical_accounts:
            if account_id not in sealed_ids:
                raise ExaTargetedEligibilityError("target account is absent from the exact seal")
            if await surviving_id(conn, account_id, EntityType.ACCOUNT) != account_id:
                raise ExaTargetedEligibilityError("target account is not the canonical survivor")
            account = await get_account(conn, account_id)
            if (
                account is None
                or account.workspace_id != workspace_id
                or not account.primary_domain
            ):
                raise ExaTargetedEligibilityError(
                    "target account lacks workspace-local primary domain"
                )
            tier_claims = await claims_for(conn, account_id, TIER_FIELD, scope=scope)
            matching = []
            for claim in tier_claims:
                value = claim.value_json
                if not isinstance(value, dict):
                    continue
                if (
                    claim.source_tier <= TIER_CLAIM_MAX_SOURCE_TIER
                    and value.get("decision_basis") == "discovery_criteria"
                    and value.get("project_run_id") == str(project_run_id)
                    and value.get("discovery_batch_id") == str(sealed.discovery_batch_id)
                    and value.get("discovery_seal_sha256") == sealed.seal_sha256
                    and value.get("icp_key") == run.icp_key
                    and value.get("icp_version") == run.icp_version
                    and value.get("disposition") == "selected"
                    and value.get("tier") in policy.eligible_tiers
                ):
                    matching.append(claim)
            if len(matching) != 1:
                raise ExaTargetedEligibilityError(
                    "target account lacks one exact live selected tier decision"
                )
            targets.append(
                TargetedEnrichmentTarget(
                    account_id=account_id,
                    identifier_url=_identifier_url(account.primary_domain),
                    tier_claim_id=matching[0].id,
                )
            )

    maximum_units = pricing.maximum_targeted_import_units(
        account_count=len(targets), formats=[field.format for field in canonical_fields]
    )
    if maximum_units != maximum_units.to_integral_value():
        raise ExaTargetedEnrichmentError("targeted enrichment credit reservation is not integral")
    if maximum_units > policy.maximum_provider_credits:
        raise ExaTargetedEligibilityError("targeted enrichment exceeds the provider credit cap")
    maximum_cost = pricing.monetary_value(maximum_units)
    request = TargetedEnrichmentRequest(
        workspace_id=workspace_id,
        project_id=run.project_id,
        project_run_id=project_run_id,
        icp_key=run.icp_key,
        icp_version=run.icp_version,
        discovery_batch_id=sealed.discovery_batch_id,
        discovery_seal_sha256=sealed.seal_sha256,
        source_key=EXA_WEBSETS_SOURCE_KEY,
        provider_api_version=EXA_WEBSETS_API_VERSION,
        provider_contract_version=EXA_WEBSETS_CONTRACT_VERSION,
        pricing_policy_version=pricing.version,
        field_policy_version=policy.version,
        observation_window=observation_window,
        targets=tuple(targets),
        fields=canonical_fields,
        provider_credit_cap=int(maximum_units),
        money_budget_cap_cents=maximum_cost,
    )
    return ExaTargetedPreflight(
        request=request,
        csv_bytes=_csv_bytes(request.targets),
        maximum_provider_credits=maximum_units,
        maximum_cost_cents=maximum_cost,
    )


def build_exa_import_request(preflight: ExaTargetedPreflight) -> ExaCreateImportRequest:
    request = preflight.request
    return ExaCreateImportRequest(
        size=len(preflight.csv_bytes),
        count=len(request.targets),
        entity=ExaWebsetEntity(type=ExaWebsetEntityType.COMPANY),
        title=f"Clue selected accounts {request.request_fingerprint[:12]}",
        metadata={
            "clueFingerprint": request.request_fingerprint,
            "clueDiscoverySeal": request.discovery_seal_sha256,
        },
    )


def build_exa_import_webset_request(
    request: TargetedEnrichmentRequest, *, import_id: str
) -> ExaCreateWebsetRequest:
    enrichments = tuple(
        ExaCreateEnrichment(
            description=field.description,
            format=_FORMATS[field.format],
            options=tuple(ExaEnrichmentOption(label=option) for option in field.options),
            metadata={"clueFieldKey": str(field.field_key)},
        )
        for field in request.fields
    )
    return ExaCreateWebsetRequest(
        imports=(ExaCreateImportRef(source="import", id=import_id),),
        enrichments=enrichments,
        external_id=_provider_external_id(request.request_fingerprint),
        metadata={
            "clueFingerprint": request.request_fingerprint,
            "clueContractVersion": request.provider_contract_version,
            "clueObservationWindow": request.observation_window,
            "clueDiscoverySeal": request.discovery_seal_sha256,
            "clueOperationKind": "targeted_import_enrichment",
        },
    )


def _definitions_match(
    requested: Sequence[ExaCreateEnrichment],
    returned: Sequence[ExaResponseEnrichment],
    *,
    webset_id: str,
) -> bool:
    expected = {value.metadata.get("clueFieldKey"): value for value in requested}
    actual = {value.metadata.get("clueFieldKey"): value for value in returned}
    if (
        None in expected
        or None in actual
        or len(expected) != len(requested)
        or len(actual) != len(returned)
        or expected.keys() != actual.keys()
    ):
        return False
    for key, request in expected.items():
        response = actual[key]
        allowed = {request.format}
        if request.format in {ExaWebsetEnrichmentFormat.EMAIL, ExaWebsetEnrichmentFormat.PHONE}:
            allowed.add(ExaWebsetEnrichmentFormat.TEXT)
        if (
            response.webset_id != webset_id
            or response.description != request.description
            or response.format not in allowed
            or response.options != (request.options or None)
            or any(response.metadata.get(k) != v for k, v in request.metadata.items())
        ):
            return False
    return True


def assert_exa_import_webset_matches(
    request: ExaCreateWebsetRequest,
    exchange: ExaWebsetExchange,
    *,
    expected_count: int,
) -> ExaImport:
    webset = exchange.webset
    if request.search is not None or len(request.imports) != 1:
        raise ExaWebsetsContractDrift("E1 requires an import-only Webset request")
    expected_import_id = request.imports[0].id
    valid = (
        webset.external_id == request.external_id
        and not webset.searches
        and len(webset.imports) == 1
        and webset.imports[0].id == expected_import_id
        and webset.imports[0].format.value == "csv"
        and webset.imports[0].entity == ExaWebsetEntity(type=ExaWebsetEntityType.COMPANY)
        and webset.imports[0].integral_count == expected_count
        and not webset.monitors
        and not webset.excludes
        and all(webset.metadata.get(key) == value for key, value in request.metadata.items())
        and _definitions_match(request.enrichments, webset.enrichments, webset_id=webset.id)
    )
    if not valid:
        raise ExaWebsetsContractDrift(
            "Exa import-only Webset does not match the pinned E1 request",
            status_code=exchange.status_code,
            request_id=exchange.request_id,
            response_body=exchange.response_body,
        )
    return webset.imports[0]


class ExaTargetedEnrichmentCoordinator:
    def __init__(
        self,
        *,
        transport: ExaWebsetsImportTransport,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
        pricing: ExaWebsetsPricingPolicy = DEFAULT_EXA_WEBSETS_PRICING,
        poll_after_seconds: int = 15,
        in_flight_grace_seconds: int = 60,
        budget: BudgetEngine | None = None,
        enforce_budget: bool = True,
    ) -> None:
        if poll_after_seconds < 1 or in_flight_grace_seconds < 1:
            raise ValueError("targeted enrichment timing values must be positive")
        self._transport = transport
        self._storage = storage
        self._conn_factory = conn_factory
        self._pricing = pricing
        self._poll_after = timedelta(seconds=poll_after_seconds)
        self._in_flight_grace = timedelta(seconds=in_flight_grace_seconds)
        self._budget = budget or BudgetEngine(store=DbBudgetStore(conn_factory=conn_factory))
        # FI pilot budget-controls: threaded from ``Settings.budget_controls_enabled`` at
        # the composition root and passed to the durable reservation, which stops raising
        # on the project-run cap while writing every ledger row unchanged.
        self._enforce_budget = enforce_budget

    async def start(self, preflight: ExaTargetedPreflight) -> ExaTargetedResult:
        request = preflight.request
        with traced_step(
            "enrichment.exa_websets.targeted.start",
            workspace_id=request.workspace_id,
            project_run_id=str(request.project_run_id),
            discovery_batch_id=str(request.discovery_batch_id),
            account_count=len(request.targets),
            field_count=len(request.fields),
        ) as span:
            operation, created = await self._reserve(preflight)
            if operation.state is TargetedEnrichmentState.SUCCEEDED:
                result = ExaTargetedResult(outcome=ExaTargetedOutcome.REPLAYED, operation=operation)
                apply_attributes(span, {"replay.hit": True, "outcome": result.outcome.value})
                return result
            if operation.state in {
                TargetedEnrichmentState.FAILED_TERMINAL,
                TargetedEnrichmentState.CANCELLED,
            }:
                return ExaTargetedResult(
                    outcome=ExaTargetedOutcome.FAILED_TERMINAL, operation=operation
                )
            if operation.state is TargetedEnrichmentState.SPEND_OUTCOME_UNKNOWN:
                return ExaTargetedResult(
                    outcome=ExaTargetedOutcome.SPEND_OUTCOME_UNKNOWN,
                    operation=operation,
                )
            if operation.provider_operation_id is not None:
                return ExaTargetedResult(
                    outcome=ExaTargetedOutcome.WAITING_EXTERNAL, operation=operation
                )

            claimed = await self._claim(operation)
            if claimed is None:
                fresh = await self._get(request.workspace_id, operation.operation_id)
                if (
                    fresh.state is TargetedEnrichmentState.SUBMITTING
                    and fresh.started_at is not None
                    and datetime.now(UTC) - fresh.started_at < self._in_flight_grace
                ):
                    return ExaTargetedResult(
                        outcome=ExaTargetedOutcome.JOINED_IN_FLIGHT, operation=fresh
                    )
                return await self._recover_stale_submit(fresh)

            import_request = build_exa_import_request(preflight)
            try:
                import_exchange = await self._transport.create_import(import_request)
            except ExaWebsetsPreDispatchError:
                failed = await self._fail_predispatch(claimed, "exa_import_create_predispatch")
                return ExaTargetedResult(
                    outcome=ExaTargetedOutcome.FAILED_RETRYABLE,
                    operation=failed,
                    import_calls=1,
                )
            except ExaWebsetsError as exc:
                failed = await self._fail_before_webset(claimed, exc, "exa_import_create_failed")
                return ExaTargetedResult(
                    outcome=ExaTargetedOutcome.FAILED_TERMINAL,
                    operation=failed,
                    import_calls=1,
                )

            if import_exchange.response.integral_count != len(
                request.targets
            ) or import_exchange.response.entity != ExaWebsetEntity(
                type=ExaWebsetEntityType.COMPANY
            ):
                unknown = await self._persist_unknown(
                    claimed, "exa_import_create_contract_drift", lookup_calls=0
                )
                return ExaTargetedResult(
                    outcome=ExaTargetedOutcome.SPEND_OUTCOME_UNKNOWN,
                    operation=unknown,
                    import_calls=1,
                )
            await self._record_bytes(
                operation=claimed,
                kind="import_create_sanitized",
                body=import_exchange.response.sanitized_bytes(),
                source_url=f"{EXA_WEBSETS_API_BASE}/imports/{import_exchange.response.id}",
                request_id=import_exchange.request_id,
            )
            try:
                await self._transport.upload_import_csv(
                    upload_url=import_exchange.response.upload_url,
                    content=preflight.csv_bytes,
                )
            except ExaWebsetsError:
                # Import creation/upload alone does not schedule paid resolution. A retry creates a
                # fresh upload slot because the presigned credential is intentionally not durable.
                failed = await self._fail_predispatch(claimed, "exa_import_upload_failed")
                return ExaTargetedResult(
                    outcome=ExaTargetedOutcome.FAILED_RETRYABLE,
                    operation=failed,
                    import_calls=1,
                    upload_calls=1,
                )

            webset_request = build_exa_import_webset_request(
                request, import_id=import_exchange.response.id
            )
            try:
                exchange = await self._transport.create_webset(webset_request)
            except ExaWebsetsError as exc:
                if exc.dispatch_uncertain or exc.status_code == 409:
                    return await self._lookup_after_create(
                        operation=claimed,
                        webset_request=webset_request,
                        import_id=import_exchange.response.id,
                        import_calls=1,
                        upload_calls=1,
                    )
                failed = await self._fail_before_webset(claimed, exc, "exa_webset_create_failed")
                return ExaTargetedResult(
                    outcome=ExaTargetedOutcome.FAILED_TERMINAL,
                    operation=failed,
                    import_calls=1,
                    upload_calls=1,
                    create_calls=1,
                )
            try:
                assert_exa_import_webset_matches(
                    webset_request, exchange, expected_count=len(request.targets)
                )
            except ExaWebsetsContractDrift:
                return await self._lookup_after_create(
                    operation=claimed,
                    webset_request=webset_request,
                    import_id=import_exchange.response.id,
                    import_calls=1,
                    upload_calls=1,
                )
            stored = await self._persist_submit(
                claimed, import_id=import_exchange.response.id, exchange=exchange
            )
            return ExaTargetedResult(
                outcome=ExaTargetedOutcome.CREATED,
                operation=stored,
                import_calls=1,
                upload_calls=1,
                create_calls=1,
            )

    async def drive_once(
        self, *, workspace_id: str, operation_id: TargetedEnrichmentOperationId
    ) -> ExaTargetedResult:
        operation = await self._get(workspace_id, operation_id)
        if operation.state is TargetedEnrichmentState.SUCCEEDED:
            return ExaTargetedResult(outcome=ExaTargetedOutcome.REPLAYED, operation=operation)
        if operation.state is TargetedEnrichmentState.SPEND_OUTCOME_UNKNOWN:
            return ExaTargetedResult(
                outcome=ExaTargetedOutcome.SPEND_OUTCOME_UNKNOWN, operation=operation
            )
        if operation.provider_operation_id is None:
            raise ExaTargetedEnrichmentError("targeted operation has no provider Webset")
        if operation.state not in {
            TargetedEnrichmentState.PROVIDER_RUNNING,
            TargetedEnrichmentState.WAITING_EXTERNAL,
            TargetedEnrichmentState.RECONCILING,
            TargetedEnrichmentState.MATERIALIZING,
        }:
            raise ExaTargetedEnrichmentError(
                f"targeted operation cannot be driven from {operation.state.value}"
            )
        exchange = await self._transport.poll_webset(operation.provider_operation_id)
        await self._record_bytes(
            operation=operation,
            kind="webset_poll",
            body=exchange.response_body,
            source_url=f"{EXA_WEBSETS_API_BASE}/websets/{operation.provider_operation_id}",
            request_id=exchange.request_id,
        )
        request = build_exa_import_webset_request(
            operation.request, import_id=operation.import_id or ""
        )
        try:
            imported = assert_exa_import_webset_matches(
                request, exchange, expected_count=len(operation.request.targets)
            )
        except ExaWebsetsContractDrift:
            unknown = await self._persist_unknown(
                operation, "exa_targeted_poll_contract_drift", lookup_calls=0
            )
            return ExaTargetedResult(
                outcome=ExaTargetedOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                poll_calls=1,
            )
        if exchange.webset.status is not ExaWebsetStatus.IDLE:
            waiting = await self._set_waiting(operation)
            return ExaTargetedResult(
                outcome=ExaTargetedOutcome.WAITING_EXTERNAL,
                operation=waiting,
                poll_calls=1,
            )
        if imported.status is not ExaImportStatus.COMPLETED or any(
            enrichment.status != "completed" for enrichment in exchange.webset.enrichments
        ):
            unknown = await self._persist_unknown(
                operation, "exa_import_or_enrichment_not_terminal_at_idle", lookup_calls=0
            )
            return ExaTargetedResult(
                outcome=ExaTargetedOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                poll_calls=1,
            )
        try:
            return await self._reconcile(operation, exchange)
        except (ExaWebsetsContractDrift, ValueError):
            unknown = await self._persist_unknown(
                operation, "exa_targeted_item_contract_drift", lookup_calls=0
            )
            return ExaTargetedResult(
                outcome=ExaTargetedOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                poll_calls=1,
            )

    async def _reserve(
        self, preflight: ExaTargetedPreflight
    ) -> tuple[TargetedEnrichmentOperation, bool]:
        request = preflight.request
        async with self._conn_factory() as conn:
            # Read exact replay before recapturing any content-addressed request/CSV artifact.
            # Besides avoiding needless writes, this is the E1 no-resurrection barrier: after a
            # subject erasure tombstones its serving edges and marks an unreferenced blob erased,
            # a terminal retry must only read the durable operation and must not put the bytes or
            # revive the subject edge again.
            existing = await find_targeted_enrichment_operation(
                conn,
                workspace_id=request.workspace_id,
                source_key=request.source_key,
                request_fingerprint=request.request_fingerprint,
                observation_window=request.observation_window,
            )
            if existing is not None:
                if (
                    existing.request != request
                    or existing.provider_units_reserved != preflight.maximum_provider_credits
                    or existing.cost_cents_reserved != preflight.maximum_cost_cents
                ):
                    raise TargetedEnrichmentReplayConflict(
                        "targeted enrichment replay differs from its durable request or reservation"
                    )
                return existing, False
            input_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=request.workspace_id,
                content=request.canonical_bytes(),
                media_type="application/json",
                source_key=EXA_WEBSETS_SOURCE_KEY,
                source_url=f"{EXA_WEBSETS_API_BASE}/imports",
            )
            csv_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=request.workspace_id,
                content=preflight.csv_bytes,
                media_type="text/csv",
                source_key=EXA_WEBSETS_SOURCE_KEY,
                source_url=f"{EXA_WEBSETS_API_BASE}/imports",
            )
            operation = TargetedEnrichmentOperation(
                operation_id=new_targeted_enrichment_operation_id(),
                request=request,
                request_fingerprint=request.request_fingerprint,
                provider_external_id=_provider_external_id(request.request_fingerprint),
                state=TargetedEnrichmentState.PLANNED,
                spend_outcome=TargetedEnrichmentSpendOutcome.NOT_DISPATCHED,
                input_artifact_key=input_key,
                csv_artifact_key=csv_key,
                provider_units_reserved=preflight.maximum_provider_credits,
                cost_cents_reserved=preflight.maximum_cost_cents,
            )
            stored, created = await reserve_targeted_enrichment_operation(
                conn, operation=operation, enforce_budget=self._enforce_budget
            )
            for artifact_key, reference_kind in (
                (stored.input_artifact_key, "targeted_enrichment_request"),
                (stored.csv_artifact_key, "targeted_enrichment_csv"),
            ):
                await _bind_targeted_artifact_subjects(
                    conn,
                    operation=stored,
                    artifact_key=artifact_key,
                    reference_kind=reference_kind,
                    reference_id=str(stored.operation_id),
                )
            return stored, created

    async def _claim(
        self, operation: TargetedEnrichmentOperation
    ) -> TargetedEnrichmentOperation | None:
        async with self._conn_factory() as conn:
            return await claim_targeted_enrichment_dispatch(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )

    async def _get(
        self, workspace_id: str, operation_id: TargetedEnrichmentOperationId
    ) -> TargetedEnrichmentOperation:
        async with self._conn_factory() as conn:
            operation = await get_targeted_enrichment_operation(
                conn, workspace_id=workspace_id, operation_id=operation_id
            )
        if operation is None:
            raise TargetedEnrichmentNotFound(f"targeted enrichment operation {operation_id}")
        return operation

    async def _record_bytes(
        self,
        *,
        operation: TargetedEnrichmentOperation,
        kind: str,
        body: bytes,
        source_url: str,
        request_id: str | None,
    ) -> str:
        async with self._conn_factory() as conn:
            key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=body,
                media_type="application/json",
                source_key=EXA_WEBSETS_SOURCE_KEY,
                source_url=source_url,
            )
            await append_targeted_enrichment_artifact(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                artifact_kind=kind,
                artifact_key=key,
                content_sha256=content_address(body),
                provider_request_id=request_id,
            )
            await _bind_targeted_artifact_subjects(
                conn,
                operation=operation,
                artifact_key=key,
                reference_kind=f"targeted_enrichment_{kind}",
                reference_id=f"{operation.operation_id}:{request_id or content_address(body)}",
            )
            return key

    async def _persist_submit(
        self,
        operation: TargetedEnrichmentOperation,
        *,
        import_id: str,
        exchange: ExaWebsetExchange,
    ) -> TargetedEnrichmentOperation:
        receipt_key = await self._record_bytes(
            operation=operation,
            kind="webset_create",
            body=exchange.response_body,
            source_url=f"{EXA_WEBSETS_API_BASE}/websets/{exchange.webset.id}",
            request_id=exchange.request_id,
        )
        async with self._conn_factory() as conn:
            current = await get_targeted_enrichment_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise TargetedEnrichmentNotFound("targeted enrichment submit")
            if current.provider_operation_id is not None:
                if current.provider_operation_id != exchange.webset.id:
                    raise TargetedEnrichmentReplayConflict("targeted operation changed provider id")
                return current
            return await update_targeted_enrichment_operation(
                conn,
                operation=current.model_copy(
                    update={
                        "state": TargetedEnrichmentState.PROVIDER_RUNNING,
                        "spend_outcome": TargetedEnrichmentSpendOutcome.CHARGED,
                        "import_id": import_id,
                        "provider_operation_id": exchange.webset.id,
                        "submitted_receipt_ref": receipt_key,
                        "next_poll_at": datetime.now(UTC) + self._poll_after,
                    }
                ),
            )

    async def _lookup_after_create(
        self,
        *,
        operation: TargetedEnrichmentOperation,
        webset_request: ExaCreateWebsetRequest,
        import_id: str,
        import_calls: int,
        upload_calls: int,
    ) -> ExaTargetedResult:
        try:
            exchange = await self._transport.get_webset(webset_request.external_id)
            assert_exa_import_webset_matches(
                webset_request, exchange, expected_count=len(operation.request.targets)
            )
        except ExaWebsetsError:
            unknown = await self._persist_unknown(
                operation, "exa_webset_create_lookup_failed", lookup_calls=1
            )
            return ExaTargetedResult(
                outcome=ExaTargetedOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                import_calls=import_calls,
                upload_calls=upload_calls,
                create_calls=1,
                lookup_calls=1,
            )
        stored = await self._persist_submit(operation, import_id=import_id, exchange=exchange)
        return ExaTargetedResult(
            outcome=ExaTargetedOutcome.CREATED,
            operation=stored,
            import_calls=import_calls,
            upload_calls=upload_calls,
            create_calls=1,
            lookup_calls=1,
        )

    async def _recover_stale_submit(
        self, operation: TargetedEnrichmentOperation
    ) -> ExaTargetedResult:
        try:
            exchange = await self._transport.get_webset(operation.provider_external_id)
        except ExaWebsetNotFound:
            # A stale submit may have crashed before or after paid create. One 404 is not enough to
            # distinguish eventual consistency from a pre-create crash, so never auto-create here.
            unknown = await self._persist_unknown(
                operation, "stale_submit_webset_absent", lookup_calls=1
            )
            return ExaTargetedResult(
                outcome=ExaTargetedOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                lookup_calls=1,
            )
        except ExaWebsetsError:
            unknown = await self._persist_unknown(
                operation, "stale_submit_lookup_failed", lookup_calls=1
            )
            return ExaTargetedResult(
                outcome=ExaTargetedOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                lookup_calls=1,
            )
        matching_imports = [
            imported
            for imported in exchange.webset.imports
            if imported.format.value == "csv"
            and imported.integral_count == len(operation.request.targets)
        ]
        if len(matching_imports) != 1:
            unknown = await self._persist_unknown(
                operation, "stale_submit_import_lineage_ambiguous", lookup_calls=1
            )
            return ExaTargetedResult(
                outcome=ExaTargetedOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                lookup_calls=1,
            )
        request = build_exa_import_webset_request(
            operation.request, import_id=matching_imports[0].id
        )
        assert_exa_import_webset_matches(
            request, exchange, expected_count=len(operation.request.targets)
        )
        stored = await self._persist_submit(
            operation, import_id=matching_imports[0].id, exchange=exchange
        )
        return ExaTargetedResult(
            outcome=ExaTargetedOutcome.CREATED, operation=stored, lookup_calls=1
        )

    async def _set_waiting(
        self, operation: TargetedEnrichmentOperation
    ) -> TargetedEnrichmentOperation:
        async with self._conn_factory() as conn:
            current = await get_targeted_enrichment_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise TargetedEnrichmentNotFound("targeted enrichment wait")
            return await update_targeted_enrichment_operation(
                conn,
                operation=current.model_copy(
                    update={
                        "state": TargetedEnrichmentState.WAITING_EXTERNAL,
                        "next_poll_at": datetime.now(UTC) + self._poll_after,
                    }
                ),
            )

    async def _reconcile(
        self, operation: TargetedEnrichmentOperation, exchange: ExaWebsetExchange
    ) -> ExaTargetedResult:
        assert operation.provider_operation_id is not None
        cursor: str | None = None
        seen_cursors: set[str | None] = set()
        items: list[ExaWebsetItem] = []
        item_page_calls = 0
        while True:
            if cursor in seen_cursors:
                raise ExaWebsetsContractDrift("Exa targeted item pagination repeated a cursor")
            seen_cursors.add(cursor)
            page_exchange = await self._transport.list_items(
                operation.provider_operation_id, cursor=cursor, limit=100
            )
            item_page_calls += 1
            await self._record_bytes(
                operation=operation,
                kind="item_page",
                body=page_exchange.response_body,
                source_url=(
                    f"{EXA_WEBSETS_API_BASE}/websets/{operation.provider_operation_id}/items"
                ),
                request_id=page_exchange.request_id,
            )
            items.extend(page_exchange.page.data)
            if not page_exchange.page.has_more:
                break
            cursor = page_exchange.page.next_cursor

        definitions = exchange.webset.enrichments
        target_by_identifier = {
            _canonical_identifier(target.identifier_url): target
            for target in operation.request.targets
        }
        returned_targets: set[EntityId] = set()
        provider_ids: set[str] = set()
        source_ids: set[str] = set()
        prepared: list[
            tuple[
                TargetedEnrichmentTarget,
                ExaWebsetItem,
                ExaWebsetItemCompanyProperties,
                bytes,
            ]
        ] = []
        expected_import_ids = {value.id for value in exchange.webset.imports}
        for item in items:
            if item.id in provider_ids:
                raise ExaWebsetsContractDrift("Exa targeted items repeat provider id")
            provider_ids.add(item.id)
            if (
                item.source != "import"
                or item.source_id not in expected_import_ids
                or item.webset_id != operation.provider_operation_id
                or item.source_entity_id is None
                or item.evaluations
                or not isinstance(item.properties, ExaWebsetItemCompanyProperties)
            ):
                raise ExaWebsetsContractDrift("Exa targeted item violates import-only identity")
            canonical_source = _canonical_identifier(item.source_entity_id)
            if canonical_source in source_ids:
                raise ExaWebsetsContractDrift("Exa targeted items repeat sourceEntityId")
            source_ids.add(canonical_source)
            target = target_by_identifier.get(canonical_source)
            if target is None or target.account_id in returned_targets:
                raise ExaWebsetsContractDrift(
                    "Exa targeted item does not map to one selected account"
                )
            if _canonical_identifier(item.properties.url) != canonical_source:
                raise ExaWebsetsContractDrift(
                    "Exa targeted item resolved a different company domain"
                )
            returned_targets.add(target.account_id)
            # This validates definition/result identity, terminal status, formats, and logical keys.
            normalize_exa_discovery_company_item(item, definitions)
            prepared.append(
                (
                    target,
                    item,
                    item.properties,
                    json.dumps(
                        item.model_dump(mode="json", by_alias=True),
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                )
            )

        ordinary_rows = 0
        contact_values = 0
        for _, item, _, _ in prepared:
            by_id = {result.enrichment_id: result for result in item.enrichment_results}
            for definition in definitions:
                field_key = definition.metadata.get("clueFieldKey")
                result = by_id[definition.id]
                if field_key in {"core.company_email", "core.company_phone"}:
                    if result.result is not None and len(result.result) != 1:
                        raise ExaWebsetsContractDrift(
                            "Exa contact enrichment returned more than one value"
                        )
                    contact_values += len(result.result or ())
                else:
                    ordinary_rows += 1
        charge = self._pricing.realized_units(
            matching_search_results=0,
            ordinary_enrichment_rows=ordinary_rows,
            contact_values=contact_values,
            resolved_import_results=len(prepared),
        )
        if charge.search_credits != 0 or charge.total_units > operation.provider_units_reserved:
            raise ExaWebsetsContractDrift("Exa targeted realized charge exceeds reservation")

        created = reused = resolved = missing = unresolved = 0
        claim_ids: list[str] = []
        async with self._conn_factory() as conn:
            current = await get_targeted_enrichment_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise TargetedEnrichmentNotFound("targeted enrichment reconciliation")
            if current.state is TargetedEnrichmentState.SUCCEEDED:
                return ExaTargetedResult(
                    outcome=ExaTargetedOutcome.REPLAYED,
                    operation=current,
                    poll_calls=1,
                    item_page_calls=item_page_calls,
                )
            if current.state in {
                TargetedEnrichmentState.FAILED_TERMINAL,
                TargetedEnrichmentState.CANCELLED,
            }:
                return ExaTargetedResult(
                    outcome=ExaTargetedOutcome.FAILED_TERMINAL,
                    operation=current,
                    poll_calls=1,
                    item_page_calls=item_page_calls,
                )
            await load_core_pack(conn)
            # Boot order: a source manifest's ``yields`` validate against the field
            # registry, and the tier-3 ``exa_search`` seed yields ``client.*`` keys — so
            # the client-knowledge pack must be loaded before the manifests are seeded.
            await load_client_knowledge_pack(conn)
            await seed_source_manifests(conn)
            # FI-2 P2 (spec §3): every enrichment claim written below is stamped with the project
            # run itself as its ``run_id``, so that is the id the project lens must resolve.
            # Registered once here — before the per-target loop, in the same transaction as its
            # writes. Idempotent, so a re-reconciled operation re-registers harmlessly.
            await record_run_lineage(
                conn,
                run_id=UUID(str(operation.request.project_run_id)),
                workspace_id=operation.request.workspace_id,
                kind="enrichment",
                project_id=operation.request.project_id,
                project_run_id=UUID(str(operation.request.project_run_id)),
            )
            for target, item, company_properties, item_bytes in prepared:
                if (
                    await surviving_id(conn, target.account_id, EntityType.ACCOUNT)
                    != target.account_id
                ):
                    raise TargetedEnrichmentReplayConflict(
                        "selected account merged during targeted enrichment"
                    )
                item_key = await capture_discovery_artifact(
                    conn,
                    self._storage,
                    workspace_id=operation.request.workspace_id,
                    content=item_bytes,
                    media_type="application/json",
                    source_key=EXA_WEBSETS_SOURCE_KEY,
                    source_url=company_properties.url,
                )
                await append_targeted_enrichment_artifact(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                    artifact_kind="item",
                    artifact_key=item_key,
                    content_sha256=content_address(item_bytes),
                )
                company = normalize_exa_discovery_company_item(item, definitions)
                members = await canonical_member_ids(
                    conn,
                    target.account_id,
                    EntityType.ACCOUNT,
                    workspace_id=operation.request.workspace_id,
                )
                await put_targeted_enrichment_item(
                    conn,
                    snapshot=TargetedEnrichmentItemSnapshot(
                        operation_id=operation.operation_id,
                        workspace_id=operation.request.workspace_id,
                        provider_item_id=item.id,
                        source_entity_id=item.source_entity_id or target.identifier_url,
                        account_id=target.account_id,
                        raw_artifact_key=item_key,
                        item_sha256=content_address(item_bytes),
                        observed_at=item.updated_at,
                        materialized_at=datetime.now(UTC),
                    ),
                )
                await bind_discovery_artifact_subject(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    artifact_key_value=item_key,
                    subject_kind="account",
                    subject_entity_id=target.account_id,
                    reference_kind="targeted_enrichment_item",
                    reference_id=f"{operation.operation_id}:{item.id}",
                )
                for observation in company.enrichments:
                    mapped = exa_enrichment_value(company, observation)
                    if mapped is None:
                        await put_targeted_enrichment_field_result(
                            conn,
                            workspace_id=operation.request.workspace_id,
                            result=TargetedEnrichmentFieldResult(
                                operation_id=operation.operation_id,
                                account_id=target.account_id,
                                field_key=observation.field_key,
                                state=TargetedEnrichmentFieldState.CONFIRMED_MISSING,
                                provider_item_id=item.id,
                                item_artifact_key=item_key,
                                reason_code="exa_terminal_enrichment_null",
                            ),
                        )
                        missing += 1
                        continue
                    field_key, value = mapped
                    claim_id, was_created = await ensure_exa_company_field_claim(
                        conn,
                        entity_id=target.account_id,
                        run_id=RunId(operation.request.project_run_id),
                        artifact_key=item_key,
                        retained_item=item_bytes,
                        company=company,
                        member_ids=members,
                        field_key=field_key,
                        value=value,
                        provider_field=observation.field_key,
                        enrichment_id=observation.enrichment_id,
                        references=observation.references,
                        reasoning=observation.reasoning,
                        research_mode=ResearchMode.ACCOUNT_PROFILING,
                    )
                    claim_ids.append(str(claim_id))
                    created += int(was_created)
                    reused += int(not was_created)
                    await put_targeted_enrichment_field_result(
                        conn,
                        workspace_id=operation.request.workspace_id,
                        result=TargetedEnrichmentFieldResult(
                            operation_id=operation.operation_id,
                            account_id=target.account_id,
                            field_key=field_key,
                            state=TargetedEnrichmentFieldState.RESOLVED,
                            provider_item_id=item.id,
                            item_artifact_key=item_key,
                            claim_id=claim_id,
                        ),
                    )
                    resolved += 1

            for target in operation.request.targets:
                if target.account_id in returned_targets:
                    continue
                for field in operation.request.fields:
                    await put_targeted_enrichment_field_result(
                        conn,
                        workspace_id=operation.request.workspace_id,
                        result=TargetedEnrichmentFieldResult(
                            operation_id=operation.operation_id,
                            account_id=target.account_id,
                            field_key=field.field_key,
                            state=TargetedEnrichmentFieldState.IMPORT_UNRESOLVED,
                            reason_code="exa_import_did_not_resolve_identifier",
                        ),
                    )
                    unresolved += 1

            artifacts = await list_targeted_enrichment_artifacts(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            receipt_payload: dict[str, JsonValue] = {
                "contract": "exa-targeted-enrichment-receipt-v1",
                "operation_id": str(operation.operation_id),
                "request_fingerprint": operation.request_fingerprint,
                "discovery_batch_id": str(operation.request.discovery_batch_id),
                "discovery_seal_sha256": operation.request.discovery_seal_sha256,
                "provider_webset_id": operation.provider_operation_id,
                "provider_import_id": operation.import_id,
                "requested_accounts": len(operation.request.targets),
                "resolved_import_results": len(prepared),
                "matching_search_results": 0,
                "ordinary_enrichment_rows": ordinary_rows,
                "contact_values": contact_values,
                "search_credits": str(charge.search_credits),
                "import_credits": str(charge.import_credits),
                "ordinary_enrichment_credits": str(charge.ordinary_enrichment_credits),
                "contact_enrichment_credits": str(charge.contact_enrichment_credits),
                "provider_units_charged": str(charge.total_units),
                "cost_cents_charged": str(self._pricing.monetary_value(charge.total_units)),
                "cost_semantics": "subscription-credit-allocation-equivalent",
                "settlement_method": "public-credit-rules-applied-to-terminal-item-facts",
                "pricing_policy_version": self._pricing.version,
                "claim_ids": cast(JsonValue, sorted(set(claim_ids))),
            }
            receipt_bytes = json.dumps(
                receipt_payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            receipt_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=receipt_bytes,
                media_type="application/json",
                source_key=EXA_WEBSETS_SOURCE_KEY,
                source_url=f"{EXA_WEBSETS_API_BASE}/websets/{operation.provider_operation_id}",
            )
            await _bind_targeted_artifact_subjects(
                conn,
                operation=operation,
                artifact_key=receipt_key,
                reference_kind="targeted_enrichment_final_receipt",
                reference_id=str(operation.operation_id),
            )
            manifest_payload: dict[str, JsonValue] = {
                "contract": "targeted-enrichment-artifact-manifest-v1",
                "operation_id": str(operation.operation_id),
                "artifacts": [
                    {
                        "ordinal": artifact.ordinal,
                        "kind": artifact.artifact_kind,
                        "key": artifact.artifact_key,
                        "sha256": artifact.content_sha256,
                        "provider_request_id": artifact.provider_request_id,
                    }
                    for artifact in artifacts
                ],
                "receipt_key": receipt_key,
                "receipt_sha256": content_address(receipt_bytes),
            }
            manifest_bytes = json.dumps(
                manifest_payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            manifest_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=manifest_bytes,
                media_type="application/json",
                source_key=EXA_WEBSETS_SOURCE_KEY,
                source_url=f"{EXA_WEBSETS_API_BASE}/websets/{operation.provider_operation_id}",
            )
            await _bind_targeted_artifact_subjects(
                conn,
                operation=operation,
                artifact_key=manifest_key,
                reference_kind="targeted_enrichment_manifest",
                reference_id=str(operation.operation_id),
            )
            current = current.model_copy(
                update={
                    "state": TargetedEnrichmentState.SUCCEEDED,
                    "spend_outcome": TargetedEnrichmentSpendOutcome.CHARGED,
                    "provider_units_charged": charge.total_units,
                    "cost_cents_charged": self._pricing.monetary_value(charge.total_units),
                    "final_receipt_ref": receipt_key,
                    "raw_response_manifest_key": manifest_key,
                    "next_poll_at": None,
                    "terminal_at": datetime.now(UTC),
                }
            )
            stored = await update_targeted_enrichment_operation(conn, operation=current)
            await self._budget.record(
                cost_cents=stored.cost_cents_charged,
                scope=BudgetScope.RUN,
                project_run_id=stored.request.project_run_id,
                conn=conn,
            )
        return ExaTargetedResult(
            outcome=ExaTargetedOutcome.SUCCEEDED,
            operation=stored,
            poll_calls=1,
            item_page_calls=item_page_calls,
            claims_created=created,
            claims_reused=reused,
            resolved_fields=resolved,
            missing_fields=missing,
            unresolved_import_fields=unresolved,
        )

    async def _fail_predispatch(
        self, operation: TargetedEnrichmentOperation, failure_code: str
    ) -> TargetedEnrichmentOperation:
        async with self._conn_factory() as conn:
            current = await get_targeted_enrichment_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise TargetedEnrichmentNotFound("targeted enrichment failure")
            return await fail_targeted_enrichment_predispatch(
                conn, operation=current, failure_code=failure_code
            )

    async def _fail_before_webset(
        self,
        operation: TargetedEnrichmentOperation,
        error: ExaWebsetsError,
        failure_code: str,
    ) -> TargetedEnrichmentOperation:
        payload = json.dumps(
            {
                "contract": "targeted-enrichment-failure-v1",
                "status_code": error.status_code,
                "request_id": error.request_id,
                "error_tag": error.error_tag,
                "response_sha256": (
                    content_address(error.response_body) if error.response_body else None
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        receipt_key = await self._record_bytes(
            operation=operation,
            kind="terminal_failure",
            body=payload,
            source_url=f"{EXA_WEBSETS_API_BASE}/websets",
            request_id=error.request_id,
        )
        async with self._conn_factory() as conn:
            current = await get_targeted_enrichment_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise TargetedEnrichmentNotFound("targeted enrichment terminal failure")
            return await update_targeted_enrichment_operation(
                conn,
                operation=current.model_copy(
                    update={
                        "state": TargetedEnrichmentState.FAILED_TERMINAL,
                        "spend_outcome": TargetedEnrichmentSpendOutcome.NOT_CHARGED,
                        "submitted_receipt_ref": receipt_key,
                        "failure_code": failure_code,
                        "next_poll_at": None,
                        "terminal_at": datetime.now(UTC),
                    }
                ),
            )

    async def _persist_unknown(
        self,
        operation: TargetedEnrichmentOperation,
        failure_code: str,
        *,
        lookup_calls: int,
    ) -> TargetedEnrichmentOperation:
        del lookup_calls
        async with self._conn_factory() as conn:
            current = await get_targeted_enrichment_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise TargetedEnrichmentNotFound("targeted enrichment unknown spend")
            return await update_targeted_enrichment_operation(
                conn,
                operation=current.model_copy(
                    update={
                        "state": TargetedEnrichmentState.SPEND_OUTCOME_UNKNOWN,
                        "spend_outcome": TargetedEnrichmentSpendOutcome.UNKNOWN,
                        "failure_code": failure_code,
                        "next_poll_at": None,
                    }
                ),
            )


class ExaTargetedEnrichmentStarter:
    """Production-facing compiler + coordinator entry point for a bounded E1 request."""

    def __init__(
        self,
        *,
        transport_factory: TargetedTransportFactory,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
        policy: ExaTargetedEnrichmentPolicy = DEFAULT_EXA_TARGETED_ENRICHMENT_POLICY,
        pricing: ExaWebsetsPricingPolicy = DEFAULT_EXA_WEBSETS_PRICING,
        enforce_budget: bool = True,
    ) -> None:
        self._transport_factory = transport_factory
        self._storage = storage
        self._conn_factory = conn_factory
        self._policy = policy
        self._pricing = pricing
        # FI pilot budget-controls, threaded from ``Settings.budget_controls_enabled`` at the
        # composition root. False means this path never refuses on budget grounds; every
        # durable row it writes is unchanged.
        self._enforce_budget = enforce_budget

    async def start(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_ids: Sequence[EntityId],
        field_keys: Sequence[str],
    ) -> ExaTargetedResult:
        preflight = await compile_exa_targeted_preflight(
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            account_ids=account_ids,
            fields=approved_targeted_field_plans(field_keys),
            observation_window=(f"project-run:{project_run_id}:targeted:{self._policy.version}"),
            storage=self._storage,
            conn_factory=self._conn_factory,
            policy=self._policy,
            pricing=self._pricing,
        )
        async with self._transport_factory() as transport:
            coordinator = ExaTargetedEnrichmentCoordinator(
                transport=transport,
                storage=self._storage,
                conn_factory=self._conn_factory,
                pricing=self._pricing,
                enforce_budget=self._enforce_budget,
            )
            return await coordinator.start(preflight)


class ExaTargetedEnrichmentWorker:
    """Lease and drive due E1 operations without originating new provider spend."""

    def __init__(
        self,
        *,
        coordinator: ExaTargetedEnrichmentCoordinator,
        conn_factory: ConnFactory = transaction,
        lease_seconds: int = 60,
    ) -> None:
        if lease_seconds < 1:
            raise ValueError("targeted enrichment lease must be positive")
        self._coordinator = coordinator
        self._conn_factory = conn_factory
        self._lease_seconds = lease_seconds

    async def run_due(self, *, limit: int = 10) -> int:
        async with self._conn_factory() as conn:
            operations = await claim_due_targeted_enrichment_operations(
                conn,
                now=datetime.now(UTC),
                limit=limit,
                lease_seconds=self._lease_seconds,
            )
        for operation in operations:
            await self._coordinator.drive_once(
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
        return len(operations)


def build_production_exa_targeted_starter(
    settings: Settings,
    *,
    secrets: Secrets,
    storage: StorageBackend,
) -> ExaTargetedEnrichmentStarter | None:
    """Bind new E1 spend only when both the spend switch and reconciler are enabled."""

    if not settings.exa_targeted_enrichment_enabled:
        return None
    if not settings.exa_websets_lifecycle_enabled:
        raise RuntimeError(
            "Exa targeted enrichment is enabled but its lifecycle worker is disabled"
        )
    if secrets.exa_api_key is None:
        raise RuntimeError(
            "Exa targeted enrichment is enabled but CLUE_EXA_API_KEY is not configured"
        )
    api_key = secrets.exa_api_key
    return ExaTargetedEnrichmentStarter(
        transport_factory=lambda: ExaWebsetsClient(api_key=api_key, lookup_attempts=1),
        storage=storage,
        enforce_budget=settings.budget_controls_enabled,
    )


__all__ = [
    "EXA_TARGETED_FIELD_POLICY_VERSION",
    "ExaTargetedEligibilityError",
    "ExaTargetedEnrichmentCoordinator",
    "ExaTargetedEnrichmentError",
    "ExaTargetedEnrichmentPolicy",
    "ExaTargetedEnrichmentStarter",
    "ExaTargetedEnrichmentWorker",
    "ExaTargetedOutcome",
    "ExaTargetedPreflight",
    "ExaTargetedResult",
    "assert_exa_import_webset_matches",
    "approved_targeted_field_plans",
    "build_exa_import_request",
    "build_exa_import_webset_request",
    "build_production_exa_targeted_starter",
    "compile_exa_targeted_preflight",
]
