use crate::diagnostics::{Diagnostic, DiagnosticSeverity, DiagnosticSubject, Phase};
use crate::ids::{NodeId, PageId};
use crate::operations::{NodePatch, Operation, OptionalFieldPatch};
use crate::page_geometry::page_geometry;
use crate::scene::{
    valign_offset, AutoLayoutDirection, ComputedGeometry, Dimension, LayoutAnchor, LayoutMode,
    Node, NodeKind, PositionMode, Rect, Scene, SizeSpec, TextAlign, TextNode, TextWrap,
};
use crate::slots::{ContentType, EmptyBehavior, ImagePolicy, OverflowPolicy, ReflowPolicy, Slot};
use crate::text_measure::{
    HeuristicTextMeasurer, SharedTextMeasurer, TextMeasureInput, TextMeasureOutput, TextMeasurer,
};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use taffy::geometry::{Rect as TaffyRect, Size as TaffySize};
use taffy::prelude::{
    auto, length, percent, AlignContent, AlignItems, AvailableSpace, Display,
    FlexDirection as TaffyFlexDirection, FlexWrap, JustifyContent, Style, TaffyTree,
};
use taffy::style::Dimension as TaffyDimension;
use taffy::tree::NodeId as TaffyNodeId;

#[derive(Clone)]
pub struct LayoutOptions {
    pub validate_slots: bool,
    /// Injected text measurer (Decision 5, Wave 1 Track A). `None` falls
    /// back to [`HeuristicTextMeasurer`], preserving wasm builds and
    /// pre-injection behavior. Server paths inject the Skia measurer here
    /// through the api helper.
    pub measurer: Option<SharedTextMeasurer>,
}

impl Default for LayoutOptions {
    fn default() -> Self {
        Self {
            validate_slots: true,
            measurer: None,
        }
    }
}

impl std::fmt::Debug for LayoutOptions {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("LayoutOptions")
            .field("validate_slots", &self.validate_slots)
            .field("has_measurer", &self.measurer.is_some())
            .finish()
    }
}

impl PartialEq for LayoutOptions {
    fn eq(&self, other: &Self) -> bool {
        // Measurers compare by identity: equal when both are absent or both
        // point at the same injected instance.
        self.validate_slots == other.validate_slots
            && match (&self.measurer, &other.measurer) {
                (None, None) => true,
                (Some(left), Some(right)) => Arc::ptr_eq(left, right),
                _ => false,
            }
    }
}

static FALLBACK_MEASURER: HeuristicTextMeasurer = HeuristicTextMeasurer;

#[derive(Clone, Debug, PartialEq)]
pub struct LayoutResult {
    pub geometry: BTreeMap<NodeId, ComputedGeometry>,
    pub diagnostics: Vec<Diagnostic>,
}

pub fn layout_scene(scene: &Scene, options: LayoutOptions) -> LayoutResult {
    let measurer: &dyn TextMeasurer = options
        .measurer
        .as_deref()
        .map(|measurer| measurer as &dyn TextMeasurer)
        .unwrap_or(&FALLBACK_MEASURER);
    let mut engine = LayoutEngine::new(scene, measurer);
    // Loud, never-silent signal that this pass measured text without font
    // shaping (LUMS0102): the heuristic measurer approximates glyph advances,
    // so every text box, wrap, and overflow verdict below is geometry-
    // approximate. Server paths inject a shaping (Skia) measurer, so they
    // report `shaping() == true` and never emit this. Modeled on LUMS0101's
    // "degraded but never silent" pattern.
    if !measurer.shaping() {
        engine
            .diagnostics
            .push(crate::text_measure::heuristic_measurement_diagnostic());
    }
    engine.layout_pages();
    engine.validate_artboard_bounds();
    engine.validate_layout_anchors();
    engine.validate_text_nodes();

    if options.validate_slots {
        engine.validate_slots();
    }

    LayoutResult {
        geometry: engine.geometry,
        diagnostics: engine.diagnostics,
    }
}

pub fn validate_layout(scene: &Scene, options: LayoutOptions) -> Vec<Diagnostic> {
    layout_scene(scene, options).diagnostics
}

pub fn layout_operations(scene: &Scene, options: LayoutOptions) -> Vec<Operation> {
    layout_scene(scene, options)
        .geometry
        .into_iter()
        .map(|(node_id, computed)| Operation::UpdateNode {
            node_id,
            patch: NodePatch {
                computed: OptionalFieldPatch::Set(computed),
                ..NodePatch::default()
            },
        })
        .collect()
}

struct LayoutEngine<'a> {
    scene: &'a Scene,
    measurer: &'a dyn TextMeasurer,
    geometry: BTreeMap<NodeId, ComputedGeometry>,
    diagnostics: Vec<Diagnostic>,
}

impl<'a> LayoutEngine<'a> {
    fn new(scene: &'a Scene, measurer: &'a dyn TextMeasurer) -> Self {
        Self {
            scene,
            measurer,
            geometry: BTreeMap::new(),
            diagnostics: Vec::new(),
        }
    }

    fn layout_pages(&mut self) {
        for page in self.scene.pages.values() {
            let geometry = page_geometry(page);
            let page_size = Size2 {
                width: geometry.layout.width,
                height: geometry.layout.height,
            };

            for child_id in &page.children {
                let Some(child) = self.scene.nodes.get(child_id) else {
                    continue;
                };
                let origin = Point2 {
                    x: child.transform.x,
                    y: child.transform.y,
                };
                self.layout_node_at(child_id, origin, page_size, &page.id);
            }
        }
    }

    fn layout_node_at(
        &mut self,
        node_id: &NodeId,
        origin: Point2,
        parent_size: Size2,
        page_id: &PageId,
    ) {
        let Some(node) = self.scene.nodes.get(node_id) else {
            return;
        };

        // Phase 1 freehand: a pinned node lays out at its page-space
        // absolute_box — `origin` (where the flow would have put it) is
        // ignored and the box is authoritative for both position and size.
        // An Absolute node without a box falls back to flow position, the
        // same treatment as a rotated out-of-flow child.
        let (origin, pinned_size) = match pinned_box(node) {
            Some(pin) => (
                Point2 { x: pin.x, y: pin.y },
                Some(Size2 {
                    width: pin.width,
                    height: pin.height,
                }),
            ),
            None => (origin, None),
        };

        // A Free container skips the flex solve entirely: it takes the
        // manual path below, so its children keep their own baked
        // transforms instead of being stacked.
        if matches!(node.kind, NodeKind::AutoLayout(_)) && !is_free_container(node) {
            self.layout_auto_node(node_id, origin, parent_size, page_id);
            return;
        }

        self.warn_unresolved_dimension_tokens(node_id);
        let size = pinned_size.unwrap_or_else(|| self.resolve_manual_size(node, parent_size));
        self.write_geometry(node, origin, size);

        // Free mode: `fill` = the padded CONTENT box, positions = the author's
        // transform relative to the OUTER origin (the freeze bakes them that
        // way). Resolving a child's fill against the outer box was the other
        // half of the 2026-09-20 defect: the same `fill × hug` row the Stack
        // solve gave the content width (976) jumped to the outer width (1080)
        // the moment its container was frozen to Free. Only an auto-layout
        // node carries `layout`, so a plain group/frame pads by zero and its
        // children see exactly what they saw before.
        let padding = node
            .layout
            .as_ref()
            .map(|layout| layout.padding)
            .unwrap_or([0.0; 4]);
        let content = Size2 {
            width: (size.width - padding[1] - padding[3]).max(0.0),
            height: (size.height - padding[0] - padding[2]).max(0.0),
        };

        for child_id in &node.children {
            let Some(child) = self.scene.nodes.get(child_id) else {
                continue;
            };
            self.layout_node_at(
                child_id,
                Point2 {
                    x: origin.x + child.transform.x,
                    y: origin.y + child.transform.y,
                },
                content,
                page_id,
            );
        }
    }

    fn layout_auto_node(
        &mut self,
        node_id: &NodeId,
        origin: Point2,
        parent_size: Size2,
        page_id: &PageId,
    ) {
        let mut tree: TaffyTree<MeasureContext> = TaffyTree::new();
        let mut map = TaffyMap::default();

        let root =
            match self.build_taffy_node(&mut tree, &mut map, node_id, Some(parent_size), None) {
                Ok(root) => root,
                Err(error) => {
                    self.diagnostics.push(Diagnostic::error(
                        Phase::Layout,
                        "LUMV0700",
                        format!("failed to build layout tree for {}: {}", node_id, error),
                        Some(DiagnosticSubject::Node(node_id.clone())),
                    ));
                    return;
                }
            };

        let available_space = TaffySize {
            width: AvailableSpace::Definite(parent_size.width as f32),
            height: AvailableSpace::Definite(parent_size.height as f32),
        };

        let measurer = self.measurer;
        if let Err(error) = tree.compute_layout_with_measure(
            root,
            available_space,
            |known_dimensions, available_space, _node_id, context, _style| {
                measure_taffy_node(known_dimensions, available_space, context, measurer)
            },
        ) {
            self.diagnostics.push(Diagnostic::error(
                Phase::Layout,
                "LUMV0700",
                format!("failed to compute layout for {}: {}", node_id, error),
                Some(DiagnosticSubject::Node(node_id.clone())),
            ));
            return;
        }

        self.collect_taffy_geometry(&tree, &map, root, origin, parent_size, page_id);
    }

    fn build_taffy_node(
        &mut self,
        tree: &mut TaffyTree<MeasureContext>,
        map: &mut TaffyMap,
        node_id: &NodeId,
        parent_size: Option<Size2>,
        parent_flow: Option<&FlowContext>,
    ) -> Result<TaffyNodeId, taffy::TaffyError> {
        self.warn_unresolved_dimension_tokens(node_id);
        let node = self.scene.nodes.get(node_id).expect("node exists");
        let style = self.style_for_node(node, parent_size, parent_flow);

        let taffy_id = if let (NodeKind::AutoLayout(auto), false) =
            (&node.kind, is_free_container(node))
        {
            let flow = self.flow_context(node, auto.direction.clone(), parent_size);
            let mut children = Vec::new();
            for child_id in &node.children {
                let Some(child) = self.scene.nodes.get(child_id) else {
                    continue;
                };

                // A pinned child leaves the flow deliberately — no
                // diagnostic, unlike rotation, which is accidental
                // out-of-flow. It lays out at its absolute_box through the
                // fallback pass in collect_taffy_geometry.
                if is_absolute(child) {
                    continue;
                }

                if is_out_of_flow_transform(child) {
                    self.diagnostics.push(
                        Diagnostic::warning(
                            Phase::Layout,
                            "LUMV0701",
                            format!(
                                "auto-layout child {} is rotated or skewed and was excluded from normal flow",
                                child_id
                            ),
                            Some(DiagnosticSubject::Node(child_id.clone())),
                        )
                        .with_hint(
                            "Transformed children keep their explicit transform; remove rotation/skew to participate in auto-layout.",
                        ),
                    );
                    continue;
                }

                children.push(self.build_taffy_node(tree, map, child_id, None, Some(&flow))?);
            }

            if children.is_empty() {
                tree.new_leaf_with_context(style, self.measure_context_for(node))?
            } else {
                tree.new_with_children(style, &children)?
            }
        } else {
            // Leaves — and Free containers, which join their parent's flow
            // as a plain box: their children stay out of the flex tree and
            // lay out at their own baked transforms through the fallback
            // pass in collect_taffy_geometry.
            tree.new_leaf_with_context(style, self.measure_context_for(node))?
        };

        map.by_lumen.insert(node_id.clone(), taffy_id);
        map.by_taffy.push((taffy_id, node_id.clone()));
        Ok(taffy_id)
    }

    fn collect_taffy_geometry(
        &mut self,
        tree: &TaffyTree<MeasureContext>,
        map: &TaffyMap,
        taffy_id: TaffyNodeId,
        parent_origin: Point2,
        parent_size: Size2,
        page_id: &PageId,
    ) {
        let Some((_, node_id)) = map
            .by_taffy
            .iter()
            .find(|(candidate, _)| *candidate == taffy_id)
        else {
            return;
        };
        let Some(node) = self.scene.nodes.get(node_id) else {
            return;
        };
        let Ok(layout) = tree.layout(taffy_id) else {
            return;
        };

        let origin = Point2 {
            x: parent_origin.x + f64::from(layout.location.x),
            y: parent_origin.y + f64::from(layout.location.y),
        };
        // A pinned node only enters a flex solve as its root (children of
        // the solve are never Absolute), with its style sized from the box;
        // write the exact f64 box back so `computed.layout_bounds` matches
        // `absolute_box` byte-for-byte instead of the f32-rounded solve.
        let size = match pinned_box(node) {
            Some(pin) => Size2 {
                width: pin.width,
                height: pin.height,
            },
            None => Size2 {
                width: f64::from(layout.size.width),
                height: f64::from(layout.size.height),
            },
        };
        self.write_geometry(node, origin, size);

        let Ok(children) = tree.children(taffy_id) else {
            return;
        };
        if matches!(node.kind, NodeKind::AutoLayout(_)) {
            for child_taffy_id in children {
                self.collect_taffy_geometry(tree, map, child_taffy_id, origin, size, page_id);
            }

            for child_id in &node.children {
                if map.by_lumen.contains_key(child_id) {
                    continue;
                }

                let Some(child) = self.scene.nodes.get(child_id) else {
                    continue;
                };
                self.layout_node_at(
                    child_id,
                    Point2 {
                        x: origin.x + child.transform.x,
                        y: origin.y + child.transform.y,
                    },
                    size,
                    page_id,
                );
            }
        } else {
            for child_id in &node.children {
                let Some(child) = self.scene.nodes.get(child_id) else {
                    continue;
                };
                self.layout_node_at(
                    child_id,
                    Point2 {
                        x: origin.x + child.transform.x,
                        y: origin.y + child.transform.y,
                    },
                    parent_size,
                    page_id,
                );
            }
        }
    }

    fn warn_unresolved_dimension_tokens(&mut self, node_id: &NodeId) {
        let tokens = self
            .scene
            .nodes
            .get(node_id)
            .map(|node| {
                [
                    (Axis::Horizontal, &node.size.width),
                    (Axis::Vertical, &node.size.height),
                ]
                .into_iter()
                .filter_map(|(axis, dimension)| {
                    if let Dimension::Token { token } = dimension {
                        Some((axis, token.clone()))
                    } else {
                        None
                    }
                })
                .collect::<Vec<_>>()
            })
            .unwrap_or_default();

        for (axis, token) in tokens {
            self.diagnostics.push(
                Diagnostic::warning(
                    Phase::Layout,
                    "LUMV0702",
                    format!(
                        "node {} uses unresolved brand token {} for {} size",
                        node_id,
                        token,
                        axis.label()
                    ),
                    Some(DiagnosticSubject::Node(node_id.clone())),
                )
                .with_hint(
                    "Run brand token resolution before layout for tokenized dimensions; unresolved token dimensions are laid out as hug/natural size.",
                ),
            );
        }
    }

    fn style_for_node(
        &self,
        node: &Node,
        parent_size: Option<Size2>,
        parent_flow: Option<&FlowContext>,
    ) -> Style {
        let mut style = Style {
            size: TaffySize {
                width: self.taffy_dimension_for_node(
                    node,
                    Axis::Horizontal,
                    parent_size,
                    parent_flow,
                ),
                height: self.taffy_dimension_for_node(
                    node,
                    Axis::Vertical,
                    parent_size,
                    parent_flow,
                ),
            },
            flex_shrink: 0.0,
            ..Style::default()
        };

        // A pinned node only ever enters a flex solve as its root
        // (build_taffy_node skips Absolute children), so its box is the
        // solve's fixed size regardless of the authored size spec.
        if let Some(pin) = pinned_box(node) {
            style.size = TaffySize {
                width: length(pin.width as f32),
                height: length(pin.height as f32),
            };
        }

        if let Some(flow) = parent_flow {
            match flow.direction {
                AutoLayoutDirection::Row => {
                    if let Dimension::Fill { weight } = node.size.width {
                        if !flow.fill_fallback_nodes.contains(&node.id) {
                            style.flex_grow = positive_f32(weight);
                        }
                    }
                }
                AutoLayoutDirection::Column => {
                    if let Dimension::Fill { weight } = node.size.height {
                        if !flow.fill_fallback_nodes.contains(&node.id) {
                            style.flex_grow = positive_f32(weight);
                        }
                    }
                }
            }
        }

        if let (NodeKind::AutoLayout(auto), Some(props)) = (&node.kind, node.layout.as_ref()) {
            style.display = Display::Flex;
            style.flex_direction = match auto.direction {
                AutoLayoutDirection::Row => TaffyFlexDirection::Row,
                AutoLayoutDirection::Column => TaffyFlexDirection::Column,
            };
            style.flex_wrap = if auto.wrap {
                FlexWrap::Wrap
            } else {
                FlexWrap::NoWrap
            };
            style.gap = TaffySize {
                width: length(props.gap as f32),
                height: length(props.gap as f32),
            };
            style.padding = TaffyRect {
                left: length(props.padding[3] as f32),
                right: length(props.padding[1] as f32),
                top: length(props.padding[0] as f32),
                bottom: length(props.padding[2] as f32),
            };
            match auto.direction {
                AutoLayoutDirection::Row => {
                    style.justify_content = Some(main_axis_alignment(&props.align_x));
                    style.align_items = Some(cross_axis_alignment(&props.align_y));
                    style.align_content = Some(cross_axis_content_alignment(&props.align_y));
                }
                AutoLayoutDirection::Column => {
                    style.justify_content = Some(main_axis_alignment(&props.align_y));
                    style.align_items = Some(cross_axis_alignment(&props.align_x));
                    style.align_content = Some(cross_axis_content_alignment(&props.align_x));
                }
            }
        }

        style
    }

    fn taffy_dimension_for_node(
        &self,
        node: &Node,
        axis: Axis,
        parent_size: Option<Size2>,
        parent_flow: Option<&FlowContext>,
    ) -> TaffyDimension {
        let dimension = match axis {
            Axis::Horizontal => &node.size.width,
            Axis::Vertical => &node.size.height,
        };

        match dimension {
            Dimension::Fixed(value) => length(*value as f32),
            Dimension::Hug => auto(),
            Dimension::Fill { .. } => {
                if let Some(flow) = parent_flow {
                    if flow.main_axis == axis {
                        auto()
                    } else if flow.cross_axis_has_definite_space {
                        percent(1.0)
                    } else {
                        auto()
                    }
                } else if let Some(parent_size) = parent_size {
                    length(axis.value(parent_size) as f32)
                } else {
                    auto()
                }
            }
            Dimension::Token { .. } => auto(),
        }
    }

    fn flow_context(
        &self,
        node: &Node,
        direction: AutoLayoutDirection,
        parent_size: Option<Size2>,
    ) -> FlowContext {
        let props = node.layout.as_ref();
        let padding = props.map(|layout| layout.padding).unwrap_or([0.0; 4]);
        let gap = props.map(|layout| layout.gap).unwrap_or(0.0);
        let main_axis = match direction {
            AutoLayoutDirection::Row => Axis::Horizontal,
            AutoLayoutDirection::Column => Axis::Vertical,
        };
        let cross_axis = main_axis.cross();
        let main_content = self.content_size_for_axis(node, main_axis, parent_size, padding);
        let cross_axis_has_definite_space = self
            .content_size_for_axis(node, cross_axis, parent_size, padding)
            .is_some_and(|size| size > 0.0);

        let normal_children = node
            .children
            .iter()
            .filter_map(|child_id| {
                self.scene
                    .nodes
                    .get(child_id)
                    .map(|child| (child_id, child))
            })
            .filter(|(_, child)| !is_out_of_flow_transform(child) && !is_absolute(child))
            .collect::<Vec<_>>();

        let mut fill_nodes = BTreeSet::new();
        for (child_id, child) in &normal_children {
            if matches!(main_axis.dimension(&child.size), Dimension::Fill { .. }) {
                fill_nodes.insert((*child_id).clone());
            }
        }

        let mut fill_fallback_nodes = BTreeSet::new();
        if !fill_nodes.is_empty() {
            match main_content {
                None => fill_fallback_nodes.extend(fill_nodes.iter().cloned()),
                Some(main_content) => {
                    let fixed_count = normal_children.len().saturating_sub(1);
                    let gap_total = gap * fixed_count as f64;
                    let used = normal_children
                        .iter()
                        .filter(|(child_id, _)| !fill_nodes.contains(*child_id))
                        .map(|(_, child)| self.natural_size_for_axis(child, main_axis))
                        .sum::<f64>();

                    if main_content - gap_total - used <= 0.0 {
                        fill_fallback_nodes.extend(fill_nodes.iter().cloned());
                    }
                }
            }
        }

        FlowContext {
            direction,
            main_axis,
            fill_fallback_nodes,
            cross_axis_has_definite_space,
        }
    }

    fn content_size_for_axis(
        &self,
        node: &Node,
        axis: Axis,
        parent_size: Option<Size2>,
        padding: [f64; 4],
    ) -> Option<f64> {
        let outer = match axis.dimension(&node.size) {
            Dimension::Fixed(value) => Some(*value),
            Dimension::Fill { .. } => parent_size.map(|size| axis.value(size)),
            Dimension::Hug | Dimension::Token { .. } => None,
        }?;

        let padding_sum = match axis {
            Axis::Horizontal => padding[1] + padding[3],
            Axis::Vertical => padding[0] + padding[2],
        };
        Some((outer - padding_sum).max(0.0))
    }

    fn natural_size_for_axis(&self, node: &Node, axis: Axis) -> f64 {
        match axis.dimension(&node.size) {
            Dimension::Fixed(value) => *value,
            Dimension::Hug | Dimension::Fill { .. } | Dimension::Token { .. } => {
                axis.value(self.natural_size(node))
            }
        }
    }

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
                let mut input = TextMeasureInput::from_text_node(text).for_node(&node.id);
                input.max_width = Some(width.max(0.0));
                self.measurer.measure(&input).height
            }
            _ => self.natural_size(node).height,
        }
    }

    fn natural_size(&self, node: &Node) -> Size2 {
        match &node.kind {
            NodeKind::Text(text) => {
                let measured = self
                    .measurer
                    .measure(&TextMeasureInput::from_text_node(text).for_node(&node.id));
                Size2 {
                    width: measured.width,
                    height: measured.height,
                }
            }
            NodeKind::Image(_) => fixed_or_zero(&node.size),
            NodeKind::Line(line) => Size2 {
                width: line.x2.abs(),
                height: line.y2.abs(),
            },
            NodeKind::Frame | NodeKind::Group | NodeKind::AutoLayout(_) => {
                if node.children.is_empty() {
                    fixed_or_zero(&node.size)
                } else {
                    let mut max_x: f64 = 0.0;
                    let mut max_y: f64 = 0.0;
                    for child_id in &node.children {
                        let Some(child) = self.scene.nodes.get(child_id) else {
                            continue;
                        };
                        let child_size = self.natural_size(child);
                        max_x = max_x.max(child.transform.x + child_size.width);
                        max_y = max_y.max(child.transform.y + child_size.height);
                    }
                    Size2 {
                        width: max_x.max(0.0),
                        height: max_y.max(0.0),
                    }
                }
            }
            NodeKind::Rect
            | NodeKind::Ellipse
            | NodeKind::Vector(_)
            | NodeKind::Instance { .. } => fixed_or_zero(&node.size),
        }
    }

    fn measure_context_for(&self, node: &Node) -> MeasureContext {
        match &node.kind {
            NodeKind::Text(text) => {
                let mut input = TextMeasureInput::from_text_node(text).for_node(&node.id);
                // A slot-bound text node must hug to the WORST-CASE fixture (the
                // largest data it will ever hold), not just its placeholder/sample.
                // Otherwise a hug height sized to the sample under-reserves and the
                // worst_case overflows (LUMV0810) — and a hug box cannot be enlarged
                // by a repair, so the run deadlocks. Reserving worst_case here keeps
                // hug heights both legible (no dead zone beyond worst_case) and safe.
                if let Some(worst_case) = self.worst_case_fixture_for(&node.id) {
                    if worst_case.chars().count() > input.content.chars().count() {
                        input.content = worst_case;
                    }
                }
                MeasureContext::Text(input)
            }
            NodeKind::Image(_) => MeasureContext::Box {
                natural: fixed_or_zero(&node.size),
            },
            _ => MeasureContext::Box {
                natural: self.natural_size(node),
            },
        }
    }

    /// The longest fixture (placeholder / sample / worst_case) of the slot bound to
    /// `node_id`, if any. Used so a slot-bound text node reserves room for its
    /// worst-case data when hugging.
    fn worst_case_fixture_for(&self, node_id: &NodeId) -> Option<String> {
        let slot = self
            .scene
            .slots
            .values()
            .find(|slot| slot.bound_nodes.contains(node_id))?;
        slot_fixtures(slot)
            .into_iter()
            .max_by_key(|fixture| fixture.chars().count())
    }

    fn write_geometry(&mut self, node: &Node, origin: Point2, size: Size2) {
        let layout_bounds = Rect {
            x: origin.x,
            y: origin.y,
            width: size.width.max(0.0),
            height: size.height.max(0.0),
        };
        let render_bounds = render_bounds_for(&layout_bounds, node);
        self.geometry.insert(
            node.id.clone(),
            ComputedGeometry {
                layout_bounds,
                render_bounds,
                text_lines: Vec::new(),
            },
        );
    }

    fn validate_artboard_bounds(&mut self) {
        for page in self.scene.pages.values() {
            let page_bounds = page_geometry(page).layout;
            if page_bounds.width <= 0.0
                || page_bounds.height <= 0.0
                || !page_bounds.width.is_finite()
                || !page_bounds.height.is_finite()
            {
                self.diagnostics.push(
                    Diagnostic::error(
                        Phase::Layout,
                        "LUMV0803",
                        format!("page {} has invalid canonical layout bounds", page.id),
                        Some(DiagnosticSubject::Page(page.id.clone())),
                    )
                    .with_hint("Normalize the page/artboard size before layout or export."),
                );
                continue;
            }

            for child_id in &page.children {
                self.validate_node_against_page(child_id, page, &page_bounds);
                self.validate_node_children_against_parent(child_id, page, &page_bounds, true);
            }
        }
    }

    fn validate_node_against_page(
        &mut self,
        node_id: &NodeId,
        page: &crate::scene::Page,
        page_bounds: &Rect,
    ) {
        let Some(bounds) = self.node_bounds(node_id, page_bounds) else {
            return;
        };
        if rect_contains_within(page_bounds, &bounds, PAGE_BOUNDS_TOLERANCE_PT) {
            return;
        }
        if page
            .bleed
            .as_ref()
            .is_some_and(|bleed| rect_contains(bleed, &bounds))
        {
            self.diagnostics.push(
                Diagnostic::warning(
                    Phase::Layout,
                    "LUMV0802",
                    format!(
                        "node {} on page {} falls outside trim bounds but inside bleed",
                        node_id, page.id
                    ),
                    Some(DiagnosticSubject::Node(node_id.clone())),
                )
                .with_hint("Review bleed-safe content before approving print export."),
            );
            return;
        }

        // Declared-bleed carve-out (A4): a node the author flagged bleed(true)
        // deliberately washes past the page — downgrade to a warning with a
        // distinct message. Never silent: the warning always appears.
        if self.is_declared_bleed(node_id) {
            self.diagnostics.push(
                Diagnostic::warning(
                    Phase::Layout,
                    "LUMV0800",
                    format!(
                        "node {} exceeds exportable bounds for page {}",
                        node_id, page.id
                    ),
                    Some(DiagnosticSubject::Node(node_id.clone())),
                )
                .with_hint(
                    "node off-canvas extent declared as bleed; content outside the page is not exported.",
                ),
            );
            return;
        }

        // Freehand clip policy (Phase 1b, user decision 2026-07-03):
        // freehand overflow is explicit intent, so it warns instead of
        // blocking — the canvas shows the true clipped consequence.
        // Managed content keeps the hard error.
        if self.is_freehand(node_id) {
            self.diagnostics.push(
                Diagnostic::warning(
                    Phase::Layout,
                    "LUMV0800",
                    format!(
                        "node {} exceeds exportable bounds for page {}",
                        node_id, page.id
                    ),
                    Some(DiagnosticSubject::Node(node_id.clone())),
                )
                .with_hint(
                    "Freehand node extends beyond the artboard; content outside the page is not exported.",
                ),
            );
            return;
        }

        self.diagnostics.push(
            Diagnostic::error(
                Phase::Layout,
                "LUMV0800",
                format!(
                    "node {} exceeds exportable bounds for page {}",
                    node_id, page.id
                ),
                Some(DiagnosticSubject::Node(node_id.clone())),
            )
            .with_hint("Move or resize the node so its computed bounds fit the artboard."),
        );
    }

    fn validate_node_children_against_parent(
        &mut self,
        node_id: &NodeId,
        page: &crate::scene::Page,
        parent_bounds: &Rect,
        parent_is_page: bool,
    ) {
        let Some(node) = self.scene.nodes.get(node_id) else {
            return;
        };
        let Some(node_bounds) = self.node_bounds(node_id, parent_bounds) else {
            return;
        };

        if !parent_is_page && !rect_contains(parent_bounds, &node_bounds) {
            // Freehand clip policy (Phase 1b, user decision 2026-07-03):
            // a freehand node past a clipping parent warns instead of
            // erroring — the human opted out of the solver's protection and
            // the canvas shows the clipped result. Managed content keeps
            // the fail-closed error under a clipping parent.
            let freehand = self.is_freehand(node_id);
            let declared_bleed = self.is_declared_bleed(node_id);
            let severity = if !freehand && !declared_bleed && self.parent_clips(node_id) {
                DiagnosticSeverity::Error
            } else {
                DiagnosticSeverity::Warning
            };
            let hint = if declared_bleed {
                "node off-canvas extent declared as bleed; content outside the page is not exported."
            } else if freehand {
                "Freehand node extends beyond its parent; the overflow is cut off wherever the parent clips content."
            } else {
                "Move, resize, wrap, or change the parent layout so the child fits."
            };
            let diagnostic = Diagnostic {
                severity,
                phase: Phase::Layout,
                code: "LUMV0801".to_owned(),
                message: format!("node {} exceeds parent bounds on page {}", node_id, page.id),
                subject: Some(DiagnosticSubject::Node(node_id.clone())),
                hint: Some(hint.to_owned()),
            };
            self.diagnostics.push(diagnostic);
        }

        for child_id in &node.children {
            self.validate_node_children_against_parent(child_id, page, &node_bounds, false);
        }
    }

    fn node_bounds(&self, node_id: &NodeId, parent_bounds: &Rect) -> Option<Rect> {
        if let Some(geometry) = self.geometry.get(node_id) {
            return Some(geometry.layout_bounds.clone());
        }
        let node = self.scene.nodes.get(node_id)?;
        let size = fixed_or_zero(&node.size);
        Some(Rect {
            x: parent_bounds.x + node.transform.x,
            y: parent_bounds.y + node.transform.y,
            width: size.width,
            height: size.height,
        })
    }

    fn parent_clips(&self, node_id: &NodeId) -> bool {
        match self.scene.parent_of(node_id) {
            Some(crate::scene::ParentRef::Node(parent_id)) => self
                .scene
                .nodes
                .get(&parent_id)
                .map(|node| node.clip)
                .unwrap_or(false),
            Some(crate::scene::ParentRef::Page(_)) | None => true,
        }
    }

    /// A node whose author declared `bleed(true)` — deliberate off-canvas
    /// intent (A4). Per-node, never inherited.
    fn is_declared_bleed(&self, node_id: &NodeId) -> bool {
        self.scene.nodes.get(node_id).is_some_and(|node| node.bleed)
    }

    /// A node a human freehands directly: pinned Absolute, or a child of a
    /// Free container (whose children all live at hand-placed transforms).
    fn is_freehand(&self, node_id: &NodeId) -> bool {
        if self
            .scene
            .nodes
            .get(node_id)
            .is_some_and(|node| is_absolute(node))
        {
            return true;
        }
        match self.scene.parent_of(node_id) {
            Some(crate::scene::ParentRef::Node(parent_id)) => self
                .scene
                .nodes
                .get(&parent_id)
                .is_some_and(is_free_container),
            Some(crate::scene::ParentRef::Page(_)) | None => false,
        }
    }

    fn validate_slots(&mut self) {
        for slot in self.scene.slots.values() {
            self.validate_slot_content(slot);
            self.validate_slot_policy_shape(slot);
            self.validate_slot_bounds(slot);
        }
    }

    fn validate_layout_anchors(&mut self) {
        let mut diagnostics = Vec::new();
        for node in self.scene.nodes.values() {
            let (NodeKind::AutoLayout(auto), Some(props)) = (&node.kind, node.layout.as_ref())
            else {
                continue;
            };

            match auto.direction {
                AutoLayoutDirection::Row => {
                    validate_main_anchor(&props.align_x, node, Axis::Horizontal, &mut diagnostics);
                    validate_cross_anchor(&props.align_y, node, Axis::Vertical, &mut diagnostics);
                }
                AutoLayoutDirection::Column => {
                    validate_main_anchor(&props.align_y, node, Axis::Vertical, &mut diagnostics);
                    validate_cross_anchor(&props.align_x, node, Axis::Horizontal, &mut diagnostics);
                }
            }
        }
        self.diagnostics.extend(diagnostics);
    }

    fn validate_text_nodes(&mut self) {
        let mut placed: Vec<(NodeId, Vec<Rect>)> = Vec::new();
        for node in self.scene.nodes.values() {
            let NodeKind::Text(text) = &node.kind else {
                continue;
            };
            let Some(geometry) = self.geometry.get(&node.id) else {
                continue;
            };

            if !text.font_size.is_finite()
                || text.font_size <= 0.0
                || !text.line_height.is_finite()
                || text.line_height <= 0.0
                || !text.letter_spacing.is_finite()
                || !text.paragraph_spacing.is_finite()
                || text.paragraph_spacing < 0.0
            {
                self.diagnostics.push(Diagnostic::error(
                    Phase::Layout,
                    "LUMV0900",
                    format!("text node {} has invalid text metrics", node.id),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                ));
                continue;
            }

            // A6a D3: `truncate(true)` on freely-wrapping text with no
            // max_lines can never fire — nothing ever cuts the copy. Teach,
            // don't block (advisory), so the author knows the flag is inert.
            if text.truncate && text.max_lines.is_none() && matches!(text.wrap, TextWrap::Wrap) {
                self.diagnostics.push(
                    Diagnostic::warning(
                        Phase::Layout,
                        "LUMV0905",
                        format!(
                            "text node {} sets truncate but wraps freely with no max_lines; the ellipsis can never fire",
                            node.id
                        ),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    )
                    .with_hint(
                        "Set max_lines(n) or wrap(false) so truncation has a cut point, or drop truncate.",
                    ),
                );
            }

            // A6b D3: reject invalid ops-injected spans BEFORE measurement so a
            // scene with an out-of-bounds / overlapping / non-char-boundary /
            // gradient-filled span never reaches partial rendering. DSL-authored
            // spans are valid by construction; only the empty guard runs there.
            if !text.spans.is_empty() {
                let errors = crate::span_validation_errors(&text.content, &text.spans);
                if !errors.is_empty() {
                    for error in errors {
                        self.diagnostics.push(
                            Diagnostic::error(
                                Phase::Layout,
                                "LUMV0906",
                                format!(
                                    "text node {} has an invalid span (#{}): {}",
                                    node.id, error.index, error.reason
                                ),
                                Some(DiagnosticSubject::Node(node.id.clone())),
                            )
                            .with_hint(
                                "Span offsets index the content bytes: keep them in-bounds, char-aligned, start<end, sorted, non-overlapping, and solid/token-filled.",
                            ),
                        );
                    }
                    continue;
                }
                // A6b v1 limitation, loud not silent (review fix): the
                // segmented span path hard-breaks on `\n` but does not apply
                // the extra paragraph gap — authored paragraph_spacing is
                // ignored on spanned text. Advise so the author knows.
                if text.paragraph_spacing > 0.0
                    && (text.content.contains('\n') || text.content.contains("\\n"))
                {
                    self.diagnostics.push(
                        Diagnostic::warning(
                            Phase::Layout,
                            "LUMV0907",
                            format!(
                                "text node {} combines spans with paragraph_spacing; the paragraph gap is not applied to spanned text in v1",
                                node.id
                            ),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        )
                        .with_hint(
                            "Split the stanzas into separate text nodes, or drop the spans/para_spacing combination.",
                        ),
                    );
                }
            }

            if geometry.layout_bounds.width <= 0.0 || geometry.layout_bounds.height <= 0.0 {
                self.diagnostics.push(Diagnostic::error(
                    Phase::Layout,
                    "LUMV0901",
                    format!("text node {} has collapsed bounds", node.id),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                ));
                continue;
            }

            let measured = self.measurer.measure(
                &TextMeasureInput::from_text_node(text)
                    .for_node(&node.id)
                    .with_bounds(&geometry.layout_bounds),
            );
            // Plan 4 item F: keep what this measurement already knows — the
            // line boxes — instead of discarding them after the overflow
            // checks. Nodes that `continue`d above (invalid metrics, collapsed
            // bounds) keep an empty `text_lines` and hit-test by their box.
            placed.push((
                node.id.clone(),
                painted_text_lines(&geometry.layout_bounds, text, &measured),
            ));
            // Taffy rounds computed geometry to whole pixels, so a hug box can
            // legitimately sit up to half a pixel under the fractional measured
            // height (e.g. stacked paragraph gaps or fractional line heights).
            // A sub-pixel "overflow" is that rounding contract, not content
            // loss — re-derive the overflow flags with the rounding tolerance
            // so hug-sized text never trips a phantom LUMV0902/0903.
            const ROUNDING_TOLERANCE: f64 = 0.5 + 0.01;
            let overflow_x = measured.overflow_x
                && measured.width > geometry.layout_bounds.width + ROUNDING_TOLERANCE;
            let overflow_y = measured.overflow_y
                && measured.height > geometry.layout_bounds.height + ROUNDING_TOLERANCE;
            // Fold measurement-time font diagnostics (LUMS0100 whole-family
            // fallback, LUMS0103 per-glyph substitution) into the layout
            // result so missing fonts surface at preflight, not only at
            // export. Re-subject them to this node (the measurer reports them
            // document-scoped) so they match the render path's emission and
            // dedupe against it.
            for diagnostic in &measured.diagnostics {
                let diagnostic = Diagnostic {
                    subject: Some(DiagnosticSubject::Node(node.id.clone())),
                    ..diagnostic.clone()
                };
                if !self.diagnostics.contains(&diagnostic) {
                    self.diagnostics.push(diagnostic);
                }
            }
            // Freehand text-fit policy (Phase 1d, user decision): a human
            // resizing a pinned text box below its content is explicit
            // intent — the canvas shows the true truncation, so text-fit
            // codes are advisory for freehand nodes. Managed text keeps
            // the fail-closed errors that protect agent-authored copy.
            let severity = if self.is_freehand(&node.id) {
                DiagnosticSeverity::Warning
            } else {
                DiagnosticSeverity::Error
            };
            let mut push = |code: &str, message: String, hint: &str| {
                self.diagnostics.push(
                    Diagnostic {
                        severity: severity.clone(),
                        phase: Phase::Layout,
                        code: code.to_owned(),
                        message,
                        subject: Some(DiagnosticSubject::Node(node.id.clone())),
                        hint: None,
                    }
                    .with_hint(hint),
                );
            };
            if measured.exceeds_max_lines {
                push(
                    "LUMV0904",
                    format!("text node {} exceeds max_lines", node.id),
                    "Increase max_lines, shorten the copy, or enlarge the text box.",
                );
            }
            if overflow_x && matches!(text.wrap, TextWrap::NoWrap) {
                push(
                    "LUMV0902",
                    format!("non-wrapping text node {} overflows horizontally", node.id),
                    "Use wrap(true), s(fill,hug), a smaller style, or a wider text box.",
                );
            }
            if overflow_y {
                push(
                    "LUMV0903",
                    format!("text node {} exceeds available height", node.id),
                    "Use hug height, increase the fixed height, reduce copy, or lower the font size.",
                );
            }
        }
        for (node_id, text_lines) in placed {
            if let Some(geometry) = self.geometry.get_mut(&node_id) {
                geometry.text_lines = text_lines;
            }
        }
    }

    fn validate_slot_content(&mut self, slot: &Slot) {
        let fixtures = slot_fixtures(slot);
        if slot.required && fixtures.is_empty() {
            self.diagnostics.push(
                Diagnostic::error(
                    Phase::Layout,
                    "LUMV0800",
                    format!(
                        "required slot {} needs a placeholder or validation fixture",
                        slot.key
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                )
                .with_hint(
                    "Add a placeholder, sample, worst-case fixture, or max_length for fit validation.",
                ),
            );
        }

        for node_id in &slot.bound_nodes {
            let Some(node) = self.scene.nodes.get(node_id) else {
                self.diagnostics.push(Diagnostic::error(
                    Phase::Layout,
                    "LUMV0801",
                    format!("slot {} binds missing node {}", slot.key, node_id),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
                continue;
            };

            let Some(geometry) = self.geometry.get(node_id).cloned() else {
                self.diagnostics.push(Diagnostic::error(
                    Phase::Layout,
                    "LUMV0802",
                    format!(
                        "slot {} node {} has no computed geometry",
                        slot.key, node_id
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
                continue;
            };

            if matches!(
                slot.content_type,
                ContentType::TextShort | ContentType::TextLong | ContentType::RichTextLimited
            ) {
                if let NodeKind::Text(text) = &node.kind {
                    self.validate_text_slot_fit(slot, node_id, text, &geometry, &fixtures);
                }
            }
        }
    }

    fn validate_text_slot_fit(
        &mut self,
        slot: &Slot,
        node_id: &NodeId,
        text: &crate::scene::TextNode,
        geometry: &ComputedGeometry,
        fixtures: &[String],
    ) {
        for fixture in fixtures {
            let fit = text_fit(
                self.measurer,
                node_id,
                fixture,
                text,
                None,
                &geometry.layout_bounds,
                &slot.overflow,
            );
            if fit.fits {
                continue;
            }

            // Freehand slot-fit policy (mirrors the Phase 1d text-fit
            // decision): a pinned or baked-Free text box is human-owned
            // geometry — worst-case fixture overflow is advisory there,
            // while solver-managed slot nodes keep the fail-closed errors
            // that protect template instantiation.
            let severity = if self.is_freehand(node_id) {
                DiagnosticSeverity::Warning
            } else {
                DiagnosticSeverity::Error
            };
            match &slot.overflow {
                OverflowPolicy::Error => {
                    self.diagnostics.push(Diagnostic {
                        severity: severity.clone(),
                        phase: Phase::Layout,
                        code: "LUMV0810".to_owned(),
                        message: format!(
                            "slot {} fixture overflows text node {}",
                            slot.key, node_id
                        ),
                        subject: Some(DiagnosticSubject::Slot(slot.id.clone())),
                        hint: None,
                    });
                }
                OverflowPolicy::ShrinkFont { min_font_size, .. } => {
                    let shrink_fit = text_fit(
                        self.measurer,
                        node_id,
                        fixture,
                        text,
                        Some(*min_font_size),
                        &geometry.layout_bounds,
                        &OverflowPolicy::Error,
                    );
                    if shrink_fit.fits {
                        self.diagnostics.push(advice(
                            "LUMV0811",
                            format!(
                                "slot {} fixture would likely fit by shrinking text; V1 does not mutate font size",
                                slot.key
                            ),
                            Some(DiagnosticSubject::Slot(slot.id.clone())),
                        ));
                    } else {
                        self.diagnostics.push(Diagnostic {
                            severity: severity.clone(),
                            phase: Phase::Layout,
                            code: "LUMV0812".to_owned(),
                            message: format!(
                                "slot {} fixture does not fit even at min font size {}",
                                slot.key, min_font_size
                            ),
                            subject: Some(DiagnosticSubject::Slot(slot.id.clone())),
                            hint: None,
                        });
                    }
                }
                OverflowPolicy::Wrap { max_lines } => {
                    self.diagnostics.push(Diagnostic {
                        severity: severity.clone(),
                        phase: Phase::Layout,
                        code: "LUMV0813".to_owned(),
                        message: format!(
                            "slot {} fixture needs {} lines but max_lines is {:?}",
                            slot.key, fit.line_count, max_lines
                        ),
                        subject: Some(DiagnosticSubject::Slot(slot.id.clone())),
                        hint: None,
                    });
                }
                OverflowPolicy::Clip | OverflowPolicy::Ellipsis => {
                    self.diagnostics.push(Diagnostic::warning(
                        Phase::Layout,
                        "LUMV0814",
                        format!(
                            "slot {} fixture overflows and policy may lose content",
                            slot.key
                        ),
                        Some(DiagnosticSubject::Slot(slot.id.clone())),
                    ));
                }
                OverflowPolicy::AskAgentToRepair => {
                    self.diagnostics.push(Diagnostic::warning(
                        Phase::Layout,
                        "LUMV0815",
                        format!("slot {} fixture needs agent layout repair", slot.key),
                        Some(DiagnosticSubject::Slot(slot.id.clone())),
                    ));
                }
                OverflowPolicy::ExpandContainer => {
                    self.diagnostics.push(advice(
                        "LUMV0816",
                        format!(
                            "slot {} fixture would require container expansion; V1 only diagnoses expansion",
                            slot.key
                        ),
                        Some(DiagnosticSubject::Slot(slot.id.clone())),
                    ));
                }
            }
        }
    }

    fn validate_slot_policy_shape(&mut self, slot: &Slot) {
        if let Some(rule) = &slot.conditional {
            if rule.expression.trim().is_empty() {
                self.diagnostics.push(Diagnostic::error(
                    Phase::Layout,
                    "LUMV0830",
                    format!("conditional slot {} has an empty expression", slot.key),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }

            if matches!(rule.when_false, EmptyBehavior::UseFallback)
                && slot.placeholder.as_deref().unwrap_or("").is_empty()
            {
                self.diagnostics.push(Diagnostic::warning(
                    Phase::Layout,
                    "LUMV0831",
                    format!(
                        "conditional slot {} uses fallback behavior without fallback content",
                        slot.key
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }
        }

        if let Some(repeater) = &slot.repeater {
            if !matches!(slot.content_type, ContentType::RepeaterGroup) {
                self.diagnostics.push(Diagnostic::error(
                    Phase::Layout,
                    "LUMV0840",
                    format!(
                        "slot {} has repeater behavior but is not a repeater group",
                        slot.key
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }
            if !self.scene.nodes.contains_key(&repeater.template_node_id) {
                self.diagnostics.push(Diagnostic::error(
                    Phase::Layout,
                    "LUMV0841",
                    format!(
                        "repeater slot {} references missing template node {}",
                        slot.key, repeater.template_node_id
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }
            if repeater
                .max_items
                .is_some_and(|max_items| max_items < repeater.min_items)
            {
                self.diagnostics.push(Diagnostic::error(
                    Phase::Layout,
                    "LUMV0842",
                    format!("repeater slot {} has max_items below min_items", slot.key),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }
            if matches!(repeater.reflow, ReflowPolicy::Paginate) {
                self.diagnostics.push(advice(
                    "LUMV0843",
                    format!(
                        "repeater slot {} requests pagination, which is scaffolded but not applied in V1",
                        slot.key
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }
        }

        if matches!(slot.content_type, ContentType::Image | ContentType::Logo) {
            match &slot.image_policy {
                Some(policy) => self.validate_image_policy(slot, policy),
                None => self.diagnostics.push(Diagnostic::error(
                    Phase::Layout,
                    "LUMV0820",
                    format!("image-like slot {} needs an image policy", slot.key),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                )),
            }
        }
    }

    fn validate_image_policy(&mut self, slot: &Slot, policy: &ImagePolicy) {
        if let Some(focal_point) = &policy.focal_point {
            if !(0.0..=1.0).contains(&focal_point.x) || !(0.0..=1.0).contains(&focal_point.y) {
                self.diagnostics.push(Diagnostic::error(
                    Phase::Layout,
                    "LUMV0821",
                    format!("image slot {} has focal point outside 0..1", slot.key),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }
        }

        if policy
            .aspect_ratio
            .is_some_and(|aspect_ratio| aspect_ratio <= 0.0)
        {
            self.diagnostics.push(Diagnostic::error(
                Phase::Layout,
                "LUMV0822",
                format!("image slot {} has non-positive aspect ratio", slot.key),
                Some(DiagnosticSubject::Slot(slot.id.clone())),
            ));
        }

        if self.print_fidelity_required() && policy.min_dpi.is_none() {
            self.diagnostics.push(Diagnostic::error(
                Phase::Layout,
                "LUMV0823",
                format!(
                    "image slot {} needs a min_dpi policy for print export",
                    slot.key
                ),
                Some(DiagnosticSubject::Slot(slot.id.clone())),
            ));
        }
    }

    fn validate_slot_bounds(&mut self, slot: &Slot) {
        if !slot.required {
            return;
        }

        for node_id in &slot.bound_nodes {
            let Some(page_id) = page_for_node(self.scene, node_id) else {
                continue;
            };
            let Some(page) = self.scene.pages.get(&page_id) else {
                continue;
            };
            let Some(safe_area) = &page.safe_area else {
                continue;
            };
            let Some(geometry) = self.geometry.get(node_id) else {
                continue;
            };

            if !rect_contains(safe_area, &geometry.render_bounds) {
                self.diagnostics.push(Diagnostic::error(
                    Phase::Layout,
                    "LUMV0803",
                    format!(
                        "required slot {} node {} falls outside page safe area",
                        slot.key, node_id
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }
        }
    }

    fn print_fidelity_required(&self) -> bool {
        matches!(
            self.scene.meta.medium,
            Some(crate::scene::Medium::Print | crate::scene::Medium::DirectMail)
        ) || self.scene.export_profiles.iter().any(|profile| {
            matches!(
                profile.pdf_intent,
                Some(crate::export_contract::PdfIntent::Print)
            ) || profile.include_bleed
        })
    }
}

#[derive(Default)]
struct TaffyMap {
    by_lumen: BTreeMap<NodeId, TaffyNodeId>,
    by_taffy: Vec<(TaffyNodeId, NodeId)>,
}

#[derive(Clone, Debug)]
struct FlowContext {
    direction: AutoLayoutDirection,
    main_axis: Axis,
    fill_fallback_nodes: BTreeSet<NodeId>,
    cross_axis_has_definite_space: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Axis {
    Horizontal,
    Vertical,
}

impl Axis {
    fn cross(self) -> Self {
        match self {
            Self::Horizontal => Self::Vertical,
            Self::Vertical => Self::Horizontal,
        }
    }

    fn value(self, size: Size2) -> f64 {
        match self {
            Self::Horizontal => size.width,
            Self::Vertical => size.height,
        }
    }

    fn dimension(self, size: &SizeSpec) -> &Dimension {
        match self {
            Self::Horizontal => &size.width,
            Self::Vertical => &size.height,
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::Horizontal => "width",
            Self::Vertical => "height",
        }
    }
}

fn main_axis_alignment(anchor: &LayoutAnchor) -> JustifyContent {
    match anchor {
        LayoutAnchor::Start | LayoutAnchor::Stretch => JustifyContent::Start,
        LayoutAnchor::Center => JustifyContent::Center,
        LayoutAnchor::End => JustifyContent::End,
        LayoutAnchor::SpaceBetween => JustifyContent::SpaceBetween,
    }
}

fn cross_axis_alignment(anchor: &LayoutAnchor) -> AlignItems {
    match anchor {
        LayoutAnchor::Start => AlignItems::Start,
        LayoutAnchor::Center => AlignItems::Center,
        LayoutAnchor::End => AlignItems::End,
        LayoutAnchor::Stretch => AlignItems::Stretch,
        LayoutAnchor::SpaceBetween => AlignItems::Start,
    }
}

fn cross_axis_content_alignment(anchor: &LayoutAnchor) -> AlignContent {
    match anchor {
        LayoutAnchor::Start => AlignContent::Start,
        LayoutAnchor::Center => AlignContent::Center,
        LayoutAnchor::End => AlignContent::End,
        LayoutAnchor::Stretch => AlignContent::Stretch,
        LayoutAnchor::SpaceBetween => AlignContent::Start,
    }
}

fn validate_main_anchor(
    anchor: &LayoutAnchor,
    node: &Node,
    axis: Axis,
    diagnostics: &mut Vec<Diagnostic>,
) {
    if matches!(anchor, LayoutAnchor::Stretch) {
        diagnostics.push(invalid_anchor_diagnostic(
            node,
            axis,
            "stretch is a cross-axis alignment and cannot be used on the main axis",
        ));
    }
}

fn validate_cross_anchor(
    anchor: &LayoutAnchor,
    node: &Node,
    axis: Axis,
    diagnostics: &mut Vec<Diagnostic>,
) {
    if matches!(anchor, LayoutAnchor::SpaceBetween) {
        diagnostics.push(invalid_anchor_diagnostic(
            node,
            axis,
            "space-between is a main-axis alignment and cannot be used on the cross axis",
        ));
    }
}

fn invalid_anchor_diagnostic(node: &Node, axis: Axis, message: &str) -> Diagnostic {
    Diagnostic::warning(
        Phase::Layout,
        "LUMV0710",
        format!(
            "auto-layout node {} has invalid {} anchor: {}",
            node.id,
            axis.label(),
            message
        ),
        Some(DiagnosticSubject::Node(node.id.clone())),
    )
    .with_hint("Use x/y anchors that match the layout direction: space-between on the main axis, stretch on the cross axis.")
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
struct Point2 {
    x: f64,
    y: f64,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
struct Size2 {
    width: f64,
    height: f64,
}

#[derive(Clone, Debug)]
enum MeasureContext {
    Text(TextMeasureInput),
    Box { natural: Size2 },
}

fn measure_taffy_node(
    known_dimensions: TaffySize<Option<f32>>,
    available_space: TaffySize<AvailableSpace>,
    context: Option<&mut MeasureContext>,
    measurer: &dyn TextMeasurer,
) -> TaffySize<f32> {
    if let TaffySize {
        width: Some(width),
        height: Some(height),
    } = known_dimensions
    {
        return TaffySize { width, height };
    }

    let natural = match context {
        Some(MeasureContext::Text(input)) => {
            // Plan 4 (ruling R8): a leaf with a definite width wraps at THAT
            // width — the painters lay out at the box, not at the container's
            // available space. A width-less leaf keeps the available bound.
            input.max_width = match known_dimensions.width {
                Some(width) => Some(f64::from(width)),
                None => available_width(available_space.width),
            };
            let measured = measurer.measure(input);
            Size2 {
                width: measured.width,
                height: measured.height,
            }
        }
        Some(MeasureContext::Box { natural }) => *natural,
        None => Size2::default(),
    };

    TaffySize {
        width: known_dimensions
            .width
            .unwrap_or_else(|| natural.width.max(0.0) as f32),
        height: known_dimensions
            .height
            .unwrap_or_else(|| natural.height.max(0.0) as f32),
    }
}

fn available_width(available: AvailableSpace) -> Option<f64> {
    match available {
        AvailableSpace::Definite(value) => Some(f64::from(value)),
        AvailableSpace::MinContent | AvailableSpace::MaxContent => None,
    }
}

fn fixed_or_zero(size: &SizeSpec) -> Size2 {
    Size2 {
        width: match &size.width {
            Dimension::Fixed(value) => *value,
            Dimension::Hug | Dimension::Fill { .. } | Dimension::Token { .. } => 0.0,
        },
        height: match &size.height {
            Dimension::Fixed(value) => *value,
            Dimension::Hug | Dimension::Fill { .. } | Dimension::Token { .. } => 0.0,
        },
    }
}

fn is_out_of_flow_transform(node: &Node) -> bool {
    node.transform.rotation.abs() > f64::EPSILON
        || node.transform.skew_x.abs() > f64::EPSILON
        || node.transform.skew_y.abs() > f64::EPSILON
}

/// Phase 1 freehand: a pinned node leaves normal flow exactly like a
/// rotated child does — except deliberately.
fn is_absolute(node: &Node) -> bool {
    node.position_mode == PositionMode::Absolute
}

/// A container whose children lay out at their own baked transforms
/// instead of the flex solve ("free this whole section").
fn is_free_container(node: &Node) -> bool {
    matches!(node.kind, NodeKind::AutoLayout(_))
        && node
            .layout
            .as_ref()
            .is_some_and(|layout| layout.layout_mode == LayoutMode::Free)
}

/// The page-space box a pinned node lays out at. The box alone means
/// nothing while Managed; Absolute without a box falls back to flow
/// position (mirrors the rotated out-of-flow treatment).
fn pinned_box(node: &Node) -> Option<&Rect> {
    match node.position_mode {
        PositionMode::Absolute => node.absolute_box.as_ref(),
        PositionMode::Managed => None,
    }
}

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

fn render_bounds_for(layout_bounds: &Rect, node: &Node) -> Rect {
    if !is_out_of_flow_transform(node) && !node.transform.flip_x && !node.transform.flip_y {
        return layout_bounds.clone();
    }

    let rotation = node.transform.rotation.to_radians();
    let skew_x = node.transform.skew_x.to_radians().tan();
    let skew_y = node.transform.skew_y.to_radians().tan();
    let corners = [
        (0.0, 0.0),
        (layout_bounds.width, 0.0),
        (layout_bounds.width, layout_bounds.height),
        (0.0, layout_bounds.height),
    ];

    let mut min_x = f64::INFINITY;
    let mut min_y = f64::INFINITY;
    let mut max_x = f64::NEG_INFINITY;
    let mut max_y = f64::NEG_INFINITY;

    for (x, y) in corners {
        let flipped_x = if node.transform.flip_x {
            layout_bounds.width - x
        } else {
            x
        };
        let flipped_y = if node.transform.flip_y {
            layout_bounds.height - y
        } else {
            y
        };
        let skewed_x = flipped_x + skew_x * flipped_y;
        let skewed_y = flipped_y + skew_y * flipped_x;
        let rotated_x = skewed_x * rotation.cos() - skewed_y * rotation.sin();
        let rotated_y = skewed_x * rotation.sin() + skewed_y * rotation.cos();
        let absolute_x = layout_bounds.x + rotated_x;
        let absolute_y = layout_bounds.y + rotated_y;
        min_x = min_x.min(absolute_x);
        min_y = min_y.min(absolute_y);
        max_x = max_x.max(absolute_x);
        max_y = max_y.max(absolute_y);
    }

    Rect {
        x: min_x,
        y: min_y,
        width: (max_x - min_x).max(0.0),
        height: (max_y - min_y).max(0.0),
    }
}

fn positive_f32(value: f64) -> f32 {
    if value.is_finite() && value > 0.0 {
        value as f32
    } else {
        1.0
    }
}

fn slot_fixtures(slot: &Slot) -> Vec<String> {
    let mut fixtures = Vec::new();
    let mut seen = BTreeSet::new();

    let mut push_fixture = |value: String| {
        if !value.trim().is_empty() && seen.insert(value.clone()) {
            fixtures.push(value);
        }
    };

    if let Some(placeholder) = &slot.placeholder {
        push_fixture(placeholder.clone());
    }
    for sample in &slot.validation.samples {
        push_fixture(sample.clone());
    }
    if let Some(worst_case) = &slot.validation.worst_case {
        push_fixture(worst_case.clone());
    }
    if let Some(max_length) = slot.validation.max_length.or(slot.formatting.max_length) {
        push_fixture("M".repeat(max_length.min(512)));
    }

    fixtures
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct TextFit {
    fits: bool,
    line_count: u16,
}

fn text_fit(
    measurer: &dyn TextMeasurer,
    node_id: &NodeId,
    content: &str,
    text: &crate::scene::TextNode,
    font_size_override: Option<f64>,
    bounds: &Rect,
    policy: &OverflowPolicy,
) -> TextFit {
    // Measure the fixture the way the NODE actually renders — its own wrap +
    // max_lines — NOT the slot's overflow policy. The DSL cannot set a slot's
    // overflow policy (it is always Error), so deriving wrap from the policy
    // measured every slotted fixture as a single no-wrap line and reported a false
    // LUMV0810 for any wrapping body whose worst_case spans more than one line. The
    // slot.overflow policy still governs the RESPONSE to a genuine overflow
    // (Error → diagnostic, ShrinkFont → shrink, Clip/Ellipsis → lossy advice) in the
    // caller; here we only reflect how the text flows. An explicit Wrap policy still
    // wins (it can raise max_lines beyond the node's own cap).
    let (wrap, max_lines) = match policy {
        OverflowPolicy::Wrap { max_lines } => (TextWrap::Wrap, *max_lines),
        _ => (text.wrap.clone(), text.max_lines),
    };
    let measured = measurer.measure(&TextMeasureInput {
        node_id: Some(node_id.to_string()),
        font_size_override,
        content: content.to_owned(),
        font_family: text.font_family.clone(),
        font_size: font_size_override.unwrap_or(text.font_size),
        font_weight: text.font_weight,
        // Italic selects a different face, changing advances → a fit input.
        italic: text.italic,
        // Measure the fixture with the node's OWN line height, not a hardcoded 1.2.
        // The hardcode made a hug-height (or any lh < 1.2) slotted text node report a
        // false LUMV0810 overflow — the fixture was measured taller than the box the
        // node actually reserves — which blocked legible hug heights and tight
        // headlines. Fall back to 1.2 only when the node carries no line height.
        line_height: if text.line_height > 0.0 {
            text.line_height
        } else {
            1.2
        },
        letter_spacing: 0.0,
        wrap,
        max_lines,
        direction: crate::TextDirection::Ltr,
        max_width: Some(bounds.width.max(0.0)),
        max_height: Some(bounds.height.max(0.0)),
        // The node's own case transform and paragraph spacing change the
        // fixture's measured geometry, so fit validation must see them.
        // Truncation is a lossy RESPONSE to overflow, not a fit input — keep
        // it off so a too-long fixture still reports the true overflow.
        text_transform: text.text_transform,
        truncate: false,
        paragraph_spacing: text.paragraph_spacing,
        // Slot fixtures substitute a different string than node.content, so the
        // node's span byte-offsets don't apply to the fixture — measure base.
        spans: Vec::new(),
    });

    TextFit {
        fits: !measured.overflow_x && !measured.overflow_y && !measured.exceeds_max_lines,
        line_count: measured.line_count,
    }
}

fn page_for_node(scene: &Scene, node_id: &NodeId) -> Option<PageId> {
    let mut current = node_id.clone();
    loop {
        match scene.parent_of(&current)? {
            crate::scene::ParentRef::Page(page_id) => return Some(page_id),
            crate::scene::ParentRef::Node(parent_id) => current = parent_id,
        }
    }
}

fn rect_contains(container: &Rect, child: &Rect) -> bool {
    child.x >= container.x
        && child.y >= container.y
        && child.x + child.width <= container.x + container.width
        && child.y + child.height <= container.y + container.height
}

/// Sub-point tolerance for page-bounds containment.
///
/// A `fill,fill` root artboard resolves to the rounded preset height (A4 portrait
/// → 842.0pt) while the canonical exportable page height is 841.889…pt. A strict
/// containment check then reports a permanent ~0.11pt overflow (`LUMV0800`) on the
/// root frame that NO authoring repair can clear — the repair loop is forced to
/// re-assert `s(fill,fill)`, which reproduces the same rounding. One point is far
/// below rendering significance (≈4px even at 300 DPI, on the page edge only) and
/// far below any genuine overflow (the smallest real-overflow fixtures exceed
/// bounds by tens of points), so forgiving it here removes the phantom without
/// masking real out-of-bounds content. Parent-bounds checks (`LUMV0801`) keep the
/// strict `rect_contains`.
const PAGE_BOUNDS_TOLERANCE_PT: f64 = 1.0;

fn rect_contains_within(container: &Rect, child: &Rect, tolerance: f64) -> bool {
    child.x >= container.x - tolerance
        && child.y >= container.y - tolerance
        && child.x + child.width <= container.x + container.width + tolerance
        && child.y + child.height <= container.y + container.height + tolerance
}

fn advice(
    code: impl Into<String>,
    message: impl Into<String>,
    subject: Option<DiagnosticSubject>,
) -> Diagnostic {
    Diagnostic {
        severity: DiagnosticSeverity::Advice,
        phase: Phase::Layout,
        code: code.into(),
        message: message.into(),
        subject,
        hint: None,
    }
}
