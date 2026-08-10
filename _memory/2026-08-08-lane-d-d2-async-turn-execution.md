# 2026-08-08 — Lane D D2: async worker-executed turns (`AGENT_TURN`)

Brief: `docs/specs/FI-lane-D-D2-implementation-brief.md`. Charter §3-P3 / §3.5, ratified §6-D1.
Branch `platform/frontend-integration`. Commits `2487e5b0` (substrate) + `ebbcca23` (tests).

## What shipped

- **`FleetTaskKind.AGENT_TURN`** (appended last so the ordered DB parity test still holds) +
  migration **`fba208917f89`** (chains off the B1-join head `c4ccc7b11810`; single head, no merge).
- **`agent_turn_submission`** — a new immutable table (append-only trigger), the durable record
  that a human submitted a turn. See the deviation below for why it exists.
- **Per-thread single-flight by construction** (`agent_turn_submission.py`): at most one
  non-terminal `agent_turn` fleet task per thread. `work_id = uuid5(workspace, thread)` so the
  existing fleet driver lease is a per-thread fence; `dedup_key = "agent-turn:<turn_id>"`.
  `dispatch_next_thread_turn` takes a `pg_advisory_xact_lock` on the thread, refuses if a
  queued/claimed task exists, else offers the earliest submission with no terminal task
  (`ORDER BY requested_at, turn_id`) — all in one transaction with the enqueue.
- **`POST /api/v1/projects/{id}/threads/{tid}/turns`** in `chat/router.py` → `202 {data:{turn_id,
  thread_id, requested_at, replayed}}`. Mandatory `Idempotency-Key`; `turn_id` derived from
  (workspace, thread, key) so a duplicate is a replay. `gate_response` (D4) left as a comment.
- **Shared conversation modules** — `conversation_capture.py` (capture-before-spend; one owner for
  the trial and the route) and `conversation_turns.py` (`ConversationTurnEngine` +
  `build_conversation_turn_engine`, incl. the committed-outcome replay short-circuit).
- **`agent_turn_fleet_wiring.py`** — `build_agent_turn_work_handler` (composed once at worker
  startup), `ProjectConversationTurnRunner`, `AgentTurnWorkHandler`. Registered in `fleet_main`
  behind `settings.chat_enabled`; `build_multi_work_worker` gained an `agent_turn_handler` kwarg
  with a kind guard.
- **`PROJECT_CONVERSATION_SURFACE`** with exactly the trial's tool subtraction (launch tools stay
  withheld until D4).

## The one design deviation from the brief (report this to the founder)

The brief says the route persists "artifact + DSAR binding + onboarding_input + **turn row**".
**It cannot.** `agent_turn.execution_id` references `execution`, and the constitution pins a
resolved profile + resource-manifest artifact + project card + budget envelope — i.e. the agent
plane, and `build_agent_platform_components` builds the *model provider* in the same call, which
the same brief forbids the HTTP process from composing. So a turn's identity lands in two halves
keyed on one derived `turn_id`: the **submission** (route) and the **`agent_turn` row** (worker,
which copies `submitted_by_user_id`/`submitted_via_membership_id` across). The identity is still
read from a durable row, never from the queue payload — the rule the brief was protecting.

Consequence to know: a *queued* turn has a submission row but no `agent_turn` row/event status yet.
The AC's "their turn rows exist with their event status" is met by the submission row; a D3/D5 read
surface for queued turns should read `agent_turn_submission` (there is
`submissions_for_thread(...)` for exactly that) unioned with the turn journal.

## Other decisions

- **Recipe seeding**: nothing new. `recipe0-stage0@5` is a SYSTEM recipe already seeded once at
  worker boot by `fleet_main`'s existing `seed_system_recipes()`. Per-turn work is only
  `starter.start(...)` + drive-to-gate (the recipe is barrier→gate→barrier; no pre-gate tools).
- **Recipe pin unified**: `CONVERSATION_RECIPE_KEY/VERSION` in `conversation_turns`;
  `STAGE0_RECIPE_VERSION` now aliases it (two pins = two callable tool sets for one role).
- **`client_entity_id` is discovered, never assumed** — `project_client_entity_id()` reads the
  latest non-null value off this project's `onboarding_input` rows. `None` when Stage-0 recon has
  not run: the constitution field is optional, Stage-0 tools then refuse loudly, and the L3 card
  says the client KB is absent. (The real fix is PC-C4's brand-aware onboarding input; not D2's.)
- **`decide_gate` actor**: the production runner passes `actor="human"`, matching
  `recipe0-stage0`'s declared gate authority. **The trial passes `"agent"` against the same
  human-authority gate** — a latent mismatch in `stage0_trial.py` that D2 did not inherit and did
  not fix. Worth a look by whoever owns the trial.
- **Trial composition**: still per request (it is a per-session CLI harness whose toolbelt is
  deliberately different — no scrape binder, Stage-0 recipes only), but it now composes *through*
  `build_conversation_turn_engine` and executes through `engine.execute`, so there is one
  implementation. Its `save_state` sequence reservation moved to just *before* the shared execute
  (strictly earlier than before; the guarantee is unchanged).

## Gates

- `make db-smoke` (up→down→up) on a **clean throwaway DB** `d2_smoke` on `clue-pg-damascus`
  (localhost:55040) — green; schema + 5 enum labels verified, then dropped.
- `uv run mypy` — clean (599 files). `uv run lint-imports` — 25 kept, 0 broken.
- `ruff check`/`ruff format` — clean on every file this slice touches. (Repo-wide,
  `ruff format --check .` reports 23 *pre-existing* unformatted files plus the untracked
  `tests/claimstore/test_lens_isolation.py`; none are ours.)
- New suites: `tests/api/test_lane_d2_turn_submission_db.py` (10) +
  `test_lane_d2_http_gateway_isolation.py` (2) — all green. `tests/fleet` green (69).
  `tests/api` green except the **pre-existing** `test_agent_registry_wiring.py::
  test_resolved_snapshot_materializes_through_c61_backend` (C6.1; recorded in the D0/D1 verdict).

## Trap hit — record it

The workspace DB (55040/clue) ended up stamped `fba208917f89` while the enum label was **missing**:
another agent's test sweep ran `alembic upgrade head` in the window between `alembic revision`
generating my file (empty `upgrade()`) and my writing its body. Fixed with `alembic downgrade -1`
+ `upgrade head`. **Lesson: write the migration body before anything else can migrate, or expect a
stamped-but-empty revision on a shared workspace DB.**

## Open items for the next slices

1. **D3** needs a read surface for queued turns (see the deviation above) and owns the turn event
   outbox; nothing here emits stream events yet.
2. **D4** widens `PROJECT_CONVERSATION_SURFACE` (launch tools) and adds the mutually-exclusive
   `gate_response` body — the seam is commented in `chat/schemas.py`.
3. A failed `agent_turn` task is terminal and never silently retried (fleet doctrine). There is no
   operator "retry this turn" surface yet; the charter's `retry_of_turn_id` semantics are unbuilt.
4. `AgentTurnWorkHandler` finalizes its own task then dispatches. If the process dies *between*
   those two steps the thread stalls until the next submission (which re-dispatches). Bounded and
   self-healing, but worth a sweeper pass if D3 makes long threads routine.
5. The B4 composed-run fleet test (`test_b4_composed_run_db.py::…deep_quarantines`) fails when
   `tests/api` runs before `tests/fleet` — **verified pre-existing** by re-running the same
   combination against HEAD with this slice's sources temporarily reverted. Cross-suite state
   pollution, not Lane D's.
