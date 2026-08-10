# Lane D slice D2 — implementation brief: async worker-executed turns (`AGENT_TURN`)

**Charter:** `docs/specs/FI-lane-D-production-chat-and-launch.md` (RATIFIED — read §1.2, §1.6,
§3-P3, §3.5, slice D2, §5). **Ratified §6-D1:** async worker-executed turns; gateway-in-HTTP is
rejected. **Scope law:** demarcation §2.4. **Identity law:** the Lane B contract §7 (async
execution: queue carries internal ids + turn refs, never tokens; workers are service-class).
D0/D1 are landed and reviewed — read `_memory/2026-08-08-lane-d-d0-d1-review-verdict.md`.

## Mission

The production turn path: `POST .../turns` persists the human turn durably (with submitter
identity) and enqueues; the fleet worker — composed once at startup — executes the platform
deepagent graph; crash/retry converges on one committed outcome; per-thread execution is
single-flight in submission order. The HTTP process never touches the model gateway.

## Verified baseline (do not re-derive)

- **Fleet:** `FleetTaskKind` (`platform/fleet/clue_fleet/enums.py`) is a package-local StrEnum
  mirrored by the Postgres enum `fleet_task_kind` with a parity test in `tests/fleet/`. Workers
  dispatch one `WorkHandler` per kind (`work_worker.py:69-129`; duplicate kinds refused).
  Production composition is `platform/api/clue_api/fleet_main.py` (registration calls only —
  composition-root chokepoint). Queue primitives live in `clue_fleet/queue.py` (dedup_key,
  priority, claim/requeue).
- **Worker-side deepagent precedent:** `account_research_turn_wiring.py:488-560` — the
  entity-research fleet already runs full deepagent turns in the worker over the same substrate
  (`turns.create`, committed-outcome replay short-circuit, context assembly, checkpointer).
- **The trial's per-request composition** (`stage0_trial.py:600-731`): storage + gateway + full
  toolbelt + recipe seeding + context assembler + runtime rebuilt per request; graph executed
  in-process blocking (`runtime.py:311-327`); deterministic `turn_id`; committed-outcome replay
  short-circuit; user message persisted (artifact + DSAR binding + `onboarding_input
  actor='human'`) **before** model spend; mandatory `Idempotency-Key`. Its surface
  (`STAGE0_CONVERSATION_TRIAL_SURFACE`) withholds the launch tools.
- **D0/D1 give you:** the `chat/` package (router, principal seam, flag), `agent_thread` +
  `agent_turn` submitter columns (nullable), the turn journal's thread auto-provisioning, and the
  C5 adapter deriving ambient `actor_id`/`action_ref` per turn (`C5AgentExecutionAdapter`
  derives `turn-action:<turn_id>` in `__init__`). `RecipeExecutor.execute` accepts
  `actor_id`/`action_ref` kwargs. `resolve_turn_action` refuses NULL-submitter turns — your
  route writing real submitters is what makes production receipts resolvable.

## Deliverables

### 1. `AGENT_TURN` task kind

`FleetTaskKind.AGENT_TURN = "agent_turn"` + one migration adding the DB enum value (chain off
`alembic heads` at authoring time; follow the house precedent for enum-value addition and give
downgrade the honest reversible shape used before — fail loud if rows reference the value) +
parity test update. Task payload/dedup: `dedup_key = "agent-turn:<turn_id>"`, payload carries
internal refs only (`turn_id`, `workspace_id`, `thread_id`, `project_id`) — never a session
token (Lane B §7/§9).

### 2. The production turn route (in D0's `chat/router.py` + `schemas.py`)

`POST /api/v1/projects/{projectId}/threads/{threadId}/turns`, behind the existing chat flag +
principal seam (`thread.write`): validate the thread (exists, `active`, in this
project+workspace — typed refusals); accept exactly `{message}` plus idempotency identity
(charter §3.5 — the mutually-exclusive `gate_response` body is **D4's**; leave the seam
commented, do not build it); persist the user turn **before enqueue** exactly as the substrate
does before spend — artifact + DSAR binding + `onboarding_input(actor='human')` + turn row —
**stamped with `submitted_by_user_id`/`submitted_via_membership_id` from the principal**; then
enqueue the `AGENT_TURN` task and return `202 {data:{turn_id}}`. Duplicate submission under one
idempotency identity returns the same turn, enqueues nothing new.

Extract the trial's persist-user-turn path into ONE shared function both the trial and this
route call (`agent_turn_wiring.py` or a sibling — no duplicated persistence logic).
`DbAgentTurnJournal.create` grows optional submitter identity params (default `None` — machine
turns unchanged). The route never imports the gateway, model provider, or toolbelt-with-gateway
composition — add a guard (import-linter contract or a test) proving the HTTP process cannot
reach `LLMGateway`.

### 3. Worker-side execution

A new wiring module (PF-7 pattern, e.g. `platform/api/clue_api/agent_turn_fleet_wiring.py`)
building the platform-deepagent turn executor ONCE at worker startup — the trial's per-request
composition (§1.2's known defect) extracted into a shared builder both the trial and the worker
use; the trial keeps rebuilding per request only if extraction would change its semantics (then
say so in the report). The `WorkHandler` for `AGENT_TURN`: load the durable turn, execute the
graph via the substrate (honoring the committed-outcome replay short-circuit — a retried task
must converge on ONE committed outcome, never a second execution of a committed turn), record
failure per fleet conventions. The worker acts as a service principal executing an agent turn:
`constitution.actor_id` for these turns is the **submitting principal's `user_id`** read from
the durable turn row (never fabricated, never from the task payload's authority — the row is
the truth). Register the handler in `fleet_main.py` (registration call only).

If recipe seeding is inherently per-project state: seed lazily once per project (cached),
never per turn — and report the shape you chose.

### 4. Per-thread single-flight + submission order (charter §3.5)

Invariants (mechanism is yours — reuse existing fleet lease/lock patterns; report your choice):
- No two turns of one thread ever execute concurrently (any number of workers).
- Turns of one thread execute in submission order (`requested_at, id`).
- Later turns stay durably queued and visible (their turn rows exist with their event status);
  queueing never blocks turns of other threads/workspaces, and a detached research run never
  blocks a chat turn.

### 5. Production conversation surface

Declare `PROJECT_CONVERSATION_SURFACE` for these turns with exactly the trial conversational
surface's tool subtraction (launch tools stay structurally withheld — widening is D4's P5(e)).
Trial surface itself: unchanged, dev-only (ratified §6-D6).

## Acceptance criteria (charter D2 — all must hold as tests)

Concurrent turns on two workspaces execute without cross-talk; two turns on one thread execute
in submission order; a worker crash mid-turn starts a distinct retry attempt and reaches one
committed outcome; the HTTP process never touches the gateway (guard test); detached research
does not block a new chat turn; duplicate POST under one idempotency identity is a no-op replay.
DB-backed tests provision REAL `platform_user`/`workspace_membership` rows via `clue_auth` for
any submitter identity they stamp (a parallel mini-slice is adding FKs to those tables — your
suite must be green with or without it). Gates: `make lint`/`make typecheck` clean on touched
packages; suites green; `make db-smoke` for your enum migration on a clean throwaway DB on
`clue-pg-damascus` (**localhost:55040** — never 5432, that is a foreign server).

## STOP-and-report tripwires

Extraction forcing edits to quarantined M8D files or restructuring `executor.py`; the queue
schema needing more than the enum value; recipe seeding resisting startup/lazy-cached shape
without semantic change; single-flight requiring new tables. Stop, commit what's done, report.

## Hard exclusions

Never touch: `chat/principal.py`, `thread_store.py` (a parallel B1-join agent owns both), Lane
B's `platform/auth/**` (call, don't edit), `frontend_read/**`, `apps/frontend/**`,
`api-contracts/*.md`, FI-2 slice files, quarantined M8D modules, `turn_action.py` (consume it,
don't edit). Composition roots: registration calls only. Do not merge Alembic heads if the
parallel agent's migration forks them — the orchestrator owns the join.

## Process

Test-first where practical; commit locally at checkpoints; never push; no AI attribution;
stage/commit only your own files by explicit path. Finish with a `_memory/` entry and a final
report: files, migration id, the single-flight mechanism chosen, the composition extraction
shape (what moved where; what the trial still rebuilds), how the replay short-circuit is proven,
test results, open items.
