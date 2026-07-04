# Moda-Inspired Editor Plan for Clue Design (Lumen)

*Source evidence: 26 screenshots of moda.app (July 2, 2026) in `/Users/aryankeshri/Documents/screenshots_and_screenrecords/` — brand-kit flow, "Design Plan" pre-brief, live agent generation, all editor menus/toolbars, Details inspector, Assets panel, AI image-edit modal, page inspector — plus the re-exported 160s screen recording (80 frames extracted at 0.5fps to /tmp/moda_frames; covers a human editing session + the full AI image-edit loop).*

*Codebase baseline re-verified 2026-07-03 on `add-image-model-to-design-tool`: the editing architecture is unchanged since STUDY.md (no `position_mode`/`absolute_box`; agent still seeds from `new_scene` at `tools.py:142`; no `initial_scene` path; `isNodeDirectGeometryEditable` gate unchanged at `sceneQueries.ts:183`; still no scene→DSL emitter). The image slice delivered two former Phase-2 items: real image pixels in CanvasKit (commit `3f43ff2`) and an image inspector with fit/focal/alt + generate/regenerate/replace (`c045699`, `ImageInspectorSection.tsx`).*

---

## 1. What Moda actually is (from the evidence)

### 1.1 Canvas/data model — freeform absolute, no live layout solver
The Details inspector shows **Position X/Y and Size W/H as plain editable numbers** (e.g. X 72, Y 252, W 936, H 290), rotation slider, lock-aspect toggle. Fractional font sizes (89.74) betray scale-by-drag of text. There is **no auto-layout panel anywhere** — no hug/fill controls, no gap/padding-as-constraint on elements. Layout *discipline* comes from soft guides instead: page **margins** (108px defaults, per-page override), a **"2-Column"** page-level layout helper, **Show margins/rulers/grid** toggles, and align/distribute + smart guides at edit time.

**Implication:** a human drag never fights a solver — what you drag is what is stored. This is precisely the property our auto-layout children lack (positions solved-and-discarded, `layout.rs:322-330`), and why our first attempt failed.

**Important nuance (user observation, confirmed by generation screenshots):** while the agent composes, elements land at *rough* positions (7:30:53 frame: headline text mid-placement, oversized box, awkward gap) and the final design is *perfectly aligned*. So Moda clearly runs layout/alignment intelligence at **authoring time** — either an explicit align/tidy pass driven by its screenshot self-QA ("Capture screenshots & polish" checklist step; "Design reviewed"; "let me verify spacing is fine"), or a one-shot layout computation over grouped elements. Either way its **output is baked to absolute coordinates before handoff to the human**. "Solver-less" therefore means: no solver *owns* positions at edit time / in the persisted model. Layout intelligence exists, but it runs as an authoring-time process, not an edit-time constraint system. This two-layer split (authoring-time layout intelligence → baked absolute for humans) is exactly what our `DetachToFreehand`/bake mechanism generalizes — with the advantage that we can also keep the solve *live* for managed mode, which Moda cannot.

### 1.2 How the agent works on the document
- Agent authors **into the same live document** the human later edits — elements appear one by one with a pink "remote cursor" selection outline on the element being written.
- **Turn-taking lock:** while generating, a banner reads "Moda is designing — please wait to edit"; the chat input becomes **"Type to queue a message…"** (messages queue for after the turn). Human editing is disabled during the agent turn; there is no concurrent-merge problem *by construction*.
- **Transparent plan:** chat shows a checklist plan ("Plan 3 distinct ad concepts", "Create 3 pages at 1080×1080", "Build Concept 1…", "Capture screenshots & polish") with live check-offs and step counters ("Created 34 elements", "Design reviewed").
- **Self-QA on pixels:** the agent narrates a screenshot-based review of its own output ("the 'With Magic Doc' label collides slightly close to the divider line. Let me verify spacing is fine.") — the same render-and-look loop we built in P1.2.
- **Variants as pages:** 3 concepts = 3 named pages ("1 — 1/10th Cost (Living Type)", "2 — Product Hero (Mint)", "3 — Exaggeration (Paper Stack)") side by side on one canvas.
- **"Notify me when ready"** toast (2–3 min expectation), and **File → Agent instructions** = per-document standing instructions for the agent.

### 1.3 Pre-generation flow
- **Brand Kit** is a first-class entity: logos, typography (with font-availability validation and suggested alternatives + upload), light/dark palettes, brand images, tagline, brand values, tone of voice, slides theme. "Import from website / Upload brand guidelines / Chat with Moda."
- **Format picker** with platform presets (Instagram/LinkedIn/Facebook/X/TikTok/YouTube, exact px: Square 1080×1080, 4:5 1080×1350, Landscape 1200×627, Profile Cover 1584×396, Page Cover 1128×191).
- **"Design Plan" questionnaire** between prompt and generation: number of variations (1–4), brand-kit adherence (Strict / Balanced / Loose), message focus, primary CTA, copy approach — all skippable ("Feel free to leave some or all questions blank").

### 1.4 Editing surface inventory (the human editor)
- **Menus:** File (New/Duplicate canvas, Save canvas as template, Import/Export, Theme, Version history, **Agent instructions**, Notifications, Settings, Delete). Edit (Undo/Redo/Cut/Copy/Paste/Paste-without-formatting/Select all/Duplicate/Delete). View (Zoom, Start presentation, Page thumbnails, Show margins/rulers/grid, Shortcuts). Insert (Text box, Image, Shape, Line, Table, Comment, Chart, Map, QR code, LaTeX, Mermaid diagram, **Shader**). Format (Text, Align, Font size). Arrange (Order: front/forward/backward/back with shortcuts; Group ⌘G / Ungroup). Page (New/Duplicate/Hide/Delete).
- **Toolbar:** search, Add page, undo/redo, zoom %, page-layout helper ("2-Column"), select tool, image, text, shapes grid, line/draw, Comment, present/play, canvas size (e.g. 1080×1080), background color, adjustments. When text is selected the toolbar becomes **contextual**: font family, weight, size stepper, italic/underline/strike, link, align, list, line-height, letter-spacing.
- **Details inspector (selection):** Layout (X, Y, W, H + aspect lock, Rotation + slider) · Appearance (Opacity % + slider) · Text (Color, Font, Weight, Size, Style, H-align, V-align, Line Height, Letter Spacing, Paragraph, Padding) · Stroke (Border width, color) · Effects (+ Add effect) · Arrange (To front/Forward/Backward/To back; Align H/V) · Description (**Layer name**, Note).
- **Details inspector (page):** Dimensions (size preset), Fill → Background with **Mesh Gradient** (color stops + grain), Page Duration (3/5/10/15/30s — pages play/export as slides), Margins (defaults 108px + custom override), Page name.
- **Assets panel:** Search assets, **Generate with AI**, My Images, Icon Packs, Stock Images.
- **AI image-edit modal** (double-click or "Edit image" on an image): Select (region) + Annotate tools, regenerate, **Remove Background**, **Isolate Headshots**, download, zoom/pan; a prompt box "Describe what you want to change…" (e.g. "make the product mockup screenshot in dark theme") → "Applying AI edits…" (modal locked, spinner) → **Before / After / Side-by-Side compare with Reject / Accept / Save as New**.

### 1.5 Additional findings from the screen recording
- **Selection-as-chat-context:** selecting an element on canvas attaches a chip to the chat input (`text-3: "SHRINKTHEPAPERP…"`) — the next message targets that element. This is the human→agent targeting mechanism, and it maps 1:1 onto our stable NodeIds (`modify #text-3`).
- **Compare | Revert… links under each agent chat message** — per-turn version checkpoints, browsable/revertible from the conversation.
- **Post-turn suggestion chips** ("Add entrance motion", "Add a proof stat") — cheap next-action affordances.
- **Canvas-size dropdown** with platform presets + Custom w×h + Apply — post-hoc canvas resizing is a first-class edit.
- Contextual text toolbar confirmed live (font "Anton", size 135 during text edit); button selection shows fill color, corner radius (All/Per-Corner, e.g. 42), blend mode, opacity in Details.

### 1.6 The targeted edit-review loop (second recording, 2026-07-03 01:17, 119s — chat edits on existing elements)
Observed flow, frame by frame:
1. User selects the "Healthcare paperwork…" headline on canvas → chip **`text-2: "Healthcare pape…"`** attaches to the chat input (removable ×; persists across turns for iterative refinement).
2. User: *"change the font of the text to sans serif font."* → status **"Initializing…"** → editor locks ("Moda is designing — please wait to edit"), input switches to queue mode.
3. Steps stream INTO the chat as they execute: **"Edits applied"** ✅ with narration *"I'll change the font of the selected text **(n14)** from the serif font (DM Serif Display) to a sans-serif font."* → **"Design reviewed"** ✅. Canvas updates live.
4. Final summary replaces the stream, which collapses behind a **"› Show work"** disclosure: *"Done. The headline … now uses a clean sans-serif font (Space Grotesk)… **I also adjusted the sizing and spacing so everything sits cleanly — the headline fits on two tidy lines and the subhead has proper breathing room above the UI screenshot.**"*
5. Under the message: **Compare | Revert…** + 👍/👎; contextual **suggestion chips** ("Match other pages", "Bolder headline"; after 2nd turn: "Bump to bold", "Emphasize 1/10th").
6. Second turn, same chip: *"make the text slightly bold."* → *"…now slightly bolder (weight 600 / semibold)… **The layout still fits neatly on two lines with no overlap.**"*
7. After the turn, the selected node's toolbar shows the agent-applied properties (Space Grotesk / Semi Bold / 76) — one document model; the human can continue manually with zero friction. Untouched pages stayed untouched.

Key inferences:
- **Two id layers:** display layer name ("text-2") vs internal node id ("n14") the agent narrates — chips carry the mapping.
- **Compensating edits:** a "change font" request is not applied literally; the agent re-fits size/spacing and *verifies* fit ("no overlap") — layout re-fit + verification is part of every targeted edit. (For us, managed-mode edits get the re-fit *for free* from the live solver; the critic covers the verify.)
- **Per-turn review:** "Design reviewed" runs even for one-property edits.
- **Per-turn checkpoints:** every agent message is a revert point.

---

## 2. Why human-edit-on-agent-design is smooth in Moda — six mechanisms

1. **Stored-absolute geometry.** Every element carries editable X/Y/W/H; nothing re-solves and overwrites human moves. (Ours: only frame/group/page children behave like this today; auto-layout children snap back.)
2. **One document, edit-in-place, stable layer names.** Agent and human mutate the same artifact; the agent later re-edits by the same element identity ("text-2"). No format translation between "agent output" and "editable document."
3. **Exclusive turns.** Agent turn = editor locked + message queue; human turn = agent idle. Round-trip conflicts are eliminated structurally, not merged.
4. **Human-gated AI mutations for risky edits.** AI image edits (and by extension big agent revisions) land behind a Before/After **Accept / Reject / Save-as-new** review, non-destructive.
5. **Layout discipline lives in the agent's process, not in engine constraints.** Playbooks/concepts, margins/column guides, and a screenshot self-QA pass produce aligned output on a freeform canvas. The human inherits a *simple* model (absolute boxes) rather than the agent's *authoring* model.
6. **Transparency & standing context.** Visible plan checklist, streamed step ticks, remote cursor, "Agent instructions" per document, version history — the human always knows what the agent did and can tell it how to behave next time.

**The strategic read for us:** Moda ships *editing simplicity* by making the persisted model absolute and pushing all layout intelligence into the agent's authoring process. We ship *layout intelligence* as engine constraints (the Brilliant-style solver — our quality moat) but that makes human editing hard. The synthesis (already the STUDY.md decision, now validated by a live product): **keep the solver for agent authoring & managed editing; give humans a first-class absolute escape (`position_mode`/`absolute_box` + per-container Free mode); the scene stays the single canonical artifact both parties edit in place, with exclusive turns.**

---

## 3. Gap analysis — what we have vs. Moda

| Moda capability | Ours today | Gap |
|---|---|---|
| Drag/resize any element | Only non-auto-layout children (`sceneQueries.ts:183` gate) | **Phase 1 core** (absolute_box) |
| Inspector X/Y/W/H editable | Fields exist, disabled when layout-managed (`InspectorPanel.tsx`) | Unlock via position_mode |
| Rotation control | `transform` supports rotation; is the accidental out-of-flow trigger (`layout.rs:1508`) | Expose intentionally post-Phase-1 |
| Opacity control | EXISTS (`InspectorPanel.tsx:281-297`) | — |
| Font family/weight/size/color | TextNode fields exist; inspector partial | Contextual text toolbar |
| Line-height/letter-spacing/paragraph | In type system (roles/tokens) | Expose + token-aware override (clear `*_token` on raw edit — stale-token clobber fix) |
| Image fit/focal ("crop") | **SHIPPED** (`ImageInspectorSection.tsx`: fit/focal/alt + generate/regenerate/replace + status) | Free-rect crop deferred |
| Real image pixels on canvas | **SHIPPED** (`3f43ff2`, imageCache.ts) | — |
| AI image edit (prompt, remove-bg) w/ before-after accept | Generate/regenerate exists; no prompt-edit, no bg-removal, no compare gate | Phase 3 |
| Z-order, group/ungroup, align/distribute | Ops partially exist in engine; thin UI | Phase 4 ladder |
| Turn lock + message queue during agent run | AgentChatPanel exists; no editing lock, no queue | Phase 2 |
| Plan checklist + step streaming + remote cursor | Loop has phases/trace; not surfaced live | Phase 2 |
| Agent works on live doc (round-trip) | **NO — agent seeds empty scene** (`tools.py:142`), sees 80-node text summary | **Phase 0 — the gate on everything** |
| Accept/Reject gate on agent turn | Ops auto-applied; post-preflight `replaceScene(preflight.scene)` swaps in token-baked scene (`EditorApp.tsx:1099`) | Phase 0/2 |
| Brand kit entity | BrandKitPanel + brand-kits knowledge exist | Enrich later (fonts validation, images, tone) |
| Text/fill color in toolbar; gradient fill editor | Engine renders linear/radial gradients end-to-end (model+DSL+Skia+SVG+Konva); UI is solid-hex-only, clobbers fill stack | §5 — 4b color rider, then Appearance slice at restyle |
| Page background Mesh Gradient (+ grain) | Not in `Paint` model; no Skia/SVG primitive | §5 deferral — demand-driven, weeks-class |
| Design Plan pre-brief | Nothing | Phase 2 (cheap, prompt-side) |
| Variants as named pages | Multi-page exists (PageRail) | Agent emits N concepts as pages — prompt/loop change |
| Version history / Save as template / comments / presentation / animation / shaders / charts | Partial (HistoryPanel) / absent | Phase 4+ / non-goals for now |

---

## 4. The plan

### Phase 0 — Close the round-trip (unchanged from STUDY.md, re-scoped per VERIFICATION.md; Moda is the living proof this model works)
1. Seed the agent's working scene from the live editor scene (`tools.py` `initial_scene`; thread through `factory.py`/`providers.py`; parse `payload.scene` in `main.py` instead of only summarizing).
2. Force continuation/director mode at the loop+prompts layer (`new_artifact` is an `AgentActionMode` in `schemas.py`/`loop.py`, not a tool) and **change authoring to never re-author existing NodeIds** (else `LUMD0401` rejects the whole block). This prompt/loop behavioral work is the real gate.
3. Return ops diffed against the seed; **gate application behind an Accept/Reject preview** (Moda's pattern), which also resolves the post-preflight token-baked `replaceScene` risk at `EditorApp.tsx:1099`.
4. Expose `position_mode`/`absolute_box`/`layout_mode` in `_node_brief` (once Phase 1 lands) so the agent sees "human pinned this."

### Phase 1 — Freehand editing core (STUDY.md §3, validated by Moda's model)
- `Node.position_mode (Managed|Absolute)` + `absolute_box` + `base_anchor` (serde defaults, `scene.rs`); `AutoLayoutProps.layout_mode (Stack|Free)`.
- Solver: widen the out-of-flow check (`layout.rs:264`) and route Free containers through the existing absolute path; lay Absolute nodes at `absolute_box`.
- Ops: `DetachToFreehand` / `ReattachToLayout` / `ConvertContainerToFree`, all invertible (`operations.rs:942`).
- Editor: unlock `isNodeDirectGeometryEditable` for Absolute/Free; point drag/resize commits at `absolute_box`; "Detach / Re-attach" selection action; inspector X/Y/W/H live.
- Policy decision needed: LUMV0801 (child outside clipped parent = batch-rejecting error) must downgrade/clamp for Absolute nodes.
- UX framing per Moda: **detach silently on drag** (Figma-style: dragging a managed child could auto-detach with a toast + undo), or explicit toggle first. Recommend explicit toggle for v1, auto-detach-on-drag as fast-follow.

### Phase 2 — The Moda agent-experience layer (turn-taking + transparency)
- **Design lock:** while a run is active, disable canvas edits; banner "Agent is designing — please wait to edit" (`EditorApp.tsx` + `AgentChatPanel`).
- **Message queue:** chat input queues during a run; queued messages feed the next turn.
- **Plan checklist streaming:** surface the loop's director plan + per-step completion into chat (loop already traces iterations; add SSE/polling of step events).
- **Remote cursor:** highlight the node targeted by the currently-applying op batch.
- **Variants as pages:** prompt the agent to emit N concepts as named pages (we have multi-page + PageRail).
- **Design Plan pre-brief:** a 4-question skippable form (variations / brand adherence / focus / CTA) feeding the prompt.
- **Agent instructions:** per-document standing instructions stored on the doc, injected into every run.
- **Selection-as-chat-context:** selected node(s) attach as chips to the chat input; the run receives the target NodeIds explicitly (maps to `modify #id` / structured ops — no ambiguity about "this headline").
- **Per-turn checkpoints:** snapshot the scene before each agent turn; render **Compare | Revert** under the agent's chat message (server inverse-op history already exists via `edit_envelopes`; needs UI).
- **Show-work streaming:** stream step events ("Edits applied", "Design reviewed") into chat during the turn; collapse behind a "Show work" disclosure when the final summary lands.
- **Compensating-edit behavior (prompt-side):** targeted edits must instruct the agent to re-fit and verify ("apply the change, then ensure text still fits / no overlap / spacing holds") — in managed mode the solver re-fits for free, and the P1.2 critic is the verify step; a `completed` turn should end with a one-sentence summary of what changed *and what was preserved*.
- **Contextual suggestion chips** after each turn (e.g. "match other pages" = propagate the same change to sibling pages — a cheap, high-value follow-up made trivial by stable NodeIds).
- **Notify-when-done** toast.

### Phase 3 — Image-editing surface (extends the shipped image slice)
- Prompt-driven image edit ("describe what you want to change") through the existing OpenRouter image adapter, with **Before/After side-by-side + Accept / Reject / Save-as-new** (cache-friendly: request→asset cache already exists, `image_cache.py`).
- Remove background (provider or model call); defer isolate-headshots.
- Keep fit/focal as the "crop" story short-term (already shipped); free-rect crop stays deferred (STUDY.md Phase 3).

### Phase 4 — Editor completeness ladder (prioritized floor, in order)
1. Contextual text toolbar (font/weight/size/style/align + line-height/letter-spacing) with **token-aware overrides** — raw edit clears the sibling `*_token` (the stale-token clobber fix, `operations.rs:556-597`). **SHIPPED as 4a** (commits `4e90201` engine + `cb0d2b2` toolbar, e2e-proven). Residual: raw *color* edits (fills) don't yet clear `style_token` — resolved by the 4b color rider below.
2. Align/distribute + smart guides for Absolute/Free nodes; z-order + group/ungroup UI (ops exist). **+ Color rider (decided 2026-07-04):** token-first color swatch in the contextual toolbar (text + shape solid fills), the fills-clear-`style_token` engine rule, and a gradient-clobber guard — full rationale and scope in §5.
3. Managed-drag → reorder (`MoveNode` by index); managed W/H → size-mode variant.
4. Page-level: background fill UI, margins as visible guides (agent already respects artboard bounds), page rename in rail.
5. Comments, version history UI, Save-as-template. Later/likely never: shaders, charts/map/LaTeX/Mermaid, page duration/animation, presentation mode.

### Non-goals / do-not-copy
- **Dropping the layout solver** to match Moda's pure-absolute model — the solver is our composition-quality moat (Brilliant model); Moda compensates with agent-side discipline only.
- Websites/HTML docs, slides themes, TikTok/YouTube formats, animation — out of scope for the editing milestone.
- A scene→DSL emitter — still unnecessary (edit-in-place via ops; STUDY.md §2).

### Sequencing & first milestone
Phase 0 → Phase 1 → Phase 2 in that order; Phases 3/4 parallelizable after 1. **Milestone M1 ("Moda-basic"):** agent generates → human drags/resizes/retypes/recolors any element (auto-detach or toggle) → human asks agent for a revision → agent edits in place preserving human changes → Accept/Reject preview. That single loop is the product moment Moda demonstrates.

### Risks (carried from VERIFICATION.md + new)
- Duplicate-id replay (`LUMD0401`) — gating Phase 0 work.
- Editor-vs-server text measurement parity when baking `absolute_box` (bake from canonical pass).
- LUMV0801 clip-overflow policy for freehand.
- Serde-default byte-parity for new fields on old scenes.
- Agent quality degradation on heavily-freehanded scenes (semantic erosion — honest cost; `base_anchor` mitigates).

---

## 5. Color & fills — engine capability audit + sequencing (added 2026-07-04, post-4a)

*Two code surveys on `agents/editing-roundtrip-v0` after 4a shipped, prompted by: when does color join the toolbar, and can brand kits carrying gradient backgrounds (e.g. SVGs) be used by the agent/engine without editor fill features?*

### 5.1 What the engine already has (the surprising part)

`Paint` is `Solid | LinearGradient{angle, stops} | RadialGradient{stops} | Token` (`scene.rs:750-757`); fills are a stacked `Vec<Fill>` (`scene.rs:276`); page backgrounds use the same model (`scene.rs:191`); every `ColorStop.color` may itself be a token, resolved per-stop on brand apply (`brand.rs:3568-3576`). **"Add gradients" is a UI project, not an engine project. Mesh/blur/blend are the opposite.**

| Capability | Model | DSL | Skia | SVG export | Konva preview | Editor UI |
|---|---|---|---|---|---|---|
| Solid fill (hex/oklch/token) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ crude (`RawStyleSection` hex input; `DesignTokensSection` token dropdown) |
| Linear gradient (angle + n stops) | ✅ | ✅ `linear(angle, stop(c,p)…)` (`dsl.rs:4482-4506`) | ✅ | ✅ | ✅ | ❌ |
| Radial gradient (n stops, center fixed 0.5,0.5) | ✅ | ✅ `radial(stop…)` | ✅ | ✅ | ✅ | ❌ |
| Token refs inside gradient stops | ✅ | ✅ `stop($token, pos)` | ✅ | ✅ | ✅ | ❌ |
| Drop shadow (color/opacity/x/y/blur/spread) | ✅ `EffectKind::DropShadow` (`scene.rs:737-748`) | ❌ | ✅ (`render.rs:705-750`) | ✅ | ✅ approx | ❌ |
| Node opacity (+ `$opacity.*` tokens) | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| Blur / backdrop-blur | ❌ scene-side — exists ONLY as brand *token type* (`EffectToken` Blur/BackdropBlur), no `EffectKind`, no render path | ❌ | ❌ | ❌ | ❌ | ❌ |
| Mesh gradient, blend modes, image-as-fill | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

Brand-kit side: `TokenCatalog` stores **flat colors only** (`brand.rs:1168-1192`; `ColorTokenValue = Hex | Oklch | Alias` at `brand.rs:1227-1231`) — **no gradient tokens** — though `constraints.allow_gradients` already anticipates them. Brand assets (logos/images) are `asset_id` refs into the asset store; the agent can place them only as image nodes (`image asset(<id>)`, `dsl.rs:3588`), never as fill paints. `validate_scene_brand_governance` (`brand.rs:1632-1903`) wants token fills; gradient stops satisfy this per-stop.

### 5.2 Decisions

1. **Toolbar color = 4b rider (~2 days incl. e2e).** Token-first swatch popover: brand swatches write `Paint::Token` (stays restylable, passes governance); custom picker is the escape hatch writing raw hex → node visibly **detaches** (clears `style_token` for text — closing the 4a residual), same semantics/undo as 4a typography. This is Moda's Strict/Balanced/Loose adherence expressed in one control; a raw-only picker would fight the brand story, a token-first one strengthens it. Engine piece in `editing.rs` + WASM rebuild.
2. **Gradient-clobber guard ships with the rider.** Today's `RawStyleSection` color input **replaces the entire fills stack with one solid** — a naive toolbar swatch would silently destroy agent-authored gradients. The control must detect gradient fills and defer to the fill editor (or warn) instead of overwriting.
3. **Appearance/Fills slice lands at the Moda restyle** (when the inspector's Raw-Style/Appearance surface is rebuilt): gradient stop/angle editor, per-fill alpha/opacity, drop-shadow editor (engine already renders shadows), effects list, full picker. **Pure frontend** — zero engine work; the engine renders all of it today.
4. **Brand-gradient ingestion rides the brand-import track, not the editor track.** To make "brand kit with gradient backgrounds → agent uses them natively" true: add `$gradient.*` tokens to `TokenCatalog` (+ resolver + governance + DSL sugar, ~2-3 days engine) and an ingestion extractor that lifts angle+stops out of brand SVGs into native `Paint::LinearGradient` with stop colors bound to `$palette.*` tokens. Renderers need nothing. Prompts/skills then teach the agent to use them (`prompts.py` brand guidance currently pushes solid `$surface.*` only).
5. **Gradient SVG assets are usable TODAY** as `image asset(<id>)` background nodes — with caveats: `VectorNode` is path-data-only (`scene.rs:524-532`), so defs-based gradient SVGs must be **rasterized at ingest**; and images are opaque to restyle/theming/governance (not recolorable on brand reapply, no light/dark modes). Native gradients (decision 4) are the right long-term path. Known adjacent gap: agent loop doesn't yet reliably *place* imagery even though plumbing works (see image-agent-integration memory).
6. **Demand-driven deferrals** — each is scene schema + both renderers + DSL + governance + WASM (the expensive class), and nothing consumes them yet: **mesh gradients** (no Skia primitive, no SVG-export representation → rasterize fallback; weeks-class — this is Moda's page-background Mesh Gradient + grain), **blur/backdrop effects** (promote the existing token types to `EffectKind` when a consumer appears), **blend modes**, **image-as-fill**.

### 5.3 The orthogonality principle (why brand kits don't block on the editor)

Editor UI and agent capability are **decoupled**: the agent authors through the DSL, and DSL + both renderers + the Konva preview already handle gradients end-to-end. The agent could emit `linear(45, stop($palette.primary.500, 0), stop($palette.accent.400, 1))` today and the human canvas renders it faithfully — the human just can't *edit* it until the Appearance slice. So: agent-side brand-gradient support needs only decision 4 (tokens + ingestion); human-side editing catches up at the restyle; neither waits on the other.

### 5.4 Sequencing

**4b color rider → Appearance/Fills slice @ Moda restyle → `$gradient.*` tokens + SVG extraction @ brand-import track → mesh/blur/blend/image-fill on demand.**

---

## 6. Handoff-absolute (decided + SHIPPED 2026-07-05, user-critical)

Direct user feedback after 4b (recordings in `.context/phase4b5/`):
end users (sales/marketing) must never experience layout-engine behavior —
no sibling re-flow on drag, no detach concept, no auto-layout jargon. This
SUPERSEDES Phase 1's "explicit detach toggle" UX framing: detach still
exists as power-user surface, but the primary contract is now **the layout
engine is the agent's authoring tool; humans always receive baked
absolute** — precisely Moda's authoring-time-intelligence → baked-absolute
handoff (§1.1/§2.5), while we retain the ability to re-enter the solve.

Mechanism (record: `.context/phase4b5/IMPLEMENTATION.md`):
- Engine `build_freeze_layout` — every unlocked Stack container → Free in
  one invertible zero-motion batch; layout props survive so agent turns can
  re-Stack; idempotent; wire kind `freeze_layout`.
- Freeze at agent-turn **Accept**, merged into the turn's own undo frame /
  envelope / checkpoint (one ⌘Z = whole turn incl. freeze).
- Lazy freeze on **first human gesture** on a solver-managed node
  (pointer-down seam) — migrates pre-freeze docs invisibly.
- Round-trip: exclusive turns; chip-targeted property edits are
  layout-inert; layout-affecting turns may re-Stack → Accept re-freezes.
  Agent-side follow-ups pending: layout_mode/human-arranged in _node_brief,
  prefer-absolute-edits prompt policy, explicit transforms on insert into
  Free containers.

### Phase 4c — RE-SCOPED (2026-07-05): agent edits on human-owned geometry

The original 4c (managed-drag → reorder) is largely obsoleted by
handoff-absolute: humans rarely touch managed nodes now (first touch
freezes). The retest exposed the real 4c: **the agent cannot move a pinned
node** — DSL `p()` writes `transform`, which pinned nodes ignore
(`absolute_box` is authoritative, page-space) → user asks like "move the
badge" are silent no-ops on exactly the elements humans drag.

Decision: make `p()`/`s()` JUST WORK on pinned targets — the DSL compiler
translates them into `absolute_box` updates using the parent's solved
page-space origin (the compile session holds the laid-out scene). Zero new
concepts for the agent; "move it there" is owner-independent. Rider: the
agent brief's "pinned nodes must not be re-positioned" note rewords to
"pinned geometry is human-owned — move it only when the user asks."
