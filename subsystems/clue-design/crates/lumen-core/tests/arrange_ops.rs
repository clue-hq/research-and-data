//! Phase 4b gate — the invertible arrange operations. `group` wraps
//! same-parent siblings in a new Group container (empty insert + moves, so
//! every op is individually invertible); `ungroup` dissolves it back.
//! Geometry contract: an all-pinned selection pins the group to the union
//! of the children's page-space boxes and the children keep their boxes;
//! a manual-flow selection gets an identity-transform Hug group so child
//! transforms keep their meaning. Solver-managed stack children are
//! rejected (detach to freehand first).

use lumen_core::{
    build_structured_edit_batch, layout_scene, AutoLayoutDirection, AutoLayoutNode, DocumentId,
    EditErrorKind, LayoutOptions, Node, NodeId, NodeKind, Operation, Orientation, Page, PageId,
    PagePreset, PageSize, ParentRef, PositionMode, Rect, Scene, SizeSpec,
    StructuredEditInstruction, Transform, Unit,
};

fn scene_with_page(width: f64, height: f64) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_arrange_ops"), "Arrange Ops");
    scene
        .apply_operation(Operation::AddPage {
            page: Page {
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
            },
        })
        .unwrap();
    scene
}

fn rect(id: &str, width: f64, height: f64) -> Node {
    let mut node = Node::new(NodeId::from(id), NodeKind::Rect);
    node.size = SizeSpec::fixed(width, height);
    node
}

fn pinned_rect(id: &str, x: f64, y: f64, width: f64, height: f64) -> Node {
    let mut node = rect(id, width, height);
    node.position_mode = PositionMode::Absolute;
    node.absolute_box = Some(Rect {
        x,
        y,
        width,
        height,
    });
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

fn scene_json(scene: &Scene) -> serde_json::Value {
    serde_json::to_value(scene).unwrap()
}

fn solved(scene: &Scene, id: &str) -> Rect {
    layout_scene(scene, LayoutOptions::default())
        .geometry
        .get(&NodeId::from(id))
        .unwrap_or_else(|| panic!("no geometry for {id}"))
        .layout_bounds
        .clone()
}

fn instruction(json: serde_json::Value) -> StructuredEditInstruction {
    serde_json::from_value(json).expect("wire-format instruction parses")
}

fn group_instruction(node_ids: &[&str], group_id: &str) -> StructuredEditInstruction {
    instruction(serde_json::json!({
        "kind": "group",
        "node_ids": node_ids,
        "group_id": group_id,
        "name": "Group"
    }))
}

/// Page with three pinned rects: a (10,20,100,50), b (200,100,80,40),
/// c (400,300,50,50) — z-order a, b, c.
fn pinned_scene() -> Scene {
    let mut scene = scene_with_page(800.0, 600.0);
    let page = ParentRef::Page(PageId::from("page"));
    insert(
        &mut scene,
        page.clone(),
        pinned_rect("a", 10.0, 20.0, 100.0, 50.0),
    );
    insert(
        &mut scene,
        page.clone(),
        pinned_rect("b", 200.0, 100.0, 80.0, 40.0),
    );
    insert(&mut scene, page, pinned_rect("c", 400.0, 300.0, 50.0, 50.0));
    scene
}

#[test]
fn group_pinned_siblings_pins_the_union_and_inverts_byte_identical() {
    let mut scene = pinned_scene();
    let before = scene_json(&scene);
    let solved_a = solved(&scene, "a");
    let solved_b = solved(&scene, "b");

    let batch = build_structured_edit_batch(&scene, &group_instruction(&["a", "b"], "g1"))
        .expect("group builds");
    assert!(
        batch.inverse_operations.is_some(),
        "group must carry exact inverses"
    );
    batch.apply_checked(&mut scene).expect("group applies");

    let group = &scene.nodes[&NodeId::from("g1")];
    assert!(matches!(group.kind, NodeKind::Group));
    assert_eq!(group.position_mode, PositionMode::Absolute);
    // Union of a (10,20,100,50) and b (200,100,80,40).
    assert_eq!(
        group.absolute_box,
        Some(Rect {
            x: 10.0,
            y: 20.0,
            width: 270.0,
            height: 120.0
        })
    );
    assert_eq!(group.size, SizeSpec::fixed(270.0, 120.0));
    assert_eq!(
        group.children,
        vec![NodeId::from("a"), NodeId::from("b")],
        "children arrive in z-order"
    );
    // Pinned children keep their page-space boxes: zero motion.
    assert_eq!(solved(&scene, "a"), solved_a);
    assert_eq!(solved(&scene, "b"), solved_b);

    let mut restored = scene.clone();
    restored
        .apply_operations(batch.inverse_operations.clone().unwrap())
        .unwrap();
    assert_eq!(
        scene_json(&restored),
        before,
        "inverses must restore the pre-group scene exactly"
    );
}

#[test]
fn group_lands_above_the_topmost_selected_sibling() {
    let mut scene = pinned_scene();
    let batch = build_structured_edit_batch(&scene, &group_instruction(&["c", "a"], "g1"))
        .expect("group builds");
    batch.apply_checked(&mut scene).expect("group applies");

    // a and c left the page; the group takes the topmost (c's) position.
    assert_eq!(
        scene.pages[&PageId::from("page")].children,
        vec![NodeId::from("b"), NodeId::from("g1")]
    );
    // Selection order does not matter; z-order does.
    assert_eq!(
        scene.nodes[&NodeId::from("g1")].children,
        vec![NodeId::from("a"), NodeId::from("c")]
    );
}

#[test]
fn group_manual_flow_children_is_zero_motion_and_inverts() {
    let mut scene = scene_with_page(800.0, 600.0);
    let page = ParentRef::Page(PageId::from("page"));
    let mut frame = Node::new(NodeId::from("frame"), NodeKind::Frame);
    frame.size = SizeSpec::fixed(600.0, 400.0);
    frame.transform = Transform {
        x: 50.0,
        y: 50.0,
        ..Transform::default()
    };
    insert(&mut scene, page, frame);
    let mut a = rect("a", 100.0, 50.0);
    a.transform.x = 20.0;
    a.transform.y = 30.0;
    insert(&mut scene, ParentRef::Node(NodeId::from("frame")), a);
    let mut b = rect("b", 80.0, 40.0);
    b.transform.x = 200.0;
    b.transform.y = 150.0;
    insert(&mut scene, ParentRef::Node(NodeId::from("frame")), b);

    let before = scene_json(&scene);
    let solved_a = solved(&scene, "a");
    let solved_b = solved(&scene, "b");

    let batch = build_structured_edit_batch(&scene, &group_instruction(&["a", "b"], "g1"))
        .expect("group builds");
    batch.apply_checked(&mut scene).expect("group applies");

    let group = &scene.nodes[&NodeId::from("g1")];
    assert_eq!(group.position_mode, PositionMode::Managed);
    assert_eq!(group.transform, Transform::default());
    // Identity transform + Hug: children keep their parent-relative meaning.
    assert_eq!(solved(&scene, "a"), solved_a);
    assert_eq!(solved(&scene, "b"), solved_b);

    let mut restored = scene.clone();
    restored
        .apply_operations(batch.inverse_operations.clone().unwrap())
        .unwrap();
    assert_eq!(scene_json(&restored), before);
}

#[test]
fn ungroup_dissolves_a_built_group_in_place() {
    let mut scene = pinned_scene();
    build_structured_edit_batch(&scene, &group_instruction(&["a", "c"], "g1"))
        .expect("group builds")
        .apply_checked(&mut scene)
        .expect("group applies");

    let batch = build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({ "kind": "ungroup", "node_id": "g1" })),
    )
    .expect("ungroup builds");
    batch.apply_checked(&mut scene).expect("ungroup applies");

    assert!(!scene.nodes.contains_key(&NodeId::from("g1")));
    // Children return at the group's slot, order preserved.
    assert_eq!(
        scene.pages[&PageId::from("page")].children,
        vec![NodeId::from("b"), NodeId::from("a"), NodeId::from("c")]
    );
}

#[test]
fn group_rejects_bad_selections() {
    let mut scene = pinned_scene();

    // Duplicate ids.
    let error = build_structured_edit_batch(&scene, &group_instruction(&["a", "a"], "g1"))
        .expect_err("duplicates rejected");
    assert_eq!(error.kind, EditErrorKind::UnsupportedTarget);

    // Mixed parents: c moved under a fresh frame first.
    let mut frame = Node::new(NodeId::from("frame"), NodeKind::Frame);
    frame.size = SizeSpec::fixed(600.0, 400.0);
    insert(&mut scene, ParentRef::Page(PageId::from("page")), frame);
    scene
        .apply_operation(Operation::MoveNode {
            node_id: NodeId::from("c"),
            new_parent: ParentRef::Node(NodeId::from("frame")),
            index: 0,
        })
        .unwrap();
    let error = build_structured_edit_batch(&scene, &group_instruction(&["a", "c"], "g1"))
        .expect_err("mixed parents rejected");
    assert_eq!(error.kind, EditErrorKind::UnsupportedTarget);

    // Locked member.
    let mut scene = pinned_scene();
    scene
        .apply_operation(Operation::UpdateNode {
            node_id: NodeId::from("b"),
            patch: lumen_core::NodePatch {
                locked: lumen_core::FieldPatch::Set(true),
                ..lumen_core::NodePatch::default()
            },
        })
        .unwrap();
    let error = build_structured_edit_batch(&scene, &group_instruction(&["a", "b"], "g1"))
        .expect_err("locked member rejected");
    assert_eq!(error.kind, EditErrorKind::LockedTarget);

    // Group id collision.
    let scene = pinned_scene();
    let error = build_structured_edit_batch(&scene, &group_instruction(&["a", "b"], "a"))
        .expect_err("existing id rejected");
    assert_eq!(error.kind, EditErrorKind::OperationFailed);
}

#[test]
fn group_rejects_solver_managed_stack_children() {
    let mut scene = scene_with_page(800.0, 600.0);
    let mut stack = Node::new(
        NodeId::from("stack"),
        NodeKind::AutoLayout(AutoLayoutNode {
            direction: AutoLayoutDirection::Column,
            wrap: false,
        }),
    );
    stack.size = SizeSpec::fixed(300.0, 500.0);
    stack.layout = Some(lumen_core::AutoLayoutProps::default());
    insert(&mut scene, ParentRef::Page(PageId::from("page")), stack);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("stack")),
        rect("a", 100.0, 50.0),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("stack")),
        rect("b", 100.0, 50.0),
    );

    let error = build_structured_edit_batch(&scene, &group_instruction(&["a", "b"], "g1"))
        .expect_err("managed stack children rejected");
    assert_eq!(error.kind, EditErrorKind::LifecycleProtected);
}

#[test]
fn wire_format_kinds_are_pinned() {
    assert_eq!(group_instruction(&["a"], "g1").kind(), "group");
    assert_eq!(
        instruction(serde_json::json!({ "kind": "ungroup", "node_id": "g1" })).kind(),
        "ungroup"
    );
}
