"""M8.1 — the ``AspectProfilingWorker`` converge body, end to end over the M4 waterfall (DB-gated).

A single real aspect worker filling one resolved account's gap field through a resolver double +
registered manifest, exercising the M8.1 ACs at the worker level: provenance (``research_mode=M2``,
non-null tier), references-not-blobs, idempotent re-run, budget-cap stop, sources-exhausted →
empty/flagged, the target-lock guard (un-lockable entity, cross-entity tier-3 claim), and the
tenant guard for a ``tenant_private`` field.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_research.claimstore import PUBLIC_ONLY, claims_for, register_field
from clue_research.core import (
    AspectContext,
    Claim,
    Entity,
    EntityScope,
    ExtractionMethod,
    FieldDef,
    Modality,
    PassKind,
    ResearchMode,
    SourceManifest,
    WorkerStatus,
    account_claim,
    new_campaign_run_id,
    new_entity_id,
    new_run_id,
)
from clue_research.identity import insert_account_entity
from clue_research.profiling import AspectProfilingWorker, ProfilingFieldDisposition, params_for_run
from clue_research.sources import RegistrySourceManifest, bind_resolver, register_source

from .conftest import conn_session_factory, rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

_FIELD = "account.test_signal"


class _Fake:
    """A resolver double (mirrors the M4.1 waterfall test): preset claims, call counter."""

    tier = 1  # the engine reads tier from the manifest; present for protocol conformance

    def __init__(self, claims: list[Claim]) -> None:
        self._claims = claims
        self.calls = 0

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        self.calls += 1
        return [c.model_copy(update={"entity_id": entity.entity_id}) for c in self._claims]


def _fake_claim(
    *,
    tier: int,
    confidence: float,
    span: str | None = "evidence",
    field_key: str = _FIELD,
    cost: Decimal = Decimal(0),
) -> Claim:
    # the engine stamps run_id/research_mode; _Fake stamps entity_id — placeholders here are inert.
    # ``cost`` rides on the claim — the waterfall records the *claim's* cost_cents as the spend.
    method = ExtractionMethod.LLM_SYNTHESIS if tier == 4 else ExtractionMethod.API
    return account_claim(
        entity_id=new_entity_id(),
        field_key=field_key,
        value_json={"summary": "x"},
        source_tier=tier,
        extraction_method=method,
        confidence=confidence,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://example.com/x",
        evidence_span=span,
        cost_cents=cost,
    )


async def _register_source(conn, source_key: str, *, tier: int, cost: Decimal = Decimal(0)) -> None:
    await register_source(
        conn,
        RegistrySourceManifest(
            manifest=SourceManifest(
                source_key=source_key,
                modality=Modality.TEXT if tier == 4 else Modality.STRUCTURED,
                entity_scope=EntityScope.ACCOUNT,
                yields=("account",),
                tier=tier,
                cost_cents=cost,
            ),
            active=True,
        ),
    )


async def _register_test_field(conn, *, field_key: str = _FIELD, tier_plan=("fake1",)) -> None:
    await register_field(
        conn,
        FieldDef(
            field_key=field_key, value_type="object", tier_plan=tier_plan, pass_kind=PassKind.DEEP
        ),
    )


async def _insert_account(conn, *, domain: str | None = "acme-robotics.com", hq_geo=None):
    return await insert_account_entity(
        conn, canonical_name="Acme Robotics", primary_domain=domain, hq_geo=hq_geo
    )


def _ctx(entity_id, *, field_keys=(_FIELD,), budget=None, tenant_id=None, aspect="account"):
    return AspectContext(
        entity_id=entity_id,
        campaign_run_id=new_campaign_run_id(),
        run_id=new_run_id(),
        tier="top",
        aspect=aspect,
        field_keys=field_keys,
        budget_envelope_cents=budget,
        params=params_for_run(client_id=None, icp_key=None, icp_version=None, tenant_id=tenant_id),
    )


# --- fill + provenance ------------------------------------------------------


def test_fills_assigned_field_with_m2_provenance() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_test_field(conn)
            await _register_source(conn, "fake1", tier=1)
            fake = _Fake([_fake_claim(tier=1, confidence=0.95)])
            bind_resolver("fake1", fake)
            acct = await _insert_account(conn)

            worker = AspectProfilingWorker("account", session_factory=conn_session_factory(conn))
            result = await worker.research(_ctx(acct))

            assert result.status is WorkerStatus.OK
            assert len(result.claim_refs) == 1
            assert fake.calls == 1
            written = await claims_for(conn, acct, _FIELD, scope=PUBLIC_ONLY)
            assert len(written) == 1
            assert written[0].research_mode is ResearchMode.ACCOUNT_PROFILING
            assert written[0].source_tier == 1

    run_async(_run())


def test_returns_references_not_blobs() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_test_field(conn)
            await _register_source(conn, "fake1", tier=1)
            bind_resolver("fake1", _Fake([_fake_claim(tier=1, confidence=0.95)]))
            acct = await _insert_account(conn)

            worker = AspectProfilingWorker("account", session_factory=conn_session_factory(conn))
            result = await worker.research(_ctx(acct))

            # the result carries ids + a coverage summary — never claim value bodies.
            assert all(isinstance(ref, type(result.claim_refs[0])) for ref in result.claim_refs)
            assert "value_json" not in result.detail
            assert result.detail["aspect"] == "account"
            assert result.detail["fields_filled"] == 1
            assert result.detail["dispositions"][_FIELD] == ProfilingFieldDisposition.FILLED.value

    run_async(_run())


def test_idempotent_rerun_does_not_double_write() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_test_field(conn)
            await _register_source(conn, "fake1", tier=1)
            bind_resolver("fake1", _Fake([_fake_claim(tier=1, confidence=0.95)]))
            acct = await _insert_account(conn)
            ctx = _ctx(acct)  # one run_id, reused on both invocations

            worker = AspectProfilingWorker("account", session_factory=conn_session_factory(conn))
            first = await worker.research(ctx)
            second = await worker.research(ctx)

            assert first.claim_refs == second.claim_refs  # same refs, no new rows
            written = await claims_for(conn, acct, _FIELD, scope=PUBLIC_ONLY)
            assert len(written) == 1

    run_async(_run())


# --- the three converge stop states ----------------------------------------


def test_budget_cap_halts_with_flagged_field() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_test_field(conn)
            await _register_source(conn, "fake1", tier=1, cost=Decimal(5))
            fake = _Fake([_fake_claim(tier=1, confidence=0.95)])
            bind_resolver("fake1", fake)
            acct = await _insert_account(conn)

            worker = AspectProfilingWorker("account", session_factory=conn_session_factory(conn))
            result = await worker.research(_ctx(acct, budget=Decimal(1)))  # 1 < the source's 5

            assert result.status is WorkerStatus.BUDGET_EXCEEDED
            assert result.claim_refs == ()
            assert fake.calls == 0  # the budget halt is before the resolver call
            assert (
                result.detail["dispositions"][_FIELD] == ProfilingFieldDisposition.BUDGET_CAP.value
            )

    run_async(_run())


def test_sources_exhausted_left_empty_and_flagged() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_test_field(conn)
            await _register_source(conn, "fake1", tier=1)
            bind_resolver("fake1", _Fake([]))  # the resolver hard-misses (no claims)
            acct = await _insert_account(conn)

            worker = AspectProfilingWorker("account", session_factory=conn_session_factory(conn))
            result = await worker.research(_ctx(acct))

            assert result.status is WorkerStatus.OK  # empty/flagged is a correct output
            assert result.claim_refs == ()
            assert result.detail["fields_empty"] == 1
            assert (
                result.detail["dispositions"][_FIELD]
                == ProfilingFieldDisposition.SOURCES_EXHAUSTED.value
            )

    run_async(_run())


# --- target-lock guards -----------------------------------------------------


def test_unlockable_entity_skips_field_without_spend() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_test_field(conn)
            await _register_source(conn, "fake1", tier=1)
            fake = _Fake([_fake_claim(tier=1, confidence=0.95)])
            bind_resolver("fake1", fake)
            acct = await _insert_account(conn, domain=None)  # name-only → not target-lockable

            worker = AspectProfilingWorker("account", session_factory=conn_session_factory(conn))
            result = await worker.research(_ctx(acct))

            assert result.claim_refs == ()
            assert fake.calls == 0  # no open-web spend on an un-lockable entity
            assert (
                result.detail["dispositions"][_FIELD]
                == ProfilingFieldDisposition.NOT_TARGET_LOCKABLE.value
            )

    run_async(_run())


def test_target_lock_excludes_cross_entity_tier3_claim() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_test_field(conn, tier_plan=("fake3",))
            await _register_source(conn, "fake3", tier=3)
            # a tier-3 (drift-prone) claim whose evidence is about a DIFFERENT same-name company.
            cross = _fake_claim(
                tier=3,
                confidence=0.95,
                span="Acme Robotics in San Francisco (acme-corp.io) shipped a product.",
            )
            bind_resolver("fake3", _Fake([cross]))
            acct = await _insert_account(
                conn,
                domain="acme-robotics.com",
                hq_geo={"city": "Boston", "region": "Massachusetts"},
            )

            worker = AspectProfilingWorker("account", session_factory=conn_session_factory(conn))
            result = await worker.research(_ctx(acct))

            assert result.status is WorkerStatus.PARTIAL  # something was screened out
            assert result.claim_refs == ()  # the cross-entity claim is not surfaced
            assert result.detail["target_lock_rejected"] == 1

    run_async(_run())


# --- tenant guard -----------------------------------------------------------


def test_tenant_private_field_without_tenant_is_flagged() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # a seeded tenant_private resonance field, profiled with NO tenant_id in context.
            acct = await _insert_account(conn)
            worker = AspectProfilingWorker(
                "account.resonance", session_factory=conn_session_factory(conn)
            )
            result = await worker.research(
                _ctx(
                    acct,
                    field_keys=("account.resonance.employee_sentiment",),
                    aspect="account.resonance",
                    tenant_id=None,
                )
            )
            assert result.claim_refs == ()
            assert (
                result.detail["dispositions"]["account.resonance.employee_sentiment"]
                == ProfilingFieldDisposition.TENANT_REQUIRED.value
            )

    run_async(_run())


# --- edge cases (audit coverage) --------------------------------------------


def test_unregistered_field_is_flagged_without_spend() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_source(conn, "fake1", tier=1)
            fake = _Fake([_fake_claim(tier=1, confidence=0.95)])
            bind_resolver("fake1", fake)
            acct = await _insert_account(conn)

            worker = AspectProfilingWorker("account", session_factory=conn_session_factory(conn))
            # the field key is not registered → get_field returns None → flagged, no spend.
            result = await worker.research(_ctx(acct, field_keys=("account.unregistered_field",)))

            assert result.status is WorkerStatus.OK
            assert result.claim_refs == ()
            assert fake.calls == 0
            assert (
                result.detail["dispositions"]["account.unregistered_field"]
                == ProfilingFieldDisposition.SOURCES_EXHAUSTED.value
            )

    run_async(_run())


def test_field_fills_then_next_field_hits_budget_cap() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # two deep fields in one aspect; the first field's claim costs 5 and the envelope is 5,
            # so the second field hits the remaining<=0 pre-check → BUDGET_CAP (a partial converge).
            await _register_test_field(conn, field_key="account.test_signal", tier_plan=("fake1",))
            await _register_test_field(conn, field_key="account.test_signal2", tier_plan=("fake1",))
            await _register_source(conn, "fake1", tier=1, cost=Decimal(5))
            bind_resolver(
                "fake1",
                _Fake([_fake_claim(tier=1, confidence=0.95, cost=Decimal(5))]),
            )
            acct = await _insert_account(conn)

            worker = AspectProfilingWorker("account", session_factory=conn_session_factory(conn))
            result = await worker.research(
                _ctx(
                    acct,
                    field_keys=("account.test_signal", "account.test_signal2"),
                    budget=Decimal(5),
                )
            )

            assert result.status is WorkerStatus.BUDGET_EXCEEDED
            assert len(result.claim_refs) == 1  # the first field's claim is surfaced
            disp = result.detail["dispositions"]
            assert disp["account.test_signal"] == ProfilingFieldDisposition.FILLED.value
            assert disp["account.test_signal2"] == ProfilingFieldDisposition.BUDGET_CAP.value

    run_async(_run())
