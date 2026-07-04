# R5 — Brilliant's Agent Architecture & Self-Improvement Loop

**Audit slice:** Brilliant's agent orchestration, sub-agent model, feedback/critique loop, recreation (cloning) workflow, and the architectural choices behind high first-pass quality + graceful convergence.

**Sources read (all under `/Users/aryankeshri/Documents/brilliant-design/brilliant/`):** `all-agents.md`, `subagent.md`, `hosted.md`, `mcp.md`, `http.md`, `skills/feedback/SKILL.md`, `knowledge/recreation/from-web.md`, `knowledge/recreation/from-image.md`, `knowledge/reference/ai.md`, `tools.md`, `export.md`, `editing.md`. Cross-referenced against our Lumen runtime in `apps/agent_runtime/lumen_deepagent/` (`loop.py`, `tools.py`, `prompts.py`, `providers.py`, `config.py`).

---

## TL;DR (the headline finding)

Brilliant is **NOT a planner→builder→critic pipeline with a gated repair loop.** It is a **single, agentic, knowledge-first author** that builds directly on a live canvas, uses `export` as an *optional self-check the model invokes when it wants*, and has **no convergence machinery at all** — no iteration counter, no "ACCEPT/REJECT" gate, no `max_iterations`, no `stop_reason`. The agent simply keeps editing until it judges the work good, then stops talking. "Done" is a model judgment, not a state-machine transition.

Our Lumen agent is the opposite: a **rigid Phase A repair state machine** (`loop.py`) with `max_iterations=5` (`config.py:23`), a `compile → preflight → export → critic` gate chain where **every stage can hard-`return self._finalize_failed(...)`**, and a `StopReason.max_iterations_reached` terminal that produces exactly the `"Maximum Phase A repair iterations reached."` failure (`loop.py:648-651`) we see in all 5 runs.

So the quality gap is **architectural, not just knowledge-volume**:
1. Brilliant front-loads quality via **mandatory heavy knowledge loading + section-at-a-time building + real-world cloning seeds** (high first-pass quality).
2. Brilliant has **no failure-prone gate chain and no iteration ceiling** to deadlock on (graceful convergence by construction — there is nothing to fail *into*).

---

## 1. How many agents/subagents? Is there a planner/builder/critic split?

### Brilliant: ONE primary agent. Sub-agents are explicitly discouraged.

Brilliant runs as a **single design agent** by default across all four entry surfaces (`hosted.md`, `http.md`, `mcp.md`, `subagent.md`). There is **no built-in planner/builder/critic division of labor.** The same agent loads knowledge, plans, builds, inspects, and fixes.

The strongest evidence is that *every* surface tells the agent to do it all itself and avoid splitting:

- `hosted.md:21` — *"**Do NOT use sub-agents unless the user explicitly asks for them.** Build everything yourself — you are faster and produce better results for single designs."*
- `http.md:21` — identical instruction, verbatim.
- `hosted.md:28` (and `http.md`) — *"Sub-agents add overhead and produce output you'll need to fix anyway."*

Sub-agents exist as an *optional* capability, not a default architecture:

- The tool surface (`reference/ai.md:214`, `reference/tools.md` region, `http.md:6`) exposes `plan_agents` then `spawn_agent`. Per `reference/ai.md:224-225`: *"For large tasks, the main session can spawn parallel sub-agents… Each sub-agent runs in its own ChatOrchestrator (same provider, same API key) with a 5-minute timeout, returns a summary, and renders in the parent session as a collapsible card."*
- When sub-agents *are* used, they are **parallel builders of different regions**, NOT a planner/critic split. `subagent.md` is the sub-agent's own brief: it just builds elements with `create_html`/`create_modify_elements`. It has *no* critic role.
- Critically, the parent **owns the result and is itself the critic**: `hosted.md:34` — *"**Own the result.** … After they finish, inspect with `lookup` … or `export`, then iterate … to fix spacing, alignment, colors, or anything that isn't good enough."* `http.md:25` repeats: *"catch what they missed, and fix what isn't good enough."*

**Inference:** The "critic" in Brilliant is the *same model instance* reviewing its own canvas via `export`/`lookup` inline in the conversation — not a separate adversarial reviewer agent, and not a separate process with its own pass/fail verdict. Self-critique is woven into the single agent's turn loop, not bolted on as a gate.

Sub-agent web search is also deliberately stripped: `reference/ai.md:192` — *"Main sessions ship with `enableWebSearch: true`; sub-agents ship without it."* This keeps sub-agents as cheap parallel hands, not autonomous researchers.

### Contrast — Lumen: a 3-role pipeline behind a gated state machine

Our `providers.py` instantiates **three distinct roles** wired into a coordinator (`create_provider_quality_loop`, `providers.py:262-272`):
- `LangChainAgentDirector` (planner/strategy — `AgentDirectorDecision`)
- `DispatchingDslAuthor` → `PlanFirstDslAuthor` + `LangChainDslAuthor` (builder/repairer)
- `LangChainVisualReviewer` (critic — `VisualCritique`)

`prompts.py` confirms the split: a **coordinator** delegates to a **lumen-dsl-author** subagent and a **lumen-visual-reviewer** subagent (`prompts.py:36` *"Delegate visual review to lumen-visual-reviewer"*; `prompts.py:55` *"Your only job is to write or repair Lumen DSL blocks for the coordinator"*).

This is exactly the planner/builder/critic split that Brilliant **explicitly tells the model not to do** ("produce output you'll need to fix anyway"). We pay the hand-off + re-validation overhead Brilliant warns about, *and* we wrap it in a fragile gate chain (Section 2/5).

---

## 2. The feedback SKILL & the self-critique / repair loop — what is the STOP / convergence condition?

### Two different things named "feedback"

`skills/feedback/SKILL.md` is **NOT a design self-critique loop.** It is a **bug-report / feature-request assistant** — it helps a *human* file feedback to the Brilliant team on GitHub (`brilliant-hq/brilliant`), Discord, email, or X (`SKILL.md:8-9`). It searches existing GitHub issues, drafts a report, and files it (`gh issue create`, `SKILL.md:142`). It is consent-gated: *"Anything beyond what the user typed … is **opt-in only**"* (`SKILL.md:10`). This is product telemetry/support, **not** the design quality loop. Worth flagging because the name is a red herring — Brilliant ships **no `skills/critique/`, `skills/review/`, or `skills/repair/` skill at all.** (Only one `SKILL.md` exists under `skills/`, confirmed by `find`.)

### Where the real self-critique lives: inline in the agent's own turn loop

Brilliant's actual "render-review-repair" loop is **not a skill and not a state machine.** It is **prose guidance embedded in the build-order knowledge**, executed by the single agent. The canonical form is the recreation build order (`from-image.md` / `from-web.md`):

> *"One section at a time. Build outermost container + first section, `export` and compare. Then next section. **Never single-pass.**"* (`from-image.md:16`)
> *"Export and compare after each section. **List specific differences, fix them.**"* (`from-image.md:26`)
> Build Order step 7: *"Final full export comparison."* (`from-image.md:39`)

And the post-subagent guidance: inspect with `lookup`/`export`, *"fix what isn't good enough"* (`hosted.md:34`, `http.md:25`).

### The STOP / convergence condition

**There is none in code.** Brilliant has:
- **No iteration counter.** Nothing equivalent to `for _ in range(self.tools.config.max_iterations)` (our `loop.py:171`).
- **No max-iterations ceiling.** No `LUMEN_AGENT_MAX_ITERATIONS` analog. The agent loops as a normal LLM tool-use conversation until it stops emitting tool calls.
- **No boolean ACCEPT gate.** No `critique.accepted` field, no `StopReason`, no `_finalize_failed`.
- **No machine-checkable pass/fail diagnostic threshold.** Nothing must be "cleared" for the run to be allowed to terminate successfully.

**"Done" = the model decides it looks right and stops editing.** Convergence is a *qualitative judgment by the same agent that built it*, expressed by simply ending its turn. Cancellation is purely user-driven: `reference/ai.md:314-319` — stop button or `/stop`; *"If the model is mid tool-use loop, no further tools are dispatched."* There is no automatic give-up state.

### Contrast — Lumen's STOP condition is a brittle multi-gate state machine

`loop.py` runs a bounded loop with **six distinct terminal `stop_reason`s**, most of which are *failures that abort the whole run*:

| Stage | Gate | Failure terminal (`loop.py`) |
|---|---|---|
| Compile | DSL must compile | `StopReason.compile_failed` (`:275, :292, :416`) |
| Preflight | no error/blocker diagnostics | `StopReason.preflight_failed` (`:511`) — surgical repair, then loops |
| Export | preview must validate + match target dims | `StopReason.preview_invalid` → **hard `_finalize_failed`** (`:524, :556`) |
| Critic | `LangChainVisualReviewer` must not throw | `StopReason.critic_failed` → **hard `_finalize_failed`** (`:592`) |
| Critic verdict | `critique.accepted == True` | `StopReason.accepted` (success, `:606`) else `reviewer_rejected` (`:645`) and loop |
| Loop exhausted | — | `StopReason.max_iterations_reached` → **`_finalize_failed`** (`:648-651`) |

The **only success path** is `critique.accepted == True` within 5 iterations (`loop.py:605`). Everything else funnels to `failed`. Our 5 runs all hit the bottom row: `loop.py:650-651` emits literally *`"Maximum Phase A repair iterations reached."`* with `stop_reason="max_iterations_reached"`. 

**Inference (high confidence):** The runs loop on **preflight diagnostics they never clear**. The author makes a *surgical* repair targeting `first_diagnostic_target(preflight_summary)` (`loop.py:452`), but surgical/targeted repairs are constrained to *"change only that target"* with *"NO `page` line, NO `delete(...)`/`parent(...)`/`clone(...)`"* (`prompts.py:108-115`), and repairs that aren't surgical are **REJECTED and NOT applied** (`prompts.py:1468` analog in `loop.py`; `eval_traces.py:112` counts `dsl_repair_not_surgical`). So a diagnostic that requires a *structural* fix can never be cleared by an allowed *surgical* edit → the gate never opens → 5 iterations burn → `max_iterations_reached`. The repair loop is **structurally incapable of converging** on whole classes of diagnostics. Brilliant has no such trap because it has no gate to clear and no edit-surface straitjacket — the agent just rewrites the offending section.

---

## 3. Does Brilliant render-and-look (multimodal) or rely on text diagnostics?

**Brilliant render-and-looks — multimodal, but lightweight and model-driven.** And critically, it does NOT rely on a geometry-diagnostic engine.

Evidence:
- `export` is the visual self-check primitive on every surface. `all-agents.md:58`: *"`export` — visual check (png, jpeg, webp, svg, pdf)"*. The recreation flow is built entirely around *"`export` and compare"* (`from-image.md:16,26`).
- The initial context Brilliant sends the model **includes a rendered screenshot**: `reference/ai.md:149` — *"when the first user message of a session is sent, Brilliant builds an MCP context payload containing a Blueprint snapshot of the canvas **and a canvas overview PNG screenshot**. This is needed for the model to 'see' the work-in-progress."* So the model literally sees pixels, not just a node tree.
- Mockup-quality rendering is taken seriously: `export.md:355` / `reference/export.md:28-35` — *"For UI mockups in WebP, set `webpLossless: true`; the lossy default leaves visible gray banding on rounded corners and gradients."* Default `scale: 2.0` (retina) — `export.md:118`. They tune the *render* so the model's visual judgment is accurate.
- `lookup` with `format: "blueprint"` gives the model the structured tree when it wants exact geometry (`all-agents.md:57`), but this **complements** the visual look — it is not a separate automated diagnostic verdict.

**There is NO machine diagnostic layer in Brilliant.** No preflight engine, no diagnostic codes, no "spacing/density/hierarchy" linter. The model *is* the spacing/density/hierarchy judge, looking at a real render. Quality is enforced by **knowledge** (foundations, blocks, effects docs) + **the model's eyes**, not by a rule engine emitting codes the agent must satisfy.

### Contrast — Lumen ALSO render-and-looks, but gates it behind diagnostics

Important nuance for the synthesis agent: **Lumen is not "text-only."** It genuinely attaches the rendered PNG to a vision model:
- `tools.py:896-957` (`get_latest_preview_for_critique`): *"PNG artifacts are returned as base64 so a vision-capable provider adapter can turn them into an image message."*
- `providers.py:205-258` (`LangChainVisualReviewer.review`): builds messages with `*preview_image_blocks(preview_payload)` — the real preview image is attached as an image block; the JSON text sends a compact base64-stripped payload (`providers.py:222-229`).
- The director and DSL author *also* receive image blocks (`providers.py:71, 104, 157` `image_blocks_from_context`).

So the visual channel is present on both sides. **The difference is not multimodality — it is that Lumen subordinates the visual critique to a machine-diagnostic gate chain** (`compile`/`preflight` codes like `LUME*`/`LUMG*`, `eval_traces.py:136` `count_geometry_diagnostic`, `tools.py:1511` `query_geometry`). The agent is *not allowed to reach* the visual reviewer until export validates (`loop.py:521-560`), and is *not allowed to finish* until `critique.accepted`. Brilliant lets the model look and decide; Lumen makes the model fight a linter first and frequently never gets to "looks good."

---

## 4. recreation/ — how does Brilliant clone designs, and does it seed from real-world good layouts?

**Yes — this is one of Brilliant's most important quality levers, and we have no equivalent.** Cloning real designs is an explicit, first-class workflow that **seeds compositions from real-world good layouts instead of generating spacing/density/hierarchy from scratch.**

### from-web.md (recreate from a URL)
- The agent **fetches the live page and extracts exact values** rather than guessing: `from-web.md:6` — *"You have HTML, CSS, and assets — **extract exact values instead of guessing.**"*
- `from-web.md:9-12` Step 0: `web_fetch` the page, read HTML structure, *"Write down: color scheme (exact hex), font stack, sections, layout structure."*
- Rule 1 (`:16`): *"**Extract, don't guess.** Get exact hex colors, fonts, weights, sizes, **padding, gap, border-radius, box-shadow** from CSS."* → spacing/density come straight from a real, professionally-made site.
- Rule 5 (`:24`): *"**Match proportions.** Use extracted CSS values. `padding: 80px 120px` → use those values."*
- Build order (`:36-44`): root → navbar → hero → each section → footer, **export & compare after each**.

### from-image.md (recreate from a screenshot/reference)
- Step 0 (`:9-11`): *"Write 3-5 sentences describing… Don't build until you've committed observations to text. **Prevents building from stereotype instead of observation.**"* — explicitly fights the "generic AI layout" failure mode.
- Rule 3 (`:17`): *"Match actual colors, **not the category**. Build from THIS image, not what this type of app 'usually' looks like."*
- Rule 4 (`:20`): *"**Match density.** If reference is compact, build compact. **Don't inflate padding.**"* — this is *exactly* the "bad spacing/density" failure our audit is chasing, and Brilliant has a hard rule against it.
- Rule 6 (`:22`): *"**Match proportions.** Narrow section stays narrow. **Don't equalize.**"* — directly addresses hierarchy/layout-rhythm.
- Rule 1 (`:15`): *"**Build every element.** 7 list items → build 7… Count elements in image, count in output. Must match."* — prevents the agent from collapsing real density into a sparse generic layout.

### Why this drives quality (inference, high confidence)
Spacing, density, and hierarchy are the hardest things for an LLM to *invent* well from a text prompt — they're the very dimensions our audit says Lumen gets wrong. Brilliant sidesteps the problem for a large fraction of tasks by **transcribing the spatial system of a known-good reference** (a live site's CSS, or an observed screenshot's proportions) instead of synthesizing it. The reference acts as a **layout prior / seed**. Even for non-recreation tasks, the *same disciplines* ("match density, don't inflate padding, match proportions, build every element, one section at a time, export and compare") are reusable habits the model carries over.

Note the recreation docs `assumes:` (frontmatter, both files) `blueprint/layout, blueprint/text, blueprint/effects, blueprint/components, blueprint/images` — so even cloning pulls in the deep layout/component knowledge. The clone is rebuilt with Brilliant's real layout primitives, not pasted as a flat image.

**Lumen has no recreation/cloning path.** `prompts.py` and `loop.py` describe only prompt→`DesignPlan`→template→DSL→repair. We generate layout from a `DesignPlan` schema (`schemas.py:215`) rendered through `templates.py` ("vetted layout templates"). Templates can produce *safe* layouts but they are generic scaffolds, not transcriptions of real good designs — so density/proportion/hierarchy are *synthesized*, which is precisely where quality degrades.

---

## 5. Architectural choices most responsible for (a) high first-pass quality and (b) graceful convergence

### (a) High first-pass quality

1. **Mandatory, heavy, front-loaded knowledge.** Brilliant's #1 rule everywhere: *first action MUST be `get_knowledge`* (`hosted.md:5`, `http.md:5`, `mcp.md:5`). And the volume is enforced: `all-agents.md:7` — *"NEVER start designing via Brilliant's DSL before loading **a minimum of 12 knowledge keys**."* `all-agents.md:5` — *"Over-load, never under-load… Many chats require 20-25 knowledge files."* HTTP raises the batch to *"up to 15 keys per call… all your knowledge loading in one or two calls before you start designing"* (`http.md:33`). The knowledge tree is **91 docs** (confirmed by `find`), vs our ~19. The doc map (`all-agents.md:11-28`) forces loading `design/foundations` + relevant `design/blocks/*` for *any* new design, plus `blueprint/components` for *"3+ similar elements"* (cards/tiles/rows) — directly governing density and repetition rhythm.
   - **This is the single biggest lever.** The model is loaded with spacing/typography/foundation/blocks/effects knowledge *before* it lays down a single element, so the first pass is informed by Brilliant's house style, not the model's generic priors.
2. **Component-first repetition.** `all-agents.md:19`: for 3+ similar elements, *"define the shape once with `comp` on a frame, then `inst(#ref)` each copy… **NEVER hand-code N near-identical lines.**"* This keeps cards/rows/tiles uniform → consistent spacing and density automatically.
3. **Build incrementally + look.** "One section at a time, export, compare" (Section 2/4) catches spacing/hierarchy errors *while building*, when they're cheap to fix, instead of in a post-hoc gated review.
4. **Real-render visual grounding from message 1** (Section 3) — the model judges against retina-quality pixels (`webpLossless`, `scale:2.0`), not an abstract tree.
5. **Token-disciplined authoring when desired.** `mcp.md:23` `designSystem: "default"` enforces `$color.surface`, `$spacing.md` — *"No bare hex or numeric literals on tokenizable slots"* — so spacing/color come from a coherent scale, not arbitrary numbers. (This is *opt-in*, not a blocking gate.)
6. **Real-world seeding via recreation** (Section 4) for the common "make it like X" task.

### (b) Graceful convergence (no infinite repair loops)

1. **No iteration ceiling and no gate to deadlock on — by construction.** Brilliant cannot loop forever on an unclearable diagnostic because **it has no diagnostic verdict and no loop counter.** The agent edits in a normal conversational tool-use loop and stops when satisfied. There is no `max_iterations`, no `_finalize_failed`, no `max_iterations_reached`. The failure mode that kills all 5 of our runs *literally cannot occur* in Brilliant's design.
2. **Self-critique is continuous and same-agent, not a separate pass/fail gate.** Because the builder is also the reviewer, there's no hand-off where a critic emits a verdict the builder must satisfy through a *restricted* edit surface. Brilliant's agent can make whatever edit it judges necessary (including restructuring a section) — it is never told "your repair was REJECTED and NOT applied because it wasn't surgical" (our `loop.py`/`prompts.py:1468`).
3. **Edits go straight to a forgiving live canvas with full undo.** `editing.md` + `reference/ai.md:453` (AI ops get *"their own per-session undo stack"*) mean repairs are cheap, reversible, and unconstrained. No "compile must pass → preflight must pass → export must validate → critic must accept" funnel where any stage aborts the run.
4. **Stopping is user-controlled, never an automatic give-up.** `/stop` exists, but the system never declares the run `failed`. The worst case is "the user asks for more," not a terminal `failed` status.

### The decisive contrast, stated plainly

Brilliant pushes quality **up-front** (knowledge + cloning + component discipline + look-while-building) and lets the model **converge by judgment** with an unbounded, gate-free loop. Lumen pushes quality **to the back** (generate from a `DesignPlan`/template, then *validate*) and tries to *force* convergence through a **bounded gate chain** (`compile → preflight → export → critic`, 5 iterations) whose surgical-repair constraints make whole diagnostic classes unclearable — so it deadlocks at `max_iterations_reached` instead of converging. Our agent has ~5x fewer knowledge docs, no real-world layout seeding, and a brittle multi-gate state machine where Brilliant has none.

---

## Numbers & names for the synthesis agent

- Knowledge docs: **Brilliant 91** (`find … knowledge -name '*.md' | wc -l`); **Lumen ~19**.
- Brilliant hard minimum before designing: **12 knowledge keys** (`all-agents.md:7`); typical **20-25**; HTTP batches **up to 15/call** (`http.md:33`).
- Brilliant primary agents: **1** (sub-agents discouraged, `hosted.md:21`); sub-agent timeout **5 min** (`reference/ai.md:225`).
- Brilliant skills under `skills/`: **1** (`feedback/SKILL.md`) — a *bug-report* assistant, not a design critic.
- Brilliant convergence machinery: **none** (no iteration counter, no `stop_reason`, no ACCEPT gate, no diagnostic codes).
- Brilliant visual self-check: `export` (PNG @`scale:2.0`, `webpLossless:true` for mockups) + initial canvas-overview PNG screenshot (`reference/ai.md:149`).
- Lumen roles: **3** — `LangChainAgentDirector`, `DispatchingDslAuthor`, `LangChainVisualReviewer` (`providers.py:262-272`).
- Lumen loop: `max_iterations=5` (`config.py:23`, env `LUMEN_AGENT_MAX_ITERATIONS`), `for _ in range(...)` (`loop.py:171`).
- Lumen terminal failure observed in all 5 runs: `StopReason.max_iterations_reached`, message *"Maximum Phase A repair iterations reached."* (`loop.py:648-651`).
- Lumen gate stages & failure terminals: `compile_failed` (`loop.py:275/292/416`), `preflight_failed` (`:511`), `preview_invalid` (`:524/556`, hard fail), `critic_failed` (`:592`, hard fail), `reviewer_rejected` (`:645`), `accepted` (only success, `:606`).
- Lumen surgical-repair trap: non-surgical repairs *"REJECTED and NOT applied"* (`prompts.py:108-115`; `eval_traces.py:112` counts `dsl_repair_not_surgical`, `:108` `layout_cluster_repair_rejected`).
- Lumen diagnostic code families: `LUME*` (compile/export, `tools.py:117`), `LUMG*` (binding/geometry, `tools.py:525`); geometry diagnostics counted in `eval_traces.py:136`.
- Recreation seeding (Brilliant only): `from-web.md` (extract exact CSS hex/font/padding/gap/radius/shadow), `from-image.md` (*"Match density… Don't inflate padding"* `:20`; *"Match proportions. Narrow section stays narrow. Don't equalize"* `:22`). **Lumen has no recreation path.**
