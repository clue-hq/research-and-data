# Site element inspector, plan 6: headers and footers as editable templates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (the founder's rule since 2026-10-17: the plan is implemented directly, one whole-branch review at the end). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A microsite's one header and one footer stop being fixed code. Each is a section, stored once in `site.shell` and drawn around every page. It can be:
- a template the extraction derived from the seller's own top bar or footer and made ABM-focused;
- today's header or footer (the fallback);
- the agent's own section.

The marketer edits it in place like any section: every word, word-level styling, logos (from the asset library), Arrange and Visibility. The header can also stay at the top while scrolling and sit see-through over the first section. Everything plans 1–5 built works in it.

**Architecture:**
- **Shape.** `site.shell` becomes `{header: {type, props}, footer: {type, props}}`, entries shaped like page sections, with the reserved ids `header` and `footer`.
- **Drawing.** Every renderer (the editor's Puck data, the static render, a live page on the server and in the browser) puts the two entries first and last in the page's `content` before drawing. They go through the same section machinery as page sections: the `_edits` scope, keys, rich text, clone filling, the agent-section boundary. The page root stops drawing a shell of its own.
- **Editor.** The frame splits the header and footer back out of Puck's data when it saves. It reports their selection as the `shell` target, so the app, annotations and Layers keep their addressing.
- **Templates.** Derived in Python from the kit's captured `nav` and `footer` fragments. A deterministic pass prunes the seller's menus, drawers and extra links, inserts the account's logo and line, and marks the menu. They are minted through the same fragment door as repairs and released at once (founder: no approval gate).
- **The menu.** The menu of the site's own pages is filled when the page is drawn.

**Tech Stack:** TypeScript, React 19, Puck 0.23.0 (pinned), Zod 4, node-html-parser, node:test via tsx; Python 3, selectolax, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-18-site-header-footer-templates-design.md` (the authority for plan 6), within `docs/superpowers/specs/2026-10-17-site-element-inspector-design.md` §7 (status, scope, change log). Update §7.1 when this plan starts and finishes, and §7.7 for each ruling below once the founder approves it.

## Rulings (decisions this plan makes where the design leaves a choice — for the founder to check)

- **R1 — The stored shape.** `site.shell = {header: {type, props}, footer: {type, props}}`. Each `props.id` is `"header"` or `"footer"`, matching its place. `type` is one of:
  - `ClonedSection`: a template or any copied section;
  - `SiteHeader` (header only) or `SiteFooter` (footer only): today's, rewritten (R7);
  - one of the site's agent sections.

  A page section may not use the id `header` or `footer`, and may not be a `SiteHeader` or `SiteFooter`. A site whose stored shell is in the old shape (no `type`) draws no header or footer until the agent rewrites it. There is no migration (founder: no real customer yet).
- **R2 — One drawing path.** `pageWithShell(page, shell)` puts the header entry first and the footer entry last in `content`. It is used by:
  - the editor's Puck data;
  - the static render;
  - the live page's stored page data (so server and browser draw the same tree).

  The header and footer therefore get the section scope box (`data-clue-section="header"`), `_edits`, clone filling, the agent boundary, and Puck selection and in-place editing, with no shell-only code. The old scopes `shell-header` and `shell-footer` are retired.
- **R3 — The editor keeps the `shell` address.** A selection, click, annotation or highlighted words in the `header` or `footer` item is reported as target `shell` (`site:shell#header`), as today. Puck's `onChange` is split back:
  - the first and last items with those ids go to `site.shell`;
  - the rest go to the page.

  A dock or panel change to the shell refreshes Puck's data, as a page change does.
- **R4 — Templates are copied sections** (`ClonedSection` with `section_role` `site_header` or `site_footer`), so plans 1–5's clone tools edit them unchanged. They are derived as follows:
  - **When.** Once per brand kit: at extraction, after the sections are minted, and by an offline script for the kits that already exist.
  - **From what.** The kit's captured `nav` and `footer` fragments: the home page's when there is one, otherwise the shortest page path. A degraded fragment is never used.
  - **No approval gate.** They are minted through the repair door (sanitize, annotate, scope the CSS against the source, content-address, insert) and released `approved` at once (founder 2026-10-18).
  - **When nothing usable is found.** No template is made, and the agent uses `SiteHeader` or `SiteFooter`.
- **R5 — How a header template is derived** (deterministic; no model):
  1. **Remove** the parts that only work with the seller's JavaScript or lead away:
     - elements with `hidden`, `data-closed`, `role="dialog"`, or `aria-haspopup`;
     - dropdown lists and dropdown toggles (an element with `aria-expanded`, and Webflow's `w-dropdown`);
     - buttons and `role="button"` elements with no text (menu toggles, hamburgers);
     - `form`, `input`, `select`, `textarea`, `iframe`, `noscript`.
  2. **Logo.** The first link holding an `img` or `svg` whose `href` is `/`, empty or the seller's root, or else the first `img`/`svg`. No logo means the header is not derivable.
  3. **Menu.** The element (outside the logo) with the most direct children that are, or hold, one link, at least two. A `nav` wins a tie. It is marked `data-clue-menu`. Its first child that is a plain link item stays as the pattern (`data-clue-menu-item`, with its deepest text element marked `data-clue-menu-label`); its other children go.
  4. **Button.** Of the links and buttons left outside the logo and menu, the last whose words are not "Log in", "Login", "Sign in" or "Sign up" stays as the one call to action. The others go.
  5. **Prune.** Any element that holds none of the kept parts and holds text, a link, a button or an image is removed. Empty decorative elements (backgrounds, overlays) stay.
  6. **Account.** Right after the logo link, insert:
     - a wrapper `<span class="clue-account" data-lumen-slot="account_shown">` holding a divider (`<span class="clue-account-rule" aria-hidden="true">`) and the account's logo (`<img class="clue-account-logo" data-lumen-slot="account_logo">`, its `src` the co-brand placeholder);
     - then the account line `<span class="clue-account-line" data-lumen-slot="account_line">`, which takes the menu link's `class` (so it has the seller's nav type).

     The account's logo takes the seller logo's `height` attribute when the logo is an `<img>` that has one, else `1.75em`. These few rules ship as the template's own CSS.
  7. **Slots.** Every old `data-lumen-slot` is stripped and the slots are found afresh:
     - the mint's own detector, on the pruned markup;
     - `account_shown` (visibility), `account_logo` (image), `account_line` (text, fallback "Prepared for you");
     - every text element still without a slot becomes a `text_<n>` slot, so every word can be changed in place.
- **R6 — How a footer template is derived.**
  1. The same removals as R5 step 1.
  2. Keep:
     - the logo (R5 step 2);
     - the legal row: the smallest element holding a text with "©", "copyright" or "all rights reserved" together with links whose words or `href` name privacy, terms, cookies or legal; when no such element exists, the copyright text alone.
  3. Prune as R5 step 5, so link columns, newsletter forms, social icons and badges go.
  4. Slots as R5 step 7 (no account parts).

  No legal row and no logo means the footer is not derivable.
- **R7 — `SiteHeader` / `SiteFooter` rewritten so every word is the marketer's.**
  - **Header props:** `accountLine` (rich, no links; replaces `preparedFor`; the fixed "Prepared for" goes), `accountLogo`, `accountLogoAlt`, `logo` (optional; empty means the kit's logo, so the seller's logo can be replaced), `logoAlt`, `ctaLabel`, `ctaHref`, `ctaNewTab`, `ctaLook`, `menuLabels`, `menuExtra`, `_edits`. `nav` is retired (the menu is R8's).
  - **Footer props:** `legal` (rich), `logo`, `logoAlt`, `privacyLabel` and `termsLabel` (rich, no links; empty draws "Privacy policy" / "Terms"), `privacyHref`, `privacyNewTab`, `termsHref`, `termsNewTab`, `_edits`.
  - **Keys:** header `root`, `root.inner`, `brand`, `logo`, `divider`, `accountLogo`, `accountLine`, `actions`, `menu`, `menu.<page>`, `ctaArea`, `cta`; footer `root`, `root.inner`, `logo`, `legal`, `links`, `privacy`, `terms`.

  Their words edit in place as our sections' do (Puck rich fields).
- **R8 — The menu lists the site's pages, filled when the page is drawn.**
  - **Order.** `/` first, then the other pages alphabetically (`siteRoutes`'s order).
  - **Keys.** `menu._home` for `/`, `menu.<name>` for `/<name>`. Page names never start with `_`, so these keys are stable when pages are added or removed.
  - **Labels.** The entry's `menuLabels[<_home|name>]`, else "Overview" for `/`, else the page name with dashes as spaces and a capital first letter.
  - **Extra links.** `menuExtra` (up to 6 `{label, href, newTab?}`, keys `menu._<n>`) are drawn after the pages. This is how the agent keeps chosen seller links on a one-to-few or one-to-many site; its skill says when (founder: the agent's judgement).
  - **One-page sites.** A site with one page draws no page items.
  - **Labels are plain text:** edited in place, styled as whole elements, never word by word.
  - **Where it is drawn.** In a template, the marked pattern item is repeated, one copy per item, each copy keyed as above (before `order` is applied). `SiteHeader` draws the same items. Agent sections get the items as `kit.menu`.
- **R9 — Phones.** Below 768px every `[data-clue-menu]` is hidden (and `SiteHeader`'s menu, as today), leaving the logos, the account line and the button. No drawer is built (founder 2026-10-18).
- **R10 — See-through and sticky.** Two new header-only `_edits` facts on the header's `root` key:
  - `sticky: true`: the header's section box becomes `position: sticky; top: 0`;
  - `overlay: true`: the box takes no height, so the first section starts under the header.

  The section box carries `data-clue-sticky` / `data-clue-overlay`, and one static stylesheet draws them. In the editor the same rules apply to Puck's item wrapper. "Opacity" is the existing fill with opacity on the header's own box (plan 3/4). The footer, and any other key, refuse both facts.
- **R11 — In the header and footer, plans 1–5 work as on any section:**
  - text: rich text, word styles and links;
  - buttons and boxes: their panels;
  - images: Replace from the library (the seller's logo too, via `logo` or the template's image slot);
  - Arrange: copied sections and `SiteHeader`/`SiteFooter` reorder through `order`; an agent's header is fixed, as on pages;
  - Visibility: hiding stays header- and footer-only and works for every type.

  Two notes are retired: "Words in the header and footer are styled as a whole for now…" and "Text in the header and footer cannot become a link yet." A page menu item's link is fixed, with "This link opens the site's <label> page; the menu follows the site's pages." A `menuExtra` link edits `menuExtra.<n>.href`.
- **R12 — The panel.** When the header itself is selected (blank space in it, or its Layers row), its box panel gains a **Header** group with two checkboxes:
  - "Stays at the top while scrolling";
  - "Sits over the first section". While it is on, the note reads: "The first section now starts under the header. If its words sit under the header, give it more top padding."

  The footer's panel gets no such group.
- **R13 — The catalog** (`catalog/index.md`) lists templates in their own first section, "Header and footer templates (use them in shell.json)", and leaves them out of the seller's page sections. The older ABM pair and the seller's own `nav`/`footer` bands stay listed as they are (founder: retired later, in one step).

## Global Constraints

- Puck stays pinned at `@puckeditor/core` 0.23.0; no new dependencies.
- No free CSS: every value passes the strict override schema; templates carry only captured CSS plus R5's fixed account rules.
- `site-kit/src/sections.tsx` and `shell.tsx` carry no style values (`test/style-literals.test.ts`).
- Element keys never shift: a clone's keys come from its captured markup; menu keys come from page names (R8).
- A control that cannot act is shown disabled with a one-line note, never live and inert. Every change is one save and one undo step.
- The header is drawn on every page: a shell the save check refuses is never saved, and never published.
- Templates never come from a model; derivation is deterministic (R5, R6). No live brand extraction runs without the founder's yes and a time estimate; the existing kits are derived offline from stored captures.
- No new runtime flag. Nothing outside `subsystems/clue-design/` imports design internals.
- Tests: named files only; never the `subsystems/clue-design/apps/api/tests` folder; never `*_live.py` or broad suites with real keys. Python runs through `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh <file>`. Browser tests use `CLUE_SITE_EDITOR_BROWSER=1` after `npm run build -w @clue/site-kit && npm run build -w @clue/site-editor` (from `apps/frontend`, with the stack down).
- Skill and prompt text is shown to the founder before it is written (Task 10).
- Commits: local only (push only when asked), no AI attribution, explicit paths, never `git stash`.

## Review Focus

1. **A page added after the header was written.** Expected: the published menu and the editor's menu both list it at once, keyed `menu.<name>`; an existing `menuLabels` or `_edits` entry for another page still points at that page. Pinned in Task 4 (filler) and Task 9 (scenario).
2. **Typing in a template's account line, then undo, then publish.** Expected: Puck's data, `site.shell.header.props.slots.account_line` and the published page agree after each step; the page sections are untouched by the shell edit, and vice versa. Pinned in Task 5 (split) and Task 9.
3. **Sticky and overlay together, in the editor canvas and on the published page.** Expected: the header stays at the top while the canvas (`#root`) or the window scrolls; the first section starts at the header's top; turning both off restores the old layout exactly. Pinned in Task 3 (CSS) and Task 11 (browser).
4. **A real seller header with a mega-menu, a mobile drawer, a Login link and two buttons (Conduit, Garner).** Expected: the derived template has one logo, the account wrapper right after it, one marked menu pattern, one button (the last non-login one), and nothing hidden or JavaScript-only. It is not derivable when there is no logo. Pinned in Task 7 (fixtures) and Task 8 (dry run on the stored captures).
5. **An old-shape shell (`{header: {preparedFor…}}`) opened in the editor and published.** Expected: no crash; no header or footer drawn; the save check names `shell.json` and how to fix it. Pinned in Task 1 and Task 3.

---

### Task 1: The contract — shell entries, header facts, the save check

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/site-document.ts` (`ShellEntrySchema`, `SiteShellSchema`, `SHELL_IDS`)
- Modify: `apps/frontend/packages/site-kit/src/schemas.ts` (`ShellSchema` retired; `SiteHeaderSchema`, `SiteFooterSchema`; `MenuLabelsSchema`, `MenuExtraSchema`; ClonedSection `menuLabels`, `menuExtra`; `RICH_PROPS`/`RICH_PROPS_NO_LINKS` gain SiteHeader/SiteFooter)
- Modify: `apps/frontend/packages/site-kit/src/edits.ts` (`sticky`, `overlay`; `SHELL_ONLY_PROPS`)
- Modify: `apps/frontend/packages/site-kit/src/validate.ts` (the per-item check becomes one function used for page items and both shell entries)
- Modify: `apps/frontend/packages/site-kit/src/editor-site.ts` (`componentEntry`; `componentProps`/`withComponentProps` on shell entries)
- Test: `apps/frontend/packages/site-kit/test/validate-site.test.ts`, `test/edits.test.ts`, `test/editor-site.test.ts`, `test/contracts.test.ts`; shared fixture helper `test/fixtures/shell.ts`

**Interfaces:**
- Produces (`site-document.ts`):
  - `SHELL_IDS = ["header", "footer"] as const`;
  - `ShellEntrySchema = z.looseObject({ type: z.string().min(1).max(200), props: z.looseObject({ id: z.enum(SHELL_IDS) }) })`;
  - `SiteShellSchema = z.looseObject({ header: ShellEntrySchema, footer: ShellEntrySchema })`;
  - `type ShellEntry`.
- Produces (`editor-site.ts`): `componentEntry(site: SiteDocument, target: SiteTarget, componentId: string): { type: string; props: Record<string, unknown> } | null` (a shell entry for target `shell`, otherwise the page item). `componentProps` and `withComponentProps` read and write `shell[part].props`, keeping `type` and `props.id`.
- Produces (`schemas.ts`):
  - `MenuLabelsSchema = z.record(z.string().regex(/^(_home|[a-z0-9][a-z0-9-]*)$/), text.min(1).max(60))`;
  - `MenuExtraSchema = z.array(z.object({ label: text.min(1).max(60), href: link, newTab: z.boolean().optional() }).strict()).max(6)`;
  - `SiteHeaderSchema` and `SiteFooterSchema` with R7's props;
  - `RICH_PROPS.SiteFooter = ["legal"]`; `RICH_PROPS_NO_LINKS.SiteHeader = ["accountLine", "ctaLabel"]`; `RICH_PROPS_NO_LINKS.SiteFooter = ["privacyLabel", "termsLabel"]`.
- Produces (`edits.ts`): `StyleOverrideSchema.sticky?: true`, `overlay?: true`; `SHELL_ONLY_PROPS = ["hidden", "sticky", "overlay"]`.
- Produces (exact refusals; `<at>` is `shell.header` or `shell.footer`):
  - `shell.json: the header and footer are sections: {"header": {"type": …, "props": {"id": "header", …}}, "footer": {…}} (building-with-puck skill)`;
  - `<at>.props.id: must be "header"` (or `"footer"`);
  - `<at>.type: SiteFooter is the footer's; the header is SiteHeader, a ClonedSection or one of this site's sections`, and the mirror for the footer;
  - `<page>.content.<n>(<id>).id: "header" and "footer" are the header's and footer's ids; use another id`;
  - `<page>.content.<n>(<id>).type: SiteHeader and SiteFooter belong in shell.json`;
  - `<at>._edits.<key>: sticky and overlay are for the header itself (its root)`.

- [ ] **Step 1: Write the failing tests** in `validate-site.test.ts`:
  - `a shell of two section entries is valid`: header `ClonedSection` (a fixture clone), footer `SiteFooter`; valid.
  - `the old shell shape is refused with how to fix it`: `{header: {preparedFor: "x", …}, footer: {legal: "y"}}` gives the exact `shell.json:` message.
  - `shell ids and types are checked`: a header id `"top"`; a header of type `SiteFooter`; a page item with id `header`; a page `SiteHeader`. Each gives its exact message.
  - `shell entries get every page item check`: a header clone with an unknown slot, a bad image, a link to a missing page and a `menuExtra` link to `/nowhere` gives the same messages as on a page, at `shell.header.…`.
  - `account logos are allowed in any shell image`: an account logo in a header clone's `account_logo` slot is accepted; the same file on a page clone is refused.
  - `sticky and overlay are the header root's`: `header._edits.root.sticky` is accepted; `header._edits.cta.sticky` and `footer._edits.root.overlay` are refused with the exact message.
  - `an agent section may be the header`: header type `SiteHeaderAcme` (in `agentSections`) is valid.

  In `edits.test.ts`, `sticky and overlay parse only as true`.
  In `editor-site.test.ts`, `componentEntry and componentProps read a shell entry; withComponentProps keeps its type and id`.
- [ ] **Step 2: Run; expect FAIL.** `cd apps/frontend/packages/site-kit && npx tsx --test test/validate-site.test.ts test/edits.test.ts test/editor-site.test.ts`
- [ ] **Step 3: Implement.** Extract the page-item loop body of `validateSite` into `checkItem(item, at, { shell: "header" | "footer" | null })`, and call it for each page item and each shell entry. Shell entries are schema-checked by type with the same agent schemas as pages. The image allowance is `imageAllowed(value) || (shell && accountLogos.has(value))`. Every existing test fixture that builds a shell moves to `test/fixtures/shell.ts` (`fallbackShell(overrides?)` returns `SiteHeader`/`SiteFooter` entries); this updates the tests listed by `grep -rl preparedFor apps/frontend` in the same commit.
- [ ] **Step 4: Run** the three files plus `test/contracts.test.ts`, `test/a9-scenarios.test.tsx` and `test/multipage.test.ts`; expect PASS.
- [ ] **Step 5: Commit:** `site-kit: header and footer as section entries in the site contract (inspector plan 6)`.

### Task 2: The server reads the new shape

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/workspace.py` (`site_components`, `read_site_files` pins shell agent sections, `_is_site_part`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_publish.py` (`_clone_ids`, `_library_families_used`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_workspace_view.py` (`pinned_site_clones`)
- Modify: `platform/api/clue_api/design_turn_targets.py` (`_site_component_props` returns the entry's `props`)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_site_workspace.py`, `tests/api/test_design_turn_targets.py`, `subsystems/clue-design/apps/api/tests/test_site_publish_package.py` (clone pins, library fonts), `subsystems/clue-design/apps/api/tests/test_site_workspace_view.py` (pinned clones)

**Interfaces:**
- Produces: `site_components(site: Mapping) -> Iterator[tuple[str, dict]]`, yielding `(route, item)` for every page item and `("shell", entry)` for each well-formed shell entry (one with a `type` and a `props` mapping). It is the one walk the API and the agent runtime use.

- [ ] **Step 1: Write the failing tests:**
  - `test_read_site_files_pins_a_shell_agent_section`: shell.json header type `SiteHeaderAcme`; `agent_sections` contains it.
  - `test_targets_name_shell_entries_by_props`: `site:shell#header.accountLine` resolves its field from `shell.header.props`.
  - `test_publish_checks_shell_clone_pins`: a draft template in `shell.header` raises `site_publish.clone_not_approved`.
  - `test_pinned_clones_include_the_shell`: a superseded template used only by the shell is loaded with `in_catalog: False`.
  - `test_library_fonts_scan_shell_props`: a library font named in `shell.footer.props._edits` ships.
- [ ] **Step 2: Run each; expect FAIL** (`pytest-keyless.sh <file>`).
- [ ] **Step 3: Implement** with `site_components` at every walk (the API imports it from `lumen_agent.site.workspace`, as `site_workspace_view` already does); `design_turn_targets` gets its own three-line change.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit:** `site: the server reads header and footer entries (inspector plan 6)`.

### Task 3: Drawing — the shell as the page's first and last section

**Files:**
- Create: `apps/frontend/packages/site-kit/src/shell-entries.ts` (`pageWithShell`, `withEditedShellPage`, `isShellEntry`)
- Modify: `apps/frontend/packages/site-kit/src/config.tsx` (`ConfigOptions.shell` and `mode` removed; `menu` added; `SiteHeader`/`SiteFooter` registered as components with rich fields, in no insert category; `BrandRoot` draws no shell; `SectionScope` sets `data-clue-sticky` / `data-clue-overlay`)
- Modify: `apps/frontend/packages/site-kit/src/shell.tsx` (R7 props and keys; `logo` overrides the kit's; labels default)
- Modify: `apps/frontend/packages/site-kit/src/theme.ts` (the static placement and phone rules, once per page)
- Modify: `apps/frontend/packages/site-kit/src/render-core.tsx`, `live-page.tsx` (draw `pageWithShell`; `LivePageData.shell` removed; `brandForPage` and `cloneStylesheet` then cover the shell's clones by themselves)
- Modify: `apps/frontend/packages/site-kit/src/index.ts` (exports)
- Test: `test/render-core.test.tsx`, `test/live-page.test.tsx`, `test/element-keys.test.tsx`, `test/sections.test.tsx`, `test/style-literals.test.ts`, new `test/shell-entries.test.ts`

**Interfaces:**
- Produces:
  - `pageWithShell(page: SitePage, shell: SiteShell | null): SitePage`, the same object when the shell is null or either entry is not well-formed;
  - `withEditedShellPage(site: SiteDocument, route: string, edited: SitePage): SiteDocument`, where an item with id `header` at index 0 and one with id `footer` at the end go to `site.shell`, and the rest is the page;
  - `isShellEntry(value: unknown): value is ShellEntry`.
- Produces (CSS, in `themeCss`):
  - `.clue-section[data-clue-sticky]{display:block;position:sticky;top:0;z-index:40}`;
  - `.clue-section[data-clue-overlay]{display:block;height:0;overflow:visible;position:relative;z-index:40}`;
  - `.clue-section[data-clue-sticky][data-clue-overlay]{position:sticky}`;
  - `@media (max-width: 767px){[data-clue-menu]{display:none!important}}`.

- [ ] **Step 1: Write the failing tests:**
  - `shell-entries.test.ts`: `pageWithShell` puts the header first and the footer last, and leaves an old-shape shell's page unchanged. `withEditedShellPage` round-trips (`withEditedShellPage(site, "/", pageWithShell(page, shell))` deep-equals `site`), and an edit to item 0 changes only `site.shell.header`.
  - `render-core.test.tsx`: `the header and footer are the page's first and last sections`. The static and the live render of a two-page site both start the body with `data-clue-section="header"` and end with `data-clue-section="footer"`. A template header's clone CSS is in the live page's `data-clue-clones` stylesheet. An old-shape shell renders the page with neither.
  - `live-page.test.tsx`: `a live page with a template header hydrates with no mismatch` (the hydration check the existing tests use).
  - `element-keys.test.tsx`: the R7 keys for `SiteHeader`/`SiteFooter`. The account line has no fixed words. `logo` set to a site image draws that file.
  - `sections.test.tsx`: `sticky and overlay set the section box's attributes`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** `makeConfig` no longer takes a shell. Callers (`render-core`, `liveConfig`, the editor in Task 5) pass `menu` (Task 4) and draw `pageWithShell`. In `SectionScope`, read `edits.root?.sticky` / `edits.root?.overlay`.
- [ ] **Step 4: Run** the files above plus `test/style-literals.test.ts`, `test/hydration-spike.test.tsx`, `test/a9-scenarios.test.tsx`; expect PASS.
- [ ] **Step 5: Commit:** `site-kit: the header and footer drawn as the page's first and last sections (inspector plan 6)`.

### Task 4: The menu, and the shell's link and image sources

**Files:**
- Create: `apps/frontend/packages/site-kit/src/site-menu.ts` (`siteMenuPages`, `menuItems`, `menuKey`)
- Modify: `apps/frontend/packages/site-kit/src/clone.ts` (`CloneExtras.menu`; expand the marked pattern after keying, before `applyOrder`)
- Modify: `apps/frontend/packages/site-kit/src/config.tsx` (ClonedSection passes `menu` in extras when its clone has `[data-clue-menu]`; `makeKit` gets `menu`)
- Modify: `apps/frontend/packages/site-kit/src/agent-kit.tsx` (`kit.menu`)
- Modify: `apps/frontend/packages/site-kit/src/shell.tsx` (`SiteHeader` draws `menuItems`, ordered by `order.menu`)
- Modify: `apps/frontend/packages/site-kit/src/rich-props.ts` (`ownLinkSource` for `menu._<n>` on any shell entry; `richSourceOf` for SiteHeader/SiteFooter rich props)
- Modify: `apps/frontend/packages/site-kit/src/image-sources.ts` (shell `logo` props replaceable; `SELLER_LOGO` used no more)
- Test: `test/site-menu.test.ts` (new), `test/clone-editing.test.tsx`, `test/rich-props.test.ts`, `test/image-sources.test.ts`, `test/agent-kit.test.tsx`

**Interfaces:**
- Produces:
  - `type MenuPage = { route: string; key: string; label: string }`;
  - `siteMenuPages(pages: Record<string, unknown>): MenuPage[]` (R8 order, keys and default labels; `[]` for a one-page site);
  - `type MenuItem = { key: string; label: string; href: string; newTab?: boolean; source: { kind: "page"; route: string } | { kind: "extra"; index: number } }`;
  - `menuItems(pages: MenuPage[], props: { menuLabels?: Record<string, string>; menuExtra?: { label: string; href: string; newTab?: boolean }[] }): MenuItem[]`;
  - `menuKey(route: string): string` (`menu._home` / `menu.<name>`).
- Produces: `CloneExtras.menu?: MenuItem[]`. Each item is a copy of the `[data-clue-menu-item]` pattern, with `data-clue-el` = the item's key, the anchor's `href` and `target`/`rel` per `newTab`, the `[data-clue-menu-label]` text = the label (escaped), and `data-clue-menu-source="page:<route>"` or `"extra:<n>"`. The pattern is removed; with no items, the container stays, empty.
- Produces: `kit.menu: MenuItem[]` (the site's pages only, default labels).
- Produces (exact copy): `PAGE_MENU_LINK = "This link opens the site's <label> page; the menu follows the site's pages."`; `ownLinkSource(type, "menu._<n>")` = `{ kind: "prop", href: "menuExtra.<n>.href", newTab: "menuExtra.<n>.newTab" }` for SiteHeader and ClonedSection; `imageSourcesOf` gives SiteHeader/SiteFooter `logo` = `{ kind: "prop", prop: "logo", uses: 1 }`.

- [ ] **Step 1: Write the failing tests:**
  - `site-menu.test.ts`: pages `/`, `/roi-analysis`, `/team` give keys `menu._home`, `menu.roi-analysis`, `menu.team` and labels `Overview`, `Roi analysis`, `Team`. `menuLabels` renames one. `menuExtra` appends `menu._0`. A one-page site gives only extras.
  - `clone-editing.test.tsx`: `a template's menu repeats its pattern per page`. Three items with those keys, hrefs and labels; an `order` on the container's key reorders them; a label `A & <b>` is escaped; keys of elements after the menu are unchanged from the fill without a menu.
  - `rich-props.test.ts`: `menuExtra links and SiteHeader rich props have sources`.
  - `image-sources.test.ts`: `the shell's logos are replaceable`.
  - `agent-kit.test.tsx`: `kit.menu lists the site's pages`.
- [ ] **Step 2: Run; expect FAIL. Step 3: Implement. Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit:** `site-kit: the header's menu follows the site's pages (inspector plan 6)`.

### Task 5: The frame — header and footer as Puck items with the shell address

**Files:**
- Modify: `apps/frontend/packages/site-editor/src/client/editor-app.tsx` (Puck gets `pageWithShell`; `selectionScope`, `placeOf`, `describeElement`, `describeButton` and `describeBox` read `componentEntry`; the shell outline and shell click paths are removed; the editor's placement CSS)
- Modify: `apps/frontend/packages/site-editor/src/client/frame-controller.ts` (`targetOf(componentId)`; `componentSelected`, `reselected` and `elementClicked` use it; `pageEdited` uses `withEditedShellPage`; `applyOutsideEdit` refreshes Puck for target `shell`; `shellSelected` and `setShellFields` are removed)
- Modify: `apps/frontend/packages/site-editor/src/client/dom.ts` (`clickIntent` loses `kind: "shell"`)
- Modify: `apps/frontend/packages/site-editor/src/client/config.tsx` (`buildPageConfig(brand, sections, menu)`; `shellFieldDescriptions` removed)
- Modify: `apps/frontend/packages/site-kit/src/editor/clone-editor.tsx` (menu labels editable; one shared `markEditableText`)
- Create: `apps/frontend/packages/site-kit/src/editor/menu-editor.tsx` (`MenuLabels`, used by `SiteHeader` in the editor through `EditorParts`)
- Modify: `apps/frontend/packages/site-editor/src/client/styles.css` (Puck's wrapper gets R10 for `:has(> .clue-section[data-clue-sticky])` / `[data-clue-overlay]`; the inner box becomes static there)
- Test: `apps/frontend/packages/site-editor/test/frame-controller.test.ts`, `test/dom.test.ts`, `test/fields.test.ts`; `apps/frontend/packages/site-kit/test/clone-editing.test.tsx`

**Interfaces:**
- Consumes: `pageWithShell`, `withEditedShellPage`, `componentEntry`, `menuItems`, `siteMenuPages` (Tasks 1, 3, 4).
- Produces: a menu label written in place sets `menuLabels[<key without "menu.">]` (a page item) or `menuExtra[<n>].label` (an extra) on the item's props, through Puck `setData` (one history step, as clone slots do). An emptied page label removes its `menuLabels` entry; an emptied extra label is ignored, keeping the old one.
- Produces: `markEditableText(element, { read(): string; write(value: string): void })` in `site-kit/src/editor/`, the per-element focus / pause / blur logic `CloneEditor` already has, extracted unchanged and used by both.

- [ ] **Step 1: Write the failing tests** in `frame-controller.test.ts`:
  - `a header item's selection is the shell target`: `componentSelected("header", "ClonedSection", …)` posts `selected` with `route: "shell"`.
  - `Puck's onChange splits the shell back`: `pageEdited("/", pageWithShell(page, editedShell))` posts a `changed` site whose shell is `editedShell`, with the page unchanged.
  - `an outside shell edit refreshes Puck's data`: `applyOutsideEdit(site, "shell", rev)` calls `showPage` with `pageWithShell`.
  - `a click in the footer names the shell part`.

  In `dom.test.ts`, `clickIntent has no shell kind; a header click is a component click`.
  In `clone-editing.test.tsx`, `typing a menu label in place writes menuLabels` (with the existing `CloneEditor` test harness).
- [ ] **Step 2: Run; expect FAIL.** `cd apps/frontend/packages/site-editor && npx tsx --test test/frame-controller.test.ts test/dom.test.ts test/fields.test.ts` and the site-kit file.
- [ ] **Step 3: Implement.** Everything that branched on `target === SHELL_TARGET` to find props now goes through `componentEntry`. `hiddenParts` reads `componentProps`.
- [ ] **Step 4: Run** the site-editor test folder's named files above plus `test/sections.test.ts`, `test/keys.test.ts`; expect PASS.
- [ ] **Step 5: Commit:** `site editor: the header and footer are Puck items addressed as the shell (inspector plan 6)`.

### Task 6: The app — shell types, Arrange, Visibility, the Header group

**Files:**
- Create: `apps/frontend/src/features/site-editor/model/site-shell.ts` (`headerPlacementState`, `commitHeaderPlacement`)
- Create: `apps/frontend/src/features/chat-shell/components/site-header-placement.tsx`
- Modify: `apps/frontend/src/features/chat-shell/components/site-box-panel.tsx` (section mode shows the Header group for the header)
- Modify: `apps/frontend/src/features/site-editor/model/site-arrange.ts` (`moveWrite` decides by type)
- Modify: `apps/frontend/src/features/site-editor/model/site-selection.ts` (the "styled as a whole" reason is removed)
- Modify: `apps/frontend/src/features/chat-shell/components/site-link-row.logic.ts` (the shell refusal is removed; a page menu item gets `PAGE_MENU_LINK`)
- Modify: `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts` (annotation `componentType` from `componentEntry`)
- Modify: `apps/frontend/src/features/site-editor/model/site-layers.ts` (labels for the shell rows unchanged; element rows from the entry)
- Test: `model/site-shell.test.ts` (new), `model/site-arrange.test.ts`, `model/site-selection.test.ts`, `model/site-layers.test.ts`, `model/site-image.test.ts`, `chat-shell/components/site-link-row.logic.test.ts`

**Interfaces:**
- Produces:
  - `headerPlacementState(site: SiteDocument | null, selection: { target: string; componentId: string; element: unknown } | null): { sticky: boolean; overlay: boolean } | null`: non-null only for the header itself (target `shell`, `header`, no element);
  - `commitHeaderPlacement(site: SiteDocument, which: "sticky" | "overlay", on: boolean): { props: Record<string, unknown>; site: SiteDocument } | null`: writes or removes `_edits.root.<which>`; null when unchanged.
- Produces (exact copy): group title `Header`; checkboxes `Stays at the top while scrolling` and `Sits over the first section`; note `The first section now starts under the header. If its words sit under the header, give it more top padding.`

- [ ] **Step 1: Write the failing tests:**
  - `site-shell.test.ts`: state is null for the footer and for a header element; `commitHeaderPlacement` writes `_edits.root.sticky: true`, removes it with `on: false`, and returns null when unchanged.
  - `site-arrange.test.ts`: `moveWrite` gives `order` for header entries of type ClonedSection and SiteHeader, and `fixed` for an agent's header.
  - `site-selection.test.ts`: `wordsUnavailableReason` is null for a template's text slot in the header.
  - `site-link-row.logic.test.ts`: a page menu item gives `PAGE_MENU_LINK` with its label; `menu._0` edits `menuExtra.0.href`.
  - `site-image.test.ts`: `the header's logo replaces through its prop`.
  - `site-layers.test.ts`: header rows come from a ClonedSection entry.
- [ ] **Step 2: Run; expect FAIL.** `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-shell.test.ts …` (the files above)
- [ ] **Step 3: Implement**; the Header group writes through the session's existing props-write path (one save, one undo step).
- [ ] **Step 4: Run; expect PASS.** Then `cd apps/frontend && npm run lint`; expect no errors.
- [ ] **Step 5: Commit:** `site inspector: the header and footer as sections in the panel (inspector plan 6)`.

### Task 7: Deriving templates from the seller's own header and footer

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/fragments/site_templates.py`
- Create: `subsystems/clue-design/apps/api/tests/test_site_templates.py`
- Create: `subsystems/clue-design/apps/api/tests/fixtures/site_templates/` (four synthetic captures written for the test: a Webflow-style header with dropdowns, co-brand text, a Login button, a CTA and a hamburger; a Tailwind/base-ui header with a hidden mega-menu panel and two buttons; the two matching footers with link columns, a newsletter form, social icons and a © row with legal links). No seller markup is copied in.

**Interfaces:**
- Produces:
  - `SITE_HEADER_ROLE = "site_header"`, `SITE_FOOTER_ROLE = "site_footer"`, `COMPOSED_SITE_TEMPLATE = "site_template"`;
  - `MENU_ATTR = "data-clue-menu"`, `MENU_ITEM_ATTR = "data-clue-menu-item"`, `MENU_LABEL_ATTR = "data-clue-menu-label"`;
  - `ACCOUNT_CSS` (R5's fixed rules);
  - `class TemplateNotDerivable(Exception)` with `.reason`;
  - `@dataclass(frozen=True) class DerivedTemplate: html: str; slots: tuple[SlotSpec, ...]; css_addition: str; notes: tuple[str, ...]`;
  - `derive_site_template(role: str, source_html: str, *, placeholder_src: str) -> DerivedTemplate`.

- [ ] **Step 1: Write the failing tests** (one per rule, on the fixtures):
  - `test_header_keeps_logo_menu_pattern_and_last_cta`: one logo link; exactly one `[data-clue-menu]` holding one `[data-clue-menu-item]` with one `[data-clue-menu-label]`; the CTA is "Book a demo"; no "Login".
  - `test_header_drops_dropdowns_drawers_and_hidden`: no element with `hidden`, `aria-expanded`, `w-dropdown`, `role=dialog`, and no textless button.
  - `test_header_inserts_the_account_after_the_logo`: the next sibling of the logo link is `span.clue-account[data-lumen-slot=account_shown]` with `img.clue-account-logo[data-lumen-slot=account_logo][src=<placeholder>]`, followed by `span.clue-account-line[data-lumen-slot=account_line]` carrying the menu link's class.
  - `test_every_text_has_a_slot`: every element with own text has `data-lumen-slot`; slot keys are unique and pass `slot_key_is_valid`.
  - `test_footer_keeps_logo_and_legal_row_only`: the © text and the legal links remain; no link column, form or social link.
  - `test_not_derivable_without_logo` / `test_footer_not_derivable_without_legal_or_logo`: raise `TemplateNotDerivable` with the reasons `no logo` / `no legal row or logo`.
  - `test_derivation_is_deterministic`: the same input twice gives byte-identical output.
- [ ] **Step 2: Run; expect FAIL.** `pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_templates.py`
- [ ] **Step 3: Implement** R5 and R6 with selectolax (the parser the fragment code uses). Slot detection calls the mint's `detect_slots` on the pruned markup, then adds R5 step 7's ruled slots.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit:** `fragments: derive ABM header and footer templates from the seller's own (inspector plan 6)`.

### Task 8: Minting templates — the extraction, the offline script, the catalog

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/agent_cloned_sections.py` (`mint_site_template`, `mint_site_templates`)
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/pipeline.py` (after the mint loop: `mint_site_templates` for the kit, its failures as diagnostics)
- Create: `subsystems/clue-design/scripts/derive_site_templates.py`
- Modify: `apps/frontend/packages/site-kit/src/catalog.ts` (R13)
- Test: `subsystems/clue-design/apps/api/tests/test_site_template_mint.py` (new; DB), `apps/frontend/packages/site-kit/test/catalog.test.ts`

**Interfaces:**
- Produces:
  - `DurableAgentClonedSectionRegistry.mint_site_template(*, role: str, source_fragment_id: str) -> JsonObject`, returning `{fragment_id, role, status, label, slot_keys, notes, converged}`. The label is `Header template — <seller>` or `Footer template — <seller>`. The provenance holds `composed: "site_template"`, `shell_role`, `source_fragment_id`. `derived_from` is the source, with `derived_reason` "site template". The status is released to `approved`.
  - `mint_site_templates(*, kit_id: str, kit_version: int) -> list[JsonObject]`: for each role, the source per R4, then `mint_site_template`; a role with no usable source, or a `TemplateNotDerivable`, gives `{role, skipped: <reason>}`.
- Produces: the diagnostic code: the next free `LUMI05xx` (grep the codes in `lumen_ingestion`), `severity: "warning"`, message `site <role> template not made: <reason>`.
- Produces: `derive_site_templates.py --workspace <ws_id> [--kit <kit_id>] [--apply] [--preview-dir <dir>]`. The default is a dry run: it prints the chosen sources, the slot keys and the notes, and writes `<role>.html` previews (the derived markup with its CSS) to `--preview-dir`. `--apply` mints and releases.

- [ ] **Step 1: Write the failing tests:**
  - `test_mint_site_template_releases_an_approved_clone` (DB): seed a `nav` fragment from the fixture. The minted row has role `site_header`, status `approved`, `derived_from` = source; `list_site_clones` returns it with role `site_header`; the `data-clue-menu*` markers survive sanitizing.
  - `test_mint_site_templates_prefers_the_home_page_and_skips_degraded`.
  - `test_mint_site_templates_reports_not_derivable`.
  - `catalog.test.ts`: `templates are listed first and not among page sections`.
- [ ] **Step 2: Run; expect FAIL. Step 3: Implement. Step 4: Run; expect PASS.**
- [ ] **Step 5: Dry run on the stored captures** (read-only; the lane DB and `.artifacts`, sourced from `.env`): `derive_site_templates.py --workspace <garner ws>` and `--workspace <conduit ws>`, with `--preview-dir` in the session scratchpad. Expected: a header and a footer derived for each. Open each preview in the in-app browser and screenshot it into the ledger. A rule that misfires on a real capture is fixed in Task 7's code with a new fixture case (RED first), never in the script.
- [ ] **Step 6: Commit:** `site templates: minted at extraction and by an offline script, listed in the catalog (inspector plan 6)`.

### Task 9: Scenario tests through the real routes

**Files:**
- Create: `subsystems/clue-design/apps/api/tests/test_site_shell_scenarios.py`

Each scenario goes through the design API's site routes, storage and publish bundle, as `test_site_image_scenarios.py` does:
- [ ] **Step 1: Write the scenarios:**
  - `test_template_header_edited_undone_published`: a site whose shell is a minted template header and a `SiteFooter`. Then: save the account line; replace `account_logo` with a library file; set `_edits.root.sticky` and `overlay`; undo once; publish. The published `/` starts with the header (account line as saved, sticky only), and the footer is last.
  - `test_menu_follows_pages`: add `pages/team.json`, save, publish. Each published page's menu lists `/`, `/team`, keyed `menu._home`/`menu.team`; a `menuLabels.team` saved earlier is kept.
  - `test_one_template_two_accounts`: the same template in two sites with different `account_line`/`account_logo`; each publishes its own, and no `{{` or placeholder pixel remains where a logo was set.
  - `test_agent_header_checked_like_a_section`: an agent header section with a `className` prop is refused by the section check (the route the existing agent-section scenarios use) with the existing message; a valid one becomes `shell.header` and publishes.
  - `test_old_shell_refused_at_save`: saving the old shape is refused with the Task 1 message.
- [ ] **Step 2: Run; expect PASS** (the behaviour exists after Tasks 1–8; a failure is a defect in them, fixed RED→GREEN in the owning task's test file first).
- [ ] **Step 3: Commit:** `site: header and footer scenario tests through the real routes (inspector plan 6)`.

### Task 10: The agent's view and skill text (founder gate)

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/workspace.py` (site.md describes the header and footer with the page-section summary; `_styled_by_hand` words for `sticky`/`overlay`; the menu line)
- Modify (after the founder approves): `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/skills-e5/writing-a-section/SKILL.md`, `.../skills/building-with-puck/SKILL.md`, `SKILLS-CHANGELOG.md`
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_site_workspace.py`

- [ ] **Step 1: Write the failing test** `test_site_md_describes_header_and_footer_as_sections`, with the exact lines:
  - `## Header and footer (shell.json)`;
  - `- Header: ClonedSection frag_… "Header template — Garner"`, followed by its slot lines as a page clone has;
  - `- Header stays at the top while scrolling; sits over the first section`;
  - `- Menu: Overview → /, Team → /team; extra: Pricing → https://…`;
  - `- Footer: SiteFooter`, with its prop lines.
- [ ] **Step 2: Run; expect FAIL; implement; run; expect PASS.**
- [ ] **Step 3: Draft the skill text** in the ledger (`skill-draft.md`) and show it to the founder in chat:
  - **building-with-puck:** the shell.json shape; start from the kit's templates; write the account line for the account (no fixed "Prepared for"); fill `account_logo` or hide `account_shown`; `menuLabels`; `menuExtra` only for one-to-few or one-to-many sites, never on a site for one account; sticky and overlay.
  - **writing-a-section:** writing a header or footer from scratch: the brand's tokens, the measured button and link styles, `kit.menu`, the seller's logo from the kit; not generic.

  **Stop here until the founder approves; then write it, and commit `agent skills: headers and footers (inspector plan 6, founder-approved)`.**

### Task 11: Browser proof, gates, live check

**Files:**
- Create: `tests/site_editor/test_editor_shell.py`

- [ ] **Step 1: Browser tests** (`CLUE_SITE_EDITOR_BROWSER=1`):
  - `test_header_template_words_edit_in_place`: click the account line, type, blur; the saved shell holds it.
  - `test_sticky_header_stays_while_canvas_scrolls`: tick "Stays at the top while scrolling", scroll `#root` by 800px; the header's top is 0.
  - `test_overlay_starts_first_section_under_header`: tick "Sits over the first section"; the first page section's top equals the header's top.
  - `test_menu_label_and_hide`: rename a menu item in place; hide another through Visibility.
- [ ] **Step 2: Gates.** Every named test file of Tasks 1–10 is green. `npm run design-system:build && npm run lint && npm run build` in `apps/frontend` (stack down) is green.
- [ ] **Step 3: Whole-branch review** (executing-plans' final review, the most capable model), then one fix pass.
- [ ] **Step 4: Live check** on the trenton stack, in the in-app browser, on Garner (Carmel Clay) and Conduit (Oliver). Pre-approved; report what it cost.
  - **Mint.** Run `derive_site_templates.py --apply` for both workspaces.
  - **Agent turn.** One turn per site: "Start the header and footer from the brand's templates."
  - **Walk:**
    - an account-line word typed and styled;
    - the account logo replaced from the Library (never Generate or Edit);
    - the seller's logo replaced and put back;
    - sticky, overlay and the header fill at 70% opacity, then scroll;
    - a menu item renamed, reordered with Arrange, hidden;
    - a page added, so the menu grows;
    - a phone-width preview: the menu is hidden;
    - publish preview.
  - **Undo** each change. The sites keep their new header and footer: the old shell shape is no longer drawn.
- [ ] **Step 5: Records.** The spec's §7.1 (plan 6 finished), §7.7 change log; `_memory/2026-10-18-site-element-inspector-plan-6.md`; the ledger. Commit `docs(specs): plan 6 finished and live-checked on Garner and Conduit`.
