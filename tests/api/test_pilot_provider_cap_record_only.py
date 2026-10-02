"""Founder ruling 2026-08-20: OUR OWN spend caps are record-only in the pilot posture.

`_memory/2026-08-20-seven-fix-night-close-out.md` §"Founder rulings", ruling 2: *"Spend caps exist
but do not block, for now. Provider credit-cap / unbounded-charge guards flip to record-only in the
pilot posture (log + exact accounting, never refuse)."* The lesson behind it — "gates before the
loop" — is the 15-day one: a cap we set ourselves killed a *paid, already-charged* tech-stack call
live on 2026-08-19 (`sumble_unbounded_charge_exceeded_authorized_cap`), throwing away data the
provider had already billed us for.

The switch is the existing FI pilot one, `Settings.budget_controls_enabled` (env
``CLUE_BUDGET_CONTROLS_ENABLED``; flipped to False by the ``integration_pilot`` overlay and
threaded as ``enforce_budget`` from every composition root). No new flag.

What "record-only" means here, and what it deliberately does not:

* **Converted** — every refusal on the Sumble account-gap and committee-acquisition paths whose
  only basis is our own cost arithmetic (cap vs bounded maximum, expected value vs cap, reserved vs
  cap, charged vs cap). Each one still computes its comparison, emits a structured log plus the
  ``research.spend.cap_record_only`` counter naming the amounts, and then proceeds.
* **Accounting stays exact** — the ledger rows keep their true reserved/charged numbers, and the
  table CHECKs (``charged <= reserved``) are untouched: where a record-only charge could now exceed
  its reservation, the operation *reserves honestly larger* instead.
* **Untouched** — provider truth (a real Sumble 4xx still folds terminal), the unknown-spend
  quarantine, the A9 idempotency machinery, and every structural/authority guard.

Both directions are pinned: with controls **on** the old refusals still fire with their original
messages, so a regression that leaves enforcement permanently off fails here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import structlog
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.sumble_account_gaps import (
    SumbleAccountGapCoordinator,
    SumbleAccountGapEligibilityError,
    SumbleAccountGapOutcome,
    SumbleAccountGapStarter,
)
from clue_api.sumble_committee_acquisition import (
    SumbleCommitteeAcquisitionCoordinator,
    SumbleCommitteeOutcome,
    compile_sumble_committee_preflight,
)
from clue_config.settings import INTEGRATION_PILOT_OVERLAY, Settings
from clue_core import (
    AccountGapOperationId,
    AccountGapOperationState,
    AccountGapSpendOutcome,
    EntityId,
    ProjectRunId,
)
from clue_obs.otel.metrics import InMemorySink, get_metric_sink, set_metric_sink
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.durable import (
    get_account_gap_operation,
    list_account_gap_snapshots,
)
from clue_research.durable.committee_acquisition import (
    CommitteeAcquisitionBudgetExceeded,
    get_committee_acquisition_operation,
)
from clue_research.durable.spend_posture import METRIC_SPEND_CAP_RECORD_ONLY
from clue_research.resolvers.sumble import (
    ORGANIZATIONS_SOURCE_KEY,
    SumbleClient,
    SumbleCreditBudget,
)
from clue_storage import FsStorage
from tests.api.test_sumble_account_gaps_s1 import (
    _RejectingSumbleHttp,
    _seed_selected_high_tier_account,
    _SumbleHttp,
)
from tests.api.test_sumble_committee_acquisition_s2b import _CommitteeTransport, _setup
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

#: The two-field request the live 2026-08-19 run made: engineering hiring (bounded ``/jobs``) plus
#: confirmed tech (the unbounded ``/techs`` endpoint). The fixtures charge 1 + 1 + 3 = 5 credits,
#: while the bounded worst case the preflight can prove is only 1 (organizations) + 1 (jobs) = 2 —
#: which is exactly why a cap set from the bounded maximum killed a call that had already been paid.
_LIVE_FIELDS = {
    "account.hiring_velocity_eng": Decimal(5),
    "core.primary_tech_stack": Decimal(5),
}
_LIVE_BOUNDED_MAXIMUM = 2
_LIVE_TRUE_CHARGE = Decimal(5)


@asynccontextmanager
async def _recorded() -> AsyncIterator[tuple[InMemorySink, list[dict[str, Any]]]]:
    """Install a fresh metric sink and capture structlog events for the duration."""

    previous = get_metric_sink()
    sink = InMemorySink()
    set_metric_sink(sink)
    try:
        with structlog.testing.capture_logs() as events:
            yield sink, events
    finally:
        set_metric_sink(previous)


def _gap_starter(
    *,
    storage: FsStorage,
    conn_factory: Any,
    http: Any,
    enforce_budget: bool,
) -> SumbleAccountGapStarter:
    def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
        return SumbleClient(
            api_key=SecretStr("fixture"),
            budget=SumbleCreditBudget(maximum=maximum),
            http=http,
            cents_per_credit=cents,
        )

    return SumbleAccountGapStarter(
        coordinator=SumbleAccountGapCoordinator(
            api_key=SecretStr("fixture"),
            storage=storage,
            cents_per_credit=Decimal("0.5"),
            conn_factory=conn_factory,
            client_factory=client_factory,
            enforce_budget=enforce_budget,
        ),
        storage=storage,
        cents_per_credit=Decimal("0.5"),
        conn_factory=conn_factory,
        enforce_budget=enforce_budget,
    )


def _record_only_event(events: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    """The one record-only log event for ``reason`` (an AssertionError, never a StopIteration)."""

    matching = [
        event
        for event in events
        if event.get("event") == "spend_cap.record_only" and event.get("reason") == reason
    ]
    assert len(matching) == 1, f"expected exactly one {reason!r} record, got {matching}"
    return matching[0]


def _record_only_reasons(sink: InMemorySink, events: list[dict[str, Any]]) -> set[str]:
    """The reasons this posture skipped, proved from both surfaces at once."""

    logged = {
        str(event["reason"])
        for event in events
        if event.get("event") == "spend_cap.record_only" and "reason" in event
    }
    metered = {
        dict(attributes)["reason"]
        for (name, attributes), value in sink.counters.items()
        if name == METRIC_SPEND_CAP_RECORD_ONLY and value > 0
    }
    assert logged == metered, "every skipped refusal must both log and meter"
    return logged


def test_the_pilot_switch_defaults_to_enforcing_and_only_the_overlay_flips_it() -> None:
    """The pin against a regression that leaves record-only permanently on.

    Record-only is a *posture*, not the new default: an unset deployment must still enforce, and
    the only thing that turns it off is the checked-in ``integration_pilot`` activation record.
    """

    # Asserted off the model rather than off a constructed Settings so a developer's sourced
    # `.env` (which sets CLUE_PRODUCT_PATH=integration_pilot) cannot make this pin vacuous.
    assert Settings.model_fields["budget_controls_enabled"].default is True
    assert INTEGRATION_PILOT_OVERLAY["budget_controls_enabled"] is False
    # An explicit value still wins over the overlay (the overlay supplies defaults only).
    assert (
        Settings(
            _env_file=None, product_path="integration_pilot", budget_controls_enabled=True
        ).budget_controls_enabled
        is True
    )


def test_an_over_cap_unbounded_tech_charge_completes_instead_of_burning_the_paid_data(
    tmp_path: Path,
) -> None:
    """The live 2026-08-19 shape: the money is already spent when our cap check runs.

    ``/techs`` has no caller-side limit, so the charge is only known after the provider answers.
    Refusing there does not save a credit — it throws away data we have already been billed for and
    fails the account. Under the pilot posture the operation completes, the claims materialize, and
    the true charge is recorded on the ledger.
    """

    # Each posture gets its own rollback transaction and its own seeded account: an account-gap
    # purchase is append-only and same-window-unique by design, so the two arms cannot share one.
    async def scenario() -> None:
        workspace_id = "ws-pilot-cap-tech"
        storage = FsStorage(tmp_path / "artifacts")

        # --- controls ON: today's behaviour, byte-identical -----------------------------------
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            enforcing_http = _SumbleHttp("insighthealth.ai")
            refused = await _gap_starter(
                storage=storage,
                conn_factory=same_connection,
                http=enforcing_http,
                enforce_budget=True,
            ).start(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=EntityId(ready.account_id),
                field_expected_value_credits=_LIVE_FIELDS,
                provider_credit_cap=_LIVE_BOUNDED_MAXIMUM,
                allow_unbounded_tech=True,
            )
            assert refused.outcome is SumbleAccountGapOutcome.FAILED_TERMINAL
            assert refused.operation.failure_code == (
                "sumble_unbounded_charge_exceeded_authorized_cap"
            )
            # The refusal never saved anything: all three calls were made and charged.
            assert len(enforcing_http.calls) == 3
            assert refused.operation.provider_units_charged == _LIVE_TRUE_CHARGE
            assert (
                await claims_for(
                    conn,
                    EntityId(ready.account_id),
                    "core.primary_tech_stack",
                    scope=WorkspaceScope.for_workspace(workspace_id),
                )
                == []
            )

        # --- controls OFF: same charge, recorded and kept -------------------------------------
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            http = _SumbleHttp("insighthealth.ai")
            async with _recorded() as (sink, events):
                result = await _gap_starter(
                    storage=storage,
                    conn_factory=same_connection,
                    http=http,
                    enforce_budget=False,
                ).start(
                    workspace_id=workspace_id,
                    project_run_id=ProjectRunId(started.project_run_id),
                    account_id=EntityId(ready.account_id),
                    field_expected_value_credits=_LIVE_FIELDS,
                    provider_credit_cap=_LIVE_BOUNDED_MAXIMUM,
                    allow_unbounded_tech=True,
                )
                reasons = _record_only_reasons(sink, events)
                charge_event = _record_only_event(events, "charge_above_authorized_cap")

            assert result.outcome is SumbleAccountGapOutcome.COMPLETED
            assert reasons == {"charge_above_authorized_cap"}
            # The record names exactly what would have been refused, and by how much.
            assert charge_event["provider_units_charged"] == str(_LIVE_TRUE_CHARGE)
            assert charge_event["provider_credit_cap"] == str(_LIVE_BOUNDED_MAXIMUM)

            operation = await get_account_gap_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=AccountGapOperationId(result.operation.operation_id),
            )
            assert operation is not None
            assert operation.state is AccountGapOperationState.SUCCEEDED
            assert operation.spend_outcome is AccountGapSpendOutcome.CHARGED
            assert operation.failure_code is None
            # Accounting is exact, not rounded down to the cap.
            assert operation.provider_units_charged == _LIVE_TRUE_CHARGE
            assert operation.cost_cents_charged == Decimal("2.5")
            assert operation.provider_units_reserved == Decimal(_LIVE_BOUNDED_MAXIMUM)
            assert operation.unbounded_call_approved is True
            charged = sum(
                (
                    row.provider_units_charged
                    for row in await list_account_gap_snapshots(
                        conn, workspace_id=workspace_id, operation_id=operation.operation_id
                    )
                ),
                Decimal(0),
            )
            assert charged == _LIVE_TRUE_CHARGE
            # And the paid data is kept.
            assert (
                len(
                    await claims_for(
                        conn,
                        EntityId(ready.account_id),
                        "core.primary_tech_stack",
                        scope=WorkspaceScope.for_workspace(workspace_id),
                    )
                )
                == 1
            )

    run_async(scenario())


def test_the_preflight_cap_arithmetic_is_recorded_not_refused_and_reserves_honestly_larger(
    tmp_path: Path,
) -> None:
    """The two pre-dispatch cost refusals: cap-below-bounded, and value-does-not-justify-cap.

    Both are pure arithmetic over numbers we chose, so both become records. The first has a durable
    consequence the ruling calls out explicitly: a reservation below the bounded worst case could
    let ``provider_units_charged`` pass ``provider_units_reserved``, so instead of weakening the
    ledger CHECK the operation reserves the honest bounded maximum.
    """

    async def scenario() -> None:
        workspace_id = "ws-pilot-cap-preflight"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            http = _SumbleHttp("insighthealth.ai")
            enforcing = _gap_starter(
                storage=storage,
                conn_factory=same_connection,
                http=http,
                enforce_budget=True,
            )
            recording = _gap_starter(
                storage=storage,
                conn_factory=same_connection,
                http=http,
                enforce_budget=False,
            )
            hiring_only = {"account.hiring_velocity_eng": Decimal(1)}

            # --- controls ON ------------------------------------------------------------------
            with pytest.raises(
                SumbleAccountGapEligibilityError,
                match="provider cap 1 is below bounded request maximum 2",
            ):
                await enforcing.start(
                    workspace_id=workspace_id,
                    project_run_id=ProjectRunId(started.project_run_id),
                    account_id=EntityId(ready.account_id),
                    field_expected_value_credits=hiring_only,
                    provider_credit_cap=1,
                    allow_unbounded_tech=False,
                )
            with pytest.raises(
                SumbleAccountGapEligibilityError,
                match="expected field value does not justify the authorized provider-credit cap",
            ):
                await enforcing.start(
                    workspace_id=workspace_id,
                    project_run_id=ProjectRunId(started.project_run_id),
                    account_id=EntityId(ready.account_id),
                    field_expected_value_credits=hiring_only,
                    provider_credit_cap=3,
                    allow_unbounded_tech=False,
                )
            assert http.calls == []
            assert (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one() == 0

            # --- controls OFF -----------------------------------------------------------------
            async with _recorded() as (sink, events):
                result = await recording.start(
                    workspace_id=workspace_id,
                    project_run_id=ProjectRunId(started.project_run_id),
                    account_id=EntityId(ready.account_id),
                    field_expected_value_credits=hiring_only,
                    provider_credit_cap=1,
                    allow_unbounded_tech=False,
                )
                reasons = _record_only_reasons(sink, events)
                below = _record_only_event(events, "cap_below_bounded_maximum")

            assert result.outcome is SumbleAccountGapOutcome.COMPLETED
            # All three of the cost comparisons this request trips are recorded, at both layers:
            # the preflight pair and the durable reservation's value-vs-reservation guard.
            assert reasons == {
                "cap_below_bounded_maximum",
                "value_below_authorized_cap",
                "value_below_reserved_units",
            }
            assert below["provider_credit_cap"] == "1"
            assert below["bounded_maximum"] == "2"

            operation = await get_account_gap_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=AccountGapOperationId(result.operation.operation_id),
            )
            assert operation is not None
            # Reserved honestly at the bounded worst case, never below what may be charged.
            assert operation.provider_units_reserved == Decimal(_LIVE_BOUNDED_MAXIMUM)
            assert operation.request.provider_credit_cap == _LIVE_BOUNDED_MAXIMUM
            assert operation.provider_units_charged <= operation.provider_units_reserved
            assert operation.provider_units_charged == Decimal(2)

            # The exact replay of the same authorization is still a zero-call replay, not a
            # conflict, even though the stored cap was raised above the argument.
            calls = len(http.calls)
            replay = await recording.start(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=EntityId(ready.account_id),
                field_expected_value_credits=hiring_only,
                provider_credit_cap=1,
                allow_unbounded_tech=False,
            )
            assert replay.outcome is SumbleAccountGapOutcome.REPLAYED
            assert replay.operation.operation_id == operation.operation_id
            assert len(http.calls) == calls

    run_async(scenario())


def test_committee_acquisition_reserves_and_dispatches_past_its_cap_when_controls_are_off(
    tmp_path: Path,
) -> None:
    """The committee equivalents: the wire-plan preflight caps and the durable reserve-vs-cap pair.

    The reservation is the wire plan's own bounded maximum, so it is already honest and needs no
    raising; only the comparison against the configured cap goes inert. The ledger CHECK
    (``charged <= reserved``) is untouched and still holds.
    """

    async def scenario() -> None:
        workspace_id = "ws-pilot-cap-committee"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(conn, storage, workspace_id=workspace_id)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            starved = request.model_copy(
                update={"provider_credit_cap": 1, "money_budget_cap_cents": Decimal(1)}
            )
            under_funded = request.model_copy(update={"money_budget_cap_cents": Decimal(1)})

            # --- controls ON ------------------------------------------------------------------
            with pytest.raises(ValueError, match="committee wire plan exceeds its provider credit"):
                compile_sumble_committee_preflight(starved, cents_per_credit=Decimal("0.5"))
            with pytest.raises(ValueError, match="committee wire plan exceeds its money cap"):
                compile_sumble_committee_preflight(under_funded, cents_per_credit=Decimal("0.5"))

            # --- controls OFF -----------------------------------------------------------------
            async with _recorded() as (sink, events):
                preflight = compile_sumble_committee_preflight(
                    starved, cents_per_credit=Decimal("0.5"), enforce_budget=False
                )
                assert _record_only_reasons(sink, events) == {
                    "wire_plan_above_credit_cap",
                    "wire_plan_above_money_cap",
                }

            # The durable reservation is the second cap layer and refuses on its own with
            # controls on, even when handed an admitted plan.
            transport = _CommitteeTransport()
            with pytest.raises(
                CommitteeAcquisitionBudgetExceeded, match="committee provider cap exceeded"
            ):
                await SumbleCommitteeAcquisitionCoordinator(
                    transport=transport,
                    storage=storage,
                    cents_per_credit=Decimal("0.5"),
                    conn_factory=same_connection,
                    poll_after_seconds=30,
                    enforce_budget=True,
                ).start(preflight)
            assert transport.calls == []

            async with _recorded() as (sink, events):
                pending = await SumbleCommitteeAcquisitionCoordinator(
                    transport=transport,
                    storage=storage,
                    cents_per_credit=Decimal("0.5"),
                    conn_factory=same_connection,
                    poll_after_seconds=30,
                    enforce_budget=False,
                ).start(preflight)
                assert _record_only_reasons(sink, events) == {
                    "reserved_units_above_cap",
                    "reserved_cost_above_cap",
                }

            assert pending.outcome is SumbleCommitteeOutcome.WAITING_EXTERNAL
            assert transport.calls == ["teams", "people_submit"]
            operation = await get_committee_acquisition_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=pending.operation.operation_id,
            )
            assert operation is not None
            expected_units = Decimal(
                preflight.teams_maximum_credits + preflight.people_maximum_credits
            )
            assert operation.provider_units_reserved == expected_units
            assert operation.cost_cents_reserved == expected_units * Decimal("0.5")
            assert operation.provider_units_charged == Decimal(12)
            assert operation.provider_units_charged <= operation.provider_units_reserved
            assert operation.cost_cents_charged <= operation.cost_cents_reserved

    run_async(scenario())


def test_provider_truth_and_unknown_spend_are_untouched_by_the_record_only_posture(
    tmp_path: Path,
) -> None:
    """The boundary of the ruling: only OUR caps stop refusing.

    A hard Sumble 4xx is the provider's own fact and still folds terminal and uncharged; an
    ambiguous fault still quarantines as ``spend_outcome_unknown`` for reconciliation. Neither is a
    cap, so neither moves — and no record-only event is emitted for either.
    """

    async def scenario() -> None:
        workspace_id = "ws-pilot-cap-truth"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            async with _recorded() as (sink, events):
                rejected = await _gap_starter(
                    storage=storage,
                    conn_factory=same_connection,
                    http=_RejectingSumbleHttp(status_code=422, body_excerpt='{"detail":[]}'),
                    enforce_budget=False,
                ).start(
                    workspace_id=workspace_id,
                    project_run_id=ProjectRunId(started.project_run_id),
                    account_id=EntityId(ready.account_id),
                    field_expected_value_credits={"account.hiring_velocity_eng": Decimal(5)},
                    provider_credit_cap=2,
                    allow_unbounded_tech=False,
                )
                assert _record_only_reasons(sink, events) == set()

            assert rejected.outcome is SumbleAccountGapOutcome.FAILED_TERMINAL
            assert rejected.operation.spend_outcome is AccountGapSpendOutcome.NOT_CHARGED
            assert rejected.operation.failure_code == (
                f"{ORGANIZATIONS_SOURCE_KEY}_provider_rejected_http_422"
            )

        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            unknown = await _gap_starter(
                storage=storage,
                conn_factory=same_connection,
                http=_RejectingSumbleHttp(status_code=None, body_excerpt=None),
                enforce_budget=False,
            ).start(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=EntityId(ready.account_id),
                field_expected_value_credits={"account.hiring_velocity_eng": Decimal(5)},
                provider_credit_cap=2,
                allow_unbounded_tech=False,
            )
            assert unknown.outcome is SumbleAccountGapOutcome.SPEND_OUTCOME_UNKNOWN
            assert unknown.operation.spend_outcome is AccountGapSpendOutcome.UNKNOWN
            assert unknown.operation.failure_code == "sumble_paid_dispatch_unreconciled"

    run_async(scenario())
