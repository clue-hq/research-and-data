# Puck trial → production: what the trial proved that is not in production yet

Date 2026-10-17. Read-only audit on branch `site/publish-durability`: no edits, commits, DB writes or model calls.

**How to read this.** "DONE" means I found the mechanism in production code (file:line given). A doc mention alone does not count.
"PARTIAL" means some of it is in code and the rest is not. "MISSING" means I found no code for it. A Wave 2 review finding that
already tracks a gap is named by its id (`docs/superpowers/verification/2026-10-14-wave2-{area,contract}-review-findings.md`); every
id cited here is still open per those docs and `git log` since 2026-10-14.

Path shorthand: `kit/` = `apps/frontend/packages/site-kit/src/`, `ed/` = `apps/frontend/packages/site-editor/src/`,
`api/` = `subsystems/clue-design/apps/api/lumen_api/`, `ing/` = `subsystems/clue-design/apps/api/lumen_ingestion/`,
`agent/` = `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/`, `T/` = `trials/puck-spike/`.

## Already known (not re-derived)

| Item | Status |
|---|---|
| Measured brand facts: heading ink on light surfaces, the standard button (pill radius, padding, height, light version), card text (PRODUCTION-NOTES item 5, `T/PRODUCTION-NOTES.md:27-31`; `T/export/measure_brand.py`) | MISSING. Report: `.superpowers/sdd/2026-10-16-s2a-2/theme-investigation.md` |
| Published pages as static HTML with no hydration (`T/PRODUCTION-NOTES.md:16-20`) | SUPERSEDED by the founder ruling of 2026-10-15 that published sites ship JavaScript |
| Live-preview eval wait, preview assets served on request, hero video stacking | Fixed 2026-10-17 (`ff2292264`, `78a8b5fa3`, `1c2503780`) |

## Counts (rows below; already-known rows not included)

**DONE 51 · PARTIAL 14 · MISSING 11 · SUPERSEDED 1.** On top of these, the already-known measured brand facts (3 facts) are also missing.
One row (thin research, C4) is outside the site layer and is not counted.

## Brand fidelity

| # | Item | What the trial proved/decided (source) | Production status | What is missing, and where it would go | Size |
|---|---|---|---|---|---|
| B1 | Text colour on each surface from the kit's `contrast_pairs` | `T/FINDINGS.md:60-61`; `T/lib/theme.ts:67-68` | DONE: `kit/surfaces.ts:53-60` (pairs, then the better ink, with a ≥4.5:1 check), used by `kit/theme.ts:160-163` | — | — |
| B2 | Whether a surface is dark is decided per brand, not hard-coded | Bug 6, `T/FINDINGS.md:46-47` | DONE: `kit/surfaces.ts:71-74` (ink lighter than the background) | — | — |
| B3 | Theme component rules live in `@layer components`, so Tailwind utilities win | Bug 5, `T/FINDINGS.md:44-45` | DONE: `kit/theme.ts:229`, `:272` | — | — |
| B4 | Token check (G3): computed font, size, weight, line height, letter spacing, surface, text colours and button radius equal the kit's values, in the editor and on the published page, for each brand | `T/FINDINGS.md:21`; `T/export/check_tokens.py` | PARTIAL: CSS-text unit tests (`apps/frontend/packages/site-kit/test/theme.test.ts`, `contrast.test.ts`, `a9-scenarios.test.tsx`). No test reads computed styles from a rendered page and compares them with the kit | A browser check per fixture kit (Garner, Conduit, Alt Carbon) over a published render and the editor frame, next to `tests/site_editor/` or `api/tests/test_site_render.py` | small–medium |
| B5 | The kit's own usage rules reach the agent | ISSUES 5, `T/ISSUES.md:23-28` | DONE: `kit/catalog.ts:405-409`, `:434-435` (the `brief.constraints` rules). `grammar_audit` is not printed | — | — |
| B6 | All 12 type roles are shown to the agent | ISSUES 47, `T/ISSUES.md:207-210` (founder: "required in production") | DONE: `kit/theme.ts:21-24`; `kit/catalog.ts:244-266` | — | — |
| B7 | Kit pieces the trial lacked: an image fit that shows the whole image, the seller's other button styles, links through the kit, a check that a brand class exists | ISSUES 49, `T/ISSUES.md:214-217` | DONE: `kit/agent-kit.tsx:27-43`, `:62` (`fit="contain"`, logos shown whole); button and card looks (`kit/catalog.ts:280-356`); raw `<a>` refused (`kit/check-section.ts:56`); unknown brand colour class refused (`kit/check-section.ts:51-53`, `:432`) | — | — |
| B8 | On the `inverse` surface, headings must not take the brand's heading ink | ISSUES 28, `T/ISSUES.md:108-110` | DONE: `kit/theme.ts:175-176` (ink-role variables are `initial` on dark surfaces, so the surface ink applies) | — | — |
| B9 | A FeatureSplit with no image becomes one text column, not an empty frame | ISSUES 29, `T/ISSUES.md:111-112` | DONE: `kit/sections.tsx:164-165` | — | — |
| B10 | The token class names and each kit piece's props are listed for section writing | ISSUES 35, 50, `T/ISSUES.md:151-153`, `:218-219` | DONE: `agent/skills-e5/writing-a-section/SKILL.md:38-60`; the classes appear in brand.md's type and spacing sections (`kit/catalog.ts:244-277`) | — | — |
| B11 | The section example carries conventions: `brand-heading`, and "kit.Shell already sets the width and padding" | E5b lesson, `T/AGENT-FINDINGS.md:127-134`; ISSUES 39, `T/ISSUES.md:166-171` | PARTIAL: the example carries `brand-heading` (`writing-a-section/SKILL.md:27`). Nothing says Shell sets the width and padding (`:39-40` mentions only the text colour) | One line in `writing-a-section` (skill text, founder review) | small |
| B12 | When no button was measured, fall back to the kit's button tokens (Alt Carbon) | ISSUES 2, `T/ISSUES.md:15-17`; `T/lib/theme.ts` | DONE: the standard button comes from kit tokens (`kit/theme.ts:184`). Buttons are measured from the whole page (`ing/measured_components.py:1-14`) | — | — |
| B13 | Type below 1440 is measured, not generated | "Not covered", `T/FINDINGS.md:114` | MISSING: still generated from the desktop size (`kit/theme.ts:146` → `kit/brand-values.ts:311-316`, `measuredAtPx: 1440`, `:35`) | Ingestion records a phone-width type sample per role. The theme uses it in place of `fluid()` | medium |
| B14 | A long account name in the mobile header wraps instead of being cut off | ISSUES 42, `T/ISSUES.md:180-181` | PARTIAL: the button is hidden on phones to make room (`kit/shell.tsx:74-76`), but the name still has `truncate` (`kit/shell.tsx:58`) | Wrap to two lines in `kit/shell.tsx` | small |
| B15 | Kit coverage gaps: no role for 18 px card titles, 8 of 12 roles derived, dark-green bands not offered as a surface | ISSUES 48, `T/ISSUES.md:211-213` | PARTIAL: re-captured kits now offer measured band surfaces (`surface.band.*`, kit v3; `kit/surfaces.ts` extra roles). There is no card-title role, and the derived roles stay derived (`ing/normalizer/typography.py`) | Ingestion mints a card-title role and measures more of the roles | medium |

## Page weight and publishing

| # | Item | What the trial proved/decided (source) | Production status | What is missing, and where it would go | Size |
|---|---|---|---|---|---|
| P1 | De-duplicate clone CSS at publish: shared rules once, per-clone rules scoped, drop rules that match nothing | PRODUCTION-NOTES 1, `T/PRODUCTION-NOTES.md:8-12`; `T/FINDINGS.md:72-74` | PARTIAL: live pages join each distinct whole clone stylesheet once (`kit/render-core.tsx:111-118`). Static mode keeps one stylesheet per clone. Nothing de-duplicates rules across clones or drops unmatched rules | A CSS pass in `api/site_publish.py` (after the render, before the cleaner) that merges shared rules and drops unmatched ones | medium |
| P2 | Ship only the font faces the page uses, as WOFF2 | PRODUCTION-NOTES 2, `T/PRODUCTION-NOTES.md:13-15` | PARTIAL: kit faces are re-encoded to WOFF2 at publish (`api/web_export.py:397-406`, via `api/site_publish.py:130-135`). Every kit face ships (`kit/theme.ts:132`), and the clones' own `@font-face` rules pass through untouched (501 font files on Garner, per the 2026-10-17 entry in `ledger.md`) | Keep only the faces the rendered page's computed styles use, and also gate the clone stylesheets' faces. The step belongs in `api/site_publish.py` | medium |
| P3 | Static HTML, no hydration | PRODUCTION-NOTES 3 | SUPERSEDED by the ruling of 2026-10-15 (sites ship JS) | — | — |
| P4 | Hero video: a poster image, `preload="metadata"` and a compressed rendition | PRODUCTION-NOTES 4, `T/PRODUCTION-NOTES.md:21-23` | MISSING: the capture only keeps a poster the seller already had (`ing/capture/candidates.py:182-187`). There is no transcode, no poster we generate, and no preload attribute anywhere in `kit/` or `api/site_*.py` | Make the rendition and poster at capture (fragment minting); set `preload="metadata"` in the clone filler (`kit/clone.ts`) | medium |
| P5 | The published route carries no editor code | Bug 4, `T/FINDINGS.md:41-43` | DONE: `apps/frontend/packages/site-kit/test/bundles.test.ts:51-61`; `kit/live-page.tsx:3-4` (render-only `Render`) | — | — |
| P6 | Captured links the page did not change are made absolute against the clone's source page | ISSUES 22, `T/ISSUES.md:79-83` | DONE: `kit/clone.ts:79` | — | — |
| P7 | Each agent section's CSS is compiled when it is written and stored with it; utilities never depend on a global scan | `T/RUNTIME-SECTIONS.md:70-77`; ISSUES 46, `T/ISSUES.md:204-206` | DONE: `api/site_turn_ports.py:240` (compiled at write, recorded with the module); served to the editor at `ed/client/sections.ts:22`; the published CSS is compiled over the rendered HTML (`api/site_render.py:388-408`) | — | — |
| P8 | Publish refuses a missing or stale module and renders inside the bounded process | `T/RUNTIME-SECTIONS.md:97-99` | DONE: `api/site_render.py:100-109` (digest and staleness checks); `api/site_publish.py:201-205` (modules, clone pins, contract checks, hardened render) | — | — |
| P9 | Published HTML is cleaned by an allow-list sanitizer and served under a strict policy | `T/RUNTIME-SECTIONS.md:96-99`; D2 decision `:101-108` | DONE: `api/site_sanitize.py`; `api/site_publish.py:229-233`, `:285`. Still open: S3-2 (the cleaner takes quadratic time), S3-5, K5-5 (theme CSS injection) | — | — |
| P10 | Live publishing to the page origin | "Not covered", `T/FINDINGS.md:117` | DONE: `api/site_live.py`; the live branch of `api/site_publish.py:207-247` | — | — |

## Robustness and security

| # | Item | What the trial proved/decided (source) | Production status | What is missing, and where it would go | Size |
|---|---|---|---|---|---|
| R1 | Each section's props are defined once in Zod; Puck fields and a JSON Schema come from that; every agent write is validated | PRODUCTION-NOTES 7, `T/PRODUCTION-NOTES.md:38-40` | DONE: `kit/schemas.ts:1-6` (strict objects); `kit/catalog.ts:141` (`z.toJSONSchema`); `api/site_doc_validate.py:1-11` | — | — |
| R2 | An error boundary around each section | PRODUCTION-NOTES 8, `T/PRODUCTION-NOTES.md:41-43` | PARTIAL: agent sections only (`kit/config.tsx:79-98`, `:186`). Our own sections, clones and the editor root are not wrapped (S2a-8 open: a crash outside an agent section blanks the editor) | Wrap every component render in `kit/config.tsx`, and add a top-level boundary in `ed/client/main.tsx` | small |
| R3 | A CSS leak test in CI for every new brand (Tailwind-built clones such as Conduit) | PRODUCTION-NOTES 9, `T/PRODUCTION-NOTES.md:44-47`; G2, `T/FINDINGS.md:20` | MISSING: no leak or bleed probe in `site-kit/test`, `tests/site_editor` or `api/tests/test_site_*` | A probe page that renders our sections alone and between each fixture brand's clones and compares computed styles both ways. It belongs in site-kit tests or `api/tests` | small |
| R4 | Pin Puck, and keep our own contract tests on editor behaviour (resolveData on load, undo history, pointer events) | PRODUCTION-NOTES 10, `T/PRODUCTION-NOTES.md:48-50`; T9, `T/FINDINGS.md:31` | PARTIAL: pinned to `@puckeditor/core` 0.23.0 (site-kit `package.json`, `ed/../package.json:15`); resolveData removed (`kit/config.tsx:254`). The browser contract tests (`tests/site_editor/*.py`) are opt-in (`tests/site_editor/conftest.py:39-42`, `CLUE_SITE_EDITOR_BROWSER=1`), so nothing runs them by default | Run `tests/site_editor` in a gate, with the site-editor build as its prerequisite | small |
| R5 | A banned-identifier lint is a cheap first gate, not the security boundary | `T/RUNTIME-SECTIONS.md:37`, `:84-87` | PARTIAL: the lint exists (`kit/check-section.ts:164-182`, `:204-235`), but S5-1 is open: `export … from` and `require()` are not checked, so the bundler copies server files into a section (`kit/check-section.ts:205`; `site-kit/bin/compile-section.ts:47-67`) | Check every import, export and require; confine the bundler to the section's own folder (S5-1) | small |
| R6 | The server render runs in a no-network, read-only, time- and memory-bounded process (closes the `process.getBuiltinModule("node:fs")` escape) | `T/RUNTIME-SECTIONS.md:39`, `:43-59`, `:91-95` | DONE: sections render in hardened Chromium, not Node, so Node builtins are unreachable (`api/hardened_browser.py:1-55`: no DNS, dead proxy, offline context, 256 MB V8 heap, browser killed at the end; `api/site_render.py:126-131` render CSP) | — | — |
| R7 | Resource abuse is bounded (an endless loop; a 20k-row output of 32 MB) | `T/RUNTIME-SECTIONS.md:37`, `:52-54` | PARTIAL: there is a timeout and an output cap (`kit/render-core.tsx:96-99`, `api/site_render.py:111-112`). S3-1 is open: a section forges the size and the error the page reports (5 MB past a 1 MB cap; 80 MB took the API to 1.85 GB). S3-2 is open: one section can stall publishing for minutes | Measure what Python actually received and capture the builtins before any section loads (S3-1); clean in one pass (S3-2) | small–medium |
| R8 | Containment in the editor: a separate domain with no login, modules reached by a signed link for this workspace and document, never by a URL segment | `T/RUNTIME-SECTIONS.md:84-87`, `:94-99`; D2 `:101-108` | DONE: `api/site_section_links.py:5-12` (10-minute HMAC token bound to workspace and document); `ed/server/csp.ts:11-16`; `kit/editor-origin.ts:18-53`; `tests/site_editor/test_editor_containment.py:42`. Still open: K3-2, K3-7 | — | — |
| R9 | One shared React: the host's react, jsx-runtime and zod handed to modules through an import map | `T/RUNTIME-SECTIONS.md:60-64` | DONE: `kit/site-runtime.tsx:20`; `ed/client/host-globals.ts`; one definition of the imports (`a23b15240`, K2-1) | — | — |
| R10 | Stable list keys, so inline edits do not collide | `T/RUNTIME-SECTIONS.md:65-69`, `:88-90` | MISSING: no injected keys and no skill rule. The skill's own live example keys by index (`agent/skills-live/making-a-section-interactive/SKILL.md:54`) | A rule in `writing-a-section`, or a check-section lint that refuses `key={item.<text prop>}` | small |
| R11 | Internal `/route` links must point to a real page; one primary destination across the site | ISSUES 20, 23, `T/ISSUES.md:76-77`, `:84-88` | DONE: `kit/validate.ts:126-131`, `:246-260` | — | — |
| R12 | `write_section`'s type check really checks the file | ISSUES 45, `T/ISSUES.md:202-203` | DONE: `kit/check-section.ts:484` (tsc over a shadow copy of the section) | — | — |
| R13 | `fetch_page` sits behind SSRF, size and time guards (the trial's fetcher had none) | Readiness §2.2, from the trial's tool | DONE: `agent/tools.py:675-702` (`web_substrate._fetch_grounded_page`, `CaptureError`) | — | — |

## Editor and editing

| # | Item | What the trial proved/decided (source) | Production status | What is missing, and where it would go | Size |
|---|---|---|---|---|---|
| E1 | Loading the editor must not reset a clone's slots (resolveData runs on load) | Bug 1, `T/FINDINGS.md:36-37` | DONE, by a different route: no resolveData at all (`kit/config.tsx:254`) | — | — |
| E2 | Inline clone edits are recorded in undo history | Bug 2, `T/FINDINGS.md:38` | DONE: `kit/editor/clone-editor.tsx:84`. Server undo; S2a-1 fixed | — | — |
| E3 | Clone text can be clicked in the canvas (`data-puck-overlay-portal`) | Bug 3, `T/FINDINGS.md:39-40` | DONE: `kit/editor/clone-editor.tsx:63` | — | — |
| E4 | One shared header and footer, edited once, with nav links in the shell editor | T7, `T/FINDINGS.md:29`; ISSUES 23 | DONE: `kit/config.tsx:119-140` | — | — |
| E5 | Clone slots, text replacements for baked labels, and link replacements | T5, `T/FINDINGS.md:27` | PARTIAL: the schema and renderer exist (`kit/schemas.ts:104-106`). S1-3 is open: replacements the check accepts are never applied, because the catalog, validator and renderer read clone text three ways (`kit/catalog.ts:52`, `kit/validate.ts:39-40,177-183`, `kit/clone.ts:101-115`) | One shared "visible text" function, and a check that accepts only what the renderer can replace (S1-3) | medium |
| E6 | Editor fields come from each agent section's Zod schema; text is edited in place | `T/RUNTIME-SECTIONS.md:35`, `:88-90` | DONE: `ed/client/config.tsx:76` (`puckFieldsFromJsonSchema`); `kit/agent-props.ts`. Edit in place shipped 2026-10-17 (S2a-2) | — | — |
| E7 | Rich text: adopt Puck's richtext with changes (our own `renderInlineMenu` controls, a `data-puck-rte-menu` root, options narrowed to 8 tags, an allow-list refine in the schema, a dock field kind, `<p>` wrappers becoming `<div>`s, list CSS, skill text, the render waiting for the chunk) | `T/RICHTEXT-R5.md:15-31`, details `:121-158` | MISSING: no `richtext` anywhere in `kit/`, `ed/` or `apps/frontend/src/features/site-editor`. Long text is still `z.string()` (`kit/schemas.ts:31-32`), and the published runtime deliberately excludes TipTap (`bundles.test.ts:61`) | As R5 lists: start with `FeatureSplit`, `CtaBand` and `ProofCard` `body` | medium |
| E8 | Reorder by mouse drag (proven in T9), plus insert, delete and duplicate | T9, `T/FINDINGS.md:31`, `:107`; readiness D4 | MISSING: all turned off (`ed/client/editor-app.tsx:16-17`, `{delete:false, drag:false, duplicate:false, insert:false}`) while the founder's designs are awaited (C13) | Designs for the insert palette and delete/duplicate; then turn on drag (reorder can reuse the existing handles) | medium |
| E9 | Image swap through a brand-asset picker that includes the seller's captured photos | T6, `T/FINDINGS.md:28`; `T/FINDINGS.md:104` | DONE: `kit/editor/asset-picker.tsx`; captured images joined in `api/site_brand.py:50-63` | — | — |
| E10 | Selections and annotations reach the agent | Readiness §5, from T9's selection reporting | DONE: `agent/workspace.py:608-622` (`targets_block`); S5-2 fixed | — | — |

## Agent harness

| # | Item | What the trial proved/decided (source) | Production status | What is missing, and where it would go | Size |
|---|---|---|---|---|---|
| H1 | One fresh session per request, with code-written `site.md` and `history.md` as memory | `T/AGENT-FINDINGS.md:149-150`; ISSUES 26 | DONE: `agent/harness.py:13-14` (a fresh thread per run); `agent/workspace.py:514`, `:715-717` | — | — |
| H2 | Context clearing starts only above 60k tokens; compaction | `T/AGENT-FINDINGS.md:151-153`; ISSUES 31 | DONE: `agent/harness.py:49`, `:170-180`; compaction sized by `compaction_for` (`:570-586`) | — | — |
| H3 | Tool calls in one response run in order | `T/AGENT-FINDINGS.md:160-161` | DONE: `agent/harness.py:182` | — | — |
| H4 | A finish guard (no turn ends on an invalid page); the safety stop follows the ruling (100 rounds, 50 calls per round, 30 min) | `T/AGENT-FINDINGS.md:31-32` | DONE: `agent/harness.py:221`, `:267`, `:303` | — | — |
| H5 | Whole-file reads | ISSUES 18, `T/ISSUES.md:73` | DONE: `agent/harness.py:210` | — | — |
| H6 | A cost record per call (catches provider cache misses) | `T/AGENT-FINDINGS.md:154-155`; ISSUES 17 | DONE: receipts through `usage_collector.turn_collector` (`agent/harness.py:12-13`); `agent_runtime/tests/test_site_cost_and_tracing.py`; Langfuse traces | — | — |
| H7 | Skills carried in the cached system prompt | ISSUES 34, `T/ISSUES.md:139-140` | DONE: `agent/harness.py:389-409` | — | — |
| H8 | Contracts in code, judgement in the prompt | `T/AGENT-FINDINGS.md:156-159`; ISSUES 19 | DONE: `kit/validate.ts:1-5` | — | — |
| H9 | Screenshots keep their width (mobile shots are not shrunk) | ISSUES 16; `T/AGENT-FINDINGS.md:164` | DONE: `agent/tools.py:47`, `:429-449` | — | — |
| H10 | The agent can view an image (`view_asset`) | ISSUES 27; `T/AGENT-FINDINGS.md:165` | DONE: `agent/tools.py:533-568` | — | — |
| H11 | Up to 3 renders | ISSUES 11, 21, 43 | DONE (prompt, as in the trial): `agent/system_prompt.md:50-52` | — | — |
| H12 | "If the request names something not on the page, say so and ask" | ISSUES 24; `T/AGENT-FINDINGS.md:87-90` | DONE: `agent/system_prompt.md:76-78` | — | — |
| H13 | The brief's facts and proof are suggestions | a4, `T/AGENT-FINDINGS.md:65-72` | DONE: `agent/system_prompt.md:66-68`; `account-page-copy/SKILL.md:46` | — | — |
| H14 | The lasting fix is upstream: the brief describes proof candidates, it does not prescribe them | `T/AGENT-FINDINGS.md:166-167` | PARTIAL: Head of ABM's brief guidance still asks for "Customer stories that fit" (`platform/agents/catalog/skills/manual-siblings/v20/SKILL.md:127`), not candidates with their conditions | Wording in manual-siblings (founder review) | small |
| H15 | The proof fit check is a gate before the preference order | ISSUES 8, 41, `T/ISSUES.md:39-44`, `:176-179` (text proposed to the founder) | MISSING: unchanged order. "Same industry and size" ranks above "same situation", and the fit check is a later bullet (`agent/skills/account-page-copy/SKILL.md:51-57`) | Reorder in `account-page-copy` (founder review) | small |
| H16 | The research's notes on how to approach the account are for the agent, never the page | ISSUES 55, `T/ISSUES.md:251-255` | DONE: `account-page-copy/SKILL.md:39` | — | — |
| H17 | The claims file is the standard research input (D3) | ISSUES 54, `T/ISSUES.md:246-250` | DONE: `agent/workspace.py:673-679`; `agent/system_prompt.md:8-11`, `:60-61` | — | — |
| H18 | `site.md` carries a one-line "contains" note per clone (edit 6 spent 9 calls hunting a logo row) | ISSUES 33, `T/ISSUES.md:137-138` | PARTIAL: site.md lists only the clone's label and changed slots (`agent/workspace.py:436-452`). The clone card holds the visible text, but costs a read | Add a "contains" line from the clone's visible text in `site_summary` | small |
| H19 | Small edits should not have to keep `plan.md` up to date (9 of 15 calls on edit 2) | ISSUES 32, `T/ISSUES.md:134-136` | MISSING (open decision): the prompt still requires plan.md on every change (`agent/system_prompt.md:72`, `:76`) | A prompt change (founder) | small |
| H20 | Keep the transcript of every turn | ISSUES 53, `T/ISSUES.md:225-226` | DONE: a checkpointed thread per run (`agent/harness.py:13-14`); Langfuse holds every observation (`speed-investigation.md`) | — | — |
| H21 | Image generation cost is recorded | ISSUES 58, `T/ISSUES.md:264-266` | DONE: `agent/tools.py:647` (spend-scoped `image_provider.generate`); `test_site_cost_and_tracing.py` | — | — |
| H22 | Ported tools: generate_image, CLIP search, the account logo, project context | Readiness §2.5; R3, `T/ISSUES.md:256-263` | DONE: `agent/tools.py:570-597`, `:625-672`; `api/site_workspace_view.py:110-135`; `agent/workspace.py:684-690` | — | — |
| H23 | A customer-logo row must not imply a relationship; a generated image must not pass as the account's own building | ISSUES 7, 56, `T/ISSUES.md:33-35`, `:256-259` | DONE (rule): `agent/skills/images-and-logos/SKILL.md` §2 and §4. The test ISSUES 7 asked for does not exist (folded into H25) | — | — |
| H24 | The seller-proof search is limited to the seller's domain | ISSUES 13, `T/ISSUES.md:55-56` | DONE: `account-page-copy/SKILL.md:49` | — | — |
| H25 | A regression set against the success bar: page under $1 and about 10 min, edit under $0.05 and about 1 min (never met), 9 of 10 edits exact, the skills' failing cases | `T/AGENT-FINDINGS.md:136-145`; `T/agent/cases.json`, `T/agent/report_tables.py` | MISSING: no site-agent eval or cases harness in production (`agent_runtime/tests/test_site_*` are unit tests). The edit-cost target has never been measured in production. The only live data is one 22-min, about $2.76 turn caused by a now-fixed bug (`speed-investigation.md`) | A cases file plus a run-table script over `agent_model_call` and Langfuse, run before skill or prompt changes | medium |

## Capture and ingestion

| # | Item | What the trial proved/decided (source) | Production status | What is missing, and where it would go | Size |
|---|---|---|---|---|---|
| C1 | Pages built by JavaScript on scroll are captured blank (Alt Carbon) | ISSUES 1, `T/ISSUES.md:9-14`; `T/AGENT-FINDINGS.md:172` | MISSING (mitigated only): degraded clones are shown to the agent with their note (`kit/catalog.ts:97`, `:470`). The 2026-10-16 capture work handles reveals for style measurement (`ing/capture/states.py`), not section content. `docs/superpowers/specs/archive/2026-10-08-capturing-javascript-heavy-sites-notes.md` says nothing is built | Section capture that settles scroll-driven content before freezing (`ing/capture/rendered.py`, `ing/sections/`) | large |
| C2 | Describe captured clone images at ingestion, as kit assets already are | PRODUCTION-NOTES 6, `T/PRODUCTION-NOTES.md:32-34`; ISSUES 4, `T/ISSUES.md:20-22` | MISSING: a captured image still gets its alt text or `From the seller's section "…"` (`api/site_brand.py:50-63`). The clone card lists images by `src` only (`kit/catalog.ts:73-76`) | Run the asset describer (`ing/describe.py` / `asset_enrichment.py`) on fragment images at minting, store the description, and print it in the clone card and brand.md | medium |
| C3 | Garner's kit is stored under the wrong name ("Doctor Quality Analytics") | ISSUES 3, `T/ISSUES.md:18-19` | PARTIAL: the agent's brand.md is titled by the seller (`kit/catalog.ts:422`), but ingestion still names the kit from the model's narrative (`ing/pipeline.py:1080`, `:1185-1189`) | Prefer the workspace or seller name at ingestion | small |
| C4 | Thin research for most accounts | ISSUES 6, `T/ISSUES.md:29-32` | Open, research lane, not the site layer (not counted) | — | — |
| C5 | The account's logo (Syracuse had none) | `T/FINDINGS.md:112`; ISSUES 57 | DONE: `api/site_workspace_view.py:110-135` (logo family fetched and stored; none → no logo) | — | — |

## Missing items ranked by effect on the marketer's result and the agent's cost and time

1. **C2, captured images have no descriptions.** This is the trial's repeated wrong-image pick: a background glow chosen as a product shot, a graphic with baked-in text. The agent must `view_asset` blind candidates, which costs calls.
2. **E8, reorder, insert, delete and duplicate are off in the editor.** A marketer cannot move or remove a section without asking the agent. Every such change is an agent turn (minutes and dollars) instead of a drag.
3. **P4 hero video (missing), with the P1 and P2 page-weight partials.** The published page still carries a 4 MB-class video with no poster or preload, per-clone stylesheets and every font face. That is load time on the marketer's live page.
4. **C1, scroll- or JS-built seller sections are captured blank.** For sites like Alt Carbon the clone library is mostly unusable, so pages fall back to brand sections or rebuilds (the cl3 rebuild cost $3.66 and 58 min).
5. **H15, the proof fit check is not a gate.** Every Syracuse build chose a proof whose conditions contradicted the page's own claim. That is a copy-accuracy risk on every 1:1 page, and a one-paragraph skill fix.

Close behind: E7 (rich text), H25 (no regression set, so skill changes go unmeasured), B13 (generated phone type), R10 (list-key collisions on inline edits). Among the partials, **E5 / S1-3** (marketer and agent text replacements accepted but never published) matters most to the marketer.
