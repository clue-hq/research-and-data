"""The retention/objection tombstone-before-merge-read sweep wired ahead of HANDOFF (M10.5 × M12) —
driven by fakes (no DB). Proves the load-bearing ordering invariant ``[M9.5×M1.2/M10.5]``: the
EXPIRED + objected personal claims are tombstoned **before** the inner handoff handler runs its
assemble/merge read, scoped to the run's accounts + committee contacts, and the references-only
payload is augmented with the sweep counts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from decimal import Decimal

from clue_api.handoff_retention import (
    RetentionSweepHandoffHandler,
)
from clue_core import (
    CampaignPhase,
    EntityId,
    PhaseContext,
    PhaseHandler,
    PhaseResult,
    PhaseStatus,
    new_campaign_run_id,
    new_entity_id,
)
from clue_research.durable import AccountSpec, PhaseHandlerRegistry

_CLIENT = "client-acme"


class _Recorder:
    def __init__(self) -> None:
        self.log: list[str] = []


class _SweepResult:
    def __init__(self, ids: Sequence[EntityId]) -> None:
        self.tombstoned_claim_ids = tuple(ids)


class FakeSweep:
    """Satisfies the handler's ``RetentionSweeping`` seam (M10.5)."""

    def __init__(self, rec: _Recorder, *, expired: int = 2, objected: int = 1) -> None:
        self._rec = rec
        self._expired = expired
        self._objected = objected
        self.expired_entity_ids: tuple[EntityId, ...] | None = None
        self.expired_calls = 0
        self.objection_calls = 0

    async def sweep_expired(
        self,
        *,
        entity_ids: tuple[EntityId, ...] | None = None,
        field_keys: tuple[str, ...] | None = None,
    ) -> _SweepResult:
        self._rec.log.append("sweep_expired")
        self.expired_calls += 1
        self.expired_entity_ids = entity_ids
        return _SweepResult([new_entity_id() for _ in range(self._expired)])

    async def sweep_objections(self) -> _SweepResult:
        self._rec.log.append("sweep_objections")
        self.objection_calls += 1
        return _SweepResult([new_entity_id() for _ in range(self._objected)])


class FakeHandoff:
    """A stand-in inner ``CampaignPhase.HANDOFF`` handler (M12's emit path)."""

    phase = CampaignPhase.HANDOFF

    def __init__(self, rec: _Recorder) -> None:
        self._rec = rec

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        self._rec.log.append("handoff_run")
        return PhaseResult(
            status=PhaseStatus.COMPLETED,
            accounts_processed=3,
            cost_cents=Decimal(0),
            payload={"newly_emitted": 3, "refs": ["a", "b", "c"]},
        )


def _resolver(specs: Sequence[AccountSpec]):  # noqa: ANN202 — local test helper
    async def _r(ctx: PhaseContext) -> Sequence[AccountSpec]:
        return specs

    return _r


def _contact_resolver(contacts: dict[EntityId, list[EntityId]]):  # noqa: ANN202
    async def _c(account_entity_id: EntityId) -> Sequence[EntityId]:
        return contacts.get(account_entity_id, [])

    return _c


def _spec(entity_id: EntityId) -> AccountSpec:
    return AccountSpec(entity_id=entity_id, tier="top", workspace_id=_CLIENT)


def _ctx() -> PhaseContext:
    return PhaseContext(
        campaign_run_id=new_campaign_run_id(),
        phase=CampaignPhase.HANDOFF,
        workspace_id=_CLIENT,
        icp_key="icp-1",
        icp_version=1,
    )


def test_conforms_and_replaces_the_handoff_handler() -> None:
    rec = _Recorder()
    handler = RetentionSweepHandoffHandler(
        sweep=FakeSweep(rec), inner=FakeHandoff(rec), account_resolver=_resolver(())
    )
    assert isinstance(handler, PhaseHandler)
    assert handler.phase is CampaignPhase.HANDOFF
    # last-write-wins: registering it makes the registry resolve HANDOFF to the sweeping wrapper.
    registry = PhaseHandlerRegistry()
    registry.register(FakeHandoff(rec))
    registry.register(handler)
    assert registry.get(CampaignPhase.HANDOFF) is handler


def test_sweeps_before_the_inner_handoff_runs() -> None:
    rec = _Recorder()
    e1 = new_entity_id()
    handler = RetentionSweepHandoffHandler(
        sweep=FakeSweep(rec), inner=FakeHandoff(rec), account_resolver=_resolver((_spec(e1),))
    )

    async def _run() -> None:
        await handler.run(_ctx())
        # both sweeps must precede the inner handoff's assemble/merge read.
        assert rec.log.index("sweep_expired") < rec.log.index("handoff_run")
        assert rec.log.index("sweep_objections") < rec.log.index("handoff_run")

    asyncio.run(_run())


def test_expired_sweep_is_scoped_to_the_runs_accounts_and_contacts() -> None:
    rec = _Recorder()
    account, contact = new_entity_id(), new_entity_id()
    sweep = FakeSweep(rec)
    handler = RetentionSweepHandoffHandler(
        sweep=sweep,
        inner=FakeHandoff(rec),
        account_resolver=_resolver((_spec(account),)),
        contact_resolver=_contact_resolver({account: [contact]}),
    )

    async def _run() -> None:
        await handler.run(_ctx())
        # the age-out is scoped to exactly the run's account + its committee contact (no
        # operator-wide widening that would re-sweep other tenants).
        assert sweep.expired_entity_ids == (account, contact)

    asyncio.run(_run())


def test_empty_run_does_not_widen_to_an_operator_wide_age_out() -> None:
    # No high-tier accounts → sweep_expired must NOT be called (entity_ids=None would scan every
    # tenant). Objections still run (operator-wide, near-absolute); the inner handoff still runs.
    rec = _Recorder()
    sweep = FakeSweep(rec)
    handler = RetentionSweepHandoffHandler(
        sweep=sweep, inner=FakeHandoff(rec), account_resolver=_resolver(())
    )

    async def _run() -> None:
        await handler.run(_ctx())
        assert sweep.expired_calls == 0
        assert sweep.objection_calls == 1
        assert "handoff_run" in rec.log

    asyncio.run(_run())


def test_delegates_and_augments_payload_with_sweep_counts() -> None:
    rec = _Recorder()
    e1 = new_entity_id()
    handler = RetentionSweepHandoffHandler(
        sweep=FakeSweep(rec, expired=2, objected=1),
        inner=FakeHandoff(rec),
        account_resolver=_resolver((_spec(e1),)),
    )

    async def _run() -> None:
        result = await handler.run(_ctx())
        # the inner handoff result is preserved …
        assert result.status is PhaseStatus.COMPLETED
        assert result.accounts_processed == 3
        assert result.payload["newly_emitted"] == 3
        # … and augmented with the sweep counts (references-only).
        assert result.payload["retention_tombstoned"] == 2
        assert result.payload["objection_tombstoned"] == 1

    asyncio.run(_run())
