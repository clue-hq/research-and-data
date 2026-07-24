# Phase C1 — Coverage Ledger and Goal Evaluation

**Status:** implemented and integrated on `platform/workspace-restructure` (2026-07-24)

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
- whether an independent evaluator thinks a meaningful gap remains;
- whether another caller-planned round is permitted;
- why an unfilled field is terminally empty.

The goal judge is a bounded LLM leaf call that independently evaluates whether the requested gaps
still appear meaningful for the research goal. It returns typed advisory warnings and a sufficiency
recommendation. It does **not** choose gaps, tools, sources, or strategies; drive the research loop;
or override budgets, policy gates, trust tiers, evidence requirements, or deterministic stop
conditions.

The governed research agent introduced in C6 is the primary planner. C1 lands first so the ledger,
one-round tool, evaluator, and enforcement machinery are independently testable before that agent is
connected.

---

## 2. Scope

### Included

1. `coverage_attempt` and `coverage_decision` migrations and repositories.
2. Typed attempt, decision, strategy, gap, and snapshot models.
3. An attempt-recorder seam around the existing waterfall/worker paths.
4. A deterministic round enforcement controller.
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

- a non-terminal decision may name one engine-permitted strategy as an advisory fallback;
- a terminal decision must have a terminal status and no next strategy;
- decisions are idempotent on `(run_id, entity, field, tier, round)`;
- only one terminal decision may exist per `(run_id, entity, field, tier)`;
- a filled claim produces `FILLED`, even if other attempted sources missed;
- terminal reasons are safe for direct user display;
- `next_strategy_key` does not bind the caller: the governed agent may choose any strategy permitted
  by the versioned transition policy;
- a run cannot be called complete while a planned unfilled field has neither an engine-permitted
  next strategy nor a terminal decision.

### 3.3 No second claim state

The ledger records attempts and decisions. Claim values remain exclusively in the claim store.
Filled status is supported by claim ids; it never copies claim bodies into coverage rows.

---

## 4. Agent, controller, and goal evaluator

### 4.0 Operational loop and authority

```text
governed research agent
  reads goal + evidence + coverage ledger
  chooses the next gaps and strategy
           |
           v
research_account_gaps
  validates the request
  runs one bounded research round
  stores attempts, costs, claims, and stop reasons
           |
           v
coverage evaluator / goal judge
  independently checks whether meaningful gaps remain
  returns typed advisory warnings/recommendations only
           |
           v
engine
  validates evidence, budget, rounds, policy, and idempotency
  records the authoritative durable state
           |
           v
agent
  continues, changes approach, delegates a facet, or proposes stopping
```

| Decision | Owner |
|---|---|
| What matters for this account/project | governed research agent |
| Which gap, tool, source, or strategy to try | governed research agent |
| Whether the result appears sufficient for the goal | agent, challenged by the evaluator |
| Whether another round is legally/financially permitted | engine |
| Whether `filled` has real promotable evidence | engine |
| Whether a hard terminal condition has been reached | engine |
| Human steering or “just go” | human |

Before C6 exists, the explicit tool caller supplies the gap set and optional strategy hint. A
deterministic default is allowed only as a compatibility/test fallback when no hint is supplied; it
does not transfer planning authority to the evaluator.

### 4.1 Deterministic controller authority

The controller owns:

- maximum rounds by tier;
- validation against the strategy transition graph;
- allowed source families;
- budget headroom;
- marginal-yield floor;
- policy blocks;
- idempotency/replay;
- terminal-state selection.

These are versioned config, not prompt-controlled values.

The controller does not decide what matters or ask the evaluator what to research. It validates the
agent/caller-selected gaps and strategy against these constraints.

### 4.2 Goal-evaluator input/output

Input is a compact, target-locked bundle:

```text
run/recon/project/account/entity refs
planned field keys
current claim refs and verification summaries
prior attempt refs + typed outcomes
remaining budget and hard round cap
the strategy attempted this round
```

Output uses tool-strategy structured parsing:

```python
class GoalJudgeAssessment(BaseModel):
    field_key: FieldKey
    meaningful_gap_remaining: bool
    recommendation: Literal["continue", "reconsider", "propose_stop"]
    warning_codes: tuple[GoalJudgeWarning, ...]
    rationale: str

class GoalJudgeResult(BaseModel):
    assessments: tuple[GoalJudgeAssessment, ...]
    sufficient_for_goal: bool
```

The controller rejects:

- assessments for fields outside the caller-requested gap set;
- unknown warning or recommendation codes;
- duplicate or missing field assessments;
- malformed/injected output.

Evaluator output is advisory. The engine may map a validated assessment to a fixed, display-safe
advisory reason code in the durable decision; raw evaluator rationale is not authoritative durable
state. The evaluator cannot select `next_strategy_key`, declare `filled`, create a terminal state,
or authorize spend. Invalid evaluator output fails closed as evaluator input: the engine does not
treat it as evidence of sufficiency and continues to apply only deterministic policy. It does not
terminally stop an otherwise permitted agent-planned loop.

### 4.3 Different-strategy guarantee

A caller-selected retry must change at least one stable strategy dimension:

- source family;
- query scope/shape;
- modality;
- worker/facet route.

Changing free-text rationale while calling the same source/query is not a new strategy and must
fail validation.

### 4.4 Future evaluator placement flag (C6)

The current C1 implementation places the advisory coverage evaluator behind a bounded
`LLMGateway` leaf call. That location exists so C1's typed assessment and enforcement boundaries
are executable and testable before the governed research agent exists; it is **not** a permanent
ownership ruling.

Product direction is that this advisory reasoning will probably become part of the platform
deepagent or its governed research subagent in C6. C6 must make that placement decision explicitly:

- there must be one evaluator owner, not parallel engine-side and agent-side evaluators;
- if evaluation moves into the agent runtime, the standalone C1 evaluator call is removed or
  disabled rather than duplicated;
- the agent remains the planner and the evaluator remains advisory;
- engine ownership of promotable evidence, budget, policy, idempotency, and hard terminal states
  does not move;
- the append-only coverage attempt/decision ledger and reference-only tool/projection contracts
  remain stable;
- malformed advice and `propose_stop` remain incapable of directly creating a terminal state;
- C6 must define how agent-local advice is journaled or projected without turning it into
  authoritative factual or execution state.

Until C6 closes this decision, the bounded C1 leaf call is the implemented contract.

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

Implement the C0-frozen `research_account_gaps` tool. It runs one caller-planned,
controller-validated bounded round; it does not recursively run until satisfaction inside a single
invocation. `gap_fields` and `strategy_hint` are caller/agent planning inputs. The engine may reject
them but the evaluator may not supply or replace them.

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
14. malformed/injected goal-evaluator output fails closed without planning or terminally stopping
    an otherwise permitted retry;
15. an agent/caller-selected strategy is accepted when it is one of the engine-permitted
    transitions, even when it differs from the engine's advisory fallback;
16. evaluator output contains no executable field/source/strategy choice and cannot create a
    terminal decision;
17. existing discovery `CoverageReport` behavior is unchanged.

Run `make check`, fresh-schema DB tests, immediate DB rerun, `alembic heads`, and `make db-smoke`.

---

## 9. Exit gate

C1 is complete when a user can inspect every research gap and see its full attempt history, an
agent/caller-planned retry genuinely changes strategy, evaluator advice cannot drive the loop, all
hard stops are deterministic, replay is free, and no completed run hides an unexplained empty
field.
