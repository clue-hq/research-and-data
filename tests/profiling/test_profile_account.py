"""M8.1 — ``profile_account`` account-level converge orchestration (DB-gated, stub workers).

Exercises the account-level ACs against the real gap-computation / clustering / aspect-capping path
with recording stub aspect workers (the M7 graph runs the real workers; here we assert the
orchestration the spec's ``profile_account`` AC names): a worker per gap cluster (AC1), aspects run
in parallel and return references only (AC4), the per-tier ``max_aspect_workers`` cap (AC6, asserted
against the ``RecursionPolicy`` knob), schema-complete → zero work (AC2), and the run_id threaded to
every aspect (AC7 idempotency key). The real per-field fill is covered in ``test_account_worker``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from clue_research.claimstore import insert_claim, register_field
from clue_research.config import RecursionPolicy, TierRecursionCaps
from clue_research.core import (
    EntityType,
    ExtractionMethod,
    FieldDef,
    ICPCreatedFrom,
    ICPSpec,
    PassKind,
    ResearchMode,
    WorkerResult,
    WorkerStatus,
    account_claim,
    new_claim_id,
    new_entity_id,
    new_run_id,
)
from clue_research.identity import insert_account_entity, mark_merged
from clue_research.profiling import profile_account

from .conftest import conn_session_factory, rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

# Three deep fields in three distinct account-axis classes → three aspect clusters.
_CORE_F = "core.test_deep"
_ACCT_F = "account.test_deep"
_RESO_F = "account.resonance.test_deep"
_ALL = (_CORE_F, _ACCT_F, _RESO_F)
_CLUSTERS = {"core", "account", "account.resonance"}


class _StubWorker:
    """A recording aspect-worker double: counts calls, captures the run_id, optional barrier."""

    def __init__(self, aspect: str, *, n_claims: int = 1, before=None) -> None:
        self.aspect = aspect
        self.calls = 0
        self.seen_run_id = None
        self.seen_entity_id = None
        self.seen_field_keys: tuple[str, ...] = ()
        self._n = n_claims
        self._before = before

    async def research(self, ctx):
        self.calls += 1
        self.seen_run_id = ctx.run_id
        self.seen_entity_id = ctx.entity_id
        self.seen_field_keys = ctx.field_keys
        if self._before is not None:
            await self._before()
        return WorkerResult(
            aspect=ctx.aspect,
            status=WorkerStatus.OK,
            claim_refs=tuple(new_claim_id() for _ in range(self._n)),
            detail={"aspect": ctx.aspect, "fields_filled": self._n},
        )


def _spec(field_keys=_ALL) -> ICPSpec:
    return ICPSpec(
        client_id="acme",
        icp_key="k",
        created_from=ICPCreatedFrom.SYNTHESIS,
        version=1,
        field_keys=field_keys,
    )


async def _register_fields(conn) -> None:
    for fk in _ALL:
        await register_field(
            conn, FieldDef(field_key=fk, value_type="object", pass_kind=PassKind.DEEP)
        )


async def _insert_account(conn):
    return await insert_account_entity(
        conn, canonical_name="Acme Robotics", primary_domain="acme-robotics.com"
    )


def _stub_builder(stubs):
    return lambda aspect: stubs.get(aspect)


# --- AC1: a worker per gap cluster ------------------------------------------


def test_dispatches_one_worker_per_gap_cluster() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_fields(conn)
            acct = await _insert_account(conn)
            stubs = {a: _StubWorker(a) for a in _CLUSTERS}

            result = await profile_account(
                account_entity_id=acct,
                spec=_spec(),
                tier="top",
                tenant_id="acme",
                session_factory=conn_session_factory(conn),
                worker_for=_stub_builder(stubs),
            )

            assert result.status is WorkerStatus.OK
            assert result.gap_field_count == 3
            assert {a for a, s in stubs.items() if s.calls} == _CLUSTERS  # every cluster dispatched
            assert result.dropped_aspects == ()
            assert len(result.claim_refs) == 3  # one ref per stub, aggregated

    run_async(_run())


# --- AC4: parallel + references only ----------------------------------------


def test_aspects_run_in_parallel() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_fields(conn)
            acct = await _insert_account(conn)
            barrier = asyncio.Barrier(3)

            async def _wait() -> None:
                await barrier.wait()

            stubs = {a: _StubWorker(a, before=_wait) for a in _CLUSTERS}
            # If the fan-out ran serially the first worker would block on the barrier forever and
            # wait_for would time out — reaching it proves the three aspects run concurrently.
            result = await asyncio.wait_for(
                profile_account(
                    account_entity_id=acct,
                    spec=_spec(),
                    tier="top",
                    tenant_id="acme",
                    session_factory=conn_session_factory(conn),
                    worker_for=_stub_builder(stubs),
                ),
                timeout=5.0,
            )
            assert result.status is WorkerStatus.OK
            assert all(isinstance(ref, type(result.claim_refs[0])) for ref in result.claim_refs)

    run_async(_run())


# --- AC6: per-tier aspect cap (read from the M7 RecursionPolicy knob) --------


def test_per_tier_aspect_cap_drops_excess_clusters() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_fields(conn)
            acct = await _insert_account(conn)
            policy = RecursionPolicy(
                by_tier={
                    "top": TierRecursionCaps(max_aspect_workers=8),
                    "small": TierRecursionCaps(max_aspect_workers=2),
                }
            )

            top_stubs = {a: _StubWorker(a) for a in _CLUSTERS}
            top = await profile_account(
                account_entity_id=acct,
                spec=_spec(),
                tier="top",
                tenant_id="acme",
                session_factory=conn_session_factory(conn),
                recursion_policy=policy,
                worker_for=_stub_builder(top_stubs),
            )
            assert sum(s.calls for s in top_stubs.values()) == 3  # full aspect set
            assert top.dropped_aspects == ()

            small_stubs = {a: _StubWorker(a) for a in _CLUSTERS}
            small = await profile_account(
                account_entity_id=acct,
                spec=_spec(),
                tier="small",
                tenant_id="acme",
                session_factory=conn_session_factory(conn),
                recursion_policy=policy,
                worker_for=_stub_builder(small_stubs),
            )
            # strictly smaller: the cap (2) bounds the dispatched aspects; the 3rd is dropped.
            assert sum(s.calls for s in small_stubs.values()) == 2
            assert len(small.dropped_aspects) == 1

    run_async(_run())


# --- AC2: schema-complete → zero work; account-not-found → terminates -------


def test_all_fresh_fields_is_complete_zero_work() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_fields(conn)
            acct = await _insert_account(conn)
            run_id = new_run_id()
            # make the two public fields FRESH so they are not gaps.
            for fk in (_CORE_F, _ACCT_F):
                await insert_claim(
                    conn,
                    account_claim(
                        entity_id=acct,
                        field_key=fk,
                        value_json={"v": 1},
                        source_tier=1,
                        extraction_method=ExtractionMethod.API,
                        confidence=0.95,
                        run_id=run_id,
                        research_mode=ResearchMode.ACCOUNT_PROFILING,
                        source_url="https://example.com/x",
                    ),
                )
            stubs = {a: _StubWorker(a) for a in _CLUSTERS}
            result = await profile_account(
                account_entity_id=acct,
                spec=_spec((_CORE_F, _ACCT_F)),  # only the two now-fresh public fields
                tier="top",
                tenant_id="acme",
                session_factory=conn_session_factory(conn),
                worker_for=_stub_builder(stubs),
            )
            assert result.status is WorkerStatus.OK
            assert result.gap_field_count == 0
            assert sum(s.calls for s in stubs.values()) == 0  # nothing to research

    run_async(_run())


def test_unresolved_account_fails_cleanly() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            result = await profile_account(
                account_entity_id=new_entity_id(),  # never inserted
                spec=_spec(),
                tier="top",
                tenant_id="acme",
                session_factory=conn_session_factory(conn),
                worker_for=_stub_builder({}),
            )
            assert result.status is WorkerStatus.FAILED

    run_async(_run())


# --- AC7: the run_id is threaded to every aspect (the idempotency key) -------


def test_run_id_is_threaded_to_every_aspect() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_fields(conn)
            acct = await _insert_account(conn)
            run_id = new_run_id()
            stubs = {a: _StubWorker(a) for a in _CLUSTERS}
            result = await profile_account(
                account_entity_id=acct,
                spec=_spec(),
                tier="top",
                run_id=run_id,
                tenant_id="acme",
                session_factory=conn_session_factory(conn),
                worker_for=_stub_builder(stubs),
            )
            assert result.run_id == run_id
            assert all(s.seen_run_id == run_id for s in stubs.values())

    run_async(_run())


# --- edge cases (audit coverage) --------------------------------------------


def test_stale_field_is_treated_as_a_gap() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # a deep account field with a short TTL holding a claim older than the TTL → STALE, so
            # it is a gap (a refresh is wanted), not silently skipped (substrate §1/§6).
            await register_field(
                conn,
                FieldDef(
                    field_key=_ACCT_F,
                    value_type="object",
                    pass_kind=PassKind.DEEP,
                    freshness_ttl=timedelta(days=30),
                ),
            )
            acct = await _insert_account(conn)
            stale = datetime.now(UTC) - timedelta(days=120)  # well past the 30d TTL
            await insert_claim(
                conn,
                account_claim(
                    entity_id=acct,
                    field_key=_ACCT_F,
                    value_json={"v": 1},
                    source_tier=1,
                    extraction_method=ExtractionMethod.API,
                    confidence=0.95,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    source_url="https://example.com/x",
                    observed_at=stale,
                ),
            )
            stubs = {"account": _StubWorker("account")}
            result = await profile_account(
                account_entity_id=acct,
                spec=_spec((_ACCT_F,)),
                tier="top",
                tenant_id="acme",
                session_factory=conn_session_factory(conn),
                worker_for=_stub_builder(stubs),
            )
            assert result.gap_field_count == 1  # the stale field is re-targeted, not skipped
            assert stubs["account"].calls == 1

    run_async(_run())


def test_profile_account_follows_account_merge_to_survivor() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_fields(conn)
            loser = await insert_account_entity(
                conn, canonical_name="Acme Old", primary_domain="old.example.com"
            )
            survivor = await _insert_account(conn)  # "Acme Robotics" / acme-robotics.com
            await mark_merged(conn, EntityType.ACCOUNT, loser, survivor)

            stubs = {a: _StubWorker(a) for a in _CLUSTERS}
            result = await profile_account(
                account_entity_id=loser,  # called with the merged-away id
                spec=_spec(),
                tier="top",
                tenant_id="acme",
                session_factory=conn_session_factory(conn),
                worker_for=_stub_builder(stubs),
            )
            # the run profiles the canonical survivor, never the merged loser.
            assert result.account_entity_id == survivor
            assert all(s.seen_entity_id == survivor for s in stubs.values() if s.calls)

    run_async(_run())
