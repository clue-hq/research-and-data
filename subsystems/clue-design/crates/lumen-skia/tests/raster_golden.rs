//! Slice A3 gates: golden PNGs for the direct scene→Skia rasterizer with a
//! pixel-diff harness (CPU backend pinned), plus the one-time
//! resvg-vs-skia comparison report (env-gated; emitted once for review
//! before resvg removal at A4).
//!
//! Regenerate goldens intentionally with:
//! `UPDATE_SKIA_GOLDENS=1 cargo test -p lumen-skia --test raster_golden`

use lumen_core::{
    DocumentId, ExportAdapter, ExportFormat, ExportProfile, ExportPurpose, ExportRequest, Fill,
    Node, NodeId, NodeKind, Operation, Orientation, Page, PageId, PagePreset, PageSize, Paint,
    PaintId, ParentRef, RasterScale, Scene, SizeSpec, TextAlign, TextNode, TextWrap, Transform,
    Unit,
};
use lumen_export::{FixtureAssetResolver, LumenExportAdapter, PageRasterizer, SvgExportAdapter};
use lumen_skia::{SkiaSceneRenderer, SkiaTextMeasurer};
use skia_safe::{surfaces, Data, Image};
use std::path::PathBuf;
use std::sync::Arc;

const EFFECTS_CARD_FIXTURE: &str =
    include_str!("../../lumen-core/fixtures/effects/effects_card.json");
const A4_EFFECTS_FIXTURE: &str = include_str!("../../lumen-core/fixtures/effects/a4_effects.json");
const PHASE_E_ASSET_FIXTURE: &str =
    include_str!("../../lumen-core/fixtures/conformance/phase_e_asset_scene.json");
const LOGO_PNG: &[u8] = include_bytes!("../../lumen-export/fixtures/assets/acme-logo-8x8-red.png");
const LOGO_DIGEST: &str = "8e5491753553a973d4e82a8ae675fdfbd6c7b06c87629d365a30c7bc659d2195";

/// Max per-channel delta tolerated before a pixel counts as different.
const CHANNEL_TOLERANCE: i32 = 2;

fn goldens_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/goldens")
}

fn solid(value: &str) -> Paint {
    Paint::Solid {
        color: lumen_core::Color::Hex {
            value: value.to_owned(),
        },
    }
}

fn fill(id: &str, value: &str) -> Fill {
    Fill {
        id: PaintId::from(id),
        paint: solid(value),
    }
}

/// Text fixture covering the raster text modes: wrap + hard breaks,
/// NoWrap center/right anchoring, letter spacing, weights, multibyte.
fn text_wrap_scene() -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_text_wrap"), "Text Wrap");
    scene
        .apply_operations([Operation::AddPage {
            page: Page {
                id: PageId::from("page_text"),
                name: "Text".to_owned(),
                size: PageSize {
                    width: 400.0,
                    height: 300.0,
                    unit: Unit::Px,
                    preset: Some(PagePreset::Custom),
                    orientation: Orientation::Landscape,
                    source: None,
                    output: None,
                },
                children: Vec::new(),
                bleed: None,
                safe_area: None,
                background: vec![fill("paint_page_bg", "#faf7f0")],
            },
        }])
        .expect("page");

    let mut title = Node::new(
        NodeId::from("node_title"),
        NodeKind::Text(TextNode {
            content: "Brilliant layouts demand honest measurement".to_owned(),
            font_size: 24.0,
            font_weight: 700,
            wrap: TextWrap::Wrap,
            line_height: 1.3,
            ..TextNode::default()
        }),
    );
    title.transform = Transform {
        x: 20.0,
        y: 20.0,
        ..Transform::default()
    };
    title.size = SizeSpec::fixed(360.0, 100.0);
    title.fills = vec![fill("fill_title", "#111827")];

    let mut centered = Node::new(
        NodeId::from("node_centered"),
        NodeKind::Text(TextNode {
            content: "Centered line".to_owned(),
            font_size: 18.0,
            font_weight: 600,
            align: TextAlign::Center,
            wrap: TextWrap::NoWrap,
            ..TextNode::default()
        }),
    );
    centered.transform = Transform {
        x: 20.0,
        y: 140.0,
        ..Transform::default()
    };
    centered.size = SizeSpec::fixed(360.0, 30.0);
    centered.fills = vec![fill("fill_centered", "#256c70")];

    let mut tracked = Node::new(
        NodeId::from("node_tracked"),
        NodeKind::Text(TextNode {
            content: "Right + tracked".to_owned(),
            font_size: 16.0,
            font_weight: 400,
            align: TextAlign::Right,
            letter_spacing: 2.0,
            wrap: TextWrap::NoWrap,
            ..TextNode::default()
        }),
    );
    tracked.transform = Transform {
        x: 20.0,
        y: 185.0,
        ..Transform::default()
    };
    tracked.size = SizeSpec::fixed(360.0, 26.0);
    tracked.fills = vec![fill("fill_tracked", "#7a4b12")];

    let mut multibyte = Node::new(
        NodeId::from("node_multibyte"),
        NodeKind::Text(TextNode {
            content: "Türkçe ölçüm 🦀 hard\\nbreak".to_owned(),
            font_size: 16.0,
            font_weight: 800,
            wrap: TextWrap::NoWrap,
            line_height: 1.4,
            ..TextNode::default()
        }),
    );
    multibyte.transform = Transform {
        x: 20.0,
        y: 225.0,
        ..Transform::default()
    };
    multibyte.size = SizeSpec::fixed(360.0, 60.0);
    multibyte.fills = vec![fill("fill_multibyte", "#3d2c8d")];

    let parent = ParentRef::Page(PageId::from("page_text"));
    scene
        .apply_operations([
            Operation::InsertNode {
                parent: parent.clone(),
                index: 0,
                node: title,
            },
            Operation::InsertNode {
                parent: parent.clone(),
                index: 1,
                node: centered,
            },
            Operation::InsertNode {
                parent: parent.clone(),
                index: 2,
                node: tracked,
            },
            Operation::InsertNode {
                parent,
                index: 3,
                node: multibyte,
            },
        ])
        .expect("text nodes insert");
    scene
}

fn logo_resolver() -> Arc<FixtureAssetResolver> {
    Arc::new(FixtureAssetResolver::new().with_digest_bytes(
        LOGO_DIGEST,
        "image/png",
        LOGO_PNG.to_vec(),
    ))
}

fn png_request(page_id: &str) -> ExportRequest {
    ExportRequest {
        profile: ExportProfile {
            name: "skia_raster_golden".to_owned(),
            format: ExportFormat::Png,
            pdf_intent: None,
            raster: Some(RasterScale {
                scale: 1.0,
                dpi: Some(96),
            }),
            include_bleed: false,
            embed_fonts: true,
        include_marks: false,
        },
        page_ids: vec![PageId::from(page_id)],
        purpose: ExportPurpose::AgentCritique,
    }
}

fn skia_adapter(with_assets: bool) -> LumenExportAdapter {
    let adapter = if with_assets {
        LumenExportAdapter::with_resolver(logo_resolver())
    } else {
        LumenExportAdapter::new()
    };
    adapter
        .with_measurer(Arc::new(SkiaTextMeasurer::bundled()))
        .with_rasterizer(Arc::new(SkiaSceneRenderer::bundled()))
}

fn resvg_adapter(with_assets: bool) -> LumenExportAdapter {
    let adapter = if with_assets {
        LumenExportAdapter::with_resolver(logo_resolver())
    } else {
        LumenExportAdapter::new()
    };
    adapter.with_measurer(Arc::new(SkiaTextMeasurer::bundled()))
}

fn export_png(adapter: &LumenExportAdapter, scene: &Scene, page_id: &str) -> Vec<u8> {
    let result = adapter
        .export(scene, &png_request(page_id))
        .expect("png export succeeds");
    assert_eq!(result.artifacts.len(), 1);
    result.artifacts[0].bytes.clone()
}

struct Rgba {
    width: i32,
    height: i32,
    pixels: Vec<u8>,
}

impl Rgba {
    fn color_at(&self, x: i32, y: i32) -> (u8, u8, u8, u8) {
        let index = ((y * self.width + x) * 4) as usize;
        (
            self.pixels[index],
            self.pixels[index + 1],
            self.pixels[index + 2],
            self.pixels[index + 3],
        )
    }
}

/// Decode PNG bytes to straight RGBA through Skia (CPU surface).
fn decode_rgba(png: &[u8]) -> Rgba {
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
    assert!(
        surface.image_snapshot().read_pixels(
            &info,
            &mut pixels,
            row_bytes,
            (0, 0),
            skia_safe::image::CachingHint::Disallow
        ),
        "read_pixels succeeds"
    );
    Rgba {
        width: image.width(),
        height: image.height(),
        pixels,
    }
}

struct DiffStats {
    total: usize,
    differing: usize,
    max_delta: i32,
    mean_delta: f64,
}

fn diff_stats(left: &Rgba, right: &Rgba) -> DiffStats {
    assert_eq!((left.width, left.height), (right.width, right.height));
    let total = (left.width * left.height) as usize;
    let mut differing = 0usize;
    let mut max_delta = 0i32;
    let mut delta_sum = 0u64;
    for (l, r) in left.pixels.iter().zip(right.pixels.iter()) {
        let delta = (i32::from(*l) - i32::from(*r)).abs();
        max_delta = max_delta.max(delta);
        delta_sum += delta as u64;
    }
    for index in 0..total {
        let offset = index * 4;
        let pixel_differs = (0..4).any(|channel| {
            let delta = i32::from(left.pixels[offset + channel])
                - i32::from(right.pixels[offset + channel]);
            delta.abs() > CHANNEL_TOLERANCE
        });
        if pixel_differs {
            differing += 1;
        }
    }
    DiffStats {
        total,
        differing,
        max_delta,
        mean_delta: delta_sum as f64 / (total as f64 * 4.0),
    }
}

fn assert_golden(name: &str, png: &[u8]) {
    let path = goldens_dir().join(format!("{name}.png"));
    if std::env::var("UPDATE_SKIA_GOLDENS").is_ok() {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, png).unwrap();
        return;
    }
    let expected = std::fs::read(&path)
        .unwrap_or_else(|_| panic!("missing golden {path:?}; run with UPDATE_SKIA_GOLDENS=1"));
    let actual_rgba = decode_rgba(png);
    let expected_rgba = decode_rgba(&expected);
    let stats = diff_stats(&actual_rgba, &expected_rgba);
    assert_eq!(
        stats.differing, 0,
        "golden {name} drifted: {}/{} pixels differ (max channel delta {}); regenerate intentionally with UPDATE_SKIA_GOLDENS=1",
        stats.differing, stats.total, stats.max_delta
    );
}

#[test]
fn golden_effects_card() {
    let scene: Scene = serde_json::from_str(EFFECTS_CARD_FIXTURE).expect("fixture parses");
    let png = export_png(&skia_adapter(false), &scene, "page_effects_card");
    assert_golden("effects_card", &png);
}

#[test]
fn golden_a4_effects() {
    // A4 effects trio: glow + layer blur + inner shadow on a per-corner rect,
    // plus a bleed(true) off-canvas wash the page clips.
    let scene: Scene = serde_json::from_str(A4_EFFECTS_FIXTURE).expect("fixture parses");
    let png = export_png(&skia_adapter(false), &scene, "page_a4_effects");
    assert_golden("a4_effects", &png);
}

#[test]
fn golden_text_wrap() {
    let scene = text_wrap_scene();
    let png = export_png(&skia_adapter(false), &scene, "page_text");
    assert_golden("text_wrap", &png);
}

#[test]
fn golden_phase_e_asset_scene() {
    let scene: Scene = serde_json::from_str(PHASE_E_ASSET_FIXTURE).expect("fixture parses");
    let png = export_png(&skia_adapter(true), &scene, "page_a4");
    assert_golden("phase_e_asset_scene", &png);
}

#[test]
fn skia_raster_is_deterministic() {
    let scene: Scene = serde_json::from_str(EFFECTS_CARD_FIXTURE).expect("fixture parses");
    let first = export_png(&skia_adapter(false), &scene, "page_effects_card");
    let second = export_png(&skia_adapter(false), &scene, "page_effects_card");
    assert_eq!(first, second, "same scene must produce identical PNG bytes");
}

#[test]
fn skia_raster_paints_resolved_asset_pixels() {
    // Independent of goldens: the logo region must contain the fixture's
    // red pixels and the export must carry no unresolved-asset diagnostics.
    let scene: Scene = serde_json::from_str(PHASE_E_ASSET_FIXTURE).expect("fixture parses");
    let result = skia_adapter(true)
        .export(&scene, &png_request("page_a4"))
        .expect("export");
    assert!(
        !result.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "LUME0202"
                || diagnostic.code == "LUME0210"
                || diagnostic.code == "LUME0211"
        }),
        "no unresolved-asset diagnostics: {:?}",
        result.diagnostics
    );

    let rgba = decode_rgba(&result.artifacts[0].bytes);
    let mut red_pixels = 0usize;
    for y in 0..rgba.height {
        for x in 0..rgba.width {
            let (r, g, b, a) = rgba.color_at(x, y);
            if a > 200 && r > 180 && g < 90 && b < 90 {
                red_pixels += 1;
            }
        }
    }
    assert!(
        red_pixels > 100,
        "expected the red logo to cover pixels, found {red_pixels}"
    );
}

#[test]
fn rasterizer_reports_missing_page() {
    let scene = text_wrap_scene();
    let renderer = SkiaSceneRenderer::bundled();
    let error = renderer
        .rasterize_page(&scene, &PageId::from("page_missing"), 100, 100, None)
        .expect_err("missing page errors");
    assert_eq!(error.code, "raster.page_missing");
}

/// One-time resvg-vs-skia comparison (plan slice A3): renders the three
/// fixtures through both PNG paths and writes a review report. Run with:
/// `EMIT_RESVG_SKIA_DIFF=1 cargo test -p lumen-skia --test raster_golden -- diff_report`
#[test]
fn diff_report_resvg_vs_skia() {
    if std::env::var("EMIT_RESVG_SKIA_DIFF").is_err() {
        return;
    }

    let mut report = String::from(
        "# resvg vs Skia raster diff (slice A3, one-time review artifact)\n\n\
         Date: 2026-06-13. Generated by `EMIT_RESVG_SKIA_DIFF=1 cargo test -p \
         lumen-skia --test raster_golden -- diff_report`.\n\n\
         Both paths use Skia text measurement (line breaks identical); pixel \
         differences come from the renderers themselves: resvg rasterizes the \
         SVG markup string with system-font text rendering, Skia paints the \
         scene directly with the bundled Inter faces.\n\n\
         | fixture | size | differing pixels | % | max channel delta | mean channel delta |\n\
         | --- | --- | --- | --- | --- | --- |\n",
    );

    let cases: Vec<(&str, Scene, &str, bool)> = vec![
        (
            "effects_card",
            serde_json::from_str(EFFECTS_CARD_FIXTURE).expect("fixture"),
            "page_effects_card",
            false,
        ),
        ("text_wrap", text_wrap_scene(), "page_text", false),
        (
            "phase_e_asset_scene",
            serde_json::from_str(PHASE_E_ASSET_FIXTURE).expect("fixture"),
            "page_a4",
            true,
        ),
    ];

    for (name, scene, page_id, with_assets) in cases {
        let skia_png = export_png(&skia_adapter(with_assets), &scene, page_id);
        let resvg_png = export_png(&resvg_adapter(with_assets), &scene, page_id);
        let skia_rgba = decode_rgba(&skia_png);
        let resvg_rgba = decode_rgba(&resvg_png);
        let stats = diff_stats(&skia_rgba, &resvg_rgba);
        report.push_str(&format!(
            "| {name} | {}x{} | {}/{} | {:.2}% | {} | {:.3} |\n",
            skia_rgba.width,
            skia_rgba.height,
            stats.differing,
            stats.total,
            stats.differing as f64 * 100.0 / stats.total as f64,
            stats.max_delta,
            stats.mean_delta,
        ));
    }

    report.push_str(
        "\nReview notes:\n\n\
         - Text-bearing fixtures are EXPECTED to differ: resvg renders text \
         through system font lookup (whatever the host resolves for \
         \"Inter\"), while Skia paints the bundled deterministic faces. The \
         Skia output is the contract going forward.\n\
         - Shape-only differences (effects card) bound the paint-translation \
         drift: gradients, shadows, dashes, and corner geometry.\n\
         - resvg and its path are removed at slice A4 after this review.\n",
    );

    let path =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../docs/resvg-vs-skia-diff-a3.md");
    std::fs::write(&path, report).expect("report written");
    println!("report written to {path:?}");
}

/// A clean stacking scene (no bleed wash) for pixel-robust probes: a solid
/// card with layer blur + glow + drop shadow + inner shadow on a white page.
const STACKING_SCENE: &str = r##"{
  "assets": {},
  "export_profiles": [],
  "meta": {"artifact_type": "card", "brand_kit": null, "id": "doc_stack",
    "medium": "digital", "status": {"kind": "draft"}, "title": "Stack"},
  "nodes": {
    "card": {
      "children": [], "clip": false, "computed": null,
      "corner": {"bottom_left": 0.0, "bottom_right": 0.0, "top_left": 0.0, "top_right": 0.0},
      "effects": [
        {"id": "g", "kind": {"kind": "glow", "color": {"kind": "hex", "value": "#a020f0"},
          "opacity": 0.95, "blur": 14.0, "spread": 6.0}},
        {"id": "lb", "kind": {"kind": "layer_blur", "radius": 2.0}},
        {"id": "ds", "kind": {"kind": "drop_shadow", "color": {"kind": "hex", "value": "#000000"},
          "opacity": 0.5, "x": 0.0, "y": 14.0, "blur": 8.0, "spread": 0.0}},
        {"id": "is", "kind": {"kind": "inner_shadow", "color": {"kind": "hex", "value": "#000000"},
          "opacity": 0.85, "x": 0.0, "y": 12.0, "blur": 10.0, "spread": 0.0}}
      ],
      "fills": [{"id": "f", "paint": {"color": {"kind": "hex", "value": "#3366ff"}, "kind": "solid"}}],
      "id": "card", "kind": {"kind": "rect"}, "layout": null, "locked": false, "name": null,
      "opacity": 1.0,
      "size": {"height": {"kind": "fixed", "value": 120.0}, "width": {"kind": "fixed", "value": 120.0}},
      "strokes": [],
      "transform": {"flip_x": false, "flip_y": false, "rotation": 0.0, "skew_x": 0.0, "skew_y": 0.0, "x": 90.0, "y": 80.0}
    }
  },
  "pages": {
    "page_stack": {
      "background": [{"id": "bg", "paint": {"color": {"kind": "hex", "value": "#ffffff"}, "kind": "solid"}}],
      "bleed": null, "children": ["card"], "id": "page_stack", "name": "Stack", "safe_area": null,
      "size": {"height": 300.0, "orientation": "landscape", "preset": "custom", "unit": "px", "width": 300.0}
    }
  },
  "schema_version": 1, "slots": {}
}"##;

fn luma(rgba: &Rgba, x: i32, y: i32) -> f64 {
    let w = 300;
    let o = ((y * w + x) * 4) as usize;
    0.299 * rgba.pixels[o] as f64
        + 0.587 * rgba.pixels[o + 1] as f64
        + 0.114 * rgba.pixels[o + 2] as f64
}

#[test]
fn effects_stacking_contract_agrees_svg_and_skia() {
    // ONE scene exercising layer blur + glow + drop shadow + inner shadow.
    // The D1 contract: source -> layer blurs -> shadow/glow beneath the
    // blurred result -> inner shadows over it. This test pins that BOTH the
    // SVG filter order and the Skia pixel stacking follow that order.
    let scene: Scene = serde_json::from_str(STACKING_SCENE).expect("stacking scene parses");

    // --- SVG side: filter primitives and merge nodes in D1 order. ---
    let svg_result = SvgExportAdapter::new()
        .export(
            &scene,
            &ExportRequest {
                profile: ExportProfile {
                    name: "svg".to_owned(),
                    format: ExportFormat::Svg,
                    pdf_intent: None,
                    raster: None,
                    include_bleed: false,
                    embed_fonts: false,
                include_marks: false,
                },
                page_ids: vec![PageId::from("page_stack")],
                purpose: ExportPurpose::UserDownload,
            },
        )
        .expect("svg export");
    let svg = String::from_utf8(svg_result.artifacts[0].bytes.clone()).unwrap();
    let lba = svg.find("result=\"lumen-lba-0\"").expect("blurred alpha");
    let outer = svg.find("result=\"lumen-outer-0\"").expect("outer effect");
    let inner = svg.find("result=\"lumen-inner-0\"").expect("inner effect");
    let merge = svg.find("<feMerge>").expect("feMerge");
    assert!(lba < outer && outer < inner && inner < merge, "SVG D1 order: {svg}");
    let mb = &svg[merge..];
    assert!(
        mb.find("in=\"lumen-outer-0\"").unwrap()
            < mb.find("in=\"lumen-lb-0\"").unwrap()
            && mb.find("in=\"lumen-lb-0\"").unwrap() < mb.find("in=\"lumen-inner-0\"").unwrap(),
        "SVG merge is outer -> base -> inner: {svg}"
    );

    // --- Skia side: pixel evidence the same order composed. ---
    let png = export_png(&skia_adapter(false), &scene, "page_stack");
    let rgba = decode_rgba(&png);
    // Card box: x[90..210], y[80..200], center x=150.
    // 1. Glow/shadow render BENEATH the card: a pixel just left of the card
    //    (in the glow band) is tinted, not the plain white background.
    let glow_band = luma(&rgba, 82, 140);
    let far_bg = luma(&rgba, 10, 10);
    assert!(
        far_bg > 250.0,
        "background stays white far from the card (luma {far_bg})"
    );
    assert!(
        glow_band < far_bg - 8.0,
        "glow/shadow renders beneath the card, tinting outside it (band {glow_band} vs bg {far_bg})"
    );
    // 2. Inner shadow renders OVER the card, clipped to it: with a +y offset it
    //    darkens the TOP interior more than the bottom interior.
    let top_interior = luma(&rgba, 150, 92);
    let bottom_interior = luma(&rgba, 150, 188);
    assert!(
        top_interior < bottom_interior - 6.0,
        "inner shadow darkens the top interior (top {top_interior} vs bottom {bottom_interior})"
    );
}
