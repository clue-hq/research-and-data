"""Selected-contact Exa Websets channel acquisition and independent validation (M8C C5)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.exa_websets_submit import DEFAULT_EXA_WEBSETS_PRICING, ExaWebsetsPricingPolicy
from clue_config import Jurisdiction, RetentionTtls
from clue_core import (
    BudgetScope,
    ChannelUseDecision,
    Claim,
    ClaimProvenanceKind,
    ContactChannel,
    ContactChannelAcquisitionRequest,
    ContactChannelOperation,
    ContactChannelOperationId,
    ContactChannelOperationState,
    ContactChannelSpendOutcome,
    ContactChannelState,
    ContactChannelValidation,
    ContactChannelValidationOutcome,
    ContactChannelValidator,
    ContactChannelValidatorRequest,
    ContactChannelValidatorResult,
    ContactResearchIntent,
    ContactResearchPolicyPin,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    PreSpendGate,
    PreSpendRequest,
    PreSpendVerdict,
    ResearchMode,
    ReuseScope,
    RunId,
    SourceTier,
    UseClass,
    UseGate,
)
from clue_db import transaction
from clue_research.adapters.exa_websets import (
    EXA_WEBSETS_API_BASE,
    EXA_WEBSETS_API_VERSION,
    EXA_WEBSETS_CONTRACT_VERSION,
    EXA_WEBSETS_SOURCE_KEY,
    ExaCreateEnrichment,
    ExaCreateImportRef,
    ExaCreateImportRequest,
    ExaCreateWebsetRequest,
    ExaImportStatus,
    ExaWebsetEnrichmentFormat,
    ExaWebsetEntity,
    ExaWebsetEntityType,
    ExaWebsetItem,
    ExaWebsetNotFound,
    ExaWebsetsContractDrift,
    ExaWebsetsError,
    ExaWebsetsImportTransport,
    ExaWebsetsPreDispatchError,
    ExaWebsetStatus,
)
from clue_research.claimstore import (
    WorkspaceScope,
    claims_by_ids,
    current_value,
    insert_claim,
    load_core_pack,
    record_run_lineage,
)
from clue_research.compliance import CONTACT_JURISDICTION, record_lawful_basis
from clue_research.directives import effective_account_research_directive
from clue_research.durable import (
    BudgetEngine,
    ContactResearchOperationStop,
    ContactResearchSelectionNotFound,
    DbBudgetStore,
    append_contact_channel_artifact,
    bind_discovery_artifact_subject,
    capture_discovery_artifact,
    claim_contact_channel_submit,
    claim_contact_channel_validation,
    contact_channel_operation_stop,
    contact_research_selection_cancellation,
    find_contact_channel_operation,
    find_fresh_reusable_contact_channel_operation,
    get_contact_channel_operation,
    get_contact_research_selection,
    get_project_run,
    latest_contact_research_selection,
    record_contact_channel_reuse,
    reserve_contact_channel_operation,
    update_contact_channel_operation,
)
from clue_research.identity import (
    get_account,
    get_contact,
    promote_contact_verified_email,
)
from clue_research.sources import get_source, seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack
from clue_storage import StorageBackend, content_address, read_verified_artifact

ConnFactoryLike = Callable[[], AbstractAsyncContextManager[AsyncConnection]]


class ContactChannelEnrichmentError(RuntimeError):
    pass


class ContactChannelEligibilityError(ContactChannelEnrichmentError):
    pass


class ContactChannelEnrichmentOutcome(StrEnum):
    CREATED = "created"
    WAITING_EXTERNAL = "waiting_external"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    REPLAYED = "replayed"
    JOINED_IN_FLIGHT = "joined_in_flight"
    READY_TO_VALIDATE = "ready_to_validate"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"


class ContactChannelPreflight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    request: ContactChannelAcquisitionRequest
    csv_bytes: bytes


class ContactChannelEnrichmentResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: ContactChannelEnrichmentOutcome
    operation: ContactChannelOperation
    import_calls: int = Field(default=0, ge=0)
    upload_calls: int = Field(default=0, ge=0)
    create_calls: int = Field(default=0, ge=0)
    poll_calls: int = Field(default=0, ge=0)
    item_calls: int = Field(default=0, ge=0)
    validation_calls: int = Field(default=0, ge=0)


def _csv_bytes(profile_url: str) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("url",))
    writer.writerow((profile_url,))
    return output.getvalue().encode("utf-8")


def _channel_format(channel: ContactChannel) -> ExaWebsetEnrichmentFormat:
    return (
        ExaWebsetEnrichmentFormat.EMAIL
        if channel is ContactChannel.EMAIL
        else ExaWebsetEnrichmentFormat.PHONE
    )


def build_exa_contact_channel_import(
    preflight: ContactChannelPreflight,
) -> ExaCreateImportRequest:
    request = preflight.request
    return ExaCreateImportRequest(
        size=len(preflight.csv_bytes),
        count=1,
        entity=ExaWebsetEntity(type=ExaWebsetEntityType.PERSON),
        title=f"Clue selected contact {request.channel.value}",
        metadata={
            "clueOperation": request.request_fingerprint,
            "clueChannel": request.channel.value,
        },
    )


def build_exa_contact_channel_webset(
    request: ContactChannelAcquisitionRequest, *, import_id: str
) -> ExaCreateWebsetRequest:
    return ExaCreateWebsetRequest(
        imports=(ExaCreateImportRef(source="import", id=import_id, evaluate=False),),
        title=f"Clue selected contact {request.channel.value}",
        enrichments=(
            ExaCreateEnrichment(
                description=(
                    "Return only the selected person's professional work email."
                    if request.channel is ContactChannel.EMAIL
                    else "Return only the selected person's direct professional phone number."
                ),
                format=_channel_format(request.channel),
                metadata={
                    "clueFieldKey": request.field_key,
                    "clueChannel": request.channel.value,
                },
            ),
        ),
        external_id=request.provider_external_id,
        metadata={
            "clueRequestFingerprint": request.request_fingerprint,
            "clueSelectionSha256": request.selection_sha256,
        },
    )


async def compile_contact_channel_preflight(
    conn: AsyncConnection,
    *,
    intent: ContactResearchIntent,
    effective_policy: ContactResearchPolicyPin,
    channel: ContactChannel,
    observation_window: str,
    entity_research_job_id: UUID | None = None,
) -> ContactChannelPreflight:
    """Prove the exact receipt/contact/channel/provider authority before any side effect."""

    intent.selection.require_effective_policy(effective_policy)
    try:
        stored_selection = await get_contact_research_selection(
            conn,
            workspace_id=intent.workspace_id,
            selection_id=intent.selection_id,
        )
    except ContactResearchSelectionNotFound as exc:
        raise ContactChannelEligibilityError(
            "contact research selection is not durable authority"
        ) from exc
    if stored_selection != intent.selection:
        raise ContactChannelEligibilityError(
            "contact research selection differs from durable authority"
        )
    current_selection = await latest_contact_research_selection(
        conn,
        workspace_id=intent.workspace_id,
        project_run_id=intent.project_run_id,
        account_id=intent.account_entity_id,
        include_cancelled=True,
    )
    if current_selection is None or current_selection.selection_id != intent.selection_id:
        raise ContactChannelEligibilityError(
            "contact research selection is not the current approved successor"
        )
    cancellation = await contact_research_selection_cancellation(
        conn,
        workspace_id=intent.workspace_id,
        selection_id=intent.selection_id,
    )
    if cancellation is not None:
        raise ContactChannelEligibilityError("contact research selection is cancelled")
    if not effective_policy.contact_reveals_enabled:
        raise ContactChannelEligibilityError("effective policy disables contact reveals")
    target = next(
        (
            item
            for item in intent.selection.body.targets
            if item.contact_entity_id == intent.contact_entity_id
        ),
        None,
    )
    if target is None:
        raise ContactChannelEligibilityError("contact is absent from the immutable selection")
    authorization = target.email if channel is ContactChannel.EMAIL else target.phone
    if not authorization.allowed:
        raise ContactChannelEligibilityError(f"selection does not authorize {channel.value}")
    if (
        len(authorization.provider_source_keys) != 1
        or len(authorization.validation_source_keys) != 1
    ):
        raise ContactChannelEligibilityError("channel requires one acquisition and one validator")
    acquisition_source = authorization.provider_source_keys[0]
    validation_source = authorization.validation_source_keys[0]
    if acquisition_source != EXA_WEBSETS_SOURCE_KEY:
        raise ContactChannelEligibilityError("C5 Exa adapter was invoked for another source")
    if acquisition_source not in effective_policy.channel_reveal_source_plan or (
        validation_source not in effective_policy.channel_validation_source_plan
    ):
        raise ContactChannelEligibilityError("channel sources are outside the effective policy")
    if acquisition_source not in intent.source_plan or validation_source not in intent.source_plan:
        raise ContactChannelEligibilityError("intent source plan omits channel provider authority")

    effective_directive = await effective_account_research_directive(
        conn,
        workspace_id=intent.workspace_id,
        directive_id=intent.research_directive.directive_id,
        account_id=intent.account_entity_id,
        expected_pin=intent.research_directive,
    )
    if effective_directive.project_id != intent.project_id:
        raise ContactChannelEligibilityError(
            "contact channel project differs from its confirmed directive"
        )
    if not (
        effective_directive.privacy_policy.contact_profiling_allowed
        and effective_directive.privacy_policy.contact_reveals_allowed
    ):
        raise ContactChannelEligibilityError(
            "confirmed directive does not authorize selected-contact reveals"
        )
    project_run = await get_project_run(conn, intent.project_run_id)
    if project_run is None or (
        project_run.workspace_id != intent.workspace_id
        or project_run.project_id != intent.project_id
        or project_run.icp_key != effective_directive.icp_key
        or project_run.icp_version != effective_directive.icp_version
    ):
        raise ContactChannelEligibilityError(
            "contact channel run does not pin the confirmed directive ICP"
        )

    account = await get_account(conn, intent.account_entity_id)
    contact = await get_contact(conn, intent.contact_entity_id)
    if (
        account is None
        or account.workspace_id != intent.workspace_id
        or account.merged_into is not None
        or not account.primary_domain
    ):
        raise ContactChannelEligibilityError("channel employer is absent, merged, or unkeyed")
    if (
        contact is None
        or contact.workspace_id != intent.workspace_id
        or contact.account_entity_id != account.id
        or contact.merged_into is not None
        or not contact.full_name
        or not contact.linkedin_url
    ):
        raise ContactChannelEligibilityError(
            "channel contact must be canonical, jurisdiction-resolved, and strongly identified"
        )
    profile_host = (urlsplit(contact.linkedin_url).hostname or "").lower().removeprefix("www.")
    if not any(
        profile_host == allowed or profile_host.endswith(f".{allowed}")
        for allowed in effective_policy.approved_strong_profile_hosts
    ):
        raise ContactChannelEligibilityError(
            "channel contact profile host is outside the approved strong-identity hosts"
        )
    objected = (
        await conn.execute(
            text(
                "SELECT 1 FROM outreach_objected WHERE workspace_id=:workspace_id "
                "AND contact_entity_id=:contact_id"
            ),
            {"workspace_id": intent.workspace_id, "contact_id": contact.id},
        )
    ).scalar_one_or_none()
    if objected is not None:
        raise ContactChannelEligibilityError("contact has a standing outreach objection")
    jurisdiction = await current_value(
        conn,
        contact.id,
        CONTACT_JURISDICTION,
        scope=WorkspaceScope.private_for_workspace(intent.workspace_id),
    )
    if jurisdiction is None or not isinstance(jurisdiction.value_json, dict):
        raise ContactChannelEligibilityError(
            "contact lacks a current provenance-backed jurisdiction regime"
        )
    raw_regime = jurisdiction.value_json.get("regime")
    try:
        regime = Jurisdiction(str(raw_regime))
    except ValueError as exc:
        raise ContactChannelEligibilityError(
            "contact jurisdiction claim contains an unsupported regime"
        ) from exc
    field_key = "core.work_email" if channel is ContactChannel.EMAIL else "core.direct_phone"
    for source_key in (acquisition_source, validation_source):
        source = await get_source(conn, source_key)
        if source is None or not source.active:
            raise ContactChannelEligibilityError(f"channel source {source_key!r} is not active")
        if field_key not in source.manifest.yields:
            raise ContactChannelEligibilityError(
                f"channel source {source_key!r} does not yield {field_key}"
            )
    if field_key not in {str(value) for value in intent.field_keys}:
        raise ContactChannelEligibilityError("channel field is not selected for this contact")
    request = ContactChannelAcquisitionRequest(
        workspace_id=intent.workspace_id,
        project_id=intent.project_id,
        project_run_id=intent.project_run_id,
        account_id=intent.account_entity_id,
        contact_id=intent.contact_entity_id,
        selection_id=intent.selection_id,
        selection_sha256=intent.selection_sha256,
        contact_intent_sha256=intent.sha256(),
        channel=channel,
        field_key=field_key,
        acquisition_source_key=acquisition_source,
        validation_source_key=validation_source,
        provider_api_version=EXA_WEBSETS_API_VERSION,
        provider_contract_version=(
            f"{EXA_WEBSETS_CONTRACT_VERSION}|{effective_policy.exa_websets_contract_ref}"
        ),
        validation_contract_version=effective_policy.channel_validation_contract_ref,
        pricing_policy_version=DEFAULT_EXA_WEBSETS_PRICING.version,
        effective_policy_sha256=effective_policy.sha256(),
        jurisdiction_policy_ref=intent.selection.body.jurisdiction_policy_ref,
        jurisdiction_regime=regime.value,
        use_policy_ref=intent.selection.body.use_policy_ref,
        retention_policy_ref=intent.selection.body.retention_policy_ref,
        observation_window=observation_window,
        freshness_seconds=effective_policy.channel_freshness_days * 86_400,
        retention_seconds=effective_policy.channel_retention_days * 86_400,
        email_identity_promotion_allowed=(
            channel is ContactChannel.EMAIL and effective_policy.email_identity_promotion_allowed
        ),
        canonical_profile_url=contact.linkedin_url,
        canonical_full_name=contact.full_name,
        employer_name=account.canonical_name,
        employer_domain=account.primary_domain,
        acquisition_native_unit_cap=Decimal(authorization.provider_native_unit_cap),
        acquisition_budget_cap_cents=Decimal(authorization.budget_cap_cents),
        validation_native_unit_cap=Decimal(authorization.validation_native_unit_cap),
        validation_budget_cap_cents=Decimal(authorization.validation_budget_cap_cents),
        entity_research_job_id=entity_research_job_id,
    )
    return ContactChannelPreflight(request=request, csv_bytes=_csv_bytes(contact.linkedin_url))


#: ``core.work_email`` carries the provider's deliverability verdict beside the address (ARV2 D4-b
#: decision 6); ``core.direct_phone`` is still the bare value. Exa Websets returns an address and
#: says nothing about whether the mailbox answers, so the verdict it earns here is ``unverified``.
#: The independent validator that runs after this write is what may later say more.
EMAIL_FIELD_KEY = "core.work_email"
UNPROBED_EMAIL_STATUS = "unverified"


def _channel_value(field_key: str, value: str) -> JsonValue:
    """The observed channel value in the shape its field registry declares."""

    if field_key != EMAIL_FIELD_KEY:
        return value
    return {"address": value, "status": UNPROBED_EMAIL_STATUS}


def _channel_text(value_json: object) -> str | None:
    """The comparable text of a stored channel claim, in either shape ``core.work_email`` has had.

    A corroborating claim may predate D4-b (a bare address string) or be another writer's verdict
    object; both corroborate the same address, and a phone claim is always the bare string.
    """

    if isinstance(value_json, str):
        return value_json.strip().lower()
    if isinstance(value_json, Mapping):
        address = value_json.get("address")
        return address.strip().lower() if isinstance(address, str) else None
    return None


class ExaContactChannelCoordinator:
    """Durable import -> Webset -> observed claim -> validator -> promotion coordinator."""

    def __init__(
        self,
        *,
        transport: ExaWebsetsImportTransport,
        validator: ContactChannelValidator,
        use_gate: UseGate,
        pre_spend_gate: PreSpendGate,
        storage: StorageBackend,
        conn_factory: ConnFactoryLike = transaction,
        pricing: ExaWebsetsPricingPolicy = DEFAULT_EXA_WEBSETS_PRICING,
        poll_after_seconds: int = 15,
        validation_lease_seconds: int = 300,
        budget: BudgetEngine | None = None,
        enforce_budget: bool = True,
    ) -> None:
        if poll_after_seconds < 1 or validation_lease_seconds < 1:
            raise ValueError("contact channel poll and validation lease must be positive")
        self._transport = transport
        self._validator = validator
        self._use_gate = use_gate
        self._gate = pre_spend_gate
        self._storage = storage
        self._conn_factory = conn_factory
        self._pricing = pricing
        self._poll_after = timedelta(seconds=poll_after_seconds)
        self._validation_lease = timedelta(seconds=validation_lease_seconds)
        self._budget = budget or BudgetEngine(store=DbBudgetStore(conn_factory=conn_factory))
        # FI pilot budget-controls: threaded from ``Settings.budget_controls_enabled`` at
        # the composition root and passed to the durable reservation, which stops raising
        # on the project-run cap while writing every ledger row unchanged.
        self._enforce_budget = enforce_budget

    async def start(
        self,
        *,
        intent: ContactResearchIntent,
        effective_policy: ContactResearchPolicyPin,
        channel: ContactChannel,
        observation_window: str,
        entity_research_job_id: UUID | None = None,
        defer_validation: bool = False,
        before_acquisition_dispatch: Callable[[ContactChannelOperation], Awaitable[None]]
        | None = None,
    ) -> ContactChannelEnrichmentResult:
        now = datetime.now(UTC)
        async with self._conn_factory() as conn:
            preflight = await compile_contact_channel_preflight(
                conn,
                intent=intent,
                effective_policy=effective_policy,
                channel=channel,
                observation_window=observation_window,
                entity_research_job_id=entity_research_job_id,
            )
            manifest = await get_source(conn, preflight.request.acquisition_source_key)
            assert manifest is not None
            reusable = await find_fresh_reusable_contact_channel_operation(
                conn,
                request=preflight.request,
                now=now,
            )
            if reusable is not None:
                await record_contact_channel_reuse(
                    conn,
                    request=preflight.request,
                    source_operation=reusable,
                )
                return ContactChannelEnrichmentResult(
                    outcome=ContactChannelEnrichmentOutcome.REPLAYED,
                    operation=reusable,
                )
            exact = await find_contact_channel_operation(conn, request=preflight.request)
            if exact is not None and exact.state is ContactChannelOperationState.SUCCEEDED:
                raise ContactChannelEligibilityError(
                    "the submitted channel request is no longer reusable; use a new observation "
                    "window for a governed refresh"
                )
        decision = await self._gate.check(
            PreSpendRequest(
                entity_id=preflight.request.contact_id,
                entity_type=EntityType.CONTACT,
                field_key=preflight.request.field_key,
                source_tier=SourceTier(manifest.manifest.tier),
                source_key=preflight.request.acquisition_source_key,
                run_id=RunId(preflight.request.project_run_id),
            )
        )
        if decision.verdict is not PreSpendVerdict.PASS:
            raise ContactChannelEligibilityError(
                "channel pre-spend rejected: " + "; ".join(decision.reasons)
            )
        operation, _created = await self._reserve(preflight)
        if operation.state is ContactChannelOperationState.SUCCEEDED:
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.REPLAYED, operation=operation
            )
        if operation.state is ContactChannelOperationState.REJECTED:
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.REJECTED, operation=operation
            )
        if operation.state is ContactChannelOperationState.READY_TO_VALIDATE:
            if defer_validation:
                return ContactChannelEnrichmentResult(
                    outcome=ContactChannelEnrichmentOutcome.READY_TO_VALIDATE,
                    operation=operation,
                )
            return await self._validate_ready(operation, effective_policy=effective_policy)
        if operation.state is ContactChannelOperationState.VALIDATING:
            if operation.next_poll_at is not None and operation.next_poll_at > now:
                return ContactChannelEnrichmentResult(
                    outcome=ContactChannelEnrichmentOutcome.JOINED_IN_FLIGHT,
                    operation=operation,
                )
            quarantined = operation.model_copy(
                update={
                    "state": ContactChannelOperationState.SPEND_OUTCOME_UNKNOWN,
                    "validation_spend_outcome": ContactChannelSpendOutcome.UNKNOWN,
                    "failure_code": "validation_dispatch_interrupted",
                }
            )
            async with self._conn_factory() as conn:
                quarantined = await update_contact_channel_operation(conn, operation=quarantined)
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=quarantined,
            )
        if operation.state is ContactChannelOperationState.SPEND_OUTCOME_UNKNOWN:
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=operation,
            )
        if operation.state in {
            ContactChannelOperationState.FAILED_TERMINAL,
            ContactChannelOperationState.CANCELLED,
        }:
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                operation=operation,
            )
        if operation.provider_operation_id is not None:
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.WAITING_EXTERNAL, operation=operation
            )
        async with self._conn_factory() as conn:
            claimed = await claim_contact_channel_submit(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                now=now,
            )
        if claimed is None:
            async with self._conn_factory() as conn:
                current = await get_contact_channel_operation(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
                stop = await contact_channel_operation_stop(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
            if stop is not None and current.state is not ContactChannelOperationState.SUBMITTING:
                return ContactChannelEnrichmentResult(
                    outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                    operation=current,
                )
            # Only a durable SUBMITTING state can justify an external-id reconciliation call.
            # A stop that won before dispatch leaves the operation CANCELLED and performs zero
            # provider traffic; a stopped SUBMITTING operation must still determine actual spend.
            return await self._recover_submit(current)
        if before_acquisition_dispatch is not None:
            await before_acquisition_dispatch(claimed)
        import_request = build_exa_contact_channel_import(preflight)
        try:
            imported = await self._transport.create_import(import_request)
            if imported.response.integral_count != 1 or imported.response.entity != ExaWebsetEntity(
                type=ExaWebsetEntityType.PERSON
            ):
                raise ExaWebsetsContractDrift("Exa contact import response is not one person")
            _, import_stop = await self._record_active(
                claimed,
                "import_create_sanitized",
                imported.response.sanitized_bytes(),
                f"{EXA_WEBSETS_API_BASE}/imports/{imported.response.id}",
                imported.request_id,
            )
            if import_stop is not None:
                cancelled = await self._cancel_without_new_spend(
                    claimed, reason_code=import_stop.reason_code
                )
                return ContactChannelEnrichmentResult(
                    outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                    operation=cancelled,
                    import_calls=1,
                )
            await self._transport.upload_import_csv(
                upload_url=imported.response.upload_url, content=preflight.csv_bytes
            )
            wire = build_exa_contact_channel_webset(
                preflight.request, import_id=imported.response.id
            )
            exchange = await self._transport.create_webset(wire)
        except ExaWebsetsPreDispatchError:
            failed = await self._fail(claimed, "exa_channel_predispatch", unknown=False)
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.FAILED_RETRYABLE,
                operation=failed,
                import_calls=1,
            )
        except ExaWebsetsError as exc:
            unknown = exc.dispatch_uncertain or exc.status_code == 409
            if unknown:
                return await self._recover_submit(
                    claimed,
                    import_calls=1,
                    upload_calls=1,
                    create_calls=1,
                )
            failed = await self._fail(claimed, "exa_channel_submit_failed", unknown=unknown)
            return ContactChannelEnrichmentResult(
                outcome=(
                    ContactChannelEnrichmentOutcome.SPEND_OUTCOME_UNKNOWN
                    if unknown
                    else ContactChannelEnrichmentOutcome.FAILED_TERMINAL
                ),
                operation=failed,
                import_calls=1,
                upload_calls=1,
                create_calls=1,
            )
        if exchange.webset.external_id != preflight.request.provider_external_id:
            failed = await self._fail(claimed, "exa_channel_external_id_drift", unknown=True)
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=failed,
                import_calls=1,
                upload_calls=1,
                create_calls=1,
            )
        _, create_stop = await self._record_active(
            claimed,
            "webset_create",
            exchange.response_body,
            f"{EXA_WEBSETS_API_BASE}/websets/{exchange.webset.id}",
            exchange.request_id,
        )
        waiting = claimed.model_copy(
            update={
                "state": ContactChannelOperationState.WAITING_EXTERNAL,
                "acquisition_spend_outcome": ContactChannelSpendOutcome.UNKNOWN,
                "provider_import_id": imported.response.id,
                "provider_operation_id": exchange.webset.id,
                "next_poll_at": now + self._poll_after,
            }
        )
        async with self._conn_factory() as conn:
            stored = await update_contact_channel_operation(conn, operation=waiting)
        return ContactChannelEnrichmentResult(
            outcome=(
                ContactChannelEnrichmentOutcome.CREATED
                if create_stop is None
                else ContactChannelEnrichmentOutcome.WAITING_EXTERNAL
            ),
            operation=stored,
            import_calls=1,
            upload_calls=1,
            create_calls=1,
        )

    async def drive_once(
        self,
        *,
        workspace_id: str,
        operation_id: ContactChannelOperationId,
        effective_policy: ContactResearchPolicyPin,
        defer_validation: bool = False,
    ) -> ContactChannelEnrichmentResult:
        async with self._conn_factory() as conn:
            operation = await get_contact_channel_operation(
                conn, workspace_id=workspace_id, operation_id=operation_id
            )
            stop = await contact_channel_operation_stop(
                conn, workspace_id=workspace_id, operation_id=operation_id
            )
        self._require_frozen_policy(operation, effective_policy)
        if stop is not None and operation.state not in {
            ContactChannelOperationState.SUBMITTING,
            ContactChannelOperationState.WAITING_EXTERNAL,
            ContactChannelOperationState.VALIDATING,
        }:
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                operation=operation,
            )
        if operation.state is ContactChannelOperationState.SUCCEEDED:
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.REPLAYED, operation=operation
            )
        if operation.state is ContactChannelOperationState.REJECTED:
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.REJECTED, operation=operation
            )
        if operation.state is ContactChannelOperationState.READY_TO_VALIDATE:
            if defer_validation:
                return ContactChannelEnrichmentResult(
                    outcome=ContactChannelEnrichmentOutcome.READY_TO_VALIDATE,
                    operation=operation,
                )
            return await self._validate_ready(operation, effective_policy=effective_policy)
        if operation.state is ContactChannelOperationState.VALIDATING:
            now = datetime.now(UTC)
            if operation.next_poll_at is not None and operation.next_poll_at > now:
                return ContactChannelEnrichmentResult(
                    outcome=ContactChannelEnrichmentOutcome.JOINED_IN_FLIGHT,
                    operation=operation,
                )
            quarantined = operation.model_copy(
                update={
                    "state": ContactChannelOperationState.SPEND_OUTCOME_UNKNOWN,
                    "validation_spend_outcome": ContactChannelSpendOutcome.UNKNOWN,
                    "failure_code": "validation_dispatch_interrupted",
                }
            )
            async with self._conn_factory() as conn:
                quarantined = await update_contact_channel_operation(conn, operation=quarantined)
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=quarantined,
            )
        if operation.state is ContactChannelOperationState.SPEND_OUTCOME_UNKNOWN:
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=operation,
            )
        if operation.state in {
            ContactChannelOperationState.FAILED_TERMINAL,
            ContactChannelOperationState.CANCELLED,
        }:
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                operation=operation,
            )
        if operation.provider_operation_id is None:
            raise ContactChannelEnrichmentError("channel operation has no provider Webset")
        exchange = await self._transport.poll_webset(operation.provider_operation_id)
        if stop is None:
            await self._record_active(
                operation,
                "webset_poll",
                exchange.response_body,
                f"{EXA_WEBSETS_API_BASE}/websets/{operation.provider_operation_id}",
                exchange.request_id,
            )
        if exchange.webset.status is not ExaWebsetStatus.IDLE:
            waiting = operation.model_copy(
                update={"next_poll_at": datetime.now(UTC) + self._poll_after}
            )
            async with self._conn_factory() as conn:
                waiting = await update_contact_channel_operation(conn, operation=waiting)
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.WAITING_EXTERNAL,
                operation=waiting,
                poll_calls=1,
            )
        imported = next(
            (item for item in exchange.webset.imports if item.id == operation.provider_import_id),
            None,
        )
        if imported is None or imported.status is not ExaImportStatus.COMPLETED:
            failed = await self._fail(
                operation, "exa_channel_import_not_terminal_at_idle", unknown=True
            )
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=failed,
                poll_calls=1,
            )
        definitions = exchange.webset.enrichments
        expected_format = _channel_format(operation.request.channel)
        matching = [
            definition
            for definition in definitions
            if definition.format is expected_format
            and definition.metadata.get("clueFieldKey") == operation.request.field_key
        ]
        if len(matching) != 1 or matching[0].status != "completed":
            failed = await self._fail(
                operation, "exa_channel_enrichment_contract_drift", unknown=True
            )
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=failed,
                poll_calls=1,
            )
        items: list[ExaWebsetItem] = []
        cursor: str | None = None
        item_calls = 0
        while True:
            page = await self._transport.list_items(
                operation.provider_operation_id, cursor=cursor, limit=100
            )
            item_calls += 1
            items.extend(page.page.data)
            cursor = page.page.next_cursor
            if cursor is None:
                break
            if item_calls >= 10:
                raise ContactChannelEnrichmentError("contact channel item pagination exceeded cap")
        if len(items) != 1:
            failed = await self._fail(operation, "exa_channel_import_cardinality", unknown=True)
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=failed,
                poll_calls=1,
                item_calls=item_calls,
            )
        item = items[0]
        value, references, reasoning = self._extract_item(operation, item, matching[0].id)
        stop = await self._current_stop(operation)
        if stop is not None:
            acquisition_units = self._pricing.realized_units(
                matching_search_results=0,
                ordinary_enrichment_rows=0,
                contact_values=int(value is not None),
                resolved_import_results=1,
            ).total_units
            acquisition_cost = self._pricing.monetary_value(acquisition_units)
            cancelled = await self._cancel_after_acquisition(
                operation,
                units=acquisition_units,
                cost_cents=acquisition_cost,
                reason_code=stop.reason_code,
            )
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                operation=cancelled,
                poll_calls=1,
                item_calls=item_calls,
            )
        acquisition_units = self._pricing.realized_units(
            matching_search_results=0,
            ordinary_enrichment_rows=0,
            contact_values=int(value is not None),
            resolved_import_results=1,
        ).total_units
        acquisition_cost = self._pricing.monetary_value(acquisition_units)
        observation_bytes = json.dumps(
            item.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":")
        ).encode()
        observation_key, retention_stop = await self._record_active(
            operation,
            "person_item",
            observation_bytes,
            operation.request.canonical_profile_url,
            None,
        )
        if retention_stop is not None:
            cancelled = await self._cancel_after_acquisition(
                operation,
                units=acquisition_units,
                cost_cents=acquisition_cost,
                reason_code=retention_stop.reason_code,
            )
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                operation=cancelled,
                poll_calls=1,
                item_calls=item_calls,
            )
        assert observation_key is not None
        if value is None:
            failed = operation.model_copy(
                update={
                    "state": ContactChannelOperationState.FAILED_TERMINAL,
                    "acquisition_spend_outcome": ContactChannelSpendOutcome.CHARGED,
                    "acquisition_units_charged": acquisition_units,
                    "acquisition_cost_cents_charged": acquisition_cost,
                    "observation_artifact_key": observation_key,
                    "failure_code": "exa_channel_empty",
                    "next_poll_at": None,
                    "terminal_at": datetime.now(UTC),
                }
            )
            async with self._conn_factory() as conn:
                current = await get_contact_channel_operation(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                    for_update=True,
                )
                final_stop = await contact_channel_operation_stop(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
                stored = await update_contact_channel_operation(
                    conn,
                    operation=(
                        failed
                        if final_stop is None
                        else current.model_copy(
                            update={
                                "state": ContactChannelOperationState.CANCELLED,
                                "acquisition_spend_outcome": ContactChannelSpendOutcome.CHARGED,
                                "acquisition_units_charged": acquisition_units,
                                "acquisition_cost_cents_charged": acquisition_cost,
                                "failure_code": final_stop.reason_code,
                                "next_poll_at": None,
                                "terminal_at": datetime.now(UTC),
                            }
                        )
                    ),
                )
                await self._budget.record(
                    cost_cents=acquisition_cost,
                    scope=BudgetScope.RUN,
                    project_run_id=operation.request.project_run_id,
                    conn=conn,
                )
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                operation=stored,
                poll_calls=1,
                item_calls=item_calls,
            )
        async with self._conn_factory() as conn:
            # The observed claim, its lawful-basis record, operation linkage, and acquisition
            # settlement are one commit boundary. A crash can therefore leave either the prior
            # pollable operation or the complete READY_TO_VALIDATE state, never a detached raw
            # channel claim or a charged operation missing its budget debit.
            current = await get_contact_channel_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            final_stop = await contact_channel_operation_stop(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            if final_stop is not None:
                cancelled = current.model_copy(
                    update={
                        "state": ContactChannelOperationState.CANCELLED,
                        "acquisition_spend_outcome": ContactChannelSpendOutcome.CHARGED,
                        "acquisition_units_charged": acquisition_units,
                        "acquisition_cost_cents_charged": acquisition_cost,
                        "validation_spend_outcome": ContactChannelSpendOutcome.NOT_DISPATCHED,
                        "failure_code": final_stop.reason_code,
                        "next_poll_at": None,
                        "terminal_at": datetime.now(UTC),
                    }
                )
                stored = await update_contact_channel_operation(conn, operation=cancelled)
                await self._budget.record(
                    cost_cents=acquisition_cost,
                    scope=BudgetScope.RUN,
                    project_run_id=operation.request.project_run_id,
                    conn=conn,
                )
                return ContactChannelEnrichmentResult(
                    outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                    operation=stored,
                    poll_calls=1,
                    item_calls=item_calls,
                )
            observed_claim = await self._write_observed_claim(
                conn,
                operation=operation,
                artifact_key=observation_key,
                item=item,
                value=value,
                references=references,
                reasoning=reasoning,
            )
            ready = operation.model_copy(
                update={
                    "state": ContactChannelOperationState.READY_TO_VALIDATE,
                    "acquisition_spend_outcome": ContactChannelSpendOutcome.CHARGED,
                    "observed_claim_id": observed_claim.id,
                    "observation_artifact_key": observation_key,
                    "acquisition_units_charged": acquisition_units,
                    "acquisition_cost_cents_charged": acquisition_cost,
                    "validation_spend_outcome": ContactChannelSpendOutcome.NOT_DISPATCHED,
                    "next_poll_at": None,
                }
            )
            ready = await update_contact_channel_operation(conn, operation=ready)
            await self._budget.record(
                cost_cents=acquisition_cost,
                scope=BudgetScope.RUN,
                project_run_id=operation.request.project_run_id,
                conn=conn,
            )
        if defer_validation:
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.READY_TO_VALIDATE,
                operation=ready,
                poll_calls=1,
                item_calls=item_calls,
            )
        validated = await self._validate_ready(ready, effective_policy=effective_policy)
        return validated.model_copy(update={"poll_calls": 1, "item_calls": item_calls})

    async def validate_ready(
        self,
        *,
        workspace_id: str,
        operation_id: ContactChannelOperationId,
        effective_policy: ContactResearchPolicyPin,
        before_validation_dispatch: Callable[[ContactChannelOperation], Awaitable[None]]
        | None = None,
    ) -> ContactChannelEnrichmentResult:
        """Validate one acquired channel only when a separate semantic tool authorized it."""

        async with self._conn_factory() as conn:
            operation = await get_contact_channel_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=operation_id,
            )
        return await self._validate_ready(
            operation,
            effective_policy=effective_policy,
            before_validation_dispatch=before_validation_dispatch,
        )

    async def _validate_ready(
        self,
        operation: ContactChannelOperation,
        *,
        effective_policy: ContactResearchPolicyPin,
        before_validation_dispatch: Callable[[ContactChannelOperation], Awaitable[None]]
        | None = None,
    ) -> ContactChannelEnrichmentResult:
        """Apply platform use policy, then lease and dispatch the independent validator once."""

        self._require_frozen_policy(operation, effective_policy)
        if operation.state is not ContactChannelOperationState.READY_TO_VALIDATE:
            raise ContactChannelEnrichmentError("channel observation is not ready for validation")
        if self._validator.source_key != operation.request.validation_source_key:
            raise ContactChannelEnrichmentError("validator source differs from frozen request")
        if operation.observed_claim_id is None:
            raise ContactChannelEnrichmentError("ready channel operation lacks an observed claim")
        async with self._conn_factory() as conn:
            claims = await claims_by_ids(
                conn,
                [operation.observed_claim_id],
                scope=WorkspaceScope.private_for_workspace(operation.request.workspace_id),
            )
            value = await read_observed_channel_value(conn, self._storage, operation=operation)
        if len(claims) != 1:
            raise ContactChannelEnrichmentError("observed channel claim is missing")
        observed_claim = claims[operation.observed_claim_id]
        use = await self._use_gate.evaluate(observed_claim)
        if use.claim_id != observed_claim.id:
            raise ContactChannelEnrichmentError("use gate returned a decision for another claim")
        platform_use = (
            ChannelUseDecision.ALLOWED if use.usable_for_outreach else ChannelUseDecision.DENIED
        )
        if platform_use is ChannelUseDecision.DENIED:
            return await self._reject_use_denied(
                operation,
                observed_claim=observed_claim,
                policy_version=use.policy_version,
                policy_reason=use.reason.value,
            )
        async with self._conn_factory() as conn:
            validator_manifest = await get_source(conn, operation.request.validation_source_key)
        if validator_manifest is None or not validator_manifest.active:
            raise ContactChannelEligibilityError("frozen channel validator is no longer active")
        validator_gate = await self._gate.check(
            PreSpendRequest(
                entity_id=operation.request.contact_id,
                entity_type=EntityType.CONTACT,
                field_key=operation.request.field_key,
                source_tier=SourceTier(validator_manifest.manifest.tier),
                source_key=operation.request.validation_source_key,
                run_id=RunId(operation.request.project_run_id),
            )
        )
        if validator_gate.verdict is not PreSpendVerdict.PASS:
            raise ContactChannelEligibilityError(
                "channel validation pre-spend rejected: " + "; ".join(validator_gate.reasons)
            )
        now = datetime.now(UTC)
        async with self._conn_factory() as conn:
            validating = await claim_contact_channel_validation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                now=now,
                lease_until=now + self._validation_lease,
            )
            if validating is None:
                current = await get_contact_channel_operation(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
                stop = await contact_channel_operation_stop(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
                return ContactChannelEnrichmentResult(
                    outcome=(
                        ContactChannelEnrichmentOutcome.FAILED_TERMINAL
                        if stop is not None
                        else ContactChannelEnrichmentOutcome.JOINED_IN_FLIGHT
                    ),
                    operation=current,
                )
        validator_request = ContactChannelValidatorRequest(
            operation_id=operation.operation_id,
            workspace_id=operation.request.workspace_id,
            account_id=operation.request.account_id,
            contact_id=operation.request.contact_id,
            channel=operation.request.channel,
            value=value,
            value_sha256=hashlib.sha256(value.strip().lower().encode()).hexdigest(),
            canonical_full_name=operation.request.canonical_full_name,
            employer_name=operation.request.employer_name,
            employer_domain=operation.request.employer_domain,
            observed_claim_id=observed_claim.id,
        )
        if before_validation_dispatch is not None:
            await before_validation_dispatch(validating)
        validator_result = await self._validator.validate(validator_request)
        if (
            validator_result.provider_units_charged > operation.request.validation_native_unit_cap
            or validator_result.provider_cost_cents_charged
            > operation.request.validation_budget_cap_cents
        ):
            failed = validating.model_copy(
                update={
                    "state": ContactChannelOperationState.SPEND_OUTCOME_UNKNOWN,
                    "validation_spend_outcome": ContactChannelSpendOutcome.UNKNOWN,
                    "failure_code": "channel_validation_cost_exceeds_reservation",
                    "next_poll_at": None,
                }
            )
            async with self._conn_factory() as conn:
                failed = await update_contact_channel_operation(conn, operation=failed)
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=failed,
                validation_calls=1,
            )
        stop = await self._current_stop(validating)
        if stop is not None:
            cancelled = await self._cancel_after_validation(
                validating,
                units=validator_result.provider_units_charged,
                cost_cents=validator_result.provider_cost_cents_charged,
                reason_code=stop.reason_code,
            )
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                operation=cancelled,
                validation_calls=1,
            )
        validator_result = await self._enforce_corroboration(
            operation=validating,
            value=value,
            result=validator_result,
        )
        if (
            operation.request.channel is ContactChannel.EMAIL
            and validator_result.outcome is ContactChannelValidationOutcome.VALIDATED
        ):
            async with self._conn_factory() as conn:
                canonical_contact = await get_contact(conn, operation.request.contact_id)
            if canonical_contact is None:
                raise ContactChannelEnrichmentError(
                    "canonical contact disappeared during validation"
                )
            if canonical_contact.verified_email is not None and (
                canonical_contact.verified_email.strip().lower() != value.strip().lower()
            ):
                validator_result = validator_result.model_copy(
                    update={
                        "outcome": ContactChannelValidationOutcome.REJECTED,
                        "corroboration": "conflicted",
                        "evidence": {
                            **validator_result.evidence,
                            "platform_rejection": (
                                "validated email conflicts with canonical identity"
                            ),
                        },
                    }
                )
        validation_bytes = validator_result.model_dump_json().encode()
        validation_key, retention_stop = await self._record_active(
            validating,
            "independent_validation",
            validation_bytes,
            None,
            validator_result.provider_reference_ids[0],
            source_key=operation.request.validation_source_key,
        )
        if retention_stop is not None:
            cancelled = await self._cancel_after_validation(
                validating,
                units=validator_result.provider_units_charged,
                cost_cents=validator_result.provider_cost_cents_charged,
                reason_code=retention_stop.reason_code,
            )
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                operation=cancelled,
                validation_calls=1,
            )
        assert validation_key is not None
        validation = validator_result.to_validation(
            channel=operation.request.channel,
            observed_claim_id=observed_claim.id,
            allow_identity_promotion=operation.request.email_identity_promotion_allowed,
            use_decision=platform_use,
        )
        terminal_state = (
            ContactChannelOperationState.SUCCEEDED
            if validator_result.outcome is ContactChannelValidationOutcome.VALIDATED
            else (
                ContactChannelOperationState.REJECTED
                if validator_result.outcome is ContactChannelValidationOutcome.REJECTED
                else ContactChannelOperationState.FAILED_TERMINAL
            )
        )
        receipt_payload: dict[str, JsonValue] = {
            "contract": "m8c-c5-contact-channel-receipt-v1",
            "operation_id": str(operation.operation_id),
            "request_fingerprint": operation.request_fingerprint,
            "channel": operation.request.channel.value,
            "observed_claim_id": str(observed_claim.id),
            "provider_webset_id": operation.provider_operation_id,
            "acquisition_units_charged": str(operation.acquisition_units_charged),
            "validation_units_charged": str(validator_result.provider_units_charged),
            "validation_state": validation.state.value,
            "delivery_eligible": validation.delivery_eligible,
            "use_policy_ref": operation.request.use_policy_ref,
            "use_policy_version": use.policy_version,
            "contains_raw_channel": False,
        }
        receipt_key, receipt_stop = await self._record_active(
            validating,
            "terminal_receipt",
            json.dumps(receipt_payload, sort_keys=True, separators=(",", ":")).encode(),
            None,
            None,
        )
        if receipt_stop is not None:
            cancelled = await self._cancel_after_validation(
                validating,
                units=validator_result.provider_units_charged,
                cost_cents=validator_result.provider_cost_cents_charged,
                reason_code=receipt_stop.reason_code,
            )
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                operation=cancelled,
                validation_calls=1,
            )
        assert receipt_key is not None
        terminal = validating.model_copy(
            update={
                "state": terminal_state,
                "validation_spend_outcome": ContactChannelSpendOutcome.CHARGED,
                "validation_artifact_key": validation_key,
                "receipt_artifact_key": receipt_key,
                "validation_units_charged": validator_result.provider_units_charged,
                "validation_cost_cents_charged": validator_result.provider_cost_cents_charged,
                "validation": validation,
                "failure_code": (
                    None
                    if terminal_state is ContactChannelOperationState.SUCCEEDED
                    else "channel_validation_not_accepted"
                ),
                "terminal_at": datetime.now(UTC),
            }
        )
        async with self._conn_factory() as conn:
            current = await get_contact_channel_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            stop = await contact_channel_operation_stop(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            if current.state is not ContactChannelOperationState.VALIDATING:
                return ContactChannelEnrichmentResult(
                    outcome=ContactChannelEnrichmentOutcome.REPLAYED,
                    operation=current,
                    validation_calls=1,
                )
            if stop is not None:
                cancelled = terminal.model_copy(
                    update={
                        "state": ContactChannelOperationState.CANCELLED,
                        "validation": None,
                        "validation_artifact_key": None,
                        "receipt_artifact_key": None,
                        "failure_code": stop.reason_code,
                    }
                )
                stored = await update_contact_channel_operation(conn, operation=cancelled)
                await self._budget.record(
                    cost_cents=validator_result.provider_cost_cents_charged,
                    scope=BudgetScope.RUN,
                    project_run_id=operation.request.project_run_id,
                    conn=conn,
                )
                return ContactChannelEnrichmentResult(
                    outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                    operation=stored,
                    validation_calls=1,
                )
            stored = await update_contact_channel_operation(conn, operation=terminal)
            await self._budget.record(
                cost_cents=validator_result.provider_cost_cents_charged,
                scope=BudgetScope.RUN,
                project_run_id=operation.request.project_run_id,
                conn=conn,
            )
            # A rejected operation is itself unusable. It intentionally does not create a
            # subject-wide suppression: a later, newly-authorized operation may use another
            # independent validator. Global suppression is reserved for objection, erasure, and
            # retention-expiry policy.
            if (
                validation.state.value == "verified_identity"
                and operation.request.channel is ContactChannel.EMAIL
            ):
                await promote_contact_verified_email(
                    conn,
                    contact_entity_id=operation.request.contact_id,
                    verified_email=value,
                )
        return ContactChannelEnrichmentResult(
            outcome=(
                ContactChannelEnrichmentOutcome.SUCCEEDED
                if terminal_state is ContactChannelOperationState.SUCCEEDED
                else (
                    ContactChannelEnrichmentOutcome.REJECTED
                    if terminal_state is ContactChannelOperationState.REJECTED
                    else ContactChannelEnrichmentOutcome.FAILED_TERMINAL
                )
            ),
            operation=stored,
            validation_calls=1,
        )

    async def _current_stop(
        self, operation: ContactChannelOperation
    ) -> ContactResearchOperationStop | None:
        async with self._conn_factory() as conn:
            return await contact_channel_operation_stop(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )

    async def _cancel_after_acquisition(
        self,
        operation: ContactChannelOperation,
        *,
        units: Decimal,
        cost_cents: Decimal,
        reason_code: str,
    ) -> ContactChannelOperation:
        cancelled = operation.model_copy(
            update={
                "state": ContactChannelOperationState.CANCELLED,
                "acquisition_spend_outcome": ContactChannelSpendOutcome.CHARGED,
                "acquisition_units_charged": units,
                "acquisition_cost_cents_charged": cost_cents,
                "validation_spend_outcome": ContactChannelSpendOutcome.NOT_DISPATCHED,
                "failure_code": reason_code,
                "next_poll_at": None,
                "terminal_at": datetime.now(UTC),
            }
        )
        async with self._conn_factory() as conn:
            current = await get_contact_channel_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current.state in {
                ContactChannelOperationState.CANCELLED,
                ContactChannelOperationState.SUCCEEDED,
                ContactChannelOperationState.REJECTED,
                ContactChannelOperationState.FAILED_TERMINAL,
            }:
                return current
            stored = await update_contact_channel_operation(conn, operation=cancelled)
            await self._budget.record(
                cost_cents=cost_cents,
                scope=BudgetScope.RUN,
                project_run_id=operation.request.project_run_id,
                conn=conn,
            )
            return stored

    async def _cancel_without_new_spend(
        self,
        operation: ContactChannelOperation,
        *,
        reason_code: str,
    ) -> ContactChannelOperation:
        """Cancel already-settled acquisition work without debiting its cost a second time."""

        async with self._conn_factory() as conn:
            current = await get_contact_channel_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current.state in {
                ContactChannelOperationState.CANCELLED,
                ContactChannelOperationState.SUCCEEDED,
                ContactChannelOperationState.REJECTED,
                ContactChannelOperationState.FAILED_TERMINAL,
            }:
                return current
            return await update_contact_channel_operation(
                conn,
                operation=current.model_copy(
                    update={
                        "state": ContactChannelOperationState.CANCELLED,
                        "failure_code": reason_code,
                        "next_poll_at": None,
                        "terminal_at": datetime.now(UTC),
                    }
                ),
            )

    async def _cancel_after_validation(
        self,
        operation: ContactChannelOperation,
        *,
        units: Decimal,
        cost_cents: Decimal,
        reason_code: str,
    ) -> ContactChannelOperation:
        cancelled = operation.model_copy(
            update={
                "state": ContactChannelOperationState.CANCELLED,
                "validation_spend_outcome": ContactChannelSpendOutcome.CHARGED,
                "validation_units_charged": units,
                "validation_cost_cents_charged": cost_cents,
                "failure_code": reason_code,
                "next_poll_at": None,
                "terminal_at": datetime.now(UTC),
            }
        )
        async with self._conn_factory() as conn:
            current = await get_contact_channel_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current.state is not ContactChannelOperationState.VALIDATING:
                return current
            stored = await update_contact_channel_operation(conn, operation=cancelled)
            await self._budget.record(
                cost_cents=cost_cents,
                scope=BudgetScope.RUN,
                project_run_id=operation.request.project_run_id,
                conn=conn,
            )
            return stored

    async def _reject_use_denied(
        self,
        operation: ContactChannelOperation,
        *,
        observed_claim: Claim,
        policy_version: int,
        policy_reason: str,
    ) -> ContactChannelEnrichmentResult:
        validation = ContactChannelValidation(
            channel=operation.request.channel,
            observed_claim_id=observed_claim.id,
            state=ContactChannelState.REJECTED,
            identity_binding=observed_claim.identity_binding or IdentityBinding.WEAK,
            use_decision=ChannelUseDecision.DENIED,
        )
        payload: dict[str, JsonValue] = {
            "contract": "m8c-c5-platform-use-decision-v1",
            "operation_id": str(operation.operation_id),
            "claim_id": str(observed_claim.id),
            "policy_ref": operation.request.use_policy_ref,
            "policy_version": policy_version,
            "reason": policy_reason,
            "usable_for_outreach": False,
            "contains_raw_channel": False,
        }
        artifact_key, retention_stop = await self._record_active(
            operation,
            "platform_use_denial",
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
            None,
            None,
            source_key=operation.request.validation_source_key,
        )
        if retention_stop is not None:
            cancelled = await self._cancel_without_new_spend(
                operation, reason_code=retention_stop.reason_code
            )
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                operation=cancelled,
            )
        assert artifact_key is not None
        receipt_key, receipt_stop = await self._record_active(
            operation,
            "terminal_receipt",
            json.dumps(
                {
                    **payload,
                    "contract": "m8c-c5-contact-channel-receipt-v1",
                    "validation_state": validation.state.value,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            None,
            None,
        )
        if receipt_stop is not None:
            cancelled = await self._cancel_without_new_spend(
                operation, reason_code=receipt_stop.reason_code
            )
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                operation=cancelled,
            )
        assert receipt_key is not None
        rejected = operation.model_copy(
            update={
                "state": ContactChannelOperationState.REJECTED,
                "validation_spend_outcome": ContactChannelSpendOutcome.NOT_CHARGED,
                "validation_artifact_key": artifact_key,
                "receipt_artifact_key": receipt_key,
                "validation": validation,
                "failure_code": "channel_use_denied",
                "terminal_at": datetime.now(UTC),
            }
        )
        async with self._conn_factory() as conn:
            current = await get_contact_channel_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            final_stop = await contact_channel_operation_stop(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            stored = await update_contact_channel_operation(
                conn,
                operation=(
                    rejected
                    if final_stop is None
                    else current.model_copy(
                        update={
                            "state": ContactChannelOperationState.CANCELLED,
                            "validation": None,
                            "validation_artifact_key": None,
                            "receipt_artifact_key": None,
                            "failure_code": final_stop.reason_code,
                            "terminal_at": datetime.now(UTC),
                        }
                    )
                ),
            )
        return ContactChannelEnrichmentResult(
            outcome=(
                ContactChannelEnrichmentOutcome.REJECTED
                if final_stop is None
                else ContactChannelEnrichmentOutcome.FAILED_TERMINAL
            ),
            operation=stored,
        )

    @staticmethod
    def _require_frozen_policy(
        operation: ContactChannelOperation,
        effective_policy: ContactResearchPolicyPin,
    ) -> None:
        request = operation.request
        if not effective_policy.contact_reveals_enabled:
            raise ContactChannelEligibilityError("effective policy now disables contact reveals")
        if effective_policy.sha256() != request.effective_policy_sha256:
            raise ContactChannelEligibilityError(
                "effective contact policy differs from the frozen channel request"
            )
        if (
            request.acquisition_source_key not in effective_policy.channel_reveal_source_plan
            or request.validation_source_key not in effective_policy.channel_validation_source_plan
            or request.provider_contract_version
            != f"{EXA_WEBSETS_CONTRACT_VERSION}|{effective_policy.exa_websets_contract_ref}"
            or request.validation_contract_version
            != effective_policy.channel_validation_contract_ref
        ):
            raise ContactChannelEligibilityError(
                "channel provider contract differs from the frozen effective policy"
            )

    async def _reserve(
        self, preflight: ContactChannelPreflight
    ) -> tuple[ContactChannelOperation, bool]:
        async with self._conn_factory() as conn:
            # Serialize operation creation with both selection cancellation and subject-level
            # objection/erasure. These locks close the compiler-to-reservation race without ever
            # holding a transaction across provider traffic.
            selection_row = (
                await conn.execute(
                    text(
                        "SELECT id FROM contact_research_selection "
                        "WHERE workspace_id=:workspace_id AND id=:selection_id FOR UPDATE"
                    ),
                    {
                        "workspace_id": preflight.request.workspace_id,
                        "selection_id": preflight.request.selection_id,
                    },
                )
            ).scalar_one_or_none()
            if selection_row is None:
                raise ContactChannelEligibilityError("selected-contact authority no longer exists")
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:subject_lock, 0))"),
                {
                    "subject_lock": (
                        f"contact-research:{preflight.request.workspace_id}:"
                        f"{preflight.request.contact_id}"
                    )
                },
            )
            blocked = (
                await conn.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM contact_research_selection_cancellation "
                        "WHERE selection_id=:selection_id) OR EXISTS (SELECT 1 FROM "
                        "outreach_objected WHERE workspace_id=:workspace_id "
                        "AND contact_entity_id=:contact_id) OR EXISTS (SELECT 1 FROM "
                        "contact_channel_suppression WHERE workspace_id=:workspace_id "
                        "AND contact_id=:contact_id AND channel=CAST(:channel AS "
                        "contact_channel_kind))"
                    ),
                    {
                        "workspace_id": preflight.request.workspace_id,
                        "selection_id": preflight.request.selection_id,
                        "contact_id": preflight.request.contact_id,
                        "channel": preflight.request.channel.value,
                    },
                )
            ).scalar_one()
            if blocked:
                raise ContactChannelEligibilityError(
                    "selected-contact authority was cancelled, objected, or erased"
                )
            existing = await find_contact_channel_operation(conn, request=preflight.request)
            if existing is not None:
                return existing, False
            input_payload = json.dumps(
                {
                    "contract": "m8c-c5-contact-channel-request-v1",
                    "lineage": preflight.request.model_dump(mode="json"),
                    "contains_raw_channel": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            input_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=preflight.request.workspace_id,
                content=input_payload,
                media_type="application/json",
                source_key=preflight.request.acquisition_source_key,
                source_url=f"{EXA_WEBSETS_API_BASE}/websets",
            )
            csv_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=preflight.request.workspace_id,
                content=preflight.csv_bytes,
                media_type="text/csv",
                source_key=preflight.request.acquisition_source_key,
                source_url=preflight.request.canonical_profile_url,
            )
            stored, created = await reserve_contact_channel_operation(
                conn,
                request=preflight.request,
                input_artifact_key=input_key,
                csv_artifact_key=csv_key,
                enforce_budget=self._enforce_budget,
            )
            for key, kind in ((input_key, "request"), (csv_key, "profile_import")):
                await bind_discovery_artifact_subject(
                    conn,
                    workspace_id=preflight.request.workspace_id,
                    artifact_key_value=key,
                    subject_kind="contact",
                    subject_entity_id=preflight.request.contact_id,
                    reference_kind=f"contact_channel_{kind}",
                    reference_id=str(stored.operation_id),
                )
            return stored, created

    async def _recover_submit(
        self,
        operation: ContactChannelOperation,
        *,
        import_calls: int = 0,
        upload_calls: int = 0,
        create_calls: int = 0,
    ) -> ContactChannelEnrichmentResult:
        """Recover an interrupted/uncertain create using Exa's stable external id."""

        try:
            exchange = await self._transport.get_webset(operation.request.provider_external_id)
        except ExaWebsetNotFound:
            stop = await self._current_stop(operation)
            if stop is not None:
                cancelled = await self._cancel_without_new_spend(
                    operation, reason_code=stop.reason_code
                )
                return ContactChannelEnrichmentResult(
                    outcome=ContactChannelEnrichmentOutcome.FAILED_TERMINAL,
                    operation=cancelled,
                    import_calls=import_calls,
                    upload_calls=upload_calls,
                    create_calls=create_calls,
                )
            retryable = operation.model_copy(
                update={
                    "state": ContactChannelOperationState.FAILED_RETRYABLE,
                    "acquisition_spend_outcome": ContactChannelSpendOutcome.NOT_CHARGED,
                    "failure_code": "exa_channel_external_id_absent",
                }
            )
            async with self._conn_factory() as conn:
                retryable = await update_contact_channel_operation(conn, operation=retryable)
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.FAILED_RETRYABLE,
                operation=retryable,
                import_calls=import_calls,
                upload_calls=upload_calls,
                create_calls=create_calls,
            )
        except ExaWebsetsError:
            unknown = await self._fail(
                operation, "exa_channel_create_lookup_indeterminate", unknown=True
            )
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                import_calls=import_calls,
                upload_calls=upload_calls,
                create_calls=create_calls,
            )
        if (
            exchange.webset.external_id != operation.request.provider_external_id
            or len(exchange.webset.imports) != 1
            or len(exchange.webset.enrichments) != 1
            or exchange.webset.imports[0].entity != ExaWebsetEntity(type=ExaWebsetEntityType.PERSON)
            or exchange.webset.enrichments[0].format
            is not _channel_format(operation.request.channel)
        ):
            unknown = await self._fail(
                operation, "exa_channel_create_lookup_contract_drift", unknown=True
            )
            return ContactChannelEnrichmentResult(
                outcome=ContactChannelEnrichmentOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                import_calls=import_calls,
                upload_calls=upload_calls,
                create_calls=create_calls,
            )
        await self._record_active(
            operation,
            "webset_create_recovered",
            exchange.response_body,
            f"{EXA_WEBSETS_API_BASE}/websets/{exchange.webset.id}",
            exchange.request_id,
        )
        waiting = operation.model_copy(
            update={
                "state": ContactChannelOperationState.WAITING_EXTERNAL,
                "acquisition_spend_outcome": ContactChannelSpendOutcome.UNKNOWN,
                "provider_import_id": exchange.webset.imports[0].id,
                "provider_operation_id": exchange.webset.id,
                "next_poll_at": datetime.now(UTC) + self._poll_after,
            }
        )
        async with self._conn_factory() as conn:
            waiting = await update_contact_channel_operation(conn, operation=waiting)
        return ContactChannelEnrichmentResult(
            outcome=ContactChannelEnrichmentOutcome.WAITING_EXTERNAL,
            operation=waiting,
            import_calls=import_calls,
            upload_calls=upload_calls,
            create_calls=create_calls,
        )

    async def _enforce_corroboration(
        self,
        *,
        operation: ContactChannelOperation,
        value: str,
        result: ContactChannelValidatorResult,
    ) -> ContactChannelValidatorResult:
        """The validator cannot mint identity corroboration by assertion alone."""

        if result.outcome is ContactChannelValidationOutcome.REJECTED:
            if (
                result.identity_binding is IdentityBinding.STRONG
                and result.corroboration.value != "conflicted"
                and result.reachability.value != "unreachable"
            ):
                return result.model_copy(
                    update={
                        "corroboration": "conflicted",
                        "evidence": {
                            **result.evidence,
                            "platform_rejection": "validator rejected without a typed reason",
                        },
                    }
                )
            return result
        if result.outcome is ContactChannelValidationOutcome.INCONCLUSIVE:
            return result
        if (
            result.identity_binding is not IdentityBinding.STRONG
            or result.corroboration.value != "matched"
            or result.reachability.value != "reachable"
        ):
            return result.model_copy(
                update={
                    "outcome": ContactChannelValidationOutcome.REJECTED,
                    "evidence": {
                        **result.evidence,
                        "platform_rejection": (
                            "validation lacked strong binding, matching corroboration, or "
                            "reachability"
                        ),
                    },
                }
            )
        ids = list(result.corroborating_claim_ids)
        if not ids:
            return result.model_copy(
                update={
                    "outcome": ContactChannelValidationOutcome.REJECTED,
                    "identity_binding": IdentityBinding.WEAK,
                    "corroboration": "conflicted",
                    "evidence": {
                        **result.evidence,
                        "platform_rejection": "missing independent corroborating claim",
                    },
                }
            )
        async with self._conn_factory() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, entity_id, field_key, value_json, source_key, "
                            "verification_status::text, superseded_by, workspace_id FROM claim "
                            "WHERE id = ANY(:ids)"
                        ),
                        {"ids": ids},
                    )
                )
                .mappings()
                .all()
            )
        expected = value.strip().lower()
        valid = len(rows) == len(ids) and all(
            row["entity_id"] == operation.request.contact_id
            and str(row["field_key"]) == operation.request.field_key
            and _channel_text(row["value_json"]) == expected
            and row["source_key"] != operation.request.acquisition_source_key
            and row["verification_status"] != "rejected"
            and row["superseded_by"] is None
            and row["workspace_id"] == operation.request.workspace_id
            for row in rows
        )
        if valid:
            return result
        return result.model_copy(
            update={
                "outcome": ContactChannelValidationOutcome.REJECTED,
                "identity_binding": IdentityBinding.WEAK,
                "corroboration": "conflicted",
                "evidence": {
                    **result.evidence,
                    "platform_rejection": "corroborating claim is missing or mismatched",
                },
            }
        )

    async def _record_active(
        self,
        operation: ContactChannelOperation,
        kind: str,
        body: bytes,
        source_url: str | None,
        request_id: str | None,
        *,
        source_key: str | None = None,
    ) -> tuple[str | None, ContactResearchOperationStop | None]:
        """Retain subject data only while the exact operation remains unstopped.

        The operation-row lock serializes this write with cancellation, objection, and erasure.
        If retention wins, a waiting privacy transaction sees and purges it; if the stop wins,
        provider/contact data cannot be recreated after the stop commits.
        """

        async with self._conn_factory() as conn:
            await get_contact_channel_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            stop = await contact_channel_operation_stop(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            if stop is not None:
                return None, stop
            key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=body,
                media_type="application/json",
                source_key=source_key or operation.request.acquisition_source_key,
                source_url=source_url,
            )
            await append_contact_channel_artifact(
                conn,
                operation=operation,
                artifact_kind=kind,
                artifact_key=key,
                content_sha256=content_address(body),
                provider_request_id=request_id,
            )
            await bind_discovery_artifact_subject(
                conn,
                workspace_id=operation.request.workspace_id,
                artifact_key_value=key,
                subject_kind="contact",
                subject_entity_id=operation.request.contact_id,
                reference_kind=f"contact_channel_{kind}",
                reference_id=str(operation.operation_id),
            )
            return key, None

    async def _fail(
        self, operation: ContactChannelOperation, code: str, *, unknown: bool
    ) -> ContactChannelOperation:
        update = operation.model_copy(
            update={
                "state": (
                    ContactChannelOperationState.SPEND_OUTCOME_UNKNOWN
                    if unknown
                    else (
                        ContactChannelOperationState.FAILED_RETRYABLE
                        if operation.provider_operation_id is None
                        else ContactChannelOperationState.FAILED_TERMINAL
                    )
                ),
                "acquisition_spend_outcome": (
                    ContactChannelSpendOutcome.UNKNOWN
                    if unknown
                    else ContactChannelSpendOutcome.NOT_CHARGED
                ),
                "failure_code": code,
                "terminal_at": (
                    datetime.now(UTC)
                    if not unknown and operation.provider_operation_id is not None
                    else None
                ),
                "next_poll_at": None,
            }
        )
        async with self._conn_factory() as conn:
            current = await get_contact_channel_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            stop = await contact_channel_operation_stop(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            if stop is not None and not unknown:
                update = current.model_copy(
                    update={
                        "state": ContactChannelOperationState.CANCELLED,
                        "acquisition_spend_outcome": ContactChannelSpendOutcome.NOT_CHARGED,
                        "failure_code": stop.reason_code,
                        "terminal_at": datetime.now(UTC),
                        "next_poll_at": None,
                    }
                )
            return await update_contact_channel_operation(conn, operation=update)

    def _extract_item(
        self, operation: ContactChannelOperation, item: ExaWebsetItem, enrichment_id: str
    ) -> tuple[str | None, tuple[str, ...], str | None]:
        if (
            item.source != "import"
            or item.source_id != operation.provider_import_id
            or item.webset_id != operation.provider_operation_id
            or item.properties.type != "person"
        ):
            raise ExaWebsetsContractDrift("Exa contact item crosses its imported person")
        expected = operation.request.canonical_profile_url.rstrip("/").lower()
        returned = (item.source_entity_id or "").rstrip("/").lower()
        if returned != expected:
            raise ExaWebsetsContractDrift("Exa contact item resolved a different profile URL")
        results = [
            result for result in item.enrichment_results if result.enrichment_id == enrichment_id
        ]
        if len(results) != 1 or results[0].status != "completed":
            raise ExaWebsetsContractDrift("Exa contact item lacks its terminal enrichment")
        result = results[0]
        if result.format is not _channel_format(operation.request.channel):
            raise ExaWebsetsContractDrift("Exa contact enrichment format changed")
        if result.result is not None and len(result.result) != 1:
            raise ExaWebsetsContractDrift("Exa contact enrichment returned multiple values")
        value = None if result.result is None else result.result[0].strip()
        if value is not None:
            self._validate_value(operation.request.channel, value)
        return value, tuple(ref.url for ref in result.references), result.reasoning

    @staticmethod
    def _validate_value(channel: ContactChannel, value: str) -> None:
        if channel is ContactChannel.EMAIL:
            local, separator, host = value.lower().partition("@")
            if not local or separator != "@" or not host or "." not in host or " " in value:
                raise ExaWebsetsContractDrift("Exa returned a malformed email")
        else:
            digits = "".join(character for character in value if character.isdigit())
            if not 7 <= len(digits) <= 15:
                raise ExaWebsetsContractDrift("Exa returned a malformed phone")

    async def _write_observed_claim(
        self,
        conn: AsyncConnection,
        *,
        operation: ContactChannelOperation,
        artifact_key: str,
        item: ExaWebsetItem,
        value: str,
        references: tuple[str, ...],
        reasoning: str | None,
    ) -> Claim:
        # FI-2 P2 (spec §3): the observed channel claim is stamped with the project run itself as
        # its ``run_id``, so that is the id the project lens must resolve. Registered here, in the
        # caller's transaction — the same one ``insert_claim`` below commits in. ``enrichment``
        # matches the other project-run-keyed enrichment writer (the Sumble materializer), so the
        # first-writer-wins ``kind`` on this shared run id is the same value either way.
        await record_run_lineage(
            conn,
            run_id=UUID(str(operation.request.project_run_id)),
            workspace_id=operation.request.workspace_id,
            kind="enrichment",
            project_id=operation.request.project_id,
            project_run_id=UUID(str(operation.request.project_run_id)),
        )
        source_url = references[0] if references else operation.request.canonical_profile_url
        if urlsplit(source_url).scheme not in {"http", "https"}:
            source_url = operation.request.canonical_profile_url
        span = (
            f"Exa Websets returned one {operation.request.channel.value} value for the exact "
            f"imported profile. References: {', '.join(references[:3]) or 'imported profile'}. "
            f"Provider reasoning: {reasoning or 'not supplied'}."
        )
        # Do not pass channel fields through the legacy prefix-only ``stamp_reuse`` classifier:
        # ``core.work_email`` is explicitly tenant-private in the field registry, while the older
        # classifier treats generic ``core.*`` API claims as public. Born-private here plus the
        # registry write gate below is the fail-closed C5 contract.
        claim = Claim(
            entity_id=operation.request.contact_id,
            entity_type=EntityType.CONTACT,
            field_key=operation.request.field_key,
            value_json=_channel_value(operation.request.field_key, value),
            source_url=source_url,
            source_key=operation.request.acquisition_source_key,
            artifact_key=artifact_key,
            source_operation_ref=str(operation.operation_id),
            source_snapshot_ref=item.id,
            source_request_ref=operation.provider_operation_id,
            provenance_kind=ClaimProvenanceKind.PROVIDER_RETURNED,
            source_tier=2,
            extraction_method=ExtractionMethod.API,
            evidence_span=span,
            confidence=0.9,
            observed_at=item.updated_at,
            cost_cents=Decimal(0),
            run_id=RunId(operation.request.project_run_id),
            research_mode=ResearchMode.CONTACT_PROFILING,
            # A provider-returned channel is only observed here. The exact contact profile is
            # strong, but the channel itself remains weak until the independent validator and
            # platform corroboration steps complete.
            identity_binding=IdentityBinding.WEAK,
            use_class=UseClass.PROFESSIONAL_PUBLIC,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
            workspace_id=operation.request.workspace_id,
        )
        await load_core_pack(conn)
        # Boot order: a source manifest's ``yields`` validate against the field
        # registry, and the tier-3 ``exa_search`` seed yields ``client.*`` keys — so
        # the client-knowledge pack must be loaded before the manifests are seeded.
        await load_client_knowledge_pack(conn)
        await seed_source_manifests(conn)
        inserted = await insert_claim(conn, claim)
        retention = timedelta(seconds=operation.request.retention_seconds)
        await record_lawful_basis(
            conn,
            claim,
            regime=Jurisdiction(operation.request.jurisdiction_regime),
            retention=RetentionTtls(
                personal_claim_ttl=retention,
                sensitive_claim_ttl=retention,
                professional_claim_ttl=retention,
            ),
            third_party_collected=True,
        )
        if inserted != claim.id:
            raise ContactChannelEnrichmentError("observed channel claim identity drifted")
        return claim


async def read_observed_channel_value(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    operation: ContactChannelOperation,
) -> str:
    """Governed audit helper; raw values never appear in generic receipts or drafting context."""

    if operation.observation_artifact_key is None:
        raise ContactChannelEnrichmentError("channel operation has no observation artifact")
    _, payload = await read_verified_artifact(
        conn,
        storage,
        storage_key=operation.observation_artifact_key,
        workspace_id=operation.request.workspace_id,
    )
    item = ExaWebsetItem.model_validate_json(payload)
    values = [value for result in item.enrichment_results for value in (result.result or ())]
    if len(values) != 1:
        raise ContactChannelEnrichmentError("stored channel observation is not singular")
    return values[0]


__all__ = [
    "ContactChannelEligibilityError",
    "ContactChannelEnrichmentError",
    "ContactChannelEnrichmentOutcome",
    "ContactChannelEnrichmentResult",
    "ContactChannelPreflight",
    "ExaContactChannelCoordinator",
    "build_exa_contact_channel_import",
    "build_exa_contact_channel_webset",
    "compile_contact_channel_preflight",
    "read_observed_channel_value",
]
