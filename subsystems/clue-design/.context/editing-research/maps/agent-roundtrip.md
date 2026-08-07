# Subsystem map: Agent loop & repair on existing/modified scenes (round-trip crux)

**Scope of this map:** what the agent author/repair loop actually *consumes* as input,
whether it can ever ingest a scene it did not author (e.g. a human freehand-edited one),
what it *emits*, how the editor applies that output to the live scene, and the realistic
smallest change to let the agent "take back" a human-edited design.

Entry points read: `apps/agent_runtime/lumen_deepagent/{loop.py,tools.py,prompts.py,factory.py,cli.py}`,
`apps/api/lumen_api/main.py` (the `/agent/turn-preview` HTTP boundary the editor calls),
`apps/api/lumen_api/models.py`, `apps/editor/src/engine/agentRunner.ts`,
`apps/editor/src/components/{AgentChatPanel.tsx,EditorApp.tsx}`.

---

## TL;DR (the crux, stated bluntly)

**The agent never edits the editor's scene. It always builds a brand-new scene from
zero, in memory, on every turn.** The editor's live scene (which is exactly where any
human freehand edits would live) is passed to the runtime **only as a truncated text
summary embedded in the prompt** — never as the working `Scene` object the loop mutates.

- `LumenDesignTools.__init__` unconditionally calls `self.scene = self.core.new_scene(...)`
  — a fresh empty scene — at `tools.py:132`. There is **no constructor argument, setter,
  or code path** anywhere that seeds `tools.scene` from an incoming editor scene.
- The HTTP handler `run_agent_turn_preview` receives `payload.scene` (the editor's real
  scene JSON) but uses it **only** to build `scene_context_summary(...)` text in
  `editor_agent_prompt(...)` (`main.py:3079-3107`). The scene object itself is dropped on
  the floor as far as the loop's working state is concerned.
- The loop's repair input is therefore its **own** compile/preflight/critic feedback on
  the **scene it just authored this turn** — not the editor's scene, and emphatically not
  any human modifications to it.

So: **today there is no scene→working-state path. The "round-trip" the user asks about
does not exist; every turn is a from-scratch regeneration informed by a prose summary.**

---

## 1. What is the agent's INPUT when it authors / repairs?

### 1a. The loop builds its own scene from nothing

`LumenDesignTools.__init__` (`tools.py:122-152`):

```python
self.scene = self.core.new_scene(self.run_id, "Agent-authored design")  # tools.py:132
```

Both runtime entry points construct tools this way and never inject a scene:

- `create_lumen_design_agent` (`factory.py:30`): `tools = LumenDesignTools(runtime_config, prompt)`
- `create_provider_quality_loop` (`providers.py:155`): `tools = LumenDesignTools(config, prompt)`

The loop then *grows* `tools.scene` only through core responses to its own
compile/operation calls — every mutation routes through
`_replace_scene_from_core_response` (`tools.py:1619-1624`), which overwrites
`self.scene` with `response["scene"]` from `compile_dsl_block` / `apply_operations` /
`apply_structured_edit` / preflight. The only other writer is
`start_fresh_rewrite_scene` (`tools.py:1498-1509`), which *also* calls
`self.core.new_scene(...)` — i.e. wipes to empty for a director-approved rewrite.

**Conclusion: `tools.scene` only ever contains what the agent itself authored this run.**

### 1b. What the repair loop actually reads each iteration

In `LumenQualityLoop.run` (`loop.py:190-765`), each iteration:

1. Builds `full_context = self.tools.curated_context(...)` (`loop.py:201`).
2. The director decides an `action_mode` from that context (`loop.py:206`).
3. The author gets an `AuthoringBlockRequest` (`loop.py:264-276`) whose scene-derived
   fields are:
   - `current_scene_summary=json.loads(self.tools.summarize_scene())` (`loop.py:272`)
   - `repair_context=self.previous_feedback[-1] if ...` (`loop.py:273`)
   - `full_context=full_context` (`loop.py:275`)

`curated_context` (`tools.py:1211-1249`) is built **fresh from `self.tools.scene`** (the
agent's own authored scene) plus `previous_feedback`. Its scene-derived fields:

- `"scene_summary": self._scene_summary()` (`tools.py:1235`, impl `1681-1699`) — page/node/
  slot counts and per-page child-id lists and slot briefs of the **agent's** scene.
- `"scene_subtree": self._scene_subtree_for_targets(target_ids)` (`tools.py:1236`,
  `1303-1330`) — node briefs for diagnosed nodes only, capped at
  `CONTEXT_MAX_SUBTREE_NODES = 24` (`tools.py:47`).
- `"diagnostics"` — the loop's own most-recent compile/preflight diagnostics
  (`_latest_diagnostics_ranked`, `tools.py:1253-1279`).
- `"latest_feedback"` / `"latest_critique"` / `"attempt_history"` — the loop's own prior
  rejections (`tools.py:1332-1427`).
- `"preview_summary"` — pointer to the PNG/SVG the loop itself just rendered, plus
  `visible_text` harvested from **its own** scene nodes (`tools.py:1429-1485`).
- `"conversation_context": extract_editor_conversation_context(self.prompt)`
  (`tools.py:1234`) — see §1c.

**Every scene-shaped field in the author/director/reviewer context is derived from
`self.tools.scene`, which is the scene the agent authored this run.** None of it reflects
the editor's scene except indirectly through the prompt text.

### 1c. The only channel carrying the editor scene: prompt text

The editor scene reaches the runtime exactly once, as prose, two layers up:

`editor_agent_prompt(payload)` (`main.py:3079-3096`) produces:

```
{payload.prompt}

Editor context JSON:
{json.dumps(context, indent=2)}
```

where `context["scene_summary"] = scene_context_summary(payload.scene)`
(`main.py:3084`, `3099-3107`). `scene_context_summary` keeps `meta`, a page summary, the
**first 80 node summaries** (`node_summary(scene)[:80]`, `main.py:3103`), slot summary, and
counts. This is a lossy digest: it is truncated, it is not the canonical scene, and it is
never parsed back into a `Scene`.

The runtime can *see* this text two ways:
- `self.prompt` is the whole concatenated string (it is the `prompt` arg passed to
  `LumenDesignTools`).
- `curated_context["conversation_context"] = extract_editor_conversation_context(self.prompt)`
  (`tools.py:1234`, `1929-1940`) — but this only extracts a `conversation_context` sub-key
  if present; for the editor path it returns `{"raw_prompt": prompt}` (the marker is
  `"Editor context JSON:"`, and that JSON has no `conversation_context` key), so the
  structured scene summary is *not* surfaced as a tidy field — it lives only in the raw
  prompt blob the model reads.

**So the agent can, in principle, read a textual description of the editor scene from its
prompt. It cannot operate on that scene as data, and nothing in the loop reconstructs a
working scene from it.** Whether the LLM author chooses to honor that prose description is
entirely up to the model; the harness does not enforce or even structurally expose it.

---

## 2. Does the agent ever consume a scene it did NOT author?

**No — not as working state.** There is:

- **No scene→DSL path.** Nothing decompiles or serializes the editor scene into DSL for
  the author to extend.
- **No scene→operations path.** Nothing diffs the editor scene against the agent's scene.
- **No scene loader.** `new_scene` is the only initializer; no `load_scene(scene)` exists.

The agent consumes a foreign scene **only as the truncated prompt summary** described in
§1c. Every tool that reports "the scene" (`summarize_scene`, `summarize_page`,
`query_geometry`, `_scene_subtree_for_targets`, etc.) reads `self.scene`, which is the
agent's own fresh build.

**Implication for human edits:** if a human freehand-edits the design in the editor and
then asks the agent to continue, the agent receives a *prose summary* of the human-edited
scene (first 80 nodes, counts, slot keys) and then **authors a completely new design from
scratch** that it hopes resembles the request. It does not load, preserve, or even
reliably perceive the specific freehand changes (absolute positions, reparenting,
relative→absolute switches). Those edits are structurally invisible to the working loop.

---

## 3. What does the agent EMIT, and how does the editor apply it?

### 3a. The agent emits full-DSL authoring blocks internally; the API exposes them as canonical operations

Inside the loop the author returns **DSL source** (`source = self.author.write_block(...)`,
`loop.py:289`), compiled via `compile_dsl_block` (`tools.py:170-275`). Repairs are either
full DSL blocks or **modify-only `#<id> ...` lines** enforced by surgical / layout-cluster /
slot-fixture gates (`loop.py:304-400`, `is_surgical_dsl` at `loop.py:1539-1557`).

At the HTTP boundary, `agent_response_from_trace` (`main.py:3110-3182`) does **not** return
the agent's final scene as the thing to apply. Instead it:

- Reads each iteration's `dsl.lumen` into `dsl_blocks` (`main.py:3121-3123`).
- Reads each iteration's `compile.json` and, **only for `status == "ok"` iterations**,
  extends `operations` with `compile_payload["operations"]` (`main.py:3136-3137`). These
  are the **canonical operations the agent's compiler emitted while building its own fresh
  scene** (e.g. `add_page`, `insert_node`, `upsert_slot` …).
- Returns `draft_scene = tools.scene` (the agent's final in-memory scene; passed in at
  `main.py:3068`).
- Sets `status = "proposed"` only if `result["status"] == "accepted"` **and** there are
  operations (`main.py:3145-3146`); otherwise `"failed"`.

So the wire payload (`agentRunner.ts:28-38`, `EditorAgentResult`) carries: `dsl_blocks`,
`operations`, `draft_scene`, `diagnostics`, `artifacts`.

### 3b. How the editor applies it

`applyAgentProposal` (`EditorApp.tsx:1028-1060`) takes **`agentProposal.operations`** and
calls `applyOperations(proposedOperations, ...)`. `applyOperations`
(`EditorApp.tsx:373-434`) runs them through the local WASM engine
(`engine.applyOperations(operations)`, line 396) against the **current editor scene**, then
`setScene(result.scene)`.

There are two apply modes:

1. **Accepted proposal → operations applied onto the live editor scene** (the normal path,
   `EditorApp.tsx:1035`). The agent's operations were authored against its **own fresh
   scene starting from empty**, so they are overwhelmingly *constructive* operations
   (`add_page page_…`, `insert_node …`). Replaying them onto a non-empty editor scene that
   already has those IDs would collide — which is part of why the agent's whole-scene
   regenerations don't compose with an existing edited scene.
2. **Failed run with a draft → whole-scene replacement.** `showAgentDraftScene`
   (`EditorApp.tsx:521-549`) calls `replaceScene(draftScene)` — it **wholesale replaces**
   the editor scene with the agent's `draft_scene`, discarding any human edits (pushed to
   the undo stack first, `EditorApp.tsx:538-546`). This is the "best draft" the loop
   restored via `_restore_best_scene` (`loop.py:805-813`).

**Net:** the editor's apply surface is "replay the agent's constructive operations" or
"replace the scene with the agent's draft." Neither is a targeted patch *of the human's
edited scene*; both assume the agent's scene is authoritative.

---

## 4. If a human freehand-edited a design, what would the agent SEE — and could it preserve those edits?

**What it would SEE:** a truncated textual summary in its prompt — `meta`, page sizes,
the first 80 node briefs (id/name/kind/transform/size/computed/slots, from
`node_summary`), slot keys, asset/profile counts (`main.py:3099-3107`). It would **not**
see: full node geometry beyond the first 80 nodes; the precise nature of a freehand change
(it can't tell "this node was reparented from relative to absolute" — it just sees the
resulting transform/parent in the summary, if that node is within the first 80); any
"freehand mode" flag (none exists in any schema read here).

**Could it preserve them? No, not reliably, today.** Because the agent **regenerates from
scratch**, any preservation would require the LLM to (a) read the prose summary, (b)
faithfully reconstruct the human's exact positions/parents/sizes in new DSL, and (c) do so
within the first-80-node truncation and the 24-node curated subtree cap. There is no
mechanism that *guarantees* preservation; the surgical/cluster gates
(`loop.py:304-400`) constrain the agent's edits to its **own** scene's node IDs, which are
not the editor scene's IDs. The keep-best/restore logic (`loop.py:767-813`) protects the
*agent's* best draft, not the human's edits.

**Concretely, the failure mode the user described is structural:** freehand edits change a
node's parent/positioning/relative→absolute. The agent loop has no representation of those
edits as inputs and no way to apply targeted ops to the editor's scene. Its output is
either constructive ops (that collide with existing IDs) or a full-scene replacement (that
nukes the human's edits via `replaceScene`). So "the agent takes it back" is not supported.

---

## 5. What's the smallest change to let the agent "take back" a human-edited scene?

Labeled **PROPOSAL** (does not exist today). Ordered by increasing scope.

### P0 — Seed the working scene from the editor (the missing scene→working-state path)
The single highest-leverage change. Today `run_agent_turn_preview` discards `payload.scene`
into a text summary (`main.py:3068`, `3079-3096`) and `LumenDesignTools` always builds
empty (`tools.py:132`). Add an optional `initial_scene` to `LumenDesignTools.__init__`
that, when provided, sets `self.scene = copy.deepcopy(initial_scene)` instead of
`new_scene(...)`, and thread `payload.scene` through `create_provider_quality_loop` →
`LumenDesignTools`. This alone makes `summarize_scene`, `query_geometry`,
`_scene_subtree_for_targets`, and the surgical/cluster gates operate on **the human-edited
scene's real node IDs**, so the agent's `#<id> ...` modify lines target the human's actual
nodes. Required corollaries:
  - The compiler must accept "continue editing an existing scene" — i.e. `dsl_session`
    semantics and the duplicate-page guard (`tools.py:176-209`,
    `first_existing_page_declaration`) already assume the scene may be non-empty, so the
    surgical-repair path is the natural fit; the director must be biased to
    `targeted_patch` / `layout_cluster_rewrite`, not `new_artifact`.
  - The API must return **only the operations that diff the seeded scene** (not the full
    constructive set). Today operations are harvested from compile output that built from
    empty (`main.py:3136-3137`); with a seeded scene the compile operations would already
    be the targeted edits, so this mostly falls out — but `start_fresh_rewrite_scene`
    (`tools.py:1498`) and any `new_artifact` director decision must be suppressed for
    "continue editing" turns or they will wipe the seed.

### P1 — A representation that survives freehand edits (the round-trip representation)
For the agent to *take back* freehand edits, the editor scene must encode them in a form
the agent can read and the compiler can re-author around. This is where freehand-vs-layout
mode matters: absolute positions / reparenting must be expressible as canonical scene
fields the agent's `summarize_scene` exposes and its modify-lines can preserve. The
**minimum** is: (a) freehand edits are stored as normal canonical scene state (transform,
parent, sizing-mode) — which the operations model already supports (`move_node`,
`update_node`, see `AgentChatPanel.tsx:200-238`); and (b) the agent is seeded with that
scene (P0) and instructed to preserve untargeted nodes. No new DSL needed if the agent
edits via structured ops against the seeded scene rather than re-authoring DSL.

### P2 — A scene→DSL (or scene→ops baseline) decompiler
If the author must keep emitting DSL, something has to turn the human-edited scene back
into DSL the author can extend without duplicate-ID collisions. None exists today
(confirmed: no decompile path). This is strictly bigger than P0/P1 and only needed if the
team insists DSL remains the sole authoring surface for continuation turns.

---

## 6. WHAT EXISTS TODAY vs WHAT'S MISSING

### Exists today
- A full author→compile→preflight→export→critic→repair loop over a scene the agent
  authors from scratch (`loop.py:190-765`).
- Strong surgical / layout-cluster / slot-fixture repair gates that keep repairs in-place
  and modify-only **against the agent's own scene** (`loop.py:304-400`, `1539-1712`).
- Keep-best + restore so a failed run still hands back the agent's best renderable draft
  (`loop.py:767-813`).
- The editor → API → runtime wiring that passes the editor scene, page, selection, and
  diagnostics (`agentRunner.ts:48-71`, `main.py:1016-1027`, `models.py:102-109`).
- The editor scene summarized into the agent's prompt text (`main.py:3079-3107`).
- An apply path: agent operations replayed onto the live scene
  (`EditorApp.tsx:1028-1060`, `373-434`), or a full draft-scene replacement on failure
  (`EditorApp.tsx:521-549`).

### Missing today
- **Any path that loads the editor's scene as the agent's working scene.** `new_scene` is
  the only initializer (`tools.py:132`); the incoming scene is summary-only.
- **Any perception of human freehand edits as data.** Only a truncated 80-node prose
  summary is available, and only via the raw prompt.
- **Any guarantee/mechanism that the agent preserves untargeted (human-edited) nodes.**
  Regeneration + full-scene replacement actively destroys them.
- **Any scene→DSL decompiler** to let the DSL author extend a human-edited scene.
- **Any "freehand mode" flag** in `AgentTurnPreviewRequest` or the schemas (`models.py`,
  `schemas.py`) telling the agent the scene contains absolute/reparented nodes to respect.

---

## Editing implications & round-trip

The round-trip question — "after a human freehand-edits, can the agent take it back?" —
**has a clear answer in the current code: no.** The agent loop is architecturally a
*generator*, not an *editor of a given scene*. It starts every turn from an empty scene
(`tools.py:132`), grows it from its own DSL, and the editor's real scene (the only place
human edits live) is injected solely as a lossy, truncated prompt summary that is never
parsed into working state (`main.py:3068`, `3079-3107`). The agent's repair gates are
sophisticated but they police *its own* node IDs, so they cannot, even in principle,
preserve a human's specific freehand changes to the editor scene.

The decisive lever is P0: **seed `tools.scene` from `payload.scene`.** That single change
flips the loop from "regenerate" to "edit the given scene," at which point the existing
surgical / structured-edit machinery (which already targets real node IDs and emits
`move_node`/`update_node` operations the editor can replay onto the live scene) becomes
directly reusable for round-trip editing. Without it, freehand edits and the agent will
always fight — the agent will either emit colliding constructive operations or replace the
whole scene and discard the human's work. The realistic usable scope is therefore: (1)
seed the scene, (2) force a continuation/director mode that forbids `new_artifact` /
`start_fresh_rewrite_scene` so the seed is never wiped, (3) constrain output to targeted
operations diffed against the seed, and (4) ensure freehand edits are stored as ordinary
canonical scene fields (transform/parent/sizing-mode) so they round-trip through
`summarize_scene` and the structured-edit surface. A scene→DSL decompiler (P2) is only
needed if DSL must remain the sole authoring surface.
