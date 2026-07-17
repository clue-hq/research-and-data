"""DB-gated end-to-end test for M8A.4 AC1 at the **orchestrator** granularity (ENG-170).

The ``test_budget_reconciliation`` tests prove the ``run_step`` *primitive* is exactly-once; this
one proves the property the spec actually scopes AC1 to: a crash *inside a per-contact step* of the
``AccountDeepOrchestrator``'s 3-stage sequence, then a real resume (re-entry via the ``sub_phase``
marker + the cost-seed from ``account_run.cost_cents`` + the durable-ledger recovery of already-paid
contacts), leaves ``account_run.cost_cents == campaign_run.spent_cents == SUM(ledger charges)`` — no
under-count, no double-charge — and **no committed contact's references dropped**. Driven by the
real ``AccountDeepOrchestrator`` + ``DbExactlyOnceSpend`` + ``DbAccountRunIO`` + a real engine over
a connection, with the per-stage transaction modelled by a SAVEPOINT (so the whole thing stays
inside ``rollback_conn``'s always-rolled-back outer transaction — no rows leak). Needs a reachable
migrated Postgres; ``pytest.skip`` without one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import DeepPhaseConfig
from clue_core import (
    EntityId,
    Persona,
    SourceTier,
    WorkerStatus,
    new_campaign_run_id,
    new_claim_id,
    new_entity_id,
)
from clue_core.enums import ICPCreatedFrom
from clue_core.handoff import ICPSpec, ProfileClaimView
from clue_research.api.deep import (
    AccountDeepOrchestrator,
    DbAccountRunIO,
    DbExactlyOnceSpend,
    deep_account_run_id,
    deep_step_key,
)
from clue_research.durable import (
    AccountRunStatus,
    AccountRunSubPhase,
    AccountSpec,
    BudgetEngine,
    add_account_spend,
    add_run_spend,
    ensure_campaign_run,
    fold_references,
    get_account_budget_state,
    get_account_run,
    get_idempotency_ledger,
    get_run_budget_state,
    insert_account_run,
    set_account_budget_cap,
    set_account_sub_phase,
)
from clue_research.durable.budget import BudgetStateNotFound
from clue_research.profiling import (
    AccountProfileResult,
    CommitteeResult,
    ContactProfileResult,
)
from clue_research.profiling.committee.coverage import estimate_committee_coverage
from clue_research.profiling.committee.results import CommitteeMemberRef
from clue_research.profiling.committee.stopping import CommitteeStopReason
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_durable_db")


def _spec() -> ICPSpec:
    return ICPSpec(workspace_id="client-1", icp_key="icp-a", created_from=ICPCreatedFrom.SYNTHESIS)


class _ConnBudgetStore:
    """A :class:`~clue_research.durable.budget.BudgetStore` bound to the **shared test connection**
    so the admission ``check`` (a read) and the conn-aware ``record`` (a write) both see the
    rollback-isolated rows the test seeds — :class:`DbBudgetStore` opens its own transaction, which
    would not. Only ``account_state`` + ``add_spend`` are exercised here (cap is high → every check
    ALLOWs, so no event / cap-set / estimate / run-scope read); the rest fail loud if reached."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def account_state(self, account_run_id: Any) -> Any:
        return await get_account_budget_state(self._conn, account_run_id)

    async def add_spend(
        self,
        *,
        campaign_run_id: Any,
        cost_cents: Decimal,
        account_run_id: Any | None = None,
        conn: AsyncConnection | None = None,
    ) -> None:
        # ``record(conn=…)`` passes the per-stage savepoint connection (which IS the shared conn);
        # fall back to the shared conn when omitted. Fail-loud, mirroring DbBudgetStore.add_spend.
        c = conn if conn is not None else self._conn
        if await add_run_spend(c, campaign_run_id, cost_cents) == 0:
            raise BudgetStateNotFound(f"campaign_run {campaign_run_id}")
        if (
            account_run_id is not None
            and await add_account_spend(c, account_run_id, cost_cents) == 0
        ):
            raise BudgetStateNotFound(f"account_run {account_run_id}")

    async def run_state(self, campaign_run_id: Any) -> Any:  # pragma: no cover - unused here
        raise NotImplementedError

    async def set_campaign_cap(self, campaign_run_id: Any, cap_cents: Decimal) -> None:
        raise NotImplementedError  # pragma: no cover - unused here

    async def set_account_cap(self, account_run_id: Any, cap_cents: Decimal | None) -> None:
        raise NotImplementedError  # pragma: no cover - unused here

    async def set_estimated(self, campaign_run_id: Any, estimated_cents: Decimal) -> None:
        raise NotImplementedError  # pragma: no cover - unused here

    async def record_event(self, **kwargs: Any) -> None:  # pragma: no cover - unused here
        raise NotImplementedError


def _savepoint_factory(conn: AsyncConnection) -> Any:
    """A ``ConnFactory`` whose every ``session_factory()`` is a SAVEPOINT on the shared test
    connection — commit (release) on clean exit, rollback on exception — modelling the production
    per-stage ``db.transaction()`` while staying inside ``rollback_conn``'s outer rollback."""

    @asynccontextmanager
    async def _open() -> AsyncIterator[AsyncConnection]:
        async with conn.begin_nested():
            yield conn

    return _open


def _account_fn(*, cost: Decimal):
    async def _f(**kwargs: Any) -> AccountProfileResult:
        return AccountProfileResult(
            account_entity_id=kwargs["account_entity_id"],
            tier=kwargs["tier"],
            run_id=kwargs["run_id"],
            status=WorkerStatus.OK,
            claim_refs=(new_claim_id(),),
            cost_cents=cost,
        )

    return _f


def _committee_fn(members: list[EntityId], *, cost: Decimal):
    def _member(cid: EntityId) -> CommitteeMemberRef:
        return CommitteeMemberRef(
            contact_entity_id=cid,
            persona=Persona.CHAMPION,
            role_on_committee=Persona.CHAMPION.value,
            role_confidence=0.8,
            role_plausible=True,
            discovery_claim_id=new_claim_id(),
            role_claim_id=new_claim_id(),
            persona_claim_id=new_claim_id(),
        )

    async def _f(conn: Any, **kwargs: Any) -> CommitteeResult:
        return CommitteeResult(
            account_entity_id=kwargs["account_entity_id"],
            members=tuple(_member(m) for m in members),
            coverage=estimate_committee_coverage(
                channels_searched=(),
                all_channels=(),
                stopping_reason=CommitteeStopReason.EXHAUSTED,
                candidates_seen=len(members),
                admitted=len(members),
            ),
            cost_cents=cost,
            admitted=len(members),
        )

    return _f


class _RecordingContact:
    """A contact-profiling fake that records which contacts it profiled (so a resume can assert no
    already-charged contact was re-run) and always succeeds."""

    def __init__(self, *, cost: Decimal) -> None:
        self._cost = cost
        self.seen: list[EntityId] = []

    async def __call__(
        self, conn: Any, *, contact_entity_id: EntityId, **kwargs: Any
    ) -> ContactProfileResult:
        self.seen.append(contact_entity_id)
        # One profile claim so the contact has a reference to record + recover on resume.
        view = ProfileClaimView(
            claim_id=new_claim_id(), value_json="facet", source_tier=SourceTier(4)
        )
        return ContactProfileResult(
            contact_entity_id=contact_entity_id,
            account_entity_id=kwargs["account_entity_id"],
            profile_claims=(view,),
            cost_cents=self._cost,
        )


def test_resume_after_a_pre_fold_crash_reconciles_cost_and_keeps_all_references() -> None:
    """AC1 at the orchestrator granularity. Run the full 3-stage sequence over a real DB, then model
    the worst crash window — every contact charged (ledger ``SUCCEEDED``) but the run crashed before
    the ``contacts_complete`` fold persisted the ``contact:*`` refs + marker — by reverting the
    durable index/marker to that exact state. On resume the account is at its cap, so re-admission
    would be ``DENY``-ed; the orchestrator instead recovers every charged contact from the ledger.
    Asserts ``account_run.cost_cents == campaign_run.spent_cents == SUM(ledger charges)`` (no
    double-charge) and that **no committed contact's references were dropped** (nor re-run)."""

    async def _run() -> None:
        members = [new_entity_id(), new_entity_id(), new_entity_id()]
        campaign = new_campaign_run_id()
        entity = new_entity_id()
        run_id = deep_account_run_id(campaign, entity)
        account_cost, committee_cost, contact_cost = Decimal("12"), Decimal("7"), Decimal("5")
        total = account_cost + committee_cost + contact_cost * 3

        async with rollback_conn(seed_pack=False) as conn:
            await ensure_campaign_run(
                conn,
                campaign_run_id=campaign,
                workspace_id="client-1",
                icp_key="icp-a",
                icp_version=1,
                budget_cap_cents=Decimal("100000"),
            )
            await insert_account_run(
                conn,
                account_run_id=run_id,
                campaign_run_id=campaign,
                entity_id=entity,
                tier="top",
                status=AccountRunStatus.RUNNING,
            )
            # A tight cap exactly equal to the full spend: after run 1 the account is AT its cap, so
            # a naive resume's re-admission ``check`` would DENY every contact.
            await set_account_budget_cap(conn, run_id, total)

            engine = BudgetEngine(store=_ConnBudgetStore(conn))
            factory = _savepoint_factory(conn)
            contact = _RecordingContact(cost=contact_cost)
            orch = AccountDeepOrchestrator(
                profile_account=_account_fn(cost=account_cost),
                discover_committee=_committee_fn(members, cost=committee_cost),
                profile_contact=contact,
                io=DbAccountRunIO(session_factory=factory),
                session_factory=factory,
                spec=_spec(),
                config=DeepPhaseConfig(
                    max_contacts_in_flight=1, per_contact_estimate_cents=contact_cost
                ),
                budget=engine,
                spend=DbExactlyOnceSpend(engine),
                sources=(),
                gateway=object(),
            )

            # Run 1: the full sequence commits — every stage charged through ``record`` once.
            await orch.run_one(AccountSpec(entity_id=entity, tier="top"), campaign_run_id=campaign)
            assert (await get_run_budget_state(conn, campaign)).spent_cents == total
            row = await get_account_run(conn, run_id)
            assert row is not None and row.cost_cents == total
            assert sorted(contact.seen) == sorted(members)  # each contact profiled once

            # Model the pre-fold crash: charges are durable (ledger SUCCEEDED, counters at total)
            # but the contacts_complete fold never persisted the contact refs + marker. Revert the
            # index to drop every ``contact:*`` key and the marker back to COMMITTEE_DISCOVERED.
            pre_fold_index = {
                k: v for k, v in row.references_index.items() if not k.startswith("contact:")
            }
            await fold_references(
                conn, run_id, references_index=pre_fold_index, status=AccountRunStatus.RUNNING
            )
            await set_account_sub_phase(conn, run_id, AccountRunSubPhase.COMMITTEE_DISCOVERED)
            contact.seen.clear()

            # Resume: stage 3 re-runs, but every contact is recovered from the ledger (NO re-charge,
            # NO re-run) and the marker advances to CONTACTS_COMPLETE.
            result = await orch.run_one(
                AccountSpec(entity_id=entity, tier="top"), campaign_run_id=campaign
            )

            # the counters did not move on resume — no double-charge
            assert (await get_run_budget_state(conn, campaign)).spent_cents == total
            final = await get_account_budget_state(conn, run_id)
            assert final is not None and final.cost_cents == total
            # cost_cents == campaign spent == SUM(ledger cost_cents_charged) — the reconciliation AC
            ledger_keys = [deep_step_key(run_id, s) for s in ("account", "committee")] + [
                deep_step_key(run_id, f"contact:{m}") for m in members
            ]
            ledger_sum = Decimal(0)
            for key in ledger_keys:
                led = await get_idempotency_ledger(conn, key)
                assert led is not None
                ledger_sum += led.cost_cents_charged
            assert ledger_sum == total == final.cost_cents

            # every committed contact's references are back in the index — the handoff loses nobody
            final_row = await get_account_run(conn, run_id)
            assert final_row is not None
            for m in members:
                assert final_row.references_index[f"contact:{m}"], f"references for {m} dropped"
            assert final_row.status is AccountRunStatus.DONE
            assert result.sub_phase is AccountRunSubPhase.CONTACTS_COMPLETE
            assert contact.seen == []  # no already-charged contact was re-run on resume

    run_async(_run())
