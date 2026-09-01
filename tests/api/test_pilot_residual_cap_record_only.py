"""The cap refusals 39fcdc13's ruling covers but its lane did not reach (sweep, 2026-08-20).

`_memory/2026-08-20-record-only-spend-caps.md` closed with a named residual: the discovery-gap and
Exa targeted-enrichment reservations carried the *same* reserved-vs-cap refusals as the two paths
that were converted, and the same pre-conversion docstring ("consistency guards on its immutable
plan"). The batch-level Exa discovery reservation is the third of that family. Each is our own
arithmetic over our own number, so under the founder ruling each records and proceeds when
``Settings.budget_controls_enabled`` is off, and refuses byte-identically when it is on.

Both arms are asserted for every site: the enforcing arm keeps the original exception and message
(a regression that leaves the caps permanently inert fails here), and the record-only arm proves
execution went *past* the comparison — for the two reservation functions by reaching the very next
statement, which is a database read.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ClaimId,
    DiscoveryBatchId,
    DiscoveryGapFieldPlan,
    DiscoveryGapOperation,
    DiscoveryGapOperationId,
    DiscoveryGapOperationState,
    DiscoveryGapRequest,
    DiscoveryGapSpendOutcome,
    DiscoveryItemSnapshotId,
    EntityId,
    ProjectRunId,
    TargetedEnrichmentFieldPlan,
    TargetedEnrichmentOperationId,
    TargetedEnrichmentSpendOutcome,
    TargetedEnrichmentState,
    TargetedEnrichmentTarget,
)
from clue_core.discovery import DiscoveryEnrichmentFormat
from clue_obs.otel.metrics import InMemorySink, get_metric_sink, set_metric_sink
from clue_research.durable.discovery_gap import (
    DiscoveryGapBudgetExceeded,
    reserve_discovery_gap_operation,
)
from clue_research.durable.spend_posture import (
    EVENT_SPEND_CAP_RECORD_ONLY,
    METRIC_SPEND_CAP_RECORD_ONLY,
)
from clue_research.durable.targeted_enrichment import (
    TargetedEnrichmentBudgetExceeded,
    TargetedEnrichmentOperation,
    TargetedEnrichmentRequest,
    reserve_targeted_enrichment_operation,
)
from tests.db.conftest import run_async


class _ReachedTheDatabase(RuntimeError):
    """Raised by the sentinel connection: proof the cap comparison did not stop the call."""


class _SentinelConn:
    """A connection that refuses to be used — the statement right after each cap comparison."""

    async def execute(self, *_args: object, **_kwargs: object) -> object:
        raise _ReachedTheDatabase("the reservation proceeded past its cap comparison")


@contextmanager
def _sync_recorded() -> Iterator[tuple[InMemorySink, list[dict[str, Any]]]]:
    previous = get_metric_sink()
    sink = InMemorySink()
    set_metric_sink(sink)
    try:
        with structlog.testing.capture_logs() as events:
            yield sink, events
    finally:
        set_metric_sink(previous)


@asynccontextmanager
async def _recorded() -> AsyncIterator[tuple[InMemorySink, list[dict[str, Any]]]]:
    previous = get_metric_sink()
    sink = InMemorySink()
    set_metric_sink(sink)
    try:
        with structlog.testing.capture_logs() as events:
            yield sink, events
    finally:
        set_metric_sink(previous)


def _reasons(sink: InMemorySink, events: list[dict[str, Any]]) -> set[str]:
    logged = {
        str(event["reason"])
        for event in events
        if event.get("event") == EVENT_SPEND_CAP_RECORD_ONLY and "reason" in event
    }
    metered = {
        dict(attributes)["reason"]
        for (name, attributes), value in sink.counters.items()
        if name == METRIC_SPEND_CAP_RECORD_ONLY and value > 0
    }
    assert logged == metered, "every skipped cap refusal must both log and meter"
    return logged


def _sites(events: list[dict[str, Any]]) -> set[str]:
    return {
        str(event["site"])
        for event in events
        if event.get("event") == EVENT_SPEND_CAP_RECORD_ONLY and "site" in event
    }


def _gap_operation(*, units_over: bool, cost_over: bool) -> DiscoveryGapOperation:
    """A gap reservation whose own reserved amounts exceed its own immutable caps."""

    request = DiscoveryGapRequest(
        workspace_id="ws-residual-cap",
        project_id="prj-residual-cap",
        project_run_id=ProjectRunId(uuid4()),
        icp_key="deep",
        icp_version=1,
        discovery_batch_id=DiscoveryBatchId(uuid4()),
        account_id=EntityId(uuid4()),
        primary_domain="insighthealth.example",
        source_key="sumble_organizations",
        provider_api_version="v9",
        provider_contract_version="contract-1",
        pricing_policy_version="pricing-1",
        field_policy_version="fields-1",
        observation_window="2026-08-20",
        required_criteria=("hq_location",),
        eligibility_claim_ids=(ClaimId(uuid4()),),
        fields=(
            DiscoveryGapFieldPlan(
                logical_field_key="core.hq_location",
                field_key="core.hq_location",
                source_key="sumble_organizations",
                expected_value_credits=Decimal(8),
                source_item_ids=(DiscoveryItemSnapshotId(uuid4()),),
            ),
        ),
        provider_credit_cap=8,
        expected_value_credits=Decimal(8),
        money_budget_cap_cents=Decimal(4),
    )
    return DiscoveryGapOperation(
        operation_id=DiscoveryGapOperationId(uuid4()),
        request=request,
        request_fingerprint=request.request_fingerprint,
        state=DiscoveryGapOperationState.PLANNED,
        spend_outcome=DiscoveryGapSpendOutcome.NOT_DISPATCHED,
        request_artifact_key="artifacts/residual-cap/request.json",
        provider_units_reserved=Decimal(99) if units_over else Decimal(1),
        cost_cents_reserved=Decimal(99) if cost_over else Decimal(1),
    )


def _targeted_operation(*, units_over: bool, cost_over: bool) -> TargetedEnrichmentOperation:
    request = TargetedEnrichmentRequest(
        workspace_id="ws-residual-cap",
        project_id="prj-residual-cap",
        project_run_id=ProjectRunId(uuid4()),
        icp_key="deep",
        icp_version=1,
        discovery_batch_id=DiscoveryBatchId(uuid4()),
        discovery_seal_sha256="a" * 64,
        source_key="exa_targeted",
        provider_api_version="v1",
        provider_contract_version="contract-1",
        pricing_policy_version="pricing-1",
        field_policy_version="fields-1",
        observation_window="2026-08-20",
        targets=(
            TargetedEnrichmentTarget(
                account_id=EntityId(uuid4()),
                identifier_url="https://insighthealth.example/",
                tier_claim_id=ClaimId(uuid4()),
            ),
        ),
        fields=(
            TargetedEnrichmentFieldPlan(
                field_key="core.hq_location",
                description="Headquarters location",
                format=DiscoveryEnrichmentFormat.TEXT,
            ),
        ),
        provider_credit_cap=8,
        money_budget_cap_cents=Decimal(4),
    )
    return TargetedEnrichmentOperation(
        operation_id=TargetedEnrichmentOperationId(uuid4()),
        request=request,
        request_fingerprint=request.request_fingerprint,
        provider_external_id="exa-import-residual-cap",
        state=TargetedEnrichmentState.PLANNED,
        spend_outcome=TargetedEnrichmentSpendOutcome.NOT_DISPATCHED,
        input_artifact_key="artifacts/residual-cap/input.json",
        csv_artifact_key="artifacts/residual-cap/input.csv",
        provider_units_reserved=Decimal(99) if units_over else Decimal(1),
        cost_cents_reserved=Decimal(99) if cost_over else Decimal(1),
    )


@pytest.mark.parametrize(
    ("units_over", "cost_over", "reason", "message"),
    [
        (True, False, "reserved_units_above_cap", "discovery-gap provider cap exceeded"),
        (False, True, "reserved_cost_above_cap", "discovery-gap money cap exceeded"),
    ],
)
def test_the_discovery_gap_reservation_caps_record_only_in_the_pilot_posture(
    units_over: bool, cost_over: bool, reason: str, message: str
) -> None:
    run_async(_gap_scenario(units_over, cost_over, reason, message))


async def _gap_scenario(units_over: bool, cost_over: bool, reason: str, message: str) -> None:
    operation = _gap_operation(units_over=units_over, cost_over=cost_over)
    conn = cast(AsyncConnection, _SentinelConn())

    # Enforcing: today's refusal, byte for byte, before anything is read or written.
    async with _recorded() as (sink, events):
        with pytest.raises(DiscoveryGapBudgetExceeded, match=message):
            await reserve_discovery_gap_operation(conn, operation=operation, enforce_budget=True)
        assert _reasons(sink, events) == set()

    # Record-only: the comparison still runs, the skip is announced, the call proceeds.
    async with _recorded() as (sink, events):
        with pytest.raises(_ReachedTheDatabase):
            await reserve_discovery_gap_operation(conn, operation=operation, enforce_budget=False)
        assert _reasons(sink, events) == {reason}
        assert _sites(events) == {"discovery_gap_reservation"}


@pytest.mark.parametrize(
    ("units_over", "cost_over", "reason", "message"),
    [
        (True, False, "reserved_units_above_cap", "targeted enrichment provider cap exceeded"),
        (False, True, "reserved_cost_above_cap", "targeted enrichment money cap exceeded"),
    ],
)
def test_the_targeted_enrichment_reservation_caps_record_only_in_the_pilot_posture(
    units_over: bool, cost_over: bool, reason: str, message: str
) -> None:
    run_async(_targeted_scenario(units_over, cost_over, reason, message))


async def _targeted_scenario(units_over: bool, cost_over: bool, reason: str, message: str) -> None:
    operation = _targeted_operation(units_over=units_over, cost_over=cost_over)
    conn = cast(AsyncConnection, _SentinelConn())

    async with _recorded() as (sink, events):
        with pytest.raises(TargetedEnrichmentBudgetExceeded, match=message):
            await reserve_targeted_enrichment_operation(
                conn, operation=operation, enforce_budget=True
            )
        assert _reasons(sink, events) == set()

    async with _recorded() as (sink, events):
        with pytest.raises(_ReachedTheDatabase):
            await reserve_targeted_enrichment_operation(
                conn, operation=operation, enforce_budget=False
            )
        assert _reasons(sink, events) == {reason}
        assert _sites(events) == {"targeted_enrichment_reservation"}


@pytest.mark.usefixtures("require_profiling_db")
def test_the_batch_discovery_reservation_cap_records_and_submits(tmp_path: Path) -> None:
    """The third of the family, proved end to end: the same request that the enforcing posture
    refuses before any transport call now creates the Webset, with the overshoot recorded."""

    from clue_api.exa_websets_submit import DurableExaWebsetSubmitter
    from clue_research.durable.discovery import DiscoveryBudgetExceeded
    from clue_storage import FsStorage
    from tests.api.test_exa_websets_submit_d2 import _RecordingTransport, _start_batch
    from tests.durable.conftest import rollback_conn

    async def _run() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            _, batch_id = await _start_batch(
                conn,
                workspace_id="ws_residual_cap_batch",
                provider_credit_cap=19,
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            enforcing = _RecordingTransport()
            with pytest.raises(DiscoveryBudgetExceeded, match="provider-unit reservation"):
                await DurableExaWebsetSubmitter(
                    transport=enforcing,
                    storage=storage,
                    conn_factory=same_connection,
                    enforce_budget=True,
                ).submit(
                    workspace_id="ws_residual_cap_batch",
                    batch_id=batch_id,
                    search_key="account-discovery",
                    observation_window="2026-08-02",
                )
            assert enforcing.create_calls == 0

            recording = _RecordingTransport()
            async with _recorded() as (sink, events):
                result = await DurableExaWebsetSubmitter(
                    transport=recording,
                    storage=storage,
                    conn_factory=same_connection,
                    enforce_budget=False,
                ).submit(
                    workspace_id="ws_residual_cap_batch",
                    batch_id=batch_id,
                    search_key="account-discovery",
                    observation_window="2026-08-02",
                )
            assert recording.create_calls == 1
            assert result.operation.provider_units_reserved > 0
            assert "batch_reserved_units_above_plan_cap" in _reasons(sink, events)
            assert _sites(events) == {"discovery_reservation"}

    run_async(_run())


def test_the_contact_channel_settlement_defaults_to_enforcing_and_is_wired_to_the_switch() -> None:
    """The fourth site: a post-charge cap on the contact-channel settle path.

    Its exact sibling — the provider settlement in ``entity_research_tools`` — has been gated on
    ``self._enforce_budget`` since the FI pilot pass; this one kept an unconditional SQL guard and
    refused *after* the provider had already charged, which is the 2026-08-19 defect exactly. The
    conversion is the sibling's shape (drop the guard clause, read the overshoot back off the
    write). Covered here by its contract rather than a second full fleet run: the constructor
    still defaults to enforcing, production wiring feeds it the pilot switch, and the announcement
    fires only on a real overshoot.
    """

    import inspect

    from clue_api import entity_research_provider_wiring
    from clue_api.contact_entity_research_channels import (
        GovernedContactChannelActions,
        _record_cap_overshoot,
    )

    signature = inspect.signature(GovernedContactChannelActions.__init__)
    assert signature.parameters["enforce_budget"].default is True, (
        "the contact-channel settlement must default to today's enforced behaviour"
    )
    source = inspect.getsource(entity_research_provider_wiring)
    assert "enforce_budget=self._settings.budget_controls_enabled" in source

    fold = inspect.getsource(GovernedContactChannelActions._fold_cost)
    assert fold.count("if self._enforce_budget else") == 2, "both budget guards must be gated"
    assert "channel cost fold replay changed settlement" in fold, (
        "the settlement-replay truth check must stay unconditional"
    )

    with _sync_recorded() as (sink, events):
        _record_cap_overshoot(Decimal(9), Decimal(10), site="s", reason="within_cap")
        assert _reasons(sink, events) == set()
        _record_cap_overshoot(Decimal(11), Decimal(10), site="s", reason="job_cap_exceeded")
        assert _reasons(sink, events) == {"job_cap_exceeded"}
