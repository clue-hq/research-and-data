# 2026-07-22 — B3 account memory scope (workspace-local accounts)

## Ruling (founder, 2026-07-22)
Lifts the PB-B3 §0 ruling-5 deferral of the `account` memory scope. The prerequisite is settled:
**accounts are workspace-local entities.** No global account identity, no cross-tenant enrichment
reuse. Grounds: (1) provider licensing — enrichment data is licensed per controller, not poolable
across clients; (2) GDPR controller-separation — each workspace is its own controller. Company X
researched in workspaces A and B is **two separate `account_entity` rows**, with separate claims,
contacts, and memories. Product / project / account are Doc M §4 SIBLINGS (a three-way branch);
cross-branch tension is surfaced + journaled, never arbitrated.

## What landed (this session, memory lane only)
- **`clue_core/memory.py`** — `MemoryScopeType.ACCOUNT` (last member); `ScopeStack.account_entity_id:
  UUID | None`; docstrings updated (account is live, workspace-local; three-way sibling branch).
- **`clue_config/schema.py` `MemoryCaps`** — `store_caps["account"]=10`, `bundle_budgets["account"]=4`
  (Doc M: account caps small).
- **Migration `50b778e4009a`** (off head `8aba77245267`):
  - `account_entity` gains nullable `workspace_id`/`brand_id`, composite FKs to `workspace` /
    `brand (brand_id, workspace_id)`, a `brand_id IS NULL OR workspace_id IS NOT NULL` CHECK, and
    `account_entity_workspace_anchor UNIQUE (id, workspace_id)`. Nullable = legacy-compatible (same
    deferral the spine used); the research-side writers that stamp these are follow-up.
  - `memory` gains `scope_account_entity_id uuid` + composite FK `(scope_account_entity_id,
    workspace_id) → account_entity (id, workspace_id)` (the isolation guarantee: `memory.workspace_id`
    is NOT NULL, so a NULL-`workspace_id` legacy account is unrepresentable = fail-closed, no global
    memory; cross-workspace refs unrepresentable). `memory_scope_type` / `memory_scope_shape` CHECKs
    re-added with the account arm; the generated `scope_id` column regenerated (`account` →
    `scope_account_entity_id::text`, immutable cast) since a generated expr can't be ALTERed.
  - Downgrade deletes account-scoped memory rows (+ their event/claim_ref rows) then restores the
    four-scope schema exactly (db-smoke runs on empty DBs).
- **`_store.insert_memory`** — account scope column mapping; binds `UUID(scope_id)` for account (the
  column is uuid, unlike the text scope FKs).
- **`write._check_scope_shape`** — account scope_id must parse as a uuid → else `MemoryPreconditionFailed`;
  existence/locality is the schema's job (IntegrityError, uncaught).
- **`assembly.py`** — `_STABILITY_ORDER` gains ACCOUNT (last, least-stable); assemble appends the
  account scope after project; cross-branch pairs generalized to **all** unordered sibling-branch
  combinations over {PRODUCT, PROJECT, ACCOUNT} via `itertools.combinations` ("a" from the earlier
  stability branch).
- **`lifecycle.record_kickoff`** — ages the account scope when the stack carries `account_entity_id`.
- **Tests** — `conftest.seed_spine` now seeds a workspace-local account (+ `seed_account` helper with
  a NULL-workspace legacy variant); offline scope-type/parity tests updated (account IS a member; the
  parity `_check_values` searches the account migration first, falls back to slice-1); new
  `tests/memory/test_account_scope_db.py` — 10 DB tests (round-trip, stability-order-last, cross-
  workspace + unstamped-legacy die at schema, malformed-id precondition, two-workspace isolation,
  per-instance reconciliation, account store cap, three-way cross-branch pairs, kickoff aging).

## Gates
`ruff format`/`check`, `mypy`, `lint-imports` (17 kept / 0 broken), offline suite, full DB suite +
rerun, db-smoke up→down→up on a throwaway DB — all green; `alembic heads` = one (`50b778e4009a`).

## Research-lane follow-up (NOT done here — CLAUDE.md `[B3×research]`)
Stamp `workspace_id`/`brand_id` on account creation; re-scope account domain/registry strong-key
uniqueness + contact strong-key to `(workspace_id, …)`; keep `merged_into` within-workspace; key
resolver/provider caches by workspace (no cross-tenant fallback / shared enrichment cache); supersede
the cross-tenant public-claim `reuse_scope` language (a `public_footprint` account claim is no longer
shareable across workspaces). Until then legacy accounts have NULL workspace and cannot own memory.
