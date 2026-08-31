# 2026-08-14 — Stage-0 durable official-site crawl C2

## Outcome

- C2 is complete on `platform/onboarding-integration`; C3 has not started.
- The crawl coordinator now owns versioned conservative URL identity, deterministic discovery
  classification, bounded HTML-link/sitemap/robots parsing, network/redirect/content safety, and
  durable graph/alias provenance. No provider SDK or HTTP client owns crawl recursion.
- C2 required no DDL change. The only C0 contract delta is an optional `UrlObservation.sitemap_url`
  field matching the already-frozen database column, so the source sitemap is preserved accurately.

## Policy and durable behavior

- `official-site-url-v1` folds only scheme/host case, IDNA host spelling, default ports,
  unreserved percent escapes, tracking allowlist parameters, and ordinary fragments. It preserves
  path case, trailing slashes, `/index.html`, query ordering/repetition, semantic query parameters,
  and hash-routing fragments.
- Raw discovered URL, absolute fetch key, observations, graph edges, redirect/canonical aliases,
  and source sitemap stay distinct. Canonical hints are observations, never identity authority.
- Backslash-ambiguous URLs and Unicode whitespace fail before parsing. Page-derived observations
  require a source page, root/sitemap observations cannot invent one, and alias observations cannot
  assert graph depth.
- Sitemap discoveries have unknown graph depth. Links from an unknown-depth page remain parked in
  `discovered`; finding a shorter root-linked route assigns the verified depth and queues them.
  Fetched pages re-expand saved anchor edges transitively without another provider call.
- `official-site-safety-v1` enforces domain/subdomain and auth-surface policy, all-answer DNS/IP
  checks, redirect continuity/domain/IP checks, MIME allowlisting, decompressed-size limits,
  combined link ceilings, and a pinned-address connector seam for C3's local fetcher.
- `official-site-robots-v1` and `official-site-sitemap-v1` parse only bounded already-captured
  bodies. Sitemap index depth/document/URL ceilings and loop/missing/external refusals are explicit;
  neither parser performs hidden network recursion.

## Verification

- Retained isolated databases:
  - `clue_c2_official_site_20260814_final`: accepted clean C2 evidence, left at Alembic head.
  - `clue_c2_official_site_20260814_broad2`: repository-wide diagnostic residue, intentionally
    separate from the accepted DB.
- Clean `make db-smoke` passed on the final DB (`head -> base -> head`); `alembic heads/current`
  both reported the sole head `6e7ba5968751`.
- Official-site C0-C2 suite: 59 passed. It covers the adversarial normalization matrix, unsafe IP
  classes, mixed DNS answers, redirect/domain/canonical refusal, MIME/size/link ceilings,
  robots/sitemap bombs and bounds, source-sitemap provenance, unknown-depth parking, hash
  collisions, replay, and no-refetch shorter-path cascade.
- Official-site + sources + discovery-scoring affected suite: 321 passed.
- Final `make lint`, `make typecheck` (646 source files), `make contracts` (25/25), and
  `git diff --check` passed.
- The repository-wide diagnostic collected 4,573 tests: 4,509 passed, 23 skipped, 41 failed. No
  official-site/C2 test failed. The failures are out-of-slice monolithic-suite isolation/order
  residue (shared source registries, protected downgrade rows, existing agent/design checks), while
  the fresh accepted DB smoke and every affected suite are green.

## C3 handoff

- Implement provider-neutral single-page Firecrawl and Scrapling fetchers behind the frozen
  `PageFetcher` result. Firecrawl must not use hidden recursive crawl mode.
- The local transport must use the C2 pinned-address seam (or an equivalently tested connect-time
  enforcement) so DNS preflight cannot be bypassed by rebinding.
- Provider results must feed C2 response/redirect validation and discovery planning before the C1
  repository records child observations; C3 must not duplicate URL/depth/dedup policy.
