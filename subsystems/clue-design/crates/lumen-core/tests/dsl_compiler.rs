use lumen_core::validation::validate_scene;
use lumen_core::{
    compile_dsl, compile_dsl_into_scene, normalize_dsl, parse_dsl, Color, DiagnosticSeverity,
    Dimension, DslCompileSession, DslLayoutAnchor, DslLayoutAxis, DslLineKind, DslProperty,
    DslScalar, LayoutAnchor, NodeId, NodeKind, Operation, Orientation, PageId, PagePreset, Paint,
    ParentRef, Scene, SlotKey, TextDirection, TextWrap, Unit,
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
            .key,
        SlotKey::from("campaign.headline")
    );
    let headline_slot_id = scene
        .slot_by_key(&SlotKey::from("campaign.headline"))
        .unwrap()
        .id
        .clone();
    assert_eq!(
        scene.bound_nodes_for_slot(&headline_slot_id)[0].id,
        NodeId::from("headline")
    );
}

#[test]
fn dsl_custom_page_size_lowers_to_scene_page_size() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_square"), "Square");
    let output = compile_dsl_into_scene("page page_square size(1080,1080,px)", &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let page = &scene.pages[&PageId::from("page_square")];
    assert_eq!(page.size.width, 1080.0);
    assert_eq!(page.size.height, 1080.0);
    assert_eq!(page.size.unit, Unit::Px);
    assert_eq!(page.size.preset, Some(PagePreset::Custom));
    assert_eq!(page.size.orientation, Orientation::Landscape);
}

#[test]
fn dsl_autolayout_anchors_lower_to_scene_alignment() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_align"), "Align");
    let output = compile_dsl_into_scene(
        r#"
page page_square size(400,300,px)
  nav al(h,x(sb),y(c)) p(0,0) s(360,80) g(16) pad(20)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let layout = scene.nodes[&NodeId::from("nav")].layout.as_ref().unwrap();
    assert_eq!(layout.align_x, LayoutAnchor::SpaceBetween);
    assert_eq!(layout.align_y, LayoutAnchor::Center);
}

#[test]
fn dsl_text_typography_fields_lower_to_text_node() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_type"), "Type");
    let output = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  headline text "Reliable copy fit" p(24,24) s(240,80) font("Inter",32,800,left) lh(1.08) ls(0.4) max_lines(2) wrap_text(true) dir(ltr)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let NodeKind::Text(text) = &scene.nodes[&NodeId::from("headline")].kind else {
        panic!("expected text node");
    };
    assert_eq!(text.line_height, 1.08);
    assert_eq!(text.letter_spacing, 0.4);
    assert_eq!(text.max_lines, Some(2));
    assert_eq!(text.wrap, TextWrap::Wrap);
    assert_eq!(text.direction, TextDirection::Ltr);
}

#[test]
fn dsl_accepts_safe_typography_aliases_models_commonly_emit() {
    let mut scene = Scene::new(
        lumen_core::DocumentId::from("doc_type_aliases"),
        "Type Aliases",
    );
    let output = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  label text "INSIGHT HEALTH" p(24,24) s(240,hug) font_size(18) font_weight(700) tracking(200) wrap_text(false)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let NodeKind::Text(text) = &scene.nodes[&NodeId::from("label")].kind else {
        panic!("expected text node");
    };
    assert_eq!(text.font_size, 18.0);
    assert_eq!(text.font_weight, 700);
    assert!((text.letter_spacing - 3.6).abs() < 0.001);
    assert_eq!(text.wrap, TextWrap::NoWrap);
}

#[test]
fn dsl_modify_line_updates_existing_text_node_without_regenerating_page() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_modify"), "Modify");
    let first = compile_dsl_into_scene(
        r#"
page page_square size(1080,1080,px)
  hero fr p(40,40) s(1000,hug)
    headline text "Oversized bad headline" p(0,0) s(fill,hug) font("Inter",72,800,left)
    body text "Keep this copy" p(0,120) s(fill,hug) font("Inter",24,500,left)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&first.compile_output.diagnostics);

    let second = compile_dsl_into_scene(
        r#"#headline text("Let surgeons focus on surgery.") font_size(44) lh(1.08) s(fill,hug)"#,
        &mut scene,
    );

    assert_no_dsl_errors(&second.compile_output.diagnostics);
    assert!(second.operation_error.is_none());
    assert_eq!(scene.pages.len(), 1);
    assert_eq!(
        second
            .compile_output
            .operations
            .iter()
            .filter(|operation| matches!(operation, Operation::UpdateNode { .. }))
            .count(),
        1
    );
    let NodeKind::Text(headline) = &scene.nodes[&NodeId::from("headline")].kind else {
        panic!("expected text node");
    };
    assert_eq!(headline.content, "Let surgeons focus on surgery.");
    assert_eq!(headline.font_size, 44.0);
    assert_eq!(headline.line_height, 1.08);
}

#[test]
fn dsl_modify_line_updates_page_size_and_background() {
    let mut scene = Scene::new(
        lumen_core::DocumentId::from("doc_page_modify"),
        "Page Modify",
    );
    let first = compile_dsl_into_scene("page page_square size(1080,1080,px)", &mut scene);
    assert_no_dsl_errors(&first.compile_output.diagnostics);

    let second = compile_dsl_into_scene(
        r##"#page:page_square size(1200,628,px) background(#111827) name("Landscape Ad")"##,
        &mut scene,
    );

    assert_no_dsl_errors(&second.compile_output.diagnostics);
    assert!(second.operation_error.is_none());
    let page = &scene.pages[&PageId::from("page_square")];
    assert_eq!(page.name, "Landscape Ad");
    assert_eq!(page.size.width, 1200.0);
    assert_eq!(page.size.height, 628.0);
    assert_eq!(page.background.len(), 1);
}

#[test]
fn dsl_modify_line_updates_slot_metadata_and_binding() {
    let mut scene = Scene::new(
        lumen_core::DocumentId::from("doc_slot_modify"),
        "Slot Modify",
    );
    let first = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  headline text "Headline" p(24,24) s(300,hug) slot(campaign.headline)
  subhead text "Subhead" p(24,96) s(300,hug)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&first.compile_output.diagnostics);

    let second = compile_dsl_into_scene(
        r#"#slot:campaign.headline placeholder("Let surgeons focus on surgery.") sample("Let Dr. Sharma focus on surgery.") bind(subhead)"#,
        &mut scene,
    );

    assert_no_dsl_errors(&second.compile_output.diagnostics);
    assert!(second.operation_error.is_none());
    let slot = scene
        .slot_by_key(&SlotKey::from("campaign.headline"))
        .expect("slot should exist");
    assert_eq!(
        slot.placeholder.as_deref(),
        Some("Let surgeons focus on surgery.")
    );
    assert_eq!(
        slot.validation.samples[0],
        "Let Dr. Sharma focus on surgery."
    );
    assert!(slot.bound_nodes.contains(&NodeId::from("headline")));
    assert!(slot.bound_nodes.contains(&NodeId::from("subhead")));
}

#[test]
fn dsl_before_after_directives_reorder_existing_nodes() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_reorder"), "Reorder");
    let first = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  hero fr p(0,0) s(400,400)
    headline text "Headline" p(0,0) s(fill,hug)
    body text "Body" p(0,40) s(fill,hug)
    cta text "CTA" p(0,80) s(fill,hug)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&first.compile_output.diagnostics);

    let second = compile_dsl_into_scene("after(headline,cta)", &mut scene);
    assert_no_dsl_errors(&second.compile_output.diagnostics);
    assert_eq!(
        scene.nodes[&NodeId::from("hero")].children,
        vec![
            NodeId::from("body"),
            NodeId::from("cta"),
            NodeId::from("headline")
        ]
    );

    let third = compile_dsl_into_scene("before(headline,body)", &mut scene);
    assert_no_dsl_errors(&third.compile_output.diagnostics);
    assert_eq!(
        scene.nodes[&NodeId::from("hero")].children,
        vec![
            NodeId::from("headline"),
            NodeId::from("body"),
            NodeId::from("cta")
        ]
    );
}

#[test]
fn dsl_clone_directive_clones_subtree_without_regenerating_page() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_clone"), "Clone");
    let first = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  hero fr p(0,0) s(400,160)
    headline text "Headline" p(24,24) s(300,hug) slot(campaign.headline)
    cta text "CTA" p(24,96) s(120,hug)
  footer fr p(0,240) s(400,80)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&first.compile_output.diagnostics);

    let second = compile_dsl_into_scene(
        "clone(hero,hero_variant,after:footer,slots:detach,computed:clear)",
        &mut scene,
    );

    assert_no_dsl_errors(&second.compile_output.diagnostics);
    assert!(second.operation_error.is_none());
    assert_eq!(scene.pages.len(), 1);
    assert_eq!(
        scene.pages[&PageId::from("page_square")].children,
        vec![
            NodeId::from("hero"),
            NodeId::from("footer"),
            NodeId::from("hero_variant")
        ]
    );
    assert_eq!(
        scene.nodes[&NodeId::from("hero_variant")].children,
        vec![
            NodeId::from("hero_variant__headline"),
            NodeId::from("hero_variant__cta")
        ]
    );
    let slot = scene
        .slot_by_key(&SlotKey::from("campaign.headline"))
        .expect("source slot should remain");
    assert_eq!(slot.bound_nodes, vec![NodeId::from("headline")]);
}

#[test]
fn dsl_replace_directive_swaps_existing_node_in_place() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_replace"), "Replace");
    let first = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  hero fr p(0,0) s(400,200)
    old_headline text "Old headline" p(24,24) s(300,hug) slot(campaign.headline)
    replacement_headline text "Better headline" p(24,120) s(300,hug)
    cta text "CTA" p(24,160) s(120,hug)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&first.compile_output.diagnostics);

    let second = compile_dsl_into_scene(
        "replace(old_headline,replacement_headline,slots:preserve)",
        &mut scene,
    );

    assert_no_dsl_errors(&second.compile_output.diagnostics);
    assert!(second.operation_error.is_none());
    assert!(!scene.nodes.contains_key(&NodeId::from("old_headline")));
    assert_eq!(
        scene.nodes[&NodeId::from("hero")].children,
        vec![NodeId::from("replacement_headline"), NodeId::from("cta")]
    );
    let slot = scene
        .slot_by_key(&SlotKey::from("campaign.headline"))
        .expect("slot should remain");
    assert_eq!(slot.bound_nodes, vec![NodeId::from("replacement_headline")]);
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
fn hash_target_lines_lower_as_modify_operations_not_comments() {
    let output = compile_dsl(
        r#"
page page_a4
  badge rect p(0,0) s(20,20) fill(#111827)
#badge p(4,4) fill(#ffffff)
"#,
    );

    assert!(output.halted_at.is_none());
    assert!(output
        .document
        .lines
        .iter()
        .any(|line| matches!(line.kind, DslLineKind::Modification(_))));
    assert!(output
        .operations
        .iter()
        .any(|operation| matches!(operation, Operation::UpdateNode { .. })));
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

#[test]
fn malformed_nested_paint_calls_return_diagnostics_instead_of_panicking() {
    for source in [
        r#"
page page_a4
  card frame p(0,0) s(100,100) fill(linear(90)
"#,
        r#"
page page_a4
  card frame p(0,0) s(100,100) fill(radial(stop(#ffffff,0)
"#,
        r#"
page page_a4
  card frame p(0,0) s(100,100) fill(solid(#ffffff)
"#,
        r#"
page page_a4
  card frame p(0,0) s(100,100) fill(oklch(0.7,0.1)
"#,
    ] {
        let output = std::panic::catch_unwind(|| parse_dsl(source))
            .expect("malformed DSL should return diagnostics, not panic");

        assert_eq!(output.halted_at.as_ref().unwrap().line, 3);
        assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0245");
        assert!(output.diagnostics[0]
            .diagnostic
            .message
            .contains("malformed"));
    }
}

#[test]
fn malformed_fill_dimension_returns_diagnostic_instead_of_panicking() {
    let output = std::panic::catch_unwind(|| {
        parse_dsl(
            r#"
page page_a4
  card frame p(0,0) s(fill(2],100)
"#,
        )
    })
    .expect("malformed fill dimension should return diagnostics, not panic");

    assert_eq!(output.halted_at.as_ref().unwrap().line, 3);
    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0245");
}

#[test]
fn slot_ops_survive_later_lowering_halt() {
    let output = compile_dsl(
        r#"
page page_a4
  headline text "A headline" p(0,0) s(200,40) slot(campaign.headline)
ungroup(headline)
"#,
    );

    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0700");
    assert!(output
        .operations
        .iter()
        .any(|operation| matches!(operation, Operation::UpsertSlot { .. })));
    assert!(output.operations.iter().any(|operation| matches!(
        operation,
        Operation::BindNodeToSlot { node_id, .. } if node_id == &NodeId::from("headline")
    )));
}

#[test]
fn delete_after_slotted_node_does_not_create_invalid_deferred_bind() {
    let mut scene = Scene::new(
        lumen_core::DocumentId::from("doc_delete_slot"),
        "Delete Slot",
    );
    let output = compile_dsl_into_scene(
        r#"
page page_a4
  headline text "A headline" p(0,0) s(200,40) slot(campaign.headline)
delete(headline)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());
    assert!(!scene.nodes.contains_key(&NodeId::from("headline")));
    assert!(scene
        .slot_by_key(&SlotKey::from("campaign.headline"))
        .unwrap()
        .bound_nodes
        .is_empty());
}

#[test]
fn landscape_presets_swap_width_and_height() {
    let output = compile_dsl(
        r#"
page page_a4 preset(a4,landscape)
page page_letter preset(letter,landscape)
"#,
    );

    assert_no_dsl_errors(&output.diagnostics);
    let pages = output
        .operations
        .iter()
        .filter_map(|operation| {
            if let Operation::AddPage { page } = operation {
                Some((&page.id, &page.size))
            } else {
                None
            }
        })
        .collect::<Vec<_>>();

    assert_eq!(pages[0].0, &PageId::from("page_a4"));
    assert_eq!(pages[0].1.width, 297.0);
    assert_eq!(pages[0].1.height, 210.0);
    assert_eq!(pages[1].0, &PageId::from("page_letter"));
    assert_eq!(pages[1].1.width, 11.0);
    assert_eq!(pages[1].1.height, 8.5);
}

#[test]
fn slot_id_derivation_is_collision_free() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_slot_ids"), "Slot IDs");
    let output = compile_dsl_into_scene(
        r#"
page page_a4
  dotted text "Dotted" p(0,0) s(100,20) slot(account.name)
  underscored text "Underscored" p(0,24) s(100,20) slot(account_name)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());
    let dotted = scene.slot_by_key(&SlotKey::from("account.name")).unwrap();
    let underscored = scene.slot_by_key(&SlotKey::from("account_name")).unwrap();

    assert_ne!(dotted.id, underscored.id);
    assert!(dotted.id.as_str().starts_with("slot_account_name_"));
    assert!(underscored.id.as_str().starts_with("slot_account_name_"));

    let mut scene_again = Scene::new(lumen_core::DocumentId::from("doc_slot_ids_2"), "Slot IDs");
    let second = compile_dsl_into_scene(
        r#"
page page_a4
  dotted text "Dotted" p(0,0) s(100,20) slot(account.name)
  underscored text "Underscored" p(0,24) s(100,20) slot(account_name)
"#,
        &mut scene_again,
    );
    assert_no_dsl_errors(&second.compile_output.diagnostics);
    assert_eq!(
        dotted.id,
        scene_again
            .slot_by_key(&SlotKey::from("account.name"))
            .unwrap()
            .id
    );
}

#[test]
fn autolayout_anchors_are_typed_not_token_warnings() {
    let parsed = parse_dsl(
        r#"
page page_a4
  layout al(h,x(c),y(sb)) p(0,0) s(240,120)
"#,
    );

    assert_no_dsl_errors(&parsed.diagnostics);
    let layout_line = parsed
        .document
        .lines
        .iter()
        .find_map(|line| {
            if let DslLineKind::Element(element) = &line.kind {
                Some(element)
            } else {
                None
            }
        })
        .unwrap();

    assert!(layout_line.properties.iter().any(|property| matches!(
        property,
        DslProperty::LayoutAnchor {
            axis: DslLayoutAxis::X,
            anchor: DslLayoutAnchor::Center
        }
    )));
    assert!(layout_line.properties.iter().any(|property| matches!(
        property,
        DslProperty::LayoutAnchor {
            axis: DslLayoutAxis::Y,
            anchor: DslLayoutAnchor::SpaceBetween
        }
    )));

    let compiled = compile_dsl(
        r#"
page page_a4
  layout al(h,x(c),y(sb)) p(0,0) s(240,120)
"#,
    );

    assert!(compiled.halted_at.is_none());
    assert!(!compiled
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.diagnostic.code == "LUMD0704"));
    assert!(!compiled
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.diagnostic.code == "LUMD0702"));
}

#[test]
fn malformed_paint_tuple_tail_halts() {
    let output = parse_dsl(
        r#"
page page_a4
  card rect p(0,0) s(100,100) f[(bg,#ffffff),(fg,#000000]
"#,
    );

    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0247");
    assert!(output.diagnostics[0]
        .diagnostic
        .message
        .contains("malformed paint tuple list"));
}

#[test]
fn invalid_hex_color_is_diagnostic() {
    let output = parse_dsl(
        r#"
page page_a4
  card rect p(0,0) s(100,100) fill(#zzzzzz)
"#,
    );

    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0219");
    assert!(output.diagnostics[0]
        .diagnostic
        .message
        .contains("invalid color"));
}

#[test]
fn aarrggbb_hex_normalizes_for_export_contract() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_hex"), "Hex");
    let output = compile_dsl_into_scene(
        r#"
page page_a4
  card rect p(0,0) s(100,100) fill(#80ff0000)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());
    let fill = &scene.nodes[&NodeId::from("card")].fills[0];
    assert!(matches!(
        &fill.paint,
        Paint::Solid {
            color: Color::Hex { value }
        } if value == "#ff000080"
    ));
}

#[test]
fn delete_before_next_sibling_keeps_insert_index_valid() {
    let mut scene = Scene::new(
        lumen_core::DocumentId::from("doc_delete_index"),
        "Delete Index",
    );
    let output = compile_dsl_into_scene(
        r#"
page page_a4
  a rect p(0,0) s(10,10)
delete(a)
  b rect p(0,0) s(10,10)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none(), "{output:#?}");
    assert_eq!(
        scene.pages[&PageId::from("page_a4")].children,
        vec![NodeId::from("b")]
    );
}

#[test]
fn parent_before_next_sibling_keeps_insert_index_valid() {
    let mut scene = Scene::new(
        lumen_core::DocumentId::from("doc_parent_index"),
        "Parent Index",
    );
    let output = compile_dsl_into_scene(
        r#"
page page_a4
  target frame p(0,0) s(100,100)
  moved frame p(0,120) s(100,100)
parent(moved,target,0)
  sibling rect p(0,240) s(20,20)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none(), "{output:#?}");
    assert_eq!(
        scene.pages[&PageId::from("page_a4")].children,
        vec![NodeId::from("target"), NodeId::from("sibling")]
    );
    assert_eq!(
        scene.nodes[&NodeId::from("target")].children,
        vec![NodeId::from("moved")]
    );
}

#[test]
fn supported_directive_errors_surface_as_dsl_diagnostics() {
    let output = compile_dsl(
        r#"
page page_a4
delete(missing)
"#,
    );

    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0900");
    assert!(output
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.diagnostic.message.contains("does not exist")));
}

#[test]
fn tokenized_numeric_styles_parse_as_typed_scalars_without_halt() {
    let parsed = parse_dsl(
        r#"
page page_a4
  card frame p(0,0) s(100,100) g($spacing.4) rd($radius.md) o($opacity.subtle) pad($spacing.2)
  headline text("Title","Inter",$type.size.heading,700,left) p(0,0) s(80,20)
"#,
    );

    assert_no_dsl_errors(&parsed.diagnostics);
    assert!(parsed.halted_at.is_none());

    let card = parsed
        .document
        .lines
        .iter()
        .find_map(|line| {
            if let DslLineKind::Element(element) = &line.kind {
                (element.id == NodeId::from("card")).then_some(element)
            } else {
                None
            }
        })
        .unwrap();
    assert!(card.properties.iter().any(|property| matches!(
        property,
        DslProperty::Gap(DslScalar::Token(token)) if token == "spacing.4"
    )));
    assert!(card.properties.iter().any(|property| matches!(
        property,
        DslProperty::Radius(DslScalar::Token(token)) if token == "radius.md"
    )));
    assert!(card.properties.iter().any(|property| matches!(
        property,
        DslProperty::Opacity(DslScalar::Token(token)) if token == "opacity.subtle"
    )));
}

#[test]
fn dsl_token_scalars_lower_to_brand_carriers() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_token_carriers"), "Tokens");
    let output = compile_dsl_into_scene(
        r#"
page page_a4
  card autolayout(h) p(0,0) s($size.card,hug) fill($surface.brand) stroke($surface.brand,$stroke.width.firm) g($space.md) pad($space.md) rd($radius.md) o($opacity.subtle)
    headline text "Plan" p(0,0) s(120,20) style($type.headline) slot(campaign.headline)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let card = &scene.nodes[&NodeId::from("card")];
    assert_eq!(
        card.size.width,
        Dimension::Token {
            token: "size.card".to_owned()
        }
    );
    assert_eq!(
        card.layout.as_ref().unwrap().gap_token,
        Some("space.md".to_owned())
    );
    assert_eq!(
        card.layout.as_ref().unwrap().padding_token,
        Some("space.md".to_owned())
    );
    assert_eq!(card.corner.token, Some("radius.md".to_owned()));
    assert_eq!(card.opacity_token, Some("opacity.subtle".to_owned()));
    assert_eq!(
        card.strokes[0].width_token,
        Some("stroke.width.firm".to_owned())
    );
    assert!(matches!(
        &card.fills[0].paint,
        Paint::Token { token } if token == "surface.brand"
    ));

    let headline = &scene.nodes[&NodeId::from("headline")];
    assert!(matches!(
        &headline.kind,
        NodeKind::Text(text) if text.style_token.as_deref() == Some("type.headline")
    ));
}

#[test]
fn font_style_token_lowers_to_text_style_token() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_type_token"), "Type");
    let output = compile_dsl_into_scene(
        r#"
page page_a4
  headline text "Title" p(0,0) s(80,20) font($type.headline)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());
    assert!(matches!(
        &scene.nodes[&NodeId::from("headline")].kind,
        NodeKind::Text(text) if text.style_token.as_deref() == Some("type.headline")
    ));
}

#[test]
fn mixed_padding_tokens_warn_until_per_edge_carriers_exist() {
    let output = compile_dsl(
        r#"
page page_a4
  card autolayout(h) p(0,0) s(100,100) pad($space.sm,$space.md)
"#,
    );

    assert_no_dsl_errors(&output.diagnostics);
    assert!(output.halted_at.is_none());
    assert!(output.diagnostics.iter().any(|diagnostic| {
        diagnostic.diagnostic.code == "LUMD0705"
            && diagnostic
                .diagnostic
                .message
                .contains("mixed padding token syntax")
    }));
}

#[test]
fn unsupported_font_size_token_remains_explicit_warning() {
    let output = compile_dsl(
        r#"
page page_a4
  headline text "Title" p(0,0) s(80,20) font("Inter",$type.size.heading,700,left)
"#,
    );

    assert_no_dsl_errors(&output.diagnostics);
    assert!(output.halted_at.is_none());
    assert!(output
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.diagnostic.code == "LUMD0705"));
}

#[test]
fn stateful_session_resumes_inside_nested_container_after_halt() {
    let mut session = DslCompileSession::empty();
    let first = session.compile_block(
        r#"
page page_a4
  hero frame p(0,0) s(100,100)
    bad svg(icon:calendar) p(0,0) s(24,24)
"#,
    );

    assert_eq!(first.halted_at.as_ref().unwrap().code, "LUMD0703");

    let second = session.compile_block(
        r#"
    title text "Title" p(0,0) s(80,20)
"#,
    );

    assert_no_dsl_errors(&second.diagnostics);
    assert!(second.halted_at.is_none());
    assert!(session.scene().nodes.contains_key(&NodeId::from("title")));
    assert_eq!(
        session.scene().nodes[&NodeId::from("hero")].children,
        vec![NodeId::from("title")]
    );
}

#[test]
fn stateful_session_preserves_seen_ids_across_blocks() {
    let mut session = DslCompileSession::empty();
    let first = session.compile_block(
        r#"
page page_a4
  hero frame p(0,0) s(100,100)
"#,
    );
    assert_no_dsl_errors(&first.diagnostics);

    let second = session.compile_block(
        r#"
  hero rect p(0,0) s(20,20)
"#,
    );

    assert_eq!(second.halted_at.as_ref().unwrap().code, "LUMD0401");
}

#[test]
fn non_finite_numeric_literals_are_rejected() {
    for source in [
        r#"
page page_a4
  card rect p(NaN,0) s(100,100)
"#,
        r#"
page page_a4
  card rect p(0,0) s(inf,100)
"#,
    ] {
        let output = parse_dsl(source);
        assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0249");
    }
}

fn assert_no_dsl_errors(diagnostics: &[lumen_core::DslDiagnostic]) {
    assert!(
        diagnostics
            .iter()
            .all(|diagnostic| diagnostic.diagnostic.severity != DiagnosticSeverity::Error),
        "{diagnostics:#?}"
    );
}
