use lumen_core::editing::solid_fill;
use lumen_core::{
    build_clone_subtree, build_modify_operations, build_move_after, build_move_before,
    build_replace_node, build_safe_delete, resolve_edit_target, AssetKind, AssetMediaMetadata,
    AssetPlacement, AssetProvenance, AssetRecord, AssetSource, AssetStatus, CloneSlotPolicy,
    CloneSubtreeRequest, Color, ComputedClonePolicy, Dimension, DocumentId, EditPatch,
    EditTargetRef, Effect, EffectId, EffectKind, FieldPatch, ImageNode, Node, NodeEditPatch,
    NodeId, NodeKind, OptionalFieldPatch, Orientation, Page, PageEditPatch, PageId, PagePreset,
    PageSize, Paint, PaintId, ParentRef, RelativePlacement, ReplaceNodeRequest, ReplaceSlotPolicy,
    Scene, SizeSpec, Slot, SlotId, SlotKey, StackEntryEdit, Stroke, StrokeCap, TextAlign,
    TextEditPatch, TextNode, Unit,
};

fn square_page() -> Page {
    Page {
        id: PageId::from("page_square"),
        name: "Square".to_owned(),
        size: PageSize {
            width: 1080.0,
            height: 1080.0,
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

fn text_node(id: &str, content: &str) -> Node {
    let mut node = Node::new(
        NodeId::from(id),
        NodeKind::Text(TextNode {
            content: content.to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 64.0,
            font_weight: 800,
            align: TextAlign::Left,
            ..TextNode::default()
        }),
    );
    node.size = SizeSpec {
        width: Dimension::Fill { weight: 1.0 },
        height: Dimension::Hug,
    };
    node
}

fn logo_asset(id: &str) -> AssetRecord {
    AssetRecord {
        id: id.into(),
        label: format!("Logo {id}"),
        kind: AssetKind::Logo,
        status: AssetStatus::Ready,
        source: AssetSource::Manual {
            label: "fixture".to_owned(),
        },
        media: AssetMediaMetadata::default(),
        raster: None,
        vector: None,
        font: None,
        logo: None,
        license: None,
        provenance: AssetProvenance::default(),
        tags: Vec::new(),
    }
}

fn scene_with_ad() -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_phase_d"), "Phase D");
    scene
        .apply_operation(lumen_core::Operation::AddPage {
            page: square_page(),
        })
        .unwrap();
    scene
        .apply_operations([
            lumen_core::Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_square")),
                index: 0,
                node: Node::new(NodeId::from("hero"), NodeKind::Frame),
            },
            lumen_core::Operation::InsertNode {
                parent: ParentRef::Node(NodeId::from("hero")),
                index: 0,
                node: text_node("headline", "Oversized headline that needs repair"),
            },
            lumen_core::Operation::InsertNode {
                parent: ParentRef::Node(NodeId::from("hero")),
                index: 1,
                node: text_node("body", "Supporting copy"),
            },
            lumen_core::Operation::InsertNode {
                parent: ParentRef::Node(NodeId::from("hero")),
                index: 2,
                node: Node::new(
                    NodeId::from("logo"),
                    NodeKind::Image(ImageNode {
                        asset_id: "asset_logo".into(),
                        alt: Some("Logo".to_owned()),
                    }),
                ),
            },
            lumen_core::Operation::InsertNode {
                parent: ParentRef::Node(NodeId::from("hero")),
                index: 3,
                node: text_node("cta", "Book a demo"),
            },
        ])
        .unwrap();
    scene
        .apply_operations([
            lumen_core::Operation::UpsertAsset {
                asset: logo_asset("asset_logo"),
            },
            lumen_core::Operation::UpsertAsset {
                asset: logo_asset("asset_logo_alt"),
            },
        ])
        .unwrap();

    let mut slot = Slot::text_short(
        SlotId::from("slot_campaign_headline"),
        SlotKey::from("campaign.headline"),
        "Campaign headline",
    );
    slot.bound_nodes.push(NodeId::from("headline"));
    scene
        .apply_operation(lumen_core::Operation::UpsertSlot { slot })
        .unwrap();
    scene
}

#[test]
fn resolves_node_page_slot_and_asset_targets() {
    let scene = scene_with_ad();

    let headline = resolve_edit_target(&scene, &EditTargetRef::Node(NodeId::from("headline")))
        .expect("node target should resolve");
    assert_eq!(headline.parent, Some(ParentRef::Node(NodeId::from("hero"))));
    assert_eq!(headline.index, Some(0));
    assert_eq!(headline.page_id, Some(PageId::from("page_square")));

    assert!(resolve_edit_target(&scene, &EditTargetRef::Page(PageId::from("page_square"))).is_ok());
    assert!(resolve_edit_target(
        &scene,
        &EditTargetRef::SlotKey(SlotKey::from("campaign.headline"))
    )
    .is_ok());
    assert!(resolve_edit_target(&scene, &EditTargetRef::Asset("asset_logo".into())).is_ok());
    assert!(resolve_edit_target(&scene, &EditTargetRef::Node(NodeId::from("missing"))).is_err());
}

#[test]
fn node_text_patch_updates_only_target_and_clears_computed() {
    let mut scene = scene_with_ad();
    scene
        .nodes
        .get_mut(&NodeId::from("headline"))
        .unwrap()
        .computed = Some(lumen_core::ComputedGeometry {
        layout_bounds: lumen_core::Rect {
            x: 1.0,
            y: 2.0,
            width: 3.0,
            height: 4.0,
        },
        render_bounds: lumen_core::Rect {
            x: 1.0,
            y: 2.0,
            width: 3.0,
            height: 4.0,
        },
        text_lines: Vec::new(),
    });

    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("headline")),
        EditPatch::Node(NodeEditPatch {
            text: Some(TextEditPatch {
                content: FieldPatch::Set("Let surgeons focus on surgery.".to_owned()),
                font_size: FieldPatch::Set(44.0),
                ..TextEditPatch::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();

    batch.apply_checked(&mut scene).unwrap();

    let NodeKind::Text(headline) = &scene.nodes[&NodeId::from("headline")].kind else {
        panic!("expected text node");
    };
    assert_eq!(headline.content, "Let surgeons focus on surgery.");
    assert_eq!(headline.font_size, 44.0);
    assert_eq!(
        scene.nodes[&NodeId::from("body")].kind,
        NodeKind::Text(TextNode {
            content: "Supporting copy".to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 64.0,
            font_weight: 800,
            align: TextAlign::Left,
            ..TextNode::default()
        })
    );
    assert!(scene.nodes[&NodeId::from("headline")].computed.is_none());
}

#[test]
fn page_patch_preserves_children() {
    let mut scene = scene_with_ad();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Page(PageId::from("page_square")),
        EditPatch::Page(PageEditPatch {
            size: FieldPatch::Set(PageSize {
                width: 1200.0,
                height: 628.0,
                unit: Unit::Px,
                preset: Some(PagePreset::Custom),
                orientation: Orientation::Landscape,
                source: None,
                output: None,
            }),
            ..PageEditPatch::default()
        }),
    )
    .unwrap();

    batch.apply_checked(&mut scene).unwrap();

    let page = &scene.pages[&PageId::from("page_square")];
    assert_eq!(page.size.width, 1200.0);
    assert_eq!(page.children, vec![NodeId::from("hero")]);
}

#[test]
fn safe_delete_removes_descendants_and_slot_bindings() {
    let mut scene = scene_with_ad();
    let batch = build_safe_delete(&scene, NodeId::from("headline")).unwrap();

    batch.apply_checked(&mut scene).unwrap();

    assert!(!scene.nodes.contains_key(&NodeId::from("headline")));
    assert!(scene
        .slot_by_key(&SlotKey::from("campaign.headline"))
        .unwrap()
        .bound_nodes
        .is_empty());
}

#[test]
fn before_after_reorders_with_same_parent_index_math() {
    let mut scene = scene_with_ad();
    build_move_after(&scene, NodeId::from("headline"), NodeId::from("cta"))
        .unwrap()
        .apply_checked(&mut scene)
        .unwrap();
    assert_eq!(
        scene.nodes[&NodeId::from("hero")].children,
        vec![
            NodeId::from("body"),
            NodeId::from("logo"),
            NodeId::from("cta"),
            NodeId::from("headline")
        ]
    );

    build_move_before(&scene, NodeId::from("headline"), NodeId::from("body"))
        .unwrap()
        .apply_checked(&mut scene)
        .unwrap();
    assert_eq!(
        scene.nodes[&NodeId::from("hero")].children,
        vec![
            NodeId::from("headline"),
            NodeId::from("body"),
            NodeId::from("logo"),
            NodeId::from("cta")
        ]
    );
}

#[test]
fn image_asset_patch_uses_checked_asset_placement() {
    let mut scene = scene_with_ad();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("logo")),
        EditPatch::Node(NodeEditPatch {
            image_asset_id: OptionalFieldPatch::Set("asset_logo_alt".into()),
            asset_placement: OptionalFieldPatch::Set(AssetPlacement {
                alt_text: Some("Alternate logo".to_owned()),
                ..AssetPlacement::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();

    batch.apply_checked(&mut scene).unwrap();

    let NodeKind::Image(image) = &scene.nodes[&NodeId::from("logo")].kind else {
        panic!("expected image node");
    };
    assert_eq!(image.asset_id, "asset_logo_alt".into());
    assert_eq!(image.alt.as_deref(), Some("Alternate logo"));
}

#[test]
fn clone_subtree_creates_deterministic_ids_and_clears_computed() {
    let mut scene = scene_with_ad();
    scene
        .nodes
        .get_mut(&NodeId::from("headline"))
        .unwrap()
        .computed = Some(lumen_core::ComputedGeometry {
        layout_bounds: lumen_core::Rect {
            x: 1.0,
            y: 2.0,
            width: 3.0,
            height: 4.0,
        },
        render_bounds: lumen_core::Rect {
            x: 1.0,
            y: 2.0,
            width: 3.0,
            height: 4.0,
        },
        text_lines: Vec::new(),
    });

    let batch = build_clone_subtree(
        &scene,
        CloneSubtreeRequest {
            source: NodeId::from("headline"),
            new_root_id: NodeId::from("headline_2"),
            placement: RelativePlacement::After {
                anchor: NodeId::from("headline"),
            },
            slot_policy: CloneSlotPolicy::Detach,
            computed_policy: ComputedClonePolicy::Clear,
        },
    )
    .unwrap();

    batch.apply_checked(&mut scene).unwrap();

    assert!(scene.nodes.contains_key(&NodeId::from("headline_2")));
    assert!(scene.nodes[&NodeId::from("headline_2")].computed.is_none());
    assert_eq!(
        scene.nodes[&NodeId::from("hero")].children[1],
        NodeId::from("headline_2")
    );
    assert_eq!(
        scene
            .slot_by_key(&SlotKey::from("campaign.headline"))
            .unwrap()
            .bound_nodes,
        vec![NodeId::from("headline")]
    );
}

/// Round-trip identity: applying a batch and then its stored inverse must
/// restore the original scene exactly (structural equality, not operation
/// comparison). This is the V1.1 correctness property.
fn assert_batch_round_trip(scene: &Scene, batch: &lumen_core::EditBatch) {
    let mut working = scene.clone();
    batch.apply_checked(&mut working).expect("batch applies");
    let inverses = batch
        .inverse_operations
        .clone()
        .expect("batch carries inverses");
    working
        .apply_operations_checked(inverses)
        .expect("inverse batch applies");
    assert_eq!(&working, scene, "inverse must restore the original scene");
}

#[test]
fn inverse_round_trip_for_node_modify_restores_computed() {
    let mut scene = scene_with_ad();
    scene
        .nodes
        .get_mut(&NodeId::from("headline"))
        .unwrap()
        .computed = Some(lumen_core::ComputedGeometry {
        layout_bounds: lumen_core::Rect {
            x: 1.0,
            y: 2.0,
            width: 3.0,
            height: 4.0,
        },
        render_bounds: lumen_core::Rect {
            x: 1.0,
            y: 2.0,
            width: 3.0,
            height: 4.0,
        },
        text_lines: Vec::new(),
    });

    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("headline")),
        EditPatch::Node(NodeEditPatch {
            text: Some(TextEditPatch {
                content: FieldPatch::Set("Repaired".to_owned()),
                font_size: FieldPatch::Set(44.0),
                ..TextEditPatch::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();

    assert_batch_round_trip(&scene, &batch);
}

#[test]
fn inverse_round_trip_for_page_modify() {
    let scene = scene_with_ad();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Page(PageId::from("page_square")),
        EditPatch::Page(PageEditPatch {
            size: FieldPatch::Set(PageSize {
                width: 1200.0,
                height: 628.0,
                unit: Unit::Px,
                preset: Some(PagePreset::Custom),
                orientation: Orientation::Landscape,
                source: None,
                output: None,
            }),
            ..PageEditPatch::default()
        }),
    )
    .unwrap();

    assert_batch_round_trip(&scene, &batch);
}

#[test]
fn inverse_round_trip_for_slot_modify_with_bindings() {
    let scene = scene_with_ad();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::SlotKey(SlotKey::from("campaign.headline")),
        EditPatch::Slot(lumen_core::SlotEditPatch {
            placeholder: OptionalFieldPatch::Set("New placeholder".to_owned()),
            bind_nodes: vec![NodeId::from("body")],
            unbind_nodes: vec![NodeId::from("headline")],
            ..lumen_core::SlotEditPatch::default()
        }),
    )
    .unwrap();

    assert_batch_round_trip(&scene, &batch);
}

#[test]
fn inverse_round_trip_for_asset_modify() {
    let scene = scene_with_ad();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Asset("asset_logo".into()),
        EditPatch::Asset(lumen_core::AssetEditPatch {
            label: FieldPatch::Set("Renamed logo".to_owned()),
            ..lumen_core::AssetEditPatch::default()
        }),
    )
    .unwrap();

    assert_batch_round_trip(&scene, &batch);
}

#[test]
fn inverse_round_trip_for_safe_delete_restores_subtree_and_bindings() {
    let scene = scene_with_ad();
    let batch = build_safe_delete(&scene, NodeId::from("hero")).unwrap();
    assert_batch_round_trip(&scene, &batch);
}

#[test]
fn inverse_round_trip_for_moves() {
    let scene = scene_with_ad();

    let after = build_move_after(&scene, NodeId::from("headline"), NodeId::from("cta")).unwrap();
    assert_batch_round_trip(&scene, &after);

    let before = build_move_before(&scene, NodeId::from("cta"), NodeId::from("headline")).unwrap();
    assert_batch_round_trip(&scene, &before);

    let cross_parent = lumen_core::build_move_to_parent(
        &scene,
        NodeId::from("logo"),
        ParentRef::Page(PageId::from("page_square")),
        1,
    )
    .unwrap();
    assert_batch_round_trip(&scene, &cross_parent);
}

#[test]
fn inverse_round_trip_for_clone_with_copied_slots_and_lineage() {
    let scene = scene_with_ad();
    let batch = build_clone_subtree(
        &scene,
        CloneSubtreeRequest {
            source: NodeId::from("headline"),
            new_root_id: NodeId::from("headline_2"),
            placement: RelativePlacement::After {
                anchor: NodeId::from("headline"),
            },
            slot_policy: CloneSlotPolicy::Copy,
            computed_policy: ComputedClonePolicy::Clear,
        },
    )
    .unwrap();

    let lineage = batch.lineage.as_ref().expect("clone records lineage");
    assert_eq!(lineage.source_root, NodeId::from("headline"));
    assert_eq!(
        lineage.id_map,
        vec![(NodeId::from("headline"), NodeId::from("headline_2"))]
    );

    assert_batch_round_trip(&scene, &batch);
}

#[test]
fn inverse_round_trip_for_replace_node() {
    let mut scene = scene_with_ad();
    scene
        .apply_operation(lumen_core::Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_square")),
            index: 1,
            node: text_node("headline_replacement", "Replacement"),
        })
        .unwrap();

    let batch = build_replace_node(
        &scene,
        ReplaceNodeRequest {
            target: NodeId::from("headline"),
            replacement: NodeId::from("headline_replacement"),
            slot_policy: ReplaceSlotPolicy::PreserveCompatible,
        },
    )
    .unwrap();

    assert_batch_round_trip(&scene, &batch);
}

#[test]
fn inverse_round_trip_for_document_and_brand_kit_updates() {
    let scene = scene_with_ad();
    let operations = vec![
        lumen_core::Operation::UpdateDocument {
            patch: lumen_core::DocumentPatch {
                title: FieldPatch::Set("Renamed".to_owned()),
                artifact_type: OptionalFieldPatch::Set("linkedin_ad".to_owned()),
                ..lumen_core::DocumentPatch::default()
            },
        },
        lumen_core::Operation::SetBrandKitRef {
            brand_kit_id: "brand_kit_fixture".into(),
            version: 3,
        },
    ];

    let inverses = scene
        .invert_operations(&operations)
        .expect("invertible")
        .expect("not finalization");

    let mut working = scene.clone();
    working.apply_operations_checked(operations).unwrap();
    working.apply_operations_checked(inverses).unwrap();
    assert_eq!(working, scene);
}

#[test]
fn finalize_template_is_not_invertible() {
    let scene = scene_with_ad();
    let result = scene
        .invert_operations(&[lumen_core::Operation::FinalizeTemplate {
            template_revision_id: "rev_1".into(),
        }])
        .expect("inversion check succeeds");
    assert!(result.is_none(), "finalization must not be invertible");
}

#[test]
fn insert_with_adopted_children_is_not_invertible() {
    let scene = scene_with_ad();
    let mut adopting = Node::new(NodeId::from("adopter"), NodeKind::Frame);
    adopting.children = vec![NodeId::from("headline")];
    let result = scene
        .invert_operations(&[lumen_core::Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_square")),
            index: 0,
            node: adopting,
        }])
        .expect("inversion check succeeds");
    assert!(
        result.is_none(),
        "insert that adopts pre-existing children must not be invertible"
    );
}

#[test]
fn scope_allows_declared_node_descendants_and_in_place_reorder() {
    let scene = scene_with_ad();

    // Modify within declared closure: hero is declared, headline is a child.
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("headline")),
        EditPatch::Node(NodeEditPatch {
            text: Some(TextEditPatch {
                content: FieldPatch::Set("In scope".to_owned()),
                ..TextEditPatch::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();
    let violations = lumen_core::batch_scope_violations(
        &scene,
        &batch.operations,
        &[EditTargetRef::Node(NodeId::from("hero"))],
    )
    .unwrap();
    assert!(violations.is_empty());

    // Same-parent reorder of a declared node is in scope even though the
    // structural parent (hero) is not declared.
    let reorder = build_move_after(&scene, NodeId::from("headline"), NodeId::from("cta")).unwrap();
    let violations = lumen_core::batch_scope_violations(
        &scene,
        &reorder.operations,
        &[EditTargetRef::Node(NodeId::from("headline"))],
    )
    .unwrap();
    assert!(violations.is_empty());

    // Clone under a declared anchor stays in scope: inserted nodes join the
    // closure when their parent is allowed.
    let clone = build_clone_subtree(
        &scene,
        CloneSubtreeRequest {
            source: NodeId::from("headline"),
            new_root_id: NodeId::from("headline_2"),
            placement: RelativePlacement::After {
                anchor: NodeId::from("headline"),
            },
            slot_policy: CloneSlotPolicy::Detach,
            computed_policy: ComputedClonePolicy::Clear,
        },
    )
    .unwrap();
    let violations = lumen_core::batch_scope_violations(
        &scene,
        &clone.operations,
        &[EditTargetRef::Node(NodeId::from("hero"))],
    )
    .unwrap();
    assert!(violations.is_empty());
}

#[test]
fn scope_rejects_undeclared_targets_fail_closed() {
    let scene = scene_with_ad();

    // Editing the body while only the headline is declared is a violation.
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("body")),
        EditPatch::Node(NodeEditPatch {
            text: Some(TextEditPatch {
                content: FieldPatch::Set("Out of scope".to_owned()),
                ..TextEditPatch::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();
    let violations = lumen_core::batch_scope_violations(
        &scene,
        &batch.operations,
        &[EditTargetRef::Node(NodeId::from("headline"))],
    )
    .unwrap();
    assert_eq!(violations.len(), 1);
    assert_eq!(
        violations[0].target,
        EditTargetRef::Node(NodeId::from("body"))
    );

    // Page edits require the page itself to be declared.
    let page_batch = build_modify_operations(
        &scene,
        EditTargetRef::Page(PageId::from("page_square")),
        EditPatch::Page(PageEditPatch {
            name: FieldPatch::Set("Renamed".to_owned()),
            ..PageEditPatch::default()
        }),
    )
    .unwrap();
    let violations = lumen_core::batch_scope_violations(
        &scene,
        &page_batch.operations,
        &[EditTargetRef::Node(NodeId::from("headline"))],
    )
    .unwrap();
    assert_eq!(violations.len(), 1);

    // Finalization is never a scoped repair.
    let violations = lumen_core::batch_scope_violations(
        &scene,
        &[lumen_core::Operation::FinalizeTemplate {
            template_revision_id: "rev_1".into(),
        }],
        &[EditTargetRef::Document],
    )
    .unwrap();
    assert_eq!(violations.len(), 1);

    // Declared targets must resolve.
    assert!(lumen_core::batch_scope_violations(
        &scene,
        &[],
        &[EditTargetRef::Node(NodeId::from("missing"))],
    )
    .is_err());
}

#[test]
fn scope_allows_slot_bindings_through_declared_nodes() {
    let scene = scene_with_ad();

    // Safe delete of a declared node clears its slot binding; the slot is in
    // scope because it binds the declared node.
    let batch = build_safe_delete(&scene, NodeId::from("headline")).unwrap();
    let violations = lumen_core::batch_scope_violations(
        &scene,
        &batch.operations,
        &[EditTargetRef::Node(NodeId::from("headline"))],
    )
    .unwrap();
    assert!(violations.is_empty());

    // Slot metadata edits without any declared node binding require the slot
    // itself to be declared.
    let slot_batch = build_modify_operations(
        &scene,
        EditTargetRef::SlotKey(SlotKey::from("campaign.headline")),
        EditPatch::Slot(lumen_core::SlotEditPatch {
            placeholder: OptionalFieldPatch::Set("New".to_owned()),
            ..lumen_core::SlotEditPatch::default()
        }),
    )
    .unwrap();
    let violations = lumen_core::batch_scope_violations(
        &scene,
        &slot_batch.operations,
        &[EditTargetRef::Node(NodeId::from("cta"))],
    )
    .unwrap();
    assert_eq!(violations.len(), 1);

    let violations = lumen_core::batch_scope_violations(
        &scene,
        &slot_batch.operations,
        &[EditTargetRef::SlotKey(SlotKey::from("campaign.headline"))],
    )
    .unwrap();
    assert!(violations.is_empty());
}

#[test]
fn replace_node_preserves_target_parent_index() {
    let mut scene = scene_with_ad();
    scene
        .apply_operation(lumen_core::Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_square")),
            index: 1,
            node: text_node("headline_replacement", "Replacement"),
        })
        .unwrap();

    let batch = build_replace_node(
        &scene,
        ReplaceNodeRequest {
            target: NodeId::from("headline"),
            replacement: NodeId::from("headline_replacement"),
            slot_policy: ReplaceSlotPolicy::PreserveCompatible,
        },
    )
    .unwrap();

    batch.apply_checked(&mut scene).unwrap();

    assert!(!scene.nodes.contains_key(&NodeId::from("headline")));
    assert_eq!(
        scene.nodes[&NodeId::from("hero")].children[0],
        NodeId::from("headline_replacement")
    );
    assert_eq!(
        scene
            .slot_by_key(&SlotKey::from("campaign.headline"))
            .unwrap()
            .bound_nodes,
        vec![NodeId::from("headline_replacement")]
    );
}

#[test]
fn page_delete_protects_last_page_and_keeps_slot_definitions() {
    let scene = scene_with_ad();

    // The fixture has one page: deletion is lifecycle-protected.
    let error =
        lumen_core::build_safe_delete_page(&scene, PageId::from("page_square")).unwrap_err();
    assert_eq!(error.kind.code(), "edit.lifecycle_protected");

    // With a second page the delete cascades nodes, unbinds the slot, and
    // keeps the slot definition so preflight can flag the gap.
    let mut scene = scene;
    scene
        .apply_operation(lumen_core::Operation::AddPage {
            page: Page {
                id: PageId::from("page_two"),
                name: "Two".to_owned(),
                size: PageSize {
                    width: 1080.0,
                    height: 1080.0,
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

    let batch = lumen_core::build_safe_delete_page(&scene, PageId::from("page_square")).unwrap();
    assert_batch_round_trip(&scene, &batch);

    let mut working = scene.clone();
    batch.apply_checked(&mut working).unwrap();
    assert!(!working.pages.contains_key(&PageId::from("page_square")));
    assert!(!working.nodes.contains_key(&NodeId::from("headline")));
    let slot = working
        .slot_by_key(&SlotKey::from("campaign.headline"))
        .expect("slot definition survives page delete");
    assert!(slot.bound_nodes.is_empty());
}

#[test]
fn slot_delete_unbinds_without_deleting_nodes() {
    let scene = scene_with_ad();
    let batch = lumen_core::build_safe_delete_slot(
        &scene,
        EditTargetRef::SlotKey(SlotKey::from("campaign.headline")),
    )
    .unwrap();
    assert_batch_round_trip(&scene, &batch);

    let mut working = scene.clone();
    batch.apply_checked(&mut working).unwrap();
    assert!(working
        .slot_by_key(&SlotKey::from("campaign.headline"))
        .is_none());
    assert!(working.nodes.contains_key(&NodeId::from("headline")));
}

#[test]
fn asset_lifecycle_archives_by_default_and_protects_referenced_hard_delete() {
    let scene = scene_with_ad();

    let archive = lumen_core::build_archive_asset(&scene, "asset_logo".into()).unwrap();
    assert_batch_round_trip(&scene, &archive);
    let mut working = scene.clone();
    archive.apply_checked(&mut working).unwrap();
    assert_eq!(
        working.assets[&lumen_core::AssetId::from("asset_logo")].status,
        AssetStatus::Archived
    );

    // asset_logo backs the logo image node: hard delete is protected.
    let error = lumen_core::build_hard_delete_asset(&scene, "asset_logo".into()).unwrap_err();
    assert_eq!(error.kind.code(), "edit.lifecycle_protected");

    // The unused alternate asset hard-deletes cleanly and round-trips.
    let hard = lumen_core::build_hard_delete_asset(&scene, "asset_logo_alt".into()).unwrap();
    assert_batch_round_trip(&scene, &hard);
}

#[test]
fn export_profile_delete_requires_a_surviving_profile() {
    let mut scene = scene_with_ad();
    scene.export_profiles.push(lumen_core::ExportProfile {
        name: "print_pdf".to_owned(),
        format: lumen_core::ExportFormat::Pdf,
        pdf_intent: Some(lumen_core::PdfIntent::Print),
        raster: None,
        include_bleed: true,
        embed_fonts: true,
    include_marks: false,
    imposition: None,
    proof: false,
    color: None,
    });

    // Only profile: protected.
    let error =
        lumen_core::build_delete_export_profile(&scene, "print_pdf".to_owned(), None).unwrap_err();
    assert_eq!(error.kind.code(), "edit.lifecycle_protected");

    scene.export_profiles.push(lumen_core::ExportProfile {
        name: "web_png".to_owned(),
        format: lumen_core::ExportFormat::Png,
        pdf_intent: None,
        raster: None,
        include_bleed: false,
        embed_fonts: false,
    include_marks: false,
    imposition: None,
    proof: false,
    color: None,
    });

    // Replacement must exist and differ.
    assert!(lumen_core::build_delete_export_profile(
        &scene,
        "print_pdf".to_owned(),
        Some("print_pdf".to_owned()),
    )
    .is_err());
    assert!(lumen_core::build_delete_export_profile(
        &scene,
        "print_pdf".to_owned(),
        Some("missing".to_owned()),
    )
    .is_err());

    let batch = lumen_core::build_delete_export_profile(
        &scene,
        "web_png".to_owned(),
        Some("print_pdf".to_owned()),
    )
    .unwrap();
    let mut working = scene.clone();
    batch.apply_checked(&mut working).unwrap();
    assert!(working.export_profile("web_png").is_none());
    assert!(working.export_profile("print_pdf").is_some());
}

#[test]
fn export_profile_patch_carries_the_print_fields() {
    // The sparse patch was frozen before the print track and silently
    // couldn't express include_marks/imposition/proof/color — the ops path
    // (agent, saved bulk profiles) could never persist a print setup.
    let mut scene = scene_with_ad();
    scene.export_profiles.push(lumen_core::ExportProfile {
        name: "print_pdf".to_owned(),
        format: lumen_core::ExportFormat::Pdf,
        pdf_intent: Some(lumen_core::PdfIntent::Print),
        raster: None,
        include_bleed: false,
        embed_fonts: true,
        include_marks: false,
        imposition: None,
        proof: false,
        color: None,
    });

    let patch: lumen_core::ExportProfileEditPatch = serde_json::from_value(serde_json::json!({
        "include_bleed": { "kind": "set", "value": true },
        "include_marks": { "kind": "set", "value": true },
        "imposition": { "kind": "set", "value": "booklet" },
        "proof": { "kind": "set", "value": true },
        "color": { "kind": "set", "value": "cmyk" }
    }))
    .expect("print-field patch parses from the wire format");

    let batch =
        lumen_core::build_export_profile_modify(&scene, "print_pdf".to_owned(), patch).unwrap();
    let mut working = scene.clone();
    batch.apply_checked(&mut working).unwrap();
    let merged = working.export_profile("print_pdf").unwrap();
    assert!(merged.include_bleed);
    assert!(merged.include_marks);
    assert_eq!(merged.imposition.as_deref(), Some("booklet"));
    assert!(merged.proof);
    assert_eq!(merged.color.as_deref(), Some("cmyk"));
    // Untouched fields survive the merge.
    assert_eq!(merged.format, lumen_core::ExportFormat::Pdf);
    assert!(merged.embed_fonts);

    // Clearing works for the optional print fields.
    let clear: lumen_core::ExportProfileEditPatch = serde_json::from_value(serde_json::json!({
        "imposition": { "kind": "clear" },
        "color": { "kind": "clear" },
        "proof": { "kind": "set", "value": false }
    }))
    .unwrap();
    let batch =
        lumen_core::build_export_profile_modify(&working, "print_pdf".to_owned(), clear).unwrap();
    batch.apply_checked(&mut working).unwrap();
    let cleared = working.export_profile("print_pdf").unwrap();
    assert_eq!(cleared.imposition, None);
    assert_eq!(cleared.color, None);
    assert!(!cleared.proof);
    assert!(cleared.include_marks, "unrelated print field survives");
}

#[test]
fn export_profile_patch_stays_complete_against_the_profile_shape() {
    // Drift killer: this is the THIRD hand-mirrored copy of ExportProfile's
    // shape to go stale (patch here, the API normalize whitelist twice). If
    // ExportProfile grows a field the patch can't express, this fails at
    // the moment of the change, not months later in an audit.
    let profile = lumen_core::ExportProfile {
        name: "shape_probe".to_owned(),
        format: lumen_core::ExportFormat::Pdf,
        pdf_intent: Some(lumen_core::PdfIntent::Print),
        raster: Some(lumen_core::RasterScale {
            scale: 2.0,
            dpi: Some(300),
        }),
        include_bleed: true,
        embed_fonts: true,
        include_marks: true,
        imposition: Some("booklet".to_owned()),
        proof: true,
        color: Some("cmyk".to_owned()),
    };
    let profile_keys: std::collections::BTreeSet<String> = serde_json::to_value(&profile)
        .unwrap()
        .as_object()
        .unwrap()
        .keys()
        .cloned()
        .collect();

    let patch_keys: std::collections::BTreeSet<String> =
        serde_json::to_value(lumen_core::ExportProfileEditPatch::default())
            .unwrap()
            .as_object()
            .unwrap()
            .keys()
            .cloned()
            .collect();

    // `name` is the patch's addressing key (#export:name), never patched.
    let expected: std::collections::BTreeSet<String> = profile_keys
        .into_iter()
        .filter(|key| key != "name")
        .collect();
    assert_eq!(
        patch_keys, expected,
        "ExportProfileEditPatch no longer mirrors ExportProfile — add the missing field(s) to the patch, the merge in build_export_profile_modify, and the API normalize whitelist"
    );
}

// --- Effects Contract V0, slice X2: per-entry stack edits ---

fn shadow(id: &str, blur: f64) -> Effect {
    Effect {
        id: EffectId::from(id),
        kind: EffectKind::DropShadow {
            color: Color::Hex {
                value: "#000000".to_owned(),
            },
            opacity: 0.18,
            x: 0.0,
            y: 8.0,
            blur,
            spread: 0.0,
            color_token: None,
        },
    }
}

fn scene_with_styled_hero() -> Scene {
    let mut scene = scene_with_ad();
    let hero = scene.nodes.get_mut(&NodeId::from("hero")).unwrap();
    hero.fills = vec![
        solid_fill("fill_a", "#ffffff"),
        solid_fill("fill_b", "#f5f1e9"),
    ];
    hero.strokes = vec![Stroke::solid(
        PaintId::from("stroke_a"),
        Paint::Solid {
            color: Color::Hex {
                value: "#111827".to_owned(),
            },
        },
        1.0,
    )];
    hero.effects = vec![shadow("shadow_a", 8.0), shadow("shadow_b", 24.0)];
    scene
}

#[test]
fn effect_entry_set_preserves_unrelated_entries_and_round_trips() {
    let scene = scene_with_styled_hero();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("hero")),
        EditPatch::Node(NodeEditPatch {
            effect_edits: vec![StackEntryEdit::Set {
                id: EffectId::from("shadow_b"),
                value: shadow("shadow_b", 40.0),
            }],
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();

    assert_batch_round_trip(&scene, &batch);

    let mut working = scene.clone();
    batch.apply_checked(&mut working).unwrap();
    let hero = &working.nodes[&NodeId::from("hero")];
    assert_eq!(
        hero.effects[0],
        shadow("shadow_a", 8.0),
        "unrelated effect entries must be preserved"
    );
    assert_eq!(hero.effects[1], shadow("shadow_b", 40.0));
    assert_eq!(
        hero.fills,
        vec![
            solid_fill("fill_a", "#ffffff"),
            solid_fill("fill_b", "#f5f1e9")
        ],
        "effect edits must not touch fills"
    );
}

#[test]
fn stack_add_remove_reorder_compose_in_order() {
    let scene = scene_with_styled_hero();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("hero")),
        EditPatch::Node(NodeEditPatch {
            fill_edits: vec![
                StackEntryEdit::Add {
                    entry: solid_fill("fill_c", "#256c70"),
                    index: Some(0),
                },
                StackEntryEdit::Remove {
                    id: PaintId::from("fill_b"),
                },
                StackEntryEdit::Reorder {
                    id: PaintId::from("fill_a"),
                    index: 0,
                },
            ],
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();

    assert_batch_round_trip(&scene, &batch);

    let mut working = scene.clone();
    batch.apply_checked(&mut working).unwrap();
    assert_eq!(
        working.nodes[&NodeId::from("hero")].fills,
        vec![
            solid_fill("fill_a", "#ffffff"),
            solid_fill("fill_c", "#256c70")
        ]
    );
}

#[test]
fn stroke_entry_set_updates_advanced_fields_and_round_trips() {
    let scene = scene_with_styled_hero();
    let next_stroke = Stroke {
        dash: Some(vec![6.0, 4.0]),
        cap: StrokeCap::Round,
        ..Stroke::solid(
            PaintId::from("stroke_a"),
            Paint::Solid {
                color: Color::Hex {
                    value: "#111827".to_owned(),
                },
            },
            2.0,
        )
    };
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("hero")),
        EditPatch::Node(NodeEditPatch {
            stroke_edits: vec![StackEntryEdit::Set {
                id: PaintId::from("stroke_a"),
                value: next_stroke.clone(),
            }],
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();

    assert_batch_round_trip(&scene, &batch);

    let mut working = scene.clone();
    batch.apply_checked(&mut working).unwrap();
    assert_eq!(
        working.nodes[&NodeId::from("hero")].strokes,
        vec![next_stroke]
    );
}

#[test]
fn stack_entry_edits_fail_closed_on_bad_addressing() {
    let scene = scene_with_styled_hero();

    let missing = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("hero")),
        EditPatch::Node(NodeEditPatch {
            effect_edits: vec![StackEntryEdit::Remove {
                id: EffectId::from("missing"),
            }],
            ..NodeEditPatch::default()
        }),
    )
    .unwrap_err();
    assert_eq!(missing.kind.code(), "edit.target_not_found");

    let duplicate = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("hero")),
        EditPatch::Node(NodeEditPatch {
            effect_edits: vec![StackEntryEdit::Add {
                entry: shadow("shadow_a", 4.0),
                index: None,
            }],
            ..NodeEditPatch::default()
        }),
    )
    .unwrap_err();
    assert_eq!(duplicate.kind.code(), "edit.id_collision");

    let out_of_bounds = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("hero")),
        EditPatch::Node(NodeEditPatch {
            effect_edits: vec![StackEntryEdit::Reorder {
                id: EffectId::from("shadow_a"),
                index: 9,
            }],
            ..NodeEditPatch::default()
        }),
    )
    .unwrap_err();
    assert_eq!(out_of_bounds.kind.code(), "edit.anchor_not_found");

    let rename_collision = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("hero")),
        EditPatch::Node(NodeEditPatch {
            effect_edits: vec![StackEntryEdit::Set {
                id: EffectId::from("shadow_a"),
                value: shadow("shadow_b", 4.0),
            }],
            ..NodeEditPatch::default()
        }),
    )
    .unwrap_err();
    assert_eq!(rename_collision.kind.code(), "edit.id_collision");
}

#[test]
fn entry_edits_apply_on_top_of_whole_stack_patch() {
    let scene = scene_with_styled_hero();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("hero")),
        EditPatch::Node(NodeEditPatch {
            effects: FieldPatch::Set(vec![shadow("shadow_new", 12.0)]),
            effect_edits: vec![StackEntryEdit::Add {
                entry: shadow("shadow_extra", 2.0),
                index: None,
            }],
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();

    assert_batch_round_trip(&scene, &batch);

    let mut working = scene.clone();
    batch.apply_checked(&mut working).unwrap();
    assert_eq!(
        working.nodes[&NodeId::from("hero")].effects,
        vec![shadow("shadow_new", 12.0), shadow("shadow_extra", 2.0)]
    );
}

#[test]
fn effect_entry_edits_are_scope_checked_as_node_edits() {
    let scene = scene_with_styled_hero();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("hero")),
        EditPatch::Node(NodeEditPatch {
            effect_edits: vec![StackEntryEdit::Remove {
                id: EffectId::from("shadow_a"),
            }],
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();

    assert!(matches!(
        batch.operations.as_slice(),
        [lumen_core::Operation::UpdateNode { .. }]
    ));

    let in_scope = lumen_core::batch_scope_violations(
        &scene,
        &batch.operations,
        &[EditTargetRef::Node(NodeId::from("hero"))],
    )
    .unwrap();
    assert!(in_scope.is_empty());

    let out_of_scope = lumen_core::batch_scope_violations(
        &scene,
        &batch.operations,
        &[EditTargetRef::Node(NodeId::from("headline"))],
    )
    .unwrap();
    assert_eq!(out_of_scope.len(), 1);
    assert_eq!(
        out_of_scope[0].target,
        EditTargetRef::Node(NodeId::from("hero"))
    );
}

#[test]
fn stack_entry_edit_wire_format_parses_snake_case() {
    let patch: NodeEditPatch = serde_json::from_value(serde_json::json!({
        "effect_edits": [
            { "kind": "add", "entry": {
                "id": "shadow_soft",
                "kind": {
                    "kind": "drop_shadow",
                    "color": { "kind": "hex", "value": "#000000" },
                    "opacity": 0.18, "x": 0.0, "y": 8.0, "blur": 24.0, "spread": 0.0
                }
            }},
            { "kind": "remove", "id": "shadow_old" },
            { "kind": "reorder", "id": "shadow_soft", "index": 0 },
            { "kind": "set", "id": "shadow_soft", "value": {
                "id": "shadow_soft",
                "kind": {
                    "kind": "drop_shadow",
                    "color": { "kind": "hex", "value": "#000000" },
                    "opacity": 0.3, "x": 0.0, "y": 8.0, "blur": 24.0, "spread": 0.0
                }
            }}
        ]
    }))
    .expect("wire format parses");
    assert_eq!(patch.effect_edits.len(), 4);

    // Pre-effects sparse node patches must still parse.
    let legacy: NodeEditPatch = serde_json::from_value(serde_json::json!({
        "text": { "content": { "kind": "set", "value": "Hi" } }
    }))
    .expect("legacy patch parses");
    assert!(legacy.effect_edits.is_empty());
    assert!(legacy.effects.is_unchanged());
}
