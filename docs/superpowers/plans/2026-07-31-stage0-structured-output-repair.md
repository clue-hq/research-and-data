# Stage-0 structured-output repair — Phase A transport blockers + trial acceptance criteria

**Branch:** `platform/clue-trial` (work directly on this branch; it is the trial branch).
**Context:** the manual Stage-0 CLI trial fails through a three-defect chain, and even with
transport fixed the trial's own acceptance criteria (durable routing, grounded ICP, product gate,
honesty) are unmet. Verified failure chain and test intent are recorded in
`_memory/2026-07-31-stage0-structured-output-failure-chain.md` — implementers should read that
file first for the diagnosis.

## Global constraints

- **Never push. Local commits only. No AI/Claude attribution in commit messages** (no
  Co-Authored-By trailers, no "Generated with" footers).
- Do not touch the untracked `.claude/`, `.codex/`, or `docs/architecture/clue-hq-research-model-surface.md`.
- Do not run repo-wide reformatting; run Ruff/format/mypy on changed files only. `make check`
  is known to stop on pre-existing unrelated formatting debt — do not "fix" those files.
- **Frozen core (`libs/clue-core`) must not change** in this plan. Provider compatibility is a
  gateway-adapter concern.
- Fail-closed philosophy: a violation should be structurally unrepresentable or rejected loudly;
  never silently coerced. Empty/typed-not-ready is a correct output; fabricated success is the
  failure mode.
- DB-backed tests: create a throwaway per-task database (e.g. via the pattern used in
  `tests/api/test_stage0_trial.py`); never use the shared local `clue` database.
- **No live model calls, no OpenRouter spend, no Sumble calls from implementer agents.** All
  live verification is controller-owned and happens after the plan completes.
- TDD: write the failing test first, then the fix. Every task lists its required regression tests.
- Alembic: if (and only if) a migration is needed, use `alembic revision -m "<slug>"` (random hash
  ids), single head, reversible. No task in this plan is expected to need one.

## Task 1 — Provider-subset tool-schema transform at the gateway + fail-closed schema gate

**Defect:** a real OpenRouter Responses request for the Head-of-ABM agent fails HTTP 400:
`Invalid JSON schema: regex lookaround is not supported … manifest.cost_cents … param: tools`.
`CostCents = Annotated[Decimal, Ge(0)]` (`libs/clue-core/clue_core/primitives.py:66`) is used by
`SourceManifestDraft.cost_cents` (`subsystems/research/clue_research/proposals/models.py:111`),
which is nested in the `propose_source@1` tool input (`platform/api/clue_api/proposal_tools.py`).
Pydantic emits a `pattern` containing a negative lookahead (`^(?!^[-+.]*$)…`) for Decimal fields.
All bound tool schemas are sent together in every agent request
(`libs/clue-gateway/clue_gateway/agent_model.py:74`, `convert_to_openai_tool`), so one
incompatible schema blocks every turn.

**Design decision (pinned):** do NOT change `CostCents` or any frozen-core type — `cost_cents`
legitimately carries fractional cents from token pricing elsewhere. Fix at the adapter seam:

1. In `libs/clue-gateway/clue_gateway/agent_model.py`, after `convert_to_openai_tool`, pass every
   generated tool schema through a deterministic provider-compatibility transform before it is
   bound/sent. Minimum behavior: recursively walk the schema; for any `pattern` string containing
   constructs the OpenAI/OpenRouter Responses subset rejects (lookarounds `(?=`, `(?!`, `(?<=`,
   `(?<!`; backreferences `\1`-style), drop the `pattern` key (local Pydantic validation remains
   authoritative — the provider schema is guidance, the platform re-validates arguments on the way
   in, so dropping a pattern loosens nothing durable). Preserve everything else byte-for-byte.
   Keep the transform pure and unit-testable (a module-level function, not a closure).
2. Add a fail-closed gate test (suggested: `tests/architecture/test_provider_tool_schema_gate.py`)
   that, for **every role's active profile** (resolve via
   `platform/api/clue_api/agent_registry_wiring.py` / `toolbelt_wiring.build_toolbelt` with
   `Settings(_env_file=None)`, the pattern used in the diagnostic walker), converts every bound
   tool through the real adapter transform and asserts the *transformed* output contains no
   unsupported constructs (no lookaround/backreference patterns anywhere, recursively — check
   every string under any `pattern` key, plus assert top-level `parameters.type == "object"`).
   The gate must fail if someone adds a new tool whose transformed schema is still incompatible.
3. Regression: a unit test that feeds a model with a `Decimal` field (reuse `SourceManifestDraft`
   or `ProposeSourceInput` directly) through the conversion+transform and asserts the emitted
   schema has no lookaround pattern, while `model_validate` still rejects a negative value locally.

**Out of scope:** `strict: true` function tools (deferred, post-acceptance); any change to
`proposals/models.py` types.

**Verify:** new tests pass; existing `tests/gateway/test_agent_model.py` stays green; Ruff+mypy
on changed files.

## Task 2 — JSON-normalize governed tool arguments before plan construction

**Defect:** with the schema 400 bypassed, Terra returned a semantically correct
`record_interview_answer` call, but the governed wrapper failed it with
`arguments.statements.list.0: input was not a valid JSON value`. Cause:
`platform/api/clue_api/agent_runtime_wiring.py:505` passes LangChain-validated kwargs — which
contain nested Pydantic model instances (e.g. `InterviewStatement`) — directly into
`PlanToolStep.arguments`, whose type admits JSON values only. This breaks every governed tool
with nested models, not just Stage 0.

**Design decision (pinned):** normalize at that single seam in `_governed_tool.invoke`: convert
`kwargs` to pure JSON values before building `PlanToolStep` (e.g.
`pydantic_core.to_jsonable_python(kwargs)`, or re-validate through the tool's args model and
`model_dump(mode="json")` — implementer picks whichever is correct given `_with_trusted_runtime`'s
field filtering, and documents why in the report). The executor's own re-validation of arguments
into `descriptor.input_model` must keep working (JSON representation is accepted; `_ModelInput`
uses `strict=False`).

**Required regression matrix** (new tests near the existing runtime-wiring tests): a governed
tool whose input model contains — a list of nested models, a nested enum, a UUID field, a
Decimal field, a datetime field — invoked through the real `StructuredTool` path, asserting the
constructed `PlanToolStep.arguments` validates as JSON and the executor receives
equivalent values. At minimum one test must reproduce the exact production failure: the real
`RecordInterviewAnswerInput` with two `InterviewStatement` items through the wrapper.

**Verify:** new matrix passes; existing agent-runtime and stage0 suites stay green.

## Task 3 — Finalize-contract parity + model-visible finalize feedback

**Defect:** Terra finalized with `status=awaiting_input` + `failure_code=…`.
`ModelFinalizeRequest` (`platform/api/clue_api/agent_runtime_wiring.py:233-246`) accepts that
combination; the durable `AgentFinalizeEnvelope.terminal_shape_is_honest`
(`platform/agents/clue_agents/contracts.py:860-877`) rejects it. The turn died as
`missing_finalize` with no feedback to the model. Class of bug: the model-facing contract is
looser than the durable contract.

**Design decision (pinned):**

1. Make `ModelFinalizeRequest` enforce the same shape rules as the envelope via a
   `model_validator(mode="after")`: `failure_code` required iff `status == FAILED`; forbidden
   otherwise. (Do not attempt a top-level discriminated union in the tool JSON schema — Responses
   function `parameters` must stay a plain object schema. Encode the rules in the validator and in
   the finalize tool's description text so the model sees them.)
2. Mirror (or delegate to) the envelope's non-terminal rule where it can be honestly checked at
   the model boundary; keep the existing behavior where an omitted `next_actions` on
   `awaiting_input` is repaired from the durable user message (that repair already exists — do not
   regress it; find it in the finalize path and cover it with a test if uncovered).
3. When finalize-argument validation OR envelope construction fails, the model must receive the
   validation error as a tool error/result it can react to (LangChain returns
   `ValidationError` on `args_schema` as a tool message when configured — implementer verifies
   how `_finalize_tool` (`agent_runtime_wiring.py:702`) and the runtime loop
   (`platform/agents/clue_agents/runtime.py`, see the bounded finalize-only recovery around
   lines 110-131) surface it, and ensures at least one bounded corrective retry happens instead of
   the turn silently ending `missing_finalize`). A second failure still fails closed.

**Required tests:** unit tests for the validator (all four statuses × failure_code
combinations); a runtime-level test where the scripted model first sends the invalid
`awaiting_input`+`failure_code` finalize, receives the validation feedback, then sends a valid
one, and the turn commits; a test that two consecutive invalid finalizations still end
`missing_finalize` (fail-closed preserved).

**Verify:** new tests pass; `tests/agents/test_runtime.py` and stage0 suites stay green.

## Task 4 — Ground ICP synthesis in the conversation + product gate + typed not-ready

**Defects (from trial `trial-65be885b9b0fe5ad` verdict):**
- `synthesize_icps` (`subsystems/research/clue_research/stage0/icp_synthesis.py:97`) reads only
  versioned Client-KB claims. Interview statements routed as `project_state` (see
  `subsystems/research/clue_research/stage0/interview.py`, `route_interview_answer`,
  `InterviewRoute.PROJECT_STATE`) are invisible to synthesis — so the user's targeting input
  cannot ground the ICP even when routing works.
- With empty evidence, synthesis emits the generic `_floor_proposal` ("Baseline undifferentiated
  B2B account") as if it were a real proposal, with empty `justifying_claim_ids`.
- The trial allowed `/synthesize-icp` with `project.product_id` unconfirmed (`null`), while
  `confirm_icp_proposal` (`platform/api/clue_api/stage0_trial.py:888-897`) does enforce it.

**Design decisions (pinned):**

1. Extend the synthesis seam so project-scoped interview/targeting statements are first-class
   evidence alongside KB claims: add an explicit, typed input (e.g. an optional
   `project_statements` argument or a small reader protocol) to `_synthesize`/`synthesize_icps*`;
   the trial call site (`stage0_trial.py:860-880`) passes the project's durable `project_state`
   statements. Proposal lineage must reference both claim ids and statement ids (extend the
   lineage/justification shape accordingly — keep it reference-only, no prose copies).
2. Replace the silent floor fallback with a **typed not-ready outcome** when there is no grounding
   evidence (no KB claims AND no project statements): `ICPSynthesisResult` (line 82) gains an
   explicit readiness/reason surface (e.g. `status: grounded | floor_only` + reason codes), the
   trial surfaces it to the CLI as "not ready: <missing evidence>" instead of presenting the
   floor proposal as a normal numbered proposal. Existing non-trial callers keep a complete
   proposal available (do not break the "always ≥1 proposal" contract for production paths —
   the floor still exists, it just cannot masquerade as grounded; update callers/tests
   deliberately).
3. Enforce the product-confirmation gate in `Stage0Trial.synthesize_icp_proposals` exactly as
   `confirm_icp_proposal` does (`project.product_id == self.state.product_id` after
   `confirm_project_product`), with a typed error the CLI renders as "run /confirm-product first".

**Required tests:** synthesis with statements-only evidence produces a grounded proposal citing
statement ids; synthesis with zero evidence returns the typed not-ready outcome (and the trial
endpoint renders it, not a generic proposal); `/synthesize-icp` before product confirmation is
rejected with the typed error; existing synthesis tests updated deliberately, not deleted.
DB-backed where the real tables are involved.

**Verify:** focused stage0 + icp_synthesis + trial HTTP suites green.

## Task 5 — Turn-level routing honesty + per-turn readiness recompute

**Defect:** across 7 turns the GPT-4.1 agent said "this is now captured as project state" while
the database shows zero interview statements, zero plans, zero tool results. Prose claimed a
durable action that never happened. Also `readiness_decisions` stayed empty for the whole trial.

**Design decisions (pinned):**

1. Deterministic honesty — not language policing: use the existing `CompletionGuard` seam
   (`agent_runtime_wiring.py:249`, invoked at `:717-719`) to reject a Stage-0 finalize with
   status `completed`/`awaiting_input` when the turn contains a substantive user message but
   **zero** durable routing receipts (no `record_interview_answer` receipt for this turn). The
   rejection message must instruct the model to route the input — including explicitly routing
   non-material content via the existing `InterviewRoute.UNMAPPED` — and flows back through
   Task 3's feedback path (one bounded corrective retry, then fail closed). "Substantive" is
   defined structurally, not semantically: any user turn except pure CLI commands; when in doubt
   the model can always satisfy the guard with an UNMAPPED route, so there is no free-text
   judgment in the guard itself.
2. Confirm `record_interview_answer` / `RecordInterviewAnswerInput` supports an
   explicit "nothing material" statement via `UNMAPPED` with a reason; if the tool currently
   requires ≥1 statement of another route or forbids empty values for UNMAPPED, relax exactly
   that (UNMAPPED requires only `route_key` + quoted span).
3. After every successful `route_interview_answer` with ≥1 non-UNMAPPED statement, recompute and
   persist the deterministic Stage-0 readiness decision (find the existing C4 readiness
   evaluator used elsewhere in stage0; wire it at the trial/turn seam so `readiness_decisions`
   is non-empty after material turns). Reuse the existing evaluator — do not write a second
   readiness implementation.
4. Update the Stage-0 skill/prompt text (`platform/agents/catalog/skills/stage0-interview-*/`,
   whichever version the active Head-of-ABM profile pins) so the agent is told: never claim
   information was recorded except by reporting the routing receipt outcome. If changing pinned
   catalog resources would mutate an immutable profile version's manifest hash, publish a new
   profile version instead (follow the existing pattern from the C7.7 and Terra profile bumps).

**Required tests:** guard rejects a no-receipt finalize and the scripted model recovers by
routing then finalizing (turn commits); a pure-command turn does not trip the guard; UNMAPPED
satisfies the guard; readiness decision row exists after a material routed turn; two invalid
attempts still fail closed.

**Verify:** stage0 governed-input, runtime, and trial suites green.

## Task 6 — CLI multiline input

**Defect:** pasting a multi-line product brief into `scripts/clue_trial.py` (plain `input()` at
line ~303) splits it into separate turns → repeated questions, concatenated fragments, wasted
model calls.

**Design decision (pinned):** keep it simple and explicit — add two mechanisms to the chat loop:
`/paste` (read lines until a line containing only `.`, send as one message) and `/file PATH`
(send the file's contents as one message, path validated, size-capped ~64KB to match
`ModelFinalizeRequest`/turn limits). Update the CLI help line and the runbook
(`docs/runbooks/` trial doc and/or `scripts/README.md`). No TUI framework, no bracketed-paste
detection.

**Required tests:** unit test for the paste/file assembly (pure function extracted from the
loop); manual verification instructions in the report. The CLI must remain HTTP-only (no new
business imports — keep the existing import-boundary test green).

## Acceptance (controller-owned, after all tasks)

Scripted Aura/neurosurgery re-run through the live server (OpenRouter spend authorized; **no
Sumble spend**): statements + KB claims + readiness visible in `report.json`;
`/confirm-product` enforced; ICP proposal names neurosurgery/US/personas with populated
justifications; quit/resume intact; no duplicate writes. Sumble 3-credit canary is a separate
follow-up gate, run by the user.
