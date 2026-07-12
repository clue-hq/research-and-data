//! Print W2 gates: the vector Skia-PDF renderer — live text with embedded
//! subset fonts, bleed page boxes, determinism, and the seam impl.

use lumen_core::{
    Color, ComputedGeometry, DocumentId, Fill, Node, NodeId, NodeKind, Orientation, Page, PageId,
    PagePreset, PageSize, Paint, PaintId, Rect, Scene, SizeSpec, TextAlign, TextNode, Transform,
    Unit,
};
use lumen_export::ScenePdfRenderer;
use lumen_skia::{vector_pdf, SkiaSceneRenderer, SkiaVectorPdfRenderer};
use std::sync::Arc;

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

/// 200×150pt page: dark background, Inter text node, optional bleed rect.
fn text_scene(bleed: Option<Rect>) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_vector_pdf"), "Vector PDF");
    scene.pages.insert(
        PageId::from("page_vector"),
        Page {
            id: PageId::from("page_vector"),
            name: "Vector".to_owned(),
            size: PageSize {
                width: 200.0,
                height: 150.0,
                unit: Unit::Pt,
                preset: Some(PagePreset::Custom),
                orientation: Orientation::Landscape,
                source: None,
                output: None,
            },
            children: vec![NodeId::from("node_headline")],
            bleed,
            safe_area: None,
            background: vec![solid_fill("paint_page_bg", "#12355b")],
        },
    );
    let mut node = Node::new(
        NodeId::from("node_headline"),
        NodeKind::Text(TextNode {
            content: "Vector text stays live".to_owned(),
            font_family: "Inter".to_owned(),
            font_size: 16.0,
            font_weight: 700,
            align: TextAlign::Left,
            ..TextNode::default()
        }),
    );
    node.transform = Transform {
        x: 20.0,
        y: 30.0,
        ..Transform::default()
    };
    node.size = SizeSpec::fixed(160.0, 40.0);
    node.computed = Some(ComputedGeometry {
        layout_bounds: Rect {
            x: 20.0,
            y: 30.0,
            width: 160.0,
            height: 40.0,
        },
        render_bounds: Rect {
            x: 20.0,
            y: 30.0,
            width: 160.0,
            height: 40.0,
        },
    });
    node.fills = vec![solid_fill("paint_headline", "#ffffff")];
    scene.nodes.insert(node.id.clone(), node);
    scene
}

#[test]
fn vector_pdf_embeds_subset_fonts_and_stays_deterministic() {
    let renderer = SkiaSceneRenderer::bundled();
    let scene = text_scene(None);

    let first = vector_pdf(&renderer, &scene, &[], 300, false, None).expect("vector pdf");
    assert!(first.bytes.starts_with(b"%PDF"));
    assert_eq!(first.pages[0].width_pt, 200.0);
    assert_eq!(first.pages[0].height_pt, 150.0);

    let raw = String::from_utf8_lossy(&first.bytes);
    // Live text with an embedded TrueType font program: the font descriptor
    // carries FontFile2 and the subset BaseFont references Inter.
    assert!(raw.contains("FontFile2"), "no embedded font program");
    assert!(raw.contains("Inter"), "font name missing from the PDF");

    assert!(first
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0427"));

    let second = vector_pdf(&renderer, &scene, &[], 300, false, None).expect("vector pdf 2");
    assert_eq!(first.bytes, second.bytes, "vector PDF must be deterministic");
}

#[test]
fn vector_pdf_expands_page_box_to_bleed() {
    let renderer = SkiaSceneRenderer::bundled();
    let bleed = Some(Rect {
        x: -9.0,
        y: -9.0,
        width: 218.0,
        height: 168.0,
    });
    let scene = text_scene(bleed);

    let trimmed = vector_pdf(&renderer, &scene, &[], 300, false, None).expect("trim pdf");
    assert_eq!(trimmed.pages[0].width_pt, 200.0);

    let bled = vector_pdf(&renderer, &scene, &[], 300, true, None).expect("bleed pdf");
    assert_eq!(bled.pages[0].width_pt, 218.0);
    assert_eq!(bled.pages[0].height_pt, 168.0);
    let raw = String::from_utf8_lossy(&bled.bytes);
    // Skia quantizes the raw page box to the raster_dpi grid (218pt →
    // 217.92 at 300dpi; 168 divides evenly and stays exact). The exact
    // boxes are restored by lumen-export's post-process — asserted at the
    // adapter level; here we pin the quantization behavior itself so a
    // Skia upgrade changing it is caught.
    assert!(
        raw.contains("/MediaBox [0 0 217.92 168]"),
        "expected dpi-grid-quantized bleed MediaBox"
    );
}

// End-to-end L2+L3 through the real adapter: vector renderer + bleed →
// content painted to the bleed extent AND exact boxes written by the
// post-process (overriding Skia's dpi-grid-quantized MediaBox).
#[test]
fn adapter_export_writes_exact_print_boxes_over_vector_pdf() {
    use lumen_core::{
        ExportAdapter, ExportFormat, ExportProfile, ExportPurpose, ExportRequest, PdfIntent,
        RasterScale,
    };
    use lumen_export::LumenExportAdapter;

    let bleed = Some(Rect {
        x: -9.0,
        y: -9.0,
        width: 218.0,
        height: 168.0,
    });
    let scene = text_scene(bleed);
    let adapter = LumenExportAdapter::new().with_pdf_renderer(Arc::new(
        SkiaVectorPdfRenderer::new(Arc::new(lumen_skia::FontManager::bundled())),
    ));

    let result = adapter
        .export(
            &scene,
            &ExportRequest {
                profile: ExportProfile {
                    name: "print_pdf".to_owned(),
                    format: ExportFormat::Pdf,
                    pdf_intent: Some(PdfIntent::Print),
                    raster: Some(RasterScale {
                        scale: 1.0,
                        dpi: Some(300),
                    }),
                    include_bleed: true,
                    embed_fonts: true,
                },
                page_ids: vec![PageId::from("page_vector")],
                purpose: ExportPurpose::UserDownload,
            },
        )
        .expect("vector export");

    let document = lopdf::Document::load_mem(&result.artifacts[0].bytes).unwrap();
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
    // Exact geometry restored by the post-process — NOT 217.92.
    assert_eq!(boxes(b"MediaBox"), vec![0.0, 0.0, 218.0, 168.0]);
    assert_eq!(boxes(b"BleedBox"), vec![0.0, 0.0, 218.0, 168.0]);
    assert_eq!(boxes(b"TrimBox"), vec![9.0, 9.0, 209.0, 159.0]);

    assert!(result
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUME0427"));
}

#[test]
fn vector_renderer_implements_the_scene_pdf_seam() {
    let scene = text_scene(None);
    let via_seam = SkiaVectorPdfRenderer::new(Arc::new(lumen_skia::FontManager::bundled()))
        .render_pdf(&scene, &[PageId::from("page_vector")], 300, false, None)
        .expect("seam render");
    let direct = vector_pdf(
        &SkiaSceneRenderer::bundled(),
        &scene,
        &[PageId::from("page_vector")],
        300,
        false,
        None,
    )
    .expect("direct render");
    assert_eq!(via_seam.bytes, direct.bytes);
}
