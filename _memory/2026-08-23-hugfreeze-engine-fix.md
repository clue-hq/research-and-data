# 2026-08-23 — HUG-FREEZE: the layout freeze bakes the container's own hug dims (close-out)

Branch `integration/frontend-design-part-iv-v4`, commits `dab03753` (Rust fix + red-first tests) +
`885eadb5` (wasm-layer pin + comment) + `23d94d20` (review round), on the C-9 close-out base
`66e4878b`. All local. **Founder-authorized engine change** (the `crates/lumen-core` fence lifted
for this defect) and **controller-implemented** (founder override: "handle the bugs yourself");
the verification regime was unchanged — independent Opus review (which re-ran red-first in a
throwaway worktree and constructed the token counter-shape), one fix round, scoped re-review
(which mutation-proved the double-write inverse by breaking `invert_operations` and watching the
exact test fail).

## The defect and the fix
`build_freeze_layout`/`build_convert_container_layout` converted a Stack container to Free
without touching the container's OWN size, and Free-mode hug natural-sizes from child extents
WITHOUT padding (`layout.rs` `natural_size`) — so a padded hug container visibly contracted by
its far-edge padding on a human's first grab (the Story ad's card: 258→218 = `padding[2]`), and
an EMPTY padded hug container collapsed to 0×0. Fix: `free_container_operations` returns the
container's solved bounds; `baked_container_size` bakes the container's own `Hug` dims to
`Fixed(solved)` at BOTH call sites. Fixed keeps its value; **Fill deliberately unbaked** (a Free
container's Fill still tracks its parent — it never moved); **Token deliberately unbaked** (see
the founder item). Undo restores Hug via the existing inverse pre-image machinery — proven
byte-identical including the nested double-write case (a hug container child is baked by its
parent's pass AND its own; both land on the same solved extent).

## Tested invariant (the robustness ask)
"Freeze is pixel-zero-motion" is now a red-first property test at TWO layers: lumen-core
`freehand_ops` (padded-hug Story shape incl. a nested hug double-write, 318/226/60 solve
arithmetic pinned; hug-width + empty-container 348×184/88×80; the convert call site; 18/18) and
the REAL vendored wasm (`wasmEngine.artifact.test.ts` padded-hug zero-motion + inverse-restores-
Hug). Browser-proven on a pristine re-seeded Story doc: the panel-commit freeze baked height
`Fixed 258` (the full padded extent; the old engine contracted to 218) with the card visually
identical (screenshots /tmp/hugfix-before/after.png at proof time).

## ★ FOUNDER ITEM — the recorded token trade (ratify or flip)
An UNRESOLVED `Dimension::Token` on a container still contracts across the freeze (review-proven
constructible and agent-authorable via the DSL; 226→186 on the fixture). Held at hug-only
because `bake_dimension`'s standing rule (baking a token severs brand governance) and because
the brand pass rewrites every RESOLVABLE dimension token to Fixed before layout — the shape
exists only in already-LUMV-warned broken documents. The trade is PINNED test-first
(`freeze_layout_keeps_a_token_dim_and_accepts_its_contraction`: the binding survives AND the
motion equals the dropped padding) so it cannot drift silently. **Founder: ratify hug-only, or
rule that the freeze bakes container token dims too — then flip that test's assertions
deliberately.**

## Environment facts (operational)
- The engine stamp is a CONTENT hash of `lumen-core` — even comment edits move it. After any
  `crates/lumen-core` change: wasm rebuild (the frontend's `pretest` preflight auto-rebuilds on
  drift), `cargo build -p lumen-api-helper --release`, `verify_handshake.mjs`, AND restart the
  design API (its `/build-info` is process-cached). Current stamp both sides: `7810bea23027`.
- :8010 now runs COLOMBO's helper via `/tmp/hugfreeze-relaunch-8010.sh` (the istanbul relauncher
  with `LUMEN_CORE_HELPER` repointed) — **the istanbul helper binary is stale**; any session that
  relaunches :8010 from istanbul's script serves the OLD engine.
- Pre-existing checkout reds, A/B-proven unrelated: lumen-core `visual_regression` + lumen-skia
  `raster_golden` (untracked-and-absent local baselines, compile-time include failures); design
  api pytest ×2 (`test_custom_component_runtime` — the CC compiler's `typescript` package is not
  installed here). Design agent_runtime pytest 610/0; api pytest otherwise green.
- Story doc re-seeded pristine (`seed_ad210_story_doc.py --recreate`) for founder testing; any
  open editor tab needs ⌘⇧R after the engine swaps.
