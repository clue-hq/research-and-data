//! Phase 1b gate — the solver honors the freehand fields. A pinned node
//! (`position_mode: absolute` + `absolute_box`) lays out at its box and
//! stops snapping back across relayouts, a Free container lays children at
//! their baked transforms, managed siblings reflow around detached nodes,
//! and the clip policy (user decision 2026-07-03) downgrades
//! LUMV0800/LUMV0801 to warnings for freehand nodes only — managed content
//! keeps today's fail-closed errors.

use lumen_core::{
    layout_operations, layout_scene, validate_layout, AutoLayoutDirection, AutoLayoutNode,
    AutoLayoutProps, Diagnostic, DiagnosticSeverity, DiagnosticSubject, Dimension, DocumentId,
    FieldPatch, LayoutMode, LayoutOptions, Node, NodeId, NodeKind, NodePatch, Operation,
    Orientation, OptionalFieldPatch, Page, PageId, PagePreset, PageSize, ParentRef, PositionMode,
    Rect, Scene, SizeSpec, Unit,
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
        safe_area: None,
        background: Vec::new(),
    }
}

fn scene_with_page(width: f64, height: f64) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_freehand_layout"), "Freehand Layout");
    scene
        .apply_operation(Operation::AddPage {
            page: page(width, height),
        })
        .unwrap();
    scene
}

fn scene_with_canonical_page(width: f64, height: f64) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_freehand_canonical"), "Freehand Pt");
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
) -> Node {
    let mut node = Node::new(
        NodeId::from(id),
        NodeKind::AutoLayout(AutoLayoutNode {
            direction,
            wrap: false,
        }),
    );
    node.size = SizeSpec { width, height };
    node.layout = Some(AutoLayoutProps {
        gap,
        ..AutoLayoutProps::default()
    });
    node
}

fn rect(id: &str, width: f64, height: f64) -> Node {
    let mut node = Node::new(NodeId::from(id), NodeKind::Rect);
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

fn pin(scene: &mut Scene, id: &str, x: f64, y: f64, width: f64, height: f64) -> Rect {
    let pin = Rect {
        x,
        y,
        width,
        height,
    };
    let node = scene.nodes.get_mut(&NodeId::from(id)).unwrap();
    node.position_mode = PositionMode::Absolute;
    node.absolute_box = Some(pin.clone());
    pin
}

fn bounds(scene: &Scene, id: &str) -> Rect {
    layout_scene(scene, LayoutOptions::default())
        .geometry
        .get(&NodeId::from(id))
        .unwrap_or_else(|| panic!("no geometry for {id}"))
        .layout_bounds
        .clone()
}

fn diag_for<'a>(diagnostics: &'a [Diagnostic], code: &str, node: &str) -> Option<&'a Diagnostic> {
    let node_id = NodeId::from(node);
    diagnostics.iter().find(|diagnostic| {
        diagnostic.code == code
            && matches!(&diagnostic.subject, Some(DiagnosticSubject::Node(id)) if *id == node_id)
    })
}

fn stack_with_three_children() -> Scene {
    let mut scene = scene_with_page(800.0, 600.0);
    let mut stack = auto_layout(
        "stack",
        AutoLayoutDirection::Column,
        Dimension::Fixed(300.0),
        Dimension::Fixed(500.0),
        10.0,
    );
    stack.transform.x = 10.0;
    stack.transform.y = 10.0;
    insert(&mut scene, ParentRef::Page(PageId::from("page")), stack);
    for id in ["a", "b", "c"] {
        insert(
            &mut scene,
            ParentRef::Node(NodeId::from("stack")),
            rect(id, 100.0, 50.0),
        );
    }
    scene
}

#[test]
fn pinned_child_lays_out_at_its_box_and_siblings_reflow() {
    let mut scene = stack_with_three_children();

    // Baseline: the column stacks a/b/c with a 10pt gap.
    assert_eq!(bounds(&scene, "b"), rect_at(10.0, 70.0, 100.0, 50.0));
    assert_eq!(bounds(&scene, "c"), rect_at(10.0, 130.0, 100.0, 50.0));

    let pinned = pin(&mut scene, "b", 500.0, 400.0, 120.0, 40.0);
    let result = layout_scene(&scene, LayoutOptions::default());

    // The detached node lands exactly on its page-space box…
    assert_eq!(result.geometry[&NodeId::from("b")].layout_bounds, pinned);
    // …the earlier sibling is untouched, and the later sibling takes b's slot.
    assert_eq!(bounds(&scene, "a"), rect_at(10.0, 10.0, 100.0, 50.0));
    assert_eq!(bounds(&scene, "c"), rect_at(10.0, 70.0, 100.0, 50.0));

    // Deliberate detach is not the accidental rotation out-of-flow case.
    assert!(
        diag_for(&result.diagnostics, "LUMV0701", "b").is_none(),
        "pinned child must not warn LUMV0701: {:#?}",
        result.diagnostics
    );
}

#[test]
fn pinned_child_does_not_snap_back_across_relayouts() {
    let mut scene = stack_with_three_children();
    let pinned = pin(&mut scene, "b", 500.0, 400.0, 120.0, 40.0);

    // The editor's cycle: solve, write computed back onto nodes, solve again.
    let operations = layout_operations(&scene, LayoutOptions::default());
    scene.apply_operations(operations).unwrap();
    let second = layout_scene(&scene, LayoutOptions::default());

    assert_eq!(
        second.geometry[&NodeId::from("b")].layout_bounds, pinned,
        "pinned node must stay at its box after computed write-back"
    );
    assert_eq!(
        second.geometry[&NodeId::from("c")].layout_bounds,
        rect_at(10.0, 70.0, 100.0, 50.0)
    );
}

#[test]
fn pinned_auto_layout_container_solves_children_inside_the_box() {
    let mut scene = scene_with_page(800.0, 600.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        auto_layout(
            "outer",
            AutoLayoutDirection::Column,
            Dimension::Fixed(400.0),
            Dimension::Fixed(600.0),
            10.0,
        ),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("outer")),
        rect("a", 100.0, 40.0),
    );
    // The authored size disagrees with the pin on purpose: the box wins.
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("outer")),
        auto_layout(
            "card",
            AutoLayoutDirection::Row,
            Dimension::Fixed(999.0),
            Dimension::Fixed(999.0),
            10.0,
        ),
    );
    for id in ["k1", "k2"] {
        insert(
            &mut scene,
            ParentRef::Node(NodeId::from("card")),
            rect(id, 50.0, 50.0),
        );
    }
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("outer")),
        rect("z", 100.0, 40.0),
    );

    let pinned = pin(&mut scene, "card", 200.0, 300.0, 300.0, 200.0);

    assert_eq!(bounds(&scene, "card"), pinned, "the box is authoritative");
    // Children of the detached container keep composing inside the box.
    assert_eq!(bounds(&scene, "k1"), rect_at(200.0, 300.0, 50.0, 50.0));
    assert_eq!(bounds(&scene, "k2"), rect_at(260.0, 300.0, 50.0, 50.0));
    // Flow siblings reflow as if the card were gone.
    assert_eq!(bounds(&scene, "a"), rect_at(0.0, 0.0, 100.0, 40.0));
    assert_eq!(bounds(&scene, "z"), rect_at(0.0, 50.0, 100.0, 40.0));
}

#[test]
fn free_container_lays_children_at_baked_transforms() {
    let mut scene = scene_with_page(800.0, 600.0);
    let mut free_section = auto_layout(
        "free_sec",
        AutoLayoutDirection::Column,
        Dimension::Fixed(400.0),
        Dimension::Fixed(300.0),
        10.0,
    );
    free_section.transform.x = 50.0;
    free_section.transform.y = 50.0;
    free_section.layout.as_mut().unwrap().layout_mode = LayoutMode::Free;
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        free_section,
    );

    let mut f1 = rect("f1", 80.0, 40.0);
    f1.transform.x = 10.0;
    f1.transform.y = 20.0;
    insert(&mut scene, ParentRef::Node(NodeId::from("free_sec")), f1);
    let mut f2 = rect("f2", 60.0, 30.0);
    f2.transform.x = 200.0;
    f2.transform.y = 100.0;
    insert(&mut scene, ParentRef::Node(NodeId::from("free_sec")), f2);

    assert_eq!(bounds(&scene, "free_sec"), rect_at(50.0, 50.0, 400.0, 300.0));
    // Children sit at container origin + their own baked transforms — the
    // column solve would have stacked f2 directly under f1 instead.
    assert_eq!(bounds(&scene, "f1"), rect_at(60.0, 70.0, 80.0, 40.0));
    assert_eq!(bounds(&scene, "f2"), rect_at(250.0, 150.0, 60.0, 30.0));
}

#[test]
fn free_container_nested_in_stack_flows_as_a_box() {
    let mut scene = scene_with_page(800.0, 600.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        auto_layout(
            "root",
            AutoLayoutDirection::Column,
            Dimension::Fixed(400.0),
            Dimension::Fixed(600.0),
            10.0,
        ),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("root")),
        rect("a", 100.0, 40.0),
    );
    let mut free_box = auto_layout(
        "free_box",
        AutoLayoutDirection::Row,
        Dimension::Fixed(200.0),
        Dimension::Fixed(100.0),
        0.0,
    );
    free_box.layout.as_mut().unwrap().layout_mode = LayoutMode::Free;
    insert(&mut scene, ParentRef::Node(NodeId::from("root")), free_box);
    let mut f1 = rect("f1", 30.0, 30.0);
    f1.transform.x = 5.0;
    f1.transform.y = 5.0;
    insert(&mut scene, ParentRef::Node(NodeId::from("free_box")), f1);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("root")),
        rect("b", 100.0, 40.0),
    );

    // The Free container itself still participates in its parent's flow…
    assert_eq!(bounds(&scene, "a"), rect_at(0.0, 0.0, 100.0, 40.0));
    assert_eq!(bounds(&scene, "free_box"), rect_at(0.0, 50.0, 200.0, 100.0));
    assert_eq!(bounds(&scene, "b"), rect_at(0.0, 160.0, 100.0, 40.0));
    // …while its children sit at their baked transforms inside it.
    assert_eq!(bounds(&scene, "f1"), rect_at(5.0, 55.0, 30.0, 30.0));
}

#[test]
fn pinned_child_excluded_from_fill_math() {
    let mut scene = scene_with_page(800.0, 600.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        auto_layout(
            "row",
            AutoLayoutDirection::Row,
            Dimension::Fixed(400.0),
            Dimension::Fixed(100.0),
            0.0,
        ),
    );
    let mut filler = rect("filler", 0.0, 100.0);
    filler.size = SizeSpec {
        width: Dimension::Fill { weight: 1.0 },
        height: Dimension::Fixed(100.0),
    };
    insert(&mut scene, ParentRef::Node(NodeId::from("row")), filler);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("row")),
        rect("p", 120.0, 100.0),
    );

    // Baseline: the fixed sibling reserves its width.
    assert_eq!(bounds(&scene, "filler").width, 280.0);

    pin(&mut scene, "p", 500.0, 20.0, 120.0, 100.0);

    // Detached: the fill child reclaims the whole row.
    assert_eq!(bounds(&scene, "filler").width, 400.0);
}

#[test]
fn pinned_node_without_box_falls_back_to_flow_position() {
    let mut scene = stack_with_three_children();
    {
        let node = scene.nodes.get_mut(&NodeId::from("b")).unwrap();
        node.position_mode = PositionMode::Absolute;
        node.transform.x = 7.0;
        node.transform.y = 9.0;
    }

    // Same treatment as a rotated child: out of flow, at origin + transform.
    assert_eq!(bounds(&scene, "b"), rect_at(17.0, 19.0, 100.0, 50.0));
    assert_eq!(bounds(&scene, "c"), rect_at(10.0, 70.0, 100.0, 50.0));
}

#[test]
fn pinned_box_wins_over_hug_size_for_text() {
    let mut scene = scene_with_page(800.0, 600.0);
    let mut headline = Node::new(
        NodeId::from("headline"),
        NodeKind::Text(lumen_core::TextNode {
            content: "Pinned headline".to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 18.0,
            font_weight: 600,
            align: lumen_core::TextAlign::Left,
            style_token: None,
            ..lumen_core::TextNode::default()
        }),
    );
    headline.size = SizeSpec {
        width: Dimension::Hug,
        height: Dimension::Hug,
    };
    insert(&mut scene, ParentRef::Page(PageId::from("page")), headline);

    let pinned = pin(&mut scene, "headline", 40.0, 60.0, 200.0, 90.0);
    assert_eq!(bounds(&scene, "headline"), pinned);
}

#[test]
fn freehand_overflow_of_clipping_parent_warns_while_managed_errors() {
    let mut scene = scene_with_canonical_page(300.0, 300.0);
    let mut card = Node::new(NodeId::from("card"), NodeKind::Frame);
    card.transform.x = 20.0;
    card.transform.y = 20.0;
    card.size = SizeSpec::fixed(100.0, 100.0);
    card.clip = true;
    insert(&mut scene, ParentRef::Page(PageId::from("page")), card);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("card")),
        rect("wide_child", 150.0, 40.0),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("card")),
        rect("pinned_out", 50.0, 40.0),
    );
    pin(&mut scene, "pinned_out", 200.0, 200.0, 50.0, 40.0);

    let diagnostics = validate_layout(&scene, LayoutOptions::default());

    let managed = diag_for(&diagnostics, "LUMV0801", "wide_child")
        .expect("managed overflow keeps firing LUMV0801");
    assert_eq!(managed.severity, DiagnosticSeverity::Error);

    let freehand = diag_for(&diagnostics, "LUMV0801", "pinned_out")
        .expect("freehand overflow still surfaces LUMV0801");
    assert_eq!(
        freehand.severity,
        DiagnosticSeverity::Warning,
        "freehand overflow of a clipping parent is advisory: {diagnostics:#?}"
    );
}

#[test]
fn free_container_child_overflow_warns_despite_clip() {
    let mut scene = scene_with_canonical_page(300.0, 300.0);
    let mut free_frame = auto_layout(
        "free_frame",
        AutoLayoutDirection::Column,
        Dimension::Fixed(100.0),
        Dimension::Fixed(100.0),
        0.0,
    );
    free_frame.transform.x = 20.0;
    free_frame.transform.y = 20.0;
    free_frame.clip = true;
    free_frame.layout.as_mut().unwrap().layout_mode = LayoutMode::Free;
    insert(&mut scene, ParentRef::Page(PageId::from("page")), free_frame);

    let mut child = rect("fc", 50.0, 50.0);
    child.transform.x = 90.0;
    child.transform.y = 90.0;
    insert(&mut scene, ParentRef::Node(NodeId::from("free_frame")), child);

    let diagnostics = validate_layout(&scene, LayoutOptions::default());
    let overflow = diag_for(&diagnostics, "LUMV0801", "fc")
        .expect("free-container child overflow surfaces LUMV0801");
    assert_eq!(
        overflow.severity,
        DiagnosticSeverity::Warning,
        "children of a Free container are freehand: {diagnostics:#?}"
    );
}

#[test]
fn freehand_page_overflow_warns_while_managed_errors() {
    let mut scene = scene_with_canonical_page(300.0, 300.0);
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        rect("oversized", 700.0, 900.0),
    );
    insert(
        &mut scene,
        ParentRef::Page(PageId::from("page")),
        rect("pinned_off", 100.0, 100.0),
    );
    pin(&mut scene, "pinned_off", 250.0, 250.0, 100.0, 100.0);

    let diagnostics = validate_layout(&scene, LayoutOptions::default());

    let managed = diag_for(&diagnostics, "LUMV0800", "oversized")
        .expect("managed page overflow keeps firing LUMV0800");
    assert_eq!(managed.severity, DiagnosticSeverity::Error);

    let freehand = diag_for(&diagnostics, "LUMV0800", "pinned_off")
        .expect("freehand page overflow still surfaces LUMV0800");
    assert_eq!(
        freehand.severity,
        DiagnosticSeverity::Warning,
        "dragging a pinned node past the artboard is advisory: {diagnostics:#?}"
    );
}

#[test]
fn checked_apply_lands_a_freehand_drag_past_a_clipped_parent() {
    let mut scene = scene_with_canonical_page(300.0, 300.0);
    let mut card = Node::new(NodeId::from("card"), NodeKind::Frame);
    card.transform.x = 20.0;
    card.transform.y = 20.0;
    card.size = SizeSpec::fixed(100.0, 100.0);
    card.clip = true;
    insert(&mut scene, ParentRef::Page(PageId::from("page")), card);
    let mut sticker = rect("sticker", 50.0, 40.0);
    sticker.transform.x = 10.0;
    sticker.transform.y = 10.0;
    insert(&mut scene, ParentRef::Node(NodeId::from("card")), sticker);

    // The 1d gesture in operation form: detach + drag outside the clipped
    // parent, committed through the same checked apply as manual edits.
    let solved = bounds(&scene, "sticker");
    let report = scene
        .apply_operations_checked([Operation::UpdateNode {
            node_id: NodeId::from("sticker"),
            patch: NodePatch {
                position_mode: FieldPatch::Set(PositionMode::Absolute),
                absolute_box: OptionalFieldPatch::Set(Rect {
                    x: 200.0,
                    y: 200.0,
                    width: 50.0,
                    height: 40.0,
                }),
                base_anchor: OptionalFieldPatch::Set(solved),
                ..NodePatch::default()
            },
        }])
        .expect("the drag must land");
    assert_eq!(report.applied_operations, 1);

    // The scene now lays the sticker outside its clipped parent — surfaced
    // as an advisory warning, never a blocking error (the acceptance gate).
    let diagnostics = validate_layout(&scene, LayoutOptions::default());
    assert!(
        diag_for(&diagnostics, "LUMV0801", "sticker")
            .is_some_and(|diagnostic| diagnostic.severity == DiagnosticSeverity::Warning),
        "{diagnostics:#?}"
    );
    assert!(
        !diagnostics
            .iter()
            .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Error),
        "freehand overflow must not block acceptance: {diagnostics:#?}"
    );
    assert_eq!(bounds(&scene, "sticker"), rect_at(200.0, 200.0, 50.0, 40.0));
}

fn rect_at(x: f64, y: f64, width: f64, height: f64) -> Rect {
    Rect {
        x,
        y,
        width,
        height,
    }
}
