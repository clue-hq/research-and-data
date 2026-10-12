# Wave 2 — what needs the founder's answer (2026-10-11)

The three lane plans are written, reviewed against the code, and committed (`6734c57bd`):
[Lane A](2026-10-11-lane-a-site-backend-and-publishing.md) (backend, renderer, publishing, the
pages-domain move), [Lane B](2026-10-11-lane-b-site-agent-on-platform.md) (the Puck agent on the
fleet) and [Lane C](2026-10-11-lane-c-site-editor.md) (the editor on its own domain). The master
plan's Wave 2 contracts carry every amendment.

Everything below is the founder's call. Each question has a recommendation; the plans are written
to it, so "all recommendations" is a complete answer, and any exception changes only the place
named. Nothing in Part 2 is written into the product before a yes.

## Part 1 — product questions

### What the review changed (one item to confirm)

- **R6. No model can save, undo, redo or publish a site directly.** The site's write, undo, redo and
  publish tools are called by the editor (as the person) and by the site turn's own code at the end
  of a request; no model is given them. Publishing a site is a person's act. (As first written, the
  plan granted them to the design agent without a profile, which would have stopped the platform
  API starting.) **Recommendation: confirm.** Granting publish to an agent later is a reviewed
  profile change.

### Lane A — backend and publishing

1. **What the Head of ABM's reads call a site.** (a) "site"; (b) "web", as for a WebDoc.
   **Recommendation: (b)** — the Head of ABM is unchanged by ruling and opened the leg as "web"; the
   gallery and editor still get "site".
2. **A published site page's head.** (a) Per page: title from the page's own title (else the
   document's), the workspace's default description and social image, the workspace favicon,
   `noindex` when asked. (b) As (a), but each page's description from its first paragraph.
   **Recommendation: (a)** for the first release.
3. **A "Button style" field (primary / secondary) on our own FeatureSplit and CtaBand.** It is a new
   editor control, so it needs your yes and a design. **Recommendation: yes, once you approve the
   control.** Not in the plan until then.
4. **Band and extra surfaces on our own sections.** (a) Agent-written sections get them; our own
   sections keep their six fixed choices. (b) Our sections' choices change per brand.
   **Recommendation: (a).**
5. **A cloned section retired ("deprecated") after a page used it.** (a) It still publishes (the web
   rule: a retirement never breaks published work). (b) Publish refuses it.
   **Recommendation: (a).**
6. **Settings → Pages refusal copy** after the move: today "Hostnames under cluehq.ai cannot be
   connected." **Recommended:** "Hostnames under Clue's own domains cannot be connected."

### Lane B — the agent

7. **`render_page`'s "console errors: 0".** The production render is static, so it is always 0.
   (a) Keep the spike's sentence as is. (b) Drop the clause (three wording changes).
   **Recommendation: (a).**
8. **The seller's own nav/footer clones and the two composed campaign shells in the agent's
   catalog.** (a) List everything the registry lists. (b) Leave them out (a site's header and
   footer come from `shell.json`, as in the spike). **Recommendation: (b).**
9. **A request that hits its limit (100 model calls or 30 minutes) with a valid page.** (a) Save it
   (one undo step) and say it stopped. (b) Save nothing. **Recommendation: (a).**
10. **The prompt's "Your four skills" line**, now that six skills ride (the two section skills are
    on by default). Text T3 in Part 2 proposes the new line. **Recommendation: approve T3.**

### Lane C — the editor

11. **The editor's registrable domain** (yours to register). (a) A new domain used only for editing,
    with wildcard DNS and certificate. (b) A subdomain of the new pages domain.
    **Recommendation: (a)** — what D2 decided. Until it exists, production shows "The website editor
    is not configured for this environment."; dev uses `editor.localhost`.
12. **Repeating fields (stats, nav links, list items) in the dock.** (a) Show each existing item's
    fields, grouped "<Field> <n>", no add/remove. (b) Hide them until designed. (c) Add/remove
    controls (needs a design). **Recommendation: (a).**
13. **Share, Publish and Export for sites before Lane A's publish and export land.** (a) Treat a site
    exactly like a web page in those menus (no workspace is in the site flag before Wave 4).
    (b) Hide them for sites until then. **Recommendation: (a).**
14. **Version rows in the action menu.** (a) "Current version / Version N", newest first, as
    designed. (b) Also who made it and when (needs a design). **Recommendation: (a).**
15. **Selecting the header or footer on the canvas.** (a) A 2px outline in Puck's own selection blue.
    (b) No outline; the dock's title says "Header". **Recommendation: (a)** (also design point DR5).
16. **A route typed into the URL bar that is not a page.** (a) Put the current route back, say
    nothing. (b) A line under the bar (needs a design). **Recommendation: (a).**

### How to run the plans

17. **Execution.** (a) Subagent-driven: a fresh Opus implementer per task, I review each one
    myself, then one whole-branch review. (b) Inline: I implement every task in this session, with
    one review at the end. **Recommendation: (a)** — 64 tasks across three lanes with many shared
    interfaces, and a shipped mistake in the security tasks (renderer, editor domain, section links)
    is costly.

## Part 2 — agent-facing text to approve (verbatim)

### Lane A Task 1 — the section check's refusals (ported word for word from the spike)

- `"<name>" reaches the page outside the section; a section renders its props and nothing else` (window, document, globalThis)
- `"<name>" is a network call; a section renders its props and nothing else` (fetch, XMLHttpRequest, WebSocket)
- `"<name>" runs code the check never saw; a section renders its props and nothing else` (eval, Function), and `"import(" loads code the check never saw; a section renders its props and nothing else`
- `"dangerouslySetInnerHTML" writes raw HTML; a section renders its props and nothing else`
- `"localStorage" reads the visitor's storage; …`, `"cookie" reads the visitor's cookies; …`, `"setTimeout" is a timer; a section renders once from its props; …` (and setInterval)
- `"<onX>" is an event handler; a section is static`

### Lane A Task 6 — three new refusals

- `<a> is not allowed in a section; write links with kit.Link (or kit.Button for a button) so they reach the right page wherever the site is published`
- `class "<class>" is not one of the brand's classes; the brand's colour classes are text-ink-*, bg-surface-*, text-on-surface-* and border-line-* (see brand/brand.md)`
- `a section id may use only letters, digits, "-" and "_" (up to 200 characters); "<id>" does not` (new from the review: the editor addresses a section by its id, so the id may not carry "#" or "."; every id the spike's agent wrote already complies)

### Lane A Task 7 — the brand.md template (angle brackets are filled from the kit; [bracketed] sections appear only when the kit has them)

```markdown
# Brand: <seller>

Every brand section takes its colours, type and buttons from these values. You choose by name
(for example `surface: "brand"`); you never write a colour or a size.

## Surfaces
| choice | kit name | name | colour | text on it |
|---|---|---|---|---|
| page | surface.page | Page | #F9FAF8 | text.primary #0E1110 |
| … one row for each of card, muted, brandSubtle, brand, inverse … |

[### More surfaces in this kit (for sections you write)
Our sections take only the six choices above. A section you write may also stand on these, with
`kit.Shell surface="<choice>"` or the classes `bg-surface-<choice> text-on-surface-<choice>`.
| choice | kit name | colour | text on it |
|---|---|---|---|
| canvas | surface.canvas | #FBFCFA | chosen by contrast |
| band-statement | surface.band.statement | #014036 | chosen by contrast |]

## Type roles
Each role is a pair of classes, `font-<role> text-<role>` (for example `font-title text-title`).
"measured" means the seller's own site showed it, for the fields listed; "derived" means the kit
worked it out from the measured roles.
| role | classes | font | size at 1440 | weight | line height | from |
|---|---|---|---|---|---|---|
| display | `font-display text-display` | Stix Two Text | 139px | 500 | 1.05 | derived |
| headline | `font-headline text-headline` | Stix Two Text | 87px | 500 | 1 | measured: family, size, weight, line height |
| … one row for each of title, subtitle, body, body.small, eyebrow, cta, stat, label, caption, legal … |

Our sections' headings choose from display, headline and title (`headingRole`).

[Headings on light surfaces use the brand's heading ink <colour>.]

## Buttons
- Primary: `kit.Button` (the default). The brand's primary button, measured from its own hero:
  background <colour>, text <colour>, radius <radius>, <weight> weight.
  (or, with no measurement: No measured button; the kit's own button is used (its brand colour
  fill, its pill shape).)
- Secondary: `kit.Button variant="secondary"`. The kit's <variant> recipe: <text token> label, a
  <border token> border in the same colour, <radius token>.
  (or, with no recipe: A plain outline: the text colour for the label and a 1px border in the same
  colour, with the primary button's shape.)
On dark surfaces both switch to their light versions automatically.

## Links
Write every link with `kit.Link` (a text link; `arrow` adds " →") or `kit.Button`, never a bare
`<a>`. A link to another page of this site is written `/` or `/<page>`; the kit points it at the
right address wherever the site is published.

[## The brand's own rules (from its brand kit)
Where a rule names a kit colour such as `surface.brand`, the matching choice is in the surfaces tables.
- <rule> (<scope>)
- …]

## Logos (always shown whole)
`kit.Image` shows a logo whole: never cropped, never rounded.
- `/asset-store/<sha256>`: <logo title>, <variant name>; on <allowed backgrounds>
- … (or: This kit has no logo files.)

## Assets (the only images and logos a page may use)
- `/asset-store/<sha256>` (<kind>, <asset id>): <description>
- …
```

### Lane B Task 0 — T1 to T15 (T15 is new from the review: what the person pointed at reaches the agent)

| # | Where | Today (spike, verbatim) | Proposed |
|---|---|---|---|
| T1 | `system_prompt.md`, "Your workspace", new line after the `fetched/` line | (none) | ``- `project-context/`: the project's own instructions and decisions, as they stood when this site was asked for.`` |
| T2a | `system_prompt.md`, "Your tools" | ``- `validate_page`: checks `page.json` and `shell.json`. It saves a version when the page is valid.`` | ``- `validate_page`: checks `page.json` and `shell.json`.`` |
| T2b | same | ``- `restore_version`: brings back a saved version.`` | ``- `restore_version`: brings back an earlier saved version of the site (`site.md` lists them).`` |
| T2c | same, new line after the `view_asset` line | (none) | ``- `search_assets`: finds the seller's other images (uploads, and images made for earlier pages) by what they show.`` |
| T3 | `system_prompt.md`, "How to work" step 1 | ``1. Your four skills are below this prompt: `account-page-copy`, `building-with-puck`,`` / `` `images-and-logos` and `page-review`. Follow them.`` | ``1. Your skills are below this prompt: `account-page-copy`, `building-with-puck`,`` / `` `images-and-logos` and `page-review`, and for new sections `writing-a-section` and`` / `` `rebuilding-a-section`. Follow them.`` (open question 4) |
| T4 | `skills/building-with-puck/SKILL.md:112` | ``If a change made the page worse, `restore_version` brings back the last good version.`` | ``If a change made the page worse, fix it, or bring back an earlier saved version with `restore_version` (`site.md` lists them).`` |
| T5 | `skills/images-and-logos/SKILL.md`, §1, new last bullet | (none) | ``- The seller's other images (uploads, and images made for earlier pages) are not in `brand/brand.md`. Find them with `search_assets`, and look at one with `view_asset` before you use it.`` |
| T6a | tool description `validate_page` | "Check page.json and shell.json against the components, the catalog, the brand and the evidence. Returns VALID (and saves a version) or INVALID with each error and its fix." | "Check page.json and shell.json against the components, the catalog, the brand and the evidence. Returns VALID or INVALID with each error and its fix." |
| T6b | tool description `restore_version` | "Bring back a version saved by validate_page into page.json, shell.json and pages/." | "Bring back the site as it was at an earlier saved version (site.md lists them) into page.json, shell.json and pages/." |
| T6c | tool description `view_asset` | "Look at up to four images (files from brand/brand.md, or images you generated), each with its description, before you choose one for a section." | "Look at up to four images (files from brand/brand.md, images you generated, or images search_assets found), each with its description, before you choose one for a section." |
| T6d | tool description `search_assets` (new) | (none) | "Search the seller's images by what they show and how they look. Write what you need in plain words, for example \"calm classroom, morning light\" or \"product dashboard screenshot\". Returns the best matches first (up to limit, 1 to 20), each with its file, type, title and a one-line description. Look at one with view_asset before you use it. kind narrows to image or logo." |
| T6e | tool description `render_page` | "Publish the site and return a desktop (1440 wide) …" | "Render the site and return a desktop (1440 wide) …" (the rest unchanged) |
| T7 | `validate_page` result when valid | "VALID. Saved as version {n} (restore_version can bring it back)." | "VALID." |
| T8a | `render_page` result, appended to the 1440 facts line when the renderer warns | (none) | " Render notes: {first three warnings joined by '; '}." |
| T8b | `render_page` result when the renderer fails | (none) | "NOT RENDERED: the page could not be drawn ({code}). Validate it and try again; if this repeats, say so in your report." |
| T9 | `site.md` (code-written), new last section, the 10 newest versions | (none) | "## Saved versions" / "Each request and each save in the editor is one version; `restore_version` brings one back." / `- version 4: "Make the hero warmer" (by the agent, 2026-10-11 14:02 UTC)` — the author is "the agent", "a person", or "an undo or redo" |
| T10 | `history.md` (code-written), new line after "- The reply:" | (none) | "- Saved: as version {n}" / "- Saved: nothing to save" / "- Saved: no, the site changed while this request ran" / "- Saved: no, the page was still invalid" / "- Saved: no, it was stopped" / "- Saved: no, the save was refused" / "- Saved: no, the request did not finish" |
| T11 | `catalog/index.md` line and `catalog/clones/<id>.md` (site-kit `catalog.ts`) | (none) | index line ends with " · degraded"; the clone card gets, after the "Source page:" line, a blank line and "Degraded: {the registry's degraded note}" |
| T12a | final message when the round limit stops a request | the spike's "Stopped: 40 model calls in one turn (safety stop)." | "Stopped: this request reached its limit of 100 model calls." |
| T12b | final message when the time limit stops a request | (none) | "Stopped: this request reached its limit of 30 minutes." |
| T12c | tool result for the 51st+ call of one response | (none) | "Not run: this was call {n} in one response, and only the first 50 run. Make it again in your next step." |
| T12d | chat summary when the user stops a request | (none) | "Stopped at your request. Nothing was saved." |
| T12e | chat summary when the page is still invalid after two reminders | (none) | "The page was still invalid, so nothing was saved: {first error}" |
| T12f | chat summary when the runtime crashed | (none) | "The website turn stopped because of an error, and nothing was saved." |
| T12g | chat summary when the governed write refused the site | (none) | "The website could not be saved: {reason}" |
| T12h | `generate_image` result when the image was made but could not be stored | (none) | "The image was made but could not be saved ({error}). Try once more, or choose a section without an image." |
| T13 | `write_section` error item when the props schema cannot be read in the render page | (none) | "the section could not be loaded to read its props ({code}: {the render page's reason}); check that it exports `schema` (a zod object with `id` and `surface`) and `render`" |
| T14 | FYI, no wording | — | The platform's compaction adds deepagents' `compact_conversation` tool to the agent's tools (as on the scene agent). Its description is deepagents' own. |
| T15 | the agent's message for a request where the person pointed at parts of the site (Task 13a), appended after their words | (none) | ``The person also pointed at parts of the site:`` / one line per part, in their order: ``- Page /analysis, the section with id "analysis-hero", its "title" field. Their note: "1. Make it warmer."`` (the header or footer reads ``- The header.`` / ``- The footer, its "ctaLabel" field.``; no note reads `` (No note.)``) / ``Work through these in the order listed. Change only these parts, unless their message asks for more. If a part is no longer on the site, say so in your report and use your judgement. In your report, say what you did for each part, or why you did not.`` |

### Lane B Task 14 — the design profile bump (an authority change)

> **design@v<N>** — design@vK plus two tools, nothing else moves (same prompt, model, workspace
> policy and limits):
> 1. `read_cited_claims@1` — the design API reads the claims a research page cites, by id, behind
>    the same display gate as every account read, and learns why each held one was held
>    (Contract 5). The site agent never calls it; its research files are built from it.
> 2. `design_record_site_section@1` — records one compiled website section the agent wrote (source,
>    module, CSS and the props schema read from the module in the hardened render page), per
>    workspace (Contract 4).
> Lane A's site writes and site publish stay granted to nobody (ruling R6): no model can save,
> undo, redo or publish a site directly.

## Part 3 — design review points (Lane C; built from existing chat-shell styles, flagged where nothing existing fits)

Built from existing chat-shell styles and primitives; where no existing style fits, the plan uses the closest existing tokens and records the point here instead of inventing a look. Each is marked `DESIGN REVIEW` in the code comment that implements it.

- **DR1** The Pages toggle's placement: first item of the header's action group (Ploy puts it at the far left of the toolbar). Uses `.artifactActionButton` + `.artifactActionButtonActive` and lucide `FilesIcon`.
- **DR2** The page panel: 280px column left of the canvas; container, head and list classes are new (`.sitePagesPanel*`) but use only `--chat-shell-*` tokens; rows reuse `.layerRow*`; search reuses `InspectorInput`; the count reuses `.inspectorFieldLabel`.
- **DR3** The URL toolbar: back/forward reuse `.deviceButton`; the route field is a new `.siteUrlField` built from `.artifactHeadingRenameInput`'s tokens; reload reuses `.deviceButton`; the existing device menu is moved inside the bar unchanged.
- **DR4** The dock's section label "Content" for a selected site section (the web lane says "Component properties", which the marketer must not see).
- **DR5** The header/footer selection outline on the canvas (question 15).
- **DR6** Repeating fields grouped as "<label> <n>" (question 12).
- **DR7** An image field: the existing "Replace image" pill (`InspectorImageUpload`) with the ad lane's generate rows (`AdImageAiRows`) stacked under it.

## Founder answers (recorded as given)

- 2026-10-12 — **Q1:** (b) the Head of ABM's reads say "web" for a site; the gallery and the editor
  still get "site". (Lane A Task 10 Step 5 as written.)
- 2026-10-12 — **Q2:** (a) per-page head for the first release. (Lane A Task 20 as written.)
- 2026-10-12 — **Q3:** the general version, superseding the "Button style: primary / secondary"
  question. No single "secondary" picked in code: the site agent gets the kit's own button recipes
  (as the web and ad agents already do), `kit.Button look="<recipe>"` draws a recipe from its
  tokens, the validator only checks the recipe exists in the kit, FeatureSplit gets a "Button
  style" field listing this brand's styles, and nothing is invented for a brand that draws one style.
  Pending: the brand.md wording, what is drawn for a part with no kit colour, and whether CtaBand
  also gets the field. Lane A Tasks 4, 5 and 7 are rewritten once those are answered.
- 2026-10-12 — **Q3 follow-ups:**
  - Missing-colour rule = **(b)**: the extraction saves each button style's exact measured colours
    ("thoroughly implement it and test it carefully"); kits not yet re-extracted fall back to token
    values and brand.md says so. Re-extraction of existing kits needs the founder's go per kit.
  - **No hard-coded style values** in site-kit: buttons and every other brand-styled element draw
    the brand kit's own values (measured first, tokens second); a fallback only where the kit has
    neither, and named.
  - **Button states**: rest, hover, pressed, focus and disabled are to be captured per button style
    and used in the CSS. Today the capture reads rest only (plus one generic focus-ring sample).
  - The agent's `buttonLook` description: approved. CtaBand gets the field too (taken as yes).
  - A plan section replacing Lane A's brand-fidelity block (Tasks 4–7) plus the extraction work is
    being drafted; it comes back for review with the final brand.md wording.
  - **Motion and behaviour** (2026-10-12): capture every behaviour and animation the site shows —
    transitions, state changes (hover/pressed/focus), keyframe animations, CSS reveal-on-scroll; and
    for each measured style letter-spacing, case, underline, transforms, cursor, icons. Clones carry
    these already; the measured values serve agent-written sections. Only CSS motion is usable on a
    script-free published page; JavaScript-driven effects are recorded as notes, not reproduced.
- 2026-10-12 — **Brand-scoped tokens** (founder's design, replaces "store raw values beside each
  recipe"): code walks every measured style and property in every state; an exact match to an
  existing token in this kit is reused, otherwise a new token is added to THIS brand's kit only,
  with a stable code-made name from where it was measured (e.g. `button.solid-2.fill`) and its
  provenance. Recipes then name those tokens, so documents and agents keep naming tokens only.
- 2026-10-12 — **Q4:** (b) our four sections' Surface field lists the six standard surfaces plus this
  brand's own extra surfaces, including the measured section colours minted as brand-scoped tokens;
  the validator checks the choice exists in the brand's kit (like Button style). The dropdown's
  labels for extra surfaces follow a readable rule, brought back with the plan for approval.
- 2026-10-12 — **Q5:** (b) publish refuses a page that uses a retired (deprecated) section; only
  approved sections publish. Pages already live stay live. Found with it, to fix in the plans:
  - The brand data the editor, the save check and the renderer use lists approved sections only
    (`agent_cloned_sections.py:485-505`, Lane B Task 8), so a section retired after a page used it
    would break that page's canvas and refuse every save, not just publish. Ruling: the brand data
    carries every section the page itself uses, whatever its status; the agent's catalog (what it
    may newly place) stays approved-only. Publish then applies Q5.
  - Publish refusal messages reach the marketer verbatim (`webDocuments.ts:2073`), and Lane A's
    current wording says "cloned section frag_…". New wording (no "clone", the section's own name)
    awaits approval, with a site.md line so the agent knows which section to replace.
- 2026-10-12 — **Q5 revised:** retiring sections is **out of scope for the site lane**. A retired
  section is treated like any other: it still draws, saves and publishes (option (a)); no special
  handling, no retirement message, no site.md section. Live published pages are never affected.
  Kept: the brand data carries every section the page itself uses, whatever its status (also needed
  when a repair supersedes an original); the agent's catalog stays current-only.
  **Approved publish messages** (replacing Lane A's "cloned section frag_…" wording):
  - not approved yet: `This page uses a section that isn't approved yet: "<section name>". Approve your brand kit, then publish again.`
  - not in the library: `This page uses a section that isn't in your brand's library. Ask the agent to replace it, then publish again.`
- 2026-10-12 — **Q6:** approved: "Hostnames under Clue's own domains cannot be connected." (Lane A
  Task 23 Step 9, now unconditional.)
- 2026-10-12 — **Q7:** (b) `render_page` drops the console-errors fact (the production screenshot runs
  no script); section crashes arrive as render notes or NOT RENDERED. Approved wording: the facts
  line (T16a), the tool description (T6e) and the page-review skill's first paragraph (T16b).
