# 2026-08-13 — Fixture-free live-provider E2E stopped at onboarding recon

## Scope and isolation

- Branch: `platform/pilot-budget-controls` after the FI-2 cutover, Stage-0 hardening, and
  onboarding merges.
- Browser: real in-app-browser custom Clerk flow against the configured Clerk test instance.
- Database: fresh `clue_singapore_live_e2e_20260813`, migrated to `ea63efd38c3a`; the zero-state
  baseline had no users, workspaces, brands, products, projects, claims, ICPs, accounts, or contacts.
- No fixture seed script or fixture repository was used. The runtime selected Clerk auth, the HTTP
  project transport, Firecrawl, OpenRouter, Exa, and Sumble credentials from environment. Required
  default-off deployment gates were enabled only in the test processes.

## Browser and durable evidence

- A new Clerk test identity completed email/password sign-up and the email-code step, then submitted
  the real Insight Health name/website through onboarding.
- `POST /auth/v1/provision` returned 200 and durably created one Clue user, active owner membership,
  workspace, brand, auth identity, and self-serve provisioning row. The submitted profile persisted.
- `POST /stage0/setup` returned 202 and created one onboarding input, one client account entity, two
  captured artifacts, and one recon run. No product or project was created; the recon row's
  `product_id` and `project_id` stayed null.
- The fast lane marked every one of the eleven Client-KB fields `empty`, wrote only
  `client.kb_version`, and completed at zero cost. The background lane then failed on its first field
  (`client.value_prop`) with durable `failure_code=ModuleNotFoundError`.
- Direct environment verification reproduced `ModuleNotFoundError: No module named 'firecrawl'`.
  `CLUE_SCRAPE_BACKEND=firecrawl` is the production default, but the SDK is intentionally not a
  declared/locked dependency; `FirecrawlScrapeBackend` imports it lazily only after onboarding has
  started.
- Despite `background_status=failed`, zero Client-KB facts, and no product, the frontend treated the
  fast-lane `complete` state as an unconditional release signal and redirected to the app. The setup
  reducer also force-marks every checklist group complete on that state.

## Additional observed defects at the same boundary

- Clerk logged that the custom flow had no `clerk-captcha` element and fell back to Invisible
  CAPTCHA, contradicting the recorded operational assumption that bot protection is disabled.
- The protected shell displayed the raw workspace id and the hard-coded profile identity
  `Aakash Shrivastava`, not the newly persisted user profile.
- Enabling optional contact-channel enrichment caused the worker to fail closed at boot because no
  validator-backed coordinator is composed. It was disabled; Sumble committee and Exa account/contact
  research gates remained enabled. This did not cause the onboarding failure.

## Stop condition and follow-up

- Per full-story verification discipline, the run stopped at the first broken boundary. Stage-0
  interview, ICP synthesis/revision/approval, discovery, account research, committee, and contact
  rendering were not exercised and must not be reported as passed or failed by this run.
- No additional API key is missing. The next live rerun needs the Firecrawl SDK declared/locked and
  installed (or a provider-backed REST adapter that removes the SDK dependency), plus a boot-time
  composition check so a Firecrawl deployment fails before accepting onboarding. The release rule
  also needs to refuse or visibly surface a zero-fact/failed-background setup instead of silently
  entering the app. The requested post-onboarding product lineage requires an explicit product
  creation/binding contract; current FI-4 provisioning intentionally creates only workspace + brand.
