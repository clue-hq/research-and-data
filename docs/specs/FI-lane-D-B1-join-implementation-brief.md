# Lane D — B1-join mini-slice implementation brief: ownership FKs + real dev principal + provisioning hardening

**Charter:** `docs/specs/FI-lane-D-production-chat-and-launch.md` §3-P1/P2. **Identity law:**
`docs/specs/FI-lane-B-authenticated-principal-contract.md` (§§3–4 are the core here). **Review
context:** `_memory/2026-08-08-lane-d-d0-d1-review-verdict.md` (items 1–2 of its follow-ups are
this slice). Lane B's B1 substrate is on this branch (`platform/auth/clue_auth/**`, tables
`platform_user` / `auth_identity` / `workspace_membership`, migration `9398ae4467e3`).

## Mission

Close D0's deferred ownership join now that B1 exists: real FKs from the thread/turn ownership
columns to Lane B's tables, a dev principal backed by real provisioned Postgres rows (contract §4:
even a dev adapter "must still resolve a real internal user/membership fixture from Postgres"),
and the `ensure_platform_thread` cross-project hardening found in review.

## Deliverables

### 1. One Alembic migration (hash id; chain off `alembic heads` at authoring time — currently `a21c4d290eb7`)

- FKs, composite where workspace locality matters (match `workspace_membership`'s
  `UNIQUE (membership_id, workspace_id)`):
  - `agent_thread (created_by_user_id)` → `platform_user (user_id)`
  - `agent_thread (created_via_membership_id, workspace_id)` → `workspace_membership (membership_id, workspace_id)`
  - `agent_turn (submitted_by_user_id)` → `platform_user (user_id)`
  - `agent_turn (submitted_via_membership_id, workspace_id)` → `workspace_membership (membership_id, workspace_id)`
  NULLs pass an FK by definition — machine turns/threads stay legal. **Pre-check orphans and fail
  loud** (the B3 `82a80fb80c9e` precedent): all DBs hold synthetic dev data only; the error text
  must name the reset path, never silently NULL anything out. Reversible downgrade.
- Verify with `make db-smoke` on a clean throwaway DB on the dedicated `clue-pg-damascus`
  Postgres (**localhost:55040** — never localhost:5432, that is a foreign server).

### 2. Dev principal backed by real rows

- A `provision_dev_principal(settings)` helper (new module, e.g. `chat/dev_fixture.py`) that
  idempotently ensures the configured dev user + workspace membership exist, going through
  `clue_auth`'s provisioning APIs — never raw INSERTs into Lane B's tables.
- `build_dev_principal_resolver` / `install_chat_surface` (D0's `chat/principal.py`): in
  `local_header` mode, provision-and-verify at install/startup (async work happens there), then
  the resolver closes over the verified ids — `PrincipalResolver` stays sync, `chat/router.py`
  stays untouched. Absent/unprovisionable rows fail startup loudly. Production behavior
  (refusal outside `local_header`) is unchanged.

### 3. `ensure_platform_thread` hardening (`platform/api/clue_api/thread_store.py`)

After `ON CONFLICT (id) DO NOTHING`, read the surviving row and verify its
`(workspace_id, project_id)` equals the caller's; on mismatch raise a typed error (stable reason
string) so the turn write fails loud instead of silently attaching to another project's thread.
Keep it one round-trip where reasonable (e.g. `RETURNING`/follow-up SELECT — your call, document
it).

### 4. Tests — in NEW files only (a parallel D2 agent edits the existing chat/turn suites)

FK enforcement (orphan user/membership refused; NULL passes; cross-workspace membership refused
by the composite FK); provisioning idempotency + startup failure when rows can't exist;
the cross-project attach now raises (and same-workspace/same-project stays a no-op);
`make db-smoke` green.

## Hard exclusions

Never touch: `platform/auth/**` code (call it, don't edit it), `chat/router.py`,
`chat/schemas.py`, `thread_tools.py`/`thread_wiring.py`, `turn_binding.py`/`turn_action.py`/
`executor.py`/`agent_execution_wiring.py`/`agent_turn_wiring.py` (D2's), fleet files,
`frontend_read/**`, `apps/frontend/**`, `api-contracts/*.md`, FI-2 files, existing test files.
A parallel D2 agent is working in this worktree — stage/commit only your own files by explicit
path. If your migration and D2's fork the Alembic head, do NOT merge heads yourself — the
orchestrator owns the join.

## Process

Test-first where practical; commit locally at checkpoints; never push; no AI attribution.
Gates: `make db-smoke` (throwaway DB), `make lint`/`make typecheck` clean on touched packages,
your suites green. Finish with a `_memory/` entry and a final report: files, migration id,
the typed error you introduced, test results, anything open.
