"""Durable, coalesced Exa Search Deep acquisition for M8B E1.

This is an API-composition coordinator, not a resolver.  It calls an injected transport outside a
database transaction, then persists the raw response, retained results, grounding normalization,
and one settlement receipt before exposing a ready snapshot reference.  It never writes claims;
E2 owns snapshot-backed materialization and verification.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.exa_contact_compiler import ExaDeepContactAcquisitionPreflight
from clue_config import Secrets
from clue_core import (
    AccountEntity,
    ExternalResearchAcquisitionRequest,
    ExternalResearchOperationState,
    ExternalResearchSnapshotRef,
    ProjectRunId,
    ResearchDirectivePin,
    RetryableResolverError,
)
from clue_research.durable.contact_research_control import (
    ContactResearchOperationStop,
    bind_external_research_contact_authority,
    external_research_operation_stop,
)
from clue_research.durable.discovery import (
    bind_discovery_artifact_subject,
    capture_discovery_artifact,
)
from clue_research.durable.external_research import (
    ExternalResearchDispatchDecision,
    ExternalResearchOperationRow,
    ExternalResearchResultArtifactInput,
    adopt_external_research_snapshot,
    claim_external_research_dispatch,
    complete_external_research_cancelled_after_dispatch,
    complete_external_research_pre_dispatch_failure,
    complete_external_research_success,
    find_external_research_operation,
    find_reusable_external_research_operation,
    mark_external_research_spend_unknown,
    reserve_external_research_operation,
)
from clue_research.resolvers.exa import (
    AUTH_REF,
    DEFAULT_EXA_CONFIG,
    SOURCE_KEY,
    ExaDeepConfig,
    ExaDeepContactNormalization,
    ExaDeepFieldSpec,
    ExaDeepNormalization,
    ExaDeepRequestFailure,
    ExaDeepSearchRequest,
    ExaDeepSearchResponse,
    build_exa_deep_http_request,
    compile_exa_deep_request,
    normalize_exa_contact_deep_snapshot,
    normalize_exa_deep_snapshot,
    parse_exa_deep_response,
)
from clue_research.resolvers.exa.deep_contract import ExaDeepFailureClass
from clue_research.resolvers.http import (
    CredentialError,
    ProviderResponseError,
    get_json,
    resolve_credential,
)
from clue_research.resolvers.live import HttpFetcher
from clue_obs import get_logger
from clue_spend import (
    BufferedLedger,
    BufferedRawSink,
    CallSpec,
    HttpxTransport,
    LedgerStamp,
    ProviderCaller,
    SpendEstimate,
    Transport,
    drain_provider_calls,
)
from clue_spend import HttpRequest as SpendRequest
from clue_storage import StorageBackend, artifact_key, content_address

log = get_logger("clue_api.exa_deep_acquisition")

#: The spend caller the coordinator opens around one threaded dispatch (design 2026-10-31). The
#: HTTP transport reads it, so the request lands on ``provider_call_ledger`` and a refusal opens a
#: provider incident when the coordinator drains — without changing the transport protocol.
_SPEND_CALLER: ContextVar[ProviderCaller | None] = ContextVar(
    "exa_deep_spend_caller", default=None
)


@contextmanager
def spend_caller(caller: ProviderCaller) -> Iterator[ProviderCaller]:
    """Route this context's Exa deep requests through ``caller``."""
    token = _SPEND_CALLER.set(caller)
    try:
        yield caller
    finally:
        _SPEND_CALLER.reset(token)


def _ledgered_fetcher(caller: ProviderCaller) -> HttpFetcher:
    """A :data:`HttpFetcher` that sends through the spend caller and keeps ``get_json``'s fault
    taxonomy: transient statuses and transport errors are retryable, hard 4xx are provider
    errors, a non-JSON body is a provider error."""

    def fetch(
        url: str,
        *,
        source_key: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        method: str = "GET",
        timeout: float = 120.0,
        retries: int = 0,
    ) -> Any:
        from urllib.parse import urlencode

        from clue_research.resolvers.http import (
            PROVIDER_ERROR_BODY_EXCERPT_CHARS,
            classify_status,
        )

        del retries  # the durable operation owns replay; the caller makes exactly one attempt
        target = f"{url}?{urlencode(params)}" if params else url
        request = SpendRequest(
            method=method,
            url=target,
            headers={**(headers or {}), "Content-Type": "application/json"},
            body=None if json_body is None else json.dumps(json_body).encode("utf-8"),
            timeout_s=timeout,
        )
        try:
            response = caller.call(
                CallSpec(
                    provider="exa",
                    operation="research.exa_deep.search",
                    label="exa_deep:search",
                    request=request,
                    estimate=SpendEstimate(),
                    max_attempts=1,
                    binary=False,
                )
            ).response
        except Exception as exc:  # noqa: BLE001 - a transport fault after dispatch is ambiguous
            raise RetryableResolverError(f"{source_key}: transport error for {url}: {exc}") from exc
        body = response.body.decode("utf-8", "replace")
        classify_status(
            response.status,
            source_key=source_key,
            url=url,
            body=body[:PROVIDER_ERROR_BODY_EXCERPT_CHARS],
        )
        try:
            return json.loads(body)
        except ValueError as exc:
            raise ProviderResponseError(f"{source_key}: non-JSON response from {url}: {exc}") from exc

    return fetch


async def dispatch_ledgered(
    transport: ExaDeepAcquisitionTransport,
    request: ExaDeepSearchRequest,
    *,
    conn_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]],
    workspace_id: str,
    spend_transport: Transport | None = None,
) -> Mapping[str, Any]:
    """Run one threaded dispatch inside a spend caller and drain its rows afterwards.

    The drain records a provider incident when Exa refused. It never changes the dispatch's own
    outcome: a drain that fails is logged and dropped.
    """
    raw, ledger = BufferedRawSink(), BufferedLedger()
    caller = ProviderCaller(
        transport=spend_transport or HttpxTransport(),
        raw_sink=raw,
        ledger=ledger,
        now=lambda: datetime.now(UTC),
    )
    with spend_caller(caller):
        try:
            return await asyncio.to_thread(transport.search, request)
        finally:
            try:
                async with conn_factory() as conn:
                    await drain_provider_calls(
                        conn,
                        raw=raw,
                        ledger=ledger,
                        artifacts=None,
                        stamp=LedgerStamp(workspace_id=workspace_id),
                    )
            except Exception:
                log.exception("provider_incident.recorder_failed", provider="exa", reason="drain")


class ExaDeepAcquisitionTransport(Protocol):
    """One attempt, zero implicit retries; the coordinator owns replay and spend ambiguity."""

    def search(self, request: ExaDeepSearchRequest) -> Mapping[str, Any]: ...


class ExaDeepHttpAcquisitionTransport:
    """Real E1 HTTP boundary, still dormant until the API composition root injects it.

    Credential resolution and request construction happen before dispatch. The HTTP wrapper gets
    zero retries because the durable operation owns retry/replay decisions; any ambiguous transport
    or response condition is converted into the typed E0 failure contract.
    """

    def __init__(
        self,
        *,
        config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
        secrets: Secrets | None = None,
        http: HttpFetcher | None = None,
    ) -> None:
        self._config = config
        self._secrets = secrets
        self._http = http

    def search(self, request: ExaDeepSearchRequest) -> Mapping[str, Any]:
        try:
            token = resolve_credential(AUTH_REF, source_key=SOURCE_KEY, secrets=self._secrets)
            wire = build_exa_deep_http_request(request, token, config=self._config)
        except (CredentialError, ValueError) as exc:
            raise ExaDeepRequestFailure(
                f"{SOURCE_KEY}: request rejected before dispatch: {exc}",
                failure_class=ExaDeepFailureClass.HARD,
                dispatched=False,
            ) from exc
        if self._http is not None:
            http = self._http
        else:
            caller = _SPEND_CALLER.get()
            http = get_json if caller is None else _ledgered_fetcher(caller)
        try:
            payload = http(
                wire.url,
                source_key=SOURCE_KEY,
                method=wire.method,
                headers=wire.headers,
                params=wire.params,
                json_body=wire.json_body,
                timeout=self._config.timeout_s,
                retries=0,
            )
        except RetryableResolverError as exc:
            raise ExaDeepRequestFailure(
                f"{SOURCE_KEY}: ambiguous transport failure after dispatch: {exc}",
                failure_class=ExaDeepFailureClass.SPEND_UNKNOWN,
                dispatched=True,
            ) from exc
        except ProviderResponseError as exc:
            failure_class = (
                ExaDeepFailureClass.BUDGET
                if exc.status_code == 402
                else (
                    ExaDeepFailureClass.HARD
                    if exc.status_code in {400, 401, 403, 404}
                    else ExaDeepFailureClass.SPEND_UNKNOWN
                )
            )
            raise ExaDeepRequestFailure(
                f"{SOURCE_KEY}: provider response failure after dispatch: {exc}",
                failure_class=failure_class,
                dispatched=True,
                status_code=exc.status_code,
            ) from exc
        if not isinstance(payload, Mapping):
            raise ExaDeepRequestFailure(
                f"{SOURCE_KEY}: non-object success response",
                failure_class=ExaDeepFailureClass.SPEND_UNKNOWN,
                dispatched=True,
            )
        return payload


class ExaDeepAcquisitionOutcome(StrEnum):
    READY = "ready"
    REPLAYED = "replayed"
    JOINED_IN_FLIGHT = "joined_in_flight"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"


class ExaDeepAcquisitionPreflight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request: ExternalResearchAcquisitionRequest
    exa_request: ExaDeepSearchRequest
    exa_config: ExaDeepConfig = DEFAULT_EXA_CONFIG


ExaDeepAnyAcquisitionPreflight = ExaDeepAcquisitionPreflight | ExaDeepContactAcquisitionPreflight
ExaDeepAnyNormalization = ExaDeepNormalization | ExaDeepContactNormalization
ExaDeepBeforeDispatch = Callable[[ExternalResearchOperationRow], Awaitable[None]]


class ExaDeepAcquisitionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: ExaDeepAcquisitionOutcome
    operation: ExternalResearchOperationRow
    snapshot: ExternalResearchSnapshotRef | None = None
    retry_after: datetime | None = None
    provider_calls: int = Field(default=0, ge=0)


class ExaDeepAcquisitionBundlePlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bundles: tuple[ExaDeepAcquisitionPreflight, ...]

    @property
    def field_count(self) -> int:
        count = 0
        for bundle in self.bundles:
            properties = bundle.exa_request.output_schema.get("properties")
            if not isinstance(properties, dict):  # defended by request validation
                raise ValueError("Exa output schema properties must be an object")
            count += len(properties)
        return count


class ExaDeepAcquisitionCoordinator:
    """Own the reserve → dispatch → immutable snapshot/receipt lifecycle."""

    def __init__(
        self,
        *,
        transport: ExaDeepAcquisitionTransport,
        storage: StorageBackend,
        conn_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]],
        dispatch_lease_seconds: int = 120,
        clock: Callable[[], datetime] | None = None,
        enforce_budget: bool = True,
    ) -> None:
        if dispatch_lease_seconds < 1:
            raise ValueError("dispatch lease must be positive")
        self._transport = transport
        self._storage = storage
        self._conn_factory = conn_factory
        self._lease = timedelta(seconds=dispatch_lease_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        # FI pilot budget-controls: threaded from ``Settings.budget_controls_enabled`` at
        # the composition root and passed to the durable reservation, which stops raising
        # on the project-run cap while writing every ledger row unchanged.
        self._enforce_budget = enforce_budget

    async def acquire(
        self,
        preflight: ExaDeepAnyAcquisitionPreflight,
        *,
        before_dispatch: ExaDeepBeforeDispatch | None = None,
    ) -> ExaDeepAcquisitionResult:
        operation, created = await self._reserve(preflight)
        if operation.state is ExternalResearchOperationState.SPEND_OUTCOME_UNKNOWN:
            recovered = await self._recover_retained_success(preflight, operation)
            if recovered is not None:
                return recovered
        terminal = await self._terminal_result(
            operation, request=preflight.request, replay=not created
        )
        if terminal is not None:
            return terminal
        # R4 binds the durable agent-tool cause here: after the provider operation exists, but
        # before the dispatch attempt can be claimed.  A callback failure leaves the operation
        # planned and proves that no provider traffic escaped an incomplete causation journal.
        if before_dispatch is not None:
            await before_dispatch(operation)
        now = self._clock()
        async with self._conn_factory() as conn:
            claim = await claim_external_research_dispatch(
                conn,
                workspace_id=operation.workspace_id,
                operation_id=operation.operation_id,
                now=now,
                lease_expires_at=now + self._lease,
            )
        if claim.decision is ExternalResearchDispatchDecision.READY:
            return await self._terminal_result(  # type: ignore[return-value]
                claim.operation, request=preflight.request, replay=True
            )
        if claim.decision is ExternalResearchDispatchDecision.JOIN_ACTIVE:
            return ExaDeepAcquisitionResult(
                outcome=ExaDeepAcquisitionOutcome.JOINED_IN_FLIGHT,
                operation=claim.operation,
                retry_after=claim.operation.dispatch_lease_expires_at,
            )
        if claim.decision in {
            ExternalResearchDispatchDecision.TERMINAL,
            ExternalResearchDispatchDecision.QUARANTINED_STALE_DISPATCH,
        }:
            return await self._terminal_result(  # type: ignore[return-value]
                claim.operation, request=preflight.request, replay=True
            )
        assert claim.attempt_ordinal is not None
        try:
            payload = await dispatch_ledgered(
                self._transport,
                preflight.exa_request,
                conn_factory=self._conn_factory,
                workspace_id=operation.workspace_id,
            )
        except ExaDeepRequestFailure as exc:
            definitively_not_charged = not exc.dispatched or (
                exc.failure_class in {ExaDeepFailureClass.HARD, ExaDeepFailureClass.BUDGET}
                and exc.status_code in {400, 401, 402, 403, 404}
            )
            if definitively_not_charged:
                failed = await self._fail_pre_dispatch(
                    claim.operation,
                    claim.attempt_ordinal,
                    failure_code=exc.failure_class.value,
                    failure_detail=str(exc),
                    dispatched=exc.dispatched,
                )
                return ExaDeepAcquisitionResult(
                    outcome=ExaDeepAcquisitionOutcome.FAILED_TERMINAL,
                    operation=failed,
                    provider_calls=int(exc.dispatched),
                )
            unknown = await self._mark_unknown(
                claim.operation,
                failure_code=exc.failure_class.value,
                failure_detail=str(exc),
            )
            return ExaDeepAcquisitionResult(
                outcome=ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                provider_calls=1,
            )
        except Exception as exc:
            unknown = await self._mark_unknown(
                claim.operation,
                failure_code=ExaDeepFailureClass.SPEND_UNKNOWN.value,
                failure_detail=f"unexpected Exa transport failure after dispatch: {exc}",
            )
            return ExaDeepAcquisitionResult(
                outcome=ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                provider_calls=1,
            )
        except BaseException:
            # A process-level crash deliberately leaves the dispatch lease in place. A concurrent
            # caller joins it; recovery after lease expiry quarantines the operation. Re-raise so
            # cancellation/termination semantics are never converted into an application result.
            raise
        if not isinstance(payload, Mapping):
            unknown = await self._mark_unknown(
                claim.operation,
                failure_code=ExaDeepFailureClass.SPEND_UNKNOWN.value,
                failure_detail="Exa returned a non-object response after dispatch",
            )
            return ExaDeepAcquisitionResult(
                outcome=ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                provider_calls=1,
            )
        stop = await self._stop(claim.operation)
        if stop is not None:
            try:
                response = parse_exa_deep_response(preflight.exa_request, payload)
                normalization = _normalize_preflight(preflight, response)
            except Exception as exc:
                unknown = await self._mark_unknown(
                    claim.operation,
                    failure_code="stopped_response_cost_unknown",
                    failure_detail=f"stopped Exa response could not be settled: {exc}",
                    provider_request_id=(
                        str(payload.get("requestId")) if payload.get("requestId") else None
                    ),
                )
                return ExaDeepAcquisitionResult(
                    outcome=ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN,
                    operation=unknown,
                    provider_calls=1,
                )
            return await self._settle_stopped(
                claim.operation,
                attempt_ordinal=claim.attempt_ordinal,
                response=response,
                reported_cost=normalization.synthesis.cost_cents,
                reason_code=stop.reason_code,
            )
        response_key: str | None = None
        provider_request_id = payload.get("requestId")
        if not isinstance(provider_request_id, str) or not provider_request_id.strip():
            provider_request_id = None
        try:
            response_key = await self._capture_response(claim.operation, payload)
        except Exception as exc:
            unknown = await self._mark_unknown(
                claim.operation,
                failure_code="response_artifact_persistence_failed",
                failure_detail=f"could not retain dispatched Exa response: {exc}",
                provider_request_id=provider_request_id,
            )
            return ExaDeepAcquisitionResult(
                outcome=ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                provider_calls=1,
            )
        if response_key is None:
            stop = await self._stop(claim.operation)
            if stop is None:  # pragma: no cover - the response fence makes this invariant
                raise RuntimeError("response persistence stopped without durable stop authority")
            try:
                response = parse_exa_deep_response(preflight.exa_request, payload)
                normalization = _normalize_preflight(preflight, response)
            except Exception as exc:
                unknown = await self._mark_unknown(
                    claim.operation,
                    failure_code="stopped_response_cost_unknown",
                    failure_detail=f"stopped Exa response could not be settled: {exc}",
                    provider_request_id=provider_request_id,
                )
                return ExaDeepAcquisitionResult(
                    outcome=ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN,
                    operation=unknown,
                    provider_calls=1,
                )
            return await self._settle_stopped(
                claim.operation,
                attempt_ordinal=claim.attempt_ordinal,
                response=response,
                reported_cost=normalization.synthesis.cost_cents,
                reason_code=stop.reason_code,
            )
        try:
            response = parse_exa_deep_response(preflight.exa_request, payload)
            normalization = _normalize_preflight(preflight, response)
        except Exception as exc:
            unknown = await self._mark_unknown(
                claim.operation,
                failure_code=ExaDeepFailureClass.SPEND_UNKNOWN.value,
                failure_detail=f"unsettleable Exa success response: {exc}",
                response_artifact_key=response_key,
                provider_request_id=provider_request_id,
            )
            return ExaDeepAcquisitionResult(
                outcome=ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                provider_calls=1,
            )
        try:
            return await self._persist_success(
                preflight,
                claim.operation,
                claim.attempt_ordinal,
                response_key,
                response,
                normalization,
            )
        except Exception as exc:
            current = await self._get(claim.operation)
            stop = await self._stop(current)
            if stop is not None and current.state is ExternalResearchOperationState.DISPATCHING:
                return await self._settle_stopped(
                    current,
                    attempt_ordinal=claim.attempt_ordinal,
                    response=response,
                    reported_cost=normalization.synthesis.cost_cents,
                    reason_code=stop.reason_code,
                )
            terminal = await self._terminal_result(current, request=preflight.request, replay=False)
            if terminal is not None and current.state is ExternalResearchOperationState.READY:
                return terminal.model_copy(update={"provider_calls": 1})
            unknown = await self._mark_unknown(
                current,
                failure_code="success_persistence_failed",
                failure_detail=f"could not durably settle dispatched Exa response: {exc}",
                response_artifact_key=response_key,
                provider_request_id=response.request_id,
            )
            return ExaDeepAcquisitionResult(
                outcome=ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                provider_calls=1,
            )

    async def _reserve(
        self, preflight: ExaDeepAnyAcquisitionPreflight
    ) -> tuple[ExternalResearchOperationRow, bool]:
        request_bytes = _json_bytes(_request_artifact(preflight))
        request_key = artifact_key(
            preflight.request.workspace_id,
            content_address(request_bytes),
        )
        async with self._conn_factory() as conn:
            now = self._clock()
            if isinstance(preflight, ExaDeepContactAcquisitionPreflight):
                selection_row = (
                    await conn.execute(
                        text(
                            "SELECT id FROM contact_research_selection "
                            "WHERE workspace_id=:workspace_id AND id=:selection_id FOR UPDATE"
                        ),
                        {
                            "workspace_id": preflight.request.workspace_id,
                            "selection_id": preflight.selection_id,
                        },
                    )
                ).scalar_one_or_none()
                if selection_row is None:
                    raise RuntimeError("selected-contact authority no longer exists")
                exact_operation = await find_external_research_operation(
                    conn,
                    workspace_id=preflight.request.workspace_id,
                    source_key=preflight.request.source_key,
                    request_fingerprint=preflight.request.request_fingerprint,
                    observation_window=preflight.request.observation_window,
                )
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
                            "SELECT EXISTS (SELECT 1 FROM "
                            "contact_research_selection_cancellation "
                            "WHERE selection_id=:selection_id) OR EXISTS (SELECT 1 FROM "
                            "outreach_objected WHERE workspace_id=:workspace_id "
                            "AND contact_entity_id=:contact_id)"
                        ),
                        {
                            "workspace_id": preflight.request.workspace_id,
                            "selection_id": preflight.selection_id,
                            "contact_id": preflight.request.contact_id,
                        },
                    )
                ).scalar_one()
                if blocked:
                    if exact_operation is not None:
                        # A unified stop makes the operation terminal and non-reusable. Return the
                        # exact stopped operation so the public acquisition boundary can report its
                        # normal terminal outcome without dispatching or leaking an internal error.
                        return exact_operation, False
                    raise RuntimeError(
                        "selected-contact authority was cancelled or has a standing objection"
                    )
            reusable = await find_reusable_external_research_operation(
                conn,
                request=preflight.request,
                now=now,
            )
            if reusable is not None:
                if isinstance(preflight, ExaDeepContactAcquisitionPreflight):
                    await bind_external_research_contact_authority(
                        conn,
                        workspace_id=preflight.request.workspace_id,
                        operation_id=reusable.operation_id,
                        selection_id=preflight.selection_id,
                        selection_sha256=preflight.selection_sha256,
                        contact_intent_sha256=preflight.intent_sha256,
                    )
                return reusable, False
            captured_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=preflight.request.workspace_id,
                content=request_bytes,
                media_type="application/json",
                source_key=SOURCE_KEY,
                source_url=None,
            )
            if captured_key != request_key:
                raise RuntimeError("request artifact content address changed during reservation")
            operation, created = await reserve_external_research_operation(
                conn,
                request=preflight.request,
                request_artifact_key=request_key,
                now=now,
                enforce_budget=self._enforce_budget,
            )
            if isinstance(preflight, ExaDeepContactAcquisitionPreflight):
                await bind_external_research_contact_authority(
                    conn,
                    workspace_id=preflight.request.workspace_id,
                    operation_id=operation.operation_id,
                    selection_id=preflight.selection_id,
                    selection_sha256=preflight.selection_sha256,
                    contact_intent_sha256=preflight.intent_sha256,
                )
            if created:
                await _bind_artifact(conn, operation, request_key, "exa_deep_request")
            return operation, created

    async def _persist_success(
        self,
        preflight: ExaDeepAnyAcquisitionPreflight,
        operation: ExternalResearchOperationRow,
        attempt_ordinal: int,
        response_key: str,
        response: ExaDeepSearchResponse,
        normalization: ExaDeepAnyNormalization,
        recover_spend_unknown: bool = False,
    ) -> ExaDeepAcquisitionResult:
        reported_cost = normalization.synthesis.cost_cents
        stop = await self._stop(operation)
        if stop is not None:
            return await self._settle_stopped(
                operation,
                attempt_ordinal=attempt_ordinal,
                response=response,
                reported_cost=reported_cost,
                reason_code=stop.reason_code,
            )
        if reported_cost > operation.cost_cents_reserved:
            unknown = await self._mark_unknown(
                operation,
                failure_code="provider_cost_exceeds_reservation",
                failure_detail="provider-reported cost exceeded the authorized reservation",
                response_artifact_key=response_key,
                provider_request_id=response.request_id,
            )
            return ExaDeepAcquisitionResult(
                outcome=ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=unknown,
                provider_calls=0 if recover_spend_unknown else 1,
            )
        now = self._clock()
        fresh_until = now + timedelta(seconds=preflight.request.freshness_seconds)
        async with self._conn_factory() as conn:
            normalization_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.workspace_id,
                content=_json_bytes(normalization.model_dump(mode="json")),
                media_type="application/json",
                source_key=SOURCE_KEY,
                source_url=None,
            )
            result_refs: list[ExternalResearchResultArtifactInput] = []
            for result in response.results:
                result_key = await capture_discovery_artifact(
                    conn,
                    self._storage,
                    workspace_id=operation.workspace_id,
                    content=_json_bytes(result.model_dump(mode="json")),
                    media_type="application/json",
                    source_key=SOURCE_KEY,
                    source_url=str(result.url),
                )
                result_refs.append(
                    ExternalResearchResultArtifactInput(
                        artifact_key=result_key,
                        source_url=str(result.url),
                        source_title=result.title,
                    )
                )
            receipt_payload = {
                "operation_id": str(operation.operation_id),
                "source_key": operation.source_key,
                "provider_request_id": response.request_id,
                "cost_cents_reserved": str(operation.cost_cents_reserved),
                "provider_reported_cost_cents": str(reported_cost),
                "provider_value_is_estimate": True,
                "reconciliation_state": "pending_provider_billing",
            }
            receipt_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.workspace_id,
                content=_json_bytes(receipt_payload),
                media_type="application/json",
                source_key=SOURCE_KEY,
                source_url=None,
            )
            snapshot = await complete_external_research_success(
                conn,
                workspace_id=operation.workspace_id,
                operation_id=operation.operation_id,
                attempt_ordinal=attempt_ordinal,
                response_artifact_key=response_key,
                normalization_artifact_key=normalization_key,
                provider_request_id=response.request_id,
                provider_reported_cost_cents=reported_cost,
                all_null=normalization.all_null,
                fresh_until=fresh_until,
                result_artifacts=tuple(result_refs),
                receipt_artifact_key=receipt_key,
                now=now,
                recover_spend_unknown=recover_spend_unknown,
                recovery_parser_version=(
                    "exa-deep-unique-alias-recovery-v1" if recover_spend_unknown else None
                ),
                recovery_actor_ref=(
                    "engine:exa-deep-retained-response-recovery" if recover_spend_unknown else None
                ),
            )
            snapshot = await adopt_external_research_snapshot(
                conn,
                request=preflight.request,
                operation_id=operation.operation_id,
                now=now,
            )
            for artifact_key, kind in (
                (response_key, "exa_deep_response"),
                (normalization_key, "exa_deep_normalization"),
                (receipt_key, "exa_deep_receipt"),
            ):
                await _bind_artifact(conn, operation, artifact_key, kind)
            for result_ref in result_refs:
                await _bind_artifact(conn, operation, result_ref.artifact_key, "exa_deep_result")
        ready = await self._get(operation)
        return ExaDeepAcquisitionResult(
            outcome=(
                ExaDeepAcquisitionOutcome.REPLAYED
                if recover_spend_unknown
                else ExaDeepAcquisitionOutcome.READY
            ),
            operation=ready,
            snapshot=snapshot,
            provider_calls=0 if recover_spend_unknown else 1,
        )

    async def _recover_retained_success(
        self,
        preflight: ExaDeepAnyAcquisitionPreflight,
        operation: ExternalResearchOperationRow,
    ) -> ExaDeepAcquisitionResult | None:
        """Re-parse a retained response after a parser/persistence repair, without new spend."""

        if await self._stop(operation) is not None:
            return None
        async with self._conn_factory() as conn:
            attempt = (
                (
                    await conn.execute(
                        text(
                            "SELECT ordinal, response_artifact_key FROM external_research_attempt "
                            "WHERE operation_id=:operation_id AND state='spend_outcome_unknown' "
                            "ORDER BY ordinal DESC LIMIT 1"
                        ),
                        {"operation_id": operation.operation_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if attempt is None or attempt["response_artifact_key"] is None:
            return None
        response_key = str(attempt["response_artifact_key"])
        try:
            raw = json.loads(await self._storage.get(response_key))
            if not isinstance(raw, Mapping):
                return None
            response = parse_exa_deep_response(preflight.exa_request, raw)
            normalization = _normalize_preflight(preflight, response)
            return await self._persist_success(
                preflight,
                operation,
                int(attempt["ordinal"]),
                response_key,
                response,
                normalization,
                recover_spend_unknown=True,
            )
        except Exception:
            # The response remains quarantined and replay remains no-spend. A later code repair or
            # explicit billing reconciliation can still resolve it; never dispatch again here.
            return None

    async def _fail_pre_dispatch(
        self,
        operation: ExternalResearchOperationRow,
        attempt_ordinal: int,
        *,
        failure_code: str,
        failure_detail: str,
        dispatched: bool = False,
    ) -> ExternalResearchOperationRow:
        async with self._conn_factory() as conn:
            return await complete_external_research_pre_dispatch_failure(
                conn,
                workspace_id=operation.workspace_id,
                operation_id=operation.operation_id,
                attempt_ordinal=attempt_ordinal,
                failure_code=failure_code,
                failure_detail=failure_detail,
                now=self._clock(),
                dispatched=dispatched,
            )

    async def _mark_unknown(
        self,
        operation: ExternalResearchOperationRow,
        *,
        failure_code: str,
        failure_detail: str,
        response_artifact_key: str | None = None,
        provider_request_id: str | None = None,
    ) -> ExternalResearchOperationRow:
        async with self._conn_factory() as conn:
            return await mark_external_research_spend_unknown(
                conn,
                workspace_id=operation.workspace_id,
                operation_id=operation.operation_id,
                failure_code=failure_code,
                failure_detail=failure_detail,
                now=self._clock(),
                response_artifact_key=response_artifact_key,
                provider_request_id=provider_request_id,
            )

    async def _capture_response(
        self,
        operation: ExternalResearchOperationRow,
        payload: Mapping[str, Any],
    ) -> str | None:
        from clue_research.durable.external_research import get_external_research_operation

        async with self._conn_factory() as conn:
            # Serialize raw-response retention with cancellation/objection/erasure. If retention
            # wins, a waiting DSAR sees and purges the new artifact; if the stop wins, raw provider
            # data cannot be recreated after that stop commits.
            await get_external_research_operation(
                conn,
                workspace_id=operation.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if (
                await external_research_operation_stop(
                    conn,
                    workspace_id=operation.workspace_id,
                    operation_id=operation.operation_id,
                )
                is not None
            ):
                return None
            key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.workspace_id,
                content=_json_bytes(dict(payload)),
                media_type="application/json",
                source_key=SOURCE_KEY,
                source_url=None,
            )
            await _bind_artifact(conn, operation, key, "exa_deep_response")
            return key

    async def _get(self, operation: ExternalResearchOperationRow) -> ExternalResearchOperationRow:
        from clue_research.durable.external_research import get_external_research_operation

        async with self._conn_factory() as conn:
            return await get_external_research_operation(
                conn,
                workspace_id=operation.workspace_id,
                operation_id=operation.operation_id,
            )

    async def _stop(
        self, operation: ExternalResearchOperationRow
    ) -> ContactResearchOperationStop | None:
        async with self._conn_factory() as conn:
            return await external_research_operation_stop(
                conn,
                workspace_id=operation.workspace_id,
                operation_id=operation.operation_id,
            )

    async def _settle_stopped(
        self,
        operation: ExternalResearchOperationRow,
        *,
        attempt_ordinal: int,
        response: ExaDeepSearchResponse,
        reported_cost: Decimal,
        reason_code: str,
    ) -> ExaDeepAcquisitionResult:
        receipt_payload = {
            "contract": "external-research-stopped-after-dispatch-v1",
            "operation_id": str(operation.operation_id),
            "source_key": operation.source_key,
            "provider_request_id": response.request_id,
            "provider_reported_cost_cents": str(reported_cost),
            "stop_reason": reason_code,
            "contains_provider_result": False,
        }
        async with self._conn_factory() as conn:
            receipt_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.workspace_id,
                content=_json_bytes(receipt_payload),
                media_type="application/json",
                source_key=operation.source_key,
                source_url=None,
            )
            settled = await complete_external_research_cancelled_after_dispatch(
                conn,
                workspace_id=operation.workspace_id,
                operation_id=operation.operation_id,
                attempt_ordinal=attempt_ordinal,
                provider_request_id=response.request_id,
                provider_reported_cost_cents=reported_cost,
                receipt_artifact_key=receipt_key,
                failure_code=reason_code,
                now=self._clock(),
            )
            await _bind_artifact(conn, settled, receipt_key, "exa_deep_stopped_receipt")
        return ExaDeepAcquisitionResult(
            outcome=ExaDeepAcquisitionOutcome.FAILED_TERMINAL,
            operation=settled,
            provider_calls=1,
        )

    async def _terminal_result(
        self,
        operation: ExternalResearchOperationRow,
        *,
        request: ExternalResearchAcquisitionRequest,
        replay: bool,
    ) -> ExaDeepAcquisitionResult | None:
        if await self._stop(operation) is not None:
            return ExaDeepAcquisitionResult(
                outcome=ExaDeepAcquisitionOutcome.FAILED_TERMINAL,
                operation=operation,
            )
        if operation.state is ExternalResearchOperationState.READY:
            async with self._conn_factory() as conn:
                snapshot = await adopt_external_research_snapshot(
                    conn,
                    request=request,
                    operation_id=operation.operation_id,
                    now=self._clock(),
                )
            return ExaDeepAcquisitionResult(
                outcome=(
                    ExaDeepAcquisitionOutcome.REPLAYED
                    if replay
                    else ExaDeepAcquisitionOutcome.READY
                ),
                operation=operation,
                snapshot=snapshot,
            )
        if operation.state is ExternalResearchOperationState.SPEND_OUTCOME_UNKNOWN:
            return ExaDeepAcquisitionResult(
                outcome=ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN,
                operation=operation,
            )
        if operation.state in {
            ExternalResearchOperationState.FAILED_TERMINAL,
            ExternalResearchOperationState.CANCELLED,
        }:
            return ExaDeepAcquisitionResult(
                outcome=ExaDeepAcquisitionOutcome.FAILED_TERMINAL,
                operation=operation,
            )
        return None


def pack_exa_deep_field_bundles(
    account: AccountEntity,
    fields: Sequence[ExaDeepFieldSpec],
    *,
    research_intent: str,
    additional_queries: Sequence[str],
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
) -> tuple[tuple[ExaDeepFieldSpec, ...], ...]:
    """The one definition of how admitted fields split into provider-safe bundles.

    Greedy over the sorted field order: keep adding until ``compile_exa_deep_request`` refuses,
    then start a new bundle. The refusal is *any* schema-shape limit, not just the alias cap —
    ``validate_exa_output_schema`` also caps total **nested** properties, so object-valued rows
    split earlier than a count of aliases predicts.

    Extracted because the budget reservation has to be sized from exactly this rule. Sizing it
    from a `ceil(len(fields) / max-aliases)` estimate under-reserved every object-heavy
    comprehensive account: the plan really compiled four bundles, the reservation covered two, and
    the atomic-reservation guard suspended the job on settlement — deterministic on replay.
    """

    ordered = sorted(fields, key=lambda field: str(field.field_key))
    if not ordered:
        raise ValueError("Exa acquisition requires at least one admitted gap field")
    grouped: list[list[ExaDeepFieldSpec]] = []
    current: list[ExaDeepFieldSpec] = []
    for field in ordered:
        candidate = [*current, field]
        try:
            compile_exa_deep_request(
                account,
                candidate,
                research_intent=research_intent,
                additional_queries=additional_queries,
                config=config,
            )
        except ValueError:
            if not current:
                raise
            grouped.append(current)
            current = [field]
            compile_exa_deep_request(
                account,
                current,
                research_intent=research_intent,
                additional_queries=additional_queries,
                config=config,
            )
        else:
            current = candidate
    grouped.append(current)
    return tuple(tuple(bundle) for bundle in grouped)


def compile_exa_deep_acquisition_plan(
    *,
    workspace_id: str,
    project_id: str,
    project_run_id: ProjectRunId,
    account: AccountEntity,
    icp_key: str,
    icp_version: int,
    research_directive: ResearchDirectivePin,
    fields: Sequence[ExaDeepFieldSpec],
    research_intent: str,
    additional_queries: Sequence[str],
    observation_window: str,
    freshness_policy_ref: str,
    freshness_seconds: int,
    cost_cents_reserved_per_bundle: Decimal,
    entity_research_job_id: UUID | None = None,
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
) -> ExaDeepAcquisitionBundlePlan:
    """Pack admitted fields deterministically under Exa's schema limits.

    Directional questions are attached to every necessary bundle, but never introduce fields.
    Most account profiles fit one bundle; only the documented provider property limit can split it.
    """

    grouped = pack_exa_deep_field_bundles(
        account,
        fields,
        research_intent=research_intent,
        additional_queries=additional_queries,
        config=config,
    )
    preflights: list[ExaDeepAcquisitionPreflight] = []
    for index, bundle in enumerate(grouped):
        wire = compile_exa_deep_request(
            account,
            bundle,
            research_intent=research_intent,
            additional_queries=additional_queries,
            config=config,
        )
        payload = wire.model_dump(mode="json", by_alias=True, exclude_none=True)
        wire_sha = _sha256(_json_bytes(payload))
        reuse_payload = {
            "contract": "exa-search-deep-acquisition-e1-semantic-v1",
            "workspace_id": workspace_id,
            "project_id": project_id,
            "account_id": str(account.id),
            "icp_key": icp_key,
            "icp_version": icp_version,
            "directive": research_directive.model_dump(mode="json"),
            "source_key": SOURCE_KEY,
            "freshness_policy_ref": freshness_policy_ref,
            "freshness_seconds": freshness_seconds,
            "wire_request_sha256": wire_sha,
        }
        reuse_fingerprint = _sha256(_json_bytes(reuse_payload))
        fingerprint_payload = {
            "contract": "exa-search-deep-acquisition-e1-v2",
            "reuse_fingerprint": reuse_fingerprint,
            "project_run_id": str(project_run_id),
            "entity_research_job_id": (
                str(entity_research_job_id) if entity_research_job_id is not None else None
            ),
            "observation_window": observation_window,
            "bundle_index": index,
        }
        fingerprint = _sha256(_json_bytes(fingerprint_payload))
        durable = ExternalResearchAcquisitionRequest(
            workspace_id=workspace_id,
            project_id=project_id,
            project_run_id=project_run_id,
            entity_research_job_id=entity_research_job_id,
            account_id=account.id,
            icp_key=icp_key,
            icp_version=icp_version,
            research_directive=research_directive,
            source_key=SOURCE_KEY,
            observation_window=f"{observation_window}:bundle:{index}",
            freshness_policy_ref=freshness_policy_ref,
            freshness_seconds=freshness_seconds,
            reuse_fingerprint=reuse_fingerprint,
            request_fingerprint=fingerprint,
            wire_request_sha256=wire_sha,
            request_payload=payload,
            cost_cents_reserved=cost_cents_reserved_per_bundle,
        )
        preflights.append(
            ExaDeepAcquisitionPreflight(
                request=durable,
                exa_request=wire,
                exa_config=config,
            )
        )
    return ExaDeepAcquisitionBundlePlan(bundles=tuple(preflights))


async def load_exa_deep_snapshot(
    *,
    storage: StorageBackend,
    snapshot: ExternalResearchSnapshotRef,
) -> tuple[ExaDeepSearchResponse, dict[str, Any]]:
    """Offline-only snapshot loader for E2; it has no provider transport dependency."""

    request_artifact = json.loads(await storage.get(snapshot.request_artifact_key))
    response_payload = json.loads(await storage.get(snapshot.response_artifact_key))
    normalization_payload = json.loads(await storage.get(snapshot.normalization_artifact_key))
    if (
        not isinstance(request_artifact, dict)
        or not isinstance(response_payload, dict)
        or not isinstance(normalization_payload, dict)
    ):
        raise ValueError("stored Exa snapshot artifacts must be JSON objects")
    wire_request = request_artifact.get("wire_request")
    if not isinstance(wire_request, dict):
        raise ValueError("stored Exa request lacks its immutable wire body")
    request = ExaDeepSearchRequest.model_validate(wire_request)
    return parse_exa_deep_response(request, response_payload), normalization_payload


async def _bind_artifact(
    conn: AsyncConnection,
    operation: ExternalResearchOperationRow,
    artifact_key: str,
    reference_kind: str,
) -> None:
    await bind_discovery_artifact_subject(
        conn,
        workspace_id=operation.workspace_id,
        artifact_key_value=artifact_key,
        subject_kind=operation.subject_kind.value,
        subject_entity_id=operation.subject_entity_id,
        reference_kind=reference_kind,
        reference_id=str(operation.operation_id),
    )


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _request_artifact(
    preflight: ExaDeepAnyAcquisitionPreflight,
) -> dict[str, object]:
    """Lossless immutable input needed to validate an offline snapshot.

    Account E1 artifacts retain their accepted shape. Contact C4 adds the exact target lock,
    field-level source authorities, and effective parser policy so a fresh process can recompute
    contact-safe normalization without consulting mutable identity or configuration state.
    """

    artifact: dict[str, object] = {
        "lineage": preflight.request.model_dump(mode="json"),
        "wire_request": preflight.exa_request.model_dump(
            mode="json", by_alias=True, exclude_none=True
        ),
    }
    if isinstance(preflight, ExaDeepContactAcquisitionPreflight):
        artifact.update(
            {
                "contract": "exa-search-contact-deep-acquisition-c4-request-v1",
                "contact_selection_id": str(preflight.selection_id),
                "contact_selection_sha256": preflight.selection_sha256,
                "contact_intent_sha256": preflight.intent_sha256,
                "contact_target_lock": preflight.target_lock.model_dump(mode="json"),
                "field_source_plans": [
                    plan.model_dump(mode="json") for plan in preflight.field_source_plans
                ],
                "exa_config": preflight.exa_config.model_dump(mode="json"),
            }
        )
    return artifact


def _normalize_preflight(
    preflight: ExaDeepAnyAcquisitionPreflight,
    response: ExaDeepSearchResponse,
) -> ExaDeepAnyNormalization:
    if isinstance(preflight, ExaDeepContactAcquisitionPreflight):
        return normalize_exa_contact_deep_snapshot(
            preflight.exa_request,
            response,
            target=preflight.target_lock,
            config=preflight.exa_config,
        )
    return normalize_exa_deep_snapshot(
        preflight.exa_request,
        response,
        config=preflight.exa_config,
    )


__all__ = [
    "ExaDeepAcquisitionBundlePlan",
    "ExaDeepAcquisitionCoordinator",
    "ExaDeepAcquisitionOutcome",
    "ExaDeepAcquisitionPreflight",
    "ExaDeepAcquisitionResult",
    "ExaDeepAcquisitionTransport",
    "ExaDeepBeforeDispatch",
    "ExaDeepHttpAcquisitionTransport",
    "compile_exa_deep_acquisition_plan",
    "load_exa_deep_snapshot",
]
