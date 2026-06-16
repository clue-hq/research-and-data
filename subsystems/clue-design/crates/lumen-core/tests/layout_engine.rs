use lumen_core::{
    layout_operations, layout_scene, validate_layout, AssetId, AutoLayoutDirection, AutoLayoutNode,
    AutoLayoutProps, Cardinality, ConditionalRule, ContentType, Diagnostic, DiagnosticSeverity,
    Dimension, DocumentId, EmptyBehavior, FocalPoint, ImageFitMode, ImageNode, ImagePolicy,
    LayoutAnchor, Node, NodeId, NodeKind, Operation, Orientation, OverflowPolicy, Page, PageId,
    PagePreset, PageSize, ParentRef, Rect, ReflowPolicy, RepeaterRule, Scene, SizeSpec, Slot,
    SlotId, SlotKey, TextAlign, TextNode, Unit, ValidationFixtures,
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
