"""Standard span/log attribute contract (M0.5).

The cross-cutting attributes every pipeline step tags its span with, drawn from `core/` (M0.2)
so observability, the cost surface, and the learning loop all key on the same dimensions
(Doc C §6). Defining them once here is what keeps dashboards and the learning loop stable across
a resolver/judge swap (the span *shape* doesn't change).

Redaction is integrated from the M0.4 helper (`config`): a secret must never reach a span or log.
Crucially, the *known-safe* standard attributes (e.g. ``entity_id``/``run_id``, which are UUIDs that
would otherwise trip the value-shape "opaque token" heuristic) are passed through by name and only
type-coerced — they are not value-shape-redacted. Arbitrary extra attributes *are* value-shape
redacted, so a secret accidentally placed under a benign key is still masked.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import Enum
from typing import TypedDict
from uuid import UUID

from clue_config import redact_mapping
from clue_core import EntityType, ResearchMode, SourceTier

# --- canonical attribute keys (the observability contract) ------------------
ATTR_ENTITY_ID = "entity_id"
ATTR_ENTITY_TYPE = "entity_type"
ATTR_FIELD_KEY = "field_key"
ATTR_SOURCE_TIER = "source_tier"
ATTR_SOURCE_KEY = "source_key"  # M4 resolve spans tag this
ATTR_RESEARCH_MODE = "research_mode"
ATTR_RUN_ID = "run_id"
ATTR_COST_CENTS = "cost_cents"
ATTR_WORKSPACE_ID = "workspace_id"
ATTR_ICP_ID = "icp_id"
ATTR_PROJECT_RUN_ID = "project_run_id"
# LLM gateway (M0.4) — the llm.gateway_call span tags these. `model` is the id that answered;
# token counts feed the cost surface (Doc C §6). None are secrets (a model id is public).
ATTR_MODEL = "model"
# P3.2 (PD-part3 delta 6): the agent-role attribution dimension on llm.gateway_call spans
# — the ONE per-role usage authority once the design trio runs on the governed gateway.
ATTR_AGENT_ROLE = "agent_role"
ATTR_PROMPT_TOKENS = "prompt_tokens"
ATTR_COMPLETION_TOKENS = "completion_tokens"
ATTR_TOTAL_TOKENS = "total_tokens"
# Modality adapters (M4.3) — the fetch/adapt/extract + pipeline spans tag these. All known-safe:
# a latency/cost number, a bool cache-hit, a modality / gate-decision enum string, a claim count.
ATTR_LATENCY_MS = "latency_ms"
ATTR_COST_ESTIMATE_CENTS = "cost_estimate_cents"  # the pre-spend gate estimate (D7)
ATTR_CACHE_HIT = "cache_hit"
ATTR_GATE_DECISION = "gate_decision"  # "run" | "skip"
ATTR_MODALITY = "modality"  # text | video | audio | pdf | structured
ATTR_N_CLAIMS = "n_claims"
# Source Planner (M4.6) — the source.plan span tags this: how many sources the plan selected (a
# count, never a secret).
ATTR_N_SOURCES = "n_sources"

# Run context (lane 3 slice 2) — the ids and enums structlog binds at the roots, copied onto every
# span by ``RunContextSpanProcessor``. Identifiers and closed vocabularies only, never text.
ATTR_REQUEST_ID = "request_id"
ATTR_PROJECT_ID = "project_id"
ATTR_THREAD_ID = "thread_id"
ATTR_TURN_ID = "turn_id"
ATTR_JOB_ID = "job_id"
ATTR_ACCOUNT_ID = "account_id"
ATTR_ACTOR = "actor"
ATTR_PROFILE_VERSION = "profile_version"
ATTR_TASK_ID = "task_id"
ATTR_WORK_ID = "work_id"
ATTR_FLEET_KIND = "fleet_kind"
ATTR_TASK_ATTEMPT = "task_attempt"
ATTR_WORKER_ID = "worker_id"

# Known-safe dimensions: identifiers/enums/numbers, never secrets. Passed through (type-coerced)
# without value-shape redaction so a UUID id is not mistaken for an opaque-token credential.
STANDARD_ATTRIBUTES: frozenset[str] = frozenset(
    {
        ATTR_ENTITY_ID,
        ATTR_ENTITY_TYPE,
        ATTR_FIELD_KEY,
        ATTR_SOURCE_TIER,
        ATTR_SOURCE_KEY,
        ATTR_RESEARCH_MODE,
        ATTR_RUN_ID,
        ATTR_COST_CENTS,
        ATTR_WORKSPACE_ID,
        ATTR_ICP_ID,
        ATTR_PROJECT_RUN_ID,
        ATTR_MODEL,
        ATTR_AGENT_ROLE,
        ATTR_PROMPT_TOKENS,
        ATTR_COMPLETION_TOKENS,
        ATTR_TOTAL_TOKENS,
        ATTR_LATENCY_MS,
        ATTR_COST_ESTIMATE_CENTS,
        ATTR_CACHE_HIT,
        ATTR_GATE_DECISION,
        ATTR_MODALITY,
        ATTR_N_CLAIMS,
        ATTR_N_SOURCES,
        ATTR_REQUEST_ID,
        ATTR_PROJECT_ID,
        ATTR_THREAD_ID,
        ATTR_TURN_ID,
        ATTR_JOB_ID,
        ATTR_ACCOUNT_ID,
        ATTR_ACTOR,
        ATTR_PROFILE_VERSION,
        ATTR_TASK_ID,
        ATTR_WORK_ID,
        ATTR_FLEET_KIND,
        ATTR_TASK_ATTEMPT,
        ATTR_WORKER_ID,
    }
)

# An OTel-acceptable attribute value.
OtelValue = str | bool | int | float


class SpanAttributes(TypedDict, total=False):
    """Typed, optional view of the standard attribute set (callers may pass any subset)."""

    entity_id: UUID | str
    entity_type: EntityType | str
    field_key: str
    source_tier: SourceTier
    source_key: str
    research_mode: ResearchMode | str
    run_id: UUID | str
    cost_cents: Decimal | float
    workspace_id: UUID | str
    icp_id: UUID | str
    project_run_id: UUID | str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    cost_estimate_cents: Decimal | float
    cache_hit: bool
    gate_decision: str
    modality: str
    n_claims: int
    n_sources: int
    request_id: str
    project_id: str
    thread_id: str
    turn_id: UUID | str
    job_id: UUID | str
    account_id: UUID | str
    actor: str
    profile_version: str
    task_id: UUID | str
    work_id: str
    fleet_kind: str
    task_attempt: int
    worker_id: str


def to_otel_value(value: object) -> OtelValue | None:
    """Coerce a Python value to an OTel-acceptable attribute value (or ``None`` to omit)."""
    if value is None:
        return None
    if isinstance(value, bool):  # bool before int (bool is an int subclass)
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, Enum):  # StrEnum -> its string value
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, UUID | Decimal):
        return str(value)
    return str(value)


def safe_attributes(attrs: Mapping[str, object]) -> dict[str, OtelValue]:
    """Redact + type-coerce a raw attribute mapping into OTel-safe attributes.

    Known-safe standard keys are coerced natively; everything else (secret-named keys and arbitrary
    extras) goes through the M0.4 ``redact_mapping`` (force-masks secret-named keys, value-shape
    masks the rest). ``None`` values are dropped.
    """
    out: dict[str, OtelValue] = {}
    needs_redaction: dict[str, object] = {}
    for key, value in attrs.items():
        if value is None:
            continue
        # STANDARD_ATTRIBUTES is a curated, code-defined allowlist of known-safe dimensions — it is
        # the trust boundary, so its keys are coerced natively without name/value redaction. (This
        # lets count attributes like ``*_tokens`` through, which the secret-name heuristic would
        # otherwise mask on the ``token`` substring.) Everything else is name+value redacted.
        if key in STANDARD_ATTRIBUTES:
            coerced = to_otel_value(value)
            if coerced is not None:
                out[key] = coerced
        else:
            needs_redaction[key] = value
    out.update(redact_mapping(needs_redaction))
    return out
