# Fast-loop Phase 2 TUNING wave — 2026-08-24

Base `def019973` (`integration/frontend-design-part-iv-v4`). Worktree was served
a stale base (`5ea7a879`, an ancestor) and was `git reset --hard` to `def019973`
before any work — check this every time; it has now happened repeatedly.

Follows `_memory/2026-08-24-deepagent-fast-loop-session.md` §7 (acceptance run
#1). Three tuning items, each scouted against the live run trace before design.

Evidence read (read-only, outside the worktree):
`…/colombo/subsystems/clue-design/.deepagent-workspace/run_4b5dd17f9e944269b94ca45d3bd6d9f2/`

## What the trace actually showed

Reconstructed a chronological timeline from `logs/run.jsonl`
(`llm_call_completed` + `tool_*_completed`, with tool_calls decoded).

**TTFP = 369s, and it breaks into three separate causes, none of them latency:**

| window | role | cost | what happened |
|---|---|---|---|
| 0–117.6s | orchestrator | 7 calls | direction phase. 2 globs, 3 ls, and a read of `/knowledge_docs/design/layout-recipes.md` that does not exist (correct path is `/knowledge_docs/knowledge/design/…`, read 27s later). One 40.3s call just to write `direction.md`. |
| 117.6–227.7s | author | 4 calls | 3 of them pure reads: **8 SKILL.md reads**, with `create-design` and `effects` read TWICE. Then the first compile. |
| 227.7–232.2s | author | 2 calls | first compile, then **preflight CLEAN** (`has_errors: false`). |
| 232.2–369.2s | author | 3 calls | **137s of detour**: `inspect × 3` (52.6s), a second compile (38.6s), then finally render. |

The decisive fact: **the first preflight was already clean at 232s.** Rendering
straight off it lands TTFP at ~236s = 3m56s, inside the 4m gate, with no other
change. §5.1's "zero grep/glob/ls" acceptance criterion binds only the author;
the orchestrator spent 5 calls hunting the filesystem from the same ceiling.

**Budget death:** round 2's direction was written at 596s and the `task`
delegation fired at 604.5s — with the wall clock already past 600s. Nothing in
the loop knew. The only budget text any role ever saw was the STATIC ceiling
interpolated once into the orchestrator system prompt at assembly time.
`RunBudget` already held every number needed to refuse; it exposed none of them
to a consumer.

**The overlap defect — the premise was wrong, and that mattered.**
- Enumerated all **477** diagnostic codes across the Rust crates. **No overlap /
  collision / sibling-intersection diagnostic exists.** Geometry codes are
  containment only (`LUMV0800/0801` node-vs-page/parent) and text-fit-vs-own-box
  (`LUMV0900–0907`). Every preflight in the run was `has_errors: false`.
- **The shipped scene has NO box overlap.** Measured per-row ink in
  `iterations/004/preview.png`: headline line 2 ends y=592, support starts
  y=640 — 48px clear. Same for `iterations/002`. A bounding-box intersection
  sweep would have caught this **zero times**.
- The real mechanism: `line_height` is a **multiplier model**.
  `lumen-skia/src/measure.rs` sets SkParagraph's height override, so measured
  paragraph height IS `line_count × font_size × line_height` **by construction**.
  Shipped headline = 80pt at `line_height 1.0` → measured 160pt for 2 lines,
  while the natural Latin line box (~1.2em) needs ~192pt. **32pt of spill into a
  24pt gap.** `LUMV0903` cannot fire because the measured height shrank with the
  box; `render_bounds` is `layout_bounds` verbatim (`layout.rs::render_bounds_for`)
  so containment cannot see it either. The engine is blind to this class **by
  design**, not by omission.

## What shipped

1. **`0bbb41a5c` — TTFP.** Prompt obligations against each measured cause: author
   gets ONE reading response and may not re-read (capability skills demoted to
   background, format skill still required); FIRST compile must be the whole
   design, with a worked example of the warm-up mistake; step 4 renamed to
   "RENDER AS SOON AS PREFLIGHT IS CLEAN" and forbids inspect/measure/polish/
   recompile **by name**, because those are what the run actually did.
   Orchestrator gains GET TO THE AUTHOR FAST + the no-search rule. No model or
   reasoning changes (config decision, out of scope).
2. **`2fbdef124` — budget headroom.** `RunBudget.remaining()` /
   `.status_line()`; floors `REPAIR_ROUND_MIN_CALLS=12` /
   `REPAIR_ROUND_MIN_SECONDS=240` derived from this run's own trace (~16 calls ×
   ~17s mean; arithmetic is in the constant's comment). The line rides the
   **orchestrator's** `render_preview` only — its step-5 verification render IS
   the round boundary; the author's instance is excluded for the same reason it
   does not checkpoint. Prompt gains DO NOT OPEN A ROUND YOU CANNOT FINISH.
   **R4 hard ceilings untouched.**
3. **`b477782b1` — collision advisory.** New `lumen_agent/text_clearance.py`:
   computes the spill from geometry preflight already returns and reports it when
   it exceeds the clearance below. Against the real v73 scene it emits **exactly
   one finding (headline vs support, 32pt vs 24pt) and is silent on every other
   node**. Flag-gated onto the preflight payload as `text_collisions`; advisory
   only (never sets `has_errors`, never edits a scene, cannot fail a preflight).
   Plus the eyes half: author LOOK step + pilot skill self-audit test 7
   `no-collisions`, both explaining the multiplier model so the author does not
   try to score it from `inspect`.

## What was rejected, and why

- **A general sibling-overlap AABB sweep.** Would have caught this defect zero
  times (proven by pixel measurement above), and would false-positive on text
  over a photo and a badge over a card corner — the two most common intentional
  overlays in the craft. Shipping it as "the fix" would have been theatre.
  Restricted to text-versus-text instead, which is essentially never intentional.
- **A bare "line_height is tight" warning.** Tight leading on display type is
  good typography. The defect is tight leading with nowhere for the spill to go,
  so clearance is half of every verdict.
- **Any Rust change.** Would have pulled in crate tests + helper rebuild + wasm
  handshake (AGENTS.md §1/§3) for a slice that did not need it.
- **Model / reasoning-effort changes.** 7 calls exceeded 30s and per-call latency
  is now the dominant cost, but that is a config decision, not this slice's.

## Tests

`uv sync --frozen` at repo root, then from the repo root:

```
PYTHONPATH=.:subsystems/clue-design/apps/agent_runtime \
  .venv/bin/python -m pytest subsystems/clue-design/apps/agent_runtime/tests
```

**785 passed, 3 skipped** (baseline 760 + 25 new). Green at each of the three
commits. Full design suite NOT run (>1h, per the standing rule). No Rust touched,
so no crate tests / helper rebuild / wasm handshake were required.
`apps/api/tests/test_scene_turn_persist.py` collects clean (32 items); not
executed (needs a live DB, and every change here is flag-gated or additive).

One pin moved deliberately: `test_flag_on_author_prompt_makes_looking_mandatory`
now anchors on `4. RENDER AS SOON AS PREFLIGHT IS CLEAN.`

Flag-off identity is untouched and still pinned by the existing §0 tests plus
`test_flag_off_leaves_preflight_byte_identical` (exact payload key set) and the
new `test_flag_off_render_carries_no_budget_line`.

## Residuals / follow-ups

1. **Engine lint for ink-beyond-box — unowned, the durable fix.** Belongs in
   `validate_text_nodes` (`lumen-core/src/layout.rs:1051-1233`, `LUMV09xx` has
   free numbers after 0907). Blocked on real ascent/descent: `TextMeasureOutput`
   does not carry font metrics out to Python today, and the measurer's height
   override is what creates the blind spot in the first place. Until then the
   Python advisory assumes `NATURAL_LINE_RATIO = 1.2` and will miss a face whose
   metrics differ — which is exactly why the eyes half shipped alongside it.
2. **The founder-reported "overlap" was never reproduced as a box overlap in the
   harness's own renders.** It was reported against editor v73. The harness
   renders with Inter fallback (`LUMS0100` fired on every text node — `sohne-var`
   is not loaded); the browser wasm may resolve a different face with different
   metrics, which would turn the latent 32pt under-report into a visible
   collision there but not here. **Unverified.** If it recurs, compare the
   editor's resolved face against the headless one before touching the geometry.
3. **Per-call latency is now the dominant cost** (7 calls >30s; author mean
   19.9s). TTFP work can only go so far against that. Next lever is a config
   decision (model / reasoning effort), deliberately not taken here.
4. The `REPAIR_ROUND_MIN_*` floors are calibrated from a single run. Re-derive
   after the next acceptance run rather than treating them as settled.
5. The advisory only inspects **siblings**. A collision between nodes in
   different subtrees (two absolutely-placed groups) is not covered.
