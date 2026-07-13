use lumen_core::{
    ContentType, DiagnosticSeverity, DocumentId, DocumentPatch, ExportFormat, ExportProfile,
    FieldPatch, Node, NodeId, NodeKind, Operation, OptionalFieldPatch, Orientation, Page, PageId,
    PagePreset, PageSize, ParentRef, PdfIntent, ReflowPolicy, RepeaterRule, Scene, SizeSpec, Slot,
    SlotId, SlotKey, TextAlign, TextNode, Unit,
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
            source: None,
            output: None,
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
    include_marks: false,
    imposition: None,
    proof: false,
    color: None,
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
            ..TextNode::default()
        }),
    );
    node.size = SizeSpec::fixed(160.0, 28.0);
    node
}

fn scene_with_page() -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_demo"), "Demo");
    scene
        .apply_operation(Operation::AddPage { page: a4_page() })
        .unwrap();
    scene
}

fn scene_with_nested_slot() -> Scene {
    let mut scene = scene_with_page();

    scene
        .apply_operations([
            Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_a4")),
                index: 0,
                node: Node::new(NodeId::from("node_frame"), NodeKind::Frame),
            },
            Operation::InsertNode {
                parent: ParentRef::Node(NodeId::from("node_frame")),
                index: 0,
                node: text_node("node_contact_name", "Dr. Priya Sharma"),
            },
        ])
        .unwrap();

    let mut slot = Slot::text_short(
        SlotId::from("slot_contact_name"),
        SlotKey::from("contact.full_name"),
        "Contact full name",
    );
    slot.placeholder = Some("Dr. Priya Sharma".to_owned());
    slot.validation.max_length = Some(80);

    scene
        .apply_operations([
            Operation::UpsertSlot { slot },
            Operation::BindNodeToSlot {
                slot_id: SlotId::from("slot_contact_name"),
                node_id: NodeId::from("node_contact_name"),
            },
            Operation::UpsertExportProfile {
                profile: print_pdf_profile(),
            },
        ])
        .unwrap();

    scene
}

#[test]
fn operation_batches_are_atomic_on_failure() {
    let mut scene = scene_with_page();

    let error = scene
        .apply_operations([
            Operation::UpdateDocument {
                patch: DocumentPatch {
                    title: FieldPatch::Set("Changed before failure".to_owned()),
                    artifact_type: OptionalFieldPatch::Set("letter".to_owned()),
                    ..DocumentPatch::default()
                },
            },
            Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("missing_page")),
                index: 0,
                node: Node::new(NodeId::from("node_orphan"), NodeKind::Rect),
            },
        ])
        .unwrap_err();

    assert_eq!(error.code, "op.page_missing");
    assert_eq!(scene.meta.title, "Demo");
    assert!(scene.meta.artifact_type.is_none());
    assert!(!scene.nodes.contains_key(&NodeId::from("node_orphan")));
}

#[test]
fn checked_apply_rejects_invalid_scene_without_commit() {
    let mut scene = scene_with_page();
    let mut slot = Slot::text_short(
        SlotId::from("slot_insights"),
        SlotKey::from("research.key_insights"),
        "Key insights",
    );
    slot.content_type = ContentType::RepeaterGroup;
    slot.repeater = Some(RepeaterRule {
        template_node_id: NodeId::from("missing_template"),
        item_slot_key: SlotKey::from("research.key_insights.item"),
        min_items: 1,
        max_items: Some(3),
        reflow: ReflowPolicy::Stack,
    });

    let error = scene
        .apply_operation_checked(Operation::UpsertSlot { slot })
        .unwrap_err();

    assert_eq!(error.code, "op.validation_failed");
    assert!(error
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMV0506"));
    assert!(!scene.slots.contains_key(&SlotId::from("slot_insights")));
}

#[test]
fn checked_apply_commits_valid_scene_and_returns_warnings() {
    let mut scene = scene_with_page();
    let slot = Slot::text_short(
        SlotId::from("slot_contact_name"),
        SlotKey::from("contact.full_name"),
        "Contact full name",
    );

    let report = scene
        .apply_operation_checked(Operation::UpsertSlot { slot })
        .unwrap();

    assert_eq!(report.applied_operations, 1);
    assert!(report
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == DiagnosticSeverity::Warning));
    assert!(scene.slots.contains_key(&SlotId::from("slot_contact_name")));
}

#[test]
fn query_helpers_report_tree_slots_and_exports() {
    let scene = scene_with_nested_slot();

    assert!(scene.page(&PageId::from("page_a4")).is_some());
    assert!(scene.node(&NodeId::from("node_frame")).is_some());
    assert!(scene.slot(&SlotId::from("slot_contact_name")).is_some());
    assert!(scene.export_profile("print_pdf").is_some());
    assert_eq!(
        scene.parent_of(&NodeId::from("node_frame")),
        Some(ParentRef::Page(PageId::from("page_a4")))
    );
    assert_eq!(
        scene.parent_of(&NodeId::from("node_contact_name")),
        Some(ParentRef::Node(NodeId::from("node_frame")))
    );
    assert_eq!(
        scene.descendants_of(&NodeId::from("node_frame")),
        vec![NodeId::from("node_contact_name")]
    );
    assert_eq!(
        scene
            .slot_by_key(&SlotKey::from("contact.full_name"))
            .unwrap()
            .id,
        SlotId::from("slot_contact_name")
    );
    assert_eq!(
        scene.slots_for_node(&NodeId::from("node_contact_name"))[0].id,
        SlotId::from("slot_contact_name")
    );
    assert_eq!(
        scene.bound_nodes_for_slot(&SlotId::from("slot_contact_name"))[0].id,
        NodeId::from("node_contact_name")
    );
}

#[test]
fn canonical_snapshot_round_trips_deterministically() {
    let scene = scene_with_nested_slot();

    let first = scene.to_canonical_json().unwrap();
    let decoded = Scene::from_json(&first).unwrap();
    let second = decoded.to_canonical_json().unwrap();

    assert_eq!(first, second);
}

#[test]
fn remove_node_cleans_descendants_and_slot_bindings() {
    let mut scene = scene_with_nested_slot();

    scene
        .apply_operation(Operation::RemoveNode {
            node_id: NodeId::from("node_frame"),
        })
        .unwrap();

    assert!(!scene.nodes.contains_key(&NodeId::from("node_frame")));
    assert!(!scene.nodes.contains_key(&NodeId::from("node_contact_name")));
    assert!(scene.slots[&SlotId::from("slot_contact_name")]
        .bound_nodes
        .is_empty());
}
