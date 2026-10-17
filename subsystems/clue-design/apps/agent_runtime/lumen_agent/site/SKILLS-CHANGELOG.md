# Skill and prompt changes, with the failing case behind each

Not loaded into the agent. One line per rule change (the lean rule: a rule enters only when a run
fails without it).

- 2026-10-08 · system prompt, edits: "If the request names something that is not on the page, say
  so and ask before adding anything." Failing case: a3 edit 7 (added a four-card section for cards
  that did not exist). Fixed in E2b edit 7.
- 2026-10-08 · account-page-copy, part 3: "The brief may suggest a proof or a structure. Treat it
  as a suggestion…" Failing cases: a1, a2, a3 builds (followed the brief's Nightingale suggestion;
  never searched Garner's site; the skill's fit check was skipped).
- 2026-10-08 · account-page-copy, part 5: "Say whose result it is in the kicker or the source
  line; keep the heading about the result." Failing cases: a3 edit 2, E2b ("Another employer's
  result — not SCSD's" as the proof heading).
- 2026-10-08 · page-review and system prompt step 5: render again until the review passes, up to
  3 renders in all (was: once more at most). Failing case: b1 (a known orphan in the hero headline
  shipped after the one allowed re-render).
- 2026-10-08 · new skill rebuilding-a-section (skills-e5, founder-approved), for the seller
  component library spike. Written before a run: the task (rebuild a clone as a component) had no
  skill at all.
- 2026-10-08 · writing-a-section, kit list: `kit.Image` with `fit="fill"` for a background photo;
  rules: surfaces may also come from `bg-surface-<role>` + `text-on-surface-<role>` for panels
  edge to edge. Failing cases (seen before the run, in the originals): Garner's hero (text over a
  full-bleed video) and closing panels (two panels edge to edge) could not be expressed with
  `kit.Shell` and the fixed `kit.Image`.
- 2026-10-08 · writing-a-section, kit list: each piece shown with its exact props (`label` for the
  button's words, `src` for an image). Failing cases: run cl3 turns 1, 2, 3 and 5, each with a write
  refused for a guessed prop (`file` for `src`; the button's words as children).
- 2026-10-09 · system prompt, R1 (founder-approved wording, founder ruling D3): the brief is
  direction (goal, reader and offer fixed; suggested facts, proof and structure are suggestions,
  say why in plan.md when choosing differently); `research/` names the claim labels, the claims file
  and the background-only sections; new rule: check a research number or quote in
  `research/claims.md`. No failing case yet: the R1 runs test it. Code side: research files now keep
  every statement type, its notes, and the Watch-outs / Context only sections (marked background);
  the claims file comes from the claims the research cites (the source drawer's read), gated by the
  platform rule.
- 2026-10-09 · new skill images-and-logos (founder-approved wording, R3): reuse the brand's real
  images; generate only a scene or a mood (no words, logos, real people, product screens, or the
  account's own places); no image beats a weak image; the account's logo only in the header; a
  customer-logo row must not imply the account is a customer. System prompt: brand.md holds the
  account's logo; view_asset and generate_image listed; four skills. building-with-puck: images
  come from brand.md or generate_image. Written before a run (the agent had no way to make an
  image); R3 runs test it.
- 2026-10-10 · account-page-copy, part 2 (founder-approved wording): "The research's notes on how
  to approach the account (who to call, what to offer, where you overlap or compete) are for you.
  Never put them on the page." Failing case: r1b-base (its closing line said "overlap, coexistence,
  a geographic split, or a referral into hotels", from a research inference on approaching Dana.AI).
- 2026-10-12 · system prompt, workspace (T1, founder-approved): new `project-context/` line, "the
  project's own instructions and decisions, as they stood when this site was asked for." No
  failing case: production gives the agent the project's pinned files; the spike had none.
- 2026-10-12 · system prompt, tools (T2a, founder-approved): `validate_page` no longer says it
  saves a version. No failing case: production saves one version of the document per request (its
  history), not on each validation.
- 2026-10-12 · system prompt, tools (T2b, founder-approved): `restore_version` "brings back an
  earlier saved version of the site (`site.md` lists them)." No failing case: production versions
  are the document's history.
- 2026-10-12 · system prompt, tools (T2c, founder-approved): new `search_assets` line, "finds the
  seller's other images (uploads, and images made for earlier pages) by what they show." No
  failing case: production adds the tool; the spike had only the images in `brand/brand.md`.
- 2026-10-12 · system prompt, how to work step 1 (T3, founder-approved, Q10): "Your skills" (was
  "Your four skills"), and "for new sections `writing-a-section` and `rebuilding-a-section`." No
  failing case: production ships all six skills, the two section skills on by default.
- 2026-10-12 · building-with-puck, "When validate_page says INVALID" (T4, founder-approved): "If a
  change made the page worse, fix it, or bring back an earlier saved version with `restore_version`
  (`site.md` lists them)." (was: `restore_version` brings back the last good version). No failing
  case: production versions are the document's history, not saved by `validate_page`.
- 2026-10-12 · images-and-logos, part 1 (T5, founder-approved): new last bullet, the seller's other
  images are not in `brand/brand.md`; find them with `search_assets` and look with `view_asset`
  before use. No failing case: production adds `search_assets`.
- 2026-10-12 · writing-a-section (T-A9-5, founder-approved): the example's `surface` is
  `z.string()` (any surface in brand/brand.md); the kit list adds `look` on `kit.Button`,
  `kit.Link`, `kit.Card`, `fit="contain"` on `kit.Image`, and the brand's motion classes; the Rules
  bullet adds the brand's spacing classes (`py-section`, `mt-stack-tight`). No failing case: the A9
  brand-fidelity rewrite gives the kit these pieces.
- 2026-10-12 · page-review: render_page no longer reports console errors (the production
  screenshot runs no script, so the count could never change); section crashes arrive as render
  notes or NOT RENDERED instead.
- 2026-10-15 · new skill making-a-section-interactive (skills-live, loaded only in workspaces on
  LUMEN_SITE_LIVE_WORKSPACES; publishing live sites, phase 1; approved by the founder 2026-10-15):
  state, handlers, timers and effects; draw the same thing on the server and in the browser; stay
  still while `kit.editing`; stay on the brand; an accordion example. No failing case: live sites
  give sections a browser to run in for the first time.
- 2026-10-15 · system prompt, live workspaces only (founder-approved wording 2026-10-15; swapped in
  by harness.py, system_prompt.md unchanged): the render_page line adds "its notes name any place
  the server and the browser drew a section differently", and step 1 names
  `making-a-section-interactive` "when a section needs to respond to the visitor". No failing case:
  the skill was in a live prompt that never named it.
- 2026-10-16 · writing-a-section, rebuilding-a-section and making-a-section-interactive (S2a-2,
  option B; founder-approved wording 2026-10-16): mark every prop a marketer reads as words on the
  page with `.meta({ edit: "inline" })`, put it into the page exactly as it is and never change it
  in code; never mark choices, links, images or `alt`. The writing-a-section example marks `quote`
  and `attribution`; rebuilding-a-section step 2 marks headings, paragraphs and button words; the
  accordion marks `heading`, `question` and `answer`. Failing case: S2a-2 (review 2026-10-14), every
  string prop of an agent section was edited in place, so in Edit mode `surface` drew as
  `bg-surface-[object Object]`, `alt` read "[object Object]", and a section that capitalised its
  text crashed.
- 2026-10-17 · page-review and the system prompt (step 5), and render_page's description and
  refusal: `render_page` checks the page first, so the agent never calls `validate_page` right
  before a render; a failed render names the step and the renderer's own message, and tells the
  agent not to rework the page for the renderer's own failure. Failing case: lane run
  run_site_590eb594523c (2026-10-16): a platform bug failed every preview of a page with two agent
  sections, the answer said only "Validate it and try again", and the agent spent 19 minutes and
  17 useless validate calls guessing, rewrote its section nine times and reworked the FAQ.
- 2026-10-17 · writing-a-section, rules (founder-approved): "Name every heading, paragraph and
  label: add `data-clue-el="<name>"`…; for `kit.Eyebrow` and `kit.Link`, pass `el`"; the example
  names its quote and attribution. building-with-puck: new part "Styling by hand (`_edits`)"; system
  prompt: the header's and footer's text can be restyled with `_edits`. Not a failing run: the site
  element inspector (plan 1) gives the marketer per-element styling, which only reaches agent
  sections whose text is named, and the agent must keep, change or drop the marketer's `_edits`
  knowingly.
- 2026-10-17 · writing-a-section and building-with-puck (founder-approved, site element inspector
  plan 2): marked props hold rich text and are put into the page as they are; a marked prop's
  element is named after the prop; a Rich text section (the grammar, links, `data-new-tab`, styled
  spans `<name>~<n>`); new-tab link props; library fonts ("Other fonts") in `_edits`. Written before
  a run: rich text, links on text and library fonts are new in the editor (plan 2).
- 2026-10-18 · writing-a-section and building-with-puck (founder-approved, site element inspector
  plan 3): `kit.Button` takes `el` (its words are `<el>.label`) and the naming rule lists it;
  "Buttons and links" adds `buttonNewTab` / `ctaNewTab` / a cloned button's name in `newTab`, and
  that a button's words hold rich text but never a link; "Styling by hand" adds a button's box
  properties (`fill`, `borderColor`, `borderWidth`, `radius`, `padding`, `width`) and its words'
  name. Written before a run: buttons are new in the editor (plan 3), so the agent must name them
  and keep, change or drop the marketer's button styling knowingly.
