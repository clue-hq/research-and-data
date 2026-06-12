use lumen_core::{
    build_clone_subtree, build_modify_operations, build_move_after, build_move_before,
    build_replace_node, build_safe_delete, resolve_edit_target, AssetKind, AssetMediaMetadata,
    AssetPlacement, AssetProvenance, AssetRecord, AssetSource, AssetStatus, CloneSlotPolicy,
    CloneSubtreeRequest, ComputedClonePolicy, Dimension, DocumentId, EditPatch, EditTargetRef,
    FieldPatch, ImageNode, Node, NodeEditPatch, NodeId, NodeKind, OptionalFieldPatch, Orientation,
    Page, PageEditPatch, PageId, PagePreset, PageSize, ParentRef, RelativePlacement,
    ReplaceNodeRequest, ReplaceSlotPolicy, Scene, SizeSpec, Slot, SlotId, SlotKey, TextAlign,
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
