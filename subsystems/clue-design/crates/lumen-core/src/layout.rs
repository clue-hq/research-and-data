use crate::diagnostics::{Diagnostic, DiagnosticSeverity, DiagnosticSubject, Phase};
use crate::ids::{NodeId, PageId};
use crate::operations::{NodePatch, Operation, OptionalFieldPatch};
use crate::scene::{
    AutoLayoutDirection, ComputedGeometry, Dimension, Node, NodeKind, Rect, Scene, SizeSpec,
};
use crate::slots::{ContentType, EmptyBehavior, ImagePolicy, OverflowPolicy, ReflowPolicy, Slot};
use std::collections::{BTreeMap, BTreeSet};
use taffy::geometry::{Rect as TaffyRect, Size as TaffySize};
use taffy::prelude::{
    auto, length, percent, AlignContent, AlignItems, AvailableSpace, Display,
    FlexDirection as TaffyFlexDirection, FlexWrap, JustifyContent, Style, TaffyTree,
};
use taffy::style::Dimension as TaffyDimension;
use taffy::tree::NodeId as TaffyNodeId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LayoutOptions {
    pub validate_slots: bool,
}

impl Default for LayoutOptions {
    fn default() -> Self {
        Self {
            validate_slots: true,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct LayoutResult {
    pub geometry: BTreeMap<NodeId, ComputedGeometry>,
    pub diagnostics: Vec<Diagnostic>,
}

pub fn layout_scene(scene: &Scene, options: LayoutOptions) -> LayoutResult {
    let mut engine = LayoutEngine::new(scene);
    engine.layout_pages();

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
    geometry: BTreeMap<NodeId, ComputedGeometry>,
    diagnostics: Vec<Diagnostic>,
}

impl<'a> LayoutEngine<'a> {
    fn new(scene: &'a Scene) -> Self {
        Self {
            scene,
            geometry: BTreeMap::new(),
            diagnostics: Vec::new(),
        }
    }

    fn layout_pages(&mut self) {
        for page in self.scene.pages.values() {
            let page_size = Size2 {
                width: page.size.width,
                height: page.size.height,
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
        let Some(is_auto_layout) = self
            .scene
            .nodes
            .get(node_id)
            .map(|node| matches!(node.kind, NodeKind::AutoLayout(_)))
        else {
            return;
        };

        if is_auto_layout {
            self.layout_auto_node(node_id, origin, parent_size, page_id);
            return;
        }

        self.warn_unresolved_dimension_tokens(node_id);
        let Some(node) = self.scene.nodes.get(node_id) else {
            return;
        };

        let size = self.resolve_manual_size(node, parent_size);
        self.write_geometry(node, origin, size);

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
                size,
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

        if let Err(error) = tree.compute_layout_with_measure(
            root,
            available_space,
            |known_dimensions, available_space, _node_id, context, _style| {
                measure_taffy_node(known_dimensions, available_space, context)
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

        let taffy_id = if let NodeKind::AutoLayout(auto) = &node.kind {
            let flow = self.flow_context(node, auto.direction.clone(), parent_size);
            let mut children = Vec::new();
            for child_id in &node.children {
                let Some(child) = self.scene.nodes.get(child_id) else {
                    continue;
                };

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
        let size = Size2 {
            width: f64::from(layout.size.width),
            height: f64::from(layout.size.height),
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
            style.align_items = Some(AlignItems::Start);
            style.align_content = Some(AlignContent::Start);
            style.justify_content = Some(JustifyContent::Start);
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
            .filter(|(_, child)| !is_out_of_flow_transform(child))
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
        Size2 {
            width: match &node.size.width {
                Dimension::Fixed(value) => *value,
                Dimension::Fill { .. } => parent_size.width,
                Dimension::Hug | Dimension::Token { .. } => self.natural_size(node).width,
            },
            height: match &node.size.height {
                Dimension::Fixed(value) => *value,
                Dimension::Fill { .. } => parent_size.height,
                Dimension::Hug | Dimension::Token { .. } => self.natural_size(node).height,
            },
        }
    }

    fn natural_size(&self, node: &Node) -> Size2 {
        match &node.kind {
            NodeKind::Text(text) => estimate_text_size(&text.content, text.font_size, None),
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
            NodeKind::Text(text) => MeasureContext::Text {
                content: text.content.clone(),
                font_size: text.font_size,
            },
            NodeKind::Image(_) => MeasureContext::Box {
                natural: fixed_or_zero(&node.size),
            },
            _ => MeasureContext::Box {
                natural: self.natural_size(node),
            },
        }
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
            },
        );
    }

    fn validate_slots(&mut self) {
        for slot in self.scene.slots.values() {
            self.validate_slot_content(slot);
            self.validate_slot_policy_shape(slot);
            self.validate_slot_bounds(slot);
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
                    self.validate_text_slot_fit(
                        slot,
                        node_id,
                        text.font_size,
                        &geometry,
                        &fixtures,
                    );
                }
            }
        }
    }

    fn validate_text_slot_fit(
        &mut self,
        slot: &Slot,
        node_id: &NodeId,
        font_size: f64,
        geometry: &ComputedGeometry,
        fixtures: &[String],
    ) {
        for fixture in fixtures {
            let fit = text_fit(fixture, font_size, &geometry.layout_bounds, &slot.overflow);
            if fit.fits {
                continue;
            }

            match &slot.overflow {
                OverflowPolicy::Error => {
                    self.diagnostics.push(Diagnostic::error(
                        Phase::Layout,
                        "LUMV0810",
                        format!("slot {} fixture overflows text node {}", slot.key, node_id),
                        Some(DiagnosticSubject::Slot(slot.id.clone())),
                    ));
                }
                OverflowPolicy::ShrinkFont { min_font_size, .. } => {
                    let shrink_fit = text_fit(
                        fixture,
                        *min_font_size,
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
                        self.diagnostics.push(Diagnostic::error(
                            Phase::Layout,
                            "LUMV0812",
                            format!(
                                "slot {} fixture does not fit even at min font size {}",
                                slot.key, min_font_size
                            ),
                            Some(DiagnosticSubject::Slot(slot.id.clone())),
                        ));
                    }
                }
                OverflowPolicy::Wrap { max_lines } => {
                    self.diagnostics.push(Diagnostic::error(
                        Phase::Layout,
                        "LUMV0813",
                        format!(
                            "slot {} fixture needs {} lines but max_lines is {:?}",
                            slot.key, fit.line_count, max_lines
                        ),
                        Some(DiagnosticSubject::Slot(slot.id.clone())),
                    ));
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
    Text { content: String, font_size: f64 },
    Box { natural: Size2 },
}

fn measure_taffy_node(
    known_dimensions: TaffySize<Option<f32>>,
    available_space: TaffySize<AvailableSpace>,
    context: Option<&mut MeasureContext>,
) -> TaffySize<f32> {
    if let TaffySize {
        width: Some(width),
        height: Some(height),
    } = known_dimensions
    {
        return TaffySize { width, height };
    }

    let natural = match context {
        Some(MeasureContext::Text { content, font_size }) => {
            let available_width = available_width(available_space.width);
            estimate_text_size(content, *font_size, available_width)
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

fn estimate_text_size(content: &str, font_size: f64, available_width: Option<f64>) -> Size2 {
    let line_height = text_line_height(font_size);
    let unwrapped_width = estimate_text_width(content, font_size);

    if let Some(width) = available_width.filter(|width| *width > 0.0) {
        let lines = (unwrapped_width / width).ceil().max(1.0);
        Size2 {
            width: unwrapped_width.min(width),
            height: lines * line_height,
        }
    } else {
        Size2 {
            width: unwrapped_width,
            height: line_height,
        }
    }
}

fn estimate_text_width(content: &str, font_size: f64) -> f64 {
    let weighted_chars = content.chars().fold(0.0, |acc, ch| {
        acc + if ch.is_whitespace() {
            0.33
        } else if ch.is_ascii_uppercase() {
            0.62
        } else {
            0.52
        }
    });
    weighted_chars * font_size
}

fn text_line_height(font_size: f64) -> f64 {
    font_size * 1.2
}

fn is_out_of_flow_transform(node: &Node) -> bool {
    node.transform.rotation.abs() > f64::EPSILON
        || node.transform.skew_x.abs() > f64::EPSILON
        || node.transform.skew_y.abs() > f64::EPSILON
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

fn text_fit(content: &str, font_size: f64, bounds: &Rect, policy: &OverflowPolicy) -> TextFit {
    let line_height = text_line_height(font_size);
    let available_lines = if line_height > 0.0 {
        (bounds.height / line_height).floor().max(1.0) as u16
    } else {
        1
    };
    let unwrapped_width = estimate_text_width(content, font_size);

    match policy {
        OverflowPolicy::Wrap { max_lines } => {
            let line_count = if bounds.width > 0.0 {
                (unwrapped_width / bounds.width).ceil().max(1.0) as u16
            } else {
                u16::MAX
            };
            let allowed_lines = max_lines.unwrap_or(available_lines).min(available_lines);
            TextFit {
                fits: line_count <= allowed_lines,
                line_count,
            }
        }
        _ => TextFit {
            fits: unwrapped_width <= bounds.width && line_height <= bounds.height,
            line_count: 1,
        },
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
