"""M6A S2B durable Sumble Teams/People committee acquisition.

The coordinator performs provider IO outside database transactions.  It stops at ready immutable
snapshots; S2C owns provider-neutral committee materialization and identity admission.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final, Protocol, cast

from pydantic import BaseModel, ConfigDict

from clue_core import (
    CommitteeAcquisitionAttempt,
    CommitteeAcquisitionOperation,
    CommitteeAcquisitionRequest,
    CommitteeAcquisitionSnapshot,
    CommitteeAcquisitionState,
    CommitteeAttemptKind,
    CommitteeAttemptState,
    CommitteeSnapshotState,
    CommitteeSpendOutcome,
    new_committee_acquisition_operation_id,
)
from clue_db import ConnFactory, transaction
from clue_research.durable import (
    CommitteeAcquisitionNotFound,
    begin_committee_acquisition_attempt,
    bind_discovery_artifact_subject,
    capture_discovery_artifact,
    claim_committee_acquisition_poll,
    claim_committee_acquisition_start,
    find_committee_acquisition_operation,
    get_committee_acquisition_operation,
    get_committee_acquisition_snapshot,
    list_committee_acquisition_attempts,
    list_committee_acquisition_snapshots,
    reserve_committee_acquisition,
    update_committee_acquisition_attempt,
    update_committee_acquisition_operation,
    update_committee_acquisition_snapshot,
)
from clue_research.durable.spend_posture import cap_refusal_is_enforced
from clue_research.resolvers.http import ProviderResponseError
from clue_research.resolvers.sumble import SUMBLE_API_BASE, SUMBLE_API_VERSION
from clue_research.resolvers.sumble.committee_transport import (
    SumbleCommitteeTransport,
    SumbleRawPayload,
    require_matching_people_request_id,
)
from clue_research.resolvers.sumble.people import (
    PEOPLE_SOURCE_KEY,
    SumbleAdvancedQuery,
    SumblePeopleResponse,
    SumblePeopleStatus,
    normalize_people,
    people_search_request,
)
from clue_research.resolvers.sumble.teams import (
    TEAMS_SOURCE_KEY,
    SumbleTeamsResponse,
    normalize_teams,
    teams_search_request,
)
from clue_storage import StorageBackend, read_verified_artifact

SUMBLE_COMMITTEE_CONTRACT_VERSION: Final = (
    "sumble-v9-openapi-c6f1324366a94844932ee3522caee6aa9f428f7d958a9956bea3425d18e2811c"
)
SUMBLE_COMMITTEE_POLICY_VERSION: Final = "sumble-committee-s2b-v1"
SUMBLE_COMMITTEE_PRICING_VERSION: Final = "sumble-v9-credits-2026-08-03"

#: Attribution for the record-only spend-cap posture (founder ruling 2026-08-20; see
#: :mod:`clue_research.durable.spend_posture`).
_SITE_COMMITTEE_PREFLIGHT: Final = "sumble_committee_preflight"


class SumbleCommitteeOutcome(StrEnum):
    READY = "ready"
    REPLAYED = "replayed"
    WAITING_EXTERNAL = "waiting_external"
    JOINED_IN_FLIGHT = "joined_in_flight"
    FAILED_TERMINAL = "failed_terminal"
    SPEND_OUTCOME_UNKNOWN = "spend_outcome_unknown"
    RATE_LIMITED = "rate_limited"


class SumbleCommitteeRateLimited(RuntimeError):
    pass


class CommitteeRateLimiter(Protocol):
    async def acquire(self, source_key: str, *, tokens: int = 1) -> bool: ...


class SumbleCommitteePreflight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request: CommitteeAcquisitionRequest
    teams_body: dict[str, Any]
    people_body: dict[str, Any]
    teams_maximum_credits: int
    people_maximum_credits: int
    maximum_cost_cents: Decimal


class SumbleCommitteeResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: SumbleCommitteeOutcome
    operation: CommitteeAcquisitionOperation
    provider_calls: int = 0


def compile_sumble_committee_preflight(
    request: CommitteeAcquisitionRequest,
    *,
    cents_per_credit: Decimal,
    enforce_budget: bool = True,
) -> SumbleCommitteePreflight:
    """Compile the exact bounded wire plan after the S2 eligibility layer has admitted it.

    ``enforce_budget`` is the FI pilot budget-controls switch (``Settings.budget_controls_enabled``,
    threaded from the composition root). It gates only the two cost comparisons at the end: under
    the 2026-08-20 record-only ruling a wire plan whose bounded maximum exceeds the configured
    credit or money cap is recorded and compiled anyway. Every contract/version/identity check
    above is structural and refuses in both modes.
    """

    if cents_per_credit < 0:
        raise ValueError("Sumble cents per credit must be non-negative")
    if request.provider_api_version != SUMBLE_API_VERSION:
        raise ValueError("committee request is not pinned to Sumble v9")
    if request.provider_contract_version != SUMBLE_COMMITTEE_CONTRACT_VERSION:
        raise ValueError("committee request contract differs from the accepted Sumble schema")
    if request.pricing_policy_version != SUMBLE_COMMITTEE_PRICING_VERSION:
        raise ValueError("committee request pricing policy differs from the accepted policy")
    if request.committee_policy_version != SUMBLE_COMMITTEE_POLICY_VERSION:
        raise ValueError("committee request policy differs from the accepted S2B policy")
    try:
        organization_id = int(request.provider_organization_id)
    except ValueError as exc:
        raise ValueError("Sumble organization id must be an integer") from exc
    advanced = (
        SumbleAdvancedQuery(expression=request.provider_filter_expression)
        if request.provider_filter_expression is not None
        else None
    )
    teams_body, teams_maximum = teams_search_request(
        organization_id,
        limit=request.team_limit,
        max_people_per_team=request.related_people_per_team,
        max_jobs_per_team=request.jobs_per_team,
        advanced_query=advanced,
    )
    people_body, people_maximum = people_search_request(
        organization_id,
        limit=request.people_limit,
        offset=request.people_offset,
        advanced_query=advanced,
    )
    maximum_units = teams_maximum + people_maximum
    maximum_cost = Decimal(maximum_units) * cents_per_credit
    if maximum_units > request.provider_credit_cap and cap_refusal_is_enforced(
        enforce_budget,
        site=_SITE_COMMITTEE_PREFLIGHT,
        reason="wire_plan_above_credit_cap",
        amounts={
            "wire_plan_maximum_units": maximum_units,
            "provider_credit_cap": request.provider_credit_cap,
        },
    ):
        raise ValueError("committee wire plan exceeds its provider credit cap")
    if maximum_cost > request.money_budget_cap_cents and cap_refusal_is_enforced(
        enforce_budget,
        site=_SITE_COMMITTEE_PREFLIGHT,
        reason="wire_plan_above_money_cap",
        amounts={
            "wire_plan_maximum_cost_cents": maximum_cost,
            "money_budget_cap_cents": request.money_budget_cap_cents,
        },
    ):
        raise ValueError("committee wire plan exceeds its money cap")
    return SumbleCommitteePreflight(
        request=request,
        teams_body=teams_body,
        people_body=people_body,
        teams_maximum_credits=teams_maximum,
        people_maximum_credits=people_maximum,
        maximum_cost_cents=maximum_cost,
    )


class SumbleCommitteeAcquisitionCoordinator:
    def __init__(
        self,
        *,
        transport: SumbleCommitteeTransport,
        storage: StorageBackend,
        cents_per_credit: Decimal,
        conn_factory: ConnFactory = transaction,
        poll_after_seconds: int = 15,
        rate_limiter: CommitteeRateLimiter | None = None,
        enforce_budget: bool = True,
    ) -> None:
        if cents_per_credit < 0 or poll_after_seconds < 1:
            raise ValueError("Sumble committee pricing and polling values must be valid")
        self._transport = transport
        self._storage = storage
        self._cents_per_credit = cents_per_credit
        self._conn_factory = conn_factory
        self._poll_after = timedelta(seconds=poll_after_seconds)
        self._rate_limiter = rate_limiter
        # FI pilot budget-controls: threaded from ``Settings.budget_controls_enabled`` at
        # the composition root and passed to the durable reservation, which stops raising
        # on the project-run cap while writing every ledger row unchanged.
        self._enforce_budget = enforce_budget

    async def start(
        self,
        preflight: SumbleCommitteePreflight,
        *,
        before_dispatch: Callable[[CommitteeAcquisitionOperation], Awaitable[None]] | None = None,
    ) -> SumbleCommitteeResult:
        operation, _created = await self._reserve(preflight)
        terminal = self._terminal_result(operation, replay=True)
        if terminal is not None:
            return terminal
        if await self._has_dispatching_attempt(operation):
            return await self._mark_unknown(
                operation, "crash_after_possible_sumble_committee_dispatch"
            )
        if operation.state is not CommitteeAcquisitionState.WAITING_EXTERNAL:
            recovered = await self._recover_persisted_response(operation)
            if recovered is not None:
                return recovered

        if operation.state is CommitteeAcquisitionState.PLANNED:
            async with self._conn_factory() as conn:
                claimed = await claim_committee_acquisition_start(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
            if claimed is None:
                return SumbleCommitteeResult(
                    outcome=SumbleCommitteeOutcome.JOINED_IN_FLIGHT,
                    operation=await self._get(operation),
                )
            operation = claimed

        if operation.state is CommitteeAcquisitionState.WAITING_EXTERNAL:
            if operation.next_poll_at is not None and operation.next_poll_at > datetime.now(UTC):
                return SumbleCommitteeResult(
                    outcome=SumbleCommitteeOutcome.WAITING_EXTERNAL, operation=operation
                )
            async with self._conn_factory() as conn:
                claimed = await claim_committee_acquisition_poll(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                    now=datetime.now(UTC),
                )
            if claimed is None:
                return SumbleCommitteeResult(
                    outcome=SumbleCommitteeOutcome.JOINED_IN_FLIGHT,
                    operation=await self._get(operation),
                )
            operation = claimed

        provider_calls = 0
        if operation.state is CommitteeAcquisitionState.ACQUIRING_TEAMS:
            teams = await self._snapshot(operation, TEAMS_SOURCE_KEY)
            if teams.state is CommitteeSnapshotState.SUCCEEDED:
                operation = await self._set_operation_state(
                    operation, CommitteeAcquisitionState.SUBMITTING_PEOPLE
                )
            else:
                try:
                    if before_dispatch is not None:
                        await before_dispatch(operation)
                    await self._dispatch_teams(operation, preflight)
                    provider_calls += 1
                except SumbleCommitteeRateLimited:
                    return SumbleCommitteeResult(
                        outcome=SumbleCommitteeOutcome.RATE_LIMITED,
                        operation=await self._get(operation),
                        provider_calls=provider_calls,
                    )
                except ProviderResponseError as exc:
                    if exc.is_deterministic_rejection:
                        return await self._mark_provider_rejected(
                            operation,
                            source_key=TEAMS_SOURCE_KEY,
                            error=exc,
                            provider_calls=provider_calls + 1,
                        )
                    return await self._mark_unknown(
                        operation,
                        "sumble_teams_dispatch_or_response_unreconciled",
                        provider_calls=provider_calls + 1,
                    )
                except Exception:
                    return await self._mark_unknown(
                        operation,
                        "sumble_teams_dispatch_or_response_unreconciled",
                        provider_calls=provider_calls + 1,
                    )
                operation = await self._set_operation_state(
                    operation, CommitteeAcquisitionState.SUBMITTING_PEOPLE
                )

        if operation.state is CommitteeAcquisitionState.SUBMITTING_PEOPLE:
            people = await self._snapshot(operation, PEOPLE_SOURCE_KEY)
            if people.state is CommitteeSnapshotState.SUCCEEDED:
                return await self._finish_ready(operation, provider_calls=provider_calls)
            try:
                if before_dispatch is not None:
                    await before_dispatch(operation)
                response = await self._dispatch_people_submit(operation, preflight)
                provider_calls += 1
            except SumbleCommitteeRateLimited:
                return SumbleCommitteeResult(
                    outcome=SumbleCommitteeOutcome.RATE_LIMITED,
                    operation=await self._get(operation),
                    provider_calls=provider_calls,
                )
            except ProviderResponseError as exc:
                if exc.is_deterministic_rejection:
                    return await self._mark_provider_rejected(
                        operation,
                        source_key=PEOPLE_SOURCE_KEY,
                        error=exc,
                        provider_calls=provider_calls + 1,
                    )
                return await self._mark_unknown(
                    operation,
                    "sumble_people_submit_or_response_unreconciled",
                    provider_calls=provider_calls + 1,
                )
            except Exception:
                return await self._mark_unknown(
                    operation,
                    "sumble_people_submit_or_response_unreconciled",
                    provider_calls=provider_calls + 1,
                )
            return await self._after_people_response(
                operation, response, provider_calls=provider_calls
            )

        if operation.state is CommitteeAcquisitionState.POLLING_PEOPLE:
            try:
                if before_dispatch is not None:
                    await before_dispatch(operation)
                response = await self._dispatch_people_poll(operation, preflight)
                provider_calls += 1
            except SumbleCommitteeRateLimited:
                return SumbleCommitteeResult(
                    outcome=SumbleCommitteeOutcome.RATE_LIMITED,
                    operation=await self._get(operation),
                    provider_calls=provider_calls,
                )
            except ProviderResponseError as exc:
                if exc.is_deterministic_rejection:
                    return await self._mark_provider_rejected(
                        operation,
                        source_key=PEOPLE_SOURCE_KEY,
                        error=exc,
                        provider_calls=provider_calls + 1,
                    )
                return await self._mark_unknown(
                    operation,
                    "sumble_people_poll_or_response_unreconciled",
                    provider_calls=provider_calls + 1,
                )
            except Exception:
                return await self._mark_unknown(
                    operation,
                    "sumble_people_poll_or_response_unreconciled",
                    provider_calls=provider_calls + 1,
                )
            return await self._after_people_response(
                operation, response, provider_calls=provider_calls
            )
        fresh = await self._get(operation)
        terminal = self._terminal_result(fresh, replay=False)
        if terminal is not None:
            return terminal
        return SumbleCommitteeResult(
            outcome=SumbleCommitteeOutcome.JOINED_IN_FLIGHT, operation=fresh
        )

    async def _recover_persisted_response(
        self, operation: CommitteeAcquisitionOperation
    ) -> SumbleCommitteeResult | None:
        """Fold a response committed just before a process died updating the operation cursor."""

        async with self._conn_factory() as conn:
            snapshots = await list_committee_acquisition_snapshots(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            attempts = await list_committee_acquisition_attempts(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
        by_source = {item.source_key: item for item in snapshots}
        responded = {
            item.source_key: item
            for item in attempts
            if item.state is CommitteeAttemptState.RESPONDED
        }
        for source_key, snapshot in by_source.items():
            attempt = responded.get(source_key)
            if (
                snapshot.state is not CommitteeSnapshotState.DISPATCHING
                or attempt is None
                or attempt.response_artifact_key is None
            ):
                continue
            try:
                async with self._conn_factory() as conn:
                    _, body = await read_verified_artifact(
                        conn,
                        self._storage,
                        storage_key=attempt.response_artifact_key,
                        workspace_id=operation.request.workspace_id,
                    )
                raw = json.loads(body)
                if not isinstance(raw, dict):
                    raise ValueError("Sumble response artifact must contain a JSON object")
                payload = cast(SumbleRawPayload, raw)
                if source_key == TEAMS_SOURCE_KEY:
                    response: SumbleTeamsResponse | SumblePeopleResponse = (
                        SumbleTeamsResponse.model_validate(payload)
                    )
                    normalize_teams(
                        payload,
                        expected_organization_id=int(operation.request.provider_organization_id),
                        max_people_per_team=operation.request.related_people_per_team,
                        max_jobs_per_team=operation.request.jobs_per_team,
                    )
                else:
                    response = SumblePeopleResponse.model_validate(payload)
                    if attempt.kind is CommitteeAttemptKind.PEOPLE_POLL:
                        current = by_source[PEOPLE_SOURCE_KEY]
                        if current.provider_operation_id is not None:
                            require_matching_people_request_id(
                                response, current.provider_operation_id
                            )
                    if response.status is SumblePeopleStatus.SUCCEEDED:
                        normalize_people(
                            payload,
                            expected_organization_id=int(
                                operation.request.provider_organization_id
                            ),
                        )
                await self._persist_response_snapshot(operation, attempt, response)
            except Exception:
                return await self._mark_unknown(
                    operation,
                    "sumble_committed_response_recovery_failed",
                )

        async with self._conn_factory() as conn:
            snapshots = await list_committee_acquisition_snapshots(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
        by_source = {item.source_key: item for item in snapshots}
        teams = by_source.get(TEAMS_SOURCE_KEY)
        people = by_source.get(PEOPLE_SOURCE_KEY)
        if people is not None and people.state is CommitteeSnapshotState.FAILED_TERMINAL:
            failed = await self._refresh_totals(
                operation,
                state=CommitteeAcquisitionState.FAILED_TERMINAL,
                failure_code=people.failure_code or "sumble_people_terminal_failure",
                terminal_at=datetime.now(UTC),
            )
            return SumbleCommitteeResult(
                outcome=SumbleCommitteeOutcome.FAILED_TERMINAL, operation=failed
            )
        if people is not None and people.state is CommitteeSnapshotState.WAITING_EXTERNAL:
            waiting = await self._refresh_totals(
                operation,
                state=CommitteeAcquisitionState.WAITING_EXTERNAL,
                next_poll_at=datetime.now(UTC) + self._poll_after,
            )
            return SumbleCommitteeResult(
                outcome=SumbleCommitteeOutcome.WAITING_EXTERNAL, operation=waiting
            )
        if (
            teams is not None
            and people is not None
            and teams.state is CommitteeSnapshotState.SUCCEEDED
            and people.state is CommitteeSnapshotState.SUCCEEDED
        ):
            return await self._finish_ready(operation, provider_calls=0)
        return None

    async def _reserve(
        self, preflight: SumbleCommitteePreflight
    ) -> tuple[CommitteeAcquisitionOperation, bool]:
        request = preflight.request
        async with self._conn_factory() as conn:
            existing = await find_committee_acquisition_operation(
                conn,
                workspace_id=request.workspace_id,
                account_id=request.account_id,
                request_fingerprint=request.request_fingerprint,
                observation_window=request.observation_window,
            )
            if existing is not None:
                return existing, False
            input_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=request.workspace_id,
                content=request.canonical_bytes(),
                media_type="application/json",
                source_key=PEOPLE_SOURCE_KEY,
                source_url=SUMBLE_API_BASE,
            )
            teams_key = await self._capture_wire(
                conn, request.workspace_id, TEAMS_SOURCE_KEY, preflight.teams_body
            )
            people_key = await self._capture_wire(
                conn, request.workspace_id, PEOPLE_SOURCE_KEY, preflight.people_body
            )
            operation = CommitteeAcquisitionOperation(
                operation_id=new_committee_acquisition_operation_id(),
                request=request,
                request_fingerprint=request.request_fingerprint,
                state=CommitteeAcquisitionState.PLANNED,
                spend_outcome=CommitteeSpendOutcome.NOT_DISPATCHED,
                input_artifact_key=input_key,
                provider_units_reserved=Decimal(
                    preflight.teams_maximum_credits + preflight.people_maximum_credits
                ),
                cost_cents_reserved=preflight.maximum_cost_cents,
            )
            snapshots = (
                CommitteeAcquisitionSnapshot(
                    operation_id=operation.operation_id,
                    workspace_id=request.workspace_id,
                    account_id=request.account_id,
                    source_key=TEAMS_SOURCE_KEY,
                    request_fingerprint=_wire_fingerprint(
                        request.request_fingerprint, TEAMS_SOURCE_KEY, preflight.teams_body
                    ),
                    state=CommitteeSnapshotState.PLANNED,
                    spend_outcome=CommitteeSpendOutcome.NOT_DISPATCHED,
                    request_artifact_key=teams_key,
                    provider_units_reserved=Decimal(preflight.teams_maximum_credits),
                ),
                CommitteeAcquisitionSnapshot(
                    operation_id=operation.operation_id,
                    workspace_id=request.workspace_id,
                    account_id=request.account_id,
                    source_key=PEOPLE_SOURCE_KEY,
                    request_fingerprint=_wire_fingerprint(
                        request.request_fingerprint, PEOPLE_SOURCE_KEY, preflight.people_body
                    ),
                    state=CommitteeSnapshotState.PLANNED,
                    spend_outcome=CommitteeSpendOutcome.NOT_DISPATCHED,
                    request_artifact_key=people_key,
                    provider_units_reserved=Decimal(preflight.people_maximum_credits),
                ),
            )
            stored, created = await reserve_committee_acquisition(
                conn,
                operation=operation,
                snapshots=snapshots,
                enforce_budget=self._enforce_budget,
            )
            if created:
                for key, kind in (
                    (input_key, "sumble_committee_input"),
                    (teams_key, "sumble_teams_request"),
                    (people_key, "sumble_people_request"),
                ):
                    await self._bind(conn, stored, key, kind)
            return stored, created

    async def _dispatch_teams(
        self, operation: CommitteeAcquisitionOperation, preflight: SumbleCommitteePreflight
    ) -> None:
        await self._require_rate_token()
        snapshot = await self._snapshot(operation, TEAMS_SOURCE_KEY)
        attempt = await self._begin_attempt(
            operation,
            TEAMS_SOURCE_KEY,
            CommitteeAttemptKind.TEAMS_SEARCH,
            snapshot.request_artifact_key,
        )
        response, payload = await asyncio.to_thread(
            self._transport.search_teams,
            preflight.teams_body,
            maximum_credits=preflight.teams_maximum_credits,
        )
        attempt = await self._record_response_attempt(operation, attempt, response, payload)
        normalize_teams(
            payload,
            expected_organization_id=int(operation.request.provider_organization_id),
            max_people_per_team=operation.request.related_people_per_team,
            max_jobs_per_team=operation.request.jobs_per_team,
        )
        await self._persist_response_snapshot(operation, attempt, response)

    async def _dispatch_people_submit(
        self, operation: CommitteeAcquisitionOperation, preflight: SumbleCommitteePreflight
    ) -> SumblePeopleResponse:
        await self._require_rate_token()
        snapshot = await self._snapshot(operation, PEOPLE_SOURCE_KEY)
        attempt = await self._begin_attempt(
            operation,
            PEOPLE_SOURCE_KEY,
            CommitteeAttemptKind.PEOPLE_SUBMIT,
            snapshot.request_artifact_key,
        )
        response, payload = await asyncio.to_thread(
            self._transport.submit_people,
            preflight.people_body,
            maximum_credits=preflight.people_maximum_credits,
        )
        attempt = await self._record_response_attempt(operation, attempt, response, payload)
        if response.status is SumblePeopleStatus.SUCCEEDED:
            normalize_people(
                payload,
                expected_organization_id=int(operation.request.provider_organization_id),
            )
        await self._persist_response_snapshot(operation, attempt, response)
        return response

    async def _dispatch_people_poll(
        self, operation: CommitteeAcquisitionOperation, preflight: SumbleCommitteePreflight
    ) -> SumblePeopleResponse:
        await self._require_rate_token()
        snapshot = await self._snapshot(operation, PEOPLE_SOURCE_KEY)
        if snapshot.provider_operation_id is None:
            raise CommitteeAcquisitionNotFound("People snapshot lacks request id")
        poll_body = {"request_id": snapshot.provider_operation_id}
        async with self._conn_factory() as conn:
            request_key = await self._capture_wire(
                conn, operation.request.workspace_id, PEOPLE_SOURCE_KEY, poll_body
            )
            await self._bind(conn, operation, request_key, "sumble_people_poll_request")
        attempt = await self._begin_attempt(
            operation,
            PEOPLE_SOURCE_KEY,
            CommitteeAttemptKind.PEOPLE_POLL,
            request_key,
        )
        response, payload = await asyncio.to_thread(
            self._transport.poll_people,
            snapshot.provider_operation_id,
            maximum_credits=preflight.people_maximum_credits,
        )
        require_matching_people_request_id(response, snapshot.provider_operation_id)
        attempt = await self._record_response_attempt(operation, attempt, response, payload)
        if response.status is SumblePeopleStatus.SUCCEEDED:
            normalize_people(
                payload,
                expected_organization_id=int(operation.request.provider_organization_id),
            )
        await self._persist_response_snapshot(operation, attempt, response)
        return response

    async def _record_response_attempt(
        self,
        operation: CommitteeAcquisitionOperation,
        attempt: CommitteeAcquisitionAttempt,
        response: SumbleTeamsResponse | SumblePeopleResponse,
        payload: SumbleRawPayload,
    ) -> CommitteeAcquisitionAttempt:
        """Persist raw provider evidence before any row-level normalization can fail."""

        source_key = attempt.source_key
        provider_status = (
            response.status.value if isinstance(response, SumblePeopleResponse) else "succeeded"
        )
        provider_id = (
            response.request_id if isinstance(response, SumblePeopleResponse) else response.id
        )
        async with self._conn_factory() as conn:
            response_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=_json_bytes(payload),
                media_type="application/json",
                source_key=source_key,
                source_url=_source_url(source_key),
            )
            await self._bind(
                conn,
                operation,
                response_key,
                "sumble_teams_response"
                if source_key == TEAMS_SOURCE_KEY
                else "sumble_people_response",
            )
            return await update_committee_acquisition_attempt(
                conn,
                attempt=attempt.model_copy(
                    update={
                        "state": CommitteeAttemptState.RESPONDED,
                        "response_artifact_key": response_key,
                        "provider_operation_id": provider_id,
                        "provider_status": provider_status,
                        "provider_units_charged": Decimal(response.credits_used),
                        "credits_remaining": response.credits_remaining,
                        "completed_at": datetime.now(UTC),
                    }
                ),
            )

    async def _persist_response_snapshot(
        self,
        operation: CommitteeAcquisitionOperation,
        attempt: CommitteeAcquisitionAttempt,
        response: SumbleTeamsResponse | SumblePeopleResponse,
    ) -> None:
        """Fold one already-recorded response into its mutable operation snapshot."""

        if attempt.response_artifact_key is None:
            raise CommitteeAcquisitionNotFound("committee response artifact")
        provider_status = (
            response.status.value if isinstance(response, SumblePeopleResponse) else "succeeded"
        )
        state = (
            CommitteeSnapshotState.SUCCEEDED
            if provider_status == "succeeded"
            else (
                CommitteeSnapshotState.FAILED_TERMINAL
                if provider_status == "failed"
                else CommitteeSnapshotState.WAITING_EXTERNAL
            )
        )
        spend = (
            CommitteeSpendOutcome.CHARGED
            if attempt.provider_units_charged
            else CommitteeSpendOutcome.NOT_CHARGED
        )
        async with self._conn_factory() as conn:
            current = await get_committee_acquisition_snapshot(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                source_key=attempt.source_key,
                for_update=True,
            )
            if current is None:
                raise CommitteeAcquisitionNotFound("committee response snapshot")
            await update_committee_acquisition_snapshot(
                conn,
                snapshot=current.model_copy(
                    update={
                        "state": state,
                        "spend_outcome": spend,
                        "response_artifact_key": attempt.response_artifact_key,
                        "provider_operation_id": attempt.provider_operation_id,
                        "provider_status": provider_status,
                        "provider_units_charged": attempt.provider_units_charged,
                        "credits_remaining": attempt.credits_remaining,
                        "cost_cents_charged": attempt.provider_units_charged
                        * self._cents_per_credit,
                        "failure_code": (
                            "sumble_people_terminal_failure"
                            if provider_status == "failed"
                            else None
                        ),
                    }
                ),
            )

    async def _after_people_response(
        self,
        operation: CommitteeAcquisitionOperation,
        response: SumblePeopleResponse,
        *,
        provider_calls: int,
    ) -> SumbleCommitteeResult:
        if response.status in {SumblePeopleStatus.PENDING, SumblePeopleStatus.RUNNING}:
            operation = await self._refresh_totals(
                operation,
                state=CommitteeAcquisitionState.WAITING_EXTERNAL,
                next_poll_at=datetime.now(UTC) + self._poll_after,
            )
            return SumbleCommitteeResult(
                outcome=SumbleCommitteeOutcome.WAITING_EXTERNAL,
                operation=operation,
                provider_calls=provider_calls,
            )
        if response.status is SumblePeopleStatus.FAILED:
            operation = await self._refresh_totals(
                operation,
                state=CommitteeAcquisitionState.FAILED_TERMINAL,
                failure_code="sumble_people_terminal_failure",
                terminal_at=datetime.now(UTC),
            )
            return SumbleCommitteeResult(
                outcome=SumbleCommitteeOutcome.FAILED_TERMINAL,
                operation=operation,
                provider_calls=provider_calls,
            )
        return await self._finish_ready(operation, provider_calls=provider_calls)

    async def _finish_ready(
        self, operation: CommitteeAcquisitionOperation, *, provider_calls: int
    ) -> SumbleCommitteeResult:
        async with self._conn_factory() as conn:
            snapshots = await list_committee_acquisition_snapshots(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            attempts = await list_committee_acquisition_attempts(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            payload = {
                "contract": "sumble-committee-acquisition-receipt-v1",
                "operation_id": str(operation.operation_id),
                "request_fingerprint": operation.request_fingerprint,
                "discovery_seal_sha256": operation.request.discovery_seal_sha256,
                "account_id": str(operation.request.account_id),
                "committee_plan_ref": operation.request.committee_plan_ref,
                "research_direction_ref": operation.request.research_direction_ref,
                "contact_reveals": False,
                "snapshots": [item.model_dump(mode="json") for item in snapshots],
                "attempts": [item.model_dump(mode="json") for item in attempts],
            }
            receipt_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=_json_bytes(payload),
                media_type="application/json",
                source_key=PEOPLE_SOURCE_KEY,
                source_url=SUMBLE_API_BASE,
            )
            await self._bind(conn, operation, receipt_key, "sumble_committee_receipt")
        completed = await self._refresh_totals(
            operation,
            state=CommitteeAcquisitionState.READY,
            receipt_manifest_key=receipt_key,
            terminal_at=datetime.now(UTC),
        )
        return SumbleCommitteeResult(
            outcome=SumbleCommitteeOutcome.READY,
            operation=completed,
            provider_calls=provider_calls,
        )

    async def _mark_provider_rejected(
        self,
        operation: CommitteeAcquisitionOperation,
        *,
        source_key: str,
        error: ProviderResponseError,
        provider_calls: int = 0,
    ) -> SumbleCommitteeResult:
        """Persist a deterministic provider rejection with its exact diagnostic evidence.

        Sumble validates a request and prechecks the balance *before* charging ("you still get a
        400/402 up front"), so a hard 4xx is a zero-credit terminal refusal — categorically
        different from a transport loss after dispatch. Collapsing both into
        ``spend_outcome_unknown`` forced a manual live replay just to learn the status code; the
        ledger now retains the HTTP status and the provider's own bounded error body.
        """

        failure_code = f"{source_key}_provider_rejected_http_{error.status_code}"
        async with self._conn_factory() as conn:
            rejection_artifact_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=operation.request.workspace_id,
                content=_json_bytes(
                    {
                        "provider_rejection": {
                            "source_key": source_key,
                            "http_status": error.status_code,
                            "body_excerpt": error.body_excerpt,
                        }
                    }
                ),
                media_type="application/json",
                source_key=source_key,
                source_url=_source_url(source_key),
            )
            attempts = await list_committee_acquisition_attempts(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            now = datetime.now(UTC)
            for attempt in attempts:
                if attempt.state is not CommitteeAttemptState.DISPATCHING:
                    continue
                await update_committee_acquisition_attempt(
                    conn,
                    attempt=attempt.model_copy(
                        update={
                            "state": CommitteeAttemptState.RESPONDED,
                            "response_artifact_key": rejection_artifact_key,
                            "failure_code": failure_code,
                            "completed_at": now,
                        }
                    ),
                )
                snapshot = await get_committee_acquisition_snapshot(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                    source_key=attempt.source_key,
                    for_update=True,
                )
                if snapshot is not None and snapshot.state is CommitteeSnapshotState.DISPATCHING:
                    await update_committee_acquisition_snapshot(
                        conn,
                        snapshot=snapshot.model_copy(
                            update={
                                "state": CommitteeSnapshotState.FAILED_TERMINAL,
                                "spend_outcome": CommitteeSpendOutcome.NOT_CHARGED,
                                "failure_code": failure_code,
                            }
                        ),
                    )
        stored = await self._refresh_totals(
            operation,
            state=CommitteeAcquisitionState.FAILED_TERMINAL,
            failure_code=failure_code,
            terminal_at=datetime.now(UTC),
        )
        return SumbleCommitteeResult(
            outcome=SumbleCommitteeOutcome.FAILED_TERMINAL,
            operation=stored,
            provider_calls=provider_calls,
        )

    async def _mark_unknown(
        self,
        operation: CommitteeAcquisitionOperation,
        failure_code: str,
        *,
        provider_calls: int = 0,
    ) -> SumbleCommitteeResult:
        async with self._conn_factory() as conn:
            attempts = await list_committee_acquisition_attempts(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            for attempt in attempts:
                if attempt.state is CommitteeAttemptState.DISPATCHING:
                    await update_committee_acquisition_attempt(
                        conn,
                        attempt=attempt.model_copy(
                            update={
                                "state": CommitteeAttemptState.SPEND_OUTCOME_UNKNOWN,
                                "failure_code": failure_code,
                                "completed_at": datetime.now(UTC),
                            }
                        ),
                    )
                    snapshot = await get_committee_acquisition_snapshot(
                        conn,
                        workspace_id=operation.request.workspace_id,
                        operation_id=operation.operation_id,
                        source_key=attempt.source_key,
                        for_update=True,
                    )
                    if (
                        snapshot is not None
                        and snapshot.state is CommitteeSnapshotState.DISPATCHING
                    ):
                        await update_committee_acquisition_snapshot(
                            conn,
                            snapshot=snapshot.model_copy(
                                update={
                                    "state": CommitteeSnapshotState.SPEND_OUTCOME_UNKNOWN,
                                    "spend_outcome": CommitteeSpendOutcome.UNKNOWN,
                                    "failure_code": failure_code,
                                }
                            ),
                        )
                elif attempt.state is CommitteeAttemptState.RESPONDED:
                    snapshot = await get_committee_acquisition_snapshot(
                        conn,
                        workspace_id=operation.request.workspace_id,
                        operation_id=operation.operation_id,
                        source_key=attempt.source_key,
                        for_update=True,
                    )
                    if (
                        snapshot is not None
                        and snapshot.state is CommitteeSnapshotState.DISPATCHING
                    ):
                        await update_committee_acquisition_snapshot(
                            conn,
                            snapshot=snapshot.model_copy(
                                update={
                                    "state": CommitteeSnapshotState.SPEND_OUTCOME_UNKNOWN,
                                    "spend_outcome": CommitteeSpendOutcome.UNKNOWN,
                                    "response_artifact_key": attempt.response_artifact_key,
                                    "provider_operation_id": attempt.provider_operation_id,
                                    "provider_status": attempt.provider_status,
                                    "provider_units_charged": (attempt.provider_units_charged),
                                    "credits_remaining": attempt.credits_remaining,
                                    "cost_cents_charged": (
                                        attempt.provider_units_charged * self._cents_per_credit
                                    ),
                                    "failure_code": failure_code,
                                }
                            ),
                        )
        stored = await self._refresh_totals(
            operation,
            state=CommitteeAcquisitionState.SPEND_OUTCOME_UNKNOWN,
            failure_code=failure_code,
            terminal_at=datetime.now(UTC),
            force_unknown=True,
        )
        return SumbleCommitteeResult(
            outcome=SumbleCommitteeOutcome.SPEND_OUTCOME_UNKNOWN,
            operation=stored,
            provider_calls=provider_calls,
        )

    async def _refresh_totals(
        self,
        operation: CommitteeAcquisitionOperation,
        *,
        state: CommitteeAcquisitionState,
        next_poll_at: datetime | None = None,
        receipt_manifest_key: str | None = None,
        failure_code: str | None = None,
        terminal_at: datetime | None = None,
        force_unknown: bool = False,
    ) -> CommitteeAcquisitionOperation:
        async with self._conn_factory() as conn:
            current = await get_committee_acquisition_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                for_update=True,
            )
            if current is None:
                raise CommitteeAcquisitionNotFound("committee total refresh")
            snapshots = await list_committee_acquisition_snapshots(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
            charged = sum((item.provider_units_charged for item in snapshots), Decimal(0))
            cost = sum((item.cost_cents_charged for item in snapshots), Decimal(0))
            spend = (
                CommitteeSpendOutcome.UNKNOWN
                if force_unknown
                else (
                    CommitteeSpendOutcome.CHARGED if charged else CommitteeSpendOutcome.NOT_CHARGED
                )
            )
            return await update_committee_acquisition_operation(
                conn,
                operation=current.model_copy(
                    update={
                        "state": state,
                        "spend_outcome": spend,
                        "receipt_manifest_key": receipt_manifest_key,
                        "provider_units_charged": charged,
                        "cost_cents_charged": cost,
                        "next_poll_at": next_poll_at,
                        "failure_code": failure_code,
                        "terminal_at": terminal_at,
                    }
                ),
            )

    async def _set_operation_state(
        self, operation: CommitteeAcquisitionOperation, state: CommitteeAcquisitionState
    ) -> CommitteeAcquisitionOperation:
        return await self._refresh_totals(operation, state=state)

    async def _begin_attempt(
        self,
        operation: CommitteeAcquisitionOperation,
        source_key: str,
        kind: CommitteeAttemptKind,
        request_artifact_key: str,
    ) -> CommitteeAcquisitionAttempt:
        async with self._conn_factory() as conn:
            return await begin_committee_acquisition_attempt(
                conn,
                operation=operation,
                source_key=source_key,
                kind=kind,
                request_artifact_key=request_artifact_key,
            )

    async def _has_dispatching_attempt(self, operation: CommitteeAcquisitionOperation) -> bool:
        async with self._conn_factory() as conn:
            return any(
                item.state is CommitteeAttemptState.DISPATCHING
                for item in await list_committee_acquisition_attempts(
                    conn,
                    workspace_id=operation.request.workspace_id,
                    operation_id=operation.operation_id,
                )
            )

    async def _snapshot(
        self, operation: CommitteeAcquisitionOperation, source_key: str
    ) -> CommitteeAcquisitionSnapshot:
        async with self._conn_factory() as conn:
            snapshot = await get_committee_acquisition_snapshot(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
                source_key=source_key,
            )
        if snapshot is None:
            raise CommitteeAcquisitionNotFound(f"committee snapshot {source_key}")
        return snapshot

    async def _get(self, operation: CommitteeAcquisitionOperation) -> CommitteeAcquisitionOperation:
        async with self._conn_factory() as conn:
            current = await get_committee_acquisition_operation(
                conn,
                workspace_id=operation.request.workspace_id,
                operation_id=operation.operation_id,
            )
        if current is None:
            raise CommitteeAcquisitionNotFound("committee acquisition")
        return current

    def _terminal_result(
        self, operation: CommitteeAcquisitionOperation, *, replay: bool
    ) -> SumbleCommitteeResult | None:
        if operation.state is CommitteeAcquisitionState.READY:
            return SumbleCommitteeResult(
                outcome=(
                    SumbleCommitteeOutcome.REPLAYED if replay else SumbleCommitteeOutcome.READY
                ),
                operation=operation,
            )
        if operation.state is CommitteeAcquisitionState.SPEND_OUTCOME_UNKNOWN:
            return SumbleCommitteeResult(
                outcome=SumbleCommitteeOutcome.SPEND_OUTCOME_UNKNOWN, operation=operation
            )
        if operation.state in {
            CommitteeAcquisitionState.FAILED_TERMINAL,
            CommitteeAcquisitionState.CANCELLED,
        }:
            return SumbleCommitteeResult(
                outcome=SumbleCommitteeOutcome.FAILED_TERMINAL, operation=operation
            )
        return None

    async def _capture_wire(
        self, conn: Any, workspace_id: str, source_key: str, body: Mapping[str, Any]
    ) -> str:
        return await capture_discovery_artifact(
            conn,
            self._storage,
            workspace_id=workspace_id,
            content=_json_bytes({"method": "POST", "body": body}),
            media_type="application/json",
            source_key=source_key,
            source_url=_source_url(source_key),
        )

    async def _require_rate_token(self) -> None:
        if self._rate_limiter is not None and not await self._rate_limiter.acquire("sumble"):
            raise SumbleCommitteeRateLimited("Sumble aggregate provider rate limit is exhausted")

    @staticmethod
    async def _bind(
        conn: Any,
        operation: CommitteeAcquisitionOperation,
        artifact_key: str,
        reference_kind: str,
    ) -> None:
        await bind_discovery_artifact_subject(
            conn,
            workspace_id=operation.request.workspace_id,
            artifact_key_value=artifact_key,
            subject_kind="account",
            subject_entity_id=operation.request.account_id,
            reference_kind=reference_kind,
            reference_id=str(operation.operation_id),
        )


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def _wire_fingerprint(parent: str, source_key: str, body: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        _json_bytes(
            {
                "parent_fingerprint": parent,
                "source_key": source_key,
                "method": "POST",
                "body": body,
                "provider_api_version": SUMBLE_API_VERSION,
                "provider_contract_version": SUMBLE_COMMITTEE_CONTRACT_VERSION,
            }
        )
    ).hexdigest()


def _source_url(source_key: str) -> str:
    return f"{SUMBLE_API_BASE}/{'teams' if source_key == TEAMS_SOURCE_KEY else 'people'}"


__all__ = [
    "SUMBLE_COMMITTEE_CONTRACT_VERSION",
    "SUMBLE_COMMITTEE_POLICY_VERSION",
    "SUMBLE_COMMITTEE_PRICING_VERSION",
    "CommitteeRateLimiter",
    "SumbleCommitteeAcquisitionCoordinator",
    "SumbleCommitteeOutcome",
    "SumbleCommitteePreflight",
    "SumbleCommitteeResult",
    "SumbleCommitteeRateLimited",
    "compile_sumble_committee_preflight",
]
