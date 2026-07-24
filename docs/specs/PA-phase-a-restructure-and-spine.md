# Phase A — Restructure, Spine & the workspace_id Rename (execution spec)

> **Status: EXECUTED** (2026-07-17; plan approved same day — see the deferral ledger in
> `_memory/2026-07-17-harness-era-code-mapping.md` for the items that left Phase A). Executes Doc R phases R0–R2 plus the
> founder-ruled spine + `workspace_id` rename (2026-07-17 rulings). Branch:
> `platform/workspace-restructure-v0` (Doc R §6). Local commits only; no push. Every step ends
> with green `make check`; A3/A4 additionally end with green `make db-smoke` on a clean DB.
>
> Governing principle (founder, 2026-07-17): conventions serve maintainability. No abstraction
> exists to satisfy an import rule; invalid states are made unrepresentable (constraints, types,
> keys), never exception-handled. Deviations from Doc R taken under this principle are flagged
> **[DEVIATION]** below for founder sign-off.

## Baseline facts (verified 2026-07-17)

- One distribution `clue-research` (hatchling, `src/clue_research`, 23 packages), no uv
  workspace; 12 import-linter contracts live in root `pyproject.toml`; alembic env imports
  the db seam (pre-move: `clue_research.db`), hand-written reversible migrations, one head.
- `make check` currently **fails**: 15 ruff errors — 1 × I001 in the uncommitted Settings slice
  (`config/__init__.py`), ~14 × E501 overlong docstrings in committed code (`identity/resolve.py`,
  `profiling/account.py`, `icp/source_profile.py`, …) — the last two commits landed ungated.
- `py_lumen_obs` source is reachable at
  `~/conductor/workspaces/clue-design/havana/py_lumen_obs` (9 modules, 839 lines) — copy-port
  unblocked (no cross-repo imports; Doc R R5).
- No code/table mentions `workspace` anywhere yet. Rename surface: `tenant_id` ≈ 204 src + 201
  test occurrences over 4 tables; `client_id` ≈ 606 src + 551 test occurrences over 15 tables;
  ~47 string-literal keys (SQL bind params, jsonb keys); span attr `ATTR_CLIENT_ID = "client_id"`;
  ~20 named indexes/constraints; 1 CHECK (`claim_reuse_scope_tenant`) and the claim append-only
  trigger reference `tenant_id`.

## A0 — Green the baseline, land the Settings slice (~½ day)

1. `ruff check --fix` (2 autofixes) + hand-wrap the E501 docstrings. Commit 1:
   `style: wrap overlong docstrings to restore the ruff gate` (committed-code fixes only).
2. Commit 2 — the founder's in-flight slice, as-is:
   `feat(config): extract ICP synthesis model into deploy-time Settings (CLUE_SYNTHESIS_MODEL)`
   (settings.py, gateway/models/__init__ wiring, stage0 constant move, script, .env.example,
   scripts/README, test).
3. `make check` green; `make db-up && make db-smoke` green. Tag the baseline mentally: this is
   the state Recipe-#1 outputs are measured against for the whole phase.
4. Create branch `platform/workspace-restructure-v0` from here.

## A1 — Doc R R0: workspace root + clue-obs (additive; ~1 day)

1. Root `pyproject.toml` gains `[tool.uv.workspace] members = ["libs/*"]` (grows in A2/A4) and
   `[tool.uv.sources]` workspace refs; root remains the `clue-research` package until A4.
2. **`libs/clue-obs`** (`clue_obs`, own pyproject, structlog dep): copy-port of `py_lumen_obs`
   (config, config_types, context, processors, redact, spans, testing, truncate), renamed and
   adapted per Doc R §4: one `clue_obs.setup(mode)` per entrypoint; bound-context spine
   `request_id / workspace_id / project_id / run_id / account_id / actor / profile_version`
   (**`workspace_id` from birth** — new code predates the A3 rename of old code); `log_span`;
   redaction chain (secrets always; personal-claim values ids-only); Console/JSON renderers via
   `CLUE_LOG_MODE`; per-run `run_<id>/logs/run.jsonl` sink; pytest capture fixture.
3. Wire `setup()` into the two real entrypoints that exist today: `api/handoff_app.py` lifespan
   and `scripts/*` (via one shared helper).
4. Enforcement, simple: ruff `T20` (print ban, with per-file allowances for the two demo CLIs)
   + one grep-shaped pytest banning `logging.getLogger` outside `clue_obs`. No new abstraction.
5. Existing `clue_research/obs` (OTel tracing) is **not** touched here — it folds into clue-obs
   in A2 when it moves anyway.

Gate: full suite green; zero file moves.

## A2 — Doc R R1: the promotion + the DRY batch (~1–1.5 days)

Move order (one move-only commit per package, `git mv`, zero logic changes):
`core → libs/clue-core/clue_core` · `db → libs/clue-db/clue_db` · `config →
libs/clue-config/clue_config` · `gateway → libs/clue-gateway/clue_gateway` · `locks →
libs/clue-locks/clue_locks` · `obs → merged into libs/clue-obs` (OTel tracing joins structlog).
Each move commit includes: the lib's pyproject, the mechanical import rewrite
(`clue_research.X` → `clue_X` across src/tests/alembic/scripts, all import forms), and the
import-linter/mypy/ruff config updates (`root_packages` grows; layers contract becomes
core < db < config < {gateway, locks, obs}; the other 11 contracts re-pointed).

**[DEVIATION — skip the R2 shims.]** Doc R ruled shim-and-deprecate to protect in-flight
branches; there are none (main fully merged; the Settings slice lands in A0). Shims for 6
packages × ~20 submodules each are exactly the ceremony the simplicity ruling bans. Instead:
rewrite every import in the same commit series and add a grep-guard test asserting no
`clue_research.(core|db|config|gateway|locks|obs)` import survives. Founder sign-off requested.

Then the DRY batch (separate, logic-bearing commits, each with tests):
1. `clue_core.normalize_host(url)` — replaces the three copies (`verification/identity_binding`,
   `verification/corroboration._host`, `resolvers/firecrawl`).
2. `clue_core.reference_time(claim)` — replaces `verification/freshness.reference_time` and
   `claimstore/merge._reference_time`.
3. `clue_core.decode_jsonb_scalar(raw)` — replaces the bytes-only decoders in
   `claimstore.claims`, `verification.eval_harness`, `verification.golden`.
4. **`claim_tagger` pre-insert hook** on `sources/waterfall.resolve_field`; contact-facet fill
   rejoins the shared waterfall; delete `profiling/contact/fill.py`'s re-implementation
   (−~115 lines). Exit test: contact claims still born with per-claim `identity_binding`
   stamped; profiling/contact + waterfall suites green.
5. `BudgetTracker` (consolidates the ×3 manual budget-threading) — attempted here; if it
   balloons beyond a day it is split out as its own follow-up (it blocks nothing in Phase B).
6. `docs/specs/_conventions.md §2` rewrite + CLAUDE.md/AGENTS.md/architecture-README structure
   references (Doc R §7).

Gate: full suite + contracts green; DRY greps clean; `db-smoke` green (alembic env now imports
`clue_db`).

## A3 — Spine + the workspace_id rename (~1–1.5 days)

**Order: rename first, then spine** (rename is pure; spine then lands in the new vocabulary).

### A3.1 The rename (founder-ruled: both `tenant_id` and `client_id` → `workspace_id`)

- **One reversible migration**: `ALTER TABLE … RENAME COLUMN` on all 19 tables (4 × tenant_id:
  `claim`, `identity_review_task`, `dsar_tombstone`, `outreach_objected`; 15 × client_id:
  `icp_spec`, `source_profile_override`, `pre_spend_policy`, `judge_policy`, `binding_policy`,
  `cadence_policy`, `positioning_policy`, `client_policy`, `project_run`, `source_yield`,
  `account_handoff`, `handoff_event`, `disposition`, `config_revision`, `review_session`);
  rename the ~20 named indexes/constraints to workspace-vocabulary names (`icp_spec_client` →
  `icp_spec_workspace`, `pre_spend_policy_scope_version` keeps its name but its column list
  updates automatically, etc.), preserving every `NULLS NOT DISTINCT` and partial-index WHERE;
  rename + recreate `claim_reuse_scope_tenant` → `claim_reuse_scope_workspace` (same
  expression over `workspace_id`); recreate the claim append-only trigger with
  `("workspace_id", "reuse_scope")` immutable. Downgrade mirrors everything. Old migrations are
  never rewritten (history stays).
- **Code rename**, mechanical + strict-mypy-verified: all `tenant_id`/`client_id` identifiers,
  the ~47 string-literal keys (SQL bind params `:client_id`, jsonb keys), and coherence renames
  where the id was the meaning: `TenantScope` → `WorkspaceScope` (factories kept),
  `ATTR_CLIENT_ID` → `ATTR_WORKSPACE_ID` (= `"workspace_id"`), handoff header `X-Client-Id` →
  `X-Workspace-Id` (internal, pre-treaty). Collision sites (code holding both names, e.g. the
  disposition backfill join `c.tenant_id = d.client_id`) collapse to the single name.
- **Deliberately retained**: the `reuse_scope` enum value **`tenant_private`** (+ its helpers) —
  it names claim-pooling semantics, not the tenancy id; renaming a stored enum value is data
  churn for zero clarity. `claimstore/tenancy.py` keeps its filename ("tenancy" is the concept).
  A grep-guard test enforces the end state: no `tenant_id`/`client_id` tokens in src/ or tests/
  outside the retained enum family and pre-A3 migration files.

### A3.2 The spine (`libs/clue-spine`, one small lib — the founder-delegated settlement)

> **Amended 2026-07-24:** the transitional one-brand-per-workspace limit is retired. A workspace
> owns multiple brand kits, and every project selects exactly one brand from that same workspace.
> Target accounts are workspace-local and brand-neutral; migration `068426c5ea34` removes their
> obsolete `brand_id` column and research plumbing.

- `clue_spine` imports clue-core + clue-db only. Contents: row dataclasses + plain async CRUD
  functions in the repo's existing raw-SQL style (`icp/spec.py` pattern). **No protocol, no
  repository layer** — one implementation exists.
- **One migration**, invalid-states-impossible by construction:
  - `workspace(workspace_id text PK, name, status CHECK IN ('active','archived'), created_at)`
    — text PK so legacy ids slot in unchanged.
  - `brand(brand_id PK, workspace_id NOT NULL REFERENCES workspace, name, created_at,
    UNIQUE(brand_id, workspace_id))` — multiple brands may belong to a workspace; the composite
    anchor pins dependent objects to the same workspace.
  - `product(product_id PK, brand_id + workspace_id with composite FK →
    brand(brand_id, workspace_id), name NOT NULL, aliases jsonb, status, created_at,
    UNIQUE(brand_id, name))` — a product can never point at a brand in a different workspace,
    structurally.
  - `project(project_id PK, workspace_id REFERENCES workspace, brand_id + workspace_id
    composite FK, product_id NULL REFERENCES product, name, status CHECK
    ('draft','active','archived'), created_at)`.
  - `project_run.project_id` — nullable `REFERENCES project` column (runs execute *for* a
    project; nullable because pre-spine runs have none).
- **Deliberately deferred**: FKs from legacy tables' `workspace_id` text columns to
  `workspace` — existing dev data has no workspace rows; the backfill + constraint lands when a
  real workspace-creation flow exists (build step 2 API). Fail-closed tenancy checks continue
  unchanged meanwhile.
- Tests: CRUD round-trips (including multiple brands in one workspace); constraint tests
  (cross-workspace product/project brand references fail as DB errors, not handler logic);
  db-smoke exercises the downgrade path.

## A4 — Doc R R2: research moves home + scaffolds (~½ day)

1. `git mv src/clue_research subsystems/research/clue_research` + its own pyproject (deps: the
   six libs); root pyproject stops being a package and becomes pure workspace root (members =
   libs/*, subsystems/*, platform/*; shared ruff/mypy/pytest/import-linter config).
2. Scaffolds, empty-but-contracted: `subsystems/memory/clue_memory`,
   `subsystems/content/clue_content`, `platform/toolbelt/clue_toolbelt`,
   `platform/agents/clue_agents`, `platform/fleet/clue_fleet`,
   `platform/projections/clue_projections`. (`platform/api` waits for R3 with build step 2;
   `api/` stays inside clue_research until then.)
3. Import-linter contracts extended: subsystems import libs only, never each other;
   `clue_agents` may import toolbelt + projections only; nothing imports `clue_research.api`.
4. Makefile final workspace pass; `docs/architecture/README.md` gains the layout per Doc R §7.

Gate: `make check` + `make db-smoke` green; scripts/01–06 chain still runs in stub mode
(Recipe-#1 regression sentinel).

## Sequence & effort

A0 (½d) → A1 (1d) → A2 (1–1.5d) → A3 (1–1.5d) → A4 (½d) ≈ **4–5 working days**, serial by
design (each step conflicts with everything; this is the quiet-point window).

## Risks & honest notes

- **Rename string-keys**: type-driven renames miss SQL/jsonb literals — swept by rg (census in
  hand lists all ~47), then the grep-guard test locks the door.
- **Trigger/CHECK recreation on `claim`**: append-only semantics must survive — existing
  claimstore immutability tests are the gate.
- **mypy strict across a multi-package workspace**: configured once at A1/A2; run per move
  commit so failures bisect trivially.
- **Telemetry key change** (`client_id` → `workspace_id` span attr): no dashboards exist yet;
  never cheaper than now.
- **Doc R deviations to sign off**: (1) shims skipped; (2) spine lands as `libs/clue-spine`
  (a box Doc R's tree didn't have); (3) `tenant_private` enum retained; (4) `X-Client-Id`
  header renamed. All justified above.
- Dev DBs are recreated freely (`docker compose down -v`); no production data exists.
