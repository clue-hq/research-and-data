//! Point→node hit-testing over rendered geometry (Wave 3 C3a).
//!
//! The editor's interaction layer (and the agent) needs to know which node is
//! under a pointer. This is geometry over `computed` — the single coherent
//! source the coordinate-model fix keeps fresh, and the SAME boxes the renderer
//! draws (`render_box_for_node`). Keeping it in the core makes it consistent
//! across renderers (Konva today, CanvasKit in Wave 3), reusable by the agent,
//! and testable against the exact geometry the renderer uses.
//!
//! Points and results are in absolute page space (scene units). Rotation is
//! honored (about the node's top-left origin, as the renderer rotates it);
//! skew/flip are V0 follow-ups, as is alpha-accurate raster and true vector
//! path-fill hit-testing (V0 uses the rotated box for vectors).
//!
//! Text is the one kind that does NOT hit-test its box (Editor Quality Plan 4,
//! item F): a text node with painted line boxes in `computed.text_lines` hits
//! by those lines, so an oversized box steals no clicks and a glyph painted
//! past the box is still clickable.

use crate::ids::{NodeId, PageId};
use crate::render_geometry::{
    paints_out_of_tree, pinned_paint_pass, render_box_for_node, RenderBox,
};
use crate::scene::{ComputedGeometry, Node, NodeKind, Rect, Scene};

/// Extra pick slop (scene units) added to a line's stroke half-width so thin
/// lines remain clickable. V0 constant; the editor may widen it by zoom.
const LINE_PICK_SLOP: f64 = 2.0;

/// Plan 4 item F: pick slop (scene units) around a painted text line, so a
/// click on a descender or a hair past a line's edge still lands on the text.
const TEXT_LINE_PICK_SLOP: f64 = 2.0;

/// The topmost node under `(x, y)` on `page_id`, or `None`. This is the
/// single-click target (deepest-first selection); the editor walks up from it
/// (`topLevelAncestorId`) for double-click container targeting.
pub fn hit_test(scene: &Scene, page_id: &PageId, x: f64, y: f64) -> Option<NodeId> {
    let mut stack = hit_stack(scene, page_id, x, y);
    stack.pop()
}

/// Every node under `(x, y)` on `page_id`, in paint order (bottom-to-top, so
/// `.last()` is the topmost hit). Drill-in / cycle-through-overlapping walk
/// this stack.
pub fn hit_stack(scene: &Scene, page_id: &PageId, x: f64, y: f64) -> Vec<NodeId> {
    let mut out = Vec::new();
    if let Some(page) = scene.pages.get(page_id) {
        for child in &page.children {
            collect(scene, child, x, y, &mut out);
        }
        // Phase 1d freehand: pinned nodes paint in a page-level pass above
        // the in-flow content (see `pinned_paint_pass`), so they hit-test
        // last — clicking where a pinned node overlaps in-flow content
        // selects the pinned node, matching what the renderers put on top.
        for pinned_id in pinned_paint_pass(scene, page) {
            if let Some(node) = scene.nodes.get(&pinned_id) {
                collect_in_paint_tree(scene, node, &pinned_id, x, y, &mut out);
            }
        }
    }
    out
}

fn collect(scene: &Scene, node_id: &NodeId, x: f64, y: f64, out: &mut Vec<NodeId>) {
    let Some(node) = scene.nodes.get(node_id) else {
        return;
    };
    // Pinned nodes are skipped inline exactly like the renderers skip them;
    // the page-level pass in `hit_stack` records them on top.
    if paints_out_of_tree(node) {
        return;
    }
    collect_in_paint_tree(scene, node, node_id, x, y, out);
}

fn collect_in_paint_tree(
    scene: &Scene,
    node: &Node,
    node_id: &NodeId,
    x: f64,
    y: f64,
    out: &mut Vec<NodeId>,
) {
    let inside = point_in_node(node, x, y);
    // A clipped container hides anything outside its own box: if the point is
    // outside, neither it nor its clipped descendants can be hit. (A pinned
    // node escapes its ANCESTORS' clips via the page-level pass, but still
    // masks its own managed children when it clips.)
    if node.clip && !inside {
        return;
    }
    // Paint order: the parent draws before its children, so push it first; the
    // node's own hit is recorded only when the point is inside it.
    if inside {
        out.push(node_id.clone());
    }
    // Children paint on top and (unless clipped) may extend beyond the parent,
    // so recurse regardless of whether the parent was hit.
    for child in &node.children {
        collect(scene, child, x, y, out);
    }
}

fn point_in_node(node: &Node, x: f64, y: f64) -> bool {
    let b = render_box_for_node(node, None);
    // Map the query point into the node's local frame: translate by -origin,
    // then undo the node's rotation about that origin.
    let (lx, ly) = to_local(x - b.x, y - b.y, node.transform.rotation);
    match &node.kind {
        NodeKind::Ellipse => point_in_ellipse(lx, ly, b.width, b.height),
        NodeKind::Line(line) => point_near_segment(lx, ly, line.x2, line.y2, line_tolerance(node)),
        // Plan 4 item F: text hit-tests against its PAINTED line boxes, never
        // its layout box — an oversized fixed box must not steal clicks from
        // what lies behind its empty area, and a glyph painted past the box
        // (a fixed height the copy outgrew) must still be clickable. The boxes
        // are page-space in `layout_bounds`' frame, so they share the node's
        // origin shift and rotation (`to_local` above). A node without
        // positive-area lines keeps the box test below.
        NodeKind::Text(_) if has_painted_lines(node) => point_in_text_lines(node, &b, lx, ly),
        // Rect/frame/group/auto-layout/text/image/vector/instance: the rotated
        // box. (Vector path-fill is a V0 follow-up — the box is the hit shape.)
        _ => {
            b.width > 0.0
                && b.height > 0.0
                && lx >= 0.0
                && lx <= b.width
                && ly >= 0.0
                && ly <= b.height
        }
    }
}

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

/// Rotate `(px, py)` by `-rotation_deg` (degrees), i.e. into the node's local,
/// unrotated frame.
fn to_local(px: f64, py: f64, rotation_deg: f64) -> (f64, f64) {
    if rotation_deg == 0.0 {
        return (px, py);
    }
    let rad = -rotation_deg.to_radians();
    let (s, c) = rad.sin_cos();
    (px * c - py * s, px * s + py * c)
}

fn point_in_ellipse(lx: f64, ly: f64, width: f64, height: f64) -> bool {
    if width <= 0.0 || height <= 0.0 {
        return false;
    }
    let rx = width / 2.0;
    let ry = height / 2.0;
    let nx = (lx - rx) / rx;
    let ny = (ly - ry) / ry;
    nx * nx + ny * ny <= 1.0
}

/// Distance from the local point to the segment `(0,0)-(x2,y2)` within `tol`.
fn point_near_segment(px: f64, py: f64, x2: f64, y2: f64, tol: f64) -> bool {
    let len_sq = x2 * x2 + y2 * y2;
    let t = if len_sq == 0.0 {
        0.0
    } else {
        ((px * x2 + py * y2) / len_sq).clamp(0.0, 1.0)
    };
    let cx = t * x2;
    let cy = t * y2;
    let dx = px - cx;
    let dy = py - cy;
    (dx * dx + dy * dy).sqrt() <= tol
}

fn line_tolerance(node: &Node) -> f64 {
    let half_stroke = node.strokes.first().map(|s| s.width).unwrap_or(1.0) / 2.0;
    half_stroke + LINE_PICK_SLOP
}
