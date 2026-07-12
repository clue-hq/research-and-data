//! Effects Contract V0, slice X6: PDF stays solid-paint-only. A scene
//! using shadows, gradients, and dashes must export the supported subset
//! AND emit explicit LUMX matrix diagnostics — never silently wrong output.

use lumen_core::scene::ColorStop;
use lumen_core::{
    Color, DocumentId, Effect, EffectId, EffectKind, ExportAdapter, ExportFormat, ExportProfile,
    ExportPurpose, ExportRequest, Fill, Node, NodeId, NodeKind, Operation, Orientation, Page,
    PageId, PagePreset, PageSize, Paint, PaintId, ParentRef, Scene, SizeSpec, Stroke, Transform,
    Unit,
};
use lumen_export::PdfExportAdapter;

fn solid(value: &str) -> Paint {
    Paint::Solid {
        color: Color::Hex {
            value: value.to_owned(),
        },
    }
}

fn effect_scene() -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_effects_pdf"), "Effects PDF");

    let mut card = Node::new(NodeId::from("card"), NodeKind::Rect);
    card.transform = Transform {
        x: 24.0,
        y: 24.0,
        ..Transform::default()
    };
    card.size = SizeSpec::fixed(200.0, 120.0);
    card.fills = vec![Fill {
        id: PaintId::from("fill_gradient"),
        paint: Paint::LinearGradient {
            angle: 90.0,
            stops: vec![
                ColorStop {
                    color: Color::Hex {
                        value: "#ffffff".to_owned(),
                    },
                    position: 0.0,
                },
                ColorStop {
                    color: Color::Hex {
                        value: "#256c70".to_owned(),
                    },
                    position: 1.0,
                },
            ],
        },
    }];
    card.strokes = vec![Stroke {
        dash: Some(vec![6.0, 4.0]),
        ..Stroke::solid(PaintId::from("stroke_border"), solid("#111827"), 1.0)
    }];
    card.effects = vec![Effect {
        id: EffectId::from("shadow_soft"),
        kind: EffectKind::DropShadow {
            color: Color::Hex {
                value: "#000000".to_owned(),
            },
            opacity: 0.18,
            x: 0.0,
            y: 8.0,
            blur: 24.0,
            spread: 0.0,
            color_token: None,
        },
    }];

    let mut plain = Node::new(NodeId::from("plain"), NodeKind::Rect);
    plain.transform = Transform {
        x: 24.0,
        y: 170.0,
        ..Transform::default()
    };
    plain.size = SizeSpec::fixed(100.0, 40.0);
    plain.fills = vec![Fill {
        id: PaintId::from("fill_plain"),
        paint: solid("#f5f1e9"),
    }];

    scene
        .apply_operations([
            Operation::AddPage {
                page: Page {
                    id: PageId::from("page_card"),
                    name: "Card".to_owned(),
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
                    background: Vec::new(),
                },
            },
            Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_card")),
                index: 0,
                node: card,
            },
            Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_card")),
                index: 1,
                node: plain,
            },
        ])
        .unwrap();
    scene
}

#[test]
fn pdf_export_of_effect_scene_emits_lumx_verdicts_and_renders_supported_subset() {
    let scene = effect_scene();
    let request = ExportRequest {
        profile: ExportProfile {
            name: "pdf_preview".to_owned(),
            format: ExportFormat::Pdf,
            pdf_intent: None,
            raster: None,
            include_bleed: false,
            embed_fonts: false,
        include_marks: false,
        imposition: None,
        },
        page_ids: vec![PageId::from("page_card")],
        purpose: ExportPurpose::UserDownload,
    };

    let result = PdfExportAdapter::new()
        .export(&scene, &request)
        .expect("exports");

    // Explicit matrix verdicts: drop shadow and gradient paint are
    // unsupported on PDF; the dash pattern is approximated.
    let unsupported: Vec<_> = result
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.code == "LUMX0002")
        .collect();
    assert!(
        unsupported
            .iter()
            .any(|diagnostic| diagnostic.message.contains("drop shadow")),
        "{unsupported:#?}"
    );
    assert!(
        unsupported
            .iter()
            .any(|diagnostic| diagnostic.message.contains("linear gradient paint")),
        "{unsupported:#?}"
    );
    assert!(
        result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "LUMX0001"
                && diagnostic.message.contains("stroke dash pattern")),
        "{:#?}",
        result.diagnostics
    );

    // The plain solid node must not appear in any LUMX verdict.
    assert!(
        !result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.starts_with("LUMX")
                && diagnostic.message.contains("node plain")),
        "{:#?}",
        result.diagnostics
    );

    // The supported subset still renders: a parseable PDF with the solid
    // stroke and the plain solid fill present in the content stream.
    let artifact = &result.artifacts[0];
    assert_eq!(artifact.format, ExportFormat::Pdf);
    let pdf = String::from_utf8_lossy(&artifact.bytes);
    assert!(pdf.starts_with("%PDF-1.4"), "renders a PDF document");
    assert!(
        pdf.contains("0.9608 0.9451 0.9137 rg"),
        "plain solid fill renders: {pdf}"
    );
}

fn text_scene(text: lumen_core::scene::TextNode, fills: Vec<Fill>, strokes: Vec<Stroke>) -> Scene {
    let mut scene = Scene::new(DocumentId::from("doc_pdf_text"), "PDF Text");
    let mut node = Node::new(NodeId::from("t"), NodeKind::Text(text));
    node.transform = Transform { x: 24.0, y: 24.0, ..Transform::default() };
    node.size = SizeSpec::fixed(200.0, 40.0);
    node.fills = fills;
    node.strokes = strokes;
    scene
        .apply_operations([
            Operation::AddPage {
                page: Page {
                    id: PageId::from("page_card"),
                    name: "Card".to_owned(),
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
                    background: Vec::new(),
                },
            },
            Operation::InsertNode {
                parent: ParentRef::Page(PageId::from("page_card")),
                index: 0,
                node,
            },
        ])
        .unwrap();
    scene
}

fn pdf_diagnostics(scene: &Scene) -> Vec<lumen_core::Diagnostic> {
    let request = ExportRequest {
        profile: ExportProfile {
            name: "pdf_preview".to_owned(),
            format: ExportFormat::Pdf,
            pdf_intent: None,
            raster: None,
            include_bleed: false,
            embed_fonts: false,
        include_marks: false,
        imposition: None,
        },
        page_ids: vec![PageId::from("page_card")],
        purpose: ExportPurpose::UserDownload,
    };
    PdfExportAdapter::new().export(scene, &request).expect("exports").diagnostics
}

#[test]
fn pdf_degrades_text_decoration_stroke_and_multi_fill_loudly() {
    // A6a D2/D5: PDF renders none of these — but never silently.
    let scene = text_scene(
        lumen_core::scene::TextNode {
            content: "Loud".to_owned(),
            underline: true,
            strikethrough: true,
            ..lumen_core::scene::TextNode::default()
        },
        vec![
            Fill { id: PaintId::from("f1"), paint: solid("#111827") },
            Fill { id: PaintId::from("f2"), paint: solid("#256c70") },
        ],
        vec![Stroke::solid(PaintId::from("s"), solid("#ffffff"), 2.0)],
    );
    let diagnostics = pdf_diagnostics(&scene);
    for code in ["LUME0421", "LUME0422", "LUME0423"] {
        assert!(
            diagnostics.iter().any(|d| d.code == code),
            "missing {code}: {diagnostics:#?}"
        );
    }
}

#[test]
fn pdf_degrades_rich_text_spans_loudly() {
    // A6b D7: PDF renders base text only; a spanned node advises (LUME0424).
    let scene = text_scene(
        lumen_core::scene::TextNode {
            content: "one two".to_owned(),
            spans: vec![lumen_core::TextSpan {
                start: 4,
                end: 7,
                fill: Some(solid("#ff0000")),
                font_weight: Some(800),
                underline: None,
                strikethrough: None,
                italic: None,
            }],
            ..lumen_core::scene::TextNode::default()
        },
        vec![Fill { id: PaintId::from("f1"), paint: solid("#111827") }],
        vec![],
    );
    let diagnostics = pdf_diagnostics(&scene);
    assert!(
        diagnostics.iter().any(|d| d.code == "LUME0424"),
        "missing LUME0424: {diagnostics:#?}"
    );
}

#[test]
fn pdf_degrades_italic_loudly() {
    // A7b D6: PDF has no italic face (single /F1 Helvetica), so italic text —
    // block-level OR span-level — advises LUME0425 (sibling of LUME0424).
    let block_italic = text_scene(
        lumen_core::scene::TextNode {
            content: "emphasis".to_owned(),
            italic: true,
            ..lumen_core::scene::TextNode::default()
        },
        vec![Fill { id: PaintId::from("f1"), paint: solid("#111827") }],
        vec![],
    );
    let diagnostics = pdf_diagnostics(&block_italic);
    assert!(
        diagnostics.iter().any(|d| d.code == "LUME0425"),
        "block italic missing LUME0425: {diagnostics:#?}"
    );

    // Span-level italic (no block italic) also fires the advisory.
    let span_italic = text_scene(
        lumen_core::scene::TextNode {
            content: "one two".to_owned(),
            spans: vec![lumen_core::TextSpan {
                start: 4,
                end: 7,
                fill: None,
                font_weight: None,
                underline: None,
                strikethrough: None,
                italic: Some(true),
            }],
            ..lumen_core::scene::TextNode::default()
        },
        vec![Fill { id: PaintId::from("f1"), paint: solid("#111827") }],
        vec![],
    );
    assert!(
        pdf_diagnostics(&span_italic).iter().any(|d| d.code == "LUME0425"),
        "span italic missing LUME0425"
    );

    // Review fix: span(italic(false)) on an UPRIGHT block resolves every run
    // upright — exactly what PDF renders — so the advisory must NOT fire.
    let span_de_italic = text_scene(
        lumen_core::scene::TextNode {
            content: "one two".to_owned(),
            spans: vec![lumen_core::TextSpan {
                start: 4,
                end: 7,
                fill: None,
                font_weight: None,
                underline: None,
                strikethrough: None,
                italic: Some(false),
            }],
            ..lumen_core::scene::TextNode::default()
        },
        vec![Fill { id: PaintId::from("f1"), paint: solid("#111827") }],
        vec![],
    );
    assert!(
        !pdf_diagnostics(&span_de_italic).iter().any(|d| d.code == "LUME0425"),
        "italic(false) span on an upright block must not warn"
    );
}

#[test]
fn pdf_clean_text_node_emits_no_a6_advisories() {
    let scene = text_scene(
        lumen_core::scene::TextNode {
            content: "Clean".to_owned(),
            text_transform: lumen_core::TextTransform::Uppercase,
            paragraph_spacing: 4.0,
            ..lumen_core::scene::TextNode::default()
        },
        vec![Fill { id: PaintId::from("f1"), paint: solid("#111827") }],
        vec![],
    );
    let diagnostics = pdf_diagnostics(&scene);
    for code in ["LUME0421", "LUME0422", "LUME0423", "LUME0424", "LUME0425"] {
        assert!(!diagnostics.iter().any(|d| d.code == code), "{code} should not fire: {diagnostics:#?}");
    }
}
