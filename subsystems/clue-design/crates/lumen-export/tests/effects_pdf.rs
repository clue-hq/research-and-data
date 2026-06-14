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
