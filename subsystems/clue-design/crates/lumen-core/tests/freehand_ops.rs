//! Phase 1c gate — the invertible freehand operations. `detach_to_freehand`
//! pins a node at its solved box (the node itself does not move; Hug/Fill
//! bake to Fixed), `reattach_to_layout` returns it to the solve,
//! `convert_container_layout` flips a container between Stack and Free with
//! zero-motion baking on the way out. Every batch carries exact inverses:
//! applying them restores the pre-edit scene byte-identically — the
//! machinery Accept/Reject (0c) and future Compare/Revert ride on.

use lumen_core::{
    build_structured_edit_batch, layout_operations, layout_scene, AutoLayoutDirection,
    AutoLayoutNode, AutoLayoutProps, Dimension, DocumentId, EditErrorKind, LayoutMode,
    LayoutOptions, Node, NodeId, NodeKind, Operation, Orientation, Page, PageId, PagePreset,
    PageSize, ParentRef, PositionMode, Rect, Scene, SizeSpec, StructuredEditInstruction, Unit,
};

fn scene_with_page(width: f64, height: f64) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_freehand_ops"), "Freehand Ops");
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

fn auto_layout(id: &str, width: f64, height: f64, gap: f64) -> Node {
    let mut node = Node::new(
        NodeId::from(id),
        NodeKind::AutoLayout(AutoLayoutNode {
            direction: AutoLayoutDirection::Column,
            wrap: false,
        }),
    );
    node.size = SizeSpec::fixed(width, height);
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

/// Column stack at (10,10), 300×500, gap 10 — children a (fixed 100×50),
/// b (FILL width × fixed 50, to exercise size baking), c (fixed 100×50).
/// Solved: a (10,10), b (10,70,300,50), c (10,130).
fn stack_scene() -> Scene {
    let mut scene = scene_with_page(800.0, 600.0);
    let mut stack = auto_layout("stack", 300.0, 500.0, 10.0);
    stack.transform.x = 10.0;
    stack.transform.y = 10.0;
    insert(&mut scene, ParentRef::Page(PageId::from("page")), stack);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("stack")),
        rect("a", 100.0, 50.0),
    );
    let mut b = rect("b", 0.0, 50.0);
    b.size = SizeSpec {
        width: Dimension::Fill { weight: 1.0 },
        height: Dimension::Fixed(50.0),
    };
    insert(&mut scene, ParentRef::Node(NodeId::from("stack")), b);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("stack")),
        rect("c", 100.0, 50.0),
    );
    scene
}

/// The builders read `node.computed`; callers hold laid-out scenes.
fn apply_layout(scene: &mut Scene) {
    let operations = layout_operations(scene, LayoutOptions::default());
    scene.apply_operations(operations).unwrap();
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

#[test]
fn detach_pins_solved_box_bakes_size_and_inverts_byte_identical() {
    let mut scene = stack_scene();
    apply_layout(&mut scene);
    let before = scene_json(&scene);
    let solved_b = scene.nodes[&NodeId::from("b")]
        .computed
        .as_ref()
        .unwrap()
        .layout_bounds
        .clone();

    // Wire form pins the serde tag the bindings will send.
    let batch = build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({ "kind": "detach_to_freehand", "node_id": "b" })),
    )
    .expect("detach builds");
    assert!(
        batch.inverse_operations.is_some(),
        "detach must carry exact inverses"
    );

    batch.apply_checked(&mut scene).expect("detach applies");
    let b = &scene.nodes[&NodeId::from("b")];
    assert_eq!(b.position_mode, PositionMode::Absolute);
    assert_eq!(b.absolute_box, Some(solved_b.clone()));
    assert_eq!(b.base_anchor, Some(solved_b.clone()));
    // Fill width baked to the solved extent; fixed height untouched.
    assert_eq!(b.size, SizeSpec::fixed(300.0, 50.0));

    // The detached node itself has not moved…
    assert_eq!(solved(&scene, "b"), solved_b);
    // …its earlier sibling is untouched, and the later sibling closes the
    // vacated slot (Figma semantics).
    assert_eq!(solved(&scene, "a").y, 10.0);
    assert_eq!(solved(&scene, "c").y, 70.0);

    let mut restored = scene.clone();
    restored
        .apply_operations(batch.inverse_operations.clone().unwrap())
        .unwrap();
    assert_eq!(
        scene_json(&restored),
        before,
        "inverses must restore the pre-detach scene exactly"
    );
}

#[test]
fn detach_requires_computed_geometry() {
    let scene = stack_scene(); // no layout pass — computed is None
    let error = build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({ "kind": "detach_to_freehand", "node_id": "b" })),
    )
    .expect_err("detach without geometry must fail");
    assert_eq!(error.kind, EditErrorKind::OperationFailed);
    assert!(error.message.contains("run layout"), "{}", error.message);
}

#[test]
fn detach_rejects_locked_missing_and_already_freehand() {
    let mut scene = stack_scene();
    apply_layout(&mut scene);

    scene.nodes.get_mut(&NodeId::from("a")).unwrap().locked = true;
    let locked = build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({ "kind": "detach_to_freehand", "node_id": "a" })),
    )
    .expect_err("locked node cannot detach");
    assert_eq!(locked.kind, EditErrorKind::LockedTarget);

    let missing = build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({ "kind": "detach_to_freehand", "node_id": "ghost" })),
    )
    .expect_err("missing node cannot detach");
    assert_eq!(missing.kind, EditErrorKind::TargetNotFound);

    build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({ "kind": "detach_to_freehand", "node_id": "b" })),
    )
    .unwrap()
    .apply_checked(&mut scene)
    .unwrap();
    let twice = build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({ "kind": "detach_to_freehand", "node_id": "b" })),
    )
    .expect_err("a freehand node cannot detach again");
    assert_eq!(twice.kind, EditErrorKind::UnsupportedTarget);
}

#[test]
fn reattach_returns_node_to_the_flow() {
    let mut scene = stack_scene();
    apply_layout(&mut scene);
    build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({ "kind": "detach_to_freehand", "node_id": "b" })),
    )
    .unwrap()
    .apply_checked(&mut scene)
    .unwrap();

    // The human drags the pin somewhere else…
    {
        let b = scene.nodes.get_mut(&NodeId::from("b")).unwrap();
        b.absolute_box = Some(Rect {
            x: 500.0,
            y: 400.0,
            width: 300.0,
            height: 50.0,
        });
    }
    assert_eq!(solved(&scene, "b").x, 500.0);

    // …then hands it back to the solver.
    apply_layout(&mut scene);
    build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({ "kind": "reattach_to_layout", "node_id": "b" })),
    )
    .unwrap()
    .apply_checked(&mut scene)
    .unwrap();

    let b = &scene.nodes[&NodeId::from("b")];
    assert_eq!(b.position_mode, PositionMode::Managed);
    assert_eq!(b.absolute_box, None);
    assert_eq!(b.base_anchor, None);
    // The size baked at detach is kept — the solver cannot know what
    // Hug/Fill meant before the human took over.
    assert_eq!(b.size, SizeSpec::fixed(300.0, 50.0));
    // Back in the flow at its stacking slot.
    assert_eq!(solved(&scene, "b"), solved(&scene, "b"));
    assert_eq!(solved(&scene, "b").y, 70.0);
    assert_eq!(solved(&scene, "c").y, 130.0);
}

#[test]
fn reattach_rejects_non_freehand_nodes() {
    let mut scene = stack_scene();
    apply_layout(&mut scene);
    let error = build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({ "kind": "reattach_to_layout", "node_id": "b" })),
    )
    .expect_err("managed node has nothing to re-attach");
    assert_eq!(error.kind, EditErrorKind::UnsupportedTarget);
}

#[test]
fn convert_to_free_is_zero_motion_and_inverts_byte_identical() {
    let mut scene = stack_scene();
    apply_layout(&mut scene);
    let before = scene_json(&scene);
    let geometry_before = layout_scene(&scene, LayoutOptions::default()).geometry;

    let batch = build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({
            "kind": "convert_container_layout",
            "node_id": "stack",
            "layout_mode": "free"
        })),
    )
    .expect("convert builds");
    batch.apply_checked(&mut scene).expect("convert applies");

    let stack = &scene.nodes[&NodeId::from("stack")];
    assert_eq!(stack.layout.as_ref().unwrap().layout_mode, LayoutMode::Free);
    // Children carry their solved offsets as baked transforms now.
    assert_eq!(scene.nodes[&NodeId::from("b")].transform.y, 60.0);
    assert_eq!(scene.nodes[&NodeId::from("c")].transform.y, 120.0);
    assert_eq!(
        scene.nodes[&NodeId::from("b")].size,
        SizeSpec::fixed(300.0, 50.0),
        "Fill bakes to Fixed on the way out of the solve"
    );

    // Freezing the section moves nothing.
    let geometry_after = layout_scene(&scene, LayoutOptions::default()).geometry;
    assert_eq!(geometry_before, geometry_after);

    let mut restored = scene.clone();
    restored
        .apply_operations(batch.inverse_operations.clone().unwrap())
        .unwrap();
    assert_eq!(
        scene_json(&restored),
        before,
        "inverses must restore the pre-conversion scene exactly"
    );
}

#[test]
fn convert_back_to_stack_restacks_hand_moved_children() {
    let mut scene = stack_scene();
    apply_layout(&mut scene);
    build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({
            "kind": "convert_container_layout",
            "node_id": "stack",
            "layout_mode": "free"
        })),
    )
    .unwrap()
    .apply_checked(&mut scene)
    .unwrap();

    // Hand-place c somewhere else inside the free section.
    {
        let c = scene.nodes.get_mut(&NodeId::from("c")).unwrap();
        c.transform.x = 50.0;
        c.transform.y = 200.0;
    }
    assert_eq!(solved(&scene, "c").y, 210.0);

    apply_layout(&mut scene);
    build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({
            "kind": "convert_container_layout",
            "node_id": "stack",
            "layout_mode": "stack"
        })),
    )
    .unwrap()
    .apply_checked(&mut scene)
    .unwrap();

    // The solve owns placement again: c re-stacks under b.
    assert_eq!(solved(&scene, "c"), solved(&scene, "c"));
    assert_eq!(solved(&scene, "c").y, 130.0);
    assert_eq!(solved(&scene, "c").x, 10.0);
}

#[test]
fn convert_to_free_skips_pinned_children() {
    let mut scene = stack_scene();
    apply_layout(&mut scene);
    build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({ "kind": "detach_to_freehand", "node_id": "b" })),
    )
    .unwrap()
    .apply_checked(&mut scene)
    .unwrap();
    apply_layout(&mut scene);
    let pinned_box = scene.nodes[&NodeId::from("b")].absolute_box.clone();

    let batch = build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({
            "kind": "convert_container_layout",
            "node_id": "stack",
            "layout_mode": "free"
        })),
    )
    .unwrap();
    assert!(
        !batch.operations.iter().any(|operation| matches!(
            operation,
            Operation::UpdateNode { node_id, .. } if node_id == &NodeId::from("b")
        )),
        "a pinned child is already freehand — freeing the container must not touch it"
    );
    batch.apply_checked(&mut scene).unwrap();
    assert_eq!(
        scene.nodes[&NodeId::from("b")].absolute_box,
        pinned_box,
        "the pin survives the container conversion"
    );
}

#[test]
fn convert_rejects_non_containers_and_no_op_modes() {
    let mut scene = stack_scene();
    apply_layout(&mut scene);

    let non_container = build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({
            "kind": "convert_container_layout",
            "node_id": "a",
            "layout_mode": "free"
        })),
    )
    .expect_err("a rect has no layout mode");
    assert_eq!(non_container.kind, EditErrorKind::UnsupportedTarget);

    let already_stack = build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({
            "kind": "convert_container_layout",
            "node_id": "stack",
            "layout_mode": "stack"
        })),
    )
    .expect_err("converting to the current mode is a no-op");
    assert_eq!(already_stack.kind, EditErrorKind::UnsupportedTarget);
}

#[test]
fn wire_format_kinds_are_pinned() {
    let detach = StructuredEditInstruction::DetachToFreehand {
        node_id: NodeId::from("n"),
    };
    assert_eq!(detach.kind(), "detach_to_freehand");
    let json = serde_json::to_value(&detach).unwrap();
    assert_eq!(json["kind"], "detach_to_freehand");

    let reattach = StructuredEditInstruction::ReattachToLayout {
        node_id: NodeId::from("n"),
    };
    assert_eq!(reattach.kind(), "reattach_to_layout");

    let convert = StructuredEditInstruction::ConvertContainerLayout {
        node_id: NodeId::from("n"),
        layout_mode: LayoutMode::Free,
    };
    assert_eq!(convert.kind(), "convert_container_layout");
    let json = serde_json::to_value(&convert).unwrap();
    assert_eq!(json["layout_mode"], "free");
    let round_tripped: StructuredEditInstruction = serde_json::from_value(json).unwrap();
    assert_eq!(round_tripped, convert);
}
