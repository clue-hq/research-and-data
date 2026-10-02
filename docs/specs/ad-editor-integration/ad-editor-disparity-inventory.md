# Ad-editor disparity inventory — dummy inspector vs the clue-design scene editor

**Status: INVENTORY ONLY — no decisions are made in this document.** Every row is a factual
observation for the founder to rule on (the AD-R ratification session). This is the ad-editor
analogue of `docs/specs/website-editor-integration/decisions-recorded.md` *before* annotation.

Date: 2026-08-19. Verified against:


| Surface                             | Source of truth                                                                                                                                                | State                                                                                                                                                                             |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Dummy ad editor**                 | `clue-frontend` (port-of-spain worktree), branch `codex/chat-shell`, HEAD `c7f2bc5` — `src/features/chat-shell/components/image-inspector.tsx` + shared chrome | fresh, clean tree                                                                                                                                                                 |
| **MVP frontend (platform)**         | `apps/frontend/src/features/chat-shell/components/image-inspector.tsx` + `image-export-menu.tsx`                                                               | **byte-identical to dummy HEAD** (verified by `diff` 2026-08-19) — lifted in W0, mounted inert. Everywhere below, "dummy" therefore also means "MVP frontend as it stands today". |
| **MVP editor (the real ad editor)** | `subsystems/clue-design/apps/editor` — scene editor only (`src/app/page.tsx` → `EditorApp`), CanvasKit path                                                    | full control-by-control enumeration, file:line anchors below                                                                                                                      |
| **Engine model**                    | `subsystems/clue-design/crates/lumen-core` (`scene.rs`, `assets.rs`, `slots.rs`, `operations.rs`, `dsl.rs`)                                                    | cited per row                                                                                                                                                                     |


The web-document editor (`apps/editor/src/app/web/*`) is **not** part of this comparison.

> **REVISION 2 — 2026-08-20.** The co-founder added four new inspector schemas to the dummy —
> **auto-layout, rectangle, ellipse, group** — a 23-file delta (+663/−33) on top of `c7f2bc5`
> in the checkout at `/Users/aryankeshri/Documents/clue-hq/clue-frontend` **[now committed
> locally as `32658ff`, 2026-08-20 — the AD0.1 lift pins against it]**
> (new `ad-dummy-inspectors.tsx` 389 L; `image-inspector.tsx` dispatch extended;
> `CHAT_SHELL_INSPECTOR_SELECTIONS` grown to 11; 16 new icons; `web-inspector.tsx` defensively
> narrowed to its own 7 web kinds — the web editor is unaffected). **That checkout's working
> tree is now the dummy source of truth for the ad editor**; the port-of-spain worktree and the
> "byte-identical to dummy HEAD" claim above are stale for ad-side files. Founder ruling
> 2026-08-20: earlier founder comments about controls that the new schemas now design are
> **stale** — each is marked `[STALE 2026-08-20]` in place below, superseded by §2.6.
> Note: the new schemas are deliberate **static scaffolding** — every control is
> `readOnly`/no-op with a single-option select — a pure visual spec (no state islands), unlike
> the original four schemas' working local state.

> **FOUNDER RULINGS 2026-08-20 (OQ-1…OQ-8, verbatim intent):**
> **OQ-1** Plain Frame renders the auto-layout schema **minus** its Auto Layout section
> (= Shape + Stroke + Layout + Arrange + Layers). **OQ-2** Width/Height mode ships all three
> (Fixed/Hug/Fill); the "Width fixed"/"Height fixed" inputs appear **only in Fixed mode**;
> fill-weight inputs stay out. **OQ-3** Opacity displays as % and converts to the engine's 0–1
> at the seam. **OQ-4** The new Layout section does **NOT** extend to text/image/button.
> **OQ-5** Editor semantics govern all Arrange controls on the new schemas — alignment (2+
> nodes), distribution (3+), Group (2+ same-parent siblings) / Ungroup (single container),
> ⌘G/⇧⌘G. **OQ-6** Group's missing Shape/Stroke sections are a deliberate hiding — confirmed.
> **OQ-7** Standing rulings govern the new kinds' headers: lock real, eye omitted. **OQ-8**
> The co-founder will commit/push the new dummy delta; the lift pins against that commit, and
> the AD0 re-lift includes the trailing `web-inspector.tsx` delta.

Legend used in the tables (factual, not a ruling):
**HAS-BACKING** = the engine model can represent it · **EDITOR-HAS** = the MVP editor UI exposes
it · **NO-BACKING** = no engine concept exists · **NO-SLOT** = the dummy has no designed place
for it · **MISMATCH** = both sides have it but the vocabularies/semantics differ.

---



## 1. Node / element-type vocabulary



### 1.1 The three vocabularies side by side


*(Updated 2026-08-20 for the four new dummy schemas.)*

| Dummy selection schemas (11 total) | Dummy layer-row kinds | Engine `NodeKind` (`scene.rs:381-392`) | MVP-editor inspector treats specially |
|---|---|---|---|
| `canvas` (artboard) | — | *(page is not a node — `Page` with `root`, `size`, `background`)* | DocumentPageSection when nothing is selected |
| `text` | Text | `Text(TextNode)` | TextSection + TextToolbar |
| `image` | Image | `Image(ImageNode{asset_id, alt})` | ImageInspectorSection |
| `button` | Button | **— (no button kind exists)** | — |
| **`auto-layout`** *(new 2026-08-20)* | Auto layout (`layout-template` icon) | `AutoLayout(direction, wrap)` | AutoLayoutSection |
| **`rectangle`** *(new)* | Rectangle | `Rect` | generic sections only |
| **`ellipse`** *(new)* | Ellipse | `Ellipse` | generic sections only |
| **`group`** *(new)* | Group (`square-dashed` icon) | `Group` | generic sections only |
| — | — | **`Frame`** | generic sections only |
| — | — | `Line(x2, y2)` | generic sections only |
| — | — | `Vector(path_data, view_box)` | generic sections only |
| — | — | `Instance{source_node_id}` | generic sections only |
| *(web-side, fall through to canvas)* `icon`/`container`/`section` | — | — | — |




### 1.2 Node types the MVP editor/engine WILL use that the dummy has no schema for

*(Rewritten 2026-08-20 — items 1–3 of the original list are RESOLVED by the co-founder's new
schemas: AutoLayout, Rect, Ellipse and Group now have designed inspectors, mapped in §2.6.)*

1. **Frame (plain, non-auto-layout) — the one structural kind STILL without a schema.** The
   co-founder added `auto-layout` but not `frame`, and the engine distinguishes them
   (`Frame` vs `AutoLayout`, `scene.rs:381-392`). This matters more than it looks: the agent's
   prescribed idiom paints the canvas background as a **clipped root artboard Frame with a
   fill** (`prompts.py:324-327`), so the most-clicked container in a real generated ad is a
   plain Frame. Open question §OQ-1: which schema serves it (the auto-layout schema minus its
   Auto Layout section ≡ Shape+Stroke+Layout+Arrange, the group schema, or a new design)?
2. **Line, Vector** (`svg(icon:…)` lowers to Vector — `dsl.rs:4657-4660`), **Instance**
   (personalization derivatives) — still absent from the dummy (no layer row, no schema).
   Founder comment (2026-08-19, STANDS — these kinds were not added):
   --> for now we will let it be without it, since we want to editor to be very less complicated i guess.
3. **The page as a first-class selection** — in the MVP editor, deselecting everything shows a
  full document/page inspector (title, artifact type, page name/W/H/unit, safe margin, bleed,
   page fill token). The dummy's `canvas` schema is the nearest analogue but carries a different  field set (§2.1).  
  --> the title here will be correspond to the artifact's name in the gallery - similar to this - /Users/aryankeshri/conductor/workspaces/research-and-data/istanbul/docs/specs/ad-editor-integration/img1.png  
  --> page name/W/H/unit display it on top of the page just like figma does it - you see how it has name at top-left corner,  
  and dimensions at the bottom edge's center. safe-margin and bleed are something which only the agent will add to the design artifact.



### 1.3 Dummy element types with no engine counterpart

1. `button` — no `NodeKind` is a button (`scene.rs:381-392`). A "button" in a static ad
  is representable only as a convention (e.g. a rounded AutoLayout/Frame + Text child); the
   engine has no notion of button type/variant, and — see §2.4 — no link either.
2. `canvas` **as a *node* selection** — the artboard is a `Page`, not a node; "canvas selected"
  maps to the editor's no-selection/page state, not to a node schema.

---



## 2. Dummy schema → MVP editor/engine, control by control

Header chrome first (present on every dummy schema):


| Dummy control                                                  | MVP editor                                                                                               | Engine                                                                 | Verdict                                                                                                                                 |
| -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Title string (hardcoded `"Canvas"/"Text34"/"Button"/"Image1"`) | read-only kind badge + `nodeDisplayName` heading + **editable Name field** (`ObjectSection.tsx:115-160`) | `Node.name`                                                            | MISMATCH — dummy titles are Figma artifacts; editor has real names + rename --> we will do the naming andmatching as per editor schema. |
| Lock toggle (hidden on canvas)                                 | Lock/Unlock button (`ObjectSection.tsx:120-123`) + lock gates every write                                | `Node.locked` (`scene.rs`)                                             | HAS-BACKING + EDITOR-HAS                                                                                                                |
| Visibility (eye) toggle (hidden on canvas)                     | **nothing** — no per-node visibility anywhere in the editor UI                                           | **no** `visible`**/**`hidden` **field on** `Node` (`scene.rs:270-319`) | NO-BACKING --> since mvp did not have it, and neither does the engine have it, we will omit it from the editor design.                  |
| Ellipsis "More actions"                                        | n/a (inert in the dummy too — no `actionMenu` passed)                                                    | —                                                                      | inert both sides                                                                                                                        |

*Addition 2026-08-20:* on the four NEW schemas the dummy renders the header lock/eye
**disabled** (no handlers, `visible=true` hardcoded — scaffolding). The standing rulings above
(lock = real per editor schema; eye = omitted, NO-BACKING) presumably govern the new kinds too
— confirm (§OQ-7).




### 2.1 Dummy `canvas` schema (artboard) vs page/document surface


| Dummy control                                   | Dummy detail                                                                                                       | MVP editor                                                                                                                                                                                | Engine                                                                                                                                                                      | Verdict                                                                                                                                                                                                                                                                               |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Size preset select                              | 3 options: `Linkedin square (1:1) - 1024x1024`, `Instagram portrait (4:5) - 1080x1350`, `Story (9:16) - 1080x1920` | PageRail quick sizes (different set, §6.1) + free W/H + unit `pt/px/mm/in`; Preset field is **read-only text**; manual W/H forces `preset:"custom"` (`DocumentPageSection.tsx:97-132`)    | `PageSize{w,h,unit,preset}`; `PagePreset = A4, UsLetter, LinkedinAd(1200×627), EnvelopeDl, Custom` (`scene.rs:185-254`)                                                     | MISMATCH — three conflicting preset vocabularies (§6.1); engine op is `update_page` --> along with three presets we will add a custom page artboard size option to dummy editor. add an option to the dropdown - custom. when it's selected, 2 textbox comes below with label H and W |
| Background fill — Solid                         | ColorControl (theme/custom hex, HSV plane, recents)                                                                | page level: **token-only** `Page Fill Token` select (`DocumentPageSection.tsx:153-158`); no raw hex, no picker                                                                            | `Page.background: Vec<Fill>` accepts Solid/Gradient/Token (`scene.rs:185-193`)                                                                                              | HAS-BACKING, editor UI narrower than both dummy and engine                                                                                                                                                                                                                            |
| Background fill — Linear/Radial gradient editor | 2–6 stops, per-stop color+%, add/remove, angle 0–360 (linear); default 4-stop radial navy                          | **no gradient editing anywhere** — ColorSwatchControl guards: "Gradient fill — edit in Appearance" (a section that doesn't exist); StyleSummary prints "linear/radial gradient" read-only | `Paint::{LinearGradient{angle,stops}, RadialGradient{stops}}` on any fill incl. page background; DSL `linear(...)`/`radial(...)` (`scene.rs:1201-1213`, `dsl.rs:3568-3616`) | HAS-BACKING, **EDITOR-LACKS UI** — the dummy's gradient editor is *richer than the real editor's*                                                                                                                                                                                     |
| Layers panel                                    | hardcoded 8-row list                                                                                               | LayerPanel — real recursive tree (§3.6)                                                                                                                                                   | scene tree                                                                                                                                                                  | dummy is fixture-only                                                                                                                                                                                                                                                                 |
| *(not in dummy)*                                | —                                                                                                                  | Document Title, Artifact Type (free text), Layout-managed-editing checkbox, page Name, Orientation (ro), Safe Margin, Bleed, page diagnostics, SlotOverview                               | all modeled                                                                                                                                                                 | NO-SLOT (§3.5)                                                                                                                                                                                                                                                                        |


Note: the agent's practice complicates "canvas background": generated designs usually paint the
background as the **root frame's fill**, not `Page.background` (`prompts.py:324-327`). "Edit the
canvas background" therefore has *two* candidate targets in real documents.

### 2.2 Dummy `text` schema vs TextSection/TextToolbar/engine


| Dummy control                       | Dummy detail                                                                 | MVP editor                                                                                                                                                                 | Engine                                                                                                      | Verdict                                                                                                                                                                               |
| ----------------------------------- | ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Color                               | ColorControl, default `#00F59B`                                              | no color in TextSection; text color = **Fill Color** (RawStyleSection `ColorSwatchControl`, token-first + native color) and the TextToolbar swatch                         | text color is `Node.fills` — **no per-node text-color field** (`scene.rs`; tokens route to `text.`* bucket) | HAS-BACKING; MISMATCH in where/how it's edited                                                                                                                                        |
| Font select                         | 4 options: Inter, Satoshi Variable, Season Serif, DM Mono                    | **free-text Family input** (TextSection `:46-53`, TextToolbar `:77-83`) — no picker; real families come from bundled Inter + ~27-family font library + brand-kit faces     | `TextNode.font_family` string                                                                               | MISMATCH — dummy's fixed list vs editor's unconstrained string vs the real font-library/kit vocabulary; Season Serif and DM Mono have no font stack anywhere in the dummy repo either |
| Size select                         | fixed list 12,13,14,16,18,20,24,32 (default 24)                              | free number, min 1                                                                                                                                                         | `font_size: f64` (+ `font_size_token`)                                                                      | MISMATCH — closed list vs continuous --> make it free number like.                                                                                                                    |
| Weight select                       | Regular / Medium / Semi Bold / Bold                                          | number 100–900 step 100 (TextSection) / 9-option select `100 Thin … 900 Black` (TextToolbar `:23-33`)                                                                      | `font_weight` numeric                                                                                       | MISMATCH — 4 names vs 9 numeric weights --> please add font-weights names options as per 9 different variants of weight.                                                              |
| Horizontal alignment                | 3 toggles (left/center/right)                                                | 4 (adds **Justify**) — TextSection `:70-88`, TextToolbar `:113-127`                                                                                                        | `TextAlign{Left,Center,Right,Justify}` (`scene.rs:864-870`)                                                 | MISMATCH — dummy lacks justify --> add justify as well.                                                                                                                               |
| Vertical alignment                  | 3 toggles (top/middle/bottom)                                                | 3 (top/center/bottom), **disabled when height is hug** ("No effect with hug height")                                                                                       | `valign: VerticalAlign` (`scene.rs:876-897`)                                                                | PARITY-shaped; editor adds the hug-height disable rule                                                                                                                                |
| Stroke color + width                | ColorControl (default `none`) + width input (default 1)                      | Stroke Color (native color input) + Stroke Width min 0 (0 clears) — RawStyleSection `:31-55`, kind-agnostic so applies to text too                                         | `Node.strokes: Vec<Stroke>` universal (`scene.rs:270-319`)                                                  | HAS-BACKING + EDITOR-HAS                                                                                                                                                              |
| Position X/Y                        | 2 inputs (Figma-artifact defaults 123/4354)                                  | X/Y (+W/H) in ObjectSection, disabled unless freehand/unlocked; pinned nodes edit `absolute_box`                                                                           | `transform`/`size`/`absolute_box`                                                                           | HAS-BACKING + EDITOR-HAS; editor adds the managed/freehand distinction the dummy has no concept of                                                                                    |
| Rotation                            | input, °                                                                     | Rotate in ObjectSection + on-canvas rotate handle                                                                                                                          | transform rotation                                                                                          | HAS-BACKING + EDITOR-HAS                                                                                                                                                              |
| Arrange — layer (4 z-order buttons) | Bring to front / forward / backward / to back                                | same 4, with ⌘]/⌘[/⌥⌘]/⌥⌘[ shortcuts + front/back edge disabling (`ArrangeSection.tsx:110-147`)                                                                            | `move_node` / structured edits                                                                              | PARITY-shaped                                                                                                                                                                         |
| Arrange — alignment (6 buttons)     | align left/center/right/top/middle/bottom, offered on a **single** selection | same 6 modes but **requires 2+ unlocked freehand nodes** (`canAlignNodes`); no align-to-page/artboard exists                                                               | `alignDistribute` ops                                                                                       | MISMATCH — semantics differ (dummy implies align-to-canvas; editor only aligns nodes to each other) --> update the dummy toolbar as per the mvp editor's toolbar.                     |
| Layers                              | fixture list                                                                 | real tree                                                                                                                                                                  | —                                                                                                           | see §3.6                                                                                                                                                                              |
| *(not in dummy — §3.3)*             | —                                                                            | Content textarea, Line Height, Letter Spacing, Max Lines, Wrap, Direction (LTR/RTL/Auto), Case, Paragraph Spacing, Style Token, Italic, Underline, Strikethrough, Truncate | all modeled (`scene.rs:401-501`)                                                                            | NO-SLOT                                                                                                                                                                               |




### 2.3 Dummy `image` schema vs ImageInspectorSection/engine


| Dummy control                             | Dummy detail                                         | MVP editor                                                                                                                                                                                              | Engine                                                                                                                                                                                                                               | Verdict                                                                                                                            |
| ----------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| Link to (URL + "Open in a new tab")       | text input + checkbox                                | **nothing**                                                                                                                                                                                             | **no link/href/url concept on any node** — exhaustively verified; the only URL-ish things are asset *source* URLs, brand website, and personalization `InstanceLink` consumed solely by QR slots (`assets.rs`, `binding.rs:236-600`) | **NO-BACKING**                                                                                                                     |
| Image upload (file picker + preview swap) | `InspectorImageUpload`, FileReader data-URL          | **no replace-in-inspector**: replacement = Regenerate (AI) or Assets panel → `Place` onto the selected node (`AssetBrowserPanel.tsx:166-180`); upload lives in the Assets panel (png/jpeg/gif/webp/svg) | `upsert_asset` + `place_asset_in_node` ops; content-addressed store                                                                                                                                                                  | MISMATCH — same goal, different affordance                                                                                         |
| Mode select                               | Fit / Fill / Stretch / Tile                          | `Fit` select: **cover / contain / crop** (+ Focal X/Y 0–1 step .05 when crop-relevant, + on-canvas focal handle) (`ImageInspectorSection.tsx:196-215`)                                                  | `ImageFitMode{Contain,Cover,Crop}` + `FocalPoint` (`slots.rs:174-184`)                                                                                                                                                               | MISMATCH — Fit≈contain, Fill≈cover map cleanly; **Stretch and Tile have no engine mode**; engine's crop+focal has no dummy control |
| Radius (all + 4 corners + scan)           | `RadiusControls` (imported from `web-inspector.tsx`) | Radius All/TL/TR/BR/BL numbers (writing clears `corner.token`) + Radius token select (`RawStyleSection.tsx:56-130`, `DesignTokensSection.tsx:73-90`)                                                    | `Node.corner: CornerRadii` universal                                                                                                                                                                                                 | PARITY-shaped                                                                                                                      |
| Layers                                    | fixture                                              | real tree                                                                                                                                                                                               | —                                                                                                                                                                                                                                    | §3.6                                                                                                                               |
| *(not in dummy — §3.4)*                   | —                                                    | Alt text, **Generate image** (prompt), **Edit image** (instruction), **Remove background**, Before/After candidate review with Accept / Reject / Save-as-new, asset status line                         | asset pipeline + placement model                                                                                                                                                                                                     | NO-SLOT — the editor's flagship image feature set has no dummy surface                                                             |




### 2.4 Dummy `button` schema vs engine reality


| Dummy control                 | Dummy detail                                                                                            | MVP editor                                                                                                  | Engine                            | Verdict                                                               |
| ----------------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | --------------------------------- | --------------------------------------------------------------------- |
| Link to (URL + new-tab)       | input + checkbox                                                                                        | nothing                                                                                                     | **NO-BACKING** (§2.3 row 1)       | NO-BACKING                                                            |
| Button type select            | Primary / Secondary / Transparent / Critical                                                            | nothing — no button concept                                                                                 | no button kind, no variant model  | **NO-BACKING** (representable only as a convention)                   |
| Background color (token chip) | label from state, swatch hardcoded `#00F59B`, fires `token-picker:button-background` (no picker exists) | Fill Token select over brand `surface_tokens` (`DesignTokensSection.tsx:30-36`)                             | `Paint::Token` + brand kit tokens | HAS-BACKING via tokens — but only if "button" resolves to a real node |
| Text color (token chip)       | label "Content", swatch `#FFFFFF`, `token-picker:button-text`                                           | Fill Token on the text child (`text.*` bucket)                                                              | same                              | same as above                                                         |
| Padding L/T/R/B               | 2×2 grid, defaults 8/4/8/4                                                                              | AutoLayoutSection Pad T/R/B/L (+ Padding Token) — only on auto-layout nodes (`AutoLayoutSection.tsx:80-91`) | `AutoLayoutProps.padding`         | HAS-BACKING iff button = AutoLayout node                              |
| Layers                        | fixture                                                                                                 | real tree                                                                                                   | —                                 | §3.6                                                                  |




### 2.5 Dummy top bar / menus vs editor chrome


| Dummy control                                                    | Dummy detail                                                                              | MVP editor                                                                                                                                                                                                                                                    | Verdict                                                                                                                                                                                               |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Zoom menu                                                        | 23% / 50% / 75% / 100% (default 23%), string state, **applies no transform**              | continuous zoom 10%–200%: ±0.1 buttons, % readout, ⌘/Ctrl+wheel ±0.08 at pointer, **Fit current artboard** and **Fit all artboards** buttons; **no percentage preset menu exists** (`CanvasKitCanvas.tsx:888-963`, `canvasViewport.ts:1-2`)                   | MISMATCH — preset menu vs continuous+fit --> keep it the way dummy frontend has it right now... just add more options to it... right from 10 to 150% at intervals of 5. make the dropdown scrollable. |
| Edit toggle (pencil-ruler)                                       | mounts the inspector dock                                                                 | no equivalent — the standalone editor is always editing; the platform Edit-gate is a chat-shell concept                                                                                                                                                       | platform-side concept, fine                                                                                                                                                                           |
| Export button + menu                                             | see §5                                                                                    | Export button + popover menu; ExportPanel sidebar mode                                                                                                                                                                                                        | §5                                                                                                                                                                                                    |
| Artifact action menu                                             | Rename, Duplicate, Undo ⌘Z, Redo ⇧⌘Z, Versions flyout (Current/V3/V2/V1), Archive, Delete | Rename = editable title (`EditorChrome.tsx:68-128`); Undo/Redo = toolbar buttons + ⌘Z/⇧⌘Z/⌘Y; **Version history dialog** (day-grouped envelope list, Undo last/Redo/Refresh) — richer than the dummy's 3-version flyout; no Duplicate/Archive at editor level | MISMATCH in placement and depth. --> maintain visual oarity the same as that of dummy frontend.                                                                                                       |
| Tab bar (gallery tab, artifact tabs, rename F2, maximize, close) | chat-shell chrome                                                                         | n/a — platform shell owns it                                                                                                                                                                                                                                  | platform-side                                                                                                                                                                                         |
| **Tool palette (authored, unbuilt)** | `ImageEditorTool` = image / pointer / shape / stroke / text + `.editorToolButton` CSS + `public/icons/chat-shell/editor/*` icons + `editor.tool.change` event — **nothing consumes them** | **the real editor has no insert palette either**: `WorkspaceTool` = select / hand only (`workspaceViewport.ts:11`); nodes enter via agent/DSL, Assets `Place`, or page creation (`WebInsertPalette.tsx` belongs to the web editor) | **NEITHER side has working insert tools** — the dummy sketched five, the founder's 2026-08-20 Figma mocks show them in the artifact header; scope undecided (§OQ, carried from the 2026-08-19 doubt list) |

*(Row restored 2026-08-20 — the original was destroyed by unescaped `|` characters during the
annotation session's table reformat.)*

### 2.6 The four NEW schemas — auto-layout / rectangle / ellipse / group (added 2026-08-20)

Source: `ad-dummy-inspectors.tsx` (`/Users/aryankeshri/Documents/clue-hq/clue-frontend`, committed locally as `32658ff` 2026-08-20).
Section composition per selection:

| Section | auto-layout | rectangle | ellipse | group |
|---|---|---|---|---|
| Auto Layout | ✓ | — | — | — |
| Shape | ✓ (with radii) | ✓ (with radii) | ✓ (**no radii**) | — |
| Stroke | ✓ | ✓ | ✓ | — |
| Layout | ✓ | ✓ | ✓ | ✓ |
| Arrange | ✓ | ✓ | ✓ | ✓ (+ Group/Ungroup row) |
| Layers | ✓ | ✓ | ✓ | ✓ |

Control-by-control mapping to the MVP editor / engine:

**Layout section (all four kinds)**

| Dummy control | Dummy detail | MVP editor | Engine | Verdict |
|---|---|---|---|---|
| Position X / Y | prefixed inputs, static `0` | ObjectSection X/Y (freehand/unlocked gating; pinned → `absolute_box`) | `transform` / `absolute_box` | HAS-BACKING + EDITOR-HAS |
| Dimensions W / H | static `100` | ObjectSection W/H | `SizeSpec` | HAS-BACKING + EDITOR-HAS |
| Rotate | prefix `R`, static `0` | ObjectSection Rotate + canvas rotate handle | transform rotation | HAS-BACKING + EDITOR-HAS |
| Opacity | prefix `%`, static `100` | ObjectSection Opacity **0–1 scale, step 0.05** | `Node.opacity` (+ token) | MISMATCH — % display vs 0–1 model (§OQ-3: convert at the seam?) |
| Width mode / Height mode | selects, single static option **`Fixed`** | SizingSection selects **Fixed / Hug / Fill** (+ display-only Token) | `Dimension` kinds | MISMATCH — option set undesigned (§OQ-2); editor's fill-weight inputs have no dummy slot |
| Width fixed / Height fixed | static `100` | SizingSection fixed inputs (min 1) | `Dimension::Fixed` | PARITY-shaped (mirrors the editor's own W/H-shown-twice) |

**Auto Layout section (auto-layout only)**

| Dummy control | Dummy detail | MVP editor | Engine | Verdict |
|---|---|---|---|---|
| Direction | select, static `Row` | Row / Column | `AutoLayoutNode.direction` | PARITY-shaped (option set to ratify) |
| Wrap | select, static `No wrap` | No wrap / Wrap | `AutoLayoutNode.wrap` | PARITY-shaped |
| Gap | prefix `G`, static `0` | Gap (min 0) | `layout.gap` | PARITY-shaped |
| Grow | prefix `+`, static `0` | Grow (min 0) | `layout.grow` | PARITY-shaped |
| Pad T/R/B/L | four prefixed inputs | Pad T/R/B/L (min 0) | `layout.padding` | PARITY-shaped (same T,R,B,L order) |
| Align X / Align Y | selects, static `Space between` / `Center` | 5 options each: Start/Center/End/Space between/Stretch | `start/center/end/space_between/stretch` | PARITY-shaped (full option set to ratify) |
| *(not designed)* | — | Gap Token, Padding Token (brand-gated) | spacing tokens | NO-SLOT (unchanged) |

**Shape section (auto-layout, rectangle; ellipse without radii)**

| Dummy control | Dummy detail | MVP editor | Engine | Verdict |
|---|---|---|---|---|
| Fill | `ColorControl` in `none` state, no opacity chip | RawStyle Fill Color (token-first popover) / DesignTokens Fill Token | `Node.fills` universal | HAS-BACKING; the color-policy question (hex vs tokens) applies here too |
| Radius all + TL/TR/BR/BL | static `0` | RawStyle radii (writes clear `corner.token`) + Radius token | `Node.corner` universal | PARITY-shaped. Ellipse omission is sensible (engine tolerates but meaningless) |

**Stroke section (all except group)** — Color (`none` state) + Width (`1`): RawStyle stroke
color/width → `Node.strokes` universal. PARITY-shaped. *(Group omits Shape AND Stroke — the
engine allows fills/strokes on `Group`, but the design treats groups as paint-less containers;
recorded as a deliberate §2-style hiding to confirm, §OQ-6.)*

**Arrange section (all four)**

| Dummy control | Dummy detail | MVP editor | Engine | Verdict |
|---|---|---|---|---|
| Layer (4 z-order) | NEW icons `layer-front/up/down/back` | same 4 + ⌘]/⌘[/⌥⌘]/⌥⌘[ + edge disabling | `move_node` | PARITY-shaped |
| Alignment (3+3) | NEW icons `align-start/center/end-{horizontal,vertical}` | 6 modes, requires **2+ unlocked freehand nodes** | `alignDistribute` | same semantics gap as the text schema — founder already ruled "as per the MVP editor's toolbar" there; presumed to extend (§OQ-5) |
| Distribution (2) | **NEW in the dummy** — horizontal / vertical | requires **3+ nodes** | `alignDistribute` | as above |
| Group / Ungroup (group schema only) | NEW icons `group`/`ungroup` | Group needs 2+ unlocked same-parent siblings; Ungroup a single container; ⌘G/⇧⌘G | `canGroupNodes`/`canUngroupNode` + structured edits | HAS-BACKING; enable/disable semantics to adopt from editor (§OQ-5) |

**Layers section** — per-schema minimal fixture rows with the NEW kind icons
(`layout-template` for auto-layout, `square-dashed` for group) and a NEW `accented` active
style (`layerRowAccented`). In the main `AdLayers` tree: an "Auto layout" row was added, and
the Group/Rectangle/Ellipse rows now actually change selection to their new schemas (formerly
dead clicks). The §3.6 founder rulings for the real tree (any depth, fill-swatch glyphs,
multi-select, auto-scroll, no up/down buttons) are unaffected and stand.

**Icon-vocabulary note:** the new schemas introduce a second alignment icon family
(`align-start-vertical` etc.) while the original text schema still uses the old family
(`align-left` etc.) — two coexisting vocabularies for the same six operations; reconcile at
lift time.


---



## 3. Reverse direction: MVP-editor controls with **no dummy slot**

Everything below exists and works in the clue-design scene editor today and has no designed
place in the dummy ad editor.

### 3.1 ObjectSection (kind-agnostic — would apply to *every* selection)

Kind badge · node id · editable **Name** · **Delete** (danger) · **Detach / Re-attach**
(pinned vs layout-managed) · **X, Y, W, H** (dummy has X/Y only, and only on text -->  
this is fine with what dummy has currently, just add W and H as well to this list)  
· **Rotate** (dummy: text only) · **Opacity** (0–1, step 0.05 — *no opacity control exists anywhere in the dummy ad editor, add one to our final integrated frontend, make it consistent and coherent with the design system convention eing followed in the dummy editor. for icons if you dont have one, let me know i will get them for you*)  
· state summary (Locked / Pinned / Layout-managed / Slot-bound) · per-node diagnostics list with "Show node" jump.

**[STALE 2026-08-20 — the founder's "add W/H" and "add opacity" comments above are superseded:
the co-founder's new Layout section (§2.6) designs X/Y + W/H + Rotate + Opacity + size modes
for the four new kinds. Remaining question is only whether that Layout section also extends to
text/image/button (§OQ-4).]**

### 3.2 SizingSection + AutoLayoutSection (the layout system)

Width/Height **mode** (Fixed / Hug / Fill) · fixed dims · fill weights · Direction (Row/Column) · Wrap · Gap · Grow · Pad T/R/B/L · Align X / Align Y (5 options each incl. Space between, Stretch) · Gap Token · Padding Token. The dummy has exactly one layout-ish control (button padding). This entire system — the backbone of how generated ads are actually structured — is unrepresented. --> it's okay to keep it from from frontend editor for now ig... 

**[STALE 2026-08-20 — superseded by founder ruling: the co-founder's new auto-layout schema
designs Direction/Wrap/Gap/Grow/Pad T,R,B,L/Align X,Y, and the new Layout section designs the
Width/Height modes + fixed dims (§2.6). Still without a dummy slot: fill weights, Gap Token,
Padding Token.]**

### 3.3 TextSection / TextToolbar beyond the dummy

Content textarea (the dummy cannot edit text *content* at all — no field, and no canvas) ·
Line Height · Letter Spacing · Max Lines · Wrap · Direction (LTR/RTL/Auto) · Case
(UPPER/lower/Title) · Paragraph Spacing · **Style Token** (brand type role) with the
detach-warning chip · Italic · Underline · Strikethrough · Truncate · Justify.  
--> i think let's keep them out for the first build for now. editor behind the scene anyway   
has these editing funcitonality, its just that we wont put those edit controls onto the frontend  
for now. 

### 3.4 ImageInspectorSection beyond the dummy

Alt text · **Generate image** (prompt → asset at long-edge 1536) · **Edit image**  
(instruction) · **Remove background** · Before/After candidate review (Accept / Reject /  
Save-as-new) · focal-point control (inspector numbers + on-canvas handle) · asset status line.  
--> we need to add this. Make sure to add this from the mvp editory only, but make it look coherent  
with the design theme of the editor.

### 3.5 Document/page surface beyond the dummy

Document Title · Artifact Type · Layout-managed-editing toggle · page Name · Unit
(pt/px/mm/in) · Orientation · **Safe Margin** · **Bleed** · Page Fill Token · page diagnostics
· SlotOverview. Plus **PageRail**: multi-artboard add/duplicate/remove, quick sizes, print
presets (A4/US Letter, flag-gated) — the dummy is structurally single-artboard ("one ad is one
artifact", `docs/api-contracts/chat-shell.md:151`).  
--> already made the decision in the table above. follow that only.

### 3.6 LayerPanel vs the dummy layers section

Real recursive tree (any depth; dummy caps at one Group) -- add any depth feature only · kind glyphs incl. **fill-swatch squares for Rect/Ellipse -- add this** · move up/down reorder buttons with lock-aware tooltips -- no up-down buttons · additive multi-select (shift/⌘-click) -add this · auto-scroll to primary -- add this. Neither side has: drag-and-drop reorder, per-row lock/visibility toggles, rename-in-place, collapse/expand (dummy *does* have
collapse/expand chevrons on its one Group row — the editor's tree has none).

*Update 2026-08-20:* the founder's add/omit rulings above stand. New facts from the delta: the
`AdLayers` fixture tree gained an "Auto layout" row; Group/Rectangle/Ellipse rows now select
their new schemas (formerly dead clicks); active rows can carry a new `accented` treatment
(`layerRowAccented`); layer icons now include `layout-template` and `square-dashed`.

### 3.7 Brand system (token-first editing)

DesignTokensSection (Fill / Stroke / Stroke-width / Radius / Opacity tokens, per-bucket,
`Concrete value` escape) · Style Summary with Token/Raw/**Missing token** status ·
BrandKitPanel (kit@version select, Medium select `digital/ad/email/print/direct_mail`, Brand
check, Compatibility) · ColorSwatchControl's token-group-first popover. The dummy's only token
surface is the two hardcoded button chips firing a `token-picker:*` action nobody handles.
(The dummy's ColorControl is hex/HSV-first — near-opposite philosophy.)

### 3.8 Slots / personalization

SlotInspector (Mark/Unmark slot, key/label/type over 11 content types, required, placeholder,
fixtures, overflow policy over 7 modes, readiness notes) · WorstCasePreviewPanel. No dummy
concept.

### 3.9 Whole panels / modes with no dummy analogue

Right-rail mode tabs (**Inspect / Assets / Agent / Diagnostics**) · AssetBrowserPanel (search,
kind filter, upload, Place) · AgentChatPanel (in-editor agent chat with edit-target chips,
model picker, standing instructions, per-turn Compare/Revert) · ValidationPanel + preflight ·
OperationHistoryPanel · Version-history dialog · agent review bar (**Before/After +
Accept/Reject**) · engine-disabled banner · heuristic-text-measurement banner · diagnostics
alert pill.

### 3.10 Canvas affordances (the dummy canvas is an empty div)

8 resize handles + rotate handle (22px offset) + suppression rules with on-canvas reason text ·
marquee · snap guides · margin/bleed/trim guides (Show margins, Print & bleed toggles) ·
double-click text editing (`TextEditOverlay` textarea; ⌘Enter commit / Esc cancel) · image
focal-point handle · select/hand tools · agent build-theater reveal chrome · keyboard map:
⌘Z/⇧⌘Z/⌘Y, Esc clear, **Delete/Backspace delete**, ⌘G/⇧⌘G group/ungroup, ⌘]/⌘[/⌥⌘]/⌥⌘[
z-order, arrows nudge 1 / shift-arrows nudge 10, ⌘wheel zoom. (No duplicate ⌘D, no ⌘A, no
V/H/T tool keys — on either side.)

> **PARTIALLY CLOSED, 2026-08-24 (founder direction): `TextEditOverlay` is no longer a
> disparity — it is ported.** `SceneTextEditOverlay` in
> `apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx` is the
> upstream surface, presentation and all (DOM textarea over the node, style-matched, ⌘/Ctrl+
> Enter or blur commits, Escape cancels), over pure decisions in
> `adapter/scene-text-edit.ts`; the double-click drill-out to the top-level container came
> with it. Plan: `docs/superpowers/plans/2026-08-24-rich-text-editing.md` (rung B). Two
> platform gates upstream does not have ride along — a locked node opens no session, and Gate
> G-H refuses to open one mid-turn. The rest of this line (rotate handle, marquee, snap/margin
> guides, focal-point handle, tools, reveal chrome, the keyboard map) stays a real disparity.
> Upstream defers span AUTHORING too, so the overlay is plain text on both sides until rung C
> lands the range-styling toolbar.

---



## 4. Where the dummy is *richer* than the MVP editor

For completeness — dummy-designed capabilities the real editor's UI cannot currently do (the
engine mostly can):


| Dummy capability                                                             | Engine                                                                                                                                            | MVP editor UI                                                                                                                                                   |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Gradient editing** (2–6 stops, positions, angle, add/remove, live preview) | full gradient model on any fill + page background                                                                                                 | read-only guard ("edit in Appearance" — no such section) -- in the platform's frontend, make use of proper integration between the dummy editor and the engine. |
| **Custom color authoring** (HSV plane + hue slider + hex + recents)          | `Color::{Hex,Oklch,Token}`                                                                                                                        | native OS `<input type="color">` only (Fill via popover Custom row; Stroke is native input directly)                                                            |
| Size-preset *menu* on the artboard (one-click)                               | `PagePreset`                                                                                                                                      | preset field is read-only; presets only at page-creation (PageRail)                                                                                             |
| Zoom preset menu                                                             | —                                                                                                                                                 | continuous only                                                                                                                                                 |
| Export: JPEG format, transparent-background toggle                           | export contract has `Svg/Png/Pdf/FigmaManifest` — **no JPEG**; transparency not surfaced in editor UI (presence in the raster options unverified) | PNG/SVG/PDF only, no transparency toggle                                                                                                                        |
| Visibility (eye) per element                                                 | no model field                                                                                                                                    | none                                                                                                                                                            |
| Link on image/button                                                         | no model field                                                                                                                                    | none                                                                                                                                                            |


---



## 5. Export comparison --> keep all the options from the dummy editor, no visual disparity. add the options of engine which are extra as well to the frontend, with them coherent to the dummy editor. use gstack browser skill to show me the appearance of the options you will add to platform editor which are not there in dummy.


| Control                | Dummy `image-export-menu.tsx`                                           | MVP editor `ExportMenu` (popover)                                 | MVP editor `ExportPanel` (sidebar)                                                 |
| ---------------------- | ----------------------------------------------------------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Formats                | PNG, **JPEG**, SVG, PDF                                                 | PNG, SVG, PDF (with per-format hint copy)                         | SVG, PNG, PDF                                                                      |
| Scale                  | 1x–4x, raster only                                                      | 0.5/0.75/1/1.5/2/3/4× shown as DPI (48–384), PNG only, default 2× | same presets + live px estimate + 150 MP limit warning                             |
| Transparent background | checkbox, PNG/SVG only, auto-cleared on switch                          | —                                                                 | —                                                                                  |
| Pages scope            | — (single artboard assumed)                                             | All pages (N) / Current                                           | Selected artboard / All artboards                                                  |
| PDF intent             | —                                                                       | Digital (preview) / Print (bleed, embedded fonts)                 | via profile                                                                        |
| Bleed & marks          | —                                                                       | Bleed+marks / Bleed only / None (print intent)                    | same, + booklet advisory                                                           |
| Color                  | —                                                                       | sRGB / CMYK (print intent)                                        | CMYK checkbox (disabled under Proof)                                               |
| Print extras           | —                                                                       | bleed-missing warning notes                                       | Booklet imposition, Proof export, print-ready pill, per-artifact download rows     |
| Profiles               | —                                                                       | —                                                                 | Profile select (saved profiles; save/remove wired but **no UI buttons call them**) |
| Preview region         | collapsible preview with `data-artifact-export-preview="ad"` mount hook | —                                                                 | Generate preview + ExportPreviewSurface                                            |


---



## 6. Value-vocabulary mismatches (option-list level)



### 6.1 Artboard size presets — three conflicting sets


| Dummy `SIZE_PRESETS`                  | Editor PageRail quick sizes                          | Engine `PagePreset`                                       |
| ------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------- |
| Linkedin square (1:1) — **1024×1024** | Square Ad — **1080×1080** px                         | —                                                         |
| Instagram portrait (4:5) — 1080×1350  | Portrait Social — 1080×1350 px                       | —                                                         |
| Story (9:16) — 1080×1920              | —                                                    | —                                                         |
| —                                     | LinkedIn Wide — **1200×628** px                      | LinkedinAd — **1200×627** px *(off by one from PageRail)* |
| —                                     | Email Header — 600×800 px                            | —                                                         |
| —                                     | A4 print 210×297mm / US Letter 8.5×11in (flag-gated) | A4 / UsLetter / EnvelopeDl                                |
| —                                     | free W/H + unit pt/px/mm/in                          | Custom                                                    |




### 6.2 Other option-list deltas


| Facet             | Dummy                                                                                                                          | MVP editor / engine                                                                                                                               |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Fonts             | Inter, Satoshi Variable, Season Serif, DM Mono (closed select; Season Serif/DM Mono have no font stack even in the dummy repo) | free-text family; real vocabulary = 4 bundled Inter statics + ~27-family curated library + brand-kit faces (TTF/OTF only) --> use these only.     |
| Font sizes        | closed list 12–32                                                                                                              | free number ≥ 1 (+ size token in model) --> use these only                                                                                        |
| Weights           | Regular/Medium/Semi Bold/Bold                                                                                                  | 100–900 numeric; toolbar names all nine --> already gave my ruling on this at the start                                                           |
| H-align           | 3                                                                                                                              | 4 (adds Justify) -- add the justify to actual one                                                                                                 |
| Opacity           | absent                                                                                                                         | 0–1 scale, step 0.05 (+ token) — *not* a percentage --> add it ot the paltform frontend                                                           |
| Image fit         | Fit/Fill/Stretch/Tile                                                                                                          | contain/cover/crop + focal point                                                                                                                  |
| Zoom              | 23/50/75/100 preset strings --> use this but add more options like i said before.                                              | continuous 10–200% + fit current/all                                                                                                              |
| Color model       | hex/HSV + 6 fixed theme swatches + recents                                                                                     | token-first buckets (Text/Surface/Palette) + native color; engine also Oklch                                                                      |
| Text wrap default | n/a                                                                                                                            | UI displays `wrap` as fallback but the **model default is** `no_wrap` (`scene.rs:902-919`) — a known UI/model divergence to not replicate blindly |
| Units             | px implied                                                                                                                     | pt/px/mm/in; "Dimensions use the active page unit"                                                                                                |

*Additions 2026-08-20 (from the new schemas):* **Opacity** is now designed in the dummy as a
`%`-prefixed field showing `100` — the engine/editor scale is **0–1** (unit conversion at the
seam, §OQ-3). **Width/Height mode** selects are designed but show only `Fixed` — the
editor/engine vocabulary is Fixed/Hug/Fill (§OQ-2). **Align X/Y** selects show
`Space between`/`Center` — engine has start/center/end/space_between/stretch. **Alignment
icons** now exist in two families (old `align-left…` on text; new `align-start-vertical…` on
the new schemas). The earlier opacity row above is superseded accordingly.



---



## 7. Interaction & write-path differences (context for wiring, still no decisions)

1. **The dummy is stateless per schema** — four independent `useInspectorController` islands,
  state lost on selection change; the editor binds every control to the live scene and commits
   ops per change (NumberField commits on every keystroke — no blur/Enter gate,
   `fields.tsx:109-148`).
2. **Selection semantics**: dummy = one flat `selection` string driven by `?selection=` or layer
  clicks; editor = real node ids, additive multi-select, but **no multi-select inspector**
   (sections bind to the primary node; only Arrange consumes the full set).
3. **The lock model differs**: dummy lock is a header toggle per schema; editor lock gates
  every section, reorder, delete, nudge, and handles — plus the *pinned / layout-managed /
   freehand* triad (Detach/Re-attach, `directGeometryEditable`) that the dummy has no vocabulary
   for at all.
4. **The editor has states the dummy never designed**: engine-disabled (stamp mismatch),
  degraded text measurement, agent-running (toolbar hidden), preview/compare mode, diagnostics
   pills — each is a user-facing state that will need a ruled home if it can occur in the
   platform mount.
5. **Agent turn review** (Before/After + Accept/Reject bar) is an editor-side surface with no
  dummy analogue — relevant because scene agent turns are propose→accept (unlike web turns).

---



## 8. Provenance & unknowns

- Dummy inventory: port-of-spain scout sweep 2026-08-19 (43 tool calls) + direct `diff`
verification that `apps/frontend`'s `image-inspector.tsx`/`image-export-menu.tsx` are
byte-identical to dummy HEAD.
- MVP-editor inventory: dedicated enumeration scout 2026-08-19 (67 tool calls), scope-pinned to
`subsystems/clue-design` only; engine facts cited to `lumen-core` sources.
- Carried unknowns (from the scouts, to close during AD-R if they matter to a ruling):
whether CanvasKit or Konva is the default renderer in a dev run (`.env.development`
unchecked; CanvasKit is canonical per `docs/frontend-practices.md`); possible additional
on-canvas affordances inside `CanvasKitCanvas.tsx` beyond the enumerated set (read by
targeted grep, not end-to-end); whether the export raster options carry a transparency flag
(not surfaced in either editor UI; contract unverified); the agent authoring-vocabulary
conclusion (Frame/AutoLayout/Text/Image-dominant) is inferred from prompts + DSL, not from a
trace corpus; visual form of some editor controls (segmented vs plain button rows) is
classified from DOM structure, not CSS.
- **Revision-2 provenance (2026-08-20):** the four new schemas were read directly (full
`ad-dummy-inspectors.tsx` + `git diff` of `image-inspector.tsx`, `inspector-primitives.tsx`,
`web-inspector.tsx`, `model/chat-shell.ts`, `chat-shell.module.css`) in the
`/Users/aryankeshri/Documents/clue-hq/clue-frontend` checkout, where they existed as an
uncommitted working-tree delta on `c7f2bc5` **[since committed locally as `32658ff`,
2026-08-20; the AD0.1 lift `cmp`-verified against that commit]**. `web-inspector.tsx` (+32/−17)
also changed upstream (defensive selection-narrowing), so the platform's lifted web-inspector
copy is now behind the dummy by that delta — a re-lift consideration for AD0, functionally
inert for the web editor.

