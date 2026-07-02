# SPEC — Imagery-Quality Fixture + Eval Set for the Lumen Design Agent

> Authored 2026-06-20 via a fan-out (eval-infra + Brilliant criteria + measurable rubric +
> brief matrix → synthesis), grounded in verified repo paths. Answers: *are we testing
> composition / shape / placement / contrast / theme-coherence when the image model is
> used, and can we have a really good fixture set?* `CritiqueCategory` confirmed to have
> **no `imagery` value yet** (closest: `asset_use`, `contrast`, `visual_balance`).

## 1. Goal + the gap

Today Lumen's tests verify the imagery *mechanics* (does `generate_image` place real pixels,
does `fit:cover` + focal crop geometrically, does export meet the DPI floor) and the *image
model itself* (does the provider return a usable hero), but **nothing measures whether the
agent composed a good DESIGN with that imagery.** The 10 existing fixtures in
`apps/agent_runtime/evaluation/fixture_prompts.json` are entirely layout/typography/brand
oriented — none mention a photo, a hero, a scrim, or `generate_image`. So we have never
asked: when the agent reaches for an image, did it *decide correctly that an image was
warranted*, *frame and crop it*, *place it*, *keep text legible over it*, and *keep it
on-brand* — would a designer ship it? This set closes that gap: a balanced brief matrix
(~37% of correct answers are "no image"), a 0–3 rubric split into deterministic scene/asset
gates and LLM/human-judge ceiling checks, a runner driving the existing
`python -m lumen_deepagent.cli ... --mode quality-loop`, and a versioned fixture store that
compares design quality across build steps while holding image-model nondeterminism constant.

---

## 2. The rubric

Every surface that places (or correctly declines) an image is scored on **10 axes**, each
**0–3**: **0** Broken (reviewer redoes) · **1** Wrong but salvageable · **2** Acceptable
(ships with minor tweaks) · **3** Deliberate and correct.

Two check families:
- **DET (deterministic gates)** — computed from scene graph + asset record + rendered PNG
  **without taste**. A DET failure *caps* the dimension at **1** (a stretched image with a
  perfect vibe is still a fail).
- **JUDGE (ceiling)** — an LLM (or human) looking at the PNG against the brief; sets the
  score *within* what the gates allow.

DET checks read fields confirmed to exist: `fit` (cover/contain/crop), `focal_point {x,y}`,
asset `width/height` vs rendered `width/height` (DPI), `source_kind`
(`generated` / `stub-image-v0` → placeholder), the scrim-rect DSL + `$opacity.scrim = 0.56`,
and diagnostics (`LUME0211` placeholder, `LUME0213` DPI floor, `LUMA0310` aspect tolerance,
`LUMA0315` crop-needs-focal). Geometry recomputed with `focalCropGeometry(...)` in
`apps/editor/src/engine/canvaskit/drawDescriptors.ts`; canonical field/token reference is
`apps/api/tests/fixtures/image_baseline/manifest.json`.

### (a) The 5 user-named dimensions

| # | Dimension | Pass (≥2) | Common failures | DET (gate) | JUDGE (ceiling) |
|---|-----------|-----------|-----------------|------------|------------------|
| 1 | **Composition** | One focal element owns the surface; image reinforces reading order; deliberate negative space; clean area for overlaid text. | Two heroes (full-bleed image *and* display headline fight); image swamps the message; orphaned whitespace from image sizing. | Dominance ratio (largest ÷ second ≥ ~1.5× or full-bleed); large-image-role count **= 1**; text bbox doesn't collide with non-scrimmed busy regions. | Does the hierarchy actually *read*; intentional whitespace; image focal mass points toward the headline. |
| 2 | **Shape / aspect-fit** | Fills frame, no stretch, no dead bands; frame aspect suits surface; focal keeps subject in-frame. | Non-uniform stretch (sx≠sy distorts faces); letterbox/pillarbox dead bands; default focal crops subject off. | **High.** `naturalAspectRatio` vs frame: sx≠sy → stretch fail; `contain`+mismatch → dead-band fail; `focalCropGeometry` out-of-bounds = 0; `LUMA0310/0315`. | Only "did focal land on the *semantically right* subject." |
| 3 | **Placement** | Bound to a real target with a coherent role (full-bleed / band / accent); grid/edge-snapped; one hero; alt set; clipped/rounded if intended. | Floating at hand-tuned x/y; wrong role / over-placement; placeholder shipped. | **High.** `source_kind == generated`/library (NOT stub), status `ready`, no `LUME0211`; edge-flush or grid-snapped; hero count = 1; `clip(true)`/`rd()` when intended; alt non-empty. | Is the chosen *role* the right call for this brief. |
| 4 | **Contrast / legibility-over-image** | Text over image sits on its own surface OR has a scrim giving ≥ ~4.5:1 (body) / ~3:1 (display). | No scrim on a busy photo; scrim opacity too low; scrim smaller/offset than text bbox. | **High (×1.2).** Per overlapping text node: scrim exists, `scrim.bbox ⊇ text.bbox`, opacity ≥ `$opacity.scrim` floor; per-tile WCAG sampled from the PNG. Text on own surface = exempt. | Edge calls where the region under text is genuinely flat/dark. |
| 5 | **Theme-coherence (on-brand)** | Subject/style/palette read on-brief + on-brand; image earns its place. | Stock cliché (handshake, lightbulb, blue-brain "AI", hoodie-hacker); palette clash; off-brand illustration palette. | **Partial.** Image dominant colors → ΔE (Lab) to brand palette/`brand_notes`; provenance (justified vs default fill); OCR → fail if in-image text. | **High.** Subject relevance, style-on-brand, cliché test — the *least* deterministic; most worth the LLM judge. |

### (b) The extra axes

| # | Axis | Pass (≥2) | DET | JUDGE |
|---|------|-----------|-----|-------|
| 6 | **Relevance / "is an image warranted"** (DECIDE guardrail — most emphasized) | Correct photo/icon/none per the decide table; can name what the image *does*; no gratuitous imagery. | **Partial.** Generated placement on a brief whose expected decision is NONE/ICON = hard mismatch count; right *mechanism* (photo→generate, icon→library, data→layout). | Does the imagery serve *this* message. |
| 7 | **Resolution / DPI** | Sufficient for rendered size; meets DPI floor; no upscale blur. | **High.** asset vs rendered dims → effective DPI ≥ floor; `LUME0213` absent. | "Looks soft" at the margin. |
| 8 | **Garbled in-image text** | No rendered text/letters/logos/watermarks in the image. | **High (OCR).** OCR asset → fail on glyphs. | Confirm ambiguous OCR (texture vs lettering). |
| 9 | **On-brand style** | (Folded into #5.) | (#5) | (#5) |
| 10 | **Placeholder-vs-real** | A real credible pixel image (not gray placeholder/solid stub). | **High.** `source_kind != stub-image-v0`, status `ready`, no `LUME0211`. | "Credible vs filler" when DET passes. |

**Stability axis (multi-iteration runs): cache / no-churn** — the same hero re-used across
iterations (no re-generate/re-pay/shift). DET: placed asset id stable across
`iterations/*/dsl.lumen`.

### Scoring & accept threshold

Per-dimension 0–3. A hard DET gate failure on **#2, #3, #4** caps that dimension at 1.

| Dim | Weight | DET | JUDGE |
|---|---|---|---|
| 1 Composition | 1.0 | partial | high |
| 2 Aspect-fit | 1.0 | **high** | low |
| 3 Placement | 1.0 | **high** | partial |
| 4 Legibility | **1.2** | **high** | low |
| 5 Coherence | 1.0 | partial | **high** |
| 6 Relevance | 1.0 | partial | high |
| 7 DPI | 0.8 | **high** | low |
| 8 Garbled text | 0.8 | **high (OCR)** | low |
| 10 Placeholder | 1.0 | **high** | low |

**Accept ("a designer would ship it with minor tweaks, not redo it") iff all:**
1. **No hard DET gate failure** on #2/#3/#4 (single failure = redo).
2. **Every scored dimension ≥ 2.**
3. **Weighted mean ≥ 2.3 / 3** (≈77%) — headroom on the JUDGE-heavy #1/#5/#6.

**Tiers:** *Ship* (gates pass, all ≥2, mean ≥2.3) · *Tweak* (gates pass, all ≥2, mean
2.0–2.3) · *Redo* (any hard gate fails OR any dim ≤1). **NONE-correct briefs** score
pass/fail on **#6 alone** (a gratuitous hero = redo).

**Cheapest-first automation:** (1) placeholder/real + hero-count + scrim-coverage
[scene-graph]; (2) aspect-fit/stretch/dead-band + focal bounds [geometry]; (3) per-tile WCAG
on the PNG; (4) palette ΔE + OCR; (5) one LLM-judge call for the residue. Steps 1–4 cover
~3.5 of 5 named dimensions deterministically.

---

## 3. The brief matrix

16 briefs: **PHOTO ×6, ICON ×4, NONE ×6** (~37% NONE is intentional — the rate a good
enterprise agent should *decline* imagery). Stored in `fixture_prompts.json` shape
`{id, artifact, prompt}` + an eval sidecar `{expected_decision, role, risks}`.

### Section 1 — Worked example: "AI-Native GTM Conference, SF" (one theme, three correct answers)

| ID | Surface | Brief (abbrev.) | Decision | Role | Top-2 risks |
|----|---------|-----------------|:--------:|------|-------------|
| **GTM-01** | Event poster 1080×1920 | RevMotion '26 — the GTM conference for AI-native go-to-market. One weekend in SF, Sep 12–13, SoMa. Get your pass. | **PHOTO** | full-bleed hero + bottom-up scrim | Headline illegible where scrim thins over busy skyline; generic Golden-Gate postcard cliché. |
| **GTM-02** | Social square 1080×1080 | AI-native GTM, live in SF. RevMotion '26 · Sep 12–13. Save your seat. | **NONE** *(opt. small icon)* | type-led | Gratuitous photo shrinks date/CTA at thumbnail; image competes with headline. |
| **GTM-03** | Deck title 1920×1080 | RevMotion '26 — Rebuilding GTM for the AI-native era. Opening slide: name, tagline, date+city, logo. | **PHOTO** *(band)* | image band + clean type zone | Full-bleed image swallows the title; square gen stretched into 16:9 band. |

### Section 2 — PHOTO-correct

| ID | Surface | Brief (abbrev.) | Role | Top-2 risks |
|----|---------|-----------------|------|-------------|
| **PH-01** | LinkedIn wide 1200×627 | Meet the team behind Atlas Health's claims-automation rollout; cut adjudication 60%. | image band + type panel | diverse-people-at-laptop cliché; faces cropped by 1.9:1. |
| **PH-02** | Portrait card 1080×1350 | "Lumen replaced three vendors and a week of design ops." — Priya N., VP Brand. | portrait frame + pulled quote | portrait stretched to 4:5; quote illegible if overlaid. |
| **PH-03** | Product card 1080×1080 | New: Lumen Brand Kits. Lock fonts, colors, logo. | product-in-context on plate | low-fidelity UI shot looks fake; product competes with headline. |
| **PH-04** | Event poster 1080×1350 | Founders Dinner — 30 climate-tech founders, rooftop Austin, Thu 7pm, by invitation. | full-bleed hero + scrim | illegible RSVP over dusk image; cliché rooftop-party stock. |

### Section 3 — ICON / flat-illustration-correct

| ID | Surface | Brief (abbrev.) | Role | Top-2 risks |
|----|---------|-----------------|------|-------------|
| **IC-01** | A4 one-pager 2480×3508 | How Lumen works — 3 steps. Enablement leave-behind. | icon row (3) above steps | mismatched icon set; photo wrongly chosen. |
| **IC-02** | Deck slide 1920×1080 | Four pillars: Ingest · Reason · Compose · Govern. | icon row (4-up) | icons fight headline; gratuitous bg photo. |
| **IC-03** | Social square 1080×1080 | Feature drop: real-time collaboration. Flat-illustration announce. | spot illustration + type | off-brand illustration palette; too detailed, steals focal point. |
| **IC-04** | LinkedIn wide 1200×627 | Security you can audit. SOC 2 Type II, SSO, RBAC. | icon row (4 marks) on plate | hoodie-hacker/padlock cliché; icon row cramped at 627px. |

### Section 4 — NONE-correct (DECIDE guardrail)

| ID | Surface | Brief (abbrev.) | Role | Top-2 risks |
|----|---------|-----------------|------|-------------|
| **NO-01** | A4 one-pager 2480×3508 | Q3 Business Review — Northwind. Revenue, NRR, pipeline, 3 risks. | type + table + rules | gratuitous hero eats the summary; stock "business meeting" adds zero info. |
| **NO-02** | Deck data slide 1920×1080 | Pipeline coverage by stage — 4.2x on $18M. Bar chart + takeaway. | chart-led | bg photo kills data legibility; decorative icon clutter. |
| **NO-03** | Social square 1080×1080 | Hiring: Staff Design Engineer. Remote US. Apply. | oversized type + color field | generic office stock; weak title-vs-CTA hierarchy. |
| **NO-04** | A4 one-pager 2480×3508 | Pricing & Packaging — Starter/Growth/Enterprise matrix + FAQ. | comparison table | decorative header image pushes table below fold; weak tier differentiation. |
| **NO-05** | Deck slide 1920×1080 | One number that matters: 60% faster claims adjudication. | giant numeral | gratuitous bg photo dilutes the stat; stat undersized. |

**Coverage:** composition (GTM-02/03, PH-03, IC-03, NO-05) · aspect-fit (PH-01/02/04, GTM-03
across 1.9:1 / 4:5 / 16:9) · placement (GTM-03 band-vs-bleed, IC-01/02 icon row, NO-01/04
no-banner) · legibility (GTM-01, PH-04, NO-02) · coherence (IC-01 set-consistency, IC-03
palette, NO-03 lockup) · DECIDE guardrail (NO-01…05 + GTM-02) · same-event-different-answer
(GTM-01 photo / GTM-02 none / GTM-03 band).

---

## 4. The eval mechanism

(Real CLI per recon — path is `lumen_deepagent/cli.py`.)

### Step A — Run the agent (provider quality loop)

```bash
cd /Users/aryankeshri/conductor/workspaces/clue-design/havana
export LUMEN_AGENT_MODEL="anthropic:claude-opus-4-6"           # vision-capable (config.py:22)
export LUMEN_AGENT_MAX_ITERATIONS=5
export LUMEN_AGENT_PREVIEW_FORMAT=svg                          # critic ALWAYS gets a PNG (loop.py:610-612)
export LUMEN_AGENT_TRACE_DIR="$PWD/.lumen-runs"
export LUMEN_AGENT_ASSET_STORE="$PWD/.lumen-runs/asset-store"  # REQUIRED for generate_image briefs
python -m lumen_deepagent.cli "<one brief prompt>" --mode quality-loop
```

`cli.py:34-36` → `create_provider_quality_loop` (`providers.py:151-164`) → `LumenQualityLoop`.
The loop forces `export_preview_bundle(critic_format="png")` (`loop.py:610-612`) so quality is
**always judged on pixels**. Honor the imagery gotcha: `upsert_asset` + preflight before
export; credits-blocked offline runs fall back to the deterministic placeholder
(`tools.py:530-532`) — which the placeholder-vs-real DET gate (#10) catches.

### Step B — Capture `.lumen-runs/<run_id>/`

Scorer reads: `final.json` (`tools.py:1934-1962`); `iterations/NNN/dsl.lumen` (placement,
`fit`, `focal_point`, scrim, `clip`/`rd`, alt); `iterations/NNN/preview.png` (the judged PNG);
`critique.json`, `preflight.json`, `export.json` (diagnostics + categories).

### Step C — Deterministic checks (new `lumen_deepagent/imagery_checks.py`)

Reads final `dsl.lumen` + scene summary + asset record + `preview.png` → per-dimension DET
sub-scores + hard-gate booleans: #10/#3 placeholder/real; #2 aspect-fit (stretch/dead-band,
`focalCropGeometry` bounds, `LUMA0310/0315`); #4 legibility (scrim exists/covers/opacity +
per-tile WCAG); #7 DPI (`LUME0213`); #8 OCR; #5 palette ΔE / #6 provenance (decision
mismatch); #1 dominance + hero count + bbox collision.

### Step D — LLM-judge (new `lumen_deepagent/imagery_judge.py`)

One vision call (PNG + brief + §2 rubric) → 0–3 for the JUDGE residue (composition-reads,
role-choice, theme/cliché/relevance) + ambiguous-DET confirmation. Reuses the reviewer image
seam `preview_image_blocks` / `image_blocks_from_context` (`providers.py:217-254`) via
`get_latest_preview_for_critique` (`tools.py:1322-1325`). Final score = `min(DET_cap, JUDGE)`.

### Step E — Optional human spot-check

PHOTO + *Tweak*-tier briefs: a human confirms the cliché/on-brand JUDGE calls; disagreements
become judge-calibration examples.

### Integration with existing infra

- **`fixture_prompts.json`** — add the 16 briefs; add a coverage test mirroring
  `test_artboard_fixture_prompts_cover_required_surfaces` (`tests/...:967-994`).
- **New runner** `evaluation/run_imagery_evals.py` — loops ids → Step-A CLI → Steps C–D →
  writes §5 records. (The only genuinely new harness piece.)
- **`eval_traces.py`** — add an `imagery` value to `CritiqueCategory` (`schemas.py:14-30`,
  currently absent) + `VisualIssue.category` → auto-aggregates in `summarize_trace_dir`
  (`eval_traces.py:51-59`). `python -m lumen_deepagent.eval_traces --trace-root .lumen-runs`.
- **Step 9 is the in-loop version of this same rubric** — add the imagery clause to
  `VISUAL_REVIEWER_SYSTEM_PROMPT` (extend clause H `prompts.py:212-220`), gate on
  `critique.accepted` (`loop.py:697-708`), route a failing axis to a non-geometry repair
  (regenerate/recrop/add-scrim/replace/remove), mirroring `RECOMPOSE_CATEGORIES`
  (`loop.py:36`). This offline set is the held-out check that the in-loop critic works.

---

## 5. The fixture format + regression

Per brief × run, under
`apps/agent_runtime/evaluation/imagery_fixtures/<brief_id>/<capture_tag>/`:

```
brief.json            # {id, artifact, prompt, expected_decision, role, risks}
dsl.lumen             # the agent's authored DSL (final iteration) — round-trippable
render.png            # the rendered PNG the judge scored
scores.json           # {per_dimension:{1..10:{det, judge, final, gate_failed}}, weighted_mean, accept, tier, accept_reasons}
asset_provenance.json # {asset_id, source_kind, status, width, height, rendered_w/h, effective_dpi, brand_notes, prompt_used, seed, content_hash, cached}
run_meta.json         # {run_id, model, max_iterations, git_sha, captured_at}
```

**Baseline + cross-step comparison:** the first tag (`baseline-pre-step9`) is the regression
baseline; each later step re-runs the set and writes a new tag; a diff script compares
`scores.json` across tags (per-dimension + weighted-mean deltas, accept-rate, tier
transitions). **Contract: a step must not regress any brief Ship→Tweak/Redo, and should move
≥1 named dimension up without dropping another.** NONE briefs track the gratuitous-hero rate
(Step 9 should drive it to zero).

**Holding nondeterminism constant (judge the design, not the pixels):** seed + cache the hero
(`content_hash` in `LUMEN_AGENT_ASSET_STORE`; re-runs of the same brief re-use the same hero —
also exercises the cache/no-churn axis); the rubric scores framing/crop/placement/scrim/
relevance on a held-constant hero, never diffs PNG bytes; the offline placeholder is a valid
stable baseline (gate #10 fails it for *acceptance* but placement/scrim/aspect/decision DET
still regression-track) — swap in real cached heroes per brief when credits return, no harness
change.

---

## 6. Phased build plan

- **Phase 0 — Brief set + sidecar + coverage test (no runner).** Add the 16 briefs to
  `fixture_prompts.json`; `imagery_fixtures/briefs.json` with `{expected_decision, role,
  risks}`; a coverage test. *Done when* the 16 ids + imagery contract assert green.
- **Phase 1 — Deterministic checks.** `imagery_checks.py` covering #2/#3/#4/#7/#8/#10 +
  partial #1/#5/#6, reusing `focalCropGeometry` semantics + the `image_baseline/manifest.json`
  reference. *Done when* DET sub-scores + hard-gates compute with zero taste calls (~3.5 of 5
  named dimensions).
- **Phase 2 — LLM-judge harness.** `imagery_judge.py` (one vision call) + the runner
  `run_imagery_evals.py`. *Done when* it produces a full `scores.json` + capture for all 16
  briefs and prints an accept/tier summary.
- **Phase 3 — Aggregation + baseline.** Add `imagery` to `CritiqueCategory`; capture the
  `baseline-pre-step9` tag; add the cross-tag diff script.

**Already coming (wire in, don't rebuild):** Step 9 in-loop imagery critic (same rubric);
Step 10 goldens (promote each brief's best accepted capture).

**Definition of done (every brief):** "a designer would ship it with minor tweaks" — no hard
DET gate failure on aspect-fit/placement/legibility; every scored dimension ≥ 2; weighted mean
≥ 2.3/3; NONE briefs place no gratuitous imagery. A step "improves quality" only if it raises
the accept rate (or a per-dimension mean) on the held-constant cached-hero set **without
regressing any brief from Ship to Tweak/Redo.**

---

**New files to create:** `evaluation/imagery_fixtures/briefs.json`,
`lumen_deepagent/imagery_checks.py`, `lumen_deepagent/imagery_judge.py`,
`evaluation/run_imagery_evals.py`.
