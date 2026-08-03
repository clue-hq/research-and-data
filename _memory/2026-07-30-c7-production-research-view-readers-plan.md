# C7.9 production research-view readers plan

**Date:** 2026-07-30
**Branch:** `platform/c7-research-views`
**Outcome:** C7.9 production read stack implemented and automated gates closed; activation remains
default-off pending the user's Exa-first quality trial

## Why

The C7 post-closeout review proved that the deterministic contract/composer and serving seams
exist, but there is no production `StatementGovernanceReader`, no real database-backed reader set,
and no production caller of `build_research_view_composer`. The read flag must remain off.

## Plan

Authoritative plan:
`docs/superpowers/plans/2026-07-30-c7-production-research-view-readers.md`.

The plan freezes:

- one request-scoped read-only repeatable-read unit of work;
- a shared exact scope resolver;
- durable canonical entity versions and canonical-member claim handling;
- explicit versioned field-to-section routes;
- product-aware current claims and run/product-correct scores;
- subject-bound journal activity;
- one shared batch governance/evidence evaluator;
- the C7-D7 support-use fix and flagged-root/redacted-support precedence;
- retention/objection sweep parity;
- eight real readers, one production runtime builder, fail-fast activation, and owner-reference
  resolution;
- Exa-only -> scraper comparison -> Postman/API manual validation.

## Implemented state

- Alembic head `6a7f8eed5b23` adds canonical identity versions, field-route metadata,
  exact-subject activity, display policy, product-aware change reports, product-safe handoff
  uniqueness, and the account-run owner lookup index.
- Production scope, direct/derived claim, score, committee, coverage, activity, canonical subject,
  governance, evidence authorization, and owner-reference adapters are wired through one
  read-only repeatable-read runtime.
- API, tools, fleet, snapshots, recheck, evidence, handoff, and owner-reference reads share the
  same production composition.
- C7-D7 transitive support-use enforcement, flagged-root precedence, sweep parity, product/run
  scoping, score supersession, and shared strict JSON parsing are closed.
- A read-only persisted-view CLI, Exa-first runbook, and sanitized Postman collection are present.
- No flag was enabled. No live Exa, scraper, or customer-data run was performed.
- Unrelated existing worktree changes were left untouched.

## Verification

- Ruff passed for changed Python; mypy: 446 files.
- Import contracts: 24/24 over 508 files and 3,799 dependencies.
- Focused C7 and adjacent database suites passed.
- Production composition query ceiling passed at 1/25/100 statements.
- DB-enabled full repository suite passed with three known order-sensitive observability tests
  deselected; all three passed separately.
- Alembic has one head and a clean throwaway database passed head -> base -> head.
- CLI help, Postman JSON, and scoped diff checks passed.

## Failures found and resolved during implementation

- A direct import from narrative into durable broke the subsystem contract; replaced with an
  injected subject-activity append seam.
- Active agent profiles pinned the old research-view tool schema hash; regenerated exact pins and
  expected manifest digests.
- Field-route deletion blocked pack cleanup; the FK now cascades.
- Legacy handoff lookup could return another product; product is part of its durable key, read API,
  events, and canonical reference.
- Direct project-run-pinned routes were only product-filtered; current-claim queries now constrain
  the allowed project/account run IDs.
- Production startup test left global registry rows behind and broke rerun order; it now removes
  exactly the fields introduced by the test.
- A migration smoke on a used test DB correctly failed an older C5 downgrade data guard; the
  required clean-database round trip then passed.

## Next exact task

Persist one normal governed Exa-only run for a chosen account/contact, then execute
`scripts/07_research_view_trial.py` with its real workspace/project/run/subject IDs. Judge that
structured output before enabling any scraper or HTTP flag. If accepted, follow
`docs/runbooks/research-views.md` for the scraper comparison and Postman/API canary.

## Session closeout

- Implementation commit: `b88db2c` (`feat(c7): wire production research-view read stack`).
- Plan/runbook closeout commit: `c365e1d` (`docs(c7): close production reader activation plan`).
- Branch: `platform/c7-research-views`; nothing was pushed.
- Final automated state: changed-surface Ruff, mypy, import contracts, focused C7/adjacent DB
  tests, 1/25/100 query-scale tests, split full repository DB suite, three standalone
  order-sensitive observability tests, Postman JSON, one Alembic head, and clean
  head -> base -> head all passed.
- Manual state: Exa-first quality trial intentionally remains unrun until a real governed target
  and credentials are supplied; all C7 flags remain default-off.

## Follow-up — governance shadow comparison setting

- Added `Settings.c7_governance_shadow_compare_enabled`, loaded from
  `CLUE_C7_GOVERNANCE_SHADOW_COMPARE_ENABLED`, independently default-off.
- This is an admission/configuration contract only. The diagnostic comparator/report is not
  implemented yet, the setting is not part of C7 route/runtime activation, and it cannot weaken
  governance or expose denied values through normal API responses.
- The operations runbook records the exact boundary.
- Verification: config and C7 activation tests passed (10 tests); changed-surface Ruff, mypy, and
  diff checks passed. Enabling the shadow setting alone is explicitly tested to expose zero HTTP
  routes.

## Follow-up — final residual review fixes

- Added the executable `flagged_derived_erased_dependency` adversarial case and database proof:
  a live `FLAGGED` derived claim with an erased required support resolves to `redacted`,
  `dependency_erased`, with no evidence action.
- Made the legacy review projection resolve the project run's pinned product through a durable
  production reader. Product filtering now covers raw claims, run-pinned fit/intent scores,
  current winners, committee membership/profile, conflict references, annotations, and
  provenance.
- Review actions now require the target to remain in the live rendered account/contact scope,
  reject foreign-product targets, and preserve `product_id` on correction/rejection successors.
- Focused C7/review database suite: 30 passed. Repository mypy: 446 files. Import contracts:
  24/24 over 508 files. The full repository test run had only the three known order-sensitive
  logging/toolbelt capture failures; all three passed independently.
- No C7 flag was enabled. The real governed Exa-first quality trial remains the next task.
