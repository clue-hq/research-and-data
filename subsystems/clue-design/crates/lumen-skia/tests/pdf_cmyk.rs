//! Print W5 stage B gates: CMYK conversion through the real adapter.
//!
//! The load-bearing claims: black text separates to pure K (the classic
//! fuzzy-text bug stays dead), colored fills separate to a real CMYK mix
//! through the target ICC, the print-intent gate holds, exact print boxes
//! survive the Ghostscript round-trip, the OutputIntent names the press
//! profile, and the converted bytes stay deterministic.
//!
//! Ink measurements use Ghostscript's `inkcov` device on the produced
//! PDF — per-plate coverage fractions, the mechanical form of "no CMY
//! under black text". Tests skip (loudly) when `gs` is not installed,
//! same convention as the veraPDF structural gate.

use lumen_core::{
    Color, ComputedGeometry, DocumentId, ExportAdapter, ExportFormat, ExportProfile,
    ExportPurpose, ExportRequest, Fill, Node, NodeId, NodeKind, Orientation, Page, PageId,
    PagePreset, PageSize, Paint, PaintId, PdfIntent, RasterScale, Rect, Scene, SizeSpec,
    TextAlign, TextNode, Transform, Unit,
};
use lumen_export::LumenExportAdapter;
use lumen_skia::SkiaVectorPdfRenderer;
use std::process::Command;
use std::sync::Arc;

fn ghostscript_available() -> bool {
    Command::new("gs")
        .arg("--version")
        .output()
        .is_ok_and(|output| output.status.success())
}

macro_rules! require_ghostscript {
    () => {
        if !ghostscript_available() {
            eprintln!("SKIP: gs not installed; CMYK conversion untested on this machine");
            return;
        }
    };
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

/// 200×150pt page. `background` colors the page; when `text_color` is
/// given, one Inter text node paints in that color.
fn scene_with(background: &str, text_color: Option<&str>) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_cmyk"), "CMYK Export");
    let children = if text_color.is_some() {
        vec![NodeId::from("node_text")]
    } else {
        Vec::new()
    };
    scene.pages.insert(
        PageId::from("page_cmyk"),
        Page {
            id: PageId::from("page_cmyk"),
            name: "CMYK".to_owned(),
            size: PageSize {
                width: 200.0,
                height: 150.0,
                unit: Unit::Pt,
                preset: Some(PagePreset::Custom),
                orientation: Orientation::Landscape,
                source: None,
                output: None,
            },
            children,
            bleed: None,
            safe_area: None,
            background: vec![solid_fill("paint_page_bg", background)],
        },
    );
    if let Some(color) = text_color {
        let mut node = Node::new(
            NodeId::from("node_text"),
            NodeKind::Text(TextNode {
                content: "Pure K text survives the press".to_owned(),
                font_family: "Inter".to_owned(),
                font_size: 18.0,
                font_weight: 700,
                align: TextAlign::Left,
                ..TextNode::default()
            }),
        );
        node.transform = Transform {
            x: 20.0,
            y: 40.0,
            ..Transform::default()
        };
        node.size = SizeSpec::fixed(160.0, 60.0);
        node.computed = Some(ComputedGeometry {
            layout_bounds: Rect {
                x: 20.0,
                y: 40.0,
                width: 160.0,
                height: 60.0,
            },
            render_bounds: Rect {
                x: 20.0,
                y: 40.0,
                width: 160.0,
                height: 60.0,
            },
            text_lines: Vec::new(),
        });
        node.fills = vec![solid_fill("paint_text", color)];
        scene.nodes.insert(node.id.clone(), node);
    }
    scene
}

fn print_profile(color: Option<&str>, intent: PdfIntent) -> ExportProfile {
    ExportProfile {
        name: "cmyk_test_pdf".to_owned(),
        format: ExportFormat::Pdf,
        pdf_intent: Some(intent),
        raster: Some(RasterScale {
            scale: 1.0,
            dpi: Some(300),
        }),
        include_bleed: false,
        embed_fonts: true,
        include_marks: false,
        imposition: None,
        proof: false,
        color: color.map(str::to_owned),
    }
}

fn export_pdf(scene: &Scene, profile: ExportProfile) -> Result<Vec<u8>, lumen_core::ExportError> {
    let adapter = LumenExportAdapter::new().with_pdf_renderer(Arc::new(
        SkiaVectorPdfRenderer::new(Arc::new(lumen_skia::FontManager::bundled())),
    ));
    adapter
        .export(
            scene,
            &ExportRequest {
                profile,
                page_ids: vec![PageId::from("page_cmyk")],
                purpose: ExportPurpose::UserDownload,
            },
        )
        .map(|result| result.artifacts[0].bytes.clone())
}

/// Per-plate ink coverage fractions [C, M, Y, K] of page 1, via the
/// Ghostscript `inkcov` device.
fn ink_coverage(pdf: &[u8]) -> [f64; 4] {
    use std::sync::atomic::{AtomicU64, Ordering};
    static SEQ: AtomicU64 = AtomicU64::new(0);
    let dir = std::env::temp_dir().join(format!(
        "lumen-inkcov-{}-{}",
        std::process::id(),
        SEQ.fetch_add(1, Ordering::Relaxed)
    ));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("cov.pdf");
    std::fs::write(&path, pdf).unwrap();
    let output = Command::new("gs")
        .args(["-dSAFER", "-dBATCH", "-dNOPAUSE", "-dQUIET", "-sDEVICE=inkcov", "-o", "-"])
        .arg(&path)
        .output()
        .expect("gs inkcov");
    let _ = std::fs::remove_dir_all(&dir);
    let stdout = String::from_utf8_lossy(&output.stdout);
    let line = stdout
        .lines()
        .find(|line| line.contains("CMYK"))
        .unwrap_or_else(|| panic!("no inkcov line in: {stdout}"));
    let values: Vec<f64> = line
        .split_whitespace()
        .take(4)
        .map(|token| token.parse().expect("coverage fraction"))
        .collect();
    [values[0], values[1], values[2], values[3]]
}

#[test]
fn cmyk_black_text_separates_to_pure_k() {
    require_ghostscript!();
    // White page, pure-black text: after conversion the ONLY ink on the
    // page must be K — any C/M/Y here is the fuzzy-text bug resurfacing.
    let scene = scene_with("#ffffff", Some("#000000"));
    let pdf = export_pdf(&scene, print_profile(Some("cmyk"), PdfIntent::Print)).expect("export");
    let [c, m, y, k] = ink_coverage(&pdf);
    assert!(k > 0.001, "black text must lay down K ink (got K={k})");
    assert!(
        c < 0.0005 && m < 0.0005 && y < 0.0005,
        "black text must be pure K, found CMY buildup (C={c} M={m} Y={y})"
    );
}

#[test]
fn cmyk_colored_fill_separates_to_a_rich_mix() {
    require_ghostscript!();
    // Navy page: a real ICC separation puts down cyan and magenta (and
    // some K) — a naive channel swap or a failed conversion would not.
    let scene = scene_with("#12355b", None);
    let pdf = export_pdf(&scene, print_profile(Some("cmyk"), PdfIntent::Print)).expect("export");
    let [c, m, _y, k] = ink_coverage(&pdf);
    assert!(
        c > 0.1 && m > 0.05 && k > 0.01,
        "navy fill should separate to a CMYK mix (C={c} M={m} K={k})"
    );
}

#[test]
fn cmyk_colored_text_stays_chromatic() {
    require_ghostscript!();
    // Red text on white: black preservation must be per-paint, never
    // blanket. (Ghostscript's -dBlackText flag forces ALL text to K —
    // measured live during this slice — which is why the K-purity
    // mechanism is our achromatic-paint normalization instead.)
    let scene = scene_with("#ffffff", Some("#d92626"));
    let pdf = export_pdf(&scene, print_profile(Some("cmyk"), PdfIntent::Print)).expect("export");
    let [_c, m, y, _k] = ink_coverage(&pdf);
    assert!(
        m > 0.001 && y > 0.001,
        "red text must keep magenta/yellow ink after conversion (M={m} Y={y})"
    );
}

#[test]
fn cmyk_export_keeps_exact_print_boxes_and_declares_the_press_profile() {
    require_ghostscript!();
    let mut scene = scene_with("#12355b", Some("#ffffff"));
    scene
        .pages
        .get_mut(&PageId::from("page_cmyk"))
        .unwrap()
        .bleed = Some(Rect {
        x: -9.0,
        y: -9.0,
        width: 218.0,
        height: 168.0,
    });
    let mut profile = print_profile(Some("cmyk"), PdfIntent::Print);
    profile.include_bleed = true;
    let pdf = export_pdf(&scene, profile).expect("export");

    let document = lopdf::Document::load_mem(&pdf).unwrap();
    let (_, page_id) = document.get_pages().into_iter().next().unwrap();
    let page_dict = document.get_object(page_id).unwrap().as_dict().unwrap();
    let boxes = |key: &[u8]| -> Vec<f32> {
        page_dict
            .get(key)
            .unwrap()
            .as_array()
            .unwrap()
            .iter()
            .map(|value| value.as_float().unwrap())
            .collect()
    };
    // L3 must survive the Ghostscript round-trip: exact scene geometry,
    // not whatever pdfwrite kept.
    assert_eq!(boxes(b"MediaBox"), vec![0.0, 0.0, 218.0, 168.0]);
    assert_eq!(boxes(b"BleedBox"), vec![0.0, 0.0, 218.0, 168.0]);
    assert_eq!(boxes(b"TrimBox"), vec![9.0, 9.0, 209.0, 159.0]);

    // The OutputIntent names the press condition and embeds a 4-component
    // profile — the file declares exactly what it was separated for.
    let catalog = document.catalog().unwrap();
    let intents = catalog.get(b"OutputIntents").unwrap().as_array().unwrap();
    assert_eq!(intents.len(), 1);
    let intent = document
        .get_object(intents[0].as_reference().unwrap())
        .unwrap()
        .as_dict()
        .unwrap();
    let condition = String::from_utf8_lossy(
        intent
            .get(b"OutputConditionIdentifier")
            .unwrap()
            .as_str()
            .unwrap(),
    )
    .into_owned();
    assert!(!condition.is_empty());
    assert_ne!(condition, "sRGB IEC61966-2.1", "CMYK export must not claim sRGB");
    let profile_stream = document
        .get_object(intent.get(b"DestOutputProfile").unwrap().as_reference().unwrap())
        .unwrap()
        .as_stream()
        .unwrap();
    assert_eq!(profile_stream.dict.get(b"N").unwrap().as_i64().unwrap(), 4);
}

#[test]
fn cmyk_export_is_deterministic() {
    require_ghostscript!();
    let scene = scene_with("#12355b", Some("#ffffff"));
    let profile = print_profile(Some("cmyk"), PdfIntent::Print);
    let first = export_pdf(&scene, profile.clone()).expect("export 1");
    let second = export_pdf(&scene, profile).expect("export 2");
    assert_eq!(first, second, "CMYK export must stay byte-deterministic");
}

#[test]
fn cmyk_on_preview_intent_fails_loudly_through_the_adapter() {
    // No Ghostscript needed: the gate fires before dependency resolution.
    let scene = scene_with("#ffffff", Some("#000000"));
    let error =
        export_pdf(&scene, print_profile(Some("cmyk"), PdfIntent::Preview)).unwrap_err();
    assert_eq!(error.code, "export.cmyk_requires_print_intent");
}

#[test]
fn cmyk_export_announces_the_conversion() {
    require_ghostscript!();
    let scene = scene_with("#ffffff", Some("#000000"));
    let adapter = LumenExportAdapter::new().with_pdf_renderer(Arc::new(
        SkiaVectorPdfRenderer::new(Arc::new(lumen_skia::FontManager::bundled())),
    ));
    let result = adapter
        .export(
            &scene,
            &ExportRequest {
                profile: print_profile(Some("cmyk"), PdfIntent::Print),
                page_ids: vec![PageId::from("page_cmyk")],
                purpose: ExportPurpose::UserDownload,
            },
        )
        .expect("export");
    assert!(
        result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUME0432"),
        "CMYK conversion must declare itself (LUME0432)"
    );
    // Print-intent exports keep their preflight report through the stage.
    assert!(result.print_ready.is_some());
}
