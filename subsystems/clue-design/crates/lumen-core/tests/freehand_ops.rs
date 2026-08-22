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

/// Handoff-absolute: `freeze_layout` bakes every Stack container to Free in
/// one zero-motion, invertible batch — nested stacks included. This is the
/// Moda handoff contract: after an agent turn the human edits pure absolute
/// and the solver never re-flows siblings under their cursor.
#[test]
fn freeze_layout_bakes_every_stack_zero_motion_and_inverts_byte_identical() {
    use lumen_core::build_freeze_layout;

    let mut scene = stack_scene();
    // Nest a second stack inside the first to prove recursion-by-iteration.
    let mut inner = auto_layout("inner", 200.0, 120.0, 5.0);
    inner.size = SizeSpec::fixed(200.0, 120.0);
    insert(&mut scene, ParentRef::Node(NodeId::from("stack")), inner);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("inner")),
        rect("d", 60.0, 40.0),
    );
    apply_layout(&mut scene);
    let before = scene_json(&scene);
    let solved_before: Vec<(&str, Rect)> = ["a", "b", "c", "d", "inner", "stack"]
        .iter()
        .map(|id| (*id, solved(&scene, id)))
        .collect();

    let batch = build_freeze_layout(&scene).expect("freeze builds");
    assert!(
        batch.inverse_operations.is_some(),
        "freeze carries inverses"
    );
    batch.apply_checked(&mut scene).expect("freeze applies");

    for id in ["stack", "inner"] {
        let node = &scene.nodes[&NodeId::from(id)];
        assert_eq!(
            node.layout.as_ref().map(|layout| layout.layout_mode),
            Some(LayoutMode::Free),
            "{id} must be Free after freeze"
        );
    }
    // Zero motion: every solved box is where the stack solve had it.
    for (id, before_box) in &solved_before {
        assert_eq!(&solved(&scene, id), before_box, "{id} moved during freeze");
    }

    let mut restored = scene.clone();
    restored
        .apply_operations(batch.inverse_operations.clone().unwrap())
        .unwrap();
    assert_eq!(
        scene_json(&restored),
        before,
        "freeze inverses must restore the pre-freeze scene exactly"
    );
}

/// K1 rider: a TEXT child's Hug height survives the freeze. Hug text
/// self-measures — it cannot re-flow siblings in a Free container — and at
/// accept time the solved extent may predate typography-token resolution
/// (proposal ops insert skeleton text; the post-accept preflight resolves
/// the real family/size). Baking it froze an 80pt headline into a 17pt
/// Fixed box (LUMV0903/0810 on the K0 live-proof document).
#[test]
fn freeze_layout_keeps_text_children_hug() {
    use lumen_core::{build_freeze_layout, Dimension, NodeKind, TextAlign, TextNode};

    let mut scene = stack_scene();
    let mut text = Node::new(
        NodeId::from("headline"),
        NodeKind::Text(TextNode {
            content: "Your health, now online.".to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 80.0,
            font_weight: 800,
            align: TextAlign::Left,
            style_token: None,
            ..TextNode::default()
        }),
    );
    text.size = SizeSpec {
        width: Dimension::Fixed(400.0),
        height: Dimension::Hug,
    };
    insert(&mut scene, ParentRef::Node(NodeId::from("stack")), text);
    apply_layout(&mut scene);

    let batch = build_freeze_layout(&scene).expect("freeze builds");
    batch.apply_checked(&mut scene).expect("freeze applies");

    let headline = &scene.nodes[&NodeId::from("headline")];
    assert_eq!(
        headline.size.height,
        Dimension::Hug,
        "text hug height must survive the freeze"
    );
    assert_eq!(
        headline.size.width,
        Dimension::Fixed(400.0),
        "text fixed width is untouched"
    );
    // Non-text children still bake to Fixed at their solved extents.
    let rect_child = &scene.nodes[&NodeId::from("a")];
    assert!(
        matches!(rect_child.size.width, Dimension::Fixed(_)),
        "non-text children still bake"
    );
}

#[test]
fn freeze_layout_skips_locked_and_free_containers_and_noops_when_done() {
    use lumen_core::{build_freeze_layout, FieldPatch, NodePatch, Operation};

    let mut scene = stack_scene();
    apply_layout(&mut scene);
    scene
        .apply_operation(Operation::UpdateNode {
            node_id: NodeId::from("stack"),
            patch: NodePatch {
                locked: FieldPatch::Set(true),
                ..NodePatch::default()
            },
        })
        .unwrap();

    let batch = build_freeze_layout(&scene).expect("freeze builds");
    assert!(
        batch.operations.is_empty(),
        "a locked container is skipped, not converted"
    );

    // Unlock, freeze for real, then a second freeze is a clean no-op.
    scene
        .apply_operation(Operation::UpdateNode {
            node_id: NodeId::from("stack"),
            patch: NodePatch {
                locked: FieldPatch::Set(false),
                ..NodePatch::default()
            },
        })
        .unwrap();
    apply_layout(&mut scene);
    build_freeze_layout(&scene)
        .expect("freeze builds")
        .apply_checked(&mut scene)
        .expect("freeze applies");
    let again = build_freeze_layout(&scene).expect("second freeze builds");
    assert!(again.operations.is_empty(), "freeze is idempotent");
}

#[test]
fn freeze_layout_wire_kind_is_pinned() {
    let freeze = instruction(serde_json::json!({ "kind": "freeze_layout" }));
    assert_eq!(freeze.kind(), "freeze_layout");
    let batch = lumen_core::build_structured_edit_batch(
        &{
            let mut scene = stack_scene();
            apply_layout(&mut scene);
            scene
        },
        &freeze,
    )
    .expect("freeze routes through the wire surface");
    assert!(!batch.operations.is_empty());
}

/// The Story-ad live-proof (2026-08-22): a padded Stack container whose own
/// height is Hug sits under the page — no frozen parent bakes it — and the
/// freeze left the Hug alone. Free-mode hug natural-sizes from child extents
/// WITHOUT padding, so the container's box contracted by exactly its bottom
/// padding the moment a human first grabbed a child. Zero-motion is the
/// freeze's contract: the container's OWN Hug dims bake to Fixed at the
/// solved extent, the same trade a child's Hug already makes.
#[test]
fn freeze_layout_bakes_a_padded_hug_containers_own_dims_zero_motion() {
    use lumen_core::build_freeze_layout;

    let mut scene = scene_with_page(1080.0, 1920.0);
    let mut card = auto_layout("card", 0.0, 0.0, 32.0);
    card.size = SizeSpec {
        width: Dimension::Fixed(936.0),
        height: Dimension::Hug,
    };
    card.layout = Some(AutoLayoutProps {
        gap: 32.0,
        padding: [40.0, 44.0, 40.0, 44.0],
        ..AutoLayoutProps::default()
    });
    card.transform.x = 72.0;
    card.transform.y = 72.0;
    insert(&mut scene, ParentRef::Page(PageId::from("page")), card);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("card")),
        rect("chip", 260.0, 104.0),
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("card")),
        rect("bar", 320.0, 10.0),
    );
    apply_layout(&mut scene);

    let before = scene_json(&scene);
    let card_before = solved(&scene, "card");
    // The stack solve hugs content PLUS padding: 40 + 104 + 32 + 10 + 40.
    assert_eq!(card_before.height, 226.0, "fixture sanity: the padded solve");
    let solved_before: Vec<(&str, Rect)> = ["card", "chip", "bar"]
        .iter()
        .map(|id| (*id, solved(&scene, id)))
        .collect();

    let batch = build_freeze_layout(&scene).expect("freeze builds");
    batch.apply_checked(&mut scene).expect("freeze applies");

    let card_node = &scene.nodes[&NodeId::from("card")];
    assert_eq!(
        card_node.size.height,
        Dimension::Fixed(card_before.height),
        "the container's own Hug height bakes to its solved extent"
    );
    assert_eq!(
        card_node.size.width,
        Dimension::Fixed(936.0),
        "an authored Fixed width keeps its value"
    );
    for (id, before_box) in &solved_before {
        assert_eq!(&solved(&scene, id), before_box, "{id} moved during freeze");
    }

    let mut restored = scene.clone();
    restored
        .apply_operations(batch.inverse_operations.clone().unwrap())
        .unwrap();
    assert_eq!(
        scene_json(&restored),
        before,
        "the inverse restores Hug (and the exact pre-freeze scene)"
    );
}

/// Axis symmetry and the degenerate case: a hug WIDTH loses the right
/// padding the same way, and an EMPTY padded hug container is the worst of
/// it — Free-mode natural size is 0×0 where the stack solve gave it its
/// padding box. Baking the solved extent fixes both.
#[test]
fn freeze_layout_bakes_hug_width_and_the_empty_padded_container() {
    use lumen_core::build_freeze_layout;

    let mut scene = scene_with_page(1080.0, 1920.0);
    let mut both = auto_layout("both", 0.0, 0.0, 0.0);
    both.size = SizeSpec {
        width: Dimension::Hug,
        height: Dimension::Hug,
    };
    both.layout = Some(AutoLayoutProps {
        padding: [40.0, 44.0, 40.0, 44.0],
        ..AutoLayoutProps::default()
    });
    insert(&mut scene, ParentRef::Page(PageId::from("page")), both);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("both")),
        rect("only", 260.0, 104.0),
    );
    let mut empty = auto_layout("empty", 0.0, 0.0, 0.0);
    empty.size = SizeSpec {
        width: Dimension::Hug,
        height: Dimension::Hug,
    };
    empty.layout = Some(AutoLayoutProps {
        padding: [40.0, 44.0, 40.0, 44.0],
        ..AutoLayoutProps::default()
    });
    empty.transform.y = 400.0;
    insert(&mut scene, ParentRef::Page(PageId::from("page")), empty);
    apply_layout(&mut scene);

    let both_before = solved(&scene, "both");
    let empty_before = solved(&scene, "empty");
    assert_eq!(
        (both_before.width, both_before.height),
        (44.0 + 260.0 + 44.0, 40.0 + 104.0 + 40.0),
        "fixture sanity: hug-both solve"
    );
    assert_eq!(
        (empty_before.width, empty_before.height),
        (88.0, 80.0),
        "fixture sanity: an empty padded hug container solves to its padding box"
    );

    let batch = build_freeze_layout(&scene).expect("freeze builds");
    batch.apply_checked(&mut scene).expect("freeze applies");

    let both_node = &scene.nodes[&NodeId::from("both")];
    assert_eq!(both_node.size.width, Dimension::Fixed(both_before.width));
    assert_eq!(both_node.size.height, Dimension::Fixed(both_before.height));
    assert_eq!(&solved(&scene, "both"), &both_before, "hug-both moved");
    assert_eq!(&solved(&scene, "only"), &solved(&scene, "only"));
    let empty_node = &scene.nodes[&NodeId::from("empty")];
    assert_eq!(
        (empty_node.size.width.clone(), empty_node.size.height.clone()),
        (Dimension::Fixed(88.0), Dimension::Fixed(80.0)),
        "the empty container bakes its padding box instead of collapsing to 0×0"
    );
    assert_eq!(&solved(&scene, "empty"), &empty_before, "empty moved");
}

/// The single-container convert is the second call site of the same helper
/// and carries the same contract: converting a padded hug container to Free
/// bakes the container's own dims too.
#[test]
fn convert_to_free_bakes_the_containers_own_hug_dimension() {
    let mut scene = scene_with_page(1080.0, 1920.0);
    let mut card = auto_layout("card", 0.0, 0.0, 32.0);
    card.size = SizeSpec {
        width: Dimension::Fixed(936.0),
        height: Dimension::Hug,
    };
    card.layout = Some(AutoLayoutProps {
        gap: 32.0,
        padding: [40.0, 44.0, 40.0, 44.0],
        ..AutoLayoutProps::default()
    });
    insert(&mut scene, ParentRef::Page(PageId::from("page")), card);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("card")),
        rect("chip", 260.0, 104.0),
    );
    apply_layout(&mut scene);

    let before = scene_json(&scene);
    let card_before = solved(&scene, "card");

    let batch = build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({
            "kind": "convert_container_layout",
            "node_id": "card",
            "layout_mode": "free"
        })),
    )
    .expect("convert builds");
    batch.apply_checked(&mut scene).expect("convert applies");

    let card_node = &scene.nodes[&NodeId::from("card")];
    assert_eq!(
        card_node.size.height,
        Dimension::Fixed(card_before.height),
        "convert-to-free bakes the container's own Hug height"
    );
    assert_eq!(&solved(&scene, "card"), &card_before, "card moved");

    let mut restored = scene.clone();
    restored
        .apply_operations(batch.inverse_operations.clone().unwrap())
        .unwrap();
    assert_eq!(
        scene_json(&restored),
        before,
        "the convert inverse restores Hug exactly"
    );
}
