"""M4.1 acceptance: the trust-tiered waterfall engine (ENG-105).

One test per acceptance criterion: stop-at-first-confident; tier-by-tier advance; tier_exhausted;
tier-4-unbound → no_resolver (no crash); claims written UNVERIFIED with correct provenance; tier-4
null-span unpromotable; provider swap = tier_plan edit; budget_stop; idempotent retry. Resolver
doubles + registered manifests + the in-process binding exercise the engine end to end.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_research.claimstore import ALL_TENANTS, claims_for
from clue_research.core import (
    Claim,
    Entity,
    EntityScope,
    EntityType,
    ExtractionMethod,
    FieldDef,
    IdentityBinding,
    Modality,
    PassKind,
    ResearchMode,
    SourceManifest,
    UseClass,
    VerificationStatus,
    account_claim,
    can_be_promoted,
    contact_claim,
    new_entity_id,
    new_run_id,
)
from clue_research.sources import (
    RegistrySourceManifest,
    StepOutcome,
    StopReason,
    bind_resolver,
    register_source,
    resolve_field,
    resolve_fields,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

_MODE = ResearchMode.ACCOUNT_PROFILING
# core.employee_count is field-class CORE → confidence threshold 0.8 (engine default, decision #1).
_HI = 0.9  # clears the 0.8 core threshold
_LO = 0.5  # below it


class _Fake:
    """A resolver double: returns a preset claim list and counts calls."""

    tier = 1  # the engine reads tier from the manifest, not here; present for protocol conformance

    def __init__(self, claims: list[Claim]) -> None:
        self._claims = claims
        self.calls = 0

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        self.calls += 1
        # a real resolver builds claims for the entity it was handed; mirror that here.
        return [c.model_copy(update={"entity_id": entity.entity_id}) for c in self._claims]


def _entity() -> Entity:
    return Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)


def _field(tier_plan: tuple[str, ...], *, field_key: str = "core.employee_count") -> FieldDef:
    return FieldDef(
        field_key=field_key, value_type="int", tier_plan=tier_plan, pass_kind=PassKind.SCORING
    )


def _claim(
    value: object,
    *,
    tier: int,
    confidence: float,
    field_key: str = "core.employee_count",
    method: ExtractionMethod = ExtractionMethod.API,
    span: str | None = "evidence",
    cost: Decimal = Decimal(0),
) -> Claim:
    # placeholder entity_id/run_id/research_mode — the fake stamps entity_id, the engine the rest.
    return account_claim(
        entity_id=new_entity_id(),
        field_key=field_key,
        value_json=value,
        source_tier=tier,
        extraction_method=method,
        confidence=confidence,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://example.com/x",
        evidence_span=span,
        cost_cents=cost,
    )


async def _register(
    conn: object,
    source_key: str,
    *,
    tier: int,
    cost: Decimal = Decimal(0),
    active: bool = True,
    entity_scope: EntityScope = EntityScope.ACCOUNT,
    identity_binding: IdentityBinding | None = None,
) -> None:
    modality = Modality.TEXT if tier == 4 else Modality.STRUCTURED
    yields = ("contact",) if entity_scope is EntityScope.CONTACT else ("account",)
    await register_source(
        conn,
        RegistrySourceManifest(
            manifest=SourceManifest(
                source_key=source_key,
                modality=modality,
                entity_scope=entity_scope,
                yields=yields,
                tier=tier,
                cost_cents=cost,
                identity_binding_strength=identity_binding,
            ),
            active=active,
        ),
    )


# --- stop-at-first-confident ------------------------------------------------


def test_confident_tier1_calls_only_tier1() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "t1", tier=1)
            await _register(conn, "t2", tier=2)
            await _register(conn, "t3", tier=3)
            r1, r2, r3 = _Fake([_claim(100, tier=1, confidence=_HI)]), _Fake([]), _Fake([])
            bind_resolver("t1", r1)
            bind_resolver("t2", r2)
            bind_resolver("t3", r3)
            result = await resolve_field(
                conn, _entity(), _field(("t1", "t2", "t3")), mode=_MODE, run_id=new_run_id()
            )
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            assert (r1.calls, r2.calls, r3.calls) == (1, 0, 0)  # only tier-1 called
            assert len(result.claim_refs) == 1

    run_async(_run())


def test_advances_until_first_confident() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "t1", tier=1)
            await _register(conn, "t2", tier=2)
            await _register(conn, "t3", tier=3)
            r1 = _Fake([_claim(100, tier=1, confidence=_LO)])  # below threshold
            r2 = _Fake([_claim(101, tier=2, confidence=_HI)])  # confident
            r3 = _Fake([_claim(102, tier=3, confidence=_HI)])
            bind_resolver("t1", r1)
            bind_resolver("t2", r2)
            bind_resolver("t3", r3)
            result = await resolve_field(
                conn, _entity(), _field(("t1", "t2", "t3")), mode=_MODE, run_id=new_run_id()
            )
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            assert (r1.calls, r2.calls, r3.calls) == (1, 1, 0)
            assert len(result.claim_refs) == 2  # the below-threshold tier-1 claim is still written

    run_async(_run())


def test_tier_exhausted_when_none_confident() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "t1", tier=1)
            await _register(conn, "t2", tier=2)
            r1 = _Fake([_claim(100, tier=1, confidence=_LO)])
            r2 = _Fake([_claim(101, tier=2, confidence=_LO)])
            bind_resolver("t1", r1)
            bind_resolver("t2", r2)
            result = await resolve_field(
                conn, _entity(), _field(("t1", "t2")), mode=_MODE, run_id=new_run_id()
            )
            assert result.stop_reason is StopReason.TIER_EXHAUSTED
            assert (r1.calls, r2.calls) == (1, 1)
            assert len(result.claim_refs) == 2  # all written; the merge may emit empty+flagged

    run_async(_run())


# --- tier-4 absent: correct empty, not a crash ------------------------------


def test_tier4_unbound_yields_no_resolver_not_crash() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "exa_deep_t", tier=4)  # registered, but NO resolver bound (M11)
            result = await resolve_field(
                conn,
                _entity(),
                _field(("exa_deep_t",), field_key="account.operational_pain"),
                mode=_MODE,
                run_id=new_run_id(),
            )
            assert result.stop_reason is StopReason.NO_RESOLVER
            assert result.claim_refs == ()
            assert result.per_tier[0].outcome is StepOutcome.NO_RESOLVER

    run_async(_run())


# --- written-claim provenance + unverified ----------------------------------


def test_written_claims_are_unverified_with_correct_provenance() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "t1", tier=1)
            bind_resolver("t1", _Fake([_claim(100, tier=1, confidence=_HI, span="from the 10-K")]))
            entity = _entity()
            run_id = new_run_id()
            result = await resolve_field(conn, entity, _field(("t1",)), mode=_MODE, run_id=run_id)
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            written = await claims_for(
                conn, entity.entity_id, "core.employee_count", scope=ALL_TENANTS
            )
            assert len(written) == 1
            claim = written[0]
            # confidence-stop is a pre-spend heuristic, NOT a verdict (M9 owns 'verified').
            assert claim.verification_status is VerificationStatus.UNVERIFIED
            assert claim.source_tier == 1
            assert claim.research_mode is _MODE  # stamped by the engine from the run mode
            assert claim.run_id == run_id  # stamped by the engine
            assert claim.evidence_span == "from the 10-K"  # resolver's span preserved

    run_async(_run())


def test_tier4_null_span_written_unverified_and_unpromotable() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "exa_deep_t", tier=4)
            bind_resolver(
                "exa_deep_t",
                _Fake(
                    [
                        _claim(
                            "synthesized pain",
                            tier=4,
                            confidence=_HI,
                            field_key="account.operational_pain",
                            method=ExtractionMethod.LLM_SYNTHESIS,
                            span=None,  # tier-4 with no evidence span
                        )
                    ]
                ),
            )
            entity = _entity()
            result = await resolve_field(
                conn,
                entity,
                _field(("exa_deep_t",), field_key="account.operational_pain"),
                mode=_MODE,
                run_id=new_run_id(),
            )
            assert result.stop_reason is StopReason.CONFIDENT_HIT  # 0.9 >= account threshold 0.75
            written = await claims_for(
                conn, entity.entity_id, "account.operational_pain", scope=ALL_TENANTS
            )
            assert len(written) == 1
            assert written[0].verification_status is VerificationStatus.UNVERIFIED
            assert not can_be_promoted(written[0])  # tier-4 + null span ⇒ never promotable

    run_async(_run())


# --- the swap seam: provider change is a tier_plan edit ---------------------


def test_provider_swap_is_a_tier_plan_edit_no_code_change() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "clay", tier=1)
            await _register(conn, "apollo", tier=1)
            clay = _Fake([_claim(100, tier=1, confidence=_HI)])
            apollo = _Fake([_claim(200, tier=1, confidence=_HI)])
            bind_resolver("clay", clay)
            bind_resolver("apollo", apollo)
            # same engine, two different tier_plans → two different resolvers, zero code change.
            await resolve_field(conn, _entity(), _field(("clay",)), mode=_MODE, run_id=new_run_id())
            assert (clay.calls, apollo.calls) == (1, 0)
            await resolve_field(
                conn, _entity(), _field(("apollo",)), mode=_MODE, run_id=new_run_id()
            )
            assert (clay.calls, apollo.calls) == (1, 1)

    run_async(_run())


def test_falls_through_to_second_provider_on_miss() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "apollo", tier=1)
            await _register(conn, "clay", tier=1)
            apollo = _Fake([])  # miss
            clay = _Fake([_claim(100, tier=1, confidence=_HI)])
            bind_resolver("apollo", apollo)
            bind_resolver("clay", clay)
            result = await resolve_field(
                conn, _entity(), _field(("apollo", "clay")), mode=_MODE, run_id=new_run_id()
            )
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            assert (apollo.calls, clay.calls) == (1, 1)  # apollo first, then clay on the miss

    run_async(_run())


# --- budget --------------------------------------------------------------


def test_budget_stop_halts_before_the_exceeding_call() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "t1", tier=1, cost=Decimal(5))
            await _register(conn, "t2", tier=2, cost=Decimal(5))
            t1 = _Fake([_claim(100, tier=1, confidence=_LO, cost=Decimal(5))])  # below threshold
            t2 = _Fake([_claim(101, tier=2, confidence=_HI, cost=Decimal(5))])
            bind_resolver("t1", t1)
            bind_resolver("t2", t2)
            # budget 7: t1 (est 5) runs; t2 would push spend to 10 > 7 → halt before calling t2.
            result = await resolve_field(
                conn,
                _entity(),
                _field(("t1", "t2")),
                mode=_MODE,
                run_id=new_run_id(),
                budget_envelope=Decimal(7),
            )
            assert result.stop_reason is StopReason.BUDGET_STOP
            assert (t1.calls, t2.calls) == (1, 0)
            assert result.total_cost_cents == Decimal(5)

    run_async(_run())


# --- idempotent retry -------------------------------------------------------


def test_idempotent_retry_does_not_double_write() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "t1", tier=1)
            fake = _Fake([_claim(100, tier=1, confidence=_HI)])
            bind_resolver("t1", fake)
            entity, run_id, field = _entity(), new_run_id(), _field(("t1",))
            first = await resolve_field(conn, entity, field, mode=_MODE, run_id=run_id)
            second = await resolve_field(conn, entity, field, mode=_MODE, run_id=run_id)
            assert fake.calls == 1  # the retried step is reused, not re-resolved
            assert first.claim_refs == second.claim_refs  # same claim id, no second write
            assert second.per_tier[0].outcome is StepOutcome.IDEMPOTENT_SKIP
            written = await claims_for(
                conn, entity.entity_id, "core.employee_count", scope=ALL_TENANTS
            )
            assert len(written) == 1  # exactly one claim despite two resolve_field calls

    run_async(_run())


# --- inactive / unregistered steps ------------------------------------------


def test_inactive_source_is_skipped() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "t1", tier=1, active=False)
            await _register(conn, "t2", tier=2)
            t1 = _Fake([_claim(100, tier=1, confidence=_HI)])
            t2 = _Fake([_claim(101, tier=2, confidence=_HI)])
            bind_resolver("t1", t1)
            bind_resolver("t2", t2)
            result = await resolve_field(
                conn, _entity(), _field(("t1", "t2")), mode=_MODE, run_id=new_run_id()
            )
            assert t1.calls == 0  # inactive → never called
            assert t2.calls == 1
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            assert result.per_tier[0].outcome is StepOutcome.INACTIVE

    run_async(_run())


def test_unregistered_source_in_tier_plan_is_no_resolver() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            result = await resolve_field(
                conn, _entity(), _field(("ghost_source",)), mode=_MODE, run_id=new_run_id()
            )
            assert result.stop_reason is StopReason.NO_RESOLVER
            assert result.per_tier[0].outcome is StepOutcome.UNREGISTERED

    run_async(_run())


# --- batch shares the budget across fields ----------------------------------


def test_resolve_fields_shares_budget_across_fields() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "t1", tier=1, cost=Decimal(5))
            bind_resolver("t1", _Fake([_claim(100, tier=1, confidence=_HI, cost=Decimal(5))]))
            f1 = _field(("t1",), field_key="core.employee_count")
            f2 = _field(("t1",), field_key="core.primary_domain")
            # budget 7: first field spends 5; the second would exceed → budget_stop on the 2nd.
            results = await resolve_fields(
                conn,
                _entity(),
                [f1, f2],
                mode=_MODE,
                run_id=new_run_id(),
                budget_envelope=Decimal(7),
            )
            assert results[0].stop_reason is StopReason.CONFIDENT_HIT
            assert results[1].stop_reason is StopReason.BUDGET_STOP

    run_async(_run())


# --- contact identity-binding is stamped from the manifest ------------------


def test_contact_claim_identity_binding_from_manifest() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(
                conn,
                "crm_t",
                tier=1,
                entity_scope=EntityScope.CONTACT,
                identity_binding=IdentityBinding.STRONG,
            )
            # resolver builds a contact.facet claim with WEAK binding; the manifest says STRONG.
            contact = contact_claim(
                entity_id=new_entity_id(),  # overridden below to the resolved entity
                field_key="contact.facet.recent_post",
                value_json="spoke at KubeCon",
                source_tier=1,
                extraction_method=ExtractionMethod.CRM_IMPORT,
                confidence=_HI,
                run_id=new_run_id(),
                research_mode=ResearchMode.CONTACT_PROFILING,
                identity_binding=IdentityBinding.WEAK,
                use_class=UseClass.PROFESSIONAL_PUBLIC,
            )
            entity = Entity(entity_id=contact.entity_id, entity_type=EntityType.CONTACT)
            bind_resolver("crm_t", _Fake([contact]))
            field = FieldDef(
                field_key="contact.facet.recent_post",
                value_type="str",
                tier_plan=("crm_t",),
                pass_kind=PassKind.DEEP,
            )
            await resolve_field(
                conn, entity, field, mode=ResearchMode.CONTACT_PROFILING, run_id=new_run_id()
            )
            written = await claims_for(
                conn, entity.entity_id, "contact.facet.recent_post", scope=ALL_TENANTS
            )
            assert len(written) == 1
            # the manifest's binding strength is authoritative — the engine stamped STRONG.
            assert written[0].identity_binding is IdentityBinding.STRONG

    run_async(_run())
