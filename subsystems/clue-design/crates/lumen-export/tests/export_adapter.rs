use lumen_core::{
    compile_dsl_into_scene, preflight_scene, AutoLayoutProps, BrandKit, Color, ComputedGeometry,
    ContentType, DiagnosticSeverity, Dimension, DocumentId, ExportAdapter, ExportFormat,
    ExportProfile, ExportPurpose, ExportRequest, Fill, Node, NodeId, NodeKind, Page, PageId,
    PagePreset, PageSize, Paint, PaintId, PdfIntent, PreflightOptions, RasterScale, Rect, Scene,
    SizeSpec, Slot, SlotId, SlotKey, Stroke, TextAlign, TextNode, Transform, Unit,
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
            ..TextNode::default()
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

fn square_px_page(id: &str, children: Vec<NodeId>) -> Page {
    Page {
        id: PageId::from(id),
        name: "Square".to_owned(),
        size: PageSize {
            width: 100.0,
            height: 100.0,
            unit: Unit::Px,
            preset: Some(PagePreset::Custom),
            orientation: lumen_core::Orientation::Portrait,
        },
        children,
        bleed: None,
        safe_area: None,
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

fn scene_with_computed_rect() -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_computed_export"), "Computed Export");
    scene.pages.insert(
        PageId::from("page_square"),
        square_px_page("page_square", vec![NodeId::from("node_computed_rect")]),
    );

    let mut node = Node::new(NodeId::from("node_computed_rect"), NodeKind::Rect);
    node.size = SizeSpec::fixed(1.0, 1.0);
    node.computed = Some(ComputedGeometry {
        layout_bounds: Rect {
            x: 20.0,
            y: 30.0,
            width: 10.0,
            height: 10.0,
        },
        render_bounds: Rect {
            x: 20.0,
            y: 30.0,
            width: 10.0,
            height: 10.0,
        },
    });
    node.fills = vec![Fill {
        id: PaintId::from("paint_computed_rect"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: "#ff0000".to_owned(),
            },
        },
    }];
    scene.nodes.insert(node.id.clone(), node);
    scene
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
    assert!(svg.contains(">Dr. Priya Sharma</tspan></text>"));
    assert!(svg.contains("data-lumen-fill-id=\"paint_rect_fill\""));

    let sidecar = result.artifacts[0].sidecar_json.as_ref().unwrap();
    assert!(sidecar.contains("\"document_id\": \"doc_export\""));
    assert!(sidecar.contains("\"slot_key\": \"contact.full_name\""));
    assert!(sidecar.contains("\"node_id\": \"node_name\""));
}

#[test]
fn multiline_svg_text_uses_measured_line_boxes() {
    let adapter = LumenExportAdapter::new();
    let mut scene = Scene::new(DocumentId::from("doc_text_export"), "Text Export");
    let compile_output = compile_dsl_into_scene(
        r#"
page page_square size(360,360,px)
  headline text "AI phone agents help neurosurgeons focus on surgery" p(24,24) s(140,120) font("Inter",20,700,left) wrap_text(true) lh(1.1)
"#,
        &mut scene,
    );

    assert!(compile_output.operation_error.is_none());

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Svg, vec![PageId::from("page_square")]),
        )
        .unwrap();
    let svg = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();

    assert!(svg.matches("<tspan").count() > 1, "{svg}");
    assert!(svg.contains("letter-spacing=\"0\""));
}

#[test]
fn svg_export_honors_custom_square_page_size() {
    let adapter = LumenExportAdapter::new();
    let mut scene = Scene::new(DocumentId::from("doc_square_export"), "Square Export");
    let compile_output = compile_dsl_into_scene(
        r##"
page page_square size(1080,1080,px)
  bg rect p(0,0) s(1080,1080) fill(#0f172a)
"##,
        &mut scene,
    );

    assert!(compile_output.operation_error.is_none());
    assert!(compile_output
        .compile_output
        .diagnostics
        .iter()
        .all(|diagnostic| diagnostic.diagnostic.severity != DiagnosticSeverity::Error));

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Svg, vec![PageId::from("page_square")]),
        )
        .unwrap();
    let svg = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();

    assert!(svg.contains("width=\"1080\""));
    assert!(svg.contains("height=\"1080\""));
    assert!(svg.contains("viewBox=\"0 0 1080 1080\""));
}

#[test]
fn svg_export_uses_computed_xy_for_layouted_children() {
    let adapter = LumenExportAdapter::new();
    let mut scene = scene_with_slot();
    let node = scene.nodes.get_mut(&NodeId::from("node_badge")).unwrap();
    node.transform.x = 0.0;
    node.transform.y = 0.0;
    node.computed = Some(ComputedGeometry {
        layout_bounds: Rect {
            x: 200.0,
            y: 40.0,
            width: 80.0,
            height: 32.0,
        },
        render_bounds: Rect {
            x: 200.0,
            y: 40.0,
            width: 80.0,
            height: 32.0,
        },
    });

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Svg, vec![PageId::from("page_a")]),
        )
        .unwrap();
    let svg = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();

    assert!(svg.contains("data-lumen-node-id=\"node_badge\""));
    assert!(svg.contains("width=\"80\" height=\"32\""));
    assert!(svg.contains("transform=\"translate(200 40)\""));
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
    headline text "Plan" p(0,0) s(132,44) style($type.headline)
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
    assert!(svg.contains(">Plan</tspan></text>"));
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
        ..AutoLayoutProps::default()
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
fn png_export_uses_computed_xy_for_layouted_nodes() {
    let adapter = LumenExportAdapter::new();
    let scene = scene_with_computed_rect();
    let result = adapter
        .export(&scene, &png_request(vec![PageId::from("page_square")]))
        .unwrap();

    let rgba = decode_png_rgba(&result.artifacts[0].bytes);
    assert_eq!(rgba.width, 100);
    assert_eq!(rgba.height, 100);
    assert_eq!(rgba.pixel(25, 35), [255, 0, 0, 255]);
    assert_eq!(rgba.pixel(5, 5), [255, 255, 255, 255]);
}

#[test]
fn png_export_rasterizes_text_nodes_from_svg_baseline() {
    let adapter = LumenExportAdapter::new();
    let mut scene = Scene::new(DocumentId::from("doc_png_text"), "PNG Text");
    scene.pages.insert(
        PageId::from("page_square"),
        square_px_page("page_square", vec![NodeId::from("node_text")]),
    );

    let mut node = text_node("node_text", "Readable PNG text");
    node.transform = Transform {
        x: 12.0,
        y: 24.0,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(180.0, 48.0);
    if let NodeKind::Text(text) = &mut node.kind {
        text.font_family = "Arial".to_owned();
        text.font_size = 20.0;
        text.line_height = 1.1;
        text.wrap = lumen_core::TextWrap::NoWrap;
    }
    node.fills = vec![Fill {
        id: PaintId::from("paint_text_dark"),
        paint: Paint::Solid {
            color: Color::Hex {
                value: "#111827".to_owned(),
            },
        },
    }];
    scene.nodes.insert(NodeId::from("node_text"), node);

    let result = adapter
        .export(&scene, &png_request(vec![PageId::from("page_square")]))
        .unwrap();

    let rgba = decode_png_rgba(&result.artifacts[0].bytes);
    let dark_pixels = rgba
        .rgba
        .chunks_exact(4)
        .filter(|pixel| pixel[3] > 0 && pixel[0] < 120 && pixel[1] < 140 && pixel[2] < 160)
        .count();

    assert!(
        dark_pixels > 20,
        "PNG raster output should contain rendered text pixels, found {dark_pixels}"
    );
    assert!(
        result
            .diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code != "LUME0304"),
        "text nodes should not be reported as unsupported by PNG export"
    );
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
fn early_pdf_export_uses_computed_xy_for_layouted_nodes() {
    let adapter = LumenExportAdapter::new();
    let scene = scene_with_computed_rect();
    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Pdf, vec![PageId::from("page_square")]),
        )
        .unwrap();

    let pdf = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();
    assert!(pdf.contains("20 60 10 10 re f\n"), "{pdf}");
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
fn early_pdf_export_uses_measured_text_lines() {
    let adapter = LumenExportAdapter::new();
    let mut scene = Scene::new(DocumentId::from("doc_pdf_text"), "PDF Text");
    scene.pages.insert(
        PageId::from("page_square"),
        square_px_page("page_square", vec![NodeId::from("node_text")]),
    );
    let mut node = text_node(
        "node_text",
        "AI phone agents help neurosurgeons focus on surgery",
    );
    node.size = SizeSpec::fixed(110.0, 120.0);
    if let NodeKind::Text(text) = &mut node.kind {
        text.font_size = 20.0;
        text.line_height = 1.1;
        text.wrap = lumen_core::TextWrap::Wrap;
    }
    scene.nodes.insert(NodeId::from("node_text"), node);

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Pdf, vec![PageId::from("page_square")]),
        )
        .unwrap();

    let pdf = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();
    assert!(pdf.matches(" Tj\n").count() > 1, "{pdf}");
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

struct DecodedPng {
    width: u32,
    height: u32,
    rgba: Vec<u8>,
}

impl DecodedPng {
    fn pixel(&self, x: u32, y: u32) -> [u8; 4] {
        let index = ((y * self.width + x) * 4) as usize;
        [
            self.rgba[index],
            self.rgba[index + 1],
            self.rgba[index + 2],
            self.rgba[index + 3],
        ]
    }
}

fn decode_png_rgba(bytes: &[u8]) -> DecodedPng {
    assert_eq!(&bytes[..8], b"\x89PNG\r\n\x1a\n");
    let pixmap = resvg::tiny_skia::Pixmap::decode_png(bytes).expect("PNG decodes");
    DecodedPng {
        width: pixmap.width(),
        height: pixmap.height(),
        rgba: pixmap.data().to_vec(),
    }
}
