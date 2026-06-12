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
