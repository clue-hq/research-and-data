# Native website changes and typography handoff — 2026-09-29

Branch: `codex/design-agent-v1`. This delivery includes the 44 local checkpoints
through `efe828f3`, plus the reviewed account-manual activation, authored typography
coverage and this handoff. It uses the native platform runtime and shared skill
library. It is not a claim that the current generated page passes visual acceptance.

## Changes included

- **Account context and handoff:** paginated complete research reads, scoped account
  identity in design turns, preserved per-document assignment on continuation and
  grounded account/contact content guidance. Recovery from an off-project account
  now tells the agent to preserve the account ID and satisfy membership, rather
  than dropping the binding and generating a generic page. Profile `head-of-abm@v63`
  actively selects the fifteen `manual-*@v10` chapters, with reviewed hashes and
  unchanged tool grants, models, limits and workspace authority. This guidance
  does not automatically approve candidates or add project membership.
- **Shared website skills:** source-format preservation, account argument and
  evidence requirements, CTA selection, identity placement, scoped revisions,
  media composition, motion fidelity and decision-material review. These are
  shared runtime resources; new projects do not depend on custom Project Instructions.
- **Component reuse:** exact text and CTA adaptation preserve source styling;
  richer card markup and retained native tab controls survive reusable-fragment
  custody and export. Isolated previews load pinned brand fonts. Search results
  expose pagination and capture coverage. Captured behavior and reconstructed
  behavior remain distinct; a static screenshot is not an interaction test.
- **Observable review:** saved preview tiles, responsive layout measurements,
  actual glyph-font evidence, image composition details, interaction receipts and
  review gaps are available through native tools. Typography references freeze
  measured source roles before editing and compare current results at desktop,
  tablet and mobile widths.
- **Typography ingestion:** complete rendered measurements outrank incomplete
  CSS samples; unresolved font variables and invalid sizes cannot win selection.
  Fallbacks no longer masquerade as measured provenance. Generated brand guidance
  prioritizes measured responsive source styles over derived type ramps.
- **Mandatory authored-type coverage:** each distinct observed text style in a
  current composed fragment must map to a captured source role. Equivalent styles
  may share a representative within that node across all three widths. Missing
  mappings, unknown provenance or incomplete measurements prevent an `accepted`
  outcome; the draft remains saved with warnings. Source-only or authored
  self-bindings cannot qualify new text. This never triggers a repair/model call.

## Verified failure and why another scrape is not the first step

The saved Conduit capture contains a 56px/400 main heading, a 48px/400 section
heading and a 24px/400 card heading. The approved kit instead exposed a derived
32px/500 section heading and 23px/500 title. An early CSS sample had unresolved
values, but the old normalizer retained it before reaching the complete rendered
sample. Defaults and available-weight substitution then became the published
styles. Generated guidance told the agent to obey those kit values.

Actual browser glyph evidence confirms the intended regular and medium fonts
loaded. This is primarily selection, normalization and authority drift, not a
missing font download. The native run authored 32px/500 headings beside preserved
48px/400 source headings and registered zero typography references. Correcting
only skill prose could not resolve the contradictory producer guidance or the
optional verification path.

The ingestion fix was replayed against the saved evidence without a new scrape:
it recovered 56px/400 and 48px/400 with rendered provenance. That proves the
normalization correction; it does not update an existing approved kit or document.

## Typography activation still required

1. Rebuild the typography and derived guidance from the saved capture using the
   corrected shared normalizer. Preserve unrelated curated brand content and the
   previous immutable version; use the normal versioned publication seam with a
   base-version check, not a direct database patch or a brand-specific seed.
2. Validate that the new kit, its summary/grammar and the runtime brand card agree
   on family, actual font face, weight, size, line height, tracking and measured
   viewport behavior. A three-width measurement is not an inferred breakpoint rule.
3. Reload the runtime for the corrected code and explicitly select the corrected
   kit version for a subsequent approved native test. Existing documents retain
   their pinned version and literal authored CSS; publishing a new kit alone
   does not restyle them retroactively.
4. Check the resulting rendered text against frozen source roles and verify the
   selected component's structure. Mapping coverage and numerical matches do not
   establish appropriate source choice, copy quality or overall visual quality.

No new paid generation, live kit rewrite, service reload or page modification
was performed for this delivery. Existing UI output must not be described as fixed.

## Separate imagery and quality defects

The audited procedures fragment retained a foreground asset but omitted the
separate source background, using a dark fill and `contain` instead. The trace
also read only the first 12,000 characters of a 201,438-character source response
and then jumped to its end. These omissions are not caused by typography.
Complete source reads, layered media composition and native interaction-route
selection still require qualification. Account-binding behavior, account-story
quality, mobile density and final identity placement also remain live acceptance
items. See `shared-skills-native-qualification-2026-09-29.md` for the prior run.

## Verification and exclusions

- Offline typography coverage/reference/view/substrate matrix passed, including
  the thirteen new coverage cases; no provider generation was invoked.
- Manual builder/drift, active registry and composer-context matrix: 74 passed.
- All four generated v10 chapters match the builder. Scoped Ruff and
  `git diff --check` passed. Pytest emitted cleanup warnings for an older nonempty
  temporary test directory. The existing large substrate file has baseline lint
  debt; no broad cleanup is included.
- Previous checkpoints record their own focused browser/engine/ingestion tests.
  This delivery did not rerun the entire repository or qualify production rollout.
- Two unfinished seller-context test edits remain local and outside this push,
  as explicitly requested. Their proposed API is not implemented on this branch.
- Local captures, logs, environment credentials and customer report bytes are
  excluded. The repository contains code, shared guidance and operational audits.
