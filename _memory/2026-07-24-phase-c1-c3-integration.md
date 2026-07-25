# 2026-07-24 — Phase C1–C3 integration checkpoint

## Starting state

- Workspace/branch: `dar-es-salaam`, `platform/workspace-restructure`.
- C1, C2, and C3 were already merged through PRs 31, 32, and 33; starting head was `4760c8d`.
- The merged graph had three Alembic heads: `2211464d398f`, `316c84a7a3a4`, and
  `5ab2d13ca389`.
- Baseline `make check` was green before integration edits.

## Integrated

- Central toolbelt now exposes 24 tools, adding:
  - `research_account_gaps`;
  - `propose_field`, `decide_field_proposal`;
  - `propose_source`, `decide_source_proposal`;
  - `submit_ingestion`, `retry_ingestion`.
- Central projections now aggregate C1 coverage/history, C2 field/source proposal cards, and C3
  ingestion status. The C3 upload router is mounted when an ingestion storage backend is supplied.
- Added `phase_c_wiring.py` as the API composition surface:
  - C3 unmapped field targets route into C2's immutable proposal ledger;
  - C2's fixed tier-3 generic-web manifest and resolver bind/register together;
  - C3 contact claims use the API-root authoritative identity-binding classifier plus the
    production use-class tagger before immutable insert;
  - C3 erasure tombstones the exact tenant-private source claims append-only and idempotently,
    allowing artifact refcounts and physical cleanup to converge;
  - `build_ingestion_engine` supplies the proposal, contact-governance, and erasure routes by
    default while leaving C4 memory/project/product construction seams injectable.
- Added Alembic merge revision `fc1f3d22a167`; the graph has exactly one head.
- Closed a C0 audit gap found during integration: Pass-A scoring now receives the production
  `PreSpendGate`, and account profiling gates each fallback source rather than only the first
  planned source.
- Added a static inventory guard over every production `resolve_field(s)` call and the paid C3
  extraction ordering. The only explicit exceptions are the two C4-owned Stage-0 callers:
  `stage0/client_kb.py::reverse_profile` and `stage0/import_accounts.py::_crm_enrich`.
- Updated Phase-C status docs: C1–C3 integrated; C4 next.

## Verification

- Focused C1–C3/tool/projection/governance/ingestion/scoring suites passed.
- `uv run alembic heads` → one head, `fc1f3d22a167`.
- Disposable Postgres/pgvector on port 55090:
  - `make db-smoke` passed head → base → head;
  - DB-enabled `make check` passed:
    - Ruff format/check green;
    - mypy: 362 source files;
    - 23 import contracts kept;
    - pytest: 2328 passed, 20 skipped.
  - immediate full `uv run pytest -q` replay passed.
- `git diff --check` passed.
- Disposable container `clue-pg-phase-c-integration` was stopped and auto-removed. No shared
  database/container was modified.

## C4 handoff

1. Close the two exact Stage-0 pre-spend exceptions; update the static inventory from exceptions to
   gated callers.
2. Land C4's additive born-scope contract (`Claim.product_id`) and inject the product-aware
   `ClaimConstructionRoute` into C3.
3. Inject C4's Doc-M memory and project-state routes into C3; preferences/instructions must remain
   outside the claim store.
4. Build durable onboarding input, fast/background recon, interview statements, readiness +
   override, run pins, and the minimal Recipe-#0 entry.
5. Compose C1 coverage, C2 proposals/generic-web targeting, and C3 ingestion through tools and
   projections; do not replace their stores or grant the goal judge planning authority.
