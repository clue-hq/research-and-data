# Phase C1 — Coverage Ledger and Goal-Judge Loop

**Status:** ready for implementation

**Parent:** [`PC-phase-c-agentic-layer.md`](./PC-phase-c-agentic-layer.md)

**Shared contracts:** [`PC-C0-step4-contract-freeze.md`](./PC-C0-step4-contract-freeze.md)

**Requirement:** harness REQ-04

---

## 1. Outcome

C1 makes failed research effort durable, retryable, bounded, and visible.

For every planned field, the platform can answer:

- what was tried;
- which strategy/source family was used;
- what it cost;
- what claims it produced;
- why it stopped;
- whether another round is useful and permitted;
- why an unfilled field is terminally empty.

The goal judge is a bounded LLM leaf call that proposes a typed next-gap set. It is not an agent,
does not own tools, and cannot override budgets, policy gates, trust tiers, or deterministic stop
conditions.

---

## 2. Scope

### Included

1. `coverage_attempt` and `coverage_decision` migrations and repositories.
2. Typed attempt, decision, strategy, gap, and snapshot models.
3. An attempt-recorder seam around the existing waterfall/worker paths.
4. A deterministic round controller.
5. A goal-judge leaf call through `LLMGateway`.
6. `research_account_gaps` tool implementation.
7. `research_coverage` and `research_attempt_history` projections.
8. Golden/eval fixtures for useful retries and honest stopping.
9. Pre-spend and born-binding regression coverage for new strategies.

### Excluded

- proposal/promotion state;
- generic web-source registration;
- upload ingestion;
- Stage-0 onboarding/interview/readiness;
- the platform deepagent or a per-account governed worker agent;
- dossier rendering (C7 consumes C1 projections).

---

## 3. Durable model

### 3.1 `coverage_attempt`

Append-only columns:

```text
id                         uuid PK
workspace_id               text, required
run_id                     uuid, required
project_run_id             uuid, nullable before project creation
entity_id                  uuid, required
entity_type                entity_type, required
field_key                  text, required
tier                       text, required
round                      integer >= 1
strategy_key               text, required
source_family              text, nullable
outcome                    research_attempt_outcome
stop_reason                text, required
reason_detail              text, nullable
cost_cents                 numeric >= 0
claim_refs_json            jsonb array of ClaimId strings
quality_mode               text, nullable
created_at                 timestamptz
```

Natural idempotency key:

```text
(run_id, entity_id, field_key, tier, round, strategy_key)
```

`run_id` is the existing generic research-run id stamped on claims. Project/account research also
records its outer `project_run_id`; onboarding recon leaves that outer id null. This lets C4 reuse
the coverage ledger without making C1 depend on C4's `recon_run` table.

`strategy_key` is an engine-defined stable identifier, not arbitrary prompt prose. Examples:
`official_site_exact`, `registry_exact`, `tier3_web_widened`, `facet_worker_role_context`.

### 3.2 `coverage_decision`

Append-only columns:

```text
id                         uuid PK
workspace_id               text, required
run_id                     uuid, required
project_run_id             uuid, nullable before project creation
entity_id                  uuid, required
entity_type                entity_type, required
field_key                  text, required
tier                       text, required
round                      integer >= 1
terminal_status            research_terminal_status, nullable
next_strategy_key          text, nullable
reason_code                text, required
reason_detail              text, required
attempt_refs_json          jsonb array
claim_refs_json            jsonb array
judge_model                text, nullable
judge_prompt_version       text, nullable
created_at                 timestamptz
```

Rules:

- a non-terminal decision may name one next strategy;
- a terminal decision must have a terminal status and no next strategy;
- decisions are idempotent on `(run_id, entity, field, tier, round)`;
- only one terminal decision may exist per `(run_id, entity, field, tier)`;
- a filled claim produces `FILLED`, even if other attempted sources missed;
- terminal reasons are safe for direct user display;
- a run cannot be called complete while a planned unfilled field has neither a permitted next
  strategy nor a terminal decision.

### 3.3 No second claim state

The ledger records attempts and decisions. Claim values remain exclusively in the claim store.
Filled status is supported by claim ids; it never copies claim bodies into coverage rows.

---

## 4. Controller and goal judge

### 4.1 Deterministic controller authority

The controller owns:

- maximum rounds by tier;
- strategy transition graph;
- allowed source families;
- budget headroom;
- marginal-yield floor;
- policy blocks;
- idempotency/replay;
- terminal-state selection.

These are versioned config, not prompt-controlled values.

### 4.2 Goal-judge input/output

Input is a compact, target-locked bundle:

```text
run/recon/project/account/entity refs
planned field keys
current claim refs and verification summaries
prior attempt refs + typed outcomes
remaining budget and hard round cap
allowed strategy keys
```

Output uses tool-strategy structured parsing:

```python
class GoalJudgeGap(BaseModel):
    field_key: FieldKey
    recommended_strategy_key: str | None
    rationale: str
    terminal_recommendation: ResearchTerminalStatus | None

class GoalJudgeResult(BaseModel):
    gaps: tuple[GoalJudgeGap, ...]
    sufficient_for_goal: bool
```

The controller rejects:

- unplanned fields unless they route to C2 as proposals;
- unknown strategy keys;
- a recommendation beyond the hard round/budget/policy cap;
- “filled” without a supporting promotable claim;
- a terminal status inconsistent with durable attempts.

### 4.3 Different-strategy guarantee

A retry must change at least one stable strategy dimension:

- source family;
- query scope/shape;
- modality;
- worker/facet route.

Changing free-text rationale while calling the same source/query is not a new strategy and must
fail validation.

---

## 5. Existing seams reused

- `compute_gap_fields` remains the initial deterministic gap detector.
- `resolve_field` remains the only waterfall engine.
- `StopReason` maps into attempt outcomes; it is not replaced.
- `SourceGate` remains the pre-spend hook.
- `ClaimTagger` remains the born-governance hook.
- `BudgetEngine`/`BudgetTracker` remain budget authorities.
- `LLMGateway` remains the only model boundary.
- `account_run.references_index` remains the account worker's reference index.

C1 may add an attempt-recorder protocol to `clue_core` and optional hooks to `resolve_field`, but
must not fork the waterfall.

---

## 6. Tool and projections

Implement the C0-frozen `research_account_gaps` tool. It runs one controller-approved bounded round;
it does not recursively run until satisfaction inside a single invocation.

This one-round boundary provides:

- deterministic cost estimation;
- crash/replay isolation;
- visible progress;
- a future C6 governed worker-agent decision point.

Implement:

- `research_coverage(run_id, project_run_id?, entity_id?)`;
- `research_attempt_history(run_id, entity_id, field_key)`.

Projection responses carry ids, costs, codes, and display-safe reasons. Claim values are resolved
through existing claim/narrative surfaces.

---

## 7. Owned and forbidden surfaces

### Owns

- `subsystems/research/clue_research/coverage/**`;
- C1 migrations;
- new optional coverage hooks in waterfall/worker code;
- `platform/api/clue_api/coverage_tools.py`;
- `platform/projections/clue_projections/research_coverage.py`;
- C1 tests/evals.

### Must not edit/finalize

- proposal/ingestion/Stage-0 stores;
- central toolbelt registry;
- central projections router/exports;
- product/run-entry pins;
- C2–C4 lane packages.

Any shared hook change requires a narrow core contract delta and must preserve existing callers by
defaulting the hook to `None`.

---

## 8. Verification

Required tests:

1. round 1 miss and round 2 distinct strategy;
2. max-round stop;
3. budget stop before provider call;
4. policy-block terminal state;
5. marginal-yield stop;
6. filled state backed by claim refs;
7. completed-round replay produces no new spend/rows;
8. one terminal decision under concurrency;
9. every planned unfilled field receives a display-safe terminal reason;
10. costs reconcile between attempts and the run ledger;
11. foreign-workspace reads/tools fail closed;
12. a tier ≥2 fake provider observes a durable `gate_decision` before its call;
13. a contact retry claim is born with the authoritative binding/use classification;
14. malformed/injected goal-judge output fails closed;
15. existing discovery `CoverageReport` behavior is unchanged.

Run `make check`, fresh-schema DB tests, immediate DB rerun, `alembic heads`, and `make db-smoke`.

---

## 9. Exit gate

C1 is complete when a user can inspect every research gap and see its full attempt history, a
retry genuinely changes strategy, all stops are deterministic, replay is free, and no completed
run hides an unexplained empty field.
