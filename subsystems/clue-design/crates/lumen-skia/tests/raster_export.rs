//! Slice A4 gates: PNG export coverage that moved here from lumen-export
//! when the resvg path was removed (lumen-export is portable and cannot
//! construct the native rasterizer), plus the critic-preview assertion that
//! preview PNGs contain real shaped text (pixel-region heuristic on the
//! Phase E fixture).

use lumen_core::{
    Color, ComputedGeometry, DiagnosticSeverity, DocumentId, ExportAdapter, ExportFormat,
    ExportProfile, ExportPurpose, ExportRequest, Fill, Node, NodeId, NodeKind, Orientation, Page,
    PageId, PagePreset, PageSize, Paint, PaintId, RasterScale, Rect, Scene, SizeSpec, TextNode,
    Transform, Unit,
};
use lumen_export::{FixtureAssetResolver, LumenExportAdapter};
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
