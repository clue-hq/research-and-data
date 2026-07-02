# R3 — Brilliant's Blocks Pattern Catalog + Design Systems

**Audit slice:** `brilliant/knowledge/design/blocks/*` (7 files), `brilliant/knowledge/design-systems/*` (3 files), and reference docs `reference/{design-systems,ui,components}.md`.

**Bottom line (thesis):** Brilliant does NOT ask its agent to "draw a UI from primitives." It ships the agent a **vetted catalog of ~50 pre-composed blocks** (hero, footer, navbar, card, stat tile, modal, form, tabs, etc.) where **the correct internal spacing, padding, type scale, hierarchy, and color roles are already baked in as token references** (`$spacing.lg`, `$font.size.4xl`, `$color.text.secondary`, …). The agent's job is reduced to **assemble-and-tune vetted blocks**, and a **token system + mode resolver** then enforces global consistency across the whole document automatically. This is the structural reason Brilliant's compositions have good spacing/density/hierarchy and ours don't — **our Lumen bundle ships no `blocks/` catalog at all** (confirmed below), so our agent is improvising every block's internal spacing per run.

---

## 1. The LIBRARY OF PRE-COMPOSED BLOCKS

Yes — emphatically. The `design/blocks/` directory is a **7-file catalog of reusable, pre-composed UI blocks**, each with internal spacing, padding, type sizes, color roles, and hierarchy specified as **token references**, not free-floating pixels. Every block file declares `assumes: blueprint/layout, blueprint/text, blueprint/effects, blueprint/components` in front-matter — i.e. each block is layered on top of the primitive grammar and the component/instance system.

Below is the complete inventory I extracted, file by file, with what each block specifies. (Notation: `al(v/h…)` = auto-layout vertical/horizontal, `g()` = gap, `pad()` = padding, `s()` = size, `f[]` = fill, `st[]` = stroke, `rd()` = radius. `$token` = design-system token.)

### `blocks/layout.md` — page-level scaffolding
| Block | Pre-baked spec (verbatim tokens) |
|---|---|
| **Separator / Divider** | H: `r s(fill,1) f[($color.outline.variant)]`; V: `r s(1,fill)`; labeled: `g($spacing.md)` divider+text(`$font.size.xs`, `$color.text.secondary`)+divider |
| **Header** | `spaceBetween` row `pad($spacing.md,$spacing.lg) s(fill,hug)`, logo-left/nav-center/actions-right, 1px bottom stroke or shadow |
| **Footer** | V-stack `pad($spacing.2xl,$spacing.xl) s(fill,hug)`, `$color.surface.container`; link columns V-stack `g($spacing.sm)` heading(13,sb)+links(14,`$color.text.secondary`); bottom spaceBetween copyright + social. Dark footer = wrap in `ds(, theme(dark))`, **do not hand-paint dark** |
| **Hero** | V-stack `y(c),x(c) g($spacing.lg) pad(80-120,$spacing.3xl) s(fill,hug)`; eyebrow + Title(40-56, sb/b, centered) + subtitle(16-18, `$color.text.secondary`) + CTA row `g($spacing.md)` |
| **Accordion** | V-stack `g(0)`, 1px dividers, header `spaceBetween pad($spacing.md,$spacing.md)` title(14,m)+caret, expanded uses `rot(180)` chevron |
| **Carousel** | clip frame + slides; dot indicators `g($spacing.sm)` active `c s(8,8)` `$color.primary`, inactive `$color.outline.variant` |
| **Form** | V-stack `g($spacing.md) pad($spacing.lg) s(fill or 400-500,hug)`, sequential fields, error text(`$font.size.sm`,`$color.text.error`), submit at bottom |

### `blocks/actions.md` — buttons & action hierarchy
| Block | Pre-baked spec |
|---|---|
| **Button** | row `x(c),y(c) pad($spacing.md,$spacing.md) s(hug,hug) rd($radius.sm)`; Primary solid `$color.primary` + `$color.on-primary` text(14,sb) + layered shadow; Secondary 1px stroke; icon variant `g($spacing.sm)` 16×16. Rule: **"CTA buttons are solid — never gradient."** |
| **Button Group** | `g(0-2)`, first/middle/last corner-radius rules for seamless joins |
| **Segmented Control** | `comp` master with active styling baked in + `inst()` for inactive segments clearing fill/shadow (full DSL example, ~9 lines) |
| **Toggle Switch** | knob via `x(e),y(c)` on / `x(s),y(c)` off; `s(44,26)` track, `s(20,20)` knob |
| **FAB** | `s(56,56) rd($radius.full)` accent + high shadow, 24×24 icon |
| **Action Hierarchy** | **explicit hierarchy table**: Primary (solid accent+shadow) / Secondary (no fill, stroke) / Destructive (red) / Rare (overflow). **"Never give equal emphasis to all actions."** |
| **Button States** | Default/Hover/Pressed/Disabled shadow + fill rules |

### `blocks/data-display.md` — containers, people, status, tiles
| Block | Pre-baked spec |
|---|---|
| **Card** | V-stack `g($spacing.md) pad($spacing.lg)`, `$color.surface` + subtle stroke + `rd($radius.md)` + soft shadow; Title(`$font.size.lg`,sb) over desc(`$font.size.sm`,`$color.text.secondary`); image-top `clip` + image `s(fill,180)` |
| **List item** | h-row `x(s),y(c) g($spacing.md) pad($spacing.md) s(fill,hug)`: leading icon, title+subtitle stack, trailing badge/chevron; thin divider between |
| **Table** | V-stack `g(0)`; header cells `$color.surface.container` sb secondary; body `$font.size.sm`; **right-align numbers, equal cell count** |
| **Avatar / Avatar stack** | `s(40,40) rd($radius.full)` + initials; stack uses negative `g($spacing.overlap.md)` + surface ring + "+N" chip |
| **Badge / pill** | `pad($spacing.xs,$spacing.sm) rd($radius.full)` text `$font.size.xs`; pairs `.container` fill with text role (`$color.success.container`+`$color.text.success`) |
| **Three-state pipeline** | Todo/Doing/Done uses brand triplet (primary/secondary/tertiary), **not** success/warning/error — "Stop at three" |
| **Stat tile** | V-stack label(`$font.size.xs`,m,secondary)+value(`$font.size.2xl`,b)+delta row; "Stamp 3-4 as `comp`/`inst` row" |
| **Progress ring / Rating / Quote** | arc+ratio; star row filled `$color.warning`; oversized serif quote glyph + attribution |

### `blocks/feedback.md` — messaging & overlays
Blocks: **Alert/banner**, **Toast** (`s(320-400,hug)` + shadow), **Modal** (scrim `solid($color.shadow,o($visibility.mid))` + centered surface + spaceBetween header + `x(e)` footer), **Drawer** (`s(360-480,fill)`), **Bottom sheet** (top-only radius, upward shadow `y(-4)`, grab handle), **Dropdown menu** (`pad($spacing.xs)`, destructive items `$color.text.error`), **Tooltip** (dark chip), **Progress bar** (`fill:3`+`fill:1`=75%), **Skeleton**, **Empty state** (centered icon+title+desc+CTA). All status sets stamped as `comp`/`inst`.

### `blocks/inputs.md` — form controls
Blocks: **Text Input** (V-stack `g($spacing.sm)`, label(`$font.size.sm`,m) + input `pad(0,$spacing.md) s(fill,44)` with inner-shadow fill + 1px stroke `rd($radius.sm)`), **Textarea** (counter "0/500", `s(fill,120-200)`), **Search Input**, **Select/Dropdown**, **Checkbox** (`s(20,20)` + ✓ glyph), **Radio Button** (inner dot `c s(10,10)`), **Slider** (track `s(W,4)` + thumb `s(16,16)`), **File Upload** (dashed stroke, "Browse" in `$color.primary`).

### `blocks/navigation.md` — nav chrome
Blocks: **Horizontal Navbar** (spaceBetween `pad($spacing.md,$spacing.xl)`, 3 groups Logo/Nav/Right), **Sidebar** (V-stack `s(64-240,fill)`, selected `$color.surface.selected`+`$color.on-surface.selected`, hover/default/disabled states; rule **"Sidebar MUST have fixed height for spaceBetween"**), **Tabs (Underline)** (`comp`+`inst()` with indicator override, ~14 lines DSL), **Bottom Tab Bar** (floating pill, active/inactive), **Breadcrumbs** (interleave item→caret→item, last sb), **Pagination** (`s(32-36,32-36)`, active `$color.primary`), **Stepper** (completed/current/future circle states).

### `blocks/patterns.md` — compositions the primitives "don't make obvious"
This is the most telling file. It explicitly says: *"Compositions the primitives don't make obvious."* Patterns:
- **Inline element in a headline** — full DSL recipe using `al(h)` fragments + sibling icon box.
- **Bento grid** — "Fixed-height rows; inside each, cells sized `fill:N` give asymmetric widths **with no pixel math**. Vary cell colors; make one cell dominant." (full recipe with `fill:3`/`fill:2` proportions).
- **Accent bar** — "A thin `r s(fill,4)` as the first child draws the eye … needs `clip`."
- **Quick tricks** — stacked/tilted cards (`comp` then `inst()` with `rot()`/shadow weight), watermark (`$font.size.9xl` at `$visibility.faint`, `abs`), chat bubble (asymmetric radius `rd(16,16,4,16)`, "~60-70% of parent width"), notification dot.

**Why this matters for spacing/density/hierarchy:** every one of those numbers is a *vetted* value — `pad(80-120,$spacing.3xl)` for hero vertical rhythm, `g($spacing.md)` between cards, `s(fill,180)` for card image height, "60-70% of parent width" for chat bubbles, "make one cell dominant" for bento. These are exactly the spacing/density/hierarchy decisions our agent is getting wrong. Brilliant has pre-decided them.

---

## 2. Is the job "assemble vetted blocks" rather than "draw primitives"? — YES (strong evidence)

1. **Layering declaration.** Every block file's front-matter is `assumes: blueprint/layout, blueprint/text, blueprint/effects, blueprint/components`. Blocks sit *above* the primitive grammar; the agent reaches for a block, not for rectangles.
2. **`patterns.md` literally frames blocks as the things "the primitives don't make obvious"** — i.e. the catalog exists precisely to keep the agent out of primitive-level improvisation.
3. **`design/foundations.md` mandates iteration over hand-coding:** *"For 3+ similar elements (cards, tiles, rows, swatches), declare the shape once with `comp` and stamp `inst()` copies… **Hand-coding N near-identical lines is a smell** — and for copies on a circle/arc/grid, compute each position, **never eyeball**."* The agent is steered away from drawing-from-scratch toward stamping vetted units.
4. **Blocks are expressed in the component system** (`comp`/`inst()`/`override()`/`slot`), per `reference/components.md`. Segmented Control, Tabs, Stat tile, Alert set, stacked cards — all are authored as a master + instances. So "assembling blocks" is the *native* idiom, reinforced by the runtime sync engine (master edit propagates to all instances; overrides preserved).
5. **`foundations.md` even bakes in anti-AI-cliché hierarchy rules** that constrain *how* blocks are composed: "one dominant region per screen," "secondary regions stay visibly subordinate," "60-70% white space, then ask what to remove," "Hero weight: use mid/firm (500/600), not bold," "Eyebrows: the tinted pill is the #1 tell — vary it." These are composition-quality guardrails our agent has no equivalent of.

**Inference:** This is the single biggest lever. Brilliant's good spacing/density/hierarchy is not the model "being smarter" — it's that the model is **recalling and lightly tuning pre-vetted blocks** whose internal proportions were decided by a human design team, then letting tokens normalize the rest.

---

## 3. How tokens/design-systems enforce document-wide consistency (spacing, type, color)

This is the second lever: even where the agent *does* vary things, a **token resolver normalizes spacing/type/color across the entire document**.

- **Everything is a token.** `design-systems/core.md`: *"Every color, font, and scale value in a blueprint is a token (`$name`), resolved through the active design system."* Blocks reference `$spacing.lg`, `$font.size.4xl`, `$color.text.secondary`, never raw px. Edit one token → every element using it updates (`reference/design-systems.md`).
- **Two constrained vocabularies prevent arbitrary values:**
  - **Presence ramp** (`hint faint subtle soft mid firm bold strong intense`) for brand/palette, `$font.weight`, `$stroke.width`, `$visibility`.
  - **T-shirt scale** (`xs sm md lg xl 2xl…Nxl` + `none`) for `$spacing`, `$radius`, `$font.size`.
  This caps the design to a **finite, harmonious set of steps** — you cannot emit `pad(13px)` next to `pad(17px)`; you pick `$spacing.sm`/`$spacing.md` from a single ramp.
- **Explicit mode HALTS on bare values** (the enforcement teeth). `core.md`: *"Explicit mode halts on bare values in tokenizable slots: `g() pad() rd() o() w() lh() ls()`, `t()` size positional, and any color… Use a `$token`."* And `reference/design-systems.md`: *"Numeric stops are author-only… **rejected in element rows in explicit mode** (the call halts)."* So in explicit authoring mode the renderer literally **refuses** ad-hoc spacing/type/color — the agent is forced onto the scale. *(Inference: this is a hard rail that mechanically produces consistent rhythm.)*
- **One seed → full ramp.** A single brand seed `color(#0080FF)` generates an 11-step OKLCH ramp `.50…950` plus a 9-stop boldness role vocabulary; `default.styles` ships 22 Tailwind v4 palettes, 4 brand slots, and all scales (`spacing`, `radius`, `font.*`, `stroke.width`, `visibility`). A custom DS is "often 1–3 lines" because everything cascades from the seed.
- **Semantic aliases give every block the *same* role meaning.** `reference/design-systems.md` tables: `color.surface`=page bg, `color.surface.container`=card bg, `color.text.primary`/`secondary`/`disabled`, `color.outline`/`outline.variant`, the M3-style `primary/on-primary/primary.container` triplet, status `success/error/warning/info` each with `on-X` + `.container`. Because the card block, the footer block, and the navbar block all reference `$color.text.secondary` for muted text, muted text is identical everywhere automatically.
- **Composites lock type & elevation.** `typography.{display,h1..h4,body,button,input,label,caption,code}` and `shadow.{2xs..2xl,inner}` are pre-declared records/lists — a hero title and a card title resolve to the *same* `font.size`/`weight`/`lineHeight` triples, not ad-hoc numbers.
- **Cascade + single source of truth.** `.styles` files cascade root→leaf like `.editorconfig`; `.gen.yaml` is the resolved artifact for external tools (never hand-edited).

**Net effect:** spacing rhythm, type scale, and color roles are *globally coherent by construction*. Our agent (per the brand-and-tokens docs we ship) has tokens too, but **without the blocks catalog the tokens are applied inconsistently per-section because each section's internal spacing is improvised.** Tokens normalize *values*; blocks normalize *proportions/relationships* — Brilliant has both, we have only the former.

---

## 4. `authoring-modes.md` — modes that constrain the agent toward good output

`design-systems/authoring-modes.md` is specifically about **mode transforms**: how a single token set auto-adapts across mode axes so the agent never hand-builds variants (a common source of inconsistency).

- **Bare semantic generators bake in mode behavior by default** — *"Use `transforms:` only to override or opt out."* Defaults per generator:
  - `boldness(color(...))` → `theme.dark: mirror`, `accessibility.high-contrast: outward(1)`
  - `font.weight: boldness(number([...]))` → `accessibility.high-contrast: shift(+1)`
  - `spacing: tshirt(number([...]))` → `density.compact: shift(-1)`, `accessibility.large-text: shift(+1)`
  - `font.lineHeight: looseness(...)` → `accessibility.large-text: shift(+1)`
- **Three ops** transform a role's stop index on *any* generator (out-of-range clamps): `shift(N)` (offsets, **sums across active modes**), `mirror` (reflect around middle stop), `outward(N)` (push toward nearer terminal).
- **Opt-out** = `transforms: none` for brand-stable knobs (e.g. `radius`).
- **Three default mode axes** ship in `default.styles` (`reference/design-systems.md`): `theme: [light, dark]`, `density: [comfortable, compact]`, `accessibility: [standard, high-contrast, large-text]`. First value = default.

**How this constrains the agent toward good output:** dark mode, compact density, and accessibility variants are produced by **re-resolving the same tokens through mode transforms**, *not* by the agent re-authoring a dark palette. `core.md` is blunt about the failure mode it prevents: *"`ds(, theme(dark))` is the only thing making this card dark… Don't fake dark mode with `firm…intense` stops in `theme(light)`; switch to `theme(dark)` and the same low stops resolve dark on their own."* And repeatedly across blocks (footer, sidebar, bottom tab bar): *"wrap in a frame with `ds(, theme(dark))` rather than hand-painting `$neutral.intense`."* So the modes system **removes a whole class of hand-tuning errors** (inconsistent dark surfaces, mismatched contrast) by making correctness the default path.

*(Authoring is the sibling concern: `design-systems/authoring.md` shows `ds_file("name")` — authors/extends a brand in a few lines, inherits `default`, "declare ONLY what differs." This keeps brand definitions sparse and consistent rather than re-specified per design.)*

---

## 5. Templates vs generative — what is actually "template-like"?

The user suspects "templates." Precise answer: **Brilliant does not ship full-page document templates** (no "landing-page-A.design"). What it ships is **a layered template SYSTEM at the component/block level** that *feels* like templates and delivers the consistency benefit of templates:

**Template-like (pre-decided, recalled not invented):**
1. **The `blocks/` catalog itself** — ~50 named blocks with pre-baked internal spacing/padding/type/role/hierarchy. Functionally these are *parameterized block templates* (vary the text/color, the proportions are fixed).
2. **The `comp`/`inst()` component system** (`reference/components.md`) — a *master template + linked instances* with override tracking and a sync engine. Stat tiles, tabs, segmented controls, alert sets, stacked cards are authored as one master stamped N times. This is the literal "template" mechanism.
3. **`seedTemplateDsl` / `default.styles`** (`reference/design-systems.md`) — *"Always exists; auto-created on first run by writing `seedTemplateDsl` verbatim."* A **token/system template**: 22 Tailwind palettes, 4 brand slots, all scales, all semantic aliases, typography + shadow composites, and inline `dark:` branches. Reset via `reset_design_system`. This is a project-baseline template.
4. **Composite tokens** (`typography.*`, `shadow.*`) — pre-declared "style templates" applied via `Apply Typography Token` / `Apply Shadow Token` commands.
5. **`design_system_viewer`** (`create_design_system_viewer`) — inserts an 800×600 swatch/type viewer = a template visualization element.

**Generative (genuinely created per design):**
- The **overall page composition** — which blocks, in what order, at what scale, the focal hierarchy. `foundations.md` is judgment guidance ("one dominant region," "60-70% white space"), not a fixed layout. The agent still *arranges* blocks.
- **Color ramps** from a seed (OKLCH `color()` generation), numeric scales (`number()` with `linear`/`geometric` ramps), brand overlays (`ds_file`).
- The Bento grid / accent-bar / inline-headline patterns are **recipes** (parameterized), not frozen layouts.

**Precise framing for the synthesis agent:** It is **template-driven assembly**, not template instantiation. Brilliant gives the agent (a) a block catalog with frozen internal proportions, (b) a master/instance system for repetition, and (c) a seed-template design system that normalizes everything. The *page* is generated; the *building blocks and their internal spacing/type/color* are templated. That hybrid is exactly what produces "good composition with correct spacing/density/hierarchy."

---

## 6. The smoking gun for our quality gap (cross-check vs Lumen bundle)

I verified our shipped Lumen knowledge against this slice:

- **Brilliant ships 91 knowledge `.md` docs** (`find … brilliant/knowledge -name '*.md' | wc -l` = `91`), including the **7-file `blocks/` catalog** + **3-file `design-systems/` set** above.
- **Our Lumen runtime ships ~19 docs** under `apps/agent_runtime/knowledge_docs/knowledge/` and **NO `blocks/` directory exists** (a `find … -type d -name blocks` over the Lumen tree returns only `node_modules` webpack dirs — zero design blocks). Our design knowledge is just 3 files: `layout-recipes.md` (131 lines), `typography-and-composition.md`, `artboard-frame-authoring.md`.
- Grepping our docs for block names yields only thin, ad-hoc fragments (one "Email Hero", one "Direct Mail Header", a couple of inline `card al(v,…)` examples in `layout-recipes.md`), **not a systematic catalog with per-block internal spacing/type/role specs**.

**Conclusion (high confidence):** Our agent produces worse spacing/density/hierarchy because it has **no vetted block catalog to recall** — it improvises every block's internal proportions from a 3-file recipe set, while Brilliant recalls ~50 pre-proportioned blocks and lets a token+mode resolver normalize the rest. The component/instance discipline (`comp`/`inst()` for 3+ similar elements) and the explicit-mode rail that *halts on bare spacing/color values* are additional enforcement layers our bundle does not appear to carry into authoring.

**Inference / caveat:** This slice does not itself touch the Phase-A repair-loop / `max_iterations_reached` failure. But it is plausibly upstream of it — if our agent hand-draws primitives with bare values, it will generate exactly the kind of layout/spacing diagnostics a preflight checker flags, then loop trying to repair compositions it never had the block-level scaffolding to get right in the first place. (Other audit slices should confirm whether the diagnostic codes the loop chokes on are spacing/token/bare-value violations — that would tie directly to the missing blocks catalog + explicit-mode token rail described here.)

---

### Key file references
- Blocks catalog: `brilliant/knowledge/design/blocks/{layout,actions,data-display,feedback,inputs,navigation,patterns}.md`
- Design systems: `brilliant/knowledge/design-systems/{core,authoring,authoring-modes}.md`
- References: `brilliant/knowledge/reference/{design-systems,ui,components}.md`
- Composition judgment: `brilliant/knowledge/design/foundations.md`
- Our gap: `agents-design-recipes-quality-v0/apps/agent_runtime/knowledge_docs/knowledge/design/` (3 files, no `blocks/`)
