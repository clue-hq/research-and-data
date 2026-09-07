# ARV2 Onboarding O2 — Exa Agent Surface, Request Templates and Document Mappers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the onboarding lane its provider leaf: the Exa **Agent** surface (`/agent/runs` create + poll) on R1's `ExaClient`, the four fixed request templates the plan's research calls use, and the pure mappers that turn a provider response into a `KnowledgeDocument` (front matter + markdown body) ready for the artifact store.

**Architecture:** Everything lands in `platform/api/clue_api/arv2/`, beside R1's clients, through R1's `ProviderCaller` wrapper (estimate row → raw record → retry/halt → result row) and its cost provision (`CallCost` on every return value). Three modules: `exa_client.py` grows an `agent_run` method; `onboarding_requests.py` holds the templates (schemas, queries, system prompts) as pure functions; `onboarding_documents.py` holds pure mappers. No settings, no DB, no driver — those are O1 and O3. Tests follow the R1 founder ruling: provider behaviour is proven **live** (skipping with the env-var name when the key is unset); pure parts are unit-tested; `ScriptedTransport` is used only for the client's own poll sequencing, which no live call can demonstrate on demand.

**Tech Stack:** Python 3.12, `httpx` behind `clue_api.arv2.transport.HttpxTransport`, `pyyaml` (new explicit dependency of `clue-api`), pytest, `uv`.

**Spec:** `docs/specs/ARV2-ONBOARDING-PLAN.md` §4 (all five calls), §9 O2 row; `docs/specs/ARV2-COMPANY-OVERVIEW-CONTRACT.md` (§1 surface facts, §2 request, §3 artifact); `docs/specs/ARV2-PRODUCT-CATALOG-CONTRACT.md` §3–§4 (the catalog mapping); `platform/api/clue_api/arv2/README.md` (cost provision, R2 composition constraints).

## Global Constraints

- **The wrapper is the only egress.** Every HTTP request goes through `ProviderCaller.call(CallSpec)`; no direct `httpx`; no `exa_py` (the import guard `tests/arv2/test_import_guard.py` forbids provider SDKs).
- **Every client return type carries `cost: CallCost`** (the guard's `test_every_client_return_type_carries_the_cost_of_the_request_behind_it`); a pure mapper's output carries `cost: CallCost | None` and is named in the README.
- **Raw before parse; cost from the provider's metering** (Appendix A laws 1–2) — handled by the wrapper; the client supplies a cost reader.
- **Exa Agent facts** (verified 2026-09-07): `POST /agent/runs` with `Authorization: Bearer <key>`, JSON `{query, effort, outputSchema?, systemPrompt?}`; `GET /agent/runs/{id}` until `status ∈ {completed, failed, cancelled}`; completed body carries `output.text`, `output.structured`, `output.grounding[]`, `usage{agentComputeUnits, searches}`, `costDollars{total,...}`, `stopReason`. Fixed efforts: minimal $0.012, low $0.025, medium $0.10, high $0.50, xhigh $1.00; `auto` metered to a $5 cap; `max` to $20. `outputSchema` supports full JSON Schema. The `/search` limits (depth 2, 10 properties, no citation fields) apply only to the `deep-reasoning` search call.
- **Failure law:** a run that ends `failed`/`cancelled`/timed out is returned with its status and error, never raised. A provider halt (`ProviderHalted`, money truth) propagates.
- **Sync and blocking by design** (R2 composition constraint): `agent_run` sleeps between polls; the O3 driver calls it through `asyncio.to_thread` with one `ProviderCaller` per worker task. Nothing here spawns threads.
- **Live tests spend real money.** Keep each under $0.05 (`effort="low"`); never run the `high` overview in tests.
- **Commits:** local only, never push; no AI attribution; one commit per task.

---

## File Structure

| Path | Responsibility |
|---|---|
| `platform/api/clue_api/arv2/exa_client.py` | **Modify.** Add the Agent surface: constants, `agent_run_body`, `exa_agent_cost_reader`, `ExaAgentRun`, `ExaClient.agent_run` + `_agent_call`; ctor gains `sleep`/`monotonic` injection. |
| `platform/api/clue_api/arv2/onboarding_requests.py` | **Create.** The fixed templates: overview, reviews, per-product (Agent) and persona-evidence (search) — schemas, queries, system prompts. Pure. |
| `platform/api/clue_api/arv2/onboarding_documents.py` | **Create.** `KnowledgeDocument`, `render_markdown`, heading demotion, grounding→sources, and the four mappers. Pure. |
| `platform/api/pyproject.toml` | **Modify.** Add `pyyaml>=6,<7`. |
| `platform/api/clue_api/arv2/README.md` | **Modify.** Document the Agent surface, the templates, the mappers' `cost: None`. |
| `tests/arv2/test_exa_agent.py` | **Create.** Pure parts + the poll sequence on `ScriptedTransport`. |
| `tests/arv2/test_exa_agent_live.py` | **Create.** One `low`-effort live run against the overview schema. |
| `tests/arv2/test_onboarding_requests.py` | **Create.** Schemas equal their contracts; the search schema honours the /search limits. |
| `tests/arv2/test_onboarding_documents.py` | **Create.** Mappers over the recorded Insight Health sample and small synthetic inputs. |
| `tests/arv2/fixtures/exa_agent_overview_insight_health.json` | **Create.** The 2026-09-07 sample run (mapper input only — not a provider double). |
| `tests/arv2/test_import_guard.py` | **Modify.** Add `ExaAgentRun` and `KnowledgeDocument` to the cost-carrying return types. |

---

### Task 1: The Agent surface's pure parts — body builder, cost reader, result type

**Files:**
- Modify: `platform/api/clue_api/arv2/exa_client.py` (constants block ~line 50; value types ~line 185; readers ~line 414)
- Test: `tests/arv2/test_exa_agent.py`

**Interfaces:**
- Produces: `EXA_AGENT_EFFORTS: tuple[str, ...]`, `AGENT_EFFORT_ESTIMATE_USD: Mapping[str, Decimal]`, `AGENT_TERMINAL_STATUSES: frozenset[str]`, `agent_run_body(*, query, output_schema, effort, system_prompt=None) -> dict`, `exa_agent_cost_reader(response) -> CostReading`, `ExaAgentRun` (fields listed in Step 3). Task 2 uses all of them; O3 reads `ExaAgentRun`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/arv2/test_exa_agent.py
"""The Exa Agent surface's pure parts and its poll sequence (ARV2-COMPANY-OVERVIEW-CONTRACT.md §1).

Provider behaviour stays live (test_exa_agent_live.py). What is unit-tested is what a live call
cannot show on demand: the body shape, the cost reader over the documented response, and the
client's own create → poll → terminal sequencing on the lane's one allowed double.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from pydantic import SecretStr

from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.exa_client import (
    AGENT_EFFORT_ESTIMATE_USD,
    AGENT_TERMINAL_STATUSES,
    EXA_AGENT_EFFORTS,
    ExaAgentRun,
    ExaClient,
    agent_run_body,
    exa_agent_cost_reader,
)
from clue_api.arv2.sinks import MemoryLedger, MemoryRawSink
from clue_api.arv2.transport import HttpResponse, ScriptedTransport

SCHEMA = {"type": "object", "required": ["facts"], "properties": {"facts": {"type": "object"}}}


def test_the_body_carries_exactly_what_the_agent_api_documents() -> None:
    body = agent_run_body(query="Research Insight Health", output_schema=SCHEMA, effort="high")
    assert body == {"query": "Research Insight Health", "effort": "high", "outputSchema": SCHEMA}
    with_prompt = agent_run_body(
        query="q", output_schema=SCHEMA, effort="low", system_prompt="Prefer the company's domain."
    )
    assert with_prompt["systemPrompt"] == "Prefer the company's domain."
    assert "stream" not in body and "previousRunId" not in body


def test_an_unknown_effort_is_refused_before_the_wire() -> None:
    with pytest.raises(ValueError):
        agent_run_body(query="q", output_schema=SCHEMA, effort="ultra")
    assert set(EXA_AGENT_EFFORTS) == {"minimal", "low", "medium", "high", "xhigh", "auto", "max"}
    assert AGENT_EFFORT_ESTIMATE_USD["high"] == Decimal("0.50")
    assert AGENT_EFFORT_ESTIMATE_USD["auto"] == Decimal("5")


def test_the_cost_reader_reads_the_completed_run_and_stays_silent_before_it() -> None:
    completed = HttpResponse(
        status=200,
        body=json.dumps(
            {
                "id": "agent_run_abc",
                "status": "completed",
                "costDollars": {"total": 0.5, "agentCompute": 0.2, "search": 0.3},
                "usage": {"agentComputeUnits": 2, "searches": 60},
            }
        ).encode(),
    )
    reading = exa_agent_cost_reader(completed)
    assert reading.cost_usd == Decimal("0.5")
    assert reading.provider_request_id == "agent_run_abc"
    assert reading.extras["cost_breakdown"]["search"] == 0.3
    assert reading.extras["usage"] == {"agentComputeUnits": 2, "searches": 60}

    queued = HttpResponse(status=200, body=b'{"id": "agent_run_abc", "status": "queued"}')
    silent = exa_agent_cost_reader(queued)
    assert silent.cost_usd is None and silent.provider_request_id == "agent_run_abc"
    assert exa_agent_cost_reader(HttpResponse(status=500, body=b"nope")).cost_usd is None


def test_terminal_statuses_are_the_three_the_api_documents() -> None:
    assert AGENT_TERMINAL_STATUSES == frozenset({"completed", "failed", "cancelled"})


def _caller(transport: ScriptedTransport, sleeps: list[float]) -> ProviderCaller:
    from datetime import UTC, datetime

    return ProviderCaller(
        transport=transport,
        raw_sink=MemoryRawSink(),
        ledger=MemoryLedger(),
        sleep=sleeps.append,
        now=lambda: datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
    )


def _run_json(**overrides: object) -> bytes:
    base: dict[str, object] = {"id": "agent_run_abc", "object": "agent_run", "status": "queued"}
    base.update(overrides)
    return json.dumps(base).encode()


def test_agent_run_creates_then_polls_until_terminal_and_settles_on_the_completed_body() -> None:
    transport = ScriptedTransport(
        [
            HttpResponse(status=200, body=_run_json(status="queued")),
            HttpResponse(status=200, body=_run_json(status="running")),
            HttpResponse(
                status=200,
                body=_run_json(
                    status="completed",
                    stopReason="schema_satisfied",
                    output={
                        "text": "done",
                        "structured": {"facts": {"legal_name": "Insight Health AI, Inc."}},
                        "grounding": [{"field": "structured.facts", "citations": [], "confidence": "high"}],
                    },
                    usage={"agentComputeUnits": 1, "searches": 12},
                    costDollars={"total": 0.025},
                ),
            ),
        ]
    )
    wrapper_sleeps: list[float] = []
    client_sleeps: list[float] = []
    client = ExaClient(
        _caller(transport, wrapper_sleeps),
        SecretStr("key"),
        sleep=client_sleeps.append,
        monotonic=iter(range(0, 100, 1)).__next__,
    )
    run = client.agent_run(
        query="Research Insight Health", output_schema=SCHEMA, effort="low", poll_interval_s=4.0
    )
    assert isinstance(run, ExaAgentRun)
    assert run.status == "completed" and run.stop_reason == "schema_satisfied"
    assert run.run_id == "agent_run_abc"
    assert run.structured == {"facts": {"legal_name": "Insight Health AI, Inc."}}
    assert run.output_text == "done"
    assert run.grounding[0]["field"] == "structured.facts"
    assert run.usage == {"agentComputeUnits": 1, "searches": 12}
    assert run.cost_usd == Decimal("0.025")
    assert run.polls == 2
    assert client_sleeps == [4.0, 4.0]
    assert len(run.costs) == 3 and run.cost is run.costs[-1]
    assert run.cost.cost_source == "metered"
    assert run.costs[0].cost_source == "estimate"  # the create reserved the effort price
    assert run.costs[0].cost_usd == Decimal("0.025")

    create_request = transport.requests[0]
    assert create_request.method == "POST" and create_request.url.endswith("/agent/runs")
    assert create_request.headers["Authorization"] == "Bearer key"  # HttpRequest keeps case
    assert transport.requests[1].method == "GET"
    assert transport.requests[1].url.endswith("/agent/runs/agent_run_abc")


def test_a_failed_run_is_returned_with_its_error_never_raised() -> None:
    transport = ScriptedTransport(
        [
            HttpResponse(status=200, body=_run_json(status="running")),
            HttpResponse(
                status=200,
                body=_run_json(
                    status="failed",
                    error={"code": "schema_unsatisfiable", "message": "could not satisfy schema"},
                ),
            ),
        ]
    )
    client = ExaClient(_caller(transport, []), SecretStr("key"), sleep=lambda _: None)
    run = client.agent_run(query="q", output_schema=SCHEMA, effort="low")
    assert run.status == "failed"
    assert run.error_code == "schema_unsatisfiable"
    assert run.structured is None and run.output_text is None


def test_a_run_that_outlives_the_timeout_is_returned_as_timed_out() -> None:
    transport = ScriptedTransport(
        [HttpResponse(status=200, body=_run_json(status="running")) for _ in range(4)]
    )
    clock = iter([0.0, 0.0, 100.0, 200.0, 301.0, 400.0, 500.0]).__next__
    client = ExaClient(
        _caller(transport, []), SecretStr("key"), sleep=lambda _: None, monotonic=clock
    )
    run = client.agent_run(query="q", output_schema=SCHEMA, effort="low", timeout_s=300.0)
    assert run.status == "timed_out"
    assert run.run_id == "agent_run_abc"
    assert run.error_code == "timeout"


def test_a_create_that_already_returns_a_terminal_run_never_polls() -> None:
    transport = ScriptedTransport(
        [
            HttpResponse(
                status=200,
                body=_run_json(
                    status="completed",
                    output={"text": "quick", "structured": {"facts": {}}, "grounding": []},
                    costDollars={"total": 0.012},
                ),
            )
        ]
    )
    client = ExaClient(_caller(transport, []), SecretStr("key"), sleep=lambda _: None)
    run = client.agent_run(query="q", output_schema=SCHEMA, effort="minimal")
    assert run.status == "completed" and run.polls == 0 and len(transport.requests) == 1
```

`ScriptedTransport.requests` (a list of `HttpRequest`, appended on every `send`) is the request log the last assertions read; `HttpRequest.headers` keeps the caller's key case, only `HttpResponse` lower-cases.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/arv2/test_exa_agent.py -v`
Expected: FAIL — `ImportError: cannot import name 'AGENT_EFFORT_ESTIMATE_USD'`.

- [ ] **Step 3: Add the pure parts to `exa_client.py`**

After `DEEP_REASONING_MAX_ATTEMPTS` add:

```python
#: Exa Agent (``/agent/runs``) — the async deep-research surface. Fixed efforts have a fixed
#: per-request price (Exa Agent guide, read 2026-09-07); ``auto``/``max`` are metered to a default
#: cap, which is the honest pre-spend reservation for them.
EXA_AGENT_EFFORTS: tuple[str, ...] = ("minimal", "low", "medium", "high", "xhigh", "auto", "max")
AGENT_EFFORT_ESTIMATE_USD: Mapping[str, Decimal] = {
    "minimal": Decimal("0.012"),
    "low": Decimal("0.025"),
    "medium": Decimal("0.10"),
    "high": Decimal("0.50"),
    "xhigh": Decimal("1.00"),
    "auto": Decimal("5"),
    "max": Decimal("20"),
}
AGENT_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})
#: One create or one poll is a short HTTP exchange; the run itself takes minutes and is waited
#: for by polling, so neither leg needs the deep-reasoning budget.
AGENT_LEG_TIMEOUT_S = 60.0
```

(`Mapping` is already imported from `collections.abc` in this module; confirm.)

After `ExaDeepResult` add:

```python
@dataclass(frozen=True)
class ExaAgentRun:
    """A finished (or given-up-on) Exa Agent run.

    ``status`` is Exa's terminal status — ``completed``, ``failed``, ``cancelled`` — or the
    client's own ``timed_out`` when the run outlived ``timeout_s``. Only ``completed`` carries
    ``structured``/``output_text``/``grounding``. ``costs`` is every leg's :class:`CallCost` in
    order (create, then each poll); ``cost`` is the settling leg's, which is the metered one on a
    completed run. Nothing here raises for a provider-side failure: the driver's failure law
    (ARV2-ONBOARDING-PLAN.md §3) records it on the step.
    """

    run_id: str | None
    status: str
    stop_reason: str | None
    output_text: str | None
    structured: object | None
    grounding: list[Any]
    usage: Mapping[str, Any]
    cost_usd: Decimal | None
    error_code: str | None
    error_message: str | None
    polls: int
    raw_refs: tuple[str, ...]
    ledger_row_ids: tuple[str, ...]
    costs: tuple[CallCost, ...]
    cost: CallCost


def agent_run_body(
    *,
    query: str,
    output_schema: Mapping[str, object],
    effort: str,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """Build the ``POST /agent/runs`` body. ``outputSchema`` is passed exactly as given: the
    Agent surface accepts full JSON Schema, and the shape is the caller's contract."""
    if effort not in EXA_AGENT_EFFORTS:
        raise ValueError(f"unknown Exa Agent effort {effort!r}; one of {EXA_AGENT_EFFORTS}")
    body: dict[str, Any] = {"query": query, "effort": effort, "outputSchema": dict(output_schema)}
    if system_prompt is not None:
        body["systemPrompt"] = system_prompt
    return body
```

After `exa_cost_reader` add:

```python
def exa_agent_cost_reader(response: HttpResponse) -> CostReading:
    """Read an Agent run body: ``costDollars.total`` and ``usage`` appear only on the completed
    run, so a queued/running poll yields a reading with the run id and no cost — "Exa has not
    told us yet", recorded as such, never as zero."""
    body = _body_json(response)
    costs = body.get("costDollars")
    costs = costs if isinstance(costs, dict) else {}
    usage = body.get("usage")
    run_id = body.get("id")
    extras: dict[str, object] = {}
    if costs:
        extras["cost_breakdown"] = costs
    if isinstance(usage, dict):
        extras["usage"] = usage
    return CostReading(
        cost_usd=_decimal(costs.get("total")),
        provider_request_id=run_id if isinstance(run_id, str) else None,
        extras=extras,
    )
```

`_body_json` returns `{}` for a non-JSON or non-object body (never raises), so the reader above is total.

- [ ] **Step 4: Run the pure-part tests**

Run: `uv run pytest tests/arv2/test_exa_agent.py -v -k "body or effort or cost_reader or terminal"`
Expected: those PASS; the `agent_run` tests still fail on `TypeError: __init__() got an unexpected keyword argument 'sleep'` (Task 2).

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/exa_client.py tests/arv2/test_exa_agent.py
git commit -m "feat(arv2): Exa Agent surface — effort table, agent_run_body, exa_agent_cost_reader, ExaAgentRun"
```

---

### Task 2: `ExaClient.agent_run` — create, poll, settle

**Files:**
- Modify: `platform/api/clue_api/arv2/exa_client.py` (`ExaClient.__init__` ~line 596; new methods after `deep_reasoning`)
- Test: `tests/arv2/test_exa_agent.py` (written in Task 1), `tests/arv2/test_exa_agent_live.py`

**Interfaces:**
- Produces: `ExaClient.agent_run(*, query: str, output_schema: Mapping[str, object], effort: str, system_prompt: str | None = None, label: str = "exa-agent", poll_interval_s: float = 4.0, timeout_s: float = 900.0) -> ExaAgentRun`. O3 calls it (through `asyncio.to_thread`) for overview, reviews and per-product steps.

- [ ] **Step 1: Extend the constructor**

Replace `ExaClient.__init__` with:

```python
    def __init__(
        self,
        caller: ProviderCaller,
        api_key: SecretStr,
        *,
        base_url: str = EXA_BASE_URL,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._caller = caller
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        # Injected for the poll loop only (the wrapper has its own for retry backoff): a test
        # drives the sequence without waiting, production waits for real.
        self._sleep = sleep
        self._monotonic = monotonic
```

Add `import time` and `from collections.abc import Callable` to the module imports (keep `Mapping`/`Sequence` where they are).

- [ ] **Step 2: Add `agent_run` and its leg helper after `deep_reasoning`**

```python
    def agent_run(
        self,
        *,
        query: str,
        output_schema: Mapping[str, object],
        effort: str,
        system_prompt: str | None = None,
        label: str = "exa-agent",
        poll_interval_s: float = 4.0,
        timeout_s: float = 900.0,
    ) -> ExaAgentRun:
        """One Exa Agent run: create, then poll until terminal or ``timeout_s`` of wall time.

        Blocking by design (R2 composition constraint): the driver calls this through
        ``asyncio.to_thread``. Each leg is one wrapped call with its own raw record and ledger
        row; the create leg reserves the effort's fixed price, the polls reserve nothing, and the
        completed body's ``costDollars`` settles the last row as metered.
        """
        body = agent_run_body(
            query=query, output_schema=output_schema, effort=effort, system_prompt=system_prompt
        )
        started = self._monotonic()
        legs: list[CallResult] = []
        create = self._agent_call(
            operation="agent-create",
            label=label,
            method="POST",
            path="/agent/runs",
            body=body,
            estimate=SpendEstimate(usd=AGENT_EFFORT_ESTIMATE_USD[effort]),
        )
        legs.append(create)
        run = _body_json(create.response)
        run_id = run.get("id") if isinstance(run.get("id"), str) else None
        polls = 0
        while _agent_status(run) not in AGENT_TERMINAL_STATUSES:
            if run_id is None:
                return _agent_result(run, run_id, legs, polls, status="unparseable",
                                     error_code="no_run_id",
                                     error_message="create returned no run id")
            if self._monotonic() - started > timeout_s:
                return _agent_result(run, run_id, legs, polls, status="timed_out",
                                     error_code="timeout",
                                     error_message=f"run not terminal after {timeout_s:.0f}s")
            self._sleep(poll_interval_s)
            poll = self._agent_call(
                operation="agent-poll",
                label=f"{label}-poll",
                method="GET",
                path=f"/agent/runs/{run_id}",
                body=None,
                estimate=SpendEstimate(),
            )
            legs.append(poll)
            polls += 1
            run = _body_json(poll.response)
        return _agent_result(run, run_id, legs, polls, status=_agent_status(run))

    def _agent_call(
        self,
        *,
        operation: str,
        label: str,
        method: str,
        path: str,
        body: Mapping[str, Any] | None,
        estimate: SpendEstimate,
    ) -> CallResult:
        """One Agent leg. Bearer auth is what the Agent guide documents (search uses x-api-key)."""
        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        if body is None:
            request = HttpRequest(
                method=method,
                url=f"{self._base_url}{path}",
                headers=headers,
                body=None,
                timeout_s=AGENT_LEG_TIMEOUT_S,
            )
        else:
            request = json_request(
                method, f"{self._base_url}{path}", headers=headers, json_body=dict(body),
                timeout_s=AGENT_LEG_TIMEOUT_S,
            )
        return self._caller.call(
            CallSpec(
                provider=PROVIDER,
                operation=operation,
                label=label,
                request=request,
                estimate=estimate,
                cost_reader=exa_agent_cost_reader,
                halt_rule=exa_halt_rule,
            )
        )
```

Add these module-level helpers next to `_read_output`:

```python
def _agent_status(run: Mapping[str, Any]) -> str:
    status = run.get("status")
    return status if isinstance(status, str) else "unparseable"


def _agent_result(
    run: Mapping[str, Any],
    run_id: str | None,
    legs: Sequence[CallResult],
    polls: int,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> ExaAgentRun:
    output = run.get("output")
    output = output if isinstance(output, dict) else {}
    error = run.get("error")
    error = error if isinstance(error, dict) else {}
    completed = status == "completed"
    grounding = output.get("grounding") if completed else None
    text = output.get("text") if completed else None
    stop_reason = run.get("stopReason")
    usage = run.get("usage")
    last = legs[-1]
    return ExaAgentRun(
        run_id=run_id,
        status=status,
        stop_reason=stop_reason if isinstance(stop_reason, str) else None,
        output_text=text if isinstance(text, str) else None,
        structured=output.get("structured") if completed else None,
        grounding=list(grounding) if isinstance(grounding, list) else [],
        usage=dict(usage) if isinstance(usage, dict) else {},
        cost_usd=last.cost.cost_usd,
        error_code=error_code or (error.get("code") if isinstance(error.get("code"), str) else None),
        error_message=error_message
        or (error.get("message") if isinstance(error.get("message"), str) else None),
        polls=polls,
        raw_refs=tuple(ref for leg in legs for ref in leg.raw_refs),
        ledger_row_ids=tuple(leg.ledger_row_id for leg in legs),
        costs=tuple(leg.call_cost for leg in legs),
        cost=last.call_cost,
    )
```

`HttpRequest` must be imported from `clue_api.arv2.transport` alongside `HttpResponse, json_request`.

- [ ] **Step 3: Run the offline suite**

Run: `uv run pytest tests/arv2/test_exa_agent.py tests/arv2/test_exa_client.py -v`
Expected: all PASS.

- [ ] **Step 4: Write the live test**

```python
# tests/arv2/test_exa_agent_live.py
"""The Exa Agent surface against the real API — R1's Global Constraint 3: no replay, no mocked
bodies. One ``low``-effort run (~$0.025, under two minutes) against the company-overview schema
proves create → poll → completed, the structured output, the grounding and the metered cost.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import SecretStr

from clue_api.arv2.exa_client import ExaClient
from clue_api.arv2.onboarding_requests import (
    COMPANY_OVERVIEW_SYSTEM_PROMPT,
    company_overview_output_schema,
    company_overview_query,
)
from tests.arv2.conftest import require_secret


def test_a_low_effort_agent_run_completes_with_structured_output(live_secrets, make_caller) -> None:
    key = require_secret(live_secrets, "exa_api_key")
    client = ExaClient(make_caller(), SecretStr(key))

    run = client.agent_run(
        query=company_overview_query("Insight Health (insighthealth.ai)"),
        output_schema=company_overview_output_schema(),
        effort="low",
        system_prompt=COMPANY_OVERVIEW_SYSTEM_PROMPT,
        label="exa-agent-live-overview",
        timeout_s=600.0,
    )

    assert run.status == "completed", (run.status, run.error_code, run.error_message)
    assert run.run_id and run.run_id.startswith("agent_run_")
    assert isinstance(run.structured, dict)
    assert set(run.structured) >= {"facts", "sections", "competitors", "named_customers", "not_found"}
    assert set(run.structured["sections"]) == {
        "origin_story", "business_model", "positioning", "market_position",
        "customer_segments", "leadership", "recent_context",
    }
    assert run.grounding, "a completed run carries field-level grounding"
    assert run.cost.cost_source == "metered"
    assert run.cost_usd is not None and Decimal("0.005") <= run.cost_usd <= Decimal("0.10")
    assert run.polls >= 1
```

This test depends on Task 3's `onboarding_requests` module; it is written now and run after Task 3.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/exa_client.py tests/arv2/test_exa_agent.py tests/arv2/test_exa_agent_live.py
git commit -m "feat(arv2): ExaClient.agent_run — create, poll until terminal, settle on the metered completed body; failures and timeouts returned, never raised"
```

---

### Task 3: The request templates — `onboarding_requests.py`

**Files:**
- Create: `platform/api/clue_api/arv2/onboarding_requests.py`
- Test: `tests/arv2/test_onboarding_requests.py`

**Interfaces:**
- Produces (all pure):
  - `company_overview_query(company_name: str) -> str`, `COMPANY_OVERVIEW_SYSTEM_PROMPT: str`, `company_overview_output_schema() -> dict[str, Any]`
  - `customer_reviews_query(company_name: str, domain: str) -> str`, `CUSTOMER_REVIEWS_SYSTEM_PROMPT: str`, `customer_reviews_output_schema() -> dict[str, Any]`
  - `product_research_query(*, product_name: str, company_name: str, official_url: str | None, sibling_names: Sequence[str]) -> str`, `PRODUCT_RESEARCH_SYSTEM_PROMPT: str`, `product_research_output_schema() -> dict[str, Any]`
  - `PERSONA_EVIDENCE_SYSTEM_PROMPT: str`, `persona_evidence_output_schema() -> dict[str, Any]` (a `/search` deep-reasoning schema: ≤ 10 properties, depth ≤ 2, no citation fields)
  - O3 passes the Agent ones to `ExaClient.agent_run`; O4's evidence tool passes the search one to `ExaClient.deep_reasoning`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/arv2/test_onboarding_requests.py
"""The fixed request templates equal their contracts and honour Exa's documented limits."""

from __future__ import annotations

import json
from typing import Any

from clue_api.arv2.onboarding_requests import (
    COMPANY_OVERVIEW_SYSTEM_PROMPT,
    CUSTOMER_REVIEWS_SYSTEM_PROMPT,
    PERSONA_EVIDENCE_SYSTEM_PROMPT,
    PRODUCT_RESEARCH_SYSTEM_PROMPT,
    company_overview_output_schema,
    company_overview_query,
    customer_reviews_output_schema,
    customer_reviews_query,
    persona_evidence_output_schema,
    product_research_output_schema,
    product_research_query,
)
from tests.arv2.test_exa_client import _count_properties


def _depth(schema: Any, current: int = 0) -> int:
    """Object-nesting depth: root object = 0; an object inside an array item counts one level."""
    if not isinstance(schema, dict):
        return current
    deepest = current
    for key in ("properties", "items"):
        node = schema.get(key)
        if key == "properties" and isinstance(node, dict):
            for child in node.values():
                deepest = max(deepest, _depth(child, current + 1))
        elif key == "items" and isinstance(node, dict):
            deepest = max(deepest, _depth(node, current))
    return deepest


def test_the_overview_schema_is_the_ratified_contract_verbatim() -> None:
    """ARV2-COMPANY-OVERVIEW-CONTRACT.md §2.3 — the live-validated schema, byte for byte."""
    schema = company_overview_output_schema()
    assert schema["required"] == ["facts", "sections", "competitors", "named_customers", "not_found"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]["facts"]["properties"]) == {
        "legal_name", "website", "founded_year", "headquarters", "employee_range",
        "funding_total_usd", "latest_round", "investors", "revenue_model", "pricing_posture",
        "industries_served", "geographies", "customer_count_claim", "regulatory_posture",
    }
    assert schema["properties"]["sections"]["required"] == [
        "origin_story", "business_model", "positioning", "market_position",
        "customer_segments", "leadership", "recent_context",
    ]
    assert schema["properties"]["competitors"]["maxItems"] == 12
    assert schema["properties"]["named_customers"]["maxItems"] == 30
    assert schema["properties"]["named_customers"]["items"]["properties"]["evidence_kind"]["enum"] == [
        "case_study", "logo_wall", "press", "review", "other"
    ]
    assert schema["properties"]["not_found"]["maxItems"] == 20
    json.dumps(schema)  # serialisable as-is


def test_the_overview_query_carries_the_nine_sections_and_the_company_name() -> None:
    query = company_overview_query("Insight Health (insighthealth.ai)")
    for heading in (
        "The Origin Story", "The Business Reality", "What They Actually Do",
        "The Market Position", "The Customer Reality", "The People", "The Problems",
        "The Future", "Recent Context",
    ):
        assert heading in query
    assert query.startswith("Research Insight Health (insighthealth.ai)")
    assert query.rstrip().endswith("company name is Insight Health (insighthealth.ai)")
    assert "[COMPANY NAME]" not in query


def test_the_system_prompts_state_the_non_negotiables() -> None:
    assert "Do not enumerate individual products" in COMPANY_OVERVIEW_SYSTEM_PROMPT
    assert "not_found" in COMPANY_OVERVIEW_SYSTEM_PROMPT
    assert "never" in CUSTOMER_REVIEWS_SYSTEM_PROMPT.lower() and "name" in CUSTOMER_REVIEWS_SYSTEM_PROMPT
    assert "only this product" in PRODUCT_RESEARCH_SYSTEM_PROMPT.lower()
    assert "verbatim" in PERSONA_EVIDENCE_SYSTEM_PROMPT


def test_the_reviews_and_product_schemas_bound_every_list_and_forbid_extras() -> None:
    reviews = customer_reviews_output_schema()
    assert reviews["properties"]["reviews"]["maxItems"] == 40
    item = reviews["properties"]["reviews"]["items"]
    assert item["required"] == ["platform", "quote", "sentiment", "source_url"]
    assert "reviewer_name" not in item["properties"]
    assert item["properties"]["sentiment"]["enum"] == ["positive", "mixed", "negative"]
    assert reviews["properties"]["case_studies"]["maxItems"] == 15

    product = product_research_output_schema()
    assert product["required"] == [
        "overview", "capabilities", "use_cases", "integrations", "pricing",
        "differentiators", "competitors", "customer_evidence", "not_found",
    ]
    assert product["properties"]["capabilities"]["maxItems"] == 15
    assert product["additionalProperties"] is False


def test_queries_name_their_subject_and_siblings() -> None:
    assert "insighthealth.ai" in customer_reviews_query("Insight Health", "insighthealth.ai")
    query = product_research_query(
        product_name="Aura AI Scribe",
        company_name="Insight Health",
        official_url="https://www.insighthealth.ai/ambient",
        sibling_names=["Aura Anywhere", "MagicFlow"],
    )
    assert "Aura AI Scribe" in query and "https://www.insighthealth.ai/ambient" in query
    assert "Aura Anywhere" in query and "MagicFlow" in query
    assert "not about" in query.lower()
    assert "official page" not in product_research_query(
        product_name="X", company_name="Y", official_url=None, sibling_names=[]
    ).lower()


def test_the_persona_evidence_schema_fits_the_search_limits() -> None:
    """It rides ``/search`` deep-reasoning: ≤ 10 properties, depth ≤ 2, no citation fields."""
    schema = persona_evidence_output_schema()
    assert _count_properties(schema) <= 10
    assert _depth(schema) <= 2
    assert schema["required"] == ["passages"]
    passage = schema["properties"]["passages"]["items"]
    assert passage["required"] == ["quote", "speaker_role"]
    assert not {"url", "citations", "source_url"} & set(passage["properties"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/arv2/test_onboarding_requests.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clue_api.arv2.onboarding_requests'`.

- [ ] **Step 3: Write the module**

```python
# platform/api/clue_api/arv2/onboarding_requests.py
"""The fixed request templates of the onboarding lane (ARV2-ONBOARDING-PLAN.md §4).

Behaviour lives in the system prompt, shape lives in the output schema (Exa's own rule). Every
template here is a pure function or constant: the driver (O3) and the evidence tool (O4) pass them
to :class:`~clue_api.arv2.exa_client.ExaClient` and never author a schema of their own.

Three of the four are **Agent** requests (full JSON Schema allowed). The persona-evidence one is a
``/search`` deep-reasoning request and must stay within Exa's documented limits for that surface:
nesting depth 2, ten properties, no citation fields (grounding is returned separately).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

__all__ = [
    "COMPANY_OVERVIEW_SYSTEM_PROMPT",
    "CUSTOMER_REVIEWS_SYSTEM_PROMPT",
    "PERSONA_EVIDENCE_SYSTEM_PROMPT",
    "PRODUCT_RESEARCH_SYSTEM_PROMPT",
    "company_overview_output_schema",
    "company_overview_query",
    "customer_reviews_output_schema",
    "customer_reviews_query",
    "persona_evidence_output_schema",
    "product_research_output_schema",
    "product_research_query",
]


def _nullable(kind: str, **extra: Any) -> dict[str, Any]:
    return {"type": [kind, "null"], **extra}


def _string_list(max_items: int, description: str | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "array", "maxItems": max_items, "items": {"type": "string"}}
    if description:
        node["items"]["description"] = description
    return node


# -- 4.2 company overview (ARV2-COMPANY-OVERVIEW-CONTRACT.md §2; live-validated 2026-09-07) -------

_COMPANY_OVERVIEW_QUERY = """Research {company} and create a comprehensive report covering these areas:

**==The Origin Story==**

- How did this company start? What problem were they solving?
- Who are the founders? What's their background and previous experience?
- Early funding, initial customers, and first product iterations

**==The Business Reality==**

- How does this company make money? What's their revenue model?
- Are they profitable? What's their financial trajectory?
- Who funds them? Latest valuation and investor expectations

**==What They Actually Do==**

- Current products and services – skip the marketing fluff
- How their technology works under the hood
- Key features that matter to users
- Product evolution and major pivots

**==The Market Position==**

- Who are their main competitors? How do they stack up?
- What's their competitive advantage? Is it defensible?
- Market size, share, and growth potential
- Target customers and use cases

**==The Customer Reality==**

- Who actually uses this? Customer segments and personas
- Positive reviews and success stories
- Complaints, negative feedback, and common problems
- Customer retention and satisfaction data

**==The People==**

- Current leadership team and key employees
- Company culture and employee reviews
- Team size, hiring patterns, and organizational structure

**==The Problems==**

- What criticism do they face? Industry controversies
- Failed products or initiatives
- Operational challenges and technical debt

**==The Future==**

- Product roadmap and strategic direction
- Market trends that help or hurt them
- Partnerships, acquisitions, and expansion plans
- Regulatory risks and opportunities

**==Recent Context==**

- Latest news, announcements, and developments
- Industry changes affecting the company
- Geopolitical pressures and international strategy

company name is {company}"""


def company_overview_query(company_name: str) -> str:
    """The nine-section query as run on 2026-09-07; the schema is the filter on what comes back."""
    return _COMPANY_OVERVIEW_QUERY.format(company=company_name)


COMPANY_OVERVIEW_SYSTEM_PROMPT = (
    "Prefer the company's own domain first, then press and case studies, then third-party "
    "sources. Every section states where each fact came from. Quote the company's own phrasing "
    "for its value proposition and any customer count. Do not enumerate individual products; "
    "another document owns the catalog. Do not reproduce customer reviews; another document owns "
    "them. If a fact cannot be established, leave the field null and add it to not_found. Never "
    "estimate silently; label any estimate as an estimate inside the text."
)


def company_overview_output_schema() -> dict[str, Any]:
    """ARV2-COMPANY-OVERVIEW-CONTRACT.md §2.3, verbatim."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["facts", "sections", "competitors", "named_customers", "not_found"],
        "properties": {
            "facts": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "legal_name": _nullable("string"),
                    "website": _nullable("string", format="uri"),
                    "founded_year": _nullable("integer"),
                    "headquarters": _nullable("string"),
                    "employee_range": _nullable(
                        "string",
                        description="e.g. 51-200, as publicly stated or estimated; say which",
                    ),
                    "funding_total_usd": _nullable("number"),
                    "latest_round": _nullable(
                        "string", description="round name, amount, date, lead investor"
                    ),
                    "investors": _string_list(15),
                    "revenue_model": _nullable(
                        "string",
                        description="how they charge: per seat, per encounter, platform fee, services",
                    ),
                    "pricing_posture": _nullable(
                        "string",
                        description="published prices, quote-only, freemium, enterprise-only",
                    ),
                    "industries_served": _string_list(10),
                    "geographies": _string_list(10),
                    "customer_count_claim": _nullable(
                        "string",
                        description="the company's own stated number, verbatim, with where it was stated",
                    ),
                    "regulatory_posture": _nullable(
                        "string",
                        description=(
                            "certifications and compliance claims relevant to buyers, "
                            "e.g. HIPAA, SOC 2, BAA availability"
                        ),
                    ),
                },
            },
            "sections": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "origin_story", "business_model", "positioning", "market_position",
                    "customer_segments", "leadership", "recent_context",
                ],
                "properties": {
                    "origin_story": {
                        "type": "string",
                        "description": (
                            "Markdown. Founding problem, founders and their prior experience, "
                            "first customers and early product."
                        ),
                    },
                    "business_model": {
                        "type": "string",
                        "description": (
                            "Markdown. How they make money, pricing posture, funding trajectory. "
                            "No valuation speculation."
                        ),
                    },
                    "positioning": {
                        "type": "string",
                        "description": (
                            "Markdown. Value proposition in the company's own words, the "
                            "differentiators they claim, and the portfolio described in one "
                            "paragraph. Do NOT list individual products; another document owns "
                            "the catalog."
                        ),
                    },
                    "market_position": {
                        "type": "string",
                        "description": (
                            "Markdown. Main competitors and how the company stacks up, "
                            "defensibility, market size and growth where sourced."
                        ),
                    },
                    "customer_segments": {
                        "type": "string",
                        "description": (
                            "Markdown. Who buys and who uses it: segments, roles, organisation "
                            "types and sizes, use cases. Cite case studies. Do not reproduce "
                            "reviews; a separate document owns them."
                        ),
                    },
                    "leadership": {
                        "type": "string",
                        "description": (
                            "Markdown. Current leadership team with titles. No employee reviews "
                            "or culture commentary."
                        ),
                    },
                    "recent_context": {
                        "type": "string",
                        "description": (
                            "Markdown. Announcements, partnerships, expansion, hiring signals "
                            "from the last 12 months, each dated."
                        ),
                    },
                },
            },
            "competitors": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "how_they_compare"],
                    "properties": {
                        "name": {"type": "string"},
                        "website": _nullable("string", format="uri"),
                        "how_they_compare": {
                            "type": "string",
                            "description": "one or two sentences, sourced",
                        },
                    },
                },
            },
            "named_customers": {
                "type": "array",
                "maxItems": 30,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "segment": _nullable("string"),
                        "evidence_kind": {
                            "type": "string",
                            "enum": ["case_study", "logo_wall", "press", "review", "other"],
                        },
                    },
                },
            },
            "not_found": _string_list(
                20, "an item that was searched for and could not be established, stated plainly"
            ),
        },
    }


# -- 4.3 customer reviews ----------------------------------------------------------------------


def customer_reviews_query(company_name: str, domain: str) -> str:
    return (
        f"Find what customers say about {company_name} ({domain}) as a vendor: reviews on G2, "
        "Capterra, Trustpilot, app marketplaces, EHR/partner marketplaces, Reddit and professional "
        "communities, plus the company's own case studies and testimonials. Separate praise from "
        "complaints. Quote verbatim."
    )


CUSTOMER_REVIEWS_SYSTEM_PROMPT = (
    "Quote every review verbatim, at most 40 words, with its URL, platform, rating and date "
    "when shown. Record the reviewer's role and organisation type; never the reviewer's name. "
    "Name a person only when the vendor's own case study names them, and then with their title. "
    "Separate praise from complaints honestly; say plainly when the corpus is thin. Leave a field "
    "null and add it to not_found rather than estimate."
)


def customer_reviews_output_schema() -> dict[str, Any]:
    """ARV2-ONBOARDING-PLAN.md §4.3."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "themes_positive", "themes_negative", "reviews", "case_studies", "not_found"],
        "properties": {
            "summary": {
                "type": "string",
                "description": (
                    "Markdown, 1–2 paragraphs: overall sentiment, volume and where reviews live. "
                    "Say plainly when the corpus is thin."
                ),
            },
            "themes_positive": _string_list(8),
            "themes_negative": _string_list(8),
            "reviews": {
                "type": "array",
                "maxItems": 40,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["platform", "quote", "sentiment", "source_url"],
                    "properties": {
                        "platform": {"type": "string"},
                        "source_url": {"type": "string", "format": "uri"},
                        "quote": {"type": "string", "description": "verbatim, 40 words max"},
                        "sentiment": {"type": "string", "enum": ["positive", "mixed", "negative"]},
                        "rating": _nullable("number"),
                        "date": _nullable("string"),
                        "reviewer_role": _nullable("string"),
                        "reviewer_org_type": _nullable(
                            "string",
                            description="e.g. multi-specialty group, 20 clinicians. Never the reviewer's name.",
                        ),
                        "product_mentioned": _nullable("string"),
                    },
                },
            },
            "case_studies": {
                "type": "array",
                "maxItems": 15,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["customer", "source_url"],
                    "properties": {
                        "customer": {"type": "string"},
                        "source_url": {"type": "string", "format": "uri"},
                        "outcome_claim": _nullable(
                            "string",
                            description="the stated result, verbatim, e.g. '38% fewer no-shows'",
                        ),
                        "named_person": _nullable(
                            "string",
                            description="only if the seller's own case study names them, with title",
                        ),
                    },
                },
            },
            "not_found": _string_list(10),
        },
    }


# -- 4.4 per-product research --------------------------------------------------------------------


def product_research_query(
    *,
    product_name: str,
    company_name: str,
    official_url: str | None,
    sibling_names: Sequence[str],
) -> str:
    parts = [
        f"Research the product {product_name} by {company_name}: what it does, its explicitly "
        "stated capabilities, use cases, who it is for, integrations, published pricing and "
        "packaging, differentiators, competitors for this product specifically, and customer "
        "evidence (case studies, testimonials, outcomes) that names this product."
    ]
    if official_url:
        parts.append(f"Its official page is {official_url}; read it first and cite it.")
    if sibling_names:
        parts.append(
            "This company also sells "
            + ", ".join(sibling_names)
            + "; this report is NOT about those — mention them only where "
            f"{product_name} integrates with or bundles them."
        )
    return " ".join(parts)


PRODUCT_RESEARCH_SYSTEM_PROMPT = (
    "Describe only this product. A capability is one explicitly stated capability in the "
    "company's own words, never an inference. Pricing is null unless published for this product. "
    "Competitors are for this product, not the company. Leave a field null or empty and add the "
    "gap to not_found rather than fill it from a sibling product or a guess."
)


def product_research_output_schema() -> dict[str, Any]:
    """ARV2-ONBOARDING-PLAN.md §4.4 — the old lane's nine product topics as the vocabulary."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "overview", "capabilities", "use_cases", "integrations", "pricing",
            "differentiators", "competitors", "customer_evidence", "not_found",
        ],
        "properties": {
            "overview": {"type": "string", "description": "Markdown, 1–2 paragraphs, this product only."},
            "capabilities": _string_list(
                15, "one explicitly stated capability, in the company's words"
            ),
            "use_cases": _string_list(10),
            "integrations": _string_list(20),
            "pricing": _nullable(
                "string",
                description="published prices and packaging for this product only; null if not published",
            ),
            "differentiators": _string_list(8),
            "competitors": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "website": _nullable("string", format="uri"),
                        "how_they_compare": _nullable("string"),
                    },
                },
            },
            "customer_evidence": {
                "type": "array",
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["customer", "source_url"],
                    "properties": {
                        "customer": {"type": "string"},
                        "source_url": {"type": "string", "format": "uri"},
                        "outcome_claim": _nullable("string"),
                    },
                },
            },
            "who_it_is_for": _nullable(
                "string",
                description="buyer and user roles, organisation types, in the company's words",
            ),
            "not_found": _string_list(10),
        },
    }


# -- 4.5 persona evidence (a /search deep-reasoning request: depth ≤ 2, ≤ 10 properties) ---------

PERSONA_EVIDENCE_SYSTEM_PROMPT = (
    "Prefer first-person accounts by people in the named role: forum posts, interviews, "
    "reviews, talks, job postings. Never paraphrase a quote; return it verbatim with its "
    "speaker's role. Return nothing rather than a weak match."
)


def persona_evidence_output_schema() -> dict[str, Any]:
    """Five properties, two levels; citations come back in ``output.grounding``, never here."""
    return {
        "type": "object",
        "required": ["passages"],
        "properties": {
            "passages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["quote", "speaker_role"],
                    "properties": {
                        "quote": {"type": "string", "description": "verbatim, 60 words max"},
                        "speaker_role": {
                            "type": "string",
                            "description": "the speaker's role/title as stated or evident",
                        },
                        "org_type": {"type": "string"},
                        "topic": {
                            "type": "string",
                            "description": "pain | language | tooling | trigger | objection",
                        },
                    },
                },
            }
        },
    }
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/arv2/test_onboarding_requests.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the live Agent test once**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/test_exa_agent_live.py -v -s`
Expected: PASS in under two minutes, ~$0.025 (or SKIP naming `CLUE_EXA_API_KEY` if unset). Paste the printed cost and status into the commit message body.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/arv2/onboarding_requests.py tests/arv2/test_onboarding_requests.py
git commit -m "feat(arv2): onboarding request templates — overview (contract-verbatim), customer reviews, per-product, persona evidence; live Agent run proven at low effort"
```

---

### Task 4: The document mappers — `onboarding_documents.py`

**Files:**
- Modify: `platform/api/pyproject.toml` (dependencies)
- Create: `platform/api/clue_api/arv2/onboarding_documents.py`
- Create: `tests/arv2/fixtures/exa_agent_overview_insight_health.json`
- Test: `tests/arv2/test_onboarding_documents.py`

**Interfaces:**
- Produces (all pure):
  - `@dataclass(frozen=True) class KnowledgeDocument`: `kind: str`, `folder: str`, `path: str`, `front_matter: dict[str, Any]`, `body: str`, `cost: CallCost | None`.
  - `render_markdown(document: KnowledgeDocument) -> str` — YAML front matter between `---` fences, blank line, body.
  - `demote_headings(markdown: str, by: int = 1) -> str`.
  - `sources_by_field(grounding: Sequence[Any]) -> dict[str, dict[str, Any]]` — `{field: {"citations": [{"url","title"}], "confidence": str}}`.
  - `company_overview_document(run: ExaAgentRun, *, company_domain: str, as_of: date) -> KnowledgeDocument` (kind `company-overview`, path `company/overview.md`).
  - `customer_reviews_document(run: ExaAgentRun, *, company_domain: str, as_of: date) -> KnowledgeDocument` (kind `customer-reviews`, path `proof/customer-reviews.md`).
  - `product_research_document(run: ExaAgentRun, *, product_id: str, product_name: str, product_slug: str, as_of: date) -> KnowledgeDocument` (kind `product-research`, path `product/<slug>.md`).
  - `product_catalog_document(result: ExaDeepResult, *, company_domain: str, as_of: date) -> KnowledgeDocument` (kind `product-catalog`, path `product/catalog.md`; front matter = `ProductCatalogResearch@1`).
  - `slugify(name: str) -> str`.
  - O3 persists `render_markdown(doc)` as the artifact and registers the document row.

- [ ] **Step 1: Add the dependency and copy the fixture**

In `platform/api/pyproject.toml`, in the `dependencies` list right after the `httpx` line, add:

```toml
    # ARV2 onboarding (O2): YAML front matter on the knowledge documents.
    "pyyaml>=6,<7",
```

Then `uv sync` (the workspace lock updates; commit `uv.lock` with this task).

```bash
mkdir -p tests/arv2/fixtures
cp ".context/attachments/MB8vCz/pasted_text_2026-09-07_18-04-55.txt" tests/arv2/fixtures/exa_agent_overview_insight_health.json
python3 -c "import json;json.load(open('tests/arv2/fixtures/exa_agent_overview_insight_health.json'))"
```

If the attachment is no longer present, ask Aryan for the saved run `agent_run_11b83e1af2bd44f399badec0d8c77ebd` JSON; do not fabricate one.

- [ ] **Step 2: Write the failing tests**

```python
# tests/arv2/test_onboarding_documents.py
"""The mappers are pure: a recorded provider body in, a KnowledgeDocument out. The recorded
Insight Health run is mapper INPUT, not a provider double (R1's live-test ruling is untouched)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

from clue_api.arv2.calls import CallCost
from clue_api.arv2.exa_client import ExaAgentRun, ExaDeepResult
from clue_api.arv2.onboarding_documents import (
    KnowledgeDocument,
    company_overview_document,
    customer_reviews_document,
    demote_headings,
    product_catalog_document,
    product_research_document,
    render_markdown,
    slugify,
    sources_by_field,
)

FIXTURE = Path(__file__).parent / "fixtures" / "exa_agent_overview_insight_health.json"
AS_OF = date(2026, 9, 7)


def _cost(usd: str = "0.5") -> CallCost:
    return CallCost(
        cost_usd=Decimal(usd), credits=Decimal(0), media_seconds=0, cost_source="metered",
        provider="exa", operation="agent-poll", raw_ref="raw/1", ledger_row_id="row-1",
    )


def _overview_run() -> ExaAgentRun:
    body = json.loads(FIXTURE.read_text())
    return ExaAgentRun(
        run_id=body["id"], status=body["status"], stop_reason=body["stopReason"],
        output_text=body["output"]["text"], structured=body["output"]["structured"],
        grounding=body["output"]["grounding"], usage=body["usage"],
        cost_usd=Decimal(str(body["costDollars"]["total"])), error_code=None, error_message=None,
        polls=3, raw_refs=("raw/1",), ledger_row_ids=("row-1",), costs=(_cost(),), cost=_cost(),
    )


def test_render_writes_yaml_front_matter_then_the_body() -> None:
    doc = KnowledgeDocument(
        kind="company-overview", folder="company", path="company/overview.md",
        front_matter={"kind": "company-overview", "as_of": "2026-09-07", "facts": {"founded_year": 2023}},
        body="# Company overview\n\nHello.\n", cost=None,
    )
    text = render_markdown(doc)
    assert text.startswith("---\n")
    head, _, body = text[4:].partition("\n---\n")
    assert yaml.safe_load(head) == doc.front_matter
    assert body.lstrip("\n") == doc.body
    assert "\nkind: company-overview\n" in "\n" + head  # insertion order kept, not sorted


def test_demote_headings_pushes_every_heading_down_one_level() -> None:
    assert demote_headings("## Leadership\n\ntext\n### Sub\n#notaheading") == (
        "### Leadership\n\ntext\n#### Sub\n#notaheading"
    )


def test_sources_by_field_keeps_confidence_and_citations_per_field() -> None:
    grounding = [
        {"field": "structured.facts", "citations": [{"url": "https://a", "title": "A"}], "confidence": "high"},
        {"field": "structured.sections.leadership", "citations": [], "confidence": "medium"},
        "garbage",
    ]
    sources = sources_by_field(grounding)
    assert sources["structured.facts"] == {"citations": [{"url": "https://a", "title": "A"}], "confidence": "high"}
    assert sources["structured.sections.leadership"]["confidence"] == "medium"
    assert len(sources) == 2


def test_the_overview_mapper_builds_the_contracts_front_matter_and_fixed_headings() -> None:
    doc = company_overview_document(_overview_run(), company_domain="insighthealth.ai", as_of=AS_OF)
    assert (doc.kind, doc.folder, doc.path) == ("company-overview", "company", "company/overview.md")
    fm = doc.front_matter
    assert fm["kind"] == "company-overview"
    assert fm["as_of"] == "2026-09-07" and fm["company_domain"] == "insighthealth.ai"
    assert fm["provider_run_id"] == "agent_run_11b83e1af2bd44f399badec0d8c77ebd"
    assert fm["facts"]["legal_name"] == "Insight Health AI, Inc."
    assert fm["facts"]["founded_year"] == 2023
    assert [c["name"] for c in fm["competitors"]][:2] == ["Tennr", "HealOS"]
    assert len(fm["named_customers"]) == 8
    assert len(fm["not_found"]) == 7
    assert fm["sources"]["structured.sections.market_position"]["confidence"] == "medium"
    assert fm["cost_usd"] == "0.5" and fm["searches"] == 60
    assert doc.cost is not None and doc.cost.cost_usd == Decimal("0.5")

    headings = [line for line in doc.body.splitlines() if line.startswith("#")]
    assert headings[0] == "# Company overview"
    assert [h for h in headings if h.startswith("## ")] == [
        "## Origin story", "## Business model", "## Positioning", "## Market position",
        "## Competitors", "## Customer segments", "## Named customers", "## Leadership",
        "## Recent context", "## Not established", "## Sources",
    ]
    # The model's own "## Leadership and organization" is demoted, so ours stay the only H2s.
    assert "### Leadership and organization" in doc.body
    assert "- **Founded:** 2023" in doc.body
    assert "| Tennr |" in doc.body and "| The Oregon Clinic |" in doc.body
    assert "Audited financial statements" in doc.body  # not_found is rendered, never hidden
    assert "[Business Wire]" in doc.body  # inline labels are left as text


def test_the_overview_mapper_on_a_failed_run_yields_an_honest_empty_document() -> None:
    failed = ExaAgentRun(
        run_id="agent_run_x", status="failed", stop_reason=None, output_text=None, structured=None,
        grounding=[], usage={}, cost_usd=None, error_code="schema_unsatisfiable",
        error_message="could not satisfy schema", polls=1, raw_refs=(), ledger_row_ids=("row-1",),
        costs=(_cost("0"),), cost=_cost("0"),
    )
    doc = company_overview_document(failed, company_domain="x.io", as_of=AS_OF)
    assert doc.front_matter["status"] == "failed"
    assert doc.front_matter["error"] == {"code": "schema_unsatisfiable", "message": "could not satisfy schema"}
    assert doc.front_matter["facts"] == {} and doc.front_matter["not_found"] == []
    assert "## Not established" in doc.body and "schema_unsatisfiable" in doc.body


def test_the_reviews_mapper_never_carries_a_reviewer_name_field() -> None:
    run = ExaAgentRun(
        run_id="agent_run_r", status="completed", stop_reason="schema_satisfied", output_text="ok",
        structured={
            "summary": "Thin corpus.",
            "themes_positive": ["fast setup"], "themes_negative": ["fax OCR misses"],
            "reviews": [{"platform": "G2", "source_url": "https://g2.com/x", "quote": "Setup took a day.",
                         "sentiment": "positive", "rating": 4.5, "date": "2026-05", "reviewer_role": "Practice manager",
                         "reviewer_org_type": "GI practice, 12 clinicians", "product_mentioned": "Aura"}],
            "case_studies": [{"customer": "Headland Family Medicine", "source_url": "https://insighthealth.ai/c/1",
                              "outcome_claim": "38% fewer no-shows", "named_person": None}],
            "not_found": ["Trustpilot page"],
        },
        grounding=[], usage={"searches": 9}, cost_usd=Decimal("0.1"), error_code=None, error_message=None,
        polls=2, raw_refs=(), ledger_row_ids=("row-1",), costs=(_cost("0.1"),), cost=_cost("0.1"),
    )
    doc = customer_reviews_document(run, company_domain="insighthealth.ai", as_of=AS_OF)
    assert doc.path == "proof/customer-reviews.md" and doc.kind == "customer-reviews"
    assert "reviewer_name" not in json.dumps(doc.front_matter)
    assert "## What customers praise" in doc.body and "## What customers complain about" in doc.body
    assert "> Setup took a day." in doc.body and "Practice manager" in doc.body
    assert "## Case studies" in doc.body and "38% fewer no-shows" in doc.body


def test_the_product_mapper_names_the_product_and_slugs_its_path() -> None:
    run = ExaAgentRun(
        run_id="agent_run_p", status="completed", stop_reason="schema_satisfied", output_text="ok",
        structured={
            "overview": "Ambient scribe.", "capabilities": ["Drafts SOAP notes"], "use_cases": ["GI visits"],
            "integrations": ["athenahealth"], "pricing": "$39.99/month Pro", "differentiators": ["Specialty templates"],
            "competitors": [{"name": "Abridge", "website": None, "how_they_compare": None}],
            "customer_evidence": [], "who_it_is_for": "Clinicians in outpatient practices", "not_found": [],
        },
        grounding=[], usage={}, cost_usd=Decimal("0.1"), error_code=None, error_message=None,
        polls=1, raw_refs=(), ledger_row_ids=("row-1",), costs=(_cost("0.1"),), cost=_cost("0.1"),
    )
    doc = product_research_document(
        run, product_id="prd_aura", product_name="Aura AI Scribe", product_slug=slugify("Aura AI Scribe"), as_of=AS_OF
    )
    assert doc.path == "product/aura-ai-scribe.md" and doc.kind == "product-research"
    assert doc.front_matter["product_id"] == "prd_aura"
    assert doc.body.startswith("# Aura AI Scribe\n")
    assert "## Who it is for" in doc.body and "## Pricing" in doc.body
    assert slugify("MagicDocs AI Referral Coordinator") == "magicdocs-ai-referral-coordinator"
    assert slugify("  Pré-Visit / Intake (Lumi)  ") == "pre-visit-intake-lumi"


def test_the_catalog_mapper_attaches_grounding_per_product_and_drops_nameless_entries() -> None:
    deep = ExaDeepResult(
        output_text="{}",
        output_object={
            "coverage_note": "Own domain + open web.",
            "products": [
                {"name": "Aura AI Scribe", "short_description": "Ambient documentation.",
                 "offering_kind": "product", "family": "Aura", "lifecycle": "active",
                 "official_url": "https://www.insighthealth.ai/ambient"},
                {"name": "", "short_description": "orphan", "offering_kind": "product"},
                {"name": "EHR Partnership", "short_description": "Embed Aura in an EHR.",
                 "offering_kind": "partner_program"},
            ],
        },
        report_text=None,
        grounding=[
            {"field": "products[0].official_url", "citations": [{"url": "https://www.insighthealth.ai/ambient", "title": "Aura"}], "confidence": "high"},
            {"field": "products[0].short_description", "citations": [{"url": "https://www.insighthealth.ai/", "title": "Home"}], "confidence": "medium"},
            {"field": "products[2].name", "citations": [{"url": "https://www.insighthealth.ai/ehr-partnership", "title": "EHR"}], "confidence": "high"},
        ],
        results=(), status=200, cost_usd=Decimal("0.015"), request_id="req", raw_ref="raw/2",
        ledger_row_id="row-2", cost=_cost("0.015"), retried=False,
    )
    doc = product_catalog_document(deep, company_domain="insighthealth.ai", as_of=AS_OF)
    assert (doc.kind, doc.path) == ("product-catalog", "product/catalog.md")
    fm = doc.front_matter
    assert fm["kind"] == "product-catalog" and fm["coverage_note"] == "Own domain + open web."
    assert [p["name"] for p in fm["products"]] == ["Aura AI Scribe", "EHR Partnership"]
    aura = fm["products"][0]
    assert aura["aliases"] == [] and aura["grounding_confidence"] == "medium"
    assert {s["url"] for s in aura["sources"]} == {"https://www.insighthealth.ai/ambient", "https://www.insighthealth.ai/"}
    assert fm["products"][1]["sources"][0]["url"].endswith("/ehr-partnership")
    assert fm["dropped"] == [{"index": 1, "reason": "missing name or short_description"}]
    assert "## Dropped by the mapper" in doc.body and "orphan" in doc.body
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/arv2/test_onboarding_documents.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clue_api.arv2.onboarding_documents'`.

- [ ] **Step 4: Write the module**

```python
# platform/api/clue_api/arv2/onboarding_documents.py
"""Provider response → KnowledgeDocument: the pure mappers of the onboarding lane.

Front matter is the machine contract (ARV2-COMPANY-OVERVIEW-CONTRACT.md §3.1,
ARV2-PRODUCT-CATALOG-CONTRACT.md §4); the body is the human-readable render under **fixed**
headings in a fixed order — product vocabulary, never model-written. A heading the model wrote
inside a section is demoted one level so the fixed ones stay the only H2s. ``not_found`` is
always rendered: an empty, named gap is a correct output.

Everything here is pure. ``cost`` on a document is the settling call's cost when the document
was built from a call, ``None`` when it was not (the import guard's documented exception).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import yaml

from clue_api.arv2.calls import CallCost
from clue_api.arv2.exa_client import ExaAgentRun, ExaDeepResult

__all__ = [
    "KnowledgeDocument",
    "company_overview_document",
    "customer_reviews_document",
    "demote_headings",
    "product_catalog_document",
    "product_research_document",
    "render_markdown",
    "slugify",
    "sources_by_field",
]

_HEADING = re.compile(r"^(#{1,5})(?=\s)", re.MULTILINE)
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class KnowledgeDocument:
    kind: str
    folder: str
    path: str
    front_matter: dict[str, Any]
    body: str
    cost: CallCost | None


def render_markdown(document: KnowledgeDocument) -> str:
    front = yaml.safe_dump(
        document.front_matter, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    return f"---\n{front}---\n\n{document.body}"


def demote_headings(markdown: str, by: int = 1) -> str:
    return _HEADING.sub(lambda m: m.group(1) + "#" * by, markdown)


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug or "untitled"


def sources_by_field(grounding: Sequence[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in grounding:
        if not isinstance(row, dict) or not isinstance(row.get("field"), str):
            continue
        citations = [
            {"url": c.get("url"), "title": c.get("title")}
            for c in (row.get("citations") or [])
            if isinstance(c, dict) and isinstance(c.get("url"), str)
        ]
        confidence = row.get("confidence")
        out[row["field"]] = {
            "citations": citations,
            "confidence": confidence if isinstance(confidence, str) else None,
        }
    return out


# -- shared pieces ----------------------------------------------------------------------------


def _iso(as_of: date) -> str:
    return as_of.isoformat()


def _structured(run: ExaAgentRun) -> Mapping[str, Any]:
    return run.structured if isinstance(run.structured, dict) else {}


def _run_header(run: ExaAgentRun, *, kind: str, as_of: date, **scope: Any) -> dict[str, Any]:
    header: dict[str, Any] = {"kind": kind, "as_of": _iso(as_of), **scope}
    header["provider_run_id"] = run.run_id
    header["status"] = "ready" if run.status == "completed" else "failed"
    if run.status != "completed":
        header["error"] = {"code": run.error_code, "message": run.error_message}
    return header


def _run_footer(run: ExaAgentRun) -> dict[str, Any]:
    searches = run.usage.get("searches") if isinstance(run.usage, dict) else None
    return {
        "sources": sources_by_field(run.grounding),
        "cost_usd": str(run.cost_usd) if run.cost_usd is not None else None,
        "searches": int(searches) if isinstance(searches, int) else 0,
    }


def _section(title: str, body: str | None) -> str:
    text = (body or "").strip()
    content = demote_headings(text) if text else "_Not established._"
    return f"## {title}\n\n{content}\n"


def _list_section(title: str, items: Sequence[Any], empty: str) -> str:
    if not items:
        return f"## {title}\n\n_{empty}_\n"
    return f"## {title}\n\n" + "".join(f"- {item}\n" for item in items)


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    def cell(value: Any) -> str:
        return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def _sources_section(sources: Mapping[str, Mapping[str, Any]]) -> str:
    if not sources:
        return "## Sources\n\n_No field-level grounding was returned._\n"
    lines = ["## Sources", ""]
    for field, entry in sources.items():
        label = field.removeprefix("structured.")
        lines.append(f"- **{label}** ({entry.get('confidence') or 'unrated'})")
        for citation in entry.get("citations", []):
            title = citation.get("title") or citation.get("url")
            lines.append(f"  - [{title}]({citation.get('url')})")
    return "\n".join(lines) + "\n"


def _failure_note(run: ExaAgentRun) -> str:
    return f"- Research run did not complete: `{run.error_code or run.status}` — {run.error_message or ''}".rstrip(" —")


# -- 4.2 company overview ----------------------------------------------------------------------

_FACT_LABELS: tuple[tuple[str, str], ...] = (
    ("legal_name", "Legal name"),
    ("website", "Website"),
    ("founded_year", "Founded"),
    ("headquarters", "Headquarters"),
    ("employee_range", "Employees"),
    ("funding_total_usd", "Funding total (USD)"),
    ("latest_round", "Latest round"),
    ("investors", "Investors"),
    ("revenue_model", "Revenue model"),
    ("pricing_posture", "Pricing posture"),
    ("industries_served", "Industries served"),
    ("geographies", "Geographies"),
    ("customer_count_claim", "Customer count (company claim)"),
    ("regulatory_posture", "Regulatory posture"),
)


def company_overview_document(
    run: ExaAgentRun, *, company_domain: str, as_of: date
) -> KnowledgeDocument:
    data = _structured(run)
    facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
    sections = data.get("sections") if isinstance(data.get("sections"), dict) else {}
    competitors = [c for c in (data.get("competitors") or []) if isinstance(c, dict)]
    customers = [c for c in (data.get("named_customers") or []) if isinstance(c, dict)]
    not_found = [n for n in (data.get("not_found") or []) if isinstance(n, str)]

    front = _run_header(run, kind="company-overview", as_of=as_of, company_domain=company_domain)
    front.update(
        {"facts": dict(facts), "competitors": competitors, "named_customers": customers,
         "not_found": not_found, **_run_footer(run)}
    )

    fact_lines = [
        f"- **{label}:** {', '.join(map(str, value)) if isinstance(value, list) else value}"
        for key, label in _FACT_LABELS
        for value in [facts.get(key)]
        if value not in (None, "", [])
    ]
    gaps = list(not_found)
    if run.status != "completed":
        gaps.append(_failure_note(run))
    body = "\n".join(
        [
            "# Company overview",
            "",
            "\n".join(fact_lines) if fact_lines else "_No facts were established._",
            "",
            _section("Origin story", sections.get("origin_story")),
            _section("Business model", sections.get("business_model")),
            _section("Positioning", sections.get("positioning")),
            _section("Market position", sections.get("market_position")),
            "## Competitors\n\n"
            + (_table(("Name", "Website", "How they compare"),
                      [(c.get("name"), c.get("website"), c.get("how_they_compare")) for c in competitors])
               if competitors else "_Not established._\n"),
            _section("Customer segments", sections.get("customer_segments")),
            "## Named customers\n\n"
            + (_table(("Name", "Segment", "Evidence"),
                      [(c.get("name"), c.get("segment"), c.get("evidence_kind")) for c in customers])
               if customers else "_Not established._\n"),
            _section("Leadership", sections.get("leadership")),
            _section("Recent context", sections.get("recent_context")),
            _list_section("Not established", gaps, "Nothing was left unestablished."),
            _sources_section(front["sources"]),
        ]
    )
    return KnowledgeDocument(
        kind="company-overview", folder="company", path="company/overview.md",
        front_matter=front, body=body, cost=run.cost,
    )


# -- 4.3 customer reviews ----------------------------------------------------------------------


def customer_reviews_document(
    run: ExaAgentRun, *, company_domain: str, as_of: date
) -> KnowledgeDocument:
    data = _structured(run)
    reviews = [r for r in (data.get("reviews") or []) if isinstance(r, dict)]
    case_studies = [c for c in (data.get("case_studies") or []) if isinstance(c, dict)]
    positive = [r for r in reviews if r.get("sentiment") == "positive"]
    negative = [r for r in reviews if r.get("sentiment") in ("negative", "mixed")]
    not_found = [n for n in (data.get("not_found") or []) if isinstance(n, str)]

    front = _run_header(run, kind="customer-reviews", as_of=as_of, company_domain=company_domain)
    front.update(
        {
            "themes_positive": list(data.get("themes_positive") or []),
            "themes_negative": list(data.get("themes_negative") or []),
            "reviews": reviews,
            "case_studies": case_studies,
            "not_found": not_found,
            **_run_footer(run),
        }
    )

    def quote_block(items: Sequence[Mapping[str, Any]]) -> str:
        if not items:
            return "_Not established._\n"
        out = []
        for r in items:
            who = " · ".join(str(x) for x in (r.get("reviewer_role"), r.get("reviewer_org_type")) if x)
            meta = " · ".join(str(x) for x in (r.get("platform"), r.get("rating"), r.get("date")) if x)
            out.append(f"> {r.get('quote', '').strip()}\n>\n> — {who or 'reviewer'} ({meta}) [{r.get('platform')}]({r.get('source_url')})\n")
        return "\n".join(out)

    gaps = list(not_found)
    if run.status != "completed":
        gaps.append(_failure_note(run))
    body = "\n".join(
        [
            "# Customer reviews",
            "",
            _section("Summary", data.get("summary")),
            _list_section("Themes: praise", front["themes_positive"], "None established."),
            _list_section("Themes: complaints", front["themes_negative"], "None established."),
            "## What customers praise\n\n" + quote_block(positive),
            "## What customers complain about\n\n" + quote_block(negative),
            "## Case studies\n\n"
            + (_table(("Customer", "Outcome claim", "Named person", "Source"),
                      [(c.get("customer"), c.get("outcome_claim"), c.get("named_person"), c.get("source_url"))
                       for c in case_studies])
               if case_studies else "_Not established._\n"),
            _list_section("Not established", gaps, "Nothing was left unestablished."),
            _sources_section(front["sources"]),
        ]
    )
    return KnowledgeDocument(
        kind="customer-reviews", folder="proof", path="proof/customer-reviews.md",
        front_matter=front, body=body, cost=run.cost,
    )


# -- 4.4 per-product research --------------------------------------------------------------------


def product_research_document(
    run: ExaAgentRun, *, product_id: str, product_name: str, product_slug: str, as_of: date
) -> KnowledgeDocument:
    data = _structured(run)
    competitors = [c for c in (data.get("competitors") or []) if isinstance(c, dict)]
    evidence = [c for c in (data.get("customer_evidence") or []) if isinstance(c, dict)]
    not_found = [n for n in (data.get("not_found") or []) if isinstance(n, str)]

    front = _run_header(
        run, kind="product-research", as_of=as_of, product_id=product_id, product_name=product_name
    )
    front.update(
        {
            key: data.get(key)
            for key in ("capabilities", "use_cases", "integrations", "pricing", "differentiators", "who_it_is_for")
        }
    )
    front.update({"competitors": competitors, "customer_evidence": evidence, "not_found": not_found, **_run_footer(run)})

    gaps = list(not_found)
    if run.status != "completed":
        gaps.append(_failure_note(run))
    body = "\n".join(
        [
            f"# {product_name}",
            "",
            _section("Overview", data.get("overview")),
            _list_section("Capabilities", data.get("capabilities") or [], "Not established."),
            _list_section("Use cases", data.get("use_cases") or [], "Not established."),
            _section("Who it is for", data.get("who_it_is_for")),
            _list_section("Integrations", data.get("integrations") or [], "Not established."),
            _section("Pricing", data.get("pricing")),
            _list_section("Differentiators", data.get("differentiators") or [], "Not established."),
            "## Competitors\n\n"
            + (_table(("Name", "Website", "How they compare"),
                      [(c.get("name"), c.get("website"), c.get("how_they_compare")) for c in competitors])
               if competitors else "_Not established._\n"),
            "## Customer evidence\n\n"
            + (_table(("Customer", "Outcome claim", "Source"),
                      [(c.get("customer"), c.get("outcome_claim"), c.get("source_url")) for c in evidence])
               if evidence else "_Not established._\n"),
            _list_section("Not established", gaps, "Nothing was left unestablished."),
            _sources_section(front["sources"]),
        ]
    )
    return KnowledgeDocument(
        kind="product-research", folder="product", path=f"product/{product_slug}.md",
        front_matter=front, body=body, cost=run.cost,
    )


# -- 4.1 product catalog (ARV2-PRODUCT-CATALOG-CONTRACT.md §4) -----------------------------------

_CATALOG_KEYS = ("name", "short_description", "offering_kind", "family", "lifecycle", "official_url")


def product_catalog_document(
    result: ExaDeepResult, *, company_domain: str, as_of: date
) -> KnowledgeDocument:
    parsed = result.output_object if isinstance(result.output_object, dict) else {}
    raw_products = [p for p in (parsed.get("products") or []) if isinstance(p, dict)]
    by_field = sources_by_field(result.grounding if isinstance(result.grounding, list) else [])

    products: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_products):
        name = raw.get("name")
        description = raw.get("short_description")
        if not (isinstance(name, str) and name.strip() and isinstance(description, str) and description.strip()):
            dropped.append({"index": index, "reason": "missing name or short_description"})
            continue
        prefix = f"products[{index}]"
        rows = [entry for field, entry in by_field.items() if field == prefix or field.startswith(prefix + ".")]
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in rows:
            for citation in entry["citations"]:
                if citation["url"] not in seen:
                    seen.add(citation["url"])
                    sources.append(citation)
        confidences = [e["confidence"] for e in rows if e.get("confidence") in _CONFIDENCE_RANK]
        entry = {key: raw.get(key) for key in _CATALOG_KEYS}
        entry["aliases"] = []
        entry["sources"] = sources
        entry["grounding_confidence"] = (
            min(confidences, key=_CONFIDENCE_RANK.__getitem__) if confidences else None
        )
        products.append(entry)

    front: dict[str, Any] = {
        "kind": "product-catalog",
        "as_of": _iso(as_of),
        "company_domain": company_domain,
        "provider_request_id": result.request_id,
        "coverage_note": parsed.get("coverage_note"),
        "products": products,
        "dropped": dropped,
        "cost_usd": str(result.cost_usd) if result.cost_usd is not None else None,
    }
    lines = ["# Product catalog", ""]
    if front["coverage_note"]:
        lines += [f"_Coverage: {front['coverage_note']}_", ""]
    if products:
        lines.append(
            _table(
                ("Name", "Kind", "Family", "Lifecycle", "Official page", "Description"),
                [(p["name"], p["offering_kind"], p["family"], p["lifecycle"], p["official_url"], p["short_description"])
                 for p in products],
            )
        )
    else:
        lines.append("_No products were established._\n")
    if dropped:
        lines += ["## Dropped by the mapper", ""]
        for d in dropped:
            raw = raw_products[d["index"]]
            lines.append(f"- entry {d['index']}: {d['reason']} — `{raw}`")
        lines.append("")
    lines.append(_sources_section(by_field))
    return KnowledgeDocument(
        kind="product-catalog", folder="product", path="product/catalog.md",
        front_matter=front, body="\n".join(lines), cost=result.cost,
    )
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/arv2/test_onboarding_documents.py -v`
Expected: all PASS. If a body assertion fails on exact spacing, fix the mapper's join, not the test's expectation of the fixed headings.

- [ ] **Step 6: Commit**

```bash
git add platform/api/pyproject.toml uv.lock platform/api/clue_api/arv2/onboarding_documents.py tests/arv2/fixtures/exa_agent_overview_insight_health.json tests/arv2/test_onboarding_documents.py
git commit -m "feat(arv2): onboarding document mappers — KnowledgeDocument with YAML front matter, fixed-heading bodies, grounding→sources, catalog per-product provenance; pyyaml dependency"
```

---

### Task 5: Guards, README, close-out

**Files:**
- Modify: `tests/arv2/test_import_guard.py:129-175`
- Modify: `platform/api/clue_api/arv2/README.md`
- Create: `_memory/2026-09-07-arv2-onboarding-o2-exa-agent-surface.md`

- [ ] **Step 1: Extend the cost-provision guard**

In `test_every_client_return_type_carries_the_cost_of_the_request_behind_it`, add to the imports `from clue_api.arv2.exa_client import ExaAgentRun` (extend the existing `exa_client` import line) and `from clue_api.arv2.onboarding_documents import KnowledgeDocument`, and add `ExaAgentRun,` and `KnowledgeDocument,` to the `return_types` tuple.

Run: `uv run pytest tests/arv2/test_import_guard.py -v`
Expected: PASS (the guard walks the package AST too; the new modules import only `clue_api.arv2` and `yaml`, which is neither an internal prefix nor a forbidden SDK root).

- [ ] **Step 2: Document the surface in the README**

Add under "The six provider clients" a row: `| exa_client.py::ExaClient.agent_run | Exa Agent (/agent/runs) — async deep research: create, poll every 4 s, settle on the completed body; fixed-effort prices reserved on the create leg; failures/timeouts returned, never raised. |`

Add a section "Onboarding templates and mappers (O2)":

```markdown
## Onboarding templates and mappers (O2)

`onboarding_requests.py` holds the fixed request templates of ARV2-ONBOARDING-PLAN.md §4 —
company overview (contract-verbatim, live-validated), customer reviews, per-product research
(Agent requests) and persona evidence (a `/search` deep-reasoning request within the depth-2 /
ten-property limits). Behaviour is in the system prompt, shape in the schema; the driver never
authors a schema.

`onboarding_documents.py` turns a response into a `KnowledgeDocument` (YAML front matter = the
machine contract; markdown body under fixed headings; `not_found` always rendered). The mappers
are pure, so `KnowledgeDocument.cost` is the settling call's `CallCost` when built from a call and
`None` otherwise — the guard's documented exception.

The Agent surface is synchronous like the rest of R1: the onboarding driver (O3) calls
`agent_run` through `asyncio.to_thread`, one `ProviderCaller` per worker task.
```

- [ ] **Step 3: Run the whole ARV2 suite**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2 -v` then `make check`
Expected: green; the live tests run with keys present and skip without. Record the Agent live run's cost and wall time.

- [ ] **Step 4: Memory note and commit**

```markdown
# 2026-09-07 — ARV2 onboarding O2: Exa Agent surface, templates, mappers

Plan: docs/superpowers/plans/2026-09-07-arv2-onboarding-o2-exa-agent-surface.md.

- `ExaClient.agent_run` (create → poll → settle; Bearer auth; effort price reserved on create;
  metered on the completed body; failed/cancelled/timed_out returned, never raised).
- `onboarding_requests.py`: overview (contract-verbatim), reviews, per-product, persona evidence.
- `onboarding_documents.py`: KnowledgeDocument + four mappers; fixture = the 2026-09-07 sample run.
- Live: `low`-effort overview run — cost $<x>, <n> polls, <s> s; status completed.
- Guards: import guard + cost provision extended; README updated; pyyaml added to clue-api.
- Not done here (by design): settings (O1), the driver and artifact persistence (O3), the evidence tool registration (O4).
```

```bash
git add tests/arv2/test_import_guard.py platform/api/clue_api/arv2/README.md _memory/2026-09-07-arv2-onboarding-o2-exa-agent-surface.md _memory/README.md
git commit -m "chore(arv2): O2 close-out — cost-provision guard covers ExaAgentRun/KnowledgeDocument, README documents the Agent surface and mappers, memory note"
```

Hand the branch name, the note, and the live-test output to Aryan. Do not push.
