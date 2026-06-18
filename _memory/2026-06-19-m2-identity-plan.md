# 2026-06-19 — M2 Identity Resolution — APPROVED plan + decisions

Branch `m2-identity-resolution` (NOT renamed; user wrote `feat/m2-identity` but left current branch).
Spec: `docs/specs/M02-identity-resolution.md`. Linear: ENG-100/106/112/118/124 (project "Research
Subsystem", milestone "M2 — Identity Resolution", label layer:identity). Plan verified by a read-only
workflow (7 agents: 5 issue analyses → order + adversarial). User approved order + decisions 1–6.

## Build order (= migration order; chain is single-headed, head was 0004)
1. **M2.1** Entity model (ENG-100) — migration **0005**. Unblocks all others + M3–M13.
2. **M2.2** Dedup→record-link→canonicalize (ENG-106) — migration **0006**.
3. **M2.4** Redis in-flight locks (ENG-118) — **no migration**. Built before M2.3 so M2.3's merge
   can use `multi_lock`. Only soft-depends on M2.1 (locks on the id value, no DB read).
4. **M2.3** Auto-merge + review queue (ENG-112) — migration **0007**.
5. **M2.5** Cross-tenant reuse + isolation (ENG-124) — migration **0008**. Highest blast radius
   (mutates M1 claim table + current_value read path); last so tenant_id contract is stable.

## Locked decisions (user-approved)
1. **claim.entity_id stays FK-FREE.** entity_id is polymorphic (account|contact via entity_type);
   a hard FK to account_entity breaks every M1 test (random ids, incl contact claim at
   test_provenance_flavors.py:298) and is unsatisfiable for contact claims. Soft ref enforced by the
   resolution service + entity_type. **Supersedes the M1.1 "FK deferred to M2" note.**
2. **M2.5 tenant scoping is FAIL-CLOSED:** a *required* tenant keyword on current_value /
   current_values / provenance_index / claims_for, with an explicit "all tenants" sentinel for
   audit/DSAR. Update existing M1 read-call tests in the same change. Add a zero-leakage test/path.
3. **tenant_id type = TEXT** (aligns with config.client_id: str), NOT uuid (spec wrote uuid).
4. **One shared `entity_status` DB enum** for both tables; core `AccountStatus` is the shared
   candidate→active→merged lifecycle (reused by ContactEntity; no separate ContactStatus).
5. **registry_ids uniqueness** via partial-unique EXPRESSION indexes on identifying namespaces
   (DUNS/NPI/CIK/LEI); keep the single JSONB column (a new identifying registry = +1 index).
6. **M2.4 infra**: add `redis>=5` + `fakeredis` (dev), `CLUE_REDIS_URL` seam (mirror CLUE_DATABASE_URL),
   docker-compose `redis` service + Make targets, skip-gracefully tests. (M0 disclaims Redis; M2.4
   provisions it — the spec's "blocked by M0 Redis client" is aspirational.)
7. Doc fix: reconcile `identity/README.md` ("imports only core/config/obs") to reality (identity
   writes Postgres; import-linter already permits identity→db/claimstore/config).

## Atomic co-land groups (correctness/security — must commit together)
- M2.1: entity tables migration + core ContactEntity + enum-parity test (DB enum ⟷ core StrEnum).
- M2.1: identity/normalize.py + the partial-unique(primary_domain) constraint (normalize at write).
- M2.2: account_entity_embedding migration + EmbeddingModel.dimension constant + dimension-parity test.
- M2.3: identity_review_task migration + review enums + DispositionPolicy config wiring + parity test.
- M2.5: 0008 (tenant_id+reuse_scope cols + reuse_scope enum + scope↔tenant CHECK + scoped index +
  CREATE OR REPLACE append-only guard adding the 2 cols + downgrade guard-restore) + core.Claim fields
  + claimstore claims.py (INSERT/SELECT/_row_to_claim) + merge.py (tenant predicate on all 4 readers)
  + reuse_scope enum-parity + updated test_claim_table expected-columns + immutable-update test.

## Verified design notes (from adversarial pass)
- surviving_id: read-time recursive walk with cycle detection (visited set → error, never loops);
  1-hop self-merge blocked by CHECK; multi-row cycle caught at read.
- M2.2 embedding: FIXED vector(N) dim constant + deterministic OFFLINE stub embedder (so the
  zero-embedding-call assertion + recall fixture run with no network); sidecar table (re-embed never
  rewrites entity row); pg_trgm trigram index for blocking; ANN index vector_cosine_ops / <=>.
- M2.5: classifier lives in identity/; ReusePolicy data shape in config/schema.py; claimstore stays
  config-free (writer stamps reuse_scope/tenant_id, insert just persists). Query-layer tenant
  predicate, NOT RLS (db/engine.py has no per-tx session-GUC plumbing, doesn't import config).
- import-linter does NOT restrict identity/ beyond core-kernel/no-SDK/no-api; identity→db/claimstore
  is machine-legal. Use claimstore's conn-injection style (pass AsyncConnection), no business SQL in db/.

## Verification env
- Host :5432 taken. `clue-postgres-m1` on **:5433** is POLLUTED by a parallel Conductor agent —
  it has stray `source_profile` / `source_profile_override` / `pack` tables (M3/M4 work) NOT in our
  0001–0005 chain; they make `alembic downgrade base` fail (field_class type has dependents). So M2
  uses a DEDICATED clean container **`clue-postgres-m2` on :5434**:
  `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:5434/clue`
  (`docker run -d --name clue-postgres-m2 -e POSTGRES_USER=clue -e POSTGRES_PASSWORD=clue
  -e POSTGRES_DB=clue -p 5434:5432 pgvector/pgvector:pg16`). Do NOT use :5433 for migration round-trip.
- Baseline at start: make check GREEN — mypy 54 files, import-linter 5/0, 225 pytest pass.
  Redis: redis-server/redis-cli present (brew); a throwaway redis container for M2.4.

## M2.1 — DONE & verified (ENG-100 → commit pending in M2 batch)
- Migration 0005: account_entity + contact_entity, one shared `entity_status` enum, partial-unique
  on normalized primary_domain + expression indexes on DUNS/NPI/CIK/LEI + contact linkedin_url/
  verified_email, GIN(aliases), merged_iff_target + no_self_merge CHECKs. NO claim FK (decision 1).
- core.ContactEntity added (+ export). identity/normalize.py (registrable_domain/normalize_name/
  name_key/canonical_registry_id) + identity/entities.py (insert/get/resolve_alias/surviving_id with
  cycle detection + update_account/set_status/mark_merged). identity/__init__.py seam. README reconciled.
- aliases column stores the NORMALIZED match index (name_key + normalize_name of name+aliases) so
  resolve_alias is an indexed equality check. registrable_domain folds www/scheme/port; no PSL yet.
- Tests: tests/identity/{conftest,test_normalize,test_entity_model}.py — all §M2.1 criteria incl. the
  FK-free regression (claim insert with orphan entity_id succeeds). make check GREEN: mypy 56 files,
  import-linter 5/0, 264 pytest pass; 0005 down→base→up reversible on the clean :5434 DB.
- GOTCHA: a `verified` `api` claim needs source_url (model rule); account_claim test must pass it.
- GOTCHA: registrable_domain returns None for a dotless bare word (it's a name, not a domain).

## Standing rules
- Commit locally at green checkpoints; NEVER push; no AI attribution; feature branch only.
- Implement sequentially (shared migration chain + identity pkg + core → parallel worktrees conflict).
- Run an adversarial-review workflow before declaring the milestone done (M1 pattern).
- First implementation attempt was reverted by the user (they wanted the plan first); now approved.
