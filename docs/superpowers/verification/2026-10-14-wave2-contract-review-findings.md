# Wave 2 review: the contract (K) findings, explained

**Date:** 2026-10-14 (reviews run 2026-10-13).
**Branch:** `puck/integration-wave1` (trenton), where all four Wave 2 lanes are merged.
**Code reviewed:** everything Wave 2 changed between the common base `8c1aa9e47` and the review tag:
`w2/review-base` (`7ee87b9fe`) for K1–K5, and `w2/review-base-2` (`94e49530d`, which adds A9's fix wave) for K6.
**Raw material:** each reviewer's full report and probe scripts are in
`.superpowers/review/2026-10-13-wave2/reports/` (git-ignored scratch). This document is the durable,
committed record of what they found and what was verified.

---

## 1. What this review is, and how to read this document

### The work under review
Wave 2 of the website agent on Puck was built in four lanes, in parallel worktrees:

| Lane | What it built |
|---|---|
| **A** | The site backend and publishing: storing and checking site documents, rendering and cleaning pages, the page origin that serves published pages, hostnames and custom domains |
| **A9** | Brand fidelity: capturing a brand's look, minting the brand kit, the brand tokens the engine and site-kit read, the Brand page |
| **B** | The site agent on the platform: the agent that writes sections and pages in a "site turn", reading the account's research |
| **C** | The site editor: a separate editor domain, the frame the canvas runs in, the dock, undo and versions, pages, the publishing UI |

Each lane reviewed its own work task by task. Nobody had looked across the **seams**: the places where
one lane's code depends on what another lane's code sends or expects. The master plan
(`docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md`, lines 256–437) wrote those
seams down as nine "contracts".

### The two review families
- **K units review the seams.** Each takes one or two contracts and reads both sides. ("K" for contract,
  because "C" already names Lane C.) Six units, K1–K6. All six are done; this document covers them.
- **S units review one area of code each** (site-kit, the editor, the design API, the page origin, the
  agent runtime, brand capture, deploy, the merge conflicts). Eight units, S1–S8. They come next.

### How the review was run
- Each unit was given to a fresh reviewer agent (Opus) that only **finds** problems and fixes nothing.
  Reviewers could run probe scripts and tests, but only against the test database with every API key
  blanked, so nothing spent money or touched the live dev data.
- **Every finding was checked first-hand by the controller before it counted:** the probe re-run, or the
  code read on both sides of the seam. Two findings were re-graded (K4-2 up to Critical; K2-2 narrowed),
  and one turned out to be a duplicate (K4-4 is K3-3).
- A finding id like **K3-1** means unit K3, finding number 1.

### Severity
- **Critical:** data loss, a security hole, or a core flow broken for everyone.
- **Important:** a real person hits it in normal use, or a seam mismatch that will bite.
- **Minor:** rare or cosmetic, but real.

### Path shorthand used below
| Short | Full path |
|---|---|
| `lumen_api/` | `subsystems/clue-design/apps/api/lumen_api/` |
| `lumen_agent/` | `subsystems/clue-design/apps/agent_runtime/lumen_agent/` |
| `clue_design/` | `subsystems/design/clue_design/` |
| `clue_api/` | `platform/api/clue_api/` |
| `site-kit/` | `apps/frontend/packages/site-kit/` |
| `site-editor/` (package) | `apps/frontend/packages/site-editor/` |
| `features/` | `apps/frontend/src/features/` |

---

## 2. Where things stand

40 finding ids in total:

| | Count | Ids |
|---|---|---|
| **Open, Critical** | 1 | K4-2 (parked, see §3) |
| **Open, Important** | 15 | K1-2, K1-3, K1-5, K2-1, K3-2, K3-4, K3-6, K4-1, K4-3, K4-5, K5-2, K5-5, K6-1, K6-2, K6-3 |
| **Open, Minor** | 14 | K1-6, K1-7, K1-8, K2-2, K3-7, K3-8, K4-6, K4-7, K4-8, K5-6, K6-4, K6-5, K6-6, K6-7 |
| **Resolved** (by A9's fix wave) | 4 | K5-1, K5-3, K5-4, K5-7 |
| **Fixed** (by the editor sync fix, 2026-10-14) | 3 | K1-4, K3-3, K3-5 |
| **Fixed** (2026-10-14, after the sync fix) | 1 | K1-1 |
| **Closed as ruled** (2026-10-14, fixes 1+2, residual accepted) | 1 | K3-1 |
| **Duplicate** | 1 | K4-4 (= K3-3) |

**Update 2026-10-14:** the editor sync fix (`docs/superpowers/plans/2026-10-14-site-editor-sync-fix.md`) closed K1-4, K3-3 and K3-5, each from a failing
test; K1-1 and K3-1 (as ruled) followed the same day. **30 K findings remain open** (1 Critical — K4-2, parked — 15 Important, 14 Minor). The rest are fixed in the fix
pass that follows the S-unit review, each from a failing test, and only the fix changes are re-reviewed.
The area document's §4.1 records the sync fix as a whole.

---

## 3. Decisions taken and decisions owed

| Finding | Decision |
|---|---|
| **K3-1** (agent code in the editor frame can pose as the editor) | The isolation model was decided on 2026-10-09 (decision D2 in `docs/superpowers/specs/2026-10-08-puck-production-readiness-map.md`): agent sections run in **one** editor frame per workspace, on its own domain with no login; a sandbox per section was **rejected** ("no builder does it; the costs multiply per section"). **Founder, 2026-10-14:** that stands, no per-section isolation; take a simple fix now and harden over time. **Founder, 2026-10-14 (later): fixes 1 and 2** — undo/redo from the frame only while editing, and a fresh frame for each different site — built in `9db8f20dd`. Fix 3 not taken; the remaining forged-save-while-editing case is accepted. The same day, external links clicked in the preview open in a new tab (asked through the app, only after a real click). |
| **K4-2** (sensitive research reaching the page writer) | **Founder, 2026-10-14: parked.** Privacy and verification guards get their own dedicated sprint, after the basic layer works. K4-2 is not part of this fix pass, and live site runs on trenton may go ahead meanwhile. |
| **K1-7** (the dock shows the agent's raw error text) | Wording is a founder/design call. Owed. |
| **K6-4** (no page navigation on phones) | Needs a design ruling. Owed. |
| **K6-3** (account sites indexable by default) | No new decision needed: founder ruling R25-4 ("ABM account pages must never be indexed") already covers it, so it is a bug. |

---

## 4. All findings at a glance

| Id | Severity | In one line | Status |
|---|---|---|---|
| K1-1 | Critical | An account that has a site breaks its Insights, Artifacts and Activity pages | **fixed** |
| K1-2 | Important | The agent can save a site the editor then refuses to open | open |
| K1-3 | Important | Restoring an older version can be refused because of the clones that version used | open |
| K1-4 | Important | After a refused save the canvas keeps the refused edit, and nothing typed after it saves | **fixed** (sync fix) |
| K1-5 | Important | Renaming a site while the agent works throws away the agent's whole request | open |
| K1-6 | Minor | Undo, redo and restore quietly undo a rename | open |
| K1-7 | Minor | The marketer sees the agent's raw validator text and raw server errors | open (wording: founder) |
| K1-8 | Minor | The agent's own restore brings back the pages but not that version's sections | open |
| K2-1 | Important | A section can publish fine yet be impossible to open in the editor | open |
| K2-2 | Minor | The section checker refuses ordinary copy that contains a class-like word | open (narrowed) |
| K3-1 | Critical | Agent code in the editor frame can save, undo and redo as the marketer | **closed as ruled** (fixes 1+2) |
| K3-2 | Important | Agent code can send the editor frame to any website, inside the app | open |
| K3-3 | Important | On the standalone artifact page, the marketer's own saves wipe what they are typing | **fixed** (sync fix) |
| K3-4 | Important | After switching workspace, sites open on the previous workspace's editor domain | open |
| K3-5 | Important | An update arriving while the editor loads is lost, and the older site is saved over the newer | **fixed** (sync fix) |
| K3-6 | Important | The domain-move runbook leaves published pages down mid-move | open (operational) |
| K3-7 | Minor | One workspace's agent code can break every workspace's editor in that browser via cookies | open |
| K3-8 | Minor | Nothing stops the pages domain sharing the editor's domain | open (config-dependent) |
| K4-1 | Important | A run taken over after a worker dies says "built" and saves nothing | open |
| K4-2 | Critical | A long research section reaches the page writer raw, past the privacy filter | **parked** (privacy sprint) |
| K4-3 | Important | Two notes on one site section refuse the whole chat message | open |
| K4-4 | — | Duplicate of K3-3 | merged into K3-3 |
| K4-5 | Important | A worker with old session files forgets newer requests, then overwrites them | open (multi-host only) |
| K4-6 | Minor | The same section code saved under a second name gets the whole turn refused | open |
| K4-7 | Minor | A failed research read looks like "no research yet", and nobody is told | open |
| K4-8 | Minor | The site agent cannot ask a clarifying question properly | open |
| K5-1 | Critical (process) | A9's fix wave was missing from the first review base | **resolved** (merged `ecdb283db`) |
| K5-2 | Important | The editor canvas has none of the brand's spacing | open |
| K5-3 | Critical | A font name could break out of the theme stylesheet | **resolved** (A9 fix wave) |
| K5-4 | Important | Unreadable text and invisible buttons on some surfaces | **resolved** (A9 fix wave) |
| K5-5 | Important | Agent code can inject CSS into the published page | open |
| K5-6 | Minor | site-kit's icon checks are looser than the engine's | open |
| K5-7 | Minor | The icon cleaner dropped multi-line shapes, leaving empty icons | **resolved** (A9 fix wave) |
| K6-1 | Important | Switching tabs carries one site's Share settings into the next | open |
| K6-2 | Important | After the first publish, Share never offers Republish when the site changes | open |
| K6-3 | Important | Account sites publish indexable, and a noindex choice is lost | open |
| K6-4 | Minor | On a phone, a multi-page site has no navigation between pages | open (design call) |
| K6-5 | Minor | Slugs `healthz`, `p-assets`, `asset-store` publish but are not served right | open |
| K6-6 | Minor | Rolling back an old address puts it back on air beside the new one | open |
| K6-7 | Minor | The default slug ignores the server's length rule | open |

---

## 5. The findings, unit by unit

### K1 — The site document (Contracts 1, 2 and 8)
What a site document looks like, how it is saved, undone and versioned, and how the word "site" travels
between the apps. Lanes A, B and C, plus site-kit's shared schema.

#### K1-1 — An account that has a site breaks its Insights, Artifacts and Activity pages
- **Severity:** Critical. Status: **fixed** 2026-10-14 (`b31f759d9`): the frontend accepts `site` and shows it as a landing page; the contract-v1 parity test now also compares allowed values at every depth (it found exactly this gap and no other)..
- **What a person sees:** in a workspace that uses sites, open any account that has a 1:1 site page. Its
  Insights, Artifacts and Activity tabs show the server error page, and nothing on screen offers a way
  around it.
- **Why it happens:** the backend now labels that account's artifact with the type `"site"`. The accounts
  screen in the frontend has its own list of allowed artifact types, still
  `presentation | document | web | ad | email`. The page parses the whole response against that list, so
  one `"site"` makes the whole parse throw. Contract 8 named the backend list to update and it was
  updated; its frontend twin was missed. The automatic check that compares backend and frontend shapes
  (`zod-fields.json`) compares field names, not the allowed values, so nothing caught it.
- **Where:**
  - Sends `"site"`: `clue_api/frontend_read/contract_v1.py:481`, fed by
    `clue_api/frontend_read/account_workspace.py:150` through `wire_kind` (`clue_api/design_leg_wiring.py:718-723`).
    A site born for a tagged account is stamped onto that account (`clue_api/design_leg_tools.py:772`).
  - Refuses it: `features/accounts/model/account-workspace.ts:21`, parsed in
    `features/accounts/data/account-workspace.repository.ts:41`, which the server components at
    `apps/frontend/src/app/(protected)/accounts/[accountId]/{insights,artifacts,activity}/page.tsx` call.
  - Also missing `site`: the labels and filter options in `features/accounts/model/account-workspace-presentation.ts:3-18`.
- **How we know:** a probe parses a response with `"web"` (accepted) and with `"site"` (refused:
  `Invalid option: expected one of "presentation"|"document"|"web"|"ad"|"email"`). Verified by reading both
  sides and the birth path.
- **Fix direction:** add `"site"` to the frontend type list, with a label and a filter mapping (for
  example under "Landing pages"). Alternatively the server maps `site` to `web` for this one read, as it
  already does for the Head of ABM.

#### K1-2 — The agent can save a site the editor then refuses to open
- **Severity:** Important. Status: open.
- **What a person sees:** the site saves, renders and publishes fine. Opening it in the editor fails with
  `pages./.content.N.props.id: Invalid input: expected string`, in preview too. The document is stuck
  until another agent turn repairs it.
- **Why it happens:** the editor requires every section on a page to carry a text id. The write path
  checks the id only when it is already text. An agent-written section whose schema makes the id optional,
  numeric or defaulted gets through every write-side check, because the renderer never reads ids.
- **Where:**
  - Write side: `site-kit/src/render-core.tsx:85` (compile only checks that an `id` key exists),
    `site-kit/src/schemas.ts:139-146` (the id rule runs only `if (typeof sectionId === "string")`),
    `lumen_api/site_doc_validate.py:48-80` (never looks at ids).
  - Read side: `site-kit/src/site-document.ts:24-27` requires `props.id` to match `^[A-Za-z0-9_-]{1,200}$`;
    parsed on every editor load (`features/site-editor/model/site-wire.ts:20`,
    `features/site-editor/data/site.repository.ts:96`), shown as the load error in
    `features/site-editor/hooks/use-site-document.ts:49-51`.
- **How we know:** probe re-run by the controller. Three cases (optional and omitted, numeric, defaulted and
  omitted): compile accepts, the validator says valid, the editor's schema refuses.
- **Fix direction:** the validator refuses any section whose `props.id` is not a text id of the right
  pattern, whatever the section's schema says; and compile requires `id` to be a required `z.string()`.

#### K1-3 — Restoring an older version can be refused because of the clones that version used
- **Severity:** Important. Status: open.
- **What a person sees:** the person picks version 4 in the Versions menu and is refused with
  `…fragmentId: "frag_A" is not one of this brand's clones`. Undo back to the same state works, so restore
  and undo disagree, although the plan says a restore lands exactly the site that stood before.
- **Why it happens:** before saving, the check builds the list of allowed clones (sections copied from the
  seller's own site) from the **current** site, not from the site being restored. A clone that has since
  been replaced or retired is still allowed only if the current site uses it. The restore route lifts the
  agent-section rule (`restore_of`) but not the clone rule.
- **Where:** `lumen_api/toolbelt/site_documents.py:105,124` (brand built from the current stored document);
  `lumen_api/site_workspace_view.py:262-276` (`site_brand_for(document["scene"])`), `:157-182` and
  `:236-246` (`pinned_site_clones` from the site it is given); the refusal in `site-kit/src/validate.ts:152-158`.
- **How we know:** code read on both sides (running it needs stored fragments in the database).
- **Fix direction:** for a restore, build the brand from the site being written, or from the union of the
  current and the restored site's clones.

#### K1-4 — After a refused save, the canvas keeps the refused edit and nothing typed after it saves
- **Severity:** Important. Status: **fixed** 2026-10-14 by the sync fix (`2d9caac55, bb6b4bb40`).
- **What a person sees:** the person clears a heading before retyping it. 600 ms later the save is refused
  (headings, button labels and stat values may not be empty) and the dock shows the error. The dock goes
  back to the saved heading, but the canvas still shows the empty one. Every later edit on the canvas
  sends the whole site again, empty heading included, and is refused again. What they type keeps
  appearing on the canvas but is never saved, until they fix the heading on the canvas or reload.
- **Why it happens:** after a refusal the app reloads its own copy of the site, but it only pushes a copy
  into the canvas when the version number changes. A refused save does not change the version, so the
  canvas is never corrected. The same split happens for an edit the app ignores during an agent run, and
  for a save refused because a run was active when that run then ends without writing.
- **Where:** `features/site-editor/hooks/site-save-controller.ts:15,198-207` (its own comment claims "the
  canvas goes back to what is saved"); `use-site-editing-session.ts:105-109,153-160,201-240`;
  `features/site-editor/model/site-frame-sync.ts:15-26` (compares versions only);
  `site-editor/src/client/frame-controller.ts:225-241` (`replaceSite`, the only thing that reverts the canvas).
- **How we know:** probe run on the real pieces: one reload requested, error `heading: Too small`, and the
  canvas sync after the reload is `none`.
- **Fix direction:** after a refusal, force the canvas to take the server's copy even when the version is
  unchanged (for example a sync counter that the canvas sync also compares).

#### K1-5 — Renaming a site while the agent works throws away the agent's whole request
- **Severity:** Important. Status: open.
- **What a person sees:** the marketer renames the site's tab while a site request runs. The request ends
  "the site changed while this request ran", and minutes of agent work are thrown away.
- **Why it happens:** rename has no agent-run lock and moves the version number. The site turn saves once,
  at the very end, and only if the version has not moved since it started.
- **Where:** `lumen_api/main.py:2749-2771` (`PUT /documents/{id}/title`) and
  `lumen_api/toolbelt/documents.py:605-617` have no agent-run check; `clue_design/documents.py:383-392`
  bumps the version; the site turn reads its base at `main.py:11949` and saves at `:11965-11975`; the
  header rename is not locked in `features/chat-shell/components/chat-surface.tsx:1316-1320`.
- **How we know:** code read.
- **Fix direction:** refuse a rename with `409 document.agent_run_active` while a run drives the document,
  and grey out the header rename under the lock.

#### K1-6 — Undo, redo and restore quietly undo a rename
- **Severity:** Minor. Status: open.
- **What a person sees:** edit a heading (version 5), rename the site "Acme proposal" (version 6), press
  ⌘Z to undo the heading edit: the title goes back to the old one too. Redo does the same.
- **Why it happens:** undo history stores whole-site snapshots, title included, and a rename is not
  recorded in that history.
- **Where:** `clue_design/documents.py:361-394` (rename), `lumen_api/toolbelt/site_documents.py:147-171`
  (undo and redo reinstall snapshots), `clue_design/documents.py:664` (the row's title follows the
  snapshot), `lumen_api/main.py:4713` (version numbering).
- **Fix direction:** keep the current title when reinstalling a snapshot, or record a rename as its own
  history step.

#### K1-7 — The marketer sees the agent's raw validator text and raw server errors
- **Severity:** Minor. Status: open; the wording is a founder/design call.
- **What a person sees:** the dock's error line can read
  `page.content.2(stats).heading: Too small: expected string to have >=1 characters`,
  `…links to /pricing, which is not a page of this site; … (a new page is pages/<name>.json)`,
  `…pick a file from brand/brand.md`, or, on a newly born site,
  `shell.json: does not exist yet; create it with write_file`. These are written for the agent, not for a
  person. A server error (503) shows the server's raw message, which for the validator is the tail of a
  command-line error.
- **Where:** `features/site-editor/hooks/site-save-controller.ts:204` (shows the first error line) and `:213`
  (the 503 detail); the texts come from `site-kit/src/validate.ts:63,107,236,258` and
  `lumen_api/site_doc_validate.py:114`.
- **Fix direction:** turn refusal lines into person-facing sentences, or show one plain sentence plus the
  field; never show a 503's raw detail.

#### K1-8 — The agent's own restore brings back the pages but not that version's sections
- **Severity:** Minor. Status: open.
- **What a person sees:** "bring back version 3" to the agent: version 3's text is saved against today's
  rewrite of a section rather than the version 3 one. The validator then refuses text shaped for the old
  section (the agent gets confused), or the section renders differently. The person's own restore from
  the Versions menu is exact; the agent's is not.
- **Where:** `lumen_agent/site/tools.py:488-500` writes only pages and the shell;
  `lumen_agent/site/workspace.py:280-319` re-pins sections by name; `lumen_api/site_workspace_view.py:185-203`
  picks the current site's section of that name, else the newest.
- **Fix direction:** carry the version's own section pins into the turn instead of re-deriving them by name.

---

### K2 — Agent-written section code (Contracts 3 and 4)
How code the agent writes is checked, stored, linked, rendered and published (Lane A), loaded in the
editor (Lane C), and cleaned before publishing.

#### K2-1 — A section can publish fine yet be impossible to open in the editor
- **Severity:** Important. Status: open.
- **What a person sees:** the published page is fine, but the editor shows its error state and the site
  cannot be edited, with no warning when the section was written.
- **Why it happens:** sections import two libraries, `zod` and `react`. The publish renderer hands sections
  the whole of both libraries. The editor hands them a fixed short list (from zod only `z`; from react a
  hand-written list of 33 names). The write check only looks at **which library** a section imports, not
  **which names**. So a section that imports, say, `toJSONSchema` from zod or `cache` from react passes the
  write, renders and publishes, and then fails to load in the editor.
- **Where:** renderer `site-kit/src/render-browser.tsx:31-35,47-54` (exports every name); editor
  `site-editor/scripts/build.ts:18-45` and `site-editor/src/client/host-globals.ts:14` (fixed list);
  loader `site-editor/src/client/sections.ts:36-49`.
- **How we know:** a probe shows the compiled section keeps its `import { z, toJSONSchema } from "zod"`; zod
  has about 240 names and react has 10 the editor list leaves out; by the rules of JavaScript modules a
  missing name is a load error. (Not run in a browser.)
- **How likely:** the section-writing skill only uses `z`, so ordinary sections are fine; it needs the
  agent to deviate.
- **Fix direction:** make the editor's shims hand over the whole library, as the renderer does; or make
  the write check refuse names outside the editor's list.

#### K2-2 — The section checker refuses ordinary copy that contains a class-like word
- **Severity:** Minor. Status: open, narrowed.
- **What a person sees:** nothing directly; the agent is told a section is invalid and wastes turns
  rewording copy such as "text-sm friendly copy", which the checker reads as a styling class.
- **Why it happens:** the class rules read every string in the file, not only `className` values.
- **Where:** `site-kit/src/check-section.ts:188-210`.
- **Status note:** the colour half of this (a `#hex` or `rgb(` in prose being refused) was fixed by A9's
  `a41d14598`; the controller re-ran the probe to confirm. The class-word half remains.
- **Fix direction:** limit the class checks to `className` strings, as the motion rules already are.

---

### K3 — The editor protocol and the domains (Contracts 6 and 9)
The messages between the app and the editor frame, and the domains: the editor domain, the published
pages domain, custom domains, and the planned move of published pages to a new domain.

#### K3-1 — Agent code in the editor frame can save, undo and redo as the marketer
- **Severity:** Critical. Status: **closed as ruled** 2026-10-14 (`9db8f20dd`): founder chose fixes 1 and 2 — the frame may ask for undo/redo only while the marketer is editing, and a different site gets a fresh frame. **Accepted residual:** a section's code can still forge a save while the marketer is editing that same site (per-section isolation stays ruled out, D2); every save is a restorable version and publishing is always the person's own action. Fix 3 (only after a real click) was not taken.
- **What a person sees:** nothing; that is the danger. While the marketer has a site open, a hostile or
  badly behaved agent-written section on it can:
  - in edit mode, save any content as the marketer, for example swap a button's link to a phishing page,
    which then publishes under the marketer's name;
  - run undo and redo on the server as the marketer, **even when the marketer is only previewing**;
  - show made-up error text in the canvas;
  - keep doing all of this to **other** sites the marketer opens later in the same page, because its code
    stays loaded in the frame.

  Its reach has limits: it cannot publish, and it cannot read the app's cookies or call the app's APIs.
- **Why it happens:** the app trusts a message from the editor frame when four checks pass: it comes from
  the frame's window, from the editor's origin, carries a secret nonce, and names the right document.
  Agent code runs inside that same window, so it passes all four: the window and origin are automatically
  right; the nonce sits in the frame's address and in every message the app sends; and the document id
  arrives with the app's next "init", which a forged "ready" message triggers at once. The frame is never
  reloaded between documents, so a section's code survives into the next site.
- **Where:** the app's acceptor `site-kit/src/editor-protocol.ts:233-244`, fed by
  `features/site-editor/hooks/use-site-frame-host.ts:42-53` and acted on in
  `features/site-editor/hooks/use-site-editing-session.ts:135-190` (save, undo) and `:360-366` (undo and redo
  check only the agent-run lock, not edit mode); the frame `site-editor/src/client/editor-app.tsx:133`
  (sections run in the frame's own window) and `site-editor/src/client/main.tsx:8-11` (the nonce stays in
  the address).
- **How we know:** the controller re-ran three browser probes on Lane C's own test harness: forged
  "ready", undo and save are all accepted, and the section's code survives into the next document. The
  real acceptor accepts forged messages, and the real section checker passes a section that forges them.
- **The earlier decision this sits inside:** D2 (2026-10-09) chose one editor frame per workspace on its
  own domain, with no per-section sandbox. This finding does not argue with that; it is about what the
  app lets a frame message do. The founder confirmed on 2026-10-14 that per-section isolation stays out.
- **Simple fixes on the table (none chosen yet):**
  - accept undo and redo from the frame only in edit mode;
  - reload the frame itself, not just re-send the site, when the marketer opens a different document, so a
    section's code cannot carry over to another site;
  - accept a save, undo or redo from the frame only right after a real click or keypress by the person.

  The first two together are what the reviewer called the minimum. They do not stop a forged save while
  the marketer is editing the same site.

#### K3-2 — Agent code can send the editor frame to any website, inside the app
- **Severity:** Important (security). Status: open.
- **What a person sees:** the canvas inside app.cluehq.ai suddenly shows another site's page, for example a
  fake "Sign in again to keep editing". The request carries what the frame knew (the site, the brand,
  section links, the nonce) and the marketer's IP address. The app does not notice.
- **Why it happens:** the frame's sandbox stops it navigating the whole app, but a frame may always
  navigate itself. The app sends no rule (a `frame-src` content security policy) limiting where its frame
  may go, and nothing watches for the frame loading a different page.
- **Where:** `features/design-editor/components/site-artifact-canvas.tsx:41-49`;
  `site-editor/src/server/csp.ts:8-25`; `apps/frontend/next.config.ts` (no CSP); the containment test
  `tests/site_editor/test_editor_containment.py:83-106` only tries navigating the parent.
- **How we know:** browser probe: the frame navigated to `collector.example` with the nonce in the
  address, while the app's page stayed put.
- **Fix direction:** an app CSP with `frame-src` limited to the workspace's editor origin; a watchdog that
  hides the frame if it loads a second time without saying "ready"; a self-navigation case in the
  containment test.

#### K3-3 — On the standalone artifact page, the marketer's own saves wipe what they are typing
- **Severity:** Important. Status: **fixed** 2026-10-14 by the sync fix (`ebe9bcdc5`). (Found again by K4 as K4-4.)
- **What a person sees:** on `/artifacts/...`, while typing on the canvas, every few seconds the canvas
  snaps back to the last saved text, the cursor jumps, and the words typed since the last save vanish.
  In a worse timing an older copy is saved over a newer one.
- **Why it happens:** this page polls "is the agent busy?" every 4 seconds, and reloads the site whenever
  the version number moves, including when the marketer's own save moved it. The reload pushes a fresh
  copy into the canvas, which cancels the edit that was waiting to be sent. The chat page is not affected;
  it reloads only when the agent saves.
- **Where:** `features/chat-shell/components/editor-surface.tsx:142-150`;
  `features/design-editor/hooks/document-agent-run.logic.ts:28-34` (any version move counts);
  `features/site-editor/hooks/use-site-editing-session.ts:104-110,237-240`;
  `features/site-editor/model/site-frame-sync.ts:24`; `site-editor/src/client/frame-controller.ts:225-241`.
- **How we know:** two separate probes (one per review unit) ran the real pieces: the poll reloads after
  the person's own save, and the typed text is gone afterwards.
- **Fix direction:** reload only for a version the session did not write itself (compare with the save
  controller's own version), or only when an agent run was active or just ended; skip pushing a copy that
  matches what the canvas already has.

#### K3-4 — After switching workspace, sites open on the previous workspace's editor domain
- **Severity:** Important. Status: open.
- **What a person sees:** open a site in workspace A, switch to workspace B from the sidebar, open one of
  B's sites. If it has agent sections: "The section … could not be loaded" until a hard reload. If not, it
  opens, but on A's editor domain, so B's site and brand are sent into the address meant for A.
- **Why it happens:** the editor's address is cached once for the life of the browser page, with no
  workspace in the key, and switching workspace is a soft navigation, so the cache survives.
- **Where:** `features/site-editor/hooks/use-site-editor-origin.ts:12-21`;
  `features/session/data/session-actions.ts:42-47`; `apps/frontend/src/components/shell/workspace-switcher-context.tsx:137-143`;
  the editor server's refusal `site-editor/src/server/app.ts:133-135`.
- **How we know:** code read (not run live).
- **Fix direction:** key the cache by workspace or clear it on a switch, or make the switch a full page load.

#### K3-5 — An update arriving while the editor loads is lost, and the older site is saved over the newer
- **Severity:** Important. Status: **fixed** 2026-10-14 by the sync fix (`e1443761e`).
- **What a person sees:** nothing at first; then the newer version's changes are silently gone. It needs a
  version change during the few moments the editor spends loading a site's agent sections: an agent save
  arriving as the site opens, an undo right after opening, or Reload after another tab saved.
- **Why it happens:** while the frame loads a site's agent sections it holds no site yet, and drops any
  update or edit sent to it. The app counts an update as delivered when it sends it, not when the frame
  applies it. The frame then shows the older site, and its next edit is saved over the newer version.
- **Where:** `site-editor/src/client/frame-controller.ts:206-226` (and the same drop at `:126`, `:131`,
  `:254`); the app side `features/site-editor/hooks/use-site-editing-session.ts:237-240`.
- **How we know:** probe on the real frame controller: the frame shows version 4, and its edit is saved on
  top of version 5. This is worse than a known minor recorded by Lane C (Task 14), which assumed the
  marketer always ends on the latest site; that is only true for sites without agent sections.
- **Fix direction:** the frame keeps the newest update and queued edits while loading and applies them
  after; or each edit carries the version it started from, and the app refuses a stale one.

#### K3-6 — The domain-move runbook leaves published pages down mid-move
- **Severity:** Important (operational). Status: open; the move has not happened yet, so nothing is broken today.
- **What a person sees (during the move):** every old published link answers with a permanent redirect
  to the new domain, and the new domain answers "not found" until the hostname rows are moved. Browsers
  cache the permanent redirect. The runbook says each step is safe to stop after.
- **Why it happens:** step 2 turns the redirect on before step 4 moves the hostnames, and the page origin
  only looks hostnames up by exact match.
- **Where:** `docs/specs/pages-hosting-runbook.md:451` (§8); `infra/cloudflare/pages-edge/routing.js:19-24`;
  `platform/page_origin/clue_page_origin/reads.py:67-69` → `hostnames.py:308-317`.
- **Fix direction:** let the page origin also try the old-domain twin of a hostname while the move is in
  progress, so the rows can move at any time; or rewrite §8 so steps 2–4 are one uninterrupted operation.

#### K3-7 — One workspace's agent code can break every workspace's editor in that browser via cookies
- **Severity:** Minor. Status: open.
- **Why it happens:** every workspace's editor lives under `edit.deeppresence.ai`, which is not on the
  Public Suffix List, so code on one workspace's subdomain may set cookies for all of them. More than
  16 KB of cookies makes the editor server answer "header too large", and every workspace's editor is
  blank in that browser until its cookies are cleared.
- **Where:** `.env.example:628` (`CLUE_SITE_EDITOR_SUFFIX`); `site-editor/src/server/main.ts:12`.
- **How we know:** browser cookie rules and Node's default header limit (not run).
- **Fix direction:** list the editor suffix on the Public Suffix List (as Lovable, Canva and Retool did),
  or raise the editor server's header limit and ignore cookies.

#### K3-8 — Nothing stops the pages domain sharing the editor's domain
- **Severity:** Minor (depends on a domain choice not made yet). Status: open.
- **What could happen:** if published pages move to `deeppresence.ai`, the edge Worker forwards editor
  hosts to the page origin and every workspace's editor goes down; a workspace could also be given the
  label `edit`.
- **Where:** `deploy/check_prod_env.py:115-130`; runbook §8 step 1; `infra/cloudflare/pages-edge/routing.js:27`;
  `hostnames.py:42-66` (the reserved labels lack `edit`).
- **Fix direction:** refuse a pages domain on the editor's domain in `check_prod_env` (and in the Worker),
  reserve `edit`, and say so in the runbook.

---

### K4 — One agent turn on a site (Contracts 5 and 7) and the run locks
How the site agent reads the account's research and its cited claims, how a site turn runs and saves,
and the locks that stop a person editing or publishing while the agent works.

#### K4-1 — A run taken over after a worker dies says "built" and saves nothing
- **Severity:** Important. Status: open.
- **What a person sees:** the chat says "Design turn applied … Built the page …", but the site has not
  changed, and the history records "nothing changed".
- **Why it happens:** the agent's work lives only in its working files until a single save at the end.
  When a worker dies (a deploy, out of memory, a restart), another worker takes the same run over. The
  takeover resumes the agent's **conversation** from where it stopped, but rebuilds its **files** from the
  old stored site. If the agent had already finished talking, the resume returns at once, the files equal
  the stored site, and the run reports "applied, nothing to save". If it stopped mid-run, the agent carries
  on believing pages exist that its files no longer hold. If the old worker is still alive (it lost its
  lease rather than died), both can save, because the save is not tied to the lease.
- **Where:** `clue_api/design_leg_wiring.py:2634-2638` (the conversation is keyed by the run id);
  `lumen_agent/checkpoint.py:47-52` (resume); `lumen_agent/site/harness.py:463,507-508` and
  `lumen_agent/site/workspace.py:584-633` (files rebuilt from the stored site);
  `lumen_api/main.py:11767-11769,11850`; `lumen_api/fleet_handler.py:362-377`; `lumen_api/toolbelt/wiring.py:331-356`.
- **How we know:** the controller re-ran the probe: the second attempt resumed, reported applied, the site
  did not change, and the summary still said "Built the page".
- **Fix direction:** never resume a conversation over rebuilt files: either start a fresh conversation per
  attempt (key it by run id plus lease generation), or save the files with the conversation and restore
  both; and tie the final save to the lease.

#### K4-2 — A long research section reaches the page writer raw, past the privacy filter
- **Severity:** Critical (re-graded up from the reviewer's Important). Status: **parked to the privacy
  and verification sprint** (founder, 2026-10-14).
- **What it means:** a sensitive or unverified personal statement about a contact, which the platform holds
  back on purpose, can reach the agent that writes the page, and could end up on the page.
- **Why it happens:** the platform cuts any research section larger than one read page (12 KiB) into a
  prefix of its JSON text. The site turn cannot parse the cut text, so for that section it never asks the
  claim check about any of its claims, writes the raw cut JSON (claim ids included) into the agent's
  research file, drops the "background only, never on the page" marker, loses the section's end, and
  labels none of its claims.
- **It also hurts page quality, apart from privacy:** the agent reads raw JSON instead of prose for that
  section, and never sees its end.
- **Where:** cut in `clue_api/arv2/read_tools.py:937-959` (budget at `:423`); read in
  `lumen_agent/site/workspace.py:74-81,93-96,108-115`; `lumen_api/site_workspace_view.py:71-91` takes claim
  ids only from what it could parse and ignores the ids the platform sent alongside.
- **How we know:** the controller re-ran the probe (a 17.7 KB section: cut, zero claims checked, the held
  statement present, the marker gone). A read-only look at the dev database showed real data already hits
  it: one Insights section of 10 KB with 35 claim ids, of which the site turn saw none.
- **Fix direction (for that sprint):** read whole sections on the design side, or page inside a section;
  never write an unparseable section raw; use the claim ids the platform sends; hold back the whole section
  when it was cut.

#### K4-3 — Two notes on one site section refuse the whole chat message
- **Severity:** Important. Status: open.
- **What a person sees:** the person clicks the hero's headline and notes "shorter headline", clicks the
  hero's image and notes "use a classroom photo", and presses Send. The message is refused: "the same
  context reference may appear only once in a submission".
- **Why it happens:** on a site, a note's address is the whole section (`site:/#hero`), not the element
  inside it, so two notes on one section produce two identical references, and the platform refuses
  duplicates. On the web lane, notes carry the inner element's path and do not collide.
- **Where:** `features/site-editor/model/site-annotations.ts:5-16`; `features/design-editor/adapter/annotations.ts:78-92`;
  `features/chat-shell/model/edit-targets.ts:86-107`; `clue_api/chat/composer_context.py:221-226`;
  `clue_api/design_turn_targets.py:344-347`.
- **How we know:** both halves run by the controller: the frontend sends two `site:/#hero` refs, and the
  platform refuses with `CONTEXT_REF_DUPLICATE`.
- **Fix direction:** merge notes on one section into one reference (numbered notes) before sending, or let
  the site composer accept repeated references and keep each note.

#### K4-4 — Duplicate of K3-3
Found independently by K4; the same bug as K3-3, merged into it.

#### K4-5 — A worker with old session files forgets newer requests, then overwrites them
- **Severity:** Important. Status: open. Only on deployments with two or more design workers on separate
  disks; dev stacks share one disk.
- **What a person sees:** the agent forgets what was asked and planned in the previous request, and that
  history is then lost for good.
- **Why it happens:** the site agent starts a fresh conversation for each request (founder ruling
  2026-10-11), so its only memory between requests is its session files (`plan.md`, `history.md`). A worker
  restores those files from storage only when it has none, and saves whatever it holds afterwards. Worker A
  runs request 1, worker B runs request 2, worker A runs request 3 with its stale files, and its snapshot
  becomes the newest.
- **Where:** `lumen_api/main.py:11831` (restore only when missing) and `:11866` (snapshot);
  `clue_api/design_leg_wiring.py:2634-2638`.
- **Fix direction:** restore whenever the newest stored snapshot differs from the one the local files were
  built from (record which snapshot they came from).

#### K4-6 — The same section code saved under a second name gets the whole turn refused
- **Severity:** Minor. Status: open.
- **What a person sees:** after a whole request, "The website could not be saved: agent_sections: agent
  section ProcessSteps has no stored module …", a misleading reason, and the request's work is lost.
- **Why it happens:** stored sections are keyed by their content. When the agent writes identical code
  under a second name (`StepsBand`, then `ProcessSteps`), the store hands back the existing row with the
  old name, and the final save refuses the name mismatch.
- **Where:** `site-kit/bin/compile-section.ts:57-59`; `clue_design/site_sections.py:54-72`;
  `lumen_api/site_turn_ports.py:229-234`; `lumen_api/site_workspace_view.py:218-220`.
- **Fix direction:** key stored sections by workspace, name and content, or have the write refuse or rename
  when the stored name differs.

#### K4-7 — A failed research read looks like "no research yet", and nobody is told
- **Severity:** Minor. Status: open.
- **What a person sees:** when the research read fails (a timeout, a refusal, an outage), the agent writes a
  generic page as if the account had no research, and neither the reply nor the summary mentions it.
- **Why it happens:** read errors are collected and then thrown away; the agent's files then say "There is no
  written research for this account yet." Dropping the statements is right (fail closed); staying silent is not.
- **Where:** `lumen_api/site_workspace_view.py:56-68,83-90,371`; `lumen_agent/site/workspace.py:595-602`.
- **Fix direction:** have the research file say the read failed (and which page), and carry a flag the reply
  and the summary can show.

#### K4-8 — The site agent cannot ask a clarifying question properly
- **Severity:** Minor. Status: open.
- **What a person sees:** the agent's question arrives as "Design turn applied on website document …:
  <question>". The clarification card other design turns get never appears for a site.
- **Why it happens:** the site prompt tells the agent to ask before adding something that is not on the
  page, but the site turn has no way to return "clarification requested".
- **Where:** `lumen_api/main.py:11757-11780`; `lumen_agent/site/system_prompt.md:73-77`;
  `clue_api/design_leg_wiring.py:877-880`.
- **Fix direction:** give the site turn the same opening-move clarification the ad runtime has, or drop
  clarification from Contract 7 and the code that waits for it.

---

### K5 — The brand seam (A9 → A → C, and B's brand file)
How a brand's colours, fonts, surfaces and spacing travel from A9's brand kit into the site theme, the
editor canvas and the published page.

#### K5-2 — The editor canvas has none of the brand's spacing
- **Severity:** Important. Status: open.
- **What a person sees:** in the editor, sections have no section padding, no vertical rhythm, no card
  padding and no page margin, so everything looks collapsed. The published page is spaced correctly. The
  marketer edits against a layout that does not match what visitors see.
- **Why it happens:** the same kind of bug as the brand-surfaces one fixed during the merge (`2ae9f44e0`).
  The editor's stylesheet is compiled once, when the editor is built, and its theme block does not declare
  the brand's spacing names; the published page's theme does.
- **Where:** `site-editor/src/client/styles.css:8-108` (no `--spacing-*` entries);
  `site-kit/src/theme.ts:257-259` (the published theme declares them); the published compile in
  `lumen_api/site_render.py:383`.
- **How we know:** a probe compiled the editor's CSS: all 12 spacing classes are missing. A cross-check
  rendered a real site and compiled both stylesheets: exactly those 12 classes are styled on the published
  page and not on the canvas.
- **Fix direction:** add the spacing entries to the editor's theme block (they point at per-brand values
  the editor already injects), or generate that block from the same list the published theme uses so the
  two cannot drift again.

#### K5-5 — Agent code can inject CSS into the published page
- **Severity:** Important (security). Status: open.
- **What could happen:** a hostile section puts arbitrary styling on the published marketing page, for
  example a full-screen overlay. Scripts still cannot run there (the published page forbids all scripts),
  so this is styling only.
- **Why it happens:** the page's theme text is built inside the same render page where agent code runs. A
  section can tamper with a built-in JavaScript function (for example `Array.prototype.join`) so the theme
  text carries its own CSS. The section checker does not catch that. The design API pastes the theme text
  into the CSS build without checking it, and the published page's CSS cleaner removes only `url()` and
  `@import`.
- **Where:** `site-kit/src/render-core.tsx:71` and `site-kit/src/render-browser.tsx`;
  `lumen_api/site_render.py:429` (`_compile_css`); `site-kit/src/check-section.ts:193`;
  `lumen_api/site_sanitize.py` (`clean_css`).
- **How we know:** the controller re-ran the probe on the merged tree: the theme text carries the
  section's marker, the checker passes the section, the CSS build keeps the injected rule, and the cleaner
  leaves it alone. This is worse than a known minor Lane A recorded (Task 29), which assumed every output
  path is cleaned; the theme path is not.
- **Fix direction:** check the theme text on the Python side before compiling (it has a fixed shape: a
  `@theme inline { … }` block of `--name: value;` lines), or build it where sections cannot reach; and
  freeze the render result deeply.

#### K5-6 — site-kit's icon checks are looser than the engine's
- **Severity:** Minor. Status: open.
- **What it is:** the engine and the Python side require an icon glyph of 1–4 characters with no control
  characters, and an SVG icon with a width and height between 1 and 256. site-kit checks only for unsafe
  characters and a safe SVG. Harmless today (text is escaped, and site-kit does not use width and height),
  but the three checks were meant to agree exactly (an A9 ruling).
- **Where:** `site-kit/src/brand-values.ts:225-226` against `subsystems/clue-design/crates/lumen-core/src/brand.rs`
  and `subsystems/clue-design/apps/api/lumen_ingestion/normalizer/component_tokens.py`.
- **Fix direction:** copy the same limits into site-kit, or write the difference down.

---

### K6 — Publishing end to end
The site publish routes, the page origin that serves published pages, hostnames, the Share menu, the
agent's publish tools, the locks and batch publishing.

#### K6-1 — Switching tabs carries one site's Share settings into the next
- **Severity:** Important. Status: open.
- **What a person sees** (all three reproduced):
  1. Site A is published at `acme-q4`. Switch to site B, never published, and open Share: the address field
     shows `acme-q4`, and publishing B is refused as "already published by another document".
  2. Open the "Initech account page" tab, switch to the "Umbrella account page" tab, and publish. Umbrella's
     site goes live at `/initech-account-page`, a link carrying another account's name, and Initech's own
     site can no longer use that address.
  3. Publish site E and switch to site F while it is publishing. F, never published, shows "Asset published"
     with E's address, and "Copy link" copies E's address.
- **Why it happens:** one Share header serves every tab (it has no `key`), the address and the indexing
  choice are set once from the first tab's title, and a publish result lands on whichever tab is showing
  when it returns. The web lane had the same hook; Wave 2 makes it the normal path, because a project now
  holds one site per account, open side by side in tabs.
- **Where:** `features/chat-shell/components/artifact-stage.tsx:466`;
  `features/chat-shell/hooks/use-artifact-sharing-controller.ts:181,208,296-300,340-373`.
- **How we know:** the controller re-ran the probe, which mounts the real Share controller.
- **Fix direction:** key the header (or the controller) on the document, so everything resets on a switch,
  and drop a publish result for a document that is no longer shown.

#### K6-2 — After the first publish, Share never offers Republish when the site changes
- **Severity:** Important. Status: open.
- **What a person sees:** the marketer publishes version 3. The agent (or they) take the site to version 4.
  Share still says "Asset published" and offers only Preview and Copy link, and the link still serves
  version 3. The only way to push version 4 is hidden: re-save the same address, which brings back
  "Republish". Also, pressing Publish while a save is still on its way publishes the version before that edit.
- **Why it happens:** the menu shows Publish only when the site was never published or the address was
  edited. It ignores the published version number the server returns, and publishing does not wait for
  pending saves.
- **Where:** `features/chat-shell/components/artifact-share-menu.tsx:132,177-196`;
  `features/chat-shell/hooks/use-artifact-sharing-controller.ts:286-295,340-373`; the server's publish state
  in `lumen_api/main.py:5015` (`_publish_state`, which does return `doc_version`);
  `features/site-editor/hooks/site-save-controller.ts`.
- **How we know:** code read; nothing in the chat shell compares versions.
- **Fix direction:** compare the published version with the current one and show "changes since publish"
  with Republish; wait for pending saves before publishing.

#### K6-3 — Account sites publish indexable, and a noindex choice is lost
- **Severity:** Important. Status: open; founder ruling R25-4 makes it a bug, not a new decision.
- **What a person sees:** every account site ("Prepared for <account>", with claims about named contacts)
  can be indexed by search engines from its first publish. If the marketer unticks "Allow indexing" and
  publishes, the page is protected, but after a reload the next republish quietly sends "indexable" again.
- **Why it happens:** the checkbox starts ticked and is never set from what is actually live; the publish
  state carries no indexing field; the route and tool that set "noindex" accept web documents only; and the
  site publish reads a flag that can never be set for a site.
- **Where:** `features/chat-shell/hooks/use-artifact-sharing-controller.ts:181`; `lumen_api/main.py:5015`
  (`_publish_state`) and `:2737` (`PUT /documents/{id}/web-noindex` requires a web document);
  `lumen_api/toolbelt/documents.py:561`; `lumen_api/toolbelt/publishes.py:237`; `site-kit/src/shell.tsx:60`.
- **Fix direction:** mark a site born for a tagged account noindex at birth (as ABM batch publishing already
  does), let the noindex setting accept sites, and return indexing in the publish state so the checkbox
  shows the truth.

#### K6-4 — On a phone, a multi-page site has no navigation between pages
- **Severity:** Minor. Status: open; needs a design ruling.
- **What a person sees:** a recipient on a phone opens the site and sees no link to its other pages unless a
  section happens to link there. The header navigation is hidden below 768 px, and the footer has only the
  legal links.
- **Where:** `site-kit/src/shell.tsx:66` and `:84-95`.
- **Fix direction:** a small-screen menu that needs no script (`<details>`), or page links in the footer.

#### K6-5 — Slugs `healthz`, `p-assets` and `asset-store` publish but are not served right
- **Severity:** Minor. Status: open.
- **What a person sees:** a site published at `healthz` shows `{"status":"ok"}` instead of the home page; at
  `p-assets` or `asset-store` the home page works and every other page answers "not found".
- **Why it happens:** the page origin uses those names for its own routes, and the address rule does not
  reserve them.
- **Where:** `lumen_api/toolbelt/publishes.py:59`, `lumen_api/main.py:8200`;
  `platform/page_origin/clue_page_origin/routes.py:78-128`.
- **How we know:** the controller re-ran the probe on the real page-origin router.
- **Fix direction:** reserve the page origin's own top-level names in the address rule.

#### K6-6 — Rolling back an old address puts it back on air beside the new one
- **Severity:** Minor. Status: open. Reachable only through the API and the old standalone editor; the
  app's Share menu has no rollback.
- **What happens:** a site moved from `acme` to `acme-q4`; rolling back `acme` brings it back live with the
  older revision while `acme-q4` keeps serving the newer one.
- **Where:** `clue_design/publishes.py:474-525` (rollback does not take other addresses offline, unlike
  publish at `lumen_api/toolbelt/publishes.py:153`).
- **Fix direction:** take other addresses offline in the rollback, or refuse a rollback on an address the
  site has moved away from.

#### K6-7 — The default slug ignores the server's length rule
- **Severity:** Minor. Status: open.
- **What a person sees:** a long title is refused with a raw pattern error; a 1–2 character title too; and
  every non-Latin title becomes `untitled-artifact`, so the second such site is refused as taken.
- **Where:** `features/chat-shell/model/artifact-sharing.ts:30-39` and
  `features/chat-shell/components/artifact-share-menu.tsx:159` (up to 72 characters) against the server's
  3–64 rule in `lumen_api/toolbelt/publishes.py:320-327`.
- **Fix direction:** use the server's own default-address rule, or send no address and let the server choose.

---

## 6. Resolved findings

| Id | What it was | How it was resolved |
|---|---|---|
| **K5-1** Critical (process) | A9 reopened for a 21-commit fix wave after its first merge, and the review base was tagged without re-checking every lane's latest commits, so the fix wave was missing from what K1–K5 reviewed. | Merged as `ecdb283db`; the review base was re-tagged as `w2/review-base-2` (`94e49530d`). Lesson recorded: re-check every lane's tip immediately before tagging. |
| **K5-3** Critical | A font family, style or weight in a brand kit could close the theme's `<style>` block and inject content, on the editor domain and the published page. | A9's fix wave (`3bae3005e`, `8282045af`, `a59c01c0b`, `403df437c`): the family is escaped, the font file must be an asset path, style and weight must be known values, and a face that fails is dropped. |
| **K5-4** Important | Unreadable text and invisible buttons: a dark brand's light button painted the page colour; white nav links on a white header; Conduit's `solid.2` button drew white on light blue at 1.46:1. | A9's fix wave (`359389299`, `5ef55b883`). The controller re-ran the contrast probes: Conduit `solid.2` is now 10.42:1, the nav swap exists, and 0 unreadable pairs remain on 4 kits. |
| **K5-7** Minor | The capture's icon cleaner dropped shapes drawn over several lines, leaving empty icon boxes on buttons. | A9's fix wave (`b93fca4c7`). |

---

## 7. Findings that share a cause (useful for the fix pass)

- **The editor frame and the app getting out of step:** K1-4 (refused edit stays on canvas), K3-3 (own
  saves wipe typing), K3-5 (update lost while loading). All three are about when the app pushes a copy of
  the site into the canvas and what the canvas does with it.
- **What agent code can do inside the editor frame:** K3-1 (posing as the editor), K3-2 (navigating the
  frame away), K3-7 (cookie flooding). K3-1's fix decision may shape K3-2's.
- **The Share menu:** K6-1 (state carried across tabs), K6-2 (no Republish), K6-3 (indexing), K6-7 (default
  address). All live in the same controller and menu.
- **Agent sections and the editor disagreeing with the publish path:** K1-2 (ids), K2-1 (library names),
  K5-2 (spacing). Each is "the publish path accepts what the editor cannot show".
- **Agent work being lost:** K1-5 (rename mid-run), K4-1 (takeover), K4-6 (second name).
- **Restores not being exact:** K1-3 (clones), K1-8 (agent's own restore), K1-6 (rename reverted).

---

## 8. What the K reviews confirmed is right

So that the absence of a finding means something, these were checked and hold (full lists in each
report's "Checked and holds"):

- **Document model (K1):** the route rule is the same in the frontend schema, Python and the validator;
  every shape the editor would refuse is also refused at write (except ids, K1-2); tenancy holds (another
  workspace's images refused even in text; every site route is workspace-scoped); saves, undo, redo and
  restore are all protected against overwriting a newer version; the agent-run lock refuses every manual
  write during a run; the undo model (move to redo, clear redo on a new write, cap 50) is right.
- **Agent code (K2):** the HTML cleaner survives 15 hostile cases; published pages forbid all scripts, so
  even a cleaner miss cannot run code; the render page blocks eval, network and endless loops; section links
  are 10-minute signed tokens bound to workspace, document and module, and the editor server re-checks the
  workspace; agent modules are never served publicly.
- **Editor and domains (K3):** both sides check origin, window, nonce and shape, and never post to `"*"`;
  the editor page's security policy is tight; the editor server holds no app credentials and refuses
  modules from another workspace; custom-domain claims are protected; the hostname-move script is a dry run
  by default and all-or-nothing; the edge Worker's 14 tests pass.
- **Site turn and locks (K4):** every manual site write passes the agent-run lock; the agent's save refuses
  to overwrite a newer version and then writes nothing; Stop is checked before every model call and tool
  call; cited claims are workspace-scoped twice and fail closed; the site agent's permissions match the
  profile exactly.
- **Brand seam (K5):** the dock, the published render and the checker share one surface list; clones look
  the same in the editor and on the published page; the type-colour contrast of all six fixture kits is
  readable.
- **Publishing (K6):** web and site share one publish sequence; the address switch and per-page rows commit
  together; a dropped page stops serving; every page carries its revision's security policy and indexing
  header; both publish routes refuse during an agent run; no agent code can publish (by ruling).

---

## 9. Issues found and fixed while merging and testing (before the review)

These broke the merged branch outright and were fixed straight away, each with a test first.

| Commit | What was wrong |
|---|---|
| `639475541` | The site agent could not draw any page or section ("the page could not be drawn (TypeError)"): Lane B called the image inliner with a `cache` option that Lane A had removed. Restored. |
| `2ae9f44e0` | Brand surfaces beyond the six built-in ones (e.g. a brand's own "canvas" background) did not paint in the editor, because the editor's styles are compiled once at build time. The editor now writes each brand's own surface rules into the frame. |
| `4d61f96ea` | A site's Share menu published through the web-page route and read the web-page state. Sites now use the site routes. |
| `843e36beb` | Every checkout's page origin ran on port 8040, so lanes collided. Each checkout now uses its own port (trenton: 8049). |
| `83734f598` | A Lane A test relied on a temporary stub Lane B has since replaced. The test now installs the stub itself. |
| `ca2c66702` | A Lane B test still expected the brand file's old surface table; A9 added a classes column. |
| `ecdb283db` | A9's fix wave merged (K5-1). |

Details: `_memory/2026-10-13-wave2-integration.md`.

## 10. Failures that predate Wave 2 (recorded, not fixed)

These fail identically at the base `8c1aa9e47`, so they are not Wave 2's:

- `test_write_path_governance.py`: `lumen_api/asset_enrichment.py:51` calls `create_asset_record` outside the toolbelt.
- `test_api.py::test_reference_manifest_matches_config_contract_shape`: the asset record grew fields the test does not know.
- `test_workspace_seam_route_table.py`: `GET /assets/upload-capabilities` has no workspace check and no allowlist entry.
- `test_api.py` hangs: an ingestion wait loop with no deadline, made worse by leftover jobs in the test
  database `clue_trenton_wave1`. Clearing those jobs needs a write to the test database, which is the
  founder's call.
