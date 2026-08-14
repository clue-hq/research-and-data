# Production context S6 — refresh, observability, and production acceptance

**Date:** 2026-08-15
**Branch:** `platform/onboarding-integration`
**Status:** implemented and accepted; retained live evidence must remain untouched for review

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

- Accepted retained database: `clue_s6_live_20260815_c2`.
- Accepted retained root: `/private/tmp/clue-s6-live-20260815-c2`.
- Shared frontend log: `/private/tmp/clue-s6-live-20260815-c1/logs/frontend.log`.
- Discovery/fault-repair evidence: `clue_s6_live_20260815_c1` and
  `/private/tmp/clue-s6-live-20260815-c1`.
- Clean migration database: `clue_s6_migration_20260815_c1` at sole head `1043a61823f1`.
- The real Clerk → Scrapling → Luna → Client-KB → browser/project → Terra chain released fast in
  35.804 seconds, continued the same frontier in background, and completed a production
  list-client-knowledge → exact-claim-inspection sequence through the real toolbelt.
- One provider attempt remained `spend_unknown` and quarantined with no blind retry. Live product
  catalog extraction was honestly empty/partial, so selection failed closed instead of presenting
  fake options.
- The retained C2 row preserves the pre-fix background-start timestamp defect. Its logs prove the
  actual start; the corrected activation transaction and idempotency are covered by the final DB
  regression. Do not rewrite the retained database.

## Verification

- Focused S1–S6 DB/API/fleet/replay matrix: 131 passed.
- Final timestamp/overlay/trusted-pin regressions: 3 passed.
- Frontend: 231 tests, lint, design-system build, and default production build passed; 19 routes.
- Ruff passed; mypy passed across 678 source files; all 25 import-linter contracts passed.
- Clean Alembic upgrade/downgrade/upgrade passed with one head.
- The monolithic backend suite retained the previously documented 40 shared-baseline failures;
  no S6-focused test failed. The clean DB gates separate migration/registry contamination from S6.

## Review boundary

- Full evidence and typed live exceptions are in
  `docs/specs/FI-production-deepagent-context-composition-S6-acceptance.md`.
- Do not store or copy credentials, user email, raw page bodies, or exact claim values into memory.
- Do not delete the named databases or roots until review sign-off.
