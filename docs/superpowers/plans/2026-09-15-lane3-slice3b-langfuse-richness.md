# Lane 3 slice 3b — Langfuse richness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every kind of work the platform does appears in Langfuse as the observation type it is: non-graph model calls as `generation`/`embedding` with settled cost, every paid provider hop as a typed observation carrying dollars, credits, tokens and the ledger row id (and the ledger row carrying the Langfuse ids back), every governed tool invocation as a `tool`/`retriever` with the platform's disposition, the ARV2 research job as its own named trace with priced generations, the design leg's exit judge as an `evaluator`, and every guardrail that stopped or refused work as a `guardrail`.

**Architecture:** Plan 3a's `clue_obs.langfuse` helpers (`observation`, `guardrail`, `event`, `current_ids`, `propagate_trace`, `LangfuseRunRegistry`) and `clue_api.langfuse_callbacks.build_langfuse_callbacks` are the only surface this plan uses; every site keeps working unchanged when Langfuse is off because every helper is then a no-op. The gateway decorator, the provider caller and the tool invoker open their own observations (they own the facts the LangChain handler cannot see); the research agent and the exit judge attach the LangChain handler and name their traces.

**Tech Stack:** as plan 3a (langfuse 4.15, opentelemetry-sdk 1.42, langchain-core 1.x, pytest).

**Spec:** `docs/superpowers/specs/archive/2026-09-15-lane3-slice3-langfuse-design.md` §3.3 (research agent, exit judge), §3.4, §3.5, §3.6, §3.7. Parent: `docs/superpowers/specs/archive/2026-09-14-telemetry-and-cost-observability-design.md` §5.3.

## Global Constraints

- **Branch, commits, DB, spend, gates, shell, R11/R12, env parity:** exactly as plan 3a's Global Constraints (`docs/superpowers/plans/2026-09-15-lane3-slice3a-langfuse-foundation.md`). The migration head after 3a is the `agent_model_call_langfuse_ids` revision; confirm `uv run alembic current` prints it before any DB test. lint-imports: 27 kept / 0 broken throughout.
- **Off by default.** With Langfuse not installed every new call site is a no-op: the same rows, receipts, exceptions and return values as before. Every task's test file proves the "off" branch once.
- **One path per call.** `clue_gateway.agent_model` opens nothing; graph generations are the handler's. `TracingGateway` opens observations only for its own `complete`/`embed` (non-graph callers).
- **Payloads (R3).** Never put a request body, a response body, an API key or a URL query string into an observation. Hosts and paths, ids, labels, counts, amounts and the platform's own decision words are what an observation carries. The mask still runs over everything.
- **No network in tests.** `tests/_langfuse.py::langfuse_installed()` only.
- **Rulings already taken (2026-09-15):** governed tools whose `effect_class` is `READ` are `retriever` observations, everything else `tool` (no per-tool declaration); the research agent's ledger rows take the registry's **latest** generation ids because the graph runs one model round at a time.

## File structure

| File | Responsibility |
| --- | --- |
| `libs/clue-gateway/clue_gateway/tracing.py` | **Modify.** `generation`/`embedding` observations around the inner call. |
| `tests/gateway/test_gateway_langfuse.py` | **Create.** |
| `platform/api/clue_api/arv2/calls.py` | **Modify.** One observation per `call`, guardrails, ids on the result row's extras. |
| `tests/arv2/test_calls_langfuse.py` | **Create.** |
| `platform/toolbelt/clue_toolbelt/invoker.py` | **Modify.** `governed.<tool>@<version>` observation with the disposition. |
| `tests/toolbelt/test_invoker_langfuse.py` | **Create.** |
| `libs/clue-obs/clue_obs/langfuse.py` | **Modify.** `LangfuseRunRegistry.latest()`. |
| `platform/api/clue_api/arv2/account_research_agent.py` | **Modify.** Handler + named trace; round rows carry ids; ending event; cap guardrails. |
| `tests/arv2/test_account_research_agent_langfuse.py` | **Create.** |
| `platform/api/clue_api/agent_turn_fleet_wiring.py` | **Modify.** The exit judge as an `evaluator`. |
| `platform/api/clue_api/agent_runtime_wiring.py` | **Modify.** `TurnWorkGuard` guardrail. |
| `tests/api/test_p37_exit_judge_unit.py`, `tests/api/test_agent_runtime_langfuse.py` | **Modify.** |
| docs: the slice 3 design note, the parent design note §9, the lane index, `_memory/2026-09-15-lane3-slice3-langfuse.md`, `_memory/README.md` | **Modify/Create.** |

---

### Task 1: Non-graph model calls — `TracingGateway` opens a `generation` / `embedding`

**Files:**
- Modify: `libs/clue-gateway/clue_gateway/tracing.py`
- Create: `tests/gateway/test_gateway_langfuse.py`

**Interfaces:**
- Consumes: `clue_obs.langfuse.observation`; `Completion(model, text, usage, cost_cents, finish_reason)`, `EmbeddingResult(model, vectors, usage, cost_cents)`, `Message(role, content)`, `TokenUsage(prompt_tokens, completion_tokens, cached_prompt_tokens)`.
- Produces: nothing new for callers; `TracingGateway.complete/embed` signatures unchanged.

- [ ] **Step 1: The failing test**

`tests/gateway/test_gateway_langfuse.py`:

```python
"""Lane 3 slice 3b, Task 1: the gateway decorator reports every non-graph call to Langfuse as a
generation / embedding carrying the settled cost — and reports nothing when Langfuse is off."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from clue_config.gateway import GatewayConfig, ModelPrice
from clue_core.gateway import Message
from clue_gateway.factory import build_gateway
from tests._langfuse import finished_spans, langfuse_installed

_PROMPT = [Message(role="system", content="be brief"), Message(role="user", content="hi")]


def _priced() -> GatewayConfig:
    return GatewayConfig(
        prices={
            "anthropic/claude-3.5-sonnet": ModelPrice(
                prompt_cents_per_1k=Decimal(2), completion_cents_per_1k=Decimal(3)
            )
        }
    )


def _attrs(span: Any) -> dict[str, Any]:
    return dict(span.attributes or {})


def test_off_the_gateway_still_answers_and_emits_only_its_otel_span() -> None:
    gw = build_gateway(_priced())  # no key → stub, wrapped in TracingGateway
    out = gw.complete(model="anthropic/claude-3.5-sonnet", messages=_PROMPT)
    assert out.text


def test_complete_exports_a_generation_with_usage_and_settled_cost() -> None:
    with langfuse_installed() as (exporter, _provider):
        gw = build_gateway(_priced())
        out = gw.complete(model="anthropic/claude-3.5-sonnet", messages=_PROMPT)
        spans = finished_spans(exporter)
    generation = next(s for s in spans if s.name == "gateway.completion")
    attrs = _attrs(generation)
    assert attrs["langfuse.observation.type"] == "generation"
    assert attrs["langfuse.observation.model.name"] == out.model
    usage = json.loads(attrs["langfuse.observation.usage_details"])
    assert usage == {
        "input": out.usage.prompt_tokens,
        "output": out.usage.completion_tokens,
        "cache_read_input": out.usage.cached_prompt_tokens,
    }
    cost = json.loads(attrs["langfuse.observation.cost_details"])
    assert cost == {"total": float(out.cost_cents / Decimal(100))}
    payload = json.loads(attrs["langfuse.observation.input"])
    assert payload == [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]
    output = json.loads(attrs["langfuse.observation.output"])
    assert output["text"] == out.text
    assert attrs["langfuse.observation.metadata.requested_model"] == "anthropic/claude-3.5-sonnet"


def test_embed_exports_an_embedding_with_counts_never_the_texts() -> None:
    with langfuse_installed() as (exporter, _provider):
        gw = build_gateway(GatewayConfig())
        gw.embed(model="text-embed", inputs=["a private sentence", "another"])
        spans = finished_spans(exporter)
    embedding = next(s for s in spans if s.name == "gateway.embedding")
    attrs = _attrs(embedding)
    assert attrs["langfuse.observation.type"] == "embedding"
    assert json.loads(attrs["langfuse.observation.input"]) == {"inputs": 2, "characters": 25}
    assert "private" not in json.dumps(attrs)
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/gateway/test_gateway_langfuse.py -q` → the two installed tests FAIL (`StopIteration`: no such span).

- [ ] **Step 3: Implement**

In `tracing.py` add `from clue_obs.langfuse import observation` and:

```python
def _messages_payload(messages: list[Message]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


def _usage_details(usage: TokenUsage) -> dict[str, int]:
    return {
        "input": usage.prompt_tokens,
        "output": usage.completion_tokens,
        "cache_read_input": usage.cached_prompt_tokens,
    }


def _cost_details(cost_cents: Decimal) -> dict[str, float]:
    return {"total": float(cost_cents / Decimal(100))}
```

`complete` becomes:

```python
    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        with (
            traced_step(SPAN_LLM_GATEWAY_CALL, **{ATTR_MODEL: model}) as span,
            observation(
                "gateway.completion",
                as_type="generation",
                model=model,
                input=_messages_payload(messages),
                metadata={"requested_model": model},
            ) as current,
        ):
            started = time.perf_counter()
            completion = self._inner.complete(model=model, messages=messages, **opts)
            duration_ms = (time.perf_counter() - started) * 1000.0
            record_model_call(...)  # unchanged
            current.update(
                model=completion.model,
                output={"text": completion.text, "finish_reason": completion.finish_reason},
                usage_details=_usage_details(completion.usage),
                cost_details=_cost_details(completion.cost_cents),
                metadata={"duration_ms": round(duration_ms, 3)},
            )
            return completion
```

`embed` the same way with `"gateway.embedding"`, `as_type="embedding"`, `input={"inputs": len(inputs), "characters": sum(len(text) for text in inputs)}`, and on return `output={"vectors": len(result.vectors)}`, the usage and cost details, `model=result.model`. (The `role` attribute stays on the OTel span as today; `record_model_call` is untouched.) If `Message.role` is an enum, use `str(message.role.value)`; check `clue_core.gateway.Role`.

- [ ] **Step 4: Run to see it pass**

Run: `uv run pytest tests/gateway/test_gateway_langfuse.py tests/gateway/test_gateway.py -q` → PASS.

- [ ] **Step 5: Gates and commit**

ruff; mypy (4 baseline); lint-imports (27/0).

```bash
git add libs/clue-gateway/clue_gateway/tracing.py tests/gateway/test_gateway_langfuse.py
git commit -m "feat(gateway): the tracing decorator reports non-graph completions and embeddings to Langfuse with usage and settled cost (lane 3 slice 3b)"
```

---

### Task 2: Provider calls — one typed observation per `ProviderCaller.call`, guardrails, ids on the ledger row

**Files:**
- Modify: `platform/api/clue_api/arv2/calls.py` (`call` ~255–400, `_settle` ~561–640)
- Create: `tests/arv2/test_calls_langfuse.py`

**Interfaces:**
- Consumes: `observation`, `guardrail`, `ObservationLike`, `NullObservation` from `clue_obs.langfuse`; `CallSpec`, `CostReading`, `CallCost`, `ProviderHalted`, `ProviderTransportError`, `LedgerRow.extras`.
- Produces: result rows' `extras` gain `langfuse_trace_id` / `langfuse_observation_id` (strings) when Langfuse is on; `_settle(..., current: ObservationLike | None = None)`.

- [ ] **Step 1: The failing test**

`tests/arv2/test_calls_langfuse.py` (reuse the doubles from `tests/arv2/test_calls.py` by importing `FakeClock`, `_request`, `_spec`, `_caller` from it — they are module-level there; if the leading-underscore names cannot be imported cleanly, copy the three helpers verbatim into this file):

```python
"""Lane 3 slice 3b, Task 2: every provider call is one typed Langfuse observation carrying the
settled money and the ledger row id; the row carries the Langfuse ids back; a halt and a ceiling
are guardrails. Off: the rows are byte-for-byte what they were."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from clue_api.arv2.calls import Ceilings, CostReading, SpendEstimate
from clue_api.arv2.errors import ProviderHalted, ProviderTransportError
from clue_api.arv2.transport import HttpResponse, TransportFailure
from tests._langfuse import finished_spans, langfuse_installed
from tests.arv2.test_calls import _caller, _spec

_OK = HttpResponse(200, {"Content-Type": "application/json"}, b'{"ok":true}')


def _attrs(span: Any) -> dict[str, Any]:
    return dict(span.attributes or {})


def _reader(_response: HttpResponse) -> CostReading:
    return CostReading(
        cost_usd=Decimal("0.02"),
        provider_request_id="req-1",
        extras={"model": "x-ai/grok-4.6", "prompt_tokens": 10, "completion_tokens": 2},
    )


def test_off_the_result_row_extras_carry_no_langfuse_keys() -> None:
    caller, _t, _r, ledger, _c = _caller([_OK])
    caller.call(_spec(cost_reader=_reader))
    result = [row for row in ledger.rows if row.phase == "result"][0]
    assert "langfuse_trace_id" not in result.extras


def test_a_chat_completion_is_a_generation_with_cost_usage_and_the_row_id() -> None:
    with langfuse_installed() as (exporter, _provider):
        caller, _t, _r, ledger, _c = _caller([_OK])
        outcome = caller.call(
            _spec(provider="openrouter", operation="chat/completions", cost_reader=_reader)
        )
        spans = finished_spans(exporter)
    span = next(s for s in spans if s.name == "openrouter.chat/completions")
    attrs = _attrs(span)
    assert attrs["langfuse.observation.type"] == "generation"
    assert attrs["langfuse.observation.model.name"] == "x-ai/grok-4.6"
    assert json.loads(attrs["langfuse.observation.cost_details"]) == {"total": 0.02}
    assert json.loads(attrs["langfuse.observation.usage_details"]) == {"input": 10, "output": 2}
    assert attrs["langfuse.observation.metadata.ledger_row_id"] == outcome.ledger_row_id
    assert attrs["langfuse.observation.metadata.cost_source"] == "metered"
    payload = json.loads(attrs["langfuse.observation.input"])
    assert payload["host"] == "provider.test" and payload["path"] == "/v1/thing"
    assert "body" not in payload and "query" not in payload
    output = json.loads(attrs["langfuse.observation.output"])
    assert output["status"] == 200 and output["outcome"] == "ok" and output["attempts"] == 1
    result = [row for row in ledger.rows if row.phase == "result"][0]
    assert result.extras["langfuse_trace_id"] == format(span.context.trace_id, "032x")
    assert result.extras["langfuse_observation_id"] == format(span.context.span_id, "016x")
    estimate = [row for row in ledger.rows if row.phase == "estimate"][0]
    assert "langfuse_trace_id" not in estimate.extras


def test_a_free_public_fetch_is_a_tool_observation() -> None:
    with langfuse_installed() as (exporter, _provider):
        caller, _t, _r, _l, _c = _caller([_OK])
        caller.call(_spec(provider="youtube", operation="watch", estimate=SpendEstimate()))
        spans = finished_spans(exporter)
    attrs = _attrs(next(s for s in spans if s.name == "youtube.watch"))
    assert attrs["langfuse.observation.type"] == "tool"
    assert attrs["langfuse.observation.metadata.cost_source"] == "free"
    assert "langfuse.observation.cost_details" in attrs  # the estimate (zero) still settles


def test_a_halt_is_an_error_and_the_next_call_is_a_latch_guardrail() -> None:
    refused = HttpResponse(402, {}, b'{"error":"out of credit"}')
    with langfuse_installed() as (exporter, _provider):
        caller, _t, _r, _l, _c = _caller([refused])
        spec = _spec(halt_rule=lambda response: "out_of_credit" if response.status == 402 else None)
        with pytest.raises(ProviderHalted):
            caller.call(spec)
        with pytest.raises(ProviderHalted):
            caller.call(spec)
        spans = finished_spans(exporter)
    by_name = {s.name: _attrs(s) for s in spans}
    assert by_name["prov.v1/thing"]["langfuse.observation.level"] == "ERROR"
    assert by_name["prov.v1/thing"]["langfuse.observation.status_message"] == "out_of_credit"
    latch = by_name["provider.halt_latch"]
    assert latch["langfuse.observation.type"] == "guardrail"
    assert "latched:out_of_credit" in latch["langfuse.observation.status_message"]


def test_transport_exhaustion_is_an_error_observation() -> None:
    with langfuse_installed() as (exporter, _provider):
        caller, _t, _r, _l, _c = _caller([TransportFailure("boom")] * 4)
        with pytest.raises(ProviderTransportError):
            caller.call(_spec(max_attempts=2))
        spans = finished_spans(exporter)
    attrs = _attrs(next(s for s in spans if s.name == "prov.v1/thing"))
    assert attrs["langfuse.observation.level"] == "ERROR"
    assert attrs["langfuse.observation.status_message"] == "transport_error"


def test_an_over_ceiling_estimate_records_a_ceiling_guardrail() -> None:
    with langfuse_installed() as (exporter, _provider):
        caller, _t, _r, _l, _c = _caller([_OK], ceilings=Ceilings(usd=Decimal("0.005")))
        caller.call(_spec())  # the estimate is 0.01 > 0.005: flagged, never stopped
        spans = finished_spans(exporter)
    ceiling = next(s for s in spans if s.name == "provider.ceiling")
    assert _attrs(ceiling)["langfuse.observation.type"] == "guardrail"
```

(Check `TransportFailure`'s constructor in `tests/arv2/test_calls.py`'s transport-error test and match it.)

- [ ] **Step 2: Run to see it fail** → FAIL (no spans / no extras).

- [ ] **Step 3: Implement**

In `calls.py` add `from urllib.parse import urlsplit` and `from clue_obs.langfuse import ObservationLike, ObservationType, guardrail, observation`, plus helpers near the top of the internals:

```python
def _observation_type(operation: str) -> ObservationType:
    """What kind of work a provider operation is, for the tree: a model completion, an embedding,
    or a fetch/tool hop (the default — an ATS board, a watch page, a media upload leg)."""
    lowered = operation.lower()
    if lowered.endswith("chat/completions") or lowered == "agent_completion":
        return "generation"
    if "embed" in lowered:
        return "embedding"
    return "tool"


def _observation_input(spec: CallSpec, *, over_ceiling: bool) -> dict[str, object]:
    parts = urlsplit(spec.request.url)
    return {
        "method": spec.request.method,
        "host": parts.netloc,
        "path": parts.path,
        "label": spec.label,
        "estimate": {
            "usd": str(spec.estimate.usd),
            "credits": str(spec.estimate.credits),
            "media_seconds": spec.estimate.media_seconds,
        },
        "over_ceiling_estimate": over_ceiling,
    }


def _usage_details(cost: CostReading, *, credits: Decimal, media_seconds: int) -> dict[str, int]:
    details: dict[str, int] = {}
    for source_key, target_key in (
        ("prompt_tokens", "input"),
        ("completion_tokens", "output"),
        ("cached_prompt_tokens", "cache_read_input"),
    ):
        value = cost.extras.get(source_key)
        if isinstance(value, int) and value > 0:
            details[target_key] = value
    if not details:
        if credits > 0:
            details["credits"] = int(credits)
        if media_seconds > 0:
            details["media_seconds"] = media_seconds
    return details


def _langfuse_extras(current: ObservationLike | None) -> dict[str, object]:
    if current is None or current.trace_id is None:
        return {}
    extras: dict[str, object] = {"langfuse_trace_id": current.trace_id}
    if current.id is not None:
        extras["langfuse_observation_id"] = current.id
    return extras
```

`call`:

- the latched branch, before `raise`:

```python
            guardrail(
                "provider.halt_latch",
                reason=f"{spec.provider}: latched:{latched_reason}",
                metadata={"provider": spec.provider, "operation": spec.operation, "label": spec.label},
            )
```

- after `over_ceiling = self._exceeds_ceilings(spec.estimate)`, wrap the rest of the method in

```python
        with observation(
            f"{spec.provider}.{spec.operation}",
            as_type=_observation_type(spec.operation),
            input=_observation_input(spec, over_ceiling=over_ceiling),
            metadata={
                "call_id": call_id,
                "provider": spec.provider,
                "operation": spec.operation,
                "label": spec.label,
            },
        ) as current:
            if over_ceiling:
                guardrail(
                    "provider.ceiling",
                    reason=f"{spec.provider}.{spec.operation}: the estimate exceeds a ceiling",
                    metadata={"call_id": call_id, "phase": "estimate"},
                )
            ...  # the existing body, indented one level
```

- the transport-error branch, before `raise ProviderTransportError(...)`:

```python
                    current.update(
                        level="ERROR",
                        status_message="transport_error",
                        output={"outcome": "transport_error", "attempts": attempts, "latency_ms": latency_ms},
                    )
```

- every `self._settle(...)` call inside `call` passes `current=current`.

`_settle` gains `current: ObservationLike | None = None` and:

- after `over_ceiling = self._exceeds_ceilings(...)`:

```python
        if over_ceiling:
            guardrail(
                "provider.ceiling",
                reason=f"{spec.provider}.{spec.operation}: the settled cost exceeds a ceiling",
                metadata={"call_id": call_id, "phase": "result"},
            )
```

- the `_record` call's extras become `extras={**cost.extras, "cost_source": source, **_langfuse_extras(current)}`;
- after `row_id = self._record(...)`:

```python
        if current is not None:
            model = cost.extras.get("model")
            current.update(
                output={
                    "status": status,
                    "outcome": outcome,
                    "attempts": attempts,
                    "latency_ms": latency_ms,
                    "provider_request_id": cost.provider_request_id,
                    "raw_ref": raw_ref,
                },
                cost_details={"total": float(usd)},
                usage_details=_usage_details(cost, credits=credits, media_seconds=media_seconds) or None,
                metadata={
                    "ledger_row_id": row_id,
                    "cost_source": source,
                    "over_ceiling": over_ceiling,
                    "credits": str(credits),
                    "media_seconds": media_seconds,
                },
                **({"model": model} if isinstance(model, str) and model else {}),
                **(
                    {"level": "ERROR", "status_message": error_code or outcome}
                    if outcome != "ok"
                    else {}
                ),
            )
```

The `NullObservation.update` accepts anything, so the off path is unchanged. Nothing else in `_settle`/`_record` moves.

- [ ] **Step 4: Run to see it pass**

Run: `uv run pytest tests/arv2/test_calls_langfuse.py tests/arv2/test_calls.py -q` → PASS (the existing suite proves the rows are unchanged when off).

- [ ] **Step 5: Gates and commit**

ruff; mypy (4 baseline); lint-imports (27/0).

```bash
git add platform/api/clue_api/arv2/calls.py tests/arv2/test_calls_langfuse.py
git commit -m "feat(arv2): every provider call is a typed Langfuse observation with settled money and the ledger row id; halts and ceilings are guardrails; rows carry the Langfuse ids (lane 3 slice 3b)"
```

---

### Task 3: Governed tools — the invoker's `tool` / `retriever` observation with the disposition

**Files:**
- Modify: `platform/toolbelt/clue_toolbelt/invoker.py`
- Create: `tests/toolbelt/test_invoker_langfuse.py`

**Interfaces:**
- Consumes: `observation` from `clue_obs.langfuse`; `ToolEffectClass`, `JournalDisposition`, `PreconditionFailed`, `ToolAwaitingInput`, `_error_code`.
- Produces: nothing new for callers.

- [ ] **Step 1: The failing test**

`tests/toolbelt/test_invoker_langfuse.py` (offline: fakes for the snapshotter and the journal; the runner and registry are real):

```python
"""Lane 3 slice 3b, Task 3: every governed invocation is a tool/retriever observation carrying
the platform's disposition — completed, replayed, blocked, failed."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import pytest

from clue_core import ExecutionAttemptId, ExecutionNodeId, new_execution_id, new_operation_id
from clue_toolbelt import PreconditionFailed, PreconditionFailure, ToolContext, ToolRegistry, ToolResult
from clue_toolbelt.invoker import (
    JournalDisposition,
    JournalStart,
    ParameterSnapshot,
    ToolInvoker,
)
from tests._langfuse import finished_spans, langfuse_installed
from tests.db.conftest import run_async
from tests.toolbelt.conftest import EchoTool, InMemoryStore


class _Snapshotter:
    async def snapshot(self, *, descriptor: Any, inputs: Any, context: Any) -> ParameterSnapshot:
        del descriptor, inputs, context
        return _snapshot()


def _snapshot() -> ParameterSnapshot:
    return ParameterSnapshot(artifact_key="ws-1/snapshot", content_sha256="0" * 64, display_params={})


class _Journal:
    def __init__(self, *, replay: ToolResult | None = None, blocked: Sequence[str] = ()) -> None:
        self._replay = replay
        self._blocked = tuple(blocked)
        self.events: list[str] = []

    async def begin(self, *, descriptor: Any, context: Any, snapshot: Any) -> JournalStart:
        del descriptor, context, snapshot
        if self._replay is not None:
            return JournalStart(
                execution_id=new_execution_id(),
                node_id=ExecutionNodeId(uuid4()),
                attempt_id=None,
                disposition=JournalDisposition.COMPLETED,
                result=self._replay,
            )
        if self._blocked:
            return JournalStart(
                execution_id=new_execution_id(),
                node_id=ExecutionNodeId(uuid4()),
                attempt_id=None,
                disposition=JournalDisposition.BLOCKED,
                blocked_reason_codes=self._blocked,
            )
        return JournalStart(
            execution_id=new_execution_id(),
            node_id=ExecutionNodeId(uuid4()),
            attempt_id=ExecutionAttemptId(uuid4()),
            disposition=JournalDisposition.STARTED,
        )

    async def steering_snapshot(self, **kwargs: Any) -> None:
        del kwargs

    async def blocked(self, **kwargs: Any) -> None:
        self.events.append("blocked")

    async def awaiting_input(self, **kwargs: Any) -> None:
        self.events.append("awaiting_input")

    async def failed(self, **kwargs: Any) -> None:
        self.events.append("failed")

    async def completed(self, *, start: Any, context: Any, result: ToolResult) -> ToolResult:
        del start, context
        self.events.append("completed")
        return result


class _NullConnFactory:
    def __call__(self) -> Any:
        raise AssertionError("no connection is opened in these tests")


def _invoker(tool: EchoTool, journal: _Journal) -> ToolInvoker:
    registry = ToolRegistry()
    registry.register(tool, make_default=True)
    return ToolInvoker(
        registry=registry,
        snapshotter=_Snapshotter(),
        journal=journal,
        idempotency_store=InMemoryStore(),
        idempotency_ttl_s=60.0,
    )


def _ctx() -> ToolContext:
    return ToolContext(
        workspace_id="ws-1",
        actor="agent",
        conn_factory=_NullConnFactory(),  # type: ignore[arg-type]
        operation_id=new_operation_id(),
    )


def _attrs(span: Any) -> dict[str, Any]:
    return dict(span.attributes or {})


def _governed(spans: Any) -> dict[str, Any]:
    return _attrs(next(s for s in spans if s.name == "governed.echo@1"))


def test_off_the_invoker_behaves_as_before() -> None:
    journal = _Journal()
    result = run_async(_invoker(EchoTool(), journal).invoke("echo", {"value": 7}, _ctx()))
    assert result.references == {"echoed": 7} and journal.events == ["completed"]


def test_a_completed_invocation_is_a_tool_observation_with_its_references() -> None:
    with langfuse_installed() as (exporter, _provider):
        run_async(_invoker(EchoTool(), _Journal()).invoke("echo", {"value": 7}, _ctx()))
        attrs = _governed(finished_spans(exporter))
    assert attrs["langfuse.observation.type"] == "tool"  # EchoTool's effect class is not READ
    assert attrs["langfuse.observation.metadata.disposition"] == "completed"
    assert json.loads(attrs["langfuse.observation.input"])["inputs"] == {"value": 7, "note": None}
    assert json.loads(attrs["langfuse.observation.output"])["references"] == {"echoed": 7}
    assert attrs["langfuse.observation.metadata.effect_class"] == "write"


def test_a_replay_is_marked_replayed() -> None:
    replay = ToolResult(tool="echo", version="1", references={"echoed": 1})
    with langfuse_installed() as (exporter, _provider):
        result = run_async(_invoker(EchoTool(), _Journal(replay=replay)).invoke("echo", {"value": 1}, _ctx()))
        attrs = _governed(finished_spans(exporter))
    assert result.replayed is True
    assert attrs["langfuse.observation.metadata.disposition"] == "replayed"


def test_a_durable_block_is_a_warning_naming_the_reason_codes() -> None:
    with langfuse_installed() as (exporter, _provider):
        with pytest.raises(PreconditionFailed):
            run_async(_invoker(EchoTool(), _Journal(blocked=("approval_required",))).invoke("echo", {"value": 1}, _ctx()))
        attrs = _governed(finished_spans(exporter))
    assert attrs["langfuse.observation.level"] == "WARNING"
    assert attrs["langfuse.observation.status_message"] == "approval_required"
    assert attrs["langfuse.observation.metadata.disposition"] == "blocked"


def test_a_precondition_refusal_inside_the_tool_is_a_warning() -> None:
    tool = EchoTool(fail=[PreconditionFailure(reason_code="no_active_icp", message="nope")])
    with langfuse_installed() as (exporter, _provider):
        with pytest.raises(PreconditionFailed):
            run_async(_invoker(tool, _Journal()).invoke("echo", {"value": 1}, _ctx()))
        attrs = _governed(finished_spans(exporter))
    assert attrs["langfuse.observation.level"] == "WARNING"
    assert attrs["langfuse.observation.status_message"] == "no_active_icp"


def test_a_failure_is_an_error_with_the_stable_code() -> None:
    with langfuse_installed() as (exporter, _provider):
        with pytest.raises(RuntimeError):
            run_async(_invoker(EchoTool(raise_on_invoke=True), _Journal()).invoke("echo", {"value": 1}, _ctx()))
        attrs = _governed(finished_spans(exporter))
    assert attrs["langfuse.observation.level"] == "ERROR"
    assert attrs["langfuse.observation.status_message"] == "runtime_error"
    assert attrs["langfuse.observation.metadata.disposition"] == "failed"
```

Verified 2026-09-15: `ParameterSnapshot(artifact_key: str, content_sha256: str, display_params: dict[str, object])` — `_snapshot()` returns `ParameterSnapshot(artifact_key="ws-1/snapshot", content_sha256="0" * 64, display_params={})`; `EchoTool.effect_class` is `WRITE`; `ExecutionNodeId`/`ExecutionAttemptId` are UUID NewTypes.

- [ ] **Step 2: Run to see it fail** → the "off" test passes; the rest FAIL (`StopIteration`).

- [ ] **Step 3: Implement**

In `invoker.py` add `from clue_obs.langfuse import ObservationLike, observation`. Rename the current body of `invoke` into `async def _invoke_observed(self, tool, descriptor, inputs, name, body, context, *, idempotency_key, current: ObservationLike) -> ToolResult` and make `invoke`:

```python
    async def invoke(self, name, body, context, *, version=None, idempotency_key=None) -> ToolResult:
        tool = self._registry.get(name, version)
        descriptor = tool.descriptor
        inputs = tool.input_model.model_validate(body)
        # Lane 3 slice 3: the platform's side of a governed call — what the LangChain handler's
        # own tool observation cannot see: the disposition (completed / replayed / blocked /
        # awaiting input / failed) and the durable references. READ tools are retrievers.
        with observation(
            f"governed.{descriptor.name}@{descriptor.version}",
            as_type="retriever" if descriptor.effect_class is ToolEffectClass.READ else "tool",
            input={
                "operation_id": str(context.operation_id),
                "actor": context.actor,
                "workspace_id": context.workspace_id,
                "inputs": inputs.model_dump(mode="json"),
            },
            metadata={
                "tool": descriptor.name,
                "version": descriptor.version,
                "effect_class": descriptor.effect_class.value,
            },
        ) as current:
            return await self._invoke_observed(
                tool, descriptor, inputs, name, body, context,
                idempotency_key=idempotency_key, current=current,
            )
```

(keep the original signature's annotations). Inside `_invoke_observed`:

- the COMPLETED replay return: before returning, `current.update(output={"replayed": True, "references": start.result.references}, metadata={"disposition": "replayed"})`.
- the BLOCKED refusal: before `raise PreconditionFailed(...)`, `current.update(level="WARNING", status_message=", ".join(start.blocked_reason_codes), metadata={"disposition": "blocked"})`.
- `except PreconditionFailed as exc:` → after `await self._journal.blocked(...)`: `current.update(level="WARNING", status_message=", ".join(exc.reason_codes), metadata={"disposition": "blocked"})`.
- `except ToolAwaitingInput as exc:` → `current.update(status_message=exc.reason_code, metadata={"disposition": "awaiting_input"})`.
- `except BaseException as exc:` → `current.update(level="ERROR", status_message=_error_code(exc), metadata={"disposition": "failed"})` (but not for `asyncio.CancelledError`, which keeps its own branch and records `metadata={"disposition": "cancelled"}` only).
- after `completed = await self._journal.completed(...)`: `current.update(output={"references": completed.references, "meta": completed.meta, "replayed": completed.replayed}, metadata={"disposition": "completed"})`.

- [ ] **Step 4: Run to see it pass**

Run: `uv run pytest tests/toolbelt/test_invoker_langfuse.py tests/toolbelt -q` → PASS. Then, on the lane DB: `uv run pytest tests/execution/test_journal.py -q` → PASS (the real journal path, Langfuse off).

- [ ] **Step 5: Gates and commit**

ruff; mypy (4 baseline); lint-imports (27/0 — `clue_toolbelt` already depends on `clue_obs`).

```bash
git add platform/toolbelt/clue_toolbelt/invoker.py tests/toolbelt/test_invoker_langfuse.py
git commit -m "feat(toolbelt): every governed invocation is a Langfuse tool/retriever observation carrying the platform's disposition and references (lane 3 slice 3b)"
```

---

### Task 4: The ARV2 research agent — its own named trace, priced rounds with ids, ending events, cap guardrails

**Files:**
- Modify: `libs/clue-obs/clue_obs/langfuse.py` (`LangfuseRunRegistry.latest`)
- Modify: `platform/api/clue_api/arv2/account_research_agent.py`
- Create: `tests/arv2/test_account_research_agent_langfuse.py`

**Interfaces:**
- Consumes: `build_langfuse_callbacks`, `propagate_trace`, `event`, `guardrail`, `LangfuseRunRegistry`.
- Produces: `LangfuseRunRegistry.latest() -> LangfuseIds | None` (the most recently remembered entry, not popped); `_ModelUsageRecorder(runtime, *, attempt, langfuse_ids: LangfuseRunRegistry | None = None)`; round rows' `extras` gain `langfuse_trace_id` / `langfuse_observation_id` when on.

- [ ] **Step 1: `latest()`**

In `clue_obs/langfuse.py`'s `LangfuseRunRegistry` add:

```python
    def latest(self) -> LangfuseIds | None:
        """The most recently remembered ids — for a caller that runs one model call at a time and
        has no run id of its own (the ARV2 round recorder)."""
        return next(reversed(self._ids.values()), None)
```

and in `tests/test_obs_langfuse.py::test_the_run_registry_remembers_and_pops_by_run_id` assert `registry.latest()` equals the remembered entry before the pop and is `None` after (the dict is insertion-ordered; `pop` removes it).

- [ ] **Step 2: The failing agent test**

`tests/arv2/test_account_research_agent_langfuse.py` — reuse the doubles from `tests/arv2/test_account_research_agent.py` (`_runtime`, `_ScriptedModel`, `_counting_tool`, `_finalizing_tool`, `_drive`, `_call`, `SCOPE`; import them, or copy verbatim if the underscore names do not import cleanly):

```python
"""Lane 3 slice 3b, Task 4: an ARV2 research job is one named Langfuse trace; each model round
row carries its generation's ids; the ending is an event and a cap is a guardrail."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage

from clue_gateway.metadata import ANSWERING_MODEL_KEY, COST_CENTS_KEY, COST_SOURCE_KEY
from tests._langfuse import finished_spans, langfuse_installed
from tests.arv2.test_account_research_agent import (
    SCOPE,
    _call,
    _counting_tool,
    _drive,
    _finalizing_tool,
    _run,
    _runtime,
    _ScriptedModel,
)


def _attrs(span: Any) -> dict[str, Any]:
    return dict(span.attributes or {})


def _priced(message: AIMessage) -> AIMessage:
    message.response_metadata = {
        **message.response_metadata,
        "model_name": "x-ai/grok-4.6",
        ANSWERING_MODEL_KEY: "x-ai/grok-4.6",
        COST_CENTS_KEY: "2.5",
        COST_SOURCE_KEY: "metered",
    }
    return message


def test_a_finalized_job_is_a_named_trace_with_priced_rounds_and_an_ending_event() -> None:
    runtime = _runtime()

    def respond(messages: Any) -> AIMessage:
        if any(getattr(m, "name", None) == "finalize_research" for m in messages):
            return _priced(AIMessage(content="done"))
        return _priced(AIMessage(content="", tool_calls=[_call("finalize_research", 1)]))

    with langfuse_installed() as (exporter, _provider):
        outcome = _run(_drive(_ScriptedModel(respond), [_finalizing_tool(runtime)], runtime))
        spans = finished_spans(exporter)
    assert outcome.reason == "finalized"
    generations = [s for s in spans if _attrs(s).get("langfuse.observation.type") == "generation"]
    assert len(generations) == outcome.model_rounds
    first = _attrs(generations[0])
    assert first["langfuse.trace.name"] == "arv2.account_research"
    assert first["session.id"] == str(SCOPE.run_id)
    assert first["user.id"] == SCOPE.workspace_id
    assert first["langfuse.trace.metadata.job_id"] == str(SCOPE.job_id)
    assert json.loads(first["langfuse.observation.cost_details"]) == {"total": 0.025}
    rows = [row for row in runtime.model_ledger.drain() if row.phase == "result"]
    assert len(rows) == outcome.model_rounds
    exported = {format(s.context.span_id, "016x") for s in generations}
    for row in rows:
        assert row.extras["langfuse_trace_id"] == format(generations[0].context.trace_id, "032x")
        assert row.extras["langfuse_observation_id"] in exported
    ending = _attrs(next(s for s in spans if s.name == "arv2.agent.ending"))
    assert ending["langfuse.observation.type"] == "event"
    assert json.loads(ending["langfuse.observation.output"])["reason"] == "finalized"


def test_a_round_cap_is_a_guardrail() -> None:
    runtime = _runtime()

    def respond(messages: Any) -> AIMessage:
        return _priced(AIMessage(content="", tool_calls=[_call("read_account_state", 1)]))

    with langfuse_installed() as (exporter, _provider):
        outcome = _run(_drive(_ScriptedModel(respond), [_counting_tool(runtime)], runtime, max_model_rounds=2))
        spans = finished_spans(exporter)
    assert outcome.reason == "round_cap"
    cap = _attrs(next(s for s in spans if s.name == "arv2.round_cap"))
    assert cap["langfuse.observation.type"] == "guardrail"
    assert cap["langfuse.observation.level"] == "WARNING"


def test_off_the_rows_carry_no_langfuse_keys() -> None:
    runtime = _runtime()

    def respond(messages: Any) -> AIMessage:
        return _priced(AIMessage(content="", tool_calls=[_call("finalize_research", 1)]))

    _run(_drive(_ScriptedModel(respond), [_finalizing_tool(runtime)], runtime))
    rows = [row for row in runtime.model_ledger.drain() if row.phase == "result"]
    assert rows and all("langfuse_trace_id" not in row.extras for row in rows)
```

`BufferedLedger` (`platform/api/clue_api/arv2/provider_ledger.py`) exposes its rows through `drain()` (verified 2026-09-15); each test drains once.

- [ ] **Step 3: Run to see it fail** → FAIL.

- [ ] **Step 4: Implement**

In `account_research_agent.py`:

- imports: `from clue_api.langfuse_callbacks import build_langfuse_callbacks`; `from clue_obs.langfuse import LangfuseRunRegistry, event, guardrail, propagate_trace`.
- `_ModelUsageRecorder.__init__(self, runtime, *, attempt, langfuse_ids: LangfuseRunRegistry | None = None)` stores `self._langfuse_ids`. In `_record`, when `message is not None` and `self._langfuse_ids is not None`:

```python
        ids = self._langfuse_ids.latest() if self._langfuse_ids is not None else None
        if ids is not None:
            extras["langfuse_trace_id"] = ids.trace_id
            if ids.observation_id is not None:
                extras["langfuse_observation_id"] = ids.observation_id
```

(`extras` is built as a `dict[str, object]` already; add after it is built, before the `LedgerRow`).

- `_RoundShapeMiddleware.awrap_tool_call`: beside the existing `log.info("arv2.account_round_shape_refused", ...)` add `guardrail("arv2.too_many_parallel_calls", reason=detail, metadata={"tool": ..., "position": position, "limit": self._limit})`.
- `run_account_agent`: build the callbacks and the recorder first, thread the handler through the config, name the trace, and report the ending:

```python
    langfuse = build_langfuse_callbacks()
    rounds = _ModelUsageRecorder(
        runtime, attempt=attempt, langfuse_ids=langfuse.registry if langfuse is not None else None
    )
    agent = create_agent(...)  # unchanged
    opening = ...
    config = RunnableConfig(
        recursion_limit=max_model_rounds * (max_tool_calls_per_round + 2) + 4,
        callbacks=[langfuse.handler] if langfuse is not None else [],
    )
    scope = runtime.scope
    with propagate_trace(
        trace_name="arv2.account_research",
        session_id=str(scope.run_id),
        user_id=scope.workspace_id,
        metadata={
            "project_id": scope.project_id,
            "project_run_id": scope.project_run_id,
            "job_id": scope.job_id,
            "account_id": scope.account_id,
            "contact_id": scope.contact_id,
            "subject_kind": scope.subject_kind,
            "attempt": attempt,
        },
        tags=("arv2", scope.subject_kind),
    ):
        outcome = await _drive_graph(agent, opening, config, runtime=runtime, rounds=rounds, max_runtime_s=max_runtime_s)
    _report_ending(outcome)
    return outcome
```

where `_drive_graph` is the existing `invoke = asyncio.create_task(...)` block through the final `return AgentOutcome(...)` lines, moved verbatim into `async def _drive_graph(agent, opening, config, *, runtime, rounds, max_runtime_s) -> AgentOutcome`, and:

```python
def _report_ending(outcome: AgentOutcome) -> None:
    """The job's ending as one event (and a guardrail when a cap, not the agent, ended it)."""
    event(
        "arv2.agent.ending",
        output={
            "reason": outcome.reason,
            "model_rounds": outcome.model_rounds,
            "tool_calls": outcome.tool_calls,
            "error": outcome.error,
            "model_spend_usd": str(outcome.model_spend.usd),
        },
        level="ERROR" if outcome.reason == "model_error" else "DEFAULT",
        status_message=outcome.error if outcome.reason == "model_error" else None,
    )
    if outcome.reason in ("round_cap", "runtime_cap"):
        guardrail(
            f"arv2.{outcome.reason}",
            reason=f"the job ended on its {outcome.reason.replace('_', ' ')} after {outcome.model_rounds} rounds",
            metadata={"model_rounds": outcome.model_rounds, "tool_calls": outcome.tool_calls},
        )
```

`propagate_trace` wraps the task creation, so the task inherits the context.

- [ ] **Step 5: Run to see it pass**

Run: `uv run pytest tests/arv2/test_account_research_agent_langfuse.py tests/arv2/test_account_research_agent.py tests/test_obs_langfuse.py -q` → PASS.

- [ ] **Step 6: Gates and commit**

ruff; mypy (4 baseline — note the pre-existing `account_research_claims.py:1387` and `account_research_driver.py:181-182` errors are in neighbouring files, not this one); lint-imports (27/0).

```bash
git add libs/clue-obs/clue_obs/langfuse.py tests/test_obs_langfuse.py platform/api/clue_api/arv2/account_research_agent.py tests/arv2/test_account_research_agent_langfuse.py
git commit -m "feat(arv2): the research job is its own named Langfuse trace — priced rounds with generation ids on the ledger rows, an ending event, cap guardrails (lane 3 slice 3b)"
```

---

### Task 5: The exit judge as an `evaluator`; the turn work guard as a `guardrail`

**Files:**
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py` (`build_design_leg_exit_judge` ~lines 1630–1670)
- Modify: `platform/api/clue_api/agent_runtime_wiring.py` (`TurnWorkGuard` ~line 710)
- Modify: `tests/api/test_p37_exit_judge_unit.py`, `tests/api/test_agent_runtime_langfuse.py`

**Interfaces:**
- Consumes: `observation`, `propagate_trace`, `guardrail`, `build_langfuse_callbacks`.

- [ ] **Step 1: The failing tests**

In `tests/api/test_p37_exit_judge_unit.py` change `_FakeModel.ainvoke` to `async def ainvoke(self, prompt: Any, **kwargs: Any) -> Any:` (recording `kwargs` on `self.configs: list[Any]`) and append:

```python
def test_with_langfuse_the_judge_is_an_evaluator_holding_its_generation() -> None:
    from tests._langfuse import finished_spans, langfuse_installed

    with langfuse_installed() as (exporter, _provider):
        judge, model = _judge_with(AIMessage(content=_VERDICT))
        verdict = _run(judge)
        spans = finished_spans(exporter)
    assert verdict is not None
    evaluator = next(s for s in spans if s.name == "design-leg.exit_judge")
    attrs = dict(evaluator.attributes or {})
    assert attrs["langfuse.observation.type"] == "evaluator"
    assert attrs["langfuse.trace.name"] == "design-leg.exit_judge"
    assert "finish" in attrs["langfuse.observation.output"]
    # The handler was attached to the direct model call so its generation nests here.
    assert model.configs and "callbacks" in (model.configs[0].get("config") or {})


def test_without_langfuse_no_config_is_passed_to_the_model() -> None:
    judge, model = _judge_with(AIMessage(content=_VERDICT))
    assert _run(judge) is not None
    assert model.configs == [{}]
```

In `tests/api/test_agent_runtime_langfuse.py` append:

```python
def test_a_stopped_turn_records_a_work_guard_guardrail() -> None:
    import asyncio

    async def stop() -> None:
        raise asyncio.CancelledError("chat turn stopped before admitting more work")

    with langfuse_installed() as (exporter, _provider):
        guard = TurnWorkGuard(stop)
        try:
            run_async(guard.on_chat_model_start())
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("the guard must re-raise")
        spans = finished_spans(exporter)
    attrs = dict(spans[0].attributes or {})
    assert spans[0].name == "turn.work_guard"
    assert attrs["langfuse.observation.type"] == "guardrail"
    assert "CancelledError" in attrs["langfuse.observation.status_message"]
```

- [ ] **Step 2: Run to see them fail** → FAIL.

- [ ] **Step 3: Implement**

`agent_turn_fleet_wiring.py`, inside `judge(...)`'s `try:` after `prompt = render_exit_judgment_prompt(...)`:

```python
            langfuse = build_langfuse_callbacks()
            call_kwargs: dict[str, Any] = (
                {"config": {"callbacks": [langfuse.handler]}} if langfuse is not None else {}
            )
            with (
                propagate_trace(trace_name="design-leg.exit_judge", tags=("design",)),
                observation(
                    "design-leg.exit_judge",
                    as_type="evaluator",
                    input={"message": message, "history_turns": len(history)},
                ) as current,
            ):
                completion = await model_holder[0].ainvoke(prompt, **call_kwargs)  # type: ignore[attr-defined]
                judgment = parse_exit_judgment(_completion_text(completion))
                current.update(
                    output=None if judgment is None else _judgment_payload(judgment),
                    level="DEFAULT" if judgment is not None else "WARNING",
                    status_message=None if judgment is not None else "unparseable verdict",
                )
            return judgment
```

with `_judgment_payload(judgment)` returning `judgment.model_dump(mode="json")` (`clue_design.exit_judgment.ExitJudgment` is a frozen pydantic model with `action` and `reason`; `clue_design` under `subsystems/design/` is read-only here). Imports: `from clue_api.langfuse_callbacks import build_langfuse_callbacks`, `from clue_obs.langfuse import observation, propagate_trace`.

`agent_runtime_wiring.TurnWorkGuard`:

```python
class TurnWorkGuard(AsyncCallbackHandler):
    """Admission check shared by model and tool boundaries for one chat turn."""

    raise_error = True

    def __init__(self, check: Callable[[], Awaitable[None]]) -> None:
        self.check = check

    async def on_chat_model_start(self, *args: Any, **kwargs: Any) -> None:
        await self._admit()

    async def on_llm_end(self, *args: Any, **kwargs: Any) -> None:
        await self._admit()

    async def _admit(self) -> None:
        try:
            await self.check()
        except BaseException as exc:
            # Lane 3 slice 3: a refused admission is a guardrail in the tree, then the same raise.
            guardrail("turn.work_guard", reason=f"{type(exc).__name__}: {exc}"[:200])
            raise
```

(import `guardrail` from `clue_obs.langfuse` beside the Task 6 imports of plan 3a).

- [ ] **Step 4: Run to see them pass**

Run: `env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/api/test_p37_exit_judge_unit.py tests/api/test_agent_runtime_langfuse.py tests/api/test_agent_runtime_wiring_cost_stamp.py -q` → PASS.

- [ ] **Step 5: Gates and commit**

ruff; mypy (4 baseline); lint-imports (27/0).

```bash
git add platform/api/clue_api/agent_turn_fleet_wiring.py platform/api/clue_api/agent_runtime_wiring.py tests/api/test_p37_exit_judge_unit.py tests/api/test_agent_runtime_langfuse.py
git commit -m "feat(api): the design leg's exit judge is a Langfuse evaluator holding its generation; a refused turn admission is a guardrail (lane 3 slice 3b)"
```

---

### Task 6: Docs and the memory note

**Files:**
- Modify: `docs/superpowers/specs/archive/2026-09-15-lane3-slice3-langfuse-design.md` (§3.6 first sentence; status line)
- Modify: `docs/superpowers/specs/archive/2026-09-14-telemetry-and-cost-observability-design.md` (§9 item 3)
- Modify: `docs/superpowers/plans/2026-09-13-lane-plan-index.md` (row 3b: nothing to change unless the plan file name differs)
- Create: `_memory/2026-09-15-lane3-slice3-langfuse.md`; Modify: `_memory/README.md` (one index line under "Topic notes", newest first)

- [ ] **Step 1: The slice 3 design note**

§3.6's first sentence becomes: ``ToolInvoker.invoke` opens `observation(f"governed.{name}@{version}", as_type=<"retriever" when descriptor.effect_class is READ, else "tool">, ...)`` (the ruling: no per-tool declaration). Change the status line to `**Status:** approved in chat 2026-09-15 (decisions D1–D4 below); 3a and 3b executed 2026-09-15.`

- [ ] **Step 2: The parent design note §9 item 3**

Replace the `**3b — next:** ...` sentence with `**3b — DONE 2026-09-15:** the research agent's named trace with priced rounds and ids on its ledger rows, the exit judge as an evaluator, gateway generations/embeddings, provider-caller observations with settled money and guardrails, governed-tool/retriever observations, the work-guard guardrail.` and append one line: `Live proof owed (founder-triggered, after the keys are set and the stack restarted): one chat turn and one research job opened in Langfuse; the receipt's `langfuse_trace_id` and a ledger row's `extras_json.langfuse_trace_id` open those traces.`

- [ ] **Step 3: The memory note**

`_memory/2026-09-15-lane3-slice3-langfuse.md` — in the style of `_memory/2026-09-15-lane3-slice2-roots.md`: what shipped (3a and 3b, commit subjects from `git log --oneline` since `cd962c712`), the four decisions D1–D4, the rulings taken during execution (copy each `Ruling:` line from both SDD ledgers `.superpowers/sdd/2026-09-15-lane3-slice3a-langfuse-foundation/progress.md` and `.superpowers/sdd/2026-09-15-lane3-slice3b-langfuse-richness/progress.md`), the env names and where credentials go (`CLUE_LANGFUSE_PUBLIC_KEY` / `CLUE_LANGFUSE_SECRET_KEY` in the lane's `.env`; `CLUE_LANGFUSE_ENABLED=true`; `make langfuse-check`; restart both API twins and the workers), the facts worth keeping (the handler's `_runs` map; start events precede the call; one chunk per stream carries the model keys; `Langfuse(tracer_provider=)` attaches to our provider so no OTLP endpoint is needed; health-check spans dropped), the verification run per task, and the owed live proof. No secrets.

Add to `_memory/README.md` under "Topic notes", first line: `- `2026-09-15-lane3-slice3-langfuse.md` — Lane 3 slice 3 (3a + 3b) on `lane3/sice1b`: Langfuse attached to the slice 2 provider; the LangChain handler + run registry in the turn and research-agent tuples; gateway/provider/tool observations with settled cost; receipt ids (migration) and ledger-row ids; redaction; `make langfuse-check`; the streamed `answering_model` fix. **Live proof owed — founder-triggered.**`

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/archive/2026-09-15-lane3-slice3-langfuse-design.md docs/superpowers/specs/archive/2026-09-14-telemetry-and-cost-observability-design.md docs/superpowers/plans/2026-09-13-lane-plan-index.md _memory/2026-09-15-lane3-slice3-langfuse.md _memory/README.md
git commit -m "docs(memory): lane 3 slice 3 — Langfuse on the roots, the agent tree, provider and tool observations, receipt and ledger ids; live proof owed"
```

---

## Self-review (done while writing)

- **Spec coverage:** §3.3 research agent + exit judge → Tasks 4, 5; §3.4 → Task 1; §3.5 → Task 2; §3.6 → Task 3; §3.7 (work guard, cap guardrails, ending event, pre-spend refusals as BLOCKED) → Tasks 3, 4, 5; §5 tests → each task's file; docs/memory → Task 6.
- **Type consistency:** `observation(name, *, as_type, input, metadata, ...)` yields `ObservationLike` with `update(**fields)`, `.id`, `.trace_id`; `guardrail(name, *, reason, metadata)`; `event(name, *, output, level, status_message)`; `LangfuseRunRegistry.latest()`; `build_langfuse_callbacks() -> LangfuseCallbacks | None` — used identically across tasks and matching plan 3a.
- **Placeholders:** none; the invoker test's snapshot literal and the ledger accessor were verified against the code on 2026-09-15.
