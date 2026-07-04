# R9 — Trace Forensics: Why Lumen's 5 Runs All Failed

**Scope:** Forensic teardown of the 5 failed Lumen agent runs in
`/Users/aryankeshri/Documents/brilliant-design/agents-design-recipes-quality-v0/.lumen-runs`.
All 5 ended `status="failed"`, `stop_reason="max_iterations_reached"`,
`summary="Maximum Phase A repair iterations reached."`

**Headline finding:** There are TWO independent failures stacked on top of each
other. (A) A **convergence/loop bug** — a malformed repair gate guarantees the
agent can never clear preflight, so every run burns its 3-cycle budget and is
killed. (B) An **intrinsic composition-quality problem** — even the first,
cleanest drafts have measurable spacing/density/hierarchy defects (300pt dead
zones, edge-clipped text, mis-tuned flex weights). The loop bug means the user
never even sees draft #1; the quality problem means draft #1 would not match
Brilliant anyway.

The runtime code that produces these traces lives in
`apps/agent_runtime/lumen_deepagent/loop.py` (I executed its real gate logic
against the recorded payloads to confirm the deadlock — see §3).

---

## Run roster

| Run id (short) | Artifact | Canvas authored | Numbered iters | Last DSL state |
|---|---|---|---|---|
| `run_92039c…` | LinkedIn 1:1 ad | `size(1080,1080,px)` | 001,002,003 | shrank 29→4→0 lines |
| `run_c0feb…` | Landscape flyer | `size(1200,628,px)` | 001,002,003 | shrank 22→15→3 lines |
| `run_e2ca…` | A4 appointment card | `preset(a4,portrait)` | 001,002 | 38→38 lines (repair rejected) |
| `run_f444…` | A4 appointment card | `preset(a4,portrait)` | 001,002,003 | 23→23→10 lines |
| `run_f58a…` | A4 appointment card | `preset(a4,portrait)` | 001,002 | 41→41 lines (repair rejected) |

All 5 prompts ship the **same stale editor context**: an A4 *portrait letter*
scene (`page_a4`, single `node_contact_name`, `slot contact.full_name`) even
for the 1:1 LinkedIn ad and the landscape flyer. The agent correctly ignores it
and authors a fresh page, but this mismatch is the source of several persistent
`LUMV0509` slot warnings (the platform pre-registers 8 demo slots regardless of
what the design uses).

---

## 1. What the agent actually authored (DSL)

The first draft of every run is **layout-driven, not absolute-coordinate** —
this is good and worth stating plainly: the agent uses auto-layout
(`al(v|h, x(), y(), g(), pad())`), `s(fill,hug)` sizing, `wrap_text`/`max_lines`,
and nested frames. Spacing is **token-ish / hand-chosen** (gaps like
`g(28)`, `g(24)`, paddings like `pad(56,48,56,48)`), not computed from a spacing
scale, and not recomputed when content changes.

### `run_c0feb` (landscape flyer) — iteration 001 (representative)
24 nodes, fully auto-layout:
```
page flyer_landscape size(1200,628,px)
  artboard al(v,x(s),g(0),pad(0)) p(0,0) s(fill,fill) fill(#F0F6FA) clip(true)
    header_bar fr p(0,0) s(fill,72) fill(#0B3D6B)
      logo_text text "Insight Health AI" p(48,20) s(400,hug) font("Inter",22,700,left) ...
    main_content al(v,x(s),g(28),pad(56,48,56,48)) p(0,0) s(fill,fill)
      headline text "AI-Powered Patient Communication..." s(fill,hug) font("Inter",36,800,left) ... slot(campaign.headline)
      body text "..." s(720,hug) font("Inter",17,400,left) ...
      benefits_row al(h,x(s),g(24),pad(0)) s(fill,hug)
        benefit_1 al(v,x(s),g(8),pad(20)) s(fill,hug) fill(#ffffff) rd(12) ...
        ... (benefit_2, benefit_3)
      cta_row al(h,x(c),y(c)) ...
        cta_button al(h,x(c),y(c),pad(16,48)) fill(#1A8FE3) rd(8)
```
**Defect already present:** the three benefit cards are `s(fill,hug)` inside a
horizontal row with `g(24)`, but the icon `b1_icon`/`b2_icon`/`b3_icon` are
non-wrapping `s(hug,hug)` glyphs that overflow, and `benefits_row` overflows the
parent (`LUMV0801`). The row of three cards is too wide for the 1200px canvas
minus margins → cascade of overflow errors.

### `run_e2ca` / `run_f58a` (A4 card) — iteration 001
38–41 nodes (`run_f58a` is the densest). **Layout-driven**, well-structured
header/body/details-card/instruction/routing/cta/footer. But it **fails to
compile at all**:
```
logo_letter text "H" p(0,0) s(fill,fill) font("Inter",24,700,center) fill(#1B3A5C) va(center)
```
`va(center)` → **`LUMD0212 unknown property va`** (compile halts, 0 ops applied).
`run_f444` iteration 001 fails differently:
```
divider_top p(0,0) s(fill,2) fill(#d4dbe6) rd(1)
```
→ **`LUMD0206 unknown element kind in line: divider_top …`** (`divider` is not a
node kind; valid kinds are `frame/fr, group/gr, autolayout/al, rect/r,
ellipse/e, line/l, text/t, image/img, vector/v, instance`).

### DSL "shrinkage" across iterations (the visible symptom of the loop bug)
The DSL gets **smaller** every iteration, because iters 2/3 are not full
re-emissions — they are **modify-line patches** (`#node prop(...)`):

`run_c0feb` iter 003 (the *entire* file):
```
#b3_icon s(340,hug) wrap_text(true) max_lines(2)
#cta_label s(hug,hug)
#headline s(fill,hug) wrap_text(true) max_lines(3)
#body s(fill,hug) wrap_text(true) max_lines(5)
```
`run_f444` iter 003 is a clean modify-only patch (`#artboard s(fill,fill)`,
`#appt_datetime max_lines(2)`, `#badge_label wrap_text(true) s(hug,hug)`, …) —
**syntactically correct surgical repair** that still does not clear the errors
(see §2/§3).

**Inference:** spacing/density is hand-computed per node, never derived from a
shared scale or re-flowed against real content length. When one node's size
changes, neighbors don't adapt, so each patch fixes one overflow and creates
another → whack-a-mole (quantified in §2).

---

## 2. Preflight diagnostics — full list + persistence table

Diagnostic codes observed, with semantics (cross-checked against
`apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/diagnostics.md`):

| Code | Sev | Meaning | Author-fixable? |
|---|---|---|---|
| `LUMD0212` | error (compile) | unknown property (`va`/`valign`) | Yes — delete it / use `y(c)` on parent |
| `LUMD0206` | error (compile) | unknown element kind (`divider`) | Yes — use `rect`/`r`/`line` |
| `LUMV0509` | warning | text slot has **no fit-validation fixtures** | **Only via `#slot:key sample(...) worst_case(...)`** — a slot directive |
| `LUMV0810` | error | slot fixture **overflows** its text node | Box fixes OR set slot overflow policy `shrink_font`/`wrap` |
| `LUMV0800` | error | node `artboard` exceeds **exportable bounds** for page | **Structurally near-unfixable** (see below) |
| `LUMV0801` | warn/err | node exceeds **parent bounds** | Yes — resize/wrap/relayout |
| `LUMV0902` | error | non-wrapping text overflows **horizontally** | Yes — `wrap_text(true)` / smaller font / wider box |
| `LUMV0903` | error | text exceeds **available height** | Yes — taller box / fewer lines / smaller font |
| `LUMV0904` | error | text exceeds **`max_lines`** | Yes — raise `max_lines` / shrink text |
| `LUMB0613` | warning | font asset not marked **embeddable** | **No** — asset/brand-kit property, no DSL surface |
| `LUMB0614` | warning | font asset not **subsettable** for PDF | **No** — same |

### Persistence (counts per iteration; `x` = compile failed, no preflight)

```
run_92039 (LinkedIn)    iters 001→002→003
  LUMB0613   1 → 1 → 1     (NEVER clears, warning)
  LUMB0614   1 → 1 → 1     (NEVER clears, warning)
  LUMV0902   4 → 0 → 0     (cleared)
  LUMV0903   1 → 1 → 0     (cleared by iter 3)
  → iter 003 has_errors=False; killed anyway by critic rejection (see §5)

run_c0feb (flyer)       iters 001→002→003
  LUMB0613   1 → 1 → 1     (NEVER)
  LUMB0614   1 → 1 → 1     (NEVER)
  LUMV0509   2 → 2 → 2     (NEVER — unfixable in surface)
  LUMV0810   2 → 2 → 2     (NEVER — unfixable in surface)
  LUMV0801   1 → 0 → 1     (RE-APPEARS — whack-a-mole)
  LUMV0902   3 → 1 → 0
  LUMV0903   3 → 1 → 1     (RE-APPEARS on cta_label)

run_f444 (A4)           iters 001(x)→002→003
  LUMV0509   x → 9 → 9     (NEVER)
  LUMV0810   x → 4 → 4     (NEVER)
  LUMV0800   x → 1 → 1     (NEVER — artboard bounds)
  LUMV0801   x → 1 → 1     (NEVER — benefit_text in benefit_row)
  LUMV0902   x → 2 → 0
  LUMV0903   x → 0 → 3     (RE-APPEARS — 0 then 3: whack-a-mole)
  LUMV0904   x → 1 → 0

run_e2ca (A4)           iters 001(x)→002 [repair rejected, run ends]
  LUMV0509 8, LUMV0810 4, LUMV0800 1, LUMV0801 4, LUMV0903 1, LUMV0904 6, LUMB0613/4

run_f58a (A4)           iters 001(x)→002 [repair rejected, run ends]
  LUMV0904 14 (!), LUMV0801 5, LUMV0810 3, LUMV0509 3, LUMV0800 1, LUMB0613/4
```

### The codes that DOOM every run (persist / unfixable in the repair surface)

1. **`LUMB0613` + `LUMB0614`** (every iteration of every run). These are
   font-asset/brand-kit export flags. There is **no DSL node-modify syntax** to
   set them. They are warnings, but they keep `has_errors`-adjacent noise in the
   feedback and never disappear. (Inference: the platform default brand kit ships
   a font that is not flagged embeddable/subsettable; the agent can't change that.)

2. **`LUMV0509` + `LUMV0810`** (every A4 run, every flyer iteration). LUMV0509
   ("no fit-validation fixtures") is fixable per the docs only by
   `#slot:key sample("…") worst_case("…")` — a **slot directive**. But the
   layout-cluster repair gate (§3) hard-rejects any line beginning with `slot:`.
   So in a layout-cluster repair, **LUMV0509/LUMV0810 are structurally
   unsatisfiable**. The agent is told "fix this" and given a surface in which it
   cannot.

3. **`LUMV0800`** ("artboard exceeds exportable bounds", every A4 run). A4
   portrait canonicalizes (in `compile.json` → `add_page`) to
   **595.2755905511812 × 841.8897637795276 pt**. The artboard authored as
   `s(fill,fill)` resolves its height to **842 pt** (ceil), which is ~0.11 pt
   over the page's 841.89 pt → permanent overflow error. The repair gate even
   *forces* `s(fill,fill)` on the root (numeric sizes are rejected), so the agent
   **cannot** author the one value that would avoid the rounding overflow. This
   is a runtime layout-resolution bug, not a model mistake; the director's own
   iter-2 rationale in `run_f444` calls it "a known layout resolution issue."

**`LUMV0902/0903/0904` are the whack-a-mole set** — genuinely fixable, and the
agent does clear individual instances, but fixing one node's height/lines pushes
a sibling over (`LUMV0903` on `cta_label` goes 0→3 in `run_f444`; `LUMV0801`
flips 1→0→1 in `run_c0feb`) because nothing reflows holistically.

---

## 3. The repair loop and the exact deadlock

Event sequence per run (from `trace.jsonl`):
`run_started → knowledge_loaded → (director_decision) → dsl_block_requested →
dsl_block_produced → dsl_compiled → [preflight_completed → preview_exported] →
edit_surface_recommended → repair_requested → …repeat… → run_finalized`.

**Iteration budget:** `loop.py:171` runs `for _ in range(max_iterations)`;
`config.py:23` defaults `LUMEN_AGENT_MAX_ITERATIONS=5`, but every run does
exactly **3** `dsl_block_requested` cycles before `max_iterations_reached`
(effective Phase-A cap = 3). 3 cycles is far too few to clear 8–28 diagnostics
by single-node patching.

**The structured repair surface is broken in two ways:**

(a) **`recommend_edit_surface` always returns the same canned answer.** Every
`edit_surface_recommended` event has `reason="conservative_phase_a_rule"`
(`tools.py:1093`) and `recommendation` ∈ {`external_planner`, `structured_ops`}
— never a content-aware suggestion. The actual diagnostics are not handed to the
planner as structured data: in every `repair_request.json`,
`current_diagnostics` is `null` and the real diagnostics are only smuggled inside
a stringified `exact_feedback` blob (59–102 `"code"` substrings). The planner
must re-parse a JSON string instead of receiving typed diagnostics.

(b) **The layout-cluster repair gate rejects the planner's own correct fix.**
This is THE deadlock, and I confirmed it by **executing the real gate logic**
(`is_layout_cluster_dsl` / `layout_cluster_modify_syntax_is_supported` /
`layout_cluster_allowed_node_ids` from `loop.py:1388-1456`) against the
recorded `rejected_source` in `run_e2ca`.

In `run_e2ca` iter 2 the planner produced a complete, reasonable layout patch
(`#artboard s(fill,fill) p(0,0) pad(36) g(20) clip(true)`, plus per-node
`s(fill,hug) max_lines wrap_text` lines for the whole page). The runtime emitted
`layout_cluster_repair_rejected` and the critique:

> "Your previous layout_cluster repair was REJECTED and NOT applied because it
> edited outside the allowed cluster or attempted to re-author the page. Emit
> only #modify lines for allowed page/node IDs."

**Why it was rejected (line-by-line, reproduced from the real gate):** the
cluster's `descendant_node_ids` contained only **20 of the ~38 nodes** in the
scene. The planner had to touch nodes that carry errors but are **not in the
allowed set** — `appt_label` (has `LUMV0904`!), `divider`, `patient_row`,
`cta_button`, `cta_text`, `footer_text`. The gate is **atomic**: any single
out-of-cluster `#ref` makes `is_layout_cluster_dsl` return `False`, the WHOLE
block is dropped, **0 operations apply**, and the scene is left untouched. So:

- Iter 1 (A4): wasted on `LUMD0212`/`LUMD0206` compile error.
- Iter 2: compiles, preflight returns 20–28 diagnostics spanning the whole page;
  director picks `layout_cluster_rewrite`; planner writes the obvious whole-page
  fix; **gate rejects it because the cluster definition is too small to contain
  the fix**; nothing applies.
- Iter 3 (when reached): same situation, same rejection (or the budget is
  already gone, as in `run_e2ca`/`run_f58a` which die at iter 2).

The cluster also bans the only tools that would clear the dominant codes:
`UNSUPPORTED_LAYOUT_CLUSTER_MODIFY_CALL_RE` (`loop.py:771`) rejects any `al(...)`
or `wrap(...)` (so you can't change a frame's auto-layout direction or enable
wrapping in a cluster repair), and any `slot:`/`asset:`/`document` ref is
rejected (so `LUMV0509`/`LUMV0810`/`LUMB0613`/`LUMB0614` can never be addressed).

**Net deadlock:** the agent is asked to fix a page-wide set of errors through a
surface that (i) only allows editing a hand-picked 20-node subset, (ii) atomic-
rejects the whole patch if it strays outside that subset, (iii) forbids the
`al()`/`wrap()`/`slot:` operations several of the errors require, and (iv) only
grants 3 cycles. Convergence is impossible by construction.

---

## 4. Concrete layout / spacing / density defects (DSL + compile + preview)

Confirmed against rendered `preview.png`:

**`run_92039` LinkedIn ad (preview verified):**
- **~300 pt vertical dead zone** in the middle third. Cause:
  `root al(v, …, y(sb))` with `top_section al(v,…) s(fill,fill(3))` containing a
  `spacer_top … s(fill,fill(1))`. The fractional fill weights over-allocate
  empty space; the headline/subhead cluster floats at top, stats sit low, huge
  void between. The critic (`iterations/003/critique.json`) independently
  measured it: *"Approximately 300pt of dead empty space sits between the subhead
  (ending ~y 395) and the divider/stats section (starting ~y 691)."*
- **Mixed alignment:** `headline`/CTA are center-anchored, `subhead` renders
  visually centered but the critic flags axis inconsistency; subhead is small
  (28px/400) against a 64px/800 headline with a giant gap → weak mid-page
  hierarchy.

**`run_f444` A4 card iter 003 (preview verified):**
- **Badge text wraps to "Appointmen / t"** — `appt_badge` is `s(hug,hug)` but the
  inner `badge_label` is `s(hug,hug)` non-wrapping → `LUMV0902`; the box hugged
  too tight.
- **"Book a Demo" wraps to "Book a / Demo"** inside the CTA button (`LUMV0903`
  on `cta_label`) — button padding `pad(16,52)` + hug sizing under-allocated
  width after the iter-3 `max_lines` bump.
- **Benefit text clipped at the right edge** ("…directs you to the right c…") —
  `benefit_text` computed width 636 pt inside a 499 pt `benefit_row`
  (`LUMV0801`); the row is `al(h)` with an icon + fill text and never fits.
- **"10:30 AM" wraps** off the datetime line (`LUMV0904`/`LUMV0810`).
- **Large empty bottom band** from `spacer fr s(fill,fill)` pushing the footer
  down — density is bottom-light.

**`run_c0feb` flyer:** three `s(fill,hug)` benefit cards in one `al(h)` row
overflow the 1200 px canvas (`benefits_row` `LUMV0801`), icons overflow
horizontally (`LUMV0902`), and the slot fixtures (real-length copy) overflow the
headline/body boxes (`LUMV0810`) — i.e. the layout is sized to the *placeholder*
text, not to worst-case content.

**Cross-cutting density/spacing root cause:** sizes are authored for the literal
sample string, gaps are hand-picked constants, and there is no holistic reflow.
Brilliant-quality output requires content-aware sizing + a spacing system; Lumen
has neither in the authoring path.

---

## 5. Root cause: loop bug (A) vs composition quality (B)

### (A) Convergence / loop bug — the proximate cause of all 5 failures
- **3-cycle Phase-A budget** (`loop.py:171` + effective cap of 3) vs 8–28
  diagnostics. Too small even if every patch worked.
- **Wasted cycle on a hallucinated grammar token.** Iter 1 of all 3 A4 runs
  fails to compile: `va(center)` (`LUMD0212`) and `divider` (`LUMD0206`). The
  doc `knowledge/lumen-dsl/text.md:29` literally says *"There is no `valign`"*
  and `grammar.md:45` lists the legal kinds — but **those docs were not among the
  8 retrieved snippets** (retrieval surfaced "Brilliant — Reverse-Engineering
  Report", "ABM Design Engine - Temporary Technical Spec Draft", and "Permanent
  Memory" with the highest scores instead). The model guessed plausible-but-wrong
  syntax because the grammar reference wasn't in context.
- **The layout-cluster repair gate atomic-rejects the planner's correct patch**
  because `cluster.descendant_node_ids` is an incomplete subset of the page
  (§3). I reproduced the rejection deterministically from the real code: 6 of 18
  emitted `#refs` were "NOT in allowed cluster nodes" → whole block dropped, 0
  ops applied, scene unchanged → identical diagnostics next cycle → budget
  exhausted.
- **Unfixable-by-construction codes** stay forever: `LUMB0613/0614` (no DSL
  surface), `LUMV0509/0810` (need `#slot:` directives the cluster gate bans),
  `LUMV0800` (0.11 pt A4 rounding overflow the runtime forces via mandatory
  `s(fill,fill)`).
- **Diagnostics aren't passed as structured data** to the repair planner
  (`current_diagnostics: null` in every `repair_request.json`).

Quantification: of the persistent error codes across the A4 runs,
**`LUMV0509`, `LUMV0810`, `LUMV0800`, `LUMB0613`, `LUMB0614` (5 of the ~8 active
codes) are not fixable in the offered repair surface at all.** Even a perfect
model cannot clear them within Phase A. This alone forces `max_iterations_reached`
on every A4 run.

### (B) Intrinsic composition quality — would fail review even without (A)
The only run that reached the visual critic (`run_92039`, iter 3 had
`has_errors=False`) was **still rejected** (`critique.accepted=false`) for purely
compositional reasons: 300 pt dead zone, mid-page hierarchy collapse, alignment
inconsistency, footer near the clip edge. So the agent's *clean-compiling* output
is not Brilliant-grade. The defects trace to:
- spacing as hand-picked constants, not a scale;
- sizing fit to placeholder text, not worst-case content (hence `LUMV0810`);
- mis-tuned flex weights (`fill(3)`/`fill(1)`) creating voids;
- horizontal rows of equal cards that don't fit the canvas.

The critic even cites a code (`LUME0205`, "hand-placed not auto-layout") that
**does not appear in any actual preflight** (0 occurrences in
`preview_bundle`/`preflight.json`) — i.e. the critic's prose references a
diagnostic the pipeline doesn't emit, a minor reliability smell, though its
*quantified* findings (the 300 pt void) are real and visible in the PNG.

### Bottom line
- **(A) is the proximate killer of all 5 runs and is a pure runtime/loop bug**:
  fix the cluster definition (make it whole-page or non-atomic), allow
  `#slot:`/`al()`/`wrap()` edits in repair, raise the 3-cycle cap, pass typed
  diagnostics, special-case the A4 0.11 pt `LUMV0800` rounding, and put the DSL
  **grammar/text** docs into the retrieved context so iter-1 stops hallucinating
  `va`/`divider`.
- **(B) is the deeper reason Lumen ≠ Brilliant even after (A)**: the authoring
  layer lacks content-aware sizing and a spacing/hierarchy system, so first
  drafts have dead zones, clipped text, and weak hierarchy. This is where the
  91-vs-19 knowledge-doc gap bites — but note the relevant grammar docs *exist*
  here and simply weren't *retrieved*, so retrieval/ranking is itself part of the
  problem, not only doc count.

---

### Evidence index (file paths)
- DSL drafts: `…/.lumen-runs/run_*/iterations/00N/dsl.lumen`
- Compile errors: `…/iterations/001/compile.json` (`LUMD0212`/`LUMD0206`)
- Diagnostics: `…/iterations/00N/preflight.json`
- Deadlock proof: `…/run_e2ca…/trace.jsonl` event `layout_cluster_repair_rejected`
  + `run_finalized.critique` (kind `layout_cluster_violation`)
- Critic quality findings: `…/run_92039…/iterations/003/critique.json`
- Repair-request structure (empty `current_diagnostics`): `…/iterations/00N/repair_request.json`
- Gate code: `apps/agent_runtime/lumen_deepagent/loop.py:171, 261-283, 1388-1456, 771-774`
- Budget config: `apps/agent_runtime/lumen_deepagent/config.py:23`
- Canned recommendation: `apps/agent_runtime/lumen_deepagent/tools.py:1093`
- Grammar docs not retrieved: `apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/{text.md:29, grammar.md:45, diagnostics.md:47-48}`
