# Phase B — platform infra core: worktree briefs & shared-surface treaty

**Status:** open (briefs ratified 2026-07-21; worktrees not yet started)
**Integration branch:** `platform/workspace-restructure` — all three worktrees branch from the
R3 commit on this branch and **integrate back onto this same branch** (founder ruling,
2026-07-21). Local commits only; no push.
**Authority:** harness doc §9 (build sequence), Doc R (tree + phases), Doc M (memory substrate),
`docs/specs/_conventions.md` (workflow, gates), CLAUDE.md backlog. This spec adds no new
architecture — it fixes *scope boundaries* so three parallel worktrees cannot collide.

---

## 1. Current state (what a worktree may assume)

Read this instead of re-deriving the tree. As of the R3 commit on `platform/workspace-restructure`:

- **Phase A is complete** (see `PA-phase-a-restructure-and-spine.md`, closed): R0 (uv workspace
  root + `libs/clue-obs`), R1 (core/db/config/gateway/locks/obs promoted to `libs/`, shim-less,
  guarded by `tests/test_structure_guards.py`), A3.1 (`tenant_id`/`client_id` → `workspace_id`
  everywhere, migration `b61cd4887129`), A3.2 (**object spine**: `libs/clue-spine` —
  `workspace → brand → {product, project}`, plain typed functions, DB-constraint correctness,
  migration `98422adaaa38`), R2 (scaffolds: `subsystems/memory`, `subsystems/content`,
  `platform/{toolbelt,agents,fleet,projections}`), plus the deferral close-outs
  (`claim_tagger`, `BudgetTracker`, `model_call_usage` gateway event, DB-suite rerun idempotency).
- **R3 is complete** (this commit): the composition root moved —
  `subsystems/research/clue_research/api` → **`platform/api` (package `clue_api`)**. The old
  dotted path `clue_research.api` is dead vocabulary (grep-guarded). Rule 5 ("nothing imports
  the api app layer") now covers every workspace package.
- **Gates at this baseline:** `make check` green (ruff · mypy 281 files · import-linter
  **16 kept, 0 broken** · offline suite 1158 passed) · full DB suite 1938 passed / 14 skipped ·
  `make db-smoke` reversible up→down→up on a throwaway DB. One alembic head.
- The linear research pipeline is **runnable end-to-end today** via `scripts/01–06` (stub gateway
  without keys). It is the standing regression harness (§5).

## 2. The three worktrees

Phase B = harness build steps 0 + 1 + Doc M slice 1, in parallel. (Step 2 — toolbelt +
projections/SSE — is **B4**; it opens as its own worktree after B1 integrates and is *not*
covered by these lane rules.) Each worktree: spec first (`docs/specs/PB-B<n>-….md`, acceptance
criteria = the exit gate below), then implementation, per the M0–M13 workflow.

### B1 — fleet worker (build step 0)

**Goal.** The detached `CampaignRunWorker`: a separate process that drives existing M7
campaign-run state machines + M8A per-account graphs as jobs — per-run **driver lease**, task
drain, tier-priority queue. No new research behavior; the pipeline gains kill-resumability.

**Owns (may create/edit):**
- `platform/fleet/clue_fleet/**` (the package: worker process, lease, drain, queue).
- `subsystems/research/clue_research/durable/**` — *minimal* seam edits only (e.g. exposing a
  drain/claim-next seam); the state machine, scheduler, `BudgetEngine`, and idempotency ledger
  semantics do not change.
- New alembic migration(s): lease/queue/worker tables (hash revision id off current head).
- `tests/fleet/**`, additions under `tests/durable/`.

**Must not touch:** `sources/`, `resolvers/`, `adapters/`, `compliance/`, `verification/`,
`subsystems/memory`, any storage code, `clue_api` wiring (§4).

**Exit gate:** kill -9 the worker at ~40% of a 500-account stub-mode run → restart → resume
completes **exactly-once** (no double spend on the `(account, field, tier)` and
`(campaign_run, phase)` idempotency keys); plus lease takeover (a second worker may not drive a
leased run; takes over after expiry).

### B2 — storage (build step 1)

**Goal.** Durable artifact storage: `StorageBackend` protocol with fs + S3-compatible
implementations behind settings; the `artifact` table; evidence-snapshot wiring so provenance
stops pointing at rot-prone live URLs; the DSAR hook so erasure reaches snapshots; millicredit
ledger **groundwork**.

**Owns (may create/edit):**
- **New lib `libs/clue-storage` (`clue_storage`)** — protocol + fs + S3 impls. Registering the
  new package touches root `pyproject.toml` (mypy files/path, first-party, root_packages,
  contracts) — mechanical, append-only (§3.4).
- New alembic migration: `artifact` table (hash id off current head).
- Snapshot wiring at fetch time: `sources/`, `resolvers/`, `adapters/cache.py` (the
  content-addressing precedent lives there).
- DSAR hook: `compliance/dsar.py` (+ its tests) so erase/sweep tombstones reach stored snapshots.
- `libs/clue-config` settings: `CLUE_STORAGE_*` (append-only, §3.2).
- `tests/storage/**`, additions under `tests/compliance/`, `tests/sources/`.

**Hard scope rule (founder-ratified):** millicredit groundwork is **additive-only** — a new
mapping table / read path over the M13.4 cost ledger. **Zero changes** to `durable/budget.py`
(`BudgetEngine`), `budget_event`, or existing ledger schema — B1 builds against those. If real
ledger changes prove necessary, they move out of B2 and land serially after B1 integrates.

**Must not touch:** `durable/**`, `platform/fleet`, `subsystems/memory`, `clue_api` wiring (§4).

**Exit gate:** fs ↔ S3 swap via settings alone (same suite green under both); snapshot
round-trip (store → content-address → retrieve byte-identical → provenance carries the artifact
ref); DSAR erase removes the snapshot; `db-smoke` reversible.

### B3 — scoped memory slice 1 (Doc M)

**Goal.** The second substrate: memory schema on the spine's scope ids, the **two enforced
seams**, inject-only deterministic assembly with the ids-never-bodies bundle journal,
workspace kill-switch, provenance-graded born trust, write-time reconciliation (+ its eval
golden set).

**Owns (may create/edit):**
- `subsystems/memory/clue_memory/**` — the whole substrate lives here.
- New alembic migration(s): `memory`, `memory_claim_ref`, … (hash id off current head).
- `libs/clue-core` **additions only if Doc M's seam protocols must be importable by future
  consumers** — append-only contract-delta, new file(s) preferred over editing existing ones.
- `libs/clue-config` settings: kill-switch flag (append-only, §3.2).
- `tests/memory/**`.

**Bindings already ruled:** `scope_type` enum value is **`project` from birth** (never
`campaign` — founder confirmation 2026-07-17, recorded in Doc M §4's naming note); scope ids
reference `clue_spine` rows (FKs, invalid states die at the schema); facts stay claims — the
species check + body rule reject fact-shaped/personal-claim-quoting submissions at the write
seam; `workspace_id` is the tenancy key (never reintroduce `tenant_id`/`client_id` —
`tests/test_workspace_rename_guard.py` will fail you).

**Must not touch:** `subsystems/research/**` (Rule S1 — subsystems are independent; enforced),
`platform/**`, `durable/`, storage code. Slice 1 needs **no** `clue_api` wiring (its first real
writer — the kickoff interview — arrives in Phase C step 4).

**Exit gate:** seam contract tests (both seams; species-split rejection cases); assembly
determinism on a golden set (same inputs → byte-identical bundle + journal of ids, never
bodies); kill-switch blanks assembly for the workspace; caps/freshness behavior per Doc M;
`db-smoke` reversible.

## 3. The four shared surfaces (the treaty)

These are the only places two worktrees may legitimately touch the same file. All four are
**append-only**; conflicts are resolved at integration, in integration order (§5), never by
pre-coordinating edits across worktrees.

1. **Alembic head.** Each lane chains its migration off the head it branched from, with
   Alembic's default **hash revision id** (never hand-picked). Three heads at integration is
   *expected*; the integrator runs `alembic merge` per the CLAUDE.md convention. Every migration
   hand-written + reversible; enums mirror `core.enums` with parity tests.
2. **`libs/clue-config/clue_config/settings.py`.** Append new fields only (prefix per area:
   `CLUE_FLEET_*`, `CLUE_STORAGE_*`, `CLUE_MEMORY_*`). Never rename/retype an existing field.
3. **`libs/clue-core/clue_core/enums.py` + enum-parity tests.** Append new enums/members only;
   keep DB enum names and parity-test rows in the same commit as the migration that adds them.
   Prefer package-local enums (e.g. `durable/enums.py` style) when only your lane reads them.
4. **Root `pyproject.toml` + `clue_api` (the composition root).** Adding a new package (B2's
   `clue-storage`) appends to mypy files/path, first-party, `root_packages`, and contracts.
   **No worktree commits wiring into `platform/api/clue_api`** — wiring commits are written *at
   integration on the integration branch*, one per slice, by the integrator (same deferral
   pattern as M9.1 AC-6 / M9.4's pre-insert stamp). This keeps the one file every lane needs
   out of every lane's diff.

If your lane genuinely needs an edit outside its owned surfaces and outside these four: **stop,
record the need in `_memory/`, and leave it for integration** — do not edit another lane's
package.

## 4. What "integrate on the current branch" means

- Worktree branches: `platform/b1-fleet-worker`, `platform/b2-storage`, `platform/b3-memory`
  (area/name convention), all cut from the R3 commit of `platform/workspace-restructure`.
- **Integration order: B2 → B3 → B1** (purely-additive first; the heaviest `durable/` touch
  last), each merged onto `platform/workspace-restructure` when its exit gate is green.
  B4 (toolbelt + projections + SSE + the step-2 additions) opens after B1 integrates.
- At each merge: resolve the append-only surfaces, run `alembic merge` if heads > 1, then the
  full gate battery (§5). The integrator writes that slice's `clue_api` wiring commit (if any)
  immediately after its merge.

## 5. Standing gates (every slice, before its integration merge)

1. `make check` green — ruff · mypy · import-linter (16+ contracts, 0 broken) · offline suite.
2. Full DB suite green on a fresh DB **and** on rerun (rerun-idempotency is a kept property).
3. `make db-smoke` (up → down → up) on a **clean per-branch throwaway DB** — exactly one head
   after any `alembic merge`.
4. **Recipe #1 regression:** the `scripts/01–06` chain still completes end-to-end in stub mode
   with unchanged outputs. The harness must never break the pipeline it re-packages.
5. `_memory/` session note per worktree (progress, decisions, failures, follow-ups — the
   session-memory protocol).

## 6. Backlog items slotted into Phase B

- **B4 ride-along (not B1–B3):** `pre_spend_policy` `NULLS NOT DISTINCT` migration + loader
  tie-break (CLAUDE.md backlog, M9.1×M0.4).
- Everything else in the backlog (api-root gate wiring, binding pre-insert stamp, merge
  retention-awareness, verdict-rationale redaction, EqualityMode relocation) stays on its
  already-scheduled Phase C timing — **do not** pull these into a Phase B lane.
