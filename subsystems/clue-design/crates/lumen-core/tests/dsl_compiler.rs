use lumen_core::validation::validate_scene;
use lumen_core::{
    compile_dsl, compile_dsl_into_scene, normalize_dsl, parse_dsl, DiagnosticSeverity, DslLineKind,
    NodeId, NodeKind, Operation, PageId, Paint, ParentRef, Scene, SlotId, SlotKey,
};

const VALID_BROCHURE: &str = include_str!("../fixtures/dsl/valid_brochure.lumen");
const VALID_LANGUAGE_SURFACE: &str = include_str!("../fixtures/dsl/valid_language_surface.lumen");
const INVALID_INDENTATION: &str = include_str!("../fixtures/dsl/invalid_indentation.lumen");
const INVALID_LEAF_CHILD: &str = include_str!("../fixtures/dsl/invalid_leaf_child.lumen");
const INVALID_SLOT_KEY: &str = include_str!("../fixtures/dsl/invalid_slot_key.lumen");
const UNSUPPORTED_DIRECTIVE: &str = include_str!("../fixtures/dsl/unsupported_directive.lumen");

#[test]
fn normalizer_preserves_indentation_and_quoted_text_while_dropping_empty_lines() {
    let source = "\r\npage page_a4\r\n  headline text \"A  spaced title\"   \r\n\r\n";

    assert_eq!(
        normalize_dsl(source),
        "page page_a4\n  headline text \"A  spaced title\""
    );
}

#[test]
fn parser_accepts_broad_blueprint_inspired_language_surface() {
    let output = parse_dsl(VALID_LANGUAGE_SURFACE);

    assert_no_dsl_errors(&output.diagnostics);
    assert!(output.halted_at.is_none());
    assert!(output
        .document
        .lines
        .iter()
        .any(|line| matches!(line.kind, DslLineKind::Checkpoint(_))));
    assert!(output
        .document
        .lines
        .iter()
        .any(|line| matches!(line.kind, DslLineKind::Page(_))));
    assert!(
        output
            .document
            .lines
            .iter()
            .filter(|line| matches!(line.kind, DslLineKind::Element(_)))
            .count()
            >= 8
    );
}

#[test]
fn compiler_lowers_valid_brochure_to_scene_operations_and_slots() {
    let output = compile_dsl(VALID_BROCHURE);

    assert_no_dsl_errors(&output.diagnostics);
    assert!(output.halted_at.is_none());
    assert_eq!(
        output
            .operations
            .iter()
            .filter(|operation| matches!(operation, Operation::AddPage { .. }))
            .count(),
        1
    );
    assert_eq!(
        output
            .operations
            .iter()
            .filter(|operation| matches!(operation, Operation::InsertNode { .. }))
            .count(),
        5
    );
    assert_eq!(
        output
            .operations
            .iter()
            .filter(|operation| matches!(operation, Operation::UpsertSlot { .. }))
            .count(),
        3
    );
    assert_eq!(
        output
            .operations
            .iter()
            .filter(|operation| matches!(operation, Operation::BindNodeToSlot { .. }))
            .count(),
        3
    );
}

#[test]
fn compiled_dsl_applies_through_checked_core_operations() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_dsl"), "DSL");
    let output = compile_dsl_into_scene(VALID_BROCHURE, &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());
    assert_eq!(
        output.operation_report.as_ref().unwrap().applied_operations,
        output.compile_output.operations.len()
    );

    let diagnostics = validate_scene(&scene);
    assert!(diagnostics
        .iter()
        .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error));
    assert!(scene.pages.contains_key(&PageId::from("page_a4")));
    assert!(scene.nodes.contains_key(&NodeId::from("headline")));
    assert_eq!(
        scene
            .slot_by_key(&SlotKey::from("campaign.headline"))
            .unwrap()
            .id,
        SlotId::from("slot_campaign_headline")
    );
    assert_eq!(
        scene.bound_nodes_for_slot(&SlotId::from("slot_campaign_headline"))[0].id,
        NodeId::from("headline")
    );
}

#[test]
fn language_surface_lowers_geometry_paint_text_image_vector_line_autolayout_and_instance() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_surface"), "Surface");
    let output = compile_dsl_into_scene(VALID_LANGUAGE_SURFACE, &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    assert!(matches!(
        scene.nodes[&NodeId::from("layout")].kind,
        NodeKind::AutoLayout(_)
    ));
    assert!(matches!(
        scene.nodes[&NodeId::from("icon")].kind,
        NodeKind::Vector(_)
    ));
    assert!(matches!(
        scene.nodes[&NodeId::from("avatar")].kind,
        NodeKind::Image(_)
    ));
    assert!(matches!(
        scene.nodes[&NodeId::from("divider")].kind,
        NodeKind::Line(_)
    ));
    assert!(matches!(
        scene.nodes[&NodeId::from("instance_copy")].kind,
        NodeKind::Instance { .. }
    ));

    let layout = &scene.nodes[&NodeId::from("layout")];
    assert_eq!(layout.layout.as_ref().unwrap().gap, 16.0);
    assert_eq!(
        layout.layout.as_ref().unwrap().padding,
        [12.0, 12.0, 12.0, 12.0]
    );

    let card = &scene.nodes[&NodeId::from("card")];
    assert!(matches!(card.fills[0].paint, Paint::LinearGradient { .. }));
    let badge = &scene.nodes[&NodeId::from("badge")];
    assert!(matches!(badge.fills[0].paint, Paint::Token { .. }));
    assert_eq!(badge.transform.rotation, 2.0);
    assert!(!badge.transform.flip_x);
    assert!(!badge.transform.flip_y);
}

#[test]
fn hash_target_lines_parse_as_future_modify_syntax_not_comments() {
    let output = compile_dsl(
        r#"
page page_a4
  badge rect p(0,0) s(20,20) fill(#111827)
#badge p(4,4) fill(#ffffff)
"#,
    );

    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0701");
    assert!(output
        .document
        .lines
        .iter()
        .any(|line| matches!(line.kind, DslLineKind::Modification(_))));
}

#[test]
fn parser_reports_precise_indentation_and_leaf_child_errors() {
    let indentation = parse_dsl(INVALID_INDENTATION);
    assert_eq!(indentation.halted_at.as_ref().unwrap().code, "LUMD0301");
    assert_eq!(indentation.diagnostics[0].span.line, 2);

    let leaf_child = parse_dsl(INVALID_LEAF_CHILD);
    assert_eq!(leaf_child.halted_at.as_ref().unwrap().code, "LUMD0304");
    assert_eq!(leaf_child.diagnostics[0].span.line, 3);
}

#[test]
fn parser_rejects_invalid_slot_keys_without_silent_repair() {
    let output = parse_dsl(INVALID_SLOT_KEY);

    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0408");
    assert!(output.diagnostics[0]
        .diagnostic
        .message
        .contains("invalid slot key"));
}

#[test]
fn unsupported_directives_are_parsed_diagnosed_and_cascade_halted() {
    let output = compile_dsl(UNSUPPORTED_DIRECTIVE);

    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0700");
    assert!(output
        .operations
        .iter()
        .any(|operation| matches!(operation, Operation::AddPage { .. })));
    assert!(output
        .operations
        .iter()
        .any(|operation| matches!(operation, Operation::InsertNode { .. })));
    assert!(output
        .operations
        .iter()
        .all(|operation| !matches!(operation, Operation::RemoveNode { .. })));
}

#[test]
fn supported_delete_and_parent_directives_lower_to_operations() {
    let output = compile_dsl(
        r#"
page page_a4
  hero frame p(0,0) s(100,100)
  card frame p(0,120) s(100,100)
parent(card,hero,0)
delete(card)
"#,
    );

    assert_no_dsl_errors(&output.diagnostics);
    assert!(output.operations.iter().any(|operation| matches!(
        operation,
        Operation::MoveNode {
            node_id,
            new_parent: ParentRef::Node(parent),
            index: 0
        } if node_id == &NodeId::from("card") && parent == &NodeId::from("hero")
    )));
    assert!(output.operations.iter().any(|operation| matches!(
        operation,
        Operation::RemoveNode { node_id } if node_id == &NodeId::from("card")
    )));
}

#[test]
fn meta_slot_syntax_normalizes_to_slot_binding() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_meta_slot"), "Meta Slot");
    let output = compile_dsl_into_scene(
        r#"
page page_a4
  title text "Chief Medical Officer" p(0,0) s(200,hug) meta(slot="contact.title")
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(scene.slot_by_key(&SlotKey::from("contact.title")).is_some());
}

#[test]
fn parsed_but_unlowered_svg_icon_reports_explicit_error() {
    let output = compile_dsl(
        r#"
page page_a4
  icon svg(icon:calendar) p(0,0) s(24,24)
"#,
    );

    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0703");
    assert!(output
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.diagnostic.message.contains("svg icon")));
}

#[test]
fn unsupported_paint_arguments_are_errors_not_silent_ignores() {
    let output = parse_dsl(
        r#"
page page_a4
  card frame p(0,0) s(100,100) fill(solid(#ffffff,o(0.5)))
"#,
    );

    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0241");
}

fn assert_no_dsl_errors(diagnostics: &[lumen_core::DslDiagnostic]) {
    assert!(
        diagnostics
            .iter()
            .all(|diagnostic| diagnostic.diagnostic.severity != DiagnosticSeverity::Error),
        "{diagnostics:#?}"
    );
}
