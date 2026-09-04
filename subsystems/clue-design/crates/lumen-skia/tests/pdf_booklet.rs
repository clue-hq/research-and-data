//! Print W4 gates: booklet imposition through the real adapter — sheet
//! count/order, derived sheet geometry, boxes, and declarations.

use lumen_core::{
    Color, ComputedGeometry, DocumentId, ExportAdapter, ExportFormat, ExportProfile,
    ExportPurpose, ExportRequest, Fill, Node, NodeId, NodeKind, Orientation, Page, PageId,
    PagePreset, PageSize, Paint, PaintId, PdfIntent, RasterScale, Rect, Scene, SizeSpec,
    Transform, Unit,
};
use lumen_export::LumenExportAdapter;
use lumen_skia::SkiaVectorPdfRenderer;
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

/// N pages of 432x576pt (6x8in) with distinct background colors.
fn brochure_scene(page_count: usize) -> Scene {
    let colors = ["#dc2626", "#f59e0b", "#16a34a", "#2563eb", "#7c3aed", "#0f172a"];
    let mut scene = Scene::new(DocumentId::from("doc_booklet"), "Booklet");
    for index in 0..page_count {
        let page_id = PageId::from(format!("page_{}", index + 1));
        let node_id = NodeId::from(format!("node_marker_{}", index + 1));
        scene.pages.insert(
            page_id.clone(),
            Page {
                id: page_id,
                name: format!("Page {}", index + 1),
                size: PageSize {
                    width: 432.0,
                    height: 576.0,
                    unit: Unit::Pt,
                    preset: Some(PagePreset::Custom),
                    orientation: Orientation::Portrait,
                    source: None,
                    output: None,
                },
                children: vec![node_id.clone()],
                bleed: None,
                safe_area: None,
                background: vec![solid_fill(
                    &format!("paint_bg_{index}"),
                    colors[index % colors.len()],
                )],
            },
        );
        let mut node = Node::new(node_id, NodeKind::Rect);
        node.transform = Transform {
            x: 40.0,
            y: 40.0,
            ..Transform::default()
        };
        node.size = SizeSpec::fixed(80.0, 80.0);
        node.computed = Some(ComputedGeometry {
            layout_bounds: Rect {
                x: 40.0,
                y: 40.0,
                width: 80.0,
                height: 80.0,
            },
            render_bounds: Rect {
                x: 40.0,
                y: 40.0,
                width: 80.0,
                height: 80.0,
            },
            text_lines: Vec::new(),
        });
        node.fills = vec![solid_fill(&format!("paint_marker_{index}"), "#ffffff")];
        scene.nodes.insert(node.id.clone(), node);
    }
    scene
}

fn booklet_request(page_count: usize) -> ExportRequest {
    ExportRequest {
        profile: ExportProfile {
            name: "booklet_pdf".to_owned(),
            format: ExportFormat::Pdf,
            pdf_intent: Some(PdfIntent::Print),
            raster: Some(RasterScale {
                scale: 1.0,
                dpi: Some(150),
            }),
            include_bleed: true,
            embed_fonts: true,
            include_marks: true,
            imposition: Some("booklet".to_owned()),
            proof: false,
            color: None,
        },
        page_ids: (0..page_count)
            .map(|index| PageId::from(format!("page_{}", index + 1)))
            .collect(),
        purpose: ExportPurpose::UserDownload,
    }
}

fn vector_adapter() -> LumenExportAdapter {
    LumenExportAdapter::new().with_pdf_renderer(Arc::new(SkiaVectorPdfRenderer::new(
        Arc::new(lumen_skia::FontManager::bundled()),
    )))
}

#[test]
fn four_pager_imposes_onto_one_duplex_sheet() {
    let scene = brochure_scene(4);
    let result = vector_adapter()
        .export(&scene, &booklet_request(4))
        .expect("booklet export");

    let document = lopdf::Document::load_mem(&result.artifacts[0].bytes).unwrap();
    // One physical sheet = 2 PDF pages (front + back).
    assert_eq!(document.get_pages().len(), 2);

    // Derived sheet geometry: 2x page width — 6x8in pages → 12x8in sheet.
    for (_, page_id) in document.get_pages() {
        let page_dict = document.get_object(page_id).unwrap().as_dict().unwrap();
        let media: Vec<f32> = page_dict
            .get(b"MediaBox")
            .unwrap()
            .as_array()
            .unwrap()
            .iter()
            .map(|value| value.as_float().unwrap())
            .collect();
        assert_eq!(media, vec![0.0, 0.0, 864.0, 576.0]);
        // Imposed sheets: trim = bleed = media (no bleed/marks in v1).
        let trim: Vec<f32> = page_dict
            .get(b"TrimBox")
            .unwrap()
            .as_array()
            .unwrap()
            .iter()
            .map(|value| value.as_float().unwrap())
            .collect();
        assert_eq!(trim, media);
    }

    let codes: Vec<&str> = result
        .diagnostics
        .iter()
        .map(|diagnostic| diagnostic.code.as_str())
        .collect();
    assert!(codes.contains(&"LUME0428"), "imposition advice missing: {codes:?}");
    assert!(
        codes.contains(&"LUME0430"),
        "bleed/marks-skipped advice missing (both were requested): {codes:?}"
    );
    assert!(codes.contains(&"LUME0427"), "vector mode advice missing: {codes:?}");
}

#[test]
fn six_pages_pad_to_two_sheets_and_declare_blanks() {
    let scene = brochure_scene(6);
    let result = vector_adapter()
        .export(&scene, &booklet_request(6))
        .expect("booklet export");
    let document = lopdf::Document::load_mem(&result.artifacts[0].bytes).unwrap();
    assert_eq!(document.get_pages().len(), 4); // 2 sheets x 2 sides
    let advice = result
        .diagnostics
        .iter()
        .find(|diagnostic| diagnostic.code == "LUME0428")
        .expect("imposition advice");
    assert!(advice.message.contains("+2 trailing blank"), "{}", advice.message);
}

#[test]
fn unknown_imposition_mode_fails_loudly() {
    let scene = brochure_scene(4);
    let mut request = booklet_request(4);
    request.profile.imposition = Some("work-and-turn".to_owned());
    let error = vector_adapter().export(&scene, &request).unwrap_err();
    assert_eq!(error.code, "export.imposition_unknown");
}

#[test]
fn mixed_page_sizes_reject_imposition() {
    let mut scene = brochure_scene(4);
    scene
        .pages
        .get_mut(&PageId::from("page_2"))
        .unwrap()
        .size
        .width = 500.0;
    let error = vector_adapter()
        .export(&scene, &booklet_request(4))
        .unwrap_err();
    assert_eq!(error.code, "export.imposition_mixed_sizes");
}

#[test]
fn booklet_is_deterministic() {
    let scene = brochure_scene(4);
    let first = vector_adapter()
        .export(&scene, &booklet_request(4))
        .expect("export 1");
    let second = vector_adapter()
        .export(&scene, &booklet_request(4))
        .expect("export 2");
    assert_eq!(first.artifacts[0].bytes, second.artifacts[0].bytes);
}
