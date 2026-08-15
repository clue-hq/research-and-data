# 2026-08-14 — Production deepagent context S2

## Scope

- Completed only S2 from `docs/specs/FI-production-deepagent-context-composition.md`.
- S3 production brand/envelope/Client-KB/active-project card composition remains intentionally
  unstarted. The worker still reports those conditional artifacts unavailable until S3.

## Changes and decisions

- Added the reversible `workspace_client_binding` migration and an insert-once repository guarded
  by a workspace advisory transaction lock.
- Reused C1's existing `recon_run_scope_anchor`; S2 does not create or drop a duplicate constraint.
- Historical migration adoption binds only a workspace with exactly one unmerged recon client;
  ambiguous and merged-only histories remain unbound for an explicit operator decision.
- Authoritative onboarding binds the client in the same transaction that prepares and pins the
  recon identity. The transitional production fleet binds from the typed `start_recon` receipt;
  crash replay repairs the separate binding transaction without repeating provider work.
- Production conversation capture now validates the project/workspace pair and then resolves the
  account-wide binding. Project-scoped onboarding rows remain statement/evidence provenance only.
- The Insight Health browser fixture now establishes the canonical binding rather than teaching
  production readers to infer identity from its project-specific provenance row.
- Added privacy-safe `stage0_setup.client_bound` events containing only workspace/recon/client IDs.

## Verification

- S2 binding/setup selection: 14 passed on retained isolated DB
  `clue_context_composition_20260814`.
- Concurrency: ten same-client transactions replayed one binding; two different-client transactions
  produced exactly one winner and one typed conflict.
- Adversarial authority: an injected target-account `client_entity_id` in fleet payload was ignored;
  the binding matched the recon-derived customer.
- Adjacent chat/stream/trial/browser/card regression selection: 68 passed.
- Broader production-context selection: 52 passed; one unrelated pre-existing C6.3 fixture failed
  because its synthetic L7 source omits the assembler-required `current_user_instruction` origin.
  The same failure reproduced alone and no S2 file is in its trace.
- Ruff and `git diff --check`: clean. Full repository mypy: 660 source files, zero issues.
- Import contracts: 25 kept, zero broken.
- One Alembic head: `b2f815da0f31`.
- Full clean Alembic head -> base -> head passed on retained DB
  `clue_context_s2_smoke_20260814`.
- Conservative backfill plus S2 downgrade/upgrade replay passed on retained DB
  `clue_context_s2_migration_20260814`: one unambiguous workspace bound to its latest recon;
  ambiguous and merged-only workspaces stayed unbound; downgrade preserved `recon_run_scope_anchor`.

## Follow-up

- Begin S3 only when requested: compose/persist the v2 envelope, Client-KB card, and exactly the
  active project's Stage-0 state in the real `AGENT_TURN` worker with one coherent KB-version pin.
- Repair the unrelated stale C6.3 test fixture separately by marking its synthetic L7 candidate as
  the current user instruction and binding it to the request's user-message artifact.
