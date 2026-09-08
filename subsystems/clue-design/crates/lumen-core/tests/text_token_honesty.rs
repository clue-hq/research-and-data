//! Token honesty on raw text edits: a raw typography edit must detach the
//! token that would otherwise re-resolve over it (export preflight, brand
//! apply) and silently clobber the human's change. Covers both writers —
//! the ops path (`UpdateNode` kind replace, what the editor emits) and the
//! structured-edit path (`TextEditPatch`, what the agent's DSL emits) — plus
//! the inverse-op roundtrip that restores bindings on undo.

use lumen_core::{
    build_modify_operations, Color, DocumentId, EditPatch, EditTargetRef, FieldPatch, Fill, Node,
    NodeEditPatch, NodeId, NodeKind, NodePatch, Operation, OptionalFieldPatch, Orientation, Page,
    PageId, PagePreset, PageSize, Paint, PaintId, ParentRef, Scene, SizeSpec, StackEntryEdit,
    TextAlign, TextEditPatch, TextNode, TextSpan, Unit,
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
fn sparse_same_token_reapplication_survives_serialized_operations() {
    let mut scene = scene_with_tokened_headline();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("headline")),
        EditPatch::Node(NodeEditPatch {
            text: Some(TextEditPatch {
                font_size: FieldPatch::Set(96.0),
                line_height: FieldPatch::Set(1.2),
                letter_spacing: FieldPatch::Set(0.0),
                style_token: OptionalFieldPatch::Set("$type.h1".to_owned()),
                font_size_token: OptionalFieldPatch::Set("$type.size.5xl".to_owned()),
                line_height_token: OptionalFieldPatch::Set("$type.leading.tight".to_owned()),
                letter_spacing_token: OptionalFieldPatch::Set("$type.tracking.tight".to_owned()),
                ..TextEditPatch::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();
    let operations: Vec<Operation> =
        serde_json::from_value(serde_json::to_value(&batch.operations).unwrap()).unwrap();
    scene.apply_operations(operations).unwrap();
    let text = headline_text(&scene);
    assert_eq!(text.font_size, 96.0);
    assert_eq!(text.style_token.as_deref(), Some("$type.h1"));
    assert_eq!(text.font_size_token.as_deref(), Some("$type.size.5xl"));
    assert_eq!(
        text.line_height_token.as_deref(),
        Some("$type.leading.tight")
    );
    assert_eq!(
        text.letter_spacing_token.as_deref(),
        Some("$type.tracking.tight")
    );
}

#[test]
fn full_kind_same_token_intent_survives_replay_and_undo_redo() {
    let mut scene = scene_with_tokened_headline();
    let original = headline_text(&scene).clone();
    let operation = kind_replace(&scene, |text| text.font_size = 96.0);
    let mut wire = serde_json::to_value(operation).unwrap();
    wire["patch"]["explicit_text_tokens"] = serde_json::json!({"style": true, "font_size": true});
    let operation: Operation = serde_json::from_value(wire).unwrap();
    let inverses = scene
        .invert_operations(std::slice::from_ref(&operation))
        .unwrap()
        .unwrap();
    scene.apply_operation(operation.clone()).unwrap();
    assert_eq!(
        headline_text(&scene).font_size_token.as_deref(),
        Some("$type.size.5xl")
    );
    assert_eq!(
        headline_text(&scene).style_token.as_deref(),
        Some("$type.h1")
    );
    let inverse_wire = serde_json::to_string(&inverses).unwrap();
    scene
        .apply_operations(serde_json::from_str::<Vec<Operation>>(&inverse_wire).unwrap())
        .unwrap();
    assert_eq!(headline_text(&scene), &original);
    scene.apply_operation(operation).unwrap();
    assert_eq!(headline_text(&scene).font_size, 96.0);
    assert_eq!(
        headline_text(&scene).font_size_token.as_deref(),
        Some("$type.size.5xl")
    );
}

#[test]
fn explicit_text_token_intent_requires_a_text_kind_update() {
    let mut scene = scene_with_tokened_headline();
    let operation = Operation::UpdateNode {
        node_id: NodeId::from("headline"),
        patch: NodePatch::default(),
    };
    let mut wire = serde_json::to_value(operation).unwrap();
    wire["patch"]["explicit_text_tokens"] = serde_json::json!({"font_size": true});
    let operation: Operation = serde_json::from_value(wire).unwrap();
    assert_eq!(
        scene.apply_operation(operation).unwrap_err().code,
        "op.text_token_intent"
    );
}

#[test]
fn reconcile_reapplies_same_tokens_as_part_of_the_intended_text() {
    let mut scene = Scene::new(DocumentId::from("doc_reconcile_tokens"), "Token replay");
    let result = lumen_core::compile_dsl_into_scene(
        "page square size(1080,1080,px)\n  artboard fr s(fill,fill)\n    headline text \"Before\" s(900,hug) style($type.display) font_size(64)",
        &mut scene,
    );
    assert!(result.operation_error.is_none());
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("headline")),
        EditPatch::Node(NodeEditPatch {
            text: Some(TextEditPatch {
                font_size_token: OptionalFieldPatch::Set("type.size.6xl".into()),
                ..TextEditPatch::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();
    batch.apply_checked(&mut scene).unwrap();
    let result = lumen_core::compile_dsl_into_scene(
        "reconcile(artboard)\n  headline text \"After\" s(900,hug) style($type.display) font_size($type.size.6xl)",
        &mut scene,
    );
    assert!(result.operation_error.is_none());
    assert_eq!(headline_text(&scene).content, "After");
    assert_eq!(
        headline_text(&scene).font_size_token.as_deref(),
        Some("type.size.6xl")
    );
    assert_eq!(
        headline_text(&scene).style_token.as_deref(),
        Some("type.display")
    );
}

#[test]
fn sparse_explicit_clear_survives_serialized_operations() {
    let mut scene = scene_with_tokened_headline();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("headline")),
        EditPatch::Node(NodeEditPatch {
            text: Some(TextEditPatch {
                font_size: FieldPatch::Set(44.0),
                font_size_token: OptionalFieldPatch::Clear,
                style_token: OptionalFieldPatch::Clear,
                ..TextEditPatch::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();
    let wire = serde_json::to_string(&batch.operations).unwrap();
    scene
        .apply_operations(serde_json::from_str::<Vec<Operation>>(&wire).unwrap())
        .unwrap();
    assert_eq!(headline_text(&scene).font_size, 44.0);
    assert!(headline_text(&scene).font_size_token.is_none());
    assert!(headline_text(&scene).style_token.is_none());
    assert_eq!(
        headline_text(&scene).line_height_token.as_deref(),
        Some("$type.leading.tight")
    );
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

// ---- Token honesty for color (4b): raw fills edits detach the type role ----
//
// Text color lives in node-level fills; the role's baked color (plus
// contrast correction) re-resolves over them, so a raw recolor must clear
// `style_token` the same way a raw typography edit does. Typography channel
// tokens are not color-bearing and survive.

fn recolor(value: &str) -> Vec<Fill> {
    vec![Fill {
        id: PaintId::from("fill_headline"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: value.to_owned(),
            },
        },
    }]
}

#[test]
fn ops_raw_fill_edit_clears_only_the_style_token() {
    let mut scene = scene_with_tokened_headline();
    scene
        .apply_operation(Operation::UpdateNode {
            node_id: NodeId::from("headline"),
            patch: NodePatch {
                fills: FieldPatch::Set(recolor("#FF3366")),
                ..NodePatch::default()
            },
        })
        .unwrap();

    let text = headline_text(&scene);
    assert_eq!(text.style_token, None);
    // Color is not a typography channel: the channel tokens survive.
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
fn ops_fill_noop_keeps_the_style_token() {
    let mut scene = scene_with_tokened_headline();
    let current_fills = scene.nodes[&NodeId::from("headline")].fills.clone();
    scene
        .apply_operation(Operation::UpdateNode {
            node_id: NodeId::from("headline"),
            patch: NodePatch {
                fills: FieldPatch::Set(current_fills),
                ..NodePatch::default()
            },
        })
        .unwrap();

    assert_eq!(
        headline_text(&scene).style_token,
        Some("$type.h1".to_owned())
    );
}

#[test]
fn ops_explicitly_authored_style_token_survives_a_recolor() {
    let mut scene = scene_with_tokened_headline();
    let mut rebound = headline_text(&scene).clone();
    rebound.style_token = Some("$type.h2".to_owned());
    scene
        .apply_operation(Operation::UpdateNode {
            node_id: NodeId::from("headline"),
            patch: NodePatch {
                kind: FieldPatch::Set(NodeKind::Text(rebound)),
                fills: FieldPatch::Set(recolor("#FF3366")),
                ..NodePatch::default()
            },
        })
        .unwrap();

    // The edit re-bound the role on purpose; the recolor must not sever it.
    assert_eq!(
        headline_text(&scene).style_token,
        Some("$type.h2".to_owned())
    );
}

#[test]
fn undo_restores_the_role_binding_after_a_recolor() {
    let mut scene = scene_with_tokened_headline();
    let edit = Operation::UpdateNode {
        node_id: NodeId::from("headline"),
        patch: NodePatch {
            fills: FieldPatch::Set(recolor("#FF3366")),
            ..NodePatch::default()
        },
    };
    let inverses = scene
        .invert_operations(std::slice::from_ref(&edit))
        .unwrap()
        .expect("update_node is invertible");

    scene.apply_operation(edit).unwrap();
    assert_eq!(headline_text(&scene).style_token, None);

    scene.apply_operations(inverses).unwrap();
    let node = &scene.nodes[&NodeId::from("headline")];
    assert!(node.fills.is_empty());
    assert_eq!(
        headline_text(&scene).style_token,
        Some("$type.h1".to_owned())
    );
}

#[test]
fn dsl_fill_stack_edit_clears_the_style_token() {
    let mut scene = scene_with_tokened_headline();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("headline")),
        EditPatch::Node(NodeEditPatch {
            fill_edits: vec![StackEntryEdit::Add {
                entry: recolor("#FF3366").remove(0),
                index: None,
            }],
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();
    batch.apply_checked(&mut scene).unwrap();

    let text = headline_text(&scene);
    assert_eq!(text.style_token, None);
    assert_eq!(text.font_size_token, Some("$type.size.5xl".to_owned()));
}

#[test]
fn a6_typography_fields_apply_and_are_not_token_channels() {
    // The five A6a fields flow through the edit patch, and — because none is a
    // token channel — they never trip clear_stale_tokens: every binding survives.
    let mut scene = scene_with_tokened_headline();
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("headline")),
        EditPatch::Node(NodeEditPatch {
            text: Some(TextEditPatch {
                text_transform: FieldPatch::Set(lumen_core::TextTransform::Uppercase),
                underline: FieldPatch::Set(true),
                strikethrough: FieldPatch::Set(true),
                truncate: FieldPatch::Set(true),
                paragraph_spacing: FieldPatch::Set(8.0),
                ..TextEditPatch::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();
    batch.apply_checked(&mut scene).unwrap();

    let text = headline_text(&scene);
    assert_eq!(text.text_transform, lumen_core::TextTransform::Uppercase);
    assert!(text.underline);
    assert!(text.strikethrough);
    assert!(text.truncate);
    assert_eq!(text.paragraph_spacing, 8.0);
    // Not token channels → bindings untouched.
    assert_eq!(text.style_token, Some("$type.h1".to_owned()));
    assert_eq!(text.font_size_token, Some("$type.size.5xl".to_owned()));
    assert_eq!(text.line_height_token, Some("$type.leading.tight".to_owned()));
}

// --- A6b D4: span honesty on content edits ---

fn accent_span() -> TextSpan {
    // "Healthcare paperwork" → accent the first word [0,10).
    TextSpan {
        start: 0,
        end: 10,
        fill: Some(Paint::Solid {
            color: Color::Hex {
                value: "#ff0000".to_owned(),
            },
        }),
        font_weight: None,
        underline: None,
        strikethrough: None,
        italic: None,
    }
}

fn seed_span(scene: &mut Scene) {
    scene
        .apply_operation(kind_replace(scene, |text| {
            text.spans = vec![accent_span()];
        }))
        .unwrap();
}

#[test]
fn d4_content_edit_without_spans_clears_stale_spans() {
    let mut scene = scene_with_tokened_headline();
    seed_span(&mut scene);
    assert_eq!(headline_text(&scene).spans.len(), 1);

    // A content edit that does NOT re-author spans clears them (stale offsets).
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("headline")),
        EditPatch::Node(NodeEditPatch {
            text: Some(TextEditPatch {
                content: FieldPatch::Set("Totally different copy".to_owned()),
                ..TextEditPatch::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();
    batch.apply_checked(&mut scene).unwrap();

    assert_eq!(headline_text(&scene).content, "Totally different copy");
    assert!(
        headline_text(&scene).spans.is_empty(),
        "content edit must drop stale spans"
    );
}

#[test]
fn d4_content_edit_that_sets_spans_applies_both() {
    let mut scene = scene_with_tokened_headline();
    seed_span(&mut scene);

    let replacement = TextSpan {
        start: 0,
        end: 3,
        fill: None,
        font_weight: Some(700),
        underline: None,
        strikethrough: None,
        italic: None,
    };
    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("headline")),
        EditPatch::Node(NodeEditPatch {
            text: Some(TextEditPatch {
                content: FieldPatch::Set("New headline copy".to_owned()),
                spans: FieldPatch::Set(vec![replacement.clone()]),
                ..TextEditPatch::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();
    batch.apply_checked(&mut scene).unwrap();

    assert_eq!(headline_text(&scene).content, "New headline copy");
    assert_eq!(headline_text(&scene).spans, vec![replacement]);
}

#[test]
fn d4_non_content_edit_preserves_spans() {
    let mut scene = scene_with_tokened_headline();
    seed_span(&mut scene);

    let batch = build_modify_operations(
        &scene,
        EditTargetRef::Node(NodeId::from("headline")),
        EditPatch::Node(NodeEditPatch {
            text: Some(TextEditPatch {
                align: FieldPatch::Set(TextAlign::Center),
                ..TextEditPatch::default()
            }),
            ..NodeEditPatch::default()
        }),
    )
    .unwrap();
    batch.apply_checked(&mut scene).unwrap();

    // No content change → spans survive.
    assert_eq!(headline_text(&scene).spans, vec![accent_span()]);
}

#[test]
fn d4_undo_restores_cleared_spans() {
    let mut scene = scene_with_tokened_headline();
    seed_span(&mut scene);

    let edit = kind_replace(&scene, |text| {
        text.content = "Rewritten".to_owned();
        text.spans.clear();
    });
    let inverses = scene
        .invert_operations(std::slice::from_ref(&edit))
        .unwrap()
        .expect("update_node is invertible");

    scene.apply_operation(edit).unwrap();
    assert!(headline_text(&scene).spans.is_empty());

    scene.apply_operations(inverses).unwrap();
    // Undo restores the whole prior Text kind, spans included.
    assert_eq!(headline_text(&scene).spans, vec![accent_span()]);
    assert_eq!(headline_text(&scene).content, "Healthcare paperwork");
}

#[test]
fn d4_whole_kind_content_replace_clears_stale_spans_too() {
    // A6b D4 review fix: the editor's updateTextNode path (whole-kind Set,
    // NOT TextEditPatch) must apply the same span honesty — a content change
    // carrying the old spans forward unchanged clears them; a replace that
    // re-authors DIFFERENT spans alongside the new content keeps them.
    let mut scene = scene_with_tokened_headline();
    seed_span(&mut scene);
    assert_eq!(headline_text(&scene).spans.len(), 1);

    scene
        .apply_operation(kind_replace(&scene, |text| {
            text.content = "Totally different copy".to_owned();
        }))
        .unwrap();
    assert!(
        headline_text(&scene).spans.is_empty(),
        "whole-kind content replace must drop stale spans"
    );

    // Re-authoring different spans with the new content keeps them.
    seed_span(&mut scene);
    scene
        .apply_operation(kind_replace(&scene, |text| {
            text.content = "Fresh copy again".to_owned();
            text.spans = vec![TextSpan {
                start: 0,
                end: 5,
                fill: None,
                font_weight: Some(700),
                underline: None,
                strikethrough: None,
                italic: None,
            }];
        }))
        .unwrap();
    assert_eq!(headline_text(&scene).spans.len(), 1);
    assert_eq!(headline_text(&scene).spans[0].end, 5);

    // Non-content whole-kind edits keep spans untouched.
    scene
        .apply_operation(kind_replace(&scene, |text| text.font_size = 60.0))
        .unwrap();
    assert_eq!(headline_text(&scene).spans.len(), 1);
}
