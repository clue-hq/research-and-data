use lumen_core::{
    layout_operations, layout_scene, validate_layout, AssetId, AutoLayoutDirection, AutoLayoutNode,
    AutoLayoutProps, Cardinality, ComputedGeometry, ConditionalRule, ContentType, Diagnostic,
    DiagnosticSeverity, Dimension, DocumentId, EmptyBehavior, FocalPoint, HeuristicTextMeasurer,
    ImageFitMode, ImageNode, ImagePolicy, LayoutAnchor, Node, NodeId, NodeKind, Operation,
    Orientation, OverflowPolicy, Page, PageId, PagePreset, PageSize, ParentRef, Rect, ReflowPolicy,
    RepeaterRule, Scene, SizeSpec, Slot, SlotId, SlotKey, TextAlign, TextMeasureInput,
    TextMeasurer, TextNode, Unit, ValidationFixtures, VerticalAlign,
};

fn page(width: f64, height: f64) -> Page {
    Page {
        id: PageId::from("page"),
        name: "Page".to_owned(),
        size: PageSize {
            width,
            height,
            unit: Unit::Px,
            preset: Some(PagePreset::Custom),
            orientation: Orientation::Landscape,
            source: None,
            output: None,
        },
        children: Vec::new(),
        bleed: None,
        safe_area: Some(Rect {
            x: 10.0,
            y: 10.0,
            width: width - 20.0,
            height: height - 20.0,
        }),
        background: Vec::new(),
    }
}

fn scene_with_page(width: f64, height: f64) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc"), "Layout Test");
    scene
        .apply_operation(Operation::AddPage {
            page: page(width, height),
        })
        .unwrap();
    scene
}

fn scene_with_canonical_page(width: f64, height: f64) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_canonical"), "Canonical Layout Test");
    scene
        .apply_operation(Operation::AddPage {
            page: Page {
                id: PageId::from("page"),
                name: "Page".to_owned(),
                size: lumen_core::normalize_page_size(lumen_core::PageSizeInput::new(
                    width,
                    height,
                    Unit::Pt,
                    Some(PagePreset::Custom),
                    Orientation::Landscape,
                )),
                children: Vec::new(),
                bleed: None,
                safe_area: None,
                background: Vec::new(),
            },
        })
        .unwrap();
    scene
}

fn auto_layout(
    id: &str,
    direction: AutoLayoutDirection,
    width: Dimension,
    height: Dimension,
    gap: f64,
    padding: [f64; 4],
    wrap: bool,
) -> Node {
    let mut node = Node::new(
        NodeId::from(id),
        NodeKind::AutoLayout(AutoLayoutNode { direction, wrap }),
    );
    node.size = SizeSpec { width, height };
    node.layout = Some(AutoLayoutProps {
        gap,
        gap_token: None,
        padding,
        padding_token: None,
        grow: 0.0,
        ..AutoLayoutProps::default()
    });
    node
}

fn rect(id: &str, width: Dimension, height: Dimension) -> Node {
    let mut node = Node::new(NodeId::from(id), NodeKind::Rect);
    node.size = SizeSpec { width, height };
    node
}

fn text_node(id: &str, content: &str, x: f64, y: f64, width: f64, height: f64) -> Node {
    let mut node = Node::new(
        NodeId::from(id),
        NodeKind::Text(TextNode {
            content: content.to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 12.0,
            font_weight: 600,
            align: TextAlign::Left,
            style_token: None,
            ..TextNode::default()
        }),
    );
    node.transform.x = x;
    node.transform.y = y;
    node.size = SizeSpec::fixed(width, height);
    node
}

fn text_node_with_font(
    id: &str,
    content: &str,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    font_size: f64,
) -> Node {
    let mut node = text_node(id, content, x, y, width, height);
    if let NodeKind::Text(text) = &mut node.kind {
        text.font_size = font_size;
    }
    node
}

fn image_node(id: &str, x: f64, y: f64, width: f64, height: f64) -> Node {
    let mut node = Node::new(
        NodeId::from(id),
        NodeKind::Image(ImageNode {
            asset_id: AssetId::from("asset_logo"),
            alt: Some("Logo".to_owned()),
        }),
    );
    node.transform.x = x;
    node.transform.y = y;
    node.size = SizeSpec::fixed(width, height);
    node
}

fn insert(scene: &mut Scene, parent: ParentRef, node: Node) {
    let index = match &parent {
        ParentRef::Page(page_id) => scene.pages[page_id].children.len(),
        ParentRef::Node(node_id) => scene.nodes[node_id].children.len(),
    };
    scene
        .apply_operation(Operation::InsertNode {
            parent,
            index,
            node,
        })
        .unwrap();
}

fn bind_slot(scene: &mut Scene, mut slot: Slot, node_id: &str) {
    let slot_id = slot.id.clone();
    slot.bound_nodes.push(NodeId::from(node_id));
    scene
        .apply_operation(Operation::UpsertSlot { slot })
        .unwrap();
    scene
        .apply_operation(Operation::BindNodeToSlot {
            slot_id,
            node_id: NodeId::from(node_id),
        })
        .unwrap();
}

fn text_slot(id: &str) -> Slot {
    Slot::text_short(SlotId::from(id), SlotKey::from(id), id)
}

fn assert_close(actual: f64, expected: f64) {
    assert!(
        (actual - expected).abs() < 0.5,
        "expected {actual} to be close to {expected}"
    );
}

fn has_code(diagnostics: &[Diagnostic], code: &str) -> bool {
    diagnostics.iter().any(|diagnostic| diagnostic.code == code)
}

#[test]
fn canonical_a4_accepts_point_sized_background_without_page_overflow() {
    let mut scene = scene_with_canonical_page(595.275_590_551_181_2, 841.889_763_779_527_6);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        rect(
            "bg",
            Dimension::Fixed(595.275_590_551_181_2),
            Dimension::Fixed(841.889_763_779_527_6),
        ),
    );

    let diagnostics = validate_layout(&scene, lumen_core::LayoutOptions::default());

    assert!(!has_code(&diagnostics, "LUMV0800"), "{diagnostics:#?}");
    assert!(diagnostics
        .iter()
        .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error));
}

#[test]
fn fill_artboard_rounding_does_not_emit_page_bounds_error() {
    // A4 portrait exportable height is 841.889…pt, but a `fill,fill` root artboard
    // resolves to the rounded 842.0pt preset height. The ~0.11pt difference is a
    // float-rounding artifact, not a real overflow, and must NOT emit a hard
    // LUMV0800 that the repair loop can never clear.
    let mut scene = scene_with_canonical_page(595.275_590_551_181_2, 841.889_763_779_527_6);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        rect(
            "artboard",
            Dimension::Fixed(595.275_590_551_181_2),
            Dimension::Fixed(842.0),
        ),
    );

    let diagnostics = validate_layout(&scene, lumen_core::LayoutOptions::default());

    assert!(!has_code(&diagnostics, "LUMV0800"), "{diagnostics:#?}");
}

#[test]
fn canonical_page_child_exceeding_artboard_emits_bounds_error() {
    let mut scene = scene_with_canonical_page(595.275_590_551_181_2, 841.889_763_779_527_6);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        rect(
            "oversized",
            Dimension::Fixed(700.0),
            Dimension::Fixed(900.0),
        ),
    );

    let diagnostics = validate_layout(&scene, lumen_core::LayoutOptions::default());

    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMV0800" && diagnostic.severity == DiagnosticSeverity::Error
    }));
}

#[test]
fn clipped_parent_child_overflow_emits_parent_bounds_error() {
    let mut scene = scene_with_canonical_page(300.0, 300.0);
    let mut parent = Node::new(NodeId::from("card"), NodeKind::Frame);
    parent.transform.x = 20.0;
    parent.transform.y = 20.0;
    parent.size = SizeSpec::fixed(100.0, 100.0);
    parent.clip = true;
    insert(&mut scene, ParentRef::Page(PageId::from("page")), parent);

    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("card")),
        rect(
            "wide_child",
            Dimension::Fixed(150.0),
            Dimension::Fixed(40.0),
        ),
    );

    let diagnostics = validate_layout(&scene, lumen_core::LayoutOptions::default());

    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMV0801" && diagnostic.severity == DiagnosticSeverity::Error
    }));
}

#[test]
fn child_outside_trim_inside_bleed_emits_bleed_warning() {
    let mut scene = scene_with_canonical_page(100.0, 100.0);
    scene.pages.get_mut(&PageId::from("page")).unwrap().bleed = Some(Rect {
        x: -10.0,
        y: -10.0,
        width: 120.0,
        height: 120.0,
    });
    let mut crop_mark = rect("crop_mark", Dimension::Fixed(10.0), Dimension::Fixed(10.0));
    crop_mark.transform.x = -5.0;
    crop_mark.transform.y = 10.0;
    insert(&mut scene, ParentRef::Page(PageId::from("page")), crop_mark);

    let diagnostics = validate_layout(&scene, lumen_core::LayoutOptions::default());

    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMV0802" && diagnostic.severity == DiagnosticSeverity::Warning
    }));
    assert!(!has_code(&diagnostics, "LUMV0800"), "{diagnostics:#?}");
}

#[test]
fn legacy_non_pt_page_emits_advice_without_blocking_validation() {
    let scene = scene_with_page(210.0, 297.0);

    let diagnostics = lumen_core::validation::validate_scene(&scene);

    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUMV0805" && diagnostic.severity == DiagnosticSeverity::Advice
    }));
    assert!(diagnostics
        .iter()
        .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error));
}

#[test]
fn row_layout_positions_fixed_children() {
    let mut scene = scene_with_page(400.0, 300.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        auto_layout(
            "row",
            AutoLayoutDirection::Row,
            Dimension::Fixed(200.0),
            Dimension::Fixed(80.0),
            0.0,
            [0.0; 4],
            false,
        ),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("a", Dimension::Fixed(50.0), Dimension::Fixed(20.0)),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("b", Dimension::Fixed(30.0), Dimension::Fixed(20.0)),
    );

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );
    assert_close(result.geometry[&NodeId::from("a")].layout_bounds.x, 0.0);
    assert_close(result.geometry[&NodeId::from("b")].layout_bounds.x, 50.0);
}

#[test]
fn plain_text_overflow_is_diagnosed_without_slot() {
    let mut scene = scene_with_page(400.0, 300.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        text_node_with_font(
            "headline",
            "A very long neurosurgery practice headline that cannot fit",
            24.0,
            24.0,
            120.0,
            24.0,
            24.0,
        ),
    );

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );

    assert!(has_code(&result.diagnostics, "LUMV0902"));
}

#[test]
fn bottom_valign_overflowing_fixed_box_still_emits_vertical_overflow() {
    // A7a D3: valign changes paint position only, never geometry. A bottom-
    // aligned text node whose content overflows its Fixed-height box must still
    // emit LUMV0903 — validation compares measured height vs bounds and never
    // sees the paint offset.
    let mut scene = scene_with_page(400.0, 300.0);
    let mut node = text_node_with_font(
        "overflow",
        "Line one\nLine two\nLine three\nLine four\nLine five",
        24.0,
        24.0,
        320.0,
        30.0, // far too short for five wrapped/broken lines
        24.0,
    );
    if let NodeKind::Text(text) = &mut node.kind {
        text.valign = lumen_core::VerticalAlign::Bottom;
        text.wrap = lumen_core::TextWrap::Wrap;
    }
    insert(&mut scene, ParentRef::Page(PageId::from("page")), node);

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );

    assert!(has_code(&result.diagnostics, "LUMV0903"));
}

#[test]
fn column_layout_positions_fixed_children() {
    let mut scene = scene_with_page(400.0, 300.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        auto_layout(
            "column",
            AutoLayoutDirection::Column,
            Dimension::Fixed(100.0),
            Dimension::Fixed(200.0),
            0.0,
            [0.0; 4],
            false,
        ),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("column")),
        rect("a", Dimension::Fixed(30.0), Dimension::Fixed(40.0)),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("column")),
        rect("b", Dimension::Fixed(30.0), Dimension::Fixed(25.0)),
    );

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );
    assert_close(result.geometry[&NodeId::from("a")].layout_bounds.y, 0.0);
    assert_close(result.geometry[&NodeId::from("b")].layout_bounds.y, 40.0);
}

#[test]
fn autolayout_row_x_center_positions_children() {
    let mut scene = scene_with_page(400.0, 300.0);
    let mut row = auto_layout(
        "row",
        AutoLayoutDirection::Row,
        Dimension::Fixed(200.0),
        Dimension::Fixed(80.0),
        0.0,
        [0.0; 4],
        false,
    );
    row.layout.as_mut().unwrap().align_x = LayoutAnchor::Center;
    insert(&mut scene, ParentRef::Page(PageId::from("page")), row);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("a", Dimension::Fixed(50.0), Dimension::Fixed(20.0)),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("b", Dimension::Fixed(30.0), Dimension::Fixed(20.0)),
    );

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );
    assert_close(result.geometry[&NodeId::from("a")].layout_bounds.x, 60.0);
    assert_close(result.geometry[&NodeId::from("b")].layout_bounds.x, 110.0);
}

#[test]
fn autolayout_row_x_space_between_distributes_children() {
    let mut scene = scene_with_page(400.0, 300.0);
    let mut row = auto_layout(
        "row",
        AutoLayoutDirection::Row,
        Dimension::Fixed(200.0),
        Dimension::Fixed(80.0),
        0.0,
        [0.0; 4],
        false,
    );
    row.layout.as_mut().unwrap().align_x = LayoutAnchor::SpaceBetween;
    insert(&mut scene, ParentRef::Page(PageId::from("page")), row);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("a", Dimension::Fixed(50.0), Dimension::Fixed(20.0)),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("b", Dimension::Fixed(30.0), Dimension::Fixed(20.0)),
    );

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );
    assert_close(result.geometry[&NodeId::from("a")].layout_bounds.x, 0.0);
    assert_close(result.geometry[&NodeId::from("b")].layout_bounds.x, 170.0);
}

#[test]
fn autolayout_row_y_center_cross_aligns_children() {
    let mut scene = scene_with_page(400.0, 300.0);
    let mut row = auto_layout(
        "row",
        AutoLayoutDirection::Row,
        Dimension::Fixed(200.0),
        Dimension::Fixed(80.0),
        0.0,
        [0.0; 4],
        false,
    );
    row.layout.as_mut().unwrap().align_y = LayoutAnchor::Center;
    insert(&mut scene, ParentRef::Page(PageId::from("page")), row);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("a", Dimension::Fixed(50.0), Dimension::Fixed(20.0)),
    );

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );
    assert_close(result.geometry[&NodeId::from("a")].layout_bounds.y, 30.0);
}

#[test]
fn gap_and_padding_offset_children() {
    let mut scene = scene_with_page(400.0, 300.0);
    let mut row = auto_layout(
        "row",
        AutoLayoutDirection::Row,
        Dimension::Fixed(200.0),
        Dimension::Fixed(80.0),
        8.0,
        [10.0, 20.0, 30.0, 40.0],
        false,
    );
    row.transform.x = 10.0;
    row.transform.y = 20.0;
    insert(&mut scene, ParentRef::Page(PageId::from("page")), row);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("a", Dimension::Fixed(30.0), Dimension::Fixed(20.0)),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("b", Dimension::Fixed(30.0), Dimension::Fixed(20.0)),
    );

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );
    assert_close(result.geometry[&NodeId::from("a")].layout_bounds.x, 50.0);
    assert_close(result.geometry[&NodeId::from("a")].layout_bounds.y, 30.0);
    assert_close(result.geometry[&NodeId::from("b")].layout_bounds.x, 88.0);
}

#[test]
fn weighted_fill_distributes_free_space() {
    let mut scene = scene_with_page(400.0, 300.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        auto_layout(
            "row",
            AutoLayoutDirection::Row,
            Dimension::Fixed(300.0),
            Dimension::Fixed(40.0),
            10.0,
            [0.0; 4],
            false,
        ),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("fixed", Dimension::Fixed(50.0), Dimension::Fixed(20.0)),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect(
            "fill_one",
            Dimension::Fill { weight: 1.0 },
            Dimension::Fixed(20.0),
        ),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect(
            "fill_two",
            Dimension::Fill { weight: 2.0 },
            Dimension::Fixed(20.0),
        ),
    );

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );
    assert_close(
        result.geometry[&NodeId::from("fill_one")]
            .layout_bounds
            .width,
        76.67,
    );
    assert_close(
        result.geometry[&NodeId::from("fill_two")]
            .layout_bounds
            .width,
        153.33,
    );
}

#[test]
fn hug_parent_sizes_to_children_gap_and_padding() {
    let mut scene = scene_with_page(400.0, 300.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        auto_layout(
            "row",
            AutoLayoutDirection::Row,
            Dimension::Hug,
            Dimension::Hug,
            10.0,
            [5.0, 5.0, 5.0, 5.0],
            false,
        ),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("a", Dimension::Fixed(30.0), Dimension::Fixed(20.0)),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("b", Dimension::Fixed(40.0), Dimension::Fixed(10.0)),
    );

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );
    assert_close(
        result.geometry[&NodeId::from("row")].layout_bounds.width,
        90.0,
    );
    assert_close(
        result.geometry[&NodeId::from("row")].layout_bounds.height,
        30.0,
    );
}

#[test]
fn fill_child_falls_back_to_hug_when_parent_has_no_free_space() {
    let mut scene = scene_with_page(400.0, 300.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        auto_layout(
            "row",
            AutoLayoutDirection::Row,
            Dimension::Hug,
            Dimension::Hug,
            0.0,
            [0.0; 4],
            false,
        ),
    );
    let mut child = text_node_with_font("headline", "Fallback", 0.0, 0.0, 0.0, 0.0, 10.0);
    child.size = SizeSpec {
        width: Dimension::Fill { weight: 1.0 },
        height: Dimension::Hug,
    };
    insert(&mut scene, ParentRef::Node(NodeId::from("row")), child);

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );
    let child_width = result.geometry[&NodeId::from("headline")]
        .layout_bounds
        .width;
    assert!(child_width > 30.0);
    assert_close(
        result.geometry[&NodeId::from("row")].layout_bounds.width,
        child_width,
    );
}

#[test]
fn wrapping_flows_children_to_multiple_lines() {
    let mut scene = scene_with_page(400.0, 300.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        auto_layout(
            "row",
            AutoLayoutDirection::Row,
            Dimension::Fixed(100.0),
            Dimension::Hug,
            0.0,
            [0.0; 4],
            true,
        ),
    );
    for id in ["a", "b", "c"] {
        insert(
            &mut scene,
            ParentRef::Node(NodeId::from("row")),
            rect(id, Dimension::Fixed(45.0), Dimension::Fixed(20.0)),
        );
    }

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );
    assert_close(result.geometry[&NodeId::from("c")].layout_bounds.y, 20.0);
    assert_close(
        result.geometry[&NodeId::from("row")].layout_bounds.height,
        40.0,
    );
}

#[test]
fn transformed_child_is_excluded_from_auto_layout_flow() {
    let mut scene = scene_with_page(400.0, 300.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        auto_layout(
            "row",
            AutoLayoutDirection::Row,
            Dimension::Fixed(200.0),
            Dimension::Fixed(100.0),
            0.0,
            [0.0; 4],
            false,
        ),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("a", Dimension::Fixed(40.0), Dimension::Fixed(20.0)),
    );
    let mut rotated = rect("rotated", Dimension::Fixed(40.0), Dimension::Fixed(20.0));
    rotated.transform.x = 100.0;
    rotated.transform.y = 40.0;
    rotated.transform.rotation = 45.0;
    insert(&mut scene, ParentRef::Node(NodeId::from("row")), rotated);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("b", Dimension::Fixed(40.0), Dimension::Fixed(20.0)),
    );

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );
    assert!(has_code(&result.diagnostics, "LUMV0701"));
    assert_close(result.geometry[&NodeId::from("b")].layout_bounds.x, 40.0);
    assert_close(
        result.geometry[&NodeId::from("rotated")].layout_bounds.x,
        100.0,
    );
    assert!(
        result.geometry[&NodeId::from("rotated")]
            .render_bounds
            .height
            > 20.0
    );
}

#[test]
fn layout_operations_persist_computed_geometry() {
    let mut scene = scene_with_page(400.0, 300.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        auto_layout(
            "row",
            AutoLayoutDirection::Row,
            Dimension::Fixed(100.0),
            Dimension::Fixed(50.0),
            0.0,
            [0.0; 4],
            false,
        ),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("a", Dimension::Fixed(40.0), Dimension::Fixed(20.0)),
    );

    let operations = layout_operations(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );
    scene.apply_operations(operations).unwrap();

    let computed = scene.nodes[&NodeId::from("a")].computed.as_ref().unwrap();
    assert_close(computed.layout_bounds.width, 40.0);
}

#[test]
fn required_slot_without_usable_content_is_an_error() {
    let mut scene = scene_with_page(120.0, 120.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        text_node("name", "", 20.0, 20.0, 80.0, 20.0),
    );
    let slot = text_slot("slot_name");
    bind_slot(&mut scene, slot, "name");

    let diagnostics = validate_layout(&scene, lumen_core::LayoutOptions::default());
    assert!(has_code(&diagnostics, "LUMV0800"));
}

#[test]
fn text_fixture_that_fits_has_no_text_fit_error() {
    let mut scene = scene_with_page(160.0, 120.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        text_node("name", "Short", 20.0, 20.0, 100.0, 24.0),
    );
    let mut slot = text_slot("slot_name");
    slot.placeholder = Some("Short".to_owned());
    slot.validation.samples = vec!["Still short".to_owned()];
    bind_slot(&mut scene, slot, "name");

    let diagnostics = validate_layout(&scene, lumen_core::LayoutOptions::default());
    assert!(!has_code(&diagnostics, "LUMV0810"), "{diagnostics:#?}");
    assert!(diagnostics
        .iter()
        .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error));
}

#[test]
fn slot_fit_uses_node_line_height_not_hardcoded_1_2() {
    // A slotted single-line node with a sub-1.2 line height and a tight box must NOT
    // report a false LUMV0810. The fixture-fit check must measure with the node's OWN
    // lh (1.0 here → ~20pt), not a hardcoded 1.2 (→ ~24pt, which falsely overflowed
    // the 23pt box and blocked legible hug heights and tight headlines).
    let mut scene = scene_with_page(200.0, 200.0);
    let mut node = text_node_with_font("name", "Short", 20.0, 20.0, 160.0, 23.0, 20.0);
    if let NodeKind::Text(text) = &mut node.kind {
        text.line_height = 1.0;
    }
    insert(&mut scene, ParentRef::Page(PageId::from("page")), node);
    let mut slot = text_slot("slot_name");
    slot.placeholder = Some("Short".to_owned());
    slot.validation.samples = vec!["Short".to_owned()];
    bind_slot(&mut scene, slot, "name");

    let diagnostics = validate_layout(&scene, lumen_core::LayoutOptions::default());
    assert!(!has_code(&diagnostics, "LUMV0810"), "{diagnostics:#?}");
}

#[test]
fn unresolved_token_dimensions_warn_and_use_natural_size() {
    let mut scene = scene_with_page(300.0, 200.0);
    let mut headline = text_node("headline", "Token sized headline", 0.0, 0.0, 100.0, 24.0);
    headline.size.width = Dimension::Token {
        token: "size.heading.width".to_owned(),
    };
    insert(&mut scene, ParentRef::Page(PageId::from("page")), headline);

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions {
            validate_slots: false,
            ..Default::default()
        },
    );

    assert!(has_code(&result.diagnostics, "LUMV0702"));
    assert!(
        result.geometry[&NodeId::from("headline")]
            .layout_bounds
            .width
            > 0.0
    );
}

#[test]
fn error_overflow_policy_reports_text_fixture_overflow() {
    let mut scene = scene_with_page(160.0, 120.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        text_node("name", "Short", 20.0, 20.0, 40.0, 12.0),
    );
    let mut slot = text_slot("slot_name");
    slot.placeholder = Some("Very long account name".to_owned());
    slot.overflow = OverflowPolicy::Error;
    bind_slot(&mut scene, slot, "name");

    let diagnostics = validate_layout(&scene, lumen_core::LayoutOptions::default());
    assert!(has_code(&diagnostics, "LUMV0810"));
}

#[test]
fn shrink_font_policy_reports_feasibility_without_mutating_font_size() {
    let mut scene = scene_with_page(160.0, 120.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        text_node_with_font("headline", "MMMMMM", 20.0, 20.0, 70.0, 24.0, 20.0),
    );
    let mut slot = text_slot("slot_headline");
    slot.placeholder = Some("MMMMMM".to_owned());
    slot.overflow = OverflowPolicy::ShrinkFont {
        min_font_size: 10.0,
        max_font_size: Some(20.0),
    };
    bind_slot(&mut scene, slot, "headline");

    let result = layout_scene(&scene, lumen_core::LayoutOptions::default());
    assert!(has_code(&result.diagnostics, "LUMV0811"));
    let NodeKind::Text(text) = &scene.nodes[&NodeId::from("headline")].kind else {
        panic!("expected text node");
    };
    assert_close(text.font_size, 20.0);
}

#[test]
fn wrap_policy_reports_max_line_overflow() {
    let mut scene = scene_with_page(180.0, 180.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        text_node_with_font("body", "Body", 20.0, 20.0, 50.0, 120.0, 10.0),
    );
    let mut slot = text_slot("slot_body");
    slot.placeholder = Some("MMMMMMMMMMMMMMMMMMMM".to_owned());
    slot.overflow = OverflowPolicy::Wrap { max_lines: Some(2) };
    bind_slot(&mut scene, slot, "body");

    let diagnostics = validate_layout(&scene, lumen_core::LayoutOptions::default());
    assert!(has_code(&diagnostics, "LUMV0813"));
}

#[test]
fn ellipsis_and_clip_policies_warn_about_lossy_overflow() {
    let mut scene = scene_with_page(220.0, 160.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        text_node("cta", "CTA", 20.0, 20.0, 35.0, 18.0),
    );
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        text_node("clip", "Clip", 20.0, 50.0, 35.0, 18.0),
    );
    let mut ellipsis = text_slot("slot_cta");
    ellipsis.placeholder = Some("Download the complete pathway".to_owned());
    ellipsis.overflow = OverflowPolicy::Ellipsis;
    bind_slot(&mut scene, ellipsis, "cta");

    let mut clip = text_slot("slot_clip");
    clip.placeholder = Some("Download the complete pathway".to_owned());
    clip.overflow = OverflowPolicy::Clip;
    bind_slot(&mut scene, clip, "clip");

    let diagnostics = validate_layout(&scene, lumen_core::LayoutOptions::default());
    assert_eq!(
        diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code == "LUMV0814")
            .count(),
        2
    );
}

#[test]
fn required_slot_outside_safe_area_is_an_error() {
    let mut scene = scene_with_page(120.0, 120.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        text_node("name", "Name", 95.0, 95.0, 20.0, 20.0),
    );
    let mut slot = text_slot("slot_name");
    slot.placeholder = Some("Name".to_owned());
    bind_slot(&mut scene, slot, "name");

    let diagnostics = validate_layout(&scene, lumen_core::LayoutOptions::default());
    assert!(has_code(&diagnostics, "LUMV0803"));
}

#[test]
fn image_slot_policy_shape_is_validated() {
    let mut scene = scene_with_page(160.0, 160.0);
    scene.meta.medium = Some(lumen_core::Medium::Print);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        image_node("logo", 20.0, 20.0, 40.0, 40.0),
    );
    let mut slot = text_slot("slot_logo");
    slot.content_type = ContentType::Logo;
    slot.placeholder = Some("Logo".to_owned());
    slot.image_policy = Some(ImagePolicy {
        fit: ImageFitMode::Crop,
        focal_point: Some(FocalPoint { x: 1.5, y: -0.2 }),
        min_dpi: None,
        preserve_transparency: true,
        aspect_ratio: Some(0.0),
    });
    bind_slot(&mut scene, slot, "logo");

    let diagnostics = validate_layout(&scene, lumen_core::LayoutOptions::default());
    assert!(has_code(&diagnostics, "LUMV0821"));
    assert!(has_code(&diagnostics, "LUMV0822"));
    assert!(has_code(&diagnostics, "LUMV0823"));
}

#[test]
fn repeater_and_conditional_scaffolds_are_validated() {
    let mut scene = scene_with_page(160.0, 160.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        text_node("items", "Items", 20.0, 20.0, 80.0, 20.0),
    );
    let mut slot = text_slot("slot_items");
    slot.content_type = ContentType::RepeaterGroup;
    slot.placeholder = Some("Items".to_owned());
    slot.cardinality = Cardinality {
        min_items: 1,
        max_items: Some(3),
    };
    slot.conditional = Some(ConditionalRule {
        expression: " ".to_owned(),
        when_false: EmptyBehavior::UseFallback,
    });
    slot.repeater = Some(RepeaterRule {
        template_node_id: NodeId::from("missing_template"),
        item_slot_key: SlotKey::from("items.item"),
        min_items: 3,
        max_items: Some(2),
        reflow: ReflowPolicy::Paginate,
    });
    slot.validation = ValidationFixtures {
        samples: Vec::new(),
        worst_case: None,
        max_length: None,
    };
    bind_slot(&mut scene, slot, "items");

    let diagnostics = validate_layout(&scene, lumen_core::LayoutOptions::default());
    assert!(has_code(&diagnostics, "LUMV0830"));
    assert!(has_code(&diagnostics, "LUMV0841"));
    assert!(has_code(&diagnostics, "LUMV0842"));
    assert!(has_code(&diagnostics, "LUMV0843"));
}

#[test]
fn truncate_with_no_max_lines_and_wrap_advises_lumv0905() {
    // A6a D3: truncate on freely-wrapping text with no max_lines can never
    // fire — teach with an advisory, don't block.
    let mut scene = scene_with_page(400.0, 300.0);
    let mut node = text_node("body", "wrapping copy that never truncates", 24.0, 24.0, 200.0, 80.0);
    if let NodeKind::Text(text) = &mut node.kind {
        text.wrap = lumen_core::TextWrap::Wrap;
        text.truncate = true;
        text.max_lines = None;
    }
    insert(&mut scene, ParentRef::Page(PageId::from("page")), node);

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions { validate_slots: false, ..Default::default() },
    );
    assert!(has_code(&result.diagnostics, "LUMV0905"), "{:#?}", result.diagnostics);
}

#[test]
fn truncate_with_max_lines_does_not_advise_lumv0905() {
    let mut scene = scene_with_page(400.0, 300.0);
    let mut node = text_node("body", "copy", 24.0, 24.0, 200.0, 80.0);
    if let NodeKind::Text(text) = &mut node.kind {
        text.wrap = lumen_core::TextWrap::Wrap;
        text.truncate = true;
        text.max_lines = Some(2);
    }
    insert(&mut scene, ParentRef::Page(PageId::from("page")), node);

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions { validate_slots: false, ..Default::default() },
    );
    assert!(!has_code(&result.diagnostics, "LUMV0905"));
}

#[test]
fn negative_paragraph_spacing_is_an_invalid_metric_lumv0900() {
    let mut scene = scene_with_page(400.0, 300.0);
    let mut node = text_node("body", "copy", 24.0, 24.0, 200.0, 80.0);
    if let NodeKind::Text(text) = &mut node.kind {
        text.paragraph_spacing = -4.0;
    }
    insert(&mut scene, ParentRef::Page(PageId::from("page")), node);

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions { validate_slots: false, ..Default::default() },
    );
    assert!(has_code(&result.diagnostics, "LUMV0900"), "{:#?}", result.diagnostics);
}

#[test]
fn invalid_ops_injected_span_errors_lumv0906_at_the_gate() {
    // A6b D3 end-to-end: the LAYOUT GATE (not just the unit helper) must
    // reject an out-of-bounds ops-injected span before measurement.
    let mut scene = scene_with_page(400.0, 300.0);
    let mut node = text_node("body", "hello", 24.0, 24.0, 200.0, 80.0);
    if let NodeKind::Text(text) = &mut node.kind {
        text.spans = vec![lumen_core::TextSpan {
            start: 2,
            end: 99,
            fill: None,
            font_weight: Some(800),
            underline: None,
            strikethrough: None,
            italic: None,
        }];
    }
    insert(&mut scene, ParentRef::Page(PageId::from("page")), node);

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions { validate_slots: false, ..Default::default() },
    );
    assert!(has_code(&result.diagnostics, "LUMV0906"), "{:#?}", result.diagnostics);
}

#[test]
fn spans_with_paragraph_spacing_advise_lumv0907() {
    // A6b v1 limitation must be LOUD: the segmented span path does not apply
    // the paragraph gap, so authored para_spacing on spanned multi-stanza
    // text advises instead of silently dropping the air.
    let mut scene = scene_with_page(400.0, 300.0);
    let mut node = text_node("body", "alpha\\nbeta", 24.0, 24.0, 200.0, 120.0);
    if let NodeKind::Text(text) = &mut node.kind {
        text.paragraph_spacing = 16.0;
        text.spans = vec![lumen_core::TextSpan {
            start: 0,
            end: 5,
            fill: None,
            font_weight: Some(800),
            underline: None,
            strikethrough: None,
            italic: None,
        }];
    }
    insert(&mut scene, ParentRef::Page(PageId::from("page")), node);

    let result = layout_scene(
        &scene,
        lumen_core::LayoutOptions { validate_slots: false, ..Default::default() },
    );
    assert!(has_code(&result.diagnostics, "LUMV0907"), "{:#?}", result.diagnostics);

    // Without spans the same node measures with the gap and must NOT advise.
    let mut clean = scene_with_page(400.0, 300.0);
    let mut plain = text_node("body2", "alpha\\nbeta", 24.0, 24.0, 200.0, 120.0);
    if let NodeKind::Text(text) = &mut plain.kind {
        text.paragraph_spacing = 16.0;
    }
    insert(&mut clean, ParentRef::Page(PageId::from("page")), plain);
    let result = layout_scene(
        &clean,
        lumen_core::LayoutOptions { validate_slots: false, ..Default::default() },
    );
    assert!(!has_code(&result.diagnostics, "LUMV0907"), "{:#?}", result.diagnostics);
}

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

    let measured = HeuristicTextMeasurer
        .measure(&TextMeasureInput::from_text_node(&text).with_bounds(&geometry.layout_bounds));
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
    assert!(result.geometry[&NodeId::from("plate")]
        .text_lines
        .is_empty());
}

#[test]
fn text_lines_serialize_only_when_present_and_default_when_absent() {
    let rect = Rect {
        x: 1.0,
        y: 2.0,
        width: 3.0,
        height: 4.0,
    };
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

    let placed = ComputedGeometry {
        text_lines: vec![rect.clone()],
        ..empty
    };
    let json = serde_json::to_value(&placed).expect("serializes");
    assert_eq!(json["text_lines"][0]["width"], 3.0);
}

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
    let NodeKind::Text(text) = &mut copy.kind else {
        unreachable!("text_node builds a text node");
    };
    text.wrap = lumen_core::TextWrap::Wrap;
    let text = text.clone();
    insert(&mut scene, ParentRef::Page(PageId::from("page")), copy);

    let result = layout_scene(&scene, lumen_core::LayoutOptions::default());
    let bounds = &result.geometry[&NodeId::from("copy")].layout_bounds;
    let expected = r8_expected_height(&text, 120.0);
    let unbounded = HeuristicTextMeasurer
        .measure(&TextMeasureInput::from_text_node(&text))
        .height;
    assert!(
        expected > unbounded,
        "the copy must wrap at 120 for this test to mean anything"
    );
    assert_eq!(bounds.width, 120.0);
    assert_eq!(
        bounds.height, expected,
        "hug height is the WRAPPED height, not {unbounded}"
    );
}

#[test]
fn fixed_width_text_inside_a_stack_hugs_its_wrapped_height() {
    // The taffy path: the leaf's own definite width is the wrap width, not the
    // 600-wide column's available space.
    let mut scene = scene_with_page(600.0, 400.0);
    let column = auto_layout(
        "column",
        AutoLayoutDirection::Column,
        Dimension::Fixed(600.0),
        Dimension::Hug,
        0.0,
        [0.0; 4],
        false,
    );
    insert(&mut scene, ParentRef::Page(PageId::from("page")), column);
    let mut copy = text_node("copy", R8_COPY, 0.0, 0.0, 120.0, 0.0);
    copy.size.height = Dimension::Hug;
    let NodeKind::Text(text) = &mut copy.kind else {
        unreachable!("text_node builds a text node");
    };
    text.wrap = lumen_core::TextWrap::Wrap;
    let text = text.clone();
    insert(&mut scene, ParentRef::Node(NodeId::from("column")), copy);

    let result = layout_scene(&scene, lumen_core::LayoutOptions::default());
    let bounds = &result.geometry[&NodeId::from("copy")].layout_bounds;
    // Taffy rounds to whole pixels; the plan's own ROUNDING_TOLERANCE.
    assert!(
        (bounds.height - r8_expected_height(&text, 120.0)).abs() <= 0.51,
        "{bounds:?}"
    );
}

#[test]
fn hug_width_text_still_measures_unbounded() {
    let mut scene = scene_with_page(600.0, 400.0);
    let mut copy = text_node("copy", R8_COPY, 20.0, 20.0, 0.0, 0.0);
    copy.size = SizeSpec {
        width: Dimension::Hug,
        height: Dimension::Hug,
    };
    let NodeKind::Text(text) = &mut copy.kind else {
        unreachable!("text_node builds a text node");
    };
    text.wrap = lumen_core::TextWrap::Wrap;
    let text = text.clone();
    insert(&mut scene, ParentRef::Page(PageId::from("page")), copy);

    let result = layout_scene(&scene, lumen_core::LayoutOptions::default());
    let bounds = &result.geometry[&NodeId::from("copy")].layout_bounds;
    let unbounded = HeuristicTextMeasurer.measure(&TextMeasureInput::from_text_node(&text));
    assert_eq!(bounds.width, unbounded.width);
    assert_eq!(bounds.height, unbounded.height);
}
