# R1 — Brilliant's Design Philosophy & Composition Foundations

**Audit slice:** Brilliant's design philosophy and composition foundation docs.
**Source bundle:** `/Users/aryankeshri/Documents/brilliant-design/brilliant/` (byte-identical to the shipped `.claude-prod` skill bundle).
**Doc count confirmed:** `find brilliant/knowledge -name '*.md' | wc -l` → **91** knowledge docs (ground-truth "~91" verified exactly). We ship ~19.

Files read in full for this slice:
- `brilliant/v3-design-spec.md`
- `brilliant/objects-syntax.md`
- `brilliant/knowledge/design/foundations.md`
- `brilliant/knowledge/design/colors.md`
- `brilliant/knowledge/design/typography.md`
- `brilliant/knowledge/design/backgrounds.md`
- `brilliant/knowledge/design/gradients.md`
- `brilliant/knowledge/design/shadows.md`
- `brilliant/knowledge/design/brand.md`

---

## 0. Headline finding (the punchline for the synthesis agent)

Brilliant does **not** treat "good composition" as an emergent property of good components. It treats it as a set of **explicit, numeric, enforceable rules** that are baked into (a) a token-generating DSL where the *design system literally is the design*, and (b) a tight feed-back loop where every emitted `<objects>` block is screenshotted and graded against a fixed checklist (spacing, typography, contrast, alignment, clipping) **before the agent is allowed to continue**.

The quality gap is therefore structural, not stylistic:
- **Brilliant pushes composition decisions UP into the token layer** (`boldness`/`tshirt`/`looseness` scales, `60-30-10`, anchor principle, `60-70%` whitespace) so the agent picks *stops on a scale*, not raw pixels. Raw pixels are explicitly forbidden in multiple docs.
- **Brilliant pushes quality enforcement DOWN into a per-block review loop** (`objects-syntax.md` lines 35-42): one block → screenshot + checklist → fix → next block.
- Our Lumen runs die in **Phase A repair** (`max_iterations_reached`, "Maximum Phase A repair iterations reached") — i.e. our loop is *stuck on preflight diagnostics it never clears*, which is the inverse of Brilliant's design: Brilliant's loop is a **composition-quality** loop, not a **syntax-validity** loop. (Inference, but strongly supported — see §6.)

---

## 1. Core design philosophy / mental model for a "good" composition

### 1.1 "Commit to a system FIRST" (foundations.md:13-17)
Before any element is drawn, the agent must commit to a concrete system:
> "commit to a system first: **3-6 colors with roles, a font with heading and body weights, a spacing rhythm.** Then decide the emotion, the focal point (one per section), and the personality."

This is the root mental model: **system → emotion → focal point → personality**, in that order. Composition is a *consequence* of an up-front system decision, never improvised per element.

### 1.2 Read the intent, two modes (foundations.md:11-13)
- A **vague prompt with no visual context** = "the user is evaluating you: deliver one tight, impressive piece."
- A **specific product prompt** = "clarity and usability come before style."

So the agent is told to *diagnose the task type first* and trade off polish-vs-utility accordingly.

### 1.3 Dominance / subordination — the squint test (foundations.md:30-37)
> "Every screen needs **one dominant region** that draws the eye first; secondary regions stay visibly subordinate (smaller, lighter, less contrast). **If you squint and nothing dominates, raise the contrast.**"

This is an operational, testable rule (the "squint test"), not vibes.

### 1.4 Surfaces over boxes; asymmetry over grid-sameness (foundations.md:33-35)
> "Prefer information on surfaces over **boxing everything in cards**; favor **asymmetry and scale contrast over grid-like sameness.**"

Directly attacks the most common AI-composition failure: everything-in-a-card, evenly-weighted grid. (Likely a major contributor to our "grid-like / flat hierarchy" output — Inference.)

### 1.5 Explicit composition numerics (foundations.md:35-37)
> "Headlines run **4-8 words**, subtitles **12-25**; **one CTA per section**; aim for **60-70% white space**, then ask what to remove."

These are hard, checkable thresholds.

### 1.6 The Anchor Principle (typography.md:38-41)
> "Every screen has **ONE focal element sized 2-3x body** — hero headline, primary metric, key callout. Don't equally weight multiple 'biggest things' — one dominates, the rest support."

### 1.7 Anti-cliché doctrine (foundations.md:39-50, gradients.md, backgrounds.md, brand.md)
A large fraction of the "professional vs amateur" knowledge is *negative* — a catalog of "AI tells" to avoid:
- **Hero weight**: modern SaaS heroes use `mid`/`firm` (500/600), **not bold**; "at 48-64px mid reads confident." (foundations.md:42-44)
- **Eyebrows**: "the tinted pill is the #1 tell." Vary it. (foundations.md:45-46)
- **Color clichés**: "skip blue-to-purple gradients, neon-on-dark, all-white with one safe accent, and low-opacity circles behind sections. **If you have seen a combo in three AI designs, drop it.**" (foundations.md:47-49)
- **Backgrounds**: "Large low-opacity circles behind content are the **#1 AI background cliché**." (backgrounds.md:41-44)
- **Gradients**: "Gradient CTAs = **never** … gradient CTAs are the #1 AI tell." / "**Never blue-purple.** The most recognizable AI gradient." (gradients.md:10, 35)
- **Shadows**: "Single `shadow()` looks fake." / "Never pure black." (shadows.md:10)
- **Logos**: "Default AI logo — icon in solid box — is generic. Break the pattern." (brand.md:5)

**Mental-model summary:** good composition = *commit to a numeric system up front* + *establish one focal anchor per section with clear subordination* + *aggressively avoid a known list of AI clichés* + *favor whitespace, surfaces, and asymmetry over dense card-grids*.

---

## 2. Concrete numeric systems prescribed

Brilliant prescribes everything as **named stops on generated scales**, not raw values. The agent is told repeatedly to reach for a token, never a pixel.

### 2.1 Spacing scale (v3-design-spec.md:76, 139)
- Generator: `spacing: tshirt(number(4, 32, linear()))` — a 32-stop linear ramp seeded at 4.
- Catalog picks 10 named stops by index: `xs→1, sm→2, md→4, lg→6, xl→8, 2xl→12, 3xl→16, 4xl→20, 5xl→24, 6xl→32`.
- T-shirt vocabulary (uniform): `xs, sm, md, lg, xl, 2xl, 3xl, 4xl, 5xl, 6xl, 7xl, 8xl, 9xl` (v3-design-spec.md:46-50).
- **Rule (v3-design-spec.md:61):** spacing/radius/font.size are **never used bare** — "agent always picks a stop (`$spacing.md`, `$radius.lg`)." There is no `$spacing` fallback; you *must* choose a rhythm step.

### 2.2 Type scale, body = 16px (typography.md:8-24)
```
xs=12  (overlines, captions, micro-labels)
sm=14  (secondary body, dense UI)
md=16  (body)
lg=20  (subheadings)
xl=24  (section headings)
2xl=32 (page headings)
3xl=36 (small heroes)
4xl=40 (heroes)
5xl=48 (large heroes)
6xl=64 (display)
7xl=80, 8xl=96, 9xl=128 (oversize / display)
```
- **Jump rule (typography.md:26):** "heading = **150-200%** of body."
- **Anchor (typography.md:40):** focal element **2-3x body**.
- Underlying primitive list (v3-design-spec.md:86): `[12,14,16,20,24,32,36,40,48,64,80,96,128]`.

### 2.3 Font weight scale — `boldness`, 9 stops (v3-design-spec.md:34-38, 87)
- Vocabulary: `hint, faint, subtle, soft, mid, firm, bold, strong, intense`.
- For `font.weight`: maps to `[100,200,300,400,500,600,700,800,900]`; `bold → 700` (CSS canon).
- **Hierarchy lever rule (typography.md:36):** use **2-3 levers simultaneously — Size + Weight + Color.** "Pair heavy headings (`$font.weight.bold`/`.strong`) with `.soft`/`.faint` body."

### 2.4 Line-height & letter-spacing — `looseness`, 6 stops (v3-design-spec.md:40-44, 88-89, 141-144)
- Vocabulary: `none, tight, snug, normal, relaxed, loose`.
- `font.lineHeight` list: `[1.0, 1.25, 1.375, 1.5, 1.625, 2.0]`.
- `font.letterSpacing` list: `[-0.05, -0.025, -0.0125, 0, 0.025, 0.1]`.
- **Tracking rule (typography.md:36):** "Tighter tracking on large type (24px+), open tracking on small-caps or labels below 13px."

### 2.5 Radius scale (v3-design-spec.md:77-78)
`tshirt(number([4,8,16,24,32,48]), min:{none:0}, max:{full:9999})` — named boundary stops `none=0` and `full=9999` (pills/circles).

### 2.6 Color = OKLCH lightness ramp, 11 stops (v3-design-spec.md:9, 113-125)
- `color(seed)` → OKLCH ramp named `.50..950`.
- `boldness(color(...))` maps 9 names onto 11 OKLCH stops:
  `hint→.50, faint→.100, subtle→.200, soft→.300, mid→.500, firm→.600, bold→.700, strong→.800, intense→.900` (`.400`/`.950` reserved for power users).
- 22 Tailwind palettes total are generated (v3-design-spec.md:73).

### 2.7 Color usage ratio — 60-30-10 (colors.md:9-11)
> "**60%** dominant (backgrounds `$color.surface`/`.container`) · **30%** secondary (text/borders) · **10%** accent (CTAs/callouts). Most common mistake: accent on 30%+ of surface."

### 2.8 Contrast ratios — WCAG AA (colors.md:41-42)
- Normal text (<18px): **4.5:1**.
- Large text (18px+ bold): **3:1**.
- Concrete failing example called out: `#10B981` (`$emerald.mid`) on white **fails** for small text → use `#059669` (`$emerald.firm`).

### 2.9 Stroke width & visibility/opacity scales (v3-design-spec.md:79-80)
- `stroke.width: boldness(number([0.25,0.5,0.75,1,1.5,2,3,5,8]))`.
- `visibility: boldness(number([0.02,0.05,0.10,0.20,0.40,0.60,0.80,0.95,1.0]))` — opacity is itself a named scale (`$visibility.faint`, `.subtle`, etc.), used pervasively in shadows.

### 2.10 Shadow opacity range (shadows.md:10)
- "Never pure black — use **0.04-0.10 opacity**." On dark, colored glows go **0.12-0.20** (shadows.md:36).

### 2.11 Mode axes (v3-design-spec.md:157-163)
`theme:[light,dark]`, `density:[comfortable,compact]`, `accessibility:[standard,high-contrast,large-text]`. Density and accessibility **shift the entire scale by a notch** automatically (v3-design-spec.md:150-151): `density.compact` shifts tshirt mappings down a step; `large-text` shifts up; `looseness` loosens one step under large-text. So "density" is a first-class, system-level lever — not a per-element fiddle.

**Net:** every visual dimension (space, size, weight, line-height, tracking, color tone, opacity, stroke, radius) is a **named position on a generated, mode-aware scale**. The agent's job is to pick stops, and the scales are pre-tuned so picks compose well.

---

## 3. How color / gradient / shadow / background usage is taught to read "professional"

### 3.1 Color (colors.md)
- **60-30-10** as the master ratio (§2.7).
- **Neutral family choice matters:** "Slate (cool) · Stone (warm) · Zinc (true neutral) · **Gray is the lifeless default — skip it.**" (colors.md:15). "**Body text should never be pure black (#000) or pure gray (#333/#666)** — tint it to match your neutral family." (colors.md:15)
- **Dark mode = switch the DS, don't hand-roll** (colors.md:19): `ds(, theme(dark))` on the top frame; semantic aliases auto-flip. "Never #000 bg (void), never #FFF text (eye strain). Reduce accent saturation on dark. Shadows invisible — surface color does the work." (colors.md:21)
- **Interactive-state tokens** are pre-named (colors.md:24-32): `$color.surface.hover` (neutral.faint), `.pressed` (neutral.subtle), `.selected` (primary.subtle) + `$color.on-surface.selected` (primary.bold). The agent doesn't hand-pick hover stops.
- **Data viz**: semantic status tokens (`success/error/warning/info`) + a **max-6 categorical series** palette of `*.mid` stops chosen for distinguishability (colors.md:35-38).

### 3.2 Gradients (gradients.md)
- **Default is NO gradient** (rule #1, gradients.md:33). "modern design = solid + whitespace" (gradients.md:10).
- **Direction encodes mood** (gradients.md:13-14, repeated in backgrounds.md:20): `180` grounding · `135` energizing · `0` uplifting · `90` progressive — and "angle matches reading direction" (rule #7).
- **Two stops feel flat; three create depth** — the "multi-stop knee," middle stop shifts character (gradients.md:17-23).
- **"One good color, shifted"** (rule #4): "Blue-to-slightly-more-purple always beats blue-to-orange." One gradient per visual group (rule #5).
- Stops are **tokens**, so gradients follow brand + mode automatically.

### 3.3 Shadows (shadows.md)
- **Two layers mandatory:** "Every shadow needs two layers — **key light** (directional, tight, offset) + **ambient** (soft spread, little offset). **Single `shadow()` looks fake.**" (shadows.md:10)
- 3-tier elevation scale (Low/Medium/High) given as literal token recipes (shadows.md:13-27), all using `$neutral.intense` + `$visibility.faint/subtle` opacities.
- **Colored shadows** tint to the element's fill = "colored light cast onto surface"; double as glow on dark (shadows.md:30-36).
- "If you can obviously see the shadow, it's too strong." / "Higher elevation = more important = more interactive." (shadows.md:10) — elevation encodes hierarchy.

### 3.4 Backgrounds (backgrounds.md)
- **Section alternation is the first move** for multi-section pages: "alternate 2-3 surface tones so **no two adjacent sections match.**" Page frame uses `g($spacing.none)`; each section owns its own vertical padding (backgrounds.md:7-13).
- "**80%+ of sections are a solid or a gradient.**" Keep one tonal family. (backgrounds.md:17)
- Decorative treatments: **one or two per page, most sections need none** (backgrounds.md:22-26).
- **Structural rule:** a full-size uniform background is a *fill on the section frame, never a child rect*; only independently-positioned/rotated layers become real elements (`gr` overlay outside auto-layout, or `abs` child inside it) (backgrounds.md:28-38). This prevents the stray-rectangle / mis-sized-background bug class.

### 3.5 Effect budget gated by personality (foundations.md:19-27)
Effects are **rationed by chosen personality**, not piled on:
- Minimal: subtle/no shadows, no effects, solid bg.
- Professional: layered shadows on *key* elements, *one* glass/shader accent, a gradient bg.
- Bold/playful: colored shadows, 2-3 effects, claymorphism, rich gradients.
- Dark/premium: colored inner glows, glass over shaders, ambient gradients.

**Net "professional" recipe:** restrained palette in 60-30-10, tinted (never pure) neutrals, solid surfaces with section alternation, gradients only where they earn it (3-stop, single hue, never on CTAs), and two-layer subtle shadows that encode elevation/hierarchy. Almost every doc is as much about *what NOT to do* as what to do.

---

## 4. Document / object model (objects-syntax.md + v3-design-spec.md)

### 4.1 Designs are a streamed tree of "blueprint" lines inside `<objects>` tags (objects-syntax.md:1-26)
A design is authored as text: an `<objects canvasId="..." previewIds="#ref">` block containing **blueprint lines**, one element per line, **indentation = parent/child nesting**. Example shape (objects-syntax.md:21-25):
```
al(v, g($spacing.4), pad($spacing.6)) ds(dashboard-blue) p(100,100) s(hug,hug) f[($color.surface)] st[($color.outline, w(1))] rd($radius.md) "Card" #card
  t("Dashboard", $font.family, 24, b) f[($color.text.primary)] "Title" #title
  t("Welcome back", $font.family, 14) s(fill,hug) f[($color.text.secondary)] "Subtitle" #subtitle
  al(h, x(c), y(c), pad($spacing.3, $spacing.4)) s(hug,hug) f[($color.primary)] rd($radius.sm) "Button" #btn
    t("Get Started", $font.family, 14, sb) f[(#FFF)] "Label" #label
```
Key grammar tokens (the agent must know these by name):
- **Layout:** `al(v|h, ...)` auto-layout, `g(...)` gap, `pad(...)` padding, `s(W,H)` size with `hug`/`fill` intrinsic modes, `p(x,y)` position, `fr` frame, `gr` group, `abs` absolute child, `c`/`r` shapes.
- **Alignment:** `x(c)`, `y(c)` center on cross/main axes.
- **Paint/style:** `f[(...)]` fill, `st[(...)]` stroke + `w(n)` width, `rd(...)` radius, `o(...)` opacity, `clip`, `rot(...)`.
- **Text:** `t("text", family, size, weight)` with weight shorthands `b`/`sb` etc.
- **Effects:** `shadow(...)`, gradient fns `linear(...)`, `radial(...)`, `metaballs(...)`.
- **DS attach:** `ds(name)` / `ds(, theme(dark))` binds a design system / mode to a subtree.
- **Refs/naming:** trailing `"Human Name"` + `#ref` id per element.

### 4.2 The design system is a separate, generative artifact (`ds_file`) (objects-syntax.md:9-25, v3-design-spec.md)
Before elements, the agent declares a DS inline via `ds_file("name")` with role bindings:
```
ds_file("dashboard-blue")
  brand: #3B82F6
  neutral: #64748B
  font.family: Inter
  color.surface: #FFFFFF
  color.text.primary: brand.900
  color.primary: brand.500
```
This DS file is the v3 DSL from `v3-design-spec.md`:
- **5 generators**: primitives `color(seed)`, `number(seed,count,ramp)`, `number(range(...))`, `number([list])`; semantics `boldness(scale)`, `tshirt(scale,[min],[max])`, `looseness(scale)` (v3-design-spec.md:7-24).
- Ramps: `linear()`, `linear(step)`, `geometric()`, `geometric(ratio)`.
- **Two-section `.gen.yaml`** output: a PRIMITIVES section + a SEMANTICS section with mode-keyed branches (v3-design-spec.md:182-185).
- **Override semantics (v3-design-spec.md:52-58):** bare value on a mode-aware path = **error**; block at a path = full replace; dotted mode segment = additive override; block with only `$default` = mode-immune lock.
- **Bare-alias convention (v3-design-spec.md:60-61):** `$primary` → `$primary.mid` (boldness palettes only); tshirt scales (`$spacing`/`$radius`/`$font.size`) are **never bare** — must pick a stop.

### 4.3 Modify-vs-create and reparenting (objects-syntax.md:44-51)
- **Modify flat, create indented.** A line starting with `#ref` = modify (flat). No id + indentation = create under parent. Reparent via `#badge parent(#new_card)`.

### 4.4 Reusability primitives: `comp` / `inst()` and computed layout (foundations.md:1-8)
For 3+ similar elements (cards/tiles/rows/swatches): "declare the shape once with `comp` and stamp `inst()` copies … **Hand-coding N near-identical lines is a smell** — and for copies on a circle/arc/grid, **compute each position, never eyeball**" (→ `blueprint/layout-patterns`).

### 4.5 This object model cross-references ~14 other docs
foundations/colors/typography/etc. constantly defer to `blueprint/paint`, `blueprint/text`, `blueprint/effects`, `blueprint/layout-patterns`, `blueprint/components`, `design-systems/core`, `design/blocks/actions`. The 91-doc corpus is a **graph**, and these 9 foundation docs are the *index/judgment layer* sitting on top of a much larger mechanical reference layer (24 `blueprint/*`, 14 `effects`+`webgl`, 7 `design/blocks/*`, 5 `charts/*`, etc.). **A 19-doc bundle almost certainly drops most of the `blueprint/*` mechanical layer these foundation docs assume exists** (every foundation doc opens with `assumes: blueprint/...`). (Inference — confirmable by diffing our shipped doc set against this list; see §6.4.)

---

## 5. The 10 most reusable, transferable rules (first-try composition)

1. **Commit to a system before drawing.** Pick 3-6 colors with roles, a font with heading+body weights, and a spacing rhythm — THEN choose emotion, focal point, personality. (foundations.md:13-17)
2. **One focal anchor per section, sized 2-3x body, everything else subordinate.** Apply the squint test: if nothing dominates, raise contrast. (foundations.md:30-32, typography.md:38-41)
3. **Never type raw pixels — pick a stop on a scale.** `$spacing.md`, `$font.size.xl`, `$radius.lg`. Spacing/size/radius are never bare. (typography.md:10, v3-design-spec.md:61)
4. **60-30-10 color split**; accent ≤10% of the surface; one accent CTA per section. (colors.md:9-11, foundations.md:35)
5. **Heading = 150-200% of body; hierarchy via 2-3 levers at once (Size + Weight + Color).** Pair heavy headings with `soft`/`faint` body. (typography.md:26, 36)
6. **Aim for 60-70% whitespace, then ask what to remove.** Favor info-on-surfaces and asymmetry over boxing-everything-in-cards and grid-sameness. (foundations.md:33-37)
7. **Shadows always two-layer (key + ambient), opacity 0.04-0.10, never pure black, consistent direction; elevation encodes importance.** (shadows.md:10-27)
8. **Gradients are opt-in, not default:** never on CTAs, never blue→purple, prefer one hue shifted, three stops for depth, angle = mood/reading direction. (gradients.md:10, 13-39)
9. **Multi-section pages alternate 2-3 surface tones so no two adjacent sections match;** background is a fill on the section frame, not a child rect; ≤1-2 decorative treatments per page. (backgrounds.md:7-44)
10. **Avoid the AI-cliché list explicitly:** bold giant hero (use mid/firm), tinted-pill eyebrow, low-opacity circles behind sections, neon-on-dark, all-white+one-safe-accent, icon-in-solid-box logo, gradient CTA. "Seen in 3 AI designs → drop it." (foundations.md:39-49, brand.md, gradients.md, backgrounds.md)

---

## 6. Why this produces a composition-quality gap vs. our Lumen agent

(Evidence-based observations + clearly-labeled inferences, tied to the established ground truth: 91 vs 19 docs; all 5 runs failed with `max_iterations_reached` / "Maximum Phase A repair iterations reached".)

### 6.1 Composition rules are encoded as enforceable numerics, not prose vibes
Brilliant turns "good spacing/density/hierarchy" into **numbers and named stops**: 60-70% whitespace, 60-30-10, heading=150-200% of body, anchor=2-3x body, headlines 4-8 words, shadow opacity 0.04-0.10, contrast 4.5:1 / 3:1, ≤6 chart series, ≤1 CTA/section, ≤2 decorations/page. An agent following these gets density/hierarchy right *by construction*. If our 19-doc bundle lacks these specific thresholds (very likely, given the doc-count gap), our agent has nothing to anchor density/spacing decisions to and defaults to even-weight, card-grid, low-whitespace output — exactly the reported "bad spacing, density, layout, hierarchy." (Inference, well-supported.)

### 6.2 Composition is pushed into the token layer (the DSL), removing per-element guesswork
Because spacing/size/weight/tone/opacity/radius are all **pre-tuned scales** with mode-aware shifts (density/large-text shift the *whole* scale a notch), Brilliant's agent picks *stops* that are guaranteed to compose. `$spacing` has no bare fallback — the grammar *forces* a rhythm choice (v3-design-spec.md:61). If Lumen lets the agent emit raw pixels (or lacks the `tshirt`/`boldness`/`looseness` scales), spacing rhythm and tonal hierarchy become ad-hoc per element → inconsistent density and muddy hierarchy. (Inference — confirm by checking whether our DSL implements `boldness/tshirt/looseness` and whether it forbids bare spacing.)

### 6.3 The per-block screenshot+checklist loop is a COMPOSITION loop, not a SYNTAX loop
`objects-syntax.md:35-42` describes Brilliant's feedback architecture: after each successful `<objects>` block, the response is interrupted and **a screenshot + a self-review checklist (spacing, typography, contrast, alignment, clipping)** plus "composition notes" (duplicate sibling names, collapsed zero-size elements, invisible text) are injected; the agent fixes, then continues. This is a *visual* quality gate that catches exactly the failure classes we're seeing (spacing/density/hierarchy/alignment/clipping).

Our runs, by contrast, die in **Phase A repair** with `"Maximum Phase A repair iterations reached"` — i.e. our loop is stuck **before** it ever reaches a composition-quality review, churning on preflight/syntax diagnostics it can't clear. So two distinct failures compound:
- **(a)** Our agent never gets to a Brilliant-style *visual* self-review of spacing/hierarchy at all, and
- **(b)** the iterations budget is burned on diagnostics rather than improving composition.
(Inference on the internal mechanics of Phase A, but directly consistent with the stop_reason and the contrast against `objects-syntax.md`.)

### 6.4 The foundation docs ASSUME a large mechanical substrate we likely don't ship
Every foundation doc declares `assumes: blueprint/paint` / `blueprint/text` / `blueprint/effects` and cross-links `blueprint/layout-patterns`, `blueprint/components`, `design-systems/core`, `design/blocks/*`. The full corpus is **91 docs** with **24 `blueprint/*`**, **7 `design/blocks/*`**, **5 `charts/*`**, **16+ `webgl/effects`**, etc. A 19-doc bundle cannot carry both the judgment layer (these 9) AND the mechanical layer they depend on. If we shipped foundations but dropped `blueprint/layout-patterns` (computed grid/arc positioning), `blueprint/components` (`comp`/`inst()`), and `design/blocks/*` (canonical card/nav/action recipes), the agent knows the *rules* but lacks the *mechanisms* to execute them — and "compute each position, never eyeball" (foundations.md:6) becomes impossible. That yields eyeballed, mis-aligned, uneven-density layouts even when individual components look fine. (Inference — directly testable by diffing the shipped 19 against this 91-doc list.)

### 6.5 Brilliant front-loads anti-cliché knowledge; "fine components, bad composition" is the exact symptom it targets
The reported symptom — *individual components look fine but the overall composition is worse* — is precisely the gap Brilliant's foundation/composition/backgrounds/gradients docs exist to close: focal hierarchy, section rhythm, whitespace budget, 60-30-10, anti-grid-sameness. These are *between-element* and *whole-page* concerns. Component-level docs (which we apparently do have, since "our components look fine") don't cover them. The missing ~72 docs are disproportionately the composition/judgment/mechanical-layout layer. (Inference, strongly supported by the symptom description.)

---

## 7. Quick-reference numeric appendix (for the synthesis agent)

| Dimension | System | Stops / values |
|---|---|---|
| Spacing | `tshirt(number(4,32,linear()))` | xs1 sm2 md4 lg6 xl8 2xl12 3xl16 4xl20 5xl24 6xl32 |
| Font size | `tshirt(number([...]))` | 12 14 16 20 24 32 36 40 48 64 80 96 128 |
| Font weight | `boldness(number([...]))` | 100-900; bold=700 |
| Line height | `looseness(number([...]))` | 1.0 1.25 1.375 1.5 1.625 2.0 |
| Letter spacing | `looseness(number([...]))` | -0.05 -0.025 -0.0125 0 0.025 0.1 |
| Radius | `tshirt(...,min none=0,max full=9999)` | 0 4 8 16 24 32 48 9999 |
| Stroke width | `boldness(number([...]))` | 0.25 0.5 0.75 1 1.5 2 3 5 8 |
| Visibility/opacity | `boldness(number([...]))` | 0.02 0.05 0.10 0.20 0.40 0.60 0.80 0.95 1.0 |
| Color tone | `boldness(color(seed))` OKLCH | hint.50 faint.100 subtle.200 soft.300 mid.500 firm.600 bold.700 strong.800 intense.900 |
| Boldness vocab (9) | uniform | hint faint subtle soft mid firm bold strong intense |
| Looseness vocab (6) | uniform | none tight snug normal relaxed loose |
| Color ratio | 60-30-10 | 60 surface / 30 text+border / 10 accent |
| Whitespace | composition | 60-70% target |
| Heading scale | jump rule | 150-200% of body; anchor 2-3x body |
| Headline / subtitle length | composition | 4-8 words / 12-25 words |
| Contrast (AA) | a11y | 4.5:1 (<18px) · 3:1 (18px+ bold) |
| Shadow opacity | effects | 0.04-0.10 (light) · 0.12-0.20 (dark glow) |
| Gradient angle = mood | gradients | 180 ground · 135 energize · 0 uplift · 90 progress |
| Effects per page | budget | ≤1-2 decorations; effect count gated by personality |
| Chart series | data viz | max 6 (`*.mid` palette) |

**Bottom line:** Brilliant's edge in composition is not better taste in prose — it's (1) composition encoded as **enforceable numerics + a forced token-stop grammar**, (2) a **per-block visual self-review loop** that grades spacing/hierarchy/alignment before continuing, and (3) a **deep mechanical substrate (layout-patterns, components, blocks)** that the lightweight judgment docs assume. Our Lumen agent appears to lack the numeric scales, gets trapped in a *syntax-level* Phase A repair loop that never reaches the *composition-level* review, and almost certainly ships only a fraction of the dependency graph these foundation docs require.
