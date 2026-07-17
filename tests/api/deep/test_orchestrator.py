"""M8A.1 — the per-account deep-orchestration sequence, driven entirely by fakes (no DB).

These prove the orchestration *logic*: the ``account → committee → contact`` ordering, the committee
as a hard gate before the contact fan-out, sub-phase resume (a crash at ``committee_discovered``
re-runs neither the account nor the committee), the committee-size cap + intra-account concurrency
bound, and that the account axis carries the ICP spec + tenant as explicit kwargs (never
``ctx.params``) with one deterministic ``run_id`` shared by all three stages.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from clue_config import DeepPhaseConfig, RecursionPolicy
from clue_core import (
    BudgetDecision,
    BudgetScope,
    BudgetVerdict,
    BurnDown,
    CampaignRunId,
    CostCents,
    EntityId,
    Estimate,
    Persona,
    RunId,
    WorkerStatus,
    new_campaign_run_id,
    new_claim_id,
    new_entity_id,
)
from clue_core.enums import ICPCreatedFrom
from clue_core.handoff import ICPSpec
from clue_research.api.deep import (
    AccountDeepOrchestrator,
    StepInfo,
    deep_account_run_id,
)
from clue_research.api.deep.run_io import DeepRunState
from clue_research.durable import AccountRunStatus, AccountRunSubPhase, AccountSpec
from clue_research.profiling import (
    AccountProfileResult,
    CommitteeResult,
    ContactProfileResult,
)
from clue_research.profiling.committee.coverage import estimate_committee_coverage
from clue_research.profiling.committee.results import CommitteeMemberRef
from clue_research.profiling.committee.stopping import CommitteeStopReason
from tests.db.conftest import run_async

# --- fakes -------------------------------------------------------------------


class FakeAccountRunIO:
    """In-memory :class:`~clue_research.api.deep.run_io.AccountRunIO` (no DB).

    Records each ``fold`` and supports ``seed`` to simulate a prior run's persisted resume state
    (sub_phase + references + cost) so the resume path is exercised without a database. ``fold``
    (M8A.4) takes the caller's connection and does **not** write ``cost_cents`` — the budget
    engine's ``record`` is its single writer — so the fake leaves the stored cost untouched."""

    def __init__(self) -> None:
        self.runs: dict[RunId, dict[str, Any]] = {}
        self.saves: list[tuple[AccountRunSubPhase, AccountRunStatus]] = []

    async def ensure(
        self,
        *,
        account_run_id: RunId,
        campaign_run_id: CampaignRunId,
        entity_id: EntityId,
        tier: str,
    ) -> None:
        self.runs.setdefault(
            account_run_id,
            {"sub_phase": None, "references_index": {}, "cost_cents": Decimal(0)},
        )

    async def load(self, account_run_id: RunId) -> DeepRunState:
        row = self.runs.get(account_run_id)
        if row is None:
            return DeepRunState()
        return DeepRunState(
            sub_phase=row["sub_phase"],
            references_index=row["references_index"],
            cost_cents=row["cost_cents"],
        )

    async def fold(
        self,
        conn: Any,
        account_run_id: RunId,
        *,
        references_index: dict[str, list[str]],
        status: AccountRunStatus,
        sub_phase: AccountRunSubPhase,
    ) -> None:
        row = self.runs.setdefault(
            account_run_id,
            {"sub_phase": None, "references_index": {}, "cost_cents": Decimal(0)},
        )
        row["sub_phase"] = sub_phase
        row["references_index"] = dict(references_index)
        self.saves.append((sub_phase, status))

    def seed(
        self,
        run_id: RunId,
        *,
        sub_phase: AccountRunSubPhase,
        references_index: dict[str, list[str]],
        cost_cents: Decimal = Decimal(0),
    ) -> None:
        self.runs[run_id] = {
            "sub_phase": sub_phase,
            "references_index": references_index,
            "cost_cents": cost_cents,
        }


class Recorder:
    """Shared call log across the three worker fakes (proves ordering + per-stage inputs)."""

    def __init__(self) -> None:
        self.order: list[str] = []
        self.account_kwargs: list[dict[str, Any]] = []
        self.committee_kwargs: list[dict[str, Any]] = []
        self.contact_ids: list[EntityId] = []


def make_profile_account(rec: Recorder, *, cost: Decimal = Decimal("5")):
    async def _f(**kwargs: Any) -> AccountProfileResult:
        rec.order.append("account")
        rec.account_kwargs.append(kwargs)
        return AccountProfileResult(
            account_entity_id=kwargs["account_entity_id"],
            tier=kwargs["tier"],
            run_id=kwargs["run_id"],
            status=WorkerStatus.OK,
            claim_refs=(new_claim_id(),),
            cost_cents=cost,
        )

    return _f


def make_failing_profile_account(rec: Recorder):
    """A ``profile_account`` fake that returns FAILED with no aspects — the not-found signature."""

    async def _f(**kwargs: Any) -> AccountProfileResult:
        rec.order.append("account")
        rec.account_kwargs.append(kwargs)
        return AccountProfileResult(
            account_entity_id=kwargs["account_entity_id"],
            tier=kwargs["tier"],
            run_id=kwargs["run_id"],
            status=WorkerStatus.FAILED,
        )

    return _f


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


def make_discover_committee(rec: Recorder, *, n_members: int = 3, cost: Decimal = Decimal("3")):
    async def _f(conn: Any, **kwargs: Any) -> CommitteeResult:
        rec.order.append("committee")
        rec.committee_kwargs.append(kwargs)
        members = tuple(_member(new_entity_id()) for _ in range(n_members))
        coverage = estimate_committee_coverage(
            channels_searched=(),
            all_channels=(),
            stopping_reason=CommitteeStopReason.EXHAUSTED,
            candidates_seen=n_members,
            admitted=n_members,
        )
        return CommitteeResult(
            account_entity_id=kwargs["account_entity_id"],
            members=members,
            coverage=coverage,
            cost_cents=cost,
            admitted=n_members,
        )

    return _f


class FakeProfileContact:
    """A contact-profiling fake that records call order + tracks peak concurrency."""

    def __init__(self, rec: Recorder, *, cost: Decimal = Decimal("2"), delay: float = 0.0) -> None:
        self._rec = rec
        self._cost = cost
        self._delay = delay
        self.in_flight = 0
        self.peak = 0

    async def __call__(
        self, conn: Any, *, contact_entity_id: EntityId, **kwargs: Any
    ) -> ContactProfileResult:
        self._rec.order.append("contact")
        self._rec.contact_ids.append(contact_entity_id)
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
        finally:
            self.in_flight -= 1
        return ContactProfileResult(
            contact_entity_id=contact_entity_id,
            account_entity_id=kwargs["account_entity_id"],
            profile_claims=(),
            cost_cents=self._cost,
        )


class FakeBudgetEngine:
    """A configurable :class:`~clue_core.BudgetEngine` for the admission tests (M8A.3).

    ``check`` returns a scripted sequence of verdicts (falling back to ``default`` — ``ALLOW`` —
    once the script is exhausted) and records every call, so a test can assert the projected
    amount, the scope, and the account keys passed to the cost dial. Only ``check`` matters for the
    admission seam; the rest satisfy the protocol trivially. Default construction admits
    everything, so the M8A.1 ordering/resume tests inject it unchanged. ``raise_after`` makes the
    ``(raise_after+1)``-th ``check`` raise (a Postgres-backed engine can fail mid-admission), so the
    orphaned-task cleanup can be exercised. ``cap_cents`` is echoed back on every decision (0 =
    uncapped), so the M8A.4 reservation guard — which reads ``decision.cap_cents`` — can fire."""

    def __init__(
        self,
        *,
        verdicts: Sequence[BudgetVerdict] = (),
        default: BudgetVerdict = BudgetVerdict.ALLOW,
        raise_after: int | None = None,
        cap_cents: CostCents = Decimal(0),
    ) -> None:
        self._verdicts = list(verdicts)
        self._default = default
        self._raise_after = raise_after
        self._cap = cap_cents
        self.checks: list[dict[str, Any]] = []

    async def check(
        self,
        *,
        scope: BudgetScope,
        projected_cents: CostCents,
        campaign_run_id: CampaignRunId,
        entity_id: EntityId | None = None,
        account_run_id: RunId | None = None,
    ) -> BudgetDecision:
        if self._raise_after is not None and len(self.checks) >= self._raise_after:
            raise RuntimeError("boom: budget engine unavailable")
        verdict = (
            self._verdicts[len(self.checks)]
            if len(self.checks) < len(self._verdicts)
            else self._default
        )
        self.checks.append(
            {
                "scope": scope,
                "projected_cents": projected_cents,
                "campaign_run_id": campaign_run_id,
                "entity_id": entity_id,
                "account_run_id": account_run_id,
            }
        )
        return BudgetDecision(
            verdict=verdict, scope=scope, projected_cents=projected_cents, cap_cents=self._cap
        )

    async def estimate(
        self,
        campaign_run_id: CampaignRunId,
        *,
        discovered_count: int,
        tier_cutoffs: dict[str, float] | None = None,
    ) -> Estimate:
        zero = Decimal(0)
        return Estimate(
            discovered_count=discovered_count,
            projected_deep_count=0,
            estimated_cost_cents=zero,
            cost_per_account_cents=zero,
        )

    async def record(
        self,
        *,
        cost_cents: CostCents,
        scope: BudgetScope,
        campaign_run_id: CampaignRunId,
        entity_id: EntityId | None = None,
        account_run_id: RunId | None = None,
    ) -> None:
        return None

    async def set_campaign_cap(self, campaign_run_id: CampaignRunId, cap_cents: CostCents) -> None:
        return None

    async def burn_down(self, campaign_run_id: CampaignRunId) -> BurnDown:
        zero = Decimal(0)
        return BurnDown(
            spent_cents=zero, estimated_cents=zero, cap_cents=zero, remaining_cents=zero
        )


class FakeExactlyOnceSpend:
    """In-memory :class:`~clue_research.api.deep.spend.ExactlyOnceSpend` (no DB, no ledger).

    Default behaviour: run ``work`` and record its charge exactly once, returning the result + a
    fresh :class:`StepInfo`. ``replay`` maps a step ``key`` → ``(claim_ids, cost)`` to simulate a
    stage that already committed on a prior run — the work is **not** re-run and the charge **not**
    re-recorded (a resumed stage). ``charges`` logs every real (non-replayed) charge so a test can
    assert exactly-once accounting and the per-account keying."""

    def __init__(self, *, replay: dict[str, tuple[tuple[str, ...], Decimal]] | None = None) -> None:
        self._replay = dict(replay or {})
        self.charges: list[dict[str, Any]] = []

    async def run_step(
        self,
        conn: Any,
        *,
        key: str,
        campaign_run_id: CampaignRunId,
        account_run_id: RunId,
        entity_id: EntityId,
        work: Any,
        stale_after: Any = None,
    ) -> tuple[Any, StepInfo]:
        if key in self._replay:
            ids, cost = self._replay[key]
            return None, StepInfo(replayed=True, claim_ids=ids, cost_cents=cost)
        result = await work(conn)
        ids = tuple(str(c) for c in result.claim_refs)
        self.charges.append(
            {
                "key": key,
                "campaign_run_id": campaign_run_id,
                "account_run_id": account_run_id,
                "entity_id": entity_id,
                "cost_cents": result.cost_cents,
            }
        )
        return result, StepInfo(replayed=False, claim_ids=ids, cost_cents=result.cost_cents)

    async def recorded(self, conn: Any, key: str) -> StepInfo | None:
        """A scripted ``replay`` key models a contact already charged on a prior run — recovered
        from the (fake) ledger as a replayed :class:`StepInfo`, independent of the budget gate."""
        if key in self._replay:
            ids, cost = self._replay[key]
            return StepInfo(replayed=True, claim_ids=ids, cost_cents=cost)
        return None


@asynccontextmanager
async def _fake_conn() -> Any:
    yield None


def _fake_session_factory() -> Any:
    return _fake_conn()


def _spec() -> ICPSpec:
    return ICPSpec(client_id="client-1", icp_key="icp-a", created_from=ICPCreatedFrom.SYNTHESIS)


def _orchestrator(
    io: FakeAccountRunIO,
    profile_account: Any,
    discover_committee: Any,
    profile_contact: Any,
    *,
    config: DeepPhaseConfig | None = None,
    recursion_policy: RecursionPolicy | None = None,
    budget: Any | None = None,
    spend: Any | None = None,
) -> AccountDeepOrchestrator:
    return AccountDeepOrchestrator(
        profile_account=profile_account,
        discover_committee=discover_committee,
        profile_contact=profile_contact,
        io=io,
        session_factory=_fake_session_factory,
        spec=_spec(),
        config=config if config is not None else DeepPhaseConfig(),
        budget=budget if budget is not None else FakeBudgetEngine(),
        spend=spend if spend is not None else FakeExactlyOnceSpend(),
        sources=(),
        gateway=object(),  # a sentinel; the fakes ignore it
        recursion_policy=recursion_policy,
    )


# --- tests -------------------------------------------------------------------


def test_fresh_run_sequences_account_then_committee_then_contacts() -> None:
    io = FakeAccountRunIO()
    rec = Recorder()
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=3),
        FakeProfileContact(rec),
    )
    campaign = new_campaign_run_id()
    entity = new_entity_id()
    spec = AccountSpec(entity_id=entity, tier="top", tenant_id="client-1")

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=campaign)
        # account first, committee second (a hard gate), then the three contacts
        assert rec.order[0] == "account"
        assert rec.order[1] == "committee"
        assert rec.order[2:] == ["contact"] * 3
        assert result.account is not None and result.committee is not None
        assert len(result.contacts) == 3
        assert result.sub_phase is AccountRunSubPhase.CONTACTS_COMPLETE
        # cost = account 5 + committee 3 + 3 contacts × 2
        assert result.cost_cents == Decimal("5") + Decimal("3") + Decimal("6")
        # the committee member ids were persisted as the fan-out resume work-list
        run_id = deep_account_run_id(campaign, entity)
        persisted = io.runs[run_id]["references_index"]["committee_contacts"]
        assert len(persisted) == 3
        # the run ended DONE; the three boundaries were stamped in order
        assert [s for s, _ in io.saves] == [
            AccountRunSubPhase.ACCOUNT_PROFILED,
            AccountRunSubPhase.COMMITTEE_DISCOVERED,
            AccountRunSubPhase.CONTACTS_COMPLETE,
        ]
        assert io.saves[-1][1] is AccountRunStatus.DONE

    run_async(_run())


def test_resume_at_committee_discovered_skips_account_and_committee() -> None:
    io = FakeAccountRunIO()
    rec = Recorder()
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec),
        FakeProfileContact(rec),
    )
    campaign = new_campaign_run_id()
    entity = new_entity_id()
    spec = AccountSpec(entity_id=entity, tier="top", tenant_id="client-1")
    run_id = deep_account_run_id(campaign, entity)
    contact_ids = [new_entity_id(), new_entity_id()]
    io.seed(
        run_id,
        sub_phase=AccountRunSubPhase.COMMITTEE_DISCOVERED,
        references_index={"committee_contacts": [str(c) for c in contact_ids]},
        cost_cents=Decimal("8"),
    )

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=campaign)
        # neither the account nor the committee was re-run — only the contact fan-out resumed
        assert "account" not in rec.order
        assert "committee" not in rec.order
        assert rec.order == ["contact", "contact"]
        assert sorted(str(c) for c in rec.contact_ids) == sorted(str(c) for c in contact_ids)
        assert result.account is None and result.committee is None
        assert len(result.contacts) == 2
        assert result.sub_phase is AccountRunSubPhase.CONTACTS_COMPLETE
        # cost = the 8 already booked + 2 contacts × 2
        assert result.cost_cents == Decimal("8") + Decimal("4")

    run_async(_run())


def test_full_resume_is_a_no_op() -> None:
    io = FakeAccountRunIO()
    rec = Recorder()
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec),
        FakeProfileContact(rec),
    )
    campaign = new_campaign_run_id()
    entity = new_entity_id()
    spec = AccountSpec(entity_id=entity, tier="top", tenant_id="client-1")
    run_id = deep_account_run_id(campaign, entity)
    io.seed(
        run_id,
        sub_phase=AccountRunSubPhase.CONTACTS_COMPLETE,
        references_index={"committee_contacts": [str(new_entity_id())]},
        cost_cents=Decimal("20"),
    )

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=campaign)
        assert rec.order == []  # nothing re-ran
        assert result.sub_phase is AccountRunSubPhase.CONTACTS_COMPLETE
        assert result.cost_cents == Decimal("20")
        assert io.saves == []  # no further writes

    run_async(_run())


def test_committee_size_cap_truncates_the_fan_out() -> None:
    io = FakeAccountRunIO()
    rec = Recorder()
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=5),
        FakeProfileContact(rec),
        config=DeepPhaseConfig(committee_size_cap=2),
    )
    spec = AccountSpec(entity_id=new_entity_id(), tier="top", tenant_id="client-1")

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=new_campaign_run_id())
        # 5 members discovered, but only committee_size_cap=2 are profiled
        assert len(rec.contact_ids) == 2
        assert len(result.contacts) == 2

    run_async(_run())


def test_max_contacts_in_flight_bounds_concurrency() -> None:
    io = FakeAccountRunIO()
    rec = Recorder()
    contact = FakeProfileContact(rec, delay=0.02)
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=6),
        contact,
        config=DeepPhaseConfig(committee_size_cap=10, max_contacts_in_flight=2),
    )
    spec = AccountSpec(entity_id=new_entity_id(), tier="top", tenant_id="client-1")

    async def _run() -> None:
        await orch.run_one(spec, campaign_run_id=new_campaign_run_id())
        assert contact.peak <= 2  # the intra-account semaphore held the line
        assert contact.peak == 2  # ...and the fan-out actually reached the cap

    run_async(_run())


def test_account_axis_carries_spec_and_explicit_kwargs_with_one_run_id() -> None:
    io = FakeAccountRunIO()
    rec = Recorder()
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=1),
        FakeProfileContact(rec),
    )
    campaign = new_campaign_run_id()
    entity = new_entity_id()
    spec = AccountSpec(entity_id=entity, tier="top", tenant_id="client-1")

    async def _run() -> None:
        await orch.run_one(spec, campaign_run_id=campaign)
        run_id = deep_account_run_id(campaign, entity)
        acc = rec.account_kwargs[0]
        com = rec.committee_kwargs[0]
        # account axis: the ICP spec + tenant + the deterministic run id, all explicit kwargs
        assert acc["spec"].client_id == "client-1"
        assert acc["tenant_id"] == "client-1"
        assert acc["run_id"] == run_id
        # committee axis: tenant + run id as explicit kwargs (never via ctx.params)
        assert com["tenant_id"] == "client-1"
        assert com["run_id"] == run_id  # one provenance line across stages

    run_async(_run())


def test_not_found_account_short_circuits_before_committee() -> None:
    io = FakeAccountRunIO()
    rec = Recorder()
    orch = _orchestrator(
        io,
        make_failing_profile_account(rec),
        make_discover_committee(rec),
        FakeProfileContact(rec),
    )
    spec = AccountSpec(entity_id=new_entity_id(), tier="top", tenant_id="client-1")

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=new_campaign_run_id())
        # the account did not resolve → stop before discovery; committee/contact never reached
        assert rec.order == ["account"]
        assert "committee" not in rec.order and "contact" not in rec.order
        assert result.account is not None and result.account.status is WorkerStatus.FAILED
        assert result.committee is None and result.contacts == ()
        assert result.sub_phase is None  # the marker is left un-advanced (a no-op on retry)
        assert io.saves == []  # nothing persisted — the M8A.2 handler records it FAILED

    run_async(_run())


def test_empty_committee_completes_with_zero_contacts() -> None:
    io = FakeAccountRunIO()
    rec = Recorder()
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=0),
        FakeProfileContact(rec),
    )
    campaign = new_campaign_run_id()
    entity = new_entity_id()
    spec = AccountSpec(entity_id=entity, tier="top", tenant_id="client-1")

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=campaign)
        # a discoverable-but-empty committee is a successful partial (coverage), not a failure
        assert rec.order == ["account", "committee"]
        assert result.contacts == ()
        assert result.committee is not None and len(result.committee.members) == 0
        assert result.sub_phase is AccountRunSubPhase.CONTACTS_COMPLETE
        assert io.saves[-1][1] is AccountRunStatus.DONE
        run_id = deep_account_run_id(campaign, entity)
        assert io.runs[run_id]["references_index"]["committee_contacts"] == []

    run_async(_run())


def test_deterministic_account_run_id() -> None:
    campaign = new_campaign_run_id()
    entity = new_entity_id()
    assert deep_account_run_id(campaign, entity) == deep_account_run_id(campaign, entity)
    assert deep_account_run_id(campaign, entity) != deep_account_run_id(
        new_campaign_run_id(), entity
    )
    assert deep_account_run_id(campaign, entity) != deep_account_run_id(campaign, new_entity_id())
