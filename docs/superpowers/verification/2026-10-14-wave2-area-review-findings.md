# Wave 2 review: the area (S) findings, explained

**Date:** 2026-10-14.
**Branch:** `puck/integration-wave1` (trenton).
**Code reviewed:** everything Wave 2 changed between the common base `8c1aa9e47` and the review tag
`w2/review-base-2` (commit `94e49530d`).
**Companion document:** the contract (K) review, `2026-10-14-wave2-contract-review-findings.md`, in
this folder. Read that one first for how the review works. This document uses the same terms, path
shorthand and severities.
**Raw material:** each reviewer's full report and probes are in
`.superpowers/review/2026-10-13-wave2/reports/S*.md` (git-ignored scratch). This document is the
durable record.

> Status: **complete**. All nine S units reviewed and every finding verified first-hand (2026-10-14).

---

## 1. What the S units are, and how they ran

The K units reviewed the **seams** between lanes. The S units review the code **area by area**, so that
every file Wave 2 changed is read by someone, including code no seam touches.

### Changes made before the S units started
- **A coverage check.** All 474 files Wave 2 changed were matched against the unit scopes. About 4,000
  lines of real code fell in no unit; each piece was added to the unit that owns it:
  - the platform's site-turn wiring and the research read → S5;
  - several design API files (the hardened browser, the fleet handler, the ZIP/PDF removal) and the
    migration → S3;
  - the engine's icon fixtures and the fixture builder → S6;
  - frontend build and config files, lockfiles, the dev-stack docs → S7;
  - the app's design-editor, artifacts, projects and settings changes, and the editor session route → S2b.
  - Left out on purpose: `trials/puck-spike/` (a spike for the pending R5 rich-text decision), and
    docs and memory notes.
- **S2 split in two** (S2a, the editor package; S2b, the app side), because one reviewer would have had
  about 5,000 lines of non-test code.
- **Stricter rules for the reviewers** (written into the review folder's `REVIEWER.md`):
  - no cap on the number of findings;
  - a coverage table showing every file in scope was read;
  - a verdict on every lane ruling, every "review focus" line and every known minor in scope;
  - every Critical and Important finding proven by running something;
  - findings about privacy and verification guards listed separately (see below);
  - a list of suspicions the reviewer could not prove, so the controller can follow them up.
- **Two units at a time**, the founder's choice. Each pair had one unit that runs tests against the
  shared test database and one that does not, so their tests could not interfere.

### Founder rulings that shaped the review (2026-10-14)
- **Agent sections share one editor frame per workspace** (decision D2, 2026-10-09). Per-section
  isolation stays out. Reviewers were told not to propose it.
- **Privacy and verification guards are parked for a dedicated sprint.** Reviewers still reported such
  findings, but in a separate list (§6), not in the main one.

### How findings were verified
Exactly as for the K units: every finding was checked first-hand by the controller before it counted,
by re-running the reviewer's probe on the merged tree or reading the code on both sides.

---

## 2. Where things stand

| Unit | Area | Critical | Important | Minor |
|---|---|---|---|---|
| S1 | site-kit, the shared package | 1 | 4 | 5 |
| S2a | the site editor package: frame, editor server, build | 1 | 2 | 7 |
| S2b | the app side of site editing | 0 | 3 | 7 |
| S3 | the design API's site backend | 0 | 2 | 6 |
| S4 | page origin, hostnames, platform API | 0 | 1 | 2 |
| S5 | the site agent's runtime and the platform's site-turn wiring | 0 | 2 | 1 |
| S6 | brand capture, minting, the engine's brand tokens, the Brand page | 0 | 3 | 9 |
| S7 | deploy and infrastructure | 1 | 1 | 2 |
| S8 | the merge conflicts resolved by hand | 0 | 0 | 0 |
| **Total** | | **3** | **18** | **39** |

**60 findings** from the area review, all open. Together with the contract review's 35 open findings, the
whole Wave 2 review stands at **95 open: 6 Critical, 36 Important, 53 Minor**. (K4-2, one of the Critical,
is parked for the privacy and verification sprint.)

Two severities were raised by the controller during verification, each explained at the finding: S2a-1
(Important → Critical, to match S1-1) and S5-1 (Minor → Important, after finding a second route).

The six Critical findings across the whole review:
| Id | One line |
|---|---|
| K1-1 | An account that has a site breaks its Insights, Artifacts and Activity pages |
| K3-1 | Agent code in the editor frame can save, undo and redo as the marketer (founder choosing the fix) |
| K4-2 | A long research section reaches the page writer past the privacy filter (parked) |
| S1-1 | Moving between pages resets a cloned section to the seller's wording, and saves it |
| S2a-1 | ⌘Z in a cloned section's text rewinds the whole page and saves it |
| S7-1 | Chromium's sandbox can't start in the backend container: every backend release is blocked |

---

## 3. The findings, unit by unit

### S1 — site-kit (the package the editor, the renderer and the agent all share)

#### S1-1 — Moving between pages resets a cloned section to the seller's original wording, and the editor saves it
- **Severity:** Critical (silent loss of the agent's copy, saved to the server, in normal use). Status: open.
- **What a person sees:** a 1:1 site has a cloned "hero" on its home page and a different cloned "hero"
  on `/analysis`. The marketer, in edit mode, moves from one page to the other (or opens a second site
  while the editor stays loaded). The second page's hero goes back to the seller's own homepage
  wording, sections the agent hid reappear, and the editor saves that as if the marketer had typed it.
  If the clone has images, the save is refused instead, and then nothing on that page saves until a
  reload (the K1-4 loop).
- **Why it happens:** a cloned section has a rule that refills its text with the clone's original
  wording when the marketer swaps in a different clone. Puck runs that rule again every time it mounts a
  page, comparing each section with the **last section it saw with the same id**. That memory is shared
  across pages and sites, and ids like `hero` repeat. So the second page's hero is compared with the
  first page's hero, looks "swapped", and is refilled. Puck then reports the change as an edit, and the
  editor saves it.
- **Where:**
  - the refill rule: `site-kit/src/config.tsx:179-184`;
  - Puck 0.23's shared memory: `node_modules/@puckeditor/core/dist/chunk-ZRAERXB4.mjs:39-60` (module-wide
    `cache.lastChange[id]`), run on every mount (`chunk-55V3NZVF.mjs:13528-13532`), reported through
    `onChange` (`:13514-13524`);
  - the editor remounts Puck on every page change and every new site
    (`site-editor/src/client/editor-app.tsx:129-137`, `site-editor/src/client/frame-controller.ts:221,233,261`)
    and turns `onChange` into a save (`frame-controller.ts:184-191`);
  - image slots are refilled with bare digests (`site-kit/src/clone.ts:122-129`), which the save check
    refuses (`site-kit/src/validate.ts:172-174`).
- **How we know:** the probe drives Puck's real resolver with site-kit's real config: mounting a second
  "hero" with the agent's text returns the seller's text and three refused image values. The controller
  re-ran it and read each step through Puck's code to the save.
- **Fix direction:** don't refill on a page load. Only refill when the marketer actually swaps the clone
  (the dock does not use this path at all, so the rule may simply go), and never write image fallbacks
  into the stored text.

#### S1-2 — Clicking into a cloned headline and clicking away, without typing, flattens and saves it
- **Severity:** Important. Status: open.
- **What a person sees:** Garner's hero headline "Top Providers. / Bottom line results." is on two lines.
  The marketer clicks into it and clicks away without typing. It becomes one line, loses any bold or
  italic inside it, and the change is saved and appears in undo history.
- **Why it happens:** leaving an editable text always saves its text. The saved text never equals the
  captured original (line breaks and non-breaking spaces become plain spaces), so the section is
  rebuilt from plain text.
- **Where:** `site-kit/src/editor/clone-editor.tsx:28-43`; `site-kit/src/clone.ts:49,89-90`; the captured
  original in `lumen_api/fragments/slots.py:172`.
- **How we know:** probe re-run: the stored original and the saved text differ by one space, and the
  heading's markup is flattened.
- **Fix direction:** save only when the text actually changed since the marketer clicked in.

#### S1-3 — Text replacements in cloned sections that the check accepts are never applied
- **Severity:** Important. Status: open.
- **What a person sees:** the agent (or the marketer, in the dock) replaces a phrase in a cloned section.
  The check says it's fine, and the published page still shows the seller's words. In other cases text
  copied exactly from the catalog is refused.
- **Why it happens:** three pieces of code read the clone's text three different ways. The catalog shows
  text with HTML codes like `&amp;` still in it and line breaks collapsed; the check decodes them and
  accepts any part of a sentence; the renderer only replaces a whole text node exactly as captured. So
  a phrase that is part of a paragraph, wraps across lines, spans bold text, or contains `&` passes one
  and fails another.
- **Where:** `site-kit/src/catalog.ts:52`; `site-kit/src/validate.ts:39-40,177-183`; `site-kit/src/clone.ts:101-115`.
- **How we know:** probe re-run on a real Garner clone: the copied text is refused but would apply; the
  readable text is accepted but not applied; wrapped, partial and bold-spanning phrases are accepted
  but not applied.
- **Note:** the logic predates Wave 2; Wave 2 put it on the site agent's path.
- **Fix direction:** one shared "visible text of this element" function used by all three, and a check
  that only accepts what the renderer can actually replace.

#### S1-4 — Clearing a cloned headline shows it empty in the editor, but the published page shows the seller's headline
- **Severity:** Important. Status: open.
- **Why it happens:** an empty value is treated as "not set", so publishing falls back to the captured
  original. In the editor, the section's HTML string doesn't change, so React does not redraw it and the
  canvas keeps showing the marketer's empty line.
- **Where:** `site-kit/src/clone.ts:46`; `site-kit/src/clone-markup.tsx:10-11`; `site-kit/src/editor/clone-editor.tsx:29`.
- **How we know:** probe re-run: canvas `""`, published headline "Top Providers.".
- **Fix direction:** decide what an empty text means (probably empty, since sections have a separate
  show/hide switch), and redraw the section when a save doesn't change its HTML.

#### S1-5 — A linked card with a button inside looks right in the editor, but on the published page the button falls outside the card
- **Severity:** Important. Status: open.
- **Why it happens:** a card with a link is itself a link, and a button is also a link. Links inside links
  are not allowed in HTML: the editor (built by React) keeps the nesting, but a browser reading the
  published page's HTML closes the card early, so the button drops out of it. The section-writing skill
  invites exactly this pattern, and the section checker does not refuse it.
- **Where:** `site-kit/src/agent-kit.tsx:46-52`; `site-kit/src/sections.tsx:67-78`.
- **How we know:** probe re-run: the published DOM has the button outside the card; the editor DOM has it inside.
- **Fix direction:** draw a linked card as a box with a covering link, or have the checker refuse links
  inside a linked card and say so in the skill.

#### S1-6 — A section field with a default is treated as optional, but nothing fills the default in
- **Severity:** Minor. Status: open.
- **What happens:** a feature section written without a heading size validates, and renders its heading
  with class `undefined` (no brand font or size). An agent section's list field with a default of `[]`
  validates when missing, then crashes the whole site render.
- **Where:** `site-kit/src/schemas.ts:60`, `site-kit/src/catalog.ts:141`, `site-kit/src/sections.tsx:172`,
  `site-kit/src/render-core.tsx:63`.
- **Fix direction:** apply each section's defaults before rendering, or require every field the renderer needs.

#### S1-7 — A page with a slightly wrong shape crashes the checker; the agent gets a stack trace and the save is refused as "validator unavailable"
- **Severity:** Minor. Status: open.
- **What happens:** a common model slip (props flattened onto the section, a `null` item, content written
  as an object, a `null` shell) throws inside the checker instead of returning "content.0 has no props".
- **Where:** `site-kit/src/validate.ts:133,144-153,234`; callers `lumen_api/site_doc_validate.py:139-144`,
  `lumen_agent/site/tools.py:355-361`.
- **How we know:** probe re-run: five malformed shapes throw.
- **Fix direction:** skip items the schema already rejected, so the checker always answers with a list of errors.

#### S1-8 — Agent-section links are checked only when the field is named "…href"
- **Severity:** Minor. Status: open.
- **What happens:** a field named `ctaUrl` pointing at a page that doesn't exist publishes a broken link,
  and `ctaLink` pointing at a competitor slips past the "one main destination" rule.
- **Where:** `site-kit/src/validate.ts:220-225`.
- **Fix direction:** check every field whose value looks like a link, or require link fields to be named `…Href`.

#### S1-9 — A replacement containing `$$` or `$&` comes out mangled
- **Severity:** Minor. Status: open.
- **What happens:** "From $$5 per member — $& more" renders as "From $5 per member — Pricingamp; more",
  because `$` patterns are special in JavaScript's string replace.
- **Where:** `site-kit/src/clone.ts:108`.
- **Fix direction:** pass the replacement as a function, or slice and join.

#### S1-10 — site-kit writes three animation values into the page's CSS without re-checking them
- **Severity:** Minor (defence in depth: the engine checks them first today). Status: open.
- **Where:** `site-kit/src/brand-values.ts:254-257` passes animation values through unchecked;
  `site-kit/src/looks.ts:422` writes them into the stylesheet. Same family as K5-3 and K5-6.
- **Fix direction:** check them against the same lists the engine uses.

---

### S2a — The site editor package (Lane C): the frame, the editor server, the build

#### S2a-1 — ⌘Z inside a cloned section's text rewinds the whole page to an older copy and saves it
- **Severity:** Critical (silent overwrite of the agent's work, saved, from an ordinary keystroke).
  Status: open. **Re-graded up by the controller** from the reviewer's Important, so that it matches S1-1,
  which has the same kind of consequence.
- **What a person sees:** the agent rewrites the proof band and the new version arrives. The marketer
  clicks into the hero headline (a cloned section), fixes a word, and presses ⌘Z to take back a typo. The
  whole page jumps back to how it looked when the editor opened, the agent's rewrite included, and 600 ms
  later that old page is saved as a new version. The same happens to dock edits, image placements,
  restores and server undo. With no earlier edit, ⌘Z in that text does nothing at all.
- **Why it happens:** Puck, the editing library inside the frame, keeps its own undo history and listens
  for ⌘Z across the whole page. The frame lets the keystroke through when the cursor is in editable text
  (so the browser's own text undo can work), but Puck catches it first and blocks the browser's undo.
  Puck's history never recorded the changes that came from outside (the dock, the agent, restores), so
  its "undo" restores a page from before them. The plan said Puck's history is never the source of undo.
- **Variants:** Ctrl+Z / Ctrl+Y on Windows; on German keyboards ⌘Z runs Puck's *redo*; on Dvorak, Puck's
  undo fires even with nothing focused.
- **Where:** `site-editor/src/client/editor-app.tsx:64-71,171-173`; `site-kit/src/editor-site.ts:137-146`;
  `site-kit/src/editor/clone-editor.tsx:22,31-33`; Puck 0.23 `chunk-K2LNXU54.mjs:725-775,915-920`.
- **How we know:** the controller re-ran the four browser probes on Lane C's own test harness. ⌘Z sent
  no server undo, and the saved page had the dock edit and the agent's rewrite rolled back.
- **Fix direction:** in the frame, stop every keystroke Puck's history would react to (matched by key code
  as well as character) unless it is in one of Puck's own text fields, and give cloned text its own undo;
  or clear Puck's history whenever the page is replaced from outside.

#### S2a-2 — In Edit mode, agent-written sections receive their text settings in the wrong form and break
- **Severity:** Important (every site with an agent section, the moment Edit is turned on). Status: open.
- **What a person sees:** the marketer turns on Edit. Agent sections lose their brand background, image
  descriptions become "[object Object]", button styles fall back to the standard look, and a section that
  works with its text (for example capitalising it) disappears. Preview and the published page are fine.
  The dock also offers "surface" and "look" as free text that the save check then refuses.
- **Why it happens:** to make text editable on the canvas, the editor marks every plain text setting of
  an agent section as editable, including settings that are really choices (`surface`, styles, `alt`).
  Puck then replaces those values with editing widgets before the section draws. Built-in sections are
  written to cope with that; agent sections are not.
- **Where:** `site-editor/src/client/fields.ts:104-111`; Puck's inline transform `chunk-55V3NZVF.mjs:5239-5253`;
  `site-kit/src/sections.tsx:28-29`.
- **How we know:** browser probe re-run: in Edit the section's class is `bg-surface-[object Object]` with a
  transparent background; in Preview it is the brand colour.
- **Fix direction:** never make choice-like settings editable text; give `surface` and the style settings
  the same pick-lists the built-in sections have; hand agent sections their plain values.

#### S2a-3 — Anyone can tie up the design API's connections through any editor address, without logging in
- **Severity:** Important (security: availability of the design API, which serves every workspace).
  Status: open. Worse than a minor issue Lane C had already recorded.
- **What could happen:** a stream of anonymous "HEAD" requests for a large public image, sent to any
  editor address, leaves a design-API connection open for each one, holding the whole image.
- **Why it happens:** for a HEAD request the editor server fetches the full image from the design API,
  answers without reading it, and never closes the upstream request. No request to the design API has a
  time limit.
- **Where:** `site-editor/src/server/app.ts:125-159`; `site-editor/src/server/send.ts:13-15`.
- **How we know:** probe re-run on the real server code: after 40 HEADs of an 8 MB image, 39 design-API
  connections were still open after forcing a cleanup.
- **Fix direction:** answer HEAD with a HEAD upstream (or close the upstream body), and put a time limit
  on every upstream request.

#### S2a-4 — After a replace, the dock can jump to a section the marketer never picked
- **Severity:** Minor. Status: open. Puck keeps the selection by position, not by section, so an undo of a
  turn that added a section above shifts the dock to a different section.
- **Where:** `site-editor/src/client/frame-controller.ts:225-241`; `site-editor/src/client/editor-app.tsx:171-187`.

#### S2a-5 — Editing the header or footer redraws every section and jumps the scroll
- **Severity:** Minor. Status: open.
- **Where:** `site-editor/src/client/editor-app.tsx:107-112`; `site-editor/src/client/config.tsx:56-62`.

#### S2a-6 — Some agent text settings can't be edited by hand at all
- **Severity:** Minor. Status: open. Lists of text, optional text and choices among fixed words get no
  field on the canvas or in the dock.
- **Where:** `site-editor/src/client/fields.ts:91-122`.

#### S2a-7 — Editor-server error paths answer with a stack trace, and nothing times out
- **Severity:** Minor. Status: open. `GET //` and a broken section body give a 500 with a stack trace in the
  logs; a stalled design API leaves the canvas "Loading preview…" for up to 5 minutes.
- **Where:** `site-editor/src/server/app.ts:71,125-136,149`; `site-editor/src/server/main.ts:16-20`.

#### S2a-8 — A crash outside an agent section blanks the editor silently, and the frame stops answering
- **Severity:** Minor (the consequence is proven; the trigger, a cloned section with an empty source
  address, is not). Status: open.
- **Where:** `site-editor/src/client/main.tsx:14-16`; `site-editor/src/client/frame-controller.ts:221-222`.
- **Fix direction:** a top-level error boundary that reports the failure to the app.

#### S2a-9 — A section that fails to load shows the marketer the raw error, with its address and access token
- **Severity:** Minor (wording; the founder decides wording under K1-7). Status: open.
- **Where:** `site-editor/src/client/sections.ts:15,44`.

#### S2a-10 — Clicking an in-page link in Preview adds a useless step to the browser's Back history
- **Severity:** Minor. Status: open.
- **Where:** `site-editor/src/client/dom.ts:26-29`.

---

### S2b — The app side of site editing (Lane C, plus Lane A's Share menu)

#### S2b-1 — An image upload that finishes after a tab switch lands on the other account's site
- **Severity:** Important. Status: open.
- **What a person sees:** on Initech's site the marketer uploads a large photo for the hero, and switches
  to Umbrella's tab while it uploads. The photo is placed in Umbrella's hero and saved as Umbrella's next
  version. Initech never gets it. If Umbrella has no section with that name, the upload is lost silently.
- **Why it happens:** when the upload finishes, it is placed into whichever site is open by then. Picking
  from the library and AI generation check that the site hasn't changed; uploads don't.
- **Where:** `features/site-editor/hooks/use-site-images.ts:136-160,179-187`.
- **How we know:** probe re-run on the real editing hook with two sites.
- **Fix direction:** remember which site the upload started on and refuse to place it on another.

#### S2b-2 — On dev stacks, site saves, undo, redo and restore silently do nothing
- **Severity:** Important (every dev stack, so every live walk; production unaffected today). Status: open.
- **What a person sees:** on `next dev` (trenton's 3029 and every lane stack) the marketer edits the site.
  The canvas and dock show the edit, nothing is sent, no error appears, and Undo stays greyed out. A
  reload shows the old site.
- **Why it happens:** in development Next.js turns on React's StrictMode by default, which mounts each
  component, unmounts it and mounts it again. The site's save queue is shut down on that first unmount
  and never recreated.
- **Where:** `features/site-editor/hooks/use-site-saves.ts:48-61`; Next's default in
  `node_modules/next/dist/build/define-env.js:143` (the app's `next.config.ts` sets no `reactStrictMode`).
- **How we know:** probe re-run: with StrictMode on, zero saves reach the server.
- **Why this matters now:** any live check of site editing on a dev stack will look broken until this is
  fixed.
- **Fix direction:** create and shut down the save queue in the same effect; add a StrictMode test.

#### S2b-3 — A reload that is older than the marketer's last save is treated as current
- **Severity:** Important. Status: open.
- **What a person sees:**
  - the marketer types, then presses the URL bar's Reload; or returns to the site's tab from another tab;
  - their next dock or image edit quietly undoes the text they had just saved, on the server, with no
    message; or the next edit is refused "Document moved on — reloaded" and lost.
- **Why it happens:** every load is adopted as the truth, even one read before the marketer's latest save
  finished. Returning to a tab first shows the copy from when the site was last open.
- **Where:** `features/site-editor/hooks/use-site-editing-session.ts:101-115`;
  `features/site-editor/hooks/site-save-controller.ts:65-68`; `features/site-editor/hooks/use-site-document.ts`.
- **How we know:** probes re-run for both orderings and the tab return.
- **Relation:** the same root cause as K3-3, reached from the chat page too.
- **Fix direction:** never adopt a load older than what the editor has already written; forget the old
  copy when the marketer leaves the site.

#### S2b-4 — Two quick ⌘Z presses during a save count as one, and an undo can run after a later edit
- **Severity:** Minor. Status: open.
- **Where:** `features/site-editor/hooks/site-save-controller.ts:104-111,163-177`.
- **Fix direction:** run queued saves and history steps in the order they were asked.

#### S2b-5 — An AI image edit left un-accepted silently blocks every other image edit, on every site
- **Severity:** Minor. Status: open.
- **Where:** `features/site-editor/hooks/site-images.logic.ts:115`.
- **Fix direction:** keep pending edits per site and field, or say why a request was ignored.

#### S2b-6 — ⌘Z anywhere on the chat page undoes the open site, even when the site is not on screen
- **Severity:** Minor (the web and ad lanes behave the same way). Status: open.
- **Where:** `features/site-editor/hooks/use-site-editing-session.ts:367-385`.
- **Fix direction:** handle undo keys only while the site is shown, for all three lanes together.

#### S2b-7 — A failed read of the editor's address is never retried; every site shows "Preview failed" until a full reload
- **Severity:** Minor. Status: open.
- **Where:** `features/site-editor/hooks/use-site-editor-origin.ts:24-39`.

#### S2b-8 — The brand is read once per site per tab, so a retired clone brought back by undo shows as "Choose a cloned section"
- **Severity:** Minor. Status: open. (Fixing K1-3 alone won't make an old version display correctly.)
- **Where:** `features/site-editor/hooks/use-site-document.ts:41-43`.

#### S2b-9 — Nothing stops the editor domain being set to the app's own domain
- **Severity:** Minor (configuration). Status: open. That setting would quietly undo the separation D2 relies on. Sibling of K3-8.
- **Where:** `features/site-editor/server/site-editor-session-handler.ts:30-35`; `site-kit/src/editor-origin.ts:18-23`.

#### S2b-10 — Two contract docs lag the code
- **Severity:** Minor (docs). Status: open. `apps/frontend/docs/api-contracts/artifacts.md` and
  `apps/frontend/docs/architecture/site-editor.md`.

---

### S3 — The design API's site backend (Lane A)

#### S3-1 — Agent section code can rewrite what the render page reports: it gets past the size limit and can choose the error the marketer sees
- **Severity:** Important (security and availability). Status: open.
- **What could happen:**
  - a section returns a page far larger than the limit: 5 MB came back against a 1 MB cap in the probe,
    and 80 MB pushed the design API process to about 1.85 GB of memory for one render;
  - a site that renders fine is refused on Publish with a message the section wrote, for example "Your
    Clue session expired. Sign in again at https://…", shown to the marketer as is.
- **Why it happens:** the section's own code runs in the render page before the page sends back its
  answer, and it can replace a built-in function the page uses to send it. The design API trusts the size
  and the error the page reports.
- **Where:** `site-kit/src/render-browser.tsx:42,64-69`; `lumen_api/site_render.py:340-348`.
- **How we know:** the controller re-ran both probes (the oversized answer and the forged error).
- **Relation:** same root cause as K5-5 (values computed where agent code runs are trusted).
- **Fix direction:** the design API measures what it actually received, ignores error codes the page did
  not produce itself, and the page captures the built-ins it needs before any section loads.

#### S3-2 — One agent section can stall publishing, the gallery thumbnail and the agent's screenshots for minutes
- **Severity:** Important (availability). Status: open.
- **Why it happens:** the page cleaner restarts from the top of the page after every element it removes,
  so its time grows with the square of the page.
- **Where:** `lumen_api/site_sanitize.py:115-125`, used by publish, the thumbnail and the agent's render tool.
- **How we know:** the controller timed it: 0.35 s, 4.2 s, 16.9 s as the page doubled; the reviewer
  measured 76 s for a 0.79 MB page from an agent section. Lane A's earlier ruling that the cleaner was
  fast enough was timed on small pages only.
- **Fix direction:** collect everything to remove in one pass, then remove it.

#### S3-3 — After a save, the server reports the document's newest version, not the one that save made
- **Severity:** Minor (a narrow timing window, but the loss is silent). Status: open.
- **What could happen:** the marketer's save lands, another tab's rename lands a moment later, and the
  editor is told the rename's version is its own. Its next save then overwrites the rename.
- **Where:** `lumen_api/main.py:4591-4593` (`_site_document_ref` re-reads the row). The agent's save
  already avoids this.
- **How we know:** probe re-run on the test database: the rename was lost.
- **Fix direction:** answer with the version the write itself produced.

#### S3-4 — If the brand kit can't be read, a site saves and publishes with no brand instead of being refused
- **Severity:** Minor (rare trigger, silent result). Status: open.
- **Why it happens:** the brand loader catches every error and returns an empty brand, so Lane A's
  typed refusals can never fire in production.
- **Where:** `lumen_api/site_workspace_view.py:262-278`; `lumen_api/main.py:12360-12392`.
- **How we know:** probe re-run: the same site with an empty brand renders with no brand colours, no
  fonts and no logo, and passes every check.
- **Fix direction:** refuse when a site's pinned brand kit cannot be read.

#### S3-5 — The publish cleaner keeps image paths with a hidden tab or line break, which a browser loads from another site
- **Severity:** Minor (the published page's security policy still blocks them). Status: open.
- **Where:** `lumen_api/site_sanitize.py:57-65`; `lumen_api/fragments/refs.py:105-116`.

#### S3-6 — A site whose render times out costs about 20 seconds on every gallery view
- **Severity:** Minor. Status: open. Failures are never remembered, so each view tries again.
- **Where:** `lumen_api/main.py:3963-4140`.

#### S3-7 — A malformed section link gets a server error (500) instead of a refusal (403)
- **Severity:** Minor. Status: open.
- **Where:** `lumen_api/site_section_links.py:85-91`.

#### S3-8 — A "dormant" cloned section blocks publishing with "Approve your brand kit", which can't fix it
- **Severity:** Minor. Status: open.
- **Where:** `lumen_api/site_publish.py:63,73-75,108-110`.

---

### S4 — Page origin, hostnames and the platform API

#### S4-1 — During the move to a new pages domain, one workspace can receive another workspace's published links
- **Severity:** Important (a cross-workspace takeover of links customers have already sent to prospects).
  Status: open. Nothing has moved yet, so no one is affected today.
- **What could happen:** while the operator is between steps 3 and 4 of the domain-move runbook, which says
  each step is safe to stop after:
  - **By accident:** a new customer signs up as "Acme" and is given `acme.<new domain>`, because only the new
    domain is checked. A prospect clicks the real Acme's old email link; the edge redirects it to
    `acme.<new domain>`, and the page served is the newcomer's page, or the newcomer's fallback address. The
    move's step 4 then refuses to run at all.
  - **On purpose:** any admin whose own label is not yet locked can rename their workspace's label, in
    Settings → Pages, to a published workspace's label, and from then on receive all of that workspace's old
    links, showing whatever they like.
  - **After the move:** a process still on the old domain can hand the freed old label to a new workspace,
    whose own links then redirect to the workspace that moved.
- **Why it happens:** a label is unique only together with its domain (`acme.old` and `acme.new` can belong to
  different workspaces), while the edge's redirect goes by label alone.
- **Where:** `libs/clue-spine/clue_spine/hostnames.py:268-276,358-403,571-601`; `platform/api/clue_api/frontend_read/settings_pages.py:283-297`;
  `infra/cloudflare/pages-edge/routing.js:19-24`; `docs/specs/pages-hosting-runbook.md:451-474`; the
  `workspace_hostname` table has no uniqueness on the label.
- **How we know:** the controller re-ran the probe (real workspace creation, label change, move, edge
  decision and page origin, in a rolled-back transaction): all three sequences reproduce.
- **Relation:** the same window as K3-6 (pages down), but a different failure, and K3-6's suggested fix does
  not prevent it.
- **Fix direction:** make a workspace's label unique whatever the domain, so the bad state cannot exist; or
  pause signups and label changes from step 2 until every service runs the new domain.

#### S4-2 — A person can run the site's undo and redo through the platform's tool endpoint, skipping the agent-run lock
- **Severity:** Minor (needs a deliberate direct API call; the app never makes it). Status: open.
- **What could happen:** a workspace operator calls `POST /tools/design_undo_site` while the agent is working
  on that site. The undo lands, the version moves under the agent, and the agent's whole request is thrown
  away at its save (the same result as K1-5, by a different route). Writing and publishing a site are
  reachable the same way but fail with a server error today. Also latent: the write tool takes "who is
  writing" from the request, and an "agent" writer may change agent sections.
- **Why it happens:** the platform registers every design tool, and "not granted" only binds agents, not
  people. The agent-run lock lives in the design API's own routes, not in the tools.
- **Where:** `platform/api/clue_api/projections_app.py:597-598,652`; `platform/api/clue_api/toolbelt_wiring.py:3172`;
  `platform/api/clue_api/design_tools.py:65-81,131-134`; `lumen_api/toolbelt/site_documents.py:112,184,227-231,267-281`.
- **How we know:** probe re-run through the real platform route: undo and redo both succeeded while a run was
  live, and the lock was never consulted.
- **Fix direction:** refuse people on `design_*` tools at the platform's tool route, or move the run lock into
  the tools themselves; never trust "who is writing" from the request.

#### S4-3 — The domain-move script can report "all moved" while one row stayed behind
- **Severity:** Minor. Status: open. If a label changes between the script's read and its update, that row
  isn't moved, yet the script reports the full count and "applied". Only a startup warning catches it later.
- **Where:** `libs/clue-spine/clue_spine/hostnames.py:386-403`; `scripts/move_system_hostnames.py:58-72`.
- **How we know:** probe re-run: "rows 2, applied" while the second workspace stayed on the old domain.
- **Fix direction:** lock the rows being moved, check each update's count, and re-check at the end.

---

### S5 — The site agent's runtime and the platform's site-turn wiring (Lane B)

#### S5-1 — Agent section code can read files from the server and put their contents on the page
- **Severity:** Important (security). Status: open. **Re-graded up by the controller** from the
  reviewer's Minor, after finding a second route during verification.
- **What could happen:** a section the agent writes, perhaps steered by text on a web page it fetched,
  pulls in a file from the server that compiles it, and its render shows the file's contents. They then
  appear in the agent's own screenshot and, if published, on the public page. Any file the design API or
  fleet worker can read is reachable if its extension is one the bundler knows (`.json`, `.txt`, `.js`,
  `.ts`, `.css` …). That could include another workspace's site files on a shared worker disk, or a
  mounted JSON credentials file. (`.env` itself is not reachable: the bundler has no loader for it.)
- **Why it happens:** the section checker only looks at import lines of the form `import … from "x"`.
  `export … from "x"` and a plain `require("x")` are not checked. The bundler then finds the file and
  copies its contents into the stored section.
- **Where:** the check `site-kit/src/check-section.ts:205`; the bundler step `site-kit/bin/compile-section.ts:47-67`;
  stored through `lumen_api/site_turn_ports.py:214,233`.
- **How we know:**
  - the reviewer showed `export { x } from "<file>.json"` is accepted and the file's value is copied in,
    while every `import … from` form, `/// <reference>` and `import()` are refused;
  - the controller then showed `require("<file>.json")` is accepted too, and the section's `render()`
    returns the file's secret value as page text (probes `controller_require_render.mts` and
    `controller_dynamic_import_require.mts` in the S5 probe folder).
- **Relation:** decision D2 says server-side agent code runs only in a locked container; the compile step
  runs in the design API / worker process with its full filesystem.
- **Fix direction:** check every import, export and `require` from the parsed code (as the other checks
  already do) and refuse anything outside the allowed list; and limit the bundler so it cannot resolve
  files outside the section's own folder.

#### S5-2 — A note drawn on one account's site is applied to every sibling site the turn addresses
- **Severity:** Important (a wrong-account edit on a page published under that account's name). Status: open.
- **What a person sees:** in a design leg holding several 1:1 account sites, the marketer opens Initech's
  site, clicks its hero and notes "shorter headline", then sends. If the turn addresses more than one
  site, Umbrella's hero gets "shorter headline" too, because every addressed site receives the note.
- **Why it happens:** a note's target is written as a page and section name (`site:/#hero`), and sites
  built from the same template share those names. The platform hands the message's notes to every
  addressed site's run unfiltered. On web pages this cannot happen, because each element id is unique to
  its document.
- **When it triggers:** a leg's first turn addresses all its sites; later turns address all of them
  unless the exit judge picks a subset.
- **Where:** `clue_api/design_leg_wiring.py:1456-1465` (addressing), `:2362-2373` (the same notes go to every
  run), `:2669-2678` (the site run takes every note); the runtime applies them by name in
  `lumen_agent/site/workspace.py:485-543`.
- **How we know:** code read on every step at the review tag by the controller; the end-to-end trigger
  was not run.
- **Fix direction:** send a note only to the document it was drawn on.

#### S5-3 — When the site checker cannot run, the agent is told its page is broken
- **Severity:** Minor (only when the checker itself fails). Status: open.
- **What happens:** the agent is told "the site is invalid … fix these" over a checker crash it cannot
  fix, and after three repeats the loop guard tells it to try a different approach. The turn's own finish
  check treats the same situation as "done, let the save decide".
- **Where:** `lumen_agent/site/tools.py:354-389,443-445` against `lumen_agent/site/harness.py:232-237`.
- **How we know:** probe re-run.
- **Fix direction:** say "could not check right now", and don't count it toward the loop guard.

---

### S6 — Brand capture, minting, the engine's brand tokens and the Brand page (A9)

#### S6-1 — A section background's text colour is taken from the wrong text, so the section's words become unreadable
- **Severity:** Important. Status: open.
- **What a person sees:** a seller's site has a cream section that opens with an orange label ("WHY TEAMS
  SWITCH") above dark headings and body, or a navy section whose first words sit in a white quote card. On
  every site made from that brand, all text on those backgrounds is drawn in the orange (contrast 1.78:1,
  hard to read) or the card's dark grey on navy (1.03:1, invisible). This happens in the editor and on the
  published page.
- **Why it happens:** when capturing a section, the capture takes the colour of the **first** text it
  finds, wherever that text sits. The kit stores it as "the colour of text on this background", and
  site-kit uses that pairing without checking it can be read. The engine only warns.
- **Where:** `lumen_ingestion/capture/geometry.py:327-335,377`; `lumen_ingestion/normalizer/__init__.py:153-154,360-381`;
  `crates/lumen-core/src/brand.rs:4949-4958`; `site-kit/src/surfaces.ts:51-58`; `site-kit/src/theme.ts:160-171`.
- **How we know:** the controller re-ran the capture probe (both browsers), the band-to-kit probe and the
  site-kit probe: contrast 1.78 and 1.03, and the navy band is labelled "Tinted band", not dark.
- **Fix direction:** measure a section's text colour from text that sits directly on that background
  (skipping cards with their own background), weighted toward headings and body text; keep the pairing
  only if it is readable, otherwise pick a readable colour.

#### S6-2 — A button icon that the seller's CSS sizes or colours never shows on our sites
- **Severity:** Important. Status: open.
- **What a person sees:** the seller's buttons carry an arrow icon sized by CSS classes (the common
  Tailwind/Heroicons and Font Awesome pattern). The Brand page shows the arrow, so the marketer believes
  the brand's buttons have it; on every site the icon is missing (drawn 0×0). An icon coloured by a CSS
  class appears on the Brand page as a black blob instead of a white arrow.
- **Why it happens:** the capture copies the icon's markup, which holds none of the size or stroke the
  CSS gave it. Site-kit draws the markup without a size.
- **Where:** `lumen_ingestion/capture/states.py:155-173`; `lumen_ingestion/capture/motion.py:149-193`;
  `lumen_ingestion/normalizer/component_tokens.py:493-495`; `site-kit/src/sections.tsx:62-66`;
  `site-kit/src/theme.ts:219`; Brand page `features/brand-context/model/measured-brand.ts:276-300`.
- **How we know:** the controller re-ran the capture and icon-render probes: the CSS-sized icon renders
  at 0×0 in site-kit's real button, against 12×12 for a control icon.
- **Relation:** a new consequence of K5-6, which called site-kit ignoring icon width and height harmless.
- **Fix direction:** write the computed size and stroke onto the icon when capturing it, or have site-kit
  size the icon from the size the kit stores.

#### S6-3 — Brands whose colours are written in `oklch()` (Tailwind v4, shadcn/ui) lose their button colours
- **Severity:** Important (the root predates Wave 2; the merging of measured button styles is new). Status: open.
- **What a person sees:** on a Tailwind v4 or shadcn site, a blue "Book a demo" and a green "Start free"
  button become one colourless "text only" style; hover colours and section backgrounds written that way
  are lost. The agent's button styles have no colour.
- **Why it happens:** the browser reports these colours in the `oklch()` format, and the capture only
  understands hex, named, `rgb()` and `hsl()` colours.
- **Where:** `lumen_ingestion/capture/states.py:105-130`; `lumen_ingestion/capture/geometry.py:785-815`;
  `lumen_ingestion/capture/parse.py:228-341`.
- **How we know:** capture probe re-run by the controller.
- **Fix direction:** convert every colour to hex inside the page before reading it, and teach the colour
  parser the newer CSS colour formats.

#### S6-4 — Some style names on the Brand page say the wrong thing
- **Severity:** Minor (cosmetic but visible). Status: open. A value used in two places in one style is
  named after the first place, so "pressed fill" shows as `…hover.fill`, and left padding as `…padding-right`.
- **Where:** `lumen_ingestion/normalizer/component_tokens.py:306-325`. Confirmed in the committed `probe.minted` kit.

#### S6-5 — A homepage address with long tracking parameters drops every measured style
- **Severity:** Minor. Status: open. A pasted URL with UTM/`gclid` parameters over 392 characters fails a
  400-character limit, so all measured styles, states and motion are dropped, and the leftover colours
  show on the Brand page under machine names.
- **Where:** `lumen_ingestion/normalizer/component_tokens.py:635-661`; `lumen_ingestion/measured_components.py:28,73,93`.
- **Fix direction:** strip the query and fragment from the stored source address.

#### S6-6 — A cookie banner makes the capture read the wrong element's animation
- **Severity:** Minor. Status: open. Removing the banner shifts element positions between the "before" and
  "after" reads, so a real fade-in is lost and a false "scripted animation in the footer" note appears.
- **Where:** `lumen_ingestion/capture/states.py:230-276,438-460`; `lumen_ingestion/capture/rendered.py:347-352`.

#### S6-7 — A fully transparent button background is called "Filled"
- **Severity:** Minor. Status: open. Also breaks the agreed rule that a main call-to-action needs a visible fill.
- **Where:** `lumen_ingestion/capture/geometry.py:243,806-813`.

#### S6-8 — Buttons inside web components or iframes are not measured at all
- **Severity:** Minor (missing, not wrong). Status: open.
- **Where:** `lumen_ingestion/capture/geometry.py:276-296`.

#### S6-9 — An element with two animations keeps only the first; animations named with quotes are never matched
- **Severity:** Minor. Status: open.
- **Where:** `lumen_ingestion/capture/geometry.py:1101-1111`; `lumen_ingestion/capture/motion.py:96`.

#### S6-10 — Some sprite icons are drawn at half size in the corner
- **Severity:** Minor. Status: open.
- **Where:** `lumen_ingestion/capture/states.py:155-173`.

#### S6-11 — Large stylesheets make one ingestion step slow (up to about 3 minutes)
- **Severity:** Minor (performance). Status: open. Each stylesheet is re-read once per animation name; the
  controller measured 5 s for 1 MB of CSS, 24 s for 4 MB and 92 s for 16 MB.
- **Where:** `lumen_ingestion/capture/motion.py:103-114`.
- **Fix direction:** read each stylesheet once.

#### S6-12 — A malicious page can make its own brand ingestion fail outright
- **Severity:** Minor. Status: open. A few odd number spellings pass the Python check but fail the
  engine's, and one such value fails the whole kit instead of dropping one animation.
- **Where:** `lumen_ingestion/normalizer/component_tokens.py:512-518` against `crates/lumen-core/src/brand.rs:1677-1683`.

---

### S7 — Deploy and infrastructure

#### S7-1 — Chromium's sandbox cannot start inside the backend container: every backend release is blocked, and a release that got through would draw no site
- **Severity:** Critical (blocks every backend release, hotfixes included; once deployed, the whole site
  flow is broken for everyone). Status: open.
- **What would happen:**
  - When Wave 2 reaches `main`, the image pipeline runs its smoke checks. One check launches Chromium with
    its own sandbox turned on. Under Docker's standard security profile (what CI and the VM workers use)
    that launch dies with "No usable sandbox!". The check fails, so the production tags never move and no
    backend service redeploys, not even for an unrelated hotfix. The frontend, editor and page origin build
    from `main` on Railway anyway and would run against the old backends.
  - If someone removes the check to get a release out, production runs the shipped default (sandbox on).
    Every hardened render then fails: the agent's previews and screenshots, recording an agent section,
    publishing, thumbnails. No site could be built or published.
- **Why nobody saw it:** on Macs Chromium sandboxes natively, so every lane's dev stack worked. The image
  build that would have run this check was recorded as owed.
- **Where:** the check `docker/backend/smoke.sh:37` (its suggested remedy, "set the variable to 0", cannot
  help, because the check ignores the variable); the release order `.github/workflows/deploy-images.yml:72-78`;
  the default `lumen_api/hardened_browser.py:59`; `.env.example:766` (`LUMEN_SITE_RENDER_CHROMIUM_SANDBOX=1`);
  `deploy/vm/compose.yaml` (no security profile); `deploy/check_prod_env.py` (doesn't know the setting).
- **How we know:** the controller re-ran the smoke check's exact launch in an existing backend image built
  with the same Chromium recipe: without the sandbox it starts; with it, "No usable sandbox!". The reviewer
  also showed the real hardened page fails with the setting at 1 or unset and renders at 0. Railway's own
  runtime is untested.
- **Fix direction:** decide the container posture first (a security profile that allows Chromium's
  sandbox on the VM and Railway, or ship the setting at 0 for containers); then make the smoke check test
  exactly what the services run, and have the production check refuse a value the hosts cannot honour.

#### S7-2 — A production frontend missing the editor's domain setting breaks every site silently, and no deploy step notices
- **Severity:** Important. Status: open.
- **What would happen:** whoever deploys follows the deploy runbook, which never mentions the editor
  service or the frontend's `CLUE_SITE_EDITOR_SUFFIX`. Every marketer opening a site then sees "The website
  editor is not configured". Related mistakes give no message at all: a suffix the editor service doesn't
  serve, a wrong app address on the editor service, or missing wildcard DNS leave the canvas on its
  loading veil forever, because there is no "editor didn't answer" timeout.
- **Where:** `apps/frontend/src/auth/config.ts:67-69`; `features/site-editor/server/site-editor-session-handler.ts:20-21`;
  `features/site-editor/model/site-canvas-state.ts:27-34`; `deploy/check_prod_env.py:13` (no frontend or editor
  role); `docs/deploy/runbook.md` §2 (no editor service, no suffix, no DNS/certificate step).
- **How we know:** the controller re-ran the probe (four cases) and the production check.
- **Fix direction:** add the editor service and the suffix to the runbook; add frontend and editor roles to
  the production check (same suffix and app address on both); log or refuse at start-up when the suffix is
  empty in production; give the canvas a timeout that says the editor did not answer.

#### S7-3 — With a pages domain like `pages.clue.co.uk`, customers' custom domains under `.co.uk` would stop being served
- **Severity:** Minor (depends on a domain choice not made yet). Status: open.
- **Why:** the edge Worker guesses "our zone" as the last two labels (`co.uk`), while the platform uses the
  Public Suffix List (`clue.co.uk`). A customer domain like `abm.acme.co.uk`, which the platform lets them
  connect, is then treated as our own record and not forwarded.
- **Where:** `infra/cloudflare/pages-edge/routing.js:4,26-28` against `libs/clue-spine/clue_spine/hostnames.py:174-182`.
- **Fix direction:** give the Worker its zone explicitly, or refuse a pages domain on a multi-label suffix.

#### S7-4 — The section-link secret check accepts a placeholder reference and a one-character value
- **Severity:** Minor. Status: open.
- **What would happen:** the Railway env files carry `${{shared.CLUE_SITE_SECTION_LINK_SECRET}}`; if the
  shared value was never created (the runbook doesn't name it), the check passes, the design API boots,
  and every agent section fails to load in the editor, silently.
- **Where:** `deploy/check_prod_env.py:105-112,131-138`; the secret is read only when used (`lumen_api/main.py:875-877`).
- **How we know:** check re-run by the controller: the reference and `x` are accepted.
- **Fix direction:** name the secret in the runbook; refuse to start in production without it; require a
  minimum length.

---

### S8 — The merge conflicts resolved by hand

**No findings.** This unit checked the only code written by hand during the merges.
- **All 11 merges between the base and the review tag are accounted for.** The 7 that had no conflicts
  contain nothing written by hand: their "remerge diff" is empty, which the controller re-checked. The 4
  resolved by hand (`c9a3c18d8`, `dda6790cc`, `d46b38a91`, `1371a4810`) contain only their conflict
  sections, plus two test-only edits in `dda6790cc`. Both edits are correct, and their tests pass.
- **Every resolution keeps both lanes' intent:** the site-kit exports, the app's TypeScript settings, the
  two locks in the chat surface and the standalone editor, the design API's imports and test seam, the
  tool-count tests (150 tools, 175 addresses, 62 design tools) and the governance list.
- **The standalone editor's publish lock** (the hand-resolved part of `d46b38a91`) was proven with a probe
  over the exact resolved lines. A site's publish lock follows its site lock with one read per poll, a web
  page gets its own read, an ad gets no publish lock, and no lock is carried over when switching tabs. The
  controller re-ran it: 7 of 7 cases pass.
- **No later change on either lane breaks a resolution.** The one changed function signature that crossed
  lanes (`inline_asset_store_refs(cache=)`) was already fixed during the merge (`639475541`).
- **For the fix pass:**
  - a sweep of stale comments the resolutions left (in `chat-surface.tsx`, the count tests,
    `lumen_api/main.py:4689` and `documentStore.ts`);
  - two now-unused imports at `lumen_api/main.py:133`;
  - no automated test publishes a site through the real route with the real composed loaders, so the
    live walk must cover publishing.

---

## 4. Analysis: what the findings have in common

The K and S units together found **95 open findings** (35 from the contract review, 60
from this one). Read one by one they look scattered. Grouped by cause, they come down to seven
problems. Each group below names the findings in it, the shared cause, and the one change that would
close most of it.

### 4.1 The editor keeps its own hidden copy of the site, and that copy overwrites the real one
**Findings:** S1-1 (Critical), S2a-1 (Critical), K1-4, K3-3, K3-5, S2b-3, S2b-4, S3-3, S2a-4.

There are three copies of a site while it is being edited: the server's, the app's, and the one inside
the editor frame, which Puck (the editing library) holds. They are kept in step only by comparing version
numbers. Puck also keeps state of its own that nobody accounted for:
- its own undo history (S2a-1);
- a memory of each section's last data, shared across pages (S1-1);
- its own idea of which section is selected (S2a-4).

Whenever that hidden state or a stale copy wins, the editor saves it over the real site, silently. This is
the group that loses people's work, which makes it the top priority.

**The shared fix:**
- one rule for syncing: the frame always shows exactly the app's copy, tracked by a counter that changes
  on every push, not only on a new version;
- the app adopts a server read only if it is newer than what it has already written;
- every write reports the version it produced, never a re-read;
- Puck's own undo history, its keyboard shortcuts and its "refill on load" behaviour are switched off in
  the frame.

### 4.2 Untrusted input is trusted: agent code, anonymous requests, and a tool route
**Findings:** K3-1 (Critical; founder deciding), S5-1, S3-1, K5-5, K3-2, S3-2, K2-2, S1-8, S2a-3 (an
anonymous outside request), S4-2 (a person reaching agent-only tools, past the run lock).

Decision D2 runs agent sections in one shared editor frame and, on the server, in a hardened browser
page. That is sound. But several places then trust what came out of that code, or check the code by
pattern-matching its text instead of parsing it:
- the render page's own report of its size and errors (S3-1);
- the theme text it builds (K5-5);
- the messages the frame sends (K3-1);
- the import check, which reads text patterns and so misses `require` and `export … from` (S5-1);
- the class and link checks, which match on names (K2-2, S1-8).

**The shared fix:**
- treat everything computed where agent code runs as untrusted: measure and re-check it on the server;
- check section code from its parsed structure, not its text;
- run the compile step so it cannot reach files outside the section's folder.

For K3-1, the founder is choosing a simple fix that fits D2.

### 4.3 What the marketer sees in the editor is not what gets published
**Findings:** K5-2, K2-1, K1-2, S1-4, S1-5, S2a-2, S2b-8, S6-2.

The editor draws a site with React inside Puck and compiles its CSS once, when the editor is built. Publishing
draws static HTML and compiles CSS over that page. Each difference between the two paths shows up as
"looks right here, wrong there":
- missing spacing (K5-2);
- missing library functions (K2-1);
- section ids (K1-2);
- cleared text (S1-4);
- nested links (S1-5);
- Edit-mode settings (S2a-2);
- a cached brand (S2b-8);
- icon sizes (S6-2).

**The shared fix:** one test that takes a real fixture site, renders it both ways, and compares the
results: classes resolved, styles computed, elements present. Each of these bugs would have failed it.

### 4.4 State that belongs to one account's site leaks into another's
**Findings:** K6-1, S2b-1, S5-2, K3-4, S2b-5, S2b-6.

Wave 2's normal shape is one site per account, open side by side. Several pieces of state are kept in
shared places with no document key, or are checked against "whatever is open now" when an async step
finishes:
- the Share menu (K6-1);
- image uploads (S2b-1);
- notes on sections (S5-2);
- the editor address after a workspace switch (K3-4);
- pending AI image edits (S2b-5);
- keyboard undo (S2b-6).

The result is a wrong-account page: a link with another account's name, another account's photo or edit.

**The shared fix:** key every per-document piece of state by the document's id, and check that id again
when an async step completes.

### 4.5 Wave 2 cannot be deployed as it stands
**Findings:** S7-1 (Critical), S4-1, S7-2, S7-4, K3-6, K3-7, K3-8, S7-3, S4-3, S2b-9, and S2b-2 (dev stacks).

- The backend release is blocked outright by the Chromium sandbox check (S7-1).
- Several settings that the new services need are neither documented in the deploy runbook nor checked
  (S7-2, S7-4).
- The domain-move runbook has a window where pages are down (K3-6), and in the same window one workspace
  can take over another's published links (S4-1). Neither move should run until both are fixed; the move
  script can also report success while leaving a row behind (S4-3).
- On every dev stack, site edits don't save (S2b-2), so any live walk of site editing will fail until that
  is fixed.

**This group gates everything else:** S7-1 must be decided before Wave 2 can reach `main`, and S2b-2 before
any live walk.

### 4.6 Brand capture misses common modern patterns
**Findings:** S6-1, S6-2, S6-3, and S6-4 to S6-12.

The capture works on the patterns it was tested with. It misses common ones:
- section text colour taken from an eyebrow line or card (S6-1);
- icons sized by CSS classes (S6-2);
- colours written in `oklch()` (S6-3);
- web components, multiple animations, long URLs.

These degrade every site built from such a brand, quietly.

**The shared fix:** read computed values (colour in hex, icon size and stroke) in the page, and add
fixtures for these common patterns.

### 4.7 Errors are either raw or misleading
**Findings:** K1-7, S2a-9, S3-8, S5-3, K4-7, S2b-7, S2a-7, S3-7.

Several failures reach people as raw machine text (agent-facing errors, import errors with tokens, stack
traces), as the wrong advice ("approve your brand kit"), or not at all ("no research yet"). The wording is
the founder's (K1-7). The plumbing — a typed error with a person-facing sentence — can be built once and
reused.

---

## 5. Suggested order for the fix pass

One pass, each fix starting from a failing test, then a review of only the fix changes. Suggested order:

1. **Unblock:** S7-1 (decide the Chromium sandbox posture for containers, then make the smoke check match),
   and S2b-2 (dev-stack saves; a small fix that unblocks every live walk).
2. **Stop losing work (§4.1):** S1-1, S2a-1, then K1-4, K3-3, K3-5, S2b-3, S2b-4, S3-3, S2a-4. These share
   one sync rule, so they are best done together.
3. **K1-1** (an account with a site breaks its research pages): small and Critical.
4. **Security (§4.2):** S5-1, S3-1, K5-5, K3-2, S3-2, S2a-3, S4-2, and K3-1 once the founder picks the fix.
5. **Wrong-account state (§4.4):** K6-1, S2b-1, S5-2, K3-4, then the minors.
6. **Editor ↔ published parity (§4.3):** build the comparison test first, then K5-2, K2-1, K1-2, S1-4, S1-5,
   S2a-2, S2b-8, S6-2.
7. **Deploy and configuration (§4.5):** S7-2, S7-4, and, before the pages-domain move is run, K3-6, S4-1
   and S4-3; then the configuration minors.
8. **Brand capture (§4.6):** S6-1, S6-3, then the capture minors.
9. **Everything else:** the remaining Important findings (K1-3, K1-5, K4-1, K4-3, K4-5, K6-2, K6-3, S1-2,
   S1-3), the minors, and the stale-comment sweep from S8.

Founder decisions needed before or during the pass:
- **K3-1:** which simple fix;
- **K1-7:** the wording of error lines (it also covers S2a-9 and S3-8);
- **K6-4:** phone navigation for multi-page sites;
- **S7-1:** the container sandbox posture, if it needs a product call.

After the pass, the **behavioural check** runs on trenton's stack:
- the lanes' scenario tests together;
- the live walk with a real site, which must include publishing through the real route (S8 found no
  automated test that does);
- editing several account sites side by side.

---

## 6. For the privacy and verification sprint (parked, founder 2026-10-14)

- **K4-2** (from the contract review): a long research section reaches the page writer raw, past the held-claim
  filter.
- **S5's note:** the held-claim filter works claim by claim, so an ordinary statement inside a "Watch-outs" or
  "Context only" section reaches the agent marked "background only" and is kept off the page by the
  prompt alone. That belongs in the sprint's threat model.

No other S unit found anything in this class.

---

## 7. Suspicions not proven (for follow-up)

Reviewers listed things they suspected but could not prove. These are not findings. The ones worth a
follow-up:

| From | Suspicion | What would prove it |
|---|---|---|
| S2b | A forged "selected" message with a huge field list could freeze the app tab. None of the simple K3-1 fixes would stop it. | A browser probe posting such a message, timing the app. |
| S2b | A note sent right after a canvas edit may be refused for "document no longer at this version". | Drive the chat submit with a save in flight. |
| S3 | Many cold site thumbnails could starve the design API's request threads. | A load test: about 40 cold thumbnail requests while saving. |
| S3 / S7 | Section-link tokens ride in URLs and are probably written to the design API's access log. | Read one design-API log line. |
| S7 | The backend image now carries the whole frontend `node_modules` (about 821 MB). | Build in CI and compare image size and disk. |
| S7 | One package (site-kit) ships on three deploy schedules; a protocol change could be dropped silently between versions. | Deploy a protocol change and watch an old tab. |
| S2a | Each agent section loads a full Tailwind stylesheet that stays in the warm frame and can restyle later sites. | Open two sites in turn and compare computed padding. |
| S2a | `/asset-store` on the editor domain would host any public HTML blob as a page. | List stored media types; add a sandbox header for non-images. |
| S6 | A carousel that clones marked elements, or a hover mega-menu, may break the state capture. | A fixture for each. |
| S8 | The site turn's screenshot cache remembers a missing image for the rest of the turn. | Render, write the image, render again in one turn. |
