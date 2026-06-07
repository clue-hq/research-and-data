use lumen_core::validation::validate_scene;
use lumen_core::{
    ContentType, DiagnosticSeverity, DocumentId, DocumentPatch, ExportFormat, ExportProfile,
    ExportPurpose, ExportRequest, FieldPatch, Node, NodeId, NodeKind, NodePatch, Operation,
    OptionalFieldPatch, Orientation, Page, PageId, PagePreset, PageSize, ParentRef, PdfIntent,
    Scene, SizeSpec, Slot, SlotId, SlotKey, SlotScope, TextAlign, TextNode, Unit,
};

fn a4_page() -> Page {
    Page {
        id: PageId::from("page_a4"),
        name: "A4 Letter".to_owned(),
        size: PageSize {
            width: 210.0,
            height: 297.0,
            unit: Unit::Mm,
            preset: Some(PagePreset::A4),
            orientation: Orientation::Portrait,
        },
        children: Vec::new(),
        bleed: None,
        safe_area: None,
        background: Vec::new(),
    }
}

fn print_pdf_profile() -> ExportProfile {
    ExportProfile {
        name: "print_pdf".to_owned(),
        format: ExportFormat::Pdf,
        pdf_intent: Some(PdfIntent::Print),
        raster: None,
        include_bleed: true,
        embed_fonts: true,
    }
}

fn text_node(id: &str, content: &str) -> Node {
    let mut node = Node::new(
        NodeId::from(id),
        NodeKind::Text(TextNode {
            content: content.to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 18.0,
            font_weight: 600,
            align: TextAlign::Left,
            style_token: None,
        }),
    );
    node.size = SizeSpec::fixed(160.0, 28.0);
    node
}

fn valid_scene_with_text_slot() -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_demo"), "Demo");
    scene
        .apply_operation(Operation::AddPage { page: a4_page() })
        .unwrap();

    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_a4")),
            index: 0,
            node: text_node("node_contact_name", "Dr. Priya Sharma"),
        })
        .unwrap();

    let mut slot = Slot::text_short(
        SlotId::from("slot_contact_name"),
        SlotKey::from("contact.full_name"),
        "Contact full name",
    );
    slot.placeholder = Some("Dr. Priya Sharma".to_owned());
    slot.validation.samples = vec!["Dr. Maximilian Alexander Whitmore".to_owned()];

    scene
        .apply_operation(Operation::UpsertSlot { slot })
        .unwrap();
    scene
        .apply_operation(Operation::BindNodeToSlot {
            slot_id: SlotId::from("slot_contact_name"),
            node_id: NodeId::from("node_contact_name"),
        })
        .unwrap();
    scene
        .apply_operation(Operation::UpsertExportProfile {
            profile: print_pdf_profile(),
        })
        .unwrap();
    scene
}

#[test]
fn scene_round_trips_through_json() {
    let mut scene = Scene::new(DocumentId::from("doc_demo"), "Demo");
    scene
        .apply_operation(Operation::AddPage { page: a4_page() })
        .unwrap();

    let json = serde_json::to_string_pretty(&scene).unwrap();
    let decoded: Scene = serde_json::from_str(&json).unwrap();

    assert_eq!(decoded.meta.id, DocumentId::from("doc_demo"));
    assert!(decoded.pages.contains_key(&PageId::from("page_a4")));
}

#[test]
fn minimal_scene_fixture_is_valid_contract_json() {
    let fixture = include_str!("../fixtures/minimal_scene.json");
    let scene: Scene = serde_json::from_str(fixture).unwrap();

    let diagnostics = validate_scene(&scene);
    assert!(
        diagnostics
            .iter()
            .all(|diag| diag.severity != DiagnosticSeverity::Error),
        "{diagnostics:#?}"
    );
}

#[test]
fn inserts_node_and_binds_slot() {
    let scene = valid_scene_with_text_slot();
    let diagnostics = validate_scene(&scene);
    assert!(
        diagnostics
            .iter()
            .all(|diag| diag.severity != DiagnosticSeverity::Error),
        "{diagnostics:#?}"
    );
}

#[test]
fn update_operations_keep_edits_in_operation_log() {
    let mut scene = valid_scene_with_text_slot();

    scene
        .apply_operation(Operation::UpdateDocument {
            patch: DocumentPatch {
                title: FieldPatch::Set("Updated letter".to_owned()),
                artifact_type: OptionalFieldPatch::Set("letter".to_owned()),
                ..DocumentPatch::default()
            },
        })
        .unwrap();

    scene
        .apply_operation(Operation::UpdateNode {
            node_id: NodeId::from("node_contact_name"),
            patch: NodePatch {
                kind: FieldPatch::Set(NodeKind::Text(TextNode {
                    content: "Dr. James Wilson".to_owned(),
                    font_family: "Inter".to_owned(),
                    font_size: 18.0,
                    font_weight: 600,
                    align: TextAlign::Left,
                    style_token: None,
                })),
                ..NodePatch::default()
            },
        })
        .unwrap();

    assert_eq!(scene.meta.title, "Updated letter");
    let node = scene.nodes.get(&NodeId::from("node_contact_name")).unwrap();
    match &node.kind {
        NodeKind::Text(text) => assert_eq!(text.content, "Dr. James Wilson"),
        other => panic!("expected text node, got {other:?}"),
    }
}

#[test]
fn old_update_node_operations_without_opacity_token_still_deserialize() {
    let json = r#"
    {
      "kind": "update_node",
      "node_id": "node_contact_name",
      "patch": {
        "name": { "kind": "unchanged" },
        "kind": { "kind": "unchanged" },
        "transform": { "kind": "unchanged" },
        "size": { "kind": "unchanged" },
        "fills": { "kind": "unchanged" },
        "strokes": { "kind": "unchanged" },
        "corner": { "kind": "unchanged" },
        "opacity": { "kind": "unchanged" },
        "clip": { "kind": "unchanged" },
        "layout": { "kind": "unchanged" },
        "computed": { "kind": "unchanged" },
        "locked": { "kind": "unchanged" }
      }
    }
    "#;

    let operation: Operation = serde_json::from_str(json).unwrap();

    let Operation::UpdateNode { patch, .. } = operation else {
        panic!("expected update_node operation");
    };
    assert!(matches!(patch.opacity_token, OptionalFieldPatch::Unchanged));
}

#[test]
fn export_request_contract_carries_profile_pages_and_purpose() {
    let request = ExportRequest {
        profile: print_pdf_profile(),
        page_ids: vec![PageId::from("page_a4")],
        purpose: ExportPurpose::AgentCritique,
    };

    assert_eq!(request.profile.format, ExportFormat::Pdf);
    assert_eq!(request.page_ids, vec![PageId::from("page_a4")]);
}

#[test]
fn finalization_requires_valid_scene_and_export_profile_then_blocks_mutation() {
    let mut scene = valid_scene_with_text_slot();

    scene
        .apply_operation(Operation::FinalizeTemplate {
            template_revision_id: lumen_core::TemplateRevisionId::from("template_rev_1"),
        })
        .unwrap();

    let error = scene
        .apply_operation(Operation::UpdateDocument {
            patch: DocumentPatch {
                title: FieldPatch::Set("Illegal mutation".to_owned()),
                ..DocumentPatch::default()
            },
        })
        .unwrap_err();

    assert_eq!(error.code, "op.finalized_scene");
}

#[test]
fn finalization_rejects_missing_export_profile() {
    let mut scene = valid_scene_with_text_slot();
    scene.export_profiles.clear();

    let error = scene
        .apply_operation(Operation::FinalizeTemplate {
            template_revision_id: lumen_core::TemplateRevisionId::from("template_rev_1"),
        })
        .unwrap_err();

    assert_eq!(error.code, "op.finalize_missing_export_profile");
}

#[test]
fn rejects_children_under_leaf_nodes() {
    let mut scene = Scene::new(DocumentId::from("doc_demo"), "Demo");
    scene
        .apply_operation(Operation::AddPage { page: a4_page() })
        .unwrap();

    let rect = Node::new(NodeId::from("node_rect"), NodeKind::Rect);
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_a4")),
            index: 0,
            node: rect,
        })
        .unwrap();

    let child = Node::new(NodeId::from("node_child"), NodeKind::Rect);
    let error = scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Node(NodeId::from("node_rect")),
            index: 0,
            node: child,
        })
        .unwrap_err();

    assert_eq!(error.code, "op.leaf_parent");
}

#[test]
fn rejects_leaf_node_payloads_with_children() {
    let mut scene = Scene::new(DocumentId::from("doc_demo"), "Demo");
    scene
        .apply_operation(Operation::AddPage { page: a4_page() })
        .unwrap();

    scene.nodes.insert(
        NodeId::from("node_child"),
        Node::new(NodeId::from("node_child"), NodeKind::Rect),
    );

    let mut invalid_payload = Node::new(NodeId::from("node_parent"), NodeKind::Rect);
    invalid_payload.children.push(NodeId::from("node_child"));

    let error = scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_a4")),
            index: 0,
            node: invalid_payload,
        })
        .unwrap_err();

    assert_eq!(error.code, "op.leaf_parent");
    assert!(!scene.nodes.contains_key(&NodeId::from("node_parent")));
}

#[test]
fn failed_leaf_update_does_not_mutate_existing_node() {
    let mut scene = Scene::new(DocumentId::from("doc_demo"), "Demo");
    scene
        .apply_operation(Operation::AddPage { page: a4_page() })
        .unwrap();

    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_a4")),
            index: 0,
            node: Node::new(NodeId::from("node_frame"), NodeKind::Frame),
        })
        .unwrap();
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Node(NodeId::from("node_frame")),
            index: 0,
            node: Node::new(NodeId::from("node_child"), NodeKind::Rect),
        })
        .unwrap();

    let error = scene
        .apply_operation(Operation::UpdateNode {
            node_id: NodeId::from("node_frame"),
            patch: NodePatch {
                kind: FieldPatch::Set(NodeKind::Rect),
                ..NodePatch::default()
            },
        })
        .unwrap_err();

    assert_eq!(error.code, "op.leaf_parent");
    assert!(matches!(
        scene.nodes[&NodeId::from("node_frame")].kind,
        NodeKind::Frame
    ));
}

#[test]
fn moving_within_same_parent_to_end_does_not_panic() {
    let mut scene = Scene::new(DocumentId::from("doc_demo"), "Demo");
    scene
        .apply_operation(Operation::AddPage { page: a4_page() })
        .unwrap();

    for id in ["node_a", "node_b", "node_c"] {
        scene
            .apply_operation(Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_a4")),
                index: scene.pages[&PageId::from("page_a4")].children.len(),
                node: Node::new(NodeId::from(id), NodeKind::Rect),
            })
            .unwrap();
    }

    scene
        .apply_operation(Operation::MoveNode {
            node_id: NodeId::from("node_a"),
            new_parent: ParentRef::Page(PageId::from("page_a4")),
            index: 3,
        })
        .unwrap();

    assert_eq!(
        scene.pages[&PageId::from("page_a4")].children,
        vec![
            NodeId::from("node_b"),
            NodeId::from("node_c"),
            NodeId::from("node_a")
        ]
    );
}

#[test]
fn duplicate_slot_keys_are_validation_errors() {
    let mut scene = Scene::new(DocumentId::from("doc_demo"), "Demo");
    scene
        .apply_operation(Operation::AddPage { page: a4_page() })
        .unwrap();

    let mut first = Slot::text_short(
        SlotId::from("slot_contact_name_a"),
        SlotKey::from("contact.full_name"),
        "Contact full name",
    );
    first.placeholder = Some("Dr. Priya Sharma".to_owned());
    first.validation.max_length = Some(80);

    let mut second = Slot::text_short(
        SlotId::from("slot_contact_name_b"),
        SlotKey::from("contact.full_name"),
        "Duplicate contact full name",
    );
    second.placeholder = Some("Dr. James Wilson".to_owned());
    second.validation.max_length = Some(80);

    scene
        .apply_operation(Operation::UpsertSlot { slot: first })
        .unwrap();
    scene
        .apply_operation(Operation::UpsertSlot { slot: second })
        .unwrap();

    let diagnostics = validate_scene(&scene);
    assert!(diagnostics.iter().any(|diag| diag.code == "LUMV0500"));
}

#[test]
fn repeater_metadata_is_scaffolded_but_validated() {
    let mut scene = Scene::new(DocumentId::from("doc_demo"), "Demo");
    scene
        .apply_operation(Operation::AddPage { page: a4_page() })
        .unwrap();

    let mut slot = Slot::text_short(
        SlotId::from("slot_insights"),
        SlotKey::from("research.key_insights"),
        "Key insights",
    );
    slot.content_type = ContentType::TextShort;
    slot.repeater = Some(lumen_core::RepeaterRule {
        template_node_id: NodeId::from("missing_template"),
        item_slot_key: SlotKey::from("research.key_insights.item"),
        min_items: 1,
        max_items: Some(3),
        reflow: lumen_core::ReflowPolicy::Stack,
    });
    slot.placeholder = Some("Insight".to_owned());
    slot.validation.max_length = Some(120);

    scene
        .apply_operation(Operation::UpsertSlot { slot })
        .unwrap();

    let diagnostics = validate_scene(&scene);
    assert!(diagnostics.iter().any(|diag| diag.code == "LUMV0505"));
    assert!(diagnostics.iter().any(|diag| diag.code == "LUMV0506"));
}

#[test]
fn validation_rejects_map_key_embedded_id_mismatch() {
    let mut scene = valid_scene_with_text_slot();
    let mut node = scene
        .nodes
        .remove(&NodeId::from("node_contact_name"))
        .unwrap();
    node.id = NodeId::from("node_other");
    scene.nodes.insert(NodeId::from("node_contact_name"), node);

    let diagnostics = validate_scene(&scene);
    assert!(diagnostics.iter().any(|diag| diag.code == "LUMV0111"));
}

#[test]
fn validation_rejects_multiple_parents_and_cycles() {
    let mut scene = Scene::new(DocumentId::from("doc_demo"), "Demo");
    scene
        .apply_operation(Operation::AddPage { page: a4_page() })
        .unwrap();

    let mut frame_a = Node::new(NodeId::from("frame_a"), NodeKind::Frame);
    frame_a.children.push(NodeId::from("frame_b"));
    let mut frame_b = Node::new(NodeId::from("frame_b"), NodeKind::Frame);
    frame_b.children.push(NodeId::from("frame_a"));

    scene.nodes.insert(NodeId::from("frame_a"), frame_a);
    scene.nodes.insert(NodeId::from("frame_b"), frame_b);
    scene
        .pages
        .get_mut(&PageId::from("page_a4"))
        .unwrap()
        .children = vec![NodeId::from("frame_a"), NodeId::from("frame_b")];

    let diagnostics = validate_scene(&scene);
    assert!(diagnostics.iter().any(|diag| diag.code == "LUMV0401"));
    assert!(diagnostics.iter().any(|diag| diag.code == "LUMV0403"));
}

#[test]
fn validation_rejects_missing_slot_scope_targets() {
    let mut scene = valid_scene_with_text_slot();
    let slot = scene
        .slots
        .get_mut(&SlotId::from("slot_contact_name"))
        .unwrap();
    slot.scope = SlotScope::Page(PageId::from("missing_page"));

    let diagnostics = validate_scene(&scene);
    assert!(diagnostics.iter().any(|diag| diag.code == "LUMV0510"));
}
