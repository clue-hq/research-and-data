# 2026-07-24 — Phase C0 contract freeze executed

## Outcome

Completed Phase C0 as a documentation/contract slice. No Phase-C runtime/schema implementation
started.

Added:

- `docs/specs/PC-C0-step4-contract-freeze.md`;
- `docs/specs/PC-C1-coverage-and-goal-judge.md`;
- `docs/specs/PC-C2-field-source-proposals.md`;
- `docs/specs/PC-C3-ingestion.md`;
- `docs/specs/PC-C4-stage0-recipe0.md`.

## Frozen decisions

1. New cross-lane enums/reference models have one future home in `clue_core`; lane row models stay
   local.
2. Schema ownership is exclusive:
   - C1: coverage attempts/decisions;
   - C2: field/source revisions;
   - C3: ingestion jobs/segments;
   - C4: onboarding, recon, statements, the additive immutable `Claim.product_id` scope,
     additive Client-KB/product lineage on `ICPSpec`, product-context versions, readiness,
     overrides, and `DISCOVERY`-entry run pins.
3. Central toolbelt/projection registration and all cross-package API construction are
   integration-owned. Lanes add distinct modules only.
4. C1–C4 share fixed tool/projection names, reference-only results, and ten semantic integration
   journeys.
5. Pre-spend is closed for the current account/committee/contact/tier-4 paths, but the C0 audit
   found `stage0/client_kb.py` and CRM enrichment in `stage0/import_accounts.py` still ungated.
   C4 owns those closures; C1/C2/C3 extend the exact `SourceGate`/`ClaimTagger` contracts and
   temporal integration tests. No lane creates replacement gates.
6. C4 fixes the harness path by adding explicit post-confirmation run entry with matching
   Client-KB/ICP/product-context pins. The legacy full fixed-phase path remains Recipe #1.
7. C4 may code in parallel against frozen protocols/fakes, but integrates last after
   C1 → C2 → C3.

## Parallelization ruling

- Safe after this reviewed head: C1, C2, C3, and C4-owned substrate in four worktrees.
- Integration order: C1 → C2 → C3 → C4.
- C5 starts after Step 4 integrates.
- C6 starts after C5.
- C7 derivation/entailment/projection substrate may overlap late C6 once C1 + C7's C8
  prerequisites are integrated; C7 tool/run integration and the Phase-C exit remain after C6.
- C8 stays attached to consumers, never one miscellaneous worktree.

## Live-code findings used

- The repository already has `ToolResult` reference-only envelopes and read-only projections.
- Discovery coverage and Phase-C research coverage are different species; C1 may not overload
  `CoverageReport`.
- `SourceGate` and `ClaimTagger` are existing waterfall hooks.
- API integration tests already prove pre-spend decisions precede current paid paths and
  authoritative contact binding is born before insert.
- Artifact storage and the adapter/extractor pipeline exist; C3 builds durable upload orchestration,
  not a second storage/pipeline stack.
- `project_run` currently pins project/brand/ICP but not Client-KB/product-context.

## Verification / final state

Documentation-only change; no schema/runtime behavior changed.

- `git diff --check`: passed.
- child/parent relative-link target check: passed.
- `AGENTS.md` / `CLAUDE.md` parity: passed.
- `uv run alembic heads`: one head, `b366c985ca12`.
- `make check`: ruff format/check, mypy (327 source files), 23 import contracts, and pytest passed
  (`1307 passed, 967 skipped`). `CLUE_DATABASE_URL` was not configured in this shell, so DB-gated
  tests were skipped; the immediately preceding parent-plan commit had the full configured DB run
  green (`2254 passed, 20 skipped`). No DB/migration behavior changed in C0.

## Next action

Review and commit C0. Then branch all implementation worktrees from the same C0 commit:

- `platform/c1-coverage-goal-judge`
- `platform/c2-field-source-proposals`
- `platform/c3-ingestion`
- `platform/c4-stage0-recipe0`
