# 2026-10-17 — Site element inspector, plan 1 (foundations + whole-box text styling)

Branch `site/publish-durability` (trenton), local commits only.

## What and where
- Design: `docs/superpowers/specs/2026-10-17-site-element-inspector-design.md` — §7 is the source of truth
  for the six plans (status, scope, coverage, change log). CLAUDE.md points agents at it.
- Plan 1: `docs/superpowers/plans/2026-10-17-site-element-inspector-plan-1-foundations-and-text.md`.
  Ledger (git-ignored): `.superpowers/sdd/2026-10-17-site-element-inspector-plan-1-foundations-and-text/progress.md`.
- Founder rulings this session: copy the scene ad inspector for web element types; highlighted words
  style only those words; brand colours first + custom; agent free to redo manual styling; order
  text → buttons → containers → images; header/footer in scope; links on text in; reorder inside
  clones in; **no hard-coded header** → standard headers/footers become editable templates (plan 6,
  with placeholders for logo/account name in agent header code); skill text approved ("EVERY
  heading, paragraph and label"). Founder stopped SDD mid-plan: implement plans directly, one review
  at the end (memory updated).

## Built (commits c703a738d..734b39e0f)
- site-kit `edits.ts`: `_edits` prop (element key → strict StyleOverride), validated beside each
  section's props (strict agent schemas untouched); shell header/footer accept `_edits`.
- Scoped stylesheet: every page section wrapped in `div.clue-section[data-clue-section=<id>]`
  (display:contents) with `<style data-clue-edits>`; rules `!important` (clone CSS is unlayered).
  In the EDITOR the box reads `_edits` from useRawProps — Puck's inline text transform rewrites nested
  `_edits.<inline-field-name>` into InlineTextField elements (found by the browser test).
- Keys (`data-clue-el`): brand sections by prop path; shell `preparedFor`, `nav.N`, `legal`,
  `privacy`, `terms`; kit.Eyebrow/Link `el`; clones by child-index path of the CAPTURED markup.
- Frame: hit-test the keyed text under the pointer (Puck sets pointer-events none inside sections);
  `selected.element/elements`, `select.elementKey`; `refreshSelection` a frame later (Puck reports
  a click mid-redraw); a click in an unselected section selects it quietly (clone slots are overlay
  portals Puck ignores); outline via `data-clue-el-selected`.
- App: selection/Layers element rows/`commitStyleEdit`; text panel (`site-text-panel.tsx` + logic);
  shared `TextAlignment` + `TextStyleToggles`.
- Design API: scenario test `test_site_element_edits_scenarios.py` (save/read/undo/redo/publish/
  refusals); `site.md` lists "styled by hand".
- Skills: writing-a-section names every text element; building-with-puck `_edits` part.

## Verified
site-kit 262, site-editor 79, app site-editor+chat-shell 382, ad/web pin tests 441; API files render
44, write_routes 13, validation 8, state_css 3, publish_routes 21, publish_package 25, lane_b 38,
turn_ports 18, tools 3, scenarios 3; agent_runtime site_harness 26, package 4, workspace 16; browser
suites all green incl. new element-styling 5/5; frontend gate (design-system:build, lint, build) green.
Live on Garner Carmel Clay site: click hero headline (clone) + Nightingale heading + header account
name; size/colour token/italic/centre/bold saved one version each, survive reload, undo one step each;
test styling undone afterwards (doc at v15, no `_edits`). Found + fixed live: re-picking the shown
font wrote a no-op save.

## Conduit live check (done)
Agent built "Oliver Hotels & Resorts microsite" (doc_ce85194b…, run_faf1f06e…): 3m49s, 16 calls all
gpt-6.1-sol, $0.42, 0 refusals, requested_model now recorded (fix a3c36fd19 live). Plan.md reasoning
sound (Oliver's own words as goals; Wynwood/Moxxi proof attributed; 5 clones). Styling on Tailwind
clones overrides correctly (!important); size/bold/colour/align saved one version each, survive
reload, undone afterwards (doc at v9, no `_edits`). Found + fixed: Bold on a font capped at 500
(0cd48e42c); palette ramps hidden (c81393c67, ruling F3). Re-describe compares element presence only
(a391382ee). Frontend gate re-run green.

## Open / owed
- Clue has no microsite in this lane (not checked).
- Header text beyond account name/nav (Prepared for label, CTA words) is plan 6.
- Empty green button on the Carmel site's Wellness Center section (from an earlier agent turn).
- Throwaway DBs clue_t7_fresh / clue_t7_verify still to drop.
