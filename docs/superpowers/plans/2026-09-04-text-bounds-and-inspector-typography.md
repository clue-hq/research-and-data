# Text Bounds and Inspector Typography (Editor Quality Plan 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A text node is selected, outlined and hit-tested by the glyphs it paints, not by the layout box the author typed; new text hugs its copy by default; item G (inspector typography rows) produces a founder preview and nothing else.

**Architecture:** The layout engine already measures every text node against its solved box (`validate_text_nodes`) and throws the line boxes away. Plan 4 keeps them: `ComputedGeometry` gains `text_lines` (page-space painted line boxes, placed by `align`/`valign` exactly as the two painters place glyphs), the core hit test uses them for text, and the editor's measure-then-inject bridge grows a second pass keyed on the solved boxes so the wasm engine's lines are CanvasKit's lines, not the heuristic's. The platform canvas outlines the union of those lines and keeps a dashed frame on the layout box when the two differ. The DSL defaults an unsized text element to hug, the author prompt and the LinkedIn ad skill say "text height is hug", and a "Fit to text" button flips an existing fixed height to hug in one write. Item G ends at a rendered preview behind the founder gate.

**Tech Stack:** Rust (lumen-core, lumen-wasm; `cargo test`), TypeScript (Next.js frontend; `node --test` via `npm test`, CanvasKit measurement tests skip without the system font), Python 3.12 + pytest (agent runtime prompts). No new dependencies.

**Spec:** `docs/superpowers/plans/2026-09-04-editor-quality-roadmap.md` — Plan 4, items F and G. Plan 3's memo `_memory/2026-09-04-plan3-selection-ladder.md` records the Apollo CTA case that belongs here.

## Global Constraints

- Every subagent is an Opus implementer; the controller reviews every diff and re-runs every test first-hand before the next task starts.
- Commit locally after each task; never push; no AI attribution in commit messages; never `git stash`.
- Rust gate for a change under `crates/` (design AGENTS.md §3): `cargo test --workspace` → `cargo build -p lumen-api-helper --release` → wasm rebuild + handshake → `pytest apps/agent_runtime/tests` → `pytest apps/api/tests`. Per-task steps run the narrow crate tests; Task 8 runs the full gate. The API test suite runs against the throwaway DB `clue_plan1_test`, never the shared dev DSN, and never while a live design turn is wanted (the suite is slow: run it in the background).
- Python tests run from `subsystems/clue-design`: `set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest <file> -q`.
- Frontend tests run from `apps/frontend`: `npx tsx --test <file>` for one file, `npm test` for all; `npm run lint` must stay clean (the React Compiler lint refuses ref reads in JSX and derived values between hooks — keep new values below every hook).
- Rust paths are under `subsystems/clue-design/crates/`; frontend paths under `apps/frontend/src/features/`. Prose in code comments follows the file's existing voice (why, then what).
- **Never run `cargo fmt --all`** (found by Task 1): the installed rustfmt reformats 73 pre-existing files across 8 crates. Write new Rust in rustfmt's form (check with `rustfmt --check <file>` and read only the hunks that touch your lines) and stage files by explicit path — never `git add crates`. `cargo test --workspace` regenerates the untracked visual-regression baseline PNGs under `crates/lumen-core/fixtures/visual_regression/baselines/` (deliberately untracked by `0f63d3080`); they must never be staged.
- No silent migration: an authored fixed text size is never rewritten by the engine or the DSL. Only the *default* for an unsized text element changes, and "Fit to text" is a user action.
- The founder preview gate on item G stands: no inspector control for line height, letter spacing, max lines/wrap or resize mode lands in this plan. Task 9 produces the preview only.
- Dummy frontend is presentation truth: the only new inspector UI in this plan is the "Fit to text" button, which reuses the panel's existing wide button style; no new visual vocabulary.

## Rulings (controller, 2026-09-04)

- **R1 — Where the lines live.** `ComputedGeometry.text_lines: Vec<Rect>`, page-space and unrotated (the frame `layout_bounds` is in), one rect per measured line, empty for every non-text node. Serialized only when non-empty (`skip_serializing_if`), deserialized with a default, so every existing scene JSON and every non-text node stays byte-identical.
- **R2 — Placement contract.** Both painters (`lumen-skia::paint_text_paragraph`, the editor's `paintTextParagraph`) resolve a line's horizontal placement to `(box_width − line_width) × f(align)` with `f` = 0 for left and justify, 0.5 for center, 1 for right, and shift the whole stack by `valign_offset(box_height, content_height, valign)`. `painted_text_lines` applies exactly that to the measurer's left-aligned, paragraph-relative line boxes. Justified lines are placed like left; the painters stretch them, and the pick slop covers the difference.
- **R3 — Hit test.** A text node with at least one positive-area painted line hits when the point is inside any line expanded by `TEXT_LINE_PICK_SLOP = 2.0` scene units. A text node with no lines (an engine that predates them, an empty string, a collapsed box) keeps today's box test. The hit-stack contract (bottom-to-top, clip semantics, pinned pass) is unchanged.
- **R4 — Editor lines are CanvasKit's.** The measure-then-inject bridge sends, per text node the engine has laid out, records keyed on the solved box: one keyed `(max_width, max_height)` — the key `validate_text_nodes` measures with — and one keyed `(max_width)` alone — the key taffy's measure closure uses for a hug-height node — both carrying the same CanvasKit line boxes and extent measured at the box width. `ProvidedTextMeasurer` substitutes the lines when a record carries them. The text measurement signature includes each text node's solved size so a resized box re-measures; the injection is deterministic, so the effect reaches a fixed point after the boxes stop changing. **Amendment (controller review of Task 5):** the line pass changes boxes itself — the taffy-keyed record gives a wrapped hug box CanvasKit's height, so the validate-keyed record from the same pass names the old height and that node's lines miss. The injection therefore iterates locally: after the unconstrained pass, re-run the line pass until the scene's text signature stops changing, at most four rounds (`injectSkiaMeasurements`, a pure function over an engine-shaped object, tested with scripted scenes and no CanvasKit). The effect's outer re-run then finds nothing to change.
- **R5 — Outline.** For a text node with painted lines the selection outline (and Plan 3's hover outline) is the union of the lines. When the layout box differs from that union by more than 0.5 scene units on any edge, a dashed frame is drawn on the layout box and the resize handles sit on the frame (the box is what a resize changes). Rotation pivots on the frame's origin when there is one. Gesture geometry (`selectionBox.box`, drag and resize math) stays the layout box.
- **R6 — Fit to text.** One write: the height flips to hug, the width is untouched (a fixed width is the wrap width the author chose). The button is enabled while the height mode is not Hug.
- **R7 — DSL default.** A text element with no `s(...)` lowers to `s(hug,hug)` instead of `Node::new`'s 0×0 fixed box (which collapsed with LUMV0901). An explicit `s(...)` still wins.
- **R8 — Hug height is measured at the wrap width (found by the Task 8 live proof).** Outside a taffy solve (`resolve_manual_size`: page children, frame children, children of a frozen Stack), a text node's hug height came from `natural_size`, which measures with NO width bound — so a fixed-width wrapped headline hugged its unwrapped line count (Apollo's "Pipeline that / shows up on time." hugged 2 lines while the painters wrap it to 3 at 503 wide; the box was 142 tall under 213 of glyphs). Inside a taffy solve the closure measured at the container's available width instead of the leaf's own definite width. Both now measure at the width the text is painted at: the resolved width when it is fixed or fill, unbounded only when the width itself hugs. The editor's line pass already sends the `(max_width = box width)` record, so the wasm engine takes CanvasKit's height under the corrected key with no frontend change. This corrects server-side hug heights for wrapped text as well — that is the point: "text height is hug" (R7) is only sane if hug follows the copy.

---

### Task 1: `ComputedGeometry.text_lines` and the layout placement

**Files:**
- Modify: `subsystems/clue-design/crates/lumen-core/src/scene.rs` (`ComputedGeometry`, ~line 1315)
- Modify: `subsystems/clue-design/crates/lumen-core/src/layout.rs` (`write_geometry` ~line 782, `validate_text_nodes` ~line 1051–1230, new `painted_text_lines`)
- Modify: `subsystems/clue-design/crates/lumen-core/src/lib.rs` (export `painted_text_lines` next to `layout_scene`)
- Modify: every `ComputedGeometry {` struct literal in the workspace (`grep -rn "ComputedGeometry {" crates --include='*.rs'`: `layout.rs`, `scene.rs`, `lumen-core/tests/{brand_tokens,dsl_compiler,editing,hit_test}.rs`, `lumen-export/tests/{export_adapter,print_ready}.rs`, `lumen-skia/tests/{pdf_booklet,pdf_cmyk,pdf_flatten,pdf_vector,raster_export}.rs`) gains `text_lines: Vec::new(),`
- Test: `subsystems/clue-design/crates/lumen-core/tests/layout_engine.rs`

**Interfaces:**
- Produces: `pub struct ComputedGeometry { layout_bounds: Rect, render_bounds: Rect, text_lines: Vec<Rect> }` and `pub fn painted_text_lines(bounds: &Rect, text: &TextNode, measured: &TextMeasureOutput) -> Vec<Rect>` (Task 2 reads `text_lines`; Task 3's wasm test reads it from scene JSON; Task 5 reads it as `computed.text_lines` on the frontend).

- [ ] **Step 1: Write the failing tests** (append to `lumen-core/tests/layout_engine.rs`; add `ComputedGeometry`, `HeuristicTextMeasurer`, `TextMeasureInput`, `TextMeasurer`, `VerticalAlign` to the `use lumen_core::{...}` import)

```rust
// ── Editor Quality Plan 4, item F: painted line boxes ride in `computed` ────

#[test]
fn computed_text_lines_are_the_painted_line_boxes() {
    // A right-aligned, vertically centred text in a fixed 300×200 box records
    // ONE line box placed where the painters draw it — not the layout box.
    // Under the heuristic measurer the extent is the measurer's own answer, so
    // the expectation is read back from it rather than hard-coded.
    let mut scene = scene_with_page(400.0, 300.0);
    let mut headline = text_node("headline", "Hello", 20.0, 30.0, 300.0, 200.0);
    let NodeKind::Text(text) = &mut headline.kind else {
        unreachable!("text_node builds a text node");
    };
    text.align = TextAlign::Right;
    text.valign = VerticalAlign::Center;
    let text = text.clone();
    insert(&mut scene, ParentRef::Page(PageId::from("page")), headline);

    let result = layout_scene(&scene, lumen_core::LayoutOptions::default());
    let geometry = &result.geometry[&NodeId::from("headline")];
    assert_eq!(geometry.layout_bounds.x, 20.0);
    assert_eq!(geometry.layout_bounds.width, 300.0);

    let measured = HeuristicTextMeasurer.measure(
        &TextMeasureInput::from_text_node(&text).with_bounds(&geometry.layout_bounds),
    );
    assert_eq!(measured.lines.len(), 1, "one short line");
    assert_eq!(geometry.text_lines.len(), 1, "{:#?}", geometry.text_lines);
    let line = &geometry.text_lines[0];
    assert_eq!(line.width, measured.lines[0].width);
    assert_eq!(line.height, measured.lines[0].height);
    // Right-aligned: the line ends at the box's right edge.
    assert_eq!(line.x, 20.0 + (300.0 - measured.lines[0].width));
    // Vertically centred: the stack sits in the middle of the box's slack.
    assert_eq!(line.y, 30.0 + (200.0 - measured.height) / 2.0);
}

#[test]
fn non_text_nodes_record_no_text_lines() {
    let mut scene = scene_with_page(400.0, 300.0);
    let mut rect = Node::new(NodeId::from("plate"), NodeKind::Rect);
    rect.size = SizeSpec::fixed(100.0, 50.0);
    insert(&mut scene, ParentRef::Page(PageId::from("page")), rect);

    let result = layout_scene(&scene, lumen_core::LayoutOptions::default());
    assert!(result.geometry[&NodeId::from("plate")].text_lines.is_empty());
}

#[test]
fn text_lines_serialize_only_when_present_and_default_when_absent() {
    let rect = Rect { x: 1.0, y: 2.0, width: 3.0, height: 4.0 };
    let empty = ComputedGeometry {
        layout_bounds: rect.clone(),
        render_bounds: rect.clone(),
        text_lines: Vec::new(),
    };
    let json = serde_json::to_value(&empty).expect("serializes");
    assert!(json.get("text_lines").is_none(), "{json}");

    let legacy: ComputedGeometry = serde_json::from_value(serde_json::json!({
        "layout_bounds": { "x": 1.0, "y": 2.0, "width": 3.0, "height": 4.0 },
        "render_bounds": { "x": 1.0, "y": 2.0, "width": 3.0, "height": 4.0 }
    }))
    .expect("pre-Plan-4 JSON deserializes");
    assert!(legacy.text_lines.is_empty());

    let placed = ComputedGeometry { text_lines: vec![rect.clone()], ..empty };
    let json = serde_json::to_value(&placed).expect("serializes");
    assert_eq!(json["text_lines"][0]["width"], 3.0);
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd subsystems/clue-design && cargo test -p lumen-core --test layout_engine computed_text_lines 2>&1 | tail -20`
Expected: compile error — `ComputedGeometry` has no field `text_lines`.

- [ ] **Step 3: Add the field and the placement**

`scene.rs`:

```rust
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ComputedGeometry {
    pub layout_bounds: Rect,
    pub render_bounds: Rect,
    /// Editor Quality Plan 4 (item F): the PAINTED line boxes of a text node —
    /// page-space and unrotated, the frame `layout_bounds` is in — one per
    /// measured line, placed where the renderers put the glyphs (`align`
    /// across the box's horizontal slack, `valign` across its vertical slack;
    /// `layout::painted_text_lines`). Empty for every non-text node and for a
    /// text node no layout pass has placed. Never serialized when empty, so
    /// pre-Plan-4 scene JSON and every non-text node stay byte-identical.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub text_lines: Vec<Rect>,
}
```

`layout.rs` — `write_geometry` adds `text_lines: Vec::new(),` to its literal. Add the pure placement (near `render_bounds_for`):

```rust
/// Editor Quality Plan 4 (item F): place a measurer's line boxes where the
/// painters draw them. Measurement lays every line out LEFT-aligned and
/// paragraph-relative (`TextLineBox` docs); `lumen-skia::paint_text_paragraph`
/// and the editor's `paintTextParagraph` both resolve the horizontal placement
/// to `(box_width − line_width) × f(align)` — f is 0 for left and justify, ½
/// for center, 1 for right — and shift the whole stack by
/// `valign_offset(box_height, content_height, valign)`. Justified lines are
/// placed like left (the painters stretch them; the hit slop covers the rest).
/// Page-space, unrotated: the same frame as `layout_bounds`.
pub fn painted_text_lines(
    bounds: &Rect,
    text: &TextNode,
    measured: &TextMeasureOutput,
) -> Vec<Rect> {
    let factor = match text.align {
        TextAlign::Left | TextAlign::Justify => 0.0,
        TextAlign::Center => 0.5,
        TextAlign::Right => 1.0,
    };
    let stack_offset = valign_offset(bounds.height, measured.height, text.valign);
    measured
        .lines
        .iter()
        .map(|line| Rect {
            x: bounds.x + (bounds.width - line.width) * factor + line.x,
            y: bounds.y + stack_offset + line.y,
            width: line.width,
            height: line.height,
        })
        .collect()
}
```

In `validate_text_nodes`, the loop borrows `self.geometry` immutably, so collect and write after it: declare `let mut placed: Vec<(NodeId, Vec<Rect>)> = Vec::new();` before the `for node in self.scene.nodes.values()` loop; right after `let measured = self.measurer.measure(&TextMeasureInput::from_text_node(text).with_bounds(&geometry.layout_bounds));` add

```rust
            // Plan 4 item F: keep what this measurement already knows — the
            // line boxes — instead of discarding them after the overflow
            // checks. Nodes that `continue`d above (invalid metrics, collapsed
            // bounds) keep an empty `text_lines` and hit-test by their box.
            placed.push((
                node.id.clone(),
                painted_text_lines(&geometry.layout_bounds, text, &measured),
            ));
```

and after the loop:

```rust
        for (node_id, text_lines) in placed {
            if let Some(geometry) = self.geometry.get_mut(&node_id) {
                geometry.text_lines = text_lines;
            }
        }
```

Confirm `validate_text_nodes` runs inside the pass that produces `LayoutResult.geometry` (it is where LUMV0902/0903 come from and `layout_scene` returns those diagnostics), so the placement lands before the geometry is returned. Import `TextAlign`, `TextMeasureOutput`, `valign_offset` in `layout.rs` as needed; export `painted_text_lines` from `lib.rs` next to `layout_scene`. Update every other `ComputedGeometry {` literal with `text_lines: Vec::new(),`.

- [ ] **Step 4: Run the tests and the crate suites**

Run: `cd subsystems/clue-design && cargo test -p lumen-core 2>&1 | tail -15 && cargo test -p lumen-wasm -p lumen-export -p lumen-skia --no-run 2>&1 | tail -5`
Expected: all lumen-core tests pass (the three new ones included); the other crates compile (their test literals updated).

- [ ] **Step 5: Format, then commit**

```bash
cd subsystems/clue-design && cargo fmt --all
git add crates
git commit -m "feat(lumen-core): computed geometry keeps a text node's painted line boxes

validate_text_nodes already measures every text node against its solved box and
threw the line boxes away. ComputedGeometry.text_lines now keeps them, placed by
align/valign exactly as both painters place the glyphs (page-space, unrotated).
Empty and unserialized for every non-text node, so existing scene JSON is
byte-identical. Plan 4 item F, step 1."
```

---

### Task 2: Text hit-tests by its painted lines

**Files:**
- Modify: `subsystems/clue-design/crates/lumen-core/src/hit_test.rs` (`point_in_node`, ~line 93)
- Test: `subsystems/clue-design/crates/lumen-core/tests/hit_test.rs`

**Interfaces:**
- Consumes: `ComputedGeometry.text_lines` (Task 1).
- Produces: unchanged `hit_test` / `hit_stack` signatures; new constant `TEXT_LINE_PICK_SLOP: f64 = 2.0`.

- [ ] **Step 1: Write the failing tests** (append to `lumen-core/tests/hit_test.rs`; add `TextAlign`, `TextNode` to the import; the file's `bounds` helper needs `text_lines: Vec::new()` from Task 1 — it is already updated)

```rust
// ── Editor Quality Plan 4, item F: text hits by its painted lines ───────────

fn text_node_with_lines(
    id: &str,
    x: f64,
    y: f64,
    w: f64,
    h: f64,
    lines: &[(f64, f64, f64, f64)],
) -> Node {
    let mut n = node(
        id,
        NodeKind::Text(TextNode {
            content: "x".to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 96.0,
            font_weight: 700,
            align: TextAlign::Left,
            ..TextNode::default()
        }),
        x,
        y,
        w,
        h,
    );
    let computed = n.computed.as_mut().expect("node() sets computed");
    computed.text_lines = lines
        .iter()
        .map(|&(x, y, width, height)| Rect { x, y, width, height })
        .collect();
    n
}

#[test]
fn text_hits_its_painted_lines_not_its_layout_box() {
    // The Apollo "x": a 326×71 fixed box holding one 96pt glyph whose line box
    // (52 wide, 115 tall) runs past the box bottom. A wash sits behind it.
    let wash = node("wash", NodeKind::Rect, 0.0, 0.0, 800.0, 600.0);
    let glyph = text_node_with_lines(
        "x",
        100.0,
        100.0,
        326.0,
        71.0,
        &[(100.0, 100.0, 52.0, 115.0)],
    );
    let scene = scene_with(vec![wash, glyph], vec!["wash", "x"]);

    // Inside the layout box, right of the glyph: the wash, not the text.
    assert_eq!(hit_test(&scene, &page_id(), 300.0, 130.0).unwrap().as_str(), "wash");
    assert_eq!(
        hit_stack(&scene, &page_id(), 300.0, 130.0)
            .iter()
            .map(|n| n.to_string())
            .collect::<Vec<_>>(),
        vec!["wash".to_string()]
    );
    // Below the layout box's bottom (171) but on the painted glyph: the text.
    assert_eq!(hit_test(&scene, &page_id(), 120.0, 200.0).unwrap().as_str(), "x");
    // Pick slop: 1.5 past the line's right edge (152) still hits; 4 past does not.
    assert_eq!(hit_test(&scene, &page_id(), 153.5, 130.0).unwrap().as_str(), "x");
    assert_eq!(hit_test(&scene, &page_id(), 156.0, 130.0).unwrap().as_str(), "wash");
}

#[test]
fn text_without_painted_lines_keeps_the_box_test() {
    // An engine that has not placed lines (pre-Plan-4 `computed`, an empty
    // string, a collapsed box) hit-tests the layout box exactly as before.
    let wash = node("wash", NodeKind::Rect, 0.0, 0.0, 800.0, 600.0);
    let legacy = text_node_with_lines("legacy", 100.0, 100.0, 326.0, 71.0, &[]);
    let zero = text_node_with_lines("zero", 500.0, 100.0, 200.0, 40.0, &[(500.0, 100.0, 0.0, 20.0)]);
    let scene = scene_with(vec![wash, legacy, zero], vec!["wash", "legacy", "zero"]);
    assert_eq!(hit_test(&scene, &page_id(), 300.0, 130.0).unwrap().as_str(), "legacy");
    assert_eq!(hit_test(&scene, &page_id(), 600.0, 120.0).unwrap().as_str(), "zero");
}

#[test]
fn text_lines_follow_the_node_rotation() {
    // A 200×50 box at (100,100) rotated 90° about its origin, with one 80×20
    // line at the box's top-left. Page point (90, 140) maps into the local
    // frame as (40, 10) — inside the line — while (90, 190) maps to (90, 10),
    // past the line's 80 width but still inside the rotated box.
    let wash = node("wash", NodeKind::Rect, 0.0, 0.0, 800.0, 600.0);
    let mut turned = text_node_with_lines("turned", 100.0, 100.0, 200.0, 50.0, &[(100.0, 100.0, 80.0, 20.0)]);
    turned.transform.rotation = 90.0;
    let scene = scene_with(vec![wash, turned], vec!["wash", "turned"]);
    assert_eq!(hit_test(&scene, &page_id(), 90.0, 140.0).unwrap().as_str(), "turned");
    assert_eq!(hit_test(&scene, &page_id(), 90.0, 190.0).unwrap().as_str(), "wash");
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd subsystems/clue-design && cargo test -p lumen-core --test hit_test text_ 2>&1 | tail -25`
Expected: `text_hits_its_painted_lines_not_its_layout_box` fails (the wash point resolves to `x`); the rotation test's second assertion fails; the legacy test passes already.

- [ ] **Step 3: Implement the line test**

In `hit_test.rs`:

```rust
/// Plan 4 item F: pick slop (scene units) around a painted text line, so a
/// click on a descender or a hair past a line's edge still lands on the text.
const TEXT_LINE_PICK_SLOP: f64 = 2.0;
```

and in `point_in_node`, before the catch-all arm:

```rust
        // Plan 4 item F: text hit-tests against its PAINTED line boxes, never
        // its layout box — an oversized fixed box must not steal clicks from
        // what lies behind its empty area, and a glyph painted past the box
        // (a fixed height the copy outgrew) must still be clickable. The boxes
        // are page-space in `layout_bounds`' frame, so they share the node's
        // origin shift and rotation (`to_local` above). A node without
        // positive-area lines keeps the box test below.
        NodeKind::Text(_) if has_painted_lines(node) => point_in_text_lines(node, &b, lx, ly),
```

with

```rust
fn has_painted_lines(node: &Node) -> bool {
    node.computed
        .as_ref()
        .is_some_and(|computed| painted_lines(computed).next().is_some())
}

fn painted_lines(computed: &ComputedGeometry) -> impl Iterator<Item = &Rect> {
    computed
        .text_lines
        .iter()
        .filter(|line| line.width > 0.0 && line.height > 0.0)
}

fn point_in_text_lines(node: &Node, b: &RenderBox, lx: f64, ly: f64) -> bool {
    let Some(computed) = &node.computed else {
        return false;
    };
    painted_lines(computed).any(|line| {
        let x0 = line.x - b.x - TEXT_LINE_PICK_SLOP;
        let y0 = line.y - b.y - TEXT_LINE_PICK_SLOP;
        let x1 = line.x - b.x + line.width + TEXT_LINE_PICK_SLOP;
        let y1 = line.y - b.y + line.height + TEXT_LINE_PICK_SLOP;
        lx >= x0 && lx <= x1 && ly >= y0 && ly <= y1
    })
}
```

(`has_painted_lines` implies `computed` exists, so `b` is `layout_bounds`' origin and `line − b` is the local offset.) Import `ComputedGeometry`, `Rect` from `crate::scene` and `RenderBox` from `crate::render_geometry`. Update the module docblock: text now hit-tests by painted lines.

- [ ] **Step 4: Run the tests**

Run: `cd subsystems/clue-design && cargo test -p lumen-core --test hit_test 2>&1 | tail -15 && cargo test -p lumen-wasm 2>&1 | tail -5`
Expected: all hit_test tests pass (10); lumen-wasm's `hit_test_returns_topmost_node_in_page_space` still passes (its headline has heuristic lines under the box; the probe point is at the line's start).

- [ ] **Step 5: Format, then commit**

```bash
cd subsystems/clue-design && cargo fmt --all
git add crates/lumen-core/src/hit_test.rs crates/lumen-core/tests/hit_test.rs
git commit -m "fix(lumen-core): text hit-tests by its painted line boxes, not its layout box

An oversized fixed text box stole clicks from whatever sat behind its empty
half, and a glyph painted past the box bottom could not be clicked at all. Text
now hits inside any painted line (2-unit slop); a node without placed lines
keeps the box test. Hit-stack contract unchanged. Plan 4 item F, step 2."
```

---

### Task 3: The provided measurer carries line boxes; the wasm bridge accepts them

**Files:**
- Modify: `subsystems/clue-design/crates/lumen-core/src/text_measure.rs` (`ProvidedTextMeasurer` ~line 213–250, inline `provided_measurer_tests` ~line 665)
- Modify: `subsystems/clue-design/crates/lumen-core/src/lib.rs` (export `ProvidedLine`, `ProvidedMetrics`)
- Modify: `subsystems/clue-design/crates/lumen-wasm/src/engine.rs` (`ProvidedMeasurement` ~line 57–100, `set_measurements` ~line 190)
- Test: `subsystems/clue-design/crates/lumen-wasm/tests/engine.rs`

**Interfaces:**
- Produces: `pub struct ProvidedLine { x, y, width, height, baseline: f64 }`, `pub struct ProvidedMetrics { width: f64, height: f64, lines: Option<Vec<ProvidedLine>> }`, `ProvidedTextMeasurer::new(HashMap<String, ProvidedMetrics>)`. Wasm payload entries gain an optional `lines: [{ x, y, width, height, baseline }]` (Task 5 sends it).

- [ ] **Step 1: Write the failing tests**

In `text_measure.rs` `provided_measurer_tests`, change the existing override construction to `ProvidedMetrics { width: 321.0, height: 47.0, lines: None }` and add:

```rust
    #[test]
    fn provided_lines_replace_the_heuristic_lines() {
        let known = input("Hello there");
        let mut overrides = std::collections::HashMap::new();
        overrides.insert(
            measure_key(&known),
            ProvidedMetrics {
                width: 120.0,
                height: 43.2,
                lines: Some(vec![
                    ProvidedLine { x: 0.0, y: 0.0, width: 120.0, height: 21.6, baseline: 17.0 },
                    ProvidedLine { x: 0.0, y: 21.6, width: 60.0, height: 21.6, baseline: 38.6 },
                ]),
            },
        );
        let measurer = ProvidedTextMeasurer::new(overrides);
        let out = measurer.measure(&known);
        assert_eq!(out.line_count, 2);
        assert_eq!(out.lines.len(), 2);
        assert_eq!(out.lines[1].y, 21.6);
        assert_eq!(out.lines[1].width, 60.0);
        assert_eq!(out.lines[1].baseline, 38.6);
        assert!(out.lines[1].runs.is_empty());
    }
```

In `lumen-wasm/tests/engine.rs`:

```rust
#[test]
fn provided_lines_place_text_lines_and_narrow_the_hit_target() {
    // Plan 4 item F: `node_contact_name` is a fixed 160×28 box at (24,40) on
    // the minimal scene. A record keyed on that box (the key
    // `validate_text_nodes` measures with) carries ONE 60-wide line, so the
    // box's empty right half no longer hits the text.
    let mut engine = Engine::from_scene_json(MINIMAL_SCENE).expect("minimal scene loads");
    let measurements = json!([{
        "content": "Dr. Priya Sharma",
        "font_family": "Inter",
        "font_size": 18.0,
        "font_weight": 600,
        "line_height": 1.2,
        "letter_spacing": 0.0,
        "wrap": "wrap",
        "max_lines": null,
        "direction": "ltr",
        "max_width": 160.0,
        "max_height": 28.0,
        "width": 60.0,
        "height": 21.6,
        "lines": [{ "x": 0.0, "y": 0.0, "width": 60.0, "height": 21.6, "baseline": 17.0 }]
    }]);
    let ack = parse(engine.set_measurements(&measurements.to_string()));
    assert_eq!(ack["ok"], true, "{ack:#?}");

    let scene: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    assert_eq!(
        scene["nodes"]["node_contact_name"]["computed"]["text_lines"],
        json!([{ "x": 24.0, "y": 40.0, "width": 60.0, "height": 21.6 }])
    );
    // Inside the box, right of the painted line: nothing (the page has no
    // other child).
    let miss = parse(engine.hit_test("page_a4", 150.0, 50.0));
    assert_eq!(miss["hit"], Value::Null, "{miss:#?}");
    // On the glyphs.
    let hit = parse(engine.hit_test("page_a4", 30.0, 50.0));
    assert_eq!(hit["hit"], "node_contact_name");
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd subsystems/clue-design && cargo test -p lumen-core provided_ 2>&1 | tail -10; cargo test -p lumen-wasm provided_lines 2>&1 | tail -10`
Expected: compile errors — `ProvidedMetrics`/`ProvidedLine` do not exist.

- [ ] **Step 3: Implement**

`text_measure.rs`:

```rust
/// One editor-measured (SkParagraph) line box, paragraph-relative and laid out
/// LEFT-aligned — exactly what `SkiaTextMeasurer` reports (`TextLineBox`),
/// so the layout engine places it by `align`/`valign` the same way.
#[derive(Clone, Debug, PartialEq)]
pub struct ProvidedLine {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
    pub baseline: f64,
}

/// One editor-supplied measurement: the overall extent, and (Plan 4 item F)
/// optionally the painted line boxes. `None` keeps the pre-Plan-4 behaviour —
/// heuristic per-line detail under a Skia-faithful extent.
#[derive(Clone, Debug, PartialEq)]
pub struct ProvidedMetrics {
    pub width: f64,
    pub height: f64,
    pub lines: Option<Vec<ProvidedLine>>,
}
```

`ProvidedTextMeasurer.overrides: HashMap<String, ProvidedMetrics>`; `new(overrides: HashMap<String, ProvidedMetrics>)`. In `measure`:

```rust
        if let Some(metrics) = self.overrides.get(&measure_key(input)) {
            output.width = metrics.width;
            output.height = metrics.height;
            // Plan 4 item F: a record that carries the editor's line boxes
            // replaces the heuristic lines outright — those are what the
            // canvas paints, so they are what hit-testing and the selection
            // outline must see. Runs stay empty (never serialized; only the
            // exporters read them, and they run under the shaping measurer).
            if let Some(lines) = &metrics.lines {
                output.lines = lines
                    .iter()
                    .map(|line| TextLineBox {
                        text: String::new(),
                        x: line.x,
                        y: line.y,
                        width: line.width,
                        height: line.height,
                        baseline: line.baseline,
                        runs: Vec::new(),
                    })
                    .collect();
                output.line_count = output.lines.len() as u16;
            }
        }
```

Update the `ProvidedTextMeasurer` docblock ("delegating everything else — including per-line boxes — to the heuristic" → "…unless the record carries lines"). Export the two structs from `lib.rs` next to `ProvidedTextMeasurer`.

`lumen-wasm/src/engine.rs`: add

```rust
/// Plan 4 item F: one editor-measured line box (see `ProvidedLine`).
#[derive(Deserialize)]
struct ProvidedMeasurementLine {
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    baseline: f64,
}
```

and on `ProvidedMeasurement`:

```rust
    /// Plan 4 item F: the painted line boxes measured at this record's
    /// `max_width` (paragraph-relative, left-aligned). Optional so the
    /// unconstrained records keep their shape.
    #[serde(default)]
    lines: Option<Vec<ProvidedMeasurementLine>>,
```

`set_measurements` builds `ProvidedMetrics { width: entry.width, height: entry.height, lines: entry.lines.as_ref().map(|lines| lines.iter().map(|l| ProvidedLine { x: l.x, y: l.y, width: l.width, height: l.height, baseline: l.baseline }).collect()) }`. Update the method docblock's payload description to mention `lines`.

- [ ] **Step 4: Run the tests**

Run: `cd subsystems/clue-design && cargo test -p lumen-core 2>&1 | tail -8 && cargo test -p lumen-wasm 2>&1 | tail -8`
Expected: all pass, including `set_measurements_makes_hug_text_geometry_skia_faithful` (unchanged) and the two new tests.

- [ ] **Step 5: Format, then commit**

```bash
cd subsystems/clue-design && cargo fmt --all
git add crates/lumen-core crates/lumen-wasm
git commit -m "feat(lumen-wasm): editor-supplied measurements can carry the painted line boxes

ProvidedTextMeasurer only patched width/height and left per-line detail to the
heuristic. A record may now carry the CanvasKit line boxes, which replace the
heuristic lines so the wasm engine's text_lines are what the canvas paints.
Plan 4 item F, step 3."
```

---

### Task 4: Text hugs by default — DSL, author prompt, LinkedIn ad skill

**Files:**
- Modify: `subsystems/clue-design/crates/lumen-core/src/dsl.rs` (`node_from_element`, ~line 4632)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts.py` (`_AUTHOR_TEACHING_BODY`, after the `s(460,hug)` bullet ~line 328)
- Modify: `subsystems/clue-design/apps/agent_runtime/knowledge_docs/skills/linkedin-square-ad/SKILL.md` (the `## Type` section, ~line 87)
- Test: `subsystems/clue-design/crates/lumen-core/tests/dsl_compiler.rs`
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_prompts_text_height.py` (new)

**Interfaces:**
- Produces: an unsized DSL text element lowers to `SizeSpec { width: Hug, height: Hug }`; the exact sentences below (Task 8's live proof and the memo quote them).

- [ ] **Step 1: Write the failing tests**

`dsl_compiler.rs` (near the other size assertions; `Scene`, `DocumentId`, `Dimension`, `NodeId` are already imported there — add any that are not):

```rust
#[test]
fn unsized_text_element_hugs_both_axes_and_an_explicit_size_still_wins() {
    // Editor Quality Plan 4 (item F, ruling R7): a text element with no s(...)
    // used to inherit Node::new's 0×0 fixed box (LUMV0901 collapsed bounds).
    // It now hugs its copy; an authored size — fixed height included — is
    // never rewritten.
    let mut scene = Scene::new(DocumentId::from("doc_text_default"), "Text default");
    let output = compile_dsl_into_scene(
        "page page_a4 preset(a4,portrait)\n  copy text \"Hi\" p(0,0)\n  boxed text \"Hi\" p(0,40) s(300,80)\n  wide text \"Hi\" p(0,140) s(fill,hug)",
        &mut scene,
    );
    assert_no_dsl_errors(&output.compile_output.diagnostics);

    let copy = &scene.nodes[&NodeId::from("copy")];
    assert_eq!(copy.size.width, Dimension::Hug);
    assert_eq!(copy.size.height, Dimension::Hug);

    let boxed = &scene.nodes[&NodeId::from("boxed")];
    assert_eq!(boxed.size.width, Dimension::Fixed(300.0));
    assert_eq!(boxed.size.height, Dimension::Fixed(80.0));

    let wide = &scene.nodes[&NodeId::from("wide")];
    assert_eq!(wide.size.width, Dimension::Fill { weight: 1.0 });
    assert_eq!(wide.size.height, Dimension::Hug);
}
```

(If `Dimension::Fill`'s DSL default weight is not `1.0`, read `dimension_to_scene` and assert the value it produces; do not change it.)

`tests/test_prompts_text_height.py`:

```python
"""Editor Quality Plan 4, item F: text height is hug — the authoring default reaches the author and the LinkedIn ad skill."""

from __future__ import annotations

from pathlib import Path

from lumen_agent import prompts

SKILL = (
    Path(prompts.__file__).resolve().parents[1]
    / "knowledge_docs" / "skills" / "linkedin-square-ad" / "SKILL.md"
)

AUTHOR_RULE = (
    "TEXT HEIGHT IS HUG. Size every text node `s(W,hug)` or `s(fill,hug)`; a text element "
    "with no `s(...)` hugs on both axes. Never give a text node a fixed height: the box stops "
    "following the copy, the editor outlines empty space, and glyphs that overflow the box "
    "cannot be clicked. Fixed and fill WIDTHS are fine."
)
SKILL_RULE = (
    "**Text height is always hug.** Write `s(W,hug)` or `s(fill,hug)`; never a fixed height on "
    "a text node — the box stops following the copy and the editor outlines empty space. "
    "Widths may be fixed or fill."
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_author_teaching_body_says_text_height_is_hug() -> None:
    assert _flat(AUTHOR_RULE) in _flat(prompts._AUTHOR_TEACHING_BODY)


def test_linkedin_ad_skill_says_text_height_is_hug() -> None:
    assert _flat(SKILL_RULE) in _flat(SKILL.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd subsystems/clue-design && cargo test -p lumen-core --test dsl_compiler unsized_text 2>&1 | tail -12; set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/agent_runtime/tests/test_prompts_text_height.py -q 2>&1 | tail -5`
Expected: the Rust test fails on `copy.size.width` (`Fixed(0.0)`); both pytest tests fail.

- [ ] **Step 3: Implement**

`dsl.rs::node_from_element`, right after the node is constructed from `kind` (before properties are applied — find the `Node::new(element.id.clone(), kind)` call at the function's tail; if the node is built and returned in one expression, bind it to `let mut node` first):

```rust
    if matches!(node.kind, NodeKind::Text(_)) {
        // Editor Quality Plan 4 (item F, ruling R7): a text element that names
        // no size hugs its copy on both axes. `Node::new`'s 0×0 fixed box
        // collapsed (LUMV0901), and the fixed heights authors reached for
        // instead stopped following the copy — the selection box then
        // outlined empty space. An explicit `s(...)` is applied after this
        // and wins; no authored size is ever rewritten.
        node.size = SizeSpec {
            width: Dimension::Hug,
            height: Dimension::Hug,
        };
    }
```

`prompts.py`, immediately after the `s(460,hug)` example bullet inside `_AUTHOR_TEACHING_BODY`, add one bullet whose text is `AUTHOR_RULE` verbatim, wrapped at the block's line width:

```
- TEXT HEIGHT IS HUG. Size every text node `s(W,hug)` or `s(fill,hug)`; a text element
  with no `s(...)` hugs on both axes. Never give a text node a fixed height: the box stops
  following the copy, the editor outlines empty space, and glyphs that overflow the box
  cannot be clicked. Fixed and fill WIDTHS are fine.
```

`SKILL.md`, as the first bullet of `## Type`:

```
- **Text height is always hug.** Write `s(W,hug)` or `s(fill,hug)`; never a fixed height on
  a text node — the box stops following the copy and the editor outlines empty space.
  Widths may be fixed or fill.
```

Only the canonical skill file under `apps/agent_runtime/knowledge_docs/` is edited (Plan 2 did the same); the `.deepagent-workspace/` copies are runtime materializations.

- [ ] **Step 4: Run the tests**

Run: `cd subsystems/clue-design && cargo test -p lumen-core --test dsl_compiler 2>&1 | tail -6; set -a; source ../../.env; set +a; PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/agent_runtime/tests/test_prompts_text_height.py apps/agent_runtime/tests/test_prompts_page_first.py -q 2>&1 | tail -4`
Expected: all dsl_compiler tests pass (if any existing test asserted an unsized text element's `Fixed(0.0)` size, read it and update its expectation to `Hug` with a one-line comment naming this ruling — that is the only sanctioned change to an existing assertion); pytest 6 passed.

- [ ] **Step 5: Format, then commit**

```bash
cd subsystems/clue-design && cargo fmt --all
git add crates/lumen-core/src/dsl.rs crates/lumen-core/tests/dsl_compiler.rs apps/agent_runtime/lumen_agent/prompts.py apps/agent_runtime/knowledge_docs/skills/linkedin-square-ad/SKILL.md apps/agent_runtime/tests/test_prompts_text_height.py
git commit -m "feat(design-agent): text height is hug — DSL default, author prompt, LinkedIn ad skill

An unsized text element lowered to a 0×0 fixed box; authors then reached for
fixed heights the copy outgrew. The DSL now defaults text to s(hug,hug) (an
explicit size still wins, nothing authored is rewritten) and the author prompt
and the ad skill state the rule. Plan 4 item F, authoring default."
```

---

### Task 5: The editor sends CanvasKit line boxes keyed on the solved boxes

**Files:**
- Modify: `apps/frontend/src/features/design-editor/engine/scene/contracts.ts` (`ComputedGeometry`, ~line 629)
- Modify: `apps/frontend/src/features/design-editor/engine/scene/wasmEngine.ts` (`TextMeasurement`, ~line 55–90)
- Modify: `apps/frontend/src/features/design-editor/engine/scene/canvaskit/skiaMeasurements.ts`
- Modify: `apps/frontend/src/features/design-editor/hooks/use-scene-document.ts` (the C4 effect, ~line 447–470)
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-canvas-view.ts` (`textMeasurementSignature`, ~line 458)
- Test: `apps/frontend/src/features/design-editor/engine/scene/__tests__/skiaMeasurements.test.ts`
- Test: `apps/frontend/src/features/design-editor/adapter/scene-canvas-view.test.ts`

**Interfaces:**
- Consumes: the wasm payload `lines` (Task 3).
- Produces: `ComputedGeometry.text_lines?: Rect[]`; `TextMeasurementLine { x, y, width, height, baseline }`; `TextMeasurement.lines?: TextMeasurementLine[]`; `skiaLineMeasurements(ck, fontProvider, scene): TextMeasurement[]` (Task 6 reads `text_lines`).

- [ ] **Step 1: Write the failing tests**

`skiaMeasurements.test.ts` (inside the existing `describe.skipIf(!present)` block; import `skiaLineMeasurements`):

```ts
  it("Plan 4: emits line boxes keyed on each laid-out text node's solved box, twice", () => {
    const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    const node = scene.nodes.node_contact_name;
    if (node.kind.kind !== "text") throw new Error("fixture");
    node.kind.content = "Hello there, world again and again and again";
    node.kind.font_family = family;
    node.kind.font_size = 20;
    node.kind.wrap = "wrap";
    node.computed = {
      layout_bounds: { x: 10, y: 20, width: 120, height: 200 },
      render_bounds: { x: 10, y: 20, width: 120, height: 200 }
    };
    // A second text node the engine has not laid out: nothing to key on.
    scene.nodes.unlaid = { ...node, id: "unlaid", computed: null };

    const records = skiaLineMeasurements(ck, fontMgr, scene);
    expect(records.length).toBe(2);
    const [validateKey, taffyKey] = records;
    expect(validateKey.max_width).toBe(120);
    expect(validateKey.max_height).toBe(200);
    expect(taffyKey.max_width).toBe(120);
    expect(taffyKey.max_height).toBeUndefined();
    // Same key fields as the unconstrained record.
    const unconstrained = skiaMeasurements(ck, fontMgr, scene).find((r) => r.content === node.kind.content)!;
    for (const key of ["content", "font_family", "font_size", "font_weight", "line_height", "letter_spacing", "wrap", "max_lines", "direction", "text_transform", "truncate", "paragraph_spacing", "italic"] as const) {
      expect(validateKey[key]).toEqual(unconstrained[key]);
    }
    // Wrapped at 120: several lines, ascending, each inside the width.
    const lines = validateKey.lines!;
    expect(lines.length).toBeGreaterThan(1);
    for (let i = 0; i < lines.length; i += 1) {
      expect(lines[i].x).toBeGreaterThanOrEqual(0);
      expect(lines[i].width).toBeLessThanOrEqual(121);
      expect(lines[i].height).toBeGreaterThan(0);
      if (i > 0) expect(lines[i].y).toBeGreaterThan(lines[i - 1].y);
    }
    expect(taffyKey.lines).toEqual(lines);
    // Extent is the stacked lines, not the unconstrained single line.
    expect(validateKey.height).toBeGreaterThan(unconstrained.height);
    expect(validateKey.width).toBeLessThanOrEqual(121);
  });

  it("Plan 4: max_lines cuts the line boxes", () => {
    const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
    const node = scene.nodes.node_contact_name;
    if (node.kind.kind !== "text") throw new Error("fixture");
    node.kind.content = "Hello there, world again and again and again";
    node.kind.font_family = family;
    node.kind.font_size = 20;
    node.kind.wrap = "wrap";
    node.kind.max_lines = 2;
    node.computed = {
      layout_bounds: { x: 0, y: 0, width: 120, height: 200 },
      render_bounds: { x: 0, y: 0, width: 120, height: 200 }
    };
    const [record] = skiaLineMeasurements(ck, fontMgr, scene);
    expect(record.lines!.length).toBe(2);
  });
```

`scene-canvas-view.test.ts` (next to the signature tests):

```ts
test("Plan 4: a text node's solved size is part of the measurement signature", () => {
  // The line pass is keyed on the box the engine solved; a resized box must
  // re-measure or its lines go stale (the key misses → heuristic lines).
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.text_proof_stat.computed = {
    layout_bounds: { x: 0, y: 0, width: 300, height: 120 },
    render_bounds: { x: 0, y: 0, width: 300, height: 120 },
  };
  const before = textMeasurementSignature(scene, 0);
  scene.nodes.text_proof_stat.computed.layout_bounds.width = 280;
  assert.notEqual(textMeasurementSignature(scene, 0), before);
  // A non-text node's size never re-measures.
  const rect = clone(HARVESTED_AD_PAGE);
  rect.nodes.rect_accent_bar.computed = {
    layout_bounds: { x: 0, y: 0, width: 9, height: 9 },
    render_bounds: { x: 0, y: 0, width: 9, height: 9 },
  };
  assert.equal(textMeasurementSignature(rect, 0), textMeasurementSignature(HARVESTED_AD_PAGE, 0));
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/adapter/scene-canvas-view.test.ts 2>&1 | tail -12; npx vitest run src/features/design-editor/engine/scene/__tests__/skiaMeasurements.test.ts 2>&1 | tail -12` (check which runner `package.json` wires for `__tests__` files under `engine/scene` — the file imports a vitest shim; use the command the existing test runs under).
Expected: the signature test fails (equal signatures); the measurement tests fail (`skiaLineMeasurements` is not exported).

- [ ] **Step 3: Implement**

`contracts.ts`:

```ts
export interface ComputedGeometry {
  layout_bounds: Rect;
  render_bounds: Rect;
  /** Plan 4 item F: the PAINTED line boxes of a text node, page-space and
   * unrotated (the frame `layout_bounds` is in), placed by the engine exactly
   * as the painters place the glyphs. Absent on non-text nodes, on stored
   * scenes, and on nodes the engine has not placed — never an empty array on
   * the wire (`skip_serializing_if`). */
  text_lines?: Rect[];
}
```

`wasmEngine.ts`:

```ts
/** Plan 4 item F: one CanvasKit line box, paragraph-relative and measured
 * LEFT-aligned — the shape `SkiaTextMeasurer` reports, so the engine places it
 * by `align`/`valign` itself. */
export interface TextMeasurementLine {
  x: number;
  y: number;
  width: number;
  height: number;
  baseline: number;
}
```

and on `TextMeasurement`: `/** Plan 4 item F: the painted line boxes measured at this record's `max_width` (see `skiaLineMeasurements`). */ lines?: TextMeasurementLine[];`.

`skiaMeasurements.ts`:
1. Extract the record construction from `skiaMeasurements`'s loop into `function measurementRecord(t: TextNode["kind" extends never ? never : Extract<Node["kind"], { kind: "text" }>]): TextMeasurement` — i.e. the `record` literal with `width: 0, height: 0` — and call it from both passes (behaviour of `skiaMeasurements` unchanged byte-for-byte: same fields, same values).
2. Extract paragraph builders so the two existing measure functions and the new line pass share them: `buildPlainParagraph(ck, fontProvider, input: ParagraphInput): { paragraph: Paragraph; builder: ParagraphBuilder }` (the style + builder + `addText` of `measureParagraph`, no `layout`) and `buildSpannedParagraph(ck, fontProvider, styled, spans, content, textTransform, blockItalic)` (the same from `measureSpannedParagraph`). Both existing functions call the builder, `layout(Number.MAX_SAFE_INTEGER)`, read the same metrics, and delete — outputs unchanged. Both builders take an `align` parameter defaulting to left; the line pass passes left (mirroring `SkiaTextMeasurer`, which measures `SkTextAlign::Left` and lets the engine place).
3. Add:

```ts
/**
 * Plan 4 item F: painted line boxes per text node the engine has laid out,
 * keyed on the box it SOLVED. Two records per node, same lines and extent:
 *   • `(max_width, max_height)` = `layout_bounds` — the key
 *     `validate_text_nodes` measures with (`TextMeasureInput::with_bounds`),
 *     which is where `computed.text_lines` is placed from;
 *   • `(max_width)` alone — the key taffy's measure closure uses for a
 *     hug-height node (`measure_taffy_node`: `max_width = available width`,
 *     no height), so a wrapped hug box takes CanvasKit's height, not the
 *     heuristic's.
 * Lines are measured LEFT-aligned and paragraph-relative, exactly as
 * `SkiaTextMeasurer` reports them; the engine applies `align`/`valign`. The
 * layout width mirrors the painter: the box width for wrap and for
 * NoWrap+truncate, unbounded for plain NoWrap. Paragraph spacing stacks
 * paragraphs with the gap, as `paintStackedParagraphs` does; `max_lines` cuts
 * the merged list (total across paragraphs, like the Rust measurer).
 * Nodes without `computed` have no box to key on and are skipped.
 */
export function skiaLineMeasurements(ck: CanvasKit, fontProvider: TypefaceFontProvider, scene: Scene): TextMeasurement[] {
  const out: TextMeasurement[] = [];
  for (const node of Object.values(scene.nodes)) {
    if (node.kind.kind !== "text" || !node.computed) {
      continue;
    }
    const bounds = node.computed.layout_bounds;
    if (!(bounds.width > 0) || !(bounds.height > 0)) {
      continue;
    }
    const measured = measureLinesAtWidth(ck, fontProvider, node.kind, bounds.width);
    const base = measurementRecord(node.kind);
    out.push({ ...base, max_width: bounds.width, max_height: bounds.height, width: measured.width, height: measured.height, lines: measured.lines });
    out.push({ ...base, max_width: bounds.width, width: measured.width, height: measured.height, lines: measured.lines });
  }
  return out;
}
```

`measureLinesAtWidth` builds the paragraph(s) via the shared builders with the node's resolved fields (`resolvedTextFields`), the transformed content, and the node's spans; lays out at `wrap === "wrap" || truncate ? width : Number.MAX_SAFE_INTEGER`; for `paragraph_spacing > 0` with a break in the content it splits like `paintStackedParagraphs` (read `drawDescriptors.ts:346-420` and mirror its split and cursor arithmetic) and stacks `cursor += paragraph.getHeight() + gap`; collects `for (const m of paragraph.getLineMetrics()) lines.push({ x: m.left, y: top + m.baseline - m.ascent, width: m.width, height: m.height, baseline: top + m.baseline })`; truncates to `max_lines`; returns `{ width: round(max line width), height: round(total stacked height), lines: lines.map(round each field) }`. Deletes every paragraph and builder.

`use-scene-document.ts`, the C4 effect body:

```ts
      // Pass 1 (Wave 3 C4): unconstrained extents, so hug boxes take Skia's
      // size. Pass 2 (Plan 4 item F): the line boxes, keyed on the boxes pass
      // 1 solved. Both sets ride the second call — `setMeasurements`
      // REPLACES the override set. The effect's signature includes each text
      // node's solved size, so a box that changes here re-runs the effect;
      // the injection is deterministic, so that stops at the first pass that
      // changes nothing.
      const unconstrained = skiaMeasurements(bundle.ck, bundle.fontProvider, engine.scene);
      engine.setMeasurements(unconstrained);
      engine.setMeasurements([
        ...unconstrained,
        ...skiaLineMeasurements(bundle.ck, bundle.fontProvider, engine.scene),
      ]);
```

`textMeasurementSignature`: append to each text node's part `node.computed ? \`${node.computed.layout_bounds.width.toFixed(3)}x${node.computed.layout_bounds.height.toFixed(3)}\` : "_"` and extend the function's docblock: the line pass is keyed on the solved box, so the box is a measurement input now; convergence reasoning as above.

- [ ] **Step 4: Run the tests, lint and the full frontend suite**

Run: `cd apps/frontend && npx vitest run src/features/design-editor/engine/scene/__tests__/skiaMeasurements.test.ts 2>&1 | tail -8; npx tsx --test src/features/design-editor/adapter/scene-canvas-view.test.ts 2>&1 | tail -6; npm run lint 2>&1 | tail -5; npm test 2>&1 | tail -6`
Expected: all pass; lint clean.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/design-editor
git commit -m "feat(design-editor): send CanvasKit line boxes keyed on each text node's solved box

The measure-then-inject bridge only carried unconstrained extents, so the wasm
engine's per-line detail — and now its painted text_lines — was heuristic. A
second pass measures every laid-out text node at its box width and sends the
line boxes under the validate key and the taffy key; the measurement signature
includes the solved size so a resized box re-measures. Plan 4 item F, step 4."
```

---

### Task 5b (added after the Task 8 live proof): hug height measures at the wrap width

**Files:**
- Modify: `subsystems/clue-design/crates/lumen-core/src/layout.rs` (`resolve_manual_size` ~line 684, `measure_taffy_node` ~line 1738)
- Test: `subsystems/clue-design/crates/lumen-core/tests/layout_engine.rs`
- Test: `subsystems/clue-design/crates/lumen-wasm/tests/engine.rs`

**Interfaces:**
- Consumes: `TextMeasureInput::from_text_node` / `max_width` (existing); the editor's `(max_width = box width)` records (Task 5).
- Produces: no new names; the hug height of a fixed- or fill-width text node equals `measure(from_text_node(text) with max_width = width).height` on every layout path.

- [ ] **Step 1: Write the failing tests** (`layout_engine.rs`; `HeuristicTextMeasurer`, `TextMeasureInput`, `TextMeasurer`, `AutoLayoutNode`/`AutoLayoutProps`/`AutoLayoutDirection` are already imported there)

```rust
// ── Plan 4 ruling R8: hug height follows the wrap width ──────────────────────

const R8_COPY: &str = "Pipeline that shows up on time for every rep on the team";

fn r8_expected_height(text: &TextNode, width: f64) -> f64 {
    let mut input = TextMeasureInput::from_text_node(text);
    input.max_width = Some(width);
    HeuristicTextMeasurer.measure(&input).height
}

#[test]
fn fixed_width_text_under_a_page_hugs_its_wrapped_height() {
    let mut scene = scene_with_page(600.0, 400.0);
    let mut copy = text_node("copy", R8_COPY, 20.0, 20.0, 120.0, 0.0);
    copy.size.height = Dimension::Hug;
    let NodeKind::Text(text) = &mut copy.kind else { unreachable!() };
    text.wrap = lumen_core::TextWrap::Wrap;
    let text = text.clone();
    insert(&mut scene, ParentRef::Page(PageId::from("page")), copy);

    let result = layout_scene(&scene, lumen_core::LayoutOptions::default());
    let bounds = &result.geometry[&NodeId::from("copy")].layout_bounds;
    let expected = r8_expected_height(&text, 120.0);
    let unbounded = HeuristicTextMeasurer.measure(&TextMeasureInput::from_text_node(&text)).height;
    assert!(expected > unbounded, "the copy must wrap at 120 for this test to mean anything");
    assert_eq!(bounds.width, 120.0);
    assert_eq!(bounds.height, expected, "hug height is the WRAPPED height, not {unbounded}");
}

#[test]
fn fixed_width_text_inside_a_stack_hugs_its_wrapped_height() {
    // The taffy path: the leaf's own definite width is the wrap width, not the
    // 600-wide column's available space.
    let mut scene = scene_with_page(600.0, 400.0);
    let mut column = Node::new(
        NodeId::from("column"),
        NodeKind::AutoLayout(AutoLayoutNode { direction: AutoLayoutDirection::Column, ..AutoLayoutNode::default() }),
    );
    column.size = SizeSpec { width: Dimension::Fixed(600.0), height: Dimension::Hug };
    insert(&mut scene, ParentRef::Page(PageId::from("page")), column);
    let mut copy = text_node("copy", R8_COPY, 0.0, 0.0, 120.0, 0.0);
    copy.size.height = Dimension::Hug;
    let NodeKind::Text(text) = &mut copy.kind else { unreachable!() };
    text.wrap = lumen_core::TextWrap::Wrap;
    let text = text.clone();
    insert(&mut scene, ParentRef::Node(NodeId::from("column")), copy);

    let result = layout_scene(&scene, lumen_core::LayoutOptions::default());
    let bounds = &result.geometry[&NodeId::from("copy")].layout_bounds;
    // Taffy rounds to whole pixels; the plan's own ROUNDING_TOLERANCE.
    assert!((bounds.height - r8_expected_height(&text, 120.0)).abs() <= 0.51, "{bounds:?}");
}

#[test]
fn hug_width_text_still_measures_unbounded() {
    let mut scene = scene_with_page(600.0, 400.0);
    let mut copy = text_node("copy", R8_COPY, 20.0, 20.0, 0.0, 0.0);
    copy.size = SizeSpec { width: Dimension::Hug, height: Dimension::Hug };
    let NodeKind::Text(text) = &mut copy.kind else { unreachable!() };
    text.wrap = lumen_core::TextWrap::Wrap;
    let text = text.clone();
    insert(&mut scene, ParentRef::Page(PageId::from("page")), copy);

    let result = layout_scene(&scene, lumen_core::LayoutOptions::default());
    let bounds = &result.geometry[&NodeId::from("copy")].layout_bounds;
    let unbounded = HeuristicTextMeasurer.measure(&TextMeasureInput::from_text_node(&text));
    assert_eq!(bounds.width, unbounded.width);
    assert_eq!(bounds.height, unbounded.height);
}
```

(Read `AutoLayoutNode`'s real fields and `ParentRef`'s variants in the file's existing tests and build the column the way they do; the shape above is illustrative for those two constructors only.)

`lumen-wasm/tests/engine.rs`:

```rust
#[test]
fn fixed_width_hug_text_takes_the_editor_height_measured_at_its_width() {
    // Ruling R8: `node_contact_name` fixed 160 wide, hug height. The editor's
    // line pass keys its record on `max_width = 160` with no height; that is
    // now the key the manual path measures with, so the injected height lands.
    let mut scene: Value = serde_json::from_str(MINIMAL_SCENE).expect("scene json");
    scene["nodes"]["node_contact_name"]["size"] =
        json!({ "width": { "kind": "fixed", "value": 160.0 }, "height": { "kind": "hug" } });
    let mut engine = Engine::from_scene_json(&scene.to_string()).expect("scene loads");
    let measurements = json!([{
        "content": "Dr. Priya Sharma", "font_family": "Inter", "font_size": 18.0, "font_weight": 600,
        "line_height": 1.2, "letter_spacing": 0.0, "wrap": "wrap", "max_lines": null, "direction": "ltr",
        "max_width": 160.0, "width": 100.0, "height": 99.0
    }]);
    let ack = parse(engine.set_measurements(&measurements.to_string()));
    assert_eq!(ack["ok"], true, "{ack:#?}");
    let scene: Value = serde_json::from_str(&engine.scene_json()).expect("scene");
    assert_eq!(scene["nodes"]["node_contact_name"]["computed"]["layout_bounds"]["height"], 99.0);
    assert_eq!(scene["nodes"]["node_contact_name"]["computed"]["layout_bounds"]["width"], 160.0);
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd subsystems/clue-design && cargo test -p lumen-core --test layout_engine r8_ hugs_its 2>&1 | tail -20; cargo test -p lumen-wasm fixed_width_hug 2>&1 | tail -8`
Expected: the two "hugs_its_wrapped_height" tests fail (height = the unbounded / container-width height); the hug-width test passes already; the wasm test fails (height stays the heuristic 21.6).

- [ ] **Step 3: Implement**

`resolve_manual_size` resolves the width first and measures the height at it:

```rust
    fn resolve_manual_size(&self, node: &Node, parent_size: Size2) -> Size2 {
        let width = match &node.size.width {
            Dimension::Fixed(value) => *value,
            Dimension::Fill { .. } => parent_size.width,
            Dimension::Hug | Dimension::Token { .. } => self.natural_size(node).width,
        };
        let height = match &node.size.height {
            Dimension::Fixed(value) => *value,
            Dimension::Fill { .. } => parent_size.height,
            Dimension::Hug | Dimension::Token { .. } => self.natural_height_at_width(node, width),
        };
        Size2 { width, height }
    }

    /// Editor Quality Plan 4 (ruling R8): a text node's hug height is measured
    /// at the width it is PAINTED at. The painters lay wrapped text out at the
    /// box width, so a fixed- or fill-width text node measured without a bound
    /// hugged its unwrapped line count — a 503-wide headline that paints three
    /// lines hugged two, and the box stopped following the copy. Only a text
    /// node whose width itself hugs measures unbounded (that IS its width).
    /// Every other kind keeps `natural_size`.
    fn natural_height_at_width(&self, node: &Node, width: f64) -> f64 {
        match &node.kind {
            NodeKind::Text(text)
                if !matches!(node.size.width, Dimension::Hug | Dimension::Token { .. }) =>
            {
                let mut input = TextMeasureInput::from_text_node(text);
                input.max_width = Some(width.max(0.0));
                self.measurer.measure(&input).height
            }
            _ => self.natural_size(node).height,
        }
    }
```

`measure_taffy_node`'s text arm:

```rust
        Some(MeasureContext::Text(input)) => {
            // Plan 4 (ruling R8): a leaf with a definite width wraps at THAT
            // width — the painters lay out at the box, not at the container's
            // available space. A width-less leaf keeps the available bound.
            input.max_width = match known_dimensions.width {
                Some(width) => Some(f64::from(width)),
                None => available_width(available_space.width),
            };
            let measured = measurer.measure(input);
            Size2 { width: measured.width, height: measured.height }
        }
```

- [ ] **Step 4: Run the crate suites and analyze every change**

Run: `cd subsystems/clue-design && cargo test -p lumen-core --lib --test layout_engine --test hit_test --test editing --test dsl_compiler --test preflight_pipeline --test freehand_layout --test personalization --test a6b_spans 2>&1 | grep -E "^test result|FAILED|panicked"; cargo test -p lumen-wasm 2>&1 | grep -E "^test result|FAILED"; cargo test -p lumen-export -p lumen-skia 2>&1 | grep -E "^test result|FAILED|panicked"`
Expected: the new tests pass. Any pre-existing test that now fails encoded the old unbounded hug height; for each, state in the report which test, what it expected, what it gets now, and why the new number is the wrapped height — then update ONLY that expectation with a one-line comment naming ruling R8. A failure that is not explained by the wrap width is a stop: report NEEDS_CONTEXT. `lumen-skia`'s golden tests compare against untracked PNGs that were generated from the pre-plan commit; a golden that drifts because a hug box grew is expected — report which and by how many pixels; do not regenerate goldens.

- [ ] **Step 5: Commit** (explicit paths; `rustfmt --edition 2021 --check` on the touched files first, fixing only your hunks)

```bash
git add subsystems/clue-design/crates/lumen-core/src/layout.rs subsystems/clue-design/crates/lumen-core/tests/layout_engine.rs subsystems/clue-design/crates/lumen-wasm/tests/engine.rs
git commit -m "fix(lumen-core): a text node's hug height is measured at its wrap width

Outside a taffy solve the hug height came from an unbounded measurement, so a
fixed-width wrapped headline hugged its unwrapped line count; inside one the
closure wrapped at the container's available width instead of the leaf's own.
Both now measure at the width the text is painted at. Plan 4 ruling R8, found
by the live proof (Apollo headline: 2 lines hugged, 3 painted)."
```

---

### Task 6: The selection outline is the painted text; a fixed box keeps a dashed frame

**Files:**
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-canvas-view.ts` (`SceneSelectionOutline` ~line 677, `selectionOutlineForBox` ~line 708, `sceneSelectionOutline` ~line 769, `selectionHandleRects` ~line 841; new `sceneTextPaintedBox`, `sceneTextFrameDiffers`)
- Modify: `apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx` (`SelectionChrome` ~line 2204)
- Test: `apps/frontend/src/features/design-editor/adapter/scene-canvas-view.test.ts`

**Interfaces:**
- Consumes: `ComputedGeometry.text_lines` (Task 5).
- Produces: `SceneSelectionOutline.frame: { x, y, width, height } | null` (screen px); `sceneTextPaintedBox(node: Node): Box | null`; `selectionHandleRects(box: { x; y; width; height })`.

- [ ] **Step 1: Write the failing tests** (`scene-canvas-view.test.ts`; import `sceneTextPaintedBox`, `selectionOutlineForBox`)

```ts
test("Plan 4: a text node's outline is the union of its painted lines; the layout box is the dashed frame", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  const node = scene.nodes.text_proof_stat;
  node.computed = {
    layout_bounds: { x: 100, y: 100, width: 300, height: 120 },
    render_bounds: { x: 100, y: 100, width: 300, height: 120 },
    text_lines: [
      { x: 100, y: 100, width: 180, height: 40 },
      { x: 100, y: 140, width: 120, height: 40 },
    ],
  };
  assert.deepEqual(sceneTextPaintedBox(node), { x: 100, y: 100, width: 180, height: 80 });
  const artboard = heroArtboard(scene);
  const viewport = sceneViewportModel({ rect: artboard.rect, stage: { width: 664, height: 664 }, zoom: null }).applied;
  const outline = sceneSelectionOutline({ artboard, pageId: AD_PAGE_ID, scene, selectedNodeId: node.id, viewport });
  const painted = selectionOutlineForBox({ artboard, box: { x: 100, y: 100, width: 180, height: 80 }, nodeId: node.id, rotation: 0, viewport })!;
  const frame = selectionOutlineForBox({ artboard, box: { x: 100, y: 100, width: 300, height: 120 }, nodeId: node.id, rotation: 0, viewport })!;
  assert.deepEqual(outline, {
    ...painted,
    frame: { x: frame.x, y: frame.y, width: frame.width, height: frame.height },
  });
});

test("Plan 4: a hug box (lines fill it within the rounding contract) draws no frame", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  const node = scene.nodes.text_proof_stat;
  node.computed = {
    layout_bounds: { x: 100, y: 100, width: 180, height: 80 },
    render_bounds: { x: 100, y: 100, width: 180, height: 80 },
    text_lines: [
      { x: 100, y: 100, width: 180, height: 40 },
      { x: 100, y: 140, width: 120, height: 40.4 },
    ],
  };
  const artboard = heroArtboard(scene);
  const viewport = sceneViewportModel({ rect: artboard.rect, stage: { width: 664, height: 664 }, zoom: null }).applied;
  const outline = sceneSelectionOutline({ artboard, pageId: AD_PAGE_ID, scene, selectedNodeId: node.id, viewport });
  assert.ok(outline);
  assert.equal(outline.frame, null);
});

test("Plan 4: a text node without painted lines, and a gesture preview, outline the box with no frame", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  const node = scene.nodes.text_proof_stat;
  node.computed = {
    layout_bounds: { x: 100, y: 100, width: 300, height: 120 },
    render_bounds: { x: 100, y: 100, width: 300, height: 120 },
  };
  const artboard = heroArtboard(scene);
  const viewport = sceneViewportModel({ rect: artboard.rect, stage: { width: 664, height: 664 }, zoom: null }).applied;
  const plain = sceneSelectionOutline({ artboard, pageId: AD_PAGE_ID, scene, selectedNodeId: node.id, viewport });
  assert.deepEqual(plain, selectionOutlineForBox({ artboard, box: { x: 100, y: 100, width: 300, height: 120 }, nodeId: node.id, rotation: 0, viewport }));
  assert.equal(plain?.frame, null);
  node.computed.text_lines = [{ x: 100, y: 100, width: 50, height: 40 }];
  const scale = artboard.page.unitScale;
  const previewed = sceneSelectionOutline({
    artboard, pageId: AD_PAGE_ID, scene, selectedNodeId: node.id, viewport,
    preview: { nodeId: node.id, box: { x: 100 * scale, y: 100 * scale, width: 300 * scale, height: 120 * scale }, rotation: 0 } as never,
  });
  assert.equal(previewed?.frame, null);
  assert.equal(previewed?.width, plain?.width);
});

test("Plan 4: handles sit on whatever box they are asked for", () => {
  const rects = selectionHandleRects({ x: 10, y: 20, width: 100, height: 50 });
  assert.equal(rects.length, 4);
  assert.deepEqual(rects.map((r) => [r.x + r.size / 2, r.y + r.size / 2]), [[10, 20], [110, 20], [10, 70], [110, 70]]);
});
```

(Read `ScenePreview`'s shape in `scene-canvas-view.ts` and build the preview literal to it instead of the `as never` cast if the fields differ.)

Existing `sceneSelectionOutline` deep-equal assertions in this file gain `frame: null`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/adapter/scene-canvas-view.test.ts 2>&1 | tail -15`
Expected: the four new tests fail (no `sceneTextPaintedBox`, no `frame`).

- [ ] **Step 3: Implement**

`scene-canvas-view.ts`:

```ts
/** Plan 4 item F: the layout box may differ from the painted box by taffy's
 * whole-pixel rounding (a hug box sits up to half a pixel under the measured
 * height — `layout.rs` ROUNDING_TOLERANCE); only a larger difference is a
 * fixed size worth a frame. Scene units. */
const TEXT_FRAME_TOLERANCE = 0.5;

/**
 * The union of a text node's PAINTED line boxes (page space, unrotated — the
 * frame `layout_bounds` is in), or null when the node is not text or carries
 * no positive-area line (a stored scene, an engine that predates the lines, an
 * empty string). This is what a text selection outlines: the glyphs, not the
 * box the author typed.
 */
export function sceneTextPaintedBox(node: Node): Box | null { /* as designed: filter width>0 && height>0, min/max fold */ }

export function sceneTextFrameDiffers(layout: Box, painted: Box): boolean {
  return (
    Math.abs(layout.x - painted.x) > TEXT_FRAME_TOLERANCE ||
    Math.abs(layout.y - painted.y) > TEXT_FRAME_TOLERANCE ||
    Math.abs(layout.x + layout.width - (painted.x + painted.width)) > TEXT_FRAME_TOLERANCE ||
    Math.abs(layout.y + layout.height - (painted.y + painted.height)) > TEXT_FRAME_TOLERANCE
  );
}
```

`SceneSelectionOutline` gains:

```ts
  /** Plan 4 item F: for a text node whose layout box differs from its painted
   * lines, the layout box — drawn dashed, and where the resize handles sit
   * (a resize changes the BOX). Null for every other selection, for a hug box,
   * and during a gesture preview (the preview IS the box). Screen px, like
   * the outline itself; rotation pivots on its origin when present. */
  frame: { x: number; y: number; width: number; height: number } | null;
```

`selectionOutlineForBox` returns `frame: null`. In `sceneSelectionOutline`, after the preview branch and the `selectionBox` null check:

```ts
  const node = scene.nodes[selectedNodeId];
  const painted = node ? sceneTextPaintedBox(node) : null;
  if (!painted) {
    return selectionOutlineForBox({ artboard, box: selectionBox.box, nodeId: selectionBox.nodeId, rotation: selectionBox.rotation, viewport });
  }
  const outline = selectionOutlineForBox({ artboard, box: painted, nodeId: selectionBox.nodeId, rotation: selectionBox.rotation, viewport });
  if (!outline) {
    return null;
  }
  const frame = sceneTextFrameDiffers(selectionBox.box, painted)
    ? selectionOutlineForBox({ artboard, box: selectionBox.box, nodeId: selectionBox.nodeId, rotation: selectionBox.rotation, viewport })
    : null;
  return { ...outline, frame: frame ? { x: frame.x, y: frame.y, width: frame.width, height: frame.height } : null };
```

`selectionHandleRects(box: { x: number; y: number; width: number; height: number })` — same body, parameter widened. Update its docblock: the caller passes the frame when there is one.

`scene-artifact-canvas.tsx` `SelectionChrome`: `const pivot = outline.frame ?? outline;` — the `<g transform>` rotates about `pivot.x, pivot.y`; after the solid `<rect>`, when `outline.frame && !hover`:

```tsx
        {outline.frame && !hover ? (
          // Plan 4 item F: the layout box of a text node whose painted lines
          // do not fill it — dashed, so the eye reads "the box you can
          // resize" apart from "the text you selected". Never on hover.
          <rect
            data-scene-selection-frame={outline.nodeId}
            fill="none"
            height={outline.frame.height}
            stroke={SELECTION_OUTLINE_COLOR}
            strokeDasharray="4 3"
            strokeWidth={HOVER_OUTLINE_WIDTH}
            width={outline.frame.width}
            x={outline.frame.x}
            y={outline.frame.y}
          />
        ) : null}
```

and handles from `selectionHandleRects(outline.frame ?? outline)`. Extend the component docblock (Plan 4 paragraph). The hover memo needs no change: it calls `sceneSelectionOutline`, and the hover variant ignores `frame`.

- [ ] **Step 4: Run the tests, lint and the full frontend suite**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/adapter/scene-canvas-view.test.ts 2>&1 | tail -8; npm run lint 2>&1 | tail -4; npm test 2>&1 | tail -6`
Expected: all pass; lint clean.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/design-editor
git commit -m "feat(design-editor): a text selection outlines its painted lines; a fixed box keeps a dashed frame

The outline was the layout box, so an oversized fixed text box outlined empty
space. It is now the union of the engine's painted line boxes; when the layout
box differs, a dashed frame marks it and carries the resize handles. Hover uses
the same lines and never a frame. Plan 4 item F, step 5."
```

---

### Task 7: "Fit to text"

**Files:**
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-apply.ts` (new case after `heightMode`, ~line 1125)
- Modify: `apps/frontend/src/features/chat-shell/components/image-inspector.tsx` (`AdTextInspector` Layout section, after the Rotation row ~line 420; import `dispatchInspectorEvent` from `../hooks/use-inspector-controller`)
- Modify: `apps/frontend/src/features/chat-shell/hooks/use-inspector-controller.ts` (the `dispatchInspectorEvent` docblock, ~line 302)
- Test: `apps/frontend/src/features/design-editor/adapter/scene-apply.test.ts`

**Interfaces:**
- Produces: property `"fitToText"` on the `clue:inspector-property-change` event (any value); one `UpdateNode` size operation.

- [ ] **Step 1: Write the failing tests** (`scene-apply.test.ts`, next to the size-mode tests; use the file's existing text fixture — `adSpannedText().node` or whichever fixture is a text node with a fixed height; if none has a fixed height, clone one and set `size.height = { kind: "fixed", value: 216 }`)

```ts
// ══ Plan 4 item F: "Fit to text" ═══════════════════════════════════════════

it("Plan 4 Fit to text: a fixed-height text box flips its height to hug, width untouched", () => {
  const { node, scene } = adSpannedText();
  const fixed = { ...node, size: { width: { kind: "fixed" as const, value: 504 }, height: { kind: "fixed" as const, value: 216 } } };
  assert.deepEqual(
    apply(fixed, "fitToText", "1", scene),
    updateNode(fixed.id, {
      size: set({
        height: { kind: "hug" },
        width: { kind: "fixed", value: 504 },
      }),
    }),
  );
});

it("Plan 4 Fit to text: a hugging text box writes nothing; a non-text node writes nothing", () => {
  const { node, scene } = adSpannedText();
  const hugging = { ...node, size: { ...node.size, height: { kind: "hug" as const } } };
  assert.equal(apply(hugging, "fitToText", "1", scene), null);
  assert.equal(apply(adRect(), "fitToText", "1"), null);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/adapter/scene-apply.test.ts 2>&1 | grep -E "Fit to text|^# (pass|fail)"`
Expected: the first test fails (null returned).

- [ ] **Step 3: Implement**

`scene-apply.ts`, after the `widthMode`/`heightMode` case:

```ts
    // ── Plan 4 item F: "Fit to text" — the text box hugs its copy ────────────
    // ONE write, one document version: the height flips to hug (the authoring
    // default Plan 4 restores) and nothing else moves. Width is deliberately
    // untouched — a fixed width is the wrap width the author chose. The value
    // is not read; the button carries "1" for the event's sake only.
    case "fitToText": {
      if (!text || node.size.height.kind === "hug") {
        return null;
      }
      return updateNodeSize(node, { ...node.size, height: { kind: "hug" } });
    }
```

Also add `"fitToText"` to the file's header list of handled properties if it keeps one.

`image-inspector.tsx`, in `AdTextInspector`'s Layout section after the Rotation row:

```tsx
        {/* Plan 4 item F: the one-click way out of a fixed height the copy
            outgrew (the selection then outlines the glyphs and drops its
            dashed frame). One property-change event, one write — two
            `setValue` calls would be two document versions and the second
            can be dropped by the one-in-flight write discipline. Dead while
            the box already hugs. */}
        <InspectorField label="Text box">
          <button
            className={styles.sharePrimaryButtonWide}
            disabled={inert || state.heightMode === "Hug"}
            onClick={() => {
              if (inspectorDisabled || locked) return;
              dispatchInspectorEvent(
                "clue:inspector-property-change",
                { property: "fitToText", selectionType: "text", value: "1" },
                addressing,
              );
            }}
            type="button"
          >
            Fit to text
          </button>
        </InspectorField>
```

`use-inspector-controller.ts`: amend the `dispatchInspectorEvent` docblock — "Exported for the addressing unit test and for the ad text inspector's Fit-to-text button (a one-shot property change with no state key of its own); every other production caller goes through the controller hooks."

- [ ] **Step 4: Run the tests, lint and the full frontend suite**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/adapter/scene-apply.test.ts 2>&1 | tail -4; npm run lint 2>&1 | tail -4; npm test 2>&1 | tail -6`
Expected: all pass; lint clean.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/design-editor/adapter/scene-apply.ts apps/frontend/src/features/design-editor/adapter/scene-apply.test.ts apps/frontend/src/features/chat-shell/components/image-inspector.tsx apps/frontend/src/features/chat-shell/hooks/use-inspector-controller.ts
git commit -m "feat(design-editor): Fit to text flips a fixed text height to hug in one write

Existing fixed boxes are never migrated silently; the text inspector's Layout
section gains a button that writes height=hug (width untouched) through one
property-change event. Plan 4 item F, authoring action."
```

---

### Task 8: Full gate, rebuilds, restart, live proof (controller)

**Files:** none new; evidence under `/tmp/plan4-evidence-keep/`.

- [ ] **Step 1: Rust workspace gate** — `cd subsystems/clue-design && cargo test --workspace 2>&1 | tail -20` (background; several minutes). Zero failures.
- [ ] **Step 2: API helper** — `cargo build -p lumen-api-helper --release 2>&1 | tail -3`.
- [ ] **Step 3: wasm** — `npm --prefix subsystems/clue-design/apps/editor run build:wasm 2>&1 | tail -5`, then `cd apps/frontend && node scripts/copy-design-vendor.mjs 2>&1 | tail -3`. The editor's own wasm-backed tests: `npm --prefix subsystems/clue-design/apps/editor test -- src/engine 2>&1 | tail -6` (they skip without the artifact; with it, zero failures — a text hit-test expectation that changed is analyzed, never weakened).
- [ ] **Step 4: Python gates** — `pytest apps/agent_runtime/tests -q` and, in the background against `clue_plan1_test`, `pytest apps/api/tests -q` (both with the plan's env recipe).
- [ ] **Step 5: Restart the design API and the fleet worker** by reproducing their `.env` (per `_memory` and the Claude memory note; never `pkill` — istanbul shares the box). Confirm the editor handshake: `curl -s localhost:8052/build_info` (or the API's build-info route) reports the same `engine_commit` as `apps/frontend/public/wasm/lumen_wasm.js` embeds.
- [ ] **Step 6: Live proof** (gstack `/browse`, Apollo ad `doc_cf05190c…`, Edit mode, hard reload so the new wasm loads): (a) click the empty half of the old headline box → the wash behind it is selected (read `data-scene-selection-outline`); (b) click the "x" glyph → `x` selected, its outline hugging the glyph with a dashed frame on the 326×71 box (`data-scene-selection-frame`); (c) hover over the headline → the hover outline is the text, not the box; (d) select the headline, press "Fit to text" in the inspector → the document version advances by one, the height mode reads Hug, the dashed frame disappears; (e) the Brex ad's CTA (Plan 3's proof node) still resolves as before. Screenshots into `/tmp/plan4-evidence-keep/`.
- [ ] **Step 7: Roadmap + memo** — tick Plan 4 item F in `docs/superpowers/plans/2026-09-04-editor-quality-roadmap.md`; write `_memory/2026-09-04-plan4-text-bounds.md` (what changed, rulings R1–R7, live-proof evidence, open items), delete `.superpowers/sdd/plan4/progress.md`, commit.

---

### Task 9: Item G — the founder preview (no controls land)

**Files:**
- Create: `docs/superpowers/previews/2026-09-04-typography-rows/index.html` (self-contained: inline CSS copied from the inspector's real class values, inline SVG icons)
- Create: `docs/superpowers/previews/2026-09-04-typography-rows/ICONS.md` (the source table)

**Interfaces:** none (a static page the controller screenshots for the founder).

- [ ] **Step 1: Read the real panel** — `apps/frontend/src/features/chat-shell/components/image-inspector.tsx` (`AdTextInspector`, the Typography section ~line 381–408), `inspector-primitives.tsx` (`InspectorField`, `InspectorSelect`, `InspectorInput`, `InspectorIcon` and the local icon vocabulary at `/public/icons/chat-shell/inspector/`), and the CSS classes those primitives use in `chat-shell.module.css` (field grid, label, input, select, alignment control). The preview must look like the panel, not like a mock-up: same widths, fonts, colours, radii, the same row order with the existing rows (Text, Color, Font, Size/Weight, Alignment) in place and the new rows after them.
- [ ] **Step 2: Compose the rows** (one static HTML page, 260px-wide panel column, dark and light not needed — match whatever the panel renders today): **Line height** (number input with a 0.05-step spinner, value `1.04`, suffix `×`), **Letter spacing** (number input, value `0`, suffix `em`), **Vertical alignment** (note in the page: this row ALREADY EXISTS in the shipped panel — the `TextAlignment` control's second group — and is shown for context only), **Max lines** (number input, value `2`) beside **Wrap** (toggle, on), **Resize** (a three-way segmented control: Auto width / Auto height / Fixed, mirroring width-hug / height-hug / fixed). Each row gets an icon in the label position, sized 12px like the panel's other icons.
- [ ] **Step 3: Icons and sources** — for every icon: prefer an icon that ALREADY exists in `/public/icons/chat-shell/inspector/` (list it as "vendored: yes"); otherwise take it from `lucide-react` (`apps/frontend/node_modules/lucide-react/dist/esm/icons/<name>.mjs` exports the node list; reconstruct the SVG at 24×24, stroke 2, round caps/joins) and list it as "vendored: no — would be added as `<name>.svg` in the inspector icon folder in the existing align-* export style". Record in `ICONS.md` a table: row · icon name · library (lucide-react version from `package.json`, licence ISC; or "inspector local set") · file path · vendored? · rationale. Candidate lucide names to evaluate: `unfold-vertical` / `align-vertical-space-around` (line height), `space` / `arrow-left-right` / `move-horizontal` (letter spacing; `move-horizontal` is local), `wrap-text` (wrap), `list-ordered` / `rows-3` (max lines), `scan` / `square-dashed` / `move-vertical` (resize; all three local). Do not invent glyphs.
- [ ] **Step 4: Report** — the final message lists the two files, each row with its icon and source, and anything the implementer could not match to the real panel's CSS (say so rather than approximating silently). No commit of frontend code; the controller commits the preview folder after screenshotting it.

---

## Self-review

- **Spec coverage.** Item F (1) engine lines + hit test: Tasks 1–3; (2) canvas outline union + dashed frame: Task 6 (the editor's lines being CanvasKit's: Task 5); (3) authoring default hug in DSL and skill, Fit-to-text, no silent migration: Tasks 4 and 7. Tests named in the roadmap (Rust oversized-box miss/hit, canvas outline bounds, DSL default) are Tasks 2, 6, 4. Live proof (empty half of the headline → wash; the "x" glyph → "x"): Task 8. Item G preview gate: Task 9; no control lands.
- **Placeholders.** None: every code step carries the code; Task 5's `measureLinesAtWidth` names the exact painter code to mirror and the exact metric fields.
- **Type consistency.** `ComputedGeometry.text_lines: Vec<Rect>` (Rust) ↔ `text_lines?: Rect[]` (TS); `ProvidedLine`/`ProvidedMetrics` (core) ↔ `ProvidedMeasurementLine` (wasm payload) ↔ `TextMeasurementLine` (TS); `SceneSelectionOutline.frame` consumed by `SelectionChrome` and `selectionHandleRects`; `"fitToText"` property string shared by the button and the apply case.
