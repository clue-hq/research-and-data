# Site element inspector, plan 5: images — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (the founder's rule since 2026-10-17: the plan is implemented directly, one whole-branch review at the end). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A marketer clicks an image on a Puck microsite (in our sections, a copied seller section, an agent's section, or the header and footer logos) and the right-hand panel edits it, as in the approved mockup (`.superpowers/brainstorm/95737-1792238115/content/site-inspector-panels.html`, "3 · Image selected"). The panel has these sections:
- **Image:** the current picture and Replace, using the existing picker (Upload, Library, Generate, Edit).
- **Fit:** Fill or Fit.
- **Alt text.**
- **Stroke:** colour, width and corner radius.
- **Arrange** and **Visibility** (both from plan 4).
- **Layers.**

Every change shows on the canvas, is one save and one undo step, and looks the same on the published page.

**Architecture:** Plan 4 already selects images (rulings R8) and lists them in Layers. Plan 5 fills their panel:
- **Look:** two new `_edits` facts. `imageFit` is drawn as `object-fit`. Stroke and corners are plan 3's box properties, which an `<img>` draws directly.
- **Where the image is stored:** the frame reports where each image's file is written: a prop, a copied section's image slot, or nowhere the marketer can change. Replace hands that place to the dock's existing image field, so uploads, the library and generation all work unchanged.
- **Where the alt text is stored:**
  - new props beside each image we draw (`imageAlt`, `logoAlt`, `accountLogoAlt`);
  - on copied sections, a new `alts` map by element key, applied by the clone filler as `newTab` is;
  - on agent sections, the agent's own; the panel says so.

**Tech Stack:** TypeScript, React 19, Puck 0.23.0 (pinned), Zod 4, node-html-parser, node:test via tsx, Python 3 + pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-10-17-site-element-inspector-design.md`. This is **plan 5**; §7 is the source of truth (§7.2 plan 5, §7.3 coverage; plan 4's R8 already moved image *selection* into plan 4). Update §7.1 when this plan starts and finishes, and §7.7 for every ruling below that changes §2/§4.

## Rulings (decisions this plan makes where the spec leaves a choice — for the founder to check)

- **R1 — Where an image's file is written (its "image source"), decided by the frame from the stored site:**
  - **Our sections:** the prop the image draws (FeatureSplit's `image`).
  - **The header's account logo:** `accountLogo`.
  - **The seller's logo** in the header and footer has no source the panel can change. Replace is disabled with "The seller's logo comes from the brand kit."
  - **A copied section's image:** its `image` slot (`slots.<name>`) when it has one. Otherwise Replace is disabled with "This image is copied from the seller's page and has no slot; ask the agent to change it."
  - **An agent's image:** the prop it is named after (as plan 3's R6 did for button words). This applies when `kit.Image` has `el="photo"` and `props.photo` holds an image path. Otherwise Replace is disabled with "The agent's section sets this image; ask the agent to change it."
- **R2 — Where alt text is written:**
  - **Our sections:** a new optional prop beside each image prop: FeatureSplit `imageAlt`.
  - **The header:** `logoAlt` and `accountLogoAlt`. **The footer:** `logoAlt`.
  - **A copied section:** a new `alts` prop mapping element keys to alt text. The clone filler sets each `alt` attribute, as it sets `newTab`.
  - **An agent's image:** the agent's own. The row is disabled with "The agent's section sets this image's alt text; ask the agent to change it."

  Alt text is plain text, at most 300 characters. It is drawn escaped (React and `setAttribute`), never as markup. Empty means a decorative image (`alt=""`).
- **R3 — Fit.** `imageFit: "fill"` draws `object-fit: cover` (the image fills its box and may be cropped). `"fit"` draws `object-fit: contain` (the whole image shows inside its box). The frame reports whether the box's shape differs from the image's own shape by more than 1%. When it doesn't, Fill and Fit look the same, so the row is disabled with "This image is shown at its own shape, so Fill and Fit look the same here." This follows plan 4's "never live and inert" rule.
- **R4 — A `<picture>`'s image is its `<img>`.** The clone keyer walks into `<picture>` (new keys inside it only, so no existing key moves) and the frame no longer counts `picture` as an image. The `<img>` is what is selected, styled and given alt text. The `<picture>` is a pass-through wrapper (plan 4's R10).
- **R5 — Videos and icons.** A `<video>` gets Fit, Stroke, Arrange and Visibility. Replace says "Ask the agent to change a video." and Alt text says "Videos have no alt text; the agent can describe one in the words beside it." An inline `<svg>` icon keeps plan 4's panel (Arrange, Visibility), with the note "This is an icon drawn in code; ask the agent to change it."
- **R6 — Replace is the dock's existing image field** (`renderImageField`, the same Upload / Library / Generate / Edit rows). It writes the image source from R1 as one save. Replacing a copied image slot clears its `srcset`, which the filler already does. When the same slot or prop draws more than one image on the page, the row says "This picture appears N times on this section; replacing it changes all of them."
- **R7 — The Stroke section reuses plan 4's box panel** (`SiteBoxPanel`, a new `mode: "image"` drawing only Stroke: colour, width, corner radius). Images get no Fill, Padding, Gap or Width: the mockup has none, and an image's size is its section's design.
- **R8 — Shapes.**
  - `imageFit`: `"fill"` or `"fit"`.
  - `imageAlt`, `logoAlt`, `accountLogoAlt`: strings of at most 300 characters, with no control characters.
  - `alts`: a record of element keys (`ElementKeySchema`, no `~`) to strings with the same limits.

## Global Constraints

- Puck stays pinned at `@puckeditor/core` 0.23.0; no new dependencies.
- No free CSS: every value passes the strict override schema and is validated where it is written; alt text is text, never markup.
- `site-kit/src/sections.tsx` and `shell.tsx` carry no style values (`test/style-literals.test.ts`).
- Element keys never shift: a clone's keys come from the captured markup; walking into `<picture>` adds keys inside it only.
- A control that cannot act is shown disabled with a one-line note, never live and inert. Text boxes commit on blur / Enter; every change is one save and one undo step.
- Generating or editing an image with AI spends money: the live check uses Upload or Library only, never Generate / Edit.
- No new runtime flag. Nothing outside `subsystems/clue-design/` imports design internals.
- Tests: named files only; never the `subsystems/clue-design/apps/api/tests` folder; never `*_live.py` or broad suites with real keys. Python via `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh <file>`. Browser tests: `CLUE_SITE_EDITOR_BROWSER=1` after `npm run build -w @clue/site-kit && npm run build -w @clue/site-editor` (from `apps/frontend`).
- Skill / prompt text is shown to the founder before it is written (Task 7).
- Commits: local only (push only when asked), no AI attribution, explicit paths, never `git stash`.

## Review Focus

1. **A copied `<img>` with `srcset` and `sizes`, replaced through its slot, then given alt text.** Expected: the new picture shows at every width (no stale `srcset` candidate wins), the alt text is set on the same element, and both survive a reload and publish. Pinned in Task 2 and Task 6.
2. **Alt text containing quotes, an ampersand and angle brackets (`Dr. "Smith" & <team>`).** Expected: stored as typed, drawn as an attribute value (escaped), never markup, on our sections, the header and a copied section alike. Pinned in Task 1 (validation) and Task 2 (render).
3. **Fit on an image whose box keeps its own shape (full width, height auto) versus a fixed-height hero photo.** Expected: the first shows Fit disabled with the R3 note; the second switches between cropping and showing the whole picture. Pinned in Task 3 and Task 8 (browser).
4. **The same image slot used by two `<img>` in one copied section.** Expected: the panel says it appears twice; replacing changes both; alt text set on one element changes only that one (alts are per element key). Pinned in Task 2 and Task 4.
5. **Corner radius on a `<picture>`-wrapped image and on a background photo selected from Layers.** Expected: the `<img>` itself is rounded (not its wrapper), and a section-covering background photo is reachable from Layers with the same panel. Pinned in Task 3 and Task 8.

---

### Task 1: The contract — `imageFit`, alt props and `alts`

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/edits.ts` (`imageFit`; CSS `object-fit`)
- Modify: `apps/frontend/packages/site-kit/src/schemas.ts` (FeatureSplit `imageAlt`; header `logoAlt`, `accountLogoAlt`; footer `logoAlt`; ClonedSection `alts`)
- Modify: `apps/frontend/packages/site-kit/src/validate.ts` (alt text rules where props are checked)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/workspace.py` (`_styled_by_hand` words for `imageFit`; alt texts in the section summary)
- Test: `apps/frontend/packages/site-kit/test/edits.test.ts`, `test/validate-site.test.ts`, `subsystems/clue-design/apps/agent_runtime/tests/test_site_workspace.py`

**Interfaces:**
- Produces: `StyleOverrideSchema.imageFit?: "fill" | "fit"` → declaration `object-fit:cover|contain !important` (after plan 4's). `AltTextSchema = z.string().max(300).regex(/^[^\u0000-\u001F\u007F]*$/)` exported from `schemas.ts`. `ClonedSection.alts?: Record<ElementKey (no ~), AltText>`.
- Produces: refusal messages (exact): `<where>.imageAlt: alt text is plain text of at most 300 characters, with no line breaks or control characters` (same wording for `logoAlt`, `accountLogoAlt`, `alts.<key>`).

- [ ] **Step 1: Write the failing tests** in `edits.test.ts`:
  - `imageFit parses fill and fit and draws object-fit`: `editsCss("s", { "0.1": { imageFit: "fill" } }, brand)` contains `object-fit:cover !important`; `"fit"` gives `object-fit:contain !important`; `"stretch"` refused.
  In `validate-site.test.ts`:
  - `alt texts are plain text of at most 300 characters`: a FeatureSplit `imageAlt` of 301 characters, a header `accountLogoAlt` holding `"\n"` and a clone `alts: { "0.1": "x".repeat(301) }` give the three exact messages. `Dr. "Smith" & <team>` is accepted everywhere. A clone `alts` key `"0.1~2"` is refused.
- [ ] **Step 2: Run; expect FAIL.** `cd apps/frontend/packages/site-kit && npx tsx --test test/edits.test.ts test/validate-site.test.ts`
- [ ] **Step 3: Implement** the schema fields, CSS and validation (the clone `alts` keys are checked against `ElementKeySchema` without `~`; values with `AltTextSchema`).
- [ ] **Step 4: Write the failing agent test** `test_site_md_reads_image_fit_and_alt_texts`. Expected `site.md` lines:
  - `image — image fills its box` / `image fits inside its box`;
  - for a FeatureSplit with `imageAlt`: `   - image alt text: "A quiet clinic waiting room"`;
  - for a clone with `alts`: `   - alt text 0.2.1: "Hotel lobby"`.
- [ ] **Step 5: Run; expect FAIL; implement; run; expect PASS** (`pytest-keyless.sh subsystems/clue-design/apps/agent_runtime/tests/test_site_workspace.py`).
- [ ] **Step 6: Commit:** `site-kit: imageFit and alt texts in the site contract (inspector plan 5)`.

### Task 2: Drawing it — alt props, clone `alts`, `<picture>` keys

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/sections.tsx` (FeatureSplit `alt={imageAlt ?? ""}`; its config field "Image alt text")
- Modify: `apps/frontend/packages/site-kit/src/shell.tsx` (`alt={header.logoAlt ?? ""}`, `alt={header.accountLogoAlt ?? ""}`, footer `alt={footer.logoAlt ?? ""}`)
- Modify: `apps/frontend/packages/site-kit/src/clone.ts` (`CloneExtras.alts`; apply after keying, by key, with `setAttribute("alt", text)`; `keyElements` walks into `<picture>`; `cloneImageAt(clone, key)`)
- Modify: `apps/frontend/packages/site-kit/src/config.tsx` (ClonedSection passes `alts` in `extras`; its `alts` field is a hidden custom field like `newTab`)
- Test: `test/element-keys.test.tsx`, `test/clone-editing.test.tsx`, `test/sections.test.tsx`, `test/live-page.test.tsx`

**Interfaces:**
- Consumes: `AltTextSchema` (Task 1).
- Produces: `cloneImageAt(clone: Clone, key: string): { slot: string | null; uses: number; alt: string } | null`. Its fields:
  - `slot` is the image slot on the `<img>`, or on its `<picture>`'s `<source>`/`<img>`.
  - `uses` counts the `<img>` elements filled from the same slot.
  - `alt` is the captured alt.
  - It returns null when the key is not an `<img>` or `<video>`.

- [ ] **Step 1: Write the failing tests:**
  - `a picture's img is keyed inside it and no other key moves` (`element-keys.test.tsx`): `<div><picture><source srcset="a.webp"><img src="a.jpg"></picture><p>x</p></div>` keys `0, 0.0, 0.0.1, 0.1`. The `fixtures/clone-text-keys.json` snapshot still holds.
  - `alts set alt text by element key, escaped, and survive slot fills` (`clone-editing.test.tsx`): `fillClone(clone, { hero: "/asset-store/<64 hex>" }, [], [], { alts: { "0.0": 'Dr. "Smith" & <team>' } })` contains `alt="Dr. &quot;Smith&quot; &amp; &lt;team&gt;"` on the `<img>` whose `src` was replaced, and that `<img>` has no `srcset`.
  - `cloneImageAt reports the slot, how many images use it, and the captured alt` (two `<img>` sharing a slot give `uses: 2`).
  - `FeatureSplit draws its image alt; the header and footer draw logo alts` (`sections.test.tsx`).
  - `a live page draws clone alts as the static render does` (`live-page.test.tsx`).
- [ ] **Step 2: Run; expect FAIL.** `cd apps/frontend/packages/site-kit && npx tsx --test test/element-keys.test.tsx test/clone-editing.test.tsx test/sections.test.tsx test/live-page.test.tsx`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the four files plus the whole site-kit suite; expect PASS** (update only tests that pin the old `<picture>` key list, each stating why).
- [ ] **Step 5: Commit:** `site-kit: alt texts drawn on our images, the shell's logos and copied images; a picture's img is keyed (inspector plan 5)`.

### Task 3: The frame describes an image

**Files:**
- Modify: `apps/frontend/packages/site-kit/src/editor-protocol.ts`
- Modify: `apps/frontend/packages/site-editor/src/client/dom.ts` (`computedImage`; `picture` out of `IMAGE_TAGS`)
- Modify: `apps/frontend/packages/site-editor/src/client/editor-app.tsx` (`describeBox` for images adds `image`, `imageSource`, `altSource`)
- Test: `apps/frontend/packages/site-editor/test/dom.test.ts`, `apps/frontend/packages/site-kit/test/editor-protocol.test.ts`

**Interfaces:**
- Produces:
  - `ComputedImageSchema = { media: "img" | "video" | "svg"; box: ComputedBox; fit: "fill" | "fit" | null; fitMatters: boolean; alt: string (≤ 300); src: string (≤ 2048) }`.
  - `ImageSourceSchema = { kind: "prop"; prop: PropPath; uses: number } | { kind: "slot"; slot: string; uses: number } | { kind: "fixed"; reason: string }`.
  - `AltSourceSchema = { kind: "prop"; prop: PropPath } | { kind: "clone"; key: ElementKey } | { kind: "fixed"; reason: string }`.
  - `ElementSelection` gains `image?`, `imageSource?`, `altSource?`.
- `computedImage(element, view, toHex): ComputedImage` works as follows:
  - `fit`: `object-fit` cover → `"fill"`, contain or scale-down → `"fit"`, otherwise `null`.
  - `fitMatters`: the box aspect (`rect.width / rect.height`) and the natural aspect (`naturalWidth / naturalHeight`; for a video `videoWidth / videoHeight`) differ by more than 1%. It is `false` when either is unknown.
- The describer's sources follow rulings R1, R2 and R5, with each reason's exact wording copied from them.

- [ ] **Step 1: Write the failing tests** (`dom.test.ts`, fake view and stubbed natural sizes):
  - `an image's fit, shape and alt as drawn`: a 400×300 box of a 4000×3000 picture gives `fitMatters: false`; a 1000×400 hero of a 4000×3000 picture with `objectFit: cover` gives `fit: "fill"`, `fitMatters: true`.
  - `a picture is a wrapper; its img is the image`.
  - `a video reports its own shape; an svg is an icon`.
  In `editor-protocol.test.ts`: `an image selection round-trips; a src over 2048 or an alt over 300 is refused`.
- [ ] **Step 2: Run; expect FAIL.** `cd apps/frontend/packages/site-editor && npx tsx --test test/dom.test.ts` and `cd ../site-kit && npx tsx --test test/editor-protocol.test.ts`
- [ ] **Step 3: Implement** (`ownImageSource` / `ownAltSource` helpers live in site-kit next to `ownLinkSource`, so the frame and the tests share one rule; `cloneImageAt` from Task 2 feeds the clone case).
- [ ] **Step 4: Run; expect PASS;** whole site-editor suite green.
- [ ] **Step 5: Commit:** `site editor: the frame reports an image's fit, shape, alt text and where its file and words are written (inspector plan 5)`.

### Task 4: The app — alt text and Replace targets

**Files:**
- Modify: `apps/frontend/src/features/site-editor/model/site-selection.ts` (`commitImageAlt`, `imageReplaceTarget`, `imageAltOf`, binding fields)
- Modify: `apps/frontend/src/features/site-editor/hooks/use-site-editing-session.ts`
- Test: `site-selection.test.ts`, `use-site-editing-session.test.ts`

**Interfaces:**
- Consumes: `ImageSource`, `AltSource` (Task 3).
- Produces:
  - `imageAltOf(site, selection): string | null` reads the stored alt from its source, or the captured alt for a clone with no entry. It is null when the source is fixed.
  - `commitImageAlt(site, selection, text: string): { props; site } | { refused: string } | null` behaves like this:
    - text is trimmed;
    - too long or a control character → `refused` with R8's message;
    - for a prop source, an empty string removes the prop;
    - for a clone source, a value equal to the captured alt removes the `alts` entry, and an empty `alts` removes the prop;
    - unchanged → null.
  - `imageReplaceTarget(selection): { prop: string; uses: number } | null` gives the prop path the dock's image field writes (`image`, `accountLogo`, `slots.hero`, an agent's `photo`).
  - The binding gains `imageAlt: string | null`, `onImageAltCommit(text): string | null` and `imageReplace: { prop; uses } | null`.

- [ ] **Step 1: Write the failing tests:**
  - `alt text is written to its prop, a clone's alts, or refused`;
  - `an alt back to the captured one drops the clone entry`;
  - `Replace targets the image prop, the header's account logo, a clone slot and an agent's named prop; none for the seller's logo`;
  - `an alt change is one save and one undo step` (session test).
- [ ] **Step 2: Run; expect FAIL.** `cd apps/frontend && npx tsx --test src/features/site-editor/model/site-selection.test.ts src/features/site-editor/hooks/use-site-editing-session.test.ts`
- [ ] **Step 3: Implement.** Save intent: `inspector: alt text <key>`.
- [ ] **Step 4: Run; expect PASS;** app suite green.
- [ ] **Step 5: Commit:** `site editor app: image alt text and Replace targets (inspector plan 5)`.

### Task 5: The image panel

**Files:**
- Create: `apps/frontend/src/features/chat-shell/components/site-image-panel.tsx` (+ `site-image-panel.logic.ts`, `site-image-panel.logic.test.ts`)
- Modify: `apps/frontend/src/features/chat-shell/components/site-box-panel.tsx` (`mode: "image"`: Stroke only; `boxTargets` takes an image's `image.box`), `site-box-panel.logic.ts`, `site-inspector.tsx` (the image branch draws `SiteImagePanel`; it needs `renderImageField`)
- Test: `site-image-panel.logic.test.ts`, `site-box-panel.logic.test.ts`, `site-inspector-button.test.ts`

**Interfaces:**
- Consumes: binding fields (Task 4), `renderImageField` (existing `SiteImageFieldRenderer`).
- Produces: `imagePanelValues(override, image): { fit: "fill" | "fit" | null; fitLive: boolean }` and `imageFitPatch(override, fit): StyleOverride | null`. Choosing what is shown returns the same override, so no save is made.
- Sections, in the mockup's order:
  - **Image:** thumbnail and Replace through `renderImageField({ kind: "image", label: "Image", name: prop }, prop, current)`; or a disabled note (R1, R5); and the "appears N times" line when `uses > 1`.
  - **Fit:** Fill · Fit, disabled with R3's note when the shape does not change it.
  - **Alt text:** a text box committing on blur / Enter; a refusal note under it; a disabled note per R2 / R5.
  - **Stroke:** `SiteBoxPanel mode="image"`.
  - **Arrange** and **Visibility** (plan 4), then **Layers**.
  The plan-4 placeholder line ("Image settings … come in the next update.") is removed.

- [ ] **Step 1: Write the failing tests:**
  - `fit values and patches; fit off when the shape does not change it`;
  - `image mode draws only Stroke and writes the image's key`;
  - `an image shows Image, Fit, Alt text, Stroke, Arrange, Layers in order` (render test);
  - `the seller's logo shows Replace disabled with its note`;
  - `a video shows the video notes`.
- [ ] **Step 2: Run; expect FAIL.** `cd apps/frontend && npx tsx --test src/features/chat-shell/components/site-image-panel.logic.test.ts src/features/chat-shell/components/site-box-panel.logic.test.ts src/features/chat-shell/components/site-inspector-button.test.ts`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run; expect PASS;** `npm run lint` (0 errors), `npx tsc --noEmit -p .` clean for the touched files.
- [ ] **Step 5: Commit:** `site inspector: the image panel (inspector plan 5)`.

### Task 6: Scenario tests through the real routes

**Files:**
- Create: `subsystems/clue-design/apps/api/tests/test_site_image_scenarios.py` (pattern: `test_site_container_scenarios.py`)

- [ ] **Step 1: Write the scenarios.** Each goes through save → read → undo → redo → publish:
  1. A FeatureSplit image with `imageAlt` (with quotes and `&`), `imageFit: "fill"` and corners 16. The published `<img>` carries the escaped alt, and the rule carries `object-fit:cover` and `border-radius:16px`.
  2. A minted copied section with an image slot and `srcset`: the slot replaced with an `/asset-store/` file and `alts` set on it. The published `<img>` has the new `src`, no `srcset`, and the alt.
  3. The header's `accountLogo` replaced, plus `accountLogoAlt` and `logoAlt`, published.
  4. Refusals with their messages: alt over 300 characters; an alt with a line break; `imageFit: "stretch"`; an `alts` key with `~`.
- [ ] **Step 2: Run** `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh subsystems/clue-design/apps/api/tests/test_site_image_scenarios.py`. Expected: all pass.
- [ ] **Step 3: Commit:** `api: scenario tests for images (inspector plan 5)`.

### Task 7: The agent's view and skill text (founder gate)

**Files:** `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/skills-e5/writing-a-section/SKILL.md`, `.../site/skills/building-with-puck/SKILL.md`, `.../site/SKILLS-CHANGELOG.md` (`workspace.py` was done in Task 1).

- [ ] **Step 1: Draft and show the founder** (in chat, not written):
  - **writing-a-section:** name an image after the prop that holds it (`el="photo"`, `src={props.photo}`), so the marketer can replace it; pass its alt from a prop too.
  - **building-with-puck:** `imageFit` (fill / fit) and the image's stroke and corners in `_edits`; `imageAlt`, `logoAlt`, `accountLogoAlt`; a cloned section's `alts` by element key; alt text is plain text, empty for a decorative image.
- [ ] **Step 2: Write it only after the founder approves;** changelog line; commit `agent skills: images (inspector plan 5)`.

### Task 8: Browser proof, gates, live check

- [ ] **Step 1: Browser test** `tests/site_editor/test_editor_images.py`:
  - click a FeatureSplit image → `selected` kind image with `image`, `imageSource` and `altSource`;
  - a copied `<picture>` → its `<img>` is selected;
  - `set_props` with `imageFit`, a radius and an alt → computed `object-fit`, `border-radius` and the `alt` attribute;
  - a fixed-height background photo selected from Layers → `fitMatters: true`;
  - a full-width image → `fitMatters: false`.
- [ ] **Step 2: Gates:**
  - the site-kit, site-editor and app suites;
  - the browser folder;
  - the frontend gate (`design-system:build`, `lint`, `build` with the lane stack down);
  - the named API files (render, publish package, publish routes, write routes, validation, element-edits, rich-text, buttons, containers, images).
- [ ] **Step 3: Live check** at the pane's native size (no viewport emulation), with the founder signed in:
  - **Garner (Carmel Clay):** the Feature split's photo — Fit, Alt text, corners, and Replace from the Library (no Generate).
  - **Conduit (Oliver Hotels):** a copied image — alt text, Fit, and Replace through its slot if it has one.

  Then undo back to the starting versions and verify each stored site equals its start. Update spec §7.1 (finished, with the date), §7.7 and `_memory`.
