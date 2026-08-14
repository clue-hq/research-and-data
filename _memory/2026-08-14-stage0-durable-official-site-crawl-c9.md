# 2026-08-14 — Stage-0 durable official-site crawl C9

## Outcome

C9 is complete. The executable manifest covers all 53 §20 cases and all nine crash boundaries.
The hardened C0–C9 target passed 200 tests on a new isolated database. Migration, frontend,
Ruff/mypy/import-contract, and adversarial-review gates are complete. C10 remains the default-off
live provider/browser/cutover gate.

## Implementation

- Added `tests/fixtures/official_site/c9_acceptance_matrix.json`, an exact case/crash manifest,
  plus an AST guard that refuses stale or missing node IDs.
- Added real-PostgreSQL cross-slice acceptance for pre-dispatch fencing, later-run freshness,
  stale publication fencing, receipt-based reconciliation, coordinator policy revalidation,
  robots refusal, category-empty extraction, and complete retention reach.
- Recovered provider-operation results now pass the same redirect/DNS/domain/MIME/size/link policy
  as ordinary fetches. Successful responses with a forged request URL or provider identity are
  refused, trusted identities are restored, bytes/links are dropped, and possible spend remains
  recorded.
- `FetchAttemptRef` now carries the durable provider request ID so a cold reconciler can look up
  the original charged call rather than invoking a new acquisition.
- Official-site evidence reach now includes pages, observations, edges, aliases, attempts,
  snapshots, checkpoints, extraction operations/model-response artifacts, and claims/artifacts.
  Claim discovery follows `source_operation_ref`, so a crash after claim insert but before the
  operation's `claim_ids_json` publication does not make data unreachable.
- Updated the parent plan, specs index, and detailed C9 acceptance record. No rollout flag,
  browser release behavior, migration, or live provider configuration changed.

## Verification

- Final fresh DB `clue_c9_official_site_20260814_final_v2`: migrated from empty to sole head
  `a57463ec42ea`; complete C0–C9/API/setup/config target 200 passed.
- Separate fresh DB `clue_c9_official_site_20260814_v2`: Alembic
  `upgrade head -> downgrade base -> upgrade head` passed.
- Migration tests alone on `clue_c9_migration_isolated_20260814`: 3 passed.
- Focused final C9 adversarial module: 13 passed.
- Ruff: 1,392 files; mypy: 658 source files, zero issues; import-linter: 25/25 contracts.
- Frontend: 228 tests, design-token build, ESLint, TypeScript, and Next.js production build passed.
- `git diff --check` was green during review.

## Baseline separation

- A monolithic full-backend run on a separate untouched DB reproduced 36 failures and 25 expected
  environment skips. Three are independent pre-existing baseline defects: stale Stage-0 v9 skill
  path expectation, a logging scanner entering excluded `subsystems/clue-design`, and a C6.3
  context fixture with no current-user instruction.
- Its three migration failures pass 3/3 alone; in the monolithic run they conflict with active
  session-scoped DB fixtures and cause 30 later schema/registry cascades. One representative
  Lane-D failure passes independently.
- Reusing a previously populated test DB also produced source-manifest collisions. The final C9
  matrix therefore ran once on its own pristine DB, as required.
- All failures are classified; none is a C9 regression. No C9 P1/P2 remains after final review.

## Retained evidence and boundary

The diagnostic, final, backend-baseline, and migration-isolation databases are retained; none was
dropped or reset. No Firecrawl, Scrapling, OpenRouter, Clerk, or browser call occurred in C9. C10
must still prove real provider receipts, live browser/API/log/DB/artifact correlation, fast release
timing, same-frontier background continuation, and replay before activation.

No secrets, raw page/model bodies, full URLs, receipts, tokens, email addresses, Clerk subjects, or
claim values are recorded here.
