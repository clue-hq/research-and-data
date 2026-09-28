//! Phase 1c gate — the invertible freehand operations. `detach_to_freehand`
//! pins a node at its solved box (the node itself does not move; Hug/Fill
//! bake to Fixed), `reattach_to_layout` returns it to the solve,
//! `convert_container_layout` flips a container between Stack and Free with
//! zero-motion baking on the way out. Every batch carries exact inverses:
//! applying them restores the pre-edit scene byte-identically — the
//! machinery Accept/Reject (0c) and future Compare/Revert ride on.

use lumen_core::{
    build_freeze_layout, build_structured_edit_batch, layout_operations, layout_scene,
    AutoLayoutDirection, AutoLayoutNode, AutoLayoutProps, Dimension, DocumentId, EditErrorKind,
    LayoutAnchor, LayoutMode, LayoutOptions, Node, NodeId, NodeKind, Operation, Orientation, Page,
    PageId, PagePreset, PageSize, ParentRef, PositionMode, Rect, Scene, SizeSpec,
    StructuredEditInstruction, TextAlign, TextNode, TextWrap, Unit,
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
    // The double-write case: a hug-height stack INSIDE the padded card is
    // baked twice — once by the parent's child-bake, once by its own
    // container pass — and both the size and the inverse must survive it.
    let mut nested = auto_layout("nested", 0.0, 0.0, 0.0);
    nested.size = SizeSpec {
        width: Dimension::Fixed(200.0),
        height: Dimension::Hug,
    };
    nested.layout = Some(AutoLayoutProps {
        padding: [10.0, 10.0, 10.0, 10.0],
        ..AutoLayoutProps::default()
    });
    insert(&mut scene, ParentRef::Node(NodeId::from("card")), nested);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("nested")),
        rect("leaf", 60.0, 40.0),
    );
    apply_layout(&mut scene);

    let before = scene_json(&scene);
    let card_before = solved(&scene, "card");
    let nested_before = solved(&scene, "nested");
    // The stack solve hugs content PLUS padding:
    // 40 + 104 + 32 + 10 + 32 + (10 + 40 + 10) + 40.
    assert_eq!(card_before.height, 318.0, "fixture sanity: the padded solve");
    assert_eq!(
        nested_before.height, 60.0,
        "fixture sanity: the nested padded hug"
    );
    let solved_before: Vec<(&str, Rect)> = ["card", "chip", "bar", "nested", "leaf"]
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
    assert_eq!(
        scene.nodes[&NodeId::from("nested")].size.height,
        Dimension::Fixed(nested_before.height),
        "the double-written nested hug lands on the same solved extent"
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
        "the inverse restores Hug (and the exact pre-freeze scene, nested double-write included)"
    );
}

/// THE RECORDED TRADE (pending founder ratification, HUG-FREEZE review
/// 2026-08-23): a container whose dimension is an UNRESOLVED `Token` keeps
/// its binding through the freeze — `bake_dimension`'s own rule, "baking a
/// token to a number would silently sever brand governance" — and therefore
/// STILL CONTRACTS, because Free-mode layout treats Token like Hug. The
/// brand pass rewrites every resolvable dimension token to Fixed before
/// layout runs, so this shape only exists in documents that are already in
/// the LUMV-warned unresolved-token state. This test pins BOTH halves of
/// the trade so neither can change silently: the binding survives, and the
/// motion is exactly the dropped padding. If the founder rules the other
/// way, flip these assertions deliberately.
#[test]
fn freeze_layout_keeps_a_token_dim_and_accepts_its_contraction() {
    use lumen_core::build_freeze_layout;

    let mut scene = scene_with_page(1080.0, 1920.0);
    let mut card = auto_layout("card", 0.0, 0.0, 32.0);
    card.size = SizeSpec {
        width: Dimension::Fixed(936.0),
        height: Dimension::Token {
            token: "size.card".to_owned(),
        },
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
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("card")),
        rect("bar", 320.0, 10.0),
    );
    apply_layout(&mut scene);
    // An unresolved token solves like Hug on the Stack side too: content
    // plus padding, 40 + 104 + 32 + 10 + 40.
    assert_eq!(solved(&scene, "card").height, 226.0, "fixture sanity");

    let batch = build_freeze_layout(&scene).expect("freeze builds");
    batch.apply_checked(&mut scene).expect("freeze applies");

    // Half one: brand governance survives — the token is NOT baked.
    assert_eq!(
        scene.nodes[&NodeId::from("card")].size.height,
        Dimension::Token {
            token: "size.card".to_owned(),
        },
        "the token binding survives the freeze"
    );
    // Half two: the accepted cost — Free-mode token-as-hug drops the
    // padding, so the box contracts by exactly the bottom inset.
    assert_eq!(
        solved(&scene, "card").height,
        186.0,
        "the recorded trade: an unresolved token dim contracts by its padding"
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
    let only_before = solved(&scene, "only");
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
    assert_eq!(&solved(&scene, "only"), &only_before, "the child moved");
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

// ---------------------------------------------------------------------------
// 2026-09-20 — freeze/bake parity for `fill` containers and hug-width text.
//
// The freeze bakes a node's Stack-solved extents so the Free mode the human
// then edits in shows exactly what the solve showed. Two dimensions used to
// escape that bake and re-resolve differently on the Free side:
//
//   * a CONTAINER's `fill` — the Stack solve treats a nested cross-axis `fill`
//     as hug (the children are built with no definite parent size), while Free
//     mode resolves `fill` against the parent's OUTER box, so a hugged pill row
//     snapped to the artboard edge on the first grab;
//   * a TEXT child's `hug` WIDTH — wrapped at the container width by the solve,
//     it measures unbounded in Free mode and unwraps across the artboard.
//
// Every test below asserts the same three things: whole-scene zero motion, a
// byte-identical inverse, and the specific dimension that must now be baked.
// ---------------------------------------------------------------------------

fn row_layout(id: &str, width: f64, height: f64, gap: f64) -> Node {
    let mut node = auto_layout(id, width, height, gap);
    node.kind = NodeKind::AutoLayout(AutoLayoutNode {
        direction: AutoLayoutDirection::Row,
        wrap: false,
    });
    node
}

/// Modelled on `tests/assets_pipeline.rs::text_node`, but wrapping — the
/// heuristic measurer wraps at the available width, which is the whole point
/// of the hug-width text cases below.
///
/// 20pt at the default 1.2 line-height ratio gives a whole-pixel 24.0 line
/// box on purpose. The Stack solve reports taffy's whole-pixel ROUNDED
/// geometry while the Free path natural-sizes unrounded, so a fractional
/// line box makes a surviving Hug HEIGHT look like sub-pixel "motion" — a
/// pre-existing rounding contract (`layout.rs` ~1187) that has nothing to do
/// with what these tests pin.
fn text(id: &str, content: &str, width: Dimension, height: Dimension) -> Node {
    let mut node = Node::new(
        NodeId::from(id),
        NodeKind::Text(TextNode {
            content: content.to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 20.0,
            font_weight: 600,
            align: TextAlign::Left,
            wrap: TextWrap::Wrap,
            style_token: None,
            ..TextNode::default()
        }),
    );
    node.size = SizeSpec { width, height };
    node
}

fn all_solved(scene: &Scene) -> Vec<(String, Rect)> {
    let ids = scene
        .nodes
        .keys()
        .map(|id| id.to_string())
        .collect::<Vec<_>>();
    ids.into_iter()
        .map(|id| {
            let bounds = solved(scene, &id);
            (id, bounds)
        })
        .collect()
}

/// Freeze the whole scene, assert nothing moved and that the inverse restores
/// the pre-freeze scene byte-identically, and hand back the frozen scene
/// (re-laid-out) for the per-test dimension assertions.
fn frozen_zero_motion(scene: &Scene) -> Scene {
    let before_geometry = all_solved(scene);
    let before_json = scene_json(scene);

    let batch = build_freeze_layout(scene).expect("freeze builds");
    let mut frozen = scene.clone();
    frozen.apply_operations(batch.operations.clone()).unwrap();

    let mut restored = frozen.clone();
    restored
        .apply_operations(batch.inverse_operations.clone().unwrap())
        .unwrap();
    assert_eq!(
        scene_json(&restored),
        before_json,
        "the freeze inverse must restore the pre-freeze scene exactly"
    );

    apply_layout(&mut frozen);
    for (id, bounds) in &before_geometry {
        assert_eq!(&solved(&frozen, id), bounds, "{id} moved during freeze");
    }
    frozen
}

fn size_of(scene: &Scene, id: &str) -> SizeSpec {
    scene.nodes[&NodeId::from(id)].size.clone()
}

/// The harvested ad's pill fixture: a padded 1080×1080 artboard, a `fill × hug`
/// products column, and three `fill × hug` padded rows each hugging a 577-wide
/// label. Returns the scene UNLAID — callers `apply_layout` themselves.
fn pills_scene() -> Scene {
    let mut scene = scene_with_page(1080.0, 1080.0);
    let mut artboard = auto_layout("artboard", 1080.0, 1080.0, 18.0);
    artboard.layout = Some(AutoLayoutProps {
        gap: 18.0,
        padding: [48.0, 52.0, 48.0, 52.0],
        ..AutoLayoutProps::default()
    });
    insert(&mut scene, ParentRef::Page(PageId::from("page")), artboard);

    let mut products = auto_layout("products", 0.0, 0.0, 10.0);
    products.size = SizeSpec {
        width: Dimension::Fill { weight: 1.0 },
        height: Dimension::Hug,
    };
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("artboard")),
        products,
    );

    for id in ["row_md", "row_in", "row_dac"] {
        let mut row = auto_layout(id, 0.0, 0.0, 0.0);
        row.size = SizeSpec {
            width: Dimension::Fill { weight: 1.0 },
            height: Dimension::Hug,
        };
        row.layout = Some(AutoLayoutProps {
            padding: [14.0, 20.0, 14.0, 20.0],
            ..AutoLayoutProps::default()
        });
        insert(&mut scene, ParentRef::Node(NodeId::from("products")), row);
        insert(
            &mut scene,
            ParentRef::Node(NodeId::from(id)),
            rect(&format!("{id}_label"), 577.0, 41.0),
        );
    }
    scene
}

/// The 2026-09-20 defect, in the shape it shipped in: the harvested ad's pill
/// rows are `fill × hug` containers under a `fill × hug` column, and the Stack
/// solve hugged them (617) because their parent has no definite cross-axis
/// size. Keeping `fill` through the freeze let Free mode re-resolve them
/// against the artboard content box (976) on the very first click.
#[test]
fn freeze_layout_bakes_a_fill_containers_solved_width() {
    let mut scene = pills_scene();
    apply_layout(&mut scene);

    assert_eq!(
        solved(&scene, "row_md").width,
        617.0,
        "fixture sanity: the row hugged its 577 label plus 20+20 padding"
    );
    assert_eq!(
        solved(&scene, "products").width,
        976.0,
        "fixture sanity: the column filled the artboard's 1080-52-52 content box"
    );

    let frozen = frozen_zero_motion(&scene);
    for id in ["row_md", "row_in", "row_dac"] {
        assert_eq!(
            size_of(&frozen, id).width,
            Dimension::Fixed(617.0),
            "{id}'s fill width must bake to the extent the solve gave it"
        );
    }
    assert_eq!(size_of(&frozen, "products").width, Dimension::Fixed(976.0));
}

/// A lone `fill × fixed` container under a padded artboard: the bake is the
/// parent's CONTENT width (976), never its outer box (1080).
#[test]
fn freeze_layout_bakes_a_fill_container_under_a_padded_parent_to_the_content_width() {
    let mut scene = scene_with_page(1080.0, 1080.0);
    let mut artboard = auto_layout("artboard", 1080.0, 1080.0, 0.0);
    artboard.layout = Some(AutoLayoutProps {
        padding: [48.0, 52.0, 48.0, 52.0],
        ..AutoLayoutProps::default()
    });
    insert(&mut scene, ParentRef::Page(PageId::from("page")), artboard);

    let mut band = auto_layout("band", 0.0, 120.0, 0.0);
    band.size = SizeSpec {
        width: Dimension::Fill { weight: 1.0 },
        height: Dimension::Fixed(120.0),
    };
    insert(&mut scene, ParentRef::Node(NodeId::from("artboard")), band);
    apply_layout(&mut scene);

    assert_eq!(solved(&scene, "band").width, 976.0, "fixture sanity");

    let frozen = frozen_zero_motion(&scene);
    assert_eq!(
        size_of(&frozen, "band").width,
        Dimension::Fixed(976.0),
        "the content width, never the artboard's 1080 outer box"
    );
}

/// Weighted main-axis `fill`: the bake must keep each child's SHARE, not its
/// weight — a Free re-resolve has no siblings to divide against.
#[test]
fn freeze_layout_bakes_weighted_fill_row_children_to_their_shares() {
    let mut scene = scene_with_page(1200.0, 600.0);
    let bar = row_layout("bar", 900.0, 100.0, 0.0);
    insert(&mut scene, ParentRef::Page(PageId::from("page")), bar);

    for (id, weight) in [("wide", 2.0), ("narrow", 1.0)] {
        let mut cell = auto_layout(id, 0.0, 100.0, 0.0);
        cell.size = SizeSpec {
            width: Dimension::Fill { weight },
            height: Dimension::Fixed(100.0),
        };
        insert(&mut scene, ParentRef::Node(NodeId::from("bar")), cell);
    }
    apply_layout(&mut scene);

    assert_eq!(solved(&scene, "wide").width, 600.0, "fixture sanity");
    assert_eq!(solved(&scene, "narrow").width, 300.0, "fixture sanity");

    let frozen = frozen_zero_motion(&scene);
    assert_eq!(size_of(&frozen, "wide").width, Dimension::Fixed(600.0));
    assert_eq!(size_of(&frozen, "narrow").width, Dimension::Fixed(300.0));
}

/// `layout.rs::flow_context`'s main-axis fallback: a `fill` child of a Row
/// whose fixed siblings already consume the whole main content is demoted to
/// its natural (hugged) size. The bake must record THAT, not the row width.
#[test]
fn freeze_layout_bakes_main_axis_fill_fallback_to_natural_size() {
    let mut scene = scene_with_page(1200.0, 600.0);
    let bar = row_layout("bar", 300.0, 60.0, 0.0);
    insert(&mut scene, ParentRef::Page(PageId::from("page")), bar);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("bar")),
        rect("hog", 300.0, 60.0),
    );
    let mut flexi = auto_layout("flexi", 0.0, 60.0, 0.0);
    flexi.size = SizeSpec {
        width: Dimension::Fill { weight: 1.0 },
        height: Dimension::Fixed(60.0),
    };
    insert(&mut scene, ParentRef::Node(NodeId::from("bar")), flexi);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("flexi")),
        rect("flexi_label", 120.0, 60.0),
    );
    apply_layout(&mut scene);

    let natural = solved(&scene, "flexi").width;
    assert_eq!(
        natural, 120.0,
        "fixture sanity: the fallback demoted the fill child to its hugged content"
    );

    let frozen = frozen_zero_motion(&scene);
    assert_eq!(size_of(&frozen, "flexi").width, Dimension::Fixed(natural));
}

/// A hug-width text the solve wrapped at the container width: its WIDTH must
/// bake (otherwise Free mode measures it unbounded and it unwraps across the
/// artboard), while its HEIGHT keeps hugging so it re-measures honestly.
#[test]
fn freeze_layout_bakes_a_wrapped_hug_width_text_to_its_solved_width() {
    let mut scene = scene_with_page(800.0, 800.0);
    let column = auto_layout("column", 300.0, 400.0, 0.0);
    insert(&mut scene, ParentRef::Page(PageId::from("page")), column);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("column")),
        text(
            "copy",
            "A deliberately long sentence that has to wrap several times inside a three hundred pixel column before it runs out of words.",
            Dimension::Hug,
            Dimension::Hug,
        ),
    );
    apply_layout(&mut scene);

    let solved_copy = solved(&scene, "copy");
    assert!(
        solved_copy.height > 20.0,
        "fixture sanity: the sentence wrapped to more than one line (height {})",
        solved_copy.height
    );

    let frozen = frozen_zero_motion(&scene);
    assert_eq!(
        size_of(&frozen, "copy").width,
        Dimension::Fixed(solved_copy.width),
        "the wrapped width must survive into Free mode"
    );
    assert_eq!(
        size_of(&frozen, "copy").height,
        Dimension::Hug,
        "the K1 rider is narrowed to HEIGHT: hug text still re-measures vertically"
    );
}

/// The agent's headline shape (`fill × hug`): the width bakes to the solved
/// extent, the height keeps hugging.
#[test]
fn freeze_layout_keeps_a_fill_x_hug_text_hugging_its_height() {
    let mut scene = scene_with_page(800.0, 800.0);
    let mut column = auto_layout("column", 400.0, 400.0, 0.0);
    column.layout = Some(AutoLayoutProps {
        padding: [20.0, 30.0, 20.0, 30.0],
        ..AutoLayoutProps::default()
    });
    insert(&mut scene, ParentRef::Page(PageId::from("page")), column);
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("column")),
        text(
            "headline",
            "Everything you need to ship a brand-true campaign in one afternoon.",
            Dimension::Fill { weight: 1.0 },
            Dimension::Hug,
        ),
    );
    apply_layout(&mut scene);

    let solved_headline = solved(&scene, "headline");
    assert_eq!(
        solved_headline.width, 340.0,
        "fixture sanity: the headline filled the 400-30-30 content box"
    );

    let frozen = frozen_zero_motion(&scene);
    assert_eq!(
        size_of(&frozen, "headline").width,
        Dimension::Fixed(340.0),
        "a fill text width bakes like any other fill"
    );
    assert_eq!(
        size_of(&frozen, "headline").height,
        Dimension::Hug,
        "hug height survives the freeze"
    );
}

/// `align_x: Stretch` sizes a cross-axis child from the container, not from
/// its own dimension — the bake must record the stretched extent.
#[test]
fn freeze_layout_bakes_stretch_aligned_children() {
    let mut scene = scene_with_page(800.0, 800.0);
    let mut column = auto_layout("column", 400.0, 300.0, 12.0);
    column.layout = Some(AutoLayoutProps {
        gap: 12.0,
        padding: [10.0, 24.0, 10.0, 24.0],
        align_x: LayoutAnchor::Stretch,
        ..AutoLayoutProps::default()
    });
    insert(&mut scene, ParentRef::Page(PageId::from("page")), column);
    for id in ["bar_one", "bar_two"] {
        let mut child = rect(id, 0.0, 30.0);
        child.size = SizeSpec {
            width: Dimension::Hug,
            height: Dimension::Fixed(30.0),
        };
        insert(&mut scene, ParentRef::Node(NodeId::from("column")), child);
    }
    apply_layout(&mut scene);

    let stretched = solved(&scene, "bar_one").width;
    assert_eq!(
        stretched, 352.0,
        "fixture sanity: stretched across the 400-24-24 content box"
    );

    let frozen = frozen_zero_motion(&scene);
    for id in ["bar_one", "bar_two"] {
        assert_eq!(size_of(&frozen, id).width, Dimension::Fixed(stretched));
    }
}

/// A wrapping Row: the children sit on several lines, and the freeze must bake
/// those line positions without re-flowing them.
#[test]
fn freeze_layout_bakes_a_wrapping_row() {
    let mut scene = scene_with_page(800.0, 800.0);
    let mut bar = row_layout("bar", 500.0, 300.0, 0.0);
    bar.kind = NodeKind::AutoLayout(AutoLayoutNode {
        direction: AutoLayoutDirection::Row,
        wrap: true,
    });
    insert(&mut scene, ParentRef::Page(PageId::from("page")), bar);
    for index in 0..5 {
        insert(
            &mut scene,
            ParentRef::Node(NodeId::from("bar")),
            rect(&format!("tile_{index}"), 200.0, 50.0),
        );
    }
    apply_layout(&mut scene);

    assert_ne!(
        solved(&scene, "tile_0").y,
        solved(&scene, "tile_2").y,
        "fixture sanity: the row wrapped onto a second line"
    );

    // Zero motion across a wrapped row is the whole assertion here.
    let frozen = frozen_zero_motion(&scene);
    assert_eq!(
        frozen.nodes[&NodeId::from("bar")]
            .layout
            .as_ref()
            .unwrap()
            .layout_mode,
        LayoutMode::Free
    );
}

/// The single-container convert shares `baked_container_size`, so it bakes the
/// container's own `fill` too — with its Stack parent left alone, proving the
/// bake records the solve rather than tracking the parent.
#[test]
fn convert_container_layout_bakes_the_containers_own_fill() {
    let mut scene = scene_with_page(1080.0, 1080.0);
    let mut artboard = auto_layout("artboard", 1080.0, 1080.0, 0.0);
    artboard.layout = Some(AutoLayoutProps {
        padding: [48.0, 52.0, 48.0, 52.0],
        ..AutoLayoutProps::default()
    });
    insert(&mut scene, ParentRef::Page(PageId::from("page")), artboard);
    let mut products = auto_layout("products", 0.0, 0.0, 10.0);
    products.size = SizeSpec {
        width: Dimension::Fill { weight: 1.0 },
        height: Dimension::Hug,
    };
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("artboard")),
        products,
    );
    insert(
        &mut scene,
        ParentRef::Node(NodeId::from("products")),
        rect("tile", 400.0, 60.0),
    );
    apply_layout(&mut scene);

    let before_geometry = all_solved(&scene);
    let before_json = scene_json(&scene);

    let batch = build_structured_edit_batch(
        &scene,
        &instruction(serde_json::json!({
            "kind": "convert_container_layout",
            "node_id": "products",
            "layout_mode": "free"
        })),
    )
    .expect("convert builds");
    let mut converted = scene.clone();
    batch
        .apply_checked(&mut converted)
        .expect("convert applies");

    let mut restored = converted.clone();
    restored
        .apply_operations(batch.inverse_operations.clone().unwrap())
        .unwrap();
    assert_eq!(
        scene_json(&restored),
        before_json,
        "the convert inverse restores Fill exactly"
    );

    apply_layout(&mut converted);
    for (id, bounds) in &before_geometry {
        assert_eq!(&solved(&converted, id), bounds, "{id} moved during convert");
    }
    assert_eq!(
        size_of(&converted, "products").width,
        Dimension::Fixed(976.0),
        "the container's own fill bakes on the way out of the solve"
    );
    assert_eq!(
        converted.nodes[&NodeId::from("artboard")]
            .layout
            .as_ref()
            .unwrap()
            .layout_mode,
        LayoutMode::Stack,
        "the parent stays in the solve"
    );
}

/// Item 2 (2026-09-20): a `fill` child of a FREE container is the container's padded
/// content box, exactly as it would be in Stack mode — never the outer box.
#[test]
fn free_container_fill_children_resolve_against_the_content_box() {
    let mut scene = scene_with_page(1080.0, 1080.0);
    let mut artboard = auto_layout("artboard", 1080.0, 1080.0, 0.0);
    artboard.layout = Some(AutoLayoutProps {
        padding: [48.0, 52.0, 48.0, 52.0],
        layout_mode: LayoutMode::Free,
        ..AutoLayoutProps::default()
    });
    insert(&mut scene, ParentRef::Page(PageId::from("page")), artboard);
    let mut band = rect("band", 0.0, 60.0);
    band.size = SizeSpec {
        width: Dimension::Fill { weight: 1.0 },
        height: Dimension::Fixed(60.0),
    };
    band.transform.x = 52.0;
    band.transform.y = 48.0;
    insert(&mut scene, ParentRef::Node(NodeId::from("artboard")), band);
    apply_layout(&mut scene);
    let solved_band = solved(&scene, "band");
    assert_eq!(solved_band.width, 976.0, "fill = outer 1080 − 52 − 52");
    assert_eq!(
        (solved_band.x, solved_band.y),
        (52.0, 48.0),
        "position is the author's transform, outer-relative"
    );
}

/// Stack/Free parity on the Task 1 pills fixture: freeze the padded artboard,
/// then drop a NEW `fill × fixed` band into the frozen (Free) container. The
/// width it resolves to must be the same 976 the Stack solve hands a `fill`
/// child — a human editing after the handoff gets the same geometry rules.
#[test]
fn a_fill_child_added_after_the_freeze_matches_the_stack_solves_width() {
    let mut scene = pills_scene();
    apply_layout(&mut scene);
    assert_eq!(
        solved(&scene, "products").width,
        976.0,
        "fixture sanity: the Stack solve fills the 1080-52-52 content box"
    );

    let mut frozen = frozen_zero_motion(&scene);
    assert_eq!(
        frozen.nodes[&NodeId::from("artboard")]
            .layout
            .as_ref()
            .unwrap()
            .layout_mode,
        LayoutMode::Free,
        "the freeze puts the artboard in Free mode"
    );

    let mut band = rect("band", 0.0, 60.0);
    band.size = SizeSpec {
        width: Dimension::Fill { weight: 1.0 },
        height: Dimension::Fixed(60.0),
    };
    band.transform.x = 52.0;
    band.transform.y = 900.0;
    insert(&mut frozen, ParentRef::Node(NodeId::from("artboard")), band);
    apply_layout(&mut frozen);

    let solved_band = solved(&frozen, "band");
    assert_eq!(
        solved_band.width,
        solved(&scene, "products").width,
        "Free-mode fill matches the Stack solve's fill: the padded content box"
    );
    assert_eq!(
        (solved_band.x, solved_band.y),
        (52.0, 900.0),
        "the new child keeps the author's outer-relative transform"
    );
}
