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

## A0 suppressors + A1a loud measurement (2026-07-10, gate-R verified)

Sweep-suppressor and hygiene slices shipped in one wave (5 reviewed build
agents; every diff read + independently re-tested before commit). Details in
`.context/next-wave/` slice notes. The class rule throughout: silent
degradation becomes either correct behavior or a loud machine-readable
diagnostic.

- **LUME0213 (error)**: a specified paint that fails to resolve at raster
  paints an opaque magenta sentinel — never silent black. Root cause of the
  sweep's "black PNG" class: the rasterizer never resolves tokens; unresolved
  paints were skipped over a transparent surface (flattens black; SVG's
  fill="none" reads white — the SVG-fine/PNG-black asymmetry). Raster surface
  now clears to WHITE paper; empty pages render white (A1 replay verified).
- **Per-glyph font fallback** (deterministic, loaded faces only) + LUMS0103
  warning naming substituted chars; tofu is structurally dead. LUMS0102
  (warning): any layout/preflight/export pass measured without font shaping
  announces itself; `TextMeasureOutput.diagnostics` channel also surfaces
  LUMS0100 from measurement (closes the gap Track B independently found).
  Wasm read-only preflight suppresses LUMS0102 (heuristic is its declared
  mode; editor synthesizes EDITOR_HEURISTIC_MEASUREMENT + loud banner).
- **LUMI0806 glyph-coverage audit** at ingestion + republish backfill; real
  kit replay: Aeonik missing 41 required glyphs (not 3 — the subset is far
  more aggressive than the sweep surfaced). Brand card carries font-gap notes
  + image inventory raised to 16 with explicit truncation line.
- **view() hardening**: sub-512px images upscaled before attach (+ thumbs.rs
  producer floor 512), any view failure returns an honest error string —
  provider rejections can no longer kill turns (A2 class dead). view("preview")
  refuses stale renders (mutation-count stamp) instead of serving old frames
  (A3 stale-black class dead).
- **Finalize hygiene**: zero-children pages pruned via ledger-riding
  remove_page ops, announced in the summary; brand_logo_auto is place-once +
  respect-removal (re-injection root cause: presence-only check per preflight).
- **Follow-ups CLOSED 2026-07-10** (commits 055264d + 4ff9bae): export now
  REFUSES unresolved token paints with the offending (node, token) pairs and
  the run-preflight_design-first directive (refusal chosen over auto-resolve
  to preserve resolution-once ordering: retokenize-on-authored-scene, the
  authored_scene.json snapshot, governance); the multi-page-slots fixture is
  de-tokenized (baseline is a real cream/teal design again; sentinel behavior
  stays pinned by raster unit tests). API document export verified SAFE
  (preflights before render); stateless /export-preview fails loud via
  LUME0213. Remaining env note: editor test env lacks canvaskit/wasm-core
  artifacts (26 pre-existing EditorApp test failures, environmental).

## A4 Effects v1 (2026-07-10, gate-R verified)

The engine's effect vocabulary grows from one kind to four — glow, layer blur,
inner shadow join drop shadow — end-to-end (scene model, DSL, validation, SVG
filters, Skia image-filters, CanvasKit editor canvas, render-contract honesty)
plus the three ledgered debts. Three build agents (engine/editor/knowledge),
every diff read + independently re-tested at the review gate; the gate itself
caught and fixed four defects that survived the builders' green suites (SVG
blur-only stacks output the blurred ALPHA — a black silhouette — by
last-primitive semantics; the mixed-corner SVG path's left edge ran to
height−tl producing an impossible arc; Skia rounded a zero corner under
stroke-alignment delta where uniform kept it square; per-corner `rd` rejected
literal 0 via parse_positive_f64, making "round only the top" uncompilable —
found by the knowledge builder's mechanical validation protocol).

- **D1 stacking contract** (pinned by an SVG↔Skia parity test with pixel
  probes): source → layer blurs → shadows/glows computed FROM the blurred
  alpha, merged beneath → inner shadows over, clipped to alpha. First effect
  of each class = topmost of its class. Pure drop-shadow stacks keep
  byte-identical pre-A4 markup/filters.
- **DSL**: `glow(id?,#c,o(),blur(),spread())` (x/y rejected — LUMD0266),
  `blur(12)`/`blur(id,r(12))` (LUMD0267), `inner_shadow(...)` mirrors shadow
  (LUMD0268); `rd(tl,tr,br,bl)` per-corner (≥0, CSS clockwise; SVG emits a
  <path>, Skia per-corner RRect, CSS overlap clamp both sides);
  `solid(#hex,0.5)` lowers opacity into color alpha (LUMD0270; LUMD0241
  retired); node `bleed(true)` declares off-canvas intent → LUMV0800/0801
  downgrade to warnings (LUMD0269 disambiguates the two bleed forms).
  LUMV0704: negative blur/radius/spread rejected.
- **Fail-loud riders**: LUME0214 text-strokes-dropped advisory from BOTH
  exporters; SVG gradient stops with alpha emit stop-opacity (max-compat);
  PDF marks all new effects Unsupported → LUMX0002.
- **Editor canvas is FAITHFUL, not approximate**: CanvasKit general pipeline
  mirrors lumen-skia (inner shadow via erode→offset→blur→SrcOut→SrcIn recolor;
  outer spread via MakeDilate/MakeErode — the design's "no dilate in
  CanvasKit" premise was wrong, so the planned spread-approximation
  diagnostic was deleted rather than shipped). Per-corner contour shared by
  body + clip. spreadApproximated flag remains only on the legacy Konva view.
- **Teaching**: effects SKILL rewritten (glow/blur/inner-shadow as core
  vocabulary, taste rules ban clichéd uses not constructs), grammar +
  diagnostics rows, numeral-hero glow variant + true-bleed soft-wash in the
  archetype canon; 6/6 exemplars mechanically validated (compile → preflight →
  render non-black) with evidence at `.context/next-wave/a4-teaching-evidence/`.
- **Deferred with intent** (coverage audit at
  `.context/next-wave/a4-effects-coverage.md`): blend modes, masks, backdrop
  blur, pattern/image paints, color filters, conic/mesh/noise gradients, and
  the effect-token façade (schema + ingestion evidence exist; ingestion emits
  {}, collect_scene_token_references skips node.effects, color_token unread —
  wiring is future work, recorded here so the façade isn't mistaken for a
  capability).

## W-isolation: the deepagent's isolated virtual workspace (2026-07-11, gate verified)

The deepagent now runs on ONE dedicated workspace (`<repo>/.deepagent-workspace`,
`lumen_agent_workspace_root` overridable; old `lumen_agent_trace_dir` still wins
for back-compat): `AgentWorkspaceBackend(FilesystemBackend, virtual_mode=True)`
roots there, so the agent's `/` IS its workspace — `/.deepagent/` (AGENTS.md +
skills), `/knowledge_docs/` (full synced copy), `/run_<id>/` (every run artifact:
workspace, rounds, previews, iterations, trace.jsonl, final.json, ledger). The
"path outside permitted root" class is retired: stock virtual mode re-anchors and
contains (verified against deepagents 0.6.12 source), `paths.normalize_agent_key`
forgives host-absolute/legacy forms (never collapsing `..` — a traversal can't be
laundered into an escape), `to_virtual` renders tool-return paths in the model's
namespace, and prompts speak only virtual paths with an explicit contract line.
Skills/knowledge are materialized from the repo tree (single source of truth,
never written back) behind a content-hash stamp — identical sources ⇒ 2ms no-op.
The API seam is untouched: envelope/ledger/preview paths stay host-absolute
(both suites green: agent-runtime 361, api 288).

Two review-gate finds worth remembering:
- **The old per-skill-dir `skills` wiring was a silent no-op.** SkillsMiddleware
  treats each source as the PARENT of skill dirs (dir children with SKILL.md);
  pointing it at a single skill dir loads NOTHING — so no skills ever loaded via
  the middleware before this slice. The flat `/.deepagent/skills` parent now
  loads all of them (progressive disclosure), both subagents.
- **Bare-directory legacy forms** (`ls` on `.../knowledge_docs` with no trailing
  slash — the exact live failure of 2026-07-10) needed their own normalization
  case; marker-substring matching alone missed them. Regression-pinned.

Behavior note: author/reviewer now see ALL skills via progressive disclosure
(name+description until invoked) instead of the old per-role lists — the role
prompts still name each role's primary skills. `.env`s carrying the old
`LUMEN_AGENT_TRACE_DIR=.lumen-runs` default should unset it to get isolation.

## Observability: structlog + CLI message tracing (2026-07-11, gate verified)

One shared module (`py_lumen_obs/`, commit 5cc24f7) owns ALL logging: the sole
structlog.configure, stdlib bridge (uvicorn included), LUMEN_LOG_MODE
info|debug, mode-independent redaction (secrets masked even in debug; base64 →
placeholders; message content never redacted), per-handler truncation (console
truncates, run-file never), contextvar binders, log_span, pytest capture.
Adoption (d68bd1c): every run writes `run_<id>/logs/run.jsonl` (full detail,
wired at run_deepagent_turn so CLI and API turns both get it); cli defaults
debug; log_span on all agent-visible tools + a single _CoreHelperProxy seam —
a hung helper/LLM call is now a `*_started` with no completion (hang
forensics for the 2026-07-10 silent-hour class). TraceCallbackHandler per
role (images placeholdered BEFORE logging since content is redaction-exempt)
+ `python -m lumen_agent.trace <run_id> [--follow|--full|--role]` renders the
role-colored conversation timeline with token/duration totals (rich, ANSI
fallback). API side (190887b): lumen_api's private formatter deleted,
request_id is a contextvar, uvicorn bridged (only its two pre-lifespan boot
lines stay raw), debug http_request_summary on /agent + /documents.
Suites at gate: agent-runtime 411, api 291 (+3 new), zero regressions.
Still open (awaiting user go): init_model timeout/retries + turn wall-clock
watchdog — tracing makes hangs visible; the watchdog will make them
fatal-fast.

## Track A — A6a Typography v1 (2026-07-11, gate verified)

Engine (see commit for the diagnostic map): `case/text_transform`, `underline`,
`strike`, `truncate/ellipsis`, `para_spacing` land as serde-default TextNode
fields — old scenes bit-identical — flowing DSL → both measurers → SVG/Skia/PDF
under one contract; text strokes RENDER (LUME0214 retired; first-solid-only
with LUME0215 for extras; PDF advises LUME0421/0422/0423 instead of silent
drops); LUMS0104 surfaces the silent within-family weight snap; render
contract gains the five text features; SVG/PDF exports fold measurer
diagnostics (the reachable LUMS0100/0103 loss on direct exports is closed).
Editor: CanvasKit byte-mirrors the engine recipes (transform twin fixture-
pinned against Rust, decoration, native ellipsis, stacked paragraphs under a
TOTAL max_lines budget, two-pass stroke), the 4-bucket weight snap is dead
(exact numeric weight in paint + measure), and TextSection/TextToolbar expose
the new controls. Teaching: taste-first vocabulary (tracked-caps eyebrow,
single underline accent, semantic strike, truncation-as-honesty, lh vs
para_spacing) with 10/10 exemplars compile→preflight→render validated.

Review-gate record — four real bugs caught after green builder suites, all
cross-backend divergence class: (1) raster painted lines the measurer/SVG cut
under stacking+max_lines (pixel-proven); (2) elided line text overflowed its
bound in markup while the raster elided natively (measurers now refit);
(3) NoWrap+truncate meant three different things in three components (unified:
per-line elide at the bound, pixel-probed as SkParagraph's native behavior);
(4) taffy whole-pixel geometry vs fractional stacked heights fired a false
LUMV0903 on every hugged para-spaced body — found by the K-A6 exemplar
validation protocol, fixed as a rounding-tolerance in the layout overflow
fold (a sub-pixel overflow is the rounding contract, not content loss).

DEFERRED, on the record so schema is never mistaken for capability: variable-
font axes (zero VF files server-side; the editor's InterVariable.ttf is an
asymmetry, not a feature), italic (zero italic faces in the 104-face library;
kit FontFace.style is written-never-read; Slant::Upright hardcoded ×3),
vertical align, token channels for the new fields, slot
OverflowPolicy::Ellipsis → node-truncate reconciliation, CanvasKit
RenderTarget in the render contract, NoWrap+truncate+max_lines multi-hard-line
raster/measure drift (rare, accepted). NEXT: A6b rich-text spans (two-color
headline) as its own designed slice, then the A5 full re-sweep.
Gates: cargo workspace 0 fail · helper release · HANDSHAKE OK fafdf01f4251 ·
agent-runtime 411 · api 291 · editor tsc + targeted green.

## Track A — A6b Rich-text spans (2026-07-11, gate verified)

The two-color headline lands: `TextSpan` sub-ranges of one text node override
fill / weight / underline / strike. DSL: `[[…]]` content markers + repeatable
`span(fill(...), weight(...))` (COMMA-separated channels — the teaching
protocol caught the space form failing); markers stay literal without span().
Segmented SkParagraph measurement (push_style + get_rects_for_range run
boxes), per-run SVG tspans at absolute x, PDF advises LUME0424, span fills
join token resolution/governance. Diagnostics: LUMD0272/3/4, LUMV0906 (span
shape, layout gate), LUMV0907 (spans+para_spacing gap not applied in v1 —
loud), LUME0424. Editor renders parity (segmented CanvasKit paragraphs,
span-keyed measurement records via the extended ProvidedMeasurement bridge);
no span-authoring UI in v1.

Review-gate record: ED-A6b's assigned investigation PROVED the D4 honesty gap
live — the editor's whole-kind updateTextNode replace bypassed span clearing,
carrying stale offsets onto new content. Fixed at the engine seam beside
clear_stale_tokens (operations.rs): content change + unchanged spans = stale
carry-forward, cleared; re-authored different spans survive; undo restores.
Also fixed at review: the silent spans×para_spacing gap-drop (→LUMV0907), the
bridge's hardcoded spans:[] (spanned nodes could never get editor-provided
shaping), and the untested LUMV0906 gate emission. Teaching protocol catch
count now: A4, A6a, A6b — three for three.

Deferred (ledger): per-span family/size/ls/lh, nested spans, span gradients,
span-authoring UI, spans on DSL modify lines (LUMD0903 route; ops carry span
edits), spans×paragraph_spacing composition, heuristic soft-wrap of spanned
text (LUMS0102-class approximation; editor now bridges real shaping).
Gates: workspace 0 fail · helper release · HANDSHAKE OK b5f0b3d093c1 ·
agent-runtime 411 · api green · editor tsc + targeted · 6/6 exemplars VALID
(two-color pixel-proven). A6 COMPLETE (A6a+A6b). NEXT: the full A5 re-sweep
(SWEEP-SPEC verbatim vs the 1.22/3 baseline), then output-quality work.

## Track A — A7a Vertical alignment (2026-07-11, gate verified)

Text valign lands: `valign(top|center|bottom)` positions the text block
inside its OWN Fixed/Fill-height box. D2: `center` canonical, NO aliases —
the scene model already says Center for the vertical axis (LayoutAnchor via
`y(c)`), so ONE word for "centered" across the grammar and the recorded
`va(center)`/`valign` hallucination trap ceases to exist; `valign(middle)` →
LUMD0275, arity → LUMD0230, wrong target → LUMD0607. D3: ONE shared formula
`lumen_core::valign_offset` = `max(box_h − content_h, 0) × {0, .5, 1}` —
clamped, so overflow degrades to a no-op and LUMV0903 fires unchanged; hug
height = zero slack = silent no-op (D6: editor control disabled + tooltip).
D4: valign is NOT a measurement input (absent from TextMeasureInput /
measure_key / the TS bridge) — the wasm seam untouched. Serde: A6a additive
pattern, absent = Top, old scenes byte-identical, SCHEMA_VERSION still 1.
Painted on all raster paths (fast/stacked/spanned), SVG + PDF exporters,
editor CanvasKit twins, TextSection select + TextToolbar icon group,
TextEditOverlay computed paddingTop. Konva leg (test-only, frontend-practices
§4) delegates to Konva's builtin verticalAlign — its real line layout beats a
formula with no measurer; divergences documented in-code.

Review-gate record: the adversarial round (two independent refuters) CONFIRMED
one HIGH cross-backend bug post-green-suites — the A4/A6a/A6b pattern now four
for four. Stacked path under a max_lines cut: the raster/CanvasKit pre-pass
counted a trailing paragraph gap after the last painted paragraph;
measure_stacked (SVG/PDF's measured.height) ends at the last visible line's
bottom → export sat a FULL GAP lower than canvas/raster for bottom. Fixed:
gap-BEFORE accumulation between consecutive painted paragraphs only, in
render.rs AND drawDescriptors.ts; pinned by
stacked_valign_bottom_with_max_lines_cut_excludes_the_trailing_gap and the
rerunnable cross-backend gate (13 cells, PNG/SVG/PDF exact to 0.01px,
.context/next-wave/a7a-gate-evidence/). Also fixed at review: the edit
overlay's scrollHeight floor bug (clientHeight floor meant paddingTop stayed
0 — zero-height read fix) and the Konva-leg no-op (formula had no content
height there). Browser verification 8/8 (staircase, controls, D6 disabled
state, overlay centering live, trailing-gap cell at box bottom). Found &
recorded: a RUNNING local API on :8000 changes one EditorApp unit test's
outcome via .env.local base URL — pre-existing test-hygiene quirk, not
valign; the 26 canvaskit-ENOENT EditorApp/Wasm failures are the known jsdom
baseline, byte-identical pre/post.

Deferred (ledger): valign token channel; reconcile/DOM→scene CSS mapping
(flex align-items → valign); heuristic-measurer export drift for
center/bottom (pre-existing measurer-honesty seam — loud-measurer slice);
f32 sub-pixel casts; control enabled on zero-slack Fixed boxes (dead knob).
Gates: core 473 · skia/export/assets 193 · helper release · HANDSHAKE OK
4d619841f3a8 · agent-runtime 411 · api 291 · editor tsc + vitest 716 (26
known baseline) · parity gate PASS · browser 8/8. Design + as-built REVIEW
AMENDMENTS: .context/next-wave/a7a-valign-design.md. NEXT: A7b italics
(span rider + provisioning; 17/27 families have italic VFs in the pinned
clone).

## Track A — A7b Italics (2026-07-12, gate verified)

Italics land end-to-end: block `italic(bool)` + span channel `italic(bool)`
with OVERRIDE merge (`span.italic.unwrap_or(block)` — deliberately unlike the
union-merged decorations; `span(italic(false))` de-italicizes a run inside an
italic block, mirroring weight, the other geometry channel). Italic IS a
measurement input (the second per-run geometry channel after weight): it
joins `measure_key` + `spans_digest` + both measurers + the wasm
ProvidedMeasurement bridge — pre-A7b editor payloads still hit their keys
(serde defaults align both sides). Font resolution is byte-driven: LoadedFace
parses slant at registration, `match_typeface(family, weight, italic)` +
`resolved_slant` mirror the weight machinery; **LUMS0105** advisory (italic
requested, family has no italic face, upright used) beside LUMS0104;
**LUME0425** PDF loud-drop beside LUME0424. Library: 22 italic faces
provisioned from the pinned clone (17 families; serif core 400/600-700 cuts,
sans/slab/mono 400; display families have none — no sources), upright
manifest entries byte-identical, `_w400i_` style-tokened asset ids,
inventory doc gains an Italics column. Editor: CanvasKit slant on all
paragraph builders, DOM FontFace descriptors (kills the (family,normal,400)
collision), toolbar Italic button + inspector toggle, italic edit overlay,
Konva combined font string.

Review-gate record — the adversarial protocol is now FIVE for five (A4, A6a,
A6b, A7a, A7b), and A7b's catch is the sharpest yet: **SkParagraph applies a
SYNTHETIC oblique for an unsatisfiable italic slant** (it does not snap to
upright like typeface-level matching), so a no-italic family rendered
SHEARED glyphs on the server raster AND the editor canvas — violating the
user-ratified no-synthetic rule and falsifying LUMS0105's message. Caught by
the gate's twin cells (missing-italic vs upright pixel diff 0.0996 ≈ a real
italic's 0.1075), independently suspected by the parity refuter on the SVG
side. FIX: a face-availability synthesis gate at every style seam — engine
`build_paragraph` (one gate covers base/stacked/segments), SVG emission via
the new `TextMeasurer::has_italic_face` trait method, editor via
registration-tracked `hasItalicFace()` — pinned by
missing_italic_face_renders_upright_not_synthetic_oblique (0 differing
pixels), svg_font_style_is_gated_on_a_real_italic_face, and gate cells
r7/r8 (missing-italic diff now 0.0000). Also fixed at review: LUME0425
false-positive on span(italic(false))-over-upright (condition == Some(true)
+ guard test). Refuters: no contract defects (serde, echo-loop, 7-site
merge, split-name family keys, advisory composition all verified). Accepted
residuals on record: kit faces lacking style metadata under-report the
editor-side gate (renders upright there; kit-ingestion fast-follow);
LUME0425 over-fires on a fully-de-italicized italic block (harmless,
comment-honest); italic_weights not validated ⊆ weights (current data
verified); heuristic measurer models no italic width delta (existing
approximation class).

Browser gate 7/7 (Lora italic live on toggle + overlay; Manrope stays
upright on canvas while controls show intent — the honest split; span +
de-italicize cells correct; no new console errors). Teaching: exemplar
pixel-proven (3.28% diff vs upright-stripped), OVERRIDE seam + no-synthetic
rule taught; the A6b "nothing that would reflow line metrics" span sentence
amended. Gates: core 476 · skia/export/assets 208 · helper release ·
HANDSHAKE OK 62e8e60efeb4 · agent-runtime 411 · api 296 · editor tsc +
vitest 730 (26 known baseline) · 19-cell parity gate PASS · provisioning
--check OK. Design + amendments: .context/next-wave/a7b-italics-design.md;
evidence: a7b-teaching-evidence/ + a7a-gate-evidence/ (gate.py now covers
valign + italics). NEXT: per-span metrics + VF axes stay parked; kit-style
metadata fast-follow on record.
## RC — Reference-conditioned design (roadmap A7; 2026-07-12, acceptance-gated)

The rec-2 capability lands: user-attached reference images ride the turn as
first-class inputs, all three minds see the pixels, and the loop is judged —
deterministically — against them. Channel: paperclip + thumbnail chips in the
chat composer (uploads via POST /assets, tags reference/chat-attachment; kind
is engine-classified — AssetKind has no reference variant, tags carry it),
`reference_asset_ids` (≤4) on the turn request → resolved BY VALUE into
`config.reference_assets` (contract frozen in config.py: always-raster
preview_digest — SVGs engine-rasterized at resolve, atomic content-addressed
writes — dominant colors, advisory describe text, attachment order; unknown
id / too-many / broken preview = hard 422 at the route boundary). Runtime:
`view("reference:<n>")` for orchestrator/author/reviewer; scaffold writes
references.md (metadata only, loudly non-load-bearing); the DIRECTOR writes
reference-brief.md from pixels (no one-shot captioner — cheap perception IS
the rec-2 failure), naming defining qualities on open-ended axes
(IMAGE-TYPE-AGNOSTIC per user amendment: a type poster, a product photo and
a wash have different defining qualities — perceive what is there);
reviewer fills VisualCritique.reference_fidelity (0-3 + reasons +
regressed_to_house_style); fidelity ≤1 blocks. No-references turns are
byte-identical to pre-RC (prompts pinned against git-HEAD bytes; scaffold
pinned; state.json gains only the neutral empty field).

Review-gate record — the adversarial protocol is now SIX for six, and this
round's finds were textbook survive-green-suites defects: (1) the LIVE
/agent/turns route swallowed the reference 422s (run row created before
validation; worker catch-all → generic "crashed"; only the sync route tests
exercise honored them) — fixed: resolve in the handler before create_run,
manifest rides into the worker; pinned end-to-end. (2) The editor queue
dropped/cross-mixed references (queued messages carried no snapshot; drain
read the live set the prior turn's success-clear had wiped) — fixed:
enqueue-time snapshot owns the attachments, id-scoped success-clear; pinned
by two queue-lifecycle tests. (3) THE central risk, confirmed: the fidelity
gate was vacuously bypassable (Optional reference_fidelity omitted →
"never accept while ≤1" true by vacuity = the moda rubber-stamp reborn) —
fixed at BOTH levels per the root-cause rule: a deterministic finalize_run
guard (accepted + references requires explicit score ≥2, actionable refusal
otherwise; the tool-level twin of the edit-scoped acceptance refusal) + the
prompt gate naming omission itself a blocker; five finalize tests pin it.
(4) The AUTHOR — the mind that can bake injected text into the canvas — was
the only one missing the injection-scoping line; fixed. Minors: raster
missing-blob now 422s like the SVG branch; the deliberate
LUMEN_AGENT_ASSET_STORE override exception documented.

ACCEPTANCE GATE (the rec-2 test, live, 3-for-3 browser turns on grok-4.5):
(1) two soft-wash references + moda's exact prompt → reference-brief.md
named the true qualities (oversized dissolving orbs, diagonal counterweight,
low-chroma sage/sand, "never scattered small blobs, never confetti");
round-1 fidelity 2 ("adopts the language without matching the atmospheric
strength") BLOCKED acceptance and drove round 2 → fidelity 3, accepted;
final render IS the reference vocabulary. (2) Generality (user amendment
proven): a brutalist type-poster reference → brief perceived a completely
different vocabulary (monumental caps, hard mechanical edges, black voids,
single lime bar) → output transferred the STRUCTURE to new meetup content,
fidelity 3. (3) Control turn without references: no RC files, normal
behavior, attachments note absent. moda's rec-2 failure (palette-only
reduction → house blobs → "no problems detected") is now structurally
impossible to rubber-stamp: the reviewer must look, must score, and
finalize refuses without it. Evidence: .context/next-wave/rc-gate-evidence/
(refs + 10 browser screenshots + run ids b07a4fa9/6a09edd0/900e110e).

Observed residuals (recorded, not RC): clarification tool payload rejection
advisory on the control turn (pre-existing class); the stale-wasm banner at
gate start (rebuilt per AGENTS.md §1, HANDSHAKE OK before any turn).
RC2 decision point deferred: image-gen conditioning via the edit path,
DET∧JUDGE palette composite, A8 multi-concept interplay, attachment-library
curation. Design + as-built amendments:
.context/next-wave/rc-reference-conditioned-design.md.
Gates: api 299 · agent-runtime 430 · editor tsc + vitest 731 (26 known
baseline) · acceptance 3/3.

## RC2 item-1 — Reference-conditioned image generation (2026-07-12, live-proven)

The lying field dies: `generate()` gains the real bytes channel
(`reference_images`, multimodal references-first-instruction-last with an
explicit STYLE-REFERENCES-generate-NEW framing; `edit()` untouched — its
"modify THIS image" semantics are the opposite), and `/assets/generate`
resolves its previously-inert `reference_asset_ids` through the RC manifest
machinery (same hard 422s, same SVG rasterize). The deepagent's
`generate_image` auto-conditions on the turn's references
(`condition_on_references=true` default — forgetting is the rec-2 failure
mode; opt-out for briefs that deliberately diverge), resolving order-sorted
preview bytes runtime-side (the by-value manifest; a mid-run-missing blob is
skipped WITH its digest so the cache key matches what actually conditioned),
stamping honest provenance ("reference-conditioned on N attachment(s): …").
Cache keys gain `reference_digests` (sorted, only-when-truthy — pre-RC2 keys
byte-identical, hand-proven). Teaching: subject in the prompt, style from
references + brand_notes; never re-describe the reference style in prose.

Refuter round: NO blockers. Top suspicion (stale-cache poisoning — pre-RC2
inert-field entries with ids in the key but unconditioned pixels) REFUTED by
hand-built hash proof: a conditioned request always carries digests, so its
key diverges from every inert-era entry. Verified clean: no-references
byte-identity both paths, images/digests desync impossible (one loop),
edit isolation both levels, route/runtime 422+order parity, dead
both-set provider branch harmless. One honesty fix applied from the round:
the stub-fallback warning names "(reference conditioning lost)" when a
conditioned generation degrades. LIVE PROOF (gemini-3-pro-image): same
wellness-texture prompt plain vs conditioned on the wash references —
default busy watercolor vs the references' soft-orb vocabulary
(.context/next-wave/rc-gate-evidence/imagegen/). Gates: api 309 ·
agent-runtime 434 · zero regressions. RC2 items 2-4 stay parked
(DET∧JUDGE palette, A8 interplay, attachment curation).

## Latency Tier 0+1 — L0 enrichment · L1 cache pinning · L2 batched reads · L3 watchdog · L4 raster/re-review guards (2026-07-12, acceptance-measured)

Diagnosis first (three-explorer evidence, .context/next-wave/
deepagent-latency-analysis.md): LLM inference is 93–97% of turn wall-clock
(tools 4–5%), wall ≈ call-count × ~7.2s (r=0.944), and each turn re-sent
3.2M–12.9M input tokens COLD (53–128× the output) — no prompt caching, no
per-call timeout, one tool call per completion, plus two runs that burned
whole rounds re-reviewing a black-raster frame. Quality was ruled invariant:
no round caps, no weaker models, no skipped verification anywhere in the tier.

The four slices (`0a8458d` → `7b0fc24` → `7a83450` → `5e28d5a`): **L0** —
`model_call_usage` gains duration_ms, served model_id, cached/reasoning token
counts (+ OpenRouter `usage:{include:true}`); every later claim is measured
against these fields. **L1** — OpenRouter `provider:{sort:"latency"}` pins one
xAI replica; probe-proven 2/8 → 8/8 cache hits on a byte-identical 30K prefix
(sort ALONE suffices; allow_fallbacks kept). The append-only-history
cache-stability invariant is documented in harness.py — L5-style pruning must
append, never mutate. **L3** — per-call timeout 60s + max_retries=2 (both
blank-disable); exhausted retries land in the pre-existing honest
failed-finalize path (now pinned by test). **L2** — batching teaching in all
three role prompts (read-only view/inspect/read_file fan in ONE response;
never-batch list: task, compile, render, preflight, asset, writes) after a
live probe showed grok-4.5 emits 6 reads in one completion 3/3; langgraph
executes batches concurrently with deterministic result order (cache-safe);
`record()` gained a lock for the now-concurrent tool threads. **L4** — the
PNG-black class was already root-cause-dead (925bdec white-clear+magenta
sentinel, 055264d token-paint refusal; investigator reproduced the old bug
and proved the fix live); the residual hole is closed: ≥99% sentinel pixels
⇒ hard validation_error (frame never reaches review as ok), ≥99% near-uniform
⇒ loud NON-blocking warning (minimalist designs stay legal). Unchanged-scene
re-renders surface a deterministic `unchanged` fact + trace event and the
orchestrator is taught to reuse the standing critique — advisory, not a hard
block, so the RC anti-rubber-stamp REFUSED→re-review path cannot deadlock.

ACCEPTANCE (one live turn, fresh server from HEAD; sample-not-proof):
93.1% cached prefill (author 95%; a 132K-token call paid ~2.7K uncached);
uncached input 0.22M vs 3.15M total; 4.98 s/call mean, p50 invoke 3.35s;
zero >60s stragglers; guards clean; enrichment on 60/60 calls. Wall was
4.98 min at 60 calls — call-count variance, the known #1 driver, not a
per-call regression (a stale-server control run of the same brief: 36 calls,
3.32 min, 0% cached). OPERATIONAL TRAP the acceptance surfaced: a
long-running API serves pre-tier code — restart the API after pulling these
commits or none of this fires. Tier 2 (L5 context pruning, L6 image
downscale, L7 per-role reasoning) stays parked pending drift evidence and
calibration A/Bs. Gates: runtime 474 · api 309 · zero regressions; no engine
sources touched (no wasm/handshake implications).

## Live design streaming — moda-parity build theater (2026-07-13, live-verified)

The turn becomes watchable: silent planning (checklist + lock pill, canvas
untouched) → structure-first artboard placeholders → element-by-element
materialization with a create-flash + gliding design cursor (Cursor accent,
SVG-overlay only — zero wasm-paint changes) → narrated banner substatus →
viewport auto-follow (user pan/zoom wins, permanently per run) → review
phase → unlock into the unchanged Before/After gate. Design doc:
.context/next-wave/live-design-streaming-design.md (D1–D8, from frame-by-
frame study of the moda/brilliant recordings; the element-by-element feel is
client-side theater over per-compile ops batches — perceived latency, zero
agent-latency cost by construction).

Four slices + a fix round (`6220c76` S0 server: clean-compile/asset ops ride
the existing durable run-events SSE pipe — the exact ledgered list, so
streamed == what Accept replays; refused drafts stream nothing; 250ms poll →
`0069e09` S1 editor core: progressive engine apply from an arm-time base,
terminal reconcile resets to base BEFORE the canonical previewAgentProposal
(streamed state can never leak into Accept; pinned) → `8f6a92b` S2 theater:
paced pump (~100ms/op, 5s per-batch cap, new-batch fast-forward), reveal
chrome, auto-follow, all CSS in new agentStreaming.css — six parked restyle
files untouched by construction → `5a039f1` fix round).

Adversarial protocol went 7-for-7: two independent refuters over the full
diff CONFIRMED a HIGH behind green suites — the reload-mid-run path settled
against the live (streamed) scene, so a failed-draft resume pushed the
half-built streamed scene into durable undo history. Class-fixed: the
pre-turn seed is captured explicitly at arm time and every settle path
consumes it (closure-staleness class dead, refuter repro flips fail→pass).
Also from the round: fit-buttons latch the auto-follow override,
prefers-reduced-motion support, mid-run doc-sync fallback pinned to the
seed, one-connection SSE polls, dangling-reveal cleanup.

LIVE PROOF (fresh servers from HEAD, real grok-4.5 turns, evidence
.context/streaming-verify/01–12): planning-silence + edit-lock PASS;
element-by-element streaming with live layer-tree fill PASS (flash/cursor
DOM-asserted 80×); substatus PASS; auto-follow PASS (user-wins proven by
code + unit test; toolbar staging limited the live check); paint cost p95
9.3ms / 0 long-tasks during the fastest cadence (refuter F4 closed);
reconcile integrity PASS (streamed state pixel-consistent with the canonical
After); Accept persists through reload; reload-mid-run re-attaches, settles,
and undo restores ONLY canonical state (the fixed HIGH, proven live).
Verifier also caught + fixed a stale-wasm handshake before browser work
(rebuild → HANDSHAKE OK). Known tuning residual: reveal pacing reads
brisker than moda's cadence — a taste knob (REVEAL_CADENCE_MS/cap), not a
correctness item. Gates: runtime 479 · api 311 · editor streaming suites
78/78 + tsc/lint clean; full-suite editor failures byte-identical to the
known environmental baseline.
