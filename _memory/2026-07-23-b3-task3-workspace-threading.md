# 2026-07-23 — B3×research Task 3: thread workspace + flip writers/resolution to required

## What landed (commit 0206f37, branch research/b3-account-workspace-localization)
The final slice of workspace-local accounts. `workspace_id` is now **required** on every entity
creation/resolution seam, and every creation chain threads it.

- **Flipped to required (production):** `insert_account_entity(..., workspace_id: str)`;
  `resolve`/`resolve_many(..., workspace_id: str)` (transitional `_ws_clause`/`_ws_bind` None-arms
  **deleted** → every candidate query unconditionally `AND workspace_id = :ws`); `disposition(...,
  workspace_id: str)`; `admit(..., workspace_id: str)` (new kwarg); `resolve_alias(conn, key,
  entity_type, *, workspace_id: str)` (new kwarg — closes the exact-name cross-tenant leak, all 4
  branches scoped); `resolve_crm_seeds(..., workspace_id: str)` (extra caller, grep-found).
- **Threaded chains:** client_kb `_resolve_client`, seeds `_resolve_customer`, import_accounts
  (`resolve_many` + `_resolve_contact_entity`), discovery `admit`→`_admit_resolved`, phases
  (`ctx.workspace_id`), committee `admit_candidate` (derives `account.workspace_id`, `ValueError`
  fail-loud on NULL), review `resolve_create_new_entity` (new `ReviewTaskUnscopedError`),
  disposition_store `capture_downstream` (`row.workspace_id`).
- **Tests:** new shared `tests/_workspace.py::seed_workspace` (idempotent `INSERT INTO workspace ...
  ON CONFLICT DO NOTHING`, default "acme"). 47 test files seed + thread a workspace (mechanical).
  New stamped-creation tests for disposition new-entity, review create-new-entity (+ unscoped
  raises), discovery admit, committee admit (+ unstamped raises), lookalike-customer seed,
  resolve_alias isolation. Integration flows creating accounts indirectly (fleet composed-run,
  api toolbelt wiring) seed committed/rollback workspaces.

## Gates
mypy 327 green; ruff check + format clean (677); import-contracts 23 kept/0 broken; full pytest
exit 0 (2264 collected, DB/redis-gated skip). DB used: `postgresql+asyncpg://clue:clue@localhost:5432/clue`
(clue-postgres container, migrated head 7f1868a127aa). No `.env` in this workspace — set
`CLUE_DATABASE_URL` inline to run the DB suite.

## Incident + recovery (IMPORTANT lesson)
Parallel sub-agents were launched WITHOUT worktree isolation → they shared one working tree. A
sub-agent's `git stash` + a `reset` swept the whole in-progress change set into `stash@{0}` and left
a broken live tree (pre-flip production + scattered partial edits). Recovered by: backup patch →
`git reset --hard HEAD` → `git stash apply stash@{0}` (the complete coherent 56-file set) → finished
stragglers single-threaded. No work lost. **Lesson: for multi-file mechanical fan-out on ONE repo,
either isolate each agent in its own `git worktree` (Agent `isolation: "worktree"`) or do it
single-threaded — never many agents on a shared tree (they clobber via stash/reset and each other's
Edits).**

## Not done / follow-ups (unchanged from CLAUDE.md [B3×research])
Strong-key uniqueness re-scoping to `(workspace_id, …)`, contact strong-key workspace-local,
resolver/provider cache keying by workspace, superseding cross-tenant public-claim reuse language —
all still open, out of this task's scope. `docs/superpowers/` (empty stray dir from a sub-agent
skill) left uncommitted deliberately.
