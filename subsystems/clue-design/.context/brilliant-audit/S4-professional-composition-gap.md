# S4 — Synthesis: Why Composition Specifically Fails (Lumen vs. Brilliant)

**Synthesis inputs:** R1 (foundations), R2 (blueprint DSL), R3 (blocks/systems), R6 (our knowledge), R9 (trace forensics), R10 (visual comparison).
**Question answered:** *Individual components look fine, but composed together the spacing / density / layout / hierarchy is wrong.* Why does **composition specifically** fail, and how is that separable from the loop bug?

**Verified during synthesis (not just asserted by readers):**
- Brilliant ships **91** knowledge docs; we ship **26** (`find … -name '*.md' | wc -l`). R6 said "~19"; the accurate count is 26 — R9's "26-doc set" is correct. The 91-vs-26 gap stands.
- We ship **no `blocks/` directory** (`find -type d -name blocks` → nothing). R3 confirmed.
- Brilliant's scale generators are real and numeric: `spacing: tshirt(number(4, 32, linear()))`, `radius: tshirt(number([4,8,16,24,32,48]))`, `boldness` (9 stops), `looseness` (6 stops), `visibility` (9 stops) — `v3-design-spec.md:19-23,76-80`. The bare-token halt is real: *"`$spacing` / `$radius` / `$font.size` are never used bare; agent always picks a stop"* — `v3-design-spec.md:61`.
- Our docs contain **zero** matches for "spacing scale / type scale / 8pt grid / modular scale" — confirms R6's "only concrete numbers are line-heights."
- Our repair surface really forbids the structural fixes: *"Do not write `#node al(...)` … `al(...)` is creation syntax … not a supported modify-line property. Do not write `#node wrap(...)` either"* — `layout-cluster-repair.md:71-73`. And our grammar lists *"editorial grid systems"* under **Future Scaffold** — `layout-recipes.md:122,131`.

---

## 0. The one-sentence answer

**Composition fails because Brilliant decides spacing/density/hierarchy in three places we don't have — a token grammar that makes off-rhythm values unrepresentable (R1/R2), a vetted ~50-block catalog with proportions pre-baked (R3), and a visual critic that grades the rendered page and feeds pixel-level fixes back (R10) — whereas Lumen re-invents every composition from primitives using prose adjectives (R6), then cannot fix what's wrong because its repair loop is both *blind* (preflight-only feedback, R10) and *structurally handcuffed* (can't change layout containers in repair, R6/R9).** The loop bug kills the runs; the composition gap is *why even a clean-compiling Lumen draft loses to Brilliant* (proven by R9: the one run that compiled clean was still rejected for 300pt of dead space).

The two problems are separable and must be fixed separately:
- **Loop bug (R9 §A):** all 5 runs die in Phase A; ~5 of 8 active diagnostics are *unfixable in the offered repair surface*. This is a runtime defect. Fixing it makes runs *finish*.
- **Composition gap (this report's focus):** even a finished Lumen draft is not Brilliant-grade. This is a *knowledge + DSL + feedback* defect. Fixing it makes finished drafts *good*.

Do not conflate them. Fixing the loop alone yields runs that complete and still look amateur.

---

## 1. Causal chain: WHAT WE SEE → WHY → WHAT TO CHANGE

Every observed defect in R10 maps cleanly to an upstream cause. Composition defects (rows 1-7) are distinct from pure loop/render bugs (rows 8-10). The key insight: **most "what we see" defects are between-element, whole-page concerns** — exactly the layer Brilliant encodes and we leave to prose.

| # | WHAT WE SEE (R10) | Defect class | WHY — upstream cause | Evidence | WHAT TO CHANGE |
|---|---|---|---|---|---|
| 1 | Noisy type scale `13/15/17/22/36`, `22px` used 4×; no display/body discipline | **Hierarchy** | No type scale in our knowledge — only role *names* (`style($type.display/headline/body)`) with no sizes/ratios; agent free-guesses font sizes (R6 §1, §5-B). Brilliant: `font.size` is a `tshirt` scale + "heading = 150-200% of body, anchor = 2-3× body" (R1 §2, `typography.md:26`). | R10 §1a, R6 §1, R1 §2 | Ship a numeric type scale + the 150-200%/2-3× anchor rule. **Missing knowledge.** |
| 2 | Hand-picked gaps `g(28)`, `pad(56,48,56,48)`; off-rhythm density | **Spacing** | No spacing scale; `$space.*` are role names with no values (R6 §5-A). Agent copies a skeleton constant or guesses. Brilliant: `g()/pad()` accept **only** `$spacing.*` tshirt rungs; bare numerics **halt the call** (R2 §1,§4.1; `v3-design-spec.md:61`). Off-scale spacing is literally unrepresentable for Brilliant. | R9 §1, R6 §1, R2 §4 | Add a spacing scale **and make bare gaps illegal** in `g()/pad()`. **DSL limitation + missing knowledge.** |
| 3 | LinkedIn subhead center-ragged inside a left-aligned stack; left edge zig-zags | **Alignment** | No "single alignment spine per stack" rule; alignment is per-node and unconstrained (R6 §1). Brilliant: `x()/y()` alignment is a container property; squint-test + "one dominant region" doctrine (R1 §1). | R10 §1b, R1 §1 | Enforce one alignment spine per content stack. **Missing knowledge** (DSL already supports `x()/y()`). |
| 4 | ~300pt vertical dead zone (LinkedIn); top-heavy / bottom-dead whitespace (flyer); right ~450pt empty | **Whitespace / balance** | Whitespace is *leftover*, not *composed*. Mis-tuned fractional `fill` weights (`fill(3)` over `fill(1)` spacer) dump empty space (R9 §4). No whitespace-ratio guidance beyond "generous." Brilliant: "aim 60-70% whitespace then ask what to remove," composed margins, asymmetry-over-grid (R1 §1, `foundations.md:35-37`). | R9 §4, R10 §1b/§3 row 4, R1 §1 | Add whitespace-budget + balance rules; the visual critic (#5 below) must *measure* balance. **Missing knowledge + no visual critic.** |
| 5 | Locks onto an overflowing 3-card grid; only tweaks `wrap_text`/`max_lines` flags; never switches strategy | **Layout strategy** | No grid primitive (single-axis flex only; "editorial grid systems" = Future Scaffold, `layout-recipes.md:131`), and **repair forbids changing layout direction/wrap** (`layout-cluster-repair.md:71-73`). So a wrong layout *cannot be re-laid-out* in repair (R6 §2,§4). Brilliant: nested auto-layouts express grids/bento with `fill:N` "no pixel math," and falls back to single-column/inline list when a grid overflows (R2 §2, R10 §2 fixture 005). | R10 §1a/§4, R6 §2/§4, R2 §2 | Allow layout-container changes in repair; add grid/bento patterns. **DSL limitation + loop never fixes it.** |
| 6 | Every block's internal proportions improvised; CTA pill `hug`-sized too narrow → "Book a / Demo" wraps (flyer + A4) | **Density / block proportion** | No vetted block catalog — our entire design knowledge is 3 thin recipe files; **no `blocks/` dir exists** (verified). Agent re-derives card padding, CTA sizing, image height every run (R3 §6, R6 §3). Brilliant: ~50 pre-proportioned blocks with `pad`/`s`/type pre-chosen (card `pad($spacing.lg)`, hero `pad(80-120…)`, CTA solid sized to label) (R3 §1). | R10 §1a/§1c, R3 §1/§6, R6 §3 | Ship a block catalog with proportions baked as tokens. **Missing knowledge (the single biggest lever).** |
| 7 | No eyebrow/kicker tier; flat 60% canvas usage; everything one weight | **Hierarchy / art-direction priors** | No art-direction priors (eyebrow conventions, anti-cliché list, dominance doctrine). Brilliant ships explicit anti-cliché negative knowledge + "one focal anchor per section, everything else subordinate" (R1 §1). | R10 §2, R1 §1 | Ship art-direction priors + anchor/dominance rule. **Missing knowledge.** |
| 8 | 1-2px blue sliver "icons" | Render/overflow bug | `LUMV0902 b1_icon overflows horizontally` — icon text node overflows; not a composition decision. | R10 §1a, R9 §2 | Render real icons or drop them. **Render/loop bug, NOT composition.** |
| 9 | Same 8 diagnostics persist iter 002→003; PNGs near-identical | Loop bug | Whack-a-mole: fixing one node pushes a sibling over (`LUMV0903` 0→3); no holistic reflow; 3-cycle budget vs 8-28 diagnostics. | R9 §2/§3, R10 §4 | Raise cap, pass typed diagnostics, non-atomic cluster. **Loop bug, NOT composition.** |
| 10 | All 5 runs end `failed / max_iterations_reached` | Loop bug | ~5 of 8 active codes (`LUMV0509/0810/0800`, `LUMB0613/0614`) unfixable in the offered repair surface; layout-cluster atomic-rejects the correct whole-page patch (20-of-38 nodes allowed). | R9 §2/§3 | Fix cluster definition, allow `slot:`/`al()`/`wrap()`, special-case A4 `LUMV0800`. **Loop bug, NOT composition.** |

**Reading the table:** rows 1-7 are the composition gap (the user's core pain). Rows 8-10 are the loop bug. The loop bug *masks* the composition gap (the user rarely sees a finished draft), but fixing the loop will *expose* rows 1-7 in full — that is why both tracks are needed.

---

## 2. Why composition fails — the three missing layers (decisive root-cause ranking)

Brilliant gets good composition "by construction" via three layers stacked on top of primitives. We have only the primitives. Ranked by impact on **composition quality specifically** (not on whether runs finish):

### Root cause #1 (highest impact): No vetted block catalog — every composition is improvised
*Supported by R3 (primary), R6 §3, R10 §1/§6.*

Brilliant's `design/blocks/*` is a 7-file catalog of ~50 blocks where **internal spacing, padding, type scale, hierarchy, and color roles are pre-decided as token references** — card `g($spacing.md) pad($spacing.lg)` + `rd($radius.md)` + soft shadow + title `$font.size.lg`/sb over `$font.size.sm`/secondary (R3 §1); hero `pad(80-120,$spacing.3xl)`; CTA "solid — never gradient." The agent *assembles and tunes vetted blocks* (R3 §2,§5).

We ship **no blocks at all** (verified: no `blocks/` dir). Our entire composition knowledge is 3 prose files (`layout-recipes.md` 131 lines, `typography-and-composition.md`, `artboard-frame-authoring.md`), 4 of 6 recipes have a single 5-9 line skeleton, 2 have none (R6 §3). So the agent re-derives every block's proportions each run from vague guidance — and gets the CTA pill width, card padding, and image height wrong (R10 §1a/§1c). **This is why "components look fine but composition is wrong": there is no vetted between-element proportion anywhere in our corpus.** Brilliant pre-decided the relationships; we only normalize values (and barely that).

### Root cause #2: DSL doesn't enforce a spacing/type rhythm — off-scale values are legal (and default)
*Supported by R2 (primary), R1 §2, R6 §1.*

Brilliant's grammar makes bad spacing **structurally hard**: `g()/pad()/rd()/font-size` accept **only** tshirt-scale tokens; a bare numeric **halts the call** (R2 §4.1, `v3-design-spec.md:61`). Every container *must* declare `g()`+`pad()` (R2 §2). Hierarchy is "Size + Weight + Color, 2-3 levers at once," heading 150-200% of body, anchor 2-3× (R1 §2). The agent picks a *rung on a scale*, never a pixel.

Our DSL permits raw pixels everywhere (`g(28)`, `pad(56,48,56,48)`), `$space.*` are value-less role names (R6 §1,§5-A), and there is **no numeric spacing or type scale in the corpus at all** (verified empty grep). Result: off-rhythm gaps and a noisy `13/15/17/22/36` type scale with `22px`×4 (R10 §1a). **The "7px here, 13px there" AI tell that is impossible for Brilliant is the default for us.** (Note R2's inference: this also feeds the loop bug — improvised sizes trip the bounds/fit diagnostics the surgical repair surface can't clear.)

### Root cause #3: The repair loop is blind to composition (preflight-only feedback)
*Supported by R10 (primary, with hard evidence), R9 §B, R6 §4.*

This is the most *surprising* finding and the one R10 proves with file evidence. Our repair feedback is `kind: "preflight"` every iteration — pure compiler diagnostics (`LUMV0902/0903/0810`). Our `final.json.critique.kind == "preflight"`, `summary == None`. **There is no visual critic in the loop.** Brilliant's fixture has `critique.kind == "visual"` with prose like *"content occupies roughly 60% of the 1200pt-wide canvas; the right ~450pt is completely empty"* and `visual_balance` issues carrying **pixel coordinates + suggested repairs** ("center the content stack… or adopt a two-column layout") (R10 TL;DR, §4).

So even when Lumen compiles clean, nothing in the loop names "mixed alignment," "dead zone," "no hierarchy." R9 confirms the consequence empirically: `run_92039` reached the critic with `has_errors=False` and was **still rejected** — for 300pt of dead space, mid-page hierarchy collapse, alignment inconsistency (R9 §5-B). **The loop is structurally incapable of fixing what a human fixes first**, because it can't see it.

**Caveat / contradiction resolved (R10 vs R1/R3/R6 on doc count):** R10 verified that *in its slice* our run and the Brilliant fixture retrieved the **identical 8 snippets** — so the 91-vs-26 doc gap was *not* the proximate cause of that fixture's superior output; the visual-critique-driven repair was. R1/R3/R6 argue the doc gap is decisive. **These are not contradictory — they operate on different mechanisms and different timelines:**
- The **doc/block/scale gap (RC #1, #2)** determines *iteration-1 quality* — whether the first draft has good art-direction priors, scales, and vetted block proportions. This is where 91-vs-26 bites.
- The **visual-critic gap (RC #3)** determines *whether iterations 2-N can repair* a mediocre draft toward good. Brilliant's fixture 005 got gallery-grade via critique-driven repair even with the same 8 snippets.

So: **#1/#2 make the first draft good; #3 makes a mediocre draft recoverable.** R9's smoking-gun nuance reinforces this — for the failed A4 runs the right grammar docs *existed in our 26-doc set but weren't retrieved* (retrieval ranked a "Reverse-Engineering Report" and "Permanent Memory" above the DSL grammar docs that say `text.md:29` "There is no `valign`"). So **retrieval/ranking is a fourth, orthogonal lever** — having the doc isn't enough if it isn't surfaced.

---

## 3. Separating composition quality from the loop bug (explicit)

| | Composition-quality gap (RC #1-3) | Loop bug (R9 §A) |
|---|---|---|
| **Symptom** | Finished drafts have bad spacing/density/hierarchy (R10 rows 1-7) | All 5 runs never finish — `max_iterations_reached` (R9) |
| **Proven by** | `run_92039` compiled clean, *still rejected* for 300pt dead space (R9 §5-B) | ~5/8 active diagnostics unfixable in repair surface; cluster atomic-rejects correct patch (R9 §3) |
| **Layer** | Knowledge (blocks, scales, priors) + DSL grammar + visual critic | Runtime loop mechanics (`loop.py`) + repair-surface scope |
| **Fix moves the needle on** | *How good* a finished design is | *Whether* a design finishes at all |
| **If you fix only this** | Runs still die in Phase A; user sees nothing | Runs finish but look amateur (rows 1-7 fully exposed) |

**They compound (R6 §synthesis, R2 inference):** weak composition guidance → improvised off-scale sizes → bounds/fit diagnostics (`LUMV0801/0903/0810`) → surgical repair surface can't clear them → `max_iterations_reached`. Better composition knowledge would *also reduce* the diagnostic load the broken loop chokes on. But the loop bug must be fixed independently — it has unfixable codes (`LUMV0800` A4 0.11pt overflow, font-embed `LUMB0613/0614`) that no amount of composition skill clears.

---

## 4. The 5 highest-leverage changes for COMPOSITION quality

Scoped to **composition quality**, not the loop bug (which R9 covers). Ranked by impact-per-effort.

### 1. Ship a vetted block catalog with proportions baked as tokens *(RC #1 — biggest lever)*
Port Brilliant's `design/blocks/*` model: hero, header, footer, card, stat tile, CTA, form, nav, modal — each with internal `g/pad/s/rd`, type roles, and color roles **pre-decided**. The agent's job becomes *assemble + tune vetted blocks* (R3 §2), not *invent proportions*. Kills the improvised-padding, wrong-card-density, mis-sized-CTA family at the source (R10 rows 1,2,6). *Effort: high. Impact: highest — this is the layer we entirely lack.*

### 2. Add a numeric spacing + type scale and make off-scale values illegal *(RC #2)*
Adopt Brilliant's `spacing: tshirt(number(4,32,linear()))` and a `font.size` scale; give `$space.*` real values; add the rules "heading 150-200% of body, anchor 2-3× body, hierarchy via Size+Weight+Color together" (R1 §2). Then **reject bare numerics in `g()/pad()/font-size`** so the agent must pick a rung (R2 §4.1). Fixes off-rhythm spacing and the noisy `13/15/17/22/36` scale (R10 rows 1,2). *Effort: medium (knowledge) + medium (grammar enforcement). Impact: very high — removes the #1 amateur tell by construction.*

### 3. Wire a visual critic into the repair loop *(RC #3 — the recoverability unlock)*
Our `final.json` already has a `critique` slot but it's `kind:"preflight"`, `summary:None` (R10 §5.1). Render the preview, run a visual critique that emits `visual_balance`/alignment/hierarchy issues **with pixel coords + suggested repairs**, and feed it into `repair_request.exact_feedback` — exactly the format Brilliant's fixture proves (R10 §4). This is what lets iterations 2-N fix mixed alignment, dead zones, and flat hierarchy (R10 rows 3,4,7) that preflight can never name. *Effort: medium. Impact: very high — fixes 3 visual defects at once and makes mediocre drafts recoverable.*

### 4. Ship art-direction priors: anchor/dominance, whitespace budget, anti-cliché, eyebrow tier *(RC #1/#2 knowledge)*
Port Brilliant's `foundations.md` judgment layer: "one dominant region per screen, squint test," "60-70% whitespace then remove," "surfaces over boxes, asymmetry over grid-sameness," the anti-cliché list, and the eyebrow/kicker convention (R1 §1, R10 §2). These are the between-element rules our prose-only corpus lacks entirely (R6 §1). Fixes flat hierarchy, leftover whitespace, missing eyebrow (R10 rows 4,7). *Effort: low-medium (mostly authoring docs). Impact: high — improves iteration-1 quality directly.*

### 5. Let repair change layout strategy; add a grid/bento primitive *(RC #5 in table — DSL + loop)*
Two coupled changes: (a) lift the repair restriction that forbids `#node al(...)` / `#node wrap(...)` (`layout-cluster-repair.md:71-73`) so a badly-laid-out region can be *re-laid-out*; (b) add nested-auto-layout grid/bento patterns (currently Future Scaffold, `layout-recipes.md:131`) using `fill:N` "no pixel math" like Brilliant (R2 §2). This is what lets the agent *abandon* an overflowing 3-card grid for a single-column/inline list (Brilliant fixture 005, R10 §2) instead of shuffling wrap flags forever (R10 row 5). *Effort: medium-high. Impact: high — fixes the layout-strategy lock-in and a whole class of overflow defects.*

**Honorable mention (orthogonal, cheap, high-value): fix retrieval/ranking.** R9's smoking gun: our DSL grammar/text docs *exist in the 26-doc set but weren't retrieved* — the ranker surfaced a "Reverse-Engineering Report" over the grammar doc that says "There is no `valign`," causing iter-1 hallucinations (`va`, `divider`). Boosting design-knowledge docs (blocks, scales, foundations) in retrieval amplifies changes 1-2-4 at near-zero authoring cost.

---

## 5. Bottom line for the synthesis layer

- **The core pain is real and has a precise locus:** composition is a *between-element / whole-page* property (spacing rhythm, density, hierarchy, balance, alignment spine). Brilliant encodes it in three layers — **token grammar (R2), block catalog (R3), visual critic (R10)** — plus an art-direction judgment layer (R1). We have **none of the three** and only prose adjectives for the fourth (R6). That is why good components compose badly.
- **It is separable from the loop bug.** R9 proves a clean-compiling Lumen draft still loses (300pt dead space). Fix the loop and runs finish; fix composition and finished runs are good. Both are required.
- **Ranked root causes for composition:** (1) no block catalog, (2) no enforced spacing/type scale, (3) blind repair loop, (4) no art-direction priors, with retrieval/ranking as an orthogonal amplifier.
- **Decisive single statement:** *We taught the agent grammar + repair discipline, not composition — so it improvises proportions off an unconstrained DSL and is then given only compiler errors to judge the result by. Brilliant pre-decided the proportions, made off-rhythm values unrepresentable, and let the agent see the rendered page.*

**Report file (persisted):** `/Users/aryankeshri/conductor/workspaces/clue-design/havana/.context/brilliant-audit/S4-professional-composition-gap.md`
