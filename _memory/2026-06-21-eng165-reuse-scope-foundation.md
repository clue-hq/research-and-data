# 2026-06-21 — ENG-165: fail-closed reuse_scope foundation (M6 prereq)

## Goal
First step of M6 (the prereq blocking ENG-133/ENG-138 claim-writers). Turn cross-tenant reuse
classification from an inferred prefix heuristic into a **declaration at the field** + make the
claim-write boundary **fail-closed**, so a client-private claim can never silently leak into the
shared cross-tenant base. Branch: `m6/discovery-and-pass-a-scoring` (off `beat0/contract-freeze-v1`
@ `f6138cd`). Per-branch DB: host Postgres 17.9 `clue_m6` (asyncpg reaches the host PG, NOT the
docker `clue-postgres` container — host has `clue`, `clue_m5`, `clue_m7`, now `clue_m6`).

## Decision: where it lands (agreed with user)
Implement the **complete contract foundation on this M6 branch**, then raise a merge PR to
`beat0/contract-freeze-v1`, then the other paused worktrees pull it. The foundation is a
self-contained set of edits at the branch tip; **raise the PR before any M6 feature code** so the
PR carries only the foundation (otherwise M6.1+ would leak into the shared base). This is a
**re-freeze** (touches the frozen `core` surface) — explicitly approved because all workstreams are
paused (M6/M9 planning-only; M7 only M7.1; M5 only M5.1 in review), so the additive change rebases
mechanically.

## Spec-vs-reality correction (important)
ENG-165 says "the write guard lives in M6." But Beat-0's import-linter **independence** contract
forbids M8/M11/M12 importing `discovery_scoring`, so a guard there can't be reused by them. Resolved
by putting the enforcement in the **claim-store write path** (`claimstore.insert_claim` →
`check_claim_writable`) — unbypassable by every writer, which is stronger than a per-milestone guard.

## What changed (W1–W6)
- **W1** `core/field.py`: `FieldDef.reuse_scope: ReuseScope | None`. Migration `82831d3fa4c5`
  (off head `eab62cbb1366`) adds nullable `field_definition.reuse_scope` (reuses the `reuse_scope`
  PG enum from 0008; **no backfill** — NULL resolves via the class default, so legacy rows + idempotent
  re-registration keep working).
- **W2** `core/field.py`: `default_reuse_scope(field_class)` (CORE/ACCOUNT→public,
  CONTACT/CONTACT_FACET/ACCOUNT_RESONANCE→private, **PACK→None = must declare**) + `resolve_reuse_scope(field)`
  (declared ?? default). Exported from `core`.
- **W2/classifier** `identity/reuse.py`: `classify_reuse_scope(..., declared_scope=None)` — precedence
  `not enabled → private` → `private method (crm_import)` → `declared_scope` (wins over prefix) →
  prefix heuristic → public.
- **W3** `icp/compiler.py`: `FieldPlan.public_fields` / `tenant_private_fields` partitions (by
  `resolve_reuse_scope`); `reuse_scope` added to `plan_hash` payload.
- **W4** `claimstore/packs.py`: `CORE_PACK` now reserves `account.scoring.fit` / `account.scoring.intent`
  (SCORING, `reuse_scope=tenant_private`, value_schema `{value:number}` + open). `_seed` gained a
  `reuse_scope` param. Closes the "ReusePolicy names `account.scoring.` but no field reserves it" gap.
- **W5 authoring** `icp/catalog.py` `_validate_pack_definition`: a `<pack>.*` field with no resolvable
  reuse_scope → `PackValidationError`. `icp/packs.py` `_field` gained `reuse_scope`; the three starter
  packs' `<pack>.*` fields now declare `PUBLIC_FOOTPRINT` (resonance contribution stays None→class default).
- **W5 write boundary** `claimstore/registry.py`: `ReuseScopeError` + `check_claim_writable(conn,*,field_key,
  value_json,reuse_scope)` — one registry read doing schema validation **and** the fail-closed reuse
  check (unresolvable scope → reject; field tenant_private + claim public → reject; claim *more* private
  than field is allowed, e.g. crm_import of a public-class field). `insert_claim` now calls it (field
  claims only; discovery claims skip, as before). Registry column plumbing: `_SELECT`/`_row_to_field_def`/
  `_INSERT`/`_comparable` carry `reuse_scope` (it is part of the redefinition-equality contract).
- **W6** `tenant_id` == `client_id` (text, per 0008) — M6 writers pass `client_id` as the tenant at the
  write boundary; documented, no code change needed in the foundation.

## Test fixes (the guard is correct; fixtures predated the contract)
- `tests/resolvers/test_resolvers.py::test_npi_activates...` registered an **undeclared** `healthcare.npi`
  → declared it `PUBLIC_FOOTPRINT` (a public registry id).
- `tests/claimstore/test_provenance_flavors.py` (3 tests) inserted **public-stamped `contact.facet.*`**
  claims (personal → must be private) → switched those raw inserts to `validate_field=False` (they test
  the append-only trigger / weak-binding merge / mode persistence, not the reuse contract; matches the
  tenant-isolation suite's pattern).
- New tests: registry (column present, reuse_scope round-trip + redefinition, W4 reserved keys),
  tenant-isolation (leak-guard reject, more-private allowed, undeclared-pack reject, two-tenant
  score-leak regression through the real write path), classifier (declared-scope precedence), compiler
  (partition), packs (authoring fail-closed).

## Verification
- `make check` (no DB): ruff ✓, mypy ✓ (108 files), import-linter ✓ (10 kept / 0 broken).
- Full pytest against `clue_m6`: green (was 4 failures from the guard — all fixed at source).
- `db-smoke` (up→down→up on clue_m6) + `alembic heads` single (`82831d3fa4c5`).

## Follow-ups
- **M4 waterfall** stamps reuse via prefix/method only; it does not yet pass the field's
  `declared_scope` to `classify_reuse_scope`. Harmless today (no declared-private PACK field is
  waterfall-resolved, and `insert_claim` is the backstop), but a declared-private pack field resolved
  via the waterfall would be stamped public and then **rejected at insert** — fix by threading
  `field_def.reuse_scope` into the waterfall's classify call when M8 needs it.
- After PR-merge to `beat0/contract-freeze-v1`: rebase `m7/*`, `m9/*`, `m5/*` onto the new base
  (additive, mechanical). Then resume M6.1 (ENG-128).
- Update CLAUDE.md/AGENTS.md backlog reuse-scope bullet → resolved by ENG-165.
