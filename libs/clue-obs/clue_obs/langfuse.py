"""Langfuse at the process roots (lane 3 slice 3, R4): the agent-tree viewer.

One client per process, attached to the tracer provider slice 2 built (D1), exporting only the
agent harness: the agent tree the LangChain handler reports and the platform-side observations
opened here. The FastAPI, httpx and ``fleet.task`` spans on the same provider stay out of Langfuse
(2026-10-03 spec, R1). Every payload passes :func:`make_mask`
before export (R3: the secret-key rule and the blob rule, plus truncation — never the claim-value
rule: this is the surface for debugging exactly those values). Nothing here does anything until
:func:`install_langfuse` was given both keys; every helper is a no-op otherwise, so an
unconfigured process behaves as it did after slice 2.

This module (and ``clue_api.langfuse_callbacks``, the LangChain adapter) are the only two that
import the SDK — an import-linter contract keeps it that way.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter

from clue_obs.redact import is_secret_key, mask_blob, redact_value
from clue_obs.truncate import truncate_str

__all__ = [
    "DEFAULT_MASK_LIMIT",
    "ENTITIES_METADATA_KEY",
    "ENTITY_TAG_PREFIX",
    "LangfuseIds",
    "LangfuseRunRegistry",
    "Level",
    "NullObservation",
    "ObservationLike",
    "ObservationType",
    "auth_check",
    "current_ids",
    "event",
    "flush_langfuse",
    "guardrail",
    "install_langfuse",
    "langfuse_is_installed",
    "make_mask",
    "observation",
    "propagate_trace",
    "shutdown_langfuse",
    "tag_entities",
]

ObservationType = Literal[
    "generation",
    "embedding",
    "span",
    "agent",
    "tool",
    "chain",
    "retriever",
    "evaluator",
    "guardrail",
]
Level = Literal["DEBUG", "DEFAULT", "WARNING", "ERROR"]

#: Longest string any exported payload may carry; the turn's receipt limit is the same order.
DEFAULT_MASK_LIMIT = 8_000

# The SDK client, typed ``Any`` on purpose: the platform never depends on its exact typed
# surface, and every helper below tolerates ``None`` (not installed).
_client: Any | None = None


# --- the mask (R3) -------------------------------------------------------------------------


def _mask_value(value: Any, limit: int, key: str | None = None) -> Any:
    """The mask's recursion: the secret-key rule, the blob rule, truncation — and nothing else.

    Deliberately NOT ``clue_obs.redact.redact_value``: the log chain's claim-value rule (the
    ids-only rule for ``value_json`` / ``evidence_span`` / ``memory_body`` / ...) must never run
    here. Langfuse is the surface for debugging exactly those values, so a tool input or output
    that happens to carry a claim-shaped key is exported verbatim (R3).
    """
    if key is not None and is_secret_key(key):
        return "***"
    if isinstance(value, bytes | bytearray):
        # The one borrowed branch: ``redact_value`` with NO key produces the shared binary
        # placeholder (``<binary png ~12KB>``) and cannot reach the claim-value rule, which is
        # key-driven and never recurses into bytes. Reusing it keeps one placeholder text.
        return redact_value(value)
    if isinstance(value, str):
        return truncate_str(mask_blob(value), limit)
    if isinstance(value, Mapping):
        return {str(k): _mask_value(v, limit, key=str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_mask_value(v, limit) for v in value]
    return value


def make_mask(limit: int = DEFAULT_MASK_LIMIT) -> Callable[..., Any]:
    """The client's ``mask`` hook: secret-key rule, blob rule, truncation — in that order."""

    def mask(data: Any) -> Any:
        return _mask_value(data, limit)

    return mask


# --- install / lifecycle ---------------------------------------------------------------------


def install_langfuse(
    *,
    public_key: str | None,
    secret_key: str | None,
    host: str,
    environment: str,
    release: str | None,
    tracer_provider: TracerProvider,
    process_name: str,
    mask_limit: int = DEFAULT_MASK_LIMIT,
    span_exporter: SpanExporter | None = None,
) -> bool:
    """Build the client on ``tracer_provider``. Returns ``False`` (and builds nothing) unless both
    keys are present. ``span_exporter`` is the test seam (an in-memory exporter instead of the
    host)."""
    global _client
    if not (public_key or "").strip() or not (secret_key or "").strip():
        return False
    from langfuse import Langfuse
    from langfuse.span_filter import is_default_export_span

    _client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=host.rstrip("/"),
        environment=environment,
        release=release or None,
        tracer_provider=tracer_provider,
        mask=make_mask(mask_limit),
        # Langfuse holds the agent harness and nothing else (2026-10-03 spec, R1): the SDK's own
        # default keeps ``langfuse-sdk`` observations, ``gen_ai.*`` spans and known LLM
        # instrumentors, and drops the FastAPI, httpx and plain ``clue_research`` spans that share
        # this provider. The first production day had ~1,195 request traces in ~1,200.
        should_export_span=is_default_export_span,
        span_exporter=span_exporter,
        tracing_enabled=True,
    )
    del process_name  # named on the provider's resource by slice 2; kept for symmetry with Sentry
    return True


def langfuse_is_installed() -> bool:
    return _client is not None


def flush_langfuse() -> None:
    if _client is not None:
        _client.flush()


def shutdown_langfuse() -> None:
    global _client
    if _client is not None:
        _client.shutdown()
        _client = None


def auth_check(*, public_key: str, secret_key: str, host: str) -> bool:
    """Verify the key pair against the host without opening a trace (the check verb)."""
    from langfuse import Langfuse

    probe = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=host.rstrip("/"),
        tracing_enabled=False,
    )
    try:
        return bool(probe.auth_check())
    finally:
        probe.shutdown()


# --- observations -----------------------------------------------------------------------------


class ObservationLike(Protocol):
    @property
    def id(self) -> str | None: ...

    @property
    def trace_id(self) -> str | None: ...

    def update(self, **fields: Any) -> Any: ...


@dataclass
class NullObservation:
    """What :func:`observation` yields when Langfuse is not installed."""

    id: str | None = None
    trace_id: str | None = None

    def update(self, **fields: Any) -> NullObservation:
        del fields
        return self


@contextmanager
def observation(
    name: str, *, as_type: ObservationType = "span", **fields: Any
) -> Iterator[ObservationLike]:
    """Open one observation as the current span (a no-op handle when not installed).

    ``fields`` are the SDK's keyword fields: ``input``, ``output``, ``metadata``, ``level``,
    ``status_message``, ``model``, ``usage_details``, ``cost_details``.
    """
    if _client is None:
        yield NullObservation()
        return
    with _client.start_as_current_observation(name=name, as_type=as_type, **fields) as current:
        yield current


@dataclass(frozen=True)
class LangfuseIds:
    trace_id: str
    observation_id: str | None


def current_ids() -> LangfuseIds | None:
    """The current trace and observation ids, or ``None`` when not installed / no span."""
    if _client is None:
        return None
    trace_id = _client.get_current_trace_id()
    if not isinstance(trace_id, str) or not trace_id:
        return None
    observation_id = _client.get_current_observation_id()
    return LangfuseIds(
        trace_id=trace_id,
        observation_id=observation_id if isinstance(observation_id, str) else None,
    )


def event(
    name: str,
    *,
    level: Level = "DEFAULT",
    status_message: str | None = None,
    metadata: Mapping[str, object] | None = None,
    input: Any = None,
    output: Any = None,
) -> None:
    """A point-in-time observation under the current span."""
    if _client is None:
        return
    _client.create_event(
        name=name,
        level=level,
        status_message=status_message,
        metadata=dict(metadata) if metadata else None,
        input=input,
        output=output,
    )


def guardrail(
    name: str,
    *,
    reason: str,
    metadata: Mapping[str, object] | None = None,
    level: Level = "WARNING",
) -> None:
    """Record that a guardrail fired: a closed ``guardrail`` observation carrying the reason."""
    if _client is None:
        return
    with _client.start_as_current_observation(
        name=name,
        as_type="guardrail",
        level=level,
        status_message=reason,
        metadata=dict(metadata) if metadata else None,
    ):
        pass


def flag_trace(
    name: str,
    *,
    tags: Sequence[str],
    level: Level = "WARNING",
    status_message: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> None:
    """Tag the current trace and record one event saying why, so the trace can be filtered on
    the tag. A no-op when Langfuse is not installed."""
    if _client is None:
        return
    from langfuse import propagate_attributes

    with propagate_attributes(tags=list(tags)):
        _client.create_event(
            name=name,
            level=level,
            status_message=status_message,
            metadata=dict(metadata) if metadata else None,
        )


@contextmanager
def propagate_trace(
    *,
    trace_name: str,
    session_id: str | None = None,
    user_id: str | None = None,
    metadata: Mapping[str, object] | None = None,
    tags: Sequence[str] = (),
) -> Iterator[None]:
    """Name the trace and stamp session, user, metadata and tags on every span opened inside.

    Metadata values are stringified (the SDK takes primitives) and ``None`` values are dropped.
    """
    if _client is None:
        yield
        return
    from langfuse import propagate_attributes

    _seed_entities()
    cleaned = {k: str(v) for k, v in (metadata or {}).items() if v is not None}
    with propagate_attributes(
        trace_name=trace_name,
        session_id=session_id,
        user_id=user_id,
        metadata=cleaned or None,
        tags=list(tags) or None,
    ):
        yield


# --- entity tags (lane 3 slice 4, R5) ------------------------------------------------------

#: The trace tag naming one entity a trace carried claims about: ``entity:<id>``.
ENTITY_TAG_PREFIX = "entity:"
#: The trace metadata key holding the same ids, sorted and comma-joined (the "contains" filter).
ENTITIES_METADATA_KEY = "entities"

#: The entities tagged so far on the current trace: ``(trace_id, ids)``. Set, never reset, so it
#: outlives the ``propagate_trace`` block that opened the trace and reaches later work in the
#: same task (the research driver's committee step after the agent). A different current trace
#: starts a fresh set.
_entities: ContextVar[tuple[str, set[str]] | None] = ContextVar(
    "clue_langfuse_entities", default=None
)


def _seed_entities() -> None:
    """Plant an empty accumulator for the current trace, in the task that opens the trace.

    Called from :func:`propagate_trace`. In production the turn runner and the research job both
    open their trace under the worker's ``fleet.task`` span, so the seed lands in the PARENT task
    and every child task / ``copy_context`` thread inherits the same set object to mutate. With
    no parent span current there is nothing to key on, so the seed is skipped and the first
    :func:`tag_entities` call plants it instead.
    """
    current = current_ids()
    if current is None:
        return
    held = _entities.get()
    if held is not None and held[0] == current.trace_id:
        return
    _entities.set((current.trace_id, set()))


def tag_entities(entity_ids: Iterable[object]) -> None:
    """Tag the current trace with the entities it wrote or served.

    The whole accumulated set is re-emitted on every call (as ``entity:<id>`` tags and as the
    ``entities`` metadata list) inside the SDK's own attribute propagation, so the trace ends up
    complete whether Langfuse merges trace attributes by union or by last writer, and the outer
    trace name, session, user and tags stay on the emitted span. A no-op when Langfuse is not
    installed, when no span is current, or when nothing is left after dropping blanks.
    """
    if _client is None:
        return
    ids = {str(item).strip() for item in entity_ids if item is not None and str(item).strip()}
    if not ids:
        return
    current = current_ids()
    if current is None:
        return
    held = _entities.get()
    if held is not None and held[0] == current.trace_id:
        # Mutate the set the accumulator already holds — never rebind the ContextVar. A child
        # task or a ``copy_context`` thread sees the same tuple, so mutating its set is visible
        # to its siblings and to the parent; a ``set()`` there would be invisible outside it.
        # (``held[1] |= ids`` would rebind the tuple slot and raise — ``update`` mutates.)
        seen = held[1]
        seen.update(ids)
    else:
        seen = set(ids)
        _entities.set((current.trace_id, seen))
    ordered = sorted(seen)
    from langfuse import propagate_attributes

    with propagate_attributes(
        tags=[f"{ENTITY_TAG_PREFIX}{entity}" for entity in ordered],
        metadata={ENTITIES_METADATA_KEY: ",".join(ordered)},
    ):
        _client.create_event(name="entities.tagged", output={ENTITIES_METADATA_KEY: ordered})


# --- the run registry (LangChain run id → Langfuse ids) --------------------------------------


@dataclass
class LangfuseRunRegistry:
    """Filled by the LangChain handler at model-call start; read by the durable recorder."""

    _ids: dict[UUID, LangfuseIds] = field(default_factory=dict)

    def remember(self, run_id: UUID, ids: LangfuseIds) -> None:
        self._ids[run_id] = ids

    def get(self, run_id: UUID) -> LangfuseIds | None:
        return self._ids.get(run_id)

    def pop(self, run_id: UUID) -> LangfuseIds | None:
        return self._ids.pop(run_id, None)

    def latest(self) -> LangfuseIds | None:
        """The most recently remembered ids — for a caller that runs one model call at a time and
        has no run id of its own (the ARV2 round recorder)."""
        return next(reversed(self._ids.values()), None)
