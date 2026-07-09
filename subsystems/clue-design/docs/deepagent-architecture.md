# Deepagent v0 — architecture mandate & decision ledger

> **This file is the persistent memory for the deepagent rebuild.** Every
> architectural decision lands here with a status (DECIDED / PENDING) and a
> date. Update it in the same commit as any change it governs. Chat history
> does not count as a record.

## The mandate (DECIDED 2026-07-09)

The design agent is **harness engineering + agency**. The live editor turn
today runs `LumenQualityLoop` (apps/agent_runtime/lumen_deepagent/loop.py) — a
deterministic Python pipeline around three one-shot LLM calls (director /
author / reviewer, providers.py) that have no tools, no memory, and no agency.
That architecture is retired as the target. The target is a **true
deepagent**: an orchestrator agent plus tool-bearing subagents with real
agency. Never call the old pipeline "the deepagent."

v0 is the **minimalistic** version: proper knowledge, skills, and tools —
**no Python-loop rails** (chip gate, keep-best, forced logo/accommodation
rounds, recipe appending, surgical filters, edit-scoped acceptance are all
suspended in v0). Engine-level contracts are NOT rails and remain: compiler
grammar, reconcile human-protection (LUMD0262 family), token resolution
(LUMB0101/0301), retokenization inside `preflight_design` (tools.py:1968),
font fallback diagnostics (LUMS0100), all diagnostics. The old quality loop
stays in the codebase untouched (see D7).

## Glossary (binding, to prevent miscommunication)

- **Deepagent / harness** — the whole system that ships.
- **Orchestrator** — the main agent from `create_deep_agent` (was called
  "coordinator" in factory.py; same thing).
- **Subagent** — invoked via the built-in `task(name, prompt)` tool. Starts
  with a FRESH empty history every invocation (only its system prompt +
  skills + the task prompt). Only its final message returns. Continuity must
  come from files/state.
- **Shared state** — LangGraph state: custom typed fields via `state_schema`
  ("constitution") + the filesystem backend ("record/workspace").
- **Substrate** — `LumenDesignTools` (tools.py): the Python object holding the
  scene + Rust engine session. Not a mind.

## Decisions

### DECIDED

| # | Decision | Date |
|---|---|---|
| M1 | True-deepagent mandate; v0 minimal; loop rails suspended; engine contracts retained | 2026-07-09 |
| M2 | Three roles: orchestrator(+director, see D1), author subagent, reviewer subagent — each with role-specific prompt, skills, tools; no overburdening | 2026-07-09 |
| M3 | **Filesystem access for ALL agents at all times** (workspace read-write; `knowledge_docs/` read-only via FilesystemPermission). Agents may read any knowledge doc at will; skills are entry points, not fences | 2026-07-09 |
| M4 | **Every agent's system prompt ends with an exhaustive resource map**: its tools, the workspace layout, the knowledge dirs, and what it does NOT have | 2026-07-09 |
| D3 | Author runs its compile→read-diagnostics→fix→recompile micro-loop INSIDE one invocation; writes full DSL source to a file every round. Context growth is watched via per-invocation token telemetry, NOT pre-capped — **no numeric halt-cap language in the author prompt** (user removed the "3 halts → stop" clause). Handling deferred to probe evidence | 2026-07-09 |
| D8 | **Round history is filesystem-canonical**: `rounds/round_N/{author_report.md, critique.json, direction.md, dsl.lumen, diagnostics.json, preview.png}` + `rounds/index.md` (one line per round: verdict + mistake-to-not-repeat). One typed state field `current_round`. Mandated-read protocol: author reads index + previous round's critique/direction/own report before authoring; reviewer reads its own previous critique before reviewing | 2026-07-09 |
| D9 | **Author gets `view`** (brand-kit asset previews + draft preview), same as orchestrator and reviewer. Pull-based; its resource map notes that images cost context — view what the task needs | 2026-07-09 |
| M5 | Cost/latency per turn is NOT a design constraint (user) | 2026-07-09 |
| M6 | Acceptance eval: the moda probe scenarios (P1 ellipse-logo, P2 deletion, P3 delete+add) + the K4 brand-fidelity eval, run against the old loop as baseline | 2026-07-09 |
| M8 | **Repository layout (reorg, user-directed)**: `apps/agent_runtime/lumen_agent/` is the LIVING deepagent package — `harness.py` (assembly+runner), `prompts.py`, `llm.py`, `workspace.py`, `config.py`, `models/` (state.py, schemas.py), `tools/` (substrate.py, view.py, render.py), plus copied support modules (brand_card, knowledge, retokenize, imagery_checks, imagery_judge). `apps/agent_runtime/lumen_pipeline_archive/` is the FROZEN old pipeline (renamed from `lumen_deepagent/`; see its README). **lumen_agent imports NOTHING from the archive — shared components are copies; fixes land in lumen_agent only.** Test fixtures for the living world: `tests/agent_fixtures.py` | 2026-07-09 |

### DECIDED 2026-07-09 (ratified by user; D7 amended)

**D1 — The orchestrator IS the director in v0 (no separate director subagent).**
Option A (recommended): the main agent reads the brief, looks at the canvas,
decides, briefs the author, judges the reviewer's verdict — director is a hat
the orchestrator wears, with continuous memory across the whole turn.
Option B: a separate director subagent — but subagents wake amnesiac each
invocation, so every consult requires full re-briefing, and every director
opinion crosses two extra prose relays (orchestrator→director→orchestrator→
author): the exact lossy-hop disease of the old pipeline. Reversible later
via `CompiledSubAgent` if orchestrator judgment degrades on long turns.

**D2 — Vision plumbing is spike-decided (capability is NOT in question).**
All four minds see pixels via a `view(target)` tool; the spike (S1) only
decides HOW image bytes reach the model over OpenRouter's OpenAI protocol:
(a) image blocks inside tool results — verified that langchain-openai
transmits them; whether OpenRouter/provider accepts them is untested; or
(b) guaranteed fallback: middleware injects the image as a user-message part
right after the view call (supported everywhere). Functionally identical to
the agents. Reference: https://docs.langchain.com/oss/python/integrations/chat/openrouter

**D4 — Context growth: filesystem offloading first; compression summarizer
(SummarizationMiddleware) armed on the ORCHESTRATOR ONLY as an emergency net.**
Files-first keeps every canonical artifact lossless (compression only ever
compresses conversation, never the record — nothing summarized is the only
copy). Author/reviewer are born fresh per invocation and need no summarizer.

**D5 — Model-facing tool surface for v0** ("killed" = off the model surface;
Python methods remain in the substrate for tests/editor/loop):

| Tool | v0 | Reason |
|---|---|---|
| `inspect` (scene/page/node_tree/geometry/slots) | all agents | queryable scene truth; its absence caused the P1 blind-coordinate bug |
| `view` (NEW: draft preview, kit-asset previews) | all agents | pull-based pixels (D2 mechanism) |
| filesystem ls/read/write/edit | all agents | M3 |
| `compile_dsl_block` | author | the one write path (DSL: create/modify/delete/reconcile) |
| `asset` (generate/place) | author | imagery is authoring |
| `validate_binding_set` | author | cheap self-check |
| `preflight_design` | author + orchestrator | self-verify + gate; contains deterministic retokenize |
| `render_preview` (merge of `export_preview` + `export_preview_bundle`) | orchestrator | one render tool, validated PNG/SVG to disk |
| `record_gap` | orchestrator | honest can't-do reporting |
| `finalize_run` | orchestrator | turn envelope for the API/editor |
| `get_preview_for_review` | killed | replaced by `view` |
| `submit_visual_critique` | killed | reviewer returns structured `VisualCritique` via response_format |
| `load_knowledge` | killed | skills middleware + direct knowledge reads (whole docs, not 800-char excerpts) |
| `recommend_edit_surface` | killed | deterministic classifier second-guessing the model (spoon-feeding class) |
| `create_repair_request` | killed | triple-nested-JSON relay; replaced by rounds/ files + direct briefs |
| `apply_operations` | killed (surface) | raw-ops escape hatch stays internal |
| `apply_structured_edit` | killed (surface) | DSL modify lines cover it; re-add on probe evidence |
| `derive_instance_preview` | killed (surface) | niche slot worst-case; re-add on demand |

**D6 — `SHARED_SURFACE_CONTRACT` survives verbatim in orchestrator + author
system prompts.** It is POLICY (who owns what on the shared surface; the
user's dictated rules from the round-5 win), not a rail. The CI test pinning
"contract present in both prompts, no duplicate policy elsewhere" carries over.

**D7 (AMENDED by user 2026-07-09) — the deepagent is the DEFAULT across all
places as soon as v0 lands.** The quality loop (`LumenQualityLoop`,
`create_provider_quality_loop`) is **ARCHIVED: kept in the codebase, wired
nowhere live** — not deleted, not used. The API entry
(apps/api/lumen_api/main.py:4023) routes to the deepagent harness. The loop
remains invocable only offline (CLI/tests) e.g. as the M6 eval baseline.

**M7 — All deepagent work happens on a dedicated branch**:
`agents/deepagent-v0` (branched from `agents/editing-roundtrip-v0` @ 7c96204).

## Context-transfer design (rides on D4/D8)

Three channels, governed by: **relays carry pointers; readers pull raw
artifacts. No mind ever consumes another mind's paraphrase of an artifact.**

1. **Typed state fields (constitution, tiny)**: `seeded`, `chip_target_node_ids`,
   `brand_kit_ref`, `artboard_id`, `turn_request` (verbatim), `current_round`.
2. **Workspace files (the record)**: `brief.md`, `brand_card.json`,
   `rounds/…` (D8), `previews/`. The scene is deliberately NOT a file —
   `inspect` is the live truth.
3. **Task-prompt relay (intent only)**: orchestrator→author briefs carry goal,
   subject node ids, constraints, and file pointers; returns carry a short
   factual report + pointers.

## Brand coherence layers (why no rails are needed for on-brand output)

1. Kit rides the run config BY VALUE (tokens, asset manifest, font spec).
2. Token system: engine-resolved `$…` tokens; undefined token = LUMB0301,
   kit mismatch = LUMB0101 (hard).
3. Deterministic retokenization inside `preflight_design` (tools.py:1968):
   raw values equal to kit tokens are mechanically rebound; the rest surface
   as LUMB08xx diagnostics.
4. Fonts: kit faces ride config; engine shapes with real bytes; fallback is a
   loud LUMS0100.
5. Teaching: `brand_card.json` (roles, accent, type roles, logo variants with
   color_mode/allowed_backgrounds) + `brand-and-tokens` skill.
6. Perception: reviewer compares the render against placed assets' SOURCE
   thumbnails; orchestrator/author `view` kit assets before choosing.
   Imagery selection flow: inventory (titles/descriptions/usage_note from the
   Slice-1 describe chain) → `view` candidates → place by `asset_id` via DSL
   (K2 auto-registration heals references).

## Spikes — ALL RESOLVED 2026-07-09 (scripts in .context/deepagent-spikes/)

- **S1 PASS (live)**: an image block inside a TOOL RESULT reaches
  `anthropic/claude-opus-4.8` via OpenRouter (model correctly described the
  image; user-message control also passed). **D2 resolves to mechanism (a):
  `view` returns image blocks directly in its tool result.** No injection
  middleware needed.
- **S2 PASS (live)**: a subagent with `response_format=VisualCritique` AND its
  own tools runs clean over OpenRouter on deepagents 0.6.12 / langchain
  1.3.11 — the old Anthropic-native "too many strict tools" trap does not
  reproduce. Finding: the structured object does NOT propagate into parent
  state (`structured_response` is an excluded key) — therefore the reviewer
  ALSO writes its critique JSON to `rounds/round_N/critique.json` itself
  (it has filesystem tools) and returns it in its final text.
- **S3 PASS (source-verified)**: `task()` copies the parent's FULL state into
  the subagent minus only `{messages, todos, structured_response}` + declared
  private keys (deepagents/middleware/subagents.py, `_EXCLUDED_STATE_KEYS`),
  and subagent state updates flow back the same way. Custom constitution
  fields (`seeded`, `chip_target_node_ids`, `brand_kit_ref`, `artboard_id`,
  `turn_request`, `current_round`) are visible to all minds' tools.

## Live proof + open hardening notes

- **First live turn (2026-07-09, run_921ab92): ACCEPTED.** Full round protocol
  exercised in the wild (direction.md → author 3-compile micro-loop → preflight
  → render → reviewer view-and-compare → critique.json → index.md verdict line
  → honest orchestrator finalize). Evidence: `.context/deepagent-v0/live-smoke-1/`.
- Hardening note: deepagents `FilesystemBackend` in non-virtual mode warns that
  absolute paths and `..` can bypass `root_dir` — the knowledge-docs write-deny
  holds, but a path-traversal guard is a future hardening item.

## Moda probe round 6 (2026-07-09, grok-4.5 — first kit round on the deepagent)

Evidence: `.context/deepagent-v0/probe-r6/`. **P2 (seed deletion): PASS
end-to-end** (explicit remove_node ×2, reviewer accepted 0.92). **P3
(delete+add, chipped): PASS end-to-end** (explicit delete + real kit product
screenshot + caption; 15 ops incl. 11 unprompted accommodation re-fits).
**P1 (logo in the human ellipse): honest FAIL at the finalize call — but the
design itself was solved**: mark placed EXACTLY centered in the human ellipse
(inspect + arithmetic; the round-5 blind-coordinate class is dead), the
reviewer caught the z-cover, the author built the moda-style light plate.
Residuals, both named:
1. **grok-4.5 runaway generation** (65,569 completion tokens →
   `LengthFinishReasonError`) on the orchestrator's finalize/structured call.
   Fix fork pending user: bounded `max_tokens` in `init_model` /
   tool-strategy structured output / per-role model choice.
2. **Engine gap (pre-existing, now precisely named by the agent itself)**:
   pinned-freehand nodes always paint last, so agent content cannot layer
   over a pinned human node — needs a `detach_to_freehand`/z-order mechanism
   (round-5 "cause B", documented in P1r6 round_3/author_report.md).

## Post-R6 decisions (DECIDED by user 2026-07-09, after probe round 6)

- **D10 — grok-runaway fixes: (a) + (c) now.** (a) `LUMEN_AGENT_MAX_TOKENS`
  output bound in the single `init_model` gateway (damage-limitation + retry
  enablement; one mechanism, all models). (c) per-role model choice:
  `LUMEN_AGENT_MODEL_ORCHESTRATOR` / `_AUTHOR` / `_REVIEWER` env knobs, each
  defaulting to `LUMEN_AGENT_MODEL`; per-subagent `model` in the harness.
- **D11 — tool-strategy structured output is the REMEMBERED fallback**: not
  implemented now; implement if a structured-output runaway/parse failure
  recurs on any model.
- **D12 — `detach_to_freehand(<node_id>)` becomes a DSL directive**, lowering
  to the existing core `StructuredEditInstruction::DetachToFreehand`
  (editing.rs:2780; builder already on the wire). This closes the P1r6
  doppelganger workaround class (pinned-freehand pass paints last; agent
  content could not layer over a pinned human node). **The cross-class
  z-index redesign is the REMEMBERED alternative**: open that discussion only
  if this incident class recurs after the directive ships.
- **P0 policy note (user, verbatim in spirit)**: the deepagent has real
  agency — do NOT add agent-side rails that prevent it from dealing with
  human-added nodes; trust it to handle human edits rationally. Engine
  contracts (explicit-delete for human content) remain; new protective
  fences on the agent surface do not get added.

## P1 rounds 7-8 (2026-07-10): the moda scenario PASSES end-to-end

- **P1r7** (max_tokens=20000 + detach directive live): agent used the taught
  recipe verbatim on first exposure (`detach_to_freehand(ellipse_mark)` +
  `after(...)`) — no ghosting, mark layered above the REAL human ellipse.
  Died at the reviewer's NATIVE structured output (`StructuredOutputValidationError`,
  unterminated JSON; zero length errors — the bound worked). D11 trigger fired.
- **D11 SHIPPED** (921308d): reviewer `response_format=ToolStrategy(VisualCritique)`,
  validation-retry on. Review fix: per-role-model tests isolate D10 env fields.
- **P1r8 = FIRST FULL END-TO-END PASS in 8 rounds** (evidence
  `.context/deepagent-v0/probe-r8-p1/`): 16 ops applied, doc v1→17, reviewer
  accepted 0.94/0 issues via ToolStrategy, zero structured/length errors,
  mark at the exact ellipse center, collateral announced honestly, ~9.4 min.
- **Open behavioral note (user to decide)**: r8's agent chose mute-pin +
  managed duplicate plate over `detach_to_freehand` (r7 chose detach) — both
  legal, ghosting disclosed. Candidate one-line teaching preference: "prefer
  detach_to_freehand over muting a pin and duplicating it — never leave a
  human node invisible." Not added; awaiting user call (no-rails philosophy).

## Tier-2 hygiene batch (2026-07-10, all SHIPPED)

- **W-A `5302eb8` — content-hash engine stamp**: both build.rs stamp from a
  sha256 of lumen-core src/**+Cargo.toml (shared hasher in
  crates/build_support/engine_stamp.rs); AGENTS.md/CLAUDE.md rules narrowed to
  "rebuild only when engine sources change"; live-proven post-commit with no
  rebuild (HANDSHAKE OK, stamp a510a90cea24 both sides). Known drift point:
  scripts/preflight_editor_wasm.mjs mirrors the hash closure in JS — widening
  the hashed crate set requires touching both (fails safe: needless rebuild).
- **W-B `eb0892c` — kit data chain**: republish re-runs the type-size ramp
  emission idempotently (Insight kit LIVE v4→v5, all 13 $type.size.* tokens;
  LUMB0301 class dead for legacy kits); LUMI0803 carries per-attempt HTTP
  status/exception reason; SVG raster glue fixed (two bugs declined EVERY svg
  — zero-page scene + wrong artifact key); play.svg captioned in v5.
- **W-C `ee11f35` — riders**: RepoRootedFilesystemBackend (post-resolution
  containment; escapes = model-facing errors; virtual_mode proven breaking for
  our absolute-path prompts); per-model-call token usage telemetry
  (`model_call_usage` trace events with per-role attribution) — the D3
  context-growth watch has data from the next live run onward.

## M6 CLOSED (2026-07-10, round 9b) — the pipeline is formally retired

Evidence: `.context/deepagent-v0/probe-r9b-sweep/`. Final stack (fc6a366,
grok-4.5 all roles, max_tokens=20000, ToolStrategy, detach directive, kit v5
re-attached per scenario and verified received).

- **Sweep 3/3, all single-round, 141-259s, zero structured/length errors,
  critiques accepted 0.90-0.95 with zero issues.** P1: human ellipse fully
  UNTOUCHED, mark placed as sibling via `detach_to_freehand` (the ideal
  mechanism, chosen naturally — detach adoption now 2 of 3 exposures),
  exact-center geometry. P2: exactly the 2 named seed nodes removed
  explicitly. P3: chipped CTA deleted + kit product screenshot in a
  $surface.card frame + caption bound to $type.caption/$text.inverse.
- **Fidelity read (the honest interpretation)**: all three score
  verdict=redo on typography_binding=0.0 — this measures the SEED's legacy
  debt (K3-era document, frozen literals predating retokenization), not the
  turns: every axis is IDENTICAL to the seed's own baseline score except
  P3's imagery_adoption which IMPROVED false→true; P1's "rogue paint" is the
  human's own ellipse fill. Correct comparison for seeded edit-turns is
  before-vs-after per scenario: ZERO degradation, one improvement. The K4
  pipeline baseline (1.0/1.0/1.0) was fresh-authoring and is not the
  comparable population.
- **First token telemetry harvest (D3)**: author is the heavy mind — P1
  author 1.65M input tokens over 21 calls (~78k/call; the ReAct micro-loop
  re-sends history per tool step); orchestrator 350-570k; reviewer ~300k.
  No action (cost unconstrained per user), recorded as the context-growth
  baseline; prompt-caching/effort-tiering are the known levers if ever needed.
- **Verdict: the archived pipeline never passed all three scenarios in any
  round; the deepagent passes 3/3 in one round each with honest statuses.
  M6 exit criterion met. The pipeline remains archived for history only.**

## Verified platform facts (2026-07-09)

deepagents 0.6.12, langchain 1.3.11, langgraph 1.2.7, langchain-openai 1.3.3.
`create_deep_agent` supports per-subagent tools/skills/model/middleware/
response_format, custom `state_schema`, `backend`, `CompiledSubAgent`,
`FilesystemMiddleware` (+permissions), `SummarizationMiddleware`.
langchain-openai transmits non-text content blocks in tool-role messages
(provider acceptance untested — S1).
