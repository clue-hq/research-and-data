"""M4.4 acceptance: the tier-1 deterministic resolvers, exercised through the real M4.1 waterfall.

One test per acceptance criterion (ENG-122): typed tier-1 ``api`` claims; the Clay↔Apollo swap as a
``tier_plan`` edit (call-counter); fall-through on a miss; NPI vertical-gating; BuiltWith →
``core.primary_tech_stack`` (+ miss → empty, never fabricated); a transient → typed retryable
error with no partial claim; per-call ``cost_cents`` on the claim *and* the trace span; the contact
path (manifest identity-binding + resolver use-class); and registration binding all eight providers.

Every provider here runs on a **backend double** (``CountingBackend`` / ``RaisingBackend`` / empty
double) — no live provider call, no credential — proving the seam, not a network integration.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import JsonValue, SecretStr

from clue_config import Secrets
from clue_core import (
    AccountEntity,
    Entity,
    EntityType,
    ExtractionMethod,
    FieldDef,
    IdentityBinding,
    PassKind,
    ResearchMode,
    ResearchScope,
    Resolver,
    RetryableResolverError,
    ReuseScope,
    UseClass,
    VerificationStatus,
    new_entity_id,
    new_run_id,
)
from clue_obs.otel import ATTR_COST_CENTS, resolve_span
from clue_obs.otel.testing import collect_spans
from clue_research.claimstore import ALL_WORKSPACES, claims_for, register_field
from clue_research.resolvers import (
    DeterministicResolver,
    HttpEnrichmentBackend,
    HttpRequest,
    apollo,
    resolved_field,
)
from clue_research.resolvers.base import ResolvedField
from clue_research.sources import StopReason, bind_resolver, resolve_field
from tests._workspace import seed_workspace

from .conftest import CountingBackend, RaisingBackend, rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

_MODE = ResearchMode.ACCOUNT_PROFILING
_RUN = new_run_id()


def _account() -> Entity:
    return Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)


def _contact() -> Entity:
    return Entity(entity_id=new_entity_id(), entity_type=EntityType.CONTACT)


def _field(
    tier_plan: tuple[str, ...],
    *,
    field_key: str = "core.employee_count",
    value_type: str = "int",
    reuse_scope: ReuseScope | None = None,
) -> FieldDef:
    return FieldDef(
        field_key=field_key,
        value_type=value_type,
        tier_plan=tier_plan,
        pass_kind=PassKind.SCORING,
        reuse_scope=reuse_scope,
    )


def _rf(field_key: str, value: JsonValue, confidence: float = 0.9) -> ResolvedField:
    return resolved_field(
        field_key, value, source_url="https://provider.example/record/1", confidence=confidence
    )


def _bind(source_key: str, fields: list[ResolvedField], cost: Decimal) -> CountingBackend:
    """Bind a counting-backend resolver to ``source_key``; return the backend (for call asserts)."""
    backend = CountingBackend(fields)
    bind_resolver(source_key, DeterministicResolver(backend, cost_cents=cost))
    return backend


# --- AC1: each resolver implements Resolver, tier=1, typed tier-1 api claims ----------------------


def test_resolver_conforms_to_protocol_at_tier_1() -> None:
    resolver = DeterministicResolver(CountingBackend([]), cost_cents=Decimal(0))
    assert isinstance(resolver, Resolver)  # structural: has tier + resolve
    assert resolver.tier == 1


def test_returns_typed_tier1_api_claim_with_full_provenance() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            _bind("clay", [_rf("core.employee_count", 1200, 0.9)], Decimal(5))
            entity = _account()
            result = await resolve_field(conn, entity, _field(("clay",)), mode=_MODE, run_id=_RUN)
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            (claim,) = await claims_for(
                conn, entity.entity_id, "core.employee_count", scope=ALL_WORKSPACES
            )
            assert claim.source_tier == 1
            assert claim.extraction_method is ExtractionMethod.API
            assert claim.evidence_span and claim.evidence_span.strip()  # non-null + non-empty
            assert claim.confidence == pytest.approx(0.9)
            assert claim.cost_cents == Decimal(5)
            assert claim.source_url  # an api claim cites a source
            assert claim.source_key == "clay"  # engine-stamped (the resolver never sets it)
            assert claim.research_mode is _MODE and claim.run_id == _RUN  # engine-stamped
            assert (
                claim.verification_status is VerificationStatus.UNVERIFIED
            )  # pre-spend, not a verdict

    run_async(_run())


# --- AC2: the swap seam — provider change is a tier_plan edit, no code change ----------------


def test_clay_to_apollo_swap_is_a_tier_plan_edit() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            clay = _bind("clay", [_rf("core.employee_count", 100, 0.9)], Decimal(5))
            apollo = _bind("apollo", [_rf("core.employee_count", 200, 0.9)], Decimal(3))
            # same engine, two tier_plans → two providers, zero caller change.
            await resolve_field(
                conn, _account(), _field(("clay",)), mode=_MODE, run_id=new_run_id()
            )
            assert (clay.calls, apollo.calls) == (1, 0)
            await resolve_field(
                conn, _account(), _field(("apollo",)), mode=_MODE, run_id=new_run_id()
            )
            assert (clay.calls, apollo.calls) == (1, 1)

    run_async(_run())


def test_apollo_first_clay_on_miss_call_counter() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            apollo = _bind("apollo", [], Decimal(3))  # miss
            clay = _bind("clay", [_rf("core.employee_count", 100, 0.9)], Decimal(5))
            result = await resolve_field(
                conn, _account(), _field(("apollo", "clay")), mode=_MODE, run_id=new_run_id()
            )
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            assert (apollo.calls, clay.calls) == (1, 1)  # apollo first, clay only on the miss

    run_async(_run())


# --- AC4: NPI activates only for a healthcare ICP/pack (vertical-gating) -----------------------


def test_npi_activates_only_when_a_field_tier_plan_names_it() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # A healthcare pack registers the npi field (the only ICPs whose tier_plan names npi).
            # A <pack>.* field must declare its reuse_scope (ENG-165 W5) and its research_scope
            # (FI-2 P3); NPI is a public registry identifier and a world-fact.
            await register_field(
                conn,
                FieldDef(
                    field_key="healthcare.npi",
                    value_type="str",
                    pass_kind=PassKind.SCORING,
                    reuse_scope=ReuseScope.PUBLIC_FOOTPRINT,
                    research_scope=ResearchScope.PROJECT_NEUTRAL,
                ),
                pack="healthcare",
            )
            npi = _bind("npi", [_rf("healthcare.npi", "1234567890", 0.97)], Decimal(0))
            clay = _bind("clay", [_rf("core.employee_count", 1200, 0.9)], Decimal(5))
            entity = _account()
            # A healthcare field's tier_plan names npi → it runs and returns the registry-id claim.
            hres = await resolve_field(
                conn,
                entity,
                _field(("npi",), field_key="healthcare.npi", value_type="str"),
                mode=_MODE,
                run_id=new_run_id(),
            )
            assert hres.stop_reason is StopReason.CONFIDENT_HIT
            assert npi.calls == 1
            (npi_claim,) = await claims_for(
                conn, entity.entity_id, "healthcare.npi", scope=ALL_WORKSPACES
            )
            assert npi_claim.value_json == "1234567890" and npi_claim.source_tier == 1
            # A non-healthcare field's tier_plan does NOT name npi → npi is never invoked for it.
            await resolve_field(conn, entity, _field(("clay",)), mode=_MODE, run_id=new_run_id())
            assert npi.calls == 1 and clay.calls == 1  # npi count unchanged — not invoked

    run_async(_run())


# --- AC5: BuiltWith → core.primary_tech_stack tier-1; miss → empty, never fabricated --------------


def test_builtwith_populates_primary_tech_stack() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            _bind(
                "builtwith",
                [_rf("core.primary_tech_stack", ["snowflake", "dbt"], 0.92)],
                Decimal(2),
            )
            entity = _account()
            await resolve_field(
                conn,
                entity,
                _field(("builtwith",), field_key="core.primary_tech_stack", value_type="list"),
                mode=_MODE,
                run_id=new_run_id(),
            )
            (claim,) = await claims_for(
                conn, entity.entity_id, "core.primary_tech_stack", scope=ALL_WORKSPACES
            )
            assert claim.value_json == ["snowflake", "dbt"] and claim.source_tier == 1

    run_async(_run())


def test_builtwith_miss_writes_no_fabricated_stack() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            bw = _bind("builtwith", [], Decimal(2))  # hard miss
            entity = _account()
            result = await resolve_field(
                conn,
                entity,
                _field(("builtwith",), field_key="core.primary_tech_stack", value_type="list"),
                mode=_MODE,
                run_id=new_run_id(),
            )
            assert bw.calls == 1
            assert result.stop_reason is StopReason.TIER_EXHAUSTED  # ran, nothing confident
            assert result.claim_refs == ()
            written = await claims_for(
                conn, entity.entity_id, "core.primary_tech_stack", scope=ALL_WORKSPACES
            )
            assert written == []  # nothing fabricated

    run_async(_run())


# --- AC6: transient → typed retryable error, no partial claim; hard miss → empty ------------------


def test_transient_failure_raises_retryable_and_writes_no_partial_claim() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            backend = RaisingBackend()
            bind_resolver("clay", DeterministicResolver(backend, cost_cents=Decimal(5)))
            entity = _account()
            with pytest.raises(RetryableResolverError):
                await resolve_field(
                    conn, entity, _field(("clay",)), mode=_MODE, run_id=new_run_id()
                )
            assert backend.calls == 1
            written = await claims_for(
                conn, entity.entity_id, "core.employee_count", scope=ALL_WORKSPACES
            )
            assert written == []  # the raise precedes any write — no guessed/partial claim

    run_async(_run())


# --- AC7: per-call cost_cents on the claim AND the trace span -------------------------------------


def test_cost_recorded_on_claim_and_resolve_span() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            _bind("clay", [_rf("core.employee_count", 1200, 0.9)], Decimal(5))
            entity = _account()
            with collect_spans() as spans:
                result = await resolve_field(
                    conn, entity, _field(("clay",)), mode=_MODE, run_id=new_run_id()
                )
            (claim,) = await claims_for(
                conn, entity.entity_id, "core.employee_count", scope=ALL_WORKSPACES
            )
            assert claim.cost_cents == Decimal(5)
            assert result.per_tier[0].cost_cents == Decimal(5)
            resolve_spans = [
                s for s in spans.get_finished_spans() if s.name == resolve_span("clay")
            ]
            assert resolve_spans, "the resolve.<source> span must be emitted"
            attrs = resolve_spans[0].attributes
            assert attrs is not None
            assert float(str(attrs[ATTR_COST_CENTS])) == 5.0  # cost surfaced on the trace span

    run_async(_run())


def test_per_call_cost_attributed_to_first_claim_only() -> None:
    # One call yielding several claims must cost the call price ONCE (the waterfall sums per-claim
    # cost) — the full price on every claim would over-count the step/budget.
    async def _run() -> None:
        async with rollback_conn() as conn:
            _bind(
                "clay",
                [_rf("core.employee_count", 1200, 0.9), _rf("core.employee_count", 1201, 0.85)],
                Decimal(5),
            )
            entity = _account()
            result = await resolve_field(
                conn, entity, _field(("clay",)), mode=_MODE, run_id=new_run_id()
            )
            written = await claims_for(
                conn, entity.entity_id, "core.employee_count", scope=ALL_WORKSPACES
            )
            assert sorted(c.cost_cents for c in written) == [Decimal(0), Decimal(5)]
            assert result.per_tier[0].cost_cents == Decimal(5)  # the step total = one call's price

    run_async(_run())


def test_paid_call_that_misses_still_records_its_cost() -> None:
    # A billed provider call that hard-misses (returns no claims) still cost its price; the step
    # records the manifest's per-call cost (clay's seed cost = 5), not 0 — otherwise per-source
    # economics would silently under-count every paid miss.
    async def _run() -> None:
        async with rollback_conn() as conn:
            backend = _bind("clay", [], Decimal(5))  # miss; clay's seeded manifest cost is 5
            result = await resolve_field(
                conn, _account(), _field(("clay",)), mode=_MODE, run_id=new_run_id()
            )
            assert backend.calls == 1
            assert result.claim_refs == ()  # nothing written
            assert result.per_tier[0].cost_cents == Decimal(5)  # the paid miss still costs 5, not 0
            assert result.total_cost_cents == Decimal(5)

    run_async(_run())


# --- the contact path: manifest identity-binding + resolver use-class -----------------------------


def test_contact_binding_is_stamped_from_the_manifest_not_the_placeholder() -> None:
    # build_claim's placeholder binding is ALWAYS WEAK; the engine overwrites it with the manifest's
    # strength. crm declares STRONG, apollo WEAK — a STRONG result can ONLY come from the manifest,
    # which distinguishes manifest-stamping from the resolver placeholder (the prior test, which
    # used only a WEAK manifest, could not tell them apart).
    async def _run() -> None:
        async with rollback_conn() as conn:
            workspace_id = await seed_workspace(conn, "ws-test")
            # ``core.work_email`` is the registry's ``{address, status}`` object since D4-b
            # (decision 6); the subject here is the *binding* stamp, so the values just have to be
            # the shape the field declares. The provider adapters that map this key (clay, apollo,
            # zoominfo) still normalize a bare address string and are unwired in every production
            # entrypoint — writing one now fails loudly at the registry instead of storing an
            # ungradeable address, which is the fail-closed direction.
            _bind(
                "crm",
                [_rf("core.work_email", {"address": "jordan@acme.com", "status": "unverified"})],
                Decimal(0),
            )
            _bind(
                "apollo",
                [_rf("core.work_email", {"address": "alex@acme.com", "status": "unverified"})],
                Decimal(3),
            )

            strong_contact = _contact()
            await resolve_field(
                conn,
                strong_contact,
                _field(
                    ("crm",),
                    field_key="core.work_email",
                    value_type="object",
                    reuse_scope=ReuseScope.TENANT_PRIVATE,
                ),
                mode=ResearchMode.CONTACT_PROFILING,
                run_id=new_run_id(),
                workspace_id=workspace_id,
            )
            (strong_claim,) = await claims_for(
                conn, strong_contact.entity_id, "core.work_email", scope=ALL_WORKSPACES
            )
            assert strong_claim.entity_type is EntityType.CONTACT
            assert (
                strong_claim.identity_binding is IdentityBinding.STRONG
            )  # from crm's manifest only
            assert (
                strong_claim.use_class is UseClass.PROFESSIONAL_PUBLIC
            )  # resolver-set, not engine
            assert (
                strong_claim.source_tier == 1
                and strong_claim.extraction_method is ExtractionMethod.API
            )

            weak_contact = _contact()
            await resolve_field(
                conn,
                weak_contact,
                _field(
                    ("apollo",),
                    field_key="core.work_email",
                    value_type="object",
                    reuse_scope=ReuseScope.TENANT_PRIVATE,
                ),
                mode=ResearchMode.CONTACT_PROFILING,
                run_id=new_run_id(),
                workspace_id=workspace_id,
            )
            (weak_claim,) = await claims_for(
                conn, weak_contact.entity_id, "core.work_email", scope=ALL_WORKSPACES
            )
            assert weak_claim.identity_binding is IdentityBinding.WEAK  # from apollo's manifest

    run_async(_run())


def test_apollo_funding_object_writes_through_value_schema_end_to_end() -> None:
    # Drive apollo's REAL normalize for account.recent_funding (an object-typed registry field)
    # through the waterfall + insert_claim's value-schema validation — the contract a per-field
    # normalize test in isolation cannot catch (a string value here would be rejected at write).
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = AccountEntity(
                id=new_entity_id(),
                canonical_name="Acme",
                primary_domain="acme.com",
                workspace_id="ws-test",
            )

            class _Accounts:
                def key_for(self, entity_id: object) -> AccountEntity:
                    return account

            def _http(url: str, **kwargs: object) -> dict[str, object]:
                return {"funding_total_usd": 50_000_000, "latest_funding_stage": "Series B"}

            def _stub_request(acct: AccountEntity, field: FieldDef, token: object) -> HttpRequest:
                return HttpRequest(url="https://provider.test/funding")

            backend = HttpEnrichmentBackend(
                source_key="apollo",
                auth_ref="CLUE_APOLLO_API_KEY",
                build_request=_stub_request,
                normalize=apollo.normalize,
                accounts=_Accounts(),
                http=_http,
                secrets=Secrets(apollo_api_key=SecretStr("apollo-fixture-key")),
            )
            bind_resolver("apollo", DeterministicResolver(backend, cost_cents=Decimal(3)))
            entity = account.as_entity()
            await resolve_field(
                conn,
                entity,
                _field(("apollo",), field_key="account.recent_funding", value_type="object"),
                mode=_MODE,
                run_id=new_run_id(),
            )
            (claim,) = await claims_for(
                conn, entity.entity_id, "account.recent_funding", scope=ALL_WORKSPACES
            )
            assert claim.value_json == {"amount_usd": 50_000_000, "round": "Series B"}
            assert claim.source_tier == 1 and claim.extraction_method is ExtractionMethod.API

    run_async(_run())
