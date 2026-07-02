# S3 — Agent-Loop & Convergence Gap (Synthesis)

**Synthesis of:** R5 (Brilliant architecture & feedback), R7 (our skills: repair-design / visual-review), R8 (our runtime: loop code + diagnostics), R9 (trace forensics across the 5 failed runs).
**Question:** All 5 of our runs die at `max_iterations_reached`. Brilliant has a feedback/critique architecture. Why does our loop deadlock, how does Brilliant's converge, do we use visual feedback, and how do planner/builder/critic differ?
**Verification:** Load-bearing claims below were re-checked directly against `apps/agent_runtime/lumen_deepagent/{config.py,loop.py}` during synthesis (cites marked ✓verified).

---

## TL;DR — the one-paragraph answer

Our loop deadlocks because it is a **bounded, gated repair state machine that tries to *force* convergence through a repair surface so constricted that whole classes of fed-back diagnostics are mathematically unclearable inside the offered edit moves.** The agent is handed N simultaneous diagnostics, told to fix exactly one node at a time, through a "layout-cluster" gate that (i) only permits edits to a ~20-of-38-node subset, (ii) **atomically rejects the entire repair patch if any single referenced node is out of that subset** (✓verified `loop.py:1386-1387`), (iii) forbids the exact operations several errors require — `al(...)`, `wrap(...)`, and any `slot:`/`asset:`/`document` reference (✓verified `loop.py:1384-1385`, `loop.py:1404-1412`), and (iv) gives only ~3 effective cycles. A rejected repair applies **zero** operations, so the scene is unchanged and the *identical* diagnostics return next cycle (R9). The budget burns, the `for` loop falls through to `StopReason.max_iterations_reached` / *"Maximum Phase A repair iterations reached."* (✓verified `loop.py:636-644`). Brilliant has **none of this machinery** — no iteration counter, no gate, no pass/fail verdict, no `max_iterations` — and converges by a single agent looking at real pixels and judging "good enough" (R5). Our loop also judges largely from **SVG text geometry, not pixels**, under shipped defaults (R8: `preview_format="svg"`, `config.py:24`), so even the parts that *do* converge are graded blind to the spacing/density defects this audit is about.

---

## 1. The exact deadlock mechanism — which diagnostics never clear, and why repairs don't reduce errors

This is the proximate cause of all 5 failures. **All four readers converge on it**; R8 and R9 give the mechanism, R7 gives the skill-level catch-22, R5 frames why Brilliant can't hit it. Verified against code.

### 1a. The loop is a bounded gauntlet, not a converging optimizer
- `max_iterations` defaults to **5** (✓verified `config.py:23`, `LUMEN_AGENT_MAX_ITERATIONS="5"`), consumed by a single counted `for _ in range(self.tools.config.max_iterations)` (✓verified `loop.py:171`) that covers compile **AND** preflight **AND** critic **for the whole run** — not per stage (R8 §1).
- Every gate failure does `continue` and **burns a turn** (✓verified preflight branch ends `continue` at `loop.py:503`). R9 measured the *effective* budget at **3** `dsl_block_requested` cycles per run before the kill — far too few for the 8–28 simultaneous diagnostics observed (R9 §3).
- The ONLY clean success is `critique.accepted == True` or director `accept` (✓verified `loop.py:192-201`). There is **no quality-floor / best-effort / "good enough" exit** (R7 §3, R8 §1).
- Fallthrough terminal is exact: `self.state.stop_reason = StopReason.max_iterations_reached` → *"Maximum Phase A repair iterations reached."* (✓verified `loop.py:636-644`). This is the literal string in all 5 traces (R9 roster).

### 1b. Single-target feedback vs many-error reality
On a realistic dense first draft the loop sees many simultaneous diagnostics but feeds back **one** via `first_diagnostic_target(...)` (✓verified `loop.py:443`) and classifies the whole repair from it (✓verified `loop.py:451-457`). R9's measured per-iteration diagnostic counts (e.g. `run_f58a`: `LUMV0904`×14, `LUMV0801`×5, `LUMV0810`×3, `LUMV0509`×3, `LUMV0800`×1 plus brand warnings) cannot fall to zero in ≤3 single-node patches even if every patch is perfect.

### 1c. The layout-cluster gate atomically rejects the correct fix — **THE deadlock** (R9, verified)
This is the single most decisive, code-confirmed finding. R9 reproduced it by replaying the recorded `rejected_source` against the real gate.

- `LAYOUT_CLUSTER_CODES = {"LUMV0800", "LUMV0801", "LUMV0803"}` (✓verified `loop.py:751`). Once a page/parent-bounds error appears, the repair is classified `layout_cluster`.
- The cluster's allowed node set = `descendant_node_ids` + root/parent/background ids (✓verified `layout_cluster_allowed_node_ids`, `loop.py:1423-1429`) — R9 found this listed only **20 of ~38 nodes** in `run_e2ca`.
- The validator is **atomic**: it iterates every `#ref` line and `return False` on the first stray ref (✓verified `loop.py:1386-1387`). A `False` means **0 operations apply** → scene unchanged → identical diagnostics next cycle. R9's line-by-line replay: **6 of 18 emitted `#refs` failed "NOT in allowed cluster nodes"** (`appt_label` carrying `LUMV0904`, `divider`, `patient_row`, `cta_button`, `cta_text`, `footer_text`), so the whole patch was dropped.
- The runtime then emits `layout_cluster_repair_rejected`: *"Your previous layout_cluster repair was REJECTED and NOT applied because it edited outside the allowed cluster or attempted to re-author the page."* (R9 §3; the symmetric surgical-violation text is ✓verified at `loop.py:1441-1447`).

### 1d. Diagnostics that are unclearable in the offered surface (the "rides-along-forever" set)
Cross-referenced R7/R8/R9 — they agree on the list; minor numbering differences reconciled here:

| Code | Meaning | Why it never clears | Sources |
|---|---|---|---|
| `LUMV0509` | text slot has no fit-validation fixtures | Fix is `#slot:key sample(...) worst_case(...)`, but fixtures live in scene metadata "NEVER in DSL" (`AGENT.md` §2), **there is no fixture tool** (`factory.py:37-61`), and the cluster gate hard-rejects any `slot:` ref (✓verified `loop.py:1384-1385`). Structurally unsatisfiable. | R7 #11, R8 §4.1, R9 §2 |
| `LUMB0613` / `LUMB0614` | font asset not embeddable / subsettable (PDF) | No DSL node-modify syntax exists to set font export flags; brand-kit/asset surface only. Warnings that never clear. | R9 §2 |
| `LUMV0800` | artboard exceeds exportable bounds | A4 portrait canonicalizes to `595.27… × 841.88… pt`; `s(fill,fill)` ceils height to 842pt → ~0.11pt over → **permanent**. The gate *forces* `s(fill,fill)` on the root (numeric sizes rejected — ✓verified `root_artboard_size_syntax_is_supported`, `loop.py:1415-1420`), so the agent cannot author the value that avoids it. | R9 §2, R8 §4.2 |
| `LUMV0805` | (legacy geometry) | Routed to `external_planner` (✓verified `LEGACY_GEOMETRY_CODES`, `loop.py:752,799-805`) **which does not exist in the runtime** — only escape is `stop_with_gap → unsupported_capability`. | R8 §4.3 |
| `al(...)` / `wrap(...)` changes | needed to fix overflow by changing layout direction / enabling wrapping | `UNSUPPORTED_LAYOUT_CLUSTER_MODIFY_CALL_RE` rejects them in cluster modify lines (✓verified `loop.py:753-755, 1404-1412`). | R9 §3 |

**R9's quantified verdict (the killer number): on the A4 runs, 5 of the ~8 active diagnostic codes are not fixable in the repair surface at all** — so *even a perfect model cannot pass Phase A*. This is the cleanest single statement of why it's a structural bug, not a model-quality problem.

### 1e. Self-reinforcing classification (no de-escalation)
Once a repair is classed `layout_cluster`, a later compile/agent-guard failure **keeps** it `layout_cluster` (✓verified `loop.py:775-789` — `prior_context.repair_class == layout_cluster` + any `LUMD`/`LUMA` code → re-returns `layout_cluster`). There is no path back to a freer surface, and no anti-oscillation memory between the competing `LUMV0902/0903/0904` fit actuators (R7 #12, R8 §1.4). R9 saw the literal whack-a-mole: `LUMV0903` on `cta_label` goes `0→3`, `LUMV0801` flips `1→0→1` as fixing one node pushes a sibling over because nothing reflows holistically.

### 1f. A second, independent failure that *also* burns iteration 1 (R9, important nuance)
On all three A4 runs, **iteration 1 never even produced valid DSL** — the model hallucinated grammar: `va(center)` → `LUMD0212 unknown property`, and `divider` as an element kind → `LUMD0206 unknown element kind`. R9's forensic detail: the **DSL grammar/text docs were NOT among the 8 retrieved knowledge snippets** (retrieval ranked "Brilliant — Reverse-Engineering Report", "ABM Design Engine Spec", "Permanent Memory" higher), even though `text.md:29` literally says *"There is no `valign`"* and the doc exists in our 26-doc corpus. So **part of the deadlock is a retrieval/ranking failure, not the doc-count gap** — a correction to the simple "19 vs 91 docs" narrative.

---

## 2. How Brilliant's loop converges and decides "done"

R5 is the primary source; R7 corroborates from the skill bundle. **Decisive finding: Brilliant has no convergence machinery at all.**

- **No iteration counter, no ceiling, no ACCEPT/REJECT gate, no `max_iterations`, no `stop_reason`** in code (R5 §2). "Done" = the single agent judges the work good and stops emitting tool calls. Cancellation is **user-only** (`/stop`, `reference/ai.md:314-319`).
- The `skills/feedback/SKILL.md` is a **red herring** — it is a GitHub bug-report / feature-request assistant that files to `brilliant-hq/brilliant` / Discord (R5 §2, R7 TL;DR). Brilliant ships **exactly one skill, and it is not a design-critique loop**. The real self-critique is **inline prose in build-order knowledge**, executed by the same agent: *"One section at a time… export and compare… Never single-pass"* (`from-image.md:16`); *"Export and compare after each section. List specific differences, fix them"* (`from-image.md:26`) (R5 §2).
- **Convergence is by judgment on a forgiving canvas**: edits hit a live canvas with full per-session undo (`reference/ai.md:453`), so repairs are cheap, reversible, and **unconstrained** — the polar opposite of our atomic-reject zero-op gate (R5 §5). There is no diagnostic engine, no preflight, no `LUMV*` linter to satisfy; the model is the judge (R5 §3).

**The exact failure killing all 5 Lumen runs *cannot occur* in Brilliant** — there is no gate to deadlock on and no budget to exhaust (R5 TL;DR, §5).

---

## 3. Multimodal visual feedback vs text-only diagnostics

The two relevant readers (R5, R8) initially *appear* to disagree; the contradiction resolves cleanly.

- **R5** says: "Lumen ALSO render-and-looks" — it base64-attaches a PNG to a vision model (`tools.py:896-957`, `providers.py:205-258`), so the gap "is not multimodality" but that Lumen subordinates the visual critique to a machine-diagnostic gate.
- **R8** says: multimodality is "effectively off under defaults" — `preview_format` defaults to **`"svg"`** (✓verified `config.py:24`), `export_preview_bundle` makes no PNG for SVG, so `png_path` is empty and the image block is attached **only for PNG** (`providers.py:217-254`). The director prompt's claim *"The latest rendered preview is attached as an image"* (`providers.py:20`) is **false under shipped config**.

**Resolution (synthesis):** Both are right at different layers. Lumen has the *capability* to look at pixels (R5), but **the shipped default config never produces the pixels**, so in practice the director/author/critic judge from **SVG text geometry + a node digest** (R8). R7 independently confirms the *skill* permits grading from SVG geometry instead of the PNG (`visual-review` line 16). R9 confirms the consequence empirically: the one run that reached the critic (`run_92039`) had its 300pt dead-zone caught — but the critic also cited `LUME0205` ("hand-placed not auto-layout"), **a code that appears in 0 actual preflight outputs**, i.e. the critic is partly hallucinating diagnostics rather than reading pixels.

So: **our loop is nominally multimodal but operationally text-first**, and the perceptual defects this audit targets (density, balance, whitespace ratio, hierarchy) are exactly what SVG-text grading under-detects. Brilliant is **pixel-first from message 1** — retina screenshots at `scale:2.0` + `webpLossless:true` to keep the model's visual judgment accurate (`export.md:355`) (R5 §3).

---

## 4. Planner / builder / critic separation differences

All four readers agree; this is a clean architectural contrast.

| Dimension | Lumen (ours) | Brilliant |
|---|---|---|
| **Roles** | **3 distinct**: `LangChainAgentDirector` + `DispatchingDslAuthor` + `LangChainVisualReviewer` wired coordinator→`lumen-dsl-author`→`lumen-visual-reviewer` (R5 §1, `providers.py:262-272`, `prompts.py:36,55`) | **1 primary agent.** *"Do NOT use sub-agents unless the user explicitly asks… Build everything yourself"* (`hosted.md:21,28`). Sub-agents are optional parallel region-builders, never a critic (R5 §1) |
| **Planner** | No real planner. The "director" is a **reactive repair-strategy selector run *after* a draft exists** (R8 §5, `loop.py:56-119`); it never emits a composition spec (grid, spacing scale, density budget) | Front-loads judgment as knowledge before building: commit to a system, pick focal point, 60-70% whitespace target, anti-cliché rules (R7 §4, `foundations.md`) |
| **Builder** | One-shot DSL emitter from JSON; **guesses `g()`/`pad()` literals**; gets geometry only post-compile (R8 §5); no layout engine exists (R8 §0.6) | Builds incrementally on live canvas, looks after each section, uses `comp`+`inst` for repetition → uniform density (R5 §5) |
| **Critic** | **Binary, unrubricked, gated behind a fully-clean preflight** (✓verified preflight error branch `continue`s at `loop.py:431,503` *before* the critic runs at `loop.py:509+`); feedback coarsely mapped to `layout_cluster` repairs the gate then forbids acting on | **Same agent is the critic** — continuous self-critique, not a separate pass/fail verdict the builder must satisfy through a restricted edit surface (R5 §1,§2) |
| **Budget** | **Shared 5-turn budget across all 3 roles** (✓verified `config.py:23`) | None |

**The irony, stated by R5:** our 3-way split is *precisely the architecture Brilliant explicitly tells the model not to use* ("Sub-agents add overhead and produce output you'll need to fix anyway"). And because the critic is gated behind clean preflight, in the deadlock runs **the critic rarely even runs** — the loop dies in the preflight repair phase before reaching the design-quality judge (R8 §1.4, R9 persistence table: only `run_92039` iter3 reached `has_errors=False`).

---

## 5. Root causes, ranked by impact

Ranking reflects: does it *cause the 5 failures* (proximate) vs *cause the quality gap* (deeper), and breadth of reader evidence.

1. **[PROXIMATE / kills all 5 runs] The layout-cluster repair gate is structurally non-converging.** Atomic rejection of whole-page patches on any stray ref (✓`loop.py:1386-1387`), forbidden `al()`/`wrap()`/`slot:` ops several errors require (✓`loop.py:1384-1385,1404-1412`), incomplete cluster node sets (20/38), self-reinforcing classification with no de-escalation (✓`loop.py:775-789`). **5 of ~8 A4 codes unfixable in this surface.** *(R9 §3 verified by replay; R8 §1.4, §4; R7 #11-13.)*
2. **[PROXIMATE] Budget far too small + single-target feedback for many-error drafts.** ~3 effective cycles vs 8–28 simultaneous diagnostics fed one node at a time. *(R9 §3; R8 §1.1-1.2.)*
3. **[PROXIMATE] Retrieval ranks the wrong docs, so iteration 1 hallucinates grammar.** Grammar/`text.md` not retrieved; `va`/`divider` halt compile and waste turn 1 on all A4 runs. **Not a doc-count problem — a ranking problem.** *(R9 §1,§5.)*
4. **[DEEPER / the real Lumen≠Brilliant gap] No planner and no layout/spacing engine.** Spacing is hand-emitted LLM literals; nothing computes positions; no composition spec is ever produced. Brilliant has a bespoke flex `AutoLayoutExtension` + `scale_elements_to_width/height` + OKLCH ramps. A clean preflight only means "nothing overflowed," never "well-spaced." *(R8 §0.6,§5; R5 §4-5; R7 §2,§5.)*
5. **[DEEPER] Operationally text-first critique.** SVG-default config means the multimodal critic usually grades from text geometry, blind to density/balance; the critic is also binary/unrubricked and partly hallucinates codes (`LUME0205`). *(R8 §3 verified `config.py:24`; R7 §3; R9 §5.)*
6. **[DEEPER] Composition doctrine lives in the wrong place / is missing.** Our skills are a "compiler-survival manual" with no whitespace target, no spacing rhythm, no anti-cliché, no recreation/cloning path; Brilliant front-loads numeric design targets and clones spatial systems from real references. *(R7 §1-5; R5 §4; R8 §2.)*

**Resolved contradiction:** R5 implies "Lumen is multimodal," R8 says "multimodal is off." Synthesis: capability present (R5), shipped default disables it (R8 ✓verified). Both retained; the operative truth is R8's — under the config that produced the 5 failures, critique was SVG-text-driven.

---

## 6. Before / After — how the loop SHOULD terminate and choose repairs

### 6a. How repairs are chosen — before vs after

| | BEFORE (current) | AFTER (target) |
|---|---|---|
| **Granularity** | One diagnostic target fed back per cycle (`first_diagnostic_target`) | Batch all diagnostics of a region into one repair; pass **typed** diagnostics (today `current_diagnostics` is `null`, real codes smuggled in a stringified blob — R9 §3a) |
| **Patch validation** | **Atomic**: any out-of-cluster ref → whole patch dropped, 0 ops applied (`loop.py:1386-1387`) | **Non-atomic / partial-apply**: apply the valid `#refs`, report which were skipped; never zero-op a multi-line patch. Or widen the cluster to whole-page when the diagnostic is page-bounds |
| **Allowed ops** | `al()`, `wrap()`, `slot:`, `asset:` all rejected in cluster repairs | Allow layout-direction and wrap changes (they are the *fix* for overflow); add a metadata-fixture path so `LUMV0509` is satisfiable |
| **Classification** | Sticky `layout_cluster`, no de-escalation (`loop.py:775-789`) | De-escalate to a freer surface once bounds errors clear; anti-oscillation memory across `LUMV0902/3/4` |
| **Unfixable codes** | `LUMV0509/0800/B0613/B0614/0805` ride along forever and block the gate | Demote non-author-fixable warnings (`LUMB0613/4`, fixture warnings) from "blocks Phase A" to "non-blocking note"; special-case the 0.11pt A4 `LUMV0800` rounding |
| **First draft** | LLM guesses `g()`/`pad()`; grammar docs often not retrieved | Pin grammar/`text.md` into context always; produce a composition spec (grid + spacing scale + whitespace target) *before* emitting DSL; run a layout engine to compute spacing |

### 6b. How termination SHOULD work — before vs after

**BEFORE:** `for _ in range(5)` → every gate failure `continue`s → success ONLY if `critique.accepted` → else fall through to `max_iterations_reached` "failed" (✓`loop.py:171,192,636-644`). No quality floor, no best-effort success, no convergence detector. Result: 5/5 `failed`, user never sees a draft.

**AFTER (recommended):**
1. **Add a convergence detector**: terminate `accepted` when monotone error-reduction stalls AND the best draft has zero *blocking* errors and a critic score above a defined floor — not only on a binary `accepted==True`.
2. **Add a "best-effort success" exit**: if the budget is hit but `best_scene` is preflight-clean (we already track it — ✓`_consider_best`/`_restore_best_scene`, `loop.py:646-690`), return `status="completed_with_warnings"` and surface the draft, not `status="failed"`. The keep-best machinery is built; it's just wired to a "failed" terminal.
3. **Raise the practical budget** and make it per-phase (separate compile-repair vs composition-iteration budgets) so geometry whack-a-mole can't starve the design critic.
4. **Replace the binary critic with a rubric + score** (whitespace ratio, focal dominance, scale contrast, alignment) graded on **pixels** (force `preview_format="png"` for the critique export), and stop only when the score clears the floor or improvement plateaus.
5. **Mirror Brilliant's "judge-and-stop" where possible**: front-load the spec, build incrementally, look at pixels after each region, and let the agent stop by judgment — with the bounded loop kept only as a safety net, not the primary convergence mechanism.

**Net:** today the loop tries to *force* convergence through a surface that makes whole diagnostic classes unclearable, so it deadlocks; the fix is to make repairs **actually reducible** (non-atomic, layout-changing, batched, with unfixable codes demoted) and to **terminate on quality/best-effort, not on a binary gate** — converging like Brilliant by judgment over a forgiving surface instead of failing on an unsatisfiable linter.

---

### Evidence map (reader → claim)
- **Deadlock mechanism / cluster gate / unfixable codes / per-iter persistence:** R9 (trace replay, primary) + R8 (code paths) + R7 (skill catch-22). ✓verified `loop.py:751,775-789,1380-1429,1404-1412,636-644`.
- **Brilliant has no convergence machinery / 1 agent / feedback-skill red herring / pixel-first:** R5 (primary) + R7 (corroborates skill bundle).
- **Multimodal-but-SVG-default contradiction resolved:** R5 (capability) vs R8 (✓`config.py:24` default disables) — both retained, R8 operative.
- **Planner/builder/critic split + no layout engine:** R8 (primary) + R5 (Brilliant side) + R7 (skills).
- **Budget = 5, single counted loop:** ✓verified `config.py:23`, `loop.py:171`.
