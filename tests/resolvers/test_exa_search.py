"""Slice 3 task 7: the tier-3 ``exa_search`` source + resolver (open-web competitor/buyer research).

Stage-0 recon can only read the client's *owned* surfaces. Two baseline fields —
``client.competitor`` and ``client.buyer_profile`` — are answerable only from third-party pages, so
their ``tier_plan`` names one tier-3 source: ``exa_search``. This module is that source's acceptance
suite.

Everything here is **pure**: the HTTP transport is an injected fake (no live Exa call, no
credential from the environment), and the claim extractor is either the real
:class:`~clue_api.claim_extraction.LlmClaimExtractor` over a canned gateway (so the
``### RESULT n | url: …`` header format is proven to actually ground ``source_url``) or a small
callable double where a specific guard is under test.

The guards are the point. A search resolver hands an LLM a *multi-record* document, so two failure
modes exist that a single-page scrape does not have: a claim that cannot be attributed to any
returned record, and a claim attributed to a record that is about a *different* company (the
same-name / competitor-page drift trap). Both are fail-closed drops here — an empty field is a
correct output, a misattributed one is a defect.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from clue_api.claim_extraction import (
    DEFAULT_MAX_TEXT_CHARS,
    ExtractionPolicy,
    LlmClaimExtractor,
)
from clue_config import Secrets
from clue_core import (
    AccountEntity,
    ClaimDraft,
    Completion,
    EmbeddingResult,
    Entity,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldDef,
    IdentityBinding,
    Message,
    Modality,
    NormalizedText,
    PassKind,
    Resolver,
    RetryableResolverError,
    new_entity_id,
)
from clue_obs import capture_events
from clue_obs.otel import ATTR_N_CLAIMS
from clue_obs.otel.testing import collect_spans
from clue_research.adapters import CallableClaimExtractor
from clue_research.resolvers.exa_search import (
    EXA_SEARCH_SOURCE_KEY,
    ExaSearchConfig,
    ExaSearchResolver,
    register_exa_search_resolver,
)
from clue_research.resolvers.http import CredentialError, ProviderResponseError
from clue_research.sources import SEED_MANIFESTS, get_resolver, is_resolver_bound

_COMPETITOR = "client.competitor"
_BUYER = "client.buyer_profile"
_RIVAL_QUOTE = "Acme Corp and Rival Inc are the two leading CI platforms for mid-market teams."
_OFF_ENTITY_QUOTE = "Globex Systems competes with Initech across the logistics market."


# --- doubles ---------------------------------------------------------------


class _Accounts:
    """The :class:`~clue_research.resolvers.live.AccountLookup` the composition root supplies."""

    def __init__(self, account: AccountEntity | None) -> None:
        self._account = account

    def key_for(self, entity_id: EntityId) -> AccountEntity | None:
        return self._account


class _Gateway:
    """An :class:`~clue_core.gateway.LLMGateway` returning one canned completion body."""

    def __init__(self, body: str) -> None:
        self._body = body
        self.calls = 0

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.calls += 1
        return Completion(model=model, text=self._body)

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        return EmbeddingResult(model=model)


class _Http:
    """A ``get_json`` double: returns a canned payload (or raises) and records every request."""

    def __init__(self, payload: Any = None, *, exc: Exception | None = None) -> None:
        self._payload = payload if payload is not None else {"results": []}
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        if self._exc is not None:
            raise self._exc
        return self._payload


def _secrets() -> Secrets:
    # ``_env_file=None`` keeps a developer's real key out of the test entirely.
    return Secrets(_env_file=None, exa_api_key="unit-test")


def _account(*, name: str = "Acme Corp", domain: str | None = "acme.example") -> AccountEntity:
    return AccountEntity(
        id=new_entity_id(),
        canonical_name=name,
        primary_domain=domain,
        workspace_id="ws-test",
    )


def _field(field_key: str = _COMPETITOR) -> FieldDef:
    return FieldDef(
        field_key=field_key,
        value_type="object",
        tier_plan=(EXA_SEARCH_SOURCE_KEY,),
        pass_kind=PassKind.SCORING,
    )


def _payload(*records: tuple[str, str]) -> dict[str, Any]:
    return {
        "results": [{"title": "Comparison", "url": url, "text": text} for url, text in records],
        "costDollars": {"total": 0.01},
    }


def _llm_extractor(body: str) -> tuple[LlmClaimExtractor, _Gateway]:
    gateway = _Gateway(body)
    # An explicit model id skips ``ExtractionPolicy``'s deploy-settings default_factory: these
    # tests never call a model, and reading deploy config for an id nobody uses is noise.
    extractor = LlmClaimExtractor(
        gateway=gateway, policy=ExtractionPolicy(extraction_model="unit-test-model")
    )
    return extractor, gateway


def _resolver(
    *,
    extractor: Any,
    account: AccountEntity | None = None,
    http: _Http,
    config: ExaSearchConfig | None = None,
) -> ExaSearchResolver:
    return ExaSearchResolver(
        extractor=extractor,
        accounts=_Accounts(account if account is not None else _account()),
        config=config,
        secrets=_secrets(),
        http=http,
    )


# --- AC: a grounded, on-entity record becomes a tier-3 API claim citing that record ---------------


def test_grounded_competitor_record_becomes_a_tier3_api_claim_with_source_url() -> None:
    """The end-to-end happy path, through the REAL extractor: the resolver's
    ``### RESULT n | url: …`` header is what lets the extractor ground ``source_url`` by exact
    substring, and the claim that comes out is tier-3 / ``api`` / cited / span-grounded."""
    url = "https://reviews.example/acme-vs-rival"
    http = _Http(_payload((url, _RIVAL_QUOTE)))
    extractor, gateway = _llm_extractor(
        json.dumps(
            {
                "claims": [
                    {
                        "value": {"name": "Rival Inc", "domain": "rival.example"},
                        "quote": _RIVAL_QUOTE,
                        "source_url": url,
                        "confidence": 0.8,
                    }
                ]
            }
        )
    )
    account = _account()
    resolver = _resolver(extractor=extractor, account=account, http=http)

    claims = resolver.resolve(account.as_entity(), _field())

    assert gateway.calls == 1
    (claim,) = claims
    assert claim.source_tier == 3
    assert claim.extraction_method is ExtractionMethod.API
    assert claim.entity_id == account.id
    assert claim.field_key == _COMPETITOR
    assert claim.value_json == {"name": "Rival Inc", "domain": "rival.example"}
    assert claim.source_url == url  # the RECORD's url, not a fallback
    assert claim.evidence_span == _RIVAL_QUOTE
    assert claim.cost_cents == Decimal(1)  # the seeded manifest price, on the first claim only

    # the request the resolver issued: the entity-bound query, the tier-3 search type, text on.
    (request,) = http.calls
    assert request["method"] == "POST"
    assert request["json_body"]["type"] == "auto"
    assert request["json_body"]["contents"] == {"text": True}
    assert "Acme Corp" in request["json_body"]["query"]


def test_only_the_first_claim_of_a_call_carries_the_call_cost() -> None:
    """Two competitors from one paid search is ONE call: the waterfall sums per-claim cost, so
    charging each claim would bill the call twice."""
    url = "https://reviews.example/acme-alternatives"
    text = f"{_RIVAL_QUOTE} Initech is another Acme Corp alternative."
    http = _Http(_payload((url, text)))
    extractor, _ = _llm_extractor(
        json.dumps(
            {
                "claims": [
                    {
                        "value": {"name": "Rival Inc"},
                        "quote": _RIVAL_QUOTE,
                        "source_url": url,
                        "confidence": 0.8,
                    },
                    {
                        "value": {"name": "Initech"},
                        "quote": "Initech is another Acme Corp alternative.",
                        "source_url": url,
                        "confidence": 0.7,
                    },
                ]
            }
        )
    )
    account = _account()
    claims = _resolver(extractor=extractor, account=account, http=http).resolve(
        account.as_entity(), _field()
    )
    assert [c.cost_cents for c in claims] == [Decimal(1), Decimal(0)]


# --- AC: target-lock — a record that never names the client is dropped, fail-closed ---------------


def test_record_not_naming_the_client_is_dropped_fail_closed() -> None:
    """The same-name / wrong-company trap. The extractor is *told* to quote the document, and it
    did — but the document is about Globex, not Acme. Off-entity evidence is rejected, not blended,
    so the field ends empty rather than carrying a competitor of somebody else."""
    url = "https://news.example/logistics-roundup"
    http = _Http(_payload((url, _OFF_ENTITY_QUOTE)))
    extractor, _ = _llm_extractor(
        json.dumps(
            {
                "claims": [
                    {
                        "value": {"name": "Initech"},
                        "quote": _OFF_ENTITY_QUOTE,
                        "source_url": url,
                        "confidence": 0.9,
                    }
                ]
            }
        )
    )
    account = _account()
    assert (
        _resolver(extractor=extractor, account=account, http=http).resolve(
            account.as_entity(), _field()
        )
        == []
    )


def test_a_substring_name_hit_does_not_count_as_naming_the_client() -> None:
    """Whole-word matching, not substring: ``Acme`` inside ``Acmerival`` is a different company."""
    url = "https://news.example/acmerival"
    text = "Acmerival Ltd competes with Initech in the CI market."
    http = _Http(_payload((url, text)))
    extractor = CallableClaimExtractor(
        lambda normalized, entity, field: [
            ClaimDraft(
                field_key=field.field_key,
                value={"name": "Initech"},
                evidence_span=text,
                confidence=0.9,
                source_url=url,
            )
        ]
    )
    account = _account(name="Acme")
    assert (
        _resolver(extractor=extractor, account=account, http=http).resolve(
            account.as_entity(), _field()
        )
        == []
    )


def test_an_account_with_no_usable_identifier_can_never_target_lock() -> None:
    """No domain and no name token long enough to disambiguate: target-lock is unsatisfiable, so
    every record is refused rather than guessed onto the entity."""
    url = "https://news.example/roundup"
    text = "A competes with Initech."
    http = _Http(_payload((url, text)))
    extractor = CallableClaimExtractor(
        lambda normalized, entity, field: [
            ClaimDraft(
                field_key=field.field_key,
                value={"name": "Initech"},
                evidence_span=text,
                confidence=0.9,
                source_url=url,
            )
        ]
    )
    account = _account(name="A", domain=None)
    assert (
        _resolver(extractor=extractor, account=account, http=http).resolve(
            account.as_entity(), _field()
        )
        == []
    )


def test_the_records_own_text_is_what_must_name_the_client() -> None:
    """Intra-document misattribution: record 1 is about Acme, record 3 is not. A draft quoting
    record 3 but citing record 1's url must NOT inherit record 1's on-entity verdict — the guard
    checks the text of the record the claim actually cites."""
    on_entity = "https://reviews.example/acme-vs-rival"
    off_entity = "https://news.example/logistics-roundup"
    http = _Http(_payload((on_entity, _RIVAL_QUOTE), (off_entity, _OFF_ENTITY_QUOTE)))
    extractor = CallableClaimExtractor(
        lambda normalized, entity, field: [
            ClaimDraft(
                field_key=field.field_key,
                value={"name": "Initech"},
                evidence_span=_OFF_ENTITY_QUOTE,
                confidence=0.9,
                source_url=off_entity,
            )
        ]
    )
    account = _account()
    assert (
        _resolver(extractor=extractor, account=account, http=http).resolve(
            account.as_entity(), _field()
        )
        == []
    )


# --- AC: a claim that cannot be attributed to a returned record is dropped -----------------------


def test_source_url_not_in_returned_records_is_dropped() -> None:
    """A ``source_url`` naming a page this call never retrieved cannot be evidence-checked, and an
    UNATTRIBUTED claim (``source_url=None``) cannot be target-locked to a record at all. Both are
    dropped — a multi-record source has no honest fallback citation."""
    url = "https://reviews.example/acme-vs-rival"
    http = _Http(_payload((url, _RIVAL_QUOTE)))

    def _drafts(normalized: NormalizedText, entity: Entity, field: FieldDef) -> list[ClaimDraft]:
        return [
            ClaimDraft(
                field_key=field.field_key,
                value={"name": "Rival Inc"},
                evidence_span=_RIVAL_QUOTE,
                confidence=0.9,
                source_url="https://elsewhere.example/never-fetched",
            ),
            ClaimDraft(
                field_key=field.field_key,
                value={"name": "Rival Inc"},
                evidence_span=_RIVAL_QUOTE,
                confidence=0.9,
                source_url=None,
            ),
        ]

    account = _account()
    assert (
        _resolver(extractor=CallableClaimExtractor(_drafts), account=account, http=http).resolve(
            account.as_entity(), _field()
        )
        == []
    )


def test_an_ungrounded_span_is_dropped() -> None:
    """The span rule, re-checked at the resolver: a value whose quote is not in the retrieved text
    is not evidence, whatever the extractor thought."""
    url = "https://reviews.example/acme-vs-rival"
    http = _Http(_payload((url, _RIVAL_QUOTE)))
    extractor = CallableClaimExtractor(
        lambda normalized, entity, field: [
            ClaimDraft(
                field_key=field.field_key,
                value={"name": "Rival Inc"},
                evidence_span="Acme Corp said Rival Inc is losing",  # never in the document
                confidence=0.9,
                source_url=url,
            )
        ]
    )
    account = _account()
    assert (
        _resolver(extractor=extractor, account=account, http=http).resolve(
            account.as_entity(), _field()
        )
        == []
    )


# --- AC: nothing to research → no call, no claim -------------------------------------------------


def test_no_template_or_wrong_entity_type_yields_empty() -> None:
    """The resolver answers exactly the fields it has a query for, for account entities it can
    look up. Every other case is an empty list *and no provider call* — never a fabricated value
    and never a paid request for a question this source cannot ask."""
    http = _Http(_payload(("https://reviews.example/x", _RIVAL_QUOTE)))
    account = _account()
    extractor = CallableClaimExtractor(lambda normalized, entity, field: [])
    resolver = _resolver(extractor=extractor, account=account, http=http)

    # a field with no query template (an owned-surface field the scrape lane fills)
    assert resolver.resolve(account.as_entity(), _field("client.value_prop")) == []
    # a contact entity — this is the account/client-research path only
    contact = Entity(entity_id=new_entity_id(), entity_type=EntityType.CONTACT)
    assert resolver.resolve(contact, _field()) == []
    # an id the orchestrator never loaded → a hard miss
    unknown = ExaSearchResolver(
        extractor=extractor, accounts=_Accounts(None), secrets=_secrets(), http=http
    )
    assert unknown.resolve(account.as_entity(), _field()) == []

    assert http.calls == []


def test_a_response_with_no_usable_records_is_a_hard_miss_not_a_raise() -> None:
    """A provider miss is an empty claim list (the field ends empty+flagged), never an error and
    never a value. Records with no text cannot be quoted, so they are not records."""
    account = _account()
    extractor = CallableClaimExtractor(lambda normalized, entity, field: [])
    for payload in ({"results": []}, {"results": [{"url": "https://x.example"}]}, "not-a-mapping"):
        resolver = _resolver(extractor=extractor, account=account, http=_Http(payload))
        assert resolver.resolve(account.as_entity(), _field()) == []


# --- AC: the tier ceiling is a construction-time guard, not a convention -------------------------


def test_search_type_never_deep() -> None:
    """``deep``/``deep-reasoning`` is Exa's tier-4 *research* product (grounded LLM synthesis,
    governed by M11 and the faithfulness judge). Configuring this tier-3 source to call it would
    smuggle tier-4 synthesis in under a tier-3 manifest, so the config refuses to construct."""
    for search_type in ("deep", "deep-reasoning", "DEEP"):
        with pytest.raises(ValueError):
            ExaSearchConfig(search_type=search_type)
    assert ExaSearchConfig().search_type == "auto"
    assert ExaSearchConfig(search_type="keyword").search_type == "keyword"


# --- AC: a transient fault is retryable, never a fabricated/empty answer --------------------------


def test_transport_failure_is_retryable_not_fabricated() -> None:
    """A timeout/5xx propagates as ``RetryableResolverError`` (M7 retries) instead of being
    swallowed into a hard miss — and the extractor is never asked to invent an answer for it."""
    http = _Http(exc=RetryableResolverError("simulated transient provider failure"))
    calls: list[str] = []

    def _never(normalized: NormalizedText, entity: Entity, field: FieldDef) -> list[ClaimDraft]:
        calls.append(field.field_key)
        return []

    account = _account()
    resolver = _resolver(extractor=CallableClaimExtractor(_never), account=account, http=http)
    with pytest.raises(RetryableResolverError):
        resolver.resolve(account.as_entity(), _field())
    assert calls == []


# --- AC: the seeded manifest ---------------------------------------------------------------------


def _seed_entry() -> Any:
    return next(m for m in SEED_MANIFESTS if m.source_key == EXA_SEARCH_SOURCE_KEY)


def test_manifest_is_tier3_weak_binding_and_seeded() -> None:
    entry = _seed_entry()
    # The tier is load-bearing, not decorative: the Stage-0 fast lane caps at max_source_tier=2, so
    # tier 3 is exactly what makes it walk past this source at zero spend and lets only the
    # background lane pay for it. Pin it.
    assert entry.tier == 3
    assert entry.provider == "exa"
    assert entry.auth_ref == "CLUE_EXA_API_KEY"
    assert entry.cost_cents == Decimal(1)
    assert entry.manifest.modality is Modality.TEXT
    assert entry.manifest.identity_binding_strength is IdentityBinding.WEAK
    assert entry.manifest.freshness_profile == "snapshot"
    # Honest yields: the two client fields this source can actually answer, and nothing else.
    assert set(entry.yields) == {_COMPETITOR, _BUYER}


def test_registration_binds_a_tier3_resolver() -> None:
    extractor = CallableClaimExtractor(lambda normalized, entity, field: [])
    register_exa_search_resolver(extractor=extractor, accounts=_Accounts(_account()))
    assert is_resolver_bound(EXA_SEARCH_SOURCE_KEY)
    bound = get_resolver(EXA_SEARCH_SOURCE_KEY)
    assert isinstance(bound, Resolver)
    assert bound.tier == 3 == _seed_entry().tier


def test_the_default_templates_cover_exactly_the_two_tier3_client_fields() -> None:
    assert set(ExaSearchConfig().query_templates) == {_COMPETITOR, _BUYER}


def test_a_span_from_one_record_cited_to_another_is_dropped() -> None:
    """The reverse misattribution, and the one the whole-document span check cannot catch: both
    records are on-entity, so target-lock passes either way — but the quote came from record 2 and
    the citation names record 1, so an operator clicking the evidence link would not find the
    quote. Quote and citation must name the same place."""
    first = "https://reviews.example/acme-vs-rival"
    second = "https://blog.example/acme-vs-initech"
    other = "Acme Corp is regularly benchmarked against Initech on build speed."
    http = _Http(_payload((first, _RIVAL_QUOTE), (second, other)))
    extractor = CallableClaimExtractor(
        lambda normalized, entity, field: [
            ClaimDraft(
                field_key=field.field_key,
                value={"name": "Initech"},
                evidence_span=other,  # record 2's text …
                confidence=0.9,
                source_url=first,  # … under record 1's url
            )
        ]
    )
    account = _account()
    assert (
        _resolver(extractor=extractor, account=account, http=http).resolve(
            account.as_entity(), _field()
        )
        == []
    )


# --- AC (review fix): a HARD provider refusal is a miss, not a dead recon lane -------------------


def test_a_hard_provider_refusal_is_an_empty_field_not_a_lane_failure() -> None:
    """The other half of "an optional enrichment must never kill recon".

    The composition root's credential gate only covers "no key was ever configured". The likelier
    production faults — key revoked (401/403), credits exhausted (402), malformed query (400) —
    arrive here as ``ProviderResponseError`` at call time, long after the gate passed. A resolver
    exception is re-raised by the waterfall and again by ``reverse_profile``, so letting one escape
    would kill the whole run. It is a hard miss instead, named on the span.
    """
    account = _account()
    extractor = CallableClaimExtractor(lambda normalized, entity, field: [])
    for exc in (
        ProviderResponseError("payment required", status_code=402, body_excerpt="out of credits"),
        ProviderResponseError("forbidden", status_code=403),
        CredentialError("the key vanished between binding and this call"),
    ):
        http = _Http(exc=exc)
        with capture_events(mode="info") as cap, collect_spans() as spans:
            claims = _resolver(extractor=extractor, account=account, http=http).resolve(
                account.as_entity(), _field()
            )
        assert claims == []
        assert http.calls  # the call WAS attempted — this is a refusal, not a skip
        assert cap.has("research.exa_search.provider_refused")
        (span,) = [s for s in spans.get_finished_spans() if s.name == "search.exa_search"]
        attrs = dict(span.attributes or {})
        assert attrs["outcome"] == "provider_refused"
        assert attrs["refusal"] == type(exc).__name__


def test_a_transient_fault_still_propagates_after_the_refusal_catch() -> None:
    """The catch must not swallow the retryable case: a timeout/5xx is M7's to retry, and turning
    it into an empty field would silently lose a fact the next attempt would have found."""
    account = _account()
    http = _Http(exc=RetryableResolverError("simulated transient provider failure"))
    with pytest.raises(RetryableResolverError):
        _resolver(
            extractor=CallableClaimExtractor(lambda normalized, entity, field: []),
            account=account,
            http=http,
        ).resolve(account.as_entity(), _field())


def test_every_dropped_draft_is_counted_so_the_span_arithmetic_reconciles() -> None:
    """``n_drafts == n_claims + every drop counter``. A guard that discards silently is only
    trustworthy if the discard is countable — including a draft for the wrong field, which is
    otherwise the one drop with no counter."""
    url = "https://reviews.example/acme-vs-rival"
    http = _Http(_payload((url, _RIVAL_QUOTE)))
    extractor = CallableClaimExtractor(
        lambda normalized, entity, field: [
            ClaimDraft(  # wrong field
                field_key=_BUYER,
                value={"persona": "Head of Eng"},
                evidence_span=_RIVAL_QUOTE,
                confidence=0.9,
                source_url=url,
            ),
            ClaimDraft(  # unattributed
                field_key=field.field_key,
                value={"name": "Rival Inc"},
                evidence_span=_RIVAL_QUOTE,
                confidence=0.9,
                source_url=None,
            ),
            ClaimDraft(  # kept
                field_key=field.field_key,
                value={"name": "Rival Inc"},
                evidence_span=_RIVAL_QUOTE,
                confidence=0.9,
                source_url=url,
            ),
        ]
    )
    account = _account()
    with collect_spans() as exporter:
        claims = _resolver(extractor=extractor, account=account, http=http).resolve(
            account.as_entity(), _field()
        )
    assert len(claims) == 1
    (span,) = [s for s in exporter.get_finished_spans() if s.name == "search.exa_search"]
    attrs = dict(span.attributes or {})
    assert attrs["outcome"] == "hit"
    assert int(attrs["n_dropped_wrong_field"]) == 1
    assert int(attrs["n_dropped_unattributed"]) == 1
    dropped = sum(int(v) for k, v in attrs.items() if str(k).startswith("n_dropped_"))
    assert int(attrs["n_drafts"]) == int(attrs[ATTR_N_CLAIMS]) + dropped


def test_the_document_cap_tracks_the_extractors_own_prompt_slice() -> None:
    """The 60k cap is hand-mirrored from the extractor. If the extractor's slice moves and this
    does not, the resolver would build a document whose tail the model never reads while the
    grounding check still accepts spans from it — pin them together."""
    assert ExaSearchConfig().max_text_chars == DEFAULT_MAX_TEXT_CHARS
