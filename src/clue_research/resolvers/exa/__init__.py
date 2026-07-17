"""The Exa Deep resolver — field-level grounded tier-4 synthesis (M11.1 / ENG-143).

When tiers 1–3 (deterministic APIs → official-source scrape → reputable third party) all miss a
field that genuinely needs *synthesis* across many weak web sources — ``account.operational_pain``,
``account.strategic_moves``, ``account.resonance.*`` — the waterfall (M4.1) reaches its last rung:
Exa Deep (substrate §4 "ONLY for fields that genuinely require synthesis"; §12 "Exa Deep —
field-level grounding"). Exa retrieves real web evidence and returns highlighted passages; this
resolver turns each highlighted passage into a typed tier-4 claim *bound to its evidence span and
citation*, with a confidence.

Exa Deep is the **most dangerous source** (substrate §4/§13 — "LLM research is the least-trusted
source; it runs last"), so it is the **most constrained**. This module owns only the two pure,
provider-specific pieces (the recorded-fixture path — finalized when live credentials land):

* :func:`build_exa_request` — the entity-bound (target-locked) query: the canonical name +
  ``hq_geo`` disambiguators + ``aliases`` + a field-intent phrase, POSTed to the Exa search with
  highlights on. It does **not** restrict to the entity's own domain (resonance lives on
  Glassdoor/news/blogs, not the company site) — off-entity drift is rejected downstream by the
  shared resolver's target-lock guard, not by hard-excluding third-party sources.
* :func:`normalize_exa_response` — map each retrieved result's **highlighted passage** to a
  :class:`~clue_research.resolvers.grounded.SynthesizedField`: the passage *is* the grounded value
  (grounded-only by construction — the value is a verbatim retrieved span), cited by the result url,
  with the highlight as its evidence span. A result with no highlight/url is dropped (no grounding ⇒
  no value). Exa's relevance scores are clamped to ``[0,1]`` via the shared ``coerce_confidence``.

Everything else — the grounded-only + target-lock guards, claim construction, no-self-promotion,
empty-on-miss, the swap seam — lives **once** in :mod:`clue_research.resolvers.grounded`, so Exa
Deep and Parallel Task (M11.2) are interchangeable at the call site and a new provider is just these
pure pieces. Exa is reached through its **own** API key (``CLUE_EXA_API_KEY``), not the OpenRouter
gateway — it is a research-product API, not an OpenAI-compatible chat endpoint (conventions §2
carve-out). The provider SDK (none needed — the transport is the shared generic HTTP) would live
only here (import-linter Rule 4).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from clue_core import AccountEntity, CostCents, FieldDef
from clue_research.resolvers.base import coerce_confidence
from clue_research.resolvers.grounded import (
    HttpSynthesisBackend,
    SynthesisBackend,
    SynthesisResult,
    SynthesizedField,
    as_list,
    cost_cents_from_cost_dollars,
    entity_query,
    field_intent,
    register_synthesis_resolver,
)
from clue_research.resolvers.http import DEFAULT_RETRIES, DEFAULT_TIMEOUT_S, get_json
from clue_research.resolvers.live import AccountLookup, HttpFetcher, HttpRequest

if TYPE_CHECKING:
    from pydantic import SecretStr

    from clue_research.config import Secrets

SOURCE_KEY = "exa_deep"
AUTH_REF = "CLUE_EXA_API_KEY"


class ExaDeepConfig(BaseModel):
    """Config-driven model/endpoint/retrieval selection for Exa Deep (conventions §2 policy-as-data;
    M0.4). Injected at the api root; swapping Exa for another grounded-synthesis provider is a
    config/registry change. Kept local to ``resolvers/exa`` (not ``config/schema.py``, which M10
    extends) so M11 stays self-contained. Concrete retrieval-depth/budget bands are D7 calibration
    (Doc C §8) — the defaults are the proposed bands, never hardcoded in the resolver."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoint: str = "https://api.exa.ai/search"
    search_type: str = "neural"  # Exa search mode (neural | keyword | auto)
    model: str | None = (
        None  # optional for the research/answer variant; omitted from a plain search
    )
    num_results: int = Field(default=8, ge=1)  # retrieval depth
    highlights_per_result: int = Field(default=2, ge=1)
    highlight_sentences: int = Field(default=3, ge=1)
    timeout_s: float = Field(default=DEFAULT_TIMEOUT_S * 3, gt=0)  # synthesis is slower than tier-1
    retries: int = Field(default=DEFAULT_RETRIES, ge=0)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    # Fallback per-call cost when Exa reports none on a response; the realized cost (when present)
    # always wins. ``None`` defers to the seed manifest's cost (the registration default).
    default_cost_cents: CostCents | None = None


DEFAULT_EXA_CONFIG = ExaDeepConfig()


def build_exa_request(
    account: AccountEntity,
    field: FieldDef,
    token: SecretStr | None,
    *,
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
) -> HttpRequest:
    """Shape the Exa search-with-highlights call for one ``(account, field)`` (pure; unit-tested).

    The documented assumed contract (finalized against recorded fixtures when live creds land): POST
    the entity-bound query to Exa with ``contents.highlights`` on so each result carries grounded
    passages. The API key is sent as the ``x-api-key`` header; a public/no-auth call omits it.
    """
    body: dict[str, Any] = {
        "query": entity_query(account, field),
        "type": config.search_type,
        "numResults": config.num_results,
        "contents": {
            "highlights": {
                "numSentences": config.highlight_sentences,
                "highlightsPerUrl": config.highlights_per_result,
                "query": field_intent(field),
            },
            "text": True,
        },
    }
    if config.model is not None:
        body["model"] = config.model
    headers = {"content-type": "application/json"}
    if token is not None:
        headers["x-api-key"] = token.get_secret_value()
    return HttpRequest(url=config.endpoint, method="POST", headers=headers, json_body=body)


def normalize_exa_response(
    payload: Mapping[str, Any],
    field: FieldDef,
    *,
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
) -> SynthesisResult:
    """Map an Exa search response to a grounded :class:`SynthesisResult` (pure; unit-tested).

    Each retrieved result's **highlighted passage** becomes one
    :class:`~clue_research.resolvers.grounded.SynthesizedField`: the passage is the grounded value
    *and* its evidence span, cited by the result url, with the result's full ``text`` as the
    ``retrieved_text`` the substrate grounds + target-locks against (falling back to the passage
    itself when no page text is returned). A result with no url or no highlight yields nothing (no
    grounding ⇒ no value). Relevance scores are clamped to ``[0,1]`` and filtered by
    ``min_confidence``.
    """
    fields: list[SynthesizedField] = []
    for result in as_list(payload.get("results")):
        if not isinstance(result, Mapping):
            continue
        url = result.get("url")
        if not isinstance(url, str) or not url.strip():
            continue  # a citation is mandatory — no url ⇒ ungroundable, dropped
        page_text = result.get("text")
        page_text = page_text if isinstance(page_text, str) else ""
        highlights = as_list(result.get("highlights"))
        scores = as_list(result.get("highlightScores"))
        result_score = result.get("score")
        for i, passage in enumerate(highlights):
            if not isinstance(passage, str) or not passage.strip():
                continue  # no passage ⇒ no grounded span ⇒ no value
            raw_score = scores[i] if i < len(scores) else result_score
            confidence = coerce_confidence(raw_score, 0.0)
            if confidence < config.min_confidence:
                continue
            # Grounded-only with teeth: prefer the full page ``text`` as the retrieved source
            # (richer context for the substrate's grounding + target-lock checks). When ``text`` IS
            # present but does NOT contain the highlight, that is a grounding mismatch (a provider
            # bug or a tampered/injected response) — drop the record rather than mask it by falling
            # back to the passage. Only a genuinely highlight-only response (no ``text``) uses it.
            if passage in page_text:
                retrieved_text = page_text
            elif page_text:
                continue  # highlight absent from a present page text → ungrounded → dropped
            else:
                retrieved_text = passage  # highlight-only response (no page text returned)
            fields.append(
                SynthesizedField(
                    field_key=field.field_key,
                    value=passage,
                    source_url=url,
                    evidence_span=passage,
                    retrieved_text=retrieved_text,
                    confidence=confidence,
                )
            )
    return SynthesisResult(fields=tuple(fields), cost_cents=cost_cents_from_cost_dollars(payload))


def make_backend(
    *,
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
    http: HttpFetcher = get_json,
    secrets: Secrets | None = None,
) -> HttpSynthesisBackend:
    """The default Exa :class:`~clue_research.resolvers.grounded.SynthesisBackend` over the shared
    generic HTTP transport — the provider's config closed over its two pure pieces. Tests inject a
    backend double instead (the hermetic-CI rule); the live ``http`` is the un-covered boundary."""
    return HttpSynthesisBackend(
        source_key=SOURCE_KEY,
        auth_ref=AUTH_REF,
        build_request=lambda account, field, token: build_exa_request(
            account, field, token, config=config
        ),
        normalize=lambda payload, field: normalize_exa_response(payload, field, config=config),
        http=http,
        timeout=config.timeout_s,
        retries=config.retries,
        secrets=secrets,
    )


def register_exa_deep_resolver(
    *,
    accounts: AccountLookup | None = None,
    backend: SynthesisBackend | None = None,
    config: ExaDeepConfig = DEFAULT_EXA_CONFIG,
    http: HttpFetcher = get_json,
    secrets: Secrets | None = None,
) -> None:
    """Bind the tier-4 Exa Deep resolver to ``exa_deep`` (the in-process waterfall dispatch).

    The M6/M8 orchestrator (api root) calls this with the live Exa-backed backend and an
    :class:`AccountLookup`; tests inject a ``backend`` double. Idempotent (last write wins). The
    per-call default cost (attributed only when the backend reports no realized cost) is taken from
    ``config.default_cost_cents`` when set, else the seed manifest — so realized cost never silently
    drifts from the registered manifest the waterfall budgets.
    """
    register_synthesis_resolver(
        SOURCE_KEY,
        backend or make_backend(config=config, http=http, secrets=secrets),
        accounts=accounts,
        default_cost_cents=config.default_cost_cents,
    )


__all__ = [
    "SOURCE_KEY",
    "AUTH_REF",
    "ExaDeepConfig",
    "DEFAULT_EXA_CONFIG",
    "build_exa_request",
    "normalize_exa_response",
    "make_backend",
    "register_exa_deep_resolver",
]
