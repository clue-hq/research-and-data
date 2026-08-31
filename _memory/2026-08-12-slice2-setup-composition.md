# 2026-08-12 — FI-4 slice 2 SHIPPED: setup composition, recon actually runs

## What landed (commits a7c040e7 backend, 7158283b frontend)
- **Scrape binder composed at BOTH roots** (projections_main + fleet_main):
  `build_stage0_scrape_binder(extractor=CallableClaimExtractor(empty), scraper=
  default_scrape_backend(resolved), policy=ScrapePolicy())`. Closes charter
  composition-backlog item (2); production start_recon no longer refuses
  stage0_recon_not_configured. Pass scraper EXPLICITLY (None → resolver constructs a fresh
  Settings() internally).
- **CRITICAL HONEST FINDING (scout-verified, cited in the contract):** NO production
  ClaimExtractor exists repo-wide (only the protocol + CallableClaimExtractor; every
  ClaimDraft( construction is in tests). Recon runs end-to-end (identity resolution,
  target-locked scrape, durable snapshot capture, lane events, cost) but drafts ZERO client.*
  facts; brief.facts = {}; coverage_ratio 0.0 (blocks DISCOVERY_SPEND readiness floor 0.25
  until interview fills ≥3/9 or override — out of onboarding scope). The interview is the
  tier-1 client.* fill path BY DESIGN (REQ-08). **LLM extractor = named follow-up work item**
  (9 field prompts, JSON contract, exact-substring evidence spans — a paraphrasing model
  raises AdaptError and FAILS the lane; belongs at composition root next to
  claim_entailment.py). Also: client.market_reputation + delivered_value are structurally
  unfillable (g2/capterra/trustradius manifests don't exist); crm resolver unregistered → max
  scrape coverage 7/9.
- **CLUE_SCRAPE_BACKEND=scrapling in local .env** (untracked): with an empty extractor,
  firecrawl burns the 5¢ fast envelope on 5 duplicate paid homepage scrapes for zero facts
  (per-field re-scrape, no cache — pipeline passes no cache); scrapling is cost-0 and walks
  all 7 fields. Flip to firecrawl when a real extractor lands.
- **POST /stage0/setup + GET /stage0/setup/current** (platform/api/clue_api/stage0_setup.py;
  gated on CLUE_SELF_SERVE_PROVISIONING_ENABLED + storage): capture-before-use (persist_body →
  submit_onboarding_input kind=website via the conversation_capture primitives), deterministic
  ids from (workspace, sha256(casefold(website))) so every retry is a replay; the D-4c kicker
  = re-invoking start_recon (ONE invocation drives exactly ONE queued lane — verified in
  stage0_tools invoke branches); GET resolves recon via provisioning record → dedupe hash →
  latest recon_run and reuses the stage0_progress projection internals. status "complete" =
  fast lane done (release signal).
- **Frontend**: LiveSetupScreen (clerk mode) polls setup/current at 1.5s; honest items = fast
  lane, background lane, brand-kit explicit dummy; fast completion → location.assign
  /session/establish (finalizing dead-end gone); fixture theatre + hold=1 untouched (timer
  gated to fixture mode). New seam files: data/setup.ts, hooks/use-setup-progress.ts.

## Gotchas learned
- `from __future__ import annotations` + closure-local Annotated alias → FastAPI treats the
  dep as a QUERY param (422). Module-level alias required (projections_app documents this).
- ToolResult requires tool+version fields. governed.start_recon replay drift-check compares
  TYPED OnboardingInputId tuples (strings → false drift error).
- Shared-conn test harness needs an asyncio.Lock around the conn_factory when a background
  driver task runs concurrently with HTTP polls (asyncpg one-op-per-conn).

## Residuals (slice 2)
- Driver is process-local: process death mid-lane → recon row keeps last durable state; a
  re-POST resumes (replay ids). No fleet-side driver.
- SSE not extended to recon (polling per D-8); background lane still has no driver outside
  this surface.
- Exit-test caveat: "real recon brief within 5¢" = lane runs + snapshots + cost accounted,
  but facts empty until the extractor exists (recorded in contract + FI-4 terms).

## Next: slice 3 (D-5 Path B + D-6)
Per-field in-flight events at reverse_profile's loop (payload.kind stage0.recon.field; commit
visibility design needed), client.competitor + client.buyer_profile fields via Exa search
(tier 3, background lane; Exa DEEP is tier-4 = REQ-08-forbidden pre-confirmation), 4 ratified
checklist groups, and (recommended to ride along) the LLM claim extractor work item.
