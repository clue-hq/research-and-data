# Production context S6 — refresh, observability, and production acceptance

**Date:** 2026-08-15
**Branch:** `platform/onboarding-integration`
**Status:** implementation and company/product composition accepted; production release blocked by
the measured fast-lane latency exception; retained evidence must remain untouched for review

## Delivered

- Interview company/product claims now allocate replay-stable derived KB markers in the same
  transaction as the claims. Company and product scopes advance independently; project-only state
  advances neither; product claims require a human-confirmed product.
- Fast/background official-site phases publish one lineage: background markers overlay an explicit
  base version rather than erasing fast facts after a partial extractor.
- The production fleet emits privacy-safe card kind/version/hash/availability/omission telemetry,
  receipt reference counts, and governed tool outcomes. Metrics use bounded labels only.
- An always-on authenticated context-ref route exposes persisted hashes, versions, counts, and
  pointers without bodies or a hydration switch; scope mismatches remain indistinguishable 404s.
- Product selection resolves its exact project and company-KB pins from the trusted captured turn,
  fixing the live missing-pin refusal without adding model authority.
- `BACKGROUND_STARTED` now advances the durable recon lane at event time. Completion remains owned
  by successful Client-KB materialization.
- Frontend production builds use the supported webpack compiler because Next 16 Turbopack
  reproducibly deadlocked in this checkout. Both build roots are pinned to `apps/frontend`.

## Live acceptance

- Earlier company-path evidence remains in `clue_s6_live_20260815_c2` and its retained roots.
- Closure evidence is retained in `clue_context_release_20260815_live_c2` and
  `/private/tmp/clue-context-release-20260815-live-c2`.
- The real Clerk → Scrapling → Luna → Client-KB → browser/project → Terra chain published a real
  catalog, recorded human product selection, composed product profile/knowledge, used exact
  company/product readers, and advanced company/product interview versions independently.
- A v1 turn receipt remained immutable while background published v2; later turns observed v2/v3.
- Fast took 103.759 seconds, missed the 40-second deadline, and required Continue-anyway. This is a
  production blocker even though the product-context path completed correctly.
- Background continued the same 53-snapshot frontier with zero duplicate successful page fetches;
  two ambiguous Scrapling pages remain quarantined with no blind retry.
- Live execution exposed the multi-emitter turn-stream sequence race. The final allocator uses a
  separate transaction-scoped per-turn advisory-lock statement before the high-water read; 32
  independent connections and a final live 49-event turn prove contiguous unique allocation.
- Product selection is functional but its human response still renders as raw JSON. Password and
  Device-Trust entry were not rerun in the closure session.

## Verification

- Final focused S3–S6 matrix: 90 passed; release-quarantine guard: 2 passed.
- Frontend: 232 tests, lint, design-system build, and production build passed; 19 routes.
- Ruff passed; mypy passed across 679 source files; all 25 import-linter contracts passed.
- Clean Alembic upgrade/downgrade/upgrade passed at sole head `df332fd7904c`.
- A fresh C4 broad run matched the exact reviewed 32-node quarantine: 26 shared-DB/order failures
  and six owned Lane-E drift failures, with zero added/removed nodes and no S3–S6 failures. Script
  19 and the manifest now fail closed on any node-set change; this is not described as a green full
  suite.

## Review boundary

- Full evidence and typed live exceptions are in
  `docs/specs/FI-production-deepagent-context-composition-S6-acceptance.md`.
- Release blockers and the exact executable quarantine are tracked in
  `docs/specs/FI-production-deepagent-context-release-closure.md`.
- Do not store or copy credentials, user email, raw page bodies, or exact claim values into memory.
- Do not delete the named databases or roots until review sign-off.
