"""A same-window re-buy of an already-acquired account-gap field is a governed refusal.

Live defect (2026-08-20, job ``3cc0a4f2``): an earlier job bought ``core.employee_count`` +
``core.hq_location`` in one operation; a later job in the same project run — the observation
window is per *run*, not per job, because that is the anti-double-spend rule — asked for
``core.hq_location`` alone.  ``find_account_gap_operation_for_fields`` matches on exact field-set
equality, so the owning operation was not found, the starter compiled a new one, and the S1
``account_gap_field_no_overlap`` trigger raised.  The raw ``DBAPIError`` escaped as
``execution_failed`` and paused the whole job (``worker_error:DBAPIError``).

That is the channel-2 → channel-1 misclassification this repo keeps extinguishing: a
model-repairable condition ("that field is already bought in this window — read it") surfaced as a
job-killing raw exception.  These tests pin the governed shape and the narrowness of the backstop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.entity_research_tools import (
    EntityResearchGovernedRejection,
    ProviderOperationObservation,
    ProviderOperationReservation,
)
from clue_api.sumble_account_gaps import (
    SumbleAccountGapCoordinator,
    SumbleAccountGapFieldAlreadyAcquired,
    SumbleAccountGapNotEligible,
    SumbleAccountGapOutcome,
    SumbleAccountGapStarter,
)
from clue_api.sumble_entity_research_tools import SumbleAccountSemanticEnrichmentAction
from clue_core import (
    AccountGapFieldPlan,
    AccountGapOperation,
    AccountGapOperationId,
    AccountGapOperationState,
    AccountGapSpendOutcome,
    ClaimId,
    EntityId,
    ProjectRunId,
    new_account_gap_operation_id,
)
from clue_core.entity_research import (
    FieldSourceAuthority,
    GovernedResearchToolRequest,
    ResearchSubjectType,
)
from clue_research.durable import (
    AccountGapFieldWindowConflict,
    list_account_gap_field_results,
    reserve_account_gap_operation,
)
from clue_research.resolvers.sumble import (
    ORGANIZATIONS_SOURCE_KEY,
    SumbleClient,
    SumbleCreditBudget,
)
from clue_storage import FsStorage
from tests.api.test_sumble_account_gaps_s1 import _seed_selected_high_tier_account
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_EMPLOYEE = "core.employee_count"
_HQ = "core.hq_location"
_INDUSTRY = "core.industry"


class _HeadcountOnlySumbleHttp:
    """The pinned v9 organization action answers headcount and knows no headquarters country."""

    def __init__(self, domain: str) -> None:
        self.domain = domain
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> object:
        self.calls.append({"url": url, **kwargs})
        if not url.endswith("/organizations"):
            raise AssertionError(f"unexpected Sumble URL: {url}")
        return {
            "id": "window-reacquisition-org",
            "credits_used": 2,
            "credits_remaining": 998,
            "organizations": [
                {
                    "input": {"url": self.domain},
                    "attributes": {
                        "id": 1726684,
                        "name": "Insight Health AI",
                        "url": self.domain,
                        "sumble_url": "https://sumble.com/l/org/insight-health-ai",
                        "employee_count": 240,
                    },
                    "entities": [],
                }
            ],
            "matched_count": 1,
            "total": 1,
        }


def _starter(
    *,
    storage: FsStorage,
    conn_factory: Any,
    http: _HeadcountOnlySumbleHttp,
) -> SumbleAccountGapStarter:
    def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
        return SumbleClient(
            api_key=SecretStr("fixture"),
            budget=SumbleCreditBudget(maximum=maximum),
            http=http,
            cents_per_credit=cents,
        )

    coordinator = SumbleAccountGapCoordinator(
        api_key=SecretStr("fixture"),
        storage=storage,
        cents_per_credit=Decimal("0.5"),
        conn_factory=conn_factory,
        client_factory=client_factory,
    )
    return SumbleAccountGapStarter(
        coordinator=coordinator,
        storage=storage,
        cents_per_credit=Decimal("0.5"),
        conn_factory=conn_factory,
    )


def test_same_window_reacquisition_of_a_bought_field_refuses_without_spend_or_state(
    tmp_path: Path,
) -> None:
    """The exact live shape: a different field set overlapping an already-bought field.

    The first operation buys headcount + HQ; the provider answers headcount only, so HQ settles as
    an honest ``confirmed_missing``.  A later request for HQ alone therefore passes the §6.3(a)
    freshness ladder (the field really is missing) and would previously have driven straight into
    the durable ``account_gap_field_no_overlap`` trigger.  It must instead come back as the
    model-repairable refusal, naming HQ, with no new operation row and no new provider call.
    """

    async def scenario() -> None:
        workspace_id = "ws-gap-window-reacquisition"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            http = _HeadcountOnlySumbleHttp("insighthealth.ai")
            starter = _starter(storage=storage, conn_factory=same_connection, http=http)

            first = await starter.start(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=EntityId(ready.account_id),
                field_expected_value_credits={_EMPLOYEE: Decimal(5), _HQ: Decimal(5)},
                provider_credit_cap=3,
                allow_unbounded_tech=False,
            )
            assert first.outcome is SumbleAccountGapOutcome.COMPLETED
            settled = {
                str(row.field_key): row.state.value
                for row in await list_account_gap_field_results(
                    conn,
                    workspace_id=workspace_id,
                    operation_id=first.operation.operation_id,
                )
            }
            assert settled == {_EMPLOYEE: "resolved", _HQ: "confirmed_missing"}
            calls_after_first = len(http.calls)
            operations_after_first = (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one()

            with pytest.raises(SumbleAccountGapFieldAlreadyAcquired) as refusal:
                await starter.start(
                    workspace_id=workspace_id,
                    project_run_id=ProjectRunId(started.project_run_id),
                    account_id=EntityId(ready.account_id),
                    field_expected_value_credits={_HQ: Decimal(5)},
                    provider_credit_cap=3,
                    allow_unbounded_tech=False,
                )
            # Model-repairable species: the tool layer converts exactly this class into a governed
            # rejection tool message, never a job suspension.
            assert isinstance(refusal.value, SumbleAccountGapNotEligible)
            assert _HQ in str(refusal.value)
            # The refusal must name the OWNING operation's exact field set, because re-asking that
            # exact set is the one legal move that makes this pair terminal (it replays, zero
            # spend). Naming only the bought field left the live agent thrashing: it read state,
            # re-asked subsets, and never discovered the exit.
            assert f"[{_EMPLOYEE}, {_HQ}]" in str(refusal.value)
            assert "replay" in str(refusal.value).lower()

            # A partly-overlapping set is refused whole — the agent re-asks for the remainder —
            # and the message names only the fields this window actually bought.
            with pytest.raises(SumbleAccountGapFieldAlreadyAcquired) as mixed:
                await starter.start(
                    workspace_id=workspace_id,
                    project_run_id=ProjectRunId(started.project_run_id),
                    account_id=EntityId(ready.account_id),
                    field_expected_value_credits={_HQ: Decimal(5), _INDUSTRY: Decimal(5)},
                    provider_credit_cap=3,
                    allow_unbounded_tech=False,
                )
            assert _HQ in str(mixed.value)
            assert f"[{_EMPLOYEE}, {_HQ}]" in str(mixed.value)
            # ``core.industry`` is unbought, so it is never listed as already acquired — it only
            # appears inside the owning set if that set contains it, which it does not.
            assert f"acquired in this observation window: {_HQ} " in str(mixed.value)

            assert len(http.calls) == calls_after_first
            assert (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one() == operations_after_first

    run_async(scenario())


def _subset_operation(
    stored: AccountGapOperation,
    *,
    plans: tuple[AccountGapFieldPlan, ...],
) -> AccountGapOperation:
    request = stored.request.model_copy(
        update={
            "fields": plans,
            "expected_value_credits": sum(
                (plan.expected_value_credits for plan in plans), Decimal(0)
            ),
        }
    )
    return AccountGapOperation(
        operation_id=new_account_gap_operation_id(),
        request=request,
        request_fingerprint=request.request_fingerprint,
        state=AccountGapOperationState.PLANNED,
        spend_outcome=AccountGapSpendOutcome.NOT_DISPATCHED,
        input_artifact_key=stored.input_artifact_key,
        provider_units_reserved=Decimal(1),
        cost_cents_reserved=Decimal(0),
        unbounded_call_approved=False,
    )


def test_durable_reservation_converts_only_the_window_trigger_and_re_raises_the_rest(
    tmp_path: Path,
) -> None:
    """The backstop under a lost pre-check race is narrow, not a blanket DBAPIError conversion.

    Two concurrent creates can both pass the pre-check, so the trigger stays the authority and the
    reservation converts *its* ``P0001`` into a typed, model-repairable conflict.  Every other
    database error on the same statement — here the ``account_gap_result_claim_lineage`` trigger,
    an integrity violation nobody may talk past — still propagates and still suspends.
    """

    async def scenario() -> None:
        workspace_id = "ws-gap-window-race"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            http = _HeadcountOnlySumbleHttp("insighthealth.ai")
            starter = _starter(storage=storage, conn_factory=same_connection, http=http)
            first = await starter.start(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=EntityId(ready.account_id),
                field_expected_value_credits={_EMPLOYEE: Decimal(5), _HQ: Decimal(5)},
                provider_credit_cap=3,
                allow_unbounded_tech=False,
            )
            assert first.outcome is SumbleAccountGapOutcome.COMPLETED
            stored = first.operation
            hq_plan = next(
                plan for plan in stored.request.fields if str(plan.field_key) == _HQ
            ).model_copy(update={"basis_claim_ids": ()})
            operations_before = (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one()

            with pytest.raises(AccountGapFieldWindowConflict) as conflict:
                async with conn.begin_nested():
                    await reserve_account_gap_operation(
                        conn,
                        operation=_subset_operation(stored, plans=(hq_plan,)),
                        snapshots=(),
                        enforce_budget=False,
                    )
            assert _HQ in str(conflict.value)
            assert (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one() == operations_before

            # Same statement, different RAISE: an unrelated lineage violation is NOT converted.
            unrelated = AccountGapFieldPlan(
                field_key="core.industry",
                source_key=ORGANIZATIONS_SOURCE_KEY,
                reason=hq_plan.reason,
                expected_value_credits=Decimal(5),
                basis_claim_ids=(ClaimId(uuid4()),),
            )
            with pytest.raises(DBAPIError) as raw:
                async with conn.begin_nested():
                    await reserve_account_gap_operation(
                        conn,
                        operation=_subset_operation(stored, plans=(unrelated,)),
                        snapshots=(),
                        enforce_budget=False,
                    )
            assert not isinstance(raw.value, AccountGapFieldWindowConflict)
            assert "basis claim lineage mismatch" in str(raw.value)
            assert (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one() == operations_before

    run_async(scenario())


_SHA = "0" * 64


def _organizations_request(
    account_id: EntityId,
    *,
    label: str,
    field_keys: tuple[str, ...] = (_HQ,),
) -> GovernedResearchToolRequest:
    return GovernedResearchToolRequest(
        research_run_id=uuid4(),
        job_id=uuid4(),
        subject_type=ResearchSubjectType.ACCOUNT,
        target_entity_id=account_id,
        agent_turn_id=uuid4(),
        agent_execution_id=uuid4(),
        tool_call_id=uuid4(),
        tool_name="enrich_account",
        tool_version=1,
        tool_input_sha256=_SHA,
        field_plan_ref=f"account-field-plan:{label}",
        source_plan_ref=f"effective-source-plans:{label}",
        field_keys=field_keys,
        source_keys=(ORGANIZATIONS_SOURCE_KEY,),
        field_source_authority=tuple(
            FieldSourceAuthority(field_key=key, source_keys=(ORGANIZATIONS_SOURCE_KEY,))
            for key in field_keys
        ),
        questions=("Where is this account headquartered?",),
        budget_reservation_key=f"{label}-budget",
        idempotency_key=f"{label}-idempotency",
    )


def test_the_m8d_action_renders_a_recoverable_rejection_and_repeats_it_on_replay(
    tmp_path: Path,
) -> None:
    """The governed shape the paused job actually needs, on the first call and on its replay.

    A checkpoint-replayed call re-executes this exact action, so the refusal must land again as a
    rendered error tool message the model reads — never a fresh suspension, and never a second
    operation row. Deterministic because the pre-check is a durable read, not turn state.
    """

    async def scenario() -> None:
        workspace_id = "ws-gap-window-governed"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )
            account_id = EntityId(ready.account_id)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            http = _HeadcountOnlySumbleHttp("insighthealth.ai")
            starter = _starter(storage=storage, conn_factory=same_connection, http=http)
            first = await starter.start(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=account_id,
                field_expected_value_credits={_EMPLOYEE: Decimal(5), _HQ: Decimal(5)},
                provider_credit_cap=3,
                allow_unbounded_tech=False,
            )
            assert first.outcome is SumbleAccountGapOutcome.COMPLETED
            calls_after_first = len(http.calls)
            operations_after_first = (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one()

            action = SumbleAccountSemanticEnrichmentAction(
                starter=starter,
                storage=storage,
                conn_factory=same_connection,
                workspace_id=workspace_id,
                project_id=started.project_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=account_id,
                field_expected_value_credits={_HQ: Decimal(5)},
                provider_credit_cap=3,
            )

            async def never_dispatched(reservation: object) -> object:
                raise AssertionError("an already-acquired field must never reserve or dispatch")

            for label in ("first-call", "checkpoint-replay"):
                with pytest.raises(EntityResearchGovernedRejection) as refusal:
                    await action.execute(  # type: ignore[arg-type]
                        _organizations_request(account_id, label=label),
                        before_dispatch=never_dispatched,
                        settle_terminal=never_dispatched,
                    )
                assert refusal.value.code == "account_gap_field_already_acquired"
                assert _HQ in refusal.value.detail
                rendered = refusal.value.render()
                assert '"recoverable":true' in rendered
                # The exit must survive rendering + the 1000-char detail clamp: the model reads
                # this string and nothing else.
                assert f"[{_EMPLOYEE}, {_HQ}]" in rendered
                assert "replay its durable outcome" in rendered
                assert len(http.calls) == calls_after_first
                assert (
                    await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
                ).scalar_one() == operations_after_first

    run_async(scenario())


async def _bind_provider_operation(
    conn: AsyncConnection,
    reservation: ProviderOperationReservation,
) -> ProviderOperationObservation:
    """The minimum of what production's causation store does before a dispatch.

    ``_persist_projection`` FKs its projection to ``entity_research_provider_operation``, so the
    owning call must leave that row behind exactly as ``bind_before_dispatch`` would; the
    observation bookkeeping around it is not what this test is about.
    """

    await conn.execute(
        text(
            "INSERT INTO entity_research_provider_operation (operation_ref, provider_kind, "
            "workspace_id, project_id, project_run_id, subject_type, target_entity_id, "
            "source_key, field_keys, request_artifact_ref, reserved_at, dispatched_at) VALUES "
            "(:operation_ref, :provider_kind, :workspace_id, :project_id, :project_run_id, "
            ":subject_type, :target_entity_id, :source_key, :field_keys, :request_artifact_ref, "
            ":reserved_at, :dispatched_at) ON CONFLICT (operation_ref) DO NOTHING"
        ),
        {
            "operation_ref": reservation.operation_ref,
            "provider_kind": reservation.provider_kind,
            "workspace_id": reservation.workspace_id,
            "project_id": reservation.project_id,
            "project_run_id": reservation.project_run_id,
            "subject_type": reservation.subject_type.value,
            "target_entity_id": reservation.target_entity_id,
            "source_key": reservation.source_key,
            "field_keys": list(reservation.field_keys),
            "request_artifact_ref": reservation.request_artifact_ref,
            "reserved_at": reservation.reserved_at,
            "dispatched_at": reservation.dispatched_at,
        },
    )
    return ProviderOperationObservation(
        observation_id=uuid4(),
        tool_request_id=uuid4(),
        operation_ref=reservation.operation_ref,
        workspace_id=reservation.workspace_id,
        disposition=reservation.observation_disposition.value,
        created_at=datetime.now(UTC),
    )


def test_the_exact_owning_field_set_still_replays_and_settles_under_the_new_job(
    tmp_path: Path,
) -> None:
    """The exit the refusal points at, proven end to end — this is the live wedge's repair.

    ``core.hq_location`` settled ``conflict``/unsatisfied under an operation that bought it
    together with ``core.employee_count``, so the pair stays OUTSTANDING for a later job and
    ``assess_account_coverage`` cannot close while it is unattempted. Re-asking the owning
    operation's *exact* field set rejoins it (``find_account_gap_operation_for_fields``) and
    replays zero-spend, writing a result under the new job's own tool request — which is what
    makes the pair terminal. The window pre-check must never stand in front of that: it lives in
    ``compile_sumble_account_gap_preflight``, which the exact-set rejoin returns before reaching.

    Tolerant of both projection-serving paths (equal recompute, or the stored projection served
    because a recompute differs) — that admitted history is correct either way.
    """

    async def scenario() -> None:
        workspace_id = "ws-gap-window-exact-set"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )
            account_id = EntityId(ready.account_id)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            http = _HeadcountOnlySumbleHttp("insighthealth.ai")
            starter = _starter(storage=storage, conn_factory=same_connection, http=http)
            action = SumbleAccountSemanticEnrichmentAction(
                starter=starter,
                storage=storage,
                conn_factory=same_connection,
                workspace_id=workspace_id,
                project_id=started.project_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=account_id,
                field_expected_value_credits={_EMPLOYEE: Decimal(5), _HQ: Decimal(5)},
                provider_credit_cap=3,
            )

            async def bind(reservation: ProviderOperationReservation) -> object:
                return await _bind_provider_operation(conn, reservation)

            # The owning job buys the pair.
            owning_drafts = await action.execute(  # type: ignore[arg-type]
                _organizations_request(account_id, label="owning-job", field_keys=(_EMPLOYEE, _HQ)),
                before_dispatch=bind,
                settle_terminal=bind,
            )
            assert len(owning_drafts) == 1
            owning_ref = owning_drafts[0].operation.operation_ref
            # The unsatisfied half: bought, terminal on the ledger, still no usable answer — the
            # exact live shape that keeps the pair OUTSTANDING for the next job.
            operation_id = AccountGapOperationId(UUID(owning_ref.rsplit(":", 1)[-1]))
            settled = {
                str(row.field_key): row.state.value
                for row in await list_account_gap_field_results(
                    conn, workspace_id=workspace_id, operation_id=operation_id
                )
            }
            assert settled[_HQ] == "confirmed_missing"
            calls_after_owning = len(http.calls)
            operations_after_owning = (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one()

            # A LATER job asking for the exact owning set is not refused: it replays zero-spend
            # and lands its own result draft, which is what makes both pairs terminal.
            async def never_dispatched(reservation: object) -> object:
                raise AssertionError("replaying a settled operation must not dispatch")

            replay_drafts = await action.execute(  # type: ignore[arg-type]
                _organizations_request(account_id, label="later-job", field_keys=(_EMPLOYEE, _HQ)),
                before_dispatch=never_dispatched,
                settle_terminal=never_dispatched,
            )
            assert len(replay_drafts) == 1
            assert replay_drafts[0].operation.operation_ref == owning_ref
            assert set(replay_drafts[0].requested_field_keys) == {_EMPLOYEE, _HQ}
            assert {str(item.field_key) for item in replay_drafts[0].fields} == {_EMPLOYEE, _HQ}
            assert len(http.calls) == calls_after_owning
            assert (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one() == operations_after_owning

            # And the starter-level guarantee the above rides on, asserted directly.
            replayed = await starter.start(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=account_id,
                field_expected_value_credits={_EMPLOYEE: Decimal(5), _HQ: Decimal(5)},
                provider_credit_cap=3,
                allow_unbounded_tech=False,
            )
            assert replayed.outcome is SumbleAccountGapOutcome.REPLAYED
            assert len(http.calls) == calls_after_owning

    run_async(scenario())
