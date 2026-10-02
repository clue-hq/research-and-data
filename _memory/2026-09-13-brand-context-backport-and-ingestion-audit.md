# Brand Context backport and sparse-source diagnosis

## Scope and evidence

Founder reported sparse AWS/Google Cloud libraries and asked to bring Aryan's
Brand Context changes here. Kept the current feature branch and four pinned
frontend instances. Shared local APIs and all four worker processes were healthy.
Read-only local database inspection; no ingestion/generation spend or DB mutation.

- AWS: one successful website job and one homepage snapshot; 3 raster images and
  1 vector record (the vector is a FontAwesome font SVG). No harvested ad rows or
  ad-assets job. Saved HTML is exactly 2,097,152 bytes and contains no body, img,
  main or section elements. `capture/rendered.py::_snapshot_from_harvest` truncates
  HTML at `HTML_MAX_BYTES = 2 MiB` before downstream parsing. The capture therefore
  lost the page body. Fragment diagnostic LUMI0523 reports no usable sections.
- Google Cloud: one successful homepage capture; 54 raster and 10 vector records.
  Browser confirms all 64 asset buttons. Saved HTML has 67 img and 16 section
  elements. No ad-assets job/harvested ads. The site import has no extra page URLs.
- Both kits were partial test sources, subsequently manually approved with
  `product_ready=false`. Approval is not proof of extraction completeness.
- Ad-assets, ingestion vision and description flags are enabled; this does not
  enqueue a harvest. Website capture explicitly does not discover linked pages.
- Conduit test corpus is a clone of earlier imports/harvesting; incomparable
  source coverage must not be reported as a fair cross-brand quality benchmark.

## Upstream and local changes

Fetched origin. `origin/design/scene-ad` did not advance. Aryan's
`origin/brand-context-polish` includes hundreds of unmerged commits, new ARV2
onboarding/Knowledge APIs and unrelated research/account work. A whole snapshot
would also discard local ingestion/logo/font fixes. Did not merge that branch.

Backported the independent presentation changes from `3903ae73`, `769b4994`,
`79330214`: responsive full-image previews, document-title treatment, real font
faces and load status, typefaces refreshed from kit props, and GFM rendering.
Preserved existing client-local Markdown drafts, local logo/asset metadata,
workspace pins and all backend/engine code. Added only the upstream Markdown
dependencies; updated the frontend contract with the exact scope.

Version-checked Markdown persistence (`2c100e8a`) and onboarding Knowledge remain
unintegrated because their ARV2 backend/document-store prerequisites are absent.
The 2 MiB capture truncation exists upstream too; a UI pull does not fix it.

## Verification and next work

- Upstream font-mapping regressions failed twice before implementation, then
  passed. All 66 Brand Context model and 18 repository/action tests pass (84 total).
- Design-system generation, lint and production build pass. Lint retains the two
  existing unused snap-helper warnings. TypeScript and route generation pass.
- Browser: AWS's modal image is contained and the dialog bounds fit the viewport;
  actual Amazon Ember and Arial samples render. Google has 64 assets. Design.md
  renders real headings/lists and retains its Preview/Edit controls.
- Google Sans and Google Sans Text samples also load successfully. Final browser
  checks retain the correct workspace/port on Clue, AWS, Google Cloud and Conduit.
  An unsupported generic-role locator timed out during browser verification;
  direct DOM snapshots verified the existing workspace labels.
- Patch preparation initially used the wrong cwd and hit expected old/new-source
  context mismatches; adapted selected hunks, preserving local drafts and styles.
  One test invocation from repo root failed the frontend path alias; rerunning
  from apps/frontend passed. No application failure was attributed to that runner.

Next: fix bounded capture so a large head cannot silently remove the body, replay
that case through extraction, then perform explicit product-page and ad-library
imports for the intended product/audience scope. Do not interpret a successful
job or an approved kit as complete brand onboarding. Keep those source improvements
separate from this UI backport and from the larger ARV2 integration.

Preserved the unrelated September 8 memory edits/untracked notes. No push or
production change. The source-data gaps are diagnosed, not repaired by this commit.
