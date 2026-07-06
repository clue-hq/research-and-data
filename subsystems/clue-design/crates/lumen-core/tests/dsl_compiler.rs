use lumen_core::validation::validate_scene;
use lumen_core::{
    compile_dsl, compile_dsl_into_scene, normalize_dsl, parse_dsl, Color, DiagnosticSeverity,
    Dimension, DslCompileSession, DslLayoutAnchor, DslLayoutAxis, DslLineKind, DslProperty,
    DslScalar, LayoutAnchor, NodeId, NodeKind, Operation, Orientation, PageId, PagePreset, Paint,
    ParentRef, PhysicalUnit, Scene, SlotKey, TextDirection, TextWrap, Unit,
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

/// Empty-page compose gap (burned two live agent turns): a continuation
/// block must be able to FILL an existing empty page. A top-level
/// `#page:<id>` modification now opens that page as the parent context, so
/// indented element lines append to it — exactly like a fresh `page` line.
#[test]
fn continuation_page_modify_accepts_indented_children() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_fill"), "Fill");
    let first = compile_dsl_into_scene("page page_empty size(1080,1080,px)", &mut scene);
    assert_no_dsl_errors(&first.compile_output.diagnostics);
    assert!(scene.pages[&PageId::from("page_empty")].children.is_empty());

    let continuation = concat!(
        "#page:page_empty size(1080,1080,px)\n",
        "  hero_root fr p(0,0) s(1080,1080) fill($surface.brand)\n",
        "    title text \"Your health, now online.\" p(60,60) s(400,hug) font(\"Inter\",64,800,left)\n",
    );
    let output = compile_dsl_into_scene(continuation, &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());
    let page = &scene.pages[&PageId::from("page_empty")];
    assert_eq!(
        page.children,
        vec![lumen_core::NodeId::from("hero_root")],
        "the indented child must attach to the EXISTING page (it was silently dropped before)"
    );
    let hero = &scene.nodes[&lumen_core::NodeId::from("hero_root")];
    assert_eq!(hero.children, vec![lumen_core::NodeId::from("title")]);
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
    assert_eq!(page.size.unit, Unit::Pt);
    assert_eq!(page.size.preset, Some(PagePreset::Custom));
    assert_eq!(page.size.orientation, Orientation::Landscape);
    let source = page.size.source.as_ref().unwrap();
    assert_eq!(source.width, 1080.0);
    assert_eq!(source.height, 1080.0);
    assert_eq!(source.unit, Unit::Px);
    let raster = page.size.output.as_ref().unwrap().raster.as_ref().unwrap();
    assert_eq!(raster.width_px, 1080);
    assert_eq!(raster.height_px, 1080);
}

#[test]
fn dsl_custom_mm_page_size_lowers_to_pt_with_physical_metadata() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_a4_custom"), "A4 Custom");
    let output = compile_dsl_into_scene("page page_a4 size(210,297,mm)", &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let page = &scene.pages[&PageId::from("page_a4")];
    assert!((page.size.width - 595.275_590_551_181_2).abs() < 0.001);
    assert!((page.size.height - 841.889_763_779_527_6).abs() < 0.001);
    assert_eq!(page.size.unit, Unit::Pt);
    assert_eq!(page.size.preset, Some(PagePreset::Custom));
    assert_eq!(page.size.orientation, Orientation::Portrait);
    let source = page.size.source.as_ref().unwrap();
    assert_eq!(source.width, 210.0);
    assert_eq!(source.height, 297.0);
    assert_eq!(source.unit, Unit::Mm);
    let output = page.size.output.as_ref().unwrap();
    assert!(output.raster.is_none());
    let physical = output.physical.as_ref().unwrap();
    assert_eq!(physical.width, 210.0);
    assert_eq!(physical.height, 297.0);
    assert_eq!(physical.unit, PhysicalUnit::Mm);
}

#[test]
fn dsl_page_size_accepts_pt_without_export_metadata() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_pt"), "Point Page");
    let output = compile_dsl_into_scene("page page_pt size(595.276,841.89,pt)", &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let page = &scene.pages[&PageId::from("page_pt")];
    assert_eq!(page.size.width, 595.276);
    assert_eq!(page.size.height, 841.89);
    assert_eq!(page.size.unit, Unit::Pt);
    assert_eq!(page.size.source.as_ref().unwrap().unit, Unit::Pt);
    assert!(page.size.output.is_none());
}

#[test]
fn dsl_envelope_preset_lowers_to_canonical_pt_with_physical_metadata() {
    let output = compile_dsl("page page_envelope preset(envelope_dl)");

    assert_no_dsl_errors(&output.diagnostics);
    let Operation::AddPage { page } = &output.operations[0] else {
        panic!("expected add page operation");
    };

    assert_eq!(page.size.unit, Unit::Pt);
    assert_eq!(page.size.preset, Some(PagePreset::EnvelopeDl));
    assert_eq!(page.size.orientation, Orientation::Landscape);
    assert!((page.size.width - 623.622_047_244_094_5).abs() < 0.001);
    assert!((page.size.height - 311.811_023_622_047_23).abs() < 0.001);
    let source = page.size.source.as_ref().unwrap();
    assert_eq!(source.width, 220.0);
    assert_eq!(source.height, 110.0);
    assert_eq!(source.unit, Unit::Mm);
    let physical = page
        .size
        .output
        .as_ref()
        .unwrap()
        .physical
        .as_ref()
        .unwrap();
    assert_eq!(physical.unit, PhysicalUnit::Mm);
    assert_eq!(physical.width, 220.0);
    assert_eq!(physical.height, 110.0);
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
    assert_eq!(page.size.unit, Unit::Pt);
    assert_eq!(page.size.source.as_ref().unwrap().unit, Unit::Px);
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
fn unknown_svg_icon_reports_explicit_error_listing_options() {
    // Step 8: `svg(icon:name)` now lowers from a curated registry; an unknown name
    // still halts with LUMD0703, but the hint lists the real options so a typo recovers.
    let output = compile_dsl(
        r#"
page page_a4
  icon svg(icon:nonexistent-glyph) p(0,0) s(24,24)
"#,
    );

    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0703");
    assert!(output
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.diagnostic.message.contains("unknown icon")));
}

#[test]
fn svg_icon_lowers_to_a_vector_with_its_source_view_box() {
    // Step 8: `svg(icon:check)` lowers to a vector node carrying the curated icon's
    // path + its 24×24 source viewBox (which the renderers fit to the node box).
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_icon"), "Icons");
    let output = compile_dsl_into_scene(
        "page page_a4\n  mark svg(icon:check) p(0,0) s(48,48) fill(#111827)",
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    let NodeKind::Vector(vector) = &scene.nodes[&NodeId::from("mark")].kind else {
        panic!("svg(icon:check) should lower to a vector node");
    };
    assert!(vector.path_data.starts_with('M'), "{}", vector.path_data);
    assert_eq!(vector.view_box, Some([24.0, 24.0]));
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

    // Ungrouping a leaf text node fails at the edit layer (LUMD0900); the
    // earlier slot operations from the valid lines must survive the halt.
    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0900");
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
    assert!((pages[0].1.width - 841.889_763_779_527_6).abs() < 0.001);
    assert!((pages[0].1.height - 595.275_590_551_181_2).abs() < 0.001);
    assert_eq!(pages[0].1.unit, Unit::Pt);
    assert_eq!(pages[0].1.source.as_ref().unwrap().unit, Unit::Mm);
    assert_eq!(pages[1].0, &PageId::from("page_letter"));
    assert_eq!(pages[1].1.width, 792.0);
    assert_eq!(pages[1].1.height, 612.0);
    assert_eq!(pages[1].1.unit, Unit::Pt);
    assert_eq!(pages[1].1.source.as_ref().unwrap().unit, Unit::In);
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

#[test]
fn document_modify_line_lowers_to_update_document() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_meta"), "Before");
    let output = compile_dsl_into_scene(
        "page page_a4\n\n#document name(\"Renamed Artifact\") artifact_type(\"linkedin_ad\") medium(ad)",
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());
    assert_eq!(scene.meta.title, "Renamed Artifact");
    assert_eq!(scene.meta.artifact_type.as_deref(), Some("linkedin_ad"));
    assert_eq!(scene.meta.medium, Some(lumen_core::Medium::Ad));
}

#[test]
fn document_modify_brand_kit_sets_versioned_ref() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_brand"), "Doc");
    let output = compile_dsl_into_scene(
        "page page_a4\n\n#document brand_kit(brand_acme, 3)",
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    let brand_ref = scene.meta.brand_kit.as_ref().expect("brand kit ref set");
    assert_eq!(brand_ref.version, 3);
}

#[test]
fn export_profile_modify_line_lowers_to_upsert_profile() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_export"), "Doc");
    scene.export_profiles.push(lumen_core::ExportProfile {
        name: "print_pdf".to_owned(),
        format: lumen_core::ExportFormat::Svg,
        pdf_intent: None,
        raster: None,
        include_bleed: false,
        embed_fonts: false,
    });

    let output = compile_dsl_into_scene(
        "page page_a4\n\n#export:print_pdf format(pdf) pdf_intent(print) include_bleed(true) embed_fonts(true)",
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());
    let profile = scene.export_profile("print_pdf").expect("profile exists");
    assert_eq!(profile.format, lumen_core::ExportFormat::Pdf);
    assert_eq!(profile.pdf_intent, Some(lumen_core::PdfIntent::Print));
    assert!(profile.include_bleed);
    assert!(profile.embed_fonts);
}

#[test]
fn export_profile_modify_missing_profile_halts() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_export2"), "Doc");
    let output = compile_dsl_into_scene("#export:missing format(pdf)", &mut scene);
    assert!(output.compile_output.halted_at.is_some());
}

#[test]
fn checkpoint_comment_label_is_captured_in_compile_output() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_ckpt"), "Doc");
    let output = compile_dsl_into_scene(
        "// hero spacing fix\npage page_a4\n  hero fr p(0,0) s(100,100)",
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert_eq!(
        output.compile_output.checkpoint_label.as_deref(),
        Some("hero spacing fix")
    );
}

#[test]
fn delete_directive_supports_lifecycle_target_forms() {
    // Slot delete by key: unbinds without deleting the node.
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_del"), "Doc");
    let output = compile_dsl_into_scene(
        "page page_a4\n  headline text \"Title\" p(0,0) s(400,hug) slot(campaign.headline)\n\ndelete(slot:campaign.headline)",
        &mut scene,
    );
    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(scene
        .slot_by_key(&lumen_core::SlotKey::from("campaign.headline"))
        .is_none());
    assert!(scene.nodes.contains_key(&NodeId::from("headline")));

    // Asset delete archives by default.
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_del2"), "Doc");
    scene
        .apply_operation(lumen_core::Operation::UpsertAsset {
            asset: lumen_core::AssetRecord {
                id: "asset_x".into(),
                label: "X".to_owned(),
                kind: lumen_core::AssetKind::RasterImage,
                status: lumen_core::AssetStatus::Ready,
                source: lumen_core::AssetSource::Manual {
                    label: "fixture".to_owned(),
                },
                media: lumen_core::AssetMediaMetadata::default(),
                raster: None,
                vector: None,
                font: None,
                logo: None,
                license: None,
                provenance: lumen_core::AssetProvenance::default(),
                tags: Vec::new(),
            },
        })
        .unwrap();
    let output = compile_dsl_into_scene("page page_a4\n\ndelete(asset:asset_x)", &mut scene);
    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert_eq!(
        scene.assets[&lumen_core::AssetId::from("asset_x")].status,
        lumen_core::AssetStatus::Archived
    );

    // Last-page delete halts with the lifecycle diagnostic.
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_del3"), "Doc");
    let output = compile_dsl_into_scene("page page_a4\n\ndelete(page:page_a4)", &mut scene);
    assert!(output.compile_output.halted_at.is_some());
}

#[test]
fn delete_if_exists_skips_missing_target_with_warning() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_del4"), "Doc");
    let output = compile_dsl_into_scene("page page_a4\n\ndelete(ghost, if_exists)", &mut scene);
    assert!(output.compile_output.halted_at.is_none());
    assert!(output
        .compile_output
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.diagnostic.code == "LUMD0915"));

    // Strict default still halts on missing targets.
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_del5"), "Doc");
    let output = compile_dsl_into_scene("page page_a4\n\ndelete(ghost)", &mut scene);
    assert!(output.compile_output.halted_at.is_some());
}

#[test]
fn append_and_prepend_extend_existing_text_content() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_append"), "Doc");
    let output = compile_dsl_into_scene(
        "page page_a4\n  headline text \"Core promise\" p(0,0) s(400,hug)\n\n#headline append(\" - now with call routing\")\n#headline prepend(\"For neurosurgery teams: \")",
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    let NodeKind::Text(text) = &scene.nodes[&NodeId::from("headline")].kind else {
        panic!("expected text node");
    };
    assert_eq!(
        text.content,
        "For neurosurgery teams: Core promise - now with call routing"
    );
}

#[test]
fn append_on_non_text_node_halts() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_append2"), "Doc");
    let output = compile_dsl_into_scene(
        "page page_a4\n  box rect p(0,0) s(10,10)\n\n#box append(\"nope\")",
        &mut scene,
    );
    assert!(output.compile_output.halted_at.is_some());
}

#[test]
fn parent_directive_supports_relative_anchors() {
    let source = "page page_a4\n  hero fr p(0,0) s(800,600)\n    headline text \"H\" p(0,0) s(100,hug)\n    body text \"B\" p(0,0) s(100,hug)\n  logo rect p(0,0) s(50,50)\n\nparent(logo, hero, before:body)";
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_anchor"), "Doc");
    let output = compile_dsl_into_scene(source, &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert_eq!(
        scene.nodes[&NodeId::from("hero")].children,
        vec![
            NodeId::from("headline"),
            NodeId::from("logo"),
            NodeId::from("body")
        ]
    );

    let mut scene2 = Scene::new(lumen_core::DocumentId::from("doc_anchor2"), "Doc");
    let output = compile_dsl_into_scene(&source.replace("before:body", "after:body"), &mut scene2);
    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert_eq!(
        scene2.nodes[&NodeId::from("hero")].children,
        vec![
            NodeId::from("headline"),
            NodeId::from("body"),
            NodeId::from("logo")
        ]
    );

    // Anchor outside the destination parent halts precisely.
    let mut scene3 = Scene::new(lumen_core::DocumentId::from("doc_anchor3"), "Doc");
    let output = compile_dsl_into_scene(&source.replace("before:body", "before:logo"), &mut scene3);
    assert!(output.compile_output.halted_at.is_some());
}

#[test]
fn parent_directive_keeps_index_forms() {
    let source = "page page_a4\n  hero fr p(0,0) s(800,600)\n    headline text \"H\" p(0,0) s(100,hug)\n  logo rect p(0,0) s(50,50)\n\nparent(logo, hero, index:0)";
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_idx"), "Doc");
    let output = compile_dsl_into_scene(source, &mut scene);
    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert_eq!(
        scene.nodes[&NodeId::from("hero")].children[0],
        NodeId::from("logo")
    );
}

#[test]
fn ungroup_dissolves_group_preserving_child_order() {
    let source = "page page_a4\n  wrap gr p(0,0) s(400,400)\n    a rect p(0,0) s(10,10)\n    b rect p(0,0) s(10,10)\n  tail rect p(0,0) s(10,10)\n\nungroup(wrap)";
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_ungroup"), "Doc");
    let output = compile_dsl_into_scene(source, &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(!scene.nodes.contains_key(&NodeId::from("wrap")));
    assert_eq!(
        scene.pages[&lumen_core::PageId::from("page_a4")].children,
        vec![NodeId::from("a"), NodeId::from("b"), NodeId::from("tail")]
    );
}

#[test]
fn ungroup_protects_auto_layout_unless_allowed() {
    let source = "page page_a4\n  stack al(v) p(0,0) s(400,400)\n    a rect p(0,0) s(10,10)\n\nungroup(stack)";
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_ungroup2"), "Doc");
    let output = compile_dsl_into_scene(source, &mut scene);
    assert!(output.compile_output.halted_at.is_some());

    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_ungroup3"), "Doc");
    let output = compile_dsl_into_scene(
        &source.replace("ungroup(stack)", "ungroup(stack, allow_layout)"),
        &mut scene,
    );
    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(!scene.nodes.contains_key(&NodeId::from("stack")));
}

#[test]
fn override_group_constrains_indented_modifies_to_root_subtree() {
    let source = "page page_a4\n  card fr p(0,0) s(200,200)\n    title text \"T\" p(0,0) s(100,hug)\n  other text \"O\" p(0,0) s(100,hug)\n\nclone(card, card_2, after:card)\noverride(card_2)\n  #card_2__title text(\"Override applied\")";
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_override"), "Doc");
    let output = compile_dsl_into_scene(source, &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    let NodeKind::Text(text) = &scene.nodes[&NodeId::from("card_2__title")].kind else {
        panic!("expected cloned title text node");
    };
    assert_eq!(text.content, "Override applied");

    // Touching a node outside the override root halts with LUMD0913.
    let bad = source.replace(
        "#card_2__title text(\"Override applied\")",
        "#other text(\"Escape\")",
    );
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_override2"), "Doc");
    let output = compile_dsl_into_scene(&bad, &mut scene);
    assert_eq!(
        output.compile_output.halted_at.as_ref().unwrap().code,
        "LUMD0913"
    );
}

struct FixtureHistory {
    undo: Vec<Operation>,
}

impl lumen_core::DslHistoryAdapter for FixtureHistory {
    fn undo_operations(&self, label: Option<&str>) -> Option<Vec<Operation>> {
        (label == Some("fix")).then(|| self.undo.clone())
    }

    fn redo_operations(&self, _label: Option<&str>) -> Option<Vec<Operation>> {
        None
    }
}

#[test]
fn undo_lowers_through_history_adapter_and_rejects_without_one() {
    let mut session = lumen_core::DslCompileSession::empty();
    let setup =
        session.compile_block("page page_a4\n  headline text \"After edit\" p(0,0) s(400,hug)");
    assert!(setup.halted_at.is_none());

    // Pure compile (no adapter) rejects undo with the precise diagnostic.
    let rejected = session.compile_block("undo(\"fix\")");
    assert_eq!(rejected.halted_at.as_ref().unwrap().code, "LUMD0916");

    // With an adapter, undo lowers the inverse operations it supplies.
    let history = FixtureHistory {
        undo: vec![Operation::UpdateNode {
            node_id: NodeId::from("headline"),
            patch: lumen_core::NodePatch {
                kind: lumen_core::FieldPatch::Set(NodeKind::Text(lumen_core::TextNode {
                    content: "Before edit".to_owned(),
                    ..lumen_core::TextNode::default()
                })),
                ..lumen_core::NodePatch::default()
            },
        }],
    };
    let undone = session.compile_block_with_history("undo(\"fix\")", Some(&history));
    assert!(undone.halted_at.is_none(), "{:#?}", undone.diagnostics);
    assert_eq!(undone.operations.len(), 1);

    // Unknown label diagnoses precisely.
    let missing = session.compile_block_with_history("undo(\"nope\")", Some(&history));
    assert_eq!(missing.halted_at.as_ref().unwrap().code, "LUMD0917");
}

const REPLACE_BLOCK_SCENE: &str = "page page_a4\n  hero fr p(0,0) s(800,600)\n    visual fr p(10,10) s(200,200)\n      caption text \"Old\" p(0,0) s(100,hug)\n    cta text \"Go\" p(0,0) s(80,hug)";

#[test]
fn block_replace_swaps_inline_subtree_at_target_position() {
    let source = format!(
        "{REPLACE_BLOCK_SCENE}\n\nreplace(visual)\n  visual_v2 fr p(40,40) s(300,300)\n    headline text \"New hero copy\" p(0,0) s(200,hug)"
    );
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_blockrep"), "Doc");
    let output = compile_dsl_into_scene(&source, &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(!scene.nodes.contains_key(&NodeId::from("visual")));
    assert!(!scene.nodes.contains_key(&NodeId::from("caption")));
    // Replacement root takes the old target's parent and index.
    assert_eq!(
        scene.nodes[&NodeId::from("hero")].children,
        vec![NodeId::from("visual_v2"), NodeId::from("cta")]
    );
    assert_eq!(
        scene.nodes[&NodeId::from("visual_v2")].children,
        vec![NodeId::from("headline")]
    );
}

#[test]
fn block_replace_preserves_slots_when_requested() {
    let source = format!(
        "{}\n\nreplace(caption, slots:preserve)\n  caption_v2 text \"New caption\" p(0,0) s(100,hug)",
        REPLACE_BLOCK_SCENE.replace(
            "caption text \"Old\" p(0,0) s(100,hug)",
            "caption text \"Old\" p(0,0) s(100,hug) slot(campaign.caption)"
        )
    );
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_blockrep2"), "Doc");
    let output = compile_dsl_into_scene(&source, &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert_eq!(
        scene
            .slot_by_key(&lumen_core::SlotKey::from("campaign.caption"))
            .unwrap()
            .bound_nodes,
        vec![NodeId::from("caption_v2")]
    );
}

#[test]
fn block_replace_rejects_multiple_roots_atomically() {
    let source = format!(
        "{REPLACE_BLOCK_SCENE}\n\nreplace(visual)\n  first fr p(0,0) s(10,10)\n  second fr p(0,0) s(10,10)"
    );
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_blockrep3"), "Doc");
    let output = compile_dsl_into_scene(&source, &mut scene);

    assert_eq!(
        output.compile_output.halted_at.as_ref().unwrap().code,
        "LUMD0914"
    );
    // The whole block rolled back: no staged nodes, target untouched.
    let ops = &output.compile_output.operations;
    assert!(!ops.iter().any(|operation| matches!(
        operation,
        Operation::InsertNode { node, .. } if node.id == NodeId::from("first")
    )));
}

#[test]
fn block_replace_without_subtree_halts() {
    let source = format!("{REPLACE_BLOCK_SCENE}\n\nreplace(visual)");
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_blockrep4"), "Doc");
    let output = compile_dsl_into_scene(&source, &mut scene);
    assert_eq!(
        output.compile_output.halted_at.as_ref().unwrap().code,
        "LUMD0914"
    );
    // Prior creation lines survive the halt; the target is never removed.
    let ops = &output.compile_output.operations;
    assert!(ops.iter().any(|operation| matches!(
        operation,
        Operation::InsertNode { node, .. } if node.id == NodeId::from("visual")
    )));
    assert!(!ops.iter().any(|operation| matches!(
        operation,
        Operation::RemoveNode { node_id } if node_id == &NodeId::from("visual")
    )));
}

// --- Effects Contract V0, slice X3: effect-aware modify language ---

#[test]
fn dsl_creation_lowers_advanced_stroke_and_shadow() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_fx"), "Effects");
    let output = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  card r p(24,24) s(200,120) fill(#ffffff) stroke(stroke_border,#111827,w(1),dash(6,4),cap(round),join(round),align(inside)) shadow(shadow_soft,#000000,o(0.18),x(0),y(8),blur(24),spread(0))
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let card = &scene.nodes[&NodeId::from("card")];
    assert_eq!(card.strokes.len(), 1);
    let stroke = &card.strokes[0];
    assert_eq!(stroke.id, lumen_core::PaintId::from("stroke_border"));
    assert_eq!(stroke.width, 1.0);
    assert_eq!(stroke.dash, Some(vec![6.0, 4.0]));
    assert_eq!(stroke.cap, lumen_core::StrokeCap::Round);
    assert_eq!(stroke.join, lumen_core::StrokeJoin::Round);
    assert_eq!(stroke.align, lumen_core::StrokeAlign::Inside);

    assert_eq!(card.effects.len(), 1);
    let effect = &card.effects[0];
    assert_eq!(effect.id, lumen_core::EffectId::from("shadow_soft"));
    let lumen_core::EffectKind::DropShadow {
        color,
        opacity,
        x,
        y,
        blur,
        spread,
        color_token,
    } = &effect.kind;
    assert_eq!(
        color,
        &Color::Hex {
            value: "#000000".to_owned()
        }
    );
    assert_eq!(*opacity, 0.18);
    assert_eq!(*x, 0.0);
    assert_eq!(*y, 8.0);
    assert_eq!(*blur, 24.0);
    assert_eq!(*spread, 0.0);
    assert_eq!(color_token, &None);
}

#[test]
fn dsl_positional_css_shadow_alias_compiles() {
    // Models reach for CSS `box-shadow` ordering — `shadow(x, y, blur, color)`
    // with the color LAST — out of habit. The compiler accepts it as a
    // compatibility alias instead of failing Phase A repair with "invalid color".
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_fx"), "Effects");
    let output = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  card r p(24,24) s(200,120) fill(#ffffff) shadow(0,4,16,#19000000)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let card = &scene.nodes[&NodeId::from("card")];
    assert_eq!(card.effects.len(), 1);
    let lumen_core::EffectKind::DropShadow {
        color,
        opacity,
        x,
        y,
        blur,
        spread,
        ..
    } = &card.effects[0].kind;
    // The alpha rides in the color (input #AARRGGBB `#19000000` ~10% black,
    // normalized to canonical #RRGGBBAA); opacity stays the channel default.
    assert_eq!(
        color,
        &Color::Hex {
            value: "#00000019".to_owned()
        }
    );
    assert_eq!(*opacity, 1.0);
    assert_eq!(*x, 0.0);
    assert_eq!(*y, 4.0);
    assert_eq!(*blur, 16.0);
    assert_eq!(*spread, 0.0);
}

#[test]
fn dsl_rgba_color_alias_compiles_in_fill_and_positional_shadow() {
    // Models reach for CSS `rgb()`/`rgba()` colors out of habit. The compiler
    // lowers them to canonical hex instead of failing with LUMD0219. This also
    // covers the exact slip the agent emitted: a positional shadow whose trailing
    // color is `rgba(...)` — `shadow(0,4,24,rgba(0,0,0,0.10))`.
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_fx"), "Effects");
    let output = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  card r p(24,24) s(200,120) fill(rgba(0,137,123,1)) shadow(0,4,24,rgba(0,0,0,0.10))
  plate r p(24,160) s(200,80) fill(rgb(240,244,247))
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let card = &scene.nodes[&NodeId::from("card")];
    // rgba(0,137,123,1) is fully opaque -> 6-digit hex.
    assert!(matches!(
        &card.fills[0].paint,
        Paint::Solid { color: Color::Hex { value } } if value == "#00897b"
    ));
    // The trailing rgba is recognized as the positional shadow color; 0.10 alpha
    // -> 0x1a, lowered to #RRGGBBAA.
    assert_eq!(card.effects.len(), 1);
    let lumen_core::EffectKind::DropShadow {
        color, x, y, blur, ..
    } = &card.effects[0].kind;
    assert_eq!(
        color,
        &Color::Hex {
            value: "#0000001a".to_owned()
        }
    );
    assert_eq!(*x, 0.0);
    assert_eq!(*y, 4.0);
    assert_eq!(*blur, 24.0);

    let plate = &scene.nodes[&NodeId::from("plate")];
    assert!(matches!(
        &plate.fills[0].paint,
        Paint::Solid { color: Color::Hex { value } } if value == "#f0f4f7"
    ));
}

#[test]
fn dsl_idful_shadow_form_is_not_confused_with_positional_alias() {
    // `shadow(shadow_soft, #000000, ...)` keeps the leading-id grammar: the
    // first arg is a non-numeric id, so the positional alias must not fire.
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_fx"), "Effects");
    let output = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  card r p(24,24) s(200,120) shadow(shadow_soft,#000000,o(0.2),y(8),blur(24))
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    let card = &scene.nodes[&NodeId::from("card")];
    assert_eq!(card.effects.len(), 1);
    assert_eq!(
        card.effects[0].id,
        lumen_core::EffectId::from("shadow_soft")
    );
}

#[test]
fn dsl_basic_stroke_form_keeps_working() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_fx"), "Effects");
    let output = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  card r p(24,24) s(200,120) stroke(#111827,2)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    let stroke = &scene.nodes[&NodeId::from("card")].strokes[0];
    assert_eq!(
        stroke.id,
        lumen_core::PaintId::from("paint_card_stroke_1"),
        "id-less strokes keep the deterministic paint-id policy"
    );
    assert_eq!(stroke.width, 2.0);
    assert_eq!(stroke.dash, None);
    assert_eq!(stroke.cap, lumen_core::StrokeCap::Butt);
}

#[test]
fn dsl_idless_shadow_gets_deterministic_effect_id() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_fx"), "Effects");
    let output = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  card r p(24,24) s(200,120) shadow(#000000,o(0.2),y(4),blur(12)) shadow(#111827,o(0.1),y(1),blur(2))
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    let card = &scene.nodes[&NodeId::from("card")];
    assert_eq!(card.effects.len(), 2);
    assert_eq!(
        card.effects[0].id,
        lumen_core::EffectId::from("effect_card_shadow_1")
    );
    assert_eq!(
        card.effects[1].id,
        lumen_core::EffectId::from("effect_card_shadow_2")
    );
}

#[test]
fn dsl_shadow_modify_upserts_by_id_and_remove_effect_removes() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_fx"), "Effects");
    let setup = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  card r p(24,24) s(200,120) shadow(shadow_soft,#000000,o(0.18),y(8),blur(24))
"#,
        &mut scene,
    );
    assert!(setup.compile_output.halted_at.is_none());

    // Same id: updates in place, preserving stack length.
    let update = compile_dsl_into_scene(
        "#card shadow(shadow_soft,#000000,o(0.3),y(12),blur(32))",
        &mut scene,
    );
    assert_no_dsl_errors(&update.compile_output.diagnostics);
    assert!(update.operation_error.is_none());
    let card = &scene.nodes[&NodeId::from("card")];
    assert_eq!(card.effects.len(), 1);
    let lumen_core::EffectKind::DropShadow { opacity, blur, .. } = &card.effects[0].kind;
    assert_eq!(*opacity, 0.3);
    assert_eq!(*blur, 32.0);

    // New id: appends to the stack top.
    let add = compile_dsl_into_scene(
        "#card shadow(shadow_crisp,#111827,o(0.08),y(1),blur(2))",
        &mut scene,
    );
    assert_no_dsl_errors(&add.compile_output.diagnostics);
    assert_eq!(scene.nodes[&NodeId::from("card")].effects.len(), 2);

    // remove_effect removes only the addressed entry.
    let remove = compile_dsl_into_scene("#card remove_effect(shadow_soft)", &mut scene);
    assert_no_dsl_errors(&remove.compile_output.diagnostics);
    let card = &scene.nodes[&NodeId::from("card")];
    assert_eq!(card.effects.len(), 1);
    assert_eq!(
        card.effects[0].id,
        lumen_core::EffectId::from("shadow_crisp")
    );
}

#[test]
fn dsl_remove_effect_of_missing_id_halts_with_edit_error() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_fx"), "Effects");
    compile_dsl_into_scene(
        "page page_square size(400,400,px)\n  card r p(0,0) s(10,10)",
        &mut scene,
    );

    let output = compile_dsl_into_scene("#card remove_effect(missing)", &mut scene);
    assert!(output.compile_output.halted_at.is_some());
    assert!(output
        .compile_output
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.diagnostic.code == "LUMD0900"
            && diagnostic
                .diagnostic
                .message
                .contains("edit.target_not_found")));
    assert!(scene.nodes[&NodeId::from("card")].effects.is_empty());
}

#[test]
fn dsl_malformed_shadow_and_stroke_options_halt_with_diagnostics() {
    let shadow = compile_dsl(
        "page page_square size(400,400,px)\n  card r p(0,0) s(10,10) shadow(#000000,wat(3))",
    );
    assert_eq!(
        shadow.halted_at.as_ref().map(|halt| halt.code.as_str()),
        Some("LUMD0257")
    );

    let stroke = compile_dsl(
        "page page_square size(400,400,px)\n  card r p(0,0) s(10,10) stroke(#111827,w(1),cap(diagonal))",
    );
    assert_eq!(
        stroke.halted_at.as_ref().map(|halt| halt.code.as_str()),
        Some("LUMD0256")
    );

    let negative_dash = compile_dsl(
        "page page_square size(400,400,px)\n  card r p(0,0) s(10,10) stroke(#111827,w(1),dash(6,-4))",
    );
    assert_eq!(
        negative_dash
            .halted_at
            .as_ref()
            .map(|halt| halt.code.as_str()),
        Some("LUMD0256")
    );

    let missing_width = compile_dsl(
        "page page_square size(400,400,px)\n  card r p(0,0) s(10,10) stroke(#111827,dash(6,4))",
    );
    assert_eq!(
        missing_width
            .halted_at
            .as_ref()
            .map(|halt| halt.code.as_str()),
        Some("LUMD0211")
    );
}

#[test]
fn dsl_tokenized_shadow_color_records_color_token() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_fx"), "Effects");
    let output = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  card r p(24,24) s(200,120) shadow(shadow_brand,$shadow.soft,o(0.18),y(8),blur(24))
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    let lumen_core::EffectKind::DropShadow {
        color, color_token, ..
    } = &scene.nodes[&NodeId::from("card")].effects[0].kind;
    assert_eq!(
        color,
        &Color::Token {
            token: "shadow.soft".to_owned()
        }
    );
    assert_eq!(color_token.as_deref(), Some("shadow.soft"));
}

// --- Phase 4c: p()/s() on pinned (position_mode: absolute) nodes ---
//
// Pinned nodes lay out at their page-space `absolute_box`; the solver
// ignores `transform` entirely for them. Historically `#node p(x,y)` wrote
// `transform`, a silent visual no-op on exactly the nodes humans create by
// dragging. p()/s() now stay parent-relative in *meaning* but lower to
// `absolute_box` for pinned targets, computed against the parent's solved
// (page-space) layout bounds.

fn scene_with_pinned_badge(parent_origin: lumen_core::Rect, badge_box: lumen_core::Rect) -> Scene {
    use lumen_core::{ComputedGeometry, Node, Page, PageSize};

    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_pinned"), "Pinned");
    scene
        .apply_operation(Operation::AddPage {
            page: Page {
                id: PageId::from("page_a4"),
                name: "Page".to_owned(),
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

    let mut frame = Node::new(NodeId::from("panel"), NodeKind::Frame);
    frame.size = lumen_core::SizeSpec::fixed(400.0, 400.0);
    frame.transform.x = parent_origin.x;
    frame.transform.y = parent_origin.y;
    frame.computed = Some(ComputedGeometry {
        layout_bounds: parent_origin.clone(),
        render_bounds: parent_origin.clone(),
    });
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_a4")),
            index: 0,
            node: frame,
        })
        .unwrap();

    let mut badge = Node::new(NodeId::from("badge"), NodeKind::Rect);
    badge.size = lumen_core::SizeSpec::fixed(badge_box.width, badge_box.height);
    badge.position_mode = lumen_core::PositionMode::Absolute;
    badge.absolute_box = Some(badge_box.clone());
    badge.base_anchor = Some(badge_box);
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Node(NodeId::from("panel")),
            index: 0,
            node: badge,
        })
        .unwrap();

    scene
}

#[test]
fn pinned_node_position_lowers_to_absolute_box_not_transform() {
    // Parent panel sits at page (50,50); p() on a pinned child is PAGE-SPACE,
    // so the parent origin must NOT be added — the badge lands exactly at the
    // coordinates the model read off the brief/inspector (run_8e7b9f64).
    let mut scene = scene_with_pinned_badge(
        lumen_core::Rect {
            x: 50.0,
            y: 50.0,
            width: 400.0,
            height: 400.0,
        },
        lumen_core::Rect {
            x: 100.0,
            y: 200.0,
            width: 220.0,
            height: 48.0,
        },
    );
    let before_transform = scene.nodes[&NodeId::from("badge")].transform.clone();

    let output = compile_dsl_into_scene("#badge p(80,904)", &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let update = output
        .compile_output
        .operations
        .iter()
        .find_map(|operation| match operation {
            Operation::UpdateNode { node_id, patch } if *node_id == NodeId::from("badge") => {
                Some(patch)
            }
            _ => None,
        })
        .expect("badge UpdateNode present");
    assert_eq!(
        update.absolute_box,
        lumen_core::OptionalFieldPatch::Set(lumen_core::Rect {
            x: 80.0,
            y: 904.0,
            width: 220.0,
            height: 48.0,
        })
    );
    assert_eq!(update.transform, lumen_core::FieldPatch::Unchanged);

    let badge = &scene.nodes[&NodeId::from("badge")];
    assert_eq!(
        badge.absolute_box,
        Some(lumen_core::Rect {
            x: 80.0,
            y: 904.0,
            width: 220.0,
            height: 48.0,
        })
    );
    // transform must be untouched: pinned moves never write it.
    assert_eq!(badge.transform, before_transform);

    // Re-running layout must place the node at the new box (zero-motion:
    // the solver lays a pinned node out exactly at its absolute_box).
    let operations = lumen_core::layout_operations(&scene, lumen_core::LayoutOptions::default());
    scene.apply_operations(operations).unwrap();
    let placed = scene.nodes[&NodeId::from("badge")]
        .computed
        .as_ref()
        .unwrap()
        .layout_bounds
        .clone();
    assert_eq!(placed.x, 80.0);
    assert_eq!(placed.y, 904.0);
}

#[test]
fn pinned_node_position_and_size_together_updates_absolute_box_and_size() {
    let mut scene = scene_with_pinned_badge(
        lumen_core::Rect {
            x: 50.0,
            y: 50.0,
            width: 400.0,
            height: 400.0,
        },
        lumen_core::Rect {
            x: 100.0,
            y: 200.0,
            width: 220.0,
            height: 48.0,
        },
    );

    let output = compile_dsl_into_scene("#badge p(80,904) s(200,40)", &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let badge = &scene.nodes[&NodeId::from("badge")];
    assert_eq!(
        badge.absolute_box,
        Some(lumen_core::Rect {
            x: 80.0,
            y: 904.0,
            width: 200.0,
            height: 40.0,
        })
    );
    assert_eq!(badge.size, lumen_core::SizeSpec::fixed(200.0, 40.0));
}

#[test]
fn pinned_node_on_page_parent_treats_position_as_page_space() {
    use lumen_core::Node;

    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_pinned_page"), "Pinned");
    scene
        .apply_operation(Operation::AddPage {
            page: lumen_core::Page {
                id: PageId::from("page_a4"),
                name: "Page".to_owned(),
                size: lumen_core::PageSize {
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

    let mut badge = Node::new(NodeId::from("badge"), NodeKind::Rect);
    badge.size = lumen_core::SizeSpec::fixed(220.0, 48.0);
    badge.position_mode = lumen_core::PositionMode::Absolute;
    badge.absolute_box = Some(lumen_core::Rect {
        x: 100.0,
        y: 200.0,
        width: 220.0,
        height: 48.0,
    });
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_a4")),
            index: 0,
            node: badge,
        })
        .unwrap();

    let output = compile_dsl_into_scene("#badge p(80,904)", &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    let badge = &scene.nodes[&NodeId::from("badge")];
    assert_eq!(
        badge.absolute_box,
        Some(lumen_core::Rect {
            x: 80.0,
            y: 904.0,
            width: 220.0,
            height: 48.0,
        })
    );
}

#[test]
fn pinned_node_move_needs_no_parent_computed_geometry() {
    // Page-space p() reads nothing from the parent, so a pinned move must
    // compile even when no layout pass has populated `computed` yet (the old
    // parent-relative lowering errored here with LUMD0918).
    use lumen_core::Node;

    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_pinned_nogeo"), "Pinned");
    scene
        .apply_operation(Operation::AddPage {
            page: lumen_core::Page {
                id: PageId::from("page_a4"),
                name: "Page".to_owned(),
                size: lumen_core::PageSize {
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

    // Parent frame has no `computed` geometry (no layout pass ran yet).
    let mut frame = Node::new(NodeId::from("panel"), NodeKind::Frame);
    frame.size = lumen_core::SizeSpec::fixed(400.0, 400.0);
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_a4")),
            index: 0,
            node: frame,
        })
        .unwrap();

    let mut badge = Node::new(NodeId::from("badge"), NodeKind::Rect);
    badge.size = lumen_core::SizeSpec::fixed(220.0, 48.0);
    badge.position_mode = lumen_core::PositionMode::Absolute;
    badge.absolute_box = Some(lumen_core::Rect {
        x: 100.0,
        y: 200.0,
        width: 220.0,
        height: 48.0,
    });
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Node(NodeId::from("panel")),
            index: 0,
            node: badge,
        })
        .unwrap();

    let output = compile_dsl_into_scene("#badge p(80,904)", &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());
    assert_eq!(
        scene.nodes[&NodeId::from("badge")].absolute_box,
        Some(lumen_core::Rect {
            x: 80.0,
            y: 904.0,
            width: 220.0,
            height: 48.0,
        })
    );
}

#[test]
fn pinned_node_non_fixed_size_is_a_compile_error() {
    let mut scene = scene_with_pinned_badge(
        lumen_core::Rect {
            x: 50.0,
            y: 50.0,
            width: 400.0,
            height: 400.0,
        },
        lumen_core::Rect {
            x: 100.0,
            y: 200.0,
            width: 220.0,
            height: 48.0,
        },
    );

    let output = compile_dsl_into_scene("#badge s(fill,hug)", &mut scene);

    assert_eq!(
        output
            .compile_output
            .halted_at
            .as_ref()
            .map(|halt| halt.code.as_str()),
        Some("LUMD0919")
    );
}

#[test]
fn non_pinned_node_position_still_lowers_to_transform() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_managed"), "Managed");
    let first = compile_dsl_into_scene("page page_a4\n  badge rect p(0,0) s(220,48)", &mut scene);
    assert_no_dsl_errors(&first.compile_output.diagnostics);

    let output = compile_dsl_into_scene("#badge p(80,904)", &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    let update = output
        .compile_output
        .operations
        .iter()
        .find_map(|operation| match operation {
            Operation::UpdateNode { node_id, patch } if *node_id == NodeId::from("badge") => {
                Some(patch)
            }
            _ => None,
        })
        .expect("badge UpdateNode present");
    assert_eq!(
        update.transform,
        lumen_core::FieldPatch::Set(lumen_core::Transform {
            x: 80.0,
            y: 904.0,
            ..scene.nodes[&NodeId::from("badge")].transform.clone()
        })
    );
    assert_eq!(
        update.absolute_box,
        lumen_core::OptionalFieldPatch::Unchanged
    );
    assert_eq!(scene.nodes[&NodeId::from("badge")].transform.x, 80.0);
    assert_eq!(scene.nodes[&NodeId::from("badge")].transform.y, 904.0);
}

#[test]
fn node_edit_patch_wire_format_omits_absolute_box_when_unchanged() {
    let patch = lumen_core::NodeEditPatch {
        name: lumen_core::OptionalFieldPatch::Set("Renamed".to_owned()),
        ..lumen_core::NodeEditPatch::default()
    };
    let json = serde_json::to_string(&patch).unwrap();
    assert!(
        !json.contains("absolute_box"),
        "unchanged absolute_box must be omitted from the wire format: {json}"
    );
}
