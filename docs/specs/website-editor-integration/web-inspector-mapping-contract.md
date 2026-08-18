# Website-editor inspector — frozen mapping contract (v1)

Status: FULLY RATIFIED by founder 2026-08-17 — all 42 items resolved (§6 records the closing
rulings on the final three).
Decision record: `docs/specs/website-editor-integration/decisions-recorded.md` (founder-annotated,
authored in the `singapore` workspace; the annotations there are the authority — this document is
the frozen, implementable restatement). Source inventories: the five Part-IV deep-reads
(dummy-UI control inventory; web-stack inventory; scene-stack inventory; services inventory;
custom-component pipeline inventory), session 2026-08-17.

Scope: the **website (web) editor inspector only** — the dummy chat-shell inspector
(`clue-frontend@codex/chat-shell`, `src/features/chat-shell/components/web-inspector.tsx` et al.)
bound to the real web editor stack (`subsystems/clue-design/apps/editor`, `WebInspectorPanel` /
`webClassFacets` / `webDocuments`). The ad/scene editor, chrome (tabs/versions/export/share), and
streaming are separate flows with their own contracts.

**Standing rule (founder, absolute): visual parity with the dummy UI.** The dummy is the ceiling
and the baseline. The ONLY deviations are the founder-ordered deltas in §2. Nothing else may be
added, moved, or restyled.

---

## 1. Wired and functional in v1

| # | Control (dummy) | Real backing | Mapping notes |
|---|---|---|---|
| 1 | Canvas → Background color | `bgColor` facet on page root | theme tokens only (R2) |
| 4 | Text → Typography color | `textColor` facet | tokens only |
| 5 | Text → Size select | `textSize` facet (Tailwind ramp) | 12→xs 14→sm 16→base 18→lg 20→xl 24→2xl 32→3xl; **13 dropped from options** |
| 6 | Text → Weight select | `fontWeight` facet | Regular→normal, Medium→medium, Semi Bold→semibold, Bold→bold |
| 7 | Text → Horizontal alignment | `textAlign` facet | left/center/right (justify unexposed) |
| 11 | Image → Link to (URL + new tab) | image props `href`/`new_tab` | shown for image selections; optional per image |
| 12 | Image → Replace image | asset-store upload + `replace_asset` op (+`upsert_asset` when new) | dummy's direct-file-upload UX preserved |
| 13 | Image → Mode select | `objectFit` facet | Fit→contain, Fill→cover, Stretch→fill; **Tile dropped from options** |
| 14 | Image → Shape/Radius (all + 4 corners) | **NEW radius facet** in `webClassFacets.ts` | founder-approved engine addition; corner classes `rounded-*` family |
| 15 | Button → Link to | button props `href`/`new_tab` | note §4: action stays link-mode only |
| 16 | Button → Style select | button `variant` prop | Primary→primary, Secondary→secondary, Transparent→ghost; **Critical dropped** |
| 17 | Button → Bg/Text color token buttons | `bgColor`/`textColor` facets | token-list popover using the dummy's existing Theme-tab pattern |
| 19 | Container → Style tokens | `textColor`/`bgColor` facets | tokens only |
| 20 | Container → Flex/Grid/Hide segmented | `display` facet | Flex→flex, Grid→grid, Hide→hidden (block/inline-flex unexposed) |
| 22 | Section → Direction / Gap / Wrap | `direction`/`gap`/`flexWrap` facets | typed gap coerced to nearest step (0,1,2,3,4,6,8,10,12,16,20,24) |
| 34 | Custom component → props form | manifest `props_schema` → `set_custom_component_props` | the existing schema-driven form, shown when a custom component is selected |
| 40 | Header visibility eye | `display` facet `hidden` value | wired as a real hide/show toggle |
| 41 | Layers tree | real document node hierarchy | names/kinds/selection from the doc; **nesting display capped at depth 1** |
| R3 | Padding | `paddingX`/`paddingY` facets | **UI collapses 4 boxes → 2 (X/Y)** (founder-ordered delta) |

Conditional-display rule (item 3, founder-specified): the **Text → "Link to" section is hidden by
default** and appears — functional — **only while a rich-text range is selected** (i.e. during a
canvas rich-text editing session with a live range). It binds to the rich-text range link
(`set_class_facet`-adjacent range link op via the rich-text commit path), never to a whole-node
href (which does not exist for text).

## 2. Founder-ordered UI deltas (the only permitted deviations from the dummy)

- Padding: 4 per-side boxes → 2 axis boxes (R3).
- Typography gains a **text style/variant select** (display/h1/h2/h3/h4/body/small/overline →
  `set_node_props` text `variant`; heading options disabled for structured rich text, engine rule) (25).
- Typography gains a **line-spacing select** (none/tight/snug/normal/relaxed/loose → `lineHeight`
  facet) (26).
- Text "Link to" becomes conditional per §1's rule (3).
- Image Mode loses "Tile" (13); Button Style loses "Critical" (16); size-select orphan handling per §6.
- Icon selections show **only Layout/padding** — icon-specific sections (icon select, token colors,
  size, stroke) are hidden (18b).
- Section "Link to" hidden (23). Text vertical alignment hidden (8).

## 3. Visible but deliberately INERT (dummy stays dummy)

- Font family select (R1 — no font-family facet; theme owns fonts).
- Custom/hex tab of the color popover (R2 sub-ruling — Theme tokens tab is the live one).
- Canvas background color-opacity input (2).
- Text Stroke section, exactly as the dummy ships it (9).
- Header lock toggle (39 — no web `locked` field; scene-only concept).

## 4. Invisible-but-alive (agent-only; no UI; data round-trips guaranteed)

- Slot keys / personalization / per-account batch (27).
- Raw CSS-classes escape hatch (28).
- Margin X/Y (30).
- Background-image + scrim system on section/container (35).
- Button dialog actions (`show_modal`/`close` + target) — inspector edits link mode only (36).
- Image alt text (37).
- `tag`/`anchor_id` on sections: **hard data-integrity guarantee** — every write path we introduce
  must round-trip these props unchanged (38).
- Node move/duplicate/delete: **keyboard-only** for now (29).

## 5. Hidden/dropped surfaces + fallback rule

- Computed-layout read-only card: dropped from UI (31).
- **Unknown/unmapped selection kinds → show Layout(-padding) only**: applies to embeds (32) and
  the interactive components dialog/accordion/marquee/carousel/tabs/nav-menu (33). The components
  keep working on the page; their prop tuning is agent-only for now.

## 6. Closing rulings (founder, 2026-08-17 — resolving the final three)

- **(5)** Size select: **drop 13 only**; 32 maps to 3xl. (Reflected in §1.)
- **(24)** Rich-text toolbar on double-click: **KEEP as-is, confirmed** — it is also the
  mechanism that makes item 3's conditional Link-to implementable (range selection exists only
  inside the toolbar's editing session).
  **Amended 2026-08-18 (founder): retheme, don't relocate.** The toolbar stays floating at the
  selection with its mechanics, control set, and commit path untouched, but its *visual* parity
  baseline moves from the source editor's token literals to the platform inspector's design
  language (`--clue-ds-*` tokens, inspector control shapes/radii/states), so canvas editing
  reads as one system with the inspector. Behavior parity with the source remains binding;
  only the skin changed.
- **(39)** Header lock toggle: **inert for now** (visible, non-functional — no web `locked`
  backing). Added to §3.

## 7. Future-work register (founder: "make a special note — we will work on this")

Tracked, never silently dropped; each needs a UI slot decision when its turn comes:

1. Container-level direction / h-v alignment / wrap / grid-columns / gap / click-action link (21).
2. Embed inspector proper (URL/snippet modes, provider handling) (32).
3. Interactive-component prop cards in the UI (33).
4. Item-16 adjunct: a `critical`/destructive button variant engine-side, if a campaign ever needs it.
5. Failure-feedback surfaces (save-failure, version-refused, 409/422, publish-failure) — the four
   one-question founder decisions deferred to their implementation flows (42). **Save-failure +
   409/422 DECIDED 2026-08-18 (W3.3): inline only — the single note/error line under the
   inspector header; no additional UI. Trade-off accepted: a failure can be missed or become
   invisible when the inspector closes. Version-refused and publish-failure remain open for
   their flows.**
6. **In-canvas node resizing** (added 2026-08-18, founder-ordered registration). Absent from the
   42-item inventory because the dummy inspector has no resize control (the computed-layout card
   was dropped by 31; drag handles exist only in the retired dev shell, which is not the parity
   baseline) — so nothing here was silently dropped; it was never in scope. The substrate is
   ready when its turn comes: the ported bridge listener already carries the `resize-node`
   callback (in-frame handle resize → width/height px per axis), and the engine's width/height
   facets exist. Entering scope requires a founder ruling on BOTH the capability and its
   affordance (in-canvas handles vs an inspector field — the dummy offers neither today).
   Companion note: node *moving* is NOT this item — it stays governed by ruling 29
   (keyboard-only for now, §4) and the W4.10 audit.

7. **[ENTERED SCOPE 2026-08-18 — founder §8 amendment, item 2; see §8]** ~~Canvas/page-root background — wired but unreachable (added 2026-08-18, W4.5).~~
   Row 1's inspector side is DONE (the canvas Background control feeds the real
   theme-token popover and emits the sanctioned write; the page root is a Container, so
   the existing background write path serves it). But `lumen-web`'s `render_page` renders
   only `root.children` into `<body>` — no element carries `data-node-id="root"` (so
   nothing can select the root: a background click clears selection, and the layer tree
   starts at the root's children) — and `root.classes` is dropped at render, so even a
   written `bg-<token>` paints nothing. Closing this needs a small engine change (render
   the root's classes onto `<body>` + a root-selection path), which §8 does not authorize
   — entering scope requires a founder §8 amendment. Until then the control is
   honest-but-inert (the dummy's own visual state; the W3.1 null contract drops its
   events), and the frontend needs zero further work when the gap closes. Full analysis:
   the in-code note at `web-inspector.tsx::CanvasControls` + `_memory/2026-08-18-w45-canvas-background.md`.

## 8. Engine-side work authorized by this contract

~~Exactly one item~~ **Exactly two items** (second added by founder amendment, 2026-08-18):

1. The **radius facet** family in `webClassFacets.ts` (+ its parse/set tests), covering
   `rounded` all-corners and the four per-corner variants used by the dummy's Shape
   section. **[DONE — W4.1]**
2. **The page-root render fix** (closes §7 item 7 / contract row 1): `lumen-web`'s
   `render_page` emits the root's classes onto the page body element (all render modes —
   published pages start honoring page backgrounds, the intended truth) and stamps the
   root's node id per the existing editor-mode attribute gating, so a click on empty page
   background resolves to the root and opens the Canvas schema (replacing the old
   click-clears-selection behavior — ratified with this amendment). Scope is that one
   render emission + its tests + whatever minimal frontend join change is needed for a
   root selection to hydrate; nothing else in the engine.

No other engine change is authorized for the web-inspector flow.
