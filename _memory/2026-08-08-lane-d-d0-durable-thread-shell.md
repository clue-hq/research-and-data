# FI Lane D — slice D0: the durable thread shell (COMPLETE)

Date: 2026-08-08. Branch: `platform/frontend-integration` (worktree `damascus`).
Brief: `docs/specs/FI-lane-D-D0-implementation-brief.md`. Charter:
`docs/specs/FI-lane-D-production-chat-and-launch.md` §3-P1 / §4 slice D0.
Commits: `f92fe1d7` (migration + shell + readers + L6), `49d7b7a5` (tools + chat surface),
`d941c6f6` (tests + principal-dependency fix).

## What landed

REQ-21's shell, which was spec-only before this slice.

1. **Migration `fb558870202b`** (`down_revision='870fe4f2af87'`; the orchestrator later joined it
   with Lane B's B1 head `9398ae4467e3` via merge revision `a21c4d290eb7` — do not re-mint).
   - `agent_thread` — mutable shell state (title / pinned / status), deliberately **not** under
     the C6 append-only trigger. Composite project FK `(project_id, workspace_id)`, workspace FK,
     `UNIQUE (id, workspace_id)` anchor, listing index `(workspace_id, project_id, created_at, id)`.
   - `agent_turn.submitted_by_user_id` / `.submitted_via_membership_id` (both nullable, no FK).
   - `agent_turn_thread_fk (thread_id, workspace_id) → agent_thread (id, workspace_id) NOT VALID`.
   - `agent_turn_project_requested` index; `onboarding_input_artifact_capture` index (the
     `get_onboarding_input_for_artifact` predicate had none).
2. **Four governed tools** (`create_thread@1`, `rename_thread@1`, `set_thread_pinned@1`,
   `archive_thread@1`) in `thread_tools.py`, registered from `thread_wiring.py` with one call at
   `toolbelt_wiring.build_toolbelt`. Store: `thread_store.py`.
3. **`/api/v1` chat surface** (`clue_api/chat/`: `router.py`, `schemas.py`, `principal.py`) behind
   `chat_enabled` (`CLUE_CHAT_ENABLED`, default off), mounted from `create_projections_app`.
4. **Paginated readers** — `agent_turns_for_project` (keyset, fixes FI-1 defect L6),
   `agent_turns_for_thread`, `thread_messages`, `threads_for_project`; shared cursor in
   `clue_projections/pagination.py`; ref vocabulary in `clue_projections/thread_refs.py`.
5. **L6 truncation inverted** — `clue_agents/context.py` retains the *newest* messages for
   `L6_CONVERSATION` and emits chronologically.

## Decisions taken (deviations from the brief — all reported to the founder)

- **Ownership columns are NULLable, not NOT NULL.** The brief specified `created_by_user_id` /
  `created_via_membership_id` NOT NULL. Two independent reasons made that wrong here: (a) the
  `agent_turn → agent_thread` FK the brief also requires would refuse *every* turn written today
  (stage-0 trial, entity-research fleet, specialist delegations — all use synthetic thread ids),
  so `DbAgentTurnJournal.create` now provisions the shell row for platform-originated threads, and
  those threads genuinely have no human creator; (b) membership is not on `ToolContext` and adding
  it is Lane B B4's seam — accepting it as a tool input would put an authorization identity into a
  model-visible schema (Lane B ruling 7). A CHECK enforces `membership ⇒ user`.
  **Consequence: `agent_thread.created_via_membership_id` is NULL for every row D0 writes.**
- **Tools are `WRITE`, not `STEERING`.** The C6 authority audit refuses to grant a steering tool to
  any model role, so classifying a rename as steering would foreclose REQ-21's agent-managed
  threads. Authority is `()` — installed and disclosed, granted to nobody, and *not* in
  `_HUMAN_ONLY_TOOLS`.
- **Route-scoped error envelope, not app-level handlers.** `frontend_read` owns the app-level
  `StarletteHTTPException` / `RequestValidationError` / `Exception` handlers and FastAPI keeps one
  per exception class; a second set would silently replace that lane's envelope. `_EnvelopeRoute`
  (an `APIRoute` subclass) is local to `chat/`.
- **CORS untouched.** Cross-origin write widening is Lane D **D2**'s item (demarcation §2.2).
- **`agent_thread_message` gets no FK of its own** — its thread integrity already rides the
  composite FK to `agent_turn (id, workspace_id, thread_id)`, and that pair is now what the new
  constraint proves resolves. A second FK would be redundant, not safer.
- **Ref flavors reuse existing closed vocabularies** — `attachment` / `output` / `open_gate` /
  `next_action` / `assumption` / `workspace_output` are each an existing `ref_role` value. Nothing
  was widened, so no STOP was required.
- **`MessageObjectRef` re-declares `DomainObjectRef`'s shape** rather than importing it: the
  machine-enforced import contract P1 forbids `clue_projections → clue_agents`.

## Failures hit and fixed

- **FastAPI closure-local `Annotated` alias.** `PrincipalDep` defined inside `build_chat_router`
  made `who` a required *query parameter* (annotations are strings under
  `from __future__ import annotations`; FastAPI resolves them against module globals). Every write
  500'd. Fixed by a module-level deny-by-default `chat_principal_resolver` +
  `bind_principal_resolver` installed through `dependency_overrides`. `projections_app` documents
  this exact trap at its own aliases — read it before adding a router.
- **`RequestValidationError` is not `pydantic.ValidationError`.** The envelope route caught only
  the latter, so an unknown body field became a 500. Both are caught now.
- **Same-transaction `now()` ties.** `create_thread` rows written in one transaction share
  `created_at`, so a listing test asserting insertion order failed. The keyset is total over
  `(created_at, id)`; the test now stamps distinct times for readability and a separate test walks
  seven tied rows to prove the row-value comparison.

## Verification

- `make db-smoke` green on the per-branch DB (`clue-pg-damascus`, localhost **55040** — never
  5432, which is a foreign native Postgres). Re-verified by the orchestrator after the alembic
  merge.
- `ruff format --check` + `ruff check` clean on every file this slice touched; `mypy` clean
  (594 files); `lint-imports` 25/25.
- Suites green: `tests/projections` (incl. new `test_thread_shell_db.py`, 8 tests),
  `tests/agents` (incl. new `test_context_l6_retention.py`), `tests/api` (incl. new
  `test_chat_thread_surface_db.py`, 7 tests) — one pre-existing failure only, see below.

## Pre-existing failure (NOT this slice's)

`tests/api/test_agent_registry_wiring.py::test_resolved_snapshot_materializes_through_c61_backend`
fails with `WorkspaceSecurityError: workspace parent directory does not exist`. Proven pre-existing
by reverting `toolbelt_wiring.py` + `agent_registry_wiring.py` to `68f358a0` and re-running: it
fails identically. Unrelated to tools — it materializes skill resources into a tmp workspace.

## Open follow-ups

1. **Ownership FK join to Lane B B1** (`platform_user` / `workspace_membership`) — explicitly out
   of D0's scope; a separate slice owns it. When it lands, also decide whether
   `created_via_membership_id` becomes writable (needs B4's `ToolContext` membership seam).
2. **`created_via_membership_id` is always NULL today.** Anything that reasons about "which
   membership opened this thread" must wait for B4.
3. **Thread `status` on the wire is derived and honest-but-thin** — `idle` / `archived` only.
   `running` / `review` / `approval` / `needs-input` need the latest turn's status plus open
   gates: D2 and D4. `chat/schemas.py::thread_status` is the single place to change.
4. **`HistoryLayerSource.load` still reads every message body from storage** before the budget
   drops most of them — N artifact reads for an N-message thread. Pre-existing; worth a windowed
   loader when D2/D3 make long threads routine.
5. **Cross-origin POST/PATCH CORS** for this surface is D2's.
6. **Frontend contract deviations** (`apps/frontend/docs/api-contracts/projects.md`) are recorded
   in the D0 final report for founder review; the document itself was deliberately not edited.
