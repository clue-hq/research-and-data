"""Provider-neutral Exa resolver integration tests.

The E0 wire/compiler/normalizer contract is covered in test_exa_deep_wire_e0.py. These tests retain
the existing resolver registration and waterfall acceptance with provider doubles only.
"""

from __future__ import annotations

from decimal import Decimal

from clue_core import (
    AccountEntity,
    Claim,
    Entity,
    EntityId,
    ExtractionMethod,
    FieldDef,
    PassKind,
    ResearchMode,
    ReuseScope,
    VerificationStatus,
    account_claim,
    new_entity_id,
    new_run_id,
)
from clue_research.claimstore import ALL_WORKSPACES, claims_for
from clue_research.resolvers import (
    SynthesisResult,
    SynthesizedField,
    register_exa_deep_resolver,
)
from clue_research.sources import StopReason, bind_resolver, get_resolver, resolve_field

from .conftest import rollback_conn, run_async

_PAIN = "account.operational_pain"
_MODE = ResearchMode.ACCOUNT_PROFILING


class _Accounts:
    def __init__(self, account: AccountEntity | None) -> None:
        self._account = account

    def key_for(self, entity_id: EntityId) -> AccountEntity | None:
        return self._account


class _StubBackend:
    def __init__(self, result: SynthesisResult) -> None:
        self._result = result

    def synthesize(self, account: AccountEntity, field: FieldDef) -> SynthesisResult:
        return self._result


def _account(domain: str = "acme.com") -> AccountEntity:
    return AccountEntity(
        id=new_entity_id(),
        canonical_name="Acme Corp",
        primary_domain=domain,
        aliases=("Acme",),
        hq_geo={"country": "US"},
        workspace_id="ws-test",
    )


def _field(key: str = _PAIN) -> FieldDef:
    return FieldDef(
        field_key=key,
        value_type="str",
        tier_plan=("exa_deep", "parallel_task"),
        pass_kind=PassKind.DEEP,
    )


def _on_entity_field(key: str = _PAIN, conf: float = 0.9) -> SynthesizedField:
    return SynthesizedField(
        field_key=key,
        value="Acme runs brittle legacy ETL",
        source_url="https://acme.com/eng",
        evidence_span="Acme runs brittle legacy ETL",
        retrieved_text="Engineering note: Acme runs brittle legacy ETL across teams.",
        confidence=conf,
    )


def test_register_synthesis_wiring_binds_a_tier4_resolver_to_exa_deep() -> None:
    from clue_api.synthesis_wiring import register_synthesis_wiring

    register_synthesis_wiring(accounts=_Accounts(_account()))
    assert get_resolver("exa_deep").tier == 4


# --- end-to-end through the real waterfall (DB-gated) --------------------------------------------


async def _claims(conn: object, entity_id: EntityId, field_key: str) -> list[Claim]:
    return list(await claims_for(conn, entity_id, field_key, scope=ALL_WORKSPACES))  # type: ignore[arg-type]


def test_exa_fires_through_the_waterfall_with_engine_stamped_provenance(require_db: None) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account()
            register_exa_deep_resolver(
                accounts=_Accounts(account),
                backend=_StubBackend(
                    SynthesisResult(fields=(_on_entity_field(),), cost_cents=Decimal(9))
                ),
            )
            entity = account.as_entity()
            run_id = new_run_id()
            result = await resolve_field(conn, entity, _field(), mode=_MODE, run_id=run_id)
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            (claim,) = await _claims(conn, entity.entity_id, _PAIN)
            assert claim.source_key == "exa_deep"  # engine-stamped
            assert claim.source_tier == 4
            assert claim.extraction_method is ExtractionMethod.LLM_SYNTHESIS
            assert claim.run_id == run_id and claim.research_mode is _MODE  # restamped
            assert claim.evidence_span == "Acme runs brittle legacy ETL"
            assert claim.verification_status is VerificationStatus.UNVERIFIED  # no self-promotion
            assert claim.reuse_scope is ReuseScope.PUBLIC_FOOTPRINT  # account.* synthesis is public
            assert claim.cost_cents == Decimal(9)  # the backend's realized cost

    run_async(_run())


def test_swap_seam_waterfall_call_site_unchanged(require_db: None) -> None:
    # A *different* tier-4 resolver bound to the same source_key — the waterfall call site is
    # unchanged (it dispatches through the registry binding, never importing a provider).
    class _StubTier4Resolver:
        tier = 4

        def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
            return [
                account_claim(
                    entity_id=entity.entity_id,
                    field_key=field.field_key,
                    value_json="swapped synthesis value",
                    source_tier=4,
                    extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                    confidence=0.9,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    source_url="https://acme.com/x",
                    evidence_span="swapped synthesis value",
                )
            ]

    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account()
            bind_resolver("exa_deep", _StubTier4Resolver())  # swap behind the same key
            entity = account.as_entity()
            result = await resolve_field(conn, entity, _field(), mode=_MODE, run_id=new_run_id())
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            (claim,) = await _claims(conn, entity.entity_id, _PAIN)
            assert claim.value_json == "swapped synthesis value"
            assert claim.source_key == "exa_deep"

    run_async(_run())


def test_budget_envelope_stops_tier4_spend(require_db: None) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account()
            register_exa_deep_resolver(
                accounts=_Accounts(account),
                backend=_StubBackend(SynthesisResult(fields=(_on_entity_field(),))),
            )
            entity = account.as_entity()
            # exa_deep's seeded manifest cost is 10¢; a 5¢ envelope stops it before the call.
            result = await resolve_field(
                conn, entity, _field(), mode=_MODE, run_id=new_run_id(), budget_envelope=Decimal(5)
            )
            assert result.stop_reason is StopReason.BUDGET_STOP
            assert await _claims(conn, entity.entity_id, _PAIN) == []

    run_async(_run())


def test_realized_cost_recorded_on_the_step(require_db: None) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account()
            register_exa_deep_resolver(
                accounts=_Accounts(account),
                backend=_StubBackend(
                    SynthesisResult(fields=(_on_entity_field(),), cost_cents=Decimal(7))
                ),
            )
            result = await resolve_field(
                conn, account.as_entity(), _field(), mode=_MODE, run_id=new_run_id()
            )
            exa_step = next(s for s in result.per_tier if s.source_key == "exa_deep")
            assert exa_step.cost_cents == Decimal(7)
            assert result.total_cost_cents == Decimal(7)

    run_async(_run())


def test_empty_retrieval_writes_no_claim(require_db: None) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account()
            register_exa_deep_resolver(
                accounts=_Accounts(account),
                backend=_StubBackend(SynthesisResult()),  # empty retrieval
            )
            entity = account.as_entity()
            result = await resolve_field(conn, entity, _field(), mode=_MODE, run_id=new_run_id())
            assert result.claim_refs == ()
            assert await _claims(conn, entity.entity_id, _PAIN) == []
            # the paid miss still records the manifest cost (10¢), not 0.
            exa_step = next(s for s in result.per_tier if s.source_key == "exa_deep")
            assert exa_step.n_claims == 0 and exa_step.cost_cents == Decimal(10)

    run_async(_run())


def test_resonance_synthesis_is_tenant_private(require_db: None) -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account()
            field = _field("account.resonance.culture")
            culture = SynthesizedField(
                field_key="account.resonance.culture",
                value="Acme has a low-trust, high-burnout culture",
                source_url="https://glassdoor.com/acme",
                evidence_span="low-trust, high-burnout culture",
                retrieved_text="Reviewers describe Acme Corp's low-trust, high-burnout culture.",
                confidence=0.95,
            )
            register_exa_deep_resolver(
                accounts=_Accounts(account),
                backend=_StubBackend(SynthesisResult(fields=(culture,), cost_cents=Decimal(9))),
            )
            entity = account.as_entity()
            result = await resolve_field(
                conn, entity, field, mode=_MODE, run_id=new_run_id(), workspace_id="client-1"
            )
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            (claim,) = await _claims(conn, entity.entity_id, "account.resonance.culture")
            assert claim.reuse_scope is ReuseScope.TENANT_PRIVATE
            assert claim.workspace_id == "client-1"

    run_async(_run())
