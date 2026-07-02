# R8 — Our Lumen Agent Runtime: Why Compositions Are Low-Quality and Why All 5 Runs Deadlocked

Scope: the `lumen_deepagent` runtime under
`apps/agent_runtime/lumen_deepagent/`. This report explains, in code terms, (1)
the agent loop and the exact deadlock mechanism that produced
`status="failed", stop_reason="max_iterations_reached"` on all 5 runs, (2) what
knowledge actually reaches the model, (3) what the system prompts do and do not
enforce, (4) which diagnostics can NEVER be cleared and therefore loop forever,
and (5) the architectural gaps vs a planner/builder/critic + layout-engine
design.

Repo paths are relative to
`/Users/aryankeshri/conductor/workspaces/clue-design/havana/`.

---

## 0. TL;DR — the causal chain

1. **`max_iterations` defaults to 5** (`config.py:23`,
   `LUMEN_AGENT_MAX_ITERATIONS="5"`). The loop in `loop.py:171`
   (`for _ in range(self.tools.config.max_iterations)`) gets **5 total
   attempts** to clear EVERY gate — compile, preflight, AND visual critique —
   and `accepted`. That is the budget for the entire run, not per-stage.

2. **Phase A is a single linear gauntlet, not a planner/builder/critic.** Each
   iteration must pass compile → preflight → export → critic, and a failure at
   ANY stage consumes an iteration and `continue`s. Realistic first drafts
   produce *multiple simultaneous* preflight errors (see the test fixture in
   §1.4: 1×`LUMV0800`, 2×`LUMV0801`, 3×`LUMV0902`, 1×`LUMV0810`, …). The loop
   only ever feeds back **one target** (`first_diagnostic_target`,
   `loop.py:443`) and forces a **surgical / single-cluster** repair. So each
   iteration nibbles at one node while 6+ errors remain.

3. **The repair surface is deliberately crippled.** When preflight reports
   layout errors the loop routes to a `layout_cluster` repair (`loop.py:451-457`,
   `classify_diagnostics` → `LAYOUT_CLUSTER_CODES = {LUMV0800, LUMV0801,
   LUMV0803}` at `loop.py:751`) and then *mechanically rejects* any DSL block
   that isn't a tiny bounded modify (`is_layout_cluster_dsl`, `loop.py:1361`;
   `is_surgical_dsl`, `loop.py:1340`). A rejected block does not even reach the
   compiler — it `continue`s and **burns an iteration** (`loop.py:267-302`)
   without improving the scene.

4. **At least one fed-back diagnostic class can never be cleared by the
   author.** `LUMV0509` ("text slot has no fit-validation fixtures") requires
   slot **fixtures** (`sample`/`worst_case`). `AGENT.md` §2 declares fixtures
   live in **scene/document metadata, NEVER in DSL**, yet the author can ONLY
   emit DSL (`prompts.py:66`, "Return Lumen DSL only"). The loop has no tool to
   write metadata fixtures. So a run that surfaces `LUMV0509` (a warning) plus
   real layout errors keeps the scene in `has_errors` while never being able to
   produce the fixture — the iterations run out. (See §4 for the exact
   non-clearable set.)

5. **Result:** 5 iterations are exhausted clearing one-node-at-a-time geometry
   while new overflow appears, blocks get rejected for not being "surgical
   enough," and the critic never gets a clean enough draft to `accept`. The loop
   falls out of the `for` at `loop.py:636-644` →
   `StopReason.max_iterations_reached`, "Maximum Phase A repair iterations
   reached." The best-ranked (still-imperfect) draft is restored to canvas
   (`_restore_best_scene`, `loop.py:684`) — which is why "individual components
   look fine" but the *composition* (spacing/density/hierarchy) is bad: the run
   ends mid-repair on a draft that never satisfied the quality gates.

6. **Even the happy path can't produce Brilliant-quality composition**, because
   there is **no layout engine** in our runtime. Spacing/gaps/padding are
   hand-emitted by the LLM as `g()`/`pad()` literals in DSL text; the runtime
   never computes spacing. Brilliant ships a bespoke Flexbox-equivalent
   `AutoLayoutExtension` flex engine that computes absolute positions
   (R5/`Brilliant-Reverse-Engineering-Report.md:434-465`). We have the *grammar*
   for `al(...)` but no engine that guarantees balanced output. (Inference,
   well-supported.)

---

## 1. The agent loop, precisely

The orchestrator is `LumenQualityLoop.run()` (`loop.py:161-644`). There are two
director implementations: a deterministic `HeuristicAgentDirector`
(`loop.py:56-119`, used by tests/non-provider) and the LLM
`LangChainAgentDirector` (`providers.py:33-62`). The loop body is identical; only
`director.decide()` differs.

### 1.1 The single counted loop and its cap

```python
# loop.py:171
for _ in range(self.tools.config.max_iterations):
```

`max_iterations` is **5** by default (`config.py:23`). There is exactly one
`for` loop. Every gate failure (`compile`, `preflight`, surgical-rejection,
layout-cluster-rejection) hits `continue` and consumes one of those 5 turns.
Hard tool failures (`export` invalid, critic provider error, preview dims wrong)
**early-return** as `failed` rather than retry (`loop.py:512-558`, `575-588`).
Only `critique.accepted` (`loop.py:594`) or a director `accept`/`stop_with_gap`
exit cleanly.

### 1.2 What happens inside one iteration (the gauntlet)

1. `curated_context(...)` rebuilds a bounded situation report
   (`loop.py:172`, `tools.py:1211`).
2. `director.decide(full_context=...)` picks an `AgentActionMode`
   (`loop.py:177`). Modes: `new_artifact`, `full_page_rewrite`,
   `replace_artboard_subtree`, `layout_cluster_rewrite`, `targeted_patch`,
   `accept`, `stop_with_gap` (`schemas.py:160-167`).
3. `accept` → finalize accepted (`loop.py:192-201`). `stop_with_gap` → finalize
   `unsupported_capability` (`loop.py:202-212`).
4. Build `AuthoringBlockRequest` and call `author.write_block(...)`
   (`loop.py:214-239`).
5. **Pre-compile enforcement gates** (`loop.py:261-302`):
   - If prior feedback is `layout_cluster` and director did NOT authorize a
     structural rewrite and the block is not valid cluster-DSL
     (`is_layout_cluster_dsl`) → push `layout_cluster_violation_feedback`,
     `continue` (iteration burned, scene untouched).
   - If prior feedback is `surgical_repair` and the block is not modify-only
     (`is_surgical_dsl`) → push `surgical_violation_feedback`, `continue`
     (iteration burned).
6. `compile_dsl_block(source)` (`loop.py:316`). If
   `tool_has_blocking_failure(compile_summary)` (`loop.py:331`,
   `loop.py:1483`: status error / validation_errors / any diagnostic severity
   in `{error, blocker}`) → classify, build repair feedback, `continue`
   (`loop.py:417`).
7. `preflight_design()` (`loop.py:425`). If
   `tool_has_blocking_failure(...) or preflight_summary.get("has_errors")`
   (`loop.py:431`) → debug-export, classify, build repair feedback, `continue`
   (`loop.py:503`).
8. `export_preview_bundle()` (`loop.py:509`). Blocking failure or dimension
   mismatch → **early return failed** (`loop.py:512-551`), NOT a retry.
9. `get_latest_preview_for_critique()` → `reviewer.review(...)`
   (`loop.py:553-574`). Provider exception → early return `critic_failed`.
10. If `critique.accepted` → finalize accepted (`loop.py:594-605`). Else push
    `visual` feedback, classify, build repair request, fall to next iteration
    (`loop.py:607-634`).

"Phase A repair" = steps 5–10 repeated under the shared 5-iteration budget. The
final fallthrough is:

```python
# loop.py:636-644
self.state.status = "failed"
self.state.stop_reason = StopReason.max_iterations_reached
return self._finalize_failed(
    StopReason.max_iterations_reached.value,
    "Maximum Phase A repair iterations reached.",
    ...
)
```

### 1.3 The STOP / convergence condition

The ONLY clean success is `critique.accepted == True` (`loop.py:594`) or the
director returning `accept`. The reviewer system prompt is explicitly adversarial
("Be strict… A design that compiles is not acceptable if it is clipped,
mis-scaled, off-brand, unreadable, visually unbalanced…", `prompts.py:133-139`).
There is **no partial-credit, no "good enough," no score threshold, no budget
re-allocation.** Convergence requires the draft to satisfy a strict binary critic
within whatever iterations remain after compile/preflight repairs are paid for.

### 1.4 WHY all 5 runs hit `max_iterations_reached` — the deadlock mechanism

The bundled test fixture in
`apps/agent_runtime/tests/test_lumen_deepagent_runtime.py:1769-1820` is a faithful
model of a realistic first-draft preflight result on a dense A4 one-pager. It
contains, simultaneously:

| code | severity | meaning |
|------|----------|---------|
| `LUMV0509` | warning | slot `cta.primary` has no fit-validation fixtures |
| `LUMV0800` | error | node `artboard` exceeds exportable bounds |
| `LUMV0801` | warning | `logo_plus` exceeds parent bounds |
| `LUMV0801` | **error** | `cta_section` exceeds parent bounds |
| `LUMV0902` ×3 | error | non-wrapping text overflows horizontally (3 nodes) |
| `LUMV0810` | error | slot `campaign.headline` fixture overflows |

The loop's response to this set:

- `tool_has_blocking_failure` is True (many `error`s) → enter the preflight
  repair branch (`loop.py:431`).
- `first_diagnostic_target` returns the FIRST error's target only
  (`loop.py:443`, `loop.py:1578`) — i.e. it feeds back **one node** even though
  6+ are broken.
- `classify_diagnostics` sees `LUMV0800 ∈ LAYOUT_CLUSTER_CODES`
  (`loop.py:751`, `loop.py:791`) → returns `repair_class = layout_cluster` with
  a bounded cluster and the strict `LAYOUT_CLUSTER_PROHIBITIONS`
  (`loop.py:722-731`: "do not regenerate the whole scene", etc.).
- The author is now constrained to emit only `#<id> p()/s()/g()/pad()/...`
  modify lines for the diagnosed cluster (`prompts.py:116-127`,
  `LAYOUT_CLUSTER_AUTHORING_CONSTRAINTS` at `loop.py:733-748`).

Now the deadlock dynamics, all visible in code:

1. **Multi-error, single-target feedback.** Six geometry errors, one target per
   iteration. Even if each surgical fix is perfect, the loop cannot clear 6
   errors in ≤5 iterations — and a layout-cluster fix that resizes a parent
   typically *creates new* `LUMV0801` parent-containment errors on descendants
   (the doc itself warns of "a `400pt` child inside a `170pt` card after only
   the parent was resized", `layout-cluster-repair.md:20`). So errors regenerate
   as fast as they're cleared.

2. **Rejection-without-progress burns iterations.** If the author emits anything
   broader than the bounded cluster (very likely, since fixing dense overflow
   *wants* a recompose), `is_layout_cluster_dsl` (`loop.py:1361`) returns False
   and the block is rejected **before compiling** (`loop.py:267-283`). The scene
   is untouched, feedback is re-issued, and a whole iteration is consumed for
   zero net change. The same is true for `is_surgical_dsl` rejections
   (`loop.py:284-302`). Rejected attempts that produce no scene delta are the
   classic infinite-loop fuel — bounded here only by the iteration cap.

3. **Self-reinforcing classification.** Once a repair is marked `layout_cluster`,
   `classify_diagnostics` keeps it `layout_cluster` on the next compile failure
   regardless of code, via the prior-context branch (`loop.py:775-789`: "if
   prior_context repair_class == layout_cluster and any LUMD/LUMA code …").
   There is no de-escalation path, so the author is pinned to the bounded
   modify-only surface for the rest of the run.

4. **A never-clearable warning rides along.** `LUMV0509` (warning) cannot be
   fixed by DSL given AGENT.md's metadata rule (see §4). It does not by itself
   set `has_errors`, but it is in the feedback set and the
   `CONTEXT_OVERFLOW_CODES` digest (`tools.py:59-68`), so the director keeps
   seeing an unresolved fit-fixture signal and the author keeps being told (by
   `create-design` SKILL line 48) to "add `sample`/`worst_case`… avoids
   `LUMV0509`" — an instruction it structurally cannot satisfy through the DSL
   tool path the loop enforces.

5. **No accept off-ramp under pressure.** The critic is strict
   (`prompts.py:133-139`) and only ever runs if preflight is fully clean
   (`loop.py:431` gate must pass first). In a 6-error scene the run usually never
   reaches the critic at all — every one of the 5 iterations is spent in the
   compile/preflight repair branches, then the `for` ends.

Net: the budget is exhausted on geometry whack-a-mole + rejected over-broad
blocks + an unfixable fixture warning, the critic rarely or never accepts, and
the loop exits at `loop.py:637` with `max_iterations_reached`. This matches the
observed `stop_reason` on all 5 runs.

---

## 2. What knowledge actually reaches the model, and when

### 2.1 The loader (`knowledge.py`)

`run()` calls `tools.load_knowledge(user_request)` once at the top
(`loop.py:162`), which calls `read_task_knowledge` (`tools.py:154`,
`knowledge.py:101`). Key facts:

- The candidate pool is **`DEFAULT_KNOWLEDGE_PATHS`** =
  `PRIMARY_KNOWLEDGE_PATHS` (20 docs, `knowledge.py:16-37`) +
  `SECONDARY_KNOWLEDGE_PATHS` (3 reference docs, `knowledge.py:41-45`). That is
  the entire universe the loader can ever surface: **~20 agent docs**.
- On disk there are **26 `.md` files** under `knowledge_docs/`
  (6 skills + 20 knowledge/AGENT docs). Compare to Brilliant's bundle: `find
  brilliant -name '*.md'` = **99 docs** (ground truth; confirms the "~91" figure).
  So our retrievable knowledge is roughly **1/5** of Brilliant's, and the design
  knowledge in particular is thin: `layout-recipes.md` (131 lines),
  `typography-and-composition.md` (68 lines), `artboard-frame-authoring.md`
  (68 lines), `layout-cluster-repair.md` (91 lines). `layout-recipes.md` even
  punts dense composition to a "Future Scaffold" TODO (`layout-recipes.md:122-132`:
  "dense stat/table modules… pagination rules… editorial grid systems").

- **The loader returns at most `limit=8` snippets** (`read_task_knowledge`
  default, `knowledge.py:105`) and each `excerpt` is a 1600-char window
  (`best_excerpt`, `knowledge.py:192`). So even of the ~20 candidate docs, **only
  8 truncated excerpts** are produced.

- **Two missing files silently shrink the pool.**
  `SECONDARY_KNOWLEDGE_PATHS[2]` =
  `reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md` **does not exist**
  on disk (confirmed: `ls` → "No such file"). `read_knowledge` skips missing
  paths (`knowledge.py:79`, `if not path.exists(): continue`), so the loader
  loses a candidate without warning.

- **The DeepAgent `skills` dir is empty.** `factory.py:36` registers
  `skills=["apps/agent_runtime/skills"]`, but `find apps/agent_runtime/skills`
  returns **nothing** — the directory is empty. The real skills live under
  `knowledge_docs/skills/` and are only wired into the *subagents*
  (`prompts.py:159-176`). So the top-level coordinator's skill mount is a dead
  path. (Inference: the coordinator gets no skill files from `factory.py`; only
  knowledge snippets via `load_knowledge`.)

### 2.2 Does the rich knowledge reach the model?

Partially, and weakly:

- The **subagents** (`lumen-dsl-author`, `lumen-visual-reviewer`) DO get full
  SKILL.md files mounted (`prompts.py:159-176`). But in the
  *provider* loop those subagents are bypassed entirely — `LangChainDslAuthor`
  (`providers.py:65-91`) and `LangChainVisualReviewer` (`providers.py:94-148`)
  are flat `model.invoke()` calls with only the static system prompt + the JSON
  context. They do **not** load `create-design`/`repair-design`/`visual-review`
  SKILL.md. The knowledge those subagents are "supposed" to read only arrives if
  it is in the `knowledge` list passed through context.

- What the author actually receives is `AuthoringBlockRequest.knowledge_snippets`
  (`loop.py:217-221`) — the **8 truncated 1600-char excerpts**, further capped to
  `CONTEXT_MAX_KNOWLEDGE = 6` snippets × `CONTEXT_MAX_KNOWLEDGE_EXCERPT = 800`
  chars inside `curated_context` (`tools.py:50-51`, `_capped_knowledge`
  `tools.py:1487`). So in the curated context the model sees **≤6 docs × ≤800
  chars ≈ 4.8 KB of design knowledge total.** That is nowhere near enough to
  encode Brilliant-level composition discipline (spacing scales, density limits,
  hierarchy ratios, grid systems).

Conclusion: the rich knowledge is mostly *not* reaching the model. We ship 1/5
of Brilliant's docs, retrieve ≤8 of them, truncate to 800-char excerpts, and the
provider path skips the SKILL.md mounts entirely.

---

## 3. The system prompts — composition discipline and multimodality

There are four prompts: `COORDINATOR_SYSTEM_PROMPT` (`prompts.py:6-50`),
`DSL_AUTHOR_SYSTEM_PROMPT` (`prompts.py:53-128`), `VISUAL_REVIEWER_SYSTEM_PROMPT`
(`prompts.py:131-145`), and `DIRECTOR_SYSTEM_PROMPT` (`providers.py:14-30`).

### 3.1 Layout/composition discipline: weak and mostly negative

- The author prompt is **dominated by syntax rules and prohibitions**, not
  composition craft. ~75 of its lines are "Hard syntax rules" and "Repair rules"
  (`prompts.py:65-127`): don't re-emit pages, don't duplicate IDs, emit only
  `#modify` lines, don't write `al(...)`/`wrap(...)` in repairs, etc. There is
  **no guidance on spacing scales, vertical rhythm, density budgets, type scale
  ratios, balance, or grid** in any system prompt.
- The closest thing to composition guidance is delegated out: "Read the
  `create-design` skill before authoring" (`prompts.py:54-55`). But (a) in the
  provider path that skill is never loaded (§2.2), and (b) `create-design`
  itself defers dense composition to a future scaffold.
- The coordinator prompt is pure process choreography (15 numbered workflow
  steps, `prompts.py:18-49`) with zero design-quality criteria.
- The reviewer prompt asks for strictness on "visually unbalanced"
  (`prompts.py:137`) but gives **no rubric** — no spacing thresholds, no
  hierarchy definition. It is a vibe check, which both over-rejects (causing the
  loop to churn) and under-specifies (so the author can't target the fix).

So the prompts enforce **DSL legality**, not **design quality**. This is a direct
cause of mediocre composition independent of the deadlock.

### 3.2 Multimodality — is the rendered image fed back?

Yes for PNG, but **the default config never produces a PNG**, so in practice the
loop is likely text-only:

- `preview_image_blocks` (`providers.py:217-230`) and
  `image_blocks_from_context` (`providers.py:233-254`) attach an image block
  **only when `format == "png"`** / only read `png_path`.
- The default `preview_format` is **`"svg"`** (`config.py:24`,
  `LUMEN_AGENT_PREVIEW_FORMAT="svg"`). `export_preview_bundle` exports canonical
  SVG and, only if the critic format differs from svg, a second critic artifact
  (`tools.py:816-820`). With the default svg config, `desired_critic_format ==
  "svg"` so **no PNG is ever generated**.
- Therefore `png_path` is empty, `image_blocks_from_context` returns `[]`
  (`providers.py:241-242`), and the director + author "judge the situation" from
  **SVG text + a structural digest only** — the DIRECTOR_SYSTEM_PROMPT's claim
  "The latest rendered preview is attached as an image" (`providers.py:20`) is
  **false under the default config.**
- The reviewer can read SVG text (`get_latest_preview_for_critique`,
  `tools.py:950-953` returns `svg_text`), but vision-grade pixel review of
  spacing/balance requires the PNG that is never made.

Net: under shipped defaults, the agents reason about **vector source text and a
node digest**, not rendered pixels. Spacing/density/hierarchy problems that are
obvious in a rasterized image are invisible to a text-only critic. (Inference,
strongly supported by config + provider code.)

---

## 4. Diagnostics: generation, feedback, and the never-clearable set

### 4.1 How diagnostics are generated and fed back

- Compile diagnostics come from `compile_dsl_block` (`tools.py:170-275`); a
  pre-check also synthesizes `LUMA0200` if the block re-declares an existing page
  (`tools.py:176-209`, `first_existing_page_declaration`).
- Preflight diagnostics come from `preflight_design` → `core.preflight_scene`
  (`tools.py:674-728`), normalized by `diagnostics_from` (`tools.py:1943`).
- Feedback construction: on a failing gate the loop calls
  `first_diagnostic_target` (one target), `recommend_edit_surface`,
  `classify_diagnostics`, then `create_repair_request` with the **exact**
  diagnostics JSON (`loop.py:331-417` compile, `loop.py:431-503` preflight,
  `loop.py:607-634` visual). Feedback is appended to `previous_feedback` and
  surfaced next iteration via `curated_context` → `_latest_diagnostics_ranked`
  (`tools.py:1253`, capped at `CONTEXT_MAX_DIAGNOSTICS = 12`).

### 4.2 Diagnostics that can NEVER be cleared by the model

These are the infinite-loop seeds — feedback the loop emits but the author cannot
resolve through the DSL-only surface the loop enforces:

1. **`LUMV0509` — "text slot has no fit-validation fixtures."**
   - Suggested repair (`diagnostics.md:48`; `create-design` SKILL line 48): add
     `sample("…")`/`worst_case("…")`.
   - `sample()`/`worst_case()` ARE in the grammar as slot subcommands
     (`grammar.md:97-98`). BUT `AGENT.md` §2 states: *"Brand Kits, slot
     validation **fixtures**, export profiles … live in scene/document
     **metadata**, never in DSL."* This is a **direct contradiction**: the skill
     tells the author to put fixtures in DSL, the permanent memory forbids it,
     and **there is no tool** in `factory.py:37-61` to write slot metadata
     fixtures (no `set_slot_fixture`, no metadata writer). `apply_structured_edit`
     edits nodes, not slot validation fixtures.
   - Worse, during a `layout_cluster`/surgical repair the enforcement gates
     (`is_layout_cluster_dsl`, `is_surgical_dsl`) reject any line that isn't a
     `#<node_id>` modify; a `slot:`-prefixed ref is explicitly rejected
     (`loop.py:1384`, `elif ref.startswith(("slot:", "asset:", ...)): return
     False`). So even if the author tried to add a fixture, the block is dropped
     unapplied. **`LUMV0509` is structurally unclearable inside the enforced
     repair surface.**

2. **`LUMV0800` / `LUMV0801` parent-/artboard-bounds errors in a dense scene.**
   Not literally unclearable, but **practically self-regenerating**: a bounded
   cluster resize fixes the diagnosed node and pushes the overflow onto a sibling
   or descendant (the doc's own `400pt`-in-`170pt` warning,
   `layout-cluster-repair.md:20`). With single-target feedback
   (`first_diagnostic_target`) and a 5-iteration cap, the error count does not
   monotonically decrease. This is the dominant time-sink.

3. **`LUMV0805` (legacy geometry).** `classify_diagnostics` routes it to
   `RepairClass.unsupported_gap` → `EditSurfaceRecommendation.external_planner`
   (`loop.py:799-805`, `LEGACY_GEOMETRY_CODES = {"LUMV0805"}` at `loop.py:752`),
   "legacy_geometry_requires_migration_decision." There is **no external planner
   in the runtime** — `factory.py` registers no such tool and the loop has no
   branch that invokes one. A draft that trips `LUMV0805` can only be repaired by
   a capability that doesn't exist; the director's only escape is
   `stop_with_gap`, which ends the run as `unsupported_capability`.

4. **Surgical/cluster over-constraint as a soft non-clearable.** Any geometry
   problem whose real fix is "recompose the section" (broaden spacing, re-flow a
   dense card) cannot be expressed within
   `LAYOUT_CLUSTER_PROHIBITIONS`/`SURGICAL_AUTHORING_CONSTRAINTS`
   (`loop.py:698-731`) unless the **director** authorizes a structural rewrite
   (`director_allows_structural_rewrite`, `loop.py:262-266`). The deterministic
   `HeuristicAgentDirector` only escalates to `replace_artboard_subtree` on
   *visual* feedback categories (`loop.py:94-109`), never on
   compile/preflight-loop feedback — so during the geometry phase the author is
   pinned to modify-only and the real fix is forbidden.

---

## 5. Architecture gaps vs planner/builder/critic and vs a layout engine

### 5.1 vs a planner/builder/critic design

- **No planner.** There is no upfront layout plan: no grid choice, no section
  budget, no spacing scale, no content-density estimate. The "director"
  (`loop.py:56-119` / `providers.py:33-62`) is a **reactive repair-strategy
  selector** invoked *after* a draft exists, choosing between patch/rewrite
  modes from diagnostics. It never produces a composition spec the builder must
  hit. Brilliant's pipeline (R5) plans structure first; ours dives straight to
  DSL emission.
- **Builder is a one-shot text emitter with no geometric feedback.**
  `LangChainDslAuthor.write_block` (`providers.py:69-91`) emits DSL from a JSON
  blob; it has no measured geometry until *after* compile/preflight. It cannot
  iterate spacing against real measurements within a single authoring step — it
  guesses `g()`/`pad()` literals.
- **Critic is binary, unrubricked, and gated behind a clean preflight.** It only
  runs when preflight passes (`loop.py:431`), returns accept/reject with a free
  text summary (`schemas.py:53-61`), and provides no quantitative spacing/balance
  scores. Its feedback is mapped back to coarse `layout_cluster` repairs
  (`classify_visual_critique`, `loop.py:1535-1575`), which the enforcement gates
  then constrain to modify-only edits — so even good critic feedback often
  cannot be acted on.
- **Shared, tiny iteration budget across all three roles.** Plan/build/critic in
  mature systems get separate budgets; here all repair, rejection, and critique
  share **5 total turns** (`config.py:23`). A single multi-error first draft
  exhausts it before the critic is meaningfully engaged.

### 5.2 vs a layout engine that auto-computes spacing

This is the deepest gap. **Our runtime has no layout/spacing engine of its own.**

- Spacing is *authored*, not *computed*: the LLM writes `al(v, x(s), g(18),
  pad(36))` as literal text (`layout.md:43`, `create-design` SKILL skeleton).
  The runtime's only spacing logic is the Rust `core` that compiles/preflights;
  the agent never calls a "compute balanced spacing" routine because none is
  registered (`factory.py:37-61` tool list has compile/preflight/export/edit, no
  layout solver).
- There is no auto-distribute, no "scale elements to width/height," no rhythm
  normalizer. Compare Brilliant: a **bespoke Flexbox-equivalent constraint
  engine** (`AutoLayoutExtension|*`, "one of the richest [symbol clusters] in the
  binary… computing absolute positions," R5 / `Brilliant-Reverse-Engineering-
  Report.md:434-465`) plus an `execute_commands` surface exposing
  `auto_layout`, `scale_elements_to_width/height`, `reorder`, boolean ops
  (`Brilliant-Reverse-Engineering-Report.md:504`). Brilliant also derives palettes
  in OKLCH on an 11-stop perceptually-even ramp
  (`Brilliant-Reverse-Engineering-Report.md:371`) — principled spacing AND color,
  by engine, not by prompt.
- Consequence for quality: because spacing/hierarchy emerge from LLM-guessed
  literals validated only by pass/fail geometry checks (overflow yes/no), the
  *components* are individually legal but their *composition* (gaps, density,
  visual rhythm, hierarchy ratios) is never optimized by anything. A clean
  preflight just means "nothing overflowed," not "this is well-spaced." That is
  precisely the reported symptom: components fine, composition poor.

### 5.3 Secondary architectural problems found

- **Provider path bypasses the DeepAgent subagents and their skills entirely**
  (§2.2): `create_provider_quality_loop` (`providers.py:151-164`) wires the
  loop directly to `LangChainDslAuthor`/`LangChainVisualReviewer`, so the
  carefully-mounted SKILL.md files (`prompts.py:159-176`) are dead weight in
  production.
- **Default text-only critique under svg config** (§3.2) — no rendered pixels.
- **Empty top-level `skills/` mount** in `factory.py:36`.
- **Knowledge truncation** to ≤6×800 chars in the curated context
  (`tools.py:50-51`).
- **No de-escalation from `layout_cluster`** once set (`loop.py:775-789`),
  pinning the author to modify-only for the rest of the run.

---

## 6. Evidence index (file:line)

- Iteration cap = 5: `config.py:23`. Loop: `loop.py:171`. Fallthrough →
  `max_iterations_reached`: `loop.py:636-644`.
- Blocking-failure gate: `tool_has_blocking_failure` `loop.py:1483-1491`;
  preflight gate `loop.py:431`.
- Single-target feedback: `first_diagnostic_target` `loop.py:443`,`1578-1604`.
- Layout-cluster routing: `LAYOUT_CLUSTER_CODES` `loop.py:751`;
  `classify_diagnostics` `loop.py:759-852`; self-reinforcing prior-context branch
  `loop.py:775-789`.
- Pre-compile rejection (iteration burned, scene untouched): `loop.py:267-302`;
  `is_layout_cluster_dsl` `loop.py:1361-1401`; `is_surgical_dsl`
  `loop.py:1340-1358`; `slot:` ref rejected `loop.py:1384`.
- `LUMV0509` contradiction: `diagnostics.md:48`, `create-design` SKILL line 48,
  vs `AGENT.md` §2; grammar `grammar.md:97-98`; no fixture tool `factory.py:37-61`.
- `LUMV0805` → nonexistent external planner: `loop.py:799-805`, `loop.py:752`.
- Knowledge loader: `knowledge.py:16-47` (20+3 paths), `read_task_knowledge`
  `knowledge.py:101-146` (limit 8), `best_excerpt` `knowledge.py:192` (1600),
  curated caps `tools.py:50-51`, `_capped_knowledge` `tools.py:1487`.
- Missing secondary doc: `Brilliant-vs-Lumen-Product-Gap-Analysis.md` absent;
  empty `apps/agent_runtime/skills/`.
- Doc counts: ours 26 `.md` under `knowledge_docs/`; Brilliant 99 `.md` under
  `brilliant/`.
- Multimodal gap: `preview_image_blocks` png-only `providers.py:217-230`;
  `image_blocks_from_context` png-only `providers.py:233-254`; default svg
  `config.py:24`; no-PNG-under-svg `tools.py:816-820`; false "attached as image"
  claim `providers.py:20`.
- No layout engine in tool list: `factory.py:37-61`. Brilliant flex engine:
  `Brilliant-Reverse-Engineering-Report.md:434-465`, commands `:504`, OKLCH `:371`.
- Provider path bypasses subagents/skills: `providers.py:151-164`,
  `prompts.py:159-176`.
- Strict, unrubricked critic: `prompts.py:131-145`; binary schema
  `schemas.py:53-61`.

(Items labeled "Inference" in the text are reconstructions from config + code +
the bundled Brilliant report; all unmarked claims trace to a cited file:line.)
