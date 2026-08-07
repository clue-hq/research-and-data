# Increment 0a — Seeding spike: empirical findings

Date: 2026-07-03. Branch: `add-image-model-to-design-tool` (this workspace).
Harness: `.context/phase0a/probe_0a.py` (real Rust helper + real FastAPI app, no fakes),
`.context/phase0a/e2e_0a.py` (real LLM through `run_agent_turn_preview`).
Raw data: `PROBE-RESULTS.json`, `E2E-RESULT.json`, `E2E-RESULT-FULL.json`, `e2e-trace/`.

## What was wired (committed code)

- `LumenDesignTools.__init__` accepts `initial_scene`; seeds `self.scene` from a deep
  copy instead of `new_scene`, records `seeded_from_initial_scene` + counts in the
  `run_started` trace event, `input.json`, and `scene_update_sources[0] == "initial_scene_seed"`.
- Threaded through `create_lumen_design_agent` (factory.py) and
  `create_provider_quality_loop` (providers.py).
- `run_agent_turn_preview` (main.py) now parses `payload.scene` into the seed via
  `agent_seed_scene()` (shape-guarded: needs `meta`/`pages`/`nodes` dicts) instead of
  only text-summarizing it.
- **Bonus wiring fix found by the probes:** the agent runtime and the API resolved
  *different* asset-store roots by default (`.lumen-runs/asset-store` vs
  `apps/api/asset-store`). A seeded scene referencing API-ingested assets therefore
  failed agent-side export with `LUME0210 asset bytes missing`. `run_agent_turn_preview`
  now aligns the agent's store to the API's (`api_asset_store_root()`), unless
  `LUMEN_AGENT_ASSET_STORE` explicitly overrides.
- Tests: 2 new runtime tests (seeded/unseeded init), 1 new API test (seed-scene guard).
  Full suites green: 173 passed, 1 skipped.

## The saved doc used

The image-baseline GTM poster (`apps/api/tests/fixtures/image_baseline/design.lumen`),
built through the real pipeline (ingest hero asset → compile DSL → upsert asset →
preflight) and saved through `POST /documents`. 6 nodes (`canvas`, `hero`, `band`,
`kicker`, `headline`, `body`), 1 page (`hero_poster`).

## Probe 1 — seeded trivial `modify #id`: ✅ compiles and applies

`#headline text("Calmer clinics, faster triage") s(936,180)` on the seeded scene:

- compile `status: ok`, 1 operation, 1 applied, no halt, no diagnostics.
- Headline content changed; **all 5 other nodes byte-identical**; node count 6→6.
- Missing-target variant `#no_such_node s(100,100)` halts with **LUMD0901**
  ("target node no_such_node does not exist", severity error) and applies nothing.

## Probe 2 — re-authoring an existing id: ✅ LUMD0401 rejects, and blocks are ATOMIC

- `page second_page …` + `headline text …` (re-author) → halt **LUMD0401** at the
  duplicate line, `applied_operations: 0`, **scene completely unchanged** — even the
  *valid* `page second_page` line before the halt did not land.
- Mixed block (`#kicker text("UPDATED KICKER")` then a re-author line) → same halt,
  `applied_operations: 0`, **the valid pre-halt modify did NOT land** (kicker unchanged).
- Conclusion: compile-into-scene is all-or-nothing on halt. There is **no partial-leak
  risk** from a re-authoring block — the whole turn's block is wasted instead. 0b's
  job is confirmed as *productivity* (stop wasting turns), not *safety* (the engine
  already fails closed).

## Probe 3 — NodeId stability across human delete + recreate: ✅ stable/predictable

Through the real document API (the editor's path):

- `remove_node headline` → headline gone; `POST /undo` → **headline restored with the
  same id, byte-identical node, correct position** in parent children.
- Delete then re-insert with the SAME id (`insert_node`) → **allowed**, lands back at
  the same index. Ids are reusable after delete; no tombstoning.
- Editor-side (code-verified): editor undo restores snapshot scenes
  (`EditorApp.tsx` `replaceScene(undoFrame.scene)`), so ids are stable under undo.
  The editor has **no from-scratch node creation UI** today; the only "recreate"
  path is page duplication, which mints deterministic derived ids
  (`<sourceId>_<pageSuffix>`, `_2`, `_3` on collision — `uniqueClonedNodeId`).
  Nothing generates random ids.

## E2E — seeded turn through the real LLM (`run_agent_turn_preview`)

Run 1 (max_iterations=2, before the asset-store fix), full trace in `e2e-trace/`:

1. `run_started`: **seeded scene from initial_scene (6 nodes, 1 pages)** — wiring works.
2. **Director chose `targeted_patch` unprompted** — "User request is a pure copy change
   on the selected `headline` text node." The feared it-always-authors-fresh failure
   mode did NOT occur (no `new_artifact`, no `start_fresh_rewrite_scene`) — at least
   for a copy change with `selected_node_id` present. 0b's forcing is still wanted as
   a guarantee, but the prompt machinery already biases correctly.
3. Iteration 1: author wrote `#headline text "…"` — **wrong modify-line grammar**
   (needs `text("…")`) → LUMD0210, 0 ops, scene untouched. One of two iterations
   burned on syntax discovery. → 0b prompt work: put modify-line grammar
   (knowledge/lumen-dsl/directives.md) in the author's face for targeted turns.
4. Iteration 2: `#headline text("Calmer clinics, faster triage")` → **compiled,
   1 op applied onto the seeded scene, preflight clean, SVG+PNG exported** — the
   exit-criterion event: a seeded, targeted edit landing on an existing scene, e2e.
5. **The visual reviewer REJECTED the turn anyway** — hero bytes missing (the
   asset-store split, now fixed) plus *pre-existing* composition complaints
   (32pt headline "does not dominate", dead band). Budget hit → `status: "failed"`,
   `stop_reason: max_iterations_reached`, and — critically — **`operations: []`**.

### The decisive 0b/0c finding from the e2e

`agent_response_from_trace` only returns operations when the run is `accepted`, and
the reviewer judges the ENTIRE artifact at ship-quality. So a perfect targeted edit
on an imperfect (human-owned!) design returns `failed` with zero ops — the edit
exists only in `draft_scene`. **Targeted-edit turns need an edit-scoped acceptance
path** (Moda's "Edits applied ✓" separate from "Design reviewed ✓"), or every
seeded turn on a real-world doc will be held hostage by pre-existing critique.
This re-scopes 0b: continuation mode isn't just "forbid new_artifact"; it must also
change the acceptance/return contract for targeted turns.

### Secondary findings

- **Diagnostic mangling (pre-existing):** DSL-session diagnostics arrive shaped
  `{"diagnostic": {...}, "span": {...}}` but `diagnostics_from` (tools.py) reads
  top-level keys → `code: null`, `severity: "info"`, real payload stringified into
  `message`. Only `halted_at.code` carries LUMD codes cleanly. The 0b guardrail
  (catch LUMD0401 → reroute to `modify #id`) should key off `halted_at.code`, and/or
  unwrap the nested `diagnostic` in `diagnostics_from`.
- Loop protections already relevant to seeding: `full_page_rewrite` /
  `replace_artboard_subtree` call `start_fresh_rewrite_scene` (wipes to a NEW scene,
  with restore-on-failed-compile). Under seeding, "restore" restores the seed — but a
  *successful* structural rewrite replaces the seeded doc wholesale. 0b must block or
  re-point these modes when seeded.
- `LUMA0200` (duplicate page) guard in `compile_dsl_block` already protects seeded
  scenes from page re-declaration before the compiler even runs.

## Run 2 (asset store aligned, max_iterations=3) — ✅ EXIT CRITERION MET

Trace preserved at `e2e-trace-run2/`. Same brief, same seed:

1. Seeded (6 nodes, 1 page) → director `targeted_patch`.
2. Iteration 1: same `#headline text "…"` grammar mistake → LUMD0210 (reproducible;
   the author reliably doesn't know modify-line grammar on the first try).
3. Iteration 2: `#headline text("…")` → 1 op applied, preflight clean, SVG+PNG
   exported — hero image now renders (store fix confirmed live).
4. Critic still rejected on *pre-existing* composition grounds (placeholder-gradient
   hero, 32pt headline, spacing).
5. **The director OVERRODE the critic and accepted**, with exactly the right
   reasoning: *"the visual critic flags pre-existing composition issues — but those
   are outside the user's stated scope and the user explicitly said not to change
   anything else. Honoring user intent takes precedence over unsolicited redesign."*
6. Editor-facing response: **`status: "proposed"`, `operations: [update_node]`
   (exactly 1), `stop_reason: "accepted"`** — all 6 node ids and the page preserved,
   headline content updated, everything else untouched.

So the full loop — seed → targeted authoring → compile onto existing scene →
render with real assets → scoped acceptance → ops returned to the editor — works
TODAY for a scoped copy change, with zero prompt/loop changes. The director's
scope-override is model judgment, not a contract (run 1 shows the same setup
failing when a blocker exists and the budget is tighter), which is exactly what 0b
item 3 must make deterministic.

## PNG ↔ SVG output disparity (flagged for next discussion)

Observed directly in `e2e-trace-run2/iterations/002/` (both `preview.png` and
`preview.svg` are committed for side-by-side comparison):

- The compiled scene's `hero` image node carries **no placement/fit** — `hero.kind`
  is just `{alt, asset_id, kind}`. Fit/focal is not expressible in this DSL yet
  (the image-baseline README notes placement is injected scene-side, "not yet
  expressible in DSL — Step 7 adds it"), so a DSL-authored scene lands a bare
  image node with no fit.
- With no explicit fit, the **two exporters default differently**:
  - **SVG** (`svg.rs`) emits `<image … preserveAspectRatio="xMidYMid meet">` with
    **no clipPath** → *contain*. A 1280×720 (16:9) source in the 1080×810 (4:3)
    hero frame scales to 1080×607.5, **letterboxed** with ~101px white bands top
    and bottom (the white canvas shows through).
  - **PNG** (Skia raster) renders the same node as *cover* → **full-bleed**,
    filling all 1080×810 and cropping the 16:9 sides. This is what the PNG shows.
- **Why it matters:** `export_preview_bundle` calls SVG "the canonical preview
  contract," yet the visual critic is shown the **PNG** when the critic format is
  PNG. So the agent approves cover-rendered pixels while the canonical SVG (and any
  SVG/PDF a human exports) would show a letterboxed image — the agent's quality
  judgment and the shipped artifact can diverge on every image. For the Moda-style
  human-editing round-trip this is worse: the on-canvas render (CanvasKit/Skia =
  cover) and an SVG/PDF export (contain) would not match, so a human's crop/focal
  intent renders one way live and another way on export.
- **Direction to resolve (next):** make image fit an explicit, persisted node
  property (Phase-1 territory — it's the same `absolute_box`/placement work) and
  make BOTH exporters honor it identically. Short term, align the SVG default to
  the raster default (cover via `slice` + a clipPath, honoring the focal point)
  so the canonical contract matches what the critic scored. This should be pinned
  by a golden that renders the SAME node through both paths and diffs the fit.

## Decision for 0b

> **STATUS: 0b SHIPPED** — all four items implemented and e2e-validated on
> `agents/editing-roundtrip-v0`; see `0B-IMPLEMENTATION.md` for what landed and
> `e2e-trace-0b/` / `e2e-trace-0b-final/` for the validation runs. One
> refinement discovered live: in-scope critique issues block only at
> error/blocker severity — warnings/info on edited nodes are advisory too.

Proceed with 0b, re-scoped to four items (was three):
1. Forbid `new_artifact` / `start_fresh_rewrite_scene` when seeded (guarantee, since
   the director already *tends* to choose targeted_patch).
2. Author-prompt work: modify-line grammar + never re-author existing ids; catch
   `halted_at.code in {LUMD0401, LUMA0200}` and reroute as corrective feedback.
3. **NEW — edit-scoped acceptance + return contract:** a targeted-edit turn returns
   its ops when the *edit* is verified applied (preflight-clean, edit landed), even
   if whole-design critique still has complaints; surface the critique as advisory
   diagnostics instead of blocking. (This is what makes 0c's Accept/Reject gate
   meaningful.)
4. Regression assertion: untouched nodes byte-identical after a targeted turn
   (probe 1 shows the engine already guarantees this; make it a fixture).
