//! Slice A4 gates: PNG export coverage that moved here from lumen-export
//! when the resvg path was removed (lumen-export is portable and cannot
//! construct the native rasterizer), plus the critic-preview assertion that
//! preview PNGs contain real shaped text (pixel-region heuristic on the
//! Phase E fixture).

use lumen_core::{
    Color, ComputedGeometry, DiagnosticSeverity, DocumentId, ExportAdapter, ExportFormat,
    ExportProfile, ExportPurpose, ExportRequest, Fill, Node, NodeId, NodeKind, Orientation, Page,
    PageId, PagePreset, PageSize, Paint, PaintId, RasterScale, Rect, Scene, SizeSpec, TextNode,
    TextSpan, Transform, Unit, VerticalAlign,
};
use lumen_export::{FixtureAssetResolver, LumenExportAdapter, PageRasterizer};
use lumen_skia::{FontManager, SkiaSceneRenderer, SkiaTextMeasurer};
use skia_safe::{surfaces, Data, Image};
use std::sync::Arc;

const PHASE_E_ASSET_FIXTURE: &str =
    include_str!("../../lumen-core/fixtures/conformance/phase_e_asset_scene.json");
const LOGO_PNG: &[u8] = include_bytes!("../../lumen-export/fixtures/assets/acme-logo-8x8-red.png");
const LOGO_DIGEST: &str = "8e5491753553a973d4e82a8ae675fdfbd6c7b06c87629d365a30c7bc659d2195";

/// Mirror of the helper's `server_export_adapter` composition (slice A4):
/// shared FontManager between measurer and rasterizer.
fn composed_adapter(adapter: LumenExportAdapter) -> LumenExportAdapter {
    let fonts = Arc::new(FontManager::bundled());
    adapter
        .with_measurer(Arc::new(SkiaTextMeasurer::new(Arc::clone(&fonts))))
        .with_rasterizer(Arc::new(SkiaSceneRenderer::new(fonts)))
}

fn png_request(page_id: &str) -> ExportRequest {
    ExportRequest {
        profile: ExportProfile {
            name: "agent_critique_preview".to_owned(),
            format: ExportFormat::Png,
            pdf_intent: None,
            raster: Some(RasterScale {
                scale: 1.0,
                dpi: Some(96),
            }),
            include_bleed: false,
            embed_fonts: true,
        include_marks: false,
        imposition: None,
        proof: false,
        color: None,
        },
        page_ids: vec![PageId::from(page_id)],
        purpose: ExportPurpose::AgentCritique,
    }
}

fn solid_fill(id: &str, value: &str) -> Fill {
    Fill {
        id: PaintId::from(id),
        paint: Paint::Solid {
            color: Color::Hex {
                value: value.to_owned(),
            },
        },
    }
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
                Orientation::Landscape
            } else {
                Orientation::Portrait
            },
            source: None,
            output: None,
        },
        children,
        bleed: None,
        safe_area: None,
        background: vec![solid_fill("paint_page_bg", "#ffffff")],
    }
}

struct Rgba {
    width: i32,
    height: i32,
    pixels: Vec<u8>,
}

impl Rgba {
    fn pixel(&self, x: i32, y: i32) -> [u8; 4] {
        let index = ((y * self.width + x) * 4) as usize;
        [
            self.pixels[index],
            self.pixels[index + 1],
            self.pixels[index + 2],
            self.pixels[index + 3],
        ]
    }
}

fn decode_rgba(png: &[u8]) -> Rgba {
    assert_eq!(&png[..8], b"\x89PNG\r\n\x1a\n");
    let image = Image::from_encoded(Data::new_copy(png)).expect("png decodes");
    let info = skia_safe::ImageInfo::new(
        (image.width(), image.height()),
        skia_safe::ColorType::RGBA8888,
        skia_safe::AlphaType::Unpremul,
        None,
    );
    let mut pixels = vec![0u8; (image.width() * image.height() * 4) as usize];
    let row_bytes = (image.width() * 4) as usize;
    let mut surface =
        surfaces::raster_n32_premul((image.width(), image.height())).expect("surface");
    surface.canvas().draw_image(&image, (0, 0), None);
    assert!(surface.image_snapshot().read_pixels(
        &info,
        &mut pixels,
        row_bytes,
        (0, 0),
        skia_safe::image::CachingHint::Disallow
    ));
    Rgba {
        width: image.width(),
        height: image.height(),
        pixels,
    }
}

// Moved from lumen-export: PNG honors non-preset custom page dimensions.
#[test]
fn png_export_honors_non_preset_custom_page_dimensions() {
    let mut scene = Scene::new(
        DocumentId::from("doc_wide_custom_export"),
        "Wide Custom Export",
    );
    scene.pages.insert(
        PageId::from("page_wide"),
        custom_px_page("page_wide", 120.0, 63.0, vec![NodeId::from("node_bg")]),
    );
    let mut node = Node::new(NodeId::from("node_bg"), NodeKind::Rect);
    node.size = SizeSpec::fixed(120.0, 63.0);
    node.fills = vec![solid_fill("paint_rect_fill", "#ffcc00")];
    scene.nodes.insert(node.id.clone(), node);

    let result = composed_adapter(LumenExportAdapter::new())
        .export(&scene, &png_request("page_wide"))
        .expect("export");
    let rgba = decode_rgba(&result.artifacts[0].bytes);

    assert_eq!(rgba.width, 120);
    assert_eq!(rgba.height, 63);
    assert_eq!(result.artifacts[0].page_id, Some(PageId::from("page_wide")));
    assert_eq!(result.artifacts[0].mime_type, "image/png");
}

// Moved from lumen-export: the rasterizer consumes computed layout
// geometry, not the raw transform.
#[test]
fn png_export_uses_computed_xy_for_layouted_nodes() {
    let mut scene = Scene::new(DocumentId::from("doc_computed_export"), "Computed Export");
    scene.pages.insert(
        PageId::from("page_square"),
        custom_px_page(
            "page_square",
            100.0,
            100.0,
            vec![NodeId::from("node_computed_rect")],
        ),
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
        text_lines: Vec::new(),
    });
    node.fills = vec![solid_fill("paint_computed_rect", "#ff0000")];
    scene.nodes.insert(node.id.clone(), node);

    let result = composed_adapter(LumenExportAdapter::new())
        .export(&scene, &png_request("page_square"))
        .expect("export");
    let rgba = decode_rgba(&result.artifacts[0].bytes);
    assert_eq!(rgba.width, 100);
    assert_eq!(rgba.pixel(25, 35), [255, 0, 0, 255]);
    assert_eq!(rgba.pixel(5, 5), [255, 255, 255, 255]);
}

// Moved from lumen-export: text rasterizes to visible pixels; an unknown
// family falls back to the default family with the LUMS0100 warning.
#[test]
fn png_export_rasterizes_text_nodes_with_font_fallback() {
    let mut scene = Scene::new(DocumentId::from("doc_png_text"), "PNG Text");
    scene.pages.insert(
        PageId::from("page_square"),
        custom_px_page("page_square", 200.0, 100.0, vec![NodeId::from("node_text")]),
    );
    let mut node = Node::new(
        NodeId::from("node_text"),
        NodeKind::Text(TextNode {
            content: "Readable PNG text".to_owned(),
            font_family: "Arial".to_owned(),
            font_size: 20.0,
            line_height: 1.1,
            font_weight: 600,
            ..TextNode::default()
        }),
    );
    node.transform = Transform {
        x: 12.0,
        y: 24.0,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(180.0, 48.0);
    node.fills = vec![solid_fill("paint_text_dark", "#111827")];
    scene.nodes.insert(node.id.clone(), node);

    let result = composed_adapter(LumenExportAdapter::new())
        .export(&scene, &png_request("page_square"))
        .expect("export");

    let rgba = decode_rgba(&result.artifacts[0].bytes);
    let dark_pixels = rgba
        .pixels
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
            .any(|diagnostic| diagnostic.code == "LUMS0100"
                && diagnostic.message.contains("Arial")),
        "unknown family must surface the fallback warning: {:?}",
        result.diagnostics
    );
}

#[test]
fn rich_span_glyph_diagnostics_follow_the_painted_face() {
    let (fonts, errors) = FontManager::bundled_with(vec![
        (include_bytes!("fixtures/subset-face.ttf").to_vec(), None),
        (include_bytes!("fixtures/subset-face-bold.ttf").to_vec(), None),
    ]);
    assert!(errors.is_empty());
    let renderer = SkiaSceneRenderer::new(Arc::new(fonts));
    let render = |base_weight, span_weight, content: &str| {
        let mut scene = Scene::new(DocumentId::from("span_glyph"), "Span glyph");
        scene.pages.insert(
            PageId::from("page"),
            custom_px_page("page", 200.0, 100.0, vec![NodeId::from("text")]),
        );
        let mut node = Node::new(
            NodeId::from("text"),
            NodeKind::Text(TextNode {
                content: content.to_owned(),
                font_family: "SubsetFace".to_owned(),
                font_size: 32.0,
                font_weight: base_weight,
                spans: vec![TextSpan {
                    start: 1,
                    end: content.len(),
                    font_weight: Some(span_weight),
                    fill: None,
                    underline: None,
                    strikethrough: None,
                    italic: None,
                }],
                ..TextNode::default()
            }),
        );
        node.size = SizeSpec::fixed(180.0, 80.0);
        node.fills = vec![solid_fill("ink", "#000000")];
        scene.nodes.insert(node.id.clone(), node);
        renderer.rasterize_page(&scene, &PageId::from("page"), 200, 100, None).unwrap()
    };
    let supplied = render(400, 700, "A\u{e123}");
    assert!(!supplied.diagnostics.iter().any(|d| d.code == "LUMS0106"), "{:?}", supplied.diagnostics);
    // The bold fixture maps U+E123 to its A outline: actual pixels must agree.
    assert_eq!(supplied.png, render(400, 700, "AA").png);
    let unresolved = render(700, 400, "A\u{e123}");
    assert!(unresolved.diagnostics.iter().any(|d| d.code == "LUMS0106" && d.message.contains("U+E123")), "{:?}", unresolved.diagnostics);
}

// Moved from lumen-export: embedded asset bytes rasterize into the image
// node's box.
#[test]
fn png_export_rasterizes_embedded_image_bytes() {
    let scene: Scene = serde_json::from_str(PHASE_E_ASSET_FIXTURE).expect("fixture parses");
    let resolver = Arc::new(FixtureAssetResolver::new().with_digest_bytes(
        LOGO_DIGEST,
        "image/png",
        LOGO_PNG.to_vec(),
    ));
    let result = composed_adapter(LumenExportAdapter::with_resolver(resolver))
        .export(&scene, &png_request("page_a4"))
        .expect("export");
    let rgba = decode_rgba(&result.artifacts[0].bytes);

    // Logo node: 24..72mm square at y 120mm on a 210mm-wide page.
    let scale = f64::from(rgba.width) / 210.0;
    let center_x = ((24.0 + 24.0) * scale) as i32;
    let center_y = ((120.0 + 24.0) * scale) as i32;
    let [r, g, b, a] = rgba.pixel(center_x, center_y);
    assert!(
        a > 200 && r > 180 && g < 90 && b < 90,
        "logo center should be the fixture's red, got ({r}, {g}, {b}, {a})"
    );
}

// Slice A4 gate: the agent-critique preview PNG contains real shaped text.
// Pixel-region heuristic on the Phase E fixture: the recipient-name text
// box must contain dark glyph pixels, and the same region rendered without
// the text node must not.
#[test]
fn critic_preview_png_contains_shaped_text() {
    let scene: Scene = serde_json::from_str(PHASE_E_ASSET_FIXTURE).expect("fixture parses");
    let resolver = Arc::new(FixtureAssetResolver::new().with_digest_bytes(
        LOGO_DIGEST,
        "image/png",
        LOGO_PNG.to_vec(),
    ));
    let result = composed_adapter(LumenExportAdapter::with_resolver(resolver))
        .export(&scene, &png_request("page_a4"))
        .expect("critic preview export");
    assert!(
        !result.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "LUME0202"
                || diagnostic.code == "LUME0210"
                || diagnostic.code == "LUME0211"
        }),
        "critic preview must not carry unresolved-asset diagnostics: {:?}",
        result.diagnostics
    );

    let rgba = decode_rgba(&result.artifacts[0].bytes);
    // Text node "Dr. Priya Sharma": 160x28mm box at (24,40)mm on a 210mm
    // page (96 dpi raster).
    let scale = f64::from(rgba.width) / 210.0;
    let (x0, y0) = ((24.0 * scale) as i32, (40.0 * scale) as i32);
    let (x1, y1) = (
        ((24.0 + 160.0) * scale) as i32,
        ((40.0 + 28.0) * scale) as i32,
    );

    let mut glyph_pixels = 0usize;
    for y in y0..y1 {
        for x in x0..x1 {
            let [r, g, b, a] = rgba.pixel(x, y);
            if a > 200 && r < 100 && g < 100 && b < 100 {
                glyph_pixels += 1;
            }
        }
    }
    assert!(
        glyph_pixels > 200,
        "critic preview must contain shaped glyph pixels in the text region, found {glyph_pixels}"
    );

    // Control: the same region is empty when the text node is removed, so
    // the heuristic is detecting glyphs, not background.
    let mut without_text = scene.clone();
    without_text
        .nodes
        .remove(&NodeId::from("node_contact_name"));
    if let Some(page) = without_text.pages.get_mut(&PageId::from("page_a4")) {
        page.children
            .retain(|child| child != &NodeId::from("node_contact_name"));
    }
    let control = composed_adapter(LumenExportAdapter::new())
        .export(&without_text, &png_request("page_a4"))
        .expect("control export");
    let control_rgba = decode_rgba(&control.artifacts[0].bytes);
    let mut control_dark = 0usize;
    for y in y0..y1 {
        for x in x0..x1 {
            let [r, g, b, a] = control_rgba.pixel(x, y);
            if a > 200 && r < 100 && g < 100 && b < 100 {
                control_dark += 1;
            }
        }
    }
    assert_eq!(control_dark, 0, "control region must contain no glyphs");
}

// Sidecar metadata survives the direct raster path.
#[test]
fn png_artifacts_carry_sidecar_with_slot_keys() {
    let scene: Scene = serde_json::from_str(PHASE_E_ASSET_FIXTURE).expect("fixture parses");
    let result = composed_adapter(LumenExportAdapter::new())
        .export(&scene, &png_request("page_a4"))
        .expect("export");
    let sidecar = result.artifacts[0]
        .sidecar_json
        .as_ref()
        .expect("sidecar present");
    assert!(sidecar.contains("\"contact.full_name\""));
}

/// A page with no children and no background must raster as blank white
/// paper, never a black frame. Regression for the archetype-baseline-sweep
/// "empty page rasterizes as a solid black 1080² frame" failure: the raster
/// surface is now cleared to opaque white paper instead of transparent
/// (which flattens to black in any viewer that composites onto black).
#[test]
fn empty_page_rasters_as_white_paper_not_black() {
    let mut scene = Scene::new(DocumentId::from("doc_empty_page"), "Empty Page");
    scene.pages.insert(
        PageId::from("page_empty"),
        Page {
            id: PageId::from("page_empty"),
            name: "Empty".to_owned(),
            size: PageSize {
                width: 128.0,
                height: 128.0,
                unit: Unit::Px,
                preset: Some(PagePreset::Custom),
                orientation: Orientation::Portrait,
                source: None,
                output: None,
            },
            children: vec![],
            bleed: None,
            safe_area: None,
            background: vec![],
        },
    );

    let result = composed_adapter(LumenExportAdapter::new())
        .export(&scene, &png_request("page_empty"))
        .expect("export");
    let rgba = decode_rgba(&result.artifacts[0].bytes);

    // Every corner and the center are opaque white — no black anywhere.
    for (x, y) in [(0, 0), (127, 0), (0, 127), (127, 127), (64, 64)] {
        assert_eq!(
            rgba.pixel(x, y),
            [255, 255, 255, 255],
            "empty page pixel ({x},{y}) must be white paper"
        );
    }
}

/// A *specified* fill that cannot resolve (unresolved brand token) must paint
/// the visible magenta sentinel AND raise the LUME0213 error — it must never
/// silently vanish into a transparent (black-reading) hole. Regression for
/// the "unresolved tokens paint black at raster" failure class.
#[test]
fn unresolved_token_fill_paints_visible_sentinel_and_errors() {
    let mut scene = Scene::new(DocumentId::from("doc_token_fill"), "Token Fill");
    scene.pages.insert(
        PageId::from("page_square"),
        // Note: empty background, so the artboard node fill is the only paper.
        Page {
            id: PageId::from("page_square"),
            name: "Square".to_owned(),
            size: PageSize {
                width: 100.0,
                height: 100.0,
                unit: Unit::Px,
                preset: Some(PagePreset::Custom),
                orientation: Orientation::Portrait,
                source: None,
                output: None,
            },
            children: vec![NodeId::from("node_artboard")],
            bleed: None,
            safe_area: None,
            background: vec![],
        },
    );
    let mut node = Node::new(NodeId::from("node_artboard"), NodeKind::Rect);
    node.size = SizeSpec::fixed(100.0, 100.0);
    node.computed = Some(ComputedGeometry {
        layout_bounds: Rect {
            x: 0.0,
            y: 0.0,
            width: 100.0,
            height: 100.0,
        },
        render_bounds: Rect {
            x: 0.0,
            y: 0.0,
            width: 100.0,
            height: 100.0,
        },
        text_lines: Vec::new(),
    });
    node.fills = vec![Fill {
        id: PaintId::from("paint_token_fill"),
        paint: Paint::Solid {
            color: Color::Token {
                token: "$surface.page".to_owned(),
            },
        },
    }];
    scene.nodes.insert(node.id.clone(), node);

    let result = composed_adapter(LumenExportAdapter::new())
        .export(&scene, &png_request("page_square"))
        .expect("export");
    let rgba = decode_rgba(&result.artifacts[0].bytes);

    // The artboard reads as the opaque magenta sentinel, not black/transparent.
    assert_eq!(
        rgba.pixel(50, 50),
        [255, 0, 255, 255],
        "unresolved fill must paint the visible magenta sentinel"
    );

    // ...and the loud LUME0213 error fires so the reviewer is never blinded.
    let sentinel_error = result.diagnostics.iter().find(|d| d.code == "LUME0213");
    let sentinel_error = sentinel_error.expect("LUME0213 error must be emitted");
    assert_eq!(sentinel_error.severity, DiagnosticSeverity::Error);
}

// A6a review gate: the raster and the measurer must agree on what text is
// visible — the PNG may never paint lines the measured geometry (and thus the
// SVG markup) cut away.

fn dark_text_pixels_in_band(rgba: &Rgba, y0: i32, y1: i32) -> usize {
    let mut count = 0;
    for y in y0..y1 {
        for x in 0..rgba.width as i32 {
            let px = rgba.pixel(x, y);
            if px[3] > 0 && px[0] < 120 && px[1] < 140 && px[2] < 160 {
                count += 1;
            }
        }
    }
    count
}

fn a6_text_node(content: &str, text: TextNode) -> Node {
    let mut node = Node::new(
        NodeId::from("node_a6_text"),
        NodeKind::Text(TextNode {
            content: content.to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 24.0,
            line_height: 1.0,
            font_weight: 400,
            ..text
        }),
    );
    node.transform = Transform {
        x: 10.0,
        y: 10.0,
        ..Transform::default()
    };
    node.fills = vec![solid_fill("paint_a6_text", "#111827")];
    node
}

#[test]
fn stacked_paragraph_raster_honors_the_total_max_lines_cut() {
    // paragraph_spacing > 0 with max_lines = 1: the measurer (and SVG) keep
    // exactly one line; the raster must not paint paragraphs 2 and 3.
    let mut scene = Scene::new(DocumentId::from("doc_a6_stack_cut"), "A6 Stack Cut");
    scene.pages.insert(
        PageId::from("page_square"),
        custom_px_page("page_square", 300.0, 200.0, vec![NodeId::from("node_a6_text")]),
    );
    let mut node = a6_text_node(
        "Alpha\nBeta\nGamma",
        TextNode {
            paragraph_spacing: 30.0,
            max_lines: Some(1),
            ..TextNode::default()
        },
    );
    node.size = SizeSpec::fixed(280.0, 180.0);
    scene.nodes.insert(node.id.clone(), node);

    let result = composed_adapter(LumenExportAdapter::new())
        .export(&scene, &png_request("page_square"))
        .expect("export");
    let rgba = decode_rgba(&result.artifacts[0].bytes);

    // Line 1 ("Alpha") paints in its band...
    assert!(
        dark_text_pixels_in_band(&rgba, 10, 40) > 10,
        "the first paragraph line must render"
    );
    // ...and NOTHING paints below it: max_lines=1 cut everything else.
    let below = dark_text_pixels_in_band(&rgba, 60, 200);
    assert_eq!(
        below, 0,
        "raster painted {below} text pixels below the max_lines cut — \
         the PNG disagrees with the measured/SVG geometry"
    );
}

#[test]
fn nowrap_truncate_never_soft_wraps_the_raster() {
    // NoWrap + truncate (no max_lines): truncation has nothing to cut, so the
    // raster must keep the pre-A6a NoWrap behavior — one natural-width line —
    // and never soft-wrap the text into the box width.
    let mut scene = Scene::new(DocumentId::from("doc_a6_nowrap_trunc"), "A6 NoWrap Truncate");
    scene.pages.insert(
        PageId::from("page_square"),
        custom_px_page("page_square", 300.0, 120.0, vec![NodeId::from("node_a6_text")]),
    );
    let mut node = a6_text_node(
        "wide open spaces keep going",
        TextNode {
            truncate: true,
            ..TextNode::default()
        },
    );
    node.size = SizeSpec::fixed(100.0, 100.0);
    scene.nodes.insert(node.id.clone(), node);

    let result = composed_adapter(LumenExportAdapter::new())
        .export(&scene, &png_request("page_square"))
        .expect("export");
    let rgba = decode_rgba(&result.artifacts[0].bytes);

    assert!(
        dark_text_pixels_in_band(&rgba, 10, 38) > 10,
        "the single NoWrap line must render"
    );
    let wrapped = dark_text_pixels_in_band(&rgba, 44, 120);
    assert_eq!(
        wrapped, 0,
        "raster painted {wrapped} text pixels below the first line — \
         NoWrap text was soft-wrapped at the box width"
    );
}


// ---- A7a vertical alignment (D3) -----------------------------------------

/// Mean y of the dark text pixels — the vertical centroid of painted glyphs.
/// Returns `None` when nothing dark was painted.
fn dark_text_mean_y(rgba: &Rgba) -> Option<f64> {
    let mut sum = 0.0f64;
    let mut count = 0.0f64;
    for y in 0..rgba.height as i32 {
        for x in 0..rgba.width as i32 {
            let px = rgba.pixel(x, y);
            if px[3] > 0 && px[0] < 120 && px[1] < 140 && px[2] < 160 {
                sum += f64::from(y);
                count += 1.0;
            }
        }
    }
    (count > 0.0).then(|| sum / count)
}

/// Render one text node into a 300x200 page and return the decoded raster.
fn render_valign_scene(doc: &str, node: Node) -> Rgba {
    let mut scene = Scene::new(DocumentId::from(doc), "Valign");
    scene.pages.insert(
        PageId::from("page_square"),
        custom_px_page("page_square", 300.0, 200.0, vec![node.id.clone()]),
    );
    scene.nodes.insert(node.id.clone(), node);
    let result = composed_adapter(LumenExportAdapter::new())
        .export(&scene, &png_request("page_square"))
        .expect("export");
    decode_rgba(&result.artifacts[0].bytes)
}

/// A single short line in a tall Fixed-height box at page top, given valign.
fn valign_fast_node(valign: VerticalAlign) -> Node {
    let mut node = a6_text_node(
        "Hi",
        TextNode {
            valign,
            ..TextNode::default()
        },
    );
    node.transform.y = 0.0;
    node.size = SizeSpec::fixed(280.0, 200.0);
    node
}

#[test]
fn fast_path_valign_shifts_the_line_down_the_box() {
    // top < center < bottom: the same short line paints progressively lower as
    // valign moves through the box's vertical slack.
    let top = dark_text_mean_y(&render_valign_scene(
        "doc_valign_top",
        valign_fast_node(VerticalAlign::Top),
    ))
    .expect("top text paints");
    let center = dark_text_mean_y(&render_valign_scene(
        "doc_valign_center",
        valign_fast_node(VerticalAlign::Center),
    ))
    .expect("center text paints");
    let bottom = dark_text_mean_y(&render_valign_scene(
        "doc_valign_bottom",
        valign_fast_node(VerticalAlign::Bottom),
    ))
    .expect("bottom text paints");

    assert!(top < 40.0, "top-aligned line should sit near the box top, got {top}");
    assert!(
        (center - 100.0).abs() < 30.0,
        "center-aligned line should sit near the box middle (~100), got {center}"
    );
    assert!(
        bottom > 160.0,
        "bottom-aligned line should sit near the box bottom (~200), got {bottom}"
    );
    assert!(
        top < center && center < bottom,
        "valign ordering violated: top={top} center={center} bottom={bottom}"
    );
}

#[test]
fn stacked_path_valign_shifts_the_whole_stack() {
    // paragraph_spacing > 0 with a \n break exercises the stacked path; center
    // must push the entire two-paragraph stack down vs top.
    let stacked = |doc: &str, valign: VerticalAlign| -> f64 {
        let mut node = a6_text_node(
            "Alpha\nBeta",
            TextNode {
                paragraph_spacing: 24.0,
                valign,
                ..TextNode::default()
            },
        );
        node.transform.y = 0.0;
        node.size = SizeSpec::fixed(280.0, 200.0);
        dark_text_mean_y(&render_valign_scene(doc, node)).expect("stack paints")
    };
    let top = stacked("doc_valign_stack_top", VerticalAlign::Top);
    let center = stacked("doc_valign_stack_center", VerticalAlign::Center);
    assert!(
        center > top + 20.0,
        "center stack should sit well below the top stack: top={top} center={center}"
    );
}

#[test]
fn spanned_path_valign_shifts_the_segmented_paragraph() {
    // A span activates the segmented paragraph path; valign must shift it too.
    let spanned = |doc: &str, valign: VerticalAlign| -> f64 {
        let mut node = a6_text_node(
            "AB",
            TextNode {
                valign,
                spans: vec![TextSpan {
                    start: 0,
                    end: 1,
                    fill: None,
                    font_weight: Some(800),
                    underline: None,
                    strikethrough: None,
                    italic: None,
                }],
                ..TextNode::default()
            },
        );
        node.transform.y = 0.0;
        node.size = SizeSpec::fixed(280.0, 200.0);
        dark_text_mean_y(&render_valign_scene(doc, node)).expect("span paints")
    };
    let top = spanned("doc_valign_span_top", VerticalAlign::Top);
    let bottom = spanned("doc_valign_span_bottom", VerticalAlign::Bottom);
    assert!(
        bottom > top + 40.0,
        "bottom-aligned spanned text should sit far below top: top={top} bottom={bottom}"
    );
}

#[test]
fn valign_offset_clamps_to_zero_when_content_overflows() {
    // D3: an overflowing box has no slack, so bottom valign is a no-op — text
    // still paints from the box top, never shifted above or below it.
    let mut node = a6_text_node(
        "Hi",
        TextNode {
            valign: VerticalAlign::Bottom,
            ..TextNode::default()
        },
    );
    node.transform.y = 0.0;
    node.size = SizeSpec::fixed(280.0, 18.0); // shorter than the ~24px line
    let rgba = render_valign_scene("doc_valign_overflow", node);
    let mean = dark_text_mean_y(&rgba).expect("overflowing text still paints");
    assert!(
        mean < 30.0,
        "overflow-clamped bottom valign must paint from the top (offset 0), got {mean}"
    );
}

#[test]
fn stacked_valign_bottom_with_max_lines_cut_excludes_the_trailing_gap() {
    // A7a adversarial-review Finding 1: paragraph_spacing > 0 with a max_lines
    // cut that drops trailing paragraphs. The painted content is Alpha (24px)
    // + gap (40px) + Beta (24px) = 88px in a 200px box, so bottom valign must
    // put the glyph bottoms at ~200. Counting a trailing gap after Beta (the
    // pre-fix behavior) inflated the total to 128px and left the text a full
    // gap (40px) higher than SVG/PDF, whose measured.height is the last
    // visible line's bottom.
    let mut node = a6_text_node(
        "Alpha\nBeta\nGamma",
        TextNode {
            paragraph_spacing: 40.0,
            max_lines: Some(2),
            valign: VerticalAlign::Bottom,
            ..TextNode::default()
        },
    );
    node.transform.y = 0.0;
    node.size = SizeSpec::fixed(280.0, 200.0);
    let rgba = render_valign_scene("doc_valign_stack_cut", node);
    let mut lowest = None;
    for y in 0..rgba.height as i32 {
        for x in 0..rgba.width as i32 {
            let px = rgba.pixel(x, y);
            if px[3] > 0 && px[0] < 120 && px[1] < 140 && px[2] < 160 {
                lowest = Some(y);
            }
        }
    }
    let lowest = f64::from(lowest.expect("stacked text paints"));
    assert!(
        lowest >= 185.0,
        "bottom-valigned cut stack must reach the box bottom (~200); \
         got lowest dark pixel {lowest} (a trailing-gap total would sit ~160)"
    );
}

// ---- A7b block italic renders with the italic face -----------------------

/// An export adapter whose shared FontManager carries the bundled set plus
/// Instrument Serif upright + italic, so an italic request reaches a real
/// italic face in BOTH the measurer and the rasterizer.
fn instrument_adapter() -> LumenExportAdapter {
    let dir =
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures");
    let upright = std::fs::read(dir.join("instrument-serif-regular.ttf"))
        .expect("instrument-serif-regular fixture reads");
    let italic = std::fs::read(dir.join("instrument-serif-italic.ttf"))
        .expect("instrument-serif-italic fixture reads");
    let (manager, errors) =
        FontManager::bundled_with(vec![(upright, None), (italic, None)]);
    assert!(errors.is_empty(), "{errors:?}");
    let fonts = Arc::new(manager);
    LumenExportAdapter::new()
        .with_measurer(Arc::new(SkiaTextMeasurer::new(Arc::clone(&fonts))))
        .with_rasterizer(Arc::new(SkiaSceneRenderer::new(fonts)))
}

fn render_instrument_italic(doc: &str, italic: bool) -> Rgba {
    let mut node = Node::new(
        NodeId::from("node_italic"),
        NodeKind::Text(TextNode {
            content: "Editorial voice".to_owned(),
            font_family: "Instrument Serif".to_owned(),
            font_size: 40.0,
            line_height: 1.0,
            font_weight: 400,
            italic,
            ..TextNode::default()
        }),
    );
    node.transform = Transform {
        x: 10.0,
        y: 60.0,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(380.0, 80.0);
    node.fills = vec![solid_fill("paint_italic", "#111827")];

    let mut scene = Scene::new(DocumentId::from(doc), "Italic");
    scene.pages.insert(
        PageId::from("page_square"),
        custom_px_page("page_square", 400.0, 200.0, vec![node.id.clone()]),
    );
    scene.nodes.insert(node.id.clone(), node);
    let result = instrument_adapter()
        .export(&scene, &png_request("page_square"))
        .expect("export");
    decode_rgba(&result.artifacts[0].bytes)
}

fn dark_pixel_count(rgba: &Rgba) -> usize {
    let mut count = 0;
    for y in 0..rgba.height as i32 {
        for x in 0..rgba.width as i32 {
            let px = rgba.pixel(x, y);
            if px[3] > 0 && px[0] < 120 && px[1] < 140 && px[2] < 160 {
                count += 1;
            }
        }
    }
    count
}

#[test]
fn block_italic_renders_different_pixels_than_upright() {
    // With a real italic face loaded, painting the SAME content as italic
    // shears/reshapes every glyph, so the raster differs from the upright one.
    // A pixel-diff proves italic reached the shaper's face selection in render.
    let upright = render_instrument_italic("doc_italic_upright", false);
    let italic = render_instrument_italic("doc_italic_on", true);
    assert_eq!((upright.width, upright.height), (italic.width, italic.height));

    let upright_dark = dark_pixel_count(&upright);
    let italic_dark = dark_pixel_count(&italic);
    assert!(upright_dark > 100, "upright text must paint: {upright_dark}");
    assert!(italic_dark > 100, "italic text must paint: {italic_dark}");

    // Count positionally-differing pixels — italic glyph shapes land elsewhere.
    let mut differing = 0usize;
    for y in 0..upright.height {
        for x in 0..upright.width {
            if upright.pixel(x, y) != italic.pixel(x, y) {
                differing += 1;
            }
        }
    }
    assert!(
        differing > 200,
        "block italic must change the raster vs upright, differing pixels = {differing}"
    );
}

// ---- A7b D2 synthesis gate (adversarial-gate finding, pixel-proven) -------

/// SkParagraph applies a SYNTHETIC oblique for an unsatisfiable italic slant;
/// the D2 gate must refuse to request it, so a family with NO italic face
/// renders byte-identical to the upright request (plus LUMS0105 advising).
#[test]
fn missing_italic_face_renders_upright_not_synthetic_oblique() {
    let node = |italic: bool| {
        let mut node = a6_text_node(
            "Verdant fields",
            TextNode {
                italic,
                ..TextNode::default()
            },
        );
        node.transform.y = 0.0;
        node.size = SizeSpec::fixed(280.0, 60.0);
        node
    };
    // Bundled Inter has no italic face.
    let italic = render_valign_scene("doc_it_gate_italic", node(true));
    let upright = render_valign_scene("doc_it_gate_upright", node(false));
    assert_eq!(
        (italic.width, italic.height),
        (upright.width, upright.height)
    );
    let differing = italic
        .pixels
        .iter()
        .zip(upright.pixels.iter())
        .filter(|(a, b)| a != b)
        .count();
    assert_eq!(
        differing, 0,
        "italic request with no italic face must render byte-identical to \
         upright (no synthetic oblique); {differing} pixels differ"
    );
}
// The real-italic-face counterpart is `block_italic_renders_different_pixels_
// than_upright` above (instrument_adapter): the gate blocks only synthesis.

/// A7b D2 gate, SVG side: `font-style="italic"` is emitted ONLY when the
/// family has a real italic face (through the shaping measurer's
/// `has_italic_face`) — otherwise the raster renders upright (LUMS0105) and an
/// italic attr would make every SVG viewer synthesize the fake oblique the
/// raster refused. Instrument Serif (real italic fixture) emits it; Inter
/// (bundled, upright-only) must not.
#[test]
fn svg_font_style_is_gated_on_a_real_italic_face() {
    let svg_request = ExportRequest {
        profile: ExportProfile {
            name: "svg_gate".to_owned(),
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
        page_ids: vec![PageId::from("page_square")],
        purpose: ExportPurpose::AgentCritique,
    };
    let render = |family: &str, doc: &str| {
        let mut node = Node::new(
            NodeId::from("node_svg_it"),
            NodeKind::Text(TextNode {
                content: "Editorial voice".to_owned(),
                font_family: family.to_owned(),
                font_size: 40.0,
                line_height: 1.0,
                font_weight: 400,
                italic: true,
                ..TextNode::default()
            }),
        );
        node.transform = Transform { x: 10.0, y: 60.0, ..Transform::default() };
        node.size = SizeSpec::fixed(380.0, 80.0);
        node.fills = vec![solid_fill("paint_svg_it", "#111827")];
        let mut scene = Scene::new(DocumentId::from(doc), "SvgItalicGate");
        scene.pages.insert(
            PageId::from("page_square"),
            custom_px_page("page_square", 400.0, 200.0, vec![node.id.clone()]),
        );
        scene.nodes.insert(node.id.clone(), node);
        let result = instrument_adapter()
            .export(&scene, &svg_request)
            .expect("svg export");
        String::from_utf8(result.artifacts[0].bytes.clone()).expect("utf8 svg")
    };
    let with_face = render("Instrument Serif", "doc_svg_it_face");
    assert!(
        with_face.contains("font-style=\"italic\""),
        "a real italic face must emit font-style: {with_face}"
    );
    let without_face = render("Inter", "doc_svg_it_noface");
    assert!(
        !without_face.contains("font-style"),
        "no italic face -> no font-style attr (the raster renders upright): {without_face}"
    );
}
