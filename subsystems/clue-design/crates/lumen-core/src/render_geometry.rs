use crate::{Dimension, Node};

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RenderBox {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
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
