# R4 — Brilliant's Visual-Richness Layer (what makes output look premium)

**Audit slice:** `brilliant/knowledge/{effects,webgl,charts,svg,images}/` + `reference/{shaders,image-filters,effects}.md`
**Comparison target:** our Lumen `apps/agent_runtime/knowledge_docs/` + Lumen DSL grammar/effects skill.
**Bottom line up front:** Brilliant ships an entire GPU-backed *visual-richness stack* — 6 procedural shaders (full GLSL), 7 image filters, 6 element effects, AI image generation (`generate_image`), AI vector generation (`generate_svg`), vectorization (`vectorize_image`), an icon library (`svg(icon:...)`), and a data-viz recipe set (bar/line/sparkline/table/heatmap). **Almost none of this exists in our Lumen engine.** Lumen's paint surface is limited to solid fills, linear/radial gradients, basic strokes, and a single drop shadow — and even *uniform-only corner radius* (`LUMD0230`). This is a large, structural slice of the "premium look" gap, and it is independent of the layout/spacing/repair-loop failures the other slices cover.

---

## 1. Catalog of rendering capabilities Brilliant exposes

### 1a. Element Effects — `reference/effects.md`
Two parallel systems, both first-class.

**Outer effects (`element.effects`, `EffectType` enum, 3 values):**
| Type | `EffectType` | Default |
|---|---|---|
| Drop Shadow | `dropShadow` | y:4, blur:8, opacity 0.25 |
| Outer Glow | `outerGlow` | blur:8, opacity 0.6, **screen blend** |
| Element Blur | `layerBlur` (UI "Element Blur") | radius:4 |

**Inner effects (fill types, `PaintStyleType`):**
| Type | `PaintStyleType` |
|---|---|
| Inner Shadow | `innerShadow` (y:2, blur:4, op 0.5) |
| Inner Glow | `innerGlow` (blur:4, op 0.6, screen) |
| Background Blur | `backgroundBlur` (radius 8, via `BackdropFilter`+`ClipPath`) |

Crucial detail: these are **stackable and z-order-interleaved** in the element's `fills` list (`effects.md` "Rendering Order"). You can place an inner shadow *between* two solid fills, stack multiple drop shadows for material elevation, or layer `solid(low-alpha) + backgroundBlur` for frosted glass. Each carries DS token bindings (`colorTokenRef`/`opacityTokenRef`) and **composite shadow tokens** that bundle multiple shadow layers into one named token.

**Directly raises perceived quality:** all of them. The "Tips" section of `effects.md` is literally a recipe list for premium polish: *subtle modern shadows* (`y:2/blur:4` @ 0.1-0.2 op), *elevation hierarchy* (stacked shadows), *frosted glass* (backdrop blur + 0.3-0.5 white), *neon glow* (outer glow, blur 12+, screen), *inset/pressed* (inner shadow). These are exactly the micro-details that separate "flat boxes" from "designed UI."

### 1b. Procedural Shaders — `reference/shaders.md` + `webgl/*`
6 GPU shader fills (`PaintStyleType`), applicable as **fills OR strokes, including on text glyphs**:

| UI label | `PaintStyleType` | Colors | Notes |
|---|---|---|---|
| Metaballs | `metaballs` | 5 | organic blob merging |
| Liquid Metal | `liquidMetal` | 2 | chromatic aberration, bump stripes |
| Iridescent | `holographic` (internal) | 3 | folded-noise iridescence |
| Liquid Stainless Steel | `liquidStainlessSteel` | 2 | multi-source lit chrome |
| Dithering | `dithering` | 2 | 7 pattern shapes × 4 dither matrices |
| Reactive Grid | `reactiveGrid` (Interactive) | 5 | cursor-reactive distortion + click ripples |

Each shader has **named presets** (10 per shader: Metaballs → *Lava Lamp, Galaxy, Blood Moon…*; Liquid Metal → *Mercury, Molten Gold, Obsidian…*; Iridescent → *Rainbow Foil, Oil Slick, Aurora…*) plus a full param set (e.g. Liquid Metal has 11 params: softness, repetition, shiftRed/shiftBlue, distortion, contour, angle, speed…) and a UV transform (scale/offsetX/offsetY/rotation) with Cmd-resize world-space compensation.

These are **not stubs** — `webgl/metaballs.md` carries the complete ~230-line GLSL ES 3.0 fragment shader (Lissajous ball trajectories, power-falloff field accumulation, interior shading, edge highlight, banding dither, premultiplied-alpha output). `webgl/` is **4,004 lines** of real shader source across 18 files, ported 1:1 from the app's SkSL (`shaders.md` "GLSL Conversion Notes": *"Shader body logic is identical to the Flutter version"*).

### 1c. Image Filters — `reference/image-filters.md` + `webgl/*`
7 GPU post-processing filters (each reprocesses everything below it in the z-order):

| Filter | `PaintStyleType` | Headline params |
|---|---|---|
| Noise/Grain | `noiseGrain` | amount, size, mono/color, gaussian, roughness, midtone-bias |
| Halftone | `halftone` | Standard/**CMYK** (4 rotated ink layers @ 15/75/0/45°), dot size, shape, hex grid |
| Pixelate | `pixelate` | cell size, 5 cell shapes, stretch, outline |
| Duotone | `duotone` | 2-3 tone luminance map, tritone, midpoint curve |
| Posterize | `posterize` | levels, RGB/Luminosity/HSL, gamma |
| Dither | `dither` | levels, Bayer 2×2/4×4/8×8, Blue Noise |
| Color Adjust | `colorAdjust` | **17 photo params** (exposure, contrast, highlights/shadows, vibrance, temperature, clarity, vignette, sepia…) + 27 presets (Noir, Cinematic, Clarendon, Faded…) |

Color Adjust alone is a Lightroom-grade grading panel applied non-destructively to any image/fill. Each filter has a curated preset table (Halftone → Newspaper, Comic Book, CMYK Classic; Duotone → Cyberpunk, Sepia, Tritone Cool; etc.).

### 1d. AI-generated imagery — `images/*` + `svg/*`
- **`generate_image`** (raster): hero photos, product shots, portraits, food, textures. Returns element ID + asset path, auto-placed on canvas. Supports 14 aspect ratios, 1K-4K, reference-image style transfer, **parallel generation** ("10 parallel = same time as 1 sequential").
- **`generate_svg`** (Quiver "Arrow" model): clean editable vector icons/logos/flat illustrations, dropped as **native vector elements** (one element per top-level shape), token-tintable after.
- **`vectorize_image`**: raster → editable paths.
- **`svg(icon:name)`**: built-in icon library invoked inline in the blueprint (e.g. `svg(icon:sparkle)`, `svg(icon:rocket)`).

### 1e. Data viz — `charts/*`
Recipe-grade guidance (not just primitives): vertical/horizontal/grouped **bar charts**, **line charts** (area fills, gridlines, comparison lines), **sparklines** (inline `v()` paths with `mi`/`st` node-type feel guidance + explicit "AI tell" avoidance), **tables** (alternating rows, column alignment, dividers), **stacked bars & contribution heatmaps**. These encode hard-won correctness rules (e.g. *"gridline y = label baseline, not label top"*; *"clip only on area fills, never stroke-only curves — else C405 overshoot"*; bezier handle-bulge top-pad math).

**Which directly raise perceived quality/polish (ranked):**
1. **Element/inner effects** (shadows, glows, backdrop blur) — the single biggest "designed vs. flat" lever; used on *every* premium card/button.
2. **AI image generation** — fills hero/banner/product regions with real photography instead of empty rectangles. A composition with a real hero image reads as professional instantly.
3. **Shaders** — premium hero/badge backdrops (glass-over-metaballs, liquid-steel, iridescent) that are otherwise impossible to fake.
4. **Image filters / Color Adjust** — turn flat raster into graded, editorial-looking imagery.
5. **Icons + SVG generation** — every real UI has icons; their absence reads as "wireframe."
6. **Charts** — for data-dense screens, the difference between a credible dashboard and labeled boxes.

---

## 2. How these are integrated into the DSL/document (are they cheap first-class primitives?)

**Yes — for Brilliant, almost everything is a one-token blueprint call.** The agent does not write GLSL or hand-roll shadows; it emits compact tokens that the renderer lowers to GPU paint.

- **Shaders** are compact `f[...]` fills with named params — e.g. from `effects/glass.md`:
  `f[(metaballs($color.surface,$violet.soft,$pink.soft,...,count(19),size(0.25),speed(0.3),scale(3)))]`
  and `f[(steel($primary.faint,$secondary.faint,flow(0.5),roughness(0.3),distortion(1),depth(1),angle(45),speed(0.4),scale(2)))]`. Color slots bind to DS tokens; the WebGL config carries resolved hex at export time (`webgl/overview.md` "Mapping Blueprint Values to WebGL Config").
- **Inner effects** are compact fill tokens with sensible defaults (`effects.md` "Via Compact Format"): `f[(inner())]`, `f[(glow($emerald.mid,o(0.8),blur(12),sp(4)))]`, `f[(blur(12))]`. Bare `inner()`/`glow()` auto-bind to `$color.shadow`/`$color.glow`.
- **Outer effects** are standalone tokens: `shadow($color.shadow,o(0.25),y(4),blur(8))`, `outerglow(...)`, `eblur(4)`.
- **Icons** inline: `svg(icon:sparkle) s(16,16) f[($slate.bold)]` — and they work *inside* `comp`/`inst()` with `override()` (`components.md` lines 254, 269), so a button component can swap its icon per instance for free.
- **AI image/SVG** are tool calls (`generate_image`, `generate_svg`, `vectorize_image`) that auto-place onto canvas and return element IDs for follow-up `execute_commands`.
- **Effects layering is z-order-native** — fills render bottom-to-top in list order, so the agent composes glass = `solid(low-alpha) + blur + inner-glow edge` as three ordered fills on one element.

The **one exception** (and it's instructive): image filters and Color Adjust have **NO compact blueprint syntax** (`image-filters.md` "General Notes": *"Image filters … cannot be authored in the `f[...]` blueprint compact form"*). They're added via command palette IDs (`add_halftone_fill`, `add_duotone_fill`, etc.) then param-tuned. So even Brilliant gates the most photo-heavy filters behind a command rather than the blueprint — but the agent still has a first-class lever.

**Net:** richness is *cheap* for Brilliant's agent. A premium glass-over-shader hero is ~2 blueprint lines (see `effects/glass.md`). The agent pays in tokens-of-text, not in geometry math.

---

## 3. `images/templates.md` & `images/prompts.md` — how Brilliant fills compositions with imagery professionally

This is a genuine craft layer, not a thin wrapper:

- **`images/prompts.md`** mandates a 5-component prompt structure — **Subject + Medium/Style + Composition + Lighting + Quality** — written as *natural-language paragraphs, not keywords*, with a BAD/GOOD example (`"coffee cup, minimalist, white"` → `"A minimalist product photo of a matte black ceramic coffee mug on light oak, shot from 45 degrees with soft diffused natural light, shallow depth of field, editorial photography style"`). It has a decision table for **when NOT to generate** (icons → `svg(icon:...)`; abstract geometric → build with shapes; text-in-image → unreliable, overlay a blueprint text element).
- **`images/templates.md`** ships ready prompt skeletons per use case — Hero/banner (16:9-21:9, 2-4K), Product shot, Portrait/avatar (Rembrandt lighting, catch light), Food (editorial), Texture/background, Illustration — each demonstrating the "subject, setting, light, lens, grade" shape so the agent only swaps the subject.
- **`images/integration.md`** gives the *placement* discipline: a parameter table mapping scenario → imageSize/aspectRatio (avatar 1:1/1K, hero 16:9/2K, etc.), the **mandatory dark-overlay-for-text-readability** pattern (`f[(img(hero.png)),(f2,solid($neutral.intense,o($visibility.mid)))] clip`), **parallel generation** of all images in one turn, reference-image style consistency, and *"A 1:1 image stretched to 16:9 looks bad — match aspectRatio to the frame."*
- **`svg/prompts.md` + `svg/integration.md`**: a parallel discipline for vector — Arrow rewards structure/color-count/"no text" over atmosphere; `prompt` (what) vs `instructions` (how, sticky across batch); token-sync the generated SVG fills to `$color.*` so icons re-tint with the DS; batch `n:2-4` for cheap parallel takes.

So Brilliant doesn't just *have* image generation — it has a **playbook for using it like an art director**: right model for the job, right prompt structure, right aspect ratio, mandatory readability overlays, and token re-tinting for brand coherence. That is a direct, repeatable path to compositions that *look filled and professional* instead of sparse.

---

## 4. What's entirely absent from a minimal text+shape vector engine — and how much of the "professional look" gap it explains

### Lumen's actual paint surface (evidence)
Our Lumen `effects` SKILL (`apps/agent_runtime/knowledge_docs/skills/effects/SKILL.md`) exposes **only three** effect families:
1. **Drop shadows** — single `shadow(...)` token (canonical + CSS positional forms).
2. **Extended strokes** — dash/cap/join/align.
3. **Gradients** — `linear(...)`/`radial(...)`.

And it explicitly forbids what Brilliant treats as table stakes:
> *"`rd(...)` is a single uniform radius. `rd(12,12,0,0)` … is not supported (→ `LUMD0230`) and the renderer squares non-uniform corners anyway."* — `effects/SKILL.md`

The Lumen DSL grammar (`knowledge/lumen-dsl/grammar.md`) lists element kinds `line, text, image, vector, svg, instance` — and paint is limited to solid/gradient + one shadow. A repo-wide grep for `metaball|holographic|duotone|halftone|webgl|shader|sparkline` across the entire Lumen `agent_runtime` returns **zero hits**. There is no inner shadow, no inner glow, no outer glow, no backdrop/background blur, no element blur, no shader, no image filter, no color-adjust, no chart recipes.

### Imagery is a stub, not a capability
`knowledge/assets/asset-placement.md` is explicit:
> *"The current Phase A runtime does not own real upload, storage, **provider image generation, vectorization**, or production asset processing. If the user request requires a missing image, the agent should request/select a fixture asset or record an asset gap."*

So Lumen can only reference *pre-registered fixture assets by ID* (`logo image asset(account_logo) …`). There is **no `generate_image`, no `generate_svg`, no `vectorize_image`, no icon library.** Where Brilliant fills a hero with art-directed photography in one parallel tool call, Lumen must leave the region empty or drop a fixture placeholder. *(Inference: a composition that can't fill hero/product/avatar regions with real imagery will read as sparse/wireframe regardless of how good its spacing is.)*

### Capability gap table
| Capability | Brilliant | Lumen | Premium-look impact |
|---|---|---|---|
| Drop shadow | ✅ stackable + composite tokens | ✅ single shadow | Low gap |
| Gradients | ✅ linear/radial/angular | ✅ linear/radial | Low gap |
| Inner shadow / inner glow | ✅ z-order fills | ❌ | **High** (depth, clay, neon, pressed states) |
| Outer glow | ✅ | ❌ | **High** (neon, accent glow borders) |
| Background/backdrop blur | ✅ `BackdropFilter` | ❌ | **High** (all glass/frosted UI) |
| Per-corner radius | ✅ `rd(tl,tr,bl,br)` | ❌ `LUMD0230`, squares them | **Med-High** (bar-chart tops, tabs, sheets) |
| Procedural shaders ×6 | ✅ full GLSL + presets | ❌ | **High** (premium hero/badge backdrops) |
| Image filters ×7 + Color Adjust | ✅ GPU + presets | ❌ | **High** (editorial imagery) |
| AI raster image generation | ✅ `generate_image`, 1-4K, parallel | ❌ stub | **Very High** (filling compositions) |
| AI vector / icon generation | ✅ `generate_svg` + `svg(icon:)` | ❌ (svg kind exists, no generation/library) | **High** (icons everywhere in real UI) |
| Chart/data-viz recipes | ✅ bar/line/spark/table/heatmap | ❌ | **Med** (dashboards) |

### How much of the gap this explains
This slice does **not** explain the spacing/density/hierarchy defects directly, nor the max-iterations preflight loop (those are layout-engine + repair-loop slices). But it explains a large fraction of the *"premium feel"* delta in a **complementary** way:

- **Two compounding effects.** (1) *Capability absence:* even a perfectly-laid-out Lumen composition is rendered with flat fills, square-ish corners, one shadow, and empty/placeholder image regions — visually a wireframe-grade render of a good layout. (2) *Knowledge absence:* Brilliant ships 38 docs in just `effects/charts/webgl/svg/images` (and ~91 total vs our ~19), so its agent *knows the recipes* (glass = tint+blur+edge; neon = 3 light layers; clay = dual inner shadows; hero = image+overlay+5xl headline). Lumen's agent has neither the primitives nor the recipes.
- **Inference on magnitude:** Of the "individual components look fine but compositions look worse" symptom, the layout slices likely own the *arrangement/spacing* half; this richness layer likely owns most of the *surface-finish/fill* half. The most visible single contributor is almost certainly **missing imagery + missing inner-shadow/glow/blur**, because those are present on virtually every Brilliant card, hero, and button, and their absence flattens *every* element uniformly — which is exactly the kind of pervasive, hard-to-localize "looks cheaper" signal the audit describes.
- **Cheapness asymmetry matters:** Brilliant's richness is ~1-2 tokens per effect, so its agent applies polish liberally within its iteration budget. Lumen's agent, even if it "wanted" glass or a graded hero, has no token to emit and (per our runs) is burning its entire iteration budget on preflight repair anyway — so it never even reaches the polish phase. *(Inference: the richness gap and the repair-loop failure reinforce each other — no spare iterations to polish, and no primitives to polish with.)*

---

## Key file references
- Brilliant effects recipes: `brilliant/knowledge/effects/{clay,glass,dark-mode,neon}.md`
- Shader/filter system of record: `brilliant/knowledge/reference/{shaders.md,image-filters.md,effects.md}`
- Full GLSL implementations: `brilliant/knowledge/webgl/*.md` (4,004 lines, 18 files; e.g. `metaballs.md` ~230 lines of shader)
- WebGL runtime + blueprint→config mapping: `brilliant/knowledge/webgl/{setup.md,overview.md}`
- Imagery playbook: `brilliant/knowledge/images/{prompts,templates,integration}.md`; vectors: `brilliant/knowledge/svg/{prompts,integration}.md`
- Charts: `brilliant/knowledge/charts/{bar-charts,line-charts,sparklines,tables,misc}.md`
- Icon primitive in DSL: `brilliant/knowledge/reference/components.md:254,269` (`svg(icon:sparkle)`)
- Lumen's limited paint surface: `agents-design-recipes-quality-v0/apps/agent_runtime/knowledge_docs/skills/effects/SKILL.md` (only shadow/stroke/gradient; `LUMD0230` no per-corner radius)
- Lumen imagery is a stub: `…/knowledge_docs/knowledge/assets/asset-placement.md` ("does not own … provider image generation, vectorization")
- Lumen DSL element/paint inventory: `…/knowledge_docs/knowledge/lumen-dsl/grammar.md`
