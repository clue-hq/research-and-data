//! Token honesty on raw text edits: a raw typography edit must detach the
//! token that would otherwise re-resolve over it (export preflight, brand
//! apply) and silently clobber the human's change. Covers both writers —
//! the ops path (`UpdateNode` kind replace, what the editor emits) and the
//! structured-edit path (`TextEditPatch`, what the agent's DSL emits) — plus
//! the inverse-op roundtrip that restores bindings on undo.

use lumen_core::{
    build_modify_operations, DocumentId, EditPatch, EditTargetRef, FieldPatch, Node, NodeEditPatch,
    NodeId, NodeKind, NodePatch, Operation, OptionalFieldPatch, Orientation, Page, PageId,
    PagePreset, PageSize, ParentRef, Scene, SizeSpec, TextAlign, TextEditPatch, TextNode, Unit,
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

fn tokened_headline() -> Node {
    let mut node = Node::new(
        NodeId::from("headline"),
        NodeKind::Text(TextNode {
            content: "Healthcare paperwork".to_owned(),
            font_family: "DM Serif Display".to_owned(),
            font_size: 64.0,
            font_weight: 400,
            align: TextAlign::Left,
            line_height: 1.1,
            letter_spacing: -0.5,
            style_token: Some("$type.h1".to_owned()),
            font_size_token: Some("$type.size.5xl".to_owned()),
            line_height_token: Some("$type.leading.tight".to_owned()),
            letter_spacing_token: Some("$type.tracking.tight".to_owned()),
            ..TextNode::default()
        }),
    );
    node.size = SizeSpec::fixed(900.0, 160.0);
    node
}

fn scene_with_tokened_headline() -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_tokens"), "Token honesty");
    scene
        .apply_operations([
            Operation::AddPage {
                page: square_page(),
            },
            Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_square")),
                index: 0,
                node: tokened_headline(),
            },
        ])
        .unwrap();
    scene
}

fn headline_text(scene: &Scene) -> &TextNode {
    let NodeKind::Text(text) = &scene.nodes[&NodeId::from("headline")].kind else {
        panic!("expected text node");
    };
    text
}

/// Mirrors the editor's `updateTextNode` builder: spread the whole current
/// kind (stale tokens included) with a few raw fields overridden.
fn kind_replace(scene: &Scene, mutate: impl FnOnce(&mut TextNode)) -> Operation {
    let mut next = headline_text(scene).clone();
    mutate(&mut next);
    Operation::UpdateNode {
        node_id: NodeId::from("headline"),
        patch: NodePatch {
            kind: FieldPatch::Set(NodeKind::Text(next)),
            ..NodePatch::default()
        },
    }
}

#[test]
fn ops_raw_size_edit_clears_size_and_style_tokens() {
    let mut scene = scene_with_tokened_headline();
    scene
        .apply_operation(kind_replace(&scene, |text| text.font_size = 44.0))
        .unwrap();

    let text = headline_text(&scene);
    assert_eq!(text.font_size, 44.0);
    assert_eq!(text.font_size_token, None);
    assert_eq!(text.style_token, None);
    // Untouched channels keep their bindings.
    assert_eq!(
        text.line_height_token,
        Some("$type.leading.tight".to_owned())
    );
    assert_eq!(
        text.letter_spacing_token,
        Some("$type.tracking.tight".to_owned())
    );
}

#[test]
fn ops_raw_weight_edit_clears_only_the_role_token() {
    let mut scene = scene_with_tokened_headline();
    scene
        .apply_operation(kind_replace(&scene, |text| text.font_weight = 700))
        .unwrap();

    let text = headline_text(&scene);
    assert_eq!(text.font_weight, 700);
    assert_eq!(text.style_token, None);
    assert_eq!(text.font_size_token, Some("$type.size.5xl".to_owned()));
    assert_eq!(
        text.line_height_token,
        Some("$type.leading.tight".to_owned())
    );
}

#[test]
fn ops_content_and_align_edits_keep_all_tokens() {
    let mut scene = scene_with_tokened_headline();
    scene
        .apply_operation(kind_replace(&scene, |text| {
            text.content = "Paperwork, shrunk".to_owned();
            text.align = TextAlign::Center;
        }))
        .unwrap();

    let text = headline_text(&scene);
    assert_eq!(text.style_token, Some("$type.h1".to_owned()));
    assert_eq!(text.font_size_token, Some("$type.size.5xl".to_owned()));
    assert_eq!(
        text.line_height_token,
        Some("$type.leading.tight".to_owned())
    );
    assert_eq!(
        text.letter_spacing_token,
        Some("$type.tracking.tight".to_owned())
    );
}

#[test]
fn ops_explicitly_authored_token_survives_a_raw_edit() {
    let mut scene = scene_with_tokened_headline();
    scene
        .apply_operation(kind_replace(&scene, |text| {
            text.font_size = 96.0;
            text.font_size_token = Some("$type.size.7xl".to_owned());
        }))
        .unwrap();

    let text = headline_text(&scene);
    // The edit re-bound the size channel on purpose; keep it.
    assert_eq!(text.font_size_token, Some("$type.size.7xl".to_owned()));
    // The role was left untouched while its size channel moved: stale.
    assert_eq!(text.style_token, None);
}

#[test]
fn undo_restores_the_cleared_bindings() {
    let mut scene = scene_with_tokened_headline();
    let edit = kind_replace(&scene, |text| text.font_size = 44.0);
    let inverses = scene
        .invert_operations(std::slice::from_ref(&edit))
        .unwrap()
        .expect("update_node is invertible");

    scene.apply_operation(edit).unwrap();
    assert_eq!(headline_text(&scene).style_token, None);

    scene.apply_operations(inverses).unwrap();
    let text = headline_text(&scene);
    assert_eq!(text.font_size, 64.0);
    assert_eq!(text.style_token, Some("$type.h1".to_owned()));
    assert_eq!(text.font_size_token, Some("$type.size.5xl".to_owned()));
}

#[test]
fn dsl_raw_size_edit_clears_size_and_style_tokens() {
    let mut scene = scene_with_tokened_headline();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("headline")),
        EditPatch::Node(NodeEditPatch {
            text: Some(TextEditPatch {
                font_size: FieldPatch::Set(44.0),
                ..TextEditPatch::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();
    batch.apply_checked(&mut scene).unwrap();

    let text = headline_text(&scene);
    assert_eq!(text.font_size, 44.0);
    assert_eq!(text.font_size_token, None);
    assert_eq!(text.style_token, None);
    assert_eq!(
        text.line_height_token,
        Some("$type.leading.tight".to_owned())
    );
}

#[test]
fn dsl_explicit_token_patch_survives_a_raw_edit() {
    let mut scene = scene_with_tokened_headline();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("headline")),
        EditPatch::Node(NodeEditPatch {
            text: Some(TextEditPatch {
                font_size: FieldPatch::Set(96.0),
                font_size_token: OptionalFieldPatch::Set("$type.size.7xl".to_owned()),
                ..TextEditPatch::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();
    batch.apply_checked(&mut scene).unwrap();

    let text = headline_text(&scene);
    assert_eq!(text.font_size_token, Some("$type.size.7xl".to_owned()));
    assert_eq!(text.style_token, None);
}

#[test]
fn dsl_content_only_edit_keeps_all_tokens() {
    let mut scene = scene_with_tokened_headline();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("headline")),
        EditPatch::Node(NodeEditPatch {
            text: Some(TextEditPatch {
                content: FieldPatch::Set("Paperwork, shrunk".to_owned()),
                ..TextEditPatch::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();
    batch.apply_checked(&mut scene).unwrap();

    let text = headline_text(&scene);
    assert_eq!(text.style_token, Some("$type.h1".to_owned()));
    assert_eq!(text.font_size_token, Some("$type.size.5xl".to_owned()));
}
