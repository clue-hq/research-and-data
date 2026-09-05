# Editor Quality Roadmap — seven defects from the 2026-09-04 Apollo dry run

**Status:** roadmap, founder-ordered 2026-09-04. **Plan 1 DONE 2026-09-04** (`2026-09-04-ingestion-type-units-and-faces.md`, live-proven on the Apollo ad; letter-spacing folded into item A on evidence; italic harvest was already present and is pinned by test). **Plan 2 DONE 2026-09-04** (`2026-09-04-page-first-and-first-batch-canvas.md`; the live proof found and fixed a second blocker for item D: ledgered-but-unstreamed ops broke the stream cursor's contiguity — Task 5). **Plan 3 DONE 2026-09-04** (`2026-09-04-selection-ladder.md`; the inspector breadcrumb was DECLINED by the founder after a preview: Layers already covers ancestry) — **its click/double-click rules were SUPERSEDED the same day by `2026-09-04-selection-model-v2.md`** (outermost unit on click, drill on double-click, Cmd/Ctrl deep select, second-click walk-up removed; live-proven on the Brex CTA). **Plan 4 item F DONE 2026-09-04** (`2026-09-04-text-bounds-and-inspector-typography.md`; live-proven on the Apollo ad: the empty half of the headline box selects what is behind it, the "x" glyph selects the "x", a text selection outlines its painted lines with a dashed frame on a fixed box, Fit to text hugs in one write. The live proof found a deeper engine defect — a text node's hug height was measured with no width bound outside a taffy solve, so fixed-width wrapped text hugged its unwrapped line count — fixed as ruling R8 / Task 5b.) **Plan 4 item G: preview delivered, founder ruling pending** (`docs/superpowers/previews/2026-09-04-typography-rows/`; no control shipped). Each numbered plan below becomes its own SDD plan
file when it starts (`docs/superpowers/plans/2026-09-0X-<slug>.md`), implemented by Opus subagents
with controller review, per the standing rules. This document is the reference the plans argue
from; it records the verified root causes so no plan re-derives them.

**Founder ordering:** Plan 1 (ingestion) → Plan 2 (fresh document) → Plan 3 (selection ladder) →
Plan 4 (text bounds + inspector typography) LAST. Inside Plan 4, the inspector controls (item D)
are gated: before any button lands in the inspector toolbar, the founder sees a rendered preview
of the controls, their icons, and the icon source (library, licence, file), and approves.

**Evidence base:** the Apollo LinkedIn ad `doc_cf05190c347f5ad9923c4e3c303b6297`
(kit `brand_kit_ing_10c2b0ea17054c668384ae5e91abfebb` v2), runs `run_0452aae9…` (budget exhausted
before repair) and `run_b866…` (headline repair), the founder's screenshot of the selected stray
"x", and the code paths cited per item. Session memo: `_memory/2026-09-04-editor-quality-dry-run.md`.

---

## Plan 1 — Ingestion: line-height units and font faces

### Item A. Line-height token stored as 4.5 (verified)

- **Root cause.** `subsystems/clue-design/apps/api/lumen_ingestion/capture/parse.py:767`
  `_line_height(value)` returns `px / 16.0` for any length: the ROOT font size, not the element's.
  Apollo's headline (~64px with a 72px line-height) becomes 4.5. Both call sites
  (`parse.py:1130` declared CSS, `parse.py:1229` rendered sample) have the element font size
  beside them (`sample.get("fontSize")`). The kit's `typography.type.headline.line_height` is 4.5
  while every other role is 1.0–1.5. Every headline-styled text inherits it: the broken headline,
  the stray "x" (30px text, 4.5 leading, 71px fixed box → glyph paints below the box), and the
  critic's wasted repair round all trace here.
- **Change.** `_line_height(value, font_size_px)`: unitless → as is; `em` → as is; `px` and `rem`
  → `px / font_size_px` (rem via the root size). `normalizer/typography.py` (~line 205–245) gains
  a guard: a ratio above 2.5 is a misparse → dropped with a diagnostic naming the role, never
  written. A dry-run backfill script (`scripts/rederive_kit_line_heights.py`, `--apply`) recomputes
  only `typography.type.*.line_height` for stored kits from the stored evidence and publishes a
  NEW kit version (kit versions are immutable); the Apollo document is re-pinned to it.
- **Tests.** Parser cases: `"72px"` at 64px → 1.125; `"1.1"` → 1.1; `"1.2em"` → 1.2; `"4.5rem"` at
  64px → 1.125; guard rejects 4.5 with the role in the message. Kit fixture: headline role lands
  in 1.0–1.3.
- **Live proof.** Re-run the Apollo ad: the headline paints as tight lines; no repair round.

### Item B. Bold / italic do nothing (verified)

- **Root cause.** The Apollo kit holds ONE face per family (`soehne` 400 normal, `seasonMix` 400
  normal). The editor matches faces the way the server does (`canvaskit/fontFaces.ts::selectFace`,
  CSS3 weight selection; the italic request is gated to a real face, A7b D2) and never
  synthesises bold or oblique, so Bold asks for 700, falls back to 400, and nothing changes.
  Both harvested fonts are variable fonts (fvar with a weight axis) that were never instanced.
- **Change.** At ingestion (`capture/evidence_builder.py` font jobs → `normalizer/emit.py add_font`):
  for a variable face with a `wght` axis, instance the named weights 400/500/600/700 with
  `fontTools.varLib.instancer` (the exact path `lumen_ingestion/font_library.py` already uses for
  the Google library), ingest each instance as its own asset (sfnt, per option A), and emit them as
  kit faces with `weight`. Harvest italic sources when the site's `@font-face` declares
  `font-style: italic` (today one source per family is kept). Editor: when a family has no face
  for the requested weight/slant, the toolbar renders that toggle DISABLED with a one-line reason
  (`scene-text-toolbar.logic.ts` reads the registered faces via `familyFaces`), instead of a
  silent no-op.
- **Tests.** Instancing on a variable fixture yields four faces with the right OS/2 weights;
  the emitted kit carries them; toolbar logic disables Bold/Italic with a reason when absent.
- **Live proof.** Bold on the Apollo headline visibly thickens on the canvas AND in the SVG
  export; Italic shows disabled with its reason until Söhne's italic file is harvested.

---

## Plan 2 — Fresh document: page first, stream from the first batch

### Item C. Page before assets (verified)

- **Root cause.** Nothing orders the author's first write. On a pageless document (`open_design_leg@4`
  births `pages: {}`), run `run_0452aae9…` fetched Ramp's logo and generated the hero before any
  page existed; every placement was refused by the engine rule `LUMV0100` "document must contain
  at least one page/artboard"; `generate_image` (`tools/substrate.py:~1039`) only discovers this
  AFTER paying for the image, then hands back the hint "author the page first". Cost: ~10 minutes
  and the budget that would have paid for the repair round.
- **Change.** (1) A hard rule in `lumen_agent/prompts.py` (author section, beside "Author in Lumen
  DSL and apply it with compile_dsl_block", ~line 291) and in
  `knowledge_docs/skills/linkedin-square-ad/SKILL.md`: on a pageless document, round one's FIRST
  write is the page. (2) Enforcement in the tools: `generate_image` and logo placement check
  `scene.pages` BEFORE spending and refuse with the existing hint payload, so a misordered author
  loses one tool call, never an image generation or a vendor request.
- **Tests.** Substrate tests with a fake image provider: pageless scene → refusal payload with the
  hint and ZERO provider calls; with a page → the provider is called once.
- **Live proof.** A fresh document's first `design.op_batch` carries `add_page` within the first
  minute; the run finishes inside the 45-call / 15-minute target with a repair round to spare.

### Item D. Canvas mounts on the first operation batch (verified)

- **Root cause.** `apps/frontend/src/features/design-editor/hooks/use-scene-document.ts:254`
  picks `pageId = firstPageId(loaded.scene)` ONCE at load. A pageless load keeps `pageId = null`
  even after a streamed batch adds a page (`use-scene-live-reveal` applies it; the engine accepts
  it; `canApply = Boolean(engine)` is true), so `scene-artifact-canvas.tsx:686`
  `scenePagelessNotice(scene, pageId)` keeps showing "Design hasn't created the page yet" until a
  checkpoint reload replaces the scene. Rung B was proven only on documents that already had a
  page.
- **Change.** Derive the effective page id in the canvas from the DRAWN scene: the loaded page id
  when present, else `firstPageId(drawnScene)`; the pageless notice keys off the same value. One
  derivation, one place; the checkpoint reload keeps its anchor role.
- **Tests.** Canvas/adapter logic test: pageless loaded scene + streamed `add_page` → an effective
  page id and no notice; a loaded page id wins when present.
- **Live proof.** Start an ad on a fresh document: the artboard appears on the first batch,
  roughly a minute in, instead of after the first render round.

---

## Plan 3 — Selection ladder (frontend only)

### Item E. The CTA cannot be selected; selection has no feedback (verified)

- **Root cause.** `adapter/scene-selection.ts::representableHit` selects the topmost node in the
  engine's bottom-to-top hit stack that has an inspector schema. Inside a button that is always
  the label text; the `cta_btn` auto-layout wins only in its 40px padding. There is no hover
  outline (the canvas has none) and no gesture to walk up to a parent. (The agent also let the
  CTA overflow its column — `left_col` fixed 896 vs CTA bottom 951 — an authoring defect Plan 2's
  page-first rule and Plan 4's hug default reduce.)
- **Change.** Engine untouched. (1) Hover outline from the same hit stack on pointer move.
  (2) A button-shaped container (auto-layout whose only child is text) is selected as a unit on
  first click; double-click enters the label. Everything else keeps deepest-leaf first click.
  (3) A second click on the same spot, or modifier-click, walks up one ancestor; Escape walks up;
  ~~a breadcrumb in the inspector header shows the ancestry and jumps on click~~ (declined by the founder 2026-09-04; Layers covers it).
- **Tests.** Pure tests over hit stacks: button-first, walk-up, breadcrumb ancestry, hover target.
- **Live proof.** Select the CTA with one click; edit its label by double-click; reach
  `left_col` with two clicks or the breadcrumb; the hover outline shows the target before the
  click.

---

## Plan 4 — Text bounds and inspector typography (LAST; Rust + frontend)

### Item F. Selection box ≠ painted text; oversized boxes steal clicks (verified)

- **Root cause.** `crates/lumen-core/src/hit_test.rs::point_in_node` tests text against
  `render_box_for_node` (the layout box); text paints unclipped; the agent authored the headline
  (fixed 504×216) and the stray "x" (fixed 326×71) as fixed boxes. Empty box area steals clicks;
  paint outside the box (the "x" glyph at ~y=190 vs box bottom 182) cannot be clicked; the
  selection outline is the box, not the text.
- **Change.** (1) Engine: keep the measured text line boxes in computed geometry (the Skia
  measure pass already computes them and discards them after layout); text hit-testing = inside
  any painted line box (small tolerance), not the layout box; the hit-stack contract is unchanged.
  (2) Canvas: the selection outline for text = union of painted line boxes; a fixed-size text box
  keeps a secondary dashed frame for deliberate resizing. (3) Authoring default: text height =
  hug in the DSL defaults and the ad skill; existing fixed boxes get a "Fit to text" action, no
  silent migration.
- **Tests.** Rust: oversized fixed text box — empty-area point misses, glyph point hits. Canvas:
  outline bounds. DSL default test.
- **Live proof.** Click the empty half of the old headline box and get the wash behind it; click
  the "x" glyph and get the "x".

### Item G. Inspector typography controls — FOUNDER PREVIEW GATE

- **Root cause.** The engine already has `line_height`, `letter_spacing`, `max_lines`, wrap and
  vertical alignment on text nodes; `adapter/scene-apply.ts` already applies vertical alignment
  (`case "verticalAlignment"`); the ad inspector (`chat-shell/components/image-inspector.tsx`,
  Typography section ~line 381) renders only text, family, size, weight, horizontal alignment,
  colour.
- **Change.** Rows for line height (ratio, 0.05 steps), letter spacing (em), vertical alignment
  (top / middle / bottom), max lines + wrap, and the text resize mode from item F; two new apply
  cases (`lineHeight`, `letterSpacing`); schema rows in the design-editor adapter.
- **Gate (founder, 2026-09-04).** Before any control lands: a rendered preview (static HTML or a
  screenshot of a branch build) showing each control in place in the Typography section, the icon
  for each, and for every icon its source (library name, licence, file path or URL, and whether
  it is already vendored in `apps/frontend`). Nothing is added to the toolbar until that preview
  is approved. Default icon source to propose: `lucide-react` (already a dependency; ISC licence).
- **Tests.** Adapter apply tests per property; schema test that a text selection exposes the rows.
- **Live proof.** Change the headline's line-height from the panel and watch it reflow.

---

## Open rulings carried from this session
- Test-DB hygiene: a disposable DSN for the design API suites (the shared-DSN theft + stale-row
  poison bit four times this session). Until ruled, no suites run while a real turn is wanted.
- The exit judge cannot be built on this stack (`agent model timeout must be positive and no
  greater than gateway policy`) — leg close ("lock it in") remains blocked; design turns are
  unaffected.
