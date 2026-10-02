"""The shared tier-4 grounded-synthesis substrate (M11.1 / M11.2 / ENG-143).

Exa Deep and Parallel Task are the **same** :class:`GroundedSynthesisResolver` wrapping a different
:class:`SynthesisBackend` — the tier-4 analogue of the tier-1
:class:`~clue_research.resolvers.base.DeterministicResolver` over an
:class:`~clue_research.resolvers.base.EnrichmentBackend`. That split is the whole point of the
milestone:

* the **backend** holds everything provider-specific — the entity-bound query construction
  (target-lock at the *query* level) and the provider API call + normalization of its response into
  provider-agnostic :class:`SynthesizedField`\\s, each carrying a mandatory citation + span.
  It lives in the provider's own sub-package (``resolvers/<provider>/``), the only place a provider
  SDK may be imported (import-linter Rule 4); nothing it returns carries a provider-shaped type.
* the **resolver** is provider-agnostic and enforces the tier-4 disciplines **once** (substrate
  §4/§13 — the LLM is the *least*-trusted source, so it is the *most*-constrained):

  - **grounded-only** — a value with no retrieved evidence span, or a span absent from its retrieved
    source, is dropped. The LLM may plan/expand queries but may never *be* the source (the
    parametric-listing prohibition, staged-flow §3/§8). No retrieved evidence ⇒ no value.
  - **target-lock (anti-drift)** — off-entity evidence (the same-name-competitor trap) is *rejected,
    not blended* (staged-flow §5): a record survives only if it cites the resolved entity's own
    domain or names the canonical name / an alias.
  - **no self-promotion** — claims are returned ``unverified``; the faithfulness judge (M9.3) owns
    the verdict (substrate §1/§6).
  - **empty-on-miss** — a miss / every candidate failing a guard / no resolved account returns
    ``[]`` (the field may end empty+flagged — a *correct* output), never a fabricated value.

Because the only thing that changes between providers is the injected backend, swapping Exa for
Parallel (or a future provider) is binding a different backend to the same ``source_key`` — a
``tier_plan``/config edit, not a caller change (the "nothing knows Exa exists" invariant, substrate
§4/§12). The waterfall (M4.1) stamps the engine-owned provenance the resolver cannot know
(``source_key``/``run_id``/``research_mode``) and the cross-tenant ``reuse_scope``; the resolver
supplies only what the *source* knows — value, span, citation, confidence, cost.

This resolver writes **account** claims only — the M11 account-synthesis path. Tier-4 *contact*
synthesis (``contact.facet.*``) is governed by Doc D / M10 (use-class tagging + the appropriateness/
use gate + identity-binding) and is **not** built here; the resolver returns ``[]`` for a contact
entity or a contact-class field, so the personal-data firewall holds structurally (a contact claim
is never written by this path).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from clue_core import (
    AccountEntity,
    Claim,
    Confidence,
    CostCents,
    Entity,
    EntityType,
    ExtractionMethod,
    FieldClass,
    FieldDef,
    FieldKey,
    ResearchMode,
    ResolverError,
    account_claim,
    new_run_id,
    normalize_host,
    parse_cost_cents,
    revalidate_with,
    serialize_value_json,
    to_value_json,
)
from clue_obs.otel import (
    ATTR_COST_CENTS,
    ATTR_ENTITY_ID,
    ATTR_FIELD_KEY,
    ATTR_N_CLAIMS,
    ATTR_SOURCE_KEY,
    apply_attributes,
    traced_step,
)
from clue_research.resolvers.http import (
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT_S,
    get_json,
    resolve_credential,
)
from clue_research.resolvers.live import AccountLookup, HttpFetcher, HttpRequest

if TYPE_CHECKING:
    from pydantic import SecretStr

    from clue_config import Secrets

# The tier-4 trust tier these resolvers always produce. The claim model enforces tier-4 ⟺
# llm_synthesis; the waterfall's _finalize re-asserts the manifest tier matches.
_TIER4 = 4

# Max chars of a backend's reasoning rationale recorded on the trace span — a synthesis rationale
# can be long, and a span attribute must stay bounded (the reasoning is an audit aid, not evidence).
_REASONING_TRACE_CAP = 2000

# Field-classes this account-synthesis resolver writes. A contact-class field (CONTACT /
# CONTACT_FACET) routes through M10's governed path, never here (the personal-data firewall).
_ACCOUNT_SYNTHESIS_CLASSES: frozenset[FieldClass] = frozenset(
    {FieldClass.CORE, FieldClass.ACCOUNT, FieldClass.ACCOUNT_RESONANCE, FieldClass.PACK}
)


class SynthesizedField(BaseModel):
    """One grounded synthesis for a field value — the shape a :class:`SynthesisBackend` returns.

    Carries exactly what a grounded tier-4 source knows: the typed ``value``, the citing
    ``source_url`` (construction admits a synthesis claim without one — ARV2 D1 moved the rule to
    ``can_be_promoted``, which refuses it — so this shape requires it here instead), the
    **mandatory non-empty** ``evidence_span`` (the exact retrieved passage supporting the value — a
    span-less value cannot exist here, by type), the ``retrieved_text`` the span was drawn from (so
    the substrate can *prove* grounded-only — span ⊆ retrieved_text — and target-lock — does this
    record name the entity?), and a ``confidence``. It deliberately does **not** carry
    ``source_key``/``run_id``/``research_mode``: those are engine-owned provenance the waterfall
    stamps (synthesis never upgrades its own trust).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    value: JsonValue
    source_url: str = Field(min_length=1)
    evidence_span: str = Field(min_length=1)
    # The retrieved source text the span was drawn from (the record/highlight context). The
    # substrate asserts the span is a substring of it (grounded-only) and target-locks against it
    # (name match). When the backend only has the highlight, it sets this to the highlight itself —
    # the grounded-only invariant (span comes from a retrieved passage) still holds.
    retrieved_text: str = Field(min_length=1)
    confidence: Confidence
    # Optional durable lineage attached by a snapshot-backed adapter after acquisition.  Live
    # one-shot test backends omit it; production E2 snapshot materialization supplies all four.
    artifact_key: str | None = None
    source_operation_ref: str | None = None
    source_snapshot_ref: str | None = None
    source_request_ref: str | None = None

    @model_validator(mode="after")
    def _snapshot_lineage_is_complete(self) -> SynthesizedField:
        refs = (
            self.source_operation_ref,
            self.source_snapshot_ref,
            self.source_request_ref,
        )
        if any(ref is not None for ref in refs) and (
            self.artifact_key is None
            or not all(isinstance(ref, str) and ref.strip() for ref in refs)
        ):
            raise ValueError(
                "snapshot-backed synthesis requires artifact, operation, snapshot, and "
                "request references"
            )
        return self


class SynthesisResult(BaseModel):
    """A backend's answer for one ``(account, field)`` synthesis: grounded fields + realized cost.

    ``cost_cents`` is the **realized** per-call price the budget engine (M7.5) reads to hard-stop
    tier-4 spend — distinct from the manifest's pre-spend estimate. An empty ``fields`` is a hard
    miss (the field may end empty+flagged), never a fabricated value.

    ``reasoning`` carries a provider's synthesis *rationale* (e.g. Parallel Task's reasoning string)
    for the **trace only** — the resolver surfaces it on the span for auditability and NOTHING else.
    It is structurally barred from ever becoming an ``evidence_span``: claims are built solely from
    :class:`SynthesizedField`\\s (each a *cited, retrieved* passage), and ``_build_claims`` never
    reads this field. So "only cited source text qualifies as evidence; the LLM's reasoning never
    does" (substrate §1/§6; M11.2) is enforced by the type, not by discipline. Empty for providers
    (Exa Deep) that return none.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fields: tuple[SynthesizedField, ...] = ()
    cost_cents: CostCents = Decimal(0)
    reasoning: tuple[str, ...] = ()


@runtime_checkable
class SynthesisBackend(Protocol):
    """The swappable tier-4 provider seam: synthesize grounded field values for an entity.

    Contract (substrate §4/§12): build the **entity-bound** query (target-lock at the query level —
    the canonical name + ``aliases`` + ``hq_geo`` disambiguators, optionally the ``primary_domain``
    as a hint; never a hard ``site:`` filter — synthesis fields like resonance live on third-party
    sites such as Glassdoor/news, and off-entity drift is rejected by the resolver's target-lock
    guard, not by excluding third-party sources), call the provider, and normalize the response into
    :class:`SynthesizedField`\\s — each with a mandatory citation +
    evidence span (a candidate with no grounding is dropped *here*, never returned). An **empty**
    :class:`SynthesisResult` is a *hard miss* the waterfall advances past; a **transient** failure
    (timeout / 5xx / rate-limit) raises :class:`~clue_core.RetryableResolverError` so M7
    retries — never swallowed into an empty result. The backend is the only place that knows the
    provider's API and response shape.
    """

    def synthesize(self, account: AccountEntity, field: FieldDef) -> SynthesisResult: ...


# A provider's two pure pieces (the tier-4 analogue of live.py's BuildRequest/Normalize). The
# provider closes its config over these before wiring, so the generic backend stays config-agnostic.
# ``build_request`` shapes the entity-bound (target-locked) call from the account + resolved
# credential; ``normalize`` maps the JSON response to a grounded :class:`SynthesisResult`.
BuildSynthesisRequest = Callable[[AccountEntity, FieldDef, "SecretStr | None"], HttpRequest]
NormalizeSynthesis = Callable[[Mapping[str, Any], FieldDef], SynthesisResult]


class HttpSynthesisBackend:
    """A generic :class:`SynthesisBackend` over the shared sync HTTP transport — the tier-4 analogue
    of :class:`~clue_research.resolvers.live.HttpEnrichmentBackend`. The provider supplies only its
    ``source_key`` / ``auth_ref`` / ``build_request`` (the endpoint + auth + entity-bound query
    shape) and ``normalize`` (response → grounded :class:`SynthesisResult`); the live network call
    is the ``# pragma: no cover`` boundary (CI injects a backend double, the hermetic-CI rule). The
    credential is resolved from the manifest ``auth_ref`` at *call time* only — so binding never
    needs a live key. A non-mapping/empty response is a hard miss (an empty result), never a
    fabrication; a transient transport/HTTP fault propagates as ``RetryableResolverError``.
    """

    def __init__(
        self,
        *,
        source_key: str,
        auth_ref: str | None,
        build_request: BuildSynthesisRequest,
        normalize: NormalizeSynthesis,
        http: HttpFetcher = get_json,
        timeout: float = DEFAULT_TIMEOUT_S,
        retries: int = DEFAULT_RETRIES,
        secrets: Secrets | None = None,
    ) -> None:
        self._source_key = source_key
        self._auth_ref = auth_ref
        self._build_request = build_request
        self._normalize = normalize
        self._http = http
        self._timeout = timeout
        self._retries = retries
        self._secrets = secrets

    def synthesize(self, account: AccountEntity, field: FieldDef) -> SynthesisResult:
        token = (
            resolve_credential(self._auth_ref, source_key=self._source_key, secrets=self._secrets)
            if self._auth_ref is not None
            else None
        )
        request = self._build_request(account, field, token)
        payload = self._http(
            request.url,
            source_key=self._source_key,
            method=request.method,
            headers=request.headers,
            params=request.params,
            json_body=request.json_body,
            timeout=self._timeout,
            retries=self._retries,
        )
        if not isinstance(payload, Mapping):
            return SynthesisResult()
        return self._normalize(payload, field)


def registrable_host(value: str | None) -> str | None:
    """The lower-cased host of a bare domain or URL, minus a leading ``www.`` — the target-lock key.

    Delegates to the shared :func:`clue_core.normalize_host` fold (M9.4 DRY consolidation — one
    host normalizer with ``resolvers.firecrawl._registrable_host``, the M9.2 corroboration
    ``_host``, and the M9.4 identity-binding ``normalize_url``). Returns ``None`` when ``value``
    has no host.
    """
    if not value:
        return None
    return normalize_host(value) or None


# Per-field synthesis intent — the phrase appended to the entity-bound query so a provider retrieves
# passages relevant to *this* field (substrate §3 the synthesis fields). Provider-NEUTRAL: Exa Deep
# and Parallel Task share it (the field→intent mapping is written once). Policy-as-data keyed by
# field_key; an unenumerated field falls back to its humanized leaf, so a newly-registered resonance
# sub-field needs no code change (Doc C §2 — registered, not enumerated).
_FIELD_INTENT: dict[str, str] = {
    "account.operational_pain": "operational challenges, bottlenecks and pain points",
    "account.strategic_moves": "strategic initiatives, expansion and recent moves",
    "account.resonance.culture": "company culture, employee sentiment and morale",
}


def field_intent(field: FieldDef) -> str:
    """The retrieval-intent phrase for a synthesis field — an enumerated phrase or the humanized
    field leaf (``account.resonance.attrition`` → ``attrition``). Shared by every tier-4 provider so
    the field→intent mapping is defined exactly once (DRY)."""
    intent = _FIELD_INTENT.get(field.field_key)
    if intent is not None:
        return intent
    leaf = field.field_key.rsplit(".", 1)[-1]
    return leaf.replace("_", " ")


def entity_query(account: AccountEntity, field: FieldDef) -> str:
    """The target-locked, entity-bound query string every tier-4 provider issues (staged-flow §5):
    the canonical name (quoted), aliases, the primary domain as a *hint* (never a hard ``site:``),
    one hq-geo disambiguator, and the field intent. Binding the query to the entity is the first
    anti-drift measure; off-entity evidence that still slips through is rejected by the resolver's
    target-lock guard. Shared so Exa and Parallel build the **identical** entity-bound query — only
    the provider's wire envelope (``build_request``) differs."""
    parts: list[str] = [f'"{account.canonical_name}"']
    parts.extend(account.aliases)
    domain = registrable_host(account.primary_domain)
    if domain is not None:
        parts.append(domain)
    geo = account.hq_geo or {}
    for key in ("country", "country_code", "city", "region"):
        value = geo.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
            break
    parts.append(field_intent(field))
    return " ".join(parts)


def as_list(value: Any) -> list[Any]:
    """A list view of a JSON array, or ``[]`` for anything else — a ``str``/``bytes`` is **not** an
    array (iterating it element-wise would be a silent bug). Shared by every tier-4 provider's
    response normalizer so the "is this a JSON array?" guard is written once (DRY)."""
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return []
    return list(value)


def dollars_to_cost_cents(dollars: Any) -> CostCents:
    """Convert a USD amount to cents, defensively — absent/malformed/negative/non-finite → ``0``
    (the resolver then attributes the seed-manifest default), never a guess. The pure conversion;
    :func:`cost_cents_from_cost_dollars` reads the assumed ``costDollars.total`` shape over it."""
    amount = parse_cost_cents(dollars)
    return Decimal(0) if amount is None else amount * 100


def cost_cents_from_cost_dollars(payload: Mapping[str, Any]) -> CostCents:
    """Read a provider's realized per-call cost from the assumed ``costDollars.total`` (USD) field
    into cents — the shape both research-product APIs (Exa, Parallel) are modeled on, shared
    so the ``costDollars``→``total`` walk is written once (DRY). Absent/malformed → ``0`` (the
    resolver attributes the seed-manifest cost). A provider whose *live* response nests cost
    differently overrides this with its own reader; this then stays the shared default."""
    cost = payload.get("costDollars")
    total = cost.get("total") if isinstance(cost, Mapping) else None
    return dollars_to_cost_cents(total)


# Off-domain name-match floor: a name token shorter than this is too ambiguous to target-lock on
# (mirrors the M9.4 identity-binding ``_token_present`` ``< 2`` floor — kept local because
# ``resolvers`` may not import ``verification``; one shared matcher is a post-integration DRY item).
_MIN_NAME_TOKEN_LEN = 2


def entity_name_tokens(account: AccountEntity) -> frozenset[str]:
    """The identifier strings that mark a record as on-entity: the canonical name and every alias
    (length ≥ the floor). Target-lock keeps an off-domain record iff one of these appears as a
    **whole-word** match in the retrieved text/span (the canonical-name disambiguation, staged-flow
    §5). A token below the floor is dropped (too short to disambiguate, e.g. a 1-char alias)."""
    names = [account.canonical_name, *account.aliases]
    return frozenset(n.strip() for n in names if n and len(n.strip()) >= _MIN_NAME_TOKEN_LEN)


def _is_grounded(field: SynthesizedField) -> bool:
    """Grounded-only: the value's evidence span is a real passage from its retrieved source.

    ``SynthesizedField`` already guarantees a non-empty span + retrieved_text by type; this asserts
    the span was actually drawn from the retrieved source (not synthesized free-hand), the
    schema-level kill switch for a fabricated value that cites a real URL but invents the passage.
    """
    return field.evidence_span in field.retrieved_text


def names_present(haystack: str, names: frozenset[str]) -> bool:
    """True iff any entity name is a **whole-word** match in ``haystack`` (case-insensitive).

    Public (alongside :func:`registrable_host`) because it is the shared target-lock primitive every
    open-web resolver needs, not a tier-4 detail: the tier-3 ``exa_search`` resolver applies the
    identical rule to each search record. Writing it a second time is exactly the duplication the
    host-normalization consolidation existed to end.

    A *substring* test fails open two ways the spec's anti-drift rule forbids: a short alias matches
    inside an unrelated word (``"hp"`` in ``"championship"``) and a near-duplicate competitor whose
    name *embeds* the token (``"acme"`` in ``"acmerival"``) reads as on-entity. Word boundaries on
    both sides (``\\b``) close both. The residual — a same-name competitor reproducing the *exact*
    canonical name on a third-party page — is a true ambiguity the resolver cannot settle alone; it
    is surfaced (``unverified``) and resolved downstream by corroboration over independent tier-≤3
    sources, cross-provider convergence, and the human review surface (coverage confidence, not a
    completeness guarantee)."""
    low = haystack.lower()
    return any(re.search(rf"\b{re.escape(name.lower())}\b", low) for name in names)


def _on_entity(field: SynthesizedField, account: AccountEntity, names: frozenset[str]) -> bool:
    """Target-lock: is this record's evidence about *this* entity (not a same-name competitor)?

    Kept iff the citation's host is the account's own ``primary_domain`` **or** the canonical name /
    an alias is a whole-word match in the retrieved text or span. Off-entity evidence is rejected,
    not blended (staged-flow §5). When the account has neither a resolvable domain nor any usable
    name token, target-lock is unsatisfiable and the record is rejected (fail-closed — never
    guess)."""
    domain = registrable_host(account.primary_domain)
    if domain is not None and registrable_host(field.source_url) == domain:
        return True
    if not names:
        return False
    return names_present(f"{field.retrieved_text}\n{field.evidence_span}", names)


def _outcome(retrieved: Sequence[SynthesizedField], claims: Sequence[Claim]) -> str:
    """The synthesis-call outcome for the trace span (M11 tracing AC): ``hit`` (claims built),
    ``miss`` (records retrieved but all dropped by the grounded-only/target-lock guards), or
    ``empty`` (the backend retrieved nothing)."""
    if claims:
        return "hit"
    return "miss" if retrieved else "empty"


class GroundedSynthesisResolver:
    """A tier-4 ``Resolver`` (M0.2): provider-agnostic grounded synthesis over an injected backend.

    ``resolve`` resolves the entity to its account record (for the target-lock identifiers), asks
    the backend to synthesize, applies the grounded-only + target-lock guards, and builds tier-4
    ``llm_synthesis`` account claims (one per **distinct value**, the realized cost on the first —
    the waterfall sums per-claim cost into the step/budget). Claims are born ``unverified``;
    promotion is the merge/verification path's job (M1.2 + M9). A miss / every candidate failing a
    guard / no resolved account → ``[]`` (empty is a correct output, never a fabrication).
    """

    tier: int = _TIER4

    def __init__(
        self,
        backend: SynthesisBackend,
        accounts: AccountLookup | None = None,
        *,
        source_key: str,
        default_cost_cents: CostCents = Decimal(0),
    ) -> None:
        self._backend = backend
        self._accounts = accounts
        self._source_key = source_key
        self._default_cost_cents = default_cost_cents
        # A ready-snapshot backend performs no external I/O and owns no new spend.  The waterfall
        # reads this provider-neutral capability to skip its live-call estimate/fallback charge.
        self.materialization_only = bool(getattr(backend, "materialization_only", False))

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        # Personal-data firewall (PF-8 / M11.3): this is the *account*-synthesis path — it never
        # writes a contact claim. A contact entity or a contact-class field routes through M10's
        # governed path, not here.
        if entity.entity_type is not EntityType.ACCOUNT:
            return []
        if field.field_class not in _ACCOUNT_SYNTHESIS_CLASSES:
            return []
        if self._accounts is None:
            raise ResolverError(
                f"{self._source_key!r} synthesis resolver requires an AccountLookup (wired by the "
                "M6/M7 orchestrator) to target-lock the query to the resolved entity"
            )
        account = self._accounts.key_for(entity.entity_id)
        if account is None:
            return []  # unknown id → hard miss (the field may end empty+flagged, never guessed)

        # The resolver's own span (M11 tracing AC) — a child of the waterfall's resolve.<source_key>
        # carrying the synthesis-internal dims it can't see: retrieval count, kept count, outcome.
        # Span *duration* is the call latency; provider identity is the source_key (never branched).
        with traced_step(
            f"synthesis.{self._source_key}",
            **{
                ATTR_SOURCE_KEY: self._source_key,
                ATTR_FIELD_KEY: field.field_key,
                ATTR_ENTITY_ID: entity.entity_id,
            },
        ) as span:
            result = self._backend.synthesize(account, field)
            names = entity_name_tokens(account)
            kept = [
                sf
                for sf in result.fields
                if sf.field_key == field.field_key
                and _is_grounded(sf)
                and _on_entity(sf, account, names)
            ]
            claims = self._build_claims(account, kept, cost_cents=result.cost_cents)
            attrs: dict[str, Any] = {
                "n_retrieved": len(result.fields),
                "n_kept": len(kept),
                ATTR_N_CLAIMS: len(claims),
                "outcome": _outcome(result.fields, claims),
                ATTR_COST_CENTS: result.cost_cents,
            }
            # The strongest grounding's confidence for the call (the `confidence` tracing dim) —
            # only when something was kept (a miss/empty call has no confidence to report).
            if kept:
                attrs["confidence"] = max(float(sf.confidence) for sf in kept)
            # A backend's synthesis rationale (Parallel's "reasoning") is recorded on the trace for
            # auditability — and ONLY here. It can never become a claim's evidence_span:
            # _build_claims reads sf.evidence_span (a cited, retrieved passage), never
            # result.reasoning, so the LLM's free-hand rationale is structurally barred from
            # grounding a value (substrate §1/§6; M11.2 reasoning-vs-span). Capped so an unbounded
            # rationale can't bloat the span.
            if result.reasoning:
                attrs["reasoning"] = " | ".join(result.reasoning)[:_REASONING_TRACE_CAP]
            apply_attributes(span, attrs)
        return claims

    def _build_claims(
        self, account: AccountEntity, fields: Sequence[SynthesizedField], *, cost_cents: CostCents
    ) -> list[Claim]:
        """One tier-4 account claim per **distinct value** (dedup of Exa-vs-Parallel + corroboration
        are the verification path's job, M9.2). The realized per-call cost is attributed to the
        first claim only (the waterfall sums per-claim cost; a paid miss falls back to the manifest
        cost in the engine). Falls back to the configured default cost when the backend reports
        none."""
        price = cost_cents if cost_cents else self._default_cost_cents
        claims: list[Claim] = []
        seen: set[str] = set()
        for sf in fields:
            value_json = to_value_json(sf.value)
            dedup_key = serialize_value_json(value_json)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            claim = account_claim(
                entity_id=account.id,
                field_key=sf.field_key,
                value_json=value_json,
                source_tier=_TIER4,
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                confidence=sf.confidence,
                # run_id / research_mode are placeholders the waterfall's _finalize restamps
                # with the run's real values (the resolver cannot know the project run/mode).
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url=sf.source_url,
                evidence_span=sf.evidence_span,
                cost_cents=price if not claims else Decimal(0),
            )
            if sf.artifact_key is not None:
                claim = revalidate_with(
                    claim,
                    artifact_key=sf.artifact_key,
                    source_operation_ref=sf.source_operation_ref,
                    source_snapshot_ref=sf.source_snapshot_ref,
                    source_request_ref=sf.source_request_ref,
                )
            claims.append(claim)
        return claims


def synthesis_default_cost(source_key: str) -> CostCents:
    """The per-call default cost for a tier-4 synthesis ``source_key``, read from the **seed
    manifest** (the single source of truth for a source's price) so a backend that reports no
    realized cost never silently drifts from the registered manifest the waterfall budgets — the
    same pattern :func:`~clue_research.resolvers.register_deterministic_resolvers` uses."""
    from clue_research.sources import SEED_MANIFESTS

    for entry in SEED_MANIFESTS:
        if entry.source_key == source_key:
            return entry.cost_cents
    return Decimal(0)


def register_synthesis_resolver(
    source_key: str,
    backend: SynthesisBackend,
    *,
    accounts: AccountLookup | None = None,
    default_cost_cents: CostCents | None = None,
) -> None:
    """Bind a :class:`GroundedSynthesisResolver` over ``backend`` to ``source_key`` (the in-process
    dispatch the waterfall uses). The one place Exa (M11.1) and Parallel (M11.2) register — each
    supplies only its provider backend. ``default_cost_cents`` is the per-call cost attributed when
    the backend reports no realized cost; ``None`` (the usual case) defers to the **seed manifest**
    (the single source of truth for a source's price, so realized cost never drifts from the
    registered manifest the waterfall budgets), while a provider config may override it. Idempotent
    (last write wins per key)."""
    from clue_research.sources import bind_resolver

    bind_resolver(
        source_key,
        GroundedSynthesisResolver(
            backend,
            accounts,
            source_key=source_key,
            default_cost_cents=(
                default_cost_cents
                if default_cost_cents is not None
                else synthesis_default_cost(source_key)
            ),
        ),
    )
