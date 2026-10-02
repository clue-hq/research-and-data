# Freeze Bake Fill Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A freeze-on-grab (ruling C-9) or convert-to-free never moves or resizes any node: every dimension the Stack solve resolved is baked to what it resolved, and Free-mode `fill` means the same thing as Stack-mode `fill` (the padded content box).

**Architecture:** Two engine changes in `lumen-core` and their tests. (1) `editing.rs`'s bake helpers stop exempting containers' `fill` and bake a text child's `hug` width; the text `hug` height and `token` dims keep their meaning. (2) `layout.rs`'s Free-container manual path hands children the container's padded content box as the size `fill` resolves against. The vendored wasm and the release helper binary are rebuilt; the platform frontend's wasm-level freeze tests gain the three real ads as fixtures and the canvas logs a loud diagnostic if a freeze ever moves a box.

**Tech Stack:** Rust (lumen-core, taffy), wasm-pack (lumen-wasm), Python (fixture recovery script over `lumen_api.core.CoreClient`), TypeScript / vitest (`apps/frontend` wasm artifact tests).

**Spec:** the design and exception inventory agreed in chat on 2026-09-20 (recorded in `_memory/2026-09-19-multi-artifact-design-legs.md`, "live walk findings and rulings"); founder rulings: C-9 stands, items 3 and 4 unchanged, items 1 and 2 fixed for every exception.

## Global Constraints

- **Design Rust gate (memory `design-rust-gate-goldens-and-fmt`):** never `cargo fmt --all`; format only your hunks with `rustfmt --edition 2021 --check <file>`; `cargo test --workspace` in a fresh worktree needs the untracked goldens generated from the BASE commit — this plan's gate is the focused `cargo test -p lumen-core --test freehand_ops` plus the crates the change reaches (`lumen-core` unit + `arrange_ops`, `conformance`, `core_engine`), NOT the full workspace, unless the goldens are already present in this worktree.
- **Design suite is slow (memory `design-suite-too-slow-for-inline-gates`):** never run the >1 h clue-design full suite synchronously; focused files only, one background full run at the end if at all.
- **The vendored wasm is TRACKED** at `subsystems/clue-design/apps/editor/public/wasm/lumen_wasm_bg.wasm` (+ `lumen_wasm.js`); rebuild with `bash subsystems/clue-design/scripts/build_wasm_core.sh` and commit it deliberately as its own commit at the end. The platform frontend copies it on `predev`/`pretest`/`prebuild` via `apps/frontend/scripts/copy-design-vendor.mjs` into the untracked `apps/frontend/public/vendor/wasm`.
- **The helper binary** the design API and fleet workers run is `subsystems/clue-design/target/release/lumen-api-helper` (`LUMEN_CORE_HELPER` in `.env`); it does NOT rebuild on its own — `cargo build -p lumen-api-helper --release` then restart the stack (`./scripts/dev_stack_san_salvador.sh restart-api` and `restart-workers`) before any live check.
- **Zero motion is the invariant:** every test asserts `solved(before) == solved(after)` for EVERY node of the scene, and that applying the batch's inverses restores the pre-edit scene byte-identically (the existing `freehand_ops` pattern).
- **No new document JSON shape, no new operation kind, no env key.** `Dimension`, `SizeSpec`, `NodePatch`, the structured-edit wire kinds are untouched.
- **Commits:** local only, never push; no AI attribution trailers; one commit per task; stage by explicit path (never `git add -A` — untracked goldens and the wasm copy must not slip in).
- **Tests that spend money are forbidden**; nothing here calls a provider. DB access only in Task 4's fixture script (reads only).
- **Founder review of behaviour:** the one judgement call (bake text `hug` WIDTH to `fixed`) was approved in chat; keep text `hug` HEIGHT hug.

---

## File structure

**Engine (`subsystems/clue-design/crates/lumen-core/`)**
- `src/editing.rs` — MODIFY: `baked_container_size` (bake `fill` too), `bake_dimension_for_child` (text: bake width, keep hug height). Both `build_freeze_layout` (2142) and `build_convert_container_layout` (1967) flow through them.
- `src/layout.rs` — MODIFY: the Free-container manual path (`layout_node_at`, ~lines 196–215) passes the padded content box to children.
- `tests/freehand_ops.rs` — MODIFY: new fixtures and tests for the exception inventory.
- `tests/freeze_real_ads.rs` — CREATE: whole-document zero-motion over the three real ads.
- `fixtures/scenes/freeze/*.json` — CREATE: the three pre-freeze ad scenes.

**Fixture recovery (`scripts/`)**
- `scripts/design_prefreeze_scene.py` — CREATE: rebuilds a document's pre-freeze scene from the DB by applying the stored inverse batches in reverse through the helper.

**Frontend (`apps/frontend/src/features/design-editor/`)**
- `adapter/scene-gestures.ts` — MODIFY: `freezeMotionReport(before, after)` pure helper.
- `components/scene-artifact-canvas.tsx` — MODIFY: `freezeLayoutForPress` logs the report.
- `engine/scene/__tests__/wasmEngine.artifact.test.ts` — MODIFY: real-ad zero-motion tests.
- `engine/scene/__tests__/__fixtures__/freeze/*.json` — CREATE: copies of the three ad fixtures.

---

### Task 1: Bake every solved dimension — containers' `fill`, text `hug` width

**Files:**
- Modify: `subsystems/clue-design/crates/lumen-core/src/editing.rs:2112-2130` (`baked_container_size`), `:2226-2231` (`bake_dimension_for_child`)
- Test: `subsystems/clue-design/crates/lumen-core/tests/freehand_ops.rs`

**Interfaces:**
- Produces (semantics, signatures unchanged):
  - `baked_container_size(node, container_bounds) -> FieldPatch<SizeSpec>`: `hug` and `fill` → `Fixed(solved)`; `fixed`, `token` unchanged.
  - `bake_dimension_for_child(dimension, solved, is_text, axis) -> Dimension`: non-text → `bake_dimension` (hug/fill → fixed); text WIDTH: hug/fill → `Fixed(solved)`; text HEIGHT: `hug` stays `Hug`, `fill` → `Fixed(solved)`. Add an `axis: Axis` parameter (the enum already exists in `layout.rs`; if it is private, add a two-variant `BakeAxis { Width, Height }` local to `editing.rs`).

- [ ] **Step 1: Write the failing tests** (append to `tests/freehand_ops.rs`, reusing `scene_with_page`, `auto_layout`, `rect`, `insert`, `apply_layout`, `solved`, `scene_json`; add a `text(id, content, width: Dimension, height: Dimension)` helper modelled on `tests/assets_pipeline.rs::text_node` with `wrap: TextWrap::Wrap`):

```rust
/// The 2026-09-20 defect: a FILL-width container the stack solved as hug (its
/// parent's cross axis was indefinite) kept `fill` through the freeze and then
/// stretched to its Free parent's outer box.
#[test]
fn freeze_layout_bakes_a_fill_containers_solved_width() {
    use lumen_core::build_freeze_layout;
    let mut scene = scene_with_page(1080.0, 1080.0);
    let mut artboard = auto_layout("artboard", 1080.0, 1080.0, 18.0);
    artboard.layout = Some(AutoLayoutProps { gap: 18.0, padding: [48.0, 52.0, 48.0, 52.0], ..AutoLayoutProps::default() });
    insert(&mut scene, ParentRef::Page(PageId::from("page")), artboard);
    let mut products = auto_layout("products", 0.0, 0.0, 10.0);
    products.size = SizeSpec { width: Dimension::Fill { weight: 1.0 }, height: Dimension::Hug };
    insert(&mut scene, ParentRef::Node(NodeId::from("artboard")), products);
    for id in ["row_md", "row_in", "row_dac"] {
        let mut row = auto_layout(id, 0.0, 0.0, 0.0);
        row.size = SizeSpec { width: Dimension::Fill { weight: 1.0 }, height: Dimension::Hug };
        row.layout = Some(AutoLayoutProps { padding: [14.0, 20.0, 14.0, 20.0], ..AutoLayoutProps::default() });
        insert(&mut scene, ParentRef::Node(NodeId::from("products")), row);
        insert(&mut scene, ParentRef::Node(NodeId::from(id)), rect(&format!("{id}_label"), 577.0, 41.0));
    }
    apply_layout(&mut scene);
    let before: Vec<(String, Rect)> = scene.nodes.keys().map(|id| (id.to_string(), solved(&scene, id))).collect();
    assert_eq!(solved(&scene, "row_md").width, 617.0, "fixture sanity: the row hugged its label + padding");
    let batch = build_freeze_layout(&scene).unwrap();
    let mut frozen = scene.clone();
    frozen.apply_operations(batch.operations.clone()).unwrap();
    apply_layout(&mut frozen);
    for (id, rect) in &before { assert_eq!(&solved(&frozen, id), rect, "{id} moved during freeze"); }
    assert_eq!(frozen.nodes[&NodeId::from("row_md")].size.width, Dimension::Fixed(617.0));
    assert_eq!(frozen.nodes[&NodeId::from("products")].size.width, Dimension::Fixed(976.0));
    let mut restored = frozen.clone();
    restored.apply_operations(batch.inverse_operations.clone()).unwrap();
    assert_eq!(scene_json(&restored), scene_json(&scene));
}
```

Then, same shape, one test each (each asserts whole-scene zero motion + byte-identical inverse + the specific baked dimension):

- `freeze_layout_bakes_a_fill_container_under_a_padded_parent_to_the_content_width` — a lone `fill × fixed` container under a padded artboard: baked width == artboard width − left − right padding (976), never 1080.
- `freeze_layout_bakes_weighted_fill_row_children_to_their_shares` — a Row stack 900 wide, gap 0, two container children `fill weight 2` and `fill weight 1`: baked widths 600 and 300.
- `freeze_layout_bakes_main_axis_fill_fallback_to_natural_size` — a fixed-width Row 300 wide holding a `fill`-width container child whose fixed sibling already uses 300: the fallback solved it at natural size; baked width == that solved width (read it from `solved()` rather than hard-coding).
- `freeze_layout_bakes_a_wrapped_hug_width_text_to_its_solved_width` — a Column stack 300 wide with a `hug × hug` text whose content wraps (long sentence, `wrap: Wrap`): after freeze `size.width == Fixed(solved width)` and `size.height == Hug`; re-laying out the frozen scene gives the same line count / height (zero motion proves it).
- `freeze_layout_keeps_a_fill_x_hug_text_hugging_its_height` — the agent's headline shape: width bakes to fixed(solved), height stays hug.
- `freeze_layout_bakes_stretch_aligned_children` — Column stack with `align_x: Stretch` and `hug`-width rect children: baked widths == the stretched solved width.
- `freeze_layout_bakes_a_wrapping_row` — a Row stack with `wrap: true` and five 200-wide children in 500 px: positions on two lines bake unchanged.
- `convert_container_layout_bakes_the_containers_own_fill` — `convert_container_layout(products, Free)` alone (parent stays Stack): products' width bakes to fixed(solved); zero motion; inverse restores `fill`.

Update the existing `convert_to_free_is_zero_motion_and_inverts_byte_identical` / `freeze_layout_bakes_every_stack_zero_motion_and_inverts_byte_identical` only if they asserted a container keeps `fill` (grep `Fill` in their assertions; the `stack_scene` container is Fixed, so they should pass unchanged).

- [ ] **Step 2: Run them to verify they fail**

Run: `cd subsystems/clue-design && cargo test -p lumen-core --test freehand_ops 2>&1 | tail -30`
Expected: the new tests FAIL on the container width assertions (`Fill { weight: 1.0 }` where `Fixed(617.0)` is expected) and on zero motion; existing tests pass.

- [ ] **Step 3: Implement**

```rust
fn baked_container_size(node: &Node, container_bounds: &Rect) -> FieldPatch<SizeSpec> {
    // 2026-09-20: a container leaving the solve keeps EXACTLY the extents the solve gave
    // it — `fill` included. The former exemption ("a Free container's Fill still tracks its
    // parent") was wrong twice over: the Stack solve treats a nested cross-axis `fill` as
    // hug (children are built with no definite parent size), and Free mode resolves `fill`
    // against the parent's OUTER box — so a kept `fill` stretched pills to the artboard
    // edge on the first grab. Token dims stay (the accepted contraction, pinned below).
    let bake = |dimension: &Dimension, solved: f64| match dimension {
        Dimension::Hug | Dimension::Fill { .. } => Dimension::Fixed(solved),
        other => other.clone(),
    };
    …unchanged tail…
}

fn bake_dimension_for_child(dimension: &Dimension, solved: f64, is_text: bool, axis: BakeAxis) -> Dimension {
    // K1 rider, narrowed to HEIGHT: a text child keeps a Hug height so it re-measures at
    // the width it is painted at. Its WIDTH bakes: a hug-width text the stack wrapped at
    // the container width would otherwise measure unbounded in Free mode and unwrap
    // across the artboard (2026-09-20).
    if is_text && axis == BakeAxis::Height && matches!(dimension, Dimension::Hug) {
        return Dimension::Hug;
    }
    bake_dimension(dimension, solved)
}
```

Thread `BakeAxis::Width` / `::Height` at the two call sites in `free_container_operations` (2080–2081). Update the docstrings of `build_freeze_layout` and the K1 comment block accordingly. `rustfmt --edition 2021 --check src/editing.rs` clean (format only your hunks).

- [ ] **Step 4: Run the tests**

Run: `cd subsystems/clue-design && cargo test -p lumen-core --test freehand_ops && cargo test -p lumen-core --lib 2>&1 | tail -5`
Expected: PASS, including the existing token-dimension, padded-hug, locked/free-skip, empty-padded tests.

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/crates/lumen-core/src/editing.rs subsystems/clue-design/crates/lumen-core/tests/freehand_ops.rs
git commit -m "fix(lumen-core): freeze bakes a container's fill and a text child's hug width to their solved extents"
```

---

### Task 2: Free-mode `fill` resolves against the padded content box

**Files:**
- Modify: `subsystems/clue-design/crates/lumen-core/src/layout.rs` (`layout_node_at`, the manual path ~lines 196–215; `resolve_manual_size` ~686)
- Test: `subsystems/clue-design/crates/lumen-core/tests/freehand_ops.rs` (append), `tests/core_engine.rs` if it pins Free-mode sizing (grep `layout_mode` there first)

**Interfaces:**
- Produces: in the manual (Free) path, the size handed to each child for `fill` resolution is the container's content box: `outer.width − padding[1] − padding[3]`, `outer.height − padding[0] − padding[2]`, clamped at 0. Child ORIGIN stays `origin + child.transform` relative to the outer box (positions are the author's, and the freeze baked them against the outer origin).

- [ ] **Step 1: Write the failing test**

```rust
/// Item 2 (2026-09-20): a `fill` child of a FREE container is the container's padded
/// content box, exactly as it would be in Stack mode — never the outer box.
#[test]
fn free_container_fill_children_resolve_against_the_content_box() {
    let mut scene = scene_with_page(1080.0, 1080.0);
    let mut artboard = auto_layout("artboard", 1080.0, 1080.0, 0.0);
    artboard.layout = Some(AutoLayoutProps {
        padding: [48.0, 52.0, 48.0, 52.0],
        layout_mode: LayoutMode::Free,
        ..AutoLayoutProps::default()
    });
    insert(&mut scene, ParentRef::Page(PageId::from("page")), artboard);
    let mut band = rect("band", 0.0, 60.0);
    band.size = SizeSpec { width: Dimension::Fill { weight: 1.0 }, height: Dimension::Fixed(60.0) };
    band.transform.x = 52.0;
    band.transform.y = 48.0;
    insert(&mut scene, ParentRef::Node(NodeId::from("artboard")), band);
    apply_layout(&mut scene);
    let solved_band = solved(&scene, "band");
    assert_eq!(solved_band.width, 976.0, "fill = outer 1080 − 52 − 52");
    assert_eq!((solved_band.x, solved_band.y), (52.0, 48.0), "position is the author's transform, outer-relative");
}
```

Also a stack-vs-free parity test: build the Task 1 pills fixture in Stack mode, freeze it (Task 1), then ADD a new `fill × fixed(60)` rect child to the frozen `artboard` at transform (52, 900): its solved width must be 976, the same as a `fill` child would get from the Stack solve.

- [ ] **Step 2: Run to verify it fails** — Expected: `assert_eq!(1080.0, 976.0)` fails.

- [ ] **Step 3: Implement** — in `layout_node_at`'s manual branch, after `let size = …resolve_manual_size…`, compute

```rust
let padding = node.layout.as_ref().map(|layout| layout.padding).unwrap_or([0.0; 4]);
let content = Size2 {
    width: (size.width - padding[1] - padding[3]).max(0.0),
    height: (size.height - padding[0] - padding[2]).max(0.0),
};
```

and pass `content` (not `size`) as the `parent_size` of every child's `layout_node_at`. Only auto-layout nodes carry `layout`, so a plain group's padding is `[0; 4]` and nothing changes for it. Document the rule at the site: "Free mode: fill = the padded content box, positions = the author's transform relative to the outer origin (the freeze bakes them that way)".

- [ ] **Step 4: Run** `cargo test -p lumen-core --test freehand_ops --test core_engine --test conformance --test arrange_ops 2>&1 | tail -8` — Expected: PASS. If a conformance golden pins the old outer-box behaviour for a Free container with a fill child, that golden was pinning the defect: update it in the same commit and say so in the report.

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/crates/lumen-core/src/layout.rs subsystems/clue-design/crates/lumen-core/tests/freehand_ops.rs
git commit -m "fix(lumen-core): a Free container's fill children resolve against its padded content box"
```

---

### Task 3: Recover the three real ads' pre-freeze scenes as fixtures

**Files:**
- Create: `scripts/design_prefreeze_scene.py`
- Create: `subsystems/clue-design/crates/lumen-core/fixtures/scenes/freeze/capital_digestive_care_ad.json`, `austin_gastroenterology_ad.json`, `mngi_digestive_health_ad.json`
- Create: `apps/frontend/src/features/design-editor/engine/scene/__tests__/__fixtures__/freeze/` (the same three files, copied)

**Interfaces:**
- Produces: `python scripts/design_prefreeze_scene.py <document_id> --before-seq <seq> --out <path>` — reads `design_document.current_scene_json` and every `design_edit_envelope` row of the document with `seq >= before_seq`, applies each row's `inverse_operations_json` in DESCENDING `seq` order through `lumen_api.core.CoreClient().apply_operations(scene, operations)`, and writes the resulting scene JSON. Prints the revision it landed on. Read-only against the DB.

- [ ] **Step 1: Write the script** (uses `set -a; source .env; set +a` for `CLUE_DATABASE_URL` and `LUMEN_CORE_HELPER`; `clue_db.db_lifespan`; `from lumen_api.core import CoreClient`; the helper returns `{"scene": …}` — check `apply_operations`' return shape in `lumen_api/core.py:68` and `_run`).

- [ ] **Step 2: Recover the three scenes** — the freeze batches are the first `actor_kind='editor'` rows: Capital `doc_9f772c46411751fba2fa59bb5f86a69e` seq 3 (base 81), Austin `doc_a2397f0963565248bcff683d5ab67220` seq 3 (base 51), MNGI `doc_48bc3377ff2a5d4aa106e7362b000276` seq 3 (base 94). Run with `--before-seq 3` for each; assert in the script output that every `auto_layout` node of the result has `layout_mode` absent or `stack` and no node carries a `computed` block (strip `computed` if present — the fixture is authored state). Sanity-check the Capital result: `row_md` has `size.width == {"kind":"fill",…}`.

- [ ] **Step 3: Strip what a fixture must not carry** — the scene's `meta.brand_kit` reference may name a workspace kit; keep it (the tests lay out without brand resolution) but confirm `lumen_core::layout_scene` on the fixture emits no error-level diagnostic (warnings about unresolved tokens are fine). Remove any `assets` entries whose bytes the tests would need (image nodes lay out by size, not bytes).

- [ ] **Step 4: Commit**

```bash
git add scripts/design_prefreeze_scene.py subsystems/clue-design/crates/lumen-core/fixtures/scenes/freeze apps/frontend/src/features/design-editor/engine/scene/__tests__/__fixtures__/freeze
git commit -m "test(lumen-core): the three 2026-09-20 ads as pre-freeze fixtures, recovered from their inverse batches"
```

---

### Task 4: Whole-document zero motion over the real ads (Rust)

**Files:**
- Create: `subsystems/clue-design/crates/lumen-core/tests/freeze_real_ads.rs`

- [ ] **Step 1: Write the test**

```rust
//! The test that would have caught 2026-09-20: freeze each real ad and assert NOTHING moves.
use lumen_core::{build_freeze_layout, layout_operations, layout_scene, LayoutOptions, Scene};

fn load(name: &str) -> Scene {
    let path = format!("{}/fixtures/scenes/freeze/{name}.json", env!("CARGO_MANIFEST_DIR"));
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn solved_boxes(scene: &Scene) -> Vec<(String, (f64, f64, f64, f64))> {
    let result = layout_scene(scene, LayoutOptions::default());
    let mut boxes: Vec<_> = result.geometry.iter()
        .map(|(id, g)| (id.to_string(), (g.layout_bounds.x, g.layout_bounds.y, g.layout_bounds.width, g.layout_bounds.height)))
        .collect();
    boxes.sort();
    boxes
}

fn freeze_is_zero_motion(name: &str) {
    let mut scene = load(name);
    scene.apply_operations(layout_operations(&scene, LayoutOptions::default())).unwrap();
    let before = solved_boxes(&scene);
    let batch = build_freeze_layout(&scene).unwrap();
    let mut frozen = scene.clone();
    frozen.apply_operations(batch.operations.clone()).unwrap();
    assert_eq!(solved_boxes(&frozen), before, "{name}: a node moved or resized during freeze");
    let mut restored = frozen.clone();
    restored.apply_operations(batch.inverse_operations.clone()).unwrap();
    assert_eq!(serde_json::to_value(&restored).unwrap(), serde_json::to_value(&scene).unwrap(), "{name}: inverse must restore the scene byte-identically");
    // Every container is Free afterwards and no dimension is still `fill` or a non-text `hug`.
    for (id, node) in &frozen.nodes { /* assert per the Task 1 rules; text height may be hug */ }
}

#[test] fn capital_digestive_care_ad_freezes_zero_motion() { freeze_is_zero_motion("capital_digestive_care_ad"); }
#[test] fn austin_gastroenterology_ad_freezes_zero_motion() { freeze_is_zero_motion("austin_gastroenterology_ad"); }
#[test] fn mngi_digestive_health_ad_freezes_zero_motion() { freeze_is_zero_motion("mngi_digestive_health_ad"); }
```

Fill the per-node assertion loop per Task 1's table. Compare boxes with an exact equality first; if the heuristic measurer makes text heights differ by float noise between the two solves, compare with a 1e-6 tolerance and say so in a comment.

- [ ] **Step 2: Run it against the PRE-Task-1 engine to prove it catches the defect** — `git stash push -u -m freeze-parity-proof` is FORBIDDEN (shared stash); instead run the test with Task 1's `baked_container_size` change temporarily reverted in a scratch copy is also overkill — simply record in the report the assertion message the test produces when `bake` keeps `Fill` (comment the two-line change out locally, run, restore, never commit the revert).

- [ ] **Step 3: Run** `cargo test -p lumen-core --test freeze_real_ads` — Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add subsystems/clue-design/crates/lumen-core/tests/freeze_real_ads.rs
git commit -m "test(lumen-core): freezing the three real ads moves nothing"
```

---

### Task 5: Rebuild the wasm and the helper; wasm-level tests over the real ads; the runtime diagnostic

**Files:**
- Modify: `subsystems/clue-design/apps/editor/public/wasm/lumen_wasm_bg.wasm`, `lumen_wasm.js` (rebuilt)
- Modify: `apps/frontend/src/features/design-editor/engine/scene/__tests__/wasmEngine.artifact.test.ts` (append), `apps/frontend/src/features/design-editor/adapter/scene-gestures.ts` (`freezeMotionReport`), `apps/frontend/src/features/design-editor/adapter/scene-gestures.test.ts` (or the nearest existing test file for that module), `apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx:1387-1420`

**Interfaces:**
- Produces: `freezeMotionReport(before: Scene, after: Scene): { moved: Array<{ id: string; before: Rect; after: Rect }> }` comparing `node.computed.layout_bounds` per node id (nodes absent on either side are ignored); `freezeLayoutForPress` calls it with `controls.sceneSnapshot()` and `outcome.scene` and, when `moved.length > 0`, logs `console.error("[freeze] a freeze moved nodes; this is an engine defect", moved)` — a loud signal, never a refusal (C-9 stands).

- [ ] **Step 1: Rebuild the engine artifacts** — `bash subsystems/clue-design/scripts/build_wasm_core.sh` (prints the size budget line; must stay under 3 MB gzipped) and `cd subsystems/clue-design && cargo build -p lumen-api-helper --release`. Then `cd apps/frontend && node scripts/copy-design-vendor.mjs` so the tests load the rebuilt wasm.

- [ ] **Step 2: Write the failing frontend tests** — in `wasmEngine.artifact.test.ts`, beside the existing `freeze_layout` cases: load each `__fixtures__/freeze/*.json`, run `engine.applyStructuredEdit({ kind: "freeze_layout" })`, and assert `solvedBoxes(after)` equals `solvedBoxes(before)` and `outcome.accepted`. Add a unit test for `freezeMotionReport` with two hand-built scenes (one moved node, none moved).

- [ ] **Step 3: Implement** the helper and the call site (keep `freezeLayoutForPress`'s flow byte-identical otherwise).

- [ ] **Step 4: Run** — `cd apps/frontend && npm test` (the `pretest` copies the vendor; wasm suites run when the artifact exists), `npm run lint`, `npm run build`. Then restart the lane's stack (`./scripts/dev_stack_san_salvador.sh restart-api` and `restart-workers`) so the design API and workers run the rebuilt helper.

- [ ] **Step 5: Commit in two commits** — the frontend change first, then the rebuilt wasm alone:

```bash
git add apps/frontend/src/features/design-editor/adapter/scene-gestures.ts apps/frontend/src/features/design-editor/adapter/*.test.ts apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx apps/frontend/src/features/design-editor/engine/scene/__tests__/wasmEngine.artifact.test.ts
git commit -m "feat(design-editor): freeze zero-motion report on the canvas; the real ads pinned at the wasm seam"
git add subsystems/clue-design/apps/editor/public/wasm/lumen_wasm_bg.wasm subsystems/clue-design/apps/editor/public/wasm/lumen_wasm.js
git commit -m "chore(lumen-wasm): rebuild the browser engine for the freeze-bake fill parity"
```

---

### Task 6: Records and the live proof checklist

- [ ] **Step 1: Records** — a CLAUDE.md backlog bullet under the design entries (`[design×freeze] Freeze-bake fill parity shipped <date> …` naming the two engine rules, the fixtures, the diagnostic, and the still-open rulings 3 and 4); `_memory/2026-09-20-freeze-bake-fill-parity.md` with commits, gates and the owed live check; `subsystems/clue-design/docs/phase-d-targeted-editing-repair-semantics.md` (or wherever C-9 is documented — grep `C-9`) gains two lines on the bake rules.
- [ ] **Step 2: Commit** the records.
- [ ] **Step 3: Live proof, founder-triggered (no spend, but the founder drives):** on a NEW ad generated after the helper restart, in Edit mode click a pill inside a fill-width row: the pill must not move or stretch; the console shows no `[freeze]` error; undo restores `fill` on the row; the inspector shows the row's width as the baked fixed value.

## Self-review

- **Spec coverage:** item 1 → Task 1 (containers' fill, text hug width, weighted fill, fallback, stretch, wrap, convert-of-one) + Task 4 (real ads); item 2 → Task 2; the "every exception" demand → the inventory rows 1–11 all have a named test (token/locked/absolute/rotated/empty-padded/nested-free are the kept existing tests, re-run in Task 1 Step 4); rulings 3 and 4 untouched (no gesture or scope change anywhere).
- **Placeholders:** Task 4's per-node loop body is described by Task 1's table; the implementer writes it from that table. Task 3's script return shape is to be read from `core.py:68`. Nothing says TBD.
- **Type consistency:** `BakeAxis` is introduced in Task 1 and used only there; `solved_boxes`/`freeze_is_zero_motion` are local to Task 4; `freezeMotionReport` is defined and consumed in Task 5.
