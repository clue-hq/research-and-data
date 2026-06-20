# 2026-06-20 — M4.5 CRM import resolver (tier-1) + Firecrawl official-site scrape (tier-2) (ENG-126)

## State: DONE on branch `akeshri516/eng-126-m45-crm-import-resolver-tier-1-firecrawl-official-site`
Branched off `integration/m4` (`190a6e1` = M4.1+M4.2+M4.3+M4.4 joined). Parallel to M4.6 (ENG-129),
which will be merged separately. `make check` GREEN (ruff, mypy --strict 102 src files, **10/10**
import contracts, **608 passed / 13 skipped** Redis), db-smoke reversible, single head `651b1d7229e2`
(NO new migration — "No new tables" per spec). Adversarial review workflow run; all fixes applied.

## What shipped (binds `crm` + `firecrawl_site` — seeded in M4.2 but resolver-absent until now)
- **resolvers/crm/__init__.py** (NEW): `CrmResolver` (Resolver, tier=1, `crm_import`) over a pluggable
  `CRMConnector` seam (Salesforce/HubSpot are config). Two surfaces share one connector + one
  vendor-agnostic record shape: (a) the Resolver maps the resolved entity's CRM record → claims incl.
  `account.crm_relationship_status` (CrmRelationship enum: customer/open_opportunity/prospect/
  former_customer/none); (b) `resolve_crm_seeds(conn, connector)` feeds `Observation`s to M2's
  `resolve_many`, binds only top-candidate-≥-auto_merge_threshold (a deterministic strong-key hit),
  never mints ids; `lookalike_seeds()` = resolved existing customers. Uses `core.factories` only;
  account-keyed via the M4.4 `AccountLookup` seam. Imports `identity` (intended M2 dependency).
- **resolvers/firecrawl/__init__.py** (NEW): `ScrapeResolver` (Resolver, tier=2, `scrape`) that runs
  the M4.3 adapter chain via **`adapters.run_chain`** (the carve-out). Target-lock: builds official
  surfaces from `primary_domain` via an injectable `SurfaceBuilder` (default = homepage) and **refuses
  any off-domain URL** (host-compare, stdlib urlsplit — no identity import). `ScrapePolicy`
  (excluded_hosts / excluded_jurisdictions) skips a disallowed surface WITHOUT scraping. Manifest
  `rate_limit` threaded into `AdaptContext.params` (M7 enforces). `register_scrape_resolver` registers
  the `firecrawl_html` adapter (FirecrawlHtmlAdapter + scraper + extractor) AND binds the resolver.
- **adapters/pipeline.py**: extracted SYNC **`run_chain(manifest, ref, entity, field, *, run_id,
  research_mode, extractor, gate_decision, cache, clock, params)`** from `run_pipeline`. Now
  `run_pipeline = get_source + run_chain + (persist)` — identical behavior, exported `run_chain`. This
  is the seam the sync/connection-less Firecrawl Resolver uses to run the async-framework chain.
- **sources/waterfall.py** (decision #6): `resolve_field`/`resolve_fields` take `tenant_id: str|None`
  + `reuse_policy`; the engine (the only composer) **`stamp_reuse`s every written claim** before
  insert → crm_import/scoring/resonance/personal = `tenant_private` bound to tenant; public stays
  public. `sources → identity` import (acyclic; no contract forbids it).
- **identity/reuse.py**: `stamp_reuse` `tenant_id` widened to `str|None` + **fail-loud** if a
  private-classifying claim has no tenant (was: silently produces an invalid claim). Backward-compatible
  (all existing callers pass a str).
- **claimstore/packs.py**: added `account.crm_relationship_status` to CORE_PACK (str, enum schema,
  tier_plan=("crm",), 30d TTL). Drift-guarded against `CrmRelationship` by a test.
- **pyproject.toml** — the carve-out: replaced the 4-module independence rule with (Rule 3) independence
  for {adapters, verification, discovery_scoring}, (Rule 3a) `resolvers ↛ verification/discovery_scoring`
  (adapters OMITTED = permitted), (Rule 3b) `{adapters,verification,discovery_scoring} ↛ resolvers`
  (one-way, mirrors Rule 3c sources↛resolvers). `test_five_modular_boundary_rules_are_declared` still
  green (independence type + "workers are independent" name preserved).

## KEY DECISIONS / mechanics
- **Resolver is SYNC + connection-less**, but both M4.5 resolvers need DB/async-shaped work. Solved
  WITHOUT changing the protocol: Firecrawl uses the new sync `run_chain` over the injected SEED manifest
  (no conn); CRM is pure-sync (connector + AccountLookup injected). The waterfall persists + `_finalize`
  re-stamps run_id/mode/source_key + checks tier (seed manifest tier == DB manifest tier == 2/1, so no
  mismatch). The live network/CRM calls are the deferred `# pragma`/double boundary (decision #3).
- **CRM resolver = enrichment surface (Resolver) + observation surface (`resolve_crm_seeds`)**, split so
  the Resolver receives an already-resolved entity (never mints) and the bulk M2-feeding is a separate
  async helper M6 calls. AC "two messy names → same entity, no dup": seed one account_entity, feed two
  records same domain → both DETERMINISTIC to the same id; account_entity count unchanged.
- **register_scrape_resolver registers the adapter as a side effect** — "wire the scrape source" = its
  adapter + its resolver binding. The resolvers conftest now also `clear_adapters()` (the adapter map is
  module-global and would otherwise leak between tests).
- **Tenant stamping is fail-closed**: a crm_import resolve with no `tenant_id` RAISES (does not write
  public). The one existing M4.1 test resolving a `contact.facet.*` crm_import field was updated to pass
  a tenant_id (+ assert private).

## Adversarial review (6-lens find→verify Workflow, 19 agents): 12 raw → 8 confirmed; ALL addressed
Two MUST-FIX tenant-isolation seams (both fixed structurally) + 4 test-rigor gaps (all filled):
- **(HIGH) Idempotency reuse leaked across tenants.** `waterfall._existing_step_claims` read
  `ALL_TENANTS` and reused by `(source_key, run_id)` only — a tenant-private claim could be handed
  back to another tenant sharing a run_id. FIX: the idempotency read is now **tenant-scoped** —
  `for_tenant(tenant_id)` when a tenant is set, else `PUBLIC_ONLY`; a private claim is never reused
  across the boundary (tenant-B re-resolves + writes its own). + regression test. (Reachability is
  low — run_id is per-run-per-tenant — but the seam is now fail-closed, not caller-discipline.)
- **(HIGH) `run_pipeline(persist=True)` bypassed tenant stamping** → an adapter-backed private claim
  (M8 resonance/facet) would be written `public_footprint` by default. The M4.3 contact-persist test
  proved it (it wrote `contact.facet` as public). FIX: `run_pipeline` now takes `tenant_id` and
  **stamps every claim via `stamp_reuse` on persist** (symmetric with the waterfall; a private claim
  with no tenant fails loud). adapters→identity import added (acyclic; contracts still 10/10). The one
  affected M4.3 test updated to pass tenant_id + assert private; + a new fail-loud test.
- Test-rigor (added): single-entity mixed public/private isolation; ScrapeResolver paid-miss cost;
  `resolve_crm_seeds` unresolved-row (entity_id=None, mints nothing); CRM empty-vs-falsy edge cases
  (0 kept, None/""/[] dropped); firecrawl run_id/mode engine-stamped assertion; rate_limit test
  comment made honest (surfaced-to-params only; M7 enforces).
REFUTED (correct as-is): CRM cost-spread (≤1 claim); CrmRelationship drift test (already present);
run_chain behavior-preservation; the import carve-out scope; target-lock/exclusion skip-without-fetch.

## NOTES / known limitations (documented, not bugs)
- **Firecrawl skip-vs-miss cost**: an excluded/off-domain skip returns [] → the waterfall's coarse
  paid-miss heuristic charges the manifest cost (1¢) even though nothing was scraped. The AC tests assert
  `scraper.calls == 0` (the real "not scraped" guarantee), not cost. A richer skip signal is an M7 follow-up.
- **Target-lock uses exact-host match** (apex + path surfaces); a careers *subdomain* would be refused.
  Default builder is path-based on the apex, so fine; registrable-domain comparison is a future enhancement.
- **rate_limit "honored" = surfaced to the transport** (ctx.params); hard throttling is M7's Redis bucket.
- CRM contact enrichment via `connector.fetch_contact(entity_id)` exists but contact-keying for the live
  path is light (mirrors M4.4's deferred contact live path).

## NEXT: ENG-126 → Done; committed locally (no push). At M4.6 merge-back, re-run `make check` on the
joined `integration/m4`. M4.5 unblocks M6 (CRM grounding + already-a-customer at Pass A; CRM/customers
as lookalike seeds; tier-2 official-site facts) and M8 (tier-2 official surfaces). See
[[2026-06-20-m43-modality-adapters]], [[2026-06-20-m44-deterministic-resolvers]],
[[2026-06-20-m41-waterfall]], [[2026-06-19-m4-kickoff-handoff]].
