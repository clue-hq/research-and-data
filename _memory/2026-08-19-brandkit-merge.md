# 2026-08-19 — brand-kit onboarding branch merged into the trunk

`feature/brandkit-onboarding-integration` (15 commits, 87 files, +13.5k — slices 1–6 of
`docs/superpowers/plans/2026-08-18-brandkit-onboarding-integration.md`) merged into
`integration/frontend-design-part-iv-v2` as `81e961ce`.

## What came in

Brand-context page (dummy lift + kit mappers + real store reads with honest fallbacks);
auto-enqueued draft ingestion at first-time provisioning; the checklist row bound to the
real job; re-extract + approval controls (re-ingestion publishes a new draft version);
**the frozen creation contract** (slice 5, `fe5370b7`): `clue_design/documents.py::
create_document` stamps the latest APPROVED brand kit at web-document birth — explicit
ref wins; single-brand workspaces only (multi-brand fails closed, no `brand_id`
selector in the create contract); approval never re-stamps existing documents;
`brand.py::latest_approved_brand_kit_ref` owns selection. Plus vision-assisted
ingestion deployment config (slice 6, env-driven).

## The merge

- Only 3 files touched by both sides. Conflicts: `apps/frontend/package.json`
  (dependency union — trunk's Lexical family × their codemirror/@lezer, alphabetical)
  and `package-lock.json` (took ours then regenerated via `npm install` off the merged
  manifest). `_memory/2026-08-17-w01-shell-lift-file-set.md` auto-merged cleanly.
- **Dropped from the merge:** an accidental `.artifacts/ws_9e0eb…/3bccbda…` runtime-store
  blob (content: the literal string `https://linear.app`, from a live ingestion test;
  referenced by nothing; the trunk's `.gitignore` now covers `.artifacts/`).

## Union verification

- Frontend: design-system:build ✓, **835/835** (772 trunk + their 63), lint ✓,
  production build ✓.
- Platform DB suites (theirs, on the union with env): `test_brand_kit_onboarding_
  ingestion_db.py` + `test_concept_joins_dal_db.py` + `test_documents_dal_db.py` — all
  green (34 items).
- Design API suites: ingestion deployment-config / routes / ui-api / web-documents —
  41 passed, 1 expected helper-gated skip. NOTE: one test
  (`test_capture_failure_marks_job_failed_no_kit`) FAILS if the platform root `.env` is
  sourced into the shell first (the slice-6 deployment-config is env-driven; vision/
  describe flags change the pipeline's failure shape) and passes in a clean shell —
  env leakage in the runner, not a merge regression. Run design tests without the
  platform env sourced.

## State

The trunk now holds: W0–W5 complete (founder sign-off on the acceptance record pending),
chat-flow integration complete, Part III agent integration, AND the brand-kit
onboarding pipeline. The chat-driven website generation plan is amended (same session)
to make leg-born documents brand-themed via the stamp-at-birth contract.
