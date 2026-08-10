# 2026-08-08 — Lane D B1-join mini-slice (ownership FKs, real dev principal, thread hardening)

Brief: `docs/specs/FI-lane-D-B1-join-implementation-brief.md` (items 1–2 of the D0/D1 review
verdict's follow-ups). Branch `platform/auth/clue_auth`-era work is Lane B's; this slice only
*calls* it. Ran in the same worktree as a parallel Lane D D2 agent.

## Shipped

- **Migration `c4ccc7b11810`** (`a21c4d290eb7` → `c4ccc7b11810`; D2 then chained `fba208917f89`
  off it, so the head never forked and no `alembic merge` was needed). Four validated FKs:
  `agent_thread.created_by_user_id` → `platform_user`, `agent_thread (created_via_membership_id,
  workspace_id)` → `workspace_membership (membership_id, workspace_id)`, and the two `agent_turn`
  twins. Columns stay nullable (machine turns/threads have no human owner; NULL passes an FK, and
  a composite FK is MATCH SIMPLE so a NULL membership passes regardless of workspace). A PL/pgSQL
  preflight refuses to migrate a DB whose ownership values name identities that do not exist and
  names `make db-fresh && make migrate` (precedent `82a80fb80c9e`); nothing is nulled out.
- **`platform/api/clue_api/chat/dev_fixture.py`** — `provision_dev_principal(conn, settings)`
  (idempotent; only `clue_auth` CRUD, never a raw INSERT into Lane B tables), the async
  `build_provisioned_dev_principal_resolver`, and `StartupDevPrincipalResolver` (sync
  `PrincipalResolver` that refuses until an async `bind()` at startup succeeds). Provider mapping
  is `provider_key='clue_local_dev'`, subject `local-dev:<user_id>` — authenticates nobody, exists
  only so the fixture has production's shape.
- **New setting `chat_dev_principal_workspace_id`** (`CLUE_CHAT_DEV_PRINCIPAL_WORKSPACE_ID`,
  default `""`). A membership belongs to one workspace, so the dev principal's workspace cannot be
  taken from the request selector; any other selector gets the router's existing 403
  `WORKSPACE_FORBIDDEN`. Empty + `chat_enabled` ⇒ startup fails.
- **`projections_main.build_application`** creates the `StartupDevPrincipalResolver` when
  `chat_enabled`, passes it as `chat_principal_resolver`, and binds it inside `startup_check` (the
  lifespan) — that is where the async work lives, so `chat/router.py` stayed untouched.
- **`thread_store.ensure_platform_thread`** now `RETURNING`s the insert and, on conflict, re-reads
  the surviving row and proves its `(workspace_id, project_id)`. Mismatch ⇒ new typed
  `ThreadOwnershipMismatch` (`reason_code` `thread_project_mismatch`, plus
  `thread_owner_unresolved` for the vanished-row race). Message names neither surviving owner.
- **`tests/_identity.py`** — shared idempotent `seed_principal(conn, workspace_id, user_id,
  membership_id=None, role_key="owner")` through `clue_auth` (the `tests/_workspace.py` of Lane B
  rows). `tests/api/test_lane_d_b1_join_db.py` — 9 DB tests (FK matrix, provisioning
  idempotency/refusals, startup binding, ensure-thread no-op + refusal).
- `clue-auth` added to `platform/api/pyproject.toml` (first `clue_api` importer) + `uv.lock`.

## Cross-agent coordination (recorded so it isn't rediscovered)

Adding enforcing FKs necessarily broke three existing suites that wrote invented `usr_…` strings.
The orchestrator amended the file exclusion to permit **minimal seeding-only** edits; the third
(`tests/projections/test_thread_shell_db.py`) was found after the amendment and treated the same
way. Edits: an import + one `seed_principal` call each (chat suite: a module-local `seed_project`
wrapper; D1 suite: inside `_persist_human_turn` when a submitter is claimed; thread-shell suite: a
seeded owner whose returned ids replace the two literals). No assertion or structural change.
Verified green **both** with the migration and against a DB with the four FKs dropped, so D2's
lane never depends on this migration having landed.

## Verification

- `make db-smoke` exit 0 on a clean throwaway DB (`clue_smoke_b1join` on `clue-pg-damascus`,
  **localhost:55040** — 5432 is a foreign server). Up→down→up, 254 revisions.
- `tests/api/test_lane_d_b1_join_db.py` 9 passed; `tests/api/test_chat_thread_surface_db.py` 7;
  `tests/api/test_lane_d1_turn_action.py` 23; `tests/projections/test_thread_shell_db.py` 8. The
  three amended suites also green on `clue_nofk` (head, FKs manually dropped) = 38 passed.
- `tests/api` + `tests/projections` sweep: **826 passed, 2 failed, 1 skipped**. Both failures are
  not this slice's: `test_agent_registry_wiring::test_resolved_snapshot_materializes_through_c61_backend`
  (pre-existing C6.1, documented in the D0/D1 review verdict) and
  `test_c8_trial_surface::…narrowed_surface…` (D2's in-flight `project_conversation` surface).
- `make typecheck` clean (595 files); `make contracts` 25/25; ruff check + format clean on every
  touched file.

## Open / follow-ups

- `created_via_membership_id` still has **no production writer** — the composite membership FK is
  proved by tests only until Lane B B4 carries membership through the `ToolContext` seam. D2's turn
  route is the first writer of the `agent_turn` submitter columns.
- The chat suite's injected principal still carries the literal `MEMBERSHIP_ID` (`wsm_d0_test`),
  which names no row: nothing writes it today. When D2/B4 write it, that suite must seed with an
  explicit membership id (one per workspace — `unique (workspace_id, user_id)` forbids reusing one
  id across two workspaces, which is why the wrapper lets it be minted).
- `StartupDevPrincipalResolver` is wired only in `projections_main`; other entrypoints that mount
  the chat surface (tests aside) would still get the unprovisioned `build_dev_principal_resolver`
  fallback inside `install_chat_surface` (`chat/router.py`, out of this slice's scope).
