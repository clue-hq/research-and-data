# 2026-07-24 — Phase C4 implementation session

## Authority and decisions

- C4 is the governed Stage-0 workload and deterministic Recipe #0, not the C6 deepagent.
- Binding contracts: `PC-C0-step4-contract-freeze.md` and `PC-C4-stage0-recipe0.md`.
- Implementation plan recorded at
  `docs/superpowers/plans/2026-07-24-phase-c4-governed-stage0-recipe0.md`.
- One-way doors: immutable `Claim.product_id`; immutable KB/product lineage on confirmed ICPs;
  immutable product-context/readiness pins on the post-confirmation run.
- Fast/background recon remain separate durable lifecycles. A published Client-KB version is never
  enriched in place; the bounded fast pass and full background pass use separate research runs.
- Interview intelligence stays injectable/typed. The C4 minimal actor supplies classifications;
  C4 validates exact-quote entailment, authority, governance, routing, and persistence.
- Project intent is represented by a project-scoped routed `volunteered_statement` reference until
  C5 formalizes general recipe/project journals; no unowned project-state table is invented.
- The API composition root owns C1–C3 joins, concrete memory routing, scrape binding, tools, and
  projection aggregation.

## Baseline verified

- Branch `platform/workspace-restructure`, head
  `84266c5 feat(phase-c): integrate C1 C2 and C3`; worktree was clean at session start.
- C1–C3 are integrated at Alembic head `fc1f3d22a167`.
- Remaining Stage-0 ungated waterfall callers are exactly
  `stage0/client_kb.py::reverse_profile` and `stage0/import_accounts.py::_crm_enrich`.
- Legacy `start_project_run@1` begins at `REVERSE_PROFILING`; C4 needs a separate
  `start_confirmed_project_run` beginning at `DISCOVERY`.
- Current `Claim` has no product dimension; current `ICPSpec` has no Client-KB/product lineage.
- Current C3 integration deliberately leaves product claim construction and memory/project routes
  injectable for C4.

## Progress

- Architecture/codebase authority pass complete.
- Detailed implementation and verification plan complete.
- Implemented C4 contracts/config, random-hash migration `1b71451d48cd`, product-aware claim and
  ICP lineage plumbing, Stage-0 pre-spend closure, two-lane recon, interview routing, immutable
  product contexts, three-gate readiness, human override/product confirmation, and confirmed run
  entry at `DISCOVERY`.
- Added seven Stage-0 tools, three projections plus HTTP routes, deterministic Recipe #0 runner,
  flat versioned Stage-0 skill loader, and real official-surface scrape composition.
- The real recon tool binds a workspace-local snapshot sink and storage backend around each lane.
  It refuses before spend when scrape/storage composition is missing.
- Recon lane transitions and `run.step.progress` events commit atomically and 1:1. Provider/DB
  failures run inside a savepoint and leave a durable failed lane instead of erasing the recon.
- Fixed concurrency/replay edge cases during the final audit: advisory-lock recon/context dedupe;
  no conflict-updates against append-only triggers; deterministic interview claim/statement IDs;
  answer hash binding to the captured artifact; idempotent readiness overrides.
- C1 gap refs and C2 proposal/C3 ingestion refs are accepted by readiness and surfaced through
  `stage0_progress`; C4 does not import their tables.
- Focused DB-backed C4 test now proves URL-only fast/background separation, pre-spend-before-
  resolver, real scrape snapshot storage, and the exact durable event sequence.

## Closing verification

- `CLUE_DATABASE_URL=... make check` — green: Ruff, mypy, all 23 import contracts, and
  `2338 passed, 20 skipped`.
- Focused C4/C1-C3/API/resolver integration — `58 passed`.
- `alembic heads` — exactly `1b71451d48cd (head)`.
- `make db-smoke` — full upgrade → downgrade to base → upgrade to head passed.
- No external network calls, push, PR, or remote mutation were performed.
