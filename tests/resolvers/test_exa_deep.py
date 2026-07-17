"""M11.1 acceptance — the Exa Deep tier-4 grounded-synthesis resolver (ENG-143).

Two layers: (1) **pure** tests of the Exa-specific pieces — the entity-bound (target-locked) query
shaping, the highlight→grounded-field normalization, score clamping, the realized-cost parse, and
the full backend over a fake HTTP transport (credential + build + normalize, no network/DB); and
(2) **end-to-end** tests through the real M4.1 waterfall (DB-gated; skip without a DB) proving the
engine stamps the provenance, the swap seam holds, the budget cap stops tier-4 spend,
the realized cost is recorded, an empty retrieval writes nothing, and resonance synthesis is
tenant-private. The provider call is always a double — no live Exa call, no key.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import SecretStr

from clue_config import Secrets
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
from clue_research.claimstore import ALL_TENANTS, claims_for
from clue_research.resolvers import (
    RetryableResolverError,
    SynthesisResult,
    SynthesizedField,
    register_exa_deep_resolver,
)
from clue_research.resolvers.exa import (
    DEFAULT_EXA_CONFIG,
    ExaDeepConfig,
    build_exa_request,
    make_backend,
    normalize_exa_response,
)
from clue_research.sources import StopReason, bind_resolver, get_resolver, resolve_field

from .conftest import rollback_conn, run_async

_PAIN = "account.operational_pain"
_MODE = ResearchMode.ACCOUNT_PROFILING


# --- shared fixtures/doubles ---------------------------------------------------------------------


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


# --- pure: the entity-bound (target-locked) query -------------------------------------------------


def test_build_exa_request_is_entity_bound_and_authed() -> None:
    request = build_exa_request(_account(), _field(), SecretStr("secret-key"))
    assert request.method == "POST"
    assert request.url == DEFAULT_EXA_CONFIG.endpoint
    assert request.headers["x-api-key"] == "secret-key"
    body = request.json_body or {}
    query = body["query"]
    assert "Acme Corp" in query  # canonical name
    assert "acme.com" in query  # primary domain
    assert "US" in query  # hq_geo disambiguator
    assert "operational" in query  # field intent
    assert body["numResults"] == DEFAULT_EXA_CONFIG.num_results
    assert "highlights" in body["contents"]


def test_build_exa_request_omits_auth_without_token() -> None:
    request = build_exa_request(_account(), _field(), None)
    assert "x-api-key" not in request.headers


# --- pure: highlight → grounded field normalization ----------------------------------------------


def test_normalize_maps_each_highlight_to_a_grounded_field() -> None:
    payload = {
        "results": [
            {
                "url": "https://glassdoor.com/acme",
                "text": "Reviewers say morale is low and attrition is high at Acme Corp.",
                "highlights": ["morale is low", "attrition is high"],
                "highlightScores": [0.81, 0.77],
            }
        ],
        "costDollars": {"total": 0.1},
    }
    result = normalize_exa_response(payload, _field())
    assert [f.value for f in result.fields] == ["morale is low", "attrition is high"]
    assert all(f.source_url == "https://glassdoor.com/acme" for f in result.fields)
    assert all(f.evidence_span == f.value for f in result.fields)
    assert all(f.evidence_span in f.retrieved_text for f in result.fields)  # grounded
    assert result.fields[0].confidence == pytest.approx(0.81)
    assert result.cost_cents == Decimal("10.0")  # 0.1 dollars -> cents


def test_normalize_drops_result_without_url() -> None:
    payload = {"results": [{"highlights": ["x"], "highlightScores": [0.9]}]}
    assert normalize_exa_response(payload, _field()).fields == ()


def test_normalize_drops_result_without_highlight() -> None:
    payload = {"results": [{"url": "https://acme.com", "text": "no highlights here"}]}
    assert normalize_exa_response(payload, _field()).fields == ()


def test_normalize_empty_payload_is_empty_result() -> None:
    result = normalize_exa_response({}, _field())
    assert result.fields == ()
    assert result.cost_cents == Decimal(0)


def test_normalize_clamps_out_of_range_scores() -> None:
    payload = {
        "results": [
            {
                "url": "https://acme.com",
                "text": "alpha beta",
                "highlights": ["alpha", "beta"],
                "highlightScores": [1.5, -0.2],  # out of [0,1]
            }
        ]
    }
    confs = [f.confidence for f in normalize_exa_response(payload, _field()).fields]
    assert confs == [1.0, 0.0]


def test_normalize_filters_below_min_confidence() -> None:
    cfg = ExaDeepConfig(min_confidence=0.5)
    payload = {
        "results": [
            {
                "url": "https://acme.com",
                "text": "weak strong",
                "highlights": ["weak", "strong"],
                "highlightScores": [0.3, 0.9],  # 0.3 < 0.5 dropped
            }
        ]
    }
    fields = normalize_exa_response(payload, _field(), config=cfg).fields
    assert [f.value for f in fields] == ["strong"]


def test_make_backend_synthesizes_via_fake_http() -> None:
    # The full Exa backend orchestration without a network: credential resolution from auth_ref +
    # build_request + the fake transport + normalize. No DB.
    payload = {
        "results": [
            {
                "url": "https://acme.com/eng",
                "text": "Acme Corp runs brittle legacy ETL across teams.",
                "highlights": ["runs brittle legacy ETL"],
                "highlightScores": [0.86],
            }
        ],
        "costDollars": {"total": 0.05},
    }
    calls: list[dict[str, object]] = []

    def _fake_http(url: str, **kwargs: object) -> dict[str, object]:
        calls.append({"url": url, **kwargs})
        return payload

    backend = make_backend(http=_fake_http, secrets=Secrets(exa_api_key=SecretStr("test-key")))
    result = backend.synthesize(_account(), _field())
    assert len(calls) == 1 and calls[0]["url"] == DEFAULT_EXA_CONFIG.endpoint
    assert calls[0]["method"] == "POST"
    assert [f.value for f in result.fields] == ["runs brittle legacy ETL"]
    assert result.cost_cents == Decimal("5.0")


def test_normalize_drops_highlight_absent_from_present_page_text() -> None:
    # Grounded-only with teeth: page text IS present but does not contain the highlight (a provider
    # bug or a tampered/injected response) → the record is dropped, not masked by a span fallback.
    payload = {
        "results": [
            {
                "url": "https://acme.com",
                "text": "the page is entirely about something else",
                "highlights": ["a fabricated passage that is not on the page"],
                "highlightScores": [0.95],
            }
        ]
    }
    assert normalize_exa_response(payload, _field()).fields == ()


def test_normalize_keeps_highlight_only_response_without_page_text() -> None:
    # A genuinely highlight-only response (no page ``text``) grounds on the passage itself.
    payload = {
        "results": [
            {
                "url": "https://acme.com",
                "highlights": ["a grounded passage"],
                "highlightScores": [0.9],
            }
        ]
    }
    fields = normalize_exa_response(payload, _field()).fields
    assert len(fields) == 1 and fields[0].retrieved_text == "a grounded passage"


# --- pure: config-driven cost / timeout / retry (AC7, AC11) --------------------------------------


def test_make_backend_threads_timeout_and_retries_from_config() -> None:
    backend = make_backend(config=ExaDeepConfig(timeout_s=42.0, retries=5))
    assert backend._timeout == 42.0
    assert backend._retries == 5


def test_transient_http_fault_propagates_not_swallowed() -> None:
    # The transient-vs-hard-miss contract M7 relies on: a retryable fault propagates rather than
    # being swallowed into an empty SynthesisResult.
    def _raising_http(url: str, **kwargs: object) -> dict[str, object]:
        raise RetryableResolverError("simulated transient provider failure")

    backend = make_backend(http=_raising_http, secrets=Secrets(exa_api_key=SecretStr("k")))
    with pytest.raises(RetryableResolverError):
        backend.synthesize(_account(), _field())


def test_config_default_cost_cents_is_honored_on_a_zero_cost_call() -> None:
    # When the backend reports no realized cost, the attributed default comes from
    # config.default_cost_cents (AC11 config-driven), overriding the seed-manifest default.
    account = _account()
    register_exa_deep_resolver(
        accounts=_Accounts(account),
        backend=_StubBackend(SynthesisResult(fields=(_on_entity_field(),), cost_cents=Decimal(0))),
        config=ExaDeepConfig(default_cost_cents=Decimal(25)),
    )
    (claim,) = get_resolver("exa_deep").resolve(account.as_entity(), _field())
    assert claim.cost_cents == Decimal(25)


def test_register_synthesis_wiring_binds_a_tier4_resolver_to_exa_deep() -> None:
    # The PF-7 api-composition-root path (not just a direct register_exa_deep_resolver call).
    from clue_research.api.synthesis_wiring import register_synthesis_wiring

    register_synthesis_wiring(accounts=_Accounts(_account()))
    resolver = get_resolver("exa_deep")
    assert resolver.tier == 4


# --- end-to-end through the real waterfall (DB-gated) --------------------------------------------


async def _claims(conn: object, entity_id: EntityId, field_key: str) -> list[Claim]:
    return list(await claims_for(conn, entity_id, field_key, scope=ALL_TENANTS))  # type: ignore[arg-type]


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
                conn, entity, field, mode=_MODE, run_id=new_run_id(), tenant_id="client-1"
            )
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            (claim,) = await _claims(conn, entity.entity_id, "account.resonance.culture")
            assert claim.reuse_scope is ReuseScope.TENANT_PRIVATE
            assert claim.tenant_id == "client-1"

    run_async(_run())
