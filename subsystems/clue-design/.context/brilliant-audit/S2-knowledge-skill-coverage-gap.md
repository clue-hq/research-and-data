# S2 — Knowledge & Skill Coverage Gap + the Template/Block Question

**Synthesis of:** R1 (Brilliant foundations), R3 (Brilliant blocks & design-systems), R4 (Brilliant visual richness), R6 (our knowledge), R7 (our skills), R8 (our runtime).
**Scope of this synthesis:** (a) how much of the quality gap is "Brilliant assembles pre-composed, correctly-spaced blocks while we draw from scratch"; (b) exactly what we lack in knowledge *breadth* and procedural *depth*; (c) whether the rich knowledge even reaches our model at runtime.

All counts in this report were re-verified directly against the filesystem during synthesis (not just inherited from the readers).

---

## 0. Headline (decisive answer)

The composition-quality gap is **primarily a knowledge-architecture gap, not a model gap**, and it decomposes into three stacked causes, ranked by impact:

1. **Brilliant assembles vetted, pre-proportioned BLOCKS; we draw every block from primitives with no catalog.** (R3, R6) — *the single largest driver of bad spacing/density/hierarchy.* Brilliant ships a 7-file, ~50-block catalog where internal padding, gap, type scale, and color roles are pre-decided as token references. We ship **zero** `blocks/` docs (verified: no `blocks` directory exists anywhere under `apps/agent_runtime` except webpack `node_modules`). Our agent re-derives every block's proportions from ~6 prose recipes each run.
2. **Brilliant encodes composition as enforceable NUMERICS + a forced token-stop grammar; we encode it as adjectives.** (R1, R6, R7) — 60-30-10, 60-70% whitespace, anchor 2-3x body, heading 150-200% of body, shadow opacity 0.04-0.10, WCAG 4.5:1/3:1 vs our "generous margins," "clear hierarchy," "enough spacing." Our only hard numbers are line-height ranges and one print-margin range.
3. **Even our limited knowledge mostly does NOT reach the model at runtime, and the runtime has no layout engine to compute spacing even if it did.** (R8, cross-checked here) — Confirmed: knowledge is capped to **6 snippets × 800 chars ≈ 4.8 KB total** (`tools.py:50-51`), and the shipped LLM provider path (`providers.py`) loads **no SKILL.md and calls no knowledge loader at all**. So the answer to (c) is **no** — and this means breadth gaps #1/#2 are *understated* in their effective severity, because much of even the thin knowledge we do have never arrives.

**Bottom line:** This is not "good components, bad luck." Brilliant pre-bakes composition into (blocks → tokens → numeric rules → mode resolver → flex engine), four enforcement layers we almost entirely lack. We pre-bake almost nothing and then starve the model of the little we have at runtime.

---

## 1. Doc-count and structure ground truth (verified during synthesis)

| Metric | Brilliant | Lumen | Source / verification |
|---|---|---|---|
| Knowledge `.md` docs | **91** | **26** | `find …/knowledge -name '*.md'`; R1/R3 said 91, R8 said 99 *all* .md — both correct, see note |
| ALL `.md` (incl. reference/specs) | 99 | 26 | `find …/brilliant -name '*.md'` |
| Knowledge subdirectories | **10** | **6** | `ls -d …/knowledge/*/` |
| `blocks/` catalog | **7 files** (`design/blocks/`) | **0 (dir absent)** | verified: no `blocks` dir under our tree |
| `webgl/` GLSL docs | 15 files, **4,004 lines** | 0 | re-counted: 4,004 lines confirmed |
| `charts/` | 5 | 0 | verified |
| `effects/` | 4 | (1 grammar-only `skills/effects`) | verified |
| `images/` + `svg/` (AI gen) | 3 + 2 | 0 (stub only) | verified |
| `blueprint/` (mechanical substrate) | **24** | 0 (no analog) | verified |
| `design/` (judgment layer) | 14 | 3 (`layout-recipes`, `typography-and-composition`, `artboard-frame-authoring`) | verified |
| Top-level `skills/` (design) | 1 (`feedback` — a GitHub bug reporter, NOT design) | empty dir registered in `factory.py:36` | R7/R8; verified empty |

**Resolving the one apparent contradiction (R1/R3 "91" vs R8 "99"):** Both are right. **91** = `.md` files under `knowledge/`. **99** = *all* `.md` in the bundle including top-level specs (`v3-design-spec.md`, `objects-syntax.md`, etc.) and the `feedback` skill. The "~91 docs" framing in the task brief refers to the knowledge corpus and is exact. Our side is 26 .md total under `knowledge_docs/` (R6 said "~19/~20" counting the docs it read in full; the extra ~6 are the `skills/*/SKILL.md` procedure files and reference docs — R8's "26" is the on-disk total). **No real contradiction; use 91 knowledge / 99 total for Brilliant, 26 total for Lumen.**

**Brilliant's 91 docs are layered (R1 §4, R3 §1):** every `design/` and `blocks/` doc opens with `assumes: blueprint/...`. The 14 `design/` docs are a thin *judgment/index* layer sitting on a **24-file `blueprint/` mechanical substrate** + the 7-file blocks catalog + 5 charts + 4 effects + 15 webgl + image/svg gen. We ship the *judgment-prose layer only* (3 design docs), and even those lack the numerics — and we ship **none** of the substrate the judgment layer assumes.

---

## 2. (a) How much of the gap is "Brilliant assembles pre-composed blocks while we draw from scratch"?

**Verdict: this is the largest single driver — call it the dominant root cause of bad spacing/density/hierarchy specifically.** Evidence converges from three independent readers:

- **R3 (the smoking gun):** `design/blocks/` is a 7-file catalog of ~50 blocks. Every spacing/density decision is *already made* and expressed as a token reference, e.g.:
  - **Card**: `g($spacing.md) pad($spacing.lg)`, surface+stroke+`rd($radius.md)`+soft shadow, title `$font.size.lg`/sb over desc `$font.size.sm`/secondary, image-top `s(fill,180)`.
  - **Hero**: V `y(c),x(c) g($spacing.lg) pad(80-120,$spacing.3xl)`; eyebrow + Title(40-56,sb/b) + subtitle(16-18,secondary) + CTA row `g($spacing.md)`.
  - **Bento grid** (`patterns.md`): "Fixed-height rows; cells `fill:N` give asymmetric widths **with no pixel math**… make one cell dominant."
  - Even micro-proportions are vetted: chat bubble "~60-70% of parent width," watermark `$font.size.9xl` at `$visibility.faint`.
  - `patterns.md` is explicitly self-described as *"Compositions the primitives don't make obvious"* — i.e., Brilliant *knows* primitives alone produce bad composition and ships the fix.

- **R6 (our side, confirmed):** We ship **no blocks**. Our entire composition knowledge is 3 design files; `layout-recipes.md` has **6 prose recipes, only 4 with a DSL skeleton** (Email Hero and Direct Mail have *no skeleton at all*, just a sentence). Skeletons use **ad-hoc magic numbers** (`g(28)`/`pad(72)`, then `g(18)`/`pad(36)`, then `g(20)`/`pad(54,48)`) — a different rhythm per recipe, no shared scale. There is **no pricing block, feature grid, testimonial, stat row, logo bar, nav, footer, or multi-card unit** anywhere. `instance`/`clone`/`replace` exist in the grammar but **no component/template is ever shipped or referenced**.

- **R7 (our skills, confirmed):** `create-design` has **no composition-planning step** — it goes "pin surface → emit DSL" with one canned LinkedIn-square skeleton, anchoring *every* layout to the same vertical stack. No `comp`/`inst` discipline.

**Why this maps directly to the symptom ("components fine, composition bad"):** Internal-block proportions (card padding, hero rhythm, stat-tile density) are *block-level* concerns Brilliant has pre-solved. Between-block concerns (section rhythm, surface alternation, focal dominance) are *page-level* concerns Brilliant's `foundations.md` + `patterns.md` pre-solve. We solve **neither** — we improvise both from primitives + adjectives every run. A component drawn in isolation can look fine (it's just a rect + text); a *composition* of many improvised components cannot, because nothing coordinates their proportions or rhythm.

**Quantified inference (labeled):** Of the *spacing/density/hierarchy* quality delta (excluding the premium-visual-richness delta, which R4 owns), I attribute **~60-70% to the missing blocks catalog + token-stop enforcement** and the remainder to missing page-level judgment numerics (§3) — because blocks are where the most consequential, most-repeated proportion decisions live, and they are 100% absent on our side.

---

## 3. (b) Exactly what we're missing — BREADTH and DEPTH

### 3.1 Breadth gap (whole capability domains Brilliant has, we lack)

Brilliant ships entire subsystems with zero Lumen analog (R3, R4, verified counts):
- **Blocks catalog** (7 docs, ~50 blocks) — §2.
- **Design-systems engine** (3 docs): one OKLCH seed → 11-step ramp + 9-stop `boldness` vocab; 22 Tailwind palettes; semantic aliases (`surface`/`surface.container`/`text.primary`/`secondary`); `authoring-modes.md` mode transforms (`shift(N)`/`mirror`/`outward(N)`) so dark/compact/large-text come from **re-resolving the same tokens**, not re-authoring (R3 §3-4).
- **Visual richness** (R4, 38 docs across effects/webgl/charts/svg/images): 6 GPU shaders (4,004 lines of real GLSL — re-verified), 7 image filters + 17-param Color Adjust, 6 stackable element effects (inner shadow/glow, outer glow, backdrop blur), `generate_image` (1-4K, parallel), `generate_svg`, `vectorize_image`, `svg(icon:)` library, chart recipes. **A repo-wide grep on our side for `metaball|holographic|duotone|halftone|webgl|shader|sparkline` returns zero** (R4). Our paint surface is solid fills, linear/radial gradients, one drop shadow, uniform-only radius (`LUMD0230`).
- **`blueprint/` mechanical substrate** (24 docs) — layout-patterns, components, text, effects mechanics. This is what `foundations.md`'s rules like "compute each position, never eyeball" and "declare with `comp`, stamp `inst()`" *depend on*. We have **no analog** (R1 §4).

### 3.2 Depth gap (same nominal topic, but ours is adjectives, theirs is numerics)

This is the more insidious gap because it hides inside topics we *appear* to cover:

| Topic | Brilliant (numeric/procedural) | Lumen (what we actually say) |
|---|---|---|
| **Spacing** | `tshirt` scale xs1…6xl32; **never bare** — emitting a raw number in `g()`/`pad()` is a **hard mode error** (R1 §2, R3 §3) | No spacing scale. `$space.*` are role *names* with no values (R6). Magic numbers in skeletons. "Generous margins" (`create-design:36`) |
| **Type hierarchy** | Anchor 2-3x body; heading 150-200% of body; hierarchy via Size+Weight+Color together (R1 §2) | No type scale, no size-contrast rule. Role names only. `token-taxonomy.md:42` *forbids* guessed sizes but offers no sanctioned scale (R6) |
| **Whitespace/density** | "aim for 60-70% white space, then ask what to remove"; density is a system-level lever that shifts the whole scale a notch (R1 §2,§3) | No whitespace target. `density` is a value-less mode axis; appears only as text-overflow risk ("make the card taller") (R6 §1) |
| **Color** | 60-30-10 ratio; tinted neutrals; WCAG 4.5:1/3:1 with concrete fail example `#10B981`→`#059669`; max-6 categorical series (R1 §3) | "Use high contrast" (`typography:27`). No ratio, no palette construction (R6 §E) |
| **Shadows** | Two layers mandatory, opacity 0.04-0.10, never pure black, consistent direction, elevation=importance (R1 §3) | Single `shadow()` only; "Single shadow looks fake" is a thing we *can't even avoid* (R4) |
| **Focal point** | "One dominant region… squint test: if nothing dominates, raise contrast" (R1 §1) | `visual_balance` is a *reject category* with no definition of balanced (R6 §C) |
| **Anti-cliché (negative knowledge)** | Whole doctrine: tinted-pill eyebrow = "#1 AI tell," low-opacity circles, blue-purple gradients, gradient CTAs, icon-in-box logo (R1 §1, R7 §4) | **None.** No anti-pattern guidance anywhere (R7 §5) |

**The self-reinforcing vagueness loop (R6 §1, R7 §3):** Our author is told to produce "clear hierarchy / enough spacing"; our reviewer (`visual-review/SKILL.md:25`) is told to *accept* when there's "enough spacing and clear hierarchy" — **the same undefined bar on both sides**. A vague author guided by a vague reviewer cannot converge on quality; there is no measurable target anywhere in the loop.

### 3.3 Procedural depth: assemble-and-tune vs draw-and-pray

- **Brilliant's procedure (R1 §1, R3 §2):** system → emotion → focal point → personality; *then* recall vetted blocks, stamp `comp`/`inst()` for 3+ similar elements ("Hand-coding N near-identical lines is a smell… never eyeball"), let the token+mode resolver normalize values, ration effects by personality, and run a **per-block visual self-review** (`objects-syntax.md:35-42`: screenshot + checklist for spacing/typography/contrast/alignment/clipping *before continuing*).
- **Lumen's procedure (R7 §1-2):** load knowledge → pin surface → emit one canned-skeleton DSL block → mechanical self-check (stable IDs, indentation, `pt` units, tokens-used). **No composition plan, no focal-point step, no whitespace target, no `comp`/`inst` step, and the "self-check" is about compiler survival, not aesthetics.** Our visual review may even judge from **SVG text geometry instead of PNG pixels** (R7 §3, R8 §3), under-detecting the exact perceptual qualities (density, balance) at issue.

---

## 4. (c) Does the rich knowledge even reach the model at runtime? — **NO** (cross-check R8)

This is the decisive multiplier, and it is **confirmed by direct file inspection during synthesis**, not just inherited from R8:

1. **Total knowledge delivered to the model ≈ 4.8 KB.** Verified `tools.py:50-51`:
   ```
   CONTEXT_MAX_KNOWLEDGE = 6
   CONTEXT_MAX_KNOWLEDGE_EXCERPT = 800
   ```
   `_capped_knowledge` (`tools.py:1487-1496`) takes at most the first **6** loaded snippets and truncates each excerpt to **800 chars**. Upstream, `read_task_knowledge` already limits to 8 snippets of 1600-char excerpts (`knowledge.py:104`, `best_excerpt max_chars=1600` at `:192`). So even though 26 docs sit on disk, the model sees ≤6 truncated fragments. **Breadth on disk is irrelevant if retrieval delivers 4.8 KB.**

2. **The shipped LLM provider path loads NO skill and NO knowledge.** Verified: `providers.py` contains **zero** references to `SKILL`, `create-design`, `repair-design`, `visual-review`, `load_knowledge`, or `read_task_knowledge`. The SKILL mounts at `prompts.py:160-175` are attached to *subagent definitions* (`lumen-dsl-author`, `lumen-visual-reviewer`) that the flat `model.invoke()` provider path (`LangChainDslAuthor`/`LangChainVisualReviewer`) **bypasses entirely**. So in the actual shipped run, the careful `create-design`/`repair-design`/`visual-review` procedures **never reach the model**.

3. **`max_iterations = 5`** (verified `config.py:23`) is a single shared budget across author+repair+critic for the whole run, and **`preview_format = "svg"`** (verified `config.py:24`) means no PNG is generated, so the critic is text-only under shipped defaults.

**Consequence for this synthesis:** The knowledge-breadth and depth gaps (§2-§3) are the *content* problem; the runtime starvation (§4) is the *delivery* problem, and it makes the content problem **worse than the doc counts alone suggest**. Even the ~26 docs we have are not meaningfully delivered: the model gets ≤6 × 800-char fragments and, on the shipped provider path, none of the procedural SKILLs. **There is no point shipping a blocks catalog or numeric design system if the runtime caps knowledge at 4.8 KB and the provider bypasses skills.** Any fix must address breadth, depth, AND delivery together.

**One more architectural multiplier (R8 §5, R4):** Brilliant has a bespoke flex/auto-layout engine that *computes* absolute positions from `al`/`g`/`pad`, plus `execute_commands` with `auto_layout`/`scale_elements_to_width`. Our runtime (`factory.py:37-61`) has **no layout solver** — spacing is hand-emitted by the LLM as `g()`/`pad()` literals and only *measured* post-compile. So even a perfectly knowledgeable model on our stack would still hand-guess every gap. The token-stop grammar (R1/R3) only *constrains* values; Brilliant's flex engine *computes* positions. We have neither.

---

## 5. Concrete content-gap table (capability → Brilliant → Lumen → impact on composition)

| Capability | Brilliant has | We have | Impact on composition |
|---|---|---|---|
| **Pre-composed block catalog** | 7 docs, ~50 blocks; internal pad/gap/type/role pre-baked as tokens (`card g($spacing.md) pad($spacing.lg)`, hero `pad(80-120)`, bento "no pixel math") | **Nothing** (no `blocks/` dir; 6 prose recipes, 2 with no skeleton) | **CRITICAL.** Every block re-improvised → inconsistent padding/density/hierarchy. Dominant driver of the bad-composition symptom |
| **Numeric spacing scale + bare-value rejection** | `tshirt` xs1…6xl32; raw number in `g()`/`pad()` = hard mode error | Role names only, no values; magic numbers; raw numbers allowed | **CRITICAL.** No rhythm; gaps guessed per element |
| **Type scale + hierarchy ratio** | Anchor 2-3x body; heading 150-200%; Size+Weight+Color | Role names + line-height ranges only; guessing forbidden but no scale given | **HIGH.** Muddy/flat hierarchy |
| **Whitespace + density doctrine** | 60-70% whitespace target; density shifts whole scale | None; density = overflow risk only | **HIGH.** Cramped or unbalanced layouts |
| **Color ratio + WCAG contrast** | 60-30-10; 4.5:1/3:1 with fail examples; ≤6 series | "Use high contrast" | **MED-HIGH.** Accent overuse, low contrast |
| **Focal-point / squint test** | One dominant region, raise contrast if nothing dominates | `visual_balance` is undefined reject category | **HIGH.** No visual entry point |
| **Anti-AI-cliché negative knowledge** | Full doctrine (eyebrow pill, blue-purple, gradient CTA, icon-box logo, circles) | None | **MED.** "Looks like AI/generic" tell |
| **Design-system token engine + modes** | Seed→11-step OKLCH ramp, 22 palettes, semantic aliases, mode transforms (re-resolve, don't re-author) | `$space.*`/`surface.*`/`text.*` role names, no values; `ds(...)` parsed-not-lowered (`LUMD0700`) | **HIGH.** No document-wide value consistency; dark mode hand-faked |
| **`comp`/`inst()` reuse discipline** | "3+ similar → declare once, stamp; never eyeball" | grammar has `instance`/`clone` but no doctrine/usage | **MED-HIGH.** N hand-coded near-duplicates drift |
| **Grid / multi-column** | Bento + layout-patterns (`blueprint/`, 24 docs) | Single-axis flex + `wrap` only; grids are "Future Scaffold" | **HIGH.** Real composed layouts inexpressible → agent drops to `p(x,y)` |
| **Layered/inner effects, blur, shaders, filters** | 38 docs; stackable; 1-2 tokens each; 4,004 lines GLSL | Single shadow, gradients, uniform radius (`LUMD0230`) | **HIGH** (premium feel; R4 owns this slice) |
| **AI image/SVG/icon generation** | `generate_image`/`generate_svg`/`vectorize`/`svg(icon:)` | Stub only (fixtures by ID) | **VERY HIGH** for "filled, professional" comps (R4) |
| **Per-block visual self-review loop** | Screenshot + spacing/type/contrast/alignment/clipping checklist before continuing | Loop checks compiler/preflight; critic text-only (svg) under defaults; not reached until preflight clean | **HIGH.** Composition defects never inspected |
| **Layout/flex compute engine** | Bespoke flex engine computes positions; `auto_layout`/`scale_to_width` commands | No solver; LLM hand-emits `g()`/`pad()`; measured post-compile only | **HIGH.** Spacing guessed even with perfect knowledge |
| **Knowledge delivery at runtime** | (skill bundle architecture mounts full docs) | **≤6 × 800 chars ≈ 4.8 KB; provider path loads no SKILL** | **CRITICAL multiplier.** Even our thin knowledge is starved |

---

## 6. Decisive ranking of root causes (by impact on composition quality)

1. **No pre-composed block catalog (assemble-vs-draw).** *Largest driver of bad spacing/density/hierarchy.* Evidence: R3 (Brilliant's 7-file catalog with pre-baked token proportions + `patterns.md` existing "because primitives don't make obvious"); R6 (we ship 0 blocks, 6 prose recipes, magic numbers); R7 (no `comp`/`inst`, one canned skeleton). **This + the missing token-stop scale is the core of the answer to (a): yes, the gap is substantially "Brilliant assembles correctly-spaced blocks while we draw from scratch."**
2. **Composition encoded as adjectives, not numerics, with no token-stop enforcement.** Evidence: R1/R3 (60-30-10, 60-70%, anchor 2-3x, bare-value=error) vs R6/R7 ("generous," "clear," "enough"; only line-height/print-margin numbers; reviewer's own bar is the same vague phrase). The author and reviewer share one undefined bar → cannot converge on quality.
3. **Runtime starvation + skill bypass + no layout engine (the delivery multiplier).** Evidence verified here: `CONTEXT_MAX_KNOWLEDGE=6`, `…_EXCERPT=800` (`tools.py:50-51`); `providers.py` loads no SKILL/knowledge; `factory.py:37-61` has no solver; `config.py` max_iter=5, svg preview. **Answer to (c): the rich knowledge does NOT reach the model — so fixing breadth/depth without fixing delivery will not move the needle.**
4. **Missing visual-richness primitives + recipes** (R4) — owns the *premium-feel* delta (flat fills, squared corners, empty image regions), largely orthogonal to spacing/hierarchy but a large part of "looks cheaper."
5. **No grid/multi-column expressiveness** (R6 §2) — structural ceiling: composed layouts are inexpressible systematically, pushing the agent to fragile `p(x,y)`.

**Note on the Phase-A `max_iterations_reached` deadlock:** R6 §4-5, R7 §3, and R8 §1.4/§4 own that failure mechanism (surgical-only repair + `LUMA0200` catch-22 + unclearable `LUMV0509` + no convergence/oscillation guard + 5-turn shared budget). It is *upstream-coupled* to this synthesis's focus: weak block/numeric scaffolding (§2-§3) produces dense first drafts that trip bounds/fit diagnostics (`LUMV0800/0801/0902/0810`), and the crippled repair surface then cannot escape them. **Knowledge poverty and loop non-convergence compound:** bad scaffolding generates the diagnostics; the loop can't clear them; the run dies before any composition-quality review ever runs. So even when we fix knowledge, the loop fix (other synthesis slice) is required for runs to *complete* and show the improvement.

---

## 7. What "fix it" implies (so the recommendation is actionable)

Ordered to match the ranking, and noting the dependency:

1. **Ship a blocks catalog** (port Brilliant's 7-file structure to Lumen DSL): hero, header, footer, card, stat tile, button + action-hierarchy, form/input, nav/sidebar, tabs, modal/toast, bento — each with pre-baked `g()`/`pad()`/type/role expressed against a real token scale. *Without this, nothing else closes the spacing/density gap.*
2. **Introduce a numeric design system**: a spacing `tshirt`-equivalent scale with **bare-value rejection in `g()`/`pad()`/`rd()`/text size**, a type scale with a heading=150-200% rule, 60-30-10, 60-70% whitespace target, WCAG ratios, and an anti-cliché doc. Give the reviewer a *measured* rubric so author and reviewer share a numeric bar.
3. **Fix delivery first or in parallel** (otherwise 1-2 are inert): raise/replace the 6×800-char cap with section-aware full-doc loading for the active task; make the shipped provider path actually load the SKILLs and knowledge it's supposed to; add a layout/flex solver so spacing is computed, not guessed; default to PNG preview so the critic sees pixels.
4. **Add visual-richness primitives + recipes** (R4) for premium feel.
5. **Add grid/multi-column** expressiveness to lift the structural ceiling.

---

## 8. Evidence index (file:line, verified during synthesis where marked ✓)

- Doc counts ✓: `find …/knowledge -name '*.md'` = 91; all = 99; subdirs = 10; `design/blocks/` = 7 files; `webgl` = 4,004 lines; Lumen `knowledge_docs` = 26 .md, 6 subdirs, **no `blocks` dir**, empty top-level `skills/`.
- Runtime caps ✓: `tools.py:50-51` (`CONTEXT_MAX_KNOWLEDGE = 6`, `CONTEXT_MAX_KNOWLEDGE_EXCERPT = 800`), `tools.py:1487-1496` (`_capped_knowledge`), `knowledge.py:104` (limit 8), `:192` (1600-char excerpt), `config.py:23-24` (max_iter 5, svg).
- Provider bypass ✓: `providers.py` has **no** `SKILL`/`create-design`/`repair-design`/`visual-review`/`load_knowledge` references; SKILL mounts are on subagent defs `prompts.py:160-175`.
- Brilliant blocks/tokens: R3 (`design/blocks/*`, `design-systems/{core,authoring-modes}.md`, `reference/components.md`).
- Brilliant numerics/foundations: R1 (`foundations.md`, `typography.md`, `colors.md`, `gradients.md`, `shadows.md`, `backgrounds.md`, `v3-design-spec.md`, `objects-syntax.md:35-42`).
- Brilliant visual richness: R4 (`effects/*`, `webgl/*`, `charts/*`, `images/*`, `svg/*`, `reference/{shaders,image-filters,effects}.md`).
- Lumen knowledge poverty: R6 (`layout-recipes.md:62,87-96,122-132`, `typography-and-composition.md:10-27`, `create-design/SKILL.md:36,52-58`, `token-taxonomy.md:21,42,57`, `grammar.md:66,89-94`, `layout.md:4-15,69-97`, `effects/SKILL.md:74-79 LUMD0230`).
- Lumen skills: R7 (`create-design`, `repair-design`, `visual-review` SKILLs; `LUMA0200` catch-22).
- Lumen runtime/loop: R8 (`loop.py:171,261-302,425-503,636-644,751`, `factory.py:37-61`, `LUMV0509`/`LUMV0805` unclearable).

**Bottom line for the synthesis consumer:** The knowledge/skill coverage gap is real, large, and three-layered: (1) we ship **no blocks** so we draw every composition from scratch — the dominant cause of bad spacing/density/hierarchy; (2) what design knowledge we do ship is **adjectives, not enforceable numerics**, with no shared author/reviewer bar; and (3) even that thin knowledge **does not reach the model at runtime** (≤4.8 KB, skill-less provider path, no layout engine). The answer to the template/block question is unambiguous: **yes — Brilliant does template-driven assembly of pre-proportioned blocks normalized by a token+mode resolver and a flex engine; we do primitive draw-from-scratch with vague prose and starved delivery.** Fix all three layers together, and fix the repair-loop (other slice) so runs complete to show it.
