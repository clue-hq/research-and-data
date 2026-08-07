# S1 — Synthesis: The DSL & Layout-Engine Gap (Lumen vs. Brilliant)

**Synthesis inputs:** R1 (Brilliant foundations / numeric systems), R2 (Brilliant blueprint DSL + layout object model), R6 (our knowledge incl. lumen-dsl), R9 (trace forensics — what DSL the agent actually emitted), R10 (visual comparison). Cross-checked against primary source: `brilliant/knowledge/**` (91 docs, count verified) and `apps/agent_runtime/knowledge_docs/knowledge/**` (~19 docs) and the 5 failed runs in `.lumen-runs/`.

---

## 0. Verdict up front

**Is "Brilliant has a constraint/auto-layout engine while we make the model hand-place absolute coordinates" the #1 root cause of our bad composition?**

**Partly — but the framing is wrong, and getting it wrong would lead to the wrong fix.** The leading hypothesis as literally stated is **FALSE**: we are *not* making the model hand-place absolute coordinates. **Both** systems ship a Figma-style auto-layout/flex solver (`hug`/`fill`/`fill:N`/`g()`/`pad()`/`x()`/`y(sb)`), and R9 proves our agent *actually uses it* — every authored scene is `al(v|h, ...)` trees, not `p(x,y)` scatter.

The real gap is one level up, in **what the DSL grammar lets the model feed the solver**. Brilliant quantizes every spacing/size/type input to a **named stop on a generated numeric scale** (`$spacing.md` off `tshirt(number(4,32,linear()))`) and **halts the call on a bare numeric**. We accept **raw free-form pixels** in the same slots — and the model emits them, off any scale. So:

- **The constraint solver is NOT the gap.** We have one.
- **The token-quantized input layer + the numeric design system feeding it IS the gap.** We have neither.

**Confidence this token/scale gap (not the solver) is a top-2 root cause of low composition quality: ~85%.** It is co-#1 with the missing **visual-critic feedback channel** (R10) and the **non-convergent repair loop** (R6/R9), which are what actually *kill* the 5 runs before composition quality even gets judged. See §6 ranking.

---

## 1. The decisive comparison (what each side actually is)

| Capability | Brilliant | Lumen (ours) | Evidence |
|---|---|---|---|
| Auto-layout / flex solver | Yes — `AutoLayoutData`, `LayoutBehavior.flex`, hug/fill resolution, computed item spacing | **Yes** — `al(v\|h, x(), y(), g(), pad(), grow(n), wrap(bool))`, `hug`/`fill`/`fill:weight` | R2 `reference/frames.md`; R6 `lumen-dsl/grammar.md:89-94`, `layout.md:9-15` |
| Proportional splits (`fill:N`) | Yes — `fill:2` vs `fill:1` → 2/3 ÷ 1/3; documented flex math | **Yes** — `fill(weight)`/`fill:weight` | R2 `layout.md:7,32`; R6 `layout.md:14` |
| `space-between` distribution | Yes — `x(sb)` → `computedItemSpacing` | **Yes** — `sb` anchor | R2 `layout.md:27`; R6 `grammar.md:91` |
| **Spacing input = token only** | **Yes — `g($spacing.md)`; bare numeric HALTS the call** | **No — `g(28)`, `g(18)` raw px accepted** | R2 `core.md:45-46`; **R9: agent emitted `g(2,4,6,8,10,12,14,16,18,20,24,28,32,48)` across runs** |
| Numeric spacing scale exists | Yes — `tshirt(number(4,32,linear()))` → xs..6xl | **No — `$space.*` are role *names* with no values** | R1 `v3-design-spec.md:76`; R6 `token-taxonomy.md:21,59`; **grep for any `tshirt`/`4,8,16`/`number(4` ramp in our docs → 0 hits** |
| Numeric type scale | Yes — 12..128, "heading = 150-200% of body", anchor 2-3× | **No — `$type.*` role names only, no sizes/ratios** | R1 `typography.md:8-26`; R6 §1, `token-taxonomy.md:42,57` |
| `density` mode that re-resolves the scale | **Yes — `density.compact: shift(-1)` shifts the whole ramp a notch** | **Declared but valueless** — `density: comfortable\|compact` axis with no numeric meaning | R1/R2 `authoring-modes.md:13`; R6 `modes.md:11` |
| 2-D grid / multi-column primitive | Nested auto-layouts + layout guides (tables, kanban, bento `fill:3`/`fill:2`) | **No — single-axis flex; grid = "Future Scaffold"** | R2 `design/blocks/patterns.md`; R6 `layout-recipes.md:131` |
| Absolute positioning | Opt-in escape hatch (`abs p()`), "excluded from gap/hug calcs", scoped to badges/overlays | **`p(x,y)` on *every* node, always available** (trap) | R2 `frames.md`; R6 `grammar.md:62,64` |
| Pin-to-edge constraints | "Not available — use auto layout with hug/fill/fixed" | n/a (same philosophy) | R2 `reference/frames.md:24` |
| Pre-composed blocks/recipes | **Yes, extensive** — `design/blocks/{layout,patterns,...}`, `blueprint/layout-patterns`, components | **No** — ~6 prose recipes, 2 with no DSL skeleton at all | R2 §3; R6 §3 |

**Resolved contradiction (R2 vs R9):** R2 frames the gap as "constraint solver + token scale **vs. absolute coordinates + free-form numbers**." R9 proves the "absolute coordinates" half is wrong for us — our model authors auto-layout, not coordinate scatter. **The half of R2's framing that survives and is decisive is "token scale vs. free-form numbers."** R2's own conditional language ("*If* a competitor instead emits absolute positions…") is what's falsified; its token-grammar analysis is exactly right. R6 §2 independently reached the correct conclusion: ours is "a genuine Figma-style auto-layout model, NOT pure absolute placement." **R2, R6, and R9 are consistent once you locate the gap at the input layer, not the solver.**

---

## 2. The smoking gun: what the model fed the solver

R9's trace teardown, re-verified against `.lumen-runs/`, is the single most load-bearing piece of evidence. Across the 5 runs the agent emitted these **distinct** spacing inputs into auto-layout containers:

```
g():   0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 48        (16 distinct)
pad(): 0, 16, 18, 20, 24, 28, 36, 48, (14,20), (16,48), (16,52),
       (20,52), (40,72), (36,36,36,36), (40,48,40,48), …            (~20 distinct patterns)
```

Representative authored line (`run_c0feb` flyer iter 001, via R9):
```
main_content al(v,x(s),g(28),pad(56,48,56,48)) s(fill,fill)
  headline text "…" s(fill,hug) font("Inter",36,800,left)
  benefits_row al(h,x(s),g(24)) s(fill,hug)
```

Every one of those `g()`/`pad()` numbers is **hand-picked free-form**, off any scale (`g(28)` next to `g(24)` next to `g(18)` next to `g(2)`). Compare the equivalent Brilliant line, where the same slots are **token-quantized**:
```
al(v,g($spacing.lg),pad($spacing.xl)) s(360,hug)            # core.md:7
al(h,x(c),y(c),g($spacing.sm),pad($spacing.md,$spacing.lg)) # core.md:10
```

**This is the "7px here, 13px there" AI spacing tell, present in our raw trace data and structurally impossible in Brilliant's grammar.** Brilliant: "bare hex or numerics halt the call" (`core.md:46`); spacing comes only from `tshirt(number(4,32,linear()))` rungs. We never offer the model a scale to snap to, so it free-guesses every gap — and R10 sees the result: a "noisy `13/15/17/22/36`" type scale with `22px` used 4× where the fixture uses a clean modular `13/15/16/18/20/40`.

**Equally important (R9):** the gaps are not just off-scale, they are **never re-flowed when content changes**. Boxes are sized to the literal sample string; the slot's real ("worst-case") copy then overflows (`LUMV0810`, `LUMV0902/0903/0904`). Brilliant's mandatory `s(fill,hug)` + hug/fill resolution + worst-case sizing make this a non-event; our hand-picked fixed sizes make it the dominant error class.

---

## 3. Why the gap is at the *input* layer, not the *solver* layer

Three structural mechanisms in Brilliant's grammar do the composition work that we offload onto the model's unaided judgment. **None of them is the solver itself** — they all govern what the solver receives:

1. **Token-quantized, mandatory spacing input.** `g()` + `pad()` are *required* on every `al()` (Brilliant `core.md:29`, ours `layout.md:7` — both require them), but Brilliant *additionally* restricts the value space to scale rungs and halts on a bare numeric (`core.md:45-46`). Net effect: in Brilliant the model picks "md / lg / xl"; in ours it picks "28 / 18 / 2." The former cannot produce off-rhythm spacing; the latter does it by default.

2. **A real numeric design system feeding those tokens.** Brilliant generates spacing/radius/font-size/weight/line-height/letter-spacing/opacity from one `tshirt()/boldness()/looseness()` family (R1 `v3-design-spec.md:76-89`), with `density.compact: shift(-1)` re-resolving the whole ramp (R1 `authoring-modes.md:13`). Our `$space.*`/`$type.*` are **role names with no values** (R6 `token-taxonomy.md:21,57,59`) — so even where we *do* use a token, it resolves to nothing principled, and our `density` axis is inert (R6 `modes.md:11`).

3. **Pre-composed blocks where the spacing/hierarchy is already decided.** Brilliant ships `design/blocks/{layout,patterns}` (Header, Footer, Hero, Bento grid with `fill:3`/`fill:2` "no pixel math", N-equal-width, etc.) so the model *fills a recipe* rather than re-deriving rhythm (R2 §3, R3). We ship ~6 prose skeletons, 2 with no DSL at all, and zero reusable blocks (R6 §3). Every Lumen run re-invents the composition from primitives.

The 2-D grid limitation (R6 §2: single-axis flex only, grid = Future Scaffold) is a **secondary** expressiveness ceiling: it makes genuinely composed multi-column/editorial layouts inexpressible *systematically*, which (R6 inference) pushes the model toward fixed sizes — but R9 shows our model mostly stayed in nested single-axis auto-layouts, so this bites on *layout strategy* (the §4 overflowing 3-card row) more than on raw coordinate scatter.

---

## 4. Does this fully explain the bad compositions? No — two other gaps gate it

A crucial cross-reader correction the focus question must absorb: **the DSL/token gap degrades quality, but it is not what kills the runs.** R9 and R10 both show all 5 runs die in **Phase-A repair** (`max_iterations_reached`, "Maximum Phase A repair iterations reached") — *before any composition judgment is rendered*. Two independent failures sit on top of the token gap:

- **(R10) Our repair loop is visually blind.** Every iteration's feedback is `kind:"preflight"` — compiler diagnostics only (`LUMV0902/0903/0810`). `final.json.critique.kind == "preflight"`, `summary == None`. Brilliant's loop carries `kind:"visual"` critiques with pixel coords and `suggested_repair` ("center the content stack… or adopt a two-column layout"). **A better spacing grammar still wouldn't fix balance/hierarchy/whitespace if nothing ever sees the rendered pixels.** R10 verified our run and the Brilliant fixture retrieved the *identical 8 snippets* — so for that slice the doc-count gap was not proximate; the missing visual channel was.

- **(R6/R9) The repair loop cannot converge.** 3-cycle effective budget vs. 8-28 diagnostics; the layout-cluster gate *atomically rejects* the planner's own correct whole-page patch when any `#ref` falls outside a 20-of-38-node allowed set; `al()`/`wrap()`/`slot:` edits are banned in repair, so 5 of ~8 active codes on the A4 runs are **unfixable in the offered surface** (incl. `LUMV0800`: A4 portrait canonicalizes to 841.89pt, artboard `s(fill,fill)` ceils to 842pt → permanent ~0.11pt overflow the model is forced into). Re-authoring (the only move that fixes a globally bad composition) is "last resort" and largely forbidden.

**These compound with the token gap:** weak spacing/sizing grammar produces designs that trip bounds/fit diagnostics → the blind, non-convergent loop can't clear them → `max_iterations_reached`. The token gap is the *quality* root cause; the loop+critic gaps are the *failure* root cause.

---

## 5. Quantified confidence

| Claim | Confidence | Basis |
|---|---|---|
| We have an auto-layout solver (hypothesis's "absolute coords" premise is false) | **~97%** | R6 grammar + R9 trace both show `al()` trees with `hug`/`fill`/`fill:N` actually used |
| The real DSL gap is token-quantized input + numeric design system, not the solver | **~90%** | R2 (Brilliant grammar), R1 (numeric scales), R6 (ours has role-names-no-values), R9 (16 free-form `g()` values emitted) |
| This token/scale gap is a top-2 driver of *low composition quality* | **~85%** | Direct: off-scale spacing + content-blind fixed sizing visible in R9 trace and R10 PNGs |
| This is the **single #1** root cause of our composition *problems* (quality + failures combined) | **~45%** | Competes with visual-critic gap (R10) and loop-convergence gap (R6/R9), which gate whether quality is ever judged or improved |
| Closing only the token/layout gap (leaving loop+critic untouched) would materially raise shipped quality | **~35%** | Runs would still die in Phase A; quality improvements wouldn't reach the user |

**Decision:** the token/scale DSL gap is **co-#1 for quality** but **not sufficient alone**. Rank it #1 among *composition-quality* causes, #2-3 among *all* causes (behind the loop-convergence bug that prevents any output from shipping).

---

## 6. Ranked root causes (all readers reconciled)

1. **Repair-loop non-convergence (R9, R6).** Atomic cluster-gate rejection + banned `al()`/`slot:` edits + 3-cycle cap + structurally-unfixable codes (`LUMV0800`, `LUMB0613/0614`) ⇒ every run hits `max_iterations_reached`. *Kills all 5 runs regardless of anything else.* **#1 for failure.**
2. **No token-quantized spacing/type input + no numeric design system (R2, R1, R6, R9).** Model feeds free-form `g(28)`/`pad(...)`/font sizes into the solver; spacing/hierarchy come out off-rhythm and content-blind. **#1 for composition quality.** *This is the DSL/layout-engine gap, correctly located.*
3. **No visual-critic feedback channel (R10).** Loop sees only preflight codes, never rendered-pixel balance/hierarchy/whitespace; can't fix what a human fixes first.
4. **No pre-composed blocks / thin recipe layer (R2/R3 vs R6).** ~6 prose recipes vs Brilliant's blocks+patterns+components; every layout re-invented.
5. **Single-axis flex, no 2-D grid (R6).** Multi-column/editorial layouts inexpressible systematically; forces fallback to fixed-size strategies that overflow.
6. **Retrieval/ranking (R9).** Our grammar/text docs *exist* (`text.md:29` literally says "There is no `valign`") but weren't among the 8 retrieved snippets, so the model hallucinated `va`/`divider` and burned iter-1 on compile errors — so it's not purely the 91-vs-19 count.

---

## 7. The exact capability we are missing + minimal layout-engine features to close most of the gap

**We are NOT missing a constraint solver. We are missing the token-quantized input grammar and the numeric design system that feeds it.** Minimal feature set, in priority order:

1. **A real numeric spacing scale + grammar enforcement.** Define `$spacing.*` as actual values (e.g. `tshirt`-style `4,8,16,24,32,48` with `none:0`), and **reject bare numerics in `g()`/`pad()`/`rd()`/font-size** the way Brilliant halts on them (`core.md:46`). This alone removes the 16-distinct-`g()`-value tell from §2. *Highest quality-per-effort; the engine already consumes whatever `g()` resolves to.*
2. **A numeric type scale + size-contrast rule.** Give `$type.*` real sizes/ratios and a "heading = 150-200% of body, anchor 2-3×" rule (R1 `typography.md:26,38`). Kills the noisy `22px`×4 scale R10 measured.
3. **Worst-case / content-aware sizing as the default.** Make `s(fill,hug)` + slot worst-case fixtures the path of least resistance for any text node, so boxes never get sized to the literal sample string (the §2 overflow class). This is a grammar/default change, not a new solver.
4. **Activate the `density` mode to shift the scale a notch** (Brilliant `authoring-modes.md:13`), turning density from an inert axis (R6 `modes.md:11`) into a real lever.
5. **Ship 6-10 pre-composed blocks** (Header/Hero/Footer/feature-row/stat-grid/CTA) with spacing/hierarchy pre-chosen in tokens, mirroring `design/blocks/layout.md`. Lets the model fill recipes instead of re-deriving rhythm.
6. **(Stretch) A 2-D track/grid primitive** so multi-column layouts are expressible without dropping to fixed sizes.

**Caveat that must travel with this recommendation:** items 1-6 raise *quality*, but the runs will still fail until the **loop-convergence bug (#1)** and the **visual-critic channel (#3 in §6)** are fixed. Sequence: fix the loop so output ships → wire in the visual critic so quality is judged → then the token/scale grammar (items 1-3 here) makes the model's *first* draft good enough that the critic and loop have little to do. Doing the DSL work alone would be invisible to users because nothing would clear Phase A.

---

## 8. One-paragraph answer to the focus question

Brilliant does have a constraint/auto-layout engine where the model declares intent and the engine computes spacing — **but so do we** (R6 `grammar.md:89-94`; R9 trace shows real `al()`/`hug`/`fill:N` usage). The hypothesis's premise that "we make the model hand-place absolute coordinates" is **false**. The true, evidence-backed gap is one layer up: Brilliant **quantizes every spacing/size/type input to a named stop on a generated numeric scale and halts on a bare numeric** (`core.md:46`, `tshirt(number(4,32,linear()))`), while we accept **free-form pixels** and ship **role-name tokens with no values** — so our model emitted 16 distinct off-scale `g()` values across the 5 runs and sized boxes to literal sample strings. This token/design-system gap is **co-#1 for low composition quality (~85% confidence)**, but it is **not the #1 cause of our failures**: all 5 runs die in a blind, non-convergent Phase-A repair loop before composition is ever judged (R9, R10). Fix the loop and visual critic first so output ships and is graded; then add a numeric spacing scale, a type scale, content-aware sizing, an active density mode, and pre-composed blocks to make the first draft Brilliant-grade.

---

*Report file: `/Users/aryankeshri/conductor/workspaces/clue-design/havana/.context/brilliant-audit/S1-dsl-layout-engine-gap.md`*
