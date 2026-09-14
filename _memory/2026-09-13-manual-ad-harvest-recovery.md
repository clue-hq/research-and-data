# Manual ad-harvest recovery — 2026-09-13

## Request and cause

Investigate missing AWS/Google Cloud ads and perform a manual harvest on localhost.
Verified `platform/api/clue_api/brand_kit_ingestion.py` only enqueues website ingestion;
the existing cofounder Mac runbook §5b explicitly keeps ad ingestion manual. Enabling
`LUMEN_BRAND_AD_ASSETS` exposes the lane; it does not schedule a harvest. The local
cross-brand setup had not offered that separate job.

## Live failures and recovery

- Bounded normal jobs hit 60-second ReadTimeouts. A temporary 180-second provider timeout
  revealed HTTP 204 No Content after about 60 seconds, then non-JSON errors. Retrying the
  verified global page did not fix the provider response. Timeout returned to 60 seconds
  in all env files and runtime; no lasting env changes.
- Fresh company enrichment selected Google Cloud Minnesota instead of global Google Cloud.
  Verified the global LinkedIn company/showcase identity in the public browser and used an
  explicit page selector for recovery. AWS identity was already correct. No hardcoded
  company mapping or identity-resolver fix was added.
- Public LinkedIn library fallback used observed original media URLs through the existing
  provider, byte-custody, asset-registration and ad-reference seams. Operator scripts,
  snapshots, original hashes, job receipts and verification remain gitignored under
  `.local-setup/manual-ad-harvest-sept13/`; no provider API success was fabricated.
- AWS: 12 URL candidates became 7 byte-unique imports. Final author audit caught one
  employee post promoted by AWS. Archived that asset and reverted only its newly imported
  ad-reference row after preserving a backup; final active set is 6 corporate originals.
  These cover event/recruiting campaigns, not comprehensive product-ad coverage.
- Google: the first 168 cards yielded oversized animated GIFs (one 44 MB, importer cap
  12 MiB); preflight rejected them before a job was written. By 192 cards, found ten
  corporate still-image candidates, deduplicated to 5 originals. Personal promotions,
  partners and the GIFs were excluded. Do not infer zero available ads from the earlier
  failed provider jobs or animation-heavy first pages.
- All 11 retained images returned original SHA-256 bytes from the local API. Every image
  returned 404 under the other brand workspace. Original source/detail links are retained.
  This is a bounded LinkedIn sample, not a complete library or a Meta harvest.

## Implementation and verification

Added persisted `OnboardAdAssetsRequest.harvest_only` (default false) and a post-custody
worker exit that explicitly skips distillation and pregeneration. Successful recovery is
a succeeded job with partial overall onboarding outcome: no new ad-DNA card or generated
background was requested. Normal onboarding behavior remains the default. Runbook updated.

Regression tested the real API request, persisted job and worker on the disposable test DB,
with model operations failing if accidentally called. Initial test failed before the field
was consumed; passed after implementation. Provider + harvest + onboarding matrix: 44
tests passed, excluding `fleet_worker_executes`. Logs are in the ignored recovery folder.
Forced root Ruff rules report 173 pre-existing findings across the three files; comparison
against HEAD showed identical diagnostic counts/messages and no new findings. Diff check
passed. No Rust, WASM, frontend, schema or migration changes were made.

Restarted this checkout's stack: API 8010, platform 8020/8030, frontend 3020 and all four
Fleet processes healthy. The running API advertises the new field. Brand frontends
3021–3024 remain isolated by workspace binding over the existing shared backend/DB.
Verified imported originals in the AWS and Google Cloud asset modals in Codex browser.

## Remaining work

Automatic per-workspace ad enqueue, verified advertiser identity resolution, provider
204 diagnostics/retry policy, broader creative-family coverage, and logo suitability are
not fixed by this manual recovery. No ad-generation quality claim follows from harvesting.
No production mutation, remote push, new branch or external issue updates were performed.
