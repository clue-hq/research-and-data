# R6 — OUR Knowledge Docs (the Lumen agent's knowledge)

Audit slice: every file under `apps/agent_runtime/knowledge_docs/` (AGENT.md, the
`knowledge/design/`, `knowledge/lumen-dsl/`, `knowledge/export/`, `knowledge/assets/`,
`knowledge/design-systems/`, and `knowledge/loop/` docs, plus the six `skills/*/SKILL.md`
procedures the docs map to). Read in full. ~20 docs total.

Bottom line up front: **our knowledge base teaches the agent how to make the compiler
and preflight happy, not how to make a composition good.** It is a *DSL grammar reference
plus a repair-discipline manual*. The composition/spacing/hierarchy guidance is
qualitative prose ("generous margins", "clear hierarchy") with essentially **no numeric
scales, no spacing system, no grid, no density rules, and no pre-composed blocks**. The
only concrete numbers in the entire corpus are line-height ranges and example values
inside skeletons that the agent copies literally. This explains lower-quality
compositions even when individual components compile fine — and it directly feeds the
repair-loop non-convergence (see §4/§5).

---

## 1. What composition / spacing / density / hierarchy guidance do we actually give?

**Verdict: vague and qualitative, with three exceptions that are themselves thin.**

### What's concrete (the only numbers in the whole corpus)

- **Line height ranges** (the single most concrete piece of typographic guidance), in
  `knowledge/design/typography-and-composition.md:20` and repeated in
  `skills/create-design/SKILL.md:38`, `knowledge/lumen-dsl/text.md:43`:
  > "tighter headlines such as `lh(1.05)` to `lh(1.15)`, relaxed body copy such as
  > `lh(1.3)` to `lh(1.45)`."
- **Print margins**, exactly once, in `knowledge/design/layout-recipes.md:62`:
  > "Keep print margins in points, usually `36-54pt`".
- **Example literal values inside skeletons** — `g(28)`, `pad(72)`, `g(18)`, `pad(36)`,
  `g(12)`, `pad(18)`, `g(20)`, `pad(54,48)`, `s(220,56)` (the CTA button), `s(360,420)`
  (a proof panel). These appear in `layout-recipes.md` and `create-design/SKILL.md:62-70`.
  Critically these are **example values inside one skeleton each**, not a spacing *scale*
  or a system. There is no statement like "use an 8pt grid" or "gaps come from {8, 16, 24,
  32, 48}". The agent has no principled way to pick a gap; it copies the skeleton's number
  or guesses.

### What's vague (the dominant mode)

Everything else about composition is adjectival, not measurable:

- `skills/create-design/SKILL.md:36`: **"One clear message, one CTA, generous margins.
  Keep text off the edges."** — "generous" and "off the edges" are undefined. No margin
  token, no minimum edge distance.
- `layout-recipes.md:16`: "one CTA, and generous margins. Keep text away from edges."
- `typography-and-composition.md:27`: **"Use high contrast and simple hierarchy."** — no
  contrast ratio, no type-scale ratio, no size steps.
- `typography-and-composition.md:10-13`: "Use short headlines. Keep headline boxes wide
  enough for expected copy." — "short" and "wide enough" are undefined.
- `visual-review/SKILL.md:25`: accept only when the design "has **enough spacing** and
  coherent alignment", "clear hierarchy and readable typography." The reviewer's own
  acceptance bar is qualitative — there is no rubric, no measured spacing/contrast/scale
  threshold it can test against. This is a self-reinforcing problem: a vague author guided
  by a vague reviewer.
- `brand-fit-critique.md:13`: "Does the design look generic, or does it plausibly belong
  to this client?" — taste question with no operationalization.

### Density / hierarchy specifically

- **Density**: there is essentially no density guidance. `modes.md:11` lists a
  `density: comfortable | compact` *mode axis* but says nothing about what density means
  numerically — no content-per-area target, no "max N elements per card", no information-
  density heuristic. `create-design/SKILL.md:52-58` ("Size the content to the box") is the
  closest thing, and it is entirely about **avoiding text overflow**, not about visual
  density: "A dense card that packs a header + several label/value pairs + a paragraph into
  a small fixed card **will** overflow." The "fix" offered is "make the card taller" — i.e.
  it treats density purely as a fit/overflow risk, never as a composition quality.
- **Hierarchy**: reduced to (a) line-height ranges, (b) "simple hierarchy" / "clear
  hierarchy" prose, and (c) the branded `style($type.display/headline/body/cta/caption/
  legal)` role list (`token-taxonomy.md:57`). There is **no type scale** (no ratio, no
  px/pt steps for display vs headline vs body), **no guidance on size contrast between
  levels**, no rule like "headline ≥ 1.5× body." When unbranded, the agent free-guesses
  font sizes — and `token-taxonomy.md:42` even warns *against* guessed values like
  `font("Inter",57,791,left)` without giving the agent a sanctioned scale to use instead.

**Inference:** the corpus optimizes for "compiles + survives personalization data
(overflow)" — which is exactly the bar AGENT.md sets ("survives real personalization
data," `AGENT.md:26`). Visual *quality* (rhythm, scale, density, balance) is asserted as
a goal but never specified, so the agent has nothing to execute against.

---

## 2. Our lumen-dsl layout model

**Verdict: it is a genuine auto-layout model (Figma-style stacks), NOT pure absolute
placement — but it is a *single-axis flexbox only*, with no grid, no per-corner radius,
no vertical alignment for text, and the docs constantly push the agent toward it while
still permitting absolute `p(x,y)` placement that "doesn't survive content that varies."**

### It DOES support auto-layout / stacks / gap / padding / alignment / sizing

From `knowledge/lumen-dsl/grammar.md:89-94`:
> Auto-layout (on `al` containers; see `layout.md`):
> `al(v|h, x(anchor), y(anchor), g(gap), pad(...), grow(n), wrap(bool))` where
> anchor ∈ `start`/`s`, `center`/`c`, `end`/`e`, `space_between`/`sb`, `stretch`/`st`.

From `knowledge/lumen-dsl/layout.md:69-78`, the auto-layout parts table:
| Part | Values | Meaning |
| direction | `v` (column) · `h` (row) | main axis |
| `x(anchor)` | `s/c/e/sb/st` | main-axis distribution / cross-axis |
| `y(anchor)` | same set | the other axis |
| `g(n)` | number / `$space.*` | gap between children |
| `pad(a)` · `pad(v,h)` · `pad(t,r,b,l)` | 1/2/4 values | padding |
| `grow(n)` | number | child grow factor |
| `wrap(bool)` | | wrap to multiple lines |

Sizing tokens (`layout.md:9-15`): `<number>` fixed `pt`, `hug` (fit content), `fill`
(fill parent main-axis), `fill(weight)` / `fill:weight` (weighted fill), `$token`. This
is recognizably Figma auto-layout: hug/fill/fixed + gap + padding + main/cross alignment +
weighted grow.

The docs **strongly prefer** auto-layout over coordinates. `layout.md:4-6`:
> "Prefer **systematic** structure (auto-layout with consistent gaps) over hand-placed
> `p(x,y)` coordinates. Hand placement is fine for a few absolute elements; it does not
> survive content that varies by account/contact."

`create-design/SKILL.md:33`: "**Structure with auto-layout**, not hand coordinates,
whenever spacing should be systematic."

### But it is also fundamentally absolute-coordinate-aware, and that's a trap

**Every node carries an absolute `p(x,y)`** even inside auto-layout. From `grammar.md:62`:
> `p(x,y)` | 2 | position in canonical layout points (`pt`), local to the parent/artboard

In the skeletons, children inside an `al` stack are written `p(0,0)` (e.g.
`layout-recipes.md:33-36`), so position is ignored by the solver — but the grammar still
*requires/permits* `p()` everywhere, and the "bad patterns" the docs warn about are
exactly hand-placed coordinate designs (`typography-and-composition.md:39-42`,
`text.md:47-50`):
> `headline text "Very long headline..." p(40,40) s(300,24) font("Inter",64,800,left)`

So the model is a **hybrid**: auto-layout containers + absolute positioning available on
every node. The docs admit hand-placement "does not survive content that varies"
(`layout.md:6`) yet the DSL leaves it fully available, and the only thing steering the
agent away from it is prose preference, not a constraint.

### What the layout model LACKS (grammar-confirmed gaps)

- **No grid / no multi-column layout primitive.** Auto-layout is strictly *single-axis*
  (`v` or `h`). The only 2-D behavior is `wrap(bool)` (`layout.md:78`) — a flex-wrap, not
  a grid with tracks/columns/rows/areas. `layout-recipes.md:131` explicitly lists
  "editorial grid systems" and "dense stat/table modules" under **Future Scaffold** —
  i.e. not supported.
- **No vertical text alignment.** `layout.md:86-97`: "there is no `valign`". To
  vertically center text you must wrap it in an `al(...)` with `y(c)`.
  `valign(...)`/`text_align(...)` → `LUMD0212 unknown property`.
- **No per-corner radius.** `grammar.md:66`: "`rd(r)` … uniform corner radius — **4-arg
  per-corner is NOT supported** (→ `LUMD0230`)." `effects/SKILL.md:74-79` confirms the
  renderer "squares non-uniform corners anyway."
- **Modify-line auto-layout is forbidden.** `layout-cluster-repair.md:71-75`: "Do not
  write `#node al(...)` in a repair. `al(...)` is creation syntax… not a supported modify-
  line property. Do not write `#node wrap(...)` either." So during repair the agent
  *cannot change the layout container* — it can only nudge `g/pad/x/y/p/s`. This sharply
  limits what a layout repair can actually achieve.

**Inference:** a single-axis flex model with no grid is adequate for one centered message
stack, but it makes genuinely composed layouts (multi-column one-pagers, stat grids,
asymmetric editorial layouts) impossible to express systematically — so the agent falls
back to fixed sizes and `p(x,y)`, which is exactly the failure mode the docs warn against.
This is a structural ceiling on composition quality.

---

## 3. Do we ship pre-composed blocks / patterns / templates?

**Verdict: NO. We ship primitives + recipes-as-prose only. There is no template/block
library, no component registry, no parameterized pattern.**

What exists:

- **Primitives** (node kinds, `grammar.md:45-47`): containers `frame/group/autolayout`;
  leaves `rect/ellipse/line/text/image/vector/svg/instance`. That's it.
- **Recipes-as-prose / skeletons** in `layout-recipes.md`: "Square Social Ad", "A4
  Appointment / One-Pager", "US Letter One-Pager", "Landscape Social / LinkedIn Ad",
  "Email Hero", "Direct Mail Header/Postcard". But these are **descriptive bullet lists
  plus one tiny DSL skeleton each**, not reusable blocks. Two of the six (Email Hero
  `layout-recipes.md:87-92`, Direct Mail `:93-96`) have **no DSL skeleton at all** — only
  a sentence of advice ("Use a compact header, a large headline, one supporting sentence,
  and a CTA").
- The skeletons are 5-9 lines each and identical in spirit: one `page`, one `artboard`
  `al(v,…)`, a `content`/`card` stack with `headline` + `body` + `cta`. There is **no
  pricing block, no feature grid, no testimonial block, no stat row, no logo bar, no
  nav, no footer, no multi-card layout, no hero+sidebar** as a reusable unit.
- `instance`/`inst` exists as a node kind (`grammar.md:47`) and `clone`/`replace` exist
  as directives (`directives.md:42-44`), which *could* support a component/template
  system — but **no template or component is actually shipped or referenced** anywhere in
  the knowledge. There is no catalogue of `source(id)` instances to draw from.

**Inference:** Brilliant (per ground-truth context, ~91 docs vs our ~19) almost certainly
ships a far richer pattern/block library. We hand the agent ~6 thin prose recipes (4 with
a skeleton, 2 without) and ask it to invent every composition from primitives. That is a
huge quality delta: the agent has no vetted "good layout" to start from, so each run
re-derives spacing/hierarchy from scratch using the vague guidance in §1.

The recipe doc even admits the catalogue is a stub — `layout-recipes.md:122-132`
**Future Scaffold**: "responsive/variant recipes, repeater/conditional regions, dense
stat/table modules, multi-page brochures, pagination rules, editorial grid systems." All
the building blocks of real composition are explicitly *not yet here*.

---

## 4. What does `knowledge/loop/` say about the repair loop and convergence?

Two files: `authoring-and-repair.md` and `layout-cluster-repair.md`. Both define a
*surgical, smallest-edit* repair discipline. Neither defines **any convergence guarantee,
iteration budget, escalation ladder, or "I am stuck / change strategy" path** — which is
the heart of why all 5 runs hit `max_iterations_reached`.

### The loop (`authoring-and-repair.md:8-22`)

The 12-step loop: load knowledge → author block → `compile_dsl_block` → repair compile
diagnostics → `preflight_design` → **repair preflight diagnostics before preview
acceptance** → export → validate bytes → embed → visual review → persist critique
verbatim → "**Stop only on acceptance, max iterations, or a deterministic tool failure**."

Key fact tying directly to the failure mode: step 6 is "Repair preflight diagnostics
**before** preview acceptance," and AGENT.md §3 (`AGENT.md:54`) makes preflight a hard
gate: "→ `preflight_design` → repair preflight diagnostics, then continue." **There is no
"give up on this preflight diagnostic and proceed to render anyway" branch in the normal
loop.** The only escape valve is the *debug* preview, `authoring-and-repair.md:63-68`:
> "A preview may be exported from a scene that still has preflight errors, for human
> inspection only (`export_preview_bundle(debug_only=True)`). It … does **not** satisfy
> final acceptance."

So if a preflight diagnostic (e.g. an artboard-bounds or parent-containment `LUMV09xx`,
or a brand-governance `LUMB08xx`) cannot be cleared by the allowed surgical edits, the
loop has nowhere to go but to keep repairing — exactly the observed
`"Maximum Phase A repair iterations reached"`. **The knowledge contains no convergence
heuristic** ("if the same diagnostic recurs N times, escalate / re-author the cluster /
record a gap / accept the best draft and stop"). The closest the corpus gets is
`record_gap` (`tools/SKILL.md:93`) for *unsupported semantics* — but a recurring
*bounds* diagnostic isn't an unsupported-semantics gap, so the agent never reaches for it.

### Surgical-repair discipline — and how it can *prevent* convergence

`authoring-and-repair.md:24-36` and `repair-design/SKILL.md` are emphatic that repairs
must be the smallest possible change:

- `repair-design/SKILL.md:13-16`: "**Never re-emit a `page …` line or an existing node id
  during a repair.** Doing so is a repair *failure* — it raises `LUMA0200`/duplicate-id."
- `repair-design/SKILL.md:9`: "A repair changes the **smallest thing that fixes the
  diagnostic** and nothing else."
- The actuator order (`repair-design/SKILL.md:22-49`): (1) modify line `#id prop(...)`,
  (2) layout-cluster repair (only for bounds/containment), (3) structural directive,
  (4) checked `apply_structured_edit` with strict scope, (5) continuation — "Re-authoring
  the whole scene is the **last** resort."

This is sound *anti-thrash* discipline, but it is also a **trap for composition-level
problems**. If the real defect is "the whole layout is badly composed / too dense / wrong
hierarchy," the doctrine forbids the only move that would fix it (re-author) and channels
the agent into endless one-node nudges that never clear a global geometry diagnostic.
`AGENT.md:122-126` (invariants #2/#3) and `authoring-and-repair.md:56-61` ("Don't lose a
good design") reinforce this: don't delete-and-recreate, preserve the best draft. Good for
safety; bad for escaping a local minimum.

### Layout-cluster repair (`layout-cluster-repair.md`)

This is the one place geometry repair is allowed to touch more than a single node, for
`LUMV09xx` bounds/containment/background/scale-mismatch diagnostics. Allowed changes
(`:25-40`): modify `p/s`, `fill/hug/fixed/weighted-fill`, adjust *existing* `al` frames'
`g/pad/x/y`, `wrap_text(true)`, `max_lines`, resize parent, `s(fill,fill)` for the root
frame, convert a background-like rect into the artboard fill. Prohibited (`:42-53`):
delete page, delete unrelated nodes, change unrelated slots/brand/assets/copy, regenerate
the whole scene, change page/export dims unless the diagnostic targets page size, hardcode
`s(595,842)`/`s(612,792)`, use `mm`/pixels for child coords.

**Convergence-relevant limitation:** even this bounded repair **cannot add or change an
auto-layout container** (`:71-73` — `#node al(...)` and `#node wrap(...)` are not lowered
on modify lines). So if a bounds failure is caused by a *missing* stack or *wrong*
direction, the cluster repair literally cannot express the fix via DSL modify lines; the
doc says fall back to a scoped `apply_structured_edit` (`:77-79`) — a narrow escape that
the author may not reliably reach for. **Inference:** this gap is a plausible direct cause
of the observed non-convergence — the agent keeps issuing `g/pad/p/s` nudges that can't
clear a structural bounds diagnostic, burning iterations until `max_iterations_reached`.

### What's missing from the loop knowledge (convergence-wise)

- No iteration budget stated, no "after K repairs of the same code, do X."
- No loop-detection / oscillation guard ("you already tried this edit, it didn't clear").
- No principled "accept best draft and stop" decision — the doc says the best draft stays
  on canvas (`:56-61`) but the agent is told "Done is reviewer acceptance" (`:71-74`,
  AGENT.md:61) and given no sanctioned way to *choose* to stop short of acceptance.
- No diagnostic-to-strategy escalation table (e.g. "recurring `LUMV09xx` bounds ⇒
  re-structure the artboard stack" — which would require re-authoring, which is forbidden).

---

## 5. Catalog of gaps vs a rich design system

Concrete, evidence-based list of what our ~19-doc knowledge base lacks. Grouped.

### A. Spacing / layout system
- **No spacing scale.** No `{4,8,12,16,24,32,48,64}` ladder, no 8pt-grid rule. Gaps in
  recipes (`g(28)`, `g(18)`, `g(12)`) are unexplained example values. `$space.*` tokens
  exist (`token-taxonomy.md:21`) but are only defined as *role names*
  (`space.stack.default`, `space.page.margin`, `space.card.padding`) with **no values and
  no scale relationship**.
- **No grid system.** Single-axis flex only; no columns/tracks/areas (`layout.md:55-78`).
  Listed as Future Scaffold (`layout-recipes.md:131`).
- **No margin/edge-safe-area numbers** beyond print "36-54pt" once (`layout-recipes.md:62`).
  Digital margins are "generous" (undefined).
- **No alignment-grid / baseline-grid** concept.
- **No section/rhythm rules** — how much space between major regions vs within a card.

### B. Typography / hierarchy
- **No type scale** (no ratio, no size steps for display→headline→body→caption→legal).
  Only role *names* exist (`type-taxonomy`/`brand-and-tokens`), no sizes, no contrast
  between levels.
- **No size-contrast or weight-contrast guidance** ("headline must be ≥ N× body").
- **No measure/line-length guidance** (chars-per-line) — only "boxes wide enough"
  (`text.md:40`).
- Line-height ranges are the *only* concrete typographic number (`text.md:43`).
- **No font-pairing guidance**, no fallback type scale for the *unbranded* case (and
  `token-taxonomy.md:42` warns against guessed `font("Inter",57,791,...)` without offering
  a sanctioned scale).

### C. Composition / density / balance
- **No density model.** `density: comfortable|compact` is a mode axis (`modes.md:11`) with
  no numeric meaning. Density only ever appears as an overflow risk
  (`create-design/SKILL.md:52-58`), never as a quality dimension.
- **No visual-balance / whitespace-ratio guidance** beyond "generous margins."
- **No focal-point / reading-order / Z-or-F-pattern guidance.**
- **No "max elements per region", no information-architecture heuristics.**
- `visual_balance` is a *reject category* in `visual-review/SKILL.md:45` with **no
  definition of what balanced means** — the reviewer is asked to judge a property the
  knowledge never specifies.

### D. Pre-composed blocks / components / templates
- **No template/block library** at all (see §3). 6 prose recipes, 4 with a thin skeleton,
  2 (Email Hero, Direct Mail) with none.
- **No component registry / no shipped `instance` sources** despite `instance`/`clone`/
  `replace` existing in the grammar.
- **No pattern variants** (hero+sidebar, feature grid, stat row, pricing table,
  testimonial, logo bar, nav/footer) — all "Future Scaffold" (`layout-recipes.md:122-132`).

### E. Color / contrast
- **No contrast-ratio rule** (no WCAG AA/AAA, no min contrast for text-on-surface).
  "Use high contrast" (`typography-and-composition.md:27`) is the entire guidance.
- **No palette-construction guidance** for the unbranded case — color forms are documented
  (`colors.md`) but *how to choose a harmonious set* is not.
- `surface.*`/`text.*` token roles exist but with **no values and no contrast pairing
  rules** (which text role goes on which surface role).

### F. Imagery / assets
- **No real asset pipeline.** `asset-placement.md:26-31`: "current Phase A runtime does not
  own real upload, storage, provider image generation, vectorization, or production asset
  processing." Agent must use fixture assets or record a gap.
- Asset placement guidance is qualitative ("respect aspect ratio, crop/fit, min readable
  size, enough whitespace around logos" — `asset-placement.md:18-23`) with **no numbers**
  (no min logo px, no clearspace multiple).

### G. Export / proofing
- **No print-safe PDF validation, no bleed/safe-area proofing, no font embedding checks,
  no visual-regression metrics** — all "Future Scaffold" (`preview-quality.md:31-39`).
- **No browser-screenshot parity** guaranteed (`preview-quality.md:24-28`); critic often
  reviews an SVG→PNG raster, not a true render.

### H. The repair loop (convergence) — see §4
- No iteration budget, no oscillation/loop guard, no escalation ladder, no sanctioned
  "accept best draft and stop short of acceptance" path, no diagnostic→strategy table.
- Surgical-only doctrine + forbidden re-author + modify-line `al()` not lowered ⇒ a
  structural composition defect can be *unfixable within the allowed edit surface*, which
  plausibly *causes* `max_iterations_reached`.

### I. Renderer / DSL expressiveness ceilings (limit composition directly)
- Per-corner radius unsupported (`grammar.md:66`, `effects/SKILL.md:74-79`).
- Vertical text alignment unsupported except via wrapper auto-layout (`layout.md:86-97`).
- Grid/wrap-to-tracks unsupported (flex-wrap only).
- `ds(...)` design-system switch parsed but **not lowered** (`LUMD0700`,
  `directives.md:8-9`); `undo/redo` need a history adapter.
- RTL/bidi shaping, rich-text spans, PDF embedding all Future Scaffold
  (`typography-and-composition.md:63-67`).

---

## Synthesis (how this slice explains the quality gap)

1. **We teach grammar + repair discipline, not composition.** ~19 docs that are 80%
   "how to write a line the compiler accepts" and "how to repair the smallest failing
   target." The 20% on visual quality is adjectives ("generous", "clear", "enough"), with
   the only hard numbers being line-height ranges and a single print-margin range.

2. **No spacing scale, no type scale, no grid, no density model, no contrast rule.** The
   agent cannot reason systematically about rhythm/hierarchy/density because we never give
   it a system — only role *names* (`$space.*`, `$type.*`) with no values, ratios, or
   pairing rules. Even our own visual reviewer is asked to judge "spacing", "hierarchy",
   "visual_balance" against an unspecified bar.

3. **No pre-composed blocks.** ~6 thin prose recipes (2 without any DSL) vs primitives.
   Every composition is re-invented from scratch each run, with no vetted starting point —
   the opposite of a rich block/template library.

4. **A single-axis flex model with absolute-position escape hatches.** Real composed
   layouts (grids, multi-column, stat rows) are inexpressible, so the agent drops to
   fixed sizes / `p(x,y)`, the exact pattern the docs admit "does not survive content."

5. **The repair loop has no convergence machinery.** Surgical-only + forbidden re-author +
   modify-line `al()` not lowered + preflight as a hard gate + no escalation/loop-guard +
   no sanctioned stop-short = the agent grinds the same un-clearable preflight diagnostic
   until `max_iterations_reached`. This is consistent with all 5 runs ending
   `status=failed`, `stop_reason=max_iterations_reached`,
   `"Maximum Phase A repair iterations reached."`

**Inference (label: inference):** the dominant root cause for *low composition quality* is
gaps A–D (no spacing/type system, no blocks); the dominant root cause for the *5 hard
failures* is gap H + I (no convergence machinery against geometry/preflight diagnostics
that the allowed surgical edit surface cannot clear). The two compound: weak composition
guidance produces designs that trip bounds/fit diagnostics, and the loop then cannot
escape them.
