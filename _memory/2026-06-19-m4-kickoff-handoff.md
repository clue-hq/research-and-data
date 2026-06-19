# 2026-06-19 — M4 (Source Layer & Source Intelligence) kickoff / handoff

**Read this first when starting M4 in a fresh chat.** M4 will be implemented in a NEW chat, after a
PR from the integration branch is raised & merged to `main`. This note is the durable plan from the
M4 orientation workflow (8 agents mapped all 6 submodules + the existing seams).

## Starting state (verify before coding)
- M0–M3 + M2 are DONE and consolidated on **`integration/m2-m3`** (tip `d13eed3`). Single Alembic
  head **`0011`**. `make check` green (ruff, mypy --strict, import-linter 6/6, ~408 tests).
- **M4 must branch off `main`** once the integration PR is merged (so `main` carries M0–M3).
- Milestone **M4 — Source Layer & Source Intelligence** (project Research Subsystem). Spec:
  `docs/specs/M04-source-layer-and-source-intelligence.md`. Depends on M1, M2, M3.
- Existing seams M4 IMPLEMENTS/CONSUMES (do NOT rebuild): `core/resolver.py` (Resolver protocol),
  `core/source.py` (SourceManifest), `core/field.py` (FieldDef.tier_plan/freshness_ttl/gate/pass_kind),
  `icp/source_profile.py` + `icp/catalog.py` (**M3.3 already shipped the `source_profile` /
  `source_profile_override` tables + `ResolvedSourceProfile`** — M4.6 consumes them), `icp/compiler.py`
  (FieldPlan: tier_plan named here, executed by M4), `claimstore` (`insert_claim` — only write path),
  `resolvers/` + `adapters/` packages (scaffolded by M0.1, currently near-empty).

## Submodules & recommended BUILD ORDER
1. **M4.2 — Source Registry + capability manifests (ENG-111)** — FIRST. The swappability spine; the
   only new M4 table; everything else depends on it.
2. **M4.1 — Resolver protocol wiring + trust-tiered waterfall engine (ENG-105)** — the executable
   core (stop-at-first-confident). Depends on M4.2's `get_resolver` binding; testable against
   resolver-doubles.
3. **M4.3 — Modality-adapter framework fetch→adapt→extract (ENG-116)** — needed by M4.5's Firecrawl.
4. **M4.4 — Deterministic tier-1 resolvers: Clay/Apollo/ZoomInfo/BuiltWith/registries (ENG-122)** —
   no adapter dependency → can run in PARALLEL with M4.3 once M4.1+M4.2 land.
5. **M4.5 — CRM import (tier-1) + Firecrawl official-site scrape (tier-2) (ENG-126)** — after M4.3
   (Firecrawl uses the adapter pipeline). CRM claims must stamp `tenant_private`.
6. **M4.6 — Source Profiles serving + config-bounded Source Planner (ENG-129)** — last; reuses
   M3.3's `get_source_profile`/`ResolvedSourceProfile`, adds only registry-intersection + planner +
   a `source_yield` telemetry table. Gated on the M0.4 LLMGateway stub.

**Critical path:** M4.2 → M4.1 → M4.3 → M4.5 (four deep). M4.4 parallel off M4.1+M4.2; M4.6 parallel
off M4.2 (+ gateway stub). **Branch strategy:** mirror M3 — each submodule on its
`akeshri516/eng-NNN-<slug>` branch, STACKED in dependency order off the M4 base, merged back to one
integration branch for a clean join. Alembic **HASH** ids chained off head `0011` (never hand-pick
`0012`); two branches adding migrations off `0011` → `alembic merge`, never renumber. Gate every
branch on `make check` + `make db-smoke` on a **fresh per-branch** Postgres container (never shared).
Local commits only; no push/PR without explicit instruction; no AI co-author trailer.

## FIRST submodule (M4.2) — what to build, in order
1. **Migration FIRST** (`alembic revision -m source_manifest`, HASH id, `down_revision='0011'`),
   mirroring `0003_field_definition` / `0009` DDL precedent: JSONB cols, named CHECKs (incl. tier
   1..4), enum casts (Modality/EntityScope/IdentityBinding), comments, reversible `downgrade`.
   Columns per spec + the extensions `active/provider/auth_ref/rate_limit/requires_adapter/version/
   created_at`. Run `make db-smoke`.
2. **SourceManifest extend-vs-redefine** (Open Decision #2): `core/source.py` is frozen + extra=
   'forbid'. Recommend a thin `RegistrySourceManifest` wrapper (or optional fields) so staged-flow
   §7a core stays clean — extend, not redefine (conventions §4).
3. **Registry API** in a NEW shared package — recommend `clue_research/sources/registry.py` (M4.2-
   owned; NOT under `resolvers/`/`adapters/` which must stay independent — import-linter Rule 3):
   `register_source` (idempotent re-register/version-bump, mirroring M3.3's
   `SourceProfileRedefinitionError`), `get_source`, `list_sources`, `sources_for(field_key|class,
   tier?, entity_scope?)`, and the in-process `get_resolver(source_key)->Resolver` map that raises a
   clear "no resolver bound" for registered-but-unbound sources (the tier-4 Exa/Parallel
   placeholders) — M4.1 maps that to `stop_reason=no_resolver`, never a crash.
4. `yields` validation against the M1.3 registry (`is_field_key_or_class`, name the offender).
5. `seeds.py`: idempotent manifests for clay/apollo/zoominfo/builtwith/npi/duns/cik/lei (tier-1
   structured), crm (tier-1, identity_binding=strong), firecrawl_site (tier-2 text/pdf), + resolver-
   ABSENT tier-4 placeholders exa_deep/parallel_task.
6. Tests: yields-rejection, `sources_for` queries, `active=false` skipping, **no-secret-in-table**
   (auth_ref is a reference only), static check that nothing outside billing/obs branches on
   `manifest.provider`. Also the late-bound `catalog.validate_pack(known_source_keys=...)` join M3.3
   left open.

## DECISIONS — LOCKED by the user (2026-06-19) — STRICTLY FOLLOW
1. **confidence_threshold (M4.1):** carry it **engine-side as versioned config keyed by field_class**
   (e.g. firmographic 0.8, fuzzy resonance 0.6) that the waterfall reads. **Do NOT** add it to
   FieldDef / the field table / plan_hash. (D7: thresholds are config the engine reads.)
2. **SourceManifest (M4.2):** **wrapper** — a thin registry-row type wrapping the frozen
   `core.source.SourceManifest` + operational metadata (active/provider/auth_ref/rate_limit/
   requires_adapter/version/created_at). Extend, not redefine; keep the core concept clean.
3. **Stub-vs-live (every resolver):** CI is **hermetic** — recorded fixtures / fake doubles ONLY, no
   live Clay/Apollo/ZoomInfo/BuiltWith/CRM/Firecrawl calls. Live keys via `CLUE_*_API_KEY` referenced
   through `auth_ref` (**never** stored in the DB). A clean **stub/live toggle behind the Resolver
   seam** is required (the Clay↔Apollo swap call-counter test + cost tests depend on it). Firecrawl:
   wrap a config-selected backend behind the Resolver seam, **NOT** the MCP tools directly.
3b. **Shared-helper (before M4.4):** build the shared HTTP/SDK client wrapper + a typed
   `RetryableResolverError` + the `auth_ref`→credential resolver **ONCE**, in a **shared
   resolver-helpers module (or core/config)**, BEFORE the first concrete resolver. No per-provider
   re-implementation of HTTP/retry/auth.
4. **M0.4 LLMGateway (before M4.6):** **build M0.4's gateway FIRST** — do not stub-and-defer. M4.6's
   planner codes against the real gateway. (Exa Deep / Parallel Task remain separate tier-4 resolvers
   in M11 — NOT routed through the gateway.) → This adds an **M0.4 (LLMGateway) task at the FRONT of
   the M4 plan**; coordinate with the OpenRouter-gateway *docs* already on this branch (commit
   `088a067`) — that was documentation only; the client class still needs building.
5. **M3.3↔M4.6 (M4.6):** **reuse** M3.3's `get_source_profile`/`get_pack_source_profile`/
   `ResolvedSourceProfile.for_field_class` (migration 0009). Add ONLY: the **registry-intersection**
   (allowed set = profile ∩ what's actually registered — can't plan a source that doesn't exist), the
   **planner** logic, and a new **`source_yield` telemetry table**. **Never** duplicate the
   source_profile store.
6. **reuse_scope (M4.5 now + ENG-165 for M6):** public firmographic/technographic → `public_footprint`;
   **CRM (M4.5) + any ICP-derived/scoring claims → `tenant_private`** (via `identity.stamp_reuse`;
   `extraction_method=crm_import` → private). **M4 wires the minimal stamping NOW** so CRM/client data
   never leaks into the shared pool.
   **REMAINING WORK FOR M6 (ENG-165) — explicitly deferred, NOT M4's job:** the *broader, structural,
   fail-closed* foundation stays M6's first step — W1 declared `reuse_scope` on every field row; W2 the
   shared `core (FieldClass, pass_kind, signal_class) → ReuseScope` mapping both M2+M3 import; W3
   surfacing scope on the compiled `FieldPlan`; W4 reserving the score field-keys as `tenant_private`;
   W5 fail-closed authoring + a require-explicit-scope write guard (no silent public default); W6
   `client_id ↔ tenant_id` harmonization. **M4.5's stamping is the interim, per-writer guard; ENG-165
   makes it structural and fail-closed across all writers (M6/M8/M11/M12).** See
   `2026-06-19-reuse-scope-classification-foundation.md`.
7. **import-linter `sources → icp` (M4.6):** **permitted** — add an explicit allow for a one-way
   `sources → icp` import (M3.3 must keep NOT importing M4, so no cycle is created). If a rule blocks
   it, move/re-export the profile-serving wrapper rather than inverting the dependency.

## USER IMPLEMENTATION DIRECTIVES (apply to EVERY M4 submodule)
- **Strictly follow the locked decisions above** and the M4 spec; achieve the documented target state.
- **Thoroughly verify correctness AND completeness** of each submodule — well-planned and robust, not
  merely green. Run `make check` + `make db-smoke` on a **fresh per-branch DB** at every checkpoint.
- **Keep the Linear issues updated as you proceed** — Todo → In Progress → Done + a completion comment
  per submodule (mirror M3 hygiene).
- **Critically self-review when done** (ultracode: adversarial find→verify Workflow), then make the
  necessary fixes before calling a submodule complete.
- **Refer to the user ONLY for genuinely crucial decisions**; otherwise proceed.
- **Base branch:** M4 branches off **`main` AFTER PR #6 is merged** (so `main` carries M0–M3). Use the
  M3-style stacked branches; Alembic hash ids off head `0011`; never push without explicit instruction.
- (Ultracode is ON → use the Workflow tool for substantive M4 tasks.)

## REVISED build order (decision #4 adds M0.4 to the front)
**M0.4 (LLMGateway, build first)** → M4.2 → M4.1 → M4.3 → M4.5 ; M4.4 parallel off M4.1+M4.2 ;
M4.6 last (now unblocked because M0.4 is built first, not stubbed).

## INVARIANTS to enforce structurally (not just by prompt)
- **M4 ships TIERS 1–3 ONLY.** Tier-4 (Exa Deep / Parallel Task) are registered resolver-ABSENT
  placeholders; `get_resolver` raises "no resolver bound" → waterfall `stop_reason=no_resolver` (a
  correct empty+flagged output, never a crash) so M11's absence never fails a run.
- **stop-at-first-confident is a PRE-SPEND heuristic** — confident claims are still written
  `verification_status=UNVERIFIED` (M9 owns "verified"). Guard with an acceptance test.
- Resolvers **MUST** use `core.factories` (`account_claim`/`contact_claim`/`first_confident_claim`/
  `by_tier_ascending`/`TIER_ORDER`/`to_value_json`) — never hand-build `Claim`.
- The **waterfall is the only composer**; resolvers never import each other (Rule 3); the engine
  reaches resolvers ONLY via the registry binding, never by importing `resolvers/<provider>` or a
  provider SDK (Rule 4).
- **Conflict between tiers is DEFERRED to merge** (M1.2 `current_value`); the waterfall writes all
  returned claims and never resolves tier disagreements itself.
- `record_source_yield` (`obs/metrics.py`) currently keys by source_url/tier with a TODO to prefer
  `source_key` once M4 adds it — M4 should make claims carry `source_key` and re-key telemetry.
- pyproject Rule 4's SDK forbidden-modules list is illustrative — M4 finalizes exact import names per
  chosen client (+ likely a transcription provider + a PDF library for M4.3).
- Naming caveat (cosmetic): M2 claim table uses `tenant_id`, M3/icp uses `client_id` — be consistent
  when stamping CRM claims.

## Linear
M4 issues: ENG-105 (M4.1), ENG-111 (M4.2), ENG-116 (M4.3), ENG-122 (M4.4), ENG-126 (M4.5),
ENG-129 (M4.6). Prereq for the DOWNSTREAM milestone, not M4: **ENG-165** (reuse_scope fail-closed,
first step of M6). Mirror M3 Linear hygiene: Todo → In Progress → Done + a completion comment per
submodule.
