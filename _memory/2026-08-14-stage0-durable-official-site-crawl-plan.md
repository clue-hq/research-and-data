# 2026-08-14 — Stage-0 durable official-site crawler plan

## Outcome

- Founder approved the architecture direction and requested an exhaustive implementation plan.
- The source of truth is `docs/specs/FI-stage0-durable-official-site-crawl-plan.md`.
- This is a new durable capability. It is not a provider swap inside the current field-oriented
  official-site resolver and not the provider-owned recursive Firecrawl spike.
- Current accepted behavior remains homepage/field-oriented until every live cutover gate passes.

## Binding decisions

- Clue owns discovery, URL identity, depth, priority, dedupe, concurrency, safety, retry, progress,
  and fast/background lifecycle. Firecrawl and Scrapling fetch one page per request.
- PostgreSQL is both frontier and ledger in V1. No Redis or in-memory scheduling authority.
- Claims and completions are generation-fenced. Stale workers cannot publish after lease reclaim.
- URL identity is conservative. Preserve discovered/requested/final URLs, redirects, canonical
  hints, and sitemap/link provenance separately; deduplicate immutable content, not provenance.
- Sitemap origin is distinct from link-graph depth. Sitemap-only pages have unknown graph depth.
- Fast and background are phases/checkpoints of one crawl run and reuse one durable frontier.
- A paid call with an ambiguous outcome is reconciled or quarantined as `spend_unknown`; it is not
  blindly retried.
- The fast target is truthful release within 40 seconds under the accepted test conditions, not an
  exhaustive-site guarantee. Background continues the same run.

## Plan shape

- C0 contract freeze and disposition of the recursive spike.
- C1 migration/repository; C2 URL/graph/safety; C3 provider adapters; C4 artifacts/spend recovery.
- C5 concurrent coordinator; C6 shared fast/background lifecycle; C7 grounded extraction.
- C8 progress/operations; C9 offline adversarial acceptance; C10 retained live browser acceptance.
- Live evidence must correlate browser, API, logs, database rows, artifacts, and provider receipts
  from one fresh isolated database/run.

## Files changed in this documentation checkpoint

- `docs/specs/FI-stage0-durable-official-site-crawl-plan.md`
- `docs/specs/README.md`
- `docs/specs/FI-onboarding-contract-gap-review.md`
- `docs/specs/M04-source-layer-and-source-intelligence.md`
- `docs/specs/M05-stage0-front-edge.md`
- `apps/frontend/docs/api-contracts/onboarding.md`
- `_memory/README.md`
- this note

## Verification and handoff

- Checked the plan for all founder refinements and the expanded acceptance cases.
- Checked cross-doc wording to keep current, planned, rejected-spike, and live states separate.
- Ran `git diff --check` successfully before the final documentation commit.
- No provider call, browser run, schema migration, or source implementation was performed in this
  checkpoint.
- Next implementation entry is C0. Do not start C1 until C0 freezes DDL and the `PageFetcher`
  result contract and disposes of the uncommitted recursive-spike code explicitly.
