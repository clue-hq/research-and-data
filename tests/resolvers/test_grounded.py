"""M11.1 — the shared tier-4 grounded-synthesis substrate (``resolvers/grounded.py``).

Pure, hermetic unit tests of the provider-agnostic :class:`GroundedSynthesisResolver` — the
disciplines every tier-4 provider (Exa Deep, Parallel Task) inherits *once*: grounded-only,
target-lock, no-self-promotion, empty-on-miss, the account-only personal-data firewall, dedup, and
realized-cost attribution. A :class:`SynthesisBackend` double stands in for the provider call (no
network, no key), so these run in ``make check`` without a DB. The end-to-end waterfall path
(engine-stamped provenance, swap seam, budget) is in ``test_exa_deep.py``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_research.core import (
    AccountEntity,
    Entity,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldDef,
    PassKind,
    Resolver,
    VerificationStatus,
    new_entity_id,
)
from clue_research.obs.testing import collect_spans
from clue_research.resolvers import (
    GroundedSynthesisResolver,
    ResolverError,
    SynthesisResult,
    SynthesizedField,
)

_FIELD_KEY = "account.operational_pain"


class _StubBackend:
    """A :class:`~clue_research.resolvers.SynthesisBackend` double: returns a preset result and
    counts ``synthesize`` calls (entity-agnostic — the resolver injects the account)."""

    def __init__(self, result: SynthesisResult) -> None:
        self._result = result
        self.calls = 0

    def synthesize(self, account: AccountEntity, field: FieldDef) -> SynthesisResult:
        self.calls += 1
        return self._result


class _Accounts:
    """An :class:`~clue_research.resolvers.AccountLookup` double."""

    def __init__(self, account: AccountEntity | None) -> None:
        self._account = account

    def key_for(self, entity_id: EntityId) -> AccountEntity | None:
        return self._account


def _account(domain: str | None = "acme.com") -> AccountEntity:
    return AccountEntity(
        id=new_entity_id(), canonical_name="Acme Corp", primary_domain=domain, aliases=("Acme",)
    )


def _field(key: str = _FIELD_KEY) -> FieldDef:
    return FieldDef(
        field_key=key,
        value_type="str",
        tier_plan=("exa_deep", "parallel_task"),
        pass_kind=PassKind.DEEP,
    )


def _synth(
    value: str,
    *,
    url: str,
    retrieved: str | None = None,
    span: str | None = None,
    conf: float = 0.9,
    key: str = _FIELD_KEY,
) -> SynthesizedField:
    span = value if span is None else span
    return SynthesizedField(
        field_key=key,
        value=value,
        source_url=url,
        evidence_span=span,
        retrieved_text=retrieved if retrieved is not None else span,
        confidence=conf,
    )


def _resolver(
    fields: tuple[SynthesizedField, ...] = (),
    *,
    cost: Decimal = Decimal(0),
    account: AccountEntity | None = None,
    accounts_none: bool = False,
    default_cost: Decimal = Decimal(0),
) -> GroundedSynthesisResolver:
    acct = account if account is not None else _account()
    lookup = None if accounts_none else _Accounts(acct)
    return GroundedSynthesisResolver(
        _StubBackend(SynthesisResult(fields=fields, cost_cents=cost)),
        lookup,
        source_key="exa_deep",
        default_cost_cents=default_cost,
    )


# --- protocol conformance + claim shape ----------------------------------------------------------


def test_conforms_to_resolver_protocol_at_tier_4() -> None:
    resolver = _resolver()
    assert isinstance(resolver, Resolver)
    assert resolver.tier == 4


def test_builds_tier4_synthesis_claim_with_span_url_confidence_cost() -> None:
    account = _account()
    field = _synth("Acme runs brittle legacy ETL", url="https://acme.com/eng", conf=0.88)
    resolver = _resolver((field,), cost=Decimal(12), account=account)
    (claim,) = resolver.resolve(account.as_entity(), _field())
    assert claim.entity_id == account.id
    assert claim.entity_type is EntityType.ACCOUNT
    assert claim.source_tier == 4
    assert claim.extraction_method is ExtractionMethod.LLM_SYNTHESIS
    assert claim.evidence_span == "Acme runs brittle legacy ETL"
    assert claim.source_url == "https://acme.com/eng"
    assert 0.0 <= claim.confidence <= 1.0 and claim.confidence == pytest.approx(0.88)
    assert claim.cost_cents == Decimal(12)
    assert claim.value_json == "Acme runs brittle legacy ETL"


def test_no_self_promotion_claims_are_unverified() -> None:
    account = _account()
    resolver = _resolver(
        (_synth("Acme is expanding to EMEA", url="https://acme.com"),), account=account
    )
    (claim,) = resolver.resolve(account.as_entity(), _field())
    assert claim.verification_status is VerificationStatus.UNVERIFIED


# --- grounded-only + empty-on-miss ---------------------------------------------------------------


def test_empty_backend_yields_no_claim() -> None:
    account = _account()
    resolver = _resolver((), account=account)
    assert resolver.resolve(account.as_entity(), _field()) == []


def test_grounded_only_drops_span_absent_from_retrieved_text() -> None:
    # On-domain (target-lock would pass), but the span is not a passage of the retrieved source →
    # the value is not grounded → dropped. Empty is correct (never a fabricated value).
    account = _account()
    field = _synth(
        "value", url="https://acme.com", span="invented claim", retrieved="unrelated page text"
    )
    resolver = _resolver((field,), account=account)
    assert resolver.resolve(account.as_entity(), _field()) == []


def test_grounded_survivor_span_is_a_substring_of_a_retrieved_source() -> None:
    account = _account()
    field = _synth(
        "Acme cut its data team",
        url="https://acme.com/news",
        span="cut its data team",
        retrieved="In 2026 Acme cut its data team by a third, sources say.",
    )
    (claim,) = _resolver((field,), account=account).resolve(account.as_entity(), _field())
    assert claim.evidence_span == "cut its data team"


# --- target-lock (anti-drift / same-name competitor) ---------------------------------------------


def test_target_lock_rejects_off_entity_evidence() -> None:
    # An off-domain citation whose text names neither the canonical name nor an alias is a same-name
    # competitor's evidence — rejected, not blended (staged-flow §5).
    account = _account()
    off = _synth(
        "struggles with legacy pipelines",
        url="https://competitor.com/blog",
        retrieved="A different firm struggles with legacy pipelines.",
    )
    assert _resolver((off,), account=account).resolve(account.as_entity(), _field()) == []


def test_target_lock_keeps_on_domain_evidence() -> None:
    account = _account()
    on = _synth("Acme ships weekly", url="https://www.acme.com/eng", retrieved="Acme ships weekly")
    (claim,) = _resolver((on,), account=account).resolve(account.as_entity(), _field())
    assert claim.source_url == "https://www.acme.com/eng"


def test_target_lock_keeps_off_domain_when_name_matches() -> None:
    # Resonance lives on third-party sites (Glassdoor/news), so an off-domain citation that *names*
    # the entity is on-target — kept.
    account = _account()
    field = _synth(
        "morale is low",
        url="https://glassdoor.com/acme",
        retrieved="Reviewers say morale is low at Acme Corp this year.",
    )
    (claim,) = _resolver((field,), account=account).resolve(account.as_entity(), _field())
    assert claim.source_url == "https://glassdoor.com/acme"


def test_target_lock_mixes_keep_on_entity_drop_off_entity() -> None:
    account = _account()
    on = _synth("Acme migrated to Snowflake", url="https://acme.com/eng")
    off = _synth(
        "unrelated competitor fact",
        url="https://other.com",
        retrieved="A rival company did something unrelated.",
    )
    claims = _resolver((on, off), account=account).resolve(account.as_entity(), _field())
    assert [c.value_json for c in claims] == ["Acme migrated to Snowflake"]


def test_target_lock_rejects_name_embedded_in_a_larger_word() -> None:
    # AC4: a near-duplicate same-name competitor whose name EMBEDS the alias ("Acme" inside
    # "AcmeRival") on a different domain. A raw substring test would keep it; whole-word target-lock
    # drops it (off-entity is rejected, not blended).
    account = _account()  # canonical "Acme Corp", alias "Acme"
    off = _synth(
        "AcmeRival struggles with legacy pipelines",
        url="https://acmerival.com/blog",
        retrieved="AcmeRival Inc struggles with legacy pipelines across its teams.",
    )
    assert _resolver((off,), account=account).resolve(account.as_entity(), _field()) == []


def test_target_lock_short_alias_does_not_match_inside_a_word() -> None:
    # A short alias ("HP") must not match inside an unrelated word ("championship") — the
    # word-boundary fix; with no resolvable domain, the off-domain page is dropped (fail-closed).
    account = AccountEntity(
        id=new_entity_id(), canonical_name="HP Inc", primary_domain=None, aliases=("HP",)
    )
    field = _synth(
        "won the championship",
        url="https://sports.example.com",
        retrieved="The team won the championship last season.",
    )
    resolver = GroundedSynthesisResolver(
        _StubBackend(SynthesisResult(fields=(field,))), _Accounts(account), source_key="exa_deep"
    )
    assert resolver.resolve(account.as_entity(), _field()) == []


# --- tracing (AC9): the synthesis span with retrieval count + outcome ----------------------------


def _span_attrs(account: AccountEntity, fields: tuple[SynthesizedField, ...]):
    resolver = _resolver(fields, cost=Decimal(9), account=account)
    with collect_spans() as exporter:
        resolver.resolve(account.as_entity(), _field())
    span = next(s for s in exporter.get_finished_spans() if s.name == "synthesis.exa_deep")
    return dict(span.attributes or {})


def test_synthesis_span_records_dims_and_hit_outcome() -> None:
    account = _account()
    attrs = _span_attrs(
        account, (_synth("Acme ships weekly", url="https://acme.com/eng", conf=0.83),)
    )
    assert attrs["field_key"] == _FIELD_KEY
    assert attrs["entity_id"] == str(account.id)
    assert str(attrs["n_retrieved"]) == "1" and str(attrs["n_kept"]) == "1"
    assert attrs["n_claims"] == 1
    assert attrs["outcome"] == "hit"
    assert float(attrs["confidence"]) == pytest.approx(0.83)  # the kept grounding's confidence


def test_synthesis_span_outcome_miss_when_all_dropped() -> None:
    account = _account()
    off = _synth("rival fact", url="https://other.com", retrieved="A different firm did something.")
    attrs = _span_attrs(account, (off,))
    assert str(attrs["n_retrieved"]) == "1" and str(attrs["n_kept"]) == "0"
    assert attrs["outcome"] == "miss"
    assert "confidence" not in attrs  # nothing kept → no confidence reported


def test_synthesis_span_outcome_empty_when_no_retrieval() -> None:
    account = _account()
    attrs = _span_attrs(account, ())
    assert str(attrs["n_retrieved"]) == "0"
    assert attrs["outcome"] == "empty"


# --- the account-only personal-data firewall -----------------------------------------------------


def test_contact_entity_writes_nothing() -> None:
    account = _account()
    resolver = _resolver((_synth("x", url="https://acme.com"),), account=account)
    contact = Entity(entity_id=new_entity_id(), entity_type=EntityType.CONTACT)
    assert resolver.resolve(contact, _field()) == []


def test_contact_class_field_writes_nothing() -> None:
    account = _account()
    resolver = _resolver((_synth("x", url="https://acme.com"),), account=account)
    facet = _field("contact.facet.recent_post")
    assert resolver.resolve(account.as_entity(), facet) == []


# --- wiring + lookup faults ----------------------------------------------------------------------


def test_unknown_account_is_hard_miss() -> None:
    resolver = GroundedSynthesisResolver(
        _StubBackend(SynthesisResult(fields=(_synth("x", url="https://acme.com"),))),
        _Accounts(None),  # entity_id resolves to no account
        source_key="exa_deep",
    )
    account = _account()
    assert resolver.resolve(account.as_entity(), _field()) == []


def test_missing_account_lookup_is_a_wiring_error() -> None:
    resolver = _resolver((_synth("x", url="https://acme.com"),), accounts_none=True)
    with pytest.raises(ResolverError):
        resolver.resolve(_account().as_entity(), _field())


# --- distinct-value dedup + cost attribution -----------------------------------------------------


def test_distinct_values_become_distinct_claims_same_value_dedups() -> None:
    account = _account()
    fields = (
        _synth("Acme is hiring in EMEA", url="https://acme.com/a"),
        _synth("Acme is hiring in EMEA", url="https://acme.com/b"),  # same value → dedup
        _synth("Acme acquired DataCo", url="https://acme.com/c"),
    )
    claims = _resolver(fields, cost=Decimal(20), account=account).resolve(
        account.as_entity(), _field()
    )
    assert sorted(c.value_json for c in claims) == [
        "Acme acquired DataCo",
        "Acme is hiring in EMEA",
    ]


def test_realized_cost_is_attributed_to_the_first_claim_only() -> None:
    account = _account()
    fields = (
        _synth("Acme fact one", url="https://acme.com/a"),
        _synth("Acme fact two", url="https://acme.com/b"),
    )
    claims = _resolver(fields, cost=Decimal(15), account=account).resolve(
        account.as_entity(), _field()
    )
    assert sum(c.cost_cents for c in claims) == Decimal(15)
    assert sorted(c.cost_cents for c in claims) == [Decimal(0), Decimal(15)]


def test_default_cost_used_when_backend_reports_none() -> None:
    account = _account()
    resolver = _resolver(
        (_synth("Acme fact", url="https://acme.com"),),
        cost=Decimal(0),  # backend reports no realized cost
        account=account,
        default_cost=Decimal(10),
    )
    (claim,) = resolver.resolve(account.as_entity(), _field())
    assert claim.cost_cents == Decimal(10)


# --- reasoning → trace ONLY, structurally barred from an evidence span (M11.2, provider-neutral) --


def _resolver_with(result: SynthesisResult, account: AccountEntity) -> GroundedSynthesisResolver:
    return GroundedSynthesisResolver(
        _StubBackend(result), _Accounts(account), source_key="exa_deep"
    )


def test_reasoning_is_surfaced_on_the_span_but_never_becomes_a_claim() -> None:
    # A backend's synthesis rationale is recorded on the trace for audit — and can NEVER become a
    # claim's value/evidence_span (claims are built only from SynthesizedFields). The firewall is
    # structural: _build_claims never reads result.reasoning.
    account = _account()
    rationale = "a free-hand rationale that must not ground a value"
    result = SynthesisResult(
        fields=(_synth("Acme ships weekly", url="https://acme.com/eng"),), reasoning=(rationale,)
    )
    with collect_spans() as exporter:
        claims = _resolver_with(result, account).resolve(account.as_entity(), _field())
    span = next(s for s in exporter.get_finished_spans() if s.name == "synthesis.exa_deep")
    assert dict(span.attributes or {})["reasoning"] == rationale
    assert all(c.evidence_span != rationale and c.value_json != rationale for c in claims)


def test_reasoning_recorded_on_span_even_when_there_are_no_claims() -> None:
    account = _account()
    rationale = "rationale with no grounded field behind it"
    result = SynthesisResult(fields=(), reasoning=(rationale,))
    with collect_spans() as exporter:
        claims = _resolver_with(result, account).resolve(account.as_entity(), _field())
    assert claims == []
    attrs = dict(
        next(s for s in exporter.get_finished_spans() if s.name == "synthesis.exa_deep").attributes
        or {}
    )
    assert attrs["outcome"] == "empty"
    assert attrs["reasoning"] == rationale


def test_no_reasoning_attr_when_backend_returns_none() -> None:
    account = _account()
    result = SynthesisResult(fields=(_synth("Acme ships weekly", url="https://acme.com/eng"),))
    with collect_spans() as exporter:
        _resolver_with(result, account).resolve(account.as_entity(), _field())
    span = next(s for s in exporter.get_finished_spans() if s.name == "synthesis.exa_deep")
    assert "reasoning" not in dict(span.attributes or {})
