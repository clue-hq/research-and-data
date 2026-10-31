"""Durable, provider-observed Contact email acquisition for FI-2 Slice 10.

This is intentionally not C5's validated contact-channel workflow. A Contacts-table click is
authenticated human intent to ask AI Ark for one exact LinkedIn-identified person's work email,
through the same ``/v1/people/export/single`` export the ARV2 research agents use (founder
ruling 2026-09-29; the Exa Websets and Sumble providers below are no longer composed). Results
stay unverified claims, are never promoted into ``contact_entity.verified_email``, and are
displayed only after the existing jurisdiction/use and display-policy checks.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, JsonValue, SecretStr
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.ai_ark_client import (
    AI_ARK_BASE_URL,
    AiArkClient,
    AiArkEmailExport,
    AiArkResponseError,
)
from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.errors import ProviderHalted
from clue_api.arv2.provider_ledger import (
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.transport import HttpxTransport
from clue_api.exa_websets_submit import DEFAULT_EXA_WEBSETS_PRICING
from clue_api.frontend_read.accounts_list import WireModel
from clue_api.frontend_read.v1_shared import arv2_display_allowed
from clue_api.provider_observers import provider_observer
from clue_config import STRICT_DEFAULT_REGIME, Jurisdiction, RetentionTtls
from clue_core import (
    Claim,
    ClaimId,
    ClaimProvenanceKind,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    ReuseScope,
    RunId,
    UseClass,
    VerificationStatus,
)
from clue_db import ConnFactory, transaction
from clue_research.adapters.exa_websets import (
    EXA_WEBSETS_API_BASE,
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
    ExaWebsetsAuthenticationError,
    ExaWebsetsClient,
    ExaWebsetsContractDrift,
    ExaWebsetsError,
    ExaWebsetsInvalidRequest,
    ExaWebsetsPaymentRequired,
    ExaWebsetsPermissionDenied,
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
from clue_research.compliance import (
    CONTACT_JURISDICTION,
    UseGateImpl,
    load_workspace_policy,
    record_lawful_basis,
)
from clue_research.durable import bind_discovery_artifact_subject, capture_discovery_artifact
from clue_research.resolvers.http import ProviderResponseError
from clue_research.resolvers.sumble import SUMBLE_API_BASE, SumbleContractError
from clue_research.resolvers.sumble.committee_transport import (
    SumbleEmailTransport,
    SumbleV9CommitteeClient,
    require_matching_people_request_id,
)
from clue_research.resolvers.sumble.people import (
    PEOPLE_EMAIL_REVEAL_MAX_CREDITS,
    PEOPLE_SOURCE_KEY,
    SumblePeopleStatus,
    extract_matched_work_email,
    people_email_match_request,
)
from clue_research.sources import seed_source_manifests
from clue_storage import StorageBackend

ConnFactoryLike = Callable[[], AbstractAsyncContextManager[AsyncConnection]]

_CONTRACT_VERSION = "fi2-contact-email-lookup-v1"
_FIELD_KEY = "core.work_email"
#: The ``core.work_email`` verdict for an address no provider probed (registry vocabulary).
_UNPROBED_STATUS = "unverified"
AI_ARK_SOURCE_KEY = "ai_ark_people"
_PROVIDER_LABELS = {
    EXA_WEBSETS_SOURCE_KEY: "Exa",
    PEOPLE_SOURCE_KEY: "Sumble",
    AI_ARK_SOURCE_KEY: "AI Ark",
}


class EmailLookupState(StrEnum):
    PENDING = "pending"
    AVAILABLE = "available"
    NOT_FOUND = "not_found"
    WITHHELD = "withheld"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class EmailResolution(StrEnum):
    PENDING = "pending"
    MATCHED = "matched"
    SINGLE_SOURCE = "single_source"
    CONFLICT = "conflict"
    NONE = "none"
    WITHHELD = "withheld"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class ProviderState(StrEnum):
    PLANNED = "planned"
    SUBMITTING = "submitting"
    WAITING_EXTERNAL = "waiting_external"
    POLLING = "polling"
    AVAILABLE = "available"
    NO_RESULT = "no_result"
    WITHHELD = "withheld"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    CONTRACT_ERROR = "contract_error"
    SPEND_UNKNOWN = "spend_unknown"

    @property
    def terminal(self) -> bool:
        return self in {
            self.AVAILABLE,
            self.NO_RESULT,
            self.WITHHELD,
            self.UNAVAILABLE,
            self.FAILED,
            self.CONTRACT_ERROR,
            self.SPEND_UNKNOWN,
        }


class EmailSource(WireModel):
    key: str
    label: str


class EmailResult(WireModel):
    value: str
    sources: tuple[EmailSource, ...]


class ContactEmailLookupView(WireModel):
    lookup_id: uuid.UUID
    state: EmailLookupState
    # Machine metadata only. The Contacts table deliberately adds no verification badge.
    resolution: EmailResolution
    emails: tuple[EmailResult, ...] = ()
    retryable: bool = False


class EmailLookupTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    account_id: uuid.UUID
    contact_id: uuid.UUID
    full_name: str
    linkedin_url: str
    account_name: str
    primary_domain: str | None = None


class ProviderArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    content: bytes
    source_url: str | None = None
    request_id: str | None = None


class ProviderProgress(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: ProviderState
    provider_import_id: str | None = None
    provider_operation_id: str | None = None
    email: str | None = None
    # The provider's own mailbox verdict (``core.work_email`` status vocabulary) and when it was
    # checked. ``None`` for a source that returns an address without probing it.
    email_status: str | None = None
    checked_at: str | None = None
    source_url: str | None = None
    observed_at: datetime | None = None
    credits_used: Decimal = Decimal(0)
    cost_cents: Decimal = Decimal(0)
    next_poll_at: datetime | None = None
    artifacts: tuple[ProviderArtifact, ...] = ()
    failure_code: str | None = None


class ProviderAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lookup_id: uuid.UUID
    workspace_id: str
    source_key: str
    state: ProviderState
    request_json: dict[str, JsonValue]
    provider_import_id: str | None = None
    provider_operation_id: str | None = None


class ContactEmailProvider(Protocol):
    source_key: str

    @property
    def available(self) -> bool: ...

    def request_json(self, target: EmailLookupTarget) -> dict[str, JsonValue]: ...

    async def start(self, target: EmailLookupTarget, *, external_id: str) -> ProviderProgress: ...

    async def poll(
        self, target: EmailLookupTarget, attempt: ProviderAttempt
    ) -> ProviderProgress: ...


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def _normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    local, separator, host = normalized.partition("@")
    if not local or separator != "@" or not host or "." not in host or " " in normalized:
        raise ValueError("provider returned a malformed email")
    return normalized


def _claim_address(value: JsonValue) -> str | None:
    """The address inside a ``core.work_email`` value, in either shape it has ever had.

    Since D4-b the value is ``{"address", "status", …}``; rows written before it are the bare
    address string, and this view is a provider-attempt history that still points at them.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        address = value.get("address")
        return address if isinstance(address, str) else None
    return None


def _normalized_profile(value: str) -> str:
    return value.strip().rstrip("/").lower()


def _safe_public_url(value: str | None, fallback: str) -> str:
    parsed = urlsplit(value or "")
    return (
        str(value)
        if parsed.scheme in {"http", "https"}
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        else fallback
    )


def _csv_bytes(profile_url: str) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("url",))
    writer.writerow((profile_url,))
    return output.getvalue().encode("utf-8")


class ExaEmailProvider:
    source_key = EXA_WEBSETS_SOURCE_KEY

    def __init__(self, *, api_key: SecretStr | None, poll_after_s: int) -> None:
        self._api_key = api_key
        self._poll_after = timedelta(seconds=poll_after_s)

    @property
    def available(self) -> bool:
        return self._api_key is not None

    def request_json(self, target: EmailLookupTarget) -> dict[str, JsonValue]:
        return {
            "providerContract": EXA_WEBSETS_CONTRACT_VERSION,
            "profileUrl": target.linkedin_url,
            "fieldKey": _FIELD_KEY,
            "format": "email",
        }

    async def start(self, target: EmailLookupTarget, *, external_id: str) -> ProviderProgress:
        if self._api_key is None:
            raise RuntimeError("Exa email provider is not configured")
        csv_content = _csv_bytes(target.linkedin_url)
        import_request = ExaCreateImportRequest(
            size=len(csv_content),
            count=1,
            entity=ExaWebsetEntity(type=ExaWebsetEntityType.PERSON),
            title="Clue contact email lookup",
            metadata={"clueOperation": external_id},
        )
        async with ExaWebsetsClient(
            api_key=self._api_key,
            observe=provider_observer("exa_websets", workspace_id=target.workspace_id),
        ) as client:
            imported = await client.create_import(import_request)
            await client.upload_import_csv(
                upload_url=imported.response.upload_url, content=csv_content
            )
            created = await client.create_webset(
                ExaCreateWebsetRequest(
                    imports=(
                        ExaCreateImportRef(
                            source="import", id=imported.response.id, evaluate=False
                        ),
                    ),
                    title="Clue contact email lookup",
                    enrichments=(
                        ExaCreateEnrichment(
                            description=(
                                "Return only this exact person's professional work email."
                            ),
                            format=ExaWebsetEnrichmentFormat.EMAIL,
                            metadata={"clueFieldKey": _FIELD_KEY},
                        ),
                    ),
                    external_id=external_id,
                    metadata={"clueContract": _CONTRACT_VERSION},
                )
            )
        return ProviderProgress(
            state=ProviderState.WAITING_EXTERNAL,
            provider_import_id=imported.response.id,
            provider_operation_id=created.webset.id,
            next_poll_at=datetime.now(UTC) + self._poll_after,
            artifacts=(
                ProviderArtifact(
                    kind="import_created",
                    content=imported.response.sanitized_bytes(),
                    source_url=f"{EXA_WEBSETS_API_BASE}/imports/{imported.response.id}",
                    request_id=imported.request_id,
                ),
                ProviderArtifact(
                    kind="webset_created",
                    content=created.response_body,
                    source_url=f"{EXA_WEBSETS_API_BASE}/websets/{created.webset.id}",
                    request_id=created.request_id,
                ),
            ),
        )

    async def poll(self, target: EmailLookupTarget, attempt: ProviderAttempt) -> ProviderProgress:
        if self._api_key is None or attempt.provider_operation_id is None:
            raise RuntimeError("Exa email operation cannot be polled")
        async with ExaWebsetsClient(
            api_key=self._api_key,
            observe=provider_observer("exa_websets", workspace_id=target.workspace_id),
        ) as client:
            exchange = await client.poll_webset(attempt.provider_operation_id)
            artifacts: list[ProviderArtifact] = [
                ProviderArtifact(
                    kind="webset_poll",
                    content=exchange.response_body,
                    source_url=(f"{EXA_WEBSETS_API_BASE}/websets/{attempt.provider_operation_id}"),
                    request_id=exchange.request_id,
                )
            ]
            if exchange.webset.status is not ExaWebsetStatus.IDLE:
                return ProviderProgress(
                    state=ProviderState.WAITING_EXTERNAL,
                    provider_import_id=attempt.provider_import_id,
                    provider_operation_id=attempt.provider_operation_id,
                    next_poll_at=datetime.now(UTC) + self._poll_after,
                    artifacts=tuple(artifacts),
                )
            imported = next(
                (item for item in exchange.webset.imports if item.id == attempt.provider_import_id),
                None,
            )
            if imported is None or imported.status is not ExaImportStatus.COMPLETED:
                raise ExaWebsetsContractDrift("email lookup import is not complete at idle")
            enrichments = [
                item
                for item in exchange.webset.enrichments
                if item.format is ExaWebsetEnrichmentFormat.EMAIL
                and item.metadata.get("clueFieldKey") == _FIELD_KEY
            ]
            if len(enrichments) != 1 or enrichments[0].status != "completed":
                raise ExaWebsetsContractDrift("email enrichment terminal shape changed")
            items: list[ExaWebsetItem] = []
            cursor: str | None = None
            for _ in range(10):
                page = await client.list_items(
                    attempt.provider_operation_id, cursor=cursor, limit=100
                )
                artifacts.append(
                    ProviderArtifact(
                        kind="items_page",
                        content=page.response_body,
                        source_url=(
                            f"{EXA_WEBSETS_API_BASE}/websets/{attempt.provider_operation_id}/items"
                        ),
                        request_id=page.request_id,
                    )
                )
                items.extend(page.page.data)
                cursor = page.page.next_cursor
                if cursor is None:
                    break
            else:
                raise ExaWebsetsContractDrift("email item pagination exceeded the cap")
        if len(items) != 1:
            raise ExaWebsetsContractDrift("email lookup returned other than one imported person")
        item = items[0]
        if (
            item.source != "import"
            or item.source_id != attempt.provider_import_id
            or item.webset_id != attempt.provider_operation_id
            or item.properties.type != "person"
            or _normalized_profile(item.source_entity_id or "")
            != _normalized_profile(target.linkedin_url)
        ):
            raise ExaWebsetsContractDrift("email lookup crossed the imported person")
        results = [
            result
            for result in item.enrichment_results
            if result.enrichment_id == enrichments[0].id
        ]
        if len(results) != 1 or results[0].status != "completed":
            raise ExaWebsetsContractDrift("email lookup item lacks its enrichment result")
        result = results[0]
        if result.format is not ExaWebsetEnrichmentFormat.EMAIL:
            raise ExaWebsetsContractDrift("email lookup format changed")
        if result.result is not None and len(result.result) != 1:
            raise ExaWebsetsContractDrift("email lookup returned multiple Exa values")
        email = None if result.result is None else _normalize_email(result.result[0])
        item_bytes = _canonical_json(item.model_dump(mode="json", by_alias=True))
        artifacts.append(
            ProviderArtifact(
                kind="person_result",
                content=item_bytes,
                source_url=target.linkedin_url,
            )
        )
        units = DEFAULT_EXA_WEBSETS_PRICING.realized_units(
            matching_search_results=0,
            ordinary_enrichment_rows=0,
            contact_values=int(email is not None),
            resolved_import_results=1,
        ).total_units
        references = tuple(reference.url for reference in result.references)
        return ProviderProgress(
            state=ProviderState.AVAILABLE if email is not None else ProviderState.NO_RESULT,
            provider_import_id=attempt.provider_import_id,
            provider_operation_id=attempt.provider_operation_id,
            email=email,
            source_url=_safe_public_url(references[0] if references else None, target.linkedin_url),
            observed_at=item.updated_at,
            credits_used=units,
            cost_cents=DEFAULT_EXA_WEBSETS_PRICING.monetary_value(units),
            artifacts=tuple(artifacts),
        )


class SumbleEmailProvider:
    source_key = PEOPLE_SOURCE_KEY

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        cents_per_credit: Decimal,
        poll_after_s: int,
        transport: SumbleEmailTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._cents_per_credit = cents_per_credit
        self._poll_after = timedelta(seconds=poll_after_s)
        self._transport = transport

    @property
    def available(self) -> bool:
        return self._transport is not None or self._api_key is not None

    def request_json(self, target: EmailLookupTarget) -> dict[str, JsonValue]:
        body, maximum = people_email_match_request(target.linkedin_url)
        return {"providerContract": "sumble-v9-people-email", "maximumCredits": maximum, **body}

    def _client(self) -> SumbleEmailTransport:
        if self._transport is not None:
            return self._transport
        if self._api_key is None:
            raise RuntimeError("Sumble email provider is not configured")
        return SumbleV9CommitteeClient(api_key=self._api_key)

    async def start(self, target: EmailLookupTarget, *, external_id: str) -> ProviderProgress:
        del external_id
        response, payload = await asyncio.to_thread(
            self._client().submit_email,
            target.linkedin_url,
            maximum_credits=PEOPLE_EMAIL_REVEAL_MAX_CREDITS,
        )
        return self._progress(target, response=response, payload=payload)

    async def poll(self, target: EmailLookupTarget, attempt: ProviderAttempt) -> ProviderProgress:
        if attempt.provider_operation_id is None:
            raise RuntimeError("Sumble email operation cannot be polled")
        response, payload = await asyncio.to_thread(
            self._client().poll_email,
            attempt.provider_operation_id,
            maximum_credits=PEOPLE_EMAIL_REVEAL_MAX_CREDITS,
        )
        require_matching_people_request_id(response, attempt.provider_operation_id)
        return self._progress(target, response=response, payload=payload)

    def _progress(
        self,
        target: EmailLookupTarget,
        *,
        response: Any,
        payload: Mapping[str, Any],
    ) -> ProviderProgress:
        artifact = ProviderArtifact(
            kind="people_response",
            content=_canonical_json(payload),
            source_url=f"{SUMBLE_API_BASE}/people",
            request_id=response.request_id,
        )
        if response.status in {SumblePeopleStatus.PENDING, SumblePeopleStatus.RUNNING}:
            return ProviderProgress(
                state=ProviderState.WAITING_EXTERNAL,
                provider_operation_id=response.request_id,
                next_poll_at=datetime.now(UTC) + self._poll_after,
                artifacts=(artifact,),
            )
        if response.status is SumblePeopleStatus.FAILED:
            return ProviderProgress(
                state=ProviderState.FAILED,
                provider_operation_id=response.request_id,
                failure_code="sumble_provider_failed",
                artifacts=(artifact,),
            )
        email, row = extract_matched_work_email(response, expected_linkedin_url=target.linkedin_url)
        return ProviderProgress(
            state=ProviderState.AVAILABLE if email is not None else ProviderState.NO_RESULT,
            provider_operation_id=response.request_id,
            email=email,
            source_url=_safe_public_url(
                None if row is None else row.sumble_url, target.linkedin_url
            ),
            observed_at=datetime.now(UTC),
            credits_used=Decimal(response.credits_used),
            cost_cents=Decimal(response.credits_used) * self._cents_per_credit,
            artifacts=(artifact,),
        )


#: The ``core.work_email`` verdicts that mean an address is usable (the same two the display
#: policy shows); any other AI Ark verdict is answered as "no email found".
_USABLE_AI_ARK_VERDICTS = frozenset({"verified_smtp", "catch_all_valid"})
_AI_ARK_EXPORT_URL = f"{AI_ARK_BASE_URL}/v1/people/export/single"


class AiArkEmailProvider:
    """AI Ark's single-person export: one synchronous call, answered with the mailbox verdict.

    The same ``/v1/people/export/single`` call the ARV2 research agents make, so a Contacts-table
    lookup and a research job find the same address and grade it the same way. The call's raw
    body and money rows go through the shared provider ledger, stamped to the workspace. There is
    nothing to poll: :meth:`start` always returns a terminal state.
    """

    source_key = AI_ARK_SOURCE_KEY

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        min_gap_s: float,
        conn_factory: ConnFactoryLike = transaction,
        client_factory: Callable[[ProviderCaller], Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self._min_gap_s = min_gap_s
        self._conn_factory = conn_factory
        self._client_factory = client_factory

    @property
    def available(self) -> bool:
        return self._api_key is not None and bool(self._api_key.get_secret_value().strip())

    def request_json(self, target: EmailLookupTarget) -> dict[str, JsonValue]:
        return {"providerContract": "ai-ark-people-export-single", "url": target.linkedin_url}

    def _client(self, caller: ProviderCaller) -> Any:
        if self._client_factory is not None:
            return self._client_factory(caller)
        if not self.available:
            raise RuntimeError("AI Ark email provider is not configured")
        assert self._api_key is not None
        return AiArkClient(caller, self._api_key, min_gap_s=self._min_gap_s)

    async def start(self, target: EmailLookupTarget, *, external_id: str) -> ProviderProgress:
        raw, ledger = BufferedRawSink(), BufferedLedger()
        caller = ProviderCaller(
            transport=HttpxTransport(),
            raw_sink=raw,
            ledger=ledger,
            now=lambda: datetime.now(UTC),
        )
        client = self._client(caller)
        try:
            exported = await asyncio.to_thread(client.export_email, target.linkedin_url)
        except ProviderHalted:
            return ProviderProgress(state=ProviderState.UNAVAILABLE, failure_code="ai_ark_halted")
        except AiArkResponseError as exc:
            return ProviderProgress(
                state=ProviderState.FAILED, failure_code=str(exc).split(":", 1)[0]
            )
        finally:
            # The call's rows are money whatever its outcome (the web-search tool's rule).
            async with self._conn_factory() as conn:
                await drain_provider_calls(
                    conn,
                    raw=raw,
                    ledger=ledger,
                    artifacts=None,
                    stamp=LedgerStamp(workspace_id=target.workspace_id),
                )
        return self._progress(exported, operation_id=external_id)

    async def poll(self, target: EmailLookupTarget, attempt: ProviderAttempt) -> ProviderProgress:
        raise RuntimeError("AI Ark email export is synchronous and is never polled")

    def _progress(self, exported: AiArkEmailExport, *, operation_id: str) -> ProviderProgress:
        cost = exported.cost
        usable = bool(exported.found and exported.address) and (
            exported.verdict in _USABLE_AI_ARK_VERDICTS
        )
        artifact = ProviderArtifact(
            kind="people_export",
            content=_canonical_json(
                {
                    "email": dict(exported.raw_email_block),
                    "fullName": exported.full_name,
                    "title": exported.title,
                    "currentCompany": exported.current_company,
                    "linkedinUrl": exported.linkedin_url,
                }
            ),
            source_url=_AI_ARK_EXPORT_URL,
            request_id=None if cost is None else cost.ledger_row_id,
        )
        return ProviderProgress(
            state=ProviderState.AVAILABLE if usable else ProviderState.NO_RESULT,
            provider_operation_id=operation_id,
            email=exported.address if usable else None,
            email_status=exported.verdict if usable else None,
            checked_at=exported.checked_at if usable else None,
            observed_at=datetime.now(UTC),
            credits_used=Decimal(0) if cost is None or cost.credits is None else cost.credits,
            cost_cents=(
                Decimal(0)
                if cost is None or cost.cost_usd is None
                else (cost.cost_usd * 100).quantize(Decimal("0.0001"))
            ),
            artifacts=(artifact,),
        )


async def _load_attempts(
    conn: AsyncConnection, *, workspace_id: str, lookup_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[str, ProviderState, str | None]]]:
    if not lookup_ids:
        return {}
    stmt = text(
        """
        SELECT provider.lookup_id, lookup.contact_id, provider.source_key, provider.state,
               provider.observed_claim_id
        FROM contact_email_lookup_provider provider
        JOIN contact_email_lookup lookup
          ON lookup.id=provider.lookup_id AND lookup.workspace_id=provider.workspace_id
        WHERE provider.workspace_id=:workspace_id AND provider.lookup_id IN :lookup_ids
        ORDER BY provider.lookup_id, provider.source_key
        """
    ).bindparams(bindparam("lookup_ids", expanding=True))
    rows = (
        await conn.execute(stmt, {"workspace_id": workspace_id, "lookup_ids": list(lookup_ids)})
    ).all()
    claim_ids = tuple(
        ClaimId(uuid.UUID(str(claim_id))) for *_, claim_id in rows if claim_id is not None
    )
    live_claims = await claims_by_ids(
        conn,
        claim_ids,
        scope=WorkspaceScope.for_workspace(workspace_id),
    )
    policy = await load_workspace_policy(conn, workspace_id=workspace_id)
    grouped: dict[uuid.UUID, list[tuple[str, ProviderState, str | None]]] = defaultdict(list)
    for lookup_id, contact_id, source_key, state, claim_id in rows:
        provider_state = ProviderState(str(state))
        value: str | None = None
        if claim_id is not None:
            claim = live_claims.get(ClaimId(uuid.UUID(str(claim_id))))
            # The ARV2 display predicate, not C7's: the address this view reports is the one the
            # contact screens render from the same claim, and two predicates over one claim is two
            # answers to "may this person's email be shown" (C7's also demands a STRONG identity
            # binding, which the ARV2 lenient writer does not stamp — so it hid every ARV2 address
            # the screens were happily showing).
            claim_is_currently_displayable = (
                claim is not None
                and claim.entity_id == EntityId(uuid.UUID(str(contact_id)))
                and str(claim.field_key) == _FIELD_KEY
                and claim.source_key == str(source_key)
                and arv2_display_allowed(claim, policy)
            )
            if claim_is_currently_displayable and claim is not None:
                value = _claim_address(claim.value_json)
            elif provider_state is ProviderState.AVAILABLE:
                # Provider history remains immutable, but a policy change, retention expiry or DSAR
                # tombstone must take effect on every read. Never resurrect the historical value
                # merely because the provider-attempt row still points to its original claim.
                provider_state = ProviderState.WITHHELD
        grouped[uuid.UUID(str(lookup_id))].append(
            (
                str(source_key),
                provider_state,
                value,
            )
        )
    return grouped


def reconcile_email_lookup(
    lookup_id: uuid.UUID,
    attempts: Sequence[tuple[str, ProviderState, str | None]],
) -> ContactEmailLookupView:
    grouped: dict[str, list[str]] = defaultdict(list)
    states: list[ProviderState] = []
    for source_key, provider_state, value in attempts:
        states.append(provider_state)
        if provider_state is ProviderState.AVAILABLE and value:
            grouped[_normalize_email(value)].append(source_key)
    emails = tuple(
        EmailResult(
            value=email,
            sources=tuple(
                EmailSource(key=source, label=_PROVIDER_LABELS.get(source, source))
                for source in sorted(sources)
            ),
        )
        for email, sources in sorted(grouped.items())
    )
    if any(not state.terminal for state in states):
        view_state = EmailLookupState.PENDING
        resolution = EmailResolution.PENDING
    elif emails:
        view_state = EmailLookupState.AVAILABLE
        resolution = (
            EmailResolution.CONFLICT
            if len(emails) > 1
            else EmailResolution.MATCHED
            if len(emails[0].sources) > 1
            else EmailResolution.SINGLE_SOURCE
        )
    elif states and all(item is ProviderState.NO_RESULT for item in states):
        view_state = EmailLookupState.NOT_FOUND
        resolution = EmailResolution.NONE
    elif any(item is ProviderState.WITHHELD for item in states):
        view_state = EmailLookupState.WITHHELD
        resolution = EmailResolution.WITHHELD
    elif any(
        item in {ProviderState.FAILED, ProviderState.CONTRACT_ERROR, ProviderState.SPEND_UNKNOWN}
        for item in states
    ):
        view_state = EmailLookupState.FAILED
        resolution = EmailResolution.FAILED
    else:
        view_state = EmailLookupState.UNAVAILABLE
        resolution = EmailResolution.UNAVAILABLE
    return ContactEmailLookupView(
        lookup_id=lookup_id,
        state=view_state,
        resolution=resolution,
        emails=emails,
        retryable=any(item is ProviderState.FAILED for item in states),
    )


async def latest_contact_email_lookups(
    conn: AsyncConnection, *, workspace_id: str, contact_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, ContactEmailLookupView]:
    """Read the newest durable lookup per Contact in one bounded batch."""

    if not contact_ids:
        return {}
    stmt = text(
        """
        SELECT DISTINCT ON (contact_id) id, contact_id
        FROM contact_email_lookup
        WHERE workspace_id=:workspace_id AND contact_id IN :contact_ids
        ORDER BY contact_id, created_at DESC, id DESC
        """
    ).bindparams(bindparam("contact_ids", expanding=True))
    rows = (
        await conn.execute(stmt, {"workspace_id": workspace_id, "contact_ids": list(contact_ids)})
    ).all()
    lookup_by_contact = {
        uuid.UUID(str(contact_id)): uuid.UUID(str(lookup_id)) for lookup_id, contact_id in rows
    }
    attempts = await _load_attempts(
        conn, workspace_id=workspace_id, lookup_ids=tuple(lookup_by_contact.values())
    )
    return {
        contact_id: reconcile_email_lookup(lookup_id, attempts.get(lookup_id, ()))
        for contact_id, lookup_id in lookup_by_contact.items()
    }


async def read_contact_email_lookup(
    conn: AsyncConnection, *, workspace_id: str, lookup_id: uuid.UUID
) -> ContactEmailLookupView | None:
    exists = (
        await conn.execute(
            text("SELECT 1 FROM contact_email_lookup WHERE id=:id AND workspace_id=:workspace_id"),
            {"id": lookup_id, "workspace_id": workspace_id},
        )
    ).scalar_one_or_none()
    if exists is None:
        return None
    attempts = await _load_attempts(conn, workspace_id=workspace_id, lookup_ids=(lookup_id,))
    return reconcile_email_lookup(lookup_id, attempts.get(lookup_id, ()))


class ContactEmailLookupService:
    """Orchestrate exactly-once provider kickoff and replay-safe browser-driven polling."""

    def __init__(
        self,
        *,
        providers: Sequence[ContactEmailProvider],
        storage: StorageBackend,
        conn_factory: ConnFactoryLike = transaction,
        poll_after_s: int = 5,
    ) -> None:
        self._providers = {provider.source_key: provider for provider in providers}
        if not self._providers:
            raise ValueError("contact email lookup requires at least one provider")
        self._storage = storage
        self._conn_factory = conn_factory
        self._poll_after = timedelta(seconds=poll_after_s)

    async def start(
        self, *, target: EmailLookupTarget, requested_by: str
    ) -> ContactEmailLookupView:
        now = datetime.now(UTC)
        observation_window = now.strftime("%Y-%m")
        fingerprint = hashlib.sha256(
            _canonical_json(
                {
                    "contract": _CONTRACT_VERSION,
                    "workspaceId": target.workspace_id,
                    "accountId": str(target.account_id),
                    "contactId": str(target.contact_id),
                    "profileUrl": _normalized_profile(target.linkedin_url),
                    "observationWindow": observation_window,
                    "providers": sorted(self._providers),
                }
            )
        ).hexdigest()
        lookup_id = uuid.uuid5(uuid.NAMESPACE_URL, f"clue:{fingerprint}")
        policy_version: int
        async with self._conn_factory() as conn:
            await load_core_pack(conn)
            await seed_source_manifests(conn)
            policy = await load_workspace_policy(conn, workspace_id=target.workspace_id)
            policy_version = policy.version
            suppressed = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM contact_channel_suppression "
                        "WHERE workspace_id=:workspace_id AND contact_id=:contact_id "
                        "AND channel='email'"
                    ),
                    {
                        "workspace_id": target.workspace_id,
                        "contact_id": target.contact_id,
                    },
                )
            ).scalar_one_or_none()
            if suppressed is not None:
                raise PermissionError("contact email acquisition is suppressed")
            await conn.execute(
                text(
                    """
                    INSERT INTO contact_email_lookup (
                        id, workspace_id, account_id, contact_id, requested_by,
                        observation_window, request_fingerprint, policy_version, target_json
                    ) VALUES (
                        :id, :workspace_id, :account_id, :contact_id, :requested_by,
                        :observation_window, :request_fingerprint, :policy_version,
                        CAST(:target_json AS jsonb)
                    ) ON CONFLICT (workspace_id, contact_id, observation_window) DO NOTHING
                    """
                ),
                {
                    "id": lookup_id,
                    "workspace_id": target.workspace_id,
                    "account_id": target.account_id,
                    "contact_id": target.contact_id,
                    "requested_by": requested_by,
                    "observation_window": observation_window,
                    "request_fingerprint": fingerprint,
                    "policy_version": policy_version,
                    "target_json": _canonical_json(target.model_dump(mode="json")).decode(),
                },
            )
            stored = (
                await conn.execute(
                    text(
                        "SELECT id FROM contact_email_lookup WHERE workspace_id=:workspace_id "
                        "AND contact_id=:contact_id AND observation_window=:observation_window"
                    ),
                    {
                        "workspace_id": target.workspace_id,
                        "contact_id": target.contact_id,
                        "observation_window": observation_window,
                    },
                )
            ).scalar_one()
            lookup_id = uuid.UUID(str(stored))
            for provider in self._providers.values():
                state = ProviderState.PLANNED if provider.available else ProviderState.UNAVAILABLE
                await conn.execute(
                    text(
                        """
                        INSERT INTO contact_email_lookup_provider (
                            lookup_id, workspace_id, source_key, state, request_json, terminal_at,
                            failure_code
                        ) VALUES (
                            :lookup_id, :workspace_id, :source_key, :state,
                            CAST(:request_json AS jsonb), :terminal_at, :failure_code
                        ) ON CONFLICT (lookup_id, source_key) DO NOTHING
                        """
                    ),
                    {
                        "lookup_id": lookup_id,
                        "workspace_id": target.workspace_id,
                        "source_key": provider.source_key,
                        "state": state.value,
                        "request_json": _canonical_json(provider.request_json(target)).decode(),
                        "terminal_at": now if state.terminal else None,
                        "failure_code": "provider_not_configured" if state.terminal else None,
                    },
                )
                if provider.available:
                    # A deterministic provider rejection/poll failure is retryable from the same
                    # UI action. Spend-unknown is deliberately excluded: replaying that kickoff
                    # could double-spend.
                    await conn.execute(
                        text(
                            """
                            UPDATE contact_email_lookup_provider
                            SET state='planned', terminal_at=NULL, failure_code=NULL,
                                next_poll_at=NULL, updated_at=now()
                            WHERE lookup_id=:lookup_id AND source_key=:source_key
                              AND state IN ('failed', 'unavailable')
                            """
                        ),
                        {"lookup_id": lookup_id, "source_key": provider.source_key},
                    )
        await asyncio.gather(
            *(
                self._start_provider(target, lookup_id, provider)
                for provider in self._providers.values()
            )
        )
        async with self._conn_factory() as conn:
            view = await read_contact_email_lookup(
                conn, workspace_id=target.workspace_id, lookup_id=lookup_id
            )
        assert view is not None
        return view

    async def poll(
        self,
        *,
        workspace_id: str,
        account_id: uuid.UUID,
        contact_id: uuid.UUID,
        lookup_id: uuid.UUID,
    ) -> ContactEmailLookupView:
        async with self._conn_factory() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT target_json FROM contact_email_lookup "
                        "WHERE id=:id AND workspace_id=:workspace_id AND account_id=:account_id "
                        "AND contact_id=:contact_id"
                    ),
                    {
                        "id": lookup_id,
                        "workspace_id": workspace_id,
                        "account_id": account_id,
                        "contact_id": contact_id,
                    },
                )
            ).first()
        if row is None:
            raise LookupError("no such contact email lookup")
        target = EmailLookupTarget.model_validate(row[0])
        await asyncio.gather(
            *(
                self._poll_provider(target, lookup_id, provider)
                for provider in self._providers.values()
            )
        )
        async with self._conn_factory() as conn:
            view = await read_contact_email_lookup(
                conn, workspace_id=workspace_id, lookup_id=lookup_id
            )
        assert view is not None
        return view

    async def _start_provider(
        self,
        target: EmailLookupTarget,
        lookup_id: uuid.UUID,
        provider: ContactEmailProvider,
    ) -> None:
        async with self._conn_factory() as conn:
            claimed = (
                await conn.execute(
                    text(
                        """
                        UPDATE contact_email_lookup_provider
                        SET state='submitting', updated_at=now()
                        WHERE lookup_id=:lookup_id AND workspace_id=:workspace_id
                          AND source_key=:source_key AND state='planned'
                        RETURNING 1
                        """
                    ),
                    {
                        "lookup_id": lookup_id,
                        "workspace_id": target.workspace_id,
                        "source_key": provider.source_key,
                    },
                )
            ).scalar_one_or_none()
        if claimed is None:
            return
        try:
            progress = await provider.start(target, external_id=f"clue-email-{lookup_id}")
        except ExaWebsetsPreDispatchError:
            await self._mark_failure(
                target.workspace_id,
                lookup_id,
                provider.source_key,
                state=ProviderState.FAILED,
                code="provider_predispatch_failed",
            )
            return
        except (
            ExaWebsetsAuthenticationError,
            ExaWebsetsPaymentRequired,
            ExaWebsetsPermissionDenied,
        ):
            await self._mark_failure(
                target.workspace_id,
                lookup_id,
                provider.source_key,
                state=ProviderState.UNAVAILABLE,
                code="provider_unavailable",
            )
            return
        except ExaWebsetsInvalidRequest:
            await self._mark_failure(
                target.workspace_id,
                lookup_id,
                provider.source_key,
                state=ProviderState.CONTRACT_ERROR,
                code="provider_contract_error",
            )
            return
        except ProviderResponseError as exc:
            await self._mark_failure(
                target.workspace_id,
                lookup_id,
                provider.source_key,
                state=(
                    ProviderState.UNAVAILABLE
                    if exc.is_deterministic_rejection and exc.status_code in {401, 402, 403}
                    else ProviderState.FAILED
                ),
                code="provider_rejected_request",
            )
            return
        except (ExaWebsetsError, SumbleContractError):
            await self._mark_failure(
                target.workspace_id,
                lookup_id,
                provider.source_key,
                state=ProviderState.SPEND_UNKNOWN,
                code="provider_submit_outcome_unknown",
            )
            return
        except Exception:
            await self._mark_failure(
                target.workspace_id,
                lookup_id,
                provider.source_key,
                state=ProviderState.SPEND_UNKNOWN,
                code="provider_submit_outcome_unknown",
            )
            return
        try:
            await self._persist_progress(target, lookup_id, provider.source_key, progress)
        except Exception:
            # The paid kickoff returned, but its result could not be committed. Never dispatch it
            # again automatically: the provider outcome must be reconciled by operation id.
            await self._mark_failure(
                target.workspace_id,
                lookup_id,
                provider.source_key,
                state=ProviderState.SPEND_UNKNOWN,
                code="provider_result_persistence_failed",
            )

    async def _poll_provider(
        self,
        target: EmailLookupTarget,
        lookup_id: uuid.UUID,
        provider: ContactEmailProvider,
    ) -> None:
        async with self._conn_factory() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        UPDATE contact_email_lookup_provider
                        SET state='polling', updated_at=now()
                        WHERE lookup_id=:lookup_id AND workspace_id=:workspace_id
                          AND source_key=:source_key AND state='waiting_external'
                          AND (next_poll_at IS NULL OR next_poll_at <= now())
                        RETURNING request_json, provider_import_id, provider_operation_id
                        """
                    ),
                    {
                        "lookup_id": lookup_id,
                        "workspace_id": target.workspace_id,
                        "source_key": provider.source_key,
                    },
                )
            ).first()
        if row is None:
            return
        attempt = ProviderAttempt(
            lookup_id=lookup_id,
            workspace_id=target.workspace_id,
            source_key=provider.source_key,
            state=ProviderState.POLLING,
            request_json=dict(row[0]),
            provider_import_id=None if row[1] is None else str(row[1]),
            provider_operation_id=None if row[2] is None else str(row[2]),
        )
        try:
            progress = await provider.poll(target, attempt)
        except (
            ExaWebsetsAuthenticationError,
            ExaWebsetsPaymentRequired,
            ExaWebsetsPermissionDenied,
        ):
            await self._mark_failure(
                target.workspace_id,
                lookup_id,
                provider.source_key,
                state=ProviderState.UNAVAILABLE,
                code="provider_unavailable",
                expected_state=ProviderState.POLLING,
            )
            return
        except ProviderResponseError as exc:
            await self._mark_failure(
                target.workspace_id,
                lookup_id,
                provider.source_key,
                state=(
                    ProviderState.UNAVAILABLE
                    if exc.is_deterministic_rejection and exc.status_code in {401, 402, 403}
                    else ProviderState.CONTRACT_ERROR
                ),
                code="provider_poll_rejected",
                expected_state=ProviderState.POLLING,
            )
            return
        except (ExaWebsetsContractDrift, ExaWebsetsInvalidRequest, SumbleContractError):
            await self._mark_failure(
                target.workspace_id,
                lookup_id,
                provider.source_key,
                state=ProviderState.CONTRACT_ERROR,
                code="provider_contract_error",
                expected_state=ProviderState.POLLING,
            )
            return
        except Exception:
            # Polls are replay-safe for both providers. A transient fault returns to the waiting
            # state; a contract/refusal was handled above so it cannot create a permanent loop.
            await self._return_poll_to_waiting(target, lookup_id, provider.source_key)
            return
        try:
            await self._persist_progress(target, lookup_id, provider.source_key, progress)
        except Exception:
            # Polling is replay-safe. A failed local commit returns the durable attempt to waiting
            # so the response can be fetched and persisted again without a second paid kickoff.
            await self._return_poll_to_waiting(target, lookup_id, provider.source_key)

    async def _persist_progress(
        self,
        target: EmailLookupTarget,
        lookup_id: uuid.UUID,
        source_key: str,
        progress: ProviderProgress,
    ) -> None:
        terminal_at = datetime.now(UTC) if progress.state.terminal else None
        async with self._conn_factory() as conn:
            artifact_keys: list[str] = []
            for artifact in progress.artifacts:
                key = await capture_discovery_artifact(
                    conn,
                    self._storage,
                    workspace_id=target.workspace_id,
                    content=artifact.content,
                    media_type="application/json",
                    source_key=source_key,
                    source_url=artifact.source_url,
                )
                artifact_keys.append(key)
                await conn.execute(
                    text(
                        """
                        INSERT INTO contact_email_lookup_artifact (
                            lookup_id, workspace_id, source_key, artifact_kind, artifact_key,
                            provider_request_id
                        ) VALUES (
                            :lookup_id, :workspace_id, :source_key, :artifact_kind, :artifact_key,
                            :provider_request_id
                        )
                        """
                    ),
                    {
                        "lookup_id": lookup_id,
                        "workspace_id": target.workspace_id,
                        "source_key": source_key,
                        "artifact_kind": artifact.kind,
                        "artifact_key": key,
                        "provider_request_id": artifact.request_id,
                    },
                )
                await bind_discovery_artifact_subject(
                    conn,
                    workspace_id=target.workspace_id,
                    artifact_key_value=key,
                    subject_kind="contact",
                    subject_entity_id=EntityId(target.contact_id),
                    reference_kind="contact_email_lookup_provider",
                    reference_id=str(lookup_id),
                )
            response_artifact_key = artifact_keys[-1] if artifact_keys else None
            observed_claim_id: ClaimId | None = None
            state = progress.state
            if progress.email is not None:
                if response_artifact_key is None or progress.provider_operation_id is None:
                    raise RuntimeError("provider email lacks durable response lineage")
                observed_claim_id, allowed = await self._write_observed_claim(
                    conn,
                    target=target,
                    lookup_id=lookup_id,
                    source_key=source_key,
                    artifact_key=response_artifact_key,
                    provider_operation_id=progress.provider_operation_id,
                    email=progress.email,
                    email_status=progress.email_status,
                    checked_at=progress.checked_at,
                    source_url=progress.source_url or target.linkedin_url,
                    observed_at=progress.observed_at or datetime.now(UTC),
                    cost_cents=progress.cost_cents,
                )
                state = ProviderState.AVAILABLE if allowed else ProviderState.WITHHELD
            await conn.execute(
                text(
                    """
                    UPDATE contact_email_lookup_provider
                    SET state=:state, provider_import_id=:provider_import_id,
                        provider_operation_id=:provider_operation_id,
                        observed_claim_id=:observed_claim_id,
                        response_artifact_key=COALESCE(:response_artifact_key,
                                                       response_artifact_key),
                        credits_used=:credits_used, cost_cents=:cost_cents,
                        next_poll_at=:next_poll_at, failure_code=:failure_code,
                        terminal_at=:terminal_at, updated_at=now()
                    WHERE lookup_id=:lookup_id AND workspace_id=:workspace_id
                      AND source_key=:source_key AND state IN ('submitting', 'polling')
                    """
                ),
                {
                    "lookup_id": lookup_id,
                    "workspace_id": target.workspace_id,
                    "source_key": source_key,
                    "state": state.value,
                    "provider_import_id": progress.provider_import_id,
                    "provider_operation_id": progress.provider_operation_id,
                    "observed_claim_id": observed_claim_id,
                    "response_artifact_key": response_artifact_key,
                    "credits_used": progress.credits_used,
                    "cost_cents": progress.cost_cents,
                    "next_poll_at": progress.next_poll_at,
                    "failure_code": progress.failure_code,
                    "terminal_at": terminal_at if state.terminal else None,
                },
            )

    async def _write_observed_claim(
        self,
        conn: AsyncConnection,
        *,
        target: EmailLookupTarget,
        lookup_id: uuid.UUID,
        source_key: str,
        artifact_key: str,
        provider_operation_id: str,
        email: str,
        email_status: str | None = None,
        checked_at: str | None = None,
        source_url: str,
        observed_at: datetime,
        cost_cents: Decimal,
    ) -> tuple[ClaimId, bool]:
        await record_run_lineage(
            conn,
            run_id=lookup_id,
            workspace_id=target.workspace_id,
            kind="enrichment",
        )
        claim = Claim(
            entity_id=EntityId(target.contact_id),
            entity_type=EntityType.CONTACT,
            field_key=_FIELD_KEY,
            # ARV2 D4-b decision 6: the address travels with the verdict that grades it. AI Ark
            # probes the mailbox and reports its own verdict (``verified_smtp`` /
            # ``catch_all_valid``) and check time; Exa Websets and Sumble return an address and
            # nothing about its deliverability, so their honest verdict is ``unverified``. The
            # claim is still born ``VerificationStatus.UNVERIFIED``: the provider graded the
            # mailbox, the platform did not independently verify it.
            value_json={
                "address": _normalize_email(email),
                "status": email_status or _UNPROBED_STATUS,
                **({"checked_at": checked_at} if checked_at else {}),
            },
            source_url=_safe_public_url(source_url, target.linkedin_url),
            source_key=source_key,
            artifact_key=artifact_key,
            source_operation_ref=str(lookup_id),
            source_snapshot_ref=artifact_key,
            source_request_ref=provider_operation_id,
            provenance_kind=ClaimProvenanceKind.PROVIDER_RETURNED,
            source_tier=2 if source_key == EXA_WEBSETS_SOURCE_KEY else 1,
            extraction_method=ExtractionMethod.API,
            evidence_span=(
                f"{_PROVIDER_LABELS.get(source_key, source_key)} returned one professional email "
                "for the exact LinkedIn-identified Contact lookup."
            ),
            confidence=0.8,
            observed_at=observed_at,
            cost_cents=cost_cents,
            run_id=RunId(lookup_id),
            research_mode=ResearchMode.CONTACT_PROFILING,
            # Strong means the provider response was target-locked to this exact LinkedIn person;
            # it does not mean deliverability or independent verification. The latter remains
            # ``verification_status=unverified`` and the identity spine is never promoted.
            identity_binding=IdentityBinding.STRONG,
            use_class=UseClass.PROFESSIONAL_PUBLIC,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
            workspace_id=target.workspace_id,
            verification_status=VerificationStatus.UNVERIFIED,
        )
        await insert_claim(conn, claim)
        policy = await load_workspace_policy(conn, workspace_id=target.workspace_id)

        @asynccontextmanager
        async def _same_connection() -> Any:
            yield conn

        decision = await UseGateImpl(
            target.workspace_id,
            policy=policy,
            conn_factory=_same_connection,
        ).evaluate(claim)
        regime = STRICT_DEFAULT_REGIME
        current = await current_value(
            conn,
            EntityId(target.contact_id),
            CONTACT_JURISDICTION,
            scope=WorkspaceScope.for_workspace(target.workspace_id),
        )
        if current is not None and isinstance(current.value_json, Mapping):
            raw = current.value_json.get("regime")
            if isinstance(raw, str):
                with suppress(ValueError):
                    regime = Jurisdiction(raw)
        await record_lawful_basis(
            conn,
            claim,
            regime=regime,
            retention=RetentionTtls(),
            third_party_collected=True,
        )
        return claim.id, decision.usable_for_outreach and arv2_display_allowed(claim, policy)

    async def _mark_failure(
        self,
        workspace_id: str,
        lookup_id: uuid.UUID,
        source_key: str,
        *,
        state: ProviderState,
        code: str,
        expected_state: ProviderState = ProviderState.SUBMITTING,
    ) -> None:
        async with self._conn_factory() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE contact_email_lookup_provider
                    SET state=:state, failure_code=:failure_code, terminal_at=now(),
                        next_poll_at=NULL, updated_at=now()
                    WHERE lookup_id=:lookup_id AND workspace_id=:workspace_id
                      AND source_key=:source_key AND state=:expected_state
                    """
                ),
                {
                    "lookup_id": lookup_id,
                    "workspace_id": workspace_id,
                    "source_key": source_key,
                    "state": state.value,
                    "failure_code": code,
                    "expected_state": expected_state.value,
                },
            )

    async def _return_poll_to_waiting(
        self,
        target: EmailLookupTarget,
        lookup_id: uuid.UUID,
        source_key: str,
    ) -> None:
        async with self._conn_factory() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE contact_email_lookup_provider
                    SET state='waiting_external', next_poll_at=:next_poll_at,
                        failure_code='provider_poll_failed', updated_at=now()
                    WHERE lookup_id=:lookup_id AND workspace_id=:workspace_id
                      AND source_key=:source_key AND state='polling'
                    """
                ),
                {
                    "lookup_id": lookup_id,
                    "workspace_id": target.workspace_id,
                    "source_key": source_key,
                    "next_poll_at": datetime.now(UTC) + self._poll_after,
                },
            )


def build_contact_email_lookup_service(
    *,
    ai_ark_api_key: SecretStr | None,
    ai_ark_min_gap_s: float,
    storage: StorageBackend,
    poll_after_s: int,
    conn_factory: ConnFactory = transaction,
) -> ContactEmailLookupService:
    """The Contacts-table lookup, on AI Ark only (founder ruling 2026-09-29)."""
    return ContactEmailLookupService(
        providers=(
            AiArkEmailProvider(
                api_key=ai_ark_api_key, min_gap_s=ai_ark_min_gap_s, conn_factory=conn_factory
            ),
        ),
        storage=storage,
        conn_factory=conn_factory,
        poll_after_s=poll_after_s,
    )


__all__ = [
    "AI_ARK_SOURCE_KEY",
    "AiArkEmailProvider",
    "ContactEmailLookupService",
    "ContactEmailLookupView",
    "EmailLookupState",
    "EmailResolution",
    "EmailLookupTarget",
    "EmailResult",
    "EmailSource",
    "ExaEmailProvider",
    "ProviderArtifact",
    "ProviderProgress",
    "ProviderState",
    "SumbleEmailProvider",
    "build_contact_email_lookup_service",
    "latest_contact_email_lookups",
    "read_contact_email_lookup",
    "reconcile_email_lookup",
]
