# Production context S5 — product catalog, knowledge, and human selection

**Date:** 2026-08-15
**Branch:** `platform/onboarding-integration`
**Status:** S5-A through S5-F implemented and verified; S6 live browser/provider acceptance remains

## Delivered

- S5-A froze and registered the account-wide `client.product_catalog`, product-scoped knowledge
  fields, V2 company catalog, product profile/Product-KB cards, bounded cursors, topics, and
  refusal contracts without rewriting historical V1 resources.
- S5-B extends provider-neutral official-site materialization: fast company catalog,
  background-only per-product grounded extraction over the same immutable corpus, conservative
  alias/prior-lineage synchronization, exact product markers, no-refetch replay, and body-free
  DSAR-reachable lineage. Company fields are always account-wide even when a recon row already
  carries a product. Official-site-only competitor extraction intentionally remains empty because
  a company's own pages are not exhaustive competitor evidence.
- S5-C adds exact-version product readers and deterministic `ClientKnowledgeCard@2`,
  `ProductProfileCard@1`, and `ProductKnowledgeCard@1` compilers with bounded omissions and honest
  profile-only state.
- S5-D registers effect-free `list_product_knowledge@1` and `inspect_product_claim@1`. Their model
  schemas carry no authority; the production constitution injects exact client/product/version.
  Product artifacts/results bind client, stable product subject, and exact copied claims; streams
  remain body-free.
- S5-E migration `1043a61823f1` adds catalog lineage, product extraction scope, optional durable
  `product_kb_version`, V2 policy checks, and selection-gate state. The real AGENT_TURN fleet now
  composes company V2, active-project Stage-0, optional product profile, and optional Product-KB
  artifacts through the assembler and replay/DSAR path.
- S5-F adds production-only `open_product_selection_gate@1`. The model can open only the exact
  turn-pinned question; it cannot author candidates or confirm. The chat route validates the
  human's structured choice and calls existing human-only `confirm_project_product@1` atomically.
  Project repointing is refused. Frontend cards render durable product options and keep the
  selected option in history without showing a fake `$0.00` budget.
- New production resources: Head-of-ABM `v27`, Stage-0 skill `v14`, Recipe #0 `v9`. Historical
  profile/skill/recipe/card/policy resources remain immutable.

## Adversarial fixes found during the checkpoint audit

- Kept the shared Stage-0 skill available on the manual trial surface while withholding the
  production product-selection tool the trial cannot compose.
- Added all S5 tools to the closed out-of-order/replay toolbelt matrix and standing Recipe #0
  audit; fixed the stale v8 promotion assertion to v9.
- Product rejection/revision cannot carry a latent selected option; route and DB CHECK agree.
- A pre-existing recon `product_id` no longer causes company/catalog claims or their KB marker to
  be written into product scope.
- The selection gate's model-visible schema is empty; its trusted `source_turn_ref` comes only from
  the captured current turn.
- The reusable Head profile may pin selected-product readers while a particular turn has no
  Product-KB. The deepagent middleware now enforces the constitution-narrowed effective tool
  surface, so profile-only turns omit those readers without failing model construction; undeclared
  tools and a missing finalizer still fail closed.
- S5's new catalog operation was threaded through the existing C9 operation-count, empty-category,
  and retention-reach acceptance tests. The legacy discovery fixture's readiness denominator is
  now 12 rather than 11; its seven grounded facts correctly report `7/12` coverage.
- Frontend fixture state now retains the selected product ID just like the HTTP answer wire. This
  was found by the production TypeScript build after the runtime tests had passed.

## Verification and retained evidence

- Retained isolated PostgreSQL database: `clue_s5_20260815_c1`, stamped at sole Alembic head
  `1043a61823f1`. Downgrade to `d3672ccf43cc` and upgrade back to head passed after the final gate
  constraint change. Keep the database untouched for review.
- Final S5-A–F checkpoint matrix: 92 passed. Final adjacent context/gate/bootstrap/toolbelt
  regression matrix: 88 passed. Both ran against the isolated DB and include real fleet/real
  LangGraph composition with only the external model deterministic.
- Frontend: 231 passed, zero skipped; ESLint, design-system token build, and optimized Next.js
  production build passed. The build emitted only the pre-existing multiple-lockfile root warning.
- Ruff format/check passed across 1,434 files; mypy passed across 676 source files; 18 architecture/
  dependency tests and all 25 import-linter contracts passed. `git diff --check` passed.
- Clean migration database `clue_s5_migration_20260815_c1` passed the complete
  upgrade-head/downgrade-base/upgrade-head smoke and returned to sole head `1043a61823f1`.
- Post-fix repository-wide run on fresh `clue_s5_full3_20260815_c1`: 4,749 passed, 23 skipped,
  40 failed. The failure node set exactly matches the documented S3.1/S4-E branch baseline:
  merged design logging guard, monolithic shared-DB migration/registry contamination, downstream
  seeded-state collisions, and the pre-existing workspace-token guard. No S5 test failed.

## Failed attempts that informed the final gate

- The first recipe DB run exposed a stale v8-only test and then an incomplete standing recipe
  inventory missing `open_product_selection_gate@1`; both were corrected and the full matrix
  rerun green.
- An early focused DB command set `DATABASE_URL` rather than the repository's
  `CLUE_DATABASE_URL`, so DB tests skipped. It was rerun with the correct isolated-DB variable.
- `make contracts` first tried the sandbox-inaccessible default uv cache. It was rerun with
  `UV_CACHE_DIR=/tmp/clue-uv-cache` and all 25 contracts passed.
- The first post-S5 full run found real integration drift: constitution-conditional product tools
  were still treated as mandatory profile tools, C9 expected eleven instead of twelve extraction
  operations, and the legacy discovery fixture expected `7/11`. Each was corrected and rerun.
- A sandboxed Next build stalled after compilation began. It was stopped by its exact process
  session and rerun outside the sandbox, where TypeScript exposed the missing selected-product
  fixture field. After repair, the full build passed in 7.7 seconds.

## Remaining boundary

- S5 is production-composed but is not the S6 live browser/provider acceptance claim. S6 still
  owns a real onboarding/browser turn over retained provider evidence, next-turn refresh after
  background publication, operator/read observability, crash/timeout acceptance, and live model
  behavior. Do not describe this S5 closeout as that live canary.
