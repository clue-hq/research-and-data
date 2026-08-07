# R2 — Brilliant's "blueprint" Authoring DSL + Canvas/Layout Object Model

**Audit slice:** the blueprint DSL (`knowledge/blueprint/*`) and the canvas/layout object model (`knowledge/reference/{canvas,frames,layout-guides,components,styling,vectors,text,editing}.md`).

**Bottom line up front:** Brilliant's "blueprint" is not a markup language for *positioning* elements — it is a thin textual front-end onto a full **Flutter-style constraint/auto-layout solver** with a **tokenized spacing/sizing/typography scale baked into the grammar**. The model author (the LLM) almost never types a pixel gap, a padding value, an x/y coordinate, or a width. It declares *intent* — `al(v,g($spacing.md),pad($spacing.lg))`, `s(fill,hug)`, `x(sb)` — and the engine computes every position, gap, and dimension. This is the single biggest structural reason Brilliant's compositions have good spacing/density/hierarchy and a competitor that emits absolute coordinates (or free-floating pixel sizes) does not. The relevant comparison is **constraint solver + token scale vs. absolute coordinates + free-form numbers.**

---

## 1. What kind of language is "blueprint"?

**Shape: an indentation-structured, line-per-element DSL where the tree IS the layout hierarchy.** From `blueprint/core.md` lines 3–13:

> "One element per line; 2-space indent = child. Properties are space-separated, in any order."

```
al(v,g($spacing.lg),pad($spacing.xl)) s(360,hug) f[($color.surface)] rd($radius.md) shadow($color.shadow,o($visibility.faint),y(2),blur(8)) "Card"
  t("Settings",$font.family,$font.size.lg,sb) f[($color.text.primary)] #title
  t("Manage your preferences",$font.family,$font.size.sm) s(fill,hug) f[($color.text.secondary)] #desc
  al(h,x(c),y(c),g($spacing.sm),pad($spacing.md,$spacing.lg)) s(fill,hug) f[($color.primary)] rd($radius.sm) "Button"
    svg(icon:check) s(16,16) f[($color.on-primary)]
    t("Save",$font.family,$font.size.sm,sb) f[($color.on-primary)]
```

**Primitives (the closed element vocabulary)** — `blueprint/core.md` lines 15–19. There are no CSS-style aliases; the parser only accepts these types:
- `r` rectangle, `c` circle, `t("text",font,size)` text, `line(...)` straight line (sugar over a 2-node vector), `fr` frame, `gr` group, `al()` auto layout, `svg(icon:name)` Phosphor icon, `v()` vector.
- **Only `fr` / `gr` / `al()` take children.** The line "no `rect`/`div`/`img` aliases" is explicit. This is a *narrow, validated* vocabulary, not free-form markup.

**Properties** (`core.md` 21–26): `p(x,y)`, `s(w,h)`, `rd(N)`/`rd(TL,TR,BR,BL)`, `rot(N)`, `o(N)`, `clip`, `flip(h,v)`, `front`/`back`, `abs`. Note `s()` (size) takes `number | fill | fill:N | hug` — the sizing *modes* are first-class literals in the grammar, not numbers.

**Units / values: almost everything is a token, not a number.** From `design-systems/core.md` (lines 5–17) and `reference/design-systems.md`: every color, gap, padding, radius, font-size, weight, line-height, letter-spacing, opacity, stroke-width slot takes a `$token` resolved through the active design system. There are two token vocabularies:
- **Presence ramp** (`hint faint subtle soft mid firm bold strong intense`) for brand stops, `$font.weight`, `$stroke.width`, `$visibility`.
- **T-shirt scale** (`xs sm md lg xl 2xl…Nxl` + `none`) for `$spacing`, `$radius`, `$font.size`.

Crucially, **explicit mode HALTS the call on a bare numeric in a tokenizable slot** (`core.md` line 46: "in explicit mode every color, font, and scale slot takes a `$token`; bare hex or numerics halt the call"). `reference/design-systems.md` line 326 confirms: `$spacing.N` numeric primitives are *rejected in element rows* — only role names (`xs/sm/md/...`) are permitted. The only numeric exception is `s()` sizing, which accepts bare pixel numbers.

So "blueprint" is best described as: **a declarative, tree-structured constraint-layout DSL with a mandatory design-token type system.** It is much closer to Flutter widget trees / SwiftUI / Jetpack Compose than to HTML/CSS or to an absolute-coordinate scene description.

---

## 2. LAYOUT ENGINE — exactly how layout is expressed

This is the heart of the report. Brilliant expresses layout through a **Flutter-style auto-layout (flexbox) solver**, exposed in the DSL via `al()`. Evidence spans `blueprint/layout.md`, `blueprint/layout-patterns.md`, and especially `reference/frames.md` (which documents the underlying `AutoLayoutData` model, `LayoutBehavior.flex`, hug/fill resolution, and the exact flex math).

### 2a. Auto-layout / flex / stacks
`al(v)` = vertical stack, `al(h)` = horizontal stack (`blueprint/layout.md` 7–11). This is the primary container. `reference/frames.md` maps it directly: "Auto Layout Frame (Shift+A) → Parent (Auto Layout) | Flow layout, supports wrap" (frames.md line ~21), and the model is literally a flexbox — `frames.md` calls wrap "CSS `flex-wrap: wrap` equivalent" (line ~284) and documents a `LayoutBehavior.flex` factor (default 1.0).

**Every `al()` REQUIRES a direction, a gap, and a padding** (`blueprint/layout.md` 7–8): `al(v) / al(h)` plus `g()` + `pad()` (use `$spacing.none` for zero). You cannot create an auto-layout container without declaring its spacing — the grammar forces it.

### 2b. Alignment & distribution
`blueprint/layout.md` 27–30:
> "`x()` aligns on the horizontal axis, `y()` on the vertical; values are `s`/`c`/`e`/`sb` and stay physical (never flipped by direction). `sb` (space-between) is main-axis only."

- `x(s|c|e|sb)`, `y(s|c|e|sb)` = start / center / end / space-between.
- Axes are **physical, not main/cross** — `x` always means horizontal regardless of `al(v)` vs `al(h)`. `layout-patterns.md` line 22 reiterates this ("Axes are physical, never flip with direction").
- `sb` is space-between (the engine distributes the free space). `frames.md` documents the underlying behavior precisely (line ~256): "With spaceBetween + a single child, the child is centered… With 2 children, they go to opposite edges with no middle gap," and computes `AutoLayoutData.computedItemSpacing`.
- For 3+ element even distribution there is also a command-level `distribute_horizontally`/`distribute_vertically` (`editing.md` ~256, `blueprint/commands.md` 23): `gap = (totalSpace − sumOfMiddleWidths) / (n − 1)`.

### 2c. Spacing / gap tokens & padding
- Gap: `g($spacing.md)`. Padding: `pad($spacing.lg)`, `pad(H,V)`, or `pad(L,T,R,B)` (`blueprint/core.md` 28–31; `frames.md` ~280 documents the comma-input parsing). **Both are mandatory inside `al()`.**
- The spacing scale itself is GENERATED, not hand-picked. `reference/design-systems.md` line 70: `spacing: tshirt(number(4, 32, linear()))` — a t-shirt-named scale (`xs sm md lg xl 2xl…` + `none`) interpolated over a **4px→32px linear ramp**. The author selects a *rung* (`$spacing.sm`, `$spacing.lg`), never a raw value. **This means every gap and pad in a Brilliant design is automatically on a consistent spacing rhythm.**
- **Negative gap (overlap) is also a token rung**: `$spacing.overlap.xs…2xl` (−2 → −32) for avatar stacks / badges (`layout-patterns.md` line 13).
- There is even a **density mode axis** baked into the default design system (`reference/design-systems.md` line 37): `density: [comfortable, compact]`. Switching density re-resolves the entire spacing scale — so "denser layout" is a one-token mode flip, not a global pixel rewrite.

### 2d. Sizing — hug / fill / fixed (the core idea)
`blueprint/layout.md` 7–11 and 32–35:
> "Each element is sized per axis: `hug` fits content, `fill` stretches to the parent, `fill:N` takes a proportional share, or a fixed number."
> "**Sizing** asks 'who decides this size?': content picks `hug` (text, buttons), the parent picks `fill`, a spec picks a fixed number."

- `s(360,hug)` = fixed-width, hug-height. `s(fill,hug)` = stretch width, hug height (the standard for prose). `s(fill:2,hug)` next to `s(fill:1,hug)` splits the parent **2/3 and 1/3 with no pixel math**.
- `frames.md` documents the exact flex solver (lines ~329–338):
  ```
  Frame: 400 wide, 16px padding each side → content = 368
  Children: [Fixed 80] [Fill] [Fill] [Fixed 80], 8px spacing × 3 = 24
  Remaining = 368 − 160 − 24 = 184
  Each Fill (flex 1) = 184 / 2 = 92
  ```
  `fill:3 + fill:1 → 138 / 46` (75% / 25%). The engine does the arithmetic; the model never types 92 or 138.
- **Hug/fill circular-dependency handling is built in** (`frames.md` ~344–356): a `fill` child on the *main* axis of a `hug` parent collapses to content size (avoids the circular dependency); on the *cross* axis it works normally; an "all-fill cross-axis" case bootstraps from the largest natural child size ("Common in pricing grids and multi-column layouts"). A competitor without this will produce 0-width invisible children or overflow.

### 2e. Constraints / anchoring
Brilliant explicitly does **NOT** use Figma-style pin-to-edge constraints. `frames.md` line ~26 (the Figma migration table): "Constraints (pin to edges) → **Not available** | Use auto layout with hug/fill/fixed." Anchoring of *connectors* exists (lines `from(#ref, side, fraction)` in `blueprint/lines.md`), and absolute positioning exists via `abs`, but the layout discipline is "constraints are expressed as auto-layout sizing modes," not edge pins. This is a deliberate funnel toward the solver.

### 2f. Absolute escape hatch (and how the grammar discourages it)
`abs` lifts a child out of layout flow so `p(x,y)` applies inside an `al()` (`blueprint/layout.md` 40–44; `frames.md` ~368–384). `p(c,c)` centers. But `abs` is scoped to badges/dots/floating overlays — "Excluded from gap, spacing, and hug calculations." The grammar's default is *in-flow*; you must opt in to free positioning. `core.md` line 26 even says "Omit `p()` on top-level elements; they auto-place beside existing work" — so even top-level placement is engine-managed by default.

### 2g. Wrap & grids
- Wrap: `al(h,wrap,...)` flows overflow onto the next row, "needs a fixed or fill main-axis size" (`blueprint/layout.md` 37–38; `frames.md` ~284). This is flex-wrap.
- Grids are expressed as **nested auto-layouts**, not a CSS grid primitive (`layout-patterns.md` 25–27): row-aligned table = `al(v,g(1))` → `al(h,g(0)) s(fill,hug)` rows → `s(fill,fill)` cells; column-major kanban = `al(h)` → `al(v) s(fill,fill)` columns.
- Separately, **layout guides** (`reference/layout-guides.md`) provide Figma-style column/row/grid *snap overlays* on frames (count, gutter default 20, margin) — these are alignment aids for manual editing, distinct from the auto-layout flow, but reinforce a column-grid discipline.

### Grammar summary (quote-level)
| Concern | Blueprint grammar | Engine computes |
|---|---|---|
| Direction | `al(v)` / `al(h)` | flow axis |
| Gap | `g($spacing.md)` (required) | inter-child spacing |
| Padding | `pad($spacing.lg)` / `pad(H,V)` / `pad(L,T,R,B)` (required) | inset |
| Main-axis align | `x(sb)` in `al(h)`, `y(sb)` in `al(v)` | free-space distribution |
| Cross-axis align | `x/y(s|c|e)` | perpendicular alignment |
| Sizing | `s(fill|hug|fill:N|fixed, …)` per axis | actual W/H, flex division |
| Proportional split | `fill:2` beside `fill:1` | 2/3 vs 1/3 widths |
| Wrap | `al(h,wrap,…)` | row breaking |
| Overlap | `g($spacing.overlap.md)` | negative spacing |
| Absolute | `abs p(x,y)` / `p(c,c)` | escape hatch only |

---

## 3. Ready-made composed PATTERNS / component recipes

**Yes — extensively.** Brilliant ships the agent both *layout recipes* (in `blueprint/layout-patterns.md`) and *composed UI block recipes* (in `blueprint/components.md` for the iteration machinery, and in the `design/blocks/*` knowledge for whole components). A competitor shipping ~19 docs almost certainly lacks this recipe layer. Inventory:

**From `blueprint/layout-patterns.md` ("Common patterns") — copy-paste layout skeletons with the right tokens already chosen:**
- spaceBetween (2 children to opposite edges): `al(h,x(sb),y(c),g($spacing.md),pad($spacing.none)) s(fill,hug)`
- push-right row: `al(h,x(e),y(c),…)`
- self-sizing centered row (button/chip): `al(h,x(c),y(c),g($spacing.sm),…) s(hug,hug)`
- pin-footer-to-bottom: `al(v,y(sb),x(s),g($spacing.none),…) s(fill,600)`
- overlap/avatar-stack: `al(h,g($spacing.overlap.md),…)`
- N equal-width items: all children `s(fill,fill)`
- fixed + flexible: `s(240,fill) + s(fill,fill)`
- bottom-align in a column: `al(v,y(e),x(c),…) s(hug,fill)`
- group for free positioning, center child with `p(c,c)`, `abs p(c,c)` inside auto-layout
- **Radial placement** (petals/ticks/orbiting dots) — exact trig formula given (`p.x = cx + R·sinθ − halfW`, `p.y = cy − R·cosθ − halfH`) so the model never eyeballs circular layouts (lines 34–47).
- **Grid patterns** (table, kanban) and a **Group-vs-Frame-vs-Absolute decision table** (line 30).
- A **Debugging** section (line 49–50) mapping symptom→fix ("spaceBetween not working → parent is `hug`, needs concrete size"; "Items jammed → parent has `g(0)`") plus canonical device sizes (iPhone 393×852, iPad 1024×1366, Laptop 1440×900, Desktop 1920×1080).

**From `design/blocks/layout.md` — full composed component recipes, each with tokens pre-chosen:**
- Separator/Divider, **Header** (`pad($spacing.md,$spacing.lg) s(fill,hug)`, logo-left/nav-center/actions-right), **Footer** (`pad($spacing.2xl,$spacing.xl)`, link-column groups with `g($spacing.xl)`), **Hero** (`y(c),x(c) g($spacing.lg) pad(80-120,$spacing.3xl)`, title 40–56 + subtitle + CTA row), Accordion, Carousel, Form.

**From `design/blocks/patterns.md` — composition patterns the primitives don't make obvious:**
- Inline element in a headline (icon mid-sentence), **Bento grid** (`fill:3`/`fill:2` asymmetric cells, "no pixel math"), Accent bar, stacked/tilted cards, watermark, chat bubble (asymmetric radius), notification dot.

**From `blueprint/components.md` — the `comp` / `inst()` / `slot` / `override()` machinery** so that "3+ near-identical elements (nav items, cards, tiles, table rows)" are stamped from one master rather than hand-coded (line 7). `design/foundations.md` line 3 elevates this to a rule: "Hand-coding N near-identical lines is a smell."

**Domain recipe libraries also exist** (seen in the file tree, outside this slice but relevant): `charts/{sparklines,bar-charts,line-charts,tables}.md`, `effects/{neon,clay,glass,dark-mode}.md`, `blueprint/arcs.md` (progress rings, pie/donut with the exact slice-angle recurrence `next_start = prev_start − prev_sweep% × 3.6`).

The net effect: the model is rarely composing from raw primitives. It is **filling in a recipe whose spacing, padding, sizing and hierarchy decisions were already made by Brilliant's designers and encoded in tokens.**

---

## 4. How the DSL makes it HARD to produce a badly-spaced layout

This is structural, not advisory. Several mechanisms each independently prevent a class of bad-spacing bug:

1. **You cannot type an off-scale gap or padding.** In explicit mode, bare numerics in `g()`/`pad()`/`rd()`/font-size/etc. **halt the call** (`core.md` 46; `design-systems/core.md` 17; `design-systems.md` 326). The author can only pick a t-shirt rung off the 4→32 generated scale. Inconsistent, arbitrary spacing (7px here, 13px there — the classic AI tell) is literally unrepresentable in explicit mode.

2. **Gap and padding are MANDATORY on every container**, so spacing is never "forgotten" or defaulted to a collision. `core.md` 29: "`g()` and `pad()` are always required (`$spacing.none` for zero)." Even zero is an explicit, intentional choice (`layout-patterns.md` line 12 calls out "`g($spacing.none)` = intentional zero gap").

3. **The engine computes all positions and sizes; the model declares relationships.** With `s(fill)`, `fill:N`, `x(sb)`, `y(c)`, the actual pixel positions/widths are solved (the flex math in `frames.md` §"Flex Factor"). The model cannot misplace an element by typing a wrong coordinate, because in-flow elements have no coordinates. Misalignment-by-arithmetic is impossible for flowed content.

4. **Sizing modes encode the right wrapping/overflow behavior.** Text defaults to `hug` (single line) for labels and `s(fill,hug)` for prose (`blueprint/text.md` 35; `reference/text.md` §"Text Inside Auto Layout Frames"). The most common spacing failure — numbers/labels wrapping in narrow cards, or paragraphs overflowing — is addressed by a documented per-use sizing table (`frames.md` ~307–323: label→hug/hug, prose→fill/hug, sidebar→fixed/fill, etc.).

5. **Cross-axis fill auto-equalizes sibling dimensions.** "Cross-axis fill stretches to match tallest/widest sibling" (`frames.md` ~320) — so rows of cards become equal height without the model measuring anything. Ragged card heights (a density/hierarchy smell) are prevented.

6. **Components keep repeated elements pixel-identical.** `comp`/`inst()` guarantees every card/row/tile shares one master's spacing and sizing; drift is impossible unless explicitly overridden (`blueprint/components.md`).

7. **Snap, pixel-grid, and distribution exist as a safety net for the manual/edit path** (`canvas.md` §Snap Guides, §Snap to Pixel Grid default-ON; `editing.md` §Distribution). Even hand-nudged elements snap to sibling edges, equal gaps, and whole pixels.

8. **The token scale is itself coherent by construction.** `spacing`, `radius`, `font.size` all come from the same `tshirt()` generator family (`design-systems.md` 70–76), and effects/opacity from a 9-stop `visibility` boldness ramp (0.02→1.0). Spacing, corner radii, and type sizes therefore advance on harmonious scales rather than ad-hoc values.

What the model still must get right (so it is not *impossible* to make a bad layout, just hard): choosing the *right rung* (`$spacing.sm` vs `$spacing.2xl`), the right sizing mode per child, the right direction, and the overall hierarchy/composition (which `design/foundations.md` coaches: "one dominant region… aim for 60–70% white space… favor asymmetry over grid-like sameness"). But the *mechanics* — gaps, padding, widths, alignment math, equal heights, pixel snapping — are the engine's job, not the model's.

---

## 5. The single most important layout-engine capability

**Engine-computed flex sizing/positioning driven by relative sizing modes (`hug`/`fill`/`fill:N`) and required, token-only gap+padding — i.e. a real auto-layout constraint solver that the model talks to in *intent* rather than coordinates.**

If a competitor lacks this and instead emits absolute positions and free-form pixel sizes, every spacing/density/hierarchy failure follows mechanically:
- **Spacing** becomes hand-arithmetic, so gaps drift off any scale and are inconsistent (no mandatory token gap to anchor them).
- **Density** can't be tuned coherently — there is no `fill`/`fill:N` to redistribute space, no `density` mode, no equal-gap distribution; the model guesses widths and they don't sum to the container.
- **Layout** breaks under any content change — absolute coordinates don't reflow, so text overflows or collides the moment a string is longer than assumed (Brilliant's `hug`/`fill` + wrap solves this automatically).
- **Hierarchy** flattens — without `fill:N` proportional splits and cross-axis fill equalization, you get grid-like sameness instead of a dominant region, and ragged sibling sizes read as noise.

Concretely, the load-bearing trio is: (a) **`hug`/`fill`/`fill:N` per-axis sizing** with the documented flex-division + hug/fill circular-dependency resolution (`frames.md` §Flex Factor, §Fill Inside Hug Frames); (b) **mandatory `g()` + `pad()` that only accept design-system spacing tokens** (`core.md` 29, 46); (c) **`x()/y()` alignment including `sb` space-between distribution**. Together they mean the model never types a coordinate, a width, or an off-scale gap for in-flow content — the exact opposite of an absolute-coordinate emitter, which must compute all three and will get them subtly (and visibly) wrong every time.

> **Inference (labeled):** Given our agent loops on Phase A preflight diagnostics and never clears them, and given that Brilliant's correctness is enforced *at parse time* (bare-numeric halts, strokeless-line rejection in `blueprint/lines.md` §Rejections, empty-text rejection, mandatory gap/pad), it is likely our DSL either (i) lacks an equivalent constraint solver and so emits coordinates/free sizes that the preflight then flags as malformed/colliding, or (ii) has the validators but not the token scale + auto-layout grammar that makes valid output the *easy* path — so the model keeps producing diagnostics it can't satisfy. Brilliant's design makes the valid, well-spaced output the path of least resistance; if ours makes valid output require explicit arithmetic, the model will fight the validator indefinitely. This should be cross-checked against R-slices covering our preflight diagnostic codes and our DSL grammar.

---

## Appendix — object model facts that reinforce the layout discipline

- **8 parent sub-types** (`frames.md`): Frame, Group, Auto Layout, Mask, 4×Boolean. Group/Mask/Boolean are forced `w:hug h:hug` and are NOT reparent targets — structural roles only. Auto Layout is the layout workhorse; converting Frame→Auto Layout *infers* direction/spacing/alignment/padding from child positions.
- **Auto Layout creation defaults** (`frames.md` ~202): direction inferred from spread, `itemSpacing` = rounded average gap, padding 0, forced hug/hug — i.e. the engine reverse-engineers a sensible layout even from loose input.
- **Coordinate spaces** (`canvas.md` §Coordinate Spaces): stored coords are **parent-local**; `lookup` returns parent-local blueprint coords. Reinforces that authoring is relative-to-parent, not world-absolute.
- **Components** (`reference/components.md`): master/instance with 17 synced property categories incl. `parentData` (layout direction, spacing, padding) and `layoutBehavior` (sizing mode) — so editing a master's spacing re-flows every instance. Slots (`isSlot`) let instances own heterogeneous content without breaking sync.
- **Text model** (`reference/text.md`): sizing modes Auto Size (hug) / Auto Height / Auto Width / Fixed; composite **typography tokens** (`typography.h1`–`h4`, `display.lg/md/sm`, `body.*`, `button`, `label`, `caption`, `code`) bundle family+size+weight+line-height+letter-spacing into one token — type hierarchy is a single-token choice, not five hand-set fields.
- **Styling** (`reference/styling.md`): fills are a z-ordered compositing stack (`blueprint/paint.md`: "Never make a separate child rectangle for a background or overlay; stack it as another fill") — discourages junk elements that would otherwise pollute spacing/hug calculations.

### Source files read in full for this slice
`blueprint/`: core, layout, layout-patterns, components, directives, text, styled-ranges, paint, lines, arcs, connectors, vectors, effects, images, commands.
`reference/`: canvas, frames, layout-guides, components, styling, text, vectors, editing.
Plus, for the token scale and composed recipes: `design-systems/core.md`, `reference/design-systems.md`, `design/foundations.md`, `design/blocks/layout.md`, `design/blocks/patterns.md`.
