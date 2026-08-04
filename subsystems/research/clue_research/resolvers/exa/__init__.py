"""Target-locked Exa Search Deep contract for account profiling (M8B E0).

This provider package owns the Exa-specific wire compiler, strict/additive response parsing,
schema-aware grounded normalization, and the fail-closed boundary before durable acquisition.
Durability, dispatch, reservation, snapshots, settlement, and replay belong to E1; claim
materialization and verification belong to E2.

The compiler intentionally receives admitted field keys together with their *effective registry
value schemas*. Directional text from A2 is accepted only as bounded query material and can never
add an output field. Production registration binds a disabled backend until E1 owns a durable
operation; the compatibility harness can consume only an explicitly injected provider double.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

from clue_core import AccountEntity, FieldDef, FieldKey, ResolverError, RetryableResolverError
from clue_research.resolvers.exa.deep_contract import (
    ACCOUNT_DEEP_CONTENT_MAX_CHARACTERS,
    EXA_OUTPUT_MAX_FIELDS,
    ExaDeepContents,
    ExaDeepFailureClass,
    ExaDeepFieldSpec,
    ExaDeepGrounding,
    ExaDeepHighlightOptions,
    ExaDeepResult,
    ExaDeepSearchRequest,
    ExaDeepSearchResponse,
    ExaDeepTextOptions,
    exa_field_alias,
    field_key_from_exa_alias,
    validate_exa_deep_exchange,
)
from clue_research.resolvers.grounded import (
    SynthesisBackend,
    SynthesisResult,
    SynthesizedField,
    dollars_to_cost_cents,
    field_intent,
    register_synthesis_resolver,
    registrable_host,
)
from clue_research.resolvers.http import (
    DEFAULT_TIMEOUT_S,
    CredentialError,
    ProviderResponseError,
    resolve_credential,
)
from clue_research.resolvers.live import AccountLookup, HttpFetcher, HttpRequest

if TYPE_CHECKING:
    from pydantic import SecretStr

    from clue_config import Secrets

SOURCE_KEY = "exa_deep"
AUTH_REF = "CLUE_EXA_API_KEY"

_MAX_ADDITIONAL_QUERIES = 10
_MAX_RESEARCH_INTENT_CHARS = 1000


class ExaDeepConfig(BaseModel):
    """Injected E0 wire policy; provider authorization remains a separate API-root setting."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoint: str = "https://api.exa.ai/search"
    search_type: Literal["deep", "deep-reasoning"] = "deep-reasoning"
    num_results: int = Field(default=50, ge=1, le=50)
    max_additional_queries: int = Field(default=10, ge=0, le=10)
    text_max_characters: int = Field(default=10_000, ge=1, le=ACCOUNT_DEEP_CONTENT_MAX_CHARACTERS)
    highlight_max_characters: int = Field(
        default=2_000, ge=1, le=ACCOUNT_DEEP_CONTENT_MAX_CHARACTERS
    )
    timeout_s: float = Field(default=DEFAULT_TIMEOUT_S * 3, gt=0)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    low_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    medium_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    high_confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    unknown_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered_confidence_policy(self) -> ExaDeepConfig:
        if not self.low_confidence <= self.medium_confidence <= self.high_confidence:
            raise ValueError("grounding confidence policy must be ordered low <= medium <= high")
        return self


class ExaDeepCitationAttribution(BaseModel):
    """One immutable normalization record for every provider grounding citation.

    Unsupported citations remain attributable here and in the raw response but never become a
    claim candidate. E1 persists this record/raw snapshot; E0 does not invent a storage path.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    source_url: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    status: Literal["selected", "unsupported", "below_confidence", "null_field"]
    evidence_span: str | None = None
    retrieved_text: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _selected_has_inspectable_evidence(self) -> ExaDeepCitationAttribution:
        if self.status in {"selected", "below_confidence"}:
            if not self.evidence_span or not self.retrieved_text:
                raise ValueError("supported citation attribution requires inspectable evidence")
            if self.evidence_span not in self.retrieved_text:
                raise ValueError("supported evidence span must occur in retrieved text")
        elif self.evidence_span is not None or self.retrieved_text is not None:
            raise ValueError("unselected citation attribution cannot carry evidence")
        return self


class ExaDeepNormalization(BaseModel):
    """Provider-neutral candidates plus the lossless citation disposition E1 must persist."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1)
    all_null: bool
    synthesis: SynthesisResult
    citations: tuple[ExaDeepCitationAttribution, ...] = ()

    @model_validator(mode="after")
    def _all_null_is_an_empty_paid_miss(self) -> ExaDeepNormalization:
        if self.all_null and self.synthesis.fields:
            raise ValueError("an all-null provider response cannot emit synthesized fields")
        return self


DEFAULT_EXA_CONFIG = ExaDeepConfig()


class ExaDeepRequestFailure(ResolverError):
    """Typed provider failure consumed by E1's durable outcome/settlement state machine."""

    def __init__(
        self,
        message: str,
        *,
        failure_class: ExaDeepFailureClass,
        dispatched: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.dispatched = dispatched
        self.status_code = status_code


def _single_line(value: str) -> str:
    return " ".join(value.split())


def _identity_query_suffix(account: AccountEntity) -> str:
    hints: list[str] = []
    aliases = tuple(_single_line(alias) for alias in account.aliases if _single_line(alias))
    if aliases:
        hints.append(f"aliases: {', '.join(aliases)}")
    geo = account.hq_geo or {}
    for key in ("country", "country_code", "city", "region"):
        value = geo.get(key)
        if isinstance(value, str) and _single_line(value):
            hints.append(f"geography: {_single_line(value)}")
            break
    return f" Identity hints: {'; '.join(hints)}." if hints else ""


def _nullable_schema(value_schema: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Copy one registry schema and admit null using one standard JSON-Schema type union.

    Type-specific constraints are ignored for a null instance under JSON Schema. An enum is the one
    exception: it must list null explicitly, so the compiler adds it without mutating the registry
    input. E0-R1 deliberately emits no ``anyOf``/``oneOf`` schema composition.
    """

    schema = copy.deepcopy(dict(value_schema))
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        schema["type"] = [schema_type, "null"] if schema_type != "null" else ["null"]
    elif isinstance(schema_type, list) and all(isinstance(item, str) for item in schema_type):
        if "null" not in schema_type:
            schema["type"] = [*schema_type, "null"]
    else:
        raise ValueError("effective field value_schema must declare a JSON schema type")
    enum = schema.get("enum")
    if isinstance(enum, list) and None not in enum:
        schema["enum"] = [*enum, None]
    return schema


def _compile_additional_queries(
    account: AccountEntity,
    queries: Sequence[str],
    *,
    config: ExaDeepConfig,
) -> tuple[str, ...] | None:
    if len(queries) > config.max_additional_queries:
        raise ValueError(
            "directional query count exceeds the configured account-deep policy "
            f"({len(queries)} > {config.max_additional_queries})"
        )
    if len(queries) > _MAX_ADDITIONAL_QUERIES:
        raise ValueError("Exa Deep admits at most ten additional queries")
    account_name = _single_line(account.canonical_name)
    compiled = tuple(f"{account_name} {_single_line(query)}" for query in queries)
    if any(query == account_name for query in compiled):
        raise ValueError("directional queries must be non-empty")
    if len(compiled) != len(set(compiled)):
        raise ValueError("directional queries must be unique")
    return compiled or None


def compile_exa_deep_request(
    account: AccountEntity,
    fields: Sequence[ExaDeepFieldSpec],
    *,
    research_intent: str,
    additional_queries: Sequence[str] = (),
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
) -> ExaDeepSearchRequest:
    """Compile a deterministic, closed, target-locked structured Search request.

    ``research_intent`` and ``additional_queries`` may originate in a confirmed A2 directive, but
    they only influence query text. The output keys and schemas come exclusively from admitted
    effective-registry specs, so prompt text cannot enlarge the data contract.
    """

    if not fields or len(fields) > EXA_OUTPUT_MAX_FIELDS:
        raise ValueError(
            f"Exa Deep requires between one and {EXA_OUTPUT_MAX_FIELDS} admitted fields"
        )
    by_key = {spec.field_key: spec for spec in fields}
    if len(by_key) != len(fields):
        raise ValueError("Exa Deep field specs must have unique field keys")

    intent = _single_line(research_intent).rstrip(".")
    if not intent:
        raise ValueError("research_intent must be non-empty")
    if len(intent) > _MAX_RESEARCH_INTENT_CHARS:
        raise ValueError("research_intent exceeds the 1000-character product cap")

    account_name = _single_line(account.canonical_name)
    if not account_name:
        raise ValueError("canonical account name is required for target lock")
    domain = registrable_host(account.primary_domain)
    target = f"{account_name} at {domain}" if domain is not None else account_name
    prompt_target = f"at {domain}" if domain is not None else f'named "{account_name}"'
    aliases = {key: exa_field_alias(key) for key in sorted(by_key)}
    properties: dict[str, JsonValue] = {
        aliases[key]: _nullable_schema(by_key[key].value_schema) for key in sorted(by_key)
    }
    field_map = "; ".join(f"{aliases[key]}={key}" for key in sorted(by_key))
    output_schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    return ExaDeepSearchRequest(
        query=(
            f"Research the exact account {target} for {intent}.{_identity_query_suffix(account)}"
        ),
        search_type=config.search_type,
        num_results=config.num_results,
        additional_queries=_compile_additional_queries(account, additional_queries, config=config),
        system_prompt=(
            f"Research only the exact account {prompt_target}. Prefer primary sources, retain "
            "every source URL, do not drift to similarly named organizations, and leave the "
            f"field null when target-locked evidence is absent. Use this exact property map: "
            f"{field_map}."
        ),
        output_schema=output_schema,
        contents=ExaDeepContents(
            highlights=ExaDeepHighlightOptions(
                query="Find direct evidence for the requested account fields.",
                max_characters=config.highlight_max_characters,
            ),
            text=ExaDeepTextOptions(max_characters=config.text_max_characters),
        ),
        stream=False,
    )


def _as_http_request(
    request: ExaDeepSearchRequest,
    token: SecretStr | None,
    *,
    config: ExaDeepConfig,
) -> HttpRequest:
    headers = {"content-type": "application/json"}
    if token is not None:
        headers["x-api-key"] = token.get_secret_value()
    return HttpRequest(
        url=config.endpoint,
        method="POST",
        headers=headers,
        json_body=request.model_dump(mode="json", by_alias=True, exclude_none=True),
    )


def build_exa_deep_http_request(
    request: ExaDeepSearchRequest,
    token: SecretStr | None,
    *,
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
) -> HttpRequest:
    """Build E1's already-compiled coalesced request without dispatching it."""

    return _as_http_request(request, token, config=config)


def build_exa_request(
    account: AccountEntity,
    field: FieldDef,
    token: SecretStr | None,
    *,
    value_schema: Mapping[str, JsonValue],
    research_intent: str | None = None,
    additional_queries: Sequence[str] = (),
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
) -> HttpRequest:
    """Build the one-field compatibility request used by the existing resolver seam."""

    request = compile_exa_deep_request(
        account,
        (ExaDeepFieldSpec(field_key=field.field_key, value_schema=dict(value_schema)),),
        research_intent=research_intent or f"grounded {field_intent(field)} evidence",
        additional_queries=additional_queries,
        config=config,
    )
    return _as_http_request(request, token, config=config)


def parse_exa_deep_response(
    request: ExaDeepSearchRequest,
    payload: Mapping[str, Any],
) -> ExaDeepSearchResponse:
    """Parse an additive response and prove it answers exactly the requested field set."""

    response = ExaDeepSearchResponse.model_validate(payload)
    validate_exa_deep_exchange(request, response)
    return response


def _confidence(grounding: ExaDeepGrounding, config: ExaDeepConfig) -> float:
    return {
        "low": config.low_confidence,
        "medium": config.medium_confidence,
        "high": config.high_confidence,
        None: config.unknown_confidence,
    }[grounding.confidence]


_TOKEN = re.compile(r"[a-z0-9]+")
_SENTENCE_BREAK = re.compile(r"(?:\r?\n)+|(?<=[.!?])\s+")
_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "account",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "by",
        "can",
        "could",
        "for",
        "from",
        "had",
        "has",
        "have",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "our",
        "that",
        "the",
        "their",
        "these",
        "this",
        "those",
        "to",
        "was",
        "were",
        "will",
        "with",
        "would",
        "your",
    }
)


def _stem_token(token: str) -> str:
    if len(token) > 5 and token.endswith("ies"):
        token = f"{token[:-3]}y"
    elif len(token) > 5 and token.endswith("ing"):
        token = token[:-3]
    elif len(token) > 4 and token.endswith(("ed", "ches", "shes", "xes", "zes")):
        token = token[:-2]
    elif len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    if len(token) > 4 and token.endswith("e"):
        token = token[:-1]
    return token


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        stemmed
        for raw in _TOKEN.findall(text.casefold())
        if raw not in _STOP_WORDS
        if len(stemmed := _stem_token(raw)) >= 2
    )


def _value_tokens(value: JsonValue) -> frozenset[str]:
    if value is None or isinstance(value, bool):
        return frozenset()
    if isinstance(value, str):
        return _tokens(value)
    if isinstance(value, (int, float)):
        return frozenset({str(value).casefold()})
    if isinstance(value, list):
        return frozenset().union(*(_value_tokens(item) for item in value))
    if isinstance(value, dict):
        return frozenset().union(*(_value_tokens(item) for item in value.values()))
    return frozenset()


def _candidate_passages(result: ExaDeepResult) -> tuple[tuple[str, str, int, int], ...]:
    """Return exact retained passages as ``(span, retrieved, highlight_priority, order)``."""

    passages: list[tuple[str, str, int, int]] = []
    seen: set[str] = set()
    order = 0
    for raw_highlight in result.highlights:
        highlight = raw_highlight.strip()
        if highlight and highlight not in seen:
            passages.append((highlight, highlight, 1, order))
            seen.add(highlight)
            order += 1
    text = result.text.strip() if result.text is not None else ""
    if text:
        for raw_passage in _SENTENCE_BREAK.split(text):
            passage = raw_passage.strip()
            if passage and passage not in seen:
                passages.append((passage, text, 0, order))
                seen.add(passage)
                order += 1
    return tuple(passages)


def _support_score(
    passage: str, *, field_key: str, value: JsonValue
) -> tuple[int, float, int] | None:
    passage_tokens = _tokens(passage)
    value_tokens = _value_tokens(value)
    field_tokens = _tokens(field_key.replace(".", " ").replace("_", " "))
    shared_value = passage_tokens & value_tokens
    shared_field = passage_tokens & field_tokens
    if value_tokens:
        required = 1 if len(value_tokens) <= 2 else 2
        if len(shared_value) < required:
            return None
        return len(shared_value), len(shared_value) / len(value_tokens), len(shared_field)
    if not shared_field:
        return None
    return 0, 0.0, len(shared_field)


def _best_grounded_span(
    result: ExaDeepResult,
    *,
    field_key: str,
    value: JsonValue,
) -> tuple[str, str] | None:
    best: tuple[tuple[int, float, int, int, int], str, str] | None = None
    for evidence_span, retrieved_text, highlight_priority, order in _candidate_passages(result):
        support = _support_score(evidence_span, field_key=field_key, value=value)
        if support is None:
            continue
        ranked = (*support, highlight_priority, -order)
        if best is None or ranked > best[0]:
            best = ranked, evidence_span, retrieved_text
    return None if best is None else (best[1], best[2])


def normalize_exa_deep_snapshot(
    request: ExaDeepSearchRequest,
    response: ExaDeepSearchResponse,
    *,
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
) -> ExaDeepNormalization:
    """Validate and normalize one immutable response without dropping citation attribution."""

    validate_exa_deep_exchange(request, response)
    result_by_url = {str(result.url): result for result in response.results}
    groundings = {
        field_key_from_exa_alias(grounding.field.removeprefix("content.")): grounding
        for grounding in response.output.grounding
    }
    fields: list[SynthesizedField] = []
    citations: list[ExaDeepCitationAttribution] = []
    for field_alias, value in response.output.content.items():
        field_key = field_key_from_exa_alias(field_alias)
        grounding = groundings.get(field_key)
        if grounding is None:
            continue
        confidence = _confidence(grounding, config)
        for citation in grounding.citations:
            result = result_by_url[str(citation.url)]
            status: Literal["selected", "unsupported", "below_confidence", "null_field"]
            span: tuple[str, str] | None = None
            if value is None:
                status = "null_field"
            else:
                span = _best_grounded_span(result, field_key=field_key, value=value)
                if span is None:
                    status = "unsupported"
                elif confidence < config.min_confidence:
                    status = "below_confidence"
                else:
                    status = "selected"
            evidence_span, retrieved_text = span if span is not None else (None, None)
            citations.append(
                ExaDeepCitationAttribution(
                    field_key=field_key,
                    source_url=str(citation.url),
                    source_title=citation.title,
                    status=status,
                    evidence_span=evidence_span,
                    retrieved_text=retrieved_text,
                    confidence=confidence,
                )
            )
            if status == "selected":
                if evidence_span is None or retrieved_text is None:  # defensive type narrowing
                    raise ValueError("selected citation is missing inspectable evidence")
                fields.append(
                    SynthesizedField(
                        field_key=field_key,
                        value=value,
                        source_url=str(citation.url),
                        evidence_span=evidence_span,
                        retrieved_text=retrieved_text,
                        confidence=confidence,
                    )
                )
    synthesis = SynthesisResult(
        fields=tuple(fields),
        cost_cents=dollars_to_cost_cents(response.cost_dollars.total),
    )
    return ExaDeepNormalization(
        request_id=response.request_id,
        all_null=all(value is None for value in response.output.content.values()),
        synthesis=synthesis,
        citations=tuple(citations),
    )


def normalize_exa_deep_response(
    request: ExaDeepSearchRequest,
    response: ExaDeepSearchResponse,
    *,
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
) -> SynthesisResult:
    """Compatibility projection of the lossless E0 normalization onto the stable synthesis seam."""

    return normalize_exa_deep_snapshot(request, response, config=config).synthesis


def normalize_exa_response(
    payload: Mapping[str, Any],
    field: FieldDef,
    *,
    request: ExaDeepSearchRequest,
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
) -> SynthesisResult:
    """Compatibility wrapper for the one-field resolver backend; structured responses only."""

    response = parse_exa_deep_response(request, payload)
    if set(response.output.content) != {exa_field_alias(field.field_key)}:
        raise ValueError("one-field Exa resolver received a different structured field set")
    return normalize_exa_deep_response(request, response, config=config)


class ExaDeepSynthesisBackend:
    """One-field response harness over the E0 structured wire contract.

    The transport is mandatory and must be explicitly injected. Production never constructs this
    harness: E1 will call :func:`compile_exa_deep_request` for coalesced fields and own durable
    dispatch before a snapshot-backed materializer is registered.
    """

    def __init__(
        self,
        *,
        http: HttpFetcher,
        field_schemas: Mapping[str, Mapping[str, JsonValue]],
        config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
        additional_queries_by_field: Mapping[str, Sequence[str]] | None = None,
        research_intents_by_field: Mapping[str, str] | None = None,
        secrets: Secrets | None = None,
    ) -> None:
        self._field_schemas = {
            key: copy.deepcopy(dict(schema)) for key, schema in field_schemas.items()
        }
        self._additional_queries_by_field = dict(additional_queries_by_field or {})
        self._research_intents_by_field = dict(research_intents_by_field or {})
        self._config = config
        self._http = http
        self._timeout = config.timeout_s
        self._secrets = secrets

    def synthesize(self, account: AccountEntity, field: FieldDef) -> SynthesisResult:
        schema = self._field_schemas.get(field.field_key)
        if schema is None:
            raise ExaDeepRequestFailure(
                f"no effective registry value_schema supplied for {field.field_key!r}",
                failure_class=ExaDeepFailureClass.HARD,
                dispatched=False,
            )
        try:
            token = resolve_credential(AUTH_REF, source_key=SOURCE_KEY, secrets=self._secrets)
            http_request = build_exa_request(
                account,
                field,
                token,
                value_schema=schema,
                research_intent=self._research_intents_by_field.get(field.field_key),
                additional_queries=self._additional_queries_by_field.get(field.field_key, ()),
                config=self._config,
            )
            if http_request.json_body is None:  # defensive; the E0 builder always emits JSON
                raise ValueError("compiled Exa Deep request has no JSON body")
            request = ExaDeepSearchRequest.model_validate(http_request.json_body)
        except (CredentialError, ValidationError, ValueError) as exc:
            raise ExaDeepRequestFailure(
                f"{SOURCE_KEY}: request rejected before dispatch: {exc}",
                failure_class=ExaDeepFailureClass.HARD,
                dispatched=False,
            ) from exc
        try:
            payload = self._http(
                http_request.url,
                source_key=SOURCE_KEY,
                method=http_request.method,
                headers=http_request.headers,
                params=http_request.params,
                json_body=http_request.json_body,
                timeout=self._timeout,
                retries=0,
            )
        except ExaDeepRequestFailure:
            raise
        except (RetryableResolverError, ProviderResponseError) as exc:
            raise ExaDeepRequestFailure(
                f"{SOURCE_KEY}: ambiguous failure after dispatch: {exc}",
                failure_class=ExaDeepFailureClass.SPEND_UNKNOWN,
                dispatched=True,
            ) from exc
        if not isinstance(payload, Mapping):
            raise ExaDeepRequestFailure(
                f"{SOURCE_KEY}: non-object success response",
                failure_class=ExaDeepFailureClass.SPEND_UNKNOWN,
                dispatched=True,
            )
        try:
            return normalize_exa_response(payload, field, request=request, config=self._config)
        except (ValidationError, ValueError) as exc:
            raise ExaDeepRequestFailure(
                f"{SOURCE_KEY}: malformed or non-settleable success response: {exc}",
                failure_class=ExaDeepFailureClass.SPEND_UNKNOWN,
                dispatched=True,
            ) from exc


class _ExaDeepAcquisitionRequiredBackend:
    """Production placeholder that makes resolver-time dispatch impossible before E1."""

    def synthesize(self, account: AccountEntity, field: FieldDef) -> SynthesisResult:
        del account, field
        raise ExaDeepRequestFailure(
            "exa_deep resolver-time acquisition is disabled; E1 must provide a durable ready "
            "snapshot backend",
            failure_class=ExaDeepFailureClass.HARD,
            dispatched=False,
        )


def make_backend(
    *,
    http: HttpFetcher,
    field_schemas: Mapping[str, Mapping[str, JsonValue]] | None = None,
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
    additional_queries_by_field: Mapping[str, Sequence[str]] | None = None,
    research_intents_by_field: Mapping[str, str] | None = None,
    secrets: Secrets | None = None,
) -> ExaDeepSynthesisBackend:
    """Build the doubles-only E0 response harness with an explicit injected transport."""

    return ExaDeepSynthesisBackend(
        field_schemas=field_schemas or {},
        config=config,
        additional_queries_by_field=additional_queries_by_field,
        research_intents_by_field=research_intents_by_field,
        http=http,
        secrets=secrets,
    )


def register_exa_deep_resolver(
    *,
    accounts: AccountLookup | None = None,
    backend: SynthesisBackend | None = None,
) -> None:
    """Bind Exa behind the stable seam; default production binding cannot acquire over HTTP."""

    register_synthesis_resolver(
        SOURCE_KEY,
        backend or _ExaDeepAcquisitionRequiredBackend(),
        accounts=accounts,
        # A valid structured response always reports cost. Missing cost is spend_unknown, never a
        # manifest-price fallback masquerading as settlement. E1 owns reservation/reconciliation.
        default_cost_cents=Decimal(0),
    )


__all__ = [
    "AUTH_REF",
    "ACCOUNT_DEEP_CONTENT_MAX_CHARACTERS",
    "EXA_OUTPUT_MAX_FIELDS",
    "SOURCE_KEY",
    "DEFAULT_EXA_CONFIG",
    "ExaDeepConfig",
    "ExaDeepCitationAttribution",
    "ExaDeepFailureClass",
    "ExaDeepFieldSpec",
    "ExaDeepNormalization",
    "ExaDeepRequestFailure",
    "ExaDeepSearchRequest",
    "ExaDeepSearchResponse",
    "ExaDeepSynthesisBackend",
    "build_exa_request",
    "build_exa_deep_http_request",
    "compile_exa_deep_request",
    "exa_field_alias",
    "field_key_from_exa_alias",
    "make_backend",
    "normalize_exa_deep_response",
    "normalize_exa_deep_snapshot",
    "normalize_exa_response",
    "parse_exa_deep_response",
    "register_exa_deep_resolver",
]
