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

use crate::ids::{NodeId, PageId};
use crate::render_geometry::render_box_for_node;
use crate::scene::{Node, NodeKind, Scene};

/// Extra pick slop (scene units) added to a line's stroke half-width so thin
/// lines remain clickable. V0 constant; the editor may widen it by zoom.
const LINE_PICK_SLOP: f64 = 2.0;

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
    }
    out
}

fn collect(scene: &Scene, node_id: &NodeId, x: f64, y: f64, out: &mut Vec<NodeId>) {
    let Some(node) = scene.nodes.get(node_id) else {
        return;
    };
    let inside = point_in_node(node, x, y);
    // A clipped container hides anything outside its own box: if the point is
    // outside, neither it nor its clipped descendants can be hit.
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
        NodeKind::Line(line) => {
            point_near_segment(lx, ly, line.x2, line.y2, line_tolerance(node))
        }
        // Rect/frame/group/auto-layout/text/image/vector/instance: the rotated
        // box. (Vector path-fill is a V0 follow-up — the box is the hit shape.)
        _ => b.width > 0.0 && b.height > 0.0 && lx >= 0.0 && lx <= b.width && ly >= 0.0 && ly <= b.height,
    }
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
