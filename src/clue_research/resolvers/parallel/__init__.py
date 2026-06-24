"""The Parallel Task resolver — a *second*, independent tier-4 grounded-synthesis provider (M11.2).

So the subsystem is not single-vendor for its least-trusted source (substrate §4/§12), Parallel
Task (Basis) is the second tier-4 ``Resolver``, registered alongside Exa Deep behind the **same**
:class:`~clue_research.resolvers.grounded.GroundedSynthesisResolver` seam. The waterfall (M4.1) and
workers (M7.1) cannot tell the two apart — running one, the other, or both for cross-provider
convergence is a registry/config choice, not a code change (the "nothing downstream knows the
provider" invariant made concrete one more time, conventions §2).

Parallel's Task API returns, per output field, a **basis**: ``citations`` (each a URL + verbatim
``excerpts``), a ``reasoning`` rationale, and a ``confidence`` (substrate §12 "Parallel Task:
citations + reasoning + confidence"). This module owns only the two pure, provider-specific pieces
(the recorded-fixture path — finalized against live fixtures when credentials land):

* :func:`build_parallel_request` — the entity-bound (target-locked) query, built by the **shared**
  :func:`~clue_research.resolvers.grounded.entity_query` (Exa and Parallel issue the identical
  entity-bound query; only the wire envelope differs), POSTed to the Task-run endpoint with basis
  enabled. The key is sent as ``x-api-key``.
* :func:`normalize_parallel_response` — map each **cited excerpt** to one
  :class:`~clue_research.resolvers.grounded.SynthesizedField`: the excerpt *is* the grounded value
  **and** its evidence span (grounded-only by construction — a claim's value is always real,
  cited, retrieved text — exactly like an Exa highlight), with the citation URL as ``source_url``.
  Parallel's ``reasoning`` is captured separately on :attr:`SynthesisResult.reasoning` (→ the trace
  span, for audit) and is **structurally barred** from ever becoming an evidence span — only cited
  source text qualifies (substrate §1/§6; the M11.2 reasoning-vs-span rule). A basis entry whose
  only support is reasoning (no citation/excerpt) yields nothing → the field stays empty.

Everything else — the grounded-only + target-lock guards, claim construction, no-self-promotion,
empty-on-miss, the account-only personal-data firewall, the swap seam — lives **once** in
:mod:`clue_research.resolvers.grounded`, so Exa Deep and Parallel Task are interchangeable at the
call site. Parallel is reached through its **own** API key (``CLUE_PARALLEL_API_KEY``), not the
OpenRouter gateway — it is a research-product API, not an OpenAI-compatible chat endpoint
(conventions §2 carve-out). The provider SDK (none needed — the transport is the shared generic
HTTP) would live only here (import-linter Rule 4).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from clue_research.core import AccountEntity, CostCents, FieldDef
from clue_research.resolvers.base import coerce_confidence
from clue_research.resolvers.grounded import (
    HttpSynthesisBackend,
    SynthesisBackend,
    SynthesisResult,
    SynthesizedField,
    as_list,
    dollars_to_cost_cents,
    entity_query,
    field_intent,
    register_synthesis_resolver,
)
from clue_research.resolvers.http import DEFAULT_RETRIES, DEFAULT_TIMEOUT_S, get_json
from clue_research.resolvers.live import AccountLookup, HttpFetcher, HttpRequest

if TYPE_CHECKING:
    from pydantic import SecretStr

    from clue_research.config import Secrets

SOURCE_KEY = "parallel_task"
AUTH_REF = "CLUE_PARALLEL_API_KEY"

# Parallel returns a categorical confidence per basis entry (these labels) or, occasionally, a bare
# number. A label maps to a configured band; anything else is coerced numerically (or the default).
_CONFIDENCE_LABELS = frozenset({"high", "medium", "low"})


class ParallelTaskConfig(BaseModel):
    """Config-driven endpoint/processor/retrieval selection for Parallel Task (conventions §2
    policy-as-data; M0.4). Injected at the api root; swapping Parallel for another grounded
    synthesis provider is a config/registry change. Kept local to ``resolvers/parallel`` (not
    ``config/schema.py``, which M10 extends) so M11 stays self-contained. Concrete processor/budget
    bands are D7 calibration (Doc C §8) — the defaults are the proposed bands, never hardcoded
    in the resolver."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoint: str = "https://api.parallel.ai/v1/tasks/runs"
    processor: str = "base"  # Parallel "processor" quality/cost tier (base | core | pro)
    timeout_s: float = Field(default=DEFAULT_TIMEOUT_S * 3, gt=0)  # synthesis is slower than tier-1
    retries: int = Field(default=DEFAULT_RETRIES, ge=0)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    # Categorical confidence → unit interval (Parallel returns high/medium/low, or a number).
    confidence_high: float = Field(default=0.9, ge=0.0, le=1.0)
    confidence_medium: float = Field(default=0.6, ge=0.0, le=1.0)
    confidence_low: float = Field(default=0.3, ge=0.0, le=1.0)
    confidence_default: float = Field(default=0.5, ge=0.0, le=1.0)  # unknown/absent label
    # Fallback per-call cost when Parallel reports none on a response; the realized cost (when
    # present) always wins. ``None`` defers to the seed manifest's cost (the registration default).
    default_cost_cents: CostCents | None = None

    def confidence_for(self, label: str) -> float:
        """Map a categorical confidence label to its configured band (default for an unknown)."""
        return {
            "high": self.confidence_high,
            "medium": self.confidence_medium,
            "low": self.confidence_low,
        }.get(label.strip().lower(), self.confidence_default)


DEFAULT_PARALLEL_CONFIG = ParallelTaskConfig()


def build_parallel_request(
    account: AccountEntity,
    field: FieldDef,
    token: SecretStr | None,
    *,
    config: ParallelTaskConfig = DEFAULT_PARALLEL_CONFIG,
) -> HttpRequest:
    """Shape the Parallel Task-run call for one ``(account, field)`` (pure; unit-tested).

    The documented assumed contract (finalized against recorded fixtures when live creds land): POST
    the **shared** entity-bound query as the task ``input`` with basis (citations + reasoning +
    confidence) enabled, on the configured ``processor``. The API key is sent as the ``x-api-key``
    header; a public/no-auth call omits it.
    """
    body: dict[str, Any] = {
        "input": entity_query(account, field),
        "processor": config.processor,
        # Request a single text output for the target field, with basis (citations/reasoning/
        # confidence) on — the field-level grounding the resolver turns into cited claims.
        "task_spec": {"output_schema": {"type": "text", "description": field_intent(field)}},
        "enable_basis": True,
    }
    headers = {"content-type": "application/json"}
    if token is not None:
        headers["x-api-key"] = token.get_secret_value()
    return HttpRequest(url=config.endpoint, method="POST", headers=headers, json_body=body)


def _coerce_confidence(raw: Any, config: ParallelTaskConfig) -> float:
    """Parallel's per-basis confidence → the unit interval: a categorical label maps to its band; a
    number (or numeric string) is coerced/clamped via the shared ``coerce_confidence``; anything
    unparseable falls back to the configured default."""
    if isinstance(raw, str) and raw.strip().lower() in _CONFIDENCE_LABELS:
        return config.confidence_for(raw)
    return coerce_confidence(raw, config.confidence_default)


def _cost_cents(payload: Mapping[str, Any]) -> CostCents:
    """Read Parallel's realized per-call cost (assumed ``costDollars.total``, in dollars) into cents
    via the shared converter. Absent/malformed → ``0`` (the resolver attributes the seed-manifest
    default), never a guess."""
    cost = payload.get("costDollars")
    total = cost.get("total") if isinstance(cost, Mapping) else None
    return dollars_to_cost_cents(total)


def normalize_parallel_response(
    payload: Mapping[str, Any],
    field: FieldDef,
    *,
    config: ParallelTaskConfig = DEFAULT_PARALLEL_CONFIG,
) -> SynthesisResult:
    """Map a Parallel Task response to a grounded :class:`SynthesisResult` (pure; unit-tested).

    Each ``output.basis`` entry carries ``citations`` (URL + verbatim ``excerpts``), a ``reasoning``
    rationale, and a ``confidence``. Every cited excerpt becomes one
    :class:`~clue_research.resolvers.grounded.SynthesizedField` — the excerpt is the grounded value
    *and* its evidence span (grounded-only by construction), cited by the citation URL, at the
    entry's normalized confidence. The ``reasoning`` is collected onto
    :attr:`SynthesisResult.reasoning` (trace-only, never an evidence span). A citation with no URL,
    an excerpt that is empty, a basis entry with no citation/excerpt, or a sub-``min_confidence``
    entry yields no field (no grounding ⇒ no value); the reasoning is still recorded.
    """
    output = payload.get("output")
    if not isinstance(output, Mapping):
        return SynthesisResult()

    fields: list[SynthesizedField] = []
    reasoning: list[str] = []
    for entry in as_list(output.get("basis")):
        if not isinstance(entry, Mapping):
            continue
        # Reasoning → trace only, even for an entry that yields no grounded field (a reasoning-only
        # answer) — the audit trail keeps the rationale; it is NEVER used as an evidence span.
        rationale = entry.get("reasoning")
        if isinstance(rationale, str) and rationale.strip():
            reasoning.append(rationale.strip())
        confidence = _coerce_confidence(entry.get("confidence"), config)
        if confidence < config.min_confidence:
            continue
        for citation in as_list(entry.get("citations")):
            if not isinstance(citation, Mapping):
                continue
            url = citation.get("url")
            if not isinstance(url, str) or not url.strip():
                continue  # a citation without a url cannot ground a claim — dropped
            for excerpt in as_list(citation.get("excerpts")):
                if not isinstance(excerpt, str) or not excerpt.strip():
                    continue  # only a real cited passage qualifies as evidence (substrate §1/§6)
                fields.append(
                    SynthesizedField(
                        field_key=field.field_key,
                        value=excerpt,
                        source_url=url,
                        evidence_span=excerpt,
                        retrieved_text=excerpt,
                        confidence=confidence,
                    )
                )
    return SynthesisResult(
        fields=tuple(fields), cost_cents=_cost_cents(payload), reasoning=tuple(reasoning)
    )


def make_backend(
    *,
    config: ParallelTaskConfig = DEFAULT_PARALLEL_CONFIG,
    http: HttpFetcher = get_json,
    secrets: Secrets | None = None,
) -> HttpSynthesisBackend:
    """The default Parallel :class:`~clue_research.resolvers.grounded.SynthesisBackend` over the
    shared generic HTTP transport — the provider's config closed over its two pure pieces. Tests
    inject a backend double instead (the hermetic-CI rule); the live ``http`` is the un-covered
    boundary."""
    return HttpSynthesisBackend(
        source_key=SOURCE_KEY,
        auth_ref=AUTH_REF,
        build_request=lambda account, field, token: build_parallel_request(
            account, field, token, config=config
        ),
        normalize=lambda payload, field: normalize_parallel_response(payload, field, config=config),
        http=http,
        timeout=config.timeout_s,
        retries=config.retries,
        secrets=secrets,
    )


def register_parallel_task_resolver(
    *,
    accounts: AccountLookup | None = None,
    backend: SynthesisBackend | None = None,
    config: ParallelTaskConfig = DEFAULT_PARALLEL_CONFIG,
    http: HttpFetcher = get_json,
    secrets: Secrets | None = None,
) -> None:
    """Bind the tier-4 Parallel Task resolver to ``parallel_task`` (the in-process waterfall
    dispatch) — the same :class:`GroundedSynthesisResolver` seam Exa binds, a different backend.

    The M6/M8 orchestrator (api root) calls this with the live Parallel-backed backend and an
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
    "ParallelTaskConfig",
    "DEFAULT_PARALLEL_CONFIG",
    "build_parallel_request",
    "normalize_parallel_response",
    "make_backend",
    "register_parallel_task_resolver",
]
