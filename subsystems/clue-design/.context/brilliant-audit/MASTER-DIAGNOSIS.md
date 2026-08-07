# MASTER DIAGNOSIS — Why Lumen Composes Worse Than Brilliant

**Audience:** the engineer who built Lumen by reverse-engineering Brilliant.
**Evidence base:** 10 reader reports (R1–R10), 4 gap syntheses (S1–S4), the in-repo `Brilliant-Reverse-Engineering-Report.md` and `ABM-Design-Engine-Temporary-Spec.md`, the 5 failed runs in `.lumen-runs/`, and direct citations to `apps/agent_runtime/lumen_deepagent/**` and `brilliant/knowledge/**`.
**Ground truth:** Brilliant's `brilliant/` bundle is byte-identical to the shipped `.claude-prod`; 91 knowledge `.md` docs (99 total `.md`); Lumen ships 26 `.md` (R6/R8 read ~19–20 design/DSL docs). All 5 Lumen runs ended `status="failed"`, `stop_reason="max_iterations_reached"`, `"Maximum Phase A repair iterations reached."`

---

## 1. EXECUTIVE SUMMARY

Four root causes, in priority order:

1. **The repair loop is mathematically non-convergent (kills 100% of runs).** The layout-cluster gate *atomically rejects* the correct whole-page patch (allows only ~20 of ~38 nodes), forbids the exact ops several errors need (`al()`/`wrap()`/`slot:`), and ~5 of ~8 active A4 diagnostics are unfixable in the offered edit surface — so the ~3-cycle budget always exhausts. Pure runtime bug; no model could pass.
2. **Composition is encoded as adjectives, not enforceable numerics, and there is no vetted block catalog.** Lumen has no spacing/type scale, no 60-30-10, no whitespace target, no `blocks/` directory; it improvises every proportion from primitives. This is the single biggest *quality* lever.
3. **The DSL accepts free-form pixels into auto-layout (we DO have a flex solver).** The premise "we hand-place coordinates" is false; the real gap is unquantized input — the agent emitted 16 distinct off-scale `g()` values. Off-rhythm spacing is impossible in Brilliant's grammar.
4. **The loop is effectively blind: feedback is preflight-only and the shipped default emits SVG, not PNG.** No visual critic ever names dead space, mixed alignment, or flat hierarchy, so a clean-compiling draft is still rejected and unrepairable.

---

## 2. THE TWO PROBLEMS, SEPARATED

There are **two independent failures stacked on each other.** Conflating them is the single most expensive mistake you can make next, because fixing one does nothing for the other.

### (a) The convergence/repair-loop failure — *why all 5 runs FAIL*

This is a **runtime/loop defect**, not a design-quality problem. It has nothing to do with knowledge docs or composition taste. The agent never even ships a draft to the user. The mechanism (R8 §1.4, R9 §3, S3 §1, verified against `loop.py`):

- One counted loop, cap 5 (`config.py:23`, `loop.py:171`), effective ~3 Phase-A cycles before the kill, covering compile **and** preflight **and** critic for the whole run.
- Many simultaneous diagnostics (8–28 per run, R9), but feedback is **one target** (`first_diagnostic_target`, `loop.py:443`).
- The repair surface is crippled: any block that isn't a tiny surgical/cluster modify is rejected *before compiling* and burns a turn with **zero scene change** (`loop.py:267-302`).
- The cluster gate is **atomic**: one out-of-cluster `#ref` → `return False` → 0 ops applied → identical diagnostics next cycle (R9 replayed this: 6 of 18 `#refs` failed "NOT in allowed cluster nodes", `loop.py:1386-1387`).
- ~5 of ~8 active A4 codes are structurally unclearable in the offered surface (`LUMV0509`, `LUMV0810`, `LUMV0800`, `LUMB0613/0614`).

**Proof it is separable:** `run_92039` reached the critic with `has_errors==False` (clean compile) and was *still* rejected — for purely compositional reasons. So the loop bug is not the only thing wrong.

### (b) The intrinsic composition-quality gap — *why a finished Lumen draft would still lose*

This is a **knowledge + DSL-grammar + visual-feedback** problem. Even if you fix the loop tomorrow and every run completes, the drafts will look amateur: noisy `13/15/17/22/36` type scales, hand-picked `g(28)`/`pad(56,48,56,48)` gaps, two-line "Book a / Demo" CTAs, ~300pt dead zones, center-ragged subheads inside left-aligned stacks, no eyebrow tier, flat hierarchy. These are *between-element, whole-page* properties that Brilliant pre-decides and Lumen improvises.

**The crisp statement:**
> *Fixing the loop makes runs **finish**. Fixing composition makes finished runs **good**. You need both. Fixing only the loop yields runs that complete and still look amateur — the worst possible demo, because now the user sees the quality gap clearly.*

They **compound** (S4 §3): weak composition → improvised off-scale sizes → bounds/fit diagnostics (`LUMV0801/0903/0810`) → crippled loop can't clear them → `max_iterations_reached`. Better composition reduces the diagnostic load the broken loop chokes on — but the loop has codes (`LUMV0800` A4 rounding, font-embed `LUMB0613/0614`) no design skill can ever clear.

---

## 3. ARCHITECTURAL DIFFERENCE: Brilliant vs Lumen

Brilliant pushes quality **up-front** (heavy knowledge + cloning + components + look-while-building) and converges **by judgment** with an unbounded, gate-free loop. Lumen pushes quality **to the back** (generate, then validate) and tries to *force* convergence through a bounded `compile→preflight→export→critic` chain whose surgical-repair constraints make whole diagnostic classes unclearable.

| Dimension | Brilliant | Lumen (ours) |
|---|---|---|
| **Layout engine** | Bespoke flex constraint solver (`AutoLayoutExtension`, `_computeAndApplyLayout`, hug/fill fallback, `resizeParentToFitChildren`) computing absolute positions from intent (RE-Report §10) | **We also have a flex solver** — `al(v\|h, x(), y(), g(), pad(), grow, wrap)`, hug/fill/`fill:N` (`grammar.md:89-94`; R9 confirms the agent uses it). Single-axis only; no 2-D grid (grids = "Future Scaffold") |
| **DSL input layer** | Tokens only; **bare numeric in `g()`/`pad()`/`rd()`/font-size HALTS the call** (`core.md:46`); off-scale spacing is *unrepresentable* | **Free-form pixels accepted** in those slots; `$space.*` are role names with no values; agent emitted 16 distinct off-scale `g()` values (R9, S1 §2) |
| **Design system** | Generative: seed → 11-stop OKLCH ramp + `tshirt`/`boldness`/`looseness` scales; 22 palettes; `density.compact: shift(-1)` re-resolves the whole scale (RE-Report §8) | Role-name tokens with **no numeric values**; `density` mode declared but inert; `ds(...)` parsed-not-lowered (`LUMD0700`) |
| **Knowledge** | 91 docs; layered (`design/` judgment + 24 `blueprint/` substrate + 7 `blocks/` + 5 charts + 38 effects/webgl/svg/images) | 26 docs; **no `blocks/` dir** (verified); composition = 3 prose files; only hard numbers are line-height ranges + one print-margin range |
| **Blocks/templates** | ~50 pre-proportioned blocks (Hero `pad(80-120…)`, Card `g($spacing.md) pad($spacing.lg)`, image `s(fill,180)`); job = *assemble + tune vetted blocks* | **Zero blocks.** 6 prose recipes (2 with no DSL skeleton); job = *invent every proportion from primitives* |
| **Agent loop** | 1 primary agent ("Build everything yourself"); **no iteration counter, no gate, no `max_iterations`, no `stop_reason`**; "done" = model judges it good | 3 roles (Director + DslAuthor + VisualReviewer); `max_iterations=5` shared budget; binary `critique.accepted` gate; terminal `max_iterations_reached` |
| **Repair model** | Edits a forgiving live canvas with full undo; unconstrained; resumptive cascade-halt | Surgical-only; cluster gate atomic-rejects; `al()`/`wrap()`/`slot:` banned in repair; re-authoring forbidden |
| **Visual feedback** | Pixel-first from message 1; retina screenshot + spacing/type/contrast/alignment/clipping checklist after each block (`objects-syntax.md:35-42`, RE-Report §12.4) | Nominally multimodal but **`preview_format="svg"` default** → no PNG produced (`config.py:24`, `tools.py:816-820`); feedback `kind:"preflight"`; critic gated behind clean preflight, often never runs |
| **Rendering richness** | Inner shadow/glow, backdrop blur, 6 GPU shaders (4,004 GLSL lines), 7 image filters + 17-param Color Adjust, `generate_image`/`generate_svg`/`svg(icon:)`, charts | Single `shadow()`, gradients, **uniform-only radius** (`LUMD0230` squares corners); imagery is a fixture-by-ID stub; grep for `metaball\|shader\|duotone\|webgl\|sparkline` = 0 hits |
| **Knowledge delivery** | Full-doc skill bundle, `get_knowledge` hard-minimum 12 keys before designing | **≤6 snippets × 800 chars ≈ 4.8 KB total** (`tools.py:50-51`); shipped provider path (`providers.py`) loads **no SKILL.md and calls no knowledge loader** |

---

## 4. ROOT-CAUSE DEEP DIVE

### RC-1 — The repair loop cannot converge by construction *(confidence: very high; verified by replay)*

**Evidence.** R9 deterministically replayed the recorded `rejected_source` against the real gate logic (`is_layout_cluster_dsl` / `layout_cluster_allowed_node_ids`, `loop.py:1388-1456`):
- `LAYOUT_CLUSTER_CODES = {LUMV0800, LUMV0801, LUMV0803}` (`loop.py:751`) — any page/parent-bounds error routes the whole repair to `layout_cluster`.
- Allowed set = `descendant_node_ids` + root/parent/bg only — **20 of ~38 nodes** in `run_e2ca`. Error-carrying nodes outside the cluster (`appt_label` with `LUMV0904`, `divider`, `cta_button`, `footer_text`) *must* be touched.
- Atomic validator: first stray ref → `return False` (`loop.py:1386-1387`) → **0 operations apply** → scene unchanged → identical diagnostics recur.
- `UNSUPPORTED_LAYOUT_CLUSTER_MODIFY_CALL_RE` (`loop.py:771`) rejects `al(...)` and `wrap(...)` — but those are the *fix* for overflow. `slot:`/`asset:` refs rejected (`loop.py:1384`) — so `LUMV0509`/`LUMV0810`/`LUMB0613/0614` can never be addressed.
- Self-reinforcing classification: once `layout_cluster`, later `LUMD`/`LUMA` failures keep it `layout_cluster` (`loop.py:775-789`); no de-escalation, no anti-oscillation memory.

**Specific unclearable codes** (R9 §2, R8 §4):
- `LUMV0509` ("no fit-validation fixtures"): fix is `#slot:key sample(...) worst_case(...)`, but `AGENT.md §2` forbids fixtures in DSL, there is **no fixture tool** (`factory.py:37-61`), and the gate rejects `slot:` refs. Unsatisfiable.
- `LUMV0800` (A4 portrait): canonicalizes to 841.89pt → artboard `s(fill,fill)` ceils to 842pt → **permanent ~0.11pt overflow**; the gate *forces* `s(fill,fill)` (`loop.py:1415-1420`), rejecting the value that would avoid it.
- `LUMB0613/0614` (font not embeddable/subsettable): no DSL surface; brand-kit only.
- `LUMV0805`: routed to `external_planner` (`loop.py:799-805`) **which does not exist**.

**Why it produces the symptom.** ~5 of ~8 active A4 codes unfixable + ~3 cycles + single-target feedback + atomic rejection = the error count cannot reach zero. The `for` loop falls through to `StopReason.max_iterations_reached` (`loop.py:636-644`). *A perfect model cannot pass Phase A on these inputs.*

**Compounding iter-1 waste (R9 §1f, retrieval bug):** All three A4 runs burned iteration 1 on hallucinated grammar — `va(center)` → `LUMD0212`, `divider` kind → `LUMD0206` — because the DSL grammar/`text.md` docs (which literally say "There is no `valign`", `text.md:29`) **were not among the 8 retrieved snippets**; the ranker surfaced "Reverse-Engineering Report", "ABM Spec", and "Permanent Memory" instead. *This is a retrieval/ranking bug, not a doc-count gap — the right doc exists in our 26 and wasn't fetched.*

### RC-2 — Composition encoded as adjectives + no block catalog *(confidence: high)*

**Evidence.** Brilliant ships `design/blocks/*` = 7 files, ~50 blocks, with internal spacing/padding/type/color roles pre-decided as token references (R3): Card `g($spacing.md) pad($spacing.lg) rd($radius.md)`; Hero `pad(80-120,$spacing.3xl) g($spacing.lg)` Title 40-56; Bento "cells `fill:N` give asymmetric widths **with no pixel math**". `patterns.md` is self-described as *"Compositions the primitives don't make obvious"* — Brilliant *knows* primitives alone compose badly and ships the fix. Its `foundations.md` adds enforceable numerics: 60-30-10, "aim for 60-70% white space then ask what to remove", anchor 2-3× body, heading 150-200% of body, shadow opacity 0.04-0.10, WCAG 4.5:1/3:1 (with fail example `#10B981`→`#059669`), "one dominant region… if you squint and nothing dominates, raise the contrast", a whole anti-AI-cliché doctrine.

Lumen (R6 §1, R7 §2, verified empty grep for "spacing scale / type scale / 8pt grid / modular scale"): **no blocks dir**; composition guidance is "generous margins", "clear hierarchy", "enough spacing", "use high contrast" — all undefined. The *only* concrete numbers in the whole corpus are line-height ranges (`lh(1.05)`–`lh(1.45)`) and one print-margin range (`36-54pt`). `visual-review/SKILL.md:25` accepts on "enough spacing and clear hierarchy" — **author and reviewer share the same undefined bar** (self-reinforcing vagueness; cannot converge on quality).

**Why it produces the symptom.** "Components fine, composition bad" is exactly this: a component in isolation is a rect+text (fine); internal-block proportions AND between-block rhythm/dominance/whitespace are the failure surface, and both are improvised every run. R10 maps the rendered defects directly: noisy type scale (no scale shipped), hand-picked gaps (no spacing scale), CTA pill too narrow (no vetted CTA block), ~300pt dead zone (no whitespace budget), missing eyebrow tier (no art-direction prior).

### RC-3 — DSL accepts free-form pixels into the solver *(confidence: high; corrects the original hypothesis)*

**The hypothesis "Brilliant has a constraint engine, we hand-place absolute coordinates" is FALSE** (S1 §0, R9). Both ship a Figma-style flex solver; R9's traces show every Lumen scene is `al(v|h, ...)` trees with `hug`/`fill`/`fill:N`, not `p(x,y)` scatter. The real gap is one layer up: **what the grammar lets the model feed the solver.**

**Evidence (the smoking gun, S1 §2).** Across the 5 runs the agent emitted these distinct spacing inputs into auto-layout containers:
```
g():   0,2,4,6,8,10,12,14,16,18,20,24,28,32,48          (16 distinct)
pad(): 0,16,18,20,24,28,36,48,(14,20),(16,48),(40,72)…  (~20 distinct)
```
Every value is hand-picked off any scale (`g(28)` beside `g(24)` beside `g(2)`). Brilliant's equivalent slot is `al(v,g($spacing.lg),pad($spacing.xl))` — token-quantized, and a bare numeric **halts the call** (`core.md:46`). The "7px here, 13px there" AI spacing tell is structurally impossible in Brilliant and is our default. Compounding: boxes are sized to the literal sample string, so real slot copy overflows (`LUMV0810/0902/0903/0904`) — there is no worst-case/content-aware sizing.

**Why it produces the symptom.** The solver faithfully lays out whatever gaps it's given; if the gaps are off-rhythm, the page is off-rhythm. Single-axis-only/no-grid is a secondary ceiling (R6 §2): it bites on layout *strategy* (the overflowing 3-card row that the agent never abandons) rather than on coordinate scatter.

### RC-4 — The loop is operationally blind *(confidence: high; verified)*

**Evidence (R10, R8 §3, S3 §3).** Every Lumen iteration's feedback is `kind:"preflight"` — pure compiler codes. `final.json.critique.kind == "preflight"`, `summary == None`. The capability to look at pixels exists (`preview_image_blocks`, `providers.py:217-254`) but the shipped default `preview_format="svg"` (`config.py:24`) means `export_preview_bundle` produces **no PNG** (`tools.py:816-820`), so the critic judges from SVG text geometry + a node digest. R9 confirms empirically: the one run that reached the critic cited `LUME0205` ("hand-placed not auto-layout") — a code that appears in **0** actual preflight outputs, i.e. the critic partly hallucinates rather than reading pixels. Brilliant's reference fixture carries `kind:"visual"` critiques with pixel coordinates and `suggested_repair` ("the right ~450pt is completely empty… center the stack or adopt a two-column layout"); its fixture-005 reached gallery-grade via *visual-critique-driven* repair using the **same 8 snippets** our run retrieved (R10 §6).

**Why it produces the symptom.** A preflight-only loop can shuffle `wrap_text`/`max_lines`/`size` on 4 nodes but can never name mixed alignment, dead space, or flat hierarchy — the exact things a human fixes first. So mediocre drafts are unrecoverable: iterations 2–N tweak overflow flags while the real defect (CTA pill too narrow, content laid wider than artboard, center-ragged subhead) persists, and the PNGs go pixel-identical (R10 §4).

### RC-5 (secondary) — Rendering-richness absence flattens every element *(confidence: high; R4)*

Independent of layout/loop, even a perfectly-composed Lumen draft renders flat: single `shadow()`, no inner shadow/glow/backdrop-blur, no shaders, uniform-only corner radius (`LUMD0230` squares them), and empty/placeholder image regions (imagery is a fixture-by-ID stub; no `generate_image`/`generate_svg`/icon library). Brilliant ships 38 docs of richness primitives, each ~1–2 tokens to invoke. This owns a large slice of the *premium-feel* delta but is **orthogonal** to spacing/density/hierarchy — do not let it crowd out RC-1–4.

---

## 5. "ARE THEY USING TEMPLATES?" — precise answer

**No full-page templates. Yes to a layered template SYSTEM.** The honest answer (R3 §5, S2 §7):

Brilliant does **template-driven assembly of pre-proportioned blocks**, not template instantiation. Four template-ish layers:
1. **`design/blocks/` catalog** — ~50 *parameterized block templates* where text/color vary but proportions (padding, gap, type scale, color roles) are fixed as token references. This is the load-bearing one for composition quality.
2. **`comp`/`inst()`/`slot`/`override()`** — a literal master-template + linked-instance mechanism with runtime sync ("3+ similar → stamp; never eyeball").
3. **`seedTemplateDsl`/`default.styles`** — a project token-system template auto-created on first run.
4. **`typography.*`/`shadow.*` composites** — named style templates.

**What stays generative:** the *page* composition (which blocks, in what order, scale, focal hierarchy), color ramps from seeds, and brand overlays via `ds_file`. So: *the page is generated; the blocks and their internal spacing/type/color are templated.*

**Lumen has none of this.** No `blocks/` directory exists anywhere under `apps/agent_runtime` (verified). `instance`/`clone`/`replace` exist in the grammar but **no template, block, or component is ever shipped or referenced**. Our 6 prose "recipes" are not reusable templates — they are one-off skeletons with ad-hoc magic numbers, a different rhythm per recipe, and 2 of 6 have no DSL at all. We do primitive draw-from-scratch with vague prose. **This is the largest single driver of the spacing/density/hierarchy gap** (S2 attributes ~60-70% of the spacing/density/hierarchy delta to the missing blocks catalog + token-stop enforcement).

---

## 6. REMEDIATION PLAN (P0/P1/P2, sequenced)

Sequencing rule: **fix the loop first so runs complete and you can SEE improvements**, then the single biggest composition lever, then the rest. DSL/knowledge work done before the loop fix is invisible — nothing clears Phase A.

### P0 — Unblock runs + biggest composition lever (do this week-to-two-weeks)

**P0.1 — De-deadlock the repair loop.** *(fixes "all runs fail"; RC-1)*
- **Make cluster repair non-atomic** (`loop.py:1386-1387`): apply valid `#refs`, report skipped ones; never zero-op a whole multi-line patch.
- **Widen the cluster to whole-page for page-bounds errors** (`LUMV0800/0801`) so error-carrying nodes outside the 20-node subset are reachable.
- **Allow `al()`/`wrap()` in cluster modify lines** (lift `loop.py:771`, `1404-1412`) — these are the actual overflow fix.
- **Add a metadata-fixture path** (a tool, not DSL) so `LUMV0509` is satisfiable; demote `LUMB0613/0614` and fixture warnings from blocking to advisory notes.
- **Special-case the A4 `LUMV0800` 0.11pt rounding** (clamp artboard fill-height to floor of canonical page height).
- **Raise the effective Phase-A cap** (≥8) and/or add **per-phase budgets** so geometry whack-a-mole can't starve the critic; pass **typed diagnostics** to the repair request (today `current_diagnostics` is `null`, codes smuggled in a string blob — R9 §3a).
- **Best-effort terminal:** if the budget hits but `best_scene` is preflight-clean, return `completed_with_warnings` and surface the draft, not `failed`. The keep-best machinery already exists (`_consider_best`/`_restore_best_scene`, `loop.py:646-690`) — it's just wired to a "failed" terminal.
- **Fix retrieval ranking** so `lumen-dsl/grammar.md` + `text.md` are always pinned in context for an authoring task (kills the `va`/`divider` iter-1 hallucinations).
- *Effort: medium (1–2 wk). Impact: runs go from 0% to mostly completing.*

**P0.2 — Ship a vetted block catalog.** *(single biggest composition lever; RC-2, §5)*
- Port Brilliant's `design/blocks/*` structure to Lumen DSL: Hero, Header, Footer, Card, Stat tile, Feature/benefit row, CTA, Form, Navbar — each with internal `g/pad/s/rd`, type roles, and color roles **pre-decided as token references**. Place under `apps/agent_runtime/knowledge_docs/knowledge/design/blocks/`.
- The agent's job becomes *assemble + tune vetted blocks*, not invent proportions. Kills improvised padding, wrong card density, and the mis-sized CTA at the source (R10 rows 1,2,6).
- *Effort: high. Impact: highest quality lever — the layer we entirely lack.*

### P1 — Make first drafts good + recoverable

**P1.1 — Numeric spacing + type scale with grammar enforcement.** *(RC-3)*
- Give `$space.*` real values via a `tshirt`-equivalent (`number(4,32,linear())`); add a `$font.size.*` scale; add the rule "heading = 150-200% body, anchor 2-3× body, hierarchy via Size+Weight+Color".
- **Reject bare numerics** in `g()`/`pad()`/`rd()`/font-size (mirror `core.md:46`). Removes the 16-distinct-`g()`-value tell and the noisy `22px`×4 type scale **by construction**.
- *Effort: medium. Impact: very high — eliminates the #1 amateur tell mechanically.*

**P1.2 — Wire a real visual critic into the loop.** *(RC-4)*
- Default the critique export to **PNG** (`config.py:24`); render the preview and emit `visual_balance`/alignment/hierarchy issues **with pixel coords + suggested repairs** into `repair_request.exact_feedback` — Brilliant's proven format. Give the reviewer a *measured* rubric (whitespace ratio, alignment-spine check, focal-dominance/squint test) instead of the undefined "enough spacing".
- Make the shipped provider path (`providers.py`) actually load the SKILL/knowledge it currently bypasses (`prompts.py:160-175` mounts are on subagent defs the flat `model.invoke()` path skips).
- *Effort: medium. Impact: very high — makes mediocre drafts recoverable; fixes mixed alignment, dead zones, flat hierarchy at once.*

**P1.3 — Content-aware / worst-case sizing as default + art-direction priors.**
- Size text boxes to slot worst-case fixtures, not the literal sample string (kills `LUMV0810` at the source, not via repair).
- Port `foundations.md`'s judgment layer: one-dominant-region + squint test, 60-70% whitespace, 60-30-10, WCAG 4.5:1/3:1, single alignment spine per stack, eyebrow convention, anti-cliché list.
- **Fix knowledge delivery** (S2 §4): the 4.8 KB cap (`tools.py:50-51`) makes a bigger corpus inert — move to task-scoped fuller-doc loading.
- *Effort: low-medium. Impact: high — improves iteration-1 directly.*

### P2 — Structural depth + premium feel

**P2.1 — Let repair change layout strategy; add a grid/bento primitive.** Lift the repair ban on `#node al(...)`/`#node wrap(...)` (`layout-cluster-repair.md:71-73`); add nested-auto-layout grid/bento via `fill:N`. Lets the agent abandon an overflowing 3-card grid for single-column (Brilliant fixture-005) instead of shuffling wrap flags forever. *Effort: medium-high.*

**P2.2 — Activate `density` mode** to shift the whole scale a notch (`authoring-modes.md:13` analog). *Effort: low once P1.1 lands.*

**P2.3 — Rendering richness (RC-5):** inner shadow/glow, backdrop blur, per-corner radius, then AI image/SVG/icon generation. Each ~1–2 DSL tokens. *Effort: high; biggest premium-feel return is imagery + inner-shadow/glow/blur.*

**P2.4 — Reconsider the 3-agent split.** Brilliant explicitly warns against planner/builder/critic separation ("Build everything yourself… sub-agents produce output you'll need to fix anyway"). Our split + shared 5-turn budget + critic-gated-behind-preflight is precisely the anti-pattern. Longer term, collapse toward a single judge-and-stop author over a forgiving canvas, with the bounded loop only as a safety net.

---

## 7. QUICK WINS (this week) vs STRUCTURAL

**Quick wins (days, high impact-per-effort):**
- Non-atomic cluster repair + whole-page cluster for page-bounds errors (P0.1) — unblocks runs.
- Special-case A4 `LUMV0800` 0.11pt rounding; demote `LUMB0613/0614` to advisory.
- Best-effort terminal via existing `_restore_best_scene` (P0.1) — users see a draft instead of "failed".
- Default critique export to PNG (P1.2) — turns the blind critic on.
- Pin grammar/`text.md` in retrieval (RC-1) — kills `va`/`divider` hallucinations.
- Reject bare numerics in `g()`/`pad()`/font-size + ship a spacing/type scale (P1.1) — removes the spacing/type-scale tell.
- Size CTA pill to its label; enforce one alignment spine per stack (R10) — kills the two-line-CTA and center-ragged-subhead tells.

**Structural (weeks-to-months):**
- The block catalog (P0.2) — biggest lever, but real authoring work.
- Visual critic with rubric + pixel coords + suggested repairs wired into repair (P1.2).
- Knowledge-delivery overhaul + provider-path SKILL loading (P1.3) — without this, a bigger corpus is inert.
- Grid/bento primitive + layout-strategy change in repair (P2.1).
- Rendering-richness primitives + AI imagery (P2.3).
- Single-agent judge-and-stop architecture (P2.4).

---

## 8. OPEN QUESTIONS / THINGS TO VERIFY

1. **Effective vs configured iteration cap.** `config.py:23` sets 5, but R9 measured ~3 effective Phase-A cycles. Confirm where the 3 comes from (rejected blocks burning turns, or a separate Phase-A sub-cap) before tuning the budget.
2. **Does the heuristic vs LangChain director matter?** R8 notes the shipped provider path bypasses SKILL/knowledge loading. Verify which director ran the 5 failed runs and whether wiring SKILLs in changes the iter-1 hallucination rate.
3. **Is `LUME0205` dead code?** The critic cited it but it appears in 0 preflight outputs (R9 §5). Confirm whether the critic has a parallel diagnostic vocabulary that doesn't match the preflight engine — if so, the critic's prose is partly ungrounded.
4. **Slot fixtures: where do they live and how does the agent set them?** `LUMV0509` is unfixable because fixtures are scene metadata with no tool. Confirm the intended authoring path and add the tool (P0.1).
5. **PNG parity.** R8 flags no guaranteed browser-screenshot parity. Before trusting a PNG critic, verify the SVG→PNG render matches the editor render (banding, font metrics) — Brilliant uses `scale:2.0 + webpLossless:true` for exactly this reason.
6. **Doc-count vs retrieval.** R10 showed the visual-critic gap, not doc count, was proximate in its slice (identical 8 snippets retrieved). Re-confirm after P0.2/P1: once blocks/scales are shipped, is retrieval surfacing them, or does the ranker still bury them?
7. **`LUMV0800` for non-A4 surfaces.** The 0.11pt overflow was A4-specific. Verify Letter/LinkedIn/landscape presets don't have analogous ceil-rounding traps before shipping the clamp fix.
