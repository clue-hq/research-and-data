use lumen_core::{
    compile_dsl_into_scene, preflight_scene, AutoLayoutProps, BrandKit, Color, ContentType,
    DiagnosticSeverity, Dimension, DocumentId, ExportAdapter, ExportFormat, ExportProfile,
    ExportPurpose, ExportRequest, Fill, Node, NodeId, NodeKind, Page, PageId, PagePreset, PageSize,
    Paint, PaintId, PdfIntent, PreflightOptions, RasterScale, Rect, Scene, SizeSpec, Slot, SlotId,
    SlotKey, Stroke, TextAlign, TextNode, Transform, Unit,
};
use lumen_export::LumenExportAdapter;
use serde_json::Value;

fn export_profile(format: ExportFormat) -> ExportProfile {
    ExportProfile {
        name: format!("profile_{format:?}"),
        format,
        pdf_intent: Some(PdfIntent::Print),
        raster: None,
        include_bleed: false,
        embed_fonts: true,
    }
}

fn request(format: ExportFormat, page_ids: Vec<PageId>) -> ExportRequest {
    ExportRequest {
        profile: export_profile(format),
        page_ids,
        purpose: ExportPurpose::UserDownload,
    }
}

fn png_request(page_ids: Vec<PageId>) -> ExportRequest {
    ExportRequest {
        profile: ExportProfile {
            raster: Some(RasterScale {
                scale: 1.0,
                dpi: Some(12),
            }),
            ..export_profile(ExportFormat::Png)
        },
        page_ids,
        purpose: ExportPurpose::AgentCritique,
    }
}

fn a4_page(id: &str, children: Vec<NodeId>) -> Page {
    Page {
        id: PageId::from(id),
        name: "A4".to_owned(),
        size: PageSize {
            width: 210.0,
            height: 297.0,
            unit: Unit::Mm,
            preset: Some(PagePreset::A4),
            orientation: lumen_core::Orientation::Portrait,
        },
        children,
        bleed: None,
        safe_area: Some(Rect {
            x: 12.0,
            y: 12.0,
            width: 186.0,
            height: 273.0,
        }),
        background: vec![Fill {
            id: PaintId::from("paint_page_bg"),
            paint: Paint::Solid {
                color: Color::Hex {
                    value: "#ffffff".to_owned(),
                },
            },
        }],
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
    node.transform = Transform {
        x: 24.0,
        y: 40.0,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(160.0, 28.0);
    node.fills = vec![Fill {
        id: PaintId::from("paint_text"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: "#123456".to_owned(),
            },
        },
    }];
    node
}

fn rect_node(id: &str) -> Node {
    let mut node = Node::new(NodeId::from(id), NodeKind::Rect);
    node.transform = Transform {
        x: 20.0,
        y: 20.0,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(40.0, 16.0);
    node.fills = vec![Fill {
        id: PaintId::from("paint_rect_fill"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: "#ffcc00".to_owned(),
            },
        },
    }];
    node.strokes = vec![Stroke {
        id: PaintId::from("paint_rect_stroke"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: "#000000".to_owned(),
            },
        },
        width: 1.0,
        width_token: None,
    }];
    node
}

fn scene_with_slot() -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_export"), "Export Demo");
    scene.pages.insert(
        PageId::from("page_a"),
        a4_page(
            "page_a",
            vec![NodeId::from("node_name"), NodeId::from("node_badge")],
        ),
    );
    scene
        .pages
        .insert(PageId::from("page_b"), a4_page("page_b", Vec::new()));
    scene.nodes.insert(
        NodeId::from("node_name"),
        text_node("node_name", "Dr. Priya Sharma"),
    );
    scene
        .nodes
        .insert(NodeId::from("node_badge"), rect_node("node_badge"));

    let mut slot = Slot::text_short(
        SlotId::from("slot_contact_name"),
        SlotKey::from("contact.full_name"),
        "Contact full name",
    );
    slot.content_type = ContentType::TextShort;
    slot.placeholder = Some("Dr. Priya Sharma".to_owned());
    slot.bound_nodes = vec![NodeId::from("node_name")];
    scene.slots.insert(slot.id.clone(), slot);
    scene
}

fn add_page_b_slot(scene: &mut Scene) {
    scene
        .pages
        .get_mut(&PageId::from("page_b"))
        .unwrap()
        .children = vec![NodeId::from("node_page_b_name")];
    scene.nodes.insert(
        NodeId::from("node_page_b_name"),
        text_node("node_page_b_name", "Page B Contact"),
    );

    let mut slot = Slot::text_short(
        SlotId::from("slot_page_b_contact_name"),
        SlotKey::from("contact.page_b_full_name"),
        "Page B contact full name",
    );
    slot.placeholder = Some("Page B Contact".to_owned());
    slot.bound_nodes = vec![NodeId::from("node_page_b_name")];
    scene.slots.insert(slot.id.clone(), slot);
}

#[test]
fn svg_export_renders_page_and_preserves_semantic_metadata() {
    let adapter = LumenExportAdapter::new();
    let scene = scene_with_slot();
    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Svg, vec![PageId::from("page_a")]),
        )
        .unwrap();

    assert_eq!(result.artifacts.len(), 1);
    assert_eq!(result.artifacts[0].mime_type, "image/svg+xml");

    let svg = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();
    assert!(svg.contains("data-lumen-document-id=\"doc_export\""));
    assert!(svg.contains("data-lumen-page-id=\"page_a\""));
    assert!(svg.contains("data-lumen-node-id=\"node_name\""));
    assert!(svg.contains("data-lumen-slot-keys=\"contact.full_name\""));
    assert!(svg.contains(">Dr. Priya Sharma</text>"));
    assert!(svg.contains("data-lumen-fill-id=\"paint_rect_fill\""));

    let sidecar = result.artifacts[0].sidecar_json.as_ref().unwrap();
    assert!(sidecar.contains("\"document_id\": \"doc_export\""));
    assert!(sidecar.contains("\"slot_key\": \"contact.full_name\""));
    assert!(sidecar.contains("\"node_id\": \"node_name\""));
}

#[test]
fn golden_dsl_brand_slot_layout_exports_svg_preview() {
    let brand_kit: BrandKit = serde_json::from_str(include_str!(
        "../../lumen-core/fixtures/brand_kits/acme_full.json"
    ))
    .unwrap();
    let mut scene = Scene::new(DocumentId::from("doc_preflight_export"), "Preflight Export");
    let compile_output = compile_dsl_into_scene(
        r#"
page page_a4
  hero autolayout(h) p(24,24) s(180,hug) fill($surface.brand) stroke($surface.brand,$stroke.width.firm) g($space.md) pad($space.md) rd($radius.md) o($opacity.subtle)
    headline text "Plan" p(0,0) s(132,hug) style($type.headline)
  slot_text text "Plan" p(24,96) s(132,48) font("Inter",16,700,left) slot(campaign.headline)
"#,
        &mut scene,
    );

    assert!(compile_output
        .compile_output
        .diagnostics
        .iter()
        .all(|diagnostic| diagnostic.diagnostic.severity != DiagnosticSeverity::Error));
    assert!(compile_output.operation_error.is_none());

    let preflight = preflight_scene(scene, Some(&brand_kit), PreflightOptions::default());
    assert!(
        preflight
            .diagnostics
            .iter()
            .all(|diagnostic| diagnostic.severity != DiagnosticSeverity::Error),
        "{:#?}",
        preflight.diagnostics
    );
    assert!(!preflight.token_operations.is_empty());
    assert!(!preflight.layout_operations.is_empty());

    let result = LumenExportAdapter::new()
        .export(
            &preflight.scene,
            &request(ExportFormat::Svg, vec![PageId::from("page_a4")]),
        )
        .unwrap();

    assert_eq!(result.artifacts.len(), 1);
    assert!(
        result.diagnostics.iter().all(|diagnostic| !matches!(
            diagnostic.code.as_str(),
            "LUME0206" | "LUME0208" | "LUME0209"
        )),
        "{:#?}",
        result.diagnostics
    );

    let svg = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();
    assert!(svg.contains("data-lumen-document-id=\"doc_preflight_export\""));
    assert!(svg.contains("data-lumen-page-id=\"page_a4\""));
    assert!(svg.contains("data-lumen-node-id=\"headline\""));
    assert!(svg.contains("data-lumen-node-id=\"slot_text\""));
    assert!(svg.contains("data-lumen-slot-keys=\"campaign.headline\""));
    assert!(svg.contains("#004D5A"));
    assert!(svg.contains("#FFFFFF"));
    assert!(svg.contains(">Plan</text>"));
}

#[test]
fn svg_export_defaults_fill_less_text_to_visible_black_with_warning() {
    let adapter = LumenExportAdapter::new();
    let fixture = include_str!("../../lumen-core/fixtures/minimal_scene.json");
    let scene: Scene = serde_json::from_str(fixture).unwrap();

    let result = adapter
        .export(&scene, &request(ExportFormat::Svg, Vec::new()))
        .unwrap();

    let svg = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();
    assert!(svg.contains("data-lumen-node-id=\"node_contact_name\""));
    assert!(svg.contains("fill=\"#000000\""));
    assert!(result.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUME0207" && diagnostic.severity == DiagnosticSeverity::Warning
    }));
}

#[test]
fn svg_export_uses_all_pages_when_request_has_no_page_filter() {
    let adapter = LumenExportAdapter::new();
    let scene = scene_with_slot();
    let result = adapter
        .export(&scene, &request(ExportFormat::Svg, Vec::new()))
        .unwrap();

    assert_eq!(result.artifacts.len(), 2);
    assert_eq!(result.artifacts[0].page_id, Some(PageId::from("page_a")));
    assert_eq!(result.artifacts[1].page_id, Some(PageId::from("page_b")));
}

#[test]
fn export_rejects_missing_pages_with_diagnostics() {
    let adapter = LumenExportAdapter::new();
    let scene = scene_with_slot();
    let error = adapter
        .export(
            &scene,
            &request(ExportFormat::Svg, vec![PageId::from("missing_page")]),
        )
        .unwrap_err();

    assert_eq!(error.code, "export.invalid_pages");
    assert!(error
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0101"));
}

#[test]
fn figma_manifest_rejects_missing_pages_like_other_export_formats() {
    let adapter = LumenExportAdapter::new();
    let scene = scene_with_slot();
    let error = adapter
        .export(
            &scene,
            &request(
                ExportFormat::FigmaManifest,
                vec![PageId::from("missing_page")],
            ),
        )
        .unwrap_err();

    assert_eq!(error.code, "export.invalid_pages");
    assert!(error
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0101"));
}

#[test]
fn token_paints_emit_export_diagnostics_instead_of_guessing_resolution() {
    let adapter = LumenExportAdapter::new();
    let mut scene = scene_with_slot();
    scene
        .nodes
        .get_mut(&NodeId::from("node_badge"))
        .unwrap()
        .fills = vec![Fill {
        id: PaintId::from("paint_token"),
        paint: Paint::Token {
            token: "brand.primary".to_owned(),
        },
    }];

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Svg, vec![PageId::from("page_a")]),
        )
        .unwrap();

    assert!(result.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "LUME0206" && diagnostic.severity == DiagnosticSeverity::Warning
    }));
}

#[test]
fn svg_export_warns_on_all_unresolved_brand_token_carriers() {
    let adapter = LumenExportAdapter::new();
    let mut scene = scene_with_slot();

    let badge = scene.nodes.get_mut(&NodeId::from("node_badge")).unwrap();
    badge.size = SizeSpec {
        width: Dimension::Token {
            token: "space.xl".to_owned(),
        },
        height: Dimension::Token {
            token: "space.md".to_owned(),
        },
    };
    badge.strokes[0].width_token = Some("stroke.width.firm".to_owned());
    badge.corner.token = Some("radius.md".to_owned());
    badge.opacity_token = Some("opacity.subtle".to_owned());
    badge.layout = Some(AutoLayoutProps {
        gap: 0.0,
        gap_token: Some("space.gap".to_owned()),
        padding: [0.0; 4],
        padding_token: Some("space.padding".to_owned()),
        grow: 0.0,
    });

    let name = scene.nodes.get_mut(&NodeId::from("node_name")).unwrap();
    if let NodeKind::Text(text) = &mut name.kind {
        text.style_token = Some("type.headline".to_owned());
    } else {
        panic!("expected text node");
    }

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Svg, vec![PageId::from("page_a")]),
        )
        .unwrap();

    let messages = result
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.code == "LUME0209")
        .map(|diagnostic| diagnostic.message.as_str())
        .collect::<Vec<_>>();

    for expected in [
        "size.width",
        "size.height",
        "stroke paint_rect_stroke width",
        "corner radius",
        "opacity",
        "layout gap",
        "layout padding",
        "text style",
    ] {
        assert!(
            messages.iter().any(|message| message.contains(expected)),
            "missing unresolved-token export warning for {expected}: {messages:#?}"
        );
    }
}

#[test]
fn png_export_returns_png_artifacts_for_required_preview_path() {
    let adapter = LumenExportAdapter::new();
    let scene = scene_with_slot();
    let result = adapter
        .export(&scene, &png_request(vec![PageId::from("page_a")]))
        .unwrap();

    assert_eq!(result.artifacts.len(), 1);
    assert_eq!(result.artifacts[0].mime_type, "image/png");
    assert!(result.artifacts[0].bytes.starts_with(b"\x89PNG\r\n\x1a\n"));
    assert!(result.artifacts[0]
        .sidecar_json
        .as_ref()
        .unwrap()
        .contains("\"slot_key\": \"contact.full_name\""));
    assert!(result
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0301"));
}

#[test]
fn early_pdf_export_returns_pdf_artifact_and_font_diagnostics() {
    let adapter = LumenExportAdapter::new();
    let scene = scene_with_slot();
    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Pdf, vec![PageId::from("page_a")]),
        )
        .unwrap();

    assert_eq!(result.artifacts.len(), 1);
    assert_eq!(result.artifacts[0].mime_type, "application/pdf");
    assert!(result.artifacts[0].bytes.starts_with(b"%PDF-1.4"));
    assert!(result.artifacts[0]
        .sidecar_json
        .as_ref()
        .unwrap()
        .contains("\"slot_key\": \"contact.full_name\""));
    assert!(result
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0402"));
}

#[test]
fn early_pdf_export_paints_page_background() {
    let adapter = LumenExportAdapter::new();
    let mut scene = scene_with_slot();
    scene
        .pages
        .get_mut(&PageId::from("page_a"))
        .unwrap()
        .background = vec![Fill {
        id: PaintId::from("paint_page_bg_brand"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: "#abcdef".to_owned(),
            },
        },
    }];

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Pdf, vec![PageId::from("page_a")]),
        )
        .unwrap();

    let pdf = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();
    assert!(pdf.contains("0.6706 0.8039 0.9373 rg\n"));
    assert!(pdf.contains("0 0 595.2756 841.8898 re f\n"));
}

#[test]
fn early_pdf_export_preserves_text_fill_color() {
    let adapter = LumenExportAdapter::new();
    let scene = scene_with_slot();

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Pdf, vec![PageId::from("page_a")]),
        )
        .unwrap();

    let pdf = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();
    assert!(pdf.contains("0.0706 0.2039 0.3373 rg\nBT /F1"));
}

#[test]
fn svg_export_diagnoses_tokenized_page_backgrounds() {
    let adapter = LumenExportAdapter::new();
    let mut scene = scene_with_slot();
    scene
        .pages
        .get_mut(&PageId::from("page_a"))
        .unwrap()
        .background = vec![Fill {
        id: PaintId::from("paint_page_bg_token"),
        paint: Paint::Token {
            token: "brand.surface".to_owned(),
        },
    }];

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Svg, vec![PageId::from("page_a")]),
        )
        .unwrap();

    assert!(result
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0208"));
}

#[test]
fn early_pdf_export_renders_stroke_only_rectangles() {
    let adapter = LumenExportAdapter::new();
    let mut scene = scene_with_slot();
    let badge = scene.nodes.get_mut(&NodeId::from("node_badge")).unwrap();
    badge.fills.clear();
    badge.strokes[0].width = 2.0;

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Pdf, vec![PageId::from("page_a")]),
        )
        .unwrap();

    let pdf = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();
    assert!(pdf.contains("5.6693 w\n"));
    assert!(pdf.contains(" re S\n"));
}

#[test]
fn early_pdf_export_renders_fill_and_stroke_rectangles() {
    let adapter = LumenExportAdapter::new();
    let scene = scene_with_slot();

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Pdf, vec![PageId::from("page_a")]),
        )
        .unwrap();

    let pdf = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();
    assert!(pdf.contains(" re B\n"));
}

#[test]
fn per_page_sidecar_filters_slots_to_exported_nodes() {
    let adapter = LumenExportAdapter::new();
    let mut scene = scene_with_slot();
    add_page_b_slot(&mut scene);

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Svg, vec![PageId::from("page_a")]),
        )
        .unwrap();

    let sidecar: Value =
        serde_json::from_str(result.artifacts[0].sidecar_json.as_ref().unwrap()).unwrap();
    let slots = sidecar["slots"].as_array().unwrap();

    assert_eq!(slots.len(), 1);
    assert_eq!(slots[0]["slot_key"], "contact.full_name");
    assert!(!result.artifacts[0]
        .sidecar_json
        .as_ref()
        .unwrap()
        .contains("contact.page_b_full_name"));
}
