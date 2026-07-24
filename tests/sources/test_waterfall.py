"""M4.1 acceptance: the trust-tiered waterfall engine (ENG-105).

One test per acceptance criterion: stop-at-first-confident; tier-by-tier advance; tier_exhausted;
tier-4-unbound → no_resolver (no crash); claims written UNVERIFIED with correct provenance; tier-4
null-span unpromotable; provider swap = tier_plan edit; budget_stop; idempotent retry. Resolver
doubles + registered manifests + the in-process binding exercise the engine end to end.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_core import (
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
    ReuseScope,
    SourceManifest,
    UseClass,
    VerificationStatus,
    account_claim,
    can_be_promoted,
    contact_claim,
    new_entity_id,
    new_run_id,
    revalidate_with,
)
from clue_research.claimstore import ALL_WORKSPACES, WorkspaceScope, claims_for, current_value
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


def test_optional_attempt_recorder_observes_the_final_result() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "attempt_probe", tier=1)
            bind_resolver("attempt_probe", _Fake([_claim(100, tier=1, confidence=_HI)]))
            observed = []

            async def record(result):
                observed.append(result)

            result = await resolve_field(
                conn,
                _entity(),
                _field(("attempt_probe",)),
                mode=_MODE,
                run_id=new_run_id(),
                attempt_recorder=record,
            )
            assert observed == [result]

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
                conn, entity.entity_id, "core.employee_count", scope=ALL_WORKSPACES
            )
            assert len(written) == 1
            claim = written[0]
            # confidence-stop is a pre-spend heuristic, NOT a verdict (M9 owns 'verified').
            assert claim.verification_status is VerificationStatus.UNVERIFIED
            assert claim.source_tier == 1
            assert claim.source_key == "t1"  # the producing source, stamped by the engine
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
                conn, entity.entity_id, "account.operational_pain", scope=ALL_WORKSPACES
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
                conn, entity.entity_id, "core.employee_count", scope=ALL_WORKSPACES
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
            # contact.facet.* + crm_import classifies tenant_private (decision #6) → the engine
            # requires the run's workspace_id to stamp it (a private claim must bind to a tenant).
            await resolve_field(
                conn,
                entity,
                field,
                mode=ResearchMode.CONTACT_PROFILING,
                run_id=new_run_id(),
                workspace_id="tenant-x",
            )
            written = await claims_for(
                conn, entity.entity_id, "contact.facet.recent_post", scope=ALL_WORKSPACES
            )
            assert len(written) == 1
            # the manifest's binding strength is authoritative — the engine stamped STRONG.
            assert written[0].identity_binding is IdentityBinding.STRONG
            # the engine stamped the personal claim tenant-private and bound it to the run tenant.
            assert written[0].reuse_scope is ReuseScope.TENANT_PRIVATE
            assert written[0].workspace_id == "tenant-x"

    run_async(_run())


# --- review regressions -----------------------------------------------------


def test_same_tier_retry_attributes_per_source() -> None:
    # Two sources at the SAME tier (apollo misses, clay hits): on retry, idempotency keyed on
    # source_key (not tier) must re-attribute each step to its own source — not credit clay's claim
    # to apollo. Guards the per-source yield substrate.
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "apollo", tier=1, cost=Decimal(3))
            await _register(conn, "clay", tier=1, cost=Decimal(5))
            bind_resolver("apollo", _Fake([]))  # miss
            bind_resolver("clay", _Fake([_claim(100, tier=1, confidence=_HI, cost=Decimal(5))]))
            entity, run_id, field = _entity(), new_run_id(), _field(("apollo", "clay"))

            first = await resolve_field(conn, entity, field, mode=_MODE, run_id=run_id)
            second = await resolve_field(conn, entity, field, mode=_MODE, run_id=run_id)

            for result in (first, second):
                by_source = {s.source_key: s for s in result.per_tier}
                assert by_source["apollo"].n_claims == 0  # apollo genuinely produced nothing
                assert not by_source["apollo"].confident
                assert by_source["clay"].confident  # clay's confident claim stays clay's
                assert by_source["clay"].n_claims == 1
            assert first.claim_refs == second.claim_refs  # no double-write on retry
            written = await claims_for(
                conn, entity.entity_id, "core.employee_count", scope=ALL_WORKSPACES
            )
            assert len(written) == 1 and written[0].source_key == "clay"

    run_async(_run())


def test_idempotent_reuse_not_blocked_by_tightened_budget() -> None:
    # A reused step spends nothing, so a retry with a budget too small to *re-run* it must still
    # reuse the persisted claim (idempotency runs before the budget gate).
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "t1", tier=1, cost=Decimal(5))
            bind_resolver("t1", _Fake([_claim(100, tier=1, confidence=_HI, cost=Decimal(5))]))
            entity, run_id, field = _entity(), new_run_id(), _field(("t1",))
            first = await resolve_field(conn, entity, field, mode=_MODE, run_id=run_id)
            # retry with a budget smaller than the step's estimated cost — reuse must NOT be gated.
            second = await resolve_field(
                conn, entity, field, mode=_MODE, run_id=run_id, budget_envelope=Decimal(1)
            )
            assert second.stop_reason is StopReason.CONFIDENT_HIT
            assert second.claim_refs == first.claim_refs
            assert second.per_tier[0].outcome is StepOutcome.IDEMPOTENT_SKIP

    run_async(_run())


def test_all_inactive_plan_is_no_resolver() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "t1", tier=1, active=False)
            await _register(conn, "t2", tier=2, active=False)
            result = await resolve_field(
                conn, _entity(), _field(("t1", "t2")), mode=_MODE, run_id=new_run_id()
            )
            assert result.stop_reason is StopReason.NO_RESOLVER  # nothing could run
            assert result.claim_refs == ()

    run_async(_run())


def test_empty_tier_plan_is_no_resolver() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            result = await resolve_field(
                conn, _entity(), _field(()), mode=_MODE, run_id=new_run_id()
            )
            assert result.stop_reason is StopReason.NO_RESOLVER
            assert result.claim_refs == () and result.per_tier == ()

    run_async(_run())


# --- tenant stamping at the engine (M4.5, decision #6) ----------------------


def test_engine_stamps_crm_import_claim_tenant_private() -> None:
    # The engine (the only composer) classifies a crm_import claim tenant_private and binds the run
    # tenant — so client data never leaks into the cross-tenant public pool (substrate §2).
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "crm", tier=1)
            bind_resolver(
                "crm",
                _Fake([_claim(100, tier=1, confidence=_HI, method=ExtractionMethod.CRM_IMPORT)]),
            )
            entity = _entity()
            await resolve_field(
                conn,
                entity,
                _field(("crm",)),
                mode=_MODE,
                run_id=new_run_id(),
                workspace_id="tenant-a",
            )
            (claim,) = await claims_for(
                conn, entity.entity_id, "core.employee_count", scope=ALL_WORKSPACES
            )
            assert (
                claim.reuse_scope is ReuseScope.TENANT_PRIVATE and claim.workspace_id == "tenant-a"
            )

    run_async(_run())


def test_engine_keeps_a_public_claim_public_even_when_a_tenant_is_supplied() -> None:
    # A public-footprint (api) claim drops the tenant even if one is passed — it must stay reusable.
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "clay", tier=1)
            bind_resolver("clay", _Fake([_claim(100, tier=1, confidence=_HI)]))  # api → public
            entity = _entity()
            await resolve_field(
                conn,
                entity,
                _field(("clay",)),
                mode=_MODE,
                run_id=new_run_id(),
                workspace_id="tenant-a",
            )
            (claim,) = await claims_for(
                conn, entity.entity_id, "core.employee_count", scope=ALL_WORKSPACES
            )
            assert claim.reuse_scope is ReuseScope.PUBLIC_FOOTPRINT and claim.workspace_id is None

    run_async(_run())


def test_engine_fails_loud_on_a_private_claim_with_no_tenant() -> None:
    # A crm_import claim with NO workspace_id is a wiring error — the engine refuses it rather than
    # silently writing client data into the shared public pool (fail-closed, substrate §2).
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "crm", tier=1)
            bind_resolver(
                "crm",
                _Fake([_claim(100, tier=1, confidence=_HI, method=ExtractionMethod.CRM_IMPORT)]),
            )
            with pytest.raises(ValueError, match="tenant_private"):
                await resolve_field(
                    conn, _entity(), _field(("crm",)), mode=_MODE, run_id=new_run_id()
                )

    run_async(_run())


def test_idempotent_reuse_is_workspace_scoped_no_cross_tenant_private_leak() -> None:
    # Defense-in-depth (substrate §2): even if two tenants shared a run_id (a caller bug — run_id is
    # per-run-per-tenant), the idempotency reuse is tenant-scoped, so tenant-B never receives
    # tenant-A's tenant_private CRM claim. Tenant-B re-resolves and writes its OWN private claim.
    class _FreshCrm:
        tier = 1

        def __init__(self) -> None:
            self.calls = 0

        def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
            self.calls += 1
            return [
                account_claim(
                    entity_id=entity.entity_id,
                    field_key=field.field_key,
                    value_json="customer",
                    source_tier=1,
                    extraction_method=ExtractionMethod.CRM_IMPORT,
                    confidence=1.0,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    source_url="crm://record/1",
                    evidence_span="crm:relationship_status=customer",
                )
            ]

    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "crm", tier=1)
            crm = _FreshCrm()
            bind_resolver("crm", crm)
            entity = _entity()
            run_id = new_run_id()
            field = _field(("crm",), field_key="account.crm_relationship_status")
            a = await resolve_field(
                conn, entity, field, mode=_MODE, run_id=run_id, workspace_id="a"
            )
            b = await resolve_field(
                conn, entity, field, mode=_MODE, run_id=run_id, workspace_id="b"
            )
            assert (
                crm.calls == 2
            )  # tenant-b did NOT reuse tenant-a's private claim — it re-resolved
            assert a.claim_refs != b.claim_refs  # a distinct private claim per tenant
            # Each tenant sees ONLY its own private claim — never the other's.
            a_claims = await claims_for(
                conn, entity.entity_id, scope=WorkspaceScope.for_workspace("a")
            )
            b_claims = await claims_for(
                conn, entity.entity_id, scope=WorkspaceScope.for_workspace("b")
            )
            assert {c.workspace_id for c in a_claims} == {"a"}
            assert {c.workspace_id for c in b_claims} == {"b"}
            field_key = "account.crm_relationship_status"
            assert (
                await current_value(
                    conn, entity.entity_id, field_key, scope=WorkspaceScope.for_workspace("a")
                )
            ) is not None
            assert (
                await current_value(
                    conn, entity.entity_id, field_key, scope=WorkspaceScope.public_only()
                )
            ) is None  # the private claims never surface publicly

    run_async(_run())


def test_claim_tagger_stamps_born_immutable_binding_pre_insert() -> None:
    # The injected claim_tagger runs after engine validation and BEFORE the insert, so it can set a
    # born-immutable column (identity_binding, 0004 trigger): the inserted row carries the tagger's
    # STRONG, not the resolver's WEAK placeholder or a manifest prior (none declared here).
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "crm_t", tier=1, entity_scope=EntityScope.CONTACT)
            placeholder = contact_claim(
                entity_id=new_entity_id(),  # overridden by the fake to the resolved entity
                field_key="contact.facet.recent_post",
                value_json="spoke at KubeCon",
                source_tier=1,
                extraction_method=ExtractionMethod.CRM_IMPORT,
                confidence=_HI,
                run_id=new_run_id(),
                research_mode=ResearchMode.CONTACT_PROFILING,
                identity_binding=IdentityBinding.WEAK,  # placeholder the tagger must override
                use_class=UseClass.PROFESSIONAL_PUBLIC,
            )
            entity = Entity(entity_id=placeholder.entity_id, entity_type=EntityType.CONTACT)
            bind_resolver("crm_t", _Fake([placeholder]))
            field = FieldDef(
                field_key="contact.facet.recent_post",
                value_type="str",
                tier_plan=("crm_t",),
                pass_kind=PassKind.DEEP,
            )

            def tagger(claim: Claim) -> Claim | None:
                return revalidate_with(claim, identity_binding=IdentityBinding.STRONG)

            result = await resolve_field(
                conn,
                entity,
                field,
                mode=ResearchMode.CONTACT_PROFILING,
                run_id=new_run_id(),
                workspace_id="tenant-x",
                claim_tagger=tagger,
            )
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            written = await claims_for(
                conn, entity.entity_id, "contact.facet.recent_post", scope=ALL_WORKSPACES
            )
            assert len(written) == 1
            # born with the tagger's verdict — stamped pre-insert on the immutable column.
            assert written[0].identity_binding is IdentityBinding.STRONG

    run_async(_run())


def test_tagger_drop_removes_claim_and_does_not_stop_the_walk() -> None:
    # A dropped 0.9-confidence claim must NOT produce CONFIDENT_HIT with nothing written — the
    # confident-stop and the TierStep accounting follow the KEPT (post-tagger) set, so the walk
    # continues to the next source as if the claim had never been produced.
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "t1", tier=1)
            await _register(conn, "t2", tier=2)
            r1 = _Fake([_claim(100, tier=1, confidence=_HI)])  # confident — but dropped below
            r2 = _Fake([_claim(101, tier=2, confidence=_HI)])
            bind_resolver("t1", r1)
            bind_resolver("t2", r2)

            def drop_tier1(claim: Claim) -> Claim | None:
                return None if claim.source_key == "t1" else claim

            entity = _entity()
            result = await resolve_field(
                conn,
                entity,
                _field(("t1", "t2")),
                mode=_MODE,
                run_id=new_run_id(),
                claim_tagger=drop_tier1,
            )
            assert (r1.calls, r2.calls) == (1, 1)  # the walk continued past the dropped hit
            assert result.stop_reason is StopReason.CONFIDENT_HIT  # t2's KEPT claim stopped it
            assert len(result.claim_refs) == 1
            t1_step = result.per_tier[0]
            assert t1_step.outcome is StepOutcome.RESOLVED
            assert t1_step.n_claims == 0 and not t1_step.confident  # accounting = the kept set
            written = await claims_for(
                conn, entity.entity_id, "core.employee_count", scope=ALL_WORKSPACES
            )
            assert len(written) == 1
            assert written[0].source_key == "t2"  # the dropped t1 claim was never inserted

    run_async(_run())


def test_source_gate_false_skips_only_that_source_and_none_hooks_match_control() -> None:
    # source_gate=False skips exactly THAT source (GATE_SKIPPED) and the walk continues; and with
    # both hooks None (the default) the engine output is identical to a control run.
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "t1", tier=1)
            await _register(conn, "t2", tier=2)
            r1 = _Fake([_claim(100, tier=1, confidence=_HI)])
            r2 = _Fake([_claim(101, tier=2, confidence=_HI)])
            bind_resolver("t1", r1)
            bind_resolver("t2", r2)

            async def deny_t1(manifest: SourceManifest) -> bool:
                return manifest.source_key != "t1"

            gated = await resolve_field(
                conn,
                _entity(),
                _field(("t1", "t2")),
                mode=_MODE,
                run_id=new_run_id(),
                source_gate=deny_t1,
            )
            assert (r1.calls, r2.calls) == (0, 1)  # exactly t1 skipped; the walk continued
            assert gated.per_tier[0].outcome is StepOutcome.GATE_SKIPPED
            assert gated.stop_reason is StopReason.CONFIDENT_HIT
            assert len(gated.claim_refs) == 1

            # Both hooks None == a control run with neither passed: identical engine output
            # (stop reason, per-step accounting, spend) — only the claim ids differ per entity.
            # Fresh fakes per run: the doubles carry client-generated claim ids, so reusing one
            # across two written runs would collide on the claim PK.
            bind_resolver("t1", _Fake([_claim(100, tier=1, confidence=_HI)]))
            bind_resolver("t2", _Fake([_claim(101, tier=2, confidence=_HI)]))
            control = await resolve_field(
                conn, _entity(), _field(("t1", "t2")), mode=_MODE, run_id=new_run_id()
            )
            bind_resolver("t1", _Fake([_claim(100, tier=1, confidence=_HI)]))
            bind_resolver("t2", _Fake([_claim(101, tier=2, confidence=_HI)]))
            with_none = await resolve_field(
                conn,
                _entity(),
                _field(("t1", "t2")),
                mode=_MODE,
                run_id=new_run_id(),
                claim_tagger=None,
                source_gate=None,
            )
            assert with_none.stop_reason is control.stop_reason
            assert with_none.per_tier == control.per_tier
            assert with_none.total_cost_cents == control.total_cost_cents
            assert len(with_none.claim_refs) == len(control.claim_refs)

    run_async(_run())


def test_resolver_tier_mismatch_is_rejected() -> None:
    # A resolver returning a claim whose tier contradicts its manifest tier corrupts the merge
    # trust order — the engine fails loud rather than writing it.
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register(conn, "t1", tier=1)
            bind_resolver(
                "t1", _Fake([_claim(100, tier=2, confidence=_HI)])
            )  # tier 2 vs manifest 1
            with pytest.raises(ValueError, match="must match the manifest"):
                await resolve_field(
                    conn, _entity(), _field(("t1",)), mode=_MODE, run_id=new_run_id()
                )

    run_async(_run())
