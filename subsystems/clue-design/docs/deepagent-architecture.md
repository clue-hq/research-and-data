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

## Spikes (before the architecture doc is finalized)

- **S1**: live OpenRouter test — do image blocks in tool results reach the
  model? Decides D2 (a) vs (b).
- **S2**: reviewer subagent with `response_format=VisualCritique` AND tools
  over OpenRouter — re-verify the old "too many strict tools" trap on
  deepagents 0.6.12 / langchain 1.3.11.
- **S3**: do custom `state_schema` fields reach subagent context? If not,
  constitution fields move to `state.json` in the workspace (same design,
  different plumbing).

## Verified platform facts (2026-07-09)

deepagents 0.6.12, langchain 1.3.11, langgraph 1.2.7, langchain-openai 1.3.3.
`create_deep_agent` supports per-subagent tools/skills/model/middleware/
response_format, custom `state_schema`, `backend`, `CompiledSubAgent`,
`FilesystemMiddleware` (+permissions), `SummarizationMiddleware`.
langchain-openai transmits non-text content blocks in tool-role messages
(provider acceptance untested — S1).
