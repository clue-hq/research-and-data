# Design harness alignment — Step 1: rule ledger

Goal: every instruction the **solo scene ad agent** receives, one row per rule, tagged by topic,
so conflicts show up side by side. No edits to prompts, skills or code in this step.

Working files (untracked until the alignment branch exists):
- `sources/` — exact captured text (system prompt of a first call, tool schemas).
- `ledger/<source>.jsonl` — one JSON row per rule.
- `PROGRESS.md` — this checklist. A source is ticked only when every rule in it is in the ledger.

Capture method: `sources/system_prompt_first_call.txt` and `sources/tool_schemas.json` come from
building the real solo agent offline (scripted model, fake engine; script kept in the session
scratchpad as `doctree/capture.py`) on `feat/scene-delete-key` @ 403442e24. The scene digest and
brand card in that capture are fixture values; their wording around the data is real. Conditional
blocks that the capture did not trigger are ledgered from source code.

## Row schema
`id, src, loc, topic, applies, strength, text, note`
- **topic**: SCOPE · ROUTINE · PRECEDENCE · BRAND · IMAGERY · COPY · EVIDENCE · ACCOUNT · LOGOS ·
  LAYOUT · REVIEW · TOOLS · READING · BUDGET · ASK · OUTPUT · MULTIAGENT · SYNTAX
- **applies**: always · new · edit · follow-up · revamp · references · account · brand-kit · print · ...
- **strength**: must · must-not · should · prefer · may · default · fact
- **text**: verbatim excerpt (trimmed with …)
- **note**: duplicate / conflict / leftover / observation

## Sources checklist

### A. System prompt (code-built, every turn)
- [x] A1 `build_scene_solo_prompt` body (prompts.py:1293) — captured lines 1–168
- [x] A2 `_SCENE_GUIDANCE_READING`, `_SCENE_SURFACE_CONTRACT` (+ logo guidance), `BATCHING_RULE` (prompts.py:25–122, 1109)
- [x] A3 conditional solo lines: ad-assets line, references line (prompts.py ~1425)
- [x] A4 frame payload wording: brand card, published-ad styles, backgrounds, type measurement, type ramp, scene digest, asset index, pinned header (frame.py)
- [x] A5 deepagents base prompt + middleware sections (captured lines ~810–999)
- [x] A6 memory wrapper around AGENTS.md (captured line ~1000+)
- [x] A7 scoped-preferences guidance (scoped_preferences.py)
- [x] A8 guidance-read notices attached to read_file results (guidance_reads.py)

### B. Tool descriptions (21, `sources/tool_schemas.json`)
- [x] B1 write_todos, ls, read_file, write_file, edit_file, glob, grep
- [x] B2 view, render_preview, inspect, search_assets, preflight_design
- [x] B3 record_gap, validate_creative_direction, request_clarification, finalize_run
- [x] B4 compile_dsl_block, asset, fetch_logo, validate_binding_set, apply_structured_edit

### C. Operating note
- [x] C1 AGENT.md (views/scene/AGENT.md)

### D. Skills (32)
- [x] D1 scene-brief-copy
- [x] D2 plan-design
- [x] D3 create-design
- [x] D4 visual-review
- [x] D5 repair-design
- [x] D6 tools
- [x] D7 reference-image-direction
- [x] D8 reference-conditioned-ads
- [x] D9 brand-imagery
- [x] D10 generative-imagery
- [x] D11 effects
- [x] D12 brand-and-tokens
- [x] D13 account-adaptation
- [x] D14 account-identity-composition
- [x] D15 playbooks, product-led: authentic-product, product-in-use, feature-deep-dive, launch-announcement, integration-ecosystem
- [x] D16 playbooks, proof-led: attributed-proof, case-study-narrative, customer-spotlight
- [x] D17 playbooks, argument-led: type-led-positioning, problem-solution, workflow-contrast, comparison-alternatives, objection-handling, editorial-pov, visual-metaphor, educational-guide
- [x] D18 playbooks, action-led: offer-conversion, event-webinar

### E. Shared scene guides
- [x] E1 direction-contract.md
- [x] E2 components.md (pinned)
- [x] E3 references.md
- [x] E4 review.md
- [x] E5 placement.md
- [x] E6 image-grammar.md (spliced into grammar.md)
- [x] E7 catalog.md (generated header, materialize.py)

### F. Engine reference (policy rows + one syntax summary row each)
- [x] F1 lumen-dsl/grammar.md (pinned)
- [x] F2 lumen-dsl/directives.md (pinned)
- [x] F3 lumen-dsl/text.md
- [x] F4 lumen-dsl/colors.md
- [x] F5 lumen-dsl/layout.md
- [x] F6 lumen-dsl/diagnostics.md
- [x] F7 design/artboard-frame-authoring.md (pinned)
- [x] F8 design/font-library.md
- [x] F9 design-systems/brand-kits.md, token-taxonomy.md, brand-validation.md, modes.md
- [x] F10 export/print-geometry.md, preview-quality.md
- [x] F11 loop/layout-cluster-repair.md

### G. Message wrappers (platform → agent, per turn)
- [x] G1 `editor_agent_prompt` / `editor_instruction` both variants + standing instructions (main.py:12522)
- [x] G2 `render_leg_turn_prompt` headers: delegation brief, session history (clue_design/leg_context.py)
- [x] G3 drift note (clue_design/sessions.py), empty-page steering note (main.py:10205)

### H. Per-turn data files (instruction-like text inside data)
- [x] H1 brief.md header + native-copy review block (workspace.py)
- [x] H2 references.md header (workspace.py)
- [x] H3 ad-assets.md header (ad lane renderer)
- [x] H4 seller/index.md header (platform)
- [x] H5 state.json / brand_card.json / source_assets.json — check for instruction text

### Out of scope (noted, not ledgered)
- Head-of-ABM delegation brief content (written by another agent per turn).
- Exit-judge prompt (decides whether a message reaches the design agent; never seen by it).
- Trio prompts (`build_orchestrator_prompt`, author, reviewer) — not used in solo mode.

## Log
- 2026-10-17: workspace created; system prompt + tool schemas captured (68,335 chars; 21 tools, 21,529 chars of descriptions).
- 2026-10-17: all 57 sources ledgered (A1–H5). Completeness audit (every must/never/do-not/cannot/only-when/requires sentence in AGENT.md, skills and scene guides matched against ledger text by 4-word window) found 53 sentences only paraphrased → added as Z1. Total 636 rows.
- 2026-10-17: 11 conflict groups curated in `issues.py` (refs resolve by source + substring; build fails on a missing/ambiguous ref) → `issues.json`. Page rendered by `render_ledger.py` → `rule-ledger.html`, published at https://claude.ai/artifact/2EagVdjnAmnGkGgzNhU5Ce. Step 1 DONE; Step 2 (founder rulings per topic) next. No prompt/skill/code edits made.
