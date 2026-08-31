# 2026-08-14 — Stage-0 durable official-site crawl C3

## Outcome

- C3 is complete on `platform/onboarding-integration`; C4 is next.
- Firecrawl and Scrapling implement the frozen provider-neutral `PageFetcher` protocol under
  provider-isolated adapter packages. Each `fetch_one` invocation owns exactly one approved URL;
  neither provider owns recursion, depth, deduplication, scheduling, robots, or frontier state.
- No production coordinator or live provider call was added. C3 remains an adapter/contract slice.

## Provider behavior

- Firecrawl uses only `AsyncFirecrawl.scrape` with rendered HTML and link output. Its SDK retry loop
  is disabled at client construction so only the future durable attempt ledger may authorize a
  redispatch. Adapter/client configuration is validated before dispatch.
- Firecrawl preserves `sourceURL` as acquisition provenance before considering generic page-authored
  URL metadata. Receipts retain only scrape ID, credits used, and cache state. Explicit zero credits
  are `no_spend`; positive/unknown credits use the configured monetary estimate. Any unresolved
  exception/timeout after dispatch is `spend_unknown + ambiguous`, never blindly retryable.
- Scrapling is credit-free and uses a local transport that resolves every hop through the C2
  resolver, rejects any non-public answer, pins curl with `RESOLVE`, disables ambient proxies,
  auto-redirects, and hidden retries, and manually revalidates/re-resolves each redirect. The whole
  redirect sequence shares the outer request deadline and decompressed-byte ceiling.
- Both adapters return shared HTML anchor/canonical observations, with provider links supplemental
  and deduplicated. C5 remains authoritative for URL/domain/depth/page-ceiling admission.

## Boundaries and dependencies

- Provider packages are `adapters/firecrawl_page/` and `adapters/scrapling_page/`; common mapping
  lives in `adapters/page_fetcher_common.py`.
- SDK imports are lazy and confined to those provider packages. Import-linter now protects
  `official_site` from provider SDK imports and permits only the exact adapter-to-frozen-contract/
  discovery/safety seam edges.
- `curl-cffi>=0.13,<1` is a direct research dependency because the pinned connector uses its public
  `RESOLVE` API; the lockfile and current workspace environment were refreshed successfully.
- The detailed source-of-truth record is
  `docs/specs/FI-stage0-durable-official-site-crawl-C3-provider-contract.md`; parent/C0/C2 status
  documents now agree that C0-C3 are complete.

## Verification

- C3 provider/adversarial/static suite: 44 passed. It covers the shared two-provider contract,
  exact call counters including concurrent calls, immutable capabilities, dict/attribute Firecrawl
  responses, receipts/cost/spend ambiguity, timeouts/cancellation, local HTTP retry classes,
  MIME/body/size/host refusals, redirects/loops/ceilings, private-IP refusal, per-hop DNS pinning,
  SDK surface smoke, lazy import guards, forbidden recursive Firecrawl AST, and provider-free
  coordinator branching.
- C3 plus dependency-contract tests: 48 passed.
- Full C0-C3 official-site suite against retained isolated database
  `clue_c2_official_site_20260814_final`: 103 passed.
- Final repository static gates: Ruff format/check passed (1,364 files), mypy passed (649 source
  files), and import-linter passed all 25 contracts. Locked `uv sync` rebuilt the research package.
- Repository-wide diagnostic pytest: 2,555 passed, 2,055 skipped, 5 failed. Three failures were
  sandbox-denied local PostgreSQL connections and passed when rerun against the isolated database.
  The two remaining failures are existing out-of-slice checks: missing materialized Stage-0 agent
  resource in `test_resolved_snapshot_materializes_through_c61_backend`, and merged clue-design
  direct-logging files in `test_no_direct_logging_getlogger_outside_clue_obs`. No C3 or official-site
  test failed.
- `git diff --check` passed. Existing unrelated frontend/auth/provisioning worktree edits were not
  modified or staged.

## C4/C5 handoff

- C4 must persist prepared/dispatched before calling a fetcher, persist body-free metadata/receipt,
  store successful bytes, resume persistence without refetch, and reconcile/quarantine
  `spend_unknown` rather than dispatching again.
- C5 must wrap every adapter call in C2 preflight and post-response validation, apply link ceilings
  before discovery insertion, and choose a registered `PageFetcher` without provider-name branches.
- Firecrawl still declares no operation lookup/idempotency or redirect-chain support; C4 must not
  invent these capabilities. Scrapling declares no receipt and needs no paid-call reconciliation.
