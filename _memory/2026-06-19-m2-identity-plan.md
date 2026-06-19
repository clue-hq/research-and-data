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

## M2.2 — DONE & verified (ENG-106 → In Progress; commit pending push)
- Migration 0006: account_entity_embedding sidecar `vector(128)` + HNSW(vector_cosine_ops) + pg_trgm
  GIN trgm index on canonical_name. Migration imports EMBEDDING_DIM (parity-tested).
- identity/embedding.py: HashingEmbedder (deterministic blake2b feature-hash of char-trigrams+token
  unigrams → unit vector; offline). Embedder Protocol. embed_account (upsert). EMBEDDING_DIM=128.
- identity/policy.py: ResolutionPolicy + ScorerWeights (sum=1.0; strong-key budget domain+registry
  =0.15 → fuzzy caps at 0.85 < 0.95 auto-merge = the "never silently collapse" rule AS DATA).
  Operational policy lives LOCAL to identity (mirrors claimstore/merge.py MergePolicy precedent;
  NOT in config/schema.py — avoids M0.4 churn; satisfies "swap config, no code change" via param).
- identity/resolve.py: Observation/Candidate/ResolutionResult/ResolutionMethod. resolve() =
  deterministic-first (domain+registry exact for accounts; linkedin/email for contacts → score 1.0,
  ZERO embed calls) then probabilistic (pgvector ANN ∪ alias-array overlap ∪ trigram → top_k →
  feature scorer). resolve_many = bulk, per-row savepoint so a garbage row never aborts the batch.
  DELIBERATE: name is NOT a deterministic key (names collide) → only domain/registry short-circuit;
  name matches go through the scorer (so two same-name-different-geo surface as 2 candidates, no collapse).
- identity/canonicalize.py: plan_merge (pure) → CanonicalPlan; M2.3 applies via update_account.
- GOTCHA (real bug caught by tests): pg array operators are type-strict. `text[] && varchar[]` and
  `text[] || varchar[]` FAIL. Fix: bind array params as ARRAY(Text()) (not String) for `&&`/`||`;
  use expanding `IN :ids` (not `ANY(varchar[])`) for the uuid fetch. Fixed in resolve.py + entities.py.
- Tests: test_embedding/test_resolution_policy/test_canonicalize (unit) + test_resolve (DB, all 10
  §M2.2 criteria incl. zero-embed-call assertion via SpyEmbedder, IBM example, Apex no-collapse,
  bounded top_k, bulk garbage-safe, policy/embedder swap, dimension parity). make check GREEN: mypy
  60 files, import-linter 5/0, 285 passed; chain 0001-0006 round-trips base↔head on :5434.

## M2.4 — DONE & verified (ENG-118 → In Progress; commit pending push)
- NEW package `src/clue_research/locks/` (shared concurrency infra, conventions §6). NO Postgres
  migration. Added to import-linter source lists (core-forbidden, no-SDK, no-api) for completeness.
- deps: added `redis>=5` (runtime) + `fakeredis>=2.20` (dev) to pyproject; `uv sync` (redis-py 8.0.0).
- client.py: CLUE_REDIS_URL seam (mirror CLUE_DATABASE_URL; read from env, NOT config — locks carries
  no config dep). create_redis(decode_responses=True)/redis_lifespan/get_redis.
- entity_lock.py: EntityLock (SET NX PX atomic acquire; owner-safe release+renew via Lua
  compare-and-act with a uuid4 fencing token; TTL auto-expiry; blocking/non-blocking acquire;
  async-with). multi_lock/MultiLock (sorted-key order → deadlock-free). Metrics via obs sink
  (research.lock.acquired/contended/released/renewed) + traced_step span.
- rate_limit.py: RateLimiter token bucket via atomic Lua (refill+consume); now passed from client.
- Infra: docker-compose `redis` service (:6379) + Make redis-up/redis-down + .env.example CLUE_REDIS_URL.
- Verification container: throwaway `clue-redis-m2` on **:6380** (`docker run -d --name clue-redis-m2
  -p 6380:6379 redis:7-alpine`). CLUE_REDIS_URL=redis://localhost:6380/0.
- Tests: tests/locks/{conftest,test_entity_lock,test_rate_limit}.py — all §M2.4 lock criteria
  (mutual exclusion, TTL expiry vs renewal-not-preempted, owner-safe release, deadlock-free
  multi-lock cross-contention, context-manager, metrics) + rate limiter (burst cap, independent
  source keys, refill, 20-concurrent-respects-budget). Skip-when-no-redis verified (11 skip).
- GOTCHA: rate-limit refill test was timing-flaky at rate=20/cap=1 (50ms refill < call overhead);
  widened to rate=2/cap=1 (~0.5s refill margin).
- make check GREEN with DB+Redis: 296 passed (11 lock). import-linter 5/0, mypy 64 files.

## M2.3 — DONE & verified (ENG-112 → In Progress; commit pending push)
- Migration 0007: identity_review_task + identity_disposition (audit), enums review_status/
  review_resolution/disposition_kind (parity-tested vs identity/review.py enums; reuse entity_type).
  tenant_id text (forward-compat with M2.5, decision 3). open-task partial index.
- identity/policy.py: DispositionPolicy (auto_merge_threshold=0.95, review_low=0.70; bands as data).
- identity/review.py: disposition() band entry → {AUTO_MERGED|ENQUEUED|NEW_ENTITY}. auto_merge()
  executor (locks both via M2.4 multi_lock when redis given; plan_merge canonicalize survivor;
  mark_merged; idempotent; audit). Review queue: enqueue_review_task/get_task/list_open_tasks +
  resolve_merge_into/create_new_entity/not_a_match/split_merge. current_value_resolved (reads claims
  across the merged-member set via recursive CTE + M1 merge_claims; claims NEVER UPDATEd).
- KEY ER FIX (bug caught by tests): a merged loser must RELINQUISH its strong keys (primary_domain/
  registry_ids; contact linkedin/email) BEFORE the survivor absorbs them, else the partial-unique
  constraint rejects the canonicalization (two rows can't hold one domain). _relinquish_strong_keys.
  Loser becomes a pure redirect (id + merged_into).
- DESIGN: auto-merge only fires on score >= 0.95 = deterministic strong-key hits (probabilistic caps
  at 0.85 by M2.2's strong-key budget) → fuzzy matches always route to review (never silently
  collapse). disposition AUTO with no pre-admitted subject = "resolve to existing" (no new entity).
- Tests: tests/identity/test_review.py — 13 tests, all §M2.3 criteria (executor union+idempotent,
  3 bands, merge_into/not_a_match/create_new/split, claims-under-survivor-no-UPDATE row-version
  assert, config moves borderline pair, audit, enum parity, redis lock integration skip-gated).
- make check GREEN: 309 passed, mypy 65 files, import-linter 5/0; chain 0001-0007 round-trips base↔head.

## M2.5 — DONE & verified (ENG-124 → In Progress; commit pending push)
- Migration 0008: ALTER claim ADD tenant_id text + reuse_scope enum (DEFAULT 'public_footprint' so
  existing rows backfill to public — correct at M2: no tenant-private writers exist yet). scope↔tenant
  CHECK (public⟺NULL tenant, private⟺tenant set). Scoped partial index (entity,field,reuse_scope,
  tenant_id) WHERE superseded_by IS NULL. CREATE OR REPLACE the append-only guard adding the 2 cols
  (the M1.4 gotcha) + downgrade restores the 0007-era guard before dropping cols. Round-trips verified.
- core: ReuseScope enum + Claim.reuse_scope/tenant_id fields + validator (private⟺tenant_id).
- claimstore: claims.py INSERT/SELECT/_row_to_claim include the 2 cols. tenancy.py TenantScope
  (public_only/for_tenant/all_tenants/private_only → SQL predicate). merge.py: current_value/
  current_values/provenance_index now REQUIRE `scope` (fail-closed, decision 2); claims_for optional
  scope defaults ALL_TENANTS (audit/DSAR reader). Updated M1 tests to pass scope=ALL_TENANTS.
- identity: ReusePolicy (config-as-data; enabled=False = safe degradation → all private).
  reuse.py classify_reuse_scope (substrate §2 defaults: core.*/account.* public; crm_import +
  contact.*/account.resonance.* private) + stamp_reuse (writer stamps before insert; claimstore stays
  config-free — no inversion) + reusable_public_value (amortization hook) + dsar_private_claims (DSAR).
- TENANT_ID TYPE = text (decision 3, aligns with config.client_id). RLS NOT used (query predicate;
  db/engine.py has no per-tx GUC). Classifier in identity; TenantScope in claimstore.
- GOTCHA: the new claim_scoped_read index supersedes claim_live_entity_field in the planner's choice
  (it's a superset prefix). Updated test_live_claims_partial_index to accept either.
- Tests: tests/claimstore/test_tenant_isolation.py (enum parity, public-reuse-cross-tenant,
  ZERO private leakage to tenant B on every read path, scope↔tenant CHECK both ways, append-only
  guard rejects UPDATE of the 2 cols, model validator) + tests/identity/test_reuse.py (classifier
  maps §2 examples, disable-reuse degradation, stamp, amortization FRESH, isolation, DSAR selector).
- make check GREEN: 326 passed, mypy 67 files, import-linter 5/0; full chain 0001-0008 round-trips.

## M2 COMPLETE — all 5 issues done + verified. NOT pushed (local commits only).

## Adversarial review (workflow wjdqk2i5q: 6 lenses → per-finding verify, 38 agents) — 28 confirmed,
## 3 refuted. ALL confirmed findings FIXED in a follow-up commit. Highlights:
- **BLOCKER (real cross-tenant leak):** `current_value_resolved` (M2.3 merge-aware read) + DSAR
  selector read merged-member claims WITHOUT a tenant scope → would leak tenant_private across
  tenants. M2.5 hardened current_value/current_values/provenance_index but missed these two (added
  in M2.3, before scoping existed). FIX: `claims_for.scope` now REQUIRED (no fail-open default);
  `current_value_resolved` takes required `scope`; `dsar_private_claims(entity, tenant_id)` uses a new
  `TenantScope.private_for_tenant`. + regression tests proving zero leak on the merge + DSAR paths.
- MAJOR: `split_merge` left the loser domain-less (auto_merge relinquishes strong keys). FIX: record
  relinquished keys in the AUTO_MERGE disposition (observation_json payload); split restores them +
  frees them from the survivor. MAJOR: `auto_merge` silently re-pointed an already-merged loser →
  now raises `MergeConflictError`. MAJOR: scoring outputs were public → added `account.scoring.` to
  ReusePolicy private prefixes. MAJOR: "fuzzy can't auto-merge" was prose → `assert_fuzzy_cannot_auto_merge`
  binds it (max_fuzzy_score < auto_merge_threshold). MAJOR: rate limiter now reads the clock
  server-side (redis TIME, no NTP skew). MAJOR: EntityLock `async with` now auto-renews (heartbeat at
  ⅓ TTL) so a long holder isn't preempted.
- MINOR: contact new-entity now raises NotImplementedError (not None); import-linter Rule 6 forbids
  claimstore→identity/locks (no inversion, CI-enforced); blocking-acquire off-by-one fixed; vector_literal
  NaN guard; test gaps closed (current_values/provenance_index isolation, idempotency no-op count,
  concurrent lock mutual-exclusion, non-vacuous score-ceiling assertion).
- REFUTED (correctly): 3 (incl. a wall-clock-test flakiness nit that doesn't run in CI).
- Post-fix make check GREEN: mypy 67 files, import-linter **6**/0, **333 passed**; chain 0001-0008
  still round-trips. Review fixes committed separately on top of the 5 issue commits.

## Standing rules
- Commit locally at green checkpoints; NEVER push; no AI attribution; feature branch only.
- Implement sequentially (shared migration chain + identity pkg + core → parallel worktrees conflict).
- Run an adversarial-review workflow before declaring the milestone done (M1 pattern).
- First implementation attempt was reverted by the user (they wanted the plan first); now approved.
