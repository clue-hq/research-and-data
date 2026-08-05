# M8D R3 — Shared `create_agent()` runtime acceptance

> **Status:** accepted for R3 on 2026-08-06.
>
> **Scope:** shared account/contact/facet agent construction and execution, exact runtime context,
> tool authorization and journaling, Postgres checkpoints, bounded facets, typed finalization,
> and the R2 driver adapter. R4 provider tools, R5 research behavior, and production cutover remain
> uncomposed.

## 1. One honest entity-agent runtime

`clue_agents.entity_research_runtime.EntityResearchAgentFactory` is the single constructor for
account, contact, and bounded facet units. Its construction path is:

```python
create_agent(
    model=model,
    tools=effective_tools,
    system_prompt=resolved_prompt,
    middleware=middleware,
    response_format=ResearchFinalizationProposal,
    checkpointer=checkpointer,
)
```

The module imports `langchain.agents.create_agent` and has no dependency on Deep Agents. The
Head-of-ABM's separate `DeepAgentTurnRuntime` was not changed; this slice does not confuse a
platform deepagent with a leased entity worker.

Executable tests construct and run all three roles through this factory. The facet role uses a
fresh child checkpoint thread derived from its exact parent job, facet key, and child ordinal.

## 2. Exact construction authority

Each invocation freezes and validates:

- role and subject axis;
- job, research run, entity, parent account, workspace, project, product, and project-run scope;
- exact selection, directive digest, admitted fields/sources/questions/facets/channels, and policy
  and approval references;
- current state digest and job/run budget observation;
- profile, prompt, and skill reference, version, digest, and resolved body;
- exact model policy and task-instruction digest;
- exact semantic tool names, versions, and input-schema digests; and
- runtime, model-round, tool-call, parallelism, and zero-yield limits.

The resolved system prompt contains the pinned role profile, prompt, skills, and exact immutable
context manifest. Resource bodies must match their pins before construction. Account/contact
bindings equal the complete R0 tool surface;
facet bindings are a strict non-empty subset and cannot include delegation, terminal finalizers,
or contact-channel operations.

## 3. Governed execution and history

The runtime middleware enforces the exact model-visible allowlist on every round. Before a
semantic tool handler can execute, it durably appends the tool-call identity, name, version,
arguments, and input digest, then calls the mandatory engine-owned admission guard. Consequently,
an R4 provider tool cannot dispatch before its causative journal event.

Multiple tool calls from one model message execute through LangGraph's concurrent tool node only
after the guard admits the complete batch and the runtime cap. Tests prove two independent calls
overlap in execution and that both observe their durable start events first.

Model inputs/outputs and tool starts/completions/failures are append-only events. The Postgres
migration adds immutable turn construction records plus ordered event history and tool-causation
indexes; update/delete triggers reject mutation.

## 4. Checkpoint, wait, replay, and finalization

Production uses `AsyncPostgresSaver` through `PostgresEntityResearchCheckpointers`. The runtime:

- resumes the exact thread instead of constructing a second fleet;
- converts a governed `EntityResearchExternalWait` into an exact wait/checkpoint/state receipt;
- cancels work when stop or lease authority is lost;
- limits model rounds, tool calls, parallel calls, runtime, and exposes mandatory budget/yield
  admission through the engine guard; and
- treats ordinary graph termination as non-authoritative.

Account/contact success requires a typed `ResearchFinalizationProposal` for the exact current
entity/state and an independently accepted `ResearchFinalizationReceipt`. Facet output is typed
but cannot acquire terminal authority over its parent job. The R2 adapter returns only R2's
`WAITING_EXTERNAL` or receipt-backed `FINALIZED` disposition.

A fresh runtime plus fresh Postgres saver replays a completed checkpoint without another model
call. The exact construction row is idempotent; changing authority under an existing turn id fails
closed.

## 5. Verification evidence

Focused executable gate:

```bash
.venv/bin/pytest -q \
  tests/agents/test_entity_research_runtime_r3.py \
  tests/unit/core/test_entity_research_r0_contracts.py \
  tests/fleet/test_entity_research_r2.py \
  tests/api/test_m8d_r1_entity_research_quarantine.py
```

Result: green.

Real Postgres gate on a fresh isolated database:

```bash
alembic upgrade head
pytest -q tests/fleet/test_entity_research_r2_db.py \
  tests/agents/test_entity_research_runtime_r3_db.py
alembic downgrade 022b1154b3aa
alembic upgrade ac980e12eb5e
```

Result: six combined R2/R3 database cases passed; R3 up/down/up passed. The test proves durable
construction/history rows, append-only enforcement, LangGraph checkpoint rows, cold replay, typed
engine acceptance, and the R2 driver mapping.

Additional gates:

- Ruff passed on all R3 source, migration, and tests.
- Mypy passed on all R3 source and tests.
- Import-linter kept all 24 dependency contracts.
- The wider agent/R0/R1/R2 regression selection passed; database-only tests were run separately
  against the isolated database.

No provider credential, provider endpoint, or paid call was used: those belong to R4 and later
live acceptance. Production still omits the entity-research handler, so R1 continues to fail new
entity research loudly instead of falling back to legacy orchestration.

## 6. Next boundary

R4 supplies provider-neutral account/contact semantic tools backed by existing provider, artifact,
claim, verification, cost, and operation services. It must preserve R3's journal-before-dispatch
ordering and return the complete persisted result projection before any agent observes success.
