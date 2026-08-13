"""The tier-3 open-web search source — competitor / buyer-profile research for Stage 0 (slice 3).

Stage-0 recon reads the client's **owned** surfaces (tier-2 official-site scrape). Two baseline
Client-KB fields cannot be answered there without taking marketing copy at face value:
``client.competitor`` (who the market compares this client against) and ``client.buyer_profile``
(who actually buys). Both are third-party facts, so both name exactly one tier-3 source in their
``tier_plan``: ``exa_search``, this module.

**Why tier 3, and why that matters.** Tier 3 is "reputable third party" — below the official
surface, above LLM synthesis. It is also the lever that keeps the interactive onboarding lane free:
the Stage-0 fast lane runs with ``max_source_tier=2``, so the pre-spend gate refuses this source
before a request is issued (a ``GATE_SKIPPED`` step at zero spend) and only the background lane
(``max_source_tier=3``) ever pays for it. The seeded manifest's ``tier`` is therefore load-bearing
and pinned by a test, and :class:`ExaSearchConfig` **refuses** a ``deep``/``deep-reasoning`` search
type: that is Exa's tier-4 research product (governed grounded synthesis, M11 + the faithfulness
judge), and calling it under a tier-3 manifest would smuggle tier-4 synthesis past its governance.

**The shape of the work.** One search returns *many* records. The resolver concatenates them into a
single :class:`~clue_core.NormalizedText` where each record is prefixed
``### RESULT n | url: <url>`` — the exact vocabulary the production claim extractor's prompt is
written against, so the extractor can name which record a quote came from — and stamps the same
urls on the document's ``metadata["record_urls"]``, which is the *checkable* half: the extractor
attributes a claim's url by membership of that out-of-band allowlist, never by finding it in the
(third-party, forgeable) text.

**Three guards, all fail-closed**, because a multi-record document has failure modes a single page
does not:

* *attributable* — the draft's ``source_url`` must be one of the urls this very call retrieved. An
  unattributed claim (the extractor nulls a url it cannot attribute) has no record to check
  against, and a multi-record source has no honest fallback citation, so it is dropped. This is now
  **defense in depth**: the same allowlist rides ``metadata["record_urls"]`` (see :func:`_document`)
  and the extractor already refuses any url outside it, so a forged ``### RESULT`` header inside a
  record's own text cannot mint a citation in the first place. The resolver re-checks it anyway
  against the records it holds — the guard is what makes the next two checks possible at all;
* *grounded-only, in the record it cites* — the draft's ``evidence_span`` must be an exact substring
  of that record's own text. The extractor already checks the span against the whole document; that
  is not enough here, because a span lifted from record 1 under record 3's url would pass it and
  then be target-locked against the wrong page. Quote and citation must name the same place;
* *target-lock* — the cited record's **own** text must be about this client: its host is the
  client's domain, or the canonical name / an alias / the domain is a whole-word match in that
  record's text. Checking the *cited* record (not the whole document) is what stops intra-document
  misattribution — record 1 being about Acme must never launder record 3's claim about Globex. When
  the account has neither a resolvable domain nor a usable name token, target-lock is unsatisfiable
  and every record is refused rather than guessed onto the entity.

A drop is not an error. A hard miss, a guard rejecting every candidate, an unknown account, a
**hard provider refusal** (a 4xx — revoked key, exhausted credits, malformed query — or a
credential that disappeared after binding), and a **transient fault that outlived its retries** (a
5xx/transport error re-raised by :func:`~clue_research.resolvers.http.get_json` after its own
``retries + 1`` attempts) all return ``[]``: an empty, flagged field is a correct output; a
fabricated or misattributed one is the only real failure. That is not defensive tidiness — a
resolver exception is re-raised by the waterfall and by ``stage0.client_kb``, so letting one escape
would kill the **whole** reverse-profiling run over one optional open-web enrichment. **The same
argument covers a 503 exactly as it covers a 402:** this resolver only ever runs in the Stage-0
recon *background* lane, and nothing there retries a failed lane — ``reverse_profile`` re-raises,
the savepoint rolls back every background claim, the lane is marked failed, and the driver only
ever drives QUEUED/RUNNING lanes. So a :class:`~clue_core.RetryableResolverError` arriving here has
no retrier left to hand it to and degrades to the same honest-empty miss, logged and spanned under
its own name (``provider_transient_exhausted``) so observability still separates "the provider
refused" from "the provider was down". Every empty answer names its reason on the trace span
(``outcome`` / ``refusal`` / the drop counters), so nothing goes quiet.

The resolver stamps only what the *source* knows — value, span, citation, confidence, cost. The
waterfall stamps the engine-owned provenance (``source_key`` / ``run_id`` / ``research_mode``) and
the tenant ``reuse_scope``; it also asserts the claim's tier equals the manifest's, which is why
``source_tier`` is hard-coded to the manifest tier here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_core import (
    AccountEntity,
    Claim,
    ClaimDraft,
    CostCents,
    Entity,
    EntityType,
    ExtractionMethod,
    FieldDef,
    NormalizedText,
    ResearchMode,
    ResolverError,
    RetryableResolverError,
    account_claim,
    new_run_id,
)
from clue_obs import get_logger
from clue_obs.otel import (
    ATTR_ENTITY_ID,
    ATTR_FIELD_KEY,
    ATTR_N_CLAIMS,
    ATTR_SOURCE_KEY,
    apply_attributes,
    traced_step,
)
from clue_research.adapters import ClaimExtractor
from clue_research.resolvers.grounded import entity_name_tokens, names_present, registrable_host
from clue_research.resolvers.http import (
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT_S,
    CredentialError,
    ProviderResponseError,
    get_json,
    resolve_credential,
)
from clue_research.resolvers.live import AccountLookup, HttpFetcher
from clue_research.sources import SEED_MANIFESTS, bind_resolver

if TYPE_CHECKING:
    from clue_config import Secrets

log = get_logger(__name__)

#: The registered ``source_key`` (its manifest lives in ``sources.seeds.SEED_MANIFESTS``).
EXA_SEARCH_SOURCE_KEY = "exa_search"

#: The credential *reference* (an env-var name), never a secret — resolved at call time.
AUTH_REF = "CLUE_EXA_API_KEY"

# The trust tier this resolver produces. The waterfall's ``_finalize`` fails loud if a claim's tier
# differs from its manifest's, so this constant and the seeded manifest tier are one fact.
_TIER3 = 3

# Search types that are Exa's tier-4 *research* product rather than a tier-3 retrieval. Matched as
# a substring so a future "deep-<x>" spelling is refused too (fail-closed on the tier ceiling).
_TIER4_SEARCH_MARKER = "deep"

#: The field → query mapping, as data. Keyed by field-key *string*: ``resolvers`` may not import
#: ``stage0`` (the one-way worker seam), exactly as the extractor's own per-field table is keyed.
#: A field absent from this mapping is a field this source cannot ask about — the resolver returns
#: ``[]`` without issuing (or paying for) a request.
DEFAULT_QUERY_TEMPLATES: Mapping[str, str] = MappingProxyType(
    {
        "client.competitor": '"{name}" competitors alternatives comparison',
        "client.buyer_profile": 'who uses "{name}" buyers customer roles teams',
    }
)


class ExaSearchConfig(BaseModel):
    """The source's policy, as data — swapping the endpoint, the breadth, or a query is config.

    ``search_type`` is validated, not merely documented: see the module docstring on the tier
    ceiling. ``max_text_chars`` mirrors the extractor's own prompt slice so the document the
    resolver builds and the document the model reads do not silently diverge — a record beyond the
    slice could never be quoted anyway, so it is dropped whole (never mid-record, which would leave
    a ``### RESULT`` header advertising text that is not there).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoint: str = "https://api.exa.ai/search"
    search_type: str = "auto"
    num_results: int = Field(default=5, ge=1, le=25)
    #: Per-record text cap — one verbose page must not crowd every other record out of the document.
    max_record_chars: int = Field(default=4_000, ge=200)
    #: Whole-document cap (the extractor's ``max_text_chars`` default).
    max_text_chars: int = Field(default=60_000, ge=1_000)
    timeout_s: float = Field(default=DEFAULT_TIMEOUT_S, gt=0)
    retries: int = Field(default=DEFAULT_RETRIES, ge=0)
    #: ``Mapping``, not ``dict``: the model is frozen, and a mutable-typed field would let a
    #: caller rewrite the query plan of a "frozen" config in place. Read-only by type.
    query_templates: Mapping[str, str] = Field(
        default_factory=lambda: MappingProxyType(dict(DEFAULT_QUERY_TEMPLATES))
    )

    @model_validator(mode="after")
    def _search_type_stays_below_tier_four(self) -> ExaSearchConfig:
        if _TIER4_SEARCH_MARKER in self.search_type.casefold():
            raise ValueError(
                f"exa_search is a tier-3 source and must never request a "
                f"{self.search_type!r} search: deep/deep-reasoning is Exa's tier-4 research "
                "product, which is governed by the M11 grounded-synthesis path and the "
                "faithfulness judge, not by a tier-3 manifest"
            )
        return self


DEFAULT_EXA_SEARCH_CONFIG = ExaSearchConfig()


@dataclass(frozen=True)
class _Record:
    """One retrieved search result, reduced to what a grounded claim needs."""

    url: str
    title: str
    text: str


def _seed_cost() -> CostCents:
    """This source's per-call price, read from the **seed manifest** — the single source of truth
    the waterfall budgets against, so a realized cost can never drift from the registered one (the
    pattern :func:`~clue_research.resolvers.grounded.synthesis_default_cost` uses)."""
    for entry in SEED_MANIFESTS:
        if entry.source_key == EXA_SEARCH_SOURCE_KEY:
            return entry.cost_cents
    return Decimal(0)


def _render_query(template: str, account: AccountEntity, field_key: str) -> str:
    """The entity-bound query — target-lock at the *query* level (the first anti-drift measure)."""
    domain = registrable_host(account.primary_domain) or ""
    try:
        return template.format(name=account.canonical_name, domain=domain)
    except (KeyError, IndexError) as exc:
        raise ResolverError(
            f"{EXA_SEARCH_SOURCE_KEY!r} query template for {field_key!r} references an unknown "
            f"placeholder {exc}; the template may use {{name}} and {{domain}} only"
        ) from exc


def _records(payload: Any, config: ExaSearchConfig) -> list[_Record]:
    """The usable records of a search response — defensively, never assuming provider shape.

    A record with no url cannot be cited and a record with no text cannot be quoted, so neither is
    a record here. Duplicate urls are collapsed: the url is the key a draft is attributed by, so two
    records sharing one would make "which record does this claim cite?" ambiguous.
    """
    if not isinstance(payload, Mapping):
        return []
    raw = payload.get("results")
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        return []
    records: list[_Record] = []
    seen: set[str] = set()
    for item in raw[: config.num_results]:
        if not isinstance(item, Mapping):
            continue
        url, text, title = item.get("url"), item.get("text"), item.get("title")
        if not isinstance(url, str) or not url.strip():
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        key = url.strip()
        if key in seen:
            continue
        seen.add(key)
        records.append(
            _Record(
                url=key,
                title=title.strip() if isinstance(title, str) else "",
                text=text.strip()[: config.max_record_chars],
            )
        )
    return records


def _quotable(record: _Record) -> str:
    """The part of a record a claim may quote — its own title and text, never its ``### RESULT``
    header (a header quote is the url, not evidence). Also the haystack target-lock reads."""
    return f"{record.title}\n{record.text}"


def _document(
    records: Sequence[_Record], config: ExaSearchConfig
) -> tuple[NormalizedText, list[_Record]]:
    """Build the multi-record document plus the records it actually contains.

    Each block is headed ``### RESULT n | url: <url>`` — the vocabulary the extractor's prompt tells
    the *model* to answer in, so it can name which record a quote came from.

    The urls of the records the document actually contains also ride the **metadata**, under
    ``record_urls``: that is the extractor's attribution allowlist (``attribution_allowlist``), and
    it is what makes a citation checkable. It has to be out-of-band — record *text* is third-party
    bytes and can always contain a ``### RESULT``-lookalike line, so a url validated by reading the
    document could be forged by the document. Only ``used`` records are listed: a record dropped by
    the ``max_text_chars`` cap was never shown, so nothing may cite it.
    """
    blocks: list[str] = []
    used: list[_Record] = []
    total = 0
    for record in records:
        block = f"### RESULT {len(used) + 1} | url: {record.url}\n{_quotable(record)}"
        if used and total + len(block) + 2 > config.max_text_chars:
            break  # drop the whole record; never a header without its text
        blocks.append(block)
        used.append(record)
        total += len(block) + 2
    return (
        NormalizedText(
            text="\n\n".join(blocks),
            metadata={
                "source_key": EXA_SEARCH_SOURCE_KEY,
                "records": len(used),
                "record_urls": [record.url for record in used],
            },
        ),
        used,
    )


def _identifiers(account: AccountEntity) -> frozenset[str]:
    """Every string whose whole-word presence marks a record as being about this account: the
    canonical name, the aliases, and the registrable domain (a comparison page routinely names the
    domain rather than the legal name)."""
    domain = registrable_host(account.primary_domain)
    names = entity_name_tokens(account)
    return names | {domain} if domain else names


def _on_entity(record: _Record, account: AccountEntity, identifiers: frozenset[str]) -> bool:
    """Target-lock for ONE record: is this page about this client (not a same-name company)?"""
    domain = registrable_host(account.primary_domain)
    if domain is not None and registrable_host(record.url) == domain:
        return True
    if not identifiers:
        return False  # unsatisfiable → refuse, never guess
    return names_present(_quotable(record), identifiers)


def _outcome(refusal: str | None, records: Sequence[_Record], claims: Sequence[Claim]) -> str:
    """Why this call ended the way it did — the one span attribute that distinguishes the three
    very different kinds of empty answer (mirrors the tier-4 ``grounded._outcome``)."""
    if refusal is not None:
        return "provider_refused"
    if claims:
        return "hit"
    return "miss" if records else "empty"


class ExaSearchResolver:
    """A tier-3 :class:`~clue_core.Resolver` over an open-web search API.

    ``extractor`` is the shared production claim extractor (the composition root's single instance);
    ``accounts`` is the :class:`~clue_research.resolvers.live.AccountLookup` the Stage-0 binder
    supplies once identity resolution has produced the client's account record. ``http`` is the
    shared JSON transport, injectable so tests drive the whole resolver without a network or a
    credential.
    """

    tier: int = _TIER3

    def __init__(
        self,
        *,
        extractor: ClaimExtractor,
        accounts: AccountLookup,
        config: ExaSearchConfig | None = None,
        secrets: Secrets | None = None,
        http: HttpFetcher = get_json,
    ) -> None:
        self._extractor = extractor
        self._accounts = accounts
        self._config = config or DEFAULT_EXA_SEARCH_CONFIG
        self._secrets = secrets
        self._http = http
        self._cost_cents = _seed_cost()

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        if entity.entity_type is not EntityType.ACCOUNT:
            return []
        template = self._config.query_templates.get(field.field_key)
        if template is None:
            return []  # a field this source cannot ask about — no request, no spend
        account = self._accounts.key_for(entity.entity_id)
        if account is None:
            return []  # unknown id → hard miss (the field may end empty+flagged, never guessed)

        with traced_step(
            f"search.{EXA_SEARCH_SOURCE_KEY}",
            **{
                ATTR_SOURCE_KEY: EXA_SEARCH_SOURCE_KEY,
                ATTR_FIELD_KEY: field.field_key,
                ATTR_ENTITY_ID: entity.entity_id,
            },
        ) as span:
            records: list[_Record] = []
            refusal: str | None = None
            try:
                records = _records(
                    self._search(_render_query(template, account, field.field_key)), self._config
                )
            except (ProviderResponseError, CredentialError) as exc:
                # A HARD provider refusal — a 4xx (revoked key, exhausted credits, malformed
                # query) or a credential that vanished between binding and this call. A retry
                # would not fix it, so it is a hard MISS: this field ends empty+flagged and the
                # rest of the recon lane continues. Letting it escape would fail the WHOLE
                # `reverse_profile` run (the waterfall bare-raises; `client_kb` re-raises), which
                # is the exact outcome the composition root's credential gate exists to prevent —
                # and the gate only covers "never configured", not "stopped working".
                refusal = type(exc).__name__
                log.warning(
                    "research.exa_search.provider_refused",
                    field_key=field.field_key,
                    source_key=EXA_SEARCH_SOURCE_KEY,
                    error_type=refusal,
                    detail=str(exc),
                )
            except RetryableResolverError as exc:
                # A TRANSIENT fault that already spent its retries: `get_json` loops `retries + 1`
                # times before re-raising. Kept a SEPARATE branch from the hard refusal so the logs
                # still distinguish "the provider said no" from "the provider was down" — but the
                # outcome is the same honest-empty miss, because in this resolver's ONLY caller
                # (the Stage-0 recon background lane) there is no retrier left: `reverse_profile`
                # re-raises, the savepoint rolls back every background claim, the lane goes
                # `failed`, and the driver never re-drives it. Propagating would trade one empty
                # optional field for the entire background research pass, permanently.
                refusal = type(exc).__name__
                log.warning(
                    "research.exa_search.provider_transient_exhausted",
                    field_key=field.field_key,
                    source_key=EXA_SEARCH_SOURCE_KEY,
                    error_type=refusal,
                    detail=str(exc),
                )
            claims: list[Claim] = []
            drafts: list[ClaimDraft] = []
            wrong_field = unattributed = ungrounded = off_entity = 0
            if records:
                normalized, used = _document(records, self._config)
                drafts = list(self._extractor.extract(normalized, entity, field))
                by_url = {record.url: record for record in used}
                identifiers = _identifiers(account)
                for draft in drafts:
                    if draft.field_key != field.field_key:
                        wrong_field += 1
                        continue
                    record = by_url.get(draft.source_url or "")
                    if record is None:
                        unattributed += 1  # cites a page this call never retrieved (or nothing)
                        continue
                    if draft.evidence_span not in _quotable(record):
                        # Grounded-only, tightened to the CITED record: a span from record 1 under
                        # record 3's url would otherwise pass the document-wide substring test and
                        # then be target-locked against the wrong page. The claim's quote and its
                        # citation must come from the same place.
                        ungrounded += 1
                        continue
                    if not _on_entity(record, account, identifiers):
                        off_entity += 1
                        continue
                    claims.append(self._claim(account, field, draft, first=not claims))
            # The draft arithmetic reconciles: n_drafts == n_claims + every drop counter, so a
            # silently-empty field is diagnosable from the span alone. ``outcome`` names WHY an
            # empty answer is empty — refused (the provider said no), miss (records came back and
            # every candidate failed a guard), or empty (nothing was returned to judge).
            apply_attributes(
                span,
                {
                    "outcome": _outcome(refusal, records, claims),
                    "refusal": refusal or "",
                    "n_records": len(records),
                    "n_drafts": len(drafts),
                    "n_dropped_wrong_field": wrong_field,
                    "n_dropped_unattributed": unattributed,
                    "n_dropped_ungrounded": ungrounded,
                    "n_dropped_off_entity": off_entity,
                    ATTR_N_CLAIMS: len(claims),
                },
            )
        return claims

    def _search(self, query: str) -> Any:
        """One search request. The credential is resolved at *call* time, so binding this resolver
        never needs a live key.

        Raises what the shared transport raises; ``resolve`` decides what to do with each fault.
        Both a hard refusal (``ProviderResponseError`` / ``CredentialError``) and a transient fault
        that outlived the transport's own retries (``RetryableResolverError``) are caught there and
        become a hard miss — nothing retries this resolver's only lane, so a propagating 503 would
        kill the whole recon run exactly as a 402 would. Every other exception still propagates."""
        token = resolve_credential(
            AUTH_REF, source_key=EXA_SEARCH_SOURCE_KEY, secrets=self._secrets
        )
        return self._http(
            self._config.endpoint,
            source_key=EXA_SEARCH_SOURCE_KEY,
            method="POST",
            headers={"content-type": "application/json", "x-api-key": token.get_secret_value()},
            json_body={
                "query": query,
                "type": self._config.search_type,
                "numResults": self._config.num_results,
                "contents": {"text": True},
            },
            timeout=self._config.timeout_s,
            retries=self._config.retries,
        )

    def _claim(
        self, account: AccountEntity, field: FieldDef, draft: ClaimDraft, *, first: bool
    ) -> Claim:
        """One tier-3 ``api`` claim from a surviving draft. The call's cost rides the FIRST claim
        only: the waterfall sums per-claim cost, so charging each would bill one search twice.
        ``run_id``/``research_mode`` are placeholders the waterfall's ``_finalize`` restamps."""
        return account_claim(
            entity_id=account.id,
            field_key=field.field_key,
            value_json=draft.value,
            source_tier=_TIER3,
            extraction_method=ExtractionMethod.API,
            confidence=draft.confidence,
            run_id=new_run_id(),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url=draft.source_url,
            evidence_span=draft.evidence_span,
            cost_cents=self._cost_cents if first else Decimal(0),
        )


def register_exa_search_resolver(
    *,
    extractor: ClaimExtractor,
    accounts: AccountLookup,
    config: ExaSearchConfig | None = None,
    secrets: Secrets | None = None,
    http: HttpFetcher = get_json,
) -> None:
    """Bind the resolver to its ``source_key`` (the in-process dispatch the waterfall uses).

    The DB manifest row is *not* written here: ``exa_search`` is a seed manifest, so
    ``seed_source_manifests`` owns registration and this only supplies the resolver. The seeded tier
    is re-asserted against the resolver's own, because the whole "the fast lane walks past this at
    zero spend" property rests on them agreeing. Idempotent (last write wins per key).
    """
    entry = next((m for m in SEED_MANIFESTS if m.source_key == EXA_SEARCH_SOURCE_KEY), None)
    if entry is None or entry.tier != _TIER3:
        raise ValueError(
            f"{EXA_SEARCH_SOURCE_KEY!r} must be seeded as a tier-{_TIER3} manifest before its "
            f"resolver is bound (found: {entry.tier if entry is not None else 'no manifest'})"
        )
    bind_resolver(
        EXA_SEARCH_SOURCE_KEY,
        ExaSearchResolver(
            extractor=extractor,
            accounts=accounts,
            config=config,
            secrets=secrets,
            http=http,
        ),
    )


__all__ = [
    "AUTH_REF",
    "DEFAULT_EXA_SEARCH_CONFIG",
    "DEFAULT_QUERY_TEMPLATES",
    "EXA_SEARCH_SOURCE_KEY",
    "ExaSearchConfig",
    "ExaSearchResolver",
    "register_exa_search_resolver",
]
