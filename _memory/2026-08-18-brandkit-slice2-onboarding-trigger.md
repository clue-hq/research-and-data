# Brand-kit × onboarding — Slice 2: the first-time-onboarding ingestion trigger (2026-08-18)

Branch `feature/brandkit-onboarding-integration`. Backend-only. Commit `4b2fbd41` (+ follow-up).

## What shipped

`POST /stage0/setup` now also enqueues ONE brand-kit website ingestion for a first-time
workspace, so the Brand-context page has a real `draft` kit to review.

- New module `platform/api/clue_api/brand_kit_ingestion.py` — `BrandKitWebsiteIngestion.ensure()`:
  per-workspace `pg_try_advisory_xact_lock` → `clue_design.ingestion.list_recent(limit=1)`
  existence read → `POST {design}/brand-kits/ingest/website` with `X-Workspace-Id`, body
  `{"url": …}`. Never raises. `build_brand_kit_ingestion_trigger` returns `None` when unconfigured.
- Hook: `stage0_setup.py::start_setup`, AFTER the capture step and AFTER the recon dispatch (so a
  slow/unreachable design API cannot delay recon by even the enqueue timeout).
- Config: `Settings.design_api_base_url` → env `CLUE_DESIGN_API_BASE_URL` (default None).
  Documented in `.env.example`. Distinct from the frontend's `LUMEN_API_BASE_URL`.
- Contract recorded in `apps/frontend/docs/api-contracts/onboarding.md`.

## Decisions worth remembering

- **HTTP, not a platform-side row write.** The enqueue is design-toolbelt-owned (`_offer_ingestion`
  → `run_design_tool`, one transaction for job row + `design_job` fleet task) and carries the SSRF
  guard. `lumen_api` is never imported into the platform web process; the `clue_design` DAL is used
  only for the idempotency read.
- **`pg_try_advisory_xact_lock`, not a blocking acquire.** A loser declines rather than queueing —
  the winner is already doing the one thing that needed doing. The lock is deliberately held across
  the HTTP call (the design API's own txn must COMMIT before a replay may look for the row);
  bounded by a 5s timeout and once per onboarding.
- **Idempotency is kind-agnostic**: ANY `design_ingestion_job` row for the workspace suppresses it.
- **First-time-only is structural** — reachable only through the self-serve provisioning scope. No
  flag to drift.
- `brand_id` is not threaded: a provisioned workspace has exactly one brand and
  `clue_design.joins.resolve_brand_id` stamps it. Multi-brand → NULL by design (slice 4's manual
  re-ingest passes an explicit brand).

## Live verification (fresh first-time onboarding, real sign-up)

Stack on 8014 (design) / 8034 (platform) / 3034 (frontend), shared dev DB `clue-pg-istanbul` 55040.
New account `onboarding+clerk_test_20260818b@example.com` (password needs 15+ chars — Clerk rule),
company **Linear**, website `https://linear.app`.

- workspace `ws_9e0eb75409214a25b336a863558f072f`, brand `brd_fe6b91bdecd94246a03f174e74b1a1ec`
- job `ingest_b91eb1c479974c27bae23406d7a086e9`, kind `website`, `succeeded`
- kit `brand_kit_ing_b91eb1c479974c27bae23406d7a086e9` v1, `draft`, source `website`,
  `brand_id` == the provisioned brand (1 brand in the workspace)
- REPLAY: 2 × `POST /stage0/setup`, 1 job; second logged `brand_kit_ingestion.already_ingested`
- `/brand-context` renders Linear's real kit (surface.brand `#5E6AD2`, Inter Variable, 14 assets)
- screenshots `/tmp/slice2-brand-context-{colors,typography,assets}.png`

**Leave this account's data in place — later slices use it.**

## Environment gotchas found (not code defects)

1. **Two design APIs on one dev Postgres share the fleet table.** The trunk workspace's design API
   (port 8010, istanbul worktree) claimed and executed OUR `design_job` and wrote the asset bytes
   to ITS storage root `/tmp/lumen-dev-storage`, so `/assets/{id}/bytes` 404'd from our API rooted
   at `/tmp/lumen-dev-storage-ww` until the blobs were copied across. Correct fleet behaviour;
   avoid by using the same `CLUE_STORAGE_FS_ROOT` (or stopping the other stack) when verifying.
2. **Recon lanes do not run without a platform fleet worker.** Only the web API was launched, so
   `recon_run` stayed empty. Irrelevant to this slice (that is the point: the brand-kit trigger is
   off the recon path), but do not read it as a recon regression.
3. Clerk test-mode sign-UP requires a 15+ character password; the code is still `424242`.

## Follow-ups / open

- The trigger holds a pooled DB connection across the enqueue HTTP call (≤ 5s, once per
  onboarding). If onboarding ever becomes high-volume, revisit (e.g. commit-then-recheck instead of
  lock-across-IO).
- Slice 3 owns the onboarding checklist row (`GET /stage0/setup/current` extension) and the
  supersession note at `docs/specs/FI-onboarding-contract-gap-review.md:140`.
- Slice 1's founder ruling on missing Colors/Typography empty-state copy is now MORE relevant: a
  kit-less workspace is common while the ingestion runs.
