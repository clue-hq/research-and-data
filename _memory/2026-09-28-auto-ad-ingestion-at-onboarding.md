# Auto ad ingestion at onboarding (2026-09-28)

Branch `feat/ad-assets-auto-onboard`, cut from `codex/ai-ark-committee-discovery-spec-v1` at
`14bc8e7c5`, in the worktree `.claude/worktrees/ad-auto-onboard` of the dubai workspace (so the
founder's pending merge into the dubai branch was not touched). Local commits only.

## Founder rulings (chat, 2026-09-28)
- Onboarding starts the ad ingestion automatically; "top 50" = the **50 most recent static ads**
  (the LinkedIn ad library via Adyntel has no performance ranking).
- Start it **in parallel** with the website brand-kit ingestion, not after it.
- Design option A: a **harvest** job at onboarding start (no kit), and a **card** job (distil the
  ad-DNA card + pre-generate) offered by whichever of harvest / kit ingestion finishes second.
- Removing brand-kit approve/reject is a SEPARATE task, not done here.

## What was built
- Platform `clue_api/brand_kit_ingestion.py`: the onboarding trigger also POSTs
  `/brand-ad-assets/onboard` `{phase: harvest, company_domain, max_creatives, max_pages}`.
  Once per kind, each fail-soft on its own. Kit-side reads (trigger idempotency + the checklist's
  newest-job read) use `KIT_INGESTION_KINDS` so an ad job never stands in for a kit job.
  Settings: `CLUE_BRAND_AD_ASSETS_AUTO_ONBOARD=true`, `_AUTO_MAX_CREATIVES=50`, `_AUTO_MAX_PAGES=8`
  (in `.env.example`; parity test `tests/test_ad_harvest_settings.py`).
- DAL `clue_design.ingestion.list_recent(kinds=...)`; `IngestionJobStore.list_recent(kinds=...)`.
- Design `OnboardAdAssetsRequest.phase: full|harvest|card` (default full = unchanged). Route:
  harvest needs no kit; `card` is refused (`ad_assets.card_phase_is_internal`); `full` without a
  kit is `ad_assets.brand_kit_required`.
- `ad_library/onboarding.py`: harvest phase = resolve → harvest → custody → record (+ ordered
  `creative_ids`) → per-image enrichment; distil/pregenerate recorded `deferred`, job completes
  with NO kit. Card phase reloads the harvest's creatives from rows + custodied bytes (no Adyntel
  call, no re-download), follows the harvest order, copies the harvest's evidence steps so the
  outcome describes the whole lane, pins the card to the kit. Steps 2–3 shared by full and card
  via `_card_and_imagery`.
- `ad_library/auto_card.py`: `offer_card_if_ready(workspace)`; deterministic card job id
  (`ingest_adcard_<sha>`) + uuid5 work id, so a race is settled by the PK/dedup key, no lock.
- `jobs.run_ingestion_job(on_complete=...)`: runs only after this attempt's successful complete;
  its failure is logged, never touches the job. Wired in website/pdf/asset pipelines and the ad job.
- Frontend `brand-kit-actions.ts`: `activeJob` ignores `ad_assets` jobs, so a running ad harvest
  does not show "Extracting your brand…" or disable re-extract on the Brand context screen.

## Why not "wait inside the job"
The ingestion pool's coordinator role runs one job at a time; an ad job parked waiting for the
kit would block the very kit ingestion it waits for.

## Verification
- Root: DAL, trigger (28), settings parity, onboarding/stage0/design suites — see the commit.
- Design: 9 new tests in `apps/api/tests/test_ad_assets_onboarding.py` + existing ingestion suites.
- Tests ran in the worktree with NO `.env` (Settings reads `.env` from cwd — running suites in a
  workspace that has one loads its real keys; see the 2026-09-28 testing notes) against throwaway
  DB `clue_dubai_feat` on papeete :55040, with `LUMEN_CORE_HELPER` = the release helper.

## Owed
- Live proof on a real company (spends Adyntel + model money): founder-triggered.
- Bring the branch onto the dubai branch after the founder's merge.
