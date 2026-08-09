# 2026-08-09 — Lane D D4: the durable gate substrate + the Option-B kickoff flow

Brief: `docs/specs/FI-lane-D-D4-implementation-brief.md`. Charter §3-P5 under ratified **§6-D3**
(immutable gate + insert-once answer) and **§6-D5** (no estimate tool; one server-derived maximum
spend). Branch `platform/frontend-integration` (worktree *damascus*).
Commits: `3afd47e5` (substrate + flow), `bb1e9cfc` (surface/registry contracts), `69e0efde`
(suites + the two contract findings).

## What shipped

1. **Migration `3caa27516b81`** (chains off D2's `fba208917f89`). `agent_gate` — immutable,
   composite-FK anchored to its thread/project, presenting-turn FK on `agent_turn`'s three-column
   thread anchor, addressee FK to `platform_user`, closed `kind` CHECK, `numeric(20,4)` spend +
   ISO-4217 currency. `agent_gate_answer` — **PK on `gate_id`**, so insert-once is a constraint;
   its turn FK points at `agent_turn_submission` (a gate is answered by the *route*, before the
   worker builds the `agent_turn` half). Both immutable by the shared append-only trigger. Also
   adds the `agent_turn_submission (turn_id, workspace_id)` anchor the answer FK needs.
   **No status column anywhere** — open is the absence of an answer row.
2. **`clue_api/agent_gate.py`** — the substrate (row models, insert/read, derived open/answered,
   `money_text`). Deliberately model-free so the HTTP route can import it and the D2 gateway
   isolation guard stays true.
3. **`clue_api/account_research_estimate.py`** — the launcher's Σ per-account
   `effort_policy.budget_cap_cents` loop (including its human-tier-checkpoint proof) **moved
   verbatim** out of `account_research_fleet_launch.py`. Launcher and gate tool both call it; the
   launcher's exact-match verification is untouched.
4. **`open_directive_confirmation_gate@1`** (`agent_gate_tools.py`, registered through
   `agent_gate_wiring.py` per the chokepoint protocol). Agent-callable. Addressee derived from the
   durable submission of the turn it is answering (`source_turn_ref` served through the PC-C8
   `TRUSTED_TURN_FIELD` seam), amount from the shared computation, digest from the directive.
5. **The structured gate-response turn** in `chat/router.py` — see the ordering note below.
6. **`turn_action.resolve_gate_answer_action`** — a second, stricter resolver; and
   `load_turn_identity` / `resolve_turn_action` now read **either** durable half of a turn's
   identity (submission first).
7. **Surface widening** — `PROJECT_CONVERSATION_SURFACE` stops withholding the launch tools and
   gains the gate tool via **head-of-abm@v23** + **account-deep-steering@v3**. Trial unchanged.
8. **`clue_projections/gates.py`** — gate → answer → confirming turn → launched run, and the
   `open_gate_kinds_for_threads` anti-join that makes `thread_status` serve `approval` /
   `needs-input` for real (wired into the thread listing route).
9. **Trial fix** — `stage0_trial.decide_gate(actor="agent")` → `"human"`.

## The route's ordering (the design worth remembering)

One transaction: advisory xact-lock the gate → validate (scope, kind, addressee, expected digest,
expected amount, not-already-answered-by-a-different-turn) → capture the answer's canonical bytes
as the turn's message → submission → insert-once answer → **only for `approved`** invoke
`confirm_account_research_directive@2` with the ambient `actor_id` and the turn-derived
`action_ref` → dispatch. A confirmation that cannot be applied rolls the whole thing back, so a
transient failure never burns a gate; and the confirm `operation_id` is derived from `(gate, turn)`
so a retry *replays* the confirmation instead of colliding with it.

## Two findings the flow forced (both are real contract changes — review these)

1. **`compose_account_research_directive` gains `allow_draft`** (+ the same flag on
   `ResearchDirectivePin.from_records`). A confirmation gate must price the **draft** it presents,
   and it must use the composition execution uses or the two numbers drift. Pricing-only: every
   execution path leaves it `False`, so "only a confirmed directive executes" is unchanged. This is
   a frozen-`core` contract-delta.
2. **`approval_refs` is de-duplicated in the launcher.** Under Option B the launching action and
   the directive's confirming turn are the *same* act — the user's structured approval confirms the
   direction and is the very turn the deepagent launches from — so `(source_action_ref,
   confirming_turn_ref)` is one receipt twice, which `EntityResearchSelection` rightly refuses.
   The AC's "carries both refs" is met as: both names resolve to the one confirming receipt.

## Known blocker discovered, NOT fixed (needs a decision)

**The C5 recipe ceiling still withholds the kickoff tools.** `recipe0-stage0@5`'s
`stage0_interactions` gate lists 14 tools in `dynamic_tool_allowlist`; `draft_account_research
_directive@2`, `open_directive_confirmation_gate@1` and `launch_account_research@1` are **not**
among them, so an agent-planned call is refused at plan validation (`c5_tool_not_allowed`) even now
that the *surface* grants them. (`get_research_view@1` is already in this position today — granted
on the profile, absent from the recipe — so the mismatch is pre-existing, not new.)

Fixing it needs, together: a `recipe0-stage0-v6.json` with the widened allowlist and
`dynamic_pin_kinds`; new pin resolvers for `research_directive` and `account_research_selection`
(neither kind has one, and the *selection* does not exist until launch, so it can only be an
optional-missing pin); `Stage0StepPinProvider` branches for the three tools; and a one-line bump of
`CONVERSATION_RECIPE_VERSION` — which lives in `conversation_turns.py`, a **D3-owned file**. I did
not touch it. D4's acceptance therefore drives the launch through the launcher with the confirming
turn's `action_ref` (the authority chain, proven end to end) rather than through a model-planned
C5 step.

## Gates

- `db-smoke` up→down→up on a **clean throwaway DB** (`d4_smoke` on `clue-pg-damascus`,
  localhost:**55040**), targeting **my head explicitly** (`alembic upgrade 3caa27516b81`) because
  the two Lane-D heads are still forked — `98a5ddafa21b` is D3's outbox and the orchestrator owns
  the join. DDL + constraints + triggers verified, then the DB was dropped.
- `uv run mypy` clean (611 files). `uv run lint-imports` 25 kept / 0 broken. `ruff check` +
  `ruff format --check` clean on every file this slice touches.
- New suites green: `test_lane_d4_agent_gate_db.py` (13), `test_lane_d4_gate_response_route_db.py`
  (19), `test_lane_d4_option_b_acceptance_db.py` (5) = **37**.
- Regression green: `tests/agents` (188), `tests/architecture`, `tests/api/test_c8_trial_surface`,
  `test_toolbelt_wiring`, `test_agent_registry_wiring` (bar the known one), the D1/D2/B1-join
  suites, the **HTTP-gateway isolation guard**, and the R6/R7 launcher + A2 directive suites.
- Two `tests/api` failures, neither this slice's:
  `test_agent_registry_wiring::test_resolved_snapshot_materializes_through_c61_backend`
  (pre-existing, recorded in the D1/D2 memories — it materializes `stage0-interview@v9` while the
  profile has pinned v10 since v22), and
  `test_account_deep_v0_fresh_process::test_v0_fresh_process_replay_inspects_complete_durable_state`
  (its subprocess runs `alembic upgrade head`, which exits 255 while two heads exist — it will pass
  once the orchestrator merges them).

## Trap to remember

Every DB-backed suite's session fixture runs `alembic upgrade head`, which **fails outright** while
two heads exist. I patched the 21 `conftest.py` files to `"heads"` for the duration of my local
runs and reverted them before committing; nothing in that patch is in the tree. The orchestrator's
`alembic merge` removes the need.

## Open items

1. The recipe-ceiling blocker above — needs an owner and the `CONVERSATION_RECIPE_VERSION` bump.
2. `entity_research_runtime_enabled` stays **off** by default. The acceptance suite does not need
   it (the launcher is composed directly in-test); the *worker* composition it gates is the fleet's,
   and flipping it on is the lane's rollout step, not a code change.
3. The gate substrate is generic but only `directive_confirmation` is answerable; `plan_approval`
   and `budget_approval` are declared in the CHECK and refused by the route with
   `GATE_KIND_UNSUPPORTED` until somebody builds them.
4. D3 owns emitting a gate-lifecycle event through its outbox; `clue_projections.gates` is the
   durable read it should project from.
5. `thread_status`'s `running` half is D3's; the function takes the two inputs independently so
   both lanes' halves compose without either rewriting the other.

---

## Close-out (same day, after the orchestrator merged the Lane-D heads)

Single head `2a4206f616fd`; `alembic upgrade head` and the repo-wide DB fixtures work again, and
`conversation_turns.py` was released to me. Open item 1 — the C5 recipe ceiling — is **closed**.
Commit `e1d3be13`.

### What shipped

- **`recipe0-stage0-v6.json`** — v5 plus the kickoff chain. Its interaction slot allowlists
  `draft_account_research_directive@2`, `open_directive_confirmation_gate@1` and
  `launch_account_research@1`; `dynamic_pin_kinds` gains `project_run`, `research_directive`,
  `account_research_selection`. **Gotcha:** the tool pins must be mirrored into *both* the gate
  node's own `requirements` and `compatibility.nodes[...]` — `RecipeDefinition` validates that the
  two agree, and only mirroring one fails at load with "compatibility.nodes must exactly mirror
  graph node-local requirements".
- **Two pin resolvers** in `recipe_wiring`. `research_directive` (keyed on directive id, versioned
  by the directive's own `version`, immutable-identity payload only — `status` deliberately out,
  the way `project_run` excludes its mutable counters). `account_research_selection` — the launch's
  subject, which the launch *creates*; the provider declares it absent with the existing
  `key="__not_supplied__", version="missing", required=False` idiom, so it resolves to a recorded
  `status='missing'` pin instead of an incompatibility. Requiring it would deadlock the tool
  against the thing it makes. It still resolves truthfully post-launch, so replays pin the real one.
- **`Stage0StepPinProvider` branches** — registries for the draft; `project_run` + `research_directive`
  for the gate and the launch; the declared-absent selection for the launch.
- **`CONVERSATION_RECIPE_VERSION = 6`** (one line, plus the rationale comment).
- **`RECIPE_0_TOOL_ADDRESSES`** gains the three addresses (anything runnable in the slot is
  replay-certified there first).
- **`tests/api/test_lane_d4_model_planned_kickoff_db.py`** (4 tests) — the model-planned acceptance.

### The new acceptance

Real promoted revision, real `RecipeExecutor`, real `Stage0StepPinProvider`, real
`C5AgentExecutionAdapter`; only the model is absent (the test authors the plan). The agent plans
the gate → the human answers through the production route → the agent, woken on that confirming
turn, plans the launch → the run's `source_action_ref` and `approval_refs` are the confirming
turn's receipt, identical to the launcher-driven acceptance. Plus: a plan proposing the human-only
confirm tool is refused by both ceilings; and the shared ceiling grants the trial nothing (its
surface still subtracts the gate and launch tools).

### Findings

1. **`draft_account_research_directive@2` cannot ride a plan.** The C5 graph forbids a raw body
   anywhere in a plan **by key name** (`_RAW_BODY_KEYS` = `body`, `content`, `interview_answer`, …)
   and that tool's input field is literally `body`. So the slot admits it, but a plan that inlines
   a directive body is rejected `raw_body_key`. Pre-existing, unrelated to D4, and fixing it means
   either passing the body as an artifact ref or renaming a frozen field (rewriting its schema
   digest and every profile that pins it) — both outside the catalog/pin seams. Pinned by
   `test_the_draft_tool_is_admitted_by_the_slot_but_cannot_ride_a_plan_today` with the exact code.
2. **`agent_plan` FKs `(turn_id, execution_id, workspace_id)` onto `agent_turn`** — a turn row
   minted against a different execution can never hold a plan. That is why
   `_seed_two_account_conversation` grew `create_turn_row`: the launcher-driven suite pre-creates
   the row (its gate needs the FK and it runs no C5 execution), while the model-planned suite
   creates the execution and the turn row together, as the fleet worker does.
3. `draft_account_research_directive@2` is the only one of the three that is operation-bound
   (`ResearchDirectiveId(operation_id)`); the gate and the launch are domain-idempotent.
   `test_recipe_contracts::test_operation_id_requirements_are_explicit` updated accordingly.

### Gates (round 2)

- `make db-smoke` up→down→up on a clean throwaway DB (`d4_smoke2`, 55040), now via plain
  `alembic upgrade head` — single head `2a4206f616fd`.
- `uv run mypy` clean (611 files); `lint-imports` 25 kept / 0 broken; `ruff check`/`format --check`
  clean on every file this round touched.
- D4 suites + the isolation guard: **43 passed** (13 + 19 + 5 + 4 + 2).
- `tests/execution` (67), `tests/agents` (188), `tests/architecture`, and full `tests/api` green
  except the one **pre-existing** failure, now proven pre-existing by stashing this round's work
  and watching it fail identically: `test_agent_registry_wiring::
  test_resolved_snapshot_materializes_through_c61_backend` (materializes `stage0-interview@v9`
  while the profile has pinned v10 since v22).
- Repo-wide `ruff check .` reports 4 errors, none mine: 3 in the orchestrator's merge migration
  `2a4206f616fd` (unsorted imports + two unused imports) and 1 E501 in the pre-existing untracked
  `tests/claimstore/test_lens_isolation.py`.

### Still open

- The `draft` raw-body constraint above (finding 1) — needs an owner if the agent is ever to draft
  from a plan rather than from a tool call the platform makes for it.
- `entity_research_runtime_enabled` remains off by default; unchanged by this round.
- Nothing else from the original open list moved: the gate substrate is still generic-but-only-
  `directive_confirmation`-answerable, and D3 owns gate-lifecycle emission.
