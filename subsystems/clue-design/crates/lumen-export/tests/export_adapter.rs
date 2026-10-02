use lumen_core::{
    collect_scene_token_references, compile_dsl_into_scene, preflight_scene, AssetId, AssetRecord,
    AutoLayoutProps, BrandKit, Color, ComputedGeometry, ContentType, DiagnosticSeverity,
    DiagnosticSubject, Dimension, DocumentId, ExportAdapter, ExportFormat, ExportProfile,
    ExportPurpose, ExportRequest, Fill, ImageNode, Node, NodeId, NodeKind, Page, PageId,
    PagePreset, PageSize, Paint, PaintId, PdfIntent, PreflightOptions, RasterScale, Rect, Scene,
    SizeSpec, Slot, SlotId, SlotKey, Stroke, TextAlign, TextDirection, TextNode, Transform, Unit,
};
use lumen_export::LumenExportAdapter;
use serde_json::Value;

const ACME_BRAND_KIT: &str = include_str!("../../lumen-core/fixtures/brand_kits/acme_full.json");
const GENERATED_RASTER_ASSET: &str =
    include_str!("../../lumen-core/fixtures/assets/generated_raster_asset.json");
const PHASE_F_MANIFEST: &str =
    include_str!("../../lumen-core/fixtures/conformance/phase_f_manifest.json");
const TOKENIZED_LINKEDIN_SQUARE: &str =
    include_str!("../../lumen-core/fixtures/brand_templates/tokenized_linkedin_square.lumen");

fn export_profile(format: ExportFormat) -> ExportProfile {
    ExportProfile {
        name: format!("profile_{format:?}"),
        format,
        pdf_intent: Some(PdfIntent::Print),
        raster: None,
        include_bleed: false,
        embed_fonts: true,
    include_marks: false,
    imposition: None,
    proof: false,
    color: None,
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
            source: None,
            output: None,
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
    node.strokes = vec![Stroke::solid(
        PaintId::from("paint_rect_stroke"),
        Paint::Solid {
            color: Color::Hex {
                value: "#000000".to_owned(),
            },
        },
        1.0,
    )];
    node
}

fn image_node(id: &str, asset_id: &str) -> Node {
    let mut node = Node::new(
        NodeId::from(id),
        NodeKind::Image(ImageNode {
            asset_id: AssetId::from(asset_id),
            alt: Some("Print guardrail image".to_owned()),
        }),
    );
    node.transform = Transform {
        x: 20.0,
        y: 120.0,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(180.0, 120.0);
    node
}

fn square_px_page(id: &str, children: Vec<NodeId>) -> Page {
    custom_px_page(id, 100.0, 100.0, children)
}

fn custom_px_page(id: &str, width: f64, height: f64, children: Vec<NodeId>) -> Page {
    Page {
        id: PageId::from(id),
        name: "Custom".to_owned(),
        size: PageSize {
            width,
            height,
            unit: Unit::Px,
            preset: Some(PagePreset::Custom),
            orientation: if width > height {
                lumen_core::Orientation::Landscape
            } else {
                lumen_core::Orientation::Portrait
            },
            source: None,
            output: None,
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
    assert!(
        svg.contains("font-family=\"Inter, Arial, Helvetica, sans-serif\""),
        "{svg}"
    );
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
fn svg_export_a4_uses_physical_size_and_pt_viewbox() {
    let adapter = LumenExportAdapter::new();
    let mut scene = Scene::new(DocumentId::from("doc_a4_export"), "A4 Export");
    let compile_output = compile_dsl_into_scene(
        r##"
page page_a4
  bg rect p(0,0) s(595.2756,841.8898) fill(#ffffff)
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
            &request(ExportFormat::Svg, vec![PageId::from("page_a4")]),
        )
        .unwrap();
    let svg = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();

    assert!(svg.contains("width=\"210mm\""), "{svg}");
    assert!(svg.contains("height=\"297mm\""), "{svg}");
    assert!(svg.contains("viewBox=\"0 0 595.2756 841.8898\""), "{svg}");
}

#[test]
fn png_export_without_rasterizer_fails_closed() {
    // Since slice A4 the resvg SVG-string path is gone: PNG export without
    // an injected scene rasterizer (composed from lumen-skia at the
    // application boundary) must error, never silently degrade. The
    // rasterizing coverage lives in lumen-skia's raster_export tests.
    let adapter = LumenExportAdapter::new();
    let scene = scene_with_slot();
    let error = adapter
        .export(&scene, &png_request(vec![PageId::from("page_a")]))
        .expect_err("png export without rasterizer must fail");
    assert_eq!(error.code, "export.png_rasterizer_missing");
}

#[test]
fn png_export_over_raster_budget_fails_before_rasterizing() {
    // A4 @ 300 dpi @ 5x is ~218 MP (~870 MB RGBA) — above the raster
    // budget. The guard must fire before any rasterization work, so a
    // rasterizer that panics on use proves the ordering.
    #[derive(Debug)]
    struct PanickingRasterizer;
    impl lumen_export::PageRasterizer for PanickingRasterizer {
        fn rasterize_page(
            &self,
            _scene: &Scene,
            _page_id: &PageId,
            _width_px: u32,
            _height_px: u32,
            _resolver: Option<&dyn lumen_export::AssetByteResolver>,
        ) -> Result<lumen_export::RasterizedPage, lumen_export::RasterizeError> {
            panic!("raster budget guard must fire before rasterization");
        }
    }

    let adapter =
        LumenExportAdapter::new().with_rasterizer(std::sync::Arc::new(PanickingRasterizer));
    let scene = scene_with_slot();
    let request = ExportRequest {
        profile: ExportProfile {
            raster: Some(RasterScale {
                scale: 5.0,
                dpi: Some(300),
            }),
            ..export_profile(ExportFormat::Png)
        },
        page_ids: vec![PageId::from("page_a")],
        purpose: ExportPurpose::UserDownload,
    };
    let error = adapter
        .export(&scene, &request)
        .expect_err("218 MP raster must exceed the export budget");
    assert_eq!(error.code, "export.raster_budget_exceeded");
    assert!(
        error.message.contains("lower the profile's raster scale or dpi"),
        "{}",
        error.message
    );
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
        text_lines: Vec::new(),
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
fn svg_export_scales_a_library_icon_to_its_node_box() {
    // Step 8: a `svg(icon:name)` node carries a 24×24 viewBox; the export must fit it to
    // the node box (here 48×48 → uniform 2× scale) so the icon renders at the node's size.
    let adapter = LumenExportAdapter::new();
    let mut scene = Scene::new(DocumentId::from("doc_icon"), "Icon");
    compile_dsl_into_scene(
        "page page_a4\n  mark svg(icon:check) p(0,0) s(48,48) fill(#111827)",
        &mut scene,
    );
    let node = scene.nodes.get_mut(&NodeId::from("mark")).unwrap();
    node.computed = Some(ComputedGeometry {
        layout_bounds: Rect {
            x: 0.0,
            y: 0.0,
            width: 48.0,
            height: 48.0,
        },
        render_bounds: Rect {
            x: 0.0,
            y: 0.0,
            width: 48.0,
            height: 48.0,
        },
        text_lines: Vec::new(),
    });

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Svg, vec![PageId::from("page_a4")]),
        )
        .unwrap();
    let svg = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();

    assert!(svg.contains("scale(2)"), "missing icon fit scale: {svg}");
    assert!(svg.contains("M9 16.17"), "missing icon path: {svg}");
}

#[test]
fn golden_dsl_brand_slot_layout_exports_svg_preview() {
    let brand_kit: BrandKit = serde_json::from_str(ACME_BRAND_KIT).unwrap();
    let mut scene = Scene::new(DocumentId::from("doc_preflight_export"), "Preflight Export");
    let compile_output = compile_dsl_into_scene(
        r#"
page page_a4
  hero autolayout(h) p(24,24) s(180,hug) fill($surface.brand) stroke($surface.brand,$stroke.width.firm) g($space.md) pad($space.md) rd($radius.md) o($opacity.subtle)
    headline text "Plan" p(0,0) s(132,48) style($type.body.small)
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
    assert!(svg.contains("fill=\"#"));
    assert!(!svg.contains("$surface."));
    assert!(!svg.contains("$type."));
    assert!(svg.contains(">Plan</tspan></text>"));
}

#[test]
fn phase_c_tokenized_brand_template_exports_resolved_svg() {
    let brand_kit: BrandKit = serde_json::from_str(ACME_BRAND_KIT).unwrap();
    let mut scene = Scene::new(
        DocumentId::from("doc_phase_c_linkedin_square_export"),
        "Phase C LinkedIn Square Export",
    );
    let compile_output = compile_dsl_into_scene(TOKENIZED_LINKEDIN_SQUARE, &mut scene);

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
    assert!(
        collect_scene_token_references(&preflight.scene).is_empty(),
        "preflight should resolve every BrandKit token before export"
    );

    let result = LumenExportAdapter::new()
        .export(
            &preflight.scene,
            &request(ExportFormat::Svg, vec![PageId::from("linkedin_square")]),
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
    assert!(svg.contains("width=\"1080\""));
    assert!(svg.contains("height=\"1080\""));
    assert!(svg.contains("viewBox=\"0 0 1080 1080\""));
    assert!(svg.contains("data-lumen-document-id=\"doc_phase_c_linkedin_square_export\""));
    assert!(svg.contains("data-lumen-page-id=\"linkedin_square\""));
    assert!(svg.contains("data-lumen-node-id=\"headline\""));
    assert!(svg.contains("data-lumen-slot-keys=\"campaign.headline\""));
    assert!(svg.contains("fill=\"#"));
    assert!(!svg.contains("$surface."));
    assert!(!svg.contains("$type."));
    assert!(svg.contains(">Surgery first.</tspan></text>"));
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
fn print_pdf_profile_preserves_custom_size_profile_and_sidecar_metadata() {
    let adapter = LumenExportAdapter::new()
        .with_pdf_renderer(std::sync::Arc::new(RecordingPdfRenderer::default()));
    let mut scene = scene_with_slot();
    add_page_b_slot(&mut scene);
    scene.pages.insert(
        PageId::from("page_square_custom"),
        custom_px_page(
            "page_square_custom",
            1080.0,
            1080.0,
            vec![NodeId::from("node_square_label")],
        ),
    );
    scene.nodes.insert(
        NodeId::from("node_square_label"),
        text_node("node_square_label", "Square custom output"),
    );

    let request = ExportRequest {
        profile: ExportProfile {
            name: "print_pdf_custom_conformance".to_owned(),
            format: ExportFormat::Pdf,
            pdf_intent: Some(PdfIntent::Print),
            raster: None,
            include_bleed: true,
            embed_fonts: true,
        include_marks: false,
        imposition: None,
        proof: false,
        color: None,
        },
        page_ids: vec![PageId::from("page_a"), PageId::from("page_square_custom")],
        purpose: ExportPurpose::UserDownload,
    };

    let result = adapter.export(&scene, &request).unwrap();

    assert_eq!(result.artifacts.len(), 1);
    assert_eq!(result.artifacts[0].mime_type, "application/pdf");
    assert!(result
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0411"));
    assert!(result
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0412"));

    let sidecar: Value =
        serde_json::from_str(result.artifacts[0].sidecar_json.as_ref().unwrap()).unwrap();
    assert_eq!(sidecar["profile_name"], "print_pdf_custom_conformance");
    assert_eq!(sidecar["pages"].as_array().unwrap().len(), 2);
    assert_eq!(sidecar["pages"][0]["page_id"], "page_a");
    assert_eq!(sidecar["pages"][1]["page_id"], "page_square_custom");
    assert!(sidecar["nodes"]
        .as_array()
        .unwrap()
        .iter()
        .any(|node| node["node_id"] == "node_square_label"));
    assert!(sidecar["slots"]
        .as_array()
        .unwrap()
        .iter()
        .any(|slot| slot["slot_key"] == "contact.full_name"));
    assert!(!sidecar["slots"]
        .as_array()
        .unwrap()
        .iter()
        .any(|slot| slot["slot_key"] == "contact.page_b_full_name"));
}


#[test]
fn print_pdf_warns_for_explicit_multi_page_and_mixed_page_sizes() {
    let adapter = LumenExportAdapter::new()
        .with_pdf_renderer(std::sync::Arc::new(RecordingPdfRenderer::default()));
    let mut scene = Scene::new(DocumentId::from("doc_pdf_pagination"), "PDF Pagination");

    let mut square = custom_px_page("page_square", 1080.0, 1080.0, Vec::new());
    square.safe_area = Some(Rect {
        x: 72.0,
        y: 72.0,
        width: 936.0,
        height: 936.0,
    });
    let mut wide = custom_px_page("page_wide", 1200.0, 628.0, Vec::new());
    wide.safe_area = Some(Rect {
        x: 48.0,
        y: 48.0,
        width: 1104.0,
        height: 532.0,
    });
    scene.pages.insert(PageId::from("page_square"), square);
    scene.pages.insert(PageId::from("page_wide"), wide);

    let result = adapter
        .export(
            &scene,
            &ExportRequest {
                profile: ExportProfile {
                    name: "print_pdf_multi_page".to_owned(),
                    format: ExportFormat::Pdf,
                    pdf_intent: Some(PdfIntent::Print),
                    raster: None,
                    include_bleed: false,
                    embed_fonts: false,
                include_marks: false,
                imposition: None,
                proof: false,
                color: None,
                },
                page_ids: vec![PageId::from("page_square"), PageId::from("page_wide")],
                purpose: ExportPurpose::UserDownload,
            },
        )
        .unwrap();

    for expected in ["LUME0419", "LUME0420"] {
        assert!(
            result
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == expected),
            "missing {expected}: {:#?}",
            result.diagnostics
        );
    }
}

#[test]
fn print_pdf_warns_for_image_dpi_gaps() {
    let adapter = LumenExportAdapter::new()
        .with_pdf_renderer(std::sync::Arc::new(RecordingPdfRenderer::default()));
    let mut scene = Scene::new(
        DocumentId::from("doc_pdf_print_guardrails"),
        "PDF Print Guardrails",
    );
    let mut page = custom_px_page(
        "page_print_guardrails",
        1080.0,
        1080.0,
        vec![
            NodeId::from("node_rtl_text"),
            NodeId::from("node_low_dpi_image"),
            NodeId::from("node_missing_dpi_image"),
        ],
    );
    page.safe_area = Some(Rect {
        x: 72.0,
        y: 72.0,
        width: 936.0,
        height: 936.0,
    });
    scene
        .pages
        .insert(PageId::from("page_print_guardrails"), page);

    let mut rtl_node = text_node("node_rtl_text", "שלום neurosurgery");
    if let NodeKind::Text(text) = &mut rtl_node.kind {
        text.direction = TextDirection::Rtl;
    }
    scene.nodes.insert(NodeId::from("node_rtl_text"), rtl_node);

    let low_dpi_asset: AssetRecord = serde_json::from_str(GENERATED_RASTER_ASSET).unwrap();
    scene
        .assets
        .insert(AssetId::from("asset_generated_hero"), low_dpi_asset.clone());
    let mut missing_dpi_asset = low_dpi_asset;
    missing_dpi_asset.id = AssetId::from("asset_missing_dpi");
    if let Some(raster) = &mut missing_dpi_asset.raster {
        raster.dpi_x = None;
        raster.dpi_y = None;
    }
    scene
        .assets
        .insert(AssetId::from("asset_missing_dpi"), missing_dpi_asset);

    scene.nodes.insert(
        NodeId::from("node_low_dpi_image"),
        image_node("node_low_dpi_image", "asset_generated_hero"),
    );
    scene.nodes.insert(
        NodeId::from("node_missing_dpi_image"),
        image_node("node_missing_dpi_image", "asset_missing_dpi"),
    );

    let result = adapter
        .export(
            &scene,
            &ExportRequest {
                profile: ExportProfile {
                    name: "print_pdf_guardrails".to_owned(),
                    format: ExportFormat::Pdf,
                    pdf_intent: Some(PdfIntent::Print),
                    raster: None,
                    include_bleed: false,
                    embed_fonts: false,
                include_marks: false,
                imposition: None,
                proof: false,
                color: None,
                },
                page_ids: vec![PageId::from("page_print_guardrails")],
                purpose: ExportPurpose::UserDownload,
            },
        )
        .unwrap();

    // LUME0413/0414 (bidi + non-Latin coverage) retired with the early
    // vector writer: the Skia renderers shape bidi and embed real fonts,
    // with fallbacks declared as LUMS010x. The image-DPI metadata checks
    // are paint-independent and remain.
    for expected in ["LUME0415", "LUME0416"] {
        assert!(
            result
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == expected),
            "missing {expected}: {:#?}",
            result.diagnostics
        );
    }
}

#[test]
fn print_pdf_warns_when_required_slot_node_is_outside_safe_area() {
    let adapter = LumenExportAdapter::new()
        .with_pdf_renderer(std::sync::Arc::new(RecordingPdfRenderer::default()));
    let mut scene = Scene::new(
        DocumentId::from("doc_pdf_slot_safe_area"),
        "PDF Slot Safe Area",
    );
    let mut page = custom_px_page(
        "page_slot_safe_area",
        1080.0,
        1080.0,
        vec![NodeId::from("node_required_slot")],
    );
    page.safe_area = Some(Rect {
        x: 72.0,
        y: 72.0,
        width: 936.0,
        height: 936.0,
    });
    scene
        .pages
        .insert(PageId::from("page_slot_safe_area"), page);
    scene.nodes.insert(
        NodeId::from("node_required_slot"),
        text_node("node_required_slot", "Book a demo"),
    );

    let mut slot = Slot::text_short(
        SlotId::from("slot_required_cta"),
        SlotKey::from("campaign.cta"),
        "Campaign CTA",
    );
    slot.bound_nodes = vec![NodeId::from("node_required_slot")];
    slot.required = true;
    scene.slots.insert(slot.id.clone(), slot);

    let result = adapter
        .export(
            &scene,
            &ExportRequest {
                profile: ExportProfile {
                    name: "print_pdf_slot_safe_area".to_owned(),
                    format: ExportFormat::Pdf,
                    pdf_intent: Some(PdfIntent::Print),
                    raster: None,
                    include_bleed: false,
                    embed_fonts: false,
                include_marks: false,
                imposition: None,
                proof: false,
                color: None,
                },
                page_ids: vec![PageId::from("page_slot_safe_area")],
                purpose: ExportPurpose::UserDownload,
            },
        )
        .unwrap();

    assert!(
        result.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "LUME0417"
                && diagnostic.subject
                    == Some(DiagnosticSubject::Slot(SlotId::from("slot_required_cta")))
        }),
        "{:#?}",
        result.diagnostics
    );
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

#[test]
fn svg_all_pages_sidecars_preserve_profile_and_page_specific_slot_mappings() {
    let adapter = LumenExportAdapter::new();
    let mut scene = scene_with_slot();
    add_page_b_slot(&mut scene);
    let request = ExportRequest {
        profile: ExportProfile {
            name: "svg_all_pages_conformance".to_owned(),
            format: ExportFormat::Svg,
            pdf_intent: None,
            raster: None,
            include_bleed: false,
            embed_fonts: false,
        include_marks: false,
        imposition: None,
        proof: false,
        color: None,
        },
        page_ids: Vec::new(),
        purpose: ExportPurpose::UserDownload,
    };

    let result = adapter.export(&scene, &request).unwrap();

    assert_eq!(result.artifacts.len(), 2);
    for artifact in &result.artifacts {
        let sidecar: Value = serde_json::from_str(artifact.sidecar_json.as_ref().unwrap()).unwrap();
        assert_eq!(sidecar["profile_name"], "svg_all_pages_conformance");
        assert_eq!(sidecar["pages"].as_array().unwrap().len(), 1);
        assert_eq!(
            sidecar["pages"][0]["page_id"],
            artifact.page_id.as_ref().unwrap().as_str()
        );
    }

    let page_a_sidecar: Value =
        serde_json::from_str(result.artifacts[0].sidecar_json.as_ref().unwrap()).unwrap();
    let page_b_sidecar: Value =
        serde_json::from_str(result.artifacts[1].sidecar_json.as_ref().unwrap()).unwrap();

    assert!(page_a_sidecar["slots"]
        .as_array()
        .unwrap()
        .iter()
        .any(|slot| slot["slot_key"] == "contact.full_name"));
    assert!(!page_a_sidecar["slots"]
        .as_array()
        .unwrap()
        .iter()
        .any(|slot| slot["slot_key"] == "contact.page_b_full_name"));
    assert!(page_b_sidecar["slots"]
        .as_array()
        .unwrap()
        .iter()
        .any(|slot| slot["slot_key"] == "contact.page_b_full_name"));
    assert!(!page_b_sidecar["slots"]
        .as_array()
        .unwrap()
        .iter()
        .any(|slot| slot["slot_key"] == "contact.full_name"));
}

#[derive(Debug)]
struct PhaseFPageCase {
    id: String,
    page_id: PageId,
    width: f64,
    height: f64,
    unit: Unit,
    preset: PagePreset,
    orientation: lumen_core::Orientation,
    node_id: NodeId,
    node_x: f64,
    node_y: f64,
    node_width: f64,
    node_height: f64,
}

#[test]
fn phase_f_manifest_page_sizes_export_with_canonical_dimensions() {
    let adapter = LumenExportAdapter::new();

    for case in phase_f_page_cases() {
        let scene = scene_for_phase_f_case(&case);

        let svg_result = adapter
            .export(
                &scene,
                &request(ExportFormat::Svg, vec![case.page_id.clone()]),
            )
            .unwrap();
        let svg = std::str::from_utf8(&svg_result.artifacts[0].bytes).unwrap();
        let view_box = parse_svg_view_box(svg);
        assert_close(view_box[2], case.width, &format!("{} svg width", case.id));
        assert_close(view_box[3], case.height, &format!("{} svg height", case.id));
        assert!(
            svg.contains(&format!("data-lumen-node-id=\"{}\"", case.node_id)),
            "{} missing probe node in SVG",
            case.id
        );
        assert!(
            svg.contains(&format!(
                "transform=\"translate({} {})\"",
                fmt_test(case.node_x),
                fmt_test(case.node_y)
            )),
            "{} should preserve probe node position in SVG: {svg}",
            case.id
        );

        // PDF dimension conformance for these cases is pinned where the
        // PDF is actually produced now: pdf_boxes unit tests (exact box
        // math), lumen-skia's adapter tests, and the API dimension
        // regression (test_api.py) — the portable crate no longer renders
        // PDFs itself (D5).
    }
}

fn phase_f_page_cases() -> Vec<PhaseFPageCase> {
    let manifest: Value = serde_json::from_str(PHASE_F_MANIFEST).unwrap();
    manifest["artifacts"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|artifact| {
            let page = artifact.get("page")?;
            let probe = artifact.get("probe_node")?;
            Some(PhaseFPageCase {
                id: artifact["id"].as_str().unwrap().to_owned(),
                page_id: PageId::from(page["id"].as_str().unwrap()),
                width: page["width"].as_f64().unwrap(),
                height: page["height"].as_f64().unwrap(),
                unit: unit_from_manifest(page["unit"].as_str().unwrap()),
                preset: preset_from_manifest(page["preset"].as_str().unwrap()),
                orientation: orientation_from_manifest(page["orientation"].as_str().unwrap()),
                node_id: NodeId::from(probe["id"].as_str().unwrap()),
                node_x: probe["x"].as_f64().unwrap(),
                node_y: probe["y"].as_f64().unwrap(),
                node_width: probe["width"].as_f64().unwrap(),
                node_height: probe["height"].as_f64().unwrap(),
            })
        })
        .collect()
}

fn scene_for_phase_f_case(case: &PhaseFPageCase) -> Scene {
    let doc_id = format!("doc_{}", case.id);
    let mut scene = Scene::new(DocumentId::from(doc_id.as_str()), case.id.clone());
    scene.pages.insert(
        case.page_id.clone(),
        Page {
            id: case.page_id.clone(),
            name: case.id.clone(),
            size: PageSize {
                width: case.width,
                height: case.height,
                unit: case.unit.clone(),
                preset: Some(case.preset.clone()),
                orientation: case.orientation.clone(),
                source: None,
                output: None,
            },
            children: vec![case.node_id.clone()],
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
        },
    );

    let mut node = rect_node(case.node_id.as_str());
    node.transform = Transform {
        x: case.node_x,
        y: case.node_y,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(case.node_width, case.node_height);
    scene.nodes.insert(case.node_id.clone(), node);
    scene
}

fn unit_from_manifest(value: &str) -> Unit {
    match value {
        "px" => Unit::Px,
        "mm" => Unit::Mm,
        "in" => Unit::In,
        other => panic!("unsupported manifest unit {other}"),
    }
}

fn preset_from_manifest(value: &str) -> PagePreset {
    match value {
        "a4" => PagePreset::A4,
        "us_letter" => PagePreset::UsLetter,
        "custom" => PagePreset::Custom,
        "linkedin_ad" => PagePreset::LinkedinAd,
        "envelope_dl" => PagePreset::EnvelopeDl,
        other => panic!("unsupported manifest preset {other}"),
    }
}

fn orientation_from_manifest(value: &str) -> lumen_core::Orientation {
    match value {
        "portrait" => lumen_core::Orientation::Portrait,
        "landscape" => lumen_core::Orientation::Landscape,
        other => panic!("unsupported manifest orientation {other}"),
    }
}

fn parse_svg_view_box(svg: &str) -> [f64; 4] {
    let start = svg.find("viewBox=\"").unwrap() + "viewBox=\"".len();
    let end = start + svg[start..].find('"').unwrap();
    let values = svg[start..end]
        .split_whitespace()
        .map(|value| value.parse::<f64>().unwrap())
        .collect::<Vec<_>>();
    [values[0], values[1], values[2], values[3]]
}



fn assert_close(actual: f64, expected: f64, label: &str) {
    assert!(
        (actual - expected).abs() < 0.01,
        "{label}: expected {expected}, got {actual}"
    );
}

fn fmt_test(value: f64) -> String {
    if value.fract().abs() < f64::EPSILON {
        format!("{}", value as i64)
    } else {
        format!("{value:.4}")
            .trim_end_matches('0')
            .trim_end_matches('.')
            .to_owned()
    }
}

/// Skia clamps an oversized uniform corner radius to half the SMALLER
/// dimension (a stadium); SVG's <rect rx ry> clamps per-axis independently,
/// which would turn pill badges/buttons into full ellipses on export while
/// the canvas shows stadiums (user-reported disparity). The exporter must
/// pre-clamp to match Skia.
#[test]
fn oversized_corner_radius_exports_as_a_stadium_not_an_ellipse() {
    let adapter = LumenExportAdapter::new();
    let mut scene = Scene::new(DocumentId::from("doc_pill_export"), "Pill Export");
    let mut pill = rect_node("node_pill");
    pill.size = SizeSpec::fixed(40.0, 16.0);
    pill.corner = lumen_core::CornerRadii {
        top_left: 9999.0,
        top_right: 9999.0,
        bottom_right: 9999.0,
        bottom_left: 9999.0,
        token: None,
    };
    scene.pages.insert(
        PageId::from("page_pill"),
        square_px_page("page_pill", vec![NodeId::from("node_pill")]),
    );
    scene.nodes.insert(pill.id.clone(), pill);

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Svg, vec![PageId::from("page_pill")]),
        )
        .unwrap();
    let svg = std::str::from_utf8(&result.artifacts[0].bytes).unwrap();

    // Half the smaller dimension (16/2), matching Skia's stadium clamp.
    assert!(
        svg.contains("rx=\"8\" ry=\"8\""),
        "expected the Skia-matching clamped radius, got: {svg}"
    );
    assert!(!svg.contains("rx=\"9999\""), "raw oversized radius leaked");
}

#[test]
fn pdf_export_without_renderer_fails_loudly() {
    // D5: the early hand-rolled vector writer is deleted; an adapter
    // without an injected renderer is a composition bug, same as PNG.
    let adapter = LumenExportAdapter::new();
    let scene = scene_with_slot();
    let error = adapter
        .export(
            &scene,
            &request(ExportFormat::Pdf, vec![PageId::from("page_a")]),
        )
        .unwrap_err();
    assert_eq!(error.code, "export.pdf_renderer_missing");
}

// ---------------------------------------------------------------------------
// Print W0: raster-flattened PDF through the injected ScenePdfRenderer seam.
// ---------------------------------------------------------------------------

/// A tiny but structurally valid PDF (catalog + pages + N empty pages)
/// so the adapter's lopdf box post-process can parse and rewrite it.
fn minimal_pdf(page_count: usize) -> Vec<u8> {
    use lopdf::{dictionary, Document, Object};
    let mut document = Document::with_version("1.4");
    let pages_id = document.new_object_id();
    let kids: Vec<Object> = (0..page_count)
        .map(|_| {
            let page_id = document.add_object(dictionary! {
                "Type" => "Page",
                "Parent" => Object::Reference(pages_id),
                "MediaBox" => vec![0.into(), 0.into(), 100.into(), 100.into()],
            });
            Object::Reference(page_id)
        })
        .collect();
    document.objects.insert(
        pages_id,
        Object::Dictionary(dictionary! {
            "Type" => "Pages",
            "Kids" => kids,
            "Count" => page_count as i64,
        }),
    );
    let catalog_id = document.add_object(dictionary! {
        "Type" => "Catalog",
        "Pages" => Object::Reference(pages_id),
    });
    document.trailer.set("Root", Object::Reference(catalog_id));
    let mut bytes = Vec::new();
    document.save_to(&mut bytes).unwrap();
    bytes
}

#[derive(Debug, Default)]
struct RecordingPdfRenderer {
    calls: std::sync::Mutex<Vec<(Vec<PageId>, u16, bool)>>,
    fail: bool,
    /// Deliberately misreport painted page sizes — exercises the
    /// adapter's painted-vs-declared geometry tripwire.
    lie_about_geometry: bool,
}

impl lumen_export::ScenePdfRenderer for RecordingPdfRenderer {
    fn render_pdf(
        &self,
        scene: &Scene,
        page_ids: &[PageId],
        options: &lumen_export::PdfRenderOptions,
        _resolver: Option<&dyn lumen_export::AssetByteResolver>,
    ) -> Result<lumen_export::RenderedPdf, lumen_export::RasterizeError> {
        self.calls
            .lock()
            .unwrap()
            .push((page_ids.to_vec(), options.dpi, options.include_bleed));
        if self.fail {
            return Err(lumen_export::RasterizeError::new(
                "raster.page_missing",
                "forced failure",
            ));
        }
        Ok(lumen_export::RenderedPdf {
            // Must be a parseable PDF: the adapter's box post-process
            // rewrites page boxes on whatever the renderer returns.
            bytes: minimal_pdf(page_ids.len().max(1)),
            // Renderers own their mode declaration (LUME0426/0427 in the
            // real impls); the adapter must pass it through untouched.
            diagnostics: vec![lumen_core::Diagnostic::advice(
                lumen_core::Phase::Export,
                "TESTMODE",
                "fake renderer mode declaration",
                None,
            )],
            // The seam contract: pages report the geometry that was
            // actually painted. The adapter verifies this against the
            // declared boxes, so the fake computes it the same way the
            // real renderers do (page box + per-page print margin).
            pages: page_ids
                .iter()
                .map(|page_id| {
                    let (width_pt, height_pt) = if self.lie_about_geometry {
                        (100.0, 100.0)
                    } else {
                        let page = scene.pages.get(page_id).expect("fake renders known pages");
                        let margin = lumen_export::print_margin_for_page(
                            page,
                            options.include_bleed,
                            options.include_marks,
                            options.proof_label.is_some(),
                        );
                        let boxes = lumen_export::page_boxes_with_margin(
                            page,
                            options.include_bleed,
                            margin,
                        );
                        (
                            (boxes.media[2] - boxes.media[0]) as f32,
                            (boxes.media[3] - boxes.media[1]) as f32,
                        )
                    };
                    lumen_export::RenderedPdfPage {
                        page_id: page_id.clone(),
                        width_pt,
                        height_pt,
                        width_px: 400,
                        height_px: 400,
                    }
                })
                .collect(),
        })
    }
}

#[test]
fn injected_flattener_replaces_stub_pdf_and_declares_rasterization() {
    let renderer = std::sync::Arc::new(RecordingPdfRenderer::default());
    let adapter = LumenExportAdapter::new().with_pdf_renderer(renderer.clone());
    let scene = scene_with_slot();

    let result = adapter
        .export(
            &scene,
            &request(ExportFormat::Pdf, vec![PageId::from("page_a")]),
        )
        .unwrap();

    assert_eq!(result.artifacts.len(), 1);
    assert_eq!(result.artifacts[0].mime_type, "application/pdf");
    // L3: the adapter's post-process writes the full print box set with
    // the EXACT scene geometry (page_a is A4: 210x297mm = 595.28x841.89pt).
    let document = lopdf::Document::load_mem(&result.artifacts[0].bytes).unwrap();
    let (_, page_id) = document.get_pages().into_iter().next().unwrap();
    let page_dict = document.get_object(page_id).unwrap().as_dict().unwrap();
    for key in [b"MediaBox".as_slice(), b"TrimBox".as_slice(), b"BleedBox".as_slice()] {
        let values: Vec<f32> = page_dict
            .get(key)
            .unwrap()
            .as_array()
            .unwrap()
            .iter()
            .map(|value| value.as_float().unwrap())
            .collect();
        assert!((values[2] - 595.276).abs() < 0.01, "{key:?}: {values:?}");
        assert!((values[3] - 841.89).abs() < 0.01, "{key:?}: {values:?}");
    }
    assert!(
        result.artifacts[0]
            .sidecar_json
            .as_ref()
            .unwrap()
            .contains("\"slot_key\": \"contact.full_name\""),
        "flattened path must keep the sidecar contract"
    );

    let codes: Vec<&str> = result
        .diagnostics
        .iter()
        .map(|diagnostic| diagnostic.code.as_str())
        .collect();
    assert!(codes.contains(&"TESTMODE"), "renderer diagnostics must pass through: {codes:?}");
    assert!(
        !codes.contains(&"LUME0401") && !codes.contains(&"LUME0402"),
        "stub fidelity warnings must not fire on the flattened path: {codes:?}"
    );

    let calls = renderer.calls.lock().unwrap();
    assert_eq!(calls.len(), 1);
    let (page_ids, dpi, include_bleed) = &calls[0];
    assert_eq!(page_ids, &vec![PageId::from("page_a")]);
    assert_eq!(*dpi, 300, "raster: None must default to the 300 dpi print floor");
    assert!(!include_bleed);
}

#[test]
fn flattened_pdf_honors_profile_dpi_bleed_flag_and_print_guardrails() {
    let renderer = std::sync::Arc::new(RecordingPdfRenderer::default());
    let adapter = LumenExportAdapter::new().with_pdf_renderer(renderer.clone());
    let scene = scene_with_slot();

    let result = adapter
        .export(
            &scene,
            &ExportRequest {
                profile: ExportProfile {
                    name: "print_pdf_flattened".to_owned(),
                    format: ExportFormat::Pdf,
                    pdf_intent: Some(PdfIntent::Print),
                    raster: Some(RasterScale {
                        scale: 1.0,
                        dpi: Some(150),
                    }),
                    include_bleed: true,
                    embed_fonts: true,
                include_marks: false,
                imposition: None,
                proof: false,
                color: None,
                },
                page_ids: vec![PageId::from("page_a")],
                purpose: ExportPurpose::UserDownload,
            },
        )
        .unwrap();

    let calls = renderer.calls.lock().unwrap();
    let (_, dpi, include_bleed) = &calls[0];
    assert_eq!(*dpi, 150, "profile raster dpi must override the default");
    assert!(*include_bleed);

    // Print guardrails are geometry checks and still run on the flattened
    // path: page_a has no bleed rect, so the include_bleed request warns.
    assert!(result
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0412"));
}

#[test]
fn flattener_failure_maps_to_export_error_with_diagnostics() {
    let renderer = std::sync::Arc::new(RecordingPdfRenderer {
        fail: true,
        ..RecordingPdfRenderer::default()
    });
    let adapter = LumenExportAdapter::new().with_pdf_renderer(renderer);
    let scene = scene_with_slot();

    // include_bleed on a bleed-less page fires the LUME0412 guardrail
    // BEFORE the renderer runs — it must ride the error.
    let error = adapter
        .export(
            &scene,
            &ExportRequest {
                profile: ExportProfile {
                    name: "print_pdf_failing".to_owned(),
                    format: ExportFormat::Pdf,
                    pdf_intent: Some(PdfIntent::Print),
                    raster: None,
                    include_bleed: true,
                    embed_fonts: true,
                include_marks: false,
                imposition: None,
                proof: false,
                color: None,
                },
                page_ids: vec![PageId::from("page_a")],
                purpose: ExportPurpose::UserDownload,
            },
        )
        .unwrap_err();

    assert_eq!(error.code, "raster.page_missing");
    assert!(
        error
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUME0412"),
        "guardrail diagnostics collected before the failure must ride the error"
    );
}

// ---------------------------------------------------------------------------
// Print-geometry contract: the per-page margin predicate and the
// painted-vs-declared tripwire (the 2026-07-15 phantom-margin bug class).
// ---------------------------------------------------------------------------

fn print_marks_profile(name: &str) -> ExportProfile {
    ExportProfile {
        name: name.to_owned(),
        format: ExportFormat::Pdf,
        pdf_intent: Some(PdfIntent::Print),
        raster: None,
        include_bleed: true,
        embed_fonts: true,
        include_marks: true,
        imposition: None,
        proof: false,
        color: None,
    }
}

fn page_boxes_of(bytes: &[u8]) -> Vec<[Vec<f32>; 3]> {
    let document = lopdf::Document::load_mem(bytes).unwrap();
    document
        .get_pages()
        .into_iter()
        .map(|(_, page_id)| {
            let dict = document.get_object(page_id).unwrap().as_dict().unwrap();
            let read = |key: &[u8]| -> Vec<f32> {
                dict.get(key)
                    .unwrap()
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|value| value.as_float().unwrap())
                    .collect()
            };
            [read(b"MediaBox"), read(b"TrimBox"), read(b"BleedBox")]
        })
        .collect()
}

fn assert_box(actual: &[f32], expected: [f64; 4], label: &str) {
    for (index, (a, e)) in actual.iter().zip(expected).enumerate() {
        assert!(
            (f64::from(*a) - e).abs() < 0.02,
            "{label}[{index}]: expected {e:.3}, got {a:.3}"
        );
    }
}

/// The live 2026-07-15 bug: a marks request against a bleed-less page must
/// degrade to plain, HONEST trim geometry — no phantom margin, no TrimBox
/// cutting into the art — with LUME0412 still flagging the gap.
#[test]
fn print_marks_on_bleedless_page_degrade_to_exact_trim_boxes() {
    let adapter = LumenExportAdapter::new()
        .with_pdf_renderer(std::sync::Arc::new(RecordingPdfRenderer::default()));
    let scene = scene_with_slot();

    let result = adapter
        .export(
            &scene,
            &ExportRequest {
                profile: print_marks_profile("print_pdf_marks_no_bleed"),
                page_ids: vec![PageId::from("page_a")],
                purpose: ExportPurpose::UserDownload,
            },
        )
        .expect("bleed-less marks export degrades, never corrupts");

    // A4: 210x297mm = 595.276x841.890pt. All three boxes identical — the
    // page has nothing to bleed, so nothing may claim a margin.
    let boxes = page_boxes_of(&result.artifacts[0].bytes);
    let a4 = [0.0, 0.0, 595.276, 841.890];
    assert_box(&boxes[0][0], a4, "MediaBox");
    assert_box(&boxes[0][1], a4, "TrimBox");
    assert_box(&boxes[0][2], a4, "BleedBox");

    assert!(
        result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUME0412"),
        "the missing-bleed warning must still fire"
    );
}

/// Margin is a PER-PAGE decision: a mixed document gets the marks margin
/// only on pages that actually carry a bleed rect.
#[test]
fn print_margin_is_per_page_in_mixed_documents() {
    let adapter = LumenExportAdapter::new()
        .with_pdf_renderer(std::sync::Arc::new(RecordingPdfRenderer::default()));
    let mut scene = scene_with_slot();
    // page_a gets a 3mm bleed; page_b stays bleed-less.
    scene.pages.get_mut(&PageId::from("page_a")).unwrap().bleed = Some(Rect {
        x: -3.0,
        y: -3.0,
        width: 216.0,
        height: 303.0,
    });

    let result = adapter
        .export(
            &scene,
            &ExportRequest {
                profile: print_marks_profile("print_pdf_marks_mixed"),
                page_ids: vec![PageId::from("page_a"), PageId::from("page_b")],
                purpose: ExportPurpose::UserDownload,
            },
        )
        .expect("mixed-bleed export");

    let boxes = page_boxes_of(&result.artifacts[0].bytes);
    // page_a: bleed 216x303mm = 612.284x858.898pt, +14pt margin per side;
    // trim sits 3mm+14pt inside.
    assert_box(&boxes[0][0], [0.0, 0.0, 640.284, 886.898], "page_a MediaBox");
    assert_box(
        &boxes[0][1],
        [22.504, 22.504, 617.780, 864.394],
        "page_a TrimBox",
    );
    assert_box(&boxes[0][2], [14.0, 14.0, 626.284, 872.898], "page_a BleedBox");
    // page_b: plain trim, no margin.
    let a4 = [0.0, 0.0, 595.276, 841.890];
    assert_box(&boxes[1][0], a4, "page_b MediaBox");
    assert_box(&boxes[1][1], a4, "page_b TrimBox");
}

/// The tripwire: a renderer whose painted page size disagrees with the
/// declared boxes is a geometry-contract violation — the export fails
/// loudly instead of shipping a file whose TrimBox miscuts the art.
#[test]
fn geometry_tripwire_rejects_renderer_box_disagreement() {
    let adapter = LumenExportAdapter::new().with_pdf_renderer(std::sync::Arc::new(
        RecordingPdfRenderer {
            lie_about_geometry: true,
            ..RecordingPdfRenderer::default()
        },
    ));
    let scene = scene_with_slot();

    let error = adapter
        .export(
            &scene,
            &request(ExportFormat::Pdf, vec![PageId::from("page_a")]),
        )
        .unwrap_err();

    assert_eq!(error.code, "export.pdf_geometry_mismatch");
    assert!(
        error.message.contains("page_a"),
        "the offending page is named: {}",
        error.message
    );
}
