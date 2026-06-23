"""M8A.2 — the ``CampaignPhase.DEEP`` handler, driven entirely by fakes (no DB).

These prove the handler *policy* around the M8A.1 orchestrator: it resolves the high-tier set and
drives the scheduler with the per-account sequence bound as ``run_one``; it isolates a single
failing account (a raise or a not-found short-circuit) so the batch survives and the row is marked
FAILED; it maps a ``RUN``-scope ``GRACEFUL_STOP`` to ``PhaseResult(PAUSED)`` and an ``ACCOUNT``
``DENY`` to a partial-but-COMPLETED account; its payload is references-only (no claim bodies); and
an empty high-tier set is a clean no-op. Registration is asserted at the registry seam the state
machine dispatches through (the full ``advance()`` path is integration-tested at M8A.6).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from decimal import Decimal
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from clue_research.api.deep import (
    AccountDeepResult,
    DeepPhaseHandler,
    HighTierResolver,
    deep_account_run_id,
)
from clue_research.core import (
    BudgetVerdict,
    CampaignPhase,
    CampaignRunId,
    EntityId,
    Persona,
    PhaseContext,
    PhaseHandler,
    PhaseStatus,
    RunId,
    WorkerStatus,
    new_campaign_run_id,
    new_claim_id,
    new_entity_id,
)
from clue_research.durable import AccountRunSubPhase, AccountSpec, PhaseHandlerRegistry
from clue_research.profiling import (
    AccountProfileResult,
    CommitteeResult,
    ContactProfileResult,
)
from clue_research.profiling.committee.coverage import estimate_committee_coverage
from clue_research.profiling.committee.results import CommitteeMemberRef
from clue_research.profiling.committee.stopping import CommitteeStopReason
from tests.db.conftest import run_async

# --- a result that carries the M8A.3 budget-stop signal ----------------------


class _ResultWithStop(AccountDeepResult):
    """``AccountDeepResult`` + the ``budget_stop`` field M8A.3 adds — so the budget-verdict mapping
    is tested on this base (M8A.1's ``AccountDeepResult`` forbids extra fields). A subclass field is
    part of the subclass schema, so it is not an ``extra``."""

    budget_stop: BudgetVerdict | None = None


# --- fakes -------------------------------------------------------------------


def _member(contact_id: EntityId) -> CommitteeMemberRef:
    return CommitteeMemberRef(
        contact_entity_id=contact_id,
        persona=Persona.CHAMPION,
        role_on_committee=Persona.CHAMPION.value,
        role_confidence=0.8,
        role_plausible=True,
        discovery_claim_id=new_claim_id(),
        role_claim_id=new_claim_id(),
        persona_claim_id=new_claim_id(),
    )


def _result_kwargs(
    *,
    account_run_id: RunId,
    entity_id: EntityId,
    tier: str = "top",
    cost: Decimal = Decimal("10"),
    n_members: int = 2,
    sub_phase: AccountRunSubPhase = AccountRunSubPhase.CONTACTS_COMPLETE,
) -> dict[str, Any]:
    members = tuple(_member(new_entity_id()) for _ in range(n_members))
    coverage = estimate_committee_coverage(
        channels_searched=("linkedin",),
        all_channels=("linkedin", "conference"),
        stopping_reason=CommitteeStopReason.EXHAUSTED,
        candidates_seen=n_members,
        admitted=n_members,
    )
    committee = CommitteeResult(
        account_entity_id=entity_id,
        members=members,
        coverage=coverage,
        cost_cents=Decimal("3"),
        admitted=n_members,
    )
    contacts = tuple(
        ContactProfileResult(
            contact_entity_id=member.contact_entity_id,
            account_entity_id=entity_id,
            profile_claims=(),
        )
        for member in members
    )
    account = AccountProfileResult(
        account_entity_id=entity_id,
        tier=tier,
        run_id=account_run_id,
        status=WorkerStatus.OK,
        claim_refs=(new_claim_id(),),
    )
    return {
        "account_run_id": account_run_id,
        "entity_id": entity_id,
        "tier": tier,
        "account": account,
        "committee": committee,
        "contacts": contacts,
        "cost_cents": cost,
        "sub_phase": sub_phase,
    }


def _result(**over: Any) -> AccountDeepResult:
    return AccountDeepResult(**_result_kwargs(**over))


def _stop_result(verdict: BudgetVerdict, **over: Any) -> _ResultWithStop:
    return _ResultWithStop(**_result_kwargs(**over), budget_stop=verdict)


def _not_found_result(
    *, account_run_id: RunId, entity_id: EntityId, tier: str = "top"
) -> AccountDeepResult:
    """The orchestrator's not-found short-circuit: FAILED account, no committee, marker un-set."""
    account = AccountProfileResult(
        account_entity_id=entity_id, tier=tier, run_id=account_run_id, status=WorkerStatus.FAILED
    )
    return AccountDeepResult(
        account_run_id=account_run_id,
        entity_id=entity_id,
        tier=tier,
        account=account,
        cost_cents=Decimal("1"),
        sub_phase=None,
    )


class FakeOrchestrator:
    """A per-account sequence fake: returns a configured result per entity, or raises."""

    def __init__(self) -> None:
        self._results: dict[EntityId, AccountDeepResult] = {}
        self._raise: set[EntityId] = set()
        self.calls: list[EntityId] = []

    def returns(self, entity_id: EntityId, result: AccountDeepResult) -> None:
        self._results[entity_id] = result

    def raises(self, entity_id: EntityId) -> None:
        self._raise.add(entity_id)

    async def run_one(
        self, spec: AccountSpec, *, campaign_run_id: CampaignRunId
    ) -> AccountDeepResult:
        self.calls.append(spec.entity_id)
        if spec.entity_id in self._raise:
            raise RuntimeError("synthetic account failure")
        return self._results[spec.entity_id]


class FakeScheduler:
    """Mirrors :meth:`AccountScheduler.run_accounts`'s ``run_one`` path: invoke the callback per
    spec, in input order, and return the outcomes (the handler's ``_isolated`` wrapper never
    raises, so the gather/sequence distinction does not matter for these assertions)."""

    def __init__(self) -> None:
        self.specs: tuple[AccountSpec, ...] = ()
        self.campaign_run_id: CampaignRunId | None = None
        self.checkpointer: Any = None

    async def run_accounts(
        self,
        specs: Any,
        *,
        campaign_run_id: CampaignRunId,
        checkpointer: BaseCheckpointSaver[Any],
        run_one: Any,
    ) -> list[Any]:
        self.specs = tuple(specs)
        self.campaign_run_id = campaign_run_id
        self.checkpointer = checkpointer
        return [await run_one(spec) for spec in self.specs]


class FakeFinalizeFailed:
    """Records the account-run ids the handler marks FAILED and returns a configured recovered cost
    (the production seam reads the row's persisted ``cost_cents`` before flipping it FAILED)."""

    def __init__(self, *, recovered_cost: Decimal = Decimal(0)) -> None:
        self.failed: list[RunId] = []
        self._recovered_cost = recovered_cost

    async def __call__(self, account_run_id: RunId) -> Decimal:
        self.failed.append(account_run_id)
        return self._recovered_cost


class FakeCheckpointerFactory:
    """Yields an in-memory saver and counts how many times it is opened."""

    def __init__(self) -> None:
        self.opened = 0

    def __call__(self) -> AbstractAsyncContextManager[BaseCheckpointSaver[Any]]:
        return self._open()

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[BaseCheckpointSaver[Any]]:
        self.opened += 1
        yield InMemorySaver()


def _resolver(specs: Sequence[AccountSpec]) -> HighTierResolver:
    async def _f(ctx: PhaseContext) -> Sequence[AccountSpec]:
        return specs

    return _f


def _ctx(campaign: CampaignRunId) -> PhaseContext:
    return PhaseContext(
        campaign_run_id=campaign,
        phase=CampaignPhase.DEEP,
        client_id="client-1",
        icp_key="icp-a",
        icp_version=1,
    )


def _spec(entity_id: EntityId, *, tier: str = "top") -> AccountSpec:
    return AccountSpec(entity_id=entity_id, tier=tier, tenant_id="client-1")


def _handler(
    *,
    scheduler: Any,
    orchestrator: Any,
    specs: Sequence[AccountSpec],
    finalize_failed: FakeFinalizeFailed | None = None,
    checkpointer_factory: FakeCheckpointerFactory | None = None,
) -> DeepPhaseHandler:
    return DeepPhaseHandler(
        scheduler=scheduler,
        orchestrator=orchestrator,
        high_tier_resolver=_resolver(specs),
        checkpointer_factory=checkpointer_factory or FakeCheckpointerFactory(),
        finalize_failed_account=finalize_failed or FakeFinalizeFailed(),
    )


def _all_keys(obj: Any) -> set[str]:
    """Every dict key anywhere in a nested structure (for the no-blob-leak assertion)."""
    keys: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            keys.add(key)
            keys |= _all_keys(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            keys |= _all_keys(value)
    return keys


# --- tests -------------------------------------------------------------------


def test_handler_conforms_to_protocol_and_registers() -> None:
    handler = _handler(scheduler=FakeScheduler(), orchestrator=FakeOrchestrator(), specs=())
    assert isinstance(handler, PhaseHandler)
    assert handler.phase is CampaignPhase.DEEP
    # registering it makes the state machine's dispatch table resolve DEEP (no NoPhaseHandler error)
    registry = PhaseHandlerRegistry()
    assert registry.get(CampaignPhase.DEEP) is None
    registry.register(handler)
    assert registry.get(CampaignPhase.DEEP) is handler
    assert CampaignPhase.DEEP in registry.phases()


def test_resolves_high_tier_set_and_processes_every_account() -> None:
    campaign = new_campaign_run_id()
    e1, e2 = new_entity_id(), new_entity_id()
    specs = (_spec(e1, tier="top"), _spec(e2, tier="high"))
    orch = FakeOrchestrator()
    orch.returns(
        e1,
        _result(account_run_id=deep_account_run_id(campaign, e1), entity_id=e1, cost=Decimal("10")),
    )
    orch.returns(
        e2,
        _result(account_run_id=deep_account_run_id(campaign, e2), entity_id=e2, cost=Decimal("7")),
    )
    sched = FakeScheduler()
    handler = _handler(scheduler=sched, orchestrator=orch, specs=specs)

    async def _run() -> None:
        result = await handler.run(_ctx(campaign))
        assert result.status is PhaseStatus.COMPLETED
        assert result.accounts_processed == 2
        assert result.cost_cents == Decimal("17")
        assert result.payload["deep_count"] == 2
        assert result.payload["accounts_failed"] == 0
        # the resolved specs reached the scheduler under the run's campaign id
        assert sched.specs == specs
        assert sched.campaign_run_id == campaign
        accounts = result.payload["accounts"]
        assert isinstance(accounts, list)
        assert {a["account_entity_id"] for a in accounts} == {str(e1), str(e2)}
        assert all(a["status"] == "completed" for a in accounts)

    run_async(_run())


def test_one_account_raising_is_isolated_and_marked_failed() -> None:
    campaign = new_campaign_run_id()
    e1, e2 = new_entity_id(), new_entity_id()
    specs = (_spec(e1), _spec(e2))
    orch = FakeOrchestrator()
    orch.raises(e1)
    orch.returns(
        e2,
        _result(account_run_id=deep_account_run_id(campaign, e2), entity_id=e2, cost=Decimal("4")),
    )
    # the crashed account had already persisted 2c before the fault — finalize recovers it
    marker = FakeFinalizeFailed(recovered_cost=Decimal("2"))
    handler = _handler(
        scheduler=FakeScheduler(), orchestrator=orch, specs=specs, finalize_failed=marker
    )

    async def _run() -> None:
        result = await handler.run(_ctx(campaign))
        # the batch survives one account's fault
        assert result.status is PhaseStatus.COMPLETED
        assert result.accounts_processed == 1
        assert result.payload["accounts_failed"] == 1
        # the crashed account's partial spend (2) is recovered, not lost → 4 + 2 (honest burn-down)
        assert result.cost_cents == Decimal("6")
        # the raised account's run was marked FAILED via the injected seam (deterministic id)
        assert marker.failed == [deep_account_run_id(campaign, e1)]
        by_entity = {a["account_entity_id"]: a for a in result.payload["accounts"]}
        assert by_entity[str(e1)]["status"] == "failed"
        assert by_entity[str(e1)]["cost_cents"] == "2"  # recovered partial cost in the manifest
        assert by_entity[str(e2)]["status"] == "completed"

    run_async(_run())


def test_not_found_account_is_recorded_failed() -> None:
    campaign = new_campaign_run_id()
    e1 = new_entity_id()
    specs = (_spec(e1),)
    orch = FakeOrchestrator()
    orch.returns(
        e1, _not_found_result(account_run_id=deep_account_run_id(campaign, e1), entity_id=e1)
    )
    marker = FakeFinalizeFailed()
    handler = _handler(
        scheduler=FakeScheduler(), orchestrator=orch, specs=specs, finalize_failed=marker
    )

    async def _run() -> None:
        result = await handler.run(_ctx(campaign))
        # a not-found short-circuit (no exception, sub_phase un-advanced) is still recorded FAILED
        assert result.status is PhaseStatus.COMPLETED
        assert result.accounts_processed == 0
        assert result.payload["accounts_failed"] == 1
        assert marker.failed == [deep_account_run_id(campaign, e1)]
        # the not-found result carries the accurate cost (1) — the handler uses it, not the DB read
        assert result.cost_cents == Decimal("1")
        accounts = result.payload["accounts"]
        assert isinstance(accounts, list)
        assert accounts[0]["status"] == "failed"
        assert accounts[0]["cost_cents"] == "1"

    run_async(_run())


def test_run_graceful_stop_pauses_the_phase() -> None:
    campaign = new_campaign_run_id()
    e1, e2 = new_entity_id(), new_entity_id()
    specs = (_spec(e1), _spec(e2))
    orch = FakeOrchestrator()
    orch.returns(
        e1,
        _result(account_run_id=deep_account_run_id(campaign, e1), entity_id=e1, cost=Decimal("5")),
    )
    orch.returns(
        e2,
        _stop_result(
            BudgetVerdict.GRACEFUL_STOP,
            account_run_id=deep_account_run_id(campaign, e2),
            entity_id=e2,
            cost=Decimal("3"),
        ),
    )
    handler = _handler(scheduler=FakeScheduler(), orchestrator=orch, specs=specs)

    async def _run() -> None:
        result = await handler.run(_ctx(campaign))
        # a RUN-scope graceful stop suspends the phase; the run re-enters DEEP and resumes
        assert result.status is PhaseStatus.PAUSED
        # both accounts did work and are counted (not failed)
        assert result.accounts_processed == 2
        assert result.payload["accounts_failed"] == 0
        assert result.cost_cents == Decimal("8")
        by_entity = {a["account_entity_id"]: a for a in result.payload["accounts"]}
        assert by_entity[str(e2)]["status"] == "partial"

    run_async(_run())


def test_account_deny_is_partial_completed_not_paused() -> None:
    campaign = new_campaign_run_id()
    e1 = new_entity_id()
    specs = (_spec(e1),)
    orch = FakeOrchestrator()
    orch.returns(
        e1,
        _stop_result(
            BudgetVerdict.DENY,
            account_run_id=deep_account_run_id(campaign, e1),
            entity_id=e1,
            cost=Decimal("6"),
        ),
    )
    handler = _handler(scheduler=FakeScheduler(), orchestrator=orch, specs=specs)

    async def _run() -> None:
        result = await handler.run(_ctx(campaign))
        # an ACCOUNT-scope DENY is partial coverage, not a pause and not a failure
        assert result.status is PhaseStatus.COMPLETED
        assert result.accounts_processed == 1
        assert result.payload["accounts_failed"] == 0
        accounts = result.payload["accounts"]
        assert isinstance(accounts, list)
        assert accounts[0]["status"] == "partial"

    run_async(_run())


def test_payload_is_references_only_no_claim_bodies() -> None:
    campaign = new_campaign_run_id()
    e1 = new_entity_id()
    specs = (_spec(e1),)
    orch = FakeOrchestrator()
    orch.returns(
        e1, _result(account_run_id=deep_account_run_id(campaign, e1), entity_id=e1, n_members=3)
    )
    handler = _handler(scheduler=FakeScheduler(), orchestrator=orch, specs=specs)

    async def _run() -> None:
        result = await handler.run(_ctx(campaign))
        keys = _all_keys(result.payload)
        # no claim bodies anywhere in the payload (references only — substrate §5b)
        assert "value_json" not in keys
        assert "evidence_span" not in keys
        assert "profile_claims" not in keys
        # the whole payload is JSON-serialisable (no model objects / Decimals leaked)
        json.dumps(result.payload)
        accounts = result.payload["accounts"]
        assert isinstance(accounts, list)
        acct = accounts[0]
        assert len(acct["committee_member_ids"]) == 3
        assert all(isinstance(mid, str) for mid in acct["committee_member_ids"])
        assert acct["coverage"] is not None
        # the M8A.5 per-section claim-id index reaches the payload — ids only, never a claim body
        references_index = acct["references_index"]
        assert isinstance(references_index, dict)
        all_ids = [cid for ids in references_index.values() for cid in ids]
        assert len(all_ids) >= 1
        assert all(isinstance(cid, str) for cid in all_ids)

    run_async(_run())


def test_empty_high_tier_set_is_a_completed_no_op() -> None:
    sched = FakeScheduler()
    handler = _handler(scheduler=sched, orchestrator=FakeOrchestrator(), specs=())

    async def _run() -> None:
        result = await handler.run(_ctx(new_campaign_run_id()))
        assert result.status is PhaseStatus.COMPLETED
        assert result.accounts_processed == 0
        assert result.cost_cents == Decimal(0)
        assert result.payload["deep_count"] == 0
        assert result.payload["accounts"] == []
        # the scheduler is never driven when there is nothing to research
        assert sched.specs == ()
        assert sched.campaign_run_id is None

    run_async(_run())


def test_checkpointer_factory_is_opened_for_the_batch() -> None:
    campaign = new_campaign_run_id()
    e1 = new_entity_id()
    specs = (_spec(e1),)
    orch = FakeOrchestrator()
    orch.returns(e1, _result(account_run_id=deep_account_run_id(campaign, e1), entity_id=e1))
    sched = FakeScheduler()
    factory = FakeCheckpointerFactory()
    handler = _handler(
        scheduler=sched, orchestrator=orch, specs=specs, checkpointer_factory=factory
    )

    async def _run() -> None:
        await handler.run(_ctx(campaign))
        assert factory.opened == 1
        assert isinstance(sched.checkpointer, InMemorySaver)

    run_async(_run())


def test_resumed_account_without_committee_lists_members_from_contacts() -> None:
    # A run resumed at COMMITTEE_DISCOVERED returns committee=None (not re-materialised) with the
    # profiled contacts populated — the manifest must source admitted member ids from contacts and
    # carry no coverage (the committee result is not reloaded on resume). The orchestrator proves it
    # returns this shape; this proves the handler consumes it.
    campaign = new_campaign_run_id()
    e1 = new_entity_id()
    c1, c2 = new_entity_id(), new_entity_id()
    contacts = tuple(
        ContactProfileResult(contact_entity_id=cid, account_entity_id=e1, profile_claims=())
        for cid in (c1, c2)
    )
    resumed = AccountDeepResult(
        account_run_id=deep_account_run_id(campaign, e1),
        entity_id=e1,
        tier="top",
        account=None,
        committee=None,
        contacts=contacts,
        cost_cents=Decimal("12"),
        sub_phase=AccountRunSubPhase.CONTACTS_COMPLETE,
    )
    orch = FakeOrchestrator()
    orch.returns(e1, resumed)
    handler = _handler(scheduler=FakeScheduler(), orchestrator=orch, specs=(_spec(e1),))

    async def _run() -> None:
        result = await handler.run(_ctx(campaign))
        assert result.status is PhaseStatus.COMPLETED
        assert result.accounts_processed == 1
        assert result.cost_cents == Decimal("12")
        accounts = result.payload["accounts"]
        assert isinstance(accounts, list)
        acct = accounts[0]
        assert acct["status"] == "completed"
        # member ids came from the resumed contacts, not a (None) committee
        assert set(acct["committee_member_ids"]) == {str(c1), str(c2)}
        assert acct["coverage"] is None

    run_async(_run())
