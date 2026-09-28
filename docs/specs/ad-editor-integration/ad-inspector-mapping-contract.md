# Ad-inspector mapping contract — v1

**Status: RATIFIED 2026-08-20 (founder), FROZEN.** Do not re-litigate rows here; changes require
a new founder ruling recorded as a dated amendment.

Decision trail: `ad-editor-disparity-inventory.md` (founder-annotated, Revision 2 + the
OQ-1…OQ-8 rulings block) and the founder's final rulings message of 2026-08-20. This contract
is the single normative restatement; where wording differs, the founder's annotations govern.

**Amendments — 2026-08-20 (founder, post-freeze follow-up):**
1. The item-5 interpretation flag is resolved: the founder confirmed **both** removals stand —
   the two Link-to sections are removed **and** the button schema is hidden in v1. §2.7 and §5
   remain exactly as written.
2. **§1.8 multi-select re-ruled.** The merged-panel preference was made conditional on effort
   ("see if it's a huge effort — then keep it out of scope for now"). Effort assessed as large
   (net-new design existing in neither source; a "Mixed" presentation *and* edit semantics for
   every control kind; one edit fanning out to N node patches in a single CAS batch under
   per-node lock/token rules) → the merged panel is **out of v1 scope**. v1 shows the
   first-selected element's schema; Arrange acts on the whole selection. Deferred to §7;
   its §6 mockup leaves the active queue.
3. **D7–D10 closed as recommended** (founder approved the pre-build list containing the
   standing recommendations): D7 drop the Konva fallback from the lift; D8 asset/font bytes via
   a narrow headerless BFF passthrough; D9 engine-stamp mismatch = loud banner + read-only
   canvas (wording still §6-gated); D10 CAS conflict = web-style "document moved on" reload
   message (wording still §6-gated). Mirrored into the plan's §5 register.

**Amendment 4 — 2026-08-21 (founder): Gate G-D closed; §6 item 5 is built.**
Ruling, verbatim: *"approve them as is from the mvp editor only, no separate banner needed…
secondly, for readonly also keep them same as that in other mode only"*, then on the rendered
preview: *"all 4 previews look good… proceed with them just the way you showed them to me."*
Therefore:
- **No new banner is designed.** The MVP editor's own `EngineDisabledBanner` and
  `HeuristicMeasurementBanner` (`subsystems/clue-design/apps/editor/src/components/EditorChrome.tsx:200-288`
  + `app/styles.css:912-974`) are ported whole — copy, glyph, geometry. A unit test asserts
  every sentence against that source file, so the two editors cannot quietly fork their voice.
- **Read-only is not special-cased.** The engine-stamp/handshake state gets the *same* canvas
  treatment as degraded text (the second half of the ruling), not a bespoke read-only surface.
- **The CAS conflict adds nothing:** it remains the inspector's existing note line
  ("Document moved on — reloaded.", D10). The ad inspector already carries that `note` slot
  from AD2.7; AD3's committer supplies the string.
- **Three deviations, disclosed at the preview and taken with it:** (a) the banner background
  is opaque — upstream's `rgba(207,45,86,0.15)` wash is only legible over that editor's always-light
  workspace and vanished over a dark artboard, so it is composited to `#efd7dd`; (b) the two
  banners **stack**, where upstream pins both at `top: 14px` and would overlap them; (c) the
  command chip names *this* repo's remedy (`npm --prefix ../../subsystems/clue-design/apps/editor
  run build:wasm`, the string our own `copy-design-vendor.mjs` prints, and
  `node scripts/copy-design-vendor.mjs`) rather than the design subsystem's `npm run build:wasm`,
  which does not exist in `apps/frontend`. Instructions that cannot be followed are not copy.
D9's "loud banner" half is now literally true rather than mechanism-only; §6 item 5 leaves the
queue, which is down to four.

Sources it binds:
- **Dummy surface:** `clue-hq/clue-frontend` branch `codex/chat-shell` — `c7f2bc5` **plus the
  co-founder's 23-file ad-schema delta** (per OQ-8 it is now committed locally at
  `/Users/aryankeshri/Documents/clue-hq/clue-frontend` as `32658ff` — "feat: add dummy ad
  inspector variants", parent `c7f2bc5` — and the AD0 lift pins byte-verification to that
  commit: `32658ff`).
- **Engine/editor:** `subsystems/clue-design` scene editor + `lumen-core` (anchors in the
  inventory).

Inherited laws (verbatim from the website-editor precedent): the dummy UI is baseline and
ceiling; §6 items ship only after the founder approves visual mockups; engine changes are
enumerated in §8 and capped; never browser→FastAPI (all traffic through `/api/clue/design`);
components never import transport or the engine.

---

## §1 — Wired surface (control → engine, by schema)

### §1.0 Header (every schema)
- **Title** = the real node's display name (editor naming; no `Text34` Figma artifacts).
- **Lock** toggle → `Node.locked`; lock gates every write for that node (editor rule).
- Visibility (eye): **removed** (§5). Ellipsis: stays present-and-inert (§3).

### §1.1 Canvas (page) schema — selection empty / artboard
| Control | Binding |
|---|---|
| Size preset select | 3 presets with **corrected values, dummy labels** — LinkedIn square (1:1) **1200×1200**, Instagram portrait (4:5) 1080×1350, Story (9:16) 1080×1920 — plus **Custom** which reveals W/H inputs (**px only**); writes `update_page` (manual W/H ⇒ `preset:"custom"`) |
| Background — Fill | **edits the root frame's fill** (founder ruling; the page-background property is not the edit target). Solid via ColorControl under the §1.6 color policy; Linear/Radial via the dummy's full gradient editor (2–6 stops, positions, angle) → `Paint::{LinearGradient,RadialGradient}` |
| Layers | the real scene tree (§1.7) |

Canvas chrome (from the founder's Figma mocks): artifact name at the artboard's **top-left**
(display-only; rename lives in the tab/action menu) and the **W×H dimensions chip at the
bottom-center edge**. Safe-margin/bleed have **no user controls** (agent-only concerns).

### §1.2 Text schema
| Control | Binding |
|---|---|
| Color | text fill (`Node.fills`) under the §1.6 color policy |
| Font select | populated from the **real font vocabulary**: bundled Inter + curated font library + brand-kit faces (TTF/OTF); the dummy's Satoshi/Season Serif/DM Mono entries are gone unless present in the library |
| Size | **free number ≥ 1** (replaces the closed 12–32 list) |
| Weight | select of the **nine named weights** (100 Thin … 900 Black) ↔ numeric `font_weight` |
| H-alignment | **4 toggles** (Justify added) → `TextAlign` |
| V-alignment | 3 toggles → `valign`; disabled when height mode is hug (editor rule) |
| Stroke color + width | `Node.strokes` (width 0 clears) |
| Position X/Y, Rotation | `transform` (pinned nodes → `absolute_box`); freehand/lock gating per editor |
| Arrange | §1.5 semantics |

Per **OQ-4** the new Layout section does **not** extend to text (nor image/button): text keeps
exactly Position X/Y + Rotation. Text content editing, line-height, letter-spacing, case,
italic/underline/strike, etc. stay **off the v1 surface** (§5; the engine retains them).

### §1.3 Image schema
| Control | Binding |
|---|---|
| Fill — Image upload | kept (founder ruling): file picker → asset upload (`POST /assets`) + `place_asset_in_node` |
| Fill — AI suite | adopted from the MVP editor, restyled to the dummy design language: Alt text · Generate (prompt) · Edit (instruction) · Remove background · Before/After candidate review (Accept / Reject / Save-as-new) · asset status line |
| Mode | **Fit / Fill / Crop** (dummy labels on engine behaviors `contain`/`cover`/`crop`); choosing Crop reveals the focal-point control (§6 mockup-gated) → `asset_placement` + `FocalPoint` |
| Shape — Radius | all + four corners → `Node.corner` (a raw radius write clears `corner.token`, editor rule) |

"Link to" is **removed** (§5). Stretch/Tile are **dropped** (§5).

### §1.4 The four new schemas (auto-layout / rectangle / ellipse / group) + plain Frame
Composition exactly as the co-founder designed (inventory §2.6), with rulings applied:
- **Plain Frame** renders the **auto-layout schema minus its Auto Layout section**
  (= Shape + Stroke + Layout + Arrange + Layers) — OQ-1.
- **Auto Layout section** (auto-layout only): Direction Row/Column · Wrap · Gap · Grow ·
  Pad T/R/B/L · Align X/Y (Start/Center/End/Space between/Stretch) → `AutoLayoutProps`.
  Gap/Padding **tokens** and **fill weights** stay out (OQ-2; §5).
- **Layout section** (all four + Frame): X/Y · W/H · Rotate · **Opacity displayed as %,
  converted to the engine's 0–1 at the seam** (OQ-3) · Width/Height **mode = Fixed/Hug/Fill**
  with the "Width fixed"/"Height fixed" inputs shown **only in Fixed mode** (OQ-2).
- **Shape**: fill (color policy §1.6) + radii (rectangle & auto-layout; ellipse has no radii).
  **Group deliberately has no Shape/Stroke** (OQ-6).
- **Stroke** (all except group): color + width → `Node.strokes`.
- **Arrange** (§1.5) and **Layers** (§1.7).
- Header lock/eye on these kinds follow §1.0 (OQ-7), not the scaffolding's disabled state.

### §1.5 Arrange semantics (all schemas) — OQ-5
Editor semantics govern everywhere: z-order (4 buttons → `move_node`; edge-disabled, with the
⌘]/⌘[/⌥⌘]/⌥⌘[ shortcuts); alignment (6 modes, enabled at **2+ unlocked freehand nodes** —
nodes align to each other, no align-to-page); distribution (**3+ nodes**); Group (**2+
unlocked same-parent siblings**) / Ungroup (**single container**) with ⌘G/⇧⌘G.

### §1.6 Color policy (all fill/stroke/text color controls) — founder ruling (c)
Brand-kit colors are offered **first** in the picker; **custom hex is allowed**, accompanied by
the small "this leaves your brand palette" note (§6 mockup-gated wording/design). A raw color
on a token-bound element detaches its brand binding — that is the accepted, *informed* trade.

### §1.7 Layers panel (all schemas)
Real recursive tree, any depth · kind glyphs incl. fill-swatch squares for Rect/Ellipse ·
additive multi-select (shift/⌘-click) · auto-scroll to primary · **no** up/down reorder
buttons (z-order lives in Arrange) · container rows keep the dummy's collapse/expand chevrons ·
the new `accented` active treatment.

### §1.8 Multi-select — v1: first-selected schema (amendment 2, 2026-08-20)
When N elements are selected, the inspector shows the **first-selected element's schema**;
Arrange acts on the whole selection (the MVP editor's behavior). The earlier merged-panel
override was conditional on effort and the effort is large (see amendment 2), so the merged
panel — common sections with per-field "Mixed" presentation — is **deferred to §7**, and
re-enters mockup-gated when picked up.

### §1.9 Canvas interaction — founder ruling (b)
Click-to-select via engine `hitTest` (selection outline) · **drag-to-move** ·
**corner-resize handles** — visuals mockup-gated (§6). NOT in v1: rotate handle, double-click
text editing, marquee, Delete-key deletion, arrow-key nudge (§7). Undo/redo: wired
(action-menu rows + ⌘Z/⇧⌘Z).

> **SUPERSEDED IN PART, 2026-08-24 (founder direction) — double-click text editing IS
> SHIPPED.** The rich-text plan
> (`docs/superpowers/plans/2026-08-24-rich-text-editing.md`, rung B) lifts it out of the
> not-in-v1 list above: a double-click on a text node opens a real caret session on the
> canvas — the design subsystem's `TextEditOverlay` ported (a DOM `<textarea>` over the node,
> style-matched, editing the stored content), with the node's painted glyphs suppressed for
> the duration. A double-click on anything else drills the selection out to its top-level
> container. **The contract:** commit on blur or ⌘/Ctrl+Enter as ONE `updateTextNode` batch —
> one atomic edit, one undo frame — Escape cancels and writes nothing, and an unchanged draft
> writes nothing either. **The gates are unchanged and still bind:** a LOCKED node opens no
> session (§1.0/§4), Gate G-H refuses to OPEN one mid-turn (an already-open session is not
> force-killed — D10 CAS is the net), and a node the reload took away closes its session and
> discards the draft. Ruling C-9's freeze-on-grab deliberately does not fire for a text
> session: a layout-managed node edits its content and the solver re-solves around it.
> Everything else in this line — rotate handle, marquee, Delete-key, nudge — stays §7.

### §1.10 Zoom & viewport
Dummy-style dropdown, options **10%–150% in 5% steps, scrollable**; **fit-on-open** (initial
zoom fits the artboard and displays the nearest step).

### §1.11 Export
Dummy menu at visual parity, with: Formats **PNG / SVG / PDF** (JPEG dropped in v1 — founder
ruling 7a) · Scale 1x–4x (raster only) · Transparent background checkbox (PNG/SVG) — pending
the §8 verification · direct download (no new preview panel; the menu's designed collapsible
preview region hosts the real render via its `data-artifact-export-preview="ad"` hook) ·
engine print extras (PDF digital/print intent, bleed & marks, sRGB/CMYK) enter **only after**
their in-dummy-style browser mockups are approved (§6).

### §1.12 Artifact action menu
Dummy visual parity. Wired now: Rename (artifact title), Undo, Redo. Versions flyout:
present-and-inert in v1, bound to real history as a fast-follow (§3/§7). Duplicate / Archive /
Delete: §7 (platform artifact semantics, not yet backed).

---

## §2 — Founder-ordered deltas from the dummy surface
1. Size preset select gains **Custom** (reveals W/H, px only); preset **values corrected**
   (LinkedIn square 1024×1024 → **1200×1200**), labels kept.
2. Font size select → free number; weight select → nine named weights; H-alignment gains
   **Justify**.
3. Font family options replaced by the real library/kit vocabulary.
4. Image Mode options → **Fit / Fill / Crop**.
5. Zoom menu options → 10–150% @ 5%, scrollable.
6. Export menu loses **JPEG** (v1).
7. Both **"Link to"** sections removed; **button schema hidden** (v1); header **eye** removed.
8. Opacity fields display % (engine 0–1 under the hood).

## §3 — Visible-but-inert (dummy parity preserved, provably no-op)
- Header ellipsis "More actions" (inert in the dummy too).
- Versions flyout (Current/V3/V2/V1) — inert until the fast-follow binds real history.

## §4 — Write rules (data integrity)
- Every mutation ships as scene operations through the **editQueue CAS** (`base_version` on
  every batch; one in-flight batch; success → resync without keyed remounts on write tokens).
- `FieldPatch` three-state discipline (`unchanged|set|clear`) — partial updates are explicit;
  never resend unrelated fields as `set`.
- A raw radius write clears `corner.token`; a raw color write detaches the brand binding
  (with the §1.6 note); % opacity converts to 0–1 at the seam; preset writes are `update_page`.
- Lock gates every write path; align/distribute/group respect the §1.5 enablement rules.
- CAS-conflict UX posture: **RULED (D10, 2026-08-20, amendment 3)** — web-style
  "Document moved on — reloaded" + quiet reload; message wording stays §6-gated.

## §5 — Hidden / dropped (no v1 surface; engine capability unaffected)
Eye toggle · both Link-to sections · the button schema · JPEG · image Stretch/Tile · the tool
palette (founder ruling 1: out of v1) · fill-weight inputs · Gap/Padding token selects ·
safe-margin/bleed controls (agent-only) · Document Title/Artifact Type/Unit/Orientation fields
(title = artifact name; name/dims render as canvas chrome) · PageRail/multi-page (**single
artboard confirmed 100%** — "one ad is one artifact") · slots/personalization ·
assets/agent/diagnostics/history/validation panels (platform shell owns chat; asset entry =
the image schema) · effects editing · the §3.3-ruled text extras (content textarea,
line-height, letter-spacing, max-lines, wrap, direction, case, paragraph-spacing, style-token,
italic/underline/strike, truncate) · Line/Vector/Instance schemas (2026-08-19 ruling stands).

## §6 — Mockup-gated new chrome (build ONLY after founder approves visuals)
1. Selection outline + move/resize handles (§1.9). — **SHIPPED (AD4.C, 2026-08-22):** G-A ruled
   Variant B (commit `9c31bbcc`); outline shipped at AD2.5, the four corner handles +
   drag/corner-resize shipped in this lane.
2. The "leaves your brand palette" custom-color note (§1.6).
3. The crop focal-point dot (§1.3).
4. Export print-extras options in dummy style, demonstrated in the browser (§1.11).
5. ~~Engine-forced user-facing states~~ — **CLOSED and BUILT (amendment 4, 2026-08-21):** the
   MVP editor's two banners ported as-is (read-only shares the degraded-text treatment), the
   CAS-conflict message unchanged from D10.

(The merged multi-select mockup left this queue with amendment 2; it re-enters when its §7
item is picked up.)

## §7 — Future-work register (explicitly not v1)

> **AMENDED 2026-08-24 (founder direction): "double-click text editing" LEAVES this register
> — it is shipped.** See the §1.9 supersession note above and
> `docs/superpowers/plans/2026-08-24-rich-text-editing.md` (rung B; rung C's range styling
> rides the engine's `TextSpan` machinery and is the plan's own destination). Every other
> item on the line below stays future work.

Tool palette (insert tools) · rotate handle, double-click text editing, marquee, Delete-key,
nudge · versions-flyout binding to real history · JPEG (client-side conversion or engine
format) · multi-page/PageRail · Duplicate/Archive/Delete menu actions · text-extras surfacing ·
full brand-token editing UI (DesignTokens-style section) · effects UI · align-to-artboard ·
Line/Vector/Instance schemas · **the merged multi-select panel** (amendment 2 — net-new design,
mockup-gated when picked up). The AD1 architecture rulings D7–D10 are **CLOSED as recommended**
(2026-08-20, amendment 3) and no longer pending here.

## §8 — Engine-side work authorized
**None authorized as of v1.** One conditional candidate: if AD1 verification finds the export
raster options carry no transparent-background flag, that small engine change comes back for
individual founder authorization before implementation. No other engine change is authorized.
