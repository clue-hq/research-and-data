# R7 — Our Lumen Skills (SKILL.md) Audit

**Slice:** Lumen agent SKILL.md instructions (create-design, repair-design, visual-review, brand-and-tokens, effects, tools) vs Brilliant's authoring instructions.
**Date:** 2026-06-17
**Files read (in full):**
- `apps/agent_runtime/knowledge_docs/skills/create-design/SKILL.md`
- `apps/agent_runtime/knowledge_docs/skills/repair-design/SKILL.md`
- `apps/agent_runtime/knowledge_docs/skills/visual-review/SKILL.md`
- `apps/agent_runtime/knowledge_docs/skills/brand-and-tokens/SKILL.md`
- `apps/agent_runtime/knowledge_docs/skills/effects/SKILL.md`
- `apps/agent_runtime/knowledge_docs/skills/tools/SKILL.md`
- `apps/agent_runtime/knowledge_docs/AGENT.md` (orchestration spec the skills hang off)
- `apps/agent_runtime/knowledge_docs/knowledge/design/layout-recipes.md`
- `apps/agent_runtime/knowledge_docs/knowledge/design/typography-and-composition.md`
- `apps/agent_runtime/knowledge_docs/knowledge/loop/authoring-and-repair.md`
- `apps/agent_runtime/knowledge_docs/knowledge/loop/layout-cluster-repair.md`
- Brilliant contrast: `brilliant/skills/feedback/SKILL.md`, `brilliant/all-agents.md`, `brilliant/knowledge/design/foundations.md`, `brilliant/knowledge/design/blocks/layout.md`, `brilliant/v3-design-spec.md`

---

## TL;DR (headline finding)

The single most important structural fact for this audit: **Brilliant's `skills/` folder contains exactly ONE skill — `feedback` — and it is about filing GitHub bug reports. It has NOTHING to do with creating designs.** Brilliant's *design* intelligence lives entirely in `all-agents.md` + `knowledge/design/foundations.md` + ~91 knowledge docs. So the literal comparison "our create-design SKILL vs Brilliant's feedback SKILL" is a category error — and that mismatch *is* the finding: **we encoded our composition intelligence as terse procedural skills; Brilliant encoded it as deep, opinionated design judgment in knowledge.**

When you compare the actual analogs — our `create-design` SKILL vs Brilliant's `foundations.md` — our instructions are **mechanically correct but aesthetically empty**. They tell the agent how to make DSL *compile and not overflow*; they never tell it what *good* looks like. Brilliant's tell the agent what good looks like (focal hierarchy, 60–70% whitespace, scale contrast, "avoid the AI clichés") and assume compilation is a solved background concern.

Layered on top: our skills make the agent **diagnostic-driven, not vision-driven**, and the repair skill has structural properties that explain the `max_iterations_reached` deadlock across all 5 runs. Detail below.

---

## 1. What each of our skills instructs, step by step

### 1.1 `create-design` (the from-scratch procedure)

The literal procedure the SKILL prescribes, in order:

**Before you write** (SKILL lines 12–28):
1. `load_knowledge` — always grammar + artboard-frame-authoring + layout-recipes; add brand/effects/text conditionally.
2. "Pin the surface" — match the requested artifact exactly (`page story size(1080,1920,px)`, `preset(a4,portrait)`), normalize to canonical `pt` bounds.
3. "Decide branded vs neutral" — `$tokens` if a Brand Kit, else raw hex/`font(...)`.

**How to compose** (lines 30–48):
- Structure with auto-layout (`al(v,...)` / `al(h,...)`), not hand coordinates.
- "One clear message, one CTA, generous margins."
- Text rules: `hug`, `wrap_text(true)`, `max_lines(...)`, headline `lh 1.05–1.15`, body `1.3–1.45`.
- Backgrounds on the container `fill(...)`, not a loose rect.
- Mark ABM `slot(...)` on every personalizable element; add `sample`/`worst_case`.

**Size content to the box** (lines 50–58) — the longest, most emphatic section: a whole block warning that dense cards overflow (`LUMV0903`/`LUMV0810`) and to make cards taller.

**Skeleton** (lines 61–70): one canned LinkedIn-square example.

**Finish / Self-check** (lines 72–90): "Return DSL only"; a checklist of *mechanical* correctness (IDs stable, two-space indent, canonical pt, no loose bg rect, slots semantic, tokens used, no invented properties).

**Step-by-step procedure for a new design, as the skill actually defines it:** load knowledge → pick page surface → pick branded/neutral → write one auto-layout DSL block following the skeleton → run the mechanical self-check → hand off to compiler. **There is no design-planning step** (no "decide the focal point," "establish a spacing scale," "choose 3–6 colors with roles," "60–70% whitespace"). It goes straight from "pin the surface" to "emit DSL."

### 1.2 `repair-design`

Procedure: a repair changes "the smallest thing that fixes the diagnostic and nothing else" (line 8).
- **The one rule that matters most** (lines 12–20): never re-emit a `page …` line or existing node id (raises `LUMA0200`/duplicate-id and can wipe the scene).
- **Choose the smallest actuator, in order** (lines 22–50): (1) modify line `#id prop(...)`; (2) layout-cluster repair (only for bounds/containment/oversized-bg/scale-mismatch); (3) structural directive (`delete`/`parent`/`clone`/`replace`/`ungroup`); (4) checked `apply_structured_edit` with strict `scope`; (5) continuation DSL for additions. Whole-scene re-author is "last resort."
- **Repair by diagnostic kind** (lines 53–86): compile `LUMD…` → fix the failing token; layout/fit `LUMV0903/0810/0904` → enlarge box / raise `max_lines` / drop a font point / make container taller / relax slot overflow policy; bounds/containment `LUMV09xx` → `layout_cluster`; brand `LUMB…` → swap raw value for `$token`; visual critique → apply named repair to named target only.
- **Preserve the best draft** (lines 95–100): never let a repair destroy a clean scene; risky changes go through scoped `apply_structured_edit`.

### 1.3 `visual-review`

- Judge the render "as a user-facing artifact, not a compiler output" (line 8).
- **Inputs** (lines 12–16): request, knowledge, scene summary, diagnostics, the SVG text or PNG image, brand summary. "Inspect the actual rendered pixels (PNG) or geometry (SVG) — never approve without looking." **So yes, it is nominally multimodal — but only conditionally (PNG *or* SVG text).**
- **Accept only when** (lines 18–27): matches type+dimensions, communicates message, clear hierarchy, "enough spacing and coherent alignment," no clipping/overflow, consistent brand tokens, semantic slots, "reasonable for a human to approve."
- **Common product failures to reject** (lines 30–40): a list dominated by *defects* (text outside artboard, oversized text, collisions, clipped headings, unclear hierarchy, dimension mismatch, brand-governance violations).
- **Issue categories** (lines 42–46): 14 enums incl. `hierarchy`, `spacing`, `alignment`, `visual_balance`.
- **Output**: a `VisualCritique` JSON (`accepted`, `summary`, `issues[severity,category,target,message,suggested_repair]`, `repair_instruction`).
- **Review style** (lines 68–74): "be specific and target-bound… name the node/page/slot… Never say 'make it better.' Prefer repairs that change one named element over anything that implies re-authoring."

### 1.4 `brand-and-tokens`

Token taxonomy table (`surface.*`, `text.*`, `type.*`, `border.*`, `space.*`, `radius.*`, `opacity.*`, `logo.*`); branded → use `$tokens`, never guessed primitives; modes (theme/density/accessibility/medium) resolved by preflight; logo surface rules (`LUMB0807`); a `LUMB` repair table (`LUMB0804/0805/0806/0807/0811/0813–815`); "brand-fit as a quality gate."

### 1.5 `effects`

Pure grammar reference: shadows (canonical color-first + CSS positional, `LUMD0257`), extended strokes (`w/dash/cap/join/align`, `LUMD0256`), gradients (`linear`/`radial`/`stop`, `LUMD0219`), and "per-corner radius is not supported" (`LUMD0230`). One taste sentence ("keep them tasteful and tokenized"); the rest is parser grammar.

### 1.6 `tools`

Function catalog: `load_knowledge`, `compile_dsl_block` (mutates, guards `LUMA0200`), `apply_operations`/`apply_structured_edit` (the precise repair actuator with strict `scope`), `preflight_design`, `export_preview_bundle`/`export_preview`/`get_latest_preview_for_critique`, `submit_visual_critique`, `recommend_edit_surface`, `create_repair_request`, scene-inspection reads, `generate_qr`, `record_gap`, `finalize_run`. Ends with the loop order map.

---

## 2. create-design: does it plan layout/grid first? Does it enforce spacing discipline?

**No layout/grid planning. No real whitespace discipline.** Evidence:

- The "Before you write" steps are: load knowledge, **pin the surface**, decide branded-vs-neutral. The very next section is "How to compose," which immediately starts emitting DSL conventions. **There is no intermediate "plan the composition" step** — no instruction to identify the focal element, establish a visual hierarchy, sketch regions, or define a spacing scale before writing nodes. The agent is told *what artifact size* but not *what arrangement*.
- There is **no grid/columns concept anywhere** in create-design or layout-recipes. The closest is "Structure with auto-layout … whenever spacing should be systematic" (create-design line 32) and `g(28)`/`pad(72)` magic numbers in the skeleton. There is no spacing *scale* (no 4/8pt rhythm, no "use one gap token consistently"); the skeleton just hardcodes `g(28)`, `pad(72)`, `g(18)`, `pad(36)`, `g(20)`, `pad(54,48)` — different ad-hoc numbers per recipe, which is precisely the "grid-like sameness / inconsistent rhythm" Brilliant warns against.
- "Generous margins" and "Keep text off the edges" (line 35) are the *entire* whitespace doctrine. There is **no whitespace *target*** (contrast: Brilliant's foundations.md line 36–37 — "aim for 60-70% white space, then ask what to remove"). Our skill optimizes against the *failure* (text touching edges) but gives no positive target for breathing room.
- The dominant emphasis of the whole skill — the section explicitly flagged "this prevents the common failure" (lines 50–58) — is about **fitting text into boxes to avoid `LUMV0903`/`LUMV0810`**, not about composition quality. The skill's center of gravity is overflow avoidance, not design.

**Inference:** Because the skill jumps straight to DSL emission with no composition plan and no whitespace target, the agent produces "components that look fine" (each node compiles and fits) assembled into a layout that was never deliberately composed — exactly the reported symptom (bad spacing/density/hierarchy at the composition level while individual elements are OK).

---

## 3. visual-review & repair-design: rubric, multimodality, loop exit, infinite-loop risk

### Critique rubric
The rubric (visual-review lines 18–46) is a **defect checklist**, not a quality scale. Acceptance criteria are binary-ish negatives ("no clipping or overflow," "enough spacing"). There is:
- **No scoring / no severity-weighted threshold** — "accept when [list]" with no notion of "8/10 is good enough."
- **No positive aesthetic bar** — nothing about focal dominance, scale contrast, intentional asymmetry, whitespace ratio, "avoid AI clichés." "Clear hierarchy" and "enough spacing" are undefined and unmeasurable, so the reviewer's interpretation is unconstrained.
- It is anchored on the *same* concerns the compiler/preflight already enforce (clipping, overflow, dimensions, brand governance) — i.e. it **largely re-litigates diagnostics** rather than adding a layer of human-taste judgment on top.

### Is it multimodal?
Nominally yes, but **softly**. visual-review line 16: "Inspect the actual rendered pixels (PNG) **or** geometry (SVG)." `tools` says `get_latest_preview_for_critique` "embeds SVG text / PNG base64 so the reviewer sees pixels, not a path." So the reviewer *can* be handed an image — but the instruction permits judging from **SVG text geometry instead of the image**. Judging composition (spacing, density, balance, "does this look good") from SVG source rather than rendered pixels is far weaker, and the skill explicitly allows it. **Inference:** if the reviewer leans on SVG text, it will catch geometric defects (overflow, bounds) but miss exactly the perceptual qualities (density, hierarchy, balance) this audit is about.

### Loop exit condition
From `AGENT.md` §3 (lines 46–59) and `authoring-and-repair.md` lines 22, 70–74:
> "Done = the visual reviewer ACCEPTS." … "Stop only on: acceptance, max iterations, or a deterministic tool failure."

So there are exactly three exits: **(a) reviewer sets `accepted:true`, (b) max iterations, (c) hard tool failure.** Critically, **there is no quality floor / "good enough" / "best-effort accept after N tries" exit, and no convergence detector.** The only graceful success is full acceptance.

### Does the repair procedure risk infinite looping? — YES, and this is the likely deadlock mechanism

All 5 runs died `status=failed`, `stop_reason=max_iterations_reached` ("Maximum Phase A repair iterations reached"), looping on **preflight diagnostics it never clears.** The skills contain several structural contributors:

1. **Surgical-repair dogma + "preserve the best draft" can make some diagnostics unfixable.** `repair-design` line 8 mandates "the smallest thing that fixes the diagnostic and nothing else," and lines 95–100 forbid destructive rewrites. But many composition problems are *not* fixable by a single-node modify — they need re-layout. The skill funnels all such cases into the narrow `layout_cluster` exception, which is hedged with a long prohibition list (`layout-cluster-repair.md` lines 44–53: no page delete, no unrelated edits, no whole-scene regen, no hardcoded root sizes). If the genuinely-correct fix is "re-compose the region," the skill **forbids it** and only permits micro-adjustments — so the same `LUMV09xx` can re-fire after a "successful" small edit. **No-progress loop.**

2. **The `LUMA0200` trap creates a catch-22.** `AGENT.md` invariant #2 + `repair-design` lines 12–20: re-emitting a `page …` line or existing node id is itself a *failure* (`LUMA0200`/duplicate-id) that "wipes the good scene." So the agent is squeezed between "you must fix this diagnostic" and "you must not touch structure." When the only real fix needs structural change, every legal move is a micro-edit that doesn't clear the diagnostic, and every effective move is forbidden. **Inference: this is the engine of the observed deadlock.**

3. **Repair list is non-converging by construction for fit diagnostics.** For `LUMV0903/0810/0904`, repair-design lines 60–67 offer five competing actuators (enlarge box, raise `max_lines`, drop font a point, enlarge container, relax slot overflow). Several of these *trade one diagnostic for another*: enlarging a box can push a sibling out of bounds (new `LUMV09xx`); shrinking font can trip a readability/brand check; relaxing overflow policy can later be re-flagged. With no memory of prior attempts and no "you already tried this" guard in the skill, the agent can **oscillate between two diagnostics indefinitely** until `max_iterations`.

4. **No loop-budget or de-escalation instruction.** Nothing in any skill says "if you've repaired the same diagnostic family N times, stop and re-plan / accept best draft / record a gap." `finalize_run` (tools) supports a `failed` status, but no skill tells the agent *when* to choose it short of the harness's hard iteration cap. So the loop runs to the ceiling every time.

5. **Acceptance is adversarial against the same defect family the agent struggles to clear.** visual-review re-checks overflow/clipping/spacing — the very things that are hard to fix surgically. So even a scene that "looks fine" can be bounced back for a residual `spacing`/`hierarchy` issue with a `suggested_repair` the surgical rules can't fully satisfy. The reviewer and the repair constraints are not co-designed to converge.

---

## 4. Depth & procedural rigor: ours vs Brilliant's

Note: Brilliant's *literal* `feedback` SKILL is a 157-line GitHub-issue-filing assistant (search budget, `gh`/REST fallbacks, opt-in context, draft-and-confirm). It is **rigorous procedurally but is not a design skill** — so the honest comparison is **our `create-design`/`visual-review` vs Brilliant's `all-agents.md` + `design/foundations.md`.**

| Dimension | Ours (create-design + visual-review) | Brilliant (all-agents.md + foundations.md) |
|---|---|---|
| Where design judgment lives | In terse skills, mixed with compiler mechanics | In dedicated knowledge (`foundations.md` = "core judgment for every build") + ~91 docs |
| Planning step before emitting | **None.** "Pin surface" → emit DSL | **Explicit:** "commit to a system first: 3-6 colors with roles, a font with heading and body weights, a spacing rhythm. Then decide the emotion, the focal point (one per section), and the personality." (foundations 14–17) |
| Whitespace doctrine | "Generous margins," "keep text off edges" (no target) | "aim for **60-70% white space**, then ask what to remove." (foundations 37) |
| Hierarchy doctrine | "clear hierarchy" (undefined) | "one dominant region that draws the eye first; secondary regions stay visibly subordinate (smaller, lighter, less contrast). **If you squint and nothing dominates, raise the contrast.**" (foundations 30–34) |
| Composition principles | none beyond "one message, one CTA" | "favor asymmetry and scale contrast over grid-like sameness… information on surfaces over boxing everything in cards. Headlines 4-8 words, subtitles 12-25." (foundations 34–37) |
| Taste guardrails | none | A whole **"Avoid the AI clichés"** section: hero weight `mid/firm` not bold; vary eyebrows ("the tinted pill is the #1 tell"); "skip blue-to-purple gradients, neon-on-dark… If you've seen a combo in three AI designs, drop it." (foundations 39–46) |
| Reusable layout vocabulary | one canned skeleton + a few recipes | `design/blocks/layout.md` gives parametric recipes for Header/Footer/Hero/Accordion/Carousel/Form with exact spacing tokens (`pad($spacing.2xl,$spacing.xl)`, `g($spacing.lg)`), plus `comp`/`inst` to stamp 3+ similar elements instead of hand-coding |
| Spacing system | ad-hoc magic numbers (`g(28)`, `pad(72)`, `g(18)`…) | a generated **tshirt spacing scale** with named stops (`$spacing.md/lg/xl`) and mode-aware density shifts (v3-design-spec 76–139) — every gap references one rhythm |
| Knowledge-loading rigor | AGENT.md §4: "load every row that applies (most tasks match 3–5)" | all-agents.md: **"NEVER start designing… before loading a minimum of 12 knowledge keys"; "Many chats require 20-25 knowledge files."** Hard floor vs soft suggestion. |
| Review/critique | our `visual-review` defect checklist (binary accept) | (Brilliant's quality bar is front-loaded into authoring judgment; it builds it right rather than relying on a back-end reject loop) |

**Bottom line on depth:** Brilliant front-loads *opinionated design judgment* ("what good looks like," with numeric targets and named anti-patterns) into always-loaded foundations and enforces a hard 12-file knowledge floor. Ours front-loads *compiler-survival mechanics* ("what won't overflow / won't fail governance") into the skills and leaves design quality to an undefined "clear hierarchy / enough spacing" gate. Our procedural rigor is real but pointed at the **wrong target** (making DSL valid) — it has high rigor about node-level correctness and near-zero rigor about composition.

---

## 5. Specific weaknesses that produce poor composition or non-convergence

**Poor composition (explains "bad spacing, density, layout, hierarchy"):**

1. **No composition-planning step.** create-design goes "pin surface → emit DSL." No focal-point selection, no region sketch, no hierarchy plan. (Brilliant explicitly does this in foundations 14–17.) → layouts are assembled, not composed.
2. **No whitespace target.** "Generous margins" with no 60–70% figure → the agent fills space because nothing tells it to leave it empty → high density.
3. **No spacing scale / rhythm.** Magic numbers per recipe (`g(28)`/`g(18)`/`g(20)`, `pad(72)`/`pad(36)`/`pad(54,48)`). No instruction that all gaps reference one rhythm → inconsistent, "off" spacing.
4. **No hierarchy mechanics.** "Clear hierarchy" is asserted but never operationalized (no "one dominant region," no scale-contrast rule, no "if you squint…"). → flat, same-weight layouts.
5. **No anti-AI-cliché guidance.** Nothing equivalent to Brilliant's hero-weight/eyebrow/color warnings → the agent produces the generic AI look.
6. **No multi-element/`comp` discipline.** Brilliant mandates `comp`+`inst` for 3+ similar elements; our skills don't mention component stamping at all → repetitive hand-stamped, inconsistent card/row arrays.
7. **Reviewer can grade from SVG text, not pixels** (visual-review 16) → perceptual issues (density, balance) under-detected; the gate that *should* catch bad composition is allowed to skip the render.
8. **One canned skeleton** (the LinkedIn-square block appears verbatim in both create-design and layout-recipes) → strong anchoring toward one stereotyped vertical-stack layout regardless of brief.
9. **Skill center-of-gravity is overflow avoidance**, not aesthetics — the longest, most emphatic create-design section (lines 50–58) is about text fit and `LUMV0903`. The agent's attention is trained on not-overflowing, not on looking good.

**Non-convergence (explains all-5 `max_iterations_reached` on preflight):**

10. **No "good enough" / quality-floor exit.** Only exits are full acceptance, max-iters, or tool crash (AGENT.md §3). Any residual nit loops to the ceiling.
11. **`LUMA0200` catch-22** (invariant #2 + repair-design 12–20): "must fix the diagnostic" vs "must not touch structure / must not re-emit page" → for structurally-rooted diagnostics, every legal move is a no-op micro-edit. **Most likely root cause of the deadlock.**
12. **Competing fit actuators with no anti-oscillation guard** (repair-design 60–67): enlarging one box births a bounds diagnostic on a sibling; the skill has no memory of prior attempts → ping-pong between two `LUMV09xx` codes.
13. **`layout_cluster` is the only escape hatch for layout problems and it's heavily fenced** (layout-cluster-repair 44–53) — and the surgical rules *forbid* the re-composition that some preflight failures genuinely require → unclearable diagnostics.
14. **No loop-budget / de-escalation rule** anywhere — no "after N repairs of the same family, accept best draft or `record_gap`." The harness's hard cap is the only brake.
15. **Reviewer and repair constraints are not co-designed to converge** — the reviewer keeps flagging spacing/hierarchy/overflow that the surgical repair rules can't fully resolve in-place.

---

## 6. Inferences explicitly labeled

- **(Inference)** The combination of #1–#4 (no plan, no whitespace target, no rhythm, no hierarchy mechanics) is sufficient to produce "good components / bad composition" even before any knowledge-coverage gap (19 vs 91 docs) is considered. The skills alone would yield mediocre composition.
- **(Inference)** Weakness #11 (the `LUMA0200` structural catch-22) is the most probable proximate cause of `max_iterations_reached` on preflight specifically — preflight emits geometry/containment diagnostics that often need structural change, which the skills forbid, so the loop cannot clear them.
- **(Inference)** Weakness #7 (SVG-text reviewing allowed) means the visual gate may be *passing* compositions that look bad in pixels while *failing* on residual geometry — consistent with "looks fine per node, bad overall, never converges."

---

## 7. One-line summary for synthesis

Our skills are a rigorous **compiler-survival manual** (validity, overflow, brand-governance, surgical repair) with **no design-composition doctrine** — no planning step, no whitespace/hierarchy/rhythm targets, no anti-cliché taste — while Brilliant front-loads exactly that doctrine into `foundations.md`; and our repair/loop design (surgical-only + `LUMA0200` catch-22 + acceptance-only exit + no anti-oscillation/loop-budget) structurally explains the all-5 `max_iterations_reached` preflight deadlock.
