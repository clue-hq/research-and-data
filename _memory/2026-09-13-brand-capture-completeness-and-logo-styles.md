# Complete website captures and portable logo styling

Follow-up to the Brand Context UI/source audit. Founder reported missing AWS and
Google Cloud ads, then the poor AWS logo/background result. Worked on
`codex/design-agent-v1`; preserved the unrelated September 8 local notes.

## Confirmed causes and scope

- Website onboarding only enqueues `/brand-kits/ingest/website`. The enabled
  `/brand-ad-assets/onboard` endpoint is separate; no frontend/onboarding caller
  enqueues it here. AWS/Google had never submitted ad jobs, rather than receiving
  empty provider results. Conduit's earlier harvest was submitted separately.
- AWS's rendered document was 3,314,451 bytes; its body began at byte 2,374,077.
  The old 2 MiB prefix discarded body images and inline logos while still allowing
  the job to succeed. Google Cloud did not suffer that truncation in its saved
  capture. A homepage import also does not discover additional product pages.
- Bare inline SVG exports lost page CSS paint. The repaired AWS source includes
  a dark-ink transparent SVG; no verified inverse primary was selected from this
  homepage. Eleven downloaded logo *candidates* are not eleven AWS logo variants.

## Implementation and evidence

- Unified HTML and page response limits at the existing 5 MiB transport budget.
  Static and rendered capture reject oversize HTML instead of returning a prefix.
  Deterministic capture refusal does not retry another browser backend.
- Rendered capture serializes a detached DOM copy and bakes observed SVG paint,
  visibility, transforms and text styling. It preserves the live page/screenshot,
  keeps local paint-server references local, and bounds SVG processing at 20,000
  elements. Failure or oversize serialized output stops that capture.
- Live AWS capture through the application code retained 33 image references,
  downloaded 20 image resources and 11 logo candidates. Styling-preserved HTML
  was 3,475,572 bytes. Selector replay recovered a transparent primary SVG, a
  favicon-derived mark and another wordmark record, with inverse still missing.
  Reviewed the primary through the existing logo rasterizer; no logo recoloring.
- Scratch captures/replay files stay ignored in `.local-setup/aws-capture-audit/`.
  No production writes, ad harvesting, generation test, or Google/Clue/Conduit
  source refresh was performed in this change.

## Verification and operational notes

- Added red/green static/rendered tests for body assets after a large head, exact
  limit, UTF-8 byte limits, oversize refusal and no browser retry. Browser tests
  export light/dark-ink SVGs and reopen them without page CSS, preserving colors
  and leaving the live source unchanged.
- Targeted capture/logo matrix: 141 passed, 1 skipped, 1 deselected. One existing
  skip remains; the unrelated DB-writing color integration test was deselected.
  Initial sandbox-only failures were DNS/DB access restrictions. The first SVG
  fixture accidentally inherited the browser's blue anchor color; fixed fixture
  inheritance before validating the intended white ink.
- Local jobs were idle (52 fleet tasks done; 5 ingestion jobs succeeded). Restarted
  only the worktree's recorded stack. Direct launcher execution lacked executable
  permission; invoking the existing launcher with Bash succeeded. APIs, frontend
  and 4/4 workers returned healthy; pinned brand frontends retained their ports.
- A read-only status query initially guessed `design_job`; the actual task table
  is `fleet_task`. A scratch rasterizer probe initially used the wrong argument
  type; reran using LadderCandidate. Neither diagnostic changed persistent data.
- Submitted AWS re-extraction through its real localhost:3022 UI after restart.
  It succeeded and refreshed the existing kit as a Draft; left approval to review.
  Browser shows 32 assets versus the old 4, including two transparent SVG logo
  records, page illustrations, photos and a separate 20-year anniversary lockup.
  Those are not 32 validated creative backgrounds; old favicon/font resources
  remain in the library. The anniversary asset is not an inverse primary logo.
- Browser exposed a follow-on UI bug: router.refresh preserves hook state, so
  drafts seeded only at mount omitted new assets and their dialog would not open.
  Store local edits as overrides over current asset metadata. Confirmed live:
  new SVG dialog opens without a page reload; its image loads at 109x64 with
  object-fit contain. Read bundled Next docs before modifying the hook.
- Frontend design-system build, lint and production build pass (the two existing
  unused snap-helper warnings remain). NEXT_DIST_DIR was not a supported output
  override here; the build used .next. The four pinned frontends use separate
  .next-local-PORT directories and were unaffected. No generated files changed.
- The image description inaccurately calls the lowercase AWS wordmark uppercase;
  automatic descriptions and asset suitability are not fully validated by this
  source-capture fix. Do not claim complete onboarding or perfect branding.
