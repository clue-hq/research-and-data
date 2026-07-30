# C7.9 production research-view readers plan

**Date:** 2026-07-30
**Branch:** `platform/c7-research-views`
**Outcome:** implementation-ready corrective plan written; no runtime code changed

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

## Current state

- No feature flag was enabled.
- No production code or migration was changed.
- The earlier plan now links to C7.9 and marks production activation blocked.
- Unrelated existing worktree changes were left untouched.

## Next exact task

Start C7.9.0 contract tests and C7.9.1 schema/substrate work. Do not implement adapter SQL before
the canonical version, field route, product-selection, and display-policy contracts are frozen.
