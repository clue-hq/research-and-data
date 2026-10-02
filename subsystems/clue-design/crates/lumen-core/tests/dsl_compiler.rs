use lumen_core::validation::validate_scene;
use lumen_core::{
    compile_dsl, compile_dsl_into_scene, compile_dsl_into_scene_with_session_and_protected,
    normalize_dsl, parse_dsl, Color, DiagnosticSeverity, Dimension, DslCompileSession,
    DslLayoutAnchor, DslLayoutAxis, DslLineKind, DslProperty, DslScalar, LayoutAnchor, NodeId,
    NodeKind, Operation, Orientation, PageId, PagePreset, Paint, ParentRef, PhysicalUnit, Scene,
    SlotKey, TextDirection, TextWrap, Unit, VerticalAlign,
};
use std::collections::BTreeSet;

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
fn dsl_valign_lowers_to_text_node_on_create() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_valign"), "Valign");
    let output = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  band text "Centered band" p(0,0) s(fill,200) align(center) valign(center)
  footer text "Bottom" p(0,220) s(fill,120) valign(bottom)
  top text "Top default" p(0,0) s(fill,80)
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let NodeKind::Text(band) = &scene.nodes[&NodeId::from("band")].kind else {
        panic!("expected text node");
    };
    assert_eq!(band.valign, VerticalAlign::Center);
    let NodeKind::Text(footer) = &scene.nodes[&NodeId::from("footer")].kind else {
        panic!("expected text node");
    };
    assert_eq!(footer.valign, VerticalAlign::Bottom);
    let NodeKind::Text(top) = &scene.nodes[&NodeId::from("top")].kind else {
        panic!("expected text node");
    };
    assert_eq!(top.valign, VerticalAlign::Top);
}

#[test]
fn dsl_modify_line_updates_valign() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_valign_mod"), "ValignMod");
    let first = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  band text "Band" p(0,0) s(fill,200)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&first.compile_output.diagnostics);

    let second = compile_dsl_into_scene(r#"#band valign(bottom)"#, &mut scene);
    assert_no_dsl_errors(&second.compile_output.diagnostics);
    assert!(second.operation_error.is_none());

    let NodeKind::Text(band) = &scene.nodes[&NodeId::from("band")].kind else {
        panic!("expected text node");
    };
    assert_eq!(band.valign, VerticalAlign::Bottom);
}

#[test]
fn dsl_rejects_valign_middle_value_with_no_alias() {
    // D2: no aliases — `middle` fails loudly with the standard value diagnostic.
    let output = compile_dsl(
        r#"
page page_square size(400,400,px)
  band text "Band" p(0,0) s(fill,200) valign(middle)
"#,
    );
    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0275");
}

#[test]
fn dsl_rejects_valign_wrong_arity() {
    let output = compile_dsl(
        r#"
page page_square size(400,400,px)
  band text "Band" p(0,0) s(fill,200) valign(top,center)
"#,
    );
    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0230");
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
fn solid_opacity_argument_lowers_into_the_color_alpha() {
    // A4 retires the LUMD0241 halt: `solid(color, opacity)` multiplies the
    // opacity into the color's alpha at model-build time.
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_solid"), "Solid");
    let output = compile_dsl_into_scene(
        r#"
page page_a4
  card frame p(0,0) s(100,100) fill(solid(#ffffff,o(0.5)))
"#,
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());
    let card = &scene.nodes[&NodeId::from("card")];
    assert_eq!(card.fills.len(), 1);
    // 0.5 * 0xff = 127.5 -> rounds to 0x80.
    assert_eq!(
        card.fills[0].paint,
        Paint::Solid {
            color: Color::Hex {
                value: "#ffffff80".to_owned()
            }
        }
    );
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
    include_marks: false,
    imposition: None,
    proof: false,
    color: None,
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
    } = &effect.kind
    else {
        panic!("expected drop shadow");
    };
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
    } = &card.effects[0].kind
    else {
        panic!("expected drop shadow");
    };
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
    } = &card.effects[0].kind
    else {
        panic!("expected drop shadow");
    };
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
    let lumen_core::EffectKind::DropShadow { opacity, blur, .. } = &card.effects[0].kind else {
        panic!("expected drop shadow");
    };
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
    } = &scene.nodes[&NodeId::from("card")].effects[0].kind
    else {
        panic!("expected drop shadow");
    };
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
        text_lines: Vec::new(),
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

// ---------------------------------------------------------------------------
// LUMD0206 double-trap compiler-ergonomics fixes (F1 / F2 / F3).
//
// A live agent run (run_5daea3965dd641bbba1c6e5e1241ef6a) burned three
// iterations on a ship-grade design because the LUMD0206 halt was atomic and
// its hint steered the model into a worse failure. The fixtures below are the
// EXACT model output from iterations 001 and 002; they must now compile.
// ---------------------------------------------------------------------------

/// Iteration 001 verbatim: line 1 is model narration, everything after it is a
/// complete, valid subtree targeting the existing empty page via `#page:`.
const LUMD0206_ITER1: &str = concat!(
    "page_custom_artboard is empty (zero nodes) — my canvas. I'll open with a `#page:` line and author the subtree. Split idiom: full-bleed product hero image top, brand band below carrying logo + copy + CTA. The hero image already has a baked-in label so text over it isn't needed; keep copy on the solid band (no scrim needed).\n",
    "\n",
    "#page:page_custom_artboard size(1080,1080,px)\n",
    "  artboard al(v, x(s), g(0), pad(0)) p(0,0) s(fill,fill) fill($surface.page) clip(true)\n",
    "    hero fr p(0,0) s(1080,560) clip(true) fill($surface.inverse)\n",
    "      photo image asset(asset_ing_631ad93878fc572f) p(0,0) s(1080,560)\n",
    "    band al(v, x(s), y(c), g($space.stack.default), pad(72,80)) p(0,0) s(1080,fill) fill($surface.brand)\n",
    "      logo image asset(asset_bbd6b7b8e2f2) p(0,0) s(280,42)\n",
    "      eyebrow text \"NOW AVAILABLE\" p(0,0) s(920,hug) style($type.eyebrow) fill($text.inverse) wrap_text(true) max_lines(1) slot(campaign.eyebrow)\n",
    "      headline text \"Meet your AI documentation assistant.\" p(0,0) s(920,hug) style($type.headline) font_size($type.size.6xl) lh(1.05) fill($text.inverse) wrap_text(true) max_lines(2) slot(campaign.headline)\n",
    "      subtitle text \"Scribe drafts your clinical notes automatically, so you can focus on patients.\" p(0,0) s(860,hug) style($type.body) font_size($type.size.lg) lh(1.4) fill($text.inverse) wrap_text(true) max_lines(3) slot(offer.primary_message)\n",
    "      cta al(h, x(c), y(c), pad(18,40)) p(0,0) s(320,72) fill($surface.inverse) rd($radius.button)\n",
    "        cta_text text \"Book a Demo\" p(0,0) s(fill,hug) align(center) style($type.cta) fill($text.inverse) max_lines(1) slot(campaign.cta)\n",
    "  #slot:campaign.eyebrow sample(\"NOW AVAILABLE\") worst_case(\"NOW AVAILABLE\")\n",
    "  #slot:campaign.headline sample(\"Meet your AI documentation assistant.\") worst_case(\"Meet your AI documentation assistant.\")\n",
    "  #slot:offer.primary_message sample(\"Scribe drafts your clinical notes automatically, so you can focus on patients.\") worst_case(\"Scribe drafts your clinical notes automatically, so you can focus on patients.\")\n",
    "  #slot:campaign.cta sample(\"Book a Demo\") worst_case(\"Book a Demo\")\n",
);

/// Iteration 002 verbatim: line 1 is a BARE `page_custom_artboard size(...)`
/// opener — the narration was deleted along with the `#page:` prefix.
const LUMD0206_ITER2: &str = concat!(
    "page_custom_artboard size(1080,1080,px)\n",
    "  artboard al(v, x(s), g(0), pad(0)) p(0,0) s(fill,fill) fill($surface.page) clip(true)\n",
    "    hero fr p(0,0) s(1080,560) clip(true) fill($surface.inverse)\n",
    "      photo image asset(asset_ing_631ad93878fc572f) p(0,0) s(1080,560)\n",
    "    band al(v, x(s), y(c), g($space.stack.default), pad(72,80)) p(0,0) s(1080,fill) fill($surface.brand)\n",
    "      logolock al(h, x(s), y(c), g(0), pad(16,24)) p(0,0) s(320,74) fill($surface.page) rd($radius.card)\n",
    "        logo image asset(asset_bbd6b7b8e2f2) p(0,0) s(272,40)\n",
    "      eyebrow text \"INTRODUCING\" p(0,0) s(920,hug) style($type.eyebrow) fill($text.inverse) wrap_text(true) max_lines(1) slot(campaign.eyebrow)\n",
    "      headline text \"Meet your AI documentation assistant.\" p(0,0) s(920,hug) style($type.headline) font_size($type.size.5xl) lh(1.06) fill($text.inverse) wrap_text(true) max_lines(2) slot(campaign.headline)\n",
    "      subtitle text \"Scribe drafts clinical notes automatically, so you can focus on patients.\" p(0,0) s(860,hug) style($type.body) font_size($type.size.lg) lh(1.4) fill($text.inverse) wrap_text(true) max_lines(3) slot(offer.primary_message)\n",
    "      cta al(h, x(c), y(c), pad(18,40)) p(0,0) s(320,72) fill($surface.inverse) rd($radius.button)\n",
    "        cta_text text \"Book a Demo\" p(0,0) s(fill,hug) align(center) style($type.cta) fill($text.inverse) max_lines(1) slot(campaign.cta)\n",
    "  #slot:campaign.eyebrow sample(\"INTRODUCING\") worst_case(\"INTRODUCING\")\n",
    "  #slot:campaign.headline sample(\"Meet your AI documentation assistant.\") worst_case(\"Meet your AI documentation assistant.\")\n",
    "  #slot:offer.primary_message sample(\"Scribe drafts clinical notes automatically, so you can focus on patients.\") worst_case(\"Scribe drafts clinical notes automatically, so you can focus on patients.\")\n",
    "  #slot:campaign.cta sample(\"Book a Demo\") worst_case(\"Book a Demo\")\n",
);

fn scene_with_empty_custom_artboard() -> Scene {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_ergo"), "Ergo");
    let seed = compile_dsl_into_scene("page page_custom_artboard size(1080,1080,px)", &mut scene);
    assert_no_dsl_errors(&seed.compile_output.diagnostics);
    assert!(scene.pages[&PageId::from("page_custom_artboard")]
        .children
        .is_empty());
    scene
}

fn assert_hero_and_logo_present(scene: &Scene) {
    let photo = scene
        .nodes
        .get(&NodeId::from("photo"))
        .expect("hero photo node must exist");
    match &photo.kind {
        NodeKind::Image(image) => assert_eq!(
            image.asset_id,
            lumen_core::AssetId::from("asset_ing_631ad93878fc572f")
        ),
        other => panic!("photo node must be an image, got {other:?}"),
    }
    let logo = scene
        .nodes
        .get(&NodeId::from("logo"))
        .expect("logo node must exist");
    match &logo.kind {
        NodeKind::Image(image) => assert_eq!(
            image.asset_id,
            lumen_core::AssetId::from("asset_bbd6b7b8e2f2")
        ),
        other => panic!("logo node must be an image, got {other:?}"),
    }
}

/// F2 — leading-narration tolerance. Iteration 001 opens with a prose line
/// then a valid `#page:` subtree; the narration is skipped with a LUMD0260
/// warning instead of halting, and the whole design lands.
#[test]
fn lumd0206_leading_narration_is_skipped_and_design_lands() {
    let mut scene = scene_with_empty_custom_artboard();
    let output = compile_dsl_into_scene(LUMD0206_ITER1, &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());
    assert!(output.compile_output.halted_at.is_none());
    assert!(
        output
            .compile_output
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.diagnostic.code == "LUMD0260"),
        "the narration line must be reported as a LUMD0260 warning, not silently dropped: {:#?}",
        output.compile_output.diagnostics
    );
    assert!(
        !output.compile_output.operations.is_empty(),
        "the valid subtree after the narration must produce operations"
    );
    assert_hero_and_logo_present(&scene);
}

/// F1 — bare known-page-id normalization. Iteration 002 opens with a bare
/// `page_custom_artboard size(...)` line; it is rewritten into a `#page:`
/// modification (LUMD0259) and routes through the empty-page compose path.
#[test]
fn lumd0206_bare_known_page_id_is_normalized_and_design_lands() {
    let mut scene = scene_with_empty_custom_artboard();
    let output = compile_dsl_into_scene(LUMD0206_ITER2, &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());
    assert!(output.compile_output.halted_at.is_none());
    assert!(
        output
            .compile_output
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.diagnostic.code == "LUMD0259"),
        "the bare page reference must be reported as a LUMD0259 warning: {:#?}",
        output.compile_output.diagnostics
    );
    assert!(!output.compile_output.operations.is_empty());
    assert_hero_and_logo_present(&scene);
}

/// F1 precedence over F2: a leading bare KNOWN page id is normalized (LUMD0259),
/// never skipped as narration (LUMD0260).
#[test]
fn lumd0206_f1_takes_precedence_over_f2_for_bare_known_page_id() {
    let mut scene = scene_with_empty_custom_artboard();
    let output =
        compile_dsl_into_scene("page_custom_artboard size(1080,1080,px)", &mut scene);

    let codes: Vec<&str> = output
        .compile_output
        .diagnostics
        .iter()
        .map(|diagnostic| diagnostic.diagnostic.code.as_str())
        .collect();
    assert!(
        codes.contains(&"LUMD0259"),
        "bare known page id must be normalized (F1): {codes:?}"
    );
    assert!(
        !codes.contains(&"LUMD0260"),
        "F1 must win over F2 — no narration skip: {codes:?}"
    );
    assert!(output.compile_output.halted_at.is_none());
}

/// F2 bounds: a block of 4+ narration-only lines (no structural line ever
/// parses) halts with LUMD0206 exactly as before — zero operations, and the
/// tentative skip warnings are dropped so it fails cleanly.
#[test]
fn lumd0206_four_narration_lines_still_halt() {
    let garbage = concat!(
        "this is the first line of prose I wrote\n",
        "still explaining what I intend to do here\n",
        "and yet more narration about the layout\n",
        "one more sentence that is not DSL at all\n",
    );
    let output = compile_dsl(garbage);

    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0206");
    assert!(
        output.operations.is_empty(),
        "a pure-narration block must apply zero operations"
    );
    assert!(
        !output
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.diagnostic.code == "LUMD0260"),
        "a genuinely failing block must not leave warnings-instead-of-error: {:#?}",
        output.diagnostics
    );
    assert!(output.has_errors());
}

/// The skip is leading-lines-only: an unknown-element line AFTER a structural
/// line has parsed still halts with LUMD0206.
#[test]
fn lumd0206_mid_block_unknown_element_still_halts() {
    let source = concat!(
        "page page_a4\n",
        "  hero fr p(0,0) s(400,400) fill($surface.brand)\n",
        "  prose narration sneaking in after a real element\n",
    );
    let output = compile_dsl(source);

    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0206");
    assert!(
        !output
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.diagnostic.code == "LUMD0260"),
        "a mid-block failure must not be skipped as narration: {:#?}",
        output.diagnostics
    );
}

/// F3 — an UNKNOWN bare page id matches no known page, so it still fails
/// LUMD0206, and the amended hint now points at the `#page:` form.
#[test]
fn lumd0206_unknown_bare_page_id_fails_with_amended_hint() {
    let mut scene = scene_with_empty_custom_artboard();
    let output = compile_dsl_into_scene("page_nonexistent size(1080,1080,px)", &mut scene);

    let halt = output.compile_output.halted_at.as_ref().unwrap();
    assert_eq!(halt.code, "LUMD0206");
    let diagnostic = output
        .compile_output
        .diagnostics
        .iter()
        .find(|diagnostic| diagnostic.diagnostic.code == "LUMD0206")
        .expect("LUMD0206 diagnostic must be present");
    let hint = diagnostic
        .diagnostic
        .hint
        .as_ref()
        .expect("LUMD0206 must carry a hint");
    assert!(
        hint.contains("#page:<page_id>"),
        "the amended hint must point at the #page: form: {hint}"
    );
}

/// Review refinement: the garbage-block guard keys on "zero PARSED lines", not
/// "zero structural lines" — a narration-led block of ONLY `#node prop(...)`
/// modifications (the repair-iteration shape, the single most common narration
/// leak site) must compile with the LUMD0260 warning, not die on the restored
/// halt.
#[test]
fn lumd0206_narration_led_modification_only_repair_block_compiles() {
    let mut scene = scene_with_empty_custom_artboard();
    let seed = compile_dsl_into_scene(
        concat!(
            "#page:page_custom_artboard size(1080,1080,px)\n",
            "  artboard al(v, x(s), g(0), pad(0)) p(0,0) s(fill,fill) clip(true)\n",
            "    headline text \"Hello\" p(0,0) s(400,hug) font(\"Inter\",32,700,left)\n",
        ),
        &mut scene,
    );
    assert!(seed.compile_output.halted_at.is_none());

    let repair = concat!(
        "The headline overflows its band, so I will simply raise its size cap.\n",
        "#headline font_size(48)\n",
    );
    let output = compile_dsl_into_scene(repair, &mut scene);

    assert!(
        output.compile_output.halted_at.is_none(),
        "a narration-led modification-only repair block must compile: {:#?}",
        output.compile_output.halted_at
    );
    assert!(
        output
            .compile_output
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.diagnostic.code == "LUMD0260"),
        "the narration line must be reported, never silently dropped: {:#?}",
        output.compile_output.diagnostics
    );
    assert!(
        !output.compile_output.operations.is_empty(),
        "the modification after the narration must produce operations"
    );
}

// ---------------------------------------------------------------------------
// Modify-path kit-asset swap (Slice 2 D1). A `#node ... asset(X)` line that
// swaps an image node to an asset the scene has not registered yet used to
// hard-fail (LUMD0900 → PlaceAssetInNode requires the record), even though the
// declaration path tolerates the same dangling reference. D1 degrades the
// modify path to declaration semantics for a LEAF node and warns LUMD0261.
// ---------------------------------------------------------------------------

/// A minimal REGISTERED raster asset record, decoded so the scene can carry it
/// verbatim (mirrors assets_pipeline.rs `decode_asset`).
fn registered_raster_asset(id: &str, label: &str) -> lumen_core::AssetRecord {
    serde_json::from_str(&format!(
        r#"{{
            "id": "{id}",
            "label": "{label}",
            "kind": "raster_image",
            "status": "ready",
            "source": {{ "kind": "uploaded", "filename": "x.png", "uploaded_by": "t" }},
            "media": {{ "mime_type": "image/png" }},
            "raster": {{ "pixel_width": 1080, "pixel_height": 560 }}
        }}"#
    ))
    .unwrap()
}

/// Base scene: page → `hero` frame → `hero_img` leaf image already carrying a
/// DIFFERENT registered asset with populated placement provenance + alt, so a
/// swap has real state to clear. The dashboard asset is NOT in scene.assets.
fn seed_hero_scene() -> Scene {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_hero_swap"), "Hero");
    let seed = compile_dsl_into_scene(
        r#"
page page_hero size(1080,560,px)
  hero frame p(0,0) s(1080,560)
    hero_img image asset(asset_existing_hero) p(0,0) s(1080,560)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&seed.compile_output.diagnostics);

    // Register a DIFFERENT asset and place it into hero_img so the base node
    // carries source_asset_id / asset_placement / alt (from the label).
    scene
        .apply_operation(Operation::UpsertAsset {
            asset: registered_raster_asset("asset_existing_hero", "Old hero photo"),
        })
        .unwrap();
    scene
        .apply_operation(Operation::PlaceAssetInNode {
            node_id: NodeId::from("hero_img"),
            asset_id: lumen_core::AssetId::from("asset_existing_hero"),
            placement: lumen_core::AssetPlacement::default(),
        })
        .unwrap();

    // Precondition sanity: the base node has all three provenance signals.
    let base = &scene.nodes[&NodeId::from("hero_img")];
    assert!(base.source_asset_id.is_some());
    assert!(base.asset_placement.is_some());
    let NodeKind::Image(base_img) = &base.kind else {
        panic!("expected image base node");
    };
    assert!(base_img.alt.is_some());
    scene
}

const ITERATION_3_FIXTURE: &str = "\
// heads-up: reworked the hero cluster and lower-half distribution — swapped the pillarboxed text-baked hero photo for the clean dashboard product image cover-filling the top band, and rebalanced the copy/logo/CTA into a fill-height centered footer region so the empty white void at the bottom is removed
#hero p(0,0) s(1080,560) clip(true) fill($surface.inverse)
#hero_img p(0,0) s(1080,560) asset(asset_ing_9394e96d3c08576a)";

#[test]
fn dsl_modify_swap_to_unregistered_kit_asset_degrades_to_dangling_reference() {
    let mut scene = seed_hero_scene();

    let output = compile_dsl_into_scene(ITERATION_3_FIXTURE, &mut scene);

    // Compiles, no halt, real ops applied.
    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.compile_output.halted_at.is_none());
    assert!(output.operation_error.is_none());
    assert!(!output.compile_output.operations.is_empty());

    // The swap warns LUMD0261 (never silent).
    assert!(
        output
            .compile_output
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.diagnostic.code == "LUMD0261"),
        "the unregistered swap must warn LUMD0261: {:#?}",
        output.compile_output.diagnostics
    );

    // hero_img now references the dashboard asset as a dangling reference with
    // alt cleared and stale placement provenance cleared.
    let img_node = &scene.nodes[&NodeId::from("hero_img")];
    let NodeKind::Image(image) = &img_node.kind else {
        panic!("expected image kind after swap");
    };
    assert_eq!(image.asset_id.as_str(), "asset_ing_9394e96d3c08576a");
    assert_eq!(image.alt, None);
    assert_eq!(img_node.source_asset_id, None);
    assert_eq!(img_node.asset_placement, None);
    assert!(!scene.assets.contains_key(&lumen_core::AssetId::from(
        "asset_ing_9394e96d3c08576a"
    )));

    // The `#hero` line's rest-of-patch (clip + fill) still applied to the frame.
    let hero = &scene.nodes[&NodeId::from("hero")];
    assert!(hero.clip);
    assert!(!hero.fills.is_empty());
}

#[test]
fn dsl_modify_swap_to_registered_asset_keeps_place_asset_in_node_route() {
    let mut scene = seed_hero_scene();
    // Register the target asset so the swap resolves to the placement route.
    scene
        .apply_operation(Operation::UpsertAsset {
            asset: registered_raster_asset("asset_ing_9394e96d3c08576a", "Dashboard product"),
        })
        .unwrap();

    let output = compile_dsl_into_scene(
        "#hero_img p(0,0) s(1080,560) asset(asset_ing_9394e96d3c08576a)",
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    // No degradation warning for a registered target.
    assert!(
        !output
            .compile_output
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.diagnostic.code == "LUMD0261"),
        "a registered swap must NOT warn LUMD0261: {:#?}",
        output.compile_output.diagnostics
    );

    // The op stream carries PlaceAssetInNode exactly as today.
    assert!(
        output
            .compile_output
            .operations
            .iter()
            .any(|operation| matches!(operation, Operation::PlaceAssetInNode { .. })),
        "a registered swap keeps the PlaceAssetInNode route: {:#?}",
        output.compile_output.operations
    );

    // Full placement semantics: provenance repopulated for the new asset.
    let img_node = &scene.nodes[&NodeId::from("hero_img")];
    assert_eq!(
        img_node.source_asset_id,
        Some(lumen_core::AssetId::from("asset_ing_9394e96d3c08576a"))
    );
    assert!(img_node.asset_placement.is_some());
}

#[test]
fn dsl_modify_swap_on_node_with_children_still_errors() {
    // A node WITH children keeps today's hard error — the leaf rule mirrors the
    // placement path. `hero` (the frame) has a child, so swapping its image
    // asset routes through build_modify_operations unchanged and fails.
    let mut scene = seed_hero_scene();

    let output = compile_dsl_into_scene(
        "#hero p(0,0) s(1080,560) asset(asset_ing_9394e96d3c08576a)",
        &mut scene,
    );

    // Today's behavior: the modify halts, no ops applied, error surfaced.
    assert!(
        output.compile_output.has_errors(),
        "a swap on a node with children must still error: {:#?}",
        output.compile_output.diagnostics
    );
    let error = output
        .compile_output
        .diagnostics
        .iter()
        .find(|diagnostic| diagnostic.diagnostic.severity == DiagnosticSeverity::Error)
        .expect("expected a hard error");
    // Pin today's error: LUMD0900 targeted-edit failure naming the missing asset.
    assert_eq!(error.diagnostic.code, "LUMD0900");
    assert!(
        error
            .diagnostic
            .message
            .contains("asset asset_ing_9394e96d3c08576a does not exist"),
        "expected the missing-asset message, got: {}",
        error.diagnostic.message
    );
    // No LUMD0261 for the children case — it never degrades.
    assert!(!output
        .compile_output
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.diagnostic.code == "LUMD0261"));
}

#[test]
fn dsl_modify_swap_degraded_still_applies_rest_of_patch() {
    // The degraded path must still land the other properties on the SAME line
    // (size + clip), not only the kind swap.
    let mut scene = seed_hero_scene();

    let output = compile_dsl_into_scene(
        "#hero_img s(640,360) clip(true) asset(asset_ing_9394e96d3c08576a)",
        &mut scene,
    );

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output
        .compile_output
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.diagnostic.code == "LUMD0261"));

    let img_node = &scene.nodes[&NodeId::from("hero_img")];
    let NodeKind::Image(image) = &img_node.kind else {
        panic!("expected image kind after swap");
    };
    assert_eq!(image.asset_id.as_str(), "asset_ing_9394e96d3c08576a");
    // rest-of-patch: size + clip landed via the ordinary modify op.
    assert!(img_node.clip);
    assert_eq!(img_node.size.width, Dimension::Fixed(640.0));
    assert_eq!(img_node.size.height, Dimension::Fixed(360.0));
}

// ---------------------------------------------------------------------------
// Slice 3 — reconcile directive (tests 8-13 from the Phase A brief).
// ---------------------------------------------------------------------------

fn summary_diag<'a>(
    diagnostics: &'a [lumen_core::DslDiagnostic],
) -> Option<&'a lumen_core::DslDiagnostic> {
    diagnostics
        .iter()
        .find(|diag| diag.diagnostic.code == "LUMD0263")
}

#[test]
fn reconcile_wraps_existing_child_in_new_containers() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_reconcile_wrap"), "Wrap");
    let seed = compile_dsl_into_scene(
        "page p size(200,200,px)\n  artboard fr s(200,200)\n    logo rect s(20,20)\n    caption text \"Brand\" s(80,20)",
        &mut scene,
    );
    assert_no_dsl_errors(&seed.compile_output.diagnostics);
    let source = "reconcile(artboard)\n  chip fr s(80,80)\n    inset fr s(40,40)\n      logo rect s(20,20)\n  caption text \"Brand\" s(80,20)";
    let result = compile_dsl_into_scene(source, &mut scene);

    assert_no_dsl_errors(&result.compile_output.diagnostics);
    assert!(result.operation_error.is_none());
    assert_eq!(
        scene.nodes[&NodeId::from("artboard")].children,
        vec![NodeId::from("chip"), NodeId::from("caption")]
    );
    assert_eq!(
        scene.parent_of(&NodeId::from("logo")),
        Some(lumen_core::ParentRef::Node(NodeId::from("inset")))
    );
    assert_eq!(scene.nodes.len(), 5);
    let repeat = compile_dsl_into_scene(source, &mut scene);
    assert_no_dsl_errors(&repeat.compile_output.diagnostics);
    assert!(repeat.compile_output.operations.is_empty());
}

#[test]
fn documented_parent_directive_compiles() {
    let docs = include_str!(
        "../../../apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/directives.md"
    );
    let row = docs
        .lines()
        .find(|line| line.starts_with("| `parent` |"))
        .unwrap();
    let form = row.split('`').nth(3).unwrap();
    let required = form.split(" [").next().unwrap();
    let source = format!(
        "{})",
        required.replace("(id,", "(logo,").replace("pid", "chip")
    );
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_parent_docs"), "Parent");
    let seed = compile_dsl_into_scene(
        "page p size(200,200,px)\n  artboard fr s(200,200)\n    logo rect s(20,20)\n    chip fr s(40,40)",
        &mut scene,
    );
    assert_no_dsl_errors(&seed.compile_output.diagnostics);

    let result = compile_dsl_into_scene(&source, &mut scene);

    assert_no_dsl_errors(&result.compile_output.diagnostics);
    assert!(result.operation_error.is_none());
    assert_eq!(
        scene.parent_of(&NodeId::from("logo")),
        Some(lumen_core::ParentRef::Node(NodeId::from("chip")))
    );
}

#[test]
fn reconcile_tracks_sibling_positions_after_each_move_and_insert() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_reconcile_order"), "Order");
    let seed = compile_dsl_into_scene(
        "page p size(200,200,px)\n  root fr s(200,200)\n    aa rect s(10,10)\n    bb rect s(10,10)\n    cc rect s(10,10)\n    dd rect s(10,10)",
        &mut scene,
    );
    assert_no_dsl_errors(&seed.compile_output.diagnostics);

    let result = compile_dsl_into_scene(
        "reconcile(root)\n  aa rect s(10,10)\n  dd rect s(10,10)\n  cc rect s(10,10)\n  new_rect rect s(10,10)\n  bb rect s(10,10)",
        &mut scene,
    );

    assert_no_dsl_errors(&result.compile_output.diagnostics);
    assert!(result.operation_error.is_none());
    assert_eq!(
        scene.nodes[&NodeId::from("root")].children,
        ["aa", "dd", "cc", "new_rect", "bb"]
            .map(NodeId::from)
            .to_vec()
    );
}

// Test 8 — P3r3's intent in reconcile form: a container `cta` holding an
// agent-born `cta_text`; a reconcile block that omits `cta_text` and adds an
// image + caption → remove + 2 inserts, compiles clean, LUMD0263 present.
#[test]
fn reconcile_p3r3_intent_removes_and_inserts() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_reconcile_p3r3"), "P3r3");
    let seed = compile_dsl_into_scene(
        r#"
page page_cta size(1080,1350,px)
  cta al(v) p(0,0) s(320,72)
    cta_text text "Book a Demo" p(0,0) s(320,40)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&seed.compile_output.diagnostics);

    let reconcile = compile_dsl_into_scene(
        r#"
reconcile(cta)
  cta_shot image asset(asset_ing_9394e96d3c08576a) p(0,0) s(320,220)
  caption text "See it in action" p(0,0) s(320,40)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&reconcile.compile_output.diagnostics);
    assert!(reconcile.operation_error.is_none());

    // cta_text removed; the two new nodes present under cta, in order.
    assert!(!scene.nodes.contains_key(&NodeId::from("cta_text")));
    assert_eq!(
        scene.nodes[&NodeId::from("cta")].children,
        vec![NodeId::from("cta_shot"), NodeId::from("caption")]
    );
    let summary = summary_diag(&reconcile.compile_output.diagnostics)
        .expect("LUMD0263 summary present");
    assert!(summary.diagnostic.message.contains("1 removed"));
    assert!(summary.diagnostic.message.contains("2 inserted"));
}

// Test 9 — P4r3's intent: reconcile over `main` re-emitting its existing
// children (unchanged) plus a new testimonial text → exactly 1 InsertNode,
// zero ops for the unchanged re-emitted children (id-reuse + suspended
// duplicate-id checks in-block).
#[test]
fn reconcile_p4r3_intent_reuses_ids_and_inserts_one() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_reconcile_p4r3"), "P4r3");
    let seed = compile_dsl_into_scene(
        r#"
page page_main size(1080,1350,px)
  main al(v) p(0,0) s(1080,900)
    lead text "Lead copy" p(0,0) s(600,40)
    body text "Body copy" p(0,0) s(600,120)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&seed.compile_output.diagnostics);

    let reconcile = compile_dsl_into_scene(
        r#"
reconcile(main)
  lead text "Lead copy" p(0,0) s(600,40)
  body text "Body copy" p(0,0) s(600,120)
  testimonial text "Loved by teams" p(0,0) s(600,60)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&reconcile.compile_output.diagnostics);
    assert!(reconcile.operation_error.is_none());

    // Exactly one InsertNode (testimonial); the re-emitted lead/body are
    // field-identical → zero ops for them.
    let inserts: Vec<&NodeId> = reconcile
        .compile_output
        .operations
        .iter()
        .filter_map(|op| match op {
            Operation::InsertNode { node, .. } => Some(&node.id),
            _ => None,
        })
        .collect();
    assert_eq!(inserts, vec![&NodeId::from("testimonial")]);
    // No stray updates/removes/moves for the unchanged children.
    assert_eq!(reconcile.compile_output.operations.len(), 1);
    assert_eq!(
        scene.nodes[&NodeId::from("main")].children,
        vec![
            NodeId::from("lead"),
            NodeId::from("body"),
            NodeId::from("testimonial")
        ]
    );
}

// Test 10 — same as 9 but the omitted node is protected → kept + LUMD0262
// warning, no RemoveNode.
#[test]
fn reconcile_protected_omission_keeps_and_warns() {
    let mut scene = Scene::new(
        lumen_core::DocumentId::from("doc_reconcile_protected"),
        "Protected",
    );
    let seed = compile_dsl_into_scene(
        r#"
page page_main size(1080,1350,px)
  main al(v) p(0,0) s(1080,900)
    lead text "Lead copy" p(0,0) s(600,40)
    body text "Body copy" p(0,0) s(600,120)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&seed.compile_output.diagnostics);

    // `body` is protected (seed-born / human). The reconcile omits it.
    let mut protected = BTreeSet::new();
    protected.insert(NodeId::from("body"));
    let reconcile = compile_dsl_into_scene_with_session_and_protected(
        r#"
reconcile(main)
  lead text "Lead copy" p(0,0) s(600,40)
"#,
        &mut scene,
        None,
        protected,
    );
    assert_no_dsl_errors(&reconcile.compile_output.diagnostics);
    assert!(reconcile.operation_error.is_none());

    // body kept, no removal op.
    assert!(scene.nodes.contains_key(&NodeId::from("body")));
    assert!(!reconcile.compile_output.operations.iter().any(|op| matches!(
        op,
        Operation::RemoveNode { node_id } if node_id == &NodeId::from("body")
    )));
    assert!(reconcile
        .compile_output
        .diagnostics
        .iter()
        .any(|diag| diag.diagnostic.code == "LUMD0262"
            && diag.diagnostic.message.contains("body")));
}

// Test 11 — invalid targets → LUMD0264 with the container hint.
#[test]
fn reconcile_invalid_target_errors_with_container_hint() {
    let mut scene = Scene::new(
        lumen_core::DocumentId::from("doc_reconcile_bad_target"),
        "BadTarget",
    );
    let seed = compile_dsl_into_scene(
        r#"
page page_main size(1080,1350,px)
  main al(v) p(0,0) s(1080,900)
    leaf text "leaf" p(0,0) s(600,40)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&seed.compile_output.diagnostics);

    // Nonexistent target.
    let missing = compile_dsl_into_scene("reconcile(nope)\n  x text \"x\" p(0,0) s(10,10)", &mut scene);
    let missing_diag = missing
        .compile_output
        .diagnostics
        .iter()
        .find(|diag| diag.diagnostic.code == "LUMD0264")
        .expect("LUMD0264 for missing target");
    assert!(missing_diag
        .diagnostic
        .hint
        .as_ref()
        .unwrap()
        .contains("main"));

    // Leaf (text) target.
    let leaf = compile_dsl_into_scene("reconcile(leaf)\n  x text \"x\" p(0,0) s(10,10)", &mut scene);
    assert!(leaf
        .compile_output
        .diagnostics
        .iter()
        .any(|diag| diag.diagnostic.code == "LUMD0264"));
}

// Test 12 — a nested delete(protected_id) inside a reconcile block IS honored
// (delete stays the human-content deletion path).
#[test]
fn reconcile_nested_delete_honors_explicit_removal_of_protected() {
    let mut scene = Scene::new(
        lumen_core::DocumentId::from("doc_reconcile_delete"),
        "Delete",
    );
    let seed = compile_dsl_into_scene(
        r#"
page page_main size(1080,1350,px)
  main al(v) p(0,0) s(1080,900)
    lead text "Lead copy" p(0,0) s(600,40)
    body text "Body copy" p(0,0) s(600,120)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&seed.compile_output.diagnostics);

    // `body` is protected, but the block explicitly deletes it → removed.
    let mut protected = BTreeSet::new();
    protected.insert(NodeId::from("body"));
    let reconcile = compile_dsl_into_scene_with_session_and_protected(
        r#"
reconcile(main)
  lead text "Lead copy" p(0,0) s(600,40)
  delete(body)
"#,
        &mut scene,
        None,
        protected,
    );
    assert_no_dsl_errors(&reconcile.compile_output.diagnostics);
    assert!(reconcile.operation_error.is_none());
    assert!(!scene.nodes.contains_key(&NodeId::from("body")));
    // Explicit delete wins over protection: no LUMD0262 kept-warning for body.
    assert!(!reconcile
        .compile_output
        .diagnostics
        .iter()
        .any(|diag| diag.diagnostic.code == "LUMD0262"));
}

// Test 13 — duplicate-id checks OUTSIDE a reconcile block are unchanged: a
// plain block re-declaring an existing id still halts LUMD0401.
#[test]
fn duplicate_id_outside_reconcile_block_still_halts() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_dupe"), "Dupe");
    let seed = compile_dsl_into_scene(
        r#"
page page_main size(1080,1350,px)
  main al(v) p(0,0) s(1080,900)
    lead text "Lead copy" p(0,0) s(600,40)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&seed.compile_output.diagnostics);

    // Re-declaring `lead` in a PLAIN continuation (no reconcile) still halts.
    let dupe = compile_dsl_into_scene(
        r#"
#page:page_main
  lead text "Duplicate" p(0,0) s(600,40)
"#,
        &mut scene,
    );
    assert!(dupe
        .compile_output
        .diagnostics
        .iter()
        .any(|diag| diag.diagnostic.code == "LUMD0401"));
}

// --- D12: detach_to_freehand(<node_id>) DSL directive ---
//
// The directive lowers to the core `StructuredEditInstruction::DetachToFreehand`
// builder: it bakes a managed (solver-owned) node to `position_mode: absolute`
// at its solved box, so the node joins the page-level freehand paint pass and
// can layer ABOVE a pre-existing pinned human node (the P1r6 doppelganger
// class, where sibling `after(...)` could not reorder managed content above a
// pin because pins paint in a page-level pass after all in-flow content).

/// A page with (in document order) a pinned human ellipse `human_ellipse_p1`
/// followed by a MANAGED (solver-owned, `position_mode: managed`) mark rect
/// `ellipse_mark`, both carrying solved `computed` geometry. This is the P1r6
/// scenario: the human pin paints in the freehand pass, so the earlier-declared
/// managed mark cannot appear on top of it until it, too, joins the pass.
fn scene_p1r6_pin_then_managed_mark() -> Scene {
    use lumen_core::{ComputedGeometry, Node, Page, PageSize};

    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_p1r6"), "P1r6");
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

    // The human freehand pin (already absolute) is declared FIRST.
    let pin_box = lumen_core::Rect {
        x: 600.0,
        y: 900.0,
        width: 340.0,
        height: 270.0,
    };
    let mut pin = Node::new(NodeId::from("human_ellipse_p1"), NodeKind::Ellipse);
    pin.size = lumen_core::SizeSpec::fixed(pin_box.width, pin_box.height);
    pin.position_mode = lumen_core::PositionMode::Absolute;
    pin.absolute_box = Some(pin_box.clone());
    pin.base_anchor = Some(pin_box.clone());
    pin.computed = Some(ComputedGeometry {
        layout_bounds: pin_box.clone(),
        render_bounds: pin_box.clone(),
        text_lines: Vec::new(),
    });
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_a4")),
            index: 0,
            node: pin,
        })
        .unwrap();

    // The managed mark is declared AFTER the pin, still solver-owned. It has
    // solved geometry so `detach_to_freehand` can read its box.
    let mark_box = lumen_core::Rect {
        x: 690.0,
        y: 955.0,
        width: 160.0,
        height: 160.0,
    };
    let mut mark = Node::new(NodeId::from("ellipse_mark"), NodeKind::Rect);
    mark.size = lumen_core::SizeSpec::fixed(mark_box.width, mark_box.height);
    mark.computed = Some(ComputedGeometry {
        layout_bounds: mark_box.clone(),
        render_bounds: mark_box.clone(),
        text_lines: Vec::new(),
    });
    scene
        .apply_operation(Operation::InsertNode {
            parent: ParentRef::Page(PageId::from("page_a4")),
            index: 1,
            node: mark,
        })
        .unwrap();

    scene
}

#[test]
fn detach_to_freehand_bakes_managed_node_to_absolute_at_solved_box() {
    let mut scene = scene_p1r6_pin_then_managed_mark();
    let solved = scene.nodes[&NodeId::from("ellipse_mark")]
        .computed
        .as_ref()
        .unwrap()
        .layout_bounds
        .clone();
    assert_eq!(
        scene.nodes[&NodeId::from("ellipse_mark")].position_mode,
        lumen_core::PositionMode::Managed,
        "mark starts solver-owned"
    );

    let output = compile_dsl_into_scene("detach_to_freehand(ellipse_mark)", &mut scene);

    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let mark = &scene.nodes[&NodeId::from("ellipse_mark")];
    assert_eq!(
        mark.position_mode,
        lumen_core::PositionMode::Absolute,
        "detach must bake the node absolute"
    );
    assert_eq!(
        mark.absolute_box,
        Some(solved.clone()),
        "detach pins the node at its solved box"
    );
    assert_eq!(
        mark.base_anchor,
        Some(solved),
        "detach records the solved box as the base anchor"
    );
}

#[test]
fn detach_to_freehand_lets_managed_mark_paint_after_pinned_human_node() {
    // THE P1r6 scenario. Before detach the mark is solver-owned, so the
    // freehand pass contains ONLY the human pin. After detach the mark joins
    // the pass and — being later in document order — paints AFTER the pin, so
    // it is visible on top (what `after(...)` could never achieve).
    let mut scene = scene_p1r6_pin_then_managed_mark();

    let before = lumen_core::pinned_paint_pass(&scene, &scene.pages[&PageId::from("page_a4")]);
    assert_eq!(
        before,
        vec![NodeId::from("human_ellipse_p1")],
        "only the human pin is in the freehand pass before detach"
    );

    let output = compile_dsl_into_scene("detach_to_freehand(ellipse_mark)", &mut scene);
    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let after = lumen_core::pinned_paint_pass(&scene, &scene.pages[&PageId::from("page_a4")]);
    assert_eq!(
        after,
        vec![
            NodeId::from("human_ellipse_p1"),
            NodeId::from("ellipse_mark"),
        ],
        "after detach the mark joins the freehand pass AFTER the pin (paints on top)"
    );
    // The pin's position in the pass is unchanged; the mark is strictly later,
    // which is exactly the paint-order guarantee the directive exists to give.
    let pin_index = after
        .iter()
        .position(|id| id == &NodeId::from("human_ellipse_p1"))
        .unwrap();
    let mark_index = after
        .iter()
        .position(|id| id == &NodeId::from("ellipse_mark"))
        .unwrap();
    assert!(
        mark_index > pin_index,
        "the detached mark must paint after the pre-existing pin"
    );
}

#[test]
fn detach_to_freehand_unknown_id_is_the_standard_unknown_target_diagnostic() {
    let mut scene = scene_p1r6_pin_then_managed_mark();

    let output = compile_dsl_into_scene("detach_to_freehand(ghost)", &mut scene);

    // Unknown node id falls through to the core builder's TargetNotFound, which
    // `edit_error_diag` reports as the standard LUMD0900 halt.
    assert_eq!(
        output.compile_output.halted_at.as_ref().unwrap().code,
        "LUMD0900"
    );
    assert!(output
        .compile_output
        .diagnostics
        .iter()
        .any(|diag| diag.diagnostic.code == "LUMD0900"
            && diag.diagnostic.message.contains("ghost")));
}

#[test]
fn detach_to_freehand_on_already_pinned_node_is_a_loud_no_op_warning() {
    let mut scene = scene_p1r6_pin_then_managed_mark();

    let output = compile_dsl_into_scene("detach_to_freehand(human_ellipse_p1)", &mut scene);

    // Already-absolute target is a loud no-op: a LUMD0265 WARNING, not a halt,
    // and no operations are emitted.
    assert!(
        output.compile_output.halted_at.is_none(),
        "already-pinned detach must not halt"
    );
    assert!(output.operation_error.is_none());
    let warning = output
        .compile_output
        .diagnostics
        .iter()
        .find(|diag| diag.diagnostic.code == "LUMD0265")
        .expect("LUMD0265 warning emitted");
    assert_eq!(
        warning.diagnostic.severity,
        DiagnosticSeverity::Warning,
        "the no-op is a warning, not an error"
    );
    assert!(output
        .compile_output
        .operations
        .iter()
        .all(|op| !matches!(op, Operation::UpdateNode { node_id, .. }
            if node_id == &NodeId::from("human_ellipse_p1"))));
}

// ---------------------------------------------------------------------------
// A4 grammar: glow / blur / inner_shadow, per-corner radius, solid opacity,
// bleed intent + misplaced-form disambiguation.
// ---------------------------------------------------------------------------

#[test]
fn dsl_lowers_glow_blur_and_inner_shadow() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_a4"), "A4");
    let output = compile_dsl_into_scene(
        r#"
page page_a4
  card r p(20,20) s(200,120) fill(#6d8bff) glow(#a855f7,o(0.8),blur(20),spread(4)) blur(3) inner_shadow(#101828,o(0.6),y(6),blur(10),spread(2))
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let card = &scene.nodes[&NodeId::from("card")];
    assert_eq!(card.effects.len(), 3);
    assert!(matches!(
        card.effects[0].kind,
        lumen_core::EffectKind::Glow { .. }
    ));
    assert!(matches!(
        card.effects[1].kind,
        lumen_core::EffectKind::LayerBlur { radius } if radius == 3.0
    ));
    assert!(matches!(
        card.effects[2].kind,
        lumen_core::EffectKind::InnerShadow { .. }
    ));
    // Auto ids are class-scoped and deterministic.
    assert_eq!(card.effects[0].id, lumen_core::EffectId::from("effect_card_glow_1"));
    assert_eq!(card.effects[1].id, lumen_core::EffectId::from("effect_card_blur_1"));
    assert_eq!(
        card.effects[2].id,
        lumen_core::EffectId::from("effect_card_inner_shadow_1")
    );
}

#[test]
fn dsl_effect_upsert_and_remove_by_id() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_a4u"), "A4");
    compile_dsl_into_scene(
        r#"
page page_a4
  card r p(20,20) s(200,120) fill(#ffffff) glow(halo,#a855f7,o(0.8),blur(20),spread(4))
"#,
        &mut scene,
    );
    // Upsert same id in place.
    compile_dsl_into_scene("#card glow(halo,#22d3ee,o(0.5),blur(30),spread(2))", &mut scene);
    let card = &scene.nodes[&NodeId::from("card")];
    assert_eq!(card.effects.len(), 1);
    let lumen_core::EffectKind::Glow { blur, .. } = &card.effects[0].kind else {
        panic!("expected glow");
    };
    assert_eq!(*blur, 30.0);

    // Remove by id.
    compile_dsl_into_scene("#card remove_effect(halo)", &mut scene);
    assert!(scene.nodes[&NodeId::from("card")].effects.is_empty());
}

#[test]
fn dsl_blur_shorthand_and_named_radius() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_blur"), "A4");
    let out = compile_dsl_into_scene(
        r#"
page page_a4
  card r p(0,0) s(100,100) fill(#ffffff) blur(12)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&out.compile_output.diagnostics);
    assert!(matches!(
        scene.nodes[&NodeId::from("card")].effects[0].kind,
        lumen_core::EffectKind::LayerBlur { radius } if radius == 12.0
    ));
}

#[test]
fn dsl_glow_rejects_xy_offset() {
    let output = parse_dsl(
        r#"
page page_a4
  card r p(0,0) s(100,100) glow(#a855f7,x(4))
"#,
    );
    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0266");
}

#[test]
fn dsl_per_corner_radius_lowers_four_args() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_rd"), "A4");
    let out = compile_dsl_into_scene(
        r#"
page page_a4
  card r p(0,0) s(200,120) fill(#ffffff) rd(40,4,40,4)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&out.compile_output.diagnostics);
    let corner = &scene.nodes[&NodeId::from("card")].corner;
    assert_eq!(corner.top_left, 40.0);
    assert_eq!(corner.top_right, 4.0);
    assert_eq!(corner.bottom_right, 40.0);
    assert_eq!(corner.bottom_left, 4.0);
}

#[test]
fn dsl_per_corner_radius_rejects_bad_arity() {
    let output = parse_dsl(
        r#"
page page_a4
  card r p(0,0) s(200,120) rd(40,4)
"#,
    );
    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0230");
}

#[test]
fn dsl_per_corner_radius_accepts_zero_corners() {
    // Review-gate regression (A4, found by the K-A4 validation protocol):
    // zero is a meaningful corner magnitude (a square corner) — the classic
    // "round only the top" idiom must compile.
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_rd0"), "A4");
    let out = compile_dsl_into_scene(
        r#"
page page_a4
  card r p(0,0) s(200,120) fill(#ffffff) rd(12,12,0,0)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&out.compile_output.diagnostics);
    let corner = &scene.nodes[&NodeId::from("card")].corner;
    assert_eq!(corner.top_left, 12.0);
    assert_eq!(corner.top_right, 12.0);
    assert_eq!(corner.bottom_right, 0.0);
    assert_eq!(corner.bottom_left, 0.0);
}

#[test]
fn dsl_per_corner_radius_rejects_negative_corners() {
    let output = parse_dsl(
        r#"
page page_a4
  card r p(0,0) s(200,120) rd(12,12,-4,0)
"#,
    );
    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0255");
}

#[test]
fn dsl_solid_opacity_composes_into_existing_alpha() {
    // opacity multiplies into the color alpha: 0xff * 0.5 = 127.5 -> 0x80.
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_solid8"), "A4");
    let out = compile_dsl_into_scene(
        r#"
page page_a4
  card r p(0,0) s(100,100) fill(solid(#ff0000,0.5))
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&out.compile_output.diagnostics);
    assert_eq!(
        scene.nodes[&NodeId::from("card")].fills[0].paint,
        Paint::Solid {
            color: Color::Hex {
                value: "#ff000080".to_owned()
            }
        }
    );
}

#[test]
fn dsl_solid_opacity_out_of_range_is_a_loud_error() {
    let output = parse_dsl(
        r#"
page page_a4
  card r p(0,0) s(100,100) fill(solid(#ff0000,1.4))
"#,
    );
    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0270");
}

#[test]
fn dsl_bleed_intent_sets_node_flag() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_bleed"), "A4");
    let out = compile_dsl_into_scene(
        r#"
page page_a4
  wash r p(0,0) s(500,400) fill(#dbe6ff) bleed(true)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&out.compile_output.diagnostics);
    assert!(scene.nodes[&NodeId::from("wash")].bleed);

    // Modify path toggles it back off.
    compile_dsl_into_scene("#wash bleed(false)", &mut scene);
    assert!(!scene.nodes[&NodeId::from("wash")].bleed);
}

#[test]
fn dsl_bleed_rect_on_node_is_disambiguated_loudly() {
    // A 4-arg print-bleed rect on an element warns with LUMD0269 naming the
    // per-node form, never silently ignored.
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_bleed2"), "A4");
    let out = compile_dsl_into_scene(
        r#"
page page_a4
  wash r p(0,0) s(100,100) fill(#ffffff) bleed(0,0,120,120)
"#,
        &mut scene,
    );
    assert!(
        out.compile_output
            .diagnostics
            .iter()
            .any(|d| d.diagnostic.code == "LUMD0269"),
        "bleed rect on a node is disambiguated: {:#?}",
        out.compile_output.diagnostics
    );
}

#[test]
fn dsl_bleed_arity_error_names_both_forms() {
    let output = parse_dsl(
        r#"
page page_a4
  wash r p(0,0) s(100,100) bleed(1,2,3)
"#,
    );
    assert_eq!(output.halted_at.as_ref().unwrap().code, "LUMD0269");
}

#[test]
fn dsl_applies_a6_typography_keywords() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_a6"), "A6");
    let output = compile_dsl_into_scene(
        r#"
page page_a6 size(400,400,px)
  eyebrow text "kicker" p(24,24) s(240,hug) case(upper) underline(true) strike(true) truncate(true) para_spacing(12) max_lines(2) wrap_text(true)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&output.compile_output.diagnostics);
    assert!(output.operation_error.is_none());

    let NodeKind::Text(text) = &scene.nodes[&NodeId::from("eyebrow")].kind else {
        panic!("expected text node");
    };
    assert_eq!(text.text_transform, lumen_core::TextTransform::Uppercase);
    assert!(text.underline);
    assert!(text.strikethrough);
    assert!(text.truncate);
    assert_eq!(text.paragraph_spacing, 12.0);
}

#[test]
fn dsl_italic_keyword_create_and_modify_lowering() {
    // A7b: block italic(bool) on create sets TextNode.italic; a later modify
    // line flips it (content edits elsewhere preserve it — geometry channel,
    // like valign).
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_italic"), "Italic");
    let first = compile_dsl_into_scene(
        r#"
page page_a7 size(400,400,px)
  quote text "Emphasis" p(24,24) s(240,hug) italic(true)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&first.compile_output.diagnostics);
    let NodeKind::Text(text) = &scene.nodes[&NodeId::from("quote")].kind else {
        panic!("expected text node");
    };
    assert!(text.italic, "create-time italic(true) sets the field");

    // Modify path: flip it back off.
    let second = compile_dsl_into_scene(r#"#quote italic(false)"#, &mut scene);
    assert_no_dsl_errors(&second.compile_output.diagnostics);
    assert!(second.operation_error.is_none());
    let NodeKind::Text(text) = &scene.nodes[&NodeId::from("quote")].kind else {
        panic!("expected text node");
    };
    assert!(!text.italic, "modify italic(false) clears the field");
}

#[test]
fn dsl_italic_on_non_text_warns_lumd0607() {
    // A7b: italic(...) on a non-text node warns LUMD0607 (underline mirror).
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_italic_wrong"), "ItalicWrong");
    let output = compile_dsl_into_scene(
        r#"
page page_a7 size(400,400,px)
  box rect p(0,0) s(100,100) italic(true)
"#,
        &mut scene,
    );
    assert!(
        output
            .compile_output
            .diagnostics
            .iter()
            .any(|d| d.diagnostic.code == "LUMD0607"),
        "italic on a non-text node must warn LUMD0607: {:#?}",
        output.compile_output.diagnostics
    );
}

#[test]
fn dsl_a6_keyword_aliases_resolve() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_a6_alias"), "A6");
    let output = compile_dsl_into_scene(
        r#"
page page_a6 size(400,400,px)
  lbl text "x" p(0,0) s(240,hug) text_transform(lowercase) strikethrough(true) ellipsis(true) paragraph_spacing(4)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&output.compile_output.diagnostics);
    let NodeKind::Text(text) = &scene.nodes[&NodeId::from("lbl")].kind else {
        panic!("expected text node");
    };
    assert_eq!(text.text_transform, lumen_core::TextTransform::Lowercase);
    assert!(text.strikethrough);
    assert!(text.truncate);
    assert_eq!(text.paragraph_spacing, 4.0);
}

#[test]
fn dsl_rejects_unknown_case_value_with_lumd0271() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_a6_badcase"), "A6");
    let output = compile_dsl_into_scene(
        r#"
page page_a6 size(400,400,px)
  lbl text "x" p(0,0) s(240,hug) case(smallcaps)
"#,
        &mut scene,
    );
    assert!(
        output
            .compile_output
            .diagnostics
            .iter()
            .any(|d| d.diagnostic.code == "LUMD0271"),
        "{:#?}",
        output.compile_output.diagnostics
    );
}

#[test]
fn dsl_rejects_negative_paragraph_spacing() {
    let mut scene = Scene::new(lumen_core::DocumentId::from("doc_a6_negspacing"), "A6");
    let output = compile_dsl_into_scene(
        r#"
page page_a6 size(400,400,px)
  lbl text "x" p(0,0) s(240,hug) para_spacing(-3)
"#,
        &mut scene,
    );
    assert!(
        output
            .compile_output
            .diagnostics
            .iter()
            .any(|d| d.diagnostic.code == "LUMD0255"),
        "{:#?}",
        output.compile_output.diagnostics
    );
}

// ---------------------------------------------------------------------------
// LUMV0820 repairability (fast-loop v1, P0.2)
//
// LUMV0820 ("image-like slot needs an image policy") used to be a preflight
// ERROR with no authoring escape: the DSL's only slot constructor is
// `Slot::text_short`, so `image … slot(key)` produced an Image slot with
// `image_policy: None` and an instant error the author could only clear by
// deleting the slot it had just asked for. The design deepagent burned dozens
// of model calls probing for a repair that did not exist.
//
// Two halves are proven here: image slots are now BORN with a policy, and an
// existing policy-less slot can be REPAIRED in place.
// ---------------------------------------------------------------------------

fn image_slot_policy_diagnostics(scene: &Scene) -> Vec<lumen_core::Diagnostic> {
    lumen_core::validate_layout(scene, lumen_core::LayoutOptions::default())
        .into_iter()
        .filter(|diagnostic| diagnostic.code == "LUMV0820")
        .collect()
}

fn scene_with_image_slot(document_id: &str) -> Scene {
    let mut scene = Scene::new(lumen_core::DocumentId::from(document_id), "Image Slot");
    let output = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  logo image asset(account_logo) p(24,24) s(96,96) slot(account.logo)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&output.compile_output.diagnostics);
    scene
}

#[test]
fn dsl_image_slot_is_born_with_an_image_policy() {
    let scene = scene_with_image_slot("doc_image_slot_born");

    let slot = scene
        .slot_by_key(&SlotKey::from("account.logo"))
        .expect("slot should exist");
    assert_eq!(slot.content_type, lumen_core::ContentType::Image);
    let policy = slot
        .image_policy
        .as_ref()
        .expect("an image-like slot must be born with a policy");
    assert_eq!(policy.fit, lumen_core::ImageFitMode::Cover);
    assert!(policy.preserve_transparency);
    assert_eq!(policy.focal_point, None);
    assert_eq!(policy.aspect_ratio, None);

    // The regression this whole slice exists to kill.
    assert!(
        image_slot_policy_diagnostics(&scene).is_empty(),
        "a freshly authored image slot must not raise LUMV0820"
    );
}

#[test]
fn dsl_text_slot_is_not_given_an_image_policy() {
    let mut scene = Scene::new(
        lumen_core::DocumentId::from("doc_text_slot_policy"),
        "Text Slot",
    );
    let output = compile_dsl_into_scene(
        r#"
page page_square size(400,400,px)
  headline text "Headline" p(24,24) s(300,hug) slot(campaign.headline)
"#,
        &mut scene,
    );
    assert_no_dsl_errors(&output.compile_output.diagnostics);

    let slot = scene
        .slot_by_key(&SlotKey::from("campaign.headline"))
        .expect("slot should exist");
    assert_eq!(slot.image_policy, None);
}

#[test]
fn slot_modify_image_policy_clears_lumv0820_on_a_legacy_slot() {
    let mut scene = scene_with_image_slot("doc_image_policy_repair");

    // Reproduce a document authored BEFORE the born-correct fix: an image slot
    // carrying no policy at all. Documents in this shape already exist, so the
    // in-place repair has to work on them, not just on new scenes.
    {
        let mut stripped = scene
            .slot_by_key(&SlotKey::from("account.logo"))
            .expect("slot should exist")
            .clone();
        stripped.image_policy = None;
        scene.slots.insert(stripped.id.clone(), stripped);
    }
    assert_eq!(
        image_slot_policy_diagnostics(&scene).len(),
        1,
        "the legacy shape must reproduce LUMV0820"
    );

    let repair = compile_dsl_into_scene(
        r#"#slot:account.logo image_policy(fit=contain, focal_x=0.5, focal_y=0.35, min_dpi=300, aspect=1.5, preserve_transparency=false)"#,
        &mut scene,
    );
    assert_no_dsl_errors(&repair.compile_output.diagnostics);
    assert!(repair.operation_error.is_none());

    let slot = scene
        .slot_by_key(&SlotKey::from("account.logo"))
        .expect("slot should exist");
    let policy = slot
        .image_policy
        .as_ref()
        .expect("the repair must install a policy");
    assert_eq!(policy.fit, lumen_core::ImageFitMode::Contain);
    assert_eq!(
        policy.focal_point,
        Some(lumen_core::FocalPoint { x: 0.5, y: 0.35 })
    );
    assert_eq!(policy.min_dpi, Some(300));
    assert_eq!(policy.aspect_ratio, Some(1.5));
    assert!(!policy.preserve_transparency);

    assert!(
        image_slot_policy_diagnostics(&scene).is_empty(),
        "the author-reachable repair must clear LUMV0820"
    );
}

#[test]
fn slot_modify_image_policy_accepts_a_bare_fit_mode() {
    let mut scene = scene_with_image_slot("doc_image_policy_bare");

    let repair = compile_dsl_into_scene(r#"#slot:account.logo image_policy(crop)"#, &mut scene);
    assert_no_dsl_errors(&repair.compile_output.diagnostics);

    let slot = scene
        .slot_by_key(&SlotKey::from("account.logo"))
        .expect("slot should exist");
    let policy = slot.image_policy.as_ref().expect("policy");
    assert_eq!(policy.fit, lumen_core::ImageFitMode::Crop);
    // Unspecified members fall back to the default, never to a half-built
    // policy that preflight would then reject.
    assert!(policy.preserve_transparency);
    assert_eq!(policy.focal_point, None);
}

#[test]
fn slot_modify_image_policy_none_clears_the_policy() {
    let mut scene = scene_with_image_slot("doc_image_policy_clear");

    let cleared = compile_dsl_into_scene(r#"#slot:account.logo image_policy(none)"#, &mut scene);
    assert_no_dsl_errors(&cleared.compile_output.diagnostics);

    let slot = scene
        .slot_by_key(&SlotKey::from("account.logo"))
        .expect("slot should exist");
    assert_eq!(slot.image_policy, None);
}

#[test]
fn slot_modify_image_policy_refuses_values_preflight_would_reject() {
    let mut scene = scene_with_image_slot("doc_image_policy_invalid");

    // A focal point outside 0..1 is LUMV0821 at preflight; the compiler
    // refuses it up front so the author sees it on the line that wrote it.
    let out_of_range = compile_dsl_into_scene(
        r#"#slot:account.logo image_policy(fit=cover, focal_x=1.4, focal_y=0.5)"#,
        &mut scene,
    );
    assert!(
        out_of_range
            .compile_output
            .diagnostics
            .iter()
            .any(|d| d.diagnostic.code == "LUMD0276"),
        "{:#?}",
        out_of_range.compile_output.diagnostics
    );

    // A lone focal axis is meaningless.
    let half_focal = compile_dsl_into_scene(
        r#"#slot:account.logo image_policy(fit=cover, focal_x=0.5)"#,
        &mut scene,
    );
    assert!(
        half_focal
            .compile_output
            .diagnostics
            .iter()
            .any(|d| d.diagnostic.code == "LUMD0276"),
        "{:#?}",
        half_focal.compile_output.diagnostics
    );

    let bad_fit = compile_dsl_into_scene(
        r#"#slot:account.logo image_policy(fit=squish)"#,
        &mut scene,
    );
    assert!(
        bad_fit
            .compile_output
            .diagnostics
            .iter()
            .any(|d| d.diagnostic.code == "LUMD0276"),
        "{:#?}",
        bad_fit.compile_output.diagnostics
    );
}

#[test]
fn unsized_text_element_hugs_both_axes_and_an_explicit_size_still_wins() {
    // Editor Quality Plan 4 (item F, ruling R7): a text element with no s(...)
    // used to inherit Node::new's 0×0 fixed box (LUMV0901 collapsed bounds).
    // It now hugs its copy; an authored size — fixed height included — is
    // never rewritten.
    let mut scene = Scene::new(
        lumen_core::DocumentId::from("doc_text_default"),
        "Text default",
    );
    let output = compile_dsl_into_scene(
        "page page_a4 preset(a4,portrait)\n  copy text \"Hi\" p(0,0)\n  boxed text \"Hi\" p(0,40) s(300,80)\n  wide text \"Hi\" p(0,140) s(fill,hug)",
        &mut scene,
    );
    assert_no_dsl_errors(&output.compile_output.diagnostics);

    let copy = &scene.nodes[&NodeId::from("copy")];
    assert_eq!(copy.size.width, Dimension::Hug);
    assert_eq!(copy.size.height, Dimension::Hug);

    let boxed = &scene.nodes[&NodeId::from("boxed")];
    assert_eq!(boxed.size.width, Dimension::Fixed(300.0));
    assert_eq!(boxed.size.height, Dimension::Fixed(80.0));

    let wide = &scene.nodes[&NodeId::from("wide")];
    assert_eq!(wide.size.width, Dimension::Fill { weight: 1.0 });
    assert_eq!(wide.size.height, Dimension::Hug);
}
