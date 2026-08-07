# Q1 — How Brilliant organizes vast functionality behind few tools, and how we cut our 25-tool deepagent

**Question.** How did Brilliant organize such a vast span of functionality behind so few tools — reverse-engineering the exact coverage and functionality of each tool — and how do we apply this to cut our 25-tool deepagent down?

**Headline answer.** Brilliant exposes a full Figma-class design feature set through a **maximum of 14 distinct agent tools**, and any single chat session ever sees only **5–12** of them. It does this not by having few features but by moving feature variation **out of the tool list and into tool arguments and loadable data**. Three force-multipliers carry the breadth: (1) a whitespace-significant **Blueprint DSL** behind one creation tool, (2) **knowledge-on-demand** (`get_knowledge`, ~80 doc keys) instead of one tool per feature, and (3) a **command multiplexer** (`execute_commands`) fronting 100+ commands behind one tool. Our deepagent ships **26** agent-facing tools and has already hit Anthropic's 20-strict-tool cap. Applying Brilliant's patterns — without touching our Scene/Operation/DSL contract — cuts us to **17** tools (a 35% reduction), and to **15** with two further safe merges.

---

## 1. The exact Brilliant tool surface

Every tool below is confirmed as an exact literal in the AOT binary (`strings -x` matched all 14) and documented in the shipped `.claude-prod` docs. "Verbatim" descriptions are exact binary strings; descriptions found only in the `.md` docs are marked `[docs]`.

| # | Tool | Description (verbatim from binary unless `[docs]`) | Coverage — the full span of user-facing capability this one tool delivers | Evidence |
|---|------|-----------------------------------------------------|---------------------------------------------------------------------------|----------|
| 1 | **`init`** | "Bootstrap a design session. Returns a unique session ID, session context (canvas ID, repo path), and documentation. Call this first. Pass the returned session ID as the `sessionId` argument on every subsequent `create_modify_elements` / `create_html` call. … Only load knowledge via `get_knowledge` when using the Blueprint DSL for advanced features." | Session bootstrap; mints a `sessionId` (`mcp:<id>`) that namespaces refs + design-system state so concurrent agents don't collide; surfaces repo/canvas context; delivers the default design-system token catalog inline; routes the agent to the fast path. **External-MCP-only** — hosted/sub-agents skip it (context pre-injected). | binary `MCPToolsInit`; `mcp.md` §"Session Identity"; `tools.md` L203 |
| 2 | **`create_html`** | "Convert HTML + inline CSS into auto layout frames, text, and shapes. No `get_knowledge` required." `[docs, tools.md L207]` | **Zero-knowledge fast path for ~80% of designs.** Auto-layout frames (flex), nested hierarchy via indentation, text, shapes, fills, linear/radial gradients, icons via `<i data-icon>`, `id="name"` → reusable `#name` session ref. Composes with Blueprint for later iteration. | binary "HTML string with inline CSS…"; `mcp.md` L11 |
| 3 | **`create_modify_elements`** | "Create or modify elements via the Blueprint DSL. Requires `get_knowledge(['blueprint/core', …])` first." `[docs, tools.md L208]` | **The single most-multiplexing creation tool — the entire vector model.** Create/modify every element type (rect, circle, text, line, frame, group, auto-layout, svg/icon); paint stacks, strokes, per-corner radius, gradients (linear/radial/angular), shaders (metaballs/metal/irid/steel), effects (glass/neon/clay/dark-mode), styled text ranges, arcs/donut/pie/progress rings, lines/arrows/flowchart/callouts, components (`comp`/`inst`/`override`/`repeat`), AI-image placement, and modify/reparent/clone/replace/delete via flat `#ref` lines. Authors entire design systems (`ds_file(...)`); enforces token discipline; undo anchors. | binary `_processCreateModifyRequest`; `mcp.md` L19–27; `objects-syntax.md` |
| 4 | **`get_knowledge`** | "Load design knowledge by key. MUST be called before creating elements. Pass keys from the available keys list … (e.g. 'blueprint/core', 'design/colors', 'effects/glass')." | **Replaces dozens of would-be feature tools with on-demand docs.** ~80 keys across `blueprint/*`, `design/*`, `design-systems/*`, `design/blocks/*`, `effects/*`, `charts/*`, `images/*`, `svg/*`, `webgl/*`, `recreation/{from-image,from-web}`, `reference/*`. Capability ships as docs the model loads, not as API. | binary `_handleGetKnowledge`; `all-agents.md` L40–53 |
| 5 | **`get_selection`** | "Get the IDs and blueprint of currently selected elements on a specific canvas. Returns selected element IDs and their full blueprint representation including descendants." | Reads what the human has selected on canvas → IDs + full blueprint subtree. The human→agent handoff channel; lets "design *this*" work. | binary `_handleGetSelection`; `tools.md` L206 |
| 6 | **`lookup`** | "Find or read elements across the design repo. Unifies discovery (by name/text/type/color/component) and inspection (by canvas or element ID). … At least one of scope/query/textContent/type/fillColor/componentName is required. Default `format` is 'summary' (cheap metadata); use 'blueprint' to get full element trees with optional `depth` bounding." | **Two tools folded into one** (this is the merge that retired the old `find_elements`): (a) discovery/search across the whole repo by name/text/type/color/component; (b) inspection of an element/canvas subtree as full blueprint with depth bounding. Covers "find all buttons", "what's in this card", cross-canvas search, component auditing. | binary `_handleLookup` (both variants); `mcp.md` L57 |
| 7 | **`execute_commands`** | "Execute one or more commands by ID. Accepts an array of commands that share a single canvasId. Commands run sequentially, stopping on first error. Use command IDs from the skill docs." | **The command multiplexer — one tool fronts 100+ `AIInvocableCommand`s.** Align/distribute/flip, corner-radius/opacity/blend-mode setters, tool changes, frame & component ops, auto-layout (direction/padding/gap/wrap), `batch_set_fills`/`batch_set_strokes`/`batch_reparent`, boolean ops (union/subtract/intersect/exclude/flatten), masks, outline/flatten text, scale-to-width/height, token bind/unbind, reorder, export-setting setters, canvas/file management, view toggles, undo/redo/clipboard. Runs through the same code path as a keyboard press, full undo. | binary `MCPToolsExecute`, `_handleExecuteCommands`, `batch_set_fills`, `auto_layout`; `ai.md` L219–221 |
| 8 | **`export`** | "Export elements in the specified format and return the data. Raster formats (png, jpeg, webp) return an inline image. SVG returns raw SVG markup as text. HTML returns an HTML/CSS snippet as text. PDF returns base64-encoded data as text. When outputPath is provided, writes to that file path …" | One tool = **visual self-review screenshot** + **multi-format asset export** (PNG/JPEG/WebP, SVG markup, PDF base64, HTML/CSS snippet, React/JSX copy paths) + write-to-disk. Fuels the screenshot-driven critique loop *and* the deliverable export. | binary `_handleExport` + param strings; `ai.md` L210 |
| 9 | **`generate_image`** | "Generate a raster image and apply it as a fill on `targetElementId`." `[docs]`; binary: "Generate images with Nano Banana 2 (Gemini Image)", "Either targetElementId or targets is required." | Photos, realistic scenes, textures, hero/banner backgrounds, product shots, patterns via Google "Nano Banana" (`gemini-3.1-flash-image-preview`), saved to `Assets/`, applied as fill. Edit-this-image via up-to-14 reference images. **Batch is the `targets[]` parameter** — no separate `generate_images` tool. | binary verbatim params + `_handleGenerateImage`; `ai.md` L211, L229–287 |
| 10 | **`generate_svg`** | "Generate an editable vector graphic (SVG) and place it on the canvas as native editable shapes." `[docs]`; binary: "Batch mode: distinct prompts generated in parallel." | Icons, logos, illustrations, diagrams via Quiver "Arrow" (`arrow-1.1`), imported as native editable vector paths. Parallel variations (`n:1–4`) or batch distinct prompts; up-to-4 reference images for style steering. | binary verbatim + `_handleGenerateSvg`; `ai.md` L212, L237–249 |
| 11 | **`vectorize_image`** | "Convert a raster image element on the canvas into editable vector paths. The new vector elements are placed on the canvas; the original raster element is left untouched … Requires Quiver API key." | Raster→vector: turn any PNG/JPEG/screenshot/AI-image on canvas into editable Quiver-vectorized paths, original intact. | binary verbatim + `_handleVectorizeImage`; `ai.md` L213 |
| 12 | **`plan_agents`** | "Announce the agents you are about to spawn. Call this BEFORE calling spawn_agent so the user sees your plan while agents are launching. After this tool returns, call spawn_agent for each agent in the next turn." | Announce-only UX/commitment step — renders the fan-out plan before launch. Carries no execution semantics. | binary verbatim; `ai.md` L214, L223–225 |
| 13 | **`spawn_agent`** | "Spawn a sub-agent for parallel design work. Blocks until the agent completes and returns its summary. Launch multiple spawn_agent calls in a single turn for parallel execution." | Horizontal scale-out: parallel ad-hoc sub-agents (no role registry — differentiated only by `prompt` + `description`), each in its own `ChatOrchestrator` with the parent's key, 5-min timeout, returns a compact summary as a collapsible card. | binary verbatim; `ai.md` L214, L223–225; `subagent.md` |
| 14 | **`load_mcp_server`** | "Load an MCP server's tools into the conversation. Call this when you need to use tools from an MCP server listed in the system prompt. The server's tools and instructions will become available on the next turn." | **Lazy extensibility** — defers all third-party tools so the base surface stays tiny and constant regardless of how many MCP servers are registered. | binary verbatim + `_normalizeMcpToolName`; `ai.md` L215 |

### Exact total count and per-session surface

- **Total distinct agent tools in existence: 14** (all 14 literals confirmed in the binary).
- **Per-session surface is smaller — this is the number to beat:**
  - **External MCP client (Claude Code CLI): 11** — `init, create_html, create_modify_elements, lookup, get_selection, get_knowledge, execute_commands, export, generate_image, generate_svg, vectorize_image` (the `tools.md` registration lists exactly these 11; no `plan_agents`/`spawn_agent`/`load_mcp_server`).
  - **In-app HTTP providers, base: 5 always-on** — `get_knowledge, get_selection, export, execute_commands, lookup` (`NativeTools.getToolDefinitions()`, `tools.md` L199). Then **+3** with generation creds, **+2** with sub-agents, **+1** with MCP loading; tops out at 11. HTTP sessions create elements by **streaming `<objects>` blocks**, so `init`/`create_html`/`create_modify_elements` are not even tools on that transport.
  - **Sub-agent:** leaner still — `create_html` + `create_modify_elements` + read tools; no `init`, no web search.

**Two corrections to the prior §12 comparison baseline:** (1) `find_elements` is stale — `strings -x find_elements` returns empty; it was unified into **`lookup`** ("Find or read elements … Unifies discovery … and inspection"). (2) There is no `generate_images` tool — batch is the `targets[]` parameter on `generate_image`.

**Bottom line:** Brilliant's *minimum viable* design agent is **5 tools**; its maximum per session is **11**; nothing ever sees more than 11 at once, and they never broke 14 total despite covering Figma's feature set. Meanwhile the binary contains **424 `*Command` classes** and **80+ knowledge files** — the compression ratio between latent capability and visible tools is the whole point.

---

## 2. The organizing principles

Five levers (the first three are the load-bearing ones; the last two are about role-splitting and tiering). Each keeps the prompt-visible tool count tiny and stable — cheap to reason over, low selection error — while the actual capability count grows without bound.

### Principle 1 — Command multiplexer / dispatcher tool (1 tool ≈ 100+ would-be tools)
`execute_commands` takes a string `commandId` + free-form `params` and routes through Brilliant's existing internal command bus. Because every UI action is already a named, undoable `AIInvocableCommand`, the AI surface is essentially *free* — it just reuses the registry. The docs say "over 100 commands in total"; the binary holds 424 command classes. One tool absorbs the entire long tail: selection, alignment, distribution, boolean ops, masks, z-order, transforms, grouping/framing/reparenting, auto-layout setters, property setters (corner radius, stroke, fill, opacity, blend mode), the whole `Add*Fill/Effect` family, typography setters, component ops, layout grids, canvas/file management, background/whiteboard, view toggles, import, tool/mode, undo/redo/clipboard, and even provider-key management. New commands extend the system without ever adding a tool the model must learn.
**Evidence:** binary `MCPToolsExecute`, `_handleExecuteCommands`, 424 `Command$` classes; `blueprint/commands.md` ("Creation, deletion, property changes, z-order, flip, group/ungroup, and reparenting are all DSL operations, never commands" — so the dispatcher is deliberately scoped to the stateful/selection/canvas/view verbs the DSL can't express).

### Principle 2 — DSL-as-the-real-surface (the biggest creation lever)
The entire create/modify universe — every element type, fills, strokes, gradients, shaders, effects, components, arcs, lines, styled text ranges, design-system authoring, *and* modify/reparent/clone/replace/delete — is **one string argument** to `create_modify_elements` (or a streamed `<objects>` block on HTTP). There is no `create_rectangle`, `set_fill`, `add_gradient`, `make_component`. The whitespace-significant grammar carries the breadth; the tool count stays at 1. On the in-app HTTP transport the creation surface drops from 3 tools to **0** — elements stream as `<objects canvasId="...">` into the same converter. Tool count is treated as transport-specific and trimmed to each client's minimum.
**Evidence:** binary `_processCreateModifyRequest`, `objects-syntax.md`; HTTP streaming path in `http.md`.

### Principle 3 — Knowledge-on-demand instead of capability-tools (+ skills)
`get_knowledge` ships ~80 doc keys. Charts, effects, shaders, recreation-from-image/URL, gradients, webgl export, design-system authoring, a whole UI-block library (`design/blocks/*`) — none are tools. They are docs the model loads when relevant, and capability scales with docs (which don't consume the tool-list context budget), not with tool schemas. The discipline is explicit: "NEVER answer about Brilliant's capabilities from memory — load the `reference/*` key first." Skills extend the same idea via the filesystem: `init` symlinks `CLAUDE.md + knowledge/ + skills/` into the workspace so behavior is *mounted as files*, read on demand, never registered as tool definitions. `load_mcp_server` (lazy extension) generalizes this to third-party tools — they appear "on the next turn" only when asked, so the base surface never grows.
**Evidence:** binary `_handleGetKnowledge`, "CLAUDE.md + knowledge/ + skills/ symlinked"; `all-agents.md` L40–53; `load_mcp_server` verbatim.

### Principle 4 — Fast-path vs advanced-path (one default, one power tool) + merged read tool
Two creation tools form a deliberate complexity gradient: `create_html` is the **zero-knowledge default** ("use it directly for most tasks, no knowledge loading"); `create_modify_elements` is the **token-disciplined power path** ("requires `get_knowledge` first"). The model pays the doc-loading cost only when it reaches for advanced features; the common case is free. They explicitly compose ("build with `create_html`, iterate with Blueprint"). The same instinct merges reads: `lookup` ate `find_elements` by carrying search *and* read-subtree behind a `format` switch (`summary` vs `blueprint`) and a `depth` knob — don't ship a "search" and a "get"; ship one with a mode parameter. The only read tool kept separate is `get_selection` (the human→agent handoff), a genuinely distinct concept.
**Evidence:** `init` fast-path string; `create_html` "No `get_knowledge` required"; `lookup` verbatim unifying string.

### Principle 5 — Agent fan-out instead of a mega-toolset (orchestration absorbs the cost)
Brilliant separates **orchestration** from **tool surface** so no single agent carries everything. A two-tool protocol — `plan_agents` (announce) then `spawn_agent` (execute) — covers arbitrary fan-out without N role-specific spawn tools. Sub-agents are **flat, generic, ad-hoc workers** (no role registry; differentiated only by `prompt` + `description`), each in its own `ChatOrchestrator` with the parent's key, a 5-minute hard timeout, and cancellation inherited from the parent. Crucially, children return a **compact summary + collapsible card**, not their raw transcript — so parallel work expands throughput without flooding the parent's context. The load-bearing safety mechanism is `sessionId`: it namespaces `#refs` *and* design-system state per session, so flat parallel fan-out is safe with **no locking/merge tools** — isolation is a property of the session model, not something the tool list must express. Asymmetric surfaces reinforce this: main sessions get web search + planning + MCP loading; workers get only canvas-mutation tools and skip `init`.
**Evidence:** binary `_spawnHttpSubAgent`, `SubAgentInfo`, `_extractSubAgentSummary`, "Sub-agent timed out after 5 minutes", `# Session Identity` block; `ai.md` L192/L214/L319; `subagent.md`.

> **The transferable statement.** Collapse a large, open-ended capability surface into a tiny set of dispatcher tools by moving variation out of the tool *list* and into tool *arguments and loadable data*. One command dispatcher (reusing your internal command bus); one find/read tool with selectors + scope + format/depth params; a small number of creation tools layered by complexity plus one knowledge-loader that mounts behavior as on-demand docs/skills; and orchestration pushed down into a session/sub-agent layer so each agent stays small and bounded.

---

## 3. Our 26 tools vs their ~14 — side-by-side mapping

**Our authoritative surface: 26 registered tools** (`factory.py` L51–78), not the assumed ~25 — every entry is a method on `LumenDesignTools` passed to `create_deep_agent(tools=[...])`. The effective surface is ~33 once deepagents' built-in filesystem/todo/skills tools are counted, and the `lumen-visual-reviewer`'s `response_format` already tripped Anthropic's **20-strict-tool cap** (`BadRequestError: Too many strict tools`), forcing both subagents to declare `"tools": []` (`prompts.py` L337–354). The "too many tools" pain is real and *actively constraining the architecture today.*

| # | Our tool | Brilliant pattern it maps to | Brilliant equivalent | Redundancy flag |
|---|----------|------------------------------|----------------------|-----------------|
| 1 | `load_knowledge` | Knowledge-on-demand (P3) | `get_knowledge` | Keep — direct analog. |
| 2 | `compile_dsl_block` | DSL-as-surface (P2) | `create_modify_elements` | Keep — mutation seam #1. |
| 3 | `apply_operations` | DSL-as-surface (P2) | `create_modify_elements` (op list) | Keep — mutation seam #2. |
| 4 | `apply_structured_edit` | DSL-as-surface (P2) | Blueprint modify lines | Keep — mutation seam #3 with scope gate. |
| 5 | `generate_qr` | Generation-by-modality (P3-adjacent) | (no exact analog) | **Fold** → `asset` dispatcher. |
| 6 | `generate_image` | One gen tool per modality | `generate_image` | **Fold** → `asset` dispatcher. |
| 7 | `place_asset_in_node` | Param-not-tool | `img(path)` in DSL | **Fold** → `asset` (shared `_place_asset`). |
| 8 | `place_asset_in_slot` | Param-not-tool | `img(path)` in DSL | **Fold** → `asset` — literally same method as #7, differing key only. |
| 9 | `validate_binding_set` | (Phase G; no analog) | — | Keep (optional pair w/ #10). |
| 10 | `derive_instance_preview` | export/perception (P4) | `export` | Keep (optional pair w/ #9). |
| 11 | `preflight_design` | Command (P1) / DS state | DS-discipline in session | Keep — distinct core call, loop-driven. |
| 12 | `export_preview` | export doubles as deliverable (P4) | `export` | **Fold candidate** → `export(mode=single)`. |
| 13 | `export_preview_bundle` | export = perception + deliverable (P4) | `export` (screenshot+asset) | **Fold candidate** → `export(mode=bundle)` (load-bearing for critic). |
| 14 | `get_latest_preview_for_critique` | export-as-perception (P4) | `export` (self-review screenshot) | Keep — distinct read-back-pixels seam. |
| 15 | `submit_visual_critique` | orchestration | (sub-agent summary fan-in) | Keep — loop-critical, fail-closed. |
| 16 | `recommend_edit_surface` | fast-path vs advanced router (P4) | the HTML/DSL split logic | Keep — the router the loop uses. |
| 17 | `create_repair_request` | orchestration | (no analog) | Keep — traceability guarantee. |
| 18 | `record_gap` | orchestration | (no analog) | Keep (or fold into finalize). |
| 19 | `summarize_scene` | merged read tool (P4) | `lookup` (summary format) | **Fold** → `inspect`. |
| 20 | `summarize_page` | merged read tool (P4) | `lookup` (blueprint/depth) | **Fold** → `inspect`. |
| 21 | `summarize_slots` | merged read tool (P4) | `lookup` | **Fold** → `inspect`. |
| 22 | `summarize_node_tree` | merged read tool (P4) | `lookup` (blueprint) | **Fold** → `inspect` — near-duplicate of #20. |
| 23 | `query_geometry` | merged read tool (P4) | `lookup` (inspect) | **Fold** → `inspect`. |
| 24 | `query_slot_bindings` | merged read tool (P4) | `lookup` (componentName) | **Fold** → `inspect`. |
| 25 | `persist_trace_event` | (none — internal bookkeeping) | — | **Drop** from agent surface (auto-traced by `record()`). |
| 26 | `finalize_run` | orchestration | (session terminal) | Keep — terminal seam. |

**The structural redundancy:** Brilliant collapses our entire `summarize_*`/`query_*` family into one `lookup` (their P4 merged-read tool — exactly the `find_elements`→`lookup` move), and our asset family into the `img()` DSL idiom + parameterized batch (their P2/"batch via param"). We pay tool-count for things Brilliant pays argument-count for. We have **no** command-multiplexer (their biggest lever, P1) because our mutations are correctly funneled through the core via three DSL/op seams — so the multiplexer pattern applies to us only on the *read* and *asset* side, not the mutation side.

---

## 4. Concrete consolidation plan for us

**The key leverage:** the deterministic `LumenQualityLoop` already drives ~10 of these tools *mechanically* (it calls `compile_dsl_block`, `preflight_design`, `export_preview_bundle`, `get_latest_preview_for_critique`, `submit_visual_critique`, `recommend_edit_surface`, `create_repair_request`, `summarize_scene`, `finalize_run`, `record_gap` as Python methods, not via the model's tool surface). So we can shrink the **agent-facing tool count** (the thing that hit the 20-strict cap) while keeping every method callable internally. The model doesn't need them as separate tools.

**The hard contract to preserve (do not break):** every scene mutation flows through the core and replaces the scene wholesale via `_replace_scene_from_core_response` (`tools.py` 1993–1998). The three legitimate mutation entry points — `compile_dsl_block` (DSL→ops), `apply_operations` (raw op list), `apply_structured_edit` (typed edit builder with `scope` enforcement) — must stay distinct, and the "scene only updates from core response" invariant must hold. Asset tools already mutate via `apply_operations([{kind: upsert_asset...}])`/placement ops, so consolidating their *dispatch* changes no core path.

### Prioritized folds

**Group A — `inspect` multiplexer (saves 5). Highest value, lowest risk.**
Fold tools 19–24 (`summarize_scene`, `summarize_page`, `summarize_slots`, `summarize_node_tree`, `query_geometry`, `query_slot_bindings`) into one `inspect(view, target?)` where `view ∈ {scene, page, slots, node_tree, geometry, slot_bindings}` and `target` is the optional `page_id`/`node_id`/`slot_key`. All six are pure, read-only views over the same in-memory `self.scene`; none mutate; `summarize_node_tree` is already a near-duplicate of `summarize_page`. This is Brilliant's `lookup` pattern exactly. Keep `summarize_scene` as a thin internal method (loop.py calls it directly at L339/L738); the multiplexer just dispatches. **6 → 1, net −5.**

**Group B — `asset` dispatcher (saves 3). High value, low risk.**
Fold tools 5–8 (`generate_qr`, `generate_image`, `place_asset_in_node`, `place_asset_in_slot`) into one `asset(action, ...)` where `action ∈ {generate_image, generate_qr, place}` and `place` accepts either `node_id` or `slot_id`. The two `place_*` tools are literally the same private method (`_place_asset`) with one differing key — risk-free to merge. All four already funnel through `core.generate_*`/`core.ingest_asset` then `apply_operations(upsert_asset)`/placement ops, so the core contract is untouched. Keep `generate_image`'s geometry-derived aspect logic (`_image_constraints`) and `generate_qr`'s print-scannability params as separate branches *inside* the dispatcher — do not force a common signature. This mirrors Brilliant's "batch via param, one tool per modality." **4 → 1, net −3.**

**Group C — drop `persist_trace_event` (saves 1).**
Remove tool 25 from the agent surface entirely; the `record()` method already auto-traces every tool call, and the loop never needs the model to hand-write trace events. Keep `record()` internal. (Optionally also fold `record_gap` into `finalize_run` as a `gaps` param, but they serve different lifecycles — gaps mid-run, finalize terminal — so prefer keeping `record_gap` standalone.) **1 → 0, net −1.**

**Group D — keep standalone (15 tools).** These must not fold:
- The three mutation seams — `compile_dsl_block`, `apply_operations`, `apply_structured_edit` (the last is the only path that can reject out-of-scope mutations before they happen; folding it into `apply_operations` would lose the scope gate).
- `preflight_design` (distinct core call + brand-kit resolution, sets `effective_brand_context`, loop-driven).
- `export_preview`, `export_preview_bundle` (two genuinely different return contracts; the bundle is the load-bearing critic input).
- `get_latest_preview_for_critique` (reads back validated artifacts as SVG/PNG — distinct from export).
- `submit_visual_critique` (fail-closed typed `VisualCritique` persistence, loop-critical).
- `recommend_edit_surface` (the dsl-vs-structured-vs-asset router — Brilliant's P4 fast/advanced split, in logic form).
- `create_repair_request` (non-paraphrased feedback — traceability guarantee).
- `validate_binding_set`, `derive_instance_preview` (Phase G personalization seams, different lifecycle).
- `load_knowledge` (our `get_knowledge` analog, loop calls it first).
- `record_gap`, `finalize_run` (mid-run + terminal record-keeping).

### Projected count

| Action | Before | After |
|--------|--------|-------|
| `inspect` multiplexer (Group A) | 6 | 1 |
| `asset` dispatcher (Group B) | 4 | 1 |
| Drop `persist_trace_event` (Group C) | 1 | 0 |
| Everything else (Group D) | 15 | 15 |
| **TOTAL** | **26** | **17** |

**26 → 17 agent-facing tools (−9, a 35% cut)** with zero changes to the Scene/Operation/DSL contract: every fold either merges pure read-only views (no core call) or merges asset operations that already share the `apply_operations(upsert_asset)`/placement core path. The three mutation seams and the scope-enforcement guarantee stay intact, and the loop-critical methods remain callable internally.

**To go further (−2 more → 15):** merge `export_preview` + `export_preview_bundle` into `export(mode=single|bundle, ...)`, and pair `validate_binding_set` + `derive_instance_preview` into `binding(action=validate|derive_preview)`. Both are safe (same core seams) but lower value than A/B because their return shapes differ more.

### Why this matters beyond aesthetics
The 20-strict-tool cap is an *active* failure mode (`prompts.py` L337–354 documents the `Too many strict tools` crash that forced the empty-`tools` workaround on subagents). Cutting the coordinator from 26 → 17 (effective ~33 → ~24 with built-ins) directly relieves that pressure. Groups A and C cost almost nothing to implement since the methods stay as-is behind a thin dispatcher. And it moves us toward Brilliant's proven posture: a small, stable, low-selection-error tool list, with capability breadth carried by DSL arguments (our three mutation seams), loadable knowledge (`load_knowledge`), and the deterministic loop — not by tool count.

> **What we still lack vs Brilliant (forward-looking, not in this cut):** we have no command-multiplexer for the non-mutating one-off operations Brilliant routes through `execute_commands`, and no fast-path/advanced-path *creation* split (we have only the advanced DSL path, no zero-knowledge `create_html` equivalent). Both are larger architectural moves; this plan deliberately stays inside the safe, contract-preserving folds.

---

### Source-of-truth files (absolute)
**Brilliant:**
- Docs: `/Users/aryankeshri/Documents/brilliant-design/package/Contents/Resources/.claude-prod/{mcp.md, all-agents.md, subagent.md, http.md, hosted.md, objects-syntax.md}` and `.../knowledge/reference/{ai.md, tools.md, editing.md, components.md}` and `.../knowledge/blueprint/commands.md`
- Binary: `/Users/aryankeshri/Documents/brilliant-design/package/Contents/Frameworks/App.framework/Versions/A/App` (`MCPToolsInit/Create/Execute/Read/Generate`, 424 `Command$` classes, `_handleLookup/ExecuteCommands/Export/GenerateImage/GenerateSvg/GetKnowledge/GetSelection/VectorizeImage`, `_processCreateModifyRequest`, `_spawnHttpSubAgent`, `SubAgentInfo`, `_extractSubAgentSummary`, `_handleCompaction`, `# Session Identity` block)
- Comparison baseline (note: its §12 `find_elements` row is stale — corrected to `lookup` above): `/Users/aryankeshri/conductor/workspaces/clue-design/havana/reference_docs/Brilliant-Reverse-Engineering-Report.md` §12

**Ours:**
- `/Users/aryankeshri/conductor/workspaces/clue-design/havana/apps/agent_runtime/lumen_deepagent/factory.py` (registration list, L51–78)
- `/Users/aryankeshri/conductor/workspaces/clue-design/havana/apps/agent_runtime/lumen_deepagent/tools.py` (26 implementations + `_replace_scene_from_core_response` contract at 1993–1998)
- `/Users/aryankeshri/conductor/workspaces/clue-design/havana/apps/agent_runtime/lumen_deepagent/prompts.py` (workflow + the ~33-tool / 20-strict-cap problem at L337–354)
- `/Users/aryankeshri/conductor/workspaces/clue-design/havana/apps/agent_runtime/lumen_deepagent/loop.py` (deterministic quality-loop usage of the loop-critical subset)
- `/Users/aryankeshri/conductor/workspaces/clue-design/havana/apps/agent_runtime/lumen_deepagent/schemas.py` (param shapes for JSON-string tools)

---

## Addendum — verified critic corrections (fold these in)

A completeness critic re-checked this report against the authoritative `blueprint/commands.md` and the binary. The headline conclusions (14 tools total, 5–11 per session, the 26→17 consolidation) all stand. These precision fixes apply:

1. **`execute_commands` scope was OVERSTATED.** The authoritative `knowledge/blueprint/commands.md` (L7–10) says `execute_commands` is **ONLY for operations the Blueprint DSL cannot express**, and that *"creation, deletion, property changes, z-order, flip, group/ungroup, and reparenting are all DSL operations, NEVER commands."* The synthesis conflated *"a `*Command` class exists in the binary"* with *"exposed to the agent via `execute_commands`."* The **doc-accurate** command surface is: selection (`select_elements`/`deselect_all`), align/distribute/center, boolean ops (`union`/`subtract`/`intersect`/`exclude`), masks (`use_mask`), component ops (`detach_component`, `reset_component_instance_overrides`, `push_overrides_to_master`, `go_to_master_component`), `import_figma`, canvas/folder management (`create_canvas`/`get_canvases`/`rename`/`delete`/`duplicate`/`create_folder`/`create_structure`), background/board toggles, view toggles, keybindings (`list_keybindings`/`set_keybinding`), provider-key setters, and undo/redo. Remove the "batch_set_fills / set_corner_radius / batch_reparent / Add*Fill family / property setters" claims for this tool — those are binary-internal command classes routed through the **DSL**, not `execute_commands`. *(This actually sharpens Principle 1: Brilliant scopes its multiplexer to strictly the non-DSL verbs, never duplicating the DSL surface.)*
2. **Binary `*Command` count is 848, not 424.** (`strings | grep -cE 'Command$'` → 848.) The operative AI-surface figure — the docs' own *"100+ commands"* — is correct; only the binary corroboration number was off.
3. **Group B implementation note.** The two `place_*` tools dispatch to **two distinct core op kinds** (`place_asset_in_node` for `node_id`, `place_asset_in_slot` for `slot_id`, `tools.py` L786–804 / `_place_asset` L826). The *agent-facing* tool merges to one `asset(action='place', …)`, but the dispatcher **must preserve both core `kind` values as branches** — collapsing to a single core kind would break the slot-binding path.
4. **`summarize_node_tree` is a strict subset of `summarize_page`** (node_tree only, no `_page_summary`), not a "near-duplicate." Both still correctly fold into `inspect`.
5. **`regenerate_design_system` is a command, not a 15th tool** — reached via `execute_commands`, consistent with the 14-tool total.

---

## Implementation status — Groups A/B/C SHIPPED (2026-06-26, branch `add-image-model-to-design-tool`)

The safe consolidation in §4 is implemented. **26 → 17 agent-facing tools**, zero changes to the Scene/Operation/DSL contract.

- **Group A — `inspect(view, target?)`** (`tools.py`): one tool fronts `scene`/`page`/`node_tree`/`slots`/`geometry`/`slot_bindings`, dispatching to the unchanged `summarize_*`/`query_*` methods (kept as internal Python API for `loop.py` + tests). Fails closed on missing-target / unknown-view.
- **Group B — `asset(action, …)`** (`tools.py`): one tool fronts `generate_image`/`generate_qr`/`place`. The `place` action **preserves both core op kinds** (`node_id`→`place_asset_in_node`, `slot_id`→`place_asset_in_slot`) per the critic flag. Fails closed on bad/unknown action.
- **Group C**: `persist_trace_event` removed (record() auto-traces).
- **`factory.py`**: registration list is now the 17 tools. **`prompts.py`**: coordinator/author prompts + strict-tool-cap comment updated. **Docs**: `skills/tools/SKILL.md` (canonical surface) + imagery/dsl docs rewritten to `asset(...)`/`inspect(...)`; op-kind references clarified.
- **Tests**: factory-surface assertion now pins the exact 17 + guards the 11 folded names are absent; 2 new dispatcher tests (`test_asset_dispatcher_routes_actions_and_preserves_place_kinds`, `test_inspect_dispatcher_routes_all_views`). **Full agent suite: 94 passed, 2 skipped.**

Not done (larger, out of this safe cut): the optional −2 → 15 (`export(mode=…)`, `binding(action=…)`), and the forward-looking command-multiplexer / `create_html` fast-path.
