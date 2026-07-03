use crate::ids::NodeId;
use crate::scene::{Page, PositionMode, Scene};
use crate::{Dimension, Node};

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RenderBox {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

/// Phase 1d freehand render policy (user decision 2026-07-03, from the Moda
/// reference: containers never mask, only the page clips). A pinned node
/// paints OUT of its ancestors' paint tree: renderers skip it inline and
/// paint it in a page-level pass above the in-flow content, so it escapes
/// every ancestor mask and is clipped only by the page itself. Managed
/// content keeps ancestor clip semantics everywhere.
pub fn paints_out_of_tree(node: &Node) -> bool {
    node.position_mode == PositionMode::Absolute
}

/// Every pinned node under `page`, in document paint order — the page-level
/// second pass. Pinned nodes nested under other pinned nodes are collected
/// too: inline painting skips pinned children at every level, and each
/// pinned node's `computed` geometry is page-space, so each paints from the
/// page origin independently.
pub fn pinned_paint_pass(scene: &Scene, page: &Page) -> Vec<NodeId> {
    let mut pass = Vec::new();
    for child_id in &page.children {
        collect_pinned(scene, child_id, &mut pass);
    }
    pass
}

fn collect_pinned(scene: &Scene, node_id: &NodeId, pass: &mut Vec<NodeId>) {
    let Some(node) = scene.nodes.get(node_id) else {
        return;
    };
    if paints_out_of_tree(node) {
        pass.push(node_id.clone());
    }
    for child_id in &node.children {
        collect_pinned(scene, child_id, pass);
    }
}

pub fn node_render_size(node: &Node) -> (f64, f64) {
    if let Some(computed) = &node.computed {
        return (computed.layout_bounds.width, computed.layout_bounds.height);
    }

    (
        dimension_value(&node.size.width),
        dimension_value(&node.size.height),
    )
}

pub fn render_box_for_node(node: &Node, parent_computed_origin: Option<(f64, f64)>) -> RenderBox {
    if let Some(computed) = &node.computed {
        let mut x = computed.layout_bounds.x;
        let mut y = computed.layout_bounds.y;
        if let Some((parent_x, parent_y)) = parent_computed_origin {
            x -= parent_x;
            y -= parent_y;
        }
        return RenderBox {
            x,
            y,
            width: computed.layout_bounds.width,
            height: computed.layout_bounds.height,
        };
    }

    let (width, height) = node_render_size(node);
    RenderBox {
        x: node.transform.x,
        y: node.transform.y,
        width,
        height,
    }
}

fn dimension_value(dimension: &Dimension) -> f64 {
    match dimension {
        Dimension::Fixed(value) => *value,
        Dimension::Hug | Dimension::Fill { .. } | Dimension::Token { .. } => 0.0,
    }
}
